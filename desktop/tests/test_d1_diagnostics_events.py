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
import os
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

    def test_plaintext_backup_without_ack_records_the_rejection(
        self, tmp_path, bound_diagnostics
    ):
        # Neither a password nor an acknowledged plaintext upload: the fixed
        # rejection itself is recorded (merged onto the family fallback).
        host = self._host(tmp_path, FakeWebdavUpload())
        with pytest.raises(mh.MaintenanceHostError) as caught:
            host.start_webdav_backup(request_id="diag-webdav-plain", password=None)
        assert caught.value.code == "PLAINTEXT_NOT_ACKNOWLEDGED"
        events = _wait_events(1)
        assert events[0]["event_type"] == "webdav_backup"
        assert events[0]["result"] == "failed"
        assert events[0]["error_code"] == "WEBDAV_BACKUP_FAILED"


# ---------------------------------------------------------------------------
# Remote download + restore outcomes (2026-11-26 teacher feedback): every
# real download/verify/install failure enters the existing safe diagnostics
# with a fine-grained fixed code, and the teacher-facing message is the
# core's own fixed text instead of one identical generic line.
# ---------------------------------------------------------------------------


class RestoreFailureLike(RuntimeError):
    """A restore-core failure carrying a fixed code and fixed message."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclasses.dataclass(frozen=True)
class FakeRestorePreview:
    operation_id: str
    preview_id: str = "preview-1"
    package_name: str = "remote.kgmbackup"
    package_bytes: int = 1234
    package_sha256: str = "0" * 64
    snapshot_id: str = "snap-1"
    created_at: str = "2026-11-26T00:00:00Z"
    app_version: str = "0.1.0"
    source_revision: str = "0022"
    target_revision: str = "0022"
    counts: dict = dataclasses.field(default_factory=dict)
    profile_present: bool = True
    profile_name: str = "王老师"
    class_name: str = "中一班"
    term_names: tuple = ("上学期",)
    credential_configured: bool = False
    credential_ready: bool = True
    warnings: tuple = ()


@dataclasses.dataclass(frozen=True)
class FakeRestorePrepared:
    operation_id: str
    prepared_id: str = "prepared-1"


@dataclasses.dataclass(frozen=True)
class FakeRestoreInstall:
    operation_id: str
    state: str = "installed_retired"
    protection_display_path: str = ""
    reopen_required: bool = True
    warnings: tuple = ()


@dataclasses.dataclass(frozen=True)
class FakeRestoreCancel:
    operation_id: str
    state: str = "canceled"
    accepted: bool = True


@dataclasses.dataclass(frozen=True)
class FakeRestoreReopen:
    operation_id: str
    state: str = "reopened"


class FakeRestoreCore:
    def __init__(self):
        self.preview_error: Exception | None = None
        self.install_error: Exception | None = None

    def recover(self):
        return {"state": "none"}

    def preview(self, path, password, *, operation_id, cancel, progress):
        if self.preview_error is not None:
            raise self.preview_error
        return FakeRestorePreview(operation_id=operation_id)

    def prepare(self, preview, *, cancel, progress):
        return FakeRestorePrepared(operation_id=preview.operation_id)

    def install(self, prepared, *, hooks, cancel, progress):
        if self.install_error is not None:
            raise self.install_error
        return FakeRestoreInstall(operation_id=prepared.operation_id)

    def reopen(self):
        return FakeRestoreReopen(operation_id="op")

    def cancel(self, operation_id):
        return FakeRestoreCancel(operation_id=operation_id)


@dataclasses.dataclass(frozen=True)
class FakeWebdavDownload:
    name: str
    size: int
    sha256: str = "0" * 64
    encrypted: bool = True


class TestWebdavDownloadAndRestoreEvents:
    VERSION = "kgm-backup-20261126T000000Z-" + "e" * 32 + ".kgmbackup"

    def _host(self, tmp_path, *, core=None, download_result=None):
        class FakeClient:
            def __init__(self):
                self.download_error = None

            def ensure_collection(self, timeout=None):
                return {"ok": True, "created": False}

            def list_versions(self):
                return []

            def download(self, name, destination, *, fd=None, progress=None, cancel=None):
                if isinstance(download_result, Exception):
                    raise download_result
                if fd is not None:
                    with os.fdopen(fd, "wb") as sink:
                        sink.write(b"synthetic-remote-package")
                        sink.flush()
                        os.fsync(sink.fileno())
                else:
                    Path(destination).write_bytes(b"synthetic-remote-package")
                if progress is not None:
                    progress(
                        {"stage": "download", "done": 1, "total": 1}
                    )
                return download_result

        class FakeEndpoint:
            url = "https://dav.example/backup/"
            username = "teacher"
            password = "secret"

        class FakeStore:
            def load(self):
                return FakeEndpoint()

            def status(self):
                return {"configured": True, "password_available": True}

        client = FakeClient()
        host = mh.MaintenanceHost(
            backup_service=None,
            restore_core=core or FakeRestoreCore(),
            webdav_store=FakeStore(),
            webdav_client_factory=lambda _endpoint: client,
            webdav_work_root=tmp_path / "webdav-work",
        )
        host.test_endpoint_fingerprint = mh.MaintenanceHost._endpoint_fingerprint(
            FakeEndpoint()
        )
        return host

    def _download(self, host, request_id="diag-download"):
        host.start_webdav_download(
            request_id=request_id,
            version_name=self.VERSION,
            endpoint_fingerprint=host.test_endpoint_fingerprint,
        )
        return _wait_phase(host, request_id, {"downloaded", "error", "cancelled"})

    def test_failed_download_records_webdav_download_event(
        self, tmp_path, bound_diagnostics
    ):
        failure = FakeWebdavError(
            "WEBDAV_TIMEOUT", "WebDAV 操作超时，请稍后重试"
        )
        host = self._host(tmp_path, download_result=failure)
        host.start_webdav_download(
            request_id="diag-download-fail",
            version_name=self.VERSION,
            endpoint_fingerprint=host.test_endpoint_fingerprint,
        )
        status = _wait_phase(host, "diag-download-fail", {"error"})
        assert status["error"]["code"] == "WEBDAV_TIMEOUT"
        events = _wait_events(1)
        assert events[0]["event_type"] == "webdav_download"
        assert events[0]["result"] == "failed"
        assert events[0]["error_code"] == "WEBDAV_TIMEOUT"

    def test_completed_download_records_ok_and_mode_flag(
        self, tmp_path, bound_diagnostics
    ):
        # A no-password remote package reports encrypted=False so the panel
        # shows the clear hint; the ok event still lands in diagnostics.
        host = self._host(
            tmp_path,
            download_result=FakeWebdavDownload(
                name=self.VERSION, size=24, encrypted=False
            ),
        )
        status = self._download(host)
        assert status["phase"] == "downloaded"
        assert status["selection"]["encrypted"] is False
        events = _wait_events(1)
        assert events[0]["event_type"] == "webdav_download"
        assert events[0]["result"] == "ok"

    def test_verify_failure_records_webdav_restore_event_and_specific_message(
        self, tmp_path, bound_diagnostics
    ):
        core = FakeRestoreCore()
        core.preview_error = RestoreFailureLike(
            "RESTORE_PACKAGE_INVALID", "备份文件无效或不受支持"
        )
        host = self._host(tmp_path, core=core, download_result=FakeWebdavDownload(
            name=self.VERSION, size=24
        ))
        status = self._download(host)
        selection_id = status["selection"]["selection_id"]
        host.start_restore_verify(
            request_id="diag-verify-fail",
            selection_id=selection_id,
            password="pw",
        )
        verify_status = _wait_phase(host, "diag-verify-fail", {"error"})
        # The teacher sees the core's own fixed message plus the fixed code,
        # not the one identical generic line for every distinct cause.
        assert verify_status["error"]["code"] == "RESTORE_PACKAGE_INVALID"
        assert verify_status["error"]["message"] == "备份文件无效或不受支持"
        events = _wait_events(2)
        by_type = {(e["event_type"], e["result"]): e for e in events}
        assert ("webdav_download", "ok") in by_type
        failed = by_type[("webdav_restore", "failed")]
        assert failed["error_code"] == "RESTORE_PACKAGE_INVALID"

    def test_wrong_password_records_password_invalid_event(
        self, tmp_path, bound_diagnostics
    ):
        core = FakeRestoreCore()
        core.preview_error = RestoreFailureLike(
            "WRONG_PASSWORD", "密码不正确或备份认证失败"
        )
        host = self._host(tmp_path, core=core, download_result=FakeWebdavDownload(
            name=self.VERSION, size=24
        ))
        status = self._download(host)
        selection_id = status["selection"]["selection_id"]
        host.start_restore_verify(
            request_id="diag-wrong-password",
            selection_id=selection_id,
            password="wrong",
        )
        password_status = _wait_phase(host, "diag-wrong-password", {"password"})
        assert password_status["error"]["code"] == "WRONG_PASSWORD"
        events = _wait_events(2)
        failed = [e for e in events if e["result"] == "failed"]
        assert len(failed) == 1
        assert failed[0]["event_type"] == "webdav_restore"
        assert failed[0]["error_code"] == "RESTORE_PASSWORD_INVALID"

    def test_local_verify_failure_records_local_restore_event(
        self, tmp_path, bound_diagnostics
    ):
        core = FakeRestoreCore()
        core.preview_error = RestoreFailureLike(
            "RESTORE_VERIFY_FAILED", "备份校验失败"
        )
        host = mh.MaintenanceHost(restore_core=core)
        selection = host.register_selection(
            tmp_path / "local.kgmbackup", "local.kgmbackup", True
        )
        host.start_restore_verify(
            request_id="diag-local-verify",
            selection_id=selection["selection_id"],
            password="pw",
        )
        status = _wait_phase(host, "diag-local-verify", {"error"})
        assert status["error"]["message"] == "备份校验失败"
        events = _wait_events(1)
        assert events[0]["event_type"] == "local_restore"
        assert events[0]["result"] == "failed"
        assert events[0]["error_code"] == "RESTORE_VERIFY_FAILED"

    def test_completed_webdav_restore_records_ok(
        self, tmp_path, bound_diagnostics
    ):
        host = self._host(
            tmp_path,
            core=FakeRestoreCore(),
            download_result=FakeWebdavDownload(name=self.VERSION, size=24),
        )
        host.reopen_host = lambda: {"state": "reopened"}
        status = self._download(host)
        selection_id = status["selection"]["selection_id"]
        host.start_restore_verify(
            request_id="diag-restore-ok",
            selection_id=selection_id,
            password="pw",
        )
        preview = _wait_phase(host, "diag-restore-ok", {"preview"})
        host.confirm_restore(
            request_id="diag-restore-confirm",
            operation_id=preview["operation_id"],
            generation=preview["generation"],
            confirmation_token=preview["preview"]["preview_id"],
        )
        completed = _wait_phase(host, "diag-restore-confirm", {"completed", "error"})
        assert completed["phase"] == "completed", completed
        events = _wait_events(2)
        results = {(e["event_type"], e["result"]) for e in events}
        assert ("webdav_download", "ok") in results
        assert ("webdav_restore", "ok") in results

    def test_install_failure_records_install_failed_event(
        self, tmp_path, bound_diagnostics
    ):
        core = FakeRestoreCore()
        core.install_error = RestoreFailureLike(
            "RESTORE_FAILED", "恢复未完成"
        )
        host = self._host(tmp_path, core=core, download_result=FakeWebdavDownload(
            name=self.VERSION, size=24
        ))
        host.reopen_host = lambda: {"state": "reopened"}
        status = self._download(host)
        selection_id = status["selection"]["selection_id"]
        host.start_restore_verify(
            request_id="diag-install-fail",
            selection_id=selection_id,
            password="pw",
        )
        preview = _wait_phase(host, "diag-install-fail", {"preview"})
        host.confirm_restore(
            request_id="diag-install-confirm",
            operation_id=preview["operation_id"],
            generation=preview["generation"],
            confirmation_token=preview["preview"]["preview_id"],
        )
        failed_status = _wait_phase(
            host, "diag-install-confirm", {"completed", "error"}
        )
        assert failed_status["phase"] == "error"
        events = _wait_events(2)
        failed = [
            e for e in events if e["event_type"] == "webdav_restore"
            and e["result"] == "failed"
        ]
        assert len(failed) == 1
        assert failed[0]["error_code"] == "RESTORE_INSTALL_FAILED"
