"""Pure listening goal-suggestion contract and projection tests."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.local import listening_ai_adoption as adoption
from app.local import listening_ai_contracts as contracts
from app.local import listening_ai_inputs as inputs
from app.local.errors import LocalValidationError


def _photo(position: int) -> dict:
    return {
        "asset_id": f"asset-{position}",
        "group_id": f"group-{position}",
        "position": position,
        "source_hash": "a" * 64,
        "work_hash": str(position + 1) * 64,
        "mime_type": "image/png",
        "width": 10,
        "height": 20,
        "orientation": None,
        "rotation_quarters": 0,
        "source_bytes": 100,
        "work_bytes": 80,
    }


def _groups() -> list[dict]:
    return [
        {
            "group_id": "group-0",
            "position": 0,
            "work_date": "2026-12-01",
            "listening_text": "第一组教师文字",
            "asset_id": None,
        },
        {
            "group_id": "group-1",
            "position": 1,
            "work_date": "2026-12-02",
            "listening_text": None,
            "asset_id": "asset-1",
        },
        {
            "group_id": "group-2",
            "position": 2,
            "work_date": None,
            "listening_text": "第三组教师文字",
            "asset_id": "asset-2",
        },
    ]


def _domain(groups: list[dict], goal: str | None = "原目标") -> dict:
    return {
        "domain": "health",
        "domain_label": "健康",
        "template_version": "v1",
        "template_sha256": "a" * 64,
        "observation_date": "2026-12",
        "adult_count": None,
        "child_age": None,
        "goal": goal,
        "observation_area": "旧区域",
        "overall_evaluation": None,
        "support_strategy": None,
        "groups": groups,
        "evaluation": [],
    }


def _item() -> dict:
    return {
        "item_id": "health_1",
        "level1": "一级",
        "level2": "二级",
        "requirement": "要求",
        "standards": {"1": "一", "2": "二", "3": "三"},
    }


class GoalContractTests(unittest.TestCase):
    def test_goal_input_and_output_contract(self) -> None:
        payload = {
            "schema_version": 1,
            "mode": "goal_suggest",
            "domain": "health",
            "domain_label": "健康",
            "grade": "middle",
            "grade_label": "中班",
            "template_version": "v1",
            "template_sha256": "a" * 64,
            "goal": "原目标",
            "groups": [
                {
                    "position": 0,
                    "work_date": "2026-12-01",
                    "listening_text": "教师文字",
                    "photo": None,
                }
            ],
            "items": [_item()],
        }
        self.assertEqual(
            contracts.validate_input(contracts.TASK_GOAL, payload),
            payload,
        )
        candidate = {
            "mode": "goal_suggest",
            "goal": "观察幼儿在活动中的主动表达",
            "uncertainties": ["需核实具体情境"],
        }
        self.assertEqual(
            contracts.validate_candidate(
                contracts.TASK_GOAL, candidate
            ),
            candidate,
        )
        self.assertEqual(
            contracts.target_keys(contracts.TASK_GOAL, []), ("goal",)
        )

    def test_goal_rejects_empty_material_and_wrong_mode(self) -> None:
        base = {
            "schema_version": 1,
            "mode": "goal_suggest",
            "domain": "health",
            "domain_label": "健康",
            "grade": "middle",
            "grade_label": "中班",
            "template_version": "v1",
            "template_sha256": "a" * 64,
            "goal": None,
            "groups": [],
            "items": [_item()],
        }
        with self.assertRaises(contracts.ListeningAIContractError):
            contracts.validate_input(contracts.TASK_GOAL, base)
        empty_group = dict(
            base,
            groups=[
                {
                    "position": 0,
                    "work_date": None,
                    "listening_text": None,
                    "photo": None,
                }
            ],
        )
        with self.assertRaises(contracts.ListeningAIContractError):
            contracts.validate_input(contracts.TASK_GOAL, empty_group)
        with self.assertRaises(contracts.ListeningAIContractError):
            contracts.validate_candidate(
                contracts.TASK_GOAL,
                {
                    "mode": "group_notes",
                    "goal": "x",
                    "uncertainties": [],
                },
            )

    def test_goal_adoption_selection_only_accepts_goal_text(self) -> None:
        self.assertEqual(
            adoption._selections(
                contracts.TASK_GOAL,
                [{"target": "goal", "value": "新目标"}],
            ),
            [{"target": "goal", "value": "新目标"}],
        )
        for selections in (
            [],
            [{"target": "goal", "stars": 2}],
            [{"target": "overall_evaluation", "value": "x"}],
            [{"target": "goal", "value": "x", "extra": True}],
        ):
            with self.subTest(selections=selections):
                with self.assertRaises(LocalValidationError):
                    adoption._selections(contracts.TASK_GOAL, selections)


class GoalProjectionTests(unittest.TestCase):
    def _project(
        self,
        groups: list[dict],
        *,
        goal: str | None = "原目标",
        photos: dict[str, dict] | None = None,
    ):
        domain = _domain(groups, goal)
        dto = {
            "record_id": "record-1",
            "grade": "middle",
            "revision": 4,
            "domains": [domain],
        }
        template = SimpleNamespace(
            version="v1", sha256="a" * 64, items=[SimpleNamespace(**_item())]
        )
        photos = photos or {}
        with (
            patch.object(
                inputs, "_load", return_value=(dto, domain, template)
            ),
            patch.object(
                inputs,
                "_read_photo_isolated",
                side_effect=lambda _runtime, **kwargs: photos[
                    kwargs["group_id"]
                ],
            ),
        ):
            return inputs.project(
                object(),
                object(),
                profile_id="p",
                record_id="record-1",
                domain="health",
                group_id=None,
                task_type=contracts.TASK_GOAL,
            )

    def test_text_only_goal_keeps_only_material_groups(self) -> None:
        groups = _groups()
        for group in groups:
            group["asset_id"] = None
        projection = self._project(groups, photos={})
        payload = projection.payload
        self.assertEqual(payload["mode"], "goal_suggest")
        self.assertEqual(payload["goal"], "原目标")
        self.assertEqual(
            [group["position"] for group in payload["groups"]],
            [0, 2],
        )
        self.assertTrue(
            all(group["photo"] is None for group in payload["groups"])
        )
        self.assertEqual(projection.dependencies["photos"], [])
        self.assertEqual(
            projection.dependencies["group_positions"], [0, 2]
        )
        self.assertEqual(
            projection.target_hashes,
            {"goal": contracts.value_hash("原目标")},
        )

    def test_photo_and_text_goal_keeps_ordered_material(self) -> None:
        groups = _groups()
        photos = {
            "group-1": _photo(1),
            "group-2": _photo(2),
        }
        projection = self._project(groups, photos=photos)
        payload = projection.payload
        self.assertEqual(
            [group["position"] for group in payload["groups"]],
            [0, 1, 2],
        )
        self.assertEqual(
            [group["photo"] is not None for group in payload["groups"]],
            [False, True, True],
        )
        self.assertEqual(
            [item["work_hash"] for item in projection.dependencies["photos"]],
            [photos["group-1"]["work_hash"], photos["group-2"]["work_hash"]],
        )
        self.assertEqual(
            contracts.validate_input(contracts.TASK_GOAL, payload), payload
        )

    def test_no_material_is_refused(self) -> None:
        groups = _groups()
        for group in groups:
            group["asset_id"] = None
            group["listening_text"] = None
        with self.assertRaises(contracts.ListeningAIContractError):
            self._project(groups, photos={})


if __name__ == "__main__":
    unittest.main()
