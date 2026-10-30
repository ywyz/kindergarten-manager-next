"""Explicit SQLite transaction helpers and error classification.

Every read that must stay consistent opens a real ``BEGIN``; every write
opens ``BEGIN IMMEDIATE`` before its first business read. The sqlite3
driver's implicit BEGIN is disabled at engine creation, so these helpers
are the only transaction owners. Failures classify on
``sqlite_errorcode``/``sqlite_errorname``: busy waits map to
``LOCAL_DATABASE_BUSY`` and everything else db-level maps to
``LOCAL_STORAGE_ERROR`` — never to a duplicate-create or version-conflict
code by accident.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy.exc import DatabaseError, IntegrityError
from sqlalchemy.orm import Session

from app.local import backup_barrier
from app.local.errors import LocalDatabaseBusy, LocalError, LocalStorageError

_BUSY_PRIMARY_CODES = {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}


def begin_read(session: Session) -> None:
    """Open an explicit SQL read transaction on this session's connection."""
    session.connection().exec_driver_sql("BEGIN")


def begin_immediate(session: Session) -> None:
    """Open the final write transaction before any business read inside it.

    The snapshot barrier is entered before SQLite's write lock.  This makes the
    writer count and the intent/exclusive decision one atomic protocol; an
    already accepted writer finishes, while a new external writer is refused.
    """
    existing = session.info.get("_kgm_backup_barrier")
    if existing is not None:
        # Nested BEGIN is invalid, but it must not acquire a second writer
        # slot or remove the outer slot when it fails.  The outer transaction
        # keeps its original token until commit/rollback/close.
        session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        return
    barrier = backup_barrier.begin_db_write(session)
    try:
        session.connection().exec_driver_sql("BEGIN IMMEDIATE")
    except BaseException:
        backup_barrier.abort_db_write(session, barrier)
        raise
    if barrier is not None:
        session.info["_kgm_backup_barrier"] = barrier


def end_read(session: Session) -> None:
    """End a read transaction; no changes are pending, so roll back."""
    _safe_rollback(session)


def rollback(session: Session) -> None:
    _safe_rollback(session)


def _safe_rollback(session: Session) -> None:
    try:
        session.rollback()
    except Exception:  # noqa: BLE001 - rollback failures must not mask the cause
        pass


@contextmanager
def read_scope(session: Session) -> Iterator[None]:
    """Run the block inside one explicit read transaction."""
    begin_read(session)
    try:
        yield
    finally:
        end_read(session)


def _sqlite_origin(exc: BaseException) -> sqlite3.Error | None:
    orig = getattr(exc, "orig", None)
    return orig if isinstance(orig, sqlite3.Error) else None


def is_busy_error(exc: BaseException) -> bool:
    orig = _sqlite_origin(exc)
    if orig is None:
        return False
    code = getattr(orig, "sqlite_errorcode", None)
    if not isinstance(code, int):
        return False
    return (code & 0xFF) in _BUSY_PRIMARY_CODES


def is_unique_violation(exc: BaseException, *, columns: tuple[str, ...]) -> bool:
    """True only for a UNIQUE failure mentioning every named column.

    SQLite reports ``UNIQUE constraint failed: <table>.<col>, ...`` so the
    partial effective-date index is identified by its column list; other
    unique, FK, CHECK or trigger failures return False.
    """
    if not isinstance(exc, IntegrityError):
        return False
    orig = _sqlite_origin(exc)
    if orig is None:
        return False
    error_name = getattr(orig, "sqlite_errorname", "")
    if error_name not in (
        "SQLITE_CONSTRAINT_UNIQUE",
        "SQLITE_CONSTRAINT_PRIMARYKEY",
    ):
        return False
    message = str(orig)
    return all(column in message for column in columns)


def local_database_error(exc: BaseException) -> LocalError | None:
    """Classify a SQLAlchemy/DBAPI failure, or return None if not db-level."""
    if is_busy_error(exc):
        return LocalDatabaseBusy()
    if isinstance(exc, DatabaseError) or isinstance(exc, sqlite3.Error):
        return LocalStorageError()
    return None


@contextmanager
def storage_errors() -> Iterator[None]:
    """Translate unhandled db failures into the public local error codes."""
    try:
        yield
    except LocalError:
        raise
    except IntegrityError as exc:
        raise LocalStorageError() from exc
    except DatabaseError as exc:
        error = local_database_error(exc)
        if error is None:
            raise
        raise error from exc
    except sqlite3.Error as exc:
        error = local_database_error(exc)
        if error is None:
            raise
        raise error from exc
