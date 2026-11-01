"""Protected local HTTP routes for weekly-plan Word export (G2a D)."""

from __future__ import annotations

from datetime import date, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from app.local import weekly_plan_export_service as service
from app.local.api import _launch_id, _session_scope, get_session
from app.local.errors import LocalWeeklyExportUnavailable
from app.local.observation_api import _profile_id
from app.local.tx import storage_errors

weekly_exports_router = APIRouter(
    prefix="/api/weekly-exports", tags=["weekly-exports"]
)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _manager(request: Request):
    manager = getattr(request.app.state, "weekly_export_manager", None)
    if manager is None:
        raise LocalWeeklyExportUnavailable()
    return manager


def _expires_header(value):
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _optional_manager(request: Request):
    return getattr(request.app.state, "weekly_export_manager", None)


def _date_before(value: Any, label: str) -> date | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) != 10:
        raise ValueError(f"{label} 必须是规范 ISO 日期")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{label} 必须是规范 ISO 日期") from None
    if parsed.isoformat() != value:
        raise ValueError(f"{label} 必须是规范 ISO 日期")
    return parsed
class PreviewIn(_Strict):
    mode: Literal["single", "range"]
    weekly_plan_id: str | None = None
    confirmation_id: str | None = None
    start_date: date | None = None
    end_date: date | None = None

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def _date(cls, value: Any, info):
        return _date_before(value, info.field_name)

    @model_validator(mode="after")
    def _shape(self):
        if self.mode == "single":
            if not self.weekly_plan_id or len(self.weekly_plan_id) > 32:
                raise ValueError("单份导出必须提供 weekly_plan_id")
            if self.confirmation_id is not None and len(self.confirmation_id) > 32:
                raise ValueError("confirmation_id 不合法")
            if self.start_date is not None or self.end_date is not None:
                raise ValueError("单份导出不接受范围日期")
        else:
            if self.weekly_plan_id is not None or self.confirmation_id is not None:
                raise ValueError("范围导出不接受 plan/confirmation")
            if self.start_date is None or self.end_date is None:
                raise ValueError("范围导出必须提供起止日期")
            if self.start_date > self.end_date:
                raise ValueError("范围导出日期顺序不合法")
        return self
class CreateIn(_Strict):
    request_id: str
    context_token: str
    ack_missing: bool

    @field_validator("request_id", "context_token")
    @classmethod
    def _nonempty(cls, value: str, info):
        if not isinstance(value, str) or not value:
            raise ValueError(f"{info.field_name} 不能为空")
        return value


class RetryIn(_Strict):
    request_id: str
    old_export_id: str
    attempt_id: str

    @field_validator("request_id", "old_export_id", "attempt_id")
    @classmethod
    def _nonempty(cls, value: str, info):
        if not isinstance(value, str) or not value:
            raise ValueError(f"{info.field_name} 不能为空")
        return value


class AttemptStartIn(_Strict):
    filename: str


class AttemptResultIn(_Strict):
    attempt_id: str
    filename: str
    status: Literal["saved", "cancelled", "failed", "indeterminate"]
    byte_size: int = Field(ge=0)
    result_hash: str | None

    @field_validator("byte_size", mode="before")
    @classmethod
    def _byte_size(cls, value: Any):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("byte_size 必须是非负整数")
        return value
@weekly_exports_router.post("/preview", response_model=dict[str, Any])
def preview_weekly_export(
    data: PreviewIn,
    request: Request,
    session: Session = Depends(get_session),
):
    with storage_errors():
        return service.preview_export(
            session,
            _manager(request),
            profile_id=_profile_id(session),
            mode=data.mode,
            weekly_plan_id=data.weekly_plan_id,
            confirmation_id=data.confirmation_id,
            start_date=data.start_date,
            end_date=data.end_date,
        )


@weekly_exports_router.post("", response_model=dict[str, Any])
def create_weekly_export(
    response: Response,
    data: CreateIn,
    request: Request,
    session: Session = Depends(get_session),
):
    with storage_errors():
        result, created = service.create_export(
            session,
            _optional_manager(request),
            profile_id=_profile_id(session),
            request_id=data.request_id,
            context_token=data.context_token,
            ack_missing=data.ack_missing,
            launch_id=_launch_id(request),
            session_scope=_session_scope(request),
        )
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return result
@weekly_exports_router.post(
    "/snapshots/{snapshot_id}/retry", response_model=dict[str, Any]
)
def retry_weekly_export(
    snapshot_id: str,
    response: Response,
    data: RetryIn,
    request: Request,
    session: Session = Depends(get_session),
):
    with storage_errors():
        result, created = service.retry_export(
            session,
            _optional_manager(request),
            profile_id=_profile_id(session),
            snapshot_id=snapshot_id,
            request_id=data.request_id,
            old_export_id=data.old_export_id,
            attempt_id=data.attempt_id,
            launch_id=_launch_id(request),
            session_scope=_session_scope(request),
        )
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return result


@weekly_exports_router.get(
    "/operations/{request_id}", response_model=dict[str, Any]
)
def read_weekly_export_operation(
    request_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    with storage_errors():
        return service.read_operation(
            session,
            getattr(request.app.state, "weekly_export_manager", None),
            profile_id=_profile_id(session),
            request_id=request_id,
        )
@weekly_exports_router.post(
    "/{export_id}/attempts", response_model=dict[str, Any]
)
def start_weekly_export_attempt(
    export_id: str,
    data: AttemptStartIn,
    request: Request,
    session: Session = Depends(get_session),
):
    with storage_errors():
        return service.start_attempt(
            session,
            _manager(request),
            profile_id=_profile_id(session),
            export_id=export_id,
            filename=data.filename,
            launch_id=_launch_id(request),
            session_scope=_session_scope(request),
        )


@weekly_exports_router.get(
    "/{export_id}/attempts/latest", response_model=dict[str, Any]
)
def read_latest_weekly_export_attempt(
    export_id: str,
    filename: str = Query(...),
    session: Session = Depends(get_session),
):
    with storage_errors():
        return service.read_latest_attempt(
            session,
            profile_id=_profile_id(session),
            export_id=export_id,
            filename=filename,
        )


@weekly_exports_router.post(
    "/{export_id}/attempts/result", response_model=dict[str, Any]
)
def finish_weekly_export_attempt(
    export_id: str,
    data: AttemptResultIn,
    request: Request,
    session: Session = Depends(get_session),
):
    with storage_errors():
        return service.finish_attempt(
            session,
            _manager(request),
            profile_id=_profile_id(session),
            export_id=export_id,
            attempt_id=data.attempt_id,
            filename=data.filename,
            status=data.status,
            byte_size=data.byte_size,
            result_hash=data.result_hash,
            launch_id=_launch_id(request),
            session_scope=_session_scope(request),
        )
def _read_artifact_chunk(artifact: service.ExportArtifact, manager, launch_id: str, session_scope: str):
    with manager.activity(
        kind="download", launch_id=launch_id, session_scope=session_scope
    ):
        return artifact.handle.read(256 * 1024)


def _iter_artifact(artifact: service.ExportArtifact, manager, launch_id: str, session_scope: str):
    try:
        while artifact.handle is not None:
            chunk = _read_artifact_chunk(
                artifact, manager, launch_id, session_scope
            )
            if not chunk:
                break
            yield chunk
        artifact.complete()
    finally:
        artifact.close()


class _ArtifactStreamingResponse(StreamingResponse):
    def __init__(self, *args, artifact, **kwargs):
        self._artifact = artifact
        super().__init__(*args, **kwargs)

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            self._artifact.close()


@weekly_exports_router.get("/{export_id}/content")
def read_weekly_export_content(
    export_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    launch = _launch_id(request)
    scope = _session_scope(request)
    manager = _manager(request)
    with storage_errors():
        artifact = service.read_export_content(
            session,
            manager,
            profile_id=_profile_id(session),
            export_id=export_id,
            launch_id=launch,
            session_scope=scope,
        )
    return _ArtifactStreamingResponse(
        _iter_artifact(artifact, manager, launch, scope),
        artifact=artifact,
        media_type=(
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
        headers={
            "Cache-Control": "no-store",
            "Content-Length": str(artifact.size),
            "X-Content-SHA256": artifact.digest,
            "X-Export-Expires-At": _expires_header(artifact.expires_at),
            "Content-Disposition": "attachment",
        },
        background=BackgroundTask(artifact.close),
    )