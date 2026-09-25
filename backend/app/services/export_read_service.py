"""I5 Word export read / selection service (read-only, no HTTP, no locks).

This module resolves what a future export request will read, pins the exact
content/confirmation versions and computes the server-side facts and warnings.
It performs no writes, opens no explicit transaction and takes no
``FOR UPDATE`` lock, mirroring the existing GET read services.

Consistency-view invariant (spec 4.4, engineering only): each ``prepare_*`` /
``select_*`` entry performs every read it needs through the caller's Session
in one call, so a future request can run it inside a single read transaction;
the range-selection calendar revision, the pinned content/version, the dynamic
columns and the header dates therefore come from the same database view. This
does not prove MySQL REPEATABLE READ — that stays in the integration layer.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    DailyPlan,
    DailyPlanContent,
    Term,
    WeeklyPlan,
    WeeklyPlanConfirmedContent,
)
from app.services import calendar_service as cal
from app.services import weekly_plan_content, weekly_plan_sync_service
from app.services.weekly_plan_read_service import public_content, read_week_days


class ExportReadError(Exception):
    code = "EXPORT_READ_ERROR"

    def __init__(self, message: str = ""):
        super().__init__(message or self.code)
        self.message = message or self.code


class ExportReadValidationError(ExportReadError):
    code = "VALIDATION_ERROR"


class ExportReadDataError(ExportReadError):
    """Missing/inconsistent persisted pointer (maps to 503)."""

    code = "SERVICE_UNAVAILABLE"


class ExportConfirmationNotFound(ExportReadError):
    code = "CONFIRMATION_NOT_FOUND"


class ExportReadNotFound(ExportReadError):
    code = "WEEKLY_PLAN_NOT_FOUND"


class ExportReadForbidden(ExportReadError):
    code = "FORBIDDEN"


@dataclass(frozen=True, slots=True)
class DailyPlanExportRecord:
    """One daily plan pinned to its current append-only content version."""

    plan_id: str
    class_id: str
    term_id: str
    plan_date: date
    week_number: int
    weekday: int
    creator_id: str
    creator_display_name: str | None
    school_name: str | None
    class_name: str
    grade: str
    content_id: str
    content_version: int
    adopted_content: dict
    split_baseline: dict | None
    warnings: tuple[dict, ...] = ()


@dataclass(frozen=True, slots=True)
class WeeklyExportItem:
    """One weekly plan pinned to an immutable confirmed snapshot."""

    plan_id: str
    class_id: str
    term_id: str
    week_number: int
    week_start: date
    first_teaching_day: date | None
    confirmed_version: int
    confirmed_content_id: str
    content: dict
    facts: dict
    warnings: tuple[dict, ...]
    term_start: date
    term_end: date
    week_days: dict
    school_name: str | None
    class_name: str
    grade: str
    header_teacher_names: list
    caregiver_name: str | None


@dataclass(frozen=True, slots=True)
class DailyExportBundle:
    items: tuple[DailyPlanExportRecord, ...]
    missing: tuple[dict, ...]
    warnings: tuple[dict, ...]
    ack_required: bool
    ack_reason: str | None
    expected_context: dict


# ---------------------------------------------------------------------------
# daily plan read / pin / missing facts
# ---------------------------------------------------------------------------

# Per-column emptiness rules for the fixed daily template (spec 4.1/5.1).
# A column is checked only when its branch applies: the morning template needs
# one collective and one free_choice group, each present post-group context is
# checked field by field, and no particular post-group context kind is
# demanded. Every fact carries a stable locator (section / group / game) so the
# fingerprint is deterministic and multiple same-kind entries are never lost.
# I3's save rules are untouched: incomplete content may still be stored, it
# only shows up here as missing template columns.

_PRESENT_GROUP_KINDS = ("collective", "free_choice")
_POST_GROUP_CONTEXTS = ("area", "outdoor", "special_room")


def _present(value) -> bool:
    """True only for non-empty (non-whitespace) text."""
    return isinstance(value, str) and bool(value.strip())


def _fact(field: str, **locators) -> dict:
    fact: dict = {"kind": "empty_field", "field": field}
    for key in (
        "section",
        "group_kind",
        "group_index",
        "group_id",
        "game_index",
        "game_id",
    ):
        value = locators.get(key)
        if value is not None:
            fact[key] = value
    return fact


def _missing_game_facts(
    games, *, prefix: str, section: str, locators: dict
) -> list[dict]:
    """Empty game list / blank game name facts for one group."""
    if not isinstance(games, list) or not games:
        return [_fact(f"{prefix}.games", section=section, **locators)]
    facts: list[dict] = []
    for game_index, game in enumerate(games):
        name = game.get("name") if isinstance(game, dict) else None
        if not _present(name):
            facts.append(
                _fact(
                    f"{prefix}.games[{game_index}].name",
                    section=section,
                    game_index=game_index,
                    game_id=(
                        game.get("game_id") if isinstance(game, dict) else None
                    ),
                    **locators,
                )
            )
    return facts


def collect_daily_missing_facts(adopted_content) -> list[dict]:
    """Server-side missing facts from the stored ``adopted_content`` only."""
    content = adopted_content if isinstance(adopted_content, dict) else {}
    facts: list[dict] = []

    # Morning games: the fixed collective + free_choice name columns, each
    # group's shared objectives/guidance columns, and every game name.
    raw_morning = content.get("morning_games")
    morning_groups = (
        [g for g in raw_morning if isinstance(g, dict)]
        if isinstance(raw_morning, list)
        else []
    )
    for kind in _PRESENT_GROUP_KINDS:
        if not any(g.get("group_kind") == kind for g in morning_groups):
            facts.append(
                _fact(
                    f"morning_games.{kind}",
                    section="morning_games",
                    group_kind=kind,
                )
            )
    for index, group in enumerate(morning_groups):
        prefix = f"morning_games[{index}]"
        locators = {
            "group_kind": group.get("group_kind"),
            "group_index": index,
            "group_id": group.get("group_id"),
        }
        facts.extend(
            _missing_game_facts(
                group.get("games"),
                prefix=prefix,
                section="morning_games",
                locators=locators,
            )
        )
        for field in ("focus_guidance", "shared_objectives", "guidance_points"):
            if not _present(group.get(field)):
                facts.append(
                    _fact(f"{prefix}.{field}", section="morning_games", **locators)
                )

    raw_talk = content.get("morning_talk")
    talk = raw_talk if isinstance(raw_talk, dict) else {}
    for field in ("topic", "questions"):
        if not _present(talk.get(field)):
            facts.append(_fact(f"morning_talk.{field}", section="morning_talk"))

    raw_activity = content.get("group_activity")
    activity = raw_activity if isinstance(raw_activity, dict) else {}
    for field in (
        "theme",
        "objectives",
        "preparation",
        "key_points",
        "difficult_points",
        "process",
    ):
        if not _present(activity.get(field)):
            facts.append(_fact(f"group_activity.{field}", section="group_activity"))

    # Post-group games: the section column, then each present context group's
    # own columns. Only the branches that actually appear are checked.
    raw_post = content.get("post_group_games")
    post_groups = (
        [g for g in raw_post if isinstance(g, dict)]
        if isinstance(raw_post, list)
        else []
    )
    if not post_groups:
        facts.append(_fact("post_group_games", section="post_group_games"))
    else:
        for index, group in enumerate(post_groups):
            prefix = f"post_group_games[{index}]"
            locators = {
                "group_index": index,
                "group_id": group.get("group_id"),
            }
            if group.get("context_kind") not in _POST_GROUP_CONTEXTS:
                facts.append(
                    _fact(
                        f"{prefix}.context_kind",
                        section="post_group_games",
                        **locators,
                    )
                )
            facts.extend(
                _missing_game_facts(
                    group.get("games"),
                    prefix=prefix,
                    section="post_group_games",
                    locators=locators,
                )
            )
            for field in (
                "area",
                "focus_guidance",
                "objectives",
                "guidance",
                "support_strategy",
            ):
                if not _present(group.get(field)):
                    facts.append(
                        _fact(
                            f"{prefix}.{field}",
                            section="post_group_games",
                            **locators,
                        )
                    )

    afternoon = content.get("afternoon_outdoor")
    if not isinstance(afternoon, dict):
        facts.append(_fact("afternoon_outdoor", section="afternoon_outdoor"))
    else:
        locators = {"group_id": afternoon.get("group_id")}
        facts.extend(
            _missing_game_facts(
                afternoon.get("games"),
                prefix="afternoon_outdoor",
                section="afternoon_outdoor",
                locators=locators,
            )
        )
        for field in (
            "area",
            "observation_focus",
            "objectives",
            "guidance",
            "support_strategy",
        ):
            if not _present(afternoon.get(field)):
                facts.append(
                    _fact(
                        f"afternoon_outdoor.{field}",
                        section="afternoon_outdoor",
                        **locators,
                    )
                )

    if not _present(content.get("reflection")):
        facts.append(_fact("reflection", section="reflection"))

    return facts


def _daily_warnings(split_baseline) -> tuple[dict, ...]:
    if split_baseline is None:
        return ({"code": "no_split_baseline"},)
    return ()


def select_daily_plans(
    db: Session,
    *,
    class_id: str,
    from_date: date,
    to_date: date,
) -> list[DailyPlanExportRecord]:
    """Strict date-range selection, ascending, pinned to current content."""
    if from_date > to_date:
        raise ExportReadValidationError("from 不能晚于 to")

    plans = list(
        db.scalars(
            select(DailyPlan)
            .where(
                DailyPlan.class_id == class_id,
                DailyPlan.deleted_at.is_(None),
                DailyPlan.plan_date >= from_date,
                DailyPlan.plan_date <= to_date,
            )
            .order_by(DailyPlan.plan_date, DailyPlan.id)
        ).all()
    )
    if not plans:
        return []
    # Ascending date order is required by the spec; SQL already orders, and
    # the explicit key keeps the contract testable and independent of driver
    # ordering.
    plans.sort(key=lambda plan: (plan.plan_date, plan.id))

    content_ids = [plan.current_content_id for plan in plans]
    if any(content_id is None for content_id in content_ids):
        raise ExportReadDataError("日计划当前内容指针为空")
    rows = db.scalars(
        select(DailyPlanContent).where(DailyPlanContent.id.in_(content_ids))
    ).all()
    by_id = {row.id: row for row in rows}

    records: list[DailyPlanExportRecord] = []
    for plan in plans:
        row = by_id.get(plan.current_content_id)
        if (
            row is None
            or row.daily_plan_id != plan.id
            or row.version != plan.current_content_version
        ):
            raise ExportReadDataError("当前内容指针不一致")
        records.append(
            DailyPlanExportRecord(
                plan_id=plan.id,
                class_id=plan.class_id,
                term_id=plan.term_id,
                plan_date=plan.plan_date,
                week_number=plan.week_number,
                weekday=plan.weekday,
                creator_id=plan.creator_id,
                creator_display_name=plan.creator_display_name,
                school_name=plan.school_name,
                class_name=plan.class_name,
                grade=plan.grade,
                content_id=row.id,
                content_version=row.version,
                adopted_content=row.adopted_content or {},
                split_baseline=row.split_baseline,
                warnings=_daily_warnings(row.split_baseline),
            )
        )
    return records


# ---------------------------------------------------------------------------
# section 11.8 option B: ack bound to the displayed version/facts object
# ---------------------------------------------------------------------------


def _canonical(value) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _facts_fingerprint(missing: list[dict]) -> str:
    return hashlib.sha256(_canonical(missing).encode("utf-8")).hexdigest()


def daily_ack_context(
    *,
    class_id: str,
    from_date: date,
    to_date: date,
    records: list[DailyPlanExportRecord],
    missing: list[dict],
) -> dict:
    """Deterministic minimal expected context the client echoes back."""
    versions = sorted(
        (
            {
                "daily_plan_id": record.plan_id,
                "content_id": record.content_id,
                "content_version": record.content_version,
            }
            for record in records
        ),
        key=lambda item: item["daily_plan_id"],
    )
    return {
        "class_id": class_id,
        "from": from_date.isoformat(),
        "to": to_date.isoformat(),
        "versions": versions,
        "missing_fingerprint": _facts_fingerprint(missing),
        "missing_count": len(missing),
    }


def daily_ack_matches(expected, current: dict) -> bool:
    """True only when the client-echoed context equals the recomputed one."""
    if not isinstance(expected, dict):
        return False
    for key in (
        "class_id",
        "from",
        "to",
        "versions",
        "missing_fingerprint",
        "missing_count",
    ):
        if expected.get(key) != current.get(key):
            return False
    return True


def prepare_daily_export(
    db: Session,
    *,
    class_id: str,
    from_date: date,
    to_date: date,
    ack_missing: bool = False,
    expected_context=None,
) -> DailyExportBundle:
    """Single read entry: selection + pinning + facts + ack decision.

    Re-authentication and class-context re-derivation remain the router's
    per-request responsibility (spec 3.5); every call here recomputes versions
    and facts, so an ack accepted on a previous request is re-validated
    against the freshly read object.

    Section 11.8 option B: an echoed expected context is only honoured when it
    equals the freshly recomputed one. A matching context with ``ack_missing``
    continues; a context that does not match (object/version/facts changed, or
    the context is absent/invalid on a retry) makes the old ack void and
    requires a fresh confirmation even when the latest ``missing`` set is
    empty, with ``ack_reason="context_changed"`` so the future API layer can
    tell the user the displayed object changed. A first request with no echoed
    context and no missing facts exports directly.
    """
    records = select_daily_plans(
        db, class_id=class_id, from_date=from_date, to_date=to_date
    )

    missing: list[dict] = []
    warnings: list[dict] = []
    for record in records:
        warnings.extend(record.warnings)
        facts = collect_daily_missing_facts(record.adopted_content)
        if facts:
            missing.append(
                {
                    "daily_plan_id": record.plan_id,
                    "plan_date": record.plan_date.isoformat(),
                    "fields": [fact["field"] for fact in facts],
                }
            )

    context = daily_ack_context(
        class_id=class_id,
        from_date=from_date,
        to_date=to_date,
        records=records,
        missing=missing,
    )
    context_supplied = expected_context is not None
    context_matches = context_supplied and daily_ack_matches(
        expected_context, context
    )

    ack_required: bool
    ack_reason: str | None
    if not context_supplied:
        ack_required = bool(missing)
        ack_reason = "missing" if ack_required else None
    elif context_matches:
        ack_required = bool(missing) and not ack_missing
        ack_reason = "missing" if ack_required else None
    else:
        # The displayed confirmation object changed (or an absent/invalid
        # context was echoed): the old ack is void even when the latest
        # missing set is empty, and the caller must re-confirm the returned
        # latest context.
        ack_required = True
        ack_reason = "context_changed"

    return DailyExportBundle(
        items=tuple(records),
        missing=tuple(missing),
        warnings=tuple(warnings),
        ack_required=ack_required,
        ack_reason=ack_reason,
        expected_context=context,
    )


# ---------------------------------------------------------------------------
# weekly plan read / selection (range + single)
# ---------------------------------------------------------------------------


def _load_term(db: Session, plan: WeeklyPlan) -> Term:
    term = db.get(Term, plan.term_id)
    if term is None:
        raise ExportReadDataError("学期缺失")
    return term


def _assert_class_access(
    plan: WeeklyPlan, *, role: str, class_id: str
) -> None:
    if plan.class_id == class_id:
        return
    if role == "admin":
        raise ExportReadNotFound("班级上下文与周计划不符")
    raise ExportReadForbidden()


def _load_current_confirmed(
    db: Session, plan: WeeklyPlan
) -> WeeklyPlanConfirmedContent:
    cid = plan.current_confirmed_content_id
    cver = plan.current_confirmed_content_version
    if cid is None and cver is None:
        raise ExportConfirmationNotFound("该周计划尚未确认")
    if cid is None or cver is None:
        raise ExportReadDataError("当前确认指针不完整")
    row = db.get(WeeklyPlanConfirmedContent, cid)
    if (
        row is None
        or row.weekly_plan_id != plan.id
        or row.version != cver
    ):
        raise ExportReadDataError("当前确认指针不一致")
    return row


def _load_confirmed_version(
    db: Session, plan: WeeklyPlan, version: int
) -> WeeklyPlanConfirmedContent:
    row = db.scalars(
        select(WeeklyPlanConfirmedContent).where(
            WeeklyPlanConfirmedContent.weekly_plan_id == plan.id,
            WeeklyPlanConfirmedContent.version == version,
        )
    ).one_or_none()
    if row is None:
        raise ExportConfirmationNotFound("确认版本不存在")
    return row


def judge_weekly_warning(
    plan: WeeklyPlan,
    confirmed: WeeklyPlanConfirmedContent,
    content: dict,
    entries,
    days: dict,
) -> list[str]:
    """Warning reasons around the actually selected confirmation row R."""
    reasons: list[str] = []
    if confirmed.draft_version < (plan.current_draft_version or 0):
        reasons.append("draft_ahead")
    facts = weekly_plan_content.build_facts(content, entries, days)
    if facts.get("stale_sources"):
        reasons.append("stale_sources")
    if confirmed.version < (plan.current_confirmed_content_version or 0):
        reasons.append("superseded")
    if (confirmed.facts or {}).get("stale_sources"):
        reasons.append("recorded_stale")
    return reasons


def _build_weekly_item(
    db: Session,
    plan: WeeklyPlan,
    term: Term,
    days: dict,
    confirmed: WeeklyPlanConfirmedContent,
) -> WeeklyExportItem:
    content = public_content(confirmed.content)
    entries = weekly_plan_sync_service.load_week_entries(
        db, plan.class_id, plan.term_id, plan.week_number, for_update=False
    )
    reasons = judge_weekly_warning(plan, confirmed, content, entries, days)
    warnings = tuple(
        {"code": "confirmed_not_latest", "reason": reason}
        for reason in reasons
    )
    week_start = _week_start(term, plan.week_number)
    teaching_days = sorted(d for d, state in days.items() if state == "teaching")
    return WeeklyExportItem(
        plan_id=plan.id,
        class_id=plan.class_id,
        term_id=plan.term_id,
        week_number=plan.week_number,
        week_start=week_start,
        first_teaching_day=teaching_days[0] if teaching_days else None,
        confirmed_version=confirmed.version,
        confirmed_content_id=confirmed.id,
        content=content,
        facts=confirmed.facts or {},
        warnings=warnings,
        term_start=term.start_date,
        term_end=term.end_date,
        week_days=dict(days),
        school_name=plan.school_name,
        class_name=plan.class_name,
        grade=plan.grade,
        header_teacher_names=list(plan.header_teacher_names or []),
        caregiver_name=plan.caregiver_name,
    )


def _week_start(term: Term, week_number: int) -> date:
    return cal.week_anchor(term.start_date) + timedelta(
        days=7 * (week_number - 1)
    )


def select_weekly_plans_range(
    db: Session,
    *,
    class_id: str,
    from_date: date,
    to_date: date,
) -> list[WeeklyExportItem]:
    """Range mode: whole weeks whose teaching days intersect [from, to].

    Unconfirmed candidates are excluded, zero-teaching-day weeks never
    intersect, ordering is by the actual week start date (never by bare
    ``week_number``) and dedup is by plan identity.
    """
    if from_date > to_date:
        raise ExportReadValidationError("from 不能晚于 to")

    plans = list(
        db.scalars(
            select(WeeklyPlan).where(
                WeeklyPlan.class_id == class_id,
                WeeklyPlan.deleted_at.is_(None),
                WeeklyPlan.current_confirmed_content_id.is_not(None),
            )
        ).all()
    )

    items: list[WeeklyExportItem] = []
    for plan in plans:
        term = _load_term(db, plan)
        days = read_week_days(db, term, plan.week_number)
        if not any(
            from_date <= day <= to_date
            for day, state in days.items()
            if state == "teaching"
        ):
            continue
        confirmed = _load_current_confirmed(db, plan)
        items.append(_build_weekly_item(db, plan, term, days, confirmed))

    deduped: list[WeeklyExportItem] = []
    seen: set[str] = set()
    for item in items:
        if item.plan_id in seen:
            continue
        seen.add(item.plan_id)
        deduped.append(item)
    deduped.sort(key=_weekly_sort_key)
    return deduped


def _weekly_sort_key(item: WeeklyExportItem) -> tuple:
    return (
        item.week_start,
        item.first_teaching_day or date.max,
        item.plan_id,
    )


def load_weekly_single(
    db: Session,
    *,
    class_id: str,
    role: str,
    plan_id: str,
    confirmed_version: int | None = None,
) -> WeeklyExportItem:
    """Single-plan mode: explicit ``confirmed_version`` or current pointer."""
    plan = db.get(WeeklyPlan, plan_id)
    if plan is None or plan.deleted_at is not None:
        raise ExportReadNotFound("周计划不存在")
    _assert_class_access(plan, role=role, class_id=class_id)

    term = _load_term(db, plan)
    days = read_week_days(db, term, plan.week_number)
    if confirmed_version is None:
        confirmed = _load_current_confirmed(db, plan)
    else:
        confirmed = _load_confirmed_version(db, plan, confirmed_version)
    return _build_weekly_item(db, plan, term, days, confirmed)
