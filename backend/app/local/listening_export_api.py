"""Protected local HTTP routes for one-to-one listening Word export.

Preview/generate/content ids are bearer tokens bound to the current launch,
profile, class/term and frozen snapshot.  The desktop host receives only the
export id, filename, size, SHA-256 and bounded content stream; it never gets
an arbitrary path or URL from the page.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr
from sqlalchemy.orm import Session

from app.local import listening_export_service, profile_service
from app.local.api import get_session
from app.local.errors import LocalValidationError
from app.local.tx import read_scope, storage_errors

listening_exports_router = APIRouter(
    prefix="/api/listening-exports", tags=["listening-exports"]
)


class ListeningExportPreviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["record", "domain"]
    record_id: StrictStr | None = None
    domain: StrictStr | None = None
    record_ids: list[StrictStr] | None = None
    term_id: StrictStr | None = None


class ListeningExportGenerateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preview_id: StrictStr = Field(min_length=1, max_length=200)
    request_id: StrictStr = Field(min_length=1, max_length=80)
    filename: StrictStr | None = Field(default=None, max_length=160)
    ack_missing: StrictBool = False


class ListeningExportPinIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    owner: StrictStr = Field(min_length=1, max_length=120)


def _manager(request: Request) -> listening_export_service.ListeningExportManager:
    manager = getattr(request.app.state, "listening_export_manager", None)
    if manager is None:
        raise LocalValidationError("倾听导出管理器尚未就绪")
    return manager


def _context(session: Session):
    with storage_errors():
        with read_scope(session):
            context = profile_service.require_context(session, date.today())
    if context.profile is None:
        raise LocalValidationError("本地档案尚未初始化")
    return context


@listening_exports_router.post("/preview", response_model=dict[str, Any])
def preview_listening_export(
    data: ListeningExportPreviewIn,
    request: Request,
    session: Session = Depends(get_session),
):
    context = _context(session)
    with storage_errors():
        return _manager(request).preview(
            session,
            profile_id=context.profile.id,
            context=context,
            mode=data.mode,
            record_id=data.record_id,
            domain=data.domain,
            record_ids=data.record_ids,
            term_id=data.term_id,
        )


@listening_exports_router.post("/generate", response_model=dict[str, Any])
def generate_listening_export(
    data: ListeningExportGenerateIn,
    request: Request,
):
    with storage_errors():
        return _manager(request).generate(
            preview_id=data.preview_id,
            request_id=data.request_id,
            filename=data.filename,
            ack_missing=data.ack_missing,
        )


@listening_exports_router.get(
    "/operations/{request_id}", response_model=dict[str, Any]
)
def read_listening_export_operation(
    request_id: str,
    request: Request,
):
    with storage_errors():
        return _manager(request).request_receipt(request_id)


@listening_exports_router.get("/{export_id}/meta", response_model=dict[str, Any])
def read_listening_export_meta(
    export_id: str,
    request: Request,
):
    with storage_errors():
        return _manager(request).meta(export_id)


@listening_exports_router.get("/{export_id}/content")
def read_listening_export_content(
    export_id: str,
    request: Request,
):
    with storage_errors():
        payload = _manager(request).content(export_id)
        meta = _manager(request).meta(export_id)

    def _iter_bounded():
        view = memoryview(payload)
        for offset in range(0, len(view), 256 * 1024):
            yield view[offset : offset + 256 * 1024]

    return StreamingResponse(
        _iter_bounded(),
        media_type=(
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
        headers={
            "Cache-Control": "no-store",
            "Content-Length": str(len(payload)),
            "X-Content-SHA256": meta["sha256"],
            "Content-Disposition": "attachment",
        },
    )


@listening_exports_router.post("/{export_id}/pin", response_model=dict[str, Any])
def pin_listening_export(
    export_id: str,
    data: ListeningExportPinIn,
    request: Request,
):
    with storage_errors():
        return _manager(request).pin_export(export_id, data.owner)


@listening_exports_router.post("/{export_id}/unpin", response_model=dict[str, Any])
def unpin_listening_export(
    export_id: str,
    data: ListeningExportPinIn,
    request: Request,
):
    with storage_errors():
        _manager(request).unpin_export(export_id, data.owner)
        return {"status": "ok"}


__all__ = ["listening_exports_router"]
