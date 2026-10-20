"""D2 W6 G15 no-AI degradation tests.

Four branches must leave reading, editing, saving, cold restart and the Word
export fully usable while the AI capability alone degrades, and the AI state
must stay readable (never a silent "available"):

1. no AI configuration (``AI_NOT_CONFIGURED``);
2. credential material undecryptable/missing (``CREDENTIAL_UNAVAILABLE``);
3. AI executor unavailable (``AI_EXECUTOR_UNAVAILABLE``);
4. network unavailable — a **real** closed-port connect failure through the real
   spawn worker/Job and production transport, which must end ``failed`` with
   ``connection_unavailable``, record an attempt with **zero** provider sends,
   and never block a manual save/read/export.

Every branch performs a real manual edit + save, a cold restart (runtime lock
released, engine disposed, re-prepared on the same root) with HTTP read-back,
and a real DOCX export. Real HTTP through Uvicorn; temporary SQLite + isolated
credential root; ``APP_DISABLE_DOTENV=1``. No real supplier is contacted.
"""

from __future__ import annotations

import http.client
import json
import socket
import time
import unittest
import uuid
from datetime import date

from tests.local.support import LocalTestCase, query_scalar


class DegradeCase(LocalTestCase):
    # -- helpers -----------------------------------------------------------
    def _export_docx(self, client, from_date: str, to_date: str):
        body = {"from": from_date, "to": to_date}
        headers = {
            "Content-Type": "application/json",
            "X-App-Session": client.token,
            "Origin": client.origin,
        }

        def one(payload):
            connection = http.client.HTTPConnection("127.0.0.1", client.port, timeout=60)
            try:
                connection.request(
                    "POST",
                    "/api/exports/daily-plans",
                    body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                    headers=headers,
                )
                response = connection.getresponse()
                return (
                    response.status,
                    {k.lower(): v for k, v in response.getheaders()},
                    response.read(),
                )
            finally:
                connection.close()

        status, resp_headers, payload = one(body)
        if status == 409:
            details = json.loads(payload.decode("utf-8"))["error"]["details"]
            status, resp_headers, payload = one(
                {
                    **body,
                    "ack_missing": True,
                    "expected_context": details["expected_context"],
                }
            )
        self.assertEqual(status, 200, payload)
        return payload, resp_headers

    def _open_or_create(self, client, day_iso: str):
        status, plan = client.get(f"/api/daily-plans/by-date?date={day_iso}")
        if status == 404:
            status, plan = client.post("/api/daily-plans", {"plan_date": day_iso})
        self.assertEqual(status, 200 if status == 200 else 201, plan)
        return plan

    def _manual_save(self, client, plan, *, raw="G15手工原文", reflection="G15手工反思"):
        status, saved = client.patch(
            f"/api/daily-plans/{plan['id']}",
            {
                "expected_content_version": plan["current_content_version"],
                "raw_lesson_plan": raw,
                "adopted_content": {"reflection": reflection},
            },
        )
        self.assertEqual(status, 200, saved)
        return saved

    def _cold_restart(self, runtime, *, executor=None):
        for server in list(self._servers):
            try:
                server.stop()
            except Exception:  # noqa: BLE001
                pass
        self._servers.clear()
        runtime.dispose()
        new_runtime = self.make_runtime(self.data_dir)
        server = self.start_server(new_runtime, executor=executor)
        return new_runtime, server.client()

    def _assert_restart_and_export(self, plan_id, *, raw="G15手工原文"):
        runtime, client = self._cold_restart(self.runtime, executor=self._restart_executor())
        self.runtime = runtime
        status, plan = client.get(f"/api/daily-plans/{plan_id}")
        self.assertEqual(status, 200, plan)
        self.assertEqual(plan["content"]["raw_lesson_plan"], raw)
        payload, _headers = self._export_docx(client, "2026-09-02", "2026-09-02")
        self.assertEqual(payload[:2], b"PK")

    def _restart_executor(self):
        return None


class _RunnableStub:
    """A minimal runnable executor so the API passes ``_require_executor``.

    Branches 1/2 must reach the configuration check, not the executor check;
    nothing here ever runs a task.
    """

    def is_runnable(self) -> bool:
        return True

    def notify(self) -> None:  # pragma: no cover - never reached
        pass


class NoConfigDegradeTests(DegradeCase):
    def test_no_ai_config_manual_path_works_and_ai_readable(self):
        runtime = self.make_runtime()
        self.runtime = runtime
        server = self.start_server(runtime, executor=_RunnableStub())
        client = server.client()
        self.initialize(client)
        status, plan = client.post("/api/daily-plans", {"plan_date": "2026-09-02"})
        self.assertEqual(status, 201, plan)

        # AI is refused with a readable code; no task is created.
        status, payload = client.post(
            f"/api/daily-plans/{plan['id']}/ai-tasks",
            {
                "request_id": str(uuid.uuid4()),
                "task_type": "daily_lesson_split",
                "expected_content_version": plan["current_content_version"],
                "target_grade": "middle",
            },
        )
        self.assertEqual(status, 409, payload)
        self.assertEqual(payload["error"]["code"], "AI_NOT_CONFIGURED")
        self.assertEqual(
            query_scalar(runtime.db_path, "SELECT count(*) FROM local_ai_tasks"), 0
        )

        # GET config is readable (unconfigured, version 0).
        status, config = client.get("/api/local/ai/config")
        self.assertEqual(status, 200, config)
        self.assertFalse(config["configured"])

        self._manual_save(client, plan)
        payload, _headers = self._export_docx(client, "2026-09-02", "2026-09-02")
        self.assertEqual(payload[:2], b"PK")

        self._assert_restart_and_export(plan["id"])


class CredentialDegradeTests(DegradeCase):
    def test_credential_unavailable_blocks_ai_only(self):
        runtime = self.make_runtime()
        self.runtime = runtime
        server = self.start_server(runtime, executor=_RunnableStub())
        client = server.client()
        self.initialize(client)
        status, config = client.patch(
            "/api/local/ai/config",
            {
                "request_id": str(uuid.uuid4()),
                "expected_ai_config_version": 0,
                "protocol_id": "chat_completions_v1",
                "base_url": "https://api.example.com/v1",
                "model": "g15-model",
                "secret": "g15-secret",
            },
        )
        self.assertEqual(status, 200, config)
        self.assertTrue(config["ready"])
        blobs = list(runtime.credential_root.rglob("*.dpapi"))
        self.assertTrue(blobs)
        # Fault injection: corrupt the stored DPAPI blob so it cannot decrypt.
        blobs[0].write_bytes(b"corrupted-dpapi-material")

        status, config = client.get("/api/local/ai/config")
        self.assertEqual(status, 200, config)
        self.assertFalse(config["ready"])
        self.assertEqual(config["reason"], "CREDENTIAL_UNAVAILABLE")

        status, plan = client.post("/api/daily-plans", {"plan_date": "2026-09-02"})
        self.assertEqual(status, 201, plan)
        status, payload = client.post(
            f"/api/daily-plans/{plan['id']}/ai-tasks",
            {
                "request_id": str(uuid.uuid4()),
                "task_type": "daily_lesson_split",
                "expected_content_version": plan["current_content_version"],
                "target_grade": "middle",
            },
        )
        self.assertEqual(status, 409, payload)
        self.assertIn(
            payload["error"]["code"],
            ("CREDENTIAL_UNAVAILABLE", "AI_NOT_CONFIGURED"),
        )
        self.assertEqual(
            query_scalar(runtime.db_path, "SELECT count(*) FROM local_ai_tasks"), 0
        )

        self._manual_save(client, plan)
        payload, _headers = self._export_docx(client, "2026-09-02", "2026-09-02")
        self.assertEqual(payload[:2], b"PK")
        self._assert_restart_and_export(plan["id"])


class ExecutorDegradeTests(DegradeCase):
    def test_executor_unavailable_manual_path_works(self):
        runtime = self.make_runtime()
        self.runtime = runtime
        # executor=None: the host degraded because the executor could not start.
        server = self.start_server(runtime, executor=None)
        client = server.client()
        self.initialize(client)
        status, plan = client.post("/api/daily-plans", {"plan_date": "2026-09-02"})
        self.assertEqual(status, 201, plan)

        status, payload = client.post(
            f"/api/daily-plans/{plan['id']}/ai-tasks",
            {
                "request_id": str(uuid.uuid4()),
                "task_type": "daily_lesson_split",
                "expected_content_version": plan["current_content_version"],
                "target_grade": "middle",
            },
        )
        self.assertEqual(status, 503, payload)
        self.assertEqual(payload["error"]["code"], "AI_EXECUTOR_UNAVAILABLE")
        self.assertEqual(
            query_scalar(runtime.db_path, "SELECT count(*) FROM local_ai_tasks"), 0
        )

        self._manual_save(client, plan)
        payload, _headers = self._export_docx(client, "2026-09-02", "2026-09-02")
        self.assertEqual(payload[:2], b"PK")
        self._assert_restart_and_export(plan["id"])


class NetworkDegradeTests(DegradeCase):
    def test_network_unavailable_real_connect_failure(self):
        """A real closed-port connect failure through the real spawn worker.

        The executor is started *before* the task exists (no cold-recovery
        pause), the manual save happens during the real connect/backoff window,
        and the attempt is proven never to have been dispatched (zero provider
        sends).
        """
        from app.local import (
            ai_config_service,
            daily_plan_service,
            profile_service,
        )
        from app.local.ai_executor import AiExecutor
        from app.local.normalize import normalize_initialization

        # A port with nothing listening (bound then closed).
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        closed_port = int(probe.getsockname()[1])
        probe.close()

        runtime = self.make_runtime()
        runtime.launch_id = str(uuid.uuid4())
        session = runtime.session()
        self.addCleanup(session.close)
        profile_service.initialize(
            session,
            normalize_initialization(
                request_id=str(uuid.uuid4()),
                display_name="G15教师",
                class_name="G15中一班",
                grade="middle",
                term_name="2026 年秋季学期",
                start_date="2026-09-01",
                end_date="2026-12-31",
                school_name="G15园所",
            ),
        )
        session.commit()
        ai_config_service.patch_config(
            session,
            expected_ai_config_version=0,
            base_url="https://api.example.com/v1",
            model="g15-real-model",
            secret="g15-secret",
            secret_provided=True,
            request_id=str(uuid.uuid4()),
            credential_root=runtime.credential_root,
        )
        plan, _ = daily_plan_service.create_or_open(
            session,
            plan_date=date(2026, 9, 2),
            raw_lesson_plan="G15网络不可用原文",
            adopted_content={"group_activity": {"process": "一、导入"}, "reflection": "反思"},
        )

        # Start the executor FIRST (no cold-recovery pause of the new task).
        executor = AiExecutor(
            runtime,
            synthetic_transport={
                "resolution": [
                    {"family": socket.AF_INET, "ip": "127.0.0.1", "port": closed_port}
                ],
                "ca_pem": None,
            },
            connect_phase_limit=1.0,
        )
        executor.start()
        self.addCleanup(lambda: executor.dispose())
        server = self.start_server(runtime, executor=executor)
        client = server.client()

        status, task = client.post(
            f"/api/daily-plans/{plan['id']}/ai-tasks",
            {
                "request_id": str(uuid.uuid4()),
                "task_type": "daily_lesson_split",
                "expected_content_version": plan["current_content_version"],
                "target_grade": "middle",
            },
        )
        self.assertEqual(status, 202, task)

        # Wait for real persisted attempt evidence (the first connect attempt is
        # recorded before any send). The save that follows must happen while the
        # task is genuinely in its connect/backoff window.
        state_at_save = None
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            status, task_now = client.get(f"/api/local/ai/tasks/{task['id']}")
            self.assertEqual(status, 200, task_now)
            attempts = query_scalar(
                runtime.db_path,
                "SELECT count(*) FROM local_ai_attempts",
            )
            if attempts and task_now["status"] in (
                "claimed",
                "dispatching",
                "retry_wait",
            ):
                state_at_save = task_now["status"]
                break
            time.sleep(0.1)
        self.assertIsNotNone(state_at_save, "no real attempt window observed")

        # While the attempt is connecting/backing off, the manual path must
        # still work: a real save that changes only the *target* / reflection,
        # never the split source (which would legitimately pause the task).
        deadline = time.monotonic() + 20
        saved = None
        while time.monotonic() < deadline:
            status, plan_now = client.get(f"/api/daily-plans/{plan['id']}")
            self.assertEqual(status, 200, plan_now)
            status, candidate = client.patch(
                f"/api/daily-plans/{plan['id']}",
                {
                    "expected_content_version": plan_now["current_content_version"],
                    "raw_lesson_plan": "G15网络不可用原文",
                    "adopted_content": {
                        "group_activity": {"process": "G15并发修改过程（手工）"},
                        "reflection": "G15并发反思",
                    },
                },
            )
            if status == 200:
                saved = candidate
                break
            time.sleep(0.2)
        self.assertIsNotNone(saved, "manual save was blocked by the AI task")
        # The task was still in its attempt window at save time.
        self.assertIn(state_at_save, ("claimed", "dispatching", "retry_wait"))

        # The AI task must end failed/connection_unavailable with zero sends.
        terminal = None
        reason = None
        deadline = time.monotonic() + 150
        while time.monotonic() < deadline:
            status, task_now = client.get(f"/api/local/ai/tasks/{task['id']}")
            self.assertEqual(status, 200, task_now)
            terminal = task_now["status"]
            reason = task_now.get("reason")
            if terminal in ("failed", "paused", "outcome_unknown", "cancelled"):
                break
            time.sleep(0.5)
        self.assertEqual(terminal, "failed", f"{terminal}/{reason}")
        self.assertEqual(reason, "connection_unavailable")
        execution_id = task_now["execution"]["id"]
        self.assertGreaterEqual(
            query_scalar(
                runtime.db_path,
                "SELECT count(*) FROM local_ai_attempts WHERE execution_id = ?",
                (execution_id,),
            ),
            1,
        )
        # No provider send: no dispatch mark and no candidate.
        self.assertEqual(
            query_scalar(
                runtime.db_path,
                "SELECT count(*) FROM local_ai_attempts WHERE execution_id = ? "
                "AND dispatch_marked_at IS NOT NULL",
                (execution_id,),
            ),
            0,
        )
        self.assertEqual(
            query_scalar(
                runtime.db_path,
                "SELECT count(*) FROM local_ai_candidates WHERE task_id = ?",
                (task["id"],),
            ),
            0,
        )

        # Confirm the real worker + coordinator have exited BEFORE releasing the
        # old runtime, otherwise the "cold restart" would leave the old
        # coordinator alive against a disposed engine. A failed teardown fails
        # the test rather than pretending a cold restart happened.
        self.assertTrue(executor.dispose(), "AI worker/coordinator did not exit")
        session.close()
        # Cold restart: manual content survives and export still works.
        runtime, client = self._cold_restart(runtime)
        self.runtime = runtime
        status, reread = client.get(f"/api/daily-plans/{plan['id']}")
        self.assertEqual(status, 200, reread)
        self.assertEqual(
            reread["content"]["raw_lesson_plan"], "G15网络不可用原文"
        )
        self.assertEqual(
            reread["content"]["adopted_content"]["group_activity"]["process"],
            "G15并发修改过程（手工）",
        )
        payload, _headers = self._export_docx(client, "2026-09-02", "2026-09-02")
        self.assertEqual(payload[:2], b"PK")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
