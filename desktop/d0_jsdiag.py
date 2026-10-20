"""Isolated JS-bridge diagnosis for the D0 automated driver.

Diagnostic output records only boolean/error state. The raw per-launch
session token is never written to this file or printed (R9): the session
probe is reduced with :func:`session_diag`, which keeps only whether a token
was present.
"""

import argparse
import json
import time

import webview

import d0_paths
from d0_driver import _wait_page_ready
from d0_main import build_runtime


def session_diag(session) -> dict:
    """Reduce a host ``get_session`` reply to a token-free summary."""
    has_token = bool(isinstance(session, dict) and session.get("launch_token"))
    return {"has_token": has_token}


def task():
    window = webview.windows[0]
    lines: list[str] = []

    def ev(expr):
        try:
            value = window.evaluate_js(expr)
            lines.append(f"{expr[:60]} -> {value!r}")
        except Exception as exc:
            lines.append(f"{expr[:60]} !! {exc!r}")

    _wait_page_ready(window, 30)
    ev("typeof window.__d0")
    ev("!!window.__d0PageReady")
    ev("document.readyState")
    ev("document.title")
    ev("typeof window.pywebview")
    ev("typeof window.pywebview && typeof window.pywebview.api")
    ev("!!(window.pywebview && window.pywebview.api && typeof window.pywebview.api.get_session === 'function')")
    # Await the host session, but keep only the boolean readiness summary.
    try:
        window.evaluate_js(
            "window.__z1 = null; window.pywebview.api.get_session()"
            ".then(v => {window.__z1 = JSON.stringify({has_token: !!(v && v.launch_token)});})"
            ".catch(e => {window.__z1 = 'ERR';});"
        )
        for _ in range(50):
            time.sleep(0.2)
            value = window.evaluate_js("window.__z1")
            if value is not None:
                lines.append(f"session_bridge -> {value!r}")
                break
        else:
            lines.append("session_bridge timeout")
    except Exception as exc:
        lines.append(f"session_bridge !! {exc!r}")
    ev("typeof window.__d0")
    try:
        value = window.evaluate_js("window.__d0.collectSession()")
        lines.append(f"direct collectSession -> {session_diag(value)!r}")
    except Exception as exc:
        lines.append(f"direct collectSession !! {exc!r}")
    from d0_driver import _await_js

    try:
        value = _await_js(window, "1+1", timeout=6)
        lines.append(f"_await_js 1+1 -> {value!r}")
    except Exception as exc:
        lines.append(f"_await_js 1+1 !! {exc!r}")
    try:
        value = _await_js(window, "window.__d0.collectSession()", timeout=12)
        lines.append(f"_await_js collectSession -> {session_diag(value)!r}")
    except Exception as exc:
        lines.append(f"_await_js collectSession !! {exc!r}")
    ev("!!window.__d0Done")

    out = d0_paths.REPO_ROOT / "build" / "desktop-d0" / "diag" / "jsdiag.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(lines, ensure_ascii=False, indent=1), encoding="utf-8")
    window.destroy()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--frontend", default=None)
    parser.add_argument("--data", default=None)
    args = parser.parse_args()
    service, host_api, probe = build_runtime(args)
    try:
        if service.start_and_wait():
            webview.create_window(
                "D0 js 诊断",
                f"http://127.0.0.1:{service.port}/",
                js_api=host_api,
                width=1000,
                height=700,
                text_select=True,
            )
            try:
                webview.start(func=task)
            finally:
                service.stop()
    finally:
        probe.close()
