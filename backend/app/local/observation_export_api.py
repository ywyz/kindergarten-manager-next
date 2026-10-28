"""Protected local HTTP routes for observation Word export.

The preview/create/attempt protocol is separate from the daily-plan export
router: observation export ids are bearer tokens bound to the profile,
launch, app session scope, frozen snapshot and expiry, and the host reports
its own file IO result back through these routes.  The host never reads the
SQLite database and never receives an arbitrary path or URL.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.local import observation_export_service
from app.local.api import _launch_id, _session_scope, get_session
from app.local.observation_api import _profile_id
from app.local.schemas import (
    LocalObservationExportAttemptResultIn,
    LocalObservationExportAttemptStartIn,
    LocalObservationExportCreateIn,
    LocalObservationExportPreviewIn,
)
from app.local.tx import storage_errors

observation_exports_router = APIRouter(
    prefix="/api/observation-exports", tags=["observation-exports"]
)


@observation_exports_router.post(
    "/prepare", response_model=dict[str, Any]
)
def prepare_observation_export(
    data: LocalObservationExportPreviewIn,
    request: Request,
    session: Session = Depends(get_session),
):
    with storage_errors():
        profile_id = _profile_id(session)
        return observation_export_service.prepare_export(
            session,
            profile_id=profile_id,
            request_id=data.request_id,
            observation_ids=data.observation_ids,
            launch_id=_launch_id(request),
            session_scope=_session_scope(request),
        )


@observation_exports_router.post(
    "/preview", response_model=dict[str, Any]
)
def preview_observation_export(
    data: LocalObservationExportPreviewIn,
    request: Request,
    session: Session = Depends(get_session),
):
    with storage_errors():
        profile_id = _profile_id(session)
        return observation_export_service.preview_export(
            session,
            request.app.state.runtime,
            profile_id=profile_id,
            request_id=data.request_id,
            observation_ids=data.observation_ids,
            launch_id=_launch_id(request),
            session_scope=_session_scope(request),
        )


@observation_exports_router.post(
    "", status_code=status.HTTP_201_CREATED, response_model=dict[str, Any]
)
def create_observation_export(
    data: LocalObservationExportCreateIn,
    request: Request,
    session: Session = Depends(get_session),
):
    with storage_errors():
        profile_id = _profile_id(session)
        return observation_export_service.create_export(
            session,
            request.app.state.runtime,
            profile_id=profile_id,
            request_id=data.request_id,
            snapshot_id=data.snapshot_id,
            ack_missing=data.ack_missing,
            retry_existing=data.retry_existing,
            launch_id=_launch_id(request),
            session_scope=_session_scope(request),
        )


@observation_exports_router.get(
    "/operations/{request_id}", response_model=dict[str, Any]
)
def read_observation_export_operation(
    request_id: str,
    session: Session = Depends(get_session),
):
    with storage_errors():
        profile_id = _profile_id(session)
        return observation_export_service.read_operation_receipt(
            session, profile_id=profile_id, request_id=request_id
        )


def _iter_artifact(artifact, runtime):
    try:
        while True:
            chunk = artifact.handle.read(256 * 1024)
            if not chunk:
                break
            yield chunk
    finally:
        observation_export_service.release_artifact(runtime, artifact)


@observation_exports_router.get("/{export_id}/content")
def read_observation_export_content(
    export_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    with storage_errors():
        profile_id = _profile_id(session)
        artifact = observation_export_service.read_export_content(
            session,
            request.app.state.runtime,
            profile_id=profile_id,
            export_id=export_id,
            launch_id=_launch_id(request),
            session_scope=_session_scope(request),
        )
    return StreamingResponse(
        _iter_artifact(artifact, request.app.state.runtime),
        media_type=(
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
        headers={
            "Cache-Control": "no-store",
            "Content-Length": str(artifact.size),
            "X-Content-SHA256": artifact.digest,
            "Content-Disposition": "attachment",
        },
        background=BackgroundTask(
            observation_export_service.release_artifact,
            request.app.state.runtime,
            artifact,
        ),
    )


@observation_exports_router.post(
    "/{export_id}/attempts", response_model=dict[str, Any]
)
def start_observation_export_attempt(
    export_id: str,
    data: LocalObservationExportAttemptStartIn,
    request: Request,
    session: Session = Depends(get_session),
):
    with storage_errors():
        profile_id = _profile_id(session)
        return observation_export_service.start_attempt(
            session,
            request.app.state.runtime,
            profile_id=profile_id,
            export_id=export_id,
            filename=data.filename,
            launch_id=_launch_id(request),
            session_scope=_session_scope(request),
        )


@observation_exports_router.get(
    "/{export_id}/attempts/latest", response_model=dict[str, Any]
)
def read_latest_observation_export_attempt(
    export_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    with storage_errors():
        profile_id = _profile_id(session)
        return observation_export_service.read_latest_attempt(
            session,
            profile_id=profile_id,
            export_id=export_id,
            launch_id=_launch_id(request),
            session_scope=_session_scope(request),
        )


@observation_exports_router.get(
    "/{export_id}/attempts/{attempt_id}", response_model=dict[str, Any]
)
def read_observation_export_attempt(
    export_id: str,
    attempt_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    with storage_errors():
        profile_id = _profile_id(session)
        return observation_export_service.read_attempt(
            session,
            profile_id=profile_id,
            export_id=export_id,
            attempt_id=attempt_id,
            launch_id=_launch_id(request),
            session_scope=_session_scope(request),
        )


@observation_exports_router.post(
    "/{export_id}/attempts/{attempt_id}/result",
    response_model=dict[str, Any],
)
def finish_observation_export_attempt(
    export_id: str,
    attempt_id: str,
    data: LocalObservationExportAttemptResultIn,
    request: Request,
    session: Session = Depends(get_session),
):
    with storage_errors():
        profile_id = _profile_id(session)
        return observation_export_service.finish_attempt(
            session,
            request.app.state.runtime,
            profile_id=profile_id,
            export_id=export_id,
            attempt_id=attempt_id,
            status=data.status,
            byte_size=data.byte_size,
            result_hash=data.result_hash,
            launch_id=_launch_id(request),
            session_scope=_session_scope(request),
        )
