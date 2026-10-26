"""R04: observation bundle schemas are data-complete but not executable yet."""

from __future__ import annotations

import unittest

from app.local import prompt_bundles


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
            },
        )
        self.assertEqual(
            set(prompt_bundles.REGISTERED_TASK_TYPES),
            set(prompt_bundles.TASK_TYPES)
            | {
                "game_observation_generate",
                "game_observation_rewrite",
            },
        )
        self.assertNotIn(
            "game_observation_generate", prompt_bundles._OUTPUT_MODELS
        )
        self.assertNotIn(
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


if __name__ == "__main__":
    unittest.main()
