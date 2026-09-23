"""I4 manual weekly plan transactional core: create/open, save, refresh, confirm.

Lock order (spec 6.1): operator account -> operator session ->
teacher_assignment (teachers) -> school_settings -> classes -> terms ->
calendar_revisions -> calendar_days -> weekly_plans -> current draft ->
current confirmed -> daily_plans -> daily_plan_contents ->
weekly_plan_sync_states (locking read only). The class row is the shared
serialization point for same-class writers; I4 always takes weekly rows
before daily rows, never the reverse.

``weekly_plan_sync_states`` is never written here. A missing projection row
while the week has daily plans is an I3 same-transaction invariant break
(503); otherwise ``projection_consumed_at`` takes the row's ``updated_at``
(or "now" for a week with no plans and no row). Deterministic content,
slot/focus selection and confirm facts come from the content module
(``weekly_plan_content``); this file owns transactions, locks, permission,
version pointers, header snapshot and audit.

Errors carry a ``code`` for HTTP mapping. Every public entry rolls back the
transaction on any failure before re-raising. Unique-key 1062 on the
effective weekly key re-reads the committed winner in a fresh transaction
with the full permission prefix; every other IntegrityError is re-raised
untouched.
"""

from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
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
    WeeklyPlan,
    WeeklyPlanContent,
    WeeklyPlanConfirmedContent,
    WeeklyPlanSyncState,
)
from app.services import auth_service, calendar_service as cal
from app.services import weekly_plan_content, weekly_plan_sync_service
from app.services.auth_service import AuthSnapshot
from app.services.config_errors import TermNotFound as ConfigTermNotFound
from app.services.config_locks import lock_class, lock_school, lock_term


class WeeklyPlanServiceError(Exception):
    code = "WEEKLY_PLAN_ERROR"

    def __init__(self, message: str = ""):
        super().__init__(message or self.code)
        self.message = message or self.code


class WeeklyPlanNotFound(WeeklyPlanServiceError):
    code = "WEEKLY_PLAN_NOT_FOUND"


class WeeklyPlanTermNotFound(WeeklyPlanServiceError):
    code = "TERM_NOT_FOUND"


class WeeklyPlanForbidden(WeeklyPlanServiceError):
    code = "FORBIDDEN"


class WeeklyPlanVersionConflict(WeeklyPlanServiceError):
    code = "VERSION_CONFLICT"


class WeeklyPlanConfirmAckRequired(WeeklyPlanServiceError):
    """Confirm facts non-empty while the matching ack was not granted (409)."""

    code = "CONFIRM_ACK_REQUIRED"

    def __init__(self, message: str = "", *, facts: dict[str, Any]):
        super().__init__(message)
        self.facts: dict[str, Any] = facts


class WeeklyPlanValidationError(WeeklyPlanServiceError):
    code = "VALIDATION_ERROR"


class WeeklyPlanDataError(WeeklyPlanServiceError):
    code = "SERVICE_UNAVAILABLE"


class WeeklyPlanWriteResult:
    """Stable result of every write entry: plan + draft + confirmed."""

    __slots__ = (
        "plan",
        "draft",
        "confirmed",
        "created",
        "refreshed_sources",
        "facts",
    )

    def __init__(
        self,
        *,
        plan: WeeklyPlan,
        draft: WeeklyPlanContent,
        confirmed: WeeklyPlanConfirmedContent | None,
        created: bool = False,
        refreshed_sources: list[dict[str, Any]] | None = None,
        facts: dict[str, Any] | None = None,
    ):
        self.plan = plan
        self.draft = draft
        self.confirmed = confirmed
        self.created = created
        self.refreshed_sources = refreshed_sources
        self.facts = facts


@dataclass(frozen=True, slots=True)
class _HeaderIdentity:
    """Scalar identity snapshot from the non-locking pre-read."""

    plan_id: str
    class_id: str
    term_id: str
    week_number: int


_WEEKLY_EFFECTIVE_UNIQUE_KEY = "uq_weekly_plans_class_term_effective_week"

_AUDIT_KEY = "_audit"

_PATCH_FIELDS = frozenset(
    {
        "theme",
        "deterministic_overrides",
        "outdoor_game_slots",
        "focus_area",
        "weekly_columns",
    }
)


def is_weekly_effective_unique_violation(exc: IntegrityError) -> bool:
    """True only when ``exc`` is the effective-row unique key (1062).

    Any other IntegrityError (FK, other unique keys, CHECK) returns False so
    callers re-raise instead of disguising it as a duplicate create.
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
    return _WEEKLY_EFFECTIVE_UNIQUE_KEY in text


def _begin(db: Session) -> None:
    if not db.in_transaction():
        db.begin()


def _rollback(db: Session) -> None:
    try:
        db.rollback()
    except Exception:  # noqa: BLE001 - rollback must not mask the cause
        pass


def _lock_operator(db: Session, snapshot: AuthSnapshot):
    account = auth_service._lock_account(db, snapshot.account_id)
    if account is None or not account.is_active:
        raise auth_service.AuthRequired()
    if account.auth_version != snapshot.auth_version:
        raise auth_service.AuthRequired()
    if account.role != snapshot.role:
        raise auth_service.AuthRequired()
    auth_service.validate_locked_session(db, snapshot)
    return account


def _require_role(snapshot: AuthSnapshot) -> None:
    if snapshot.role not in ("teacher", "admin"):
        raise WeeklyPlanForbidden()


def _lock_teacher_assignment(db: Session, snapshot: AuthSnapshot):
    stmt = (
        select(TeacherAssignment)
        .where(TeacherAssignment.teacher_id == snapshot.account_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return db.execute(stmt).scalar_one_or_none()


def _resolve_create_class(db: Session, snapshot: AuthSnapshot) -> str:
    if snapshot.role == "admin":
        raise WeeklyPlanForbidden("管理员不能创建周计划")
    if snapshot.role != "teacher":
        raise WeeklyPlanForbidden()
    assignment = _lock_teacher_assignment(db, snapshot)
    if assignment is None:
        raise WeeklyPlanForbidden()
    return assignment.class_id


def _validate_expected_version(value: Any) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 1
    ):
        raise WeeklyPlanValidationError("expected_draft_version 必须是 >= 1 的整数")
    return value


def _validate_week_number(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise WeeklyPlanValidationError("week_number 必须是 >= 1 的整数")
    return value


def _max_week(term: Term) -> int:
    max_week, _week_start, _weekday = cal.week_info(
        term.start_date, term.end_date
    )
    return max_week


def _validate_week_in_term(term: Term, week_number: int) -> None:
    if week_number < 1 or week_number > _max_week(term):
        raise WeeklyPlanValidationError("week_number 超出学期范围")


def _normalize_theme(theme: Any) -> str:
    if theme is None:
        return ""
    if not isinstance(theme, str):
        raise WeeklyPlanValidationError("theme 必须是字符串")
    return theme


def _load_week_days(db: Session, term: Term, week_number: int) -> dict[date, str]:
    """Lock the term's current revision + week days; map to teaching/rest."""
    if term.current_calendar_revision_id is None:
        raise WeeklyPlanDataError("学期缺少当前日历修订")
    revision = db.execute(
        select(CalendarRevision)
        .where(CalendarRevision.id == term.current_calendar_revision_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if revision is None:
        raise WeeklyPlanDataError("当前日历修订缺失")

    week_start = cal.week_anchor(term.start_date) + timedelta(
        days=7 * (week_number - 1)
    )
    start = max(week_start, term.start_date)
    end = min(week_start + timedelta(days=6), term.end_date)

    days: dict[date, str] = {}
    if start > end:
        return days
    rows = db.scalars(
        select(CalendarDay)
        .where(
            CalendarDay.revision_id == revision.id,
            CalendarDay.date >= start,
            CalendarDay.date <= end,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all()
    by_date = {row.date: row for row in rows}
    current = start
    while current <= end:
        row = by_date.get(current)
        if row is None:
            raise WeeklyPlanDataError("日历快照缺少本周日期")
        state = row.effective_state
        if state == "teaching":
            days[current] = "teaching"
        elif state == "non_teaching":
            days[current] = "rest"
        else:
            raise WeeklyPlanDataError("日历快照日期状态未知")
        current += timedelta(days=1)
    return days


def _lock_weekly_plan(db: Session, plan_id: str) -> WeeklyPlan | None:
    return db.execute(
        select(WeeklyPlan)
        .where(WeeklyPlan.id == plan_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()


def _find_effective_weekly(
    db: Session, class_id: str, term_id: str, week_number: int, *, for_update: bool
) -> WeeklyPlan | None:
    stmt = select(WeeklyPlan).where(
        WeeklyPlan.class_id == class_id,
        WeeklyPlan.term_id == term_id,
        WeeklyPlan.week_number == week_number,
        WeeklyPlan.deleted_at.is_(None),
    )
    if for_update:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return db.execute(stmt).scalar_one_or_none()


def _preload_header(db: Session, plan_id: str) -> _HeaderIdentity:
    """Non-locking scalar pre-read used only to locate the lock prefix.

    Returns frozen scalars so a later ``populate_existing`` reload of the
    same ORM identity cannot rewrite the values under comparison.
    """
    row = db.execute(
        select(
            WeeklyPlan.id,
            WeeklyPlan.class_id,
            WeeklyPlan.term_id,
            WeeklyPlan.week_number,
            WeeklyPlan.deleted_at,
        ).where(WeeklyPlan.id == plan_id)
    ).one_or_none()
    if row is None or row[4] is not None:
        raise WeeklyPlanNotFound()
    return _HeaderIdentity(
        plan_id=row[0], class_id=row[1], term_id=row[2], week_number=row[3]
    )


def _assert_identity(
    locked: WeeklyPlan, header: _HeaderIdentity, plan_id: str
) -> None:
    if (
        locked.id != plan_id
        or locked.class_id != header.class_id
        or locked.term_id != header.term_id
        or locked.week_number != header.week_number
        or locked.deleted_at is not None
    ):
        raise WeeklyPlanNotFound()


def _lock_draft(db: Session, plan: WeeklyPlan) -> WeeklyPlanContent:
    if (
        plan.current_draft_content_id is None
        or plan.current_draft_version is None
    ):
        raise WeeklyPlanDataError("当前草稿指针为空")
    row = db.execute(
        select(WeeklyPlanContent)
        .where(WeeklyPlanContent.id == plan.current_draft_content_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if (
        row is None
        or row.weekly_plan_id != plan.id
        or row.version != plan.current_draft_version
    ):
        raise WeeklyPlanDataError("当前草稿指针不一致")
    return row


def _lock_confirmed_pointer(db: Session, plan: WeeklyPlan) -> None:
    cid = plan.current_confirmed_content_id
    cver = plan.current_confirmed_content_version
    if cid is None and cver is None:
        return
    if cid is None or cver is None:
        raise WeeklyPlanDataError("当前确认指针不完整")
    row = db.execute(
        select(WeeklyPlanConfirmedContent)
        .where(WeeklyPlanConfirmedContent.id == cid)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if (
        row is None
        or row.weekly_plan_id != plan.id
        or row.version != cver
    ):
        raise WeeklyPlanDataError("当前确认指针不一致")


def _assert_pointer_complete(
    plan: WeeklyPlan, content: WeeklyPlanContent
) -> None:
    if (
        plan.current_draft_content_id != content.id
        or plan.current_draft_version != content.version
        or plan.current_draft_content_id is None
        or plan.current_draft_version is None
    ):
        raise WeeklyPlanDataError("提交前草稿指针不完整")


def _strip_audit(content: dict[str, Any] | None) -> dict[str, Any]:
    """Return a top-level copy without the server ``_audit`` envelope."""
    if not isinstance(content, dict):
        return {}
    if _AUDIT_KEY in content:
        return {k: v for k, v in content.items() if k != _AUDIT_KEY}
    return dict(content)


def _attach_audit(
    content: dict[str, Any], audit: dict[str, Any]
) -> dict[str, Any]:
    stored = dict(content)
    stored[_AUDIT_KEY] = audit
    return stored


def _new_audit(
    action: str, operator_id: str, editor_role: str, now: datetime
) -> dict[str, Any]:
    return {
        "action": action,
        "editor_id": operator_id,
        "editor_role": editor_role,
        "recorded_at": now.isoformat(sep=" ", timespec="seconds"),
    }


def _load_week_sources(
    db: Session, plan: WeeklyPlan
) -> tuple[list[weekly_plan_sync_service.WeekPlanEntry], datetime]:
    """Lock this week's daily plans + contents, then the projection row.

    The sync row is read (locking read for freshness) but never written.
    """
    return _load_week_sources_by_key(
        db,
        class_id=plan.class_id,
        term_id=plan.term_id,
        week_number=plan.week_number,
    )


def _load_week_sources_by_key(
    db: Session, *, class_id: str, term_id: str, week_number: int
) -> tuple[list[weekly_plan_sync_service.WeekPlanEntry], datetime]:
    """Ordered-set FOR UPDATE of this week's daily plans + contents.

    This file re-implements I3's load with ``populate_existing`` so a prior
    non-locking pre-read in the same session cannot leave stale identity-map
    rows in play. Pointer checks mirror I3; then the projection row is read
    with FOR UPDATE (never written), validating status and updated_at.
    """
    stmt = (
        select(DailyPlan)
        .where(
            DailyPlan.class_id == class_id,
            DailyPlan.term_id == term_id,
            DailyPlan.week_number == week_number,
            DailyPlan.deleted_at.is_(None),
        )
        .order_by(DailyPlan.plan_date, DailyPlan.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    plans = list(db.scalars(stmt).all())
    if not plans:
        entries: list[weekly_plan_sync_service.WeekPlanEntry] = []
    else:
        content_ids = [plan.current_content_id for plan in plans]
        if any(content_id is None for content_id in content_ids):
            raise WeeklyPlanDataError("日计划缺少当前内容指针")
        content_stmt = (
            select(DailyPlanContent)
            .where(DailyPlanContent.id.in_(content_ids))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        content_rows = db.scalars(content_stmt).all()
        by_id = {row.id: row for row in content_rows}

        entries = []
        for plan in plans:
            row = by_id.get(plan.current_content_id)
            if (
                row is None
                or row.daily_plan_id != plan.id
                or row.version != plan.current_content_version
            ):
                raise WeeklyPlanDataError("日计划当前内容指针不一致")
            entries.append(
                weekly_plan_sync_service.WeekPlanEntry(
                    plan_id=plan.id,
                    content_id=row.id,
                    content_version=row.version,
                    plan_date=plan.plan_date,
                    adopted_content=row.adopted_content or {},
                )
            )

    sync = db.execute(
        select(WeeklyPlanSyncState)
        .where(
            WeeklyPlanSyncState.class_id == class_id,
            WeeklyPlanSyncState.term_id == term_id,
            WeeklyPlanSyncState.week_number == week_number,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if sync is None:
        if entries:
            raise WeeklyPlanDataError("存在日计划但缺少周计划同步投影")
        return entries, auth_service.utc_now()
    if sync.status != "pending_projection":
        raise WeeklyPlanDataError("周计划同步投影状态异常")
    if sync.updated_at is None:
        raise WeeklyPlanDataError("周计划同步投影缺少更新时间")
    return entries, sync.updated_at


def _lock_write_prefix(
    db: Session,
    snapshot: AuthSnapshot,
    header: _HeaderIdentity,
    class_id: str | None,
) -> tuple[Term, str]:
    """accounts -> session -> assignment(teacher) -> school -> class -> term.

    Teachers may not smuggle ``class_id``; their current assignment must
    exist and match the plan's class, re-checked under the row lock (owner_id
    alone is not enough). Admins still need an explicit matching class_id.
    """
    _lock_operator(db, snapshot)
    if snapshot.role == "teacher":
        if class_id is not None:
            raise WeeklyPlanValidationError("教师请求不得包含 class_id")
        assignment = _lock_teacher_assignment(db, snapshot)
        if assignment is None or assignment.class_id != header.class_id:
            raise WeeklyPlanForbidden()
    elif snapshot.role == "admin":
        if not class_id:
            raise WeeklyPlanValidationError("管理员请求必须包含 class_id")
        if class_id != header.class_id:
            raise WeeklyPlanNotFound("班级上下文与周计划不符")
    else:
        raise WeeklyPlanForbidden()
    lock_school(db)
    lock_class(db, header.class_id)
    try:
        term = lock_term(db, header.term_id)
    except ConfigTermNotFound as exc:
        raise WeeklyPlanDataError("周计划学期缺失") from exc
    return term, header.class_id


def create_or_open_weekly_plan(
    db: Session,
    snapshot: AuthSnapshot,
    *,
    term_id: str,
    week_number: int,
    theme: str | None = None,
    class_id: str | None = None,
) -> WeeklyPlanWriteResult:
    """Create the effective weekly plan, or open the existing one (201/200).

    Admins may never create (403). A unique-key clash rolls back the whole
    transaction and re-reads the committed winner under a fresh permission
    prefix, preserving creator/owner.
    """
    _require_role(snapshot)
    if snapshot.role == "admin":
        raise WeeklyPlanForbidden("管理员不能创建周计划")
    if class_id is not None:
        raise WeeklyPlanValidationError("教师请求不得包含 class_id")
    week = _validate_week_number(week_number)
    theme_value = _normalize_theme(theme)
    if not isinstance(term_id, str) or not term_id:
        raise WeeklyPlanTermNotFound()

    _begin(db)
    try:
        return _create_or_open_locked(
            db,
            snapshot,
            term_id=term_id,
            week_number=week,
            theme_value=theme_value,
        )
    except IntegrityError as exc:
        _rollback(db)
        if not is_weekly_effective_unique_violation(exc):
            raise
        try:
            return _open_existing_after_conflict(
                db, snapshot, term_id=term_id, week_number=week
            )
        except Exception:
            # Fresh-transaction reread must release locks on any failure
            # (forbidden/data errors included); only fall back to the
            # original 1062 when no winner row can be opened.
            _rollback(db)
            raise
    except Exception:
        _rollback(db)
        raise


def _open_existing_after_conflict(
    db: Session,
    snapshot: AuthSnapshot,
    *,
    term_id: str,
    week_number: int,
) -> WeeklyPlanWriteResult:
    """Fresh transaction: full permission prefix, then open the winner."""
    _begin(db)
    operator = _lock_operator(db, snapshot)
    resolved_class_id = _resolve_create_class(db, snapshot)
    lock_school(db)
    lock_class(db, resolved_class_id)
    term = _require_term(db, term_id, for_write=True)
    _validate_week_in_term(term, week_number)

    existing = _find_effective_weekly(
        db, resolved_class_id, term_id, week_number, for_update=True
    )
    if existing is None:
        raise WeeklyPlanNotFound()

    draft = _lock_draft(db, existing)
    _lock_confirmed_pointer(db, existing)
    confirmed = _load_confirmed_unlocked(db, existing)
    _validate_week_in_term(term, existing.week_number)
    result = WeeklyPlanWriteResult(
        plan=existing,
        draft=draft,
        confirmed=confirmed,
        created=False,
    )
    db.commit()
    return result


def _create_or_open_locked(
    db: Session,
    snapshot: AuthSnapshot,
    *,
    term_id: str,
    week_number: int,
    theme_value: str,
) -> WeeklyPlanWriteResult:
    operator = _lock_operator(db, snapshot)
    resolved_class_id = _resolve_create_class(db, snapshot)
    school = lock_school(db)
    school_class = lock_class(db, resolved_class_id)
    term = _require_term(db, term_id, for_write=True)
    _validate_week_in_term(term, week_number)

    # Calendar (revision + week days) must lock before any weekly row.
    days = _load_week_days(db, term, week_number)

    existing = _find_effective_weekly(
        db, resolved_class_id, term_id, week_number, for_update=True
    )
    if existing is not None:
        draft = _lock_draft(db, existing)
        _lock_confirmed_pointer(db, existing)
        confirmed = _load_confirmed_unlocked(db, existing)
        result = WeeklyPlanWriteResult(
            plan=existing,
            draft=draft,
            confirmed=confirmed,
            created=False,
        )
        db.commit()
        return result

    entries, consumed_at = _load_week_sources_by_key(
        db,
        class_id=resolved_class_id,
        term_id=term_id,
        week_number=week_number,
    )
    content_body = weekly_plan_content.new_content(
        entries, days, theme_value
    )

    now = auth_service.utc_now()
    plan = WeeklyPlan(
        id=security.generate_id(),
        class_id=resolved_class_id,
        term_id=term_id,
        week_number=week_number,
        creator_id=operator.id,
        owner_id=operator.id,
        current_draft_content_id=None,
        current_draft_version=None,
        current_confirmed_content_id=None,
        current_confirmed_content_version=None,
        school_name=school.school_name,
        class_name=school_class.name,
        grade=school_class.grade,
        header_teacher_names=deepcopy(school_class.header_teacher_names),
        caregiver_name=school_class.caregiver_name,
        projection_consumed_at=consumed_at,
        deleted_at=None,
        deleted_by=None,
        created_at=now,
        updated_at=now,
    )
    db.add(plan)
    db.flush()

    content = WeeklyPlanContent(
        id=security.generate_id(),
        weekly_plan_id=plan.id,
        version=1,
        content=_attach_audit(
            content_body,
            _new_audit("create", operator.id, "owner", now),
        ),
        editor_id=operator.id,
        editor_role="owner",
        created_at=now,
    )
    db.add(content)
    db.flush()

    plan.current_draft_content_id = content.id
    plan.current_draft_version = content.version
    plan.updated_at = now
    db.flush()
    _assert_pointer_complete(plan, content)

    confirmed = None
    auth_service.record_operation(
        db,
        operator_id=operator.id,
        operator_type="account",
        action="create_weekly_plan",
        target_type="weekly_plan",
        target_id=plan.id,
        target_version_after=content.version,
    )
    result = WeeklyPlanWriteResult(
        plan=plan,
        draft=content,
        confirmed=confirmed,
        created=True,
    )
    db.commit()
    return result


def _require_term(db: Session, term_id: str, *, for_write: bool) -> Term:
    try:
        return lock_term(db, term_id)
    except ConfigTermNotFound as exc:
        if for_write:
            raise WeeklyPlanTermNotFound() from exc
        raise WeeklyPlanDataError("周计划学期缺失") from exc


def _load_confirmed_unlocked(
    db: Session, plan: WeeklyPlan
) -> WeeklyPlanConfirmedContent | None:
    cid = plan.current_confirmed_content_id
    cver = plan.current_confirmed_content_version
    if cid is None and cver is None:
        return None
    if cid is None or cver is None:
        raise WeeklyPlanDataError("当前确认指针不完整")
    row = db.get(WeeklyPlanConfirmedContent, cid)
    if (
        row is None
        or row.weekly_plan_id != plan.id
        or row.version != cver
    ):
        raise WeeklyPlanDataError("当前确认指针不一致")
    return row


def _validate_patch_shape(patch: Any) -> dict[str, Any]:
    if not isinstance(patch, dict):
        raise WeeklyPlanValidationError("patch 必须是 JSON 对象")
    unknown = set(patch) - _PATCH_FIELDS
    if unknown:
        raise WeeklyPlanValidationError(
            f"patch 含不支持的字段：{sorted(unknown)}"
        )
    return patch


def _map_content_error(exc: Exception) -> Exception:
    if isinstance(exc, weekly_plan_content.ContentValidationError):
        return WeeklyPlanValidationError(str(exc))
    return exc


def save_weekly_plan(
    db: Session,
    snapshot: AuthSnapshot,
    *,
    plan_id: str,
    expected_draft_version: int,
    patch: dict[str, Any],
    class_id: str | None = None,
) -> WeeklyPlanWriteResult:
    """Append a new draft version (owner teacher or admin only).

    Omitted fields inherit the current draft inside ``prepare_patch``;
    existing daily-plan source references are never re-stamped here.
    """
    expected = _validate_expected_version(expected_draft_version)
    validated_patch = _validate_patch_shape(patch)

    _begin(db)
    try:
        return _save_locked(
            db,
            snapshot,
            plan_id=plan_id,
            expected_draft_version=expected,
            patch=validated_patch,
            class_id=class_id,
        )
    except Exception as exc:
        _rollback(db)
        raise _map_content_error(exc) from None


def _save_locked(
    db: Session,
    snapshot: AuthSnapshot,
    *,
    plan_id: str,
    expected_draft_version: int,
    patch: dict[str, Any],
    class_id: str | None,
) -> WeeklyPlanWriteResult:
    header = _preload_header(db, plan_id)
    term, resolved_class_id = _lock_write_prefix(
        db, snapshot, header, class_id
    )
    _validate_week_in_term(term, header.week_number)
    days = _load_week_days(db, term, header.week_number)
    plan = _lock_weekly_plan(db, plan_id)
    if plan is None:
        raise WeeklyPlanNotFound()
    _assert_identity(plan, header, plan_id)
    if plan.class_id != resolved_class_id:
        raise WeeklyPlanForbidden()
    if not (
        snapshot.role == "admin" or plan.owner_id == snapshot.account_id
    ):
        raise WeeklyPlanForbidden()

    draft = _lock_draft(db, plan)
    if plan.current_draft_version != expected_draft_version:
        raise WeeklyPlanVersionConflict()
    _lock_confirmed_pointer(db, plan)
    entries, consumed_at = _load_week_sources(db, plan)

    editor_role = "admin" if snapshot.role == "admin" else "owner"
    now = auth_service.utc_now()
    body = weekly_plan_content.prepare_patch(
        _strip_audit(draft.content), patch, entries, days
    )

    new_version = draft.version + 1
    content = WeeklyPlanContent(
        id=security.generate_id(),
        weekly_plan_id=plan.id,
        version=new_version,
        content=_attach_audit(
            body, _new_audit("save", snapshot.account_id, editor_role, now)
        ),
        editor_id=snapshot.account_id,
        editor_role=editor_role,
        created_at=now,
    )
    db.add(content)
    db.flush()

    plan.current_draft_content_id = content.id
    plan.current_draft_version = new_version
    plan.projection_consumed_at = consumed_at
    plan.updated_at = now
    db.flush()
    _assert_pointer_complete(plan, content)

    confirmed = _load_confirmed_unlocked(db, plan)
    auth_service.record_operation(
        db,
        operator_id=snapshot.account_id,
        operator_type="account",
        action="save_weekly_plan",
        target_type="weekly_plan",
        target_id=plan.id,
        target_version_after=new_version,
    )
    result = WeeklyPlanWriteResult(
        plan=plan, draft=content, confirmed=confirmed
    )
    db.commit()
    return result


def refresh_weekly_sources(
    db: Session,
    snapshot: AuthSnapshot,
    *,
    plan_id: str,
    expected_draft_version: int,
    class_id: str | None = None,
) -> WeeklyPlanWriteResult:
    """Explicitly re-resolve selected sources and recompute deterministic rows.

    Theme, manual overrides and weekly columns stay untouched; the append
    records action ``refresh_weekly_sources`` with per-source from/to facts.
    """
    expected = _validate_expected_version(expected_draft_version)

    _begin(db)
    try:
        return _refresh_locked(
            db,
            snapshot,
            plan_id=plan_id,
            expected_draft_version=expected,
            class_id=class_id,
        )
    except Exception as exc:
        _rollback(db)
        raise _map_content_error(exc) from None


def _refresh_locked(
    db: Session,
    snapshot: AuthSnapshot,
    *,
    plan_id: str,
    expected_draft_version: int,
    class_id: str | None,
) -> WeeklyPlanWriteResult:
    header = _preload_header(db, plan_id)
    term, resolved_class_id = _lock_write_prefix(
        db, snapshot, header, class_id
    )
    _validate_week_in_term(term, header.week_number)
    days = _load_week_days(db, term, header.week_number)
    plan = _lock_weekly_plan(db, plan_id)
    if plan is None:
        raise WeeklyPlanNotFound()
    _assert_identity(plan, header, plan_id)
    if plan.class_id != resolved_class_id:
        raise WeeklyPlanForbidden()
    if not (
        snapshot.role == "admin" or plan.owner_id == snapshot.account_id
    ):
        raise WeeklyPlanForbidden()

    draft = _lock_draft(db, plan)
    if plan.current_draft_version != expected_draft_version:
        raise WeeklyPlanVersionConflict()
    _lock_confirmed_pointer(db, plan)
    entries, consumed_at = _load_week_sources(db, plan)

    body, refreshed_sources = weekly_plan_content.refresh_content(
        _strip_audit(draft.content), entries, days
    )

    editor_role = "admin" if snapshot.role == "admin" else "owner"
    now = auth_service.utc_now()
    audit = _new_audit("refresh", snapshot.account_id, editor_role, now)
    audit["refreshed_sources"] = refreshed_sources or []

    new_version = draft.version + 1
    content = WeeklyPlanContent(
        id=security.generate_id(),
        weekly_plan_id=plan.id,
        version=new_version,
        content=_attach_audit(body, audit),
        editor_id=snapshot.account_id,
        editor_role=editor_role,
        created_at=now,
    )
    db.add(content)
    db.flush()

    plan.current_draft_content_id = content.id
    plan.current_draft_version = new_version
    plan.projection_consumed_at = consumed_at
    plan.updated_at = now
    db.flush()
    _assert_pointer_complete(plan, content)

    confirmed = _load_confirmed_unlocked(db, plan)
    auth_service.record_operation(
        db,
        operator_id=snapshot.account_id,
        operator_type="account",
        action="refresh_weekly_sources",
        target_type="weekly_plan",
        target_id=plan.id,
        target_version_after=new_version,
    )
    result = WeeklyPlanWriteResult(
        plan=plan,
        draft=content,
        confirmed=confirmed,
        refreshed_sources=refreshed_sources or [],
    )
    db.commit()
    return result


def confirm_weekly_plan(
    db: Session,
    snapshot: AuthSnapshot,
    *,
    plan_id: str,
    expected_draft_version: int,
    acknowledge_missing: bool,
    acknowledge_stale: bool,
    note: str | None = None,
    class_id: str | None = None,
) -> WeeklyPlanWriteResult:
    """Atomically append an immutable confirmed snapshot (owner only).

    Never refreshes implicitly: stale sources keep their old ids/versions
    and texts, while ``facts.stale_sources`` records both sides. Facts are
    recomputed under lock; missing/stale facts without the matching ack
    raise 409 CONFIRM_ACK_REQUIRED carrying the facts back.
    """
    expected = _validate_expected_version(expected_draft_version)
    if not isinstance(acknowledge_missing, bool) or not isinstance(
        acknowledge_stale, bool
    ):
        raise WeeklyPlanValidationError(
            "acknowledge_missing/acknowledge_stale 必须是布尔值"
        )
    if note is not None and not isinstance(note, str):
        raise WeeklyPlanValidationError("note 必须是字符串或 null")

    _begin(db)
    try:
        return _confirm_locked(
            db,
            snapshot,
            plan_id=plan_id,
            expected_draft_version=expected,
            acknowledge_missing=acknowledge_missing,
            acknowledge_stale=acknowledge_stale,
            note=note,
            class_id=class_id,
        )
    except Exception as exc:
        _rollback(db)
        raise _map_content_error(exc) from None


def _confirm_locked(
    db: Session,
    snapshot: AuthSnapshot,
    *,
    plan_id: str,
    expected_draft_version: int,
    acknowledge_missing: bool,
    acknowledge_stale: bool,
    note: str | None,
    class_id: str | None,
) -> WeeklyPlanWriteResult:
    if snapshot.role == "admin":
        raise WeeklyPlanForbidden("管理员不能确认周计划")

    header = _preload_header(db, plan_id)
    term, resolved_class_id = _lock_write_prefix(
        db, snapshot, header, class_id
    )
    _validate_week_in_term(term, header.week_number)
    days = _load_week_days(db, term, header.week_number)

    plan = _lock_weekly_plan(db, plan_id)
    if plan is None:
        raise WeeklyPlanNotFound()
    _assert_identity(plan, header, plan_id)
    if plan.class_id != resolved_class_id:
        raise WeeklyPlanForbidden()
    if plan.owner_id != snapshot.account_id:
        raise WeeklyPlanForbidden()

    draft = _lock_draft(db, plan)
    if plan.current_draft_version != expected_draft_version:
        raise WeeklyPlanVersionConflict()
    _lock_confirmed_pointer(db, plan)
    entries, _consumed_at = _load_week_sources(db, plan)

    body = _strip_audit(draft.content)
    built = weekly_plan_content.build_facts(body, entries, days)
    missing = list(built.get("missing") or [])
    stale_sources = list(built.get("stale_sources") or [])
    facts: dict[str, Any] = {
        "missing": missing,
        "stale_sources": stale_sources,
        "ack_missing": acknowledge_missing,
        "ack_stale": acknowledge_stale,
        "note": note if note else None,
    }
    if (missing and not acknowledge_missing) or (
        stale_sources and not acknowledge_stale
    ):
        raise WeeklyPlanConfirmAckRequired(facts=facts)

    now = auth_service.utc_now()
    next_confirmed = (plan.current_confirmed_content_version or 0) + 1
    confirmed = WeeklyPlanConfirmedContent(
        id=security.generate_id(),
        weekly_plan_id=plan.id,
        version=next_confirmed,
        draft_version=draft.version,
        content=deepcopy(draft.content),
        facts=facts,
        confirmed_by=snapshot.account_id,
        created_at=now,
    )
    db.add(confirmed)
    db.flush()

    plan.current_confirmed_content_id = confirmed.id
    plan.current_confirmed_content_version = next_confirmed
    plan.updated_at = now
    db.flush()

    auth_service.record_operation(
        db,
        operator_id=snapshot.account_id,
        operator_type="account",
        action="confirm_weekly_plan",
        target_type="weekly_plan",
        target_id=plan.id,
        target_version_after=next_confirmed,
    )
    result = WeeklyPlanWriteResult(
        plan=plan,
        draft=draft,
        confirmed=confirmed,
        facts=facts,
    )
    db.commit()
    return result
