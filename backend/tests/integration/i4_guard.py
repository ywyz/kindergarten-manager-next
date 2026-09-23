"""Shared guard + helpers for I4 MySQL integration tests.

Strict isolation rules (spec §12):
* Runs only when ``I4_TEST_ALLOW_DESTRUCTIVE=yes`` AND
  ``I4_TEST_DATABASE_URL`` is set AND the URL targets one of the two
  whitelisted I4 databases on 127.0.0.1/localhost with the mysql+pymysql
  driver on the dedicated I4 port.
* Any other schema name — including production, shared and the I1/I2/I3
  test databases — is refused *before any connection is opened*.
* This guard intentionally does NOT reuse the I3 destructive switch so the
  two suites can never be pointed at each other's data by accident.
* ``APP_DISABLE_DOTENV=1`` is forced here so no project ``.env`` DSN can
  leak into an I4 run.
* Tests never run migrations; the authorized run applies
  ``alembic upgrade head`` first and the suite only verifies the result.
"""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from urllib.parse import urlsplit

os.environ["APP_DISABLE_DOTENV"] = "1"

ALLOWED_DATABASES = frozenset(
    {"kindergarten_test_i4", "kindergarten_test_i4_fresh"}
)
# I3 uses 13384; I4 owns 13385 so the suites cannot cross-connect.
_ALLOWED_PORT = 13385

_database_url = os.environ.get("I4_TEST_DATABASE_URL")

# Names that must never be reachable from this suite.
_FORBIDDEN_DATABASE_MARKERS = (
    "kindergarten_test_i1",
    "kindergarten_test_i2",
    "kindergarten_test_i3",
    "kindergarten_test",
    "kindergarten_dev",
    "kindergarten_prod",
    "production",
)


def _database_name(url: str | None) -> str | None:
    if not url:
        return None
    path = urlsplit(url).path
    return path.lstrip("/") or None


def _database_host(url: str | None) -> str | None:
    if not url:
        return None
    return urlsplit(url).hostname


def _database_port(url: str | None) -> int | None:
    if not url:
        return None
    return urlsplit(url).port


def _database_driver(url: str | None) -> str | None:
    if not url:
        return None
    return urlsplit(url).scheme


def _refuse_non_local(url: str) -> None:
    host = _database_host(url)
    if host not in ("127.0.0.1", "localhost"):
        raise RuntimeError(
            f"I4 integration tests only run against 127.0.0.1/localhost (got {host!r})"
        )


def _refuse_forbidden_schema(db_name: str | None) -> None:
    if db_name is None:
        raise RuntimeError("I4 integration tests require an explicit database name")
    if db_name in ALLOWED_DATABASES:
        return
    for marker in _FORBIDDEN_DATABASE_MARKERS:
        if db_name == marker or db_name.startswith(marker):
            raise RuntimeError(
                "I4 integration tests refuse non-I4 database "
                f"{db_name!r} (I1/I2/I3, shared or production targets are blocked)"
            )
    raise RuntimeError(
        "I4 integration tests refuse to run against non-whitelisted "
        f"database: {db_name!r}"
    )


def _enabled() -> bool:
    if os.environ.get("I4_TEST_ALLOW_DESTRUCTIVE") != "yes":
        return False
    if not _database_url:
        return False
    if _database_driver(_database_url) != "mysql+pymysql":
        raise RuntimeError(
            "I4 integration tests require mysql+pymysql driver"
        )
    _refuse_non_local(_database_url)
    port = _database_port(_database_url)
    if port != _ALLOWED_PORT:
        raise RuntimeError(
            f"I4 integration tests only run against port {_ALLOWED_PORT} "
            f"(got {port})"
        )
    _refuse_forbidden_schema(_database_name(_database_url))
    return True


INTEGRATION_ENABLED = _enabled()

if INTEGRATION_ENABLED:
    os.environ["DATABASE_URL"] = _database_url

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app.config import settings  # noqa: E402

if INTEGRATION_ENABLED and not settings.database_url.get_secret_value():
    # app.config may have been imported before this guard (empty DSN).
    from pydantic import SecretStr

    settings.database_url = SecretStr(_database_url)


def skip_unless_enabled(cls):
    return unittest.skipUnless(
        INTEGRATION_ENABLED,
        "I4 MySQL integration tests disabled; set I4_TEST_ALLOW_DESTRUCTIVE=yes "
        "and I4_TEST_DATABASE_URL to a whitelisted I4 database.",
    )(cls)


def require_authorized_url(raw_url: str) -> None:
    url = make_url(raw_url)
    if url.drivername != "mysql+pymysql":
        raise AssertionError("Only mysql+pymysql URLs are supported")
    if url.host not in ("127.0.0.1", "localhost"):
        raise AssertionError("Integration tests only run against 127.0.0.1/localhost")
    if url.port != _ALLOWED_PORT:
        raise AssertionError(
            f"Integration tests only run against port {_ALLOWED_PORT}"
        )
    if url.database not in ALLOWED_DATABASES:
        raise AssertionError(
            f"Integration tests require database in {ALLOWED_DATABASES}"
        )


def make_engine():
    configured_raw = settings.database_url.get_secret_value()
    if not configured_raw:
        raise AssertionError("DATABASE_URL is not configured")

    configured = make_url(configured_raw)
    if (
        configured.drivername != "mysql+pymysql"
        or configured.host not in ("127.0.0.1", "localhost")
        or configured.port != _ALLOWED_PORT
        or configured.database not in ALLOWED_DATABASES
    ):
        raise AssertionError(
            "App settings DATABASE_URL points outside the whitelisted I4 target"
        )

    engine = create_engine(_database_url, poolclass=NullPool, future=True)
    if configured != engine.url:
        raise AssertionError(
            "App settings DATABASE_URL does not match I4_TEST_DATABASE_URL; "
            "possible module pre-loading with a different DSN."
        )

    from app.database import _engine as app_engine

    if app_engine is not None and configured != app_engine.url:
        raise AssertionError(
            "App engine singleton target does not match the test target; "
            "possible module pre-loading with a different DSN."
        )

    return engine


def check_environment(engine) -> None:
    with engine.connect() as conn:
        version = conn.execute(text("SELECT VERSION()")).scalar()
        engine_var = conn.execute(
            text("SHOW VARIABLES LIKE 'default_storage_engine'")
        ).fetchone()

    if not version or not version.startswith("8.4"):
        raise AssertionError(f"MySQL 8.4 required, found {version}")
    if not engine_var or engine_var[1].lower() != "innodb":
        raise AssertionError("MySQL default storage engine must be InnoDB")


I4_TABLES = (
    "weekly_plans",
    "weekly_plan_contents",
    "weekly_plan_confirmed_contents",
)

I3_TABLES = (
    "accounts",
    "first_admin_control",
    "sessions",
    "operation_records",
    "school_settings",
    "classes",
    "teacher_assignments",
    "terms",
    "calendar_revisions",
    "calendar_days",
    "configuration_changes",
    "daily_plans",
    "daily_plan_contents",
    "weekly_plan_sync_states",
)


def ensure_schema(engine) -> None:
    """Verify the I4 migration chain is applied and structurally sound."""
    required_tables = I3_TABLES + I4_TABLES
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT table_name, engine FROM information_schema.tables "
                "WHERE table_schema = DATABASE() AND table_name IN :names"
            ),
            {"names": required_tables},
        ).fetchall()
        found = {row[0]: row[1] for row in rows}
        missing = set(required_tables) - set(found)
        if missing:
            raise AssertionError(
                f"Schema missing tables {missing}; run 'alembic upgrade head' first."
            )
        non_innodb = [t for t, e in found.items() if e.lower() != "innodb"]
        if non_innodb:
            raise AssertionError(f"Tables must use InnoDB: {non_innodb}")

        revision = conn.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar()
        if revision != "20260924_i4_weekly_plans":
            raise AssertionError(
                f"I4 schema must be at 20260924_i4_weekly_plans, found {revision!r}"
            )

        fk_rows = conn.execute(
            text(
                "SELECT constraint_name, column_name FROM "
                "information_schema.key_column_usage "
                "WHERE table_schema = DATABASE() "
                "AND constraint_name IN "
                "('fk_weekly_plans_current_draft_content', "
                "'fk_weekly_plans_current_confirmed_content') "
                "ORDER BY constraint_name, ordinal_position"
            )
        ).fetchall()
        by_fk: dict[str, list[str]] = {}
        for name, column in fk_rows:
            by_fk.setdefault(name, []).append(column)
        expected_fk = {
            "fk_weekly_plans_current_draft_content": [
                "id",
                "current_draft_content_id",
                "current_draft_version",
            ],
            "fk_weekly_plans_current_confirmed_content": [
                "id",
                "current_confirmed_content_id",
                "current_confirmed_content_version",
            ],
        }
        if by_fk != expected_fk:
            raise AssertionError(
                f"Composite pointer foreign keys incorrect: {by_fk}"
            )

        unique = conn.execute(
            text(
                "SELECT constraint_name FROM information_schema.table_constraints "
                "WHERE table_schema = DATABASE() AND constraint_name = "
                "'uq_weekly_plans_class_term_effective_week'"
            )
        ).scalar()
        if unique is None:
            raise AssertionError(
                "Missing unique key uq_weekly_plans_class_term_effective_week"
            )

        check_clause = conn.execute(
            text(
                "SELECT check_clause FROM information_schema.check_constraints "
                "WHERE constraint_schema = DATABASE() AND constraint_name = "
                "'ck_operation_record_target_type'"
            )
        ).scalar()
        if not check_clause or "weekly_plan" not in check_clause:
            raise AssertionError(
                f"operation_records CHECK must include weekly_plan: {check_clause!r}"
            )


def reset_i4_tables(engine) -> None:
    """Independent per-test cleanup (child tables first, FK checks off)."""
    order = [
        "weekly_plan_confirmed_contents",
        "weekly_plan_contents",
        "weekly_plans",
        "weekly_plan_sync_states",
        "daily_plan_contents",
        "daily_plans",
        "calendar_days",
        "calendar_revisions",
        "configuration_changes",
        "teacher_assignments",
        "classes",
        "terms",
        "operation_records",
        "sessions",
        "accounts",
        "school_settings",
        "first_admin_control",
    ]
    stamp = datetime.now(timezone.utc).replace(tzinfo=None)
    with engine.begin() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
        for table in order:
            conn.execute(text(f"DELETE FROM `{table}`"))
        conn.execute(
            text(
                "INSERT INTO first_admin_control (id, claimed, first_admin_id) "
                "VALUES ('singleton', 0, NULL)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO school_settings (id, school_name, version, "
                "schedule_version, plans_started_at, created_at, updated_at) "
                "VALUES ('singleton', NULL, 1, 1, NULL, :created_at, :updated_at)"
            ),
            {"created_at": stamp, "updated_at": stamp},
        )
        conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))


__all__ = [
    "INTEGRATION_ENABLED",
    "skip_unless_enabled",
    "make_engine",
    "require_authorized_url",
    "check_environment",
    "ensure_schema",
    "reset_i4_tables",
    "I4_TABLES",
    "I3_TABLES",
    "ALLOWED_DATABASES",
]
