"""Weekly-plan AI task submission and safe operation receipts (A)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ids import new_opaque_id
from app.local import ai_task_service, ai_transport, weekly_ai_inputs, weekly_ai_sources
from app.local.errors import (
    LocalAiNotFound,
    LocalAiOperationNotFound,
    LocalMaterialContextRequired,
    LocalStorageError,
    LocalValidationError,
    LocalWeeklyAiRequestConflict,
    LocalWeeklyAiTaskActive,
    LocalWeeklyPlanNotFound,
    LocalWeeklyVersionConflict,
)
from app.local.models import (
    LocalAIOperation,
    LocalAIInput,
    LocalAITask,
    LocalPersonalPromptHead,
    LocalPersonalPromptVersion,
    LocalPromptBundle,
    LocalWeeklyPlan,
    LocalWeeklyPlanContent,
)
from app.local.normalize import normalize_request_id
from app.local.prompt_bundles import canonical_json
from app.local.tx import begin_immediate, read_scope, rollback

GAMES = "weekly_ai_games_create"
COLUMNS = "weekly_ai_columns_create"
MATERIALS = "weekly_ai_materials_create"
ADOPT = "weekly_ai_adopt"
CREATE_KINDS = (GAMES, COLUMNS, MATERIALS)
OP_KINDS = (GAMES, COLUMNS, MATERIALS, ADOPT)


@dataclass(frozen=True)
class WeeklyTaskSpec:
    task_type: str
    target: str


def _fingerprint(operation_kind: str, payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        canonical_json({"operation_kind": operation_kind, "payload": payload}).encode(
            "utf-8"
        )
    ).hexdigest()


def require_plan(
    session: Session, *, profile_id: str, plan_id: str
) -> LocalWeeklyPlan:
    """Resolve one weekly plan for read paths; foreign/missing is a 404."""
    with read_scope(session):
        plan = session.get(LocalWeeklyPlan, plan_id, populate_existing=True)
        if plan is None or plan.profile_id != profile_id:
            raise LocalAiNotFound("未找到该周计划")
        return plan


def _content(session: Session, plan: LocalWeeklyPlan) -> LocalWeeklyPlanContent:
    row = session.get(LocalWeeklyPlanContent, plan.current_draft_id, populate_existing=True)
    if (
        row is None
        or row.weekly_plan_id != plan.id
        or row.version != plan.current_draft_version
    ):
        raise LocalStorageError("周计划草稿指针不一致")
    return row


def _plan(session: Session, profile_id: str, plan_id: str) -> LocalWeeklyPlan:
    plan = session.get(LocalWeeklyPlan, plan_id)
    if plan is None or plan.profile_id != profile_id:
        raise LocalWeeklyPlanNotFound()
    return plan


def _validate_specs(operation_kind: str, specs: Sequence[WeeklyTaskSpec]) -> None:
    if operation_kind == GAMES:
        if len(specs) != 1 or specs[0].task_type != "weekly_games_select" or specs[0].target != "games":
            raise LocalValidationError("游戏任务必须恰好一个 games 目标")
        return
    if operation_kind == MATERIALS:
        if (
            len(specs) != 1
            or specs[0].task_type != "weekly_materials_generate"
            or specs[0].target != "materials"
        ):
            raise LocalValidationError("材料任务必须恰好一个 materials 目标")
        return
    if operation_kind != COLUMNS:
        raise LocalValidationError("operation_kind 不合法")
    if not 1 <= len(specs) <= 4:
        raise LocalValidationError("栏目任务必须包含 1–4 个目标")
    mapping = {
        "key_week_focus": "weekly_key_week_focus",
        "environment_setup": "weekly_environment_setup",
        "habit_culture": "weekly_habit_culture",
        "home_cooperation": "weekly_home_cooperation",
    }
    seen: set[str] = set()
    for spec in specs:
        if spec.target in seen or mapping.get(spec.target) != spec.task_type:
            raise LocalValidationError("栏目目标/类型不合法或重复")
        seen.add(spec.target)


def _safe_result(
    request_id: str,
    operation_kind: str,
    plan: LocalWeeklyPlan,
    content: LocalWeeklyPlanContent,
    specs: Sequence[WeeklyTaskSpec],
    task_ids: Sequence[str],
) -> dict[str, Any]:
    return {
        "request_id": request_id,
        "operation_kind": operation_kind,
        "weekly_plan_id": plan.id,
        "draft": {"id": content.id, "version": content.version},
        "tasks": [
            {"target": spec.target, "task_id": task_id}
            for spec, task_id in zip(specs, task_ids)
        ],
        "replayed": False,
    }


def _replay(row: LocalAIOperation, request_id: str, plan_id: str,
            operation_kind: str, fingerprint: str) -> dict[str, Any]:
    result = dict(row.result_json or {})
    if result.get("weekly_plan_id") != plan_id:
        raise LocalAiOperationNotFound()
    if row.operation_kind != operation_kind or row.request_fingerprint != fingerprint:
        raise LocalWeeklyAiRequestConflict()
    result["replayed"] = True
    return result


def peek_create_operation(
    session: Session,
    *,
    profile_id: str,
    plan_id: str,
    request_id: object,
    operation_kind: str,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    if operation_kind not in CREATE_KINDS:
        raise LocalValidationError("operation_kind 不合法")
    rid = normalize_request_id(request_id)
    fingerprint = _fingerprint(operation_kind, payload)
    with read_scope(session):
        row = session.scalars(
            select(LocalAIOperation).where(
                LocalAIOperation.profile_id == profile_id,
                LocalAIOperation.request_id == rid,
            )
        ).first()
        if row is None:
            return None
        return _replay(row, rid, plan_id, operation_kind, fingerprint)


def get_operation(
    session: Session, *, profile_id: str, plan_id: str, request_id: str
) -> dict[str, Any]:
    rid = normalize_request_id(request_id)
    with read_scope(session):
        row = session.scalars(
            select(LocalAIOperation).where(
                LocalAIOperation.profile_id == profile_id,
                LocalAIOperation.request_id == rid,
            )
        ).first()
        if row is None or row.operation_kind not in OP_KINDS:
            raise LocalAiOperationNotFound()
        result = dict(row.result_json or {})
        if result.get("weekly_plan_id") != plan_id:
            raise LocalAiOperationNotFound()
        return {
            "request_id": row.request_id,
            "operation_kind": row.operation_kind,
            "status": "committed",
            "result": result,
            "created_at": row.created_at.isoformat(),
        }


def create_weekly_tasks(
    session: Session,
    *,
    runtime: Any | None,
    profile_id: str,
    plan_id: str,
    request_id: object,
    expected_draft_version: object,
    operation_kind: str,
    task_specs: Sequence[WeeklyTaskSpec],
) -> tuple[dict[str, Any], bool]:
    if operation_kind not in CREATE_KINDS:
        raise LocalValidationError("operation_kind 不合法")
    _validate_specs(operation_kind, task_specs)
    if (
        isinstance(expected_draft_version, bool)
        or not isinstance(expected_draft_version, int)
        or expected_draft_version < 1
    ):
        raise LocalValidationError("expected_draft_version 必须是正整数")
    rid = normalize_request_id(request_id)
    order = ("key_week_focus", "environment_setup", "habit_culture", "home_cooperation")
    selected = [spec.target for spec in task_specs]
    canonical_targets = [target for target in order if target in selected] + [
        target for target in selected if target not in order
    ]
    payload = {
        "weekly_plan_id": plan_id,
        "expected_draft_version": expected_draft_version,
        "operation_kind": operation_kind,
        "selected_fields": canonical_targets,
    }
    fingerprint = _fingerprint(operation_kind, payload)

    with read_scope(session):
        row = session.scalars(
            select(LocalAIOperation).where(
                LocalAIOperation.profile_id == profile_id,
                LocalAIOperation.request_id == rid,
            )
        ).first()
        if row is not None:
            return _replay(row, rid, plan_id, operation_kind, fingerprint), False

    if runtime is not None:
        for task_type in dict.fromkeys(spec.task_type for spec in task_specs):
            ai_task_service._preflight_ready(runtime, session, task_type)

    begin_immediate(session)
    try:
        plan = _plan(session, profile_id, plan_id)
        row = session.scalars(
            select(LocalAIOperation).where(
                LocalAIOperation.profile_id == profile_id,
                LocalAIOperation.request_id == rid,
            )
        ).first()
        if row is not None:
            result = _replay(row, rid, plan_id, operation_kind, fingerprint)
            rollback(session)
            return result, False
        content = _content(session, plan)
        if content.version != expected_draft_version:
            raise LocalWeeklyVersionConflict(details={"draft_version": content.version})
        for spec in task_specs:
            active = session.scalars(
                select(LocalAITask).where(
                    LocalAITask.profile_id == profile_id,
                    LocalAITask.source_kind == "weekly_plan",
                    LocalAITask.weekly_plan_id == plan.id,
                    LocalAITask.task_type == spec.task_type,
                    LocalAITask.status.in_(ai_task_service.LIVE_STATUSES),
                )
            ).first()
            if active is not None:
                raise LocalWeeklyAiTaskActive(details={"task_id": active.id})
            ai_task_service._require_ai_ready(session, spec.task_type)

        raw = weekly_ai_sources.load_raw_manifest(session, plan=plan, content=content)
        batch_hash = weekly_ai_sources.raw_manifest_hash(raw)
        projections = []
        for spec in task_specs:
            try:
                projection = weekly_ai_inputs.project_weekly_input(
                    spec.task_type, raw, content.content_json
                )
            except Exception as exc:
                code = getattr(exc, "code", "")
                if code == "MATERIAL_CONTEXT_REQUIRED":
                    raise LocalMaterialContextRequired() from None
                raise
            projections.append(projection)
            if runtime is not None:
                _preflight_projection_size(runtime, session, spec.task_type, projection)
        now = ai_task_service._now()
        operation_id = new_opaque_id()
        task_ids = [new_opaque_id() for _ in task_specs]
        input_ids = [new_opaque_id() for _ in task_specs]
        result = _safe_result(rid, operation_kind, plan, content, task_specs, task_ids)
        operation = LocalAIOperation(
            id=operation_id,
            profile_id=profile_id,
            request_id=rid,
            operation_kind=operation_kind,
            request_fingerprint=fingerprint,
            fingerprint_kind="sha256",
            fingerprint_key_id=None,
            result_json=result,
            created_at=now,
        )
        session.add(operation)
        session.flush()
        for spec, projection, task_id, input_id in zip(
            task_specs, projections, task_ids, input_ids
        ):
            deps = dict(projection.dependencies)
            deps["_batch_snapshot_hash"] = batch_hash
            session.add(
                LocalAIInput(
                    id=input_id,
                    profile_id=profile_id,
                    source_kind="weekly_plan",
                    source_id=plan.id,
                    observation_id=None,
                    source_revision=content.version,
                    daily_plan_id=None,
                    content_id=None,
                    content_version=None,
                    weekly_plan_id=plan.id,
                    weekly_draft_id=content.id,
                    create_operation_id=operation_id,
                    task_type=spec.task_type,
                    target_grade=None,
                    input_schema_version=1,
                    payload_json=projection.payload,
                    dependencies_json=deps,
                    dependency_hash=projection.dependency_hash,
                    target_hashes_json=projection.target_hashes,
                    created_at=now,
                )
            )
            session.add(
                LocalAITask(
                    id=task_id,
                    profile_id=profile_id,
                    source_kind="weekly_plan",
                    source_id=plan.id,
                    observation_id=None,
                    daily_plan_id=None,
                    weekly_plan_id=plan.id,
                    task_type=spec.task_type,
                    input_id=input_id,
                    status="pending",
                    reason=None,
                    current_execution_id=None,
                    generation=0,
                    runtime_meta_json=ai_task_service._meta(
                        ai_task_service.CERTAINTY_NOT_SENT
                    ),
                    created_at=now,
                    updated_at=now,
                )
            )
        session.commit()
        return result, True
    except BaseException:
        rollback(session)
        raise


def _preflight_projection_size(runtime: Any, session: Session, task_type: str,
                               projection: Any) -> None:
    from app.local.ai_config_service import _read_config
    from app.local.errors import LocalAiInputTooLarge, LocalAiNotConfigured

    state, config, _credential = _read_config(session)
    if state is None or config is None:
        raise LocalAiNotConfigured()
    head = session.get(LocalPersonalPromptHead, (state.profile_id, task_type))
    version = (
        session.get(
            LocalPersonalPromptVersion,
            (state.profile_id, task_type, head.current_revision),
        )
        if head is not None
        else None
    )
    if version is None:
        raise LocalStorageError("个人指导缺失")
    bundle = session.get(
        LocalPromptBundle,
        (task_type, version.contract_version, version.based_default_revision),
    )
    if bundle is None:
        raise LocalStorageError("提示词包缺失")
    size = ai_task_service.serialized_request_bytes(
        task_type=task_type,
        contract_version=version.contract_version,
        output_schema=dict(bundle.output_schema_json or {}),
        guidance=dict(version.guidance_json or {}),
        payload=projection.payload,
        model=config.model or "",
    )
    if size > ai_transport.REQUEST_MAX_BYTES:
        raise LocalAiInputTooLarge(details={"serialized_bytes": size})


__all__ = [
    "ADOPT",
    "COLUMNS",
    "CREATE_KINDS",
    "GAMES",
    "MATERIALS",
    "OP_KINDS",
    "WeeklyTaskSpec",
    "create_weekly_tasks",
    "get_operation",
    "peek_create_operation",
]
