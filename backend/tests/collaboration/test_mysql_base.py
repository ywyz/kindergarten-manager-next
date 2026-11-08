"""Static and opt-in MySQL 8.4 checks for the collaboration slice.

The integration class runs only when ``KGM_COLLAB_TEST_DATABASE_URL`` is set
to an explicit ``mysql+pymysql://`` URL.  It requires a fresh database (zero
tables), applies the explicit migration file once and reports the real server
version and database name.  It never creates a database, drops tables, reads a
real secret or runs during ordinary unit-test discovery without that URL.
"""

from __future__ import annotations

import os
import re
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.mysql import dialect as mysql_dialect
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateTable

from app.collaboration.config import CollaborationSettings
from app.collaboration.db import create_collaboration_engine
from app.collaboration.errors import CollaborationError
from app.collaboration.models import (
    Classroom,
    CollaborationBase,
    CollaborationOperation,
    School,
    Teacher,
    TeacherClassMembership,
    TeacherGameConfig,
    TeacherToken,
    UTCDateTime,
)
from app.collaboration.security import (
    authenticate,
    digest_bearer_token,
    issue_bearer_token,
    normalize_utc,
)
from app.collaboration.service import get_own_config, save_config
from app.collaboration.schemas import ConfigSaveIn
from app.local.schemas import ConfigClassGamesChangeIn

REPO = Path(__file__).resolve().parents[3]
BACKEND = REPO / "backend"
MYSQL_MIGRATION = (
    BACKEND / "migrations_collaboration" / "mysql" / "0001_initial.sql"
)
POSTGRES_MIGRATION = (
    BACKEND / "migrations_collaboration" / "0001_initial.sql"
)
SYNTHETIC_PEPPER = "synthetic-collaboration-pepper-0123456789"
SYNTHETIC_PREVIEW = "synthetic-collaboration-preview-0123456789"


def _settings(url: str) -> CollaborationSettings:
    return CollaborationSettings(
        database_url=url,
        token_pepper=SYNTHETIC_PEPPER,
        preview_secret=SYNTHETIC_PREVIEW,
    )


class CollaborationConfigAndModelTests(unittest.TestCase):
    def test_mysql_url_is_accepted_and_other_backends_are_rejected(self):
        settings = _settings("mysql+pymysql://user:pass@localhost:3306/collab_test")
        settings.validate()
        for url in (
            "sqlite:///collab.db",
            "postgresql+psycopg://user:pass@localhost:5432/collab_test",
            "postgresql://user:pass@localhost:5432/collab_test",
            "mysql://user:pass@localhost:3306/collab_test",
            "mysql+pymysql://user:pass@localhost:3306/",
            "mysql+pymysql:///collab_test",
        ):
            with self.subTest(url=url):
                with self.assertRaises(RuntimeError):
                    _settings(url).validate()

    def test_engine_rejects_non_mysql_schemes(self):
        for url in (
            "sqlite:///collab.db",
            "postgresql+psycopg://user:pass@localhost:5432/collab_test",
        ):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    create_collaboration_engine(_settings(url))

    def test_engine_is_mysql_read_committed_and_hides_parameters(self):
        settings = _settings("mysql+pymysql://user:pass@localhost:3306/collab_test")
        engine = create_collaboration_engine(settings)
        self.addCleanup(engine.dispose)
        self.assertEqual(engine.dialect.name, "mysql")
        self.assertEqual(engine.dialect.driver, "pymysql")
        self.assertEqual(
            engine.dialect._on_connect_isolation_level, "READ COMMITTED"
        )
        self.assertTrue(engine.hide_parameters)
        self.assertFalse(engine.echo)
        self.assertEqual(engine.pool.size(), 5)
        self.assertEqual(engine.pool._recycle, 1800)
        self.assertEqual(engine.url.database, "collab_test")

    def test_mysql_models_have_no_fixed_schema_and_use_mysql_types(self):
        dialect = mysql_dialect()
        expected_tables = (
            "schools",
            "classes",
            "teachers",
            "teacher_tokens",
            "teacher_class_memberships",
            "teacher_game_configs",
            "operations",
        )
        for name in expected_tables:
            table = CollaborationBase.metadata.tables[name]
            ddl = str(CreateTable(table).compile(dialect=dialect))
            self.assertNotIn("collaboration.", ddl)
            self.assertIn("ENGINE=InnoDB", ddl)
            self.assertIn("CHAR(32)", ddl)
            self.assertIn("DATETIME(6)", ddl)
            self.assertIn("utf8mb4_0900_ai_ci", ddl)
        config_ddl = str(
            CreateTable(TeacherGameConfig.__table__).compile(dialect=dialect)
        )
        operation_ddl = str(
            CreateTable(CollaborationOperation.__table__).compile(dialect=dialect)
        )
        self.assertIn(" JSON", config_ddl)
        self.assertIn(" JSON", operation_ddl)
        self.assertIn("ascii_bin", config_ddl)
        self.assertIn("ascii_bin", operation_ddl)
        for table in (
            CollaborationBase.metadata.tables["schools"],
            CollaborationBase.metadata.tables["classes"],
            CollaborationBase.metadata.tables["teachers"],
            CollaborationBase.metadata.tables["teacher_tokens"],
            CollaborationBase.metadata.tables["teacher_game_configs"],
        ):
            self.assertIn(
                "char_length",
                str(CreateTable(table).compile(dialect=dialect)).lower(),
            )

    def test_mysql_migration_is_explicit_and_stops_on_partial_ddl(self):
        sql = MYSQL_MIGRATION.read_text(encoding="utf-8")
        upper = sql.upper()
        self.assertNotIn("CREATE DATABASE", upper)
        self.assertNotIn("CREATE SCHEMA", upper)
        self.assertNotIn("DROP TABLE", upper)
        self.assertNotRegex(sql, r"(?im)^\s*USE\s+")
        self.assertEqual(sql.count("CREATE TABLE"), 7)
        self.assertEqual(sql.count("ENGINE=InnoDB"), 7)
        for marker in (
            "CHAR(32)",
            "CHAR_LENGTH",
            "DATETIME(6)",
            "JSON",
            "READ COMMITTED",
            "CURRENT_TIMESTAMP(6)",
            "DDL auto-commits",
            "STOP",
            "CONSTRAINT uq_classes_id_school UNIQUE (id, school_id)",
            "CONSTRAINT uq_teachers_id_school UNIQUE (id, school_id)",
            "CONSTRAINT uq_teacher_tokens_hash UNIQUE (token_hash)",
            "CONSTRAINT fk_membership_teacher_school",
            "CONSTRAINT fk_config_class_school",
            "CONSTRAINT fk_operations_source_school",
            "ascii_bin",
        ):
            self.assertIn(marker, sql)
        self.assertNotIn("JSONB", upper)

    def test_historical_postgresql_sql_is_retained(self):
        sql = POSTGRES_MIGRATION.read_text(encoding="utf-8")
        self.assertIn("CREATE SCHEMA IF NOT EXISTS collaboration", sql)
        self.assertIn("jsonb", sql)
        self.assertIn("timestamptz", sql)

    def test_utc_type_normalizes_naive_and_aware_values(self):
        dialect = mysql_dialect()
        utc = UTCDateTime()
        aware = datetime(2026, 11, 8, 1, 2, 3, 456789, tzinfo=timezone.utc)
        bound = utc.process_bind_param(aware, dialect)
        self.assertIsNone(bound.tzinfo)
        self.assertEqual(bound.microsecond, 456789)
        loaded = utc.process_result_value(bound, dialect)
        self.assertEqual(loaded, aware)
        naive = datetime(2026, 11, 8, 1, 2, 3, 456789)
        self.assertEqual(normalize_utc(naive), aware)
        self.assertEqual(
            normalize_utc(aware.astimezone(timezone(timedelta(hours=8)))),
            aware,
        )

    def test_auth_token_hash_and_preview_shapes_remain_compatible(self):
        token, digest = issue_bearer_token(SYNTHETIC_PEPPER)
        self.assertEqual(len(token), 43)
        self.assertEqual(len(digest), 64)
        self.assertEqual(digest, digest_bearer_token(token, SYNTHETIC_PEPPER))


@unittest.skipUnless(
    os.environ.get("KGM_COLLAB_TEST_DATABASE_URL", "").strip(),
    "set KGM_COLLAB_TEST_DATABASE_URL to a fresh independent MySQL 8.4 database",
)
class CollaborationMySQLIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        url = os.environ["KGM_COLLAB_TEST_DATABASE_URL"].strip()
        settings = _settings(url)
        settings.validate()
        parsed = make_url(url)
        if parsed.drivername != "mysql+pymysql":
            raise AssertionError("integration URL must use mysql+pymysql://")
        cls.settings = settings
        cls.engine = create_collaboration_engine(settings)
        cls.addClassCleanup(cls.engine.dispose)
        with cls.engine.connect() as connection:
            version = connection.exec_driver_sql("SELECT VERSION()").scalar_one()
            database = connection.exec_driver_sql("SELECT DATABASE()").scalar_one()
            table_count = connection.exec_driver_sql(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema = DATABASE()"
            ).scalar_one()
            isolation = connection.exec_driver_sql(
                "SELECT @@transaction_isolation"
            ).scalar_one()
            time_zone = connection.exec_driver_sql(
                "SELECT @@session.time_zone"
            ).scalar_one()
            sql_mode = connection.exec_driver_sql("SELECT @@session.sql_mode").scalar_one()
        if not str(version).startswith("8.4."):
            raise AssertionError(f"MySQL 8.4 required, got {version!r}")
        if table_count != 0:
            raise AssertionError(
                f"integration database {database!r} is not fresh: {table_count} tables"
            )
        if str(database) != str(parsed.database):
            raise AssertionError(
                f"selected database mismatch: {database!r} != {parsed.database!r}"
            )
        if str(isolation).replace("_", "-") != "READ-COMMITTED":
            raise AssertionError(f"READ COMMITTED required, got {isolation!r}")
        if str(time_zone) != "+00:00":
            raise AssertionError(f"UTC session required, got {time_zone!r}")
        if "STRICT_ALL_TABLES" not in str(sql_mode):
            raise AssertionError(f"strict SQL mode required, got {sql_mode!r}")
        try:
            from importlib.metadata import version as package_version

            pymysql_version = package_version("PyMySQL")
        except Exception:  # noqa: BLE001 - diagnostics only
            pymysql_version = "unknown"
        import sqlalchemy

        print(
            f"KGM_MYSQL_VERSION={version} "
            f"KGM_MYSQL_DATABASE={database} "
            f"KGM_MYSQL_TRANSACTION_ISOLATION={isolation} "
            f"KGM_MYSQL_TIME_ZONE={time_zone} "
            f"KGM_SQLALCHEMY_VERSION={sqlalchemy.__version__} "
            f"KGM_PYMYSQL_VERSION={pymysql_version}"
        )
        statements = _sql_statements(MYSQL_MIGRATION.read_text(encoding="utf-8"))
        raw = cls.engine.raw_connection()
        try:
            cursor = raw.cursor()
            for statement in statements:
                cursor.execute(statement)
            raw.commit()
        finally:
            raw.close()
        with cls.engine.connect() as connection:
            tables = connection.exec_driver_sql(
                "SELECT TABLE_NAME, ENGINE, TABLE_COLLATION "
                "FROM information_schema.tables WHERE table_schema = DATABASE()"
            ).all()
            columns = connection.exec_driver_sql(
                "SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, "
                "CHARACTER_MAXIMUM_LENGTH, DATETIME_PRECISION, COLUMN_TYPE "
                "FROM information_schema.columns WHERE table_schema = DATABASE()"
            ).all()
            fks = connection.exec_driver_sql(
                "SELECT CONSTRAINT_NAME, TABLE_NAME, REFERENCED_TABLE_NAME "
                "FROM information_schema.referential_constraints "
                "WHERE constraint_schema = DATABASE()"
            ).all()
        if len(tables) != 7 or any(row[1] != "InnoDB" for row in tables):
            raise AssertionError(f"unexpected tables/engines: {tables!r}")
        id_columns = [
            row for row in columns
            if row[1] in {"id", "teacher_id", "school_id", "class_id",
                          "membership_generation", "actor_teacher_id",
                          "request_id", "source_teacher_id"}
        ]
        if not id_columns or any(row[3] != 32 for row in id_columns):
            raise AssertionError(f"UUID character mapping mismatch: {id_columns!r}")
        timestamp_columns = [row for row in columns if row[2] == "datetime"]
        if not timestamp_columns or any(row[4] != 6 for row in timestamp_columns):
            raise AssertionError(f"microsecond datetime mismatch: {timestamp_columns!r}")
        json_columns = [row for row in columns if row[2] == "json"]
        if {row[1] for row in json_columns} != {"payload", "result_json"}:
            raise AssertionError(f"JSON mapping mismatch: {json_columns!r}")
        if len(fks) != 10:
            raise AssertionError(f"unexpected foreign keys: {fks!r}")
        cls.Session = sessionmaker(
            bind=cls.engine, autoflush=False, expire_on_commit=False
        )
        cls.database = database
        cls.version = version

    def test_service_version_replay_and_concurrent_conflict(self):
        from app.collaboration.security import TeacherPrincipal

        school_id = uuid4()
        class_id = uuid4()
        teacher_id = uuid4()
        with self.Session() as session:
            with session.begin():
                session.add(School(id=school_id, name="合成幼儿园"))
                session.flush()
                session.add_all(
                    [
                        Classroom(
                            id=class_id,
                            school_id=school_id,
                            display_name="中一班",
                        ),
                        Teacher(
                            id=teacher_id,
                            school_id=school_id,
                            display_name="合成教师",
                            active=True,
                        ),
                    ]
                )
                session.flush()
                session.add(
                    TeacherClassMembership(
                        teacher_id=teacher_id,
                        school_id=school_id,
                        class_id=class_id,
                        membership_generation=uuid4(),
                        selected_at=datetime.now(timezone.utc),
                        updated_at=datetime.now(timezone.utc),
                    )
                )
        principal = TeacherPrincipal(
            teacher_id=teacher_id,
            school_id=school_id,
            display_name="合成教师",
            school_name="合成幼儿园",
            token_id=uuid4(),
        )
        change = ConfigClassGamesChangeIn(
            kind="class_games",
            locations=[{"kind": "area", "name": "积木区", "guidance": "轻声"}],
            game_scope="室内",
            guidance=None,
        )
        request_id = uuid4()
        first = ConfigSaveIn(
            request_id=request_id,
            class_id=class_id,
            expected_version=0,
            change=change,
        )
        with self.Session() as session:
            saved = save_config(session, principal, first)
        self.assertEqual(saved.config_version, 1)
        self.assertTrue(saved.changed)
        with self.Session() as session:
            replay = save_config(session, principal, first)
        self.assertEqual(replay.config_version, 1)
        self.assertTrue(replay.replayed)
        with self.Session() as session:
            with self.assertRaises(CollaborationError) as stale:
                save_config(
                    session,
                    principal,
                    ConfigSaveIn(
                        request_id=uuid4(),
                        class_id=class_id,
                        expected_version=0,
                        change=change,
                    ),
                )
        self.assertEqual(stale.exception.code, "TARGET_VERSION_CHANGED")

        results: list[tuple[str, object]] = []
        barrier = threading.Barrier(2)

        def worker(worker_id: int) -> None:
            with self.Session() as session:
                barrier.wait()
                try:
                    value = save_config(
                        session,
                        principal,
                        ConfigSaveIn(
                            request_id=uuid4(),
                            class_id=class_id,
                            expected_version=1,
                            change=ConfigClassGamesChangeIn(
                                kind="class_games",
                                locations=[
                                    {
                                        "kind": "area",
                                        "name": f"积木区{worker_id}",
                                        "guidance": None,
                                    }
                                ],
                                game_scope="室内",
                                guidance=None,
                            ),
                        ),
                    )
                    results.append(("ok", value.config_version))
                except CollaborationError as exc:
                    results.append(("error", exc.code))
                except Exception as exc:  # noqa: BLE001 - report class only
                    results.append(("error", type(exc).__name__))

        threads = [
            threading.Thread(target=worker, args=(index,)) for index in (1, 2)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(len(results), 2, results)
        self.assertEqual(sum(1 for kind, _ in results if kind == "ok"), 1, results)
        self.assertIn(("error", "TARGET_VERSION_CHANGED"), results)

        with self.Session() as session:
            current = get_own_config(session, principal)
        self.assertEqual(current.config_version, 2)
        self.assertEqual(current.payload.locations[0].kind, "area")
        self.assertEqual(
            self.engine.url.database, self.database
        )

    def test_auth_expiry_accepts_naive_mysql_datetime(self):
        from app.collaboration.security import TeacherPrincipal

        school_id = uuid4()
        class_id = uuid4()
        teacher_id = uuid4()
        token, digest = issue_bearer_token(SYNTHETIC_PEPPER)
        with self.Session() as session:
            with session.begin():
                session.add(School(id=school_id, name="合成幼儿园"))
                session.flush()
                session.add_all(
                    [
                        Classroom(
                            id=class_id,
                            school_id=school_id,
                            display_name="中二班",
                        ),
                        Teacher(
                            id=teacher_id,
                            school_id=school_id,
                            display_name="合成教师二",
                            active=True,
                        ),
                    ]
                )
                session.flush()
                session.add(
                    TeacherToken(
                        teacher_id=teacher_id,
                        token_hash=digest,
                        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                    )
                )
        with self.Session() as session:
            principal: TeacherPrincipal = authenticate(
                session, token, SYNTHETIC_PEPPER
            )
        self.assertEqual(principal.teacher_id, teacher_id)
        with self.Session() as session:
            with session.begin():
                row = session.scalars(
                    select(TeacherToken).where(
                        TeacherToken.token_hash == digest
                    )
                ).one()
                row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        with self.Session() as session:
            with self.assertRaises(CollaborationError) as expired:
                authenticate(session, token, SYNTHETIC_PEPPER)
        self.assertEqual(expired.exception.code, "AUTH_REQUIRED")


def _sql_statements(sql: str) -> list[str]:
    text = "\n".join(
        line for line in sql.splitlines() if not line.lstrip().startswith("--")
    )
    return [statement.strip() for statement in text.split(";") if statement.strip()]
