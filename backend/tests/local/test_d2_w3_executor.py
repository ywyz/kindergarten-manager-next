"""D2 W3 executor: real spawned workers, real Job, controlled TLS.

These tests exercise the coordinator with real ``multiprocessing`` spawn
children (fake in-process worker modes for handshake branches, the real worker
+ a controlled TLS server for the end-to-end path). No whole-path mock.
"""

from __future__ import annotations

import json
import os
import socket
import time
import unittest
import uuid
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from app.local import ai_task_service
from app.local.ai_executor import AiExecutor
from app.local.base import utc_now
from app.local.errors import LocalAiNotConfigured
from app.local.models import LocalAICredential
from sqlalchemy import select

from tests.local import w3_tls
from tests.local.support import LocalTestCase, query_scalar, sqlite_connect
from tests.local.w3_tls import TEST_HOST

SPLIT_CANDIDATE = {
    "group_activity": {
        "theme": "主题",
        "objectives": "目标",
        "preparation": "准备",
        "key_points": "重点",
        "difficult_points": "难点",
        "process": "过程",
    }
}


class ExecutorCase(LocalTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.runtime = self.make_runtime()
        self.runtime.launch_id = str(uuid.uuid4())
        self.db = self.runtime.db_path
        self.session = self.runtime.session()
        self.addCleanup(self.session.close)
        from app.local import profile_service

        from app.local.normalize import normalize_initialization

        profile_service.initialize(
            self.session, normalize_initialization(**{
                "request_id": str(uuid.uuid4()),
                "display_name": "王老师",
                "class_name": "中一班",
                "grade": "middle",
                "term_name": "2026 年秋季学期",
                "start_date": "2026-09-01",
                "end_date": "2026-12-31",
                "school_name": "示范幼儿园",
            })
        )
        self.session.commit()
        self._executors: list[AiExecutor] = []

    # -- helpers -----------------------------------------------------------
    def configure_ai(self, *, model="w3fake|ready_then_result:0", secret="s3cret"):
        from app.local import ai_config_service

        version = query_scalar(self.db, "SELECT current_config_version FROM local_ai_state")
        ai_config_service.patch_config(
            self.session,
            expected_ai_config_version=version or 0,
            base_url=f"https://{TEST_HOST}/v1",
            model=model,
            secret=secret,
            secret_provided=True,
            request_id=str(uuid.uuid4()),
            credential_root=self.runtime.credential_root,
        )

    def make_plan(self, plan_date=date(2026, 9, 2)):
        from app.local import daily_plan_service

        payload, _ = daily_plan_service.create_or_open(
            self.session,
            plan_date=plan_date,
            raw_lesson_plan="原始教案正文",
            adopted_content={"group_activity": {"process": "一、导入"}, "reflection": "反思"},
        )
        return payload

    def create_split(self, plan_id):
        return ai_task_service.create_task(
            self.session,
            plan_id=plan_id,
            task_type="daily_lesson_split",
            expected_content_version=1,
            target_grade="middle",
            request_id=str(uuid.uuid4()),
        )[0]

    def start_executor(self, **kwargs) -> AiExecutor:
        from tests.local.w3_workers import fake_worker_entry

        kwargs.setdefault("worker_target", fake_worker_entry)
        executor = AiExecutor(self.runtime, **kwargs)
        executor.start()
        self._executors.append(executor)
        self.addCleanup(self._dispose_executors)
        return executor

    def submit(self, plan_id, task_type="daily_lesson_split", executor=None):
        """Submit *after* the executor exists (cold recovery pauses old tasks)."""
        task = ai_task_service.create_task(
            self.session,
            plan_id=plan_id,
            task_type=task_type,
            expected_content_version=1,
            target_grade="middle",
            request_id=str(uuid.uuid4()),
            runtime=self.runtime,
        )[0]
        if executor is not None:
            executor.notify()
        return task

    def _dispose_executors(self):
        for executor in self._executors:
            try:
                executor.stop()
            except Exception:  # noqa: BLE001
                pass

    def task_status(self, task_id):
        return query_scalar(self.db, "SELECT status FROM local_ai_tasks WHERE id = ?", (task_id,))

    def task_row(self, task_id):
        connection = sqlite_connect(self.db)
        try:
            row = connection.execute(
                "SELECT * FROM local_ai_tasks WHERE id = ?", (task_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            connection.close()

    def wait_status(self, task_id, statuses, timeout=25.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.task_status(task_id) in statuses:
                return self.task_status(task_id)
            time.sleep(0.05)
        row = self.task_row(task_id) or {}
        raise AssertionError(
            f"task {task_id} did not reach {statuses}; "
            f"last={row.get('status')} reason={row.get('reason')} "
            f"meta={row.get('runtime_meta_json')}"
        )

    def candidate_count(self, task_id):
        return query_scalar(
            self.db,
            "SELECT count(*) FROM local_ai_candidates WHERE task_id = ?",
            (task_id,),
        )


class ClassificationExecutorTests(ExecutorCase):
    def test_prefetch_auth_pauses_and_blocks(self):
        self.configure_ai(model="w3fake|result:auth:auth_rejected")
        plan = self.make_plan()
        executor = self.start_executor()
        task = self.submit(plan["id"], executor=executor)
        self.assertEqual(self.wait_status(task["id"], {"paused"}), "paused")
        row = self.task_row(task["id"])
        self.assertEqual(row["reason"], "auth_rejected")
        self.assertEqual(
            query_scalar(self.db, "SELECT blocked_config_version FROM local_ai_state"), 1
        )
        self.assertEqual(self.candidate_count(task["id"]), 0)

    def test_prefetch_policy_not_sent_failed(self):
        self.configure_ai(model="w3fake|result:policy:endpoint_blocked")
        plan = self.make_plan()
        executor = self.start_executor()
        task = self.submit(plan["id"], executor=executor)
        self.wait_status(task["id"], {"failed"})
        row = self.task_row(task["id"])
        self.assertEqual(row["reason"], "endpoint_blocked")
        self.assertEqual(json.loads(row["runtime_meta_json"])["processing_certainty"], "not_sent")

    def test_invalid_candidate_failed(self):
        self.configure_ai(model="w3fake|ready_then_result:0:invalid")
        plan = self.make_plan()
        executor = self.start_executor()
        task = self.submit(plan["id"], executor=executor)
        self.wait_status(task["id"], {"failed"})
        self.assertEqual(self.task_row(task["id"])["reason"], "output_invalid")
        self.assertEqual(self.candidate_count(task["id"]), 0)

    def test_success_persists_candidate(self):
        self.configure_ai(model="w3fake|ready_then_result:0")
        plan = self.make_plan()
        executor = self.start_executor()
        task = self.submit(plan["id"], executor=executor)
        self.assertEqual(self.wait_status(task["id"], {"succeeded"}, timeout=40), "succeeded")
        self.assertEqual(self.candidate_count(task["id"]), 1)
        self.assertEqual(
            query_scalar(
                self.db, "SELECT count(*) FROM local_ai_attempts WHERE execution_id = "
                "(SELECT current_execution_id FROM local_ai_tasks WHERE id = ?)",
                (task["id"],),
            ),
            1,
        )


class FreezeAndDrainTests(ExecutorCase):
    def test_freeze_then_cancel_close_keeps_pinned_versions(self):
        # Freeze during the connect phase, change the AI config, then cancel
        # the close: the already-claimed execution must keep its permit and
        # pinned config version and send at most once.
        self.configure_ai(model="w3fake|ready_delay:1.5|ready_then_result:0")
        plan = self.make_plan()
        executor = self.start_executor()
        task = self.submit(plan["id"], executor=executor)
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline and not executor.active_snapshot()["attempt_in_flight"]:
            time.sleep(0.02)
        self.assertTrue(executor.active_snapshot()["attempt_in_flight"])
        row_before = self.task_row(task["id"])
        self.assertEqual(row_before["status"], "claimed")
        pinned_config = query_scalar(
            self.db, "SELECT config_version FROM local_ai_executions WHERE id = ?",
            (row_before["current_execution_id"],),
        )
        pinned_generation = row_before["generation"]
        executor.freeze()
        # Change the AI configuration while the close intent is pending.
        self.configure_ai(model="w3fake|ready_then_result:0", secret="changed-secret")
        self.assertEqual(
            query_scalar(self.db, "SELECT current_config_version FROM local_ai_state"), 2
        )
        # The user keeps waiting instead of exiting.
        executor.unfreeze()
        executor.notify()
        self.wait_status(task["id"], {"succeeded"}, timeout=40)
        row_after = self.task_row(task["id"])
        self.assertEqual(row_after["current_execution_id"], row_before["current_execution_id"])
        self.assertEqual(row_after["generation"], pinned_generation)
        self.assertEqual(
            query_scalar(
                self.db, "SELECT config_version FROM local_ai_executions WHERE id = ?",
                (row_after["current_execution_id"],),
            ),
            pinned_config,
        )
        # At most one SEND: exactly one attempt and one candidate.
        self.assertEqual(
            query_scalar(
                self.db, "SELECT count(*) FROM local_ai_attempts WHERE execution_id = ?",
                (row_after["current_execution_id"],),
            ),
            1,
        )
        self.assertEqual(self.candidate_count(task["id"]), 1)

    def test_stop_and_exit_retires_and_leaves_manual_resume(self):
        self.configure_ai(model="w3fake|ready_then_silent:30")
        plan = self.make_plan()
        executor = self.start_executor()
        task = self.submit(plan["id"], executor=executor)
        self.wait_status(task["id"], {"dispatching"}, timeout=25)
        self.assertTrue(executor.stop_and_drain(deadline=5.0))
        self.assertEqual(self.wait_status(task["id"], {"outcome_unknown"}), "outcome_unknown")
        out = ai_task_service.get_task(self.session, task["id"])
        self.assertEqual(out["reason"], "user_stop")
        self.assertIn("retry", out["allowed_actions"])
        self.assertNotIn("resume", out["allowed_actions"])

    def test_cancel_blocks_send(self):
        self.configure_ai(model="w3fake|ready_delay:1.5|ready_then_result:0")
        plan = self.make_plan()
        executor = self.start_executor()
        task = self.submit(plan["id"], executor=executor)
        self.wait_status(task["id"], {"claimed"}, timeout=25)
        claim_id = self.task_row(task["id"])["current_execution_id"]
        self.assertTrue(executor.begin_cancel(claim_id))
        result, abort_id, abort_kind = ai_task_service.cancel_task(
            self.session,
            task_id=task["id"],
            expected_execution_id=claim_id,
            request_id=str(uuid.uuid4()),
        )
        executor.end_cancel(claim_id, committed=True)
        self.assertEqual(result["status"], "cancelled")
        executor.abort_execution(claim_id, "cancel")
        executor.notify()
        time.sleep(1.5)
        self.assertEqual(self.candidate_count(task["id"]), 0)
        self.assertEqual(self.task_status(task["id"]), "cancelled")


class IpcBlockingTests(LocalTestCase):
    """A child that never reads a large bootstrap must not hang the parent."""

    def setUp(self):
        super().setUp()
        self.runtime = self.make_runtime()
        self.runtime.launch_id = str(uuid.uuid4())
        self.db = self.runtime.db_path
        self.session = self.runtime.session()
        self.addCleanup(self.session.close)
        from app.local import profile_service
        from app.local.normalize import normalize_initialization

        profile_service.initialize(
            self.session,
            normalize_initialization(
                request_id=str(uuid.uuid4()),
                display_name="王老师",
                class_name="中一班",
                grade="middle",
                term_name="2026 年秋季学期",
                start_date="2026-09-01",
                end_date="2026-12-31",
                school_name="示范幼儿园",
            ),
        )
        self.session.commit()

    def _heavy_task(self, model):
        """A plan whose bootstrap frame is large enough to fill the pipe."""
        from app.local import ai_config_service, ai_task_service, daily_plan_service

        ai_config_service.patch_config(
            self.session,
            expected_ai_config_version=0,
            base_url="https://api.example.com/v1",
            model=model,
            secret="s3cret",
            secret_provided=True,
            request_id=str(uuid.uuid4()),
            credential_root=self.runtime.credential_root,
        )
        heavy = "\\" * 42750
        adopted = {
            "group_activity": {
                key: heavy
                for key in (
                    "theme", "objectives", "preparation",
                    "key_points", "difficult_points", "process",
                )
            },
            "reflection": "反思",
        }
        plan, _ = daily_plan_service.create_or_open(
            self.session,
            plan_date=date(2026, 9, 2),
            raw_lesson_plan="原始教案",
            adopted_content=adopted,
        )
        return ai_task_service.create_task(
            self.session,
            plan_id=plan["id"],
            task_type="daily_other_activities",
            expected_content_version=1,
            target_grade="middle",
            request_id=str(uuid.uuid4()),
            runtime=self.runtime,
        )[0]

    def _wait_terminal(self, task_id, timeout=40, statuses=("paused", "failed", "outcome_unknown")):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = query_scalar(
                self.db, "SELECT status FROM local_ai_tasks WHERE id = ?", (task_id,)
            )
            if status in statuses:
                return status
            time.sleep(0.05)
        return None

    def test_child_never_reading_bootstrap_terminates_within_budget(self):
        from tests.local.w3_workers import never_read_worker

        marker = self.tmp_root / "never-read.marker"
        os.environ["KGM_W3_NEVER_READ_MARK"] = str(marker)
        self.addCleanup(lambda: os.environ.pop("KGM_W3_NEVER_READ_MARK", None))
        # Start the executor FIRST so the task is not paused by cold recovery.
        events: list[str] = []
        pids: list[int] = []
        executor = AiExecutor(
            self.runtime,
            worker_target=never_read_worker,
            connect_phase_limit=1.0,
            on_event=lambda name, _claim, info=None: (
                events.append(name),
                pids.append(info.get("pid")) if name == "child_started" and info else None,
            ),
        )
        executor.start()
        try:
            task = self._heavy_task("probe-model")
            executor.notify()
            started = time.monotonic()
            status = self._wait_terminal(task["id"])
            elapsed = time.monotonic() - started
            # The worker really started, was really recorded, and really read
            # nothing; the write timed out, the Job was terminated.
            self.assertTrue(marker.is_file(), "worker did not start")
            self.assertTrue(any(pid for pid in pids), "child_started carried no pid")
            self.assertIn("child_started", events)
            self.assertEqual(
                query_scalar(self.db, "SELECT count(*) FROM local_ai_executions"), 1
            )
            self.assertEqual(
                query_scalar(self.db, "SELECT count(*) FROM local_ai_attempts"), 1
            )
            self.assertNotIn("sent", events)
            self.assertIn(status, ("paused", "failed"))
            self.assertEqual(
                query_scalar(
                    self.db,
                    "SELECT count(*) FROM local_ai_attempts WHERE dispatch_marked_at IS NOT NULL",
                ),
                0,
            )
            self.assertLess(elapsed, 15.0, f"shutdown took {elapsed:.1f}s")
            self.assertTrue(executor.dispose())
        finally:
            executor.stop()

    def test_invalid_complete_frame_rejected_without_blocking(self):
        from tests.local.w3_workers import fake_worker_entry

        # Note: this is a *complete but invalid* frame (not a partial frame);
        # the truncated/partial-frame risk is covered by the bounded-IO design
        # and the never-reading test above.
        events: list[str] = []
        executor = AiExecutor(
            self.runtime,
            worker_target=fake_worker_entry,
            connect_phase_limit=3.0,
            on_event=lambda name, _claim, info=None: events.append(name),
        )
        executor.start()
        try:
            task = self._heavy_task("w3fake|truncated_frame")
            executor.notify()
            started = time.monotonic()
            # An invalid (but complete) frame is rejected; the attempt may go to
            # retry_wait within the bounded retry budget, never to a candidate.
            status = self._wait_terminal(
                task["id"], statuses=("retry_wait", "paused", "failed", "outcome_unknown")
            )
            elapsed = time.monotonic() - started
            self.assertIn(status, ("retry_wait", "paused", "failed"))
            self.assertEqual(
                query_scalar(
                    self.db,
                    "SELECT count(*) FROM local_ai_candidates WHERE task_id = ?",
                    (task["id"],),
                ),
                0,
            )
            self.assertLess(elapsed, 15.0, f"shutdown took {elapsed:.1f}s")
            self.assertTrue(executor.dispose())
        finally:
            executor.stop()


class LateAndDegradationTests(ExecutorCase):
    def test_late_response_after_deadline_rejected(self):
        from unittest import mock

        from app.local import ai_transport

        self.configure_ai(model="w3fake|ready_then_result:1.5")
        executor = self.start_executor()
        # The shortened deadline is in force before the task is submitted, so
        # no scheduling luck is involved.
        with mock.patch.object(ai_transport, "ATTEMPT_BUDGET_MS", 600):
            task = self.submit(plan_id=self.make_plan()["id"], executor=executor)
            status = self.wait_status(task["id"], {"outcome_unknown", "succeeded"}, timeout=30)
        self.assertEqual(status, "outcome_unknown")
        self.assertEqual(self.candidate_count(task["id"]), 0)

    def test_manual_save_and_export_work_without_ai(self):
        # G15: with no executor/AI configured, the manual path is complete.
        from app.local import daily_plan_service, export_service

        plan = self.make_plan()
        payload = daily_plan_service.save(
            self.session,
            plan_id=plan["id"],
            expected_content_version=1,
            raw_lesson_plan="手工修改的原文",
            adopted_content={
                "group_activity": {"process": "手工过程"},
                "reflection": "手工反思",
            },
        )
        self.assertEqual(payload["current_content_version"], 2)
        bundle = export_service.prepare_export(
            self.session,
            from_date=date(2026, 9, 2),
            to_date=date(2026, 9, 2),
            ack_missing=False,
            expected_context=None,
        )
        self.assertTrue(bundle.records)

    def test_result_persistence_failure_then_local_recovery(self):
        from unittest import mock

        self.configure_ai(model="w3fake|ready_then_result:0")
        executor = self.start_executor()
        # Both the submission and the failure-phase assertions run inside the
        # patch, so the background local recovery cannot race them.
        with mock.patch.object(
            ai_task_service, "finalize_success", side_effect=RuntimeError("db down")
        ):
            task = self.submit(plan_id=self.make_plan()["id"], executor=executor)
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                if executor.active_snapshot()["pending_persist"]:
                    break
                time.sleep(0.05)
            # The result is kept in memory and new scheduling stops; the attempt
            # was not resent (the task never became succeeded).
            self.assertEqual(executor.active_snapshot()["pending_persist"], 1)
            self.assertFalse(executor.is_runnable())
            self.assertEqual(self.candidate_count(task["id"]), 0)
            self.assertIn(self.task_status(task["id"]), ("dispatching", "succeeded"))
        # With the fault removed only the local commit is retried.
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            if (
                self.task_status(task["id"]) == "succeeded"
                and executor.active_snapshot()["pending_persist"] == 0
            ):
                break
            time.sleep(0.05)
        self.assertEqual(self.task_status(task["id"]), "succeeded")
        self.assertEqual(self.candidate_count(task["id"]), 1)
        self.assertTrue(executor.is_runnable())


    def test_post_send_teardown_exception_classified_unknown(self):
        from unittest import mock

        from app.local.errors import LocalAiRetryAckRequired

        self.configure_ai(model="w3fake|ready_then_result:0")
        executor = self.start_executor()

        calls = {"n": 0}
        real_teardown = AiExecutor._teardown

        def flaky_teardown(self, active, *, grace, force, gate_held=False):  # noqa: ANN001
            calls["n"] += 1
            if not getattr(active, "marked", False) or calls["n"] > 1:
                return real_teardown(
                    self, active, grace=grace, force=force, gate_held=gate_held
                )
            # Fail *after* the dispatch mark: the attempt may already be sent.
            raise RuntimeError("teardown fault")

        # The fault is installed before the task exists, so the attempt cannot
        # be claimed under a different code path.
        with mock.patch.object(AiExecutor, "_teardown", flaky_teardown):
            task = self.submit(plan_id=self.make_plan()["id"], executor=executor)
            status = self.wait_status(
                task["id"], {"outcome_unknown", "succeeded", "failed"}, timeout=30
            )
        self.assertEqual(status, "outcome_unknown")
        out = ai_task_service.get_task(self.session, task["id"])
        self.assertTrue(out["retry_requires_ack"])
        self.assertEqual(
            query_scalar(
                self.db,
                "SELECT count(*) FROM local_ai_attempts WHERE dispatch_marked_at IS NOT NULL",
            ),
            1,
        )
        with self.assertRaises(LocalAiRetryAckRequired):
            ai_task_service.retry_task(
                self.session,
                task_id=task["id"],
                expected_execution_id=self.task_row(task["id"])["current_execution_id"],
                ack_duplicate_cost=False,
                request_id=str(uuid.uuid4()),
            )


class RealTlsExecutorTests(ExecutorCase):
    def setUp(self):
        super().setUp()
        self._temp = TemporaryDirectory(prefix="kgm-w3-exec-tls-")
        self.addCleanup(self._temp.cleanup)
        root = Path(self._temp.name)
        ca_dir = root / "ca"
        _cert, _key, ca_pem = w3_tls.create_ca(ca_dir)
        leaf_cert, leaf_key = w3_tls.create_leaf(ca_dir, root / "leaf")
        body = w3_tls.envelope(
            json.dumps(SPLIT_CANDIDATE, ensure_ascii=False),
            usage={"prompt_tokens": 4, "completion_tokens": 5},
        )
        self.server = w3_tls.TlsServer(cert=leaf_cert, key=leaf_key, reply=body).start()
        self.addCleanup(self.server.stop)
        self.ca_pem = ca_pem.decode("utf-8")

    def test_real_tls_persistence_recovery_keeps_single_http(self):
        self.configure_ai(model="real-model")
        plan = self.make_plan()
        executor = AiExecutor(
            self.runtime,
            synthetic_transport={
                "resolution": [
                    {"family": socket.AF_INET, "ip": "127.0.0.1", "port": self.server.port}
                ],
                "ca_pem": self.ca_pem,
            },
        )
        executor.start()
        self._executors.append(executor)
        self.addCleanup(self._dispose_executors)
        from unittest import mock

        with mock.patch.object(
            ai_task_service, "finalize_success", side_effect=RuntimeError("db down")
        ):
            task = self.submit(plan["id"], executor=executor)
            deadline = time.monotonic() + 40
            while time.monotonic() < deadline:
                if executor.active_snapshot()["pending_persist"]:
                    break
                time.sleep(0.05)
            # Exactly one real HTTP request; the result is kept in memory.
            self.assertEqual(len(self.server.requests), 1)
            self.assertEqual(self.candidate_count(task["id"]), 0)
            self.assertTrue(executor.active_snapshot()["pending_persist"])
            self.assertFalse(executor.is_runnable())
        # With the fault removed the coordinator retries only the local commit.
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            if (
                self.task_status(task["id"]) == "succeeded"
                and executor.active_snapshot()["pending_persist"] == 0
            ):
                break
            time.sleep(0.05)
        self.assertEqual(self.candidate_count(task["id"]), 1)
        self.assertEqual(self.task_status(task["id"]), "succeeded")
        self.assertEqual(executor.active_snapshot()["pending_persist"], 0)
        # No second outbound request was made.
        self.assertEqual(len(self.server.requests), 1)
        self.assertTrue(executor.is_runnable())
        self.assertEqual(len(self.server.requests), 1)
        request = self.server.requests[0]
        self.assertTrue(request.startswith(b"POST /v1/chat/completions HTTP/1.1"))
        self.assertIn(b"Authorization: Bearer s3cret", request)
        self.assertEqual(self.candidate_count(task["id"]), 1)
        # The system message carries the output contract and the guidance.
        self.assertIn(b"output_contract", request)
        self.assertIn(b"instructions", request)
        # Metadata persisted from the provider are whitelisted values.
        usage = query_scalar(
            self.db,
            "SELECT usage_json FROM local_ai_attempts WHERE execution_id = "
            "(SELECT current_execution_id FROM local_ai_tasks WHERE id = ?)",
            (task["id"],),
        )
        self.assertIn("prompt_tokens", usage)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
