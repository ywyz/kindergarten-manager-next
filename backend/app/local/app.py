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
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.local.api import exports_router, local_router, plans_router
from app.local.collaboration_proxy import (
    collaboration_router,
    create_collaboration_proxy,
)
from app.local.curriculum_api import curriculum_router
from app.local.directional_revision_api import (
    router as directional_revision_router,
)
from app.local.errors import LocalError
from app.local.listening_api import listening_router
from app.local.listening_export_api import listening_exports_router
from app.local.listening_export_service import ListeningExportManager
from app.local.listening_ai_api import router as listening_ai_router
from app.local.observation_api import observations_router
from app.local.observation_export_api import observation_exports_router
from app.local.runtime import LocalRuntime
from app.local.schemas import LocalHealthOut
from app.local.todo_api import todos_router
from app.local.weekly_plan_api import weekly_plans_router
from app.local.weekly_ai_api import weekly_ai_router
from app.local.weekly_plan_export_api import weekly_exports_router
from app.local.weekly_collaboration_export import (
    router as weekly_collaboration_export_router,
)

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


def initialize_prompt_package(
    runtime: LocalRuntime,
    *,
    client_version: str | None = None,
) -> object:
    """Synchronously verify/enable the package before an executor can claim.

    The desktop host calls this immediately after ``runtime.prepare()`` (and
    after restore reopen) and before starting the AI executor.  It is
    idempotent: a second app build reuses the already initialized service.
    """
    from app.local.prompt_package_service import PromptPackageService

    existing = getattr(runtime, "prompt_package_service", None)
    if existing is not None:
        return existing
    service = PromptPackageService(
        runtime,
        client_version=client_version or getattr(runtime, "app_version", None),
    )
    runtime.prompt_package_service = service
    runtime.prompt_package_restore_hook = service.startup
    try:
        service.startup()
    except Exception:  # noqa: BLE001 - package failure never blocks launch
        pass
    return service


def create_local_app(
    *,
    data_dir: str | Path | None = None,
    port: int,
    session_token: str,
    host: str = "127.0.0.1",
    runtime: LocalRuntime | None = None,
    executor: object | None = None,
    prompt_package_client_version: str | None = None,
) -> FastAPI:
    """Create the local API for one launch (loopback host/port fixed).

    ``prompt_package_client_version`` lets the desktop entry pass its actual
    stable/preview identity without adding a readable package-resource field.
    Source runs keep the deterministic packaged default.
    """
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
    # Prompt-package cache verification is local-only.  It re-applies a cached
    # package after a database restore before any AI request can run; an
    # unconfigured source performs no network and leaves built-in guidance.
    prompt_package = initialize_prompt_package(
        runtime,
        client_version=prompt_package_client_version,
    )
    app.state.prompt_package = prompt_package
    # No network at startup: this only reads the deployment-configured HTTPS
    # origin and creates the process-memory collaboration session holder.
    app.state.collaboration_proxy = create_collaboration_proxy()
    # An internal, never-returned random scope for this app instance. Adoption
    # preview tokens are bound to it (plus the launch id) so a token minted for
    # one app session is refused by another, even on the same runtime; it is
    # not the session token and is never persisted.
    app.state.session_scope = secrets.token_urlsafe(16)
    if not getattr(runtime, "launch_id", None):
        runtime.launch_id = str(uuid.uuid4())
    # Listening export previews/exports live only in this app generation and
    # are invalidated when the runtime launch id changes.
    previous_listening = getattr(runtime, "listening_export_manager", None)
    if previous_listening is not None:
        previous_listening.retire()
    app.state.listening_export_manager = ListeningExportManager(
        runtime, launch_id=str(runtime.launch_id)
    )
    runtime.listening_export_manager = app.state.listening_export_manager
    # Bind the one fixed manager for this app generation before any API can
    # serve; D's manager is constructed from the runtime/launch/scope only.
    app.state.weekly_export_manager = runtime.bind_weekly_exports(
        launch_id=str(runtime.launch_id),
        session_scope=app.state.session_scope,
    )
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
    app.include_router(curriculum_router)
    app.include_router(directional_revision_router)
    app.include_router(todos_router)
    app.include_router(plans_router)
    app.include_router(exports_router)
    app.include_router(observations_router)
    app.include_router(observation_exports_router)
    app.include_router(listening_router)
    app.include_router(listening_ai_router)
    app.include_router(listening_exports_router)
    app.include_router(weekly_plans_router)
    app.include_router(weekly_ai_router)
    app.include_router(weekly_exports_router)
    app.include_router(collaboration_router)
    app.include_router(weekly_collaboration_export_router)
    # Rate-limited and disabled entirely when the build has no fixed trust
    # source.  It runs after the app is fully built and never blocks launch.
    prompt_package.start_background_check()
    return app
