"""No-DB pure unittest for I4 weekly_plan_content rules."""

import copy
import unittest
from datetime import date

from app.services.weekly_plan_content import (
    ContentValidationError,
    build_deterministic,
    build_facts,
    build_source_candidates,
    new_content,
    prepare_patch,
    refresh_content,
)
from app.services.weekly_plan_sync_service import WeekPlanEntry


def _entry(
    day: int,
    *,
    plan_id: str | None = None,
    content_id: str,
    version: int,
    adopted: dict,
) -> WeekPlanEntry:
    return WeekPlanEntry(
        plan_id=plan_id or f"plan-{day}",
        content_id=content_id,
        content_version=version,
        plan_date=date(2026, 9, day),
        adopted_content=adopted,
    )


def _days_full() -> dict[date, str]:
    # Mon 7 - Sun 13, 2026-09
    return {
        date(2026, 9, 7): "teaching",
        date(2026, 9, 8): "teaching",
        date(2026, 9, 9): "rest",
        date(2026, 9, 10): "teaching",
        date(2026, 9, 11): "teaching",
        date(2026, 9, 12): "rest",
        date(2026, 9, 13): "rest",
    }


def _adopted_full(
    *,
    topic: str = "秋天的树",
    theme: str = "捡落叶",
    collective_name: str = "跳圈圈",
    free_name: str = "滚球",
    focus_name: str = "建构区",
) -> dict:
    return {
        "morning_talk": {"topic": topic, "questions": "q"},
        "group_activity": {"theme": theme, "objectives": "o"},
        "morning_games": [
            {
                "group_id": "g-col",
                "group_kind": "collective",
                "games": [{"game_id": "gm-col", "name": collective_name}],
                "shared_objectives": "shared-obj",
                "guidance_points": "guide-points",
                "focus_guidance": "focus-guide",
            },
            {
                "group_id": "g-free",
                "group_kind": "free_choice",
                "games": [{"game_id": "gm-free", "name": free_name}],
                "shared_objectives": "free-obj",
                "guidance_points": "free-guide",
                "focus_guidance": "free-focus",
            },
        ],
        "post_group_games": [
            {
                "context_kind": "area",
                "group_id": "g-focus",
                "area": "建构区",
                "games": [{"game_id": "gm-focus", "name": focus_name}],
                "objectives": "focus-obj",
                "guidance": "focus-guidance",
                "support_strategy": "support",
            }
        ],
        "afternoon_outdoor": {
            "group_id": "g-noon",
            "area": "户外",
            "games": [{"game_id": "gm-noon", "name": "午休后游戏"}],
            "objectives": "noon-obj",
            "guidance": "noon-guide",
        },
    }


def _entries_version1() -> list[WeekPlanEntry]:
    return [
        _entry(
            7,
            content_id="c7",
            version=1,
            adopted=_adopted_full(),
        )
    ]


def _collective_candidate(entries) -> dict:
    for cand in build_source_candidates(entries):
        if cand.get("group_kind") == "collective":
            return cand
    raise AssertionError("collective candidate missing")


def _focus_candidate(entries) -> dict:
    for cand in build_source_candidates(entries):
        if cand.get("category") == "focus":
            return cand
    raise AssertionError("focus candidate missing")


def _slot_from_candidate(cand: dict) -> dict:
    return {
        "source_kind": "daily_plan",
        "manual_item_id": None,
        "daily_plan_id": cand["daily_plan_id"],
        "content_id": cand["content_id"],
        "content_version": cand["content_version"],
        "group_id": cand["group_id"],
        "game_id": cand["game_id"],
        "name": cand["name"],
        "shared_objectives": cand.get("shared_objectives"),
        "guidance_points": cand.get("guidance_points"),
        "focus_guidance": cand.get("focus_guidance"),
    }


def _focus_from_candidate(cand: dict) -> dict:
    return {
        "source_kind": "daily_plan",
        "manual_item_id": None,
        "daily_plan_id": cand["daily_plan_id"],
        "content_id": cand["content_id"],
        "content_version": cand["content_version"],
        "group_id": cand["group_id"],
        "game_id": cand["game_id"],
        "context_kind": cand.get("context_kind"),
        "area": cand.get("area"),
        "name": cand.get("name"),
        "objectives": cand.get("objectives"),
        "guidance": cand.get("guidance"),
        "support_strategy": cand.get("support_strategy"),
    }


class DeterministicTests(unittest.TestCase):
    def test_plan_states_and_empty_field_trichotomy(self):
        days = _days_full()
        entries = _entries_version1()
        rows = build_deterministic(entries, days, None)
        by_date = {r["date"]: r for r in rows}
        self.assertEqual(
            set(by_date),
            {d.isoformat() for d in days},
        )
        saved = by_date["2026-09-07"]
        self.assertEqual(saved["plan_state"], "saved")
        self.assertEqual(saved["source"]["morning_talk_topic"], "秋天的树")
        self.assertEqual(saved["source"]["group_activity_theme"], "捡落叶")
        no_plan = by_date["2026-09-08"]
        self.assertEqual(no_plan["plan_state"], "no_plan")
        self.assertIsNone(no_plan["source"]["daily_plan_id"])
        self.assertIsNone(no_plan["source"]["morning_talk_topic"])
        rest = by_date["2026-09-09"]
        self.assertEqual(rest["plan_state"], "none_required")
        self.assertIsNone(rest["source"]["daily_plan_id"])
        self.assertIsNone(rest["source"]["content_id"])
        self.assertIsNone(rest["source"]["content_version"])
        self.assertIsNone(rest["source"]["morning_talk_topic"])
        self.assertIsNone(rest["source"]["group_activity_theme"])

    def test_empty_saved_field_is_empty_string_not_null(self):
        days = {date(2026, 9, 7): "teaching"}
        adopted = _adopted_full()
        adopted["morning_talk"]["topic"] = ""
        entries = [
            _entry(7, content_id="c7", version=1, adopted=adopted)
        ]
        rows = build_deterministic(entries, days, None)
        self.assertEqual(rows[0]["plan_state"], "saved")
        self.assertEqual(rows[0]["source"]["morning_talk_topic"], "")
        self.assertEqual(rows[0]["effective"]["morning_talk_topic"], "")

    def test_source_override_effective_layers(self):
        days = {date(2026, 9, 7): "teaching"}
        entries = [
            _entry(
                7, content_id="c7", version=1, adopted=_adopted_full()
            )
        ]
        previous = new_content(entries, days, theme="t")
        patched = prepare_patch(
            previous,
            {
                "deterministic_overrides": {
                    "2026-09-07": {"morning_talk_topic": "人工覆盖"}
                }
            },
            entries,
            days,
        )
        row = patched["deterministic"][0]
        self.assertEqual(row["source"]["morning_talk_topic"], "秋天的树")
        self.assertEqual(row["override"]["morning_talk_topic"], "人工覆盖")
        self.assertEqual(row["effective"]["morning_talk_topic"], "人工覆盖")

    def test_override_kept_on_save_and_refresh_null_clears(self):
        days = {date(2026, 9, 7): "teaching"}
        entries = [
            _entry(
                7, content_id="c7", version=1, adopted=_adopted_full()
            )
        ]
        previous = new_content(entries, days, theme="t")
        with_override = prepare_patch(
            previous,
            {
                "deterministic_overrides": {
                    "2026-09-07": {"group_activity_theme": "改主题"}
                }
            },
            entries,
            days,
        )
        again = prepare_patch(with_override, {"theme": "新主题"}, entries, days)
        self.assertEqual(
            again["deterministic"][0]["override"]["group_activity_theme"],
            "改主题",
        )
        self.assertEqual(again["theme"], "新主题")
        refreshed, _audit = refresh_content(again, entries, days)
        self.assertEqual(
            refreshed["deterministic"][0]["override"]["group_activity_theme"],
            "改主题",
        )
        cleared = prepare_patch(
            again,
            {
                "deterministic_overrides": {
                    "2026-09-07": {"group_activity_theme": None}
                }
            },
            entries,
            days,
        )
        self.assertIsNone(
            cleared["deterministic"][0]["override"]["group_activity_theme"]
        )
        self.assertEqual(
            cleared["deterministic"][0]["effective"]["group_activity_theme"],
            "捡落叶",
        )


class CandidateTests(unittest.TestCase):
    def test_outdoor_only_morning_focus_only_post_no_afternoon(self):
        entries = _entries_version1()
        cands = build_source_candidates(entries)
        outdoor = [
            c for c in cands if c["source_section"] == "morning_games"
        ]
        focus = [
            c for c in cands if c["source_section"] == "post_group_games"
        ]
        self.assertEqual({c["category"] for c in outdoor}, {"collective", "free_choice"})
        self.assertEqual({c["category"] for c in focus}, {"focus"})
        for c in cands:
            self.assertEqual(c["source_kind"], "daily_plan")
        self.assertFalse(any(c["game_id"] == "gm-noon" for c in cands))
        self.assertFalse(any(c.get("context_kind") == "area" and c["source_section"] == "morning_games" for c in cands))

    def test_whole_group_text_came_from_same_group(self):
        entries = _entries_version1()
        cand = _collective_candidate(entries)
        self.assertEqual(cand["shared_objectives"], "shared-obj")
        self.assertEqual(cand["guidance_points"], "guide-points")
        self.assertEqual(cand["focus_guidance"], "focus-guide")


class PatchSlotTests(unittest.TestCase):
    def _base(self):
        days = _days_full()
        entries = _entries_version1()
        previous = new_content(entries, days, theme="秋")
        return days, entries, previous

    def test_manual_slot_null_refs_and_stable_id_chain(self):
        days, entries, previous = self._base()
        with_manual = prepare_patch(
            previous,
            {
                "outdoor_game_slots": {
                    "collective_1": {
                        "source_kind": "manual",
                        "name": "滚球游戏",
                        "shared_objectives": "so",
                        "guidance_points": "gp",
                        "focus_guidance": "fg",
                    }
                }
            },
            entries,
            days,
        )
        manual = with_manual["outdoor_game_slots"]["collective_1"]
        self.assertEqual(manual["source_kind"], "manual")
        self.assertTrue(manual["manual_item_id"])
        for field in (
            "daily_plan_id",
            "content_id",
            "content_version",
            "group_id",
            "game_id",
        ):
            self.assertIn(field, manual)
            self.assertIsNone(manual[field])

        only_theme = prepare_patch(
            with_manual, {"theme": "只改主题"}, entries, days
        )
        self.assertEqual(
            only_theme["outdoor_game_slots"]["collective_1"],
            manual,
        )

        same_id_text = copy.deepcopy(manual)
        same_id_text["name"] = "改名后的手工"
        retyped = prepare_patch(
            only_theme,
            {"outdoor_game_slots": {"collective_1": same_id_text}},
            entries,
            days,
        )
        self.assertEqual(
            retyped["outdoor_game_slots"]["collective_1"]["manual_item_id"],
            manual["manual_item_id"],
        )
        self.assertEqual(
            retyped["outdoor_game_slots"]["collective_1"]["name"],
            "改名后的手工",
        )

        refreshed, audit = refresh_content(retyped, entries, days)
        self.assertEqual(
            refreshed["outdoor_game_slots"]["collective_1"]["manual_item_id"],
            manual["manual_item_id"],
        )
        self.assertEqual(
            refreshed["outdoor_game_slots"]["collective_1"]["name"],
            "改名后的手工",
        )
        self.assertEqual(refreshed["theme"], "只改主题")
        self.assertFalse(
            any(
                a.get("slot") == "collective_1" and a.get("kind") == "refreshed"
                for a in audit
            )
        )

    def test_same_identity_returned_with_fake_version_keeps_old_snapshot(self):
        days, entries, previous = self._base()
        cand = _collective_candidate(entries)
        selected = prepare_patch(
            previous,
            {
                "outdoor_game_slots": {
                    "collective_1": _slot_from_candidate(cand)
                }
            },
            entries,
            days,
        )
        old = selected["outdoor_game_slots"]["collective_1"]
        tampered = copy.deepcopy(old)
        tampered["content_version"] = 999
        tampered["name"] = "伪造文本"
        again = prepare_patch(
            selected,
            {"outdoor_game_slots": {"collective_1": tampered}},
            entries,
            days,
        )
        self.assertEqual(
            again["outdoor_game_slots"]["collective_1"], old
        )
        self.assertEqual(old["content_version"], 1)
        self.assertEqual(old["name"], "跳圈圈")

    def test_omitted_slot_inherits_previous(self):
        days, entries, previous = self._base()
        cand = _collective_candidate(entries)
        selected = prepare_patch(
            previous,
            {
                "outdoor_game_slots": {
                    "collective_1": _slot_from_candidate(cand)
                }
            },
            entries,
            days,
        )
        inherited = prepare_patch(selected, {"theme": "x"}, entries, days)
        self.assertEqual(
            inherited["outdoor_game_slots"]["collective_1"],
            selected["outdoor_game_slots"]["collective_1"],
        )
        self.assertIsNone(inherited["outdoor_game_slots"]["collective_2"])

    def test_reselect_replaces_whole_group_object(self):
        days, entries, previous = self._base()
        cand_col = _collective_candidate(entries)
        cand_free = next(
            c
            for c in build_source_candidates(entries)
            if c.get("group_kind") == "free_choice"
        )
        # Category mismatch rejected first.
        with self.assertRaises(ContentValidationError):
            prepare_patch(
                previous,
                {
                    "outdoor_game_slots": {
                        "collective_1": _slot_from_candidate(cand_free)
                    }
                },
                entries,
                days,
            )

        selected = prepare_patch(
            previous,
            {
                "outdoor_game_slots": {
                    "collective_1": _slot_from_candidate(cand_col)
                }
            },
            entries,
            days,
        )
        # Change identity to free-choice game placed in free slot, then
        # collective slot reselected to a different daily plan ref.
        other_entry = _entry(
            8,
            plan_id="plan-8",
            content_id="c8",
            version=2,
            adopted=_adopted_full(collective_name="另一个集体游戏"),
        )
        entries2 = entries + [other_entry]
        cand2 = next(
            c
            for c in build_source_candidates(entries2)
            if c["daily_plan_id"] == "plan-8"
            and c.get("group_kind") == "collective"
        )
        reselected = prepare_patch(
            selected,
            {
                "outdoor_game_slots": {
                    "collective_1": _slot_from_candidate(cand2)
                }
            },
            entries2,
            days,
        )
        new_slot = reselected["outdoor_game_slots"]["collective_1"]
        self.assertEqual(new_slot["daily_plan_id"], "plan-8")
        self.assertEqual(new_slot["content_version"], 2)
        self.assertEqual(new_slot["name"], "另一个集体游戏")
        self.assertEqual(new_slot["shared_objectives"], "shared-obj")
        # Whole object replaced: old identity fields are gone.
        self.assertNotEqual(
            new_slot["content_id"], old_content_id(selected)
        )

    def test_same_category_same_name_rejected_including_manual(self):
        days, entries, previous = self._base()
        # Single-slot manual is legal; dual-slot same name must fail.
        prepare_patch(
            previous,
            {
                "outdoor_game_slots": {
                    "collective_1": {
                        "source_kind": "manual",
                        "name": "跳圈圈",
                        "shared_objectives": "a",
                        "guidance_points": "b",
                        "focus_guidance": "c",
                    }
                }
            },
            entries,
            days,
        )
        with self.assertRaises(ContentValidationError):
            prepare_patch(
                previous,
                {
                    "outdoor_game_slots": {
                        "collective_1": {
                            "source_kind": "manual",
                            "name": "跳圈圈",
                            "shared_objectives": "a",
                            "guidance_points": "b",
                            "focus_guidance": "c",
                        },
                        "collective_2": {
                            "source_kind": "manual",
                            "name": "跳圈圈",
                            "shared_objectives": "a",
                            "guidance_points": "b",
                            "focus_guidance": "c",
                        },
                    }
                },
                entries,
                days,
            )

        cand = _collective_candidate(entries)
        with self.assertRaises(ContentValidationError):
            prepare_patch(
                previous,
                {
                    "outdoor_game_slots": {
                        "collective_1": _slot_from_candidate(cand),
                        "collective_2": {
                            "source_kind": "manual",
                            "name": cand["name"],
                            "shared_objectives": "a",
                            "guidance_points": "b",
                            "focus_guidance": "c",
                        },
                    }
                },
                entries,
                days,
            )

    def test_category_mismatch_free_choice_on_collective_slot(self):
        days, entries, previous = self._base()
        free_cand = next(
            c
            for c in build_source_candidates(entries)
            if c.get("group_kind") == "free_choice"
        )
        with self.assertRaises(ContentValidationError):
            prepare_patch(
                previous,
                {
                    "outdoor_game_slots": {
                        "collective_1": _slot_from_candidate(free_cand)
                    }
                },
                entries,
                days,
            )


class FocusTests(unittest.TestCase):
    def _base(self):
        days = _days_full()
        entries = _entries_version1()
        previous = new_content(entries, days, theme="秋")
        return days, entries, previous

    def test_focus_from_post_group_only(self):
        days, entries, previous = self._base()
        cand = _focus_candidate(entries)
        selected = prepare_patch(
            previous, {"focus_area": _focus_from_candidate(cand)}, entries, days
        )
        self.assertEqual(selected["focus_area"]["context_kind"], "area")
        self.assertEqual(selected["focus_area"]["name"], "建构区")

        # afternoon_outdoor game cannot be selected as focus
        focus_by_ref = {
            (c["daily_plan_id"], c["group_id"], c["game_id"]): c
            for c in build_source_candidates(entries)
            if c.get("category") == "focus"
        }
        noon_ref = ("plan-7", "g-noon", "gm-noon")
        self.assertNotIn(noon_ref, focus_by_ref)
        with self.assertRaises(ContentValidationError):
            prepare_patch(
                previous,
                {
                    "focus_area": {
                        "source_kind": "daily_plan",
                        "daily_plan_id": "plan-7",
                        "content_id": "c7",
                        "content_version": 1,
                        "group_id": "g-noon",
                        "game_id": "gm-noon",
                        "context_kind": "outdoor",
                        "area": "户外",
                        "name": "午休后游戏",
                        "objectives": "x",
                        "guidance": "y",
                        "support_strategy": "z",
                    }
                },
                entries,
                days,
            )

    def test_focus_rejects_manual_and_unknown_kind(self):
        days, entries, previous = self._base()
        for payload in (
            {"source_kind": "manual", "manual_item_id": "m1", "name": "x"},
            {"source_kind": "ai"},
            {"source_kind": ["daily_plan"]},
            {"source_kind": {"a": 1}},
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(ContentValidationError):
                    prepare_patch(
                        previous, {"focus_area": payload}, entries, days
                    )


class ValidationRejectTests(unittest.TestCase):
    def _base(self):
        days = _days_full()
        entries = _entries_version1()
        previous = new_content(entries, days, theme="秋")
        return days, entries, previous

    def test_ai_and_unknown_source_kind_rejected_without_typeerror(self):
        days, entries, previous = self._base()
        for kind in ("ai", "unknown", ["manual"], {"a": 1}, 5, None):
            with self.subTest(kind=kind):
                with self.assertRaises(ContentValidationError):
                    prepare_patch(
                        previous,
                        {
                            "outdoor_game_slots": {
                                "collective_1": {
                                    "source_kind": kind,
                                    "name": "x",
                                }
                            }
                        },
                        entries,
                        days,
                    )

    def test_unknown_nested_and_top_level_fields_rejected(self):
        days, entries, previous = self._base()
        with self.assertRaises(ContentValidationError):
            prepare_patch(previous, {"bogus": 1}, entries, days)
        with self.assertRaises(ContentValidationError):
            prepare_patch(
                previous,
                {
                    "outdoor_game_slots": {
                        "collective_1": {
                            "source_kind": "manual",
                            "name": "x",
                            "bogus": 1,
                        }
                    }
                },
                entries,
                days,
            )
        with self.assertRaises(ContentValidationError):
            prepare_patch(
                previous, {"weekly_columns": {"bogus": ""}}, entries, days
            )

    def test_illegal_ref_types_rejected_as_validation_error(self):
        days, entries, previous = self._base()
        bad_cases = [
            {
                "source_kind": "daily_plan",
                "daily_plan_id": "plan-7",
                "content_id": "c7",
                "content_version": "2",
                "group_id": "g-col",
                "game_id": "gm-col",
                "name": "跳圈圈",
            },
            {
                "source_kind": "daily_plan",
                "daily_plan_id": "plan-7",
                "content_id": "c7",
                "content_version": True,
                "group_id": "g-col",
                "game_id": "gm-col",
                "name": "跳圈圈",
            },
            {
                "source_kind": "daily_plan",
                "daily_plan_id": "",
                "content_id": "c7",
                "content_version": 1,
                "group_id": "g-col",
                "game_id": "gm-col",
                "name": "跳圈圈",
            },
            {
                "source_kind": "daily_plan",
                "daily_plan_id": "plan-7",
                "content_id": "c7",
                "content_version": 0,
                "group_id": "g-col",
                "game_id": "gm-col",
                "name": "跳圈圈",
            },
        ]
        for bad in bad_cases:
            with self.subTest(bad=bad):
                with self.assertRaises(ContentValidationError):
                    prepare_patch(
                        previous,
                        {"outdoor_game_slots": {"collective_1": bad}},
                        entries,
                        days,
                    )

    def test_cross_draft_manual_id_rejected(self):
        days, entries, previous = self._base()
        with self.assertRaises(ContentValidationError):
            prepare_patch(
                previous,
                {
                    "outdoor_game_slots": {
                        "collective_1": {
                            "source_kind": "manual",
                            "manual_item_id": "not-in-draft",
                            "name": "x",
                            "shared_objectives": None,
                            "guidance_points": None,
                            "focus_guidance": None,
                        }
                    }
                },
                entries,
                days,
            )

    def test_duplicate_manual_id_in_payload_rejected(self):
        days, entries, previous = self._base()
        with_manual = prepare_patch(
            previous,
            {
                "outdoor_game_slots": {
                    "collective_1": {
                        "source_kind": "manual",
                        "name": "a",
                        "shared_objectives": "1",
                        "guidance_points": "2",
                        "focus_guidance": "3",
                    }
                }
            },
            entries,
            days,
        )
        mid = with_manual["outdoor_game_slots"]["collective_1"][
            "manual_item_id"
        ]
        with self.assertRaises(ContentValidationError):
            prepare_patch(
                with_manual,
                {
                    "outdoor_game_slots": {
                        "collective_2": {
                            "source_kind": "manual",
                            "manual_item_id": mid,
                            "name": "b",
                            "shared_objectives": "1",
                            "guidance_points": "2",
                            "focus_guidance": "3",
                        }
                    }
                },
                entries,
                days,
            )

    def test_fake_daily_plan_ref_rejected(self):
        days, entries, previous = self._base()
        with self.assertRaises(ContentValidationError):
            prepare_patch(
                previous,
                {
                    "outdoor_game_slots": {
                        "collective_1": {
                            "source_kind": "daily_plan",
                            "daily_plan_id": "ghost",
                            "content_id": "c9",
                            "content_version": 1,
                            "group_id": "g-x",
                            "game_id": "gm-x",
                            "name": "ghost",
                        }
                    }
                },
                entries,
                days,
            )

    def test_manual_with_nonnull_ref_rejected(self):
        days, entries, previous = self._base()
        with self.assertRaises(ContentValidationError):
            prepare_patch(
                previous,
                {
                    "outdoor_game_slots": {
                        "collective_1": {
                            "source_kind": "manual",
                            "daily_plan_id": "plan-7",
                            "name": "x",
                            "shared_objectives": None,
                            "guidance_points": None,
                            "focus_guidance": None,
                        }
                    }
                },
                entries,
                days,
            )


class RefreshAndFactsTests(unittest.TestCase):
    def _seed_with_slot(self):
        days = _days_full()
        entries = _entries_version1()
        previous = new_content(entries, days, theme="秋")
        cand = _collective_candidate(entries)
        seeded = prepare_patch(
            previous,
            {
                "outdoor_game_slots": {
                    "collective_1": _slot_from_candidate(cand)
                },
                "focus_area": _focus_from_candidate(_focus_candidate(entries)),
                "weekly_columns": {
                    "key_week_focus": "本周重点",
                    "environment_setup": "环境",
                    "habit_culture": "习惯",
                    "home_cooperation": "家园",
                },
                "deterministic_overrides": {
                    "2026-09-07": {"morning_talk_topic": "覆盖话题"}
                },
            },
            entries,
            days,
        )
        return days, entries, seeded

    def test_refresh_updates_both_sides_audit_and_keeps_manual_regions(self):
        days, entries, seeded = self._seed_with_slot()
        old_slot = seeded["outdoor_game_slots"]["collective_1"]
        new_entries = [
            _entry(
                7,
                content_id="c7b",
                version=3,
                adopted=_adopted_full(collective_name="跳圈圈新文本"),
            )
        ]
        refreshed, audit = refresh_content(seeded, new_entries, days)
        new_slot = refreshed["outdoor_game_slots"]["collective_1"]
        self.assertEqual(new_slot["content_version"], 3)
        self.assertEqual(new_slot["name"], "跳圈圈新文本")
        self.assertEqual(refreshed["theme"], "秋")
        self.assertEqual(
            refreshed["deterministic"][0]["override"]["morning_talk_topic"],
            "覆盖话题",
        )
        self.assertEqual(
            refreshed["weekly_columns"]["key_week_focus"], "本周重点"
        )
        det_audit = [
            a
            for a in audit
            if a.get("slot") == "deterministic" and a.get("date") == "2026-09-07"
        ]
        self.assertTrue(det_audit)
        self.assertEqual(det_audit[0]["from"]["content_version"], 1)
        self.assertEqual(det_audit[0]["to"]["content_version"], 3)
        self.assertEqual(det_audit[0]["from"]["daily_plan_id"], "plan-7")
        self.assertEqual(det_audit[0]["to"]["daily_plan_id"], "plan-7")
        slot_audit = [
            a for a in audit if a.get("slot") == "collective_1"
        ]
        self.assertTrue(slot_audit)
        self.assertEqual(slot_audit[0]["from"]["content_version"], 1)
        self.assertEqual(slot_audit[0]["to"]["content_version"], 3)

    def test_refresh_vanished_keeps_old_and_marks_missing_stale(self):
        days, entries, seeded = self._seed_with_slot()
        old_slot = copy.deepcopy(
            seeded["outdoor_game_slots"]["collective_1"]
        )
        refreshed, audit = refresh_content(seeded, [], days)
        self.assertEqual(
            refreshed["outdoor_game_slots"]["collective_1"], old_slot
        )
        missing_audits = [
            a
            for a in audit
            if a.get("kind") == "missing_facts"
            and a.get("slot") == "collective_1"
        ]
        self.assertTrue(missing_audits)
        self.assertFalse(missing_audits[0]["current_item_exists"])
        self.assertIsNone(missing_audits[0]["to"])

    def test_refresh_deterministic_null_to_real_audit(self):
        days = {date(2026, 9, 8): "teaching"}
        previous = new_content([], days, theme="t")
        row = previous["deterministic"][0]
        self.assertEqual(row["plan_state"], "no_plan")
        entries = [
            _entry(
                8, content_id="c8", version=1, adopted=_adopted_full()
            )
        ]
        refreshed, audit = refresh_content(previous, entries, days)
        self.assertEqual(refreshed["deterministic"][0]["plan_state"], "saved")
        det = [
            a
            for a in audit
            if a.get("slot") == "deterministic"
            and a.get("date") == "2026-09-08"
        ]
        self.assertEqual(len(det), 1)
        self.assertIsNone(det[0]["from"]["daily_plan_id"])
        self.assertEqual(det[0]["to"]["daily_plan_id"], "plan-8")

    def test_facts_null_to_real_stale_and_missing_empty_fields(self):
        days = {date(2026, 9, 8): "teaching"}
        previous = new_content([], days, theme="")
        entries = [
            _entry(
                8, content_id="c8", version=1, adopted=_adopted_full()
            )
        ]
        facts = build_facts(previous, entries, days)
        kinds = {m["kind"] for m in facts["missing"]}
        self.assertIn("empty_theme", kinds)
        self.assertIn("empty_field", kinds)
        self.assertIn("outdoor_slot", kinds)
        self.assertIn("materials", kinds)
        self.assertIn("empty_field", kinds)  # focus_area empty + columns
        stale = [
            s
            for s in facts["stale_sources"]
            if s.get("slot") == "deterministic"
            and s.get("date") == "2026-09-08"
        ]
        self.assertEqual(len(stale), 1)
        self.assertIsNone(stale[0]["draft"]["daily_plan_id"])
        self.assertEqual(stale[0]["current"]["daily_plan_id"], "plan-8")
        self.assertEqual(stale[0]["draft"]["content_version"], None)
        self.assertEqual(stale[0]["current"]["content_version"], 1)
        self.assertTrue(stale[0]["current_item_exists"])

    def test_facts_missing_daily_plan_date_and_rest_not_missing_date(self):
        days = _days_full()
        entries = _entries_version1()
        content = new_content(entries, days, theme="t")
        facts = build_facts(content, entries, days)
        missing_dates = [
            m
            for m in facts["missing"]
            if m.get("kind") == "missing_daily_plan_date"
        ]
        self.assertEqual(
            {m["date"] for m in missing_dates},
            {"2026-09-08", "2026-09-10", "2026-09-11"},
        )
        self.assertFalse(
            any(m.get("date") == "2026-09-09" for m in missing_dates)
        )

    def test_facts_manual_not_stale_but_empty_content_is_missing(self):
        days, entries, seeded = self._seed_with_slot()
        manual = prepare_patch(
            seeded,
            {
                "outdoor_game_slots": {
                    "collective_1": {
                        "source_kind": "manual",
                        "manual_item_id": seeded["outdoor_game_slots"][
                            "collective_1"
                        ]["manual_item_id"],
                        "name": "手工游戏",
                        "shared_objectives": "",
                        "guidance_points": "",
                        "focus_guidance": "",
                    },
                    "collective_2": {
                        "source_kind": "manual",
                        "name": "另一个手工",
                        "shared_objectives": "so",
                        "guidance_points": "gp",
                        "focus_guidance": "fg",
                    },
                }
            },
            entries,
            days,
        )
        # Note: same manual id cannot occupy two slots; do single-slot patch.
        manual = prepare_patch(
            seeded,
            {
                "outdoor_game_slots": {
                    "collective_1": {
                        "source_kind": "manual",
                        "manual_item_id": seeded["outdoor_game_slots"][
                            "collective_1"
                        ]["manual_item_id"],
                        "name": "手工游戏",
                        "shared_objectives": "",
                        "guidance_points": "",
                        "focus_guidance": "",
                    }
                }
            },
            entries,
            days,
        )
        facts = build_facts(manual, entries, days)
        manual_stale = [
            s for s in facts["stale_sources"] if s.get("slot") == "collective_1"
        ]
        self.assertEqual(manual_stale, [])
        manual_empty = [
            m
            for m in facts["missing"]
            if m.get("slot") == "collective_1"
            and m.get("kind") == "empty_field"
        ]
        self.assertTrue(manual_empty)
        self.assertTrue(
            any(m.get("field") == "shared_objectives" for m in manual_empty)
        )

    def test_facts_vanished_slot_missing_and_stale_both(self):
        days, entries, seeded = self._seed_with_slot()
        facts = build_facts(seeded, [], days)
        slot_missing = [
            m
            for m in facts["missing"]
            if m.get("slot") == "collective_1"
            and m.get("kind") == "source_missing"
        ]
        self.assertTrue(slot_missing)
        slot_stale = [
            s
            for s in facts["stale_sources"]
            if s.get("slot") == "collective_1"
        ]
        self.assertEqual(len(slot_stale), 1)
        self.assertFalse(slot_stale[0]["current_item_exists"])
        self.assertEqual(
            slot_stale[0]["draft"]["content_version"],
            seeded["outdoor_game_slots"]["collective_1"]["content_version"],
        )
        self.assertIsNone(slot_stale[0]["current"]["content_id"])

    def test_facts_fresh_source_has_no_stale(self):
        days, entries, seeded = self._seed_with_slot()
        facts = build_facts(seeded, entries, days)
        # collective_1 and focus are fresh against current entries.
        self.assertFalse(
            any(
                s.get("slot") in ("collective_1", "focus_area")
                for s in facts["stale_sources"]
            )
        )
        # deterministic 09-07 is fresh (same content_version).
        self.assertFalse(
            any(
                s.get("slot") == "deterministic"
                and s.get("date") == "2026-09-07"
                for s in facts["stale_sources"]
            )
        )

    def test_facts_rejects_focus_manual_before_manual_branch(self):
        days, entries, seeded = self._seed_with_slot()
        bad = copy.deepcopy(seeded)
        bad["focus_area"] = {
            "source_kind": "manual",
            "manual_item_id": "m1",
            "name": "x",
        }
        with self.assertRaises(ContentValidationError):
            build_facts(bad, entries, days)

    def test_facts_rejects_non_string_source_kind_without_typeerror(self):
        days, entries, seeded = self._seed_with_slot()
        bad = copy.deepcopy(seeded)
        bad["outdoor_game_slots"]["collective_2"] = {"source_kind": ["x"]}
        with self.assertRaises(ContentValidationError):
            build_facts(bad, entries, days)

    def test_facts_do_not_accept_input_facts_argument(self):
        import inspect

        sig = inspect.signature(build_facts)
        self.assertEqual(
            list(sig.parameters), ["content", "entries", "days"]
        )

    def test_deepcopy_previous_not_mutated(self):
        days, entries, seeded = self._seed_with_slot()
        snapshot = copy.deepcopy(seeded)
        new_entries = [
            _entry(
                7,
                content_id="c7b",
                version=9,
                adopted=_adopted_full(collective_name="变"),
            )
        ]
        refreshed, _ = refresh_content(seeded, new_entries, days)
        self.assertEqual(seeded, snapshot)
        self.assertNotEqual(
            refreshed["outdoor_game_slots"]["collective_1"]["content_version"],
            seeded["outdoor_game_slots"]["collective_1"]["content_version"],
        )
        # Mutating returned content must not touch previous.
        refreshed["outdoor_game_slots"]["collective_1"]["name"] = "mutated"
        self.assertEqual(
            seeded["outdoor_game_slots"]["collective_1"]["name"], "跳圈圈"
        )


def old_content_id(selected: dict):
    return selected["outdoor_game_slots"]["collective_1"]["content_id"]


if __name__ == "__main__":
    unittest.main()
