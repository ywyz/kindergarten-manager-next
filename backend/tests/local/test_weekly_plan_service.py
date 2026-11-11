"""Weekly plan service tests (engineering spec §3-4/§11)."""

from __future__ import annotations

import copy
import unittest
import uuid
from datetime import date

from app.local import (
    daily_plan_service,
    profile_service,
    weekly_plan_service,
    weekly_plan_snapshot as snapshots,
)
from app.local.errors import (
    LocalWeeklyInvalid,
    LocalWeeklyOperationConflict,
    LocalWeeklyPreviewStale,
    LocalWeeklySourceChanged,
    LocalWeeklyVersionConflict,
)
from app.local.models import (
    LocalProfile,
    LocalSettings,
    LocalTerm,
    LocalWeeklyPlanConfirmation,
    LocalWeeklyPlanOperation,
)
from app.local.migrate import head_revision
from app.local.normalize import normalize_initialization
from app.local.weekly_plan_tokens import scope_hash
from sqlalchemy import select
from tests.local.support import LocalTestCase

ANCHOR = date(2026, 9, 7)
PLAN_DATE = date(2026, 9, 8)


def _adopted(topic: str = "秋天的树叶") -> dict:
    return {
        "morning_talk": {"topic": topic, "questions": "你看到了什么"},
        "group_activity": {"theme": "树叶分类", "process": "观察"},
        "morning_games": [
            {
                "group_kind": "collective",
                "games": [{"name": "老狼老狼几点了"}],
                "shared_objectives": "听信号行动",
                "guidance_points": "注意安全",
                "focus_guidance": "观察反应",
            }
        ],
        "post_group_games": [
            {
                "context_kind": "area",
                "area": "积木区",
                "games": [{"name": "搭建小桥"}],
                "objectives": "合作",
                "guidance": "协商",
                "support_strategy": "提供材料",
            }
        ],
    }


class WeeklyPlanServiceTests(LocalTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.runtime = self.make_runtime()
        self.session = self.runtime.session()
        self.addCleanup(self.session.close)
        normalized = normalize_initialization(
            request_id=str(uuid.uuid4()),
            display_name="测试教师",
            class_name="中一班",
            grade="middle",
            term_name="秋季学期",
            start_date=ANCHOR.isoformat(),
            end_date="2026-10-30",
            school_name="测试幼儿园",
        )
        profile_service.initialize(self.session, normalized)
        self.session.expire_all()
        self.profile = self.session.scalars(select(LocalProfile)).one()
        self.term = self.session.scalars(select(LocalTerm)).one()
        self.settings = self.session.get(LocalSettings, "singleton")
        self.scope = scope_hash("test-scope")
        self.launch = "test-launch"

    def _create_daily(self, topic: str = "秋天的树叶") -> str:
        plan, created = daily_plan_service.create_or_open(
            self.session,
            plan_date=PLAN_DATE,
            raw_lesson_plan=None,
            adopted_content=_adopted(topic),
        )
        self.assertTrue(created)
        return plan["id"]

    def _preview(self) -> dict:
        return weekly_plan_service.create_preview(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            launch_id=self.launch,
            session_scope_hash=self.scope,
            term_id=self.term.id,
            week_anchor_date=ANCHOR,
        )

    def _create(self, preview: dict | None = None):
        preview = preview or self._preview()
        return weekly_plan_service.create_or_open(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            launch_id=self.launch,
            session_scope_hash=self.scope,
            request_id=str(uuid.uuid4()),
            term_id=self.term.id,
            week_anchor_date=ANCHOR,
            expected_config_version=self.settings.config_version,
            context_token=preview["create_token"],
        )

    def _confirm(self, plan_id: str, version: int):
        preview = weekly_plan_service.confirmation_preview(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            launch_id=self.launch,
            session_scope_hash=self.scope,
            plan_id=plan_id,
            expected_draft_version=version,
        )
        return weekly_plan_service.confirm(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            launch_id=self.launch,
            session_scope_hash=self.scope,
            request_id=str(uuid.uuid4()),
            plan_id=plan_id,
            expected_draft_version=version,
            context_token=preview["preview_token"],
            ack_missing=True,
            ack_stale=True,
            note=None,
        )

    def test_create_uses_saved_daily_source_and_returns_candidates(self) -> None:
        self._create_daily()
        preview = self._preview()
        self.assertEqual(preview["status"], "new")
        self.assertTrue(preview["source_candidates"])
        self.assertEqual(
            preview["calendar"]["week_anchor_date"], ANCHOR.isoformat()
        )
        result, created = self._create(preview)
        self.assertTrue(created)
        detail = weekly_plan_service.get_detail(
            self.session, profile_id=self.profile.id, plan_id=result["weekly_plan_id"]
        )
        self.assertEqual(detail["draft"]["version"], 1)
        rows = detail["draft"]["content"]["deterministic"]
        saved = [row for row in rows if row["date"] == PLAN_DATE.isoformat()][0]
        self.assertEqual(saved["source_state"], "saved")
        self.assertEqual(saved["source"]["morning_talk_topic"], "秋天的树叶")

    def test_existing_week_opens_without_valid_create_token(self) -> None:
        self._create_daily()
        first, created = self._create()
        self.assertTrue(created)
        again, created_again = weekly_plan_service.create_or_open(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            launch_id=self.launch,
            session_scope_hash=self.scope,
            request_id=str(uuid.uuid4()),
            term_id=self.term.id,
            week_anchor_date=ANCHOR,
            expected_config_version=self.settings.config_version,
            context_token="expired-token",
        )
        self.assertFalse(created_again)
        self.assertEqual(again["weekly_plan_id"], first["weekly_plan_id"])
        self.assertEqual(again["draft"]["id"], first["draft"]["id"])

    def test_save_manual_slot_assigns_server_id_and_theme_null_becomes_empty(self) -> None:
        self._create_daily()
        result, _ = self._create()
        plan_id = result["weekly_plan_id"]
        saved = weekly_plan_service.save_draft(
            self.session,
            profile_id=self.profile.id,
            request_id=str(uuid.uuid4()),
            plan_id=plan_id,
            expected_draft_version=1,
            patch={
                "theme": None,
                "weekly_columns": {"key_week_focus": "观察"},
                "outdoor_game_slots": {
                    "collective_1": {
                        "source_kind": "manual",
                        "manual_item_id": None,
                        "client_key": "manual-1",
                        "name": "手填游戏",
                        "shared_objectives": "目标",
                        "guidance_points": "指导",
                        "focus_guidance": "关注",
                    }
                },
            },
        )
        content = saved["draft"]["content"]
        self.assertEqual(content["theme"], "")
        slot = content["outdoor_game_slots"]["collective_1"]
        self.assertTrue(slot["manual_item_id"])
        self.assertNotIn("client_key", slot)
        self.assertEqual(content["weekly_columns"]["key_week_focus"], "观察")

    def test_receipt_replay_and_conflicting_reuse(self) -> None:
        self._create_daily()
        result, _ = self._create()
        plan_id = result["weekly_plan_id"]
        request_id = str(uuid.uuid4())
        first = weekly_plan_service.save_draft(
            self.session,
            profile_id=self.profile.id,
            request_id=request_id,
            plan_id=plan_id,
            expected_draft_version=1,
            patch={"theme": "主题"},
        )
        stored = self.session.scalars(
            select(LocalWeeklyPlanOperation).where(
                LocalWeeklyPlanOperation.request_id == request_id
            )
        ).one()
        self.assertEqual(
            set(stored.result_json),
            {
                "schema_version",
                "weekly_plan_id",
                "draft_id",
                "draft_version",
                "confirmation_id",
                "confirmation_version",
                "snapshot_id",
                "token_id",
            },
        )
        self.assertNotIn("content", stored.result_json)
        self.assertEqual(
            stored.result_json["draft_id"], first["draft"]["id"]
        )
        replay = weekly_plan_service.save_draft(
            self.session,
            profile_id=self.profile.id,
            request_id=request_id,
            plan_id=plan_id,
            expected_draft_version=1,
            patch={"theme": "主题"},
        )
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["draft"]["id"], first["draft"]["id"])
        self.assertTrue(first["operation_id"])
        self.assertTrue(first["request_id"])
        self.assertEqual(replay["operation_id"], first["operation_id"])
        self.assertEqual(replay["request_id"], first["request_id"])
        self.assertEqual(
            {k: v for k, v in first.items() if k != "replayed"},
            {k: v for k, v in replay.items() if k != "replayed"},
        )
        with self.assertRaises(LocalWeeklyOperationConflict):
            weekly_plan_service.save_draft(
                self.session,
                profile_id=self.profile.id,
                request_id=request_id,
                plan_id=plan_id,
                expected_draft_version=1,
                patch={"theme": "另一个主题"},
            )

    def test_confirmation_is_self_contained_and_history_keeps_old_content(self) -> None:
        self._create_daily()
        result, _ = self._create()
        plan_id = result["weekly_plan_id"]
        saved = weekly_plan_service.save_draft(
            self.session,
            profile_id=self.profile.id,
            request_id=str(uuid.uuid4()),
            plan_id=plan_id,
            expected_draft_version=1,
            patch={"theme": "确认主题"},
        )
        confirmed = self._confirm(plan_id, saved["draft"]["version"])
        confirmation_id = confirmed["confirmation"]["id"]
        # A later draft must not rewrite the confirmation snapshot.
        weekly_plan_service.save_draft(
            self.session,
            profile_id=self.profile.id,
            request_id=str(uuid.uuid4()),
            plan_id=plan_id,
            expected_draft_version=saved["draft"]["version"],
            patch={"theme": "后来主题"},
        )
        history = weekly_plan_service.get_confirmation(
            self.session,
            profile_id=self.profile.id,
            plan_id=plan_id,
            confirmation_id=confirmation_id,
        )
        self.assertEqual(history["snapshot"]["content"]["theme"], "确认主题")
        detail = weekly_plan_service.get_detail(
            self.session, profile_id=self.profile.id, plan_id=plan_id
        )
        self.assertEqual(
            detail["confirmed"]["id"], confirmation_id
        )
        self.assertEqual(detail["draft"]["content"]["theme"], "后来主题")

    def test_reissue_confirmation_appends_current_term_name_without_draft_write(self) -> None:
        self._create_daily()
        result, _ = self._create()
        plan_id = result["weekly_plan_id"]
        first = self._confirm(plan_id, 1)
        source = weekly_plan_service.get_confirmation(
            self.session,
            profile_id=self.profile.id,
            plan_id=plan_id,
            confirmation_id=first["confirmation"]["id"],
        )["snapshot"]
        self.assertEqual(source["term_name"], "秋季学期")
        before_draft = weekly_plan_service.get_detail(
            self.session, profile_id=self.profile.id, plan_id=plan_id
        )["draft"]

        self.term.name = "新学期"
        self.session.commit()
        preview = weekly_plan_service.confirmation_preview(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            launch_id=self.launch,
            session_scope_hash=self.scope,
            plan_id=plan_id,
            expected_draft_version=before_draft["version"],
            source_confirmation_id=first["confirmation"]["id"],
        )
        target = preview["target"]
        self.assertEqual(target["term_name"], "新学期")
        self.assertEqual(
            target["reissued_from_confirmation_id"],
            first["confirmation"]["id"],
        )
        for key in (
            "content",
            "header",
            "creation_context",
            "date_range",
            "columns",
            "facts",
            "draft_id",
            "draft_version",
            "content_hash",
        ):
            self.assertEqual(target[key], source[key], key)
        self.assertNotEqual(
            snapshots.snapshot_hash(target), first["confirmation"]["snapshot_hash"]
        )

        request_id = str(uuid.uuid4())
        confirmed = weekly_plan_service.confirm(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            launch_id=self.launch,
            session_scope_hash=self.scope,
            request_id=request_id,
            plan_id=plan_id,
            expected_draft_version=before_draft["version"],
            context_token=preview["preview_token"],
            ack_missing=True,
            ack_stale=True,
            source_confirmation_id=first["confirmation"]["id"],
        )
        replayed = weekly_plan_service.confirm(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            launch_id=self.launch,
            session_scope_hash=self.scope,
            request_id=request_id,
            plan_id=plan_id,
            expected_draft_version=before_draft["version"],
            context_token=preview["preview_token"],
            ack_missing=True,
            ack_stale=True,
            source_confirmation_id=first["confirmation"]["id"],
        )
        self.assertTrue(replayed["replayed"])
        self.assertEqual(
            replayed["confirmation"]["id"], confirmed["confirmation"]["id"]
        )
        duplicate = weekly_plan_service.confirm(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            launch_id=self.launch,
            session_scope_hash=self.scope,
            request_id=str(uuid.uuid4()),
            plan_id=plan_id,
            expected_draft_version=before_draft["version"],
            context_token=preview["preview_token"],
            ack_missing=True,
            ack_stale=True,
            source_confirmation_id=first["confirmation"]["id"],
        )
        self.assertTrue(duplicate["replayed"])
        self.assertEqual(
            duplicate["confirmation"]["id"], confirmed["confirmation"]["id"]
        )
        self.assertEqual(confirmed["confirmation"]["version"], 2)
        self.assertEqual(confirmed["confirmation"]["term_name"], "新学期")
        self.assertEqual(
            confirmed["confirmation"]["reissued_from_confirmation_id"],
            first["confirmation"]["id"],
        )
        detail = weekly_plan_service.get_detail(
            self.session, profile_id=self.profile.id, plan_id=plan_id
        )
        self.assertEqual(detail["plan"]["current_confirmed_version"], 2)
        self.assertEqual(detail["draft"], before_draft)
        old = weekly_plan_service.get_confirmation(
            self.session,
            profile_id=self.profile.id,
            plan_id=plan_id,
            confirmation_id=first["confirmation"]["id"],
        )
        self.assertEqual(old["snapshot"], source)
        self.assertEqual(
            old["confirmation"]["snapshot_hash"],
            first["confirmation"]["snapshot_hash"],
        )

    def test_reissue_rejects_same_name_source_swap_and_late_changes(self) -> None:
        self._create_daily()
        result, _ = self._create()
        plan_id = result["weekly_plan_id"]
        first = self._confirm(plan_id, 1)
        other = self._confirm(plan_id, 1)
        self.term.name = "新学期"
        self.session.commit()
        preview = weekly_plan_service.confirmation_preview(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            launch_id=self.launch,
            session_scope_hash=self.scope,
            plan_id=plan_id,
            expected_draft_version=1,
            source_confirmation_id=first["confirmation"]["id"],
        )
        second = weekly_plan_service.confirm(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            launch_id=self.launch,
            session_scope_hash=self.scope,
            request_id=str(uuid.uuid4()),
            plan_id=plan_id,
            expected_draft_version=1,
            context_token=preview["preview_token"],
            ack_missing=True,
            ack_stale=True,
            source_confirmation_id=first["confirmation"]["id"],
        )
        with self.assertRaises(LocalWeeklyInvalid):
            weekly_plan_service.confirmation_preview(
                self.session,
                runtime=self.runtime,
                profile_id=self.profile.id,
                launch_id=self.launch,
                session_scope_hash=self.scope,
                plan_id=plan_id,
                expected_draft_version=1,
                source_confirmation_id=second["confirmation"]["id"],
            )

        # A different ordinary confirmation is a different source even when
        # the current term name is equal.
        swapped = weekly_plan_service.confirmation_preview(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            launch_id=self.launch,
            session_scope_hash=self.scope,
            plan_id=plan_id,
            expected_draft_version=1,
            source_confirmation_id=first["confirmation"]["id"],
        )
        with self.assertRaises(LocalWeeklyPreviewStale):
            weekly_plan_service.confirm(
                self.session,
                runtime=self.runtime,
                profile_id=self.profile.id,
                launch_id=self.launch,
                session_scope_hash=self.scope,
                request_id=str(uuid.uuid4()),
                plan_id=plan_id,
                expected_draft_version=1,
                context_token=swapped["preview_token"],
                ack_missing=True,
                ack_stale=True,
                source_confirmation_id=other["confirmation"]["id"],
            )

        # A late draft edit changes the bound current draft version.
        late = weekly_plan_service.confirmation_preview(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            launch_id=self.launch,
            session_scope_hash=self.scope,
            plan_id=plan_id,
            expected_draft_version=1,
            source_confirmation_id=first["confirmation"]["id"],
        )
        weekly_plan_service.save_draft(
            self.session,
            profile_id=self.profile.id,
            request_id=str(uuid.uuid4()),
            plan_id=plan_id,
            expected_draft_version=1,
            patch={"theme": "晚到编辑"},
        )
        with self.assertRaises(LocalWeeklyVersionConflict):
            weekly_plan_service.confirm(
                self.session,
                runtime=self.runtime,
                profile_id=self.profile.id,
                launch_id=self.launch,
                session_scope_hash=self.scope,
                request_id=str(uuid.uuid4()),
                plan_id=plan_id,
                expected_draft_version=1,
                context_token=late["preview_token"],
                ack_missing=True,
                ack_stale=True,
                source_confirmation_id=first["confirmation"]["id"],
            )

        # A term rename after preview changes the target snapshot name.
        renamed = weekly_plan_service.confirmation_preview(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            launch_id=self.launch,
            session_scope_hash=self.scope,
            plan_id=plan_id,
            expected_draft_version=2,
            source_confirmation_id=first["confirmation"]["id"],
        )
        self.term.name = "更新学期"
        self.session.commit()
        with self.assertRaises(LocalWeeklyPreviewStale):
            weekly_plan_service.confirm(
                self.session,
                runtime=self.runtime,
                profile_id=self.profile.id,
                launch_id=self.launch,
                session_scope_hash=self.scope,
                request_id=str(uuid.uuid4()),
                plan_id=plan_id,
                expected_draft_version=2,
                context_token=renamed["preview_token"],
                ack_missing=True,
                ack_stale=True,
                source_confirmation_id=first["confirmation"]["id"],
            )

        # A snapshot whose own weekly_plan_id differs from the plan is rejected
        # even when its row hash was recomputed.
        source_row = self.session.get(
            LocalWeeklyPlanConfirmation, first["confirmation"]["id"]
        )
        tampered = copy.deepcopy(source_row.snapshot_json)
        tampered["weekly_plan_id"] = "z" * 22
        source_row.snapshot_json = tampered
        source_row.snapshot_hash = snapshots.snapshot_hash(tampered)
        self.session.commit()
        with self.assertRaises(
            weekly_plan_service.LocalWeeklyConfirmationNotFound
        ):
            weekly_plan_service.confirmation_preview(
                self.session,
                runtime=self.runtime,
                profile_id=self.profile.id,
                launch_id=self.launch,
                session_scope_hash=self.scope,
                plan_id=plan_id,
                expected_draft_version=2,
                source_confirmation_id=first["confirmation"]["id"],
            )

    def test_confirmation_preview_target_is_the_persisted_snapshot(self) -> None:
        self._create_daily()
        result, _ = self._create()
        plan_id = result["weekly_plan_id"]
        saved = weekly_plan_service.save_draft(
            self.session,
            profile_id=self.profile.id,
            request_id=str(uuid.uuid4()),
            plan_id=plan_id,
            expected_draft_version=1,
            patch={"theme": "目标"},
        )
        preview = weekly_plan_service.confirmation_preview(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            launch_id=self.launch,
            session_scope_hash=self.scope,
            plan_id=plan_id,
            expected_draft_version=saved["draft"]["version"],
        )
        target = preview["target"]
        self.assertEqual(
            set(target),
            {
                "schema_version",
                "weekly_plan_id",
                "profile_id",
                "class_id",
                "term_id",
                "draft_id",
                "draft_version",
                "content_hash",
                "header",
                "creation_context",
                "content",
                "date_range",
                "columns",
                "facts",
                "term_name",
            },
        )
        self.assertEqual(target["draft_id"], saved["draft"]["id"])
        self.assertEqual(target["draft_version"], saved["draft"]["version"])
        self.assertEqual(target["term_name"], "秋季学期")
        self.assertEqual(target["content"]["theme"], "目标")
        self.assertTrue(target["date_range"]["start"] <= target["date_range"]["end"])
        self.assertEqual(len(target["columns"]), 5)
        from app.local import weekly_plan_snapshot

        self.assertEqual(
            weekly_plan_snapshot.snapshot_hash(target), preview["target_hash"]
        )
        confirmed = weekly_plan_service.confirm(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            launch_id=self.launch,
            session_scope_hash=self.scope,
            request_id=str(uuid.uuid4()),
            plan_id=plan_id,
            expected_draft_version=saved["draft"]["version"],
            context_token=preview["preview_token"],
            ack_missing=True,
            ack_stale=True,
            note=None,
        )
        history = weekly_plan_service.get_confirmation(
            self.session,
            profile_id=self.profile.id,
            plan_id=plan_id,
            confirmation_id=confirmed["confirmation"]["id"],
        )
        self.assertEqual(history["snapshot"], target)
        self.assertEqual(
            set(history),
            {"confirmation", "snapshot", "note", "confirmed_by", "confirmed_at"},
        )

    def test_stale_source_is_reported_from_live_snapshot(self) -> None:
        daily_id = self._create_daily()
        result, _ = self._create()
        plan_id = result["weekly_plan_id"]
        current = daily_plan_service.get_plan(self.session, plan_id=daily_id)
        adopted = dict(current["content"]["adopted_content"])
        adopted["morning_talk"] = {"topic": "改过的主题", "questions": "问题"}
        daily_plan_service.save(
            self.session,
            plan_id=daily_id,
            expected_content_version=current["content"]["version"],
            adopted_content=adopted,
        )
        detail = weekly_plan_service.get_detail(
            self.session, profile_id=self.profile.id, plan_id=plan_id
        )
        self.assertTrue(detail["facts"]["stale_sources"])
        self.assertTrue(
            any(
                fact.get("old_ref") and fact.get("new_ref")
                for fact in detail["facts"]["stale_sources"]
            )
        )

    def test_refresh_updates_resolvable_source_and_preserves_manual_text(self) -> None:
        daily_id = self._create_daily()
        result, _ = self._create()
        plan_id = result["weekly_plan_id"]
        saved = weekly_plan_service.save_draft(
            self.session,
            profile_id=self.profile.id,
            request_id=str(uuid.uuid4()),
            plan_id=plan_id,
            expected_draft_version=1,
            patch={
                "theme": "刷新主题",
                "weekly_columns": {"key_week_focus": "保留"},
                "outdoor_game_slots": {
                    "collective_1": {
                        "source_kind": "manual",
                        "manual_item_id": None,
                        "client_key": "manual-refresh",
                        "name": "手工保留",
                        "shared_objectives": "目标",
                        "guidance_points": "指导",
                        "focus_guidance": "关注",
                    }
                },
            },
        )
        current = daily_plan_service.get_plan(self.session, plan_id=daily_id)
        adopted = dict(current["content"]["adopted_content"])
        adopted["morning_talk"] = {"topic": "刷新后的主题", "questions": "问题"}
        daily_plan_service.save(
            self.session,
            plan_id=daily_id,
            expected_content_version=current["content"]["version"],
            adopted_content=adopted,
        )
        preview = weekly_plan_service.refresh_preview(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            launch_id=self.launch,
            session_scope_hash=self.scope,
            plan_id=plan_id,
            expected_draft_version=saved["draft"]["version"],
        )
        self.assertTrue(preview["differences"])
        refreshed = weekly_plan_service.refresh_sources(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            launch_id=self.launch,
            session_scope_hash=self.scope,
            request_id=str(uuid.uuid4()),
            plan_id=plan_id,
            expected_draft_version=saved["draft"]["version"],
            preview_token=preview["preview_token"],
        )
        content = refreshed["draft"]["content"]
        self.assertEqual(content["theme"], "刷新主题")
        self.assertEqual(content["weekly_columns"]["key_week_focus"], "保留")
        self.assertEqual(
            content["outdoor_game_slots"]["collective_1"]["name"], "手工保留"
        )
        row = next(
            item
            for item in content["deterministic"]
            if item["date"] == PLAN_DATE.isoformat()
        )
        self.assertEqual(row["source"]["morning_talk_topic"], "刷新后的主题")

    def _apply_config(self, change: dict) -> None:
        from app.local import config_service

        settings = self.session.get(LocalSettings, "singleton")
        preview = config_service.preview(
            self.session,
            expected_config_version=settings.config_version,
            change=change,
        )
        config_service.apply(
            self.session,
            request_id=str(uuid.uuid4()),
            expected_config_version=settings.config_version,
            change=change,
            preview_token=preview["preview_token"],
        )
        self.session.expire_all()

    def test_unrelated_game_guidance_does_not_mark_week_stale(self) -> None:
        self._create_daily()
        base = {
            "kind": "class_games",
            "locations": [
                {"kind": "area", "name": "积木区", "guidance": "先观察再介入"},
                {
                    "kind": "special_room",
                    "name": "音乐室",
                    "guidance": "旧指导",
                },
            ],
            "game_scope": "室内区域游戏",
            "guidance": "按幼儿兴趣提供材料",
        }
        self._apply_config(base)
        result, _ = self._create()
        plan_id = result["weekly_plan_id"]
        before = weekly_plan_service.get_detail(
            self.session, profile_id=self.profile.id, plan_id=plan_id
        )
        base["locations"][1]["guidance"] = "新指导"
        self._apply_config(base)
        after = weekly_plan_service.get_detail(
            self.session, profile_id=self.profile.id, plan_id=plan_id
        )
        self.assertEqual(
            after["source_context_hash"], before["source_context_hash"]
        )
        self.assertFalse(
            any(
                item.get("code") == "source_context_changed"
                for item in after["facts"]["warnings"]
            )
        )
        base["locations"][0]["guidance"] = "相关指导已变化"
        self._apply_config(base)
        changed = weekly_plan_service.get_detail(
            self.session, profile_id=self.profile.id, plan_id=plan_id
        )
        self.assertNotEqual(
            changed["source_context_hash"], before["source_context_hash"]
        )
        self.assertTrue(
            any(
                item.get("code") == "source_context_changed"
                for item in changed["facts"]["warnings"]
            )
        )

    def test_moved_term_refresh_uses_creation_term_for_zero_teaching_range(self) -> None:
        self._create_daily()
        result, _ = self._create()
        plan_id = result["weekly_plan_id"]
        self._apply_config(
            {
                "kind": "term_update",
                "term_id": self.term.id,
                "name": "冬季学期",
                "start_date": "2026-11-01",
                "end_date": "2026-11-30",
            }
        )
        moved = weekly_plan_service.get_detail(
            self.session, profile_id=self.profile.id, plan_id=plan_id
        )
        self.assertTrue(
            any(
                item.get("code") == "calendar_basis_changed"
                for item in moved["facts"]["warnings"]
            )
        )
        saved = weekly_plan_service.save_draft(
            self.session,
            profile_id=self.profile.id,
            request_id=str(uuid.uuid4()),
            plan_id=plan_id,
            expected_draft_version=1,
            patch={"theme": "移出学期"},
        )
        refresh = weekly_plan_service.refresh_preview(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            launch_id=self.launch,
            session_scope_hash=self.scope,
            plan_id=plan_id,
            expected_draft_version=saved["draft"]["version"],
        )
        refreshed = weekly_plan_service.refresh_sources(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            launch_id=self.launch,
            session_scope_hash=self.scope,
            request_id=str(uuid.uuid4()),
            plan_id=plan_id,
            expected_draft_version=saved["draft"]["version"],
            preview_token=refresh["preview_token"],
        )
        target = weekly_plan_service.confirmation_preview(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            launch_id=self.launch,
            session_scope_hash=self.scope,
            plan_id=plan_id,
            expected_draft_version=refreshed["draft"]["version"],
        )["target"]
        self.assertEqual(
            target["date_range"], {"start": "2026-09-07", "end": "2026-09-13"}
        )
        self.assertEqual(len(target["columns"]), 5)
        import sqlite3

        from app.local import backup_validate

        copy = self.tmp_root / "moved-term-copy.db"
        source = sqlite3.connect(str(self.runtime.db_path))
        dest = sqlite3.connect(str(copy))
        try:
            source.backup(dest)
        finally:
            dest.close()
            source.close()
        facts = backup_validate.validate_database(
            copy,
            migrate_old=False,
            require_current=True,
            scratch_dir=self.tmp_root,
        )
        self.assertEqual(facts["revision"], head_revision())

    def test_version_conflict_and_explicit_reselect_validation(self) -> None:
        self._create_daily()
        result, _ = self._create()
        plan_id = result["weekly_plan_id"]
        with self.assertRaises(LocalWeeklyVersionConflict):
            weekly_plan_service.save_draft(
                self.session,
                profile_id=self.profile.id,
                request_id=str(uuid.uuid4()),
                plan_id=plan_id,
                expected_draft_version=99,
                patch={"theme": "x"},
            )
        with self.assertRaises(LocalWeeklySourceChanged):
            weekly_plan_service.save_draft(
                self.session,
                profile_id=self.profile.id,
                request_id=str(uuid.uuid4()),
                plan_id=plan_id,
                expected_draft_version=1,
                patch={
                    "outdoor_game_slots": {
                        "collective_1": {
                            "source_kind": "daily_plan",
                            "daily_plan_id": "wrong",
                            "content_id": "wrong",
                            "content_version": 1,
                            "content_hash": "0" * 64,
                            "section": "morning_games",
                            "group_id": "wrong",
                            "game_id": "wrong",
                        }
                    }
                },
            )


class WeeklyMetadataSchemaTests(unittest.TestCase):
    """Pure receipt metadata schema tests; no Runtime, DB or service setup."""

    @staticmethod
    def _metadata(schema_version):
        return {
            "schema_version": schema_version,
            "weekly_plan_id": None,
            "draft_id": None,
            "draft_version": None,
            "confirmation_id": None,
            "confirmation_version": None,
            "snapshot_id": None,
            "token_id": None,
        }

    @staticmethod
    def _validate(metadata):
        from app.local.weekly_plan_operations import validate_metadata

        return validate_metadata(
            metadata,
            weekly_plan_id=None,
            draft_id=None,
            draft_version=None,
            confirmation_id=None,
            confirmation_version=None,
            snapshot_id=None,
            token_id=None,
        )

    def test_schema_version_accepts_only_real_integer_one(self) -> None:
        values = self._validate(self._metadata(1))
        self.assertIsNone(values["weekly_plan_id"])
        self.assertIsNone(values["draft_id"])
        self.assertIsNone(values["confirmation_id"])

    def test_schema_version_rejects_bool_float_and_other_values(self) -> None:
        for value in (True, False, 1.0, 0, 2, "1", None):
            with self.subTest(schema_version=value):
                with self.assertRaises(LocalWeeklyInvalid):
                    self._validate(self._metadata(value))
