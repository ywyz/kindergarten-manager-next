"""Builder: calendar_reimport (pure; defaults rebuilt outside tx)."""

from datetime import date

from app.services import calendar_service as cal
from app.services.config_builders_calendar import (
    _gate_blockers,
    _revision_id,
    _schedule_version,
    _term_version,
)
from app.services.config_builders_term import (
    _day_payload,
    default_day_payloads,
)
from app.services.config_errors import NoChanges, PreviewStale, TermNotFound
from app.services.config_preview import ChangePreview
from app.services.config_state import ReadState


def build_calendar_reimport(state: ReadState, proposal: dict) -> ChangePreview:
    target_id = proposal.get("target_id")
    if not isinstance(target_id, str) or not target_id:
        from app.services.config_errors import ValidationError

        raise ValidationError("target_id 非法")
    ev = _term_version(proposal)
    er = _revision_id(proposal)
    es = _schedule_version(proposal)

    term = state.terms_by_id.get(target_id)
    if term is None:
        raise TermNotFound()
    school = state.school
    if ev != term.version:
        raise PreviewStale()
    if er != term.current_calendar_revision_id:
        raise PreviewStale()
    if es != school.schedule_version:
        raise PreviewStale()

    start, end = term.start_date, term.end_date
    existing = state.day_maps[target_id]

    # Recompute every default from the current library (outside tx).
    new_defaults, _unknown = default_day_payloads(start, end)
    new_by_date = new_defaults

    changes = []
    full_days = []
    unknown_resolved = 0
    masked_default_changes = 0
    changed_days = 0

    for default in new_by_date:
        d = date.fromisoformat(default["date"])
        old = existing[d]  # completeness verified at gather time
        payload = _day_payload(
            d,
            default["base_state"],
            default["base_library_version"],
            old.override_state,
            old.override_reason,
        )
        week_no, anchor, weekday = cal.week_info(term.start_date, d)
        payload["week_no"] = week_no
        payload["week_label"] = "第%d周" % week_no
        payload["week_anchor"] = anchor.isoformat()
        payload["weekday"] = weekday
        payload["source"] = (
            "admin_exception"
            if old.override_state is not None
            else "calendar_library"
            if payload["base_state"] != "unknown"
            else "unknown"
        )
        full_days.append(payload)

        day_has_change = False
        base_state_changed = False
        # Base/default changes are reported even when an exception hides
        # them from the effective state.
        if old.base_state != payload["base_state"]:
            changes.append(
                {
                    "field": "day:%s:base_state" % d.isoformat(),
                    "old": old.base_state,
                    "new": payload["base_state"],
                    "week_label": payload["week_label"],
                    "source": payload["source"],
                    "masked_by_exception": old.override_state is not None,
                }
            )
            day_has_change = True
            base_state_changed = True
            if old.override_state is not None:
                masked_default_changes += 1
        if old.base_library_version != payload["base_library_version"]:
            changes.append(
                {
                    "field": "day:%s:base_library_version" % d.isoformat(),
                    "old": old.base_library_version,
                    "new": payload["base_library_version"],
                    "week_label": payload["week_label"],
                    "source": payload["source"],
                    "masked_by_exception": old.override_state is not None,
                }
            )
        if old.effective_state != payload["effective_state"]:
            changes.append(
                {
                    "field": "day:%s:effective_state" % d.isoformat(),
                    "old": old.effective_state,
                    "new": payload["effective_state"],
                    "week_label": payload["week_label"],
                    "source": payload["source"],
                    "masked_by_exception": False,
                }
            )
            day_has_change = True
        if day_has_change:
            changed_days += 1

        if old.base_state == "unknown" and payload["base_state"] != "unknown":
            unknown_resolved += 1

    if not changes:
        raise NoChanges()

    library_version = cal.library_version()
    return ChangePreview(
        kind="calendar_reimport",
        target_id=target_id,
        proposal={"library_version": library_version, "days": full_days},
        base_versions={
            "version": term.version,
            "schedule_version": school.schedule_version,
            "plans_started": school.plans_started_at is not None,
            "calendar_revision_id": term.current_calendar_revision_id,
        },
        changes=tuple(changes),
        impact={
            "unknown_resolved": unknown_resolved,
            "changed_day_count": changed_days,
            "masked_default_changes": masked_default_changes,
            "diff_entry_count": len(changes),
            "new_library_version": library_version,
            "plan_impact_status": (
                "started"
                if school.plans_started_at is not None
                else "not_applicable_before_first_plan"
            ),
        },
        blockers=_gate_blockers(school),
    )
