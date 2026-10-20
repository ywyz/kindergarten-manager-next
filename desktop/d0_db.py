"""D0 synthetic SQLite probe (SQLAlchemy 2.x + pysqlite, isolated data dir).

Scope of this probe (D0-2 / D0-3):
- one single-row synthetic note with an explicit integer ``version``;
- explicit ``BEGIN IMMEDIATE`` write transactions and immediate rollback on
  any failure, so a failed write leaves the previous record intact and is
  never reported as success;
- write-then-verify before commit: an inconsistency aborts the transaction;
- meta facts recorded for the result report: driver/dialect, SQLite library
  version, ``PRAGMA foreign_keys`` enforcement and journal mode.

This probe does NOT replace the D1 work: real model constraints, FK chains,
version races and busy timeouts must be validated on the D1 schema.
"""

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError as SQLAlchemyIntegrityError

PROBE_TABLE = "probe_synthetic_note"

# D0-2/D0-3: an explicit length guard gives the probe a real, reachable
# IntegrityError path so failure simulation exercises the actual commit
# instead of injecting test-only hooks into business code.
SCHEMA_SQL = f"""
CREATE TABLE IF NOT EXISTS {PROBE_TABLE} (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    content TEXT NOT NULL CHECK (length(content) <= 2000),
    version INTEGER NOT NULL CHECK (version >= 1),
    updated_at TEXT NOT NULL
)
"""

_CONTENT_MAX = 2000


class ProbeError(Exception):
    """Any probe failure surfaced to the API layer as ``SAVE_FAILED``."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class SQLiteProbe:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "d0_probe.db"
        # ``isolation_level=None``: the pysqlite layer stops issuing its own
        # implicit BEGINs, so this module controls the transaction shape it
        # reports (BEGIN IMMEDIATE .. COMMIT/ROLLBACK). SQLAlchemy-documented
        # pattern for serialized writes on SQLite.
        self.engine = create_engine(
            f"sqlite+pysqlite:///{self.db_path}",
            future=True,
            connect_args={"isolation_level": None},
        )
        self._init_schema()

    def close(self) -> None:
        self.engine.dispose()

    # -- schema ------------------------------------------------------------
    def _init_schema(self) -> None:
        with self.engine.connect() as conn:
            _enable_foreign_keys(conn)
            conn.exec_driver_sql("PRAGMA journal_mode = WAL")
            conn.exec_driver_sql(SCHEMA_SQL)

    # -- write ---------------------------------------------------------------
    def save(self, content: str, *, simulate_failure: bool = False) -> dict:
        """Save one new version of the single-row note.

        Returns ``{"status": "saved", ...}`` only after a committed write and
        a verified read-back. Every failure path returns
        ``{"status": "failed", "message": ...}`` and leaves the previous
        record untouched.
        """
        try:
            with self.engine.connect() as conn:
                _enable_foreign_keys(conn)
                conn.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    # Inside the write transaction: the base version and the
                    # next version must be computed under the SAME upgrade
                    # lock, not read optimistically before it.
                    current = self._read_row(conn)
                    next_version = (current["version"] + 1) if current else 1
                    payload = ("长度攻破失败的合成内容 " * 300) \
                        if simulate_failure else content
                    conn.execute(
                        text(
                            f"INSERT INTO {PROBE_TABLE} (id, content, version, updated_at) "
                            "VALUES (1, :content, :version, :updated_at) "
                            "ON CONFLICT(id) DO UPDATE SET "
                            "content = excluded.content, "
                            "version = excluded.version, "
                            "updated_at = excluded.updated_at"
                        ),
                        {
                            "content": payload,
                            "version": next_version,
                            "updated_at": _utcnow(),
                        },
                    )
                    verify = self._read_row(conn)
                    if verify is None:
                        raise ProbeError("事务内读回失败：记录不存在")
                    if verify["content"] != payload or verify["version"] != next_version:
                        raise ProbeError("事务内写后读校验不一致")
                except Exception:
                    conn.exec_driver_sql("ROLLBACK")
                    raise
                conn.exec_driver_sql("COMMIT")
            return {
                "status": "saved",
                "content": (
                    content if not simulate_failure else None
                ),
                "version": verify["version"],
            }
        except SQLAlchemyIntegrityError as exc:
            return {"status": "failed", "error_kind": "integrity", "message": str(exc)}
        except ProbeError as exc:
            return {"status": "failed", "error_kind": "verify", "message": exc.message}
        except Exception as exc:  # any unexpected DB failure: report, never fake success
            return {"status": "failed", "error_kind": "sqlite", "message": str(exc)}

    # -- read ------------------------------------------------------------------
    def read(self) -> dict:
        with self.engine.connect() as conn:
            row = self._read_row(conn)
        if row is None:
            return {"status": "empty"}
        return {
            "status": "ok",
            "content": row["content"],
            "version": row["version"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _read_row(conn) -> dict | None:
        result = conn.execute(
            text(
                f"SELECT content, version, updated_at FROM {PROBE_TABLE} WHERE id = 1"
            )
        ).mappings().first()
        return dict(result) if result is not None else None

    # -- facts for the result report ---------------------------------------------
    def meta(self) -> dict:
        with self.engine.connect() as conn:
            foreign_keys = conn.exec_driver_sql("PRAGMA foreign_keys").fetchone()[0]
            journal_mode = conn.exec_driver_sql("PRAGMA journal_mode").fetchone()[0]
        return {
            "sqlite_library_version": sqlite3.sqlite_version,
            "sqlite_runtime_version": sqlite3.lib_version
            if hasattr(sqlite3, "lib_version")
            else os.environ.get("SQLITE3_VERSION", "") or sqlite3.sqlite_version,
            "pysqlite_module_version": getattr(sqlite3, "version", "n/a"),
            "dialect": self.engine.dialect.name,
            "driver": self.engine.dialect.driver,
            "foreign_keys_pragma": foreign_keys,
            "journal_mode": journal_mode,
            "transaction_style": "BEGIN IMMEDIATE ... COMMIT / ROLLBACK（显式 SQL，isolation_level=None）",
            "write_then_verify_before_commit": True,
            "data_dir": str(self.data_dir),
            "db_path": str(self.db_path),
        }


def _enable_foreign_keys(conn) -> None:
    enabled = conn.exec_driver_sql("PRAGMA foreign_keys").fetchone()[0]
    if enabled == 0:
        conn.exec_driver_sql("PRAGMA foreign_keys = ON")
        enabled = conn.exec_driver_sql("PRAGMA foreign_keys").fetchone()[0]
    if enabled != 1:
        raise ProbeError("PRAGMA foreign_keys 未能启用")


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
