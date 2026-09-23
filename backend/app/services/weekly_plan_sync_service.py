"""Weekly pending-projection state (option A read state, not a task table).

``weekly_plan_sync_states`` is recomputed from ALL effective daily plans of
the class/term/week on every create/save, inside the caller's transaction.
It never decides the creator/owner of a real weekly plan and never
references tables that do not exist yet.
"""

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import security
from app.models import DailyPlan, DailyPlanContent, WeeklyPlanSyncState


class WeeklySyncDataError(Exception):
    """Incomplete plan/content pointer inside the recomputed week (503)."""


@dataclass(frozen=True, slots=True)
class WeekPlanEntry:
    plan_id: str
    content_id: str
    content_version: int
    plan_date: date
    adopted_content: dict


def _sorted_entries(entries) -> list[WeekPlanEntry]:
    return sorted(entries, key=lambda e: (e.plan_date, e.plan_id))


def build_deterministic_themes(entries) -> list[dict]:
    themes: list[dict] = []
    for entry in _sorted_entries(entries):
        content = entry.adopted_content or {}
        talk = content.get("morning_talk") or {}
        activity = content.get("group_activity") or {}
        themes.append(
            {
                "date": entry.plan_date.isoformat(),
                "morning_talk_topic": talk.get("topic") or "",
                "group_activity_theme": activity.get("theme") or "",
            }
        )
    return themes


def build_game_source_manifest(entries) -> list[dict]:
    manifest: list[dict] = []
    for entry in _sorted_entries(entries):
        content = entry.adopted_content or {}
        groups: list[dict] = []
        for section in ("morning_games", "post_group_games"):
            for group in content.get(section) or []:
                if isinstance(group, dict):
                    groups.append(group)
        afternoon = content.get("afternoon_outdoor")
        if isinstance(afternoon, dict):
            groups.append(afternoon)
        for group in groups:
            for game in group.get("games") or []:
                if not isinstance(game, dict):
                    continue
                context_kind = group.get("context_kind")
                manifest.append(
                    {
                        "daily_plan_id": entry.plan_id,
                        "content_version": entry.content_version,
                        "date": entry.plan_date.isoformat(),
                        "group_id": group.get("group_id"),
                        "game_id": game.get("game_id"),
                        "context_kind": (
                            context_kind
                            if isinstance(context_kind, str)
                            else None
                        ),
                    }
                )
    return manifest


def build_current_week_source_manifest(entries) -> list[dict]:
    return [
        {
            "daily_plan_id": entry.plan_id,
            "current_content_id": entry.content_id,
            "current_content_version": entry.content_version,
            "date": entry.plan_date.isoformat(),
        }
        for entry in _sorted_entries(entries)
    ]


def load_week_entries(
    db: Session,
    class_id: str,
    term_id: str,
    week_number: int,
    *,
    for_update: bool = False,
) -> list[WeekPlanEntry]:
    stmt = (
        select(DailyPlan)
        .where(
            DailyPlan.class_id == class_id,
            DailyPlan.term_id == term_id,
            DailyPlan.week_number == week_number,
            DailyPlan.deleted_at.is_(None),
        )
        .order_by(DailyPlan.plan_date, DailyPlan.id)
    )
    if for_update:
        stmt = stmt.with_for_update()
    plans = list(db.scalars(stmt).all())
    if not plans:
        return []

    content_ids = [plan.current_content_id for plan in plans]
    if any(content_id is None for content_id in content_ids):
        raise WeeklySyncDataError("daily plan has no current content pointer")

    content_stmt = select(DailyPlanContent).where(
        DailyPlanContent.id.in_(content_ids)
    )
    if for_update:
        content_stmt = content_stmt.with_for_update()
    content_rows = db.scalars(content_stmt).all()
    by_id = {row.id: row for row in content_rows}

    entries: list[WeekPlanEntry] = []
    for plan in plans:
        row = by_id.get(plan.current_content_id)
        if (
            row is None
            or row.daily_plan_id != plan.id
            or row.version != plan.current_content_version
        ):
            raise WeeklySyncDataError("current content pointer is inconsistent")
        entries.append(
            WeekPlanEntry(
                plan_id=plan.id,
                content_id=row.id,
                content_version=row.version,
                plan_date=plan.plan_date,
                adopted_content=row.adopted_content or {},
            )
        )
    return entries


def recompute_weekly_sync_state(
    db: Session,
    *,
    class_id: str,
    term_id: str,
    week_number: int,
    trigger_daily_plan_id: str,
    trigger_content_version: int,
    trigger_event: str,
    now: datetime,
) -> WeeklyPlanSyncState:
    entries = load_week_entries(
        db, class_id, term_id, week_number, for_update=True
    )
    themes = build_deterministic_themes(entries)
    game_manifest = build_game_source_manifest(entries)
    source_manifest = build_current_week_source_manifest(entries)

    row = db.execute(
        select(WeeklyPlanSyncState)
        .where(
            WeeklyPlanSyncState.class_id == class_id,
            WeeklyPlanSyncState.term_id == term_id,
            WeeklyPlanSyncState.week_number == week_number,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()

    if row is None:
        row = WeeklyPlanSyncState(
            id=security.generate_id(),
            class_id=class_id,
            term_id=term_id,
            week_number=week_number,
            status="pending_projection",
            deterministic_themes=themes,
            game_source_manifest=game_manifest,
            current_week_source_manifest=source_manifest,
            last_trigger_daily_plan_id=trigger_daily_plan_id,
            last_trigger_content_version=trigger_content_version,
            last_trigger_event=trigger_event,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
    else:
        row.status = "pending_projection"
        row.deterministic_themes = themes
        row.game_source_manifest = game_manifest
        row.current_week_source_manifest = source_manifest
        row.last_trigger_daily_plan_id = trigger_daily_plan_id
        row.last_trigger_content_version = trigger_content_version
        row.last_trigger_event = trigger_event
        row.updated_at = now
    return row


def get_weekly_sync_state(
    db: Session, class_id: str, term_id: str, week_number: int
) -> WeeklyPlanSyncState | None:
    return db.execute(
        select(WeeklyPlanSyncState).where(
            WeeklyPlanSyncState.class_id == class_id,
            WeeklyPlanSyncState.term_id == term_id,
            WeeklyPlanSyncState.week_number == week_number,
        )
    ).scalar_one_or_none()
