"""Current-class header configuration tests (engineering spec §2.1)."""

from __future__ import annotations

import threading
import unittest
import uuid
from datetime import date
from types import SimpleNamespace

from pydantic import ValidationError

from app.local import config_service, profile_service, weekly_plan_service, weekly_plan_tokens
from app.local.errors import LocalConfigPreviewStale, LocalValidationError
from app.local.models import LocalClass, LocalSettings
from app.local.normalize import normalize_initialization
from app.local.schemas import WeeklyConfirmIn, WeeklyCreatePreviewIn
from app.local.weekly_plan_tokens import scope_hash
from tests.local.support import LocalTestCase


class WeeklyHeaderConfigTests(LocalTestCase):
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
            start_date=date(2026, 9, 7).isoformat(),
            end_date=date(2026, 10, 30).isoformat(),
            school_name="测试幼儿园",
        )
        profile_service.initialize(self.session, normalized)
        self.session.expire_all()
        self.settings = self.session.get(LocalSettings, "singleton")
        self.assertIsNotNone(self.settings)

    def _apply(self, change: dict) -> dict:
        preview = config_service.preview(
            self.session,
            expected_config_version=self.settings.config_version,
            change=change,
        )
        result = config_service.apply(
            self.session,
            request_id=str(uuid.uuid4()),
            expected_config_version=self.settings.config_version,
            change=change,
            preview_token=preview["preview_token"],
        )
        self.session.expire_all()
        self.settings = self.session.get(LocalSettings, "singleton")
        return result

    def _class(self) -> LocalClass:
        context = profile_service.read_context(self.session, date.today())
        return self.session.get(LocalClass, context["class"]["id"])

    def test_header_names_trim_order_and_duplicates_are_preserved(self) -> None:
        self._apply(
            {
                "kind": "current_class",
                "name": "中一班",
                "grade": "middle",
                "header_teacher_names": [" 王老师 ", "李老师", "王老师"],
                "caregiver_name": " 张阿姨 ",
            }
        )
        school_class = self._class()
        self.assertEqual(
            school_class.header_teacher_names, ["王老师", "李老师", "王老师"]
        )
        self.assertEqual(school_class.caregiver_name, "张阿姨")

    def test_omitted_fields_keep_values_and_explicit_empty_clears(self) -> None:
        self._apply(
            {
                "kind": "current_class",
                "name": "中一班",
                "grade": "middle",
                "header_teacher_names": ["王老师"],
                "caregiver_name": "张阿姨",
            }
        )
        self._apply(
            {"kind": "current_class", "name": "中一班", "grade": "middle"}
        )
        school_class = self._class()
        self.assertEqual(school_class.header_teacher_names, ["王老师"])
        self.assertEqual(school_class.caregiver_name, "张阿姨")
        self._apply(
            {
                "kind": "current_class",
                "name": "中一班",
                "grade": "middle",
                "header_teacher_names": [],
                "caregiver_name": None,
            }
        )
        school_class = self._class()
        self.assertEqual(school_class.header_teacher_names, [])
        self.assertIsNone(school_class.caregiver_name)

    def test_header_limits_are_rejected_not_truncated(self) -> None:
        base = {"kind": "current_class", "name": "中一班", "grade": "middle"}
        with self.assertRaises(LocalValidationError):
            config_service.normalize_change(
                {**base, "header_teacher_names": ["名"] * 101}
            )
        with self.assertRaises(LocalValidationError):
            config_service.normalize_change(
                {**base, "header_teacher_names": ["名" * 81]}
            )
        with self.assertRaises(LocalValidationError):
            config_service.normalize_change(
                {**base, "header_teacher_names": ["\x01" * 80] * 100}
            )
        with self.assertRaises(LocalValidationError):
            config_service.normalize_change(
                {**base, "header_teacher_names": "王老师"}
            )
        with self.assertRaises(LocalValidationError):
            config_service.normalize_change(
                {**base, "caregiver_name": "名" * 81}
            )

    def test_header_does_not_change_existing_weekly_plan_header(self) -> None:
        # Covered by the weekly service fixture; this test only ensures the
        # configuration path never rewrites existing class header history.
        self._apply(
            {
                "kind": "current_class",
                "name": "中一班",
                "grade": "middle",
                "header_teacher_names": ["王老师"],
            }
        )
        self.assertEqual(self._class().header_teacher_names, ["王老师"])


class WeeklyRequestStrictnessTests(unittest.TestCase):
    def test_iso_date_and_ack_are_strict(self) -> None:
        for value in (1757203200, "2026-09-07T00:00:00", "2026-9-7", ""):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    WeeklyCreatePreviewIn(term_id="t", week_anchor_date=value)
        with self.assertRaises(ValidationError):
            WeeklyConfirmIn(
                request_id=str(uuid.uuid4()),
                expected_draft_version=1,
                context_token="token",
                ack_missing=1,
            )
        with self.assertRaises(ValidationError):
            WeeklyConfirmIn(
                request_id=str(uuid.uuid4()),
                expected_draft_version=True,
                context_token="token",
            )

    def test_concurrent_first_tokens_are_both_valid(self) -> None:
        runtime = SimpleNamespace()
        barrier = threading.Barrier(2)
        results: list[str] = []
        errors: list[BaseException] = []

        def issue() -> None:
            try:
                barrier.wait()
                results.append(
                    weekly_plan_tokens.issue_token(
                        runtime,
                        purpose="create",
                        profile_id="p" * 22,
                        launch_id="l",
                        session_scope_hash="s" * 64,
                        object_id="t:2026-09-07",
                        expected_version=1,
                    )
                )
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=issue) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertFalse(errors)
        self.assertEqual(len(results), 2)
        for token in results:
            weekly_plan_tokens.verify_token(
                runtime,
                token,
                purpose="create",
                profile_id="p" * 22,
                launch_id="l",
                session_scope_hash="s" * 64,
                object_id="t:2026-09-07",
                expected_version=1,
            )


class ConfigWeeklyImpactTests(WeeklyHeaderConfigTests):
    def _create_manual_week(self) -> str:
        preview = weekly_plan_service.create_preview(
            self.session,
            runtime=self.runtime,
            profile_id=self.session.query(__import__("app.local.models", fromlist=["LocalProfile"]).LocalProfile).one().id,
            launch_id="config-impact",
            session_scope_hash=scope_hash("config-impact"),
            term_id=self._term().id,
            week_anchor_date=date(2026, 9, 7),
        )
        result, _ = weekly_plan_service.create_or_open(
            self.session,
            runtime=self.runtime,
            profile_id=self.session.query(__import__("app.local.models", fromlist=["LocalProfile"]).LocalProfile).one().id,
            launch_id="config-impact",
            session_scope_hash=scope_hash("config-impact"),
            request_id=str(uuid.uuid4()),
            term_id=self._term().id,
            week_anchor_date=date(2026, 9, 7),
            expected_config_version=self.settings.config_version,
            context_token=preview["create_token"],
        )
        return result["weekly_plan_id"]

    def _term(self):
        from app.local.models import LocalTerm

        return self.session.query(LocalTerm).one()

    def _create_week(self, term_id: str, anchor: date) -> str:
        preview = weekly_plan_service.create_preview(
            self.session,
            runtime=self.runtime,
            profile_id=self.session.query(__import__("app.local.models", fromlist=["LocalProfile"]).LocalProfile).one().id,
            launch_id="config-impact",
            session_scope_hash=scope_hash("config-impact"),
            term_id=term_id,
            week_anchor_date=anchor,
        )
        result, _ = weekly_plan_service.create_or_open(
            self.session,
            runtime=self.runtime,
            profile_id=self.session.query(__import__("app.local.models", fromlist=["LocalProfile"]).LocalProfile).one().id,
            launch_id="config-impact",
            session_scope_hash=scope_hash("config-impact"),
            request_id=str(uuid.uuid4()),
            term_id=term_id,
            week_anchor_date=anchor,
            expected_config_version=self.settings.config_version,
            context_token=preview["create_token"],
        )
        return result["weekly_plan_id"]

    def test_term_move_lists_manual_week_even_without_daily_plan(self) -> None:
        self._create_manual_week()
        preview = config_service.preview(
            self.session,
            expected_config_version=self.settings.config_version,
            change={
                "kind": "term_update",
                "term_id": self._term().id,
                "name": "秋季学期",
                "start_date": "2026-09-15",
                "end_date": "2026-10-30",
            },
        )
        impact = preview["impact"]
        self.assertEqual(impact["affected_plans"], [])
        self.assertEqual(len(impact["weekly_plans"]), 1)
        self.assertEqual(
            impact["weekly_plans"][0]["week_anchor_date"], "2026-09-07"
        )
        self.assertTrue(impact["weekly_plans"][0]["creation_context_retained"])
        self.assertIn(
            "weekly_anchor_outside_new_term",
            impact["weekly_plans"][0]["reasons"],
        )

    def test_term_create_does_not_lend_new_term_range_to_old_week(self) -> None:
        self._create_manual_week()
        # Move A to November so a new September term B can be created.
        self._apply_term_move = None
        preview = config_service.preview(
            self.session,
            expected_config_version=self.settings.config_version,
            change={
                "kind": "term_update",
                "term_id": self._term().id,
                "name": "冬季学期",
                "start_date": "2026-11-01",
                "end_date": "2026-11-30",
            },
        )
        config_service.apply(
            self.session,
            request_id=str(uuid.uuid4()),
            expected_config_version=self.settings.config_version,
            change={
                "kind": "term_update",
                "term_id": self._term().id,
                "name": "冬季学期",
                "start_date": "2026-11-01",
                "end_date": "2026-11-30",
            },
            preview_token=preview["preview_token"],
        )
        self.session.expire_all()
        create_preview = config_service.preview(
            self.session,
            expected_config_version=self.settings.config_version,
            change={
                "kind": "term_create",
                "name": "秋季学期B",
                "start_date": "2026-09-01",
                "end_date": "2026-10-30",
            },
        )
        impact = create_preview["impact"]
        self.assertEqual(len(impact["weekly_plans"]), 1)
        item = impact["weekly_plans"][0]
        self.assertFalse(item["creation_eligible_after"])
        self.assertIn("weekly_anchor_outside_own_term", item["reasons"])
        self.assertNotIn("weekly_week_intersects_new_term", item["reasons"])

    def test_calendar_override_only_affects_its_own_term_same_anchor(self) -> None:
        from sqlalchemy import select
        from app.local.models import LocalTerm

        a_term = self._term()
        a_plan = self._create_manual_week()
        move = {
            "kind": "term_update",
            "term_id": a_term.id,
            "name": "冬季学期A",
            "start_date": "2026-11-01",
            "end_date": "2026-11-30",
        }
        preview = config_service.preview(
            self.session,
            expected_config_version=self.settings.config_version,
            change=move,
        )
        config_service.apply(
            self.session,
            request_id=str(uuid.uuid4()),
            expected_config_version=self.settings.config_version,
            change=move,
            preview_token=preview["preview_token"],
        )
        self.session.expire_all()
        create_b = {
            "kind": "term_create",
            "name": "秋季学期B",
            "start_date": "2026-09-01",
            "end_date": "2026-10-30",
        }
        preview = config_service.preview(
            self.session,
            expected_config_version=self.settings.config_version,
            change=create_b,
        )
        config_service.apply(
            self.session,
            request_id=str(uuid.uuid4()),
            expected_config_version=self.settings.config_version,
            change=create_b,
            preview_token=preview["preview_token"],
        )
        self.session.expire_all()
        b_term = self.session.scalars(
            select(LocalTerm).where(LocalTerm.name == "秋季学期B")
        ).one()
        b_plan = self._create_week(b_term.id, date(2026, 9, 7))
        override = {
            "kind": "calendar_override",
            "term_id": b_term.id,
            "date": "2026-09-09",
            "state": "non_teaching",
            "reason": "B 日历变更",
        }
        preview = config_service.preview(
            self.session,
            expected_config_version=self.settings.config_version,
            change=override,
        )
        impact = preview["impact"]
        by_term = {item["term_id"]: item for item in impact["weekly_plans"]}
        self.assertIn(a_term.id, by_term)
        self.assertIn(b_term.id, by_term)
        self.assertEqual(len(impact["weekly_plans"]), 2)
        self.assertEqual(impact["affected_plans"], [])
        self.assertEqual(impact["weekly_retained_header_count"], 2)
        self.assertEqual(impact["counts"]["weekly_plan_count"], 2)
        self.assertEqual(
            impact["counts"]["affected_weekly_plan_count"], 1
        )
        self.assertEqual(by_term[a_term.id]["reasons"], [])
        self.assertNotIn(
            "weekly_calendar_override_in_week", by_term[a_term.id]["reasons"]
        )
        self.assertIn(
            "weekly_calendar_override_in_week", by_term[b_term.id]["reasons"]
        )
        self.assertFalse(by_term[a_term.id]["creation_eligible_after"])
        self.assertTrue(by_term[b_term.id]["creation_eligible_after"])
        self.assertEqual(
            impact["counts"]["weekly_by_reason"].get(
                "weekly_calendar_override_in_week"
            ),
            1,
        )
        a_detail = weekly_plan_service.get_detail(
            self.session, profile_id=self.profile_id(), plan_id=a_plan
        )
        b_detail = weekly_plan_service.get_detail(
            self.session, profile_id=self.profile_id(), plan_id=b_plan
        )
        self.assertEqual(
            a_detail["plan"]["week_anchor_date"], "2026-09-07"
        )
        self.assertEqual(
            b_detail["plan"]["week_anchor_date"], "2026-09-07"
        )

    def profile_id(self) -> str:
        from app.local.models import LocalProfile

        return self.session.query(LocalProfile).one().id

    def test_weekly_total_count_is_in_premise_digest(self) -> None:
        first_preview = weekly_plan_service.create_preview(
            self.session,
            runtime=self.runtime,
            profile_id=self.session.query(__import__("app.local.models", fromlist=["LocalProfile"]).LocalProfile).one().id,
            launch_id="config-count",
            session_scope_hash=scope_hash("config-count"),
            term_id=self._term().id,
            week_anchor_date=date(2026, 9, 7),
        )
        weekly_plan_service.create_or_open(
            self.session,
            runtime=self.runtime,
            profile_id=self.session.query(__import__("app.local.models", fromlist=["LocalProfile"]).LocalProfile).one().id,
            launch_id="config-count",
            session_scope_hash=scope_hash("config-count"),
            request_id=str(uuid.uuid4()),
            term_id=self._term().id,
            week_anchor_date=date(2026, 9, 7),
            expected_config_version=self.settings.config_version,
            context_token=first_preview["create_token"],
        )
        preview = config_service.preview(
            self.session,
            expected_config_version=self.settings.config_version,
            change={
                "kind": "calendar_override",
                "term_id": self._term().id,
                "date": "2026-09-07",
                "state": "non_teaching",
                "reason": "并发计数探针",
            },
        )
        second_preview = weekly_plan_service.create_preview(
            self.session,
            runtime=self.runtime,
            profile_id=self.session.query(__import__("app.local.models", fromlist=["LocalProfile"]).LocalProfile).one().id,
            launch_id="config-count",
            session_scope_hash=scope_hash("config-count"),
            term_id=self._term().id,
            week_anchor_date=date(2026, 10, 26),
        )
        weekly_plan_service.create_or_open(
            self.session,
            runtime=self.runtime,
            profile_id=self.session.query(__import__("app.local.models", fromlist=["LocalProfile"]).LocalProfile).one().id,
            launch_id="config-count",
            session_scope_hash=scope_hash("config-count"),
            request_id=str(uuid.uuid4()),
            term_id=self._term().id,
            week_anchor_date=date(2026, 10, 26),
            expected_config_version=self.settings.config_version,
            context_token=second_preview["create_token"],
        )
        with self.assertRaises(LocalConfigPreviewStale):
            config_service.apply(
                self.session,
                request_id=str(uuid.uuid4()),
                expected_config_version=self.settings.config_version,
                change={
                    "kind": "calendar_override",
                    "term_id": self._term().id,
                    "date": "2026-09-07",
                    "state": "non_teaching",
                    "reason": "并发计数探针",
                },
                preview_token=preview["preview_token"],
            )

    def test_class_rename_lists_week_header_retained(self) -> None:
        self._create_manual_week()
        preview = config_service.preview(
            self.session,
            expected_config_version=self.settings.config_version,
            change={
                "kind": "current_class",
                "name": "新班名",
                "grade": "middle",
            },
        )
        impact = preview["impact"]
        self.assertEqual(len(impact["weekly_plans"]), 1)
        self.assertTrue(impact["weekly_plans"][0]["header_retained"])
        self.assertIn(
            "weekly_header_retained", impact["weekly_plans"][0]["reasons"]
        )
