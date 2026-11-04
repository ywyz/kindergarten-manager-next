"""Trusted weekly AI source assembly (A).

The model never receives these identities.  A builds one frozen raw manifest
from the saved weekly draft, the maker's saved daily plans, the current class
game configuration and the fixed plan calendar.  B's pure projection strips
identities and assigns input-local handles.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from typing import Any, Mapping

from sqlalchemy.orm import Session

from app.local import ai_inputs, weekly_plan_sources
from app.local.errors import LocalStorageError
from app.local.models import (
    LocalCalendarRevision,
    LocalClassGameHead,
    LocalClassGameRevision,
    LocalDailyPlan,
    LocalDailyPlanContent,
    LocalSettings,
    LocalTerm,
    LocalWeeklyPlan,
    LocalWeeklyPlanContent,
)
from app.local.tx import read_scope
from app.services.daily_plan_content import parse_adopted_content


def _canonical(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def raw_manifest_hash(raw: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(raw).encode("utf-8")).hexdigest()


def load_class_game_config(session: Session, *, class_id: str) -> dict[str, Any]:
    head = session.get(LocalClassGameHead, class_id)
    if head is None:
        return {
            "revision_id": "0" * 32,
            "revision_no": 1,
            "locations": [],
            "game_scope": None,
            "guidance": None,
        }
    revision = session.get(LocalClassGameRevision, head.current_revision_id)
    if revision is None or revision.class_id != class_id:
        raise ValueError("班级游戏配置修订缺失")
    payload = dict(revision.payload_json or {})
    counts: dict[tuple[str, str], int] = {}
    locations: list[dict[str, Any]] = []
    for item in payload.get("locations") or []:
        kind = str(item.get("kind") or "")
        name = str(item.get("name") or "")
        key = (kind, name)
        counts[key] = counts.get(key, 0) + 1
        locations.append(
            {
                "kind": kind,
                "name": name,
                "occurrence": counts[key],
                "guidance": item.get("guidance"),
            }
        )
    locations.sort(key=lambda x: (x["kind"], x["name"], x["occurrence"]))
    return {
        "revision_id": revision.id,
        "revision_no": revision.revision_no,
        "locations": locations,
        "game_scope": payload.get("game_scope"),
        "guidance": payload.get("guidance"),
    }


def _current_term_context(
    session: Session, plan: LocalWeeklyPlan
) -> tuple[LocalTerm, LocalCalendarRevision]:
    """Resolve the term/revision currently used by normal weekly source refresh."""
    term = session.get(LocalTerm, plan.term_id)
    if term is None:
        raise LocalStorageError("周计划所属学期缺失")
    revision_id = term.current_calendar_revision_id
    if revision_id is None:
        raise LocalStorageError("学期缺少当前日历修订")
    revision = session.get(LocalCalendarRevision, revision_id)
    if revision is None or revision.term_id != term.id:
        raise LocalStorageError("当前日历修订缺失")
    return term, revision


def load_calendar_window(
    session: Session, *, plan: LocalWeeklyPlan, holiday_provider=None
) -> dict[str, Any]:
    term, revision = _current_term_context(session, plan)
    start = plan.week_anchor_date - timedelta(days=7)
    end = plan.week_anchor_date + timedelta(days=13)
    facts, coverage = ai_inputs.holiday_context(start, end, provider=holiday_provider)
    by_date: dict[str, list[str]] = {}
    for item in facts:
        by_date.setdefault(item["date"], []).append(item["name"])
    unknown = set(coverage.get("unknown_dates") or [])
    days: list[dict[str, Any]] = []
    day = start
    from app.local.models import LocalCalendarDay

    while day <= end:
        outside = day < term.start_date or day > term.end_date
        if outside:
            state = "outside_term"
        else:
            row = session.get(LocalCalendarDay, (revision.id, day))
            state = (
                "teaching"
                if row is not None and row.effective_state == "teaching"
                else ("rest" if row is not None else "unknown")
            )
        names = sorted(set(by_date.get(day.isoformat(), [])))
        days.append(
            {
                "date": day.isoformat(),
                "day_state": state,
                "holiday_names": names,
                "coverage": "unknown"
                if outside or day.isoformat() in unknown
                else "known",
            }
        )
        day += timedelta(days=1)
    return {"start": start.isoformat(), "end": end.isoformat(), "days": days}


def _full_source(
    session: Session, source: Mapping[str, Any] | None
) -> dict[str, Any] | None:
    if source is None:
        return None
    result = {
        "daily_plan_id": source["daily_plan_id"],
        "content_id": source["content_id"],
        "content_version": source["content_version"],
        "content_hash": source["content_hash"],
        "morning_talk_topic": source.get("morning_talk_topic"),
        "group_activity_theme": source.get("group_activity_theme"),
        "group_activity_objectives": None,
        "group_activity_process": None,
    }
    content = session.get(
        LocalDailyPlanContent, source["content_id"], populate_existing=True
    )
    if content is not None and content.daily_plan_id == source["daily_plan_id"]:
        try:
            adopted = parse_adopted_content(content.adopted_content).model_dump(
                exclude_none=True
            )
        except Exception:
            return result
        activity = adopted.get("group_activity") or {}
        result["group_activity_objectives"] = activity.get("objectives")
        result["group_activity_process"] = activity.get("process")
    return result


def load_raw_manifest(
    session: Session,
    *,
    plan: LocalWeeklyPlan,
    content: LocalWeeklyPlanContent,
    holiday_provider=None,
) -> dict[str, Any]:
    settings = session.get(LocalSettings, "singleton")
    if settings is None:
        raise ValueError("本地设置缺失")
    term, revision = _current_term_context(session, plan)
    snapshot = weekly_plan_sources.load_source_snapshot(
        session,
        profile_id=plan.profile_id,
        class_id=plan.class_id,
        term_id=plan.term_id,
        week_anchor_date=plan.week_anchor_date,
        calendar_revision_id=revision.id,
        term_start=term.start_date,
        term_end=term.end_date,
        week_number=plan.week_number_snapshot,
        header=plan.header_json,
        config_version=settings.config_version,
    )
    days: list[dict[str, Any]] = []
    for day in snapshot["days"]:
        days.append(
            {
                "date": day["date"],
                "day_state": day["day_state"],
                "source_state": day["source_state"],
                "source": _full_source(session, day["source"]),
                "morning_groups": day["morning_groups"],
                "post_group_groups": day["post_group_groups"],
            }
        )
    config = load_class_game_config(session, class_id=plan.class_id)
    calendar = load_calendar_window(
        session, plan=plan, holiday_provider=holiday_provider
    )
    return {
        "schema_version": 1,
        "contract_version": 1,
        "source_kind": "weekly_plan",
        "profile_id": plan.profile_id,
        "class_id": plan.class_id,
        "term_id": plan.term_id,
        "weekly_plan_id": plan.id,
        "draft_id": content.id,
        "draft_version": content.version,
        "content_hash": content.content_hash,
        "week_anchor_date": plan.week_anchor_date.isoformat(),
        "week_number": plan.week_number_snapshot,
        "term_start": term.start_date.isoformat(),
        "term_end": term.end_date.isoformat(),
        "calendar_revision_id": revision.id,
        "config_version": settings.config_version,
        "header": plan.header_json,
        "source_context_hash": snapshot["source_context_hash"],
        "days": days,
        "calendar_window": calendar,
        "game_config": config,
    }


__all__ = [
    "load_calendar_window",
    "load_class_game_config",
    "load_raw_manifest",
    "raw_manifest_hash",
]
