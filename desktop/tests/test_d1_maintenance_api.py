"""D1 host API maintenance seams: window binding, retirement, opaque ids.

The maintenance coordinator is a recording fake here; the real coordinator is
covered by ``test_maintenance_host.py``.  No WebView2 window is created.
"""

from __future__ import annotations

import types
from pathlib import Path

import pytest

import d1_host_api
import maintenance_host as mh


class FakeWindow:
    def __init__(self, name: str, dialog_result=None):
        self.name = name
        self.dialog_result = dialog_result
        self.dialog_calls: list[dict] = []

    def create_file_dialog(self, *args, **kwargs):
        self.dialog_calls.append({"args": args, "kwargs": kwargs})
        return self.dialog_result


class FakeMaintenance:
    def __init__(self):
        self.retired = 0
        self.active = False
        self.targets: list[tuple[Path, str]] = []
        self.selections: list[tuple[Path, str, bool]] = []
        self.started: list[dict] = []
        self.canceled: list[dict] = []

    def retire(self):
        self.retired += 1

    def has_active_operation(self):
        return self.active

    def startup_state(self):
        return {"state": "ready"}

    def register_target(self, path, display_name):
        self.targets.append((Path(path), display_name))
        return {"target_id": "target-opaque", "display_name": display_name}

    def register_selection(self, path, display_name, encrypted):
        self.selections.append((Path(path), display_name, bool(encrypted)))
        return {
            "selection_id": "selection-opaque",
            "display_name": display_name,
            "encrypted": bool(encrypted),
        }

    def start_backup(self, **kwargs):
        self.started.append(kwargs)
        return {"request_id": kwargs["request_id"], "operation_id": "op-1", "generation": 1}

    def start_restore_verify(self, **kwargs):
        self.started.append(kwargs)
        return {"request_id": kwargs["request_id"], "operation_id": "op-2", "generation": 2}

    def confirm_restore(self, **kwargs):
        self.started.append(kwargs)
        return {"request_id": kwargs["request_id"], "operation_id": "op-2", "generation": 2}

    def query(self, payload):
        return {"state": "found", "status": {"phase": "creating", "request_id": "req"}}

    def cancel(self, payload):
        self.canceled.append(payload)
        return {"accepted": True, "state": "cancelled"}


def make_host(window, maintenance=None, generation=1):
    host = d1_host_api.D1HostApi(
        launch_token="launch-token",
        maintenance_host=maintenance,
        document_generation=generation,
    )
    host._bind_window(window)
    return host


def bind_page(host) -> str:
    bootstrap = host.get_bootstrap()
    ticket = bootstrap["page_ticket"]
    ready = host.page_ready(
        {"bridge_protocol": d1_host_api.BRIDGE_PROTOCOL, "page_ticket": ticket}
    )
    assert ready["accepted"] is True
    return ticket


def test_each_host_uses_only_its_bound_window():
    window_a = FakeWindow("a", dialog_result="C:/synthetic/a.kgmbackup")
    window_b = FakeWindow("b", dialog_result="C:/synthetic/b.kgmbackup")
    maintenance = FakeMaintenance()
    host_a = make_host(window_a, maintenance)
    host_b = make_host(window_b, maintenance, generation=2)
    bind_page(host_a)
    bind_page(host_b)

    result_a = host_a.choose_backup_target()
    result_b = host_b.choose_backup_target()
    assert result_a["ok"] is True
    assert result_b["ok"] is True
    assert len(window_a.dialog_calls) == 1
    assert len(window_b.dialog_calls) == 1
    assert maintenance.targets[0][0] == Path("C:/synthetic/a.kgmbackup")
    assert maintenance.targets[1][0] == Path("C:/synthetic/b.kgmbackup")


def test_unbound_host_never_guesses_webview_windows(monkeypatch):
    monkeypatch.setattr(
        d1_host_api.webview,
        "windows",
        [FakeWindow("someone-else", dialog_result="C:/synthetic/x.kgmbackup")],
        raising=False,
    )
    host = d1_host_api.D1HostApi(launch_token="t", maintenance_host=FakeMaintenance())
    bind_page(host)
    result = host.choose_backup_target()
    assert result["error"]["code"] == "DIALOG_FAILED"
    assert "C:/synthetic" not in str(result)


def test_retirement_blocks_new_bootstrap_and_side_effects_but_keeps_query():
    maintenance = FakeMaintenance()
    window = FakeWindow("a", dialog_result="C:/synthetic/a.kgmbackup")
    host = make_host(window, maintenance)
    bind_page(host)
    started = host.start_backup(
        {"request_id": "req-1", "target_id": "t", "password": "pw", "explicit_plaintext": False}
    )
    assert started["operation_id"] == "op-1"

    host._retire()
    assert maintenance.retired == 1
    bootstrap = host.get_bootstrap()
    assert bootstrap["retired"] is True
    assert "launch_token" not in bootstrap
    assert host.page_ready({"bridge_protocol": d1_host_api.BRIDGE_PROTOCOL})["accepted"] is False
    assert host.start_backup({"request_id": "req-2"})["error"]["code"] == "HOST_RETIRED"
    assert host.choose_backup_target()["error"]["code"] == "HOST_RETIRED"
    # Read-only status of the old operation still answers.
    assert host.query_maintenance({"request_id": "req-1"})["state"] == "found"
    assert host.cancel_maintenance({"request_id": "req-1"}) == {
        "accepted": False,
        "state": "unknown",
    }
    assert maintenance.canceled == []


def test_dialog_cancel_is_honest_and_not_an_error():
    maintenance = FakeMaintenance()
    window = FakeWindow("a", dialog_result=None)
    host = make_host(window, maintenance)
    bind_page(host)
    assert host.choose_backup_target() == {"ok": False, "canceled": True}
    assert host.choose_restore_source() == {"ok": False, "canceled": True}
    assert maintenance.targets == []
    assert maintenance.selections == []


def test_restore_selection_returns_opaque_ids_and_encryption_hint(tmp_path: Path):
    plain = tmp_path / "plain.kgmbackup"
    # magic (8) + format version (2) + mode=plaintext (1)
    plain.write_bytes(b"KGMBKP1\x00" + b"\x01\x00" + b"\x01" + b"payload")
    encrypted = tmp_path / "encrypted.kgmbackup"
    encrypted.write_bytes(b"not-a-plain-header")

    maintenance = FakeMaintenance()
    host = make_host(FakeWindow("a", dialog_result=str(plain)), maintenance)
    bind_page(host)
    plain_result = host.choose_restore_source()
    assert plain_result == {
        "ok": True,
        "selection": {
            "selection_id": "selection-opaque",
            "display_name": "plain.kgmbackup",
            "encrypted": False,
        },
    }
    assert str(tmp_path) not in str(plain_result)
    assert maintenance.selections[-1][2] is False

    host2 = make_host(FakeWindow("b", dialog_result=str(encrypted)), maintenance)
    bind_page(host2)
    encrypted_result = host2.choose_restore_source()
    assert encrypted_result["selection"]["encrypted"] is True
    assert str(tmp_path) not in str(encrypted_result)


class _ClosingHook:
    def __init__(self):
        self.callbacks = []

    def __iadd__(self, callback):
        self.callbacks.append(callback)
        return self


class _CloseWindow:
    def __init__(self):
        self.destroyed = 0
        self.events = types.SimpleNamespace(closing=_ClosingHook())

    def destroy(self):
        self.destroyed += 1


class _StoppedExecutor:
    def active_snapshot(self):
        return {"live": 0, "in_flight": False}

    def freeze(self):
        pass

    def unfreeze(self):
        pass

    def notify(self):
        pass

    def stop_and_drain(self, deadline):
        return True

    def dispose(self):
        return True


class _ActiveExecutor:
    def active_snapshot(self):
        return {"attempt_in_flight": True, "unconfirmed": False, "pending_persist": False}

    def freeze(self):
        pass

    def unfreeze(self):
        pass

    def notify(self):
        pass

    def stop_and_drain(self, deadline):
        raise AssertionError("cannot stop without an explicit user task choice")


class _RunningRuntime:
    prepared = True

    def __init__(self):
        self.ai_executor = _ActiveExecutor()

    def session(self):
        raise AssertionError("inflight snapshot must not need DB query")


class _ClosedRuntime:
    prepared = False

    def __init__(self):
        self.ai_executor = _StoppedExecutor()

    def session(self):
        raise RuntimeError("engine closed during unresolved restore")


def test_recovery_required_closed_engine_window_can_close_natively():
    import d1_main

    window = _CloseWindow()
    host = d1_host_api.D1HostApi(
        launch_token="synthetic", window_getter=lambda: window
    )
    host._page_ready = True
    host._bind_maintenance(
        types.SimpleNamespace(
            has_active_operation=lambda: False, _recovery_required=True
        )
    )
    host._block_native_io()
    d1_main._install_close_handlers(window, host, _ClosedRuntime())
    try:
        allow = window.events.closing.callbacks[0]()
        assert allow is True
        assert window.destroyed == 0
    finally:
        host._close_coordinator._cancel_timer()


def test_recovery_required_with_active_maintenance_still_refuses_close():
    import d1_main

    window = _CloseWindow()
    host = d1_host_api.D1HostApi(
        launch_token="synthetic", window_getter=lambda: window
    )
    host._bind_maintenance(
        types.SimpleNamespace(
            has_active_operation=lambda: True, _recovery_required=True
        )
    )
    d1_main._install_close_handlers(window, host, _ClosedRuntime())
    try:
        allow = window.events.closing.callbacks[0]()
        assert allow is False
        assert window.destroyed == 0
    finally:
        host._close_coordinator._cancel_timer()


def test_recovery_required_open_engine_with_real_inflight_keeps_close_guard():
    import d1_main

    window = _CloseWindow()
    host = d1_host_api.D1HostApi(
        launch_token="synthetic", window_getter=lambda: window
    )
    host._page_ready = True
    host._bind_maintenance(
        types.SimpleNamespace(
            has_active_operation=lambda: False, _recovery_required=True
        )
    )
    # Transport was not confirmed stopped and native IO was not blocked.
    d1_main._install_close_handlers(window, host, _RunningRuntime())
    try:
        allow = window.events.closing.callbacks[0]()
        assert allow is False
        assert window.destroyed == 0
    finally:
        host._close_coordinator._cancel_timer()


def test_closed_engine_without_recovery_required_keeps_normal_ai_close_guard():
    import d1_main

    window = _CloseWindow()
    host = d1_host_api.D1HostApi(
        launch_token="synthetic", window_getter=lambda: window
    )
    host._bind_maintenance(
        types.SimpleNamespace(
            has_active_operation=lambda: False, _recovery_required=False
        )
    )
    d1_main._install_close_handlers(window, host, _ClosedRuntime())
    try:
        allow = window.events.closing.callbacks[0]()
        assert allow is False
        assert window.destroyed == 0
    finally:
        host._close_coordinator._cancel_timer()


def test_retired_terminal_window_can_close_natively():
    import d1_main

    window = _CloseWindow()
    host = d1_host_api.D1HostApi(
        launch_token="synthetic", window_getter=lambda: window
    )
    host._bind_maintenance(types.SimpleNamespace(has_active_operation=lambda: False))
    d1_main._install_close_handlers(window, host, None)
    host._retire()
    try:
        allow = window.events.closing.callbacks[0]()
        assert allow is True
        assert window.destroyed == 0  # native close is allowed; no forced destroy
    finally:
        host._close_coordinator._cancel_timer()


def test_retired_window_still_refuses_close_during_active_maintenance():
    import d1_main

    window = _CloseWindow()
    host = d1_host_api.D1HostApi(
        launch_token="synthetic", window_getter=lambda: window
    )
    host._bind_maintenance(types.SimpleNamespace(has_active_operation=lambda: True))
    d1_main._install_close_handlers(window, host, None)
    host._retire()
    try:
        allow = window.events.closing.callbacks[0]()
        assert allow is False
        assert window.destroyed == 0
    finally:
        host._close_coordinator._cancel_timer()


def test_bootstrap_carries_display_only_restore_notice():
    notice = "恢复前保护副本：D:\\保护\\副本。自动保留，不会自动删除。"
    host = d1_host_api.D1HostApi(
        launch_token="token",
        maintenance_notice=notice,
    )
    bootstrap = host.get_bootstrap()
    assert bootstrap["maintenance_notice"] == notice
    assert "launch_token" in bootstrap
    # A host without a restore notice does not invent one.
    plain = d1_host_api.D1HostApi(launch_token="token")
    assert "maintenance_notice" not in plain.get_bootstrap()


def test_business_ready_requires_page_ready_and_exact_ticket():
    maintenance = FakeMaintenance()
    host = make_host(FakeWindow("a"), maintenance, generation=7)
    bootstrap = host.get_bootstrap()
    assert bootstrap["document_generation"] == 7
    ticket = bootstrap["page_ticket"]
    # Before page_ready the business ack is refused.
    assert host.page_business_ready({"page_ticket": ticket})["accepted"] is False
    host.page_ready({"bridge_protocol": d1_host_api.BRIDGE_PROTOCOL, "page_ticket": ticket})
    assert host.page_business_ready({"page_ticket": "old-ticket"})["accepted"] is False
    ack = host.page_business_ready({"page_ticket": ticket})
    assert ack == {"accepted": True, "document_generation": 7}
    assert host._wait_business_ready(0.1) is True
    # A fresh bootstrap retires the old ticket and resets business readiness:
    # the old page's ack must not satisfy the new page's reopen waiter.
    host.get_bootstrap()
    assert host._wait_business_ready(0.01) is False
    assert host.page_business_ready({"page_ticket": ticket})["accepted"] is False


def test_retire_destroy_flag_is_consumed_exactly_once():
    host = make_host(FakeWindow("a"), FakeMaintenance())
    assert host._consume_retire_destroy() is False
    host._request_retire_destroy()
    assert host._consume_retire_destroy() is True
    assert host._consume_retire_destroy() is False


def test_retire_after_native_dialog_does_not_commit_a_new_write(tmp_path, monkeypatch):
    """A blocking dialog may return after the host generation was retired."""
    writes: list[tuple] = []

    class RetiringWindow:
        def create_file_dialog(self, *args, **kwargs):
            host._retire()
            return str(tmp_path / "out.docx")

    host = make_host(RetiringWindow(), FakeMaintenance())
    bind_page(host)
    host._decode_docx = lambda payload: (b"docx", None)
    monkeypatch.setattr(
        d1_host_api,
        "write_docx_atomic",
        lambda *args, **kwargs: writes.append(args) or {"status": "saved"},
    )
    result = host.save_docx(
        {"request_id": "req-save", "filename": "x.docx", "payload_base64": "x"}
    )
    assert result["status"] == "failed"
    assert result["code"] == "HOST_SWITCHING"
    assert writes == []


def test_switch_guard_refuses_new_native_io_before_retirement():
    host = make_host(FakeWindow("a", dialog_result="C:/synthetic/out.docx"), FakeMaintenance())
    bind_page(host)
    host._block_native_io()
    result = host.save_docx(
        {"request_id": "req-switch", "filename": "x.docx", "payload_base64": "x"}
    )
    assert result["code"] == "HOST_SWITCHING"
    export = host.save_observation_export({"export_id": "e", "filename": "x.docx"})
    assert export["code"] == "HOST_SWITCHING"
    assert host.choose_backup_target()["error"]["code"] == "HOST_SWITCHING"
    assert host.start_backup({"request_id": "r"})["error"]["code"] == "HOST_SWITCHING"



def test_close_probe_refuses_destroy_while_maintenance_is_active():
    maintenance = FakeMaintenance()
    host = make_host(FakeWindow("a"), maintenance)
    assert host._maintenance_busy_probe() is False
    maintenance.active = True
    assert host._maintenance_busy_probe() is True
    maintenance.active = False
    assert host._maintenance_busy_probe() is False


def test_maintenance_guard_requires_page_ready():
    maintenance = FakeMaintenance()
    host = make_host(FakeWindow("a", dialog_result="C:/synthetic/a.kgmbackup"), maintenance)
    assert host.choose_backup_target()["error"]["code"] == "BRIDGE_NOT_READY"
    assert maintenance.targets == []
