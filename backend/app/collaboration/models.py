"""MySQL 8.4 models for the optional online collaboration service.

The selected database in ``KGM_COLLAB_DATABASE_URL`` is the collaboration
database; there is no fixed PostgreSQL ``collaboration`` schema in the ORM.
Tables are created only by
``backend/migrations_collaboration/mysql/0001_initial.sql`` and never at
import or startup time.  The historical PostgreSQL SQL is intentionally
retained unchanged as a record.

Ownership is enforced by composite foreign keys where possible: a teacher,
class and membership all carry ``school_id`` so a row cannot point at a
different school even when an identifier is guessed.  Business checks add the
current class-membership and version checks; no request body supplies actor or
school identity.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.mysql import DATETIME as MySQLDateTime
from sqlalchemy.dialects.mysql import VARCHAR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator[datetime]):
    """Store naive UTC on MySQL and return aware UTC to callers."""

    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "mysql":
            return dialect.type_descriptor(MySQLDateTime(fsp=6))
        return dialect.type_descriptor(DateTime(timezone=True))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if not isinstance(value, datetime):
            raise TypeError("timestamp value must be a datetime")
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        value = value.astimezone(timezone.utc)
        if dialect.name == "mysql":
            return value.replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


def _ascii_string(length: int) -> String:
    """Case-sensitive ASCII storage for UUID/hash/kind tokens on MySQL."""
    return String(length).with_variant(
        VARCHAR(length, charset="ascii", collation="ascii_bin"),
        "mysql",
    )


def _table_options() -> dict[str, str]:
    return {
        "mysql_engine": "InnoDB",
        "mysql_charset": "utf8mb4",
        "mysql_collate": "utf8mb4_0900_ai_ci",
    }


class CollaborationBase(DeclarativeBase):
    pass


class School(CollaborationBase):
    __tablename__ = "schools"
    __table_args__ = (
        CheckConstraint(
            "char_length(name) between 1 and 120",
            name="ck_school_name",
        ),
        _table_options(),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
    )


class Classroom(CollaborationBase):
    __tablename__ = "classes"
    __table_args__ = (
        UniqueConstraint("id", "school_id", name="uq_classes_id_school"),
        CheckConstraint(
            "char_length(display_name) between 1 and 120",
            name="ck_classes_display_name",
        ),
        Index("ix_classes_school", "school_id"),
        _table_options(),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "schools.id",
            name="fk_classes_school",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
    )


class Teacher(CollaborationBase):
    __tablename__ = "teachers"
    __table_args__ = (
        UniqueConstraint("id", "school_id", name="uq_teachers_id_school"),
        CheckConstraint(
            "char_length(display_name) between 1 and 120",
            name="ck_teachers_display_name",
        ),
        Index("ix_teachers_school", "school_id"),
        _table_options(),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "schools.id",
            name="fk_teachers_school",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("1")
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
    )


class TeacherToken(CollaborationBase):
    __tablename__ = "teacher_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_teacher_tokens_hash"),
        CheckConstraint(
            "char_length(token_hash) = 64",
            name="ck_teacher_tokens_hash_length",
        ),
        Index("ix_teacher_tokens_teacher", "teacher_id"),
        _table_options(),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    teacher_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "teachers.id",
            name="fk_teacher_tokens_teacher",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(
        _ascii_string(64), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )


class TeacherClassMembership(CollaborationBase):
    __tablename__ = "teacher_class_memberships"
    __table_args__ = (
        CheckConstraint(
            "school_id is not null", name="ck_membership_school_required"
        ),
        ForeignKeyConstraint(
            ["teacher_id", "school_id"],
            ["teachers.id", "teachers.school_id"],
            name="fk_membership_teacher_school",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["class_id", "school_id"],
            ["classes.id", "classes.school_id"],
            name="fk_membership_class_school",
            ondelete="RESTRICT",
        ),
        Index("ix_membership_teacher_school", "teacher_id", "school_id"),
        Index("ix_membership_class", "class_id", "school_id"),
        _table_options(),
    )

    teacher_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    class_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    # Opaque, per-selection generation.  It stays stable while the teacher
    # re-selects the same class and changes on a switch/leave/rejoin, so an
    # old unsubmitted preview cannot be revived by returning to that class.
    membership_generation: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, default=uuid.uuid4
    )
    selected_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP(6)"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=text("CURRENT_TIMESTAMP(6)"),
    )


class TeacherGameConfig(CollaborationBase):
    __tablename__ = "teacher_game_configs"
    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_config_version_positive"),
        CheckConstraint(
            "char_length(payload_hash) = 64",
            name="ck_config_payload_hash_length",
        ),
        ForeignKeyConstraint(
            ["teacher_id", "school_id"],
            ["teachers.id", "teachers.school_id"],
            name="fk_config_teacher_school",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["class_id", "school_id"],
            ["classes.id", "classes.school_id"],
            name="fk_config_class_school",
            ondelete="RESTRICT",
        ),
        Index("ix_config_school_class", "school_id", "class_id"),
        Index("ix_config_class_school", "class_id", "school_id"),
        _table_options(),
    )

    teacher_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True
    )
    class_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    payload_hash: Mapped[str] = mapped_column(
        _ascii_string(64), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=text("CURRENT_TIMESTAMP(6)"),
    )


class CollaborationOperation(CollaborationBase):
    __tablename__ = "operations"
    __table_args__ = (
        CheckConstraint(
            "kind in ('save', 'import')", name="ck_operations_kind"
        ),
        CheckConstraint(
            "source_version is null or source_version >= 1",
            name="ck_operations_source_version",
        ),
        CheckConstraint(
            "target_version is null or target_version >= 0",
            name="ck_operations_target_version",
        ),
        CheckConstraint(
            "(kind = 'save' and source_teacher_id is null and source_version is null) "
            "or (kind = 'import' and source_teacher_id is not null "
            "and source_version is not null and target_version is not null)",
            name="ck_operations_binding",
        ),
        ForeignKeyConstraint(
            ["actor_teacher_id", "school_id"],
            ["teachers.id", "teachers.school_id"],
            name="fk_operations_actor_school",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["class_id", "school_id"],
            ["classes.id", "classes.school_id"],
            name="fk_operations_class_school",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["source_teacher_id", "school_id"],
            ["teachers.id", "teachers.school_id"],
            name="fk_operations_source_school",
            ondelete="RESTRICT",
        ),
        Index("ix_operations_actor_school", "actor_teacher_id", "school_id"),
        Index("ix_operations_class_school", "class_id", "school_id"),
        Index("ix_operations_source_school", "source_teacher_id", "school_id"),
        Index("ix_operations_actor_created", "actor_teacher_id", "created_at"),
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
    kind: Mapped[str] = mapped_column(
        _ascii_string(16), nullable=False
    )
    request_fingerprint: Mapped[str] = mapped_column(
        _ascii_string(64), nullable=False
    )
    source_teacher_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    source_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
    )
