"""Independent weekly-plan integrity regressions (no implementation edits).

These tests exercise real Alembic SQLite, real service relationships and
pure token/schema contracts.  They are intentionally independent from the
A-owned weekly tests; expected contract failures are allowed to fail until A
fixes the implementation.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import threading
import time
import unittest
import uuid
import warnings
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from pydantic import ValidationError
from sqlalchemy import select

from app.local import (
    backup_validate,
    config_service,
    daily_plan_service,
    profile_service,
    weekly_plan_content,
    weekly_plan_service,
    weekly_plan_sources,
    weekly_plan_tokens,
)
from app.local.errors import LocalWeeklyOperationConflict
from app.local.models import (
    LocalClass,
    LocalDailyPlan,
    LocalProfile,
    LocalSettings,
    LocalTerm,
    LocalWeeklyPlan,
)
from app.local.normalize import normalize_initialization
from app.local.schemas import (
    WeeklyConfirmIn,
    WeeklyCreateIn,
    WeeklyCreatePreviewIn,
)
from app.local.weekly_plan_tokens import scope_hash
from app.services import calendar_service as cal
from tests.local.support import (
    LocalTestCase,
    execute_sql,
    query_rows,
    query_scalar,
    sqlite_connect,
)

ANCHOR = date(2026, 9, 7)


@contextmanager
def _db(path: Path):
    connection = sqlite_connect(path)
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def _adopted(topic: str = "晨谈主题", theme: str = "集体活动") -> dict:
    return {
        "morning_talk": {"topic": topic},
        "group_activity": {"theme": theme},
        "morning_games": [
            {
                "group_kind": "collective",
                "games": [{"name": "切西瓜"}],
                "shared_objectives": "共同目标",
                "guidance_points": "指导要点",
                "focus_guidance": "重点指导",
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


EVIDENCE_ROOT_ENV = "KGM_WEEKLY_INTEGRITY_EVIDENCE_ROOT"


class _WeeklyBase(LocalTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.addCleanup(self._retain_runtime_db)
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
                start_date="2026-09-01",
                end_date="2026-10-30",
                school_name="测试幼儿园",
            ),
        )
        self.session.expire_all()
        self.profile = self.session.scalars(select(LocalProfile)).one()
        self.term = self.session.scalars(select(LocalTerm)).one()
        self.settings = self.session.get(LocalSettings, "singleton")
        self.launch = "integrity-launch"
        self.scope = scope_hash("integrity-scope")

    def _daily(self, plan_date: date = ANCHOR) -> str:
        plan, created = daily_plan_service.create_or_open(
            self.session,
            plan_date=plan_date,
            raw_lesson_plan=None,
            adopted_content=_adopted(),
        )
        self.assertTrue(created)
        return plan["id"]

    def _plan(self, *, with_daily: bool = False) -> tuple[str, dict]:
        if with_daily:
            self._daily()
        preview = weekly_plan_service.create_preview(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            launch_id=self.launch,
            session_scope_hash=self.scope,
            term_id=self.term.id,
            week_anchor_date=ANCHOR,
        )
        result, created = weekly_plan_service.create_or_open(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            launch_id=self.launch,
            session_scope_hash=self.scope,
            request_id=str(uuid.uuid4()),
            term_id=self.term.id,
            week_anchor_date=ANCHOR,
            expected_config_version=self.settings.config_version,
            context_token=preview["create_token"],
        )
        self.assertTrue(created)
        return result["weekly_plan_id"], result

    def _save(self, plan_id: str, version: int, patch: dict, request_id: str | None = None) -> dict:
        return weekly_plan_service.save_draft(
            self.session,
            profile_id=self.profile.id,
            request_id=request_id or str(uuid.uuid4()),
            plan_id=plan_id,
            expected_draft_version=version,
            patch=patch,
        )

    def _retain_runtime_db(self) -> None:
        runtime = getattr(self, "runtime", None)
        if runtime is None:
            if os.environ.get(EVIDENCE_ROOT_ENV):
                self._note_retention_failure(
                    None, f"{type(self).__name__}.{self._testMethodName}: runtime was not created"
                )
            return
        self._retain_db(Path(runtime.db_path), "runtime")

    def _retain_db(self, source_path: Path, label: str) -> None:
        """Copy a test DB to an opt-in evidence root, never overwriting.

        Without ``KGM_WEEKLY_INTEGRITY_EVIDENCE_ROOT`` no extra file is kept;
        the DB remains in the existing isolated LocalTestCase temp root.
        """
        raw_root = os.environ.get(EVIDENCE_ROOT_ENV)
        if not raw_root:
            return
        root: Path | None = None
        try:
            candidate = Path(raw_root).expanduser()
            if not candidate.is_absolute():
                raise ValueError("evidence root must be an absolute path")
            root = candidate.resolve()
            if root == Path(root.anchor):
                raise ValueError("evidence root must not be a filesystem root")
            root.mkdir(parents=True, exist_ok=True)
            if not root.is_dir():
                raise ValueError("evidence root is not a directory")
            source_path = source_path.resolve()
            if not source_path.is_file():
                raise FileNotFoundError(f"source DB not found: {source_path}")
            safe_name = re.sub(
                r"[^A-Za-z0-9_.-]+",
                "_",
                f"{type(self).__name__}.{self._testMethodName}.{label}",
            )
            target_path: Path | None = None
            for _ in range(8):
                stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
                candidate = root / f"{safe_name}.{stamp}.{uuid.uuid4().hex[:12]}.db"
                if candidate.parent.resolve() != root:
                    raise ValueError("evidence target escaped the evidence root")
                try:
                    fd = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                except FileExistsError:
                    continue
                else:
                    os.close(fd)
                    target_path = candidate
                    break
            if target_path is None:
                raise RuntimeError("could not reserve a unique evidence filename")
            try:
                source = sqlite3.connect(str(source_path))
                target = sqlite3.connect(str(target_path))
                try:
                    source.backup(target)
                finally:
                    target.close()
                    source.close()
            except BaseException:
                try:
                    target_path.unlink()
                except OSError as cleanup_error:
                    self._note_retention_failure(
                        root,
                        f"{target_path.name}: backup failed and the reserved "
                        f"file could not be removed: {cleanup_error}",
                    )
                raise
            if target_path.resolve().parent != root:
                raise ValueError("retained file escaped the evidence root")
        except Exception as exc:  # noqa: BLE001 - evidence infrastructure
            self._note_retention_failure(
                root,
                f"{type(self).__name__}.{self._testMethodName} [{label}]: {exc}",
            )

    @staticmethod
    def _note_retention_failure(root: Path | None, message: str) -> None:
        line = (
            f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {message}\n"
        )
        warnings.warn(
            f"weekly integrity evidence retention failed: {message}",
            RuntimeWarning,
            stacklevel=2,
        )
        print(f"WEEKLY_INTEGRITY_RETENTION_FAILURE {line}", end="", file=sys.__stderr__)
        if sys.stderr is not sys.__stderr__:
            print(
                f"WEEKLY_INTEGRITY_RETENTION_FAILURE {line}",
                end="",
                file=sys.stderr,
            )
        if root is None:
            return
        try:
            with (root / "retention-failures.log").open(
                "a", encoding="utf-8"
            ) as handle:
                handle.write(line)
        except OSError as exc:
            print(
                "WEEKLY_INTEGRITY_RETENTION_FAILURE "
                f"failure-log write also failed: {exc}",
                file=sys.__stderr__,
            )

    def _copy_db(self, name: str) -> Path:
        path = self.tmp_root / name
        source = sqlite3.connect(str(self.runtime.db_path))
        target = sqlite3.connect(str(path))
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        return path


class RawSchemaConstraintTests(_WeeklyBase):
    def test_raw_ui_theme_invalid_value_is_rejected_by_real_check(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            execute_sql(
                self.runtime.db_path,
                "UPDATE local_settings SET ui_theme = 'sepia'",
            )

    def test_raw_ui_theme_version_zero_is_rejected_by_real_check(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            execute_sql(
                self.runtime.db_path,
                "UPDATE local_settings SET ui_theme_version = 0",
            )

    def test_raw_caregiver_81_chars_is_rejected_by_real_check(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            execute_sql(
                self.runtime.db_path,
                "UPDATE local_classes SET caregiver_name = ? "
                "WHERE id = ?",
                ("保" * 81, self.session.scalars(select(LocalClass)).one().id),
            )


class ExportSqlConstraintTests(_WeeklyBase):
    def _add_export_pair(self, suffix: str) -> tuple[str, str, str]:
        profile_id = self.profile.id
        snap_a = f"snapA-{suffix}"
        snap_b = f"snapB-{suffix}"
        token_b = f"tokenB-{suffix}"
        hash_a = ("a" + suffix).ljust(64, "a")[:64]
        hash_b = ("b" + suffix).ljust(64, "b")[:64]
        token_hash_b = ("c" + suffix).ljust(64, "c")[:64]
        now = "2026-11-01T00:00:00"
        later = "2026-11-02T00:00:00"
        with _db(self.runtime.db_path) as connection:
            for snap, digest in ((snap_a, hash_a), (snap_b, hash_b)):
                connection.execute(
                    "INSERT INTO local_weekly_export_snapshots "
                    "(id, profile_id, launch_id, session_scope_hash, manifest_json, "
                    " manifest_hash, created_at, expires_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (snap, profile_id, "launch-1", "d" * 64, "{}", digest, now, later),
                )
            connection.execute(
                "INSERT INTO local_weekly_export_tokens "
                "(id, snapshot_id, profile_id, token_hash, expires_at, consumed_at, "
                " parent_attempt_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, NULL, NULL, ?)",
                (token_b, snap_b, profile_id, token_hash_b, later, now),
            )
            connection.commit()
        return snap_a, snap_b, token_b

    def _insert_operation(self, *, request_id: str, snapshot: str, token: str, scope: str | None) -> None:
        with _db(self.runtime.db_path) as connection:
            connection.execute(
                "INSERT INTO local_weekly_plan_operations "
                "(id, profile_id, request_id, weekly_plan_id, action, input_fingerprint, "
                " result_draft_id, result_draft_version, result_confirmed_id, "
                " result_confirmed_version, result_snapshot_id, result_token_id, "
                " launch_id, session_scope_hash, result_json, created_at) "
                "VALUES (?, ?, ?, NULL, 'export_create', ?, NULL, NULL, NULL, NULL, "
                "        ?, ?, 'launch-1', ?, '{}', ?)",
                (
                    "op-" + request_id[-20:],
                    self.profile.id,
                    request_id,
                    "e" * 64,
                    snapshot,
                    token,
                    scope,
                    "2026-11-01T00:00:00",
                ),
            )
            connection.commit()

    def test_export_operation_snapshot_token_cross_owner_is_rejected(self) -> None:
        snap_a, _snap_b, token_b = self._add_export_pair("x1")
        with self.assertRaises(sqlite3.IntegrityError):
            self._insert_operation(
                request_id=str(uuid.uuid4()),
                snapshot=snap_a,
                token=token_b,
                scope="d" * 64,
            )

    def test_export_operation_null_scope_cannot_bypass_shape_check(self) -> None:
        snap_a, _snap_b, token_b = self._add_export_pair("x2")
        # Use a token belonging to the same snapshot for the scope-only negative.
        with _db(self.runtime.db_path) as connection:
            connection.execute(
                "INSERT INTO local_weekly_export_tokens "
                "(id, snapshot_id, profile_id, token_hash, expires_at, consumed_at, "
                " parent_attempt_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, NULL, NULL, ?)",
                ("tokenA-x2", snap_a, self.profile.id, "f" * 64, "2026-11-02T00:00:00", "2026-11-01T00:00:00"),
            )
            connection.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            self._insert_operation(
                request_id=str(uuid.uuid4()),
                snapshot=snap_a,
                token="tokenA-x2",
                scope=None,
            )

    def _insert_attempt(self, *, attempt_id: str, snapshot: str, token: str, byte_size: int | None, status: str) -> None:
        with _db(self.runtime.db_path) as connection:
            connection.execute(
                "INSERT INTO local_weekly_export_attempts "
                "(id, profile_id, snapshot_id, token_id, export_id_hash, "
                " filename_fingerprint, status, result_hash, byte_size, "
                " started_at, ended_at, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, NULL, ?)",
                (
                    attempt_id,
                    self.profile.id,
                    snapshot,
                    token,
                    ("1" + attempt_id).ljust(64, "1")[:64],
                    "2" * 64,
                    status,
                    byte_size,
                    "2026-11-01T00:00:00",
                    "2026-11-01T00:00:00",
                ),
            )
            connection.commit()

    def test_attempt_null_byte_size_is_rejected(self) -> None:
        snap_a, _snap_b, _token_b = self._add_export_pair("x3")
        with _db(self.runtime.db_path) as connection:
            connection.execute(
                "INSERT INTO local_weekly_export_tokens "
                "(id, snapshot_id, profile_id, token_hash, expires_at, consumed_at, "
                " parent_attempt_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, NULL, NULL, ?)",
                ("tokenA-x3", snap_a, self.profile.id, "3" * 64, "2026-11-02T00:00:00", "2026-11-01T00:00:00"),
            )
            connection.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            self._insert_attempt(
                attempt_id="attempt-null",
                snapshot=snap_a,
                token="tokenA-x3",
                byte_size=None,
                status="in_progress",
            )

    def test_attempt_zero_byte_size_non_saved_is_valid(self) -> None:
        snap_a, _snap_b, _token_b = self._add_export_pair("x4")
        with _db(self.runtime.db_path) as connection:
            connection.execute(
                "INSERT INTO local_weekly_export_tokens "
                "(id, snapshot_id, profile_id, token_hash, expires_at, consumed_at, "
                " parent_attempt_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, NULL, NULL, ?)",
                ("tokenA-x4", snap_a, self.profile.id, "4" * 64, "2026-11-02T00:00:00", "2026-11-01T00:00:00"),
            )
            connection.commit()
        self._insert_attempt(
            attempt_id="attempt-zero",
            snapshot=snap_a,
            token="tokenA-x4",
            byte_size=0,
            status="failed",
        )
        assert query_scalar(
            self.runtime.db_path,
            "SELECT byte_size FROM local_weekly_export_attempts WHERE id='attempt-zero'",
        ) == 0


class SourceTermFilterTests(_WeeklyBase):
    def _apply_change(self, expected_version: int, change: dict) -> dict:
        preview = config_service.preview(
            self.session,
            expected_config_version=expected_version,
            change=change,
        )
        result = config_service.apply(
            self.session,
            request_id=str(uuid.uuid4()),
            expected_config_version=expected_version,
            change=change,
            preview_token=preview["preview_token"],
        )
        self.session.expire_all()
        return result

    def test_saved_daily_from_old_term_is_not_a_source_for_new_term(self) -> None:
        profile_id = self.profile.id
        old_term_id = self.term.id
        self.session.expire_all()
        school_class = self.session.scalars(select(LocalClass)).one()
        class_id = school_class.id
        daily_id = self._daily(date(2026, 9, 8))

        version = self.session.get(LocalSettings, "singleton").config_version
        moved = self._apply_change(
            version,
            {
                "kind": "term_update",
                "term_id": old_term_id,
                "name": "秋季学期",
                "start_date": "2026-11-01",
                "end_date": "2026-11-30",
            },
        )
        self.assertTrue(moved["calendar_revision_id"])

        version = self.session.get(LocalSettings, "singleton").config_version
        created = self._apply_change(
            version,
            {
                "kind": "term_create",
                "name": "新秋季学期",
                "start_date": "2026-09-01",
                "end_date": "2026-10-30",
            },
        )
        new_revision_id = created["calendar_revision_id"]
        self.assertTrue(new_revision_id)

        self.session.expire_all()
        old_term = self.session.get(LocalTerm, old_term_id)
        self.assertEqual(old_term.start_date, date(2026, 11, 1))
        self.assertEqual(old_term.end_date, date(2026, 11, 30))
        new_terms = [
            term
            for term in self.session.scalars(select(LocalTerm)).all()
            if term.id != old_term_id
            and term.start_date == date(2026, 9, 1)
            and term.end_date == date(2026, 10, 30)
        ]
        self.assertEqual(len(new_terms), 1, "expected exactly one new B term")
        new_term = new_terms[0]
        self.assertEqual(new_term.current_calendar_revision_id, new_revision_id)

        old_row = query_rows(
            self.runtime.db_path,
            "SELECT term_id, plan_date, current_content_version "
            "FROM local_daily_plans WHERE id=?",
            (daily_id,),
        )[0]
        self.assertEqual(old_row["term_id"], old_term_id)
        self.assertEqual(old_row["plan_date"], "2026-09-08")
        self.assertEqual(old_row["current_content_version"], 1)

        settings = self.session.get(LocalSettings, "singleton")
        school_class = self.session.get(LocalClass, class_id)
        week_number, week_start, _weekday = cal.week_info(
            new_term.start_date, ANCHOR
        )
        self.assertEqual((week_number, week_start), (2, ANCHOR))
        snapshot = weekly_plan_sources.load_source_snapshot(
            self.session,
            profile_id=profile_id,
            class_id=class_id,
            term_id=new_term.id,
            week_anchor_date=ANCHOR,
            calendar_revision_id=new_term.current_calendar_revision_id,
            term_start=new_term.start_date,
            term_end=new_term.end_date,
            week_number=week_number,
            header=weekly_plan_sources.header_from_class(
                settings.school_name, school_class
            ),
            config_version=settings.config_version,
            include_sources=True,
        )
        self.assertEqual(snapshot["term_id"], new_term.id)
        self.assertEqual(snapshot["week_anchor_date"], "2026-09-07")
        self.assertEqual(snapshot["week_number"], 2)
        day = next(
            item for item in snapshot["days"] if item["date"] == "2026-09-08"
        )
        self.assertEqual(day["source_state"], "no_plan", day)
        self.assertIsNone(day["source"], day)


class TokenConcurrencyTests(unittest.TestCase):
    def test_two_first_issue_tokens_both_verify_with_a_synchronized_key(self) -> None:
        runtime = SimpleNamespace()
        started = threading.Event()
        second_started = threading.Event()
        second_issued = threading.Event()
        release = threading.Event()
        real_token_bytes = weekly_plan_tokens.secrets.token_bytes
        calls = 0
        calls_lock = threading.Lock()
        tokens: list[str] = []
        errors: list[BaseException] = []

        def slow_token_bytes(size: int) -> bytes:
            nonlocal calls
            with calls_lock:
                index = calls
                calls += 1
            if index == 0:
                started.set()
                release.wait(5)
            elif index == 1:
                second_started.set()
            return real_token_bytes(size)

        kwargs = dict(
            purpose="confirm",
            profile_id="profile-1",
            launch_id="launch-1",
            session_scope_hash="scope-1",
            object_id="object-1",
            expected_version=1,
            source_context_hash="a" * 64,
            facts_hash="b" * 64,
            target_hash="c" * 64,
        )

        def issue(index: int) -> None:
            try:
                tokens.append(weekly_plan_tokens.issue_token(runtime, **kwargs))
                if index == 1:
                    second_issued.set()
            except BaseException as exc:  # noqa: BLE001 - test evidence
                errors.append(exc)

        with mock.patch.object(
            weekly_plan_tokens.secrets, "token_bytes", side_effect=slow_token_bytes
        ), mock.patch.object(
            weekly_plan_tokens.secrets, "token_hex", return_value="0" * 16
        ):
            first = threading.Thread(target=issue, args=(0,))
            first.start()
            self.assertTrue(started.wait(2), "first key generation did not start")
            second = threading.Thread(target=issue, args=(1,))
            second.start()
            second_started.wait(0.2)
            second_issued.wait(0.2)
            release.set()
            first.join(5)
            second.join(5)
        self.assertEqual(errors, [])
        self.assertEqual(len(tokens), 2)
        for token in tokens:
            weekly_plan_tokens.verify_token(runtime, token, purpose="confirm",
                                            profile_id="profile-1", launch_id="launch-1",
                                            session_scope_hash="scope-1", object_id="object-1",
                                            expected_version=1, source_context_hash="a" * 64,
                                            facts_hash="b" * 64, target_hash="c" * 64)


class RequestSchemaStrictnessTests(unittest.TestCase):
    def test_valid_iso_date_and_explicit_bool_are_accepted(self) -> None:
        """Positive control: only non-ISO dates / implicit bools are refused."""
        term_id = "term_0123456789abcdef"
        preview = WeeklyCreatePreviewIn(
            term_id=term_id, week_anchor_date="2026-09-07"
        )
        self.assertEqual(preview.week_anchor_date, date(2026, 9, 7))
        create = WeeklyCreateIn(
            request_id=str(uuid.uuid4()),
            term_id=term_id,
            week_anchor_date="2026-09-07",
            expected_config_version=1,
            context_token="token",
        )
        self.assertEqual(create.week_anchor_date, date(2026, 9, 7))
        confirm = WeeklyConfirmIn(
            request_id=str(uuid.uuid4()),
            expected_draft_version=1,
            context_token="token",
            ack_missing=True,
            ack_stale=False,
        )
        self.assertIs(confirm.ack_missing, True)
        self.assertIs(confirm.ack_stale, False)

    def test_date_fields_reject_unix_number_and_datetime_string(self) -> None:
        term_id = "term_0123456789abcdef"
        with self.assertRaises(ValidationError):
            WeeklyCreatePreviewIn(term_id=term_id, week_anchor_date=1735689600)
        with self.assertRaises(ValidationError):
            WeeklyCreateIn(
                request_id=str(uuid.uuid4()),
                term_id=term_id,
                week_anchor_date="2026-09-07T00:00:00",
                expected_config_version=1,
                context_token="token",
            )

    def test_ack_fields_reject_implicit_bool_values(self) -> None:
        for value in ("yes", 1):
            with self.subTest(ack=value):
                with self.assertRaises(ValidationError):
                    WeeklyConfirmIn(
                        request_id=str(uuid.uuid4()),
                        expected_draft_version=1,
                        context_token="token",
                        ack_missing=value,
                        ack_stale=False,
                    )


class LiveCalendarComparisonTests(_WeeklyBase):
    def test_confirmation_preview_returns_target_content_and_facts(self) -> None:
        plan_id, _created = self._plan(with_daily=False)
        detail = weekly_plan_service.get_detail(
            self.session, profile_id=self.profile.id, plan_id=plan_id
        )
        confirm = weekly_plan_service.confirmation_preview(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            launch_id=self.launch,
            session_scope_hash=self.scope,
            plan_id=plan_id,
            expected_draft_version=detail["draft"]["version"],
        )
        self.assertIn("target", confirm, confirm)
        target = confirm["target"]
        self.assertIn("content", target, target)
        self.assertIn("facts", target, target)
        self.assertEqual(
            target["content"]["calendar_basis"]["term_end"], "2026-10-30"
        )
        self.assertEqual(
            target["content"]["calendar_basis"]["week_anchor_date"],
            ANCHOR.isoformat(),
        )

    def test_get_confirm_refresh_compare_live_term_boundary_without_mutating_target(self) -> None:
        plan_id, created = self._plan(with_daily=False)
        detail = weekly_plan_service.get_detail(
            self.session, profile_id=self.profile.id, plan_id=plan_id
        )
        self.assertEqual(detail["draft"]["content"]["calendar_basis"]["term_end"], "2026-10-30")
        self.term.end_date = date(2026, 9, 9)
        self.session.commit()
        self.session.expire_all()

        detail = weekly_plan_service.get_detail(
            self.session, profile_id=self.profile.id, plan_id=plan_id
        )
        warning_codes = [item.get("code") for item in detail["facts"].get("warnings", [])]
        self.assertIn("calendar_basis_changed", warning_codes, detail["facts"])
        self.assertEqual(detail["draft"]["content"]["calendar_basis"]["term_end"], "2026-10-30")

        confirm = weekly_plan_service.confirmation_preview(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            launch_id=self.launch,
            session_scope_hash=self.scope,
            plan_id=plan_id,
            expected_draft_version=detail["draft"]["version"],
        )
        self.assertIn("target", confirm, confirm)
        target = confirm["target"]
        self.assertIn("content", target, target)
        self.assertIn("facts", target, target)
        self.assertEqual(
            target["content"]["calendar_basis"]["term_end"], "2026-10-30"
        )
        self.assertIn(
            "calendar_basis_changed",
            [item.get("code") for item in target["facts"].get("warnings", [])],
        )

        refresh = weekly_plan_service.refresh_preview(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            launch_id=self.launch,
            session_scope_hash=self.scope,
            plan_id=plan_id,
            expected_draft_version=detail["draft"]["version"],
        )
        paths = {item.get("field_path") for item in refresh.get("differences", [])}
        self.assertIn("calendar_basis.term_end", paths, refresh.get("differences"))
        self.assertEqual(refresh["content"]["calendar_basis"]["term_end"], "2026-09-09")


class OperationReceiptTests(_WeeklyBase):
    def test_first_create_response_has_ids_and_matches_replay_except_replayed(self) -> None:
        preview = weekly_plan_service.create_preview(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            launch_id=self.launch,
            session_scope_hash=self.scope,
            term_id=self.term.id,
            week_anchor_date=ANCHOR,
        )
        request_id = str(uuid.uuid4())
        first, created = weekly_plan_service.create_or_open(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            launch_id=self.launch,
            session_scope_hash=self.scope,
            request_id=request_id,
            term_id=self.term.id,
            week_anchor_date=ANCHOR,
            expected_config_version=self.settings.config_version,
            context_token=preview["create_token"],
        )
        self.assertTrue(created)
        self.assertTrue(first.get("operation_id"), first)
        self.assertEqual(first.get("request_id"), request_id)
        self.assertFalse(first.get("replayed"))

        replay, created_again = weekly_plan_service.create_or_open(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            launch_id=self.launch,
            session_scope_hash=self.scope,
            request_id=request_id,
            term_id=self.term.id,
            week_anchor_date=ANCHOR,
            expected_config_version=self.settings.config_version,
            context_token=preview["create_token"],
        )
        self.assertFalse(created_again)
        self.assertTrue(replay.get("replayed"))
        first_payload = dict(first)
        replay_payload = dict(replay)
        first_payload.pop("replayed", None)
        replay_payload.pop("replayed", None)
        self.assertEqual(replay_payload, first_payload)

    def test_old_save_receipt_replays_old_draft_after_cold_reopen_and_is_minimal(self) -> None:
        plan_id, _created = self._plan(with_daily=False)
        request_v1 = str(uuid.uuid4())
        first = self._save(plan_id, 1, {"theme": "v1"}, request_v1)
        old_draft_id = first["draft"]["id"]
        old_version = first["draft"]["version"]
        second = self._save(plan_id, old_version, {"theme": "v2"})
        self.assertNotEqual(second["draft"]["id"], old_draft_id)
        profile_id = self.profile.id
        self.session.close()
        self.runtime.dispose()
        reopened = self.make_runtime()
        session = reopened.session()
        try:
            replay = weekly_plan_service.get_operation(
                session, profile_id=profile_id, request_id=request_v1
            )
            self.assertEqual(replay["schema_version"], 1)
            self.assertEqual(replay["weekly_plan_id"], plan_id)
            self.assertEqual(replay["draft_id"], old_draft_id)
            self.assertEqual(replay["draft_version"], old_version)
            self.assertIsNone(replay["confirmation_id"])
            self.assertIsNone(replay["confirmation_version"])
            self.assertIsNone(replay["snapshot_id"])
            self.assertIsNone(replay["token_id"])
            row = query_rows(
                reopened.db_path,
                "SELECT id, version, content_hash FROM local_weekly_plan_contents WHERE id=?",
                (old_draft_id,),
            )[0]
            self.assertEqual(row["version"], old_version)
        finally:
            session.close()
        operation = query_rows(
            self.runtime.db_path,
            "SELECT weekly_plan_id, result_draft_id, result_draft_version, "
            "result_confirmed_id, result_confirmed_version, "
            "result_snapshot_id, result_token_id, result_json "
            "FROM local_weekly_plan_operations WHERE request_id=?",
            (request_v1,),
        )[0]
        payload = json.loads(operation["result_json"])
        self.assertEqual(
            set(payload),
            {
                "schema_version",
                "weekly_plan_id",
                "draft_id",
                "draft_version",
                "confirmation_id",
                "confirmation_version",
                "snapshot_id",
                "token_id",
            },
            payload,
        )
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["weekly_plan_id"], operation["weekly_plan_id"])
        self.assertEqual(payload["draft_id"], operation["result_draft_id"])
        self.assertEqual(payload["draft_version"], operation["result_draft_version"])
        self.assertEqual(
            payload["confirmation_id"], operation["result_confirmed_id"]
        )
        self.assertEqual(
            payload["confirmation_version"],
            operation["result_confirmed_version"],
        )
        self.assertEqual(payload["snapshot_id"], operation["result_snapshot_id"])
        self.assertEqual(payload["token_id"], operation["result_token_id"])
        self.assertEqual(payload["draft_id"], old_draft_id)
        self.assertEqual(payload["draft_version"], old_version)
        self.assertIsNone(payload["confirmation_id"])
        self.assertIsNone(payload["confirmation_version"])
        self.assertIsNone(payload["snapshot_id"])
        self.assertIsNone(payload["token_id"])
        for forbidden in (
            "operation_id",
            "request_id",
            "content",
            "content_json",
            "draft",
            "confirmation",
            "status",
        ):
            self.assertNotIn(forbidden, payload)
        self.assertNotIn("content", operation["result_json"])

    def test_different_create_context_token_with_same_request_conflicts(self) -> None:
        preview1 = weekly_plan_service.create_preview(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            launch_id=self.launch,
            session_scope_hash=self.scope,
            term_id=self.term.id,
            week_anchor_date=ANCHOR,
        )
        preview2 = weekly_plan_service.create_preview(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            launch_id=self.launch,
            session_scope_hash=self.scope,
            term_id=self.term.id,
            week_anchor_date=ANCHOR,
        )
        request_id = str(uuid.uuid4())
        first, _ = weekly_plan_service.create_or_open(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            launch_id=self.launch,
            session_scope_hash=self.scope,
            request_id=request_id,
            term_id=self.term.id,
            week_anchor_date=ANCHOR,
            expected_config_version=self.settings.config_version,
            context_token=preview1["create_token"],
        )
        self.assertTrue(first["weekly_plan_id"])
        with self.assertRaises(LocalWeeklyOperationConflict):
            weekly_plan_service.create_or_open(
                self.session,
                runtime=self.runtime,
                profile_id=self.profile.id,
                launch_id=self.launch,
                session_scope_hash=self.scope,
                request_id=request_id,
                term_id=self.term.id,
                week_anchor_date=ANCHOR,
                expected_config_version=self.settings.config_version,
                context_token=preview2["create_token"],
            )


class HistoricalBackupTests(_WeeklyBase):
    def _prepare(self) -> tuple[Path, str]:
        plan_id, _created = self._plan(with_daily=True)
        self._save(plan_id, 1, {"theme": "old"})
        self._save(plan_id, 2, {"theme": "current"})
        return self._copy_db("integrity-copy.db"), plan_id

    def _assert_baseline_valid(self, copy_path: Path) -> None:
        result = backup_validate.validate_database(
            copy_path,
            migrate_old=False,
            require_current=True,
            scratch_dir=self.tmp_root,
        )
        self.assertEqual(result["source_revision"], result["head_revision"])

    def _sync_copies(
        self,
        connection: sqlite3.Connection,
        *,
        draft_id: str,
        draft_version: int,
        content: dict,
        digest: str,
        confirmations: list[dict],
    ) -> None:
        for row in connection.execute(
            "SELECT id, result_draft_id, result_draft_version, result_json "
            "FROM local_weekly_plan_operations"
        ).fetchall():
            if row["result_draft_id"] == draft_id:
                self.assertEqual(row["result_draft_version"], draft_version)
            result = json.loads(row["result_json"])
            if row["result_draft_id"] == draft_id:
                self.assertEqual(row["result_draft_version"], draft_version)
                if "draft_id" in result:
                    self.assertEqual(result["draft_id"], draft_id)
                if "draft_version" in result:
                    self.assertEqual(result["draft_version"], draft_version)
            draft = result.get("draft")
            if isinstance(draft, dict) and draft.get("id") == draft_id:
                self.assertEqual(draft.get("version"), draft_version)
                if "content" in draft:
                    draft["content"] = content
                if "content_hash" in draft:
                    draft["content_hash"] = digest
                connection.execute(
                    "UPDATE local_weekly_plan_operations SET result_json=? "
                    "WHERE id=?",
                    (json.dumps(result, ensure_ascii=False), row["id"]),
                )
        for row in confirmations:
            self.assertEqual(row["draft_version"], draft_version)
            snapshot = json.loads(row["snapshot_json"])
            self.assertEqual(snapshot.get("content_hash"), row["old_hash"])
            snapshot["content"] = content
            snapshot["content_hash"] = digest
            connection.execute(
                "UPDATE local_weekly_plan_confirmations "
                "SET snapshot_json=?, snapshot_hash=? WHERE id=?",
                (
                    json.dumps(snapshot, ensure_ascii=False),
                    weekly_plan_sources.hash_json(snapshot),
                    row["id"],
                ),
            )

    def _mutate_old(self, copy_path: Path, *, source_change: bool) -> None:
        connection = sqlite3.connect(str(copy_path))
        connection.row_factory = sqlite3.Row
        try:
            plan = connection.execute(
                "SELECT id, current_draft_id, current_draft_version "
                "FROM local_weekly_plans"
            ).fetchone()
            self.assertIsNotNone(plan)
            old = connection.execute(
                "SELECT id, version, content_json FROM local_weekly_plan_contents "
                "WHERE weekly_plan_id=? AND version=2",
                (plan["id"],),
            ).fetchone()
            self.assertIsNotNone(old)
            self.assertNotEqual(old["id"], plan["current_draft_id"])
            self.assertNotEqual(old["version"], plan["current_draft_version"])
            content = json.loads(old["content_json"])
            daily_before = [
                tuple(row)
                for row in connection.execute(
                    "SELECT id, adopted_content FROM local_daily_plan_contents "
                    "ORDER BY id"
                ).fetchall()
            ]
            confirmations = connection.execute(
                "SELECT id, draft_version, snapshot_json, snapshot_hash "
                "FROM local_weekly_plan_confirmations WHERE draft_id=?",
                (old["id"],),
            ).fetchall()
            confirmations = [
                dict(row, old_hash=json.loads(row["snapshot_json"]).get("content_hash"))
                for row in confirmations
            ]

            if source_change:
                plan_model = self.session.get(LocalWeeklyPlan, plan["id"])
                self.assertIsNotNone(plan_model)
                settings = self.session.get(LocalSettings, "singleton")
                school_class = self.session.get(LocalClass, plan_model.class_id)
                snapshot = weekly_plan_sources.load_source_snapshot(
                    self.session,
                    profile_id=plan_model.profile_id,
                    class_id=plan_model.class_id,
                    term_id=plan_model.term_id,
                    week_anchor_date=plan_model.week_anchor_date,
                    calendar_revision_id=plan_model.calendar_revision_id,
                    term_start=plan_model.term_start_date,
                    term_end=plan_model.term_end_date,
                    week_number=plan_model.week_number_snapshot,
                    header=weekly_plan_sources.header_from_class(
                        settings.school_name, school_class
                    ),
                    config_version=settings.config_version,
                    include_sources=True,
                )
                self.assertEqual(
                    snapshot["source_context_hash"],
                    content["source_manifest"]["source_context_hash"],
                )
                forged = "伪造来源与生效同值"
                snapshot_day = next(
                    item
                    for item in snapshot["days"]
                    if item["date"] == "2026-09-07"
                )
                self.assertIsNotNone(snapshot_day["source"])
                snapshot_day["source"]["morning_talk_topic"] = forged
                content["deterministic"][0]["source"]["morning_talk_topic"] = forged
                content["deterministic"][0]["effective"]["morning_talk_topic"] = forged
                validated = weekly_plan_content.validate_content(content)
                self.assertIsInstance(validated, dict)
                self.assertEqual(
                    validated["deterministic"][0]["source"]["morning_talk_topic"],
                    forged,
                )
                self.assertEqual(
                    validated["deterministic"][0]["effective"]["morning_talk_topic"],
                    forged,
                )
                validated["source_manifest"]["source_context_hash"] = (
                    weekly_plan_sources.source_context_hash(
                        profile_id=snapshot["profile_id"],
                        class_id=snapshot["class_id"],
                        term_id=snapshot["term_id"],
                        week_anchor_date=snapshot["week_anchor_date"],
                        week_number=snapshot["week_number"],
                        term_start=snapshot["term_start"],
                        term_end=snapshot["term_end"],
                        calendar_revision_id=snapshot["calendar_revision_id"],
                        days=snapshot["days"],
                        game_projection=weekly_plan_sources._game_projection(
                            self.session, snapshot["class_id"], snapshot["days"]
                        ),
                    )
                )
                content = weekly_plan_content.validate_content(validated)
            else:
                content["deterministic"][0]["effective"]["morning_talk_topic"] = "伪造"

            digest = weekly_plan_content.content_hash(content)
            connection.execute(
                "UPDATE local_weekly_plan_contents SET content_json=?, "
                "content_hash=? WHERE id=?",
                (json.dumps(content, ensure_ascii=False), digest, old["id"]),
            )
            self._sync_copies(
                connection,
                draft_id=old["id"],
                draft_version=old["version"],
                content=content,
                digest=digest,
                confirmations=confirmations,
            )
            daily_after = [
                tuple(row)
                for row in connection.execute(
                    "SELECT id, adopted_content FROM local_daily_plan_contents "
                    "ORDER BY id"
                ).fetchall()
            ]
            self.assertEqual(daily_after, daily_before)
            connection.commit()
            self.assertEqual(
                connection.execute("PRAGMA foreign_key_check").fetchall(), []
            )
        finally:
            connection.close()

    def test_old_draft_effective_only_must_not_validate_as_history(self) -> None:
        copy_path, _plan_id = self._prepare()
        self._assert_baseline_valid(copy_path)
        self._mutate_old(copy_path, source_change=False)
        self._retain_db(copy_path, "tampered")
        with self.assertRaises(backup_validate.BackupValidationError):
            backup_validate.validate_database(
                copy_path,
                migrate_old=False,
                require_current=True,
                scratch_dir=self.tmp_root,
            )

    def test_old_draft_source_and_effective_must_not_validate_as_history(self) -> None:
        copy_path, _plan_id = self._prepare()
        self._assert_baseline_valid(copy_path)
        self._mutate_old(copy_path, source_change=True)
        self._retain_db(copy_path, "tampered")
        with self.assertRaises(backup_validate.BackupValidationError):
            backup_validate.validate_database(
                copy_path,
                migrate_old=False,
                require_current=True,
                scratch_dir=self.tmp_root,
            )


if __name__ == "__main__":
    unittest.main()
