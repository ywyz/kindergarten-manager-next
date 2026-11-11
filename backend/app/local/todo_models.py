"""Local personal todo tables (shared ``LocalBase`` metadata).

The tables are added by the forward-only ``20261108_0013_local_todos``
migration.  Ownership is the single local teacher profile; class and term are
deliberately not part of the todo identity or ordering.  The repository never
creates tables dynamically and reports a storage-not-ready state on an old
archive until the normal startup migration has run.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    PrimaryKeyConstraint,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.local.base import LocalBase, utc_now


class LocalTodo(LocalBase):
    __tablename__ = "local_todos"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_local_todos"),
        CheckConstraint(
            "length(title) BETWEEN 1 AND 200", name="ck_local_todos_title"
        ),
        CheckConstraint("version >= 1", name="ck_local_todos_version"),
        ForeignKeyConstraint(
            ["profile_id"],
            ["local_profile.id"],
            name="fk_local_todos_profile",
        ),
        Index("ix_local_todos_profile_order", "profile_id", "completed", "due_date"),
        Index("ix_local_todos_profile_archive", "profile_id", "archived_at"),
    )

    id: Mapped[str] = mapped_column(String(32), nullable=False)
    profile_id: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, default=utc_now
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )


class LocalTodoOperation(LocalBase):
    __tablename__ = "local_todo_operations"
    __table_args__ = (
        PrimaryKeyConstraint(
            "profile_id", "request_id", name="pk_local_todo_operations"
        ),
        CheckConstraint(
            "action IN ('create','update','delete')",
            name="ck_local_todo_operations_action",
        ),
        ForeignKeyConstraint(
            ["profile_id"],
            ["local_profile.id"],
            name="fk_local_todo_operations_profile",
        ),
        Index("ix_local_todo_operations_todo", "profile_id", "todo_id"),
    )

    profile_id: Mapped[str] = mapped_column(String(32), nullable=False)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    todo_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, default=utc_now
    )


__all__ = ["LocalTodo", "LocalTodoOperation"]
