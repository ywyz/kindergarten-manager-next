"""PostgreSQL models for the optional online collaboration service.

All tables live in the independent ``collaboration`` schema and are created
only by ``backend/migrations_collaboration/0001_initial.sql``.  The service
never creates or alters these tables at import or startup time.

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
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .config import COLLABORATION_SCHEMA


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CollaborationBase(DeclarativeBase):
    pass


class School(CollaborationBase):
    __tablename__ = "schools"
    __table_args__ = (
        CheckConstraint("length(name) between 1 and 120", name="ck_school_name"),
        {"schema": COLLABORATION_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Classroom(CollaborationBase):
    __tablename__ = "classes"
    __table_args__ = (
        UniqueConstraint("id", "school_id", name="uq_classes_id_school"),
        CheckConstraint(
            "length(display_name) between 1 and 120",
            name="ck_classes_display_name",
        ),
        {"schema": COLLABORATION_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{COLLABORATION_SCHEMA}.schools.id",
            name="fk_classes_school",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Teacher(CollaborationBase):
    __tablename__ = "teachers"
    __table_args__ = (
        UniqueConstraint("id", "school_id", name="uq_teachers_id_school"),
        CheckConstraint(
            "length(display_name) between 1 and 120",
            name="ck_teachers_display_name",
        ),
        {"schema": COLLABORATION_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{COLLABORATION_SCHEMA}.schools.id",
            name="fk_teachers_school",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TeacherToken(CollaborationBase):
    __tablename__ = "teacher_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_teacher_tokens_hash"),
        CheckConstraint(
            "length(token_hash) = 64", name="ck_teacher_tokens_hash_length"
        ),
        Index("ix_teacher_tokens_teacher", "teacher_id"),
        {"schema": COLLABORATION_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    teacher_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{COLLABORATION_SCHEMA}.teachers.id",
            name="fk_teacher_tokens_teacher",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class TeacherClassMembership(CollaborationBase):
    __tablename__ = "teacher_class_memberships"
    __table_args__ = (
        CheckConstraint(
            "school_id is not null", name="ck_membership_school_required"
        ),
        ForeignKeyConstraint(
            ["teacher_id", "school_id"],
            [
                f"{COLLABORATION_SCHEMA}.teachers.id",
                f"{COLLABORATION_SCHEMA}.teachers.school_id",
            ],
            name="fk_membership_teacher_school",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["class_id", "school_id"],
            [
                f"{COLLABORATION_SCHEMA}.classes.id",
                f"{COLLABORATION_SCHEMA}.classes.school_id",
            ],
            name="fk_membership_class_school",
            ondelete="RESTRICT",
        ),
        Index("ix_membership_class", "school_id", "class_id"),
        {"schema": COLLABORATION_SCHEMA},
    )

    teacher_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True
    )
    school_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    class_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    # Opaque, per-selection generation.  It stays stable while the teacher
    # re-selects the same class and changes on a switch/leave/rejoin, so an
    # old unsubmitted preview cannot be revived by returning to that class.
    membership_generation: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, default=uuid.uuid4
    )
    selected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
    )


class TeacherGameConfig(CollaborationBase):
    __tablename__ = "teacher_game_configs"
    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_config_version_positive"),
        CheckConstraint(
            "length(payload_hash) = 64", name="ck_config_payload_hash_length"
        ),
        ForeignKeyConstraint(
            ["teacher_id", "school_id"],
            [
                f"{COLLABORATION_SCHEMA}.teachers.id",
                f"{COLLABORATION_SCHEMA}.teachers.school_id",
            ],
            name="fk_config_teacher_school",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["class_id", "school_id"],
            [
                f"{COLLABORATION_SCHEMA}.classes.id",
                f"{COLLABORATION_SCHEMA}.classes.school_id",
            ],
            name="fk_config_class_school",
            ondelete="RESTRICT",
        ),
        Index("ix_config_school_class", "school_id", "class_id"),
        {"schema": COLLABORATION_SCHEMA},
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
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
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
            [
                f"{COLLABORATION_SCHEMA}.teachers.id",
                f"{COLLABORATION_SCHEMA}.teachers.school_id",
            ],
            name="fk_operations_actor_school",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["class_id", "school_id"],
            [
                f"{COLLABORATION_SCHEMA}.classes.id",
                f"{COLLABORATION_SCHEMA}.classes.school_id",
            ],
            name="fk_operations_class_school",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["source_teacher_id", "school_id"],
            [
                f"{COLLABORATION_SCHEMA}.teachers.id",
                f"{COLLABORATION_SCHEMA}.teachers.school_id",
            ],
            name="fk_operations_source_school",
            ondelete="RESTRICT",
        ),
        Index("ix_operations_actor_created", "actor_teacher_id", "created_at"),
        {"schema": COLLABORATION_SCHEMA},
    )

    actor_teacher_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True
    )
    request_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True
    )
    school_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    class_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    source_teacher_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    source_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
