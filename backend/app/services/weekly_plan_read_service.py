"""I4 weekly plan read-only queries and response assembly (slice 2).

Read side only: no transaction, no ``FOR UPDATE``, no draft rebuild and no
write to ``weekly_plan_sync_states``. GET recomputes live missing / stale
facts from the stored draft against the week's current daily plan contents
(freshness authority), exposes ``source_candidates`` for pickers, the
``projection_pending`` banner flag (sync row ``updated_at`` newer than
``projection_consumed_at``), the immutable header snapshot (U1=A) and
can_edit / can_confirm derived from role + owner. Confirmation history and
single versions are read as stored; the server ``_audit`` envelope is never
leaked inside ``content``.

Permission on reads: the router derives the class context (teacher from the
current assignment, admin from explicit ``class_id``); the functions here
re-judge plan-vs-context: unknown id 404 ``WEEKLY_PLAN_NOT_FOUND`` for both
roles, teacher class mismatch 403 ``FORBIDDEN``, admin class mismatch 404
``WEEKLY_PLAN_NOT_FOUND`` (never a cross-class leak). Errors reuse the
slice-1 service exception classes for a single HTTP mapping table.
"""

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    CalendarDay,
    CalendarRevision,
    Term,
    WeeklyPlan,
    WeeklyPlanContent,
    WeeklyPlanConfirmedContent,
)
from app.services import calendar_service as cal
from app.services import weekly_plan_content, weekly_plan_sync_service
from app.services.weekly_plan_service import (
    WeeklyPlanDataError,
    WeeklyPlanForbidden,
    WeeklyPlanNotFound,
    WeeklyPlanTermNotFound,
)

AUDIT_KEY = "_audit"

CONFIRMATION_NEVER = "never_confirmed"
CONFIRMATION_DRAFT_AHEAD = "draft_ahead"
CONFIRMATION_DRAFT_CURRENT = "draft_current"


def public_content(content) -> dict:
    """Stored content as the public §2.5 structure (server ``_audit`` out)."""
    if not isinstance(content, dict):
        return {}
    if AUDIT_KEY in content:
        return {k: v for k, v in content.items() if k != AUDIT_KEY}
    return dict(content)


def _audit_of(content) -> dict | None:
    if isinstance(content, dict):
        audit = content.get(AUDIT_KEY)
        if isinstance(audit, dict):
            return audit
    return None


def _load_plan(db: Session, plan_id: str) -> WeeklyPlan:
    plan = db.get(WeeklyPlan, plan_id)
    if plan is None or plan.deleted_at is not None:
        raise WeeklyPlanNotFound()
    return plan


def _assert_class_access(plan: WeeklyPlan, *, role: str, class_id: str) -> None:
    if plan.class_id == class_id:
        return
    if role == "admin":
        raise WeeklyPlanNotFound("班级上下文与周计划不符")
    raise WeeklyPlanForbidden()


def _load_draft(db: Session, plan: WeeklyPlan) -> WeeklyPlanContent:
    if (
        plan.current_draft_content_id is None
        or plan.current_draft_version is None
    ):
        raise WeeklyPlanDataError("当前草稿指针为空")
    row = db.get(WeeklyPlanContent, plan.current_draft_content_id)
    if (
        row is None
        or row.weekly_plan_id != plan.id
        or row.version != plan.current_draft_version
    ):
        raise WeeklyPlanDataError("当前草稿指针不一致")
    return row


def _load_confirmed(
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


def _load_term(db: Session, term_id: str) -> Term:
    term = db.get(Term, term_id)
    if term is None:
        raise WeeklyPlanTermNotFound()
    return term


def _read_week_days(db: Session, term: Term, week_number: int) -> dict[date, str]:
    """Calendar days of the week, plain reads (no locks, GET only)."""
    if term.current_calendar_revision_id is None:
        raise WeeklyPlanDataError("学期缺少当前日历修订")
    revision = db.get(CalendarRevision, term.current_calendar_revision_id)
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
        select(CalendarDay).where(
            CalendarDay.revision_id == revision.id,
            CalendarDay.date >= start,
            CalendarDay.date <= end,
        )
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


def _live_context(
    db: Session, plan: WeeklyPlan
) -> tuple[dict[date, str], list, bool]:
    """Week days + current daily plan entries + projection_pending flag.

    The sync row is a plain read (never written, never locked here); a row
    missing while the week has daily plans is the I3 invariant break (503),
    mirroring the write-side semantics.
    """
    term = _load_term(db, plan.term_id)
    days = _read_week_days(db, term, plan.week_number)
    entries = weekly_plan_sync_service.load_week_entries(
        db, plan.class_id, plan.term_id, plan.week_number, for_update=False
    )
    sync = weekly_plan_sync_service.get_weekly_sync_state(
        db, plan.class_id, plan.term_id, plan.week_number
    )
    if sync is None:
        if entries:
            raise WeeklyPlanDataError("存在日计划但缺少周计划同步投影")
        return days, entries, False
    if sync.status != "pending_projection":
        raise WeeklyPlanDataError("周计划同步投影状态异常")
    if sync.updated_at is None:
        raise WeeklyPlanDataError("周计划同步投影缺少更新时间")
    consumed = plan.projection_consumed_at
    pending = consumed is None or sync.updated_at > consumed
    return days, entries, pending


def _confirmation_status(
    confirmed: WeeklyPlanConfirmedContent | None, draft_version: int
) -> str:
    if confirmed is None:
        return CONFIRMATION_NEVER
    if confirmed.draft_version < draft_version:
        return CONFIRMATION_DRAFT_AHEAD
    return CONFIRMATION_DRAFT_CURRENT


def _permissions(
    plan: WeeklyPlan, *, account_id: str, role: str
) -> tuple[bool, bool]:
    """(can_edit, can_confirm): admin edits never confirms; owner does both."""
    if role == "admin":
        return True, False
    is_owner = plan.owner_id == account_id
    return is_owner, is_owner


def _confirmed_summary(confirmed: WeeklyPlanConfirmedContent) -> dict:
    return {
        "version": confirmed.version,
        "draft_version": confirmed.draft_version,
        "confirmed_by": confirmed.confirmed_by,
        "facts": confirmed.facts,
        "created_at": confirmed.created_at,
    }


def _detail_payload(
    db: Session,
    plan: WeeklyPlan,
    draft: WeeklyPlanContent,
    confirmed: WeeklyPlanConfirmedContent | None,
    *,
    account_id: str,
    role: str,
    refreshed_sources: list[dict] | None = None,
) -> dict:
    days, entries, projection_pending = _live_context(db, plan)
    body = public_content(draft.content)
    facts = weekly_plan_content.build_facts(body, entries, days)
    candidates = weekly_plan_content.build_source_candidates(entries)
    status = _confirmation_status(confirmed, draft.version)
    can_edit, can_confirm = _permissions(
        plan, account_id=account_id, role=role
    )
    return {
        "id": plan.id,
        "class_id": plan.class_id,
        "term_id": plan.term_id,
        "week_number": plan.week_number,
        "creator_id": plan.creator_id,
        "owner_id": plan.owner_id,
        "school_name": plan.school_name,
        "class_name": plan.class_name,
        "grade": plan.grade,
        "header_teacher_names": list(plan.header_teacher_names or []),
        "caregiver_name": plan.caregiver_name,
        "confirmation_status": status,
        "needs_confirm": status != CONFIRMATION_DRAFT_CURRENT,
        "draft": {
            "id": draft.id,
            "version": draft.version,
            "content": body,
            "audit": _audit_of(draft.content),
            "editor_id": draft.editor_id,
            "editor_role": draft.editor_role,
            "created_at": draft.created_at,
        },
        "confirmed": (
            _confirmed_summary(confirmed) if confirmed is not None else None
        ),
        "missing": list(facts.get("missing") or []),
        "stale_sources": list(facts.get("stale_sources") or []),
        "projection_pending": projection_pending,
        "source_candidates": candidates,
        "can_edit": can_edit,
        "can_confirm": can_confirm,
        "refreshed_sources": refreshed_sources,
        "created_at": plan.created_at,
        "updated_at": plan.updated_at,
    }


def get_detail(
    db: Session,
    plan_id: str,
    *,
    account_id: str,
    role: str,
    class_id: str,
) -> dict:
    """GET detail: read-only assembly of draft, facts, candidates, flags."""
    plan = _load_plan(db, plan_id)
    _assert_class_access(plan, role=role, class_id=class_id)
    draft = _load_draft(db, plan)
    confirmed = _load_confirmed(db, plan)
    return _detail_payload(
        db, plan, draft, confirmed, account_id=account_id, role=role
    )


def assemble_from_result(
    db: Session,
    result,
    *,
    account_id: str,
    role: str,
    refreshed_sources: list[dict] | None = None,
) -> dict:
    """Detail after a locked write entry (permission already re-judged there)."""
    return _detail_payload(
        db,
        result.plan,
        result.draft,
        result.confirmed,
        account_id=account_id,
        role=role,
        refreshed_sources=refreshed_sources,
    )


def list_plans(
    db: Session,
    *,
    class_id: str,
    term_id: str | None,
    offset: int,
    limit: int,
) -> tuple[list[dict], int]:
    """Paged effective weekly plans of one class (optional term filter)."""
    if term_id is not None and db.get(Term, term_id) is None:
        raise WeeklyPlanTermNotFound()

    conditions = [
        WeeklyPlan.class_id == class_id,
        WeeklyPlan.deleted_at.is_(None),
    ]
    if term_id is not None:
        conditions.append(WeeklyPlan.term_id == term_id)

    total = (
        db.scalar(select(func.count()).select_from(WeeklyPlan).where(*conditions))
        or 0
    )
    rows = db.scalars(
        select(WeeklyPlan)
        .where(*conditions)
        .order_by(WeeklyPlan.term_id, WeeklyPlan.week_number, WeeklyPlan.id)
        .offset(offset)
        .limit(limit)
    ).all()

    items: list[dict] = []
    for plan in rows:
        if (
            plan.current_draft_content_id is None
            or plan.current_draft_version is None
        ):
            raise WeeklyPlanDataError("当前草稿指针为空")
        confirmed_version, needs_confirm = _list_confirmation_state(db, plan)
        items.append(
            {
                "id": plan.id,
                "term_id": plan.term_id,
                "week_number": plan.week_number,
                "creator_id": plan.creator_id,
                "owner_id": plan.owner_id,
                "draft_version": plan.current_draft_version,
                "confirmed_version": confirmed_version,
                "needs_confirm": needs_confirm,
                "updated_at": plan.updated_at,
            }
        )
    return items, int(total)


def _list_confirmation_state(
    db: Session, plan: WeeklyPlan
) -> tuple[int | None, bool]:
    cid = plan.current_confirmed_content_id
    cver = plan.current_confirmed_content_version
    if cid is None and cver is None:
        # Never confirmed counts as needing the first confirmation; only a
        # confirmation matching the current draft clears needs_confirm.
        return None, True
    if cid is None or cver is None:
        raise WeeklyPlanDataError("当前确认指针不完整")
    row = db.get(WeeklyPlanConfirmedContent, cid)
    if (
        row is None
        or row.weekly_plan_id != plan.id
        or row.version != cver
    ):
        raise WeeklyPlanDataError("当前确认指针不一致")
    needs = row.draft_version < (plan.current_draft_version or 0)
    return row.version, needs


def list_confirmations(
    db: Session,
    plan_id: str,
    *,
    role: str,
    class_id: str,
) -> dict:
    plan = _load_plan(db, plan_id)
    _assert_class_access(plan, role=role, class_id=class_id)
    rows = db.scalars(
        select(WeeklyPlanConfirmedContent)
        .where(WeeklyPlanConfirmedContent.weekly_plan_id == plan.id)
        .order_by(WeeklyPlanConfirmedContent.version)
    ).all()
    items = [_confirmed_summary(row) for row in rows]
    return {"items": items, "total": len(items)}


def get_confirmation(
    db: Session,
    plan_id: str,
    version: int,
    *,
    role: str,
    class_id: str,
) -> dict:
    plan = _load_plan(db, plan_id)
    _assert_class_access(plan, role=role, class_id=class_id)
    row = db.scalars(
        select(WeeklyPlanConfirmedContent).where(
            WeeklyPlanConfirmedContent.weekly_plan_id == plan.id,
            WeeklyPlanConfirmedContent.version == version,
        )
    ).one_or_none()
    if row is None:
        raise WeeklyPlanNotFound("确认版本不存在")
    return {
        "id": row.id,
        "weekly_plan_id": row.weekly_plan_id,
        "version": row.version,
        "draft_version": row.draft_version,
        "content": public_content(row.content),
        "facts": row.facts,
        "confirmed_by": row.confirmed_by,
        "created_at": row.created_at,
    }
