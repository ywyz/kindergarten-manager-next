"""Protected local HTTP routes for curriculum deliberations."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.local import (
    ai_task_service,
    curriculum_ai,
    curriculum_content,
    curriculum_service,
    profile_service,
)
from app.local.api import _require_executor, _task_progress, get_session
from app.local.errors import (
    LocalAiExecutorUnavailable,
    LocalAiNotFound,
    LocalValidationError,
)
from app.local.tx import read_scope, storage_errors

curriculum_router = APIRouter(
    prefix="/api/local/curriculum-deliberations",
    tags=["curriculum-deliberations"],
)

_DOCX_MIME = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
_FILENAME_FORBIDDEN = frozenset('\\/:*?"<>|')


class CurriculumSaveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(..., ge=0, strict=True)
    content: dict[str, Any]
    document: dict[str, Any] | None = None


class CurriculumAiTaskIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    kind: Literal["split", "review", "edit"]
    version: int = Field(..., ge=0, strict=True)
    content: dict[str, Any]
    age_group: str | None = None
    instruction: str | None = None
    document: dict[str, Any] | None = None
    split_task_id: str | None = None
    resolutions: list[dict[str, Any]] | None = None
    selection: dict[str, Any] | None = None


def _profile_id(session: Session) -> str:
    with read_scope(session):
        context = profile_service.require_context(session, date.today())
    if context.profile is None:  # pragma: no cover - require_context guarantees it
        raise LocalValidationError("本地档案尚未初始化")
    return context.profile.id


def _filename(content: dict[str, str]) -> str:
    name = "".join(
        "_"
        if char in _FILENAME_FORBIDDEN or ord(char) < 32
        else char
        for char in curriculum_content.sanitize_export_text(
            content.get("activity_name") or ""
        )
    )
    name = " ".join(name.split()).strip(" .")[:120]
    if not name:
        name = "未命名活动"
    date_text = content.get("activity_date") or ""
    suffix = f"_{date_text}" if date_text else ""
    return f"课程审议记录表_{name}{suffix}.docx"


def _content_disposition(filename: str) -> str:
    fallback = "".join(
        char
        if char.isascii() and 32 <= ord(char) < 127 and char not in '"\\'
        else "_"
        for char in filename
    )
    return (
        f'attachment; filename="{fallback}"; '
        f"filename*=UTF-8''{quote(filename, safe='')}"
    )


@curriculum_router.get("", response_model=dict[str, Any])
def list_curriculum_deliberations(
    session: Session = Depends(get_session),
):
    with storage_errors():
        return curriculum_service.list_records(
            session, profile_id=_profile_id(session)
        )


@curriculum_router.get(
    "/{record_id}/export-preview", response_model=dict[str, Any]
)
def preview_curriculum_export(
    record_id: str,
    version: int = Query(...),
    session: Session = Depends(get_session),
):
    with storage_errors():
        return curriculum_service.export_preview(
            session,
            profile_id=_profile_id(session),
            record_id=record_id,
            version=version,
        )


@curriculum_router.get("/{record_id}/word")
def export_curriculum_word(
    record_id: str,
    version: int = Query(...),
    session: Session = Depends(get_session),
):
    with storage_errors():
        payload, content = curriculum_service.word_bytes(
            session,
            profile_id=_profile_id(session),
            record_id=record_id,
            version=version,
        )
    filename = _filename(content)
    return Response(
        content=payload,
        media_type=_DOCX_MIME,
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": _content_disposition(filename),
        },
    )


@curriculum_router.post(
    "/{record_id}/ai/tasks",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=dict[str, Any],
)
def create_curriculum_ai_task(
    record_id: str,
    data: CurriculumAiTaskIn,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
):
    replay = None
    with storage_errors():
        replay = ai_task_service.peek_curriculum_create(
            session,
            record_id=record_id,
            kind=data.kind,
            version=data.version,
            content=data.content,
            age_group=data.age_group,
            instruction=data.instruction,
            document=data.document,
            split_task_id=data.split_task_id,
            resolutions=data.resolutions,
            selection=data.selection,
            request_id=data.request_id,
        )
    if replay is not None:
        response.status_code = status.HTTP_200_OK
        return replay
    executor = _require_executor(request)
    if getattr(executor, "is_frozen", lambda: False)():
        raise LocalAiExecutorUnavailable()
    with storage_errors():
        result, created = ai_task_service.create_curriculum_task(
            session,
            runtime=request.app.state.runtime,
            record_id=record_id,
            kind=data.kind,
            version=data.version,
            content=data.content,
            age_group=data.age_group,
            instruction=data.instruction,
            document=data.document,
            split_task_id=data.split_task_id,
            resolutions=data.resolutions,
            selection=data.selection,
            request_id=data.request_id,
        )
    if not created:
        response.status_code = status.HTTP_200_OK
    return result


@curriculum_router.get(
    "/{record_id}/ai/tasks/{task_id}", response_model=dict[str, Any]
)
def read_curriculum_ai_task(
    record_id: str,
    task_id: str,
    session: Session = Depends(get_session),
):
    rid = curriculum_service.normalize_record_id(record_id)
    profile_id = _profile_id(session)
    with storage_errors():
        with read_scope(session):
            task = ai_task_service.require_task(
                session,
                task_id,
                source_kind=curriculum_ai.SOURCE_KIND,
                source_id=rid,
            )
            if task.profile_id != profile_id:
                raise LocalAiNotFound("未找到该 AI 任务")
            return curriculum_ai.task_payload(session, task)


@curriculum_router.get(
    "/{record_id}/ai/tasks/{task_id}/progress", response_model=dict[str, Any]
)
def read_curriculum_ai_task_progress(
    record_id: str,
    task_id: str,
    session: Session = Depends(get_session),
):
    """Display-only progress for this record's accepted execution.

    The shared read path binds the source kind and record id, so another
    record's task or a stale execution can never be projected here.
    """
    rid = curriculum_service.normalize_record_id(record_id)
    return _task_progress(
        session,
        task_id,
        source_kind=curriculum_ai.SOURCE_KIND,
        source_id=rid,
    )


@curriculum_router.get("/{record_id}", response_model=dict[str, Any])
def read_curriculum_deliberation(
    record_id: str,
    session: Session = Depends(get_session),
):
    with storage_errors():
        return curriculum_service.get_record(
            session,
            profile_id=_profile_id(session),
            record_id=record_id,
        )


@curriculum_router.post("/{record_id}/save", response_model=dict[str, Any])
def save_curriculum_deliberation(
    record_id: str,
    data: CurriculumSaveIn,
    session: Session = Depends(get_session),
):
    arguments: dict[str, Any] = {
        "profile_id": _profile_id(session),
        "record_id": record_id,
        "expected_version": data.expected_version,
        "content": data.content,
    }
    if "document" in data.model_fields_set:
        arguments["document"] = data.document
    with storage_errors():
        return curriculum_service.save_record(session, **arguments)


__all__ = ["curriculum_router"]
