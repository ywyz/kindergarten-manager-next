"""Lightweight spawn worker for the weekly AI executor tests.

The spawn target is imported by a fresh interpreter.  Keeping it in a
stdlib-only module means the child does not import SQLAlchemy, FastAPI, the
pytest support package or the whole weekly service test module before it can
answer READY.

Behaviour is selected from the pinned model string (``w3weekly|...``) so every
executor branch can be driven without network.  The functions are moved
verbatim from the service test module.
"""

from __future__ import annotations

import json
import os
import time


def _weekly_trace(event: str, **fields) -> None:
    path = os.environ.get("KGM_WEEKLY_WORKER_TRACE")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {"event": event, "pid": os.getpid(), **fields},
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                + "\n"
            )
    except OSError:
        pass


def _weekly_result_frame(
    kind: str,
    *,
    reason: str | None = None,
    sent: bool = True,
    transient: bool = False,
    http_status: int | None = None,
    candidate=None,
) -> dict:
    return {
        "type": "result",
        "result": {
            "kind": kind,
            "reason": reason,
            "transient_not_sent": transient,
            "sent": sent,
            "http_status": http_status,
            "provider_request_id": "weekly-req",
            "returned_model": "weekly-fake",
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            "candidate_text": (
                json.dumps(candidate, ensure_ascii=False, separators=(",", ":"))
                if candidate is not None
                else None
            ),
            "detail": None,
        },
    }


def _weekly_candidate(payload: dict) -> dict:
    task_type = payload.get("task_type")
    if task_type == "weekly_games_select":
        morning = next(
            (
                game["source_handle"]
                for day in payload.get("days") or []
                for group in day.get("morning_games") or []
                for game in group.get("games") or []
            ),
            None,
        )
        post = next(
            (
                game["source_handle"]
                for day in payload.get("days") or []
                for group in day.get("post_group_games") or []
                for game in group.get("games") or []
            ),
            None,
        )
        return {
            "outdoor_game_slots": {
                "collective_1": (
                    {"kind": "source", "source_handle": morning} if morning else None
                ),
                "collective_2": None,
                "free_choice_1": None,
            },
            "focus_area": {"kind": "source", "source_handle": post} if post else None,
        }
    if task_type == "weekly_materials_generate":
        return {"items": []}
    return {"text": f"1. {task_type} 建议\n2. 第二条建议"}


def _weekly_send(conn, frame: dict) -> bool:
    try:
        conn.send_bytes(json.dumps(frame, ensure_ascii=False).encode("utf-8"))
        return True
    except Exception:  # noqa: BLE001
        return False


def weekly_fake_worker(conn) -> None:
    """Spawned fake provider for the real weekly executor path.

    The pinned model string selects a scripted branch.  Every branch records
    ``ready``/``send`` in the trace file named by ``KGM_WEEKLY_WORKER_TRACE`` so
    the parent can prove transport sends independently of finalize calls.
    """
    try:
        if not conn.poll(5.0):
            return
        bootstrap = json.loads(
            bytes(conn.recv_bytes(8 * 1024 * 1024)).decode("utf-8")
        )
        model = bootstrap["request"]["model"]
        spec = model.split("w3weekly|", 1)[1] if "w3weekly|" in model else "success"
        parts = spec.split("|")
        mode = parts[0]
        payload = json.loads(bootstrap["request"]["user_text"])
        task_type = payload.get("task_type")
        if mode == "pre_send":
            kind = parts[1] if len(parts) > 1 else "not_sent"
            reason = parts[2] if len(parts) > 2 else "connection_unavailable"
            _weekly_trace("pre_send", kind=kind, task_type=task_type)
            _weekly_send(
                conn,
                _weekly_result_frame(
                    kind,
                    reason=reason,
                    sent=False,
                    transient=kind == "not_sent",
                ),
            )
            return
        _weekly_trace("ready", task_type=task_type)
        if not _weekly_send(conn, {"type": "ready", "remaining_ms": 1000}):
            return
        if not conn.poll(30.0):
            return
        try:
            command = json.loads(bytes(conn.recv_bytes(64 * 1024)).decode("utf-8"))
        except Exception:  # noqa: BLE001
            return
        if command.get("type") != "send":
            return
        _weekly_trace("send", task_type=task_type)
        if mode == "mixed_columns":
            candidate = (
                _weekly_candidate(payload)
                if task_type == "weekly_key_week_focus"
                else {"unexpected": "x"}
            )
            _weekly_send(
                conn,
                _weekly_result_frame("success", candidate=candidate),
            )
            return
        if mode == "after_send":
            outcome = parts[1] if len(parts) > 1 else "success"
            if outcome == "silent":
                time.sleep(30.0)
                return
            if outcome in ("auth401", "auth403"):
                _weekly_send(
                    conn,
                    _weekly_result_frame(
                        "auth",
                        reason="auth_rejected",
                        http_status=401 if outcome == "auth401" else 403,
                    ),
                )
                return
            if outcome == "rate_limit":
                _weekly_send(
                    conn,
                    _weekly_result_frame(
                        "rate_limited", reason="rate_limited", http_status=429
                    ),
                )
                return
            if outcome == "provider_error":
                _weekly_send(
                    conn,
                    _weekly_result_frame(
                        "provider_error", reason="provider_error", http_status=503
                    ),
                )
                return
            if outcome == "invalid":
                _weekly_send(
                    conn,
                    _weekly_result_frame("success", candidate={"unexpected": "x"}),
                )
                return
            if outcome == "truncated":
                try:
                    conn.send_bytes(b'{"type": "res')
                except Exception:  # noqa: BLE001
                    pass
                time.sleep(30.0)
                return
        _weekly_send(
            conn,
            _weekly_result_frame("success", candidate=_weekly_candidate(payload)),
        )
    except Exception:  # noqa: BLE001
        pass
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass
