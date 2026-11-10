"""Deterministic local_listening_assets DDL/trusted-schema regressions."""
from __future__ import annotations

import hashlib
import io
import re
import sqlite3
import threading
import uuid
from datetime import date
from pathlib import Path

import pytest
from alembic import command

from app.local import (
    backup_validate,
    listening_assets,
    listening_service,
    profile_service,
)
from app.local.backup_snapshot import SnapshotService
from app.local.migrate import alembic_config, head_revision
from app.local.normalize import normalize_initialization
from app.local.runtime import LocalRuntime
from tests.local import listening_fixture_support
from tests.local.support import initialize_body

TABLE = "local_listening_assets"
REV_0018 = "20261110_0018_local_curriculum_ai"


def _runtime(root: Path) -> LocalRuntime:
    runtime = LocalRuntime(root / "data", credential_root=root / "cred")
    runtime.prepare()
    return runtime

def _initialize(runtime: LocalRuntime) -> None:
    session = runtime.session()
    try:
        profile_service.initialize(
            session, normalize_initialization(**initialize_body())
        )
        session.commit()
    finally:
        session.close()


def _seed_listening(runtime: LocalRuntime) -> str:
    session = runtime.session()
    try:
        context = profile_service.require_context(session, date.today())
        profile_id = context.profile.id
        created = listening_service.create_record(
            session,
            profile_id=profile_id,
            request_id=str(uuid.uuid4()),
            term_id=context.terms[0].id,
            child_name="DDL 回归幼儿",
        )
        record = listening_service.read_record(
            session,
            profile_id=profile_id,
            record_id=created["record_id"],
        )
        group = record["domains"][0]["groups"][0]
        imported = listening_assets.import_group_photo(
            session,
            runtime,
            profile_id=profile_id,
            record_id=record["record_id"],
            domain=listening_service.DOMAINS[0],
            group_id=group["group_id"],
            request_id=str(uuid.uuid4()),
            expected_revision=record["revision"],
            stream=io.BytesIO(
                listening_fixture_support.jpeg_bytes((20, 120, 220), (80, 60))
            ),
            display_name="ddl-schema.jpg",
        )
        return imported["asset_id"]
    finally:
        session.close()

def _copy_db(source: Path, target: Path) -> None:
    source_connection = sqlite3.connect(str(source))
    target_connection = sqlite3.connect(str(target))
    try:
        source_connection.backup(target_connection)
    finally:
        target_connection.close()
        source_connection.close()


def _table_sql(db_path: Path) -> str:
    connection = sqlite3.connect(str(db_path))
    try:
        return connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            (TABLE,),
        ).fetchone()[0]
    finally:
        connection.close()


def _snapshot(runtime: LocalRuntime, root: Path):
    service = SnapshotService(
        runtime,
        app_version="schema-ddl-test",
        source_identity={"fixture": "schema-ddl"},
    )
    package = root / "schema-ddl.kgmbackup"
    service.create(package, password=None, cancel=threading.Event())
    verified = service.verify(
        package, password=None, cancel=threading.Event()
    )
    return service, verified


def _split_table(sql: str) -> tuple[str, list[str]]:
    start = sql.index("(")
    end = sql.rindex(")")
    body = sql[start + 1 : end]
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    quote = ""
    for char in body:
        if quote:
            current.append(char)
            if char == quote:
                quote = ""
            continue
        if char in ("'", '"'):
            quote = char
            current.append(char)
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    parts.append("".join(current).strip())
    return sql[:start], parts

def _rebuild_table(db_path: Path, new_sql: str) -> None:
    connection = sqlite3.connect(str(db_path))
    try:
        connection.execute("PRAGMA foreign_keys=OFF")
        new_table = re.sub(
            r'^CREATE TABLE\s+"local_listening_assets"',
            'CREATE TABLE "local_listening_assets_new"',
            new_sql,
            count=1,
            flags=re.IGNORECASE,
        )
        assert new_table != new_sql
        connection.execute(new_table)
        connection.execute(
            "INSERT INTO local_listening_assets_new "
            "SELECT * FROM local_listening_assets"
        )
        connection.execute("DROP TABLE local_listening_assets")
        connection.execute(
            "ALTER TABLE local_listening_assets_new "
            "RENAME TO local_listening_assets"
        )
        connection.commit()
    finally:
        connection.close()


def _constraints(sql: str) -> list[str]:
    _prefix, parts = _split_table(sql)
    return [
        part for part in parts if part.lower().startswith("constraint ")
    ]



def _row(db_path: Path, asset_id: str):
    connection = sqlite3.connect(str(db_path))
    try:
        return connection.execute(
            "SELECT id, relative_path, content_hash, byte_size "
            "FROM local_listening_assets WHERE id=?",
            (asset_id,),
        ).fetchone()
    finally:
        connection.close()


def _validate(db_path: Path, scratch: Path) -> None:
    backup_validate.validate_database(
        db_path,
        migrate_old=False,
        require_current=True,
        scratch_dir=scratch,
    )


def test_reordered_same_named_listening_asset_constraints_accept(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path / "source")
    _initialize(runtime)
    asset_id = _seed_listening(runtime)
    service, verified = _snapshot(runtime, tmp_path)
    try:
        original_hash = hashlib.sha256(
            verified.database_path.read_bytes()
        ).hexdigest()
        assert original_hash == verified.manifest["database"]["sha256"]
        original_row = _row(verified.database_path, asset_id)
        assert original_row is not None
        asset_path = runtime.data_dir.joinpath(
            *original_row[1].split("/")
        )
        assert hashlib.sha256(asset_path.read_bytes()).hexdigest() == original_row[2]

        reordered = tmp_path / "reordered.db"
        _copy_db(verified.database_path, reordered)
        original_sql = _table_sql(reordered)
        original_constraints = _constraints(original_sql)
        assert len(original_constraints) >= 8
        assert len({item.split()[1] for item in original_constraints}) == len(
            original_constraints
        )
        prefix, parts = _split_table(original_sql)
        columns = [part for part in parts if part not in original_constraints]
        reordered_sql = prefix + "(" + ", ".join(
            columns + list(reversed(original_constraints))
        ) + ")"
        assert _constraints(reordered_sql) == list(
            reversed(original_constraints)
        )
        _rebuild_table(reordered, reordered_sql)
        assert _constraints(_table_sql(reordered)) == list(
            reversed(original_constraints)
        )
        assert _row(reordered, asset_id) == original_row
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        _validate(verified.database_path, scratch)
        _validate(reordered, scratch)
    finally:
        try:
            service.discard_verified(verified)
        finally:
            runtime.dispose()

def test_listening_asset_schema_rejects_changed_check_missing_constraint_and_trigger(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path / "source")
    _initialize(runtime)
    asset_id = _seed_listening(runtime)
    service, verified = _snapshot(runtime, tmp_path)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    try:
        original = _table_sql(verified.database_path)
        changed_check = tmp_path / "changed-check.db"
        _copy_db(verified.database_path, changed_check)
        changed_sql = re.sub(
            r"between 0 and 3",
            "BETWEEN 0 AND 4",
            original,
            count=1,
            flags=re.IGNORECASE,
        )
        assert changed_sql != original
        _rebuild_table(changed_check, changed_sql)
        with pytest.raises(backup_validate.BackupValidationError) as check:
            _validate(changed_check, scratch)
        assert check.value.code == "BACKUP_DB_SCHEMA_UNTRUSTED"

        missing = tmp_path / "missing-constraint.db"
        _copy_db(verified.database_path, missing)
        prefix, parts = _split_table(original)
        kept = [
            part
            for part in parts
            if "ck_local_listening_assets_rotation" not in part
        ]
        assert len(kept) == len(parts) - 1
        missing_sql = prefix + "(" + ", ".join(kept) + ")"
        _rebuild_table(missing, missing_sql)
        with pytest.raises(backup_validate.BackupValidationError) as absent:
            _validate(missing, scratch)
        assert absent.value.code == "BACKUP_DB_SCHEMA_UNTRUSTED"

        triggered = tmp_path / "triggered.db"
        _copy_db(verified.database_path, triggered)
        connection = sqlite3.connect(str(triggered))
        try:
            connection.execute(
                "CREATE TRIGGER sqliteXprobe AFTER INSERT ON local_profile "
                "BEGIN SELECT 1; END"
            )
            connection.commit()
        finally:
            connection.close()
        with pytest.raises(backup_validate.BackupValidationError) as trigger:
            _validate(triggered, scratch)
        assert trigger.value.code == "BACKUP_DB_SCHEMA_UNTRUSTED"
        assert _row(verified.database_path, asset_id) is not None
    finally:
        try:
            service.discard_verified(verified)
        finally:
            runtime.dispose()

def test_current_package_and_0018_to_0019_copy_share_trusted_listening_schema(
    tmp_path: Path,
) -> None:
    current = _runtime(tmp_path / "current")
    upgrade_db = tmp_path / "upgrade" / "kindergarten.db"
    upgrade_db.parent.mkdir(parents=True)
    command.upgrade(alembic_config(upgrade_db), REV_0018)
    command.upgrade(alembic_config(upgrade_db), head_revision())
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    snapshots = []
    try:
        for db_path in (current.db_path, upgrade_db):
            connection = sqlite3.connect(str(db_path))
            try:
                backup_validate._validate_schema(
                    connection, head_revision(), scratch
                )
                snapshots.append(
                    backup_validate._schema_snapshot(connection)["tables"][TABLE]
                )
            finally:
                connection.close()
        assert snapshots[0] == snapshots[1]
        assert (
            len(_constraints(snapshots[0]["sql"]))
            == len(_constraints(snapshots[1]["sql"]))
        )
    finally:
        current.dispose()
