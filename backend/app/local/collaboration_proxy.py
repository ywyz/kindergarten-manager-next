"""Authenticated local proxy for the optional online collaboration service.

The desktop never talks to PostgreSQL and never accepts an arbitrary target.
This module only forwards the fixed collaboration endpoints below to the one
deployment-configured HTTPS origin in ``APP_COLLABORATION_API_ORIGIN``.  The
teacher credential is kept in this process's memory only and is never returned,
logged, written to SQLite, or included in an error message.

The local app middleware already enforces the loopback Host, the exact Origin
for mutating requests and the per-launch ``X-App-Session`` token for every
path below ``/api``.  This router deliberately has no unauthenticated route.
"""

from __future__ import annotations

import json
import os
import ssl
import threading
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from app.local.errors import LocalError

API_PREFIX = "/api/collaboration"
MAX_RESPONSE_BYTES = 2_000_000
MAX_ERROR_BYTES = 65_536
REQUEST_TIMEOUT_SECONDS = 15.0
_OPERATION_PATH_PREFIX = "/game-config/operations/"
_ALLOWED_ENDPOINTS = frozenset(
    {
        ("GET", "/me"),
        ("GET", "/classes"),
        ("GET", "/me/class"),
        ("PUT", "/me/class"),
        ("DELETE", "/me/class"),
        ("GET", "/classmates"),
        ("GET", "/game-config"),
        ("PUT", "/game-config"),
        ("POST", "/game-config/preview"),
        ("POST", "/game-config/confirm"),
    }
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TeacherOut(_StrictModel):
    teacher_id: UUID
    display_name: str
    school_id: UUID
    school_name: str


class ClassOut(_StrictModel):
    class_id: UUID
    display_name: str


class MembershipOut(_StrictModel):
    teacher_id: UUID
    school_id: UUID
    class_id: UUID
    class_name: str
    selected_at: datetime


class MembershipEnvelope(_StrictModel):
    membership: MembershipOut | None


class ClassmateOut(_StrictModel):
    teacher_id: UUID
    display_name: str
    config_version: int
    config_updated_at: datetime | None


class GameLocation(_StrictModel):
    kind: Literal["area", "special_room", "outdoor"]
    name: str = Field(..., min_length=1, max_length=80)
    guidance: str | None = Field(default=None, max_length=2000)


class GameConfigPayload(_StrictModel):
    locations: list[GameLocation]
    game_scope: str | None
    guidance: str | None


class ConfigCurrentOut(_StrictModel):
    class_id: UUID
    config_version: int
    payload: GameConfigPayload


class ConfigSaveOut(_StrictModel):
    request_id: UUID
    class_id: UUID
    config_version: int
    changed: bool
    payload: GameConfigPayload
    replayed: bool = False


class TextFieldDiff(_StrictModel):
    source: str | None
    target: str | None
    changed: bool


class LocationsDiff(_StrictModel):
    source: list[GameLocation]
    target: list[GameLocation]
    changed: bool


class GameConfigDiff(_StrictModel):
    locations: LocationsDiff
    game_scope: TextFieldDiff
    guidance: TextFieldDiff
    changed: bool


class ConfigPreviewOut(_StrictModel):
    request_id: UUID
    preview_token: str
    expires_at: datetime
    class_id: UUID
    source_teacher_id: UUID
    source_teacher_name: str
    source_version: int
    target_version: int
    source_payload: GameConfigPayload
    target_payload: GameConfigPayload
    diff: GameConfigDiff


class ConfigConfirmOut(_StrictModel):
    request_id: UUID
    class_id: UUID
    source_teacher_id: UUID
    source_version: int
    target_version: int
    config_version: int
    changed: bool
    payload: GameConfigPayload
    replayed: bool = False


class OperationOut(_StrictModel):
    request_id: UUID
    kind: Literal["save", "import"]
    result: ConfigSaveOut | ConfigConfirmOut


class StatusOut(_StrictModel):
    configured: bool
    connected: bool
    teacher: TeacherOut | None = None
    message: str | None = None


class RemoveClassOut(_StrictModel):
    removed: bool


class ConnectIn(_StrictModel):
    credential: str = Field(..., min_length=1, max_length=4096)
    expected_teacher_id: UUID | None = None
    expected_school_id: UUID | None = None

    @field_validator("credential")
    @classmethod
    def _credential_shape(cls, value: str) -> str:
        if value != value.strip() or not value:
            raise ValueError("credential must not have surrounding whitespace")
        if any(ord(char) < 32 for char in value):
            raise ValueError("credential contains control characters")
        return value

    @model_validator(mode="after")
    def _binding_pair(self) -> "ConnectIn":
        if (self.expected_teacher_id is None) != (
            self.expected_school_id is None
        ):
            raise ValueError(
                "expected teacher and school must be supplied together"
            )
        return self


class SelectClassIn(_StrictModel):
    class_id: UUID


class ClassGamesChangeIn(_StrictModel):
    kind: Literal["class_games"]
    locations: list[GameLocation] = Field(default_factory=list, max_length=90)
    game_scope: str | None = Field(default=None, max_length=8000)
    guidance: str | None = Field(default=None, max_length=8000)


class SaveGameConfigIn(_StrictModel):
    request_id: UUID
    class_id: UUID
    expected_version: int = Field(..., ge=0, strict=True)
    change: ClassGamesChangeIn


class PreviewImportIn(_StrictModel):
    request_id: UUID
    class_id: UUID
    source_teacher_id: UUID


class ConfirmImportIn(_StrictModel):
    request_id: UUID
    preview_token: str = Field(..., min_length=1, max_length=4096)
    source_teacher_id: UUID
    source_version: int = Field(..., ge=1, strict=True)
    target_version: int = Field(..., ge=0, strict=True)


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


def _endpoint_allowed(method: str, path: str) -> bool:
    if (method, path) in _ALLOWED_ENDPOINTS:
        return True
    if method != "GET" or not path.startswith(_OPERATION_PATH_PREFIX):
        return False
    try:
        UUID(path[len(_OPERATION_PATH_PREFIX):])
    except (ValueError, TypeError):
        return False
    return True


def _not_configured() -> LocalError:
    return _error(
        503,
        "COLLABORATION_NOT_CONFIGURED",
        "未配置在线协作服务地址，请联系部署方",
    )


def _not_connected() -> LocalError:
    return _error(
        409,
        "COLLABORATION_NOT_CONNECTED",
        "尚未连接在线协作，请先输入部署方提供的登录凭据",
    )


def _session_changed() -> LocalError:
    return _error(
        409,
        "COLLABORATION_SESSION_CHANGED",
        "在线协作连接已变化，请重新连接并核对原请求回执",
    )


def _recovery_identity_mismatch() -> LocalError:
    return _error(
        409,
        "COLLABORATION_RECOVERY_IDENTITY_MISMATCH",
        "该凭据不属于待核对的原在线账号，未建立会话",
    )


def _auth_failed() -> LocalError:
    return _error(
        401,
        "COLLABORATION_AUTH_FAILED",
        "在线协作凭据无效或已过期，请重新连接",
    )


def _network_failed() -> LocalError:
    return _error(
        503,
        "COLLABORATION_NETWORK_UNAVAILABLE",
        "无法连接在线协作服务，请检查网络后重试",
    )


def _upstream_invalid() -> LocalError:
    return _error(
        502,
        "COLLABORATION_UPSTREAM_INVALID",
        "在线协作服务返回了无法识别的结果，请稍后重试",
    )


def _upstream_unavailable() -> LocalError:
    return _error(
        503,
        "COLLABORATION_UPSTREAM_UNAVAILABLE",
        "在线协作服务暂时不可用，请稍后重试",
    )


def _upstream_redirect() -> LocalError:
    return _error(
        502,
        "COLLABORATION_UPSTREAM_REDIRECT",
        "在线协作服务返回了不允许的跳转，已停止转发",
    )


_UPSTREAM_ERRORS: dict[str, tuple[int, str, str]] = {
    "CLASS_NOT_FOUND": (
        404,
        "COLLABORATION_CLASS_NOT_FOUND",
        "当前园所中没有该班级",
    ),
    "CLASS_NOT_SELECTED": (
        409,
        "COLLABORATION_CLASS_NOT_SELECTED",
        "请先在在线协作中选择班级",
    ),
    "SOURCE_NOT_AVAILABLE": (
        404,
        "COLLABORATION_SOURCE_NOT_AVAILABLE",
        "该教师当前不是你的同班教师",
    ),
    "SOURCE_CONFIG_MISSING": (
        409,
        "COLLABORATION_SOURCE_CONFIG_MISSING",
        "对方尚未保存可带入的班级游戏配置",
    ),
    "PREVIEW_INVALID": (
        409,
        "COLLABORATION_PREVIEW_INVALID",
        "预览已失效，请重新预览",
    ),
    "PREVIEW_EXPIRED": (
        409,
        "COLLABORATION_PREVIEW_EXPIRED",
        "预览已过期，请重新预览",
    ),
    "PREVIEW_BINDING_MISMATCH": (
        409,
        "COLLABORATION_PREVIEW_BINDING_MISMATCH",
        "确认内容与预览不一致，请重新预览",
    ),
    "SOURCE_VERSION_CHANGED": (
        409,
        "COLLABORATION_SOURCE_VERSION_CHANGED",
        "对方配置已变化，请重新读取并预览",
    ),
    "TARGET_VERSION_CHANGED": (
        409,
        "COLLABORATION_TARGET_VERSION_CHANGED",
        "你的在线配置已变化，请重新读取后再操作",
    ),
    "MEMBERSHIP_CHANGED": (
        409,
        "COLLABORATION_MEMBERSHIP_CHANGED",
        "当前班级或同班关系已变化，请重新读取并预览",
    ),
    "REQUEST_CONFLICT": (
        409,
        "COLLABORATION_REQUEST_CONFLICT",
        "同一请求 ID 已在处理其他内容，原请求不会被替换",
    ),
    "INVALID_CLASS_GAMES": (
        422,
        "COLLABORATION_INVALID_CLASS_GAMES",
        "班级游戏配置不合法",
    ),
}


def _safe_upstream_error(
    code: str | None,
    details: dict[str, Any] | None,
    http_status: int,
) -> LocalError:
    if code == "AUTH_REQUIRED":
        return _auth_failed()
    spec = _UPSTREAM_ERRORS.get(code or "")
    if spec is None:
        fallback = {
            404: (
                "COLLABORATION_UPSTREAM_NOT_FOUND",
                "在线协作资源不存在",
            ),
            409: (
                "COLLABORATION_CONFLICT",
                "在线协作状态已变化，请重新读取",
            ),
            422: (
                "COLLABORATION_INVALID_REQUEST",
                "在线协作请求参数不合法",
            ),
        }.get(http_status)
        if fallback is None:
            return _upstream_unavailable()
        return _error(http_status, fallback[0], fallback[1])
    status_code, local_code, message = spec
    safe_details: dict[str, Any] = {}
    if details is not None:
        for key in ("current_source_version", "current_target_version"):
            value = details.get(key)
            if type(value) is int and 0 <= value <= 2_147_483_647:
                safe_details[key] = value
    return _error(
        status_code,
        local_code,
        message,
        details=safe_details or None,
    )


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        # Returning None makes urllib stop at the 3xx response instead of
        # following an untrusted Location header.
        return None


_SSL_CONTEXT = ssl.create_default_context()
_OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}),
    _NoRedirect(),
    urllib.request.HTTPSHandler(context=_SSL_CONTEXT),
)


class CollaborationProxy:
    """Process-memory session plus a fixed, allowlisted HTTPS client."""

    def __init__(self, origin: str | None) -> None:
        self._lock = threading.RLock()
        self._generation = 0
        self._token: str | None = None
        self._teacher: TeacherOut | None = None
        (
            self._origin,
            self._configuration_code,
            self._configuration_error,
        ) = _normalize_origin(origin)

    def status(self) -> StatusOut:
        with self._lock:
            if self._origin is None:
                return StatusOut(
                    configured=False,
                    connected=False,
                    teacher=None,
                    message=self._configuration_error,
                )
            return StatusOut(
                configured=True,
                connected=self._token is not None,
                teacher=self._teacher,
                message=None if self._token is not None else "尚未连接在线协作",
            )

    def connect(
        self,
        credential: str,
        expected_teacher_id: UUID | None = None,
        expected_school_id: UUID | None = None,
    ) -> StatusOut:
        self._require_configured()
        generation = self._begin_connect()
        payload = self._send(
            generation,
            credential,
            "GET",
            "/me",
            None,
        )
        teacher = self._validate(generation, TeacherOut, payload)
        if expected_teacher_id is not None and (
            teacher.teacher_id != expected_teacher_id
            or teacher.school_id != expected_school_id
        ):
            # _begin_connect already cleared the old session, and this
            # candidate session is deliberately not installed.  No wrong
            # teacher is exposed and no disconnect race exists.
            raise _recovery_identity_mismatch()
        with self._lock:
            if generation != self._generation:
                raise _session_changed()
            self._token = credential
            self._teacher = teacher
            return StatusOut(
                configured=True,
                connected=True,
                teacher=teacher,
                message=None,
            )

    def disconnect(self) -> StatusOut:
        with self._lock:
            self._generation += 1
            self._token = None
            self._teacher = None
        return self.status()

    def classes(self) -> list[ClassOut]:
        generation, token = self._require_session()
        payload = self._send(generation, token, "GET", "/classes", None)
        return self._validate_list(generation, ClassOut, payload)

    def membership(self) -> MembershipOut | None:
        generation, token = self._require_session()
        payload = self._send(generation, token, "GET", "/me/class", None)
        if payload is None:
            return None
        return self._validate(generation, MembershipOut, payload)

    def select_class(self, class_id: UUID) -> MembershipOut:
        generation, token = self._require_session()
        payload = self._send(
            generation,
            token,
            "PUT",
            "/me/class",
            SelectClassIn(class_id=class_id).model_dump(mode="json"),
        )
        return self._validate(generation, MembershipOut, payload)

    def leave_class(self) -> None:
        generation, token = self._require_session()
        self._send(generation, token, "DELETE", "/me/class", None)

    def classmates(self) -> list[ClassmateOut]:
        generation, token = self._require_session()
        payload = self._send(generation, token, "GET", "/classmates", None)
        return self._validate_list(generation, ClassmateOut, payload)

    def own_config(self) -> ConfigCurrentOut:
        generation, token = self._require_session()
        payload = self._send(generation, token, "GET", "/game-config", None)
        return self._validate(generation, ConfigCurrentOut, payload)

    def save_config(self, data: SaveGameConfigIn) -> ConfigSaveOut:
        generation, token = self._require_session()
        payload = self._send(
            generation,
            token,
            "PUT",
            "/game-config",
            data.model_dump(mode="json"),
        )
        return self._validate(generation, ConfigSaveOut, payload)

    def preview_import(self, data: PreviewImportIn) -> ConfigPreviewOut:
        generation, token = self._require_session()
        payload = self._send(
            generation,
            token,
            "POST",
            "/game-config/preview",
            data.model_dump(mode="json"),
        )
        return self._validate(generation, ConfigPreviewOut, payload)

    def confirm_import(self, data: ConfirmImportIn) -> ConfigConfirmOut:
        generation, token = self._require_session()
        payload = self._send(
            generation,
            token,
            "POST",
            "/game-config/confirm",
            data.model_dump(mode="json"),
        )
        return self._validate(generation, ConfigConfirmOut, payload)

    def operation(self, request_id: UUID) -> OperationOut:
        generation, token = self._require_session()
        payload = self._send(
            generation,
            token,
            "GET",
            f"/game-config/operations/{request_id}",
            None,
        )
        return self._validate(generation, OperationOut, payload)

    def _require_configured(self) -> None:
        if self._origin is None:
            raise _error(
                503,
                self._configuration_code or "COLLABORATION_NOT_CONFIGURED",
                self._configuration_error or "未配置在线协作服务地址，请联系部署方",
            )

    def _require_session(self) -> tuple[int, str]:
        with self._lock:
            self._require_configured()
            if self._token is None:
                raise _not_connected()
            return self._generation, self._token

    def _begin_connect(self) -> int:
        with self._lock:
            self._generation += 1
            self._token = None
            self._teacher = None
            return self._generation

    def _ensure_current(self, generation: int) -> None:
        with self._lock:
            if generation != self._generation:
                raise _session_changed()

    def _invalidate(self, generation: int) -> None:
        with self._lock:
            if generation != self._generation:
                return
            self._generation += 1
            self._token = None
            self._teacher = None

    def _validate(
        self, generation: int, model: type[BaseModel], payload: Any
    ) -> Any:
        self._ensure_current(generation)
        if not isinstance(payload, dict):
            raise _upstream_invalid()
        try:
            value = model.model_validate(payload)
        except ValidationError:
            raise _upstream_invalid() from None
        self._ensure_current(generation)
        return value

    def _validate_list(
        self, generation: int, model: type[BaseModel], payload: Any
    ) -> list[Any]:
        self._ensure_current(generation)
        if not isinstance(payload, list):
            raise _upstream_invalid()
        values: list[Any] = []
        try:
            for item in payload:
                if not isinstance(item, dict):
                    raise _upstream_invalid()
                values.append(model.model_validate(item))
        except ValidationError:
            raise _upstream_invalid() from None
        self._ensure_current(generation)
        return values

    def _send(
        self,
        generation: int,
        token: str,
        method: str,
        path: str,
        payload: dict[str, Any] | None,
    ) -> Any:
        self._require_configured()
        assert self._origin is not None
        if not _endpoint_allowed(method, path):
            raise _error(
                500,
                "COLLABORATION_PROXY_ENDPOINT",
                "本地在线协作代理拒绝了未登记的在线接口",
            )
        body = (
            None
            if payload is None
            else json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "Authorization": f"Bearer {token}",
            "User-Agent": "KGM-Desktop-Collaboration/1",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{self._origin}{API_PREFIX}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        self._ensure_current(generation)
        try:
            with _OPENER.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                self._ensure_current(generation)
                status_code = response.status
                content_type = response.headers.get_content_type()
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            self._ensure_current(generation)
            self._raise_http_error(exc, generation)
            raise AssertionError("unreachable")
        except (urllib.error.URLError, TimeoutError, ssl.SSLError, OSError):
            self._ensure_current(generation)
            raise _network_failed() from None

        self._ensure_current(generation)
        if status_code == 204:
            return None
        if not 200 <= status_code < 300:
            raise _upstream_unavailable()
        if content_type != "application/json":
            raise _upstream_invalid()
        if len(raw) > MAX_RESPONSE_BYTES:
            raise _upstream_invalid()
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise _upstream_invalid() from None

    def _raise_http_error(
        self, exc: urllib.error.HTTPError, generation: int
    ) -> None:
        try:
            if 300 <= exc.code < 400:
                raise _upstream_redirect() from None
            if exc.code == 401:
                self._invalidate(generation)
                raise _auth_failed() from None
            if exc.code in (404, 409, 422):
                code, details = _read_upstream_error(exc)
                if code == "AUTH_REQUIRED":
                    self._invalidate(generation)
                raise _safe_upstream_error(code, details, exc.code) from None
            if exc.code == 403:
                raise _error(
                    403,
                    "COLLABORATION_FORBIDDEN",
                    "在线协作服务拒绝了该操作",
                ) from None
            raise _upstream_unavailable() from None
        finally:
            try:
                exc.close()
            except OSError:
                pass


def _read_upstream_error(
    exc: urllib.error.HTTPError,
) -> tuple[str | None, dict[str, Any] | None]:
    try:
        try:
            raw = exc.read(MAX_ERROR_BYTES + 1)
        finally:
            exc.close()
        if len(raw) > MAX_ERROR_BYTES:
            return None, None
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            return None, None
        error = payload.get("error")
        if not isinstance(error, dict):
            return None, None
        code = error.get("code")
        details = error.get("details")
        if not isinstance(code, str):
            code = None
        if not isinstance(details, dict):
            details = None
        return code, details
    except Exception:
        # Never let an untrusted error body escape as text or break the
        # sanitized mapping above.
        return None, None


def _normalize_origin(
    origin: str | None,
) -> tuple[str | None, str, str | None]:
    if origin is None or not origin.strip():
        return (
            None,
            "COLLABORATION_NOT_CONFIGURED",
            "未配置在线协作服务地址，请联系部署方",
        )
    text = origin.strip()
    if (
        any(char.isspace() or ord(char) < 33 or char == "\\" for char in text)
        or "?" in text
        or "#" in text
    ):
        return (
            None,
            "COLLABORATION_ORIGIN_INVALID",
            "在线协作服务地址只能是 HTTPS 源，不能包含路径、查询或凭据",
        )
    try:
        parsed = urlsplit(text)
        port = parsed.port
    except ValueError:
        return (
            None,
            "COLLABORATION_ORIGIN_INVALID",
            "在线协作服务地址配置不合法，请联系部署方",
        )
    if parsed.scheme.lower() != "https":
        return (
            None,
            "COLLABORATION_ORIGIN_INVALID",
            "在线协作服务地址必须使用 HTTPS，请联系部署方",
        )
    if not parsed.hostname:
        return (
            None,
            "COLLABORATION_ORIGIN_INVALID",
            "在线协作服务地址配置不合法，请联系部署方",
        )
    if (
        parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        return (
            None,
            "COLLABORATION_ORIGIN_INVALID",
            "在线协作服务地址只能是 HTTPS 源，不能包含路径、查询或凭据",
        )
    if port is not None and not 1 <= port <= 65535:
        return (
            None,
            "COLLABORATION_ORIGIN_INVALID",
            "在线协作服务地址配置不合法，请联系部署方",
        )
    return f"https://{parsed.netloc}", "COLLABORATION_READY", None


def create_collaboration_proxy() -> CollaborationProxy:
    """Build the process-memory proxy; this performs no network request."""
    return CollaborationProxy(os.environ.get("APP_COLLABORATION_API_ORIGIN"))


def _proxy(request: Request) -> CollaborationProxy:
    proxy = getattr(request.app.state, "collaboration_proxy", None)
    if proxy is None:
        raise _not_configured()
    return proxy


collaboration_router = APIRouter(
    prefix="/api/local/collaboration",
    tags=["collaboration-proxy"],
)


@collaboration_router.get("/status", response_model=StatusOut)
def collaboration_status(
    proxy: CollaborationProxy = Depends(_proxy),
) -> StatusOut:
    return proxy.status()


@collaboration_router.post("/connect", response_model=StatusOut)
def collaboration_connect(
    data: ConnectIn,
    proxy: CollaborationProxy = Depends(_proxy),
) -> StatusOut:
    return proxy.connect(
        data.credential,
        data.expected_teacher_id,
        data.expected_school_id,
    )


@collaboration_router.post("/disconnect", response_model=StatusOut)
def collaboration_disconnect(
    proxy: CollaborationProxy = Depends(_proxy),
) -> StatusOut:
    return proxy.disconnect()


@collaboration_router.get("/classes", response_model=list[ClassOut])
def collaboration_classes(
    proxy: CollaborationProxy = Depends(_proxy),
) -> list[ClassOut]:
    return proxy.classes()


@collaboration_router.get("/class", response_model=MembershipEnvelope)
def collaboration_membership(
    proxy: CollaborationProxy = Depends(_proxy),
) -> MembershipEnvelope:
    return MembershipEnvelope(membership=proxy.membership())


@collaboration_router.put("/class", response_model=MembershipOut)
def collaboration_select_class(
    data: SelectClassIn,
    proxy: CollaborationProxy = Depends(_proxy),
) -> MembershipOut:
    return proxy.select_class(data.class_id)


@collaboration_router.delete("/class", response_model=RemoveClassOut)
def collaboration_leave_class(
    proxy: CollaborationProxy = Depends(_proxy),
) -> RemoveClassOut:
    proxy.leave_class()
    return RemoveClassOut(removed=True)


@collaboration_router.get("/classmates", response_model=list[ClassmateOut])
def collaboration_classmates(
    proxy: CollaborationProxy = Depends(_proxy),
) -> list[ClassmateOut]:
    return proxy.classmates()


@collaboration_router.get("/game-config", response_model=ConfigCurrentOut)
def collaboration_game_config(
    proxy: CollaborationProxy = Depends(_proxy),
) -> ConfigCurrentOut:
    return proxy.own_config()


@collaboration_router.put("/game-config", response_model=ConfigSaveOut)
def collaboration_save_game_config(
    data: SaveGameConfigIn,
    proxy: CollaborationProxy = Depends(_proxy),
) -> ConfigSaveOut:
    return proxy.save_config(data)


@collaboration_router.post(
    "/game-config/preview", response_model=ConfigPreviewOut
)
def collaboration_preview_game_config(
    data: PreviewImportIn,
    proxy: CollaborationProxy = Depends(_proxy),
) -> ConfigPreviewOut:
    return proxy.preview_import(data)


@collaboration_router.post(
    "/game-config/confirm", response_model=ConfigConfirmOut
)
def collaboration_confirm_game_config(
    data: ConfirmImportIn,
    proxy: CollaborationProxy = Depends(_proxy),
) -> ConfigConfirmOut:
    return proxy.confirm_import(data)


@collaboration_router.get(
    "/game-config/operations/{request_id}",
    response_model=OperationOut,
)
def collaboration_game_config_operation(
    request_id: UUID,
    proxy: CollaborationProxy = Depends(_proxy),
) -> OperationOut:
    return proxy.operation(request_id)
