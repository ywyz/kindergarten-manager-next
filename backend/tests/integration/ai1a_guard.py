"""Shared guard + helpers for the AI 1A config/prompts MySQL integration tests.

Strict isolation rules (checklist §9.2):
* Runs only when ``AI1A_TEST_ALLOW_DESTRUCTIVE=yes`` AND
  ``AI1A_TEST_DATABASE_URL`` is set AND the URL targets one of the two
  whitelisted AI-1A test databases on 127.0.0.1/localhost with the
  ``mysql+pymysql`` driver on the dedicated AI-1A port 13387.
* Any other schema name — including the I1–I5 suites, dev and production —
  is refused BEFORE any connection is opened.
* No destructive switch shared with I2/I3/I4/I5, so the suites cannot be
  pointed at each other's data by accident.
* ``APP_DISABLE_DOTENV=1`` is forced before app.config is imported, so no
  project ``.env`` DSN or master key can leak in.
* Alembic child processes are only ever handed the guard-validated URL;
  existing connection strings are never inherited (helpers below).
"""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

os.environ["APP_DISABLE_DOTENV"] = "1"
# S2: guard 模块加载前清除继承的连接／主密钥环境，避免任何进程把私人
# DATABASE_URL 或主密钥带进本模块（AI1A_TEST_DATABASE_URL 是唯一入口）。
for _leaked in ("DATABASE_URL", "AI_MASTER_KEY", "AI_MASTER_KEY_ID"):
    os.environ.pop(_leaked, None)

ALLOWED_DATABASES = frozenset(
    {"kindergarten_test_ai1a", "kindergarten_test_ai1a_fresh"}
)
# I2/I3 use 13384, I4 13385, I5 13386; AI-1A owns 13387 only.
_ALLOWED_PORT = 13387

_database_url = os.environ.get("AI1A_TEST_DATABASE_URL")

forbidden_databases = frozenset(
    {
        "kindergarten_test_i1",
        "kindergarten_test_i2",
        "kindergarten_test_i3",
        "kindergarten_test_i4",
        "kindergarten_test_i4_fresh",
        "kindergarten_test_i5",
        "kindergarten_test_i5_fresh",
        "kindergarten_test",
        "kindergarten_dev",
        "kindergarten",
        "production",
    }
)

BACKEND_ROOT = Path(__file__).resolve().parents[2]

# S2: 固定安全拒绝消息（不回显原始输入）。
_REFUSE_NON_AI1A_MESSAGE = (
    "AI 1A integration tests refuse non-AI1A database "
    "(other suites, shared or production are blocked)"
)
_REFUSE_NOT_WHITELISTED_MESSAGE = (
    "AI 1A integration tests refuse to run against non-whitelisted database"
)
_REFUSE_HOST_MESSAGE = (
    "AI 1A integration tests only run against 127.0.0.1/localhost"
)
_REFUSE_PORT_MESSAGE = (
    f"AI 1A integration tests only run against the dedicated port {_ALLOWED_PORT}"
)
_REFUSE_DRIVER_MESSAGE = (
    "AI 1A integration tests require mysql+pymysql driver"
)
_REFUSE_MALFORMED_URL_MESSAGE = (
    "AI 1A integration tests require a parseable, whitelisted mysql+pymysql URL"
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
    try:
        return urlsplit(url).port
    except ValueError:
        return None


def _database_driver(url: str | None) -> str | None:
    if not url:
        return None
    return urlsplit(url).scheme


def _refuse_forbidden_schema(db_name: str | None) -> None:
    if db_name is None:
        raise RuntimeError(
            "AI 1A integration tests require an explicit database name"
        )
    if db_name in ALLOWED_DATABASES:
        return
    if db_name in forbidden_databases:
        raise RuntimeError(_REFUSE_NON_AI1A_MESSAGE)
    raise RuntimeError(_REFUSE_NOT_WHITELISTED_MESSAGE)


def _enabled() -> bool:
    if os.environ.get("AI1A_TEST_ALLOW_DESTRUCTIVE") != "yes":
        return False
    if not _database_url:
        return False
    if _database_driver(_database_url) != "mysql+pymysql":
        raise RuntimeError("AI 1A integration tests require mysql+pymysql driver")
    host = _database_host(_database_url)
    if host not in ("127.0.0.1", "localhost"):
        raise RuntimeError(_REFUSE_HOST_MESSAGE)
    port = _database_port(_database_url)
    if port is None or port != _ALLOWED_PORT:
        raise RuntimeError(_REFUSE_PORT_MESSAGE)
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
    # app.config may have been imported before this guard (empty/other DSN).
    from pydantic import SecretStr

    settings.database_url = SecretStr(_database_url)


def skip_unless_enabled(cls):
    return unittest.skipUnless(
        INTEGRATION_ENABLED,
        "AI 1A MySQL integration tests disabled; set AI1A_TEST_ALLOW_DESTRUCTIVE=yes "
        "and AI1A_TEST_DATABASE_URL to a whitelisted AI-1A database.",
    )(cls)


def require_authorized_url(raw_url: str) -> None:
    """Guard-validate any URL handed to this module (S2 结果／固定消息）。"""
    try:
        url = make_url(raw_url)
        port = url.port
        host = url.host
        database = url.database
    except Exception:
        raise RuntimeError(_REFUSE_MALFORMED_URL_MESSAGE) from None
    if url.drivername != "mysql+pymysql":
        raise RuntimeError(_REFUSE_DRIVER_MESSAGE)
    if host not in ("127.0.0.1", "localhost"):
        raise RuntimeError(_REFUSE_HOST_MESSAGE)
    if port != _ALLOWED_PORT:
        raise RuntimeError(_REFUSE_PORT_MESSAGE)
    if database not in ALLOWED_DATABASES:
        raise RuntimeError(_REFUSE_NOT_WHITELISTED_MESSAGE)


def authorized_url(variant_database: str | None = None) -> str:
    """Return a guard-validated URL (optionally with a whitelisted db name)."""
    if not INTEGRATION_ENABLED:
        raise RuntimeError("AI 1A integration is not enabled")
    require_authorized_url(_database_url)
    if variant_database is None:
        return _database_url
    variant_url = (
        _database_url[: _database_url.index(_database_name(_database_url))]
        + variant_database
    )
    require_authorized_url(variant_url)
    return variant_url


def authorized_migration_env(variant_database: str | None = None) -> dict:
    """Environment for the Alembic child: only the validated URL and dotenv
    disabled; inherited DSN info is never reused."""
    url = authorized_url(variant_database)
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("DATABASE_URL", "AI_MASTER_KEY", "AI_MASTER_KEY_ID")
    }
    env["APP_DISABLE_DOTENV"] = "1"
    env["DATABASE_URL"] = url
    return env


def run_alembic(args: list[str], variant_database: str | None = None) -> None:
    """Run alembic in a subprocess under the guard (checklist 区域验证 2)."""
    require_authorized_url(_database_url)
    completed = subprocess.run(
        [
            os.path.join(BACKEND_ROOT, ".venv", "bin", "python"),
            "-m",
            "alembic",
            *args,
        ],
        cwd=str(BACKEND_ROOT),
        env=authorized_migration_env(variant_database),
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        # S2: 公开失败异常只保留已校验 driver／port／库名、退出码与固定
        # 错误类别；不拼任何原始 stdout／stderr，不用 `from` 把解析异常
        # 链带出 traceback。
        target_db = _database_name(authorized_url(variant_database)) or ""
        raise RuntimeError(
            "alembic subprocess failed "
            "(driver=mysql+pymysql, port=13387, db="
            + target_db
            + ", exit=" + str(completed.returncode)
            + ", category=alembic_child_process_nonzero_exit)"
        ) from None


def make_engine(variant_database: str | None = None):
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
            "App settings DATABASE_URL points outside the whitelisted AI-1A target"
        )
    raw = authorized_url(variant_database)
    target_url = make_url(raw)
    from app.database import _engine as app_engine

    if variant_database is None and app_engine is not None:
        if configured != app_engine.url:
            raise AssertionError(
                "App engine singleton target does not match the test target; "
                "possible module pre-loading with a different DSN."
            )
    if target_url.database not in ALLOWED_DATABASES:
        raise AssertionError("engine target escaped the AI-1A whitelist")
    return create_engine(
        raw, poolclass=NullPool, future=True,
        isolation_level="REPEATABLE READ", pool_pre_ping=True,
    )


def check_environment(engine) -> tuple[str, str]:
    """Assert MySQL 8.4 + InnoDB; return ``(version, database)``."""
    with engine.connect() as conn:
        version = conn.execute(text("SELECT VERSION()")).scalar()
        engine_var = conn.execute(
            text("SHOW VARIABLES LIKE 'default_storage_engine'")
        ).fetchone()
    if not version or not version.startswith("8.4"):
        raise AssertionError(f"AI 1A integration requires MySQL 8.4, found {version}")
    if not engine_var or engine_var[1].lower() != "innodb":
        raise AssertionError("MySQL default storage engine must be InnoDB")
    return version, _database_name(_database_url)


AI1A_TABLES = (
    "prompt_change_records",
    "personal_prompt_heads",
    "personal_prompt_versions",
    "prompt_default_versions",
    "prompt_contract_versions",
    "ai_config_heads",
    "ai_config_versions",
)

BASE_TABLES = (
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

_ALL_TABLES = AI1A_TABLES + BASE_TABLES

_EXPECTED_HEAD = "20261003_ai1a_config_prompts"


def ensure_schema(engine) -> str:
    """Verify the full migration chain and head revision applied."""
    with engine.connect() as conn:
        names = ",".join("?" for _ in _ALL_TABLES)  # not used; keep raw below
        rows = conn.execute(
            text(
                "SELECT table_name, engine FROM information_schema.tables "
                "WHERE table_schema = DATABASE()"
            )
        ).fetchall()
        found = {row[0]: row[1] for row in rows}
        missing = set(_ALL_TABLES) - set(found)
        if missing:
            raise AssertionError(
                f"Schema missing tables {missing}; run 'alembic upgrade head' first."
            )
        non_innodb = [t for t, e in found.items() if t in _ALL_TABLES and e.lower() != "innodb"]
        if non_innodb:
            raise AssertionError(f"Tables must use InnoDB: {non_innodb}")
        revision = conn.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar()
        if revision != _EXPECTED_HEAD:
            raise AssertionError(
                f"Expected head {_EXPECTED_HEAD}, found {revision!r}"
            )
    return revision


def reset_ai1a_tables(engine) -> None:
    """Fresh per-test world: clear existing tables first with FK checks off.

    Missing tables (e.g. AI-1A tables absent at I4 head) are skipped."""
    stamp = datetime(2026, 1, 1, 0, 0, 0)
    with engine.begin() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
        existing = _existing_tables(conn)
        tables = [t for t in _ALL_TABLES if t in existing]
        for table in tables:
            conn.execute(text(f"DELETE FROM `{table}`"))
        if "first_admin_control" in existing:
            conn.execute(
                text(
                    "INSERT INTO first_admin_control (id, claimed, first_admin_id) "
                    "VALUES ('singleton', 0, NULL)"
                )
            )
        if "school_settings" in existing:
            conn.execute(
                text(
                    "INSERT INTO school_settings (id, school_name, version, "
                    "schedule_version, plans_started_at, created_at, updated_at) "
                    "VALUES ('singleton', NULL, 1, 1, NULL, :created_at, :updated_at)"
                ),
                {"created_at": stamp, "updated_at": stamp},
            )
        conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))


def reset_base_tables(engine) -> None:
    """Clear only the I1-I4 tables + audit/sales; for representative rows
    placed BEFORE the AI-1A migration runs."""
    stamp = datetime(2026, 1, 1, 0, 0, 0)
    with engine.begin() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
        existing = _existing_tables(conn)
        for table in BASE_TABLES:
            if table in existing:
                conn.execute(text(f"DELETE FROM `{table}`"))
        if "first_admin_control" in existing:
            conn.execute(
                text(
                    "INSERT INTO first_admin_control (id, claimed, first_admin_id) "
                    "VALUES ('singleton', 0, NULL)"
                )
            )
        if "school_settings" in existing:
            conn.execute(
                text(
                    "INSERT INTO school_settings (id, school_name, version, "
                    "schedule_version, plans_started_at, created_at, updated_at) "
                    "VALUES ('singleton', NULL, 1, 1, NULL, :created_at, :updated_at)"
                ),
                {"created_at": stamp, "updated_at": stamp},
            )
        conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))


def _existing_tables(conn) -> set[str]:
    return {
        row[0]
        for row in conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = DATABASE()"
            )
        )
    }


__all__ = [
    "AI1A_TABLES",
    "BASE_TABLES",
    "INTEGRATION_ENABLED",
    "ALLOWED_DATABASES",
    "authorized_migration_env",
    "authorized_url",
    "check_environment",
    "ensure_schema",
    "make_engine",
    "require_authorized_url",
    "reset_ai1a_tables",
    "run_alembic",
    "skip_unless_enabled",
]
