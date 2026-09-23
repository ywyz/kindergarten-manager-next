"""No-DB Pydantic tests for I4 request/response schemas (extra=forbid)."""

import unittest
from datetime import datetime

from pydantic import ValidationError

from app.schemas import (
    WeeklyPlanConfirmIn,
    WeeklyPlanConfirmationListOut,
    WeeklyPlanConfirmationOut,
    WeeklyPlanConfirmedSummaryOut,
    WeeklyPlanCreateIn,
    WeeklyPlanDetailOut,
    WeeklyPlanDraftOut,
    WeeklyPlanListItemOut,
    WeeklyPlanListOut,
    WeeklyPlanPatchIn,
    WeeklyPlanRefreshIn,
)

_NOW = datetime(2026, 9, 23, 8, 0, 0)


def _valid_draft() -> dict:
    return {
        "id": "c1",
        "version": 2,
        "content": {"theme": "秋"},
        "audit": {"action": "save"},
        "editor_id": "tch1",
        "editor_role": "owner",
        "created_at": _NOW,
    }


def _valid_confirmed_summary() -> dict:
    return {
        "version": 1,
        "draft_version": 2,
        "confirmed_by": "tch1",
        "facts": {"missing": [], "stale_sources": []},
        "created_at": _NOW,
    }


def _valid_detail() -> dict:
    return {
        "id": "wp1",
        "class_id": "cls1",
        "term_id": "ter1",
        "week_number": 3,
        "creator_id": "tch1",
        "owner_id": "tch1",
        "school_name": "阳光园",
        "class_name": "中一",
        "grade": "中班",
        "header_teacher_names": ["甲老师"],
        "caregiver_name": "王五",
        "confirmation_status": "draft_ahead",
        "needs_confirm": True,
        "draft": _valid_draft(),
        "confirmed": _valid_confirmed_summary(),
        "missing": [{"kind": "empty_theme"}],
        "stale_sources": [],
        "projection_pending": True,
        "source_candidates": [],
        "can_edit": True,
        "can_confirm": True,
        "refreshed_sources": None,
        "created_at": _NOW,
        "updated_at": _NOW,
    }


def _valid_confirmation() -> dict:
    return {
        "id": "cf1",
        "weekly_plan_id": "wp1",
        "version": 1,
        "draft_version": 2,
        "content": {"theme": "秋"},
        "facts": {"missing": [], "stale_sources": [], "note": None},
        "confirmed_by": "tch1",
        "created_at": _NOW,
    }


class WeeklyPlanCreateInTests(unittest.TestCase):
    def test_minimal_payload_tracks_only_supplied_fields(self):
        data = WeeklyPlanCreateIn.model_validate(
            {"term_id": "ter1", "week_number": 3}
        )
        self.assertEqual(data.term_id, "ter1")
        self.assertEqual(data.week_number, 3)
        self.assertIsNone(data.theme)
        self.assertIsNone(data.class_id)
        self.assertEqual(data.model_fields_set, {"term_id", "week_number"})

    def test_required_fields_enforced(self):
        for payload in ({}, {"term_id": "ter1"}, {"week_number": 1}):
            with self.subTest(payload=payload):
                with self.assertRaises(ValidationError):
                    WeeklyPlanCreateIn.model_validate(payload)

    def test_extra_fields_rejected(self):
        for extra in ("bogus", "expected_draft_version", "owner_id"):
            with self.subTest(extra=extra):
                with self.assertRaises(ValidationError):
                    WeeklyPlanCreateIn.model_validate(
                        {"term_id": "ter1", "week_number": 1, extra: "x"}
                    )

    def test_week_number_strict_int_ge_1(self):
        for bad in (True, False, 1.0, "1", 0, -1):
            with self.subTest(bad=bad):
                with self.assertRaises(ValidationError):
                    WeeklyPlanCreateIn.model_validate(
                        {"term_id": "ter1", "week_number": bad}
                    )
        data = WeeklyPlanCreateIn.model_validate(
            {"term_id": "ter1", "week_number": 52}
        )
        self.assertEqual(data.week_number, 52)

    def test_class_id_presence_tracked_for_router_matrix(self):
        omitted = WeeklyPlanCreateIn.model_validate(
            {"term_id": "ter1", "week_number": 1}
        )
        explicit_null = WeeklyPlanCreateIn.model_validate(
            {"term_id": "ter1", "week_number": 1, "class_id": None}
        )
        with_value = WeeklyPlanCreateIn.model_validate(
            {"term_id": "ter1", "week_number": 1, "class_id": "cls1"}
        )
        self.assertNotIn("class_id", omitted.model_fields_set)
        self.assertIn("class_id", explicit_null.model_fields_set)
        self.assertIsNone(explicit_null.class_id)
        self.assertIn("class_id", with_value.model_fields_set)
        self.assertEqual(with_value.class_id, "cls1")

    def test_empty_theme_is_valid_not_422(self):
        data = WeeklyPlanCreateIn.model_validate(
            {"term_id": "ter1", "week_number": 1, "theme": ""}
        )
        self.assertEqual(data.theme, "")
        null_theme = WeeklyPlanCreateIn.model_validate(
            {"term_id": "ter1", "week_number": 1, "theme": None}
        )
        self.assertIn("theme", null_theme.model_fields_set)


class WeeklyPlanPatchInTests(unittest.TestCase):
    def test_expected_draft_version_required(self):
        with self.assertRaises(ValidationError):
            WeeklyPlanPatchIn.model_validate({"theme": "x"})

    def test_expected_draft_version_strict_int_ge_1(self):
        for bad in (True, False, 1.0, "1", 0, -3):
            with self.subTest(bad=bad):
                with self.assertRaises(ValidationError):
                    WeeklyPlanPatchIn.model_validate(
                        {"expected_draft_version": bad}
                    )
        data = WeeklyPlanPatchIn.model_validate({"expected_draft_version": 7})
        self.assertEqual(data.expected_draft_version, 7)

    def test_extra_fields_rejected(self):
        for extra in ("class_id", "source", "effective", "materials", "id"):
            with self.subTest(extra=extra):
                with self.assertRaises(ValidationError):
                    WeeklyPlanPatchIn.model_validate(
                        {"expected_draft_version": 1, extra: {}}
                    )

    def test_omitted_optionals_not_in_fields_set(self):
        data = WeeklyPlanPatchIn.model_validate({"expected_draft_version": 3})
        self.assertEqual(data.model_fields_set, {"expected_draft_version"})
        for field in (
            "theme",
            "deterministic_overrides",
            "outdoor_game_slots",
            "focus_area",
            "weekly_columns",
        ):
            self.assertNotIn(field, data.model_fields_set)

    def test_explicit_nulls_are_tracked(self):
        data = WeeklyPlanPatchIn.model_validate(
            {
                "expected_draft_version": 3,
                "theme": None,
                "focus_area": None,
                "outdoor_game_slots": None,
                "weekly_columns": None,
                "deterministic_overrides": None,
            }
        )
        for field in (
            "theme",
            "deterministic_overrides",
            "outdoor_game_slots",
            "focus_area",
            "weekly_columns",
        ):
            self.assertIn(field, data.model_fields_set)
            self.assertIsNone(getattr(data, field))

    def test_wrong_types_rejected(self):
        for field in (
            "deterministic_overrides",
            "outdoor_game_slots",
            "focus_area",
            "weekly_columns",
        ):
            with self.subTest(field=field):
                with self.assertRaises(ValidationError):
                    WeeklyPlanPatchIn.model_validate(
                        {"expected_draft_version": 1, field: "x"}
                    )
        with self.assertRaises(ValidationError):
            WeeklyPlanPatchIn.model_validate(
                {"expected_draft_version": 1, "theme": 1}
            )


class WeeklyPlanRefreshInTests(unittest.TestCase):
    def test_expected_required_and_strict(self):
        with self.assertRaises(ValidationError):
            WeeklyPlanRefreshIn.model_validate({})
        for bad in (True, 0, 1.0, "1"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValidationError):
                    WeeklyPlanRefreshIn.model_validate(
                        {"expected_draft_version": bad}
                    )
        WeeklyPlanRefreshIn.model_validate({"expected_draft_version": 2})

    def test_extra_fields_rejected(self):
        with self.assertRaises(ValidationError):
            WeeklyPlanRefreshIn.model_validate(
                {"expected_draft_version": 1, "theme": "x"}
            )


class WeeklyPlanConfirmInTests(unittest.TestCase):
    def _base(self, **kw) -> dict:
        payload = {
            "expected_draft_version": 1,
            "acknowledge_missing": True,
            "acknowledge_stale": True,
        }
        payload.update(kw)
        return payload

    def test_acks_required(self):
        with self.assertRaises(ValidationError):
            WeeklyPlanConfirmIn.model_validate({"expected_draft_version": 1})
        with self.assertRaises(ValidationError):
            WeeklyPlanConfirmIn.model_validate(
                {"expected_draft_version": 1, "acknowledge_missing": True}
            )

    def test_acks_strict_bool(self):
        for bad in (1, 0, "true", "false"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValidationError):
                    WeeklyPlanConfirmIn.model_validate(
                        self._base(acknowledge_missing=bad)
                    )

    def test_note_optional_and_nullable(self):
        omitted = WeeklyPlanConfirmIn.model_validate(self._base())
        self.assertNotIn("note", omitted.model_fields_set)
        explicit = WeeklyPlanConfirmIn.model_validate(
            self._base(note=None)
        )
        self.assertIn("note", explicit.model_fields_set)
        self.assertIsNone(explicit.note)
        with_note = WeeklyPlanConfirmIn.model_validate(
            self._base(note="确认说明")
        )
        self.assertEqual(with_note.note, "确认说明")

    def test_extra_fields_rejected(self):
        for extra in ("facts", "class_id", "missing", "stale_sources"):
            with self.subTest(extra=extra):
                with self.assertRaises(ValidationError):
                    WeeklyPlanConfirmIn.model_validate(
                        self._base(**{extra: None})
                    )


class WeeklyPlanDetailOutTests(unittest.TestCase):
    def test_valid_payload_roundtrips(self):
        out = WeeklyPlanDetailOut.model_validate(_valid_detail())
        self.assertEqual(out.confirmation_status, "draft_ahead")
        self.assertTrue(out.can_confirm)
        self.assertIsNone(out.refreshed_sources)
        self.assertEqual(out.header_teacher_names, ["甲老师"])
        self.assertEqual(out.draft.audit, {"action": "save"})

    def test_never_confirmed_with_null_confirmed(self):
        payload = _valid_detail()
        payload["confirmed"] = None
        payload["confirmation_status"] = "never_confirmed"
        out = WeeklyPlanDetailOut.model_validate(payload)
        self.assertIsNone(out.confirmed)

    def test_invalid_confirmation_status_rejected(self):
        payload = _valid_detail()
        payload["confirmation_status"] = "confirmed"
        with self.assertRaises(ValidationError):
            WeeklyPlanDetailOut.model_validate(payload)

    def test_unknown_top_level_field_rejected(self):
        payload = _valid_detail()
        payload["deleted_at"] = None
        with self.assertRaises(ValidationError):
            WeeklyPlanDetailOut.model_validate(payload)

    def test_missing_required_section_rejected(self):
        payload = _valid_detail()
        del payload["source_candidates"]
        with self.assertRaises(ValidationError):
            WeeklyPlanDetailOut.model_validate(payload)
        payload = _valid_detail()
        del payload["header_teacher_names"]
        with self.assertRaises(ValidationError):
            WeeklyPlanDetailOut.model_validate(payload)

    def test_audit_null_allowed(self):
        payload = _valid_detail()
        payload["draft"] = dict(payload["draft"], audit=None)
        WeeklyPlanDetailOut.model_validate(payload)


class WeeklyPlanListSchemasTests(unittest.TestCase):
    def _item(self) -> dict:
        return {
            "id": "wp1",
            "term_id": "ter1",
            "week_number": 3,
            "creator_id": "tch1",
            "owner_id": "tch1",
            "draft_version": 2,
            "confirmed_version": 1,
            "needs_confirm": True,
            "updated_at": _NOW,
        }

    def test_list_roundtrip_with_null_confirmed_version(self):
        item = self._item()
        item["confirmed_version"] = None
        out = WeeklyPlanListOut.model_validate(
            {"items": [item], "total": 1, "offset": 0, "limit": 20}
        )
        self.assertEqual(out.total, 1)
        self.assertIsNone(out.items[0].confirmed_version)

    def test_list_item_rejects_extra_and_deleted_fields(self):
        for extra in ("deleted_at", "class_name", "status"):
            with self.subTest(extra=extra):
                item = self._item()
                item[extra] = None
                with self.assertRaises(ValidationError):
                    WeeklyPlanListItemOut.model_validate(item)

    def test_list_item_requires_all_fields(self):
        item = self._item()
        del item["needs_confirm"]
        with self.assertRaises(ValidationError):
            WeeklyPlanListItemOut.model_validate(item)


class WeeklyPlanConfirmationSchemasTests(unittest.TestCase):
    def test_confirmation_roundtrip(self):
        out = WeeklyPlanConfirmationOut.model_validate(_valid_confirmation())
        self.assertEqual(out.version, 1)
        self.assertEqual(out.content, {"theme": "秋"})

    def test_confirmation_rejects_extra_and_missing(self):
        payload = _valid_confirmation()
        payload["editor_role"] = "owner"
        with self.assertRaises(ValidationError):
            WeeklyPlanConfirmationOut.model_validate(payload)
        payload = _valid_confirmation()
        del payload["facts"]
        with self.assertRaises(ValidationError):
            WeeklyPlanConfirmationOut.model_validate(payload)

    def test_history_list_roundtrip_and_extra_rejected(self):
        summary = _valid_confirmed_summary()
        out = WeeklyPlanConfirmationListOut.model_validate(
            {"items": [summary], "total": 1}
        )
        self.assertEqual(out.total, 1)
        WeeklyPlanConfirmedSummaryOut.model_validate(summary)
        with self.assertRaises(ValidationError):
            WeeklyPlanConfirmationListOut.model_validate(
                {"items": [summary], "total": 1, "offset": 0}
            )

    def test_draft_out_rejects_extra(self):
        draft = _valid_draft()
        draft["deleted_at"] = None
        with self.assertRaises(ValidationError):
            WeeklyPlanDraftOut.model_validate(draft)


if __name__ == "__main__":
    unittest.main()
