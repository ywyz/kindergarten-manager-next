"""HTTP routes for the local (desktop) API.

Identity, class and term are always server-derived from the single local
profile context; clients cannot pass ownership or permission fields. Only
``/api/local/health`` is available without the per-launch application
session, and only ``context``/``initialize`` work before the profile
exists (all other endpoints return 409 ``LOCAL_PROFILE_REQUIRED``).

D1B increments (spec §10): date-addressed context with the full term list,
old-term plan listing by *stored* term id, the preview/apply configuration
protocol with committed receipts, and the optional strict
``expected_config_version`` on plan creation.
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from typing import Iterator
from urllib.parse import quote

from fastapi import (
    APIRouter,
    Depends,
    Query,
    Request,
    Response,
    status,
)
from sqlalchemy.orm import Session

from app.local import (
    ai_adoption,
    ai_candidates,
    ai_progress,
    ai_task_service,
    calendar_read,
    config_service,
    daily_plan_service,
    export_service,
    profile_service,
)
from app.local.ai_transport import now_ticks
from app.local.ai_config_service import (
    clear_secret,
    get_config,
    get_operation,
    patch_config,
)
from app.local.errors import (
    LocalAiExecutorUnavailable,
    LocalPromptSyncUnavailable,
    LocalValidationError,
)
from app.local.normalize import normalize_initialization
from app.local.prompt_service import (
    accept_default,
    adapt_prompt,
    get_default,
    get_prompt,
    list_prompts,
    reject_default,
    save_prompt,
)
from app.local.schemas import (
    LocalAIConfigClearSecretIn,
    LocalAIConfigOperationOut,
    LocalAIConfigOut,
    LocalAIConfigPatchIn,
    LocalAIAdoptionIn,
    LocalAIAdoptionOut,
    LocalAIAdoptionPreviewIn,
    LocalAIAdoptionPreviewOut,
    LocalAICandidateListOut,
    LocalAICandidateOut,
    LocalAITaskActionIn,
    LocalAITaskCreateIn,
    LocalAITaskListOut,
    LocalAITaskOut,
    LocalAITaskRetryIn,
    LocalAIProgressOut,
    LocalCalendarOut,
    LocalClassGamesOut,
    LocalConfigApplyIn,
    LocalConfigApplyOut,
    LocalConfigPreviewIn,
    LocalConfigPreviewOut,
    LocalContextOut,
    LocalDailyExportIn,
    LocalDailyPlanCreateIn,
    LocalDailyPlanListOut,
    LocalDailyPlanOut,
    LocalDailyPlanPatchIn,
    LocalInitializeIn,
    LocalPromptAcceptDefaultIn,
    LocalPromptAdaptIn,
    LocalPromptDefaultOut,
    LocalPromptGuidancePatchIn,
    LocalPromptListOut,
    LocalPromptOut,
    LocalPromptRejectDefaultIn,
    LocalTermDailyPlanListOut,
)
from app.local.tx import read_scope, storage_errors

local_router = APIRouter(prefix="/api/local", tags=["local"])
plans_router = APIRouter(prefix="/api", tags=["daily-plans"])
exports_router = APIRouter(prefix="/api/exports", tags=["exports"])

DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
_ASCII_SAFE = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"


def get_session(request: Request) -> Iterator[Session]:
    """One independent Session per request; always closed."""
    session = request.app.state.runtime.session()
    try:
        yield session
    finally:
        session.close()


def _optional(data, field: str, sentinel):
    """Distinguish an omitted optional field from an explicit null."""
    return getattr(data, field) if field in data.model_fields_set else sentinel


def _reject_ownership_fields(**fields) -> None:
    """Ownership is server-derived; clients may never send these fields."""
    if any(value is not None for value in fields.values()):
        raise LocalValidationError("请求不得包含归属或权限字段")


@local_router.get("/context", response_model=LocalContextOut)
def get_context(
    date_: date | None = Query(default=None, alias="date"),
    session: Session = Depends(get_session),
):
    with storage_errors():
        return profile_service.read_context(session, date_)


@local_router.post(
    "/initialize",
    response_model=LocalContextOut,
    status_code=status.HTTP_201_CREATED,
)
def initialize(
    response: Response,
    data: LocalInitializeIn,
    session: Session = Depends(get_session),
):
    normalized = normalize_initialization(
        request_id=data.request_id,
        display_name=data.display_name,
        class_name=data.class_name,
        grade=data.grade,
        term_name=data.term_name,
        start_date=data.start_date,
        end_date=data.end_date,
        school_name=data.school_name,
    )
    with storage_errors():
        payload, created = profile_service.initialize(session, normalized)
    if not created:
        # Same-key retry or a concurrent commit reads the current
        # configuration back (later maintenance is never rolled back).
        response.status_code = status.HTTP_200_OK
    return payload


@local_router.get("/calendar", response_model=LocalCalendarOut)
def get_calendar(
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
    class_id: str | None = None,
    term_id: str | None = None,
    creator_id: str | None = None,
    session: Session = Depends(get_session),
):
    _reject_ownership_fields(
        class_id=class_id, term_id=term_id, creator_id=creator_id
    )
    with storage_errors():
        with read_scope(session):
            context = profile_service.require_context(session, date.today())
            items = calendar_read.explain_range(
                session,
                class_id=context.school_class.id,
                from_date=from_date,
                to_date=to_date,
            )
    return {"from_date": from_date, "to_date": to_date, "items": items}


@local_router.get(
    "/terms/{term_id}/daily-plans", response_model=LocalTermDailyPlanListOut
)
def list_term_daily_plans(
    term_id: str,
    offset: int = Query(0),
    limit: int = Query(daily_plan_service.DEFAULT_LIST_LIMIT),
    class_id: str | None = None,
    creator_id: str | None = None,
    session: Session = Depends(get_session),
):
    _reject_ownership_fields(class_id=class_id, creator_id=creator_id)
    with storage_errors():
        return daily_plan_service.list_plans_by_term(
            session, term_id=term_id, offset=offset, limit=limit
        )


@local_router.post(
    "/config/preview", response_model=LocalConfigPreviewOut
)
def config_preview(
    data: LocalConfigPreviewIn,
    session: Session = Depends(get_session),
):
    with storage_errors():
        return config_service.preview(
            session,
            expected_config_version=data.expected_config_version,
            change=data.change.model_dump(),
        )


@local_router.post("/config/apply", response_model=LocalConfigApplyOut)
def config_apply(
    data: LocalConfigApplyIn,
    session: Session = Depends(get_session),
):
    with storage_errors():
        return config_service.apply(
            session,
            request_id=data.request_id,
            expected_config_version=data.expected_config_version,
            change=data.change.model_dump(),
            preview_token=data.preview_token,
        )


@local_router.get(
    "/config/operations/{request_id}", response_model=LocalConfigApplyOut
)
def config_operation(
    request_id: str,
    session: Session = Depends(get_session),
):
    with storage_errors():
        return config_service.get_operation(session, request_id=request_id)


@local_router.get("/config/class-games", response_model=LocalClassGamesOut)
def config_class_games_read(
    session: Session = Depends(get_session),
):
    with storage_errors():
        return config_service.read_class_games(session)


# ---------------------------------------------------------------------------
# D2 AI configuration (engineering spec §5)
# ---------------------------------------------------------------------------


@local_router.get("/ai/config", response_model=LocalAIConfigOut)
def ai_config_get(
    request: Request,
    session: Session = Depends(get_session),
):
    runtime = request.app.state.runtime
    with storage_errors():
        result = get_config(session, credential_root=runtime.credential_root)
        return result.to_dict()


@local_router.patch("/ai/config", response_model=LocalAIConfigOut)
def ai_config_patch(
    request: Request,
    data: LocalAIConfigPatchIn,
    session: Session = Depends(get_session),
):
    runtime = request.app.state.runtime
    with storage_errors():
        result = patch_config(
            session,
            expected_ai_config_version=data.expected_ai_config_version,
            base_url=data.base_url,
            model=data.model,
            secret=data.secret,
            secret_provided="secret" in data.model_fields_set,
            request_id=data.request_id,
            credential_root=runtime.credential_root,
        )
        return result.to_dict()


@local_router.post("/ai/config/clear-secret", response_model=LocalAIConfigOut)
def ai_config_clear_secret(
    request: Request,
    data: LocalAIConfigClearSecretIn,
    session: Session = Depends(get_session),
):
    runtime = request.app.state.runtime
    with storage_errors():
        result = clear_secret(
            session,
            expected_ai_config_version=data.expected_ai_config_version,
            request_id=data.request_id,
            credential_root=runtime.credential_root,
        )
        return result.to_dict()


@local_router.get("/ai/operations/{request_id}", response_model=LocalAIConfigOperationOut)
def ai_operations_get(
    request_id: str,
    session: Session = Depends(get_session),
):
    with storage_errors():
        return get_operation(session, request_id=request_id)


def _require_prompt_sync(request: Request) -> None:
    """Block only the AI prompt endpoints when the package sync failed."""
    runtime = request.app.state.runtime
    error = getattr(runtime, "prompt_sync_error", None)
    if error:
        raise LocalPromptSyncUnavailable(details={"reason": error})


@local_router.get("/ai/prompts", response_model=LocalPromptListOut)
def ai_prompts_list(
    request: Request,
    session: Session = Depends(get_session),
):
    with storage_errors():
        _require_prompt_sync(request)
        return list_prompts(session)


@local_router.get(
    "/ai/prompts/{task_type}/defaults/{contract_version}/{default_revision}",
    response_model=LocalPromptDefaultOut,
)
def ai_prompt_default(
    task_type: str,
    contract_version: int,
    default_revision: int,
    request: Request,
    session: Session = Depends(get_session),
):
    with storage_errors():
        _require_prompt_sync(request)
        return get_default(
            session,
            task_type=task_type,
            contract_version=contract_version,
            default_revision=default_revision,
        )


@local_router.get("/ai/prompts/{task_type}", response_model=LocalPromptOut)
def ai_prompt_get(
    task_type: str,
    request: Request,
    session: Session = Depends(get_session),
):
    with storage_errors():
        _require_prompt_sync(request)
        return get_prompt(session, task_type=task_type)


@local_router.patch("/ai/prompts/{task_type}", response_model=LocalPromptOut)
def ai_prompt_patch(
    task_type: str,
    data: LocalPromptGuidancePatchIn,
    request: Request,
    session: Session = Depends(get_session),
):
    with storage_errors():
        _require_prompt_sync(request)
        return save_prompt(
            session,
            task_type=task_type,
            expected_personal_revision=data.expected_personal_revision,
            contract_version=data.contract_version,
            guidance=data.guidance,
            request_id=data.request_id,
        )


@local_router.post(
    "/ai/prompts/{task_type}/accept-default", response_model=LocalPromptOut
)
def ai_prompt_accept_default(
    task_type: str,
    data: LocalPromptAcceptDefaultIn,
    request: Request,
    session: Session = Depends(get_session),
):
    with storage_errors():
        _require_prompt_sync(request)
        return accept_default(
            session,
            task_type=task_type,
            expected_personal_revision=data.expected_personal_revision,
            target_contract_version=data.target_contract_version,
            target_default_revision=data.target_default_revision,
            selected_fields=data.selected_fields,
            request_id=data.request_id,
        )


@local_router.post(
    "/ai/prompts/{task_type}/reject-default", response_model=LocalPromptOut
)
def ai_prompt_reject_default(
    task_type: str,
    data: LocalPromptRejectDefaultIn,
    request: Request,
    session: Session = Depends(get_session),
):
    with storage_errors():
        _require_prompt_sync(request)
        return reject_default(
            session,
            task_type=task_type,
            expected_personal_revision=data.expected_personal_revision,
            target_contract_version=data.target_contract_version,
            target_default_revision=data.target_default_revision,
            request_id=data.request_id,
        )


@local_router.post("/ai/prompts/{task_type}/adapt", response_model=LocalPromptOut)
def ai_prompt_adapt(
    task_type: str,
    data: LocalPromptAdaptIn,
    request: Request,
    session: Session = Depends(get_session),
):
    with storage_errors():
        _require_prompt_sync(request)
        return adapt_prompt(
            session,
            task_type=task_type,
            expected_personal_revision=data.expected_personal_revision,
            target_contract_version=data.target_contract_version,
            target_default_revision=data.target_default_revision,
            guidance=data.guidance,
            request_id=data.request_id,
        )


@plans_router.get("/daily-plans", response_model=LocalDailyPlanListOut)
def list_daily_plans(
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
    offset: int = Query(0),
    limit: int = Query(daily_plan_service.DEFAULT_LIST_LIMIT),
    class_id: str | None = None,
    term_id: str | None = None,
    creator_id: str | None = None,
    session: Session = Depends(get_session),
):
    _reject_ownership_fields(
        class_id=class_id, term_id=term_id, creator_id=creator_id
    )
    with storage_errors():
        return daily_plan_service.list_plans(
            session,
            from_date=from_date,
            to_date=to_date,
            offset=offset,
            limit=limit,
        )


# Registered before /daily-plans/{plan_id} so "by-date" is not captured as
# a path parameter.
@plans_router.get("/daily-plans/by-date", response_model=LocalDailyPlanOut)
def get_daily_plan_by_date(
    date_: date = Query(..., alias="date"),
    class_id: str | None = None,
    term_id: str | None = None,
    creator_id: str | None = None,
    session: Session = Depends(get_session),
):
    _reject_ownership_fields(
        class_id=class_id, term_id=term_id, creator_id=creator_id
    )
    with storage_errors():
        return daily_plan_service.get_by_date(session, plan_date=date_)


@plans_router.post(
    "/daily-plans",
    response_model=LocalDailyPlanOut,
    status_code=status.HTTP_201_CREATED,
)
def create_daily_plan(
    response: Response,
    data: LocalDailyPlanCreateIn,
    session: Session = Depends(get_session),
):
    with storage_errors():
        payload, created = daily_plan_service.create_or_open(
            session,
            plan_date=data.plan_date,
            raw_lesson_plan=_optional(
                data, "raw_lesson_plan", daily_plan_service.UNSET
            ),
            adopted_content=_optional(
                data, "adopted_content", daily_plan_service.UNSET
            ),
            expected_config_version=data.expected_config_version,
        )
    if not created:
        response.status_code = status.HTTP_200_OK
    return payload


@plans_router.get("/daily-plans/{plan_id}", response_model=LocalDailyPlanOut)
def get_daily_plan(
    plan_id: str,
    class_id: str | None = None,
    term_id: str | None = None,
    creator_id: str | None = None,
    session: Session = Depends(get_session),
):
    _reject_ownership_fields(
        class_id=class_id, term_id=term_id, creator_id=creator_id
    )
    with storage_errors():
        return daily_plan_service.get_plan(session, plan_id=plan_id)


@plans_router.patch("/daily-plans/{plan_id}", response_model=LocalDailyPlanOut)
def patch_daily_plan(
    plan_id: str,
    data: LocalDailyPlanPatchIn,
    session: Session = Depends(get_session),
):
    with storage_errors():
        return daily_plan_service.save(
            session,
            plan_id=plan_id,
            expected_content_version=data.expected_content_version,
            raw_lesson_plan=_optional(
                data, "raw_lesson_plan", daily_plan_service.UNSET
            ),
            adopted_content=_optional(
                data, "adopted_content", daily_plan_service.UNSET
            ),
        )


def _require_executor(request: Request):
    executor = getattr(request.app.state, "executor", None)
    if executor is None or not getattr(executor, "is_runnable", lambda: False)():
        raise LocalAiExecutorUnavailable()
    return executor


@plans_router.post(
    "/daily-plans/{plan_id}/ai-tasks",
    response_model=LocalAITaskOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_ai_task(
    plan_id: str,
    data: LocalAITaskCreateIn,
    request: Request,
    session: Session = Depends(get_session),
):
    # Receipt priority: a committed same-key operation is read back even when
    # the executor is unavailable (never a 503 over a completed operation).
    with storage_errors():
        peek = ai_task_service.peek_operation(
            session,
            request_id=data.request_id,
            operation_kind=ai_task_service.OP_CREATE,
            payload={
                "plan_id": plan_id,
                "task_type": data.task_type,
                "expected_content_version": data.expected_content_version,
                "target_grade": data.target_grade,
            },
        )
    if peek is not None:
        return peek
    executor = _require_executor(request)
    with storage_errors():
        result, created = ai_task_service.create_task(
            session,
            plan_id=plan_id,
            task_type=data.task_type,
            expected_content_version=data.expected_content_version,
            target_grade=data.target_grade,
            request_id=data.request_id,
            runtime=request.app.state.runtime,
        )
        executor.notify()
    return result


@local_router.get("/ai/tasks", response_model=LocalAITaskListOut)
def list_ai_tasks(
    plan_id: str | None = None,
    status_: str | None = Query(default=None, alias="status"),
    limit: int = Query(ai_task_service.DEFAULT_LIST_LIMIT),
    cursor: str | None = None,
    session: Session = Depends(get_session),
):
    with storage_errors():
        return ai_task_service.list_tasks(
            session, plan_id=plan_id, status=status_, limit=limit, cursor=cursor
        )


@local_router.get("/ai/tasks/{task_id}", response_model=LocalAITaskOut)
def get_ai_task(task_id: str, session: Session = Depends(get_session)):
    with storage_errors():
        return ai_task_service.get_task(session, task_id)


@local_router.get("/ai/tasks/{task_id}/progress", response_model=LocalAIProgressOut)
def get_ai_task_progress(task_id: str, session: Session = Depends(get_session)):
    """Read-only display progress for the task's current execution.

    It never starts a task, opens a network connection or writes anything: a
    missing snapshot returns an explicit unavailable projection. The task is
    resolved through the normal profile-scoped read (foreign/missing = 404).
    """
    with storage_errors():
        task = ai_task_service.get_task(session, task_id)
        status = str(task.get("status") or "")
        execution = task.get("execution") or {}
        execution_id = execution.get("id")
        current_attempt = execution.get("attempt_no")
        if not execution_id:
            return {
                "available": False,
                "task_id": task_id,
                "execution_id": None,
                "attempt_id": None,
                "attempt_no": None,
                "seq": 0,
                "phase": "waiting" if status == "pending" else "unavailable",
                "elapsed_ms": 0,
                "last_data_age_ms": None,
                "reasoning": "",
                "content_chars": 0,
                "truncated": False,
            }
        if status == "pending":
            # Artificial retry/resume leaves the old execution id in place until
            # the next claim; it is history, not this pending activity.
            return {
                "available": False,
                "task_id": task_id,
                "execution_id": execution_id,
                "attempt_id": None,
                "attempt_no": current_attempt,
                "seq": 0,
                "phase": "waiting",
                "elapsed_ms": 0,
                "last_data_age_ms": None,
                "reasoning": "",
                "content_chars": 0,
                "truncated": False,
            }
        snapshot = ai_progress.snapshot(task_id, execution_id)
        if (
            snapshot is not None
            and isinstance(current_attempt, int)
            and snapshot["attempt_no"] != current_attempt
        ):
            # A new attempt has begun (or the snapshot is from an old one); it
            # must never be projected as the current attempt.
            snapshot = None
        if snapshot is not None and status == "claimed" and snapshot["ended"]:
            # A claim is pre-send; a finished snapshot on this execution is the
            # old activity, not the new claim's progress.
            return {
                "available": False,
                "task_id": task_id,
                "execution_id": execution_id,
                "attempt_id": None,
                "attempt_no": current_attempt,
                "seq": 0,
                "phase": "waiting",
                "elapsed_ms": 0,
                "last_data_age_ms": None,
                "reasoning": "",
                "content_chars": 0,
                "truncated": False,
            }
        if snapshot is None:
            return {
                "available": False,
                "task_id": task_id,
                "execution_id": execution_id,
                "attempt_no": current_attempt,
                "phase": "unavailable",
            }
        terminal = status in ("succeeded", "failed", "outcome_unknown", "cancelled", "paused")
        now = now_ticks()
        if terminal:
            end_ticks = (
                snapshot["ended_at_ticks"]
                or snapshot["last_data_ticks"]
                or snapshot["started_ticks"]
            )
            clock = end_ticks
        else:
            clock = now
        elapsed = max(0, clock - snapshot["started_ticks"])
        last_data = snapshot["last_data_ticks"]
        last_age = max(0, clock - last_data) if last_data else None
        phase = snapshot["phase"]
        if status == "succeeded":
            phase = "completed"
        elif status == "failed":
            phase = "failed"
        elif status == "outcome_unknown":
            phase = "unknown"
        elif status == "cancelled":
            phase = "cancelled"
        elif status == "paused":
            phase = "paused"
        elif snapshot["ended"] and snapshot["phase"] == "completed":
            # Transport success is not business success: while the persistent
            # task is still live, the result is being validated/persisted.
            phase = "validating"
        return {
            "available": True,
            "task_id": task_id,
            "execution_id": execution_id,
            "attempt_id": snapshot["attempt_id"],
            "attempt_no": snapshot["attempt_no"] or current_attempt,
            "seq": snapshot["seq"],
            "phase": phase,
            "elapsed_ms": elapsed,
            "last_data_age_ms": last_age,
            "reasoning": snapshot["reasoning"],
            "content_chars": snapshot["content_chars"],
            "truncated": snapshot["truncated"],
        }


def _current_execution_id(session: Session, task_id: str) -> str | None:
    from app.local.models import LocalAITask

    task = session.get(LocalAITask, task_id)
    return task.current_execution_id if task is not None else None


@local_router.post("/ai/tasks/{task_id}/cancel", response_model=LocalAITaskOut)
def cancel_ai_task(
    task_id: str,
    data: LocalAITaskActionIn,
    request: Request,
    session: Session = Depends(get_session),
):
    with storage_errors():
        peek = ai_task_service.peek_operation(
            session,
            request_id=data.request_id,
            operation_kind=ai_task_service.OP_CANCEL,
            payload={
                "task_id": task_id,
                "expected_execution_id": data.expected_execution_id,
            },
        )
    if peek is not None:
        return peek
    executor = _require_executor(request)
    expected = data.expected_execution_id
    started = bool(expected) and executor.begin_cancel(expected)
    committed = False
    try:
        with storage_errors():
            result, abort_id, abort_kind = ai_task_service.cancel_task(
                session,
                task_id=task_id,
                expected_execution_id=expected,
                request_id=data.request_id,
            )
            committed = True
    finally:
        if started:
            executor.end_cancel(expected, committed=committed)
        executor.notify()
    if abort_kind == "stop_wait" and abort_id:
        executor.abort_execution(abort_id, "stop_wait")
    return result


@local_router.post(
    "/ai/tasks/{task_id}/resume",
    response_model=LocalAITaskOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def resume_ai_task(
    task_id: str,
    data: LocalAITaskActionIn,
    request: Request,
    session: Session = Depends(get_session),
):
    executor = None
    with storage_errors():
        peek = ai_task_service.peek_operation(
            session,
            request_id=data.request_id,
            operation_kind=ai_task_service.OP_RESUME,
            payload={
                "task_id": task_id,
                "expected_execution_id": data.expected_execution_id,
            },
        )
    if peek is not None:
        return peek
    executor = _require_executor(request)
    with storage_errors():
        result = ai_task_service.resume_task(
            session,
            task_id=task_id,
            expected_execution_id=data.expected_execution_id,
            request_id=data.request_id,
            runtime=request.app.state.runtime,
        )
        executor.notify()
    return result


@local_router.post(
    "/ai/tasks/{task_id}/retry",
    response_model=LocalAITaskOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_ai_task(
    task_id: str,
    data: LocalAITaskRetryIn,
    request: Request,
    session: Session = Depends(get_session),
):
    with storage_errors():
        peek = ai_task_service.peek_operation(
            session,
            request_id=data.request_id,
            operation_kind=ai_task_service.OP_RETRY,
            payload={
                "task_id": task_id,
                "expected_execution_id": data.expected_execution_id,
                "ack_duplicate_cost": bool(data.ack_duplicate_cost),
            },
        )
    if peek is not None:
        return peek
    executor = _require_executor(request)
    with storage_errors():
        result = ai_task_service.retry_task(
            session,
            task_id=task_id,
            expected_execution_id=data.expected_execution_id,
            ack_duplicate_cost=data.ack_duplicate_cost,
            request_id=data.request_id,
            runtime=request.app.state.runtime,
        )
        executor.notify()
    return result


def _launch_id(request: Request) -> str:
    """The current launch id; tokens are invalid after a restart anyway."""
    runtime = request.app.state.runtime
    return str(getattr(runtime, "launch_id", "") or "")


def _session_scope(request: Request) -> str:
    """This app instance's internal adoption-token scope (never returned)."""
    return str(getattr(request.app.state, "session_scope", "") or "")


@plans_router.get(
    "/daily-plans/{plan_id}/ai-candidates",
    response_model=LocalAICandidateListOut,
)
def list_ai_candidates(
    plan_id: str,
    limit: int = Query(ai_candidates.DEFAULT_LIST_LIMIT),
    cursor: str | None = None,
    session: Session = Depends(get_session),
):
    with storage_errors():
        return ai_candidates.list_candidates(
            session, plan_id=plan_id, limit=limit, cursor=cursor
        )


@plans_router.get(
    "/daily-plans/{plan_id}/ai-candidates/{candidate_id}",
    response_model=LocalAICandidateOut,
)
def get_ai_candidate(
    plan_id: str,
    candidate_id: str,
    session: Session = Depends(get_session),
):
    with storage_errors():
        return ai_candidates.get_candidate(
            session, plan_id=plan_id, candidate_id=candidate_id
        )


@plans_router.post(
    "/daily-plans/{plan_id}/ai-candidates/{candidate_id}/preview-adoption",
    response_model=LocalAIAdoptionPreviewOut,
)
def preview_ai_adoption(
    plan_id: str,
    candidate_id: str,
    data: LocalAIAdoptionPreviewIn,
    request: Request,
    session: Session = Depends(get_session),
):
    with storage_errors():
        return ai_adoption.preview_adoption(
            session,
            plan_id=plan_id,
            candidate_id=candidate_id,
            expected_content_version=data.expected_content_version,
            selected_targets=data.selected_targets,
            edited_candidate=data.edited_candidate,
            launch_id=_launch_id(request),
            session_scope=_session_scope(request),
        )


@plans_router.post(
    "/daily-plans/{plan_id}/ai-candidates/{candidate_id}/adopt",
    response_model=LocalAIAdoptionOut,
)
def adopt_ai_candidate(
    plan_id: str,
    candidate_id: str,
    data: LocalAIAdoptionIn,
    request: Request,
    session: Session = Depends(get_session),
):
    with storage_errors():
        return ai_adoption.adopt(
            session,
            plan_id=plan_id,
            candidate_id=candidate_id,
            expected_content_version=data.expected_content_version,
            preview_token=data.preview_token,
            request_id=data.request_id,
            launch_id=_launch_id(request),
            session_scope=_session_scope(request),
        )


def _content_disposition(filename: str) -> str:
    ascii_fallback = "".join(
        char if char in _ASCII_SAFE else "_" for char in filename
    )
    return (
        f'attachment; filename="{ascii_fallback}"; '
        f"filename*=UTF-8''{quote(filename)}"
    )


@exports_router.post("/daily-plans")
def export_daily_plans(
    data: LocalDailyExportIn,
    session: Session = Depends(get_session),
):
    """Generate one DOCX from the database-saved versions (D1 spec §12.1).

    The read snapshot (selection, pinning, facts, ack context) runs in one
    explicit read transaction; the materialized DTOs are then mapped and the
    DOCX is generated after the transaction has ended. The native save
    dialog is the host's responsibility and never holds a transaction.
    """
    with storage_errors():
        bundle = export_service.prepare_export(
            session,
            from_date=data.from_,
            to_date=data.to,
            ack_missing=data.ack_missing,
            expected_context=data.expected_context,
        )
        export_service.raise_if_ack_required(bundle)
        payload = export_service.generate_docx(bundle)
        filename = export_service.suggested_filename(
            bundle.records, data.from_, data.to
        )
    return Response(
        content=payload,
        media_type=DOCX_MEDIA_TYPE,
        headers={
            "Content-Disposition": _content_disposition(filename),
            "X-Export-Warnings": json.dumps(
                list(bundle.warnings), ensure_ascii=True
            ),
            "Cache-Control": "no-store",
        },
    )
