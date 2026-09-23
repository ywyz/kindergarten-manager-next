"""No-DB tests for the weekly pending-projection builders and service codes."""

import unittest
from datetime import date, datetime
from types import SimpleNamespace
from unittest import mock

from app.models import DailyPlan, Term
from app.services import daily_plan_service
from app.services.daily_plan_service import (
    DailyPlanDataError,
    DailyPlanDateNotEligible,
    DailyPlanForbidden,
    DailyPlanNotFound,
    DailyPlanOutsideTerm,
    DailyPlanOutsideTerm as OutsideTerm,
    DailyPlanServiceError,
    DailyPlanValidationError,
    DailyPlanVersionConflict,
    DailyPlanYearNotCovered,
    _normalize_raw,
)
from app.services.weekly_plan_sync_service import (
    WeekPlanEntry,
    build_current_week_source_manifest,
    build_deterministic_themes,
    build_game_source_manifest,
)


def _entry(day: int, *, content_id, version, adopted, plan_id=None):
    return WeekPlanEntry(
        plan_id=plan_id or f"plan-{day}",
        content_id=content_id,
        content_version=version,
        plan_date=date(2026, 9, day),
        adopted_content=adopted,
    )


class ProjectionBuilderTests(unittest.TestCase):
    def test_themes_cover_all_days_sorted_by_date(self):
        entries = [
            _entry(
                8,
                content_id="c8",
                version=2,
                adopted={
                    "morning_talk": {"topic": "话题二"},
                    "group_activity": {"theme": "主题二"},
                },
            ),
            _entry(
                7,
                content_id="c7",
                version=1,
                adopted={
                    "morning_talk": {"topic": "话题一"},
                    "group_activity": {"theme": "主题一"},
                },
            ),
        ]
        themes = build_deterministic_themes(entries)
        self.assertEqual(
            themes,
            [
                {
                    "date": "2026-09-07",
                    "morning_talk_topic": "话题一",
                    "group_activity_theme": "主题一",
                },
                {
                    "date": "2026-09-08",
                    "morning_talk_topic": "话题二",
                    "group_activity_theme": "主题二",
                },
            ],
        )

    def test_themes_default_missing_fields_to_empty_string(self):
        themes = build_deterministic_themes(
            [_entry(7, content_id="c", version=1, adopted={})]
        )
        self.assertEqual(
            themes,
            [
                {
                    "date": "2026-09-07",
                    "morning_talk_topic": "",
                    "group_activity_theme": "",
                }
            ],
        )

    def test_game_manifest_covers_all_sections_with_exact_path(self):
        prepared = {
            "morning_games": [
                {
                    "group_id": "gm",
                    "group_kind": "collective",
                    "games": [
                        {"game_id": "ga", "name": "a"},
                        {"game_id": "gb", "name": "b"},
                    ],
                }
            ],
            "post_group_games": [
                {
                    "group_id": "gp",
                    "context_kind": "area",
                    "area": "建构区",
                    "games": [{"game_id": "gc", "name": "c"}],
                }
            ],
            "afternoon_outdoor": {
                "group_id": "go",
                "area": "操场",
                "observation_focus": "重点观察",
                "games": [{"game_id": "gd", "name": "d"}],
            },
        }
        manifest = build_game_source_manifest(
            [_entry(7, content_id="c7", version=3, adopted=prepared)]
        )
        self.assertEqual(len(manifest), 4)
        self.assertEqual(
            manifest[0],
            {
                "daily_plan_id": "plan-7",
                "content_version": 3,
                "date": "2026-09-07",
                "group_id": "gm",
                "game_id": "ga",
                "context_kind": None,
            },
        )
        self.assertEqual(
            [m["game_id"] for m in manifest], ["ga", "gb", "gc", "gd"]
        )
        self.assertEqual(
            [m["context_kind"] for m in manifest],
            [None, None, "area", None],
        )

    def test_game_manifest_skips_sections_absent_from_content(self):
        manifest = build_game_source_manifest(
            [_entry(7, content_id="c", version=1, adopted={"reflection": "x"})]
        )
        self.assertEqual(manifest, [])

    def test_source_manifest_lists_every_day_with_current_pointer(self):
        entries = [
            _entry(8, content_id="c8", version=2, adopted={}),
            _entry(7, content_id="c7", version=1, adopted={}),
        ]
        sources = build_current_week_source_manifest(entries)
        self.assertEqual(
            sources,
            [
                {
                    "daily_plan_id": "plan-7",
                    "current_content_id": "c7",
                    "current_content_version": 1,
                    "date": "2026-09-07",
                },
                {
                    "daily_plan_id": "plan-8",
                    "current_content_id": "c8",
                    "current_content_version": 2,
                    "date": "2026-09-08",
                },
            ],
        )

    def test_empty_week_produces_empty_manifests(self):
        self.assertEqual(build_deterministic_themes([]), [])
        self.assertEqual(build_game_source_manifest([]), [])
        self.assertEqual(build_current_week_source_manifest([]), [])

    def test_builders_are_deterministic_regardless_of_input_order(self):
        a = _entry(7, content_id="c7", version=1, adopted={"reflection": "x"})
        b = _entry(8, content_id="c8", version=1, adopted={"reflection": "y"})
        self.assertEqual(
            build_current_week_source_manifest([a, b]),
            build_current_week_source_manifest([b, a]),
        )
        self.assertEqual(
            build_deterministic_themes([a, b]),
            build_deterministic_themes([b, a]),
        )
        self.assertEqual(
            build_game_source_manifest([a, b]),
            build_game_source_manifest([b, a]),
        )


class ServiceCodeTests(unittest.TestCase):
    def test_error_codes_match_spec(self):
        self.assertEqual(DailyPlanNotFound.code, "DAILY_PLAN_NOT_FOUND")
        self.assertEqual(DailyPlanVersionConflict.code, "VERSION_CONFLICT")
        self.assertEqual(OutsideTerm.code, "OUTSIDE_TERM")
        self.assertEqual(DailyPlanDateNotEligible.code, "DATE_NOT_ELIGIBLE")
        self.assertEqual(DailyPlanYearNotCovered.code, "YEAR_NOT_COVERED")
        self.assertEqual(DailyPlanForbidden.code, "FORBIDDEN")
        self.assertEqual(DailyPlanValidationError.code, "VALIDATION_ERROR")
        self.assertEqual(DailyPlanDataError.code, "SERVICE_UNAVAILABLE")

    def test_normalize_raw_accepts_str_and_none_only(self):
        self.assertIsNone(_normalize_raw(None))
        self.assertEqual(_normalize_raw("教案"), "教案")
        for bad in (5, ["x"], {"a": 1}, True):
            with self.subTest(bad=bad):
                with self.assertRaises(DailyPlanValidationError):
                    _normalize_raw(bad)

    def test_all_service_errors_carry_code(self):
        for cls in (
            DailyPlanNotFound,
            DailyPlanVersionConflict,
            DailyPlanOutsideTerm,
            DailyPlanDateNotEligible,
            DailyPlanYearNotCovered,
            DailyPlanForbidden,
            DailyPlanValidationError,
            DailyPlanDataError,
        ):
            with self.subTest(cls=cls):
                self.assertTrue(issubclass(cls, DailyPlanServiceError))
                self.assertTrue(cls.code)


def _summary_plan() -> DailyPlan:
    return DailyPlan(
        id="plan1",
        class_id="cls1",
        term_id="ter1",
        plan_date=date(2026, 9, 7),
        creator_id="tch1",
        week_number=2,
        weekday=1,
        current_content_id="cnt1",
        current_content_version=1,
        creator_display_name="甲老师",
        school_name=None,
        class_name="小班甲",
        grade="small",
        created_at=datetime(2026, 9, 7, 8, 0, 0),
        updated_at=datetime(2026, 9, 7, 8, 0, 0),
    )


def _summary_term() -> Term:
    return Term(
        id="ter1",
        name="2026秋",
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 30),
        version=1,
        current_calendar_revision_id="rev1",
    )


class WeeklySyncSummaryTests(unittest.TestCase):
    def _row(self, manifest) -> SimpleNamespace:
        return SimpleNamespace(
            status="pending_projection",
            current_week_source_manifest=manifest,
        )

    def _db(self, *, term, teaching_days):
        db = mock.MagicMock()
        db.get.return_value = term
        db.scalars.return_value.all.return_value = [
            SimpleNamespace(date=day) for day in teaching_days
        ]
        return db

    def _summary(self, db, manifest):
        with mock.patch.object(
            daily_plan_service.weekly_plan_sync_service,
            "get_weekly_sync_state",
            return_value=self._row(manifest),
        ):
            return daily_plan_service.weekly_sync_summary(db, _summary_plan())

    def test_missing_projection_row_is_data_error(self):
        db = mock.MagicMock()
        with mock.patch.object(
            daily_plan_service.weekly_plan_sync_service,
            "get_weekly_sync_state",
            return_value=None,
        ):
            with self.assertRaises(DailyPlanDataError) as ctx:
                daily_plan_service.weekly_sync_summary(db, _summary_plan())
        self.assertEqual(ctx.exception.code, "SERVICE_UNAVAILABLE")
        db.get.assert_not_called()

    def test_saved_dates_sorted_and_missing_teaching_days(self):
        db = self._db(
            term=_summary_term(),
            teaching_days=[
                date(2026, 9, 9),
                date(2026, 9, 7),
                date(2026, 9, 8),
                date(2026, 9, 10),
                date(2026, 9, 11),
                date(2026, 9, 12),
            ],
        )
        summary = self._summary(
            db,
            [
                {
                    "daily_plan_id": "plan1",
                    "current_content_id": "cnt1",
                    "current_content_version": 1,
                    "date": "2026-09-07",
                }
            ],
        )
        self.assertEqual(summary["status"], "pending_projection")
        self.assertTrue(summary["has_pending_projection"])
        self.assertEqual(summary["saved_dates"], ["2026-09-07"])
        self.assertEqual(
            summary["missing_dates"],
            [
                "2026-09-08",
                "2026-09-09",
                "2026-09-10",
                "2026-09-11",
                "2026-09-12",
            ],
        )

    def test_all_days_saved_produces_empty_missing(self):
        db = self._db(
            term=_summary_term(),
            teaching_days=[date(2026, 9, 7), date(2026, 9, 8)],
        )
        summary = self._summary(
            db,
            [
                {"date": "2026-09-08", "daily_plan_id": "b"},
                {"date": "2026-09-07", "daily_plan_id": "a"},
            ],
        )
        self.assertEqual(summary["saved_dates"], ["2026-09-07", "2026-09-08"])
        self.assertEqual(summary["missing_dates"], [])

    def test_malformed_manifest_entries_are_skipped(self):
        db = self._db(term=_summary_term(), teaching_days=[])
        summary = self._summary(db, [{"no_date": True}, "junk", None])
        self.assertEqual(summary["saved_dates"], [])
        self.assertEqual(summary["missing_dates"], [])

    def test_term_without_revision_is_data_error(self):
        term = _summary_term()
        term.current_calendar_revision_id = None
        db = self._db(term=term, teaching_days=[])
        with mock.patch.object(
            daily_plan_service.weekly_plan_sync_service,
            "get_weekly_sync_state",
            return_value=self._row([]),
        ):
            with self.assertRaises(DailyPlanDataError) as ctx:
                daily_plan_service.weekly_sync_summary(db, _summary_plan())
        self.assertEqual(ctx.exception.code, "SERVICE_UNAVAILABLE")

    def test_missing_term_is_data_error(self):
        db = self._db(term=None, teaching_days=[])
        with mock.patch.object(
            daily_plan_service.weekly_plan_sync_service,
            "get_weekly_sync_state",
            return_value=self._row([]),
        ):
            with self.assertRaises(DailyPlanDataError):
                daily_plan_service.weekly_sync_summary(db, _summary_plan())


if __name__ == "__main__":
    unittest.main()
