"""Same-class grade promotion transactions for online collaboration.

Writes use the same teacher -> class lock order as the existing selection
and configuration paths.  The class state row carries the expected version;
the request ID is the idempotency key.  A future term records the grade for
that term only, so the class keeps its current display name until the term's
Shanghai start date.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import and_, select
from sqlalchemy.orm import Session, aliased

from .class_promotion_models import (
    GRADES,
    GRADE_RANK,
    ClassPromotionHistory,
    ClassPromotionOperation,
    ClassPromotionState,
    CollaborationTerm,
    latest_grade_at_date,
    make_class_name,
    shanghai_today,
)
from .errors import (
    CollaborationError,
    class_not_found,
    membership_changed,
    membership_required,
    operation_not_found,
    request_conflict,
)
from .models import Classroom, TeacherClassMembership
from .security import TeacherPrincipal
from .service import _lock_class, _lock_teachers, _membership


@dataclass(frozen=True)
class PromotionTermView:
    term_id: UUID
    name: str
    start_date: date
    end_date: date


@dataclass(frozen=True)
class PromotionCurrentView:
    class_id: UUID
    class_name: str
    grade: str
    version: int
    terms: tuple[PromotionTermView, ...]


@dataclass(frozen=True)
class PromotionReceiptView:
    request_id: UUID
    class_id: UUID
    class_name: str
    grade: str
    version: int
    effective_term_id: UUID
    replayed: bool


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def promotion_not_ready() -> CollaborationError:
    return CollaborationError(
        409,
        "CLASS_PROMOTION_NOT_READY",
        "该班级尚未登记年级和班号，请联系部署方",
    )


def promotion_version_conflict(current_version: int) -> CollaborationError:
    return CollaborationError(
        409,
        "CLASS_PROMOTION_VERSION_CONFLICT",
        "班级版本已变化，请重新读取后确认",
        details={"current_version": int(current_version)},
    )


def invalid_promotion(message: str) -> CollaborationError:
    return CollaborationError(422, "INVALID_CLASS_PROMOTION", message)


def term_not_found() -> CollaborationError:
    return CollaborationError(404, "TERM_NOT_FOUND", "没有找到该学期")


def _terms(session: Session, school_id: UUID) -> tuple[PromotionTermView, ...]:
    rows = session.scalars(
        select(CollaborationTerm)
        .where(CollaborationTerm.school_id == school_id)
        .order_by(CollaborationTerm.start_date, CollaborationTerm.id)
    ).all()
    return tuple(
        PromotionTermView(
            term_id=row.id,
            name=row.name,
            start_date=row.start_date,
            end_date=row.end_date,
        )
        for row in rows
    )


def _state(
    session: Session, class_id: UUID, *, for_update: bool = False
) -> ClassPromotionState:
    query = select(ClassPromotionState).where(
        ClassPromotionState.class_id == class_id
    )
    if for_update:
        query = query.with_for_update()
    state = session.scalars(query).one_or_none()
    if state is None:
        raise promotion_not_ready()
    return state


def _operation(
    session: Session, actor_teacher_id: UUID, request_id: UUID
) -> ClassPromotionOperation | None:
    return session.scalars(
        select(ClassPromotionOperation)
        .where(
            ClassPromotionOperation.actor_teacher_id == actor_teacher_id,
            ClassPromotionOperation.request_id == request_id,
        )
        .with_for_update()
    ).one_or_none()


def _receipt(
    operation: ClassPromotionOperation, *, replayed: bool
) -> PromotionReceiptView:
    return PromotionReceiptView(
        request_id=operation.request_id,
        class_id=operation.class_id,
        class_name=operation.result_class_name,
        grade=operation.result_grade,
        version=operation.result_version,
        effective_term_id=operation.effective_term_id,
        replayed=replayed,
    )


def _fingerprint(
    *,
    request_id: UUID,
    actor_teacher_id: UUID,
    school_id: UUID,
    class_id: UUID,
    expected_version: int,
    target_grade: str,
    effective_term_id: UUID,
) -> str:
    canonical = json.dumps(
        {
            "request_id": str(request_id),
            "actor_teacher_id": str(actor_teacher_id),
            "school_id": str(school_id),
            "class_id": str(class_id),
            "expected_version": int(expected_version),
            "target_grade": target_grade,
            "effective_term_id": str(effective_term_id),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def get_promotion(
    session: Session, principal: TeacherPrincipal
) -> PromotionCurrentView:
    # One statement is one READ COMMITTED snapshot: membership, class,
    # promotion state/version and the latest effective history grade are read
    # together.  The display name is derived from that same grade, so a
    # concurrent promotion can only appear as one complete before/after view.
    today = shanghai_today()
    history = aliased(ClassPromotionHistory)
    term = aliased(CollaborationTerm)
    current_grade = (
        select(history.grade)
        .join(term, term.id == history.term_id)
        .where(
            history.class_id == ClassPromotionState.class_id,
            term.start_date <= today,
        )
        .order_by(
            term.start_date.desc(),
            history.version_after.desc(),
        )
        .limit(1)
        .correlate(ClassPromotionState)
        .scalar_subquery()
    )
    row = session.execute(
        select(
            TeacherClassMembership.school_id,
            TeacherClassMembership.class_id,
            Classroom.display_name,
            ClassPromotionState.class_number,
            ClassPromotionState.base_grade,
            ClassPromotionState.version,
            current_grade,
        )
        .select_from(TeacherClassMembership)
        .outerjoin(
            Classroom,
            and_(
                Classroom.id == TeacherClassMembership.class_id,
                Classroom.school_id == TeacherClassMembership.school_id,
            ),
        )
        .outerjoin(
            ClassPromotionState,
            ClassPromotionState.class_id
            == TeacherClassMembership.class_id,
        )
        .where(TeacherClassMembership.teacher_id == principal.teacher_id)
    ).one_or_none()
    if row is None:
        raise membership_required()
    (
        school_id,
        class_id,
        display_name,
        class_number,
        base_grade,
        version,
        grade,
    ) = row
    if school_id != principal.school_id or display_name is None:
        raise membership_changed()
    if version is None or class_number is None or base_grade is None:
        raise promotion_not_ready()
    effective_grade = grade or base_grade
    return PromotionCurrentView(
        class_id=class_id,
        class_name=make_class_name(effective_grade, class_number),
        grade=effective_grade,
        version=version,
        terms=_terms(session, principal.school_id),
    )


def submit_promotion(
    session: Session,
    principal: TeacherPrincipal,
    *,
    request_id: UUID,
    class_id: UUID,
    expected_version: int,
    target_grade: str,
    effective_term_id: UUID,
) -> PromotionReceiptView:
    if target_grade not in GRADES:
        raise invalid_promotion("目标年级只能是小班、中班或大班")
    if expected_version < 1:
        raise invalid_promotion("班级版本必须从 1 开始")
    fingerprint = _fingerprint(
        request_id=request_id,
        actor_teacher_id=principal.teacher_id,
        school_id=principal.school_id,
        class_id=class_id,
        expected_version=expected_version,
        target_grade=target_grade,
        effective_term_id=effective_term_id,
    )
    with session.begin():
        _lock_teachers(session, [principal.teacher_id])
        class_row = _lock_class(session, principal.school_id, class_id)
        if class_row.school_id != principal.school_id:
            raise class_not_found()
        existing = _operation(
            session, principal.teacher_id, request_id
        )
        if existing is not None:
            if (
                existing.request_fingerprint != fingerprint
                or existing.class_id != class_id
                or existing.school_id != principal.school_id
            ):
                raise request_conflict()
            return _receipt(existing, replayed=True)

        membership = _membership(session, principal.teacher_id)
        if membership is None:
            raise membership_required()
        if (
            membership.school_id != principal.school_id
            or membership.class_id != class_id
        ):
            raise membership_changed()
        state = _state(session, class_id, for_update=True)

        if state.version != expected_version:
            raise promotion_version_conflict(state.version)

        term = session.get(CollaborationTerm, effective_term_id)
        if term is None or term.school_id != principal.school_id:
            raise term_not_found()
        if term.end_date < shanghai_today():
            raise invalid_promotion("不能对已结束学期提交升班")

        last_term = session.scalars(
            select(CollaborationTerm)
            .join(
                ClassPromotionHistory,
                ClassPromotionHistory.term_id == CollaborationTerm.id,
            )
            .where(ClassPromotionHistory.class_id == class_id)
            .order_by(CollaborationTerm.start_date.desc())
            .limit(1)
        ).one_or_none()
        if last_term is not None and term.start_date <= last_term.start_date:
            raise invalid_promotion("升班学期必须晚于该班已有升班学期")

        current_grade = (
            latest_grade_at_date(session, class_id, term.start_date)
            or state.base_grade
        )
        if GRADE_RANK[target_grade] <= GRADE_RANK[current_grade]:
            raise invalid_promotion("班级只能向更高年级升班")

        new_version = state.version + 1
        now = _utcnow()
        state.version = new_version
        state.updated_at = now
        name = make_class_name(target_grade, state.class_number)
        session.add(
            ClassPromotionHistory(
                id=uuid4(),
                class_id=class_id,
                school_id=principal.school_id,
                term_id=term.id,
                grade=target_grade,
                version_after=new_version,
                created_at=now,
            )
        )
        operation = ClassPromotionOperation(
            actor_teacher_id=principal.teacher_id,
            request_id=request_id,
            school_id=principal.school_id,
            class_id=class_id,
            effective_term_id=term.id,
            target_grade=target_grade,
            expected_version=expected_version,
            result_version=new_version,
            result_grade=target_grade,
            result_class_name=name,
            request_fingerprint=fingerprint,
            created_at=now,
        )
        session.add(operation)
        session.flush()
        return _receipt(operation, replayed=False)


def query_promotion_operation(
    session: Session, principal: TeacherPrincipal, request_id: UUID
) -> PromotionReceiptView:
    operation = session.scalars(
        select(ClassPromotionOperation).where(
            ClassPromotionOperation.actor_teacher_id == principal.teacher_id,
            ClassPromotionOperation.request_id == request_id,
        )
    ).one_or_none()
    if operation is None:
        raise operation_not_found()
    return _receipt(operation, replayed=False)
