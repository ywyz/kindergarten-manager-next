"""Read-side term and calendar date explanation.

All queries in one call run against a single REPEATABLE READ snapshot (the
autobegun read transaction), so a response never mixes revisions. Dates are
interpreted by membership first: find the unique term containing the date
(P1), then read its current revision snapshot.
"""

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CalendarDay, SchoolSettings, Term
from app.services import calendar_service as cal
from app.services.config_errors import MAX_QUERY_DAYS


class CalendarDataError(Exception):
    """Persisted calendar snapshot is missing/corrupt (maps to 503)."""


def list_terms(
    db: Session, *, offset: int, limit: int
) -> tuple[list[Term], int]:
    from sqlalchemy import func

    total = db.scalar(select(func.count()).select_from(Term)) or 0
    rows = (
        db.execute(
            select(Term).order_by(Term.start_date, Term.id)
            .offset(offset)
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return list(rows), total


def _find_term(db: Session, day: date, terms: list[Term]) -> Term | None:
    for term in terms:
        if term.start_date <= day <= term.end_date:
            return term
    return None


def explain_range(
    db: Session, from_date: date, to_date: date
) -> tuple[list[dict], int]:
    if from_date > to_date:
        raise ValueError("from must be <= to")
    if (to_date - from_date).days + 1 > MAX_QUERY_DAYS:
        raise ValueError(f"range exceeds {MAX_QUERY_DAYS} days")

    # One snapshot for the whole response: all terms.
    terms = list(db.scalars(select(Term)).all())

    # Which terms intersect the query range.
    relevant = [
        t
        for t in terms
        if cal.ranges_overlap(from_date, to_date, t.start_date, t.end_date)
    ]

    # Load current-revision days for each relevant term in the same snapshot.
    day_rows: dict[str, dict[date, CalendarDay]] = {}
    for term in relevant:
        revision_id = term.current_calendar_revision_id
        if revision_id is None:
            raise CalendarDataError("term has no current calendar revision")
        rows = db.scalars(
            select(CalendarDay).where(CalendarDay.revision_id == revision_id)
        ).all()
        mapping = {r.date: r for r in rows}
        day_rows[term.id] = mapping

    school = db.scalar(
        select(SchoolSettings).where(SchoolSettings.id == "singleton")
    )
    schedule_version = school.schedule_version if school else None

    items: list[dict] = []
    current = from_date
    while current <= to_date:
        term = _find_term(db, current, relevant)
        if term is None:
            items.append(
                {
                    "date": current.isoformat(),
                    "term_id": None,
                    "term_version": None,
                    "calendar_revision_id": None,
                    "week_number": None,
                    "week_start": None,
                    "weekday": None,
                    "base_state": None,
                    "override_state": None,
                    "effective_state": "outside_term",
                    "source": "none",
                    "date_eligible": False,
                    "reason": "学期外",
                    "reason_code": "OUTSIDE_TERM",
                }
            )
        else:
            mapping = day_rows[term.id]
            row = mapping.get(current)
            if row is None:
                # Missing persisted row is data incompleteness, never a guess.
                raise CalendarDataError("calendar snapshot missing date")
            week_number, week_start, weekday = cal.week_info(
                term.start_date, current
            )
            if row.override_state is not None:
                source = "admin_exception"
                reason = row.override_reason
                reason_code = "ADMIN_OVERRIDE"
            elif row.base_state == "unknown":
                source = "library_uncovered"
                reason = "该年份日历数据未就绪"
                reason_code = "YEAR_NOT_COVERED"
            else:
                source = "library_default"
                reason = None
                reason_code = "LIBRARY_DEFAULT"

            items.append(
                {
                    "date": current.isoformat(),
                    "term_id": term.id,
                    "term_version": term.version,
                    "calendar_revision_id": term.current_calendar_revision_id,
                    "week_number": week_number,
                    "week_start": week_start.isoformat(),
                    "weekday": weekday,
                    "base_state": row.base_state,
                    "override_state": row.override_state,
                    "effective_state": row.effective_state,
                    "source": source,
                    "date_eligible": row.effective_state == "teaching",
                    "reason": reason,
                    "reason_code": reason_code,
                }
            )
        current += timedelta(days=1)

    return items, schedule_version
