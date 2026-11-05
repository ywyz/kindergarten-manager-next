"""Pure core tests for the manual renderer-recovery coordinator.

B's native adapter is injected as a fake here.  No WebView2, WinForms, JS, HTTP
or database is created.
"""

from __future__ import annotations

import threading

import renderer_recovery as rr


class FakeForm:
    IsDisposed = False


class FakeWindow:
    def __init__(self):
        self.native = FakeForm()


class FakeExecutor:
    def __init__(self):
        self.freeze_owners: set[str] = set()
        self.calls: list[tuple] = []
        self.snapshot = {
            "attempt_in_flight": False,
            "pending_persist": 0,
            "unconfirmed": False,
            "persist_blocked": False,
        }
        self.snapshot_idle = True
        self.stop_ok = True

    def freeze(self, owner="close"):
        self.freeze_owners.add(owner)
        self.calls.append(("freeze", owner))

    def unfreeze(self, owner="close"):
        self.freeze_owners.discard(owner)
        self.calls.append(("unfreeze", owner))

    def active_snapshot(self):
        return dict(self.snapshot)

    def is_snapshot_idle(self):
        return self.snapshot_idle

    def stop_if_idle(self, *, owner, timeout=5.0):
        self.calls.append(("stop_if_idle", owner, timeout))
        if owner not in self.freeze_owners:
            return False
        return self.stop_ok


class FakeWeekly:
    def __init__(self):
        self.owners: set[str] = set()
        self.calls: list[tuple] = []
        self.idle = True

    def pause(self, *, owner):
        self.owners.add(owner)
        self.calls.append(("pause", owner))

    def resume(self, *, owner):
        self.owners.discard(owner)
        self.calls.append(("resume", owner))

    def wait_idle(self, *, timeout=60.0):
        self.calls.append(("wait_idle", timeout))
        return self.idle


class FakeHost:
    def __init__(self):
        self._retired = False
        self._native_io_blocked = False
        self._save = False
        self._page_busy = False
        self._update = False
        self._maintenance = False
        self._recovery_required = False
        self._weekly_export_manager = FakeWeekly()
        self._close_coordinator = None
        self._install_coordinator = None
        self.calls: list[str] = []

    def _block_native_io(self):
        self._native_io_blocked = True
        self.calls.append("block_native_io")

    def _save_in_progress(self):
        return self._save

    def _page_busy_probe(self):
        return self._page_busy

    def _update_busy_probe(self):
        return self._update

    def _maintenance_busy_probe(self):
        return self._maintenance

    def _recovery_required_probe(self):
        return self._recovery_required


class FakeService:
    def __init__(self):
        self.weekly_export_manager = None


class FakeBundle:
    def __init__(self, generation=1, runtime=None):
        self.generation = generation
        self.runtime = runtime
        self.window = FakeWindow()
        self.service = FakeService()
        self.executor = FakeExecutor()


class FakeLifecycle:
    def __init__(self, bundle, host):
        self.bundle = bundle
        self.host = host
        self.calls: list[str] = []
        self.stop_ok = True

    def is_current(self, bundle):
        return bundle is self.bundle

    def current(self):
        return self.bundle

    def install(self, bundle):
        self.bundle = bundle

    def stop_service(self, bundle, timeout=10.0):
        self.calls.append("stop_service")
        return self.stop_ok

    def retire_host(self, bundle):
        self.calls.append("retire_host")
        self.host._retired = True


class FakeLease:
    def __init__(self, barrier):
        self.barrier = barrier
        self.released = 0

    def release(self):
        self.released += 1
        self.barrier.calls.append("release_lease")


class FakeBarrier:
    def __init__(self):
        self.calls: list[str] = []
        self.active_counts = (0, 0)
        self.begin_fails = False
        self.acquire_fails = False
        self.validate_fails = False
        self.lease = FakeLease(self)

    def begin_intent(self, owner):
        self.calls.append(("begin_intent", owner))
        if self.begin_fails:
            raise RuntimeError("busy")
        return self.lease

    def acquire_exclusive(self, lease):
        self.calls.append("acquire_exclusive")
        if self.acquire_fails:
            raise RuntimeError("busy")

    def validate_exclusive_lease(self, lease):
        self.calls.append("validate_exclusive_lease")
        if self.validate_fails:
            raise RuntimeError("busy")


class FakeRuntime:
    def __init__(self, host):
        self.data_dir = "C:/synthetic"
        self.prepared = True
        self._owns_lock = True
        self.ai_executor = None
        self.calls: list[str] = []
        self.close_fails = False
        self.reopen_fails = False

    def close_engine_keep_lock(self):
        self.calls.append("close_engine")
        if self.close_fails:
            raise RuntimeError("close failed")

    def reopen_after_restore(self):
        self.calls.append("reopen_engine")
        if self.reopen_fails:
            raise RuntimeError("reopen failed")


class FakeAdapter:
    def __init__(self, prompt_results=None):
        self.prompt_results = list(prompt_results or [False])
        self.prompts = 0
        self.blocked: list[str] = []
        self.watcher = None
        self.watcher_callback = None
        self.watcher_close = 0

    def install_renderer_watcher(self, window, on_failure, *, log=None):
        self.watcher_callback = on_failure
        self.watcher = FakeWatcher(self)
        return self.watcher

    def prompt_reopen(self, window):
        self.prompts += 1
        if len(self.prompt_results) > 1:
            return self.prompt_results.pop(0)
        return self.prompt_results[0] if self.prompt_results else False

    def notify_reopen_blocked(self, window, code):
        self.blocked.append(code)


class FakeWatcher:
    def __init__(self, adapter):
        self.adapter = adapter

    def close(self):
        self.adapter.watcher_close += 1


def make_coordinator(
    *,
    prompt_results=None,
    host=None,
    lifecycle=None,
    adapter=None,
    close_revoker=None,
    close_revocation_finisher=None,
):
    bundle = FakeBundle()
    host = host or FakeHost()
    lifecycle = lifecycle or FakeLifecycle(bundle, host)
    runtime = FakeRuntime(host)
    bundle.runtime = runtime
    barrier = FakeBarrier()
    adapter = adapter or FakeAdapter(prompt_results)
    order: list[str] = []

    def reopen_sequence():
        order.append("reopen_sequence")
        return {"state": "reopened", "generation": 2}

    coordinator = rr.RendererRecoveryCoordinator(
        window=bundle.window,
        host_api=host,
        lifecycle=lifecycle,
        bundle=bundle,
        runtime=runtime,
        reopen_sequence=reopen_sequence,
        adapter=adapter,
        log=lambda _message: None,
        invalidate_authorizations=lambda: order.append("invalidate"),
        barrier_getter=lambda _root: barrier,
        close_revoker=close_revoker,
        close_revocation_finisher=close_revocation_finisher,
    )
    coordinator.install()
    return coordinator, bundle, host, lifecycle, runtime, barrier, adapter, order


def fault(coordinator):
    coordinator._on_native_failure("RenderProcessExited")
    assert coordinator._worker_done.wait(5), "recovery worker did not finish"
    worker = coordinator._worker
    if worker is not None:
        worker.join(5)
        assert not worker.is_alive()


def test_prompt_false_freezes_owner_and_keeps_window():
    coordinator, bundle, host, _lifecycle, runtime, barrier, adapter, order = (
        make_coordinator(prompt_results=[False])
    )
    fault(coordinator)
    assert coordinator.state == coordinator.KEPT
    assert coordinator.expected_close is False
    assert bundle.executor.freeze_owners == {coordinator.freeze_owner}
    assert host._weekly_export_manager.owners == {coordinator.weekly_owner}
    assert adapter.prompts == 1
    assert adapter.blocked == []
    assert "stop_if_idle" not in str(bundle.executor.calls)
    assert barrier.calls == []
    assert runtime.calls == []
    assert order == []


def test_later_explicit_x_re_presents_choice_and_reopens_only_then():
    coordinator, bundle, host, _lifecycle, runtime, barrier, adapter, order = (
        make_coordinator(prompt_results=[False, True])
    )
    fault(coordinator)
    assert coordinator.state == coordinator.KEPT
    assert coordinator.intercept_native_close() is True
    assert coordinator._worker_done.wait(5)
    worker = coordinator._worker
    if worker is not None:
        worker.join(5)
        assert not worker.is_alive()
    assert coordinator.state == coordinator.RECOVERED
    assert adapter.prompts == 2
    assert "reopen_sequence" in order
    assert "invalidate" in order
    assert bundle.executor.freeze_owners == {coordinator.freeze_owner}


def test_preflight_busy_refuses_without_stopping_or_closing():
    host = FakeHost()
    host._page_busy = True
    coordinator, bundle, _host, _lifecycle, runtime, barrier, adapter, _order = (
        make_coordinator(prompt_results=[True], host=host)
    )
    fault(coordinator)
    assert coordinator.state == coordinator.BLOCKED
    assert coordinator.last_code == "BUSY"
    assert adapter.blocked == ["BUSY"]
    assert "stop_if_idle" not in str(bundle.executor.calls)
    assert barrier.calls == []
    assert runtime.calls == []


def test_active_ai_refuses_without_stop_or_drain():
    host = FakeHost()
    coordinator, bundle, _host, _lifecycle, runtime, barrier, adapter, _order = (
        make_coordinator(prompt_results=[True], host=host)
    )
    bundle.executor.snapshot_idle = False
    bundle.executor.snapshot["attempt_in_flight"] = True
    fault(coordinator)
    assert coordinator.state == coordinator.BLOCKED
    assert coordinator.last_code == "AI_BUSY"
    assert "stop_if_idle" not in str(bundle.executor.calls)
    assert barrier.calls == []
    assert runtime.calls == []


def test_atomic_idle_stop_and_service_stop_order_then_engine_and_lease():
    coordinator, bundle, host, lifecycle, runtime, barrier, adapter, order = (
        make_coordinator(prompt_results=[True])
    )
    trace: list[str] = []
    original_block = host._block_native_io

    def block_native():
        trace.append("block_native")
        return original_block()

    host._block_native_io = block_native
    original_stop = bundle.executor.stop_if_idle

    def stop_if_idle(**kwargs):
        trace.append("stop_executor")
        return original_stop(**kwargs)

    bundle.executor.stop_if_idle = stop_if_idle
    original_service = lifecycle.stop_service

    def stop_service(bundle_arg, timeout=10.0):
        trace.append("stop_service")
        return original_service(bundle_arg, timeout)

    lifecycle.stop_service = stop_service
    original_retire = lifecycle.retire_host

    def retire_host(bundle_arg):
        trace.append("retire_host")
        return original_retire(bundle_arg)

    lifecycle.retire_host = retire_host
    original_close = runtime.close_engine_keep_lock

    def close_engine():
        trace.append("close_engine")
        return original_close()

    runtime.close_engine_keep_lock = close_engine
    original_reopen = runtime.reopen_after_restore

    def reopen_engine():
        trace.append("reopen_engine")
        return original_reopen()

    runtime.reopen_after_restore = reopen_engine
    original_release = barrier.lease.release

    def release_lease():
        trace.append("release_lease")
        return original_release()

    barrier.lease.release = release_lease
    coordinator._invalidate_authorizations = lambda: trace.append("invalidate")
    coordinator._reopen_sequence = lambda: (
        trace.append("reopen_sequence") or {"state": "reopened"}
    )

    fault(coordinator)
    assert coordinator.state == coordinator.RECOVERED
    assert adapter.blocked == []
    assert trace == [
        "stop_executor",
        "block_native",
        "stop_service",
        "retire_host",
        "close_engine",
        "release_lease",
        "reopen_engine",
        "invalidate",
        "reopen_sequence",
    ]
    assert barrier.lease.released == 1
    assert runtime.prepared is True


def test_service_stop_failure_keeps_engine_and_root_ownership():
    coordinator, bundle, host, lifecycle, runtime, barrier, adapter, order = (
        make_coordinator(prompt_results=[True])
    )
    lifecycle.stop_ok = False
    fault(coordinator)
    assert coordinator.state == coordinator.BLOCKED
    assert coordinator.last_code == "REOPEN_FAILED"
    assert adapter.blocked == ["REOPEN_FAILED"]
    assert "stop_if_idle" in str(bundle.executor.calls)
    assert "stop_service" in lifecycle.calls
    assert "retire_host" not in lifecycle.calls
    assert runtime.calls == []
    assert barrier.lease.released == 0
    assert coordinator.lease_retained is True
    assert order == []


def test_executor_stop_failure_does_not_stop_service_or_engine():
    coordinator, bundle, host, lifecycle, runtime, barrier, adapter, order = (
        make_coordinator(prompt_results=[True])
    )
    bundle.executor.stop_ok = False
    fault(coordinator)
    assert coordinator.state == coordinator.BLOCKED
    assert coordinator.last_code == "BUSY"
    assert "stop_if_idle" in str(bundle.executor.calls)
    assert host.calls == []
    assert host._native_io_blocked is False
    assert "stop_service" not in lifecycle.calls
    assert runtime.calls == []
    assert barrier.lease.released == 1
    assert order == []

    # The quiet refusal is retryable: after the handoff settles, the same
    # explicit choice can complete without a poisoned native-IO host.
    bundle.executor.stop_ok = True
    assert coordinator.intercept_native_close() is True
    assert coordinator._worker_done.wait(5)
    assert coordinator.state == coordinator.RECOVERED
    assert host.calls == ["block_native_io"]
    assert "stop_service" in lifecycle.calls
    assert "reopen_engine" in runtime.calls


def test_engine_close_failure_keeps_root_lock_and_fault_window():
    coordinator, bundle, host, lifecycle, runtime, barrier, adapter, order = (
        make_coordinator(prompt_results=[True])
    )
    runtime.close_fails = True
    fault(coordinator)
    assert coordinator.state == coordinator.BLOCKED
    assert "stop_service" in lifecycle.calls
    assert "retire_host" in lifecycle.calls
    assert "close_engine" in runtime.calls
    assert "reopen_engine" not in runtime.calls
    assert barrier.lease.released == 0
    assert coordinator.lease_retained is True
    assert order == []


def test_reopen_engine_failure_is_terminal_without_automatic_retry():
    coordinator, bundle, host, lifecycle, runtime, barrier, adapter, order = (
        make_coordinator(prompt_results=[True, True])
    )
    runtime.reopen_fails = True
    fault(coordinator)
    assert coordinator.state == coordinator.BLOCKED
    assert coordinator.last_code == "REOPEN_FAILED"
    assert adapter.prompts == 1
    # The old host was retired and the engine was closed: a later explicit X
    # must not start a second recovery against stale ownership.
    assert coordinator.intercept_native_close() is True
    assert coordinator._worker is None
    assert adapter.prompts == 1
    assert coordinator.state == coordinator.STALE


def test_stale_bundle_cannot_operate_new_current_bundle():
    host = FakeHost()
    coordinator, bundle, _host, lifecycle, runtime, barrier, adapter, order = (
        make_coordinator(prompt_results=[False], host=host)
    )
    fault(coordinator)
    assert adapter.prompts == 1
    newer = FakeBundle(generation=2)
    lifecycle.install(newer)
    assert coordinator.intercept_native_close() is True
    assert coordinator.state == coordinator.STALE
    assert adapter.prompts == 1
    assert runtime.calls == []
    assert barrier.calls == []
    assert order == []


def test_mark_expected_close_detaches_watcher_and_ignores_later_faults():
    coordinator, bundle, _host, _lifecycle, runtime, barrier, adapter, order = (
        make_coordinator(prompt_results=[False])
    )
    fault(coordinator)
    coordinator.mark_expected_close()
    assert coordinator.expected_close is True
    assert adapter.watcher_close == 1
    coordinator._on_native_failure("BrowserProcessExited")
    assert adapter.prompts == 1
    assert runtime.calls == []
    assert barrier.calls == []


def test_freeze_owner_survives_ordinary_close_cancel():
    coordinator, bundle, _host, _lifecycle, _runtime, _barrier, _adapter, _order = (
        make_coordinator(prompt_results=[False])
    )
    fault(coordinator)
    bundle.executor.freeze(owner="close:request")
    bundle.executor.unfreeze(owner="close:request")
    assert coordinator.freeze_owner in bundle.executor.freeze_owners
    assert coordinator.weekly_owner in _host._weekly_export_manager.owners


def test_duplicate_fault_callback_is_deduplicated():
    coordinator, _bundle, _host, _lifecycle, _runtime, _barrier, adapter, _order = (
        make_coordinator(prompt_results=[False])
    )
    fault(coordinator)
    coordinator._on_native_failure("BrowserProcessExited")
    assert adapter.prompts == 1


def test_threaded_concurrent_faults_start_only_one_worker():
    coordinator, _bundle, _host, _lifecycle, _runtime, _barrier, adapter, _order = (
        make_coordinator(prompt_results=[False])
    )
    barrier = threading.Barrier(3)

    def fire():
        barrier.wait()
        coordinator._on_native_failure("RenderProcessExited")

    threads = [threading.Thread(target=fire) for _ in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(5)
    assert coordinator._worker_done.wait(5)
    worker = coordinator._worker
    if worker is not None:
        worker.join(5)
    assert adapter.prompts == 1
    assert coordinator.faulted is True


def test_late_old_initial_bundle_does_not_freeze_runtime_new_executor():
    old_bundle = FakeBundle(generation=1)
    old_bundle.executor = None  # the initial run_interactive bundle may have no AI
    host = FakeHost()
    lifecycle = FakeLifecycle(old_bundle, host)
    runtime = FakeRuntime(host)
    old_bundle.runtime = runtime
    new_executor = FakeExecutor()
    runtime.ai_executor = new_executor
    barrier = FakeBarrier()
    adapter = FakeAdapter([True])
    coordinator = rr.RendererRecoveryCoordinator(
        window=old_bundle.window,
        host_api=host,
        lifecycle=lifecycle,
        bundle=old_bundle,
        runtime=runtime,
        reopen_sequence=lambda: {"state": "reopened"},
        adapter=adapter,
        log=lambda _message: None,
        invalidate_authorizations=lambda: None,
        barrier_getter=lambda _root: barrier,
    )
    coordinator.install()
    newer = FakeBundle(generation=2, runtime=runtime)
    newer.executor = new_executor
    lifecycle.install(newer)

    coordinator._on_native_failure("RenderProcessExited")

    assert adapter.prompts == 0
    assert new_executor.freeze_owners == set()
    assert new_executor.calls == []
    assert host._weekly_export_manager.owners == set()
    assert coordinator._worker is None


def test_blocking_prompt_and_notice_keep_single_worker_reservation():
    class GatedAdapter(FakeAdapter):
        def __init__(self):
            super().__init__([True])
            self.prompt_entered = threading.Event()
            self.release_prompt = threading.Event()
            self.notice_entered = threading.Event()
            self.release_notice = threading.Event()

        def prompt_reopen(self, window):
            self.prompts += 1
            self.prompt_entered.set()
            assert self.release_prompt.wait(5)
            return True

        def notify_reopen_blocked(self, window, code):
            self.blocked.append(code)
            self.notice_entered.set()
            assert self.release_notice.wait(5)

    host = FakeHost()
    host._page_busy = True
    adapter = GatedAdapter()
    coordinator, _bundle, _host, _lifecycle, _runtime, _barrier, _adapter, _order = (
        make_coordinator(host=host, adapter=adapter)
    )
    coordinator._on_native_failure("RenderProcessExited")
    assert adapter.prompt_entered.wait(5)
    first_worker = coordinator._worker
    assert first_worker is not None
    assert coordinator.intercept_native_close() is True
    assert adapter.prompts == 1
    adapter.release_prompt.set()
    assert adapter.notice_entered.wait(5)
    assert coordinator._worker_done.is_set() is False
    assert coordinator.intercept_native_close() is True
    assert adapter.prompts == 1
    adapter.release_notice.set()
    assert coordinator._worker_done.wait(5)
    first_worker.join(5)
    assert not first_worker.is_alive()
    assert coordinator.state == coordinator.BLOCKED
    assert coordinator.last_code == "BUSY"
    assert adapter.prompts == 1


class FakeCloseGuard:
    def __init__(self):
        self.revoked: list[str] = []
        self.finish_calls = 0
        self.finish_ok = True

    def revoke(self, reason):
        self.revoked.append(reason)
        return {"revoked": True, "reason": reason}

    def finish(self):
        self.finish_calls += 1
        return self.finish_ok


class OrderAdapter(FakeAdapter):
    def __init__(self, guard):
        super().__init__([False])
        self.guard = guard
        self.prompt_finish_calls = None

    def prompt_reopen(self, window):
        self.prompt_finish_calls = self.guard.finish_calls
        return super().prompt_reopen(window)


def test_fault_revokes_close_and_finishes_install_before_prompt():
    guard = FakeCloseGuard()
    adapter = OrderAdapter(guard)
    coordinator, _bundle, _host, _lifecycle, _runtime, _barrier, _adapter, _order = (
        make_coordinator(
            adapter=adapter,
            close_revoker=guard.revoke,
            close_revocation_finisher=guard.finish,
        )
    )
    fault(coordinator)
    assert guard.revoked == ["renderer_recovery"]
    assert guard.finish_calls == 1
    assert adapter.prompt_finish_calls == 1
    assert coordinator.state == coordinator.KEPT


def test_close_revocation_failure_blocks_prompt():
    guard = FakeCloseGuard()
    guard.finish_ok = False
    adapter = OrderAdapter(guard)
    coordinator, _bundle, _host, _lifecycle, _runtime, _barrier, _adapter, _order = (
        make_coordinator(
            adapter=adapter,
            close_revoker=guard.revoke,
            close_revocation_finisher=guard.finish,
        )
    )
    fault(coordinator)
    assert guard.finish_calls == 1
    assert adapter.prompts == 0
    assert adapter.prompt_finish_calls is None
    assert coordinator.state == coordinator.BLOCKED
    assert coordinator.last_code == "REOPEN_FAILED"
    assert adapter.blocked == ["REOPEN_FAILED"]


def test_final_closing_fault_does_not_prompt_or_finish_install_cancel():
    class FinalCloseGuard(FakeCloseGuard):
        def revoke(self, reason):
            self.revoked.append(reason)
            return {"revoked": False, "reason": "final_closing"}

    guard = FinalCloseGuard()
    adapter = OrderAdapter(guard)
    coordinator, _bundle, _host, _lifecycle, _runtime, _barrier, _adapter, _order = (
        make_coordinator(
            adapter=adapter,
            close_revoker=guard.revoke,
            close_revocation_finisher=guard.finish,
        )
    )
    fault(coordinator)
    assert guard.revoked == ["renderer_recovery"]
    assert guard.finish_calls == 0
    assert adapter.prompts == 0
    assert coordinator.expected_close is True
