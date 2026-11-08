"""Independent FastAPI application factory for online collaboration.

Startup requires explicit PostgreSQL and secret configuration.  It never
creates tables, never falls back to SQLite and is not mounted into the local
desktop app.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from .api import router
from .config import CollaborationSettings
from .errors import CollaborationError


def _no_store_headers() -> dict[str, str]:
    return {"Cache-Control": "no-store"}


def create_collaboration_app(
    settings: CollaborationSettings | None = None,
) -> FastAPI:
    resolved = settings or CollaborationSettings.from_env()
    resolved.validate()
    engine = create_engine(
        resolved.database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=0,
    )
    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    app = FastAPI(
        title="Kindergarten Manager Collaboration",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
    )
    app.state.collab_settings = resolved
    app.state.engine = engine
    app.state.session_factory = session_factory

    @app.middleware("http")
    async def no_store_middleware(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(CollaborationError)
    async def collaboration_error_handler(
        _request: Request, exc: CollaborationError
    ) -> JSONResponse:
        payload = {
            "error": {
                "code": exc.code,
                "message": exc.message,
            }
        }
        if exc.details:
            payload["error"]["details"] = exc.details
        headers = _no_store_headers()
        headers.update(exc.headers)
        return JSONResponse(
            status_code=exc.status_code,
            content=payload,
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Do not echo input values: an invalid credential/token field must
        # not reappear in the response.  Only field locations and error
        # classes are returned.
        errors = [
            {
                "loc": [str(part) for part in error.get("loc", ())],
                "type": str(error.get("type", "value_error")),
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "INVALID_REQUEST",
                    "message": "请求参数无效",
                    "details": {"errors": errors},
                }
            },
            headers=_no_store_headers(),
        )

    @app.exception_handler(SQLAlchemyError)
    async def database_error_handler(
        _request: Request, _exc: SQLAlchemyError
    ) -> JSONResponse:
        # Never expose SQL text, credentials, other rows or driver errors.
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "DATABASE_UNAVAILABLE",
                    "message": "在线协作数据库暂时不可用",
                }
            },
            headers=_no_store_headers(),
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(
        _request: Request, _exc: Exception
    ) -> JSONResponse:
        # Keep arbitrary exception text, SQL and secret material out of the
        # response.
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "服务内部错误",
                }
            },
            headers=_no_store_headers(),
        )

    app.include_router(router)
    return app
