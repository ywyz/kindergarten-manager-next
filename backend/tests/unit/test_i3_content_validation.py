"""No-DB tests for I3 adopted_content structure validation and ID rules."""

import unittest

from app.services.daily_plan_content import (
    ContentValidationError,
    collect_identity_sets,
    parse_adopted_content,
    prepare_content,
)


class StructureTests(unittest.TestCase):
    def test_empty_object_is_allowed_and_stays_empty(self):
        self.assertEqual(prepare_content({}), {})

    def test_non_object_payload_rejected(self):
        for bad in ([], "x", 5, None, True):
            with self.subTest(bad=bad):
                with self.assertRaises(ContentValidationError):
                    prepare_content(bad)

    def test_unknown_top_level_field_rejected(self):
        with self.assertRaises(ContentValidationError):
            prepare_content({"reflection": "", "extra": 1})
        with self.assertRaises(ContentValidationError):
            prepare_content({"morning_talk": {"topic": "", "bogus": ""}})

    def test_no_default_fields_are_filled_in(self):
        result = prepare_content({"reflection": "今天很开心"})
        self.assertEqual(result, {"reflection": "今天很开心"})

    def test_explicit_null_sections_are_dropped_not_filled(self):
        result = prepare_content(
            {"morning_talk": None, "reflection": ""}
        )
        self.assertEqual(result, {"reflection": ""})

    def test_text_fields_may_be_empty_strings(self):
        result = prepare_content(
            {
                "morning_talk": {"topic": "", "questions": ""},
                "group_activity": {"theme": ""},
            }
        )
        self.assertEqual(
            result,
            {
                "morning_talk": {"topic": "", "questions": ""},
                "group_activity": {"theme": ""},
            },
        )

    def test_morning_group_kind_must_be_known(self):
        with self.assertRaises(ContentValidationError):
            prepare_content(
                {"morning_games": [{"group_kind": "free", "games": []}]}
            )

    def test_morning_allows_at_most_one_group_per_kind(self):
        ok = prepare_content(
            {
                "morning_games": [
                    {"group_kind": "collective", "games": []},
                    {"group_kind": "free_choice", "games": []},
                ]
            }
        )
        self.assertEqual(len(ok["morning_games"]), 2)

        with self.assertRaises(ContentValidationError):
            prepare_content(
                {
                    "morning_games": [
                        {"group_kind": "collective", "games": []},
                        {"group_kind": "collective", "games": []},
                    ]
                }
            )
        with self.assertRaises(ContentValidationError):
            prepare_content(
                {
                    "morning_games": [
                        {"group_kind": "free_choice", "games": []},
                        {"group_kind": "free_choice", "games": []},
                    ]
                }
            )

    def test_empty_arrays_are_allowed(self):
        result = prepare_content(
            {
                "morning_games": [],
                "post_group_games": [],
            }
        )
        self.assertEqual(result["morning_games"], [])
        self.assertEqual(result["post_group_games"], [])

    def test_game_requires_name(self):
        with self.assertRaises(ContentValidationError):
            prepare_content(
                {"morning_games": [{"group_kind": "collective", "games": [{}]}]}
            )

    def test_unknown_group_kind_on_post_group_rejected(self):
        with self.assertRaises(ContentValidationError):
            prepare_content(
                {
                    "post_group_games": [
                        {"group_kind": "collective", "games": []}
                    ]
                }
            )

    def test_post_group_requires_context_kind_enum(self):
        with self.assertRaises(ContentValidationError):
            prepare_content(
                {"post_group_games": [{"area": "建构区", "games": []}]}
            )
        with self.assertRaises(ContentValidationError):
            prepare_content(
                {
                    "post_group_games": [
                        {
                            "context_kind": "indoor",
                            "area": "建构区",
                            "games": [],
                        }
                    ]
                }
            )
        for kind in ("area", "outdoor", "special_room"):
            with self.subTest(context_kind=kind):
                result = prepare_content(
                    {
                        "post_group_games": [
                            {
                                "context_kind": kind,
                                "area": "建构区",
                                "games": [{"name": "积木"}],
                            }
                        ]
                    }
                )
                self.assertEqual(
                    result["post_group_games"][0]["context_kind"], kind
                )

    def test_afternoon_uses_observation_focus_and_rejects_old_field(self):
        result = prepare_content(
            {
                "afternoon_outdoor": {
                    "area": "操场",
                    "observation_focus": "排队安全",
                    "games": [{"name": "皮球"}],
                }
            }
        )
        self.assertEqual(
            result["afternoon_outdoor"]["observation_focus"], "排队安全"
        )
        self.assertNotIn("focus_guidance", result["afternoon_outdoor"])

        with self.assertRaises(ContentValidationError):
            prepare_content(
                {
                    "afternoon_outdoor": {
                        "focus_guidance": "旧字段",
                        "games": [],
                    }
                }
            )

    def test_post_group_keeps_focus_guidance_distinct_from_afternoon(self):
        result = prepare_content(
            {
                "post_group_games": [
                    {
                        "context_kind": "outdoor",
                        "focus_guidance": "重点指导",
                        "games": [],
                    }
                ],
                "afternoon_outdoor": {
                    "observation_focus": "重点观察",
                    "games": [],
                },
            }
        )
        self.assertEqual(
            result["post_group_games"][0]["focus_guidance"], "重点指导"
        )
        self.assertNotIn("observation_focus", result["post_group_games"][0])
        self.assertNotIn(
            "focus_guidance", result["afternoon_outdoor"]
        )


class IdentityTests(unittest.TestCase):
    def _morning(self, group_id=None, game_id=None, name="跳绳"):
        group = {"group_kind": "collective", "games": [{"name": name}]}
        if group_id is not None:
            group["group_id"] = group_id
        if game_id is not None:
            group["games"][0]["game_id"] = game_id
        return {"morning_games": [group]}

    def test_create_rejects_client_supplied_ids(self):
        with self.assertRaises(ContentValidationError):
            prepare_content(self._morning(group_id="client-group"))
        with self.assertRaises(ContentValidationError):
            prepare_content(self._morning(game_id="client-game"))

    def test_create_generates_ids_for_new_objects(self):
        result = prepare_content(self._morning())
        group = result["morning_games"][0]
        self.assertTrue(group["group_id"])
        self.assertTrue(group["games"][0]["game_id"])
        self.assertEqual(group["games"][0]["name"], "跳绳")

    def test_update_preserves_existing_ids(self):
        first = prepare_content(self._morning())
        group_id = first["morning_games"][0]["group_id"]
        game_id = first["morning_games"][0]["games"][0]["game_id"]

        again = prepare_content(
            self._morning(group_id=group_id, game_id=game_id, name="新名字"),
            allowed_group_ids=frozenset({group_id}),
            allowed_game_ids=frozenset({game_id}),
        )
        self.assertEqual(again["morning_games"][0]["group_id"], group_id)
        self.assertEqual(again["morning_games"][0]["games"][0]["game_id"], game_id)
        self.assertEqual(again["morning_games"][0]["games"][0]["name"], "新名字")

    def test_update_rejects_unknown_or_cross_plan_ids(self):
        with self.assertRaises(ContentValidationError):
            prepare_content(
                self._morning(group_id="foreign-group", game_id="g1"),
                allowed_group_ids=frozenset({"mine"}),
                allowed_game_ids=frozenset({"g1"}),
            )
        with self.assertRaises(ContentValidationError):
            prepare_content(
                self._morning(group_id="mine", game_id="foreign-game"),
                allowed_group_ids=frozenset({"mine"}),
                allowed_game_ids=frozenset(),
            )

    def test_duplicate_ids_rejected_within_payload(self):
        group_id, game_id = "gA", "m1"
        payload = {
            "morning_games": [
                {
                    "group_id": group_id,
                    "group_kind": "collective",
                    "games": [{"game_id": game_id, "name": "a"}],
                },
                {
                    "group_id": group_id,
                    "group_kind": "free_choice",
                    "games": [{"game_id": game_id, "name": "b"}],
                },
            ]
        }
        with self.assertRaises(ContentValidationError):
            prepare_content(
                payload,
                allowed_group_ids=frozenset({group_id}),
                allowed_game_ids=frozenset({game_id}),
            )

    def test_new_object_alongside_kept_object_generates_only_missing(self):
        base = prepare_content(self._morning())
        group_id = base["morning_games"][0]["group_id"]
        game_id = base["morning_games"][0]["games"][0]["game_id"]

        payload = {
            "morning_games": [
                {
                    "group_id": group_id,
                    "group_kind": "collective",
                    "games": [
                        {"game_id": game_id, "name": "kept"},
                        {"name": "brand-new"},
                    ],
                }
            ]
        }
        result = prepare_content(
            payload,
            allowed_group_ids=frozenset({group_id}),
            allowed_game_ids=frozenset({game_id}),
        )
        games = result["morning_games"][0]["games"]
        self.assertEqual(games[0]["game_id"], game_id)
        self.assertNotEqual(games[1]["game_id"], game_id)
        self.assertTrue(games[1]["game_id"])

    def test_afternoon_outdoor_ids_assigned(self):
        result = prepare_content(
            {"afternoon_outdoor": {"area": "操场", "games": [{"name": "皮球"}]}}
        )
        self.assertTrue(result["afternoon_outdoor"]["group_id"])
        self.assertTrue(result["afternoon_outdoor"]["games"][0]["game_id"])

    def test_collect_identity_sets_roundtrip(self):
        prepared = prepare_content(
            {
                "morning_games": [
                    {
                        "group_kind": "collective",
                        "games": [{"name": "a"}, {"name": "b"}],
                    }
                ],
                "post_group_games": [
                    {
                        "context_kind": "area",
                        "area": "建构区",
                        "games": [{"name": "c"}],
                    }
                ],
                "afternoon_outdoor": {
                    "games": [{"name": "d"}],
                    "observation_focus": "观察",
                },
            }
        )
        groups, games = collect_identity_sets(prepared)
        self.assertEqual(len(groups), 3)
        self.assertEqual(len(games), 4)
        self.assertIn(prepared["morning_games"][0]["group_id"], groups)
        self.assertIn(
            prepared["afternoon_outdoor"]["games"][0]["game_id"], games
        )

    def test_collect_identity_sets_handles_empty_and_null(self):
        self.assertEqual(
            collect_identity_sets(None), (frozenset(), frozenset())
        )
        self.assertEqual(
            collect_identity_sets({}), (frozenset(), frozenset())
        )

    def test_parse_does_not_mutate_payload(self):
        payload = {"morning_games": [{"group_kind": "collective", "games": []}]}
        snapshot = repr(payload)
        model = parse_adopted_content(payload)
        self.assertEqual(repr(payload), snapshot)
        self.assertEqual(len(model.morning_games), 1)


if __name__ == "__main__":
    unittest.main()
