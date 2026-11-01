"""Synthetic G2b weekly host tests: real loopback, real files, tiny DOCX."""

from __future__ import annotations

import hashlib
import http.server
import io
import json
import os
import threading
import time
import urllib.parse
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import d1_host_api
from d1_host_api import D1HostApi

MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    '</Types>'
)
_RELS = (
    '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
    '</Relationships>'
)


def minimal_docx(text: str = "周计划导出验证") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _CONTENT_TYPES)
        archive.writestr("_rels/.rels", _RELS)
        archive.writestr(
            "word/document.xml",
            '<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>",
        )
    return buffer.getvalue()


DOCX = minimal_docx()
class FakeReader:
    def __init__(self, path: Path):
        self.path = path
        self.handle = path.open("rb")
        self.size = path.stat().st_size
    def read(self, size=-1): return self.handle.read(size)
    def seek(self, offset, whence=0): return self.handle.seek(offset, whence)
    def tell(self): return self.handle.tell()
    def fileno(self): return self.handle.fileno()
    def seekable(self): return True
    def readable(self): return True
    @property
    def closed(self): return self.handle.closed
    def close(self): self.handle.close()


class FakeTemp:
    def __init__(self, manager, token, path):
        self.manager = manager
        self.token = token
        self.path = path
        self.handle = path.open("wb")
    def finish(self): return self.manager.finish_owned_temp(self.token)
    def abort(self): self.manager.abort_owned_temp(self.token)


class FakeManager:
    launch_id = "launch-host"
    session_scope = "scope-host"
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._closed = False
        self._active = 0
        self.paused = False
        self.pause_on_finish = False
        self._temps = {}
    @property
    def is_closed(self): return self._closed
    def activity(self, *, kind, launch_id, session_scope):
        manager = self
        class Activity:
            def __enter__(self):
                if manager._closed: raise RuntimeError("closed")
                manager._active += 1
                return 1
            def __exit__(self, *args): manager._active -= 1
        return Activity()
    def publish(self, *, epoch, launch_id, session_scope):
        if self._closed or self.paused: raise RuntimeError("closed")
        return threading.Lock()
    def create_owned_temp(self, *, owner, suffix=".docx"):
        if self._active <= 0 or self._closed: raise RuntimeError("not active")
        token = uuid.uuid4().hex
        path = self.root / f"tmp-{token}{suffix}"
        temp = FakeTemp(self, token, path)
        self._temps[token] = temp
        return temp
    def finish_owned_temp(self, token):
        temp = self._temps.get(token)
        if temp is None: raise RuntimeError("unknown temp")
        temp.handle.flush(); temp.handle.close()
        if self.pause_on_finish:
            self.paused = True
        return FakeReader(temp.path)
    def abort_owned_temp(self, token):
        temp = self._temps.pop(token, None)
        if temp is not None:
            if not temp.handle.closed: temp.handle.close()
            try: temp.path.unlink()
            except OSError: pass
    def close(self): self._closed = True
class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.should_prompt = True
        self.initial_status = "in_progress"
        self.content_mode = "ok"
        self.latest_status = "in_progress"
        self.fail_result = False
        self.attempt_fail = False
        self.paused = False
        self.attempt_calls = 0
        self.content_calls = 0
        self.latest_calls = 0
        self.result_calls = []
        self.expiry = (datetime.now(timezone.utc) + timedelta(seconds=600)).strftime("%Y-%m-%dT%H:%M:%SZ")
class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.should_prompt = True
        self.initial_status = "in_progress"
        self.content_mode = "ok"
        self.latest_status = "in_progress"
        self.fail_result = False
        self.attempt_fail = False
        self.paused = False
        self.attempt_calls = 0
        self.content_calls = 0
        self.latest_calls = 0
        self.result_calls = []
        self.expiry = (datetime.now(timezone.utc) + timedelta(seconds=600)).strftime("%Y-%m-%dT%H:%M:%SZ")

def make_handler(state):
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def _json(self, status, body):
            raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            if self.path.endswith("/attempts"):
                with state.lock: state.attempt_calls += 1
                if state.attempt_fail:
                    self._json(503, {"error": {"code": "ATTEMPT_UNAVAILABLE", "message": "failed"}})
                    return
                status = state.initial_status if not state.should_prompt else "in_progress"
                self._json(200, {"attempt_id": "attempt-1", "status": status,
                                 "filename": body.get("filename"),
                                 "should_prompt": state.should_prompt,
                                 "byte_size": 0, "result_hash": None,
                                 "started_at": "2026-11-01T00:00:00+00:00",
                                 "ended_at": None})
                return
            if self.path.endswith("/attempts/result"):
                with state.lock:
                    state.result_calls.append(body)
                    fail = state.fail_result
                if fail:
                    self._json(503, {"error": {"code": "STORE_FAILED", "message": "failed"}})
                    return
                self._json(200, {"attempt_id": body.get("attempt_id"),
                                 "status": body.get("status"), "filename": body.get("filename"),
                                 "should_prompt": False, "byte_size": body.get("byte_size"),
                                 "result_hash": body.get("result_hash"),
                                 "started_at": "2026-11-01T00:00:00+00:00",
                                 "ended_at": "2026-11-01T00:01:00+00:00"})
                return
            self._json(404, {"error": {"code": "NOT_FOUND", "message": "not found"}})
        def do_GET(self):
            if self.path.endswith("/content"):
                with state.lock: state.content_calls += 1
                mode = state.content_mode
                if mode == "redirect":
                    self.send_response(302); self.send_header("Location", "http://127.0.0.1:1/steal"); self.end_headers(); return
                data = b"not-a-zip" if mode == "bad_zip" else DOCX
                digest = hashlib.sha256(data).hexdigest()
                self.send_response(200)
                self.send_header("Content-Type", "text/plain" if mode == "bad_mime" else MIME)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Disposition", "attachment")
                self.send_header("Content-Length", str(len(data) + (1 if mode == "bad_length" else 0)))
                self.send_header("X-Content-SHA256", "0" * 64 if mode == "bad_hash" else digest)
                self.send_header("X-Export-Expires-At", "not-a-z" if mode == "bad_expiry" else state.expiry)
                self.end_headers()
                if mode != "bad_length": self.wfile.write(data)
                return
            if "/attempts/latest" in self.path:
                with state.lock: state.latest_calls += 1
                self._json(200, {"attempt_id": "attempt-latest", "status": state.latest_status,
                                 "filename": urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("filename", [""])[0],
                                 "should_prompt": False, "byte_size": 12 if state.latest_status == "saved" else 0,
                                 "result_hash": "b" * 64 if state.latest_status == "saved" else None,
                                 "started_at": "2026-11-01T00:00:00+00:00", "ended_at": None})
                return
            self._json(404, {"error": {"code": "NOT_FOUND", "message": "not found"}})
    return Handler

@pytest.fixture
def weekly(tmp_path):
    state = State()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), make_handler(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    manager = FakeManager(tmp_path / "work")
    host = D1HostApi(
        launch_token="session-host",
        verify_save_dir=tmp_path / "out",
        service_port=server.server_port,
        weekly_export_manager=manager,
    )
    host._page_ready = True
    try:
        yield state, host, manager, tmp_path
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


def test_save_valid_download_and_original_protocol_name(weekly):
    state, host, manager, tmp_path = weekly
    export_id = "export-valid"
    result = host.save_weekly_export(
        {"export_id": export_id, "filename": "周工作表.docx"}
    )
    assert result["status"] == "saved"
    assert result["filename"] == "周工作表.docx"
    assert (tmp_path / "out" / "周工作表.docx").read_bytes() == DOCX
    assert state.result_calls[-1] == {
        "attempt_id": "attempt-1",
        "filename": "周工作表.docx",
        "status": "saved",
        "byte_size": len(DOCX),
        "result_hash": hashlib.sha256(DOCX).hexdigest(),
    }
    assert manager._active == 0
    assert list((tmp_path / "work").iterdir()) == []
def test_should_prompt_false_never_downloads_or_writes(weekly):
    state, host, manager, tmp_path = weekly
    state.should_prompt = False
    state.initial_status = "cancelled"
    result = host.save_weekly_export({"export_id": "export-terminal", "filename": "已登记.docx"})
    assert result["status"] == "canceled"
    assert state.content_calls == 0
    assert not (tmp_path / "out" / "已登记.docx").exists()
    assert manager._active == 0


@pytest.mark.parametrize("mode", ["bad_mime", "bad_length", "bad_hash", "bad_expiry", "bad_zip", "redirect"])
def test_bad_content_never_opens_dialog_or_writes(weekly, mode):
    state, host, manager, tmp_path = weekly
    state.content_mode = mode
    opened = {"value": False}
    original = host._choose_target
    def choose(name):
        opened["value"] = True
        return original(name)
    host._choose_target = choose
    result = host.save_weekly_export({"export_id": "export-" + mode, "filename": "坏响应.docx"})
    assert result["status"] in ("failed", "unknown")
    assert opened["value"] is False
    assert not (tmp_path / "out" / "坏响应.docx").exists()
    assert manager._active == 0


def test_expired_download_rejected_before_dialog(weekly):
    state, host, manager, tmp_path = weekly
    state.expiry = (datetime.now(timezone.utc) - timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    result = host.save_weekly_export({"export_id": "export-expired", "filename": "过期.docx"})
    assert result["code"] == "WEEKLY_EXPORT_EXPIRED"
    assert not (tmp_path / "out" / "过期.docx").exists()
from unittest import mock

def test_lost_saved_receipt_is_reconciled_without_download(weekly):
    state, host, manager, tmp_path = weekly
    state.fail_result = True
    result = host.save_weekly_export({"export_id": "export-receipt", "filename": "回执.docx"})
    assert result["status"] == "saved"
    assert result.get("receipt_pending") is True
    state.fail_result = False
    queried = host.get_weekly_export_result({"export_id": "export-receipt", "filename": "回执.docx"})
    assert queried["status"] == "saved"
    assert "receipt_pending" not in queried
    assert len(state.result_calls) == 2
    assert state.content_calls == 1


def test_unknown_query_uses_latest_only(weekly):
    state, host, manager, tmp_path = weekly
    state.latest_status = "saved"
    result = host.get_weekly_export_result({"export_id": "export-query", "filename": "查询.docx"})
    assert result["status"] == "saved"
    assert state.attempt_calls == 0
    assert state.content_calls == 0
    assert state.latest_calls == 1


def test_actual_target_rename_keeps_protocol_name(weekly, tmp_path):
    state, host, manager, _ = weekly
    actual = tmp_path / "out" / "教师选择的名称.docx"
    actual.parent.mkdir(parents=True, exist_ok=True)
    host._choose_target = lambda name: str(actual)
    result = host.save_weekly_export({"export_id": "export-rename", "filename": "协议名.docx"})
    assert result["status"] == "saved"
    assert result["filename"] == "协议名.docx"
    assert actual.is_file()
    assert state.result_calls[-1]["filename"] == "协议名.docx"
def test_write_failure_preserves_existing_target(weekly, tmp_path):
    state, host, manager, _ = weekly
    target = tmp_path / "out" / "保留.docx"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"original-target")
    host._choose_target = lambda name: str(target)
    with mock.patch.object(d1_host_api.os, "replace", side_effect=OSError("forced-replace")):
        result = host.save_weekly_export({"export_id": "export-fail", "filename": "保留.docx"})
    assert result["status"] == "failed"
    assert target.read_bytes() == b"original-target"
    assert manager._active == 0


def test_missing_manager_rejects_new_work(weekly):
    state, host, manager, tmp_path = weekly
    host._weekly_export_manager = None
    result = host.save_weekly_export({"export_id": "export-no-manager", "filename": "不可用.docx"})
    assert result["status"] == "failed"
    assert result["code"] == "WEEKLY_EXPORT_UNAVAILABLE"
    assert state.attempt_calls == 0
    assert state.content_calls == 0
def test_same_export_concurrent_and_conflicting_name(weekly):
    state, host, manager, tmp_path = weekly
    barrier = threading.Barrier(2)
    results = []
    def run():
        barrier.wait(5)
        results.append(host.save_weekly_export({"export_id": "export-concurrent", "filename": "并发.docx"}))
    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads: thread.start()
    for thread in threads: thread.join(10)
    assert state.attempt_calls == 1
    assert all(result["status"] in ("saved", "pending") for result in results)
    conflict = host.save_weekly_export({"export_id": "export-concurrent", "filename": "异名.docx"})
    assert conflict["code"] == "WEEKLY_EXPORT_ATTEMPT_CONFLICT"
    assert not (tmp_path / "out" / "异名.docx").exists()


def test_retired_host_rejects_without_attempt(weekly):
    state, host, manager, tmp_path = weekly
    host._retired = True
    result = host.save_weekly_export({"export_id": "export-retired", "filename": "退休.docx"})
    assert result["status"] == "failed"
    assert result["code"] == "HOST_SWITCHING"
    assert state.attempt_calls == 0
    assert not (tmp_path / "out" / "退休.docx").exists()
@pytest.mark.parametrize("name", ["CON.docx", "con.docx", "CON.note.docx", "aux.docx", "a:b.docx", "A<.docx", "A|.docx", "A?.docx", "bad.docx ", "bad.docx.", "bad\x00.docx"])
def test_invalid_windows_basename_rejected_without_attempt(weekly, name):
    state, host, manager, tmp_path = weekly
    result = host.save_weekly_export({"export_id": "export-invalid-name", "filename": name})
    assert result["status"] == "failed"
    assert result["code"] == "INVALID_PAYLOAD"
    assert state.attempt_calls == 0
    assert not (tmp_path / "out" / name).exists()


@pytest.mark.parametrize("value", [
    "2026-11-01T12:00:00Z",
    "2026-11-01T12:00:00.123456Z",
])
def test_expiry_accepts_only_service_iso(value):
    parsed = d1_host_api._weekly_expiry(value)
    assert parsed.tzinfo is not None


@pytest.mark.parametrize("value", [
    "2026-11-01X12:00:00Z",
    "2026-11-01T12:00:00+00:00",
    "2026-11-01T12:00:00",
    "20261101T120000Z",
    "2026-11-01T12:00:00.123Z",
    "2026-11-01T12:00:00.1234567Z",
    "2026-11-01T12:00:00.000000Z",
])
def test_expiry_rejects_noncanonical(value):
    with pytest.raises(ValueError):
        d1_host_api._weekly_expiry(value)
def test_cleanup_fault_does_not_downgrade_saved(weekly):
    state, host, manager, tmp_path = weekly
    real_close = FakeReader.close
    real_abort = FakeManager.abort_owned_temp
    close_calls = {"n": 0}
    abort_calls = {"n": 0}
    def flaky_close(reader):
        close_calls["n"] += 1
        if close_calls["n"] == 1:
            raise OSError("cleanup-close")
        return real_close(reader)
    def flaky_abort(manager_self, token):
        abort_calls["n"] += 1
        if abort_calls["n"] == 1:
            raise OSError("cleanup-abort")
        return real_abort(manager_self, token)
    with mock.patch.object(FakeReader, "close", flaky_close), mock.patch.object(FakeManager, "abort_owned_temp", flaky_abort):
        result = host.save_weekly_export({"export_id": "export-cleanup", "filename": "清理故障.docx"})
    assert result["status"] == "saved"
    assert (tmp_path / "out" / "清理故障.docx").read_bytes() == DOCX
    assert close_calls["n"] >= 2 and abort_calls["n"] >= 2
    assert manager._active == 0


def test_pause_after_download_prevents_dialog(weekly):
    state, host, manager, tmp_path = weekly
    manager.pause_on_finish = True
    visited = {"value": False}
    original = host._choose_target
    def choose(name):
        visited["value"] = True
        return original(name)
    host._choose_target = choose
    result = host.save_weekly_export({"export_id": "export-pause", "filename": "暂停.docx"})
    assert result["status"] == "failed"
    assert visited["value"] is False
    assert not (tmp_path / "out" / "暂停.docx").exists()
    assert manager._active == 0
def test_closed_cache_replay_keeps_saved_without_io(weekly):
    state, host, manager, tmp_path = weekly
    first = host.save_weekly_export({"export_id": "export-cache", "filename": "缓存.docx"})
    assert first["status"] == "saved"
    attempt_calls = state.attempt_calls
    content_calls = state.content_calls
    host._retire()
    replay = host.save_weekly_export({"export_id": "export-cache", "filename": "缓存.docx"})
    assert replay["status"] == "saved"
    assert state.attempt_calls == attempt_calls
    assert state.content_calls == content_calls
    queried = host.get_weekly_export_result({"export_id": "export-cache", "filename": "缓存.docx"})
    assert queried["status"] == "saved"
    conflict = host.save_weekly_export({"export_id": "export-cache", "filename": "异名.docx"})
    assert conflict["code"] == "WEEKLY_EXPORT_ATTEMPT_CONFLICT"


def test_manager_create_failure_after_attempt_is_failed_terminal(weekly):
    state, host, manager, tmp_path = weekly
    with mock.patch.object(manager, "create_owned_temp", side_effect=RuntimeError("manager-denied")):
        result = host.save_weekly_export({"export_id": "export-manager", "filename": "管理器.docx"})
    assert result["status"] == "failed"
    assert result["attempt_id"] == "attempt-1"
    assert state.result_calls[-1]["status"] == "failed"
    assert not (tmp_path / "out" / "管理器.docx").exists()
def test_start_unknown_queries_latest_without_fake_result(weekly):
    state, host, manager, tmp_path = weekly
    state.attempt_fail = True
    result = host.save_weekly_export({"export_id": "export-start-unknown", "filename": "未知.docx"})
    assert result["status"] == "unknown"
    assert state.result_calls == []
    state.latest_status = "in_progress"
    queried = host.get_weekly_export_result({"export_id": "export-start-unknown", "filename": "未知.docx"})
    assert queried["status"] == "pending"
    assert state.result_calls == []
    assert state.latest_calls == 1


def test_indeterminate_query_reconciles_same_attempt_once(weekly, tmp_path):
    state, host, manager, _ = weekly
    target = tmp_path / "out" / "未知写入.docx"
    target.parent.mkdir(parents=True, exist_ok=True)
    state.fail_result = True
    real_replace = d1_host_api.os.replace
    def replace_and_corrupt(source, destination):
        real_replace(source, destination)
        Path(destination).write_bytes(b"corrupt-after-replace")
    with mock.patch.object(d1_host_api.os, "replace", replace_and_corrupt):
        result = host.save_weekly_export({"export_id": "export-indeterminate", "filename": "未知写入.docx"})
    assert result["status"] == "unknown"
    assert result.get("receipt_pending") is True
    state.fail_result = False
    content_calls = state.content_calls
    queried = host.get_weekly_export_result({"export_id": "export-indeterminate", "filename": "未知写入.docx"})
    assert queried["status"] == "unknown"
    assert state.result_calls[-1]["status"] == "indeterminate"
    assert state.result_calls[-1]["byte_size"] == 0
    assert state.content_calls == content_calls
def test_retired_unknown_cache_replays_without_http(weekly):
    state, host, manager, tmp_path = weekly
    state.attempt_fail = True
    result = host.save_weekly_export({"export_id": "export-unknown-cache", "filename": "未知缓存.docx"})
    assert result["status"] == "unknown"
    attempts = state.attempt_calls
    host._retire()
    replay = host.save_weekly_export({"export_id": "export-unknown-cache", "filename": "未知缓存.docx"})
    assert replay["status"] == "unknown"
    queried = host.get_weekly_export_result({"export_id": "export-unknown-cache", "filename": "未知缓存.docx"})
    assert queried["status"] == "unknown"
    assert state.attempt_calls == attempts
    assert state.latest_calls == 0


def test_retired_receipt_pending_does_not_write(weekly):
    state, host, manager, tmp_path = weekly
    state.fail_result = True
    result = host.save_weekly_export({"export_id": "export-retired-receipt", "filename": "退休回执.docx"})
    assert result["status"] == "saved" and result.get("receipt_pending") is True
    calls = len(state.result_calls)
    host._retire()
    queried = host.get_weekly_export_result({"export_id": "export-retired-receipt", "filename": "退休回执.docx"})
    assert queried["status"] == "saved"
    assert queried.get("receipt_pending") is True
    assert len(state.result_calls) == calls
def test_real_retire_keeps_same_pending_attempt_and_filename(weekly):
    state, host, manager, tmp_path = weekly
    state.should_prompt = False
    state.initial_status = "in_progress"
    pending = host.save_weekly_export({"export_id": "export-pending", "filename": "进行中.docx"})
    assert pending["status"] == "pending"
    assert pending["filename"] == "进行中.docx"
    assert pending["attempt_id"] == "attempt-1"
    attempt_calls = state.attempt_calls
    content_calls = state.content_calls
    host._retire()
    replayed = host.save_weekly_export({"export_id": "export-pending", "filename": "进行中.docx"})
    assert replayed["status"] == "pending"
    queried = host.get_weekly_export_result({"export_id": "export-pending", "filename": "进行中.docx"})
    assert queried["status"] == "pending"
    assert queried["attempt_id"] == "attempt-1"
    assert queried["filename"] == "进行中.docx"
    assert state.attempt_calls == attempt_calls
    assert state.content_calls == content_calls
    assert state.latest_calls == 0