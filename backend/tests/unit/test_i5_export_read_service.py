"""No-DB unit tests for the I5 Word export read/selection service.

Uses a stub Session (no MySQL, no SQLite, no HTTP) to exercise daily range
selection/pinning/missing facts, the section 11.8 option B ack binding, weekly
range intersection / cross-term ordering / identity dedup, explicit vs current
confirmed version selection and the section 3.6 warning judgement.
"""

import unittest
from datetime import date, datetime
from types import SimpleNamespace
from unittest import mock

from app.models import (
    DailyPlan,
    DailyPlanContent,
    Term,
    WeeklyPlan,
    WeeklyPlanConfirmedContent,
)
from app.services import export_read_service as export
from app.services import word_export_mapping as mapping
from app.services.daily_plan_content import prepare_content
from app.services.weekly_plan_sync_service import WeekPlanEntry

_NOW = datetime(2026, 9, 23, 8, 0, 0)


def _complete_payload():
    """A fully-filled daily content payload (before I3 parser validation)."""
    return {
        "morning_games": [
            {
                "group_kind": "collective",
                "games": [{"name": "集体游戏"}],
                "focus_guidance": "重点",
                "shared_objectives": "目标",
                "guidance_points": "要点",
            },
            {
                "group_kind": "free_choice",
                "games": [{"name": "自主游戏"}],
                "focus_guidance": "重点",
                "shared_objectives": "目标",
                "guidance_points": "要点",
            },
        ],
        "morning_talk": {"topic": "话题", "questions": "问题"},
        "group_activity": {
            "theme": "主题",
            "objectives": "目标",
            "preparation": "准备",
            "key_points": "重点",
            "difficult_points": "难点",
            "process": "过程",
        },
        "post_group_games": [
            {
                "context_kind": "area",
                "area": "建构区",
                "games": [{"name": "区域游戏"}],
                "focus_guidance": "重点",
                "objectives": "目标",
                "guidance": "指导",
                "support_strategy": "支持",
            }
        ],
        "afternoon_outdoor": {
            "area": "操场",
            "games": [{"name": "户外游戏"}],
            "observation_focus": "观察",
            "objectives": "目标",
            "guidance": "指导",
            "support_strategy": "支持",
        },
        "reflection": "反思",
    }


def _parsed(payload=None):
    """Run the payload through the real I3 parser (assigns group/game ids)."""
    return prepare_content(_complete_payload() if payload is None else payload)


def _complete_content():
    return _parsed()


class _Result:
    def __init__(self, rows):
        self._rows = list(rows)

    def all(self):
        return list(self._rows)

    def one_or_none(self):
        return self._rows[0] if self._rows else None


class _StubSession:
    """Read-only Session stub: ``get`` map + queued ``scalars`` results."""

    def __init__(self, *, get_map=None, scalars_queue=None):
        self.get_map = dict(get_map or {})
        self.scalars_queue = list(scalars_queue or [])

    def get(self, entity, key):
        return self.get_map.get((entity.__name__, key))

    def scalars(self, stmt):
        rows = self.scalars_queue.pop(0) if self.scalars_queue else []
        return _Result(rows)

    def scalar(self, stmt):
        return 0

    def begin(self):
        raise AssertionError("export read must not open a transaction")

    def commit(self):
        raise AssertionError("export read must not commit")

    def rollback(self):
        raise AssertionError("export read must not roll back")

    def flush(self):
        raise AssertionError("export read must not flush")

    def add(self, obj):
        raise AssertionError("export read must not write")


def _dplan(*, plan_id="dp1", plan_date=date(2026, 9, 1), content_id="c1", version=1):
    plan = DailyPlan()
    plan.id = plan_id
    plan.class_id = "cls1"
    plan.term_id = "ter1"
    plan.plan_date = plan_date
    plan.creator_id = "tch1"
    plan.week_number = 1
    plan.weekday = 2
    plan.current_content_id = content_id
    plan.current_content_version = version
    plan.creator_display_name = "甲老师"
    plan.school_name = "阳光园"
    plan.class_name = "中一"
    plan.grade = "中班"
    plan.deleted_at = None
    return plan


def _dcontent(*, plan_id="dp1", content_id="c1", version=1, adopted=None, baseline=None):
    row = DailyPlanContent()
    row.id = content_id
    row.daily_plan_id = plan_id
    row.version = version
    row.raw_lesson_plan = None
    row.split_baseline = baseline
    row.adopted_content = adopted if adopted is not None else {}
    row.editor_id = "tch1"
    row.created_at = _NOW
    return row


def _drecord(*, plan_id="dp1", content_id="c1", content_version=1, adopted=None, baseline=None):
    return export.DailyPlanExportRecord(
        plan_id=plan_id,
        class_id="cls1",
        term_id="ter1",
        plan_date=date(2026, 9, 1),
        week_number=1,
        weekday=2,
        creator_id="tch1",
        creator_display_name="甲老师",
        school_name="阳光园",
        class_name="中一",
        grade="中班",
        content_id=content_id,
        content_version=content_version,
        adopted_content=adopted if adopted is not None else {},
        split_baseline=baseline,
    )


def _term(*, term_id="ter1", start=date(2026, 9, 1), end=date(2026, 9, 30)):
    term = Term()
    term.id = term_id
    term.name = "秋"
    term.start_date = start
    term.end_date = end
    term.current_calendar_revision_id = "rev1"
    return term


def _wplan(
    *,
    plan_id="wp1",
    term_id="ter1",
    week_number=1,
    draft_version=2,
    confirmed_id="cf1",
    confirmed_version=1,
):
    plan = WeeklyPlan()
    plan.id = plan_id
    plan.class_id = "cls1"
    plan.term_id = term_id
    plan.week_number = week_number
    plan.creator_id = "tch1"
    plan.owner_id = "tch1"
    plan.current_draft_content_id = "d2"
    plan.current_draft_version = draft_version
    plan.current_confirmed_content_id = confirmed_id
    plan.current_confirmed_content_version = confirmed_version
    plan.school_name = "阳光园"
    plan.class_name = "中一"
    plan.grade = "中班"
    plan.header_teacher_names = ["甲老师"]
    plan.caregiver_name = "王五"
    plan.deleted_at = None
    return plan


def _wconfirmed(
    *,
    content_id="cf1",
    version=1,
    draft_version=2,
    content=None,
    facts=None,
):
    row = WeeklyPlanConfirmedContent()
    row.id = content_id
    row.weekly_plan_id = "wp1"
    row.version = version
    row.draft_version = draft_version
    row.content = content if content is not None else {}
    row.facts = facts if facts is not None else {"missing": [], "stale_sources": []}
    row.confirmed_by = "tch1"
    row.created_at = _NOW
    return row


def _empty_content(theme="主题"):
    return {
        "theme": theme,
        "deterministic": [],
        "outdoor_game_slots": {key: None for key in mapping.OUTDOOR_SLOT_KEYS},
        "focus_area": None,
        "weekly_columns": {key: "内容" for key in mapping.WEEKLY_COLUMN_KEYS},
        "materials": None,
    }


class DailySelectionTests(unittest.TestCase):
    def test_range_selection_pins_version_and_sorts(self):
        plans = [
            _dplan(plan_id="dp2", plan_date=date(2026, 9, 2), content_id="c2", version=3),
            _dplan(plan_id="dp1", plan_date=date(2026, 9, 1), content_id="c1", version=1),
        ]
        contents = [
            _dcontent(plan_id="dp2", content_id="c2", version=3, adopted={"reflection": "b"}),
            _dcontent(plan_id="dp1", content_id="c1", version=1, adopted={"reflection": "a"}),
        ]
        db = _StubSession(scalars_queue=[plans, contents])
        records = export.select_daily_plans(
            db, class_id="cls1", from_date=date(2026, 9, 1), to_date=date(2026, 9, 3)
        )
        self.assertEqual([r.plan_id for r in records], ["dp1", "dp2"])
        self.assertEqual(records[0].content_version, 1)
        self.assertEqual(records[0].content_id, "c1")
        self.assertEqual(records[1].content_version, 3)

    def test_strict_range_rejects_reversed_dates(self):
        db = _StubSession()
        with self.assertRaises(export.ExportReadValidationError):
            export.select_daily_plans(
                db,
                class_id="cls1",
                from_date=date(2026, 9, 3),
                to_date=date(2026, 9, 1),
            )

    def test_inconsistent_pointer_is_data_error(self):
        db = _StubSession(
            scalars_queue=[
                [_dplan(plan_id="dp1", content_id="c1", version=2)],
                [_dcontent(plan_id="dp1", content_id="c1", version=1)],
            ]
        )
        with self.assertRaises(export.ExportReadDataError):
            export.select_daily_plans(
                db,
                class_id="cls1",
                from_date=date(2026, 9, 1),
                to_date=date(2026, 9, 3),
            )

    def test_no_split_baseline_warning(self):
        db = _StubSession(
            scalars_queue=[
                [_dplan(plan_id="dp1", content_id="c1", version=1)],
                [_dcontent(plan_id="dp1", content_id="c1", version=1, baseline=None)],
            ]
        )
        records = export.select_daily_plans(
            db, class_id="cls1", from_date=date(2026, 9, 1), to_date=date(2026, 9, 3)
        )
        self.assertEqual(records[0].warnings, ({"code": "no_split_baseline"},))

    def test_missing_facts_complete_parsed_content_is_empty(self):
        # The fixture goes through the real I3 parser and every fixed template
        # column is filled -> no missing facts.
        self.assertEqual(export.collect_daily_missing_facts(_complete_content()), [])

    def test_missing_facts_empty_content_reports_every_column(self):
        facts = export.collect_daily_missing_facts({})
        fields = {fact["field"] for fact in facts}
        self.assertIn("morning_games.collective", fields)
        self.assertIn("morning_games.free_choice", fields)
        self.assertIn("morning_talk.topic", fields)
        self.assertIn("group_activity.theme", fields)
        self.assertIn("group_activity.objectives", fields)
        self.assertIn("post_group_games", fields)
        self.assertIn("afternoon_outdoor", fields)
        self.assertIn("reflection", fields)

    def test_container_present_but_games_empty_is_reported(self):
        payload = _complete_payload()
        payload["morning_games"][0]["games"] = []
        payload["post_group_games"][0]["games"] = []
        payload["afternoon_outdoor"]["games"] = []
        content = _parsed(payload)
        facts = export.collect_daily_missing_facts(content)
        fields = {fact["field"] for fact in facts}
        self.assertEqual(
            fields,
            {
                "morning_games[0].games",
                "post_group_games[0].games",
                "afternoon_outdoor.games",
            },
        )
        # Stable locators point at the actual group.
        by_field = {fact["field"]: fact for fact in facts}
        self.assertEqual(
            by_field["morning_games[0].games"]["group_id"],
            content["morning_games"][0]["group_id"],
        )
        self.assertEqual(
            by_field["post_group_games[0].games"]["group_id"],
            content["post_group_games"][0]["group_id"],
        )

    def test_blank_game_name_is_reported(self):
        payload = _complete_payload()
        payload["morning_games"][0]["games"] = [{"name": "   "}]
        content = _parsed(payload)
        facts = export.collect_daily_missing_facts(content)
        self.assertEqual(len(facts), 1)
        fact = facts[0]
        self.assertEqual(fact["field"], "morning_games[0].games[0].name")
        self.assertEqual(fact["game_index"], 0)
        self.assertEqual(
            fact["game_id"], content["morning_games"][0]["games"][0]["game_id"]
        )
        self.assertEqual(
            fact["group_id"], content["morning_games"][0]["group_id"]
        )

    def test_group_level_objectives_and_guidance_reported(self):
        payload = _complete_payload()
        collective = payload["morning_games"][0]
        collective["focus_guidance"] = ""
        collective["shared_objectives"] = "  "
        del collective["guidance_points"]
        content = _parsed(payload)
        facts = export.collect_daily_missing_facts(content)
        fields = {(fact["field"], fact.get("group_id")) for fact in facts}
        group_id = content["morning_games"][0]["group_id"]
        self.assertEqual(
            fields,
            {
                ("morning_games[0].focus_guidance", group_id),
                ("morning_games[0].shared_objectives", group_id),
                ("morning_games[0].guidance_points", group_id),
            },
        )

    def test_missing_morning_kind_reported(self):
        payload = _complete_payload()
        payload["morning_games"] = [payload["morning_games"][0]]  # no free_choice
        content = _parsed(payload)
        facts = export.collect_daily_missing_facts(content)
        self.assertEqual(
            [fact["field"] for fact in facts], ["morning_games.free_choice"]
        )

    def test_inapplicable_post_group_branches_not_reported(self):
        # Only an 'area' group exists: outdoor/special_room must not be
        # demanded, and the complete content yields no facts at all.
        payload = _complete_payload()
        content = _parsed(payload)
        facts = export.collect_daily_missing_facts(content)
        self.assertEqual(facts, [])
        self.assertFalse(
            any("outdoor" in fact["field"] for fact in facts)
        )
        self.assertFalse(
            any("special_room" in fact["field"] for fact in facts)
        )

    def test_multiple_same_context_groups_keep_all_facts(self):
        payload = _complete_payload()
        second_area = dict(payload["post_group_games"][0])
        second_area["games"] = []
        payload["post_group_games"][0]["games"] = []
        payload["post_group_games"].append(second_area)
        content = _parsed(payload)
        facts = export.collect_daily_missing_facts(content)
        self.assertEqual(
            [fact["field"] for fact in facts],
            ["post_group_games[0].games", "post_group_games[1].games"],
        )
        group_ids = [fact["group_id"] for fact in facts]
        self.assertEqual(len(set(group_ids)), 2)

    def test_unparsed_partial_group_is_not_treated_as_complete(self):
        # Old-style bogus "complete" fixture: only group_kind, no games/text.
        facts = export.collect_daily_missing_facts(
            {
                "morning_games": [{"group_kind": "collective"}],
                "morning_talk": {"topic": "话题", "questions": "问题"},
                "group_activity": {
                    "theme": "主题",
                    "objectives": "目标",
                    "preparation": "准备",
                    "key_points": "重点",
                    "difficult_points": "难点",
                    "process": "过程",
                },
                "post_group_games": [{"context_kind": "area"}],
                "afternoon_outdoor": {"area": "操场"},
                "reflection": "反思",
            }
        )
        fields = {fact["field"] for fact in facts}
        self.assertIn("morning_games.free_choice", fields)
        self.assertIn("morning_games[0].games", fields)
        self.assertIn("post_group_games[0].games", fields)
        self.assertIn("afternoon_outdoor.games", fields)


class DailyAckBindingTests(unittest.TestCase):
    def _prepare(self, spec, expected, *, ack=True):
        plans = []
        contents = []
        for plan_id, version, adopted in spec:
            content_id = f"c-{plan_id}"
            plans.append(
                _dplan(
                    plan_id=plan_id,
                    plan_date=date(2026, 9, 1),
                    content_id=content_id,
                    version=version,
                )
            )
            contents.append(
                _dcontent(
                    plan_id=plan_id,
                    content_id=content_id,
                    version=version,
                    adopted=adopted,
                )
            )
        db = _StubSession(scalars_queue=[plans, contents])
        return export.prepare_daily_export(
            db,
            class_id="cls1",
            from_date=date(2026, 9, 1),
            to_date=date(2026, 9, 3),
            ack_missing=ack,
            expected_context=expected,
        )

    def _single(self, expected, *, ack=True, version=1, adopted=None):
        return self._prepare(
            [("dp1", version, adopted if adopted is not None else {})],
            expected,
            ack=ack,
        )

    def test_first_incomplete_requires_ack_with_context(self):
        bundle = self._single(None, ack=False)
        self.assertTrue(bundle.ack_required)
        self.assertEqual(bundle.ack_reason, "missing")
        self.assertTrue(bundle.missing)
        self.assertIn("versions", bundle.expected_context)
        self.assertIn("missing_fingerprint", bundle.expected_context)

    def test_first_complete_content_exports_directly(self):
        bundle = self._single(None, ack=False, adopted=_complete_content())
        self.assertFalse(bundle.ack_required)
        self.assertIsNone(bundle.ack_reason)
        self.assertEqual(bundle.missing, ())

    def test_same_object_allows_retry(self):
        first = self._single(None, ack=False)
        retry = self._single(first.expected_context, ack=True)
        self.assertFalse(retry.ack_required)
        self.assertIsNone(retry.ack_reason)
        self.assertEqual(
            retry.expected_context["missing_fingerprint"],
            first.expected_context["missing_fingerprint"],
        )

    def test_same_object_without_ack_still_requires(self):
        first = self._single(None, ack=False)
        retry = self._single(first.expected_context, ack=False)
        self.assertTrue(retry.ack_required)
        self.assertEqual(retry.ack_reason, "missing")

    def test_content_version_change_same_missing_reprompts(self):
        first = self._single(None, ack=False)
        # Same facts, but the pinned content version moved on.
        changed = self._single(first.expected_context, ack=True, version=2)
        self.assertTrue(changed.ack_required)
        self.assertEqual(changed.ack_reason, "context_changed")

    def test_new_missing_item_reprompts(self):
        initial = _complete_payload()
        del initial["reflection"]
        later = _complete_payload()
        del later["reflection"]
        del later["group_activity"]["theme"]
        first = self._single(None, ack=False, adopted=_parsed(initial))
        self.assertTrue(first.ack_required)
        changed = self._single(
            first.expected_context, ack=True, adopted=_parsed(later)
        )
        self.assertTrue(changed.ack_required)
        self.assertEqual(changed.ack_reason, "context_changed")
        self.assertNotEqual(
            changed.expected_context["missing_fingerprint"],
            first.expected_context["missing_fingerprint"],
        )

    def test_missing_reduction_still_nonzero_reprompts(self):
        reduced = _complete_payload()
        del reduced["reflection"]
        first = self._single(None, ack=False, adopted={})  # all missing
        changed = self._single(
            first.expected_context, ack=True, adopted=_parsed(reduced)
        )
        self.assertTrue(changed.ack_required)
        self.assertEqual(changed.ack_reason, "context_changed")

    def test_missing_reduction_to_zero_reprompts(self):
        # R2 core: V1 incomplete -> V2 complete with the old context must not
        # silently export just because the latest missing set is now empty.
        first = self._single(None, ack=False, adopted={})
        complete = self._single(
            first.expected_context, ack=True, adopted=_complete_content()
        )
        self.assertTrue(complete.ack_required)
        self.assertEqual(complete.ack_reason, "context_changed")
        self.assertEqual(complete.missing, ())
        # Re-confirming the returned latest context then continues.
        again = self._single(
            complete.expected_context,
            ack=True,
            adopted=_complete_content(),
        )
        self.assertFalse(again.ack_required)
        self.assertIsNone(again.ack_reason)

    def test_object_set_change_reprompts(self):
        first = self._single(None, ack=False, adopted={})
        changed = self._prepare(
            [("dp1", 1, {}), ("dp2", 1, {})],
            first.expected_context,
            ack=True,
        )
        self.assertTrue(changed.ack_required)
        self.assertEqual(changed.ack_reason, "context_changed")
        self.assertEqual(len(changed.expected_context["versions"]), 2)

    def test_invalid_context_with_complete_content_reprompts(self):
        forged = self._single(
            {"class_id": "x"},
            ack=True,
            adopted=_complete_content(),
        )
        self.assertTrue(forged.ack_required)
        self.assertEqual(forged.ack_reason, "context_changed")

    def test_ack_does_not_trust_client_facts(self):
        first = self._single(None, ack=False)
        forged = dict(first.expected_context)
        forged["missing_fingerprint"] = "0" * 64
        blocked = self._single(forged, ack=True)
        self.assertTrue(blocked.ack_required)
        self.assertEqual(blocked.ack_reason, "context_changed")
        # Server recomputed facts are still returned, not the client's.
        self.assertTrue(blocked.missing)


class DailyAckContextUnitTests(unittest.TestCase):
    def test_context_and_matching(self):
        records = [
            _drecord(plan_id="dp1", content_id="c1", content_version=1),
            _drecord(plan_id="dp2", content_id="c2", content_version=4),
        ]
        missing = [
            {"daily_plan_id": "dp1", "plan_date": "2026-09-01", "fields": ["reflection"]}
        ]
        ctx = export.daily_ack_context(
            class_id="cls1",
            from_date=date(2026, 9, 1),
            to_date=date(2026, 9, 3),
            records=records,
            missing=missing,
        )
        self.assertTrue(export.daily_ack_matches(ctx, ctx))
        self.assertFalse(export.daily_ack_matches(None, ctx))
        self.assertFalse(export.daily_ack_matches({"class_id": "x"}, ctx))

        # Version change alone changes the object.
        changed_records = [
            _drecord(plan_id="dp1", content_id="c1", content_version=2),
            _drecord(plan_id="dp2", content_id="c2", content_version=4),
        ]
        changed = export.daily_ack_context(
            class_id="cls1",
            from_date=date(2026, 9, 1),
            to_date=date(2026, 9, 3),
            records=changed_records,
            missing=missing,
        )
        self.assertFalse(export.daily_ack_matches(ctx, changed))


class WeeklySelectionTests(unittest.TestCase):
    def _db(self, plans, terms, confirmed, week_days_map, *, extra_scalars=None):
        get_map = {}
        for term in terms:
            get_map[("Term", term.id)] = term
        for row in confirmed:
            get_map[("WeeklyPlanConfirmedContent", row.id)] = row
        queue = [plans]
        if extra_scalars:
            queue.extend(extra_scalars)
        return _StubSession(get_map=get_map, scalars_queue=queue)

    def _patch(self, week_days_map):
        return mock.patch.object(
            export,
            "read_week_days",
            side_effect=lambda db, term, week_number: dict(
                week_days_map[(term.id, week_number)]
            ),
        )

    def test_range_intersection_and_cross_term_order(self):
        term_a = _term(term_id="ta", start=date(2026, 9, 1), end=date(2026, 9, 30))
        term_b = _term(term_id="tb", start=date(2026, 10, 5), end=date(2026, 10, 31))
        plan_a = _wplan(plan_id="wa", term_id="ta", week_number=5, confirmed_id="cfa")
        plan_b = _wplan(plan_id="wb", term_id="tb", week_number=1, confirmed_id="cfb")
        confirmed = [
            _wconfirmed(content_id="cfa", content=_empty_content()),
            _wconfirmed(content_id="cfb", content=_empty_content()),
        ]
        confirmed[0].weekly_plan_id = "wa"
        confirmed[1].weekly_plan_id = "wb"
        week_days_map = {
            # week 5 of term a: 09-28..09-30 inside term
            ("ta", 5): {
                date(2026, 9, 28): "teaching",
                date(2026, 9, 29): "teaching",
                date(2026, 9, 30): "teaching",
            },
            # week 1 of term b: 10-05..10-11
            ("tb", 1): {
                date(2026, 10, 5): "teaching",
                date(2026, 10, 6): "teaching",
            },
        }
        db = self._db([plan_b, plan_a], [term_a, term_b], confirmed, week_days_map)
        with self._patch(week_days_map), mock.patch.object(
            export.weekly_plan_sync_service, "load_week_entries", return_value=[]
        ):
            items = export.select_weekly_plans_range(
                db,
                class_id="cls1",
                from_date=date(2026, 9, 28),
                to_date=date(2026, 10, 6),
            )
        # Sorted by actual week start, not by bare week_number (5 before 1).
        self.assertEqual([item.plan_id for item in items], ["wa", "wb"])
        self.assertEqual(items[0].confirmed_version, 1)
        self.assertEqual(items[0].week_start, date(2026, 9, 28))

    def test_same_week_number_not_deduped_across_terms(self):
        term_a = _term(term_id="ta", start=date(2026, 9, 28), end=date(2026, 10, 9))
        term_b = _term(term_id="tb", start=date(2026, 10, 5), end=date(2026, 10, 16))
        plan_a = _wplan(plan_id="wa", term_id="ta", week_number=1, confirmed_id="cfa")
        plan_b = _wplan(plan_id="wb", term_id="tb", week_number=1, confirmed_id="cfb")
        cfa = _wconfirmed(content_id="cfa", content=_empty_content())
        cfa.weekly_plan_id = "wa"
        cfb = _wconfirmed(content_id="cfb", content=_empty_content())
        cfb.weekly_plan_id = "wb"
        week_days_map = {
            ("ta", 1): {
                date(2026, 9, 28): "teaching",
                date(2026, 9, 29): "teaching",
            },
            ("tb", 1): {
                date(2026, 10, 5): "teaching",
                date(2026, 10, 6): "teaching",
            },
        }
        db = self._db([plan_a, plan_b], [term_a, term_b], [cfa, cfb], week_days_map)
        with self._patch(week_days_map), mock.patch.object(
            export.weekly_plan_sync_service, "load_week_entries", return_value=[]
        ):
            items = export.select_weekly_plans_range(
                db,
                class_id="cls1",
                from_date=date(2026, 9, 28),
                to_date=date(2026, 10, 6),
            )
        self.assertEqual([item.plan_id for item in items], ["wa", "wb"])
        self.assertTrue(all(item.week_number == 1 for item in items))

    def test_zero_class_day_week_not_selected(self):
        term = _term(term_id="ta", start=date(2026, 9, 28), end=date(2026, 10, 18))
        plan = _wplan(plan_id="wa", term_id="ta", week_number=2)
        confirmed = _wconfirmed(content=_empty_content())
        confirmed.weekly_plan_id = "wa"
        week_days_map = {
            ("ta", 2): {
                date(2026, 10, 5): "rest",
                date(2026, 10, 6): "rest",
            }
        }
        db = self._db([plan], [term], [confirmed], week_days_map)
        with self._patch(week_days_map), mock.patch.object(
            export.weekly_plan_sync_service, "load_week_entries", return_value=[]
        ):
            items = export.select_weekly_plans_range(
                db,
                class_id="cls1",
                from_date=date(2026, 10, 5),
                to_date=date(2026, 10, 11),
            )
        self.assertEqual(items, [])

    def test_single_explicit_version(self):
        term = _term()
        plan = _wplan(plan_id="wa", term_id="ter1", week_number=1)
        explicit = _wconfirmed(content_id="cfhist", version=1, content=_empty_content())
        explicit.weekly_plan_id = "wa"
        week_days_map = {("ter1", 1): {date(2026, 9, 1): "teaching"}}
        db = _StubSession(
            get_map={
                ("WeeklyPlan", "wa"): plan,
                ("Term", "ter1"): term,
            },
            scalars_queue=[[explicit]],
        )
        with self._patch(week_days_map), mock.patch.object(
            export.weekly_plan_sync_service, "load_week_entries", return_value=[]
        ):
            item = export.load_weekly_single(
                db,
                class_id="cls1",
                role="teacher",
                plan_id="wa",
                confirmed_version=1,
            )
        self.assertEqual(item.confirmed_content_id, "cfhist")

    def test_single_current_pointer_and_missing_confirmation(self):
        term = _term()
        plan = _wplan(
            plan_id="wa", term_id="ter1", week_number=1, confirmed_id="cfcur"
        )
        current = _wconfirmed(content_id="cfcur", version=1, content=_empty_content())
        current.weekly_plan_id = "wa"
        week_days_map = {("ter1", 1): {date(2026, 9, 1): "teaching"}}
        db = _StubSession(
            get_map={
                ("WeeklyPlan", "wa"): plan,
                ("Term", "ter1"): term,
                ("WeeklyPlanConfirmedContent", "cfcur"): current,
            }
        )
        with self._patch(week_days_map), mock.patch.object(
            export.weekly_plan_sync_service, "load_week_entries", return_value=[]
        ):
            item = export.load_weekly_single(
                db, class_id="cls1", role="teacher", plan_id="wa"
            )
        self.assertEqual(item.confirmed_content_id, "cfcur")

        never = _wplan(
            plan_id="wa",
            term_id="ter1",
            week_number=1,
            confirmed_id=None,
            confirmed_version=None,
        )
        db2 = _StubSession(
            get_map={("WeeklyPlan", "wa"): never, ("Term", "ter1"): term}
        )
        with self._patch(week_days_map), mock.patch.object(
            export.weekly_plan_sync_service, "load_week_entries", return_value=[]
        ):
            with self.assertRaises(export.ExportConfirmationNotFound):
                export.load_weekly_single(
                    db2, class_id="cls1", role="teacher", plan_id="wa"
                )

    def test_single_permission_matrix(self):
        term = _term()
        plan = _wplan(plan_id="wa", term_id="ter1", week_number=1)
        week_days_map = {("ter1", 1): {date(2026, 9, 1): "teaching"}}
        db = _StubSession(
            get_map={("WeeklyPlan", "wa"): plan, ("Term", "ter1"): term}
        )
        with self._patch(week_days_map), mock.patch.object(
            export.weekly_plan_sync_service, "load_week_entries", return_value=[]
        ):
            with self.assertRaises(export.ExportReadForbidden):
                export.load_weekly_single(
                    db, class_id="other", role="teacher", plan_id="wa"
                )
        db2 = _StubSession(
            get_map={("WeeklyPlan", "wa"): plan, ("Term", "ter1"): term}
        )
        with self._patch(week_days_map), mock.patch.object(
            export.weekly_plan_sync_service, "load_week_entries", return_value=[]
        ):
            with self.assertRaises(export.ExportReadNotFound):
                export.load_weekly_single(
                    db2, class_id="other", role="admin", plan_id="wa"
                )


class WeeklyWarningTests(unittest.TestCase):
    def _entry(self, *, version=2, content_id="c2"):
        return WeekPlanEntry(
            plan_id="dp1",
            content_id=content_id,
            content_version=version,
            plan_date=date(2026, 9, 1),
            adopted_content={},
        )

    def _content(self, *, source_version=1, source_id="c1"):
        return {
            "theme": "主题",
            "deterministic": [
                {
                    "date": "2026-09-01",
                    "day_state": "teaching",
                    "plan_state": "saved",
                    "source": {
                        "daily_plan_id": "dp1",
                        "content_id": source_id,
                        "content_version": source_version,
                        "morning_talk_topic": "谈话",
                        "group_activity_theme": "活动",
                    },
                    "override": {},
                    "effective": {
                        "morning_talk_topic": "谈话",
                        "group_activity_theme": "活动",
                    },
                }
            ],
            "outdoor_game_slots": {key: None for key in mapping.OUTDOOR_SLOT_KEYS},
            "focus_area": None,
            "weekly_columns": {key: "内容" for key in mapping.WEEKLY_COLUMN_KEYS},
            "materials": None,
        }

    def _days(self):
        return {date(2026, 9, 1): "teaching"}

    def test_clean_no_warning(self):
        plan = _wplan(draft_version=2, confirmed_version=1)
        confirmed = _wconfirmed(version=1, draft_version=2)
        content = self._content(source_version=2, source_id="c2")
        # entry matches the content source versions -> no stale.
        entries = [self._entry(version=2, content_id="c2")]
        self.assertEqual(
            export.judge_weekly_warning(plan, confirmed, content, entries, self._days()),
            [],
        )

    def test_draft_ahead(self):
        plan = _wplan(draft_version=3, confirmed_version=1)
        confirmed = _wconfirmed(version=1, draft_version=2)
        content = self._content(source_version=2, source_id="c2")
        entries = [self._entry(version=2, content_id="c2")]
        self.assertEqual(
            export.judge_weekly_warning(plan, confirmed, content, entries, self._days()),
            ["draft_ahead"],
        )

    def test_stale_sources(self):
        plan = _wplan(draft_version=2, confirmed_version=1)
        confirmed = _wconfirmed(version=1, draft_version=2)
        content = self._content(source_version=1, source_id="c1")
        entries = [self._entry(version=2, content_id="c2")]
        self.assertEqual(
            export.judge_weekly_warning(plan, confirmed, content, entries, self._days()),
            ["stale_sources"],
        )

    def test_superseded(self):
        plan = _wplan(draft_version=2, confirmed_version=2)
        confirmed = _wconfirmed(version=1, draft_version=2)
        content = self._content(source_version=2, source_id="c2")
        entries = [self._entry(version=2, content_id="c2")]
        self.assertEqual(
            export.judge_weekly_warning(plan, confirmed, content, entries, self._days()),
            ["superseded"],
        )

    def test_recorded_stale_fact(self):
        plan = _wplan(draft_version=2, confirmed_version=1)
        confirmed = _wconfirmed(
            version=1,
            draft_version=2,
            facts={"missing": [], "stale_sources": [{"slot": "deterministic"}]},
        )
        content = self._content(source_version=2, source_id="c2")
        entries = [self._entry(version=2, content_id="c2")]
        self.assertEqual(
            export.judge_weekly_warning(plan, confirmed, content, entries, self._days()),
            ["recorded_stale"],
        )


if __name__ == "__main__":
    unittest.main()
