"""Fake spawn worker for observation E06/E07 service tests.

No network.  It accepts the small header + vision body, reports ready, waits
for the parent SEND, then returns a fixed observation candidate.  The real
worker/transport path is exercised separately with a synthetic TLS server.
"""

from __future__ import annotations

import json
import time

from app.local import ai_transport, ai_worker

GENERATE = {
    "observation_goal": "观察幼儿合作搭建",
    "observation_process": "幼儿说：“我们一起搭桥吧。”\n两人轮流放置积木。",
    "analysis_evaluation": {
        "health": "动作协调",
        "language": "表达合作意愿",
        "social": "轮流协商",
        "science": "尝试连接",
        "arts": "",
    },
    "support_strategy": "提供更多连接材料，鼓励共同计划。",
}


def _send(conn, frame):
    try:
        conn.send_bytes(json.dumps(frame, ensure_ascii=False).encode("utf-8"))
        return True
    except Exception:  # noqa: BLE001
        return False


def observation_worker_entry(conn):
    try:
        if not conn.poll(5.0):
            return
        first = json.loads(bytes(conn.recv_bytes(ai_worker.REQUEST_FRAME_MAX)).decode("utf-8"))
        if first.get("type") == "bootstrap_header":
            if not first.get("vision"):
                return
            bootstrap = json.loads(
                bytes(conn.recv_bytes(ai_worker.VISION_REQUEST_FRAME_MAX)).decode("utf-8")
            )
        else:
            bootstrap = first
        request = bootstrap["request"]
        mode = (bootstrap.get("synthetic") or {}).get("obs_mode")
        if mode == "result_not_sent":
            _send(
                conn,
                {
                    "type": "result",
                    "result": {
                        "kind": "not_sent",
                        "reason": "connection_unavailable",
                        "transient_not_sent": False,
                        "sent": False,
                    },
                },
            )
            return
        _send(conn, {"type": "ready", "remaining_ms": 5000})
        if not conn.poll(30.0):
            return
        command = json.loads(bytes(conn.recv_bytes(64 * 1024)).decode("utf-8"))
        if command.get("type") != "send":
            return
        if mode == "exit_after_send":
            return
        if mode == "silent_after_send":
            time.sleep(5.0)
            return
        payload = json.loads(request["user_text"])
        if request.get("protocol") != ai_transport.VISION_PROTOCOL_ID:
            return
        if payload.get("target"):
            target = payload["target"]
            if target == "analysis_evaluation":
                candidate = {
                    "target": target,
                    "analysis_evaluation": {
                        "health": "重写健康",
                        "language": "重写语言",
                        "social": "重写社会",
                        "science": "重写科学",
                        "arts": "重写艺术",
                    },
                }
            else:
                candidate = {"target": target, "text": f"重写后的{target}"}
        else:
            candidate = GENERATE
        _send(
            conn,
            {
                "type": "result",
                "result": {
                    "kind": "success",
                    "sent": True,
                    "http_status": 200,
                    "provider_request_id": "obs-test",
                    "returned_model": "deepseek-flash",
                    "usage": {"prompt_tokens": 1},
                    "candidate_text": json.dumps(candidate, ensure_ascii=False),
                },
            },
        )
    except Exception:  # noqa: BLE001
        pass
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass
