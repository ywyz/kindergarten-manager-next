"""Fake spawn worker for the D2 W3 executor tests.

Runs in a spawned child process. The behaviour is selected from the pinned
``model`` string (``w3fake|mode:...``) so a test can drive every handshake
branch without any network:

* ``result:<kind>:<reason>[:transient]`` — terminal result before any send;
* ``ready_then_result:<delay>[:<candidate_mode>]`` — ready, wait for send,
  then a success (or invalid) result after ``delay`` seconds;
* ``ready_then_silent:<delay>`` — ready, wait for send, never reply;
* ``ready_delay:<delay>|...`` — sleep before sending ready;
* ``exit_after_ready`` — ready then exit (EOF before send);
* ``exit_after_send`` — ready, consume send, then exit (EOF after send).
"""

from __future__ import annotations

import json
import time

VALID_SPLIT = {
    "group_activity": {
        "theme": "秋天的树叶",
        "objectives": "观察树叶",
        "preparation": "树叶若干",
        "key_points": "观察",
        "difficult_points": "比较",
        "process": "一、导入；二、观察；三、比较",
    }
}
INVALID_SPLIT = {"unexpected": "x"}


def never_read_worker(conn):
    """A spawn target that reads nothing at all until it is terminated.

    Used to prove the parent's bootstrap write is bounded: a large frame fills
    the pipe and would block an unbounded ``send_bytes``. It optionally touches
    a marker file (path from the test's own env) so the test can prove the
    child really started.
    """
    import os

    marker = os.environ.get("KGM_W3_NEVER_READ_MARK")
    if marker:
        try:
            with open(marker, "w", encoding="utf-8") as handle:
                handle.write("started")
        except OSError:
            pass
    time.sleep(60.0)
    try:
        conn.close()
    except Exception:  # noqa: BLE001
        pass


def _send(conn, frame):
    try:
        conn.send_bytes(json.dumps(frame, ensure_ascii=False).encode("utf-8"))
        return True
    except Exception:  # noqa: BLE001
        return False


def _result(kind, reason, transient=False, candidate=None):
    return {
        "type": "result",
        "result": {
            "kind": kind,
            "reason": reason,
            "transient_not_sent": transient,
            "sent": kind not in ("not_sent", "stopped", "policy", "tls_invalid"),
            "http_status": None,
            "provider_request_id": "req-test",
            "returned_model": "fake-model",
            "usage": {"prompt_tokens": 1},
            "candidate_text": json.dumps(candidate, ensure_ascii=False) if candidate is not None else None,
            "detail": None,
        },
    }


def fake_worker_entry(conn):
    try:
        if not conn.poll(5.0):
            return
        raw = conn.recv_bytes(8 * 1024 * 1024)
        bootstrap = json.loads(bytes(raw).decode("utf-8"))
        model = bootstrap["request"]["model"]
        spec = model.split("w3fake|", 1)[1] if "w3fake|" in model else "ready_then_result:0"
        segments = [seg for seg in spec.split("|") if seg]

        delay_before_ready = 0.0
        if segments and segments[0].startswith("ready_delay:"):
            delay_before_ready = float(segments[0].split(":", 1)[1])
            segments = segments[1:]
        parts = (segments[0] if segments else "ready_then_result:0").split(":")
        mode = parts[0]

        if delay_before_ready:
            time.sleep(delay_before_ready)

        if mode == "no_read":
            # Never read the bootstrap: a large frame must block the parent's
            # write, which the bounded IPC must survive.
            time.sleep(30.0)
            return

        if mode == "truncated_frame":
            try:
                conn.send_bytes(b'{"type": "rea')  # a complete but invalid frame
            except Exception:  # noqa: BLE001
                pass
            time.sleep(5.0)
            return

        if mode == "result":
            kind = parts[1]
            reason = parts[2] if len(parts) > 2 else None
            transient = len(parts) > 3 and parts[3] == "transient"
            _send(conn, _result(kind, reason, transient))
            return

        if mode == "exit_after_ready":
            _send(conn, {"type": "ready", "remaining_ms": 1000})
            return

        if mode in ("ready_then_result", "ready_then_silent", "exit_after_send"):
            _send(conn, {"type": "ready", "remaining_ms": 1000})
            if not conn.poll(30.0):
                return
            try:
                command = json.loads(bytes(conn.recv_bytes(64 * 1024)).decode("utf-8"))
            except Exception:  # noqa: BLE001
                return
            if command.get("type") != "send":
                return
            if mode == "exit_after_send":
                return
            delay = float(parts[1]) if len(parts) > 1 else 0.0
            if delay:
                time.sleep(delay)
            if mode == "ready_then_silent":
                time.sleep(30.0)
                return
            candidate_mode = parts[2] if len(parts) > 2 else "valid"
            candidate = INVALID_SPLIT if candidate_mode == "invalid" else VALID_SPLIT
            _send(conn, _result("success", None, candidate=candidate))
            return

        # Default: a success after a short delay.
        _send(conn, {"type": "ready", "remaining_ms": 1000})
        if conn.poll(30.0):
            conn.recv_bytes(64 * 1024)
        _send(conn, _result("success", None, candidate=VALID_SPLIT))
    except Exception:  # noqa: BLE001
        pass
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass
