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
# Vision is a separately versioned frame bound; the old text bound stays.
VISION_REQUEST_FRAME_MAX = ai_transport.VISION_IPC_FRAME_MAX


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


def _recv_with_size(conn: Any, maxlength: int) -> tuple[dict[str, Any] | None, int]:
    try:
        raw = conn.recv_bytes(maxlength)
    except (EOFError, OSError):
        return None, 0
    if not isinstance(raw, (bytes, bytearray)):
        return None, 0
    size = len(raw)
    try:
        frame = json.loads(bytes(raw).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, size
    if not isinstance(frame, dict):
        return None, size
    return frame, size


PROGRESS_CHUNK_CHARS = 2000


def _progress_chunks(text: str) -> list[str]:
    """Split display text so one JSON-encoded progress frame stays bounded.

    A CJK character is 3 UTF-8 bytes, an astral one 4, and a JSON-escaped
    control character 6; 2000 characters therefore stay below the 16 KiB
    control-frame cap even with metadata. The final result is never affected.
    """
    return [
        text[i : i + PROGRESS_CHUNK_CHARS]
        for i in range(0, len(text), PROGRESS_CHUNK_CHARS)
    ] or [""]


def _send(conn: Any, frame: dict[str, Any]) -> bool:
    try:
        raw = _encode(frame)
    except (TypeError, ValueError):
        return False
    limit = RESPONSE_FRAME_MAX if frame.get("type") == "result" else CONTROL_FRAME_MAX
    if len(raw) > limit:
        if frame.get("type") == "progress":
            # Display-only progress must never be turned into a fake final
            # result; dropping one update is safe and the final result frame
            # carries the authoritative outcome.
            return False
        # Never emit an over-cap result/control frame; report a fixed,
        # material-free failure.
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


VISION_TASK_TYPES = (
    "game_observation_generate",
    "game_observation_rewrite",
)
VISION_SCHEMA_VERSION = 1
VISION_CONTRACT_VERSIONS = (1,)


def validate_vision_header(header: Any) -> bool:
    """Header-only contract check; must run before waiting for any body."""
    if not isinstance(header, dict) or header.get("type") != "bootstrap_header":
        return False
    if header.get("vision") is not True:
        return False
    if header.get("protocol") != ai_transport.VISION_PROTOCOL_ID:
        return False
    if header.get("schema_version") != VISION_SCHEMA_VERSION:
        return False
    if header.get("source_kind") != "game_observation":
        return False
    if header.get("task_type") not in VISION_TASK_TYPES:
        return False
    if header.get("contract_version") not in VISION_CONTRACT_VERSIONS:
        return False
    image_count = header.get("image_count")
    if (
        not isinstance(image_count, int)
        or isinstance(image_count, bool)
        or not 1 <= image_count <= ai_transport.VISION_MAX_IMAGES
    ):
        return False
    frame_size = header.get("frame_size")
    if (
        not isinstance(frame_size, int)
        or isinstance(frame_size, bool)
        or not 1 <= frame_size <= ai_transport.VISION_IPC_FRAME_MAX
    ):
        return False
    return True


def validate_vision_bootstrap(
    header: Any, request: Any, image_urls: Any, actual_body_size: Any = None
) -> bool:
    """Pure restricted-claim check used by the worker before any network."""
    if not validate_vision_header(header):
        return False
    if not isinstance(image_urls, list) or len(image_urls) > ai_transport.VISION_MAX_IMAGES:
        return False
    if header.get("image_count") != len(image_urls):
        return False
    frame_size = header.get("frame_size")
    if actual_body_size is not None and frame_size != actual_body_size:
        return False
    if any(
        not isinstance(item, str) or not item.startswith("data:image/")
        for item in image_urls
    ):
        return False
    if not isinstance(request, dict) or request.get("protocol") != ai_transport.VISION_PROTOCOL_ID:
        return False
    meta = request.get("vision")
    if not isinstance(meta, dict):
        return False
    for key in (
        "protocol",
        "schema_version",
        "source_kind",
        "task_type",
        "contract_version",
        "image_count",
    ):
        if meta.get(key) != header.get(key):
            return False
    return True


def run(conn: Any) -> None:
    """The whole worker lifetime for one attempt."""
    import os  # noqa: PLC0415

    parent_pid = os.getppid()
    # 1) Wait for the bootstrap header only.  A text bootstrap is a single
    # frame capped by the unchanged 1 MiB receive bound; a vision bootstrap
    # must first prove its restricted claim metadata in a small header frame
    # before the worker accepts the larger body frame.
    if not _wait_for_frame(conn, HANDSHAKE_TIMEOUT_SECONDS, parent_pid):
        return
    first, _first_size = _recv_with_size(conn, REQUEST_FRAME_MAX)
    if first is None:
        return
    if first.get("type") == "bootstrap_header":
        header = first
        if not validate_vision_header(header):
            _send(conn, _result_frame(ai_transport.TransportResult(
                ai_transport.POLICY, reason="endpoint_blocked", detail="vision_not_authorized"
            )))
            return
        bootstrap, body_size = _recv_with_size(conn, VISION_REQUEST_FRAME_MAX)
        if bootstrap is None or bootstrap.get("type") != "bootstrap":
            _send(conn, _result_frame(ai_transport.TransportResult(
                ai_transport.POLICY, reason="endpoint_blocked", detail="vision_bootstrap_invalid"
            )))
            return
        request = bootstrap.get("request")
        image_urls = request.get("image_urls") if isinstance(request, dict) else None
        if not validate_vision_bootstrap(
            header, request, image_urls, actual_body_size=body_size
        ):
            _send(conn, _result_frame(ai_transport.TransportResult(
                ai_transport.POLICY, reason="endpoint_blocked", detail="vision_not_authorized"
            )))
            return
    else:
        bootstrap = first
        first_request = first.get("request")
        if isinstance(first_request, dict) and first_request.get(
            "protocol"
        ) == ai_transport.VISION_PROTOCOL_ID:
            _send(conn, _result_frame(ai_transport.TransportResult(
                ai_transport.POLICY, reason="endpoint_blocked", detail="vision_header_required"
            )))
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

    vision = request.get("protocol") == ai_transport.VISION_PROTOCOL_ID
    if vision and not ai_transport.vision_capability(
        request.get("base_url"), request.get("model")
    ):
        _send(conn, _result_frame(ai_transport.TransportResult(
            ai_transport.POLICY, reason="endpoint_blocked", detail="vision_not_authorized"
        )))
        return
    if vision:
        image_urls = request.get("image_urls")
        if (
            not isinstance(image_urls, list)
            or len(image_urls) > ai_transport.VISION_MAX_IMAGES
            or any(
                not isinstance(item, str) or not item.startswith("data:image/")
                for item in image_urls
            )
        ):
            _send(conn, _result_frame(ai_transport.TransportResult(
                ai_transport.POLICY, reason="endpoint_blocked", detail="vision_bootstrap_invalid"
            )))
            return
        try:
            body = ai_transport.build_vision_request(
                model=str(request.get("model") or ""),
                system_text=str(request.get("system_text") or ""),
                user_text=str(request.get("user_text") or ""),
                image_urls=image_urls,
            )
        except ValueError:
            _send(conn, _result_frame(ai_transport.TransportResult(
                ai_transport.POLICY, reason="endpoint_blocked", detail="vision_bootstrap_invalid"
            )))
            return
    else:
        body = None

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
        body=body,
        request_body_max=(
            ai_transport.VISION_BODY_MAX_BYTES if vision else ai_transport.REQUEST_MAX_BYTES
        ),
        request_total_max=(
            ai_transport.VISION_HTTP_MAX_BYTES
            if vision
            else ai_transport.REQUEST_MAX_BYTES + 4096
        ),
    )
    if prepared is None:
        assert failure is not None
        _send(conn, _result_frame(failure))
        return

    _send(conn, {"type": "ready", "remaining_ms": max(deadline_ms - ai_transport.now_ticks(), 0)})

    # 3) Block until the parent's single send (or abort/parent death).
    send_timeout = (
        ai_transport.VISION_ATTEMPT_BUDGET_MS if vision else ai_transport.ATTEMPT_BUDGET_MS
    ) / 1000.0 + 5.0
    if not _wait_for_frame(conn, send_timeout, parent_pid):
        prepared.sock.close()
        return
    command = _recv(conn, CONTROL_FRAME_MAX)
    if command is None or command.get("type") != "send":
        prepared.sock.close()
        return

    # Streaming progress: coalesce high-frequency deltas into small bounded
    # control frames. Only display text crosses the pipe; the final result is a
    # separate frame and the parent re-validates everything.
    import time as _time  # noqa: PLC0415

    progress = {"seq": 0, "reasoning": [], "content_chars": 0, "last": 0.0}

    def flush_progress(phase: str) -> None:
        text = "".join(progress["reasoning"])
        progress["reasoning"].clear()
        progress["last"] = _time.monotonic()
        # Split very large deltas so a control frame never approaches its cap
        # in UTF-8 bytes (CJK 3 bytes/char, astral 4, JSON-escaped control 6).
        chunks = _progress_chunks(text)
        for chunk in chunks:
            progress["seq"] += 1
            _send(
                conn,
                {
                    "type": "progress",
                    "seq": progress["seq"],
                    "phase": phase,
                    "reasoning": chunk,
                    "content_chars": progress["content_chars"],
                },
            )

    def on_progress(reasoning: str, content: str) -> None:
        if reasoning:
            progress["reasoning"].append(reasoning)
        if content:
            progress["content_chars"] += len(content)
        pending_chars = sum(len(item) for item in progress["reasoning"])
        if pending_chars >= 4096 or _time.monotonic() - progress["last"] >= 0.1:
            flush_progress("thinking" if progress["reasoning"] else "generating")

    def on_heartbeat() -> None:
        # A real SSE keepalive updates only the "last supplier data" clock; it
        # never changes the phase, fabricates reasoning or resets the deadline.
        progress["seq"] += 1
        _send(
            conn,
            {
                "type": "progress",
                "seq": progress["seq"],
                "phase": "heartbeat",
                "heartbeat": True,
                "reasoning": "",
                "content_chars": progress["content_chars"],
            },
        )

    result = ai_transport.send(
        prepared,
        deadline_ms=deadline_ms,
        on_progress=on_progress,
        on_heartbeat=on_heartbeat,
    )
    if progress["reasoning"]:
        flush_progress("thinking")
    # A short "validating" phase before the final result frame (display only).
    progress["seq"] += 1
    _send(
        conn,
        {
            "type": "progress",
            "seq": progress["seq"],
            "phase": "validating",
            "reasoning": "",
            "content_chars": progress["content_chars"],
        },
    )
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
    "VISION_REQUEST_FRAME_MAX",
    "VISION_CONTRACT_VERSIONS",
    "VISION_SCHEMA_VERSION",
    "VISION_TASK_TYPES",
    "HANDSHAKE_TIMEOUT_SECONDS",
    "SEND_TIMEOUT_SECONDS",
    "validate_vision_bootstrap",
    "validate_vision_header",
    "run",
    "worker_entry",
]
