"""Term/calendar effects for I2 configuration (locked transaction).

Guarantees:
* Every term/calendar change increments term.version BEFORE the revision is
  built, so revision.term_version matches the term's new version.
* Every successful term/calendar change increments schedule_version (even a
  name-only term update), keeping baseline invalidation correct.
* Every new revision stores a FULL, continuous, validated day set. Overrides
  merge touched days over the previous complete snapshot; untouched days are
  preserved, never dropped when the pointer switches.
"""

from datetime import date, datetime

from sqlalchemy import func, select

from app import security
from app.models import CalendarDay, CalendarRevision, Term
from app.services import calendar_service as cal
from app.services.config_calendar_validate import (
    CandidateInvalid,
    validate_full_days,
)
from app.services.config_preview import ChangePreview


def _result(school, term, revision_id) -> dict:
    return {
        "school_version": school.version,
        "schedule_version": school.schedule_version,
        "class_id": None,
        "class_version": None,
        "term_id": term.id,
        "term_version": term.version,
        "calendar_revision_id": revision_id,
    }


def create_term(db, preview, school, *, now, operator_id, change_id):
    p = preview.proposal
    term = Term(
        id=preview.target_id,
        name=p["name"],
        start_date=date.fromisoformat(p["start_date"]),
        end_date=date.fromisoformat(p["end_date"]),
        version=1,
        current_calendar_revision_id=None,
        created_at=now,
        updated_at=now,
    )
    # Validate the full default calendar before writing anything.
    validate_full_days(term, p["days"])

    db.add(term)
    db.flush()

    revision = CalendarRevision(
        id=security.generate_id(),
        term_id=term.id,
        revision_no=1,
        term_version=1,
        start_date=term.start_date,
        end_date=term.end_date,
        library_version=_library_version(p["days"]),
        created_by=operator_id,
        created_at=now,
    )
    db.add(revision)
    db.flush()
    _insert_days(db, revision.id, p["days"])
    term.current_calendar_revision_id = revision.id
    school.schedule_version += 1
    return _result(school, term, revision.id)


def update_term(db, preview, school, *, now, operator_id, change_id):
    p = preview.proposal
    term = _locked_term(db, preview.target_id)

    # Version increments before the revision so term_version matches.
    term.version += 1
    term.name = p["name"]
    term.start_date = date.fromisoformat(p["start_date"])
    term.end_date = date.fromisoformat(p["end_date"])
    term.updated_at = now

    revision_id = term.current_calendar_revision_id
    if p.get("range_changed"):
        # Validate the full candidate for the new range before revision.
        candidate_term = _CandidateTermView(term)
        validate_full_days(candidate_term, p["days"])

        revision = _new_revision(db, term, preview, now, operator_id,
                                 library_version=_library_version(p["days"]))
        _insert_days(db, revision.id, p["days"])
        revision_id = revision.id
        term.current_calendar_revision_id = revision_id

    # A name-only change still advances the schedule sequence.
    school.schedule_version += 1

    return _result(school, term, revision_id)


def new_calendar_revision(db, preview, school, *, now, operator_id, change_id):
    term = _locked_term(db, preview.target_id)

    # Pick the full candidate payload already built outside the transaction.
    if preview.kind == "calendar_override":
        full_days = preview.proposal["full_days"]
    else:  # reimport
        full_days = preview.proposal["days"]

    # Full, continuous server-side validation before any row is written.
    validate_full_days(_CandidateTermView(term), full_days)

    # Increment term.version first, so the revision records the new version.
    term.version += 1
    term.updated_at = now

    revision = _new_revision(
        db, term, preview, now, operator_id,
        library_version=_library_version(full_days),
    )
    # Write the FULL merged range (not only touched days). Untouched dates
    # are preserved in full_days from the previous revision.
    _insert_days(db, revision.id, full_days)

    term.current_calendar_revision_id = revision.id
    school.schedule_version += 1
    return _result(school, term, revision.id)


class _CandidateTermView:
    """Validation view reflecting possibly-updated term range/version."""

    def __init__(self, term):
        self.start_date = term.start_date
        self.end_date = term.end_date
        self.version = term.version


def _locked_term(db, term_id):
    return db.execute(
        select(Term).where(Term.id == term_id).with_for_update()
    ).scalar_one()


def _library_version(full_days) -> str:
    versions = {p.get("base_library_version") for p in full_days}
    versions.discard(None)
    if len(versions) == 1:
        return next(iter(versions))
    if not versions:
        raise CandidateInvalid("calendar candidate library version invalid")
    # Mixed library versions within one revision: keep a deterministic
    # composite label rather than silently dropping one.
    return "mixed:" + "|".join(sorted(versions))[:40]


def _new_revision(db, term, preview, now, operator_id, *, library_version):
    revision_no = db.scalar(
        select(func.coalesce(func.max(CalendarRevision.revision_no), 0)).where(
            CalendarRevision.term_id == term.id
        )
    )
    revision = CalendarRevision(
        id=security.generate_id(),
        term_id=term.id,
        revision_no=int(revision_no) + 1,
        term_version=term.version,
        start_date=term.start_date,
        end_date=term.end_date,
        library_version=library_version,
        created_by=operator_id,
        created_at=now,
    )
    db.add(revision)
    db.flush()
    return revision


def _insert_days(db, revision_id, payloads):
    for payload in payloads:
        db.add(
            CalendarDay(
                date=date.fromisoformat(payload["date"]),
                revision_id=revision_id,
                base_state=payload["base_state"],
                base_library_version=payload["base_library_version"],
                override_state=payload.get("override_state"),
                override_reason=payload.get("override_reason"),
                effective_state=payload["effective_state"],
            )
        )
