"""D2 W3 persistent task service and scheduling state machine.

Engineering spec §2, §4.1, §4.3, §5.2, §10.

Responsibilities:

* task submission with the immutable business-input projection and the
  cross-domain idempotent receipt (``local_ai_operations``); the receipt check
  always runs *before* any version/state check;
* list / detail / cancel / resume / retry;
* the executor-facing state machine: a three-phase claim (decide → load
  material **outside** any DB transaction → re-verify and commit), the
  dispatch mark, bounded retry wait, terminal finalisation, cold-start
  recovery, and credential收口 after every execution end.

Every state change re-checks the full permit (task ↔ execution link,
``permit_id``, ``launch_id``, ``generation``) inside the write transaction and
never trusts a client flag. A retry reuses the *versions pinned by the
existing execution* (including a ``retired`` credential still needed for a
safe retry); a new execution pins the then-current versions. DPAPI / ACL work
never runs inside a write transaction.
"""

from __future__ import annotations

import base64
import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ids import new_opaque_id
from app.local import ai_inputs, ai_transport
from app.local.base import utc_now
from app.local.errors import (
    LocalAiContractUnsupported,
    LocalAiInputTooLarge,
    LocalAiNotConfigured,
    LocalAiNotFound,
    LocalAiRequestConflict,
    LocalAiRetryAckRequired,
    LocalAiSourceChanged,
    LocalAiTaskActive,
    LocalAiTaskStateConflict,
    LocalProfileRequired,
    LocalStorageError,
    LocalValidationError,
    LocalVersionConflict,
)
from app.local.models import (
    LocalAIState,
    LocalAIAttempt,
    LocalAICandidate,
    LocalAIConfigVersion,
    LocalAICredential,
    LocalAIExecution,
    LocalAIInput,
    LocalAIOperation,
    LocalAITask,
    LocalDailyPlan,
    LocalDailyPlanContent,
    LocalPersonalPromptHead,
    LocalPersonalPromptVersion,
    LocalProfile,
    LocalPromptBundle,
)
from app.local.prompt_bundles import (
    PACKAGE_CONTRACT_VERSION,
    TASK_TYPES,
    CandidateInvalid,
    canonical_json,
    validate_candidate,
)
from app.local.tx import begin_immediate, read_scope, rollback

LIVE_STATUSES = ("pending", "claimed", "dispatching", "retry_wait")
TERMINAL_STATUSES = ("succeeded", "failed", "outcome_unknown", "cancelled")

# This build only ships the frozen v1 contract. A pinned/required contract
# outside this set is never run through the v1 validator (spec §7 note).
SUPPORTED_CONTRACT_VERSIONS = (PACKAGE_CONTRACT_VERSION,)

OP_CREATE = "ai_task_create"
OP_CANCEL = "ai_task_cancel"
OP_RESUME = "ai_task_resume"
OP_RETRY = "ai_task_retry"

MAX_ATTEMPTS = 3
DEFAULT_LIST_LIMIT = 20
MAX_LIST_LIMIT = 100

CERTAINTY_NOT_SENT = "not_sent"
CERTAINTY_RESPONSE = "response_received"
CERTAINTY_UNKNOWN = "unknown"

# Reasons that mean the task may already have reached the provider.
_SENT_REASONS = frozenset(
    {"provider_error", "timeout_after_dispatch", "rate_limited", "user_stop"}
)

_DEFAULT_WAIT_SECONDS = (5, 30)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _now() -> datetime:
    return utc_now()


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _normalize_request_id(value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        raise LocalValidationError("request_id 必须是 UUID")


def _meta(
    certainty: str,
    *,
    user_stop: bool = False,
    permit_revoked_at: datetime | None = None,
    next_attempt_at: datetime | None = None,
) -> dict[str, Any]:
    return {
        "processing_certainty": certainty,
        "user_stop_requested": bool(user_stop),
        "permit_revoked_at": _iso(permit_revoked_at),
        "next_attempt_at": _iso(next_attempt_at),
    }


def _profile_id(session: Session) -> str:
    row = session.scalars(select(LocalProfile)).first()
    if row is None:
        raise LocalProfileRequired()
    return row.id


def require_task(
    session: Session, task_id: str, *, source_kind: str = "daily_plan"
) -> LocalAITask:
    task = session.get(LocalAITask, task_id, populate_existing=True)
    if task is None or task.source_kind != source_kind:
        raise LocalAiNotFound("未找到该 AI 任务")
    return task


def _attempt_no(session: Session, execution_id: str) -> int:
    return int(
        session.scalar(
            select(func.max(LocalAIAttempt.attempt_no)).where(
                LocalAIAttempt.execution_id == execution_id
            )
        )
        or 0
    )


def _certainty(task: LocalAITask) -> str:
    return (task.runtime_meta_json or {}).get("processing_certainty") or CERTAINTY_NOT_SENT


def _cleanup_credentials(session: Session, profile_id: str, now: datetime) -> None:
    """Clear credentials no longer pinned by a live execution/task.

    The pending execution/task changes must be visible to the retained-set
    query first (the session has ``autoflush=False``), otherwise a just-ended
    execution still looks live and keeps its old key material.
    """
    from app.local.ai_config_service import _clear_replaced_credentials

    session.flush()
    state = session.get(LocalAIState, profile_id)
    keep_id = None
    if state is not None and state.current_config_version is not None:
        config = session.get(
            LocalAIConfigVersion, (profile_id, state.current_config_version)
        )
        keep_id = config.credential_id if config is not None else None
    _clear_replaced_credentials(session, profile_id, keep_id, now)


# ---------------------------------------------------------------------------
# Receipts (cross-domain idempotency)
# ---------------------------------------------------------------------------


def _find_receipt(session: Session, profile_id: str, request_id: str):
    return session.scalars(
        select(LocalAIOperation).where(
            LocalAIOperation.profile_id == profile_id,
            LocalAIOperation.request_id == request_id,
        )
    ).first()


def _fingerprint(operation_kind: str, payload: dict[str, Any]) -> str:
    return _digest({"operation_kind": operation_kind, "payload": payload})


def _replay(
    receipt: LocalAIOperation, operation_kind: str, fingerprint: str
) -> dict[str, Any]:
    if receipt.operation_kind != operation_kind or receipt.request_fingerprint != fingerprint:
        raise LocalAiRequestConflict(
            "同一请求 ID 已用于不同操作或不同内容，不得自动换键"
        )
    return dict(receipt.result_json or {})


def _store_receipt(
    session: Session,
    *,
    profile_id: str,
    request_id: str,
    operation_kind: str,
    fingerprint: str,
    result: dict[str, Any],
) -> None:
    session.add(
        LocalAIOperation(
            id=new_opaque_id(),
            profile_id=profile_id,
            request_id=request_id,
            operation_kind=operation_kind,
            request_fingerprint=fingerprint,
            fingerprint_kind="sha256",
            fingerprint_key_id=None,
            result_json=result,
            created_at=_now(),
        )
    )


def peek_operation(
    session: Session,
    *,
    request_id: object,
    operation_kind: str,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    """Return a committed receipt's result, or None when no receipt exists.

    Used by the API so a same-key committed operation is read back *before*
    any executor-availability check; a same-key/different-body request still
    raises ``AI_REQUEST_CONFLICT``.
    """
    rid = _normalize_request_id(request_id)
    fingerprint = _fingerprint(operation_kind, payload)
    with read_scope(session):
        profile_id = _profile_id(session)
        receipt = _find_receipt(session, profile_id, rid)
        if receipt is None:
            return None
        return _replay(receipt, operation_kind, fingerprint)


def _preflight_size(
    runtime: Any,
    session: Session,
    task_type: str,
    target_grade: object,
    plan_id: str,
    holiday_provider: ai_inputs.HolidayProvider | None,
) -> None:
    """Refuse an over-limit *serialized* request before creating anything.

    Runs outside the write transaction; the authoritative re-check happens at
    claim time against the pinned versions.
    """
    from app.local.ai_config_service import _read_config

    with read_scope(session):
        plan, content = _load_plan_and_content(session, plan_id)
        projected = ai_inputs.project_input(
            session,
            plan=plan,
            content=content,
            task_type=task_type,
            target_grade=target_grade,
            holiday_provider=holiday_provider,
        )
        state, config, _credential = _read_config(session)
        model = config.model if config is not None else ""
        head, version = _current_prompt(session, state.profile_id if state else "", task_type)
        bundle = None
        guidance: dict[str, Any] = {}
        output_schema: dict[str, Any] = {}
        if version is not None:
            guidance = dict(version.guidance_json or {})
            bundle = session.get(
                LocalPromptBundle,
                (task_type, version.contract_version, version.based_default_revision),
            )
        if bundle is not None:
            output_schema = dict(bundle.output_schema_json or {})
    size = serialized_request_bytes(
        task_type=task_type,
        contract_version=version.contract_version if version else 1,
        output_schema=output_schema,
        guidance=guidance,
        payload=projected.payload,
        model=model or "",
    )
    if size > ai_transport.REQUEST_MAX_BYTES:
        raise LocalAiInputTooLarge(
            details={
                "serialized_bytes": size,
                "limit": ai_transport.REQUEST_MAX_BYTES,
            }
        )


def _preflight_ready(runtime: Any, session: Session, task_type: str) -> None:
    """Advisory AI readiness before the write transaction.

    The authoritative re-check happens at claim time. DPAPI/ACL work runs here,
    outside any write transaction, so a slow credential read never holds a
    content write lock.
    """
    from app.local.errors import LocalCredentialUnavailable, LocalPromptSyncUnavailable
    from app.local.ai_config_service import _build_store, _decrypt_secret, _read_config

    error = getattr(runtime, "prompt_sync_error", None)
    if error:
        raise LocalPromptSyncUnavailable(details={"reason": error})
    with read_scope(session):
        _require_ai_ready(session, task_type)
        state, config, credential = _read_config(session)
        if state is None:
            raise LocalProfileRequired()
        if config is None or config.credential_id is None:
            raise LocalAiNotConfigured()
        profile_id = state.profile_id
        database_uuid = state.database_uuid
        credential_id = config.credential_id
        credential_root = getattr(runtime, "credential_root", None)
    store = _build_store(profile_id, database_uuid, credential_root)
    secret = _decrypt_secret(credential, store, profile_id, credential_id)
    if secret is None:
        raise LocalCredentialUnavailable()


# ---------------------------------------------------------------------------
# Output projection
# ---------------------------------------------------------------------------


def _allowed_actions(task: LocalAITask) -> list[str]:
    status = task.status
    certainty = _certainty(task)
    if status in ("pending", "claimed", "dispatching", "retry_wait"):
        return ["cancel"]
    if status == "succeeded":
        return ["view"]
    if status == "cancelled":
        return ["view"]
    if status in ("failed", "outcome_unknown"):
        return ["retry", "view"]
    if status == "paused":
        actions: list[str] = []
        if task.reason != "source_changed":
            if certainty == CERTAINTY_NOT_SENT:
                actions.append("resume")
            actions.append("retry")
        actions.extend(["cancel", "view"])
        return actions
    return ["view"]


def task_out(session: Session, task: LocalAITask) -> dict[str, Any]:
    inp = session.get(LocalAIInput, task.input_id)
    meta = dict(task.runtime_meta_json or {})
    certainty = _certainty(task)
    execution_out = None
    candidate_id = None
    if task.current_execution_id:
        execution = session.get(LocalAIExecution, task.current_execution_id)
        if execution is not None:
            execution_out = {
                "id": execution.id,
                "generation": execution.generation,
                "ai_config_version": execution.config_version,
                "personal_revision": execution.personal_revision,
                "contract_version": execution.contract_version,
                "default_revision": execution.default_revision,
                "attempt_no": _attempt_no(session, execution.id) or None,
            }
            try:
                candidate = session.scalars(
                    select(LocalAICandidate).where(
                        LocalAICandidate.execution_id == execution.id
                    )
                ).first()
            except ValueError:
                raise LocalStorageError("候选内容损坏") from None
            candidate_id = candidate.id if candidate is not None else None
    input_summary: dict[str, Any] = {
        "content_version": inp.content_version if inp else None,
        "target_grade": inp.target_grade if inp else None,
        "dependency_hash": inp.dependency_hash if inp else None,
        "source_revision": inp.source_revision if inp else None,
    }
    if inp is not None:
        warning = ai_inputs.calendar_coverage_warning(inp.dependencies_json or {})
        if warning is not None:
            input_summary["calendar_coverage_warning"] = warning
        if inp.source_kind == "game_observation":
            deps = dict(inp.dependencies_json or {})
            internal = dict(deps.get("internal") or {})
            input_summary["input_schema_version"] = inp.input_schema_version
            input_summary["wire_schema_version"] = internal.get("wire_schema_version")
            input_summary["missing_fields"] = list(internal.get("missing_fields") or [])
            input_summary["warnings"] = list(internal.get("warnings") or [])
    result = {
        "id": task.id,
        "plan_id": task.daily_plan_id,
        "task_type": task.task_type,
        "status": task.status,
        "reason": task.reason,
        "processing_certainty": certainty,
        "user_stop_requested": bool(meta.get("user_stop_requested")),
        "created_at": _iso(task.created_at),
        "updated_at": _iso(task.updated_at),
        "input_summary": input_summary,
        "execution": execution_out,
        "candidate_id": candidate_id,
        "allowed_actions": _allowed_actions(task),
        "retry_requires_ack": certainty == CERTAINTY_UNKNOWN,
    }
    if task.source_kind == "game_observation":
        result["source_kind"] = task.source_kind
        result["observation_id"] = task.observation_id
    return result


# ---------------------------------------------------------------------------
# Submission
# ---------------------------------------------------------------------------


def _load_plan_and_content(
    session: Session, plan_id: str
) -> tuple[LocalDailyPlan, LocalDailyPlanContent]:
    from app.local.daily_plan_service import _load_content

    plan = session.get(LocalDailyPlan, plan_id, populate_existing=True)
    if plan is None or plan.deleted_at is not None:
        raise LocalAiNotFound("未找到该日计划")
    return plan, _load_content(session, plan)


def _current_prompt(session: Session, profile_id: str, task_type: str):
    head = session.get(LocalPersonalPromptHead, (profile_id, task_type))
    if head is None:
        return None, None
    version = session.get(
        LocalPersonalPromptVersion, (profile_id, task_type, head.current_revision)
    )
    return head, version


def _require_ai_ready(session: Session, task_type: str) -> None:
    from app.local.ai_config_service import _read_config

    state, config, _credential = _read_config(session)
    if state is None:
        raise LocalProfileRequired()
    if config is None or config.base_url is None or config.model is None or config.credential_id is None:
        raise LocalAiNotConfigured()
    head, version = _current_prompt(session, state.profile_id, task_type)
    if head is None or version is None:
        raise LocalStorageError("个人指导缺失")
    if head.required_contract_version not in SUPPORTED_CONTRACT_VERSIONS:
        raise LocalAiContractUnsupported()
    if version.contract_version not in SUPPORTED_CONTRACT_VERSIONS:
        raise LocalAiContractUnsupported()
    if version.contract_version != head.required_contract_version:
        from app.local.errors import LocalPromptAdaptationRequired

        raise LocalPromptAdaptationRequired()


def create_task(
    session: Session,
    *,
    plan_id: str,
    task_type: object,
    expected_content_version: object,
    target_grade: object,
    request_id: object,
    holiday_provider: ai_inputs.HolidayProvider | None = None,
    runtime: Any | None = None,
) -> tuple[dict[str, Any], bool]:
    """Submit one task; return ``(TaskOut, created)``."""
    if task_type not in TASK_TYPES:
        raise LocalValidationError("不支持的日任务类型")
    if (
        not isinstance(expected_content_version, int)
        or isinstance(expected_content_version, bool)
        or expected_content_version < 1
    ):
        raise LocalValidationError("expected_content_version 必须是正整数")
    rid = _normalize_request_id(request_id)

    fingerprint = _fingerprint(
        OP_CREATE,
        {
            "plan_id": plan_id,
            "task_type": task_type,
            "expected_content_version": expected_content_version,
            "target_grade": target_grade,
        },
    )
    # Receipt priority: a committed re-send is read back before anything else,
    # including the executor/credential readiness checks.
    with read_scope(session):
        profile_id = _profile_id(session)
        receipt = _find_receipt(session, profile_id, rid)
    if receipt is not None:
        result = _replay(receipt, OP_CREATE, fingerprint)
        return result, False

    if runtime is not None:
        _preflight_ready(runtime, session, task_type)
        _preflight_size(runtime, session, task_type, target_grade, plan_id, holiday_provider)

    begin_immediate(session)
    try:
        profile_id = _profile_id(session)
        receipt = _find_receipt(session, profile_id, rid)
        if receipt is not None:
            result = _replay(receipt, OP_CREATE, fingerprint)
            rollback(session)
            return result, False

        plan, content = _load_plan_and_content(session, plan_id)
        if content.version != expected_content_version:
            raise LocalVersionConflict(details={"current_content_version": content.version})
        active = session.scalars(
            select(LocalAITask).where(
                LocalAITask.source_kind == "daily_plan",
                LocalAITask.daily_plan_id == plan.id,
                LocalAITask.task_type == task_type,
                LocalAITask.status.in_(LIVE_STATUSES),
            )
        ).first()
        if active is not None:
            raise LocalAiTaskActive(details={"task_id": active.id})

        _require_ai_ready(session, task_type)

        projected = ai_inputs.project_input(
            session,
            plan=plan,
            content=content,
            task_type=task_type,
            target_grade=target_grade,
            holiday_provider=holiday_provider,
        )
        now = _now()
        input_id = new_opaque_id()
        session.add(
            LocalAIInput(
                id=input_id,
                profile_id=profile_id,
                source_kind="daily_plan",
                source_id=plan.id,
                observation_id=None,
                source_revision=None,
                daily_plan_id=plan.id,
                content_id=content.id,
                content_version=content.version,
                task_type=task_type,
                target_grade=projected.target_grade,
                input_schema_version=ai_inputs.INPUT_SCHEMA_VERSION,
                payload_json=projected.payload,
                dependencies_json=projected.dependencies,
                dependency_hash=projected.dependency_hash,
                target_hashes_json=projected.target_hashes,
                created_at=now,
            )
        )
        task = LocalAITask(
            id=new_opaque_id(),
            profile_id=profile_id,
            source_kind="daily_plan",
            source_id=plan.id,
            observation_id=None,
            daily_plan_id=plan.id,
            task_type=task_type,
            input_id=input_id,
            status="pending",
            reason=None,
            current_execution_id=None,
            generation=0,
            runtime_meta_json=_meta(CERTAINTY_NOT_SENT),
            created_at=now,
            updated_at=now,
        )
        session.add(task)
        session.flush()
        result = task_out(session, task)
        _store_receipt(
            session,
            profile_id=profile_id,
            request_id=rid,
            operation_kind=OP_CREATE,
            fingerprint=fingerprint,
            result=result,
        )
        session.commit()
        return result, True
    except BaseException:
        rollback(session)
        raise


# ---------------------------------------------------------------------------
# List / detail
# ---------------------------------------------------------------------------


def _encode_cursor(created: datetime, task_id: str) -> str:
    raw = f"{created.isoformat()}|{task_id}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        created_raw, task_id = raw.split("|", 1)
        return datetime.fromisoformat(created_raw), task_id
    except Exception:  # noqa: BLE001
        raise LocalValidationError("cursor 不合法")


def list_tasks(
    session: Session,
    *,
    plan_id: str | None = None,
    status: str | None = None,
    limit: object = DEFAULT_LIST_LIMIT,
    cursor: str | None = None,
    source_kind: str = "daily_plan",
) -> dict[str, Any]:
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_LIST_LIMIT:
        raise LocalValidationError("limit 必须在 1–100 之间")
    if status is not None and status not in (LIVE_STATUSES + TERMINAL_STATUSES + ("paused",)):
        raise LocalValidationError("status 不在允许范围")
    if source_kind not in ("daily_plan", "game_observation"):
        raise LocalValidationError("source_kind 不在允许范围")
    with read_scope(session):
        _profile_id(session)
        statement = select(LocalAITask).where(
            LocalAITask.source_kind == source_kind
        )
        if plan_id is not None:
            statement = statement.where(LocalAITask.daily_plan_id == plan_id)
        if status is not None:
            statement = statement.where(LocalAITask.status == status)
        if cursor:
            created, task_id = _decode_cursor(cursor)
            statement = statement.where(
                (LocalAITask.created_at > created)
                | ((LocalAITask.created_at == created) & (LocalAITask.id > task_id))
            )
        statement = statement.order_by(LocalAITask.created_at, LocalAITask.id).limit(limit + 1)
        rows = list(session.scalars(statement).all())
        next_cursor = None
        if len(rows) > limit:
            rows = rows[:limit]
            last = rows[-1]
            next_cursor = _encode_cursor(last.created_at, last.id)
        return {"items": [task_out(session, row) for row in rows], "next_cursor": next_cursor}


def get_task(
    session: Session, task_id: str, *, source_kind: str = "daily_plan"
) -> dict[str, Any]:
    with read_scope(session):
        _profile_id(session)
        return task_out(session, require_task(session, task_id, source_kind=source_kind))


# ---------------------------------------------------------------------------
# Cancel / resume / retry
# ---------------------------------------------------------------------------


def _check_expected_execution(task: LocalAITask, expected_execution_id: object) -> None:
    current = task.current_execution_id
    if current is None:
        if expected_execution_id is not None:
            raise LocalAiTaskStateConflict("该任务尚无执行，expected_execution_id 必须为 null")
    elif expected_execution_id != current:
        raise LocalAiTaskStateConflict(
            "expected_execution_id 不是当前执行", details={"current_execution_id": current}
        )


def _end_open_attempt(
    session: Session, execution: LocalAIExecution, *, now: datetime, dispatched: bool
) -> bool:
    """End the execution's current *un-terminated* attempt in this transaction.

    A revoked permit would otherwise leave a ``claimed``/``dispatching``
    attempt "in progress" forever (the worker's later result is refused), so
    the attempt is closed with the matching state and a fixed evidence code.
    An already-ended attempt (a prior generation's history) is never touched.
    """
    attempt = session.scalars(
        select(LocalAIAttempt)
        .where(
            LocalAIAttempt.execution_id == execution.id,
            LocalAIAttempt.ended_at.is_(None),
        )
        .order_by(LocalAIAttempt.attempt_no.desc())
    ).first()
    if attempt is None:
        return False
    if dispatched:
        attempt.state = "outcome_unknown"
        attempt.evidence_code = "user_stop"
    else:
        attempt.state = "paused"
        attempt.evidence_code = "not_sent"
    attempt.ended_at = now
    return True


def _close_execution(execution: LocalAIExecution, state: str, meta: dict, now: datetime) -> None:
    execution.state = state
    execution.runtime_meta_json = meta
    execution.ended_at = now


def cancel_task(
    session: Session,
    *,
    task_id: str,
    expected_execution_id: object,
    request_id: object,
    source_kind: str = "daily_plan",
) -> tuple[dict[str, Any], str | None, str]:
    """Cancel; return ``(TaskOut, abort_execution_id, abort_kind)``."""
    rid = _normalize_request_id(request_id)
    fingerprint = _fingerprint(
        OP_CANCEL, {"task_id": task_id, "expected_execution_id": expected_execution_id}
    )
    begin_immediate(session)
    try:
        profile_id = _profile_id(session)
        receipt = _find_receipt(session, profile_id, rid)
        if receipt is not None:
            result = _replay(receipt, OP_CANCEL, fingerprint)
            rollback(session)
            return result, None, "none"
        task = require_task(session, task_id, source_kind=source_kind)
        _check_expected_execution(task, expected_execution_id)
        now = _now()
        abort_id: str | None = None
        abort_kind = "none"
        certainty = _certainty(task)
        execution = None
        if task.current_execution_id:
            execution = session.get(LocalAIExecution, task.current_execution_id)

        if task.status == "pending":
            # A pending task's current_execution_id is the *previous*
            # generation's historical reference; cancelling the queued attempt
            # must never modify that old execution.
            task.status = "cancelled"
            task.reason = None
            task.runtime_meta_json = _meta(CERTAINTY_NOT_SENT, permit_revoked_at=now)
        elif task.status == "retry_wait":
            # The live execution is queued but not sent: end it and revoke.
            abort_kind = "none"
            if execution is not None:
                _end_open_attempt(session, execution, now=now, dispatched=False)
                _close_execution(
                    execution,
                    "cancelled",
                    _meta(CERTAINTY_NOT_SENT, permit_revoked_at=now),
                    now,
                )
            task.status = "cancelled"
            task.reason = None
            task.runtime_meta_json = _meta(CERTAINTY_NOT_SENT, permit_revoked_at=now)
        elif task.status in ("claimed", "dispatching"):
            dispatched = execution is not None and execution.state == "dispatching"
            meta = _meta(
                CERTAINTY_UNKNOWN if dispatched else CERTAINTY_NOT_SENT,
                user_stop=dispatched,
                permit_revoked_at=now,
            )
            task.status = "outcome_unknown" if dispatched else "cancelled"
            task.reason = "user_stop" if dispatched else None
            task.runtime_meta_json = meta
            abort_kind = "stop_wait" if dispatched else "cancel"
            abort_id = task.current_execution_id
            if execution is not None:
                _end_open_attempt(
                    session, execution, now=now, dispatched=execution.state == "dispatching"
                )
                _close_execution(execution, task.status, meta, now)
        elif task.status == "succeeded":
            abort_kind = "none"
        elif task.status == "cancelled":
            abort_kind = "none"
        else:
            # paused / failed / outcome_unknown. The classification follows the
            # persisted certainty, never the reason string: a not-sent task is
            # cancelled; a possibly-sent task stays/becomes outcome_unknown with
            # the user-stop intent recorded on both the task and its execution.
            if certainty == CERTAINTY_UNKNOWN:
                task.status = "outcome_unknown"
                task.reason = "user_stop"
                task.runtime_meta_json = _meta(
                    CERTAINTY_UNKNOWN, user_stop=True, permit_revoked_at=now
                )
                if execution is not None:
                    meta = dict(execution.runtime_meta_json or {})
                    meta["user_stop_requested"] = True
                    execution.runtime_meta_json = meta
            elif certainty == CERTAINTY_RESPONSE:
                # A definite success or a complete invalid model output was
                # received: keep the real status, only record the stop intent.
                meta = dict(task.runtime_meta_json or {})
                meta["user_stop_requested"] = True
                task.runtime_meta_json = meta
            else:  # provably not sent
                task.status = "cancelled"
                task.reason = None
                task.runtime_meta_json = _meta(CERTAINTY_NOT_SENT, permit_revoked_at=now)
        task.updated_at = now
        _cleanup_credentials(session, profile_id, now)
        session.flush()
        result = task_out(session, task)
        _store_receipt(
            session,
            profile_id=profile_id,
            request_id=rid,
            operation_kind=OP_CANCEL,
            fingerprint=fingerprint,
            result=result,
        )
        session.commit()
        return result, abort_id, abort_kind
    except BaseException:
        rollback(session)
        raise


def _revalidate_source(session: Session, task: LocalAITask) -> bool:
    if task.source_kind == "game_observation":
        if task.observation_id is None:
            return False
        from app.local.observation_ai_service import revalidate_observation_source

        return revalidate_observation_source(session, task)
    if task.source_kind != "daily_plan" or task.daily_plan_id is None:
        return False
    inp = session.get(LocalAIInput, task.input_id)
    if inp is None:
        return False
    try:
        plan, content = _load_plan_and_content(session, task.daily_plan_id)
    except (LocalStorageError, LocalAiNotFound):
        return False
    return ai_inputs.dependency_matches(
        session, plan=plan, content=content, input_row=inp
    )


def _aliased_task_exists(session: Session, task: LocalAITask) -> bool:
    return session.scalars(
        select(LocalAITask).where(
            LocalAITask.source_kind == task.source_kind,
            LocalAITask.source_id == task.source_id,
            LocalAITask.task_type == task.task_type,
            LocalAITask.status.in_(LIVE_STATUSES),
            LocalAITask.id != task.id,
        )
    ).first() is not None


def _clear_config_block(session: Session, profile_id: str, now: datetime) -> None:
    state = session.get(LocalAIState, profile_id)
    if state is not None and state.blocked_config_version is not None:
        state.blocked_config_version = None
        state.blocked_reason = None
        state.updated_at = now


def _requeue(
    session: Session,
    task: LocalAITask,
    *,
    profile_id: str,
    operation_kind: str,
    fingerprint: str,
    request_id: str,
    now: datetime,
    allow_paused: bool,
) -> dict[str, Any]:
    if _aliased_task_exists(session, task):
        raise LocalAiTaskActive()
    try:
        _require_ai_ready(session, task.task_type)
    except (LocalAiNotConfigured, LocalStorageError, LocalProfileRequired) as exc:
        raise LocalAiNotConfigured() from exc
    if not _revalidate_source(session, task):
        task.status = "paused"
        task.reason = "source_changed"
        task.runtime_meta_json = _meta(CERTAINTY_NOT_SENT)
        task.updated_at = now
        raise LocalAiSourceChanged("来源已变化，请重新生成")
    _clear_config_block(session, profile_id, now)
    task.status = "pending"
    task.reason = None
    task.runtime_meta_json = _meta(CERTAINTY_NOT_SENT)
    task.updated_at = now
    session.flush()
    result = task_out(session, task)
    _store_receipt(
        session,
        profile_id=profile_id,
        request_id=request_id,
        operation_kind=operation_kind,
        fingerprint=fingerprint,
        result=result,
    )
    session.commit()
    return result


def _preflight_for_task(
    runtime: Any, session: Session, task_id: str, *, source_kind: str = "daily_plan"
) -> None:
    """Runtime preflight for resume/retry: prompt sync, credential and size.

    Runs after the receipt priority check and before the write transaction, so
    a credential/prompt failure never returns ``pending`` and then immediately
    pauses the task.
    """
    with read_scope(session):
        task = require_task(session, task_id, source_kind=source_kind)
        if task.source_kind == "game_observation":
            task_type = task.task_type
            plan_id = None
            grade = None
        else:
            if task.source_kind != "daily_plan":
                raise LocalAiNotFound("未找到该日计划任务")
            task_type = task.task_type
            plan_id = task.daily_plan_id
            inp = session.get(LocalAIInput, task.input_id)
            grade = inp.target_grade if inp is not None else "middle"
    _preflight_ready(runtime, session, task_type)
    if plan_id is not None:
        _preflight_size(runtime, session, task_type, grade, plan_id, None)


def resume_task(
    session: Session,
    *,
    task_id: str,
    expected_execution_id: object,
    request_id: object,
    runtime: Any | None = None,
    source_kind: str = "daily_plan",
) -> dict[str, Any]:
    rid = _normalize_request_id(request_id)
    fingerprint = _fingerprint(
        OP_RESUME, {"task_id": task_id, "expected_execution_id": expected_execution_id}
    )
    # Receipt priority first: a committed re-send replays even with a broken
    # credential or a pending prompt sync.
    with read_scope(session):
        profile_id = _profile_id(session)
        receipt = _find_receipt(session, profile_id, rid)
    if receipt is not None:
        return _replay(receipt, OP_RESUME, fingerprint)
    if runtime is not None:
        _preflight_for_task(runtime, session, task_id, source_kind=source_kind)
    begin_immediate(session)
    try:
        profile_id = _profile_id(session)
        receipt = _find_receipt(session, profile_id, rid)
        if receipt is not None:
            result = _replay(receipt, OP_RESUME, fingerprint)
            rollback(session)
            return result
        task = require_task(session, task_id, source_kind=source_kind)
        _check_expected_execution(task, expected_execution_id)
        if task.status != "paused":
            raise LocalAiTaskStateConflict("只有 paused 任务可以继续")
        if _certainty(task) != CERTAINTY_NOT_SENT:
            raise LocalAiTaskStateConflict("已发送的暂停任务不能继续，请使用重试")
        if task.reason == "source_changed":
            raise LocalAiSourceChanged("来源已变化，请重新生成")
        return _requeue(
            session,
            task,
            profile_id=profile_id,
            operation_kind=OP_RESUME,
            fingerprint=fingerprint,
            request_id=rid,
            now=_now(),
            allow_paused=True,
        )
    except BaseException:
        rollback(session)
        raise


def retry_task(
    session: Session,
    *,
    task_id: str,
    expected_execution_id: object,
    ack_duplicate_cost: bool,
    request_id: object,
    runtime: Any | None = None,
    source_kind: str = "daily_plan",
) -> dict[str, Any]:
    rid = _normalize_request_id(request_id)
    fingerprint = _fingerprint(
        OP_RETRY,
        {
            "task_id": task_id,
            "expected_execution_id": expected_execution_id,
            "ack_duplicate_cost": bool(ack_duplicate_cost),
        },
    )
    with read_scope(session):
        profile_id = _profile_id(session)
        receipt = _find_receipt(session, profile_id, rid)
    if receipt is not None:
        return _replay(receipt, OP_RETRY, fingerprint)
    if runtime is not None:
        _preflight_for_task(runtime, session, task_id, source_kind=source_kind)
    begin_immediate(session)
    try:
        profile_id = _profile_id(session)
        receipt = _find_receipt(session, profile_id, rid)
        if receipt is not None:
            result = _replay(receipt, OP_RETRY, fingerprint)
            rollback(session)
            return result
        task = require_task(session, task_id, source_kind=source_kind)
        _check_expected_execution(task, expected_execution_id)
        if task.status not in ("failed", "paused", "outcome_unknown"):
            raise LocalAiTaskStateConflict("只有 failed/paused/outcome_unknown 可以重试")
        if task.reason == "source_changed":
            raise LocalAiSourceChanged("来源已变化，请重新生成，不能换输入重试")
        needs_ack = _certainty(task) == CERTAINTY_UNKNOWN or task.status == "outcome_unknown"
        if needs_ack and not ack_duplicate_cost:
            raise LocalAiRetryAckRequired()
        return _requeue(
            session,
            task,
            profile_id=profile_id,
            operation_kind=OP_RETRY,
            fingerprint=fingerprint,
            request_id=rid,
            now=_now(),
            allow_paused=True,
        )
    except BaseException:
        rollback(session)
        raise


# ---------------------------------------------------------------------------
# Executor-facing claim (three phases: decide -> material -> commit)
# ---------------------------------------------------------------------------


@dataclass
class Claim:
    task_id: str
    plan_id: str | None
    input_id: str
    task_type: str
    execution_id: str
    generation: int
    attempt_id: str
    attempt_no: int
    permit_id: str
    launch_id: str
    config_version: int
    personal_revision: int
    contract_version: int
    default_revision: int
    payload: dict[str, Any]
    system_text: str
    base_url: str
    model: str
    secret: str
    started_ticks: int = 0
    source_kind: str = "daily_plan"
    observation_id: str | None = None
    image_urls: tuple[str, ...] = ()
    attempt_budget_ms: int = ai_transport.ATTEMPT_BUDGET_MS
    vision_authorized: bool = False
    vision_schema_version: int | None = None
    vision_protocol: str | None = None
    work_dimensions: tuple[tuple[int, int], ...] = ()


@dataclass
class _Pick:
    task_id: str
    task_status: str
    plan_id: str | None
    input_id: str
    task_type: str
    generation: int
    current_execution_id: str | None
    existing_execution_id: str | None
    permit_id: str | None
    launch_id: str | None
    config_version: int | None
    personal_revision: int | None
    contract_version: int | None
    default_revision: int | None
    pause_reason: str | None = None
    source_kind: str = "daily_plan"
    observation_id: str | None = None


def _render_system_text(
    task_type: str,
    contract_version: int,
    output_schema: dict[str, Any],
    guidance: dict[str, Any],
    *,
    protocol: str = ai_transport.PROTOCOL_ID,
) -> str:
    """System message: pinned output contract + separate personal guidance.

    The business material is sent as the user message; the system message
    carries the structural contract *and task-specific rules*, so the model is
    actually told to return one JSON object matching the pinned schema without
    forbidding a confirmed capability (an adapt may rewrite the process; an
    other-activities task may propose new games).
    """
    common = [
        "只返回一个 JSON 对象，不要 Markdown 代码围栏、前后解释或额外文字。",
        "严格遵循 output_contract 的字段与类型，不要输出未列出的字段或 ID。",
        "多项内容、活动步骤、目标、准备、要点、问题或游戏建议：每项使用真实换行，并以“1. ”、“2. ”、“3. ”阿拉伯数字依次编号；数量按实际内容，不强行凑三条；名称、主题等短单值不编号。JSON 字符串中的换行必须使用转义换行，解码后是真实换行，不能向教师显示字面 \\n。",
    ]
    per_task: dict[str, list[str]] = {
        "daily_lesson_split": [
            "只从教师提供的原始教案中摘取内容，不得补写或编造教案里没有的环节。",
            "原始教案未写到的字段返回空字符串，不要猜测。",
            "原文已有可识别条目时，只整理这些已有条目的编号和换行；保留原文语句、顺序和教学含义，不为列表扩写、补写或改写原文事实。",
        ],
        "daily_process_adapt": [
            "输入为一份已保存的活动过程；请按目标年级调整其年龄适宜性，可以改写表达、步骤和难度。",
            "输出完整的调整后过程；最终过程按实际步骤分行并用阿拉伯数字编号，数量按实际，不强凑三条。",
            "每个环节都要写出教师可直接说的具体话语：关键处包含引导语、提问和教师的预设回应或支持语，简短自然、衔接操作、适合目标年龄。",
            "补充教师话语时保持目标年级适宜的活动难度，不因话语增加认知或表达要求；回应可写成条件式建议，不虚构已经发生的课堂事实或幼儿实际回答，不要求扩成全程逐字稿。",
            "即使无需年龄适宜性调整，也保留原教学内容、整理编号和换行，并为每个环节补齐教师可直接说的具体话语。",
            "保留活动主题和主要教学意图，不要编造已经发生的课堂事实。",
        ],
        "daily_other_activities": [
            "可以根据日期、周次、班级年级、可用游戏配置和当前日计划，提出新的游戏与活动建议。",
            "晨间游戏的一项集体与一项自选/自主均为户外活动，不含区域游戏、室内或专用室活动；优先使用 game_config 中 kind=outdoor 的场地及限制，没有户外配置时只给一般户外建议并明确未结合配置，不冒充已配置场地。",
            "其他板块仍可使用各自适用的区域、专用室或户外配置。",
            "集体活动为空时，按现有信息给出一般性建议，并说明未结合班级游戏配置。",
            "不伪造日计划引用或真实活动事实；不输出“一日活动反思”。",
            "节日信息仅供参考，不强制安排节日活动。",
        ],
        "game_observation_generate": [
            "根据记录类型、基本资料、已有四栏正文、全部有序照片及简短说明，一次生成四个栏目；四个栏目都必须返回，暂无可写内容时使用空字符串，评价分析必须是五个领域齐全的对象。",
            "允许补写对话和基于情境的动作衔接，但不得编造未提供的精确分钟、持续时长或完整新事件。只有在教师明确给出姓名与行为／原话对应时，才把该行为或原话写到具体姓名；仅提供 subjects 姓名不构成对应。没有明确对应时，只写材料能确定的共同情境，或写不归属具体姓名的对话／动作，不自行给幼儿分配角色、台词或动作。确有必要时可在正文简短说明人物对应缺口，但不得因此删除或禁止 C11 允许的对话与动作衔接。四栏正文若有多条或多段，JSON 解码后必须是真实换行；JSON 字符串中只转义一层（\n），不得输出字面反斜杠+n、双重转义或让教师看到 \n 字面文本。",
            "教师已给的原话、时间、人物对应优先；AI补写的对话和动作只作为候选，不是已核实事实，不得写成“记录显示”“只能确定”等已证实表述，也不得声称从静态照片听到了原话。",
            "审核提示、候选／AI补写／待核实等标记只由应用候选区独立 metadata 提供；四栏正文不得包裹、添加或复述这些审核说明。",
            "只使用输入中的资料、照片和说明；不引入学校、班级、观察者、学期或任何内部身份字段。",
        ],
        "game_observation_rewrite": [
            "只重写 target 指定的栏目并只返回该栏目；评价分析目标必须返回 health/language/social/science/arts 五领域完整对象，其他目标只返回 text。",
            "输入中的其他栏目只作为上下文，不得顺带改写或返回；允许补写对话和基于情境的动作衔接，但不得编造未提供的精确分钟、持续时长或完整新事件。目标正文若有多条或多段，JSON 解码后必须是真实换行；JSON 字符串中只转义一层（\n），不得输出字面反斜杠+n、双重转义或让教师看到 \n 字面文本。",
            "只有在教师明确给出姓名与行为／原话对应时，才把该行为或原话写到具体姓名；仅提供 subjects 姓名不构成对应。没有明确对应时，只写材料能确定的共同情境，或写不归属具体姓名的对话／动作，不自行给幼儿分配角色、台词或动作；确有必要时可简短说明人物对应缺口。教师已给的原话、时间、人物对应优先。",
            "AI补写的对话和动作只作为候选，不是已核实事实，不得写成“记录显示”“只能确定”等已证实表述，也不得声称从静态照片听到了原话。审核提示、候选／AI补写／待核实等标记只由应用候选区独立 metadata 提供，不得写进目标正文。",
        ],
    }
    return canonical_json(
        {
            "task_type": task_type,
            "protocol": protocol,
            "contract_version": contract_version,
            "output_contract": output_schema,
            "guidance": guidance,
            "instructions": common + per_task.get(task_type, []),
        }
    )


def _credential_usable(session: Session, profile_id: str, config_version: int) -> bool:
    """True when the config's credential can still be decrypted by this build."""
    config = session.get(LocalAIConfigVersion, (profile_id, config_version))
    if config is None or config.credential_id is None:
        return False
    credential = session.scalars(
        select(LocalAICredential).where(
            LocalAICredential.profile_id == profile_id,
            LocalAICredential.id == config.credential_id,
        )
    ).first()
    return (
        credential is not None
        and credential.state in ("active", "retired")
        and credential.nonce is not None
        and credential.ciphertext is not None
        and len(credential.nonce) == 12
    )


def _verify_pending_preconditions(
    session: Session, task: LocalAITask, pick: _Pick
) -> str | None:
    """Re-verify a *new-execution* claim inside the final write transaction."""
    from app.local.ai_config_service import _read_config

    state, config, _cred = _read_config(session)
    if state is None or config is None or config.version != pick.config_version:
        return "not_configured"
    if state.blocked_config_version == config.version:
        return "auth_rejected"
    head, version = _current_prompt(session, task.profile_id, task.task_type)
    if head is None or version is None:
        return "prompt_missing"
    if head.required_contract_version not in SUPPORTED_CONTRACT_VERSIONS:
        return "contract_unsupported"
    if version.revision != pick.personal_revision:
        return "restart"
    if version.contract_version != head.required_contract_version:
        return "adaptation_required"
    if version.contract_version not in SUPPORTED_CONTRACT_VERSIONS:
        return "contract_unsupported"
    if not _credential_usable(session, task.profile_id, pick.config_version):
        return "credential_unavailable"
    return None


def _pick_candidate(runtime: Any, now: datetime) -> tuple[_Pick | None, bool]:
    """Phase 1: choose the FIFO task and read the versions to pin.

    Returns ``(pick, paused)``: ``paused`` is True when a precondition failed
    and the task was already transitioned (so the caller should just continue).
    """
    session = runtime.session()
    try:
        begin_immediate(session)
        try:
            profile_id = _profile_id(session)
            rows = list(
                session.scalars(
                    select(LocalAITask)
                    .where(
                        LocalAITask.profile_id == profile_id,
                        LocalAITask.status.in_(("pending", "retry_wait")),
                    )
                    .order_by(LocalAITask.created_at, LocalAITask.id)
                ).all()
            )
            target = None
            for candidate in rows:
                if candidate.status == "pending":
                    target = candidate
                    break
                next_at = (candidate.runtime_meta_json or {}).get("next_attempt_at")
                due = True
                if next_at:
                    try:
                        due = datetime.fromisoformat(next_at) <= now
                    except ValueError:
                        due = True
                if due:
                    target = candidate
                    break
            if target is None:
                rollback(session)
                return None, False

            if getattr(runtime, "prompt_sync_error", None):
                _pause_target(session, target, "prompt_sync_unavailable", CERTAINTY_NOT_SENT, now, profile_id)
                session.commit()
                return None, True
            if not _revalidate_source(session, target):
                _pause_target(session, target, "source_changed", CERTAINTY_NOT_SENT, now, profile_id)
                session.commit()
                return None, True

            inp = session.get(LocalAIInput, target.input_id)
            assert inp is not None
            if target.status == "pending":
                from app.local.ai_config_service import _read_config

                state, config, credential = _read_config(session)
                if state is None or config is None or config.base_url is None or config.model is None or config.credential_id is None:
                    _pause_target(session, target, "not_configured", CERTAINTY_NOT_SENT, now, profile_id)
                    session.commit()
                    return None, True
                if state.blocked_config_version == config.version:
                    _pause_target(session, target, "auth_rejected", CERTAINTY_NOT_SENT, now, profile_id)
                    session.commit()
                    return None, True
                head, version = _current_prompt(session, profile_id, target.task_type)
                if head is None or version is None:
                    _pause_target(session, target, "prompt_missing", CERTAINTY_NOT_SENT, now, profile_id)
                    session.commit()
                    return None, True
                if head.required_contract_version not in SUPPORTED_CONTRACT_VERSIONS:
                    _pause_target(session, target, "contract_unsupported", CERTAINTY_NOT_SENT, now, profile_id)
                    session.commit()
                    return None, True
                if version.contract_version not in SUPPORTED_CONTRACT_VERSIONS:
                    _pause_target(session, target, "contract_unsupported", CERTAINTY_NOT_SENT, now, profile_id)
                    session.commit()
                    return None, True
                if version.contract_version != head.required_contract_version:
                    _pause_target(session, target, "adaptation_required", CERTAINTY_NOT_SENT, now, profile_id)
                    session.commit()
                    return None, True
                pick = _Pick(
                    task_id=target.id,
                    task_status="pending",
                    plan_id=target.daily_plan_id,
                    input_id=target.input_id,
                    task_type=target.task_type,
                    generation=target.generation,
                    current_execution_id=target.current_execution_id,
                    existing_execution_id=None,
                    permit_id=None,
                    launch_id=None,
                    config_version=config.version,
                    personal_revision=version.revision,
                    contract_version=version.contract_version,
                    default_revision=version.based_default_revision,
                    source_kind=target.source_kind,
                    observation_id=target.observation_id,
                )
            else:  # retry_wait: reuse the execution's pinned versions
                execution = session.get(
                    LocalAIExecution, target.current_execution_id, populate_existing=True
                )
                if execution is None or execution.state != "retry_wait":
                    _pause_target(session, target, "restart", CERTAINTY_NOT_SENT, now, profile_id)
                    session.commit()
                    return None, True
                if getattr(runtime, "launch_id", None) and execution.launch_id != getattr(runtime, "launch_id", None):
                    _pause_target(session, target, "restart", CERTAINTY_NOT_SENT, now, profile_id)
                    session.commit()
                    return None, True
                if execution.contract_version not in SUPPORTED_CONTRACT_VERSIONS:
                    _pause_target(session, target, "contract_unsupported", CERTAINTY_NOT_SENT, now, profile_id)
                    session.commit()
                    return None, True
                if not _credential_usable(session, profile_id, execution.config_version):
                    _pause_target(session, target, "credential_unavailable", CERTAINTY_NOT_SENT, now, profile_id)
                    session.commit()
                    return None, True
                pick = _Pick(
                    task_id=target.id,
                    task_status="retry_wait",
                    plan_id=target.daily_plan_id,
                    input_id=target.input_id,
                    task_type=target.task_type,
                    generation=execution.generation,
                    current_execution_id=execution.id,
                    existing_execution_id=execution.id,
                    permit_id=execution.permit_id,
                    launch_id=execution.launch_id,
                    config_version=execution.config_version,
                    personal_revision=execution.personal_revision,
                    contract_version=execution.contract_version,
                    default_revision=execution.default_revision,
                    source_kind=target.source_kind,
                    observation_id=target.observation_id,
                )
            session.commit()
            return pick, False
        except BaseException:
            rollback(session)
            raise
    finally:
        session.close()


def serialized_request_bytes(
    *,
    task_type: str,
    contract_version: int,
    output_schema: dict[str, Any],
    guidance: dict[str, Any],
    payload: dict[str, Any],
    model: str,
) -> int:
    """Length of the *actual* Chat Completions body for these inputs.

    A backslash-heavy or multi-byte payload can be far larger once the business
    JSON is re-serialized inside the request envelope, so the input JSON size is
    never used as the limit check (spec §4.2 / §11: serialized request ≤ 1 MiB).
    """
    system_text = _render_system_text(task_type, contract_version, output_schema, guidance)
    user_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return len(ai_transport.build_request(model=model, system_text=system_text, user_text=user_text))


def _load_material(runtime: Any, pick: _Pick) -> tuple[dict[str, Any] | None, str | None]:
    """Phase 2: read pinned rows and decrypt outside any DB transaction."""
    from app.local.ai_config_service import _build_store

    if pick.source_kind == "game_observation":
        from app.local.observation_ai_service import load_observation_material

        return load_observation_material(runtime, pick)

    session = runtime.session()
    try:
        with read_scope(session):
            state = session.get(LocalAIState, _profile_id(session))
            if state is None:
                return None, "not_configured"
            config = session.get(
                LocalAIConfigVersion, (state.profile_id, pick.config_version)
            )
            if config is None or config.base_url is None or config.model is None or config.credential_id is None:
                return None, "not_configured"
            credential = session.scalars(
                select(LocalAICredential).where(
                    LocalAICredential.profile_id == state.profile_id,
                    LocalAICredential.id == config.credential_id,
                )
            ).first()
            version = session.get(
                LocalPersonalPromptVersion,
                (state.profile_id, pick.task_type, pick.personal_revision),
            )
            bundle = session.get(
                LocalPromptBundle,
                (pick.task_type, pick.contract_version, pick.default_revision),
            )
            if version is None or bundle is None:
                return None, "prompt_missing"
            profile_id = state.profile_id
            database_uuid = state.database_uuid
            credential_id = config.credential_id
            base_url = config.base_url
            model = config.model
            cred_state = credential.state if credential is not None else None
            key_id = credential.key_id if credential is not None else None
            nonce = bytes(credential.nonce) if credential is not None and credential.nonce else None
            ciphertext = bytes(credential.ciphertext) if credential is not None and credential.ciphertext else None
            guidance = dict(version.guidance_json or {})
            output_schema = dict(bundle.output_schema_json or {})
            inp = session.get(LocalAIInput, pick.input_id)
            payload = dict(inp.payload_json) if inp is not None else None
    finally:
        session.close()

    if payload is None:
        return None, "input_missing"
    # Validate the *real* serialized request (envelope + re-escaped payload)
    # before any network/IPC work; a heavy escape or multi-byte payload is
    # refused here, never passed to a worker that would then fail.
    if (
        serialized_request_bytes(
            task_type=pick.task_type,
            contract_version=pick.contract_version,
            output_schema=output_schema,
            guidance=guidance,
            payload=payload,
            model=model,
        )
        > ai_transport.REQUEST_MAX_BYTES
    ):
        return None, "input_too_large"

    if cred_state not in ("active", "retired") or nonce is None or ciphertext is None or len(nonce) != 12:
        return None, "credential_unavailable"
    # DPAPI / ACL work happens here, with no DB transaction held.
    store = _build_store(profile_id, database_uuid, runtime.credential_root)
    if store is None:
        return None, "credential_unavailable"
    try:
        master_key = store.load_master_key(key_id)
        from app.local.credentials import SavedSecret

        secret = store.decrypt_secret(
            master_key, SavedSecret(key_id=key_id, nonce=nonce, ciphertext=ciphertext), profile_id, credential_id
        )
    except Exception:  # noqa: BLE001
        return None, "credential_unavailable"
    return {
        "base_url": base_url,
        "model": model,
        "secret": secret,
        "system_text": _render_system_text(pick.task_type, pick.contract_version, output_schema, guidance),
        "payload": payload,
        "config_version": pick.config_version,
        "personal_revision": pick.personal_revision,
        "contract_version": pick.contract_version,
        "default_revision": pick.default_revision,
    }, None


def _apply_pause_for_pick(runtime: Any, pick: _Pick, reason: str) -> None:
    """Pause the exact picked generation; never a newer one.

    Binds the original ``status``/execution identity/``generation`` so a
    cancel or re-queue that lands during the DPAPI gap is not overwritten by a
    pause meant for the previous attempt.
    """
    session = runtime.session()
    try:
        begin_immediate(session)
        try:
            task = session.get(LocalAITask, pick.task_id, populate_existing=True)
            if task is None or task.status != pick.task_status:
                rollback(session)
                return
            # A pending task legitimately keeps the previous generation's
            # execution reference; the snapshot (status + generation + current
            # execution) is the discriminator, never "must be null".
            if (
                task.status != pick.task_status
                or task.generation != pick.generation
                or task.current_execution_id != pick.current_execution_id
            ):
                rollback(session)
                return
            _pause_target(session, task, reason, CERTAINTY_NOT_SENT, _now(), task.profile_id)
            session.commit()
        except BaseException:
            rollback(session)
            raise
    finally:
        session.close()


def claim_next(
    runtime: Any,
    *,
    now: datetime,
    started_ticks: int,
    guard: Any = None,
) -> Claim | None:
    pick, paused = _pick_candidate(runtime, now)
    if paused or pick is None:
        return None
    material, failure = _load_material(runtime, pick)
    if failure is not None:
        _apply_pause_for_pick(runtime, pick, failure)
        return None
    assert material is not None

    session = runtime.session()
    try:
        begin_immediate(session)
        try:
            # In-memory close-epoch re-verify: a close that began while this
            # claim waited must not commit across it.
            if guard is not None and not guard():
                rollback(session)
                return None
            task = session.get(LocalAITask, pick.task_id, populate_existing=True)
            if task is None or task.status != pick.task_status:
                rollback(session)
                return None
            if not _revalidate_source(session, task):
                _pause_target(session, task, "source_changed", CERTAINTY_NOT_SENT, now, task.profile_id)
                session.commit()
                return None
            launch_id = str(getattr(runtime, "launch_id", "") or "")
            if pick.task_status == "pending":
                if (
                    task.generation != pick.generation
                    or task.current_execution_id != pick.current_execution_id
                ):
                    rollback(session)
                    return None
                # Re-verify every precondition inside the final write
                # transaction: required contract / adaptation / blocked version
                # / credential not cleared.
                failure = _verify_pending_preconditions(session, task, pick)
                if failure is not None:
                    _pause_target(session, task, failure, CERTAINTY_NOT_SENT, now, task.profile_id)
                    session.commit()
                    return None
                generation = task.generation + 1
                execution_id = new_opaque_id()
                permit_id = str(uuid.uuid4())
                execution = LocalAIExecution(
                    id=execution_id,
                    task_id=task.id,
                    source_kind=task.source_kind,
                    source_id=task.source_id,
                    observation_id=task.observation_id,
                    daily_plan_id=task.daily_plan_id,
                    input_id=task.input_id,
                    task_type=task.task_type,
                    generation=generation,
                    launch_id=launch_id,
                    permit_id=permit_id,
                    config_version=pick.config_version,
                    profile_id=task.profile_id,
                    personal_revision=pick.personal_revision,
                    contract_version=pick.contract_version,
                    default_revision=pick.default_revision,
                    state="claimed",
                    runtime_meta_json=_meta(CERTAINTY_NOT_SENT),
                    started_at=now,
                    created_at=now,
                )
                session.add(execution)
                session.flush()
                task.generation = generation
                task.current_execution_id = execution_id
                attempt_no = 1
            else:
                execution = session.get(
                    LocalAIExecution, pick.existing_execution_id, populate_existing=True
                )
                if execution is None or execution.state != "retry_wait":
                    rollback(session)
                    return None
                if (
                    execution.permit_id != pick.permit_id
                    or execution.launch_id != pick.launch_id
                    or execution.generation != pick.generation
                    or task.generation != pick.generation
                    or execution.ended_at is not None
                ):
                    rollback(session)
                    return None
                # Never revive an unsent execution after its credential was
                # cleared: the secret copy in memory is not enough.
                if not _credential_usable(session, task.profile_id, execution.config_version):
                    _pause_target(session, task, "credential_unavailable", CERTAINTY_NOT_SENT, now, task.profile_id)
                    session.commit()
                    return None
                permit_id = execution.permit_id
                execution_id = execution.id
                generation = execution.generation
                execution.state = "claimed"
                execution.runtime_meta_json = _meta(CERTAINTY_NOT_SENT)
                execution.ended_at = None
                attempt_no = _attempt_no(session, execution.id) + 1

            task.status = "claimed"
            task.reason = None
            task.runtime_meta_json = _meta(CERTAINTY_NOT_SENT)
            task.updated_at = now
            attempt_id = new_opaque_id()
            session.add(
                LocalAIAttempt(
                    id=attempt_id,
                    execution_id=execution_id,
                    attempt_no=attempt_no,
                    state="claimed",
                    created_at=now,
                )
            )
            session.flush()
            claim = Claim(
                task_id=task.id,
                plan_id=task.daily_plan_id,
                input_id=task.input_id,
                task_type=task.task_type,
                execution_id=execution_id,
                generation=generation,
                attempt_id=attempt_id,
                attempt_no=attempt_no,
                permit_id=permit_id,
                launch_id=launch_id,
                config_version=pick.config_version,
                personal_revision=pick.personal_revision,
                contract_version=pick.contract_version,
                default_revision=pick.default_revision,
                payload=dict(material["payload"]),
                system_text=material["system_text"],
                base_url=material["base_url"],
                model=material["model"],
                secret=material["secret"],
                started_ticks=started_ticks,
                source_kind=task.source_kind,
                observation_id=task.observation_id,
                image_urls=tuple(material.get("image_urls") or ()),
                attempt_budget_ms=int(
                    material.get("attempt_budget_ms")
                    or ai_transport.ATTEMPT_BUDGET_MS
                ),
                vision_authorized=bool(material.get("vision_authorized")),
                vision_schema_version=material.get("vision_schema_version"),
                vision_protocol=material.get("vision_protocol"),
                work_dimensions=tuple(material.get("work_dimensions") or ()),
            )
            session.commit()
            return claim
        except BaseException:
            rollback(session)
            raise
    finally:
        session.close()


def _pause_target(
    session: Session,
    task: LocalAITask,
    reason: str,
    certainty: str,
    now: datetime,
    profile_id: str,
) -> None:
    task.status = "paused"
    task.reason = reason
    meta = _meta(certainty, permit_revoked_at=now)
    task.runtime_meta_json = meta
    task.updated_at = now
    if task.current_execution_id:
        execution = session.get(LocalAIExecution, task.current_execution_id)
        if execution is not None and execution.ended_at is None:
            _end_open_attempt(
                session,
                execution,
                now=now,
                dispatched=execution.state == "dispatching",
            )
            _close_execution(execution, "paused", meta, now)
    _cleanup_credentials(session, profile_id, now)


# ---------------------------------------------------------------------------
# Dispatch mark and terminal results
# ---------------------------------------------------------------------------


def _permit_ok(
    task: LocalAITask,
    execution: LocalAIExecution,
    claim: Claim,
    attempt: LocalAIAttempt | None = None,
) -> bool:
    """Full permit verification: a stale permit can never be accepted.

    Besides the ID links this re-checks the task generation and a live status,
    the execution's generation/launch/permit, that the execution has not ended
    and its permit was never revoked, and (when given) that the attempt belongs
    to this execution and has not already terminated.
    """
    if (
        task.current_execution_id != execution.id
        or execution.task_id != task.id
        or execution.id != claim.execution_id
        or execution.permit_id != claim.permit_id
        or execution.launch_id != claim.launch_id
        or execution.generation != claim.generation
        or task.generation != claim.generation
        or task.status not in ("claimed", "dispatching")
        or execution.state not in ("claimed", "dispatching")
        or execution.ended_at is not None
    ):
        return False
    if (execution.runtime_meta_json or {}).get("permit_revoked_at"):
        return False
    if attempt is not None:
        if attempt.execution_id != execution.id or attempt.ended_at is not None:
            return False
    return True


def commit_dispatch_mark(session: Session, claim: Claim, now: datetime) -> bool:
    """Short transaction: re-verify everything, then mark dispatching."""
    begin_immediate(session)
    try:
        attempt = session.get(LocalAIAttempt, claim.attempt_id)
        execution = session.get(LocalAIExecution, claim.execution_id, populate_existing=True)
        task = session.get(LocalAITask, claim.task_id, populate_existing=True)
        if attempt is None or execution is None or task is None:
            rollback(session)
            return False
        if execution.state != "claimed" or not _permit_ok(task, execution, claim, attempt):
            rollback(session)
            return False
        if not _revalidate_source(session, task):
            _pause_target(session, task, "source_changed", CERTAINTY_NOT_SENT, now, task.profile_id)
            session.commit()
            return False
        # Re-verify the pinned credential inside this transaction: a secret
        # cleared after the claim must not be sent using the in-memory copy.
        if not _credential_usable(session, task.profile_id, claim.config_version):
            _pause_target(session, task, "credential_unavailable", CERTAINTY_NOT_SENT, now, task.profile_id)
            session.commit()
            return False
        attempt.dispatch_marked_at = now
        attempt.state = "dispatching"
        execution.state = "dispatching"
        execution.runtime_meta_json = _meta(CERTAINTY_UNKNOWN)
        task.status = "dispatching"
        task.runtime_meta_json = _meta(CERTAINTY_UNKNOWN)
        task.updated_at = now
        session.commit()
        return True
    except BaseException:
        rollback(session)
        raise


def _context(session: Session, claim: Claim):
    attempt = session.get(LocalAIAttempt, claim.attempt_id)
    execution = session.get(LocalAIExecution, claim.execution_id, populate_existing=True)
    task = session.get(LocalAITask, claim.task_id, populate_existing=True)
    if attempt is None or execution is None or task is None:
        raise LocalStorageError("任务结果提交缺少对象")
    return attempt, execution, task


def _finish_attempt(attempt: LocalAIAttempt, state: str, result: dict[str, Any], now: datetime) -> None:
    attempt.state = state
    attempt.ended_at = now
    attempt.evidence_code = result.get("reason") or result.get("kind")
    http_status = result.get("http_status")
    attempt.http_status = http_status if isinstance(http_status, int) else None
    request_id = result.get("provider_request_id")
    attempt.provider_request_id = request_id if isinstance(request_id, str) else None
    returned_model = result.get("returned_model")
    attempt.returned_model = returned_model if isinstance(returned_model, str) else None
    usage = result.get("usage")
    attempt.usage_json = usage if isinstance(usage, dict) else None
    duration_ms = result.get("duration_ms")
    if isinstance(duration_ms, int) and not isinstance(duration_ms, bool) and duration_ms >= 0:
        attempt.duration_ms = duration_ms


def finalize_success(session: Session, claim: Claim, result: dict[str, Any], now: datetime) -> bool:
    text = result.get("candidate_text")
    if not isinstance(text, str):
        return finalize_failure(session, claim, result, now)
    try:
        parsed = ai_transport.parse_strict_json_object(text)
        validated = validate_candidate(claim.task_type, parsed)
    except (ValueError, CandidateInvalid):
        invalid = dict(result)
        invalid["kind"] = "output_invalid"
        invalid["reason"] = "output_invalid"
        return finalize_failure(session, claim, invalid, now)

    begin_immediate(session)
    try:
        attempt, execution, task = _context(session, claim)
        if execution.state != "dispatching" or not _permit_ok(task, execution, claim, attempt):
            rollback(session)
            return False
        inp = session.get(LocalAIInput, task.input_id)
        schema_version = inp.input_schema_version if inp is not None else 1
        candidate = LocalAICandidate(
            id=new_opaque_id(),
            profile_id=task.profile_id,
            execution_id=execution.id,
            task_id=task.id,
            source_kind=task.source_kind,
            source_id=task.source_id,
            observation_id=task.observation_id,
            daily_plan_id=task.daily_plan_id,
            input_id=task.input_id,
            task_type=task.task_type,
            contract_version=execution.contract_version,
            schema_version=schema_version,
            raw_candidate_json=validated,
            candidate_hash=_digest(validated),
            created_at=now,
        )
        session.add(candidate)
        session.flush()
        if task.source_kind == "game_observation":
            from app.local.observation_ai_service import (
                store_candidate_review_metadata,
            )

            store_candidate_review_metadata(session, candidate, validated)
            session.flush()
        _finish_attempt(attempt, "succeeded", result, now)
        meta = _meta(CERTAINTY_RESPONSE)
        _close_execution(execution, "succeeded", meta, now)
        task.status = "succeeded"
        task.reason = None
        task.runtime_meta_json = meta
        task.updated_at = now
        _cleanup_credentials(session, task.profile_id, now)
        session.commit()
        return True
    except Exception:
        rollback(session)
        raise


def finalize_failure(
    session: Session,
    claim: Claim,
    result: dict[str, Any],
    now: datetime,
    *,
    wait_seconds: tuple[int, ...] = _DEFAULT_WAIT_SECONDS,
) -> bool:
    kind = result.get("kind") or ai_transport.UNKNOWN
    reason = result.get("reason")
    sent = bool(result.get("sent"))

    if kind == "stopped":
        return _end_paused(
            session, claim, result, now,
            reason=result.get("reason") or "user_stop",
            certainty=CERTAINTY_NOT_SENT,
        )

    if kind == ai_transport.NOT_SENT and result.get("transient_not_sent"):
        if claim.attempt_no < MAX_ATTEMPTS:
            delay = wait_seconds[min(claim.attempt_no - 1, len(wait_seconds) - 1)]
            return _retry_wait(session, claim, result, now, delay)
        return _end_failed(session, claim, result, now, reason="connection_unavailable", certainty=CERTAINTY_NOT_SENT)

    if kind == ai_transport.AUTH:
        return _end_paused(session, claim, result, now, reason="auth_rejected", certainty=CERTAINTY_UNKNOWN, block=True)
    if kind == ai_transport.CONFIG_REJECTED:
        return _end_paused(session, claim, result, now, reason="provider_error", certainty=CERTAINTY_UNKNOWN, block=True)
    if kind == ai_transport.RATE_LIMITED:
        return _end_paused(session, claim, result, now, reason="rate_limited", certainty=CERTAINTY_UNKNOWN, block=False)
    if kind == ai_transport.PROVIDER_ERROR:
        return _end_unknown(session, claim, result, now, reason="provider_error")
    if kind == ai_transport.UNKNOWN:
        return _end_unknown(session, claim, result, now, reason=reason or "timeout_after_dispatch")
    if kind == ai_transport.TLS_INVALID:
        return _end_failed(session, claim, result, now, reason="tls_invalid", certainty=CERTAINTY_NOT_SENT)
    if kind == ai_transport.POLICY:
        if sent:
            # A redirect / policy refusal after the request was written is
            # *not* proof the provider did not process it: keep the processing
            # certainty unknown so a retry requires an explicit risk ack, and
            # block the bad configuration.
            return _end_paused(session, claim, result, now, reason="endpoint_blocked", certainty=CERTAINTY_UNKNOWN, block=True)
        return _end_failed(session, claim, result, now, reason="endpoint_blocked", certainty=CERTAINTY_NOT_SENT)
    if kind == ai_transport.OUTPUT_INVALID:
        # A complete, successfully received but invalid model output *is* a
        # definite response.
        return _end_failed(session, claim, result, now, reason="output_invalid", certainty=CERTAINTY_RESPONSE)
    if kind == ai_transport.NOT_SENT:
        return _end_failed(session, claim, result, now, reason=reason or "connection_unavailable", certainty=CERTAINTY_NOT_SENT)
    return _end_unknown(session, claim, result, now, reason=reason or "provider_error")


def _block_config_if_requested(session: Session, task: LocalAITask, claim: Claim, now: datetime) -> None:
    state = session.get(LocalAIState, task.profile_id)
    if state is not None:
        state.blocked_config_version = claim.config_version
        state.blocked_reason = "provider_rejected"
        state.updated_at = now


def _end_paused(session, claim, result, now, *, reason, certainty, block=False) -> bool:
    begin_immediate(session)
    try:
        attempt, execution, task = _context(session, claim)
        if execution.state not in ("dispatching", "claimed") or not _permit_ok(task, execution, claim, attempt):
            rollback(session)
            return False
        _finish_attempt(attempt, "paused", result, now)
        meta = _meta(certainty, permit_revoked_at=now)
        _close_execution(execution, "paused", meta, now)
        task.status = "paused"
        task.reason = reason
        task.runtime_meta_json = meta
        task.updated_at = now
        if block:
            _block_config_if_requested(session, task, claim, now)
        _cleanup_credentials(session, task.profile_id, now)
        session.commit()
        return True
    except Exception:
        rollback(session)
        raise


def _end_unknown(session, claim, result, now, *, reason) -> bool:
    begin_immediate(session)
    try:
        attempt, execution, task = _context(session, claim)
        if execution.state not in ("dispatching", "claimed") or not _permit_ok(task, execution, claim, attempt):
            rollback(session)
            return False
        _finish_attempt(attempt, "outcome_unknown", result, now)
        meta = _meta(CERTAINTY_UNKNOWN, permit_revoked_at=now)
        _close_execution(execution, "outcome_unknown", meta, now)
        task.status = "outcome_unknown"
        task.reason = reason
        task.runtime_meta_json = meta
        task.updated_at = now
        _cleanup_credentials(session, task.profile_id, now)
        session.commit()
        return True
    except Exception:
        rollback(session)
        raise


def _end_failed(session, claim, result, now, *, reason, certainty) -> bool:
    begin_immediate(session)
    try:
        attempt, execution, task = _context(session, claim)
        if not _permit_ok(task, execution, claim, attempt):
            rollback(session)
            return False
        if execution.state not in ("dispatching", "claimed"):
            rollback(session)
            return False
        _finish_attempt(attempt, "failed", result, now)
        meta = _meta(certainty, permit_revoked_at=now)
        _close_execution(execution, "failed", meta, now)
        task.status = "failed"
        task.reason = reason
        task.runtime_meta_json = meta
        task.updated_at = now
        _cleanup_credentials(session, task.profile_id, now)
        session.commit()
        return True
    except Exception:
        rollback(session)
        raise


def _retry_wait(session, claim, result, now, delay) -> bool:
    begin_immediate(session)
    try:
        attempt, execution, task = _context(session, claim)
        if not _permit_ok(task, execution, claim, attempt) or execution.state not in ("dispatching", "claimed"):
            rollback(session)
            return False
        _finish_attempt(attempt, "retry_wait", result, now)
        next_at = now + timedelta(seconds=delay)
        meta = _meta(CERTAINTY_NOT_SENT, next_attempt_at=next_at)
        execution.state = "retry_wait"
        execution.runtime_meta_json = meta
        execution.ended_at = None
        task.status = "retry_wait"
        task.reason = None
        task.runtime_meta_json = meta
        task.updated_at = now
        session.commit()
        return True
    except Exception:
        rollback(session)
        raise


def revoke_all_for_close(session: Session, *, now: datetime) -> dict[str, int]:
    """One transaction: revoke every unfinished permit for a stop-and-exit.

    Classification follows the persisted send evidence (spec §4.3): a task
    whose attempt was dispatched becomes ``outcome_unknown`` with the user-stop
    intent; an unsent task becomes ``paused``. A task already ``succeeded`` is
    never touched. Every referenced execution is ended and credentials are
    reconciled. Returns counts; the caller must not kill any worker when this
    raises or reports a failure.
    """
    begin_immediate(session)
    try:
        profile_id = _profile_id(session)
        rows = list(
            session.scalars(
                select(LocalAITask).where(LocalAITask.status.in_(LIVE_STATUSES))
            ).all()
        )
        counts = {"paused": 0, "unknown": 0, "touched": 0}
        for task in rows:
            execution = None
            if task.current_execution_id:
                execution = session.get(LocalAIExecution, task.current_execution_id)
            dispatched = bool(execution is not None and execution.state == "dispatching")
            if dispatched:
                meta = _meta(CERTAINTY_UNKNOWN, user_stop=True, permit_revoked_at=now)
                task.status = "outcome_unknown"
                task.reason = "user_stop"
                if execution is not None:
                    _end_open_attempt(session, execution, now=now, dispatched=True)
                    _close_execution(execution, "outcome_unknown", meta, now)
                counts["unknown"] += 1
            else:
                meta = _meta(CERTAINTY_NOT_SENT, user_stop=True, permit_revoked_at=now)
                task.status = "paused"
                task.reason = "user_stop"
                if execution is not None and execution.ended_at is None:
                    _end_open_attempt(session, execution, now=now, dispatched=False)
                    _close_execution(execution, "paused", meta, now)
                counts["paused"] += 1
            task.runtime_meta_json = meta
            task.updated_at = now
            counts["touched"] += 1
        if rows:
            _cleanup_credentials(session, profile_id, now)
        session.commit()
        return counts
    except BaseException:
        rollback(session)
        raise


def recover_on_start(session: Session, *, now: datetime) -> dict[str, int]:
    """Cold-start classification only; never starts an outbound request."""
    begin_immediate(session)
    try:
        counts = {"paused": 0, "unknown": 0, "execution_ended": 0}
        profile_id = _profile_id(session)
        rows = list(session.scalars(select(LocalAITask).where(LocalAITask.status.in_(LIVE_STATUSES))).all())
        for task in rows:
            execution = None
            if task.current_execution_id:
                execution = session.get(LocalAIExecution, task.current_execution_id)
            dispatched = bool(execution is not None and execution.state == "dispatching")
            if dispatched:
                task.status = "outcome_unknown"
                task.reason = "restart"
                task.runtime_meta_json = _meta(CERTAINTY_UNKNOWN, permit_revoked_at=now)
                counts["unknown"] += 1
            else:
                task.status = "paused"
                task.reason = "restart"
                task.runtime_meta_json = _meta(CERTAINTY_NOT_SENT, permit_revoked_at=now)
                counts["paused"] += 1
            task.updated_at = now
            if execution is not None and execution.ended_at is None:
                _end_open_attempt(session, execution, now=now, dispatched=dispatched)
                execution.state = task.status
                execution.runtime_meta_json = dict(task.runtime_meta_json)
                execution.ended_at = now
                counts["execution_ended"] += 1
        if rows:
            _cleanup_credentials(session, profile_id, now)
        session.commit()
        return counts
    except BaseException:
        rollback(session)
        raise


def active_task_snapshot(session: Session) -> dict[str, Any]:
    """Read-only counts used by the host's final close barrier.

    A database that has not been initialised yet has no profile and therefore
    zero tasks — a *legal* state, not an error. A real read failure still
    raises so the host can fail closed.
    """
    with read_scope(session):
        if session.scalars(select(LocalProfile)).first() is None:
            return {"live": 0, "pending_manual": 0, "counts": {}, "no_profile": True}
        rows = session.execute(
            select(LocalAITask.status, func.count()).group_by(LocalAITask.status)
        ).all()
        counts = {status: int(count) for status, count in rows}
        live = sum(counts.get(status, 0) for status in LIVE_STATUSES)
        return {"live": live, "pending_manual": counts.get("paused", 0), "counts": counts}


__all__ = [
    "CERTAINTY_NOT_SENT",
    "CERTAINTY_RESPONSE",
    "CERTAINTY_UNKNOWN",
    "Claim",
    "LIVE_STATUSES",
    "MAX_ATTEMPTS",
    "OP_CANCEL",
    "OP_CREATE",
    "OP_RESUME",
    "OP_RETRY",
    "active_task_snapshot",
    "cancel_task",
    "claim_next",
    "commit_dispatch_mark",
    "create_task",
    "finalize_failure",
    "finalize_success",
    "get_task",
    "list_tasks",
    "peek_operation",
    "recover_on_start",
    "require_task",
    "resume_task",
    "retry_task",
    "revoke_all_for_close",
    "task_out",
]
