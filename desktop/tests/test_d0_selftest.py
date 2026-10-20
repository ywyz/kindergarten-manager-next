"""R10: the self-test must never report success on failure/timeout/leaks."""

import json
import sys
from types import ModuleType, SimpleNamespace

import d0_driver
import d0_main
from d0_driver import combine_ok


class _FakeWindow:
    def __init__(self):
        self.destroyed = False

    def destroy(self):
        self.destroyed = True


class _BadWindow:
    def destroy(self):
        raise RuntimeError("window refused to close")


def _fake_webview(monkeypatch, window):
    module = ModuleType("webview")
    module.windows = [window]
    monkeypatch.setitem(sys.modules, "webview", module)
    return module


class _FakeService:
    def __init__(self, alive=False):
        self._alive = alive
        self.error = None
        self.port = 12345

    def start_and_wait(self):
        return True

    def stop(self):
        pass

    def alive(self):
        return self._alive


class _FakeProbe:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class _FakeServiceFail(_FakeService):
    def start_and_wait(self):
        self.error = "bind failed"
        return False


def _args(out):
    return SimpleNamespace(
        selftest_phase="first",
        expect_content=None,
        expect_version=None,
        session_tag="t",
        out=str(out),
        frontend=None,
        data=None,
    )


def test_combine_ok_requires_every_check():
    assert combine_ok({"a": True, "b": True}) is True
    assert combine_ok({"a": True, "b": False}) is False
    assert combine_ok({}) is False


def test_cleanup_leak_is_failure():
    assert combine_ok({"server_stopped_clean": False, "page_ready": True}) is False


def test_driver_never_running_is_failure(monkeypatch, tmp_path):
    probe = _FakeProbe()
    monkeypatch.setattr(
        d0_main, "build_runtime", lambda args: (_FakeService(), object(), probe)
    )
    # open_window never invokes the driver callback (window failed before it).
    monkeypatch.setattr(d0_main, "open_window", lambda *a, **k: None)
    out = tmp_path / "out.json"
    assert d0_main.run_selftest(_args(out)) == 3
    summary = json.loads(out.read_text(encoding="utf-8"))
    assert summary["ok"] is False
    assert probe.closed is True


def test_window_error_is_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(
        d0_main, "build_runtime", lambda args: (_FakeService(), object(), _FakeProbe())
    )

    def boom(service, host_api, *, driver=None):
        raise RuntimeError("window boom")

    monkeypatch.setattr(d0_main, "open_window", boom)
    out = tmp_path / "out.json"
    assert d0_main.run_selftest(_args(out)) == 3
    summary = json.loads(out.read_text(encoding="utf-8"))
    assert summary["ok"] is False
    assert "window_error" in summary


def test_cleanup_leak_makes_run_fail(monkeypatch, tmp_path):
    monkeypatch.setattr(
        d0_main,
        "build_runtime",
        lambda args: (_FakeService(alive=True), object(), _FakeProbe()),
    )
    monkeypatch.setattr(
        d0_driver,
        "drive_window",
        lambda *a, **k: {"checks": {"page_ready": True, "docx_saved_via_page": True}},
    )
    monkeypatch.setattr(
        d0_main, "open_window", lambda service, host_api, *, driver=None: driver()
    )
    out = tmp_path / "out.json"
    assert d0_main.run_selftest(_args(out)) == 3
    summary = json.loads(out.read_text(encoding="utf-8"))
    assert summary["checks"]["server_stopped_clean"] is False
    assert summary["ok"] is False


def test_all_checks_true_returns_success(monkeypatch, tmp_path):
    monkeypatch.setattr(
        d0_main, "build_runtime", lambda args: (_FakeService(), object(), _FakeProbe())
    )
    monkeypatch.setattr(
        d0_driver,
        "drive_window",
        lambda *a, **k: {"checks": {"page_ready": True, "docx_saved_via_page": True}},
    )
    monkeypatch.setattr(
        d0_main, "open_window", lambda service, host_api, *, driver=None: driver()
    )
    out = tmp_path / "out.json"
    assert d0_main.run_selftest(_args(out)) == 0
    summary = json.loads(out.read_text(encoding="utf-8"))
    assert summary["ok"] is True


def test_startup_exception_writes_failure_summary(monkeypatch, tmp_path):
    def boom(args):
        raise RuntimeError("init failed")

    monkeypatch.setattr(d0_main, "build_runtime", boom)
    out = tmp_path / "out.json"
    assert d0_main.run_selftest(_args(out)) == 2
    summary = json.loads(out.read_text(encoding="utf-8"))
    assert summary["ok"] is False
    assert "startup_error" in summary


def test_service_start_failure_writes_failure_summary(monkeypatch, tmp_path):
    monkeypatch.setattr(
        d0_main,
        "build_runtime",
        lambda args: (_FakeServiceFail(), object(), _FakeProbe()),
    )
    out = tmp_path / "out.json"
    assert d0_main.run_selftest(_args(out)) == 2
    summary = json.loads(out.read_text(encoding="utf-8"))
    assert summary["ok"] is False
    assert summary["startup_error"] == "bind failed"


# -- R10 abnormal end: no human needed to finish a failed self-test ---------


def test_driver_exception_closes_window_without_human(monkeypatch, tmp_path):
    window = _FakeWindow()
    _fake_webview(monkeypatch, window)
    monkeypatch.setattr(
        d0_main, "build_runtime", lambda args: (_FakeService(), object(), _FakeProbe())
    )

    def boom(*args, **kwargs):
        raise RuntimeError("driver boom")

    monkeypatch.setattr(d0_driver, "drive_window", boom)
    # open_window would normally block until the window closes; the real
    # pywebview runs the driver in a background thread, so this equivalent
    # invokes it and then returns.
    monkeypatch.setattr(
        d0_main, "open_window", lambda service, host_api, *, driver=None: driver()
    )
    out = tmp_path / "out.json"
    assert d0_main.run_selftest(_args(out)) == 3
    summary = json.loads(out.read_text(encoding="utf-8"))
    assert summary["ok"] is False
    assert "driver_error" in summary
    # The window was closed by the driver's own completion path, no human.
    assert window.destroyed is True
    assert summary["checks"]["selftest_window_closed"] is True
    assert summary["checks"]["no_driver_error"] is False


def test_successful_selftest_closes_window(monkeypatch, tmp_path):
    window = _FakeWindow()
    _fake_webview(monkeypatch, window)
    monkeypatch.setattr(
        d0_main, "build_runtime", lambda args: (_FakeService(), object(), _FakeProbe())
    )
    monkeypatch.setattr(
        d0_driver,
        "drive_window",
        lambda *a, **k: {"checks": {"page_ready": True, "docx_saved_via_page": True}},
    )
    monkeypatch.setattr(
        d0_main, "open_window", lambda service, host_api, *, driver=None: driver()
    )
    out = tmp_path / "out.json"
    assert d0_main.run_selftest(_args(out)) == 0
    assert window.destroyed is True


def test_window_close_failure_is_explicit_failure(monkeypatch, tmp_path):
    _fake_webview(monkeypatch, _BadWindow())
    monkeypatch.setattr(
        d0_main, "build_runtime", lambda args: (_FakeService(), object(), _FakeProbe())
    )
    monkeypatch.setattr(
        d0_driver,
        "drive_window",
        lambda *a, **k: {"checks": {"page_ready": True, "docx_saved_via_page": True}},
    )
    monkeypatch.setattr(
        d0_main, "open_window", lambda service, host_api, *, driver=None: driver()
    )
    out = tmp_path / "out.json"
    assert d0_main.run_selftest(_args(out)) == 3
    summary = json.loads(out.read_text(encoding="utf-8"))
    assert summary["ok"] is False
    assert summary["checks"]["selftest_window_closed"] is False
    assert summary["checks"]["window_closed_without_error"] is False
    assert "window_close_error" in summary
