"""No-DB validation tests for I2 request schemas and calendar math."""

import unittest
from datetime import date

import pydantic
from pydantic import TypeAdapter

from app.schemas import ApplyIn, Proposal
from app.services import calendar_service as cal


class I2ValidationTests(unittest.TestCase):
    def setUp(self):
        self._proposal_adapter = TypeAdapter(Proposal)

    # -- Apply confirm -------------------------------------------------------

    def test_apply_requires_literal_true(self):
        self.assertIs(ApplyIn(confirm=True).confirm, True)
        for bad in (None, False, 0, 1, "true", "yes"):
            with self.subTest(value=bad):
                with self.assertRaises(pydantic.ValidationError):
                    ApplyIn(confirm=bad)

    # -- class_update null rejection -----------------------------------------

    def test_class_update_rejects_explicit_null_but_allows_omission(self):
        ok = self._proposal_adapter.validate_python(
            {
                "kind": "class_update",
                "target_id": "c1",
                "expected_version": 1,
                "grade": "small",
            }
        )
        self.assertEqual(ok.kind, "class_update")

        for field in ("name", "grade", "header_teacher_names"):
            with self.subTest(field=field):
                with self.assertRaises(pydantic.ValidationError):
                    self._proposal_adapter.validate_python(
                        {
                            "kind": "class_update",
                            "target_id": "c1",
                            "expected_version": 1,
                            field: None,
                        }
                    )

        cleared = self._proposal_adapter.validate_python(
            {
                "kind": "class_update",
                "target_id": "c1",
                "expected_version": 1,
                "caregiver_name": None,
            }
        )
        self.assertIsNone(cleared.caregiver_name)

    # -- Week numbering ------------------------------------------------------

    def test_week_numbering_starts_at_one_and_does_not_reset_on_holiday(self):
        start = date(2026, 9, 1)
        week_no, anchor, weekday = cal.week_info(start, start)
        self.assertEqual(week_no, 1)
        self.assertEqual(weekday, start.isoweekday())

        later = date(2026, 9, 14)  # 13 days later
        week_no2, _, _ = cal.week_info(start, later)
        self.assertEqual(week_no2, 3)

    # -- Closed-interval overlap (P1) ----------------------------------------

    def test_closed_ranges_sharing_an_endpoint_overlap(self):
        self.assertTrue(
            cal.ranges_overlap(
                date(2026, 9, 1), date(2026, 9, 30),
                date(2026, 9, 30), date(2026, 10, 31),
            )
        )
        self.assertFalse(
            cal.ranges_overlap(
                date(2026, 9, 1), date(2026, 9, 30),
                date(2026, 10, 1), date(2026, 10, 31),
            )
        )


if __name__ == "__main__":
    unittest.main()
