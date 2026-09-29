"""Schema unit tests for the I5 export request bodies (slice 3).

Pure pydantic coverage of the two strict ``extra="forbid"`` models — no app
import side effects, no DB, no HTTP. Covers spec §3.2 / §8:

* unknown fields are always rejected (term ids, plan ids, content versions,
  client facts, draft shapes);
* ``from``/``to`` are required dates with ``from <= to``;
* ``ack_missing`` and ``confirmed_version`` are strict (booleans never pass
  as integers, strings/floats never pass as integers);
* the weekly dual mode is mutually exclusive (both modes, neither mode,
  one-sided ranges and single-mode bodies carrying ``from``/``to`` are 422);
* ``class_id`` accepts a stored None value at the schema layer — presence
  (explicit null versus omitted) is judged by the router on
  ``model_fields_set``, so a teacher's ``null`` is never "not sent".
"""

import os

os.environ["APP_DISABLE_DOTENV"] = "1"

import unittest

from pydantic import ValidationError

from app.schemas import DailyExportIn, WeeklyExportIn


def daily_payload(**overrides) -> dict:
    payload = {"from": "2026-09-01", "to": "2026-09-30"}
    payload.update(overrides)
    return payload


def weekly_range_payload(**overrides) -> dict:
    payload = {"from": "2026-09-01", "to": "2026-10-06"}
    payload.update(overrides)
    return payload


def weekly_single_payload(**overrides) -> dict:
    payload = {"plan_id": "wp1"}
    payload.update(overrides)
    return payload


class DailyExportSchemaTests(unittest.TestCase):
    def test_valid_minimal_body(self):
        data = DailyExportIn.model_validate(daily_payload())
        self.assertEqual(data.from_.isoformat(), "2026-09-01")
        self.assertEqual(data.to.isoformat(), "2026-09-30")
        self.assertFalse(data.ack_missing)
        self.assertIsNone(data.expected_context)
        self.assertIsNone(data.class_id)
        self.assertNotIn("class_id", data.model_fields_set)

    def test_equal_dates_and_month_range_accepted(self):
        for start, end in (
            ("2026-09-07", "2026-09-07"),  # single day
            ("2026-09-07", "2026-09-13"),  # one week
            ("2026-09-01", "2026-09-30"),  # month
            ("2026-01-01", "2026-12-31"),  # custom
        ):
            with self.subTest(start=start, end=end):
                data = DailyExportIn.model_validate(
                    daily_payload(**{"from": start, "to": end})
                )
                self.assertEqual(data.from_.isoformat(), start)
                self.assertEqual(data.to.isoformat(), end)

    def test_from_after_to_rejected(self):
        with self.assertRaises(ValidationError):
            DailyExportIn.model_validate(
                daily_payload(**{"from": "2026-09-30", "to": "2026-09-01"})
            )

    def test_required_dates(self):
        payload = daily_payload()
        del payload["from"]
        with self.assertRaises(ValidationError):
            DailyExportIn.model_validate(payload)
        payload = daily_payload()
        del payload["to"]
        with self.assertRaises(ValidationError):
            DailyExportIn.model_validate(payload)

    def test_invalid_date_format_rejected(self):
        with self.assertRaises(ValidationError):
            DailyExportIn.model_validate(daily_payload(**{"from": "2026/09/01"}))

    def test_unknown_fields_rejected(self):
        for extra in (
            {"plan_id": "plan1"},
            {"term_id": "ter1"},
            {"content_version": 2},
            {"facts": [{"kind": "empty_field"}]},
            {"draft": {}},
            {"adopted_content": {}},
            {"random_unknown": 1},
        ):
            with self.subTest(extra=extra):
                with self.assertRaises(ValidationError):
                    DailyExportIn.model_validate(daily_payload(**extra))

    def test_ack_missing_is_strict_boolean(self):
        self.assertTrue(
            DailyExportIn.model_validate(daily_payload(ack_missing=True)).ack_missing
        )
        for bad in (1, 0, 1.0, "true", "false", None, "yes"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValidationError):
                    DailyExportIn.model_validate(daily_payload(ack_missing=bad))

    def test_expected_context_round_trip(self):
        context = {
            "class_id": "cls1",
            "from": "2026-09-01",
            "to": "2026-09-30",
            "versions": [{"daily_plan_id": "p1", "content_id": "c1", "content_version": 2}],
            "missing_fingerprint": "abc",
            "missing_count": 3,
        }
        data = DailyExportIn.model_validate(daily_payload(expected_context=context))
        self.assertEqual(data.expected_context, context)

    def test_class_id_null_is_kept_as_explicit_value(self):
        """The schema stores the explicit null; presence goes to the router."""
        data = DailyExportIn.model_validate(daily_payload(class_id=None))
        self.assertIsNone(data.class_id)
        self.assertIn("class_id", data.model_fields_set)


class WeeklyExportSchemaTests(unittest.TestCase):
    def test_valid_single_mode_defaults_version(self):
        data = WeeklyExportIn.model_validate(weekly_single_payload())
        self.assertEqual(data.plan_id, "wp1")
        self.assertIsNone(data.confirmed_version)
        self.assertIsNone(data.from_)
        self.assertIsNone(data.to)

    def test_valid_single_mode_with_version(self):
        data = WeeklyExportIn.model_validate(
            weekly_single_payload(confirmed_version=3)
        )
        self.assertEqual(data.confirmed_version, 3)

    def test_valid_range_mode(self):
        data = WeeklyExportIn.model_validate(weekly_range_payload())
        self.assertEqual(data.from_.isoformat(), "2026-09-01")
        self.assertEqual(data.to.isoformat(), "2026-10-06")
        self.assertIsNone(data.plan_id)
        self.assertIsNone(data.confirmed_version)

    def test_both_modes_rejected(self):
        with self.assertRaises(ValidationError):
            WeeklyExportIn.model_validate(
                weekly_range_payload(plan_id="wp1", confirmed_version=1)
            )
        with self.assertRaises(ValidationError):
            WeeklyExportIn.model_validate(
                weekly_single_payload(  # no range keys except plan_id
                    to=None,
                )
            )

    def test_range_carries_plan_version_rejected(self):
        with self.assertRaises(ValidationError):
            WeeklyExportIn.model_validate(weekly_range_payload(plan_id="wp1"))
        with self.assertRaises(ValidationError):
            WeeklyExportIn.model_validate(
                weekly_range_payload(confirmed_version=2)
            )

    def test_one_sided_range_rejected(self):
        with self.assertRaises(ValidationError):
            WeeklyExportIn.model_validate({"from": "2026-09-01"})
        with self.assertRaises(ValidationError):
            WeeklyExportIn.model_validate({"to": "2026-09-30"})
        with self.assertRaises(ValidationError):
            WeeklyExportIn.model_validate({"from": "2026-09-01", "to": None})

    def test_single_mode_cARRYing_range_keys_rejected(self):
        """Single mode must not carry from/to — even as explicit null."""
        with self.assertRaises(ValidationError):
            WeeklyExportIn.model_validate(
                weekly_single_payload(**{"from": "2026-09-01"})
            )
        with self.assertRaises(ValidationError):
            WeeklyExportIn.model_validate(
                weekly_single_payload(**{"from": None})
            )
        with self.assertRaises(ValidationError):
            WeeklyExportIn.model_validate(
                weekly_single_payload(**{"from": None, "to": None})
            )

    def test_single_mode_requires_plan_id(self):
        with self.assertRaises(ValidationError):
            WeeklyExportIn.model_validate({"plan_id": None})
        with self.assertRaises(ValidationError):
            WeeklyExportIn.model_validate({"plan_id": ""})
        with self.assertRaises(ValidationError):
            WeeklyExportIn.model_validate({"confirmed_version": 2})

    def test_no_mode_at_all_rejected(self):
        with self.assertRaises(ValidationError):
            WeeklyExportIn.model_validate({})
        with self.assertRaises(ValidationError):
            WeeklyExportIn.model_validate({"class_id": "cls1"})

    def test_confirmed_version_bounds_and_strictness(self):
        with self.assertRaises(ValidationError):
            WeeklyExportIn.model_validate(
                weekly_single_payload(confirmed_version=0)
            )
        with self.assertRaises(ValidationError):
            WeeklyExportIn.model_validate(
                weekly_single_payload(confirmed_version=True)
            )
        with self.assertRaises(ValidationError):
            WeeklyExportIn.model_validate(
                weekly_single_payload(confirmed_version=1.0)
            )
        with self.assertRaises(ValidationError):
            WeeklyExportIn.model_validate(
                weekly_single_payload(confirmed_version="3")
            )

    def test_range_order_rejected(self):
        with self.assertRaises(ValidationError):
            WeeklyExportIn.model_validate(
                weekly_range_payload(
                    **{"from": "2026-10-06", "to": "2026-09-01"}
                )
            )

    def test_unknown_fields_rejected(self):
        for extra in (
            {"term_id": "ter1"},
            {"content_id": "c1"},
            {"draft_version": 2},
            {"facts": {}},
            {"source_candidates": []},
            {"week_number": 2},
            {"random_unknown": 1},
        ):
            for base in (weekly_range_payload, weekly_single_payload):
                with self.subTest(extra=extra, base=base.__name__):
                    with self.assertRaises(ValidationError):
                        WeeklyExportIn.model_validate(base(**extra))

    def test_class_id_null_is_kept_as_explicit_value(self):
        data = WeeklyExportIn.model_validate(weekly_range_payload(class_id=None))
        self.assertIsNone(data.class_id)
        self.assertIn("class_id", data.model_fields_set)


if __name__ == "__main__":
    unittest.main()
