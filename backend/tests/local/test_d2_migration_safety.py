"""D2 W1 R02: cold-migration consistent backup, source revision and D1 summary.

Covers engineering spec §2.3: a known non-empty old revision must be backed up
(SQLite backup API, WAL included) with ``integrity_check`` / ``foreign_key_check``
/ unique revision verification, a real source revision in the manifest and an
exclusive manifest write; the pre-upgrade D1 logical summary (all old tables,
old columns and all rows, typed and order-independent) is captured from that
verified backup and re-checked inside the migration transaction (before
``run_migrations`` and again before ``COMMIT``). Unknown/newer revisions, a
missing backup, a failed manifest write and an occupied database all refuse the
upgrade and leave the source untouched.

Sources are built with **real Alembic** at 0001/0002/0003 (never by editing
``version_num`` or stamping); the seeds are written on each revision's own
schema. Every test root lives under ``%TEMP%/kgm-d2-w1-*`` and every runtime
gets an explicit synthetic ``credential_root``.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from alembic import command
from sqlalchemy import event

from app.local import d1_digest
from app.local import runtime as runtime_module
from app.local.errors import (
    LocalDatabaseStateError,
    LocalStorageError,
    LocalValidationError,
)
from app.local.migrate import (
    D1UpgradeGuard,
    alembic_config,
    ensure_local_schema,
    head_revision,
)
from app.local.runtime import LocalRuntime
from app.local.sqlite import LOCAL_VERSION_TABLE
from tests.local.support import (
    BACKEND_DIR,
    execute_sql,
    query_rows,
    query_scalar,
    sqlite_connect,
    wait_for_file,
    worker_env,
)

FIXTURE_MODULE = "tests.local.migration_fixture_worker"

SOURCE_REVISIONS = {
    "0001": "20261012_0001_local",
    "0002": "20261012_0002_local",
    "0003": "20261014_0003_local",
}

# Deterministic identities of the synthetic D1 dataset.
PROFILE_ID = "profile-d1-0000000000000000"
CLASS_ID = "class-d1-00000000000000000"
TERM_ID = "term-d1-0000000000000000000"
TERM2_ID = "term-d1-0000000000000000002"
REV_ID = "rev-d1-00000000000000000001"
REV2_ID = "rev-d1-00000000000000000002"
REV3_ID = "rev-d1-00000000000000000003"
PLAN_ID = "plan-d1-0000000000000000000"
CONTENT1_ID = "cont-d1-0000000000000000001"
CONTENT2_ID = "cont-d1-0000000000000000002"
CONTENT1_TEXT = "历史正文一"
CONTENT2_TEXT = "历史正文二"
OP1_ID = "oprec-d1-000000000000000001"
OP2_ID = "oprec-d1-000000000000000002"
WAL_ROW_ID = "oprec-d1-wal-00000000000001"


def _make_junction(link: Path, target: Path) -> None:
    """Create a real directory junction ``link`` -> ``target`` (target exists)."""
    target.mkdir(parents=True, exist_ok=True)
    if link.exists() or link.is_symlink() or link.is_junction():
        raise AssertionError(f"junction link already exists: {link}")
    completed = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "mklink /J failed rc=%d: %s"
            % (
                completed.returncode,
                completed.stderr.decode("utf-8", "replace"),
            )
        )
    if not link.is_junction():
        raise AssertionError(f"not a junction: {link}")


def _seed_d1(db: Path, revision: str) -> None:
    """Write a realistic D1 dataset on the revision's own schema.

    Uses raw SQL with foreign keys off, mirroring the reviewed D1 program's
    rows (single profile/class, two terms, a two-revision history, 30+ calendar
    days, a two-version daily plan with an old header and current pointer,
    settings and operation records). ``config_version = 4`` is only written on
    a 0003 source, where the column exists.
    """
    statements = [
        "INSERT INTO local_profile (id, singleton, display_name, created_at, "
        "updated_at) VALUES (?, 1, '王老师', '2026-10-12 00:00:00', "
        "'2026-10-12 00:00:00')",
        "INSERT INTO local_classes (id, name, grade, created_at, updated_at) "
        "VALUES (?, '中一班', 'middle', '2026-10-12 00:00:00', "
        "'2026-10-12 00:00:00')",
        "INSERT INTO local_terms (id, name, start_date, end_date, "
        "current_calendar_revision_id, created_at, updated_at) "
        "VALUES (?, '2026 年秋季学期', '2026-09-01', '2026-09-30', ?, "
        "'2026-10-12 00:00:00', '2026-10-12 00:00:00')",
        "INSERT INTO local_terms (id, name, start_date, end_date, "
        "current_calendar_revision_id, created_at, updated_at) "
        "VALUES (?, '2026 年春季学期', '2026-03-01', '2026-03-31', ?, "
        "'2026-10-12 00:00:00', '2026-10-12 00:00:00')",
        "INSERT INTO local_calendar_revisions (id, term_id, revision_no, "
        "library_version, created_by, created_at) VALUES (?, ?, 1, 'seed-v1', "
        "?, '2026-10-12 00:00:00')",
        "INSERT INTO local_calendar_revisions (id, term_id, revision_no, "
        "library_version, created_by, created_at) VALUES (?, ?, 2, 'seed-v2', "
        "?, '2026-10-12 00:00:00')",
        "INSERT INTO local_calendar_revisions (id, term_id, revision_no, "
        "library_version, created_by, created_at) VALUES (?, ?, 1, 'seed-v1', "
        "?, '2026-10-12 00:00:00')",
        "INSERT INTO local_settings (id, singleton, school_name, "
        "current_class_id, init_request_id, init_input_fingerprint, created_at, "
        "updated_at) VALUES ('singleton', 1, '示范幼儿园', ?, "
        "'00000000-0000-4000-8000-000000000001', ?, '2026-10-12 00:00:00', "
        "'2026-10-12 00:00:00')",
        "INSERT INTO local_daily_plans (id, class_id, term_id, plan_date, "
        "creator_id, week_number, weekday, calendar_revision_id, "
        "current_content_id, current_content_version, creator_display_name, "
        "school_name, class_name, grade, deleted_at, deleted_by, created_at, "
        "updated_at) VALUES (?, ?, ?, '2026-09-01', ?, 1, 2, ?, ?, 2, "
        "'王老师', '示范幼儿园', '中一班', 'middle', NULL, NULL, "
        "'2026-10-12 00:00:00', '2026-10-12 00:00:00')",
        "INSERT INTO local_daily_plan_contents (id, daily_plan_id, version, "
        "raw_lesson_plan, split_baseline, adopted_content, editor_id, "
        "created_at) VALUES (?, ?, 1, ?, NULL, '{}', ?, "
        "'2026-10-12 00:00:00')",
        "INSERT INTO local_daily_plan_contents (id, daily_plan_id, version, "
        "raw_lesson_plan, split_baseline, adopted_content, editor_id, "
        "created_at) VALUES (?, ?, 2, ?, NULL, '{}', ?, "
        "'2026-10-12 00:00:00')",
        "INSERT INTO local_operation_records (id, created_at, actor_id, "
        "action, target_type, target_id, target_version_after) VALUES (?, "
        "'2026-10-12 00:00:00', ?, 'create', 'daily_plan', ?, 2)",
        "INSERT INTO local_operation_records (id, created_at, actor_id, "
        "action, target_type, target_id, target_version_after) VALUES (?, "
        "'2026-10-12 01:00:00', ?, 'save', 'daily_plan', ?, 2)",
    ]
    params = [
        (PROFILE_ID,),
        (CLASS_ID,),
        (TERM_ID, REV2_ID),
        (TERM2_ID, REV3_ID),
        (REV_ID, TERM_ID, PROFILE_ID),
        (REV2_ID, TERM_ID, PROFILE_ID),
        (REV3_ID, TERM2_ID, PROFILE_ID),
        (CLASS_ID, "a" * 64),
        (
            PLAN_ID,
            CLASS_ID,
            TERM_ID,
            PROFILE_ID,
            REV2_ID,
            CONTENT2_ID,
        ),
        (CONTENT1_ID, PLAN_ID, CONTENT1_TEXT, PROFILE_ID),
        (CONTENT2_ID, PLAN_ID, CONTENT2_TEXT, PROFILE_ID),
        (OP1_ID, PROFILE_ID, PLAN_ID),
        (OP2_ID, PROFILE_ID, PLAN_ID),
    ]
    days = []
    day_params = []
    for day in range(1, 31):
        days.append(
            "INSERT INTO local_calendar_days (revision_id, date, base_state, "
            "base_library_version, override_state, override_reason, "
            "effective_state) VALUES (?, ?, 'teaching', 'seed-v1', NULL, "
            "NULL, 'teaching')"
        )
        day_params.append((REV_ID, f"2026-09-{day:02d}"))
    for day in (1, 2):
        days.append(
            "INSERT INTO local_calendar_days (revision_id, date, base_state, "
            "base_library_version, override_state, override_reason, "
            "effective_state) VALUES (?, ?, 'teaching', 'seed-v2', NULL, "
            "NULL, 'teaching')"
        )
        day_params.append((REV2_ID, f"2026-09-{day:02d}"))
    for day in (1, 2):
        days.append(
            "INSERT INTO local_calendar_days (revision_id, date, base_state, "
            "base_library_version, override_state, override_reason, "
            "effective_state) VALUES (?, ?, 'teaching', 'seed-v1', NULL, "
            "NULL, 'teaching')"
        )
        day_params.append((REV3_ID, f"2026-03-{day:02d}"))

    connection = sqlite3.connect(str(db))
    try:
        connection.execute("PRAGMA foreign_keys=OFF")
        for statement, values in zip(statements, params, strict=True):
            connection.execute(statement, values)
        for statement, values in zip(days, day_params, strict=True):
            connection.execute(statement, values)
        if revision == SOURCE_REVISIONS["0003"]:
            connection.execute(
                "UPDATE local_settings SET config_version = 4"
            )
        connection.commit()
    finally:
        connection.close()


def _table_names(db: Path) -> set[str]:
    return {
        row["name"]
        for row in query_rows(
            db, "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }


def _backups(data_dir: Path) -> list[Path]:
    backup_dir = data_dir / "migration-backups"
    if not backup_dir.is_dir():
        return []
    return sorted(backup_dir.glob("pre-D2-*.sqlite"))


def _manifest_for(backup: Path) -> dict:
    manifest_path = backup.with_suffix(".manifest.json")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _d1_snapshot(db: Path) -> tuple[dict, str]:
    connection = sqlite3.connect(str(db))
    try:
        schema = d1_digest.capture_schema(connection)
        return schema, d1_digest.digest(connection, schema)
    finally:
        connection.close()


def _digest_with_schema(db: Path, schema: dict) -> str:
    """Digest only the captured (pre-upgrade) tables/columns of ``db``."""
    connection = sqlite3.connect(str(db))
    try:
        return d1_digest.digest(connection, schema)
    finally:
        connection.close()


def _cause_messages(exc: BaseException) -> list[str]:
    """Collect messages along the exception ``__cause__``/``__context__`` chain."""
    messages: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        messages.append(getattr(current, "message", None) or str(current))
        current = current.__cause__ or current.__context__
    return messages


class _TamperGuard(D1UpgradeGuard):
    """Simulate a migration that alters an existing D1 row (must be caught)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fired = False

    def after_migrations(self, connection) -> None:  # noqa: ANN001
        connection.exec_driver_sql(
            "UPDATE local_profile SET display_name = '被篡改'"
        )
        self.fired = True
        super().after_migrations(connection)


class _PreCommitFaultGuard(D1UpgradeGuard):
    """Inject a failure after ``run_migrations`` but before ``COMMIT``."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fired = False

    def after_migrations(self, connection) -> None:  # noqa: ANN001
        self.fired = True
        raise RuntimeError("injected failure before COMMIT")


class _RecordingGuard(D1UpgradeGuard):
    """Record that ``before_migrations`` was actually entered."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.entered = False

    def before_migrations(self, connection) -> None:  # noqa: ANN001
        self.entered = True
        super().before_migrations(connection)


class _StatementFaultGuard(D1UpgradeGuard):
    """Inject a failure on a matching statement inside the migration txn."""

    def __init__(self, *args, needle: str, **kwargs):
        super().__init__(*args, **kwargs)
        self._needle = needle
        self._listener = None
        self.fired = False

    def before_migrations(self, connection) -> None:  # noqa: ANN001
        super().before_migrations(connection)
        target_engine = connection.engine

        def _fail(conn, cursor, statement, parameters, context, executemany):
            if self._needle in " ".join(statement.split()):
                self.fired = True
                raise RuntimeError(f"injected failure at: {self._needle}")

        event.listen(target_engine, "before_cursor_execute", _fail)
        self._listener = (target_engine, _fail)

    def after_migrations(self, connection) -> None:  # noqa: ANN001
        if self._listener is not None:
            try:
                event.remove(*self._listener)
            except Exception:  # noqa: BLE001 - best-effort listener cleanup
                pass
            self._listener = None
        super().after_migrations(connection)


class _SchemaChangeGuard(D1UpgradeGuard):
    """Simulate a migration that renames/drops an existing D1 column.

    ``fired`` is set only after the DDL actually executed *and* the target
    column is confirmed absent in the live schema, so a DDL that SQLite itself
    rejected can never be mistaken for the digest protection passing.
    """

    def __init__(self, *args, statement: str, table: str, absent_column: str, **kwargs):
        super().__init__(*args, **kwargs)
        self._statement = statement
        self._table = table
        self._absent_column = absent_column
        self.fired = False

    def after_migrations(self, connection) -> None:  # noqa: ANN001
        connection.exec_driver_sql(self._statement)
        live = {
            row[1]
            for row in connection.exec_driver_sql(
                f'PRAGMA table_info("{self._table}")'
            ).fetchall()
        }
        if self._absent_column in live:
            raise AssertionError("injected DDL did not remove the column")
        self.fired = True
        super().after_migrations(connection)


class _D2MigrationSafetyCase(unittest.TestCase):
    """Synthetic ``%TEMP%/kgm-d2-w1-*`` root with explicit credential roots."""

    def setUp(self) -> None:
        super().setUp()
        self._root = Path(
            tempfile.mkdtemp(prefix="kgm-d2-w1-", dir=Path(tempfile.gettempdir()))
        )
        self.addCleanup(shutil.rmtree, self._root, ignore_errors=True)
        self._junctions: list[Path] = []
        self.addCleanup(self._remove_junctions)
        self._runtimes: list[LocalRuntime] = []
        self.addCleanup(self._dispose_runtimes)
        self._processes: list[subprocess.Popen] = []
        self.addCleanup(self._reap_processes)

    # -- cleanup ----------------------------------------------------------
    def _remove_junctions(self) -> None:
        for link in reversed(self._junctions):
            try:
                os.rmdir(link)
            except OSError:
                pass

    def _dispose_runtimes(self) -> None:
        for runtime in reversed(self._runtimes):
            try:
                runtime.dispose()
            except Exception:  # noqa: BLE001 - cleanup must not mask failures
                pass

    def _reap_processes(self) -> None:
        for process in self._processes:
            if process.poll() is None:
                process.kill()
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:  # pragma: no cover - defensive
                process.kill()
                process.wait(timeout=30)
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass

    # -- fixtures ---------------------------------------------------------
    def _cred_root(self) -> Path:
        return self._root / "credentials"

    def _runtime(self, data_dir: Path) -> LocalRuntime:
        runtime = LocalRuntime(data_dir, credential_root=self._cred_root())
        self._runtimes.append(runtime)
        return runtime

    def _junction(self, link: Path, target: Path) -> Path:
        _make_junction(link, target)
        self._junctions.append(link)
        return link

    def _prepare_source(self, revision_key: str) -> tuple[Path, Path]:
        data_dir = self._root / f"src-{revision_key}-{secrets.token_hex(4)}"
        data_dir.mkdir(parents=True, exist_ok=True)
        db = data_dir / "kindergarten.db"
        command.upgrade(alembic_config(db), SOURCE_REVISIONS[revision_key])
        self.assertEqual(
            query_scalar(db, f"SELECT version_num FROM {LOCAL_VERSION_TABLE}"),
            SOURCE_REVISIONS[revision_key],
        )
        _seed_d1(db, SOURCE_REVISIONS[revision_key])
        self.assertEqual(query_rows(db, "PRAGMA foreign_key_check"), [])
        return data_dir, db

    def _spawn_fixture(self, spec: dict) -> subprocess.Popen:
        input_file = Path(spec["input_file"])
        input_file.write_text(
            json.dumps(spec, ensure_ascii=False, default=str), encoding="utf-8"
        )
        process = subprocess.Popen(
            [sys.executable, "-m", FIXTURE_MODULE, str(input_file)],
            cwd=str(BACKEND_DIR),
            env=worker_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._processes.append(process)
        return process

    def _fixture_paths(self, name: str) -> dict:
        return {
            "input_file": str(self._root / f"{name}.in.json"),
            "result_file": str(self._root / f"{name}.out.json"),
            "ready_file": str(self._root / f"{name}.ready"),
            "release_file": str(self._root / f"{name}.release"),
        }


class D1DigestUnitTests(unittest.TestCase):
    """The logical summary is type-safe, order-independent and excludes D2."""

    def _typed_digest(self, order: list) -> str:
        connection = sqlite3.connect(":memory:")
        try:
            connection.execute("CREATE TABLE t (a)")
            connection.executemany(
                "INSERT INTO t (a) VALUES (?)", [(value,) for value in order]
            )
            return d1_digest.digest(connection, {"t": ("a",)})
        finally:
            connection.close()

    def test_digest_is_order_independent(self):
        self.assertEqual(
            self._typed_digest([None, 0, "", b"", "0"]),
            self._typed_digest(["0", b"", "", 0, None]),
        )

    def test_digest_distinguishes_types_and_values(self):
        self.assertNotEqual(self._typed_digest([0]), self._typed_digest(["0"]))
        self.assertNotEqual(self._typed_digest([0]), self._typed_digest([0.0]))
        self.assertNotEqual(self._typed_digest([None]), self._typed_digest([""]))
        self.assertNotEqual(self._typed_digest([b""]), self._typed_digest([""]))
        self.assertNotEqual(
            self._typed_digest(["历史"]), self._typed_digest(["历 史"])
        )

    def test_capture_schema_excludes_version_table(self):
        connection = sqlite3.connect(":memory:")
        try:
            connection.execute(f"CREATE TABLE {LOCAL_VERSION_TABLE} (v)")
            connection.execute("CREATE TABLE t (a, b)")
            schema = d1_digest.capture_schema(connection)
        finally:
            connection.close()
        self.assertEqual(schema, {"t": ("a", "b")})

    def test_digest_refuses_renamed_or_missing_column(self):
        connection = sqlite3.connect(":memory:")
        try:
            # Codex reproduction: DQS would read a renamed column as the
            # string literal 'name' and keep the digest equal.
            connection.execute("CREATE TABLE local_classes (id, name)")
            connection.execute(
                "INSERT INTO local_classes (id, name) VALUES ('class-1', 'name')"
            )
            schema = d1_digest.capture_schema(connection)
            self.assertEqual(schema["local_classes"], ("id", "name"))
            first = d1_digest.digest(connection, schema)
            connection.execute(
                "ALTER TABLE local_classes RENAME COLUMN name TO renamed_name"
            )
            with self.assertRaises(d1_digest.DigestSchemaError):
                d1_digest.digest(connection, schema)
            # A renamed-back column digests equal again (value unchanged).
            connection.execute(
                "ALTER TABLE local_classes RENAME COLUMN renamed_name TO name"
            )
            self.assertEqual(d1_digest.digest(connection, schema), first)
        finally:
            connection.close()

    def test_digest_refuses_missing_table(self):
        connection = sqlite3.connect(":memory:")
        try:
            connection.execute("CREATE TABLE t (a)")
            schema = d1_digest.capture_schema(connection)
            connection.execute("DROP TABLE t")
            with self.assertRaises(d1_digest.DigestSchemaError):
                d1_digest.digest(connection, schema)
        finally:
            connection.close()

    def test_digest_ignores_added_columns(self):
        connection = sqlite3.connect(":memory:")
        try:
            connection.execute("CREATE TABLE t (a)")
            connection.execute("INSERT INTO t (a) VALUES ('x')")
            schema = d1_digest.capture_schema(connection)
            before = d1_digest.digest(connection, schema)
            connection.execute("ALTER TABLE t ADD COLUMN b TEXT")
            self.assertEqual(d1_digest.digest(connection, schema), before)
        finally:
            connection.close()

    def test_single_revision_requires_exactly_one_row(self):
        connection = sqlite3.connect(":memory:")
        try:
            connection.execute(
                f"CREATE TABLE {LOCAL_VERSION_TABLE} (version_num)"
            )
            self.assertIsNone(d1_digest.single_revision(connection))
            connection.execute(
                f"INSERT INTO {LOCAL_VERSION_TABLE} (version_num) VALUES ('a')"
            )
            self.assertEqual(d1_digest.single_revision(connection), "a")
            connection.execute(
                f"INSERT INTO {LOCAL_VERSION_TABLE} (version_num) VALUES ('b')"
            )
            self.assertIsNone(d1_digest.single_revision(connection))
        finally:
            connection.close()


class ColdUpgradeBackupTests(_D2MigrationSafetyCase):
    def test_0003_upgrade_backs_up_with_source_revision_and_keeps_d1(self):
        data_dir, db = self._prepare_source("0003")
        schema, before = _d1_snapshot(db)
        # Point the pointer at the newest content version to prove the current
        # D1 pointer/header survives.
        self.assertEqual(
            query_scalar(db, "SELECT current_content_version FROM local_daily_plans"),
            2,
        )

        runtime = self._runtime(data_dir)
        inspection = runtime.prepare()
        self.assertEqual(inspection.state, "current")
        self.assertEqual(inspection.current_revision, head_revision())

        backups = _backups(data_dir)
        self.assertEqual(len(backups), 1, backups)
        manifest = _manifest_for(backups[0])
        self.assertEqual(manifest["version"], SOURCE_REVISIONS["0003"])
        self.assertEqual(manifest["utc"], backups[0].name.split("-")[2])
        self.assertEqual(
            manifest["sha256"],
            hashlib.sha256(backups[0].read_bytes()).hexdigest(),
        )

        # Old D1 tables/columns/rows are logically unchanged (same summary over
        # the schema captured before the upgrade; D2 additions are excluded).
        self.assertEqual(_digest_with_schema(db, schema), before)
        self.assertEqual(
            query_scalar(db, "SELECT config_version FROM local_settings"), 4
        )
        self.assertEqual(
            query_scalar(
                db,
                "SELECT raw_lesson_plan FROM local_daily_plan_contents "
                "WHERE version = 2",
            ),
            CONTENT2_TEXT,
        )
        self.assertEqual(
            query_scalar(db, "SELECT count(*) FROM local_calendar_days"), 34
        )
        self.assertEqual(
            query_scalar(db, "SELECT count(*) FROM local_terms"), 2
        )
        self.assertEqual(
            query_scalar(db, "SELECT count(*) FROM local_calendar_revisions"), 3
        )

        # Repeat start at head: no new backup, no version/seed/UUID growth.
        state_before = query_rows(db, "SELECT * FROM local_ai_state")
        prompt_before = query_scalar(
            db, "SELECT count(*) FROM local_personal_prompt_heads"
        )
        runtime.dispose()
        again = self._runtime(data_dir)
        again.prepare()
        self.assertEqual(len(_backups(data_dir)), 1)
        self.assertEqual(query_rows(db, "SELECT * FROM local_ai_state"), state_before)
        self.assertEqual(
            query_scalar(db, "SELECT count(*) FROM local_personal_prompt_heads"),
            prompt_before,
        )

    def test_backup_includes_committed_wal_frames(self):
        data_dir, db = self._prepare_source("0003")
        paths = self._fixture_paths("wal")
        spec = {
            "action": "wal_commit_exit",
            "db_path": str(db),
            "statements": [
                (
                    "INSERT INTO local_operation_records (id, created_at, "
                    "actor_id, action, target_type, target_id, "
                    "target_version_after) VALUES (?, '2026-10-12 02:00:00', ?, "
                    "'save', 'daily_plan', ?, 2)",
                    [WAL_ROW_ID, PROFILE_ID, PLAN_ID],
                )
            ],
            **paths,
        }
        process = self._spawn_fixture(spec)
        stdout, stderr = process.communicate(timeout=120)
        self.assertEqual(
            process.returncode, 0, stderr.decode("utf-8", "replace")
        )
        result = json.loads(Path(paths["result_file"]).read_text("utf-8"))
        self.assertEqual(result["state"], "committed")
        wal = db.with_name(db.name + "-wal")
        self.assertTrue(wal.is_file() and wal.stat().st_size > 0, wal)

        runtime = self._runtime(data_dir)
        runtime.prepare()
        backup = _backups(data_dir)[0]
        # If the WAL frame were not copied, the guard would have refused the
        # upgrade; assert it is present in both the backup and the live file.
        self.assertEqual(
            query_scalar(
                backup,
                "SELECT count(*) FROM local_operation_records WHERE id = ?",
                (WAL_ROW_ID,),
            ),
            1,
        )
        self.assertEqual(
            query_scalar(
                db,
                "SELECT count(*) FROM local_operation_records WHERE id = ?",
                (WAL_ROW_ID,),
            ),
            1,
        )

    def test_backup_revision_mismatch_refuses_and_keeps_backup(self):
        data_dir, db = self._prepare_source("0003")
        runtime = self._runtime(data_dir)
        with self.assertRaises(LocalStorageError):
            runtime.backup_before_migration("20990101_9999_bogus")
        # The generated (but unverified) backup is kept; the source is intact
        # and no D2 table was created.
        self.assertEqual(len(_backups(data_dir)), 1)
        self.assertEqual(
            query_scalar(db, f"SELECT version_num FROM {LOCAL_VERSION_TABLE}"),
            SOURCE_REVISIONS["0003"],
        )
        self.assertNotIn("local_ai_state", _table_names(db))

    def test_backup_write_failure_refuses_upgrade(self):
        data_dir, db = self._prepare_source("0003")
        runtime = self._runtime(data_dir)
        with patch.object(
            runtime,
            "_write_sqlite_backup",
            side_effect=LocalStorageError("injected backup failure"),
        ):
            with self.assertRaises(LocalStorageError):
                runtime.prepare()
        self.assertFalse(runtime.prepared)
        self.assertEqual(len(_backups(data_dir)), 1)
        self.assertEqual(
            query_scalar(db, f"SELECT version_num FROM {LOCAL_VERSION_TABLE}"),
            SOURCE_REVISIONS["0003"],
        )
        self.assertNotIn("local_ai_state", _table_names(db))
        # The failed attempt released the lock: a fresh runtime can prepare.
        recovered = self._runtime(data_dir)
        recovered.prepare()
        self.assertTrue(recovered.prepared)

    def test_manifest_write_failure_refuses_upgrade(self):
        data_dir, db = self._prepare_source("0003")
        runtime = self._runtime(data_dir)
        with patch.object(
            runtime_module,
            "_write_exclusive_bytes",
            side_effect=LocalStorageError("injected manifest failure"),
        ):
            with self.assertRaises(LocalStorageError):
                runtime.prepare()
        self.assertFalse(runtime.prepared)
        self.assertEqual(
            query_scalar(db, f"SELECT version_num FROM {LOCAL_VERSION_TABLE}"),
            SOURCE_REVISIONS["0003"],
        )
        self.assertNotIn("local_ai_state", _table_names(db))
        self.assertTrue(_backups(data_dir), "backup must be kept on failure")

    def test_manifest_partial_writes_are_completed(self):
        """A helper that only ever writes 1 byte per call must still finish.

        Real short writes (``os.write`` returning less than requested) are
        advanced through the loop, so the manifest ends up complete and the
        upgrade proceeds.
        """
        data_dir, _db = self._prepare_source("0003")
        runtime = self._runtime(data_dir)
        real_write_fd = runtime_module._write_fd
        calls = {"n": 0, "max": 0}

        def one_byte(handle, data):
            calls["n"] += 1
            chunk = bytes(data[:1])
            calls["max"] = max(calls["max"], len(data))
            return real_write_fd(handle, chunk)

        with patch.object(runtime_module, "_write_fd", one_byte):
            runtime.prepare()
        self.assertTrue(runtime.prepared)
        # Many short writes were needed: the loop really ran repeatedly.
        self.assertGreater(calls["n"], 1, calls)
        backup = _backups(data_dir)[0]
        manifest = _manifest_for(backup)
        self.assertEqual(manifest["version"], SOURCE_REVISIONS["0003"])
        self.assertEqual(
            manifest["sha256"], hashlib.sha256(backup.read_bytes()).hexdigest()
        )
        # The upgrade completed: D2 tables are present.
        self.assertIn("local_ai_state", _table_names(_db))

    def test_manifest_zero_progress_write_refuses(self):
        """A write that accepts 0 bytes must refuse, not spin or truncate."""
        data_dir, db = self._prepare_source("0003")
        runtime = self._runtime(data_dir)
        calls = {"n": 0}

        def zero_progress(handle, data):
            calls["n"] += 1
            return 0

        with patch.object(runtime_module, "_write_fd", zero_progress):
            with self.assertRaises(LocalStorageError) as caught:
                runtime.prepare()
        self.assertEqual(caught.exception.code, "LOCAL_STORAGE_ERROR")
        self.assertEqual(calls["n"], 1, "the injection must fire exactly once")
        self.assertFalse(runtime.prepared)
        self.assertEqual(
            query_scalar(db, f"SELECT version_num FROM {LOCAL_VERSION_TABLE}"),
            SOURCE_REVISIONS["0003"],
        )
        self.assertNotIn("local_ai_state", _table_names(db))
        # The generated backup and the (empty) reserved manifest are kept as
        # the failure fact, not silently removed.
        self.assertEqual(len(_backups(data_dir)), 1)
        manifest_path = _backups(data_dir)[0].with_suffix(".manifest.json")
        self.assertTrue(manifest_path.is_file())
        self.assertEqual(manifest_path.stat().st_size, 0)
        # The lock was released: a fresh runtime completes the upgrade.
        recovered = self._runtime(data_dir)
        recovered.prepare()
        self.assertTrue(recovered.prepared)

    def test_manifest_fsync_failure_refuses(self):
        """An fsync that fails must refuse even though all bytes were written."""
        data_dir, db = self._prepare_source("0003")
        runtime = self._runtime(data_dir)
        calls = {"n": 0}

        def failing_fsync(handle):
            calls["n"] += 1
            raise OSError(5, "injected fsync failure")

        with patch.object(runtime_module, "_fsync_fd", failing_fsync):
            with self.assertRaises(LocalStorageError) as caught:
                runtime.prepare()
        self.assertEqual(caught.exception.code, "LOCAL_STORAGE_ERROR")
        self.assertIsInstance(caught.exception.__cause__, OSError)
        self.assertEqual(calls["n"], 1, "fsync injection must fire exactly once")
        self.assertFalse(runtime.prepared)
        self.assertEqual(
            query_scalar(db, f"SELECT version_num FROM {LOCAL_VERSION_TABLE}"),
            SOURCE_REVISIONS["0003"],
        )
        self.assertNotIn("local_ai_state", _table_names(db))
        self.assertTrue(_backups(data_dir), "backup must be kept on refusal")
        # Full bytes were written before fsync failed; the source is still on
        # the old revision, so the unflushed manifest was never trusted.
        manifest_path = _backups(data_dir)[0].with_suffix(".manifest.json")
        self.assertTrue(manifest_path.is_file())
        # The lock was released: a fresh runtime completes the upgrade.
        recovered = self._runtime(data_dir)
        recovered.prepare()
        self.assertTrue(recovered.prepared)

    def test_same_utc_multiple_backups_do_not_overwrite(self):
        data_dir, _db = self._prepare_source("0003")
        runtime = self._runtime(data_dir)
        with patch.object(
            runtime_module,
            "_backup_timestamp",
            return_value="20261018T000000Z",
        ), patch.object(
            runtime_module,
            "_unique_token",
            side_effect=["b" * 16, "c" * 16],
        ):
            first = runtime.backup_before_migration(SOURCE_REVISIONS["0003"])
            second = runtime.backup_before_migration(SOURCE_REVISIONS["0003"])
        self.assertNotEqual(first, second)
        self.assertTrue(first.is_file() and second.is_file())
        backups = _backups(data_dir)
        self.assertEqual(len(backups), 2, backups)

    def test_target_collision_does_not_overwrite(self):
        data_dir, _db = self._prepare_source("0003")
        runtime = self._runtime(data_dir)
        with patch.object(
            runtime_module,
            "_backup_timestamp",
            return_value="20261018T000000Z",
        ), patch.object(
            runtime_module,
            "_unique_token",
            side_effect=["d" * 16, "d" * 16],
        ):
            first = runtime.backup_before_migration(SOURCE_REVISIONS["0003"])
            first_bytes = first.read_bytes()
            with self.assertRaises(LocalStorageError):
                runtime.backup_before_migration(SOURCE_REVISIONS["0003"])
        self.assertEqual(len(_backups(data_dir)), 1)
        self.assertEqual(first.read_bytes(), first_bytes)

    def test_backup_hash_read_failure_maps_to_storage_error(self):
        data_dir, db = self._prepare_source("0003")
        runtime = self._runtime(data_dir)
        real_read_bytes = Path.read_bytes

        def failing_read_bytes(self_path: Path) -> bytes:
            if self_path.name.startswith("pre-D2-") and self_path.suffix == ".sqlite":
                raise OSError(5, "injected hash read failure")
            return real_read_bytes(self_path)

        with patch.object(Path, "read_bytes", failing_read_bytes):
            with self.assertRaises(LocalStorageError) as caught:
                runtime.prepare()
        self.assertEqual(caught.exception.code, "LOCAL_STORAGE_ERROR")
        self.assertIsInstance(caught.exception.__cause__, OSError)
        self.assertFalse(runtime.prepared)
        self.assertTrue(_backups(data_dir), "backup must be kept on failure")
        self.assertEqual(
            query_scalar(db, f"SELECT version_num FROM {LOCAL_VERSION_TABLE}"),
            SOURCE_REVISIONS["0003"],
        )
        self.assertNotIn("local_ai_state", _table_names(db))
        # The failed attempt released the lock: a fresh runtime can prepare.
        recovered = self._runtime(data_dir)
        recovered.prepare()
        self.assertTrue(recovered.prepared)

    def test_guard_build_failure_maps_to_storage_error(self):
        data_dir, db = self._prepare_source("0003")
        runtime = self._runtime(data_dir)
        with patch.object(
            d1_digest,
            "capture_schema",
            side_effect=sqlite3.OperationalError("injected backup read failure"),
        ):
            with self.assertRaises(LocalStorageError) as caught:
                runtime.prepare()
        self.assertEqual(caught.exception.code, "LOCAL_STORAGE_ERROR")
        self.assertIsInstance(caught.exception.__cause__, sqlite3.Error)
        self.assertFalse(runtime.prepared)
        self.assertTrue(_backups(data_dir))
        self.assertEqual(
            query_scalar(db, f"SELECT version_num FROM {LOCAL_VERSION_TABLE}"),
            SOURCE_REVISIONS["0003"],
        )
        self.assertNotIn("local_ai_state", _table_names(db))
        recovered = self._runtime(data_dir)
        recovered.prepare()
        self.assertTrue(recovered.prepared)

    def test_postcommit_verification_failure_refuses_startup_without_rollback(self):
        data_dir, db = self._prepare_source("0003")
        runtime = self._runtime(data_dir)
        with patch.object(
            runtime_module,
            "head_revision",
            side_effect=OSError("injected post-commit failure"),
        ):
            with self.assertRaises(LocalStorageError) as caught:
                runtime.prepare()
        self.assertEqual(caught.exception.code, "LOCAL_STORAGE_ERROR")
        self.assertIsInstance(caught.exception.__cause__, OSError)
        self.assertFalse(runtime.prepared)
        # The already committed upgrade is preserved, not rolled back.
        self.assertEqual(
            query_scalar(db, f"SELECT version_num FROM {LOCAL_VERSION_TABLE}"),
            head_revision(),
        )
        self.assertIn("local_ai_state", _table_names(db))
        # The failed attempt released the lock; a fresh runtime opens the
        # committed database at head.
        recovered = self._runtime(data_dir)
        recovered.prepare()
        self.assertTrue(recovered.prepared)
        self.assertEqual(recovered._inspection.state, "current")

    def test_no_backup_for_fresh_empty_or_refused_revision(self):
        # A fresh empty database is baselined with no pre-D2 backup.
        fresh_dir = self._root / "fresh-empty"
        fresh = self._runtime(fresh_dir)
        fresh.prepare()
        self.assertEqual(_backups(fresh_dir), [])

        # Both an unknown/newer revision and a multi-row state are refused
        # before any backup is written.
        for label, statements in {
            "unknown": (
                f"UPDATE {LOCAL_VERSION_TABLE} SET version_num = "
                "'20990101_9999_future'",
            ),
            "multi_row": (
                f"INSERT INTO {LOCAL_VERSION_TABLE} (version_num) VALUES "
                f"('{SOURCE_REVISIONS['0002']}')",
            ),
        }.items():
            with self.subTest(case=label):
                data_dir, db = self._prepare_source("0003")
                for statement in statements:
                    execute_sql(db, statement)
                runtime = self._runtime(data_dir)
                with self.assertRaises(LocalDatabaseStateError) as caught:
                    runtime.prepare()
                self.assertEqual(
                    caught.exception.code, "LOCAL_DB_VERSION_UNSUPPORTED"
                )
                self.assertEqual(_backups(data_dir), [])
                self.assertNotIn("local_ai_state", _table_names(db))

    def test_backup_dir_junction_is_rejected(self):
        data_dir, db = self._prepare_source("0003")
        target = self._root / "elsewhere"
        self._junction(data_dir / "migration-backups", target)
        runtime = self._runtime(data_dir)
        with self.assertRaises(LocalValidationError):
            runtime.prepare()
        self.assertEqual(
            query_scalar(db, f"SELECT version_num FROM {LOCAL_VERSION_TABLE}"),
            SOURCE_REVISIONS["0003"],
        )
        self.assertNotIn("local_ai_state", _table_names(db))
        self.assertEqual(list(target.iterdir()), [])


class D1SummaryTransactionTests(_D2MigrationSafetyCase):
    def _backup_and_guard(self, runtime: LocalRuntime) -> D1UpgradeGuard:
        backup = runtime.backup_before_migration(SOURCE_REVISIONS["0003"])
        return runtime._build_upgrade_guard(backup, SOURCE_REVISIONS["0003"])

    def _backup_schema_digest(self, backup: Path) -> tuple[dict, str]:
        connection = sqlite3.connect(str(backup))
        try:
            schema = d1_digest.capture_schema(connection)
            return schema, d1_digest.digest(connection, schema)
        finally:
            connection.close()

    def test_source_change_between_backup_and_transaction_is_detected(self):
        data_dir, db = self._prepare_source("0003")
        runtime = self._runtime(data_dir)
        backup = runtime.backup_before_migration(SOURCE_REVISIONS["0003"])
        guard = _RecordingGuard(
            SOURCE_REVISIONS["0003"], *self._backup_schema_digest(backup)
        )
        connection = sqlite_connect(db)
        try:
            connection.execute(
                "UPDATE local_profile SET display_name = '事后修改'"
            )
            connection.commit()
        finally:
            connection.close()
        with self.assertRaises(LocalDatabaseStateError) as caught:
            ensure_local_schema(db, d1_guard=guard)
        self.assertEqual(caught.exception.code, "LOCAL_DB_MIGRATION_FAILED")
        # The guard really ran and the failure came from the digest check
        # (the revision is unchanged, so it is not the revision check).
        self.assertTrue(guard.entered, "before_migrations was not entered")
        messages = _cause_messages(caught.exception)
        self.assertTrue(
            any("摘要与备份不一致" in message for message in messages),
            messages,
        )
        # Whole transaction rolled back: revision and schema unchanged, and the
        # out-of-band change (the source's new fact) is preserved, not restored.
        self.assertEqual(
            query_scalar(db, f"SELECT version_num FROM {LOCAL_VERSION_TABLE}"),
            SOURCE_REVISIONS["0003"],
        )
        self.assertNotIn("local_ai_state", _table_names(db))
        self.assertEqual(
            query_scalar(db, "SELECT display_name FROM local_profile"),
            "事后修改",
        )

    def test_tampered_d1_row_during_migration_triggers_rollback(self):
        data_dir, db = self._prepare_source("0003")
        runtime = self._runtime(data_dir)
        original = self._backup_and_guard(runtime)
        tamper = _TamperGuard(
            original.source_revision, original.schema, original.expected_digest
        )
        with self.assertRaises(LocalDatabaseStateError) as caught:
            ensure_local_schema(db, d1_guard=tamper)
        self.assertEqual(caught.exception.code, "LOCAL_DB_MIGRATION_FAILED")
        self.assertTrue(tamper.fired, "the D1 row tamper did not execute")
        messages = _cause_messages(caught.exception)
        self.assertTrue(
            any("摘要发生变化" in message for message in messages), messages
        )
        self.assertEqual(
            query_scalar(db, f"SELECT version_num FROM {LOCAL_VERSION_TABLE}"),
            SOURCE_REVISIONS["0003"],
        )
        self.assertNotIn("local_ai_state", _table_names(db))
        # The in-transaction UPDATE was rolled back.
        self.assertEqual(
            query_scalar(db, "SELECT display_name FROM local_profile"), "王老师"
        )

    def test_statement_injection_rolls_back_at_build_and_seed(self):
        needles = (
            "CREATE TABLE local_ai_credentials",
            "INSERT INTO local_prompt_bundles",
        )
        for needle in needles:
            with self.subTest(needle=needle):
                data_dir, db = self._prepare_source("0003")
                runtime = self._runtime(data_dir)
                tables_before = _table_names(db)
                _, digest_before = _d1_snapshot(db)
                original = self._backup_and_guard(runtime)
                fault = _StatementFaultGuard(
                    original.source_revision,
                    original.schema,
                    original.expected_digest,
                    needle=needle,
                )
                with self.assertRaises(LocalDatabaseStateError) as caught:
                    ensure_local_schema(db, d1_guard=fault)
                self.assertEqual(
                    caught.exception.code, "LOCAL_DB_MIGRATION_FAILED"
                )
                self.assertTrue(
                    fault.fired, f"statement injection did not fire: {needle}"
                )
                messages = _cause_messages(caught.exception)
                self.assertTrue(
                    any(needle in message for message in messages), messages
                )
                self.assertEqual(_table_names(db), tables_before)
                self.assertEqual(_d1_snapshot(db)[1], digest_before)
                self.assertEqual(
                    query_scalar(
                        db, f"SELECT version_num FROM {LOCAL_VERSION_TABLE}"
                    ),
                    SOURCE_REVISIONS["0003"],
                )

    def test_precommit_fault_rolls_back(self):
        data_dir, db = self._prepare_source("0003")
        runtime = self._runtime(data_dir)
        original = self._backup_and_guard(runtime)
        fault = _PreCommitFaultGuard(
            original.source_revision, original.schema, original.expected_digest
        )
        with self.assertRaises(LocalDatabaseStateError) as caught:
            ensure_local_schema(db, d1_guard=fault)
        self.assertEqual(caught.exception.code, "LOCAL_DB_MIGRATION_FAILED")
        self.assertTrue(fault.fired, "pre-COMMIT injection did not run")
        messages = _cause_messages(caught.exception)
        self.assertTrue(
            any("injected failure before COMMIT" in message for message in messages),
            messages,
        )
        self.assertEqual(
            query_scalar(db, f"SELECT version_num FROM {LOCAL_VERSION_TABLE}"),
            SOURCE_REVISIONS["0003"],
        )
        self.assertNotIn("local_ai_state", _table_names(db))

    def test_in_transaction_old_column_rename_and_drop_roll_back(self):
        cases = {
            "rename": (
                "ALTER TABLE local_classes RENAME COLUMN name TO renamed_name",
                "local_classes",
                "name",
                "renamed_name",
            ),
            "drop": (
                "ALTER TABLE local_calendar_revisions "
                "DROP COLUMN library_version",
                "local_calendar_revisions",
                "library_version",
                None,
            ),
        }
        for label, (statement, table, changed, gone) in cases.items():
            with self.subTest(change=label):
                data_dir, db = self._prepare_source("0003")
                runtime = self._runtime(data_dir)
                tables_before = _table_names(db)
                _, digest_before = _d1_snapshot(db)
                original = self._backup_and_guard(runtime)
                fault = _SchemaChangeGuard(
                    original.source_revision,
                    original.schema,
                    original.expected_digest,
                    statement=statement,
                    table=table,
                    absent_column=changed,
                )
                with self.assertRaises(LocalDatabaseStateError) as caught:
                    ensure_local_schema(db, d1_guard=fault)
                self.assertEqual(
                    caught.exception.code, "LOCAL_DB_MIGRATION_FAILED"
                )
                # fired is set only after the DDL ran AND removed the column,
                # so a SQLite-rejected DROP can never masquerade as a pass.
                self.assertTrue(
                    fault.fired, f"injected DDL did not take effect: {label}"
                )
                messages = _cause_messages(caught.exception)
                self.assertTrue(
                    any("表/列结构发生变化" in message for message in messages),
                    messages,
                )
                # Whole transaction rolled back: schema and D1 rows unchanged.
                self.assertEqual(_table_names(db), tables_before)
                self.assertEqual(_d1_snapshot(db)[1], digest_before)
                columns = {
                    row["name"]
                    for row in query_rows(db, f"PRAGMA table_info('{table}')")
                }
                self.assertIn(changed, columns)
                if gone is not None:
                    self.assertNotIn(gone, columns)
                self.assertEqual(
                    query_scalar(
                        db, f"SELECT version_num FROM {LOCAL_VERSION_TABLE}"
                    ),
                    SOURCE_REVISIONS["0003"],
                )


class ExternalOccupationTests(_D2MigrationSafetyCase):
    def test_external_process_occupation_refuses_upgrade(self):
        data_dir, db = self._prepare_source("0003")
        paths = self._fixture_paths("hold")
        spec = {
            "action": "hold_open",
            "db_path": str(db),
            **paths,
        }
        process = self._spawn_fixture(spec)
        wait_for_file(paths["ready_file"])

        runtime = self._runtime(data_dir)
        with self.assertRaises(LocalDatabaseStateError) as caught:
            runtime.prepare()
        self.assertEqual(caught.exception.code, "LOCAL_DB_OCCUPIED")
        self.assertFalse(runtime.prepared)
        # Occupation is checked before the backup: nothing was written.
        self.assertEqual(_backups(data_dir), [])
        self.assertEqual(
            query_scalar(db, f"SELECT version_num FROM {LOCAL_VERSION_TABLE}"),
            SOURCE_REVISIONS["0003"],
        )

        Path(paths["release_file"]).write_text("go", encoding="utf-8")
        process.wait(timeout=60)
        self.assertEqual(process.returncode, 0)
        # After the old process closes, the cold upgrade proceeds.
        recovered = self._runtime(data_dir)
        recovered.prepare()
        self.assertTrue(recovered.prepared)
        self.assertEqual(
            query_scalar(db, f"SELECT version_num FROM {LOCAL_VERSION_TABLE}"),
            head_revision(),
        )


class OlderSourceUpgradeTests(_D2MigrationSafetyCase):
    def test_0001_and_0002_upgrade_preserve_old_columns(self):
        for key in ("0001", "0002"):
            with self.subTest(source=key):
                data_dir, db = self._prepare_source(key)
                schema, before = _d1_snapshot(db)
                runtime = self._runtime(data_dir)
                inspection = runtime.prepare()
                self.assertEqual(inspection.state, "current")
                self.assertEqual(inspection.current_revision, head_revision())

                # Existing D1 rows are logically unchanged after the upgrade
                # (same summary over the pre-upgrade schema).
                self.assertEqual(_digest_with_schema(db, schema), before)
                self.assertEqual(
                    query_scalar(
                        db,
                        "SELECT current_calendar_revision_id FROM local_terms "
                        f"WHERE id = '{TERM_ID}'",
                    ),
                    REV2_ID,
                )
                # 0002 rebuild: the pointer is now NOT NULL.
                columns = {
                    row["name"]: row
                    for row in query_rows(db, "PRAGMA table_info('local_terms')")
                }
                self.assertEqual(
                    columns["current_calendar_revision_id"]["notnull"], 1
                )
                # 0003 new column default for old rows.
                settings_columns = {
                    row["name"]
                    for row in query_rows(
                        db, "PRAGMA table_info('local_settings')"
                    )
                }
                self.assertIn("config_version", settings_columns)
                self.assertEqual(
                    query_scalar(db, "SELECT config_version FROM local_settings"),
                    1,
                )
                self.assertEqual(
                    _manifest_for(_backups(data_dir)[0])["version"],
                    SOURCE_REVISIONS[key],
                )


if __name__ == "__main__":
    unittest.main()
