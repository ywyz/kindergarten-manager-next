"""Local configuration maintenance: preview, apply and committed receipts.

Implements D1B spec §10.2/§10.3 for the five mutually exclusive change
kinds (profile / current_class / term_create / term_update /
calendar_override):

- preview materializes one short read snapshot, builds the calendar
  candidate and the complete impact facts outside the lock, and signs a
  10-minute ``preview_token`` that binds this launch, the normalized
  change, the configuration version, the candidate digest and the impact
  digest;
- apply first replays a committed receipt for the same request id, then
  rebuilds the candidate from a fresh short read, then re-checks the
  receipt, the configuration version and every preview premise inside
  ``BEGIN IMMEDIATE`` before writing everything in one COMMIT;
- a preview whose premises changed (new/saved plans, another committed
  configuration, moved pointers) is refused as ``CONFIG_PREVIEW_STALE``
  even when the impact shrank;
- ``changed=false`` previews only record an idempotent receipt: no
  configuration version, calendar revision or audit row is created.

Calendar revision rules follow the confirmed I2 contract: the new range
keeps the base values and overrides of its intersection with the current
revision; newly included dates get a fresh library base with no override;
previously removed overrides are never restored; the library is not called
for override-only changes and effective state is always override or base.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from app.ids import new_opaque_id
from app.local import calendar_build, config_tokens
from app.local.base import utc_now
from app.local.errors import (
    LocalCalendarUnavailable,
    LocalConfigOperationNotFound,
    LocalConfigPreviewStale,
    LocalConfigRequestConflict,
    LocalConfigVersionConflict,
    LocalStorageError,
    LocalTermNotFound,
    LocalTermOverlap,
    LocalValidationError,
)
from app.local.models import (
    LocalCalendarDay,
    LocalCalendarRevision,
    LocalClass,
    LocalClassGameHead,
    LocalClassGameRevision,
    LocalConfigOperation,
    LocalDailyPlan,
    LocalOperationRecord,
    LocalProfile,
    LocalSettings,
    LocalTerm,
)
from app.local.normalize import normalize_display_name, normalize_request_id
from app.local.profile_service import _term_revision, require_context
from app.local.tx import begin_immediate, read_scope, rollback
from app.services import calendar_service as cal
from app.services import config_normalize as cfg
from app.services.config_errors import MAX_TERM_DAYS, ValidationError

CHANGE_KINDS = (
    "profile",
    "current_class",
    "term_create",
    "term_update",
    "calendar_override",
    "class_games",
)

_LOCATION_KINDS = ("area", "special_room", "outdoor")
MAX_LOCATIONS_PER_KIND = 30
MAX_GAME_NAME_CHARS = 80
MAX_LOCATION_GUIDANCE_CHARS = 2000
MAX_GAME_TEXT_CHARS = 8000

_REASON_ORDER = (
    "header_retained",
    "date_state_changed",
    "week_changed",
    "outside_new_range",
)


def _digest(value) -> str:
    return config_tokens.digest(value)


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def _normalize_term_id(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 32:
        raise LocalValidationError("term_id 不合法")
    return value


def _normalize_school(value: object) -> str | None:
    try:
        return cfg.normalize_school_name(value)
    except ValidationError as exc:
        raise LocalValidationError(str(exc)) from None


def _normalize_term_fields(base: dict, change: dict) -> dict:
    try:
        name = cfg.normalize_term_name(change.get("name"))
        start = cfg.parse_date(change.get("start_date"))
        end = cfg.parse_date(change.get("end_date"))
    except ValidationError as exc:
        raise LocalValidationError(str(exc)) from None
    if start > end:
        raise LocalValidationError("学期开始日期不能晚于结束日期")
    if (end - start).days + 1 > MAX_TERM_DAYS:
        raise LocalValidationError(f"学期范围不能超过 {MAX_TERM_DAYS} 天")
    base.update(
        {"name": name, "start_date": start.isoformat(), "end_date": end.isoformat()}
    )
    return base


def normalize_change(change: object) -> dict:
    """Validate and normalize one change object (422 on any violation)."""
    if not isinstance(change, dict):
        raise LocalValidationError("change 必须是对象")
    kind = change.get("kind")
    if kind not in CHANGE_KINDS:
        raise LocalValidationError("不支持的配置操作类型")
    if kind == "profile":
        return {
            "kind": "profile",
            "display_name": normalize_display_name(change.get("display_name")),
            "school_name": _normalize_school(change.get("school_name")),
        }
    if kind == "current_class":
        try:
            name = cfg.normalize_class_name(change.get("name"))
            grade = cfg.normalize_grade(change.get("grade"))
        except ValidationError as exc:
            raise LocalValidationError(str(exc)) from None
        return {"kind": "current_class", "name": name, "grade": grade}
    if kind == "term_create":
        return _normalize_term_fields({"kind": "term_create"}, change)
    if kind == "term_update":
        return _normalize_term_fields(
            {
                "kind": "term_update",
                "term_id": _normalize_term_id(change.get("term_id")),
            },
            change,
        )
    if kind == "class_games":
        return _normalize_class_games(change)
    # calendar_override
    state = change.get("state")
    if state not in ("teaching", "non_teaching", None):
        raise LocalValidationError("state 只能是 teaching、non_teaching 或 null")
    reason = change.get("reason")
    if state is None:
        if reason is not None:
            raise LocalValidationError("撤销例外时 reason 必须为 null")
        new_reason = None
    else:
        try:
            new_reason = cfg.normalize_reason(reason)
        except ValidationError as exc:
            raise LocalValidationError(str(exc)) from None
    try:
        target_date = cfg.parse_date(change.get("date"))
    except ValidationError as exc:
        raise LocalValidationError(str(exc)) from None
    return {
        "kind": "calendar_override",
        "term_id": _normalize_term_id(change.get("term_id")),
        "date": target_date.isoformat(),
        "state": state,
        "reason": new_reason,
    }


def _normalize_game_text(value: object, limit: int, label: str) -> str | None:
    """Empty text and null both mean "no text" (deterministic no-op compare)."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise LocalValidationError(f"{label}必须是字符串或 null")
    if value == "":
        return None
    if len(value) > limit:
        raise LocalValidationError(f"{label}不能超过 {limit} 个字符")
    return value


def _normalize_class_games(change: dict) -> dict:
    """The current class is always server-derived; ``class_id`` is refused."""
    extra = set(change) - {"kind", "locations", "game_scope", "guidance"}
    if extra:
        raise LocalValidationError("游戏配置包含未知字段")
    locations = change.get("locations", [])
    if not isinstance(locations, list):
        raise LocalValidationError("locations 必须是列表")
    counts: dict[str, int] = {}
    normalized_locations: list[dict] = []
    for item in locations:
        if not isinstance(item, dict):
            raise LocalValidationError("地点项必须是对象")
        if set(item) - {"kind", "name", "guidance"}:
            raise LocalValidationError("地点项包含未知字段")
        kind = item.get("kind")
        if kind not in _LOCATION_KINDS:
            raise LocalValidationError("地点类型只能是 area、special_room 或 outdoor")
        name = item.get("name")
        if (
            not isinstance(name, str)
            or not (1 <= len(name) <= MAX_GAME_NAME_CHARS)
        ):
            raise LocalValidationError("地点名称长度应为 1–80 个字符")
        guidance = _normalize_game_text(
            item.get("guidance"), MAX_LOCATION_GUIDANCE_CHARS, "地点指导"
        )
        counts[kind] = counts.get(kind, 0) + 1
        if counts[kind] > MAX_LOCATIONS_PER_KIND:
            raise LocalValidationError(
                f"每类地点最多 {MAX_LOCATIONS_PER_KIND} 个"
            )
        normalized_locations.append(
            {"kind": kind, "name": name, "guidance": guidance}
        )
    return {
        "kind": "class_games",
        "locations": normalized_locations,
        "game_scope": _normalize_game_text(
            change.get("game_scope"), MAX_GAME_TEXT_CHARS, "游戏范围"
        ),
        "guidance": _normalize_game_text(
            change.get("guidance"), MAX_GAME_TEXT_CHARS, "通用指导"
        ),
    }


def _game_payload(normalized: dict) -> dict:
    """Build the immutable stored game payload from a normalized change.

    The normalized change is flat (``kind``/``locations``/``game_scope``/
    ``guidance``) so it round-trips through the D1 preview -> apply contract;
    the persisted payload is the same three business fields without ``kind``.
    """
    return {
        "locations": normalized["locations"],
        "game_scope": normalized["game_scope"],
        "guidance": normalized["guidance"],
    }


def change_fingerprint(expected_config_version: int, change: dict) -> str:
    """Input fingerprint: config version + normalized change only."""
    return _digest(
        {"expected_config_version": expected_config_version, "change": change}
    )


# ---------------------------------------------------------------------------
# Snapshots (materialized inside one short read transaction)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TermSnapshot:
    id: str
    name: str
    start_date: date
    end_date: date
    revision_id: str
    revision_no: int
    library_version: str


@dataclass(frozen=True)
class DaySnapshot:
    day: date
    base_state: str
    base_library_version: str
    override_state: str | None
    override_reason: str | None
    effective_state: str


@dataclass(frozen=True)
class PlanSnapshot:
    id: str
    plan_date: date
    term_id: str
    week_number: int
    content_version: int


@dataclass(frozen=True)
class ConfigSnapshot:
    config_version: int
    profile_id: str
    display_name: str
    school_name: str | None
    class_id: str
    class_name: str
    grade: str
    terms: tuple[TermSnapshot, ...]
    target_term: TermSnapshot | None
    # Materialized day maps, keyed by term id, loaded only where the change
    # can need them (every term for profile/class impact, the target term
    # for term_update/calendar_override, none for term_create).
    days_by_term: dict[str, tuple[DaySnapshot, ...]]
    plans: tuple[PlanSnapshot, ...]
    total_plan_count: int
    # Current class game payload, materialized only for a ``class_games``
    # change (None keeps every other change's premise digest unchanged).
    game_payload: dict | None = None


def _term_snapshot(session: Session, term: LocalTerm) -> TermSnapshot:
    revision = _term_revision(session, term)
    return TermSnapshot(
        id=term.id,
        name=term.name,
        start_date=term.start_date,
        end_date=term.end_date,
        revision_id=revision.id,
        revision_no=revision.revision_no,
        library_version=revision.library_version,
    )


def _day_rows(session: Session, revision_id: str) -> tuple[DaySnapshot, ...]:
    rows = session.scalars(
        select(LocalCalendarDay)
        .where(LocalCalendarDay.revision_id == revision_id)
        .order_by(LocalCalendarDay.date)
    ).all()
    return tuple(
        DaySnapshot(
            day=row.date,
            base_state=row.base_state,
            base_library_version=row.base_library_version,
            override_state=row.override_state,
            override_reason=row.override_reason,
            effective_state=row.effective_state,
        )
        for row in rows
    )


def _term_days(session: Session, term: LocalTerm) -> tuple[DaySnapshot, ...]:
    """Load one term's current revision days and verify full coverage.

    A revision that does not exactly cover its term range is corrupt
    storage: preview/apply must refuse it instead of cloning the incomplete
    snapshot into a new revision or silently rebuilding missing days from
    today's calendar library (R9).
    """
    revision = _term_revision(session, term)
    rows = _day_rows(session, revision.id)
    expected = tuple(cal.iter_dates(term.start_date, term.end_date))
    if tuple(row.day for row in rows) != expected:
        raise LocalStorageError("日历修订未完整覆盖学期范围")
    return rows


def _term_update_window(normalized: dict, target: TermSnapshot) -> tuple[date, date]:
    """Envelope of the old and new ranges of a term_update change."""
    return (
        min(target.start_date, date.fromisoformat(normalized["start_date"])),
        max(target.end_date, date.fromisoformat(normalized["end_date"])),
    )


def _plan_window(
    normalized: dict, target: TermSnapshot | None
) -> tuple[date, date] | None:
    """Date window of plans relevant to the impact facts (None = all)."""
    kind = normalized["kind"]
    if kind in ("profile", "current_class", "class_games"):
        return None
    if kind == "term_create":
        return (
            date.fromisoformat(normalized["start_date"]),
            date.fromisoformat(normalized["end_date"]),
        )
    if kind == "term_update":
        assert target is not None
        return _term_update_window(normalized, target)
    # calendar_override
    day = date.fromisoformat(normalized["date"])
    return day, day


def load_snapshot(session: Session, normalized: dict) -> ConfigSnapshot:
    """Materialize the configuration premises (caller holds a read scope)."""
    context = require_context(session, date.today())
    settings = context.settings
    assert settings is not None and context.school_class is not None
    kind = normalized["kind"]
    terms = tuple(_term_snapshot(session, term) for term in context.terms)

    target: TermSnapshot | None = None
    target_row: LocalTerm | None = None
    if kind in ("term_update", "calendar_override"):
        target_row = session.get(LocalTerm, normalized["term_id"])
        if target_row is None:
            raise LocalTermNotFound()
        target = _term_snapshot(session, target_row)

    days_by_term: dict[str, tuple[DaySnapshot, ...]] = {}
    if kind in ("profile", "current_class"):
        for term in context.terms:
            days_by_term[term.id] = _term_days(session, term)
    elif target_row is not None:
        days_by_term[target_row.id] = _term_days(session, target_row)
        if kind == "term_update":
            # The old/new range envelope may contain other terms; their own
            # current revisions are materialized so an intermediate unchanged
            # term is compared against itself (never mistaken for a missing
            # day, never producing a fake diff or impact entry — R8).
            assert target is not None
            window_start, window_end = _term_update_window(normalized, target)
            for term in context.terms:
                if term.id in days_by_term:
                    continue
                if term.end_date >= window_start and term.start_date <= window_end:
                    days_by_term[term.id] = _term_days(session, term)

    window = _plan_window(normalized, target)
    conditions = [
        LocalDailyPlan.class_id == context.school_class.id,
        LocalDailyPlan.deleted_at.is_(None),
    ]
    if window is not None:
        start, end = window
        conditions.append(LocalDailyPlan.plan_date >= start)
        conditions.append(LocalDailyPlan.plan_date <= end)
    rows = session.scalars(
        select(LocalDailyPlan)
        .where(*conditions)
        .order_by(LocalDailyPlan.plan_date, LocalDailyPlan.id)
    ).all()
    plans = tuple(
        PlanSnapshot(
            id=row.id,
            plan_date=row.plan_date,
            term_id=row.term_id,
            week_number=row.week_number,
            content_version=row.current_content_version,
        )
        for row in rows
    )
    total = (
        session.scalar(
            select(func.count())
            .select_from(LocalDailyPlan)
            .where(
                LocalDailyPlan.class_id == context.school_class.id,
                LocalDailyPlan.deleted_at.is_(None),
            )
        )
        or 0
    )
    game_payload: dict | None = None
    if kind == "class_games":
        game_head = session.get(LocalClassGameHead, context.school_class.id)
        if game_head is None:
            raise LocalStorageError("班级游戏配置缺失")
        current_game = session.get(
            LocalClassGameRevision, game_head.current_revision_id
        )
        if current_game is None or current_game.class_id != context.school_class.id:
            raise LocalStorageError("班级游戏配置修订缺失")
        game_payload = dict(current_game.payload_json)
    return ConfigSnapshot(
        config_version=settings.config_version,
        profile_id=context.profile.id,
        display_name=context.profile.display_name,
        school_name=settings.school_name,
        class_id=context.school_class.id,
        class_name=context.school_class.name,
        grade=context.school_class.grade,
        terms=terms,
        target_term=target,
        days_by_term=days_by_term,
        plans=plans,
        total_plan_count=int(total),
        game_payload=game_payload,
    )


# ---------------------------------------------------------------------------
# Change validation against the loaded state
# ---------------------------------------------------------------------------


def validate_against_state(snapshot: ConfigSnapshot, normalized: dict) -> None:
    """Range overlap and override-location rules (422, no writes)."""
    kind = normalized["kind"]
    if kind in ("term_create", "term_update"):
        start = date.fromisoformat(normalized["start_date"])
        end = date.fromisoformat(normalized["end_date"])
        for term in snapshot.terms:
            if kind == "term_update" and term.id == normalized["term_id"]:
                continue
            if cal.ranges_overlap(start, end, term.start_date, term.end_date):
                raise LocalTermOverlap()
    if kind == "calendar_override":
        assert snapshot.target_term is not None
        day = date.fromisoformat(normalized["date"])
        if not (
            snapshot.target_term.start_date
            <= day
            <= snapshot.target_term.end_date
        ):
            raise LocalValidationError("日期必须在该学期当前范围")


def _target_day(snapshot: ConfigSnapshot, normalized: dict) -> DaySnapshot:
    assert snapshot.target_term is not None
    target_date = date.fromisoformat(normalized["date"])
    for row in snapshot.days_by_term.get(snapshot.target_term.id, ()):
        if row.day == target_date:
            return row
    raise LocalStorageError("日历快照缺少目标日期")


def is_changed(snapshot: ConfigSnapshot, normalized: dict) -> bool:
    kind = normalized["kind"]
    if kind == "profile":
        return (
            normalized["display_name"] != snapshot.display_name
            or normalized["school_name"] != snapshot.school_name
        )
    if kind == "current_class":
        return (
            normalized["name"] != snapshot.class_name
            or normalized["grade"] != snapshot.grade
        )
    if kind == "term_create":
        return True
    if kind == "term_update":
        assert snapshot.target_term is not None
        return (
            normalized["name"] != snapshot.target_term.name
            or normalized["start_date"]
            != snapshot.target_term.start_date.isoformat()
            or normalized["end_date"] != snapshot.target_term.end_date.isoformat()
        )
    if kind == "class_games":
        return _digest(_game_payload(normalized)) != _digest(
            snapshot.game_payload
        )
    # calendar_override
    current = _target_day(snapshot, normalized)
    return (current.override_state, current.override_reason) != (
        normalized["state"],
        normalized["reason"],
    )


# ---------------------------------------------------------------------------
# Candidate calendar revision
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CandidateDay:
    day: date
    base_state: str
    base_library_version: str
    override_state: str | None
    override_reason: str | None
    effective_state: str


@dataclass(frozen=True)
class RevisionCandidate:
    revision_no: int
    library_version: str
    days: tuple[CandidateDay, ...]


@dataclass(frozen=True)
class ConfigCandidate:
    kind: str
    revision: RevisionCandidate | None


def _copy_day(row: DaySnapshot) -> CandidateDay:
    return CandidateDay(
        day=row.day,
        base_state=row.base_state,
        base_library_version=row.base_library_version,
        override_state=row.override_state,
        override_reason=row.override_reason,
        effective_state=row.effective_state,
    )


def _new_day(day: date, base_state: str, version: str) -> CandidateDay:
    return CandidateDay(
        day=day,
        base_state=base_state,
        base_library_version=version,
        override_state=None,
        override_reason=None,
        effective_state=base_state,
    )


def _build_full_range(
    start: date, end: date
) -> tuple[tuple[CandidateDay, ...], str]:
    candidates, library_version = calendar_build.build_calendar_candidate(
        start, end
    )
    days = tuple(
        CandidateDay(
            day=item.day,
            base_state=item.base_state,
            base_library_version=item.base_library_version,
            override_state=None,
            override_reason=None,
            effective_state=item.effective_state,
        )
        for item in candidates
    )
    return days, library_version


def build_candidate(
    snapshot: ConfigSnapshot, normalized: dict
) -> ConfigCandidate:
    """Build the new revision outside any write lock (library calls allowed)."""
    kind = normalized["kind"]
    if kind in ("profile", "current_class", "class_games"):
        return ConfigCandidate(kind=kind, revision=None)
    if kind == "term_create":
        days, library_version = _build_full_range(
            date.fromisoformat(normalized["start_date"]),
            date.fromisoformat(normalized["end_date"]),
        )
        return ConfigCandidate(
            kind=kind,
            revision=RevisionCandidate(
                revision_no=1, library_version=library_version, days=days
            ),
        )
    assert snapshot.target_term is not None
    if kind == "term_update":
        new_start = date.fromisoformat(normalized["start_date"])
        new_end = date.fromisoformat(normalized["end_date"])
        if (
            new_start == snapshot.target_term.start_date
            and new_end == snapshot.target_term.end_date
        ):
            return ConfigCandidate(kind=kind, revision=None)
        old_days = {
            row.day: row
            for row in snapshot.days_by_term.get(snapshot.target_term.id, ())
        }
        days: list[CandidateDay] = []
        built_version: str | None = None
        for day in cal.iter_dates(new_start, new_end):
            previous = old_days.get(day)
            if previous is not None:
                days.append(_copy_day(previous))
                continue
            # A general library failure is CALENDAR_UNAVAILABLE, never a
            # guessed state; unknown coverage is persisted as ``unknown``
            # by ``default_state`` itself.
            try:
                state, version = cal.default_state(day)
            except cal.CalendarLibraryError as exc:
                raise LocalCalendarUnavailable() from exc
            built_version = version
            days.append(_new_day(day, state, version))
        library_version = (
            built_version
            if built_version is not None
            else snapshot.target_term.library_version
        )
        return ConfigCandidate(
            kind=kind,
            revision=RevisionCandidate(
                revision_no=snapshot.target_term.revision_no + 1,
                library_version=library_version,
                days=tuple(days),
            ),
        )
    # calendar_override: copy every stored day; only the target date changes.
    current = _target_day(snapshot, normalized)
    days = []
    for row in snapshot.days_by_term.get(snapshot.target_term.id, ()):
        if row.day == current.day:
            override_state = normalized["state"]
            override_reason = normalized["reason"]
            days.append(
                CandidateDay(
                    day=row.day,
                    base_state=row.base_state,
                    base_library_version=row.base_library_version,
                    override_state=override_state,
                    override_reason=override_reason,
                    effective_state=override_state or row.base_state,
                )
            )
        else:
            days.append(_copy_day(row))
    return ConfigCandidate(
        kind=kind,
        revision=RevisionCandidate(
            revision_no=snapshot.target_term.revision_no + 1,
            # No library call for an override-only change: the previous
            # header's library version is kept.
            library_version=snapshot.target_term.library_version,
            days=tuple(days),
        ),
    )


# ---------------------------------------------------------------------------
# Digests
# ---------------------------------------------------------------------------


def _day_payload(row: DaySnapshot | CandidateDay) -> dict:
    return {
        "day": row.day,
        "base_state": row.base_state,
        "base_library_version": row.base_library_version,
        "override_state": row.override_state,
        "override_reason": row.override_reason,
        "effective_state": row.effective_state,
    }


def _snapshot_payload(snapshot: ConfigSnapshot) -> dict:
    payload = {
        "config_version": snapshot.config_version,
        "profile": {
            "id": snapshot.profile_id,
            "display_name": snapshot.display_name,
        },
        "school_name": snapshot.school_name,
        "class": {
            "id": snapshot.class_id,
            "name": snapshot.class_name,
            "grade": snapshot.grade,
        },
        "terms": [
            {
                "id": term.id,
                "name": term.name,
                "start_date": term.start_date,
                "end_date": term.end_date,
                "revision_id": term.revision_id,
                "revision_no": term.revision_no,
                "library_version": term.library_version,
            }
            for term in snapshot.terms
        ],
        "days_by_term": {
            term_id: [_day_payload(row) for row in rows]
            for term_id, rows in snapshot.days_by_term.items()
        },
        "plans": [
            {
                "id": plan.id,
                "plan_date": plan.plan_date,
                "term_id": plan.term_id,
                "week_number": plan.week_number,
                "content_version": plan.content_version,
            }
            for plan in snapshot.plans
        ],
    }
    if snapshot.game_payload is not None:
        payload["class_games"] = snapshot.game_payload
    return payload


def premise_digest(snapshot: ConfigSnapshot) -> str:
    return _digest(_snapshot_payload(snapshot))


def candidate_digest(candidate: ConfigCandidate) -> str:
    revision = candidate.revision
    return _digest(
        {
            "kind": candidate.kind,
            "revision": None
            if revision is None
            else {
                "revision_no": revision.revision_no,
                "library_version": revision.library_version,
                "days": [_day_payload(row) for row in revision.days],
            },
        }
    )


# ---------------------------------------------------------------------------
# Views: before/after, calendar diff and impact facts
# ---------------------------------------------------------------------------


def _day_maps(snapshot: ConfigSnapshot) -> dict[str, dict[date, DaySnapshot]]:
    return {
        term_id: {row.day: row for row in rows}
        for term_id, rows in snapshot.days_by_term.items()
    }


def _interpretation(
    terms: tuple[TermSnapshot, ...],
    maps: dict[str, dict[date, DaySnapshot]],
    day: date,
) -> tuple[str, int | None, dict | None]:
    """(state, week_number, override) under a configuration; outside_term."""
    for term in terms:
        if term.start_date <= day <= term.end_date:
            row = maps.get(term.id, {}).get(day)
            if row is None:
                raise LocalStorageError("日历快照缺少目标日期")
            week_number, _start, _weekday = cal.week_info(term.start_date, day)
            override = (
                None
                if row.override_state is None
                else {"state": row.override_state, "reason": row.override_reason}
            )
            return row.effective_state, week_number, override
    return cal.OUTSIDE_TERM, None, None


def _candidate_interpretation(
    snapshot: ConfigSnapshot,
    normalized: dict,
    candidate: ConfigCandidate,
    day: date,
) -> tuple[str, int | None, dict | None]:
    """Interpretation after the change is applied (preview/apply time)."""
    kind = normalized["kind"]
    maps = _day_maps(snapshot)
    if kind in ("profile", "current_class"):
        return _interpretation(snapshot.terms, maps, day)
    revision = candidate.revision
    if revision is None:
        # term_update without a calendar change (rename-only / no-op): the
        # date interpretation stays exactly the current one (R7).
        return _interpretation(snapshot.terms, maps, day)
    by_day = {row.day: row for row in revision.days}
    if kind == "term_create":
        start = date.fromisoformat(normalized["start_date"])
        end = date.fromisoformat(normalized["end_date"])
        if start <= day <= end:
            row = by_day.get(day)
            if row is None:
                raise LocalStorageError("候选日历缺少目标日期")
            week_number, _start, _weekday = cal.week_info(start, day)
            return row.effective_state, week_number, None
        return _interpretation(snapshot.terms, maps, day)
    if kind == "term_update":
        start = date.fromisoformat(normalized["start_date"])
        end = date.fromisoformat(normalized["end_date"])
        if start <= day <= end:
            row = by_day.get(day)
            if row is None:
                raise LocalStorageError("候选日历缺少目标日期")
            week_number, _start, _weekday = cal.week_info(start, day)
            override = (
                None
                if row.override_state is None
                else {"state": row.override_state, "reason": row.override_reason}
            )
            return row.effective_state, week_number, override
        # Outside the *new* range the date is no longer interpreted by this
        # term: only another term could cover it (overlap is refused).
        other_terms = tuple(
            term
            for term in snapshot.terms
            if term.id != snapshot.target_term.id
        )
        return _interpretation(other_terms, maps, day)
    # calendar_override (range unchanged)
    for term in snapshot.terms:
        if term.start_date <= day <= term.end_date:
            row = by_day.get(day)
            if row is None:
                row = maps.get(term.id, {}).get(day)
            if row is None:
                raise LocalStorageError("候选日历缺少目标日期")
            week_number, _start, _weekday = cal.week_info(term.start_date, day)
            override = (
                None
                if row.override_state is None
                else {"state": row.override_state, "reason": row.override_reason}
            )
            return row.effective_state, week_number, override
    return cal.OUTSIDE_TERM, None, None


def _before_after(
    snapshot: ConfigSnapshot, normalized: dict
) -> tuple[dict | None, dict | None]:
    kind = normalized["kind"]
    if kind == "profile":
        return (
            {
                "display_name": snapshot.display_name,
                "school_name": snapshot.school_name,
            },
            {
                "display_name": normalized["display_name"],
                "school_name": normalized["school_name"],
            },
        )
    if kind == "current_class":
        return (
            {"name": snapshot.class_name, "grade": snapshot.grade},
            {"name": normalized["name"], "grade": normalized["grade"]},
        )
    if kind == "term_create":
        return (
            None,
            {
                "name": normalized["name"],
                "start_date": normalized["start_date"],
                "end_date": normalized["end_date"],
            },
        )
    if kind == "class_games":
        return (snapshot.game_payload, _game_payload(normalized))
    if kind == "term_update":
        assert snapshot.target_term is not None
        return (
            {
                "term_id": snapshot.target_term.id,
                "name": snapshot.target_term.name,
                "start_date": snapshot.target_term.start_date.isoformat(),
                "end_date": snapshot.target_term.end_date.isoformat(),
            },
            {
                "term_id": normalized["term_id"],
                "name": normalized["name"],
                "start_date": normalized["start_date"],
                "end_date": normalized["end_date"],
            },
        )
    return None, None


def _diff_item(
    day: date,
    before: tuple[str, int | None, dict | None],
    after: tuple[str, int | None, dict | None],
) -> dict:
    return {
        "date": day.isoformat(),
        "before_state": before[0],
        "after_state": after[0],
        "before_week": before[1],
        "after_week": after[1],
        "override_before": before[2],
        "override_after": after[2],
    }


def _calendar_diff(
    snapshot: ConfigSnapshot, normalized: dict, candidate: ConfigCandidate
) -> list[dict]:
    kind = normalized["kind"]
    if kind in ("profile", "current_class", "class_games"):
        return []
    maps = _day_maps(snapshot)
    if kind == "term_create":
        start = date.fromisoformat(normalized["start_date"])
        end = date.fromisoformat(normalized["end_date"])
        diff = []
        for day in cal.iter_dates(start, end):
            after = _candidate_interpretation(snapshot, normalized, candidate, day)
            diff.append(_diff_item(day, (cal.OUTSIDE_TERM, None, None), after))
        return diff
    if kind == "term_update":
        assert snapshot.target_term is not None
        revision = candidate.revision
        if revision is None:
            return []  # rename only: no invented date changes
        old_start = snapshot.target_term.start_date
        old_end = snapshot.target_term.end_date
        new_start = date.fromisoformat(normalized["start_date"])
        new_end = date.fromisoformat(normalized["end_date"])
        window_start = min(old_start, new_start)
        window_end = max(old_end, new_end)
        diff = []
        for day in cal.iter_dates(window_start, window_end):
            # The full current interpretation (every materialized term inside
            # the envelope, including intermediate unmoved terms) compared
            # with the candidate interpretation: unaffected days never enter
            # the diff.
            before = _interpretation(snapshot.terms, maps, day)
            after = _candidate_interpretation(
                snapshot, normalized, candidate, day
            )
            if before != after:
                diff.append(_diff_item(day, before, after))
        return diff
    # calendar_override: exactly the target date when it actually changed
    target_date = date.fromisoformat(normalized["date"])
    before = _interpretation(snapshot.terms, maps, target_date)
    after = _candidate_interpretation(
        snapshot, normalized, candidate, target_date
    )
    if before == after:
        return []
    return [_diff_item(target_date, before, after)]


def _impact_view(
    snapshot: ConfigSnapshot, normalized: dict, candidate: ConfigCandidate
) -> dict:
    kind = normalized["kind"]
    if kind == "class_games":
        # Game configuration never changes plan headers or week numbers.
        return {
            "retained_header_count": snapshot.total_plan_count,
            "affected_plans": [],
            "counts": {
                "existing_plan_count": snapshot.total_plan_count,
                "affected_plan_count": 0,
                "by_reason": {},
            },
        }
    maps = _day_maps(snapshot)
    affected: list[dict] = []
    for plan in snapshot.plans:
        before_state, before_week, _before_override = _interpretation(
            snapshot.terms, maps, plan.plan_date
        )
        after_state, after_week, _after_override = _candidate_interpretation(
            snapshot, normalized, candidate, plan.plan_date
        )
        if kind in ("profile", "current_class"):
            reasons = ["header_retained"]
        else:
            reasons = []
            if after_state == cal.OUTSIDE_TERM and before_state != cal.OUTSIDE_TERM:
                reasons.append("outside_new_range")
            if before_state != after_state:
                reasons.append("date_state_changed")
            if before_week != after_week:
                reasons.append("week_changed")
            reasons = [reason for reason in _REASON_ORDER if reason in reasons]
            if not reasons:
                continue
        affected.append(
            {
                "id": plan.id,
                "plan_date": plan.plan_date.isoformat(),
                "term_id": plan.term_id,
                "content_version": plan.content_version,
                "stored_week_number": plan.week_number,
                "proposed_week_number": after_week,
                "creation_eligible_after": (after_state == cal.TEACHING),
                "reasons": reasons,
            }
        )
    by_reason: dict[str, int] = {}
    for item in affected:
        for reason in item["reasons"]:
            by_reason[reason] = by_reason.get(reason, 0) + 1
    return {
        "retained_header_count": snapshot.total_plan_count,
        "affected_plans": affected,
        "counts": {
            "existing_plan_count": (
                snapshot.total_plan_count
                if kind in ("profile", "current_class")
                else len(snapshot.plans)
            ),
            "affected_plan_count": len(affected),
            "by_reason": by_reason,
        },
    }


# ---------------------------------------------------------------------------
# Receipts
# ---------------------------------------------------------------------------

ACTION_BY_KIND = {
    "profile": ("update_local_profile", "local_profile"),
    "current_class": ("update_local_class", "local_class"),
    "term_create": ("create_local_term", "local_term"),
    "term_update": ("update_local_term", "local_term"),
    "calendar_override": ("update_calendar_override", "local_term"),
    "class_games": ("update_class_games", "local_class"),
}


def _find_receipt(session: Session, request_id: str) -> LocalConfigOperation | None:
    try:
        return session.scalars(
            select(LocalConfigOperation).where(
                LocalConfigOperation.request_id == request_id
            )
        ).one_or_none()
    except ValueError:
        # A persisted receipt that is not valid JSON is a storage error.
        raise LocalStorageError("配置回执数据损坏") from None


def _receipt_result(receipt: LocalConfigOperation) -> dict:
    try:
        result = receipt.result_json
    except ValueError:
        raise LocalStorageError("配置回执数据损坏") from None
    if not isinstance(result, dict):
        raise LocalStorageError("配置回执数据损坏")
    return result


def _replay(receipt: LocalConfigOperation, fingerprint: str) -> dict:
    if receipt.input_fingerprint != fingerprint:
        raise LocalConfigRequestConflict()
    result = dict(_receipt_result(receipt))
    result["replayed"] = True
    return result


def _store_receipt(
    session: Session,
    *,
    request_id: str,
    fingerprint: str,
    result: dict,
    config_version: int,
    created_at,
) -> None:
    session.add(
        LocalConfigOperation(
            id=new_opaque_id(),
            request_id=request_id,
            input_fingerprint=fingerprint,
            result_json=result,
            config_version=config_version,
            created_at=created_at,
        )
    )
    session.flush()


def _record_operation(
    session: Session,
    *,
    actor_id: str,
    action: str,
    target_type: str,
    target_id: str,
    config_version: int,
    created_at,
) -> None:
    session.add(
        LocalOperationRecord(
            id=new_opaque_id(),
            created_at=created_at,
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            target_version_after=config_version,
        )
    )
    session.flush()


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


def _validate_config_version(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise LocalValidationError("expected_config_version 必须是 >= 1 的整数")
    return value


def preview(
    session: Session,
    *,
    expected_config_version: object,
    change: object,
) -> dict:
    expected = _validate_config_version(expected_config_version)
    normalized = normalize_change(change)

    with read_scope(session):
        snapshot = load_snapshot(session, normalized)
    if snapshot.config_version != expected:
        raise LocalConfigVersionConflict(
            details={"config_version": snapshot.config_version}
        )
    validate_against_state(snapshot, normalized)
    candidate = build_candidate(snapshot, normalized)
    changed = is_changed(snapshot, normalized)
    before, after = _before_after(snapshot, normalized)
    diff = _calendar_diff(snapshot, normalized, candidate)
    impact = _impact_view(snapshot, normalized, candidate)

    payload = config_tokens.new_preview_payload(
        config_version=snapshot.config_version,
        change=normalized,
        changed=changed,
        premise_digest=premise_digest(snapshot),
        candidate_digest=candidate_digest(candidate),
        impact_digest=_digest(impact),
    )
    return {
        "expected_config_version": snapshot.config_version,
        "normalized_change": normalized,
        "changed": changed,
        "preview_token": config_tokens.sign_preview_token(payload),
        "expires_at": datetime.fromtimestamp(payload["exp"], tz=timezone.utc),
        "before": before,
        "after": after,
        "calendar_diff": diff,
        "impact": impact,
    }


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


def _unchanged_result(request_id: str, config_version: int) -> dict:
    return {
        "status": "unchanged",
        "request_id": request_id,
        "config_version": config_version,
        "changed": False,
        "affected_plan_ids": [],
        "calendar_revision_id": None,
        "game_revision_id": None,
    }


def apply(
    session: Session,
    *,
    request_id: object,
    expected_config_version: object,
    change: object,
    preview_token: object,
) -> dict:
    expected = _validate_config_version(expected_config_version)
    normalized = normalize_change(change)
    rid = normalize_request_id(request_id)
    fingerprint = change_fingerprint(expected, normalized)

    # First short read: a committed receipt for this request id replays.
    with read_scope(session):
        require_context(session, date.today())
        receipt = _find_receipt(session, rid)
        if receipt is not None:
            return _replay(receipt, fingerprint)

    # A valid token is required before any candidate work (422/409).
    payload = config_tokens.verify_preview_token(preview_token)
    if (
        payload.get("change") != normalized
        or payload.get("config_version") != expected
    ):
        raise LocalConfigPreviewStale()

    # Fresh short read snapshot: rebuild the very same candidate outside the
    # lock (library calls, normalization and diffing never hold the lock).
    # When the configuration version already moved, the same request id may
    # have committed concurrently: the receipt check comes before the
    # version conflict so a lost-response retry replays its own result.
    with read_scope(session):
        require_context(session, date.today())
        snapshot = load_snapshot(session, normalized)
        concurrent_receipt = (
            _find_receipt(session, rid)
            if snapshot.config_version != expected
            else None
        )
    if concurrent_receipt is not None:
        return _replay(concurrent_receipt, fingerprint)
    if snapshot.config_version != expected:
        raise LocalConfigVersionConflict(
            details={"config_version": snapshot.config_version}
        )
    if premise_digest(snapshot) != payload.get("premise_digest"):
        raise LocalConfigPreviewStale()
    validate_against_state(snapshot, normalized)
    candidate = build_candidate(snapshot, normalized)
    if candidate_digest(candidate) != payload.get("candidate_digest"):
        raise LocalConfigPreviewStale()
    impact = _impact_view(snapshot, normalized, candidate)
    if _digest(impact) != payload.get("impact_digest"):
        raise LocalConfigPreviewStale()
    if is_changed(snapshot, normalized) != payload.get("changed"):
        raise LocalConfigPreviewStale()

    affected_ids = [item["id"] for item in impact["affected_plans"]]

    begin_immediate(session)
    try:
        require_context(session, date.today())
        receipt = _find_receipt(session, rid)
        if receipt is not None:
            result = _replay(receipt, fingerprint)
            rollback(session)
            return result
        locked = load_snapshot(session, normalized)
        if locked.config_version != expected:
            raise LocalConfigVersionConflict(
                details={"config_version": locked.config_version}
            )
        if premise_digest(locked) != payload.get("premise_digest"):
            raise LocalConfigPreviewStale()
        changed_locked = is_changed(locked, normalized)
        if changed_locked != payload.get("changed"):
            raise LocalConfigPreviewStale()
        now = utc_now()
        if not changed_locked:
            result = _unchanged_result(rid, locked.config_version)
            _store_receipt(
                session,
                request_id=rid,
                fingerprint=fingerprint,
                result=result,
                config_version=locked.config_version,
                created_at=now,
            )
            session.commit()
            return result
        result = _apply_change(
            session,
            snapshot=locked,
            candidate=candidate,
            normalized=normalized,
            request_id=rid,
            fingerprint=fingerprint,
            affected_ids=affected_ids,
            now=now,
        )
        session.commit()
    except BaseException:
        rollback(session)
        raise
    return result


def _apply_change(
    session: Session,
    *,
    snapshot: ConfigSnapshot,
    candidate: ConfigCandidate,
    normalized: dict,
    request_id: str,
    fingerprint: str,
    affected_ids: list[str],
    now,
) -> dict:
    kind = normalized["kind"]
    profile = session.get(LocalProfile, snapshot.profile_id)
    settings = session.get(LocalSettings, "singleton")
    if profile is None or settings is None:  # pragma: no cover - validated
        raise LocalStorageError("本地档案数据不完整")
    new_config_version = snapshot.config_version + 1
    revision_id: str | None = None
    game_revision_id: str | None = None
    action, target_type = ACTION_BY_KIND[kind]
    target_id: str

    if kind == "profile":
        profile.display_name = normalized["display_name"]
        profile.updated_at = now
        settings.school_name = normalized["school_name"]
        target_id = profile.id
    elif kind == "current_class":
        school_class = session.get(LocalClass, snapshot.class_id)
        if school_class is None:  # pragma: no cover - validated
            raise LocalStorageError("当前班级缺失")
        school_class.name = normalized["name"]
        school_class.grade = normalized["grade"]
        school_class.updated_at = now
        target_id = school_class.id
    elif kind == "term_create":
        assert candidate.revision is not None
        term_id = new_opaque_id()
        revision_id = new_opaque_id()
        term = LocalTerm(
            id=term_id,
            name=normalized["name"],
            start_date=date.fromisoformat(normalized["start_date"]),
            end_date=date.fromisoformat(normalized["end_date"]),
            current_calendar_revision_id=revision_id,
            created_at=now,
            updated_at=now,
        )
        session.add(term)
        session.flush()
        _insert_revision(
            session,
            revision_id=revision_id,
            term_id=term_id,
            revision_no=candidate.revision.revision_no,
            library_version=candidate.revision.library_version,
            created_by=snapshot.profile_id,
            created_at=now,
            days=candidate.revision.days,
        )
        target_id = term_id
    elif kind == "term_update":
        term = session.get(LocalTerm, normalized["term_id"])
        if term is None:  # pragma: no cover - validated in snapshot
            raise LocalTermNotFound()
        term.name = normalized["name"]
        term.updated_at = now
        if candidate.revision is not None:
            term.start_date = date.fromisoformat(normalized["start_date"])
            term.end_date = date.fromisoformat(normalized["end_date"])
            revision_id = new_opaque_id()
            _insert_revision(
                session,
                revision_id=revision_id,
                term_id=term.id,
                revision_no=candidate.revision.revision_no,
                library_version=candidate.revision.library_version,
                created_by=snapshot.profile_id,
                created_at=now,
                days=candidate.revision.days,
            )
            term.current_calendar_revision_id = revision_id
        target_id = term.id
    elif kind == "class_games":
        game_head = session.get(LocalClassGameHead, snapshot.class_id)
        if game_head is None:  # pragma: no cover - validated in snapshot
            raise LocalStorageError("班级游戏配置缺失")
        current_game = session.get(
            LocalClassGameRevision, game_head.current_revision_id
        )
        if current_game is None:  # pragma: no cover - validated in snapshot
            raise LocalStorageError("班级游戏配置修订缺失")
        payload = _game_payload(normalized)
        game_revision_id = new_opaque_id()
        session.add(
            LocalClassGameRevision(
                id=game_revision_id,
                class_id=snapshot.class_id,
                revision_no=current_game.revision_no + 1,
                payload_json=payload,
                payload_hash=_digest(payload),
                created_at=now,
            )
        )
        session.flush()
        game_head.current_revision_id = game_revision_id
        game_head.updated_at = now
        target_id = snapshot.class_id
    else:  # calendar_override
        term = session.get(LocalTerm, normalized["term_id"])
        if term is None:  # pragma: no cover - validated in snapshot
            raise LocalTermNotFound()
        assert candidate.revision is not None
        revision_id = new_opaque_id()
        _insert_revision(
            session,
            revision_id=revision_id,
            term_id=term.id,
            revision_no=candidate.revision.revision_no,
            library_version=candidate.revision.library_version,
            created_by=snapshot.profile_id,
            created_at=now,
            days=candidate.revision.days,
        )
        term.current_calendar_revision_id = revision_id
        term.updated_at = now
        target_id = term.id

    settings.config_version = new_config_version
    settings.updated_at = now
    _record_operation(
        session,
        actor_id=snapshot.profile_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        config_version=new_config_version,
        created_at=now,
    )
    result = {
        "status": "applied",
        "request_id": request_id,
        "config_version": new_config_version,
        "changed": True,
        "affected_plan_ids": list(affected_ids),
        "calendar_revision_id": revision_id,
        "game_revision_id": game_revision_id,
    }
    _store_receipt(
        session,
        request_id=request_id,
        fingerprint=fingerprint,
        result=result,
        config_version=new_config_version,
        created_at=now,
    )
    return result


def _insert_revision(
    session: Session,
    *,
    revision_id: str,
    term_id: str,
    revision_no: int,
    library_version: str,
    created_by: str,
    created_at,
    days: tuple[CandidateDay, ...],
) -> None:
    session.add(
        LocalCalendarRevision(
            id=revision_id,
            term_id=term_id,
            revision_no=revision_no,
            library_version=library_version,
            created_by=created_by,
            created_at=created_at,
        )
    )
    session.flush()
    if days:
        session.execute(
            insert(LocalCalendarDay),
            [
                {
                    "revision_id": revision_id,
                    "date": row.day,
                    "base_state": row.base_state,
                    "base_library_version": row.base_library_version,
                    "override_state": row.override_state,
                    "override_reason": row.override_reason,
                    "effective_state": row.effective_state,
                }
                for row in days
            ],
        )


# ---------------------------------------------------------------------------
# Receipt lookup
# ---------------------------------------------------------------------------


def get_operation(session: Session, *, request_id: object) -> dict:
    rid = normalize_request_id(request_id)
    with read_scope(session):
        require_context(session, date.today())
        receipt = _find_receipt(session, rid)
        if receipt is None:
            raise LocalConfigOperationNotFound()
        return dict(_receipt_result(receipt))


def read_class_games(session: Session) -> dict:
    """Read-only current class game configuration (D2 W2 / W5 hand-off).

    Returns the current immutable revision identity and an apply-ready flat
    ``change`` object (``kind``/``locations``/``game_scope``/``guidance``) so a
    settings page can show the current payload and prefill an edit without
    building a modification preview first. Never writes.
    """
    with read_scope(session):
        context = require_context(session, date.today())
        assert context.school_class is not None and context.settings is not None
        game_head = session.get(LocalClassGameHead, context.school_class.id)
        if game_head is None:
            raise LocalStorageError("班级游戏配置缺失")
        revision = session.get(
            LocalClassGameRevision, game_head.current_revision_id
        )
        if revision is None or revision.class_id != context.school_class.id:
            raise LocalStorageError("班级游戏配置修订缺失")
        payload = dict(revision.payload_json)
        return {
            "class_id": context.school_class.id,
            "class_name": context.school_class.name,
            "grade": context.school_class.grade,
            "config_version": context.settings.config_version,
            "game_revision_id": revision.id,
            "revision_no": revision.revision_no,
            "change": {
                "kind": "class_games",
                "locations": list(payload.get("locations") or []),
                "game_scope": payload.get("game_scope"),
                "guidance": payload.get("guidance"),
            },
        }
