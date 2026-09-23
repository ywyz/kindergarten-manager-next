"""Builders: calendar_override, calendar_reimport (pure)."""

from datetime import date

from app.services import calendar_service as cal
from app.services.config_builders_term import (
    _day_payload,
    default_day_payloads,
)
from app.services.config_errors import (
    NoChanges,
    PreviewStale,
    TermNotFound,
    ValidationError,
)
from app.services.config_normalize import normalize_reason, parse_date
from app.services.config_preview import ChangePreview
from app.services.config_state import ReadState


def _term_version(proposal: dict) -> int:
    value = proposal.get("expected_term_version")
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 1
    ):
        raise ValidationError("expected_term_version 非法")
    return value


def _schedule_version(proposal: dict) -> int:
    value = proposal.get("expected_schedule_version")
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 1
    ):
        raise ValidationError("expected_schedule_version 非法")
    return value


def _revision_id(proposal: dict) -> str:
    value = proposal.get("expected_calendar_revision_id")
    if not isinstance(value, str) or not value:
        raise ValidationError("expected_calendar_revision_id 非法")
    return value


def _gate_blockers(school) -> tuple[str, ...]:
    return (
        ("DEPENDENCY_NOT_READY",)
        if school.plans_started_at is not None
        else ()
    )


def _payload_from(row) -> dict:
    return _day_payload(
        row.date,
        row.base_state,
        row.base_library_version,
        row.override_state,
        row.override_reason,
    )


def build_calendar_override(state: ReadState, proposal: dict) -> ChangePreview:
    target_id = proposal.get("target_id")
    if not isinstance(target_id, str) or not target_id:
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

    entries = proposal.get("dates")
    if not isinstance(entries, list) or not entries:
        raise ValidationError("dates 必须是非空数组")
    if len(entries) > 366:
        raise ValidationError("例外批量最多 366 个日期")

    seen: set[date] = set()
    parsed = []
    for item in entries:
        if not isinstance(item, dict):
            raise ValidationError("dates 项必须是对象")
        d = parse_date(item.get("date"))
        if d in seen:
            raise ValidationError(f"日期重复：{d.isoformat()}")
        seen.add(d)
        if d < term.start_date or d > term.end_date:
            raise ValidationError(
                f"日期 {d.isoformat()} 不在学期范围内"
            )
        state_value = item.get("state")
        if state_value is not None and state_value not in (
            "teaching",
            "non_teaching",
        ):
            raise ValidationError(
                "state 只能是 teaching、non_teaching 或 null"
            )
        reason = (
            normalize_reason(item.get("reason"))
            if state_value is not None
            else None
        )
        parsed.append((d, state_value, reason))

    existing = state.day_maps[target_id]
    changes = []
    touched_days = []
    added = 0
    removed = 0
    removed_to_unknown = 0

    for d, state_value, reason in parsed:
        old = existing[d]  # completeness verified at gather time
        new_effective = state_value or old.base_state

        payload = _day_payload(
            d,
            old.base_state,
            old.base_library_version,
            state_value,
            reason,
        )
        week_no, anchor, weekday = cal.week_info(term.start_date, d)
        payload["week_no"] = week_no
        payload["week_label"] = "第%d周" % week_no
        payload["week_anchor"] = anchor.isoformat()
        payload["weekday"] = weekday
        payload["source"] = (
            "admin_exception"
            if state_value is not None
            else "calendar_library"
            if old.base_state != "unknown"
            else "unknown"
        )
        touched_days.append(payload)

        # Compare the FULL state, not only effective_state. This makes a
        # same-as-default explicit exception, a reason-only edit, and a
        # same-effective removal all visible changes.
        if old.override_state != state_value:
            changes.append(
                {
                    "field": "day:%s:override_state" % d.isoformat(),
                    "old": old.override_state,
                    "new": state_value,
                    "week_label": payload["week_label"],
                    "source": payload["source"],
                }
            )
        if old.override_reason != reason:
            changes.append(
                {
                    "field": "day:%s:override_reason" % d.isoformat(),
                    "old": old.override_reason,
                    "new": reason,
                    "week_label": payload["week_label"],
                    "source": payload["source"],
                }
            )
        if old.effective_state != new_effective:
            changes.append(
                {
                    "field": "day:%s:effective_state" % d.isoformat(),
                    "old": old.effective_state,
                    "new": new_effective,
                    "week_label": payload["week_label"],
                    "source": payload["source"],
                }
            )

        if state_value is not None and old.override_state is None:
            added += 1
        if state_value is None and old.override_state is not None:
            removed += 1
            if old.base_state == "unknown":
                removed_to_unknown += 1

    if not changes:
        raise NoChanges()

    candidate_dates = []
    for d, state_value, reason in parsed:
        entry = {"date": d.isoformat(), "state": state_value}
        if reason is not None:
            entry["reason"] = reason
        candidate_dates.append(entry)

    # Merge the touched entries into a FULL, continuous candidate: every
    # non-touched day is copied unchanged from the current revision, so the
    # new revision never loses dates when the pointer switches.
    touched_by_date = {p["date"]: p for p in touched_days}
    full_days = []
    for d in cal.iter_dates(term.start_date, term.end_date):
        iso = d.isoformat()
        full_days.append(touched_by_date.get(iso) or _payload_from(existing[d]))

    return ChangePreview(
        kind="calendar_override",
        target_id=target_id,
        proposal={
            "dates": candidate_dates,
            "touched_days": touched_days,
            "full_days": full_days,
        },
        base_versions={
            "version": term.version,
            "schedule_version": school.schedule_version,
            "plans_started": school.plans_started_at is not None,
            "calendar_revision_id": term.current_calendar_revision_id,
        },
        changes=tuple(changes),
        impact={
            "override_added": added,
            "override_removed": removed,
            "removed_to_unknown": removed_to_unknown,
            "plan_impact_status": (
                "started"
                if school.plans_started_at is not None
                else "not_applicable_before_first_plan"
            ),
        },
        blockers=_gate_blockers(school),
    )
