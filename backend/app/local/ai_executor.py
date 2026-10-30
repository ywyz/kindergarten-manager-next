"""D2 W3 main-process AI executor: one coordinator thread, one spawn worker.

Engineering spec §4.1 / §4.3. Design guarantees:

* **one coordinator** owns every pipe write, every ``_active`` mutation and
  every worker teardown; host threads only set flags and wait on an idle
  event, so there is no concurrent read/close of the same pipe and no spawn
  after a drain observed an empty slot;
* a **short in-memory gate** (``_gate``) is shared by ``freeze`` and the final
  SEND: the freeze flag is set under the gate and the SEND control frame is
  written under the same gate, so a freeze either lands before the mark (no
  send) or after it (treated conservatively). The gate never spans a DB wait,
  the network or user interaction; the DB dispatch mark is committed *before*
  the gate is taken for the SEND;
* **fail-closed recovery**: if the cold-start classification fails, scheduling
  is blocked for the whole session (no outbound request) while the manual path
  keeps working;
* a stopped/drained attempt is **persistently classified** (released back to
  pending, or paused/unknown by send evidence) — never left ``claimed``;
* worker exit is confirmed with ``WaitForSingleObject``; an unconfirmed exit
  keeps the handles and blocks new scheduling, normal close and the runtime
  lock release;
* the absolute ``GetTickCount64`` attempt deadline is re-checked after every
  poll/recv and before a result is committed, so a response queued across a
  sleep cannot bypass the rule.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wtypes
import json
import multiprocessing
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from app.local import ai_progress, ai_task_service, ai_transport, backup_barrier
from app.local.base import utc_now

# ---------------------------------------------------------------------------
# Windows Job Object / wait primitives
# ---------------------------------------------------------------------------

_JobObjectExtendedLimitInformation = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_TERMINATE = 0x0001
_WAIT_OBJECT_0 = 0x00000000
_WAIT_TIMEOUT = 0x00000102

_kernel32 = None


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wtypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wtypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wtypes.DWORD),
        ("SchedulingClass", wtypes.DWORD),
    ]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def _load_kernel32():
    global _kernel32
    if _kernel32 is None:
        _kernel32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)
        _kernel32.CreateJobObjectW.restype = wtypes.HANDLE
        _kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wtypes.LPCWSTR]
        _kernel32.SetInformationJobObject.restype = wtypes.BOOL
        _kernel32.SetInformationJobObject.argtypes = [
            wtypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wtypes.DWORD
        ]
        _kernel32.AssignProcessToJobObject.restype = wtypes.BOOL
        _kernel32.AssignProcessToJobObject.argtypes = [wtypes.HANDLE, wtypes.HANDLE]
        _kernel32.TerminateJobObject.restype = wtypes.BOOL
        _kernel32.TerminateJobObject.argtypes = [wtypes.HANDLE, wtypes.UINT]
        _kernel32.OpenProcess.restype = wtypes.HANDLE
        _kernel32.OpenProcess.argtypes = [wtypes.DWORD, wtypes.BOOL, wtypes.DWORD]
        _kernel32.CloseHandle.restype = wtypes.BOOL
        _kernel32.CloseHandle.argtypes = [wtypes.HANDLE]
        _kernel32.WaitForSingleObject.restype = wtypes.DWORD
        _kernel32.WaitForSingleObject.argtypes = [wtypes.HANDLE, wtypes.DWORD]
    return _kernel32


def wait_handle(handle: Any, timeout_ms: int) -> int:
    return int(_load_kernel32().WaitForSingleObject(handle, max(int(timeout_ms), 0)))


class JobObject:
    """A fresh anonymous Job with KILL_ON_JOB_CLOSE and no breakaway."""

    def __init__(self):
        if os.name != "nt":
            raise RuntimeError("Windows Job Object unavailable")
        kernel32 = _load_kernel32()
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise OSError("CreateJobObjectW failed")
        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(
            handle, _JobObjectExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info)
        ):
            kernel32.CloseHandle(handle)
            raise OSError("SetInformationJobObject failed")
        self._handle = handle
        self._closed = False

    def assign(self, pid: int) -> None:
        kernel32 = _load_kernel32()
        process = kernel32.OpenProcess(_PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, int(pid))
        if not process:
            raise OSError(f"OpenProcess failed: {ctypes.get_last_error()}")
        try:
            if not kernel32.AssignProcessToJobObject(self._handle, process):
                raise OSError(f"AssignProcessToJobObject failed: {ctypes.get_last_error()}")
        finally:
            kernel32.CloseHandle(process)

    def terminate(self) -> None:
        if self._closed:
            return
        try:
            _load_kernel32().TerminateJobObject(self._handle, 1)
        except Exception:  # noqa: BLE001
            pass

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            _load_kernel32().CloseHandle(self._handle)
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------

_DRAIN = object()

# How long the coordinator withholds a SEND while a cancel transaction
# resolves before treating the unresolved state conservatively.
_CANCEL_RESOLVE_SECONDS = 10.0


@dataclass
class _Active:
    claim: ai_task_service.Claim
    process: Any
    conn: Any
    job: JobObject
    marked: bool = False
    abort_mode: str = ""
    cancel_pending: bool = False
    io_threads: list = field(default_factory=list)


class AiExecutor:
    """One coordinator thread and at most one in-flight network attempt."""

    def __init__(
        self,
        runtime: Any,
        *,
        worker_target: Callable[[Any], None] | None = None,
        spawn_context: Any | None = None,
        clock: Callable[[], int] = ai_transport.now_ticks,
        sleep: Callable[[float], None] = time.sleep,
        poll_interval: float = 0.2,
        connect_phase_limit: float = ai_transport.CONNECT_BUDGET_MS / 1000.0,
        logger: Callable[[str], None] | None = None,
        synthetic_transport: dict[str, Any] | None = None,
        on_event: Callable[[str, Any], None] | None = None,
        thread_factory: Callable[..., Any] | None = None,
    ):
        self._runtime = runtime
        self._worker_target = worker_target or _default_worker_target()
        self._ctx = spawn_context or multiprocessing.get_context("spawn")
        self._clock = clock
        self._sleep = sleep
        self._poll = poll_interval
        self._connect_phase_limit = connect_phase_limit
        self._log = logger or (lambda _message: None)
        # Synthetic transport (test CA + fixed resolution): only a dedicated
        # synthetic verification entry sets this; production leaves it None.
        self._synthetic = synthetic_transport
        # Observation hook for the verification probe (never changes behavior).
        self._on_event = on_event or (lambda _name, _claim: None)
        # Thread factory seam: only a dedicated verification entry injects one
        # (to exercise a real ``threading.Thread.start`` failure); production
        # always uses the standard library factory.
        self._thread_factory = thread_factory or threading.Thread
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._frozen = threading.Event()
        self._freeze_owners: set[str] = set()
        self._draining = threading.Event()
        self._gate = threading.Lock()
        self._idle = threading.Event()
        self._idle.set()
        self._active: _Active | None = None
        self._schedule_blocked = False
        self._persist_blocked = False
        self._unconfirmed = False
        self._unconfirmed_slots: list[dict] = []
        self._close_epoch = 0
        self._pending_results: dict[str, dict[str, Any]] = {}
        self.launch_id = str(uuid.uuid4())

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> bool:
        if self._thread is not None:
            return True
        if not getattr(self._runtime, "launch_id", None):
            try:
                self._runtime.launch_id = self.launch_id
            except Exception:  # noqa: BLE001
                pass
        recovery_ok = self._recover()
        if not recovery_ok:
            # Fail closed: an unclassified old task must never be claimed.
            self._schedule_blocked = True
            self._log("recovery failed; AI scheduling disabled")
        self._stop.clear()
        # The thread handle is assigned only *after* a successful start. A
        # factory/``Thread.start`` failure must leave ``_thread`` unset so
        # ``stop()``/``dispose()`` can honestly confirm "no worker" instead of
        # joining a thread that was never started (which would raise).
        thread = self._thread_factory(
            target=self._run, name="kgm-ai-executor", daemon=True
        )
        thread.start()
        self._thread = thread
        return recovery_ok

    def _recover(self) -> bool:
        """Cold-start classification; True only when it fully succeeded."""
        session = self._runtime.session()
        try:
            from sqlalchemy import select

            from app.local.models import LocalProfile

            if session.scalars(select(LocalProfile)).first() is None:
                return True
            ai_task_service.recover_on_start(session, now=utc_now())
            return True
        except Exception:  # noqa: BLE001
            try:
                session.rollback()
            except Exception:  # noqa: BLE001
                pass
            return False
        finally:
            session.close()

    def notify(self) -> None:
        self._wake.set()

    def _emit(self, name: str, claim: Any, info: dict | None = None) -> None:
        """Observation hook (the verification probe); never changes behavior.

        The payload carries only non-secret facts (never the pinned secret).
        """
        try:
            self._on_event(name, claim, info or {})
        except TypeError:
            try:
                self._on_event(name, claim)
            except Exception:  # noqa: BLE001
                pass
        except Exception:  # noqa: BLE001
            pass

    def is_frozen(self) -> bool:
        return self._frozen.is_set()

    def freeze(self, owner: str = "close") -> None:
        """Synchronously freeze new claims and the final SEND (short gate).

        Freeze owners are independent: a snapshot ending must not clear a
        close/restore intent that was already present (or arrived later).
        """
        with self._gate:
            self._freeze_owners.add(owner)
            self._frozen.set()
        self._wake.set()

    def unfreeze(self, owner: str = "close") -> None:
        with self._gate:
            self._freeze_owners.discard(owner)
            if not self._freeze_owners:
                self._frozen.clear()
                self._draining.clear()
        self._wake.set()

    def is_snapshot_idle(self) -> bool:
        """True when no active/pending result can still write persistence."""
        return (
            self._active is None
            and not self._pending_results
            and not self._unconfirmed_slots
            and not self._unconfirmed
        )

    def abort_execution(self, execution_id: str, mode: str) -> bool:
        active = self._active
        if active is None or active.claim.execution_id != execution_id:
            return False
        active.abort_mode = mode
        self._wake.set()
        return True

    def begin_cancel(self, execution_id: str) -> bool:
        """Freeze the final SEND while the caller's cancel transaction runs.

        It never terminates the worker: the coordinator only withholds the SEND
        and waits for the transaction's conclusion. On a commit the caller
        calls ``end_cancel(committed=True)``; on a failure/conflict it calls
        ``end_cancel(committed=False)`` and the original permit continues.
        Bound to the execution id so a stale key/expected value cannot disturb
        a newer execution.
        """
        with self._gate:
            active = self._active
            if active is None or active.claim.execution_id != execution_id:
                return False
            active.cancel_pending = True
            return True

    def end_cancel(self, execution_id: str, *, committed: bool) -> None:
        with self._gate:
            active = self._active
            if active is None or active.claim.execution_id != execution_id:
                return
            active.cancel_pending = False
            if committed:
                active.abort_mode = "stop_wait"
        self._wake.set()

    def is_runnable(self) -> bool:
        """True only when the coordinator can actually take new work."""
        if (
            self._schedule_blocked
            or self._persist_blocked
            or self._unconfirmed
            or self._pending_results
            or self._unconfirmed_slots
        ):
            return False
        thread = self._thread
        if thread is None or not thread.is_alive():
            return False
        return True

    def stop_and_drain(self, *, deadline: float = 5.0) -> bool:
        """Stop-and-exit: freeze, revoke permits in ONE transaction, then stop.

        Order per spec §4.3: a close barrier freezes new claims/SEND first; a
        single short transaction revokes every unfinished permit and classifies
        by send evidence (a success committed first stays succeeded). Only a
        *committed* revoke marks the coordinator draining and lets it stop the
        in-flight worker (2 s cooperative, then a forced Job terminate confirmed
        within 3 s). A DB failure keeps the original worker alive and refuses
        the close. The in-memory close epoch guarantees a claim that already
        left the gate cannot commit across the revoke transaction.
        """
        # Stage 1: pending-close barrier (freeze only; never kill yet).
        with self._gate:
            self._freeze_owners.add("close")
            self._frozen.set()
            self._close_epoch += 1
        self._wake.set()
        # Stage 2: revoke in one transaction.
        try:
            session = self._runtime.session()
            try:
                ai_task_service.revoke_all_for_close(session, now=utc_now())
            finally:
                session.close()
        except Exception:  # noqa: BLE001 - never kill without a committed revoke
            self._log("close revoke failed")
            return False
        # Stage 3: the revoke is committed; now the coordinator may drain.
        self._draining.set()
        self._wake.set()
        if not self._idle.wait(deadline):
            return False
        return (
            self._active is None
            and not self._unconfirmed
            and not self._pending_results
            and not self._unconfirmed_slots
        )

    def stop(self, *, grace: float = 2.0, force: float = 3.0) -> bool:
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=grace + force + 5.0)
            if thread.is_alive():
                # Keep the reference: the thread may still own a worker.
                return False
            self._thread = None
        return (
            self._active is None
            and not self._unconfirmed
            and not self._pending_results
            and not self._unconfirmed_slots
        )

    def dispose(self, *, grace: float = 2.0, force: float = 3.0) -> bool:
        """Confirm worker收口 before the runtime lock may be released.

        Also resolves any resource kept from an earlier unconfirmed teardown.
        """
        result = self.stop(grace=grace, force=force)
        for slot in list(self._unconfirmed_slots):
            active = slot.get("active")
            process = slot.get("process")
            job = slot.get("job")
            conn = slot.get("conn")
            try:
                if job is not None:
                    job.terminate()
            except Exception:  # noqa: BLE001
                pass
            if active is not None:
                self._join_io(active, max(force, 1.0))
            if not self._wait_exit(process, force):
                continue
            if active is not None and active.io_threads and self._io_pending(active):
                continue
            try:
                if conn is not None:
                    conn.close()
            except Exception:  # noqa: BLE001
                pass
            try:
                if job is not None:
                    job.close()
            except Exception:  # noqa: BLE001
                pass
            try:
                self._unconfirmed_slots.remove(slot)
            except ValueError:
                pass
        if not self._unconfirmed_slots:
            self._unconfirmed = False
        if result and not self._unconfirmed_slots:
            # The display cache is process-local and is released on exit.
            ai_progress.clear()
        return result and not self._unconfirmed_slots

    def active_snapshot(self) -> dict[str, Any]:
        active = self._active
        return {
            "attempt_in_flight": active is not None,
            "execution_id": active.claim.execution_id if active is not None else None,
            "frozen": self.is_frozen(),
            "draining": self._draining.is_set(),
            "schedule_blocked": self._schedule_blocked,
            "unconfirmed": self._unconfirmed,
            "pending_persist": len(self._pending_results),
            "persist_blocked": self._persist_blocked,
        }

    # -- thread loop -------------------------------------------------------
    def _run(self) -> None:
        while not self._stop.is_set():
            if self._pending_results:
                # Only local commit/read-back is retried; never a resend.
                self._flush_pending()
                if not self._pending_results:
                    continue
                self._wake.wait(self._poll)
                self._wake.clear()
                continue
            try:
                worked = self._claim_and_run()
            except Exception:  # noqa: BLE001 - never kill the coordinator
                self._log("executor iteration failed")
                worked = False
            if not worked:
                self._wake.wait(self._poll)
                self._wake.clear()

    def _flush_pending(self) -> None:
        """Retry only the local persistence of results already received."""
        for execution_id, entry in list(self._pending_results.items()):
            claim, result = entry["claim"], entry["result"]
            session = self._runtime.session()
            try:
                with backup_barrier.ai_write_scope():
                    if result.get("kind") == ai_transport.SUCCESS:
                        ai_task_service.finalize_success(session, claim, result, utc_now())
                    else:
                        ai_task_service.finalize_failure(session, claim, result, utc_now())
                self._pending_results.pop(execution_id, None)
            except Exception:  # noqa: BLE001 - still local only
                try:
                    session.rollback()
                except Exception:  # noqa: BLE001
                    pass
            finally:
                session.close()
        if not self._pending_results:
            self._persist_blocked = False

    def _claim_and_run(self) -> bool:
        # Atomic handoff with freeze/drain: the frozen/draining check and the
        # idle clear happen under the same short gate, so a drain can never see
        # an idle executor that is about to claim. DB work stays outside.
        with self._gate:
            if (
                self._frozen.is_set()
                or self._stop.is_set()
                or self._draining.is_set()
                or self._schedule_blocked
            ):
                return False
            self._idle.clear()
            epoch = self._close_epoch
        try:
            session = self._runtime.session()
            try:
                from sqlalchemy import select

                from app.local.models import LocalProfile

                profile = session.scalars(select(LocalProfile)).first()
                if profile is None:
                    return False
                self._emit("before_claim", None, {})
                with backup_barrier.ai_write_scope():
                    claim = ai_task_service.claim_next(
                        self._runtime,
                        now=utc_now(),
                        started_ticks=self._clock(),
                        guard=lambda: self._close_epoch == epoch,
                    )
            finally:
                session.close()
            if claim is None:
                return False
            self._emit("claimed", claim)
            try:
                outcome = self._drive(claim)
            except Exception:  # noqa: BLE001 - a pre-send crash must be classified
                self._log("attempt drive failed")
                outcome = self._exception_outcome(claim)
            if outcome is _DRAIN:
                outcome = {"kind": "stopped", "reason": "user_stop"}
            self._finalize(claim, outcome)
            return True
        finally:
            self._idle.set()

    def _assign_job(self, job: JobObject, process: Any, parent_conn, active: _Active | None) -> bool:
        try:
            job.assign(process.pid)
            return True
        except Exception:  # noqa: BLE001
            return False

    def _abandon_process(self, process: Any, parent_conn, job: JobObject | None) -> Any:
        """A start/Job failure: confirm the exit before releasing any handle.

        If the exit cannot be confirmed the process keeps its handles, the
        coordinator stops scheduling new work and a normal dispose/close is
        refused — never a silent handle drop.
        """
        try:
            process.kill()
        except Exception:  # noqa: BLE001
            pass
        confirmed = self._wait_exit(process, 3.0)
        if confirmed:
            if job is not None:
                try:
                    job.close()
                except Exception:  # noqa: BLE001
                    pass
            try:
                parent_conn.close()
            except Exception:  # noqa: BLE001
                pass
        else:
            self._unconfirmed = True
            self._schedule_blocked = True
            # Keep the process/pipe/job references in the persistent slot: a
            # normal dispose must not pass while a worker may still be alive.
            self._unconfirmed_slots.append(
                {"process": process, "conn": parent_conn, "job": job, "active": None}
            )
            self._log("abandoned worker exit unconfirmed")
        return {"kind": "stopped", "reason": "executor_unavailable"}

    def _exception_outcome(self, claim: ai_task_service.Claim) -> dict[str, Any]:
        """Classify an unexpected attempt failure from the persisted evidence.

        An exception in the post-SEND teardown/WinAPI/IPC phase must never wash
        a marked (possibly sent) attempt into ``not_sent``. The attempt's
        persisted ``dispatch_marked_at`` is the authority; if it cannot be read,
        the conservative "possibly sent" classification is used.
        """
        session = None
        marked = True
        try:
            session = self._runtime.session()
            from app.local.models import LocalAIAttempt

            attempt = session.get(LocalAIAttempt, claim.attempt_id)
            marked = bool(attempt is not None and attempt.dispatch_marked_at is not None)
        except Exception:  # noqa: BLE001 - cannot prove unsent: be conservative
            marked = True
        finally:
            if session is not None:
                try:
                    session.close()
                except Exception:  # noqa: BLE001
                    pass
        if marked:
            return {"kind": "unknown", "reason": "timeout_after_dispatch", "sent": True}
        return {"kind": "stopped", "reason": "executor_unavailable"}

    # -- one attempt -------------------------------------------------------
    def _wait_unfreeze(self, active: _Active | None, deadline_ms: int) -> str:
        """Wait out a close-intent freeze without retiring the claim.

        Returns ``"go"`` (freeze cleared: continue with the same permit and
        pinned versions), ``"stop"`` (a real stop/cancel drains the attempt) or
        ``"timeout"`` (the attempt budget expired while frozen). The claim is
        never released or replaced here, so cancelling a close continues the
        already-claimed execution instead of creating a new generation.
        """
        while True:
            with self._gate:
                if self._stop.is_set() or self._draining.is_set():
                    return "stop"
                if active is not None and active.abort_mode in ("cancel", "pause"):
                    return "stop"
                if not self._frozen.is_set():
                    return "go"
            if self._clock() > deadline_ms:
                return "timeout"
            self._sleep(0.02)

    def _drive(self, claim: ai_task_service.Claim) -> Any:
        deadline_ms = claim.started_ticks + claim.attempt_budget_ms
        # Barrier 1: a close-intent freeze before spawning waits it out rather
        # than retiring the claim.
        verdict = self._wait_unfreeze(None, deadline_ms)
        if verdict == "stop":
            return {"kind": "stopped", "reason": "user_stop"}
        if verdict == "timeout":
            return {"kind": "stopped", "reason": "connection_unavailable"}
        try:
            parent_conn, child_conn = self._ctx.Pipe(duplex=True)
            process = self._ctx.Process(
                target=self._worker_target, args=(child_conn,), daemon=False
            )
            process.start()
        except Exception:  # noqa: BLE001
            for stream in (locals().get("parent_conn"), locals().get("child_conn")):
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:  # noqa: BLE001
                        pass
            return {"kind": "stopped", "reason": "executor_unavailable"}
        child_conn.close()
        # Emitted after the child exists but BEFORE the Job assignment: the
        # child must not do any network work until the Job is assigned.
        self._emit("child_started", claim, {"pid": int(process.pid)})
        try:
            job = JobObject()
        except Exception:  # noqa: BLE001 - Job construction is controlled too
            return self._abandon_process(process, parent_conn, None)
        if not self._assign_job(job, process, parent_conn, active=None):
            return self._abandon_process(process, parent_conn, job)
        self._emit("job_assigned", claim, {"pid": int(process.pid)})
        active = _Active(claim=claim, process=process, conn=parent_conn, job=job)
        self._active = active
        # Display-only progress: "waiting" is visible before any HTTP byte.
        ai_progress.begin(claim)
        try:
            frame_bytes = _encode_bootstrap(claim, deadline_ms, self._synthetic)
        except ValueError:
            # The actual request/IPC frame exceeds the limit: pause before any
            # network or Job work, never disguise it as a model output error.
            return self._teardown_then(active, {"kind": "stopped", "reason": "input_too_large"})
        try:
            # Barrier 2 (before any network work in the child).
            verdict = self._wait_unfreeze(active, deadline_ms)
            if verdict == "stop":
                return self._teardown_then(active, {"kind": "stopped", "reason": "user_stop"})
            if verdict == "timeout":
                return self._teardown_then(
                    active, {"kind": "stopped", "reason": "connection_unavailable"}
                )
            # The connect phase (worker start + DNS + TCP + TLS) is supervised
            # by the parent with the same 10 s budget as the worker's own
            # resolver/connect deadline, and can never extend past the whole
            # attempt's absolute deadline (a long claim/close wait already
            # consumed part of the 120 s).
            phase_deadline = min(
                deadline_ms, self._clock() + int(self._connect_phase_limit * 1000)
            )
            active.deadline_ms = phase_deadline
            status = self._run_io(
                active, lambda: {"data": self._sendall(parent_conn, frame_bytes)}
            )
            if status != "ok":
                return self._teardown_then(
                    active, {"kind": "stopped", "reason": "executor_unavailable"}
                )

            frame = self._await_frame(active, phase_deadline)
            if frame is _DRAIN:
                return self._drain_outcome(active, sent=False)
            if frame is None:
                return self._teardown_then(active, self._prefetch_timeout_outcome())
            if frame.get("type") == "result":
                return self._teardown_then(active, frame.get("result") or self._prefetch_timeout_outcome())
            if frame.get("type") != "ready":
                return self._teardown_then(active, self._prefetch_timeout_outcome())
            self._emit("ready", claim)

            # Barrier 3: the freeze is waited out (claim kept) before the mark.
            verdict = self._wait_unfreeze(active, deadline_ms)
            if verdict == "stop":
                return self._teardown_then(active, {"kind": "stopped", "reason": "user_stop"})
            if verdict == "timeout":
                return self._teardown_then(
                    active, {"kind": "stopped", "reason": "connection_unavailable"}
                )

            # The DB dispatch mark is committed *outside* the gate.
            if not self._commit_mark(claim):
                return self._teardown_then(active, {"kind": "stopped", "reason": "user_stop"})
            active.marked = True
            self._emit("marked", claim)
            conservative = self._send_after_mark(active, parent_conn, deadline_ms)
            if conservative is not None:
                return self._teardown_then(active, conservative)
            self._emit("sent", claim)
            frame = self._await_frame(active, deadline_ms)
            if frame is _DRAIN:
                return self._drain_outcome(active, sent=True)
            if frame is None or frame.get("type") != "result":
                return self._teardown_then(
                    active,
                    {"kind": "unknown", "reason": "timeout_after_dispatch", "sent": True},
                )
            outcome = frame.get("result") or {}
            self._emit("result_received", claim)
            obtained_at = self._clock()
            if obtained_at > deadline_ms:
                # A response that only arrived after the absolute deadline is
                # rejected even if the content looks like a success.
                self._teardown(active, grace=0.0, force=3.0)
                return {"kind": "unknown", "reason": "timeout_after_dispatch", "sent": True}
            return self._teardown_then(active, outcome)
        except BaseException:
            if self._active is active:
                # One bounded teardown only; the drain budget is enforced by
                # the host's idle wait, which returns False rather than
                # claiming a 5 s close that actually took longer.
                self._teardown(active, grace=0.0, force=3.0)
            raise

    def _sendall(self, conn: Any, data: Any) -> bool:
        frames = data if isinstance(data, (list, tuple)) else (data,)
        for frame in frames:
            conn.send_bytes(frame)
        return True

    def _send_after_mark(self, active: _Active, parent_conn, deadline_ms: int) -> Any:
        """Send the SEND frame atomically with the freeze/cancel check.

        Only this small control frame is written here: READY proves the child
        already consumed the bootstrap, so it cannot block the pipe. Any wait
        for a pending cancel happens outside the gate. Returns None when the
        send happened; otherwise a conservative (possibly-sent) outcome.
        """
        waited = 0.0
        while True:
            with self._gate:
                if active.cancel_pending:
                    pass  # wait for the cancel transaction's conclusion
                elif (
                    self._frozen.is_set()
                    or self._stop.is_set()
                    or self._draining.is_set()
                    or active.abort_mode
                ):
                    return {
                        "kind": "unknown",
                        "reason": "timeout_after_dispatch",
                        "sent": True,
                    }
                else:
                    try:
                        parent_conn.send_bytes(json.dumps({"type": "send"}).encode("utf-8"))
                        return None
                    except Exception:  # noqa: BLE001
                        return {
                            "kind": "unknown",
                            "reason": "timeout_after_dispatch",
                            "sent": True,
                        }
            if waited >= _CANCEL_RESOLVE_SECONDS or self._clock() > deadline_ms:
                return {"kind": "unknown", "reason": "timeout_after_dispatch", "sent": True}
            self._sleep(0.02)
            waited += 0.02

    # -- frame I/O ---------------------------------------------------------
    def _await_frame(self, active: _Active, deadline_ms: int) -> Any:
        active.deadline_ms = deadline_ms
        conn = active.conn
        while True:
            if self._stop.is_set():
                return _DRAIN
            if self._draining.is_set():
                return _DRAIN
            if active.abort_mode in ("cancel", "pause", "stop_wait"):
                return _DRAIN
            remaining = deadline_ms - self._clock()
            if remaining <= 0:
                return None
            try:
                ready = conn.poll(min(0.1, max(remaining, 1) / 1000.0))
            except (OSError, ValueError):
                return None
            if not ready:
                continue
            # A partial frame could block recv_bytes forever: read on a helper
            # thread (short-interval wait, stop/drain aware) so the coordinator
            # keeps supervising and can terminate the Job to unblock the pipe.
            status = self._run_io(
                active,
                lambda: {"data": conn.recv_bytes(ai_worker_frame_limit())},
            )
            if status == "stopped":
                return _DRAIN
            if status != "ok":
                return None
            raw = getattr(active, "last_io", None)
            if raw is None:
                return {"type": "eof"}
            # Re-check the absolute deadline *after* the data is in hand: a
            # response queued across a sleep must not bypass the rule.
            if self._clock() > deadline_ms:
                return None
            try:
                frame = json.loads(bytes(raw).decode("utf-8"))
            except Exception:  # noqa: BLE001
                return {"type": "eof"}
            if not isinstance(frame, dict):
                return {"type": "eof"}
            if frame.get("type") == "progress":
                # Display-only progress: consume and keep waiting. A stale or
                # foreign frame is ignored; the absolute deadline is re-checked
                # at the top of this loop on the next iteration.
                self._apply_progress(active, frame)
                continue
            return frame

    def _apply_progress(self, active: _Active, frame: dict[str, Any]) -> None:
        """Project one worker progress frame into the bounded display cache."""
        if self._active is not active:
            return
        if self._stop.is_set() or self._draining.is_set() or active.abort_mode:
            return
        reasoning = frame.get("reasoning")
        content_chars = frame.get("content_chars")
        phase = frame.get("phase")
        seq = frame.get("seq")
        if not isinstance(seq, int) or isinstance(seq, bool):
            return
        if frame.get("heartbeat") is True:
            # A real SSE keepalive updates only the supplier-data clock; it must
            # not change the phase or invent text.
            ai_progress.heartbeat(active.claim, seq=seq)
            return
        if not isinstance(reasoning, str) or not isinstance(phase, str):
            return
        if not isinstance(content_chars, int) or isinstance(content_chars, bool):
            content_chars = 0
        ai_progress.update(
            active.claim,
            seq=seq,
            phase=phase,
            reasoning_delta=reasoning,
            content_chars=content_chars,
        )

    # -- bounded IPC (the coordinator never blocks on the pipe) ------------
    def _run_io(self, active: _Active, work) -> str:  # noqa: ANN001
        """Run one pipe operation on a helper thread with a short-interval wait.

        Returns ``"ok"``/``"error"``/``"timeout"``/``"stopped"``. The helper is
        tracked on the attempt so teardown can confirm it exited before the
        pipe is closed and never writes a second frame into an in-flight write.
        """
        outcome: dict[str, Any] = {"ok": False, "data": None}

        def runner() -> None:
            try:
                outcome.update(work())
                outcome["ok"] = True
            except Exception:  # noqa: BLE001
                outcome["ok"] = False

        thread = threading.Thread(target=runner, daemon=True)
        active.io_threads.append(thread)
        thread.start()
        while thread.is_alive():
            if self._stop.is_set() or self._draining.is_set() or active.abort_mode:
                return "stopped"
            if self._clock() > self._deadline_hint(active):
                return "timeout"
            thread.join(0.05)
        if not outcome["ok"]:
            return "error"
        active.last_io = outcome.get("data")
        return "ok"

    def _deadline_hint(self, active: _Active) -> int:
        return getattr(
            active,
            "deadline_ms",
            ai_transport.now_ticks() + active.claim.attempt_budget_ms,
        )

    def _io_pending(self, active: _Active) -> bool:
        return any(thread.is_alive() for thread in active.io_threads)

    def _join_io(self, active: _Active, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        for thread in active.io_threads:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            thread.join(remaining)
        return not self._io_pending(active)

    def _prefetch_timeout_outcome(self) -> dict[str, Any]:
        if self._draining.is_set():
            return {"kind": "stopped", "reason": "user_stop"}
        return {
            "kind": "not_sent",
            "reason": "connection_unavailable",
            "transient_not_sent": True,
            "sent": False,
        }

    def _drain_outcome(self, active: _Active, *, sent: bool) -> Any:
        if sent:
            self._teardown(active, grace=0.0, force=3.0)
            return {"kind": "unknown", "reason": "user_stop", "sent": True}
        return self._teardown_then(active, {"kind": "stopped", "reason": "user_stop"})

    def _teardown_then(self, active: _Active, outcome: Any, *, gate_held: bool = False) -> Any:
        self._teardown(active, grace=2.0, force=3.0, gate_held=gate_held)
        return outcome

    def _teardown(self, active: _Active, *, grace: float, force: float, gate_held: bool = False) -> bool:
        """Cooperative stop, then Job force; confirm the exit with a wait.

        An in-flight pipe operation is never joined by a second frame (no abort
        written into a pending bootstrap write): the Job is terminated first so
        the blocked IO fails, then the IO thread is joined before the handles
        are released. A worker whose exit (or IO thread) cannot be confirmed is
        kept in the persistent unconfirmed slot and blocks dispose/close.
        """
        io_pending = self._io_pending(active)
        confirmed = False
        if not io_pending and grace > 0:
            try:
                if not active.conn.closed:
                    if gate_held:
                        active.conn.send_bytes(json.dumps({"type": "abort"}).encode("utf-8"))
                    else:
                        with self._gate:
                            active.conn.send_bytes(
                                json.dumps({"type": "abort"}).encode("utf-8")
                            )
            except Exception:  # noqa: BLE001
                pass
            if self._wait_exit(active.process, grace):
                confirmed = True
        if not confirmed:
            try:
                active.job.terminate()
            except Exception:  # noqa: BLE001
                pass
            # The IO join and the OS exit wait share one force deadline so the
            # two steps cannot accumulate 3 s + 3 s.
            force_deadline = time.monotonic() + force
            io_ok = self._join_io(active, max(force_deadline - time.monotonic(), 0.1))
            confirmed = (
                self._wait_exit(active.process, max(force_deadline - time.monotonic(), 0.1))
                and io_ok
            )
        if confirmed:
            self._release_active(active)
            return True
        # Could not confirm: keep the handles (and the IO thread) and block
        # scheduling/close until a later dispose resolves them.
        self._unconfirmed = True
        self._schedule_blocked = True
        self._unconfirmed_slots.append(
            {"process": active.process, "conn": active.conn, "job": active.job, "active": active}
        )
        self._log("worker exit unconfirmed")
        return False

    def _wait_exit(self, process: Any, timeout: float) -> bool:
        try:
            sentinel = process.sentinel
        except Exception:  # noqa: BLE001
            sentinel = None
        if sentinel is not None:
            result = wait_handle(sentinel, int(timeout * 1000))
            if result == _WAIT_OBJECT_0:
                try:
                    process.join(0)
                except Exception:  # noqa: BLE001
                    pass
                return process.exitcode is not None
            if result == _WAIT_TIMEOUT:
                return False
        try:
            process.join(timeout)
        except Exception:  # noqa: BLE001
            return False
        return process.exitcode is not None

    def _release_active(self, active: _Active) -> None:
        if self._io_pending(active):
            # Never close the pipe under an in-flight helper.
            self._unconfirmed = True
            self._schedule_blocked = True
            return
        try:
            active.conn.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            active.job.close()
        except Exception:  # noqa: BLE001
            pass
        if self._active is active:
            self._active = None

    # -- persistence -------------------------------------------------------
    def _commit_mark(self, claim: ai_task_service.Claim) -> bool:
        session = self._runtime.session()
        try:
            with backup_barrier.ai_write_scope():
                return ai_task_service.commit_dispatch_mark(session, claim, utc_now())
        finally:
            session.close()

    def _finalize(self, claim: ai_task_service.Claim, result: Any) -> None:
        if not isinstance(result, dict):
            result = {"kind": "unknown", "reason": "timeout_after_dispatch", "sent": True}
        result.setdefault("duration_ms", max(self._clock() - claim.started_ticks, 0))
        ai_progress.finish(claim, result)
        kind = result.get("kind")
        last_error: Exception | None = None
        for _ in range(3):
            session = self._runtime.session()
            try:
                with backup_barrier.ai_write_scope():
                    if kind == ai_transport.SUCCESS:
                        ai_task_service.finalize_success(session, claim, result, utc_now())
                    else:
                        ai_task_service.finalize_failure(session, claim, result, utc_now())
                self._emit("persisted", claim)
                return
            except Exception as exc:  # noqa: BLE001 - local only, never a resend
                last_error = exc
                try:
                    session.rollback()
                except Exception:  # noqa: BLE001
                    pass
                self._sleep(0.2)
            finally:
                session.close()
        self._pending_results[claim.execution_id] = {"claim": claim, "result": result}
        self._persist_blocked = True
        self._log(f"result persistence failed: {type(last_error).__name__}")


def _encode_bootstrap(
    claim: ai_task_service.Claim,
    deadline_ms: int,
    synthetic: dict | None = None,
) -> list[bytes]:
    from app.local import ai_worker
    from app.local.observation_ai_inputs import (
        OBSERVATION_INPUT_SCHEMA_VERSION,
        OBSERVATION_TASK_TYPES,
        build_vision_frames,
        check_vision_context,
    )

    if claim.image_urls:
        if not (
            claim.source_kind == "game_observation"
            and claim.observation_id
            and claim.task_type in OBSERVATION_TASK_TYPES
            and claim.vision_authorized
            and claim.vision_protocol == ai_transport.VISION_PROTOCOL_ID
            and claim.vision_schema_version == OBSERVATION_INPUT_SCHEMA_VERSION
            and claim.contract_version in ai_task_service.SUPPORTED_CONTRACT_VERSIONS
            and ai_transport.vision_capability(claim.base_url, claim.model)
            and len(claim.work_dimensions) == len(claim.image_urls)
        ):
            raise ValueError("vision_not_authorized")
        if len(claim.image_urls) > ai_transport.VISION_MAX_IMAGES:
            raise ValueError("vision_image_count")
        if any(
            not isinstance(url, str) or not url.startswith("data:image/")
            for url in claim.image_urls
        ):
            raise ValueError("vision_image_url")
        user_text = json.dumps(
            claim.payload, ensure_ascii=False, separators=(",", ":")
        )
        check_vision_context(
            base_url=claim.base_url,
            model=claim.model,
            system_text=claim.system_text,
            user_text=user_text,
            work_dimensions=list(claim.work_dimensions),
        )
        body = ai_transport.build_vision_request(
            model=claim.model,
            system_text=claim.system_text,
            user_text=user_text,
            image_urls=list(claim.image_urls),
        )
        if len(body) > ai_transport.VISION_BODY_MAX_BYTES:
            raise ValueError("request_too_large")
        total = ai_transport.build_http_request(
            base_url=claim.base_url, secret=claim.secret, body=body
        )
        if len(total) > ai_transport.VISION_HTTP_MAX_BYTES:
            raise ValueError("request_too_large")
        frames = build_vision_frames(
            base_url=claim.base_url,
            model=claim.model,
            secret=claim.secret,
            system_text=claim.system_text,
            user_text=user_text,
            image_urls=list(claim.image_urls),
            deadline_ms=deadline_ms,
            task_type=claim.task_type,
            contract_version=claim.contract_version,
            synthetic=synthetic,
        )
        if sum(len(item) for item in frames) > ai_transport.VISION_IPC_FRAME_MAX:
            raise ValueError("frame_too_large")
        if len(frames[0]) > ai_worker.REQUEST_FRAME_MAX:
            raise ValueError("frame_too_large")
        return frames

    if claim.source_kind != "daily_plan" or claim.vision_authorized:
        raise ValueError("text_bootstrap_not_authorized")

    request = {
        "base_url": claim.base_url,
        "model": claim.model,
        "secret": claim.secret,
        "system_text": claim.system_text,
        "user_text": json.dumps(claim.payload, ensure_ascii=False, separators=(",", ":")),
    }
    # The actual serialized body must fit the 1 MiB request limit (a heavy
    # escape or multi-byte payload can exceed it even when the input JSON did
    # not); the whole bootstrap frame must also fit the IPC bound.
    body_size = len(
        ai_transport.build_request(
            model=claim.model,
            system_text=claim.system_text,
            user_text=request["user_text"],
        )
    )
    if body_size > ai_transport.REQUEST_MAX_BYTES:
        raise ValueError("request_too_large")
    payload = {
        "type": "bootstrap",
        "deadline_ms": deadline_ms,
        "synthetic": synthetic,
        "request": request,
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(raw) > ai_worker.REQUEST_FRAME_MAX:
        raise ValueError("frame_too_large")
    return [raw]


def ai_worker_frame_limit() -> int:
    from app.local import ai_worker

    return ai_worker.RESPONSE_FRAME_MAX


def _default_worker_target() -> Callable[[Any], None]:
    from app.local import ai_worker

    return ai_worker.worker_entry


__all__ = ["AiExecutor", "JobObject", "ai_worker_frame_limit", "wait_handle"]
