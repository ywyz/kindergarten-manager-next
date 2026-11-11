"""A §9.16 weekly streaming bounds via the real transport parser.

The response bytes are fed through ``ai_transport.send`` and the actual HTTP
response/SSE parser; this is not a request-dictionary or fake-transport-only
test.  No socket, DNS, TLS, provider, DB or secret is used.
"""

from __future__ import annotations

import io
import json
import unittest
from types import SimpleNamespace

from app.local import (
    ai_executor,
    ai_task_service,
    ai_transport as tr,
    ai_worker,
)


class _FakeSock:
    def __init__(self, payload: bytes):
        self._raw = io.BytesIO(payload)
        self.sent: list[bytes] = []

    def sendall(self, data):
        self.sent.append(bytes(data))

    def settimeout(self, _timeout):
        pass

    def makefile(self, _mode, buffering=0):
        return self._raw

    def close(self):
        pass


def _prepared(payload: bytes) -> tr.Prepared:
    return tr.Prepared(
        sock=_FakeSock(payload),
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
            ]
        }
    )


def _stop_only() -> bytes:
    return _event(
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
    )


def _sse(
    *,
    reasoning_chunks: int = 0,
    final_content: str = '{"text":"ok"}',
    stop: bool = True,
) -> bytes:
    parts = [
        _reasoning("r" * 16_000)
        for _ in range(reasoning_chunks)
    ]
    parts.append(_content(final_content, stop=stop))
    if stop:
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
    sock_payload: bytes, *, task_type: str
) -> tuple[tr.TransportResult, _FakeSock]:
    prepared = _prepared(sock_payload)
    budget = tr.text_response_budget(task_type)
    assert budget is not None
    result = tr.send(
        prepared,
        deadline_ms=tr.now_ticks() + 60_000,
        budget=budget,
    )
    return result, prepared.sock


def _claim(task_type: str) -> SimpleNamespace:
    return SimpleNamespace(
        image_urls=(),
        source_kind="weekly_plan" if task_type.startswith("weekly_") else "daily_plan",
        vision_authorized=False,
        task_type=task_type,
        base_url="https://api.example.com/v1",
        model="deepseek-flash",
        system_text="system",
        secret="secret-not-logged",
        payload={"task_type": task_type, "schema_version": 1, "days": []},
        contract_version=1,
    )


class WeeklyStreamBudgetTests(unittest.TestCase):
    def test_small_candidate_above_old_wire_limit_succeeds_weekly_and_daily(self):
        body = _sse(reasoning_chunks=80)  # ~1.28 MiB SSE wire, tiny valid JSON content
        self.assertGreater(len(body), tr.RESPONSE_MAX_BYTES)
        self.assertLess(len(body), tr.WEEKLY_TEXT_RESPONSE_BUDGET.wire_max_bytes)

        weekly, weekly_sock = _send(_http(body), task_type="weekly_games_select")
        self.assertEqual(weekly.kind, tr.SUCCESS, weekly)
        self.assertEqual(weekly.candidate_text, '{"text":"ok"}')
        self.assertEqual(len(weekly_sock.sent), 1)

        daily, daily_sock = _send(_http(body), task_type="daily_lesson_split")
        self.assertEqual(daily.kind, tr.SUCCESS, daily)
        self.assertEqual(daily.candidate_text, '{"text":"ok"}')
        self.assertEqual(len(daily_sock.sent), 1)

    def test_weekly_wire_limit_overrun_is_body_too_large(self):
        body = b"x" * (tr.WEEKLY_TEXT_RESPONSE_BUDGET.wire_max_bytes + 1)
        result, sock = _send(_http(body), task_type="weekly_games_select")
        self.assertEqual(result.kind, tr.PROVIDER_ERROR)
        self.assertEqual(result.detail, tr.DETAIL["body_too_large"])
        self.assertEqual(len(sock.sent), 1)

    def test_weekly_content_limit_and_legal_baseline_are_independent(self):
        legal = _sse(final_content='{"text":"ok"}')
        result, _ = _send(_http(legal), task_type="weekly_games_select")
        self.assertEqual(result.kind, tr.SUCCESS)

        # Exactly 1 MiB of final content is legal; one more byte is rejected.
        prefix, suffix = '{"text":"', '"}'
        exact_content = prefix + ("x" * (1_048_576 - len(prefix) - len(suffix))) + suffix
        exact_body = b"".join(
            [
                _content(exact_content[i : i + 16_000], stop=False)
                for i in range(0, len(exact_content), 16_000)
            ]
        ) + _stop_only() + b"data: [DONE]\n\n"
        exact, _ = _send(_http(exact_body), task_type="weekly_games_select")
        self.assertEqual(exact.kind, tr.SUCCESS)
        self.assertEqual(exact.candidate_text, exact_content)

        # Multiple small SSE events, final content itself >1 MiB.
        content = '{"text":"' + ("x" * 1_100_000) + '"}'
        body = b"".join(
            [_content(content[i : i + 16_000], stop=False) for i in range(0, len(content), 16_000)]
        ) + _stop_only() + b"data: [DONE]\n\n"
        self.assertGreater(len(content.encode("utf-8")), 1_048_576)
        self.assertLess(len(body), tr.WEEKLY_TEXT_RESPONSE_BUDGET.wire_max_bytes)
        result, _ = _send(_http(body), task_type="weekly_games_select")
        self.assertEqual(result.kind, tr.OUTPUT_INVALID)
        self.assertEqual(result.detail, tr.DETAIL["content_too_large"])
        self.assertIsNone(result.candidate_text)

    def test_weekly_single_event_and_incomplete_buffer_have_separate_limits(self):
        oversized_event = _reasoning("x" * 2_120_000) + _stop_only()
        self.assertLess(
            len(oversized_event), tr.WEEKLY_TEXT_RESPONSE_BUDGET.wire_max_bytes
        )
        result, _ = _send(_http(oversized_event), task_type="weekly_games_select")
        self.assertEqual(result.kind, tr.OUTPUT_INVALID)
        self.assertEqual(result.detail, tr.DETAIL["event_too_large"])

        unterminated = b"data: " + (b"x" * 3_000_000)  # no SSE event boundary
        self.assertLess(
            len(unterminated), tr.WEEKLY_TEXT_RESPONSE_BUDGET.wire_max_bytes
        )
        result, _ = _send(_http(unterminated), task_type="weekly_games_select")
        self.assertEqual(result.kind, tr.OUTPUT_INVALID)
        self.assertEqual(result.detail, tr.DETAIL["buffer_too_large"])

    def test_weekly_non_sse_keeps_one_mib_and_requires_done(self):
        body = b"x" * (1_048_576 + 1)
        result, _ = _send(
            _http(body, content_type="application/json"),
            task_type="weekly_games_select",
        )
        self.assertEqual(result.kind, tr.PROVIDER_ERROR)
        self.assertEqual(result.detail, tr.DETAIL["body_too_large"])

        no_done = _sse(reasoning_chunks=1, final_content='{"text":"ok"}')[:-len(b"data: [DONE]\n\n")]
        result, _ = _send(_http(no_done), task_type="weekly_games_select")
        self.assertEqual(result.kind, tr.OUTPUT_INVALID)
        self.assertEqual(result.detail, tr.DETAIL["stream_truncated"])

        tail = _sse(reasoning_chunks=1) + b"data: {}\n\n"
        result, _ = _send(_http(tail), task_type="weekly_games_select")
        self.assertEqual(result.kind, tr.OUTPUT_INVALID)
        self.assertEqual(result.detail, tr.DETAIL["stream_truncated"])

    def test_weekly_result_ipc_limit_is_separate_and_parent_matches(self):
        class Conn:
            def __init__(self):
                self.frames = []

            def send_bytes(self, raw):
                self.frames.append(raw)

        frame = {
            "type": "result",
            "result": {"kind": "success", "candidate_text": "x" * 1_100_000},
        }
        conn = Conn()
        self.assertTrue(
            ai_worker._send(
                conn,
                frame,
                result_limit=tr.WEEKLY_TEXT_RESPONSE_BUDGET.result_ipc_max_bytes,
            )
        )
        self.assertGreater(len(conn.frames[0]), ai_worker.RESPONSE_FRAME_MAX)
        self.assertEqual(
            ai_executor.ai_worker_frame_limit(_claim("weekly_games_select")),
            tr.WEEKLY_TEXT_RESPONSE_BUDGET.result_ipc_max_bytes,
        )
        self.assertEqual(
            ai_executor.ai_worker_frame_limit(_claim("daily_lesson_split")),
            tr.DAILY_TEXT_RESPONSE_BUDGET.result_ipc_max_bytes,
        )

    def test_missing_stop_is_failed_and_truncated_length_is_unknown(self):
        no_stop = _sse(reasoning_chunks=1, final_content='{"text":"no-stop"}', stop=False)
        result, _ = _send(_http(no_stop), task_type="weekly_games_select")
        self.assertEqual(result.kind, tr.OUTPUT_INVALID)
        self.assertEqual(result.detail, tr.DETAIL["stream_truncated"])
        self.assertIsNone(result.candidate_text)

        complete = _sse(reasoning_chunks=1)
        truncated = _http(complete).replace(
            f"Content-Length: {len(complete)}\r\n".encode("ascii"),
            f"Content-Length: {len(complete) + 100}\r\n".encode("ascii"),
            1,
        )
        result, _ = _send(truncated, task_type="weekly_games_select")
        self.assertEqual(result.kind, tr.UNKNOWN)
        self.assertEqual(result.detail, tr.DETAIL["incomplete_body"])
        self.assertIsNone(result.candidate_text)

    def test_unknown_budget_is_rejected_before_any_request_and_worker_matches_preflight(self):
        self.assertIsNone(tr.text_response_budget("weekly_forged"))
        self.assertIsNone(tr.text_response_budget([]))
        self.assertIsNone(tr.text_response_budget({}))
        self.assertIsNone(
            tr.text_response_budget(
                "weekly_games_select", source_kind="daily_plan"
            )
        )
        self.assertIsNone(
            tr.text_response_budget(
                "daily_lesson_split", source_kind="weekly_plan"
            )
        )
        with self.assertRaises(ValueError):
            ai_executor._encode_bootstrap(_claim("weekly_forged"), 60_000)
        with self.assertRaises(ValueError):
            ai_executor._encode_bootstrap(
                SimpleNamespace(
                    image_urls=(),
                    source_kind="daily_plan",
                    vision_authorized=False,
                    task_type="weekly_games_select",
                    base_url="https://api.example.com/v1",
                    model="deepseek-flash",
                    system_text="system",
                    secret="secret-not-logged",
                    payload={},
                    contract_version=1,
                ),
                60_000,
            )
        injected = {
            "source_kind": "weekly_plan",
            "task_type": "weekly_games_select",
            "model": "deepseek-flash",
            "system_text": "s",
            "user_text": "{}",
            "max_tokens": 1_000_000,
        }
        with self.assertRaises(ValueError):
            ai_worker.text_request_body(injected)
        mixed = dict(injected)
        mixed.pop("max_tokens")
        mixed["source_kind"] = "daily_plan"
        with self.assertRaises(ValueError):
            ai_worker.text_request_body(mixed)

        for task_type in sorted(tr.WEEKLY_TEXT_TASK_TYPES):
            budget = tr.text_response_budget(
                task_type, source_kind="weekly_plan"
            )
            self.assertEqual(budget, tr.WEEKLY_TEXT_RESPONSE_BUDGET)
            weekly_request = json.loads(
                ai_executor._encode_bootstrap(_claim(task_type), 60_000)[0].decode(
                    "utf-8"
                )
            )["request"]
            _worker_budget, weekly_body = ai_worker.text_request_body(weekly_request)
            self.assertEqual(json.loads(weekly_body)["max_tokens"], 16_384)
        for task_type in sorted(tr.DAILY_TEXT_TASK_TYPES):
            budget = tr.text_response_budget(
                task_type, source_kind="daily_plan"
            )
            self.assertEqual(budget, tr.DAILY_TEXT_RESPONSE_BUDGET)
            self.assertIsNone(budget.max_tokens)
            daily_request = json.loads(
                ai_executor._encode_bootstrap(_claim(task_type), 60_000)[0].decode(
                    "utf-8"
                )
            )["request"]
            _worker_budget, daily_body = ai_worker.text_request_body(daily_request)
            self.assertNotIn("max_tokens", json.loads(daily_body))
        weekly_claim = _claim("weekly_games_select")
        preflight_size = ai_task_service.serialized_request_bytes(
            task_type="weekly_games_select",
            contract_version=1,
            output_schema={},
            guidance={},
            payload=weekly_claim.payload,
            model="deepseek-flash",
        )
        preflight_body = tr.build_request(
            model="deepseek-flash",
            system_text=ai_task_service._render_system_text(
                "weekly_games_select", 1, {}, {}
            ),
            user_text=json.dumps(
                weekly_claim.payload, ensure_ascii=False, separators=(",", ":")
            ),
            max_tokens=16_384,
        )
        self.assertEqual(preflight_size, len(preflight_body))
        frame = json.loads(
            ai_executor._encode_bootstrap(weekly_claim, 60_000)[0].decode("utf-8")
        )
        request = frame["request"]
        self.assertEqual(request["task_type"], "weekly_games_select")
        budget, worker_body = ai_worker.text_request_body(request)
        self.assertEqual(budget, tr.WEEKLY_TEXT_RESPONSE_BUDGET)
        preflight_body = tr.build_request(
            model=request["model"],
            system_text=request["system_text"],
            user_text=request["user_text"],
            max_tokens=budget.max_tokens,
        )
        self.assertEqual(worker_body, preflight_body)
        self.assertEqual(json.loads(worker_body)["max_tokens"], 16_384)

        daily_claim = _claim("daily_lesson_split")
        daily_frame = json.loads(
            ai_executor._encode_bootstrap(daily_claim, 60_000)[0].decode("utf-8")
        )
        daily_request = daily_frame["request"]
        daily_budget, daily_body = ai_worker.text_request_body(daily_request)
        self.assertEqual(daily_budget, tr.DAILY_TEXT_RESPONSE_BUDGET)
        self.assertNotIn("max_tokens", json.loads(daily_body))
        self.assertNotIn("max_tokens", json.loads(
            tr.build_request(
                model=daily_request["model"],
                system_text=daily_request["system_text"],
                user_text=daily_request["user_text"],
            )
        ))

    def test_default_non_stream_response_behavior_is_unchanged(self):
        envelope = json.dumps(
            {
                "choices": [
                    {
                        "message": {"content": '{"text":"ok"}'},
                        "finish_reason": "stop",
                    }
                ],
                "model": "deepseek-flash",
            },
            ensure_ascii=False,
        ).encode("utf-8")
        result, _ = _send(
            _http(envelope, content_type="application/json"),
            task_type="daily_lesson_split",
        )
        self.assertEqual(result.kind, tr.SUCCESS)
        self.assertEqual(result.candidate_text, '{"text":"ok"}')
        self.assertEqual(result.returned_model, "deepseek-flash")


if __name__ == "__main__":
    unittest.main()
