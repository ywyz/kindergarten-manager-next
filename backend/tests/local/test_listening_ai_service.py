"""Listening AI task → claim → candidate → per-target adoption on real SQLite."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import date, datetime

from sqlalchemy import select

from app.local import (
    ai_config_service,
    backup_validate,
    ai_task_service,
    listening_ai_adoption,
    listening_ai_service,
    listening_service,
    listening_templates,
    profile_service,
)
from app.local.errors import LocalValidationError
from app.local.models import LocalAIOperation, LocalListeningAIAdoption
from app.local.normalize import normalize_initialization
from tests.local.support import LocalTestCase


class ListeningAIServiceTests(LocalTestCase):
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
        self.group_id = next(
            group["group_id"]
            for domain in dto["domains"]
            if domain["domain"] == "health"
            for group in domain["groups"]
            if group["position"] == 0
        )
        listening_service.save_domain(
            self.session,
            profile_id=self.profile_id,
            record_id=self.record_id,
            domain="health",
            request_id=str(uuid.uuid4()),
            expected_revision=1,
            patch={
                "goal": "观察目标",
                "groups": [
                    {
                        "group_id": self.group_id,
                        "listening_text": "孩子说想画太阳。",
                    }
                ],
            },
        )
        self.revision = 2

    def _candidate(self, task_id: str) -> dict:
        return listening_ai_service.get_candidate(
            self.session,
            profile_id=self.profile_id,
            record_id=self.record_id,
            task_id=task_id,
        )

    def _run_candidate(self, task_type: str, candidate: dict, group_id=None) -> dict:
        result, _created = listening_ai_service.create_task(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile_id,
            record_id=self.record_id,
            domain="health",
            group_id=group_id,
            task_type=task_type,
            expected_revision=self.revision,
            request_id=str(uuid.uuid4()),
        )
        claim = ai_task_service.claim_next(
            self.runtime, now=datetime.now(), started_ticks=0
        )
        self.assertIsNotNone(claim)
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
                            candidate, ensure_ascii=False
                        ),
                    },
                    datetime.now(),
                )
            )
        finally:
            final_session.close()
        return result

    def test_note_then_domain_sequential_adoption_and_replay(self) -> None:
        note_result = self._run_candidate(
            "listening_note_draft",
            {"text": "孩子指着太阳说想画下来。", "uncertainties": ["需核实"]},
            self.group_id,
        )
        note_cand = self._candidate(note_result["task_id"])
        preview = listening_ai_adoption.preview(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile_id,
            record_id=self.record_id,
            candidate_id=note_cand["candidate_id"],
            launch_id=self.runtime.launch_id,
            session_scope_hash="scope",
        )
        request = str(uuid.uuid4())
        adopted = listening_ai_adoption.adopt(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile_id,
            record_id=self.record_id,
            request_id=request,
            expected_revision=preview["revision"],
            preview_token=preview["preview_token"],
            selections=[
                {"target": "listening_text", "value": "孩子指着太阳说想画下来。"}
            ],
            candidate_id=note_cand["candidate_id"],
            launch_id=self.runtime.launch_id,
            session_scope_hash="scope",
        )
        self.assertEqual(len(adopted["adopted"]), 1)
        self.assertEqual(adopted["revision_after"], 3)
        receipt = listening_ai_service.get_operation(
            self.session,
            profile_id=self.profile_id,
            record_id=self.record_id,
            request_id=request,
        )
        self.assertEqual(receipt["operation_kind"], "listening_ai_adopt")
        self.assertEqual(receipt["result"]["domain"], "health")
        self.revision = 3
        session = self.runtime.session()
        try:
            ledger = session.scalars(
                select(LocalListeningAIAdoption).where(
                    LocalListeningAIAdoption.record_id == self.record_id
                )
            ).all()
            self.assertEqual(len(ledger), 1)
            replay = listening_ai_adoption.adopt(
                session,
                runtime=self.runtime,
                profile_id=self.profile_id,
                record_id=self.record_id,
                request_id=request,
                expected_revision=preview["revision"],
                preview_token=preview["preview_token"],
                selections=[
                    {
                        "target": "listening_text",
                        "value": "孩子指着太阳说想画下来。",
                    }
                ],
                candidate_id=note_cand["candidate_id"],
                launch_id=self.runtime.launch_id,
                session_scope_hash="scope",
            )
            self.assertTrue(replay["replayed"])
        finally:
            session.close()

        template = listening_templates.get_template("middle", "health")
        items = [
            {
                "item_id": item.item_id,
                "stars": 2 if index == 0 else None,
                "basis": "材料可见依据" if index == 0 else "不足",
            }
            for index, item in enumerate(template.items)
        ]
        domain_result = self._run_candidate(
            "listening_domain_evaluate",
            {
                "overall_evaluation": "综合评价建议",
                "support_strategy": "支持策略建议",
                "items": list(reversed(items)),
            },
        )
        domain_cand = self._candidate(domain_result["task_id"])
        preview2 = listening_ai_adoption.preview(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile_id,
            record_id=self.record_id,
            candidate_id=domain_cand["candidate_id"],
            launch_id=self.runtime.launch_id,
            session_scope_hash="scope",
        )
        self.assertEqual(
            preview2["target_states"]["support_strategy"], "eligible"
        )
        support = listening_ai_adoption.adopt(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile_id,
            record_id=self.record_id,
            request_id=str(uuid.uuid4()),
            expected_revision=preview2["revision"],
            preview_token=preview2["preview_token"],
            selections=[{"target": "support_strategy", "value": "支持策略建议"}],
            candidate_id=domain_cand["candidate_id"],
            launch_id=self.runtime.launch_id,
            session_scope_hash="scope",
        )
        self.revision = support["revision_after"]
        preview3 = listening_ai_adoption.preview(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile_id,
            record_id=self.record_id,
            candidate_id=domain_cand["candidate_id"],
            launch_id=self.runtime.launch_id,
            session_scope_hash="scope",
        )
        self.assertEqual(
            preview3["target_states"]["support_strategy"], "adopted"
        )
        self.assertEqual(
            preview3["target_states"][template.items[0].item_id], "eligible"
        )
        self.assertEqual(
            preview3["target_states"]["overall_evaluation"], "eligible"
        )
        star = listening_ai_adoption.adopt(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile_id,
            record_id=self.record_id,
            request_id=str(uuid.uuid4()),
            expected_revision=preview3["revision"],
            preview_token=preview3["preview_token"],
            selections=[
                {"target": template.items[0].item_id, "stars": 1}
            ],
            candidate_id=domain_cand["candidate_id"],
            launch_id=self.runtime.launch_id,
            session_scope_hash="scope",
        )
        self.assertGreater(star["revision_after"], self.revision)
        connection = sqlite3.connect(self.runtime.db_path)
        try:
            backup_validate._listening_ai_chain(connection)
        finally:
            connection.close()
        final = listening_service.read_record(
            self.session, profile_id=self.profile_id, record_id=self.record_id
        )
        health = next(
            item for item in final["domains"] if item["domain"] == "health"
        )
        self.assertEqual(health["support_strategy"], "支持策略建议")
        self.assertIsNone(health["overall_evaluation"])
        self.assertEqual(health["evaluation"][0]["stars"], 1)
        # The same candidate/target cannot be adopted by a new request.
        self.revision = star["revision_after"]
        preview4 = listening_ai_adoption.preview(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile_id,
            record_id=self.record_id,
            candidate_id=domain_cand["candidate_id"],
            launch_id=self.runtime.launch_id,
            session_scope_hash="scope",
        )
        self.assertEqual(
            preview4["target_states"][template.items[0].item_id], "adopted"
        )
        with self.assertRaises(LocalValidationError):
            listening_ai_adoption.adopt(
                self.session,
                runtime=self.runtime,
                profile_id=self.profile_id,
                record_id=self.record_id,
                request_id=str(uuid.uuid4()),
                expected_revision=preview4["revision"],
                preview_token=preview4["preview_token"],
                selections=[
                    {"target": template.items[0].item_id, "stars": 1}
                ],
                candidate_id=domain_cand["candidate_id"],
                launch_id=self.runtime.launch_id,
                session_scope_hash="scope",
            )

    def test_create_receipt_does_not_create_second_task(self) -> None:
        request = str(uuid.uuid4())
        first, created = listening_ai_service.create_task(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile_id,
            record_id=self.record_id,
            domain="health",
            group_id=self.group_id,
            task_type="listening_note_draft",
            expected_revision=self.revision,
            request_id=request,
        )
        self.assertTrue(created)
        second, created_again = listening_ai_service.create_task(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile_id,
            record_id=self.record_id,
            domain="health",
            group_id=self.group_id,
            task_type="listening_note_draft",
            expected_revision=self.revision,
            request_id=request,
        )
        self.assertFalse(created_again)
        self.assertEqual(first["task_id"], second["task_id"])
