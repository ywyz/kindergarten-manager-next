"""R1 cleanup: startup timeout/failure must stop this run's service, and the
interactive error box must be shown only after the server has been released.
Initialisation failure must dispose the probe and stop any created service.
"""

import json
import time
from types import SimpleNamespace

import pytest

import d0_db
import d0_host_api
import d0_main


class _Probe:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class RecordingService:
    """Fake ServiceRun that records the stop/error ordering."""

    def __init__(self, *, start_result=True, error=None, delay=0.0):
        self.start_result = start_result
        self.error = error
        self._delay = delay
        self._alive = False
        self.stop_calls = 0
        self.events = []

    def start_and_wait(self):
        if self._delay:
            time.sleep(self._delay)
        self._alive = self.start_result
        return self.start_result

    def stop(self, timeout=10.0):
        self.stop_calls += 1
        self._alive = False
        self.events.append("stop")

    def alive(self):
        return self._alive


def _interactive_args():
    return SimpleNamespace(frontend=None, data=None)


def _selftest_args(out):
    return SimpleNamespace(
        selftest_phase="first",
        expect_content=None,
        expect_version=None,
        session_tag="t",
        out=str(out),
        frontend=None,
        data=None,
    )


# -- self-test startup timeout ----------------------------------------------


def test_selftest_delayed_startup_timeout_stops_service(monkeypatch, tmp_path):
    service = RecordingService(
        start_result=False, error="服务在 3s 内未就绪", delay=0.05
    )
    monkeypatch.setattr(
        d0_main, "build_runtime", lambda args: (service, object(), _Probe())
    )
    out = tmp_path / "out.json"
    assert d0_main.run_selftest(_selftest_args(out)) == 2
    assert service.stop_calls >= 1
    summary = json.loads(out.read_text(encoding="utf-8"))
    assert summary["ok"] is False
    assert summary["startup_error"] == "服务在 3s 内未就绪"


# -- interactive startup failure --------------------------------------------


def test_interactive_startup_failure_stops_before_error_box(monkeypatch):
    service = RecordingService(start_result=False, error="bind failed")
    monkeypatch.setattr(d0_main, "webview2_runtime_version", lambda: "1.0")
    monkeypatch.setattr(
        d0_main, "build_runtime", lambda args: (service, object(), _Probe())
    )
    shown = []

    def fake_show_error(title, message, *, box=None):
        # The server must already be released when the blocking box appears.
        shown.append((title, list(service.events)))

    monkeypatch.setattr(d0_main, "show_error", fake_show_error)
    assert d0_main.run_interactive(_interactive_args()) == 2
    # At the moment the blocking box was shown the service was already
    # stopped; the idempotent finally stop adds a harmless second call.
    assert service.events[0] == "stop"
    assert shown == [("D0 启动失败", ["stop"])]


def test_interactive_init_failure_shows_error(monkeypatch):
    def boom(args):
        raise RuntimeError("init boom")

    monkeypatch.setattr(d0_main, "webview2_runtime_version", lambda: "1.0")
    monkeypatch.setattr(d0_main, "build_runtime", boom)
    seen = []
    monkeypatch.setattr(
        d0_main, "show_error", lambda title, message, *, box=None: seen.append(title)
    )
    assert d0_main.run_interactive(_interactive_args()) == 2
    assert seen == ["D0 启动失败"]


def test_interactive_normal_exit_stops_service(monkeypatch):
    service = RecordingService(start_result=True)
    probe = _Probe()
    monkeypatch.setattr(d0_main, "webview2_runtime_version", lambda: "1.0")
    monkeypatch.setattr(
        d0_main, "build_runtime", lambda args: (service, object(), probe)
    )
    monkeypatch.setattr(d0_main, "open_window", lambda *a, **k: None)
    assert d0_main.run_interactive(_interactive_args()) == 0
    assert service.stop_calls >= 1
    assert service.alive() is False
    assert probe.closed is True


# -- build_runtime initialisation failure -----------------------------------


def test_build_runtime_init_failure_releases_service_and_probe(monkeypatch, tmp_path):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "d0.html").write_text("<html></html>", encoding="utf-8")
    data = tmp_path / "data"

    probes = []
    services = []

    class RecordingProbe:
        def __init__(self, data_dir):
            self.closed = False
            probes.append(self)

        def meta(self):
            return {}

        def close(self):
            self.closed = True

    class RecordingServiceRun:
        def __init__(self, app, port):
            self.port = port
            self.stopped = 0
            services.append(self)

        def stop(self, timeout=10.0):
            self.stopped += 1

    monkeypatch.setattr(d0_db, "SQLiteProbe", RecordingProbe)
    monkeypatch.setattr(d0_main, "ServiceRun", RecordingServiceRun)
    monkeypatch.setattr(d0_main, "webview2_runtime_version", lambda: "1.0")

    def raiser(*args, **kwargs):
        raise RuntimeError("host api init failed")

    monkeypatch.setattr(d0_host_api, "D0HostApi", raiser)

    args = SimpleNamespace(frontend=str(frontend), data=str(data))
    with pytest.raises(RuntimeError):
        d0_main.build_runtime(args)

    # The engine created before the failure is disposed and the service (if it
    # had been created) is stopped instead of being left to start later.
    assert probes and probes[0].closed is True
    assert services and services[0].stopped == 1
