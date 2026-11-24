"""HTTP routes and the body-bound guard for the in-app feedback slice.

Three deliberately separate pieces:

- ``FeedbackBodyLimitMiddleware`` — a pure ASGI guard for the one public
  feedback write.  It runs before routing and buffers the body itself: an
  illegal or over-long declared ``Content-Length`` is answered without
  reading a single body byte, an actual stream beyond ``MAX_BODY_BYTES``
  (chunked or a lying declaration) is answered with 413 without ever
  reaching the application, and only a complete within-cap body is replayed
  to the downstream app — so a truncated-but-valid JSON prefix can never be
  parsed and committed while the client is told 413.  Only the feedback
  submission route is intercepted.
- ``/api/collaboration/feedback/submissions`` — the one unauthenticated
  write used by the desktop app.  Since 2026-11-24 it needs no feedback code
  and no collaboration account; the optional ``feedback_code`` is accepted
  only for already-released clients, and the optional ``diagnostics``
  window is a bounded list of fixed-shape events.  It never reads or
  returns any stored feedback.
- ``/api/collaboration/admin/feedback`` — the admin list (bounded offset /
  limit pagination with a total count) and processing-state update,
  protected by the existing administrator session and CSRF checks.  The list
  carries each submission's attached diagnostics verbatim so the
  administrator sees exactly the events that were sent; old submissions
  without an attachment keep rendering (their diagnostics stay null).

User content crosses this boundary only as JSON values; the admin page is
responsible for text-only rendering.
"""

from __future__ import annotations

import json
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from .admin_api import get_admin_csrf_principal, get_admin_principal
from .admin_service import AdminPrincipal
from .api import get_session, get_settings
from .config import CollaborationSettings
from .feedback_service import (
    MAX_BODY_BYTES,
    FeedbackListItem,
    list_feedback,
    submit_feedback,
    update_feedback_status,
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FeedbackSubmitIn(_StrictModel):
    request_id: UUID
    # Old-request compatibility only: released clients still send a code; a
    # new submission carries none and needs no code, account or login.
    feedback_code: str | None = Field(default=None, max_length=512)
    content: str = Field(..., min_length=1, max_length=4000)
    contact: str | None = Field(default=None, max_length=200)
    app_version: str | None = Field(default=None, max_length=100)
    diagnostics: list[dict[str, Any]] | None = Field(default=None)

    @field_validator("feedback_code", "content", "contact", "app_version")
    @classmethod
    def _no_nul(cls, value: str | None) -> str | None:
        if value is not None and "\x00" in value:
            raise ValueError("value must not contain NUL characters")
        return value

    @field_validator("diagnostics")
    @classmethod
    def _bounded_diagnostics(
        cls, value: list[dict[str, Any]] | None
    ) -> list[dict[str, Any]] | None:
        # A structural bound only; the fixed vocabulary, timestamps and code
        # rules are enforced by the service-level validation.
        from .feedback_service import MAX_DIAGNOSTICS_EVENTS

        if value is None:
            return None
        if len(value) > MAX_DIAGNOSTICS_EVENTS:
            raise ValueError("too many diagnostics events")
        return value


class FeedbackReceiptOut(_StrictModel):
    submission_id: UUID
    request_id: UUID
    received_at: str
    replayed: bool


class FeedbackItemOut(_StrictModel):
    submission_id: UUID
    request_id: UUID
    status: str
    content: str
    contact: str | None
    app_version: str | None
    diagnostics_events: list[dict[str, Any]] | None
    handled_by_admin_username: str | None
    handled_at: str | None
    created_at: str


class FeedbackListOut(_StrictModel):
    items: list[FeedbackItemOut]
    total: int
    offset: int
    limit: int


class FeedbackStatusUpdateIn(_StrictModel):
    expected_status: str = Field(..., min_length=1, max_length=16)
    new_status: str = Field(..., min_length=1, max_length=16)


def _iso(value) -> str:
    return value.isoformat()


def _item_out(item: FeedbackListItem) -> FeedbackItemOut:
    return FeedbackItemOut(
        submission_id=item.submission_id,
        request_id=item.request_id,
        status=item.status,
        content=item.content,
        contact=item.contact,
        app_version=item.app_version,
        diagnostics_events=item.diagnostics_events,
        handled_by_admin_username=item.handled_by_admin_username,
        handled_at=_iso(item.handled_at) if item.handled_at else None,
        created_at=_iso(item.created_at),
    )


FEEDBACK_SUBMISSION_PATH = "/api/collaboration/feedback/submissions"


def _declared_content_length(scope: dict[str, Any]) -> int | None | str:
    for name, value in scope.get("headers") or []:
        if name == b"content-length":
            text = value.decode("latin-1").strip()
            try:
                length = int(text)
            except ValueError:
                return "invalid"
            if length < 0:
                return "invalid"
            return length
    return None


async def _send_rejection(
    send: Any,
    status_code: int,
    code: str,
    message: str,
) -> None:
    body = json.dumps(
        {"error": {"code": code, "message": message}},
        ensure_ascii=False,
    ).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"cache-control", b"no-store"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class FeedbackBodyLimitMiddleware:
    """Pure ASGI body bound for the feedback submission route (only).

    The body is buffered here first and never streamed into the application:

    - an illegal or over-long declared ``Content-Length`` is answered before
      a single body byte is read;
    - otherwise at most ``MAX_BODY_BYTES`` actual bytes are read (covering
      chunked streams and declarations that lie); the moment the cap is
      exceeded the answer is 413 and the remainder is never read;
    - only a complete, within-cap body is replayed to the downstream app, so
      the application can never parse a truncated-but-valid JSON prefix and
      commit a submission for a request that is answered with 413;
    - an explicit disconnect during buffering ends the exchange without
      invoking the application, so nothing is written for a vanished client.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") != "POST"
            or scope.get("path") != FEEDBACK_SUBMISSION_PATH
        ):
            await self.app(scope, receive, send)
            return
        declared = _declared_content_length(scope)
        if declared == "invalid":
            await _send_rejection(
                send, 422, "FEEDBACK_INVALID", "Content-Length 不合法"
            )
            return
        if declared is not None and declared > MAX_BODY_BYTES:
            # Declared too large: answer before reading any body byte.
            await _send_rejection(
                send, 413, "REQUEST_TOO_LARGE", "请求体超过大小限制"
            )
            return
        buffered = bytearray()
        overflow = False
        disconnected = False
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                disconnected = True
                break
            if message["type"] != "http.request":
                continue
            chunk = message.get("body") or b""
            if chunk:
                buffered.extend(chunk)
            if len(buffered) > MAX_BODY_BYTES:
                overflow = True
                break
            if not message.get("more_body"):
                break
        if overflow:
            # Over the cap: answer here.  The downstream application is never
            # invoked, so nothing can be parsed or written for this request,
            # and the unread remainder is never read.
            await _send_rejection(
                send, 413, "REQUEST_TOO_LARGE", "请求体超过大小限制"
            )
            return
        if disconnected:
            # The client vanished mid-body: nothing to answer and nothing to
            # store; the server just ends this exchange.
            return
        body = bytes(buffered)
        replayed = False

        async def bounded_receive() -> dict[str, Any]:
            nonlocal replayed
            if replayed:
                return {"type": "http.request", "body": b"", "more_body": False}
            replayed = True
            return {"type": "http.request", "body": body, "more_body": False}

        await self.app(scope, bounded_receive, send)


def add_feedback_body_limit(app: Any) -> None:
    """Mount the body bound on an app hosting the feedback routers."""
    app.add_middleware(FeedbackBodyLimitMiddleware)


feedback_router = APIRouter(
    prefix="/api/collaboration/feedback",
    tags=["feedback"],
)


@feedback_router.post("/submissions", response_model=FeedbackReceiptOut)
def submit(
    data: FeedbackSubmitIn,
    request: Request,
    session: Session = Depends(get_session),
    settings: CollaborationSettings = Depends(get_settings),
) -> FeedbackReceiptOut:
    client_ip = request.client.host if request.client is not None else ""
    receipt = submit_feedback(
        session,
        settings,
        request_id=data.request_id,
        code=data.feedback_code,
        content=data.content,
        contact=data.contact,
        app_version=data.app_version,
        client_ip=client_ip,
        diagnostics=data.diagnostics,
    )
    return FeedbackReceiptOut(
        submission_id=receipt.submission_id,
        request_id=receipt.request_id,
        received_at=_iso(receipt.received_at),
        replayed=receipt.replayed,
    )


admin_feedback_router = APIRouter(
    prefix="/api/collaboration/admin/feedback",
    tags=["feedback-admin"],
)

FeedbackStatusFilter = Literal["new", "processing", "resolved"]


@admin_feedback_router.get("", response_model=FeedbackListOut)
def admin_list_feedback(
    response: Response,
    status: FeedbackStatusFilter | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
    _principal: AdminPrincipal = Depends(get_admin_principal),
) -> FeedbackListOut:
    response.headers["Cache-Control"] = "no-store"
    page = list_feedback(session, status=status, offset=offset, limit=limit)
    return FeedbackListOut(
        items=[_item_out(item) for item in page.items],
        total=page.total,
        offset=page.offset,
        limit=page.limit,
    )


@admin_feedback_router.patch(
    "/{submission_id}", response_model=FeedbackItemOut
)
def admin_update_feedback_status(
    submission_id: UUID,
    data: FeedbackStatusUpdateIn,
    response: Response,
    session: Session = Depends(get_session),
    principal: AdminPrincipal = Depends(get_admin_csrf_principal),
) -> FeedbackItemOut:
    item = update_feedback_status(
        session,
        admin_id=principal.admin_id,
        submission_id=submission_id,
        expected_status=data.expected_status,
        new_status=data.new_status,
    )
    response.headers["Cache-Control"] = "no-store"
    return _item_out(item)
