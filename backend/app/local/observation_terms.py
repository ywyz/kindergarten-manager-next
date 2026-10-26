"""Pure date/term attribution rules for game observations (E04).

This module never writes configuration or observation rows.  It resolves a
new record's term, or returns an explicit decision requirement for an existing
record.  Term snapshots are read from ``local_terms`` (or a trusted stored
history payload), never from page-supplied snapshot data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.local.models import LocalTerm
from app.local.observation_validation import (
    ObservationValidationError,
    normalize_term_snapshot,
)


@dataclass(frozen=True)
class TermSnapshot:
    term_id: str
    name: str
    start_date: str
    end_date: str

    def as_json(self) -> dict[str, str]:
        return {
            "term_id": self.term_id,
            "name": self.name,
            "start_date": self.start_date,
            "end_date": self.end_date,
        }


_UNSET = object()


@dataclass(frozen=True)
class TermResolution:
    status: str
    term_id: str | None
    snapshot: TermSnapshot | None
    options: tuple[TermSnapshot, ...] = ()
    requires_decision: bool = False
    cancelled: bool = False
    unchanged: bool = False
    warnings: tuple[str, ...] = ()


def _as_date(value: Any, field: str = "date") -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            raise ObservationValidationError(
                f"{field} 必须是有效的 ISO 日期", field=field
            ) from None
    raise ObservationValidationError(f"{field} 必须是日期或空", field=field)


def snapshot_from_term(term: LocalTerm) -> TermSnapshot:
    return TermSnapshot(
        term_id=term.id,
        name=term.name,
        start_date=term.start_date.isoformat(),
        end_date=term.end_date.isoformat(),
    )


def snapshot_from_history(payload: dict[str, Any]) -> TermSnapshot | None:
    value = payload.get("term_snapshot")
    if value is None:
        return None
    try:
        normalized = normalize_term_snapshot(value)
    except ObservationValidationError:
        raise
    if normalized is None:
        return None
    term_id = payload.get("term_id")
    if term_id is not None and term_id != normalized["term_id"]:
        raise ObservationValidationError(
            "历史 payload 的 term_id 与 term_snapshot 不一致", field="term_id"
        )
    return TermSnapshot(**normalized)


def _terms(session: Session) -> list[LocalTerm]:
    return list(session.scalars(select(LocalTerm).order_by(LocalTerm.start_date, LocalTerm.id)).all())


def terms_for_date(session: Session, day: Any) -> tuple[TermSnapshot, ...]:
    target = _as_date(day)
    if target is None:
        return ()
    return tuple(
        snapshot_from_term(term)
        for term in _terms(session)
        if term.start_date <= target <= term.end_date
    )


def get_term_snapshot(session: Session, term_id: Any) -> TermSnapshot:
    if not isinstance(term_id, str) or not term_id:
        raise ObservationValidationError("term_id 必须是非空字符串", field="term_id")
    term = session.get(LocalTerm, term_id)
    if term is None:
        from app.local.errors import LocalTermNotFound

        raise LocalTermNotFound()
    return snapshot_from_term(term)


def _unique_options(options: list[TermSnapshot]) -> tuple[TermSnapshot, ...]:
    seen: set[str] = set()
    result: list[TermSnapshot] = []
    for option in options:
        if option.term_id not in seen:
            seen.add(option.term_id)
            result.append(option)
    return tuple(result)


def resolve_new(
    session: Session,
    *,
    observation_date: Any = _UNSET,
    clock: Any = None,
) -> TermResolution:
    """New record: omitted date means today; explicit ``None`` means no date.

    The sentinel distinction is load-bearing: the UI's "no date" state must not
    silently become today's date, while a new record with no field supplied
    still defaults to today per C18/C25.
    """
    if observation_date is _UNSET:
        today = clock() if callable(clock) else (clock or date.today())
        target = _as_date(today, "clock")
    elif observation_date is None:
        return TermResolution(
            status="unassigned",
            term_id=None,
            snapshot=None,
            options=(),
        )
    else:
        target = _as_date(observation_date)
    options = terms_for_date(session, target)
    if len(options) == 1:
        return TermResolution(
            status="assigned",
            term_id=options[0].term_id,
            snapshot=options[0],
            options=options,
        )
    if len(options) > 1:
        return TermResolution(
            status="selection_required",
            term_id=None,
            snapshot=None,
            options=options,
            requires_decision=True,
            warnings=("multiple_terms_match",),
        )
    return TermResolution(
        status="unassigned",
        term_id=None,
        snapshot=None,
        options=(),
    )


def _current_snapshot(
    session: Session,
    current_term_id: str | None,
    supplied: Any = None,
    *,
    require_supplied: bool = False,
) -> TermSnapshot | None:
    """Resolve the trusted current snapshot.

    For an existing record the caller must pass the stored draft snapshot.  A
    missing snapshot is not silently replaced by today's term configuration;
    ``require_supplied`` makes that explicit.  A supplied snapshot must have the
    same term_id as the stored term, but its name/dates are preserved even if
    the term was later renamed or its range changed.
    """
    if current_term_id is None:
        return None
    term = session.get(LocalTerm, current_term_id)
    if term is None:
        return None
    actual = snapshot_from_term(term)
    if supplied is not None:
        normalized = normalize_term_snapshot(supplied)
        if normalized is None or normalized["term_id"] != actual.term_id:
            raise ObservationValidationError(
                "term_snapshot 与当前学期不一致", field="term_snapshot"
            )
        return TermSnapshot(**normalized)
    if require_supplied:
        return None
    return actual


def resolve_edit(
    session: Session,
    *,
    current_term_id: str | None,
    new_date: Any,
    previous_date: Any = None,
    current_snapshot: Any = None,
    decision: str | None = None,
    selected_term_id: str | None = None,
    history_snapshot: Any = None,
) -> TermResolution:
    """Resolve an existing record's date/term change without writing anything.

    ``decision`` is ``keep_current``, ``assign_selected``, ``unassigned``,
    ``keep_history`` or ``cancel``.  With no decision, the function either
    keeps a still-valid current attribution or returns an explicit choice
    requirement; it never silently migrates a term.
    """
    target = _as_date(new_date, "observation_date")
    previous = _as_date(previous_date, "previous_date")
    current = _current_snapshot(
        session, current_term_id, current_snapshot, require_supplied=True
    )
    matches = terms_for_date(session, target)

    if decision == "cancel":
        return TermResolution(
            status="cancelled",
            term_id=current_term_id,
            snapshot=current,
            options=matches,
            cancelled=True,
            unchanged=True,
        )

    if decision == "keep_history":
        history = snapshot_from_history({"term_snapshot": history_snapshot})
        if history is None:
            return TermResolution(
                status="selection_required",
                term_id=None,
                snapshot=None,
                options=matches,
                requires_decision=True,
                warnings=("history_term_missing",),
            )
        if session.get(LocalTerm, history.term_id) is None:
            return TermResolution(
                status="selection_required",
                term_id=None,
                snapshot=None,
                options=matches,
                requires_decision=True,
                warnings=("history_term_missing",),
            )
        return TermResolution(
            status="assigned",
            term_id=history.term_id,
            snapshot=history,
            options=matches,
        )

    if decision == "assign_selected":
        selected = get_term_snapshot(session, selected_term_id)
        warnings: list[str] = []
        if target is not None:
            start = date.fromisoformat(selected.start_date)
            end = date.fromisoformat(selected.end_date)
            if not (start <= target <= end):
                warnings.append("date_outside_selected_term")
        return TermResolution(
            status="assigned",
            term_id=selected.term_id,
            snapshot=selected,
            options=matches,
            warnings=tuple(warnings),
        )

    if decision == "unassigned":
        return TermResolution(
            status="unassigned",
            term_id=None,
            snapshot=None,
            options=matches,
        )

    if decision == "keep_current":
        if current_term_id is None:
            return TermResolution(
                status="unassigned",
                term_id=None,
                snapshot=None,
                options=matches,
            )
        if current is None:
            return TermResolution(
                status="selection_required",
                term_id=None,
                snapshot=None,
                options=matches,
                requires_decision=True,
                warnings=("current_term_missing",),
            )
        warnings = []
        if target is not None:
            start = date.fromisoformat(current.start_date)
            end = date.fromisoformat(current.end_date)
            if not (start <= target <= end):
                warnings.append("date_outside_current_term")
        return TermResolution(
            status="keep_current",
            term_id=current.term_id,
            snapshot=current,
            options=matches,
            unchanged=previous == target,
            warnings=tuple(warnings),
        )

    if decision is not None:
        raise ObservationValidationError(
            "不支持的 term decision", field="term_decision"
        )

    # A normal edit that did not change the date must not re-open attribution:
    # an explicit keep-current choice outside the current range, or a term added
    # later that happens to match an unchanged date, must not create a new
    # confirmation loop or rewrite the stored snapshot.
    if previous == target:
        if current_term_id is None:
            return TermResolution(
                status="unassigned",
                term_id=None,
                snapshot=None,
                options=matches,
                unchanged=True,
            )
        if current is None:
            return TermResolution(
                status="selection_required",
                term_id=None,
                snapshot=None,
                options=matches,
                requires_decision=True,
                warnings=("current_snapshot_missing",),
            )
        return TermResolution(
            status="keep_current",
            term_id=current.term_id,
            snapshot=current,
            options=matches,
            unchanged=True,
        )

    # No explicit decision: preserve existing attribution by default.
    if current_term_id is not None:
        if current is None:
            return TermResolution(
                status="selection_required",
                term_id=None,
                snapshot=None,
                options=matches,
                requires_decision=True,
                warnings=("current_term_missing",),
            )
        start = date.fromisoformat(current.start_date)
        end = date.fromisoformat(current.end_date)
        if target is None or start <= target <= end:
            return TermResolution(
                status="keep_current",
                term_id=current.term_id,
                snapshot=current,
                options=matches,
                unchanged=previous == target,
            )
        options = _unique_options([current, *matches])
        return TermResolution(
            status="selection_required",
            term_id=None,
            snapshot=None,
            options=options,
            requires_decision=True,
            warnings=("cross_term_change",),
        )

    # Current attribution is unassigned.  A matching term is only a suggestion;
    # changing to it requires an explicit decision.
    if matches:
        options = _unique_options([*matches])
        return TermResolution(
            status="selection_required",
            term_id=None,
            snapshot=None,
            options=options,
            requires_decision=True,
            warnings=("assign_available_term",),
        )
    return TermResolution(
        status="unassigned",
        term_id=None,
        snapshot=None,
        options=(),
        unchanged=previous == target,
    )


def apply_term_resolution(
    payload: dict[str, Any], resolution: TermResolution
) -> dict[str, Any]:
    """Return a copy with the resolved term fields; never mutates the input."""
    if resolution.requires_decision or resolution.cancelled:
        return dict(payload)
    updated = dict(payload)
    updated["term_id"] = resolution.term_id
    updated["term_snapshot"] = (
        resolution.snapshot.as_json() if resolution.snapshot is not None else None
    )
    return updated


__all__ = [
    "TermSnapshot",
    "TermResolution",
    "snapshot_from_term",
    "snapshot_from_history",
    "terms_for_date",
    "get_term_snapshot",
    "resolve_new",
    "resolve_edit",
    "apply_term_resolution",
]
