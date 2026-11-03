"""A G1 weekly AI HTTP route tests over a real loopback server."""

from __future__ import annotations

import uuid

from app.local import weekly_ai_adoption
from app.local.models import LocalAICandidate, LocalAIExecution, LocalAIInput
from tests.local.support import LocalTestCase
from tests.local.test_weekly_ai_service import WeeklyAIServiceFixture


class _StubExecutor:
    def __init__(self):
        self.frozen = False
        self.notified = 0

    def is_runnable(self):
        return True

    def notify(self):
        self.notified += 1
        return None

    def is_frozen(self):
        return self.frozen


class WeeklyAIApiTests(WeeklyAIServiceFixture):
    def setUp(self):
        super().setUp()
        self.executor = _StubExecutor()
        self.server = self.start_server(self.runtime, executor=self.executor)
        self.client = self.server.client()

    def _path(self, suffix=""):
        return f"/api/weekly-plans/{self.plan_id}/ai{suffix}"

    def test_create_replay_task_operation_and_wrong_plan_scope(self):
        body = {
            "request_id": str(uuid.uuid4()),
            "expected_draft_version": self.version,
        }
        status, payload = self.client.post(self._path("/games"), body)
        self.assertEqual(status, 202, payload)
        self.assertFalse(payload["replayed"])
        task_id = payload["tasks"][0]["task_id"]
        status, replay = self.client.post(self._path("/games"), body)
        self.assertEqual(status, 200, replay)
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["tasks"], payload["tasks"])
        status, tasks = self.client.get(self._path("/tasks"))
        self.assertEqual(status, 200, tasks)
        self.assertEqual([item["task_id"] for item in tasks["items"]], [task_id])
        self.assertEqual(tasks["items"][0]["target"], "games")
        self.assertNotIn("plan_id", tasks["items"][0])
        status, task = self.client.get(self._path(f"/tasks/{task_id}"))
        self.assertEqual(status, 200, task)
        self.assertEqual(task["weekly_plan_id"], self.plan_id)
        status, progress = self.client.get(self._path(f"/tasks/{task_id}/progress"))
        self.assertEqual(status, 200, progress)
        self.assertEqual(progress["task_id"], task_id)
        self.assertNotIn("plan_id", progress)
        status, operation = self.client.get(
            self._path(f"/operations/{body['request_id']}")
        )
        self.assertEqual(status, 200, operation)
        self.assertEqual(operation["result"]["tasks"], payload["tasks"])
        # A GET of an unknown key says "not found", never "not submitted": the
        # original request key still has its committed receipt.
        status, unknown = self.client.get(self._path(f"/operations/{uuid.uuid4()}"))
        self.assertEqual(status, 404, unknown)
        status, replay_after_404 = self.client.post(self._path("/games"), body)
        self.assertEqual(status, 200, replay_after_404)
        self.assertTrue(replay_after_404["replayed"])
        self.assertEqual(replay_after_404["tasks"], payload["tasks"])
        status, _ = self.client.get(
            f"/api/weekly-plans/not-this-plan/ai/tasks/{task_id}"
        )
        self.assertEqual(status, 404)
        status, wrong_plan_tasks = self.client.get(
            "/api/weekly-plans/not-this-plan/ai/tasks"
        )
        self.assertEqual(status, 404, wrong_plan_tasks)
        self.assertEqual(wrong_plan_tasks["error"]["code"], "AI_NOT_FOUND")

    def test_frozen_adopt_rejects_before_token_consumption_and_replays_after(self):
        _task_id, candidate_id = self._succeed_games()
        scope = self.server.app.state.session_scope
        preview = weekly_ai_adoption.preview_adoption(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            plan_id=self.plan_id,
            expected_draft_version=self.version,
            selections=[{"candidate_id": candidate_id, "target": "games"}],
            launch_id=self.runtime.launch_id,
            session_scope_hash=scope,
        )
        body = {
            "request_id": str(uuid.uuid4()),
            "expected_draft_version": self.version,
            "preview_token": preview["preview_token"],
        }
        self.executor.frozen = True
        status, rejected = self.client.post(self._path("/adopt"), body)
        self.assertEqual(status, 503, rejected)
        self.assertEqual(rejected["error"]["code"], "AI_EXECUTOR_UNAVAILABLE")
        self.executor.frozen = False
        status, adopted = self.client.post(self._path("/adopt"), body)
        self.assertEqual(status, 200, adopted)
        self.assertFalse(adopted["replayed"])
        self.executor.frozen = True
        status, replay = self.client.post(self._path("/adopt"), body)
        self.assertEqual(status, 200, replay)
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["draft"], adopted["draft"])

    def test_corrupt_stored_candidate_is_503_for_candidate_and_preview(self):
        _task_id, candidate_id = self._succeed_games()
        candidate = self.session.get(LocalAICandidate, candidate_id)
        candidate.raw_candidate_json = {"outdoor_game_slots": {}, "focus_area": None}
        self.session.commit()
        status, detail = self.client.get(self._path(f"/candidates/{candidate_id}"))
        self.assertEqual(status, 503, detail)
        self.assertEqual(detail["error"]["code"], "LOCAL_STORAGE_ERROR")
        status, preview = self.client.post(
            self._path("/adoption-preview"),
            {
                "expected_draft_version": self.version,
                "selections": [{"candidate_id": candidate_id, "target": "games"}],
            },
        )
        self.assertEqual(status, 503, preview)
        self.assertEqual(preview["error"]["code"], "LOCAL_STORAGE_ERROR")

    def test_frozen_executor_rejects_new_create_but_receipt_replays(self):
        body = {
            "request_id": str(uuid.uuid4()),
            "expected_draft_version": self.version,
        }
        status, first = self.client.post(self._path("/games"), body)
        self.assertEqual(status, 202, first)
        self.executor.frozen = True
        status, replay = self.client.post(self._path("/games"), body)
        self.assertEqual(status, 200, replay)
        self.assertTrue(replay["replayed"])
        status, rejected = self.client.post(
            self._path("/games"),
            {"request_id": str(uuid.uuid4()), "expected_draft_version": self.version},
        )
        self.assertEqual(status, 503, rejected)
        self.assertEqual(rejected["error"]["code"], "AI_EXECUTOR_UNAVAILABLE")

    def test_adopt_works_without_executor_when_not_frozen(self):
        _task_id, candidate_id = self._succeed_games()
        self.server.stop()
        self.server = self.start_server(self.runtime, executor=None)
        self.client = self.server.client()
        scope = self.server.app.state.session_scope
        preview = weekly_ai_adoption.preview_adoption(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            plan_id=self.plan_id,
            expected_draft_version=self.version,
            selections=[{"candidate_id": candidate_id, "target": "games"}],
            launch_id=self.runtime.launch_id,
            session_scope_hash=scope,
        )
        status, adopted = self.client.post(
            self._path("/adopt"),
            {
                "request_id": str(uuid.uuid4()),
                "expected_draft_version": self.version,
                "preview_token": preview["preview_token"],
            },
        )
        self.assertEqual(status, 200, adopted)
        self.assertEqual(adopted["draft"]["version"], self.version + 1)

    def test_old_contract_candidate_detail_is_readable_but_preview_is_409(self):
        _task_id, candidate_id = self._succeed_games()
        status, current = self.client.get(self._path(f"/candidates/{candidate_id}"))
        self.assertEqual(status, 200, current)
        self.assertEqual(current["eligibility"], "eligible")

        candidate = self.session.get(LocalAICandidate, candidate_id)
        execution = self.session.get(LocalAIExecution, candidate.execution_id)
        self._ensure_bundle_version("weekly_games_select", 1, 1)
        candidate.contract_version = 1
        execution.contract_version = 1
        self.session.commit()
        status, detail = self.client.get(self._path(f"/candidates/{candidate_id}"))
        self.assertEqual(status, 200, detail)
        self.assertEqual(detail["eligibility"], "contract_obsolete")
        self.assertIn("data", detail)
        status, rejected = self.client.post(
            self._path("/adoption-preview"),
            {
                "expected_draft_version": self.version,
                "selections": [{"candidate_id": candidate_id, "target": "games"}],
            },
        )
        self.assertEqual(status, 409, rejected)
        self.assertEqual(rejected["error"]["code"], "WEEKLY_AI_CONTRACT_OBSOLETE")

    def test_materials_context_required_is_422_without_task(self):
        body = {
            "request_id": str(uuid.uuid4()),
            "expected_draft_version": self.version,
        }
        status, payload = self.client.post(self._path("/materials"), body)
        self.assertEqual(status, 422, payload)
        self.assertEqual(payload["error"]["code"], "MATERIAL_CONTEXT_REQUIRED")
        status, tasks = self.client.get(self._path("/tasks"))
        self.assertEqual(status, 200, tasks)
        self.assertEqual(tasks["items"], [])

    def test_candidate_list_scope_and_columns_dto(self):
        body = {
            "request_id": str(uuid.uuid4()),
            "expected_draft_version": self.version,
            "selected_fields": ["environment_setup", "key_week_focus"],
        }
        status, payload = self.client.post(self._path("/columns"), body)
        self.assertEqual(status, 202, payload)
        self.assertEqual(
            [item["target"] for item in payload["tasks"]],
            ["key_week_focus", "environment_setup"],
        )
        status, candidates = self.client.get(self._path("/candidates"))
        self.assertEqual(status, 200, candidates)
        self.assertEqual(candidates["items"], [])
        # Same request key with a different selected field set is a conflict.
        bad = dict(body, selected_fields=["habit_culture"])
        status, conflict = self.client.post(self._path("/columns"), bad)
        self.assertEqual(status, 409, conflict)
        self.assertEqual(conflict["error"]["code"], "WEEKLY_AI_REQUEST_CONFLICT")

    def test_snapshot_intent_rejects_new_create_but_replays_committed_receipt(self):
        from app.local import backup_barrier

        body = {
            "request_id": str(uuid.uuid4()),
            "expected_draft_version": self.version,
        }
        status, first = self.client.post(self._path("/games"), body)
        self.assertEqual(status, 202, first)
        barrier = backup_barrier.get_barrier(self.runtime.db_path.parent)
        lease = barrier.begin_intent("api-test")
        self.addCleanup(lease.release)
        status, rejected = self.client.post(
            self._path("/games"),
            {
                "request_id": str(uuid.uuid4()),
                "expected_draft_version": self.version,
            },
        )
        self.assertEqual(status, 409, rejected)
        self.assertEqual(rejected["error"]["code"], "LOCAL_BACKUP_BUSY")
        status, replay = self.client.post(self._path("/games"), body)
        self.assertEqual(status, 200, replay)
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["tasks"], first["tasks"])

    def test_snapshot_intent_rejects_new_adopt_but_keeps_preview_token(self):
        from app.local import backup_barrier

        _task_id, candidate_id = self._succeed_games()
        preview = weekly_ai_adoption.preview_adoption(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            plan_id=self.plan_id,
            expected_draft_version=self.version,
            selections=[{"candidate_id": candidate_id, "target": "games"}],
            launch_id=self.runtime.launch_id,
            session_scope_hash=self.server.app.state.session_scope,
        )
        body = {
            "request_id": str(uuid.uuid4()),
            "expected_draft_version": self.version,
            "preview_token": preview["preview_token"],
        }
        barrier = backup_barrier.get_barrier(self.runtime.db_path.parent)
        lease = barrier.begin_intent("api-adopt-test")
        self.addCleanup(lease.release)
        status, rejected = self.client.post(self._path("/adopt"), body)
        self.assertEqual(status, 409, rejected)
        self.assertEqual(rejected["error"]["code"], "LOCAL_BACKUP_BUSY")
        lease.release()
        status, adopted = self.client.post(self._path("/adopt"), body)
        self.assertEqual(status, 200, adopted)
        self.assertEqual(adopted["draft"]["version"], self.version + 1)

    def test_corrupt_stored_input_fails_list_and_detail_with_503(self):
        _task_id, candidate_id = self._succeed_games()
        candidate = self.session.get(LocalAICandidate, candidate_id)
        input_row = self.session.get(LocalAIInput, candidate.input_id)
        input_row.payload_json = {
            **dict(input_row.payload_json),
            "grade": "tampered",
        }
        self.session.commit()
        status, listing = self.client.get(self._path("/candidates"))
        self.assertEqual(status, 503, listing)
        self.assertEqual(listing["error"]["code"], "LOCAL_STORAGE_ERROR")
        status, detail = self.client.get(self._path(f"/candidates/{candidate_id}"))
        self.assertEqual(status, 503, detail)
        self.assertEqual(detail["error"]["code"], "LOCAL_STORAGE_ERROR")

    def test_bad_json_row_shape_fails_candidate_list_and_detail_with_503(self):
        _task_id, candidate_id = self._succeed_games()
        candidate = self.session.get(LocalAICandidate, candidate_id)
        input_row = self.session.get(LocalAIInput, candidate.input_id)
        input_row.target_hashes_json = ["not-a-map"]
        self.session.commit()
        status, listing = self.client.get(self._path("/candidates"))
        self.assertEqual(status, 503, listing)
        self.assertEqual(listing["error"]["code"], "LOCAL_STORAGE_ERROR")
        status, detail = self.client.get(self._path(f"/candidates/{candidate_id}"))
        self.assertEqual(status, 503, detail)
        self.assertEqual(detail["error"]["code"], "LOCAL_STORAGE_ERROR")
