"""Process-local snapshot write barrier.

The barrier has two phases:

* intent: new external DB writes, file operations and AI submissions are
  rejected, while work already accepted (including queued/in-flight AI tasks)
  may finish and commit;
* exclusive: after the snapshot has waited for all writers and AI persistence
  to become idle, the barrier atomically takes DB+file exclusivity.

The registry is keyed by data root so independent synthetic runtimes in one
test process do not block each other.  A lease is owned by exactly one
snapshot; release never clears another owner's close/restore intent.
"""

from __future__ import annotations

import contextlib
import contextvars
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.local.errors import LocalError


class SnapshotBusy(LocalError):
    """Another snapshot/writer intent owns this data root."""

    code = "LOCAL_BACKUP_BUSY"
    status_code = 409
    message = "备份或维护操作正在进行，请稍后重试"


class SnapshotCancelled(LocalError):
    """The caller cancelled a snapshot before it acquired exclusivity."""

    code = "LOCAL_BACKUP_CANCELLED"
    status_code = 409
    message = "备份已取消"


class MaintenanceLeaseError(LocalError):
    """The supplied maintenance lease is not the current exclusive lease."""

    code = "LOCAL_BACKUP_MAINTENANCE_LEASE"
    status_code = 409
    message = "维护 lease 无效或不属于当前数据根"


_AI_WRITE_ALLOWED: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "kgm_backup_ai_write_allowed", default=False
)
_OPERATION_WRITE_ALLOWED: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "kgm_backup_operation_write_allowed", default=False
)
_REGISTRY: dict[str, "SnapshotBarrier"] = {}
_REGISTRY_LOCK = threading.Lock()


def _root_key(data_root: str | Path) -> str:
    return os.path.normcase(os.path.abspath(str(data_root)))


def get_barrier(data_root: str | Path) -> "SnapshotBarrier":
    key = _root_key(data_root)
    with _REGISTRY_LOCK:
        barrier = _REGISTRY.get(key)
        if barrier is None:
            barrier = SnapshotBarrier(Path(data_root))
            _REGISTRY[key] = barrier
        return barrier


def barrier_for_session(session: Session) -> "SnapshotBarrier | None":
    try:
        bind = session.get_bind()
        url = getattr(bind, "url", None)
        database = getattr(url, "database", None)
    except Exception:  # noqa: BLE001 - an unusual bind has no managed root
        return None
    if not isinstance(database, str) or not database or database == ":memory:":
        return None
    return get_barrier(Path(database).parent)


def begin_db_write(session: Session) -> "SnapshotBarrier | None":
    barrier = barrier_for_session(session)
    if barrier is not None:
        barrier.enter_db_write()
    return barrier


def abort_db_write(session: Session, barrier: "SnapshotBarrier | None") -> None:
    if barrier is not None:
        barrier.leave_db_write()
    session.info.pop("_kgm_backup_barrier", None)


@contextlib.contextmanager
def ai_write_scope() -> Iterator[None]:
    """Allow the AI executor's own claim/finalize writes during intent.

    This is a private executor context, not a page/API bypass.  It is reset on
    every exit, including exceptions.
    """

    token = _AI_WRITE_ALLOWED.set(True)
    try:
        yield
    finally:
        _AI_WRITE_ALLOWED.reset(token)


def ai_writes_allowed() -> bool:
    return bool(_AI_WRITE_ALLOWED.get() or _OPERATION_WRITE_ALLOWED.get())


@dataclass
class SnapshotLease:
    barrier: "SnapshotBarrier"
    owner: str
    token: str
    exclusive: bool = False
    released: bool = False

    def release(self) -> None:
        if self.released:
            return
        self.released = True
        self.barrier.release(self)


class SnapshotBarrier:
    def __init__(self, data_root: Path):
        self.data_root = Path(data_root)
        self._cond = threading.Condition(threading.RLock())
        self._intent_owner: str | None = None
        self._intent_token: str | None = None
        self._exclusive_owner: str | None = None
        self._db_writers = 0
        self._file_ops = 0
        self._lease_seq = 0

    # -- lease lifecycle -------------------------------------------------
    def begin_intent(self, owner: str, *, cancel=None) -> SnapshotLease:
        with self._cond:
            self._check_cancel(cancel)
            if self._intent_owner is not None:
                raise SnapshotBusy("该数据根已有备份/维护操作")
            self._intent_owner = owner
            self._lease_seq += 1
            token = f"{owner}:{self._lease_seq}"
            self._intent_token = token
            return SnapshotLease(self, owner, token)

    def wait_idle(
        self,
        lease: SnapshotLease,
        *,
        timeout: float = 60.0,
        cancel=None,
    ) -> None:
        deadline = time.monotonic() + max(0.0, timeout)
        with self._cond:
            while self._db_writers or self._file_ops:
                self._check_cancel(cancel)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise SnapshotBusy("等待在途保存/文件操作超时")
                self._cond.wait(min(0.05, remaining))
            self._check_cancel(cancel)

    def acquire_exclusive(
        self,
        lease: SnapshotLease,
        *,
        cancel=None,
    ) -> None:
        with self._cond:
            self._check_cancel(cancel)
            if (
                self._intent_owner != lease.owner
                or self._intent_token != lease.token
                or lease.released
            ):
                raise SnapshotBusy("备份 lease 已失效")
            if self._exclusive_owner is not None and self._exclusive_owner != lease.owner:
                raise SnapshotBusy("该数据根已有独占维护操作")
            if self._db_writers or self._file_ops:
                raise SnapshotBusy("仍有在途保存/文件操作，拒绝独占")
            self._exclusive_owner = lease.owner
            lease.exclusive = True

    def validate_exclusive_lease(self, lease: SnapshotLease) -> None:
        """Read-only validation of an externally held maintenance lease.

        The caller must already own the current intent and exclusive state.
        This method never begins, acquires, releases or mutates a lease.
        """
        if not isinstance(lease, SnapshotLease):
            raise MaintenanceLeaseError("维护 lease 类型不合法")
        if lease.barrier is not self:
            raise MaintenanceLeaseError("维护 lease 不属于当前数据根")
        with self._cond:
            if lease.released or not lease.exclusive:
                raise MaintenanceLeaseError("维护 lease 已释放或未独占")
            if (
                self._intent_owner != lease.owner
                or self._intent_token != lease.token
                or self._exclusive_owner != lease.owner
            ):
                raise MaintenanceLeaseError("维护 lease owner/token 已失效")
            if self._db_writers or self._file_ops:
                raise MaintenanceLeaseError("维护 lease 仍有在途写入或文件操作")

    def release(self, lease: SnapshotLease) -> None:
        with self._cond:
            if (
                self._intent_owner != lease.owner
                or self._intent_token != lease.token
            ):
                # A stale lease (even with a reused owner name) must not clear
                # a newer intent.
                return
            self._intent_owner = None
            self._intent_token = None
            if self._exclusive_owner == lease.owner:
                self._exclusive_owner = None
            self._cond.notify_all()

    # -- writer accounting ----------------------------------------------
    def enter_db_write(self) -> None:
        with self._cond:
            # Internal/continuation scopes may cross intent, never exclusive.
            self._assert_allowed_locked()
            self._db_writers += 1

    def leave_db_write(self) -> None:
        with self._cond:
            if self._db_writers > 0:
                self._db_writers -= 1
            self._cond.notify_all()

    def enter_file_operation(self) -> None:
        with self._cond:
            self._assert_allowed_locked()
            self._file_ops += 1

    def leave_file_operation(self) -> None:
        with self._cond:
            if self._file_ops > 0:
                self._file_ops -= 1
            self._cond.notify_all()

    def assert_writes_allowed(self) -> None:
        with self._cond:
            self._assert_allowed_locked()

    def _assert_allowed_locked(self) -> None:
        if self._exclusive_owner is not None:
            raise SnapshotBusy("备份独占期间禁止写入")
        if self._intent_owner is not None and not ai_writes_allowed():
            raise SnapshotBusy("备份准备期间禁止新的外部写入")

    @staticmethod
    def _check_cancel(cancel) -> None:
        if cancel is not None and cancel.is_set():
            raise SnapshotCancelled("备份已取消")

    @property
    def active_counts(self) -> tuple[int, int]:
        with self._cond:
            return self._db_writers, self._file_ops

    @property
    def intent_owner(self) -> str | None:
        with self._cond:
            return self._intent_owner

    @property
    def exclusive_owner(self) -> str | None:
        with self._cond:
            return self._exclusive_owner


@contextlib.contextmanager
def file_scope(data_root: str | Path) -> Iterator[None]:
    barrier = get_barrier(data_root)
    barrier.enter_file_operation()
    token = _OPERATION_WRITE_ALLOWED.set(True)
    try:
        yield
    finally:
        _OPERATION_WRITE_ALLOWED.reset(token)
        barrier.leave_file_operation()


# A transaction-end listener releases the writer slot even when a service
# raises, rolls back or closes without an explicit commit.  The session stores
# only the barrier object, never business content.
@event.listens_for(Session, "after_transaction_end")
def _after_transaction_end(session: Session, transaction) -> None:  # noqa: ANN001
    if getattr(transaction, "parent", None) is not None:
        return
    barrier = session.info.pop("_kgm_backup_barrier", None)
    if barrier is not None:
        barrier.leave_db_write()
