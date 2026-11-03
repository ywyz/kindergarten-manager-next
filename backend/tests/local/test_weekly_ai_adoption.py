"""A G1 same-batch readonly preview and atomic multi-target adoption tests."""

from __future__ import annotations

import threading
import uuid
from unittest import mock

from sqlalchemy import select

from app.local import (
    ai_task_service,
    daily_plan_service,
    weekly_ai_adoption,
    weekly_ai_candidates,
    weekly_ai_contracts,
    weekly_ai_service,
    weekly_plan_service,
)
from app.local.errors import (
    LocalStorageError,
    LocalWeeklyAiContractObsolete,
    LocalWeeklyAiPreviewExpired,
    LocalWeeklyAiRequestConflict,
    LocalWeeklyAiSourceChanged,
    LocalWeeklyAiTargetChanged,
    LocalWeeklyVersionConflict,
)
from app.local.models import (
    LocalAICandidate,
    LocalAIExecution,
    LocalAIInput,
    LocalAIOperation,
    LocalDailyPlan,
    LocalWeeklyPlan,
    LocalWeeklyPlanAIAdoption,
    LocalWeeklyPlanContent,
)
from tests.local.test_weekly_ai_service import WeeklyAIServiceFixture


class WeeklyAIAdoptionTests(WeeklyAIServiceFixture):
    def _column_candidates(self):
        specs = [
            weekly_ai_service.WeeklyTaskSpec("weekly_key_week_focus", "key_week_focus"),
            weekly_ai_service.WeeklyTaskSpec("weekly_environment_setup", "environment_setup"),
        ]
        result, created = self._create(weekly_ai_service.COLUMNS, specs)
        self.assertTrue(created)
        candidates = []
        for _ in result["tasks"]:
            claim = ai_task_service.claim_next(
                self.runtime, now=ai_task_service._now(), started_ticks=1
            )
            self.assertIsNotNone(claim)
            self.assertTrue(
                ai_task_service.commit_dispatch_mark(
                    self.session, claim, ai_task_service._now()
                )
            )
            text = '{"text":"' + claim.task_type + '候选"}'
            self.assertTrue(
                ai_task_service.finalize_success(
                    self.session,
                    claim,
                    {"kind": "success", "candidate_text": text},
                    ai_task_service._now(),
                )
            )
            candidate = self.session.scalars(
                select(LocalAICandidate).where(LocalAICandidate.task_id == claim.task_id)
            ).one()
            candidates.append(candidate)
        return candidates

    def test_ai_supplement_games_get_server_owned_stable_ids(self):
        result, _ = self._create(
            weekly_ai_service.GAMES,
            [weekly_ai_service.WeeklyTaskSpec("weekly_games_select", "games")],
        )
        claim = ai_task_service.claim_next(
            self.runtime, now=ai_task_service._now(), started_ticks=1
        )
        self.assertIsNotNone(claim)
        self.assertTrue(
            ai_task_service.commit_dispatch_mark(
                self.session, claim, ai_task_service._now()
            )
        )
        text = (
            '{"outdoor_game_slots":{"collective_1":{"kind":"ai_supplement",'
            '"name":"补足游戏","shared_objectives":"目标","guidance_points":"指导",'
            '"focus_guidance":"关注","basis_handles":[]},"collective_2":null,'
            '"free_choice_1":null},"focus_area":null}'
        )
        self.assertTrue(
            ai_task_service.finalize_success(
                self.session,
                claim,
                {"kind": "success", "candidate_text": text},
                ai_task_service._now(),
            )
        )
        candidate = self.session.scalars(
            select(LocalAICandidate).where(LocalAICandidate.task_id == claim.task_id)
        ).one()
        preview = weekly_ai_adoption.preview_adoption(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            plan_id=self.plan_id,
            expected_draft_version=self.version,
            selections=[{"candidate_id": candidate.id, "target": "games"}],
            launch_id=self.runtime.launch_id,
            session_scope_hash="scope",
        )
        adopted = weekly_ai_adoption.adopt(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            plan_id=self.plan_id,
            request_id=str(uuid.uuid4()),
            expected_draft_version=self.version,
            preview_token=preview["preview_token"],
            launch_id=self.runtime.launch_id,
            session_scope_hash="scope",
        )
        preview_slot = preview["after"]["games"]["outdoor_game_slots"]["collective_1"]
        content = self.session.get(LocalWeeklyPlanContent, adopted["draft"]["id"])
        slot = content.content_json["outdoor_game_slots"]["collective_1"]
        self.assertEqual(slot["source_kind"], "ai_supplement")
        self.assertTrue(slot["ai_item_id"])
        self.assertEqual(slot["ai_item_id"], preview_slot["ai_item_id"])
        self.assertEqual(slot["candidate_id"], candidate.id)
        self.assertEqual(slot["input_id"], candidate.input_id)

    def test_preview_token_allows_unrelated_newer_draft(self):
        _task_id, candidate_id = self._succeed_games()
        preview = weekly_ai_adoption.preview_adoption(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            plan_id=self.plan_id,
            expected_draft_version=self.version,
            selections=[{"candidate_id": candidate_id, "target": "games"}],
            launch_id=self.runtime.launch_id,
            session_scope_hash="scope",
        )
        saved = weekly_plan_service.save_draft(
            self.session,
            profile_id=self.profile.id,
            request_id=str(uuid.uuid4()),
            plan_id=self.plan_id,
            expected_draft_version=self.version,
            patch={"theme": "无关主题"},
        )
        self.assertEqual(saved["draft"]["version"], self.version + 1)
        adopted = weekly_ai_adoption.adopt(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            plan_id=self.plan_id,
            request_id=str(uuid.uuid4()),
            expected_draft_version=self.version + 1,
            preview_token=preview["preview_token"],
            launch_id=self.runtime.launch_id,
            session_scope_hash="scope",
        )
        self.assertEqual(adopted["draft"]["version"], self.version + 2)
        content = self.session.get(LocalWeeklyPlanContent, adopted["draft"]["id"])
        self.assertEqual(content.content_json["theme"], "无关主题")

    def test_concurrent_same_key_returns_one_result_one_draft(self):
        _task_id, candidate_id = self._succeed_games()
        preview = weekly_ai_adoption.preview_adoption(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            plan_id=self.plan_id,
            expected_draft_version=self.version,
            selections=[{"candidate_id": candidate_id, "target": "games"}],
            launch_id=self.runtime.launch_id,
            session_scope_hash="scope",
        )
        barrier = threading.Barrier(2)
        results: list[dict] = []
        errors: list[BaseException] = []

        def run():
            session = self.runtime.session()
            try:
                barrier.wait(timeout=10)
                results.append(
                    weekly_ai_adoption.adopt(
                        session,
                        runtime=self.runtime,
                        profile_id=self.profile.id,
                        plan_id=self.plan_id,
                        request_id="00000000-0000-4000-8000-000000000123",
                        expected_draft_version=self.version,
                        preview_token=preview["preview_token"],
                        launch_id=self.runtime.launch_id,
                        session_scope_hash="scope",
                    )
                )
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                session.close()

        threads = [threading.Thread(target=run) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["draft"], results[1]["draft"])
        self.assertEqual(results[0]["operation_id"], results[1]["operation_id"])
        self.assertEqual(
            sorted(item["replayed"] for item in results), [False, True]
        )
        self.assertEqual(
            self.session.query(LocalAIOperation)
            .filter(LocalAIOperation.id == results[0]["operation_id"])
            .count(),
            1,
        )
        self.assertEqual(
            self.session.query(LocalWeeklyPlanAIAdoption)
            .filter(LocalWeeklyPlanAIAdoption.draft_id == results[0]["draft"]["id"])
            .count(),
            1,
        )
        self.assertEqual(
            self.session.get(LocalWeeklyPlanContent, results[0]["draft"]["id"]).version,
            self.version + 1,
        )

    def test_lost_response_and_restart_receipt_replay_survives_token_reset(self):
        _task_id, candidate_id = self._succeed_games()
        preview = weekly_ai_adoption.preview_adoption(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            plan_id=self.plan_id,
            expected_draft_version=self.version,
            selections=[{"candidate_id": candidate_id, "target": "games"}],
            launch_id=self.runtime.launch_id,
            session_scope_hash="scope",
        )
        rid = str(uuid.uuid4())
        first = weekly_ai_adoption.adopt(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            plan_id=self.plan_id,
            request_id=rid,
            expected_draft_version=self.version,
            preview_token=preview["preview_token"],
            launch_id=self.runtime.launch_id,
            session_scope_hash="scope",
        )
        # Simulate a restart: in-memory tokens are gone, the committed receipt
        # and draft are not.
        weekly_ai_adoption.reset_tokens()
        replay = weekly_ai_adoption.adopt(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            plan_id=self.plan_id,
            request_id=rid,
            expected_draft_version=self.version,
            preview_token=preview["preview_token"],
            launch_id=self.runtime.launch_id,
            session_scope_hash="scope",
        )
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["draft"], first["draft"])
        self.assertEqual(
            self.session.query(LocalWeeklyPlanContent)
            .filter(LocalWeeklyPlanContent.weekly_plan_id == self.plan_id)
            .count(),
            2,
        )
        with self.assertRaises(LocalWeeklyAiPreviewExpired):
            weekly_ai_adoption.adopt(
                self.session,
                runtime=self.runtime,
                profile_id=self.profile.id,
                plan_id=self.plan_id,
                request_id=str(uuid.uuid4()),
                expected_draft_version=self.version + 1,
                preview_token=preview["preview_token"],
                launch_id=self.runtime.launch_id,
                session_scope_hash="scope",
            )

    def test_event_write_failure_rolls_back_draft_operation_and_pointer(self):
        _task_id, candidate_id = self._succeed_games()
        preview = weekly_ai_adoption.preview_adoption(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            plan_id=self.plan_id,
            expected_draft_version=self.version,
            selections=[{"candidate_id": candidate_id, "target": "games"}],
            launch_id=self.runtime.launch_id,
            session_scope_hash="scope",
        )
        with mock.patch.object(
            weekly_ai_adoption,
            "LocalWeeklyPlanAIAdoption",
            side_effect=RuntimeError("event fault"),
        ):
            with self.assertRaises(RuntimeError):
                weekly_ai_adoption.adopt(
                    self.session,
                    runtime=self.runtime,
                    profile_id=self.profile.id,
                    plan_id=self.plan_id,
                    request_id=str(uuid.uuid4()),
                    expected_draft_version=self.version,
                    preview_token=preview["preview_token"],
                    launch_id=self.runtime.launch_id,
                    session_scope_hash="scope",
                )
        self.session.expire_all()
        plan = self.session.get(LocalWeeklyPlan, self.plan_id)
        self.assertEqual(plan.current_draft_version, self.version)
        self.assertEqual(
            self.session.query(LocalWeeklyPlanAIAdoption)
            .filter(LocalWeeklyPlanAIAdoption.weekly_plan_id == self.plan_id)
            .count(),
            0,
        )
        self.assertEqual(
            self.session.query(LocalWeeklyPlanContent)
            .filter(LocalWeeklyPlanContent.weekly_plan_id == self.plan_id)
            .count(),
            1,
        )

    def test_two_column_candidates_preview_readonly_then_one_atomic_draft(self):
        candidates = self._column_candidates()
        before_id = self.session.get(LocalWeeklyPlan, self.plan_id).current_draft_id
        selections = [
            {
                "candidate_id": item.id,
                "target": weekly_ai_contracts.TASK_TARGETS[item.task_type],
            }
            for item in candidates
        ]
        preview = weekly_ai_adoption.preview_adoption(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            plan_id=self.plan_id,
            expected_draft_version=self.version,
            selections=selections,
            launch_id=self.runtime.launch_id,
            session_scope_hash="scope",
        )
        self.assertEqual(preview["draft"]["id"], before_id)
        self.assertEqual(preview["selections"], selections)
        adopted = weekly_ai_adoption.adopt(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            plan_id=self.plan_id,
            request_id=str(uuid.uuid4()),
            expected_draft_version=self.version,
            preview_token=preview["preview_token"],
            launch_id=self.runtime.launch_id,
            session_scope_hash="scope",
        )
        self.assertEqual(adopted["draft"]["version"], self.version + 1)
        self.assertEqual(
            self.session.query(LocalWeeklyPlanAIAdoption)
            .filter(LocalWeeklyPlanAIAdoption.draft_id == adopted["draft"]["id"])
            .count(),
            2,
        )
        content = self.session.get(LocalWeeklyPlanContent, adopted["draft"]["id"])
        self.assertEqual(content.schema_version, 2)
        self.assertEqual(
            content.content_json["weekly_columns"]["key_week_focus"],
            "weekly_key_week_focus候选",
        )
        self.assertEqual(
            content.content_json["weekly_columns"]["environment_setup"],
            "weekly_environment_setup候选",
        )

    def _preview(self, candidates, version=None):
        selections = [
            {
                "candidate_id": item.id,
                "target": weekly_ai_contracts.TASK_TARGETS[item.task_type],
            }
            for item in candidates
        ]
        preview = weekly_ai_adoption.preview_adoption(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            plan_id=self.plan_id,
            expected_draft_version=self.version if version is None else version,
            selections=selections,
            launch_id=self.runtime.launch_id,
            session_scope_hash="scope",
        )
        return preview, selections

    def _adopt(self, preview, version=None):
        return weekly_ai_adoption.adopt(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            plan_id=self.plan_id,
            request_id=str(uuid.uuid4()),
            expected_draft_version=self.version if version is None else version,
            preview_token=preview["preview_token"],
            launch_id=self.runtime.launch_id,
            session_scope_hash="scope",
        )

    def test_stale_token_after_actual_target_change_is_rejected(self):
        _task_id, candidate_id = self._succeed_games()
        preview = weekly_ai_adoption.preview_adoption(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            plan_id=self.plan_id,
            expected_draft_version=self.version,
            selections=[{"candidate_id": candidate_id, "target": "games"}],
            launch_id=self.runtime.launch_id,
            session_scope_hash="scope",
        )
        saved = weekly_plan_service.save_draft(
            self.session,
            profile_id=self.profile.id,
            request_id=str(uuid.uuid4()),
            plan_id=self.plan_id,
            expected_draft_version=self.version,
            patch={
                "outdoor_game_slots": {
                    "collective_1": {
                        "source_kind": "manual",
                        "manual_item_id": None,
                        "client_key": "manual-target-change",
                        "name": "手填游戏",
                        "shared_objectives": "目标",
                        "guidance_points": "指导",
                        "focus_guidance": "关注",
                    }
                }
            },
        )
        self.assertEqual(saved["draft"]["version"], self.version + 1)
        with self.assertRaises(LocalWeeklyAiTargetChanged):
            self._adopt(preview, version=self.version + 1)

    def test_source_change_between_preview_and_adopt_is_rejected(self):
        _task_id, candidate_id = self._succeed_games()
        preview = weekly_ai_adoption.preview_adoption(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            plan_id=self.plan_id,
            expected_draft_version=self.version,
            selections=[{"candidate_id": candidate_id, "target": "games"}],
            launch_id=self.runtime.launch_id,
            session_scope_hash="scope",
        )
        plan = self.session.scalars(select(LocalDailyPlan)).first()
        daily_plan_service.save(
            self.session,
            plan_id=plan.id,
            expected_content_version=1,
            adopted_content={
                "morning_talk": {"topic": "改过的晨谈"},
                "group_activity": {
                    "theme": "改过的活动",
                    "objectives": "观察",
                    "process": "再看一看",
                },
            },
        )
        with self.assertRaises(LocalWeeklyAiSourceChanged):
            self._adopt(preview)

    def test_cross_batch_candidates_are_rejected(self):
        _games_task, games_candidate = self._succeed_games()
        candidates = self._column_candidates()
        selections = [
            {"candidate_id": games_candidate, "target": "games"},
            {
                "candidate_id": candidates[0].id,
                "target": weekly_ai_contracts.TASK_TARGETS[candidates[0].task_type],
            },
        ]
        with self.assertRaises(LocalWeeklyAiRequestConflict):
            weekly_ai_adoption.preview_adoption(
                self.session,
                runtime=self.runtime,
                profile_id=self.profile.id,
                plan_id=self.plan_id,
                expected_draft_version=self.version,
                selections=selections,
                launch_id=self.runtime.launch_id,
                session_scope_hash="scope",
            )

    def test_old_contract_candidate_is_reported_obsolete(self):
        _task_id, candidate_id = self._succeed_games()
        candidate = self.session.get(LocalAICandidate, candidate_id)
        execution = self.session.get(LocalAIExecution, candidate.execution_id)
        self.assertEqual(candidate.contract_version, 2)
        self.assertEqual(execution.contract_version, 2)
        current = weekly_ai_candidates.get_candidate(
            self.session,
            profile_id=self.profile.id,
            plan_id=self.plan_id,
            candidate_id=candidate_id,
        )
        self.assertEqual(current["eligibility"], "eligible")

        # Supported historical v1 remains readable in detail/history, but a
        # new adoption must be obsolete. The synthetic new archive has no
        # historical v1 bundle row until we add the fixture row.
        self._ensure_bundle_version("weekly_games_select", 1, 1)
        candidate.contract_version = 1
        execution.contract_version = 1
        self.session.commit()
        old = weekly_ai_candidates.get_candidate(
            self.session,
            profile_id=self.profile.id,
            plan_id=self.plan_id,
            candidate_id=candidate_id,
        )
        self.assertEqual(old["eligibility"], "contract_obsolete")
        self.assertIn("data", old)
        with self.assertRaises(LocalWeeklyAiContractObsolete):
            weekly_ai_adoption.preview_adoption(
                self.session,
                runtime=self.runtime,
                profile_id=self.profile.id,
                plan_id=self.plan_id,
                expected_draft_version=self.version,
                selections=[{"candidate_id": candidate_id, "target": "games"}],
                launch_id=self.runtime.launch_id,
                session_scope_hash="scope",
            )

        # Unknown versions are not silently treated as current or as v1.
        # Keep this as an in-memory eligibility probe so the synthetic DB does
        # not need an impossible unknown execution/bundle FK target.
        candidate.contract_version = 99
        content = self.session.get(
            LocalWeeklyPlanContent,
            self.session.get(LocalWeeklyPlan, self.plan_id).current_draft_id,
        )
        input_row = self.session.get(LocalAIInput, candidate.input_id)
        self.assertEqual(
            weekly_ai_candidates.eligibility(
                self.session,
                plan=self.session.get(LocalWeeklyPlan, self.plan_id),
                content=content,
                candidate=candidate,
                input_row=input_row,
            ),
            "contract_obsolete",
        )
        candidate.contract_version = 2
        execution.contract_version = 2
        self.session.commit()
        restored = weekly_ai_candidates.get_candidate(
            self.session,
            profile_id=self.profile.id,
            plan_id=self.plan_id,
            candidate_id=candidate_id,
        )
        self.assertEqual(restored["eligibility"], "eligible")

    def test_cas_stale_version_is_conflict_without_partial_draft(self):
        candidates = self._column_candidates()
        first_preview = weekly_ai_adoption.preview_adoption(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            plan_id=self.plan_id,
            expected_draft_version=self.version,
            selections=[
                {
                    "candidate_id": candidates[0].id,
                    "target": weekly_ai_contracts.TASK_TARGETS[candidates[0].task_type],
                }
            ],
            launch_id=self.runtime.launch_id,
            session_scope_hash="scope",
        )
        adopted = self._adopt(first_preview)
        self.session.expire_all()
        self.assertEqual(
            self.session.get(LocalWeeklyPlan, self.plan_id).current_draft_version,
            adopted["draft"]["version"],
        )
        stale_preview = weekly_ai_adoption.preview_adoption(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            plan_id=self.plan_id,
            expected_draft_version=self.version + 1,
            selections=[
                {
                    "candidate_id": candidates[1].id,
                    "target": weekly_ai_contracts.TASK_TARGETS[candidates[1].task_type],
                }
            ],
            launch_id=self.runtime.launch_id,
            session_scope_hash="scope",
        )
        with self.assertRaises(LocalWeeklyVersionConflict):
            self._adopt(stale_preview, version=self.version + 3)
        self.session.expire_all()
        self.assertEqual(
            self.session.get(LocalWeeklyPlan, self.plan_id).current_draft_version,
            adopted["draft"]["version"],
        )
        self.assertEqual(
            self.session.query(LocalWeeklyPlanContent)
            .filter(LocalWeeklyPlanContent.weekly_plan_id == self.plan_id)
            .count(),
            2,
        )

    def test_multi_target_operation_fault_rolls_back_everything(self):
        candidates = self._column_candidates()
        preview, _ = self._preview(candidates)
        before = self.session.get(LocalWeeklyPlan, self.plan_id)
        before_id = before.current_draft_id
        before_hash = self.session.get(LocalWeeklyPlanContent, before_id).content_hash
        original_add = self.session.add

        def add_with_fault(obj):
            if isinstance(obj, LocalAIOperation):
                raise RuntimeError("operation fault")
            return original_add(obj)

        with mock.patch.object(self.session, "add", side_effect=add_with_fault):
            with self.assertRaises(RuntimeError):
                self._adopt(preview)
        self.session.expire_all()
        plan = self.session.get(LocalWeeklyPlan, self.plan_id)
        self.assertEqual(plan.current_draft_id, before_id)
        self.assertEqual(
            self.session.get(LocalWeeklyPlanContent, plan.current_draft_id).content_hash,
            before_hash,
        )
        self.assertEqual(
            self.session.query(LocalWeeklyPlanAIAdoption)
            .filter(LocalWeeklyPlanAIAdoption.weekly_plan_id == self.plan_id)
            .count(),
            0,
        )

    def test_multi_target_draft_fault_rolls_back_everything(self):
        candidates = self._column_candidates()
        preview, _ = self._preview(candidates)
        before = self.session.get(LocalWeeklyPlan, self.plan_id)
        before_id = before.current_draft_id
        before_hash = self.session.get(LocalWeeklyPlanContent, before_id).content_hash
        original_add = self.session.add

        def add_with_fault(obj):
            if isinstance(obj, LocalWeeklyPlanContent) and obj.version > self.version:
                raise RuntimeError("draft fault")
            return original_add(obj)

        with mock.patch.object(self.session, "add", side_effect=add_with_fault):
            with self.assertRaises(RuntimeError):
                self._adopt(preview)
        self.session.expire_all()
        plan = self.session.get(LocalWeeklyPlan, self.plan_id)
        self.assertEqual(plan.current_draft_id, before_id)
        self.assertEqual(
            self.session.get(LocalWeeklyPlanContent, plan.current_draft_id).content_hash,
            before_hash,
        )
        self.assertEqual(
            self.session.query(LocalWeeklyPlanAIAdoption)
            .filter(LocalWeeklyPlanAIAdoption.weekly_plan_id == self.plan_id)
            .count(),
            0,
        )

    def test_corruption_after_preview_makes_adopt_storage_failure(self):
        _task_id, candidate_id = self._succeed_games()
        preview = weekly_ai_adoption.preview_adoption(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            plan_id=self.plan_id,
            expected_draft_version=self.version,
            selections=[{"candidate_id": candidate_id, "target": "games"}],
            launch_id=self.runtime.launch_id,
            session_scope_hash="scope",
        )
        candidate = self.session.get(LocalAICandidate, candidate_id)
        candidate.raw_candidate_json = {"outdoor_game_slots": {}, "focus_area": None}
        self.session.commit()
        with self.assertRaises(LocalStorageError):
            weekly_ai_adoption.adopt(
                self.session,
                runtime=self.runtime,
                profile_id=self.profile.id,
                plan_id=self.plan_id,
                request_id=str(uuid.uuid4()),
                expected_draft_version=self.version,
                preview_token=preview["preview_token"],
                launch_id=self.runtime.launch_id,
                session_scope_hash="scope",
            )
        self.session.expire_all()
        self.assertEqual(
            self.session.get(LocalWeeklyPlan, self.plan_id).current_draft_version,
            self.version,
        )
        self.assertEqual(
            self.session.query(LocalWeeklyPlanAIAdoption)
            .filter(LocalWeeklyPlanAIAdoption.weekly_plan_id == self.plan_id)
            .count(),
            0,
        )

    def test_multi_target_event_fault_rolls_back_everything(self):
        candidates = self._column_candidates()
        preview, _ = self._preview(candidates)
        before = self.session.get(LocalWeeklyPlan, self.plan_id)
        before_id = before.current_draft_id
        before_hash = self.session.get(LocalWeeklyPlanContent, before_id).content_hash
        with mock.patch.object(
            weekly_ai_adoption,
            "LocalWeeklyPlanAIAdoption",
            side_effect=RuntimeError("event fault"),
        ):
            with self.assertRaises(RuntimeError):
                self._adopt(preview)
        self.session.expire_all()
        plan = self.session.get(LocalWeeklyPlan, self.plan_id)
        self.assertEqual(plan.current_draft_id, before_id)
        self.assertEqual(
            self.session.get(LocalWeeklyPlanContent, plan.current_draft_id).content_hash,
            before_hash,
        )
        self.assertEqual(
            self.session.query(LocalWeeklyPlanAIAdoption)
            .filter(LocalWeeklyPlanAIAdoption.weekly_plan_id == self.plan_id)
            .count(),
            0,
        )

    def test_multi_target_cas_fault_rolls_back_everything(self):
        candidates = self._column_candidates()
        preview, _ = self._preview(candidates)
        before = self.session.get(LocalWeeklyPlan, self.plan_id)
        before_id = before.current_draft_id
        before_hash = self.session.get(LocalWeeklyPlanContent, before_id).content_hash
        with self.assertRaises(LocalWeeklyVersionConflict):
            self._adopt(preview, version=self.version + 1)
        self.session.expire_all()
        plan = self.session.get(LocalWeeklyPlan, self.plan_id)
        self.assertEqual(plan.current_draft_id, before_id)
        self.assertEqual(
            self.session.get(LocalWeeklyPlanContent, plan.current_draft_id).content_hash,
            before_hash,
        )
        self.assertEqual(
            self.session.query(LocalWeeklyPlanAIAdoption)
            .filter(LocalWeeklyPlanAIAdoption.weekly_plan_id == self.plan_id)
            .count(),
            0,
        )
