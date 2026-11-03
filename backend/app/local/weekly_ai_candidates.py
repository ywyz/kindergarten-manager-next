"""Weekly AI candidate reads, chain checks and applicability (A)."""

from __future__ import annotations

import base64
from datetime import datetime
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.local import (
    weekly_ai_contracts,
    weekly_ai_inputs,
    weekly_ai_sources,
    weekly_materials,
    weekly_plan_content,
)
from app.local.errors import LocalAiNotFound, LocalStorageError, LocalValidationError
from app.local.models import (
    LocalAICandidate,
    LocalAIExecution,
    LocalAIInput,
    LocalAITask,
    LocalWeeklyPlan,
    LocalWeeklyPlanContent,
)
from app.local.tx import read_scope

DEFAULT_LIMIT = 20
MAX_LIMIT = 100
TARGETS = {
    "weekly_games_select": "games",
    "weekly_key_week_focus": "key_week_focus",
    "weekly_environment_setup": "environment_setup",
    "weekly_habit_culture": "habit_culture",
    "weekly_home_cooperation": "home_cooperation",
    "weekly_materials_generate": "materials",
}


def _cursor(created: datetime, candidate_id: str) -> str:
    raw = f"{created.isoformat()}|{candidate_id}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _decode_cursor(value: str) -> tuple[datetime, str]:
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode("utf-8")
        created, candidate_id = raw.split("|", 1)
        return datetime.fromisoformat(created), candidate_id
    except Exception:
        raise LocalValidationError("cursor 不合法") from None


def validate_input_row(
    session: Session,
    *,
    plan: LocalWeeklyPlan,
    input_row: LocalAIInput,
    frozen: LocalWeeklyPlanContent | None = None,
):
    """Validate one persisted weekly input against its exact frozen draft."""
    if (
        input_row.source_kind != "weekly_plan"
        or input_row.weekly_plan_id != plan.id
        or input_row.profile_id != plan.profile_id
        or input_row.weekly_draft_id is None
        or input_row.source_revision is None
        or input_row.task_type not in weekly_ai_contracts.TASK_TARGETS
        or type(input_row.input_schema_version) is not int
        or input_row.input_schema_version
        != weekly_ai_inputs.AI_INPUT_SCHEMA_VERSION
    ):
        raise LocalStorageError("AI 输入来源链损坏")
    if not isinstance(input_row.payload_json, Mapping):
        raise LocalStorageError("AI 输入 payload 形状损坏")
    if not isinstance(input_row.dependencies_json, Mapping):
        raise LocalStorageError("AI 输入 dependencies 形状损坏")
    if not isinstance(input_row.target_hashes_json, dict):
        raise LocalStorageError("AI 输入 target hashes 形状损坏")
    if frozen is None:
        frozen = session.get(
            LocalWeeklyPlanContent,
            input_row.weekly_draft_id,
            populate_existing=True,
        )
    if (
        frozen is None
        or frozen.weekly_plan_id != plan.id
        or frozen.id != input_row.weekly_draft_id
        or frozen.version != input_row.source_revision
    ):
        raise LocalStorageError("AI 输入冻结草稿不一致")
    identity = {
        "weekly_plan_id": plan.id,
        "draft_id": frozen.id,
        "draft_version": frozen.version,
        "content_hash": frozen.content_hash,
        "profile_id": plan.profile_id,
        "class_id": plan.class_id,
        "term_id": plan.term_id,
        "week_anchor_date": plan.week_anchor_date.isoformat(),
        "week_number": plan.week_number_snapshot,
    }
    try:
        projected = weekly_ai_inputs.validate_stored_weekly_input(
            input_row.task_type,
            input_row.payload_json,
            input_row.dependencies_json,
            frozen.content_json,
            plan_identity=identity,
        )
    except weekly_ai_contracts.WeeklyAIContractError:
        raise LocalStorageError("AI 输入存储结构不一致") from None
    if projected.dependency_hash != input_row.dependency_hash:
        raise LocalStorageError("AI 输入业务 hash 不一致")
    if input_row.target_hashes_json != projected.target_hashes:
        raise LocalStorageError("AI 输入目标 hash 不一致")
    if projected.payload != input_row.payload_json:
        raise LocalStorageError("AI 输入 payload 与投影不一致")
    return projected


def require_chain(
    session: Session, *, plan: LocalWeeklyPlan, candidate: LocalAICandidate
) -> tuple[dict, LocalAIExecution, LocalAIInput]:
    if candidate.source_kind != "weekly_plan" or candidate.weekly_plan_id != plan.id:
        raise LocalAiNotFound("未找到该 AI 候选")
    execution = session.get(LocalAIExecution, candidate.execution_id)
    task = session.get(LocalAITask, candidate.task_id)
    inp = session.get(LocalAIInput, candidate.input_id)
    if (
        execution is None
        or task is None
        or inp is None
        or candidate.task_id != task.id
        or candidate.execution_id != execution.id
        or candidate.input_id != inp.id
        or execution.task_id != task.id
        or execution.input_id != inp.id
        or task.input_id != inp.id
        or execution.source_kind != "weekly_plan"
        or task.source_kind != "weekly_plan"
        or inp.source_kind != "weekly_plan"
        or execution.source_id != plan.id
        or execution.weekly_plan_id != plan.id
        or task.source_id != plan.id
        or inp.weekly_plan_id != plan.id
        or task.weekly_plan_id != plan.id
        or inp.profile_id != plan.profile_id
        or candidate.profile_id != plan.profile_id
        or execution.profile_id != plan.profile_id
        or task.profile_id != plan.profile_id
        or candidate.source_id != plan.id
        or candidate.source_kind != "weekly_plan"
        or candidate.weekly_plan_id != plan.id
        or candidate.task_type != task.task_type
        or candidate.task_type != execution.task_type
        or candidate.task_type != inp.task_type
        or candidate.contract_version != execution.contract_version
        or candidate.schema_version != inp.input_schema_version
        or inp.weekly_draft_id is None
        or inp.source_revision is None
        or inp.create_operation_id is None
        or task.task_type not in weekly_ai_contracts.TASK_TARGETS
    ):
        raise LocalStorageError("候选来源链损坏")
    # Validate the input row/manifest before handing the stored candidate to
    # the pure validator; this also prevents dict(list/scalar) normalization.
    projected = validate_input_row(session, plan=plan, input_row=inp)
    raw = candidate.raw_candidate_json
    if not isinstance(raw, Mapping):
        raise LocalStorageError("候选存储结构损坏")
    try:
        stored = weekly_ai_contracts.validate_stored_candidate(
            candidate.task_type, raw, server_manifest=_server_manifest(inp)
        )
    except (
        weekly_ai_contracts.WeeklyAIContractError,
        TypeError,
        ValueError,
        KeyError,
    ):
        raise LocalStorageError("候选存储结构损坏") from None
    if weekly_ai_contracts.candidate_hash(stored) != candidate.candidate_hash:
        raise LocalStorageError("候选 hash 与存储内容不一致")
    target = projected.target
    from app.local.models import LocalAIOperation

    operation = session.get(LocalAIOperation, inp.create_operation_id)
    result = operation.result_json if operation is not None else None
    receipt_tasks = result.get("tasks") if isinstance(result, dict) else None
    if (
        operation is None
        or operation.profile_id != plan.profile_id
        or not isinstance(result, dict)
        or plan.id != result.get("weekly_plan_id")
        or not isinstance(receipt_tasks, list)
        or not any(
            isinstance(item, Mapping)
            and item.get("task_id") == task.id
            and item.get("target") == target
            for item in receipt_tasks
        )
    ):
        raise LocalStorageError("AI 创建回执链损坏")
    return stored, execution, inp


def _server_manifest(input_row: LocalAIInput) -> dict:
    deps = input_row.dependencies_json
    if not isinstance(deps, Mapping):
        raise LocalStorageError("候选输入 dependencies 形状损坏")
    manifest = deps.get("_server_manifest")
    if not isinstance(manifest, dict):
        raise LocalStorageError("候选输入缺少 server manifest")
    return manifest


def materialized_candidate(
    candidate: LocalAICandidate, input_row: LocalAIInput
) -> dict[str, Any]:
    raw = candidate.raw_candidate_json
    if not isinstance(raw, Mapping):
        raise LocalStorageError("候选存储结构损坏")
    if candidate.task_type == "weekly_materials_generate":
        items = weekly_materials.materialize_materials_items(
            raw.get("items"), server_manifest=_server_manifest(input_row)
        )
        return {"items": items}
    return dict(raw)


def eligibility(
    session: Session,
    *,
    plan: LocalWeeklyPlan,
    content: LocalWeeklyPlanContent,
    candidate: LocalAICandidate,
    input_row: LocalAIInput,
) -> str:
    if candidate.task_type not in TARGETS:
        return "contract_obsolete"
    if not weekly_ai_contracts.supports_prompt_contract(
        candidate.task_type, candidate.contract_version
    ):
        return "contract_obsolete"
    try:
        current_version = weekly_ai_contracts.prompt_contract_version(
            candidate.task_type
        )
    except weekly_ai_contracts.WeeklyAIContractError:
        return "contract_obsolete"
    if candidate.contract_version != current_version:
        # Historical supported versions remain readable in detail/history,
        # but are not eligible for a new adoption.
        return "contract_obsolete"
    try:
        raw = weekly_ai_sources.load_raw_manifest(session, plan=plan, content=content)
        projected = weekly_ai_inputs.project_weekly_input(
            candidate.task_type, raw, content.content_json
        )
    except weekly_ai_contracts.WeeklyAIContractError:
        return "source_changed"
    except weekly_plan_content.WeeklyContentError:
        return "source_changed"
    if projected.dependency_hash != input_row.dependency_hash:
        return "source_changed"
    return "eligible"


def _candidate_facts(task_type: str, deps: Mapping[str, Any]) -> tuple[list[dict], list[dict]]:
    unavailable: list[dict] = []
    warnings: list[dict] = []
    daily = deps.get("daily_sources") or []
    if task_type in (
        "weekly_games_select",
        "weekly_key_week_focus",
        "weekly_habit_culture",
        "weekly_home_cooperation",
    ) and not daily:
        unavailable.append({"code": "no_own_daily_sources"})
    if task_type in ("weekly_environment_setup", "weekly_materials_generate"):
        selected = deps.get("selected") or {}
        slots = selected.get("outdoor_game_slots") or {}
        if not selected.get("focus_area") and not any(
            item is not None for item in slots.values()
        ):
            unavailable.append({"code": "no_selected_games_or_focus"})
    if task_type == "weekly_home_cooperation" and deps.get("calendar") is None:
        warnings.append({"code": "calendar_context_unavailable"})
    return unavailable, warnings


def _item(
    session: Session, candidate: LocalAICandidate, input_row: LocalAIInput
) -> dict[str, Any]:
    return {
        "candidate_id": candidate.id,
        "task_id": candidate.task_id,
        "target": TARGETS.get(candidate.task_type, ""),
        "candidate_hash": candidate.candidate_hash,
        "eligibility": "eligible",
        "available_targets": [TARGETS.get(candidate.task_type, "")],
        "create_operation_id": input_row.create_operation_id,
        "created_at": candidate.created_at.isoformat(),
    }


def list_candidates(
    session: Session,
    *,
    profile_id: str,
    plan_id: str,
    create_operation_id: str | None = None,
    task_id: str | None = None,
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> dict[str, Any]:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
        raise LocalValidationError("limit 必须在 1–100 之间")
    with read_scope(session):
        plan = session.get(LocalWeeklyPlan, plan_id)
        if plan is None or plan.profile_id != profile_id:
            raise LocalAiNotFound("未找到该周计划")
        content = session.get(LocalWeeklyPlanContent, plan.current_draft_id)
        if content is None or content.weekly_plan_id != plan.id:
            raise LocalStorageError("周计划草稿指针不一致")
        query = select(LocalAICandidate).where(
            LocalAICandidate.profile_id == profile_id,
            LocalAICandidate.source_kind == "weekly_plan",
            LocalAICandidate.weekly_plan_id == plan_id,
        )
        if task_id is not None:
            query = query.where(LocalAICandidate.task_id == task_id)
        if create_operation_id is not None:
            query = query.join(
                LocalAIInput, LocalAIInput.id == LocalAICandidate.input_id
            ).where(LocalAIInput.create_operation_id == create_operation_id)
        if cursor:
            created, candidate_id = _decode_cursor(cursor)
            query = query.where(
                (LocalAICandidate.created_at > created)
                | (
                    (LocalAICandidate.created_at == created)
                    & (LocalAICandidate.id > candidate_id)
                )
            )
        rows = list(
            session.scalars(
                query.order_by(LocalAICandidate.created_at, LocalAICandidate.id).limit(
                    limit + 1
                )
            ).all()
        )
        items: list[dict[str, Any]] = []
        for candidate in rows[:limit]:
            _raw, _execution, inp = require_chain(
                session, plan=plan, candidate=candidate
            )
            item = _item(session, candidate, inp)
            item["eligibility"] = eligibility(
                session, plan=plan, content=content, candidate=candidate, input_row=inp
            )
            items.append(item)
        next_cursor = (
            _cursor(rows[limit - 1].created_at, rows[limit - 1].id)
            if len(rows) > limit
            else None
        )
        return {"items": items, "next_cursor": next_cursor}


def get_candidate(
    session: Session, *, profile_id: str, plan_id: str, candidate_id: str
) -> dict[str, Any]:
    with read_scope(session):
        plan = session.get(LocalWeeklyPlan, plan_id)
        if plan is None or plan.profile_id != profile_id:
            raise LocalAiNotFound("未找到该周计划")
        candidate = session.get(LocalAICandidate, candidate_id)
        if candidate is None:
            raise LocalAiNotFound("未找到该 AI 候选")
        raw, _execution, inp = require_chain(session, plan=plan, candidate=candidate)
        content = session.get(LocalWeeklyPlanContent, plan.current_draft_id)
        if content is None:
            raise LocalStorageError("周计划草稿指针不一致")
        state = eligibility(
            session, plan=plan, content=content, candidate=candidate, input_row=inp
        )
        item = _item(session, candidate, inp)
        item["eligibility"] = state
        item["data"] = materialized_candidate(candidate, inp)
        deps = weekly_ai_inputs.build_business_dependency_view(
            dict(inp.dependencies_json or {})
        )
        item["basis"] = deps
        unavailable, warnings = _candidate_facts(candidate.task_type, deps)
        item["warnings"] = warnings
        item["unavailable_inputs"] = unavailable
        return item


__all__ = [
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "TARGETS",
    "eligibility",
    "get_candidate",
    "list_candidates",
    "materialized_candidate",
    "require_chain",
    "validate_input_row",
]
