"""D4 E09/E10 observation HTTP API tests over a real loopback server.

Every request uses the real local app guard (Host / Origin / per-launch
session), a synthetic temporary database and synthetic JPEGs. The AI task /
candidate flow uses the reviewed in-process executor with the fake spawn
worker; no external network is involved.
"""

from __future__ import annotations

import io
import json
import time
import unittest
import uuid
from urllib.parse import quote

from PIL import Image
from sqlalchemy import select

from app.local import ai_config_service, ai_executor, profile_service
from app.local.models import LocalProfile
from app.local.normalize import normalize_initialization
from tests.local.obs_ai_workers import observation_worker_entry
from tests.local.support import LocalTestCase, initialize_body, query_scalar


class ObservationApiCase(LocalTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.runtime = self.make_runtime()
        self.session = self.runtime.session()
        profile_service.initialize(
            self.session, normalize_initialization(**initialize_body())
        )
        self.session.commit()
        self.profile = self.session.scalars(select(LocalProfile)).one()
        self.server = self.start_server(self.runtime)
        self.client = self.server.client()

    def tearDown(self) -> None:
        self.session.close()
        super().tearDown()

    # -- helpers -----------------------------------------------------------
    def create(self, record_type="public", payload=None, **kwargs):
        body = {
            "request_id": str(uuid.uuid4()),
            "record_type": record_type,
        }
        if payload is not None:
            body["payload"] = payload
        body.update(kwargs)
        status, result = self.client.post("/api/observations", body)
        self.assertEqual(status, 201, result)
        return result

    def current(self, observation_id):
        status, result = self.client.get(f"/api/observations/{observation_id}")
        self.assertEqual(status, 200, result)
        return result

    def save(self, observation_id, payload, *, photos=None, reason="manual", **kwargs):
        current = self.current(observation_id)
        body = {
            "request_id": str(uuid.uuid4()),
            "expected_revision": current["revision"],
            "payload": payload,
            "save_reason": reason,
        }
        if photos is not None:
            body["photos"] = photos
        body.update(kwargs)
        return self.client.patch(f"/api/observations/{observation_id}", body)

    def upload(self, observation_id, data: bytes, *, caption=None, name="a.jpg"):
        current = self.current(observation_id)
        boundary = "----kgm" + uuid.uuid4().hex
        fields = {
            "request_id": str(uuid.uuid4()),
            "expected_revision": str(current["revision"]),
            "display_name": name,
        }
        if caption is not None:
            fields["caption"] = caption
        body = bytearray()
        for key, value in fields.items():
            body += (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'
                f"{value}\r\n"
            ).encode("utf-8")
        body += (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="a.jpg"\r\n'
            "Content-Type: image/jpeg\r\n\r\n"
        ).encode("utf-8")
        body += data + b"\r\n"
        body += f"--{boundary}--\r\n".encode("utf-8")
        return self.raw(
            "POST",
            f"/api/observations/{observation_id}/photos",
            bytes(body),
            content_type=f"multipart/form-data; boundary={boundary}",
        )

    def raw(self, method, path, body=None, *, content_type=None, token=True, origin=True):
        import http.client

        headers = {"Host": f"127.0.0.1:{self.server.port}"}
        if token:
            headers["X-App-Session"] = self.server.token
        if origin:
            headers["Origin"] = self.server.origin
        if content_type:
            headers["Content-Type"] = content_type
        connection = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=60)
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            raw = response.read()
            status = response.status
            headers_out = {
                key.lower(): value for key, value in response.getheaders()
            }
        finally:
            connection.close()
        try:
            return status, json.loads(raw.decode("utf-8")), headers_out
        except (UnicodeDecodeError, json.JSONDecodeError):
            return status, raw, headers_out

    def jpeg(self, color=(200, 30, 30)):
        buffer = io.BytesIO()
        Image.new("RGB", (64, 48), color).save(buffer, "JPEG", quality=90)
        return buffer.getvalue()

    def ready_observation(self):
        created = self.create(
            payload={
                "observation_date": "2026-09-15",
                "subjects": [{"name": "小明"}],
                "age_years": 5,
                "environment": "积木区",
            }
        )
        observation_id = created["observation_id"]
        status, uploaded, _headers = self.upload(observation_id, self.jpeg(), caption="观察")
        self.assertEqual(status, 201, uploaded)
        asset_id = uploaded["asset_id"]
        status, saved = self.save(
            observation_id,
            {
                "observation_goal": "观察合作",
                "observation_process": "幼儿在积木区搭建。",
            },
            photos=[{"asset_id": asset_id, "caption": "观察"}],
        )
        self.assertEqual(status, 200, saved)
        return observation_id, asset_id

    # -- guards ------------------------------------------------------------
    def test_local_session_host_and_origin_guards(self):
        status, _body, _headers = self.raw("GET", "/api/observations", token=False)
        self.assertEqual(status, 401)
        status, _body, _headers = self.raw(
            "POST",
            "/api/observations",
            json.dumps({"request_id": "r", "record_type": "public"}).encode(),
            content_type="application/json",
            origin=False,
        )
        self.assertEqual(status, 403)
        status, _body, _headers = self.raw(
            "GET",
            "/api/observations",
            token=True,
        )
        self.assertEqual(status, 200)
        # The binary photo route is protected exactly like JSON routes.
        created = self.create()
        observation_id = created["observation_id"]
        status, _uploaded, _headers = self.upload(observation_id, self.jpeg())
        self.assertEqual(status, 201)
        status, _photos = self.client.get(f"/api/observations/{observation_id}/photos")
        asset_id = _photos[0]["asset_id"]
        status, _body, _headers = self.raw(
            "GET",
            f"/api/observations/{observation_id}/photos/{asset_id}/derivatives/ai/content",
            token=False,
        )
        self.assertEqual(status, 401)

    # -- create / list / save / receipt ------------------------------------
    def test_create_list_save_receipt_and_conflict(self):
        create_request_id = str(uuid.uuid4())
        status, created = self.client.post(
            "/api/observations",
            {
                "request_id": create_request_id,
                "record_type": "public",
                "payload": {
                    "observation_date": "2026-09-15",
                    "subjects": [{"name": "小明"}, {"name": "小红"}],
                    "environment": "积木区",
                },
            },
        )
        self.assertEqual(status, 201, created)
        observation_id = created["observation_id"]
        status, create_receipt = self.client.get(
            f"/api/observations/operations/{create_request_id}"
        )
        self.assertEqual(status, 200, create_receipt)
        self.assertEqual(create_receipt["result"]["observation_id"], observation_id)
        current = self.current(observation_id)
        self.assertEqual(current["revision"], 1)
        self.assertEqual(current["payload"]["school_name"], "示范幼儿园")

        status, listed = self.client.get("/api/observations?limit=10")
        self.assertEqual(status, 200)
        self.assertEqual(listed["total"], 1)
        item = listed["items"][0]
        self.assertEqual(item["observation_id"], observation_id)
        self.assertEqual(item["subjects"], ["小明", "小红"])
        self.assertEqual(item["record_type"], "public")

        status, filtered = self.client.get(
            "/api/observations?subject=" + quote("小红")
        )
        self.assertEqual(status, 200)
        self.assertEqual(filtered["total"], 1)
        status, filtered = self.client.get(
            "/api/observations?subject=" + quote("小刚")
        )
        self.assertEqual(status, 200)
        self.assertEqual(filtered["total"], 0)
        status, filtered = self.client.get("/api/observations?unassigned=true")
        self.assertEqual(status, 200)
        self.assertEqual(filtered["total"], 0)
        status, filtered = self.client.get(
            "/api/observations?from=2026-09-16&to=2026-09-30"
        )
        self.assertEqual(filtered["total"], 0)

        request_id = str(uuid.uuid4())
        status, saved = self.client.patch(
            f"/api/observations/{observation_id}",
            {
                "request_id": request_id,
                "expected_revision": 1,
                "payload": {"observation_goal": "观察合作"},
                "save_reason": "manual",
            },
        )
        self.assertEqual(status, 200, saved)
        self.assertEqual(saved["revision"], 2)
        self.assertTrue(saved["history_created"])
        status, receipt = self.client.get(
            f"/api/observations/{observation_id}/operations/{request_id}"
        )
        self.assertEqual(status, 200, receipt)
        self.assertEqual(receipt["result"]["revision"], 2)
        # Same request id and body replays the committed result.
        status, replay = self.client.patch(
            f"/api/observations/{observation_id}",
            {
                "request_id": request_id,
                "expected_revision": 1,
                "payload": {"observation_goal": "观察合作"},
                "save_reason": "manual",
            },
        )
        self.assertEqual(status, 200, replay)
        self.assertEqual(replay["revision"], 2)
        # Same request id with a different body is refused.
        status, conflict = self.client.patch(
            f"/api/observations/{observation_id}",
            {
                "request_id": request_id,
                "expected_revision": 2,
                "payload": {"observation_goal": "不同内容"},
                "save_reason": "manual",
            },
        )
        self.assertEqual(status, 409, conflict)
        self.assertEqual(conflict["error"]["code"], "OBS_IDEMPOTENCY_CONFLICT")
        # Stale expected revision keeps the draft and reports the conflict.
        status, conflict = self.client.patch(
            f"/api/observations/{observation_id}",
            {
                "request_id": str(uuid.uuid4()),
                "expected_revision": 1,
                "payload": {"observation_goal": "旧版本"},
                "save_reason": "manual",
            },
        )
        self.assertEqual(status, 409, conflict)
        self.assertEqual(conflict["error"]["code"], "OBS_REVISION_CONFLICT")
        # Auto save changes the draft but never creates a history node.
        status, auto = self.client.patch(
            f"/api/observations/{observation_id}",
            {
                "request_id": str(uuid.uuid4()),
                "expected_revision": 2,
                "payload": {"observation_goal": "自动保存目标"},
                "save_reason": "auto",
            },
        )
        self.assertEqual(status, 200, auto)
        self.assertEqual(auto["revision"], 3)
        self.assertFalse(auto["history_created"])
        status, history = self.client.get(f"/api/observations/{observation_id}/history")
        self.assertEqual(status, 200)
        self.assertEqual(len(history), 1)
        # The daily task list keeps its source boundary.
        status, tasks = self.client.get("/api/local/ai/tasks")
        self.assertEqual(status, 200)
        self.assertEqual(tasks["items"], [])

    def test_basic_info_only_leave_still_retains_history(self):
        created = self.create(
            payload={
                "observation_date": "2026-09-15",
                "subjects": [{"name": "小明"}],
                "environment": "积木区",
            }
        )
        observation_id = created["observation_id"]
        status, saved = self.save(
            observation_id,
            {},
            reason="leave",
        )
        self.assertEqual(status, 200, saved)
        self.assertTrue(saved["history_created"])
        self.assertIsNotNone(saved["current_version"])
        self.assertGreaterEqual(saved["current_version"], 1)

    # -- term decision ------------------------------------------------------
    def test_cross_term_date_change_requires_an_explicit_decision(self):
        created = self.create(
            payload={"observation_date": "2026-09-15"},
        )
        observation_id = created["observation_id"]
        current = self.current(observation_id)
        self.assertEqual(current["payload"]["term_id"], self.term_id())
        status, result = self.save(
            observation_id,
            {"observation_date": "2026-02-10"},
        )
        self.assertEqual(status, 409, result)
        self.assertEqual(result["error"]["code"], "OBS_TERM_DECISION_REQUIRED")
        options = result["error"]["details"]["options"]
        self.assertTrue(options)
        selected = options[0]["term_id"]
        status, saved = self.save(
            observation_id,
            {"observation_date": "2026-02-10"},
            term_decision="assign_selected",
            selected_term_id=selected,
        )
        self.assertEqual(status, 200, saved)
        current = self.current(observation_id)
        self.assertEqual(current["payload"]["term_id"], selected)
        # A later edit within the assigned term needs no new decision.
        status, saved = self.save(observation_id, {"observation_goal": "观察"})
        self.assertEqual(status, 200, saved)

    def term_id(self):
        status, context = self.client.get("/api/local/context")
        self.assertEqual(status, 200)
        return context["terms"][0]["id"]

    # -- photos -------------------------------------------------------------
    def test_photo_import_caption_order_remove_and_binary_read(self):
        created = self.create(payload={"observation_date": "2026-09-15"})
        observation_id = created["observation_id"]
        status, first, _headers = self.upload(observation_id, self.jpeg(), caption="第一张")
        self.assertEqual(status, 201, first)
        status, second, _headers = self.upload(
            observation_id, self.jpeg((30, 30, 200)), caption=None
        )
        self.assertEqual(status, 201, second)
        status, photos = self.client.get(f"/api/observations/{observation_id}/photos")
        self.assertEqual(status, 200)
        self.assertEqual([item["caption"] for item in photos], ["第一张", None])
        self.assertEqual([item["sort_order"] for item in photos], [0, 1])
        asset_id = photos[0]["asset_id"]
        status, _body, headers = self.raw(
            "GET",
            f"/api/observations/{observation_id}/photos/{asset_id}/derivatives/ai/content",
        )
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("content-type"), "image/jpeg")
        self.assertGreater(len(_body), 0)
        status, _body, headers = self.raw(
            "GET", f"/api/observations/{observation_id}/photos/{asset_id}/content"
        )
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("content-type"), "image/jpeg")
        # Caption update.
        status, captioned = self.client.patch(
            f"/api/observations/{observation_id}/photos/{asset_id}",
            {
                "request_id": str(uuid.uuid4()),
                "expected_revision": self.current(observation_id)["revision"],
                "caption": "新说明",
            },
        )
        self.assertEqual(status, 200, captioned)
        # Reorder by explicit id list.
        current = self.current(observation_id)
        ids = [item["asset_id"] for item in current["photos"]]
        status, reordered = self.client.post(
            f"/api/observations/{observation_id}/photos/order",
            {
                "request_id": str(uuid.uuid4()),
                "expected_revision": current["revision"],
                "asset_ids": list(reversed(ids)),
            },
        )
        self.assertEqual(status, 200, reordered)
        self.assertEqual(
            [item["asset_id"] for item in reordered["photos"]],
            list(reversed(ids)),
        )
        # Remove the second asset only from the current association.
        current = self.current(observation_id)
        removed_id = current["photos"][1]["asset_id"]
        status, removed = self.client.request(
            "DELETE",
            f"/api/observations/{observation_id}/photos/{removed_id}",
            {
                "request_id": str(uuid.uuid4()),
                "expected_revision": current["revision"],
            },
        )
        self.assertEqual(status, 200, removed)
        self.assertEqual(len(removed["photos"]), 1)

    # -- history / restore --------------------------------------------------
    def test_history_preview_and_restore_keep_the_current_draft_protected(self):
        observation_id, _asset = self.ready_observation()
        # A manual save with content creates version 2.
        status, saved = self.save(
            observation_id, {"observation_process": "第二版正文"}
        )
        self.assertEqual(status, 200, saved)
        status, history = self.client.get(f"/api/observations/{observation_id}/history")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(len(history), 2)
        oldest = history[-1]["version"]
        status, detail = self.client.get(
            f"/api/observations/{observation_id}/history/{oldest}"
        )
        self.assertEqual(status, 200, detail)
        self.assertIn("payload", detail)
        # Preview needs a protected current draft (latest retained = current).
        current = self.current(observation_id)
        preview_request_id = str(uuid.uuid4())
        status, preview = self.client.post(
            f"/api/observations/{observation_id}/history/preview-restore",
            {
                "request_id": preview_request_id,
                "source_version": oldest,
                "base_draft_revision": current["revision"],
                "base_draft_hash": current["payload_hash"],
                "term_decision": "keep_history",
            },
        )
        self.assertEqual(status, 200, preview)
        self.assertTrue(preview["restore_token"])
        request_id = preview_request_id
        status, restored = self.client.post(
            f"/api/observations/{observation_id}/history/restore",
            {
                "request_id": request_id,
                "restore_token": preview["restore_token"],
                "expected_base_revision": preview["base_draft_revision"],
                "expected_base_hash": preview["base_draft_hash"],
                "term_decision": "keep_history",
            },
        )
        self.assertEqual(status, 200, restored)
        self.assertTrue(restored["changed"])
        status, receipt = self.client.get(
            f"/api/observations/{observation_id}/history/restore-operations/{request_id}"
        )
        self.assertEqual(status, 200, receipt)
        self.assertEqual(receipt["result"]["revision"], restored["revision"])
        # A second restore of the now-current version is an unchanged receipt.
        current = self.current(observation_id)
        preview2_request_id = str(uuid.uuid4())
        status, preview2 = self.client.post(
            f"/api/observations/{observation_id}/history/preview-restore",
            {
                "request_id": preview2_request_id,
                "source_version": restored["result_version"],
                "base_draft_revision": current["revision"],
                "base_draft_hash": current["payload_hash"],
                "term_decision": "keep_history",
            },
        )
        self.assertEqual(status, 200, preview2)
        status, unchanged = self.client.post(
            f"/api/observations/{observation_id}/history/restore",
            {
                "request_id": preview2_request_id,
                "restore_token": preview2["restore_token"],
                "expected_base_revision": preview2["base_draft_revision"],
                "expected_base_hash": preview2["base_draft_hash"],
                "term_decision": "keep_history",
            },
        )
        self.assertEqual(status, 200, unchanged)
        self.assertFalse(unchanged["changed"])

    # -- AI task / candidate / adoption ------------------------------------
    def test_ai_task_candidate_preview_and_adopt_over_http(self):
        self.configure_ai()
        observation_id, _asset = self.ready_observation()
        executor = ai_executor.AiExecutor(
            self.runtime, worker_target=observation_worker_entry
        )
        executor.start()
        self.addCleanup(executor.dispose)
        # Restart the API with the live executor (same runtime).
        self.server.stop()
        self.server = self.start_server(self.runtime, executor=executor)
        self.client = self.server.client()
        current = self.current(observation_id)
        task_request_id = str(uuid.uuid4())
        status, task = self.client.post(
            f"/api/observations/{observation_id}/ai-tasks",
            {
                "request_id": task_request_id,
                "task_type": "game_observation_generate",
                "expected_revision": current["revision"],
                "expected_hash": current["payload_hash"],
            },
        )
        self.assertEqual(status, 202, task)
        task_id = task["id"]
        status, task_receipt = self.client.get(
            f"/api/observations/{observation_id}/ai-operations/{task_request_id}"
        )
        self.assertEqual(status, 200, task_receipt)
        self.assertEqual(task_receipt["result"]["id"], task_id)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            status, task = self.client.get(
                f"/api/observations/{observation_id}/ai-tasks/{task_id}"
            )
            self.assertEqual(status, 200, task)
            if task["status"] in ("succeeded", "failed", "paused", "outcome_unknown"):
                break
            time.sleep(0.1)
        self.assertEqual(task["status"], "succeeded", task)
        status, candidates = self.client.get(
            f"/api/observations/{observation_id}/ai-candidates"
        )
        self.assertEqual(status, 200, candidates)
        self.assertTrue(candidates["items"])
        candidate_id = candidates["items"][-1]["id"]
        status, detail = self.client.get(
            f"/api/observations/{observation_id}/ai-candidates/{candidate_id}"
        )
        self.assertEqual(status, 200, detail)
        self.assertIn("raw_candidate", detail)
        current = self.current(observation_id)
        status, preview = self.client.post(
            f"/api/observations/{observation_id}/ai-candidates/{candidate_id}/preview-adoption",
            {
                "request_id": str(uuid.uuid4()),
                "expected_revision": current["revision"],
                "expected_hash": current["payload_hash"],
                "selected_targets": ["observation_goal"],
            },
        )
        self.assertEqual(status, 200, preview)
        self.assertTrue(preview["adoption_token"])
        status, adopted = self.client.post(
            f"/api/observations/{observation_id}/ai-candidates/{candidate_id}/adopt",
            {
                "request_id": str(uuid.uuid4()),
                "expected_revision": current["revision"],
                "expected_hash": current["payload_hash"],
                "selected_targets": ["observation_goal"],
                "preview_token": preview["adoption_token"],
            },
        )
        self.assertEqual(status, 200, adopted)
        self.assertTrue(adopted["changed"])
        self.assertEqual(adopted["selected_targets"], ["observation_goal"])
        updated = self.current(observation_id)
        self.assertNotEqual(
            updated["payload"]["observation_goal"], "观察合作"
        )
        # A consumed adoption token maps to the observation-domain stale code.
        status, preview2 = self.client.post(
            f"/api/observations/{observation_id}/ai-candidates/{candidate_id}/preview-adoption",
            {
                "request_id": str(uuid.uuid4()),
                "expected_revision": updated["revision"],
                "expected_hash": updated["payload_hash"],
                "selected_targets": ["observation_goal"],
            },
        )
        self.assertEqual(status, 200, preview2)
        status, adopted2 = self.client.post(
            f"/api/observations/{observation_id}/ai-candidates/{candidate_id}/adopt",
            {
                "request_id": str(uuid.uuid4()),
                "expected_revision": updated["revision"],
                "expected_hash": updated["payload_hash"],
                "selected_targets": ["observation_goal"],
                "preview_token": preview2["adoption_token"],
            },
        )
        self.assertEqual(status, 200, adopted2)
        status, stale = self.client.post(
            f"/api/observations/{observation_id}/ai-candidates/{candidate_id}/adopt",
            {
                "request_id": str(uuid.uuid4()),
                "expected_revision": adopted2["revision"],
                "expected_hash": adopted2["payload_hash"],
                "selected_targets": ["observation_goal"],
                "preview_token": preview2["adoption_token"],
            },
        )
        self.assertEqual(status, 409, stale)
        self.assertEqual(stale["error"]["code"], "OBS_AI_CANDIDATE_STALE")
        # Observation task list is scoped to this record and source.
        status, listed = self.client.get(
            f"/api/observations/{observation_id}/ai-tasks"
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(listed["items"]), 1)
        status, source_listed = self.client.get(
            "/api/local/ai/observation-tasks"
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(source_listed["items"]), 1)
        # The daily task list still refuses to expose observation tasks.
        status, daily = self.client.get("/api/local/ai/tasks")
        self.assertEqual(status, 200)
        self.assertEqual(daily["items"], [])


    # -- R01 / R13: list ranges, strict multipart, typed retry ---------------
    def test_list_without_range_keeps_no_date_and_old_term_records(self):
        no_date = self.create(payload=None, observation_date=None)
        old_term = self.create(payload={"observation_date": "2026-09-15"})
        status, listed = self.client.get("/api/observations?limit=50")
        self.assertEqual(status, 200)
        ids = {item["observation_id"] for item in listed["items"]}
        self.assertIn(no_date["observation_id"], ids)
        self.assertIn(old_term["observation_id"], ids)
        status, ranged = self.client.get(
            "/api/observations?from=2026-10-01&to=2026-10-31"
        )
        self.assertEqual(status, 200)
        self.assertEqual(ranged["total"], 0)
        status, unassigned = self.client.get("/api/observations?unassigned=true")
        self.assertEqual(status, 200)
        self.assertEqual(unassigned["total"], 1)
        term_id = self.term_id()
        status, by_term = self.client.get(f"/api/observations?term_id={term_id}")
        self.assertEqual(status, 200)
        self.assertEqual(by_term["total"], 1)
        self.assertEqual(
            by_term["items"][0]["observation_id"], old_term["observation_id"]
        )

    def _strict_multipart(self, observation_id, file_bytes, boundary):
        current = self.current(observation_id)
        fields = {
            "request_id": str(uuid.uuid4()),
            "expected_revision": str(current["revision"]),
            "display_name": "strict.jpg",
        }
        body = bytearray()
        for key, value in fields.items():
            body += (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'
                f"{value}\r\n"
            ).encode("utf-8")
        body += (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="strict.jpg"\r\n'
            "Content-Type: image/jpeg\r\n\r\n"
        ).encode("utf-8")
        body += file_bytes + b"\r\n"
        body += f"--{boundary}--\r\n".encode("utf-8")
        return bytes(body), boundary

    def test_multipart_requires_final_boundary_and_preserves_payload_bytes(self):
        created = self.create(payload={"observation_date": "2026-09-15"})
        observation_id = created["observation_id"]
        boundary = "----kgmstrict" + uuid.uuid4().hex
        jpeg = self.jpeg()
        # A delimiter-like substring that is not at a line-start boundary must
        # stay part of the file bytes (the image decoder may ignore trailing
        # bytes; the stored original must remain byte-exact).
        file_bytes = jpeg + b"xx--" + boundary.encode() + b"yy"
        body, boundary = self._strict_multipart(
            observation_id, file_bytes, boundary
        )
        status, uploaded, _headers = self.raw(
            "POST",
            f"/api/observations/{observation_id}/photos",
            body,
            content_type=f"multipart/form-data; boundary={boundary}",
        )
        self.assertEqual(status, 201, uploaded)
        asset_id = uploaded["asset_id"]
        status, data, _headers = self.raw(
            "GET",
            f"/api/observations/{observation_id}/photos/{asset_id}/content",
        )
        self.assertEqual(status, 200)
        self.assertEqual(data, file_bytes)
        # A missing final boundary is rejected before any decode.
        truncated = body.replace(f"--{boundary}--\r\n".encode("utf-8"), b"")
        status, rejected, _headers = self.raw(
            "POST",
            f"/api/observations/{observation_id}/photos",
            truncated,
            content_type=f"multipart/form-data; boundary={boundary}",
        )
        self.assertEqual(status, 422, rejected)
        self.assertEqual(rejected["error"]["code"], "OBS_MATERIAL_INVALID")
        # Trailing bytes after the final boundary are refused too.
        status, trailing, _headers = self.raw(
            "POST",
            f"/api/observations/{observation_id}/photos",
            body + b"garbage",
            content_type=f"multipart/form-data; boundary={boundary}",
        )
        self.assertEqual(status, 422, trailing)

    def test_retry_ack_must_be_a_real_boolean(self):
        created = self.create()
        observation_id = created["observation_id"]
        status, result = self.client.post(
            f"/api/observations/{observation_id}/ai-tasks/task-x/retry",
            {
                "request_id": str(uuid.uuid4()),
                "expected_execution_id": "exec-x",
                "ack_duplicate_cost": "false",
            },
        )
        self.assertEqual(status, 422, result)
        self.assertEqual(result["error"]["code"], "VALIDATION_ERROR")

    def configure_ai(self):
        version = (
            query_scalar(
                self.runtime.db_path,
                "SELECT current_config_version FROM local_ai_state",
            )
            or 0
        )
        ai_config_service.patch_config(
            self.session,
            expected_ai_config_version=version,
            base_url="https://api.deepseek.com/v1",
            model="deepseek-flash",
            secret="s3cret",
            secret_provided=True,
            request_id=str(uuid.uuid4()),
            credential_root=self.runtime.credential_root,
        )


if __name__ == "__main__":
    unittest.main()
