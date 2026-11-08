"""MySQL ORM tables for the collaboration administrator and one-time codes.

These tables are intentionally outside the local SQLite model chain and use
the collaboration service's default database (no PostgreSQL schema).  The
teacher/school tables remain owned by the base collaboration slice.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .models import CollaborationBase


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AdminUser(CollaborationBase):
    __tablename__ = "admin_users"
    __table_args__ = (
        CheckConstraint(
            "length(username) between 3 and 80", name="ck_admin_users_username"
        ),
        CheckConstraint(
            "failed_attempts >= 0", name="ck_admin_users_failed_attempts"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    username: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1")
    )
    failed_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AdminSession(CollaborationBase):
    __tablename__ = "admin_sessions"
    __table_args__ = (
        CheckConstraint(
            "length(token_hash) = 64", name="ck_admin_sessions_token_hash"
        ),
        CheckConstraint(
            "length(csrf_hash) = 64", name="ck_admin_sessions_csrf_hash"
        ),
        Index("ix_admin_sessions_admin", "admin_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    admin_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("admin_users.id", name="fk_admin_sessions_admin", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    csrf_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AdminCode(CollaborationBase):
    __tablename__ = "admin_codes"
    __table_args__ = (
        CheckConstraint(
            "purpose in ('join', 'recovery')", name="ck_admin_codes_purpose"
        ),
        CheckConstraint("length(code_hash) = 64", name="ck_admin_codes_hash"),
        ForeignKeyConstraint(
            ["teacher_id", "school_id"],
            ["teachers.id", "teachers.school_id"],
            name="fk_admin_codes_teacher_school",
            ondelete="RESTRICT",
        ),
        Index("ix_admin_codes_teacher", "teacher_id", "purpose", "created_at"),
        Index("ix_admin_codes_school", "school_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    purpose: Mapped[str] = mapped_column(String(16), nullable=False)
    teacher_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("schools.id", name="fk_admin_codes_school", ondelete="RESTRICT"),
        nullable=False,
    )
    created_by_admin_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "admin_users.id",
            name="fk_admin_codes_admin",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
