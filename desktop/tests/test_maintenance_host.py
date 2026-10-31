"""B2 host maintenance coordinator: fake-core unit tests.

No real backup package, database, WebView2 window or network is used.  The
backup engine and restore core are explicit fakes; these tests pin the host
contract: request idempotency, foreign/conflicting refs, cancel/terminal
monotonicity, retirement, exact protection/reopen text and safe error DTOs.
"""

from __future__ import annotations

import dataclasses
import threading
import time
from pathlib import Path

import pytest

import maintenance_host as mh


@dataclasses.dataclass(frozen=True)
class FakePreview:
    operation_id: str
    preview_id: str
    package_name: str = "sample.kgmbackup"
    package_bytes: int = 1234
    package_sha256: str = "0" * 64
    snapshot_id: str = "snap-1"
    created_at: str = "2026-10-31T00:00:00Z"
    app_version: str = "0.1.0"
    source_revision: str = "0005"
    target_revision: str = "0005"
    counts: dict = dataclasses.field(
        default_factory=lambda: {"daily_plans": 1, "observations": 2, "assets": 3}
    )
    profile_present: bool = True
    profile_name: str = "王老师"
    class_name: str = "中一班"
    term_names: tuple = ("上学期",)
    credential_configured: bool = False
    credential_ready: bool = True
    warnings: tuple = ()


@dataclasses.dataclass(frozen=True)
class FakePrepared:
    operation_id: str
    prepared_id: str = "prepared-1"
    package_sha256: str = "0" * 64
    db_sha256: str = "1" * 64
    assets_manifest_hash: str = "2" * 64
    resource_count: int = 0
    resource_bytes: int = 0
    auth_change_count: int = 0
    profile_present: bool = True


@dataclasses.dataclass(frozen=True)
class FakeInstall:
    operation_id: str
    state: str = "installed_retired"
    protection_display_path: str = ""
    receipt_id: str | None = "receipt-1"
    old_group_preserved: bool = True
    lease_released: bool = True
    reopen_required: bool = True
    warnings: tuple = ()


@dataclasses.dataclass(frozen=True)
class FakeCancel:
    operation_id: str
    state: str = "canceled"
    accepted: bool = True


@dataclasses.dataclass(frozen=True)
class FakeReopen:
    operation_id: str
    state: str = "reopened"
    prompt_sync_error: str | None = None
    notice: dict | None = None
    error_code: str | None = None


class FakeBackupCancelled(Exception):
    code = "LOCAL_BACKUP_CANCELLED"


class FakeBackup:
    def __init__(self):
        self.calls = 0
        self.gate = threading.Event()
        self.gate.set()

    def create(self, target, *, password, cancel, progress):
        self.calls += 1
        self.gate.wait(2.0)
        if cancel.is_set():
            raise FakeBackupCancelled("synthetic backup cancelled")
        return {"path": str(target), "password": password}


class FakeCore:
    def __init__(self):
        self.preview_calls = 0
        self.install_calls = 0
        self.reopen_calls = 0
        self.cancel_calls: list[str] = []
        self.events: list[str] = []
        self.reopen_state = "reopened"
        self.install_state = "installed_retired"
        self.reopen_required = True
        self.protection = r"C:\Users\synthetic\protection\kgm-restore-protection-1"
        self.preview_gate = threading.Event()
        self.preview_gate.set()
        self.install_gate = threading.Event()
        self.install_gate.set()
        self.switch_gate = threading.Event()
        self.switch_gate.set()
        self.preview_error: Exception | None = None
        self.prepare_error: Exception | None = None
        self.install_error: Exception | None = None
        self.reopen_error: Exception | None = None

    def preview(self, path, password, *, operation_id, cancel, progress):
        self.preview_calls += 1
        self.preview_gate.wait(2.0)
        if self.preview_error is not None:
            raise self.preview_error
        return FakePreview(operation_id=operation_id, preview_id="preview-1")

    def prepare(self, preview, *, cancel, progress):
        if self.prepare_error is not None:
            raise self.prepare_error
        return FakePrepared(operation_id=preview.operation_id)

    def install(self, prepared, *, hooks, cancel, progress):
        self.install_calls += 1
        self.install_gate.wait(2.0)
        if hooks is not None:
            if not hooks.wait_host_idle(cancel):
                raise mh.MaintenanceHostError("RESTORE_QUIESCE_FAILED", "idle")
            if not hooks.stop_transport():
                raise mh.MaintenanceHostError("RESTORE_QUIESCE_FAILED", "stop")
        if progress is not None:
            progress({"stage": "switch", "done": 0, "total": 1})
        self.switch_gate.wait(2.0)
        if self.install_error is not None:
            raise self.install_error
        return FakeInstall(
            operation_id=prepared.operation_id,
            state=self.install_state,
            protection_display_path=self.protection,
            reopen_required=self.reopen_required,
        )

    def cancel(self, operation_id):
        self.cancel_calls.append(operation_id)
        return FakeCancel(operation_id=operation_id)

    def reopen(self):
        self.reopen_calls += 1
        self.events.append("reopen")
        if self.reopen_error is not None:
            raise self.reopen_error
        return FakeReopen(operation_id="op", state=self.reopen_state)

    def recover(self):
        return {"state": "none"}


def wait_phase(host: mh.MaintenanceHost, request_id: str, phases, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = host.query({"request_id": request_id})
        if result.get("state") == "found":
            phase = result["status"]["phase"]
            if phase in phases:
                return result["status"]
        time.sleep(0.01)
    raise AssertionError(f"phase {phases} not reached: {host.query({'request_id': request_id})}")


@pytest.fixture()
def host(tmp_path: Path):
    backup = FakeBackup()
    core = FakeCore()
    host = mh.MaintenanceHost(backup_service=backup, restore_core=core)
    return host, backup, core


def _selection(host: mh.MaintenanceHost, name="sample.kgmbackup", encrypted=False):
    return host.register_selection(Path("C:/synthetic") / name, name, encrypted)


def test_backup_request_id_is_idempotent_and_conflicting_payload_refused(host):
    host, backup, _core = host
    target = host.register_target(Path("C:/synthetic/backup.kgmbackup"), "backup.kgmbackup")
    backup.gate.clear()
    first = host.start_backup(
        request_id="req-1",
        target_id=target["target_id"],
        password="pw",
        explicit_plaintext=False,
    )
    second = host.start_backup(
        request_id="req-1",
        target_id=target["target_id"],
        password="pw",
        explicit_plaintext=False,
    )
    assert first["operation_id"] == second["operation_id"]
    assert first["generation"] == second["generation"]
    assert backup.calls == 1
    with pytest.raises(mh.MaintenanceHostError) as conflict:
        host.start_backup(
            request_id="req-1",
            target_id=target["target_id"],
            password="different",
            explicit_plaintext=False,
        )
    assert conflict.value.code == "REQUEST_CONFLICT"
    backup.gate.set()
    wait_phase(host, "req-1", {"completed"})


def test_empty_password_never_downgrades_to_plaintext(host):
    host, _backup, _core = host
    target = host.register_target(Path("C:/synthetic/backup.kgmbackup"), "backup.kgmbackup")
    with pytest.raises(mh.MaintenanceHostError) as exc:
        host.start_backup(
            request_id="req-empty",
            target_id=target["target_id"],
            password="",
            explicit_plaintext=True,
        )
    assert exc.value.code == "PASSWORD_REQUIRED"
    with pytest.raises(mh.MaintenanceHostError) as exc:
        host.start_backup(
            request_id="req-plain",
            target_id=target["target_id"],
            password=None,
            explicit_plaintext=False,
        )
    assert exc.value.code == "PLAINTEXT_NOT_ACKNOWLEDGED"


def test_restore_preview_confirm_idempotent_and_foreign_refs_rejected(host):
    host, _backup, core = host
    selection = _selection(host)
    core.preview_gate.clear()
    ref = host.start_restore_verify(
        request_id="verify-1",
        selection_id=selection["selection_id"],
        password=None,
    )
    core.preview_gate.set()
    status = wait_phase(host, "verify-1", {"preview"})
    assert status["preview"]["preview_id"] == "preview-1"

    # A foreign request id pointing at this operation is not accepted.
    with pytest.raises(mh.MaintenanceHostError) as foreign:
        host.confirm_restore(
            request_id="foreign-request",
            operation_id=ref["operation_id"],
            generation=ref["generation"],
            confirmation_token="not-the-token",
        )
    assert foreign.value.code == "PREVIEW_STALE"

    core.install_gate.clear()
    confirmed = host.confirm_restore(
        request_id="confirm-1",
        operation_id=ref["operation_id"],
        generation=ref["generation"],
        confirmation_token="preview-1",
    )
    again = host.confirm_restore(
        request_id="confirm-1",
        operation_id=ref["operation_id"],
        generation=ref["generation"],
        confirmation_token="preview-1",
    )
    assert confirmed["operation_id"] == again["operation_id"]
    with pytest.raises(mh.MaintenanceHostError) as conflict:
        host.confirm_restore(
            request_id="confirm-1",
            operation_id=ref["operation_id"],
            generation=ref["generation"],
            confirmation_token="other-token",
        )
    assert conflict.value.code == "REQUEST_CONFLICT"
    core.install_gate.set()
    final = wait_phase(host, "confirm-1", {"completed", "error"})
    assert core.install_calls == 1
    assert final["phase"] == "completed"
    expected_notice = (
        "恢复前保护副本："
        r"C:\Users\synthetic\protection\kgm-restore-protection-1"
        "。自动保留，不会自动删除。"
    )
    assert final["protection"]["display_text"] == expected_notice
    assert host.completion_notice() == expected_notice


def test_duplicate_confirm_with_new_request_id_never_reinstalls(host):
    host, _backup, core = host
    selection = _selection(host)
    ref = host.start_restore_verify(
        request_id="verify-dup", selection_id=selection["selection_id"], password=None
    )
    wait_phase(host, "verify-dup", {"preview"})
    core.install_gate.clear()
    host.confirm_restore(
        request_id="confirm-first",
        operation_id=ref["operation_id"],
        generation=ref["generation"],
        confirmation_token="preview-1",
    )
    # A second confirmation with a different request id while the first is
    # still in flight must not start a second install.
    with pytest.raises(mh.MaintenanceHostError) as stale:
        host.confirm_restore(
            request_id="confirm-second",
            operation_id=ref["operation_id"],
            generation=ref["generation"],
            confirmation_token="preview-1",
        )
    assert stale.value.code == "PREVIEW_STALE"
    core.install_gate.set()
    wait_phase(host, "confirm-first", {"completed"})
    assert core.install_calls == 1
    # After completion, replaying the old preview with another request id is
    # still refused, and the completed result is unchanged.
    with pytest.raises(mh.MaintenanceHostError) as stale_after:
        host.confirm_restore(
            request_id="confirm-third",
            operation_id=ref["operation_id"],
            generation=ref["generation"],
            confirmation_token="preview-1",
        )
    assert stale_after.value.code == "PREVIEW_STALE"
    assert core.install_calls == 1
    assert host.query({"request_id": "confirm-first"})["status"]["phase"] == "completed"


def test_recovery_required_blocks_new_operations_but_keeps_query(host):
    host, _backup, core = host
    core.install_state = "recovery_required"
    selection = _selection(host)
    ref = host.start_restore_verify(
        request_id="verify-rec", selection_id=selection["selection_id"], password=None
    )
    wait_phase(host, "verify-rec", {"preview"})
    host.confirm_restore(
        request_id="confirm-rec",
        operation_id=ref["operation_id"],
        generation=ref["generation"],
        confirmation_token="preview-1",
    )
    status = wait_phase(host, "confirm-rec", {"error"})
    assert status["error"]["code"] == "RESTORE_RECOVERY_REQUIRED"
    assert status["error"]["committed"] is True
    assert status["phase"] == "error"
    # The old operation can still be queried; no new operation may start
    # until the app restarts and resolves the journal.
    assert host.query({"request_id": "confirm-rec"})["state"] == "found"
    target = host.register_target(Path("C:/synthetic/backup.kgmbackup"), "backup.kgmbackup")
    with pytest.raises(mh.MaintenanceHostError) as blocked_backup:
        host.start_backup(
            request_id="req-after-rec",
            target_id=target["target_id"],
            password=None,
            explicit_plaintext=True,
        )
    assert blocked_backup.value.code == "RECOVERY_REQUIRED"
    with pytest.raises(mh.MaintenanceHostError) as blocked_verify:
        host.start_restore_verify(
            request_id="verify-after-rec",
            selection_id=selection["selection_id"],
            password=None,
        )
    assert blocked_verify.value.code == "RECOVERY_REQUIRED"


def test_rejected_start_is_queryable_by_same_request_id(host):
    host, _backup, _core = host
    target = host.register_target(Path("C:/synthetic/backup.kgmbackup"), "backup.kgmbackup")
    with pytest.raises(mh.MaintenanceHostError) as rejected:
        host.start_backup(
            request_id="rejected-backup",
            target_id=target["target_id"],
            password="",
            explicit_plaintext=True,
        )
    assert rejected.value.code == "PASSWORD_REQUIRED"
    result = host.query({"request_id": "rejected-backup"})
    assert result["state"] == "found"
    status = result["status"]
    assert status["phase"] == "error"
    assert status["error"]["code"] == "PASSWORD_REQUIRED"
    # A lost reply can be retried with the same request id: it resolves to
    # the same terminal record instead of starting a second side effect.
    ref = host.start_backup(
        request_id="rejected-backup",
        target_id=target["target_id"],
        password="",
        explicit_plaintext=True,
    )
    assert ref["operation_id"] == status["operation_id"]
    assert host.query({"request_id": "rejected-backup"})["status"]["error"]["code"] == "PASSWORD_REQUIRED"


def test_rejected_confirm_is_queryable_and_preview_stays_usable(host):
    host, _backup, core = host
    selection = _selection(host)
    ref = host.start_restore_verify(
        request_id="verify-stale", selection_id=selection["selection_id"], password=None
    )
    wait_phase(host, "verify-stale", {"preview"})
    with pytest.raises(mh.MaintenanceHostError) as rejected:
        host.confirm_restore(
            request_id="rejected-confirm",
            operation_id=ref["operation_id"],
            generation=ref["generation"],
            confirmation_token="wrong-token",
        )
    assert rejected.value.code == "PREVIEW_STALE"
    result = host.query({"request_id": "rejected-confirm"})
    assert result["state"] == "found"
    assert result["status"]["error"]["code"] == "PREVIEW_STALE"
    # The rejection record did not overwrite the real preview.
    assert host.query({"request_id": "verify-stale"})["status"]["phase"] == "preview"
    host.confirm_restore(
        request_id="good-confirm",
        operation_id=ref["operation_id"],
        generation=ref["generation"],
        confirmation_token="preview-1",
    )
    final = wait_phase(host, "good-confirm", {"completed", "error"})
    assert final["phase"] == "completed"
    assert core.install_calls == 1


def test_old_host_retires_before_core_reopen(host):
    host, _backup, core = host
    host.before_reopen = lambda: core.events.append("retire-old")
    selection = _selection(host)
    ref = host.start_restore_verify(
        request_id="verify-order", selection_id=selection["selection_id"], password=None
    )
    wait_phase(host, "verify-order", {"preview"})
    host.confirm_restore(
        request_id="confirm-order",
        operation_id=ref["operation_id"],
        generation=ref["generation"],
        confirmation_token="preview-1",
    )
    status = wait_phase(host, "confirm-order", {"completed", "error"})
    assert status["phase"] == "completed"
    assert core.events == ["retire-old", "reopen"]


def test_before_reopen_failure_never_opens_new_engine(host):
    host, _backup, core = host
    def fail_retire():
        raise RuntimeError("synthetic retire failure")
    host.before_reopen = fail_retire
    selection = _selection(host)
    ref = host.start_restore_verify(
        request_id="verify-retire-fail",
        selection_id=selection["selection_id"],
        password=None,
    )
    wait_phase(host, "verify-retire-fail", {"preview"})
    host.confirm_restore(
        request_id="confirm-retire-fail",
        operation_id=ref["operation_id"],
        generation=ref["generation"],
        confirmation_token="preview-1",
    )
    status = wait_phase(host, "confirm-retire-fail", {"error"})
    assert status["error"]["code"] == "RESTORE_RESTART_REQUIRED"
    assert status["error"]["committed"] is True
    assert core.reopen_calls == 0
    with pytest.raises(mh.MaintenanceHostError) as blocked:
        host.start_restore_verify(
            request_id="verify-after-retire-fail",
            selection_id=selection["selection_id"],
            password=None,
        )
    assert blocked.value.code == "RECOVERY_REQUIRED"


def test_canceled_after_transport_stop_reports_restart_not_cancelled():
    backup = FakeBackup()
    core = FakeCore()
    core.install_state = "canceled"

    class Hooks:
        def wait_host_idle(self, cancel):
            return True
        def stop_transport(self):
            return True

    host = mh.MaintenanceHost(
        backup_service=backup, restore_core=core, hooks=Hooks()
    )
    selection = host.register_selection(Path("C:/synthetic/x.kgmbackup"), "x", False)
    ref = host.start_restore_verify(
        request_id="verify-cancel-transport",
        selection_id=selection["selection_id"],
        password=None,
    )
    wait_phase(host, "verify-cancel-transport", {"preview"})
    host.confirm_restore(
        request_id="confirm-cancel-transport",
        operation_id=ref["operation_id"],
        generation=ref["generation"],
        confirmation_token="preview-1",
    )
    status = wait_phase(host, "confirm-cancel-transport", {"error", "cancelled"})
    assert status["phase"] == "error"
    assert status["error"]["code"] == "RESTORE_RESTART_REQUIRED"
    assert status["error"]["committed"] is True


def test_failed_keep_old_after_transport_stop_reports_restart_not_unchanged():
    backup = FakeBackup()
    core = FakeCore()
    core.install_state = "failed_keep_old"
    core.reopen_required = False

    class Hooks:
        def wait_host_idle(self, cancel):
            return True
        def stop_transport(self):
            return True

    host = mh.MaintenanceHost(
        backup_service=backup, restore_core=core, hooks=Hooks()
    )
    selection = host.register_selection(Path("C:/synthetic/x.kgmbackup"), "x", False)
    ref = host.start_restore_verify(
        request_id="verify-failed-transport",
        selection_id=selection["selection_id"],
        password=None,
    )
    wait_phase(host, "verify-failed-transport", {"preview"})
    host.confirm_restore(
        request_id="confirm-failed-transport",
        operation_id=ref["operation_id"],
        generation=ref["generation"],
        confirmation_token="preview-1",
    )
    status = wait_phase(host, "confirm-failed-transport", {"error"})
    assert status["error"]["code"] == "RESTORE_RESTART_REQUIRED"
    assert status["error"]["committed"] is True
    assert "未更改" not in status["error"]["message"]


def test_protection_verify_progress_stays_cancellable():
    backup = FakeBackup()

    class ProtectionCore(FakeCore):
        def __init__(self):
            super().__init__()
            self.at_verify = threading.Event()
            self.release = threading.Event()

        def install(self, prepared, *, hooks, cancel, progress):
            progress(
                {
                    "stage": "verify",
                    "done": 0,
                    "total": 1,
                    "message_key": "verify protection snapshot",
                }
            )
            self.at_verify.set()
            assert self.release.wait(3)
            return FakeInstall(
                operation_id=prepared.operation_id,
                state="canceled" if cancel.is_set() else "installed_retired",
                protection_display_path="synthetic protection",
                reopen_required=False,
            )

    core = ProtectionCore()
    host = mh.MaintenanceHost(backup_service=backup, restore_core=core)
    selection = host.register_selection(Path("C:/synthetic/x.kgmbackup"), "x", False)
    ref = host.start_restore_verify(
        request_id="verify-protection",
        selection_id=selection["selection_id"],
        password=None,
    )
    wait_phase(host, "verify-protection", {"preview"})
    host.confirm_restore(
        request_id="confirm-protection",
        operation_id=ref["operation_id"],
        generation=ref["generation"],
        confirmation_token="preview-1",
    )
    assert core.at_verify.wait(3)
    before = host.query({"request_id": "confirm-protection"})["status"]
    assert before["phase"] == "protection"
    assert before["progress"]["stage"] == "校验数据"
    ack = host.cancel(
        {"operation_id": ref["operation_id"], "generation": ref["generation"]}
    )
    assert ack["accepted"] is True
    assert ack["state"] != "too_late"
    core.release.set()
    final = wait_phase(host, "confirm-protection", {"cancelled", "error", "completed"})
    assert final["phase"] == "cancelled"
    assert core.reopen_calls == 0


def test_progress_keys_are_mapped_to_teacher_text():
    class ProgressBackup:
        def __init__(self):
            self.gate = threading.Event()

        def create(self, target, *, password, cancel, progress):
            progress(
                {
                    "stage": "prepare",
                    "done": 1,
                    "total": 2,
                    "message_key": "copy_database",
                }
            )
            self.gate.wait(2)
            return {"output": str(target)}

    backup = ProgressBackup()
    host = mh.MaintenanceHost(backup_service=backup)
    target = host.register_target(Path("C:/synthetic/backup.kgmbackup"), "backup.kgmbackup")
    host.start_backup(
        request_id="req-progress",
        target_id=target["target_id"],
        password=None,
        explicit_plaintext=True,
    )
    deadline = time.monotonic() + 2
    progress = None
    while time.monotonic() < deadline:
        status = host.query({"request_id": "req-progress"})["status"]
        progress = status.get("progress")
        if progress:
            break
        time.sleep(0.01)
    assert progress is not None
    assert progress["stage"] == "准备恢复文件"
    assert progress["message"] == "复制数据库"
    assert "prepare" not in str(progress)
    assert "copy_database" not in str(progress)
    backup.gate.set()
    wait_phase(host, "req-progress", {"completed"})


def test_unknown_progress_keys_get_neutral_chinese():
    class ProgressBackup:
        def __init__(self):
            self.gate = threading.Event()

        def create(self, target, *, password, cancel, progress):
            progress(
                {
                    "stage": "future_stage",
                    "done": 0,
                    "total": 0,
                    "message_key": "future_key",
                }
            )
            self.gate.wait(2)
            return {"output": str(target)}

    backup = ProgressBackup()
    host = mh.MaintenanceHost(backup_service=backup)
    target = host.register_target(Path("C:/synthetic/backup.kgmbackup"), "backup.kgmbackup")
    host.start_backup(
        request_id="req-future-progress",
        target_id=target["target_id"],
        password=None,
        explicit_plaintext=True,
    )
    deadline = time.monotonic() + 2
    progress = None
    while time.monotonic() < deadline:
        progress = host.query({"request_id": "req-future-progress"})["status"].get("progress")
        if progress:
            break
        time.sleep(0.01)
    assert progress is not None
    assert progress["stage"] == "维护操作进行中"
    assert progress["message"] == "正在处理"
    backup.gate.set()
    wait_phase(host, "req-future-progress", {"completed"})


def test_wrong_password_retry_then_cancel_has_no_abandoned_active(host):
    host, _backup, core = host
    core.preview_error = mh.MaintenanceHostError("WRONG_PASSWORD", "bad")
    selection = _selection(host, encrypted=True)
    old = host.start_restore_verify(
        request_id="wrong-password",
        selection_id=selection["selection_id"],
        password="wrong",
    )
    wait_phase(host, "wrong-password", {"password"})
    core.preview_error = None
    new = host.start_restore_verify(
        request_id="correct-password",
        selection_id=selection["selection_id"],
        password="correct",
    )
    wait_phase(host, "correct-password", {"preview"})
    ack = host.cancel(
        {"operation_id": new["operation_id"], "generation": new["generation"]}
    )
    assert ack == {"accepted": True, "state": "cancelled"}
    assert host.has_active_operation() is False
    # The superseded wrong-password request remains readable by requestId,
    # but its core verification was retired, not left active.
    old_status = host.query({"request_id": "wrong-password"})["status"]
    assert old_status["phase"] == "password"
    assert old_status["error"]["code"] == "WRONG_PASSWORD"
    assert old["operation_id"] in core.cancel_calls
    assert new["operation_id"] in core.cancel_calls


def test_wrong_password_stays_on_password_phase(host):
    host, _backup, core = host
    core.preview_error = mh.MaintenanceHostError("WRONG_PASSWORD", "bad")
    selection = _selection(host, encrypted=True)
    host.start_restore_verify(
        request_id="verify-bad",
        selection_id=selection["selection_id"],
        password="wrong",
    )
    status = wait_phase(host, "verify-bad", {"password", "error"})
    assert status["phase"] == "password"
    assert status["error"]["code"] == "WRONG_PASSWORD"
    assert "SQL" not in status["error"]["message"]


def test_reopen_failure_is_committed_and_uses_exact_text(host):
    host, _backup, core = host
    core.reopen_state = "reopen_failed"
    selection = _selection(host)
    ref = host.start_restore_verify(
        request_id="verify-2", selection_id=selection["selection_id"], password=None
    )
    wait_phase(host, "verify-2", {"preview"})
    host.confirm_restore(
        request_id="confirm-2",
        operation_id=ref["operation_id"],
        generation=ref["generation"],
        confirmation_token="preview-1",
    )
    status = wait_phase(host, "confirm-2", {"error"})
    assert status["error"]["code"] == "REOPEN_FAILED"
    assert status["error"]["message"] == "资料已恢复，重新打开失败，请重启应用"
    assert status["error"]["committed"] is True
    assert status["protection"]["display_text"].startswith("恢复前保护副本：")
    assert status["reopened"] is False


def test_prepare_failure_before_live_change_keeps_unchanged_claim(host):
    host, _backup, core = host
    core.prepare_error = RuntimeError("synthetic prepare failure")
    selection = _selection(host)
    ref = host.start_restore_verify(
        request_id="verify-8", selection_id=selection["selection_id"], password=None
    )
    wait_phase(host, "verify-8", {"preview"})
    host.confirm_restore(
        request_id="confirm-8",
        operation_id=ref["operation_id"],
        generation=ref["generation"],
        confirmation_token="preview-1",
    )
    status = wait_phase(host, "confirm-8", {"error"})
    assert status["error"]["committed"] is False
    assert "当前档案未更改" in status["error"]["message"]
    assert core.install_calls == 0


def test_unexpected_install_exception_blocks_new_operations_as_recovery(host):
    host, _backup, core = host
    core.install_error = RuntimeError("synthetic post-rename failure")
    selection = _selection(host)
    ref = host.start_restore_verify(
        request_id="verify-9", selection_id=selection["selection_id"], password=None
    )
    wait_phase(host, "verify-9", {"preview"})
    host.confirm_restore(
        request_id="confirm-9",
        operation_id=ref["operation_id"],
        generation=ref["generation"],
        confirmation_token="preview-1",
    )
    status = wait_phase(host, "confirm-9", {"error"})
    assert status["error"]["committed"] is True
    assert "请重启应用核对当前档案" in status["error"]["message"]
    with pytest.raises(mh.MaintenanceHostError) as blocked:
        host.start_restore_verify(
            request_id="verify-after-install-error",
            selection_id=selection["selection_id"],
            password=None,
        )
    assert blocked.value.code == "RECOVERY_REQUIRED"


def test_failed_keep_old_without_live_change_allows_a_new_attempt(host):
    host, _backup, core = host
    core.install_state = "failed_keep_old"
    core.reopen_required = False
    selection = _selection(host)
    ref = host.start_restore_verify(
        request_id="verify-10", selection_id=selection["selection_id"], password=None
    )
    wait_phase(host, "verify-10", {"preview"})
    host.confirm_restore(
        request_id="confirm-10",
        operation_id=ref["operation_id"],
        generation=ref["generation"],
        confirmation_token="preview-1",
    )
    status = wait_phase(host, "confirm-10", {"error"})
    assert status["error"]["committed"] is False
    # No live change was reported: a new preview may start without a restart.
    again = host.start_restore_verify(
        request_id="verify-10-retry",
        selection_id=selection["selection_id"],
        password=None,
    )
    assert again["operation_id"] != ref["operation_id"]


def test_unexpected_reopen_exception_after_install_uses_reopen_failed(host):
    host, _backup, core = host
    core.reopen_error = RuntimeError("synthetic engine failure")
    selection = _selection(host)
    ref = host.start_restore_verify(
        request_id="verify-7", selection_id=selection["selection_id"], password=None
    )
    wait_phase(host, "verify-7", {"preview"})
    host.confirm_restore(
        request_id="confirm-7",
        operation_id=ref["operation_id"],
        generation=ref["generation"],
        confirmation_token="preview-1",
    )
    status = wait_phase(host, "confirm-7", {"error"})
    assert status["error"]["code"] == "REOPEN_FAILED"
    assert status["error"]["message"] == "资料已恢复，重新打开失败，请重启应用"
    assert status["error"]["committed"] is True


def test_reopen_host_failure_is_reopen_failed_not_completed(tmp_path):
    _backup = FakeBackup()
    core = FakeCore()
    calls = []

    def reopen_host():
        calls.append("reopen-host")
        return {"state": "reopen_failed", "code": "REOPEN_PAGE_TIMEOUT"}

    host = mh.MaintenanceHost(
        backup_service=_backup, restore_core=core, reopen_host=reopen_host
    )
    selection = host.register_selection(Path("C:/synthetic/x.kgmbackup"), "x", False)
    ref = host.start_restore_verify(
        request_id="verify-3", selection_id=selection["selection_id"], password=None
    )
    wait_phase(host, "verify-3", {"preview"})
    host.confirm_restore(
        request_id="confirm-3",
        operation_id=ref["operation_id"],
        generation=ref["generation"],
        confirmation_token="preview-1",
    )
    status = wait_phase(host, "confirm-3", {"error"})
    assert calls == ["reopen-host"]
    assert status["error"]["code"] == "REOPEN_FAILED"
    assert status["error"]["committed"] is True
    with pytest.raises(mh.MaintenanceHostError) as blocked:
        host.start_restore_verify(
            request_id="verify-after-reopen-failed",
            selection_id=selection["selection_id"],
            password=None,
        )
    assert blocked.value.code == "RECOVERY_REQUIRED"


def test_failed_keep_old_is_honest_about_restart_requirement(host):
    host, _backup, core = host
    core.install_state = "failed_keep_old"
    selection = _selection(host)
    ref = host.start_restore_verify(
        request_id="verify-5", selection_id=selection["selection_id"], password=None
    )
    wait_phase(host, "verify-5", {"preview"})
    host.confirm_restore(
        request_id="confirm-5",
        operation_id=ref["operation_id"],
        generation=ref["generation"],
        confirmation_token="preview-1",
    )
    status = wait_phase(host, "confirm-5", {"error"})
    assert status["error"]["code"] == "RESTORE_RESTART_REQUIRED"
    assert status["error"]["committed"] is True
    assert "未更改" not in status["error"]["message"]
    with pytest.raises(mh.MaintenanceHostError) as blocked:
        host.start_restore_verify(
            request_id="verify-after-restart-required",
            selection_id=selection["selection_id"],
            password=None,
        )
    assert blocked.value.code == "RECOVERY_REQUIRED"


def test_failed_keep_old_before_live_change_keeps_unchanged_claim(host):
    host, _backup, core = host
    core.install_state = "failed_keep_old"
    core.reopen_required = False
    selection = _selection(host)
    ref = host.start_restore_verify(
        request_id="verify-6", selection_id=selection["selection_id"], password=None
    )
    wait_phase(host, "verify-6", {"preview"})
    host.confirm_restore(
        request_id="confirm-6",
        operation_id=ref["operation_id"],
        generation=ref["generation"],
        confirmation_token="preview-1",
    )
    status = wait_phase(host, "confirm-6", {"error"})
    assert status["error"]["code"] == "RESTORE_FAILED"
    assert status["error"]["committed"] is False
    assert "当前档案未更改" in status["error"]["message"]


def test_cancel_after_transport_stop_is_too_late_not_fake_cancelled():
    backup = FakeBackup()
    core = FakeCore()

    class Hooks:
        def __init__(self):
            self.stopped = 0

        def wait_host_idle(self, cancel):
            return True

        def stop_transport(self):
            self.stopped += 1
            return True

    hooks = Hooks()
    host = mh.MaintenanceHost(
        backup_service=backup, restore_core=core, hooks=hooks
    )
    selection = host.register_selection(Path("C:/synthetic/x.kgmbackup"), "x", False)
    ref = host.start_restore_verify(
        request_id="verify-switch", selection_id=selection["selection_id"], password=None
    )
    wait_phase(host, "verify-switch", {"preview"})
    core.switch_gate.clear()
    host.confirm_restore(
        request_id="confirm-switch",
        operation_id=ref["operation_id"],
        generation=ref["generation"],
        confirmation_token="preview-1",
    )
    status = wait_phase(host, "confirm-switch", {"switching"})
    assert status["phase"] == "switching"
    ack = host.cancel(
        {"operation_id": ref["operation_id"], "generation": ref["generation"]}
    )
    assert ack == {"accepted": False, "state": "too_late"}
    core.switch_gate.set()
    final = wait_phase(host, "confirm-switch", {"completed", "error"})
    assert final["phase"] == "completed"
    assert hooks.stopped == 1


def test_cancel_is_terminal_and_late_ack_does_not_regress(host):
    host, backup, _core = host
    target = host.register_target(Path("C:/synthetic/backup.kgmbackup"), "backup.kgmbackup")
    backup.gate.clear()
    ref = host.start_backup(
        request_id="req-cancel",
        target_id=target["target_id"],
        password=None,
        explicit_plaintext=True,
    )
    ack = host.cancel({"operation_id": ref["operation_id"], "generation": ref["generation"]})
    assert ack == {"accepted": True, "state": "unknown"}
    backup.gate.set()
    wait_phase(host, "req-cancel", {"cancelled"})
    late = host.cancel({"operation_id": ref["operation_id"], "generation": ref["generation"]})
    assert late["accepted"] is False
    assert late["state"] == "completed"


def test_retired_host_refuses_old_confirm_without_install(host):
    host, _backup, core = host
    selection = _selection(host)
    ref = host.start_restore_verify(
        request_id="verify-retired-confirm",
        selection_id=selection["selection_id"],
        password=None,
    )
    wait_phase(host, "verify-retired-confirm", {"preview"})
    host.retire()
    with pytest.raises(mh.MaintenanceHostError) as retired:
        host.confirm_restore(
            request_id="confirm-after-retire",
            operation_id=ref["operation_id"],
            generation=ref["generation"],
            confirmation_token="preview-1",
        )
    assert retired.value.code == "HOST_RETIRED"
    assert core.install_calls == 0
    # The old preview is still queryable read-only for the closing page.
    assert host.query({"request_id": "verify-retired-confirm"})["status"]["phase"] == "preview"


def test_retire_keeps_old_status_query_but_refuses_new_start(host):
    host, backup, _core = host
    target = host.register_target(Path("C:/synthetic/backup.kgmbackup"), "backup.kgmbackup")
    backup.gate.clear()
    host.start_backup(
        request_id="req-retire",
        target_id=target["target_id"],
        password=None,
        explicit_plaintext=True,
    )
    host.retire()
    # The old window may still poll its own operation.
    assert host.query({"request_id": "req-retire"})["state"] == "found"
    with pytest.raises(mh.MaintenanceHostError) as retired:
        host.start_backup(
            request_id="req-new",
            target_id=target["target_id"],
            password=None,
            explicit_plaintext=True,
        )
    assert retired.value.code == "HOST_RETIRED"
    backup.gate.set()
    # Retirement does not cancel an already accepted old operation: it keeps
    # running to a terminal state while the old window may poll it read-only.
    wait_phase(host, "req-retire", {"completed"})


def test_cancel_preview_retires_the_confirmation_token(host):
    host, _backup, _core = host
    selection = _selection(host)
    ref = host.start_restore_verify(
        request_id="verify-preview-cancel",
        selection_id=selection["selection_id"],
        password=None,
    )
    wait_phase(host, "verify-preview-cancel", {"preview"})
    ack = host.cancel(
        {"operation_id": ref["operation_id"], "generation": ref["generation"]}
    )
    assert ack == {"accepted": True, "state": "cancelled"}
    assert _core.cancel_calls == [ref["operation_id"]]
    assert host.query({"request_id": "verify-preview-cancel"})["status"]["phase"] == "cancelled"
    with pytest.raises(mh.MaintenanceHostError) as stale:
        host.confirm_restore(
            request_id="confirm-after-preview-cancel",
            operation_id=ref["operation_id"],
            generation=ref["generation"],
            confirmation_token="preview-1",
        )
    assert stale.value.code == "PREVIEW_STALE"


def test_active_operation_probe_tracks_terminal_state(host):
    host, backup, _core = host
    target = host.register_target(Path("C:/synthetic/backup.kgmbackup"), "backup.kgmbackup")
    assert host.has_active_operation() is False
    backup.gate.clear()
    host.start_backup(
        request_id="req-active",
        target_id=target["target_id"],
        password=None,
        explicit_plaintext=True,
    )
    assert host.has_active_operation() is True
    backup.gate.set()
    wait_phase(host, "req-active", {"completed"})
    assert host.has_active_operation() is False


def test_unknown_query_and_foreign_generation_do_not_match(host):
    host, _backup, _core = host
    selection = _selection(host)
    ref = host.start_restore_verify(
        request_id="verify-4", selection_id=selection["selection_id"], password=None
    )
    wait_phase(host, "verify-4", {"preview"})
    assert host.query({"operation_id": ref["operation_id"], "generation": 999}) == {
        "state": "unknown"
    }
    assert host.query({"operation_id": "not-an-op", "generation": ref["generation"]}) == {
        "state": "unknown"
    }
