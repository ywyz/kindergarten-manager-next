"""End-to-end feedback tests over real loopback HTTP and TLS servers.

Synthetic environment only: a throwaway CA and a leaf certificate for
``127.0.0.1`` are generated per run, both servers are real uvicorn instances
on loopback with temporary SQLite databases under the test root, and the
feedback code/pepper are synthetic values.  The desktop app reaches the
upstream through the production transport; only the TLS trust store is
explicitly injected for this test (``app.state.feedback_ssl_context``), never
an environment override of trust.  No real teacher data, no real secrets and
no real deployment origin are touched.

Covered here (per the accepted feedback scope): the local entry (status and
submit), upstream idempotency (duplicate receipts, single admin row),
permission isolation (anonymous admin access, CSRF, invalid feedback code),
bounded bodies (declared-oversize rejection without reading the remainder,
chunked streams hard-capped at 65 536 bytes), rate limiting, offline
behaviour with an outcome-unknown message, and the admin pagination/filter
API.
"""

from __future__ import annotations

import datetime
import ipaddress
import json
import os
import socket
import ssl
import threading
import time
import unittest
from http.client import HTTPSConnection
from pathlib import Path
from uuid import UUID, uuid4

import uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from app.collaboration.admin_models import AdminUser
from app.collaboration.admin_service import bootstrap_admin
from app.collaboration.config import CollaborationSettings
from app.collaboration.feedback_models import FeedbackSubmission
from app.collaboration.feedback_service import FeedbackRateLimiter
from tests.local.support import LocalServer, LocalTestCase, free_port

SYNTHETIC_PEPPER = "synthetic-feedback-e2e-pepper-0123456789abcdef"
SYNTHETIC_PREVIEW = "synthetic-feedback-e2e-preview-0123456789abcdef"
SYNTHETIC_CODE = "synthetic-feedback-e2e-code-2026"
ADMIN_USERNAME = "feedback-admin"
ADMIN_PASSWORD = "synthetic-admin-password-2026"
APP_VERSION = "0.1.0-feedback-e2e"
MAX_BODY_BYTES = 65_536

UPSTREAM_ORIGIN_ENV = "APP_FEEDBACK_API_ORIGIN"


def _write_test_ca_and_leaf(directory: Path) -> tuple[Path, Path]:
    """A throwaway CA plus a leaf valid for the loopback IP 127.0.0.1.

    Python 3.14's default context enables VERIFY_X509_STRICT, so the CA
    carries critical BasicConstraints/KeyUsage plus a Subject Key Identifier
    and the leaf carries an Authority Key Identifier back to it.  Validation
    is never weakened.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "KGM Feedback E2E CA")]
    )
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=30))
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=None), critical=True
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    leaf_cert = (
        x509.CertificateBuilder()
        .subject_name(
            x509.Name(
                [x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")]
            )
        )
        .issuer_name(ca_cert.subject)
        .public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=30))
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None), critical=True
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(leaf_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(
                ca_key.public_key()
            ),
            critical=False,
        )
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    directory.mkdir(parents=True, exist_ok=True)
    cert_path = directory / "upstream-leaf.pem"
    key_path = directory / "upstream-leaf.key"
    cert_path.write_bytes(leaf_cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        leaf_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    ca_path = directory / "test-ca.pem"
    ca_path.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    return cert_path, key_path, ca_path


def _client_ssl_context(ca_path: Path) -> ssl.SSLContext:
    return ssl.create_default_context(cafile=str(ca_path))


class TlsUpstream:
    """The real feedback/admin ASGI app served over real loopback TLS."""

    def __init__(
        self, app, *, cert: Path, key: Path, port: int
    ) -> None:
        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            ssl_certfile=str(cert),
            ssl_keyfile=str(key),
            log_level="warning",
            access_log=False,
        )
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(
            target=self.server.run, name="feedback-upstream-tls", daemon=True
        )

    def start(self) -> "TlsUpstream":
        self.thread.start()
        deadline = time.time() + 20
        while time.time() < deadline:
            if self.server.started:
                return self
            if not self.thread.is_alive():
                raise AssertionError("upstream TLS server thread exited")
            time.sleep(0.02)
        raise AssertionError("upstream TLS server did not start")

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=20)
        if self.thread.is_alive():
            raise AssertionError("upstream TLS server did not stop")


class AdminTlsClient:
    """Real HTTPS admin client with an explicit cookie/CSRF jar."""

    def __init__(self, port: int, ca_path: Path) -> None:
        self.port = port
        self.ca_path = str(ca_path)
        self.cookie_header = ""
        self.csrf = ""

    def set_cookies(self, set_cookie_entries: list[str]) -> None:
        pairs = [
            entry.split(";", 1)[0] for entry in set_cookie_entries if entry
        ]
        if pairs:
            self.cookie_header = "; ".join(pairs)

    def request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        *,
        csrf: bool = False,
    ) -> tuple[int, object, list[str]]:
        context = _client_ssl_context(Path(self.ca_path))
        connection = HTTPSConnection(
            "127.0.0.1", self.port, context=context, timeout=15
        )
        headers: dict[str, str] = {"Accept": "application/json"}
        if self.cookie_header:
            headers["Cookie"] = self.cookie_header
        if csrf and self.csrf:
            headers["X-CSRF-Token"] = self.csrf
        payload = None
        if body is not None:
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        try:
            connection.request(method, path, body=payload, headers=headers)
            response = connection.getresponse()
            raw = response.read().decode("utf-8")
            status = response.status
            set_cookies = response.headers.get_all("Set-Cookie") or []
        finally:
            connection.close()
        data = json.loads(raw) if raw else None
        return status, data, set_cookies

    def login(self) -> None:
        status, data, set_cookies = self.request(
            "POST",
            "/api/collaboration/admin/login",
            {"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
        )
        if status != 200 or not isinstance(data, dict):
            raise AssertionError(f"admin login failed: {status} {data}")
        self.set_cookies(set_cookies)
        self.csrf = str(data.get("csrf_token", ""))


def _raw_tls_exchange(
    port: int,
    ca_path: Path,
    head: bytes,
    chunks: list[tuple[bytes, float]],
    *,
    read_timeout: float = 5.0,
) -> bytes:
    """Send a hand-built request and read until timeout or close.

    The caller controls exactly how much of the body is sent, so a response
    that arrives before the declared remainder proves the server never read
    it.
    """
    context = _client_ssl_context(ca_path)
    sock = socket.create_connection(("127.0.0.1", port), timeout=10)
    tls = context.wrap_socket(sock, server_hostname="127.0.0.1")
    try:
        tls.sendall(head)
        for chunk, delay in chunks:
            tls.sendall(chunk)
            if delay:
                time.sleep(delay)
        tls.settimeout(read_timeout)
        data = b""
        while True:
            try:
                part = tls.recv(65_536)
            except (socket.timeout, TimeoutError):
                break
            if not part:
                break
            data += part
            if len(data) > 1_000_000:
                break
        return data
    finally:
        try:
            tls.close()
        except OSError:
            pass


def _status_line(raw: bytes) -> str:
    return raw.split(b"\r\n", 1)[0].decode("latin-1", "replace")


class FeedbackEndToEndTests(LocalTestCase):
    def setUp(self) -> None:
        super().setUp()
        import app.collaboration.feedback_service as feedback_service

        self._original_limiter = feedback_service.rate_limiter
        self.limiter = FeedbackRateLimiter(max_per_window=50)
        feedback_service.rate_limiter = self.limiter

        self.cert_path, self.key_path, self.ca_path = _write_test_ca_and_leaf(
            self.tmp_root / "certs"
        )
        self.upstream_app, self.upstream_engine = self._build_upstream(
            self.tmp_root / "upstream" / "feedback.db"
        )
        self.upstream_port = free_port()
        self.upstream = TlsUpstream(
            self.upstream_app,
            cert=self.cert_path,
            key=self.key_path,
            port=self.upstream_port,
        )
        self.upstream.start()
        self.admin = AdminTlsClient(self.upstream_port, self.ca_path)

        self._original_origin = os.environ.get(UPSTREAM_ORIGIN_ENV)
        os.environ[UPSTREAM_ORIGIN_ENV] = (
            f"https://127.0.0.1:{self.upstream_port}"
        )

        self.runtime = self.make_runtime()
        self.runtime.app_version = APP_VERSION
        self.local_server = LocalServer(self.runtime, self.token)
        # Explicit synthetic trust injection for this test only.
        self.local_server.app.state.feedback_ssl_context = _client_ssl_context(
            self.ca_path
        )
        self.local_server.start()
        self.local = self.local_server.client()

    def tearDown(self) -> None:
        import app.collaboration.feedback_service as feedback_service

        feedback_service.rate_limiter = self._original_limiter
        if self._original_origin is None:
            os.environ.pop(UPSTREAM_ORIGIN_ENV, None)
        else:
            os.environ[UPSTREAM_ORIGIN_ENV] = self._original_origin
        self.local_server.stop()
        self.upstream.stop()
        # Release the upstream SQLite file before the temp root is removed.
        self.upstream_engine.dispose()
        super().tearDown()

    def _build_upstream(self, db_path: Path):
        from fastapi import FastAPI
        from fastapi.exceptions import RequestValidationError
        from fastapi.responses import JSONResponse
        from sqlalchemy import create_engine
        from sqlalchemy.exc import SQLAlchemyError
        from sqlalchemy.orm import sessionmaker

        from app.collaboration.admin_api import router as admin_router
        from app.collaboration.admin_models import AdminSession
        from app.collaboration.errors import CollaborationError
        from app.collaboration.feedback_api import (
            add_feedback_body_limit,
            admin_feedback_router,
            feedback_router,
        )

        settings = CollaborationSettings(
            database_url=(
                "mysql+pymysql://synthetic:synthetic@127.0.0.1:3306/"
                "feedback_synthetic"
            ),
            token_pepper=SYNTHETIC_PEPPER,
            preview_secret=SYNTHETIC_PREVIEW,
            feedback_code=SYNTHETIC_CODE,
        )
        db_path.parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False},
        )
        AdminUser.__table__.create(engine)
        AdminSession.__table__.create(engine)
        FeedbackSubmission.__table__.create(engine)
        factory = sessionmaker(
            bind=engine, autoflush=False, expire_on_commit=False
        )
        app = FastAPI()
        app.state.collab_settings = settings
        app.state.session_factory = factory

        @app.exception_handler(CollaborationError)
        async def collaboration_error_handler(_request, exc: CollaborationError):
            payload = {"error": {"code": exc.code, "message": exc.message}}
            if exc.details:
                payload["error"]["details"] = exc.details
            headers = {"Cache-Control": "no-store"}
            headers.update(exc.headers)
            return JSONResponse(
                status_code=exc.status_code, content=payload, headers=headers
            )

        @app.exception_handler(RequestValidationError)
        async def validation_error_handler(_request, _exc):
            return JSONResponse(
                status_code=422,
                content={
                    "error": {
                        "code": "INVALID_REQUEST",
                        "message": "请求参数无效",
                    }
                },
                headers={"Cache-Control": "no-store"},
            )

        @app.exception_handler(SQLAlchemyError)
        async def database_error_handler(_request, _exc):
            return JSONResponse(
                status_code=503,
                content={
                    "error": {
                        "code": "DATABASE_UNAVAILABLE",
                        "message": "在线协作数据库暂时不可用",
                    }
                },
                headers={"Cache-Control": "no-store"},
            )

        app.include_router(admin_router)
        app.include_router(feedback_router)
        app.include_router(admin_feedback_router)
        # Same pure-ASGI body bound as the production collaboration app.
        add_feedback_body_limit(app)
        with factory() as session:
            bootstrap_admin(session, ADMIN_USERNAME, ADMIN_PASSWORD)
        return app, engine

    def submit_feedback(
        self,
        *,
        request_id: UUID | None = None,
        code: str = SYNTHETIC_CODE,
        content: str = "游戏观察导出在周五崩溃了",
        contact: str | None = None,
    ) -> tuple[int, object]:
        return self.local.post(
            "/api/local/feedback/submissions",
            {
                "request_id": str(request_id or uuid4()),
                "feedback_code": code,
                "content": content,
                "contact": contact,
            },
        )

    # -- entry ------------------------------------------------------------

    def test_status_reports_configuration_and_app_version(self):
        status, data = self.local.get("/api/local/feedback/status")
        self.assertEqual(status, 200)
        self.assertTrue(data["configured"])
        self.assertEqual(data["app_version"], APP_VERSION)

    def test_status_reports_unconfigured_without_origin(self):
        saved = os.environ.pop(UPSTREAM_ORIGIN_ENV)
        try:
            status, data = self.local.get("/api/local/feedback/status")
        finally:
            os.environ[UPSTREAM_ORIGIN_ENV] = saved
        self.assertEqual(status, 200)
        self.assertFalse(data["configured"])
        self.assertTrue(data["message"])

    # -- submission, idempotency and admin visibility ----------------------

    def test_submit_creates_row_and_admin_sees_it(self):
        request_id = uuid4()
        status, receipt = self.submit_feedback(request_id=request_id)
        self.assertEqual(status, 200)
        self.assertEqual(receipt["request_id"], str(request_id))
        self.assertFalse(receipt["replayed"])
        UUID(receipt["submission_id"])

        # Anonymous admin access stays isolated.
        anon = AdminTlsClient(self.upstream_port, self.ca_path)
        status, data, _cookies = anon.request(
            "GET", "/api/collaboration/admin/feedback"
        )
        self.assertEqual(status, 401)
        self.assertEqual(data["error"]["code"], "ADMIN_AUTH_REQUIRED")

        self.admin.login()
        status, page, _cookies = self.admin.request(
            "GET", "/api/collaboration/admin/feedback?limit=10"
        )
        self.assertEqual(status, 200)
        self.assertEqual(page["total"], 1)
        self.assertEqual(len(page["items"]), 1)
        item = page["items"][0]
        self.assertEqual(item["request_id"], str(request_id))
        self.assertEqual(item["content"], "游戏观察导出在周五崩溃了")
        self.assertEqual(item["app_version"], APP_VERSION)
        self.assertEqual(item["status"], "new")

    def test_duplicate_submission_replays_without_duplicate(self):
        request_id = uuid4()
        first_status, first = self.submit_feedback(request_id=request_id)
        self.assertEqual(first_status, 200)
        retry_status, retry = self.submit_feedback(request_id=request_id)
        self.assertEqual(retry_status, 200)
        self.assertTrue(retry["replayed"])
        self.assertEqual(retry["submission_id"], first["submission_id"])
        self.admin.login()
        _status, page, _cookies = self.admin.request(
            "GET", "/api/collaboration/admin/feedback"
        )
        self.assertEqual(page["total"], 1)

    def test_invalid_code_rejected_without_storage(self):
        status, error = self.submit_feedback(code="wrong-code")
        self.assertEqual(status, 400)
        self.assertEqual(error["error"]["code"], "FEEDBACK_CODE_INVALID")
        self.admin.login()
        _status, page, _cookies = self.admin.request(
            "GET", "/api/collaboration/admin/feedback"
        )
        self.assertEqual(page["total"], 0)

    # -- permissions --------------------------------------------------------

    def test_admin_status_update_requires_csrf_and_respects_conflicts(self):
        _status, receipt = self.submit_feedback()
        submission_id = receipt["submission_id"]
        self.admin.login()
        # Missing CSRF header: rejected even with a valid session.
        status, data, _cookies = self.admin.request(
            "PATCH",
            f"/api/collaboration/admin/feedback/{submission_id}",
            {"expected_status": "new", "new_status": "processing"},
        )
        self.assertEqual(status, 403)
        self.assertEqual(data["error"]["code"], "ADMIN_CSRF_INVALID")
        status, item, _cookies = self.admin.request(
            "PATCH",
            f"/api/collaboration/admin/feedback/{submission_id}",
            {"expected_status": "new", "new_status": "processing"},
            csrf=True,
        )
        self.assertEqual(status, 200)
        self.assertEqual(item["status"], "processing")
        self.assertEqual(item["handled_by_admin_username"], ADMIN_USERNAME)
        # Stale baseline is a controlled conflict, never a silent overwrite.
        status, data, _cookies = self.admin.request(
            "PATCH",
            f"/api/collaboration/admin/feedback/{submission_id}",
            {"expected_status": "new", "new_status": "resolved"},
            csrf=True,
        )
        self.assertEqual(status, 409)
        self.assertEqual(data["error"]["code"], "FEEDBACK_STATUS_CONFLICT")
        self.assertEqual(data["error"]["details"]["current_status"], "processing")

    # -- offline and rate limiting ------------------------------------------

    def test_upstream_offline_reports_unknown_outcome(self):
        self.upstream.stop()
        status, error = self.submit_feedback()
        self.assertEqual(status, 503)
        self.assertEqual(
            error["error"]["code"], "FEEDBACK_NETWORK_UNAVAILABLE"
        )
        # The outcome is genuinely unknown after a transport failure: the
        # message must not claim the feedback was "not sent".
        self.assertNotIn("未发送", error["error"]["message"])
        self.assertIn("未确认", error["error"]["message"])

    def test_rate_limit_is_enforced_per_ip(self):
        import app.collaboration.feedback_service as feedback_service

        feedback_service.rate_limiter = FeedbackRateLimiter(max_per_window=2)
        for _ in range(2):
            status, _receipt = self.submit_feedback()
            self.assertEqual(status, 200)
        status, error = self.submit_feedback()
        self.assertEqual(status, 429)
        self.assertEqual(error["error"]["code"], "FEEDBACK_RATE_LIMITED")

    # -- bounded bodies -----------------------------------------------------

    def test_oversized_declared_body_rejected_without_reading_remainder(self):
        head = (
            "POST /api/collaboration/feedback/submissions HTTP/1.1\r\n"
            "Host: 127.0.0.1\r\n"
            "Content-Type: application/json\r\n"
            "Content-Length: 70000\r\n"
            "\r\n"
        ).encode("ascii")
        raw = _raw_tls_exchange(
            self.upstream_port,
            self.ca_path,
            head,
            [(b"x" * 1000, 0.3)],
            read_timeout=5.0,
        )
        self.assertTrue(raw, "no response before the declared remainder")
        self.assertTrue(_status_line(raw).startswith("HTTP/1.1 413"), raw[:120])
        self.assertIn(b"REQUEST_TOO_LARGE", raw)

    def test_chunked_stream_is_hard_capped(self):
        head = (
            "POST /api/collaboration/feedback/submissions HTTP/1.1\r\n"
            "Host: 127.0.0.1\r\n"
            "Content-Type: application/json\r\n"
            "Transfer-Encoding: chunked\r\n"
            "\r\n"
        ).encode("ascii")

        def frame(data: bytes) -> bytes:
            return f"{len(data):x}\r\n".encode("ascii") + data + b"\r\n"

        filler = b"y" * 8000
        chunks = [(frame(filler), 0.0) for _ in range(8)]
        chunks.append((frame(b"z" * 2000), 0.3))  # total 66000 > cap
        raw = _raw_tls_exchange(
            self.upstream_port, self.ca_path, head, chunks, read_timeout=5.0
        )
        self.assertTrue(raw, "no response before the chunked remainder")
        self.assertTrue(_status_line(raw).startswith("HTTP/1.1 413"), raw[:120])

    def test_chunked_submission_within_cap_succeeds(self):
        head = (
            "POST /api/collaboration/feedback/submissions HTTP/1.1\r\n"
            "Host: 127.0.0.1\r\n"
            "Content-Type: application/json\r\n"
            "Transfer-Encoding: chunked\r\n"
            "\r\n"
        ).encode("ascii")
        payload = json.dumps(
            {
                "request_id": str(uuid4()),
                "feedback_code": SYNTHETIC_CODE,
                "content": "分块提交的合成反馈",
                "contact": None,
                "app_version": APP_VERSION,
            },
            ensure_ascii=False,
        ).encode("utf-8")

        def frame(data: bytes) -> bytes:
            return f"{len(data):x}\r\n".encode("ascii") + data + b"\r\n"

        frames = b"".join(
            frame(payload[index : index + 120])
            for index in range(0, len(payload), 120)
        )
        chunks = [(frames, 0.2), (b"0\r\n\r\n", 0.0)]
        raw = _raw_tls_exchange(
            self.upstream_port, self.ca_path, head, chunks, read_timeout=5.0
        )
        self.assertTrue(_status_line(raw).startswith("HTTP/1.1 200"), raw[:200])
        self.assertIn(b'"replayed":false', raw)

    # -- over-limit bodies never reach the write path -------------------------

    def _spy_write_path(self):
        """Patch the route's write function and record every invocation."""
        import app.collaboration.feedback_api as feedback_api
        from unittest.mock import patch as mock_patch

        real_submit = feedback_api.submit_feedback
        calls: list[int] = []

        def spy(*args, **kwargs):
            calls.append(1)
            return real_submit(*args, **kwargs)

        return mock_patch.object(feedback_api, "submit_feedback", spy), calls

    def _stored_feedback_count(self) -> int:
        from sqlalchemy import func, select

        with self.upstream_engine.connect() as connection:
            return int(
                connection.scalar(
                    select(func.count()).select_from(FeedbackSubmission)
                )
            )

    def test_valid_json_prefix_over_limit_never_reaches_write_path(self):
        # Regression for the independent ASGI reproduction: the first chunk
        # carries a complete, valid submission JSON followed by padding, so
        # the truncated stream would still parse.  The old capped-receive
        # design let the endpoint commit the submission and only rewrote the
        # response to 413 afterwards.  The fixed middleware must answer 413
        # without invoking the write path at all.
        head = (
            "POST /api/collaboration/feedback/submissions HTTP/1.1\r\n"
            "Host: 127.0.0.1\r\n"
            "Content-Type: application/json\r\n"
            "Transfer-Encoding: chunked\r\n"
            "\r\n"
        ).encode("ascii")
        payload = json.dumps(
            {
                "request_id": str(uuid4()),
                "feedback_code": SYNTHETIC_CODE,
                "content": "合法前缀加超限填充",
                "contact": None,
                "app_version": APP_VERSION,
            },
            ensure_ascii=False,
        ).encode("utf-8")

        def frame(data: bytes) -> bytes:
            return f"{len(data):x}\r\n".encode("ascii") + data + b"\r\n"

        # Chunk 1 alone parses as valid JSON (JSON allows trailing spaces);
        # chunk 2 pushes the cumulative stream past the 65 536-byte cap.
        # Chunk 3 is never sent: the response must arrive without it.
        chunks = [
            (frame(payload + b" " * 40_000), 0.3),
            (frame(b" " * 40_000), 0.3),
        ]
        patcher, calls = self._spy_write_path()
        with patcher:
            raw = _raw_tls_exchange(
                self.upstream_port,
                self.ca_path,
                head,
                chunks,
                read_timeout=5.0,
            )
        self.assertTrue(raw, "no response before the third chunk")
        self.assertTrue(_status_line(raw).startswith("HTTP/1.1 413"), raw[:120])
        self.assertIn(b"REQUEST_TOO_LARGE", raw)
        self.assertEqual(calls, [], "the write path ran for an over-limit body")
        self.assertEqual(self._stored_feedback_count(), 0)

    def test_client_disconnect_during_body_never_reaches_write_path(self):
        head = (
            "POST /api/collaboration/feedback/submissions HTTP/1.1\r\n"
            "Host: 127.0.0.1\r\n"
            "Content-Type: application/json\r\n"
            "Content-Length: 10000\r\n"
            "\r\n"
        ).encode("ascii")
        patcher, calls = self._spy_write_path()
        with patcher:
            context = _client_ssl_context(self.ca_path)
            sock = socket.create_connection(
                ("127.0.0.1", self.upstream_port), timeout=10
            )
            tls = context.wrap_socket(sock, server_hostname="127.0.0.1")
            tls.sendall(head)
            tls.sendall(b"x" * 10)
            # Abrupt disconnect before the declared body completes.
            tls.close()
            time.sleep(0.5)
        self.assertEqual(calls, [], "a vanished client must not be persisted")
        # The server stays healthy and normal submissions still persist.
        status, _receipt = self.submit_feedback()
        self.assertEqual(status, 200)
        self.assertEqual(self._stored_feedback_count(), 1)

    # -- local input bounds --------------------------------------------------

    def test_local_rejects_oversize_and_control_characters(self):
        status, error = self.submit_feedback(content="x" * 4001)
        self.assertEqual(status, 422)
        status, error = self.submit_feedback(content="bad\x00content")
        self.assertEqual(status, 422)

    # -- admin pagination ------------------------------------------------------

    def test_admin_pagination_and_status_filter(self):
        for index in range(3):
            _status, _receipt = self.submit_feedback(
                content=f"合成反馈 {index}"
            )
        self.admin.login()
        first_status, first, _cookies = self.admin.request(
            "GET", "/api/collaboration/admin/feedback?limit=2&offset=0"
        )
        self.assertEqual(first_status, 200)
        self.assertEqual(first["total"], 3)
        self.assertEqual(len(first["items"]), 2)
        self.assertEqual(first["offset"], 0)
        self.assertEqual(first["limit"], 2)
        _status, second, _cookies = self.admin.request(
            "GET", "/api/collaboration/admin/feedback?limit=2&offset=2"
        )
        self.assertEqual(second["total"], 3)
        self.assertEqual(len(second["items"]), 1)
        self.assertNotEqual(
            second["items"][0]["submission_id"],
            first["items"][0]["submission_id"],
        )
        target_id = first["items"][0]["submission_id"]
        _status, updated, _cookies = self.admin.request(
            "PATCH",
            f"/api/collaboration/admin/feedback/{target_id}",
            {"expected_status": "new", "new_status": "resolved"},
            csrf=True,
        )
        self.assertEqual(updated["status"], "resolved")
        _status, resolved_page, _cookies = self.admin.request(
            "GET", "/api/collaboration/admin/feedback?status=resolved"
        )
        self.assertEqual(resolved_page["total"], 1)
        self.assertEqual(resolved_page["items"][0]["submission_id"], target_id)
        _status, new_page, _cookies = self.admin.request(
            "GET", "/api/collaboration/admin/feedback?status=new"
        )
        self.assertEqual(new_page["total"], 2)


if __name__ == "__main__":
    unittest.main()
