"""Administrator prompt-release routes and immutable package delivery."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, StrictStr
from sqlalchemy.orm import Session

from .admin_api import get_admin_csrf_principal, get_admin_principal
from .admin_service import AdminPrincipal
from .api import get_session
from .prompt_release_service import (
    MANIFEST_NAME,
    PromptReleaseConfig,
    create_draft,
    get_workspace,
    latest_manifest_bytes,
    package_root_from_env,
    parse_package_filename,
    publish_preview,
    publish_rollback,
    publish_stable,
    resolve_package_path,
)

Channels = Literal["preview", "stable"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EditableOut(_StrictModel):
    task_type: str
    fields: dict[str, str]


class DraftOut(_StrictModel):
    draft_id: UUID
    notes: str
    base_stable_sequence: int | None
    changes: dict[str, dict[str, str]]


class ReleaseOut(_StrictModel):
    release_sequence: int
    channel: Channels
    draft_id: UUID | None
    notes: str | None
    rollback_of: int | None


class LatestOut(_StrictModel):
    preview: int | None
    stable: int | None


class WorkspaceOut(_StrictModel):
    editable: list[EditableOut]
    drafts: list[DraftOut]
    releases: list[ReleaseOut]
    latest: LatestOut


class DraftIn(_StrictModel):
    changes: dict[StrictStr, dict[StrictStr, StrictStr]]
    notes: StrictStr = Field(..., max_length=500)


class PreviewIn(_StrictModel):
    draft_id: UUID


class StableIn(_StrictModel):
    preview_sequence: int = Field(..., ge=1, strict=True)


class RollbackIn(_StrictModel):
    target_sequence: int = Field(..., ge=1, strict=True)
    expected_stable_sequence: int = Field(..., ge=1, strict=True)


admin_router = APIRouter(
    prefix="/api/collaboration/admin/prompt-releases",
    tags=["collaboration-prompt-releases"],
)
package_router = APIRouter(tags=["collaboration-prompt-packages"])


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"


def _require_configured() -> PromptReleaseConfig:
    return PromptReleaseConfig.from_env()


@admin_router.get("", response_model=WorkspaceOut)
def read_prompt_releases(
    response: Response,
    session: Session = Depends(get_session),
    _principal: AdminPrincipal = Depends(get_admin_principal),
) -> WorkspaceOut:
    _require_configured()
    result = get_workspace(session)
    _no_store(response)
    return WorkspaceOut.model_validate(result)


@admin_router.post("/drafts", response_model=DraftOut)
def create_prompt_draft(
    data: DraftIn,
    response: Response,
    session: Session = Depends(get_session),
    _principal: AdminPrincipal = Depends(get_admin_csrf_principal),
) -> DraftOut:
    _require_configured()
    result = create_draft(
        session,
        changes=data.changes,
        notes=data.notes,
    )
    _no_store(response)
    return DraftOut.model_validate(result)


@admin_router.post("/preview", response_model=ReleaseOut)
def publish_prompt_preview(
    data: PreviewIn,
    response: Response,
    session: Session = Depends(get_session),
    _principal: AdminPrincipal = Depends(get_admin_csrf_principal),
) -> ReleaseOut:
    config = _require_configured()
    result = publish_preview(
        session,
        config,
        draft_id=data.draft_id,
    )
    _no_store(response)
    return ReleaseOut.model_validate(result)


@admin_router.post("/stable", response_model=ReleaseOut)
def publish_prompt_stable(
    data: StableIn,
    response: Response,
    session: Session = Depends(get_session),
    _principal: AdminPrincipal = Depends(get_admin_csrf_principal),
) -> ReleaseOut:
    config = _require_configured()
    result = publish_stable(
        session,
        config,
        preview_sequence=data.preview_sequence,
    )
    _no_store(response)
    return ReleaseOut.model_validate(result)


@admin_router.post("/rollback", response_model=ReleaseOut)
def publish_prompt_rollback(
    data: RollbackIn,
    response: Response,
    session: Session = Depends(get_session),
    _principal: AdminPrincipal = Depends(get_admin_csrf_principal),
) -> ReleaseOut:
    config = _require_configured()
    result = publish_rollback(
        session,
        config,
        target_sequence=data.target_sequence,
        expected_stable_sequence=data.expected_stable_sequence,
    )
    _no_store(response)
    return ReleaseOut.model_validate(result)


@package_router.get("/prompt-packages/{channel}/{filename}")
def read_prompt_package(
    channel: str,
    filename: str,
    session: Session = Depends(get_session),
):
    if filename == MANIFEST_NAME:
        body = latest_manifest_bytes(session, channel)
        return Response(
            content=body,
            media_type="application/json",
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )
    sequence, package_sha256 = parse_package_filename(filename)
    root = package_root_from_env()
    path = resolve_package_path(
        session, root, channel, sequence, package_sha256
    )
    return FileResponse(
        path,
        media_type="application/json",
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )
