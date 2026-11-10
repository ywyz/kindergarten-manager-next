"""Protected local HTTP routes for directional revisions."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr
from sqlalchemy.orm import Session

from app.local import ai_task_service, directional_revision
from app.local.api import _require_executor, get_session
from app.local.errors import LocalAiExecutorUnavailable, LocalAiNotFound
from app.local.models import LocalAITask
from app.local.observation_api import _profile_id
from app.local.tx import read_scope, storage_errors

router = APIRouter(
    prefix="/api/local/directional-revisions",
    tags=["directional-revisions"],
)


class DirectionalScopeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal[
        "listening_record", "listening_candidate", "weekly_candidate"
    ]
    record_id: StrictStr
    version: StrictInt
    candidate_id: StrictStr | None = None
    task_id: StrictStr | None = None
    domain: StrictStr | None = None
    group_id: StrictStr | None = None
    field: StrictStr


class DirectionalSelectionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: StrictInt
    end: StrictInt
    text: StrictStr


class DirectionalRevisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: StrictStr
    scope: DirectionalScopeIn
    field_text: StrictStr
    selection: DirectionalSelectionIn
    instruction: StrictStr


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=dict[str, Any],
)
def create_directional_revision(
    data: DirectionalRevisionIn,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
):
    scope = data.scope.model_dump()
    with storage_errors():
        replay = ai_task_service.peek_directional_revision_create(
            session,
            request_id=data.request_id,
            scope=scope,
            field_text=data.field_text,
            selection=data.selection.model_dump(),
            instruction=data.instruction,
        )
    if replay is not None:
        response.status_code = status.HTTP_200_OK
        return replay
    executor = _require_executor(request)
    if getattr(executor, "is_frozen", lambda: False)():
        raise LocalAiExecutorUnavailable()
    with storage_errors():
        result, created = ai_task_service.create_directional_revision_task(
            session,
            runtime=request.app.state.runtime,
            request_id=data.request_id,
            scope=scope,
            field_text=data.field_text,
            selection=data.selection.model_dump(),
            instruction=data.instruction,
        )
        executor.notify()
    if not created:
        response.status_code = status.HTTP_200_OK
    return result


@router.get("/{task_id}", response_model=dict[str, Any])
def get_directional_revision(
    task_id: str,
    session: Session = Depends(get_session),
):
    profile_id = _profile_id(session)
    with storage_errors():
        with read_scope(session):
            task = session.get(LocalAITask, task_id, populate_existing=True)
            if (
                task is None
                or task.profile_id != profile_id
                or task.source_kind != directional_revision.SOURCE_KIND
            ):
                raise LocalAiNotFound("未找到该定向修改任务")
            return directional_revision.task_payload(session, task)


__all__ = ["router"]
