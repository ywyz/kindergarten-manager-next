"""Strict ConfirmationSnapshotV1 helper tests (A-owned, pure)."""

from __future__ import annotations

import copy
import unittest
from datetime import date, timedelta

from app.local import weekly_plan_content, weekly_plan_snapshot
from app.local.errors import LocalWeeklyInvalid

ANCHOR = date(2026, 9, 7)


def _header():
    return {
        "school_name": "测试幼儿园",
        "class_name": "中一班",
        "grade": "middle",
        "header_teacher_names": ["王老师"],
        "caregiver_name": "张阿姨",
    }


def _source_snapshot(
    *,
    term_start: str = "2026-09-07",
    term_end: str = "2026-10-30",
    states: list[str] | None = None,
    revision: str = "a" * 22,
):
    states = states or ["teaching", "teaching", "teaching", "teaching", "teaching", "rest", "rest"]
    days = []
    for offset in range(7):
        day = ANCHOR + timedelta(days=offset)
        state = states[offset]
        if state == "teaching":
            source_state = "no_plan"
        elif state == "rest":
            source_state = "none_required"
        else:
            source_state = "none_required"
        days.append(
            {
                "date": day.isoformat(),
                "day_state": state,
                "source_state": source_state,
                "source": None,
                "morning_groups": [],
                "post_group_groups": [],
            }
        )
    return {
        "profile_id": "p" * 22,
        "class_id": "c" * 22,
        "term_id": "t" * 22,
        "week_anchor_date": ANCHOR.isoformat(),
        "week_number": 1,
        "term_start": term_start,
        "term_end": term_end,
        "calendar_revision_id": revision,
        "config_version": 1,
        "game_context": None,
        "header": _header(),
        "source_context_hash": "f" * 64,
        "days": days,
    }


def _valid_snapshot(*, source=None, revision: str = "a" * 22):
    source = source or _source_snapshot(revision=revision)
    content = weekly_plan_content.new_content(source)
    facts = weekly_plan_content.build_facts(content, source)
    creation = {
        "week_anchor_date": ANCHOR.isoformat(),
        "week_number_snapshot": 1,
        "term_start": "2026-09-07",
        "term_end": "2026-10-30",
        "calendar_revision_id": "b" * 22,
    }
    return weekly_plan_snapshot.build_confirmation_snapshot(
        weekly_plan_id="w" * 22,
        profile_id=source["profile_id"],
        class_id=source["class_id"],
        term_id=source["term_id"],
        draft_id="d" * 22,
        draft_version=1,
        content_hash=weekly_plan_content.content_hash(content),
        header=source["header"],
        creation_context=creation,
        content=content,
        facts=facts,
    )


def _rehash(snapshot: dict) -> dict:
    snapshot = copy.deepcopy(snapshot)
    snapshot["content_hash"] = weekly_plan_content.content_hash(snapshot["content"])
    return snapshot


class SnapshotStrictnessTests(unittest.TestCase):
    def test_baseline_is_valid_and_refresh_basis_may_differ(self) -> None:
        snapshot = _valid_snapshot()
        weekly_plan_snapshot.validate_confirmation_snapshot(snapshot)
        self.assertNotEqual(
            snapshot["creation_context"]["calendar_revision_id"],
            snapshot["content"]["calendar_basis"]["calendar_revision_id"],
        )

    def test_schema_version_rejects_bool_and_float(self) -> None:
        for value in (True, 1.0):
            snapshot = _valid_snapshot()
            snapshot["schema_version"] = value
            with self.subTest(value=value):
                with self.assertRaises(LocalWeeklyInvalid):
                    weekly_plan_snapshot.validate_confirmation_snapshot(snapshot)

    def test_top_identity_must_match_manifest(self) -> None:
        for key in ("class_id", "term_id"):
            snapshot = _valid_snapshot()
            snapshot[key] = "x" * 22
            with self.subTest(key=key):
                with self.assertRaises(LocalWeeklyInvalid):
                    weekly_plan_snapshot.validate_confirmation_snapshot(snapshot)
        snapshot = _valid_snapshot()
        snapshot["header"]["class_name"] = "别的班"
        with self.assertRaises(LocalWeeklyInvalid):
            weekly_plan_snapshot.validate_confirmation_snapshot(snapshot)

    def test_creation_week_must_match_manifest(self) -> None:
        snapshot = _valid_snapshot()
        snapshot["creation_context"]["week_number_snapshot"] = 2
        with self.assertRaises(LocalWeeklyInvalid):
            weekly_plan_snapshot.validate_confirmation_snapshot(snapshot)

    def test_creation_term_must_intersect_fixed_week(self) -> None:
        snapshot = _valid_snapshot()
        snapshot["creation_context"]["term_start"] = "2026-11-01"
        snapshot["creation_context"]["term_end"] = "2026-11-30"
        with self.assertRaises(LocalWeeklyInvalid):
            weekly_plan_snapshot.validate_confirmation_snapshot(snapshot)

    def test_facts_items_must_be_structural_objects(self) -> None:
        for value in ([0], [{}], [{"code": "x"}]):
            snapshot = _valid_snapshot()
            snapshot["facts"]["missing"] = value
            with self.subTest(value=value):
                with self.assertRaises(LocalWeeklyInvalid):
                    weekly_plan_snapshot.validate_confirmation_snapshot(snapshot)

    def test_noncanonical_null_column_is_rejected_after_rehash(self) -> None:
        snapshot = _valid_snapshot()
        snapshot["content"]["weekly_columns"]["key_week_focus"] = None
        snapshot = _rehash(snapshot)
        with self.assertRaises(LocalWeeklyInvalid):
            weekly_plan_snapshot.validate_confirmation_snapshot(snapshot)

    def test_optional_term_name_and_reissue_fields_keep_old_snapshots_valid(self) -> None:
        snapshot = _valid_snapshot()
        baseline_hash = weekly_plan_snapshot.snapshot_hash(snapshot)
        weekly_plan_snapshot.validate_confirmation_snapshot(snapshot)
        snapshot["term_name"] = "新学期"
        snapshot["reissued_from_confirmation_id"] = "c" * 22
        weekly_plan_snapshot.validate_confirmation_snapshot(snapshot)
        self.assertNotEqual(
            weekly_plan_snapshot.snapshot_hash(snapshot), baseline_hash
        )
        for bad in ("", " 春季 ", "春\x00季", "名" * 81, 1):
            candidate = _valid_snapshot()
            candidate["term_name"] = bad
            with self.subTest(term_name=bad):
                with self.assertRaises(LocalWeeklyInvalid):
                    weekly_plan_snapshot.validate_confirmation_snapshot(
                        candidate
                    )
        missing_name = _valid_snapshot()
        missing_name["reissued_from_confirmation_id"] = "c" * 22
        with self.assertRaises(LocalWeeklyInvalid):
            weekly_plan_snapshot.validate_confirmation_snapshot(missing_name)
        unknown = _valid_snapshot()
        unknown["unknown_key"] = True
        with self.assertRaises(LocalWeeklyInvalid):
            weekly_plan_snapshot.validate_confirmation_snapshot(unknown)
        manifest = _export_manifest_for(snapshot)
        weekly_plan_snapshot.validate_export_manifest(manifest)
        self.assertEqual(
            manifest["items"][0]["term_name"], "新学期"
        )

    def test_zero_teaching_uses_saved_basis_term_intersection(self) -> None:
        source = _source_snapshot(
            term_start="2026-09-09",
            term_end="2026-09-11",
            states=["outside_term", "outside_term", "rest", "rest", "rest", "rest", "rest"],
            revision="c" * 22,
        )
        snapshot = _valid_snapshot(source=source)
        self.assertEqual(
            snapshot["date_range"], {"start": "2026-09-09", "end": "2026-09-11"}
        )
        weekly_plan_snapshot.validate_confirmation_snapshot(snapshot)

    def test_zero_teaching_falls_back_only_when_basis_is_disjoint(self) -> None:
        source = _source_snapshot(
            term_start="2026-11-01",
            term_end="2026-11-30",
            states=["outside_term"] * 7,
            revision="c" * 22,
        )
        snapshot = _valid_snapshot(source=source)
        self.assertEqual(
            snapshot["date_range"], {"start": "2026-09-07", "end": "2026-09-13"}
        )
        weekly_plan_snapshot.validate_confirmation_snapshot(snapshot)


def _export_manifest_for(snapshot, mode="single", requested=None):
    item = copy.deepcopy(snapshot)
    item["confirmation_id"] = "n" * 22
    item["confirmation_version"] = 1
    item["confirmation_hash"] = weekly_plan_snapshot.snapshot_hash(snapshot)
    selection = {
        "weekly_plan_id": snapshot["weekly_plan_id"],
        "confirmation_id": item["confirmation_id"],
        "confirmation_version": 1,
        "draft_id": snapshot["draft_id"],
        "draft_version": snapshot["draft_version"],
        "content_hash": snapshot["content_hash"],
        "confirmation_hash": item["confirmation_hash"],
        "week_anchor_date": snapshot["creation_context"]["week_anchor_date"],
        "week_number": snapshot["creation_context"]["week_number_snapshot"],
        "date_range": copy.deepcopy(snapshot["date_range"]),
    }
    missing = []
    for fact in snapshot["facts"]["missing"]:
        copied = copy.deepcopy(fact)
        copied["details"] = dict(copied.get("details") or {})
        copied["details"]["weekly_plan_id"] = snapshot["weekly_plan_id"]
        copied["details"]["confirmation_id"] = item["confirmation_id"]
        missing.append(copied)
    return {
        "schema_version": 1,
        "profile_id": snapshot["profile_id"],
        "mode": mode,
        "requested_range": copy.deepcopy(requested),
        "selection": [selection],
        "warnings_as_of": "2026-11-01T10:00:00+00:00",
        "missing": missing,
        "warnings": [],
        "items": [item],
    }


def _export_manifest():
    return _export_manifest_for(_valid_snapshot())


class ExportManifestStrictnessTests(unittest.TestCase):
    def test_valid_manifest_passes(self) -> None:
        weekly_plan_snapshot.validate_export_manifest(_export_manifest())

    def test_tampered_manifest_cases_are_rejected(self) -> None:
        def case(mutate):
            manifest = copy.deepcopy(_export_manifest())
            mutate(manifest)
            with self.assertRaises(LocalWeeklyInvalid):
                weekly_plan_snapshot.validate_export_manifest(manifest)

        case(lambda m: m["selection"][0].update(confirmation_id="unknown"))
        case(lambda m: m["items"][0].update(content="串正文"))
        case(lambda m: m["items"][0]["facts"].update(missing=[0]))
        case(lambda m: m.update(warnings_as_of=None))
        case(lambda m: m["selection"][0].update(week_number=999))
        case(lambda m: m["items"][0].update(unknown_key=True))
        case(lambda m: m.update(mode="range", requested_range={"start": "2026-12-01", "end": "2026-12-02"}))
        case(lambda m: m["selection"][0]["date_range"].update(start="2026-12-01", end="2026-12-02"))
        case(lambda m: m["missing"].append({"code": "x"}))
        case(lambda m: m.update(profile_id="other"))
        case(lambda m: m["selection"][0].update(confirmation_version=1.0))
        case(lambda m: m["selection"][0].update(draft_version=True))
        case(lambda m: m.update(mode="range", requested_range={"start": "2026-09-01", "end": "2026-09-30"}, selection=[], items=[], missing=[], warnings=[]))


class ExportManifestBoundedFixesTests(unittest.TestCase):
    def test_warning_origin_values_must_be_ids(self) -> None:
        for bad in ([], {}):
            manifest = _export_manifest()
            manifest["warnings"] = [
                {
                    "code": "probe_warning",
                    "field_path": "content.theme",
                    "old_ref": None,
                    "new_ref": None,
                    "details": {
                        "weekly_plan_id": bad,
                        "confirmation_id": "n" * 22,
                    },
                }
            ]
            with self.subTest(value=bad):
                with self.assertRaises(LocalWeeklyInvalid):
                    weekly_plan_snapshot.validate_export_manifest(manifest)

    def test_missing_aggregate_keeps_exact_json_types(self) -> None:
        snapshot = _valid_snapshot()
        snapshot["facts"]["missing"][0]["details"]["probe_version"] = 1
        manifest = _export_manifest_for(snapshot)
        weekly_plan_snapshot.validate_export_manifest(manifest)
        for bad in (True, 1.0):
            candidate = copy.deepcopy(manifest)
            candidate["missing"][0]["details"]["probe_version"] = bad
            with self.subTest(value=bad):
                with self.assertRaises(LocalWeeklyInvalid):
                    weekly_plan_snapshot.validate_export_manifest(candidate)

    def test_rest_only_range_is_rejected_but_single_allowed(self) -> None:
        source = _source_snapshot(
            states=["teaching", "rest", "rest", "rest", "rest", "rest", "rest"]
        )
        snapshot = _valid_snapshot(source=source)
        single = _export_manifest_for(snapshot)
        weekly_plan_snapshot.validate_export_manifest(single)
        rest_day = (ANCHOR + timedelta(days=1)).isoformat()
        with self.assertRaises(LocalWeeklyInvalid):
            weekly_plan_snapshot.validate_export_manifest(
                _export_manifest_for(
                    snapshot,
                    mode="range",
                    requested={"start": rest_day, "end": rest_day},
                )
            )

    def test_zero_teaching_single_allowed_range_rejected(self) -> None:
        source = _source_snapshot(
            states=["rest"] * 7,
            term_start="2026-09-09",
            term_end="2026-09-11",
        )
        snapshot = _valid_snapshot(source=source)
        weekly_plan_snapshot.validate_export_manifest(_export_manifest_for(snapshot))
        with self.assertRaises(LocalWeeklyInvalid):
            weekly_plan_snapshot.validate_export_manifest(
                _export_manifest_for(
                    snapshot,
                    mode="range",
                    requested={"start": "2026-09-09", "end": "2026-09-11"},
                )
            )
