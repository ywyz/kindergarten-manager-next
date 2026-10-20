"""Local SQLite declarative base and shared conventions.

The local metadata is independent from ``app.database.Base`` (MySQL).
Constraint and index names are explicit and stable: the hand-written
Alembic baseline in ``migrations_local`` and these models must agree, and
SQLite enforces them with native TEXT/length checks (no MySQL collations
or functions).
"""

from datetime import datetime, timezone

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase


class LocalBase(DeclarativeBase):
    """Declarative base for the local (desktop) SQLite database."""

    metadata = MetaData()


def utc_now() -> datetime:
    """Return a naive UTC datetime (SQLite stores ISO text, UTC by rule)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
