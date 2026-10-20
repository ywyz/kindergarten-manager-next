"""R2/R7: unified DOCX target validation and atomic, failure-safe writes."""

import base64

import pytest
import webview

import d0_host_api
from d0_host_api import validate_docx_target, write_docx_file


class TestSuffixBoundary:
    def test_accepts_docx_case_insensitively(self, tmp_path):
        target = tmp_path / "报告.DOCX"
        result = write_docx_file(str(target), b"PK-data")
        assert result["status"] == "saved"
        assert result["suffix_ok"] is True
        assert target.read_bytes() == b"PK-data"

    def test_rejects_no_suffix_without_creating_file(self, tmp_path):
        target = tmp_path / "报告"
        result = write_docx_file(str(target), b"PK-data")
        assert result["status"] == "failed"
        assert result["suffix_ok"] is False
        assert not target.exists()
        assert list(tmp_path.iterdir()) == []

    def test_rejects_other_suffix_without_creating_file(self, tmp_path):
        target = tmp_path / "报告.txt"
        result = write_docx_file(str(target), b"PK-data")
        assert result["status"] == "failed"
        assert result["suffix_ok"] is False
        assert not target.exists()
        assert list(tmp_path.iterdir()) == []

    def test_validate_empty_target(self):
        ok, reason = validate_docx_target("")
        assert ok is False and reason


class TestAtomicWrite:
    def test_success_leaves_no_temp_file(self, tmp_path):
        target = tmp_path / "ok.docx"
        result = write_docx_file(str(target), b"PK-complete")
        assert result["status"] == "saved"
        assert result["bytes"] == len(b"PK-complete")
        assert [path.name for path in tmp_path.iterdir()] == ["ok.docx"]

    def test_partial_write_preserves_original(self, tmp_path, monkeypatch):
        target = tmp_path / "keep.docx"
        target.write_bytes(b"OLD-ORIGINAL")
        monkeypatch.setattr(
            d0_host_api, "_write_payload", lambda handle, data: handle.write(data[:3])
        )
        result = write_docx_file(str(target), b"PK-NEW-CONTENT")
        assert result["status"] == "failed"
        assert target.read_bytes() == b"OLD-ORIGINAL"
        assert [path.name for path in tmp_path.iterdir()] == ["keep.docx"]

    def test_fsync_failure_preserves_original(self, tmp_path, monkeypatch):
        target = tmp_path / "keep.docx"
        target.write_bytes(b"OLD")

        def boom(fd):
            raise OSError("fsync failed")

        monkeypatch.setattr(d0_host_api.os, "fsync", boom)
        result = write_docx_file(str(target), b"PK-NEW")
        assert result["status"] == "failed"
        assert target.read_bytes() == b"OLD"
        assert [path.name for path in tmp_path.iterdir()] == ["keep.docx"]

    def test_replace_failure_preserves_original(self, tmp_path, monkeypatch):
        target = tmp_path / "keep.docx"
        target.write_bytes(b"OLD")

        def boom(src, dst):
            raise OSError("replace failed")

        monkeypatch.setattr(d0_host_api.os, "replace", boom)
        result = write_docx_file(str(target), b"PK-NEW")
        assert result["status"] == "failed"
        assert target.read_bytes() == b"OLD"
        assert [path.name for path in tmp_path.iterdir()] == ["keep.docx"]

    def test_new_target_failure_leaves_no_half_product(self, tmp_path, monkeypatch):
        target = tmp_path / "new.docx"

        def boom(fd):
            raise OSError("fsync failed")

        monkeypatch.setattr(d0_host_api.os, "fsync", boom)
        result = write_docx_file(str(target), b"PK-NEW")
        assert result["status"] == "failed"
        assert not target.exists()
        assert list(tmp_path.iterdir()) == []


class TestDialogSuffix:
    def test_dialog_non_docx_target_rejected(self, monkeypatch, tmp_path):
        monkeypatch.delenv("KGM_D0_AUTOSAVE_DIR", raising=False)
        api = d0_host_api.D0HostApi("token")
        chosen = tmp_path / "unexpected.txt"

        class FakeWindow:
            def create_file_dialog(self, *args, **kwargs):
                return str(chosen)

        monkeypatch.setattr(webview, "windows", [FakeWindow()])
        payload = {
            "payload_base64": base64.b64encode(b"PK").decode(),
            "filename": "D0验证_日计划.docx",
        }
        result = api.save_docx(payload)
        assert result["status"] == "failed"
        assert result["suffix_ok"] is False
        assert not chosen.exists()

    def test_dialog_docx_target_written(self, monkeypatch, tmp_path):
        monkeypatch.delenv("KGM_D0_AUTOSAVE_DIR", raising=False)
        api = d0_host_api.D0HostApi("token")
        chosen = tmp_path / "含 中文 与空格.docx"

        class FakeWindow:
            def create_file_dialog(self, *args, **kwargs):
                return str(chosen)

        monkeypatch.setattr(webview, "windows", [FakeWindow()])
        payload = {
            "payload_base64": base64.b64encode(b"PK-real").decode(),
            "filename": "D0验证_日计划.docx",
        }
        result = api.save_docx(payload)
        assert result["status"] == "saved"
        assert chosen.read_bytes() == b"PK-real"
