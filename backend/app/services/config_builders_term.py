"""Builders: term_create, term_update (pure; calendar built outside tx)."""

from datetime import date

from app.services import calendar_service as cal
from app.services.config_errors import (
    CalendarError,
    NoChanges,
    PreviewStale,
    TermOverlap,
    ValidationError,
)
from app.services.config_normalize import (
    normalize_term_name,
    parse_date,
)
from app.services.config_preview import ChangePreview
from app.services.config_state import ReadState


def _schedule_version(proposal: dict) -> int:
    value = proposal.get("expected_schedule_version")
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 1
    ):
        raise ValidationError("expected_schedule_version 非法")
    return value


def _version(proposal: dict) -> int:
    value = proposal.get("expected_version")
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 1
    ):
        raise ValidationError("expected_version 非法")
    return value


def _overlaps(start, end, terms, *, exclude_id) -> bool:
    for candidate in terms:
        if exclude_id is not None and candidate.id == exclude_id:
            continue
        if cal.ranges_overlap(
            start, end, candidate.start_date, candidate.end_date
        ):
            return True
    return False


def _day_payload(
    d: date,
    base_state: str,
    base_version: str,
    override_state=None,
    override_reason=None,
) -> dict:
    return {
        "date": d.isoformat(),
        "base_state": base_state,
        "base_library_version": base_version,
        "override_state": override_state,
        "override_reason": override_reason,
        "effective_state": override_state or base_state,
    }


def default_day_payloads(start: date, end: date):
    """Full-range default payloads via the library (outside tx)."""
    payloads = []
    unknown_count = 0
    for d in cal.iter_dates(start, end):
        state, version = cal.default_state(d)
        if state == "unknown":
            unknown_count += 1
        payloads.append(_day_payload(d, state, version))
    return payloads, unknown_count


def build_term_create(state: ReadState, proposal: dict) -> ChangePreview:
    name = normalize_term_name(proposal.get("name"))
    start = parse_date(proposal.get("start_date"))
    end = parse_date(proposal.get("end_date"))
    expected_schedule = _schedule_version(proposal)

    school = state.school
    if expected_schedule != school.schedule_version:
        raise PreviewStale()
    try:
        day_count = cal.validate_range(start, end, max_days=2000)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc

    if _overlaps(start, end, state.terms_by_id.values(), exclude_id=None):
        raise TermOverlap()

    try:
        days, unknown_count = default_day_payloads(start, end)
    except cal.CalendarLibraryError as exc:
        raise CalendarError(str(exc)) from exc

    return ChangePreview(
        kind="term_create",
        target_id=state.new_term_id,
        proposal={
            "name": name,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "days": days,
        },
        base_versions={
            "schedule_version": school.schedule_version,
            "plans_started": school.plans_started_at is not None,
        },
        changes=(
            {"field": "name", "old": None, "new": name},
            {"field": "start_date", "old": None, "new": start.isoformat()},
            {"field": "end_date", "old": None, "new": end.isoformat()},
        ),
        impact={
            "day_count": day_count,
            "unknown_day_count": unknown_count,
            "plan_impact_status": (
                "started"
                if school.plans_started_at is not None
                else "not_applicable_before_first_plan"
            ),
        },
        blockers=(),
    )
