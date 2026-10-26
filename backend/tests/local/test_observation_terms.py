"""E04 date/term attribution tests against a real synthetic SQLite database."""

from __future__ import annotations

import sqlite3
import unittest
from datetime import date

from sqlalchemy import select

from app.local import profile_service
from app.local.models import LocalCalendarRevision, LocalProfile, LocalTerm
from app.local.normalize import normalize_initialization
from app.local.observation_terms import (
    apply_term_resolution,
    get_term_snapshot,
    resolve_edit,
    resolve_new,
    snapshot_from_history,
)
from app.local.observation_validation import ObservationValidationError
from tests.local.support import LocalTestCase, initialize_body


class ObservationTermsTests(LocalTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.runtime = self.make_runtime()
        self.session = self.runtime.session()
        profile_service.initialize(
            self.session, normalize_initialization(**initialize_body())
        )
        self.session.commit()
        self.profile = self.session.scalars(select(LocalProfile)).one()
        self.term = self.session.scalars(select(LocalTerm)).one()
        self.term_snapshot = get_term_snapshot(self.session, self.term.id)

    def tearDown(self) -> None:
        self.session.close()
        super().tearDown()

    def _add_overlapping_term(self) -> LocalTerm:
        # The revision's term FK is immediate while the term's pointer is
        # deferred; build the synthetic pair with FK enforcement off, exactly
        # as a reviewed fixture would, then reopen a normal session.
        self.session.close()
        connection = sqlite3.connect(str(self.runtime.db_path))
        try:
            connection.execute("PRAGMA foreign_keys=OFF")
            connection.execute(
                "INSERT INTO local_terms "
                "(id,name,start_date,end_date,current_calendar_revision_id,"
                "created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                (
                    "term-overlap-0000000000000001",
                    "重叠学期",
                    "2026-09-15",
                    "2026-10-15",
                    "rev-overlap-0000000000000001",
                    "2026-10-20 00:00:00",
                    "2026-10-20 00:00:00",
                ),
            )
            connection.execute(
                "INSERT INTO local_calendar_revisions "
                "(id,term_id,revision_no,library_version,created_by,created_at) "
                "VALUES (?,?,?,?,?,?)",
                (
                    "rev-overlap-0000000000000001",
                    "term-overlap-0000000000000001",
                    1,
                    "test",
                    self.profile.id,
                    "2026-10-20 00:00:00",
                ),
            )
            connection.commit()
        finally:
            connection.close()
        self.session = self.runtime.session()
        return self.session.get(LocalTerm, "term-overlap-0000000000000001")

    def test_new_defaults_today_unique_match_and_unassigned(self):
        assigned = resolve_new(self.session, observation_date="2026-09-10")
        self.assertEqual(assigned.status, "assigned")
        self.assertEqual(assigned.term_id, self.term.id)

        unassigned = resolve_new(self.session, observation_date="2026-10-10")
        self.assertEqual(unassigned.status, "unassigned")
        self.assertIsNone(unassigned.term_id)

        today = resolve_new(self.session, clock=lambda: date(2026, 9, 10))
        self.assertEqual(today.status, "assigned")
        explicit_none = resolve_new(self.session, observation_date=None)
        self.assertEqual(explicit_none.status, "unassigned")
        self.assertIsNone(explicit_none.term_id)

    def test_unchanged_date_does_not_reopen_attribution(self):
        # Explicit keep-current outside the range is stable on a later edit.
        first = resolve_edit(
            self.session,
            current_term_id=self.term.id,
            current_snapshot=self.term_snapshot.as_json(),
            new_date="2026-10-10",
            decision="keep_current",
        )
        self.assertEqual(first.status, "keep_current")
        again = resolve_edit(
            self.session,
            current_term_id=self.term.id,
            current_snapshot=first.snapshot.as_json(),
            new_date="2026-10-10",
            previous_date=date(2026, 10, 10),
        )
        self.assertEqual(again.status, "keep_current")
        self.assertFalse(again.requires_decision)
        self.assertTrue(again.unchanged)

        # An unassigned record whose date did not change stays unassigned even
        # if a term is added later that would match it.
        unassigned = resolve_edit(
            self.session,
            current_term_id=None,
            new_date="2026-10-10",
            previous_date=date(2026, 10, 10),
        )
        self.assertEqual(unassigned.status, "unassigned")
        self.assertFalse(unassigned.requires_decision)

    def test_missing_current_snapshot_is_explicit_not_silently_filled(self):
        result = resolve_edit(
            self.session,
            current_term_id=self.term.id,
            current_snapshot=None,
            new_date="2026-09-10",
            previous_date=date(2026, 9, 10),
        )
        self.assertTrue(result.requires_decision)
        self.assertIn("current_snapshot_missing", result.warnings)
        keep = resolve_edit(
            self.session,
            current_term_id=self.term.id,
            current_snapshot=None,
            new_date="2026-09-10",
            decision="keep_current",
        )
        self.assertTrue(keep.requires_decision)

    def test_multiple_matches_require_explicit_selection(self):
        self._add_overlapping_term()
        result = resolve_new(self.session, observation_date="2026-09-20")
        self.assertEqual(result.status, "selection_required")
        self.assertTrue(result.requires_decision)
        self.assertEqual(len(result.options), 2)

    def test_clearing_date_keeps_existing_term_and_snapshot(self):
        result = resolve_edit(
            self.session,
            current_term_id=self.term.id,
            current_snapshot=self.term_snapshot.as_json(),
            new_date=None,
            previous_date=date(2026, 9, 10),
        )
        self.assertEqual(result.status, "keep_current")
        self.assertEqual(result.term_id, self.term.id)
        self.assertEqual(result.snapshot, self.term_snapshot)
        self.assertFalse(result.requires_decision)

    def test_empty_date_can_explicitly_select_existing_term(self):
        result = resolve_edit(
            self.session,
            current_term_id=None,
            new_date=None,
            decision="assign_selected",
            selected_term_id=self.term.id,
        )
        self.assertEqual(result.status, "assigned")
        self.assertEqual(result.term_id, self.term.id)

    def test_cross_term_change_requires_decision_and_options(self):
        result = resolve_edit(
            self.session,
            current_term_id=self.term.id,
            current_snapshot=self.term_snapshot.as_json(),
            new_date="2026-10-10",
            previous_date=date(2026, 9, 10),
        )
        self.assertEqual(result.status, "selection_required")
        self.assertTrue(result.requires_decision)
        self.assertEqual(result.warnings, ("cross_term_change",))
        self.assertIn(self.term.id, {item.term_id for item in result.options})

    def test_explicit_decisions_keep_current_select_existing_or_unassign(self):
        keep = resolve_edit(
            self.session,
            current_term_id=self.term.id,
            current_snapshot=self.term_snapshot.as_json(),
            new_date="2026-10-10",
            decision="keep_current",
        )
        self.assertEqual(keep.status, "keep_current")
        self.assertIn("date_outside_current_term", keep.warnings)

        other = self._add_overlapping_term()
        selected = resolve_edit(
            self.session,
            current_term_id=self.term.id,
            current_snapshot=self.term_snapshot.as_json(),
            new_date="2026-10-10",
            decision="assign_selected",
            selected_term_id=other.id,
        )
        self.assertEqual(selected.status, "assigned")
        self.assertEqual(selected.term_id, other.id)
        self.assertNotIn("date_outside_selected_term", selected.warnings)

        unassigned = resolve_edit(
            self.session,
            current_term_id=self.term.id,
            current_snapshot=self.term_snapshot.as_json(),
            new_date="2026-10-10",
            decision="unassigned",
        )
        self.assertEqual(unassigned.status, "unassigned")
        self.assertIsNone(unassigned.term_id)

    def test_cancel_preserves_payload_and_writes_nothing(self):
        payload = {"term_id": self.term.id, "term_snapshot": self.term_snapshot.as_json()}
        result = resolve_edit(
            self.session,
            current_term_id=self.term.id,
            current_snapshot=self.term_snapshot.as_json(),
            new_date="2026-10-10",
            decision="cancel",
        )
        self.assertTrue(result.cancelled)
        self.assertTrue(result.unchanged)
        self.assertEqual(apply_term_resolution(payload, result), payload)

    def test_history_snapshot_is_preserved_only_when_explicit(self):
        history = self.term_snapshot.as_json()
        result = resolve_edit(
            self.session,
            current_term_id=self.term.id,
            current_snapshot=self.term_snapshot.as_json(),
            new_date="2026-10-10",
            decision="keep_history",
            history_snapshot=history,
        )
        self.assertEqual(result.status, "assigned")
        self.assertEqual(result.snapshot, self.term_snapshot)

    def test_forged_snapshot_term_id_is_rejected(self):
        forged = dict(self.term_snapshot.as_json(), term_id="other-term")
        with self.assertRaises(ObservationValidationError):
            resolve_edit(
                self.session,
                current_term_id=self.term.id,
                current_snapshot=forged,
                new_date="2026-09-10",
            )

    def test_term_range_shrink_does_not_rewrite_old_snapshot(self):
        old = self.term_snapshot
        self.term.end_date = date(2026, 9, 5)
        self.session.commit()
        result = resolve_edit(
            self.session,
            current_term_id=self.term.id,
            current_snapshot=old.as_json(),
            new_date="2026-09-20",
            previous_date=date(2026, 9, 10),
        )
        self.assertEqual(result.status, "keep_current")
        self.assertEqual(result.snapshot, old)
        self.assertNotIn("cross_term_change", result.warnings)

    def test_history_snapshot_validation(self):
        self.assertEqual(
            snapshot_from_history(
                {"term_id": self.term.id, "term_snapshot": self.term_snapshot.as_json()}
            ),
            self.term_snapshot,
        )
        with self.assertRaises(ObservationValidationError):
            snapshot_from_history(
                {
                    "term_id": "different",
                    "term_snapshot": self.term_snapshot.as_json(),
                }
            )


if __name__ == "__main__":
    unittest.main()
