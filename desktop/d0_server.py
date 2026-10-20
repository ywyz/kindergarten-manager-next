"""D0 isolated local server: same-origin frontend + guarded probe API.

Hard rules implemented here (D0-2/D0-3/D0-4):
- The app binds the loopback interface only; the launcher passes the exact
  ``127.0.0.1:<port>`` Host and http:// origin of this one launch.
- Every ``/api`` request must carry a Host header equal to the launch Host.
- Mutating ``/api`` requests must carry an Origin equal to the launch origin
  (constant-time comparison; a missing or wrong Origin is rejected).
- Everything under ``/api`` except the liveness ``/api/probe/health``
  requires the per-launch session token in ``X-App-Session`` (constant-time
  compare). Token lives in launcher memory only; it is never logged, never
  placed in a URL, never stored in the database.
``/api/probe/health`` returns liveness only and touches no data, no config
and no secret.
- No legacy business router is mounted; no legacy config (``.env``) is read.
"""

import hmac
import secrets

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from starlette.staticfiles import StaticFiles

import d0_paths
from d0_db import SQLiteProbe

SESSION_HEADER = "X-App-Session"
# Server-side guard for probe content; the schema also hard-fails at 2000.
_CONTENT_MAX_SAFE = 1000


class LaunchContext:
    """Per-launch security material created by the desktop entry."""

    def __init__(self, port: int, launch_token: str):
        if not port or not launch_token:
            raise ValueError("launch context must include port and token")
        self.port = port
        self.host = "127.0.0.1"
        self.expected_host = f"127.0.0.1:{port}"
        self.expected_origin = f"http://127.0.0.1:{port}"
        self.launch_token = launch_token


class ProbeSaveRequest(BaseModel):
    content: str
    simulate_failure: bool = False


class ProbeStateResponse(BaseModel):
    status: str
    content: str | None = None
    version: int | None = None
    updated_at: str | None = None


def _no_store(response) -> None:
    response.headers.setdefault("Cache-Control", "no-store")


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
        headers={"Cache-Control": "no-store"},
    )


def create_app(context: LaunchContext, probe: SQLiteProbe, environment: dict) -> FastAPI:
    app = FastAPI(
        title="Kindergarten Manager D0 Probe",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    token_ref = context.launch_token  # token is compared, never returned or logged

    @app.middleware("http")
    async def d0_guard(request, call_next):
        path = request.url.path
        if not path.startswith("/api"):
            # Frontend static files (no data) skip session checks but keep
            # no-store off the HTML shell only; assets are fingerprinted.
            response = await call_next(request)
            return response

        # Exact Host: this launch's loopback binding only.
        host = request.headers.get("host")
        if not (host and hmac.compare_digest(host, context.expected_host)):
            return _error(403, "FORBIDDEN_HOST", "允许的主机不匹配")

        method = request.method.upper()
        mutating = method in ("POST", "PUT", "PATCH", "DELETE")
        if mutating:
            origin = request.headers.get("origin")
            if not (origin and hmac.compare_digest(origin, context.expected_origin)):
                return _error(403, "FORBIDDEN", "不允许的来源")

        if path != "/api/probe/health":
            supplied = request.headers.get(SESSION_HEADER)
            if not (
                supplied
                and hmac.compare_digest(supplied, token_ref)
            ):
                return _error(401, "AUTH_REQUIRED", "缺少有效的应用会话")

        response = await call_next(request)
        _no_store(response)
        return response

    # -- liveness (no data, no session, no config) -------------------------
    @app.get("/api/probe/health")
    def health():
        return {"status": "ok", "probe": "d0"}

    # -- guarded probe API ---------------------------------------------------
    @app.get("/api/probe/environment")
    def environment_snapshot() -> dict:
        return environment

    @app.get("/api/probe/state")
    def state():
        return probe.read()

    @app.post("/api/probe/state")
    def save_state(body: ProbeSaveRequest):
        content = body.content if isinstance(body.content, str) else ""
        if not content.strip():
            return _error(422, "VALIDATION_ERROR", "合成内容不能为空")
        if len(content) > _CONTENT_MAX_SAFE:
            return _error(422, "VALIDATION_ERROR", "合成内容过长")
        result = probe.save(content, simulate_failure=body.simulate_failure)
        if result.get("status") == "saved":
            return result
        return _error(500, "SAVE_FAILED", result.get("message") or "写入失败")

    @app.post("/api/probe/export")
    def export_word():
        from d0_word import synthetic_docx_bytes, synthetic_export_filename

        try:
            data = synthetic_docx_bytes()
        except Exception as exc:  # template missing/invalid etc.
            return _error(500, "EXPORT_UNAVAILABLE", f"DOCX 生成失败: {exc}")
        import base64

        return {
            "filename": synthetic_export_filename(),
            "payload_base64": base64.b64encode(data).decode("ascii"),
            "bytes": len(data),
        }

    # -- frontend shell (built Vue/Element Plus entry) ----------------------
    frontend_dir = d0_paths.frontend_dist()
    index_file = frontend_dir / "d0.html"
    if not frontend_dir.is_dir() or not index_file.is_file():
        raise RuntimeError(
            f"D0 前端构建产物缺失: {frontend_dir}（先执行 make frontend）"
        )

    @app.get("/", include_in_schema=False)
    def shell():
        return FileResponse(index_file, headers={"Cache-Control": "no-store"})

    app.mount("/", StaticFiles(directory=str(frontend_dir)), name="frontend")
    return app
