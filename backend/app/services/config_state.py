"""Request-local read state for I2 configuration builders.

Every :class:`ReadState` is created inside one request and passed explicitly;
nothing is shared across requests/threads.
"""

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import security
from app.models import (
    CalendarDay,
    Class,
    SchoolSettings,
    TeacherAssignment,
    Term,
)
from app.services.config_errors import (
    CalendarError,
    ConfigServiceError,
    TermNotFound,
)


_VALID_STATES = {"teaching", "non_teaching", "unknown"}


def _verify_revision_complete(term, rows) -> None:
    start, end = term.start_date, term.end_date
    expected_count = (end - start).days + 1
    by_date = {r.date: r for r in rows}
    if len(rows) != expected_count or len(by_date) != expected_count:
        raise CalendarError("calendar snapshot incomplete")
    current = start
    while current <= end:
        row = by_date.get(current)
        if row is None:
            raise CalendarError("calendar snapshot has a date gap")
        if row.base_state not in _VALID_STATES:
            raise CalendarError("calendar snapshot has an invalid base state")
        if row.override_state not in (None, "teaching", "non_teaching"):
            raise CalendarError("calendar snapshot has an invalid override")
        expected_effective = row.override_state or row.base_state
        if row.effective_state != expected_effective:
            raise CalendarError("calendar snapshot effective state mismatch")
        current += timedelta(days=1)


@dataclass(frozen=True, slots=True)
class ReadState:
    school: SchoolSettings
    classes_by_id: dict[str, Class]
    classes_by_name: dict[str, Class]
    terms_by_id: dict[str, Term]
    # term id -> {date -> CalendarDay} (already resolved at gather time).
    day_maps: dict[str, dict[date, CalendarDay]]
    all_members: tuple[str, ...]
    class_members: dict[str, tuple[str, ...]]
    new_class_id: str
    new_term_id: str


def gather_read_state(
    db: Session, kind: str, proposal: dict
) -> ReadState:
    """Read phase: snapshot reads only. Authentication already enforced."""
    school = db.scalar(
        select(SchoolSettings).where(SchoolSettings.id == "singleton")
    )
    if school is None:
        raise ConfigServiceError("school settings missing")

    class_rows = db.scalars(select(Class)).all()
    classes_by_id = {c.id: c for c in class_rows}
    classes_by_name = {c.name: c for c in class_rows}

    term_rows = db.scalars(select(Term)).all()
    terms_by_id = {t.id: t for t in term_rows}

    target_id = proposal.get("target_id")
    day_maps: dict[str, dict[date, CalendarDay]] = {}
    if kind in ("term_update", "calendar_override", "calendar_reimport"):
        term = terms_by_id.get(target_id) if target_id else None
        if term is None:
            raise TermNotFound()
        revision_id = term.current_calendar_revision_id
        if revision_id is None:
            # A committed term always has a pointer; a null pointer means the
            # service is not ready.
            raise CalendarError("term has no current calendar revision")
        rows = db.scalars(
            select(CalendarDay).where(CalendarDay.revision_id == revision_id)
        ).all()
        # The current revision must cover the whole term range completely,
        # continuously, and every row must be self-consistent. A missing day
        # is data corruption -> 503, never silently patched.
        _verify_revision_complete(term, rows)
        day_maps[term.id] = {r.date: r for r in rows}

    all_member_rows = db.scalars(
        select(TeacherAssignment.teacher_id)
    ).all()
    all_members = tuple(sorted(all_member_rows))

    class_members: dict[str, tuple[str, ...]] = {}
    if kind == "class_update":
        rows = db.scalars(
            select(TeacherAssignment.teacher_id).where(
                TeacherAssignment.class_id == target_id
            )
        ).all()
        class_members[target_id] = tuple(sorted(rows))

    return ReadState(
        school=school,
        classes_by_id=classes_by_id,
        classes_by_name=classes_by_name,
        terms_by_id=terms_by_id,
        day_maps=day_maps,
        all_members=all_members,
        class_members=class_members,
        new_class_id=security.generate_id(),
        new_term_id=security.generate_id(),
    )
