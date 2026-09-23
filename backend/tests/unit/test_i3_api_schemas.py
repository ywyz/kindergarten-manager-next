"""No-DB Pydantic tests for I3 request/response schemas (extra=forbid)."""

import unittest
from datetime import date, datetime

from pydantic import ValidationError

from app.schemas import (
    DailyPlanContentOut,
    DailyPlanCreateIn,
    DailyPlanListItemOut,
    DailyPlanListOut,
    DailyPlanOut,
    DailyPlanPatchIn,
    WeeklyPlanSyncStateOut,
    WeeklySyncSummaryOut,
)


def _valid_content() -> dict:
    return {
        "id": "cnt1",
        "version": 2,
        "raw_lesson_plan": "教案",
        "split_baseline": None,
        "adopted_content": {
            "morning_games": [
                {
                    "group_id": "grp1",
                    "group_kind": "collective",
                    "games": [{"game_id": "gam1", "name": "跳绳"}],
                }
            ]
        },
        "editor_id": "tch1",
        "created_at": datetime(2026, 9, 7, 8, 0, 0),
    }


def _valid_summary() -> dict:
    return {
        "status": "pending_projection",
        "has_pending_projection": True,
        "saved_dates": ["2026-09-07"],
        "missing_dates": ["2026-09-08"],
    }


def _valid_plan_out() -> dict:
    return {
        "id": "plan1",
        "class_id": "cls1",
        "term_id": "ter1",
        "plan_date": date(2026, 9, 7),
        "week_number": 2,
        "weekday": 1,
        "creator_id": "tch1",
        "creator_display_name": "甲老师",
        "current_content_id": "cnt1",
        "current_content_version": 2,
        "content": _valid_content(),
        "school_name": "阳光园",
        "class_name": "小班甲",
        "grade": "small",
        "weekly_sync_state": _valid_summary(),
        "created_at": datetime(2026, 9, 7, 8, 0, 0),
        "updated_at": datetime(2026, 9, 8, 9, 0, 0),
    }


class DailyPlanCreateInTests(unittest.TestCase):
    def test_minimal_payload_only_sets_plan_date(self):
        data = DailyPlanCreateIn.model_validate({"plan_date": "2026-09-07"})
        self.assertEqual(data.plan_date, date(2026, 9, 7))
        self.assertIsNone(data.class_id)
        self.assertEqual(data.model_fields_set, {"plan_date"})

    def test_extra_fields_rejected_including_term_and_split_baseline(self):
        for extra in ("term_id", "split_baseline", "bogus"):
            with self.subTest(extra=extra):
                with self.assertRaises(ValidationError):
                    DailyPlanCreateIn.model_validate(
                        {"plan_date": "2026-09-07", extra: "x"}
                    )

    def test_omitted_and_explicit_null_are_distinguishable(self):
        omitted = DailyPlanCreateIn.model_validate(
            {"plan_date": "2026-09-07"}
        )
        explicit = DailyPlanCreateIn.model_validate(
            {
                "plan_date": "2026-09-07",
                "raw_lesson_plan": None,
                "adopted_content": None,
            }
        )
        self.assertNotIn("raw_lesson_plan", omitted.model_fields_set)
        self.assertNotIn("adopted_content", omitted.model_fields_set)
        self.assertIn("raw_lesson_plan", explicit.model_fields_set)
        self.assertIn("adopted_content", explicit.model_fields_set)
        self.assertIsNone(explicit.raw_lesson_plan)

    def test_class_id_optional_at_schema_level(self):
        data = DailyPlanCreateIn.model_validate(
            {"plan_date": "2026-09-07", "class_id": "cls1"}
        )
        self.assertEqual(data.class_id, "cls1")

    def test_class_id_presence_tracked_in_fields_set(self):
        omitted = DailyPlanCreateIn.model_validate(
            {"plan_date": "2026-09-07"}
        )
        explicit_null = DailyPlanCreateIn.model_validate(
            {"plan_date": "2026-09-07", "class_id": None}
        )
        with_value = DailyPlanCreateIn.model_validate(
            {"plan_date": "2026-09-07", "class_id": "cls1"}
        )
        # The router judges presence on model_fields_set, so the schema must
        # preserve the omitted vs explicit-null distinction for class_id.
        self.assertNotIn("class_id", omitted.model_fields_set)
        self.assertIn("class_id", explicit_null.model_fields_set)
        self.assertIsNone(explicit_null.class_id)
        self.assertIn("class_id", with_value.model_fields_set)
        self.assertEqual(with_value.class_id, "cls1")

    def test_invalid_plan_date_rejected(self):
        with self.assertRaises(ValidationError):
            DailyPlanCreateIn.model_validate({"plan_date": "07/09/2026"})


class DailyPlanPatchInTests(unittest.TestCase):
    def test_expected_content_version_required(self):
        with self.assertRaises(ValidationError):
            DailyPlanPatchIn.model_validate({"raw_lesson_plan": "x"})

    def test_expected_content_version_must_be_ge_1(self):
        with self.assertRaises(ValidationError):
            DailyPlanPatchIn.model_validate({"expected_content_version": 0})

    def test_expected_content_version_rejects_bool_float_and_string(self):
        # Strict integer: no coercion from bool/float/str (service keeps its
        # own bool guard as defense in depth).
        for bad in (True, False, 1.0, 0.0, "1", "2"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValidationError):
                    DailyPlanPatchIn.model_validate(
                        {"expected_content_version": bad}
                    )

    def test_expected_content_version_accepts_positive_ints(self):
        for good in (1, 2, 99):
            with self.subTest(good=good):
                data = DailyPlanPatchIn.model_validate(
                    {"expected_content_version": good}
                )
                self.assertEqual(data.expected_content_version, good)
                self.assertIsInstance(data.expected_content_version, int)
                self.assertNotIsInstance(data.expected_content_version, bool)

    def test_split_baseline_rejected(self):
        with self.assertRaises(ValidationError):
            DailyPlanPatchIn.model_validate(
                {"expected_content_version": 1, "split_baseline": {}}
            )

    def test_class_id_and_term_id_rejected(self):
        for extra in ("class_id", "term_id"):
            with self.subTest(extra=extra):
                with self.assertRaises(ValidationError):
                    DailyPlanPatchIn.model_validate(
                        {"expected_content_version": 1, extra: "x"}
                    )

    def test_omitted_optional_fields_not_in_fields_set(self):
        data = DailyPlanPatchIn.model_validate(
            {"expected_content_version": 3}
        )
        self.assertEqual(data.model_fields_set, {"expected_content_version"})
        self.assertIsNone(data.raw_lesson_plan)

    def test_explicit_null_raw_is_tracked(self):
        data = DailyPlanPatchIn.model_validate(
            {"expected_content_version": 3, "raw_lesson_plan": None}
        )
        self.assertIn("raw_lesson_plan", data.model_fields_set)
        self.assertIsNone(data.raw_lesson_plan)


class DailyPlanOutTests(unittest.TestCase):
    def test_valid_payload_roundtrips(self):
        out = DailyPlanOut.model_validate(_valid_plan_out())
        self.assertEqual(out.current_content_version, 2)
        self.assertEqual(
            out.content.adopted_content["morning_games"][0]["games"][0][
                "game_id"
            ],
            "gam1",
        )

    def test_deleted_fields_are_rejected(self):
        for field in ("deleted_at", "deleted_by"):
            with self.subTest(field=field):
                payload = _valid_plan_out()
                payload[field] = None
                with self.assertRaises(ValidationError):
                    DailyPlanOut.model_validate(payload)

    def test_unknown_top_level_field_rejected(self):
        payload = _valid_plan_out()
        payload["extra"] = 1
        with self.assertRaises(ValidationError):
            DailyPlanOut.model_validate(payload)

    def test_missing_weekly_sync_state_rejected(self):
        payload = _valid_plan_out()
        del payload["weekly_sync_state"]
        with self.assertRaises(ValidationError):
            DailyPlanOut.model_validate(payload)


class DailyPlanListOutTests(unittest.TestCase):
    def test_valid_list_payload(self):
        item = {
            "id": "plan1",
            "plan_date": date(2026, 9, 7),
            "week_number": 2,
            "weekday": 1,
            "creator_id": "tch1",
            "creator_display_name": "甲老师",
            "current_content_version": 2,
            "created_at": datetime(2026, 9, 7, 8, 0, 0),
            "updated_at": datetime(2026, 9, 8, 9, 0, 0),
        }
        out = DailyPlanListOut.model_validate(
            {"items": [item], "total": 1, "offset": 0, "limit": 20}
        )
        self.assertEqual(out.total, 1)
        DailyPlanListItemOut.model_validate(item)

    def test_list_item_rejects_deleted_fields(self):
        item = {
            "id": "plan1",
            "plan_date": date(2026, 9, 7),
            "week_number": 2,
            "weekday": 1,
            "creator_id": "tch1",
            "creator_display_name": None,
            "current_content_version": 1,
            "created_at": datetime(2026, 9, 7, 8, 0, 0),
            "updated_at": datetime(2026, 9, 7, 8, 0, 0),
            "deleted_at": None,
        }
        with self.assertRaises(ValidationError):
            DailyPlanListItemOut.model_validate(item)


class WeeklySyncSchemasTests(unittest.TestCase):
    def test_summary_extra_field_rejected(self):
        payload = _valid_summary()
        payload["bogus"] = 1
        with self.assertRaises(ValidationError):
            WeeklySyncSummaryOut.model_validate(payload)

    def test_sync_state_full_payload_and_null_triggers(self):
        payload = {
            "id": "wss1",
            "class_id": "cls1",
            "term_id": "ter1",
            "week_number": 2,
            "status": "pending_projection",
            "deterministic_themes": [],
            "game_source_manifest": [],
            "current_week_source_manifest": [],
            "last_trigger_daily_plan_id": None,
            "last_trigger_content_version": None,
            "last_trigger_event": None,
            "created_at": datetime(2026, 9, 7, 8, 0, 0),
            "updated_at": datetime(2026, 9, 7, 8, 0, 0),
        }
        out = WeeklyPlanSyncStateOut.model_validate(payload)
        self.assertEqual(out.status, "pending_projection")
        self.assertIsNone(out.last_trigger_event)

    def test_sync_state_rejects_unknown_field(self):
        payload = {
            "id": "wss1",
            "class_id": "cls1",
            "term_id": "ter1",
            "week_number": 2,
            "status": "pending_projection",
            "deterministic_themes": [],
            "game_source_manifest": [],
            "current_week_source_manifest": [],
            "last_trigger_daily_plan_id": None,
            "last_trigger_content_version": None,
            "last_trigger_event": None,
            "created_at": datetime(2026, 9, 7, 8, 0, 0),
            "updated_at": datetime(2026, 9, 7, 8, 0, 0),
            "confirmed_exists": False,
        }
        with self.assertRaises(ValidationError):
            WeeklyPlanSyncStateOut.model_validate(payload)

    def test_content_out_extra_field_rejected(self):
        content = _valid_content()
        content["deleted_at"] = None
        with self.assertRaises(ValidationError):
            DailyPlanContentOut.model_validate(content)


if __name__ == "__main__":
    unittest.main()
