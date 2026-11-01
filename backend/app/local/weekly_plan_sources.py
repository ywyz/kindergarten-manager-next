"""Trusted weekly-plan source snapshots (engineering spec §3.2/§11.2).

Only this module reads the database for weekly sources; the pure content
module (B) receives the materialized snapshot and never opens a session.
The snapshot covers the fixed Monday..Sunday window, the creator's saved
daily adopted content, the persisted calendar revision and the current class
game configuration.  Header names/caregiver and appearance preferences are
never part of ``source_context_hash``.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.local.errors import LocalStorageError, LocalValidationError, LocalWeeklyInvalid
from app.local.models import (
    LocalClass,
    LocalClassGameHead,
    LocalClassGameRevision,
    LocalDailyPlan,
    LocalDailyPlanContent,
    LocalTerm,
    LocalCalendarDay,
    LocalCalendarRevision,
)
from app.services import calendar_service as cal
from app.services.daily_plan_content import ContentValidationError, parse_adopted_content

DAY_STATES = ("teaching", "rest", "outside_term")
MAX_HEADER_TEACHER_NAMES = 100
MAX_HEADER_TEACHER_NAME_CHARS = 80
MAX_HEADER_TEACHER_NAMES_BYTES = 32 * 1024


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def hash_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def validate_header(header: Any) -> dict:
    if not isinstance(header, dict):
        raise LocalWeeklyInvalid("周计划表头必须是对象")
    if set(header) != {
        "school_name",
        "class_name",
        "grade",
        "header_teacher_names",
        "caregiver_name",
    }:
        raise LocalWeeklyInvalid("周计划表头字段不完整")
    names = header.get("header_teacher_names")
    if not isinstance(names, list) or len(names) > MAX_HEADER_TEACHER_NAMES:
        raise LocalWeeklyInvalid("表头教师名单不合法")
    normalized_names: list[str] = []
    for item in names:
        if not isinstance(item, str):
            raise LocalWeeklyInvalid("表头教师名单不合法")
        name = item.strip()
        if not (1 <= len(name) <= MAX_HEADER_TEACHER_NAME_CHARS):
            raise LocalWeeklyInvalid("表头教师名单不合法")
        if "\x00" in name:
            raise LocalWeeklyInvalid("表头教师名单不合法")
        normalized_names.append(name)
    if (
        len(canonical_json(normalized_names).encode("utf-8"))
        > MAX_HEADER_TEACHER_NAMES_BYTES
    ):
        raise LocalWeeklyInvalid("表头教师名单超过 32KiB")
    caregiver = header.get("caregiver_name")
    if caregiver is not None:
        if not isinstance(caregiver, str):
            raise LocalWeeklyInvalid("保育员姓名不合法")
        caregiver = caregiver.strip() or None
        if caregiver is not None and (
            len(caregiver) > 80 or "\x00" in caregiver
        ):
            raise LocalWeeklyInvalid("保育员姓名不合法")
    grade = header.get("grade")
    if grade not in ("small", "middle", "large"):
        raise LocalWeeklyInvalid("年级不合法")
    class_name = header.get("class_name")
    if not isinstance(class_name, str) or not (1 <= len(class_name) <= 80):
        raise LocalWeeklyInvalid("班级名称不合法")
    school_name = header.get("school_name")
    if school_name is not None and (
        not isinstance(school_name, str) or not (1 <= len(school_name) <= 120)
    ):
        raise LocalWeeklyInvalid("园所名称不合法")
    return {
        "school_name": school_name,
        "class_name": class_name,
        "grade": grade,
        "header_teacher_names": normalized_names,
        "caregiver_name": caregiver,
    }


def header_from_class(
    school_name: str | None, school_class: LocalClass
) -> dict:
    return validate_header(
        {
            "school_name": school_name,
            "class_name": school_class.name,
            "grade": school_class.grade,
            "header_teacher_names": list(
                school_class.header_teacher_names or ()
            ),
            "caregiver_name": school_class.caregiver_name,
        }
    )


def _week_dates(anchor: date) -> list[date]:
    return [anchor + timedelta(days=offset) for offset in range(7)]


def _game_context(session: Session, class_id: str) -> dict | None:
    head = session.get(LocalClassGameHead, class_id)
    if head is None:
        return None
    revision = session.get(LocalClassGameRevision, head.current_revision_id)
    if revision is None or revision.class_id != class_id:
        raise LocalStorageError("班级游戏配置修订缺失")
    return {
        "revision_id": revision.id,
        "revision_no": revision.revision_no,
    }


def _source_for_plan(
    session: Session, plan: LocalDailyPlan
) -> dict | None:
    content = session.get(
        LocalDailyPlanContent, plan.current_content_id, populate_existing=True
    )
    if (
        content is None
        or content.daily_plan_id != plan.id
        or content.version != plan.current_content_version
    ):
        raise LocalStorageError("日计划内容指针不一致")
    try:
        model = parse_adopted_content(content.adopted_content)
    except ContentValidationError:
        raise LocalStorageError("日计划内容持久数据损坏") from None
    adopted = model.model_dump(exclude_none=True)
    talk = adopted.get("morning_talk") or {}
    activity = adopted.get("group_activity") or {}
    return {
        "daily_plan_id": plan.id,
        "content_id": content.id,
        "content_version": content.version,
        "content_hash": hash_json(adopted),
        "morning_talk_topic": talk.get("topic"),
        "group_activity_theme": activity.get("theme"),
    }


def _morning_groups(adopted: dict) -> list[dict]:
    groups: list[dict] = []
    for group in adopted.get("morning_games") or []:
        groups.append(
            {
                "group_id": group.get("group_id"),
                "group_kind": group.get("group_kind"),
                "games": [
                    {"game_id": game.get("game_id"), "name": game.get("name")}
                    for game in group.get("games") or []
                ],
                "shared_objectives": group.get("shared_objectives"),
                "guidance_points": group.get("guidance_points"),
                "focus_guidance": group.get("focus_guidance"),
            }
        )
    return groups


def _post_group_groups(adopted: dict) -> list[dict]:
    groups: list[dict] = []
    for group in adopted.get("post_group_games") or []:
        groups.append(
            {
                "group_id": group.get("group_id"),
                "context_kind": group.get("context_kind"),
                "area": group.get("area"),
                "games": [
                    {"game_id": game.get("game_id"), "name": game.get("name")}
                    for game in group.get("games") or []
                ],
                "objectives": group.get("objectives"),
                "guidance": group.get("guidance"),
                "support_strategy": group.get("support_strategy"),
            }
        )
    return groups


def _day_rows(
    session: Session, term_id: str, revision_id: str
) -> dict[date, LocalCalendarDay]:
    revision = session.get(LocalCalendarRevision, revision_id)
    if revision is None or revision.term_id != term_id:
        raise LocalStorageError("周计划日历修订缺失或不属于该学期")
    rows = session.scalars(
        select(LocalCalendarDay).where(
            LocalCalendarDay.revision_id == revision_id
        )
    ).all()
    return {row.date: row for row in rows}


def _game_projection(
    session: Session, class_id: str, days: list[dict]
) -> dict:
    """Only the class-game locations actually referenced by this week."""
    head = session.get(LocalClassGameHead, class_id)
    if head is None:
        return {"locations": []}
    revision = session.get(LocalClassGameRevision, head.current_revision_id)
    if revision is None or revision.class_id != class_id:
        raise LocalStorageError("班级游戏配置修订缺失")
    payload = dict(revision.payload_json)
    locations = list(payload.get("locations") or [])
    referenced: dict[tuple[str, str], dict] = {}
    for day in days:
        for group in day["post_group_groups"]:
            kind = group.get("context_kind")
            area = (group.get("area") or "").strip()
            if not area:
                continue
            for location in locations:
                if (
                    location.get("kind") == kind
                    and (location.get("name") or "").strip() == area
                ):
                    referenced[(kind, area)] = {
                        "kind": kind,
                        "name": area,
                        "guidance": location.get("guidance"),
                    }
    projection: dict = {
        "locations": [
            referenced[key] for key in sorted(referenced, key=lambda item: (item[0], item[1]))
        ]
    }
    if projection["locations"]:
        projection["game_scope"] = payload.get("game_scope")
        projection["guidance"] = payload.get("guidance")
    return projection


def source_context_hash(
    *,
    profile_id: str,
    class_id: str,
    term_id: str,
    week_anchor_date: str,
    week_number: int,
    term_start: str,
    term_end: str,
    calendar_revision_id: str,
    days: list[dict],
    game_projection: dict,
) -> str:
    """Exact shared production hash for the live source context."""
    return hash_json(
        {
            "profile_id": profile_id,
            "class_id": class_id,
            "term_id": term_id,
            "week_anchor_date": week_anchor_date,
            "week_number": week_number,
            "term_start": term_start,
            "term_end": term_end,
            "calendar_revision_id": calendar_revision_id,
            "game_projection": game_projection,
            "days": [
                {
                    "date": item["date"],
                    "day_state": item["day_state"],
                    "source_state": item["source_state"],
                    "source": item["source"],
                }
                for item in days
            ],
        }
    )


def load_source_snapshot(
    session: Session,
    *,
    profile_id: str,
    class_id: str,
    term_id: str,
    week_anchor_date: date,
    calendar_revision_id: str,
    term_start: date,
    term_end: date,
    week_number: int,
    header: dict,
    config_version: int,
    include_sources: bool = True,
) -> dict:
    """Materialize one trusted snapshot for the fixed 7-day week."""
    if week_anchor_date.isoweekday() != 1:
        raise LocalValidationError("周起始日期必须是周一")
    if not (term_start <= term_end):
        raise LocalStorageError("周计划学期范围损坏")
    header = validate_header(header)
    days_rows = _day_rows(session, term_id, calendar_revision_id)
    days: list[dict] = []
    for day in _week_dates(week_anchor_date):
        if day < term_start or day > term_end:
            day_state = "outside_term"
        else:
            row = days_rows.get(day)
            if row is None:
                raise LocalStorageError("日历修订缺少目标日期")
            day_state = (
                "teaching" if row.effective_state == "teaching" else "rest"
            )
        plan = None
        if include_sources and day_state == "teaching":
            plan = session.scalars(
                select(LocalDailyPlan).where(
                    LocalDailyPlan.class_id == class_id,
                    LocalDailyPlan.term_id == term_id,
                    LocalDailyPlan.creator_id == profile_id,
                    LocalDailyPlan.plan_date == day,
                    LocalDailyPlan.deleted_at.is_(None),
                )
            ).first()
        if plan is not None:
            source_state = "saved"
            source = _source_for_plan(session, plan)
            content = session.get(
                LocalDailyPlanContent, plan.current_content_id,
                populate_existing=True,
            )
            if content is None:
                raise LocalStorageError("日计划内容指针不一致")
            try:
                adopted = parse_adopted_content(
                    content.adopted_content
                ).model_dump(exclude_none=True)
            except ContentValidationError:
                raise LocalStorageError("日计划内容持久数据损坏") from None
            morning_groups = _morning_groups(adopted)
            post_groups = _post_group_groups(adopted)
        elif day_state == "teaching":
            source_state = "no_plan"
            source = None
            morning_groups = []
            post_groups = []
        else:
            source_state = "none_required"
            source = None
            morning_groups = []
            post_groups = []
        days.append(
            {
                "date": day.isoformat(),
                "day_state": day_state,
                "source_state": source_state,
                "source": source,
                "morning_groups": morning_groups,
                "post_group_groups": post_groups,
            }
        )
    game_context = _game_context(session, class_id)
    game_projection = _game_projection(session, class_id, days)
    source_hash = source_context_hash(
        profile_id=profile_id,
        class_id=class_id,
        term_id=term_id,
        week_anchor_date=week_anchor_date.isoformat(),
        week_number=week_number,
        term_start=term_start.isoformat(),
        term_end=term_end.isoformat(),
        calendar_revision_id=calendar_revision_id,
        days=days,
        game_projection=game_projection,
    )
    return {
        "profile_id": profile_id,
        "class_id": class_id,
        "term_id": term_id,
        "week_anchor_date": week_anchor_date.isoformat(),
        "week_number": week_number,
        "term_start": term_start.isoformat(),
        "term_end": term_end.isoformat(),
        "calendar_revision_id": calendar_revision_id,
        "config_version": config_version,
        "game_context": game_context,
        "header": header,
        "source_context_hash": source_hash,
        "days": days,
    }
