"""D4 E12 observation export host channel: fixed loopback, no redirect/proxy.

Synthetic loopback servers and synthetic DOCX bytes only. No real teacher
data, credential, package or application AI call is used.
"""

from __future__ import annotations

import hashlib
import http.server
import io
import json
import os
import threading
import time
import uuid
import zipfile
from pathlib import Path

import pytest

import d1_host_api
from d1_host_api import D1HostApi, write_stream_atomic

_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    "</Types>"
)
_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
    "</Relationships>"
)


def minimal_docx(text: str = "观察导出验证") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _CONTENT_TYPES)
        archive.writestr("_rels/.rels", _RELS)
        archive.writestr(
            "word/document.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>",
        )
    return buffer.getvalue()


DOCX_BYTES = minimal_docx()


class FakeState:
    def __init__(self):
        self.attempt_calls = 0
        self.content_calls = 0
        self.result_calls: list[dict] = []
        self.latest_status = "in_progress"
        self.content_mode = "ok"
        self.attempt_redirect = False
        self.content_redirect = False
        self.trickle_content = False
        self.trickle_json = False
        self.slow_headers = False
        self.trickle_headers = False
        self.will_close_body = False
        self.redirect_target_port = 0
        self.steal_hits = 0
        self.sleep_seconds = 0.0
        self.proxy_hits = 0
        self.attempt_response: dict | None = None
        self.lock = threading.Lock()


def make_handler(state: FakeState):
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):  # noqa: ANN002
            pass

        def _json(self, status: int, body: dict):
            raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _redirect(self):
            self.send_response(302)
            self.send_header(
                "Location",
                f"http://127.0.0.1:{state.redirect_target_port}/steal",
            )
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _trickle_headers(self, content_type: str, length: int, digest: str | None = None):
            lines = [
                "HTTP/1.1 200 OK",
                f"Content-Type: {content_type}",
                f"Content-Length: {length}",
            ]
            if digest is not None:
                lines.append(f"X-Content-SHA256: {digest}")
            raw = ("\r\n".join(lines) + "\r\n\r\n").encode("ascii")
            for offset in range(0, len(raw), 4):
                self.wfile.write(raw[offset : offset + 4])
                self.wfile.flush()
                time.sleep(0.04)

        def do_GET(self):  # noqa: N802
            with state.lock:
                state.proxy_hits += 1
            if self.path == "/steal":
                with state.lock:
                    state.steal_hits += 1
                self._json(200, {"stolen": True})
                return
            if self.path.startswith("/api/observation-exports/") and self.path.endswith(
                "/content"
            ):
                with state.lock:
                    state.content_calls += 1
                if state.sleep_seconds:
                    time.sleep(state.sleep_seconds)
                if state.content_redirect:
                    self._redirect()
                    return
                if state.slow_headers:
                    time.sleep(0.5)
                data = DOCX_BYTES
                if state.content_mode == "truncated":
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(data) + 20))
                    self.send_header("X-Content-SHA256", hashlib.sha256(data).hexdigest())
                    self.end_headers()
                    self.wfile.write(data)
                    return
                if state.content_mode == "bad_hash":
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("X-Content-SHA256", "0" * 64)
                    self.end_headers()
                    self.wfile.write(data)
                    return
                if state.content_mode == "oversized":
                    self.send_response(200)
                    self.send_header(
                        "Content-Length",
                        str(d1_host_api.MAX_OBSERVATION_EXPORT_BYTES + 1),
                    )
                    self.send_header("X-Content-SHA256", hashlib.sha256(data).hexdigest())
                    self.end_headers()
                    return
                if state.will_close_body:
                    headers = (
                        "HTTP/1.0 200 OK\r\n"
                        f"Content-Length: {len(data)}\r\n"
                        f"X-Content-SHA256: {hashlib.sha256(data).hexdigest()}\r\n"
                        "Connection: close\r\n\r\n"
                    ).encode("ascii")
                    self.wfile.write(headers + data[:1])
                    self.wfile.flush()
                    time.sleep(0.12)
                    self.wfile.write(data[1:2])
                    self.wfile.flush()
                    time.sleep(0.5)
                    return
                if state.trickle_headers:
                    self._trickle_headers(
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        len(data),
                        hashlib.sha256(data).hexdigest(),
                    )
                    self.wfile.write(data)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("X-Content-SHA256", hashlib.sha256(data).hexdigest())
                self.end_headers()
                if state.trickle_content:
                    for offset in range(0, len(data), 32):
                        self.wfile.write(data[offset : offset + 32])
                        self.wfile.flush()
                        time.sleep(0.04)
                else:
                    self.wfile.write(data)
                return
            if self.path.startswith("/api/observation-exports/") and self.path.endswith(
                "/attempts/latest"
            ):
                if state.slow_headers:
                    time.sleep(0.5)
                body = {
                    "attempt_id": "attempt-1",
                    "status": state.latest_status,
                    "byte_size": 123 if state.latest_status == "saved" else None,
                    "result_hash": "a" * 64 if state.latest_status == "saved" else None,
                }
                if state.will_close_body:
                    raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
                    headers = (
                        "HTTP/1.0 200 OK\r\n"
                        f"Content-Length: {len(raw)}\r\n"
                        "Connection: close\r\n\r\n"
                    ).encode("ascii")
                    self.wfile.write(headers + raw[:1])
                    self.wfile.flush()
                    time.sleep(0.12)
                    self.wfile.write(raw[1:2])
                    self.wfile.flush()
                    time.sleep(0.5)
                    return
                if state.trickle_headers:
                    raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
                    self._trickle_headers("application/json", len(raw))
                    self.wfile.write(raw)
                    return
                if state.trickle_json:
                    raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    for offset in range(0, len(raw), 8):
                        self.wfile.write(raw[offset : offset + 8])
                        self.wfile.flush()
                        time.sleep(0.04)
                    return
                self._json(200, body)
                return
            self._json(404, {"error": {"code": "NOT_FOUND", "message": "not found"}})

        def do_POST(self):  # noqa: N802
            with state.lock:
                state.proxy_hits += 1
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            if self.path.startswith("/api/observation-exports/") and self.path.endswith(
                "/attempts"
            ):
                with state.lock:
                    state.attempt_calls += 1
                if state.attempt_redirect:
                    self._redirect()
                    return
                if state.attempt_response is not None:
                    self._json(200, state.attempt_response)
                    return
                self._json(
                    200,
                    {
                        "attempt_id": "attempt-1",
                        "status": "in_progress",
                        "filename": "观察.docx",
                        "should_prompt": True,
                        "byte_size": None,
                        "result_hash": None,
                    },
                )
                return
            if self.path.startswith("/api/observation-exports/") and self.path.endswith(
                "/result"
            ):
                with state.lock:
                    state.result_calls.append(json.loads(raw.decode("utf-8")))
                body = json.loads(raw.decode("utf-8"))
                self._json(
                    200,
                    {
                        "attempt_id": "attempt-1",
                        "status": body.get("status"),
                        "byte_size": body.get("byte_size"),
                        "result_hash": body.get("result_hash"),
                    },
                )
                return
            self._json(404, {"error": {"code": "NOT_FOUND", "message": "not found"}})

    return Handler


class LoopbackServer:
    def __init__(self, state: FakeState):
        self.state = state
        self.server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), make_handler(state)
        )
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(
            target=self.server.serve_forever, daemon=True
        )

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):  # noqa: ANN002
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=10)


def make_api(tmp_path, port, *, verify=True, dialog_result=None):
    class FakeWindow:
        def create_file_dialog(self, *args, **kwargs):  # noqa: ANN002
            return dialog_result

    api = D1HostApi(
        launch_token="SYNTHETIC-NOT-A-CREDENTIAL",
        window_getter=lambda: FakeWindow(),
        verify_save_dir=(tmp_path / "verify" if verify else None),
        service_port=port,
    )
    api.page_ready({"bridge_protocol": 1})
    return api


def test_local_json_redirect_is_not_followed(tmp_path):
    target_state = FakeState()
    source_state = FakeState()
    with LoopbackServer(target_state) as target, LoopbackServer(source_state) as source:
        source_state.redirect_target_port = target.port
        source_state.attempt_redirect = True
        api = make_api(tmp_path, source.port)
        with pytest.raises(d1_host_api._LocalApiError) as caught:
            api._local_json("POST", "/api/observation-exports/x/attempts", {"filename": "a.docx"})
        assert caught.value.code == "EXPORT_LOCAL_API_REDIRECT"
        assert target_state.steal_hits == 0
        assert target_state.attempt_calls == 0
        assert source_state.attempt_calls == 1


def test_download_redirect_is_not_followed(tmp_path):
    target_state = FakeState()
    source_state = FakeState()
    with LoopbackServer(target_state) as target, LoopbackServer(source_state) as source:
        source_state.redirect_target_port = target.port
        source_state.content_redirect = True
        api = make_api(tmp_path, source.port)
        with pytest.raises(d1_host_api._ExportDownloadError) as caught:
            api._download_observation_export("x")
        assert caught.value.code == "EXPORT_LOCAL_API_REDIRECT"
        assert target_state.steal_hits == 0
        assert target_state.content_calls == 0


def test_environment_proxy_is_ignored(tmp_path, monkeypatch):
    proxy_state = FakeState()
    with LoopbackServer(proxy_state) as proxy, LoopbackServer(FakeState()) as target:
        monkeypatch.setenv("HTTP_PROXY", f"http://127.0.0.1:{proxy.port}")
        monkeypatch.setenv("HTTPS_PROXY", f"http://127.0.0.1:{proxy.port}")
        monkeypatch.setenv("ALL_PROXY", f"http://127.0.0.1:{proxy.port}")
        api = make_api(tmp_path, target.port)
        assert api._local_json("GET", "/api/observation-exports/x/attempts/latest")["attempt_id"] == "attempt-1"
        assert proxy_state.proxy_hits == 0
        assert proxy_state.steal_hits == 0


def test_save_observation_export_saved_and_reentry(tmp_path):
    state = FakeState()
    with LoopbackServer(state) as server:
        api = make_api(tmp_path, server.port)
        export_id = "export-" + uuid.uuid4().hex
        result = api.save_observation_export(
            {"export_id": export_id, "filename": "观察记录.docx"}
        )
        assert result["status"] == "saved", result
        target = tmp_path / "verify" / "观察记录.docx"
        assert target.read_bytes() == DOCX_BYTES
        assert state.attempt_calls == 1
        assert state.content_calls == 1
        assert state.result_calls[-1]["status"] == "saved"
        assert state.result_calls[-1]["byte_size"] == len(DOCX_BYTES)
        # Same token + same filename only reads the original result.
        again = api.save_observation_export(
            {"export_id": export_id, "filename": "观察记录.docx"}
        )
        assert again["status"] == "saved"
        assert state.attempt_calls == 1
        assert state.content_calls == 1
        # Different filename is refused without a second dialog.
        conflict = api.save_observation_export(
            {"export_id": export_id, "filename": "另一个.docx"}
        )
        assert conflict["status"] == "failed"
        assert conflict["code"] == "EXPORT_ATTEMPT_CONFLICT"


def test_save_observation_export_canceled_and_query(tmp_path):
    state = FakeState()
    with LoopbackServer(state) as server:
        api = make_api(tmp_path, server.port, verify=False, dialog_result=None)
        api._verify_save_dir = None
        export_id = "export-" + uuid.uuid4().hex
        result = api.save_observation_export(
            {"export_id": export_id, "filename": "观察记录.docx"}
        )
        assert result["status"] == "canceled", result
        assert state.result_calls[-1]["status"] == "cancelled"
        assert api.get_observation_export_result(
            {"export_id": export_id, "filename": "观察记录.docx"}
        )["status"] == "canceled"


def test_download_truncated_bad_hash_oversize_and_timeout(tmp_path, monkeypatch):
    state = FakeState()
    with LoopbackServer(state) as server:
        api = make_api(tmp_path, server.port)
        state.content_mode = "truncated"
        result = api.save_observation_export(
            {"export_id": "e1", "filename": "观察.docx"}
        )
        assert result["status"] == "failed"
        assert result["code"] == "EXPORT_DOWNLOAD_TRUNCATED"
        assert state.result_calls[-1]["status"] == "failed"
        state.content_mode = "bad_hash"
        result = api.save_observation_export(
            {"export_id": "e2", "filename": "观察.docx"}
        )
        assert result["status"] == "failed"
        assert result["code"] == "EXPORT_DOWNLOAD_INVALID"
        state.content_mode = "oversized"
        result = api.save_observation_export(
            {"export_id": "e3", "filename": "观察.docx"}
        )
        assert result["status"] == "failed"
        assert result["code"] == "EXPORT_TOO_LARGE"
        state.content_mode = "ok"
        state.sleep_seconds = 1.0
        monkeypatch.setattr(d1_host_api, "OBSERVATION_EXPORT_TIMEOUT_SECONDS", 0.15)
        result = api.save_observation_export(
            {"export_id": "e4", "filename": "观察.docx"}
        )
        assert result["status"] == "failed"
        assert result["code"] == "EXPORT_DOWNLOAD_TIMEOUT"


def test_latest_attempt_query_maps_pending_and_saved(tmp_path):
    state = FakeState()
    with LoopbackServer(state) as server:
        api = make_api(tmp_path, server.port)
        state.latest_status = "in_progress"
        pending = api.get_observation_export_result({"export_id": "x"})
        assert pending["status"] == "pending"
        state.latest_status = "saved"
        saved = api.get_observation_export_result({"export_id": "x"})
        assert saved["status"] == "saved"


def test_canceled_terminal_report_pending_and_explicit_reconcile(
    tmp_path, monkeypatch
):
    state = FakeState()
    with LoopbackServer(state) as server:
        api = make_api(tmp_path, server.port, verify=False, dialog_result=None)
        api._verify_save_dir = None
        original = api._report_observation_attempt
        monkeypatch.setattr(
            api, "_report_observation_attempt", lambda *args, **kwargs: False
        )
        result = api.save_observation_export(
            {"export_id": "cancel-pending", "filename": "观察.docx"}
        )
        assert result["status"] == "canceled"
        assert result["receipt_pending"] is True
        assert state.result_calls == []
        assert state.attempt_calls == 1
        assert state.content_calls == 1
        # Same-token reentry reads the cached terminal result; no new dialog,
        # download or attempt.
        again = api.save_observation_export(
            {"export_id": "cancel-pending", "filename": "观察.docx"}
        )
        assert again["status"] == "canceled"
        assert again["receipt_pending"] is True
        assert state.attempt_calls == 1
        assert state.content_calls == 1
        monkeypatch.setattr(api, "_report_observation_attempt", original)
        reconciled = api.reconcile_observation_export_result(
            {"export_id": "cancel-pending", "filename": "观察.docx"}
        )
        assert reconciled["status"] == "canceled"
        assert reconciled.get("receipt_pending") is not True
        assert state.result_calls[-1]["status"] == "cancelled"
        assert state.attempt_calls == 1
        assert state.content_calls == 1
        # Read-only query remains read-only after reconciliation.
        before_results = len(state.result_calls)
        queried = api.get_observation_export_result(
            {"export_id": "cancel-pending", "filename": "观察.docx"}
        )
        assert queried["status"] == "canceled"
        assert len(state.result_calls) == before_results
        assert api._save_in_progress() is False


def test_saved_terminal_report_pending_and_reconcile(tmp_path, monkeypatch):
    state = FakeState()
    with LoopbackServer(state) as server:
        api = make_api(tmp_path, server.port)
        original = api._report_observation_attempt
        monkeypatch.setattr(
            api, "_report_observation_attempt", lambda *args, **kwargs: False
        )
        result = api.save_observation_export(
            {"export_id": "saved-pending", "filename": "观察.docx"}
        )
        assert result["status"] == "saved"
        assert result["receipt_pending"] is True
        assert result["result_hash"]
        monkeypatch.setattr(api, "_report_observation_attempt", original)
        reconciled = api.reconcile_observation_export_result(
            {"export_id": "saved-pending", "filename": "观察.docx"}
        )
        assert reconciled["status"] == "saved"
        assert reconciled.get("receipt_pending") is not True
        assert state.result_calls[-1]["status"] == "saved"
        assert state.result_calls[-1]["result_hash"] == result["result_hash"]
        assert api._save_in_progress() is False


def test_failed_and_indeterminate_terminal_report_reconcile(
    tmp_path, monkeypatch
):
    state = FakeState()
    with LoopbackServer(state) as server:
        api = make_api(tmp_path, server.port)
        original = api._report_observation_attempt
        monkeypatch.setattr(
            api, "_report_observation_attempt", lambda *args, **kwargs: False
        )
        state.content_mode = "truncated"
        failed = api.save_observation_export(
            {"export_id": "failed-pending", "filename": "观察.docx"}
        )
        assert failed["status"] == "failed"
        assert failed["receipt_pending"] is True
        monkeypatch.setattr(api, "_report_observation_attempt", original)
        reconciled = api.reconcile_observation_export_result(
            {"export_id": "failed-pending", "filename": "观察.docx"}
        )
        assert reconciled["status"] == "failed"
        assert state.result_calls[-1]["status"] == "failed"

        state.content_mode = "ok"
        monkeypatch.setattr(
            api, "_report_observation_attempt", lambda *args, **kwargs: False
        )
        monkeypatch.setattr(
            d1_host_api,
            "write_stream_atomic",
            lambda *args, **kwargs: {
                "status": "unknown",
                "code": "SAVE_RESULT_UNKNOWN",
                "message": "synthetic unknown",
            },
        )
        unknown = api.save_observation_export(
            {"export_id": "unknown-pending", "filename": "观察.docx"}
        )
        assert unknown["status"] == "unknown"
        assert unknown["receipt_pending"] is True
        monkeypatch.setattr(api, "_report_observation_attempt", original)
        reconciled = api.reconcile_observation_export_result(
            {"export_id": "unknown-pending", "filename": "观察.docx"}
        )
        assert reconciled["status"] == "unknown"
        assert state.result_calls[-1]["status"] == "indeterminate"


def test_reconcile_without_pending_is_read_only(tmp_path):
    state = FakeState()
    with LoopbackServer(state) as server:
        api = make_api(tmp_path, server.port)
        result = api.save_observation_export(
            {"export_id": "already-confirmed", "filename": "观察.docx"}
        )
        assert result["status"] == "saved"
        before = len(state.result_calls)
        queried = api.reconcile_observation_export_result(
            {"export_id": "already-confirmed", "filename": "观察.docx"}
        )
        assert queried["status"] == "saved"
        assert len(state.result_calls) == before


def test_write_stream_atomic_verifies_hash(tmp_path):
    source = tmp_path / "source.docx"
    source.write_bytes(DOCX_BYTES)
    target = tmp_path / "target.docx"
    result = write_stream_atomic(
        str(target),
        str(source),
        expected_hash=hashlib.sha256(DOCX_BYTES).hexdigest(),
        expected_size=len(DOCX_BYTES),
    )
    assert result["status"] == "saved"
    assert target.read_bytes() == DOCX_BYTES
    bad = write_stream_atomic(
        str(target),
        str(source),
        expected_hash="0" * 64,
        expected_size=len(DOCX_BYTES),
    )
    assert bad["status"] == "failed"
    assert target.read_bytes() == DOCX_BYTES


def test_trickle_content_hits_total_deadline_and_cleans_temp(
    tmp_path, monkeypatch
):
    state = FakeState()
    created_paths = []
    original_mkstemp = d1_host_api.tempfile.mkstemp

    def tracking_mkstemp(*args, **kwargs):
        fd, name = original_mkstemp(*args, **kwargs)
        created_paths.append(name)
        return fd, name

    with LoopbackServer(state) as server:
        api = make_api(tmp_path, server.port)
        state.trickle_content = True
        monkeypatch.setattr(
            d1_host_api, "OBSERVATION_EXPORT_TIMEOUT_SECONDS", 0.15
        )
        monkeypatch.setattr(
            d1_host_api.tempfile, "mkstemp", tracking_mkstemp
        )
        started = time.monotonic()
        result = api.save_observation_export(
            {"export_id": "trickle", "filename": "观察.docx"}
        )
        elapsed = time.monotonic() - started
        assert result["status"] == "failed"
        assert result["code"] == "EXPORT_DOWNLOAD_TIMEOUT"
        assert elapsed < 1.0
        assert state.result_calls[-1]["status"] == "failed"
        assert api._save_in_progress() is False
        assert created_paths
        assert not Path(created_paths[-1]).exists()


def test_slow_headers_hit_total_deadline(tmp_path, monkeypatch):
    state = FakeState()
    with LoopbackServer(state) as server:
        api = make_api(tmp_path, server.port)
        state.slow_headers = True
        monkeypatch.setattr(
            d1_host_api, "OBSERVATION_EXPORT_TIMEOUT_SECONDS", 0.15
        )
        result = api.save_observation_export(
            {"export_id": "slow-header", "filename": "观察.docx"}
        )
        assert result["status"] == "failed"
        assert result["code"] == "EXPORT_DOWNLOAD_TIMEOUT"
        assert state.result_calls[-1]["status"] == "failed"


def test_will_close_body_hits_total_deadline_both_channels(tmp_path, monkeypatch):
    state = FakeState()
    created_paths = []
    original_mkstemp = d1_host_api.tempfile.mkstemp

    def tracking_mkstemp(*args, **kwargs):
        fd, name = original_mkstemp(*args, **kwargs)
        created_paths.append(name)
        return fd, name

    with LoopbackServer(state) as server:
        api = make_api(tmp_path, server.port)
        state.will_close_body = True
        monkeypatch.setattr(
            d1_host_api, "OBSERVATION_EXPORT_JSON_DEADLINE_SECONDS", 0.15
        )
        started = time.monotonic()
        with pytest.raises(d1_host_api._LocalApiError) as caught:
            api._local_json(
                "GET", "/api/observation-exports/x/attempts/latest"
            )
        elapsed = time.monotonic() - started
        assert caught.value.code == "EXPORT_LOCAL_API_TIMEOUT"
        assert elapsed < 0.8
        monkeypatch.setattr(
            d1_host_api, "OBSERVATION_EXPORT_TIMEOUT_SECONDS", 0.15
        )
        monkeypatch.setattr(d1_host_api.tempfile, "mkstemp", tracking_mkstemp)
        started = time.monotonic()
        result = api.save_observation_export(
            {"export_id": "will-close", "filename": "观察.docx"}
        )
        elapsed = time.monotonic() - started
        assert result["status"] == "failed"
        assert result["code"] == "EXPORT_DOWNLOAD_TIMEOUT"
        assert elapsed < 1.0
        assert api._save_in_progress() is False
        assert created_paths
        assert not Path(created_paths[-1]).exists()


def test_header_trickle_hits_total_deadline_both_channels(tmp_path, monkeypatch):
    state = FakeState()
    created_paths = []
    original_mkstemp = d1_host_api.tempfile.mkstemp

    def tracking_mkstemp(*args, **kwargs):
        fd, name = original_mkstemp(*args, **kwargs)
        created_paths.append(name)
        return fd, name

    with LoopbackServer(state) as server:
        api = make_api(tmp_path, server.port)
        state.trickle_headers = True
        monkeypatch.setattr(
            d1_host_api, "OBSERVATION_EXPORT_JSON_DEADLINE_SECONDS", 0.15
        )
        started = time.monotonic()
        with pytest.raises(d1_host_api._LocalApiError) as caught:
            api._local_json(
                "GET", "/api/observation-exports/x/attempts/latest"
            )
        elapsed = time.monotonic() - started
        assert caught.value.code == "EXPORT_LOCAL_API_TIMEOUT"
        assert elapsed < 0.8
        monkeypatch.setattr(
            d1_host_api, "OBSERVATION_EXPORT_TIMEOUT_SECONDS", 0.15
        )
        monkeypatch.setattr(d1_host_api.tempfile, "mkstemp", tracking_mkstemp)
        started = time.monotonic()
        result = api.save_observation_export(
            {"export_id": "header-trickle", "filename": "观察.docx"}
        )
        elapsed = time.monotonic() - started
        assert result["status"] == "failed"
        assert result["code"] == "EXPORT_DOWNLOAD_TIMEOUT"
        assert elapsed < 1.0
        assert api._save_in_progress() is False
        assert created_paths
        assert not Path(created_paths[-1]).exists()


def test_json_trickle_and_slow_headers_hit_total_deadline(
    tmp_path, monkeypatch
):
    state = FakeState()
    with LoopbackServer(state) as server:
        api = make_api(tmp_path, server.port)
        monkeypatch.setattr(
            d1_host_api, "OBSERVATION_EXPORT_JSON_DEADLINE_SECONDS", 0.15
        )
        monkeypatch.setattr(
            d1_host_api, "OBSERVATION_EXPORT_JSON_TIMEOUT_SECONDS", 0.15
        )
        state.trickle_json = True
        with pytest.raises(d1_host_api._LocalApiError) as caught:
            api._local_json(
                "GET", "/api/observation-exports/x/attempts/latest"
            )
        assert caught.value.code == "EXPORT_LOCAL_API_TIMEOUT"
        state.trickle_json = False
        state.slow_headers = True
        with pytest.raises(d1_host_api._LocalApiError) as caught:
            api._local_json(
                "GET", "/api/observation-exports/x/attempts/latest"
            )
        assert caught.value.code == "EXPORT_LOCAL_API_TIMEOUT"
