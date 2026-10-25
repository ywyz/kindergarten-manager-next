"""Synthetic new-process fixture for U2 integration tests.

It uses the real LocalRuntime (migration, data lock, SQLite), the real D1
FastAPI/uvicorn service and the real D1HostApi page-ready receipt path.  The
only synthetic part is that no WebView2 window is opened in this fixture; U3
covers the complete source-UI chain.  It is never a product entry point.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DESKTOP = REPO_ROOT / "desktop"
BACKEND = REPO_ROOT / "backend"
for entry in (str(DESKTOP), str(BACKEND)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import d1_host_api  # noqa: E402
import d1_server  # noqa: E402
from app.local.runtime import LocalRuntime  # noqa: E402
from d0_main import ServiceRun  # noqa: E402
from update_identity import load_app_identity  # noqa: E402
from update_install import ReadyReceiptWriter, read_launch_plan_from_env  # noqa: E402


def _free_port() -> int:
    sock = socket.socket()
    try:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
    finally:
        sock.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    parser.add_argument("--credential-root", required=True)
    parser.add_argument("--stop", required=True)
    parser.add_argument("--skip-page-ready", action="store_true")
    args = parser.parse_args()
    plan = read_launch_plan_from_env()
    if plan is None:
        Path(args.stop).write_text("no-plan", encoding="utf-8")
        return 2
    runtime = LocalRuntime(args.data, credential_root=args.credential_root)
    service = None
    try:
        runtime.prepare()
        identity = load_app_identity(
            database_revision=runtime.current_revision or "",
            path=Path(plan.install_app_dir) / "_internal" / "build_identity.json",
            require_packaged=True,
        )
        if identity is None:
            return 6
        port = _free_port()
        token = secrets.token_urlsafe(16)
        app = d1_server.build_d1_app(
            runtime=runtime,
            port=port,
            session_token=token,
            frontend_dir=None,
            executor=None,
        )
        service = ServiceRun(app, port)
        if not service.start_and_wait():
            return 3
        # Real service/page availability: the fixture fetches the actual
        # D1 page bytes before the host page-ready receipt is written.
        import urllib.request

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=10) as page:
            body = page.read()
        if b"<html" not in body.lower():
            return 4
        receipt = ReadyReceiptWriter(
            plan,
            identity=identity,
            runtime=runtime,
            service=service,
            service_port=port,
            verification_context=(
                os.environ.get("KGM_UPDATE_VERIFICATION_CONTEXT") == "1"
            ),
        )
        host = d1_host_api.D1HostApi(
            launch_token=token,
            update_manager=None,
            ready_receipt=receipt,
        )
        bootstrap = host.get_bootstrap()
        if not args.skip_page_ready:
            result = host.page_ready(
                {
                    "bridge_protocol": d1_host_api.BRIDGE_PROTOCOL,
                    "update_install": bootstrap.get("update_install"),
                }
            )
            if not result.get("accepted"):
                return 5
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline and not Path(args.stop).exists():
            time.sleep(0.05)
        return 0
    finally:
        if service is not None:
            service.stop()
        runtime.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
