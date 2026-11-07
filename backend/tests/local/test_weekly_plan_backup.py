"""Weekly backup/logical-validation tests (engineering spec §7)."""

from __future__ import annotations

import json
import sqlite3
import threading
import unittest
import uuid
from datetime import date, datetime

from sqlalchemy import select

from app.local import (
    backup_snapshot,
    backup_validate,
    config_service,
    daily_plan_service,
    profile_service,
    weekly_plan_service,
)
from app.local.models import (
    LocalProfile,
    LocalWeeklyPlanConfirmation,
    LocalSettings,
    LocalTerm,
    LocalWeeklyExportAttempt,
    LocalWeeklyExportSnapshot,
    LocalWeeklyExportToken,
)
from app.local.migrate import head_revision
from app.local.normalize import normalize_initialization
from app.local.runtime import LocalRuntime
from app.local.weekly_plan_tokens import scope_hash
from tests.local.support import LocalTestCase

ANCHOR = date(2026, 9, 7)


class WeeklyBackupTests(LocalTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.runtime = self.make_runtime()
        self.session = self.runtime.session()
        self.addCleanup(self.session.close)
        profile_service.initialize(
            self.session,
            normalize_initialization(
                request_id=str(uuid.uuid4()),
                display_name="测试教师",
                class_name="中一班",
                grade="middle",
                term_name="秋季学期",
                start_date=ANCHOR.isoformat(),
                end_date="2026-10-30",
                school_name="测试幼儿园",
            ),
        )
        self.session.expire_all()
        self.profile = self.session.scalars(select(LocalProfile)).one()
        self.term = self.session.scalars(select(LocalTerm)).one()
        self.settings = self.session.get(LocalSettings, "singleton")
        daily_plan_service.create_or_open(
            self.session,
            plan_date=ANCHOR,
            raw_lesson_plan=None,
            adopted_content={
                "morning_talk": {"topic": "主题"},
                "group_activity": {"theme": "活动"},
            },
        )
        preview = weekly_plan_service.create_preview(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            launch_id="backup-launch",
            session_scope_hash=scope_hash("backup-scope"),
            term_id=self.term.id,
            week_anchor_date=ANCHOR,
        )
        result, _ = weekly_plan_service.create_or_open(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            launch_id="backup-launch",
            session_scope_hash=scope_hash("backup-scope"),
            request_id=str(uuid.uuid4()),
            term_id=self.term.id,
            week_anchor_date=ANCHOR,
            expected_config_version=self.settings.config_version,
            context_token=preview["create_token"],
        )
        self.plan_id = result["weekly_plan_id"]
        saved = weekly_plan_service.save_draft(
            self.session,
            profile_id=self.profile.id,
            request_id=str(uuid.uuid4()),
            plan_id=self.plan_id,
            expected_draft_version=1,
            patch={"theme": "备份主题"},
        )
        confirmation = weekly_plan_service.confirmation_preview(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            launch_id="backup-launch",
            session_scope_hash=scope_hash("backup-scope"),
            plan_id=self.plan_id,
            expected_draft_version=saved["draft"]["version"],
        )
        weekly_plan_service.confirm(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            launch_id="backup-launch",
            session_scope_hash=scope_hash("backup-scope"),
            request_id=str(uuid.uuid4()),
            plan_id=self.plan_id,
            expected_draft_version=saved["draft"]["version"],
            context_token=confirmation["preview_token"],
            ack_missing=True,
            ack_stale=True,
            note=None,
        )
        self.copy = self.tmp_root / "weekly-copy.db"
        source = sqlite3.connect(str(self.runtime.db_path))
        target = sqlite3.connect(str(self.copy))
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()

    def _validate(self) -> dict:
        return backup_validate.validate_database(
            self.copy,
            migrate_old=False,
            require_current=True,
            scratch_dir=self.tmp_root,
        )

    def test_weekly_plan_backup_validates(self) -> None:
        facts = self._validate()
        self.assertEqual(facts["revision"], head_revision())

    def test_tampered_content_hash_is_rejected(self) -> None:
        connection = sqlite3.connect(str(self.copy))
        try:
            raw = connection.execute(
                "SELECT content_json FROM local_weekly_plan_contents "
                "WHERE weekly_plan_id = ? ORDER BY version LIMIT 1",
                (self.plan_id,),
            ).fetchone()[0]
            content = json.loads(raw)
            content["theme"] = "被篡改"
            connection.execute(
                "UPDATE local_weekly_plan_contents SET content_json = ? "
                "WHERE weekly_plan_id = ?",
                (json.dumps(content, ensure_ascii=False), self.plan_id),
            )
            connection.commit()
        finally:
            connection.close()
        with self.assertRaises(backup_validate.BackupValidationError) as raised:
            self._validate()
        self.assertEqual(raised.exception.code, "BACKUP_DB_LOGICAL_INVALID")

    def test_monday_unique_and_pointer_checks_are_real(self) -> None:
        connection = sqlite3.connect(str(self.copy))
        connection.execute("PRAGMA foreign_keys=OFF")
        try:
            row = connection.execute(
                "SELECT profile_id, class_id, term_id, week_anchor_date, "
                "week_number_snapshot, term_start_date, term_end_date, "
                "calendar_revision_id, header_json, header_hash, "
                "current_draft_id, current_draft_version "
                "FROM local_weekly_plans WHERE id = ?",
                (self.plan_id,),
            ).fetchone()
            columns = (
                "id,profile_id,class_id,term_id,week_anchor_date,"
                "week_number_snapshot,term_start_date,term_end_date,"
                "calendar_revision_id,header_json,header_hash,"
                "current_draft_id,current_draft_version,created_at,updated_at"
            )
            values = (
                "n" * 22,
                *row[:12],
                "2026-09-01 00:00:00",
                "2026-09-01 00:00:00",
            )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    f"INSERT INTO local_weekly_plans ({columns}) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (values[0], *values[1:4], "2026-09-08", *values[5:]),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    f"INSERT INTO local_weekly_plans ({columns}) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    values,
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    f"INSERT INTO local_weekly_plans ({columns}) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        "m" * 22,
                        *row[:10],
                        "x" * 32,
                        None,
                        "2026-09-01 00:00:00",
                        "2026-09-01 00:00:00",
                    ),
                )
        finally:
            connection.close()

    def test_forged_deterministic_text_with_recomputed_hash_is_rejected(self) -> None:
        from app.local import weekly_plan_content

        connection = sqlite3.connect(str(self.copy))
        try:
            row = connection.execute(
                "SELECT id, content_json FROM local_weekly_plan_contents "
                "WHERE weekly_plan_id = ? ORDER BY version LIMIT 1",
                (self.plan_id,),
            ).fetchone()
            content = json.loads(row[1])
            for item in content["deterministic"]:
                if item["source"] is not None:
                    item["source"]["morning_talk_topic"] = "伪造全文"
                    break
            connection.execute(
                "UPDATE local_weekly_plan_contents SET content_json = ?, "
                "content_hash = ? WHERE id = ?",
                (
                    json.dumps(content, ensure_ascii=False),
                    weekly_plan_content.content_hash(content),
                    row[0],
                ),
            )
            connection.commit()
        finally:
            connection.close()
        with self.assertRaises(backup_validate.BackupValidationError) as raised:
            self._validate()
        self.assertEqual(raised.exception.code, "BACKUP_DB_LOGICAL_INVALID")

    def test_historical_source_remains_valid_after_daily_content_changes(self) -> None:
        from app.local import daily_plan_service
        from app.local.models import LocalDailyPlan

        daily_id = self.session.scalars(select(LocalDailyPlan)).one().id
        current = daily_plan_service.get_plan(self.session, plan_id=daily_id)
        adopted = dict(current["content"]["adopted_content"])
        adopted["reflection"] = "后续变化"
        daily_plan_service.save(
            self.session,
            plan_id=daily_id,
            expected_content_version=current["content"]["version"],
            adopted_content=adopted,
        )
        source = sqlite3.connect(str(self.runtime.db_path))
        target = sqlite3.connect(str(self.copy))
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        facts = self._validate()
        self.assertEqual(facts["revision"], head_revision())

    def test_interrupted_export_attempt_becomes_indeterminate(self) -> None:
        from app.local import weekly_plan_operations

        snapshot = LocalWeeklyExportSnapshot(
            id="s" * 22,
            profile_id=self.profile.id,
            launch_id="launch",
            session_scope_hash="a" * 64,
            manifest_json={},
            manifest_hash="b" * 64,
            expires_at=datetime.utcnow(),
        )
        token = LocalWeeklyExportToken(
            id="t" * 22,
            snapshot_id=snapshot.id,
            profile_id=self.profile.id,
            token_hash="c" * 64,
            expires_at=datetime.utcnow(),
        )
        attempt = LocalWeeklyExportAttempt(
            id="a" * 22,
            profile_id=self.profile.id,
            snapshot_id=snapshot.id,
            token_id=token.id,
            export_id_hash="d" * 64,
            filename_fingerprint="e" * 64,
            status="in_progress",
            byte_size=0,
            started_at=datetime.utcnow(),
        )
        self.session.add_all([snapshot, token])
        self.session.flush()
        self.session.add(attempt)
        self.session.commit()
        changed = weekly_plan_operations.invalidate_in_progress(self.session)
        self.session.commit()
        self.assertEqual(changed, 1)
        self.session.expire_all()
        row = self.session.get(LocalWeeklyExportAttempt, attempt.id)
        self.assertEqual(row.status, "indeterminate")
        self.assertEqual(row.byte_size, 0)
        self.assertIsNone(row.result_hash)
        self.assertIsNotNone(row.ended_at)

    def _export_manifest(self) -> dict:
        from app.local import weekly_plan_snapshot
        from sqlalchemy import select

        confirmation = self.session.scalars(
            select(LocalWeeklyPlanConfirmation).where(
                LocalWeeklyPlanConfirmation.weekly_plan_id == self.plan_id
            )
        ).one()
        snapshot = confirmation.snapshot_json
        item = dict(snapshot)
        item.update(
            confirmation_id=confirmation.id,
            confirmation_version=confirmation.version,
            confirmation_hash=confirmation.snapshot_hash,
        )
        selection = {
            "weekly_plan_id": snapshot["weekly_plan_id"],
            "confirmation_id": confirmation.id,
            "confirmation_version": confirmation.version,
            "draft_id": snapshot["draft_id"],
            "draft_version": snapshot["draft_version"],
            "content_hash": snapshot["content_hash"],
            "confirmation_hash": confirmation.snapshot_hash,
            "week_anchor_date": snapshot["creation_context"]["week_anchor_date"],
            "week_number": snapshot["creation_context"]["week_number_snapshot"],
            "date_range": snapshot["date_range"],
        }
        missing = []
        for fact in snapshot["facts"]["missing"]:
            copied = json.loads(json.dumps(fact, ensure_ascii=False))
            copied["details"] = dict(copied.get("details") or {})
            copied["details"]["weekly_plan_id"] = snapshot["weekly_plan_id"]
            copied["details"]["confirmation_id"] = confirmation.id
            missing.append(copied)
        return {
            "schema_version": 1,
            "profile_id": snapshot["profile_id"],
            "mode": "single",
            "requested_range": None,
            "selection": [selection],
            "warnings_as_of": "2026-11-01T10:00:00+00:00",
            "missing": missing,
            "warnings": [],
            "items": [item],
        }

    def test_new_runtime_marks_in_progress_attempt_indeterminate(self) -> None:
        snapshot = LocalWeeklyExportSnapshot(
            id="q" * 22,
            profile_id=self.profile.id,
            launch_id="launch",
            session_scope_hash="a" * 64,
            manifest_json={},
            manifest_hash="b" * 64,
            expires_at=datetime.utcnow(),
        )
        token = LocalWeeklyExportToken(
            id="r" * 22,
            snapshot_id=snapshot.id,
            profile_id=self.profile.id,
            token_hash="c" * 64,
            expires_at=datetime.utcnow(),
        )
        attempt = LocalWeeklyExportAttempt(
            id="u" * 22,
            profile_id=self.profile.id,
            snapshot_id=snapshot.id,
            token_id=token.id,
            export_id_hash="d" * 64,
            filename_fingerprint="e" * 64,
            status="in_progress",
            byte_size=0,
            started_at=datetime.utcnow(),
        )
        self.session.add_all([snapshot, token])
        self.session.flush()
        self.session.add(attempt)
        self.session.commit()
        self.session.close()
        self.runtime.dispose()
        reopened = LocalRuntime(
            data_dir=self.runtime.data_dir,
            credential_root=self.runtime.credential_root,
        )
        try:
            reopened.prepare()
            session = reopened.session()
            try:
                row = session.get(LocalWeeklyExportAttempt, attempt.id)
                self.assertEqual(row.status, "indeterminate")
                self.assertEqual(row.byte_size, 0)
                self.assertIsNone(row.result_hash)
                self.assertIsNotNone(row.ended_at)
                self.assertIsNotNone(
                    session.get(LocalWeeklyExportToken, token.id).consumed_at
                )
            finally:
                session.close()
        finally:
            reopened.dispose()

    def test_export_manifest_uses_real_confirmation_projection(self) -> None:
        from app.local import weekly_plan_snapshot
        import hashlib

        manifest = self._export_manifest()
        row = LocalWeeklyExportSnapshot(
            id="x" * 22,
            profile_id=self.profile.id,
            launch_id="launch",
            session_scope_hash="a" * 64,
            manifest_json=manifest,
            manifest_hash=hashlib.sha256(
                weekly_plan_snapshot.canonical_json(manifest).encode("utf-8")
            ).hexdigest(),
            expires_at=datetime(2020, 1, 1),
        )
        self.session.add(row)
        self.session.commit()
        source = sqlite3.connect(str(self.runtime.db_path))
        target = sqlite3.connect(str(self.copy))
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        self._validate()
        bad = json.loads(json.dumps(manifest, ensure_ascii=False))
        bad["selection"][0]["confirmation_id"] = "y" * 22
        bad["items"][0]["confirmation_id"] = "y" * 22
        connection = sqlite3.connect(str(self.copy))
        try:
            connection.execute(
                "UPDATE local_weekly_export_snapshots SET manifest_json = ?, "
                "manifest_hash = ? WHERE id = ?",
                (
                    json.dumps(bad, ensure_ascii=False),
                    hashlib.sha256(
                        weekly_plan_snapshot.canonical_json(bad).encode("utf-8")
                    ).hexdigest(),
                    row.id,
                ),
            )
            connection.commit()
        finally:
            connection.close()
        with self.assertRaises(backup_validate.BackupValidationError):
            self._validate()

    def test_refreshed_basis_survives_real_snapshot_create_verify(self) -> None:
        settings = self.session.get(LocalSettings, "singleton")
        change = {
            "kind": "term_update",
            "term_id": self.term.id,
            "name": "冬季学期",
            "start_date": "2026-11-01",
            "end_date": "2026-11-30",
        }
        preview = config_service.preview(
            self.session,
            expected_config_version=settings.config_version,
            change=change,
        )
        config_service.apply(
            self.session,
            request_id=str(uuid.uuid4()),
            expected_config_version=settings.config_version,
            change=change,
            preview_token=preview["preview_token"],
        )
        self.session.expire_all()
        saved = weekly_plan_service.save_draft(
            self.session,
            profile_id=self.profile.id,
            request_id=str(uuid.uuid4()),
            plan_id=self.plan_id,
            expected_draft_version=2,
            patch={"theme": "刷新后"},
        )
        refresh = weekly_plan_service.refresh_preview(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            launch_id="backup-launch",
            session_scope_hash=scope_hash("backup-scope"),
            plan_id=self.plan_id,
            expected_draft_version=saved["draft"]["version"],
        )
        refreshed = weekly_plan_service.refresh_sources(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            launch_id="backup-launch",
            session_scope_hash=scope_hash("backup-scope"),
            request_id=str(uuid.uuid4()),
            plan_id=self.plan_id,
            expected_draft_version=saved["draft"]["version"],
            preview_token=refresh["preview_token"],
        )
        target = weekly_plan_service.confirmation_preview(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            launch_id="backup-launch",
            session_scope_hash=scope_hash("backup-scope"),
            plan_id=self.plan_id,
            expected_draft_version=refreshed["draft"]["version"],
        )
        weekly_plan_service.confirm(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            launch_id="backup-launch",
            session_scope_hash=scope_hash("backup-scope"),
            request_id=str(uuid.uuid4()),
            plan_id=self.plan_id,
            expected_draft_version=refreshed["draft"]["version"],
            context_token=target["preview_token"],
            ack_missing=True,
            ack_stale=True,
            note=None,
        )
        package = self.tmp_root / "refreshed.kgmbackup"
        service = backup_snapshot.SnapshotService(
            self.runtime,
            app_version="r03-test",
            source_identity={"app_version": "r03-test"},
        )
        service.create(
            package, password=None, cancel=threading.Event()
        )
        verified = service.verify(
            package, password=None, cancel=threading.Event()
        )
        self.assertEqual(verified.source_revision, head_revision())
        self.assertEqual(verified.target_revision, head_revision())

    def test_snapshot_service_accepts_default_and_fixed_weekly_manager(self) -> None:
        default = backup_snapshot.SnapshotService(
            self.runtime,
            app_version="r03-test",
            source_identity={"app_version": "r03-test"},
        )
        self.assertIsNone(default.weekly_export_manager)
        marker = object()
        fixed = backup_snapshot.SnapshotService(
            self.runtime,
            app_version="r03-test",
            source_identity={"app_version": "r03-test"},
            weekly_export_manager=marker,
        )
        self.assertIs(fixed.weekly_export_manager, marker)

    def test_tampered_confirmation_snapshot_is_rejected(self) -> None:
        connection = sqlite3.connect(str(self.copy))
        try:
            raw = connection.execute(
                "SELECT snapshot_json FROM local_weekly_plan_confirmations "
                "WHERE weekly_plan_id = ?",
                (self.plan_id,),
            ).fetchone()[0]
            snapshot = json.loads(raw)
            snapshot["content"]["theme"] = "被篡改"
            connection.execute(
                "UPDATE local_weekly_plan_confirmations SET snapshot_json = ? "
                "WHERE weekly_plan_id = ?",
                (json.dumps(snapshot, ensure_ascii=False), self.plan_id),
            )
            connection.commit()
        finally:
            connection.close()
        with self.assertRaises(backup_validate.BackupValidationError) as raised:
            self._validate()
        self.assertEqual(raised.exception.code, "BACKUP_DB_LOGICAL_INVALID")
