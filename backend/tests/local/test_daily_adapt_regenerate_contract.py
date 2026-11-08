"""#20 adapt regeneration pure contract tests (no database, no network)."""

from __future__ import annotations

import json
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from app.local import ai_inputs, ai_transport, prompt_bundles
from app.local.errors import LocalValidationError

SAVED = "1. 导入\n师：早上好\n2. 观察"
CANDIDATE = "1. 导入\n师：请找两个蓝色圆。\n2. 观察"
INSTRUCTION = "把候选的蓝色圆改为大小不同的方形"


def candidate_row(plan_id="p1", task_type="daily_process_adapt", process=CANDIDATE):
    return SimpleNamespace(
        daily_plan_id=plan_id,
        source_kind="daily_plan",
        task_type=task_type,
        raw_candidate_json={"process": process},
    )


class FakeSession:
    def __init__(self, row):
        self.row = row

    def get(self, _kind, _key):
        return self.row


def project(session, *, base=None, instruction=None, with_baseline=True):
    plan = SimpleNamespace(id="p1")
    content = SimpleNamespace(
        version=4,
        adopted_content={"group_activity": {"process": SAVED}},
    )
    baseline = (
        ("cand-split", {"group_activity_process": SAVED})
        if with_baseline
        else (None, None)
    )
    with patch.object(ai_inputs, "_baseline_reference", return_value=baseline):
        return ai_inputs.project_input(
            session,
            plan=plan,
            content=content,
            task_type="daily_process_adapt",
            target_grade="middle",
            base_candidate_id=base,
            revision_instruction=instruction,
        )

class AdaptRegenerateContractTests(unittest.TestCase):
    def test_historical_adapt_input_keeps_original_bytes(self):
        projected = project(FakeSession(candidate_row()), with_baseline=False)
        self.assertEqual(projected.payload, {"process_source": SAVED, "grade": "middle"})
        self.assertEqual(
            set(projected.dependencies),
            {"process_source", "grade", "baseline_candidate_id", "split_baseline"},
        )
        self.assertEqual(
            json.dumps(projected.payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            '{"grade":"middle","process_source":"1. 导入\\n师：早上好\\n2. 观察"}',
        )

    def test_regeneration_carries_saved_candidate_and_instruction(self):
        projected = project(
            FakeSession(candidate_row()), base="cand-current", instruction=INSTRUCTION
        )
        self.assertEqual(projected.payload["process_source"], SAVED)
        self.assertEqual(projected.payload["split_baseline_process"], SAVED)
        self.assertEqual(projected.payload["base_candidate_process"], CANDIDATE)
        self.assertEqual(projected.payload["revision_instruction"], INSTRUCTION)
        self.assertEqual(projected.dependencies["base_candidate_id"], "cand-current")
        self.assertEqual(projected.dependencies["base_candidate_process"], CANDIDATE)
        self.assertEqual(projected.dependencies["revision_instruction"], INSTRUCTION)
        self.assertEqual(
            prompt_bundles.validate_input("daily_process_adapt", projected.payload),
            projected.payload,
        )

    def test_foreign_plan_candidate_is_rejected_before_projection(self):
        with self.assertRaises(LocalValidationError):
            project(
                FakeSession(candidate_row(plan_id="other-plan")),
                base="cand-foreign",
                instruction=INSTRUCTION,
            )

    def test_wrong_task_type_candidate_is_rejected(self):
        with self.assertRaises(LocalValidationError):
            project(
                FakeSession(candidate_row(task_type="daily_lesson_split")),
                base="cand-wrong",
            )

    def test_old_bundle_identities_are_unchanged(self):
        expected = {
            ("daily_process_adapt", 1, 1): "33dd13f4800ae428f74b157cdaa484abf50588258b6a4a2e00c12af24f0c73e6",
            ("daily_process_adapt", 1, 2): "dd3aaf65c22a600e4aa50b85360f17bf9c2e6395ededdff5d9428491e7e98751",
            ("daily_process_adapt", 1, 3): "f2c4a308db6d74b0754ce1c9370d5d551f867ad91ca1e0bcb3e39ef713353e4e",
        }
        actual = {
            (item["task_type"], item["contract_version"], item["default_revision"]): item["bundle_hash"]
            for item in prompt_bundles.PROMPT_BUNDLE_MANIFEST
            if item["task_type"] == "daily_process_adapt"
        }
        self.assertEqual(actual, expected)
        self.assertEqual(
            prompt_bundles.validate_input(
                "daily_process_adapt", {"process_source": "saved", "grade": "middle"}
            ),
            {"process_source": "saved", "grade": "middle"},
        )


if __name__ == "__main__":
    unittest.main()


class SplitRegenerationProjectionTests(unittest.TestCase):
    def _row(self, plan_id="p1"):
        return SimpleNamespace(
            daily_plan_id=plan_id,
            source_kind="daily_plan",
            task_type="daily_lesson_split",
            raw_candidate_json={
                "group_activity": {
                    "theme": "候选专属主题",
                    "objectives": "",
                    "preparation": "",
                    "key_points": "",
                    "difficult_points": "",
                    "process": "1. 探索",
                }
            },
        )

    def test_split_regeneration_binds_base_and_instruction(self):
        plan = SimpleNamespace(id="p1")
        content = SimpleNamespace(
            version=4,
            raw_lesson_plan="1. 探锁\n师：看看叶子。",
            adopted_content={},
        )
        projected = ai_inputs.project_input(
            FakeSession(self._row()),
            plan=plan,
            content=content,
            task_type="daily_lesson_split",
            target_grade="middle",
            base_candidate_id="cand-split",
            revision_instruction="只清理错字，保留原文",
        )
        self.assertEqual(projected.payload["raw_lesson_plan"], "1. 探锁\n师：看看叶子。")
        self.assertEqual(projected.payload["revision_instruction"], "只清理错字，保留原文")
        self.assertEqual(projected.dependencies["base_candidate_id"], "cand-split")
        self.assertEqual(projected.dependencies["revision_instruction"], "只清理错字，保留原文")
        self.assertNotIn("base_candidate_process", projected.payload)
        self.assertEqual(
            projected.payload["base_candidate"]["group_activity"]["theme"],
            "候选专属主题",
        )
        wire = ai_transport.build_request(
            model="m",
            system_text="s",
            user_text=json.dumps(projected.payload, ensure_ascii=False),
        ).decode("utf-8")
        self.assertIn("候选专属主题", wire)
        self.assertNotIn("cand-split", wire)


    def test_foreign_plan_split_base_is_rejected(self):
        plan = SimpleNamespace(id="p1")
        content = SimpleNamespace(version=4, raw_lesson_plan="原始教案", adopted_content={})
        with self.assertRaises(LocalValidationError):
            ai_inputs.project_input(
                FakeSession(self._row("other")),
                plan=plan,
                content=content,
                task_type="daily_lesson_split",
                target_grade="middle",
                base_candidate_id="cand-foreign",
            )

    def test_split_and_other_rules_cover_directed_requirements(self):
        import json
        from app.local.ai_task_service import _render_system_text

        split = json.loads(_render_system_text("daily_lesson_split", 1, {}, {}))
        other = json.loads(_render_system_text("daily_other_activities", 1, {}, {}))
        self.assertTrue(any("revision_instruction" in rule for rule in split["instructions"]))
        self.assertTrue(any("revision_instruction" in rule for rule in other["instructions"]))

class OtherRegenerationWireTests(unittest.TestCase):
    def test_other_candidate_reference_reaches_wire_without_internal_id(self):
        plan = SimpleNamespace(
            id="p1", class_id="c1", plan_date=date(2026, 11, 8),
            week_number=2, weekday=7,
        )
        content = SimpleNamespace(version=4, raw_lesson_plan="原始教案", adopted_content={})
        row = SimpleNamespace(
            daily_plan_id="p1", source_kind="daily_plan",
            task_type="daily_other_activities",
            raw_candidate_json={
                "morning_talk": {
                    "topic": "候选专属话题",
                    "questions": "候选专属问题",
                }
            },
        )
        context = {"effective_state": "teaching", "weekday": 7, "holiday_context": []}
        with patch.object(
            ai_inputs, "_calendar_context", return_value=(context, {})
        ), patch.object(
            ai_inputs, "_game_config",
            return_value=({"locations": []}, "game-v1", "hash"),
        ):
            projected = ai_inputs.project_input(
                FakeSession(row),
                plan=plan,
                content=content,
                task_type="daily_other_activities",
                target_grade="middle",
                base_candidate_id="cand-other",
                revision_instruction="把当前候选专用话题改为活动文字",
            )
        wire = ai_transport.build_request(
            model="m",
            system_text="s",
            user_text=json.dumps(projected.payload, ensure_ascii=False),
        ).decode("utf-8")
        self.assertIn("候选专属话题", wire)
        self.assertNotIn("cand-other", wire)
        self.assertEqual(
            projected.payload["base_candidate"]["morning_talk"]["topic"],
            "候选专属话题",
        )
        self.assertEqual(projected.dependencies["base_candidate_id"], "cand-other")

    def test_without_base_candidate_old_shape_is_unchanged(self):
        plan = SimpleNamespace(id="p1")
        content = SimpleNamespace(version=4, raw_lesson_plan="原始教案", adopted_content={})
        projected = ai_inputs.project_input(
            FakeSession(SimpleNamespace(
                daily_plan_id="p1", source_kind="daily_plan",
                task_type="daily_lesson_split", raw_candidate_json={},
            )),
            plan=plan,
            content=content,
            task_type="daily_lesson_split",
            target_grade="middle",
        )
        self.assertEqual(set(projected.payload), {"raw_lesson_plan", "grade"})
        self.assertNotIn("base_candidate_id", projected.dependencies)
