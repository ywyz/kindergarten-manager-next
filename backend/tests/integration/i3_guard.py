"""Shared guard + helpers for I3 MySQL integration tests.

Strict isolation rules:
* Enabled only when I3_TEST_ALLOW_DESTRUCTIVE=yes AND I3_TEST_DATABASE_URL is
  set AND the URL's schema is one of the two whitelisted I3 databases AND the
  host is 127.0.0.1/localhost AND the driver is mysql+pymysql.
* Any other database name (including the I1/I2 test databases) is refused
  before any connection is made.
* Tests never run migrations themselves and never execute unless explicitly
  enabled; this suite only delivers test code for the authorized run.

Current slice-5 readiness: HTTP routes exist since slice 3, but these tests
still exercise the I3 service/transaction layer (and the plan-create vs
config-confirm lock order) directly against real MySQL 8.4 / InnoDB, never
through HTTP. SQLite is never used. The suite — including the restart-
persistence and both submission-order lock cases — is written but has not
been executed yet.
"""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from urllib.parse import urlsplit

os.environ["APP_DISABLE_DOTENV"] = "1"

ALLOWED_DATABASES = frozenset(
    {"kindergarten_test_i3", "kindergarten_test_i3_fresh"}
)
_ALLOWED_PORT = 13384

_database_url = os.environ.get("I3_TEST_DATABASE_URL")


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


def _enabled() -> bool:
    if os.environ.get("I3_TEST_ALLOW_DESTRUCTIVE") != "yes":
        return False
    if not _database_url:
        return False
    if _database_driver(_database_url) != "mysql+pymysql":
        raise RuntimeError(
            "I3 integration tests require mysql+pymysql driver"
        )
    host = _database_host(_database_url)
    if host not in ("127.0.0.1", "localhost"):
        raise RuntimeError(
            "I3 integration tests only run against 127.0.0.1/localhost"
        )
    port = _database_port(_database_url)
    if port != _ALLOWED_PORT:
        raise RuntimeError(
            f"I3 integration tests only run against port {_ALLOWED_PORT} "
            f"(got {port})"
        )
    db_name = _database_name(_database_url)
    if db_name not in ALLOWED_DATABASES:
        raise RuntimeError(
            "I3 integration tests refuse to run against non-whitelisted "
            f"database: {db_name!r}"
        )
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
        "I3 MySQL integration tests disabled; set I3_TEST_ALLOW_DESTRUCTIVE=yes "
        "and I3_TEST_DATABASE_URL to a whitelisted I3 database.",
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
            "App settings DATABASE_URL points outside the whitelisted I3 target"
        )

    engine = create_engine(_database_url, poolclass=NullPool, future=True)
    if configured != engine.url:
        raise AssertionError(
            "App settings DATABASE_URL does not match I3_TEST_DATABASE_URL; "
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


def ensure_schema(engine) -> None:
    required_tables = (
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


def reset_i3_tables(engine) -> None:
    """Independent per-test cleanup of I3 + I2 + identity rows (child first)."""
    order = [
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
    "reset_i3_tables",
]
