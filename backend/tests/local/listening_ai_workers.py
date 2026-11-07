"""Stdlib-only fake worker for the listening AI executor contract test."""

from __future__ import annotations

import json
import os
import time


def _trace(event: str, **fields) -> None:
    path = os.environ.get("KGM_LISTENING_WORKER_TRACE")
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


def _send(conn, frame: dict) -> bool:
    try:
        conn.send_bytes(json.dumps(frame, ensure_ascii=False).encode("utf-8"))
        return True
    except Exception:  # noqa: BLE001
        return False


def _candidate(payload: dict) -> dict:
    if payload.get("mode") == "group_note":
        return {"text": "孩子说想画太阳。", "uncertainties": ["需核实"]}
    items = [
        {"item_id": item["item_id"], "stars": 2, "basis": "照片/正文可见依据"}
        for item in payload.get("items") or []
    ]
    return {
        "overall_evaluation": "综合评价建议",
        "support_strategy": "支持策略建议",
        "items": items,
    }


def listening_fake_worker(conn) -> None:
    try:
        if not conn.poll(5.0):
            return
        first = json.loads(bytes(conn.recv_bytes(8 * 1024 * 1024)).decode("utf-8"))
        if first.get("type") == "bootstrap_header":
            _trace("vision_header", source_kind=first.get("source_kind"))
            if not conn.poll(5.0):
                return
            bootstrap = json.loads(
                bytes(conn.recv_bytes(36 * 1024 * 1024)).decode("utf-8")
            )
        else:
            bootstrap = first
        request = bootstrap["request"]
        payload = json.loads(request["user_text"])
        _trace("ready", mode=payload.get("mode"), image_count=len(request.get("image_urls") or []))
        if not _send(conn, {"type": "ready", "remaining_ms": 1000}):
            return
        if not conn.poll(30.0):
            return
        command = json.loads(bytes(conn.recv_bytes(64 * 1024)).decode("utf-8"))
        if command.get("type") != "send":
            return
        _trace("send", mode=payload.get("mode"))
        _send(
            conn,
            {
                "type": "result",
                "result": {
                    "kind": "success",
                    "reason": None,
                    "transient_not_sent": False,
                    "sent": True,
                    "http_status": 200,
                    "provider_request_id": "listening-fake",
                    "returned_model": "listening-fake",
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                    "candidate_text": json.dumps(
                        _candidate(payload), ensure_ascii=False
                    ),
                    "detail": None,
                },
            },
        )
    except Exception:  # noqa: BLE001
        return
