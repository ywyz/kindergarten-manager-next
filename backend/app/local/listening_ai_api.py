"""Authenticated local HTTP routes for one-to-one listening AI."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr
from sqlalchemy.orm import Session

from app.local import ai_task_service, listening_ai_adoption, listening_ai_service
from app.local.api import (
    _launch_id,
    _require_executor,
    _session_scope,
    _task_progress,
    get_session,
)
from app.local.errors import LocalAiExecutorUnavailable, LocalValidationError
from app.local.observation_api import _profile_id
from app.local.schemas import LocalAITaskActionIn, LocalAITaskRetryIn
from app.local.tx import storage_errors

router = APIRouter(prefix="/api/listening", tags=["listening-ai"])


class ListeningAICreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: StrictStr
    expected_revision: StrictInt
    domain: Literal["health", "language", "social", "science", "art"]
    group_id: StrictStr | None = None
    task_type: Literal["listening_note_draft", "listening_domain_evaluate"]


class ListeningAIAdoptionPreviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_id: StrictStr


class ListeningAIAdoptionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: StrictStr
    expected_revision: StrictInt
    preview_token: StrictStr
    selections: list[dict[str, Any]] = Field(min_length=1, max_length=100)


def _bound_task(session: Session, record_id: str, task_id: str):
    task = ai_task_service.require_task(
        session,
        task_id,
        source_kind="one_to_one_listening",
        source_id=record_id,
    )
    if task.listening_record_id != record_id:
        from app.local.errors import LocalAiNotFound

        raise LocalAiNotFound("未找到该倾听 AI 任务")
    return task


@router.post(
    "/records/{record_id}/ai/tasks",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=dict[str, Any],
)
def create_task(
    record_id: str,
    data: ListeningAICreateIn,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
):
    profile_id = _profile_id(session)
    with storage_errors():
        replay = listening_ai_service.peek_create(
            session,
            profile_id=profile_id,
            record_id=record_id,
            request_id=data.request_id,
            task_type=data.task_type,
            expected_revision=data.expected_revision,
            domain=data.domain,
            group_id=data.group_id,
        )
    if replay is not None:
        response.status_code = status.HTTP_200_OK
        return replay
    executor = _require_executor(request)
    if getattr(executor, "is_frozen", lambda: False)():
        raise LocalAiExecutorUnavailable()
    with storage_errors():
        result, created = listening_ai_service.create_task(
            session,
            runtime=request.app.state.runtime,
            profile_id=profile_id,
            record_id=record_id,
            domain=data.domain,
            group_id=data.group_id,
            task_type=data.task_type,
            expected_revision=data.expected_revision,
            request_id=data.request_id,
        )
        executor.notify()
    if not created:
        response.status_code = status.HTTP_200_OK
    return result


@router.get("/records/{record_id}/ai/operations/{request_id}")
def get_operation(
    record_id: str,
    request_id: str,
    session: Session = Depends(get_session),
):
    with storage_errors():
        return listening_ai_service.get_operation(
            session,
            profile_id=_profile_id(session),
            record_id=record_id,
            request_id=request_id,
        )


@router.get("/records/{record_id}/ai/tasks")
def list_tasks(
    record_id: str,
    domain: str | None = Query(default=None),
    status_: str | None = Query(default=None, alias="status"),
    limit: int = Query(ai_task_service.DEFAULT_LIST_LIMIT),
    cursor: str | None = None,
    session: Session = Depends(get_session),
):
    with storage_errors():
        return listening_ai_service.list_tasks(
            session,
            profile_id=_profile_id(session),
            record_id=record_id,
            domain=domain,
            status=status_,
            limit=limit,
            cursor=cursor,
        )


@router.get("/records/{record_id}/ai/tasks/{task_id}")
def get_task(
    record_id: str,
    task_id: str,
    session: Session = Depends(get_session),
):
    with storage_errors():
        _profile_id(session)
        _bound_task(session, record_id, task_id)
        return listening_ai_service.get_task(
            session,
            profile_id=_profile_id(session),
            record_id=record_id,
            task_id=task_id,
        )


@router.get("/records/{record_id}/ai/tasks/{task_id}/progress")
def get_progress(
    record_id: str,
    task_id: str,
    session: Session = Depends(get_session),
):
    with storage_errors():
        _profile_id(session)
        _bound_task(session, record_id, task_id)
        return _task_progress(
            session,
            task_id,
            source_kind="one_to_one_listening",
            source_id=record_id,
        )


@router.get("/records/{record_id}/ai/tasks/{task_id}/candidate")
def get_candidate(
    record_id: str,
    task_id: str,
    session: Session = Depends(get_session),
):
    with storage_errors():
        return listening_ai_service.get_candidate(
            session,
            profile_id=_profile_id(session),
            record_id=record_id,
            task_id=task_id,
        )


@router.post(
    "/records/{record_id}/ai/candidates/{candidate_id}/preview-adoption"
)
def preview_adoption(
    record_id: str,
    candidate_id: str,
    data: ListeningAIAdoptionPreviewIn,
    request: Request,
    session: Session = Depends(get_session),
):
    if data.candidate_id != candidate_id:
        raise LocalValidationError("预览 URL 候选与请求候选不一致")
    with storage_errors():
        return listening_ai_adoption.preview(
            session,
            runtime=request.app.state.runtime,
            profile_id=_profile_id(session),
            record_id=record_id,
            candidate_id=candidate_id,
            launch_id=_launch_id(request),
            session_scope_hash=_session_scope(request),
        )


@router.post(
    "/records/{record_id}/ai/candidates/{candidate_id}/adopt",
    status_code=status.HTTP_201_CREATED,
)
def adopt(
    record_id: str,
    candidate_id: str,
    data: ListeningAIAdoptionIn,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
):
    with storage_errors():
        result = listening_ai_adoption.adopt(
            session,
            runtime=request.app.state.runtime,
            profile_id=_profile_id(session),
            record_id=record_id,
            request_id=data.request_id,
            expected_revision=data.expected_revision,
            preview_token=data.preview_token,
            selections=data.selections,
            candidate_id=candidate_id,
            launch_id=_launch_id(request),
            session_scope_hash=_session_scope(request),
        )
        if result.get("replayed"):
            response.status_code = status.HTTP_200_OK
        return result


@router.post(
    "/records/{record_id}/ai/tasks/{task_id}/cancel",
    status_code=status.HTTP_202_ACCEPTED,
)
def cancel_task(
    record_id: str,
    task_id: str,
    data: LocalAITaskActionIn,
    request: Request,
    session: Session = Depends(get_session),
):
    with storage_errors():
        _bound_task(session, record_id, task_id)
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
    started = bool(data.expected_execution_id) and executor.begin_cancel(
        data.expected_execution_id
    )
    committed = False
    try:
        with storage_errors():
            result, abort_id, abort_kind = ai_task_service.cancel_task(
                session,
                task_id=task_id,
                expected_execution_id=data.expected_execution_id,
                request_id=data.request_id,
                source_kind="one_to_one_listening",
                source_id=record_id,
            )
            committed = True
    finally:
        if started:
            executor.end_cancel(
                data.expected_execution_id, committed=committed
            )
        executor.notify()
    if abort_kind == "stop_wait" and abort_id:
        executor.abort_execution(abort_id, "stop_wait")
    return result


@router.post(
    "/records/{record_id}/ai/tasks/{task_id}/resume",
    status_code=status.HTTP_202_ACCEPTED,
)
def resume_task(
    record_id: str,
    task_id: str,
    data: LocalAITaskActionIn,
    request: Request,
    session: Session = Depends(get_session),
):
    with storage_errors():
        _bound_task(session, record_id, task_id)
        result = ai_task_service.resume_task(
            session,
            task_id=task_id,
            expected_execution_id=data.expected_execution_id,
            request_id=data.request_id,
            runtime=request.app.state.runtime,
            source_kind="one_to_one_listening",
            source_id=record_id,
        )
        if request.app.state.executor is not None:
            request.app.state.executor.notify()
    return result


@router.post(
    "/records/{record_id}/ai/tasks/{task_id}/retry",
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_task(
    record_id: str,
    task_id: str,
    data: LocalAITaskRetryIn,
    request: Request,
    session: Session = Depends(get_session),
):
    with storage_errors():
        _bound_task(session, record_id, task_id)
        result = ai_task_service.retry_task(
            session,
            task_id=task_id,
            expected_execution_id=data.expected_execution_id,
            ack_duplicate_cost=data.ack_duplicate_cost,
            request_id=data.request_id,
            runtime=request.app.state.runtime,
            source_kind="one_to_one_listening",
            source_id=record_id,
        )
        if request.app.state.executor is not None:
            request.app.state.executor.notify()
    return result


__all__ = ["router"]
