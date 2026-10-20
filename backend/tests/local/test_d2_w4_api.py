"""D2 W4 candidate/preview/adopt API tests over a real local HTTP server.

A real Uvicorn server on loopback, real ``http.client`` requests and the
W3-generated candidates (never inserted rows). The test process explicitly
isolates ``LOCALAPPDATA``/``credential_root`` via ``LocalTestCase`` and runs
with ``APP_DISABLE_DOTENV=1``. Direct SQL writes are fault injection and are
marked as such.
"""

from __future__ import annotations

import json
import threading
import unittest
import uuid
from datetime import date
from http.client import HTTPConnection
from unittest import mock

from app.local import ai_adoption  # noqa: F401 - reset in the shared base
from tests.local.support import (
    execute_sql,
    query_scalar,
)
from tests.local.test_d2_w4_candidates import (
    ADAPT_CANDIDATE,
    OTHER_CANDIDATE,
    SPLIT_CANDIDATE,
    W4Case,
)

BASELINE_KEY = "group_activity_process"


class W4ApiCase(W4Case):
    def setUp(self) -> None:
        super().setUp()
        self.configure_ai()
        self.plan = self.make_plan()
        self.start_api()

    def start_api(self) -> None:
        self.server = self.start_server(self.runtime)
        self.client = self.server.client()

    def restart_api(self) -> None:
        """A new app instance (new internal session scope) on the same runtime."""
        self.server.stop()
        self.start_api()

    # -- HTTP helpers ------------------------------------------------------
    def candidates_path(self, plan_id=None) -> str:
        return f"/api/daily-plans/{plan_id or self.plan['id']}/ai-candidates"

    def preview_http(
        self, candidate_id, selected, edited, *, expected=None, plan_id=None, **kwargs
    ):
        plan_id = plan_id or self.plan["id"]
        return self.client.post(
            f"{self.candidates_path(plan_id)}/{candidate_id}/preview-adoption",
            {
                "expected_content_version": expected
                if expected is not None
                else self.content_version(plan_id),
                "selected_targets": selected,
                "edited_candidate": edited,
            },
            **kwargs,
        )

    def adopt_http(
        self,
        candidate_id,
        token,
        *,
        request_id,
        expected=None,
        plan_id=None,
        **kwargs,
    ):
        plan_id = plan_id or self.plan["id"]
        return self.client.post(
            f"{self.candidates_path(plan_id)}/{candidate_id}/adopt",
            {
                "request_id": request_id,
                "expected_content_version": expected
                if expected is not None
                else self.content_version(plan_id),
                "preview_token": token,
            },
            **kwargs,
        )

    def raw_get(self, path):
        connection = HTTPConnection(self.client.host, self.client.port, timeout=30)
        try:
            connection.request(
                "GET",
                path,
                headers={
                    "X-App-Session": self.token,
                    "Host": f"{self.client.host}:{self.client.port}",
                },
            )
            response = connection.getresponse()
            body = response.read()
            headers = {k.lower(): v for k, v in response.getheaders()}
            return response.status, headers, body
        finally:
            connection.close()


class HttpFlowTests(W4ApiCase):
    def test_three_types_over_http(self):
        # Split.
        split_id = self.generate(self.plan["id"], "daily_lesson_split", SPLIT_CANDIDATE)
        status, preview = self.preview_http(split_id, ["group_activity"], SPLIT_CANDIDATE)
        self.assertEqual(status, 200, preview)
        status, adopted = self.adopt_http(
            split_id, preview["preview_token"], request_id=str(uuid.uuid4())
        )
        self.assertEqual(status, 200, adopted)
        self.assertTrue(adopted["changed"])
        status, plan = self.client.get(f"/api/daily-plans/{self.plan['id']}")
        self.assertEqual(status, 200, plan)
        self.assertEqual(
            plan["content"]["split_baseline"],
            {BASELINE_KEY: SPLIT_CANDIDATE["group_activity"]["process"]},
        )

        # Adapt (generated after the split adoption, on the new version).
        adapt_id = self.generate(self.plan["id"], "daily_process_adapt", ADAPT_CANDIDATE)
        status, preview = self.preview_http(
            adapt_id, ["group_activity.process"], ADAPT_CANDIDATE
        )
        self.assertEqual(status, 200, preview)
        status, adopted = self.adopt_http(
            adapt_id, preview["preview_token"], request_id=str(uuid.uuid4())
        )
        self.assertEqual(status, 200, adopted)
        self.assertTrue(adopted["changed"])

        # Other activities.
        other_id = self.generate(
            self.plan["id"], "daily_other_activities", OTHER_CANDIDATE
        )
        status, preview = self.preview_http(
            other_id, ["morning_games", "morning_talk"], OTHER_CANDIDATE
        )
        self.assertEqual(status, 200, preview)
        status, adopted = self.adopt_http(
            other_id, preview["preview_token"], request_id=str(uuid.uuid4())
        )
        self.assertEqual(status, 200, adopted)
        self.assertEqual(len(adopted["selected_targets"]), 2)

        status, plan = self.client.get(f"/api/daily-plans/{self.plan['id']}")
        self.assertEqual(status, 200)
        content = plan["content"]
        self.assertEqual(content["version"], 4)
        self.assertEqual(content["adopted_content"]["morning_talk"]["topic"], "今日话题")
        # The baseline survives adapt + other-activities adoption.
        self.assertEqual(
            content["split_baseline"],
            {BASELINE_KEY: SPLIT_CANDIDATE["group_activity"]["process"]},
        )

    def test_strict_schema_and_targets_over_http(self):
        candidate_id = self.generate(
            self.plan["id"], "daily_lesson_split", SPLIT_CANDIDATE
        )
        bad_edits = [
            {**SPLIT_CANDIDATE, "unknown": 1},
            {"group_activity": {**SPLIT_CANDIDATE["group_activity"], "theme": None}},
            {"group_activity": {**SPLIT_CANDIDATE["group_activity"], "group_id": "x"}},
            {
                "group_activity": {
                    **SPLIT_CANDIDATE["group_activity"],
                    "split_baseline": {"group_activity_process": "forged"},
                }
            },
            {**SPLIT_CANDIDATE, "reflection": "不应带反思"},
        ]
        for edited in bad_edits:
            with self.subTest(edited=str(edited)[:48]):
                status, body = self.preview_http(candidate_id, ["group_activity"], edited)
                self.assertEqual(status, 422, body)
                self.assertEqual(body["error"]["code"], "VALIDATION_ERROR")
        for selected in ([], ["group_activity", "group_activity"], ["nope"]):
            with self.subTest(selected=selected):
                status, body = self.preview_http(candidate_id, selected, SPLIT_CANDIDATE)
                self.assertEqual(status, 422, body)

    def test_list_and_detail_no_material_and_no_store(self):
        candidate_id = self.generate(
            self.plan["id"], "daily_lesson_split", SPLIT_CANDIDATE
        )
        status, headers, body = self.raw_get(self.candidates_path())
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("cache-control"), "no-store")
        listed = json.loads(body.decode("utf-8"))
        self.assertEqual(len(listed["items"]), 1)
        self.assertNotIn("raw_candidate", listed["items"][0])
        self.assertNotIn("source", listed["items"][0])

        status, detail = self.client.get(f"{self.candidates_path()}/{candidate_id}")
        self.assertEqual(status, 200, detail)
        self.assertIn("raw_candidate", detail)
        self.assertIn("dependencies", detail["source"])
        self.assertIn("source_excerpt", detail["source"])
        # A plan that does not own the candidate gets a plain 404.
        other_plan = self.make_plan(plan_date=date(2026, 9, 3))
        status, body = self.client.get(
            f"{self.candidates_path(other_plan['id'])}/{candidate_id}"
        )
        self.assertEqual(status, 404, body)
        self.assertEqual(body["error"]["code"], "AI_NOT_FOUND")
        status, body = self.client.get(f"{self.candidates_path()}/does-not-exist")
        self.assertEqual(status, 404, body)

    def test_host_origin_session_protection(self):
        path = self.candidates_path()
        status, _body = self.client.get(path, token=None)
        self.assertEqual(status, 401)
        status, _body = self.client.get(path, host="evil.example")
        self.assertEqual(status, 403)
        body = {
            "expected_content_version": 1,
            "selected_targets": ["group_activity"],
            "edited_candidate": SPLIT_CANDIDATE,
        }
        status, _body = self.client.post(
            f"{path}/whatever/preview-adoption", body, origin=None
        )
        self.assertEqual(status, 403)
        status, _body = self.client.post(
            f"{path}/whatever/preview-adoption", body, origin="http://evil.example"
        )
        self.assertEqual(status, 403)

    def test_preview_wrong_version_conflict(self):
        candidate_id = self.generate(
            self.plan["id"], "daily_lesson_split", SPLIT_CANDIDATE
        )
        status, body = self.preview_http(
            candidate_id, ["group_activity"], SPLIT_CANDIDATE, expected=9
        )
        self.assertEqual(status, 409, body)
        self.assertEqual(body["error"]["code"], "VERSION_CONFLICT")
        self.assertEqual(body["error"]["details"]["current_content_version"], 1)

    def test_source_and_target_change_over_http(self):
        candidate_id = self.generate(
            self.plan["id"], "daily_lesson_split", SPLIT_CANDIDATE
        )
        status, preview = self.preview_http(candidate_id, ["group_activity"], SPLIT_CANDIDATE)
        self.assertEqual(status, 200)
        token = preview["preview_token"]
        # Source change: the raw lesson plan is saved anew.
        self.save_content(
            self.plan["id"],
            1,
            {
                "group_activity": {"process": "一、导入\n二、观察"},
                "reflection": "反思",
            },
            raw="新的原文",
        )
        status, body = self.adopt_http(candidate_id, token, request_id=str(uuid.uuid4()), expected=1)
        self.assertEqual(status, 409, body)
        self.assertEqual(body["error"]["code"], "AI_SOURCE_CHANGED")
        self.assertIn("raw_lesson_plan", body["error"]["details"]["changed_fields"])

        # Target change: only the collective activity is edited, source valid.
        candidate_id2 = self.generate(
            self.plan["id"], "daily_lesson_split", SPLIT_CANDIDATE
        )
        status, preview2 = self.preview_http(
            candidate_id2, ["group_activity"], SPLIT_CANDIDATE
        )
        self.assertEqual(status, 200)
        version = self.content_version(self.plan["id"])
        self.save_content(
            self.plan["id"],
            version,
            {
                "group_activity": {
                    "process": "一、导入\n二、观察",
                    "theme": "教师主题",
                },
                "reflection": "反思",
            },
            raw="新的原文",
        )
        status, body = self.adopt_http(
            candidate_id2, preview2["preview_token"], request_id=str(uuid.uuid4()), expected=version
        )
        self.assertEqual(status, 409, body)
        self.assertEqual(body["error"]["code"], "AI_TARGET_CHANGED")


class HttpIdempotencyTests(W4ApiCase):
    def test_lost_response_and_restart_receipt(self):
        candidate_id = self.generate(
            self.plan["id"], "daily_lesson_split", SPLIT_CANDIDATE
        )
        status, preview = self.preview_http(candidate_id, ["group_activity"], SPLIT_CANDIDATE)
        self.assertEqual(status, 200)
        token = preview["preview_token"]
        rid = str(uuid.uuid4())
        status, first = self.adopt_http(candidate_id, token, request_id=rid, expected=1)
        self.assertEqual(status, 200, first)
        # Same key/body after the token was consumed replays the result.
        status, replay = self.adopt_http(candidate_id, token, request_id=rid, expected=1)
        self.assertEqual(status, 200, replay)
        self.assertEqual(replay, first)
        # ...and still replays after a full app restart (receipt persists).
        self.restart_api()
        status, replay2 = self.adopt_http(candidate_id, token, request_id=rid, expected=1)
        self.assertEqual(status, 200, replay2)
        self.assertEqual(replay2, first)
        # The operation receipt is queryable.
        status, receipt = self.client.get(f"/api/local/ai/operations/{rid}")
        self.assertEqual(status, 200, receipt)
        self.assertEqual(receipt["operation_kind"], "ai_candidate_adopt")
        self.assertEqual(receipt["result"]["content_version"], 2)
        self.assertEqual(self.content_version(self.plan["id"]), 2)

    def test_new_app_session_rejects_old_token(self):
        candidate_id = self.generate(
            self.plan["id"], "daily_lesson_split", SPLIT_CANDIDATE
        )
        status, preview = self.preview_http(candidate_id, ["group_activity"], SPLIT_CANDIDATE)
        self.assertEqual(status, 200)
        token = preview["preview_token"]
        # A fresh app instance has a new internal session scope: the old token
        # is refused even on the same runtime.
        self.restart_api()
        status, body = self.adopt_http(candidate_id, token, request_id=str(uuid.uuid4()), expected=1)
        self.assertEqual(status, 409, body)
        self.assertEqual(body["error"]["code"], "AI_PREVIEW_EXPIRED")
        self.assertEqual(self.content_version(self.plan["id"]), 1)


class HttpConcurrencyTests(W4ApiCase):
    def _run_two(self, worker, results):
        barrier = threading.Barrier(2)

        def target(index):
            barrier.wait()
            results[index] = worker(index)

        threads = [threading.Thread(target=target, args=(i,)) for i in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        for thread in threads:
            self.assertFalse(thread.is_alive(), "concurrent request did not finish")

    def test_concurrent_different_tokens_single_success(self):
        candidate_id = self.generate(
            self.plan["id"], "daily_lesson_split", SPLIT_CANDIDATE
        )
        tokens = []
        for _ in range(2):
            status, preview = self.preview_http(
                candidate_id, ["group_activity"], SPLIT_CANDIDATE
            )
            self.assertEqual(status, 200)
            tokens.append(preview["preview_token"])
        results: list = [None, None]

        def worker(index):
            return self.adopt_http(
                candidate_id,
                tokens[index],
                request_id=str(uuid.uuid4()),
                expected=1,
            )

        self._run_two(worker, results)
        statuses = sorted(status for status, _body in results)
        self.assertEqual(statuses, [200, 409], results)
        loser = next(body for status, body in results if status == 409)
        self.assertIn(
            loser["error"]["code"], ("AI_TARGET_CHANGED", "VERSION_CONFLICT")
        )
        # Exactly one version was appended and one adopt receipt committed.
        self.assertEqual(self.content_version(self.plan["id"]), 2)
        self.assertEqual(
            query_scalar(
                self.db,
                "SELECT count(*) FROM local_ai_operations WHERE operation_kind = 'ai_candidate_adopt'",
            ),
            1,
        )
        self.assertEqual(
            query_scalar(self.db, "SELECT count(*) FROM local_daily_plan_contents"), 2
        )

    def test_same_token_same_key_replays_under_deterministic_race(self):
        """R09: a same-token/same-key duplicate replays 200, never 409.

        The first request is deterministically paused *after* its receipt read
        and *before* its token lookup; the second (same token, same key) then
        commits and consumes the token. The first must read the committed
        receipt on resume instead of reporting an expired preview.
        """
        candidate_id = self.generate(
            self.plan["id"], "daily_lesson_split", SPLIT_CANDIDATE
        )
        status, preview = self.preview_http(candidate_id, ["group_activity"], SPLIT_CANDIDATE)
        self.assertEqual(status, 200)
        token = preview["preview_token"]
        rid = str(uuid.uuid4())

        real_get = ai_adoption._TOKENS.get
        arrived = threading.Event()
        release = threading.Event()
        gate = {"used": False}
        gate_lock = threading.Lock()

        def gated_get(value):
            with gate_lock:
                block = not gate["used"]
                if block:
                    gate["used"] = True
            if block:
                arrived.set()
                release.wait(timeout=30)
            return real_get(value)

        results: dict = {}

        def first_request():
            results["first"] = self.adopt_http(
                candidate_id, token, request_id=rid, expected=1
            )

        with mock.patch.object(ai_adoption._TOKENS, "get", side_effect=gated_get):
            thread = threading.Thread(target=first_request)
            thread.start()
            self.assertTrue(
                arrived.wait(timeout=30), "first request never reached token lookup"
            )
            # The second identical request runs to completion while the first
            # is paused inside its token lookup.
            results["second"] = self.adopt_http(
                candidate_id, token, request_id=rid, expected=1
            )
            release.set()
            thread.join(timeout=60)
        self.assertFalse(thread.is_alive(), "first request did not finish")

        first_status, first_body = results["first"]
        second_status, second_body = results["second"]
        self.assertEqual(second_status, 200, second_body)
        self.assertEqual(first_status, 200, first_body)
        self.assertEqual(first_body, second_body)
        # Exactly one version and one committed receipt.
        self.assertEqual(self.content_version(self.plan["id"]), 2)
        self.assertEqual(
            query_scalar(self.db, "SELECT count(*) FROM local_daily_plan_contents"), 2
        )
        self.assertEqual(
            query_scalar(
                self.db,
                "SELECT count(*) FROM local_ai_operations WHERE operation_kind = 'ai_candidate_adopt'",
            ),
            1,
        )


class HttpCorruptionTests(W4ApiCase):
    def test_malformed_candidate_row_is_503(self):
        candidate_id = self.generate(
            self.plan["id"], "daily_lesson_split", SPLIT_CANDIDATE
        )
        status, preview = self.preview_http(candidate_id, ["group_activity"], SPLIT_CANDIDATE)
        self.assertEqual(status, 200)
        # Fault injection: the JSON column holds non-JSON text.
        execute_sql(
            self.db,
            "UPDATE local_ai_candidates SET raw_candidate_json = 'not-json' WHERE id = ?",
            (candidate_id,),
        )
        status, body = self.client.get(f"{self.candidates_path()}/{candidate_id}")
        self.assertEqual(status, 503, body)
        self.assertEqual(body["error"]["code"], "LOCAL_STORAGE_ERROR")
        status, body = self.client.get(self.candidates_path())
        self.assertEqual(status, 503, body)
        self.assertEqual(body["error"]["code"], "LOCAL_STORAGE_ERROR")
        status, body = self.preview_http(candidate_id, ["group_activity"], SPLIT_CANDIDATE)
        self.assertEqual(status, 503, body)
        status, body = self.adopt_http(
            candidate_id, preview["preview_token"], request_id=str(uuid.uuid4()), expected=1
        )
        self.assertEqual(status, 503, body)
        # The plan itself is still readable (never written into an unreadable
        # state by the corrupt candidate).
        status, plan = self.client.get(f"/api/daily-plans/{self.plan['id']}")
        self.assertEqual(status, 200, plan)
        self.assertEqual(plan["content"]["version"], 1)

    def test_foreign_corrupt_candidate_is_404_not_503(self):
        # A candidate that belongs to another plan.
        other_plan = self.make_plan(plan_date=date(2026, 9, 3))
        foreign_id = self.generate(
            other_plan["id"], "daily_lesson_split", SPLIT_CANDIDATE
        )
        # Fault injection: corrupt the *foreign* candidate's JSON.
        execute_sql(
            self.db,
            "UPDATE local_ai_candidates SET raw_candidate_json = 'not-json' WHERE id = ?",
            (foreign_id,),
        )
        # Requested through plan A: a foreign plan id must still be a plain 404,
        # never a 503 from decoding the other plan's corrupt row.
        status, body = self.client.get(f"{self.candidates_path()}/{foreign_id}")
        self.assertEqual(status, 404, body)
        self.assertEqual(body["error"]["code"], "AI_NOT_FOUND")
        status, body = self.preview_http(foreign_id, ["group_activity"], SPLIT_CANDIDATE)
        self.assertEqual(status, 404, body)
        self.assertEqual(body["error"]["code"], "AI_NOT_FOUND")
        # The owning plan still sees the corrupt row as a storage error.
        status, body = self.client.get(
            f"{self.candidates_path(other_plan['id'])}/{foreign_id}"
        )
        self.assertEqual(status, 503, body)
        self.assertEqual(body["error"]["code"], "LOCAL_STORAGE_ERROR")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
