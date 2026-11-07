"""One-to-one listening AI task submission and read-only receipts."""

from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ids import new_opaque_id
from app.local import ai_task_service, listening_ai_contracts, listening_ai_inputs
from app.local.errors import (
    LocalAiInputTooLarge,
    LocalAiNotFound,
    LocalAiOperationNotFound,
    LocalAiTaskActive,
    LocalStorageError,
    LocalValidationError,
    LocalVersionConflict,
)
from app.local.models import (
    LocalAICandidate,
    LocalAIExecution,
    LocalAIInput,
    LocalAIOperation,
    LocalAITask,
)
from app.local.normalize import normalize_request_id
from app.local.prompt_bundles import canonical_json
from app.local.tx import begin_immediate, read_scope, rollback

SOURCE_KIND = "one_to_one_listening"
OP_NOTE_CREATE = "listening_ai_note_create"
OP_DOMAIN_CREATE = "listening_ai_domain_create"
OP_KINDS = (OP_NOTE_CREATE, OP_DOMAIN_CREATE)


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _op_kind(task_type: str) -> str:
    if task_type == listening_ai_contracts.TASK_NOTE:
        return OP_NOTE_CREATE
    if task_type == listening_ai_contracts.TASK_DOMAIN:
        return OP_DOMAIN_CREATE
    raise LocalValidationError("不支持的倾听 AI 任务类型")


def _fingerprint(task_type: str, payload: dict[str, Any]) -> str:
    return _digest(
        {"operation_kind": _op_kind(task_type), "payload": payload}
    )


def _replay(
    row: LocalAIOperation,
    *,
    request_id: str,
    record_id: str,
    operation_kind: str,
    fingerprint: str,
) -> dict[str, Any]:
    result = dict(row.result_json or {})
    if result.get("listening_record_id") != record_id:
        raise LocalAiOperationNotFound()
    if row.operation_kind != operation_kind or row.request_fingerprint != fingerprint:
        raise LocalValidationError("同一请求已用于不同倾听 AI 操作")
    result["replayed"] = True
    return result


def peek_create(
    session: Session,
    *,
    profile_id: str,
    record_id: str,
    request_id: object,
    task_type: str,
    expected_revision: object,
    domain: str,
    group_id: str | None,
) -> dict[str, Any] | None:
    rid = normalize_request_id(request_id)
    fingerprint = _fingerprint(
        task_type,
        {
            "record_id": record_id,
            "task_type": task_type,
            "expected_revision": expected_revision,
            "domain": domain,
            "group_id": group_id,
        },
    )
    with read_scope(session):
        row = session.scalars(
            select(LocalAIOperation).where(
                LocalAIOperation.profile_id == profile_id,
                LocalAIOperation.request_id == rid,
            )
        ).first()
        if row is None:
            return None
        return _replay(
            row,
            request_id=rid,
            record_id=record_id,
            operation_kind=_op_kind(task_type),
            fingerprint=fingerprint,
        )


def get_operation(
    session: Session, *, profile_id: str, record_id: str, request_id: str
) -> dict[str, Any]:
    rid = normalize_request_id(request_id)
    with read_scope(session):
        row = session.scalars(
            select(LocalAIOperation).where(
                LocalAIOperation.profile_id == profile_id,
                LocalAIOperation.request_id == rid,
            )
        ).first()
        if row is None:
            raise LocalAiOperationNotFound()
        operation_kind = row.operation_kind
        result_json = dict(row.result_json or {})
        created_at = row.created_at.isoformat()
        stored_request_id = row.request_id
    if operation_kind == "listening_ai_adopt":
        from app.local import listening_ai_adoption

        return listening_ai_adoption.read_operation(
            session,
            profile_id=profile_id,
            record_id=record_id,
            request_id=rid,
        )
    if operation_kind not in OP_KINDS:
        raise LocalAiOperationNotFound()
    if result_json.get("listening_record_id") != record_id:
        raise LocalAiOperationNotFound()
    return {
        "request_id": stored_request_id,
        "operation_kind": operation_kind,
        "status": "committed",
        "result": result_json,
        "created_at": created_at,
    }


def create_task(
    session: Session,
    *,
    runtime: Any,
    profile_id: str,
    record_id: str,
    domain: str,
    group_id: str | None,
    task_type: str,
    expected_revision: object,
    request_id: object,
) -> tuple[dict[str, Any], bool]:
    if task_type not in listening_ai_contracts.TASK_TYPES:
        raise LocalValidationError("不支持的倾听 AI 任务类型")
    if (
        isinstance(expected_revision, bool)
        or not isinstance(expected_revision, int)
        or expected_revision < 1
    ):
        raise LocalValidationError("expected_revision 必须是正整数")
    rid = normalize_request_id(request_id)
    fingerprint = _fingerprint(
        task_type,
        {
            "record_id": record_id,
            "task_type": task_type,
            "expected_revision": expected_revision,
            "domain": domain,
            "group_id": group_id,
        },
    )
    with read_scope(session):
        row = session.scalars(
            select(LocalAIOperation).where(
                LocalAIOperation.profile_id == profile_id,
                LocalAIOperation.request_id == rid,
            )
        ).first()
        if row is not None:
            return (
                _replay(
                    row,
                    request_id=rid,
                    record_id=record_id,
                    operation_kind=_op_kind(task_type),
                    fingerprint=fingerprint,
                ),
                False,
            )
        try:
            projection = listening_ai_inputs.project(
                session,
                runtime,
                profile_id=profile_id,
                record_id=record_id,
                domain=domain,
                group_id=group_id,
                task_type=task_type,
            )
        except listening_ai_contracts.ListeningAIContractError:
            raise LocalValidationError("倾听 AI 输入不合法") from None
        prepared_photos = {
            item["group_id"]: dict(item)
            for item in projection.dependencies.get("photos") or []
        }
        if projection.source_revision != expected_revision:
            raise LocalVersionConflict(
                details={"current_revision": projection.source_revision}
            )
        ai_task_service._require_ai_ready(session, task_type)
    try:
        ai_task_service._preflight_ready(runtime, session, task_type)
    except Exception:
        raise

    now = ai_task_service._now()
    operation_id = new_opaque_id()
    task_id = new_opaque_id()
    input_id = new_opaque_id()
    begin_immediate(session)
    try:
        row = session.scalars(
            select(LocalAIOperation).where(
                LocalAIOperation.profile_id == profile_id,
                LocalAIOperation.request_id == rid,
            )
        ).first()
        if row is not None:
            result = _replay(
                row,
                request_id=rid,
                record_id=record_id,
                operation_kind=_op_kind(task_type),
                fingerprint=fingerprint,
            )
            rollback(session)
            return result, False
        projection = listening_ai_inputs.project(
            session,
            None,
            profile_id=profile_id,
            record_id=record_id,
            domain=domain,
            group_id=group_id,
            task_type=task_type,
            stored_photos=prepared_photos,
        )
        if projection.source_revision != expected_revision:
            raise LocalVersionConflict(
                details={"current_revision": projection.source_revision}
            )
        active = session.scalars(
            select(LocalAITask).where(
                LocalAITask.profile_id == profile_id,
                LocalAITask.source_kind == SOURCE_KIND,
                LocalAITask.listening_record_id == record_id,
                LocalAITask.listening_domain == domain,
                LocalAITask.listening_group_id == group_id,
                LocalAITask.task_type == task_type,
                LocalAITask.status.in_(ai_task_service.LIVE_STATUSES),
            )
        ).first()
        if active is not None:
            raise LocalAiTaskActive(details={"task_id": active.id})
        result = {
            "request_id": rid,
            "operation_kind": _op_kind(task_type),
            "listening_record_id": record_id,
            "domain": domain,
            "group_id": group_id,
            "task_type": task_type,
            "task_id": task_id,
            "replayed": False,
        }
        session.add(
            LocalAIOperation(
                id=operation_id,
                profile_id=profile_id,
                request_id=rid,
                operation_kind=_op_kind(task_type),
                request_fingerprint=fingerprint,
                fingerprint_kind="sha256",
                fingerprint_key_id=None,
                result_json=result,
                created_at=now,
            )
        )
        session.flush()
        session.add(
            LocalAIInput(
                id=input_id,
                profile_id=profile_id,
                source_kind=SOURCE_KIND,
                source_id=record_id,
                observation_id=None,
                source_revision=projection.source_revision,
                daily_plan_id=None,
                content_id=None,
                content_version=None,
                weekly_plan_id=None,
                weekly_draft_id=None,
                listening_record_id=record_id,
                listening_domain=domain,
                listening_group_id=group_id,
                create_operation_id=operation_id,
                task_type=task_type,
                target_grade=None,
                input_schema_version=listening_ai_inputs.AI_SCHEMA_VERSION,
                payload_json=projection.payload,
                dependencies_json=projection.dependencies,
                dependency_hash=projection.dependency_hash,
                target_hashes_json=projection.target_hashes,
                created_at=now,
            )
        )
        session.add(
            LocalAITask(
                id=task_id,
                profile_id=profile_id,
                source_kind=SOURCE_KIND,
                source_id=record_id,
                observation_id=None,
                daily_plan_id=None,
                weekly_plan_id=None,
                listening_record_id=record_id,
                listening_domain=domain,
                listening_group_id=group_id,
                task_type=task_type,
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
        session.flush()
        session.commit()
        return result, True
    except IntegrityError as exc:
        rollback(session)
        raise LocalStorageError("倾听 AI 任务写入失败") from exc
    except BaseException:
        rollback(session)
        raise


def list_tasks(
    session: Session,
    *,
    profile_id: str,
    record_id: str,
    domain: str | None = None,
    status: str | None = None,
    limit: object = ai_task_service.DEFAULT_LIST_LIMIT,
    cursor: str | None = None,
) -> dict[str, Any]:
    return ai_task_service.list_tasks(
        session,
        source_kind=SOURCE_KIND,
        source_id=record_id,
        listening_domain=domain,
        status=status,
        limit=limit,
        cursor=cursor,
    )


def get_task(
    session: Session, *, profile_id: str, record_id: str, task_id: str
) -> dict[str, Any]:
    return ai_task_service.get_task(
        session,
        task_id,
        source_kind=SOURCE_KIND,
        source_id=record_id,
    )


def require_candidate_chain(
    session: Session,
    *,
    profile_id: str,
    record_id: str,
    candidate_id: str,
) -> tuple[LocalAICandidate, LocalAITask, LocalAIInput, LocalAIExecution]:
    """The single complete candidate/task/input/execution binding check.

    The candidate's typed record/domain/group must equal the task, frozen input
    and execution.  A perfectly valid candidate moved to another group of the
    same record is therefore never displayed or adoptable.
    """
    candidate = session.get(LocalAICandidate, candidate_id)
    if (
        candidate is None
        or candidate.profile_id != profile_id
        or candidate.source_kind != SOURCE_KIND
        or candidate.source_id != record_id
        or candidate.listening_record_id != record_id
    ):
        raise LocalAiNotFound("未找到该倾听 AI 候选")
    task = session.get(LocalAITask, candidate.task_id)
    if (
        task is None
        or task.profile_id != profile_id
        or task.source_kind != SOURCE_KIND
        or task.source_id != record_id
        or task.listening_record_id != record_id
        or task.listening_domain != candidate.listening_domain
        or task.listening_group_id != candidate.listening_group_id
        or task.input_id != candidate.input_id
        or task.task_type != candidate.task_type
    ):
        raise LocalStorageError("倾听 AI 候选任务绑定不一致")
    inp = session.get(LocalAIInput, task.input_id)
    if (
        inp is None
        or inp.profile_id != profile_id
        or inp.source_kind != SOURCE_KIND
        or inp.source_id != record_id
        or inp.listening_record_id != record_id
        or inp.listening_domain != candidate.listening_domain
        or inp.listening_group_id != candidate.listening_group_id
        or inp.id != candidate.input_id
        or inp.task_type != candidate.task_type
    ):
        raise LocalStorageError("倾听 AI 候选输入绑定不一致")
    execution = session.get(LocalAIExecution, candidate.execution_id)
    if (
        execution is None
        or execution.profile_id != profile_id
        or execution.source_kind != SOURCE_KIND
        or execution.source_id != record_id
        or execution.listening_record_id != record_id
        or execution.listening_domain != candidate.listening_domain
        or execution.listening_group_id != candidate.listening_group_id
        or execution.task_id != task.id
        or execution.input_id != inp.id
        or execution.task_type != candidate.task_type
        or execution.contract_version != candidate.contract_version
        or execution.state != "succeeded"
        or task.current_execution_id != execution.id
        or task.status != "succeeded"
        or candidate.contract_version != listening_ai_contracts.CONTRACT_VERSION
    ):
        raise LocalStorageError("倾听 AI 候选执行绑定不一致")
    raw = dict(candidate.raw_candidate_json or {})
    try:
        validated = listening_ai_contracts.validate_candidate(
            candidate.task_type, raw
        )
    except listening_ai_contracts.ListeningAIContractError:
        raise LocalStorageError("倾听 AI 候选结构损坏") from None
    if validated != raw or _digest(raw) != candidate.candidate_hash:
        raise LocalStorageError("倾听 AI 候选摘要不一致")
    if candidate.task_type == listening_ai_contracts.TASK_DOMAIN:
        expected_ids = [
            item.get("item_id")
            for item in dict(inp.payload_json or {}).get("items") or []
        ]
        actual_ids = [item.get("item_id") for item in validated.get("items") or []]
        if (
            len(actual_ids) != len(set(actual_ids))
            or set(actual_ids) != set(expected_ids)
            or len(actual_ids) != len(expected_ids)
        ):
            raise LocalStorageError("倾听 AI 候选项目集合与冻结模板不一致")
    if candidate.listening_group_id is not None:
        from app.local.models import LocalListeningPhotoGroup

        group = session.get(LocalListeningPhotoGroup, candidate.listening_group_id)
        payload = dict(inp.payload_json or {})
        if (
            group is None
            or group.record_id != record_id
            or group.domain != candidate.listening_domain
            or group.position != payload.get("group_position")
        ):
            raise LocalStorageError("倾听 AI 候选小组绑定不一致")
    return candidate, task, inp, execution


def get_candidate(
    session: Session, *, profile_id: str, record_id: str, task_id: str
) -> dict[str, Any]:
    with read_scope(session):
        task = ai_task_service.require_task(
            session,
            task_id,
            source_kind=SOURCE_KIND,
            source_id=record_id,
        )
        if task.profile_id != profile_id or task.listening_record_id != record_id:
            raise LocalAiNotFound("未找到该倾听 AI 任务")
        candidate = session.scalars(
            select(LocalAICandidate).where(
                LocalAICandidate.profile_id == profile_id,
                LocalAICandidate.source_kind == SOURCE_KIND,
                LocalAICandidate.source_id == record_id,
                LocalAICandidate.task_id == task_id,
            )
        ).first()
        if candidate is None:
            raise LocalAiNotFound("该倾听 AI 任务尚无候选")
        candidate, task, inp, execution = require_candidate_chain(
            session,
            profile_id=profile_id,
            record_id=record_id,
            candidate_id=candidate.id,
        )
        return {
            "task": ai_task_service.task_out(session, task),
            "candidate_id": candidate.id,
            "candidate": dict(candidate.raw_candidate_json or {}),
            "candidate_hash": candidate.candidate_hash,
            "input_id": inp.id,
        }


__all__ = [
    "SOURCE_KIND",
    "OP_KINDS",
    "create_task",
    "get_candidate",
    "get_operation",
    "get_task",
    "list_tasks",
    "peek_create",
]
