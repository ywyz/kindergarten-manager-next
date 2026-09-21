from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings
from app.routers import admin, auth, settings as settings_router
from app.security import is_safe_origin

app = FastAPI(title=settings.app_name)


@app.middleware("http")
async def security_headers_and_body_check(request: Request, call_next):
    path: str = request.url.path
    method = request.method

    # Enforce JSON payloads before body parsing for all mutating API routes.
    if method in ("POST", "PATCH", "PUT", "DELETE") and path.startswith("/api"):
        content_type = request.headers.get("content-type", "")
        media_type = _media_type(content_type)
        if media_type != "application/json":
            return _json_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "VALIDATION_ERROR",
                "请求 Content-Type 必须是 application/json",
            )

        # Require an exact, browser-provided Origin header; no Referer fallback.
        if not is_safe_origin(request):
            return _json_error(
                status.HTTP_403_FORBIDDEN,
                "FORBIDDEN",
                "不允许的来源",
            )

    response = await call_next(request)

    if path.startswith("/api"):
        # Never cache authentication or personal data.
        response.headers.setdefault("Cache-Control", "no-store")

    return response


app.include_router(auth.router, prefix="/api")
app.include_router(settings_router.router, prefix="/api")
app.include_router(admin.router, prefix="/api")


@app.get("/health")
def health() -> dict[str, str]:
    """Process liveness only; does not access MySQL or external services."""
    return {"status": "ok"}


_ERROR_MESSAGES = {
    401: "需要登录或凭证无效",
    403: "没有权限",
    404: "资源不存在",
    409: "数据冲突",
    422: "请求参数校验失败",
    429: "请求过于频繁",
    503: "服务暂不可用",
}


def _media_type(content_type: str) -> str | None:
    if not content_type:
        return None
    return content_type.split(";")[0].strip().lower() or None


def _error_body(code: str, message: str, fields: dict | None = None) -> dict:
    body: dict = {"error": {"code": code, "message": message}}
    if fields:
        body["error"]["fields"] = fields
    return body


def _json_error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=_error_body(code, message),
        headers={"Cache-Control": "no-store"},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    fields: dict[str, str] = {}
    for err in exc.errors():
        loc = err.get("loc", [])
        if loc:
            field = loc[-1]
            fields[str(field)] = err.get("msg", "invalid")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=_error_body(
            "VALIDATION_ERROR", "请求参数校验失败", fields if fields else None
        ),
        headers={"Cache-Control": "no-store"},
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    code = exc.detail
    message = _ERROR_MESSAGES.get(exc.status_code, exc.detail)
    if isinstance(exc.detail, dict):
        code = exc.detail.get("code", exc.detail)
        message = exc.detail.get("message", message)

    headers = dict(exc.headers) if exc.headers else None
    if headers is None:
        headers = {"Cache-Control": "no-store"}
    else:
        headers.setdefault("Cache-Control", "no-store")
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_body(str(code), str(message)),
        headers=headers,
    )


@app.exception_handler(SQLAlchemyError)
@app.exception_handler(RuntimeError)
async def database_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return _json_error(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "SERVICE_UNAVAILABLE",
        "服务暂不可用",
    )
