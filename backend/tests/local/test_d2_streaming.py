"""D2 streaming transport/progress tests.

Part 1 uses a fake socket/reader to exercise exact SSE boundaries (UTF-8 split
across chunks, CRLF, heartbeats, usage, truncation, invalid frames) without any
network. Part 2 uses a real controlled TLS server plus the real spawned worker /
Job / production transport, and proves that progress is readable *before* the
final answer; a broken stream is not retried.
"""

from __future__ import annotations

import json
import socket
import ssl
import threading
import time
import unittest
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory

from app.local import ai_progress, ai_transport
from app.local.ai_executor import AiExecutor
from tests.local import w3_tls
from tests.local.test_d2_w3_executor import SPLIT_CANDIDATE, ExecutorCase
from tests.local.w3_tls import TEST_HOST

# ---------------------------------------------------------------------------
# Part 1: deterministic SSE parser
# ---------------------------------------------------------------------------


class _Reader:
    def __init__(self, data: bytes, chunk_size: int | None = None):
        self._data = data
        self._pos = 0
        self._chunk = chunk_size

    def readline(self, size: int = -1) -> bytes:
        end = self._data.find(b"\n", self._pos)
        end = len(self._data) if end < 0 else end + 1
        chunk = self._data[self._pos : end]
        self._pos = end
        return chunk

    def read1(self, size: int = -1) -> bytes:
        if self._pos >= len(self._data):
            return b""
        limit = self._chunk if self._chunk else (size if size and size > 0 else len(self._data))
        count = min(limit, len(self._data) - self._pos)
        chunk = self._data[self._pos : self._pos + count]
        self._pos += count
        return chunk

    def read(self, size: int = -1) -> bytes:
        return self.read1(size)

    def close(self) -> None:
        pass


class _FakeSock:
    def __init__(self, response: bytes, chunk_size: int | None = None):
        self._response = response
        self._chunk = chunk_size
        self.sent = 0

    def sendall(self, data: bytes) -> None:
        self.sent += 1

    def makefile(self, *args, **kwargs) -> _Reader:
        return _Reader(self._response, self._chunk)

    def settimeout(self, timeout: float) -> None:
        pass

    def close(self) -> None:
        pass


class _BrokenReader(_Reader):
    def __init__(self, data: bytes, after: int):
        super().__init__(data)
        self._after = after

    def read1(self, size: int = -1) -> bytes:
        if self._pos >= self._after:
            raise OSError("connection reset mid-stream")
        return super().read1(size)


class _BrokenSock(_FakeSock):
    def __init__(self, response: bytes, after: int):
        super().__init__(response)
        self._after = after

    def makefile(self, *args, **kwargs) -> _BrokenReader:
        return _BrokenReader(self._response, self._after)


class _SlowReader(_Reader):
    def __init__(self, data: bytes, delay: float, after: int):
        super().__init__(data)
        self._delay = delay
        self._after = after

    def read1(self, size: int = -1) -> bytes:
        if self._pos >= self._after:
            time.sleep(self._delay)
            return b""
        return super().read1(size)


class _SlowSock(_FakeSock):
    def __init__(self, response: bytes, delay: float, after: int):
        super().__init__(response)
        self._delay = delay
        self._after = after

    def makefile(self, *args, **kwargs) -> _SlowReader:
        return _SlowReader(self._response, self._delay, self._after)


class _TimeoutReader(_Reader):
    def __init__(self, data: bytes, after: int):
        super().__init__(data)
        self._after = after

    def read1(self, size: int = -1) -> bytes:
        if self._pos >= self._after:
            raise socket.timeout("simulated read timeout")
        return super().read1(size)


class _TimeoutSock(_FakeSock):
    def __init__(self, response: bytes, after: int):
        super().__init__(response)
        self._after = after

    def makefile(self, *args, **kwargs) -> _TimeoutReader:
        return _TimeoutReader(self._response, self._after)


def _http(body: bytes, *, content_type: str, chunked: bool = False) -> bytes:
    if chunked:
        payload = b""
        for start in range(0, len(body), 4096):
            part = body[start : start + 4096]
            payload += f"{len(part):x}\r\n".encode() + part + b"\r\n"
        payload += b"0\r\n\r\n"
        return (
            b"HTTP/1.1 200 OK\r\nContent-Type: "
            + content_type.encode()
            + b"\r\nTransfer-Encoding: chunked\r\n\r\n"
            + payload
        )
    return (
        b"HTTP/1.1 200 OK\r\nContent-Type: "
        + content_type.encode()
        + b"\r\nContent-Length: "
        + str(len(body)).encode()
        + b"\r\n\r\n"
        + body
    )


def _event(payload: dict | str) -> bytes:
    data = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return f"data: {data}\n\n".encode("utf-8")


def _event_json(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _send(body: bytes, *, chunk_size: int | None = None, chunked: bool = False, on_progress=None):
    sock = _FakeSock(_http(body, content_type="text/event-stream", chunked=chunked), chunk_size)
    prepared = ai_transport.Prepared(
        sock=sock,
        host="api.example.com",
        netloc="api.example.com",
        path="/v1/chat/completions",
        request_bytes=b"POST /v1/chat/completions HTTP/1.1\r\n\r\n",
    )
    return ai_transport.send(
        prepared,
        deadline_ms=ai_transport.now_ticks() + 30_000,
        on_progress=on_progress,
    ), sock


class StreamParserTests(unittest.TestCase):
    def test_request_asks_for_stream(self):
        body = ai_transport.build_request(
            model="m", system_text="s", user_text="u"
        )
        self.assertIn(b'"stream":true', body)

    def test_split_utf8_and_crlf_with_reasoning_content_separation(self):
        body = b"".join(
            [
                b": keep-alive\r\n\r\n",
                _event({"model": "m", "choices": [{"delta": {"reasoning_content": "思考一"}}]}),
                _event({"choices": [{"delta": {}}]}),
                _event({"choices": [{"delta": {"content": '{"ok":'}}]}),
                _event({"choices": [{"delta": {"content": 'true}'}}]}),
                _event({"choices": [], "usage": {"prompt_tokens": 2, "completion_tokens": 1}}),
                _event({"choices": [{"delta": {}, "finish_reason": "stop"}]}),
                _event("[DONE]"),
            ]
        )
        progress: list[tuple[str, str]] = []
        result, sock = _send(
            body,
            chunk_size=1,
            on_progress=lambda reasoning, content: progress.append((reasoning, content)),
        )
        self.assertEqual(result.kind, ai_transport.SUCCESS, result.detail)
        self.assertEqual(result.candidate_text, '{"ok":true}')
        self.assertEqual(result.returned_model, "m")
        self.assertEqual(result.usage, {"prompt_tokens": 2, "completion_tokens": 1})
        self.assertIn(("思考一", ""), progress)
        self.assertTrue(any(content for _reasoning, content in progress))
        self.assertEqual(sock.sent, 1)

    def test_chunked_stream_is_supported(self):
        body = b"".join(
            [
                _event({"choices": [{"delta": {"content": '{"a":1}'}}]}),
                _event({"choices": [{"delta": {}, "finish_reason": "stop"}]}),
                _event("[DONE]"),
            ]
        )
        result, _sock = _send(body, chunked=True)
        self.assertEqual(result.kind, ai_transport.SUCCESS, result.detail)
        self.assertEqual(result.candidate_text, '{"a":1}')

    def test_multi_data_line_event_survives_split_crlf(self):
        # One JSON object split over two data: lines, with CRLF split at every
        # byte boundary. Before the fix this became an early blank line.
        first = '{"choices":['
        second = '{"delta":{"content":"{\\"a\\":1}"},"finish_reason":"stop"}]}'
        body = (
            b"data: "
            + first.encode()
            + b"\r\ndata: "
            + second.encode()
            + b"\r\n\r\n"
            + b"data: [DONE]\r\n\r\n"
        )
        result, _sock = _send(body, chunk_size=1)
        self.assertEqual(result.kind, ai_transport.SUCCESS, result.detail)
        self.assertEqual(result.candidate_text, '{"a":1}')

    def test_lone_cr_line_endings(self):
        body = (
            b"data: "
            + _event_json({"choices": [{"delta": {"content": '{"a":1}'}}]})
            + b"\r\rdata: "
            + _event_json({"choices": [{"delta": {}, "finish_reason": "stop"}]})
            + b"\r\rdata: [DONE]\r\r"
        )
        result, _sock = _send(body, chunk_size=1)
        self.assertEqual(result.kind, ai_transport.SUCCESS, result.detail)
        self.assertEqual(result.candidate_text, '{"a":1}')

    def test_done_without_stop_is_invalid(self):
        body = b"".join(
            [
                _event({"choices": [{"delta": {"content": '{"a":1}'}}]}),
                _event("[DONE]"),
            ]
        )
        result, sock = _send(body)
        self.assertEqual(result.kind, ai_transport.OUTPUT_INVALID)
        self.assertEqual(result.detail, ai_transport.DETAIL["stream_truncated"])
        self.assertEqual(sock.sent, 1)

    def test_content_after_stop_is_invalid(self):
        body = b"".join(
            [
                _event({"choices": [{"index": 0, "delta": {"content": '{"a":1}'}}]}),
                _event({"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}),
                _event({"choices": [{"index": 0, "delta": {"content": '{"b":2}'}}]}),
                _event("[DONE]"),
            ]
        )
        result, sock = _send(body)
        self.assertEqual(result.kind, ai_transport.OUTPUT_INVALID)
        self.assertEqual(sock.sent, 1)

    def test_different_choice_index_is_invalid(self):
        body = b"".join(
            [
                _event({"choices": [{"index": 0, "delta": {"content": '{"a":1}'}}]}),
                _event({"choices": [{"index": 1, "delta": {"content": "x"}}]}),
                _event({"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}),
                _event("[DONE]"),
            ]
        )
        result, _sock = _send(body)
        self.assertEqual(result.kind, ai_transport.OUTPUT_INVALID)

    def test_usage_only_frame_is_allowed_but_empty_choices_are_not(self):
        body = b"".join(
            [
                _event({"choices": [{"delta": {"content": '{"a":1}'}}]}),
                _event({"choices": [], "usage": {"prompt_tokens": 1}}),
                _event({"choices": [{"delta": {}, "finish_reason": "stop"}]}),
                _event("[DONE]"),
            ]
        )
        result, _sock = _send(body)
        self.assertEqual(result.kind, ai_transport.SUCCESS, result.detail)
        bad, _sock2 = _send(
            b"".join(
                [
                    _event({"choices": [{"delta": {"content": '{"a":1}'}}]}),
                    _event({"choices": []}),
                    _event({"choices": [{"delta": {}, "finish_reason": "stop"}]}),
                    _event("[DONE]"),
                ]
            )
        )
        self.assertEqual(bad.kind, ai_transport.OUTPUT_INVALID)

    def test_message_branch_forbidden_fields_are_rejected(self):
        for field, value in (
            ("tool_calls", [{"id": "tool1"}]),
            ("function_call", {"name": "x"}),
            ("refusal", "no"),
        ):
            with self.subTest(field=field):
                body = b"".join(
                    [
                        _event(
                            {
                                "choices": [
                                    {"index": 0, "delta": {"content": "{}"}}
                                ]
                            }
                        ),
                        _event(
                            {
                                "choices": [
                                    {
                                        "index": 0,
                                        "message": {field: value},
                                        "finish_reason": "stop",
                                    }
                                ]
                            }
                        ),
                        _event("[DONE]"),
                    ]
                )
                result, sock = _send(body)
                self.assertEqual(result.kind, ai_transport.OUTPUT_INVALID)
                self.assertEqual(result.detail, ai_transport.DETAIL["forbidden_field"])
                self.assertEqual(sock.sent, 1)

    def test_content_and_stop_in_the_same_final_chunk_is_valid(self):
        body = _event(
            {
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": '{"a":1}'},
                        "finish_reason": "stop",
                    }
                ]
            }
        )
        result, _sock = _send(body)
        self.assertEqual(result.kind, ai_transport.SUCCESS, result.detail)
        self.assertEqual(result.candidate_text, '{"a":1}')

    def test_stop_without_done_is_success_when_framing_is_complete(self):
        body = b"".join(
            [
                _event({"choices": [{"delta": {"content": '{"a":1}'}}]}),
                _event({"choices": [{"delta": {}, "finish_reason": "stop"}]}),
            ]
        )
        result, _sock = _send(body)
        self.assertEqual(result.kind, ai_transport.SUCCESS, result.detail)
        self.assertEqual(result.candidate_text, '{"a":1}')

    def test_stop_then_incomplete_utf8_tail_is_invalid(self):
        body = b"".join(
            [
                _event({"choices": [{"delta": {"content": '{"a":1}'}}]}),
                _event({"choices": [{"delta": {}, "finish_reason": "stop"}]}),
                _event("[DONE]"),
                b"\xe4",
            ]
        )
        result, _sock = _send(body)
        self.assertEqual(result.kind, ai_transport.OUTPUT_INVALID)
        self.assertEqual(result.detail, ai_transport.DETAIL["response_not_utf8"])

    def test_heartbeat_comment_is_forwarded_without_content(self):
        heartbeats = []
        body = b"".join(
            [
                b": keep-alive\n\n",
                _event({"choices": [{"delta": {"content": '{"a":1}'}}]}),
                _event({"choices": [{"delta": {}, "finish_reason": "stop"}]}),
                _event("[DONE]"),
            ]
        )
        sock = _FakeSock(_http(body, content_type="text/event-stream"))
        prepared = ai_transport.Prepared(
            sock=sock,
            host="api.example.com",
            netloc="api.example.com",
            path="/v1/chat/completions",
            request_bytes=b"x",
        )
        result = ai_transport.send(
            prepared,
            deadline_ms=ai_transport.now_ticks() + 30_000,
            on_heartbeat=lambda: heartbeats.append(1),
        )
        self.assertEqual(result.kind, ai_transport.SUCCESS, result.detail)
        self.assertEqual(len(heartbeats), 1)

    def test_plain_json_response_is_still_accepted(self):
        envelope = w3_tls.envelope(json.dumps({"a": 1}))
        sock = _FakeSock(envelope)
        prepared = ai_transport.Prepared(
            sock=sock,
            host="api.example.com",
            netloc="api.example.com",
            path="/v1/chat/completions",
            request_bytes=b"x",
        )
        result = ai_transport.send(prepared, deadline_ms=ai_transport.now_ticks() + 30_000)
        self.assertEqual(result.kind, ai_transport.SUCCESS, result.detail)
        self.assertEqual(result.candidate_text, '{"a": 1}')

    def test_stream_without_done_or_finish_is_truncated(self):
        body = _event({"choices": [{"delta": {"content": '{"a":'}}]})
        result, sock = _send(body)
        self.assertEqual(result.kind, ai_transport.OUTPUT_INVALID)
        self.assertEqual(result.detail, ai_transport.DETAIL["stream_truncated"])
        self.assertEqual(sock.sent, 1)

    def test_invalid_event_and_forbidden_fields_are_refused(self):
        cases = [
            _event("{not-json"),
            _event({"choices": [{"delta": {"tool_calls": [{"id": "x"}]}}]}),
            _event({"choices": [{"delta": {"content": '"x"'}, "finish_reason": "length"}]}),
            _event({"choices": [{"delta": {}}, {"delta": {}}]}),
        ]
        for body in cases:
            with self.subTest(body=body[:40]):
                result, sock = _send(body + _event("[DONE]"))
                self.assertEqual(result.kind, ai_transport.OUTPUT_INVALID)
                self.assertEqual(sock.sent, 1)

    def test_complete_stream_with_invalid_candidate_json(self):
        body = b"".join(
            [
                _event({"choices": [{"delta": {"content": "not json"}}]}),
                _event({"choices": [{"delta": {}, "finish_reason": "stop"}]}),
                _event("[DONE]"),
            ]
        )
        result, _sock = _send(body)
        self.assertEqual(result.kind, ai_transport.OUTPUT_INVALID)
        self.assertEqual(result.detail, ai_transport.DETAIL["invalid_candidate_json"])

    def test_short_declared_body_is_unknown_even_with_stop_and_done(self):
        body = b"".join(
            [
                _event({"choices": [{"delta": {"content": '{"a":1}'}}]}),
                _event({"choices": [{"delta": {}, "finish_reason": "stop"}]}),
                _event("[DONE]"),
            ]
        )
        response = (
            b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n"
            b"Content-Length: 9999\r\n\r\n" + body
        )
        sock = _FakeSock(response)
        prepared = ai_transport.Prepared(
            sock=sock,
            host="api.example.com",
            netloc="api.example.com",
            path="/v1/chat/completions",
            request_bytes=b"x",
        )
        result = ai_transport.send(
            prepared, deadline_ms=ai_transport.now_ticks() + 30_000
        )
        self.assertEqual(result.kind, ai_transport.UNKNOWN)
        self.assertEqual(result.detail, ai_transport.DETAIL["incomplete_body"])
        self.assertEqual(sock.sent, 1)

    def test_chunked_without_terminal_chunk_is_unknown(self):
        body = _event({"choices": [{"delta": {"content": '{"a":1}'}}]})
        body += _event({"choices": [{"delta": {}, "finish_reason": "stop"}]})
        body += _event("[DONE]")
        payload = f"{len(body):x}\r\n".encode() + body + b"\r\n"
        response = (
            b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n"
            b"Transfer-Encoding: chunked\r\n\r\n" + payload
        )
        sock = _FakeSock(response)
        prepared = ai_transport.Prepared(
            sock=sock,
            host="api.example.com",
            netloc="api.example.com",
            path="/v1/chat/completions",
            request_bytes=b"x",
        )
        result = ai_transport.send(
            prepared, deadline_ms=ai_transport.now_ticks() + 30_000
        )
        self.assertEqual(result.kind, ai_transport.UNKNOWN)
        self.assertIn(
            result.detail,
            {ai_transport.DETAIL["incomplete_body"], ai_transport.DETAIL["stream_truncated"]},
        )

    def test_connection_break_is_unknown_and_not_retried(self):
        body = _event({"choices": [{"delta": {"reasoning_content": "思考"}}]})
        response = (
            b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n"
            b"Content-Length: 9999\r\n\r\n" + body
        )
        sock = _BrokenSock(response, len(response) - 3)
        prepared = ai_transport.Prepared(
            sock=sock,
            host="api.example.com",
            netloc="api.example.com",
            path="/v1/chat/completions",
            request_bytes=b"x",
        )
        result = ai_transport.send(
            prepared, deadline_ms=ai_transport.now_ticks() + 30_000
        )
        self.assertEqual(result.kind, ai_transport.UNKNOWN)
        self.assertEqual(sock.sent, 1)

    def test_stream_read_timeout_is_unknown_and_not_retried(self):
        body = _event({"choices": [{"delta": {"reasoning_content": "思考"}}]})
        response = (
            b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n"
            b"Content-Length: 9999\r\n\r\n" + body
        )
        sock = _TimeoutSock(response, len(response))
        prepared = ai_transport.Prepared(
            sock=sock,
            host="api.example.com",
            netloc="api.example.com",
            path="/v1/chat/completions",
            request_bytes=b"x",
        )
        result = ai_transport.send(
            prepared, deadline_ms=ai_transport.now_ticks() + 30_000
        )
        self.assertEqual(result.kind, ai_transport.UNKNOWN)
        self.assertEqual(sock.sent, 1)

    def test_progress_hook_exception_never_breaks_the_attempt(self):
        body = b"".join(
            [
                _event({"choices": [{"delta": {"reasoning_content": "思考"}}]}),
                _event({"choices": [{"delta": {"content": '{"a":1}'}}]}),
                _event({"choices": [{"delta": {}, "finish_reason": "stop"}]}),
                _event("[DONE]"),
            ]
        )

        def boom(_reasoning: str, _content: str) -> None:
            raise RuntimeError("display hook failure")

        result, _sock = _send(body, on_progress=boom)
        self.assertEqual(result.kind, ai_transport.SUCCESS, result.detail)
        self.assertEqual(result.candidate_text, '{"a":1}')


# ---------------------------------------------------------------------------
# Part 2: real spawned executor + streaming TLS server
# ---------------------------------------------------------------------------


class _StreamingServer:
    """A controlled TLS server that emits an SSE stream with a pause."""

    def __init__(self, *, cert: Path, key: Path, first: bytes, second: bytes, delay: float = 0.5, close_after_first: bool = False):
        self.requests: list[bytes] = []
        self._first = first
        self._second = second
        self._delay = delay
        self._close_after_first = close_after_first
        self._stop = threading.Event()
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certfile=str(cert), keyfile=str(key))
        self._context = context
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(8)
        self._sock.settimeout(0.2)
        self.port = int(self._sock.getsockname()[1])
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def start(self):
        self._thread.start()
        return self

    def _serve(self):
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except (socket.timeout, TimeoutError):
                continue
            except OSError:
                break
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn):
        try:
            tls = self._context.wrap_socket(conn, server_side=True)
        except Exception:  # noqa: BLE001
            conn.close()
            return
        try:
            tls.settimeout(20)
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = tls.recv(65536)
                if not chunk:
                    break
                data += chunk
            head, _, rest = data.partition(b"\r\n\r\n")
            length = 0
            for line in head.split(b"\r\n"):
                if line.lower().startswith(b"content-length:"):
                    length = int(line.split(b":", 1)[1].strip())
            while len(rest) < length:
                chunk = tls.recv(65536)
                if not chunk:
                    break
                rest += chunk
            self.requests.append(head + b"\r\n\r\n" + rest)
            tls.sendall(
                b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n"
                b"Transfer-Encoding: chunked\r\n\r\n"
            )
            for part in (self._first,):
                tls.sendall(f"{len(part):x}\r\n".encode() + part + b"\r\n")
            if self._close_after_first:
                # A clean end of the HTTP body without a finish/DONE event: the
                # stream is truncated, not a transport break.
                time.sleep(0.1)
                tls.sendall(b"0\r\n\r\n")
                return
            time.sleep(self._delay)
            tls.sendall(f"{len(self._second):x}\r\n".encode() + self._second + b"\r\n")
            tls.sendall(b"0\r\n\r\n")
        except Exception:  # noqa: BLE001
            pass
        finally:
            try:
                tls.close()
            except Exception:  # noqa: BLE001
                pass

    def stop(self):
        self._stop.set()
        try:
            self._sock.close()
        except Exception:  # noqa: BLE001
            pass


class StreamingExecutorTests(ExecutorCase):
    def setUp(self):
        super().setUp()
        ai_progress.clear()
        self._temp = TemporaryDirectory(prefix="kgm-stream-tls-")
        self.addCleanup(self._temp.cleanup)
        root = Path(self._temp.name)
        w3_tls.create_ca(root / "ca")
        self._leaf = w3_tls.create_leaf(root / "ca", root / "leaf")
        self._ca_pem = (root / "ca" / "ca.pem").read_text(encoding="utf-8")

    def tearDown(self):
        ai_progress.clear()
        super().tearDown()

    def _executor(self, server: _StreamingServer) -> AiExecutor:
        executor = AiExecutor(
            self.runtime,
            synthetic_transport={
                "resolution": [
                    {"family": socket.AF_INET, "ip": "127.0.0.1", "port": server.port}
                ],
                "ca_pem": self._ca_pem,
            },
        )
        executor.start()
        self._executors.append(executor)
        self.addCleanup(self._dispose_executors)
        return executor

    def test_progress_is_readable_before_final_answer(self):
        candidate = json.dumps(SPLIT_CANDIDATE, ensure_ascii=False)
        first = b"".join(
            [
                b": provider-keepalive\n\n",
                _event({"model": "m", "choices": [{"delta": {"reasoning_content": "先思考"}}]}),
                _event({"choices": [{"delta": {"content": candidate[:12]}}]}),
            ]
        )
        second = b"".join(
            [
                _event({"choices": [{"delta": {"content": candidate[12:]}}]}),
                _event({"choices": [{"delta": {}, "finish_reason": "stop"}]}),
                _event("[DONE]"),
            ]
        )
        server = _StreamingServer(
            cert=self._leaf[0], key=self._leaf[1], first=first, second=second, delay=0.8
        ).start()
        self.addCleanup(server.stop)
        self.configure_ai(model="real-model")
        executor = self._executor(server)
        plan = self.make_plan()
        task = self.submit(plan["id"], executor=executor)

        seen_nonempty = False
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            row = self.task_row(task["id"])
            execution_id = row.get("current_execution_id") if row else None
            if execution_id:
                snap = ai_progress.snapshot(task["id"], execution_id)
                if snap and snap["reasoning"] and not snap["ended"]:
                    seen_nonempty = True
                    self.assertIn(snap["phase"], ("thinking", "generating"))
                    self.assertGreater(snap["last_data_ticks"], 0)
                    break
            time.sleep(0.05)
        self.assertTrue(seen_nonempty, "progress must be readable before the final answer")
        self.assertEqual(self.wait_status(task["id"], {"succeeded"}, timeout=40), "succeeded")
        self.assertEqual(self.candidate_count(task["id"]), 1)
        self.assertEqual(len(server.requests), 1)

    def test_broken_stream_is_not_retried(self):
        first = _event({"choices": [{"delta": {"reasoning_content": "只有思考"}}]})
        server = _StreamingServer(
            cert=self._leaf[0],
            key=self._leaf[1],
            first=first,
            second=b"",
            close_after_first=True,
        ).start()
        self.addCleanup(server.stop)
        self.configure_ai(model="real-model")
        executor = self._executor(server)
        plan = self.make_plan()
        task = self.submit(plan["id"], executor=executor)
        self.assertEqual(self.wait_status(task["id"], {"failed"}, timeout=40), "failed")
        self.assertEqual(self.task_row(task["id"])["reason"], "output_invalid")
        self.assertEqual(self.candidate_count(task["id"]), 0)
        self.assertEqual(len(server.requests), 1)

    def test_cancel_after_stream_send_is_unknown_without_retry(self):
        from app.local import ai_task_service

        first = _event({"choices": [{"delta": {"reasoning_content": "思考中"}}]})
        server = _StreamingServer(
            cert=self._leaf[0],
            key=self._leaf[1],
            first=first,
            second=b"",
            delay=10.0,
        ).start()
        self.addCleanup(server.stop)
        self.configure_ai(model="real-model")
        executor = self._executor(server)
        plan = self.make_plan()
        task = self.submit(plan["id"], executor=executor)
        claim_id = None
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            row = self.task_row(task["id"])
            claim_id = row.get("current_execution_id") if row else None
            if claim_id:
                snapshot = ai_progress.snapshot(task["id"], claim_id)
                if snapshot and snapshot["reasoning"]:
                    break
            time.sleep(0.05)
        self.assertIsNotNone(claim_id)
        assert claim_id is not None
        self.assertTrue(executor.begin_cancel(claim_id))
        result, _abort_id, _kind = ai_task_service.cancel_task(
            self.session,
            task_id=task["id"],
            expected_execution_id=claim_id,
            request_id=str(uuid.uuid4()),
        )
        executor.end_cancel(claim_id, committed=True)
        executor.abort_execution(claim_id, "cancel")
        executor.notify()
        # The request was already sent; a cancel cannot prove it was not
        # received, so the only honest terminal state is outcome_unknown.
        self.assertEqual(result["status"], "outcome_unknown")
        self.assertEqual(
            self.wait_status(task["id"], {"outcome_unknown"}, timeout=20),
            "outcome_unknown",
        )
        self.assertEqual(self.candidate_count(task["id"]), 0)
        self.assertEqual(len(server.requests), 1)


class ProgressApiTests(ExecutorCase):
    def setUp(self):
        super().setUp()
        ai_progress.clear()

    def tearDown(self):
        ai_progress.clear()
        super().tearDown()

    def test_progress_api_lists_only_current_execution(self):
        from app.local import ai_task_service, api
        from app.local.base import utc_now

        self.configure_ai(model="real-model")
        plan = self.make_plan()
        task = self.create_split(plan["id"])
        claim = ai_task_service.claim_next(
            self.runtime,
            now=utc_now(),
            started_ticks=ai_transport.now_ticks(),
        )
        self.assertIsNotNone(claim)
        assert claim is not None
        before = self.task_row(task["id"])
        ai_progress.begin(claim)
        ai_progress.update(
            claim,
            seq=1,
            phase="thinking",
            reasoning_delta="先想一想",
            content_chars=5,
        )
        out = api.get_ai_task_progress(task["id"], self.session)
        self.assertTrue(out["available"])
        self.assertEqual(out["execution_id"], claim.execution_id)
        self.assertEqual(out["attempt_id"], claim.attempt_id)
        self.assertEqual(out["phase"], "thinking")
        self.assertEqual(out["reasoning"], "先想一想")
        self.assertIsNotNone(out["elapsed_ms"])
        after = self.task_row(task["id"])
        self.assertEqual(before["updated_at"], after["updated_at"])

        ai_progress.clear()
        empty = api.get_ai_task_progress(task["id"], self.session)
        self.assertFalse(empty["available"])
        self.assertEqual(empty["execution_id"], claim.execution_id)

        with self.assertRaises(Exception):
            api.get_ai_task_progress("missing-task", self.session)

    def test_pending_after_manual_retry_hides_old_execution_progress(self):
        from app.local import ai_task_service, ai_transport, api
        from app.local.base import utc_now
        from app.local.models import LocalAITask

        self.configure_ai(model="real-model")
        plan = self.make_plan()
        task = self.create_split(plan["id"])
        first = ai_task_service.claim_next(
            self.runtime, now=utc_now(), started_ticks=ai_transport.now_ticks()
        )
        self.assertIsNotNone(first)
        assert first is not None
        ai_progress.begin(first)
        ai_progress.update(
            first, seq=1, phase="thinking", reasoning_delta="旧失败思考"
        )
        ai_progress.finish(
            first,
            {"kind": ai_transport.UNKNOWN, "reason": "timeout_after_dispatch"},
        )
        self.session.expire_all()
        row = self.session.get(LocalAITask, task["id"])
        assert row is not None
        row.status = "failed"
        row.reason = "timeout_after_dispatch"
        self.session.commit()
        old_execution = row.current_execution_id

        result = ai_task_service.retry_task(
            self.session,
            task_id=task["id"],
            expected_execution_id=old_execution,
            ack_duplicate_cost=True,
            request_id=str(uuid.uuid4()),
            runtime=self.runtime,
        )
        self.assertEqual(result["status"], "pending")
        self.assertEqual(result["execution"]["id"], old_execution)
        pending = api.get_ai_task_progress(task["id"], self.session)
        self.assertFalse(pending["available"])
        self.assertEqual(pending["phase"], "waiting")
        self.assertEqual(pending["reasoning"], "")
        self.assertEqual(pending["execution_id"], old_execution)

        second = ai_task_service.claim_next(
            self.runtime, now=utc_now(), started_ticks=ai_transport.now_ticks()
        )
        self.assertIsNotNone(second)
        assert second is not None
        self.assertNotEqual(second.execution_id, old_execution)
        ai_progress.begin(second)
        ai_progress.update(
            second, seq=1, phase="thinking", reasoning_delta="新尝试思考"
        )
        fresh = api.get_ai_task_progress(task["id"], self.session)
        self.assertTrue(fresh["available"])
        self.assertEqual(fresh["execution_id"], second.execution_id)
        self.assertEqual(fresh["reasoning"], "新尝试思考")
        self.assertNotIn("旧失败思考", fresh["reasoning"])

    def test_persistent_terminal_status_fixes_phase_and_clock(self):
        from unittest.mock import patch

        from app.local import ai_task_service, ai_transport, api

        ai_progress.begin_ids(
            task_id="t1", execution_id="e1", attempt_id="a1", attempt_no=1
        )
        claim = _claim("t1", "e1", "a1")
        ai_progress.update(
            claim, seq=1, phase="thinking", reasoning_delta="思考", content_chars=2
        )
        ai_progress.finish(claim, {"kind": ai_transport.SUCCESS, "reason": "ok"})

        live = {"id": "t1", "status": "dispatching", "execution": {"id": "e1", "attempt_no": 1}}
        with patch.object(ai_task_service, "get_task", return_value=live):
            projected = api.get_ai_task_progress("t1", self.session)
        self.assertEqual(projected["phase"], "validating")

        failed = {"id": "t1", "status": "failed", "execution": {"id": "e1", "attempt_no": 1}}
        with patch.object(ai_task_service, "get_task", return_value=failed):
            first = api.get_ai_task_progress("t1", self.session)
            time.sleep(0.03)
            second = api.get_ai_task_progress("t1", self.session)
        self.assertEqual(first["phase"], "failed")
        self.assertEqual(second["phase"], "failed")
        self.assertEqual(first["elapsed_ms"], second["elapsed_ms"])
        self.assertEqual(first["last_data_age_ms"], second["last_data_age_ms"])

        succeeded = {"id": "t1", "status": "succeeded", "execution": {"id": "e1", "attempt_no": 1}}
        with patch.object(ai_task_service, "get_task", return_value=succeeded):
            done = api.get_ai_task_progress("t1", self.session)
        self.assertEqual(done["phase"], "completed")

        new_attempt = {"id": "t1", "status": "dispatching", "execution": {"id": "e1", "attempt_no": 2}}
        with patch.object(ai_task_service, "get_task", return_value=new_attempt):
            stale = api.get_ai_task_progress("t1", self.session)
        self.assertFalse(stale["available"])
        self.assertEqual(stale["attempt_no"], 2)


class WorkerFrameTests(unittest.TestCase):
    def test_overcap_progress_is_dropped_not_a_fake_result(self):
        from app.local import ai_worker

        class _Conn:
            def __init__(self):
                self.frames: list[bytes] = []

            def send_bytes(self, raw: bytes) -> None:
                self.frames.append(raw)

        conn = _Conn()
        ok = ai_worker._send(
            conn,
            {
                "type": "progress",
                "seq": 1,
                "phase": "thinking",
                "reasoning": "汉" * 10_000,
                "content_chars": 0,
            },
        )
        self.assertFalse(ok)
        self.assertEqual(conn.frames, [], "an over-cap progress frame is dropped")

    def test_progress_chunks_cover_large_multibyte_text(self):
        from app.local import ai_worker

        samples = [
            "汉" * 5000,
            "😀" * 3000,
            '"\\' * 4000,
            "\x00" * 5000,
        ]
        for sample in samples:
            chunks = ai_worker._progress_chunks(sample)
            self.assertEqual("".join(chunks), sample)
            for chunk in chunks:
                raw = ai_worker._encode(
                    {
                        "type": "progress",
                        "seq": 1,
                        "phase": "thinking",
                        "reasoning": chunk,
                        "content_chars": 0,
                    }
                )
                self.assertLessEqual(len(raw), ai_worker.CONTROL_FRAME_MAX)


class ProgressStoreTests(unittest.TestCase):
    def tearDown(self):
        ai_progress.clear()

    def test_old_attempt_and_stale_seq_are_rejected(self):
        ai_progress.begin_ids(
            task_id="t1", execution_id="e1", attempt_id="a1", attempt_no=1
        )
        self.assertTrue(
            ai_progress.update(
                _claim("t1", "e1", "a1"),
                seq=1,
                phase="thinking",
                reasoning_delta="first",
            )
        )
        self.assertFalse(
            ai_progress.update(
                _claim("t1", "e1", "a1"),
                seq=1,
                phase="thinking",
                reasoning_delta="less",
            )
        )
        ai_progress.begin_ids(
            task_id="t1", execution_id="e2", attempt_id="a2", attempt_no=1
        )
        self.assertFalse(
            ai_progress.update(
                _claim("t1", "e1", "a1"),
                seq=2,
                phase="thinking",
                reasoning_delta="old",
            )
        )
        snap = ai_progress.snapshot("t1", "e2")
        self.assertEqual(snap["reasoning"], "")

    def test_reasoning_text_is_bounded(self):
        ai_progress.begin_ids(task_id="t", execution_id="e", attempt_id="a")
        for seq in range(1, 7):
            ai_progress.update(
                _claim("t", "e", "a"),
                seq=seq,
                phase="thinking",
                reasoning_delta="x" * ai_progress.MAX_DELTA_CHARS,
            )
        snap = ai_progress.snapshot("t", "e")
        self.assertLessEqual(len(snap["reasoning"]), ai_progress.REASONING_MAX_CHARS)
        self.assertTrue(snap["truncated"])

    def test_local_validating_and_heartbeat_data_clock(self):
        ai_progress.begin_ids(task_id="t", execution_id="e", attempt_id="a")
        ai_progress.update(
            _claim("t", "e", "a"),
            seq=1,
            phase="thinking",
            reasoning_delta="思考",
            content_chars=3,
        )
        first = ai_progress.snapshot("t", "e")
        time.sleep(0.02)
        ai_progress.update(
            _claim("t", "e", "a"),
            seq=2,
            phase="validating",
            reasoning_delta="",
            content_chars=3,
        )
        local = ai_progress.snapshot("t", "e")
        self.assertEqual(local["phase"], "validating")
        self.assertEqual(local["last_data_ticks"], first["last_data_ticks"])

        time.sleep(0.02)
        self.assertTrue(ai_progress.heartbeat(_claim("t", "e", "a"), seq=3))
        beat = ai_progress.snapshot("t", "e")
        self.assertEqual(beat["phase"], "validating")
        self.assertGreater(beat["last_data_ticks"], first["last_data_ticks"])

    def test_finish_records_a_fixed_end(self):
        ai_progress.begin_ids(task_id="t", execution_id="e", attempt_id="a")
        ai_progress.update(
            _claim("t", "e", "a"), seq=1, phase="thinking", reasoning_delta="x"
        )
        ai_progress.finish(
            _claim("t", "e", "a"), {"kind": ai_transport.SUCCESS, "reason": "ok"}
        )
        first = ai_progress.snapshot("t", "e")
        self.assertTrue(first["ended"])
        self.assertGreater(first["ended_at_ticks"], 0)
        time.sleep(0.02)
        ai_progress.finish(
            _claim("t", "e", "a"), {"kind": ai_transport.SUCCESS, "reason": "ok"}
        )
        second = ai_progress.snapshot("t", "e")
        self.assertEqual(second["ended_at_ticks"], first["ended_at_ticks"])


def _claim(task_id: str, execution_id: str, attempt_id: str):
    return type(
        "C",
        (),
        {"task_id": task_id, "execution_id": execution_id, "attempt_id": attempt_id},
    )()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
