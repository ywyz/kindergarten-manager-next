"""Desktop feedback API and the fixed-origin upstream feedback client.

The desktop never talks to the collaboration database and never accepts an
arbitrary target: this module forwards exactly one fixed endpoint
(``POST /api/collaboration/feedback/submissions``) to the one
deployment-configured HTTPS origin.  A submission is anonymous by design —
no teacher credential or collaboration session is read, attached or required,
so the entry works with and without class collaboration.  The application
version is filled in by the local API from this process's runtime, never by
the renderer.

The upstream leg reuses the collaboration proxy's transport discipline:
HTTPS-only normalized origin, no redirects, no system proxy, a bounded
response read and short timeout.  The SSL context and the synthetic-test CA
stay explicit: production builds use the default trust store, and isolated
tests inject a throwaway CA through ``app.state.feedback_ssl_context`` /
``create_feedback_client`` — never through the environment.

The router below is registered with a relative prefix and must be included
under the local router (``/api/local``), which keeps every route behind the
per-launch app-session guard.
"""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.local.collaboration_proxy import (
    _NoRedirect,
    _packaged_collaboration_origin,
)
from app.local.errors import LocalError

FEEDBACK_TIMEOUT_SECONDS = 15.0
FEEDBACK_MAX_RESPONSE_BYTES = 65_536
MAX_CONTENT_CHARS = 4000
MAX_CONTACT_CHARS = 200
MAX_CODE_CHARS = 512

_UPSTREAM_SUBMISSION_PATH = "/api/collaboration/feedback/submissions"
_CONTENT_MAX_BYTES = 65_536


class FeedbackStatusOut(BaseModel):
    configured: bool
    app_version: str
    message: str | None = None


class FeedbackSubmitIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    feedback_code: str = Field(..., min_length=1, max_length=MAX_CODE_CHARS)
    content: str = Field(..., min_length=1, max_length=MAX_CONTENT_CHARS)
    contact: str | None = Field(default=None, max_length=MAX_CONTACT_CHARS)

    @field_validator("feedback_code", "content", "contact")
    @classmethod
    def _bounded_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if "\x00" in value or any(ord(char) < 32 and char != "\n" for char in value):
            raise ValueError("value must not contain control characters")
        return value


class FeedbackReceiptOut(BaseModel):
    submission_id: str
    request_id: str
    received_at: str
    replayed: bool


def _error(
    status_code: int,
    code: str,
    message: str,
    *,
    details: dict[str, Any] | None = None,
) -> LocalError:
    error = LocalError(message, details=details)
    error.status_code = status_code
    error.code = code
    return error


def _not_configured() -> LocalError:
    return _error(
        503,
        "FEEDBACK_NOT_CONFIGURED",
        "未配置反馈服务地址，请联系部署方",
    )


def _origin_invalid() -> LocalError:
    return _error(
        503,
        "FEEDBACK_ORIGIN_INVALID",
        "反馈服务地址配置不合法，请联系部署方",
    )


def _network_failed() -> LocalError:
    return _error(
        503,
        "FEEDBACK_NETWORK_UNAVAILABLE",
        "暂时无法连接反馈服务，提交结果未确认；表单内容已保留，可稍后用同一请求再次提交",
    )


def _upstream_invalid() -> LocalError:
    return _error(
        502,
        "FEEDBACK_UPSTREAM_INVALID",
        "反馈服务返回了无法识别的结果，提交结果未确认；表单内容已保留，可稍后用同一请求再次提交",
    )


def _upstream_unavailable() -> LocalError:
    return _error(
        503,
        "FEEDBACK_UPSTREAM_UNAVAILABLE",
        "反馈服务暂时不可用，提交结果未确认；表单内容已保留，可稍后用同一请求再次提交",
    )


def _upstream_redirect() -> LocalError:
    return _error(
        502,
        "FEEDBACK_UPSTREAM_REDIRECT",
        "反馈服务返回了不允许的跳转，提交结果未确认；表单内容已保留，可稍后用同一请求再次提交",
    )


# Same strict origin rules as the collaboration proxy, with feedback-specific
# messages: HTTPS origin only, no path, query, fragment or credentials.
def _normalize_feedback_origin(
    origin: str | None,
) -> tuple[str | None, str, str | None]:
    from urllib.parse import urlsplit

    if origin is None or not origin.strip():
        return (None, "FEEDBACK_NOT_CONFIGURED", "未配置反馈服务地址，请联系部署方")
    text = origin.strip()
    if (
        any(char.isspace() or ord(char) < 33 or char == "\\" for char in text)
        or "?" in text
        or "#" in text
    ):
        return (None, "FEEDBACK_ORIGIN_INVALID", "反馈服务地址只能是 HTTPS 源，不能包含路径、查询或凭据")
    try:
        parsed = urlsplit(text)
        port = parsed.port
    except ValueError:
        return (None, "FEEDBACK_ORIGIN_INVALID", "反馈服务地址配置不合法，请联系部署方")
    if parsed.scheme.lower() != "https":
        return (None, "FEEDBACK_ORIGIN_INVALID", "反馈服务地址必须使用 HTTPS，请联系部署方")
    if not parsed.hostname:
        return (None, "FEEDBACK_ORIGIN_INVALID", "反馈服务地址配置不合法，请联系部署方")
    if (
        parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        return (None, "FEEDBACK_ORIGIN_INVALID", "反馈服务地址只能是 HTTPS 源，不能包含路径、查询或凭据")
    if port is not None and not 1 <= port <= 65535:
        return (None, "FEEDBACK_ORIGIN_INVALID", "反馈服务地址配置不合法，请联系部署方")
    return f"https://{parsed.netloc}", "FEEDBACK_READY", None


def _resolve_feedback_origin() -> tuple[str | None, str, str | None]:
    """Resolve the fixed feedback origin without any network access.

    Frozen builds read the packaged release origin (fail-closed on a present
    but malformed file) and ignore the environment, matching the
    collaboration proxy.  Source runs allow an explicit
    ``APP_FEEDBACK_API_ORIGIN`` injection — the synthetic-test entry point —
    and fall back to the collaboration origin when only that is configured.
    """
    packaged, origin, code, message = _packaged_collaboration_origin()
    if packaged:
        if origin is None:
            return (None, code or "FEEDBACK_ORIGIN_INVALID", message)
        return origin, "FEEDBACK_READY", None
    injected: str | None = None
    for name in ("APP_FEEDBACK_API_ORIGIN", "APP_COLLABORATION_API_ORIGIN"):
        value = os.environ.get(name)
        if value and value.strip():
            injected = value
            break
    if injected is None:
        return (None, "FEEDBACK_NOT_CONFIGURED", "未配置反馈服务地址，请联系部署方")
    return _normalize_feedback_origin(injected)


def _default_ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context()


def create_feedback_client(ssl_context: ssl.SSLContext | None = None) -> "FeedbackClient":
    """Build the stateless feedback client; this performs no network request."""
    origin, _code, _message = _resolve_feedback_origin()
    return FeedbackClient(origin, ssl_context=ssl_context)


class FeedbackClient:
    """A fixed, allowlisted HTTPS client for the one feedback endpoint."""

    def __init__(
        self,
        origin: str | None,
        *,
        ssl_context: ssl.SSLContext | None = None,
        timeout: float = FEEDBACK_TIMEOUT_SECONDS,
    ) -> None:
        self._origin = origin
        self._timeout = timeout
        self._ssl_context = ssl_context

    @property
    def configured(self) -> bool:
        return self._origin is not None

    def submit(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._origin is None:
            raise _not_configured()
        body = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        if len(body) > _CONTENT_MAX_BYTES:
            raise _error(
                422,
                "FEEDBACK_INVALID",
                "反馈内容序列化后超过单次上限，未发送",
            )
        request = urllib.request.Request(
            f"{self._origin}{_UPSTREAM_SUBMISSION_PATH}",
            data=body,
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "identity",
                "Content-Type": "application/json",
                "User-Agent": "KGM-Desktop-Feedback/1",
            },
            method="POST",
        )
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            _NoRedirect(),
            urllib.request.HTTPSHandler(
                context=self._ssl_context or _default_ssl_context()
            ),
        )
        try:
            with opener.open(request, timeout=self._timeout) as response:
                status_code = response.status
                content_type = response.headers.get_content_type()
                raw = response.read(FEEDBACK_MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            self._raise_http_error(exc)
            raise AssertionError("unreachable")
        except (urllib.error.URLError, TimeoutError, ssl.SSLError, OSError):
            raise _network_failed() from None
        if status_code != 200:
            raise _upstream_unavailable()
        if content_type != "application/json" or len(raw) > FEEDBACK_MAX_RESPONSE_BYTES:
            raise _upstream_invalid()
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise _upstream_invalid() from None
        if not isinstance(value, dict) or not isinstance(
            value.get("submission_id"), str
        ):
            raise _upstream_invalid()
        return value

    def _raise_http_error(self, exc: urllib.error.HTTPError) -> None:
        try:
            if 300 <= exc.code < 400:
                raise _upstream_redirect() from None
            error = self._read_error_body(exc)
            code = str(error.get("code", "")) if isinstance(error, dict) else ""
            message = (
                str(error.get("message", ""))
                if isinstance(error, dict) and error.get("message")
                else None
            )
            mapped = _UPSTREAM_ERRORS.get(code)
            if mapped is not None:
                status_code, local_code, fallback_message = mapped
                raise _error(
                    status_code,
                    local_code,
                    message or fallback_message,
                ) from None
            # Unexpected auth answers from a code-gated endpoint are treated
            # as upstream trouble, never as a local session problem.
            raise _upstream_unavailable() from None
        finally:
            try:
                exc.close()
            except OSError:
                pass

    @staticmethod
    def _read_error_body(exc: urllib.error.HTTPError) -> dict[str, Any] | None:
        try:
            raw = exc.read(FEEDBACK_MAX_RESPONSE_BYTES + 1)
        except (OSError, ValueError):
            return None
        if len(raw) > FEEDBACK_MAX_RESPONSE_BYTES:
            return None
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return None
        error = payload.get("error") if isinstance(payload, dict) else None
        return error if isinstance(error, dict) else None


_UPSTREAM_ERRORS: dict[str, tuple[int, str, str]] = {
    "FEEDBACK_CODE_INVALID": (
        400,
        "FEEDBACK_CODE_INVALID",
        "反馈码无效或未分发给本版本，请核对后重试",
    ),
    "FEEDBACK_NOT_CONFIGURED": (
        503,
        "FEEDBACK_UPSTREAM_DISABLED",
        "反馈入口未启用，请联系测试组织者",
    ),
    "REQUEST_CONFLICT": (
        409,
        "FEEDBACK_REQUEST_CONFLICT",
        "同一反馈请求 ID 已用于不同内容，原反馈不会被替换",
    ),
    "FEEDBACK_RATE_LIMITED": (
        429,
        "FEEDBACK_RATE_LIMITED",
        "提交过于频繁，请稍后再试",
    ),
    "REQUEST_TOO_LARGE": (
        422,
        "FEEDBACK_INVALID",
        "反馈内容超过大小限制，未发送",
    ),
    "FEEDBACK_INVALID": (
        422,
        "FEEDBACK_INVALID",
        "反馈内容不合法，未发送",
    ),
    "DATABASE_UNAVAILABLE": (
        503,
        "FEEDBACK_UPSTREAM_UNAVAILABLE",
        "反馈服务暂时不可用，提交结果未确认；表单内容已保留，可稍后用同一请求再次提交",
    ),
}


def get_feedback_client(request: Request) -> FeedbackClient:
    """One client per request: stateless, fixed origin, explicit TLS trust."""
    context = getattr(request.app.state, "feedback_ssl_context", None)
    return create_feedback_client(ssl_context=context)


feedback_router = APIRouter(prefix="/feedback", tags=["feedback"])


@feedback_router.get("/status", response_model=FeedbackStatusOut)
def feedback_status(request: Request) -> FeedbackStatusOut:
    origin, _code, message = _resolve_feedback_origin()
    runtime = request.app.state.runtime
    app_version = str(getattr(runtime, "app_version", "") or "")
    return FeedbackStatusOut(
        configured=origin is not None,
        app_version=app_version,
        message=message,
    )


@feedback_router.post("/submissions", response_model=FeedbackReceiptOut)
def feedback_submit(
    data: FeedbackSubmitIn,
    request: Request,
    client: FeedbackClient = Depends(get_feedback_client),
) -> FeedbackReceiptOut:
    runtime = request.app.state.runtime
    app_version = str(getattr(runtime, "app_version", "") or "")
    receipt = client.submit(
        {
            "request_id": str(data.request_id),
            "feedback_code": data.feedback_code,
            "content": data.content,
            "contact": data.contact,
            "app_version": app_version or None,
        }
    )
    submission_id = receipt.get("submission_id")
    request_id = receipt.get("request_id")
    received_at = receipt.get("received_at")
    replayed = receipt.get("replayed")
    if (
        not isinstance(submission_id, str)
        or not isinstance(request_id, str)
        or not isinstance(received_at, str)
        or not isinstance(replayed, bool)
    ):
        raise _upstream_invalid()
    return FeedbackReceiptOut(
        submission_id=submission_id,
        request_id=request_id,
        received_at=received_at,
        replayed=replayed,
    )
