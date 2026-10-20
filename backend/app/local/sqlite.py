"""SQLite engine, path resolution and connection pragmas for the local app.

Hard rules (D1A spec §2/§6):
- the production data directory is ``%LOCALAPPDATA%\\KindergartenManager\\data``
  with database file ``kindergarten.db``, resolved to an absolute path;
- every physical connection enables and verifies ``foreign_keys=ON``,
  ``busy_timeout=5000`` and ``synchronous=FULL``; file databases use WAL;
- the sqlite3 driver's implicit BEGIN is disabled (``isolation_level=None``)
  so only the explicit ``BEGIN`` / ``BEGIN IMMEDIATE`` helpers own
  transaction boundaries.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, URL

APP_DIR_NAME = "KindergartenManager"
DATA_SUBDIR = "data"
DB_FILENAME = "kindergarten.db"
DATA_DIR_ENV_VAR = "KGM_LOCAL_DATA_DIR"
DB_PATH_ENV_VAR = "KGM_LOCAL_DB_PATH"

# Independent version table for the local migration chain (never the old
# MySQL ``alembic_version``).
LOCAL_VERSION_TABLE = "local_alembic_version"

BUSY_TIMEOUT_MS = 5000


def default_data_dir() -> Path:
    """Return the fixed production data directory (absolute)."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return base / APP_DIR_NAME / DATA_SUBDIR


def data_dir_raw(data_dir: str | Path | None = None) -> Path:
    """Return the raw data directory selected for a runtime, *without* resolve.

    ``None`` uses the ``KGM_LOCAL_DATA_DIR`` override when present and the
    fixed production directory otherwise. The returned path is not resolved,
    so junction/symlink reparse information on the raw path and its
    ancestors is preserved for the pre-resolve alias check in
    ``LocalRuntime``.
    """
    if data_dir is None:
        env_value = os.environ.get(DATA_DIR_ENV_VAR)
        base = Path(env_value) if env_value else default_data_dir()
    else:
        base = Path(data_dir)
    return base.expanduser()


def resolve_data_dir(data_dir: str | Path | None = None) -> Path:
    """Resolve the data directory to an absolute path.

    ``None`` uses the ``KGM_LOCAL_DATA_DIR`` override when present and the
    fixed production directory otherwise. Tests always pass an explicit
    temporary directory; the production path is never used implicitly by
    the test suite.
    """
    return data_dir_raw(data_dir).resolve()


def resolve_db_path(db_path: str | Path | None = None) -> Path:
    """Resolve a database file path (``KGM_LOCAL_DB_PATH`` override)."""
    if db_path is not None:
        return Path(db_path).expanduser().resolve()
    env_value = os.environ.get(DB_PATH_ENV_VAR)
    if env_value:
        return Path(env_value).expanduser().resolve()
    return resolve_data_dir() / DB_FILENAME


def sqlite_url(db_path: Path) -> URL:
    """Build a pysqlite URL for exactly this file path."""
    return URL.create("sqlite+pysqlite", database=db_path.as_posix())


def readonly_sqlite_uri(db_path: Path) -> str:
    """Read-only SQLite URI for exactly this file path.

    ``Path.as_uri`` percent-encodes ``#``, ``%``, spaces and non-ASCII
    characters, so the query string stays a query string and the path is
    never truncated at a URI fragment or resolved to a neighbouring file.
    """
    return f"{db_path.as_uri()}?mode=ro"


def install_pragmas(engine: Engine) -> None:
    """Install per-connection pragmas on every physical connection."""

    @event.listens_for(engine, "connect")
    def _apply_pragmas(dbapi_connection, _record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
            cursor.execute("PRAGMA synchronous=FULL")
            cursor.execute("PRAGMA journal_mode=WAL")
        finally:
            cursor.close()


def create_local_engine(
    db_path: Path,
    *,
    autocommit_driver: bool = True,
) -> Engine:
    """Create a local SQLite engine for ``db_path``.

    ``autocommit_driver=True`` (application runtime) disables the sqlite3
    implicit BEGIN so the explicit transaction helpers control boundaries.
    ``autocommit_driver=False`` (migration runtime) keeps the driver's
    deferred BEGIN so Alembic's ``engine.begin()`` yields one real,
    atomic DDL transaction.
    """
    connect_args: dict[str, object] = {"check_same_thread": False}
    if autocommit_driver:
        connect_args["isolation_level"] = None
    engine = create_engine(
        sqlite_url(db_path),
        connect_args=connect_args,
    )
    install_pragmas(engine)
    return engine


def connection_settings(dbapi_connection) -> dict[str, object]:  # noqa: ANN001
    """Read and verify the three mandated pragmas on a raw connection."""
    cursor = dbapi_connection.cursor()
    try:
        foreign_keys = cursor.execute("PRAGMA foreign_keys").fetchone()[0]
        busy_timeout = cursor.execute("PRAGMA busy_timeout").fetchone()[0]
        synchronous = cursor.execute("PRAGMA synchronous").fetchone()[0]
        journal_mode = cursor.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        cursor.close()
    return {
        "foreign_keys": int(foreign_keys),
        "busy_timeout": int(busy_timeout),
        "synchronous": int(synchronous),
        "journal_mode": str(journal_mode).lower(),
    }
