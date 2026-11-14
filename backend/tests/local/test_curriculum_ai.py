"""Curriculum AI task lifecycle, private projection and local linkage tests."""

from __future__ import annotations

import json
import socket
import sqlite3
import time
import uuid
from datetime import datetime
from typing import Any

from alembic import command

from app.local import (
    ai_config_service,
    ai_task_service,
    curriculum_ai,
    curriculum_ai_contracts,
    curriculum_content,
    profile_service,
)
from app.local.ai_executor import AiExecutor
from app.local.errors import (
    LocalAiRequestConflict,
    LocalAiSourceChanged,
    LocalValidationError,
)
from app.local.migrate import alembic_config, head_revision
from app.local.models import LocalAIInput, LocalAITask, LocalPromptBundle
from app.local.normalize import normalize_initialization
from app.local.prompt_bundles import CandidateInvalid
from tests.local import w3_tls
from tests.local.support import LocalTestCase, query_scalar
from tests.local.w3_tls import TEST_HOST


class _ReadyExecutor:
    def is_runnable(self) -> bool:
        return True

    def is_frozen(self) -> bool:
        return False


def _content(**overrides: str) -> dict[str, str]:
    content = curriculum_content.empty_content()
    content.update(
        {
            "activity_name": "纸桥怎样更稳",
            "activity_form": "small_group",
            "child_count": "18",
            "organizer": "王老师",
            "recorder": "李老师",
            "institution": "示范幼儿园",
            "class_name": "中一班",
            "activity_date": "2026-11-10",
            "lesson_original": (
                "一、活动目标\n"
                "组织教师：王老师\n"
                "记录人：李老师\n"
                "执教：合成不外传署名\n"
                "目标内容\n"
                "二、活动准备\n"
                "准备内容\n"
                "三、活动过程\n"
                "过程内容"
            ),
        }
    )
    content.update(overrides)
    return content


class CurriculumAIServiceTests(LocalTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.runtime = self.make_runtime()
        self.runtime.launch_id = str(uuid.uuid4())
        session = self.runtime.session()
        try:
            profile_service.initialize(
                session,
                normalize_initialization(
                    request_id=str(uuid.uuid4()),
                    display_name="合成教师",
                    class_name="中一班",
                    grade="middle",
                    term_name="2026 年秋季学期",
                    start_date="2026-09-01",
                    end_date="2026-12-31",
                    school_name="示范幼儿园",
                ),
            )
            session.commit()
            ai_config_service.patch_config(
                session,
                expected_ai_config_version=0,
                base_url="https://api.deepseek.com/v1",
                model="deepseek-v4-flash",
                secret="synthetic-secret",
                secret_provided=True,
                request_id=str(uuid.uuid4()),
                credential_root=self.runtime.credential_root,
            )
            session.commit()
        finally:
            session.close()

    def _create(self, payload: dict[str, Any]):
        session = self.runtime.session()
        try:
            result, created = ai_task_service.create_curriculum_task(
                session,
                runtime=self.runtime,
                request_id=payload.pop("request_id", str(uuid.uuid4())),
                **payload,
            )
            return result, created
        finally:
            session.close()

    def _input(self, task_id: str):
        session = self.runtime.session()
        try:
            task = session.get(LocalAITask, task_id)
            inp = session.get(LocalAIInput, task.input_id)
            return dict(inp.payload_json or {}), dict(inp.dependencies_json or {})
        finally:
            session.close()

    def _claim(self, task_id: str):
        claim = ai_task_service.claim_next(
            self.runtime, now=datetime.now(), started_ticks=0
        )
        self.assertIsNotNone(claim)
        self.assertEqual(claim.task_id, task_id)
        session = self.runtime.session()
        try:
            self.assertTrue(
                ai_task_service.commit_dispatch_mark(
                    session, claim, datetime.now()
                )
            )
        finally:
            session.close()
        return claim

    def _finish(self, claim, candidate: dict[str, Any]) -> bool:
        session = self.runtime.session()
        try:
            return ai_task_service.finalize_success(
                session,
                claim,
                {
                    "kind": "success",
                    "candidate_text": json.dumps(
                        candidate, ensure_ascii=False
                    ),
                },
                datetime.now(),
            )
        finally:
            session.close()

    def _task(self, task_id: str) -> dict[str, Any]:
        session = self.runtime.session()
        try:
            task = session.get(LocalAITask, task_id)
            return curriculum_ai.task_payload(session, task)
        finally:
            session.close()

    def _edit_document(
        self,
        content: dict[str, str],
        revised_blocks: list[dict[str, Any]],
        original_blocks: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "source_hash": curriculum_ai._digest(
                curriculum_ai._normalized_lesson(content["lesson_original"])
            ),
            "original": {"blocks": original_blocks or []},
            "revised": {"blocks": revised_blocks},
        }

    def _split_candidate(
        self, blocks: list[dict[str, str]], questions=None
    ) -> dict[str, Any]:
        result = []
        section = "goals"
        for block in blocks:
            text = str(block["text"])
            kind = "body"
            if text.startswith("一、活动目标"):
                section, kind = "goals", "heading"
            elif text.startswith("二、活动准备"):
                section, kind = "preparation", "heading"
            elif text.startswith("三、活动过程"):
                section, kind = "process", "heading"
            result.append(
                {
                    "source_id": block["source_id"],
                    "quote": text,
                    "section": section,
                    "kind": kind,
                    "text": text,
                }
            )
        return {"blocks": result, "questions": questions or []}

    def test_split_private_projection_prompt_and_restoration(self) -> None:
        content = _content()
        result, _created = self._create(
            {
                "record_id": str(uuid.uuid4()),
                "kind": "split",
                "version": 0,
                "content": content,
            }
        )
        payload, dependencies = self._input(result["id"])
        serialized = json.dumps(payload, ensure_ascii=False)

        for private in (
            "王老师",
            "李老师",
            "合成不外传署名",
            "示范幼儿园",
            "中一班",
            "2026-11-10",
        ):
            self.assertNotIn(private, serialized)
        self.assertIn("[[LOCAL", serialized)
        self.assertIn("lesson_source_hash", dependencies)
        self.assertIn("王老师", dict(dependencies["header_redactions"]).values())
        self.assertTrue(
            any(
                "合成不外传署名" in value
                for value in dict(
                    dependencies["header_redactions"]
                ).values()
            )
        )

        session = self.runtime.session()
        try:
            bundle = session.get(
                LocalPromptBundle,
                (curriculum_ai_contracts.TASK_SPLIT, 1, 1),
            )
            self.assertIn(
                curriculum_ai_contracts.SPLIT_PROMPT,
                bundle.guidance_defaults_json["task"],
            )
        finally:
            session.close()

        claim = self._claim(result["id"])
        self.assertTrue(
            self._finish(claim, self._split_candidate(payload["source_blocks"]))
        )
        task = self._task(result["id"])
        self.assertEqual(task["status"], "succeeded")
        self.assertEqual(task["candidate"]["kind"], "split")
        patch = task["candidate"]["patch"]
        self.assertIn("王老师", patch["lesson_original"])
        self.assertIn("李老师", patch["lesson_original"])
        self.assertIn("合成不外传署名", patch["lesson_original"])
        self.assertIn(
            "王老师",
            task["candidate"]["document"]["original"]["blocks"][1]["text"],
        )

    def test_split_rejects_missing_coverage_and_out_of_order(self) -> None:
        content = _content()
        result, _created = self._create(
            {
                "record_id": str(uuid.uuid4()),
                "kind": "split",
                "version": 0,
                "content": content,
            }
        )
        payload, dependencies = self._input(result["id"])
        session = self.runtime.session()
        try:
            task = session.get(LocalAITask, result["id"])
            task_input = session.get(LocalAIInput, task.input_id)
            blocks = payload["source_blocks"]
            missing = self._split_candidate(blocks[:-1])
            with self.assertRaises(CandidateInvalid):
                curriculum_ai.validate_candidate_for_input(
                    curriculum_ai_contracts.TASK_SPLIT,
                    missing,
                    task_input,
                )
            reversed_blocks = list(reversed(blocks))
            with self.assertRaises(CandidateInvalid):
                curriculum_ai.validate_candidate_for_input(
                    curriculum_ai_contracts.TASK_SPLIT,
                    self._split_candidate(reversed_blocks),
                    task_input,
                )
            fabricated = self._split_candidate(blocks)
            fabricated["blocks"][0]["text"] = "教师示范如何用胶水固定纸桥"
            with self.assertRaises(CandidateInvalid):
                curriculum_ai.validate_candidate_for_input(
                    curriculum_ai_contracts.TASK_SPLIT,
                    fabricated,
                    task_input,
                )
        finally:
            session.close()

    def _successful_split(self, *, question: bool = False):
        content = _content(
            lesson_original=(
                "一、活动目标\n目标内容\n二、活动准备\n准备内容\n"
                "三、活动过程\n过程内容"
            )
        )
        record_id = str(uuid.uuid4())
        result, _created = self._create(
            {
                "record_id": record_id,
                "kind": "split",
                "version": 0,
                "content": content,
            }
        )
        payload, _dependencies = self._input(result["id"])
        questions = (
            [
                {
                    "source_id": "s2",
                    "quote": "目标内容",
                    "question": "目标内容归属请核对",
                    "section": "",
                }
            ]
            if question
            else []
        )
        claim = self._claim(result["id"])
        self.assertTrue(
            self._finish(claim, self._split_candidate(payload["source_blocks"], questions))
        )
        return content, record_id, self._task(result["id"])

    def test_review_requires_resolutions_and_rejects_cross_column(self) -> None:
        content, record_id, split = self._successful_split(question=True)
        with self.assertRaises(LocalValidationError):
            self._create(
                {
                    "record_id": record_id,
                    "kind": "review",
                    "version": 0,
                    "content": content,
                    "split_task_id": split["id"],
                    "resolutions": [],
                }
            )
        result, _created = self._create(
            {
                "record_id": record_id,
                "kind": "review",
                "version": 0,
                "content": content,
                "split_task_id": split["id"],
                "resolutions": [{"id": "q1", "section": "goals"}],
                "instruction": "请重点关注活动过程的顺序。",
            }
        )
        payload, _dependencies = self._input(result["id"])
        self.assertEqual(
            payload["instruction"], "请重点关注活动过程的顺序。"
        )
        self.assertTrue(payload["insertion_anchors"])
        session = self.runtime.session()
        try:
            task = session.get(LocalAITask, result["id"])
            inp = session.get(LocalAIInput, task.input_id)
            invalid = {
                "goals": {"decision": "unchanged", "edits": []},
                "preparation": {"decision": "unchanged", "edits": []},
                "process": {
                    "edits": [
                        {"op": "replace", "target_id": "b1", "text": "跨栏", "note": ""}
                    ]
                },
                "reason": "",
                "questions": [],
            }
            with self.assertRaises(CandidateInvalid):
                curriculum_ai.validate_candidate_for_input(
                    curriculum_ai_contracts.TASK_REVIEW, invalid, inp
                )
        finally:
            session.close()
        claim = self._claim(result["id"])
        valid = {
            "goals": {"decision": "unchanged", "edits": []},
            "preparation": {"decision": "unchanged", "edits": []},
            "process": {
                "edits": [
                    {
                        "op": "replace",
                        "target_id": "b6",
                        "text": "过程内容（调整）",
                        "note": "更具体",
                    }
                ]
            },
            "reason": "建议调整过程。",
            "questions": [],
        }
        self.assertTrue(self._finish(claim, valid))
        task = self._task(result["id"])
        self.assertEqual(task["status"], "succeeded")
        candidate = task["candidate"]
        self.assertEqual(candidate["patch"]["goals_status"], "unchanged")
        self.assertEqual(candidate["patch"]["preparation_status"], "unchanged")
        self.assertEqual(
            candidate["patch"]["process_adjustment"], "过程内容（调整）"
        )
        self.assertEqual(candidate["patch"]["reason"], "建议调整过程。")
        self.assertEqual(candidate["reason_suggestion"], "")

    def test_unchanged_review_has_no_mixed_revision_document(self) -> None:
        content, record_id, split = self._successful_split()
        result, _created = self._create(
            {
                "record_id": record_id,
                "kind": "review",
                "version": 0,
                "content": content,
                "split_task_id": split["id"],
                "resolutions": [],
            }
        )
        claim = self._claim(result["id"])
        self.assertTrue(
            self._finish(
                claim,
                {
                    "goals": {"decision": "unchanged", "edits": []},
                    "preparation": {"decision": "unchanged", "edits": []},
                    "process": {"edits": []},
                    "reason": "可保持原设计。",
                    "questions": [],
                },
            )
        )
        candidate = self._task(result["id"])["candidate"]
        self.assertNotIn("lesson_revised", candidate["patch"])
        self.assertEqual(
            candidate["document"]["revised"]["blocks"], []
        )
        self.assertEqual(candidate["patch"]["reason"], "可保持原设计。")

    def test_review_missing_section_uses_deterministic_anchor(self) -> None:
        content = _content(
            lesson_original="一、活动目标\n目标内容\n三、活动过程\n过程内容"
        )
        record_id = str(uuid.uuid4())
        split_result, _created = self._create(
            {
                "record_id": record_id,
                "kind": "split",
                "version": 0,
                "content": content,
            }
        )
        split_payload, _deps = self._input(split_result["id"])
        split_claim = self._claim(split_result["id"])
        self.assertTrue(
            self._finish(
                split_claim,
                self._split_candidate(split_payload["source_blocks"]),
            )
        )
        split = self._task(split_result["id"])
        review_result, _created = self._create(
            {
                "record_id": record_id,
                "kind": "review",
                "version": 0,
                "content": content,
                "split_task_id": split["id"],
                "resolutions": [],
            }
        )
        review_payload, _deps = self._input(review_result["id"])
        anchors = {
            item["section"]: item["target_id"]
            for item in review_payload["insertion_anchors"]
        }
        self.assertIn("preparation", anchors)
        review_claim = self._claim(review_result["id"])
        self.assertTrue(
            self._finish(
                review_claim,
                {
                    "goals": {"decision": "unchanged", "edits": []},
                    "preparation": {
                        "decision": "adjusted",
                        "edits": [
                            {
                                "op": "insert_after",
                                "target_id": anchors["preparation"],
                                "text": "补充准备",
                                "note": "补齐准备",
                            }
                        ],
                    },
                    "process": {"edits": []},
                    "reason": "补齐准备。",
                    "questions": [],
                },
            )
        )
        candidate = self._task(review_result["id"])["candidate"]
        self.assertEqual(
            candidate["patch"]["preparation_status"], "adjusted"
        )
        self.assertEqual(
            candidate["patch"]["preparation_adjustment"], "补充准备"
        )
        self.assertIn("补充准备", candidate["patch"]["lesson_revised"])

    def test_edit_utf16_selection_links_body_and_keeps_reason_separate(self) -> None:
        content = _content(
            process_adjustment="👩\u200d🔬第一段",
            lesson_revised="开头\n👩\u200d🔬第一段\n结尾",
        )
        selected = "👩\u200d🔬第一段"
        document = {
            "schema_version": 1,
            "source_hash": curriculum_ai._digest(
                curriculum_ai._normalized_lesson(content["lesson_original"])
            ),
            "original": {"blocks": []},
            "revised": {
                "blocks": [
                    {
                        "id": "r1",
                        "source_id": "",
                        "quote": "",
                        "section": "other",
                        "kind": "body",
                        "text": "开头",
                    },
                    {
                        "id": "r2",
                        "source_id": "",
                        "quote": "",
                        "section": "process",
                        "kind": "body",
                        "text": selected,
                    },
                    {
                        "id": "r3",
                        "source_id": "",
                        "quote": "",
                        "section": "other",
                        "kind": "body",
                        "text": "结尾",
                    },
                ]
            },
        }
        record_id = str(uuid.uuid4())
        result, _created = self._create(
            {
                "record_id": record_id,
                "kind": "edit",
                "version": 0,
                "content": content,
                "document": document,
                "instruction": "改得更具体",
                "selection": {
                    "field": "process_adjustment",
                    "start": 0,
                    "end": curriculum_ai_contracts.utf16_length(selected),
                    "text": selected,
                },
            }
        )
        payload, _dependencies = self._input(result["id"])
        self.assertEqual(payload["selection"]["text"], selected)
        self.assertIn("👩\u200d🔬", payload["selection"]["text"])
        self.assertTrue(payload["target_id"].startswith("sel:process_adjustment:"))
        self.assertTrue(
            len(payload["context_before"]) <= 240
            and len(payload["context_after"]) <= 240
        )
        self.assertNotIn("王老师", json.dumps(payload, ensure_ascii=False))
        claim = self._claim(result["id"])
        self.assertTrue(
            self._finish(
                claim,
                {
                    "status": "proposed",
                    "edit": {
                        "target_id": payload["target_id"],
                        "replacement": "新的过程内容",
                    },
                    "question": None,
                    "reason_suggestion": "建议同步修改理由。",
                },
            )
        )
        candidate = self._task(result["id"])["candidate"]
        self.assertEqual(
            candidate["patch"]["process_adjustment"], "新的过程内容"
        )
        self.assertEqual(
            candidate["patch"]["lesson_revised"],
            "开头\n新的过程内容\n结尾",
        )
        self.assertNotIn("reason", candidate["patch"])
        self.assertEqual(candidate["reason_suggestion"], "建议同步修改理由。")
        self.assertEqual(candidate["questions"], [])

    def test_edit_partial_phrase_uses_within_block_offsets(self) -> None:
        content = _content(
            process_adjustment="前文目标短语后文",
            lesson_revised="开头\n前文目标短语后文\n结尾",
        )
        document = self._edit_document(
            content,
            [
                {
                    "id": "r1",
                    "source_id": "",
                    "quote": "",
                    "section": "other",
                    "kind": "body",
                    "text": "开头",
                },
                {
                    "id": "r2",
                    "source_id": "",
                    "quote": "",
                    "section": "process",
                    "kind": "body",
                    "text": "前文目标短语后文",
                },
                {
                    "id": "r3",
                    "source_id": "",
                    "quote": "",
                    "section": "other",
                    "kind": "body",
                    "text": "结尾",
                },
            ],
        )
        result, _created = self._create(
            {
                "record_id": str(uuid.uuid4()),
                "kind": "edit",
                "version": 0,
                "content": content,
                "document": document,
                "instruction": "只改短语",
                "selection": {
                    "field": "process_adjustment",
                    "start": 2,
                    "end": 6,
                    "text": "目标短语",
                },
            }
        )
        payload, _deps = self._input(result["id"])
        claim = self._claim(result["id"])
        self.assertTrue(
            self._finish(
                claim,
                {
                    "status": "proposed",
                    "edit": {
                        "target_id": payload["target_id"],
                        "replacement": "新短语",
                    },
                    "question": None,
                    "reason_suggestion": "",
                },
            )
        )
        candidate = self._task(result["id"])["candidate"]
        self.assertEqual(
            candidate["patch"]["process_adjustment"], "前文新短语后文"
        )
        self.assertEqual(
            candidate["patch"]["lesson_revised"],
            "开头\n前文新短语后文\n结尾",
        )
        self.assertEqual(
            candidate["document"]["revised"]["blocks"][1]["text"],
            "前文新短语后文",
        )
        self.assertEqual(candidate["questions"], [])

    def test_edit_repeated_phrase_uses_document_section_not_phrase(self) -> None:
        content = _content(
            goals_adjustment="相同",
            preparation_adjustment="相同",
            lesson_revised="相同\n相同",
        )
        document = self._edit_document(
            content,
            [
                {
                    "id": "r1",
                    "source_id": "",
                    "quote": "",
                    "section": "goals",
                    "kind": "body",
                    "text": "相同",
                },
                {
                    "id": "r2",
                    "source_id": "",
                    "quote": "",
                    "section": "preparation",
                    "kind": "body",
                    "text": "相同",
                },
            ],
        )
        result, _created = self._create(
            {
                "record_id": str(uuid.uuid4()),
                "kind": "edit",
                "version": 0,
                "content": content,
                "document": document,
                "instruction": "只改准备",
                "selection": {
                    "field": "lesson_revised",
                    "start": 3,
                    "end": 5,
                    "text": "相同",
                },
            }
        )
        payload, _deps = self._input(result["id"])
        claim = self._claim(result["id"])
        self.assertTrue(
            self._finish(
                claim,
                {
                    "status": "proposed",
                    "edit": {
                        "target_id": payload["target_id"],
                        "replacement": "不同准备",
                    },
                    "question": None,
                    "reason_suggestion": "",
                },
            )
        )
        candidate = self._task(result["id"])["candidate"]
        self.assertNotIn("goals_adjustment", candidate["patch"])
        self.assertEqual(
            candidate["patch"]["preparation_adjustment"], "不同准备"
        )
        self.assertEqual(candidate["patch"]["lesson_revised"], "相同\n不同准备")

    def test_edit_manual_counterpart_is_preserved_and_questioned(self) -> None:
        content = _content(
            process_adjustment="段落",
            lesson_revised="开头\n已手工修改\n结尾",
        )
        document = self._edit_document(
            content,
            [
                {
                    "id": "r1",
                    "source_id": "",
                    "quote": "",
                    "section": "other",
                    "kind": "body",
                    "text": "开头",
                },
                {
                    "id": "r2",
                    "source_id": "",
                    "quote": "",
                    "section": "process",
                    "kind": "body",
                    "text": "段落",
                },
                {
                    "id": "r3",
                    "source_id": "",
                    "quote": "",
                    "section": "other",
                    "kind": "body",
                    "text": "结尾",
                },
            ],
        )
        result, _created = self._create(
            {
                "record_id": str(uuid.uuid4()),
                "kind": "edit",
                "version": 0,
                "content": content,
                "document": document,
                "instruction": "改段落",
                "selection": {
                    "field": "process_adjustment",
                    "start": 0,
                    "end": 2,
                    "text": "段落",
                },
            }
        )
        payload, _deps = self._input(result["id"])
        claim = self._claim(result["id"])
        self.assertTrue(
            self._finish(
                claim,
                {
                    "status": "proposed",
                    "edit": {
                        "target_id": payload["target_id"],
                        "replacement": "新段落",
                    },
                    "question": None,
                    "reason_suggestion": "",
                },
            )
        )
        candidate = self._task(result["id"])["candidate"]
        self.assertEqual(candidate["patch"]["process_adjustment"], "新段落")
        self.assertNotIn("lesson_revised", candidate["patch"])
        self.assertTrue(candidate["questions"])

    def test_edit_empty_adjustment_fills_status_and_keeps_reason_separate(self) -> None:
        content = _content(
            goals_original="原目标",
            goals_adjustment="",
            goals_status="unchanged",
        )
        result, _created = self._create(
            {
                "record_id": str(uuid.uuid4()),
                "kind": "edit",
                "version": 0,
                "content": content,
                "instruction": "补充目标",
                "selection": {
                    "field": "goals_adjustment",
                    "start": 0,
                    "end": 0,
                    "text": "",
                },
            }
        )
        payload, _dependencies = self._input(result["id"])
        claim = self._claim(result["id"])
        self.assertTrue(
            self._finish(
                claim,
                {
                    "status": "proposed",
                    "edit": {
                        "target_id": payload["target_id"],
                        "replacement": "补充后的目标",
                    },
                    "question": None,
                    "reason_suggestion": "理由建议，需单独采用。",
                },
            )
        )
        candidate = self._task(result["id"])["candidate"]
        self.assertEqual(
            candidate["patch"]["goals_adjustment"], "补充后的目标"
        )
        self.assertEqual(candidate["patch"]["goals_status"], "adjusted")
        self.assertNotIn("reason", candidate["patch"])
        self.assertEqual(
            candidate["reason_suggestion"], "理由建议，需单独采用。"
        )

    def test_edit_restoring_revised_column_to_original_canonicalizes_both(
        self,
    ) -> None:
        content = _content(
            goals_original="原目标",
            goals_adjustment="新目标",
            goals_status="adjusted",
        )
        result, _created = self._create(
            {
                "record_id": str(uuid.uuid4()),
                "kind": "edit",
                "version": 0,
                "content": content,
                "instruction": "恢复原目标",
                "selection": {
                    "field": "goals_adjustment",
                    "start": 0,
                    "end": curriculum_ai_contracts.utf16_length("新目标"),
                    "text": "新目标",
                },
            }
        )
        payload, _dependencies = self._input(result["id"])
        claim = self._claim(result["id"])
        self.assertTrue(
            self._finish(
                claim,
                {
                    "status": "proposed",
                    "edit": {
                        "target_id": payload["target_id"],
                        "replacement": "原目标",
                    },
                    "question": None,
                    "reason_suggestion": "",
                },
            )
        )
        candidate = self._task(result["id"])["candidate"]
        self.assertEqual(candidate["patch"]["goals_adjustment"], "")
        self.assertEqual(candidate["patch"]["goals_status"], "unchanged")

    def test_edit_original_side_rejects_symbol_change(self) -> None:
        content = _content(goals_original="1+2")
        result, _created = self._create(
            {
                "record_id": str(uuid.uuid4()),
                "kind": "edit",
                "version": 0,
                "content": content,
                "instruction": "整理格式",
                "selection": {
                    "field": "goals_original",
                    "start": 0,
                    "end": 3,
                    "text": "1+2",
                },
            }
        )
        payload, _dependencies = self._input(result["id"])
        session = self.runtime.session()
        try:
            task = session.get(LocalAITask, result["id"])
            inp = session.get(LocalAIInput, task.input_id)
            with self.assertRaises(CandidateInvalid):
                curriculum_ai.validate_candidate_for_input(
                    curriculum_ai_contracts.TASK_EDIT,
                    {
                        "status": "proposed",
                        "edit": {
                            "target_id": payload["target_id"],
                            "replacement": "1-2",
                        },
                        "question": None,
                        "reason_suggestion": "",
                    },
                    inp,
                )
        finally:
            session.close()

    def test_edit_original_side_keeps_decimal_and_allows_line_reflow(
        self,
    ) -> None:
        self.assertNotEqual(
            curriculum_ai._content_signature("1.5米"),
            curriculum_ai._content_signature("5米"),
        )
        self.assertNotEqual(
            curriculum_ai._content_signature("1．5米"),
            curriculum_ai._content_signature("5米"),
        )
        content = _content(goals_original="1.5米\n目标内容")
        selected_text = "1.5米\n目标内容"
        result, _created = self._create(
            {
                "record_id": str(uuid.uuid4()),
                "kind": "edit",
                "version": 0,
                "content": content,
                "instruction": "整理格式",
                "selection": {
                    "field": "goals_original",
                    "start": 0,
                    "end": curriculum_ai_contracts.utf16_length(
                        selected_text
                    ),
                    "text": selected_text,
                },
            }
        )
        payload, _dependencies = self._input(result["id"])
        session = self.runtime.session()
        try:
            task = session.get(LocalAITask, result["id"])
            inp = session.get(LocalAIInput, task.input_id)
            with self.assertRaises(CandidateInvalid):
                curriculum_ai.validate_candidate_for_input(
                    curriculum_ai_contracts.TASK_EDIT,
                    {
                        "status": "proposed",
                        "edit": {
                            "target_id": payload["target_id"],
                            "replacement": "5米\n目标内容",
                        },
                        "question": None,
                        "reason_suggestion": "",
                    },
                    inp,
                )
            accepted = curriculum_ai.validate_candidate_for_input(
                curriculum_ai_contracts.TASK_EDIT,
                {
                    "status": "proposed",
                    "edit": {
                        "target_id": payload["target_id"],
                        "replacement": "1.5米 目标内容",
                    },
                    "question": None,
                    "reason_suggestion": "",
                },
                inp,
            )
            self.assertEqual(
                accepted["patch"]["goals_original"], "1.5米 目标内容"
            )
        finally:
            session.close()

    def test_edit_binds_advertised_target_and_rejects_reteaching_original(self) -> None:
        content = _content(goals_original="原目标")
        result, _created = self._create(
            {
                "record_id": str(uuid.uuid4()),
                "kind": "edit",
                "version": 0,
                "content": content,
                "instruction": "整理格式",
                "selection": {
                    "field": "goals_original",
                    "start": 0,
                    "end": 3,
                    "text": "原目标",
                },
            }
        )
        payload, _deps = self._input(result["id"])
        session = self.runtime.session()
        try:
            task = session.get(LocalAITask, result["id"])
            inp = session.get(LocalAIInput, task.input_id)
            with self.assertRaises(CandidateInvalid):
                curriculum_ai.validate_candidate_for_input(
                    curriculum_ai_contracts.TASK_EDIT,
                    {
                        "status": "proposed",
                        "edit": {
                            "target_id": "selection",
                            "replacement": "原目标。",
                        },
                        "question": None,
                        "reason_suggestion": "",
                    },
                    inp,
                )
            with self.assertRaises(CandidateInvalid):
                curriculum_ai.validate_candidate_for_input(
                    curriculum_ai_contracts.TASK_EDIT,
                    {
                        "status": "proposed",
                        "edit": {
                            "target_id": payload["target_id"],
                            "replacement": "新的教学目标",
                        },
                        "question": None,
                        "reason_suggestion": "",
                    },
                    inp,
                )
            accepted = curriculum_ai.validate_candidate_for_input(
                curriculum_ai_contracts.TASK_EDIT,
                {
                    "status": "proposed",
                    "edit": {
                        "target_id": payload["target_id"],
                        "replacement": "1. 原目标",
                    },
                    "question": None,
                    "reason_suggestion": "",
                },
                inp,
            )
            self.assertEqual(accepted["patch"]["goals_original"], "1. 原目标")
        finally:
            session.close()

    def test_edit_ambiguous_link_keeps_both_texts_and_asks(self) -> None:
        content = _content(
            process_adjustment="重复段落",
            lesson_revised="重复段落\n重复段落",
        )
        result, _created = self._create(
            {
                "record_id": str(uuid.uuid4()),
                "kind": "edit",
                "version": 0,
                "content": content,
                "instruction": "替换",
                "selection": {
                    "field": "process_adjustment",
                    "start": 0,
                    "end": curriculum_ai_contracts.utf16_length("重复段落"),
                    "text": "重复段落",
                },
            }
        )
        payload, _dependencies = self._input(result["id"])
        claim = self._claim(result["id"])
        self.assertTrue(
            self._finish(
                claim,
                {
                    "status": "proposed",
                    "edit": {
                        "target_id": payload["target_id"],
                        "replacement": "新段落",
                    },
                    "question": None,
                    "reason_suggestion": "",
                },
            )
        )
        candidate = self._task(result["id"])["candidate"]
        self.assertEqual(candidate["patch"]["process_adjustment"], "新段落")
        self.assertNotIn("lesson_revised", candidate["patch"])
        self.assertTrue(candidate["questions"])

    def test_request_replay_and_fingerprint_conflict(self) -> None:
        record_id = str(uuid.uuid4())
        request_id = str(uuid.uuid4())
        body = {
            "record_id": record_id,
            "kind": "split",
            "version": 0,
            "content": _content(),
            "request_id": request_id,
        }
        first, created = self._create(dict(body))
        self.assertTrue(created)
        replay, created = self._create(dict(body))
        self.assertFalse(created)
        self.assertEqual(replay["id"], first["id"])
        changed = dict(body)
        changed["content"] = _content(activity_name="另一个活动")
        with self.assertRaises(LocalAiRequestConflict):
            self._create(changed)


class CurriculumAIExecutorTests(LocalTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.runtime = self.make_runtime()
        self.runtime.launch_id = str(uuid.uuid4())
        session = self.runtime.session()
        try:
            profile_service.initialize(
                session,
                normalize_initialization(
                    request_id=str(uuid.uuid4()),
                    display_name="合成教师",
                    class_name="中一班",
                    grade="middle",
                    term_name="秋季",
                    start_date="2026-09-01",
                    end_date="2026-12-31",
                    school_name="示范幼儿园",
                ),
            )
            session.commit()
        finally:
            session.close()

    def test_real_executor_with_fake_tls_provider(self) -> None:
        ca_dir = self.tmp_root / "curriculum-ca"
        _cert, _key, ca_pem = w3_tls.create_ca(ca_dir)
        leaf_cert, leaf_key = w3_tls.create_leaf(ca_dir, self.tmp_root / "leaf")
        content = _content(
            lesson_original="一、活动目标\n目标内容\n二、活动准备\n准备内容\n三、活动过程\n过程内容"
        )
        source = []
        for index, line in enumerate(content["lesson_original"].splitlines()):
            source.append(
                {
                    "source_id": f"s{index + 1}",
                    "quote": line,
                    "section": "goals" if index < 2 else "preparation" if index < 4 else "process",
                    "kind": "body",
                    "text": line,
                }
            )
        candidate = {"blocks": source, "questions": []}
        body = w3_tls.envelope(
            json.dumps(candidate, ensure_ascii=False),
            usage={"prompt_tokens": 4, "completion_tokens": 5},
        )
        server = w3_tls.TlsServer(cert=leaf_cert, key=leaf_key, reply=body).start()
        self.addCleanup(server.stop)
        session = self.runtime.session()
        try:
            ai_config_service.patch_config(
                session,
                expected_ai_config_version=0,
                base_url=f"https://{TEST_HOST}/v1",
                model="curriculum-fake",
                secret="synthetic-secret",
                secret_provided=True,
                request_id=str(uuid.uuid4()),
                credential_root=self.runtime.credential_root,
            )
            session.commit()
        finally:
            session.close()
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
        session = self.runtime.session()
        try:
            result, _created = ai_task_service.create_curriculum_task(
                session,
                runtime=self.runtime,
                record_id=str(uuid.uuid4()),
                kind="split",
                version=0,
                content=content,
                request_id=str(uuid.uuid4()),
            )
        finally:
            session.close()
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
        session = self.runtime.session()
        try:
            task = session.get(LocalAITask, result["id"])
            out = curriculum_ai.task_payload(session, task)
        finally:
            session.close()
        self.assertEqual(out["candidate"]["kind"], "split")
        self.assertEqual(len(server.requests), 1)
        # The accepted execution identity is exposed so the dialog can bind
        # progress reads to this exact execution/attempt.
        self.assertIsNotNone(out["execution"])
        self.assertTrue(out["execution"]["id"])
        self.assertEqual(out["execution"]["attempt_no"], 1)

    def test_real_executor_edit_echoes_advertised_target_id(self) -> None:
        ca_dir = self.tmp_root / "curriculum-edit-ca"
        _cert, _key, ca_pem = w3_tls.create_ca(ca_dir)
        leaf_cert, leaf_key = w3_tls.create_leaf(ca_dir, self.tmp_root / "edit-leaf")

        def reply_factory(request: bytes) -> bytes:
            _head, _, body = request.partition(b"\r\n\r\n")
            outer = json.loads(body.decode("utf-8"))
            payload = json.loads(outer["messages"][1]["content"])
            candidate = {
                "status": "proposed",
                "edit": {
                    "target_id": payload["target_id"],
                    "replacement": "新内容",
                },
                "question": None,
                "reason_suggestion": "",
            }
            return w3_tls.envelope(
                json.dumps(candidate, ensure_ascii=False),
                usage={"prompt_tokens": 4, "completion_tokens": 5},
            )

        server = w3_tls.TlsServer(
            cert=leaf_cert, key=leaf_key, reply_factory=reply_factory
        ).start()
        self.addCleanup(server.stop)
        session = self.runtime.session()
        try:
            ai_config_service.patch_config(
                session,
                expected_ai_config_version=0,
                base_url=f"https://{TEST_HOST}/v1",
                model="curriculum-edit-fake",
                secret="synthetic-secret",
                secret_provided=True,
                request_id=str(uuid.uuid4()),
                credential_root=self.runtime.credential_root,
            )
            session.commit()
        finally:
            session.close()
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
        content = _content(process_adjustment="原文")
        session = self.runtime.session()
        try:
            result, _created = ai_task_service.create_curriculum_task(
                session,
                runtime=self.runtime,
                record_id=str(uuid.uuid4()),
                kind="edit",
                version=0,
                content=content,
                instruction="改得更具体",
                selection={
                    "field": "process_adjustment",
                    "start": 0,
                    "end": 2,
                    "text": "原文",
                },
                request_id=str(uuid.uuid4()),
            )
        finally:
            session.close()
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
        session = self.runtime.session()
        try:
            task = session.get(LocalAITask, result["id"])
            out = curriculum_ai.task_payload(session, task)
        finally:
            session.close()
        self.assertEqual(
            out["candidate"]["patch"]["process_adjustment"], "新内容"
        )
        self.assertEqual(len(server.requests), 1)


class CurriculumAIMigrationTests(LocalTestCase):
    def test_0017_to_0018_preserves_curriculum_and_existing_ai_rows(self) -> None:
        db = self.tmp_root / "curriculum-upgrade.db"
        command.upgrade(
            alembic_config(db), "20261109_0017_local_curriculum_deliberations"
        )
        now = datetime.now().isoformat(sep=" ")
        profile_id = "profile-upgrade-0001"
        class_id = "class-upgrade-0001"
        record_id = str(uuid.uuid4())
        input_id = "input-upgrade-0001"
        task_id = "task-upgrade-00000000001"
        connection = sqlite3.connect(str(db))
        try:
            connection.execute(
                "INSERT INTO local_profile "
                "(id,singleton,display_name,created_at,updated_at) "
                "VALUES (?,1,'升级教师',?,?)",
                (profile_id, now, now),
            )
            connection.execute(
                "INSERT INTO local_classes "
                "(id,name,grade,header_teacher_names,caregiver_name,"
                "created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                (class_id, "升级班", "middle", "[]", None, now, now),
            )
            connection.execute(
                "INSERT INTO local_curriculum_deliberations "
                "(id,profile_id,class_id,version,activity_name,activity_date,"
                "content_json,content_hash,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    record_id,
                    profile_id,
                    class_id,
                    1,
                    "升级活动",
                    None,
                    "{}",
                    "a" * 64,
                    now,
                    now,
                ),
            )
            connection.execute(
                "INSERT INTO local_ai_inputs "
                "(id,profile_id,source_kind,source_id,observation_id,"
                "source_revision,daily_plan_id,content_id,content_version,"
                "weekly_plan_id,weekly_draft_id,listening_record_id,"
                "listening_domain,listening_group_id,create_operation_id,"
                "task_type,target_grade,input_schema_version,payload_json,"
                "dependencies_json,dependency_hash,target_hashes_json,created_at) "
                "VALUES (?,?,?,?,NULL,1,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,"
                "NULL,'class_game_config_extract',NULL,1,'{}','{}',?, '{}',?)",
                (input_id, profile_id, "class_game_config", class_id, "b" * 64, now),
            )
            connection.execute(
                "INSERT INTO local_ai_tasks "
                "(id,profile_id,source_kind,source_id,observation_id,daily_plan_id,"
                "weekly_plan_id,listening_record_id,listening_domain,"
                "listening_group_id,task_type,input_id,status,reason,"
                "current_execution_id,generation,runtime_meta_json,created_at,"
                "updated_at) VALUES (?,?,?,?,NULL,NULL,NULL,NULL,NULL,NULL,"
                "'class_game_config_extract',?,'pending',NULL,NULL,0,'{}',?,?)",
                (task_id, profile_id, "class_game_config", class_id, input_id, now, now),
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
                    "SELECT activity_name, content_hash, document_json "
                    "FROM local_curriculum_deliberations WHERE id=?",
                    (record_id,),
                ).fetchone(),
                ("升级活动", "a" * 64, None),
            )
            self.assertEqual(
                connection.execute(
                    "SELECT source_kind, source_id, task_type FROM local_ai_tasks "
                    "WHERE id=?",
                    (task_id,),
                ).fetchone(),
                ("class_game_config", class_id, "class_game_config_extract"),
            )
            task_source_type = next(
                row[2]
                for row in connection.execute(
                    "PRAGMA table_info(local_ai_tasks)"
                )
                if row[1] == "source_id"
            )
            self.assertEqual(task_source_type, "VARCHAR(36)")
            sql = connection.execute(
                "SELECT sql FROM sqlite_master "
                "WHERE type='table' AND name='local_ai_tasks'"
            ).fetchone()[0]
            self.assertIn("curriculum_deliberation", sql)
            self.assertEqual(
                connection.execute("PRAGMA foreign_key_check").fetchall(), []
            )
        finally:
            connection.close()


class CurriculumAIListeningMigrationTests(LocalTestCase):
    def test_populated_goal_suggestion_chain_and_old_indexes_survive(self) -> None:
        db = self.tmp_root / "curriculum-listening-upgrade.db"
        command.upgrade(
            alembic_config(db), "20261109_0017_local_curriculum_deliberations"
        )
        now = datetime.now().isoformat(sep=" ")
        profile_id = "profile-upgrade-0001"
        class_id = "class-upgrade-0001"
        term_id = "term-upgrade-000000000001"
        revision_id = "calendar-upgrade-00000001"
        record_id = "listening-upgrade-0000001"
        domain = "health"
        operation_id = "operation-upgrade-000000001"
        config_id = "config-upgrade-00000000001"
        input_id = "input-listening-0000000001"
        task_id = "task-listening-00000000001"
        execution_id = "exec-listening-0000000001"
        candidate_id = "cand-listening-0000000001"
        connection = sqlite3.connect(str(db))
        try:
            connection.execute(
                "INSERT INTO local_profile "
                "(id,singleton,display_name,created_at,updated_at) "
                "VALUES (?,1,'升级教师',?,?)",
                (profile_id, now, now),
            )
            connection.execute(
                "INSERT INTO local_classes "
                "(id,name,grade,header_teacher_names,caregiver_name,"
                "created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                (class_id, "升级班", "middle", "[]", None, now, now),
            )
            connection.execute(
                "INSERT INTO local_terms "
                "(id,name,start_date,end_date,current_calendar_revision_id,"
                "created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                (
                    term_id,
                    "升级学期",
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
                "INSERT INTO local_ai_config_versions "
                "(profile_id,version,protocol_id,base_url,model,credential_id,"
                "created_at) VALUES (?,1,'chat_completions_v1',NULL,NULL,NULL,?)",
                (profile_id, now),
            )
            connection.execute(
                "INSERT INTO local_prompt_bundles "
                "(task_type,contract_version,default_revision,input_schema_json,"
                "output_schema_json,guidance_defaults_json,bundle_hash,created_at) "
                "VALUES ('listening_goal_suggest',1,1,'{}','{}','{}',?,?)",
                ("c" * 64, now),
            )
            connection.execute(
                "INSERT INTO local_personal_prompt_versions "
                "(profile_id,task_type,revision,contract_version,"
                "based_default_revision,guidance_json,orphaned_guidance_json,"
                "action,rejected_default_revision,created_at) "
                "VALUES (?,'listening_goal_suggest',1,1,1,'{}',NULL,'initial',"
                "NULL,?)",
                (profile_id, now),
            )
            connection.execute(
                "INSERT INTO local_ai_inputs "
                "(id,profile_id,source_kind,source_id,observation_id,"
                "source_revision,daily_plan_id,content_id,content_version,"
                "weekly_plan_id,weekly_draft_id,listening_record_id,"
                "listening_domain,listening_group_id,create_operation_id,"
                "task_type,target_grade,input_schema_version,payload_json,"
                "dependencies_json,dependency_hash,target_hashes_json,created_at) "
                "VALUES (?,?,?,?,NULL,1,NULL,NULL,NULL,NULL,NULL,?,?,NULL,?,"
                "'listening_goal_suggest',NULL,1,'{}','{}',?, '{}',?)",
                (
                    input_id,
                    profile_id,
                    "one_to_one_listening",
                    record_id,
                    record_id,
                    domain,
                    operation_id,
                    "d" * 64,
                    now,
                ),
            )
            connection.execute(
                "INSERT INTO local_ai_tasks "
                "(id,profile_id,source_kind,source_id,observation_id,"
                "daily_plan_id,weekly_plan_id,listening_record_id,"
                "listening_domain,listening_group_id,task_type,input_id,status,"
                "reason,current_execution_id,generation,runtime_meta_json,"
                "created_at,updated_at) VALUES (?,?,?,?,NULL,NULL,NULL,?,?,NULL,"
                "'listening_goal_suggest',?,'succeeded',NULL,NULL,1,'{}',?,?)",
                (
                    task_id,
                    profile_id,
                    "one_to_one_listening",
                    record_id,
                    record_id,
                    domain,
                    input_id,
                    now,
                    now,
                ),
            )
            connection.execute(
                "INSERT INTO local_ai_executions "
                "(id,task_id,source_kind,source_id,observation_id,daily_plan_id,"
                "weekly_plan_id,listening_record_id,listening_domain,"
                "listening_group_id,input_id,task_type,generation,launch_id,"
                "permit_id,config_version,profile_id,personal_revision,"
                "contract_version,default_revision,state,runtime_meta_json,"
                "started_at,created_at,ended_at) "
                "VALUES (?,?,?,?,NULL,NULL,NULL,?,?,NULL,?,"
                "'listening_goal_suggest',1,?,?,1,?,1,1,1,'succeeded','{}',?,?,?)",
                (
                    execution_id,
                    task_id,
                    "one_to_one_listening",
                    record_id,
                    record_id,
                    domain,
                    input_id,
                    str(uuid.uuid4()),
                    str(uuid.uuid4()),
                    profile_id,
                    now,
                    now,
                    now,
                ),
            )
            connection.execute(
                "INSERT INTO local_ai_candidates "
                "(id,profile_id,execution_id,task_id,source_kind,source_id,"
                "observation_id,daily_plan_id,weekly_plan_id,"
                "listening_record_id,listening_domain,listening_group_id,"
                "input_id,task_type,contract_version,schema_version,"
                "raw_candidate_json,candidate_hash,created_at) "
                "VALUES (?,?,?,?,?,?,NULL,NULL,NULL,?,?,NULL,?,"
                "'listening_goal_suggest',1,1,'{}',?,?)",
                (
                    candidate_id,
                    profile_id,
                    execution_id,
                    task_id,
                    "one_to_one_listening",
                    record_id,
                    record_id,
                    domain,
                    input_id,
                    "e" * 64,
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
                    "SELECT source_kind, task_type, status FROM local_ai_tasks "
                    "WHERE id=?",
                    (task_id,),
                ).fetchone(),
                ("one_to_one_listening", "listening_goal_suggest", "succeeded"),
            )
            self.assertEqual(
                connection.execute(
                    "SELECT task_type FROM local_ai_candidates WHERE id=?",
                    (candidate_id,),
                ).fetchone()[0],
                "listening_goal_suggest",
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
            for table_name, prefix in (
                ("local_ai_inputs", "fk_local_ai_inputs_listening"),
                ("local_ai_tasks", "fk_local_ai_tasks_listening"),
                ("local_ai_executions", "fk_local_ai_executions_listening"),
                ("local_ai_candidates", "fk_local_ai_candidates_listening"),
            ):
                sql = connection.execute(
                    "SELECT sql FROM sqlite_master "
                    "WHERE type='table' AND name=?",
                    (table_name,),
                ).fetchone()[0]
                for suffix in ("record", "domain", "group"):
                    self.assertIn(f"{prefix}_{suffix}", sql)

            new_input = "input-listening-new-00000001"
            new_task = "task-listening-new-000000001"
            connection.execute(
                "INSERT INTO local_ai_inputs "
                "(id,profile_id,source_kind,source_id,observation_id,"
                "source_revision,daily_plan_id,content_id,content_version,"
                "weekly_plan_id,weekly_draft_id,listening_record_id,"
                "listening_domain,listening_group_id,create_operation_id,"
                "task_type,target_grade,input_schema_version,payload_json,"
                "dependencies_json,dependency_hash,target_hashes_json,created_at) "
                "VALUES (?,?,?,?,NULL,1,NULL,NULL,NULL,NULL,NULL,?,?,NULL,?,"
                "'listening_goal_suggest',NULL,1,'{}','{}',?, '{}',?)",
                (
                    new_input,
                    profile_id,
                    "one_to_one_listening",
                    record_id,
                    record_id,
                    domain,
                    operation_id,
                    "f" * 64,
                    now,
                ),
            )
            connection.execute(
                "INSERT INTO local_ai_tasks "
                "(id,profile_id,source_kind,source_id,observation_id,"
                "daily_plan_id,weekly_plan_id,listening_record_id,"
                "listening_domain,listening_group_id,task_type,input_id,status,"
                "reason,current_execution_id,generation,runtime_meta_json,"
                "created_at,updated_at) VALUES (?,?,?,?,NULL,NULL,NULL,?,?,NULL,"
                "'listening_goal_suggest',?,'pending',NULL,NULL,0,'{}',?,?)",
                (
                    new_task,
                    profile_id,
                    "one_to_one_listening",
                    record_id,
                    record_id,
                    domain,
                    new_input,
                    now,
                    now,
                ),
            )
            connection.commit()
            self.assertEqual(
                connection.execute("PRAGMA foreign_key_check").fetchall(), []
            )
        finally:
            connection.close()


class CurriculumAIHttpTests(LocalTestCase):
    def test_http_create_replay_and_task_read(self) -> None:
        runtime = self.make_runtime()
        runtime.launch_id = str(uuid.uuid4())
        server = self.start_server(runtime, executor=_ReadyExecutor())
        client = server.client()
        self.initialize(client)
        session = runtime.session()
        try:
            ai_config_service.patch_config(
                session,
                expected_ai_config_version=0,
                base_url="https://api.deepseek.com/v1",
                model="deepseek-v4-flash",
                secret="synthetic-secret",
                secret_provided=True,
                request_id=str(uuid.uuid4()),
                credential_root=runtime.credential_root,
            )
            session.commit()
        finally:
            session.close()
        record_id = str(uuid.uuid4())
        body = {
            "request_id": str(uuid.uuid4()),
            "kind": "split",
            "version": 0,
            "content": _content(),
        }
        status, created = client.post(
            f"/api/local/curriculum-deliberations/{record_id}/ai/tasks", body
        )
        self.assertEqual(status, 202, created)
        self.assertEqual(created["status"], "pending")
        self.assertIsNone(created["candidate"])
        status, replay = client.post(
            f"/api/local/curriculum-deliberations/{record_id}/ai/tasks", body
        )
        self.assertEqual(status, 200, replay)
        self.assertEqual(replay["id"], created["id"])
        status, task = client.get(
            f"/api/local/curriculum-deliberations/{record_id}/ai/tasks/"
            f"{created['id']}"
        )
        self.assertEqual(status, 200, task)
        self.assertEqual(task["id"], created["id"])
        self.assertEqual(task["execution"], None)
        status, progress = client.get(
            f"/api/local/curriculum-deliberations/{record_id}/ai/tasks/"
            f"{created['id']}/progress"
        )
        self.assertEqual(status, 200, progress)
        self.assertEqual(progress["task_id"], created["id"])
        self.assertFalse(progress["available"])
        self.assertEqual(progress["phase"], "waiting")
        self.assertEqual(progress["reasoning"], "")
