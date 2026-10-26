"""E02 real-Alembic 0005 cold upgrade, guard/seed and rollback tests."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import unittest
from pathlib import Path
from unittest import mock

from alembic import command
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.local import d1_digest, profile_service, prompt_bundles
from app.local.errors import LocalDatabaseStateError, LocalStorageError
from app.local.migrate import D1UpgradeGuard, alembic_config, ensure_local_schema
from app.local.models import (
    LocalAIInput,
    LocalAITask,
    LocalAICandidate,
    LocalPersonalPromptHead,
    LocalPersonalPromptVersion,
    LocalProfile,
    LocalPromptBundle,
)
from app.local.normalize import normalize_initialization
from app.local.runtime import LocalRuntime
from app.local.sqlite import LOCAL_VERSION_TABLE, create_local_engine
from tests.local.support import LocalTestCase, initialize_body, query_rows, query_scalar

SOURCE_REVISION = "20261023_0005_local_history"
H = "a" * 64
NOW = "2026-10-20 00:00:00"


def _exec(connection: sqlite3.Connection, sql: str, params=()) -> None:
    connection.execute(sql, params)


def _build_0005(db: Path, *, bad_task: bool = False) -> None:
    command.upgrade(alembic_config(db), SOURCE_REVISION)
    connection = sqlite3.connect(str(db))
    try:
        connection.execute("PRAGMA foreign_keys=OFF")
        _exec(connection, "INSERT INTO local_profile VALUES (?,?,?,?,?)",
              ("prof1", 1, "王老师", NOW, NOW))
        _exec(connection, "INSERT INTO local_classes VALUES (?,?,?,?,?)",
              ("class1", "中一班", "middle", NOW, NOW))
        _exec(connection, "INSERT INTO local_terms VALUES (?,?,?,?,?,?,?)",
              ("term1", "2026秋", "2026-09-01", "2026-09-30", "rev1", NOW, NOW))
        _exec(connection, "INSERT INTO local_calendar_revisions VALUES (?,?,?,?,?,?)",
              ("rev1", "term1", 1, "lib1", "prof1", NOW))
        _exec(connection, "INSERT INTO local_settings VALUES ('singleton',1,'示范园',?,?,?,?,?,1)",
              ("class1", "00000000-0000-4000-8000-000000000001", H, NOW, NOW))
        _exec(connection, "INSERT INTO local_daily_plans VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,NULL,?,?)",
              ("plan1", "class1", "term1", "2026-09-10", "prof1", 2, 4, "rev1",
               "cont2", 2, "王老师", "示范园", "中一班", "middle", NOW, NOW))
        _exec(connection, "INSERT INTO local_daily_plan_contents VALUES (?,?,?,?,?,?,?,?)",
              ("cont1", "plan1", 1, "raw", None, "{}", "prof1", NOW))
        _exec(connection, "INSERT INTO local_daily_plan_contents VALUES (?,?,?,?,?,?,?,?)",
              ("cont2", "plan1", 2, "raw2", None, "{}", "prof1", NOW))
        _exec(connection, "INSERT INTO local_ai_inputs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
              ("inp1", "plan1", "cont1", 1, "daily_lesson_split", "middle", 1,
               json.dumps({"raw_lesson_plan": "x", "grade": "middle"}),
               "{}", H, "{}", NOW))
        task_plan = "plan2" if bad_task else "plan1"
        _exec(connection, "INSERT INTO local_ai_tasks VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
              ("task1", "prof1", task_plan, "daily_lesson_split", "inp1",
               "succeeded", None, None, 0, "{}", NOW, NOW))
        _exec(connection, "INSERT INTO local_ai_credentials VALUES (?,?,?,?,?,?,?,?)",
              ("cred1", "prof1", "key1", sqlite3.Binary(b"\x00" * 12),
               sqlite3.Binary(b"\x01" * 16), "active", NOW, NOW))
        _exec(connection, "INSERT INTO local_ai_config_versions VALUES (?,?,?,?,?,?,?)",
              ("prof1", 1, "chat_completions_v1", "https://example.com/v1", "model-1", "cred1", NOW))
        _exec(connection, "INSERT INTO local_ai_state VALUES (?,?,?,?,?,?,?)",
              ("prof1", "00000000-0000-4000-8000-000000000001", 1, None, None, NOW, NOW))
        _exec(connection, "INSERT INTO local_personal_prompt_versions VALUES (?,?,?,?,?,?,?,?,?,?)",
              ("prof1", "daily_lesson_split", 1, 1, 1,
               json.dumps({"theme": "旧指导"}), None, "initial", None, NOW))
        _exec(connection, "INSERT INTO local_personal_prompt_heads VALUES (?,?,?,?,?,?,?)",
              ("prof1", "daily_lesson_split", 1, 1, 1, NOW, NOW))
        _exec(connection, "INSERT INTO local_ai_executions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
              ("exe1", "task1", "plan1", "inp1", "daily_lesson_split", 1,
               "launch1", "permit1", 1, "prof1", 1, 1, 1, "succeeded",
               "{}", NOW, NOW, NOW))
        _exec(connection, "INSERT INTO local_ai_attempts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
              ("att1", "exe1", 1, "succeeded", None, NOW, None, 200, None, "model-1", "{}", 10, NOW))
        _exec(connection, "INSERT INTO local_ai_candidates VALUES (?,?,?,?,?,?,?,?,?,?,?)",
              ("cand1", "exe1", "task1", "plan1", "inp1", "daily_lesson_split",
               1, 1, "{}", H, NOW))
        _exec(connection, "INSERT INTO local_daily_plan_ai_provenance VALUES (?,?,?,?,?,?,?,?)",
              ("cont1", "plan1", 1, None, "cand1", '{"group_activity":"adopted"}', H, NOW))
        _exec(connection, "INSERT INTO local_daily_plan_ai_provenance VALUES (?,?,?,?,?,?,?,?)",
              ("cont2", "plan1", 2, None, "cand1", '{"group_activity":"adopted2"}', H, NOW))
        _exec(connection, "INSERT INTO local_ai_operations VALUES (?,?,?,?,?,?,?,?,?)",
              ("aiop1", "prof1", "00000000-0000-4000-8000-000000000010",
               "config_patch", H, "sha256", None, "{}", NOW))
        _exec(connection, "INSERT INTO local_daily_plan_restores VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
              ("restore1", "prof1", "00000000-0000-4000-8000-000000000011",
               H, "plan1", "cont1", 1, "cont1", 1, "cont2", 2, NOW))
        connection.commit()
    finally:
        connection.close()


def _source_digest(db: Path) -> tuple[dict, str]:
    connection = sqlite3.connect(str(db))
    try:
        schema = d1_digest.capture_schema(connection)
        return schema, d1_digest.digest(connection, schema)
    finally:
        connection.close()


def _cause_text(exc: BaseException) -> str:
    """Join the explicit cause/context chain for target-failure assertions."""
    parts: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        parts.append(str(current))
        current = current.__cause__ or current.__context__
    return " | ".join(parts)


def _retain(name: str, path: Path) -> None:
    """Optional evidence switch: copy a synthetic DB outside TemporaryDirectory."""
    root = os.environ.get("KGM_OBSERVATION_EVIDENCE_ROOT")
    if not root:
        return
    target = Path(root)
    target.mkdir(parents=True, exist_ok=True)
    destination = target / name
    if path.is_dir():
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(path, destination)
    else:
        shutil.copy2(path, destination)


class ObservationMigrationTests(LocalTestCase):
    def test_empty_database_registers_only_bundles_and_new_profile_seeds_all(self):
        runtime = self.make_runtime()
        db = runtime.db_path
        self.assertEqual(
            query_scalar(db, f"SELECT version_num FROM {LOCAL_VERSION_TABLE}"),
            "20261025_0006_local_game_observations",
        )
        self.assertEqual(query_rows(db, "PRAGMA foreign_key_check"), [])
        tables = {
            row["name"]
            for row in query_rows(db, "SELECT name FROM sqlite_master WHERE type='table'")
        }
        for name in (
            "local_observation_records",
            "local_observation_drafts",
            "local_observation_versions",
            "local_observation_assets",
            "local_observation_ai_input_photos",
            "local_observation_ai_provenance",
        ):
            self.assertIn(name, tables)
        observation_bundles = query_rows(
            db,
            "SELECT task_type FROM local_prompt_bundles "
            "WHERE task_type LIKE 'game_observation_%' ORDER BY task_type",
        )
        self.assertEqual(
            [row["task_type"] for row in observation_bundles],
            ["game_observation_generate", "game_observation_rewrite"],
        )
        self.assertEqual(
            query_scalar(db, "SELECT count(*) FROM local_personal_prompt_heads"),
            0,
        )

        session = runtime.session()
        try:
            profile_service.initialize(
                session, normalize_initialization(**initialize_body())
            )
        finally:
            session.close()
        heads = query_rows(
            db,
            "SELECT task_type FROM local_personal_prompt_heads ORDER BY task_type",
        )
        self.assertEqual(
            [row["task_type"] for row in heads],
            sorted(prompt_bundles.REGISTERED_TASK_TYPES),
        )

    def test_real_0005_upgrade_preserves_old_digest_and_backfills_source(self):
        source = self.tmp_root / "source-0005.db"
        _build_0005(source)
        _retain("source-0005-rich.db", source)
        schema, expected = _source_digest(source)
        self.assertEqual(query_rows(source, "PRAGMA foreign_key_check"), [])

        upgraded = self.tmp_root / "upgraded-0006.db"
        shutil.copy2(source, upgraded)
        ensure_local_schema(upgraded)
        _retain("success-0006.db", upgraded)
        connection = sqlite3.connect(str(upgraded))
        try:
            self.assertEqual(
                d1_digest.digest(connection, schema),
                expected,
                "migration must not change pre-existing rows/columns",
            )
        finally:
            connection.close()
        self.assertEqual(
            query_scalar(upgraded, f"SELECT version_num FROM {LOCAL_VERSION_TABLE}"),
            "20261025_0006_local_game_observations",
        )
        input_row = query_rows(
            upgraded,
            "SELECT id,profile_id,source_kind,source_id,daily_plan_id,content_id,"
            "content_version,target_grade,observation_id,source_revision "
            "FROM local_ai_inputs",
        )[0]
        self.assertEqual(input_row["profile_id"], "prof1")
        self.assertEqual(input_row["source_kind"], "daily_plan")
        self.assertEqual(input_row["source_id"], "plan1")
        self.assertIsNone(input_row["observation_id"])
        self.assertIsNone(input_row["source_revision"])
        task_row = query_rows(
            upgraded, "SELECT id,source_kind,source_id,daily_plan_id FROM local_ai_tasks"
        )[0]
        self.assertEqual(task_row, {
            "id": "task1", "source_kind": "daily_plan",
            "source_id": "plan1", "daily_plan_id": "plan1",
        })
        self.assertEqual(
            query_scalar(
                upgraded,
                "SELECT adopted_candidate_id FROM local_daily_plan_ai_provenance",
            ),
            "cand1",
        )

    def test_runtime_guard_then_seed_is_idempotent_and_keeps_daily_rows(self):
        source = self.tmp_root / "source-runtime.db"
        _build_0005(source)
        old_prompt_rows = query_rows(
            source,
            "SELECT task_type,contract_version,default_revision,bundle_hash "
            "FROM local_prompt_bundles ORDER BY task_type,contract_version,default_revision",
        )
        old_daily_version = query_rows(
            source,
            "SELECT profile_id,task_type,revision,guidance_json "
            "FROM local_personal_prompt_versions ORDER BY task_type,revision",
        )
        data_dir = self.tmp_root / "runtime-data"
        data_dir.mkdir(parents=True)
        shutil.copy2(source, data_dir / "kindergarten.db")
        runtime = LocalRuntime(data_dir, credential_root=self.tmp_root / "credentials")
        runtime.prepare()
        self.assertIsNone(runtime.prompt_sync_error)
        db = runtime.db_path
        self.assertEqual(query_rows(db, "PRAGMA foreign_key_check"), [])
        self.assertEqual(
            query_scalar(db, f"SELECT version_num FROM {LOCAL_VERSION_TABLE}"),
            "20261025_0006_local_game_observations",
        )
        new_daily_prompt_rows = query_rows(
            db,
            "SELECT task_type,contract_version,default_revision,bundle_hash "
            "FROM local_prompt_bundles WHERE task_type LIKE 'daily_%' "
            "ORDER BY task_type,contract_version,default_revision",
        )
        for row in old_prompt_rows:
            self.assertIn(row, new_daily_prompt_rows)
        self.assertEqual(
            query_rows(
                db,
                "SELECT profile_id,task_type,revision,guidance_json "
                "FROM local_personal_prompt_versions WHERE task_type LIKE 'daily_%' "
                "ORDER BY task_type,revision",
            ),
            old_daily_version,
        )
        heads = {
            row["task_type"]
            for row in query_rows(
                db, "SELECT task_type FROM local_personal_prompt_heads"
            )
        }
        self.assertTrue(
            {"game_observation_generate", "game_observation_rewrite"} <= heads
        )
        counts_before = (
            query_scalar(db, "SELECT count(*) FROM local_prompt_bundles"),
            query_scalar(db, "SELECT count(*) FROM local_personal_prompt_versions"),
            query_scalar(db, "SELECT count(*) FROM local_personal_prompt_heads"),
        )
        runtime.dispose()
        runtime2 = LocalRuntime(data_dir, credential_root=self.tmp_root / "credentials")
        runtime2.prepare()
        self.assertIsNone(runtime2.prompt_sync_error)
        counts_after = (
            query_scalar(db, "SELECT count(*) FROM local_prompt_bundles"),
            query_scalar(db, "SELECT count(*) FROM local_personal_prompt_versions"),
            query_scalar(db, "SELECT count(*) FROM local_personal_prompt_heads"),
        )
        self.assertEqual(counts_before, counts_after)
        runtime2.dispose()

    def test_preflight_rejects_each_missing_parent_before_ddl(self):
        source = self.tmp_root / "good-source.db"
        _build_0005(source)
        cases = {
            "content": "UPDATE local_ai_inputs SET content_id='missing-content'",
            "content_version": "UPDATE local_ai_inputs SET content_version=99",
            "profile": "UPDATE local_daily_plans SET creator_id='missing-profile'",
            "task": "UPDATE local_ai_tasks SET input_id='missing-input'",
            "execution": "UPDATE local_ai_executions SET task_id='missing-task'",
            "candidate": "UPDATE local_ai_candidates SET execution_id='missing-exec'",
        }
        for label, mutation in cases.items():
            with self.subTest(label=label):
                db = self.tmp_root / f"bad-{label}.db"
                shutil.copy2(source, db)
                connection = sqlite3.connect(str(db))
                try:
                    connection.execute("PRAGMA foreign_keys=OFF")
                    connection.execute(mutation)
                    connection.commit()
                    schema_before = connection.execute(
                        "SELECT type,name,sql FROM sqlite_master ORDER BY type,name"
                    ).fetchall()
                finally:
                    connection.close()
                with self.assertRaises(LocalDatabaseStateError) as caught:
                    ensure_local_schema(db)
                self.assertIn(
                    "pre-existing foreign key violation", _cause_text(caught.exception)
                )
                self.assertEqual(
                    query_scalar(db, f"SELECT version_num FROM {LOCAL_VERSION_TABLE}"),
                    SOURCE_REVISION,
                )
                self.assertEqual(
                    query_scalar(
                        db,
                        "SELECT count(*) FROM sqlite_master WHERE name LIKE '%_new'",
                    ),
                    0,
                )
                connection = sqlite3.connect(str(db))
                try:
                    schema_after = connection.execute(
                        "SELECT type,name,sql FROM sqlite_master ORDER BY type,name"
                    ).fetchall()
                finally:
                    connection.close()
                self.assertEqual(schema_after, schema_before)
                _retain(f"failed-preflight-{label}.db", db)

    def test_mid_ddl_failure_rolls_back_observation_tables(self):
        source = self.tmp_root / "ddl-source.db"
        _build_0005(source)
        schema, expected = _source_digest(source)
        connection = sqlite3.connect(str(source))
        try:
            connection.execute("CREATE TABLE local_ai_inputs_new (sentinel TEXT)")
            connection.commit()
        finally:
            connection.close()
        schema, expected = _source_digest(source)
        with self.assertRaises(LocalDatabaseStateError) as caught:
            ensure_local_schema(source)
        self.assertIn("local_ai_inputs_new already exists", _cause_text(caught.exception))
        self.assertEqual(
            query_scalar(source, f"SELECT version_num FROM {LOCAL_VERSION_TABLE}"),
            SOURCE_REVISION,
        )
        self.assertEqual(
            query_scalar(
                source,
                "SELECT count(*) FROM sqlite_master WHERE name='local_observation_records'",
            ),
            0,
        )
        connection = sqlite3.connect(str(source))
        try:
            self.assertEqual(d1_digest.digest(connection, schema), expected)
        finally:
            connection.close()
        _retain("failed-mid-ddl-create.db", source)

    def test_mid_ddl_failure_after_task_and_execution_rebuild_rolls_back(self):
        source = self.tmp_root / "ddl-late-source.db"
        _build_0005(source)
        schema, expected = _source_digest(source)
        connection = sqlite3.connect(str(source))
        try:
            # Fail when the candidates table is created, after inputs, tasks
            # and the task/execution cycle have already been rebuilt.
            connection.execute("CREATE TABLE local_ai_candidates_new (sentinel TEXT)")
            connection.commit()
        finally:
            connection.close()
        with self.assertRaises(LocalDatabaseStateError) as caught:
            ensure_local_schema(source)
        self.assertIn(
            "local_ai_candidates_new already exists", _cause_text(caught.exception)
        )
        self.assertEqual(
            query_scalar(source, f"SELECT version_num FROM {LOCAL_VERSION_TABLE}"),
            SOURCE_REVISION,
        )
        connection = sqlite3.connect(str(source))
        try:
            self.assertEqual(d1_digest.digest(connection, schema), expected)
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        finally:
            connection.close()
        # Migration-created _new tables are gone; only the pre-existing
        # sentinel remains.  Observation tables created before the failure are
        # also gone.
        self.assertNotIn("local_ai_inputs_new", tables)
        self.assertNotIn("local_ai_tasks_new", tables)
        self.assertNotIn("local_ai_executions_new", tables)
        self.assertNotIn("local_observation_records", tables)
        self.assertIn("local_ai_candidates_new", tables)
        _retain("failed-mid-ddl-after-executions.db", source)

    def test_mid_ddl_failure_after_execution_index_rolls_back(self):
        source = self.tmp_root / "ddl-index-source.db"
        _build_0005(source)
        schema, expected = _source_digest(source)
        connection = sqlite3.connect(str(source))
        try:
            # The migration creates this index only after rebuilding executions.
            # A pre-existing same-name index deterministically fails there.
            connection.execute(
                "CREATE INDEX ix_local_ai_executions_source_task "
                "ON local_profile(id)"
            )
            connection.commit()
        finally:
            connection.close()
        with self.assertRaises(LocalDatabaseStateError) as caught:
            ensure_local_schema(source)
        self.assertIn(
            "ix_local_ai_executions_source_task already exists",
            _cause_text(caught.exception),
        )
        self.assertEqual(
            query_scalar(source, f"SELECT version_num FROM {LOCAL_VERSION_TABLE}"),
            SOURCE_REVISION,
        )
        connection = sqlite3.connect(str(source))
        try:
            self.assertEqual(d1_digest.digest(connection, schema), expected)
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            indexes = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'"
                )
            }
            executions_ddl = connection.execute(
                "SELECT sql FROM sqlite_master WHERE name='local_ai_executions'"
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertNotIn("local_ai_inputs_new", tables)
        self.assertNotIn("local_ai_tasks_new", tables)
        self.assertNotIn("local_ai_executions_new", tables)
        self.assertNotIn("local_observation_records", tables)
        self.assertIn("ix_local_ai_executions_source_task", indexes)
        self.assertIn("fk_local_ai_executions_task", executions_ddl)
        self.assertNotIn("source_kind", executions_ddl)
        self.assertEqual(query_rows(source, "PRAGMA foreign_key_check"), [])
        _retain("failed-mid-ddl-after-execution-index.db", source)

    def test_precommit_guard_failure_rolls_back_every_ddl_step(self):
        source = self.tmp_root / "guard-source.db"
        _build_0005(source)
        schema, expected = _source_digest(source)
        connection = sqlite3.connect(str(source))
        try:
            guard = D1UpgradeGuard(SOURCE_REVISION, schema, expected)
        finally:
            connection.close()

        class _FailAfter(D1UpgradeGuard):
            hit = False

            def after_migrations(self, connection) -> None:  # noqa: ANN001
                type(self).hit = True
                raise RuntimeError("injected pre-commit guard failure")

        guard = _FailAfter(SOURCE_REVISION, schema, expected)
        with self.assertRaises(LocalDatabaseStateError) as caught:
            ensure_local_schema(source, d1_guard=guard)
        self.assertTrue(_FailAfter.hit)
        self.assertIn(
            "injected pre-commit guard failure", _cause_text(caught.exception)
        )
        _retain("failed-precommit-guard.db", source)
        self.assertEqual(
            query_scalar(source, f"SELECT version_num FROM {LOCAL_VERSION_TABLE}"),
            SOURCE_REVISION,
        )
        self.assertEqual(
            query_scalar(
                source,
                "SELECT count(*) FROM sqlite_master WHERE name='local_observation_records'",
            ),
            0,
        )
        self.assertEqual(
            query_scalar(
                source,
                "SELECT count(*) FROM local_prompt_bundles "
                "WHERE task_type LIKE 'game_observation_%'",
            ),
            0,
        )
        self.assertEqual(
            query_scalar(
                source,
                "SELECT count(*) FROM local_personal_prompt_heads "
                "WHERE task_type LIKE 'game_observation_%'",
            ),
            0,
        )
        connection = sqlite3.connect(str(source))
        try:
            self.assertEqual(d1_digest.digest(connection, schema), expected)
        finally:
            connection.close()

    def test_post_commit_verify_failure_refuses_startup_and_does_not_seed(self):
        source = self.tmp_root / "postcommit-source.db"
        _build_0005(source)
        data_dir = self.tmp_root / "postcommit-data"
        data_dir.mkdir(parents=True)
        shutil.copy2(source, data_dir / "kindergarten.db")

        class _FailVerify(LocalRuntime):
            hit = False

            def _verify_committed_upgrade(self, guard, config) -> None:  # noqa: ANN001
                type(self).hit = True
                raise LocalStorageError("injected post-commit verify failure")

        runtime = _FailVerify(data_dir, credential_root=self.tmp_root / "credentials")
        with self.assertRaises(LocalStorageError):
            runtime.prepare()
        self.assertTrue(_FailVerify.hit)
        self.assertFalse(runtime.prepared)
        runtime.dispose()
        db = data_dir / "kindergarten.db"
        self.assertEqual(
            query_scalar(db, f"SELECT version_num FROM {LOCAL_VERSION_TABLE}"),
            "20261025_0006_local_game_observations",
        )
        self.assertEqual(
            query_scalar(
                db,
                "SELECT count(*) FROM local_prompt_bundles "
                "WHERE task_type LIKE 'game_observation_%'",
            ),
            0,
        )
        self.assertEqual(
            query_scalar(
                db,
                "SELECT count(*) FROM local_personal_prompt_heads "
                "WHERE task_type LIKE 'game_observation_%'",
            ),
            0,
        )
        backups = list((data_dir / "migration-backups").glob("pre-D2-*.sqlite"))
        self.assertTrue(backups)
        backup = backups[0]
        manifest = backup.with_suffix(".manifest.json")
        self.assertTrue(manifest.is_file())
        manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual(manifest_data["version"], SOURCE_REVISION)
        self.assertEqual(
            manifest_data["sha256"],
            hashlib.sha256(backup.read_bytes()).hexdigest(),
        )
        backup_connection = sqlite3.connect(str(backup))
        try:
            backup_schema = d1_digest.capture_schema(backup_connection)
            self.assertEqual(
                d1_digest.single_revision(backup_connection),
                SOURCE_REVISION,
            )
            self.assertEqual(
                d1_digest.digest(backup_connection, backup_schema),
                _source_digest(source)[1],
            )
        finally:
            backup_connection.close()
        _retain("failed-postcommit-committed.db", db)
        _retain("failed-postcommit-backup.sqlite", backup)
        _retain("failed-postcommit-manifest.json", manifest)
        # The backup is independently restorable in another isolated target.
        restore_dir = self.tmp_root / "restore-from-backup"
        restore_dir.mkdir()
        restored = restore_dir / "kindergarten.db"
        shutil.copy2(backup, restored)
        ensure_local_schema(restored)
        self.assertEqual(
            query_scalar(restored, f"SELECT version_num FROM {LOCAL_VERSION_TABLE}"),
            "20261025_0006_local_game_observations",
        )
        self.assertEqual(query_rows(restored, "PRAGMA foreign_key_check"), [])

        normal = LocalRuntime(data_dir, credential_root=self.tmp_root / "credentials")
        normal.prepare()
        self.assertIsNone(normal.prompt_sync_error)
        self.assertEqual(
            query_scalar(
                db,
                "SELECT count(*) FROM local_prompt_bundles "
                "WHERE task_type LIKE 'game_observation_%'",
            ),
            2,
        )
        self.assertEqual(
            query_scalar(
                db,
                "SELECT count(*) FROM local_personal_prompt_heads "
                "WHERE task_type LIKE 'game_observation_%'",
            ),
            2,
        )
        normal.dispose()

    def test_seed_partial_failure_rolls_back_both_new_row_sets(self):
        source = self.tmp_root / "seed-source.db"
        _build_0005(source)
        ensure_local_schema(source)
        old_daily_guidance = query_rows(
            source,
            "SELECT task_type,revision,guidance_json FROM local_personal_prompt_versions "
            "WHERE task_type LIKE 'daily_%' ORDER BY task_type,revision",
        )
        old_daily_heads = query_rows(
            source,
            "SELECT task_type,current_revision,required_contract_version,"
            "latest_default_revision FROM local_personal_prompt_heads "
            "WHERE task_type LIKE 'daily_%' ORDER BY task_type",
        )
        engine = create_local_engine(source)
        session = sessionmaker(bind=engine, expire_on_commit=False)()
        class _InjectedSeedFailure(RuntimeError):
            pass
        try:
            hit = {"value": False}

            def _fail_after_one(session, items, targets, now):
                task_type = "game_observation_generate"
                target = targets[task_type]
                item = items[(task_type, target["required_contract_version"],
                              target["latest_default_revision"])]
                session.add(
                    LocalPersonalPromptVersion(
                        profile_id="prof1",
                        task_type=task_type,
                        revision=1,
                        contract_version=target["required_contract_version"],
                        based_default_revision=target["latest_default_revision"],
                        guidance_json=dict(item["guidance_defaults_json"]),
                        orphaned_guidance_json=None,
                        action="initial",
                        rejected_default_revision=None,
                        created_at=now,
                    )
                )
                session.add(
                    LocalPersonalPromptHead(
                        profile_id="prof1",
                        task_type=task_type,
                        current_revision=1,
                        required_contract_version=target["required_contract_version"],
                        latest_default_revision=target["latest_default_revision"],
                        created_at=now,
                        updated_at=now,
                    )
                )
                session.flush()
                # The injected fault happens after a real personal row pair is
                # visible inside this transaction.
                self.assertEqual(
                    session.scalar(
                        select(func.count()).select_from(LocalPersonalPromptVersion).where(
                            LocalPersonalPromptVersion.task_type == task_type
                        )
                    ),
                    1,
                )
                self.assertEqual(
                    session.scalar(
                        select(func.count()).select_from(LocalPersonalPromptHead).where(
                            LocalPersonalPromptHead.task_type == task_type
                        )
                    ),
                    1,
                )
                hit["value"] = True
                raise _InjectedSeedFailure("injected seed failure")

            with mock.patch.object(
                prompt_bundles,
                "_ensure_missing_observation_prompt_seeds",
                _fail_after_one,
            ):
                with self.assertRaises(_InjectedSeedFailure):
                    prompt_bundles.sync_prompt_bundles(session)
            self.assertTrue(hit["value"])
            _retain("failed-seed-transaction.db", source)
            for table in (
                "local_prompt_bundles",
                "local_personal_prompt_versions",
                "local_personal_prompt_heads",
            ):
                self.assertEqual(
                    query_scalar(
                        source,
                        f"SELECT count(*) FROM {table} "
                        "WHERE task_type LIKE 'game_observation_%'",
                    ),
                    0,
                    table,
                )
            self.assertEqual(
                query_rows(
                    source,
                    "SELECT task_type,revision,guidance_json "
                    "FROM local_personal_prompt_versions WHERE task_type LIKE 'daily_%' "
                    "ORDER BY task_type,revision",
                ),
                old_daily_guidance,
            )
            self.assertEqual(
                query_rows(
                    source,
                    "SELECT task_type,current_revision,required_contract_version,"
                    "latest_default_revision FROM local_personal_prompt_heads "
                    "WHERE task_type LIKE 'daily_%' ORDER BY task_type",
                ),
                old_daily_heads,
            )
            prompt_bundles.sync_prompt_bundles(session)
            first_counts = {
                table: query_scalar(
                    source,
                    f"SELECT count(*) FROM {table} "
                    "WHERE task_type LIKE 'game_observation_%'",
                )
                for table in (
                    "local_prompt_bundles",
                    "local_personal_prompt_versions",
                    "local_personal_prompt_heads",
                )
            }
            self.assertEqual(first_counts, {
                "local_prompt_bundles": 2,
                "local_personal_prompt_versions": 2,
                "local_personal_prompt_heads": 2,
            })
            prompt_bundles.sync_prompt_bundles(session)
            second_counts = {
                table: query_scalar(
                    source,
                    f"SELECT count(*) FROM {table} "
                    "WHERE task_type LIKE 'game_observation_%'",
                )
                for table in first_counts
            }
            self.assertEqual(second_counts, first_counts)
            _retain("success-after-seed-retry.db", source)
        finally:
            session.close()
            engine.dispose()

    def test_preflight_failure_leaves_0005_and_no_new_tables(self):
        source = self.tmp_root / "bad-source.db"
        _build_0005(source, bad_task=True)
        with self.assertRaises(LocalDatabaseStateError):
            ensure_local_schema(source)
        self.assertEqual(
            query_scalar(source, f"SELECT version_num FROM {LOCAL_VERSION_TABLE}"),
            SOURCE_REVISION,
        )
        self.assertEqual(
            query_scalar(
                source,
                "SELECT count(*) FROM sqlite_master WHERE name LIKE '%_new'",
            ),
            0,
        )


if __name__ == "__main__":
    unittest.main()
