"""Pointer integrity, deferred-FK commit failures and fault-injected saves.

Constraint evidence uses direct SQL on the real file (real DDL, real
foreign keys). Save failures are injected with real SQLite triggers:
statement-time ABORT for content/audit inserts and a commit-time deferred
FK violation for the pointer update. In every case the previous content,
pointer and audit rows must survive unchanged and the API must not
reinterpret the failure as duplicate-create or version-conflict.
"""

from __future__ import annotations

import sqlite3
import unittest
from datetime import datetime

from tests.local.support import (
    LocalTestCase,
    StaticCalendarProvider,
    calendar_provider,
    execute_sql,
    query_rows,
    query_scalar,
    sqlite_connect,
)

HEADER_INSERT = (
    "INSERT INTO local_daily_plans ("
    "id, class_id, term_id, plan_date, creator_id, week_number, weekday, "
    "calendar_revision_id, current_content_id, current_content_version, "
    "creator_display_name, school_name, class_name, grade, deleted_at, "
    "deleted_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,NULL,?,?)"
)

CONTENT_INSERT = (
    "INSERT INTO local_daily_plan_contents (id, daily_plan_id, version, "
    "raw_lesson_plan, split_baseline, adopted_content, editor_id, created_at) "
    "VALUES (?,?,?,?,NULL,?,?,?)"
)


class TransactionIntegrityTests(LocalTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.provider = StaticCalendarProvider()
        self.enterContext(calendar_provider(self.provider))
        self.server = self.start_server()
        self.client = self.server.client()
        self.initialize(self.client)
        self.db = self.server.runtime.db_path
        status, self.plan = self.client.post(
            "/api/daily-plans", {"plan_date": "2026-09-01", "raw_lesson_plan": "v1"}
        )
        self.assertEqual(status, 201, self.plan)
        self.header = query_rows(
            self.db,
            "SELECT id, class_id, term_id, creator_id, calendar_revision_id, "
            "current_content_id, current_content_version "
            "FROM local_daily_plans",
        )[0]
        self.now = "2026-10-12 00:00:00"

    def _new_header_values(self, *, plan_date="2026-09-08", **overrides):
        values = {
            "id": "pxxxxxxxxxxxxxxxxxxxxx",
            "class_id": self.header["class_id"],
            "term_id": self.header["term_id"],
            "plan_date": plan_date,
            "creator_id": self.header["creator_id"],
            "week_number": 2,
            "weekday": 2,
            "calendar_revision_id": self.header["calendar_revision_id"],
            "current_content_id": "cxxxxxxxxxxxxxxxxxxxxx",
            "current_content_version": 1,
            "creator_display_name": "王老师",
            "school_name": "示范幼儿园",
            "class_name": "中一班",
            "grade": "middle",
        }
        values.update(overrides)
        return (
            values["id"],
            values["class_id"],
            values["term_id"],
            values["plan_date"],
            values["creator_id"],
            values["week_number"],
            values["weekday"],
            values["calendar_revision_id"],
            values["current_content_id"],
            values["current_content_version"],
            values["creator_display_name"],
            values["school_name"],
            values["class_name"],
            values["grade"],
            self.now,
            self.now,
        )

    def _expect_commit_failure(self, values) -> None:
        connection = sqlite_connect(self.db)
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(HEADER_INSERT, values)
            with self.assertRaises(sqlite3.IntegrityError):
                connection.commit()
            connection.rollback()
        finally:
            connection.close()
        self.assertIsNone(
            query_scalar(
                self.db,
                "SELECT id FROM local_daily_plans WHERE id = ?",
                (values[0],),
            )
        )

    # -- direct constraint evidence ---------------------------------------
    def test_first_content_version_is_mandatory(self):
        # Pointer to a content row that never exists -> commit must fail.
        self._expect_commit_failure(self._new_header_values())

    def test_pointer_version_mismatch_cannot_commit(self):
        # Same content id, wrong version -> the triple does not exist.
        self._expect_commit_failure(
            self._new_header_values(
                current_content_id=self.header["current_content_id"],
                current_content_version=99,
            )
        )

    def test_cross_plan_pointer_cannot_commit(self):
        # Pointer to another plan's content triple.
        status, other = self.client.post(
            "/api/daily-plans", {"plan_date": "2026-09-02"}
        )
        self.assertEqual(status, 201)
        self._expect_commit_failure(
            self._new_header_values(
                current_content_id=other["current_content_id"],
                current_content_version=1,
            )
        )

    def test_duplicate_content_version_is_rejected(self):
        connection = sqlite_connect(self.db)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO local_daily_plan_contents "
                    "(id, daily_plan_id, version, raw_lesson_plan, split_baseline, "
                    " adopted_content, editor_id, created_at) "
                    "VALUES (?,?,?,?,NULL,?,?,?)",
                    (
                        "dupxxxxxxxxxxxxxxxxxxx",
                        self.plan["id"],
                        1,
                        "dup",
                        "{}",
                        self.header["creator_id"],
                        self.now,
                    ),
                )
        finally:
            connection.close()

    def test_second_effective_plan_is_rejected_by_unique_index_at_insert(self):
        # The duplicate header points at its own (still missing) first
        # content version, so the only thing that can reject the INSERT
        # statement itself is the effective-date partial unique index. A
        # deferred-FK failure would happen only at COMMIT; asserting the
        # stage and SQLite error name separates the two.
        connection = sqlite_connect(self.db)
        try:
            connection.execute("BEGIN IMMEDIATE")
            with self.assertRaises(sqlite3.IntegrityError) as caught:
                connection.execute(
                    HEADER_INSERT,
                    self._new_header_values(
                        plan_date="2026-09-01", week_number=1, weekday=2
                    ),
                )
            error = caught.exception
            self.assertEqual(
                getattr(error, "sqlite_errorname", ""), "SQLITE_CONSTRAINT_UNIQUE"
            )
            message = str(error)
            self.assertIn("class_id", message)
            self.assertIn("plan_date", message)
            self.assertNotIn("FOREIGN KEY", message.upper())
            connection.rollback()
        finally:
            connection.close()
        self.assertEqual(
            query_scalar(self.db, "SELECT count(*) AS n FROM local_daily_plans"),
            1,
        )

    def test_same_day_duplicate_commit_succeeds_when_unique_index_is_dropped(self):
        # Counter-check for the test above: with a fully valid header and
        # first version (all other constraints satisfied), removing only
        # the effective-date index is what allows the duplicate to commit.
        execute_sql(
            self.db, "DROP INDEX uq_local_daily_plans_effective_class_date"
        )
        values = self._new_header_values(
            plan_date="2026-09-01", week_number=1, weekday=2
        )
        connection = sqlite_connect(self.db)
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(HEADER_INSERT, values)
            connection.execute(
                CONTENT_INSERT,
                (
                    values[8],  # current_content_id
                    values[0],  # plan id
                    1,
                    "dup",
                    "{}",
                    self.header["creator_id"],
                    self.now,
                ),
            )
            connection.commit()
        finally:
            connection.close()
        self.assertEqual(
            query_scalar(self.db, "SELECT count(*) AS n FROM local_daily_plans"),
            2,
        )

    # -- fault-injected service saves -------------------------------------
    def _state(self) -> dict:
        return {
            "contents": query_scalar(
                self.db, "SELECT count(*) AS n FROM local_daily_plan_contents"
            ),
            "audit": query_scalar(
                self.db, "SELECT count(*) AS n FROM local_operation_records"
            ),
            "version": query_scalar(
                self.db,
                "SELECT current_content_version FROM local_daily_plans WHERE id = ?",
                (self.plan["id"],),
            ),
            "content_id": query_scalar(
                self.db,
                "SELECT current_content_id FROM local_daily_plans WHERE id = ?",
                (self.plan["id"],),
            ),
            "raw": query_scalar(
                self.db,
                "SELECT raw_lesson_plan FROM local_daily_plan_contents WHERE id = ?",
                (self.header["current_content_id"],),
            ),
        }

    def _save(self):
        return self.client.patch(
            f"/api/daily-plans/{self.plan['id']}",
            {"expected_content_version": 1, "raw_lesson_plan": "v2"},
        )

    def _with_trigger(self, name: str, create_sql: str):
        execute_sql(self.db, create_sql)
        try:
            yield
        finally:
            execute_sql(self.db, f"DROP TRIGGER IF EXISTS {name}")

    def test_content_insert_failure_keeps_previous_state(self):
        before = self._state()
        for _ in self._with_trigger(
            "fault_content",
            "CREATE TRIGGER fault_content BEFORE INSERT ON local_daily_plan_contents "
            "BEGIN SELECT RAISE(ABORT, 'injected content insert failure'); END",
        ):
            status, payload = self._save()
        self.assertEqual(status, 503, payload)
        self.assertEqual(payload["error"]["code"], "LOCAL_STORAGE_ERROR")
        self.assertEqual(self._state(), before)

    def test_pointer_update_failure_fails_at_commit_and_rolls_back(self):
        before = self._state()
        for _ in self._with_trigger(
            "fault_pointer",
            "CREATE TRIGGER fault_pointer AFTER UPDATE ON local_daily_plans "
            "WHEN NEW.current_content_version = 2 "
            "BEGIN UPDATE local_daily_plans SET current_content_version = 99 "
            "WHERE id = NEW.id; END",
        ):
            status, payload = self._save()
        self.assertEqual(status, 503, payload)
        self.assertEqual(payload["error"]["code"], "LOCAL_STORAGE_ERROR")
        self.assertEqual(self._state(), before)

    def test_audit_insert_failure_rolls_back_everything(self):
        before = self._state()
        for _ in self._with_trigger(
            "fault_audit",
            "CREATE TRIGGER fault_audit BEFORE INSERT ON local_operation_records "
            "BEGIN SELECT RAISE(ABORT, 'injected audit failure'); END",
        ):
            status, payload = self._save()
        self.assertEqual(status, 503, payload)
        self.assertEqual(payload["error"]["code"], "LOCAL_STORAGE_ERROR")
        self.assertEqual(self._state(), before)

    def test_create_path_failure_is_not_reported_as_duplicate_open(self):
        for _ in self._with_trigger(
            "fault_header",
            "CREATE TRIGGER fault_header BEFORE INSERT ON local_daily_plans "
            "BEGIN SELECT RAISE(ABORT, 'injected header failure'); END",
        ):
            status, payload = self.client.post(
                "/api/daily-plans", {"plan_date": "2026-09-03"}
            )
        self.assertEqual(status, 503, payload)
        self.assertEqual(payload["error"]["code"], "LOCAL_STORAGE_ERROR")
        self.assertEqual(
            query_scalar(
                self.db, "SELECT count(*) AS n FROM local_daily_plans"
            ),
            1,
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
