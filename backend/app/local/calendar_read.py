"""Local effective-calendar reads from persisted revisions only.

Week numbers and weekday come from the reviewed pure rules; the library is
never called on this path. A missing persisted day row for a date inside a
term is a data error (``LOCAL_STORAGE_ERROR``), never a live recompute.
Creation eligibility (``date_eligible``) and the existing-plan entry are
separate fields: days without teaching eligibility still report an existing
plan id.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.local.errors import LocalStorageError
from app.local.models import (
    LocalCalendarDay,
    LocalCalendarRevision,
    LocalDailyPlan,
    LocalTerm,
)
from app.local.normalize import validate_date_range
from app.services import calendar_service as cal

MAX_CALENDAR_RANGE_DAYS = 366


def _reason(row: LocalCalendarDay) -> str | None:
    if row.override_state is not None:
        return row.override_reason
    if row.base_state == cal.UNKNOWN:
        return "该年份的日历数据尚未就绪"
    if row.effective_state == cal.NON_TEACHING:
        return "非上课日"
    return None


def explain_range(
    session: Session,
    *,
    class_id: str,
    from_date: date,
    to_date: date,
) -> list[dict]:
    """Explain every day of the closed range (caller holds the read scope)."""
    validate_date_range(
        from_date, to_date, max_days=MAX_CALENDAR_RANGE_DAYS
    )

    terms = list(
        session.scalars(
            select(LocalTerm).order_by(LocalTerm.start_date, LocalTerm.id)
        ).all()
    )
    relevant = [
        term
        for term in terms
        if cal.ranges_overlap(from_date, to_date, term.start_date, term.end_date)
    ]

    revision_ids: dict[str, str] = {}
    days_by_term: dict[str, dict[date, LocalCalendarDay]] = {}
    for term in relevant:
        revision_id = term.current_calendar_revision_id
        if revision_id is None:
            raise LocalStorageError("学期缺少当前日历修订")
        revision = session.get(LocalCalendarRevision, revision_id)
        if revision is None or revision.term_id != term.id:
            raise LocalStorageError("当前日历修订缺失")
        revision_ids[term.id] = revision_id
        rows = session.scalars(
            select(LocalCalendarDay).where(
                LocalCalendarDay.revision_id == revision_id
            )
        ).all()
        days_by_term[term.id] = {row.date: row for row in rows}

    plan_rows = session.scalars(
        select(LocalDailyPlan).where(
            LocalDailyPlan.class_id == class_id,
            LocalDailyPlan.deleted_at.is_(None),
            LocalDailyPlan.plan_date >= from_date,
            LocalDailyPlan.plan_date <= to_date,
        )
    ).all()
    plans_by_date: dict[date, str] = {}
    for row in plan_rows:
        if row.plan_date in plans_by_date:
            raise LocalStorageError("同一日期存在多份有效计划")
        plans_by_date[row.plan_date] = row.id

    items: list[dict] = []
    for day in cal.iter_dates(from_date, to_date):
        term = next(
            (
                candidate
                for candidate in relevant
                if candidate.start_date <= day <= candidate.end_date
            ),
            None,
        )
        if term is None:
            items.append(
                {
                    "date": day.isoformat(),
                    "term_id": None,
                    "week_number": None,
                    "weekday": None,
                    "effective_state": cal.OUTSIDE_TERM,
                    "date_eligible": False,
                    "reason": "学期外",
                    "revision_id": None,
                    # D1B §10.1: the existing-record entry is independent of
                    # the current date interpretation; a plan moved outside
                    # every current range must still be openable.
                    "existing_plan_id": plans_by_date.get(day),
                }
            )
            continue
        row = days_by_term[term.id].get(day)
        if row is None:
            raise LocalStorageError("日历快照缺少目标日期")
        week_number, _week_start, weekday = cal.week_info(term.start_date, day)
        items.append(
            {
                "date": day.isoformat(),
                "term_id": term.id,
                "week_number": week_number,
                "weekday": weekday,
                "effective_state": row.effective_state,
                "date_eligible": row.effective_state == cal.TEACHING,
                "reason": _reason(row),
                "revision_id": revision_ids[term.id],
                "existing_plan_id": plans_by_date.get(day),
            }
        )
    return items
