"""Pure #36 contract: one middle-class kindergarten week context for six tasks.

No database, runtime, network or provider call.  It uses the shared pure fake
manifest and the real projection/contract modules only.
"""

from __future__ import annotations

import copy
import json
import unittest

from app.local import prompt_bundles
from app.local import weekly_ai_contracts as contracts
from app.local import weekly_ai_inputs as inputs
from tests.local.weekly_ai_fake_transport import (
    make_raw,
    make_snapshot,
    selected_content,
)


EXPECTED_CONTEXT = {
    "stage": "kindergarten",
    "stage_label": "幼儿园",
    "grade": "middle",
    "grade_label": "中班",
    "term_start": "2026-09-01",
    "term_end": "2026-09-30",
    "week_number": 2,
    "week_start": "2026-09-07",
    "week_end": "2026-09-13",
}


class WeeklyAIContextContractTests(unittest.TestCase):
    def _fixture(self):
        snapshot = make_snapshot(
            header={
                "school_name": "测试园",
                "class_name": "中一班",
                "grade": "middle",
                "header_teacher_names": ["张老师"],
                "caregiver_name": "保育员",
            }
        )
        snapshot, content = selected_content(snapshot)
        return snapshot, content, make_raw(snapshot, content)

    def test_six_tasks_carry_the_same_minimal_kindergarten_context(self):
        _snapshot, content, raw = self._fixture()
        for task in inputs.TASK_TARGETS:
            projection = inputs.project_weekly_input(task, raw, content)
            context = projection.payload["weekly_context"]
            self.assertEqual(
                {key: context[key] for key in EXPECTED_CONTEXT},
                EXPECTED_CONTEXT,
            )
            self.assertIn("幼儿园", context["age_guidance"])
            self.assertIn("年龄", context["age_guidance"])
            self.assertIn("小学", context["age_guidance"])
            self.assertIn("中学", context["age_guidance"])
            self.assertEqual(projection.payload["grade"], "middle")

            text = json.dumps(projection.payload, ensure_ascii=False)
            self.assertNotIn("张老师", text)
            self.assertNotIn("测试园", text)
            self.assertNotIn("profile-1", text)
            self.assertNotIn("class-1", text)
            self.assertNotIn("term-1", text)

    def test_existing_weekly_bundle_identities_stay_unchanged(self):
        # Hashes from the pre-#36 HEAD definitions.  Only the payload
        # projection carries the new context; existing default guidance and
        # prompt bundle identities must not be redefined.
        expected = {
            ("weekly_games_select", 2, 1): "39e9f72be809d48e65bda2aa4ee97828e942cdbdc8a6acacddcab1360d8d0f86",
            ("weekly_key_week_focus", 1, 1): "8e0fb2eeb8173812f50f18cf2f72fe17d5239ed05c990eec445a1c46eb846d6a",
            ("weekly_environment_setup", 1, 1): "76620f3e418a4ccf0730d9a3e343d75181263e55d883fa53613ec93a9904145a",
            ("weekly_habit_culture", 1, 1): "e7d730521a75ca1f97422ec07200383a07f59548a7ef19d8828d8eaddafa5c9f",
            ("weekly_home_cooperation", 1, 1): "2cd7bd82b922e609d73bf8d6a97e297bb4fed95d215de7cf9b47218aa4d8e6d1",
            ("weekly_materials_generate", 2, 1): "0f87bb32bc5ab45d3bf5a4db9076592587e4093825ccb0e072e894ef6dbedc3c",
        }
        actual = {
            (item["task_type"], item["contract_version"], item["default_revision"]): prompt_bundles.bundle_hash(
                item["input_schema_json"],
                item["output_schema_json"],
                item["guidance_defaults_json"],
            )
            for item in contracts.weekly_bundle_definitions()
        }
        self.assertEqual(actual, expected)

    def test_existing_business_payload_is_unchanged_apart_from_context(self):
        _snapshot, content, raw = self._fixture()
        for task in inputs.TASK_TARGETS:
            projection = inputs.project_weekly_input(task, raw, content)
            payload = projection.payload
            self.assertEqual(payload["task_type"], task)
            self.assertEqual(payload["grade"], "middle")
            self.assertIn("weekly_context", payload)
            # The old business facts still exist and are not replaced by the
            # program-owned context.
            if task == "weekly_key_week_focus":
                self.assertEqual(payload["theme"], content["theme"])
            elif task == "weekly_environment_setup":
                self.assertIn("selection", payload)
                self.assertIn("config", payload)
            elif task == "weekly_habit_culture":
                self.assertIn("days", payload)
            elif task == "weekly_home_cooperation":
                self.assertIn("group_activities", payload)
                self.assertIn("calendar", payload)
            elif task == "weekly_materials_generate":
                self.assertIn("selection", payload)
                self.assertIn("config", payload)
            else:
                self.assertIn("days", payload)
                self.assertIn("config", payload)

    def test_legacy_stored_payload_without_context_remains_valid(self):
        _snapshot, content, raw = self._fixture()
        for task in inputs.TASK_TARGETS:
            projection = inputs.project_weekly_input(task, raw, content)
            legacy = copy.deepcopy(projection.payload)
            legacy.pop("weekly_context")
            validated = inputs.validate_stored_weekly_input(
                task,
                legacy,
                projection.dependencies,
                content,
                plan_identity=projection.server_manifest["plan"],
            )
            self.assertEqual(validated.payload, legacy)
            self.assertNotIn("weekly_context", validated.payload)
            self.assertEqual(
                validated.dependency_hash, projection.dependency_hash
            )
            self.assertEqual(validated.target_hashes, projection.target_hashes)

    def test_forged_context_is_rejected(self):
        _snapshot, content, raw = self._fixture()
        for task in inputs.TASK_TARGETS:
            projection = inputs.project_weekly_input(task, raw, content)
            forged = copy.deepcopy(projection.payload)
            forged["weekly_context"]["term_start"] = "2020-01-01"
            with self.assertRaises(contracts.WeeklyAIContractError):
                inputs.validate_stored_weekly_input(
                    task,
                    forged,
                    projection.dependencies,
                    content,
                    plan_identity=projection.server_manifest["plan"],
                )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
