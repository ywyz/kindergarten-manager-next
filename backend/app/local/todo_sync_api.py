"""HTTP surface for the optional Nextcloud Tasks (CalDAV) todo sync.

The router is mounted by :mod:`app.local.todo_api` under
``/api/local/todos/nextcloud`` — the local API entry module stays
untouched.  The endpoints are deliberately small and idempotent by
request id; ownership is always the local profile context.

Never part of a response: the Nextcloud password (it lives only in the
machine-local DPAPI store), any remote href beyond the teacher's own list
name, or raw transport text.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Callable

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.local.api import get_session
from app.local.normalize import normalize_request_id
from app.local.profile_service import require_context
from app.local.todo_sync_models import LocalTodoSyncOperation
from app.local.todo_sync_service import TodoSyncServiceError
from app.local.todo_sync_service import (
    connect_account,
    disable,
    get_status,
    list_lists,
    run_sync,
    select_list,
)
from app.local.tx import read_scope

nextcloud_router = APIRouter(prefix="/nextcloud", tags=["todo-sync"])


class NextcloudConnectIn(BaseModel):
    request_id: str
    url: str
    username: str
    password: str


class NextcloudSelectIn(BaseModel):
    request_id: str
    expected_version: int
    list_href: str


class NextcloudSyncIn(BaseModel):
    request_id: str


class NextcloudDisableIn(BaseModel):
    request_id: str
    expected_version: int
    clear_credentials: bool = False


def _error_response(exc: TodoSyncServiceError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
        headers={"Cache-Control": "no-store"},
    )


def _runtime(request: Request):
    runtime = getattr(request.app.state, "runtime", None)
    if runtime is None:
        raise TodoSyncServiceError(
            "SYNC_RUNTIME_UNAVAILABLE", "本地服务尚未就绪", status_code=503
        )
    return runtime


def _handle(fn: Callable[[], Any]) -> Any:
    try:
        return fn()
    except TodoSyncServiceError as exc:
        return _error_response(exc)


@nextcloud_router.get("/status")
def sync_status(
    request: Request,
    session: Session = Depends(get_session),
):
    runtime = _runtime(request)

    def action():
        return get_status(session, runtime)

    return _handle(action)


@nextcloud_router.post("/connect")
def sync_connect(
    request: Request,
    data: NextcloudConnectIn,
    session: Session = Depends(get_session),
):
    runtime = _runtime(request)

    def action():
        return connect_account(
            session,
            runtime,
            request_id=data.request_id,
            url=data.url,
            username=data.username,
            password=data.password,
        )

    return _handle(action)


@nextcloud_router.post("/lists")
def sync_lists(
    request: Request,
    session: Session = Depends(get_session),
):
    runtime = _runtime(request)

    def action():
        return list_lists(session, runtime)

    return _handle(action)


@nextcloud_router.post("/select")
def sync_select(
    request: Request,
    data: NextcloudSelectIn,
    session: Session = Depends(get_session),
):
    runtime = _runtime(request)

    def action():
        return select_list(
            session,
            runtime,
            request_id=data.request_id,
            expected_version=data.expected_version,
            list_href=data.list_href,
        )

    return _handle(action)


@nextcloud_router.post("/sync")
def sync_run(
    request: Request,
    data: NextcloudSyncIn,
    session: Session = Depends(get_session),
):
    runtime = _runtime(request)

    def action():
        return run_sync(session, runtime, request_id=data.request_id)

    return _handle(action)


@nextcloud_router.post("/disable")
def sync_disable(
    request: Request,
    data: NextcloudDisableIn,
    session: Session = Depends(get_session),
):
    runtime = _runtime(request)

    def action():
        return disable(
            session,
            runtime,
            request_id=data.request_id,
            expected_version=data.expected_version,
            clear_credentials=data.clear_credentials,
        )

    return _handle(action)


@nextcloud_router.get("/operations/{request_id}")
def sync_operation(request_id: str, session: Session = Depends(get_session)):
    def action():
        rid = normalize_request_id(request_id)
        with read_scope(session):
            context = require_context(session, date.today())
            if context.profile is None:  # pragma: no cover - guarded upstream
                raise TodoSyncServiceError(
                    "SYNC_PROFILE_REQUIRED", "本地档案未就绪", status_code=409
                )
            row = session.get(LocalTodoSyncOperation, (context.profile.id, rid))
        if row is None:
            raise TodoSyncServiceError(
                "SYNC_OPERATION_NOT_FOUND", "未找到原操作回执", status_code=404
            )
        return {
            "action": row.action,
            "result": row.result_json,
            "created_at": row.created_at.isoformat(sep=" "),
        }

    return _handle(action)


__all__ = ["nextcloud_router"]
