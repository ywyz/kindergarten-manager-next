"""D1 local app: the reviewed local API factory plus the D1 frontend shell.

The API guard (loopback host, exact Origin on writes, per-launch session
token) comes from ``app.local.app.create_local_app``; this module only adds
the same-origin static shell. No legacy router, no D0 probe page.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from starlette.staticfiles import StaticFiles

import d1_paths
from app.local.app import create_local_app
from app.local.runtime import LocalRuntime


def build_d1_app(
    *,
    runtime: LocalRuntime,
    port: int,
    session_token: str,
    frontend_dir: str | Path | None = None,
    executor: object | None = None,
) -> FastAPI:
    app = create_local_app(
        port=port, session_token=session_token, runtime=runtime, executor=executor
    )
    dist = Path(frontend_dir).resolve() if frontend_dir else d1_paths.frontend_dist()
    index = dist / "d1.html"
    if not dist.is_dir() or not index.is_file():
        raise RuntimeError(
            f"D1 前端构建产物缺失: {dist}（先执行 npm run build:d1）"
        )

    @app.get("/", include_in_schema=False)
    def shell():
        return FileResponse(index, headers={"Cache-Control": "no-store"})

    app.mount("/", StaticFiles(directory=str(dist)), name="frontend")
    return app
