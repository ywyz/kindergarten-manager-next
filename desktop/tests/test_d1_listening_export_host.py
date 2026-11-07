"""Listening export host channel: pin/download/Save As/result without paths."""

from __future__ import annotations

import hashlib
import http.server
import io
import json
import threading
import urllib.parse
import zipfile

import pytest

import d1_host_api
from d1_host_api import D1HostApi

_DOCUMENT = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    "<w:body><w:p><w:r><w:t>倾听记录</w:t></w:r></w:p></w:body></w:document>"
)
_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    "</Types>"
)


def _docx(payload: bytes = b"listening") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", _CONTENT_TYPES)
        archive.writestr("word/document.xml", _DOCUMENT)
        archive.writestr("word/media/note.bin", payload)
    return buffer.getvalue()


class State:
    def __init__(self) -> None:
        self.content = _docx()
        self.digest = hashlib.sha256(self.content).hexdigest()
        self.pin_calls: list[dict] = []
        self.unpin_calls: list[dict] = []
        self.content_calls = 0
        self.content_mode = "ok"
        self.pin_failure = None


class Server:
    def __init__(self, state: State) -> None:
        self.state = state
        handler = self._handler()
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def _handler(self):
        state = self.state

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):  # noqa: ANN002
                return

            def _json(self, status: int, payload: dict) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length") or "0")
                raw = self.rfile.read(length) if length else b"{}"
                payload = json.loads(raw.decode("utf-8") or "{}")
                path = urllib.parse.urlparse(self.path).path
                if path.endswith("/pin"):
                    state.pin_calls.append(payload)
                    if state.pin_failure is not None:
                        self._json(*state.pin_failure)
                        return
                    self._json(
                        200,
                        {
                            "status": "ready",
                            "export_id": path.split("/")[-2],
                            "filename": "倾听记录.docx",
                            "bytes": len(state.content),
                            "sha256": state.digest,
                        },
                    )
                    return
                if path.endswith("/unpin"):
                    state.unpin_calls.append(payload)
                    self._json(200, {"status": "ok"})
                    return
                self._json(404, {"error": {"code": "NOT_FOUND"}})

            def do_GET(self):  # noqa: N802
                path = urllib.parse.urlparse(self.path).path
                if path.endswith("/content"):
                    state.content_calls += 1
                    if state.content_mode == "bad_hash":
                        digest = "0" * 64
                    elif state.content_mode == "bad_mime":
                        digest = state.digest
                    else:
                        digest = state.digest
                    body = state.content
                    if state.content_mode == "truncated":
                        self.send_response(200)
                        self.send_header(
                            "Content-Type",
                            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        )
                        self.send_header("Content-Length", str(len(body) + 10))
                        self.send_header("X-Content-SHA256", state.digest)
                        self.end_headers()
                        self.wfile.write(body)
                        return
                    self.send_response(200)
                    self.send_header(
                        "Content-Type",
                        (
                            "text/plain"
                            if state.content_mode == "bad_mime"
                            else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                        ),
                    )
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("X-Content-SHA256", digest)
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self._json(404, {"error": {"code": "NOT_FOUND"}})

        return Handler

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):  # noqa: ANN002
        self.httpd.shutdown()
        self.httpd.server_close()


def _api(
    tmp_path,
    port: int,
    *,
    verify=True,
    dialog_result=None,
    listening_export_manager=None,
):
    class Window:
        def create_file_dialog(self, *args, **kwargs):  # noqa: ANN002
            return dialog_result

    api = D1HostApi(
        launch_token="SYNTHETIC-NOT-A-CREDENTIAL",
        window_getter=lambda: Window(),
        verify_save_dir=(tmp_path / "verify" if verify else None),
        service_port=port,
        listening_export_manager=listening_export_manager,
    )
    api.page_ready({"bridge_protocol": 1})
    return api


def test_saved_and_cached_reentry(tmp_path) -> None:
    state = State()
    with Server(state) as server:
        api = _api(tmp_path, server.port)
        result = api.save_listening_export(
            {"export_id": "A" * 32, "filename": "倾听记录.docx"}
        )
        assert result["status"] == "saved", result
        assert result["bytes"] == len(state.content)
        target = tmp_path / "verify" / "倾听记录.docx"
        assert target.read_bytes() == state.content
        assert len(state.pin_calls) == 1
        assert state.unpin_calls and state.unpin_calls[-1]["owner"]
        again = api.save_listening_export(
            {"export_id": "A" * 32, "filename": "倾听记录.docx"}
        )
        assert again["status"] == "saved"
        assert state.content_calls == 1
        conflict = api.save_listening_export(
            {"export_id": "A" * 32, "filename": "另一个.docx"}
        )
        assert conflict["status"] == "failed"
        assert conflict["code"] == "LISTENING_EXPORT_ATTEMPT_CONFLICT"
        queried = api.get_listening_export_result(
            {"export_id": "A" * 32, "filename": "倾听记录.docx"}
        )
        assert queried["status"] == "saved"
        assert state.content_calls == 1


def test_canceled_failed_unknown_and_query(tmp_path, monkeypatch) -> None:
    state = State()
    with Server(state) as server:
        api = _api(tmp_path, server.port, verify=False, dialog_result=None)
        result = api.save_listening_export(
            {"export_id": "B" * 32, "filename": "取消.docx"}
        )
        assert result["status"] == "canceled", result
        assert state.unpin_calls
        assert api.get_listening_export_result(
            {"export_id": "B" * 32}
        )["status"] == "canceled"

        api2 = _api(tmp_path, server.port)
        monkeypatch.setattr(
            d1_host_api,
            "write_stream_atomic",
            lambda *args, **kwargs: {"status": "failed", "code": "WRITE_FAILED"},
        )
        failed = api2.save_listening_export(
            {"export_id": "C" * 32, "filename": "失败.docx"}
        )
        assert failed["status"] == "failed"
        assert failed["code"] == "WRITE_FAILED"
        assert len(state.unpin_calls) >= 2

        api3 = _api(tmp_path, server.port)
        monkeypatch.setattr(
            d1_host_api,
            "write_stream_atomic",
            lambda *args, **kwargs: {"status": "unknown", "code": "UNKNOWN_WRITE"},
        )
        pins_before = len(state.pin_calls)
        unknown = api3.save_listening_export(
            {"export_id": "D" * 32, "filename": "未知.docx"}
        )
        assert unknown["status"] == "unknown"
        assert unknown["code"] == "UNKNOWN_WRITE"
        assert len(state.pin_calls) == pins_before + 1
        # Unknown stays pinned and is only queried; the save is never retried.
        queried = api3.get_listening_export_result(
            {"export_id": "D" * 32, "filename": "未知.docx"}
        )
        assert queried["status"] == "unknown"
        assert len(state.pin_calls) == pins_before + 1
        assert state.content_calls >= 1


def test_payload_validation_and_no_arbitrary_paths(tmp_path) -> None:
    state = State()
    with Server(state) as server:
        api = _api(tmp_path, server.port)
        for payload in (
            {},
            {"export_id": "A" * 32, "filename": "a.docx", "path": "C:/x"},
            {"export_id": "a/b", "filename": "a.docx"},
            {"export_id": "A" * 32, "filename": "C:/x.docx"},
            {"export_id": "A" * 32, "filename": "CON.docx"},
            {"export_id": "A" * 32, "filename": "a" * 156 + ".docx"},
        ):
            result = api.save_listening_export(payload)
            assert result["status"] == "failed", (payload, result)
            assert result["code"] == "INVALID_PAYLOAD"
        assert state.pin_calls == []
        assert api.get_listening_export_result({"export_id": "missing"})[
            "status"
        ] == "unknown"


def test_bad_hash_mime_truncated_and_pin_failure(tmp_path) -> None:
    state = State()
    with Server(state) as server:
        api = _api(tmp_path, server.port)
        for index, (mode, code) in enumerate(
            (
                ("bad_hash", "EXPORT_DOWNLOAD_INVALID"),
                ("bad_mime", "EXPORT_DOWNLOAD_INVALID"),
                ("truncated", "EXPORT_DOWNLOAD_TRUNCATED"),
            )
        ):
            state.content_mode = mode
            result = api.save_listening_export(
                {
                    "export_id": (chr(ord("H") + index) * 32),
                    "filename": f"{mode}.docx",
                }
            )
            assert result["status"] == "failed", result
            assert result["code"] == code, result

        state.content_mode = "ok"
        state.pin_failure = (404, {"error": {"code": "LISTENING_EXPORT_NOT_FOUND"}})
        result = api.save_listening_export(
            {"export_id": "Z" * 32, "filename": "pin.docx"}
        )
        assert result["status"] == "failed"
        assert result["code"] == "EXPORT_NOT_FOUND"


def test_captured_listening_activity_feeds_close_busy_probe(tmp_path) -> None:
    class Manager:
        def __init__(self, active: bool):
            self.has_active_work = active

    api = _api(tmp_path, 1, listening_export_manager=Manager(True))
    assert api._listening_busy_probe() is True
    # The coordinator is built by d1_main with this captured probe; the host
    # probe itself must never consult runtime.listening_export_manager late.
    api._listening_export_manager = Manager(False)
    assert api._listening_busy_probe() is False


def test_maintenance_busy_reads_captured_app_generation_manager(tmp_path) -> None:
    from types import SimpleNamespace

    import d1_main

    class Manager:
        has_active_work = True

    service = SimpleNamespace(
        weekly_export_manager=None,
        listening_export_manager=Manager(),
    )
    host = SimpleNamespace(
        _save_in_progress=lambda: False,
        _page_busy_probe=lambda: False,
        _update_busy_probe=lambda: False,
    )
    bundle = SimpleNamespace(host_api=host, service=service)
    assert d1_main._maintenance_busy(bundle) is True
    service.listening_export_manager = SimpleNamespace(has_active_work=False)
    assert d1_main._maintenance_busy(bundle) is False


def test_close_coordinator_uses_captured_listening_activity(tmp_path) -> None:
    from types import SimpleNamespace

    import d1_main

    class Manager:
        def __init__(self, active: bool):
            self.has_active_work = active

    class Closing:
        def __iadd__(self, _callback):
            return self

    api = _api(tmp_path, 1)
    window = SimpleNamespace(
        destroy=lambda: None,
        events=SimpleNamespace(closing=Closing()),
    )
    manager = Manager(True)
    d1_main._install_close_handlers(
        window,
        api,
        None,
        listening_export_manager=manager,
    )
    assert api._close_coordinator._save_busy() is True
    manager.has_active_work = False
    assert api._close_coordinator._save_busy() is False
