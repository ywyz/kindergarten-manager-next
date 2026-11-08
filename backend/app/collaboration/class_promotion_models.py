"""Stable class terms and same-class promotion history for online collaboration.

The existing ``classes`` and ``teacher_class_memberships`` rows keep their
stable IDs.  A separate state row records the class number and initial grade;
promotion history records only grade changes by effective school term.  The
class number never changes for that stable ID.  All names are derived from
those rows, never used as identity or lookup keys.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Iterable

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    select,
    text,
)
from sqlalchemy.dialects.mysql import VARCHAR
from sqlalchemy.orm import Mapped, Session, mapped_column

from .models import CollaborationBase, UTCDateTime

GRADES = ("small", "middle", "large")
GRADE_LABELS = {"small": "小", "middle": "中", "large": "大"}
GRADE_RANK = {grade: index for index, grade in enumerate(GRADES)}
CLASS_NUMBER_MIN = 1
CLASS_NUMBER_MAX = 99
_SHANGHAI = timezone(timedelta(hours=8))
_CN_DIGITS = "零一二三四五六七八九"


def _table_options() -> dict[str, str]:
    return {
        "mysql_engine": "InnoDB",
        "mysql_charset": "utf8mb4",
        "mysql_collate": "utf8mb4_0900_ai_ci",
    }


def shanghai_today() -> date:
    """Return the current calendar date in Asia/Shanghai (no DST)."""
    return datetime.now(timezone.utc).astimezone(_SHANGHAI).date()


def _number_label(number: int) -> str:
    if not (CLASS_NUMBER_MIN <= number <= CLASS_NUMBER_MAX):
        raise ValueError("class number is out of range")
    if number < 10:
        return _CN_DIGITS[number]
    if number == 10:
        return "十"
    if number < 20:
        return "十" + _CN_DIGITS[number - 10]
    tens, ones = divmod(number, 10)
    return _CN_DIGITS[tens] + "十" + (_CN_DIGITS[ones] if ones else "")


def make_class_name(grade: str, class_number: int) -> str:
    if grade not in GRADE_LABELS:
        raise ValueError("invalid grade")
    return f"{GRADE_LABELS[grade]}{_number_label(class_number)}班"


def _ascii_string(length: int) -> String:
    return String(length).with_variant(
        VARCHAR(length, charset="ascii", collation="ascii_bin"),
        "mysql",
    )


class CollaborationTerm(CollaborationBase):
    __tablename__ = "terms"
    __table_args__ = (
        UniqueConstraint("id", "school_id", name="uq_terms_id_school"),
        CheckConstraint(
            "char_length(name) between 1 and 80",
            name="ck_terms_name",
        ),
        CheckConstraint(
            "start_date <= end_date",
            name="ck_terms_date_order",
        ),
        Index("ix_terms_school_start", "school_id", "start_date"),
        _table_options(),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("schools.id", name="fk_terms_school", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
    )


class ClassPromotionState(CollaborationBase):
    __tablename__ = "class_promotion_states"
    __table_args__ = (
        CheckConstraint(
            "class_number between 1 and 99",
            name="ck_promotion_state_number",
        ),
        CheckConstraint(
            "base_grade in ('small', 'middle', 'large')",
            name="ck_promotion_state_base_grade",
        ),
        CheckConstraint("version >= 1", name="ck_promotion_state_version"),
        ForeignKeyConstraint(
            ["class_id", "school_id"],
            ["classes.id", "classes.school_id"],
            name="fk_promotion_state_class_school",
            ondelete="RESTRICT",
        ),
        Index("ix_promotion_state_school", "school_id"),
        Index(
            "ix_promotion_state_class_school",
            "class_id",
            "school_id",
        ),
        _table_options(),
    )

    class_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    class_number: Mapped[int] = mapped_column(Integer, nullable=False)
    base_grade: Mapped[str] = mapped_column(
        _ascii_string(8), nullable=False
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
    )


class ClassPromotionHistory(CollaborationBase):
    __tablename__ = "class_promotion_history"
    __table_args__ = (
        UniqueConstraint(
            "class_id", "term_id", name="uq_promotion_history_class_term"
        ),
        CheckConstraint(
            "grade in ('small', 'middle', 'large')",
            name="ck_promotion_history_grade",
        ),
        CheckConstraint(
            "version_after >= 1", name="ck_promotion_history_version"
        ),
        ForeignKeyConstraint(
            ["class_id", "school_id"],
            ["classes.id", "classes.school_id"],
            name="fk_promotion_history_class_school",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["term_id", "school_id"],
            ["terms.id", "terms.school_id"],
            name="fk_promotion_history_term_school",
            ondelete="RESTRICT",
        ),
        Index("ix_promotion_history_class_term", "class_id", "term_id"),
        Index(
            "ix_promotion_history_class_school",
            "class_id",
            "school_id",
        ),
        Index(
            "ix_promotion_history_term_school",
            "term_id",
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
    grade: Mapped[str] = mapped_column(
        _ascii_string(8), nullable=False
    )
    version_after: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
    )


class ClassPromotionOperation(CollaborationBase):
    __tablename__ = "class_promotion_operations"
    __table_args__ = (
        CheckConstraint(
            "target_grade in ('small', 'middle', 'large')",
            name="ck_promotion_operation_target_grade",
        ),
        CheckConstraint(
            "result_grade in ('small', 'middle', 'large')",
            name="ck_promotion_operation_result_grade",
        ),
        CheckConstraint(
            "char_length(result_class_name) between 1 and 80",
            name="ck_promotion_operation_name",
        ),
        CheckConstraint(
            "char_length(request_fingerprint) = 64",
            name="ck_promotion_operation_fingerprint",
        ),
        CheckConstraint(
            "expected_version >= 1 and result_version >= 1",
            name="ck_promotion_operation_versions",
        ),
        ForeignKeyConstraint(
            ["actor_teacher_id", "school_id"],
            ["teachers.id", "teachers.school_id"],
            name="fk_promotion_operation_actor_school",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["class_id", "school_id"],
            ["classes.id", "classes.school_id"],
            name="fk_promotion_operation_class_school",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["effective_term_id", "school_id"],
            ["terms.id", "terms.school_id"],
            name="fk_promotion_operation_term_school",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_promotion_operation_actor_school",
            "actor_teacher_id",
            "school_id",
        ),
        Index(
            "ix_promotion_operation_class_school",
            "class_id",
            "school_id",
        ),
        Index(
            "ix_promotion_operation_term_school",
            "effective_term_id",
            "school_id",
        ),
        Index(
            "ix_promotion_operation_actor_created",
            "actor_teacher_id",
            "created_at",
        ),
        Index(
            "ix_promotion_operation_class_created",
            "class_id",
            "created_at",
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
    effective_term_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    target_grade: Mapped[str] = mapped_column(
        _ascii_string(8), nullable=False
    )
    expected_version: Mapped[int] = mapped_column(Integer, nullable=False)
    result_version: Mapped[int] = mapped_column(Integer, nullable=False)
    result_grade: Mapped[str] = mapped_column(
        _ascii_string(8), nullable=False
    )
    result_class_name: Mapped[str] = mapped_column(String(80), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(
        _ascii_string(64), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
    )


def latest_grade_at_date(
    session: Session, class_id: uuid.UUID, at_date: date
) -> str | None:
    state = session.get(ClassPromotionState, class_id)
    if state is None:
        return None
    row = session.execute(
        select(ClassPromotionHistory.grade)
        .join(
            CollaborationTerm,
            CollaborationTerm.id == ClassPromotionHistory.term_id,
        )
        .where(
            ClassPromotionHistory.class_id == class_id,
            CollaborationTerm.start_date <= at_date,
        )
        .order_by(
            CollaborationTerm.start_date.desc(),
            ClassPromotionHistory.version_after.desc(),
        )
        .limit(1)
    ).scalar_one_or_none()
    return row if row is not None else state.base_grade


def effective_class_name_at_date(
    session: Session,
    class_id: uuid.UUID,
    at_date: date,
    fallback: str | None = None,
) -> str | None:
    state = session.get(ClassPromotionState, class_id)
    if state is None:
        return fallback
    grade = latest_grade_at_date(session, class_id, at_date)
    if grade is None:
        return fallback
    return make_class_name(grade, state.class_number)


def effective_class_name_now(
    session: Session,
    class_id: uuid.UUID,
    fallback: str | None = None,
) -> str | None:
    return effective_class_name_at_date(
        session, class_id, shanghai_today(), fallback
    )


def effective_class_names_now(
    session: Session, class_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, str]:
    ids = list(dict.fromkeys(class_ids))
    if not ids:
        return {}
    states = session.scalars(
        select(ClassPromotionState).where(
            ClassPromotionState.class_id.in_(ids)
        )
    ).all()
    if not states:
        return {}
    today = shanghai_today()
    rows = session.execute(
        select(
            ClassPromotionHistory.class_id,
            ClassPromotionHistory.grade,
        )
        .join(
            CollaborationTerm,
            CollaborationTerm.id == ClassPromotionHistory.term_id,
        )
        .where(
            ClassPromotionHistory.class_id.in_(ids),
            CollaborationTerm.start_date <= today,
        )
        .order_by(
            ClassPromotionHistory.class_id,
            CollaborationTerm.start_date,
            ClassPromotionHistory.version_after,
        )
    ).all()
    latest = {class_id: grade for class_id, grade in rows}
    return {
        state.class_id: make_class_name(
            latest.get(state.class_id, state.base_grade),
            state.class_number,
        )
        for state in states
    }


def resolve_class_name_at_term(
    session: Session,
    class_id: uuid.UUID,
    term_id: uuid.UUID,
    fallback: str | None = None,
) -> str | None:
    term = session.get(CollaborationTerm, term_id)
    if term is None:
        return fallback
    return effective_class_name_at_date(
        session, class_id, term.start_date, fallback
    )


def resolve_grade_at_term(
    session: Session,
    class_id: uuid.UUID,
    term_id: uuid.UUID,
) -> str | None:
    term = session.get(CollaborationTerm, term_id)
    if term is None:
        return None
    return latest_grade_at_date(session, class_id, term.start_date)
