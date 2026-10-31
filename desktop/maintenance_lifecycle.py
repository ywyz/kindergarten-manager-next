"""Host lifecycle bundles and the reopen sequencing after a restore.

The restore core owns the maintenance lease, the data switch and the journal.
It never creates servers, executors or windows: this module is the host side of
that boundary.  One ``LifecycleBundle`` describes exactly one generation of

    runtime lock + executor + local app/service + host API + window + close
    coordinator + native-IO epoch.

A restore creates a new bundle and installs it before the old window is
destroyed, so process shutdown always closes the latest server and releases
only the runtime lock that belongs to it.  A late callback bound to an old
bundle keeps a reference to that old object; it is never resolved dynamically
to the current bundle.
"""

from __future__ import annotations

import dataclasses
import threading
import time
from typing import Any, Callable


class ReopenSequenceError(RuntimeError):
    """Bounded host-side failure after the core already installed the data."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclasses.dataclass
class LifecycleBundle:
    """One host generation.  Never re-point a bundle at a newer object."""

    generation: int
    service: Any = None
    host_api: Any = None
    runtime: Any = None
    window: Any = None
    coordinator: Any = None
    executor: Any = None
    # Bound to this window/host only; used for the restore retire path so the
    # old window closes without starting the normal close-and-exit handshake
    # and without touching the new window.
    retire_destroy: Callable[[], None] | None = None

    def destroy_window_for_retire(self) -> None:
        if self.retire_destroy is not None:
            self.retire_destroy()
            return
        window = self.window
        if window is not None:
            window.destroy()


class LifecycleManager:
    """Holds the single current bundle and closes the latest one only."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._current: LifecycleBundle | None = None
        self._generation = 0

    def next_generation(self) -> int:
        with self._lock:
            self._generation += 1
            return self._generation

    def install(self, bundle: LifecycleBundle) -> LifecycleBundle:
        with self._lock:
            self._current = bundle
        return bundle

    def current(self) -> LifecycleBundle | None:
        with self._lock:
            return self._current

    # -- retirement / stop primitives -----------------------------------
    @staticmethod
    def retire_host(bundle: LifecycleBundle | None) -> None:
        """Disable new side effects/bootstrap on this exact host instance."""
        host = getattr(bundle, "host_api", None)
        if host is None:
            return
        retire = getattr(host, "retire", None)
        if not callable(retire):
            retire = getattr(host, "_retire", None)
        if callable(retire):
            try:
                retire()
            except Exception:  # noqa: BLE001 - retirement is best effort
                pass

    @staticmethod
    def stop_service(bundle: LifecycleBundle | None, timeout: float = 10.0) -> bool:
        """Stop this bundle's transport and report only confirmed death.

        ``stop()`` alone (a timed-out join) is not success: a caller must keep
        the old data group and must not switch while this returns False.
        """
        service = getattr(bundle, "service", None)
        if service is None:
            return True
        confirm = getattr(service, "stop_and_confirm", None)
        if callable(confirm):
            try:
                return bool(confirm(timeout))
            except Exception:  # noqa: BLE001 - unknown is never success
                return False
        # Legacy service objects have no confirmation API.  Stopping is still
        # attempted, but the caller never treats it as confirmed death.
        try:
            service.stop(timeout)
        except Exception:  # noqa: BLE001
            pass
        return False

    def dispose_bundle(self, bundle: LifecycleBundle | None, timeout: float = 10.0) -> bool:
        """Retire host, stop transport, then release executor/runtime.

        The runtime lock is released only after the service thread is
        confirmed dead: releasing it while a server still serves the same
        runtime would defeat the single-writer guarantee.
        """
        if bundle is None:
            return True
        self.retire_host(bundle)
        if not self.stop_service(bundle, timeout):
            return False
        executor = bundle.executor
        if executor is None and bundle.runtime is not None:
            executor = getattr(bundle.runtime, "ai_executor", None)
        executor_confirmed = True
        if executor is not None:
            dispose = getattr(executor, "dispose", None)
            if callable(dispose):
                try:
                    executor_confirmed = bool(dispose())
                except Exception:  # noqa: BLE001
                    executor_confirmed = False
        if not executor_confirmed:
            # A worker whose exit is not confirmed keeps the runtime lock, as
            # the normal D2 close path does.  The process is ending, but the
            # run must not claim a clean release.
            return False
        runtime = bundle.runtime
        if runtime is not None:
            dispose_runtime = getattr(runtime, "dispose", None)
            if callable(dispose_runtime):
                try:
                    dispose_runtime()
                except Exception:  # noqa: BLE001
                    pass
        return True

    def close_latest(self, timeout: float = 10.0) -> bool:
        with self._lock:
            bundle = self._current
        return self.dispose_bundle(bundle, timeout)


class ReopenSequencer:
    """Create the new host generation after the core reopened the data.

    Ordering is the contract:

    1. retire the old host before the new engine is exposed;
    2. build the new app/token/scope/executor and install the bundle BEFORE
       the service starts, so a failed/unconfirmed start is still owned by
       the latest-bundle cleanup;
    3. confirm the service ready, then create the new Window + host while the
       old window still exists;
    5. wait for the new page to load business, not merely ``page_ready``;
    6. destroy the old window through its own retire path.

    Any failure keeps the old window and its protection/error text, stops only
    the new transport and keeps the runtime lock.  It never claims that the
    data was unchanged and never auto-rolls back.
    """

    def __init__(
        self,
        *,
        manager: LifecycleManager,
        old_bundle: LifecycleBundle,
        build_bundle: Callable[[LifecycleBundle], LifecycleBundle],
        create_window: Callable[[LifecycleBundle], None],
        wait_business_ready: Callable[[LifecycleBundle, float], bool],
        timeout: float = 60.0,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self.manager = manager
        self.old_bundle = old_bundle
        self.build_bundle = build_bundle
        self.create_window = create_window
        self.wait_business_ready = wait_business_ready
        self.timeout = timeout
        self.log = log or (lambda _message: None)

    def run(self) -> dict[str, Any]:
        # 1. No new old-host side effect or bootstrap may race the new engine.
        self.manager.retire_host(self.old_bundle)
        new_bundle: LifecycleBundle | None = None
        try:
            # 2. New runtime exposure exists only after this bundle is built.
            new_bundle = self.build_bundle(self.old_bundle)
            if new_bundle is None:
                raise ReopenSequenceError(
                    "REOPEN_BUILD_FAILED", "无法创建新的本地服务"
                )
            # 2. Install the new bundle BEFORE the service starts: a failed
            # start (or an unconfirmed stop) must still be the latest bundle
            # whose cleanup protects the shared runtime lock.
            self.manager.install(new_bundle)
            service = new_bundle.service
            if service is not None:
                started = False
                start = getattr(service, "start_and_wait", None)
                if callable(start):
                    started = bool(start())
                else:
                    started = True
                if not started:
                    raise ReopenSequenceError(
                        "REOPEN_SERVICE_FAILED", "新的本地服务未能启动"
                    )
            # 3. The new window exists before the old one is destroyed.
            self.create_window(new_bundle)
            # 5. page_ready is before reloadContext: wait for real business.
            if not self.wait_business_ready(new_bundle, self.timeout):
                raise ReopenSequenceError(
                    "REOPEN_PAGE_TIMEOUT", "新页面未能读取本地资料"
                )
            # 6. Retire path bound to the old window itself.
            self.old_bundle.destroy_window_for_retire()
            return {
                "state": "reopened",
                "generation": new_bundle.generation,
            }
        except Exception as exc:  # noqa: BLE001 - reported as a terminal DTO
            code = str(getattr(exc, "code", "REOPEN_SEQUENCE_FAILED"))
            self.log(f"reopen sequence failed: {code}")
            if new_bundle is not None:
                # Keep the runtime lock: the old page may still be showing
                # progress and the process must not lose its single writer.
                self.manager.retire_host(new_bundle)
                self.manager.stop_service(new_bundle, self.timeout)
                if new_bundle.window is not None:
                    # Never leave a half-started new window beside the old
                    # error window.  Its own retire path bypasses the normal
                    # close-and-exit handshake.
                    try:
                        new_bundle.host_api._request_retire_destroy()
                    except Exception:  # noqa: BLE001
                        pass
                    try:
                        new_bundle.destroy_window_for_retire()
                    except Exception:  # noqa: BLE001
                        pass
            return {"state": "reopen_failed", "code": code}


class HostMaintenanceHooks:
    """The only host operations the restore core may call.

    ``wait_host_idle`` drains accepted page/native work but never waits on the
    maintenance panel's own busy flag: doing so would make the panel wait for
    itself.  ``stop_transport`` must confirm the old server thread is dead.
    """

    def __init__(
        self,
        *,
        manager: LifecycleManager,
        bundle_getter: Callable[[], LifecycleBundle | None],
        busy_probe: Callable[[LifecycleBundle], bool],
        poll_seconds: float = 0.05,
        timeout: float = 60.0,
        log: Callable[[str], None] | None = None,
        on_switch: Callable[[], None] | None = None,
    ) -> None:
        self.manager = manager
        self.bundle_getter = bundle_getter
        self.busy_probe = busy_probe
        self.poll_seconds = poll_seconds
        self.timeout = timeout
        self.log = log or (lambda _message: None)
        self.on_switch = on_switch or (lambda: None)

    def wait_host_idle(self, cancel=None) -> bool:
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            if cancel is not None and getattr(cancel, "is_set", lambda: False)():
                return False
            bundle = self.bundle_getter()
            if bundle is None:
                return True
            try:
                busy = bool(self.busy_probe(bundle))
            except Exception:  # noqa: BLE001 - unknown work is not idle
                busy = True
            if not busy:
                return True
            time.sleep(self.poll_seconds)
        self.log("wait_host_idle timed out")
        return False

    def stop_transport(self) -> bool:
        bundle = self.bundle_getter()
        confirmed = self.manager.stop_service(bundle, self.timeout)
        if not confirmed:
            self.log("stop_transport not confirmed")
            return False
        try:
            self.on_switch()
        except Exception:  # noqa: BLE001 - the switch still proceeds
            pass
        return True
