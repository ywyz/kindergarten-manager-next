"""Daily long-SSE and vision response-budget regressions.

These use the real transport parser with a fake socket; no network, DNS, TLS,
provider, database or secret is involved.  The daily path keeps one request and
the strict six-field JSON candidate, while the wire/event/buffer/result-IPC
layers get separate bounded room so a long reasoning stream is not mistaken for
an oversized response.
"""

from __future__ import annotations

import json
import socket
import unittest
from types import SimpleNamespace

from app.local import (
    ai_executor,
    ai_transport as tr,
    ai_worker,
)
from tests.local.test_d2_streaming import _TimeoutReader
from tests.local.test_weekly_ai_transport_bounds import _FakeSock


class _DailyTimeoutSock(_FakeSock):
    def __init__(self, response: bytes, after: int):
        super().__init__(response)
        self._payload = response
        self._after = after

    def makefile(self, *args, **kwargs):
        return _TimeoutReader(self._payload, self._after)


def _prepared(payload: bytes, *, sock=None) -> tr.Prepared:
    return tr.Prepared(
        sock=sock or _FakeSock(payload),
        host="api.example.com",
        netloc="api.example.com",
        path="/chat/completions",
        request_bytes=b"",
    )


def _event(value: dict) -> bytes:
    return (
        b"data: "
        + json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        + b"\n\n"
    )


def _reasoning(text: str) -> bytes:
    return _event(
        {
            "model": "deepseek-flash",
            "choices": [
                {
                    "index": 0,
                    "delta": {"reasoning_content": text},
                    "finish_reason": None,
                }
            ],
        }
    )


def _content(text: str, *, stop: bool = True) -> bytes:
    return _event(
        {
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": text},
                    "finish_reason": "stop" if stop else None,
                }
            ],
        }
    )


def _stop_only() -> bytes:
    return _event(
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
    )


def _sse(*, reasoning_chunks: int = 0, final_content: str = '{"text":"ok"}') -> bytes:
    parts = [_reasoning("r" * 16_000) for _ in range(reasoning_chunks)]
    parts.append(_content(final_content, stop=False))
    parts.append(_stop_only())
    parts.append(b"data: [DONE]\n\n")
    return b"".join(parts)


def _http(body: bytes, *, content_type: str = "text/event-stream") -> bytes:
    head = (
        "HTTP/1.1 200 OK\r\n"
        f"Content-Type: {content_type}\r\n"
        f"Content-Length: {len(body)}\r\n"
        "\r\n"
    ).encode("ascii")
    return head + body


def _send(
    payload: bytes, *, budget: tr.ResponseBudget, deadline_ms: int | None = None
) -> tuple[tr.TransportResult, object]:
    prepared = _prepared(payload)
    result = tr.send(
        prepared,
        deadline_ms=deadline_ms or (tr.now_ticks() + 60_000),
        budget=budget,
    )
    return result, prepared.sock


def _daily_claim(task_type: str = "daily_lesson_split") -> SimpleNamespace:
    return SimpleNamespace(
        image_urls=(),
        source_kind="daily_plan",
        vision_authorized=False,
        task_type=task_type,
        base_url="https://api.example.com/v1",
        model="deepseek-flash",
        system_text="system",
        secret="secret-not-logged",
        payload={
            "raw_lesson_plan": "活动目标：一。\n活动准备：二。\n活动过程：三。",
            "grade": "middle",
        },
        contract_version=1,
    )


class DailyLongStreamTests(unittest.TestCase):
    def test_long_sse_above_old_one_mib_wire_limit_succeeds(self):
        body = _sse(reasoning_chunks=80)
        self.assertGreater(len(body), tr.RESPONSE_MAX_BYTES)
        self.assertLess(len(body), tr.DAILY_TEXT_RESPONSE_BUDGET.wire_max_bytes)
        result, sock = _send(_http(body), budget=tr.DAILY_TEXT_RESPONSE_BUDGET)
        self.assertEqual(result.kind, tr.SUCCESS, result)
        self.assertEqual(result.candidate_text, '{"text":"ok"}')
        self.assertEqual(len(sock.sent), 1)

    def test_missing_terminal_is_truncated_not_success(self):
        body = _sse(reasoning_chunks=1)[: -len(b"data: [DONE]\n\n")]
        result, _ = _send(_http(body), budget=tr.DAILY_TEXT_RESPONSE_BUDGET)
        self.assertEqual(result.kind, tr.OUTPUT_INVALID)
        self.assertEqual(result.detail, tr.DETAIL["stream_truncated"])
        self.assertIsNone(result.candidate_text)

    def test_tail_after_done_is_truncated(self):
        body = _sse(reasoning_chunks=1) + b"data: {}\n\n"
        result, _ = _send(_http(body), budget=tr.DAILY_TEXT_RESPONSE_BUDGET)
        self.assertEqual(result.kind, tr.OUTPUT_INVALID)
        self.assertEqual(result.detail, tr.DETAIL["stream_truncated"])

    def test_reasoning_final_answer_is_display_only_not_the_candidate(self):
        reasoning = "需要先摘出六字段。\nFinal answer:\n{\"group_activity\":{\"theme\":\"模型思考里的答案\"}}"
        body = (
            _reasoning(reasoning)
            + _content('{"group_activity":{"theme":"正文答案","objectives":"","preparation":"","key_points":"","difficult_points":"","process":""}}')
            + b"data: [DONE]\n\n"
        )
        result, sock = _send(_http(body), budget=tr.DAILY_TEXT_RESPONSE_BUDGET)
        self.assertEqual(result.kind, tr.SUCCESS, result)
        self.assertIn("正文答案", result.candidate_text)
        self.assertNotIn("模型思考里的答案", result.candidate_text)
        self.assertNotIn("Final answer", result.candidate_text)
        self.assertEqual(len(sock.sent), 1)

    def test_reasoning_only_final_answer_is_never_accepted(self):
        body = (
            _reasoning('思考结束。\nFinal answer:\n{"group_activity":{"theme":"只有思考"}}')
            + b"data: [DONE]\n\n"
        )
        result, sock = _send(_http(body), budget=tr.DAILY_TEXT_RESPONSE_BUDGET)
        self.assertEqual(result.kind, tr.OUTPUT_INVALID)
        self.assertEqual(result.detail, tr.DETAIL["reasoning_only"])
        self.assertIsNone(result.candidate_text)
        self.assertEqual(len(sock.sent), 1)

    def test_final_answer_prefix_inside_content_is_not_silently_accepted(self):
        body = (
            _reasoning("思考一")
            + _content('Final answer:\n{"group_activity":{"theme":"前缀答案"}}')
            + b"data: [DONE]\n\n"
        )
        result, sock = _send(_http(body), budget=tr.DAILY_TEXT_RESPONSE_BUDGET)
        self.assertEqual(result.kind, tr.OUTPUT_INVALID)
        self.assertEqual(result.detail, tr.DETAIL["invalid_candidate_json"])
        self.assertIsNone(result.candidate_text)
        self.assertEqual(len(sock.sent), 1)

    def test_daily_non_sse_body_keeps_one_mib_limit(self):
        body = b"x" * (tr.RESPONSE_MAX_BYTES + 1)
        result, _ = _send(
            _http(body, content_type="application/json"),
            budget=tr.DAILY_TEXT_RESPONSE_BUDGET,
        )
        self.assertEqual(result.kind, tr.PROVIDER_ERROR)
        self.assertEqual(result.detail, tr.DETAIL["body_too_large"])

    def test_socket_timeout_after_send_is_unknown_and_not_resent(self):
        body = _sse(reasoning_chunks=1)
        sock = _DailyTimeoutSock(_http(body), after=0)
        prepared = _prepared(b"", sock=sock)
        result = tr.send(
            prepared,
            deadline_ms=tr.now_ticks() + 60_000,
            budget=tr.DAILY_TEXT_RESPONSE_BUDGET,
        )
        self.assertEqual(result.kind, tr.UNKNOWN)
        self.assertEqual(result.reason, "timeout_after_dispatch")
        self.assertEqual(len(sock.sent), 1)
        self.assertIsNone(result.candidate_text)

    def test_daily_request_is_one_streaming_json_request_without_provider_pollution(self):
        frames = ai_executor._encode_bootstrap(_daily_claim(), 60_000)
        self.assertEqual(len(frames), 1)
        request = json.loads(frames[0].decode("utf-8"))["request"]
        budget, body = ai_worker.text_request_body(request)
        self.assertEqual(budget, tr.DAILY_TEXT_RESPONSE_BUDGET)
        payload = json.loads(body)
        self.assertIs(payload["stream"], True)
        self.assertEqual(len(payload["messages"]), 2)
        self.assertNotIn("max_tokens", payload)
        # One explicit JSON-mode request, never a retry or an extra call.
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertEqual(
            ai_executor.ai_worker_frame_limit(_daily_claim()),
            tr.DAILY_TEXT_RESPONSE_BUDGET.result_ipc_max_bytes,
        )
        self.assertGreaterEqual(tr.ATTEMPT_BUDGET_MS, 60_000)


class VisionLongStreamTests(unittest.TestCase):
    def test_long_vision_sse_uses_vision_budget_not_one_mib_default(self):
        body = _sse(reasoning_chunks=80)
        self.assertGreater(len(body), tr.RESPONSE_MAX_BYTES)
        self.assertLess(len(body), tr.VISION_TEXT_RESPONSE_BUDGET.wire_max_bytes)
        result, sock = _send(_http(body), budget=tr.VISION_TEXT_RESPONSE_BUDGET)
        self.assertEqual(result.kind, tr.SUCCESS, result)
        self.assertEqual(result.candidate_text, '{"text":"ok"}')
        self.assertEqual(len(sock.sent), 1)

    def test_vision_missing_terminal_is_truncated(self):
        body = _sse(reasoning_chunks=1)[: -len(b"data: [DONE]\n\n")]
        result, _ = _send(_http(body), budget=tr.VISION_TEXT_RESPONSE_BUDGET)
        self.assertEqual(result.kind, tr.OUTPUT_INVALID)
        self.assertEqual(result.detail, tr.DETAIL["stream_truncated"])

    def test_vision_claim_result_frame_uses_vision_limit(self):
        claim = SimpleNamespace(
            image_urls=("data:image/jpeg;base64,AA==",),
            source_kind="game_observation",
            task_type="game_observation_generate",
        )
        self.assertEqual(
            ai_executor.ai_worker_frame_limit(claim),
            tr.VISION_TEXT_RESPONSE_BUDGET.result_ipc_max_bytes,
        )

    def test_worker_selects_vision_budget_for_vision_request(self):
        source = inspect_source()
        self.assertIn("VISION_TEXT_RESPONSE_BUDGET", source)
        self.assertIn("if vision", source)
        self.assertIn("DEFAULT_TEXT_RESPONSE_BUDGET", source)


def inspect_source() -> str:
    import inspect

    return inspect.getsource(ai_worker.run)


if __name__ == "__main__":
    unittest.main()
