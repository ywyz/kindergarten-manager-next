"""Current-form listening AI projection, adoption binding and prompt guidance."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime

from app.local import (
    ai_config_service,
    ai_task_service,
    listening_ai_adoption,
    listening_ai_contracts,
    listening_ai_inputs,
    listening_ai_service,
    listening_service,
    profile_service,
    prompt_bundles,
)
from app.local.errors import LocalValidationError
from app.local.models import LocalAIInput, LocalAITask
from app.local.normalize import normalize_initialization
from tests.local.support import LocalTestCase


class ListeningCurrentFormAITests(LocalTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.runtime = self.make_runtime()
        self.runtime.launch_id = str(uuid.uuid4())
        self.session = self.runtime.session()
        self.addCleanup(self.session.close)
        profile_service.initialize(
            self.session,
            normalize_initialization(
                request_id=str(uuid.uuid4()),
                display_name="合成教师",
                class_name="中班合册",
                grade="middle",
                term_name="秋季",
                start_date="2026-09-01",
                end_date="2026-12-31",
                school_name="合成园",
            ),
        )
        self.session.commit()
        ai_config_service.patch_config(
            self.session,
            expected_ai_config_version=0,
            base_url="https://api.deepseek.com/v1",
            model="deepseek-v4-flash-vision-exp",
            secret="synthetic-secret",
            secret_provided=True,
            request_id=str(uuid.uuid4()),
            credential_root=self.runtime.credential_root,
        )
        self.session.commit()
        context = profile_service.require_context(self.session, date(2026, 11, 7))
        self.profile_id = context.profile.id
        self.term_id = context.terms[0].id
        self.record = listening_service.create_record(
            self.session,
            profile_id=self.profile_id,
            request_id=str(uuid.uuid4()),
            term_id=self.term_id,
            child_name="甲",
        )
        self.record_id = self.record["record_id"]
        dto = listening_service.read_record(
            self.session, profile_id=self.profile_id, record_id=self.record_id
        )
        domain = next(item for item in dto["domains"] if item["domain"] == "health")
        self.groups = sorted(domain["groups"], key=lambda item: item["position"])
        self.group_id = self.groups[0]["group_id"]
        listening_service.save_domain(
            self.session,
            profile_id=self.profile_id,
            record_id=self.record_id,
            domain="health",
            request_id=str(uuid.uuid4()),
            expected_revision=1,
            patch={
                "goal": "已保存目标",
                "groups": [
                    {
                        "group_id": self.group_id,
                        "listening_text": "已保存正文",
                    }
                ],
                "overall_evaluation": "已保存评价",
                "support_strategy": "已保存支持",
                "evaluation": {"health_1": 1},
            },
        )
        self.revision = 2

    def _current_form(
        self,
        *,
        goal: str = "未保存目标",
        overall: str = "未保存评价",
        support: str = "未保存支持",
        group_text: str = "未保存正文",
        stars: int = 3,
        group_order: list[int] | None = None,
    ) -> dict:
        dto = listening_service.read_record_no_tx(
            self.session, profile_id=self.profile_id, record_id=self.record_id
        )
        domain = next(item for item in dto["domains"] if item["domain"] == "health")
        ordered = sorted(domain["groups"], key=lambda item: int(item["position"]))
        if group_order is not None:
            ordered = [ordered[index] for index in group_order]
        evaluation = {
            item["item_id"]: item.get("stars")
            for item in domain["evaluation"]
        }
        return {
            "schema_version": 1,
            "observation_date": "2026-09",
            "adult_count": "2",
            "child_age": "5",
            "goal": goal,
            "observation_area": "美工区",
            "overall_evaluation": overall,
            "support_strategy": support,
            "groups": [
                {
                    "group_id": group["group_id"],
                    "position": index,
                    "work_date": f"2026-09-1{index}",
                    "listening_text": (
                        group_text
                        if group["group_id"] == self.group_id
                        else f"未保存正文-{index}"
                    ),
                    "asset_id": group.get("asset_id"),
                }
                for index, group in enumerate(ordered)
            ],
            "evaluation": [
                {"item_id": item_id, "stars": stars if item_id == "health_1" else value}
                for item_id, value in evaluation.items()
            ],
        }

    def _create_current_form_task(self) -> dict:
        current_form = self._current_form()
        result, created = listening_ai_service.create_task(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile_id,
            record_id=self.record_id,
            domain="health",
            group_id=self.group_id,
            task_type=listening_ai_contracts.TASK_NOTE,
            expected_revision=self.revision,
            request_id=str(uuid.uuid4()),
            current_form=current_form,
        )
        self.assertTrue(created)
        return result

    def _finish_note_candidate(self, task_id: str, text: str) -> None:
        claim = ai_task_service.claim_next(
            self.runtime, now=datetime.now(), started_ticks=0
        )
        self.assertIsNotNone(claim)
        self.assertEqual(claim.task_id, task_id)
        dispatch_session = self.runtime.session()
        try:
            self.assertTrue(
                ai_task_service.commit_dispatch_mark(
                    dispatch_session, claim, datetime.now()
                )
            )
        finally:
            dispatch_session.close()
        final_session = self.runtime.session()
        try:
            self.assertTrue(
                ai_task_service.finalize_success(
                    final_session,
                    claim,
                    {
                        "kind": "success",
                        "candidate_text": json.dumps(
                            {"text": text, "uncertainties": []},
                            ensure_ascii=False,
                        ),
                    },
                    datetime.now(),
                )
            )
        finally:
            final_session.close()

    def test_projection_uses_current_unsaved_values_for_all_text_fields(self) -> None:
        current_form = self._current_form()
        saved = listening_ai_inputs.project(
            self.session,
            self.runtime,
            profile_id=self.profile_id,
            record_id=self.record_id,
            domain="health",
            group_id=None,
            task_type=listening_ai_contracts.TASK_DOMAIN,
        )
        projected = listening_ai_inputs.project(
            self.session,
            self.runtime,
            profile_id=self.profile_id,
            record_id=self.record_id,
            domain="health",
            group_id=None,
            task_type=listening_ai_contracts.TASK_DOMAIN,
            current_form=current_form,
        )
        self.assertEqual(projected.source_revision, self.revision)
        self.assertEqual(projected.payload["goal"], "未保存目标")
        self.assertEqual(
            projected.target_hashes["support_strategy"],
            listening_ai_contracts.value_hash("未保存支持"),
        )
        self.assertEqual(projected.dependencies["source_mode"], "current_form")
        self.assertEqual(
            projected.target_hashes["overall_evaluation"],
            listening_ai_contracts.value_hash("未保存评价"),
        )
        self.assertEqual(
            projected.target_hashes["health_1"],
            listening_ai_contracts.value_hash(3),
        )
        self.assertNotEqual(projected.dependency_hash, saved.dependency_hash)

        note = listening_ai_inputs.project(
            self.session,
            self.runtime,
            profile_id=self.profile_id,
            record_id=self.record_id,
            domain="health",
            group_id=self.group_id,
            task_type=listening_ai_contracts.TASK_NOTE,
            current_form=current_form,
        )
        self.assertEqual(note.payload["listening_text"], "未保存正文")
        self.assertEqual(note.payload["work_date"], "2026-09-10")
        self.assertEqual(
            note.target_hashes["listening_text"],
            listening_ai_contracts.value_hash("未保存正文"),
        )

        goal = listening_ai_inputs.project(
            self.session,
            self.runtime,
            profile_id=self.profile_id,
            record_id=self.record_id,
            domain="health",
            group_id=None,
            task_type=listening_ai_contracts.TASK_GOAL,
            current_form=current_form,
        )
        self.assertEqual(goal.payload["goal"], "未保存目标")
        self.assertEqual(
            goal.payload["groups"][0]["listening_text"], "未保存正文"
        )

        reordered = self._current_form(group_order=[2, 1, 0])
        projection = listening_ai_inputs.project(
            self.session,
            self.runtime,
            profile_id=self.profile_id,
            record_id=self.record_id,
            domain="health",
            group_id=None,
            task_type=listening_ai_contracts.TASK_DOMAIN,
            current_form=reordered,
        )
        self.assertEqual(
            [group["position"] for group in projection.payload["groups"]],
            [0, 1, 2],
        )
        self.assertEqual(
            [group["group_id"] for group in projection.dependencies["current_form_groups"]],
            [self.groups[2]["group_id"], self.groups[1]["group_id"], self.groups[0]["group_id"]],
        )

    def test_service_creates_from_current_form_without_saving_record(self) -> None:
        result = self._create_current_form_task()
        record = listening_service.read_record_no_tx(
            self.session, profile_id=self.profile_id, record_id=self.record_id
        )
        self.assertEqual(record["revision"], self.revision, "generation never saves")
        task = self.session.get(LocalAITask, result["task_id"])
        inp = self.session.get(LocalAIInput, task.input_id)
        self.assertEqual(inp.payload_json["listening_text"], "未保存正文")
        self.assertEqual(inp.dependencies_json["source_mode"], "current_form")
        self.assertTrue(
            listening_ai_inputs.revalidate_source(self.session, task)
        )

    def test_preview_and_adopt_are_bound_to_the_supplied_current_form(self) -> None:
        result = self._create_current_form_task()
        self._finish_note_candidate(result["task_id"], "候选正文")
        candidate = listening_ai_service.get_candidate(
            self.session,
            profile_id=self.profile_id,
            record_id=self.record_id,
            task_id=result["task_id"],
        )
        current_form = self._current_form()
        preview = listening_ai_adoption.preview(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile_id,
            record_id=self.record_id,
            candidate_id=candidate["candidate_id"],
            current_form=current_form,
            launch_id=self.runtime.launch_id,
            session_scope_hash="scope",
        )
        self.assertEqual(
            preview["target_states"]["listening_text"], "eligible"
        )
        self.assertEqual(preview["proposed"]["current"], "未保存正文")

        changed_form = self._current_form(group_text="教师生成后又改了")
        changed = listening_ai_adoption.preview(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile_id,
            record_id=self.record_id,
            candidate_id=candidate["candidate_id"],
            current_form=changed_form,
            launch_id=self.runtime.launch_id,
            session_scope_hash="scope",
        )
        self.assertEqual(
            changed["target_states"]["listening_text"], "changed"
        )
        with self.assertRaises(LocalValidationError):
            listening_ai_adoption.adopt(
                self.session,
                runtime=self.runtime,
                profile_id=self.profile_id,
                record_id=self.record_id,
                request_id=str(uuid.uuid4()),
                expected_revision=preview["revision"],
                preview_token=preview["preview_token"],
                selections=[{"target": "listening_text", "value": "候选正文"}],
                candidate_id=candidate["candidate_id"],
                current_form=changed_form,
                launch_id=self.runtime.launch_id,
                session_scope_hash="scope",
            )
        record = listening_service.read_record_no_tx(
            self.session, profile_id=self.profile_id, record_id=self.record_id
        )
        self.assertEqual(record["revision"], self.revision)

        adopted = listening_ai_adoption.adopt(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile_id,
            record_id=self.record_id,
            request_id=str(uuid.uuid4()),
            expected_revision=preview["revision"],
            preview_token=preview["preview_token"],
            selections=[{"target": "listening_text", "value": "候选正文"}],
            candidate_id=candidate["candidate_id"],
            current_form=current_form,
            launch_id=self.runtime.launch_id,
            session_scope_hash="scope",
        )
        self.assertEqual(adopted["revision_after"], self.revision + 1)

    def test_prompt_guidance_distinguishes_teacher_handwriting_and_ai_draft(self) -> None:
        bundles = {
            (bundle["task_type"], bundle["default_revision"]): bundle
            for bundle in prompt_bundles.PROMPT_BUNDLE_MANIFEST
        }
        note = bundles[("listening_note_draft", 3)]["guidance_defaults_json"]
        group = bundles[("listening_group_notes", 3)]["guidance_defaults_json"]
        goal = bundles[("listening_goal_suggest", 2)]["guidance_defaults_json"]
        domain = bundles[("listening_domain_evaluate", 2)]["guidance_defaults_json"]
        directional = bundles[("directional_revision", 3)]["guidance_defaults_json"]
        for text in (note["text"], group["groups"]):
            self.assertIn("教师", text)
            self.assertIn("字迹", text)
            self.assertIn("AI 拟写", text)
            self.assertIn("模糊", text)
        self.assertIn("AI 拟写", goal["goal"])
        self.assertIn("星级", domain["items"])
        self.assertIn("当前表单", directional["fidelity"])
        self.assertIn("未保存", directional["fidelity"])
