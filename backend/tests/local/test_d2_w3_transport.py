"""D2 W3 transport tests (engineering spec §4.2, G07).

Pure framing / policy tests use a fake socket; a real controlled-TLS server
exercises the actual ``prepare`` + ``send`` path with a test CA and a fixed
synthetic resolution (verification entry only).
"""

from __future__ import annotations

import io
import json
import socket
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from tests.local import w3_tls
from app.local import ai_transport as tr
from app.local.errors import LocalValidationError


class FakeSock:
    def __init__(self, payload: bytes):
        self._raw = io.BytesIO(payload)
        self.sent: list[bytes] = []

    def sendall(self, data):  # noqa: ANN001
        self.sent.append(bytes(data))

    def settimeout(self, _timeout):  # noqa: ANN001
        pass

    def makefile(self, _mode, buffering=0):  # noqa: ANN001
        return self._raw

    def close(self):  # noqa: ANN001
        pass


def _prepared(payload: bytes) -> tr.Prepared:
    return tr.Prepared(
        sock=FakeSock(payload), host="api.example.com", netloc="api.example.com",
        path="/chat/completions", request_bytes=b"",
    )


def _resp(headers: bytes, body: bytes) -> bytes:
    return headers + b"\r\n\r\n" + body


def _envelope(content, **extra) -> bytes:
    payload = {
        "choices": [
            {
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ]
    }
    payload.update(extra)
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


SPLIT = json.dumps(
    {
        "group_activity": {
            "theme": "", "objectives": "", "preparation": "",
            "key_points": "", "difficult_points": "", "process": "",
        }
    }
)


class TargetPathTests(unittest.TestCase):
    def test_prefix_preserved_and_appended_once(self):
        for base, expected in (
            ("https://api.example.com", "/chat/completions"),
            ("https://api.example.com/v1", "/v1/chat/completions"),
            ("https://api.example.com/v1/", "/v1/chat/completions"),
            ("https://api.example.com/openai/v1", "/openai/v1/chat/completions"),
        ):
            url, host, port, netloc, path = tr.build_target(base)
            self.assertEqual(path, expected)
            self.assertEqual(url, "https://" + netloc + expected)
            self.assertEqual(host, "api.example.com")
            self.assertEqual(port, 443)

    def test_full_completion_path_refused(self):
        with self.assertRaises(LocalValidationError):
            tr.build_target("https://api.example.com/v1/chat/completions")

    def test_request_line_uses_prefix_path(self):
        body = tr.build_request(model="m", system_text="s", user_text="u")
        raw = tr._http_request_bytes(
            netloc="api.example.com", path="/v1/chat/completions", secret="k", body=body
        )
        self.assertTrue(raw.startswith(b"POST /v1/chat/completions HTTP/1.1\r\n"))
        self.assertIn(b"Host: api.example.com\r\n", raw)
        self.assertIn(b"Accept-Encoding: identity\r\n", raw)
        self.assertIn(b"Connection: close\r\n", raw)


class AddressPolicyTests(unittest.TestCase):
    def test_mixed_public_private_refused(self):
        with mock.patch("socket.getaddrinfo") as fake:
            fake.return_value = [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 443)),
            ]
            addresses, failure = tr.resolve_addresses("api.example.com", 443)
        self.assertIsNotNone(failure)
        self.assertEqual(failure.detail, tr.DETAIL["resolution_policy"])

    def test_loopback_refused_without_synthetic(self):
        with mock.patch("socket.getaddrinfo") as fake:
            fake.return_value = [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))
            ]
            addresses, failure = tr.resolve_addresses("api.example.com", 443)
        self.assertIsNotNone(failure)
        self.assertEqual(failure.detail, tr.DETAIL["resolution_policy"])

    def test_too_many_addresses_refused(self):
        resolver = [
            {"family": socket.AF_INET, "ip": f"93.184.216.{i}"} for i in range(1, 40)
        ]
        addresses, failure = tr.resolve_addresses("h", 443, resolver=resolver)
        self.assertIsNotNone(failure)
        self.assertEqual(failure.detail, tr.DETAIL["resolution_too_many"])

    def test_synthetic_resolver_allows_loopback(self):
        addresses, failure = tr.resolve_addresses(
            "api.example.com", 443,
            resolver=[{"family": socket.AF_INET, "ip": "127.0.0.1", "port": 8443}],
        )
        self.assertIsNone(failure)
        self.assertEqual(addresses, [(socket.AF_INET, "127.0.0.1", 8443)])


class FramingTests(unittest.TestCase):
    def _send(self, payload: bytes) -> tr.TransportResult:
        return tr.send(_prepared(payload), deadline_ms=tr.now_ticks() + 60_000)

    def test_normal_success(self):
        body = _envelope(SPLIT, model="returned", usage={"prompt_tokens": 3, "evil": 1})
        result = self._send(
            _resp(f"HTTP/1.1 200 OK\r\nContent-Length: {len(body)}".encode(), body)
        )
        self.assertEqual(result.kind, tr.SUCCESS)
        self.assertEqual(result.returned_model, "returned")
        self.assertEqual(result.usage, {"prompt_tokens": 3})
        self.assertTrue(result.sent)

    def test_declared_length_longer_than_body_refused(self):
        body = _envelope(SPLIT)
        result = self._send(
            _resp(f"HTTP/1.1 200 OK\r\nContent-Length: {len(body) + 100}".encode(), body)
        )
        self.assertEqual(result.kind, tr.PROVIDER_ERROR)
        self.assertEqual(result.detail, tr.DETAIL["length_mismatch"])

    def test_duplicate_content_length_refused(self):
        body = _envelope(SPLIT)
        headers = (
            f"HTTP/1.1 200 OK\r\nContent-Length: {len(body)}\r\n"
            f"Content-Length: {len(body)}"
        ).encode()
        result = self._send(_resp(headers, body))
        self.assertEqual(result.detail, tr.DETAIL["duplicate_header"])

    def test_unsupported_transfer_encoding_refused(self):
        result = self._send(_resp(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: nonsense", _envelope(SPLIT)))
        self.assertEqual(result.detail, tr.DETAIL["bad_transfer_encoding"])

    def test_length_and_transfer_conflict_refused(self):
        body = _envelope(SPLIT)
        headers = (
            f"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nContent-Length: {len(body)}"
        ).encode()
        result = self._send(_resp(headers, body))
        self.assertEqual(result.detail, tr.DETAIL["length_conflict"])

    def test_chunked_ok_and_truncated(self):
        body = _envelope(SPLIT)
        good = (
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n"
            + hex(len(body))[2:].encode()
            + b"\r\n"
            + body
            + b"\r\n0\r\n\r\n"
        )
        self.assertEqual(self._send(good).kind, tr.SUCCESS)
        truncated = (
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n"
            + hex(len(body))[2:].encode()
            + b"\r\n"
            + body[:10]
        )
        self.assertEqual(self._send(truncated).detail, tr.DETAIL["malformed_frame"])

    def test_content_encoding_refused(self):
        result = self._send(
            _resp(b"HTTP/1.1 200 OK\r\nContent-Encoding: gzip\r\nContent-Length: 3", b"abc")
        )
        self.assertEqual(result.detail, tr.DETAIL["bad_content_encoding"])

    def test_status_classification(self):
        cases = {
            301: (tr.POLICY, True),
            401: (tr.AUTH, True),
            403: (tr.AUTH, True),
            429: (tr.RATE_LIMITED, True),
            400: (tr.CONFIG_REJECTED, True),
            503: (tr.PROVIDER_ERROR, True),
        }
        for status, (kind, sent) in cases.items():
            result = self._send(_resp(f"HTTP/1.1 {status} x\r\nContent-Length: 2".encode(), b"{}"))
            self.assertEqual(result.kind, kind, status)
            self.assertTrue(result.sent, status)
        redirect = self._send(_resp(b"HTTP/1.1 302 x\r\nLocation: https://evil\r\nContent-Length: 0", b""))
        self.assertEqual(redirect.kind, tr.POLICY)
        self.assertTrue(redirect.sent)

    def test_envelope_rules(self):
        def envelope_message(message_extra=None, finish="stop", **extra):
            message = {"role": "assistant", "content": SPLIT}
            if message_extra:
                message.update(message_extra)
            payload = {
                "choices": [{"message": message, "finish_reason": finish}],
            }
            payload.update(extra)
            return json.dumps(payload, ensure_ascii=False).encode("utf-8")

        two_choices = json.dumps(
            {
                "choices": [
                    {"message": {"content": SPLIT}, "finish_reason": "stop"},
                    {"message": {"content": SPLIT}, "finish_reason": "stop"},
                ]
            }
        ).encode("utf-8")
        cases = {
            "two_choices": two_choices,
            "not_stop": envelope_message(finish="length"),
            "tool_calls": envelope_message({"tool_calls": [{"id": "x"}]}),
            "function_call": envelope_message({"function_call": {"name": "f"}}),
            "refusal": envelope_message({"refusal": "no"}),
            "non_text": envelope_message({"content": 5}),
            "free_text": _envelope("这是解释，不是 JSON"),
            "fenced": _envelope("```json\n" + SPLIT + "\n```"),
            "duplicate_key": _envelope('{"group_activity":{},"group_activity":{}}'),
            "nan": _envelope('{"group_activity":{"theme":NaN}}'),
        }
        for name, body in cases.items():
            result = self._send(
                _resp(f"HTTP/1.1 200 OK\r\nContent-Length: {len(body)}".encode(), body)
            )
            self.assertEqual(result.kind, tr.OUTPUT_INVALID, name)
            self.assertIsNone(result.candidate_text, name)

    def test_request_id_and_model_sanitized(self):
        body = _envelope(SPLIT, model="x" * 500)
        headers = (
            f"HTTP/1.1 200 OK\r\nX-Request-Id: {'r' * 300}\r\nContent-Length: {len(body)}"
        ).encode()
        result = self._send(_resp(headers, body))
        self.assertIsNone(result.returned_model)
        self.assertIsNone(result.provider_request_id)

    def test_prepare_failures_are_not_sent(self):
        # A policy-refused target never writes a byte.
        prepared, failure = tr.prepare(
            base_url="https://127.0.0.1/v1", model="m", secret="k",
            system_text="s", user_text="u", deadline_ms=tr.now_ticks() + 5000,
        )
        self.assertIsNone(prepared)
        self.assertEqual(failure.kind, tr.POLICY)
        self.assertFalse(failure.sent)


class StrictJsonTests(unittest.TestCase):
    def test_duplicate_and_nan_rejected(self):
        with self.assertRaises(ValueError):
            tr.parse_strict_json_object('{"a":1,"a":2}')
        with self.assertRaises(ValueError):
            tr.parse_strict_json_object('{"a":NaN}')
        with self.assertRaises(ValueError):
            tr.parse_strict_json_object("[1,2]")
        self.assertEqual(tr.parse_strict_json_object('{"a": 1}'), {"a": 1})


class RealTlsTests(unittest.TestCase):
    def setUp(self):
        self._temp = TemporaryDirectory(prefix="kgm-w3-tls-")
        self.addCleanup(self._temp.cleanup)
        root = Path(self._temp.name)
        ca_dir = root / "ca"
        ca_cert, ca_key, ca_pem = w3_tls.create_ca(ca_dir)
        leaf_cert, leaf_key = w3_tls.create_leaf(ca_dir, root / "leaf")
        self.ca_pem = ca_pem.decode("utf-8")
        self._server = w3_tls.TlsServer(
            cert=leaf_cert, key=leaf_key,
            reply=w3_tls.envelope(SPLIT, usage={"prompt_tokens": 2}),
        ).start()
        self.addCleanup(self._server.stop)

    def _resolver(self):
        return [{"family": socket.AF_INET, "ip": "127.0.0.1", "port": self._server.port}]

    def test_prepare_ready_then_send_once(self):
        prepared, failure = tr.prepare(
            base_url="https://api.example.com/v1",
            model="test-model",
            secret="secret-value",
            system_text="system-prompt",
            user_text='{"plan_date":"2026-09-02"}',
            deadline_ms=tr.now_ticks() + 20_000,
            resolver=self._resolver(),
            ca_pem=self.ca_pem,
        )
        self.assertIsNone(failure)
        self.assertIsNotNone(prepared)
        # No HTTP byte may have reached the server yet.
        self.assertEqual(len(self._server.requests), 0)
        result = tr.send(prepared, deadline_ms=tr.now_ticks() + 20_000)
        self.assertEqual(result.kind, tr.SUCCESS)
        self.assertEqual(result.candidate_text, SPLIT)
        self.assertEqual(len(self._server.requests), 1)
        request = self._server.requests[0]
        self.assertTrue(request.startswith(b"POST /v1/chat/completions HTTP/1.1"))
        self.assertIn(b"Authorization: Bearer secret-value", request)
        self.assertIn(b'"stream":false', request)

    def test_wrong_ca_fails_closed(self):
        prepared, failure = tr.prepare(
            base_url="https://api.example.com",
            model="test-model", secret="k", system_text="s", user_text="u",
            deadline_ms=tr.now_ticks() + 20_000,
            resolver=self._resolver(),
            ca_pem=None,
        )
        self.assertIsNone(prepared)
        self.assertEqual(failure.kind, tr.TLS_INVALID)
        self.assertEqual(failure.reason, "tls_invalid")
        self.assertFalse(failure.sent)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
