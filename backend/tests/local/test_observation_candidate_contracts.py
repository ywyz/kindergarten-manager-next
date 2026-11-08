"""#16 pure observation candidate edit and regeneration request contracts.

No database, runtime, network or worker is started here.  These tests pin the
synthetic production projections and the strict field/target rules used by the
real observation edit page.
"""

from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from app.local import observation_ai_inputs as oi
from app.local import observation_ai_service as service
from app.local.errors import LocalAiInputInvalid, LocalValidationError
from app.local.prompt_bundles import CandidateInvalid
from app.local.schemas import (
    LocalObservationAIAdoptionPreviewIn,
    LocalObservationAITaskCreateIn,
)


def _payload(**overrides):
    value = {
        "record_type": "public",
        "observation_date": "2026-09-15",
        "start_time": "10:00",
        "end_time": "10:20",
        "adult_count": 2,
        "child_count": 8,
        "age_years": 5,
        "subjects": [{"name": "小明"}],
        "environment": "积木区",
        "observation_goal": "观察合作",
        "observation_process": "幼儿一起搭建。",
        "analysis_evaluation": {
            "health": "",
            "language": "",
            "social": "",
            "science": "",
            "arts": "",
        },
        "support_strategy": "",
    }
    value.update(overrides)
    return value


def _manifest():
    return [
        {
            "asset_id": "a" * 8,
            "content_hash": "1" * 64,
            "work_hash": "2" * 64,
            "format": "jpeg",
            "width": 40,
            "height": 30,
            "orientation": None,
            "sort_order": 0,
            "caption": "观察",
            "derivative_id": "d" * 8,
            "params_version": 1,
            "work_width": 40,
            "work_height": 30,
        }
    ]


def _base_generate():
    return {
        "observation_goal": "原目标",
        "observation_process": "原记录",
        "analysis_evaluation": {
            "health": "健康",
            "language": "语言",
            "social": "社会",
            "science": "科学",
            "arts": "艺术",
        },
        "support_strategy": "原策略",
    }


def _project(task_type="game_observation_generate", target=None, **extras):
    return oi.project_input(
        None,
        profile_id="profile",
        observation_id="observation",
        task_type=task_type,
        target=target,
        record=SimpleNamespace(),
        draft=SimpleNamespace(payload_json=_payload()),
        manifest=_manifest(),
        **extras,
    )


class CreateIdentityTests(unittest.TestCase):
    def test_old_ordinary_create_omits_optional_keys_and_replays(self):
        payload, base, instruction = service.observation_create_identity(
            profile_id="profile",
            observation_id="observation",
            task_type="game_observation_generate",
            expected_revision=3,
            expected_hash="a" * 64,
            target=None,
        )
        self.assertIsNone(base)
        self.assertIsNone(instruction)
        self.assertNotIn("base_candidate_id", payload)
        self.assertNotIn("revision_instruction", payload)
        legacy = {
            "source_kind": "game_observation",
            "source_id": "observation",
            "profile_id": "profile",
            "observation_id": "observation",
            "task_type": "game_observation_generate",
            "expected_revision": 3,
            "expected_hash": "a" * 64,
            "target": None,
        }
        self.assertEqual(
            service._fingerprint(service.OP_CREATE, payload),
            service._fingerprint(service.OP_CREATE, legacy),
        )

    def test_directed_create_fingerprint_needs_real_optional_values(self):
        payload, base, instruction = service.observation_create_identity(
            profile_id="profile",
            observation_id="observation",
            task_type="game_observation_generate",
            expected_revision=3,
            expected_hash="a" * 64,
            target=None,
            base_candidate_id="  c1  ",
            revision_instruction="  请更简洁  ",
        )
        self.assertEqual(base, "c1")
        self.assertEqual(instruction, "请更简洁")
        self.assertEqual(payload["base_candidate_id"], "c1")
        self.assertEqual(payload["revision_instruction"], "请更简洁")
        changed, _, _ = service.observation_create_identity(
            profile_id="profile",
            observation_id="observation",
            task_type="game_observation_generate",
            expected_revision=3,
            expected_hash="a" * 64,
            target=None,
            base_candidate_id="c1",
            revision_instruction="请更具体",
        )
        self.assertNotEqual(
            service._fingerprint(service.OP_CREATE, payload),
            service._fingerprint(service.OP_CREATE, changed),
        )

    def test_blank_optional_values_are_omitted(self):
        payload, _, _ = service.observation_create_identity(
            profile_id="profile",
            observation_id="observation",
            task_type="game_observation_generate",
            expected_revision=3,
            expected_hash="a" * 64,
            target=None,
            base_candidate_id="   ",
            revision_instruction="   ",
        )
        self.assertNotIn("base_candidate_id", payload)
        self.assertNotIn("revision_instruction", payload)

    def test_instruction_without_base_is_rejected(self):
        with self.assertRaises(LocalValidationError):
            service.observation_create_identity(
                profile_id="profile",
                observation_id="observation",
                task_type="game_observation_generate",
                expected_revision=3,
                expected_hash="a" * 64,
                target=None,
                revision_instruction="请更简洁",
            )


class WorkerProjectionTests(unittest.TestCase):
    def test_base_and_instruction_enter_the_real_send_projection(self):
        projected = _project(
            base_candidate=_base_generate(),
            revision_instruction="  请更简洁  ",
        )
        self.assertEqual(projected.payload["base_candidate"], _base_generate())
        self.assertEqual(projected.payload["revision_instruction"], "请更简洁")
        self.assertEqual(
            projected.dependencies["base_candidate"], _base_generate()
        )
        self.assertEqual(
            projected.dependencies["revision_instruction"], "请更简洁"
        )
        # Photo facts and the stable business columns remain untouched.
        self.assertEqual(projected.payload["photos"][0]["content_hash"], "1" * 64)
        self.assertEqual(projected.payload["photos"][0]["work_hash"], "2" * 64)
        self.assertEqual(projected.payload["observation_goal"], "观察合作")
        oi.validate_observation_input("game_observation_generate", projected.payload)

    def test_same_projection_is_stable_and_instruction_changes_hash(self):
        first = _project(
            base_candidate=_base_generate(),
            revision_instruction="请更简洁",
        )
        second = _project(
            base_candidate=_base_generate(),
            revision_instruction="请更简洁",
        )
        third = _project(
            base_candidate=_base_generate(),
            revision_instruction="请更具体",
        )
        self.assertEqual(first.dependency_hash, second.dependency_hash)
        self.assertNotEqual(first.dependency_hash, third.dependency_hash)

    def test_rewrite_base_is_the_single_fixed_target(self):
        raw = {"target": "observation_process", "text": "原记录"}
        projected = _project(
            task_type="game_observation_rewrite",
            target="observation_process",
            base_candidate=raw,
            revision_instruction="更具体",
        )
        self.assertEqual(projected.payload["base_candidate"], raw)
        self.assertEqual(projected.payload["target"], "observation_process")
        self.assertNotIn("base_candidate_id", projected.payload)

    def test_unknown_extra_and_instruction_without_base_are_rejected(self):
        with self.assertRaises(LocalAiInputInvalid):
            _project(
                base_candidate=_base_generate(),
                revision_instruction="x",
                dependency_overrides={"unknown": "x"},
            )
        with self.assertRaises(CandidateInvalid):
            oi.validate_observation_input(
                "game_observation_generate",
                {**_project().payload, "revision_instruction": "x"},
            )

    def test_projection_without_extras_has_no_optional_keys(self):
        projected = _project()
        self.assertNotIn("base_candidate", projected.payload)
        self.assertNotIn("revision_instruction", projected.payload)
        self.assertNotIn("base_candidate", projected.dependencies)
        self.assertNotIn("revision_instruction", projected.dependencies)


class EditedCandidateTests(unittest.TestCase):
    def test_generate_edit_keeps_four_columns_and_five_domains(self):
        raw = _base_generate()
        edited = {
            **_base_generate(),
            "observation_goal": "老师改后的目标",
            "analysis_evaluation": {
                "health": "健康改",
                "language": "语言改",
                "social": "社会改",
                "science": "科学改",
                "arts": "艺术改",
            },
        }
        validated = service._validated_edited_candidate(
            "game_observation_generate", raw, edited
        )
        self.assertEqual(validated["observation_goal"], "老师改后的目标")
        self.assertEqual(
            set(validated["analysis_evaluation"]),
            {"health", "language", "social", "science", "arts"},
        )
        values = service._edited_values(
            raw,
            "game_observation_generate",
            validated,
            ["observation_goal", "analysis_evaluation"],
        )
        self.assertEqual(set(values), {"observation_goal", "analysis_evaluation"})
        self.assertEqual(values["observation_goal"], "老师改后的目标")

    def test_generate_edit_rejects_missing_or_extra_fields(self):
        raw = _base_generate()
        missing = _base_generate()
        missing.pop("support_strategy")
        with self.assertRaises(LocalValidationError):
            service._validated_edited_candidate(
                "game_observation_generate", raw, missing
            )
        extra = {**_base_generate(), "unknown": "x"}
        with self.assertRaises(LocalValidationError):
            service._validated_edited_candidate(
                "game_observation_generate", raw, extra
            )
        missing_domain = _base_generate()
        missing_domain["analysis_evaluation"] = {
            "health": "健康",
            "language": "语言",
            "social": "社会",
            "science": "科学",
        }
        with self.assertRaises(LocalValidationError):
            service._validated_edited_candidate(
                "game_observation_generate", raw, missing_domain
            )

    def test_rewrite_edit_must_keep_the_original_target(self):
        raw = {"target": "observation_process", "text": "原记录"}
        validated = service._validated_edited_candidate(
            "game_observation_rewrite",
            raw,
            {"target": "observation_process", "text": "老师改后"},
        )
        self.assertEqual(
            service._edited_values(
                raw, "game_observation_rewrite", validated, ["observation_process"]
            ),
            {"observation_process": "老师改后"},
        )
        with self.assertRaises(LocalValidationError):
            service._validated_edited_candidate(
                "game_observation_rewrite",
                raw,
                {"target": "support_strategy", "text": "改错目标"},
            )

    def test_rewrite_evaluation_edit_keeps_five_domains(self):
        raw = {
            "target": "analysis_evaluation",
            "analysis_evaluation": {
                "health": "健康",
                "language": "语言",
                "social": "社会",
                "science": "科学",
                "arts": "艺术",
            },
        }
        edited = {
            "target": "analysis_evaluation",
            "analysis_evaluation": {
                "health": "健康改",
                "language": "语言改",
                "social": "社会改",
                "science": "科学改",
                "arts": "艺术改",
            },
        }
        validated = service._validated_edited_candidate(
            "game_observation_rewrite", raw, edited
        )
        values = service._edited_values(
            raw,
            "game_observation_rewrite",
            validated,
            ["analysis_evaluation"],
        )
        self.assertEqual(values["analysis_evaluation"]["health"], "健康改")
        self.assertEqual(
            set(values["analysis_evaluation"]),
            {"health", "language", "social", "science", "arts"},
        )

    def test_non_object_edit_is_rejected(self):
        with self.assertRaises(LocalValidationError):
            service._validated_edited_candidate(
                "game_observation_generate", _base_generate(), "text"
            )


class ObservationSchemaTests(unittest.TestCase):
    def test_task_create_accepts_only_the_two_optional_regeneration_fields(self):
        data = LocalObservationAITaskCreateIn(
            request_id="r1",
            task_type="game_observation_generate",
            expected_revision=3,
            expected_hash="a" * 64,
            target=None,
            base_candidate_id="c1",
            revision_instruction="请更简洁",
        )
        self.assertEqual(data.base_candidate_id, "c1")
        self.assertEqual(data.revision_instruction, "请更简洁")
        with self.assertRaises(Exception):
            LocalObservationAITaskCreateIn(
                request_id="r1",
                task_type="game_observation_generate",
                expected_revision=3,
                expected_hash="a" * 64,
                unknown="x",
            )

    def test_preview_accepts_an_edited_candidate_and_rejects_unknown(self):
        data = LocalObservationAIAdoptionPreviewIn(
            request_id="r1",
            expected_revision=3,
            expected_hash="a" * 64,
            selected_targets=["observation_goal"],
            edited_candidate=_base_generate(),
        )
        self.assertEqual(data.edited_candidate["observation_goal"], "原目标")
        with self.assertRaises(Exception):
            LocalObservationAIAdoptionPreviewIn(
                request_id="r1",
                expected_revision=3,
                expected_hash="a" * 64,
                selected_targets=["observation_goal"],
                unknown="x",
            )


if __name__ == "__main__":
    unittest.main()
