"""Diagnostics event recording at the desktop host boundary (2026-11-24).

The host save channels, the update state machine and the maintenance backup
workers record their already-fixed, desensitized outcomes into the bounded
local diagnostics ring at the time the original operation happens.  These
tests bind the module store to a synthetic temporary directory and pin:

- one ``export_word`` event per terminal Word-save outcome (saved / canceled /
  failed with the existing fixed code), and none for payload-validation
  refusals (no host operation happened);
- the fixed update event mapping for terminal discovery/download outcomes;
- one ``local_backup`` / ``webdav_backup`` event per terminal backup outcome.

No real database, WebView2 window or network is involved; the backup engines
are explicit fakes.
"""

from __future__ import annotations

import base64
import dataclasses
import io
import threading
import time
import uuid
import zipfile
from pathlib import Path

import pytest

import d1_host_api
import maintenance_host as mh
import update_service
from d1_host_api import D1HostApi
from app.local import diagnostics as diagnostics_module


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


def minimal_docx() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _CONTENT_TYPES)
        archive.writestr("_rels/.rels", _RELS)
        archive.writestr(
            "word/document.xml",
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body><w:p><w:r><w:t>诊断验证</w:t></w:r></w:p></w:body></w:document>",
        )
    return buffer.getvalue()


DOCX_BYTES = minimal_docx()


@pytest.fixture()
def bound_diagnostics(tmp_path: Path):
    """Bind the module store to a synthetic root; unbind after the test."""
    original_dir = diagnostics_module._store._data_dir  # noqa: SLF001
    original_events = list(diagnostics_module._store._events)  # noqa: SLF001
    data_dir = tmp_path / "diag-data"
    diagnostics_module.configure(data_dir)
    diagnostics_module._store._events = []  # noqa: SLF001
    yield diagnostics_module
    diagnostics_module._store._data_dir = original_dir  # noqa: SLF001
    diagnostics_module._store._events = original_events  # noqa: SLF001


def _only_events(module=diagnostics_module) -> list[dict]:
    return module.recent_events()


def _make_api(tmp_path: Path, *, verify=False, dialog_result=None):
    class FakeWindow:
        def create_file_dialog(self, *args, **kwargs):
            return dialog_result

    api = D1HostApi(
        launch_token="token",
        window_getter=lambda: FakeWindow(),
        verify_save_dir=(tmp_path / "verify" if verify else None),
    )
    api.page_ready({"bridge_protocol": 1})
    return api


def _save_payload(filename="日计划.docx", data=DOCX_BYTES) -> dict:
    return {
        "request_id": uuid.uuid4().hex,
        "filename": filename,
        "payload_base64": base64.b64encode(data).decode(),
    }


class TestExportWordEvents:
    def test_saved_outcome_records_one_ok_event(self, tmp_path, bound_diagnostics):
        api = _make_api(tmp_path, verify=True)
        result = api.save_docx(_save_payload())
        assert result["status"] == "saved"
        events = _only_events()
        assert len(events) == 1
        assert events[0]["event_type"] == "export_word"
        assert events[0]["result"] == "ok"
        assert events[0]["error_code"] is None

    def test_canceled_dialog_records_canceled(self, tmp_path, bound_diagnostics):
        api = _make_api(tmp_path, dialog_result=None)
        result = api.save_docx(_save_payload())
        assert result == {"status": "canceled"}
        events = _only_events()
        assert len(events) == 1
        assert events[0]["result"] == "canceled"

    def test_write_failure_records_the_fixed_code(self, tmp_path, bound_diagnostics):
        # The dialog names a directory that does not exist: the atomic write
        # is refused before the commit point with the fixed SAVE_IO_ERROR.
        target = tmp_path / "missing-dir" / "x.docx"
        api = _make_api(tmp_path, dialog_result=str(target))
        result = api.save_docx(_save_payload())
        assert result["status"] == "failed", result
        assert result["code"] == "SAVE_IO_ERROR"
        events = _only_events()
        assert len(events) == 1
        assert events[0]["event_type"] == "export_word"
        assert events[0]["result"] == "failed"
        assert events[0]["error_code"] == "SAVE_IO_ERROR"

    def test_invalid_payload_records_nothing(self, tmp_path, bound_diagnostics):
        api = _make_api(tmp_path, dialog_result=str(tmp_path / "x.docx"))
        bad = _save_payload(data=b"not-a-zip")
        result = api.save_docx(bad)
        assert result["status"] == "failed"
        assert result["code"] == "INVALID_PAYLOAD"
        assert _only_events() == [], "no host save happened, no event"

    def test_replays_do_not_double_record(self, tmp_path, bound_diagnostics):
        target = tmp_path / "again.docx"
        api = _make_api(tmp_path, dialog_result=str(target))
        payload = _save_payload()
        assert api.save_docx(dict(payload))["status"] == "saved"
        assert api.save_docx(dict(payload))["status"] == "saved"
        events = _only_events()
        assert len(events) == 1, "a replayed operation id records once"

    def test_unlisted_or_crafted_export_codes_classify(self, bound_diagnostics):
        # Only the real fixed host errors travel verbatim; any other (or a
        # crafted canary) code classifies as EXPORT_FAILED.
        d1_host_api._record_export_word_result(
            {"status": "failed", "code": "SOME_UNLISTED_CODE"}
        )
        d1_host_api._record_export_word_result(
            {"status": "failed", "code": "SYNTHETIC_PRIVATE_CANARY"}
        )
        events = _only_events()
        assert [event["error_code"] for event in events] == [
            "EXPORT_FAILED",
            "EXPORT_FAILED",
        ]


class TestUpdateEventMapping:
    def _record(self, previous, state, code=None):
        update_service.UpdateManager._record_update_event(
            None, previous, state, code
        )

    def test_terminal_check_outcomes(self, bound_diagnostics):
        # A code already in the shared finite vocabulary passes verbatim.
        self._record("checking", "up_to_date")
        self._record("checking", "available")
        self._record("checking", "failed", "UPDATE_RATE_LIMITED")
        # The window reads newest first.
        events = _only_events()
        assert [event["result"] for event in events] == ["failed", "ok", "ok"]
        assert events[0]["event_type"] == "update_check"
        assert events[0]["error_code"] == "UPDATE_RATE_LIMITED"
        assert {event["event_type"] for event in events} == {"update_check"}

    def test_unlisted_real_update_code_merges_to_the_family_fallback(
        self, bound_diagnostics
    ):
        # A real code outside the shared vocabulary (e.g. a package
        # verification failure) never travels verbatim: it merges into the
        # fixed family fallback.
        self._record("verifying", "failed", "UPDATE_PACKAGE_INVALID")
        events = _only_events()
        assert len(events) == 1
        assert events[0]["event_type"] == "update_download"
        assert events[0]["result"] == "failed"
        assert events[0]["error_code"] == "UPDATE_DOWNLOAD_FAILED"

    def test_terminal_download_outcomes(self, bound_diagnostics):
        self._record("downloading", "ready")
        self._record("downloading", "cancelled")
        events = _only_events()
        assert [event["result"] for event in events] == ["canceled", "ok"]
        assert {event["event_type"] for event in events} == {"update_download"}

    def test_download_initiation_refusal_from_available(self, bound_diagnostics):
        self._record("available", "failed", "UPDATE_STAGING_UNSAFE")
        events = _only_events()
        assert len(events) == 1
        assert events[0]["event_type"] == "update_download"
        assert events[0]["result"] == "failed"
        assert events[0]["error_code"] == "UPDATE_STAGING_UNSAFE"

    def test_intermediate_and_foreign_transitions_record_nothing(
        self, bound_diagnostics
    ):
        for previous, state in (
            ("checking", "checking"),
            ("downloading", "verifying"),
            ("available", "downloading"),
            ("idle", "checking"),
            ("ready", "failed"),
        ):
            self._record(previous, state, None)
        assert _only_events() == []


class FakeOkBackup:
    def create(self, target, *, password, cancel, progress):
        progress({"stage": "db", "message_key": "复制数据库", "done": 1, "total": 2})
        return {"path": str(target)}


class SnapshotVerifyFailed(RuntimeError):
    """A backup engine failure carrying a fixed code, like the real core."""

    code = "SNAPSHOT_VERIFY_FAILED"


class SnapshotCancelledLike(RuntimeError):
    """The real cancel marker is matched by its type name or code."""

    code = "LOCAL_BACKUP_CANCELLED"


class FakeFailingBackup:
    def create(self, target, *, password, cancel, progress):
        raise SnapshotVerifyFailed("synthetic verify failure")


class FakeCancelledBackup:
    def create(self, target, *, password, cancel, progress):
        raise SnapshotCancelledLike("synthetic cancel")


def _wait_phase(host, request_id, phases, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = host.query({"request_id": request_id})
        if result.get("state") == "found":
            phase = result["status"]["phase"]
            if phase in phases:
                return result["status"]
        time.sleep(0.01)
    raise AssertionError(
        f"phase {phases} not reached: {host.query({'request_id': request_id})}"
    )


def _wait_events(count, timeout=5.0) -> list[dict]:
    """Wait until ``count`` diagnostic events have landed.

    The backup/update workers record the event in the same worker thread
    that commits the terminal phase; a status poll can observe the phase a
    moment before the event write completes, so tests wait for the event
    with the same bounded-pollution style as ``_wait_phase``.
    """
    deadline = time.monotonic() + timeout
    events: list[dict] = []
    while time.monotonic() < deadline:
        events = _only_events()
        if len(events) >= count:
            return events
        time.sleep(0.01)
    raise AssertionError(f"{count} diagnostics events not recorded: {events}")


class TestLocalBackupEvents:
    def test_completed_backup_records_ok(self, tmp_path, bound_diagnostics):
        host = mh.MaintenanceHost(backup_service=FakeOkBackup())
        target = host.register_target(
            tmp_path / "backup.kgmbackup", "backup.kgmbackup"
        )
        host.start_backup(
            request_id="diag-ok",
            target_id=target["target_id"],
            password="pw",
            explicit_plaintext=False,
        )
        status = _wait_phase(host, "diag-ok", {"completed"})
        assert status["phase"] == "completed"
        events = _wait_events(1)
        assert len(events) == 1
        assert events[0]["event_type"] == "local_backup"
        assert events[0]["result"] == "ok"

    def test_failed_backup_records_the_fixed_family_code(
        self, tmp_path, bound_diagnostics
    ):
        # The detailed core code stays in the operation status the teacher
        # already sees; the diagnostic event carries the fixed family code.
        host = mh.MaintenanceHost(backup_service=FakeFailingBackup())
        target = host.register_target(
            tmp_path / "backup.kgmbackup", "backup.kgmbackup"
        )
        host.start_backup(
            request_id="diag-fail",
            target_id=target["target_id"],
            password="pw",
            explicit_plaintext=False,
        )
        status = _wait_phase(host, "diag-fail", {"error"})
        assert status["error"]["code"] == "SNAPSHOT_VERIFY_FAILED"
        events = _wait_events(1)
        assert len(events) == 1
        assert events[0]["event_type"] == "local_backup"
        assert events[0]["result"] == "failed"
        assert events[0]["error_code"] == "BACKUP_FAILED"

    def test_unclassified_failure_uses_the_fallback_code(
        self, tmp_path, bound_diagnostics
    ):
        class PlainFailureBackup:
            def create(self, target, *, password, cancel, progress):
                raise RuntimeError("no code attribute")

        host = mh.MaintenanceHost(backup_service=PlainFailureBackup())
        target = host.register_target(
            tmp_path / "backup.kgmbackup", "backup.kgmbackup"
        )
        host.start_backup(
            request_id="diag-fallback",
            target_id=target["target_id"],
            password="pw",
            explicit_plaintext=False,
        )
        status = _wait_phase(host, "diag-fallback", {"error"})
        assert status["error"]["code"] == "BACKUP_FAILED"
        events = _wait_events(1)
        assert events[0]["result"] == "failed"
        assert events[0]["error_code"] == "BACKUP_FAILED"

    def test_cancelled_backup_records_canceled(self, tmp_path, bound_diagnostics):
        host = mh.MaintenanceHost(backup_service=FakeCancelledBackup())
        target = host.register_target(
            tmp_path / "backup.kgmbackup", "backup.kgmbackup"
        )
        host.start_backup(
            request_id="diag-cancel",
            target_id=target["target_id"],
            password="pw",
            explicit_plaintext=False,
        )
        status = _wait_phase(host, "diag-cancel", {"cancelled"})
        assert status["phase"] == "cancelled"
        events = _wait_events(1)
        assert len(events) == 1
        assert events[0]["result"] == "canceled"
        assert events[0]["error_code"] is None


class FakeWebdavUpload:
    def __init__(self):
        self.name = "kgm-backup-20261124T000000Z-" + "d" * 32 + ".kgmbackup"
        self.verified = True


class FakeWebdavFailed:
    def __init__(self, code, message):
        self.code = code
        self.message = message


class FakeWebdavError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


class FakeWebdavSnapshot:
    def __init__(self, path):
        self.path = path
        self.snapshot_id = "synthetic-snap"
        self.manifest = {"created_at": "2026-11-24T00:00:00Z"}


class TestWebdavBackupEvents:
    def _host(self, tmp_path, upload_result):
        class FakeBackup:
            def create(self, target, *, password, cancel, progress):
                path = Path(str(target))
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"synthetic-snapshot")
                return FakeWebdavSnapshot(path)

        class FakeClient:
            def __init__(self):
                self.uploads = 0

            def upload(self, path, snapshot_id, *, created_at=None, cancel=None, progress=None):
                self.uploads += 1
                if isinstance(upload_result, Exception):
                    raise upload_result
                return upload_result

        class FakeEndpoint:
            def __init__(self):
                self.url = "https://dav.example/backup/"
                self.username = "teacher"
                self.password = "secret"

        class FakeStore:
            def __init__(self):
                self.loaded = FakeEndpoint()

            def load(self):
                return self.loaded

            def save(self, *, url, username, password):
                return None

        client = FakeClient()
        host = mh.MaintenanceHost(
            backup_service=FakeBackup(),
            webdav_store=FakeStore(),
            webdav_client_factory=lambda _endpoint: client,
            webdav_work_root=tmp_path / "webdav-work",
        )
        return host

    def test_completed_webdav_backup_records_ok(self, tmp_path, bound_diagnostics):
        host = self._host(tmp_path, FakeWebdavUpload())
        host.start_webdav_backup(request_id="diag-webdav-ok", password="pw")
        status = _wait_phase(host, "diag-webdav-ok", {"completed", "error"})
        assert status["phase"] == "completed", status
        events = _wait_events(1)
        assert len(events) == 1
        assert events[0]["event_type"] == "webdav_backup"
        assert events[0]["result"] == "ok"

    def test_failed_webdav_upload_records_the_real_host_code(
        self, tmp_path, bound_diagnostics
    ):
        # WEBDAV_CONNECT_FAILED is one of the common real host errors kept
        # verbatim in the shared finite vocabulary.
        failure = FakeWebdavError(
            "WEBDAV_CONNECT_FAILED", "无法连接 WebDAV 服务器"
        )
        host = self._host(tmp_path, failure)
        host.start_webdav_backup(request_id="diag-webdav-fail", password="pw")
        status = _wait_phase(host, "diag-webdav-fail", {"error"})
        assert status["error"]["code"] == "WEBDAV_CONNECT_FAILED"
        events = _wait_events(1)
        assert len(events) == 1
        assert events[0]["event_type"] == "webdav_backup"
        assert events[0]["result"] == "failed"
        assert events[0]["error_code"] == "WEBDAV_CONNECT_FAILED"
