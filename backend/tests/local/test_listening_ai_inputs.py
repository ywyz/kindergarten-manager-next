"""Listening AI input projection and target/dependency independence."""

from __future__ import annotations

import uuid
from datetime import date

from app.local import (
    listening_ai_inputs,
    listening_ai_service,
    listening_service,
    profile_service,
)
from app.local.models import LocalAIInput, LocalAITask
from app.local.normalize import normalize_initialization
from tests.local.support import LocalTestCase


class ListeningAIInputTests(LocalTestCase):
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
                class_name="中班",
                grade="middle",
                term_name="秋季",
                start_date="2026-09-01",
                end_date="2026-12-31",
                school_name="合成园",
            ),
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
        self.domain = dto["domains"][0]
        self.group_id = self.domain["groups"][0]["group_id"]
        listening_service.save_domain(
            self.session,
            profile_id=self.profile_id,
            record_id=self.record_id,
            domain="health",
            request_id=str(uuid.uuid4()),
            expected_revision=1,
            patch={
                "goal": "目标",
                "observation_area": "阅读区",
                "groups": [
                    {"group_id": self.group_id, "listening_text": "孩子说想画太阳。"}
                ],
                "overall_evaluation": "旧综合评价",
                "evaluation": {"health_1": 2},
            },
        )
        self.revision = 2

    def test_payload_has_no_identity_and_targets_do_not_change_dependency(self) -> None:
        projection = listening_ai_inputs.project(
            self.session,
            self.runtime,
            profile_id=self.profile_id,
            record_id=self.record_id,
            domain="health",
            group_id=None,
            task_type="listening_domain_evaluate",
        )
        text = str(projection.payload)
        self.assertNotIn(self.record_id, text)
        self.assertNotIn(self.group_id, text)
        self.assertNotIn("甲", text)
        self.assertNotIn("旧综合评价", text)
        self.assertEqual(projection.target_hashes["overall_evaluation"], __import__("app.local.listening_ai_contracts", fromlist=["value_hash"]).value_hash("旧综合评价"))
        before = projection.dependency_hash
        listening_service.save_domain(
            self.session,
            profile_id=self.profile_id,
            record_id=self.record_id,
            domain="health",
            request_id=str(uuid.uuid4()),
            expected_revision=self.revision,
            patch={"support_strategy": "新支持"},
        )
        self.revision += 1
        projection2 = listening_ai_inputs.project(
            self.session,
            self.runtime,
            profile_id=self.profile_id,
            record_id=self.record_id,
            domain="health",
            group_id=None,
            task_type="listening_domain_evaluate",
        )
        self.assertEqual(before, projection2.dependency_hash)
        self.assertNotEqual(
            projection.target_hashes["support_strategy"],
            projection2.target_hashes["support_strategy"],
        )
        task = LocalAITask(
            profile_id=self.profile_id,
            source_kind="one_to_one_listening",
            source_id=self.record_id,
            listening_record_id=self.record_id,
            listening_domain="health",
            listening_group_id=None,
            task_type="listening_domain_evaluate",
            input_id="missing",
        )
        # A missing input is a false revalidation, never an exception.
        self.assertFalse(listening_ai_inputs.revalidate_source(self.session, task))
