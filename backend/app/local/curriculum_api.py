"""Protected local HTTP routes for curriculum deliberations."""

from __future__ import annotations

from datetime import date
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.local import curriculum_content, curriculum_service, profile_service
from app.local.api import get_session
from app.local.errors import LocalValidationError
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
    with storage_errors():
        return curriculum_service.save_record(
            session,
            profile_id=_profile_id(session),
            record_id=record_id,
            expected_version=data.expected_version,
            content=data.content,
        )


__all__ = ["curriculum_router"]
