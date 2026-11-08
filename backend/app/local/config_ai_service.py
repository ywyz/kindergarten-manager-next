"""Class game-configuration AI extraction on the formal AI task lifecycle.

The task is intentionally not a daily-plan task:

* ``source_kind = class_game_config``; the source is the current class and the
  configuration version at submission time;
* the immutable input is only the teacher's pasted text;
* the executor/worker/transport and the pinned prompt bundle do the network
  call (no direct provider request, no parallel executor);
* a successful result is a candidate only.  The existing configuration
  ``preview`` -> ``apply`` path remains the only writer.

The service also provides the idempotent create receipt and a read-only
latest/task/candidate view for the settings panel.
"""

from __future__ import annotations

import hashlib
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ids import new_opaque_id
from app.local import ai_inputs, ai_task_service, config_ai_contracts
from app.local.ai_config_service import _read_config
from app.local.errors import (
    LocalAiInputTooLarge,
    LocalAiNotFound,
    LocalAiTaskActive,
    LocalConfigVersionConflict,
    LocalValidationError,
)
from app.local.models import (
    LocalAICandidate,
    LocalAIInput,
    LocalAITask,
    LocalPersonalPromptHead,
    LocalPersonalPromptVersion,
    LocalPromptBundle,
)
from app.local.profile_service import require_context
from app.local.prompt_bundles import canonical_json
from app.local.tx import begin_immediate, read_scope, rollback

TASK_TYPE = config_ai_contracts.TASK_TYPE
SOURCE_KIND = config_ai_contracts.SOURCE_KIND
OP_CREATE = "config_ai_extract_create"
LIVE_STATUSES = ai_task_service.LIVE_STATUSES


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _fingerprint(
    *, class_id: str, config_version: int, source_text: str
) -> str:
    return _digest(
        {
            "operation_kind": OP_CREATE,
            "class_id": class_id,
            "config_version": config_version,
            "source_text": source_text,
        }
    )


def _validate_expected_version(value: object) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 1
    ):
        raise LocalValidationError("expected_config_version 必须是正整数")
    return value


def _current_context(session: Session):
    context = require_context(session, date.today())
    if context.school_class is None or context.settings is None:
        raise LocalValidationError("当前班级或配置缺失")
    return context


def _candidate_id(session: Session, task: LocalAITask) -> str | None:
    if task.current_execution_id is None:
        return None
    candidate = session.scalars(
        select(LocalAICandidate).where(
            LocalAICandidate.profile_id == task.profile_id,
            LocalAICandidate.execution_id == task.current_execution_id,
        )
    ).first()
    return candidate.id if candidate is not None else None


def task_out(session: Session, task: LocalAITask) -> dict[str, Any]:
    inp = session.get(LocalAIInput, task.input_id)
    certainty = (task.runtime_meta_json or {}).get("processing_certainty") or "not_sent"
    return {
        "task_id": task.id,
        "source_kind": task.source_kind,
        "status": task.status,
        "reason": task.reason,
        "processing_certainty": certainty,
        "candidate_id": _candidate_id(session, task),
        "allowed_actions": ai_task_service._allowed_actions(task),
        "retry_requires_ack": certainty == "unknown",
        "config_version": inp.source_revision if inp is not None else None,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
    }


def _preflight_size(
    session: Session, *, source_text: str, config_version: int
) -> None:
    state, config, _credential = _read_config(session)
    if state is None or config is None or config.model is None:
        return
    head, version = ai_task_service._current_prompt(session, state.profile_id, TASK_TYPE)
    if head is None or version is None:
        return
    bundle = session.get(
        LocalPromptBundle,
        (TASK_TYPE, version.contract_version, version.based_default_revision),
    )
    if bundle is None:
        return
    size = ai_task_service.serialized_request_bytes(
        task_type=TASK_TYPE,
        contract_version=version.contract_version,
        output_schema=dict(bundle.output_schema_json or {}),
        guidance=dict(version.guidance_json or {}),
        payload={"source_text": source_text},
        model=config.model,
    )
    if size > ai_transport_limit():
        raise LocalAiInputTooLarge(
            details={"serialized_bytes": size, "limit": ai_transport_limit()}
        )


def ai_transport_limit() -> int:
    from app.local import ai_transport

    return ai_transport.REQUEST_MAX_BYTES


def peek_create(
    session: Session,
    *,
    request_id: object,
    expected_config_version: object,
    source_text: str,
) -> dict[str, Any] | None:
    expected = _validate_expected_version(expected_config_version)
    rid = ai_task_service._normalize_request_id(request_id)
    with read_scope(session):
        profile_id = ai_task_service._profile_id(session)
        context = _current_context(session)
        class_id = context.school_class.id
        fingerprint = _fingerprint(
            class_id=class_id, config_version=expected, source_text=source_text
        )
        receipt = ai_task_service._find_receipt(session, profile_id, rid)
        if receipt is None:
            return None
        result = ai_task_service._replay(receipt, OP_CREATE, fingerprint)
        task = session.get(LocalAITask, result.get("task_id"))
        if task is None or task.source_kind != SOURCE_KIND:
            return None
        return task_out(session, task)


def create_task(
    session: Session,
    *,
    runtime: Any,
    expected_config_version: object,
    source_text: object,
    request_id: object,
) -> tuple[dict[str, Any], bool]:
    expected = _validate_expected_version(expected_config_version)
    if not isinstance(source_text, str):
        raise LocalValidationError("source_text 必须是字符串")
    if not source_text.strip():
        raise LocalValidationError("source_text 不能为空")
    try:
        config_ai_contracts.validate_input({"source_text": source_text})
    except config_ai_contracts.ConfigAIInputError as exc:
        raise LocalValidationError(str(exc)) from None
    rid = ai_task_service._normalize_request_id(request_id)

    with read_scope(session):
        profile_id = ai_task_service._profile_id(session)
        context = _current_context(session)
        class_id = context.school_class.id
        current_version = context.settings.config_version

    # Receipts are read back before the current version is checked: a lost
    # create response under the original config version must still recover.
    fingerprint = _fingerprint(
        class_id=class_id, config_version=expected, source_text=source_text
    )
    with read_scope(session):
        receipt = ai_task_service._find_receipt(session, profile_id, rid)
    if receipt is not None:
        result = ai_task_service._replay(receipt, OP_CREATE, fingerprint)
        task = session.get(LocalAITask, result.get("task_id"))
        if task is None:
            raise LocalAiNotFound("未找到原解析任务")
        return task_out(session, task), False

    if current_version != expected:
        raise LocalConfigVersionConflict(details={"config_version": current_version})

    # Readiness and size are advisory preflight checks; the executor re-checks
    # them at claim time against the pinned versions.
    ai_task_service._preflight_ready(runtime, session, TASK_TYPE)
    with read_scope(session):
        _preflight_size(session, source_text=source_text, config_version=current_version)

    begin_immediate(session)
    try:
        profile_id = ai_task_service._profile_id(session)
        receipt = ai_task_service._find_receipt(session, profile_id, rid)
        if receipt is not None:
            result = ai_task_service._replay(receipt, OP_CREATE, fingerprint)
            task = session.get(LocalAITask, result.get("task_id"))
            if task is None:
                raise LocalAiNotFound("未找到原解析任务")
            summary = task_out(session, task)
            rollback(session)
            return summary, False

        context = _current_context(session)
        class_id = context.school_class.id
        if context.settings.config_version != current_version:
            raise LocalConfigVersionConflict(
                details={"config_version": context.settings.config_version}
            )
        active = session.scalars(
            select(LocalAITask).where(
                LocalAITask.profile_id == profile_id,
                LocalAITask.source_kind == SOURCE_KIND,
                LocalAITask.source_id == class_id,
                LocalAITask.task_type == TASK_TYPE,
                LocalAITask.status.in_(LIVE_STATUSES),
            )
        ).first()
        if active is not None:
            raise LocalAiTaskActive(details={"task_id": active.id})

        task_id = new_opaque_id()
        input_id = new_opaque_id()
        now = ai_task_service._now()
        try:
            projected = ai_inputs.project_config_input(
                source_text=source_text,
                class_id=class_id,
                config_version=current_version,
            )
        except config_ai_contracts.ConfigAIInputError as exc:
            raise LocalValidationError(str(exc)) from None
        session.add(
            LocalAIInput(
                id=input_id,
                profile_id=profile_id,
                source_kind=SOURCE_KIND,
                source_id=class_id,
                observation_id=None,
                source_revision=current_version,
                daily_plan_id=None,
                content_id=None,
                content_version=None,
                weekly_plan_id=None,
                weekly_draft_id=None,
                listening_record_id=None,
                listening_domain=None,
                listening_group_id=None,
                create_operation_id=None,
                task_type=TASK_TYPE,
                target_grade=None,
                input_schema_version=config_ai_contracts.INPUT_SCHEMA_VERSION,
                payload_json=projected["payload"],
                dependencies_json=projected["dependencies"],
                dependency_hash=projected["dependency_hash"],
                target_hashes_json=projected["target_hashes"],
                created_at=now,
            )
        )
        session.add(
            LocalAITask(
                id=task_id,
                profile_id=profile_id,
                source_kind=SOURCE_KIND,
                source_id=class_id,
                observation_id=None,
                daily_plan_id=None,
                weekly_plan_id=None,
                listening_record_id=None,
                listening_domain=None,
                listening_group_id=None,
                task_type=TASK_TYPE,
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
        ai_task_service._store_receipt(
            session,
            profile_id=profile_id,
            request_id=rid,
            operation_kind=OP_CREATE,
            fingerprint=fingerprint,
            result={"task_id": task_id, "source_kind": SOURCE_KIND},
        )
        session.commit()
        task = session.get(LocalAITask, task_id)
        if task is None:
            raise LocalAiNotFound("未找到新建解析任务")
        return task_out(session, task), True
    except IntegrityError:
        rollback(session)
        # A concurrent same-key create may have committed first.  Re-read the
        # receipt before treating the unique active index as a different task.
        with read_scope(session):
            receipt = ai_task_service._find_receipt(session, profile_id, rid)
            if receipt is not None:
                result = ai_task_service._replay(receipt, OP_CREATE, fingerprint)
                task = session.get(LocalAITask, result.get("task_id"))
                if task is not None:
                    return task_out(session, task), False
        raise LocalAiTaskActive() from None
    except BaseException:
        rollback(session)
        raise


def get_task(session: Session, *, task_id: str) -> dict[str, Any]:
    with read_scope(session):
        profile_id = ai_task_service._profile_id(session)
        context = _current_context(session)
        task = session.get(LocalAITask, task_id)
        if (
            task is None
            or task.profile_id != profile_id
            or task.source_kind != SOURCE_KIND
            or task.source_id != context.school_class.id
        ):
            raise LocalAiNotFound("未找到班级游戏配置解析任务")
        return task_out(session, task)


def latest_task(session: Session) -> dict[str, Any] | None:
    with read_scope(session):
        profile_id = ai_task_service._profile_id(session)
        context = _current_context(session)
        task = session.scalars(
            select(LocalAITask)
            .where(
                LocalAITask.profile_id == profile_id,
                LocalAITask.source_kind == SOURCE_KIND,
                LocalAITask.source_id == context.school_class.id,
                LocalAITask.task_type == TASK_TYPE,
            )
            .order_by(LocalAITask.created_at.desc(), LocalAITask.id.desc())
        ).first()
        return task_out(session, task) if task is not None else None


def get_candidate(session: Session, *, candidate_id: str) -> dict[str, Any]:
    with read_scope(session):
        profile_id = ai_task_service._profile_id(session)
        context = _current_context(session)
        candidate = session.get(LocalAICandidate, candidate_id)
        if (
            candidate is None
            or candidate.profile_id != profile_id
            or candidate.source_kind != SOURCE_KIND
            or candidate.source_id != context.school_class.id
        ):
            raise LocalAiNotFound("未找到班级游戏配置解析候选")
        inp = session.get(LocalAIInput, candidate.input_id)
        return {
            "candidate_id": candidate.id,
            "task_id": candidate.task_id,
            "task_type": candidate.task_type,
            "raw_candidate": dict(candidate.raw_candidate_json or {}),
            "source": {
                "source_kind": SOURCE_KIND,
                "class_id": candidate.source_id,
                "config_version": inp.source_revision if inp is not None else None,
            },
            "created_at": candidate.created_at.isoformat() if candidate.created_at else None,
        }


__all__ = [
    "TASK_TYPE",
    "SOURCE_KIND",
    "OP_CREATE",
    "peek_create",
    "create_task",
    "get_task",
    "latest_task",
    "get_candidate",
]
