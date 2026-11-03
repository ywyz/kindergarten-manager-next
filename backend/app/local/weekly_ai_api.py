"""Authenticated local HTTP routes for weekly-plan AI."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.local import (
    ai_task_service,
    weekly_ai_adoption,
    weekly_ai_candidates,
    weekly_ai_contracts,
    weekly_ai_service,
)
from app.local.api import (
    _launch_id,
    _require_executor,
    _session_scope,
    _task_progress,
    get_session,
)
from app.local.errors import LocalAiExecutorUnavailable, LocalValidationError
from app.local.observation_api import _profile_id
from app.local.schemas import (
    WeeklyAIAdoptionIn,
    WeeklyAIAdoptionOut,
    WeeklyAIAdoptionPreviewIn,
    WeeklyAIAdoptionPreviewOut,
    WeeklyAICandidateListOut,
    WeeklyAICandidateOut,
    WeeklyAIColumnsCreateIn,
    WeeklyAICreateOut,
    WeeklyAIGamesCreateIn,
    WeeklyAIMaterialsCreateIn,
    WeeklyAIOperationOut,
    WeeklyAITaskListOut,
    WeeklyAITaskOut,
    LocalAITaskActionIn,
    LocalAITaskRetryIn,
)
from app.local.tx import storage_errors

weekly_ai_router = APIRouter(prefix="/api/weekly-plans", tags=["weekly-ai"])

COLUMN_TASK = {
    "key_week_focus": "weekly_key_week_focus",
    "environment_setup": "weekly_environment_setup",
    "habit_culture": "weekly_habit_culture",
    "home_cooperation": "weekly_home_cooperation",
}


def _specs(operation_kind: str, selected_fields: list[str] | None = None):
    if operation_kind == weekly_ai_service.GAMES:
        return [weekly_ai_service.WeeklyTaskSpec("weekly_games_select", "games")]
    if operation_kind == weekly_ai_service.MATERIALS:
        return [weekly_ai_service.WeeklyTaskSpec("weekly_materials_generate", "materials")]
    try:
        fields = weekly_ai_contracts.normalize_selected_fields(selected_fields)
        pairs = weekly_ai_contracts.task_types_for_columns(fields)
    except Exception as exc:
        raise LocalValidationError(str(getattr(exc, "code", "") or exc)) from None
    return [weekly_ai_service.WeeklyTaskSpec(task_type, target) for target, task_type in pairs]


def _payload(plan_id: str, operation_kind: str, expected: int, specs) -> dict[str, Any]:
    return {
        "weekly_plan_id": plan_id,
        "expected_draft_version": expected,
        "operation_kind": operation_kind,
        "selected_fields": [spec.target for spec in specs],
    }


def _create(
    *,
    plan_id: str,
    operation_kind: str,
    selected_fields: list[str] | None,
    data: Any,
    request: Request,
    response: Response,
    session: Session,
):
    specs = _specs(operation_kind, selected_fields)
    payload = _payload(plan_id, operation_kind, data.expected_draft_version, specs)
    profile_id = _profile_id(session)
    with storage_errors():
        replay = weekly_ai_service.peek_create_operation(
            session,
            profile_id=profile_id,
            plan_id=plan_id,
            request_id=data.request_id,
            operation_kind=operation_kind,
            payload=payload,
        )
    if replay is not None:
        response.status_code = status.HTTP_200_OK
        return replay
    executor = _require_executor(request)
    if getattr(executor, "is_frozen", lambda: False)():
        raise LocalAiExecutorUnavailable()
    with storage_errors():
        result, created = weekly_ai_service.create_weekly_tasks(
            session,
            runtime=request.app.state.runtime,
            profile_id=profile_id,
            plan_id=plan_id,
            request_id=data.request_id,
            expected_draft_version=data.expected_draft_version,
            operation_kind=operation_kind,
            task_specs=specs,
        )
        executor.notify()
    if not created:
        response.status_code = status.HTTP_200_OK
    return result


@weekly_ai_router.post(
    "/{plan_id}/ai/games",
    response_model=WeeklyAICreateOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_games(
    plan_id: str,
    data: WeeklyAIGamesCreateIn,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
):
    return _create(
        plan_id=plan_id,
        operation_kind=weekly_ai_service.GAMES,
        selected_fields=None,
        data=data,
        request=request,
        response=response,
        session=session,
    )


@weekly_ai_router.post(
    "/{plan_id}/ai/columns",
    response_model=WeeklyAICreateOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_columns(
    plan_id: str,
    data: WeeklyAIColumnsCreateIn,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
):
    return _create(
        plan_id=plan_id,
        operation_kind=weekly_ai_service.COLUMNS,
        selected_fields=list(data.selected_fields),
        data=data,
        request=request,
        response=response,
        session=session,
    )


@weekly_ai_router.post(
    "/{plan_id}/ai/materials",
    response_model=WeeklyAICreateOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_materials(
    plan_id: str,
    data: WeeklyAIMaterialsCreateIn,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
):
    return _create(
        plan_id=plan_id,
        operation_kind=weekly_ai_service.MATERIALS,
        selected_fields=None,
        data=data,
        request=request,
        response=response,
        session=session,
    )


@weekly_ai_router.get(
    "/{plan_id}/ai/operations/{request_id}", response_model=WeeklyAIOperationOut
)
def get_operation(
    plan_id: str, request_id: str, session: Session = Depends(get_session)
):
    with storage_errors():
        return weekly_ai_service.get_operation(
            session,
            profile_id=_profile_id(session),
            plan_id=plan_id,
            request_id=request_id,
        )


def _require_plan_task(session: Session, profile_id: str, plan_id: str, task_id: str):
    task = ai_task_service.require_task(
        session, task_id, source_kind="weekly_plan", weekly_plan_id=plan_id
    )
    if task.profile_id != profile_id:
        from app.local.errors import LocalAiNotFound

        raise LocalAiNotFound("未找到该 AI 任务")
    return task


@weekly_ai_router.get("/{plan_id}/ai/tasks", response_model=WeeklyAITaskListOut)
def list_tasks(
    plan_id: str,
    status_: str | None = Query(default=None, alias="status"),
    limit: int = Query(ai_task_service.DEFAULT_LIST_LIMIT),
    cursor: str | None = None,
    create_operation_id: str | None = None,
    session: Session = Depends(get_session),
):
    with storage_errors():
        weekly_ai_service.require_plan(
            session, profile_id=_profile_id(session), plan_id=plan_id
        )
        return ai_task_service.list_tasks(
            session,
            weekly_plan_id=plan_id,
            status=status_,
            limit=limit,
            cursor=cursor,
            source_kind="weekly_plan",
            create_operation_id=create_operation_id,
        )


@weekly_ai_router.get("/{plan_id}/ai/tasks/{task_id}", response_model=WeeklyAITaskOut)
def get_task(
    plan_id: str, task_id: str, session: Session = Depends(get_session)
):
    with storage_errors():
        _require_plan_task(session, _profile_id(session), plan_id, task_id)
        return ai_task_service.get_task(
            session, task_id, source_kind="weekly_plan", weekly_plan_id=plan_id
        )


@weekly_ai_router.get("/{plan_id}/ai/tasks/{task_id}/progress")
def get_progress(
    plan_id: str, task_id: str, session: Session = Depends(get_session)
):
    with storage_errors():
        _require_plan_task(session, _profile_id(session), plan_id, task_id)
        return _task_progress(
            session, task_id, source_kind="weekly_plan", weekly_plan_id=plan_id
        )


@weekly_ai_router.post(
    "/{plan_id}/ai/tasks/{task_id}/cancel", response_model=WeeklyAITaskOut
)
def cancel_task(
    plan_id: str,
    task_id: str,
    data: LocalAITaskActionIn,
    request: Request,
    session: Session = Depends(get_session),
):
    with storage_errors():
        _require_plan_task(session, _profile_id(session), plan_id, task_id)
        peek = ai_task_service.peek_operation(
            session,
            request_id=data.request_id,
            operation_kind=ai_task_service.OP_CANCEL,
            payload={"task_id": task_id, "expected_execution_id": data.expected_execution_id},
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
                source_kind="weekly_plan",
                weekly_plan_id=plan_id,
            )
            committed = True
    finally:
        if started:
            executor.end_cancel(expected, committed=committed)
        executor.notify()
    if abort_kind == "stop_wait" and abort_id:
        executor.abort_execution(abort_id, "stop_wait")
    return result


@weekly_ai_router.post(
    "/{plan_id}/ai/tasks/{task_id}/resume",
    response_model=WeeklyAITaskOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def resume_task(
    plan_id: str,
    task_id: str,
    data: LocalAITaskActionIn,
    request: Request,
    session: Session = Depends(get_session),
):
    with storage_errors():
        _require_plan_task(session, _profile_id(session), plan_id, task_id)
        peek = ai_task_service.peek_operation(
            session,
            request_id=data.request_id,
            operation_kind=ai_task_service.OP_RESUME,
            payload={"task_id": task_id, "expected_execution_id": data.expected_execution_id},
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
            source_kind="weekly_plan",
            weekly_plan_id=plan_id,
        )
        executor.notify()
    return result


@weekly_ai_router.post(
    "/{plan_id}/ai/tasks/{task_id}/retry",
    response_model=WeeklyAITaskOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_task(
    plan_id: str,
    task_id: str,
    data: LocalAITaskRetryIn,
    request: Request,
    session: Session = Depends(get_session),
):
    with storage_errors():
        _require_plan_task(session, _profile_id(session), plan_id, task_id)
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
            source_kind="weekly_plan",
            weekly_plan_id=plan_id,
        )
        executor.notify()
    return result


@weekly_ai_router.get(
    "/{plan_id}/ai/candidates", response_model=WeeklyAICandidateListOut
)
def list_candidates(
    plan_id: str,
    create_operation_id: str | None = None,
    task_id: str | None = None,
    limit: int = Query(20),
    cursor: str | None = None,
    session: Session = Depends(get_session),
):
    with storage_errors():
        return weekly_ai_candidates.list_candidates(
            session,
            profile_id=_profile_id(session),
            plan_id=plan_id,
            create_operation_id=create_operation_id,
            task_id=task_id,
            limit=limit,
            cursor=cursor,
        )


@weekly_ai_router.get(
    "/{plan_id}/ai/candidates/{candidate_id}", response_model=WeeklyAICandidateOut
)
def get_candidate(
    plan_id: str, candidate_id: str, session: Session = Depends(get_session)
):
    with storage_errors():
        return weekly_ai_candidates.get_candidate(
            session,
            profile_id=_profile_id(session),
            plan_id=plan_id,
            candidate_id=candidate_id,
        )


@weekly_ai_router.post(
    "/{plan_id}/ai/adoption-preview", response_model=WeeklyAIAdoptionPreviewOut
)
def adoption_preview(
    plan_id: str,
    data: WeeklyAIAdoptionPreviewIn,
    request: Request,
    session: Session = Depends(get_session),
):
    with storage_errors():
        return weekly_ai_adoption.preview_adoption(
            session,
            runtime=request.app.state.runtime,
            profile_id=_profile_id(session),
            plan_id=plan_id,
            expected_draft_version=data.expected_draft_version,
            selections=[item.model_dump() for item in data.selections],
            launch_id=_launch_id(request),
            session_scope_hash=_session_scope(request),
        )


@weekly_ai_router.post("/{plan_id}/ai/adopt", response_model=WeeklyAIAdoptionOut)
def adopt(
    plan_id: str,
    data: WeeklyAIAdoptionIn,
    request: Request,
    session: Session = Depends(get_session),
):
    executor = getattr(request.app.state, "executor", None)
    blocked = bool(executor is not None and getattr(executor, "is_frozen", lambda: False)())
    with storage_errors():
        return weekly_ai_adoption.adopt(
            session,
            runtime=request.app.state.runtime,
            profile_id=_profile_id(session),
            plan_id=plan_id,
            request_id=data.request_id,
            expected_draft_version=data.expected_draft_version,
            preview_token=data.preview_token,
            launch_id=_launch_id(request),
            session_scope_hash=_session_scope(request),
            blocked=blocked,
        )
