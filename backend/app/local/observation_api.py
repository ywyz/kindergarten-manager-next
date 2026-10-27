"""Protected local HTTP routes for game observation pages (E09/E10).

All identity is server-derived from the single local profile; clients never
send ownership or paths. The routes adapt the already-reviewed observation
services (create/list/save, materials, history/restore, AI tasks/candidates)
without introducing a second business state machine. DOCX export, export ids
and native save remain outside this slice.

Image import uses the documented ``multipart/form-data`` protocol. The
runtime dependency set deliberately does not include ``python-multipart``, so
one strictly bounded single-file envelope is parsed here (opaque metadata
fields plus exactly one binary part); arbitrary form uploads are refused.
"""

from __future__ import annotations

import io
import re
from datetime import date
from email import policy
from email.parser import BytesParser
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.local import (
    ai_task_service,
    observation_ai_service,
    observation_assets,
    observation_history_service,
    observation_service,
    profile_service,
)
from app.local.api import _task_progress, get_session
from app.local.errors import (
    LocalAiContractObsolete,
    LocalAiExecutorUnavailable,
    LocalAiNotFound,
    LocalAiPreviewExpired,
    LocalAiSourceChanged,
    LocalAiTargetChanged,
    LocalError,
    LocalValidationError,
)
from app.local.observation_assets import (
    ObservationMaterialInvalid,
    ObservationMaterialLimit,
)
from app.local.schemas import (
    LocalObservationAIAdoptionIn,
    LocalObservationAIAdoptionPreviewIn,
    LocalObservationAITaskCreateIn,
    LocalObservationCreateIn,
    LocalObservationCurrentOut,
    LocalObservationListOut,
    LocalObservationPhotoCaptionIn,
    LocalObservationPhotoOut,
    LocalObservationPhotoRemoveIn,
    LocalObservationPhotoReorderIn,
    LocalObservationRestoreIn,
    LocalObservationRestorePreviewIn,
    LocalObservationSaveIn,
    LocalObservationSaveOut,
)
from app.local.tx import read_scope, storage_errors

observations_router = APIRouter(prefix="/api/observations", tags=["observations"])


class ObservationAiSourceChanged(LocalError):
    code = "OBS_AI_SOURCE_CHANGED"
    status_code = 409
    message = "观察输入已变化，候选仅可查看；请重新生成或核对差异"


class ObservationAiContractIncompatible(LocalError):
    code = "OBS_AI_CONTRACT_INCOMPATIBLE"
    status_code = 409
    message = "该候选的契约版本已过时，只能查看"


class ObservationAiCandidateStale(LocalError):
    code = "OBS_AI_CANDIDATE_STALE"
    status_code = 409
    message = "候选预览或目标已失效，请重新预览"


def _map_ai_error(exc: LocalError) -> LocalError:
    if isinstance(exc, LocalAiSourceChanged):
        return ObservationAiSourceChanged(details=exc.details)
    if isinstance(exc, LocalAiContractObsolete):
        return ObservationAiContractIncompatible(details=exc.details)
    if isinstance(exc, (LocalAiPreviewExpired, LocalAiTargetChanged)):
        return ObservationAiCandidateStale(details=exc.details)
    return exc

_BOUNDARY_RE = re.compile(r'boundary="?([^";]+)"?', re.IGNORECASE)
_MAX_UPLOAD_BODY = observation_assets.MAX_SOURCE_BYTES + 256 * 1024
_MIME_BY_FORMAT = {
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
    "bmp": "image/bmp",
}


def _profile_id(session: Session) -> str:
    with read_scope(session):
        context = profile_service.require_context(session, date.today())
    if context.profile is None:  # pragma: no cover - require_context guarantees it
        raise LocalValidationError("本地档案尚未初始化")
    return context.profile.id


def _require_executor(request: Request):
    executor = getattr(request.app.state, "executor", None)
    if executor is None or not getattr(executor, "is_runnable", lambda: False)():
        raise LocalAiExecutorUnavailable()
    return executor


def _int_field(value: str | None, field: str) -> int:
    if value is None or not value.isdigit():
        raise ObservationMaterialInvalid(f"{field} 必须是正整数")
    number = int(value)
    if number < 1:
        raise ObservationMaterialInvalid(f"{field} 必须是正整数")
    return number


async def _read_multipart(request: Request) -> tuple[dict[str, str], bytes]:
    """Strict bounded single-file multipart parser (no extra dependency).

    The final ``--boundary--`` is required, every delimiter must start a line,
    trailing bytes are refused, and exactly one binary file part is accepted.
    """
    content_type = request.headers.get("content-type", "")
    if not content_type.lower().startswith("multipart/form-data"):
        raise ObservationMaterialInvalid("图片导入必须使用 multipart/form-data")
    match = _BOUNDARY_RE.search(content_type)
    if match is None:
        raise ObservationMaterialInvalid("multipart 缺少 boundary")
    try:
        boundary = match.group(1).encode("latin-1")
    except UnicodeEncodeError:
        raise ObservationMaterialInvalid("multipart boundary 不合法") from None
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > _MAX_UPLOAD_BODY:
            raise ObservationMaterialLimit("图片导入内容超过上限")
    return _parse_multipart_body(bytes(body), boundary)


def _parse_multipart_body(body: bytes, boundary: bytes) -> tuple[dict[str, str], bytes]:
    marker = b"--" + boundary
    pos = 0
    if body.startswith(b"\r\n"):
        pos = 2
    if not body.startswith(marker, pos):
        raise ObservationMaterialInvalid("multipart 起始边界不合法")
    pos += len(marker)
    fields: dict[str, str] = {}
    file_bytes: bytes | None = None
    parts = 0
    while True:
        if body.startswith(b"--", pos):
            pos += 2
            if body[pos : pos + 2] == b"\r\n":
                pos += 2
            if pos != len(body):
                raise ObservationMaterialInvalid("multipart 终止边界后存在多余内容")
            break
        if body[pos : pos + 2] != b"\r\n":
            raise ObservationMaterialInvalid("multipart 分段边界不合法")
        pos += 2
        header_end = body.find(b"\r\n\r\n", pos)
        if header_end < 0:
            raise ObservationMaterialInvalid("multipart 分段缺少头部终止")
        header_blob = body[pos:header_end]
        payload_start = header_end + 4
        next_marker = body.find(b"\r\n" + marker, payload_start)
        if next_marker < 0:
            raise ObservationMaterialInvalid("multipart 缺少终止边界")
        payload = body[payload_start:next_marker]
        pos = next_marker + 2 + len(marker)
        parts += 1
        if parts > 16:
            raise ObservationMaterialInvalid("multipart 分段过多")
        headers = BytesParser(policy=policy.compat32).parsebytes(
            header_blob + b"\r\n\r\n"
        )
        disposition = str(headers.get("content-disposition") or "")
        if not disposition.lower().startswith("form-data"):
            raise ObservationMaterialInvalid("multipart 分段缺少表单声明")
        name = headers.get_param("name", header="content-disposition")
        if not name:
            continue
        filename = headers.get_filename()
        if filename is not None:
            if name != "file" or file_bytes is not None:
                raise ObservationMaterialInvalid("图片导入只接受一个文件字段")
            transfer = str(headers.get("content-transfer-encoding") or "").lower()
            if transfer not in ("", "binary", "8bit"):
                raise ObservationMaterialInvalid("图片文件编码不合法")
            file_bytes = payload
            continue
        if name in fields:
            raise ObservationMaterialInvalid("multipart 字段重复")
        charset = headers.get_content_charset() or "utf-8"
        try:
            value = payload.decode(charset)
        except (LookupError, UnicodeDecodeError):
            raise ObservationMaterialInvalid("multipart 文本字段编码不合法") from None
        if len(value) > 4096:
            raise ObservationMaterialInvalid("multipart 文本字段过长")
        fields[name] = value
    if file_bytes is None:
        raise ObservationMaterialInvalid("缺少图片文件")
    return fields, file_bytes


# ---------------------------------------------------------------------------
# Create / list / current / save / receipts
# ---------------------------------------------------------------------------


@observations_router.post(
    "", status_code=status.HTTP_201_CREATED, response_model=dict[str, Any]
)
def create_observation(
    data: LocalObservationCreateIn,
    session: Session = Depends(get_session),
):
    with storage_errors():
        profile_id = _profile_id(session)
        kwargs: dict[str, Any] = {}
        if "observation_date" in data.model_fields_set:
            kwargs["observation_date"] = data.observation_date
        if "term_id" in data.model_fields_set:
            kwargs["term_id"] = data.term_id
        return observation_service.create_observation(
            session,
            profile_id=profile_id,
            request_id=data.request_id,
            record_type=data.record_type,
            payload=data.payload,
            **kwargs,
        )


@observations_router.get("", response_model=LocalObservationListOut)
def list_observations(
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    term_id: str | None = None,
    unassigned: bool = False,
    record_type: str | None = None,
    subject: str | None = None,
    offset: int = Query(0),
    limit: int = Query(observation_service.DEFAULT_LIST_LIMIT),
    session: Session = Depends(get_session),
):
    with storage_errors():
        profile_id = _profile_id(session)
        return observation_service.list_observations(
            session,
            profile_id=profile_id,
            from_date=from_date,
            to_date=to_date,
            term_id=term_id,
            unassigned=unassigned,
            record_type=record_type,
            subject=subject,
            offset=offset,
            limit=limit,
        )


@observations_router.get(
    "/operations/{request_id}", response_model=dict[str, Any]
)
def read_observation_create_operation(
    request_id: str,
    session: Session = Depends(get_session),
):
    """Read a create receipt without knowing the new observation id."""
    with storage_errors():
        profile_id = _profile_id(session)
        return observation_service.read_operation_receipt(
            session, profile_id=profile_id, request_id=request_id
        )


@observations_router.get(
    "/{observation_id}", response_model=LocalObservationCurrentOut
)
def read_observation(
    observation_id: str,
    session: Session = Depends(get_session),
):
    with storage_errors():
        profile_id = _profile_id(session)
        return observation_service.read_current(
            session, profile_id=profile_id, observation_id=observation_id
        )


@observations_router.patch(
    "/{observation_id}", response_model=LocalObservationSaveOut
)
def save_observation(
    observation_id: str,
    data: LocalObservationSaveIn,
    session: Session = Depends(get_session),
):
    with storage_errors():
        profile_id = _profile_id(session)
        return observation_service.save_observation(
            session,
            profile_id=profile_id,
            observation_id=observation_id,
            request_id=data.request_id,
            expected_revision=data.expected_revision,
            payload=data.payload,
            photos=data.photos,
            save_reason=data.save_reason,
            term_decision=data.term_decision,
            selected_term_id=data.selected_term_id,
        )


@observations_router.get(
    "/{observation_id}/operations/{request_id}", response_model=dict[str, Any]
)
def read_observation_operation(
    observation_id: str,
    request_id: str,
    session: Session = Depends(get_session),
):
    with storage_errors():
        profile_id = _profile_id(session)
        receipt = observation_service.read_operation_receipt(
            session, profile_id=profile_id, request_id=request_id
        )
        result = receipt.get("result") or {}
        if result.get("observation_id") not in (None, observation_id):
            raise observation_service.ObservationOperationNotFound()
        return receipt


# ---------------------------------------------------------------------------
# Photos: ordered list, multipart import, captions, order, remove, binary
# ---------------------------------------------------------------------------


@observations_router.get(
    "/{observation_id}/photos", response_model=list[LocalObservationPhotoOut]
)
def list_observation_photos(
    observation_id: str,
    session: Session = Depends(get_session),
):
    with storage_errors():
        profile_id = _profile_id(session)
        return observation_assets.list_photos(
            session, profile_id=profile_id, observation_id=observation_id
        )


@observations_router.post(
    "/{observation_id}/photos",
    status_code=status.HTTP_201_CREATED,
    response_model=dict[str, Any],
)
async def import_observation_photo(
    observation_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    profile_id = _profile_id(session)
    fields, content = await _read_multipart(request)
    request_id = fields.get("request_id")
    if not request_id:
        raise ObservationMaterialInvalid("缺少 request_id")
    expected_revision = _int_field(
        fields.get("expected_revision"), "expected_revision"
    )
    caption = fields.get("caption")
    display_name = fields.get("display_name") or "photo"
    runtime = request.app.state.runtime
    return await run_in_threadpool(
        _import_photo_sync,
        session,
        runtime,
        profile_id,
        observation_id,
        request_id,
        expected_revision,
        content,
        display_name,
        caption,
    )


def _import_photo_sync(
    session: Session,
    runtime,
    profile_id: str,
    observation_id: str,
    request_id: str,
    expected_revision: int,
    content: bytes,
    display_name: str,
    caption: str | None,
):
    with storage_errors():
        return observation_assets.import_asset(
            session,
            runtime,
            profile_id=profile_id,
            observation_id=observation_id,
            request_id=request_id,
            expected_revision=expected_revision,
            stream=io.BytesIO(content),
            display_name=display_name,
            caption=caption,
        )


@observations_router.patch(
    "/{observation_id}/photos/{asset_id}", response_model=dict[str, Any]
)
def update_observation_photo(
    observation_id: str,
    asset_id: str,
    data: LocalObservationPhotoCaptionIn,
    session: Session = Depends(get_session),
):
    with storage_errors():
        profile_id = _profile_id(session)
        return observation_assets.set_caption(
            session,
            profile_id=profile_id,
            observation_id=observation_id,
            request_id=data.request_id,
            expected_revision=data.expected_revision,
            asset_id=asset_id,
            caption=data.caption,
        )


@observations_router.post(
    "/{observation_id}/photos/order", response_model=dict[str, Any]
)
def reorder_observation_photos(
    observation_id: str,
    data: LocalObservationPhotoReorderIn,
    session: Session = Depends(get_session),
):
    with storage_errors():
        profile_id = _profile_id(session)
        return observation_assets.reorder_photos(
            session,
            profile_id=profile_id,
            observation_id=observation_id,
            request_id=data.request_id,
            expected_revision=data.expected_revision,
            asset_ids=data.asset_ids,
        )


@observations_router.delete(
    "/{observation_id}/photos/{asset_id}", response_model=dict[str, Any]
)
def remove_observation_photo(
    observation_id: str,
    asset_id: str,
    data: LocalObservationPhotoRemoveIn,
    session: Session = Depends(get_session),
):
    with storage_errors():
        profile_id = _profile_id(session)
        return observation_assets.remove_photo(
            session,
            profile_id=profile_id,
            observation_id=observation_id,
            request_id=data.request_id,
            expected_revision=data.expected_revision,
            asset_id=asset_id,
        )


@observations_router.get("/{observation_id}/photos/{asset_id}/content")
def read_observation_photo(
    observation_id: str,
    asset_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    with storage_errors():
        profile_id = _profile_id(session)
        manifest = observation_assets.list_photos(
            session, profile_id=profile_id, observation_id=observation_id
        )
        entry = next(
            (item for item in manifest if item.get("asset_id") == asset_id), None
        )
        if entry is None:
            raise observation_assets.ObservationAssetNotFound()
        data = observation_assets.read_asset_bytes(
            session,
            request.app.state.runtime,
            profile_id=profile_id,
            observation_id=observation_id,
            asset_id=asset_id,
        )
    media_type = _MIME_BY_FORMAT.get(str(entry.get("format")), "application/octet-stream")
    return Response(
        content=data,
        media_type=media_type,
        headers={
            "Cache-Control": "no-store",
            "Content-Length": str(len(data)),
        },
    )


@observations_router.get(
    "/{observation_id}/photos/{asset_id}/derivatives/{purpose}/content"
)
def read_observation_photo_derivative(
    observation_id: str,
    asset_id: str,
    purpose: str,
    request: Request,
    session: Session = Depends(get_session),
):
    if purpose != "ai":
        raise ObservationMaterialInvalid("只允许读取 AI 工作图用于受控显示")
    with storage_errors():
        profile_id = _profile_id(session)
        data = observation_assets.read_derivative_bytes(
            session,
            request.app.state.runtime,
            profile_id=profile_id,
            observation_id=observation_id,
            asset_id=asset_id,
            purpose="ai",
            params_version=observation_assets.AI_PARAMS_VERSION,
            max_bytes=observation_assets.MAX_SOURCE_BYTES,
        )
    return Response(
        content=data,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "no-store",
            "Content-Length": str(len(data)),
        },
    )


# ---------------------------------------------------------------------------
# History and whole-record restore
# ---------------------------------------------------------------------------


@observations_router.get(
    "/{observation_id}/history", response_model=list[dict[str, Any]]
)
def list_observation_history(
    observation_id: str,
    session: Session = Depends(get_session),
):
    with storage_errors():
        profile_id = _profile_id(session)
        return observation_history_service.list_history(
            session, profile_id=profile_id, observation_id=observation_id
        )


@observations_router.get(
    "/{observation_id}/history/restore-operations/{request_id}",
    response_model=dict[str, Any],
)
def read_observation_restore_operation(
    observation_id: str,
    request_id: str,
    session: Session = Depends(get_session),
):
    with storage_errors():
        profile_id = _profile_id(session)
        receipt = observation_service.read_operation_receipt(
            session, profile_id=profile_id, request_id=request_id
        )
        result = receipt.get("result") or {}
        if result.get("observation_id") not in (None, observation_id):
            raise observation_service.ObservationOperationNotFound()
        return receipt


@observations_router.get(
    "/{observation_id}/history/{version}", response_model=dict[str, Any]
)
def read_observation_history_version(
    observation_id: str,
    version: int,
    session: Session = Depends(get_session),
):
    with storage_errors():
        profile_id = _profile_id(session)
        return observation_history_service.read_history_version(
            session,
            profile_id=profile_id,
            observation_id=observation_id,
            version=version,
        )


@observations_router.post(
    "/{observation_id}/history/preview-restore", response_model=dict[str, Any]
)
def preview_observation_restore(
    observation_id: str,
    data: LocalObservationRestorePreviewIn,
    request: Request,
    session: Session = Depends(get_session),
):
    with storage_errors():
        profile_id = _profile_id(session)
        return observation_history_service.preview_restore(
            session,
            request.app.state.runtime,
            profile_id=profile_id,
            observation_id=observation_id,
            source_version=data.source_version,
            request_id=data.request_id,
            base_draft_revision=data.base_draft_revision,
            base_draft_hash=data.base_draft_hash,
            term_decision=data.term_decision,
            selected_term_id=data.selected_term_id,
        )


@observations_router.post(
    "/{observation_id}/history/restore", response_model=dict[str, Any]
)
def restore_observation(
    observation_id: str,
    data: LocalObservationRestoreIn,
    request: Request,
    session: Session = Depends(get_session),
):
    with storage_errors():
        profile_id = _profile_id(session)
        return observation_history_service.restore_observation(
            session,
            request.app.state.runtime,
            profile_id=profile_id,
            observation_id=observation_id,
            request_id=data.request_id,
            restore_token=data.restore_token,
            expected_base_revision=data.expected_base_revision,
            expected_base_hash=data.expected_base_hash,
            term_decision=data.term_decision,
            selected_term_id=data.selected_term_id,
        )


# ---------------------------------------------------------------------------
# AI tasks, candidates and adoption
# ---------------------------------------------------------------------------


def _bound_task(
    session: Session, observation_id: str, task_id: str
) -> dict[str, Any]:
    task = ai_task_service.get_task(
        session, task_id, source_kind="game_observation"
    )
    if task.get("observation_id") != observation_id:
        raise LocalAiNotFound("未找到该观察 AI 任务")
    return task


@observations_router.post(
    "/{observation_id}/ai-tasks",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=dict[str, Any],
)
def create_observation_ai_task(
    observation_id: str,
    data: LocalObservationAITaskCreateIn,
    request: Request,
    session: Session = Depends(get_session),
):
    with storage_errors():
        profile_id = _profile_id(session)
        peek = ai_task_service.peek_operation(
            session,
            request_id=data.request_id,
            operation_kind=observation_ai_service.OP_CREATE,
            payload={
                "source_kind": "game_observation",
                "source_id": observation_id,
                "profile_id": profile_id,
                "observation_id": observation_id,
                "task_type": data.task_type,
                "expected_revision": data.expected_revision,
                "expected_hash": data.expected_hash,
                "target": data.target,
            },
        )
    if peek is not None:
        return peek
    executor = _require_executor(request)
    with storage_errors():
        result, _created = observation_ai_service.create_observation_task(
            session,
            request.app.state.runtime,
            profile_id=profile_id,
            observation_id=observation_id,
            task_type=data.task_type,
            expected_revision=data.expected_revision,
            expected_hash=data.expected_hash,
            target=data.target,
            request_id=data.request_id,
        )
        executor.notify()
    return result


@observations_router.get(
    "/{observation_id}/ai-tasks", response_model=dict[str, Any]
)
def list_observation_ai_tasks(
    observation_id: str,
    status_: str | None = Query(default=None, alias="status"),
    limit: int = Query(ai_task_service.DEFAULT_LIST_LIMIT),
    cursor: str | None = None,
    session: Session = Depends(get_session),
):
    with storage_errors():
        _profile_id(session)
        return ai_task_service.list_tasks(
            session,
            observation_id=observation_id,
            status=status_,
            limit=limit,
            cursor=cursor,
            source_kind="game_observation",
        )


@observations_router.get(
    "/{observation_id}/ai-tasks/{task_id}", response_model=dict[str, Any]
)
def get_observation_ai_task(
    observation_id: str,
    task_id: str,
    session: Session = Depends(get_session),
):
    with storage_errors():
        _profile_id(session)
        return _bound_task(session, observation_id, task_id)


@observations_router.get(
    "/{observation_id}/ai-tasks/{task_id}/progress",
    response_model=dict[str, Any],
)
def get_observation_ai_task_progress(
    observation_id: str,
    task_id: str,
    session: Session = Depends(get_session),
):
    with storage_errors():
        _profile_id(session)
        _bound_task(session, observation_id, task_id)
        return _task_progress(session, task_id, "game_observation")


@observations_router.post(
    "/{observation_id}/ai-tasks/{task_id}/cancel", response_model=dict[str, Any]
)
def cancel_observation_ai_task(
    observation_id: str,
    task_id: str,
    data: dict[str, Any],
    request: Request,
    session: Session = Depends(get_session),
):
    request_id = data.get("request_id")
    expected = data.get("expected_execution_id")
    if not isinstance(request_id, str):
        raise LocalValidationError("request_id 必须是字符串")
    if expected is not None and not isinstance(expected, str):
        raise LocalValidationError("expected_execution_id 必须是字符串或空")
    with storage_errors():
        _profile_id(session)
        _bound_task(session, observation_id, task_id)
        peek = ai_task_service.peek_operation(
            session,
            request_id=request_id,
            operation_kind=ai_task_service.OP_CANCEL,
            payload={
                "task_id": task_id,
                "expected_execution_id": expected,
            },
        )
    if peek is not None:
        return peek
    executor = _require_executor(request)
    started = bool(expected) and executor.begin_cancel(expected)
    committed = False
    try:
        with storage_errors():
            result, abort_id, abort_kind = ai_task_service.cancel_task(
                session,
                task_id=task_id,
                expected_execution_id=expected,
                request_id=request_id,
                source_kind="game_observation",
            )
            committed = True
    finally:
        if started:
            executor.end_cancel(expected, committed=committed)
        executor.notify()
    if abort_kind == "stop_wait" and abort_id:
        executor.abort_execution(abort_id, "stop_wait")
    return result


@observations_router.post(
    "/{observation_id}/ai-tasks/{task_id}/resume",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=dict[str, Any],
)
def resume_observation_ai_task(
    observation_id: str,
    task_id: str,
    data: dict[str, Any],
    request: Request,
    session: Session = Depends(get_session),
):
    request_id = data.get("request_id")
    expected = data.get("expected_execution_id")
    if not isinstance(request_id, str):
        raise LocalValidationError("request_id 必须是字符串")
    if expected is not None and not isinstance(expected, str):
        raise LocalValidationError("expected_execution_id 必须是字符串或空")
    with storage_errors():
        _profile_id(session)
        _bound_task(session, observation_id, task_id)
        peek = ai_task_service.peek_operation(
            session,
            request_id=request_id,
            operation_kind=ai_task_service.OP_RESUME,
            payload={
                "task_id": task_id,
                "expected_execution_id": expected,
            },
        )
    if peek is not None:
        return peek
    executor = _require_executor(request)
    with storage_errors():
        result = ai_task_service.resume_task(
            session,
            task_id=task_id,
            expected_execution_id=expected,
            request_id=request_id,
            runtime=request.app.state.runtime,
            source_kind="game_observation",
        )
        executor.notify()
    return result


@observations_router.post(
    "/{observation_id}/ai-tasks/{task_id}/retry",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=dict[str, Any],
)
def retry_observation_ai_task(
    observation_id: str,
    task_id: str,
    data: dict[str, Any],
    request: Request,
    session: Session = Depends(get_session),
):
    request_id = data.get("request_id")
    expected = data.get("expected_execution_id")
    ack = data.get("ack_duplicate_cost", False)
    if not isinstance(request_id, str):
        raise LocalValidationError("request_id 必须是字符串")
    if not isinstance(expected, str):
        raise LocalValidationError("expected_execution_id 必须是字符串")
    if not isinstance(ack, bool):
        raise LocalValidationError("ack_duplicate_cost 必须是布尔值")
    with storage_errors():
        _profile_id(session)
        _bound_task(session, observation_id, task_id)
        peek = ai_task_service.peek_operation(
            session,
            request_id=request_id,
            operation_kind=ai_task_service.OP_RETRY,
            payload={
                "task_id": task_id,
                "expected_execution_id": expected,
                "ack_duplicate_cost": ack,
            },
        )
    if peek is not None:
        return peek
    executor = _require_executor(request)
    with storage_errors():
        result = ai_task_service.retry_task(
            session,
            task_id=task_id,
            expected_execution_id=expected,
            ack_duplicate_cost=ack,
            request_id=request_id,
            runtime=request.app.state.runtime,
            source_kind="game_observation",
        )
        executor.notify()
    return result


@observations_router.get(
    "/{observation_id}/ai-operations/{request_id}", response_model=dict[str, Any]
)
def read_observation_ai_operation(
    observation_id: str,
    request_id: str,
    session: Session = Depends(get_session),
):
    with storage_errors():
        profile_id = _profile_id(session)
        result = observation_ai_service.read_create_operation(
            session, profile_id=profile_id, request_id=request_id
        )
        if result.get("observation_id") not in (None, observation_id):
            raise LocalAiNotFound("未找到该观察 AI 提交回执")
        return {"result": result}


@observations_router.get(
    "/{observation_id}/ai-candidates", response_model=dict[str, Any]
)
def list_observation_ai_candidates(
    observation_id: str,
    limit: int = Query(20),
    cursor: str | None = None,
    session: Session = Depends(get_session),
):
    with storage_errors():
        profile_id = _profile_id(session)
        return observation_ai_service.list_candidates(
            session,
            profile_id=profile_id,
            observation_id=observation_id,
            limit=limit,
            cursor=cursor,
        )


@observations_router.get(
    "/{observation_id}/ai-candidates/{candidate_id}",
    response_model=dict[str, Any],
)
def get_observation_ai_candidate(
    observation_id: str,
    candidate_id: str,
    session: Session = Depends(get_session),
):
    with storage_errors():
        profile_id = _profile_id(session)
        return observation_ai_service.get_candidate(
            session,
            profile_id=profile_id,
            observation_id=observation_id,
            candidate_id=candidate_id,
        )


@observations_router.post(
    "/{observation_id}/ai-candidates/{candidate_id}/preview-adoption",
    response_model=dict[str, Any],
)
def preview_observation_adoption(
    observation_id: str,
    candidate_id: str,
    data: LocalObservationAIAdoptionPreviewIn,
    request: Request,
    session: Session = Depends(get_session),
):
    with storage_errors():
        profile_id = _profile_id(session)
        try:
            return observation_ai_service.preview_adoption(
                session,
                request.app.state.runtime,
                profile_id=profile_id,
                observation_id=observation_id,
                candidate_id=candidate_id,
                expected_revision=data.expected_revision,
                expected_hash=data.expected_hash,
                selected_targets=data.selected_targets,
                request_id=data.request_id,
            )
        except LocalError as exc:
            raise _map_ai_error(exc) from exc


@observations_router.post(
    "/{observation_id}/ai-candidates/{candidate_id}/adopt",
    response_model=dict[str, Any],
)
def adopt_observation_candidate(
    observation_id: str,
    candidate_id: str,
    data: LocalObservationAIAdoptionIn,
    request: Request,
    session: Session = Depends(get_session),
):
    with storage_errors():
        profile_id = _profile_id(session)
        try:
            return observation_ai_service.adopt(
                session,
                request.app.state.runtime,
                profile_id=profile_id,
                observation_id=observation_id,
                candidate_id=candidate_id,
                expected_revision=data.expected_revision,
                expected_hash=data.expected_hash,
                selected_targets=data.selected_targets,
                preview_token=data.preview_token,
                request_id=data.request_id,
                review_decision=data.review_decision,
            )
        except LocalError as exc:
            raise _map_ai_error(exc) from exc


__all__ = ["observations_router"]
