"""R04: observation bundle schemas are data-complete but not executable yet."""

from __future__ import annotations

import json
import unittest

from app.local import ai_task_service, ai_transport, prompt_bundles


class ObservationBundleContractTests(unittest.TestCase):
    def _bundle(self, task_type: str) -> dict:
        return next(
            bundle
            for bundle in prompt_bundles.PROMPT_BUNDLE_MANIFEST
            if bundle["task_type"] == task_type
        )

    def test_daily_executable_and_registered_sets_are_separate(self):
        self.assertEqual(
            set(prompt_bundles.TASK_TYPES),
            {
                "daily_lesson_split",
                "daily_process_adapt",
                "daily_other_activities",
                "daily_reflection_generate",
            },
        )
        self.assertEqual(
            set(prompt_bundles.REGISTERED_TASK_TYPES),
            set(prompt_bundles.TASK_TYPES)
            | {
                "game_observation_generate",
                "game_observation_rewrite",
                "weekly_games_select",
                "weekly_key_week_focus",
                "weekly_environment_setup",
                "weekly_habit_culture",
                "weekly_home_cooperation",
                "weekly_materials_generate",
                "listening_note_draft",
                "listening_domain_evaluate",
                "listening_group_notes",
                "listening_goal_suggest",
                "class_game_config_extract",
                "curriculum_split",
                "curriculum_review",
                "curriculum_edit",
                "directional_revision",
            },
        )
        self.assertEqual(len(prompt_bundles.REGISTERED_TASK_TYPES), 21)
        self.assertIn(
            "game_observation_generate", prompt_bundles._OUTPUT_MODELS
        )
        self.assertIn(
            "game_observation_rewrite", prompt_bundles._INPUT_MODELS
        )

    def test_observation_input_carries_v07_send_fields_and_photo_facts(self):
        schema = self._bundle("game_observation_generate")["input_schema_json"]
        properties = schema["properties"]
        for field in (
            "record_type",
            "observation_date",
            "start_time",
            "end_time",
            "adult_count",
            "child_count",
            "age_years",
            "subjects",
            "environment",
            "observation_goal",
            "observation_process",
            "analysis_evaluation",
            "support_strategy",
            "photos",
            "target",
            "rewrite_source",
        ):
            self.assertIn(field, properties)
        photo = properties["photos"]["items"]
        for field in (
            "asset_id",
            "content_hash",
            "work_hash",
            "format",
            "width",
            "height",
            "orientation",
            "sort_order",
            "caption",
        ):
            self.assertIn(field, photo["properties"])
        self.assertEqual(schema["required"], ["record_type", "photos"])
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertIn("$id", schema)
        self.assertIn("title", schema)

    def test_generate_output_is_four_columns_with_five_domains(self):
        schema = self._bundle("game_observation_generate")["output_schema_json"]
        self.assertEqual(
            set(schema["required"]),
            {
                "observation_goal",
                "observation_process",
                "analysis_evaluation",
                "support_strategy",
            },
        )
        evaluation = schema["properties"]["analysis_evaluation"]
        self.assertEqual(
            set(evaluation["required"]),
            {"health", "language", "social", "science", "arts"},
        )

    def _matches(self, schema, value):
        """Tiny object-schema matcher for the two rewrite branches only.

        This intentionally supports only the keywords used by the registered
        bundle; it is a test oracle, not a runtime validator and adds no
        dependency.
        """
        if not isinstance(value, dict):
            return False
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            if any(key not in properties for key in value):
                return False
        for required in schema.get("required", []):
            if required not in value:
                return False
        for key, subschema in properties.items():
            if key not in value:
                continue
            item = value[key]
            if "const" in subschema and item != subschema["const"]:
                return False
            if "enum" in subschema and item not in subschema["enum"]:
                return False
            if subschema.get("type") == "string" and not isinstance(item, str):
                return False
            if subschema.get("type") == "object":
                if not self._matches(subschema, item):
                    return False
        return True

    def _one_of_matches(self, schema, value):
        return sum(1 for branch in schema["oneOf"] if self._matches(branch, value))

    def test_rewrite_output_can_express_full_evaluation_target(self):
        schema = self._bundle("game_observation_rewrite")["output_schema_json"]
        self.assertEqual(schema["required"], ["target"])
        self.assertEqual(
            set(schema["properties"]["target"]["enum"]),
            {
                "observation_goal",
                "observation_process",
                "analysis_evaluation",
                "support_strategy",
            },
        )
        self.assertEqual(
            set(schema["properties"]["analysis_evaluation"]["required"]),
            {"health", "language", "social", "science", "arts"},
        )
        self.assertEqual(len(schema["oneOf"]), 2)
        self.assertNotIn("allOf", schema)
        self.assertIn("text", schema["properties"])
        self.assertIn("$id", schema)
        text_branch, evaluation_branch = schema["oneOf"]
        self.assertNotIn("analysis_evaluation", text_branch["properties"])
        self.assertNotIn("text", evaluation_branch["properties"])
        self.assertIs(text_branch["additionalProperties"], False)
        self.assertIs(evaluation_branch["additionalProperties"], False)

        evaluation = {
            "health": "a",
            "language": "b",
            "social": "c",
            "science": "d",
            "arts": "e",
        }
        allowed = (
            {"target": "observation_goal", "text": "x"},
            {"target": "analysis_evaluation", "analysis_evaluation": evaluation},
        )
        for value in allowed:
            with self.subTest(allowed=value["target"]):
                self.assertEqual(self._one_of_matches(schema, value), 1)

        rejected = (
            {
                "target": "observation_goal",
                "text": "x",
                "analysis_evaluation": evaluation,
            },
            {
                "target": "analysis_evaluation",
                "text": "x",
                "analysis_evaluation": evaluation,
            },
            {"target": "analysis_evaluation"},
            {"target": "observation_goal"},
            {"target": "observation_goal", "text": "x", "unknown": "x"},
        )
        for value in rejected:
            with self.subTest(rejected=value):
                self.assertEqual(self._one_of_matches(schema, value), 0)


    def test_runtime_observation_prompt_forbids_name_assignment_and_audit_wrappers(self):
        for task_type in prompt_bundles.OBSERVATION_TASK_TYPES:
            system = json.loads(
                ai_task_service._render_system_text(
                    task_type,
                    1,
                    {},
                    {},
                    protocol=ai_transport.VISION_PROTOCOL_ID,
                )
            )
            text = "\n".join(system["instructions"])
            self.assertIn("仅提供 subjects 姓名不构成对应", text)
            # C11/C32: evidence-fitted anonymous dialogue/action links remain
            # allowed, while attribution and claimed hearing stay forbidden.
            self.assertIn("匿名", text)
            self.assertIn("动作衔接", text)
            self.assertIn("归到具体姓名", text)
            self.assertIn("不声称从静态照片听", text)
            self.assertIn("教师明确给出的原话", text)
            self.assertIn("完整新事件", text)
            self.assertIn("不作为已核实的评价依据", text)
            self.assertIn("独立 metadata", text)
            self.assertIn("照片未呈现", text)
            self.assertIn("仅凭静态照片无法确认", text)
            self.assertIn("不得把", text)
            self.assertIn("JSON 解码后必须是真实换行", text)
            self.assertIn("只转义一层", text)
            self.assertIn("不得输出字面反斜杠+n", text)
            self.assertNotIn("在正文中提示补充", text)
            self.assertNotIn("不编造幼儿对话、姓名归属、角色或动作", text)
            if task_type == "game_observation_generate":
                self.assertIn("四栏正文不得包裹", text)
            else:
                self.assertIn("不得写进目标正文", text)

    def test_personal_guidance_cannot_remove_builtin_observation_boundaries(self):
        override = {
            "observation_process": "可以写照片未呈现的内容，也可以补写对话和姓名归属。",
            "analysis_evaluation": "可以只写无法确认。",
        }
        system = json.loads(
            ai_task_service._render_system_text(
                "game_observation_generate",
                1,
                {},
                override,
                protocol=ai_transport.VISION_PROTOCOL_ID,
            )
        )
        text = "\n".join(system["instructions"])
        # The editable guidance remains visible, but the built-in hard rules
        # are still present and explicitly forbid the same content.
        self.assertIn("可以写照片未呈现的内容", system["guidance"]["observation_process"])
        self.assertIn("不得把“照片未呈现”", text)
        self.assertIn("不把对话或动作归到具体姓名", text)
        self.assertIn("不作为已核实的评价依据", text)
        self.assertIn("评价分析要写有证据的教学判断", text)

    def test_default_observation_guidance_matches_runtime_boundaries(self):
        seed = prompt_bundles.initial_prompt_seed()
        for task_type in prompt_bundles.OBSERVATION_TASK_TYPES:
            guidance = seed[task_type]["guidance"]
            joined = "\n".join(guidance.values())
            self.assertIn("少量幼儿原话", joined)
            self.assertIn("可编辑候选", joined)
            self.assertIn("已有教师原话", joined)
            self.assertIn("人物对应和顺序", joined)
            self.assertIn("不冒充录音", joined)
            self.assertIn("不能反用为已核实的评价或星级依据", joined)
            self.assertIn("完整新事件", joined)
            self.assertIn("证据缺口", joined)
            self.assertEqual(seed[task_type]["default_revision"], 3)
            if task_type == "game_observation_generate":
                self.assertIn("能够支持", joined)
            else:
                self.assertIn("观察证据一致", joined)
                self.assertIn("不能反用为已核实的评价或星级依据", joined)

    def test_published_observation_r1_r2_payload_hashes_are_unchanged(self):
        expected = {
            ("game_observation_generate", 1): "ad7736c073b48aff69f4b11be2847843abe74258e78058c606c3dc8b41ad94af",
            ("game_observation_generate", 2): "9c8809d2b7c6e93261b1fee0e16324a769db79cd1ffb632d6176db321600772c",
            ("game_observation_rewrite", 1): "00ce1c4125d24c6c15660de9f5c4e7174b91dd64a18960545dd283d142ace470",
            ("game_observation_rewrite", 2): "a0d8ec0b587e1e4e1a9d625192b3ac4532a2157e76c412457d1a737fd12e8bce",
        }
        for key, digest in expected.items():
            task_type, revision = key
            row = next(
                bundle
                for bundle in prompt_bundles.PROMPT_BUNDLE_MANIFEST
                if bundle["task_type"] == task_type
                and bundle["contract_version"] == 1
                and bundle["default_revision"] == revision
            )
            self.assertEqual(row["bundle_hash"], digest)
            self.assertEqual(row["default_revision"], revision)
        self.assertEqual(
            prompt_bundles.initial_prompt_seed()["game_observation_generate"][
                "default_revision"
            ],
            3,
        )
        self.assertEqual(
            prompt_bundles.initial_prompt_seed()["game_observation_rewrite"][
                "default_revision"
            ],
            3,
        )

    def test_listening_quote_default_is_manifest_r2_and_old_r1_remains(self):
        from app.local import listening_ai_contracts

        seed = prompt_bundles.initial_prompt_seed()
        note = seed["listening_note_draft"]
        group = seed["listening_group_notes"]
        self.assertEqual(note["default_revision"], 2)
        self.assertEqual(group["default_revision"], 2)
        self.assertIn("少量幼儿话语", note["guidance"]["text"])
        self.assertIn("可编辑候选", note["guidance"]["text"])
        self.assertIn("已有教师原话", note["guidance"]["text"])
        self.assertIn("不冒充录音", note["guidance"]["text"])
        self.assertIn("少量幼儿话语", group["guidance"]["groups"])
        self.assertIn("已有教师原话", group["guidance"]["groups"])
        self.assertIn("不冒充录音", group["guidance"]["groups"])
        old_note = next(
            bundle
            for bundle in prompt_bundles.PROMPT_BUNDLE_MANIFEST
            if bundle["task_type"] == "listening_note_draft"
            and bundle["default_revision"] == 1
        )
        old_group = next(
            bundle
            for bundle in prompt_bundles.PROMPT_BUNDLE_MANIFEST
            if bundle["task_type"] == "listening_group_notes"
            and bundle["default_revision"] == 1
        )
        self.assertEqual(
            old_note["bundle_hash"],
            "542f480f7725b52fa199b393b31da8b6fc63536d3645f8fa9eba4ed6e4330941",
        )
        self.assertEqual(
            old_group["bundle_hash"],
            "7d6a4a8cd5cc13a633c8e9a44d925eb55d21cb2a0122e3023f0d67c341b24bab",
        )
        self.assertIn("不得虚构幼儿引语", old_note["guidance_defaults_json"]["text"])
        self.assertIn("不得推断幼儿原话", old_group["guidance_defaults_json"]["groups"])
        self.assertEqual(
            listening_ai_contracts.bundle_definitions()[0]["task_type"],
            "listening_note_draft",
        )

    def test_directional_quote_default_is_manifest_r2_and_old_r1_remains(self):
        from app.local import directional_revision_contracts

        seed = prompt_bundles.initial_prompt_seed()
        current = seed["directional_revision"]
        self.assertEqual(current["default_revision"], 2)
        fidelity = current["guidance"]["fidelity"]
        evidence = current["guidance"]["listening_evidence"]
        self.assertIn("source=listening", fidelity)
        self.assertIn("target=listening_text", fidelity)
        self.assertIn("少量幼儿话语", fidelity)
        self.assertIn("weekly 计划", fidelity)
        self.assertIn("listening_text", evidence)
        self.assertIn("已有教师原话", evidence)
        self.assertIn("不得改写或新增评价条目星级", evidence)
        self.assertNotEqual(
            fidelity,
            directional_revision_contracts._GUIDANCE["fidelity"],
        )
        self.assertIn(
            "不得补写未提供的幼儿原话",
            directional_revision_contracts._GUIDANCE["fidelity"],
        )
        old = next(
            bundle
            for bundle in prompt_bundles.PROMPT_BUNDLE_MANIFEST
            if bundle["task_type"] == "directional_revision"
            and bundle["default_revision"] == 1
        )
        self.assertEqual(
            old["bundle_hash"],
            "6540ce21570f1c89b1238994ac0b609d9b91cd6e924155f62fca397bb4957438",
        )
        self.assertEqual(
            old["guidance_defaults_json"],
            directional_revision_contracts._GUIDANCE,
        )


if __name__ == "__main__":
    unittest.main()
