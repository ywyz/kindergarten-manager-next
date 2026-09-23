"""I3 manual daily plan transactional core: create/open, save and queries.

Lock order (spec 8.1): operator account -> operator session ->
school_settings -> classes -> terms -> calendar_revisions -> calendar_days ->
daily_plans -> daily_plan_contents -> weekly_plan_sync_states. Date
membership and eligibility are re-verified under those locks against the
persisted calendar; the default calendar library is never called here and
the persisted calendar is never overwritten.

Same-class writers serialize on the class row, but reads that must see the
latest committed state still use locking reads, because the transaction's
REPEATABLE READ snapshot may predate the lock acquisition. The generated
unique key on (class_id, effective_date) backstops concurrent creates;
an IntegrityError rolls back the whole transaction and re-reads the winner
in a fresh transaction, so no partial plans_started_at / projection / audit
writes can survive.
"""

from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import security
from app.models import (
    CalendarDay,
    CalendarRevision,
    DailyPlan,
    DailyPlanContent,
    TeacherAssignment,
    Term,
)
from app.services import auth_service, calendar_service as cal
from app.services import weekly_plan_sync_service
from app.services.config_locks import lock_class, lock_school
from app.services.daily_plan_content import (
    ContentValidationError,
    collect_identity_sets,
    prepare_content,
)


MAX_LIST_LIMIT = 100
DEFAULT_LIST_LIMIT = 20


class _Unset:
    def __repr__(self) -> str:
        return "UNSET"


UNSET = _Unset()


class DailyPlanServiceError(Exception):
    code = "DAILY_PLAN_ERROR"

    def __init__(self, message: str = ""):
        super().__init__(message or self.code)
        self.message = message or self.code


class DailyPlanNotFound(DailyPlanServiceError):
    code = "DAILY_PLAN_NOT_FOUND"


class DailyPlanVersionConflict(DailyPlanServiceError):
    code = "VERSION_CONFLICT"


class DailyPlanOutsideTerm(DailyPlanServiceError):
    code = "OUTSIDE_TERM"


class DailyPlanDateNotEligible(DailyPlanServiceError):
    code = "DATE_NOT_ELIGIBLE"


class DailyPlanYearNotCovered(DailyPlanServiceError):
    code = "YEAR_NOT_COVERED"


class DailyPlanForbidden(DailyPlanServiceError):
    code = "FORBIDDEN"


class DailyPlanValidationError(DailyPlanServiceError):
    code = "VALIDATION_ERROR"


class DailyPlanDataError(DailyPlanServiceError):
    code = "SERVICE_UNAVAILABLE"


def _begin(db: Session) -> None:
    if not db.in_transaction():
        db.begin()


def _lock_operator(db: Session, snapshot: auth_service.AuthSnapshot):
    account = auth_service._lock_account(db, snapshot.account_id)
    if account is None or not account.is_active:
        raise auth_service.AuthRequired()
    if account.auth_version != snapshot.auth_version:
        raise auth_service.AuthRequired()
    # Role is part of the trusted snapshot from here on: a mismatch means
    # the snapshot is stale and every later snapshot.role branch is unsafe.
    if account.role != snapshot.role:
        raise auth_service.AuthRequired()
    auth_service.validate_locked_session(db, snapshot)
    return account


def _resolve_class_id(
    db: Session,
    snapshot: auth_service.AuthSnapshot,
    class_id: str | None,
    *,
    for_update: bool,
) -> str:
    if snapshot.role == "admin":
        if not class_id:
            raise DailyPlanValidationError("管理员请求必须包含 class_id")
        return class_id
    if class_id is not None:
        raise DailyPlanValidationError("教师请求不得包含 class_id")
    stmt = select(TeacherAssignment).where(
        TeacherAssignment.teacher_id == snapshot.account_id
    )
    if for_update:
        stmt = stmt.with_for_update()
    assignment = db.execute(stmt).scalar_one_or_none()
    if assignment is None:
        raise DailyPlanForbidden()
    return assignment.class_id


def _resolve_date_locked(db: Session, plan_date: date):
    # Locking scan (I2 precedent: current-read of term rows while writers
    # serialize on school_settings) so membership cannot go stale against
    # the transaction snapshot.
    terms = list(
        db.scalars(select(Term).order_by(Term.id).with_for_update()).all()
    )
    term = next(
        (t for t in terms if t.start_date <= plan_date <= t.end_date),
        None,
    )
    if term is None:
        raise DailyPlanOutsideTerm()
    if term.current_calendar_revision_id is None:
        raise DailyPlanDataError("学期缺少当前日历修订")
    revision = db.execute(
        select(CalendarRevision)
        .where(CalendarRevision.id == term.current_calendar_revision_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if revision is None:
        raise DailyPlanDataError("当前日历修订缺失")
    day = db.execute(
        select(CalendarDay)
        .where(
            CalendarDay.revision_id == revision.id,
            CalendarDay.date == plan_date,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if day is None:
        raise DailyPlanDataError("日历快照缺少目标日期")
    if day.effective_state == "unknown":
        raise DailyPlanYearNotCovered()
    if day.effective_state != "teaching":
        raise DailyPlanDateNotEligible()
    week_number, _week_start, weekday = cal.week_info(
        term.start_date, plan_date
    )
    return term, day, week_number, weekday


def _find_effective_plan(
    db: Session, class_id: str, plan_date: date, *, for_update: bool
) -> DailyPlan | None:
    stmt = select(DailyPlan).where(
        DailyPlan.class_id == class_id,
        DailyPlan.effective_date == plan_date,
    )
    if for_update:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return db.execute(stmt).scalar_one_or_none()


def _lock_plan(db: Session, plan_id: str) -> DailyPlan | None:
    return db.execute(
        select(DailyPlan)
        .where(DailyPlan.id == plan_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()


def _lock_current_content(db: Session, plan: DailyPlan):
    if plan.current_content_id is None or plan.current_content_version is None:
        raise DailyPlanDataError("当前内容指针为空")
    content = db.execute(
        select(DailyPlanContent)
        .where(DailyPlanContent.id == plan.current_content_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if (
        content is None
        or content.daily_plan_id != plan.id
        or content.version != plan.current_content_version
    ):
        raise DailyPlanDataError("当前内容指针不一致")
    return content


def _assert_pointer_complete(plan: DailyPlan, content: DailyPlanContent) -> None:
    if (
        plan.current_content_id != content.id
        or plan.current_content_version != content.version
        or plan.current_content_id is None
        or plan.current_content_version is None
    ):
        raise DailyPlanDataError("提交前内容指针不完整")


_EFFECTIVE_DATE_UNIQUE_KEY = "uq_daily_plans_class_effective_date"


def is_effective_date_unique_violation(exc: IntegrityError) -> bool:
    """True only when ``exc`` is the effective-row unique key (1062).

    Matches PyMySQL/MySQL message forms: the code may appear as ``1062``
    anywhere in ``orig``/``args``/``str(exc)``, and the key name may be bare
    or qualified (``daily_plans.uq_...`` / ``db`.`uq_...``). Any other
    IntegrityError (FK, other unique keys, CHECK) returns False so callers
    re-raise instead of disguising it as a duplicate create.
    """
    chunks: list[str] = []
    orig = getattr(exc, "orig", None)
    if orig is not None:
        chunks.append(str(orig))
        for arg in getattr(orig, "args", ()) or ():
            chunks.append(str(arg))
    chunks.append(str(exc))
    text = " ".join(chunks)
    if "1062" not in text and "duplicate entry" not in text.lower():
        return False
    return _EFFECTIVE_DATE_UNIQUE_KEY in text


def _recompute_sync(
    db: Session,
    *,
    class_id: str,
    term_id: str,
    week_number: int,
    trigger_daily_plan_id: str,
    trigger_content_version: int,
    trigger_event: str,
    now: datetime,
) -> None:
    try:
        weekly_plan_sync_service.recompute_weekly_sync_state(
            db,
            class_id=class_id,
            term_id=term_id,
            week_number=week_number,
            trigger_daily_plan_id=trigger_daily_plan_id,
            trigger_content_version=trigger_content_version,
            trigger_event=trigger_event,
            now=now,
        )
    except weekly_plan_sync_service.WeeklySyncDataError as exc:
        raise DailyPlanDataError(str(exc)) from exc


def _normalize_raw(raw_value: Any) -> str | None:
    if raw_value is None:
        return None
    if not isinstance(raw_value, str):
        raise DailyPlanValidationError("raw_lesson_plan 必须是字符串或 null")
    return raw_value


def create_or_open(
    db: Session,
    snapshot: auth_service.AuthSnapshot,
    *,
    plan_date: date,
    class_id: str | None = None,
    raw_lesson_plan: Any = UNSET,
    adopted_content: Any = UNSET,
) -> tuple[DailyPlan, DailyPlanContent, bool]:
    """Create the effective daily plan, or open the existing one.

    Returns ``(plan, content, created)``. A duplicate create never
    overwrites the creator or content; it rolls back and re-reads the
    committed winner, including after a unique-key IntegrityError.
    """
    _begin(db)
    try:
        return _create_or_open_locked(
            db,
            snapshot,
            plan_date=plan_date,
            class_id=class_id,
            raw_lesson_plan=raw_lesson_plan,
            adopted_content=adopted_content,
        )
    except IntegrityError as exc:
        db.rollback()
        if not is_effective_date_unique_violation(exc):
            raise
        existing = _find_after_conflict(db, snapshot, plan_date, class_id)
        if existing is None:
            raise
        plan, content = get(db, existing.id)
        return plan, content, False


def _create_or_open_locked(
    db: Session,
    snapshot: auth_service.AuthSnapshot,
    *,
    plan_date: date,
    class_id: str | None,
    raw_lesson_plan: Any,
    adopted_content: Any,
) -> tuple[DailyPlan, DailyPlanContent, bool]:
    operator = _lock_operator(db, snapshot)
    resolved_class_id = _resolve_class_id(
        db, snapshot, class_id, for_update=True
    )
    school = lock_school(db)
    school_class = lock_class(db, resolved_class_id)
    term, _day, week_number, weekday = _resolve_date_locked(db, plan_date)

    existing = _find_effective_plan(
        db, resolved_class_id, plan_date, for_update=True
    )
    if existing is not None:
        existing_id = existing.id
        db.rollback()
        plan, content = get(db, existing_id)
        return plan, content, False

    now = auth_service.utc_now()
    raw_value = None if raw_lesson_plan is UNSET else raw_lesson_plan
    raw_value = _normalize_raw(raw_value)
    content_payload: Any = {} if adopted_content is UNSET else adopted_content
    prepared = prepare_content(
        content_payload,
        allowed_group_ids=frozenset(),
        allowed_game_ids=frozenset(),
    )

    if school.plans_started_at is None:
        school.plans_started_at = now
        school.updated_at = now

    plan = DailyPlan(
        id=security.generate_id(),
        class_id=resolved_class_id,
        term_id=term.id,
        plan_date=plan_date,
        creator_id=operator.id,
        week_number=week_number,
        weekday=weekday,
        current_content_id=None,
        current_content_version=None,
        creator_display_name=operator.display_name,
        school_name=school.school_name,
        class_name=school_class.name,
        grade=school_class.grade,
        deleted_at=None,
        deleted_by=None,
        created_at=now,
        updated_at=now,
    )
    db.add(plan)
    db.flush()

    content = DailyPlanContent(
        id=security.generate_id(),
        daily_plan_id=plan.id,
        version=1,
        raw_lesson_plan=raw_value,
        split_baseline=None,
        adopted_content=prepared,
        editor_id=operator.id,
        created_at=now,
    )
    db.add(content)
    db.flush()

    plan.current_content_id = content.id
    plan.current_content_version = content.version
    plan.updated_at = now
    db.flush()
    _assert_pointer_complete(plan, content)

    _recompute_sync(
        db,
        class_id=resolved_class_id,
        term_id=term.id,
        week_number=week_number,
        trigger_daily_plan_id=plan.id,
        trigger_content_version=content.version,
        trigger_event="create",
        now=now,
    )
    auth_service.record_operation(
        db,
        operator_id=operator.id,
        operator_type="account",
        action="create_daily_plan",
        target_type="daily_plan",
        target_id=plan.id,
        target_version_after=content.version,
    )
    db.commit()
    return plan, content, True


def _find_after_conflict(
    db: Session,
    snapshot: auth_service.AuthSnapshot,
    plan_date: date,
    class_id: str | None,
) -> DailyPlan | None:
    try:
        resolved = _resolve_class_id(
            db, snapshot, class_id, for_update=False
        )
    except DailyPlanServiceError:
        return None
    return _find_effective_plan(db, resolved, plan_date, for_update=False)


def save(
    db: Session,
    snapshot: auth_service.AuthSnapshot,
    *,
    plan_id: str,
    expected_content_version: int,
    raw_lesson_plan: Any = UNSET,
    adopted_content: Any = UNSET,
) -> tuple[DailyPlan, DailyPlanContent]:
    """Append a new immutable content version (creator or admin only).

    ``expected_content_version`` must match the locked current version,
    otherwise 409 VERSION_CONFLICT. Omitted fields inherit the current
    version; ``split_baseline`` is never accepted from clients. Every save
    appends a version even when nothing changed.
    """
    if (
        not isinstance(expected_content_version, int)
        or isinstance(expected_content_version, bool)
        or expected_content_version < 1
    ):
        raise DailyPlanValidationError("expected_content_version 必须是 >= 1 的整数")
    _begin(db)
    try:
        return _save_locked(
            db,
            snapshot,
            plan_id=plan_id,
            expected_content_version=expected_content_version,
            raw_lesson_plan=raw_lesson_plan,
            adopted_content=adopted_content,
        )
    except IntegrityError:
        db.rollback()
        plan = db.get(DailyPlan, plan_id)
        if plan is None or plan.deleted_at is not None:
            raise
        if plan.current_content_version != expected_content_version:
            raise DailyPlanVersionConflict() from None
        raise


def _save_locked(
    db: Session,
    snapshot: auth_service.AuthSnapshot,
    *,
    plan_id: str,
    expected_content_version: int,
    raw_lesson_plan: Any,
    adopted_content: Any,
) -> tuple[DailyPlan, DailyPlanContent]:
    operator = _lock_operator(db, snapshot)
    header = db.get(DailyPlan, plan_id)
    if header is None or header.deleted_at is not None:
        raise DailyPlanNotFound()

    school = lock_school(db)
    lock_class(db, header.class_id)
    term, _day, week_number, weekday = _resolve_date_locked(
        db, header.plan_date
    )

    plan = _lock_plan(db, plan_id)
    if plan is None or plan.deleted_at is not None:
        raise DailyPlanNotFound()
    if snapshot.role != "admin" and plan.creator_id != snapshot.account_id:
        raise DailyPlanForbidden()
    if (
        plan.term_id != term.id
        or plan.week_number != week_number
        or plan.weekday != weekday
    ):
        raise DailyPlanDataError("日计划与当前学期/日历不一致")
    if plan.current_content_version != expected_content_version:
        raise DailyPlanVersionConflict()

    current = _lock_current_content(db, plan)

    now = auth_service.utc_now()
    if raw_lesson_plan is UNSET:
        raw_value = current.raw_lesson_plan
    else:
        raw_value = _normalize_raw(raw_lesson_plan)
    if adopted_content is UNSET:
        new_adopted = current.adopted_content
    else:
        group_ids, game_ids = collect_identity_sets(current.adopted_content)
        new_adopted = prepare_content(
            adopted_content,
            allowed_group_ids=group_ids,
            allowed_game_ids=game_ids,
        )

    new_version = current.version + 1
    content = DailyPlanContent(
        id=security.generate_id(),
        daily_plan_id=plan.id,
        version=new_version,
        raw_lesson_plan=raw_value,
        split_baseline=current.split_baseline,
        adopted_content=new_adopted,
        editor_id=operator.id,
        created_at=now,
    )
    db.add(content)
    db.flush()

    plan.current_content_id = content.id
    plan.current_content_version = new_version
    plan.updated_at = now
    db.flush()
    _assert_pointer_complete(plan, content)

    _recompute_sync(
        db,
        class_id=plan.class_id,
        term_id=plan.term_id,
        week_number=plan.week_number,
        trigger_daily_plan_id=plan.id,
        trigger_content_version=new_version,
        trigger_event="update",
        now=now,
    )
    auth_service.record_operation(
        db,
        operator_id=operator.id,
        operator_type="account",
        action="update_daily_plan",
        target_type="daily_plan",
        target_id=plan.id,
        target_version_after=new_version,
    )
    db.commit()
    return plan, content


def get(db: Session, plan_id: str) -> tuple[DailyPlan, DailyPlanContent]:
    plan = db.get(DailyPlan, plan_id)
    if plan is None or plan.deleted_at is not None:
        raise DailyPlanNotFound()
    if plan.current_content_id is None or plan.current_content_version is None:
        raise DailyPlanDataError("当前内容指针为空")
    content = db.get(DailyPlanContent, plan.current_content_id)
    if (
        content is None
        or content.daily_plan_id != plan.id
        or content.version != plan.current_content_version
    ):
        raise DailyPlanDataError("当前内容指针不一致")
    return plan, content


def get_by_date(
    db: Session, class_id: str, plan_date: date
) -> tuple[DailyPlan, DailyPlanContent]:
    plan = _find_effective_plan(db, class_id, plan_date, for_update=False)
    if plan is None:
        raise DailyPlanNotFound()
    return get(db, plan.id)


def list_plans(
    db: Session,
    *,
    class_id: str,
    from_date: date | None = None,
    to_date: date | None = None,
    offset: int = 0,
    limit: int = DEFAULT_LIST_LIMIT,
) -> tuple[list[DailyPlan], int]:
    if offset < 0 or limit < 1 or limit > MAX_LIST_LIMIT:
        raise DailyPlanValidationError("分页参数超出允许范围")
    if from_date is not None and to_date is not None and from_date > to_date:
        raise DailyPlanValidationError("from 不能晚于 to")
    conditions = [
        DailyPlan.class_id == class_id,
        DailyPlan.deleted_at.is_(None),
    ]
    if from_date is not None:
        conditions.append(DailyPlan.plan_date >= from_date)
    if to_date is not None:
        conditions.append(DailyPlan.plan_date <= to_date)
    total = (
        db.scalar(
            select(func.count()).select_from(DailyPlan).where(*conditions)
        )
        or 0
    )
    rows = list(
        db.scalars(
            select(DailyPlan)
            .where(*conditions)
            .order_by(DailyPlan.plan_date, DailyPlan.id)
            .offset(offset)
            .limit(limit)
        ).all()
    )
    return rows, int(total)


def get_sync_state(
    db: Session, class_id: str, term_id: str, week_number: int
):
    return weekly_plan_sync_service.get_weekly_sync_state(
        db, class_id, term_id, week_number
    )


def weekly_sync_summary(db: Session, plan: DailyPlan) -> dict[str, Any]:
    """Build the ``DailyPlanOut.weekly_sync_state`` summary for plan's week.

    ``saved_dates`` come from the persisted projection's current-week source
    manifest; ``missing_dates`` are teaching days of that week (per the
    term's current calendar revision) that have no saved plan. A plan whose
    projection row is missing means the same-transaction invariant broke and
    maps to 503 SERVICE_UNAVAILABLE, never to a silent empty state.
    """
    row = weekly_plan_sync_service.get_weekly_sync_state(
        db, plan.class_id, plan.term_id, plan.week_number
    )
    if row is None:
        raise DailyPlanDataError("周计划同步投影缺失")
    saved_dates = sorted(
        {
            entry["date"]
            for entry in (row.current_week_source_manifest or [])
            if isinstance(entry, dict) and isinstance(entry.get("date"), str)
        }
    )
    term = db.get(Term, plan.term_id)
    if term is None:
        raise DailyPlanDataError("学期缺失")
    if term.current_calendar_revision_id is None:
        raise DailyPlanDataError("学期缺少当前日历修订")
    week_start = cal.week_anchor(term.start_date) + timedelta(
        days=7 * (plan.week_number - 1)
    )
    start = max(week_start, term.start_date)
    end = min(week_start + timedelta(days=6), term.end_date)
    teaching_dates: list[str] = []
    if start <= end:
        day_rows = db.scalars(
            select(CalendarDay).where(
                CalendarDay.revision_id == term.current_calendar_revision_id,
                CalendarDay.date >= start,
                CalendarDay.date <= end,
                CalendarDay.effective_state == "teaching",
            )
        ).all()
        teaching_dates = sorted(d.date.isoformat() for d in day_rows)
    saved_set = set(saved_dates)
    return {
        "status": row.status,
        "has_pending_projection": row.status == "pending_projection",
        "saved_dates": saved_dates,
        "missing_dates": [
            day for day in teaching_dates if day not in saved_set
        ],
    }
