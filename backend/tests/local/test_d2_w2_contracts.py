"""D2 W2 frozen input/output contract: pure local validation (G06).

Fast, database-free checks of ``prompt_bundles.validate_candidate`` /
``validate_input`` plus one integration check that the package manifest hashes
equal the W1 migration seed rows. Every rule is exercised with both a positive
and a negative example, including the UTF-8 byte capacity cap and the
material-free error message.
"""

from __future__ import annotations

import unittest

from app.local import prompt_bundles as pb
from app.local.prompt_bundles import PROMPT_BUNDLE_MANIFEST
from tests.local.support import LocalTestCase, query_rows

SPLIT = {
    "group_activity": {
        "theme": "",
        "objectives": "",
        "preparation": "",
        "key_points": "",
        "difficult_points": "",
        "process": "",
    }
}


class SplitContractTests(unittest.TestCase):
    def test_six_fields_required_empty_allowed(self):
        out = pb.validate_candidate("daily_lesson_split", SPLIT)
        self.assertEqual(set(out["group_activity"]), set(SPLIT["group_activity"]))

    def test_null_and_missing_and_extra_rejected(self):
        with self.assertRaises(pb.CandidateInvalid):
            pb.validate_candidate(
                "daily_lesson_split",
                {"group_activity": {**SPLIT["group_activity"], "theme": None}},
            )
        missing = dict(SPLIT["group_activity"])
        missing.pop("theme")
        with self.assertRaises(pb.CandidateInvalid):
            pb.validate_candidate("daily_lesson_split", {"group_activity": missing})
        with self.assertRaises(pb.CandidateInvalid):
            pb.validate_candidate(
                "daily_lesson_split",
                {"group_activity": {**SPLIT["group_activity"], "reflection": "x"}},
            )
        with self.assertRaises(pb.CandidateInvalid):
            pb.validate_candidate(
                "daily_lesson_split",
                {"group_activity": {**SPLIT["group_activity"], "theme": 5}},
            )

    def test_split_input_is_strict_and_non_null(self):
        pb.validate_input(
            "daily_lesson_split", {"raw_lesson_plan": "原文", "grade": "middle"}
        )
        with self.assertRaises(pb.CandidateInvalid):
            pb.validate_input(
                "daily_lesson_split", {"raw_lesson_plan": None, "grade": "middle"}
            )
        with self.assertRaises(pb.CandidateInvalid):
            pb.validate_input("daily_lesson_split", {"raw_lesson_plan": "x"})
        with self.assertRaises(pb.CandidateInvalid):
            pb.validate_input(
                "daily_lesson_split",
                {"raw_lesson_plan": "x", "grade": "middle", "extra": 1},
            )


class AdaptContractTests(unittest.TestCase):
    def test_only_process(self):
        self.assertEqual(
            pb.validate_candidate("daily_process_adapt", {"process": ""}),
            {"process": ""},
        )
        with self.assertRaises(pb.CandidateInvalid):
            pb.validate_candidate("daily_process_adapt", {"process": None})
        with self.assertRaises(pb.CandidateInvalid):
            pb.validate_candidate(
                "daily_process_adapt", {"process": "x", "theme": "y"}
            )

    def test_adapt_input(self):
        pb.validate_input(
            "daily_process_adapt", {"process_source": "", "grade": "small"}
        )
        with self.assertRaises(pb.CandidateInvalid):
            pb.validate_input(
                "daily_process_adapt", {"process_source": None, "grade": "small"}
            )


def morning_collective(name="A") -> dict:
    return {"group_kind": "collective", "games": [{"name": name}]}


def morning_free(name="B") -> dict:
    return {"group_kind": "free_choice", "games": [{"name": name}]}


class OtherContractTests(unittest.TestCase):
    def test_at_least_one_board(self):
        with self.assertRaises(pb.CandidateInvalid):
            pb.validate_candidate("daily_other_activities", {})
        out = pb.validate_candidate(
            "daily_other_activities",
            {"morning_talk": {"topic": "t", "questions": "q"}},
        )
        # Omitted optional boards stay omitted (never fabricated as null/"").
        self.assertEqual(set(out), {"morning_talk"})

    def test_morning_exactly_one_each_with_one_game(self):
        ok = pb.validate_candidate(
            "daily_other_activities",
            {
                "morning_games": [morning_collective(), morning_free()],
                "morning_talk": {"topic": "t", "questions": "q"},
            },
        )
        self.assertEqual(
            sorted(g["group_kind"] for g in ok["morning_games"]),
            ["collective", "free_choice"],
        )
        # Two of the same kind.
        with self.assertRaises(pb.CandidateInvalid):
            pb.validate_candidate(
                "daily_other_activities",
                {"morning_games": [morning_collective("A"), morning_collective("B")]},
            )
        # Two games inside one morning group.
        two_games = {
            "group_kind": "collective",
            "games": [{"name": "A"}, {"name": "B"}],
        }
        with self.assertRaises(pb.CandidateInvalid):
            pb.validate_candidate(
                "daily_other_activities",
                {"morning_games": [two_games, morning_free()]},
            )
        # Only one kind present.
        with self.assertRaises(pb.CandidateInvalid):
            pb.validate_candidate(
                "daily_other_activities", {"morning_games": [morning_collective()]}
            )

    def test_shared_text_preserved_and_no_ids(self):
        group = {
            "group_kind": "collective",
            "games": [{"name": "A"}],
            "shared_objectives": "共同目标",
            "guidance_points": "共同指导",
        }
        out = pb.validate_candidate(
            "daily_other_activities",
            {"morning_games": [group, morning_free()]},
        )
        collective = next(
            g for g in out["morning_games"] if g["group_kind"] == "collective"
        )
        self.assertEqual(collective["shared_objectives"], "共同目标")
        self.assertEqual(collective["guidance_points"], "共同指导")
        with self.assertRaises(pb.CandidateInvalid):
            pb.validate_candidate(
                "daily_other_activities",
                {
                    "morning_games": [
                        {**group, "group_id": "g1"},
                        morning_free(),
                    ]
                },
            )

    def test_explicit_null_rejected_but_omitted_ok(self):
        with self.assertRaises(pb.CandidateInvalid):
            pb.validate_candidate(
                "daily_other_activities",
                {"morning_talk": None, "afternoon_outdoor": {"games": [{"name": "A"}]}},
            )
        with self.assertRaises(pb.CandidateInvalid):
            pb.validate_candidate(
                "daily_other_activities",
                {"afternoon_outdoor": {"games": [{"name": "A"}], "area": None}},
            )
        ok = pb.validate_candidate(
            "daily_other_activities",
            {"afternoon_outdoor": {"games": [{"name": "A"}]}},
        )
        self.assertNotIn("area", ok["afternoon_outdoor"])

    def test_capacity_limits(self):
        # Single string cap.
        with self.assertRaises(pb.CandidateInvalid):
            pb.validate_candidate(
                "daily_lesson_split",
                {
                    "group_activity": {
                        **SPLIT["group_activity"],
                        "process": "x" * 100001,
                    }
                },
            )
        # Array cap.
        with self.assertRaises(pb.CandidateInvalid):
            pb.validate_candidate(
                "daily_other_activities",
                {
                    "post_group_games": [
                        {"context_kind": "area", "games": [{"name": "A"}]}
                        for _ in range(101)
                    ]
                },
            )
        # UTF-8 byte cap: six 100000-char CJK fields exceed 1 MiB bytes while
        # each field is within its character limit.
        big = "中" * 100000
        with self.assertRaises(pb.CandidateInvalid):
            pb.validate_candidate(
                "daily_lesson_split",
                {
                    "group_activity": {
                        "theme": big,
                        "objectives": big,
                        "preparation": big,
                        "key_points": big,
                        "difficult_points": big,
                        "process": big,
                    }
                },
            )

    def test_error_message_never_contains_material(self):
        material = "SECRET_MATERIAL_ABC"
        with self.assertRaises(pb.CandidateInvalid) as ctx:
            pb.validate_candidate(
                "daily_lesson_split",
                {
                    "group_activity": {
                        **SPLIT["group_activity"],
                        "theme": material,
                        "objectives": 3,
                    }
                },
            )
        self.assertNotIn(material, str(ctx.exception))
        # The raw Pydantic error (which carries input_value) is not chained.
        self.assertIsNone(ctx.exception.__cause__)


class OtherInputContractTests(unittest.TestCase):
    def _valid(self) -> dict:
        return {
            "plan_date": "2026-09-02",
            "week_number": 1,
            "calendar_context": {
                "effective_state": "teaching",
                "weekday": 3,
                "holiday_context": [{"date": "2026-09-02", "name": "节日"}],
            },
            "game_config": None,
            "daily_plan_snapshot": {
                "group_activity": {
                    "theme": "",
                    "objectives": None,
                    "preparation": None,
                    "key_points": None,
                    "difficult_points": None,
                    "process": None,
                },
                "morning_games": None,
                "morning_talk": None,
                "post_group_games": None,
                "afternoon_outdoor": None,
            },
            "target_grade": "middle",
        }

    def test_manual_input_allows_empty_and_null(self):
        out = pb.validate_input("daily_other_activities", self._valid())
        self.assertIsNone(out["game_config"])
        self.assertIsNone(out["daily_plan_snapshot"]["group_activity"]["objectives"])

    def test_required_top_level_keys_and_unknown_rejected(self):
        payload = self._valid()
        payload.pop("calendar_context")
        with self.assertRaises(pb.CandidateInvalid):
            pb.validate_input("daily_other_activities", payload)
        bad = self._valid()
        bad["name"] = "x"
        with self.assertRaises(pb.CandidateInvalid):
            pb.validate_input("daily_other_activities", bad)

    def test_bad_date_and_week_rejected(self):
        bad = self._valid()
        bad["plan_date"] = "not-a-date"
        with self.assertRaises(pb.CandidateInvalid):
            pb.validate_input("daily_other_activities", bad)
        bad = self._valid()
        bad["week_number"] = 0
        with self.assertRaises(pb.CandidateInvalid):
            pb.validate_input("daily_other_activities", bad)

    def test_morning_input_group_counts_at_most_one_per_kind(self):
        def with_groups(groups):
            payload = self._valid()
            payload["daily_plan_snapshot"]["morning_games"] = groups
            return payload

        # Legal: null (default), empty list, a single kind, one of each.
        pb.validate_input("daily_other_activities", self._valid())
        pb.validate_input("daily_other_activities", with_groups([]))
        pb.validate_input(
            "daily_other_activities",
            with_groups([{"group_kind": "collective", "games": []}]),
        )
        pb.validate_input(
            "daily_other_activities",
            with_groups(
                [
                    {"group_kind": "collective", "games": []},
                    {"group_kind": "free_choice", "games": []},
                ]
            ),
        )
        # Illegal: two of the same kind (even with empty games).
        with self.assertRaises(pb.CandidateInvalid):
            pb.validate_input(
                "daily_other_activities",
                with_groups(
                    [
                        {"group_kind": "collective", "games": []},
                        {"group_kind": "collective", "games": []},
                    ]
                ),
            )
        with self.assertRaises(pb.CandidateInvalid):
            pb.validate_input(
                "daily_other_activities",
                with_groups(
                    [
                        {"group_kind": "free_choice", "games": []},
                        {"group_kind": "free_choice", "games": []},
                    ]
                ),
            )


class BundleSeedTests(LocalTestCase):
    def test_manifest_hashes_equal_migration_seed(self):
        runtime = self.make_runtime()
        self.initialize_profile(runtime)
        rows = query_rows(
            runtime.db_path,
            "SELECT task_type, contract_version, default_revision, bundle_hash "
            "FROM local_prompt_bundles WHERE task_type LIKE 'daily_%' "
            "ORDER BY task_type",
        )
        self.assertEqual(len(rows), 7)
        observation_rows = query_rows(
            runtime.db_path,
            "SELECT task_type, contract_version, default_revision, bundle_hash "
            "FROM local_prompt_bundles WHERE task_type LIKE 'game_observation_%' "
            "ORDER BY task_type",
        )
        self.assertEqual(len(observation_rows), 2)
        manifest = {
            (b["task_type"], b["contract_version"], b["default_revision"]): b[
                "bundle_hash"
            ]
            for b in PROMPT_BUNDLE_MANIFEST
        }
        for row in rows:
            self.assertEqual(
                row["bundle_hash"],
                manifest[
                    (row["task_type"], row["contract_version"], row["default_revision"])
                ],
            )
        r1 = [r for r in rows if r["default_revision"] == 1]
        r2 = [r for r in rows if r["default_revision"] == 2]
        r3 = [r for r in rows if r["default_revision"] == 3]
        self.assertEqual(len(r1), 3)
        self.assertEqual(len(r2), 3)
        self.assertEqual(len(r3), 1)
        self.assertEqual(r3[0]["task_type"], "daily_process_adapt")

    def initialize_profile(self, runtime) -> None:
        from app.local import profile_service
        from app.local.normalize import normalize_initialization
        from tests.local.support import initialize_body

        session = runtime.session()
        try:
            profile_service.initialize(
                session, normalize_initialization(**initialize_body())
            )
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
