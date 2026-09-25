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
    expected_context: dict


# ---------------------------------------------------------------------------
# daily plan read / pin / missing facts
# ---------------------------------------------------------------------------

# Fixed-template column groups checked for content presence (spec 4.1,
# engineering scheme aligned with the I4 "empty_field" wording). Empty
# string / empty array / missing key are missing; ``{}`` misses all of them.
DAILY_MISSING_FIELDS: tuple[tuple[str, str], ...] = (
    ("morning_games", "section"),
    ("morning_talk.topic", "text"),
    ("morning_talk.questions", "text"),
    ("group_activity.theme", "text"),
    ("group_activity.objectives", "text"),
    ("group_activity.preparation", "text"),
    ("group_activity.key_points", "text"),
    ("group_activity.difficult_points", "text"),
    ("group_activity.process", "text"),
    ("post_group_games", "section"),
    ("afternoon_outdoor", "section"),
    ("reflection", "text"),
)


def _resolve_path(content: dict, path: str):
    current = content
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def collect_daily_missing_facts(adopted_content) -> list[dict]:
    """Server-side missing facts from the stored ``adopted_content`` only."""
    content = adopted_content if isinstance(adopted_content, dict) else {}
    facts: list[dict] = []
    for path, kind in DAILY_MISSING_FIELDS:
        value = _resolve_path(content, path)
        if kind == "text":
            missing = not (isinstance(value, str) and value.strip())
        else:
            missing = value is None or (
                isinstance(value, (list, dict)) and len(value) == 0
            )
        if missing:
            facts.append({"kind": "empty_field", "field": path})
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
    ack_required = bool(missing)
    if ack_required and ack_missing and daily_ack_matches(expected_context, context):
        ack_required = False

    return DailyExportBundle(
        items=tuple(records),
        missing=tuple(missing),
        warnings=tuple(warnings),
        ack_required=ack_required,
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
