"""Weekly-plan Word export service/API tests (G2a D scope)."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import http.client
import io
import os
import json
import subprocess
import tempfile
import threading
import uuid
import xml.etree.ElementTree as ET
import zipfile
from unittest import mock
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select

from app.local import backup_fs
from app.local import (
    daily_plan_service,
    profile_service,
    weekly_plan_content,
    weekly_plan_export_api as export_api,
    weekly_plan_export_service as export_service,
    weekly_plan_service,
    weekly_plan_snapshot as snapshots,
    weekly_plan_tokens as tokens,
)
from app.local.errors import (
    LocalWeeklyExportConflict,
    LocalWeeklyExportNotFound,
    LocalWeeklyExportUnavailable,
    LocalWeeklyInvalid,
    LocalWeeklyOperationConflict,
    LocalWeeklyPreviewExpired,
    LocalWeeklyPreviewStale,
)
from app.local.models import (
    LocalProfile,
    LocalSettings,
    LocalTerm,
    LocalWeeklyExportAttempt,
    LocalWeeklyExportSnapshot,
    LocalWeeklyExportToken,
    LocalWeeklyPlan,
    LocalWeeklyPlanConfirmation,
    LocalWeeklyPlanContent,
    LocalWeeklyPlanOperation,
)
from app.local.normalize import normalize_initialization
from app.services import word_export_docx as word_docx
from starlette.requests import Request
from tests.local.support import LocalTestCase

ANCHOR = date(2026, 9, 7)
PLAN_DATE = date(2026, 9, 8)
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _weekly_table(document: bytes):
    with zipfile.ZipFile(io.BytesIO(document)) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    table = root.find(f".//{_W}tbl")
    if table is None:
        raise AssertionError("weekly table missing from generated docx")
    return root, table


def _xml_text(root) -> str:
    return "".join(node.text or "" for node in root.iter(f"{_W}t"))


def _adopted(topic: str = "秋天的树叶") -> dict:
    return {
        "morning_talk": {"topic": topic, "questions": "你看到了什么"},
        "group_activity": {"theme": "树叶分类", "process": "观察"},
        "morning_games": [
            {
                "group_kind": "collective",
                "games": [{"name": "老狼老狼几点了"}],
                "shared_objectives": "听信号行动",
                "guidance_points": "注意安全",
                "focus_guidance": "观察反应",
            }
        ],
        "post_group_games": [
            {
                "context_kind": "area",
                "area": "积木区",
                "games": [{"name": "搭建小桥"}],
                "objectives": "合作",
                "guidance": "协商",
                "support_strategy": "提供材料",
            }
        ],
    }
class WeeklyExportTests(LocalTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.runtime = self.make_runtime()
        self.session = self.runtime.session()
        self.addCleanup(self.session.close)
        normalized = normalize_initialization(
            request_id=str(uuid.uuid4()),
            display_name="导出教师",
            class_name="中一班",
            grade="middle",
            term_name="秋季学期",
            start_date=ANCHOR.isoformat(),
            end_date="2026-10-30",
            school_name="导出幼儿园",
        )
        profile_service.initialize(self.session, normalized)
        self.session.expire_all()
        self.profile = self.session.scalars(select(LocalProfile)).one()
        self.term = self.session.scalars(select(LocalTerm)).one()
        self.settings = self.session.get(LocalSettings, "singleton")
        self.manager = self.runtime.bind_weekly_exports(
            launch_id="launch-export", session_scope="scope-export"
        )
        self.addCleanup(self.manager.close)
        self.work_root = self.runtime.weekly_export_work_root
    def _create_daily(self, day: date = PLAN_DATE) -> dict:
        result, _created = daily_plan_service.create_or_open(
            self.session,
            plan_date=day,
            raw_lesson_plan=None,
            adopted_content=_adopted(),
        )
        return result

    def _make_confirmation(
        self, *, anchor: date = ANCHOR, theme: str = "主题"
    ) -> tuple[str, str, int]:
        self._create_daily(anchor + timedelta(days=1))
        preview = weekly_plan_service.create_preview(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            launch_id=self.manager.launch_id,
            session_scope_hash=self.manager.session_scope_hash,
            term_id=self.term.id,
            week_anchor_date=anchor,
        )
        result, _created = weekly_plan_service.create_or_open(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            launch_id=self.manager.launch_id,
            session_scope_hash=self.manager.session_scope_hash,
            request_id=str(uuid.uuid4()),
            term_id=self.term.id,
            week_anchor_date=anchor,
            expected_config_version=self.settings.config_version,
            context_token=preview["create_token"],
        )
        plan_id = result["weekly_plan_id"]
        detail = weekly_plan_service.get_detail(
            self.session, profile_id=self.profile.id, plan_id=plan_id
        )
        saved = weekly_plan_service.save_draft(
            self.session,
            profile_id=self.profile.id,
            request_id=str(uuid.uuid4()),
            plan_id=plan_id,
            expected_draft_version=detail["draft"]["version"],
            patch={"theme": theme},
        )
        version = saved["draft"]["version"]
        target = weekly_plan_service.confirmation_preview(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            launch_id=self.manager.launch_id,
            session_scope_hash=self.manager.session_scope_hash,
            plan_id=plan_id,
            expected_draft_version=version,
        )
        confirmed = weekly_plan_service.confirm(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            launch_id=self.manager.launch_id,
            session_scope_hash=self.manager.session_scope_hash,
            request_id=str(uuid.uuid4()),
            plan_id=plan_id,
            expected_draft_version=version,
            context_token=target["preview_token"],
            ack_missing=True,
            ack_stale=True,
        )
        return plan_id, confirmed["confirmation"]["id"], version
    def _export_weekly_docx(self, plan_id: str, confirmation_id: str) -> bytes:
        preview = export_service.preview_export(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            mode="single",
            weekly_plan_id=plan_id,
            confirmation_id=confirmation_id,
        )
        created, _ = export_service.create_export(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            request_id=str(uuid.uuid4()),
            context_token=preview["context_token"],
            ack_missing=True,
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        )
        artifact = export_service.read_export_content(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            export_id=created["export_id"],
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        )
        try:
            return artifact.handle.read()
        finally:
            artifact.close()
    def test_preview_is_ephemeral_and_uses_strict_shapes(self) -> None:
        plan_id, confirmation_id, _version = self._make_confirmation()
        self.assertFalse(self.work_root.exists())
        before = {
            model: self.session.scalar(select(func.count()).select_from(model))
            for model in (
                LocalWeeklyExportSnapshot,
                LocalWeeklyExportToken,
                LocalWeeklyPlanOperation,
                LocalWeeklyExportAttempt,
            )
        }
        preview = export_service.preview_export(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            mode="single",
            weekly_plan_id=plan_id,
            confirmation_id=confirmation_id,
        )
        self.assertEqual(
            set(preview),
            {
                "context_token",
                "manifest_hash",
                "expires_at",
                "selection",
                "items",
                "missing",
                "warnings",
                "warnings_as_of",
                "suggested_filename",
            },
        )
        context = self.manager.take_preview(tokens.token_hash(preview["context_token"]))
        self.assertIsNotNone(context)
        manifest = snapshots.validate_export_manifest(context["manifest"])
        self.assertEqual(set(manifest), snapshots.EXPORT_MANIFEST_KEYS)
        self.assertEqual(set(manifest["selection"][0]), snapshots.EXPORT_SELECTION_KEYS)
        self.assertEqual(set(manifest["items"][0]), snapshots.EXPORT_ITEM_KEYS)
        self.assertEqual(
            context["manifest_hash"], snapshots.snapshot_hash(manifest)
        )
        after = {
            model: self.session.scalar(select(func.count()).select_from(model))
            for model in before
        }
        self.assertEqual(before, after)
        self.assertFalse(self.work_root.exists())
    def test_create_content_attempt_and_replay(self) -> None:
        plan_id, confirmation_id, _version = self._make_confirmation()
        preview = export_service.preview_export(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            mode="single",
            weekly_plan_id=plan_id,
            confirmation_id=confirmation_id,
        )
        request_id = str(uuid.uuid4())
        created, was_created = export_service.create_export(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            request_id=request_id,
            context_token=preview["context_token"],
            ack_missing=True,
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        )
        self.assertTrue(was_created)
        self.assertEqual(created["generation_status"], "generated")
        export_id = created["export_id"]
        replay, replayed_created = export_service.create_export(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            request_id=request_id,
            context_token=preview["context_token"],
            ack_missing=True,
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        )
        self.assertFalse(replayed_created)
        self.assertEqual(replay["export_id"], export_id)
        operation = export_service.read_operation(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            request_id=request_id,
        )
        self.assertEqual(operation["generation_status"], "generated")
        artifact = export_service.read_export_content(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            export_id=export_id,
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        )
        data = artifact.handle.read()
        self.assertEqual(len(data), artifact.size)
        self.assertEqual(hashlib.sha256(data).hexdigest(), artifact.digest)
        artifact.close()
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            self.assertIn("word/document.xml", archive.namelist())
        name = "周计划测试.docx"
        attempt = export_service.start_attempt(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            export_id=export_id,
            filename=name,
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        )
        self.assertTrue(attempt["should_prompt"])
        self.assertEqual(attempt["byte_size"], 0)
        self.assertIsNone(attempt["result_hash"])
        finished = export_service.finish_attempt(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            export_id=export_id,
            attempt_id=attempt["attempt_id"],
            filename=name,
            status="saved",
            byte_size=len(data),
            result_hash=hashlib.sha256(data).hexdigest(),
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        )
        self.assertEqual(finished["status"], "saved")
        self.assertEqual(finished["byte_size"], len(data))
        latest = export_service.read_latest_attempt(
            self.session,
            profile_id=self.profile.id,
            export_id=export_id,
            filename=name,
        )
        self.assertEqual(latest["status"], "saved")
        again = export_service.start_attempt(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            export_id=export_id,
            filename=name,
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        )
        self.assertFalse(again["should_prompt"])
        with self.assertRaises(LocalWeeklyExportConflict):
            export_service.start_attempt(
                self.session,
                self.manager,
                profile_id=self.profile.id,
                export_id=export_id,
                filename="另一名称.docx",
                launch_id=self.manager.launch_id,
                session_scope=self.manager.session_scope,
            )
        expired = export_service.read_operation(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            request_id=request_id,
        )
        self.assertEqual(expired["generation_status"], "transfer_expired")
        self.assertNotIn("export_id", expired)
    def test_old_confirmation_exports_after_new_draft_and_confirm(self) -> None:
        plan_id, old_confirmation, version = self._make_confirmation()
        saved = weekly_plan_service.save_draft(
            self.session,
            profile_id=self.profile.id,
            request_id=str(uuid.uuid4()),
            plan_id=plan_id,
            expected_draft_version=version,
            patch={"theme": "新主题"},
        )
        new_version = saved["draft"]["version"]
        target = weekly_plan_service.confirmation_preview(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            launch_id=self.manager.launch_id,
            session_scope_hash=self.manager.session_scope_hash,
            plan_id=plan_id,
            expected_draft_version=new_version,
        )
        weekly_plan_service.confirm(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            launch_id=self.manager.launch_id,
            session_scope_hash=self.manager.session_scope_hash,
            request_id=str(uuid.uuid4()),
            plan_id=plan_id,
            expected_draft_version=new_version,
            context_token=target["preview_token"],
            ack_missing=True,
            ack_stale=True,
        )
        preview = export_service.preview_export(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            mode="single",
            weekly_plan_id=plan_id,
            confirmation_id=old_confirmation,
        )
        self.assertEqual(preview["selection"][0]["confirmation_id"], old_confirmation)
        self.assertEqual(preview["selection"][0]["draft_version"], version)
        created, _ = export_service.create_export(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            request_id=str(uuid.uuid4()),
            context_token=preview["context_token"],
            ack_missing=True,
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        )
        self.assertEqual(created["generation_status"], "generated")
    def test_range_selection_order_and_page_break(self) -> None:
        first, _first_confirmation, _ = self._make_confirmation()
        second, _second_confirmation, _ = self._make_confirmation(
            anchor=ANCHOR + timedelta(days=7)
        )
        preview = export_service.preview_export(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            mode="range",
            start_date=ANCHOR,
            end_date=ANCHOR + timedelta(days=7),
        )
        self.assertEqual(len(preview["selection"]), 2)
        self.assertEqual(
            [item["weekly_plan_id"] for item in preview["selection"]],
            [first, second],
        )
        request_id = str(uuid.uuid4())
        created, _ = export_service.create_export(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            request_id=request_id,
            context_token=preview["context_token"],
            ack_missing=True,
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        )
        artifact = export_service.read_export_content(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            export_id=created["export_id"],
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        )
        data = artifact.handle.read()
        artifact.close()
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            document = archive.read("word/document.xml")
        self.assertGreaterEqual(document.count(b'w:type="page"'), 1)
    def test_range_without_matching_teaching_week_is_explicit(self) -> None:
        plan_id, confirmation_id, _ = self._make_confirmation()
        self._rewrite_states(plan_id, confirmation_id, ["rest"] * 7)
        models = (
            LocalWeeklyExportSnapshot,
            LocalWeeklyExportToken,
            LocalWeeklyPlanOperation,
            LocalWeeklyExportAttempt,
        )
        before = {
            model: self.session.scalar(select(func.count()).select_from(model))
            for model in models
        }
        with self.assertRaises(LocalWeeklyExportNotFound) as raised:
            export_service.preview_export(
                self.session,
                self.manager,
                profile_id=self.profile.id,
                mode="range",
                start_date=ANCHOR,
                end_date=ANCHOR + timedelta(days=6),
            )
        self.assertEqual(raised.exception.code, "WEEKLY_EXPORT_NOT_FOUND")
        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(
            raised.exception.details,
            {"reason": "no_matching_confirmed_weeks"},
        )
        after = {
            model: self.session.scalar(select(func.count()).select_from(model))
            for model in models
        }
        self.assertEqual(before, after)
        self.assertFalse(self.work_root.exists())
        # The same zero-teaching-day week remains exportable as a single plan.
        single = export_service.preview_export(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            mode="single",
            weekly_plan_id=plan_id,
            confirmation_id=confirmation_id,
        )
        self.assertEqual(len(single["items"][0]["columns"]), 5)
        # Ordinary not-found paths must not inherit the range-specific reason.
        with self.assertRaises(LocalWeeklyExportNotFound) as missing:
            export_service.preview_export(
                self.session,
                self.manager,
                profile_id=self.profile.id,
                mode="single",
                weekly_plan_id="missing-plan",
            )
        self.assertIsNone(missing.exception.details)
    def test_pause_expiry_purpose_and_scope(self) -> None:
        plan_id, confirmation_id, _ = self._make_confirmation()
        self.manager.pause(owner="test-pause")
        with self.assertRaises(LocalWeeklyExportUnavailable):
            export_service.preview_export(
                self.session,
                self.manager,
                profile_id=self.profile.id,
                mode="single",
                weekly_plan_id=plan_id,
                confirmation_id=confirmation_id,
            )
        self.manager.resume(owner="test-pause")
        preview = export_service.preview_export(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            mode="single",
            weekly_plan_id=plan_id,
            confirmation_id=confirmation_id,
        )
        with self.assertRaises(LocalWeeklyPreviewStale):
            tokens.verify_token(
                self.runtime,
                preview["context_token"],
                purpose="confirm",
                profile_id=self.profile.id,
                launch_id=self.manager.launch_id,
                session_scope_hash=self.manager.session_scope_hash,
            )
        with self.assertRaises(LocalWeeklyExportConflict):
            export_service.create_export(
                self.session,
                self.manager,
                profile_id=self.profile.id,
                request_id=str(uuid.uuid4()),
                context_token=preview["context_token"],
                ack_missing=True,
                launch_id="other-launch",
                session_scope=self.manager.session_scope,
            )
        with mock.patch.object(export_service, "PREVIEW_TTL_SECONDS", -1):
            expired = export_service.preview_export(
                self.session,
                self.manager,
                profile_id=self.profile.id,
                mode="single",
                weekly_plan_id=plan_id,
                confirmation_id=confirmation_id,
            )
            with self.assertRaises(LocalWeeklyPreviewExpired):
                export_service.create_export(
                    self.session,
                    self.manager,
                    profile_id=self.profile.id,
                    request_id=str(uuid.uuid4()),
                    context_token=expired["context_token"],
                    ack_missing=True,
                    launch_id=self.manager.launch_id,
                    session_scope=self.manager.session_scope,
                )
    def test_concurrent_same_request_single_result(self) -> None:
        plan_id, confirmation_id, _ = self._make_confirmation()
        preview = export_service.preview_export(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            mode="single",
            weekly_plan_id=plan_id,
            confirmation_id=confirmation_id,
        )
        request_id = str(uuid.uuid4())
        profile_id = self.profile.id
        launch_id = self.manager.launch_id
        session_scope = self.manager.session_scope
        barrier = threading.Barrier(2)

        def run():
            session = self.runtime.session()
            try:
                barrier.wait(timeout=10)
                return export_service.create_export(
                    session,
                    self.manager,
                    profile_id=profile_id,
                    request_id=request_id,
                    context_token=preview["context_token"],
                    ack_missing=True,
                    launch_id=launch_id,
                    session_scope=session_scope,
                )
            finally:
                session.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: run(), range(2)))
        self.assertEqual(sum(1 for _result, created in results if created), 1)
        self.assertEqual(results[0][0]["export_id"], results[1][0]["export_id"])
        self.session.expire_all()
        count = self.session.scalar(
            select(func.count())
            .select_from(LocalWeeklyPlanOperation)
            .where(
                LocalWeeklyPlanOperation.profile_id == self.profile.id,
                LocalWeeklyPlanOperation.request_id == request_id,
            )
        )
        self.assertEqual(count, 1)
        docx = list(self.work_root.glob("*.docx"))
        self.assertEqual(len(docx), 1)
    def test_retry_failed_unique_successor_and_replay(self) -> None:
        plan_id, confirmation_id, _ = self._make_confirmation()
        preview = export_service.preview_export(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            mode="single",
            weekly_plan_id=plan_id,
            confirmation_id=confirmation_id,
        )
        created, _ = export_service.create_export(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            request_id=str(uuid.uuid4()),
            context_token=preview["context_token"],
            ack_missing=True,
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        )
        name = "重试周计划.docx"
        attempt = export_service.start_attempt(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            export_id=created["export_id"],
            filename=name,
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        )
        export_service.finish_attempt(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            export_id=created["export_id"],
            attempt_id=attempt["attempt_id"],
            filename=name,
            status="failed",
            byte_size=0,
            result_hash=None,
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        )
        request_id = str(uuid.uuid4())
        retry, created_new = export_service.retry_export(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            snapshot_id=created["snapshot_id"],
            request_id=request_id,
            old_export_id=created["export_id"],
            attempt_id=attempt["attempt_id"],
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        )
        self.assertTrue(created_new)
        self.assertEqual(retry["generation_status"], "generated")
        replay, replay_created = export_service.retry_export(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            snapshot_id=created["snapshot_id"],
            request_id=request_id,
            old_export_id=created["export_id"],
            attempt_id=attempt["attempt_id"],
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        )
        self.assertFalse(replay_created)
        self.assertEqual(replay["export_id"], retry["export_id"])
        with self.assertRaises(LocalWeeklyExportConflict):
            export_service.retry_export(
                self.session,
                self.manager,
                profile_id=self.profile.id,
                snapshot_id=created["snapshot_id"],
                request_id=str(uuid.uuid4()),
                old_export_id=created["export_id"],
                attempt_id=attempt["attempt_id"],
                launch_id=self.manager.launch_id,
                session_scope=self.manager.session_scope,
            )
    def test_stream_ref_and_close_preserve_unknown_work(self) -> None:
        plan_id, confirmation_id, _ = self._make_confirmation()
        preview = export_service.preview_export(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            mode="single",
            weekly_plan_id=plan_id,
            confirmation_id=confirmation_id,
        )
        request_id = str(uuid.uuid4())
        created, _ = export_service.create_export(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            request_id=request_id,
            context_token=preview["context_token"],
            ack_missing=True,
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        )
        original_activity = self.manager.activity
        kinds = []

        def record_activity(*, kind, launch_id, session_scope):
            kinds.append(kind)
            return original_activity(
                kind=kind, launch_id=launch_id, session_scope=session_scope
            )

        self.manager.activity = record_activity
        try:
            artifact = export_service.read_export_content(
                self.session,
                self.manager,
                profile_id=self.profile.id,
                export_id=created["export_id"],
                launch_id=self.manager.launch_id,
                session_scope=self.manager.session_scope,
            )
        finally:
            self.manager.activity = original_activity
        self.assertEqual(kinds[0], "download")
        self.assertFalse(self.session.in_transaction())
        self.assertFalse(self.manager.wait_idle(timeout=0.0))
        unknown = self.work_root / "unknown-user-file.txt"
        unknown.write_text("keep", encoding="utf-8")
        artifact.handle.read(16)
        self.manager.close()
        artifact.close()
        self.assertTrue(self.manager.wait_idle(timeout=0.0))
        self.assertFalse(any(self.work_root.glob("*.docx")))
        self.assertFalse(any(self.work_root.glob("*.json")))
        self.assertTrue(unknown.is_file())
        with self.assertRaises(LocalWeeklyExportUnavailable):
            export_service.preview_export(
                self.session,
                self.manager,
                profile_id=self.profile.id,
                mode="single",
                weekly_plan_id=plan_id,
                confirmation_id=confirmation_id,
            )
        retired = export_service.read_operation(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            request_id=request_id,
        )
        self.assertEqual(retired["generation_status"], "transfer_expired")
        self.assertNotIn("export_id", retired)
    def test_http_contract_content_headers_and_attempt(self) -> None:
        plan_id, confirmation_id, _ = self._make_confirmation()
        self.manager.close()
        server = self.start_server(self.runtime)
        client = server.client()
        status, preview = client.post(
            "/api/weekly-exports/preview",
            {
                "mode": "single",
                "weekly_plan_id": plan_id,
                "confirmation_id": confirmation_id,
            },
        )
        self.assertEqual(status, 200, preview)
        self.assertEqual(
            set(preview),
            {
                "context_token",
                "manifest_hash",
                "expires_at",
                "selection",
                "items",
                "missing",
                "warnings",
                "warnings_as_of",
                "suggested_filename",
            },
        )
        request_id = str(uuid.uuid4())
        status, created = client.post(
            "/api/weekly-exports",
            {
                "request_id": request_id,
                "context_token": preview["context_token"],
                "ack_missing": True,
            },
        )
        self.assertEqual(status, 201, created)
        self.assertEqual(created["generation_status"], "generated")
        token = self.session.scalars(
            select(LocalWeeklyExportToken).where(
                LocalWeeklyExportToken.snapshot_id == created["snapshot_id"]
            )
        ).one()
        short_expiry = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=60)
        token.expires_at = short_expiry
        self.session.commit()
        status, operation = client.get(
            f"/api/weekly-exports/operations/{request_id}"
        )
        self.assertEqual(status, 200, operation)
        self.assertEqual(operation["export_id"], created["export_id"])
        status, attempt = client.post(
            f"/api/weekly-exports/{created['export_id']}/attempts",
            {"filename": "HTTP周计划.docx"},
        )
        self.assertEqual(status, 200, attempt)
        connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=30)
        try:
            connection.request(
                "GET",
                f"/api/weekly-exports/{created['export_id']}/content",
                headers={"X-App-Session": server.token},
            )
            response = connection.getresponse()
            data = response.read()
            headers = {key.lower(): value for key, value in response.getheaders()}
        finally:
            connection.close()
        self.assertEqual(response.status, 200)
        self.assertEqual(
            headers["content-type"],
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        self.assertEqual(headers["cache-control"], "no-store")
        self.assertEqual(headers["content-disposition"], "attachment")
        self.assertEqual(int(headers["content-length"]), len(data))
        self.assertEqual(
            headers["x-content-sha256"], hashlib.sha256(data).hexdigest()
        )
        self.assertEqual(
            headers["x-export-expires-at"],
            export_api._expires_header(short_expiry),
        )
        self.assertTrue(headers["x-export-expires-at"].endswith("Z"))
        status, finished = client.post(
            f"/api/weekly-exports/{created['export_id']}/attempts/result",
            {
                "attempt_id": attempt["attempt_id"],
                "filename": "HTTP周计划.docx",
                "status": "saved",
                "byte_size": len(data),
                "result_hash": hashlib.sha256(data).hexdigest(),
            },
        )
        self.assertEqual(status, 200, finished)
        self.assertEqual(finished["status"], "saved")
    def _rewrite_states(
        self, plan_id: str, confirmation_id: str, states: list[str]
    ) -> None:
        row = self.session.get(LocalWeeklyPlanConfirmation, confirmation_id)
        self.assertIsNotNone(row)
        self.assertEqual(row.weekly_plan_id, plan_id)
        content_row = self.session.get(LocalWeeklyPlanContent, row.draft_id)
        self.assertIsNotNone(content_row)
        snapshot = copy.deepcopy(row.snapshot_json)
        content = copy.deepcopy(content_row.content_json)
        for index, state in enumerate(states):
            source_state = "no_plan" if state == "teaching" else "none_required"
            content["calendar_basis"]["days"][index]["day_state"] = state
            row_day = content["deterministic"][index]
            row_day["day_state"] = state
            row_day["source_state"] = source_state
            row_day["source"] = None
            row_day["effective"] = {
                key: "" for key in row_day["effective"]
            }
            source = content["source_manifest"]["sources"][index]
            source["source_state"] = source_state
            for key in ("daily_plan_id", "content_id", "content_version", "content_hash"):
                source[key] = None
        content = weekly_plan_content.validate_content(content)
        content_hash = weekly_plan_content.content_hash(content)
        facts = copy.deepcopy(snapshot["facts"])
        rebuilt = snapshots.build_confirmation_snapshot(
            weekly_plan_id=snapshot["weekly_plan_id"],
            profile_id=snapshot["profile_id"],
            class_id=snapshot["class_id"],
            term_id=snapshot["term_id"],
            draft_id=snapshot["draft_id"],
            draft_version=snapshot["draft_version"],
            content_hash=content_hash,
            header=snapshot["header"],
            creation_context=snapshot["creation_context"],
            content=content,
            facts=facts,
        )
        content_row.content_json = content
        content_row.content_hash = content_hash
        row.snapshot_json = rebuilt
        row.snapshot_hash = snapshots.snapshot_hash(rebuilt)
        row.facts_json = facts
        row.facts_hash = hashlib.sha256(
            snapshots.canonical_json(facts).encode("utf-8")
        ).hexdigest()
        self.session.commit()
    def test_zero_teaching_fallback_and_seven_columns(self) -> None:
        plan_id, confirmation_id, _ = self._make_confirmation()
        self._rewrite_states(plan_id, confirmation_id, ["rest"] * 7)
        preview = export_service.preview_export(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            mode="single",
            weekly_plan_id=plan_id,
            confirmation_id=confirmation_id,
        )
        self.assertEqual(
            preview["selection"][0]["date_range"],
            {"start": ANCHOR.isoformat(), "end": (ANCHOR + timedelta(days=6)).isoformat()},
        )
        self.assertEqual(len(preview["items"][0]["columns"]), 5)
        self.assertFalse(
            any(
                day["day_state"] == "teaching"
                for day in preview["items"][0]["content"]["calendar_basis"]["days"]
            )
        )
        created, _ = export_service.create_export(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            request_id=str(uuid.uuid4()),
            context_token=preview["context_token"],
            ack_missing=True,
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        )
        self.assertEqual(created["generation_status"], "generated")
        self._rewrite_states(plan_id, confirmation_id, ["teaching"] * 7)
        seven = export_service.preview_export(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            mode="single",
            weekly_plan_id=plan_id,
            confirmation_id=confirmation_id,
        )
        self.assertEqual(len(seven["items"][0]["columns"]), 7)
        self.assertEqual(
            seven["selection"][0]["date_range"],
            {"start": ANCHOR.isoformat(), "end": (ANCHOR + timedelta(days=6)).isoformat()},
        )
    def test_weekly_table_widths_match_grid_for_five_six_seven_and_zero(self) -> None:
        # The controlled template stays a frozen asset; this regression only
        # constrains the generated tcW declarations.
        self.assertEqual(
            hashlib.sha256(word_docx.WEEKLY_TEMPLATE.read_bytes()).hexdigest(),
            word_docx.WEEKLY_TEMPLATE_SHA256,
        )
        plan_id, confirmation_id, _ = self._make_confirmation()
        cases = (
            ("five-teaching-day", ["teaching"] * 5 + ["rest"] * 2, 5),
            ("six-teaching-day", ["teaching"] * 6 + ["rest"], 6),
            ("seven-teaching-day", ["teaching"] * 7, 7),
            ("zero-teaching-day", ["rest"] * 7, 5),
        )
        for label, states, expected_columns in cases:
            with self.subTest(case=label):
                self._rewrite_states(plan_id, confirmation_id, states)
                data = self._export_weekly_docx(plan_id, confirmation_id)
                root, table = _weekly_table(data)
                grid = table.find(f"{_W}tblGrid")
                self.assertIsNotNone(grid)
                grid_widths = [
                    int(column.get(f"{_W}w"))
                    for column in grid.findall(f"{_W}gridCol")
                ]
                self.assertEqual(len(grid_widths), expected_columns + 2, label)
                grid_total = sum(grid_widths)
                self.assertEqual(grid_total, 11052, label)
                table_properties = table.find(f"{_W}tblPr")
                self.assertEqual(
                    table_properties.find(f"{_W}tblW").get(f"{_W}w"),
                    "11052",
                    label,
                )
                self.assertEqual(
                    table_properties.find(f"{_W}tblW").get(f"{_W}type"),
                    "dxa",
                    label,
                )
                self.assertEqual(
                    table_properties.find(f"{_W}jc").get(f"{_W}val"),
                    "center",
                    label,
                )
                self.assertEqual(
                    table_properties.find(f"{_W}tblLayout").get(f"{_W}type"),
                    "fixed",
                    label,
                )
                rows = table.findall(f"{_W}tr")
                self.assertEqual(len(rows), 9, label)
                for row_index, row in enumerate(rows):
                    covered = 0
                    row_total = 0
                    for cell in row.findall(f"{_W}tc"):
                        cell_properties = cell.find(f"{_W}tcPr")
                        self.assertIsNotNone(cell_properties, label)
                        tc_w = cell_properties.find(f"{_W}tcW")
                        self.assertIsNotNone(tc_w, label)
                        span_node = cell_properties.find(f"{_W}gridSpan")
                        span = (
                            int(span_node.get(f"{_W}val"))
                            if span_node is not None
                            else 1
                        )
                        width = int(tc_w.get(f"{_W}w"))
                        self.assertEqual(
                            width,
                            sum(grid_widths[covered:covered + span]),
                            f"{label} row {row_index}: tcW {width} does not "
                            f"match its {span} covered grid column(s)",
                        )
                        covered += span
                        row_total += width
                    self.assertEqual(covered, expected_columns + 2, label)
                    self.assertEqual(
                        row_total,
                        grid_total,
                        f"{label} row {row_index}: row tcW total {row_total} "
                        f"!= grid total {grid_total}",
                    )
                # The four fixed weekly-label rows keep the 933 label cell and
                # one merged cell covering the 920 label plus all data columns.
                for row_index in range(5, 9):
                    cells = rows[row_index].findall(f"{_W}tc")
                    self.assertEqual(len(cells), 2, label)
                    label_properties = cells[0].find(f"{_W}tcPr")
                    self.assertEqual(
                        int(label_properties.find(f"{_W}tcW").get(f"{_W}w")),
                        933,
                        label,
                    )
                    merged_properties = cells[1].find(f"{_W}tcPr")
                    merged_span = merged_properties.find(f"{_W}gridSpan")
                    self.assertEqual(
                        int(merged_span.get(f"{_W}val")),
                        expected_columns + 1,
                        label,
                    )
                    self.assertEqual(
                        int(merged_properties.find(f"{_W}tcW").get(f"{_W}w")),
                        920 + sum(grid_widths[2:]),
                        label,
                    )
                # Template borders and frozen source text remain intact.
                for row in rows:
                    right = row.findall(f"{_W}tc")[-1].find(
                        f"{_W}tcPr/{_W}tcBorders/{_W}right"
                    )
                    self.assertIsNotNone(right, label)
                    self.assertEqual(right.get(f"{_W}val"), "single", label)
                    self.assertEqual(right.get(f"{_W}sz"), "4", label)
                    self.assertEqual(right.get(f"{_W}color"), "000000", label)
                text = _xml_text(root)
                for marker in (
                    "主题",
                    "本周重点",
                    "环境创设",
                    "生活习惯培养",
                    "家园共育",
                ):
                    self.assertIn(marker, text, label)
    def test_attempt_payload_validation_and_size_limit(self) -> None:
        plan_id, confirmation_id, _ = self._make_confirmation()
        preview = export_service.preview_export(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            mode="single",
            weekly_plan_id=plan_id,
            confirmation_id=confirmation_id,
        )
        created, _ = export_service.create_export(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            request_id=str(uuid.uuid4()),
            context_token=preview["context_token"],
            ack_missing=True,
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        )
        name = "校验周计划.docx"
        attempt = export_service.start_attempt(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            export_id=created["export_id"],
            filename=name,
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        )
        with self.assertRaises(LocalWeeklyExportConflict):
            export_service.finish_attempt(
                self.session,
                self.manager,
                profile_id=self.profile.id,
                export_id=created["export_id"],
                attempt_id=attempt["attempt_id"],
                filename=name,
                status="failed",
                byte_size=1,
                result_hash=None,
                launch_id=self.manager.launch_id,
                session_scope=self.manager.session_scope,
            )
        failed = export_service.finish_attempt(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            export_id=created["export_id"],
            attempt_id=attempt["attempt_id"],
            filename=name,
            status="failed",
            byte_size=0,
            result_hash=None,
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        )
        self.assertEqual(failed["status"], "failed")
        second, _ = export_service.create_export(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            request_id=str(uuid.uuid4()),
            context_token=preview["context_token"],
            ack_missing=True,
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        )
        using = export_service.read_export_content(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            export_id=second["export_id"],
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        )
        payload = using.handle.read()
        using.close()
        second_attempt = export_service.start_attempt(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            export_id=second["export_id"],
            filename=name,
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        )
        with self.assertRaises(LocalWeeklyExportConflict):
            export_service.finish_attempt(
                self.session,
                self.manager,
                profile_id=self.profile.id,
                export_id=second["export_id"],
                attempt_id=second_attempt["attempt_id"],
                filename=name,
                status="saved",
                byte_size=len(payload) + 1,
                result_hash=hashlib.sha256(payload).hexdigest(),
                launch_id=self.manager.launch_id,
                session_scope=self.manager.session_scope,
            )
        latest = export_service.read_latest_attempt(
            self.session,
            profile_id=self.profile.id,
            export_id=second["export_id"],
            filename=name,
        )
        self.assertEqual(latest["status"], "in_progress")
        saved = export_service.finish_attempt(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            export_id=second["export_id"],
            attempt_id=second_attempt["attempt_id"],
            filename=name,
            status="saved",
            byte_size=len(payload),
            result_hash=hashlib.sha256(payload).hexdigest(),
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        )
        self.assertEqual(saved["status"], "saved")
        limit_request = str(uuid.uuid4())
        with mock.patch.object(export_service, "MAX_DOCX_BYTES", 10):
            with self.assertRaises(LocalWeeklyExportUnavailable):
                export_service.create_export(
                    self.session,
                    self.manager,
                    profile_id=self.profile.id,
                    request_id=limit_request,
                    context_token=preview["context_token"],
                    ack_missing=True,
                    launch_id=self.manager.launch_id,
                    session_scope=self.manager.session_scope,
                )
        self.assertEqual(
            self.session.scalar(
                select(func.count())
                .select_from(LocalWeeklyPlanOperation)
                .where(LocalWeeklyPlanOperation.request_id == limit_request)
            ),
            0,
        )
    def test_long_text_is_rendered_in_frozen_docx(self) -> None:
        long_theme = "长主题" * 5000
        plan_id, confirmation_id, _ = self._make_confirmation(theme=long_theme)
        preview = export_service.preview_export(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            mode="single",
            weekly_plan_id=plan_id,
            confirmation_id=confirmation_id,
        )
        request_id = str(uuid.uuid4())
        created, _ = export_service.create_export(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            request_id=request_id,
            context_token=preview["context_token"],
            ack_missing=True,
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        )
        artifact = export_service.read_export_content(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            export_id=created["export_id"],
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        )
        data = artifact.handle.read()
        artifact.close()
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            document = archive.read("word/document.xml")
        self.assertIn(long_theme.encode("utf-8"), document)

    def test_unknown_files_survive_constructor_and_replaced_identity(self) -> None:
        self.work_root.mkdir(parents=True, exist_ok=True)
        unknown_docx = self.work_root / "unregistered.docx"
        unknown_json = self.work_root / "other-owner.json"
        unknown_docx.write_bytes(b"unknown-docx")
        unknown_json.write_text("unknown-json", encoding="utf-8")
        other = export_service.WeeklyExportManager(
            self.runtime, launch_id="other-launch", session_scope="other-scope"
        )
        self.assertTrue(unknown_docx.is_file())
        self.assertTrue(unknown_json.is_file())
        other.close()
        self.assertTrue(unknown_docx.is_file())
        self.assertTrue(unknown_json.is_file())
        plan_id, confirmation_id, _ = self._make_confirmation()
        preview = export_service.preview_export(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            mode="single",
            weekly_plan_id=plan_id,
            confirmation_id=confirmation_id,
        )
        created, _ = export_service.create_export(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            request_id=str(uuid.uuid4()),
            context_token=preview["context_token"],
            ack_missing=True,
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        )
        entry = self.manager.artifact_entry(
            export_service.tokens.export_id_hash(created["export_id"])
        )
        path = entry["docx"]
        path.unlink()
        path.write_bytes(b"replacement-owned-by-someone-else")
        self.manager.close()
        self.assertTrue(path.is_file())
        self.assertEqual(path.read_bytes(), b"replacement-owned-by-someone-else")
    def test_retry_reuses_the_same_fixed_docx(self) -> None:
        plan_id, confirmation_id, _ = self._make_confirmation()
        preview = export_service.preview_export(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            mode="single",
            weekly_plan_id=plan_id,
            confirmation_id=confirmation_id,
        )
        created, _ = export_service.create_export(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            request_id=str(uuid.uuid4()),
            context_token=preview["context_token"],
            ack_missing=True,
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        )
        entry = self.manager.artifact_entry(
            export_service.tokens.export_id_hash(created["export_id"])
        )
        old_bytes = entry["docx"].read_bytes()
        old_hash = hashlib.sha256(old_bytes).hexdigest()
        name = "重试固定.docx"
        attempt = export_service.start_attempt(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            export_id=created["export_id"],
            filename=name,
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        )
        export_service.finish_attempt(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            export_id=created["export_id"],
            attempt_id=attempt["attempt_id"],
            filename=name,
            status="failed",
            byte_size=0,
            result_hash=None,
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        )
        with self.assertRaises(LocalWeeklyExportConflict):
            export_service.retry_export(
                self.session,
                self.manager,
                profile_id=self.profile.id,
                snapshot_id="another-snapshot",
                request_id=str(uuid.uuid4()),
                old_export_id=created["export_id"],
                attempt_id=attempt["attempt_id"],
                launch_id=self.manager.launch_id,
                session_scope=self.manager.session_scope,
            )
        retry_request = str(uuid.uuid4())
        retry, _ = export_service.retry_export(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            snapshot_id=created["snapshot_id"],
            request_id=retry_request,
            old_export_id=created["export_id"],
            attempt_id=attempt["attempt_id"],
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        )
        artifact = export_service.read_export_content(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            export_id=retry["export_id"],
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        )
        new_bytes = artifact.handle.read()
        artifact.close()
        self.assertEqual(new_bytes, old_bytes)
        self.assertEqual(hashlib.sha256(new_bytes).hexdigest(), old_hash)
        with self.assertRaises(LocalWeeklyOperationConflict):
            export_service.retry_export(
                self.session,
                self.manager,
                profile_id=self.profile.id,
                snapshot_id="another-snapshot",
                request_id=retry_request,
                old_export_id=created["export_id"],
                attempt_id=attempt["attempt_id"],
                launch_id=self.manager.launch_id,
                session_scope=self.manager.session_scope,
            )
    def test_start_pause_before_publish_never_authorizes(self) -> None:
        plan_id, confirmation_id, _ = self._make_confirmation()
        preview = export_service.preview_export(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            mode="single",
            weekly_plan_id=plan_id,
            confirmation_id=confirmation_id,
        )
        created, _ = export_service.create_export(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            request_id=str(uuid.uuid4()),
            context_token=preview["context_token"],
            ack_missing=True,
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        )
        original = self.manager.publish

        def racing_publish(*, epoch, launch_id, session_scope):
            self.manager.pause(owner="race-pause")
            try:
                return original(
                    epoch=epoch,
                    launch_id=launch_id,
                    session_scope=session_scope,
                )
            finally:
                self.manager.resume(owner="race-pause")

        self.manager.publish = racing_publish
        try:
            with self.assertRaises(LocalWeeklyExportConflict):
                export_service.start_attempt(
                    self.session,
                    self.manager,
                    profile_id=self.profile.id,
                    export_id=created["export_id"],
                    filename="竞态.docx",
                    launch_id=self.manager.launch_id,
                    session_scope=self.manager.session_scope,
                )
        finally:
            self.manager.publish = original
        self.session.expire_all()
        count = self.session.scalar(
            select(func.count())
            .select_from(LocalWeeklyExportAttempt)
            .where(LocalWeeklyExportAttempt.profile_id == self.profile.id)
        )
        self.assertEqual(count, 0)
    def test_closed_manager_replays_committed_receipts(self) -> None:
        plan_id, confirmation_id, _ = self._make_confirmation()
        preview = export_service.preview_export(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            mode="single",
            weekly_plan_id=plan_id,
            confirmation_id=confirmation_id,
        )
        create_request = str(uuid.uuid4())
        created, _ = export_service.create_export(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            request_id=create_request,
            context_token=preview["context_token"],
            ack_missing=True,
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        )
        name = "关闭回放.docx"
        attempt = export_service.start_attempt(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            export_id=created["export_id"],
            filename=name,
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        )
        export_service.finish_attempt(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            export_id=created["export_id"],
            attempt_id=attempt["attempt_id"],
            filename=name,
            status="failed",
            byte_size=0,
            result_hash=None,
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        )
        retry_request = str(uuid.uuid4())
        retry, _ = export_service.retry_export(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            snapshot_id=created["snapshot_id"],
            request_id=retry_request,
            old_export_id=created["export_id"],
            attempt_id=attempt["attempt_id"],
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        )
        self.assertEqual(retry["generation_status"], "generated")
        operation_id = retry["operation_id"]
        self.manager.close()
        replay_create, created_again = export_service.create_export(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            request_id=create_request,
            context_token=preview["context_token"],
            ack_missing=True,
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        )
        self.assertFalse(created_again)
        self.assertEqual(replay_create["generation_status"], "transfer_expired")
        self.assertNotIn("export_id", replay_create)
        replay_retry, retried_again = export_service.retry_export(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            snapshot_id=created["snapshot_id"],
            request_id=retry_request,
            old_export_id=created["export_id"],
            attempt_id=attempt["attempt_id"],
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        )
        self.assertFalse(retried_again)
        self.assertEqual(replay_retry["operation_id"], operation_id)
        self.assertEqual(replay_retry["generation_status"], "transfer_expired")
        self.assertNotIn("export_id", replay_retry)
    def test_operation_projection_rejects_forged_refs(self) -> None:
        plan_id, confirmation_id, _ = self._make_confirmation()
        preview = export_service.preview_export(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            mode="single",
            weekly_plan_id=plan_id,
            confirmation_id=confirmation_id,
        )
        first_request = str(uuid.uuid4())
        first, _ = export_service.create_export(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            request_id=first_request,
            context_token=preview["context_token"],
            ack_missing=True,
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        )
        operation = self.session.scalars(
            select(LocalWeeklyPlanOperation).where(
                LocalWeeklyPlanOperation.request_id == first_request
            )
        ).one()
        forged = dict(operation.result_json)
        forged["token_id"] = "not-a-real-token"
        operation.result_json = forged
        self.session.commit()
        with self.assertRaises(LocalWeeklyInvalid):
            export_service.read_operation(
                self.session,
                self.manager,
                profile_id=self.profile.id,
                request_id=first_request,
            )
        second, _ = export_service.create_export(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            request_id=str(uuid.uuid4()),
            context_token=preview["context_token"],
            ack_missing=True,
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        )
        token = self.session.scalars(
            select(LocalWeeklyExportToken).where(
                LocalWeeklyExportToken.snapshot_id == second["snapshot_id"]
            )
        ).one()
        token.token_hash = "0" * 64
        self.session.commit()
        projected = export_service.read_operation(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            request_id=second["request_id"],
        )
        self.assertEqual(projected["generation_status"], "transfer_expired")
        self.assertNotIn("export_id", projected)
    def test_generation_crossing_ttl_registers_nothing(self) -> None:
        plan_id, confirmation_id, _ = self._make_confirmation()
        preview = export_service.preview_export(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            mode="single",
            weekly_plan_id=plan_id,
            confirmation_id=confirmation_id,
        )
        request_id = str(uuid.uuid4())
        real_now = export_service._now
        real_generate = export_service._generate_docx
        advanced = {"value": False}

        def fake_now():
            value = real_now()
            if advanced["value"]:
                return value + timedelta(seconds=1000)
            return value

        def generate(manifest):
            advanced["value"] = True
            return real_generate(manifest)

        with mock.patch.object(export_service, "_now", side_effect=fake_now):
            with mock.patch.object(export_service, "_generate_docx", side_effect=generate):
                with self.assertRaises(LocalWeeklyPreviewExpired):
                    export_service.create_export(
                        self.session,
                        self.manager,
                        profile_id=self.profile.id,
                        request_id=request_id,
                        context_token=preview["context_token"],
                        ack_missing=True,
                        launch_id=self.manager.launch_id,
                        session_scope=self.manager.session_scope,
                    )
        self.session.expire_all()
        self.assertEqual(
            self.session.scalar(
                select(func.count())
                .select_from(LocalWeeklyPlanOperation)
                .where(LocalWeeklyPlanOperation.request_id == request_id)
            ),
            0,
        )
        self.assertEqual(
            self.session.scalar(select(func.count()).select_from(LocalWeeklyExportSnapshot)),
            0,
        )
        self.assertEqual(
            self.session.scalar(select(func.count()).select_from(LocalWeeklyExportToken)),
            0,
        )
    def test_word_view_uses_frozen_columns_and_display_grade(self) -> None:
        item = {
            "weekly_plan_id": "plan",
            "term_id": "term",
            "confirmation_version": 1,
            "creation_context": {
                "week_anchor_date": "2026-09-07",
                "week_number_snapshot": 1,
            },
            "header": {
                "school_name": "幼儿园",
                "class_name": "中一班",
                "grade": "middle",
                "header_teacher_names": ["教师"],
                "caregiver_name": "保育",
            },
            "date_range": {"start": "2026-09-07", "end": "2026-09-13"},
            "columns": [
                {"date": "2026-09-07", "day_state": "outside_term"},
                {"date": "2026-09-08", "day_state": "rest"},
            ],
            "content": {
                "theme": "",
                "deterministic": [
                    {
                        "date": "2026-09-07",
                        "day_state": "outside_term",
                        "effective": {},
                        "source": None,
                    },
                    {
                        "date": "2026-09-08",
                        "day_state": "rest",
                        "effective": {},
                        "source": None,
                    },
                ],
                "outdoor_game_slots": {},
                "focus_area": None,
                "weekly_columns": {},
                "materials": None,
            },
            "facts": {"warnings": []},
        }
        view = export_service._view_from_item(item)
        self.assertTrue(view["columns"][0]["outside_term"])
        self.assertFalse(view["columns"][0]["holiday"])
        self.assertTrue(view["columns"][1]["holiday"])
        self.assertFalse(view["columns"][1]["outside_term"])
        self.assertEqual(view["header"]["grade"], "中班")
        self.assertEqual(item["header"]["grade"], "middle")
    def test_preview_live_warning_does_not_rewrite_historical_facts(self) -> None:
        daily = self._create_daily()
        plan_id, confirmation_id, _ = self._make_confirmation()
        row = self.session.get(LocalWeeklyPlanConfirmation, confirmation_id)
        original_facts = copy.deepcopy(row.snapshot_json["facts"])
        daily_plan_service.save(
            self.session,
            plan_id=daily["id"],
            expected_content_version=daily["current_content_version"],
            adopted_content=_adopted("更新后的树叶"),
        )
        preview = export_service.preview_export(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            mode="single",
            weekly_plan_id=plan_id,
            confirmation_id=confirmation_id,
        )
        self.assertTrue(preview["warnings"])
        self.assertEqual(preview["items"][0]["facts"], original_facts)
        self.assertTrue(
            all(
                warning["details"].get("weekly_plan_id") == plan_id
                and warning["details"].get("confirmation_id") == confirmation_id
                for warning in preview["warnings"]
            )
        )
    def test_late_terminal_uses_retained_artifact_metadata(self) -> None:
        plan_id, confirmation_id, _ = self._make_confirmation()
        preview = export_service.preview_export(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            mode="single",
            weekly_plan_id=plan_id,
            confirmation_id=confirmation_id,
        )
        created, _ = export_service.create_export(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            request_id=str(uuid.uuid4()),
            context_token=preview["context_token"],
            ack_missing=True,
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        )
        artifact = export_service.read_export_content(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            export_id=created["export_id"],
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        )
        payload = artifact.handle.read()
        artifact.complete()
        artifact.close()
        name = "迟到终态.docx"
        attempt = export_service.start_attempt(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            export_id=created["export_id"],
            filename=name,
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        )
        real_now = export_service._now
        with mock.patch.object(
            export_service,
            "_now",
            side_effect=lambda: real_now() + timedelta(seconds=1000),
        ):
            saved = export_service.finish_attempt(
                self.session,
                self.manager,
                profile_id=self.profile.id,
                export_id=created["export_id"],
                attempt_id=attempt["attempt_id"],
                filename=name,
                status="saved",
                byte_size=len(payload),
                result_hash=hashlib.sha256(payload).hexdigest(),
                launch_id=self.manager.launch_id,
                session_scope=self.manager.session_scope,
            )
        self.assertEqual(saved["status"], "saved")
    def test_held_stream_reference_survives_alias_retirement(self) -> None:
        plan_id, confirmation_id, _ = self._make_confirmation()
        preview = export_service.preview_export(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            mode="single",
            weekly_plan_id=plan_id,
            confirmation_id=confirmation_id,
        )
        created, _ = export_service.create_export(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            request_id=str(uuid.uuid4()),
            context_token=preview["context_token"],
            ack_missing=True,
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        )
        held = export_service.read_export_content(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            export_id=created["export_id"],
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        )
        name = "alias-retire.docx"
        attempt = export_service.start_attempt(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            export_id=created["export_id"],
            filename=name,
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        )
        export_service.finish_attempt(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            export_id=created["export_id"],
            attempt_id=attempt["attempt_id"],
            filename=name,
            status="failed",
            byte_size=0,
            result_hash=None,
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        )
        retry, _ = export_service.retry_export(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            snapshot_id=created["snapshot_id"],
            request_id=str(uuid.uuid4()),
            old_export_id=created["export_id"],
            attempt_id=attempt["attempt_id"],
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        )
        self.assertFalse(self.manager.wait_idle(timeout=0.0))
        held.close()
        self.assertTrue(self.manager.wait_idle(timeout=0.0))
        fresh = export_service.read_export_content(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            export_id=retry["export_id"],
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        )
        self.assertTrue(fresh.handle.read(16))
        fresh.close()
    def test_asgi_start_send_failure_releases_artifact(self) -> None:
        plan_id, confirmation_id, _ = self._make_confirmation()
        preview = export_service.preview_export(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            mode="single",
            weekly_plan_id=plan_id,
            confirmation_id=confirmation_id,
        )
        created, _ = export_service.create_export(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            request_id=str(uuid.uuid4()),
            context_token=preview["context_token"],
            ack_missing=True,
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        )
        artifact = export_service.read_export_content(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            export_id=created["export_id"],
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        )
        response = export_api._ArtifactStreamingResponse(
            export_api._iter_artifact(
                artifact,
                self.manager,
                self.manager.launch_id,
                self.manager.session_scope,
            ),
            artifact=artifact,
            media_type="application/octet-stream",
            headers={"Content-Length": str(artifact.size)},
        )

        async def receive():
            await asyncio.Event().wait()

        async def send(message):
            if message["type"] == "http.response.start":
                raise OSError("start-send-failed")
            raise AssertionError("body must not start")

        with self.assertRaises(OSError):
            asyncio.run(
                response(
                    {"type": "http", "method": "GET", "path": "/", "headers": []},
                    receive,
                    send,
                )
            )
        self.assertIsNone(artifact.handle)
        self.assertTrue(self.manager.wait_idle(timeout=0.0))
    def test_download_holds_file_barrier_until_close(self) -> None:
        plan_id, confirmation_id, _ = self._make_confirmation()
        preview = export_service.preview_export(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            mode="single",
            weekly_plan_id=plan_id,
            confirmation_id=confirmation_id,
        )
        created, _ = export_service.create_export(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            request_id=str(uuid.uuid4()),
            context_token=preview["context_token"],
            ack_missing=True,
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        )
        artifact = export_service.read_export_content(
            self.session,
            self.manager,
            profile_id=self.profile.id,
            export_id=created["export_id"],
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        )
        self.assertGreaterEqual(self.manager._barrier.active_counts[1], 1)
        self.manager.pause(owner="download-barrier")
        artifact.close()
        self.manager.resume(owner="download-barrier")
        self.assertEqual(self.manager._barrier.active_counts[1], 0)
        self.assertTrue(self.manager.wait_idle(timeout=0.0))
    def test_work_root_junction_is_rejected_without_touching_target(self) -> None:
        base = Path(tempfile.mkdtemp(prefix="kgm-we-junction-r05-"))
        data = base / "data"
        target = base / "outside-target"
        data.mkdir()
        target.mkdir()
        sentinel = target / "keep.txt"
        sentinel.write_text("keep", encoding="utf-8")
        link = data / ".weekly-export-work"
        try:
            subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(target)],
                check=True,
                capture_output=True,
            )
            self.assertTrue(os.path.isjunction(link))
            fake = type(
                "FakeRuntime",
                (),
                {"data_dir": data, "weekly_export_work_root": link},
            )()
            manager = export_service.WeeklyExportManager(
                fake, launch_id="junction", session_scope="junction"
            )
            try:
                with self.assertRaises(LocalWeeklyExportUnavailable):
                    manager.ensure_work_root()
                self.assertEqual(
                    sorted(path.name for path in target.iterdir()), ["keep.txt"]
                )
                self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")
            finally:
                manager.close()
        finally:
            if os.path.isjunction(link):
                os.rmdir(link)
            sentinel.unlink(missing_ok=True)
            target.rmdir()
            data.rmdir()
            base.rmdir()
    def test_owned_temp_finished_lease_and_abort_lifetimes(self) -> None:
        with self.manager.activity(
            kind="native",
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        ):
            temp = self.manager.create_owned_temp(owner="host:test")
            with zipfile.ZipFile(temp.handle, "w") as archive:
                archive.writestr("verified.txt", "same-handle")
            finished = temp.finish()
            with zipfile.ZipFile(finished, "r") as archive:
                self.assertEqual(archive.read("verified.txt"), b"same-handle")
            path = finished.path
            second = self.manager.create_owned_temp(owner="host:test")
            second_path = second.path
            second.abort()
            self.assertFalse(second_path.exists())
            self.manager.pause(owner="owned-temp-pause")
            self.manager.close()
            finished.close()
            self.assertFalse(path.exists())
    def test_http_receipt_replay_with_missing_manager(self) -> None:
        plan_id, confirmation_id, _ = self._make_confirmation()
        server = self.start_server(self.runtime)
        client = server.client()
        preview = client.post(
            "/api/weekly-exports/preview",
            {
                "mode": "single",
                "weekly_plan_id": plan_id,
                "confirmation_id": confirmation_id,
            },
        )[1]
        create_request = str(uuid.uuid4())
        create_body = {
            "request_id": create_request,
            "context_token": preview["context_token"],
            "ack_missing": True,
        }
        created = client.post("/api/weekly-exports", create_body)[1]
        name = "missing-manager.docx"
        attempt = client.post(
            f"/api/weekly-exports/{created['export_id']}/attempts",
            {"filename": name},
        )[1]
        client.post(
            f"/api/weekly-exports/{created['export_id']}/attempts/result",
            {
                "attempt_id": attempt["attempt_id"],
                "filename": name,
                "status": "cancelled",
                "byte_size": 0,
                "result_hash": None,
            },
        )
        retry_request = str(uuid.uuid4())
        retry_body = {
            "request_id": retry_request,
            "old_export_id": created["export_id"],
            "attempt_id": attempt["attempt_id"],
        }
        retry = client.post(
            f"/api/weekly-exports/snapshots/{created['snapshot_id']}/retry",
            retry_body,
        )[1]
        self.assertEqual(retry["generation_status"], "generated")
        original = server.app.state.weekly_export_manager
        server.app.state.weekly_export_manager = None
        try:
            status_create, replay_create = client.post(
                "/api/weekly-exports", create_body
            )
            self.assertEqual(status_create, 200)
            self.assertEqual(replay_create["operation_id"], created["operation_id"])
            self.assertEqual(replay_create["generation_status"], "transfer_expired")
            self.assertNotIn("export_id", replay_create)
            status_retry, replay_retry = client.post(
                f"/api/weekly-exports/snapshots/{created['snapshot_id']}/retry",
                retry_body,
            )
            self.assertEqual(status_retry, 200)
            self.assertEqual(replay_retry["operation_id"], retry["operation_id"])
            self.assertEqual(replay_retry["generation_status"], "transfer_expired")
            self.assertNotIn("export_id", replay_retry)
            status_new, error = client.post(
                "/api/weekly-exports",
                {
                    "request_id": str(uuid.uuid4()),
                    "context_token": preview["context_token"],
                    "ack_missing": True,
                },
            )
            self.assertEqual(status_new, 503, error)
            self.assertEqual(error["error"]["code"], "WEEKLY_EXPORT_UNAVAILABLE")
        finally:
            server.app.state.weekly_export_manager = original
    def test_owned_temp_read_interface_and_writer_idle(self) -> None:
        self.assertTrue(self.manager.wait_idle(timeout=0.0))
        with self.manager.activity(
            kind="native",
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        ):
            temp = self.manager.create_owned_temp(owner="host:read")
            temp.handle.write(b"0123456789")
            finished = temp.finish()
            self.assertEqual(finished.read(0), b"")
            self.assertEqual(finished.tell(), 0)
            self.assertEqual(finished.read(3), b"012")
            self.assertEqual(finished.tell(), 3)
            self.assertEqual(finished.seek(0), 0)
            self.assertEqual(finished.read(-1), b"0123456789")
            self.assertEqual(finished.read(), b"")
            finished.seek(0)
            self.assertEqual(os.fstat(finished.fileno()).st_size, 10)
            finished.close()
        self.assertTrue(self.manager.wait_idle(timeout=0.0))
        with self.manager.activity(
            kind="native",
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        ):
            writer = self.manager.create_owned_temp(owner="host:writer")
            writer_path = writer.path
        self.assertFalse(self.manager.wait_idle(timeout=0.0))
        self.manager.close()
        self.assertFalse(self.manager.wait_idle(timeout=0.0))
        leased = writer.finish()
        self.assertFalse(self.manager.wait_idle(timeout=0.0))
        leased.close()
        self.assertTrue(self.manager.wait_idle(timeout=0.0))
        self.assertFalse(writer_path.exists())
    def test_actual_route_response_start_failure_releases(self) -> None:
        plan_id, confirmation_id, _ = self._make_confirmation()
        server = self.start_server(self.runtime)
        app_manager = server.app.state.weekly_export_manager
        client = server.client()
        preview = client.post(
            "/api/weekly-exports/preview",
            {
                "mode": "single",
                "weekly_plan_id": plan_id,
                "confirmation_id": confirmation_id,
            },
        )[1]
        created = client.post(
            "/api/weekly-exports",
            {
                "request_id": str(uuid.uuid4()),
                "context_token": preview["context_token"],
                "ack_missing": True,
            },
        )[1]
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": f"/api/weekly-exports/{created['export_id']}/content",
                "headers": [],
                "app": server.app,
            }
        )
        response = export_api.read_weekly_export_content(
            created["export_id"], request, self.session
        )
        self.assertIsInstance(response, export_api._ArtifactStreamingResponse)

        async def receive():
            await asyncio.Event().wait()

        async def send(message):
            if message["type"] == "http.response.start":
                raise OSError("route-start-send-failed")
            raise AssertionError("body must not start")

        with self.assertRaises(OSError):
            asyncio.run(
                response(
                    {"type": "http", "method": "GET", "path": "/", "headers": []},
                    receive,
                    send,
                )
            )
        self.assertTrue(app_manager.wait_idle(timeout=0.0))
    def test_finished_read_lease_keeps_idle_false_until_close(self) -> None:
        with self.manager.activity(
            kind="native",
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        ):
            temp = self.manager.create_owned_temp(owner="host:lease")
            temp.handle.write(b"lease")
            leased = temp.finish()
        path = leased.path
        self.assertFalse(self.manager.wait_idle(timeout=0.0))
        self.assertEqual(leased.read(-1), b"lease")
        leased.close()
        self.assertTrue(self.manager.wait_idle(timeout=0.0))
        self.assertFalse(path.exists())
    def test_create_after_close_and_root_guard_deferral(self) -> None:
        self.manager.close()
        with self.assertRaises(LocalWeeklyExportUnavailable):
            self.manager.create_owned_temp(owner="closed")
        self.assertIsNone(self.manager._root_guard)

    def test_root_guard_survives_until_live_writer_aborts(self) -> None:
        with self.manager.activity(
            kind="native",
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        ):
            writer = self.manager.create_owned_temp(owner="guard")
        self.assertIsNotNone(self.manager._root_guard)
        self.manager.close()
        self.assertIsNotNone(self.manager._root_guard)
        self.assertFalse(self.manager.wait_idle(timeout=0.0))
        writer.abort()
        self.assertTrue(self.manager.wait_idle(timeout=0.0))
        self.assertIsNone(self.manager._root_guard)
    def test_finish_lease_registration_race_with_close(self) -> None:
        with self.manager.activity(
            kind="native",
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        ):
            temp = self.manager.create_owned_temp(owner="race-finish")
            temp.handle.write(b"race")
        entered = threading.Event()
        release = threading.Event()
        original_enter = backup_fs.FileLease.__enter__
        result = {}

        def blocked_enter(lease):
            entered.set()
            if not release.wait(5):
                raise RuntimeError("finish block timed out")
            return original_enter(lease)

        def run_finish():
            try:
                result["lease"] = temp.finish()
            except BaseException as error:
                result["error"] = error

        with mock.patch.object(backup_fs.FileLease, "__enter__", blocked_enter):
            finish_thread = threading.Thread(target=run_finish)
            finish_thread.start()
            self.assertTrue(entered.wait(5))
            close_thread = threading.Thread(target=self.manager.close)
            close_thread.start()
            close_thread.join(0.2)
            self.assertTrue(close_thread.is_alive())
            release.set()
            finish_thread.join(5)
            close_thread.join(5)
        self.assertNotIn("error", result)
        leased = result["lease"]
        self.assertIsNotNone(self.manager._root_guard)
        self.assertFalse(self.manager.wait_idle(timeout=0.0))
        self.assertEqual(leased.read(-1), b"race")
        leased.close()
        self.assertTrue(self.manager.wait_idle(timeout=0.0))
        self.assertIsNone(self.manager._root_guard)
    def test_release_stays_busy_until_verified_fd_closes(self) -> None:
        with self.manager.activity(
            kind="native",
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        ):
            temp = self.manager.create_owned_temp(owner="race-release")
            temp.handle.write(b"release")
            leased = temp.finish()
        entered = threading.Event()
        release = threading.Event()
        original_close = backup_fs.FileLease.close
        idle_result = {}

        def blocked_close(lease):
            entered.set()
            if not release.wait(5):
                raise RuntimeError("release block timed out")
            return original_close(lease)

        def run_wait():
            idle_result["value"] = self.manager.wait_idle(timeout=1.0)

        with mock.patch.object(backup_fs.FileLease, "close", blocked_close):
            release_thread = threading.Thread(target=leased.close)
            release_thread.start()
            self.assertTrue(entered.wait(5))
            wait_thread = threading.Thread(target=run_wait)
            wait_thread.start()
            wait_thread.join(0.2)
            self.assertTrue(wait_thread.is_alive())
            release.set()
            release_thread.join(5)
            wait_thread.join(5)
        self.assertTrue(idle_result.get("value"))
        self.assertFalse(leased.path.exists())
    def test_abort_does_not_steal_borrowed_read_lease(self) -> None:
        with self.manager.activity(
            kind="native",
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        ):
            temp = self.manager.create_owned_temp(owner="abort-reader")
            temp.handle.write(b"borrowed")
            leased = temp.finish()
        self.manager.abort_owned_temp(temp.token)
        self.assertFalse(self.manager.wait_idle(timeout=0.0))
        self.assertEqual(leased.read(-1), b"borrowed")
        leased.close()
        self.assertTrue(self.manager.wait_idle(timeout=0.0))
        self.assertFalse(leased.path.exists())
    def test_finish_fsync_failure_closes_writer_and_cleans_known_file(self) -> None:
        with self.manager.activity(
            kind="native",
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        ):
            temp = self.manager.create_owned_temp(owner="fsync-fail")
            temp.handle.write(b"fsync-failure")
            writer = temp.handle
            fd = writer.fileno()
            path = temp.path
        real_fsync = os.fsync
        hits = {"count": 0}

        def failing_fsync(target_fd):
            if target_fd == fd and hits["count"] == 0:
                hits["count"] += 1
                raise OSError("forced-fsync-failure")
            return real_fsync(target_fd)

        with mock.patch("os.fsync", side_effect=failing_fsync):
            with self.assertRaises(OSError):
                temp.finish()
        self.assertTrue(writer.closed)
        self.assertNotIn(temp.token, self.manager._temps)
        self.assertFalse(path.exists())
        self.assertTrue(self.manager.wait_idle(timeout=0.0))
        self.manager.close()
        self.assertIsNone(self.manager._root_guard)

    def test_finish_flush_failure_closes_writer_and_cleans_known_file(self) -> None:
        with self.manager.activity(
            kind="native",
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        ):
            temp = self.manager.create_owned_temp(owner="flush-fail")
            temp.handle.write(b"flush-failure")
            writer = temp.handle
            path = temp.path
        real_flush = writer.flush
        hits = {"count": 0}

        def failing_flush():
            if hits["count"] == 0:
                hits["count"] += 1
                raise OSError("forced-flush-failure")
            return real_flush()

        with mock.patch.object(writer, "flush", side_effect=failing_flush):
            with self.assertRaises(OSError):
                temp.finish()
        self.assertTrue(writer.closed)
        self.assertNotIn(temp.token, self.manager._temps)
        self.assertFalse(path.exists())
        self.assertTrue(self.manager.wait_idle(timeout=0.0))
        self.manager.close()
        self.assertIsNone(self.manager._root_guard)
    def test_finish_close_failure_preserves_owner_writer_for_abort(self) -> None:
        with self.manager.activity(
            kind="native",
            launch_id=self.manager.launch_id,
            session_scope=self.manager.session_scope,
        ):
            temp = self.manager.create_owned_temp(owner="close-fail")
            temp.handle.write(b"close-failure")
            writer = temp.handle
            path = temp.path
        with mock.patch.object(writer, "close", side_effect=OSError("forced-close-failure")):
            with self.assertRaises(OSError):
                temp.finish()
            self.manager.close()
            self.assertFalse(writer.closed)
            self.assertIn(temp.token, self.manager._temps)
            self.assertFalse(self.manager.wait_idle(timeout=0.0))
            self.assertIsNotNone(self.manager._root_guard)
            self.assertTrue(path.exists())
            with self.assertRaises(LocalWeeklyExportUnavailable):
                temp.abort()
            self.assertFalse(writer.closed)
            self.assertIn(temp.token, self.manager._temps)
            self.assertFalse(self.manager.wait_idle(timeout=0.0))
            self.assertIsNotNone(self.manager._root_guard)
            self.assertTrue(path.exists())
            with self.assertRaises(LocalWeeklyExportUnavailable):
                temp.abort()
            self.assertFalse(writer.closed)
            self.assertIn(temp.token, self.manager._temps)
        temp.abort()
        self.assertTrue(writer.closed)
        self.assertNotIn(temp.token, self.manager._temps)
        self.assertFalse(path.exists())
        self.assertTrue(self.manager.wait_idle(timeout=0.0))
        self.assertIsNone(self.manager._root_guard)
        temp.abort()
        self.assertTrue(self.manager.wait_idle(timeout=0.0))
    def test_weekly_filename_windows_reserved_and_illegal(self) -> None:
        valid = ["正常周计划.docx", "A.B.docx"]
        for name in valid:
            self.assertEqual(export_service._filename(name), name)
        invalid = ["CON.docx", "con.docx", "CON.note.docx", "aux.docx",
                   "a:b.docx", "a<.docx", "a|.docx", "a?.docx"]
        for name in invalid:
            with self.assertRaises(LocalWeeklyInvalid):
                export_service._filename(name)
    def test_invalid_filename_attempt_rejected_without_new_attempt(self) -> None:
        plan_id, confirmation_id, _ = self._make_confirmation()
        self.manager.close()
        server = self.start_server(self.runtime)
        client = server.client()
        preview = client.post(
            "/api/weekly-exports/preview",
            {"mode": "single", "weekly_plan_id": plan_id,
             "confirmation_id": confirmation_id},
        )[1]
        created = client.post(
            "/api/weekly-exports",
            {"request_id": str(uuid.uuid4()), "context_token": preview["context_token"],
             "ack_missing": True},
        )[1]
        before_attempts = self.session.scalar(
            select(func.count()).select_from(LocalWeeklyExportAttempt)
        )
        before_tokens = self.session.scalar(
            select(func.count()).select_from(LocalWeeklyExportToken)
        )
        for bad in ("bad.docx ", "bad.docx.", "bad\\x00.docx"):
            status, error = client.post(
                f"/api/weekly-exports/{created['export_id']}/attempts",
                {"filename": bad},
            )
            self.assertIn(status, (400, 422), error)
        self.assertEqual(
            self.session.scalar(select(func.count()).select_from(LocalWeeklyExportAttempt)),
            before_attempts,
        )
        self.assertEqual(
            self.session.scalar(select(func.count()).select_from(LocalWeeklyExportToken)),
            before_tokens,
        )
        status, attempt = client.post(
            f"/api/weekly-exports/{created['export_id']}/attempts",
            {"filename": "合法.docx"},
        )
        self.assertEqual(status, 200, attempt)
        self.assertEqual(attempt["filename"], "合法.docx")
class Schema2WeeklyExportTests(WeeklyExportTests):
    def _promote_current_schema2(self, plan_id: str) -> int:
        plan = self.session.get(LocalWeeklyPlan, plan_id)
        current = self.session.get(LocalWeeklyPlanContent, plan.current_draft_id)
        content = copy.deepcopy(current.content_json)
        if content.get("schema_version") == 1:
            content = weekly_plan_content.promote_to_schema2(content)
        content["theme"] = "AI新主题"
        content["weekly_columns"] = {
            key: f"AI四栏-{key}" for key in weekly_plan_content.WEEKLY_COLUMN_KEYS
        }
        content["materials"] = None
        new_id = uuid.uuid4().hex
        new_version = current.version + 1
        new_hash = weekly_plan_content.content_hash(content)
        self.session.add(LocalWeeklyPlanContent(
            id=new_id, weekly_plan_id=plan_id, version=new_version,
            schema_version=2, content_json=content, content_hash=new_hash,
            editor_profile_id=self.profile.id,
        ))
        self.session.commit()
        plan = self.session.get(LocalWeeklyPlan, plan_id)
        plan.current_draft_id = new_id
        plan.current_draft_version = new_version
        self.session.commit()
        return new_version
    def _confirm_current(self, plan_id: str, version: int) -> str:
        target = weekly_plan_service.confirmation_preview(
            self.session, runtime=self.runtime, profile_id=self.profile.id,
            launch_id=self.manager.launch_id,
            session_scope_hash=self.manager.session_scope_hash,
            plan_id=plan_id, expected_draft_version=version,
        )
        confirmed = weekly_plan_service.confirm(
            self.session, runtime=self.runtime, profile_id=self.profile.id,
            launch_id=self.manager.launch_id,
            session_scope_hash=self.manager.session_scope_hash,
            request_id=str(uuid.uuid4()), plan_id=plan_id,
            expected_draft_version=version,
            context_token=target["preview_token"], ack_missing=True,
            ack_stale=True,
        )
        return confirmed["confirmation"]["id"]
    def test_schema2_mixed_confirmations_export_new_text_and_empty_materials(self) -> None:
        plan_id, old_confirmation, _old_version = self._make_confirmation()
        old_docx = self._export_weekly_docx(plan_id, old_confirmation)
        version = self._promote_current_schema2(plan_id)
        new_confirmation = self._confirm_current(plan_id, version)
        new_docx = self._export_weekly_docx(plan_id, new_confirmation)
        old_root, _ = _weekly_table(old_docx)
        new_root, _ = _weekly_table(new_docx)
        old_text = _xml_text(old_root)
        new_text = _xml_text(new_root)
        self.assertNotIn("AI四栏-key_week_focus", old_text)
        self.assertIn("AI新主题", new_text)
        self.assertIn("AI四栏-key_week_focus", new_text)
        self.assertNotIn("None", new_text)
        self.assertNotIn("null", new_text)
        self.assertNotIn("来源", new_text)
        again = self._export_weekly_docx(plan_id, old_confirmation)
        again_root, _ = _weekly_table(again)
        self.assertNotIn("AI四栏-key_week_focus", _xml_text(again_root))
        out = os.environ.get("KGM_G2_WORD_OUT")
        if out:
            from pathlib import Path
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            Path(out).write_bytes(new_docx)