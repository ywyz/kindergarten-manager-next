"""Locked verification: FOR UPDATE current reads; never calls the library."""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import TeacherAssignment, Term
from app.services import calendar_service as cal
from app.services.config_errors import (
    ClassNameTaken,
    PreviewStale,
    TermOverlap,
)
from app.services.config_preview import ChangePreview


def verify_candidate(
    db: Session,
    preview: ChangePreview,
    school,
    locked_classes: dict,
    locked_terms: dict,
) -> None:
    base = preview.base_versions
    if base.get("schedule_version") != school.schedule_version:
        raise PreviewStale()
    if base.get("plans_started") != (school.plans_started_at is not None):
        raise PreviewStale()

    kind = preview.kind
    if kind == "school_update":
        if base.get("version") != school.version:
            raise PreviewStale()
        if base.get("member_summary") != _all_assigned(db):
            raise PreviewStale()

    elif kind == "class_create":
        _assert_name_free(db, preview.proposal["name"])

    elif kind == "class_update":
        locked = locked_classes[preview.target_id]
        if base.get("version") != locked.version:
            raise PreviewStale()
        if base.get("member_summary") != _class_assigned(db, locked.id):
            raise PreviewStale()
        if "name" in preview.proposal:
            _assert_name_free(db, preview.proposal["name"])

    elif kind == "term_create":
        _assert_no_overlap(
            db,
            date.fromisoformat(preview.proposal["start_date"]),
            date.fromisoformat(preview.proposal["end_date"]),
            exclude_id=None,
        )

    elif kind == "term_update":
        locked = locked_terms[preview.target_id]
        _verify_term_base(base, locked)
        _assert_no_overlap(
            db,
            date.fromisoformat(preview.proposal["start_date"]),
            date.fromisoformat(preview.proposal["end_date"]),
            exclude_id=locked.id,
        )

    elif kind in ("calendar_override", "calendar_reimport"):
        locked = locked_terms[preview.target_id]
        _verify_term_base(base, locked)


def _verify_term_base(base: dict, term: Term) -> None:
    if base.get("version") != term.version:
        raise PreviewStale()
    if base.get("calendar_revision_id") != term.current_calendar_revision_id:
        raise PreviewStale()


def _assert_name_free(db: Session, name: str) -> None:
    """Current-read name probe; the gap lock blocks a concurrent insert."""
    from app.models import Class

    existing = db.execute(
        select(Class.id).where(Class.name == name).with_for_update()
    ).first()
    if existing is not None:
        raise ClassNameTaken()


def _assert_no_overlap(db, start, end, *, exclude_id) -> None:
    """Current read of all term rows; term writers serialize while held."""
    terms = db.scalars(select(Term).with_for_update()).all()
    for term in terms:
        if exclude_id is not None and term.id == exclude_id:
            continue
        if cal.ranges_overlap(start, end, term.start_date, term.end_date):
            raise TermOverlap()


def _class_assigned(db: Session, class_id: str) -> list[str]:
    rows = db.execute(
        select(TeacherAssignment.teacher_id)
        .where(TeacherAssignment.class_id == class_id)
        .with_for_update()
    ).all()
    return sorted(r[0] for r in rows)


def _all_assigned(db: Session) -> list[str]:
    rows = db.execute(
        select(TeacherAssignment.teacher_id).with_for_update()
    ).all()
    return sorted(r[0] for r in rows)
