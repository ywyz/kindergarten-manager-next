"""D2 W3 business input projection for the three daily AI tasks.

Engineering spec §2.2 / §9.1: the service, not the model, builds the immutable
input snapshot from local business data. Only the *actually sent* business
values form the dependency fingerprint, so an unrelated later change (school
name, reflection, global config version, personal guidance) never makes a
candidate look source-stale.

Rules implemented here (no network, no writing):

* ``daily_lesson_split`` — the saved raw lesson plan + this request's target
  grade; the six-field ``group_activity`` is the replaced target.
* ``daily_process_adapt`` — the current saved process + target grade + the
  current split-baseline *value* (business identity only; a reflection edit
  that only bumps the content version never changes it).
* ``daily_other_activities`` — plan date / week number / weekday / target
  grade / the persisted effective-calendar context with the ±7-day holiday
  window / the plan's class game-configuration revision / the saved
  collective-activity + four-board snapshot. Reflection, names, the whole raw
  lesson plan and server group/game ids are never included.

Calendar: the target day's effective state comes from the plan's term *current
persisted* revision (never a live recompute) and the plan header keeps its own
``week_number``/``weekday``. Holiday names come from the existing
``chinese_calendar`` library (offline, no network): only days the library
reports as an actual holiday *with a name* enter ``holiday_context``, so an
ordinary weekend (name ``None``) is never dressed up as a festival. When the
library's coverage does not reach a day of the window, the payload is not
silently presented as "no holiday": a coverage diagnostic is recorded on the
input record (server-side fact, returned with task detail) while the model
payload stays inside the frozen contract.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.local.ai_provenance import resolve_baseline
from app.local.errors import (
    LocalAiInputEmpty,
    LocalAiInputInvalid,
    LocalStorageError,
    LocalValidationError,
)
from app.local.models import (
    LocalCalendarDay,
    LocalCalendarRevision,
    LocalClassGameHead,
    LocalClassGameRevision,
    LocalDailyPlan,
    LocalDailyPlanContent,
    LocalTerm,
)
from app.local.prompt_bundles import (
    TASK_TYPES,
    CandidateInvalid,
    canonical_json,
    validate_input,
)
from app.services.daily_plan_content import (
    ContentValidationError,
    parse_adopted_content,
)

INPUT_SCHEMA_VERSION = 1
HOLIDAY_WINDOW_DAYS = 7

_GRADES = ("small", "middle", "large")

# Keys that are server-owned identities and must never reach the model payload.
_ID_KEYS = ("group_id", "game_id")

# The four replaceable boards of the OTHER-activities candidate, in a fixed
# order so target hashes are stable.
_OTHER_BOARDS = (
    "morning_games",
    "morning_talk",
    "post_group_games",
    "afternoon_outdoor",
)

HolidayProvider = Callable[[date], "tuple[bool, str | None]"]


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _default_holiday_provider(day: date) -> tuple[bool, str | None]:
    """Existing offline calendar library: ``(is_holiday, holiday_name)``.

    Imported lazily so the local layer keeps working when the optional
    dependency is absent; a missing library is reported as "no coverage" by
    the caller instead of guessing a holiday name.
    """
    import chinese_calendar as cc  # noqa: PLC0415

    return cc.get_holiday_detail(day)


def holiday_context(
    from_date: date,
    to_date: date,
    *,
    provider: HolidayProvider | None = None,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Return ``(holiday_context, coverage_diagnostic)`` for ``[from, to]``.

    Only a day the library reports as an actual holiday (``is_holiday``)
    *with* a name is included; an ordinary weekend (``name is None``) and a
    make-up workday (``is_holiday is False``) are not festivals. Days the
    library does not cover are listed in the diagnostic so the window is never
    silently claimed complete.
    """
    resolve = provider or _default_holiday_provider
    facts: list[dict[str, str]] = []
    uncovered: list[str] = []
    total = 0
    day = from_date
    while day <= to_date:
        total += 1
        try:
            is_holiday, name = resolve(day)
        except NotImplementedError:
            uncovered.append(day.isoformat())
        except Exception:  # noqa: BLE001 - a broken provider is "no coverage"
            uncovered.append(day.isoformat())
        else:
            if is_holiday is True and isinstance(name, str) and name.strip():
                facts.append({"date": day.isoformat(), "name": name})
        day += timedelta(days=1)
    if not uncovered:
        coverage_state = "full"
        note = ""
    elif len(uncovered) == total:
        coverage_state = "unknown"
        note = "该窗口超出日历库覆盖范围，未收录节日不代表当天没有节日"
    else:
        coverage_state = "partial"
        note = "部分日期超出日历库覆盖范围，未收录节日不代表当天没有节日"
    coverage: dict[str, Any] = {
        "from": from_date.isoformat(),
        "to": to_date.isoformat(),
        "coverage": coverage_state,
        "unknown_dates": uncovered,
        "note": note,
        "source": "chinese_calendar",
    }
    return facts, coverage


def _calendar_context(
    session: Session,
    plan: LocalDailyPlan,
    *,
    provider: HolidayProvider | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Target-day persisted state + the ±7 holiday window."""
    term = session.get(LocalTerm, plan.term_id)
    if term is None:
        raise LocalStorageError("计划所属学期缺失")
    revision = session.get(LocalCalendarRevision, term.current_calendar_revision_id)
    if revision is None or revision.term_id != term.id:
        raise LocalStorageError("当前日历修订缺失")
    row = session.get(LocalCalendarDay, (revision.id, plan.plan_date))
    effective_state = row.effective_state if row is not None else "unknown"
    facts, coverage = holiday_context(
        plan.plan_date - timedelta(days=HOLIDAY_WINDOW_DAYS),
        plan.plan_date + timedelta(days=HOLIDAY_WINDOW_DAYS),
        provider=provider,
    )
    context = {
        "effective_state": effective_state,
        "weekday": plan.weekday,
        "holiday_context": facts,
    }
    diagnostic = {
        "calendar_revision_id": revision.id,
        "target_day_state": effective_state,
        "target_day_row_present": row is not None,
        "holiday_window": coverage,
    }
    return context, diagnostic


def _game_config(
    session: Session, class_id: str
) -> tuple[dict[str, Any], str, str]:
    head = session.get(LocalClassGameHead, class_id)
    if head is None:
        raise LocalStorageError("班级游戏配置缺失")
    revision = session.get(LocalClassGameRevision, head.current_revision_id)
    if revision is None or revision.class_id != class_id:
        raise LocalStorageError("班级游戏配置修订缺失")
    payload = revision.payload_json
    config = {
        "locations": list(payload.get("locations") or []),
        "game_scope": payload.get("game_scope"),
        "guidance": payload.get("guidance"),
    }
    return config, revision.id, revision.payload_hash


def _baseline_reference(
    session: Session, plan: LocalDailyPlan, content: LocalDailyPlanContent
) -> tuple[str | None, Any]:
    """The current split-baseline *source identity* and value.

    Engineering spec §2.2: the adapt dependency is the current process, this
    request's grade and the **current baseline source reference** — the
    ``baseline_candidate_id`` of the content's provenance row, not merely a
    hash of the baseline text. Two adopted split candidates can carry identical
    process text but different sources, so the identity must be part of the
    dependency. Old D1 content has no provenance row and a ``null`` baseline,
    which is legal ("no baseline"). Corrupt combinations are storage errors and
    are never downgraded to "no baseline".

    W4 moved the actual validation into the shared
    :mod:`app.local.ai_provenance` module so the daily-plan read/save/export
    chain and this projection agree on exactly what a legal baseline is (the
    value must equal the referenced split candidate's raw model process).
    """
    return resolve_baseline(session, plan, content)


def _strip_ids(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_ids(item)
            for key, item in value.items()
            if key not in _ID_KEYS
        }
    if isinstance(value, list):
        return [_strip_ids(item) for item in value]
    return value


def _snapshot(content: LocalDailyPlanContent) -> tuple[dict[str, Any], dict[str, Any]]:
    """The saved collective-activity + four-board snapshot without ids.

    Returns ``(snapshot, boards)`` where ``boards`` holds the canonical
    replaceable values used for the target hashes.
    """
    try:
        model = parse_adopted_content(content.adopted_content)
    except ContentValidationError:
        raise LocalStorageError("计划内容无法解析") from None
    dumped = model.model_dump(exclude_none=True)
    snapshot: dict[str, Any] = {}
    group_activity = _strip_ids(dumped.get("group_activity"))
    snapshot["group_activity"] = group_activity or None
    for board in ("morning_games", "morning_talk", "post_group_games", "afternoon_outdoor"):
        if board in dumped:
            snapshot[board] = _strip_ids(dumped[board])
    boards: dict[str, Any] = {
        "group_activity": group_activity or None,
    }
    for board in _OTHER_BOARDS:
        boards[board] = snapshot.get(board)
    return snapshot, boards


@dataclass(frozen=True)
class ProjectedInput:
    """One immutable input projection for a task submission."""

    task_type: str
    target_grade: str
    payload: dict[str, Any]
    dependencies: dict[str, Any]
    dependency_hash: str
    target_hashes: dict[str, str]
    source_excerpt: dict[str, Any]

    def as_row_kwargs(self) -> dict[str, Any]:
        return {
            "payload_json": self.payload,
            "dependencies_json": self.dependencies,
            "dependency_hash": self.dependency_hash,
            "target_hashes_json": self.target_hashes,
        }


def _require_grade(value: object) -> str:
    if value not in _GRADES:
        raise LocalValidationError("target_grade 必须是小班/中班/大班之一")
    return str(value)


def _require_non_empty(text: object, label: str) -> str:
    if not isinstance(text, str) or not text.strip():
        raise LocalAiInputEmpty(f"{label}为空，无法发起该 AI 操作")
    return text


def _validated(task_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return validate_input(task_type, payload)
    except CandidateInvalid as exc:
        raise LocalAiInputInvalid(f"AI 输入不合契约：{exc}")


def project_input(
    session: Session,
    *,
    plan: LocalDailyPlan,
    content: LocalDailyPlanContent,
    task_type: str,
    target_grade: object,
    holiday_provider: HolidayProvider | None = None,
) -> ProjectedInput:
    """Build the immutable input projection for one task submission."""
    if task_type not in TASK_TYPES:
        raise LocalValidationError("不支持的日任务类型")
    grade = _require_grade(target_grade)

    if task_type == "daily_lesson_split":
        raw = _require_non_empty(content.raw_lesson_plan, "原始教案")
        payload = {"raw_lesson_plan": raw, "grade": grade}
        dependencies = {"raw_lesson_plan": raw, "grade": grade}
        boards = _strip_ids(
            parse_adopted_content(content.adopted_content).model_dump(exclude_none=True)
        )
        group_activity = boards.get("group_activity") or None
        target_hashes = {"group_activity": _digest(group_activity)}
        excerpt = {"raw_lesson_plan": raw}
    elif task_type == "daily_process_adapt":
        dumped = parse_adopted_content(content.adopted_content).model_dump(
            exclude_none=True
        )
        process = (dumped.get("group_activity") or {}).get("process")
        process = _require_non_empty(process, "活动过程")
        baseline_candidate_id, baseline = _baseline_reference(session, plan, content)
        payload = {"process_source": process, "grade": grade}
        dependencies = {
            "process_source": process,
            "grade": grade,
            "baseline_candidate_id": baseline_candidate_id,
            "split_baseline": baseline,
        }
        target_hashes = {"process": _digest(process)}
        excerpt = {
            "process": process,
            "baseline_candidate_id": baseline_candidate_id,
            "split_baseline": baseline,
        }
    else:  # daily_other_activities
        context, calendar_diagnostic = _calendar_context(
            session, plan, provider=holiday_provider
        )
        game_config, game_revision_id, game_payload_hash = _game_config(
            session, plan.class_id
        )
        snapshot, boards = _snapshot(content)
        payload = {
            "plan_date": plan.plan_date.isoformat(),
            "week_number": plan.week_number,
            "calendar_context": context,
            "game_config": game_config,
            "daily_plan_snapshot": snapshot,
            "target_grade": grade,
        }
        dependencies = {
            "plan_date": plan.plan_date.isoformat(),
            "week_number": plan.week_number,
            "weekday": plan.weekday,
            "target_grade": grade,
            "calendar_context": context,
            "game_revision_id": game_revision_id,
            "game_payload_hash": game_payload_hash,
            "game_config": game_config,
            "daily_plan_snapshot": snapshot,
        }
        target_hashes = {
            board: _digest(boards.get(board)) for board in _OTHER_BOARDS
        }
        excerpt = {
            "plan_date": plan.plan_date.isoformat(),
            "game_revision_id": game_revision_id,
            "holiday_context": context["holiday_context"],
        }
    clean = _validated(task_type, payload)
    business = business_dependency_view(dependencies)
    dependencies = dict(dependencies)
    if task_type == "daily_other_activities":
        dependencies["_diagnostics"] = calendar_diagnostic
    return ProjectedInput(
        task_type=task_type,
        target_grade=grade,
        payload=clean,
        dependencies=dependencies,
        # The fingerprint covers only the actually sent business values, so a
        # server-side coverage diagnostic never makes a candidate source-stale.
        dependency_hash=_digest(business),
        target_hashes=target_hashes,
        source_excerpt=excerpt,
    )


def business_dependency_view(dependencies: dict[str, Any]) -> dict[str, Any]:
    """The dependency object without server-side diagnostics (hash input)."""
    return {key: value for key, value in dependencies.items() if not key.startswith("_")}


def dependency_matches(
    session: Session,
    *,
    plan: LocalDailyPlan,
    content: LocalDailyPlanContent,
    input_row: Any,
    holiday_provider: HolidayProvider | None = None,
) -> bool:
    """True when the current plan/content still projects to this input's hash.

    The single shared source validator used by task claim/retry and by W4
    candidate applicability: only the actually sent business values matter, so
    an unrelated change (reflection, name, global config version) keeps the
    input valid while a real source change (raw text, process, calendar,
    game revision, boards) breaks it.
    """
    try:
        projected = project_input(
            session,
            plan=plan,
            content=content,
            task_type=input_row.task_type,
            target_grade=input_row.target_grade,
            holiday_provider=holiday_provider,
        )
    except (LocalValidationError, LocalStorageError, CandidateInvalid, ValueError):
        return False
    return projected.dependency_hash == input_row.dependency_hash


def source_excerpt(
    task_type: str,
    payload: dict[str, Any],
    dependencies: dict[str, Any],
) -> dict[str, Any]:
    """The minimal real source a candidate depends on, for candidate detail.

    Returned only through candidate detail (never a list or a log) and never
    carries another task's material: split -> raw lesson plan; adapt -> the
    current process plus the split-baseline source identity; other activities
    -> plan date / game revision / holiday window (no reflection, no names, no
    whole raw lesson plan).
    """
    payload = payload if isinstance(payload, dict) else {}
    dependencies = dependencies if isinstance(dependencies, dict) else {}
    if task_type == "daily_lesson_split":
        return {"raw_lesson_plan": payload.get("raw_lesson_plan")}
    if task_type == "daily_process_adapt":
        return {
            "process": payload.get("process_source"),
            "baseline_candidate_id": dependencies.get("baseline_candidate_id"),
            "split_baseline": dependencies.get("split_baseline"),
        }
    calendar = payload.get("calendar_context")
    holiday = calendar.get("holiday_context") if isinstance(calendar, dict) else None
    return {
        "plan_date": payload.get("plan_date"),
        "week_number": payload.get("week_number"),
        "target_grade": payload.get("target_grade"),
        # The actual activity / game-configuration material this candidate was
        # generated from, so a teacher can check what was really used (W4 R05).
        "calendar_context": calendar if isinstance(calendar, dict) else None,
        "game_revision_id": dependencies.get("game_revision_id"),
        "game_config": dependencies.get("game_config"),
        "daily_plan_snapshot": dependencies.get("daily_plan_snapshot"),
        "holiday_context": holiday if isinstance(holiday, list) else [],
    }


def calendar_coverage_warning(dependencies: dict[str, Any]) -> dict[str, Any] | None:
    """Safe, material-free warning when the holiday window is not fully known.

    Returns ``None`` for a fully covered window (nothing to warn about) and a
    small dict otherwise so a task detail can tell the teacher that a missing
    holiday entry does not mean there is no festival. Never carries lesson
    material, only dates / a coverage state / a fixed note.
    """
    diagnostics = dependencies.get("_diagnostics")
    if not isinstance(diagnostics, dict):
        return None
    window = diagnostics.get("holiday_window")
    if not isinstance(window, dict):
        return None
    coverage = window.get("coverage")
    if coverage not in ("partial", "unknown"):
        return None
    return {
        "coverage": coverage,
        "unknown_dates": list(window.get("unknown_dates") or []),
        "note": window.get("note") or "",
    }


__all__ = [
    "INPUT_SCHEMA_VERSION",
    "HOLIDAY_WINDOW_DAYS",
    "ProjectedInput",
    "business_dependency_view",
    "calendar_coverage_warning",
    "dependency_matches",
    "source_excerpt",
    "holiday_context",
    "project_input",
]
