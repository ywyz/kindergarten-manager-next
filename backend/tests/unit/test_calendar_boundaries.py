"""Targeted no-DB boundary tests for calendar builders.

These exercise the pure builders with lightweight fakes; no database or
calendar library is required.
"""

import unittest
from datetime import date

from app.models import CalendarDay, SchoolSettings, Term
from app.services import calendar_service
from app.services.config_builders_calendar import build_calendar_override
from app.services.config_builders_reimport import build_calendar_reimport
from app.services.config_state import ReadState


class FakeTerm(Term):
    def __init__(self, start, end):
        self.id = "term1"
        self.name = "t"
        self.start_date = start
        self.end_date = end
        self.version = 1
        self.current_calendar_revision_id = "rev1"
        self.schedule_version = 1


def _day(d, base, override=None, reason=None):
    return CalendarDay(
        date=d,
        revision_id="rev1",
        base_state=base,
        base_library_version="stub",
        override_state=override,
        override_reason=reason,
        effective_state=override or base,
    )


def _state(term, day_map):
    school = SchoolSettings(
        id="singleton",
        school_name="s",
        version=1,
        schedule_version=1,
        plans_started_at=None,
    )
    return ReadState(
        school=school,
        classes_by_id={},
        classes_by_name={},
        terms_by_id={"term1": term},
        day_maps={"term1": day_map},
        all_members=(),
        class_members={},
        new_class_id="nc",
        new_term_id="nt",
    )


def _base_proposal(entries):
    return {
        "target_id": "term1",
        "expected_term_version": 1,
        "expected_calendar_revision_id": "rev1",
        "expected_schedule_version": 1,
        "dates": entries,
    }


class CalendarBoundaryTests(unittest.TestCase):
    def test_same_as_default_explicit_exception_is_a_change(self):
        d = date(2026, 9, 1)
        term = FakeTerm(d, d)
        state = _state(term, {d: _day(d, "teaching")})
        proposal = _base_proposal(
            [{"date": d.isoformat(), "state": "teaching", "reason": "园所统一"}]
        )
        preview = build_calendar_override(state, proposal)
        fields = {c["field"].split(":")[2] for c in preview.changes}
        self.assertIn("override_state", fields)
        self.assertIn("override_reason", fields)
        self.assertEqual(preview.impact["override_added"], 1)
        self.assertTrue(all("source" in c and "week_label" in c for c in preview.changes))

    def test_reason_only_edit_is_a_change(self):
        d = date(2026, 9, 1)
        term = FakeTerm(d, d)
        state = _state(term, {d: _day(d, "non_teaching", "teaching", "旧原因")})
        proposal = _base_proposal(
            [{"date": d.isoformat(), "state": "teaching", "reason": "新原因"}]
        )
        preview = build_calendar_override(state, proposal)
        fields = {c["field"].split(":")[2] for c in preview.changes}
        self.assertEqual(fields, {"override_reason"})

    def test_same_effective_removal_is_a_change(self):
        d = date(2026, 9, 1)
        term = FakeTerm(d, d)
        state = _state(term, {d: _day(d, "teaching", "teaching", "原因")})
        proposal = _base_proposal([{"date": d.isoformat(), "state": None}])
        preview = build_calendar_override(state, proposal)
        fields = {c["field"].split(":")[2] for c in preview.changes}
        self.assertIn("override_state", fields)
        self.assertIn("override_reason", fields)
        self.assertEqual(preview.impact["override_removed"], 1)

    def test_override_full_days_preserves_non_touched_date(self):
        d1 = date(2026, 9, 1)
        d2 = date(2026, 9, 2)
        term = FakeTerm(d1, d2)
        state = _state(
            term,
            {d1: _day(d1, "teaching"), d2: _day(d2, "non_teaching")},
        )
        # Override only d1; d2 must survive unchanged in full_days.
        proposal = _base_proposal(
            [{"date": d1.isoformat(), "state": "non_teaching", "reason": "园所活动"}]
        )
        preview = build_calendar_override(state, proposal)
        full = preview.proposal["full_days"]
        self.assertEqual(len(full), 2)
        by_date = {p["date"]: p for p in full}
        self.assertEqual(by_date[d2.isoformat()]["effective_state"], "non_teaching")
        self.assertIsNone(by_date[d2.isoformat()]["override_state"])
        self.assertEqual(by_date[d1.isoformat()]["override_reason"], "园所活动")

    def test_reimport_reports_default_change_masked_by_exception(self):
        d = date(2026, 9, 1)
        term = FakeTerm(d, d)
        # Old default was non_teaching; an exception forced teaching.
        state = _state(
            term, {d: _day(d, "non_teaching", "teaching", "园所例外")}
        )

        provider = type(
            "P",
            (),
            {
                "version": "stub2",
                "is_holiday": staticmethod(lambda x: False),
                "is_workday": staticmethod(lambda x: True),
            },
        )
        calendar_service.register_provider(provider, "stub2")
        try:
            proposal = _base_proposal([])
            preview = build_calendar_reimport(state, proposal)
        finally:
            calendar_service.reset_provider()

        base_changes = [c for c in preview.changes if c["field"].endswith("base_state")]
        self.assertEqual(len(base_changes), 1)
        self.assertTrue(base_changes[0]["masked_by_exception"])
        self.assertEqual(preview.impact["masked_default_changes"], 1)
        # Effective stays teaching, but the day is still reported as changed.
        self.assertEqual(preview.impact["changed_day_count"], 1)


if __name__ == "__main__":
    unittest.main()
