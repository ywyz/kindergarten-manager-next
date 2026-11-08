"""Shared weekly-plan reads, saves, confirmations and operation receipts.

Authorization is always the actor's current same-school/class membership.
Writes lock the teacher and class first, then the weekly row/confirmation
rows, and recheck membership before changing anything.  Only the shared
morning-talk, group-activity and game-slot names/dates are stored here.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from .class_promotion_models import (
    ClassPromotionState,
    CollaborationTerm,
    latest_grade_at_date,
    make_class_name,
)
from .errors import (
    CollaborationError,
    class_not_found,
    membership_changed,
    membership_required,
    operation_not_found,
    request_conflict,
)
from .models import Classroom
from .security import TeacherPrincipal
from .service import _lock_class, _lock_teachers, _membership
from .weekly_plan_models import (
    WeeklyPlanConfirmation,
    WeeklyPlanOperation,
    WeeklyPlanWeek,
)

GAME_KEYS = ("collective_1", "collective_2", "free_choice_1", "focus_area")
DAY_KEYS = ("date", "morning_talk_topic", "group_activity_theme")
MAX_DAY_TEXT = 2000
MAX_GAME_NAME = 200


def empty_content() -> dict:
    return {"days": [], "games": {key: None for key in GAME_KEYS}}


@dataclass(frozen=True)
class WeekContext:
    class_id: UUID
    school_id: UUID
    term_id: UUID
    week_start: date
    first_date: date
    range_start: date
    range_end: date
    class_name: str
    term_name: str
    grade: str


def invalid_weekly(message: str) -> CollaborationError:
    return CollaborationError(422, "WEEKLY_PLAN_INVALID", message)


def weekly_version_conflict(current_version: int) -> CollaborationError:
    return CollaborationError(
        409,
        "WEEKLY_PLAN_VERSION_CONFLICT",
        "共享周计划版本已变化，请重新读取后再操作",
        details={"current_version": int(current_version)},
    )


def weekly_not_saved() -> CollaborationError:
    return CollaborationError(
        409,
        "WEEKLY_PLAN_NOT_SAVED",
        "该周还没有可确认的已保存共享版本",
    )


def confirmation_not_found() -> CollaborationError:
    return CollaborationError(
        404,
        "CONFIRMATION_NOT_FOUND",
        "没有找到该确认版本",
    )


def class_not_ready() -> CollaborationError:
    return CollaborationError(
        409,
        "CLASS_PROMOTION_NOT_READY",
        "该班级尚未登记年级和班号，请联系部署方",
    )


def _as_date(value: object) -> date:
    if isinstance(value, datetime):
        raise invalid_weekly("日期必须是 YYYY-MM-DD")
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise invalid_weekly("日期必须是 YYYY-MM-DD")


def _optional_text(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or "\x00" in value:
        raise invalid_weekly(f"{field} 必须是字符串或 null")
    text = value.strip()
    if not text:
        return None
    if len(text) > MAX_DAY_TEXT:
        raise invalid_weekly(f"{field} 最多 {MAX_DAY_TEXT} 个字符")
    return text


def normalize_content(content: object) -> dict:
    if not isinstance(content, Mapping):
        raise invalid_weekly("content 必须是对象")
    if set(content) != {"days", "games"}:
        raise invalid_weekly("content 只能包含 days 和 games")
    raw_days = content.get("days")
    if not isinstance(raw_days, list):
        raise invalid_weekly("days 必须是列表")
    if len(raw_days) > 7:
        raise invalid_weekly("一周最多 7 个日项")
    days: list[dict] = []
    seen: set[date] = set()
    for item in raw_days:
        if (
            not isinstance(item, Mapping)
            or "date" not in item
            or not set(item).issubset(DAY_KEYS)
        ):
            raise invalid_weekly("日项只能包含 date、morning_talk_topic、group_activity_theme")
        day = _as_date(item.get("date"))
        if day in seen:
            raise invalid_weekly("日项日期不得重复")
        seen.add(day)
        days.append(
            {
                "date": day.isoformat(),
                "morning_talk_topic": _optional_text(
                    item.get("morning_talk_topic"),
                    "morning_talk_topic",
                ),
                "group_activity_theme": _optional_text(
                    item.get("group_activity_theme"),
                    "group_activity_theme",
                ),
            }
        )
    days.sort(key=lambda item: item["date"])

    raw_games = content.get("games")
    if not isinstance(raw_games, Mapping):
        raise invalid_weekly("games 必须是对象")
    if not set(raw_games).issubset(GAME_KEYS):
        raise invalid_weekly(
            "games 只能包含 collective_1、collective_2、free_choice_1、focus_area"
        )
    games: dict[str, dict | None] = {}
    for key in GAME_KEYS:
        raw = raw_games.get(key)
        if raw is None:
            games[key] = None
            continue
        if (
            not isinstance(raw, Mapping)
            or "name" not in raw
            or not set(raw).issubset({"name", "date"})
        ):
            raise invalid_weekly("游戏槽只能包含 name 和 date")
        name = raw.get("name")
        if not isinstance(name, str) or "\x00" in name:
            raise invalid_weekly("游戏名称必须是字符串")
        name = name.strip()
        if not (1 <= len(name) <= MAX_GAME_NAME):
            raise invalid_weekly(f"游戏名称长度必须为 1–{MAX_GAME_NAME} 个字符")
        game_date = raw.get("date")
        games[key] = {
            "name": name,
            "date": None if game_date is None else _as_date(game_date).isoformat(),
        }
    return {"days": days, "games": games}


def validate_content_window(
    content: Mapping[str, Any],
    context: WeekContext,
) -> None:
    for day in content["days"]:
        day_date = _as_date(day["date"])
        if not (context.range_start <= day_date <= context.range_end):
            raise invalid_weekly("日项日期必须在所属学期和本周范围内")
    for key in GAME_KEYS:
        slot = content["games"].get(key)
        if slot is None or slot.get("date") is None:
            continue
        slot_date = _as_date(slot["date"])
        if not (context.range_start <= slot_date <= context.range_end):
            raise invalid_weekly("游戏日期必须在所属学期和本周范围内")


def _context(
    session: Session,
    principal: TeacherPrincipal,
    class_id: UUID,
    term_id: UUID,
    week_start: object,
    *,
    lock: bool,
) -> WeekContext:
    week = _as_date(week_start)
    if week.weekday() != 0:
        raise invalid_weekly("week_start 必须是 ISO 周一")
    if lock:
        _lock_teachers(session, [principal.teacher_id])
        class_row = _lock_class(session, principal.school_id, class_id)
    else:
        class_row = session.get(Classroom, class_id)
        if class_row is None or class_row.school_id != principal.school_id:
            raise class_not_found()
    membership = _membership(session, principal.teacher_id)
    if membership is None:
        raise membership_required()
    if (
        membership.school_id != principal.school_id
        or membership.class_id != class_id
    ):
        raise membership_changed()

    term = session.get(CollaborationTerm, term_id)
    if term is None or term.school_id != principal.school_id:
        raise CollaborationError(404, "TERM_NOT_FOUND", "没有找到该学期")
    week_end = week + timedelta(days=6)
    if week > term.end_date or week_end < term.start_date:
        raise invalid_weekly("本周与学期范围没有交集")
    state = session.get(ClassPromotionState, class_id)
    if state is None:
        raise class_not_ready()
    first_date = max(week, term.start_date)
    grade = latest_grade_at_date(session, class_id, first_date)
    if grade is None:
        raise class_not_ready()
    class_name = make_class_name(grade, state.class_number)
    return WeekContext(
        class_id=class_id,
        school_id=principal.school_id,
        term_id=term_id,
        week_start=week,
        first_date=first_date,
        range_start=max(week, term.start_date),
        range_end=min(week_end, term.end_date),
        class_name=class_name,
        term_name=term.name,
        grade=grade,
    )


def _week(
    session: Session,
    context: WeekContext,
    *,
    for_update: bool = False,
) -> WeeklyPlanWeek | None:
    query = select(WeeklyPlanWeek).where(
        WeeklyPlanWeek.class_id == context.class_id,
        WeeklyPlanWeek.term_id == context.term_id,
        WeeklyPlanWeek.week_start == context.week_start,
    )
    if for_update:
        query = query.with_for_update()
    return session.scalars(query).one_or_none()


def _latest_confirmation(
    session: Session,
    context: WeekContext,
    *,
    for_update: bool = False,
    max_saved_version: int | None = None,
) -> WeeklyPlanConfirmation | None:
    query = (
        select(WeeklyPlanConfirmation)
        .where(
            WeeklyPlanConfirmation.class_id == context.class_id,
            WeeklyPlanConfirmation.term_id == context.term_id,
            WeeklyPlanConfirmation.week_start == context.week_start,
        )
        .order_by(WeeklyPlanConfirmation.confirmation_version.desc())
        .limit(1)
    )
    if max_saved_version is not None:
        query = query.where(
            WeeklyPlanConfirmation.version <= max_saved_version
        )
    if for_update:
        query = query.with_for_update()
    return session.scalars(query).one_or_none()


def _confirmation(row: WeeklyPlanConfirmation) -> dict:
    return {
        "confirmation_id": str(row.id),
        "confirmation_version": row.confirmation_version,
        "version": row.version,
        "class_id": str(row.class_id),
        "term_id": str(row.term_id),
        "week_start": row.week_start.isoformat(),
        "class_name": row.class_name,
        "grade": row.grade,
        "term_name": row.term_name,
        "content": row.content,
        "confirmed_by": str(row.confirmed_by),
        "confirmed_at": row.confirmed_at.isoformat(),
    }


def _read_payload(
    context: WeekContext,
    week: WeeklyPlanWeek | None,
    confirmation: WeeklyPlanConfirmation | None,
) -> dict:
    return {
        "class_id": str(context.class_id),
        "term_id": str(context.term_id),
        "week_start": context.week_start.isoformat(),
        "class_name": context.class_name,
        "term_name": context.term_name,
        "version": week.version if week is not None else 0,
        "content": week.content if week is not None else empty_content(),
        "confirmation": (
            _confirmation(confirmation) if confirmation is not None else None
        ),
    }


def _operation(
    session: Session,
    principal: TeacherPrincipal,
    request_id: UUID,
) -> WeeklyPlanOperation | None:
    return session.scalars(
        select(WeeklyPlanOperation)
        .where(
            WeeklyPlanOperation.actor_teacher_id == principal.teacher_id,
            WeeklyPlanOperation.request_id == request_id,
        )
        .with_for_update()
    ).one_or_none()


def _fingerprint(
    *,
    kind: str,
    request_id: UUID,
    principal: TeacherPrincipal,
    context: WeekContext,
    expected_version: int,
    content: Mapping[str, Any] | None,
) -> str:
    payload: dict[str, Any] = {
        "kind": kind,
        "request_id": str(request_id),
        "actor_teacher_id": str(principal.teacher_id),
        "school_id": str(principal.school_id),
        "class_id": str(context.class_id),
        "term_id": str(context.term_id),
        "week_start": context.week_start.isoformat(),
        "expected_version": int(expected_version),
    }
    if content is not None:
        payload["content"] = content
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def get_weekly_plan(
    session: Session,
    principal: TeacherPrincipal,
    class_id: UUID,
    term_id: UUID,
    week_start: object,
) -> dict:
    context = _context(
        session, principal, class_id, term_id, week_start, lock=False
    )
    week = _week(session, context)
    # Cap the confirmation at the draft version read above.  A concurrent
    # save/confirm that commits between these two statements must not make
    # this response pair a draft with a confirmation from its future.
    confirmation = (
        _latest_confirmation(
            session, context, max_saved_version=week.version
        )
        if week is not None and week.version > 0
        else None
    )
    return _read_payload(context, week, confirmation)


def save_weekly_plan(
    session: Session,
    principal: TeacherPrincipal,
    class_id: UUID,
    term_id: UUID,
    week_start: object,
    *,
    request_id: UUID,
    expected_version: int,
    content: object,
) -> dict:
    if expected_version < 0:
        raise invalid_weekly("expected_version 不得小于 0")
    normalized = normalize_content(content)
    with session.begin():
        context = _context(
            session, principal, class_id, term_id, week_start, lock=True
        )
        validate_content_window(normalized, context)
        fingerprint = _fingerprint(
            kind="save",
            request_id=request_id,
            principal=principal,
            context=context,
            expected_version=expected_version,
            content=normalized,
        )
        existing = _operation(session, principal, request_id)
        if existing is not None:
            if (
                existing.request_fingerprint != fingerprint
                or existing.class_id != context.class_id
                or existing.term_id != context.term_id
                or existing.week_start != context.week_start
                or existing.school_id != context.school_id
            ):
                raise request_conflict()
            result = dict(existing.result_json)
            result["replayed"] = True
            return result

        week = _week(session, context, for_update=True)
        current_version = week.version if week is not None else 0
        if current_version != expected_version:
            raise weekly_version_conflict(current_version)
        new_version = current_version + 1
        now = datetime.now(timezone.utc)
        if week is None:
            week = WeeklyPlanWeek(
                class_id=context.class_id,
                term_id=context.term_id,
                week_start=context.week_start,
                school_id=context.school_id,
                version=new_version,
                content=normalized,
                updated_at=now,
            )
            session.add(week)
        else:
            week.version = new_version
            week.content = normalized
            week.updated_at = now
        confirmation = _latest_confirmation(session, context)
        result = _read_payload(context, week, confirmation)
        result["request_id"] = str(request_id)
        result["replayed"] = False
        session.add(
            WeeklyPlanOperation(
                actor_teacher_id=principal.teacher_id,
                request_id=request_id,
                school_id=context.school_id,
                class_id=context.class_id,
                term_id=context.term_id,
                week_start=context.week_start,
                kind="save",
                request_fingerprint=fingerprint,
                result_json=result,
                created_at=now,
            )
        )
        session.flush()
        return result


def confirm_weekly_plan(
    session: Session,
    principal: TeacherPrincipal,
    class_id: UUID,
    term_id: UUID,
    week_start: object,
    *,
    request_id: UUID,
    expected_version: int,
) -> dict:
    if expected_version < 0:
        raise invalid_weekly("expected_version 不得小于 0")
    with session.begin():
        context = _context(
            session, principal, class_id, term_id, week_start, lock=True
        )
        fingerprint = _fingerprint(
            kind="confirm",
            request_id=request_id,
            principal=principal,
            context=context,
            expected_version=expected_version,
            content=None,
        )
        existing_operation = _operation(session, principal, request_id)
        if existing_operation is not None:
            if (
                existing_operation.request_fingerprint != fingerprint
                or existing_operation.class_id != context.class_id
                or existing_operation.term_id != context.term_id
                or existing_operation.week_start != context.week_start
                or existing_operation.school_id != context.school_id
            ):
                raise request_conflict()
            result = dict(existing_operation.result_json)
            result["replayed"] = True
            return result

        week = _week(session, context, for_update=True)
        if week is None or week.version == 0:
            raise weekly_not_saved()
        if week.version != expected_version:
            raise weekly_version_conflict(week.version)
        existing = session.scalars(
            select(WeeklyPlanConfirmation)
            .where(
                WeeklyPlanConfirmation.class_id == context.class_id,
                WeeklyPlanConfirmation.term_id == context.term_id,
                WeeklyPlanConfirmation.week_start == context.week_start,
                WeeklyPlanConfirmation.version == week.version,
            )
            .with_for_update()
        ).one_or_none()
        if existing is not None:
            result = _confirmation(existing)
            result["request_id"] = str(request_id)
            result["replayed"] = True
            session.add(
                WeeklyPlanOperation(
                    actor_teacher_id=principal.teacher_id,
                    request_id=request_id,
                    school_id=context.school_id,
                    class_id=context.class_id,
                    term_id=context.term_id,
                    week_start=context.week_start,
                    kind="confirm",
                    request_fingerprint=fingerprint,
                    result_json=result,
                    created_at=datetime.now(timezone.utc),
                )
            )
            session.flush()
            return result

        next_version = (
            session.scalars(
                select(WeeklyPlanConfirmation.confirmation_version)
                .where(
                    WeeklyPlanConfirmation.class_id == context.class_id,
                    WeeklyPlanConfirmation.term_id == context.term_id,
                    WeeklyPlanConfirmation.week_start == context.week_start,
                )
                .order_by(WeeklyPlanConfirmation.confirmation_version.desc())
                .limit(1)
            ).one_or_none()
            or 0
        ) + 1
        now = datetime.now(timezone.utc)
        confirmation = WeeklyPlanConfirmation(
            id=uuid4(),
            class_id=context.class_id,
            school_id=context.school_id,
            term_id=context.term_id,
            week_start=context.week_start,
            confirmation_version=next_version,
            version=week.version,
            class_name=context.class_name,
            grade=context.grade,
            term_name=context.term_name,
            content=week.content,
            confirmed_by=principal.teacher_id,
            confirmed_at=now,
        )
        session.add(confirmation)
        session.flush()
        result = _confirmation(confirmation)
        result["request_id"] = str(request_id)
        result["replayed"] = False
        session.add(
            WeeklyPlanOperation(
                actor_teacher_id=principal.teacher_id,
                request_id=request_id,
                school_id=context.school_id,
                class_id=context.class_id,
                term_id=context.term_id,
                week_start=context.week_start,
                kind="confirm",
                request_fingerprint=fingerprint,
                result_json=result,
                created_at=now,
            )
        )
        session.flush()
        return result


def get_confirmation(
    session: Session,
    principal: TeacherPrincipal,
    class_id: UUID,
    term_id: UUID,
    week_start: object,
    confirmation_id: UUID,
) -> dict:
    context = _context(
        session, principal, class_id, term_id, week_start, lock=False
    )
    row = session.get(WeeklyPlanConfirmation, confirmation_id)
    if (
        row is None
        or row.school_id != context.school_id
        or row.class_id != context.class_id
        or row.term_id != context.term_id
        or row.week_start != context.week_start
    ):
        raise confirmation_not_found()
    return _confirmation(row)


def get_operation(
    session: Session,
    principal: TeacherPrincipal,
    class_id: UUID,
    term_id: UUID,
    week_start: object,
    request_id: UUID,
) -> dict:
    context = _context(
        session, principal, class_id, term_id, week_start, lock=False
    )
    row = session.scalars(
        select(WeeklyPlanOperation).where(
            WeeklyPlanOperation.actor_teacher_id == principal.teacher_id,
            WeeklyPlanOperation.request_id == request_id,
        )
    ).one_or_none()
    if (
        row is None
        or row.school_id != context.school_id
        or row.class_id != context.class_id
        or row.term_id != context.term_id
        or row.week_start != context.week_start
    ):
        raise operation_not_found()
    return {
        "request_id": str(row.request_id),
        "kind": row.kind,
        "result": row.result_json,
    }
