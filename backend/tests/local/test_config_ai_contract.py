"""Pure contract/static checks for the class game-config AI extraction.

No database, no network, no real AI, no migration execution and no teacher
data.  Run with the repository Python environment.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from app.local import (
    ai_inputs,
    ai_task_service,
    ai_transport,
    config_ai_contracts,
    config_ai_service,
    config_service,
    prompt_bundles,
)

TASK = config_ai_contracts.TASK_TYPE
SOURCE = config_ai_contracts.SOURCE_KIND


class ConfigAIContractTests(unittest.TestCase):
    def test_input_shape(self) -> None:
        self.assertEqual(
            config_ai_contracts.validate_input({"source_text": "区域：建构区"}),
            {"source_text": "区域：建构区"},
        )
        for bad in (
            {},
            {"source_text": ""},
            {"source_text": "   "},
            {"source_text": "x", "extra": 1},
            {"source_text": "x" * (config_ai_contracts.MAX_SOURCE_TEXT_CHARS + 1)},
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(config_ai_contracts.ConfigAIInputError):
                    config_ai_contracts.validate_input(bad)

    def test_service_entry_rejects_blank_text_without_provider(self) -> None:
        # No session/runtime is touched: the service validates the text before
        # any readiness check, task write or provider dispatch.
        with self.assertRaises(Exception) as raised:
            config_ai_service.create_task(
                None,
                runtime=None,
                expected_config_version=1,
                source_text="   ",
                request_id="00000000-0000-4000-8000-000000000001",
            )
        self.assertIn("不能为空", str(raised.exception))
        from app.local.schemas import LocalConfigAITaskCreateIn

        with self.assertRaises(Exception):
            LocalConfigAITaskCreateIn(
                request_id="00000000-0000-4000-8000-000000000001",
                expected_config_version=1,
                source_text="   ",
            )

    def test_candidate_shape_and_limits(self) -> None:
        valid = {
            "locations": [
                {"kind": "area", "name": "建构区", "guidance": "限 4 人"},
                {"kind": "outdoor", "name": "东操场", "guidance": None},
            ],
            "game_scope": "户外为主",
            "guidance": "雨天改室内",
        }
        parsed = config_ai_contracts.validate_candidate(valid)
        self.assertEqual(parsed["locations"][0]["name"], "建构区")
        for bad in (
            {"locations": [{"kind": "area", "name": ""}], "game_scope": None, "guidance": None},
            {"locations": [{"kind": "room", "name": "x"}], "game_scope": None, "guidance": None},
            {"locations": [], "game_scope": None, "guidance": None, "extra": 1},
            {"locations": [{"kind": "area", "name": "x", "extra": 1}], "game_scope": None, "guidance": None},
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(config_ai_contracts.ConfigAICandidateError):
                    config_ai_contracts.validate_candidate(bad)
        too_many = {
            "locations": [
                {"kind": "area", "name": f"区域{i}"} for i in range(31)
            ],
            "game_scope": None,
            "guidance": None,
        }
        with self.assertRaises(config_ai_contracts.ConfigAICandidateError):
            config_ai_contracts.validate_candidate(too_many)

    def test_existing_class_game_rules_normalize_candidate(self) -> None:
        normalized = config_service.normalize_class_games_candidate(
            {
                "locations": [
                    {"kind": "area", "name": "建构区", "guidance": ""},
                    {"kind": "special_room", "name": "图书室", "guidance": None},
                ],
                "game_scope": "",
                "guidance": "通用限制",
            }
        )
        self.assertIsNone(normalized["locations"][0]["guidance"])
        self.assertIsNone(normalized["game_scope"])
        self.assertEqual(normalized["guidance"], "通用限制")
        with self.assertRaises(Exception):
            config_service.normalize_class_games_candidate(
                {"locations": [{"kind": "area", "name": ""}], "game_scope": None, "guidance": None}
            )

    def test_projection_and_render(self) -> None:
        first = ai_inputs.project_config_input(
            source_text="区域：建构区", class_id="c1", config_version=3
        )
        second = ai_inputs.project_config_input(
            source_text="区域：建构区", class_id="c1", config_version=3
        )
        self.assertEqual(first["payload"], {"source_text": "区域：建构区"})
        self.assertEqual(first["dependency_hash"], second["dependency_hash"])
        self.assertNotEqual(
            first["dependency_hash"],
            ai_inputs.project_config_input(
                source_text="区域：美工区", class_id="c1", config_version=3
            )["dependency_hash"],
        )
        self.assertEqual(
            config_ai_service._fingerprint(
                class_id="c1", config_version=3, source_text="区域：建构区"
            ),
            config_ai_service._fingerprint(
                class_id="c1", config_version=3, source_text="区域：建构区"
            ),
        )
        system = ai_task_service._render_system_text(
            TASK,
            1,
            config_ai_contracts.OUTPUT_SCHEMA,
            config_ai_contracts.GUIDANCE,
        )
        self.assertIn("class_game_config_extract", system)
        self.assertIn("locations", system)
        self.assertIn("无法判断地点类型", system)

    def test_formal_lifecycle_branches_are_present(self) -> None:
        import inspect

        self.assertIn("class_game_config", inspect.getsource(ai_task_service._revalidate_source))
        self.assertIn("class_game_config", inspect.getsource(ai_task_service.finalize_success))
        self.assertIn("class_game_config_extract", inspect.getsource(ai_task_service._render_system_text))
        self.assertIn("LocalAIInput", inspect.getsource(config_ai_service.create_task))
        self.assertIn("LocalAITask", inspect.getsource(config_ai_service.create_task))

    def test_task_registration_surface(self) -> None:
        self.assertIn(TASK, prompt_bundles.REGISTERED_TASK_TYPES)
        self.assertNotIn(TASK, prompt_bundles.TASK_TYPES)
        self.assertTrue(
            any(
                item["task_type"] == TASK
                for item in prompt_bundles.PROMPT_BUNDLE_MANIFEST
            )
        )
        self.assertTrue(ai_task_service._supports_task_contract(TASK, 1))
        self.assertIsNotNone(
            ai_transport.text_response_budget(TASK, source_kind=SOURCE)
        )
        self.assertIsNone(
            ai_transport.text_response_budget(TASK, source_kind="daily_plan")
        )
        self.assertNotIn("class_game_config", prompt_bundles.TASK_TYPES)

    def test_models_register_config_source_and_task(self) -> None:
        from app.local.models import (
            LocalAICandidate,
            LocalAIExecution,
            LocalAIInput,
            LocalAITask,
            LocalPromptBundle,
        )

        for table in (
            LocalAIInput.__table__,
            LocalAITask.__table__,
            LocalAIExecution.__table__,
            LocalAICandidate.__table__,
            LocalPromptBundle.__table__,
        ):
            ddl = " ".join(
                str(getattr(constraint, "sqltext", ""))
                for constraint in table.constraints
            )
            self.assertIn("class_game_config", ddl, table.name)
        self.assertIn(
            "uq_local_ai_tasks_active_per_config_type",
            {index.name for index in LocalAITask.__table__.indexes},
        )

    def test_production_text_bootstrap_authorizes_only_config_text_pair(self) -> None:
        import json
        from types import SimpleNamespace

        from app.local.ai_executor import _encode_bootstrap
        from app.local.ai_worker import text_request_body

        def claim(**overrides):
            values = dict(
                image_urls=(),
                vision_authorized=False,
                source_kind=SOURCE,
                task_type=TASK,
                base_url="https://synthetic.invalid/v1",
                model="synthetic",
                secret="synthetic-only",
                system_text="synthetic system",
                payload={"source_text": "合成区域：建构区"},
            )
            values.update(overrides)
            return SimpleNamespace(**values)

        frame, = _encode_bootstrap(claim(), 1000)
        request = json.loads(frame)["request"]
        budget, body = text_request_body(request)
        self.assertEqual(request["source_kind"], SOURCE)
        self.assertEqual(request["task_type"], TASK)
        self.assertEqual(json.loads(request["user_text"]), claim().payload)
        self.assertEqual(json.loads(body)["max_tokens"], budget.max_tokens)
        self.assertEqual(budget.max_tokens, 8192)

        for bad, error in (
            (claim(task_type="daily_lesson_split"), "text_bootstrap_not_authorized"),
            (claim(source_kind="daily_plan"), "response_budget_not_authorized"),
            (claim(vision_authorized=True), "text_bootstrap_not_authorized"),
            (
                claim(image_urls=("data:image/png;base64,AA==",)),
                "vision_not_authorized",
            ),
        ):
            with self.subTest(error=error, bad=bad):
                with self.assertRaises(ValueError) as raised:
                    _encode_bootstrap(bad, 1000)
                self.assertEqual(str(raised.exception), error)

        daily = claim(
            source_kind="daily_plan",
            task_type="daily_lesson_split",
            payload={"raw_lesson_plan": "合成原文", "grade": "middle"},
        )
        daily_frame, = _encode_bootstrap(daily, 1000)
        daily_request = json.loads(daily_frame)["request"]
        self.assertEqual(daily_request["source_kind"], "daily_plan")
        self.assertEqual(daily_request["task_type"], "daily_lesson_split")
        self.assertIsNotNone(text_request_body(daily_request))

    def test_migration_is_forward_only_and_preserves_old_columns(self) -> None:
        migration = (
            Path(__file__).resolve().parents[2]
            / "migrations_local"
            / "versions"
            / "20261108_0011_local_config_ai.py"
        )
        source = migration.read_text(encoding="utf-8")
        tree = ast.parse(source)
        revision = down_revision = None
        for node in tree.body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.target.id == "revision":
                    revision = ast.literal_eval(node.value)
                if node.target.id == "down_revision":
                    down_revision = ast.literal_eval(node.value)
        self.assertEqual(revision, "20261108_0011_local_config_ai")
        self.assertEqual(down_revision, "20261107_0010_local_listening_ai")
        self.assertIn("class_game_config", source)
        self.assertIn("class_game_config_extract", source)
        self.assertIn("listening_record_id, listening_domain, listening_group_id", source)
        self.assertNotIn("_create_listening_adoption_table()", source)
        self.assertIn("_rebuild_ai_inputs()", source)
        self.assertIn("_rebuild_ai_tasks()", source)
        self.assertIn("_rebuild_ai_executions()", source)
        self.assertIn("_rebuild_ai_candidates()", source)
        self.assertIn("_rebuild_prompt_bundles()", source)
        self.assertIn("uq_local_ai_tasks_active_per_config_type", source)


if __name__ == "__main__":
    unittest.main()
