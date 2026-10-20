"""D0-3/D0-5/D0-6 basis: host save semantics (real file writes, no dialog)."""

import base64
from pathlib import Path

import pytest
import webview

import d0_host_api
from d0_host_api import write_docx_file


@pytest.fixture()
def autosave_env(tmp_path, monkeypatch):
    monkeypatch.setenv("KGM_D0_AUTOSAVE_DIR", str(tmp_path / "autosave"))
    Path(tmp_path / "autosave").mkdir()
    return tmp_path


def _busy_handle(path: Path):
    """Hold an exclusive kernel handle on the file (simulates a busy target).

    Python's open() shares write access by default, which would let both
    handles write; a zero-share CreateFileW makes any other open fail with
    an OSError, matching a file locked by Word/another process."""
    import ctypes

    kernel32 = ctypes.windll.kernel32
    GENERIC_WRITE = 0x40000000
    OPEN_EXISTING = 3
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
    handle = kernel32.CreateFileW(
        str(path), GENERIC_WRITE, 0, None, OPEN_EXISTING, 0, None
    )
    if handle in (0, INVALID_HANDLE_VALUE):
        raise OSError("CreateFileW failed in test setup")
    return handle


def _close_busy_handle(handle: int) -> None:
    import ctypes

    ctypes.windll.kernel32.CloseHandle(handle)


class TestWriteDocxFile:
    def test_saves_bytes_and_verifies(self, tmp_path):
        target = tmp_path / "含 中文 与空格.docx"
        data = b"PK\x03\x04-fake docx bytes-\xe4\xb8\xad\xe6\x96\x87"
        result = write_docx_file(str(target), data)
        assert result["status"] == "saved"
        assert result["bytes"] == len(data)
        assert target.read_bytes() == data

    def test_occupied_target_reports_failed_without_touching_content(self, tmp_path):
        target = tmp_path / "D0验证_日计划.docx"
        target.write_bytes(b"old")
        handle = _busy_handle(target)
        try:
            result = write_docx_file(str(target), b"PK-new-bytes")
            assert result["status"] == "failed"
            assert "保存失败" in result["message"]
        finally:
            _close_busy_handle(handle)
        # The previous content was never overwritten by the failed attempt.
        assert target.read_bytes() == b"old"

class TestHostApiSave:
    def test_empty_payload_reports_failed_not_saved(self, autosave_env):
        api = d0_host_api.D0HostApi("token")
        result = api.save_docx(
            {"payload_base64": "", "filename": "D0验证_日计划.docx"}
        )
        assert result["status"] == "failed"
        assert result["message"] == "DOCX 数据为空"

    def test_dialog_cancel_returns_canceled(self, monkeypatch, autosave_env):
        api = d0_host_api.D0HostApi("token")

        class FakeWindow:
            def create_file_dialog(self, *args, **kwargs):
                return None

        monkeypatch.setattr(webview, "windows", [FakeWindow()])
        payload = {
            "payload_base64": base64.b64encode(b"PK-docx").decode(),
            "filename": "D0验证_日计划.docx",
        }
        result = api.save_docx(payload)
        assert result == {"status": "canceled"}

    def test_occupied_autosave_target_failed_and_no_partial_file(self, autosave_env):
        api = d0_host_api.D0HostApi("token")
        autosave = Path(autosave_env) / "autosave"
        target = autosave / "D0自动保存_日计划.docx"
        target.write_bytes(b"existing docx")
        handle = _busy_handle(target)
        try:
            payload = {
                "payload_base64": base64.b64encode(b"PK-new-bytes").decode(),
                "filename": "D0自动保存_日计划.docx",
                "autosave_target": "D0自动保存_日计划.docx",
            }
            result = api.save_docx(payload)  # autosave dir -> no dialog
            assert result["status"] == "failed"
        finally:
            _close_busy_handle(handle)
        assert target.read_bytes() == b"existing docx"
        assert [path.name for path in autosave.iterdir()] == [
            "D0自动保存_日计划.docx"
        ]

    def test_autosave_outside_authorized_dir_rejected(self, autosave_env):
        api = d0_host_api.D0HostApi("token")
        payload = {
            "payload_base64": base64.b64encode(b"PK").decode(),
            "filename": "n.docx",
            "autosave_target": "../outside.docx",
        }
        result = api.save_docx(payload)
        assert result["status"] == "failed"
        assert "预授权目录" in result["message"]
        assert not list((Path(autosave_env) / "autosave").iterdir())

    def test_retry_after_failure_succeeds(self, tmp_path):
        target = tmp_path / "retry.docx"
        target.write_bytes(b"old")
        handle = _busy_handle(target)
        try:
            assert write_docx_file(str(target), b"PK-new")["status"] == "failed"
        finally:
            _close_busy_handle(handle)
        data = b"PK-real-content"
        result = write_docx_file(str(target), data)
        assert result["status"] == "saved"
        assert target.read_bytes() == data
