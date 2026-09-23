"""Builder: term_update (pure; new revision days built outside tx)."""

from datetime import date

from app.services import calendar_service as cal
from app.services.config_builders_term import (
    _day_payload,
    _overlaps,
    _schedule_version,
    _version,
)
from app.services.config_errors import (
    NoChanges,
    PreviewStale,
    TermOverlap,
    ValidationError,
)
from app.services.config_normalize import normalize_term_name, parse_date
from app.services.config_preview import ChangePreview
from app.services.config_state import ReadState


def _updated_day_payloads(new_start, new_end, existing):
    """In-range days copied as saved; genuinely new dates via library."""
    payloads = []
    for d in cal.iter_dates(new_start, new_end):
        old = existing.get(d)
        if old is not None:
            payloads.append(
                _day_payload(
                    d,
                    old.base_state,
                    old.base_library_version,
                    old.override_state,
                    old.override_reason,
                )
            )
        else:
            state, version = cal.default_state(d)
            payloads.append(_day_payload(d, state, version))
    return payloads


def build_term_update(state: ReadState, proposal: dict) -> ChangePreview:
    target_id = proposal.get("target_id")
    if not isinstance(target_id, str) or not target_id:
        raise ValidationError("target_id 非法")
    expected_version = _version(proposal)
    expected_schedule = _schedule_version(proposal)

    term = state.terms_by_id.get(target_id)
    if term is None:
        from app.services.config_errors import TermNotFound

        raise TermNotFound()
    school = state.school
    if expected_version != term.version:
        raise PreviewStale()
    if expected_schedule != school.schedule_version:
        raise PreviewStale()

    new_name = term.name
    new_start = term.start_date
    new_end = term.end_date
    if "name" in proposal:
        new_name = normalize_term_name(proposal["name"])
    if "start_date" in proposal:
        new_start = parse_date(proposal["start_date"])
    if "end_date" in proposal:
        new_end = parse_date(proposal["end_date"])

    try:
        cal.validate_range(new_start, new_end, max_days=2000)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    if _overlaps(
        new_start, new_end, state.terms_by_id.values(), exclude_id=target_id
    ):
        raise TermOverlap()

    changes = []
    if new_name != term.name:
        changes.append(
            {"field": "name", "old": term.name, "new": new_name}
        )
    if new_start != term.start_date:
        changes.append(
            {
                "field": "start_date",
                "old": term.start_date.isoformat(),
                "new": new_start.isoformat(),
            }
        )
    if new_end != term.end_date:
        changes.append(
            {
                "field": "end_date",
                "old": term.end_date.isoformat(),
                "new": new_end.isoformat(),
            }
        )

    range_changed = new_start != term.start_date or new_end != term.end_date
    existing = state.day_maps[target_id]
    day_payloads = []
    unknown_day_count = 0
    removed_override_dates = []
    week_shift_count = 0

    if range_changed:
        day_payloads = _updated_day_payloads(new_start, new_end, existing)
        for payload in day_payloads:
            d = date.fromisoformat(payload["date"])
            old_row = existing.get(d)
            old_effective = (
                old_row.effective_state if old_row is not None else None
            )
            if old_effective != payload["effective_state"]:
                week_no, anchor, weekday = cal.week_info(new_start, d)
                payload["week_no"] = week_no
                payload["week_label"] = "第%d周" % week_no
                payload["week_anchor"] = anchor.isoformat()
                payload["weekday"] = weekday
                payload["source"] = (
                    "admin_exception"
                    if payload["override_state"] is not None
                    else "calendar_library"
                    if payload["base_state"] != "unknown"
                    else "unknown"
                )
                changes.append(
                    {
                        "field": "day:" + payload["date"],
                        "old": old_effective,
                        "new": payload["effective_state"],
                        "week_label": payload["week_label"],
                        "source": payload["source"],
                    }
                )
            if payload["base_state"] == "unknown":
                unknown_day_count += 1

        for d in cal.iter_dates(term.start_date, term.end_date):
            if d < new_start or d > new_end:
                old_row = existing.get(d)
                if old_row is not None and old_row.override_state is not None:
                    removed_override_dates.append(d.isoformat())

        if new_start != term.start_date:
            for d in cal.iter_dates(new_start, new_end):
                old_week, _, _ = cal.week_info(term.start_date, d)
                new_week, _, _ = cal.week_info(new_start, d)
                if old_week != new_week:
                    week_shift_count += 1

    if not changes:
        raise NoChanges()

    gate = (
        "started"
        if school.plans_started_at is not None
        else "not_applicable_before_first_plan"
    )
    blockers = (
        ("DEPENDENCY_NOT_READY",)
        if school.plans_started_at is not None
        else ()
    )
    return ChangePreview(
        kind="term_update",
        target_id=target_id,
        proposal={
            "name": new_name,
            "start_date": new_start.isoformat(),
            "end_date": new_end.isoformat(),
            "range_changed": range_changed,
            "days": day_payloads,
        },
        base_versions={
            "version": term.version,
            "schedule_version": school.schedule_version,
            "plans_started": school.plans_started_at is not None,
            "calendar_revision_id": term.current_calendar_revision_id,
        },
        changes=tuple(changes),
        impact={
            "day_count": (new_end - new_start).days + 1,
            "unknown_day_count": unknown_day_count,
            "removed_override_dates": removed_override_dates,
            "week_shift_count": week_shift_count,
            "plan_impact_status": gate,
        },
        blockers=blockers,
    )
