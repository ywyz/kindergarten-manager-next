"""B2 host lifecycle bundles, reopen ordering and transport confirmation.

All services/windows/executors are explicit fakes.  The only real object is a
thread used to prove ``ServiceRun.stop_and_confirm`` never reports success for
a worker that is still alive.
"""

from __future__ import annotations

import threading
import time
import types

import pytest

import maintenance_lifecycle as ml


class FakeService:
    def __init__(self, *, start=True, confirmed=True, alive_after_stop=False):
        self.start_result = start
        self.confirmed = confirmed
        self.alive_after_stop = alive_after_stop
        self.started = 0
        self.stopped = 0

    def start_and_wait(self):
        self.started += 1
        return self.start_result

    def stop_and_confirm(self, timeout=10.0):
        self.stopped += 1
        return self.confirmed


class FakeHost:
    def __init__(self, name="host"):
        self.name = name
        self.retired = 0
        self.business_ready = False

    def retire(self):
        self.retired += 1

    def wait_business_ready(self, timeout):
        return self.business_ready


class FakeExecutor:
    def __init__(self):
        self.disposed = 0

    def dispose(self):
        self.disposed += 1
        return True


class FakeRuntime:
    def __init__(self):
        self.disposed = 0
        self.ai_executor = FakeExecutor()

    def dispose(self):
        self.disposed += 1


class FakeWindow:
    def __init__(self, name="window"):
        self.name = name
        self.destroyed = 0

    def destroy(self):
        self.destroyed += 1


def bundle(manager, **overrides):
    values = dict(
        generation=manager.next_generation(),
        service=FakeService(),
        host_api=FakeHost(),
        runtime=FakeRuntime(),
        window=FakeWindow(),
    )
    values.update(overrides)
    return ml.LifecycleBundle(**values)


def test_dispose_bundle_keeps_runtime_lock_when_stop_is_unconfirmed():
    manager = ml.LifecycleManager()
    item = bundle(manager, service=FakeService(confirmed=False))
    manager.install(item)
    assert manager.close_latest(timeout=0.01) is False
    assert item.host_api.retired == 1
    assert item.service.stopped == 1
    assert item.runtime.ai_executor.disposed == 0
    assert item.runtime.disposed == 0


def test_dispose_bundle_releases_only_after_confirmed_stop():
    manager = ml.LifecycleManager()
    item = bundle(manager)
    manager.install(item)
    assert manager.close_latest(timeout=1.0) is True
    assert item.runtime.ai_executor.disposed == 1
    assert item.runtime.disposed == 1


def test_unconfirmed_executor_keeps_runtime_lock():
    manager = ml.LifecycleManager()
    item = bundle(manager)
    item.runtime.ai_executor.dispose = lambda: False
    manager.install(item)
    assert manager.close_latest(timeout=1.0) is False
    assert item.runtime.disposed == 0


def test_legacy_stop_without_confirmation_is_not_success():
    class LegacyService:
        def __init__(self):
            self.stopped = 0

        def stop(self, timeout=10.0):
            self.stopped += 1

    manager = ml.LifecycleManager()
    legacy = LegacyService()
    item = ml.LifecycleBundle(generation=1, service=legacy, runtime=FakeRuntime())
    assert manager.stop_service(item, 0.01) is False
    assert legacy.stopped == 1


def test_reopen_sequence_retires_old_before_building_and_destroys_old_last():
    manager = ml.LifecycleManager()
    events: list[str] = []
    old = bundle(manager)
    old.host_api.retire = lambda: events.append("retire-old")
    old.window.destroy = lambda: events.append("destroy-old")

    new_bundle = ml.LifecycleBundle(
        generation=manager.next_generation(),
        service=FakeService(),
        host_api=FakeHost("new"),
        runtime=FakeRuntime(),
        window=FakeWindow("new"),
    )

    def build_bundle(_old):
        events.append("build-new")
        return new_bundle

    def create_window(_new):
        events.append("create-window")

    def wait_business(_new, _timeout):
        events.append("business-ready")
        return True

    sequencer = ml.ReopenSequencer(
        manager=manager,
        old_bundle=old,
        build_bundle=build_bundle,
        create_window=create_window,
        wait_business_ready=wait_business,
        timeout=1.0,
    )
    result = sequencer.run()
    assert result["state"] == "reopened"
    assert events == [
        "retire-old",
        "build-new",
        "create-window",
        "business-ready",
        "destroy-old",
    ]
    assert manager.current() is new_bundle


def test_reopen_sequence_failure_keeps_old_window_and_stops_new_transport():
    manager = ml.LifecycleManager()
    old = bundle(manager)
    new_bundle = ml.LifecycleBundle(
        generation=manager.next_generation(),
        service=FakeService(),
        host_api=FakeHost("new"),
        runtime=FakeRuntime(),
        window=FakeWindow("new"),
    )
    sequencer = ml.ReopenSequencer(
        manager=manager,
        old_bundle=old,
        build_bundle=lambda _old: new_bundle,
        create_window=lambda _new: None,
        wait_business_ready=lambda _new, _timeout: False,
        timeout=0.01,
    )
    result = sequencer.run()
    assert result == {"state": "reopen_failed", "code": "REOPEN_PAGE_TIMEOUT"}
    assert old.window.destroyed == 0
    assert new_bundle.window.destroyed == 1
    assert new_bundle.service.stopped == 1
    assert new_bundle.host_api.retired == 1
    # The runtime lock is retained for the old page/error state.
    assert new_bundle.runtime.disposed == 0
    # Shutdown still closes the newest bundle, never the old server.
    assert manager.current() is new_bundle


def test_failed_start_keeps_new_bundle_and_shared_runtime_lock():
    manager = ml.LifecycleManager()
    old = bundle(manager, service=FakeService(start=True, confirmed=True))
    new = ml.LifecycleBundle(
        generation=manager.next_generation(),
        service=FakeService(start=False, confirmed=False),
        host_api=FakeHost("new"),
        runtime=old.runtime,
        window=FakeWindow("new"),
    )
    manager.install(old)
    sequencer = ml.ReopenSequencer(
        manager=manager,
        old_bundle=old,
        build_bundle=lambda _old: new,
        create_window=lambda _new: None,
        wait_business_ready=lambda _new, _timeout: True,
        timeout=0.01,
    )
    result = sequencer.run()
    assert result["state"] == "reopen_failed"
    assert result["code"] == "REOPEN_SERVICE_FAILED"
    # The failed new bundle is still the latest owner; closing it must not
    # release the shared runtime while its service exit is unconfirmed.
    assert manager.current() is new
    assert manager.close_latest(timeout=0.01) is False
    assert old.runtime.disposed == 0
    assert new.service.stopped >= 1


def test_reopen_sequence_start_failure_keeps_old_window_and_latest_new_owner():
    manager = ml.LifecycleManager()
    old = bundle(manager)
    manager.install(old)
    new_bundle = ml.LifecycleBundle(
        generation=manager.next_generation(),
        service=FakeService(start=False, confirmed=True),
        host_api=FakeHost("new"),
        runtime=old.runtime,
        window=FakeWindow("new"),
    )
    sequencer = ml.ReopenSequencer(
        manager=manager,
        old_bundle=old,
        build_bundle=lambda _old: new_bundle,
        create_window=lambda _new: None,
        wait_business_ready=lambda _new, _timeout: True,
        timeout=0.01,
    )
    result = sequencer.run()
    assert result["state"] == "reopen_failed"
    assert result["code"] == "REOPEN_SERVICE_FAILED"
    assert manager.current() is new_bundle
    assert old.window.destroyed == 0
    assert old.host_api.retired == 1


def test_wait_host_idle_never_waits_on_panel_busy_and_honours_cancel():
    manager = ml.LifecycleManager()
    item = bundle(manager)
    manager.install(item)
    probes = {"count": 0}

    def busy(_bundle):
        probes["count"] += 1
        return probes["count"] < 3

    hooks = ml.HostMaintenanceHooks(
        manager=manager,
        bundle_getter=manager.current,
        busy_probe=busy,
        poll_seconds=0.001,
        timeout=1.0,
    )
    assert hooks.wait_host_idle() is True
    assert probes["count"] == 3

    cancel = threading.Event()
    cancel.set()
    assert hooks.wait_host_idle(cancel) is False

    hooks_timeout = ml.HostMaintenanceHooks(
        manager=manager,
        bundle_getter=manager.current,
        busy_probe=lambda _bundle: True,
        poll_seconds=0.001,
        timeout=0.02,
    )
    assert hooks_timeout.wait_host_idle() is False


def test_stop_transport_marks_switch_only_after_confirmed_death():
    manager = ml.LifecycleManager()
    item = bundle(manager, service=FakeService(confirmed=False))
    manager.install(item)
    switches = []
    hooks = ml.HostMaintenanceHooks(
        manager=manager,
        bundle_getter=manager.current,
        busy_probe=lambda _bundle: False,
        timeout=0.01,
        on_switch=lambda: switches.append("switch"),
    )
    assert hooks.stop_transport() is False
    assert switches == []
    item.service.confirmed = True
    assert hooks.stop_transport() is True
    assert switches == ["switch"]


def test_stop_transport_uses_confirmed_service_stop():
    manager = ml.LifecycleManager()
    item = bundle(manager, service=FakeService(confirmed=False))
    manager.install(item)
    hooks = ml.HostMaintenanceHooks(
        manager=manager,
        bundle_getter=manager.current,
        busy_probe=lambda _bundle: False,
        timeout=0.01,
    )
    assert hooks.stop_transport() is False
    item.service.confirmed = True
    assert hooks.stop_transport() is True


def test_service_run_stop_and_confirm_reports_live_thread_as_failure():
    from d0_main import ServiceRun

    service = ServiceRun.__new__(ServiceRun)
    service.server = types.SimpleNamespace(should_exit=False)
    stop_flag = threading.Event()

    def worker():
        while not stop_flag.is_set():
            time.sleep(0.005)

    service.thread = threading.Thread(target=worker, daemon=True)
    service.thread.start()
    try:
        assert service.stop_and_confirm(timeout=0.02) is False
        assert service.thread.is_alive()
    finally:
        stop_flag.set()
        service.thread.join(2.0)
    assert service.stop_and_confirm(timeout=0.1) is True


def test_service_run_stop_and_confirm_accepts_dead_thread():
    from d0_main import ServiceRun

    service = ServiceRun.__new__(ServiceRun)
    service.server = types.SimpleNamespace(should_exit=False)
    service.thread = threading.Thread(target=lambda: None)
    service.thread.start()
    service.thread.join(1.0)
    assert service.stop_and_confirm(timeout=0.01) is True
