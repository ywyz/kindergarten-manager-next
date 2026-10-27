"""Local app factory and per-launch API guard.

Hard rules (D1A spec §2), carried over from the verified D0 probe:
- the service binds loopback only and is created with the exact
  ``host:port`` Host and ``http://host:port`` origin of this one launch;
- every ``/api`` request must carry that Host; mutating requests must carry
  the exact Origin; everything except the liveness health check requires
  the per-launch ``X-App-Session`` token (constant-time compare);
- the token lives in memory only and never reaches a URL, log or table;
- public docs are disabled, no CORS is added, and unhandled failures never
  expose SQL, paths or session material.
"""

from __future__ import annotations

import hmac
import secrets
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.local.api import exports_router, local_router, plans_router
from app.local.errors import LocalError
from app.local.observation_api import observations_router
from app.local.runtime import LocalRuntime
from app.local.schemas import LocalHealthOut

SESSION_HEADER = "X-App-Session"
LOCAL_HEALTH_PATH = "/api/local/health"
_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _matches(supplied: str | None, expected: str) -> bool:
    if not supplied:
        return False
    try:
        return hmac.compare_digest(
            supplied.encode("utf-8", "replace"), expected.encode("utf-8")
        )
    except (UnicodeError, TypeError):
        return False


def _error(
    status_code: int,
    code: str,
    message: str,
    *,
    details: dict | None = None,
) -> JSONResponse:
    body: dict = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return JSONResponse(
        status_code=status_code,
        content=body,
        headers={"Cache-Control": "no-store"},
    )


def create_local_app(
    *,
    data_dir: str | Path | None = None,
    port: int,
    session_token: str,
    host: str = "127.0.0.1",
    runtime: LocalRuntime | None = None,
    executor: object | None = None,
) -> FastAPI:
    """Create the local API for one launch (loopback host/port fixed)."""
    if not port or not session_token:
        raise ValueError("local app requires a port and a per-launch session token")
    if host != "127.0.0.1":
        raise ValueError("local app only supports the loopback host 127.0.0.1")

    runtime = runtime or LocalRuntime(data_dir)
    # Baseline/upgrade with real Alembic before any writable API exists; a
    # refused database state raises here and keeps the original file.
    if not runtime.prepared:
        runtime.prepare()

    app = FastAPI(
        title="Kindergarten Manager Local API",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.runtime = runtime
    app.state.executor = executor
    # An internal, never-returned random scope for this app instance. Adoption
    # preview tokens are bound to it (plus the launch id) so a token minted for
    # one app session is refused by another, even on the same runtime; it is
    # not the session token and is never persisted.
    app.state.session_scope = secrets.token_urlsafe(16)
    expected_host = f"{host}:{port}"
    expected_origin = f"http://{host}:{port}"
    token_ref = session_token  # compared only; never returned, logged or stored

    @app.middleware("http")
    async def local_guard(request: Request, call_next):  # noqa: ANN001
        path = request.url.path
        if not path.startswith("/api"):
            response = await call_next(request)
            return response

        if not _matches(request.headers.get("host"), expected_host):
            return _error(403, "FORBIDDEN_HOST", "请求来源主机不受信任")

        if request.method.upper() in _MUTATING_METHODS:
            if not _matches(request.headers.get("origin"), expected_origin):
                return _error(403, "FORBIDDEN_ORIGIN", "请求来源不受信任")

        if path != LOCAL_HEALTH_PATH:
            if not _matches(request.headers.get(SESSION_HEADER), token_ref):
                return _error(401, "APP_SESSION_REQUIRED", "缺少有效的应用会话")

        response = await call_next(request)
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.get(LOCAL_HEALTH_PATH, response_model=LocalHealthOut)
    def health():
        # Liveness only: no profile, path or session material.
        return {"status": "ok"}

    @app.exception_handler(LocalError)
    async def local_error_handler(_request: Request, exc: LocalError):
        details = getattr(exc, "details", None)
        return _error(exc.status_code, exc.code, exc.message, details=details)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _request: Request, _exc: RequestValidationError
    ):
        return _error(422, "VALIDATION_ERROR", "请求参数不合法")

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(_request: Request, exc: StarletteHTTPException):
        code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(
            exc.status_code, "HTTP_ERROR"
        )
        return _error(exc.status_code, code, "请求的资源不可用")

    @app.exception_handler(Exception)
    async def unexpected_error_handler(_request: Request, _exc: Exception):
        return _error(500, "INTERNAL_ERROR", "本地服务内部错误")

    app.include_router(local_router)
    app.include_router(plans_router)
    app.include_router(exports_router)
    app.include_router(observations_router)
    return app
