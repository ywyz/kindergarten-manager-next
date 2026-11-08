"""MySQL 8.4 tables for the shared weekly-plan slice.

A week is identified by the stable class, stable term and ISO Monday.  The
shared draft row exists only after the first save; version 0 means no row.
Confirmations are append-only snapshots of one saved version.  The local
SQLite weekly plans and all local lesson bodies stay outside this schema.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.mysql import VARCHAR
from sqlalchemy.orm import Mapped, mapped_column

from .models import CollaborationBase, UTCDateTime


def _table_options() -> dict[str, str]:
    return {
        "mysql_engine": "InnoDB",
        "mysql_charset": "utf8mb4",
        "mysql_collate": "utf8mb4_0900_ai_ci",
    }


def _ascii_string(length: int) -> String:
    return String(length).with_variant(
        VARCHAR(length, charset="ascii", collation="ascii_bin"),
        "mysql",
    )


class WeeklyPlanWeek(CollaborationBase):
    __tablename__ = "weekly_plan_weeks"
    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_weekly_week_version"),
        ForeignKeyConstraint(
            ["class_id", "school_id"],
            ["classes.id", "classes.school_id"],
            name="fk_weekly_week_class_school",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["term_id", "school_id"],
            ["terms.id", "terms.school_id"],
            name="fk_weekly_week_term_school",
            ondelete="RESTRICT",
        ),
        Index("ix_weekly_week_school", "school_id", "week_start"),
        Index("ix_weekly_week_class_school", "class_id", "school_id"),
        Index("ix_weekly_week_term_school", "term_id", "school_id"),
        _table_options(),
    )

    class_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True
    )
    term_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True
    )
    week_start: Mapped[date] = mapped_column(Date, primary_key=True)
    school_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[dict] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
    )


class WeeklyPlanConfirmation(CollaborationBase):
    __tablename__ = "weekly_plan_confirmations"
    __table_args__ = (
        UniqueConstraint(
            "class_id",
            "term_id",
            "week_start",
            "confirmation_version",
            name="uq_weekly_confirmation_version",
        ),
        UniqueConstraint(
            "class_id",
            "term_id",
            "week_start",
            "version",
            name="uq_weekly_confirmation_saved_version",
        ),
        CheckConstraint(
            "confirmation_version >= 1",
            name="ck_weekly_confirmation_version",
        ),
        CheckConstraint("version >= 1", name="ck_weekly_confirmation_saved"),
        CheckConstraint(
            "char_length(class_name) between 1 and 80",
            name="ck_weekly_confirmation_class_name",
        ),
        CheckConstraint(
            "char_length(term_name) between 1 and 80",
            name="ck_weekly_confirmation_term_name",
        ),
        CheckConstraint(
            "grade in ('small', 'middle', 'large')",
            name="ck_weekly_confirmation_grade",
        ),
        ForeignKeyConstraint(
            ["class_id", "school_id"],
            ["classes.id", "classes.school_id"],
            name="fk_weekly_confirmation_class_school",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["term_id", "school_id"],
            ["terms.id", "terms.school_id"],
            name="fk_weekly_confirmation_term_school",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["confirmed_by", "school_id"],
            ["teachers.id", "teachers.school_id"],
            name="fk_weekly_confirmation_teacher_school",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_weekly_confirmation_week",
            "class_id",
            "term_id",
            "week_start",
        ),
        Index(
            "ix_weekly_confirmation_class_school",
            "class_id",
            "school_id",
        ),
        Index(
            "ix_weekly_confirmation_term_school",
            "term_id",
            "school_id",
        ),
        Index(
            "ix_weekly_confirmation_teacher_school",
            "confirmed_by",
            "school_id",
        ),
        _table_options(),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    class_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    term_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    confirmation_version: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    class_name: Mapped[str] = mapped_column(String(80), nullable=False)
    grade: Mapped[str] = mapped_column(_ascii_string(8), nullable=False)
    term_name: Mapped[str] = mapped_column(String(80), nullable=False)
    content: Mapped[dict] = mapped_column(JSON, nullable=False)
    confirmed_by: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    confirmed_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
    )


class WeeklyPlanOperation(CollaborationBase):
    __tablename__ = "weekly_plan_operations"
    __table_args__ = (
        CheckConstraint(
            "kind in ('save', 'confirm')",
            name="ck_weekly_operation_kind",
        ),
        CheckConstraint(
            "char_length(request_fingerprint) = 64",
            name="ck_weekly_operation_fingerprint",
        ),
        ForeignKeyConstraint(
            ["actor_teacher_id", "school_id"],
            ["teachers.id", "teachers.school_id"],
            name="fk_weekly_operation_actor_school",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["class_id", "school_id"],
            ["classes.id", "classes.school_id"],
            name="fk_weekly_operation_class_school",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["term_id", "school_id"],
            ["terms.id", "terms.school_id"],
            name="fk_weekly_operation_term_school",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_weekly_operation_actor_created",
            "actor_teacher_id",
            "created_at",
        ),
        Index(
            "ix_weekly_operation_week",
            "class_id",
            "term_id",
            "week_start",
        ),
        Index(
            "ix_weekly_operation_actor_school",
            "actor_teacher_id",
            "school_id",
        ),
        Index(
            "ix_weekly_operation_class_school",
            "class_id",
            "school_id",
        ),
        Index(
            "ix_weekly_operation_term_school",
            "term_id",
            "school_id",
        ),
        _table_options(),
    )

    actor_teacher_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True
    )
    request_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    class_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    term_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    kind: Mapped[str] = mapped_column(_ascii_string(16), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(
        _ascii_string(64), nullable=False
    )
    result_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
    )
