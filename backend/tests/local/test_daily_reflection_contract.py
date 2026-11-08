"""#27 daily reflection pure contract tests (no database, no network)."""

from __future__ import annotations

import json
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from app.local import ai_candidates, ai_inputs, prompt_bundles
from app.local.ai_adoption import _merge, _warnings
from app.local.prompt_bundles import CandidateInvalid, validate_candidate, validate_input

MATERIALS = "幼儿分成四组用纸杯搭桥；两组成功，一组反复倒塌后改用宽底座。"


def saved_content() -> dict:
    return {
        "group_activity": {
            "theme": "纸杯搭桥",
            "objectives": "尝试让桥面保持稳定",
            "preparation": "纸杯、纸板",
            "key_points": "底座要稳",
            "difficult_points": "连接处容易倒",
            "process": "1. 导入\n师：今天搭桥。\n2. 操作",
        },
        "reflection": "旧反思：活动尚未开展。",
    }


def payload() -> dict:
    return {
        "plan_date": "2026-11-08",
        "week_number": 3,
        "weekday": 6,
        "target_grade": "middle",
        "plan_snapshot": {"group_activity": saved_content()["group_activity"]},
        "implementation_materials": MATERIALS,
    }


class ReflectionContractTests(unittest.TestCase):
    def test_bundle_registered_and_old_three_remain_present(self):
        self.assertIn("daily_reflection_generate", prompt_bundles.TASK_TYPES)
        entries = {
            (bundle["task_type"], bundle["contract_version"], bundle["default_revision"])
            for bundle in prompt_bundles.PROMPT_BUNDLE_MANIFEST
        }
        self.assertIn(("daily_lesson_split", 1, 1), entries)
        self.assertIn(("daily_process_adapt", 1, 1), entries)
        self.assertIn(("daily_other_activities", 1, 1), entries)
        reflection = [
            bundle
            for bundle in prompt_bundles.PROMPT_BUNDLE_MANIFEST
            if bundle["task_type"] == "daily_reflection_generate"
        ]
        self.assertEqual(len(reflection), 1)
        self.assertEqual(set(reflection[0]["guidance_defaults_json"]), {"reflection"})

    def test_input_requires_materials_and_separates_plan(self):
        clean = validate_input("daily_reflection_generate", payload())
        self.assertEqual(clean["implementation_materials"], MATERIALS)
        self.assertIn("plan_snapshot", clean)
        with self.assertRaises(CandidateInvalid):
            validate_input(
                "daily_reflection_generate",
                {**payload(), "implementation_materials": ""},
            )
        with self.assertRaises(CandidateInvalid):
            validate_input(
                "daily_reflection_generate",
                {**payload(), "candidate_id": "internal"},
            )

    def test_output_is_only_reflection(self):
        clean = validate_candidate(
            "daily_reflection_generate", {"reflection": "新增反思正文"}
        )
        self.assertEqual(clean, {"reflection": "新增反思正文"})
        with self.assertRaises(CandidateInvalid):
            validate_candidate(
                "daily_reflection_generate",
                {"reflection": "正文", "group_activity": {}},
            )

    def test_projection_uses_saved_plan_and_materials_not_old_reflection(self):
        plan = SimpleNamespace(
            id="plan-1",
            plan_date=date(2026, 11, 8),
            week_number=3,
            weekday=6,
            class_id="class-1",
        )
        content = SimpleNamespace(
            version=7,
            adopted_content=saved_content(),
        )
        projected = ai_inputs.project_input(
            SimpleNamespace(),
            plan=plan,
            content=content,
            task_type="daily_reflection_generate",
            target_grade="middle",
            implementation_materials=MATERIALS,
        )
        self.assertEqual(
            projected.payload,
            {
                "plan_date": "2026-11-08",
                "week_number": 3,
                "weekday": 6,
                "target_grade": "middle",
                "plan_snapshot": {"group_activity": saved_content()["group_activity"]},
                "implementation_materials": MATERIALS,
            },
        )
        self.assertEqual(
            set(projected.dependencies),
            {
                "plan_date",
                "week_number",
                "weekday",
                "target_grade",
                "plan_snapshot",
                "implementation_materials",
            },
        )
        self.assertNotIn("旧反思", json.dumps(projected.payload, ensure_ascii=False))
        self.assertNotIn("reflection", projected.payload)

    def test_reflection_target_and_merge(self):
        self.assertEqual(
            ai_candidates.available_targets(
                "daily_reflection_generate", {"reflection": "候选反思"}
            ),
            ["reflection"],
        )
        content = SimpleNamespace(adopted_content=saved_content())
        merged = _merge(
            content,
            "daily_reflection_generate",
            ["reflection"],
            {"reflection": "候选反思"},
        )
        self.assertEqual(merged["reflection"], "候选反思")
        self.assertEqual(
            merged["group_activity"]["process"], saved_content()["group_activity"]["process"]
        )
        self.assertIn(
            "反思为空字符串",
            "；".join(_warnings("daily_reflection_generate", {"reflection": ""}, ["reflection"])),
        )

    def test_0014_is_static_successor_of_0013_with_reflection_checks(self):
        path = (
            Path(__file__).resolve().parents[2]
            / "migrations_local"
            / "versions"
            / "20261108_0014_local_reflection_ai.py"
        )
        source = path.read_text(encoding="utf-8")
        self.assertIn('down_revision: Union[str, None] = "20261108_0013_local_todos"', source)
        self.assertIn('REFLECTION_TASKS = "\'daily_reflection_generate\'"', source)
        self.assertGreaterEqual(source.count("'daily_reflection_generate'"), 4)
        self.assertIn("task_type IN ({ALL_TASKS})", source)


if __name__ == "__main__":
    unittest.main()
