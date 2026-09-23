"""Shared guard + helpers for I2 MySQL integration tests.

Strict isolation rules:
* Enabled only when I2_TEST_ALLOW_DESTRUCTIVE=yes AND I2_TEST_DATABASE_URL is
  set AND the URL's schema is one of the two whitelisted I2 databases AND the
  host is 127.0.0.1/localhost AND the driver is mysql+pymysql.
* Any other database name (including kindergarten_test_i1) is refused before
  any connection is made.
* Each test class gets independent cleanup: tables relevant to I2 are deleted
  and both control rows are reset inside setUp, never via a shared-state
  session.

Tests never run migrations themselves.
"""

from __future__ import annotations

import json
import os
import unittest
from urllib.parse import urlsplit

# Never let a stale .env change the test target out from under the guard.
os.environ["APP_DISABLE_DOTENV"] = "1"

ALLOWED_DATABASES = frozenset(
    {"kindergarten_test_i2", "kindergarten_test_i2_fresh"}
)
_ALLOWED_PORT = 13384

_database_url = os.environ.get("I2_TEST_DATABASE_URL")


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
    if os.environ.get("I2_TEST_ALLOW_DESTRUCTIVE") != "yes":
        return False
    if not _database_url:
        return False
    if _database_driver(_database_url) != "mysql+pymysql":
        raise RuntimeError(
            "I2 integration tests require mysql+pymysql driver"
        )
    host = _database_host(_database_url)
    if host not in ("127.0.0.1", "localhost"):
        raise RuntimeError(
            "I2 integration tests only run against 127.0.0.1/localhost"
        )
    port = _database_port(_database_url)
    if port != _ALLOWED_PORT:
        raise RuntimeError(
            f"I2 integration tests only run against port {_ALLOWED_PORT} "
            f"(got {port})"
        )
    db_name = _database_name(_database_url)
    if db_name not in ALLOWED_DATABASES:
        raise RuntimeError(
            "I2 integration tests refuse to run against non-whitelisted "
            f"database: {db_name!r}"
        )
    return True


INTEGRATION_ENABLED = _enabled()

if INTEGRATION_ENABLED:
    os.environ["DATABASE_URL"] = _database_url

# ---------------------------------------------------------------------------
# Imports that need DATABASE_URL resolved
# ---------------------------------------------------------------------------

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app.config import settings  # noqa: E402
from app.rate_limit import limiter  # noqa: E402

from tests.integration.test_identity import AsgiClient, _json_body  # noqa: E402

ORIGIN = "http://localhost:5173"
HEADERS = {
    "Origin": ORIGIN,
    "Content-Type": "application/json",
}


def skip_unless_enabled(cls):
    return unittest.skipUnless(
        INTEGRATION_ENABLED,
        "I2 MySQL integration tests disabled; set I2_TEST_ALLOW_DESTRUCTIVE=yes "
        "and I2_TEST_DATABASE_URL to a whitelisted I2 database.",
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
    # Guard against module pre-loading: if app.config.settings was already
    # imported with a different DATABASE_URL, the test would clean one DB while
    # the application wrote to another. Refuse to run until they match.
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
            "App settings DATABASE_URL points outside the whitelisted I2 target"
        )

    engine = create_engine(_database_url, poolclass=NullPool, future=True)
    if configured != engine.url:
        raise AssertionError(
            "App settings DATABASE_URL does not match I2_TEST_DATABASE_URL; "
            "possible module pre-loading with a different DSN."
        )

    # Also check the application engine singleton if it has already been
    # created; otherwise its first use would silently target a different DB.
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


def reset_i2_tables(engine) -> None:
    """Independent per-test cleanup of I2 + identity rows (child first)."""
    # Reset the in-memory rate limiter so tests do not inherit each other's
    # failure counts; product rate-limit rules stay unchanged.
    limiter.reset()
    order = [
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
    from datetime import datetime, timezone

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


def register_and_login(client: AsgiClient, username: str, password: str = "password1234"):
    resp = client.request(
        "POST",
        "/api/auth/register",
        headers=HEADERS,
        body=_json_body({"username": username, "password": password}),
    )
    assert resp.status == 201, (resp.status, resp.body)
    login = client.request(
        "POST",
        "/api/auth/login",
        headers=HEADERS,
        body=_json_body({"username": username, "password": password}),
    )
    assert login.status == 200, (login.status, login.body)
    return login.json(), client.cookies.copy()


def unclaim_first_admin(engine) -> None:
    """Reset the first-admin control row so the next registration becomes admin."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE first_admin_control SET claimed = 0, "
                "first_admin_id = NULL WHERE id = 'singleton'"
            )
        )


__all__ = [
    "INTEGRATION_ENABLED",
    "skip_unless_enabled",
    "make_engine",
    "require_authorized_url",
    "check_environment",
    "ensure_schema",
    "reset_i2_tables",
    "register_and_login",
    "AsgiClient",
    "_json_body",
    "ORIGIN",
    "HEADERS",
]
