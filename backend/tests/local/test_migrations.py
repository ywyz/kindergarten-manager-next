"""Real file/Alembic initialization, restart stability and version guards."""

from __future__ import annotations

import sqlite3
import subprocess
import sys
import unittest
from datetime import date
from pathlib import Path

from alembic import command
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.local import daily_plan_service, profile_service
from app.local.errors import LocalDatabaseStateError
from app.local.migrate import alembic_config, ensure_local_schema, head_revision
from app.local.normalize import normalize_initialization
from app.local.runtime import LocalRuntime
from app.local.sqlite import (
    LOCAL_VERSION_TABLE,
    connection_settings,
    create_local_engine,
)
from tests.local.support import (
    BACKEND_DIR,
    LocalTestCase,
    StaticCalendarProvider,
    calendar_provider,
    execute_sql,
    initialize_body,
    query_rows,
    query_scalar,
    sqlite_connect,
    worker_env,
)

OLD_HEAD_REVISION = "20261012_0001_local"

EXPECTED_TABLES = {
    "local_profile",
    "local_settings",
    "local_classes",
    "local_terms",
    "local_calendar_revisions",
    "local_calendar_days",
    "local_daily_plans",
    "local_daily_plan_contents",
    "local_operation_records",
    "local_config_operations",
    LOCAL_VERSION_TABLE,
}

# Deterministic identities of the synthetic D1A-era dataset.
_OLD_PROFILE_ID = "profile-old-0001-abcdef"
_OLD_CLASS_ID = "class-old-0001-abcdefgh"
_OLD_TERM_ID = "term-old-0001-abcdefgh"
_OLD_REVISION_ID = "rev-old-0001-abcdefghij"


class MigrationTests(LocalTestCase):
    def test_empty_file_baselines_to_head_with_constraints(self):
        runtime = self.make_runtime()
        db = runtime.db_path
        self.assertTrue(db.is_file())
        self.assertGreater(db.stat().st_size, 0)

        versions = query_rows(db, f"SELECT version_num FROM {LOCAL_VERSION_TABLE}")
        self.assertEqual([row["version_num"] for row in versions], [head_revision()])

        tables = {
            row["name"]
            for row in query_rows(
                db, "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        self.assertTrue(EXPECTED_TABLES <= tables, tables)
        self.assertEqual(query_rows(db, "PRAGMA foreign_key_check"), [])

        # Partial unique index with the exact WHERE clause (no effective_date).
        index_sql = query_scalar(
            db,
            "SELECT sql FROM sqlite_master WHERE type='index' "
            "AND name='uq_local_daily_plans_effective_class_date'",
        )
        self.assertIsNotNone(index_sql)
        self.assertIn("WHERE deleted_at IS NULL", index_sql)
        self.assertNotIn("effective_date", index_sql)

        # Inline composite deferred FKs and named CHECK constraints exist.
        plans_ddl = query_scalar(
            db, "SELECT sql FROM sqlite_master WHERE name='local_daily_plans'"
        )
        self.assertIn("DEFERRABLE INITIALLY DEFERRED", plans_ddl)
        self.assertIn("fk_local_daily_plans_current_content", plans_ddl)
        self.assertIn("fk_local_daily_plans_term_revision", plans_ddl)
        self.assertIn(
            "ck_local_daily_plans_current_content_version", plans_ddl
        )
        terms_ddl = query_scalar(
            db, "SELECT sql FROM sqlite_master WHERE name='local_terms'"
        )
        self.assertIn("DEFERRABLE INITIALLY DEFERRED", terms_ddl)
        self.assertIn(
            "current_calendar_revision_id VARCHAR(32) NOT NULL", terms_ddl
        )
        terms_columns = {
            row["name"]: row
            for row in query_rows(db, "PRAGMA table_info('local_terms')")
        }
        self.assertEqual(terms_columns["current_calendar_revision_id"]["notnull"], 1)
        revisions_ddl = query_scalar(
            db, "SELECT sql FROM sqlite_master WHERE name='local_calendar_revisions'"
        )
        self.assertIn("uq_local_calendar_revisions_term_id", revisions_ddl)
        self.assertIn("uq_local_calendar_revisions_term_revision", revisions_ddl)

        # The effective-date unique index is a partial index on exactly
        # (class_id, plan_date); the predicate leaves soft-deleted rows out.
        index_rows = [
            row
            for row in query_rows(db, "PRAGMA index_list('local_daily_plans')")
            if row["name"] == "uq_local_daily_plans_effective_class_date"
        ]
        self.assertEqual(len(index_rows), 1, index_rows)
        self.assertEqual(index_rows[0]["unique"], 1)
        self.assertEqual(index_rows[0]["partial"], 1)
        index_columns = query_rows(
            db, "PRAGMA index_info('uq_local_daily_plans_effective_class_date')"
        )
        self.assertEqual(
            [(row["seqno"], row["name"]) for row in index_columns],
            [(0, "class_id"), (1, "plan_date")],
        )

        # MySQL-specific constructs are absent.
        self.assertNotIn("utf8mb4", plans_ddl)
        self.assertNotIn("CHAR_LENGTH", plans_ddl)

    def test_repeat_start_does_not_change_data(self):
        runtime = self.make_runtime()
        db = runtime.db_path
        before = query_rows(db, f"SELECT version_num FROM {LOCAL_VERSION_TABLE}")
        checksum_before = query_scalar(
            db,
            "SELECT count(*) AS n FROM sqlite_master WHERE type='table'",
        )
        # 同一数据根不允许第二个runtime并行持有独占锁；用同一runtime的
        # 数据文件直接再次读取，验证重复启动不改变数据。
        after = query_rows(db, f"SELECT version_num FROM {LOCAL_VERSION_TABLE}")
        self.assertEqual(before, after)
        self.assertEqual(
            checksum_before,
            query_scalar(
                db, "SELECT count(*) AS n FROM sqlite_master WHERE type='table'"
            ),
        )
        self.assertTrue(runtime.prepared)

    def test_unknown_or_newer_revision_is_refused_and_file_preserved(self):
        runtime = self.make_runtime()
        db = runtime.db_path
        runtime.dispose()
        execute_sql(
            db,
            f"UPDATE {LOCAL_VERSION_TABLE} SET version_num = '20990101_9999_future'",
        )
        with self.assertRaises(LocalDatabaseStateError) as caught:
            ensure_local_schema(db)
        self.assertEqual(caught.exception.code, "LOCAL_DB_VERSION_UNSUPPORTED")
        # Original file and its data are preserved; nothing was stamped.
        self.assertEqual(
            query_scalar(db, f"SELECT version_num FROM {LOCAL_VERSION_TABLE}"),
            "20990101_9999_future",
        )
        self.assertEqual(
            query_scalar(
                db, "SELECT count(*) AS n FROM sqlite_master WHERE name='local_profile'"
            ),
            1,
        )

    def test_multi_row_version_states_are_refused_in_both_orders(self):
        head = head_revision()
        cases = {
            "known_then_unknown": (
                f"INSERT INTO {LOCAL_VERSION_TABLE} (version_num) "
                "VALUES ('20990101_9999_future')",
            ),
            "unknown_then_known": (
                f"DELETE FROM {LOCAL_VERSION_TABLE}",
                f"INSERT INTO {LOCAL_VERSION_TABLE} (version_num) "
                "VALUES ('20990101_9999_future')",
                f"INSERT INTO {LOCAL_VERSION_TABLE} (version_num) "
                f"VALUES ('{head}')",
            ),
            "two_known_rows": (
                f"INSERT INTO {LOCAL_VERSION_TABLE} (version_num) "
                f"VALUES ('{OLD_HEAD_REVISION}')",
            ),
        }
        for label, statements in cases.items():
            with self.subTest(label=label):
                data_dir = self.tmp_root / f"versions-{label}"
                runtime = LocalRuntime(
                    data_dir, credential_root=self.credential_root
                )
                runtime.prepare()
                runtime.dispose()
                db = data_dir / "kindergarten.db"
                for statement in statements:
                    execute_sql(db, statement)
                before = query_rows(
                    db, f"SELECT rowid, version_num FROM {LOCAL_VERSION_TABLE}"
                )
                self.assertEqual(len(before), 2, before)
                with self.assertRaises(LocalDatabaseStateError) as caught:
                    ensure_local_schema(db)
                self.assertEqual(
                    caught.exception.code, "LOCAL_DB_VERSION_UNSUPPORTED"
                )
                # Nothing was cleaned, downgraded or stamped.
                after = query_rows(
                    db, f"SELECT rowid, version_num FROM {LOCAL_VERSION_TABLE}"
                )
                self.assertEqual(after, before)
                self.assertEqual(
                    query_scalar(
                        db, "SELECT count(*) AS n FROM sqlite_master WHERE name='local_profile'"
                    ),
                    1,
                )

    # -- R2: first calendar revision and old-head upgrades -----------------
    def _upgrade_old_head(self, data_dir: Path) -> Path:
        data_dir.mkdir(parents=True, exist_ok=True)
        db = data_dir / "kindergarten.db"
        command.upgrade(alembic_config(db), OLD_HEAD_REVISION)
        self.assertEqual(
            query_scalar(db, f"SELECT version_num FROM {LOCAL_VERSION_TABLE}"),
            OLD_HEAD_REVISION,
        )
        columns = {
            row["name"]: row
            for row in query_rows(db, "PRAGMA table_info('local_terms')")
        }
        self.assertEqual(columns["current_calendar_revision_id"]["notnull"], 0)
        return db

    def _execute_without_foreign_keys(self, db, statements) -> None:
        connection = sqlite3.connect(str(db))
        try:
            for statement in statements:
                connection.execute(statement)
            connection.commit()
        finally:
            connection.close()

    def _seed_old_schema_dataset(self, db: Path) -> tuple[str, str, str, str]:
        """Insert a D1A-era initialized dataset with raw SQL on the old schema.

        The current service code already writes the 0003 ``config_version``
        column and therefore cannot run against a pre-0003 database; these
        raw rows mirror exactly what the reviewed D1A code produced (single
        profile/class/term, one 30-day revision, settings) so the upgrade
        path still operates on realistic existing data.
        """
        statements = [
            "INSERT INTO local_profile (id, singleton, display_name, "
            f"created_at, updated_at) VALUES ('{_OLD_PROFILE_ID}', 1, '王老师', "
            "'2026-10-12 00:00:00', '2026-10-12 00:00:00')",
            "INSERT INTO local_classes (id, name, grade, created_at, updated_at) "
            f"VALUES ('{_OLD_CLASS_ID}', '中一班', 'middle', "
            "'2026-10-12 00:00:00', '2026-10-12 00:00:00')",
            "INSERT INTO local_terms (id, name, start_date, end_date, "
            "current_calendar_revision_id, created_at, updated_at) "
            f"VALUES ('{_OLD_TERM_ID}', '2026 年秋季学期', '2026-09-01', "
            "'2026-09-30', NULL, '2026-10-12 00:00:00', '2026-10-12 00:00:00')",
            "INSERT INTO local_calendar_revisions (id, term_id, revision_no, "
            "library_version, created_by, created_at) "
            f"VALUES ('{_OLD_REVISION_ID}', '{_OLD_TERM_ID}', 1, 'seed-v1', "
            f"'{_OLD_PROFILE_ID}', '2026-10-12 00:00:00')",
            "UPDATE local_terms SET current_calendar_revision_id = "
            f"'{_OLD_REVISION_ID}' WHERE id = '{_OLD_TERM_ID}'",
            "INSERT INTO local_settings (id, singleton, school_name, "
            "current_class_id, init_request_id, init_input_fingerprint, "
            "created_at, updated_at) "
            f"VALUES ('singleton', 1, '示范幼儿园', '{_OLD_CLASS_ID}', "
            f"'00000000-0000-4000-8000-000000000001', '{'a' * 64}', "
            "'2026-10-12 00:00:00', '2026-10-12 00:00:00')",
        ]
        for day in range(1, 31):
            date_text = f"2026-09-{day:02d}"
            statements.append(
                "INSERT INTO local_calendar_days (revision_id, date, "
                "base_state, base_library_version, override_state, "
                "override_reason, effective_state) "
                f"VALUES ('{_OLD_REVISION_ID}', '{date_text}', 'teaching', "
                "'seed-v1', NULL, NULL, 'teaching')"
            )
        self._execute_without_foreign_keys(db, statements)
        self.assertEqual(query_rows(db, "PRAGMA foreign_key_check"), [])
        return _OLD_PROFILE_ID, _OLD_CLASS_ID, _OLD_TERM_ID, _OLD_REVISION_ID

    def test_old_head_with_valid_pointer_upgrades_and_keeps_data(self):
        self.enterContext(calendar_provider(StaticCalendarProvider()))
        data_dir = self.tmp_root / "old-head-valid"
        db = self._upgrade_old_head(data_dir)

        # Build a real D1A-era dataset on the old schema with raw SQL (the
        # current service writes the 0003 column and cannot run pre-0003).
        profile_id, class_id, term_id, revision_id = self._seed_old_schema_dataset(
            db
        )
        self.assertEqual(
            query_scalar(db, "SELECT current_calendar_revision_id FROM local_terms"),
            revision_id,
        )

        inspection = ensure_local_schema(db)
        self.assertEqual(inspection.state, "current")
        self.assertEqual(inspection.current_revision, head_revision())
        self.assertEqual(
            query_scalar(db, f"SELECT version_num FROM {LOCAL_VERSION_TABLE}"),
            head_revision(),
        )
        columns = {
            row["name"]: row
            for row in query_rows(db, "PRAGMA table_info('local_terms')")
        }
        self.assertEqual(columns["current_calendar_revision_id"]["notnull"], 1)
        self.assertEqual(query_scalar(db, "SELECT id FROM local_terms"), term_id)
        self.assertEqual(
            query_scalar(db, "SELECT current_calendar_revision_id FROM local_terms"),
            revision_id,
        )
        self.assertEqual(
            query_scalar(db, "SELECT count(*) AS n FROM local_calendar_days"), 30
        )
        self.assertEqual(query_rows(db, "PRAGMA foreign_key_check"), [])
        # 0003: existing rows receive config_version = 1 and the receipt
        # table exists.
        settings_columns = {
            row["name"]: row
            for row in query_rows(db, "PRAGMA table_info('local_settings')")
        }
        self.assertIn("config_version", settings_columns)
        self.assertEqual(
            query_scalar(db, "SELECT config_version FROM local_settings"), 1
        )
        self.assertEqual(
            query_scalar(
                db,
                "SELECT count(*) AS n FROM sqlite_master "
                "WHERE type='table' AND name='local_config_operations'",
            ),
            1,
        )

        # A fresh runtime reads the same objects back and can save a plan.
        runtime = LocalRuntime(data_dir, credential_root=self.credential_root)
        runtime.prepare()
        self.addCleanup(runtime.dispose)
        session = runtime.session()
        try:
            context = profile_service.read_context(session, date(2026, 9, 15))
            self.assertEqual(context["status"], "ready")
            self.assertEqual(context["profile"]["id"], profile_id)
            self.assertEqual(context["calendar_revision"]["id"], revision_id)
            plan, plan_created = daily_plan_service.create_or_open(
                session, plan_date=date(2026, 9, 1), raw_lesson_plan="v1"
            )
        finally:
            session.close()
        self.assertTrue(plan_created)
        session = runtime.session()
        try:
            saved = daily_plan_service.save(
                session,
                plan_id=plan["id"],
                expected_content_version=1,
                raw_lesson_plan="v2",
            )
        finally:
            session.close()
        self.assertEqual(saved["current_content_version"], 2)

    def test_old_head_null_pointer_is_refused_and_preserved(self):
        data_dir = self.tmp_root / "old-head-null"
        db = self._upgrade_old_head(data_dir)
        self._execute_without_foreign_keys(
            db,
            [
                "INSERT INTO local_terms (id, name, start_date, end_date, "
                "current_calendar_revision_id, created_at, updated_at) "
                "VALUES ('null-term', 'n', '2026-09-01', '2026-09-30', NULL, "
                "'2026-01-01 00:00:00', '2026-01-01 00:00:00')"
            ],
        )
        with self.assertRaises(LocalDatabaseStateError) as caught:
            ensure_local_schema(db)
        self.assertEqual(caught.exception.code, "LOCAL_DB_MIGRATION_FAILED")
        self.assertEqual(
            query_scalar(db, f"SELECT version_num FROM {LOCAL_VERSION_TABLE}"),
            OLD_HEAD_REVISION,
        )
        self.assertEqual(
            query_scalar(db, "SELECT id FROM local_terms"), "null-term"
        )
        self.assertIsNone(
            query_scalar(db, "SELECT current_calendar_revision_id FROM local_terms")
        )
        columns = {
            row["name"]: row
            for row in query_rows(db, "PRAGMA table_info('local_terms')")
        }
        self.assertEqual(columns["current_calendar_revision_id"]["notnull"], 0)

    def test_old_head_dangling_pointer_is_refused_and_preserved(self):
        data_dir = self.tmp_root / "old-head-dangling"
        db = self._upgrade_old_head(data_dir)
        self._execute_without_foreign_keys(
            db,
            [
                "INSERT INTO local_terms (id, name, start_date, end_date, "
                "current_calendar_revision_id, created_at, updated_at) "
                "VALUES ('dangling-term', 'n', '2026-09-01', '2026-09-30', "
                "'missing-revision', '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
            ],
        )
        with self.assertRaises(LocalDatabaseStateError) as caught:
            ensure_local_schema(db)
        self.assertEqual(caught.exception.code, "LOCAL_DB_MIGRATION_FAILED")
        self.assertEqual(
            query_scalar(db, f"SELECT version_num FROM {LOCAL_VERSION_TABLE}"),
            OLD_HEAD_REVISION,
        )
        self.assertEqual(
            query_scalar(db, "SELECT current_calendar_revision_id FROM local_terms"),
            "missing-revision",
        )

    def test_old_head_foreign_pointer_is_refused_and_preserved(self):
        data_dir = self.tmp_root / "old-head-foreign"
        db = self._upgrade_old_head(data_dir)
        self._execute_without_foreign_keys(
            db,
            [
                "INSERT INTO local_profile (id, singleton, display_name, "
                "created_at, updated_at) VALUES ('p1', 1, 'n', "
                "'2026-01-01 00:00:00', '2026-01-01 00:00:00')",
                "INSERT INTO local_terms (id, name, start_date, end_date, "
                "current_calendar_revision_id, created_at, updated_at) "
                "VALUES ('term-a', '甲', '2026-09-01', '2026-09-30', NULL, "
                "'2026-01-01 00:00:00', '2026-01-01 00:00:00')",
                "INSERT INTO local_terms (id, name, start_date, end_date, "
                "current_calendar_revision_id, created_at, updated_at) "
                "VALUES ('term-b', '乙', '2026-09-01', '2026-09-30', NULL, "
                "'2026-01-01 00:00:00', '2026-01-01 00:00:00')",
                "INSERT INTO local_calendar_revisions (id, term_id, revision_no, "
                "library_version, created_by, created_at) "
                "VALUES ('rev-a', 'term-a', 1, 'v', 'p1', "
                "'2026-01-01 00:00:00')",
                "UPDATE local_terms SET current_calendar_revision_id = 'rev-a' "
                "WHERE id = 'term-a'",
                "UPDATE local_terms SET current_calendar_revision_id = 'rev-a' "
                "WHERE id = 'term-b'",
            ],
        )
        with self.assertRaises(LocalDatabaseStateError) as caught:
            ensure_local_schema(db)
        self.assertEqual(caught.exception.code, "LOCAL_DB_MIGRATION_FAILED")
        self.assertEqual(
            query_scalar(
                db, "SELECT current_calendar_revision_id FROM local_terms "
                "WHERE id = 'term-b'"
            ),
            "rev-a",
        )

    def test_term_revision_pointer_schema_constraints(self):
        runtime = self.make_runtime()
        db = runtime.db_path
        connection = sqlite_connect(db)
        try:
            # NULL pointer is rejected by the column NOT NULL immediately.
            connection.execute("BEGIN IMMEDIATE")
            with self.assertRaises(sqlite3.IntegrityError) as caught:
                connection.execute(
                    "INSERT INTO local_terms (id, name, start_date, end_date, "
                    "current_calendar_revision_id, created_at, updated_at) "
                    "VALUES ('null-term', 'n', '2026-09-01', '2026-09-30', "
                    "NULL, 't', 't')"
                )
            self.assertEqual(
                getattr(caught.exception, "sqlite_errorname", ""),
                "SQLITE_CONSTRAINT_NOTNULL",
            )
            connection.rollback()

            # A missing revision is rejected by the deferred composite FK at
            # COMMIT, never accepted just because it is non-null.
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO local_terms (id, name, start_date, end_date, "
                "current_calendar_revision_id, created_at, updated_at) "
                "VALUES ('dangling-term', 'n', '2026-09-01', '2026-09-30', "
                "'missing-revision', 't', 't')"
            )
            with self.assertRaises(sqlite3.IntegrityError) as caught:
                connection.commit()
            self.assertEqual(
                getattr(caught.exception, "sqlite_errorname", ""),
                "SQLITE_CONSTRAINT_FOREIGNKEY",
            )
            connection.rollback()

            # The cyclic pair commits atomically when both rows are present.
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO local_profile (id, singleton, display_name, "
                "created_at, updated_at) VALUES ('p1', 1, 'n', 't', 't')"
            )
            connection.execute(
                "INSERT INTO local_terms (id, name, start_date, end_date, "
                "current_calendar_revision_id, created_at, updated_at) "
                "VALUES ('term-ok', 'n', '2026-09-01', '2026-09-30', "
                "'rev-ok', 't', 't')"
            )
            connection.execute(
                "INSERT INTO local_calendar_revisions (id, term_id, revision_no, "
                "library_version, created_by, created_at) "
                "VALUES ('rev-ok', 'term-ok', 1, 'v', 'p1', 't')"
            )
            connection.commit()
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
        finally:
            connection.close()

    def test_failed_upgrade_rolls_back_midway_and_preserves_old_data(self):
        # A genuine mid-migration failure: the validation passes, the new
        # table is created and the copy starts, but an over-long term name
        # (injected with CHECK enforcement disabled) violates the rebuilt
        # CHECK. The whole env.py transaction must roll back and leave the
        # old head file, version and rows exactly as they were.
        self.enterContext(calendar_provider(StaticCalendarProvider()))
        data_dir = self.tmp_root / "old-head-midway"
        db = self._upgrade_old_head(data_dir)

        profile_id, class_id, term_id, revision_id = self._seed_old_schema_dataset(
            db
        )

        connection = sqlite3.connect(str(db))
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA ignore_check_constraints=ON")
            connection.execute(
                "INSERT INTO local_terms (id, name, start_date, end_date, "
                "current_calendar_revision_id, created_at, updated_at) "
                "VALUES ('long-term', ?, '2026-09-01', '2026-09-30', NULL, "
                "'2026-01-01 00:00:00', '2026-01-01 00:00:00')",
                ("x" * 200,),
            )
            connection.execute(
                "INSERT INTO local_calendar_revisions (id, term_id, revision_no, "
                "library_version, created_by, created_at) "
                "VALUES ('long-rev', 'long-term', 1, 'v', ?, "
                "'2026-01-01 00:00:00')",
                (profile_id,),
            )
            connection.execute(
                "UPDATE local_terms SET current_calendar_revision_id = "
                "'long-rev' WHERE id = 'long-term'"
            )
            connection.commit()
        finally:
            connection.close()

        with self.assertRaises(LocalDatabaseStateError) as caught:
            ensure_local_schema(db)
        self.assertEqual(caught.exception.code, "LOCAL_DB_MIGRATION_FAILED")
        self.assertEqual(
            query_scalar(db, f"SELECT version_num FROM {LOCAL_VERSION_TABLE}"),
            OLD_HEAD_REVISION,
        )
        self.assertEqual(
            query_scalar(
                db, "SELECT length(name) FROM local_terms WHERE id = 'long-term'"
            ),
            200,
        )
        self.assertEqual(
            query_scalar(
                db, "SELECT current_calendar_revision_id FROM local_terms "
                "WHERE id = 'long-term'"
            ),
            "long-rev",
        )
        self.assertIsNotNone(
            query_scalar(
                db, "SELECT id FROM local_calendar_revisions WHERE id = ?",
                (revision_id,),
            )
        )
        columns = {
            row["name"]: row
            for row in query_rows(db, "PRAGMA table_info('local_terms')")
        }
        self.assertEqual(columns["current_calendar_revision_id"]["notnull"], 0)
        self.assertEqual(
            query_scalar(
                db,
                "SELECT count(*) AS n FROM sqlite_master "
                "WHERE name = '_local_terms_rebuild'",
            ),
            0,
        )

    def test_unmanaged_non_empty_database_is_refused(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        db = self.data_dir / "kindergarten.db"
        connection = sqlite3.connect(str(db))
        try:
            connection.execute("CREATE TABLE legacy_business (id INTEGER)")
            connection.execute("INSERT INTO legacy_business (id) VALUES (1)")
            connection.commit()
        finally:
            connection.close()

        with self.assertRaises(LocalDatabaseStateError) as caught:
            ensure_local_schema(db)
        self.assertEqual(caught.exception.code, "LOCAL_DB_NOT_MANAGED")
        self.assertEqual(
            query_scalar(db, "SELECT count(*) AS n FROM legacy_business"), 1
        )
        # No local tables and no version record were created.
        self.assertIsNone(
            query_scalar(
                db, "SELECT name FROM sqlite_master WHERE name='local_profile'"
            )
        )

    def test_empty_version_table_with_business_tables_is_refused(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        db = self.data_dir / "kindergarten.db"
        connection = sqlite3.connect(str(db))
        try:
            connection.execute("CREATE TABLE other_app (id INTEGER)")
            connection.execute(f"CREATE TABLE {LOCAL_VERSION_TABLE} (version_num VARCHAR(32) NOT NULL)")
            connection.commit()
        finally:
            connection.close()
        with self.assertRaises(LocalDatabaseStateError) as caught:
            ensure_local_schema(db)
        self.assertEqual(caught.exception.code, "LOCAL_DB_NOT_MANAGED")

    def test_unreadable_file_is_refused_and_preserved(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        db = self.data_dir / "kindergarten.db"
        original = b"this is not a sqlite database"
        db.write_bytes(original)
        with self.assertRaises(LocalDatabaseStateError) as caught:
            ensure_local_schema(db)
        self.assertEqual(caught.exception.code, "LOCAL_DB_UNREADABLE")
        self.assertEqual(db.read_bytes(), original)

    def test_alembic_cli_upgrades_empty_file_to_head(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        env = worker_env()
        env["KGM_LOCAL_DATA_DIR"] = str(self.data_dir)
        completed = subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "alembic-local.ini", "upgrade", "head"],
            cwd=str(BACKEND_DIR),
            env=env,
            capture_output=True,
            timeout=180,
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stderr.decode("utf-8", "replace"),
        )
        db = self.data_dir / "kindergarten.db"
        self.assertTrue(db.is_file())
        self.assertEqual(
            query_scalar(db, f"SELECT version_num FROM {LOCAL_VERSION_TABLE}"),
            head_revision(),
        )

    def test_pragmas_verified_on_every_pooled_connection(self):
        runtime = self.make_runtime()
        observed = []
        for _ in range(3):
            with runtime.engine.connect() as connection:
                raw = connection.connection.driver_connection
                observed.append(connection_settings(raw))
        for settings in observed:
            self.assertEqual(settings["foreign_keys"], 1)
            self.assertEqual(settings["busy_timeout"], 5000)
            self.assertEqual(settings["synchronous"], 2)  # FULL
            self.assertEqual(settings["journal_mode"], "wal")

    def test_foreign_keys_enforced_on_app_connections(self):
        runtime = self.make_runtime()
        with runtime.engine.connect() as connection:
            with self.assertRaises(IntegrityError):
                connection.exec_driver_sql(
                    "INSERT INTO local_operation_records "
                    "(id, created_at, actor_id, action, target_type, target_id, "
                    " target_version_after) VALUES "
                    "('missing-actor', '2026-01-01 00:00:00', 'no-such-profile', "
                    " 'x', 'y', 'z', NULL)"
                )

    def test_named_check_constraints_are_enforced(self):
        runtime = self.make_runtime()
        with runtime.engine.connect() as connection:
            with self.assertRaises(IntegrityError):
                # singleton CHECK is 1
                connection.exec_driver_sql(
                    "INSERT INTO local_profile "
                    "(id, singleton, display_name, created_at, updated_at) "
                    "VALUES ('singleton-2', 2, 'name', "
                    "'2026-01-01 00:00:00', '2026-01-01 00:00:00')"
                )
            connection.rollback()
            with self.assertRaises(IntegrityError):
                # name length CHECK is 1..80 (native length(), no trim trick)
                connection.exec_driver_sql(
                    "INSERT INTO local_classes "
                    "(id, name, grade, created_at, updated_at) "
                    "VALUES ('empty-name', '', 'middle', "
                    "'2026-01-01 00:00:00', '2026-01-01 00:00:00')"
                )
            connection.rollback()

    def test_app_factory_refuses_unmanageable_database(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        db = self.data_dir / "kindergarten.db"
        connection = sqlite3.connect(str(db))
        try:
            connection.execute("CREATE TABLE foreign_business (id INTEGER)")
            connection.commit()
        finally:
            connection.close()
        from app.local.app import create_local_app

        with self.assertRaises(LocalDatabaseStateError) as caught:
            create_local_app(
                port=12345, session_token="unused-token", data_dir=self.data_dir
            )
        self.assertEqual(caught.exception.code, "LOCAL_DB_NOT_MANAGED")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
