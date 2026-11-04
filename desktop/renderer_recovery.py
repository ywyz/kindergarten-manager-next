"""Manual recovery coordinator for a confirmed WebView2 renderer/browser loss.

The native watcher/prompt lives in ``renderer_recovery_native`` (owned by B).
This module owns only the business-safe recovery state machine: one fault per
window/generation, a single bounded worker, fail-closed preflight, snapshot
barrier accounting, retiral of the old side, and the same-database reopen via
the existing lifecycle sequencer.

No JS, HTTP, database write or user dialog runs in the native failure callback.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable

FATAL_KINDS = frozenset({"RenderProcessExited", "BrowserProcessExited"})
RECOVERY_NOTICE = "已重新打开最后保存的档案。未保存的输入可能已丢失。"


@dataclass(frozen=True)
class RecoveryFault:
    kind: str
    generation: int
    nonce: str


@dataclass(frozen=True)
class RecoveryResult:
    state: str
    code: str | None = None


class RendererRecoveryCoordinator:
    """One exact window/generation's native fault to manual reopen flow."""

    IDLE = "idle"
    FAULTED = "faulted"
    KEPT = "kept"
    RECOVERING = "recovering"
    RECOVERED = "recovered"
    BLOCKED = "blocked"
    STALE = "stale"

    def __init__(
        self,
        *,
        window: Any,
        host_api: Any,
        lifecycle: Any,
        bundle: Any,
        runtime: Any,
        reopen_sequence: Callable[[], dict[str, Any]],
        adapter: Any,
        log: Callable[[str], None] | None = None,
        invalidate_authorizations: Callable[[], None] | None = None,
        barrier_getter: Callable[[Any], Any] | None = None,
    ) -> None:
        self._window = window
        self._host = host_api
        self._lifecycle = lifecycle
        self._bundle = bundle
        self._runtime = runtime
        # Capture the exact generation's objects once.  Never read
        # runtime.ai_executor or a live service field later: after a restore
        # reopen those point at a newer generation while an old watcher can
        # still receive a late ProcessFailed.
        self._executor_ref = getattr(bundle, "executor", None)
        self._weekly_ref = getattr(host_api, "_weekly_export_manager", None)
        if self._weekly_ref is None:
            self._weekly_ref = getattr(
                getattr(bundle, "service", None), "weekly_export_manager", None
            )
        self._reopen_sequence = reopen_sequence
        self._adapter = adapter
        self._log = log or (lambda _message: None)
        self._invalidate_authorizations = (
            invalidate_authorizations or _invalidate_launch_authorizations
        )
        self._barrier_getter = barrier_getter or _default_barrier_getter
        self._lock = threading.RLock()
        self._state = self.IDLE
        self._fault: RecoveryFault | None = None
        self._expected_close = False
        self._last_code: str | None = None
        self._worker: threading.Thread | None = None
        self._worker_done = threading.Event()
        self._worker_done.set()
        self._watcher: Any = None
        self._recovery_attempt = 0
        self._destructive_started = False
        self._freeze_error = False
        self._retained_lease: Any = None
        self._lease_retained = False

    # -- installation / introspection -------------------------------------

    def install(self) -> None:
        """Install B's native watcher for exactly this window."""
        try:
            self._watcher = self._adapter.install_renderer_watcher(
                self._window, self._on_native_failure, log=self._log
            )
        except Exception as exc:  # noqa: BLE001 - no recovery without a watcher
            self._log(f"renderer recovery: watcher install failed: {type(exc).__name__}")

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    @property
    def faulted(self) -> bool:
        with self._lock:
            return self._fault is not None

    @property
    def expected_close(self) -> bool:
        with self._lock:
            return self._expected_close

    @property
    def last_code(self) -> str | None:
        with self._lock:
            return self._last_code

    @property
    def lease_retained(self) -> bool:
        with self._lock:
            return self._lease_retained

    @property
    def freeze_owner(self) -> str:
        with self._lock:
            fault = self._fault
        if fault is None:
            nonce = "unfaulted"
            generation = int(getattr(self._bundle, "generation", 0) or 0)
        else:
            nonce = fault.nonce
            generation = fault.generation
        return f"renderer:{generation}:{nonce}"

    @property
    def weekly_owner(self) -> str:
        with self._lock:
            fault = self._fault
        if fault is None:
            nonce = "unfaulted"
            generation = int(getattr(self._bundle, "generation", 0) or 0)
        else:
            nonce = fault.nonce
            generation = fault.generation
        return f"renderer-weekly:{generation}:{nonce}"

    # -- native callback (must stay quick) --------------------------------

    def _on_native_failure(self, kind: str) -> None:
        kind = str(kind)
        if kind not in FATAL_KINDS:
            return
        if not self._identity_current():
            return
        with self._lock:
            if self._expected_close or self._fault is not None:
                return
            nonce = _new_nonce()
            self._fault = RecoveryFault(
                kind=kind,
                generation=int(getattr(self._bundle, "generation", 0) or 0),
                nonce=nonce,
            )
            self._state = self.FAULTED
            self._last_code = None
        # These are short in-memory owner operations, never DB/UI/JS.
        self._freeze_fault_owners()
        self._request_prompt_worker()

    def _freeze_fault_owners(self) -> None:
        executor = self._executor()
        if executor is not None:
            try:
                executor.freeze(owner=self.freeze_owner)
            except Exception as exc:  # noqa: BLE001 - recovery will fail closed
                self._freeze_error = True
                self._log(f"renderer recovery: freeze failed: {type(exc).__name__}")
        weekly = self._weekly_manager()
        if weekly is not None:
            try:
                weekly.pause(owner=self.weekly_owner)
            except Exception as exc:  # noqa: BLE001 - recovery will fail closed
                self._freeze_error = True
                self._log(f"renderer recovery: weekly pause failed: {type(exc).__name__}")

    def _request_prompt_worker(self) -> None:
        with self._lock:
            if self._expected_close or self._fault is None:
                return
            worker = self._worker
            if worker is not None:
                if not worker.is_alive() and self._worker_done.is_set():
                    self._worker = None
                else:
                    return
            worker = threading.Thread(
                target=self._prompt_and_recover,
                name="renderer-recovery",
                daemon=True,
            )
            self._worker = worker
            self._worker_done.clear()
            try:
                # Start under the same lock: a concurrent explicit X cannot
                # see an unstarted reservation as "not alive" and start a
                # second worker.
                worker.start()
            except Exception as exc:  # noqa: BLE001 - no prompt is safer
                self._worker = None
                self._worker_done.set()
                self._log(
                    f"renderer recovery: worker start failed: {type(exc).__name__}"
                )

    # -- public close interception ---------------------------------------

    def intercept_native_close(self) -> bool:
        """Return True to cancel a faulted native close and request a choice."""
        with self._lock:
            if self._expected_close or self._fault is None:
                return False
            if self._state == self.RECOVERING:
                return True
            if self._state in (self.RECOVERED, self.STALE):
                return True
            if not self._identity_current():
                self._state = self.STALE
                return True
        self._request_prompt_worker()
        return True

    def mark_expected_close(self) -> None:
        """Detach the native watcher before a controlled/final window close."""
        with self._lock:
            self._expected_close = True
            watcher = self._watcher
            self._watcher = None
        if watcher is not None:
            try:
                watcher.close()
            except Exception:  # noqa: BLE001 - closing is best effort
                pass

    # -- prompt / recovery worker ----------------------------------------

    def _prompt_and_recover(self) -> None:
        try:
            if not self._identity_current():
                with self._lock:
                    self._state = self.STALE
                return
            try:
                choice = bool(self._adapter.prompt_reopen(self._window))
            except Exception as exc:  # noqa: BLE001 - keep the fault window
                self._log(f"renderer recovery: prompt failed: {type(exc).__name__}")
                choice = False
            if not choice:
                with self._lock:
                    if self._state == self.FAULTED:
                        self._state = self.KEPT
                return
            with self._lock:
                if self._expected_close:
                    return
                if not self._identity_current():
                    self._state = self.STALE
                    return
                self._state = self.RECOVERING
                self._recovery_attempt += 1
            code = self._recover_once()
            with self._lock:
                if code is None:
                    self._state = self.RECOVERED
                    self._last_code = None
                else:
                    self._state = self.BLOCKED
                    self._last_code = code
            if code is not None:
                try:
                    self._adapter.notify_reopen_blocked(self._window, code)
                except Exception as exc:  # noqa: BLE001 - notice is best effort
                    self._log(
                        f"renderer recovery: blocked notice failed: "
                        f"{type(exc).__name__}"
                    )
        finally:
            # Keep the worker reservation until the blocking prompt AND any
            # blocked notice have fully returned; a later explicit X may then
            # present a fresh choice.
            with self._lock:
                self._worker = None
                self._worker_done.set()

    # -- recovery preflight / safe sequence ------------------------------

    def _recover_once(self) -> str | None:
        if not self._identity_current():
            return "STALE"
        if self._freeze_error:
            return "BUSY"
        busy = self._preflight_code()
        if busy is not None:
            return busy
        executor = self._executor()
        weekly = self._weekly_manager()
        barrier = None
        lease = None
        retain_lease = False
        try:
            barrier = self._barrier_getter(self._runtime.data_dir)
            try:
                lease = barrier.begin_intent(self.freeze_owner)
            except Exception:  # noqa: BLE001 - maintenance/backup owns the root
                return "MAINTENANCE_BUSY"
            if tuple(barrier.active_counts) != (0, 0):
                return "BUSY"
            busy = self._preflight_code()
            if busy is not None:
                return busy
            if executor is not None and not executor.is_snapshot_idle():
                return "AI_BUSY"
            if weekly is not None and not weekly.wait_idle(timeout=0.0):
                return "BUSY"
            try:
                barrier.acquire_exclusive(lease)
                barrier.validate_exclusive_lease(lease)
            except Exception:  # noqa: BLE001 - another writer arrived
                return "BUSY"
            if tuple(barrier.active_counts) != (0, 0):
                return "BUSY"
            busy = self._preflight_code()
            if busy is not None:
                return busy
            if executor is not None and not executor.is_snapshot_idle():
                return "AI_BUSY"
            if weekly is not None and not weekly.wait_idle(timeout=0.0):
                return "BUSY"
            if not self._identity_current():
                return "STALE"

            # Quiet, retryable stop gate FIRST.  A claim handoff with _active
            # still None but _idle cleared must not poison the old host/native
            # IO; only after the atomic stop succeeds do we enter the
            # irreversible block/service/engine path.
            if executor is not None:
                stop_if_idle = getattr(executor, "stop_if_idle", None)
                if not callable(stop_if_idle):
                    return "REOPEN_FAILED"
                if not bool(stop_if_idle(owner=self.freeze_owner, timeout=5.0)):
                    return "BUSY"

            # From here on a failure retains root-lock/latest ownership.
            # The exclusive lease is retained too if the old side may still
            # serve a valid token/writer; it is never blanket-released.
            self._destructive_started = True
            retain_lease = True
            try:
                self._host._block_native_io()
            except Exception:
                return "REOPEN_FAILED"

            if not bool(self._lifecycle.stop_service(self._bundle, timeout=10.0)):
                return "REOPEN_FAILED"

            # Revalidate the exclusive lease after the old side stopped.
            try:
                barrier.validate_exclusive_lease(lease)
            except Exception:  # noqa: BLE001 - cannot close safely
                return "REOPEN_FAILED"
            if tuple(barrier.active_counts) != (0, 0):
                return "REOPEN_FAILED"

            self._lifecycle.retire_host(self._bundle)
            if not bool(getattr(self._host, "_retired", False)):
                return "REOPEN_FAILED"

            self._runtime.close_engine_keep_lock()

            # Startup writes are allowed only after old service/host/executor
            # stopped, engine closed, and the exclusive lease released.
            lease.release()
            lease = None
            retain_lease = False

            self._runtime.reopen_after_restore()
            self._invalidate_authorizations()
            if not self._generation_current():
                return "STALE"
            outcome = self._reopen_sequence()
            if not isinstance(outcome, dict) or outcome.get("state") != "reopened":
                return "REOPEN_FAILED"
            return None
        except Exception as exc:  # noqa: BLE001 - fixed terminal boundary
            self._log(f"renderer recovery: sequence failed: {type(exc).__name__}")
            return "REOPEN_FAILED"
        finally:
            if lease is not None:
                if retain_lease:
                    # Post-stop failure: keep the exclusive write gate/owner
                    # until the old service/engine ownership is resolved.  Do
                    # not reopen writes or release the root.
                    with self._lock:
                        self._retained_lease = lease
                        self._lease_retained = True
                else:
                    try:
                        lease.release()
                    except Exception:  # noqa: BLE001 - preserve primary failure
                        pass

    def _preflight_code(self) -> str | None:
        try:
            if not self._identity_current():
                return "STALE"
            if bool(getattr(self._host, "_retired", False)) or bool(
                getattr(self._host, "_native_io_blocked", False)
            ):
                return "STALE"
            recovery_required = getattr(self._host, "_recovery_required_probe", None)
            if callable(recovery_required) and bool(recovery_required()):
                return "MAINTENANCE_BUSY"
            if self._probe("_save_in_progress"):
                return "BUSY"
            if self._probe("_page_busy_probe"):
                return "BUSY"
            if self._probe("_update_busy_probe"):
                return "BUSY"
            if self._probe("_maintenance_busy_probe"):
                return "MAINTENANCE_BUSY"

            close_coordinator = getattr(self._host, "_close_coordinator", None)
            if close_coordinator is not None:
                close_state = str(getattr(close_coordinator, "_state", "idle"))
                if close_state in ("pending", "closing"):
                    return "BUSY"

            install = getattr(self._host, "_install_coordinator", None)
            if install is not None:
                available = getattr(install, "install_available", None)
                if callable(available) and not bool(available()):
                    return "BUSY"

            weekly = self._weekly_manager()
            if weekly is not None and not bool(weekly.wait_idle(timeout=0.0)):
                return "BUSY"

            executor = self._executor()
            if executor is not None:
                snapshot = executor.active_snapshot()
                if (
                    snapshot.get("attempt_in_flight")
                    or snapshot.get("pending_persist")
                    or snapshot.get("unconfirmed")
                    or snapshot.get("persist_blocked")
                ):
                    return "AI_BUSY"
                if not bool(executor.is_snapshot_idle()):
                    return "AI_BUSY"

            if not bool(getattr(self._runtime, "prepared", True)):
                return "STALE"
            if not bool(getattr(self._runtime, "_owns_lock", True)):
                return "STALE"
            return None
        except Exception as exc:  # noqa: BLE001 - unknown work is not idle
            self._log(f"renderer recovery: probe failed: {type(exc).__name__}")
            return "BUSY"

    def _probe(self, name: str) -> bool:
        probe = getattr(self._host, name, None)
        if not callable(probe):
            return False
        try:
            return bool(probe())
        except Exception:  # noqa: BLE001 - unknown is busy
            return True

    # -- dependency access / identity ------------------------------------

    def _identity_current(self) -> bool:
        if not self._generation_current():
            return False
        if bool(getattr(self._host, "_retired", False)):
            return False
        form = getattr(self._window, "native", None)
        if form is None or bool(getattr(form, "IsDisposed", False)):
            return False
        return True

    def _generation_current(self) -> bool:
        checker = getattr(self._lifecycle, "is_current", None)
        try:
            if callable(checker):
                if not bool(checker(self._bundle)):
                    return False
            else:
                current = self._lifecycle.current()
                if current is not self._bundle:
                    return False
        except Exception:  # noqa: BLE001 - unknown generation is not current
            return False
        if getattr(self._bundle, "runtime", None) is not self._runtime:
            return False
        if getattr(self._bundle, "window", None) is not self._window:
            return False
        return True

    def _executor(self) -> Any:
        return self._executor_ref

    def _weekly_manager(self) -> Any:
        return self._weekly_ref


def install_renderer_recovery(
    *,
    window: Any,
    host_api: Any,
    lifecycle: Any,
    bundle: Any,
    runtime: Any,
    reopen_sequence: Callable[[], dict[str, Any]],
    adapter: Any = None,
    log: Callable[[str], None] | None = None,
    invalidate_authorizations: Callable[[], None] | None = None,
    barrier_getter: Callable[[Any], Any] | None = None,
) -> RendererRecoveryCoordinator:
    """Install the business coordinator and B's native watcher for one window."""
    if adapter is None:
        import renderer_recovery_native as adapter  # noqa: PLC0415 - native adapter
    coordinator = RendererRecoveryCoordinator(
        window=window,
        host_api=host_api,
        lifecycle=lifecycle,
        bundle=bundle,
        runtime=runtime,
        reopen_sequence=reopen_sequence,
        adapter=adapter,
        log=log,
        invalidate_authorizations=invalidate_authorizations,
        barrier_getter=barrier_getter,
    )
    coordinator.install()
    return coordinator


def _new_nonce() -> str:
    import secrets

    return secrets.token_hex(8)


def _default_barrier_getter(data_root: Any) -> Any:
    from app.local import backup_barrier  # noqa: PLC0415 - backend module

    return backup_barrier.get_barrier(data_root)


def _invalidate_launch_authorizations() -> None:
    """Invalidate old launch-scoped preview/adoption/config tokens."""
    from app.local import config_tokens  # noqa: PLC0415

    config_tokens.rotate_key()
    # The runtime reopen primitive rotates the weekly-plan token key. These
    # module-level preview stores are launch/scope checked; reset them as
    # defense in depth without touching credentials or business rows.
    for name in (
        "ai_adoption",
        "daily_plan_history_service",
        "observation_ai_service",
        "weekly_ai_adoption",
    ):
        try:
            module = __import__(f"app.local.{name}", fromlist=["reset_tokens"])
            reset = getattr(module, "reset_tokens", None)
            if callable(reset):
                reset()
        except Exception:  # noqa: BLE001 - optional legacy preview store
            continue


__all__ = [
    "FATAL_KINDS",
    "RECOVERY_NOTICE",
    "RecoveryFault",
    "RecoveryResult",
    "RendererRecoveryCoordinator",
    "install_renderer_recovery",
]
