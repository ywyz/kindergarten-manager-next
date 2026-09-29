"""Shared guard + helpers for I5 export MySQL integration tests.

Strict isolation rules (word-export spec §12 slice 3):
* Runs only when ``I5_TEST_ALLOW_DESTRUCTIVE=yes`` AND
  ``I5_TEST_DATABASE_URL`` is set AND the URL targets one of the two
  whitelisted I5 test databases on 127.0.0.1/localhost with the
  ``mysql+pymysql`` driver on the dedicated I5 port 13386.
* Any other schema name — including the I1/I2/I3/I4 suites, dev and
  production names — is refused **before any connection is opened**.
* This guard shares no destructive switch with I2/I3/I4, so the suites can
  never be pointed at each other's data by accident.
* ``APP_DISABLE_DOTENV=1`` is forced so no project ``.env`` DSN can leak.
* I5 adds no migrations; the authorized run applies the existing
  ``alembic upgrade head`` chain (head ``20260924_i4_weekly_plans``) and
  this module verifies the result.
"""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from urllib.parse import urlsplit

os.environ["APP_DISABLE_DOTENV"] = "1"

ALLOWED_DATABASES = frozenset(
    {"kindergarten_test_i5", "kindergarten_test_i5_fresh"}
)
# I2/I3 use 13384, I4 uses 13385; I5 owns 13386 so the suites cannot
# cross-connect.
_ALLOWED_PORT = 13386

_database_url = os.environ.get("I5_TEST_DATABASE_URL")

# Other suites' exact database names plus shared/dev/prod markers.
_FORBIDDEN_DATABASES = frozenset(
    {
        "kindergarten_test_i1",
        "kindergarten_test_i2",
        "kindergarten_test_i3",
        "kindergarten_test_i4",
        "kindergarten_test_i4_fresh",
        "kindergarten_test",
        "kindergarten_dev",
        "kindergarten_prod",
        "kindergarten",
        "production",
    }
)


def _database_name(url: str | None) -> str | None:
    if not url:
        return None
    return urlsplit(url).path.lstrip("/") or None


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


def _refuse_forbidden_schema(db_name: str | None) -> None:
    if db_name is None:
        raise RuntimeError("I5 integration tests require an explicit database name")
    if db_name in ALLOWED_DATABASES:
        return
    if db_name in _FORBIDDEN_DATABASES:
        raise RuntimeError(
            "I5 integration tests refuse non-I5 database "
            f"{db_name!r} (other suites, shared or production are blocked)"
        )
    if db_name.startswith("kindergarten_prod") or db_name.startswith(
        "production"
    ):
        raise RuntimeError(f"I5 integration tests refuse database {db_name!r}")
    raise RuntimeError(
        "I5 integration tests refuse to run against non-whitelisted "
        f"database: {db_name!r}"
    )


def _enabled() -> bool:
    if os.environ.get("I5_TEST_ALLOW_DESTRUCTIVE") != "yes":
        return False
    if not _database_url:
        return False
    if _database_driver(_database_url) != "mysql+pymysql":
        raise RuntimeError("I5 integration tests require mysql+pymysql driver")
    host = _database_host(_database_url)
    if host not in ("127.0.0.1", "localhost"):
        raise RuntimeError(
            f"I5 integration tests only run against 127.0.0.1/localhost (got {host!r})"
        )
    port = _database_port(_database_url)
    if port != _ALLOWED_PORT:
        raise RuntimeError(
            f"I5 integration tests only run against port {_ALLOWED_PORT} (got {port})"
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

if INTEGRATION_ENABLED and settings.database_url.get_secret_value() != (
    _database_url or ""
):
    # app.config may have been imported before this guard (empty or other DSN).
    from pydantic import SecretStr

    settings.database_url = SecretStr(_database_url)


def skip_unless_enabled(cls):
    return unittest.skipUnless(
        INTEGRATION_ENABLED,
        "I5 MySQL integration tests disabled; set I5_TEST_ALLOW_DESTRUCTIVE=yes "
        "and I5_TEST_DATABASE_URL to a whitelisted I5 database.",
    )(cls)


def require_authorized_url(raw_url: str) -> None:
    url = make_url(raw_url)
    if url.drivername != "mysql+pymysql":
        raise AssertionError("Only mysql+pymysql URLs are supported")
    if url.host not in ("127.0.0.1", "localhost"):
        raise AssertionError("Integration tests only run against 127.0.0.1/localhost")
    if url.port != _ALLOWED_PORT:
        raise AssertionError(
            f"I5 integration tests only run against port {_ALLOWED_PORT}"
        )
    if url.database not in ALLOWED_DATABASES:
        raise AssertionError(
            f"I5 integration tests require database in {ALLOWED_DATABASES}"
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
            "App settings DATABASE_URL points outside the whitelisted I5 target"
        )

    engine = create_engine(_database_url, poolclass=NullPool, future=True)
    if configured != engine.url:
        raise AssertionError(
            "App settings DATABASE_URL does not match I5_TEST_DATABASE_URL; "
            "possible module pre-loading with a different DSN."
        )

    from app.database import _engine as app_engine

    if app_engine is not None and configured != app_engine.url:
        raise AssertionError(
            "App engine singleton target does not match the test target; "
            "possible module pre-loading with a different DSN."
        )

    return engine


def check_environment(engine) -> tuple[str, str]:
    """Assert MySQL 8.4 + InnoDB; return ``(version, database)`` for logs."""
    with engine.connect() as conn:
        version = conn.execute(text("SELECT VERSION()")).scalar()
        database = conn.execute(text("SELECT DATABASE()")).scalar()
        engine_var = conn.execute(
            text("SHOW VARIABLES LIKE 'default_storage_engine'")
        ).fetchone()

    if not version or not version.startswith("8.4"):
        raise AssertionError(f"I5 integration requires MySQL 8.4, found {version}")
    if not engine_var or engine_var[1].lower() != "innodb":
        raise AssertionError("MySQL default storage engine must be InnoDB")
    return version, database


ALL_TABLES = (
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
)

_REQUIRED_TABLES = tuple(ALL_TABLES)


def ensure_schema(engine) -> str:
    """Verify the migration chain is applied and structurally sound."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT table_name, engine FROM information_schema.tables "
                "WHERE table_schema = DATABASE() AND table_name IN :names"
            ),
            {"names": _REQUIRED_TABLES},
        ).fetchall()
        found = {row[0]: row[1] for row in rows}
        missing = set(_REQUIRED_TABLES) - set(found)
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
                f"Expected head 20260924_i4_weekly_plans, found {revision!r}"
            )
    return revision


def reset_i5_tables(engine) -> None:
    """Independent per-test cleanup (child tables first, FK checks off)."""
    stamp = datetime.now(timezone.utc).replace(tzinfo=None)
    with engine.begin() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
        for table in ALL_TABLES:
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
    "reset_i5_tables",
    "ALL_TABLES",
    "ALLOWED_DATABASES",
]
