"""No-DB ASGI tests for security middleware and error handling.

Uses only the standard library ``asyncio`` to drive the ASGI app directly,
because ``httpx`` is not an installed dependency.
"""

import asyncio
import os

os.environ["APP_DISABLE_DOTENV"] = "1"
os.environ["ALLOWED_ORIGINS"] = "http://localhost:5173,http://127.0.0.1:5173"

import unittest

from app.main import app
from app.rate_limit import limiter


async def _asgi_request(
    method: str,
    path: str,
    headers: dict[str, str | bytes] | None = None,
    body: bytes = b"",
) -> tuple[int, dict[str, list[str]], bytes]:
    headers = dict(headers or {})
    request_headers = []
    for k, v in headers.items():
        name = k.lower().encode("latin-1")
        value = v if isinstance(v, bytes) else v.encode("latin-1")
        request_headers.append((name, value))
    if body and not any(k.lower() == b"content-length" for k, _ in request_headers):
        request_headers.append((b"content-length", str(len(body)).encode("latin-1")))

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "root_path": "",
        "headers": request_headers,
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8000),
        "scheme": "http",
    }

    request_events = [
        {"type": "http.request", "body": body, "more_body": False},
    ]
    request_iter = iter(request_events)

    response_start: dict | None = None
    response_body = bytearray()

    async def receive():
        return next(request_iter)

    async def send(message):
        nonlocal response_start
        if message["type"] == "http.response.start":
            response_start = message
        elif message["type"] == "http.response.body":
            response_body.extend(message.get("body", b""))

    await app(scope, receive, send)
    assert response_start is not None

    grouped: dict[str, list[str]] = {}
    for name, value in response_start["headers"]:
        key = name.decode("latin-1").lower()
        grouped.setdefault(key, []).append(value.decode("latin-1"))
    return response_start["status"], grouped, bytes(response_body)


def asgi_request(
    method: str,
    path: str,
    headers: dict[str, str | bytes] | None = None,
    body: bytes = b"",
) -> tuple[int, dict[str, list[str]], bytes]:
    return asyncio.run(_asgi_request(method, path, headers, body))


class MainSecurityTests(unittest.TestCase):
    def setUp(self):
        limiter.reset()

    def test_register_rejects_unknown_fields(self):
        status, headers, body = asgi_request(
            "POST",
            "/api/auth/register",
            headers={
                "Origin": "http://localhost:5173",
                "Content-Type": "application/json",
            },
            body=b'{"username":"alice","password":"password1234","role":"admin"}',
        )
        self.assertEqual(status, 422)
        self.assertIn("no-store", headers.get("cache-control", []))

    def test_register_requires_exact_origin(self):
        status, _, body = asgi_request(
            "POST",
            "/api/auth/register",
            headers={"Content-Type": "application/json"},
            body=b'{"username":"alice","password":"password1234"}',
        )
        self.assertEqual(status, 403)
        self.assertIn(b'"FORBIDDEN"', body)

    def test_register_rejects_referer_fallback(self):
        status, _, body = asgi_request(
            "POST",
            "/api/auth/register",
            headers={
                "Content-Type": "application/json",
                "Referer": "http://localhost:5173/",
            },
            body=b'{"username":"alice","password":"password1234"}',
        )
        self.assertEqual(status, 403)

    def test_register_requires_json_content_type(self):
        status, _, body = asgi_request(
            "POST",
            "/api/auth/register",
            headers={
                "Origin": "http://localhost:5173",
                "Content-Type": "text/plain",
            },
            body=b'{"username":"alice","password":"password1234"}',
        )
        self.assertEqual(status, 422)
        self.assertIn(b'"VALIDATION_ERROR"', body)

    def test_register_accepts_json_with_charset(self):
        status, _, _ = asgi_request(
            "POST",
            "/api/auth/register",
            headers={
                "Origin": "http://localhost:5173",
                "Content-Type": "application/json; charset=utf-8",
            },
            body=b'{"username":"alice","password":"password1234"}',
        )
        # DATABASE_URL is empty, so the route fails with a desensitized 503.
        self.assertEqual(status, 503)

    def test_get_endpoint_does_not_require_origin(self):
        status, _, body = asgi_request("GET", "/api/auth/me")
        self.assertEqual(status, 401)
        self.assertIn(b'"AUTH_REQUIRED"', body)

    def test_logout_idempotent_with_invalid_unicode_cookie(self):
        status, headers, _ = asgi_request(
            "POST",
            "/api/auth/logout",
            headers={
                "Origin": "http://localhost:5173",
                "Content-Type": "application/json",
                "Cookie": b"session=\xe4\xb8\xad\xe6\x96\x87",
            },
            body=b"{}",
        )
        self.assertEqual(status, 204)
        set_cookie = "; ".join(headers.get("set-cookie", []))
        self.assertIn('session=""', set_cookie)

    def test_rate_limit_returns_retry_after_header(self):
        payload = b'{"username":"alice","password":"password1234"}'
        request_headers = {
            "Origin": "http://localhost:5173",
            "Content-Type": "application/json",
        }
        for _ in range(10):
            asgi_request("POST", "/api/auth/register", request_headers, payload)
        status, headers, _ = asgi_request(
            "POST", "/api/auth/register", request_headers, payload
        )
        self.assertEqual(status, 429)
        self.assertIn("retry-after", headers)
        self.assertTrue(headers["retry-after"][0].isdigit())

    def test_database_unavailable_returns_desensitized_503(self):
        status, _, body = asgi_request(
            "POST",
            "/api/auth/register",
            headers={
                "Origin": "http://localhost:5173",
                "Content-Type": "application/json",
            },
            body=b'{"username":"alice","password":"password1234"}',
        )
        self.assertEqual(status, 503)
        self.assertIn(b'"SERVICE_UNAVAILABLE"', body)
        self.assertNotIn(b"DATABASE_URL", body)
        self.assertNotIn(b"SQL", body)

    def test_register_response_does_not_leak_password_hash(self):
        _, _, body = asgi_request(
            "POST",
            "/api/auth/register",
            headers={
                "Origin": "http://localhost:5173",
                "Content-Type": "application/json",
            },
            body=b'{"username":"alice","password":"password1234"}',
        )
        text = body.lower()
        self.assertNotIn(b"password", text)
        self.assertNotIn(b"hash", text)


if __name__ == "__main__":
    unittest.main()
