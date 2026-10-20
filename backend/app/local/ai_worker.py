"""D2 W3 spawn worker entry: one immutable network attempt per process.

Engineering spec §4.1. The worker is deliberately tiny and import-safe:

* the *entry script* calls ``multiprocessing.freeze_support()`` before any
  side effect (PyInstaller requirement), and this module has no top-level
  application startup — importing it never opens the database, FastAPI, the
  GUI or the legacy configuration chain;
* the child waits on the IPC pipe first; the parent only sends the bootstrap
  **after** it has assigned the Windows Job Object, so no DNS/TLS work happens
  before the Job exists;
* after ``prepare`` (DNS + TCP + TLS) the worker reports ``ready`` and then
  blocks; it writes an HTTP byte only after the parent's single ``send`` frame,
  and it re-checks the parent-provided absolute ``GetTickCount64`` deadline
  before the write so a sleep that exhausted the budget cannot start a request;
* only JSON ``bytes`` frames cross the pipe (``send_bytes``/``recv_bytes`` with
  an explicit ``maxlength``); no model object is ever pickled. The secret
  reaches this process only inside the bootstrap frame, never in argv or the
  environment.

The transport can be told to use a synthetic resolution + test CA, but that
descriptor can only arrive inside an explicitly synthetic bootstrap built by a
dedicated verification entry; nothing here reads the environment or an
ordinary HTTP request to relax the production network policy.
"""

from __future__ import annotations

import json
from typing import Any

from app.local import ai_transport

HANDSHAKE_TIMEOUT_SECONDS = 5.0
SEND_TIMEOUT_SECONDS = ai_transport.ATTEMPT_BUDGET_MS / 1000.0 + 5.0

_WAIT_OBJECT_0 = 0x00000000
_SYNCHRONIZE = 0x00100000


def _parent_alive(parent_pid: int) -> bool:
    """True while the parent process still runs.

    A child that was created *before* the parent assigned the Job must still
    exit on its own if the parent dies (spec §4.1): the pipe EOF or the 5 s
    handshake timeout covers it, and this check makes that bounded to a
    fraction of a second. Uses only the standard library.
    """
    if parent_pid <= 0:
        return True
    try:
        import ctypes  # noqa: PLC0415
        import ctypes.wintypes as wtypes  # noqa: PLC0415

        kernel32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)
        kernel32.OpenProcess.restype = wtypes.HANDLE
        kernel32.OpenProcess.argtypes = [wtypes.DWORD, wtypes.BOOL, wtypes.DWORD]
        kernel32.WaitForSingleObject.restype = wtypes.DWORD
        kernel32.WaitForSingleObject.argtypes = [wtypes.HANDLE, wtypes.DWORD]
        kernel32.CloseHandle.argtypes = [wtypes.HANDLE]
        handle = kernel32.OpenProcess(_SYNCHRONIZE, False, int(parent_pid))
        if not handle:
            return False
        try:
            return kernel32.WaitForSingleObject(handle, 0) != _WAIT_OBJECT_0
        finally:
            kernel32.CloseHandle(handle)
    except Exception:  # noqa: BLE001 - non-Windows / API failure: keep waiting
        return True


def _wait_for_frame(conn: Any, timeout: float, parent_pid: int) -> bool:
    """Wait for a frame, aborting as soon as the parent is gone."""
    import time  # noqa: PLC0415

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if conn.poll(0.25):
                return True
        except (OSError, ValueError):
            return False
        if not _parent_alive(parent_pid):
            return False
    return False
# Control frames (ready/send/abort) are small; request and response frames are
# one body plus bounded metadata (spec §4.1: 1 MiB body + 16 KiB metadata).
CONTROL_FRAME_MAX = 16 * 1024
REQUEST_FRAME_MAX = ai_transport.REQUEST_MAX_BYTES + 16 * 1024
RESPONSE_FRAME_MAX = ai_transport.RESPONSE_MAX_BYTES + 16 * 1024


def _encode(frame: dict[str, Any]) -> bytes:
    return json.dumps(frame, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _recv(conn: Any, maxlength: int) -> dict[str, Any] | None:
    try:
        raw = conn.recv_bytes(maxlength)
    except (EOFError, OSError):
        return None
    if not isinstance(raw, (bytes, bytearray)):
        return None
    try:
        frame = json.loads(bytes(raw).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(frame, dict):
        return None
    return frame


def _send(conn: Any, frame: dict[str, Any]) -> bool:
    try:
        raw = _encode(frame)
    except (TypeError, ValueError):
        return False
    limit = RESPONSE_FRAME_MAX if frame.get("type") == "result" else CONTROL_FRAME_MAX
    if len(raw) > limit:
        # Never emit an over-cap frame; report a fixed, material-free failure.
        raw = _encode(_result_frame(ai_transport.TransportResult(
            ai_transport.PROVIDER_ERROR, reason="provider_error", detail="frame_too_large"
        )))
    try:
        conn.send_bytes(raw)
        return True
    except (BrokenPipeError, EOFError, OSError, ValueError):
        return False


def _result_frame(result: ai_transport.TransportResult) -> dict[str, Any]:
    return {"type": "result", "result": result.to_wire()}


def run(conn: Any) -> None:
    """The whole worker lifetime for one attempt."""
    import os  # noqa: PLC0415

    parent_pid = os.getppid()
    # 1) Wait for the bootstrap only. No network, no filesystem, no DB yet.
    if not _wait_for_frame(conn, HANDSHAKE_TIMEOUT_SECONDS, parent_pid):
        return
    bootstrap = _recv(conn, REQUEST_FRAME_MAX)
    if bootstrap is None or bootstrap.get("type") != "bootstrap":
        return

    request = bootstrap.get("request")
    deadline_ms = bootstrap.get("deadline_ms")
    if not isinstance(request, dict) or not isinstance(deadline_ms, int):
        _send(conn, _result_frame(ai_transport.TransportResult(
            ai_transport.POLICY, reason="endpoint_blocked", detail="bootstrap 无效"
        )))
        return

    synthetic = bootstrap.get("synthetic")
    resolver = None
    ca_pem = None
    if isinstance(synthetic, dict):
        resolver = synthetic.get("resolution")
        ca_pem = synthetic.get("ca_pem") or None

    # 2) DNS + TCP + TLS. Still no HTTP byte.
    prepared, failure = ai_transport.prepare(
        base_url=str(request.get("base_url") or ""),
        model=str(request.get("model") or ""),
        secret=str(request.get("secret") or ""),
        system_text=str(request.get("system_text") or ""),
        user_text=str(request.get("user_text") or ""),
        deadline_ms=deadline_ms,
        resolver=resolver,
        ca_pem=ca_pem,
    )
    if prepared is None:
        assert failure is not None
        _send(conn, _result_frame(failure))
        return

    _send(conn, {"type": "ready", "remaining_ms": max(deadline_ms - ai_transport.now_ticks(), 0)})

    # 3) Block until the parent's single send (or abort/parent death).
    if not _wait_for_frame(conn, SEND_TIMEOUT_SECONDS, parent_pid):
        prepared.sock.close()
        return
    command = _recv(conn, CONTROL_FRAME_MAX)
    if command is None or command.get("type") != "send":
        prepared.sock.close()
        return

    result = ai_transport.send(prepared, deadline_ms=deadline_ms)
    _send(conn, _result_frame(result))


def worker_entry(conn: Any) -> None:  # pragma: no cover - runs in the child
    """Process target; never raises across the process boundary."""
    try:
        run(conn)
    except BaseException:  # noqa: BLE001 - a crash must not hang the parent
        try:
            _send(conn, _result_frame(ai_transport.TransportResult(
                ai_transport.UNKNOWN, reason="provider_error", detail="worker 内部错误"
            )))
        except Exception:  # noqa: BLE001
            pass
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


__all__ = [
    "CONTROL_FRAME_MAX",
    "REQUEST_FRAME_MAX",
    "RESPONSE_FRAME_MAX",
    "HANDSHAKE_TIMEOUT_SECONDS",
    "SEND_TIMEOUT_SECONDS",
    "run",
    "worker_entry",
]
