"""Targeted daily section and pre-adoption split-adapt source contracts.

Synthetic pure-input tests only; no database or network.
"""

from __future__ import annotations

import json
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from app.local import ai_inputs, prompt_bundles
from app.local.ai_task_service import require_adapt_baseline
from app.local.errors import LocalValidationError

SPLIT_PROCESS = "1. 导入\n师：看看叶子。\n2. 观察"
BOARDS = {
    "morning_games": [
        {
            "group_kind": "collective",
            "games": [{"name": "晨间集体"}],
            "focus_guidance": "晨间集体",
            "shared_objectives": "晨间目标",
            "guidance_points": "晨间指导",
        },
        {
            "group_kind": "free_choice",
            "games": [{"name": "晨间自选"}],
        },
    ],
    "morning_talk": {"topic": "晨间话题", "questions": "晨间问题"},
    "post_group_games": [
        {
            "context_kind": "area",
            "area": "美工区、建构区",
            "focus_guidance": "美工区",
            "games": [{"name": "区域游戏"}],
            "objectives": "区域目标",
            "guidance": "区域指导",
            "support_strategy": "区域支持",
        }
    ],
    "afternoon_outdoor": {
        "area": "骑行、沙水池",
        "observation_focus": "骑行",
        "games": [{"name": "户外游戏"}],
        "objectives": "户外目标",
        "guidance": "户外指导",
        "support_strategy": "户外支持",
    },
}


class MappingSession:
    def __init__(self, rows):
        self.rows = rows

    def get(self, _kind, key):
        return self.rows.get(key)


def other_input_row(projected, task_type="daily_other_activities"):
    return SimpleNamespace(
        task_type=task_type,
        target_grade=projected.target_grade,
        payload_json=projected.payload,
        dependencies_json=projected.dependencies,
        dependency_hash=projected.dependency_hash,
    )


class TargetSectionContractTests(unittest.TestCase):
    def _project(self, target_section="morning_talk", instruction="更贴近本周主题"):
        plan = SimpleNamespace(
            id="p1",
            class_id="c1",
            plan_date=date(2026, 11, 17),
            week_number=12,
            weekday=2,
        )
        content = SimpleNamespace(
            version=5,
            raw_lesson_plan="原始教案",
            adopted_content={
                "group_activity": {
                    "theme": "集体主题",
                    "objectives": "集体目标",
                    "preparation": "集体准备",
                    "key_points": "集体重点",
                    "difficult_points": "集体难点",
                    "process": SPLIT_PROCESS,
                },
                **BOARDS,
            },
        )
        context = {
            "effective_state": "teaching",
            "weekday": 2,
            "holiday_context": [],
        }
        with patch.object(
            ai_inputs, "_calendar_context", return_value=(context, {})
        ), patch.object(
            ai_inputs,
            "_game_config",
            return_value=({"locations": []}, "game-v1", "hash"),
        ):
            return plan, content, ai_inputs.project_input(
                MappingSession({}),
                plan=plan,
                content=content,
                task_type="daily_other_activities",
                target_grade="middle",
                target_section=target_section,
                revision_instruction=instruction,
            )

    def test_target_section_enters_input_dependencies_and_only_its_target_hash(self):
        _plan, _content, projected = self._project()
        instruction = projected.payload["revision_instruction"]
        self.assertIn("只生成「晨间谈话」栏目", instruction)
        self.assertIn("更贴近本周主题", instruction)
        self.assertEqual(projected.dependencies["target_section"], "morning_talk")
        self.assertEqual(
            projected.dependencies["teacher_revision_instruction"],
            "更贴近本周主题",
        )
        self.assertEqual(set(projected.target_hashes), {"morning_talk"})
        self.assertEqual(
            prompt_bundles.validate_input(
                "daily_other_activities", projected.payload
            ),
            projected.payload,
        )
        self.assertNotIn("target_section", projected.payload)

    def test_composite_instruction_does_not_break_dependency_matching(self):
        plan, content, projected = self._project()
        row = other_input_row(projected)
        context = {
            "effective_state": "teaching",
            "weekday": 2,
            "holiday_context": [],
        }

        def matches(value):
            with patch.object(
                ai_inputs, "_calendar_context", return_value=(context, {})
            ), patch.object(
                ai_inputs,
                "_game_config",
                return_value=({"locations": []}, "game-v1", "hash"),
            ):
                return ai_inputs.dependency_matches(
                    MappingSession({}), plan=plan, content=value, input_row=row
                )

        self.assertTrue(matches(content))
        changed = SimpleNamespace(**vars(content))
        changed.adopted_content = {
            **content.adopted_content,
            "morning_games": [],
        }
        self.assertTrue(
            matches(changed),
            "an unrelated board must not invalidate the targeted section",
        )
        changed_target = SimpleNamespace(**vars(content))
        changed_target.adopted_content = {
            **content.adopted_content,
            "morning_talk": {"topic": "已变化", "questions": "已变化"},
        }
        self.assertFalse(matches(changed_target))

    def test_target_section_is_rejected_for_other_task_types(self):
        plan = SimpleNamespace(id="p1")
        content = SimpleNamespace(version=1, raw_lesson_plan="原始教案", adopted_content={})
        with self.assertRaises(LocalValidationError):
            ai_inputs.project_input(
                MappingSession({}),
                plan=plan,
                content=content,
                task_type="daily_lesson_split",
                target_grade="middle",
                target_section="morning_talk",
            )


class PreAdoptionSplitSourceTests(unittest.TestCase):
    def _row(self, *, plan_id="p1", task_type="daily_lesson_split"):
        return SimpleNamespace(
            input_id="split-input",
            daily_plan_id=plan_id,
            source_kind="daily_plan",
            task_type=task_type,
            raw_candidate_json={
                "group_activity": {
                    "theme": "拆分主题",
                    "objectives": "",
                    "preparation": "",
                    "key_points": "",
                    "difficult_points": "",
                    "process": SPLIT_PROCESS,
                }
            },
        )

    def test_split_candidate_process_is_the_direct_adapt_source_and_baseline(self):
        plan = SimpleNamespace(id="p1")
        content = SimpleNamespace(
            version=5, raw_lesson_plan="原始教案", adopted_content={}
        )
        source = self._row()
        source_projection = ai_inputs.project_input(
            MappingSession({}),
            plan=plan,
            content=content,
            task_type="daily_lesson_split",
            target_grade="small",
        )
        source_input = SimpleNamespace(
            task_type="daily_lesson_split",
            source_kind="daily_plan",
            daily_plan_id="p1",
            content_version=5,
            target_grade="small",
            dependency_hash=source_projection.dependency_hash,
        )
        projected = ai_inputs.project_input(
            MappingSession({"cand-split": source, "split-input": source_input}),
            plan=plan,
            content=content,
            task_type="daily_process_adapt",
            target_grade="small",
            source_candidate_id="cand-split",
        )
        self.assertEqual(projected.payload["process_source"], SPLIT_PROCESS)
        self.assertEqual(projected.payload["split_baseline_process"], SPLIT_PROCESS)
        self.assertEqual(
            projected.dependencies["source_split_candidate_id"], "cand-split"
        )
        self.assertEqual(
            projected.dependencies["source_split_candidate_process"], SPLIT_PROCESS
        )
        self.assertTrue(projected.dependencies["pre_adoption_split"])
        self.assertEqual(require_adapt_baseline(projected.payload), SPLIT_PROCESS)
        self.assertEqual(
            prompt_bundles.validate_input("daily_process_adapt", projected.payload),
            projected.payload,
        )
        wire = json.dumps(projected.payload, ensure_ascii=False)
        self.assertEqual(json.loads(wire)["process_source"], SPLIT_PROCESS)
        self.assertNotIn("cand-split", wire)

    def test_foreign_or_wrong_type_split_source_is_rejected(self):
        plan = SimpleNamespace(id="p1")
        content = SimpleNamespace(version=5, adopted_content={})
        for row in (
            self._row(plan_id="other"),
            self._row(task_type="daily_process_adapt"),
        ):
            with self.assertRaises(LocalValidationError):
                ai_inputs.project_input(
                    MappingSession({"cand-split": row}),
                    plan=plan,
                    content=content,
                    task_type="daily_process_adapt",
                    target_grade="middle",
                    source_candidate_id="cand-split",
                )

    def test_source_and_base_candidate_are_mutually_exclusive(self):
        plan = SimpleNamespace(id="p1")
        content = SimpleNamespace(version=5, adopted_content={})
        with self.assertRaises(LocalValidationError):
            ai_inputs.project_input(
                MappingSession({"cand-split": self._row()}),
                plan=plan,
                content=content,
                task_type="daily_process_adapt",
                target_grade="middle",
                source_candidate_id="cand-split",
                base_candidate_id="cand-adapt",
            )


if __name__ == "__main__":
    unittest.main()
