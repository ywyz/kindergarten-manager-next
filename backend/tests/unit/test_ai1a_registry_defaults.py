"""AI 1A unit tests: 7-task registry completeness, field limits, defaults,
schema typing and migration-seed snapshot consistency (checklist §9.1).

The comparison against the migration uses the module-level ``SEED_ROWS``
literal constants (importing the migration module does not run Alembic).
JSON content comparison is key-order independent (dict == dict).
"""

from __future__ import annotations

import importlib.util
import os
import unittest
from pathlib import Path

os.environ["APP_DISABLE_DOTENV"] = "1"

from app.services import ai_prompt_registry as reg  # noqa: E402
from app.services.ai_prompt_registry import (  # noqa: E402
    CandidateStructureInvalid,
    FieldViolation,
    TASK_REGISTRY,
    TASK_TYPES,
    UnknownTaskType,
    contract_snapshot,
    get_registry,
    guidance_defaults_snapshot,
    validate_candidate,
    validate_candidate_sources,
    validate_guidance_map,
    validate_guidance_patch,
    require_task_type,
)

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "versions"
    / "20261003_ai1a_config_prompts.py"
)


def _load_migration_module():
    spec = importlib.util.spec_from_file_location(
        "ai1a_seed_module", MIGRATION_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EXPECTED_DEFAULT_COUNT = 22


class RegistryCoverageTest(unittest.TestCase):
    def test_seven_tasks_registered_unique(self):
        self.assertEqual(len(TASK_REGISTRY), 7)
        self.assertEqual(len(set(TASK_TYPES)), 7)
        self.assertEqual(
            tuple(sorted(TASK_TYPES)),
            (
                "daily_lesson_split",
                "daily_other_activities",
                "daily_process_adapt",
                "weekly_columns",
                "weekly_games",
                "weekly_materials",
                "weekly_theme_suggestion",
            ),
        )

    def test_each_task_completeness(self):
        snapshot = contract_snapshot()
        defaults = guidance_defaults_snapshot()
        total_fields = 0
        for task in TASK_TYPES:
            entry = snapshot[task]
            self.assertTrue(entry["input_vars"], task)
            for var, spec in entry["input_vars"].items():
                for key in ("type", "required", "nullable", "origin"):
                    self.assertIn(key, spec, (task, var))
            self.assertIn("output_schema", entry)
            self.assertTrue(entry["guidance_fields"])
            self.assertEqual(
                defaults[task],
                reg.get_registry(task).guidance_defaults,
            )
            total_fields += len(entry["guidance_fields"])
        self.assertEqual(total_fields, EXPECTED_DEFAULT_COUNT)

    def test_grade_enum_declared_on_regression_inputs(self):
        snapshot = contract_snapshot()
        for task in ("daily_lesson_split", "daily_process_adapt"):
            self.assertIn("small", snapshot[task]["input_vars"]["grade"]["type"])
        self.assertIn(
            "small",
            snapshot["daily_other_activities"]["input_vars"]["class_grade"]["type"],
        )
        self.assertIn(
            "small",
            snapshot["weekly_games"]["input_vars"]["class_grade"]["type"],
        )

    def test_defaults_match_coordination_text(self):
        # v3 定稿正文逐字段比对（抽查关键文案防止漂移）。
        reg_dailysplit = guidance_defaults_snapshot()["daily_lesson_split"]
        self.assertEqual(
            reg_dailysplit["theme"],
            "从原始教案中摘出集体活动的活动主题名称；只用教案已有的表述；"
            "教案未写主题时输出空字符串，不要编造。",
        )
        self.assertEqual(
            guidance_defaults_snapshot()["weekly_games"]["focus_area_selection"],
            "从本周全班日计划中集体活动之后的区域／户外／专用室游戏候选里，"
            "选出本周重点区域；只能引用真实存在的候选来源，保持其所属区域与游戏完整对应，"
            "不跨来源拼接目标与指导；候选不足时对应槽输出null，补足建议写insufficient_supplements。",
        )
        materials = guidance_defaults_snapshot()["weekly_materials"]
        self.assertIn("evidence_refs为空", materials["supplement"])
        self.assertEqual(
            set(materials), {"extraction", "supplement"}
        )


class GuidanceValidationTest(unittest.TestCase):
    def test_unknown_task(self):
        with self.assertRaises(UnknownTaskType):
            get_registry("not_a_task")
        with self.assertRaises(UnknownTaskType):
            require_task_type("not_a_task")

    def test_full_map_must_match_fields(self):
        registry = get_registry("weekly_games")
        good = dict(registry.guidance_defaults)
        self.assertEqual(validate_guidance_map(registry, good), good)
        bad = dict(good)
        bad.pop("collective_selection")
        with self.assertRaises(FieldViolation):
            validate_guidance_map(registry, bad)
        bad2 = dict(good)
        bad2["made_up_field"] = "x"
        with self.assertRaises(FieldViolation):
            validate_guidance_map(registry, bad2)
        with self.assertRaises(FieldViolation):
            validate_guidance_map(registry, "not a dict")

    def test_field_length_limit(self):
        registry = get_registry("daily_process_adapt")
        bad = dict(registry.guidance_defaults)
        bad["process"] = "长" * 8001
        with self.assertRaises(FieldViolation):
            validate_guidance_map(registry, bad)
        ok = dict(registry.guidance_defaults)
        ok["process"] = "长" * 8000
        validate_guidance_map(registry, ok)

    def test_patch_rejects_empty_unknown_duplicate(self):
        registry = get_registry("daily_lesson_split")
        with self.assertRaises(FieldViolation):
            validate_guidance_patch(registry, [])
        with self.assertRaises(FieldViolation):
            validate_guidance_patch(registry, ["theme", "theme"])
        with self.assertRaises(FieldViolation):
            validate_guidance_patch(registry, ["huh"])
        self.assertEqual(
            validate_guidance_patch(registry, ["theme"]), ["theme"]
        )
        # 改字段名／结构都不可能：字段名白名单是唯一入口。
        with self.assertRaises(FieldViolation):
            validate_guidance_patch(registry, ["theme_renamed"])


class CandidateSchemaTest(unittest.TestCase):
    def test_lesson_split_shape(self):
        registry = get_registry("daily_lesson_split")
        candidate = validate_candidate(
            registry,
            {
                "group_activity": {
                    "theme": "t", "objectives": "", "preparation": "",
                    "key_points": "", "difficult_points": "", "process": "p",
                }
            },
        )
        self.assertEqual(candidate.group_activity.theme, "t")
        with self.assertRaises(CandidateStructureInvalid):
            validate_candidate(
                registry, {"group_activity": {"theme": "t"}}
            )
        with self.assertRaises(CandidateStructureInvalid):
            validate_candidate(
                registry,
                {"group_activity": {"theme": "t"} | {"extra": 1}},
            )

    def test_afternoon_outdoor_single_object_rules(self):
        registry = get_registry("daily_other_activities")
        # 单对象，非列表。
        candidate = validate_candidate(
            registry,
            {"afternoon_outdoor": {"games": [{"name": "  踩影子   "}]}},
        )
        self.assertEqual(candidate.afternoon_outdoor.games[0].name, "  踩影子   ")
        with self.assertRaises(CandidateStructureInvalid):
            validate_candidate(
                registry,
                {"afternoon_outdoor": [{"games": [{"name": "x"}]}]},
            )
        with self.assertRaises(CandidateStructureInvalid):
            validate_candidate(
                registry,
                {"afternoon_outdoor": {"context_kind": "area",
                                       "games": [{"name": "x"}]}},
            )
        with self.assertRaises(CandidateStructureInvalid):
            validate_candidate(
                registry,
                {"afternoon_outdoor": {"games": [{"name": "x"}],
                                       "reflection": "r"}},
            )
        with self.assertRaises(CandidateStructureInvalid):
            validate_candidate(
                registry,
                {"afternoon_outdoor": {"games": [{"name": "x"}],
                                       "group_id": "g1"}},
            )
        # {} 是合法空候选，不冒充生成完成。
        validate_candidate(registry, {})
        # 显式 null 的部分不冒充省略。
        with self.assertRaises(CandidateStructureInvalid):
            validate_candidate(registry, {"afternoon_outdoor": None})
        # morning 组数量 ≤1 集体 + ≤1 自选。
        with self.assertRaises(CandidateStructureInvalid):
            validate_candidate(
                registry,
                {
                    "morning_games": [
                        {"group_kind": "collective", "games": [{"name": "a"}]},
                        {"group_kind": "collective", "games": [{"name": "b"}]},
                    ]
                },
            )

    def test_weekly_games_requires_slots_and_refs(self):
        registry = get_registry("weekly_games")
        with self.assertRaises(CandidateStructureInvalid):
            validate_candidate(
                registry,
                {"collective_1": None, "collective_2": None,
                 "free_choice_1": None,
                 "insufficient_supplements": []},
            )
        base = {
            "source_ref": "d1", "game_id": "g1", "group_id": "gr1",
            "name": "老狼老狼几点了",
        }
        candidate = validate_candidate(
            registry,
            {
                "collective_1": base,
                "collective_2": None,
                "free_choice_1": None,
                "focus_area": None,
                "insufficient_supplements": [
                    {"target_slot": "collective_2", "name": "沙包投准",
                     "objectives": "目标", "guidance_points": "要点"}
                ],
            },
        )
        validate_candidate_sources(
            registry,
            candidate,
            {"week_source_manifest": [dict(base, source="daily")]},
        )
        with self.assertRaises(reg.SourceReferenceInvalid):
            validate_candidate_sources(
                registry,
                candidate,
                {"week_source_manifest": []},
            )
        # 不许生成新身份／新槽枚举。
        # 未知 slot 枚举值：结构拒绝（target_slot 限四槽）。
        with self.assertRaises(CandidateStructureInvalid):
            validate_candidate(
                registry,
                {
                    "collective_1": None, "collective_2": None,
                    "free_choice_1": None, "focus_area": None,
                    "insufficient_supplements": [
                        {"target_slot": "group_9", "name": "n",
                         "objectives": "o", "guidance_points": "g"}
                    ],
                },
            )

    def test_theme_suggestion_empty_invalid(self):
        registry = get_registry("weekly_theme_suggestion")
        candidate = validate_candidate(registry, {"theme_suggestion": "秋天的树"})
        self.assertEqual(candidate.theme_suggestion, "秋天的树")
        with self.assertRaises(CandidateStructureInvalid):
            validate_candidate(registry, {"theme_suggestion": "  "})

    def test_materials_limits(self):
        registry = get_registry("weekly_materials")
        candidate = validate_candidate(
            registry,
            {
                "items": [
                    {"text": "彩纸", "origin": "extracted",
                     "evidence_refs": [
                         {"source_ref": "s1", "field_path": "x",
                          "quote": "彩纸"}
                     ]},
                    {"text": "胶水", "origin": "suggested",
                     "evidence_refs": []},
                ]
            },
        )
        validate_candidate_sources(
            registry,
            candidate,
            {"sources": {"s1": {"x": "准备 彩纸 若干。"}}},
        )
        with self.assertRaises(reg.SourceReferenceInvalid):
            validate_candidate_sources(
                registry,
                candidate,
                {"sources": {"s1": {"x": "没有这个词"}}},
            )
        with self.assertRaises(CandidateStructureInvalid):
            validate_candidate(
                registry,
                {"items": [
                    {"text": "彩纸", "origin": "extracted",
                     "evidence_refs": []},
                ]},
            )
        with self.assertRaises(CandidateStructureInvalid):
            validate_candidate(
                registry,
                {"items": [
                    {"text": "彩纸", "origin": "suggested",
                     "evidence_refs": [
                         {"source_ref": "s1", "field_path": "x",
                          "quote": "彩纸"}
                     ]},
                ]},
            )
        with self.assertRaises(CandidateStructureInvalid):
            validate_candidate(
                registry,
                {"items": [{"text": "t" * 301, "origin": "suggested",
                            "evidence_refs": []}]},
            )
        with self.assertRaises(CandidateStructureInvalid):
            validate_candidate(
                registry,
                {"items": [
                    {"text": "t", "origin": "suggested", "evidence_refs": []}
                ] * 101},
            )

    def test_schema_separation_from_business_models(self):
        # 候选 schema 是独立 Pydantic 类型，不与业务保存 schema 复用。
        import inspect

        from app.services import daily_plan_content

        business_names = {
            name
            for name, obj in inspect.getmembers(daily_plan_content)
            if name.endswith("Model") or name.endswith("Content")
        }
        for task in TASK_TYPES:
            registry = get_registry(task)
            model = registry.output_model
            self.assertEqual(model.__module__, "app.services.ai_prompt_registry")
            self.assertNotIn(model.__name__, business_names)
            source = inspect.getsource(daily_plan_content)
            self.assertNotIn(model.__name__, source)

    def test_source_validation_separate_from_structure(self):
        # 结构通过 ≠ 来源已验：weekly_games 结构合法但候选集合空 → 来源校验失败。
        registry = get_registry("weekly_games")
        candidate = validate_candidate(
            registry,
            {"collective_1": None, "collective_2": None,
             "free_choice_1": None, "focus_area": None,
             "insufficient_supplements": []},
        )
        # 空候选（全 null）无需来源命中，但不能当作“已验真实来源”。
        validate_candidate_sources(
            registry, candidate, {"week_source_manifest": []}
        )
        self.assertEqual(registry.source_validation, "weekly_games_refs")


class MigrationSeedConsistencyTest(unittest.TestCase):
    def test_seed_literals_match_registry(self):
        migration = _load_migration_module()
        self.assertTrue(MIGRATION_PATH.exists())
        import json as _json

        seeds = [_json.loads(_json.dumps(r)) for r in migration.SEED_ROWS]
        for row in seeds:
            for key in ("input_vars", "output_schema", "guidance_fields", "guidance_map"):
                if key in row:
                    row[key] = _json.loads(row[key])
        contracts = [r for r in seeds if "default_revision" not in r]
        defaults = [r for r in seeds if "default_revision" in r]
        self.assertEqual(len(contracts), 7)
        self.assertEqual(len(defaults), 7)
        snapshot = contract_snapshot()
        defaults_snapshot = guidance_defaults_snapshot()
        for row in contracts:
            task = row["task_type"]
            self.assertEqual(row["contract_version"], 1)
            # JSON 内容比较，dict 相等即键序无关（§2.9）。
            self.assertEqual(row["input_vars"], snapshot[task]["input_vars"], task)
            self.assertEqual(
                row["output_schema"], snapshot[task]["output_schema"], task
            )
            self.assertEqual(
                row["guidance_fields"], snapshot[task]["guidance_fields"], task
            )
        for row in defaults:
            task = row["task_type"]
            self.assertEqual(row["default_revision"], 1)
            self.assertEqual(
                row["guidance_map"], defaults_snapshot[task], task
            )


if __name__ == "__main__":
    unittest.main()
