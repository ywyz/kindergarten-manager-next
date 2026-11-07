"""Protected local HTTP routes for one-to-one listening (L1).

All identity, class and term ownership is server-derived from the single local
profile; clients never send profile/class/term ownership fields for an
existing record.  The routes adapt the reviewed listening service and asset
module without creating a second business state machine.

Photo import uses the same strictly bounded single-file multipart envelope as
the observation API; the runtime dependency set intentionally does not include
``python-multipart``.
"""

from __future__ import annotations

import io
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.local import (
    listening_assets,
    listening_service,
    profile_service,
)
from app.local.api import get_session
from app.local.errors import LocalError, LocalValidationError
from app.local.observation_api import _int_field, _read_multipart
from app.local.observation_assets import ObservationMaterialLimit
from app.local.schemas import (
    LocalListeningCreateIn,
    LocalListeningDomainPatchIn,
    LocalListeningPhotoRemoveIn,
    LocalListeningRecordPatchIn,
    LocalListeningReorderIn,
)
from app.local.tx import read_scope, storage_errors

listening_router = APIRouter(prefix="/api/listening", tags=["listening"])


def _profile_id(session: Session) -> str:
    with read_scope(session):
        context = profile_service.require_context(session, date.today())
    if context.profile is None:  # pragma: no cover - require_context guarantees it
        raise LocalValidationError("本地档案尚未初始化")
    return context.profile.id


def _listening_material_error(message: str) -> listening_assets.ListeningMaterialInvalid:
    return listening_assets.ListeningMaterialInvalid(message)


def _revision_field(value: str | None) -> int:
    try:
        return _int_field(value, "expected_revision")
    except LocalError as exc:
        raise _listening_material_error(str(exc)) from None


async def _read_listening_multipart(request: Request) -> tuple[dict[str, str], bytes]:
    try:
        return await _read_multipart(request)
    except LocalError as exc:
        if isinstance(exc, ObservationMaterialLimit):
            raise listening_assets.ListeningMaterialLimit(str(exc)) from None
        raise _listening_material_error(str(exc)) from None


def _domain_patch(data: LocalListeningDomainPatchIn) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    for name in (
        "observation_date",
        "adult_count",
        "child_age",
        "goal",
        "observation_area",
        "overall_evaluation",
        "support_strategy",
    ):
        if name in data.model_fields_set:
            patch[name] = getattr(data, name)
    if "groups" in data.model_fields_set:
        groups: list[dict[str, Any]] = []
        for item in data.groups or []:
            group_patch: dict[str, Any] = {"group_id": item.group_id}
            if "work_date" in item.model_fields_set:
                group_patch["work_date"] = item.work_date
            if "listening_text" in item.model_fields_set:
                group_patch["listening_text"] = item.listening_text
            groups.append(group_patch)
        patch["groups"] = groups
    if "evaluation" in data.model_fields_set:
        patch["evaluation"] = data.evaluation
    return patch


@listening_router.post(
    "/records", status_code=status.HTTP_201_CREATED, response_model=dict[str, Any]
)
def create_listening_record(
    data: LocalListeningCreateIn,
    session: Session = Depends(get_session),
):
    with storage_errors():
        profile_id = _profile_id(session)
        return listening_service.create_record(
            session,
            profile_id=profile_id,
            request_id=data.request_id,
            term_id=data.term_id,
            child_name=data.child_name,
        )


@listening_router.get("/records", response_model=dict[str, Any])
def list_listening_records(
    term_id: str | None = None,
    child_name: str | None = None,
    offset: int = Query(0),
    limit: int = Query(listening_service.DEFAULT_LIST_LIMIT),
    session: Session = Depends(get_session),
):
    with storage_errors():
        profile_id = _profile_id(session)
        return listening_service.list_records(
            session,
            profile_id=profile_id,
            term_id=term_id,
            child_name=child_name,
            offset=offset,
            limit=limit,
        )


@listening_router.get(
    "/records/operations/{request_id}", response_model=dict[str, Any]
)
def read_listening_operation(
    request_id: str,
    session: Session = Depends(get_session),
):
    """Read a create/record receipt without knowing the record id."""
    with storage_errors():
        profile_id = _profile_id(session)
        return listening_service.read_operation_receipt(
            session, profile_id=profile_id, request_id=request_id
        )


@listening_router.get("/templates", response_model=dict[str, Any])
def read_listening_templates(
    domain: str | None = None,
    version: str | None = None,
    record_id: str | None = None,
    session: Session = Depends(get_session),
):
    with storage_errors():
        profile_id = _profile_id(session)
        return listening_service.get_templates(
            session,
            profile_id=profile_id,
            domain=domain,
            version=version,
            record_id=record_id,
        )


@listening_router.get("/records/{record_id}", response_model=dict[str, Any])
def read_listening_record(
    record_id: str,
    session: Session = Depends(get_session),
):
    with storage_errors():
        profile_id = _profile_id(session)
        return listening_service.read_record(
            session, profile_id=profile_id, record_id=record_id
        )


@listening_router.patch("/records/{record_id}", response_model=dict[str, Any])
def patch_listening_record(
    record_id: str,
    data: LocalListeningRecordPatchIn,
    session: Session = Depends(get_session),
):
    with storage_errors():
        profile_id = _profile_id(session)
        return listening_service.patch_record_name(
            session,
            profile_id=profile_id,
            record_id=record_id,
            request_id=data.request_id,
            expected_revision=data.expected_revision,
            child_name=data.child_name,
        )


@listening_router.get(
    "/records/{record_id}/operations/{request_id}",
    response_model=dict[str, Any],
)
def read_listening_record_operation(
    record_id: str,
    request_id: str,
    session: Session = Depends(get_session),
):
    with storage_errors():
        profile_id = _profile_id(session)
        receipt = listening_service.read_operation_receipt(
            session, profile_id=profile_id, request_id=request_id
        )
        result = receipt.get("result") or {}
        if result.get("record_id") not in (None, record_id):
            raise listening_service.ListeningOperationNotFound()
        return receipt


@listening_router.patch(
    "/records/{record_id}/domains/{domain}", response_model=dict[str, Any]
)
def save_listening_domain(
    record_id: str,
    domain: str,
    data: LocalListeningDomainPatchIn,
    session: Session = Depends(get_session),
):
    with storage_errors():
        profile_id = _profile_id(session)
        return listening_service.save_domain(
            session,
            profile_id=profile_id,
            record_id=record_id,
            domain=domain,
            request_id=data.request_id,
            expected_revision=data.expected_revision,
            patch=_domain_patch(data),
        )


@listening_router.post(
    "/records/{record_id}/domains/{domain}/photos/order",
    response_model=dict[str, Any],
)
def reorder_listening_photos(
    record_id: str,
    domain: str,
    data: LocalListeningReorderIn,
    session: Session = Depends(get_session),
):
    with storage_errors():
        profile_id = _profile_id(session)
        return listening_assets.reorder_groups(
            session,
            profile_id=profile_id,
            record_id=record_id,
            domain=domain,
            request_id=data.request_id,
            expected_revision=data.expected_revision,
            group_ids=data.group_ids,
        )


@listening_router.post(
    "/records/{record_id}/domains/{domain}/photos/{group_id}",
    status_code=status.HTTP_201_CREATED,
    response_model=dict[str, Any],
)
async def import_listening_photo(
    record_id: str,
    domain: str,
    group_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    profile_id = _profile_id(session)
    fields, content = await _read_listening_multipart(request)
    request_id = fields.get("request_id")
    if not request_id:
        raise _listening_material_error("缺少 request_id")
    expected_revision = _revision_field(fields.get("expected_revision"))
    display_name = fields.get("display_name") or "photo"
    runtime = request.app.state.runtime
    return await run_in_threadpool(
        _import_listening_photo_sync,
        session,
        runtime,
        profile_id,
        record_id,
        domain,
        group_id,
        request_id,
        expected_revision,
        content,
        display_name,
    )


def _import_listening_photo_sync(
    session: Session,
    runtime,
    profile_id: str,
    record_id: str,
    domain: str,
    group_id: str,
    request_id: str,
    expected_revision: int,
    content: bytes,
    display_name: str,
):
    with storage_errors():
        return listening_assets.import_group_photo(
            session,
            runtime,
            profile_id=profile_id,
            record_id=record_id,
            domain=domain,
            group_id=group_id,
            request_id=request_id,
            expected_revision=expected_revision,
            stream=io.BytesIO(content),
            display_name=display_name,
        )


@listening_router.delete(
    "/records/{record_id}/domains/{domain}/photos/{group_id}",
    response_model=dict[str, Any],
)
def remove_listening_photo(
    record_id: str,
    domain: str,
    group_id: str,
    data: LocalListeningPhotoRemoveIn,
    session: Session = Depends(get_session),
):
    with storage_errors():
        profile_id = _profile_id(session)
        return listening_assets.remove_group_photo(
            session,
            profile_id=profile_id,
            record_id=record_id,
            domain=domain,
            group_id=group_id,
            request_id=data.request_id,
            expected_revision=data.expected_revision,
        )


@listening_router.get("/records/{record_id}/assets/{asset_id}/content")
def read_listening_asset(
    record_id: str,
    asset_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    with storage_errors():
        profile_id = _profile_id(session)
        payload, metadata = listening_assets.read_asset(
            session,
            request.app.state.runtime,
            profile_id=profile_id,
            record_id=record_id,
            asset_id=asset_id,
        )
        return Response(
            content=payload,
            media_type=metadata["mime_type"],
            headers={
                "Cache-Control": "no-store",
                "Content-Length": str(len(payload)),
            },
        )


__all__ = ["listening_router"]
