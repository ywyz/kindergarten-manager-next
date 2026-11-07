"""Listening migration and SQL constraint coverage."""

from __future__ import annotations

import hashlib
import sqlite3

import pytest
from alembic import command

from app.local import listening_service, profile_service
from app.local.base import LocalBase
from app.local.errors import LocalDatabaseStateError
from app.local.migrate import alembic_config, ensure_local_schema, head_revision
from app.local.normalize import normalize_initialization
from app.local.runtime import LocalRuntime
from tests.local.backup_fixture_support import (
    create_old_0007_fixture,
    migration_rows,
    resource_fingerprint,
)
from tests.local.support import initialize_body

HEAD = "20261107_0010_local_listening_ai"
OLD_0008 = "20261102_0008_local_weekly_ai"


def _runtime(tmp_path, name="data") -> LocalRuntime:
    runtime = LocalRuntime(
        tmp_path / name, credential_root=tmp_path / (name + "-cred")
    )
    runtime.prepare()
    session = runtime.session()
    try:
        profile_service.initialize(
            session, normalize_initialization(**initialize_body())
        )
        session.commit()
    finally:
        session.close()
    return runtime


def _initials(runtime: LocalRuntime):
    session = runtime.session()
    try:
        context = profile_service.require_context(
            session, __import__("datetime").date.today()
        )
        return context.profile.id, context.terms[0].id
    finally:
        session.close()


def test_new_database_has_six_listening_tables_and_constraints(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    try:
        assert runtime.current_revision == HEAD
        assert len(LocalBase.metadata.tables) == 56
        db = runtime.db_path
        connection = sqlite3.connect(str(db))
        try:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            }
            assert len(tables - {"local_alembic_version"}) == 56
            assert {
                "local_listening_records",
                "local_listening_domains",
                "local_listening_evaluation_choices",
                "local_listening_photo_groups",
                "local_listening_assets",
                "local_listening_operations",
            } <= tables
            group_sql = connection.execute(
                "SELECT sql FROM sqlite_master WHERE name="
                "'local_listening_photo_groups'"
            ).fetchone()[0]
            assert "UNIQUE (record_id, domain, position)" in group_sql
            assert "FOREIGN KEY(record_id, asset_id)" in group_sql
            assert "FOREIGN KEY(record_id, domain)" in group_sql
            choice_sql = connection.execute(
                "SELECT sql FROM sqlite_master WHERE name="
                "'local_listening_evaluation_choices'"
            ).fetchone()[0]
            assert "typeof(stars) = 'integer'" in choice_sql
            assert "stars IN (1, 2, 3)" in choice_sql
            record_sql = connection.execute(
                "SELECT sql FROM sqlite_master WHERE name="
                "'local_listening_records'"
            ).fetchone()[0]
            assert "uq_local_listening_records_profile_id" in record_sql
            record_indexes = {
                row[1]
                for row in connection.execute(
                    "PRAGMA index_list('local_listening_records')"
                ).fetchall()
            }
            assert "ix_local_listening_records_profile_class_term" in record_indexes
            assert "ix_local_listening_records_profile_name" in record_indexes
        finally:
            connection.close()

        profile_id, term_id = _initials(runtime)
        session = runtime.session()
        try:
            created = listening_service.create_record(
                session,
                profile_id=profile_id,
                request_id=__import__("uuid").uuid4(),
                term_id=term_id,
                child_name="约束幼儿",
            )
        finally:
            session.close()
        record_id = created["record_id"]
        connection = sqlite3.connect(str(db))
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            for stars in (0, 4, "4", 1.5):
                with pytest.raises(sqlite3.IntegrityError):
                    connection.execute(
                        "UPDATE local_listening_evaluation_choices SET stars = ? "
                        "WHERE record_id = ? AND item_id = 'health_1'",
                        (stars, record_id),
                    )
            connection.execute("UPDATE local_listening_evaluation_choices "
                               "SET stars = 2 WHERE record_id = ? AND item_id='health_1'",
                               (record_id,))
            connection.commit()
            groups = connection.execute(
                "SELECT id, position FROM local_listening_photo_groups "
                "WHERE record_id = ? AND domain = 'health' ORDER BY position",
                (record_id,),
            ).fetchall()
            assert [row[1] for row in groups] == [0, 1, 2]
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE local_listening_photo_groups SET position = 0 "
                    "WHERE id = ?",
                    (groups[1][0],),
                )
            connection.rollback()
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE local_listening_domains SET template_sha256 = 'x' "
                    "WHERE record_id = ? AND domain = 'health'",
                    (record_id,),
                )
        finally:
            connection.close()
    finally:
        runtime.dispose()


def test_0008_upgrade_preserves_old_rows_and_resources(tmp_path) -> None:
    root = tmp_path / "old"
    db = root / "kindergarten.db"
    data = root / "data"
    create_old_0007_fixture(db, data)
    command.upgrade(alembic_config(db), OLD_0008)
    before = migration_rows(db)
    before_resources = resource_fingerprint(data)
    ensure_local_schema(db)
    after = migration_rows(db)
    assert before == after
    assert resource_fingerprint(data) == before_resources
    connection = sqlite3.connect(str(db))
    try:
        assert connection.execute(
            "SELECT version_num FROM local_alembic_version"
        ).fetchone() == (HEAD,)
        for table in (
            "local_listening_records",
            "local_listening_domains",
            "local_listening_evaluation_choices",
            "local_listening_photo_groups",
            "local_listening_assets",
            "local_listening_operations",
        ):
            assert connection.execute(
                f'SELECT COUNT(*) FROM "{table}"'
            ).fetchone()[0] == 0
    finally:
        connection.close()


def test_failed_migration_preserves_original_database(tmp_path) -> None:
    root = tmp_path / "bad"
    db = root / "kindergarten.db"
    data = root / "data"
    create_old_0007_fixture(db, data)
    command.upgrade(alembic_config(db), OLD_0008)
    connection = sqlite3.connect(str(db))
    try:
        connection.execute("CREATE TABLE local_listening_records (x TEXT)")
        connection.commit()
    finally:
        connection.close()
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    with pytest.raises(LocalDatabaseStateError) as caught:
        ensure_local_schema(db)
    assert caught.value.code == "LOCAL_DB_MIGRATION_FAILED"
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before
    connection = sqlite3.connect(str(db))
    try:
        assert connection.execute(
            "SELECT version_num FROM local_alembic_version"
        ).fetchone() == (OLD_0008,)
        assert connection.execute(
            "SELECT COUNT(*) FROM local_profile"
        ).fetchone()[0] == 1
    finally:
        connection.close()


def test_backup_rejects_forged_receipt_or_invalid_json(tmp_path) -> None:
    from app.local import backup_validate

    runtime = _runtime(tmp_path)
    try:
        profile_id, term_id = _initials(runtime)
        session = runtime.session()
        try:
            first = listening_service.create_record(
                session,
                profile_id=profile_id,
                request_id=__import__("uuid").uuid4(),
                term_id=term_id,
                child_name="同名甲",
            )
            second = listening_service.create_record(
                session,
                profile_id=profile_id,
                request_id=__import__("uuid").uuid4(),
                term_id=term_id,
                child_name="同名乙",
            )
            record = listening_service.read_record(
                session, profile_id=profile_id, record_id=first["record_id"]
            )
            request_id = str(__import__("uuid").uuid4())
            saved = listening_service.save_domain(
                session,
                profile_id=profile_id,
                record_id=first["record_id"],
                domain="health",
                request_id=request_id,
                expected_revision=record["revision"],
                patch={"goal": "甲的目标"},
            )
        finally:
            session.close()
        scratch = tmp_path / "schema"
        scratch.mkdir()
        copy_path = tmp_path / "forged.db"

        def _copy() -> None:
            source = sqlite3.connect(str(runtime.db_path))
            target = sqlite3.connect(str(copy_path))
            try:
                source.backup(target)
            finally:
                target.close()
                source.close()

        _copy()
        backup_validate.validate_database(
            copy_path,
            migrate_old=False,
            require_current=True,
            scratch_dir=scratch,
        )
        connection = sqlite3.connect(str(copy_path))
        try:
            result = connection.execute(
                "SELECT result_json FROM local_listening_operations "
                "WHERE request_id = ?",
                (request_id,),
            ).fetchone()[0]
            forged = __import__("json").loads(result)
            forged["record_id"] = second["record_id"]
            connection.execute(
                "UPDATE local_listening_operations SET result_json = ? "
                "WHERE request_id = ?",
                (__import__("json").dumps(forged, ensure_ascii=False), request_id),
            )
            connection.commit()
        finally:
            connection.close()
        with pytest.raises(backup_validate.BackupValidationError) as caught:
            backup_validate.validate_database(
                copy_path,
                migrate_old=False,
                require_current=True,
                scratch_dir=scratch,
            )
        assert caught.value.code == "BACKUP_DB_LOGICAL_INVALID"

        _copy()
        connection = sqlite3.connect(str(copy_path))
        try:
            connection.execute(
                "UPDATE local_listening_operations SET result_json = '{bad' "
                "WHERE request_id = ?",
                (request_id,),
            )
            connection.commit()
        finally:
            connection.close()
        with pytest.raises(backup_validate.BackupValidationError):
            backup_validate.validate_database(
                copy_path,
                migrate_old=False,
                require_current=True,
                scratch_dir=scratch,
            )

        # Runtime replay also refuses a forged result instead of returning the
        # other same-name record's receipt.
        session = runtime.session()
        try:
            connection = sqlite3.connect(str(runtime.db_path))
            try:
                result = connection.execute(
                    "SELECT result_json FROM local_listening_operations "
                    "WHERE request_id = ?",
                    (request_id,),
                ).fetchone()[0]
                forged = __import__("json").loads(result)
                forged["record_id"] = second["record_id"]
                connection.execute(
                    "UPDATE local_listening_operations SET result_json = ? "
                    "WHERE request_id = ?",
                    (__import__("json").dumps(forged, ensure_ascii=False), request_id),
                )
                connection.commit()
            finally:
                connection.close()
            with pytest.raises(listening_service.ListeningRequestConflict):
                listening_service.save_domain(
                    session,
                    profile_id=profile_id,
                    record_id=first["record_id"],
                    domain="health",
                    request_id=request_id,
                    expected_revision=saved["revision"],
                    patch={"goal": "甲的目标"},
                )
        finally:
            session.close()
    finally:
        runtime.dispose()


def test_database_validation_checks_listening_rows(tmp_path) -> None:
    from app.local import backup_validate

    runtime = _runtime(tmp_path)
    try:
        profile_id, term_id = _initials(runtime)
        session = runtime.session()
        try:
            created = listening_service.create_record(
                session,
                profile_id=profile_id,
                request_id=__import__("uuid").uuid4(),
                term_id=term_id,
                child_name="校验幼儿",
            )
        finally:
            session.close()
        scratch = tmp_path / "schema"
        scratch.mkdir()
        from app.local import backup_validate as validate

        copy_path = tmp_path / "copy.db"

        def _copy_database() -> None:
            source = sqlite3.connect(str(runtime.db_path))
            target = sqlite3.connect(str(copy_path))
            try:
                source.backup(target)
            finally:
                target.close()
                source.close()

        _copy_database()
        validate.validate_database(
            copy_path,
            migrate_old=False,
            require_current=True,
            scratch_dir=scratch,
        )
        connection = sqlite3.connect(str(runtime.db_path))
        try:
            connection.execute(
                "DELETE FROM local_listening_evaluation_choices "
                "WHERE record_id = ? AND domain = 'health' AND item_id = 'health_1'",
                (created["record_id"],),
            )
            connection.commit()
        finally:
            connection.close()
        copy_path.unlink()
        _copy_database()
        with pytest.raises(backup_validate.BackupValidationError) as caught:
            validate.validate_database(
                copy_path,
                migrate_old=False,
                require_current=True,
                scratch_dir=scratch,
            )
        assert caught.value.code == "BACKUP_DB_LOGICAL_INVALID"
    finally:
        runtime.dispose()
