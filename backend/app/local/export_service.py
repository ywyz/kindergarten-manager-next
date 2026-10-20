"""Local Word export: database-saved daily plans (D1 spec §12).

Selection, pinning, missing facts and the ack context run in one explicit
read transaction; the DTOs are materialized without ORM lazy loading and the
DOCX generation happens after the transaction ends (the native dialog never
holds a database transaction). The fixed template, mapping and generator are
the reviewed v1 modules; only the read adapter is local.

The fact-collection rules mirror the reviewed I5 algorithm (spec 4.1: stable
locators, complete facts, never faked). They are implemented locally because
the v1 module imports the legacy models and the local package must not.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.local.errors import (
    LocalExportAckRequired,
    LocalExportGenerationFailed,
    LocalExportLimitExceeded,
    LocalExportNotFound,
    LocalValidationError,
)
from app.local.models import LocalDailyPlan
from app.local.profile_service import require_context
from app.local.tx import read_scope
from app.services.word_export_docx import (
    WordExportError,
    generate_daily_export_docx,
)
from app.services.word_export_mapping import map_daily_plan

MAX_EXPORT_COUNT = 31

_PRESENT_GROUP_KINDS = ("collective", "free_choice")
_POST_GROUP_CONTEXTS = ("area", "outdoor", "special_room")


@dataclass(frozen=True)
class ExportRecord:
    """One daily plan pinned to its current content version (no lazy loads)."""

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


# ---------------------------------------------------------------------------
# Missing facts (reviewed I5 rules; stable locators; complete facts)
# ---------------------------------------------------------------------------


def _present(value) -> bool:
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


def _missing_game_facts(games, *, prefix: str, section: str, locators: dict) -> list[dict]:
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


def _warnings(split_baseline) -> tuple[dict, ...]:
    if split_baseline is None:
        return (
            {
                "code": "no_split_baseline",
                "message": "无原始拆分基准，无法比较",
            },
        )
    return ()


# ---------------------------------------------------------------------------
# Ack context (mirrors the reviewed I5 fingerprint rules)
# ---------------------------------------------------------------------------


def _canonical(value) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _facts_fingerprint(missing: list[dict]) -> str:
    return hashlib.sha256(_canonical(missing).encode("utf-8")).hexdigest()


def ack_context(
    *,
    class_id: str,
    from_date: date,
    to_date: date,
    records: tuple[ExportRecord, ...],
    missing: list[dict],
) -> dict:
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
        "missing_count": sum(len(entry.get("facts", ())) for entry in missing),
    }


def ack_matches(expected, current: dict) -> bool:
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


@dataclass(frozen=True)
class ExportBundle:
    records: tuple[ExportRecord, ...]
    missing: tuple[dict, ...]
    warnings: tuple[dict, ...]
    ack_required: bool
    ack_reason: str | None
    expected_context: dict


# ---------------------------------------------------------------------------
# Read snapshot
# ---------------------------------------------------------------------------


def _load_records(session: Session, *, class_id: str, start: date, end: date) -> tuple[ExportRecord, ...]:
    from app.local.daily_plan_service import _load_content  # shared corruption boundary

    plans = list(
        session.scalars(
            select(LocalDailyPlan)
            .where(
                LocalDailyPlan.class_id == class_id,
                LocalDailyPlan.deleted_at.is_(None),
                LocalDailyPlan.plan_date >= start,
                LocalDailyPlan.plan_date <= end,
            )
            .order_by(LocalDailyPlan.plan_date, LocalDailyPlan.id)
        ).all()
    )
    records: list[ExportRecord] = []
    for plan in plans:
        content = _load_content(session, plan)
        records.append(
            ExportRecord(
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
                content_id=content.id,
                content_version=content.version,
                adopted_content=content.adopted_content or {},
                split_baseline=content.split_baseline,
                warnings=_warnings(content.split_baseline),
            )
        )
    return tuple(records)


def prepare_export(
    session: Session,
    *,
    from_date: date,
    to_date: date,
    ack_missing: bool,
    expected_context,
) -> ExportBundle:
    """One explicit read snapshot: select, pin, facts, ack decision."""
    if from_date > to_date:
        raise LocalValidationError("from 不能晚于 to")
    if ack_missing and expected_context is None:
        # ack_missing=true without the complete context can never bypass the
        # confirmation (spec §12.2).
        raise LocalValidationError("缺项确认必须附带完整的 expected_context")

    with read_scope(session):
        context = require_context(session, date.today())
        records = _load_records(
            session,
            class_id=context.school_class.id,
            start=from_date,
            end=to_date,
        )
        if not records:
            raise LocalExportNotFound()
        if len(records) > MAX_EXPORT_COUNT:
            raise LocalExportLimitExceeded(
                f"单次最多导出 {MAX_EXPORT_COUNT} 份日计划，本次范围内有 {len(records)} 份"
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
                        "facts": facts,
                    }
                )
        context_value = ack_context(
            class_id=context.school_class.id,
            from_date=from_date,
            to_date=to_date,
            records=records,
            missing=missing,
        )

    context_supplied = expected_context is not None
    context_ok = context_supplied and ack_matches(expected_context, context_value)
    if not context_supplied:
        ack_required = bool(missing)
        ack_reason = "missing" if ack_required else None
    elif context_ok:
        ack_required = bool(missing) and not ack_missing
        ack_reason = "missing" if ack_required else None
    else:
        ack_required = True
        ack_reason = "context_changed"

    return ExportBundle(
        records=records,
        missing=tuple(missing),
        warnings=tuple(warnings),
        ack_required=ack_required,
        ack_reason=ack_reason,
        expected_context=context_value,
    )


def raise_if_ack_required(bundle: ExportBundle) -> None:
    if bundle.ack_required:
        raise LocalExportAckRequired(
            details={
                "reason": bundle.ack_reason or "missing",
                "facts": list(bundle.missing),
                "expected_context": bundle.expected_context,
            }
        )


# ---------------------------------------------------------------------------
# Generation (outside any database transaction)
# ---------------------------------------------------------------------------


def generate_docx(bundle: ExportBundle) -> bytes:
    views = [map_daily_plan(record) for record in bundle.records]
    try:
        return generate_daily_export_docx(views)
    except WordExportError as exc:
        raise LocalExportGenerationFailed() from exc
    except Exception as exc:  # template/asset failures never leak internals
        raise LocalExportGenerationFailed() from exc


def suggested_filename(records: tuple[ExportRecord, ...], start: date, end: date) -> str:
    class_name = records[0].class_name if records else "日计划"
    safe = class_name.replace("\\", "_").replace("/", "_").replace('"', "_")
    return f"日计划_{safe}_{start.isoformat()}_{end.isoformat()}.docx"
