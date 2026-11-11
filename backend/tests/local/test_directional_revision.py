"""Directional revision projection, binding, candidate and HTTP tests."""

from __future__ import annotations

import json
import socket
import sqlite3
import time
import uuid
from datetime import date, datetime
from typing import Any

from alembic import command
from sqlalchemy import select

from app.local import (
    ai_config_service,
    ai_task_service,
    directional_revision,
    directional_revision_contracts as contracts,
    listening_ai_service,
    listening_service,
    profile_service,
    weekly_ai_adoption,
    weekly_ai_service,
    weekly_plan_service,
)
from app.local.ai_executor import AiExecutor
from app.local.errors import (
    LocalAiNotFound,
    LocalAiRequestConflict,
    LocalAiTaskActive,
    LocalValidationError,
)
from app.local.migrate import alembic_config, head_revision
from app.local.models import (
    LocalAICandidate,
    LocalAIInput,
    LocalAIOperation,
    LocalAITask,
    LocalListeningAIAdoption,
)
from app.local.normalize import normalize_initialization
from app.local.prompt_bundles import CandidateInvalid
from tests.local import w3_tls
from tests.local.support import LocalTestCase, query_scalar
from tests.local.test_weekly_ai_service import WeeklyAIServiceFixture
from tests.local.w3_tls import TEST_HOST


class _ReadyExecutor:
    def is_runnable(self) -> bool:
        return True

    def is_frozen(self) -> bool:
        return False

    def notify(self) -> None:
        return None


def _selection(text: str) -> dict[str, Any]:
    return {
        "start": 0,
        "end": directional_revision.utf16_length(text),
        "text": text,
    }


class DirectionalServiceTests(LocalTestCase):
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
                display_name="王老师",
                class_name="中一班",
                grade="middle",
                term_name="2026 年秋季学期",
                start_date="2026-09-01",
                end_date="2026-12-31",
                school_name="示范幼儿园",
            ),
        )
        self.session.commit()
        context = profile_service.require_context(self.session, date.today())
        self.profile_id = context.profile.id
        record = listening_service.create_record(
            self.session,
            profile_id=self.profile_id,
            request_id=str(uuid.uuid4()),
            term_id=context.term.id,
            child_name="小明",
        )
        self.session.commit()
        self.record_id = record["record_id"]
        dto = listening_service.read_record_no_tx(
            self.session, profile_id=self.profile_id, record_id=self.record_id
        )
        self.group_id = dto["domains"][0]["groups"][0]["group_id"]
        saved, _changed = listening_service.domain_patch_kernel_no_tx(
            self.session,
            profile_id=self.profile_id,
            record_id=self.record_id,
            domain="health",
            expected_revision=1,
            patch={
                "goal": "观察目标",
                "overall_evaluation": "综合评价",
                "support_strategy": "支持策略",
                "groups": [
                    {
                        "group_id": self.group_id,
                        "listening_text": "小明说：老师你看。",
                    }
                ],
            },
            now=datetime.now(),
        )
        self.session.commit()
        self.revision = saved["revision"]
        ai_config_service.patch_config(
            self.session,
            expected_ai_config_version=0,
            base_url="https://api.deepseek.com/v1",
            model="directional-fake",
            secret="synthetic-secret",
            secret_provided=True,
            request_id=str(uuid.uuid4()),
            credential_root=self.runtime.credential_root,
        )
        self.session.commit()

    def _create(self, *, scope: dict[str, Any], field_text: str, selection: dict[str, Any], instruction: str, request_id: str | None = None):
        return ai_task_service.create_directional_revision_task(
            self.session,
            runtime=self.runtime,
            request_id=request_id or str(uuid.uuid4()),
            scope=scope,
            field_text=field_text,
            selection=selection,
            instruction=instruction,
        )

    def _record_scope(self, **overrides):
        scope = {
            "kind": "listening_record",
            "record_id": self.record_id,
            "version": self.revision,
            "domain": "health",
            "group_id": self.group_id,
            "field": "listening_text",
        }
        scope.update(overrides)
        return scope

    def _input(self, task_id: str) -> LocalAIInput:
        task = self.session.get(LocalAITask, task_id)
        return self.session.get(LocalAIInput, task.input_id)

    def _claim(self, task_id: str):
        claim = ai_task_service.claim_next(
            self.runtime, now=datetime.now(), started_ticks=0
        )
        self.assertIsNotNone(claim)
        self.assertEqual(claim.task_id, task_id)
        self.assertTrue(
            ai_task_service.commit_dispatch_mark(
                self.session, claim, datetime.now()
            )
        )
        return claim

    def _finish(self, claim, candidate: dict[str, Any]) -> bool:
        return ai_task_service.finalize_success(
            self.session,
            claim,
            {
                "kind": "success",
                "candidate_text": json.dumps(candidate, ensure_ascii=False),
            },
            datetime.now(),
        )

    def _payload(self, task_id: str) -> dict[str, Any]:
        task = self.session.get(LocalAITask, task_id)
        return directional_revision.task_payload(self.session, task)

    def test_partial_astral_selection_and_private_name_restore(self) -> None:
        text = "前文😀小明说：老师你看。"
        start = directional_revision.utf16_length("前文😀")
        selected = "小明说：老师你看。"
        result, created = self._create(
            scope=self._record_scope(),
            field_text=text,
            selection={
                "start": start,
                "end": start + directional_revision.utf16_length(selected),
                "text": selected,
            },
            instruction="请保留幼儿原话，只把语气写清楚。",
        )
        self.assertTrue(created)
        inp = self._input(result["id"])
        serialized = json.dumps(inp.payload_json, ensure_ascii=False)
        self.assertNotIn("小明", serialized)
        self.assertNotIn(self.record_id, serialized)
        self.assertNotIn(self.group_id, serialized)
        self.assertIn("[[KGM", serialized)
        claim = self._claim(result["id"])
        self.assertTrue(
            self._finish(
                claim,
                {
                    "status": "proposed",
                    "replacement": "[[KGM1]]说：“老师，你看。”",
                    "question": "",
                },
            )
        )
        payload = self._payload(result["id"])
        self.assertEqual(payload["status"], "succeeded")
        self.assertEqual(
            payload["candidate"]["replacement"], "小明说：“老师，你看。”"
        )
        self.assertIn("幼儿原话", payload["candidate"]["notice"])
        record = listening_service.read_record_no_tx(
            self.session, profile_id=self.profile_id, record_id=self.record_id
        )
        self.assertEqual(record["revision"], self.revision)

    def test_selection_cannot_cut_surrogate_or_cross_name(self) -> None:
        with self.assertRaises(LocalValidationError):
            self._create(
                scope=self._record_scope(),
                field_text="😀",
                selection={"start": 1, "end": 2, "text": "\udc00"},
                instruction="改",
            )
        with self.assertRaises(LocalValidationError):
            self._create(
                scope=self._record_scope(),
                field_text="前文小明后文",
                selection={"start": 3, "end": 5, "text": "明后"},
                instruction="改",
            )

    def test_context_window_avoids_surrogate_split_and_name_fragments(self) -> None:
        text = "甲" * 159 + "😀" + "乙" * 157 + "小明" + "丙" * 20
        start = 320
        selected = "丙"
        result, created = self._create(
            scope=self._record_scope(),
            field_text=text,
            selection={
                "start": start,
                "end": start + 1,
                "text": selected,
            },
            instruction="只改一个字",
        )
        self.assertTrue(created)
        inp = self._input(result["id"])
        payload = inp.payload_json
        self.assertNotIn("明", payload["context_before"])
        self.assertNotIn("小", payload["context_before"])
        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("小明", serialized)

    def test_instruction_is_redacted_separately(self) -> None:
        text = "小明说：老师你看。"
        result, _created = self._create(
            scope=self._record_scope(),
            field_text=text,
            selection=_selection(text),
            instruction="把王老师和小明的句子改顺，不要出现2026-11-10。",
        )
        inp = self._input(result["id"])
        serialized = json.dumps(inp.payload_json, ensure_ascii=False)
        self.assertNotIn("王老师", serialized)
        self.assertNotIn("小明", serialized)
        self.assertNotIn("2026-11-10", serialized)
        self.assertIn("[[KGM", serialized)

    def test_scope_optional_keys_and_wrong_target(self) -> None:
        normalized = directional_revision.normalize_request(
            scope={
                "kind": "weekly_candidate",
                "record_id": "plan-1",
                "version": 2,
                "candidate_id": "candidate-1",
                "field": "slot.collective_1.name",
            },
            field_text="旧名",
            selection=_selection("旧名"),
            instruction="改名",
        )
        self.assertIsNone(normalized["scope"]["domain"])
        self.assertIsNone(normalized["scope"]["group_id"])
        with self.assertRaises(LocalValidationError):
            directional_revision.normalize_request(
                scope={
                    "kind": "weekly_candidate",
                    "record_id": "plan-1",
                    "version": 2,
                    "candidate_id": "candidate-1",
                    "field": "slot.collective_1.name",
                    "extra": "x",
                },
                field_text="旧名",
                selection=_selection("旧名"),
                instruction="改名",
            )
        with self.assertRaises(LocalValidationError):
            self._create(
                scope=self._record_scope(group_id=None, field="listening_text"),
                field_text="正文",
                selection=_selection("正文"),
                instruction="改",
            )

    def test_listening_candidate_allows_unrelated_save_but_keeps_original_revision(self) -> None:
        note = "小明说：老师你看。"
        created, _ = listening_ai_service.create_task(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile_id,
            record_id=self.record_id,
            domain="health",
            group_id=self.group_id,
            task_type="listening_note_draft",
            expected_revision=self.revision,
            request_id=str(uuid.uuid4()),
        )
        claim = self._claim(created["task_id"])
        self.assertTrue(
            self._finish(
                claim,
                {"text": "小明说想画太阳。", "uncertainties": []},
            )
        )
        candidate = self.session.scalars(
            select(LocalAICandidate).where(
                LocalAICandidate.task_id == created["task_id"]
            )
        ).one()
        saved, _ = listening_service.domain_patch_kernel_no_tx(
            self.session,
            profile_id=self.profile_id,
            record_id=self.record_id,
            domain="language",
            expected_revision=self.revision,
            patch={"goal": "另一个领域目标"},
            now=datetime.now(),
        )
        self.session.commit()
        current_revision = saved["revision"]
        result, is_new = self._create(
            scope={
                "kind": "listening_candidate",
                "record_id": self.record_id,
                "version": current_revision,
                "candidate_id": candidate.id,
                "domain": "health",
                "group_id": self.group_id,
                "field": "listening_text",
            },
            field_text="小明说想画太阳。",
            selection=_selection("小明说想画太阳。"),
            instruction="改得更具体",
        )
        self.assertTrue(is_new)
        inp = self._input(result["id"])
        self.assertEqual(inp.source_revision, current_revision)
        self.assertEqual(
            inp.dependencies_json["candidate_source_revision"],
            self.revision,
        )
        task = self.session.get(LocalAITask, result["id"])
        self.assertTrue(
            directional_revision.revalidate_source(self.session, task)
        )
        saved2, _ = listening_service.domain_patch_kernel_no_tx(
            self.session,
            profile_id=self.profile_id,
            record_id=self.record_id,
            domain="social",
            expected_revision=current_revision,
            patch={"goal": "再次保存"},
            now=datetime.now(),
        )
        self.session.commit()
        self.assertFalse(
            directional_revision.revalidate_source(self.session, task)
        )
        self.assertGreater(saved2["revision"], current_revision)

    def test_listening_candidate_wrong_domain_or_adopted_target_rejected(self) -> None:
        created, _ = listening_ai_service.create_task(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile_id,
            record_id=self.record_id,
            domain="health",
            group_id=self.group_id,
            task_type="listening_note_draft",
            expected_revision=self.revision,
            request_id=str(uuid.uuid4()),
        )
        claim = self._claim(created["task_id"])
        self.assertTrue(
            self._finish(
                claim, {"text": "小明说想画太阳。", "uncertainties": []}
            )
        )
        candidate = self.session.scalars(
            select(LocalAICandidate).where(
                LocalAICandidate.task_id == created["task_id"]
            )
        ).one()
        with self.assertRaises(LocalValidationError):
            self._create(
                scope={
                    "kind": "listening_candidate",
                    "record_id": self.record_id,
                    "version": self.revision,
                    "candidate_id": candidate.id,
                    "domain": "health",
                    "group_id": self.group_id,
                    "field": "goal",
                },
                field_text="观察目标",
                selection=_selection("观察目标"),
                instruction="改",
            )
        operation_id = uuid.uuid4().hex
        self.session.add(
            LocalAIOperation(
                id=operation_id,
                profile_id=self.profile_id,
                request_id=str(uuid.uuid4()),
                operation_kind="listening_ai_adopt",
                request_fingerprint="c" * 64,
                fingerprint_kind="sha256",
                fingerprint_key_id=None,
                result_json={},
                created_at=datetime.now(),
            )
        )
        self.session.flush()
        self.session.add(
            LocalListeningAIAdoption(
                id=uuid.uuid4().hex,
                profile_id=self.profile_id,
                source_kind="one_to_one_listening",
                record_id=self.record_id,
                domain="health",
                group_id=self.group_id,
                scope_key=self.group_id,
                target_key="listening_text",
                candidate_id=candidate.id,
                input_id=candidate.input_id,
                before_hash="a" * 64,
                after_hash="b" * 64,
                revision_before=self.revision,
                revision_after=self.revision,
                operation_id=operation_id,
                created_at=datetime.now(),
            )
        )
        self.session.commit()
        with self.assertRaises(LocalValidationError):
            self._create(
                scope={
                    "kind": "listening_candidate",
                    "record_id": self.record_id,
                    "version": self.revision,
                    "candidate_id": candidate.id,
                    "domain": "health",
                    "group_id": self.group_id,
                    "field": "listening_text",
                },
                field_text="小明说想画太阳。",
                selection=_selection("小明说想画太阳。"),
                instruction="改",
            )

    def test_idempotency_and_active_task(self) -> None:
        request_id = str(uuid.uuid4())
        text = "小明说：老师你看。"
        result, created = self._create(
            scope=self._record_scope(),
            field_text=text,
            selection=_selection(text),
            instruction="改",
            request_id=request_id,
        )
        self.assertTrue(created)
        replay, created_again = self._create(
            scope=self._record_scope(),
            field_text=text,
            selection=_selection(text),
            instruction="改",
            request_id=request_id,
        )
        self.assertFalse(created_again)
        self.assertEqual(replay["id"], result["id"])
        with self.assertRaises(LocalAiRequestConflict):
            self._create(
                scope=self._record_scope(),
                field_text=text,
                selection=_selection(text),
                instruction="不同意见",
                request_id=request_id,
            )
        with self.assertRaises(LocalAiTaskActive):
            self._create(
                scope=self._record_scope(),
                field_text=text,
                selection=_selection(text),
                instruction="另一任务",
            )

    def test_http_subset_scope_and_get(self) -> None:
        server = self.start_server(self.runtime, executor=_ReadyExecutor())
        client = server.client()
        text = "小明说：老师你看。"
        body = {
            "request_id": str(uuid.uuid4()),
            "scope": {
                "kind": "listening_record",
                "record_id": self.record_id,
                "version": self.revision,
                "domain": "health",
                "group_id": self.group_id,
                "field": "listening_text",
            },
            "field_text": text,
            "selection": _selection(text),
            "instruction": "改",
        }
        status, payload = client.post("/api/local/directional-revisions", body)
        self.assertEqual(status, 202, payload)
        self.assertEqual(payload["status"], "pending")
        status, replay = client.post("/api/local/directional-revisions", body)
        self.assertEqual(status, 200, replay)
        self.assertEqual(replay["id"], payload["id"])
        status, task = client.get(
            f"/api/local/directional-revisions/{payload['id']}"
        )
        self.assertEqual(status, 200, task)
        self.assertEqual(task["id"], payload["id"])
        status, missing = client.get(
            f"/api/local/directional-revisions/{uuid.uuid4().hex}"
        )
        self.assertEqual(status, 404, missing)

    def test_real_executor_with_fake_tls_provider(self) -> None:
        ca_dir = self.tmp_root / "direction-ca"
        _cert, _key, ca_pem = w3_tls.create_ca(ca_dir)
        leaf_cert, leaf_key = w3_tls.create_leaf(ca_dir, self.tmp_root / "leaf")

        def reply_factory(request: bytes) -> bytes:
            _head, _, body = request.partition(b"\r\n\r\n")
            outer = json.loads(body.decode("utf-8"))
            payload = json.loads(outer["messages"][1]["content"])
            self.assertNotIn("小明", payload["selected_text"])
            candidate = {
                "status": "proposed",
                "replacement": "[[KGM1]]说：“老师，你看。”",
                "question": "",
            }
            return w3_tls.envelope(
                json.dumps(candidate, ensure_ascii=False),
                usage={"prompt_tokens": 4, "completion_tokens": 5},
            )

        server = w3_tls.TlsServer(
            cert=leaf_cert, key=leaf_key, reply_factory=reply_factory
        ).start()
        self.addCleanup(server.stop)
        ai_config_service.patch_config(
            self.session,
            expected_ai_config_version=1,
            base_url=f"https://{TEST_HOST}/v1",
            model="directional-fake-tls",
            secret="synthetic-secret",
            secret_provided=True,
            request_id=str(uuid.uuid4()),
            credential_root=self.runtime.credential_root,
        )
        self.session.commit()
        executor = AiExecutor(
            self.runtime,
            synthetic_transport={
                "resolution": [
                    {
                        "family": socket.AF_INET,
                        "ip": "127.0.0.1",
                        "port": server.port,
                    }
                ],
                "ca_pem": ca_pem.decode("utf-8"),
            },
        )
        executor.start()
        self.addCleanup(executor.stop_and_drain)
        text = "小明说：老师你看。"
        result, _created = self._create(
            scope=self._record_scope(),
            field_text=text,
            selection=_selection(text),
            instruction="整理语气",
        )
        deadline = time.monotonic() + 40
        status = "pending"
        while time.monotonic() < deadline:
            status = query_scalar(
                self.runtime.db_path,
                "SELECT status FROM local_ai_tasks WHERE id = ?",
                (result["id"],),
            )
            if status in ("succeeded", "failed", "outcome_unknown", "cancelled"):
                break
            time.sleep(0.05)
        self.assertEqual(status, "succeeded")
        self.session.expire_all()
        payload = self._payload(result["id"])
        self.assertEqual(
            payload["candidate"]["replacement"], "小明说：“老师，你看。”"
        )
        self.assertEqual(len(server.requests), 1)


class DirectionalWeeklyTests(WeeklyAIServiceFixture):
    def _claim(self, task_id: str):
        claim = ai_task_service.claim_next(
            self.runtime, now=datetime.now(), started_ticks=0
        )
        self.assertIsNotNone(claim)
        self.assertEqual(claim.task_id, task_id)
        self.assertTrue(
            ai_task_service.commit_dispatch_mark(
                self.session, claim, datetime.now()
            )
        )
        return claim

    def _finish(self, claim, candidate: dict[str, Any]) -> bool:
        return ai_task_service.finalize_success(
            self.session,
            claim,
            {
                "kind": "success",
                "candidate_text": json.dumps(candidate, ensure_ascii=False),
            },
            datetime.now(),
        )

    def _create_candidate_task(
        self,
        *,
        candidate_id: str,
        version: int,
        field: str,
        field_text: str,
        selection: dict[str, Any],
    ):
        return ai_task_service.create_directional_revision_task(
            self.session,
            runtime=self.runtime,
            request_id=str(uuid.uuid4()),
            scope={
                "kind": "weekly_candidate",
                "record_id": self.plan_id,
                "version": version,
                "candidate_id": candidate_id,
                "field": field,
            },
            field_text=field_text,
            selection=selection,
            instruction="按教师意见修改",
        )

    def test_weekly_candidate_uses_current_draft_and_old_candidate_source(self) -> None:
        _task_id, candidate_id = self._succeed_games()
        save = weekly_plan_service.save_draft(
            self.session,
            profile_id=self.profile.id,
            request_id=str(uuid.uuid4()),
            plan_id=self.plan_id,
            expected_draft_version=self.version,
            patch={"weekly_columns": {"key_week_focus": "无关栏目已改"}},
        )
        self.session.expire_all()
        current_version = save["draft"]["version"]
        candidate = self.session.get(LocalAICandidate, candidate_id)
        name = candidate.raw_candidate_json["outdoor_game_slots"]["collective_1"]["name"]
        result, created = self._create_candidate_task(
            candidate_id=candidate_id,
            version=current_version,
            field="slot.collective_1.name",
            field_text=name,
            selection=_selection(name),
        )
        self.assertTrue(created)
        inp = self.session.get(LocalAIInput, self.session.get(LocalAITask, result["id"]).input_id)
        self.assertEqual(inp.source_revision, current_version)
        self.assertEqual(inp.dependencies_json["candidate_source_revision"], self.version)
        self.assertEqual(
            inp.dependencies_json["weekly_draft_id"],
            save["draft"]["id"],
        )
        task = self.session.get(LocalAITask, result["id"])
        self.assertTrue(directional_revision.revalidate_source(self.session, task))
        claim = self._claim(result["id"])
        self.assertTrue(
            self._finish(
                claim,
                {
                    "status": "proposed",
                    "replacement": "新游戏名",
                    "question": "",
                },
            )
        )
        payload = directional_revision.task_payload(self.session, task)
        self.assertEqual(payload["candidate"]["replacement"], "新游戏名")
        self.assertIn("原引用", payload["candidate"]["notice"])

    def test_weekly_candidate_revalidation_uses_new_draft_binding(self) -> None:
        _task_id, candidate_id = self._succeed_games()
        candidate = self.session.get(LocalAICandidate, candidate_id)
        name = candidate.raw_candidate_json["outdoor_game_slots"]["collective_1"]["name"]
        result, _created = self._create_candidate_task(
            candidate_id=candidate_id,
            version=self.version,
            field="slot.collective_1.name",
            field_text=name,
            selection=_selection(name),
        )
        task = self.session.get(LocalAITask, result["id"])
        save = weekly_plan_service.save_draft(
            self.session,
            profile_id=self.profile.id,
            request_id=str(uuid.uuid4()),
            plan_id=self.plan_id,
            expected_draft_version=self.version,
            patch={"weekly_columns": {"home_cooperation": "另一栏已改"}},
        )
        self.session.expire_all()
        self.assertGreater(save["draft"]["version"], self.version)
        self.assertFalse(directional_revision.revalidate_source(self.session, task))

    def test_material_edit_marks_only_rewritten_extraction_as_suggestion(self) -> None:
        original = {
            "items": [
                {
                    "text": "彩纸",
                    "origin": "extracted",
                    "evidence_refs": [{"source_handle": "m1"}],
                },
                {
                    "text": "胶水",
                    "origin": "extracted",
                    "evidence_refs": [{"source_handle": "m2"}],
                },
            ]
        }
        edited = weekly_ai_adoption._apply_candidate_edit(
            "materials",
            original,
            {"items": [{"text": "新彩纸"}, {"text": "胶水"}]},
        )
        self.assertEqual(edited["items"][0]["origin"], "suggested")
        self.assertEqual(edited["items"][0]["evidence_refs"], [])
        self.assertEqual(edited["items"][1]["origin"], "extracted")
        self.assertEqual(
            edited["items"][1]["evidence_refs"], [{"source_handle": "m2"}]
        )

    def test_weekly_wrong_target_and_limits(self) -> None:
        _task_id, candidate_id = self._succeed_games()
        candidate = self.session.get(LocalAICandidate, candidate_id)
        name = candidate.raw_candidate_json["outdoor_game_slots"]["collective_1"]["name"]
        with self.assertRaises(LocalValidationError):
            self._create_candidate_task(
                candidate_id=candidate_id,
                version=self.version,
                field="item.0.text",
                field_text=name,
                selection=_selection(name),
            )
        result, _created = self._create_candidate_task(
            candidate_id=candidate_id,
            version=self.version,
            field="slot.collective_1.name",
            field_text=name,
            selection=_selection(name),
        )
        inp = self.session.get(LocalAIInput, self.session.get(LocalAITask, result["id"]).input_id)
        with self.assertRaises(CandidateInvalid):
            directional_revision.validate_candidate(
                {"status": "proposed", "replacement": "", "question": ""},
                inp,
            )
        with self.assertRaises(CandidateInvalid):
            directional_revision.validate_candidate(
                {"status": "proposed", "replacement": "名" * 81, "question": ""},
                inp,
            )
        with self.assertRaises(CandidateInvalid):
            directional_revision.validate_candidate(
                {
                    "status": "proposed",
                    "replacement": "与原来源一致的新名字",
                    "question": "",
                },
                inp,
            )


class DirectionalCandidateContractTests(LocalTestCase):
    class _Input:
        def __init__(self, dependencies: dict[str, Any]):
            self.dependencies_json = dependencies

    def _deps(self, **overrides):
        deps = {
            "target": "weekly_material",
            "field": "item.0.text",
            "field_text": "彩纸",
            "selection": {"start": 0, "end": 2, "text": "彩纸"},
            "redactions": [],
            "source_identity": {"origin": "extracted"},
        }
        deps.update(overrides)
        return deps

    def test_full_field_constraints_and_legal_listening_deletion(self) -> None:
        inp = self._Input(self._deps())
        with self.assertRaises(CandidateInvalid):
            directional_revision.validate_candidate(
                {"status": "proposed", "replacement": "", "question": ""},
                inp,
            )
        with self.assertRaises(CandidateInvalid):
            directional_revision.validate_candidate(
                {"status": "proposed", "replacement": "材" * 301, "question": ""},
                inp,
            )
        accepted = directional_revision.validate_candidate(
            {"status": "proposed", "replacement": "新彩纸", "question": ""},
            inp,
        )
        self.assertEqual(accepted["status"], "proposed")
        listening = self._Input(
            self._deps(
                target="listening_text",
                field="listening_text",
                field_text="旧正文",
                selection={"start": 0, "end": 3, "text": "旧正文"},
                source_identity={},
            )
        )
        deleted = directional_revision.validate_candidate(
            {"status": "proposed", "replacement": "", "question": ""},
            listening,
        )
        self.assertEqual(deleted["replacement"], "")
        column = self._Input(
            self._deps(
                target="weekly_column",
                field="text",
                field_text="栏目正文",
                selection={"start": 0, "end": 4, "text": "栏目正文"},
                source_identity={},
            )
        )
        with self.assertRaises(CandidateInvalid):
            directional_revision.validate_candidate(
                {"status": "proposed", "replacement": "", "question": ""},
                column,
            )

    def test_clarify_no_change_and_source_claim(self) -> None:
        inp = self._Input(self._deps())
        clarify = directional_revision.validate_candidate(
            {"status": "clarify", "replacement": None, "question": "改哪一项？"},
            inp,
        )
        self.assertEqual(clarify["status"], "clarify")
        self.assertEqual(clarify["notice"], "")
        no_change = directional_revision.validate_candidate(
            {"status": "no_change", "replacement": None, "question": ""},
            inp,
        )
        self.assertEqual(no_change["status"], "no_change")
        with self.assertRaises(CandidateInvalid):
            directional_revision.validate_candidate(
                {"status": "clarify", "replacement": None, "question": ""},
                inp,
            )
        with self.assertRaises(CandidateInvalid):
            directional_revision.validate_candidate(
                {
                    "status": "proposed",
                    "replacement": "已核对来源，彩纸",
                    "question": "",
                },
                inp,
            )


class DirectionalMigrationTests(LocalTestCase):
    def test_0018_to_0019_preserves_old_rows_and_indexes(self) -> None:
        db = self.tmp_root / "directional-upgrade.db"
        command.upgrade(
            alembic_config(db), "20261110_0018_local_curriculum_ai"
        )
        now = datetime.now().isoformat(sep=" ")
        profile_id = "profile-direction-0001"
        class_id = "class-direction-0001"
        term_id = "term-direction-000000001"
        revision_id = "calendar-direction-0001"
        record_id = "listening-direction-001"
        domain = "health"
        operation_id = "operation-direction-001"
        input_id = "input-direction-0000001"
        connection = sqlite3.connect(str(db))
        try:
            connection.execute(
                "INSERT INTO local_profile (id,singleton,display_name,created_at,updated_at) "
                "VALUES (?,1,'定向教师',?,?)",
                (profile_id, now, now),
            )
            connection.execute(
                "INSERT INTO local_classes (id,name,grade,header_teacher_names,"
                "caregiver_name,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                (class_id, "定向班", "middle", "[]", None, now, now),
            )
            connection.execute(
                "INSERT INTO local_terms (id,name,start_date,end_date,"
                "current_calendar_revision_id,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    term_id,
                    "定向学期",
                    "2026-09-01",
                    "2026-12-31",
                    revision_id,
                    now,
                    now,
                ),
            )
            connection.execute(
                "INSERT INTO local_calendar_revisions "
                "(id,term_id,revision_no,library_version,created_by,created_at) "
                "VALUES (?,?,?,?,?,?)",
                (revision_id, term_id, 1, "synthetic", profile_id, now),
            )
            connection.execute(
                "INSERT INTO local_listening_records "
                "(id,profile_id,class_id,term_id,grade,child_name,revision,"
                "created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (record_id, profile_id, class_id, term_id, "middle", "甲", 1, now, now),
            )
            connection.execute(
                "INSERT INTO local_listening_domains "
                "(record_id,domain,template_version,template_sha256,"
                "observation_date_text,adult_count_text,child_age_text,goal,"
                "observation_area,overall_evaluation,support_strategy,"
                "created_at,updated_at) "
                "VALUES (?,?,?,?,NULL,NULL,NULL,NULL,NULL,NULL,NULL,?,?)",
                (record_id, domain, "1", "a" * 64, now, now),
            )
            connection.execute(
                "INSERT INTO local_ai_operations "
                "(id,profile_id,request_id,operation_kind,request_fingerprint,"
                "fingerprint_kind,fingerprint_key_id,result_json,created_at) "
                "VALUES (?,?,?,'ai_task_create',?,'sha256',NULL,'{}',?)",
                (operation_id, profile_id, str(uuid.uuid4()), "b" * 64, now),
            )
            connection.execute(
                "INSERT INTO local_ai_inputs "
                "(id,profile_id,source_kind,source_id,observation_id,"
                "source_revision,daily_plan_id,content_id,content_version,"
                "weekly_plan_id,weekly_draft_id,listening_record_id,"
                "listening_domain,listening_group_id,create_operation_id,"
                "task_type,target_grade,input_schema_version,payload_json,"
                "dependencies_json,dependency_hash,target_hashes_json,created_at) "
                "VALUES (?,?,?,?,NULL,1,NULL,NULL,NULL,NULL,NULL,?,?,NULL,?,'listening_goal_suggest',NULL,1,'{}','{}',?,'{}',?)",
                (
                    input_id,
                    profile_id,
                    "one_to_one_listening",
                    record_id,
                    record_id,
                    domain,
                    operation_id,
                    "c" * 64,
                    now,
                ),
            )
            connection.commit()
        finally:
            connection.close()
        command.upgrade(alembic_config(db), "head")
        connection = sqlite3.connect(str(db))
        try:
            self.assertEqual(
                connection.execute(
                    "SELECT version_num FROM local_alembic_version"
                ).fetchone()[0],
                head_revision(),
            )
            self.assertEqual(
                connection.execute(
                    "SELECT task_type, source_revision FROM local_ai_inputs "
                    "WHERE id=?",
                    (input_id,),
                ).fetchone(),
                ("listening_goal_suggest", 1),
            )
            indexes = {
                row[0]: row[1]
                for row in connection.execute(
                    "SELECT name, sql FROM sqlite_master "
                    "WHERE type='index' AND sql IS NOT NULL"
                )
            }
            for name in (
                "ix_local_ai_tasks_plan_created",
                "ix_local_ai_tasks_status_created",
                "uq_local_ai_tasks_active_per_plan_type",
                "uq_local_ai_tasks_active_listening_goal",
                "ix_local_ai_candidates_plan_created",
            ):
                self.assertIn(name, indexes)
            self.assertIn(
                "listening_goal_suggest",
                indexes["uq_local_ai_tasks_active_listening_goal"],
            )
            self.assertEqual(
                connection.execute("PRAGMA foreign_key_check").fetchall(), []
            )
        finally:
            connection.close()
