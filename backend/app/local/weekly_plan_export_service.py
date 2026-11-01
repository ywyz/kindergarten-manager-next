"""Weekly-plan Word export service (G2a D scope).

Preview is ephemeral memory only. Create/retry persist a frozen manifest,
token and operation receipt in the final short transaction. Native attempt
metadata is reported separately; HTTP generation is never ``saved``.
"""

from __future__ import annotations

import copy
import ctypes
import msvcrt
import hashlib
import json
import ntpath
import os
import re
import stat
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Literal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ids import new_opaque_id
from app.local import backup_barrier
from app.local import backup_fs
from app.local import weekly_plan_content
from app.local import weekly_plan_operations as operations
from app.local import weekly_plan_service
from app.local import weekly_plan_snapshot as snapshots
from app.local import weekly_plan_tokens as tokens
from app.local.errors import (
    LocalWeeklyAckRequired,
    LocalWeeklyConfirmationNotFound,
    LocalWeeklyExportConflict,
    LocalWeeklyExportNotFound,
    LocalWeeklyExportUnavailable,
    LocalWeeklyInvalid,
    LocalWeeklyOperationNotFound,
    LocalWeeklyPreviewExpired,
    LocalWeeklyPreviewStale,
)
from app.local.models import (
    LocalWeeklyExportAttempt,
    LocalWeeklyExportSnapshot,
    LocalWeeklyExportToken,
    LocalWeeklyPlan,
    LocalWeeklyPlanConfirmation,
    LocalWeeklyPlanContent,
    LocalWeeklyPlanOperation,
)
from app.local.normalize import normalize_request_id
from app.local.tx import begin_immediate, read_scope, rollback
from app.services import word_export_mapping as mapping
from app.services.word_export_docx import generate_weekly_export_docx
PREVIEW_TTL_SECONDS = 600
TOKEN_TTL_SECONDS = 600
MAX_SELECTION = 8
MAX_DOCX_BYTES = 128 * 1024 * 1024
WORK_DIR_NAME = ".weekly-export-work"
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_ARTIFACT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_CONTROL = set(chr(i) for i in range(32)) | {"\x7f"}
_INVALID_FILENAME_CHARS = set('<>:"/\\|?*')
_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *[f"COM{i}" for i in range(1, 10)],
    *[f"LPT{i}" for i in range(1, 10)],
}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _filename(value: Any) -> str:
    if not isinstance(value, str):
        raise LocalWeeklyInvalid("filename 必须是字符串")
    name = value
    if (
        not name
        or name != name.strip()
        or name in (".", "..")
        or len(name) > 200
        or any(char in _CONTROL or char in _INVALID_FILENAME_CHARS for char in name)
        or name.endswith(" ")
        or name.endswith(".")
        or ntpath.isreserved(name)
    ):
        raise LocalWeeklyInvalid("filename 不合法")
    if not name.lower().endswith(".docx"):
        raise LocalWeeklyInvalid("filename 必须是 .docx 文件")
    return name


def _fingerprint_name(name: str) -> str:
    return hashlib.sha256(name.encode("utf-8")).hexdigest()
class _LeasedFile:
    def __init__(self, lease):
        self.lease = lease
        self.handle = os.fdopen(lease.fd, "rb", closefd=True)
        lease.fd = None
        lease.handle = None

    def read(self, size: int = -1) -> bytes:
        return self.handle.read(size)

    def seek(self, offset: int) -> int:
        return self.handle.seek(offset)

    def fileno(self) -> int:
        return self.handle.fileno()

    @property
    def closed(self) -> bool:
        return self.handle.closed

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        self.handle.close()
        self.lease.close()


def _open_verified(path: Path, identity: tuple[int, int], root: Path):
    try:
        lease = backup_fs.FileLease(path, expected=path, root=root)
        lease.__enter__()
    except BaseException:
        raise LocalWeeklyExportUnavailable() from None
    try:
        if lease.identity is None or lease.identity[:2] != identity:
            raise LocalWeeklyExportUnavailable()
        return _LeasedFile(lease)
    except BaseException:
        lease.close()
        raise


_DELETE = 0x00010000
_FILE_SHARE_READ_WRITE = 0x00000003
_OPEN_EXISTING = 3
_FILE_ATTRIBUTE_NORMAL = 0x00000080
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_INVALID_HANDLE = ctypes.c_void_p(-1).value


class _FILE_DISPOSITION_INFO(ctypes.Structure):
    _fields_ = [("DeleteFile", ctypes.c_ubyte)]


def _delete_handle(path: Path, identity: tuple[int, int], root: Path) -> bool:
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateFileW.argtypes = [
        ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
        ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
    ]
    kernel32.CreateFileW.restype = ctypes.c_void_p
    kernel32.SetFileInformationByHandle.argtypes = [
        ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32,
    ]
    kernel32.SetFileInformationByHandle.restype = ctypes.c_int
    handle = kernel32.CreateFileW(
        str(path), _DELETE, _FILE_SHARE_READ_WRITE, None, _OPEN_EXISTING,
        _FILE_ATTRIBUTE_NORMAL | _FILE_FLAG_OPEN_REPARSE_POINT, None,
    )
    if handle in (None, _INVALID_HANDLE):
        return False
    fd = None
    try:
        info = backup_fs._handle_info(handle)
        if (
            info.dwFileAttributes & backup_fs.FILE_ATTRIBUTE_DIRECTORY
            or info.dwFileAttributes & backup_fs.FILE_ATTRIBUTE_REPARSE_POINT
            or info.nNumberOfLinks != 1
            or (info.nFileIndexHigh == 0 and info.nFileIndexLow == 0)
        ):
            return False
        final = backup_fs._final_path(handle)
        if backup_fs._normalized(final) != backup_fs._normalized(path):
            return False
        try:
            final.relative_to(root)
        except ValueError:
            return False
        fd = msvcrt.open_osfhandle(
            int(handle), os.O_RDONLY | getattr(os, "O_BINARY", 0)
        )
        stat_info = os.fstat(fd)
        if (int(stat_info.st_dev), int(stat_info.st_ino)) != identity:
            return False
        disposition = _FILE_DISPOSITION_INFO(1)
        if not kernel32.SetFileInformationByHandle(
            ctypes.c_void_p(handle), 4, ctypes.byref(disposition),
            ctypes.sizeof(disposition)
        ):
            return False
        return True
    except BaseException:
        return False
    finally:
        if fd is not None:
            os.close(fd)
        else:
            backup_fs._close_handle(handle)
def _unlink_verified(path: Path, identity: tuple[int, int], root: Path) -> None:
    try:
        with backup_fs.DirectoryGuard(root):
            _delete_handle(path, identity, root)
    except BaseException:
        return
def _write_owned(path: Path, data: bytes, root: Path) -> tuple[int, int]:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        raise LocalWeeklyExportConflict() from None
    except OSError:
        raise LocalWeeklyExportUnavailable() from None
    identity = None
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
            st = os.fstat(handle.fileno())
            identity = (int(st.st_dev), int(st.st_ino))
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        raise
    if identity is None:
        raise LocalWeeklyExportUnavailable()
    return identity


@dataclass
class OwnedTempRead:
    manager: Any
    token: str
    path: Path
    handle: Any
    size: int
    identity: tuple[int, int]
    owner: str

    def read(self, size: int = -1) -> bytes:
        fd = self.handle.fd
        if fd is None:
            raise ValueError("I/O operation on closed file")
        if size == 0:
            return b""
        if size < 0:
            chunks = []
            while True:
                chunk = os.read(fd, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            return b"".join(chunks)
        return os.read(fd, size)

    def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
        fd = self.handle.fd
        if fd is None:
            raise ValueError("I/O operation on closed file")
        return os.lseek(fd, offset, whence)

    def tell(self) -> int:
        fd = self.handle.fd
        if fd is None:
            raise ValueError("I/O operation on closed file")
        return os.lseek(fd, 0, os.SEEK_CUR)

    def seekable(self) -> bool:
        return True

    def fileno(self) -> int:
        fd = self.handle.fd
        if fd is None:
            raise ValueError("I/O operation on closed file")
        return fd

    def close(self) -> None:
        self.manager.release_owned_temp(self.token)


@dataclass
class OwnedTemp:
    manager: Any
    token: str
    path: Path
    handle: Any
    owner: str

    def finish(self) -> OwnedTempRead:
        return self.manager.finish_owned_temp(self.token)

    def abort(self) -> None:
        self.manager.abort_owned_temp(self.token)
class WeeklyExportManager:
    """Per-runtime export lifecycle, preview cache and owned work artifacts."""

    def __init__(self, runtime: Any, *, launch_id: str, session_scope: str) -> None:
        self.runtime = runtime
        self.launch_id = str(launch_id)
        self.session_scope = str(session_scope)
        self.session_scope_hash = tokens.scope_hash(self.session_scope)
        self.work_root = Path(runtime.weekly_export_work_root)
        self._barrier = backup_barrier.get_barrier(runtime.data_dir)
        self._cond = threading.Condition(threading.RLock())
        self._closed = False
        self._owners: set[str] = set()
        self._epoch = 0
        self._active = 0
        self._previews: dict[str, dict] = {}
        self._artifacts: dict[str, dict] = {}
        self._aliases: dict[str, str] = {}
        self._temps: dict[str, dict] = {}
        self._root_guard = None

    @property
    def is_closed(self) -> bool:
        with self._cond:
            return self._closed

    @property
    def epoch(self) -> int:
        with self._cond:
            return self._epoch

    def _check_binding(self, launch_id: str, session_scope: str) -> None:
        if str(launch_id) != self.launch_id or str(session_scope) != self.session_scope:
            raise LocalWeeklyExportConflict()

    def _check_open_locked(self) -> None:
        if self._closed or self._owners:
            raise LocalWeeklyExportUnavailable()
        if self._barrier.intent_owner is not None or self._barrier.exclusive_owner is not None:
            raise LocalWeeklyExportUnavailable()
    def pause(self, *, owner: str) -> None:
        if not isinstance(owner, str) or not owner:
            raise LocalWeeklyExportConflict()
        with self._cond:
            if self._closed or owner in self._owners:
                return
            self._owners.add(owner)
            self._epoch += 1
            self._previews.clear()
            self._cond.notify_all()

    def resume(self, *, owner: str) -> None:
        with self._cond:
            if owner in self._owners:
                self._owners.discard(owner)
                self._cond.notify_all()

    def close(self) -> None:
        with self._cond:
            if self._closed:
                return
            self._closed = True
            self._epoch += 1
            self._previews.clear()
            for artifact_id in list(self._artifacts):
                entry = self._artifacts.get(artifact_id)
                if entry is None:
                    continue
                if entry["refs"] == 0:
                    self._delete_entry_locked(artifact_id)
                else:
                    entry["pending"] = True
            for token, entry in list(self._temps.items()):
                if (
                    entry.get("handle") is not None
                    or entry.get("lease") is not None
                    or entry.get("refs", 0) > 0
                ):
                    entry["pending"] = True
                else:
                    self._delete_temp_locked(token)
            self._maybe_release_root_guard_locked()
            self._cond.notify_all()

    def _temp_active(self, entry: dict) -> bool:
        return (
            entry.get("handle") is not None
            or entry.get("lease") is not None
            or entry.get("refs", 0) > 0
        )

    def _maybe_release_root_guard_locked(self) -> None:
        if not self._closed or self._root_guard is None:
            return
        if self._active > 0:
            return
        if any(entry["refs"] > 0 for entry in self._artifacts.values()):
            return
        if any(self._temp_active(entry) for entry in self._temps.values()):
            return
        guard = self._root_guard
        self._root_guard = None
        guard.close()

    def wait_idle(self, *, timeout: float = 60.0, cancel: threading.Event | None = None) -> bool:
        if cancel is not None and not isinstance(cancel, threading.Event):
            return False
        deadline = time.monotonic() + max(0.0, float(timeout))
        with self._cond:
            while (
                self._active > 0
                or any(entry["refs"] > 0 for entry in self._artifacts.values())
                or any(
                    entry.get("handle") is not None
                    or entry.get("lease") is not None
                    or entry.get("refs", 0) > 0
                    for entry in self._temps.values()
                )
            ):
                if cancel is not None and cancel.is_set():
                    return False
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._cond.wait(min(0.1, remaining))
            return True
    def put_preview(self, token_hash: str, payload: dict) -> None:
        with self._cond:
            if self._closed or self._owners:
                raise LocalWeeklyExportUnavailable()
            self._previews[token_hash] = payload

    def take_preview(self, token_hash: str) -> dict | None:
        with self._cond:
            payload = self._previews.get(token_hash)
            return copy.deepcopy(payload) if payload is not None else None

    def drop_preview(self, token_hash: str) -> None:
        with self._cond:
            self._previews.pop(token_hash, None)

    def clear_previews(self) -> None:
        with self._cond:
            self._previews.clear()

    @contextmanager
    def activity(self, *, kind: Literal["preview", "generate", "download", "native", "receipt"], launch_id: str, session_scope: str) -> Iterator[int]:
        if kind not in ("preview", "generate", "download", "native", "receipt"):
            raise LocalWeeklyExportConflict()
        self._check_binding(launch_id, session_scope)
        with self._cond:
            self._check_open_locked()
            self._active += 1
            epoch = self._epoch
        file_scope = None
        entered = False
        download_barrier = False
        try:
            if kind in ("generate", "native"):
                file_scope = backup_barrier.file_scope(self.runtime.data_dir)
                file_scope.__enter__()
                entered = True
            elif kind == "download":
                self._barrier.enter_file_operation()
                download_barrier = True
            yield epoch
        finally:
            if entered and file_scope is not None:
                file_scope.__exit__(None, None, None)
            if download_barrier:
                self._barrier.leave_file_operation()
            with self._cond:
                self._active = max(0, self._active - 1)
                self._maybe_release_root_guard_locked()
                self._cond.notify_all()

    @contextmanager
    def publish(self, *, epoch: int, launch_id: str, session_scope: str) -> Iterator[None]:
        self._check_binding(launch_id, session_scope)
        with self._cond:
            if self._closed or self._owners or int(epoch) != self._epoch:
                raise LocalWeeklyExportConflict()
            if self._barrier.intent_owner is not None or self._barrier.exclusive_owner is not None:
                raise LocalWeeklyExportConflict()
            yield
    def ensure_work_root(self) -> Path:
        root = self.work_root
        with self._cond:
            if self._root_guard is not None:
                return root
            try:
                if not root.exists():
                    with backup_fs.DirectoryGuard(root.parent):
                        try:
                            root.mkdir()
                        except FileExistsError:
                            pass
                guard = backup_fs.DirectoryGuard(root)
                guard.__enter__()
                self._root_guard = guard
            except BaseException:
                raise LocalWeeklyExportUnavailable() from None
            return root

    def create_artifact(self, artifact_id: str, token_hash: str, docx_data: bytes, meta_payload: dict, *, expires_at: datetime, snapshot_id: str, manifest_hash: str) -> dict:
        root = self.ensure_work_root()
        docx_path, meta_path = _artifact_paths(root, artifact_id)
        meta_data = json.dumps(meta_payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        docx_identity = None
        meta_identity = None
        try:
            docx_identity = _write_owned(docx_path, docx_data, root)
            meta_identity = _write_owned(meta_path, meta_data, root)
            with self._cond:
                if self._closed or self._owners:
                    raise LocalWeeklyExportUnavailable()
                if artifact_id in self._artifacts or token_hash in self._aliases:
                    raise LocalWeeklyExportConflict()
                entry = {
                    "artifact_id": artifact_id,
                    "docx": docx_path,
                    "meta": meta_path,
                    "docx_identity": docx_identity,
                    "meta_identity": meta_identity,
                    "refs": 0,
                    "aliases": {token_hash: expires_at},
                    "pending": False,
                    "protected": False,
                    "downloaded": False,
                    "expires_at": expires_at,
                    "snapshot_id": snapshot_id,
                    "manifest_hash": manifest_hash,
                    "byte_size": len(docx_data),
                    "artifact_hash": _sha(docx_data),
                }
                self._artifacts[artifact_id] = entry
                self._aliases[token_hash] = artifact_id
                return self._entry_copy(entry)
        except BaseException:
            if docx_identity is not None:
                _unlink_verified(docx_path, docx_identity, root)
            if meta_identity is not None:
                _unlink_verified(meta_path, meta_identity, root)
            raise
    @staticmethod
    def _entry_copy(entry: dict) -> dict:
        return {
            **{key: value for key, value in entry.items() if key != "aliases"},
            "aliases": dict(entry["aliases"]),
        }

    def artifact_entry(self, token_hash: str) -> dict | None:
        with self._cond:
            artifact_id = self._aliases.get(token_hash)
            entry = self._artifacts.get(artifact_id) if artifact_id else None
            return self._entry_copy(entry) if entry is not None else None

    def acquire_artifact(self, token_hash: str) -> dict:
        with self._cond:
            artifact_id = self._aliases.get(token_hash)
            entry = self._artifacts.get(artifact_id) if artifact_id else None
            if entry is None:
                raise LocalWeeklyExportNotFound()
            entry["refs"] += 1
            return self._entry_copy(entry)

    def open_artifact(self, token_hash: str):
        with self._cond:
            artifact_id = self._aliases.get(token_hash)
            entry = self._artifacts.get(artifact_id) if artifact_id else None
            if entry is None:
                raise LocalWeeklyExportNotFound()
            return _open_verified(entry["docx"], entry["docx_identity"], self.work_root)

    def read_artifact_meta(self, token_hash: str) -> dict:
        with self._cond:
            artifact_id = self._aliases.get(token_hash)
            entry = self._artifacts.get(artifact_id) if artifact_id else None
            if entry is None:
                raise LocalWeeklyExportNotFound()
            path = entry["meta"]
            identity = entry["meta_identity"]
        with _open_verified(path, identity, self.work_root) as handle:
            try:
                value = json.loads(handle.read().decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise LocalWeeklyExportUnavailable() from None
        if not isinstance(value, dict):
            raise LocalWeeklyExportUnavailable()
        return value
    def release_artifact_id(self, artifact_id: str) -> None:
        with self._cond:
            entry = self._artifacts.get(artifact_id)
            if entry is None:
                return
            entry["refs"] = max(0, entry["refs"] - 1)
            if entry["refs"] == 0 and (entry["pending"] or not entry["aliases"]):
                self._delete_entry_locked(artifact_id)
            self._maybe_release_root_guard_locked()
            self._cond.notify_all()

    def release_artifact(self, token_hash: str) -> None:
        with self._cond:
            artifact_id = self._aliases.get(token_hash)
        if artifact_id is not None:
            self.release_artifact_id(artifact_id)

    def discard_artifact(self, token_hash: str) -> None:
        with self._cond:
            artifact_id = self._aliases.pop(token_hash, None)
            if artifact_id is None:
                return
            entry = self._artifacts.get(artifact_id)
            if entry is None:
                return
            entry["aliases"].pop(token_hash, None)
            if entry["refs"] == 0 and not entry["aliases"]:
                self._delete_entry_locked(artifact_id)

    def alias_artifact(self, old_token_hash: str, new_token_hash: str, expires_at: datetime) -> bool:
        with self._cond:
            artifact_id = self._aliases.get(old_token_hash)
            entry = self._artifacts.get(artifact_id) if artifact_id else None
            if entry is None or new_token_hash in self._aliases:
                return False
            entry["aliases"][new_token_hash] = expires_at
            entry["expires_at"] = max(entry["expires_at"], expires_at)
            self._aliases[new_token_hash] = artifact_id
            return True

    def drop_alias(self, token_hash: str) -> None:
        self.discard_artifact(token_hash)
    def protect_artifact(self, token_hash: str, *, downloaded: bool = False) -> None:
        with self._cond:
            artifact_id = self._aliases.get(token_hash)
            entry = self._artifacts.get(artifact_id) if artifact_id else None
            if entry is None:
                return
            entry["protected"] = True
            if downloaded:
                entry["downloaded"] = True

    def cleanup_expired(self, now: datetime | None = None) -> None:
        stamp = now or _now()
        with self._cond:
            for artifact_id in list(self._artifacts):
                entry = self._artifacts.get(artifact_id)
                if entry is None or entry["protected"]:
                    continue
                for token_hash, expires_at in list(entry["aliases"].items()):
                    if stamp > expires_at:
                        entry["aliases"].pop(token_hash, None)
                        self._aliases.pop(token_hash, None)
                if entry["refs"] == 0 and not entry["aliases"]:
                    self._delete_entry_locked(artifact_id)

    def _delete_entry_locked(self, artifact_id: str) -> None:
        entry = self._artifacts.pop(artifact_id, None)
        if entry is None:
            return
        for token_hash in list(entry["aliases"]):
            self._aliases.pop(token_hash, None)
        _unlink_verified(entry["docx"], entry["docx_identity"], self.work_root)
        _unlink_verified(entry["meta"], entry["meta_identity"], self.work_root)
    def create_owned_temp(self, *, owner: str, suffix: str = ".docx") -> OwnedTemp:
        if not isinstance(owner, str) or not owner or suffix not in (".docx", ".tmp"):
            raise LocalWeeklyExportConflict()
        with self._cond:
            self._check_open_locked()
            if self._active <= 0:
                raise LocalWeeklyExportUnavailable()
            root = self.ensure_work_root()
            token = new_opaque_id()
            path = root / f"tmp-{token}{suffix}"
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
            try:
                fd = os.open(path, flags, 0o600)
            except FileExistsError:
                raise LocalWeeklyExportConflict() from None
            except OSError:
                raise LocalWeeklyExportUnavailable() from None
            identity = None
            handle = None
            try:
                st = os.fstat(fd)
                identity = (int(st.st_dev), int(st.st_ino))
                handle = os.fdopen(fd, "wb")
                if self._closed or self._owners:
                    raise LocalWeeklyExportUnavailable()
                self._temps[token] = {
                    "path": path,
                    "identity": identity,
                    "handle": handle,
                    "lease": None,
                    "refs": 0,
                    "pending": False,
                    "finished": False,
                    "owner": owner,
                }
            except BaseException:
                if handle is not None:
                    try:
                        handle.close()
                    except OSError:
                        pass
                elif fd is not None:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                if identity is not None:
                    _unlink_verified(path, identity, root)
                raise
            return OwnedTemp(self, token, path, handle, owner)
    def finish_owned_temp(self, token: str) -> OwnedTempRead:
        with self._cond:
            entry = self._temps.get(token)
            if entry is None or entry["finished"] or entry["handle"] is None:
                raise LocalWeeklyExportNotFound()
            handle = entry["handle"]
            failure = None
            try:
                handle.flush()
                os.fsync(handle.fileno())
            except BaseException as error:
                failure = error
            try:
                handle.close()
            except BaseException as error:
                if failure is None:
                    failure = error
            if not handle.closed:
                self._cond.notify_all()
                if failure is not None:
                    raise failure
                raise LocalWeeklyExportUnavailable()
            entry["handle"] = None
            if failure is not None:
                self._delete_temp_locked(token)
                self._maybe_release_root_guard_locked()
                self._cond.notify_all()
                raise failure
            lease = None
            try:
                lease = backup_fs.FileLease(
                    entry["path"], expected=entry["path"], root=self.work_root
                )
                lease.__enter__()
                if lease.identity is None or lease.identity[:2] != entry["identity"]:
                    raise LocalWeeklyExportUnavailable()
            except BaseException:
                if lease is not None:
                    try:
                        lease.close()
                    except OSError:
                        pass
                self._delete_temp_locked(token)
                self._maybe_release_root_guard_locked()
                self._cond.notify_all()
                raise LocalWeeklyExportUnavailable() from None
            entry["lease"] = lease
            entry["refs"] = 1
            entry["finished"] = True
            self._cond.notify_all()
            return OwnedTempRead(
                self, token, entry["path"], lease, int(lease.size),
                entry["identity"], entry["owner"],
            )
    def release_owned_temp(self, token: str) -> None:
        with self._cond:
            entry = self._temps.get(token)
            if entry is None:
                return
            lease = entry.get("lease")
            entry["refs"] = 0
            failure = None
            if lease is not None:
                try:
                    lease.close()
                except BaseException as error:
                    if getattr(lease, "fd", None) is not None:
                        failure = error
                if getattr(lease, "fd", None) is None:
                    entry["lease"] = None
            if failure is not None:
                entry["pending"] = True
                self._cond.notify_all()
                raise failure
            if entry.get("handle") is None and entry.get("lease") is None:
                self._delete_temp_locked(token)
            self._maybe_release_root_guard_locked()
            self._cond.notify_all()

    def abort_owned_temp(self, token: str) -> None:
        with self._cond:
            entry = self._temps.get(token)
            if entry is None:
                return
            if entry.get("lease") is not None or entry.get("refs", 0) > 0:
                entry["pending"] = True
                self._cond.notify_all()
                return
            deleted = self._delete_temp_locked(token)
            self._maybe_release_root_guard_locked()
            self._cond.notify_all()
            if not deleted:
                raise LocalWeeklyExportUnavailable()
    def _close_temp_resources_locked(self, entry: dict) -> bool:
        unclosed = False
        lease = entry.get("lease")
        if lease is not None:
            try:
                lease.close()
            except BaseException:
                if getattr(lease, "fd", None) is not None:
                    unclosed = True
            if getattr(lease, "fd", None) is None:
                entry["lease"] = None
        handle = entry.get("handle")
        if handle is not None:
            try:
                handle.close()
            except BaseException:
                if not handle.closed:
                    unclosed = True
            if handle.closed:
                entry["handle"] = None
        return unclosed

    def _delete_temp_locked(self, token: str) -> bool:
        entry = self._temps.get(token)
        if entry is None:
            return True
        if self._close_temp_resources_locked(entry):
            entry["pending"] = True
            return False
        self._temps.pop(token, None)
        _unlink_verified(entry["path"], entry["identity"], self.work_root)
        self._maybe_release_root_guard_locked()
        return True

def _artifact_paths(root: Path, artifact_id: str) -> tuple[Path, Path]:
    if not isinstance(artifact_id, str) or not _ARTIFACT_ID_RE.match(artifact_id):
        raise LocalWeeklyInvalid("导出标识不合法")
    return root / f"{artifact_id}.docx", root / f"{artifact_id}.json"


def _write_artifact(
    manager: WeeklyExportManager,
    *,
    artifact_id: str,
    token_hash: str,
    data: bytes,
    snapshot_id: str,
    manifest_hash: str,
    expires_at: datetime,
) -> dict:
    if len(data) <= 0 or len(data) > MAX_DOCX_BYTES:
        raise LocalWeeklyExportUnavailable()
    digest = _sha(data)
    meta = {
        "schema_version": 1,
        "artifact_id": artifact_id,
        "snapshot_id": snapshot_id,
        "manifest_hash": manifest_hash,
        "artifact_hash": digest,
        "byte_size": len(data),
        "expires_at": _iso(expires_at),
        "created_at": _iso(_now()),
    }
    return manager.create_artifact(
        artifact_id,
        token_hash,
        data,
        meta,
        expires_at=expires_at,
        snapshot_id=snapshot_id,
        manifest_hash=manifest_hash,
    )
def _read_artifact_meta(
    manager: WeeklyExportManager,
    *,
    token_hash: str,
    snapshot_id: str,
    manifest_hash: str,
    now: datetime,
    allow_expired: bool = False,
) -> dict:
    entry = manager.acquire_artifact(token_hash)
    artifact_id = entry["artifact_id"]
    handle = None
    try:
        handle = manager.open_artifact(token_hash)
        meta = manager.read_artifact_meta(token_hash)
        if (
            not isinstance(meta.get("artifact_id"), str)
            or meta["artifact_id"] != entry["artifact_id"]
            or meta.get("snapshot_id") != snapshot_id
            or meta.get("manifest_hash") != manifest_hash
            or not isinstance(meta.get("artifact_hash"), str)
            or not _HASH_RE.match(meta["artifact_hash"])
            or type(meta.get("byte_size")) is not int
            or meta["byte_size"] <= 0
            or meta["byte_size"] > MAX_DOCX_BYTES
        ):
            raise LocalWeeklyExportUnavailable()
        if not allow_expired and now > entry["expires_at"]:
            raise LocalWeeklyExportNotFound()
        st = os.fstat(handle.fileno())
        if int(st.st_size) != meta["byte_size"]:
            raise LocalWeeklyExportUnavailable()
        handle.seek(0)
        digest = hashlib.sha256()
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        if digest.hexdigest() != meta["artifact_hash"]:
            raise LocalWeeklyExportUnavailable()
        return meta
    finally:
        if handle is not None:
            try:
                handle.close()
            except OSError:
                pass
        manager.release_artifact_id(artifact_id)
@dataclass
class ExportArtifact:
    handle: Any
    size: int
    digest: str
    expires_at: datetime
    token_hash: str
    _release: Any
    _complete: Any = None

    def complete(self) -> None:
        callback = self._complete
        self._complete = None
        if callback is not None:
            callback()

    def close(self) -> None:
        handle = self.handle
        self.handle = None
        if handle is not None:
            try:
                handle.close()
            except OSError:
                pass
        release = self._release
        self._release = None
        if release is not None:
            release()
def _operation_response(
    session: Session,
    manager: WeeklyExportManager | None,
    row: LocalWeeklyPlanOperation,
    now: datetime,
) -> dict:
    metadata = operations.validate_metadata(
        row.result_json,
        weekly_plan_id=row.weekly_plan_id,
        draft_id=row.result_draft_id,
        draft_version=row.result_draft_version,
        confirmation_id=row.result_confirmed_id,
        confirmation_version=row.result_confirmed_version,
        snapshot_id=row.result_snapshot_id,
        token_id=row.result_token_id,
    )
    snapshot_id = metadata["snapshot_id"]
    token_id = metadata["token_id"]
    if snapshot_id is None or token_id is None:
        raise LocalWeeklyExportNotFound()
    snapshot = session.get(LocalWeeklyExportSnapshot, snapshot_id)
    token = session.get(LocalWeeklyExportToken, token_id)
    if (
        snapshot is None
        or token is None
        or snapshot.profile_id != row.profile_id
        or token.profile_id != row.profile_id
        or token.snapshot_id != snapshot.id
        or row.result_snapshot_id != snapshot.id
        or row.result_token_id != token.id
    ):
        raise LocalWeeklyExportNotFound()
    base = {
        "operation_id": row.id,
        "request_id": row.request_id,
        "snapshot_id": snapshot.id,
        "manifest_hash": snapshot.manifest_hash,
        "expires_at": _iso(snapshot.expires_at),
    }
    if (
        manager is not None
        and not manager.is_closed
        and manager.launch_id == row.launch_id
        and manager.session_scope_hash == row.session_scope_hash
        and token.consumed_at is None
        and now <= token.expires_at
        and now <= snapshot.expires_at
    ):
        export_id = tokens.derive_export_id(
            manager.runtime,
            profile_id=row.profile_id,
            snapshot_id=snapshot.id,
            token_id=token.id,
            request_id=row.request_id,
            launch_id=row.launch_id,
            session_scope_hash=row.session_scope_hash,
        )
        if tokens.export_id_hash(export_id) == token.token_hash:
            base["generation_status"] = "generated"
            base["export_id"] = export_id
            return base
    base["generation_status"] = "transfer_expired"
    return base


def _load_confirmation(
    session: Session,
    *,
    profile_id: str,
    plan_id: str,
    confirmation_id: str,
) -> tuple[LocalWeeklyPlan, LocalWeeklyPlanConfirmation, dict, LocalWeeklyPlanContent]:
    plan = session.get(LocalWeeklyPlan, plan_id)
    if plan is None or plan.profile_id != profile_id:
        raise LocalWeeklyConfirmationNotFound()
    row = session.get(LocalWeeklyPlanConfirmation, confirmation_id)
    if row is None or row.weekly_plan_id != plan.id:
        raise LocalWeeklyConfirmationNotFound()
    snapshot = snapshots.validate_confirmation_snapshot(row.snapshot_json)
    content = session.get(LocalWeeklyPlanContent, snapshot["draft_id"])
    if (
        content is None
        or content.weekly_plan_id != plan.id
        or content.version != snapshot["draft_version"]
        or content.content_hash != snapshot["content_hash"]
        or snapshots.canonical_json(content.content_json)
        != snapshots.canonical_json(snapshot["content"])
        or row.version < 1
        or row.draft_id != snapshot["draft_id"]
        or row.draft_version != snapshot["draft_version"]
        or row.snapshot_hash != snapshots.snapshot_hash(snapshot)
        or snapshots.canonical_json(row.facts_json)
        != snapshots.canonical_json(snapshot["facts"])
        or hashlib.sha256(
            snapshots.canonical_json(row.facts_json).encode("utf-8")
        ).hexdigest()
        != row.facts_hash
        or snapshot["profile_id"] != plan.profile_id
        or snapshot["class_id"] != plan.class_id
        or snapshot["term_id"] != plan.term_id
        or snapshot["header"] != plan.header_json
        or snapshot["creation_context"]["week_anchor_date"]
        != plan.week_anchor_date.isoformat()
        or snapshot["creation_context"]["week_number_snapshot"]
        != plan.week_number_snapshot
        or snapshot["creation_context"]["term_start"]
        != plan.term_start_date.isoformat()
        or snapshot["creation_context"]["term_end"]
        != plan.term_end_date.isoformat()
        or snapshot["creation_context"]["calendar_revision_id"]
        != plan.calendar_revision_id
    ):
        raise LocalWeeklyExportNotFound()
    return plan, row, snapshot, content
def _copy_fact(fact: dict, *, weekly_plan_id: str, confirmation_id: str) -> dict:
    copied = copy.deepcopy(fact)
    details = dict(copied.get("details") or {})
    details["weekly_plan_id"] = weekly_plan_id
    details["confirmation_id"] = confirmation_id
    copied["details"] = details
    return copied


def _item_and_selection(
    plan: LocalWeeklyPlan,
    row: LocalWeeklyPlanConfirmation,
    snapshot: dict,
) -> tuple[dict, dict]:
    item = dict(snapshot)
    item["confirmation_id"] = row.id
    item["confirmation_version"] = row.version
    item["confirmation_hash"] = row.snapshot_hash
    creation = snapshot["creation_context"]
    selection = {
        "weekly_plan_id": snapshot["weekly_plan_id"],
        "confirmation_id": row.id,
        "confirmation_version": row.version,
        "draft_id": snapshot["draft_id"],
        "draft_version": snapshot["draft_version"],
        "content_hash": snapshot["content_hash"],
        "confirmation_hash": row.snapshot_hash,
        "week_anchor_date": creation["week_anchor_date"],
        "week_number": creation["week_number_snapshot"],
        "date_range": copy.deepcopy(snapshot["date_range"]),
    }
    return item, selection
def _resolve_single(
    session: Session,
    *,
    profile_id: str,
    weekly_plan_id: str,
    confirmation_id: str | None,
) -> list[tuple[LocalWeeklyPlan, LocalWeeklyPlanConfirmation, dict]]:
    plan = session.get(LocalWeeklyPlan, weekly_plan_id)
    if plan is None or plan.profile_id != profile_id:
        raise LocalWeeklyExportNotFound()
    chosen = confirmation_id or plan.current_confirmed_id
    if not isinstance(chosen, str) or not chosen:
        raise LocalWeeklyConfirmationNotFound()
    loaded = _load_confirmation(
        session,
        profile_id=profile_id,
        plan_id=plan.id,
        confirmation_id=chosen,
    )
    return [(loaded[0], loaded[1], loaded[2])]
def _teaching_days(snapshot: dict) -> list[date]:
    days = snapshot["content"]["calendar_basis"]["days"]
    return [
        date.fromisoformat(item["date"])
        for item in days
        if item["day_state"] == "teaching"
    ]


def _resolve_range(
    session: Session,
    *,
    profile_id: str,
    start_date: date,
    end_date: date,
) -> list[tuple[LocalWeeklyPlan, LocalWeeklyPlanConfirmation, dict]]:
    plans = session.scalars(
        select(LocalWeeklyPlan).where(LocalWeeklyPlan.profile_id == profile_id)
    ).all()
    found = []
    for plan in plans:
        if not plan.current_confirmed_id:
            continue
        loaded = _load_confirmation(
            session,
            profile_id=profile_id,
            plan_id=plan.id,
            confirmation_id=plan.current_confirmed_id,
        )
        if any(start_date <= day <= end_date for day in _teaching_days(loaded[2])):
            found.append((loaded[0], loaded[1], loaded[2]))
    found.sort(
        key=lambda item: (
            item[2]["creation_context"]["week_anchor_date"],
            item[2]["term_id"],
            item[2]["weekly_plan_id"],
        )
    )
    if not found:
        raise LocalWeeklyExportNotFound()
    if len(found) > MAX_SELECTION:
        raise LocalWeeklyInvalid("周导出最多 8 份")
    return found
def _build_manifest(
    *,
    session: Session,
    profile_id: str,
    mode: str,
    requested_range: dict | None,
    rows: list[tuple[LocalWeeklyPlan, LocalWeeklyPlanConfirmation, dict]],
) -> dict:
    items = []
    selection = []
    missing = []
    warnings = []
    for plan, row, snapshot in rows:
        item, selected = _item_and_selection(plan, row, snapshot)
        items.append(item)
        selection.append(selected)
        for fact in snapshot["facts"]["missing"]:
            missing.append(
                _copy_fact(fact, weekly_plan_id=row.weekly_plan_id, confirmation_id=row.id)
            )
        live = weekly_plan_service._live_snapshot(session, plan)
        live_facts = weekly_plan_content.build_facts(snapshot["content"], live)
        for fact in list(live_facts["stale_sources"]) + list(live_facts["warnings"]):
            warnings.append(
                _copy_fact(fact, weekly_plan_id=row.weekly_plan_id, confirmation_id=row.id)
            )
    manifest = {
        "schema_version": 1,
        "profile_id": profile_id,
        "mode": mode,
        "requested_range": requested_range,
        "selection": selection,
        "warnings_as_of": _iso(datetime.now(timezone.utc)),
        "missing": missing,
        "warnings": warnings,
        "items": items,
    }
    return snapshots.validate_export_manifest(manifest)

def preview_export(
    session: Session,
    manager: WeeklyExportManager,
    *,
    profile_id: str,
    mode: str,
    weekly_plan_id: str | None = None,
    confirmation_id: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict:
    if manager is None or manager.is_closed:
        raise LocalWeeklyExportUnavailable()
    if mode not in ("single", "range"):
        raise LocalWeeklyInvalid("mode 不合法")
    with manager.activity(
        kind="preview",
        launch_id=manager.launch_id,
        session_scope=manager.session_scope,
    ) as epoch:
        with read_scope(session):
            if mode == "single":
                if not isinstance(weekly_plan_id, str) or start_date is not None or end_date is not None:
                    raise LocalWeeklyInvalid("单份导出参数不合法")
                requested_range = None
                rows = _resolve_single(
                    session,
                    profile_id=profile_id,
                    weekly_plan_id=weekly_plan_id,
                    confirmation_id=confirmation_id,
                )
            else:
                if (
                    weekly_plan_id is not None
                    or confirmation_id is not None
                    or not isinstance(start_date, date)
                    or not isinstance(end_date, date)
                    or start_date > end_date
                ):
                    raise LocalWeeklyInvalid("范围导出参数不合法")
                requested_range = {
                    "start": start_date.isoformat(),
                    "end": end_date.isoformat(),
                }
                rows = _resolve_range(
                    session,
                    profile_id=profile_id,
                    start_date=start_date,
                    end_date=end_date,
                )
            manifest = _build_manifest(
                session=session,
                profile_id=profile_id,
                mode=mode,
                requested_range=requested_range,
                rows=rows,
            )
        manifest_hash = snapshots.snapshot_hash(manifest)
        now = _now()
        context_token = tokens.issue_token(
            manager.runtime,
            purpose="export",
            profile_id=profile_id,
            launch_id=manager.launch_id,
            session_scope_hash=manager.session_scope_hash,
            object_id=manifest_hash,
            target_hash=manifest_hash,
            ttl=PREVIEW_TTL_SECONDS,
        )
        expires_at = now + timedelta(seconds=PREVIEW_TTL_SECONDS)
        token_hash = tokens.token_hash(context_token)
        context = {
            "profile_id": profile_id,
            "mode": mode,
            "manifest": manifest,
            "manifest_hash": manifest_hash,
            "expires_at": expires_at,
        }
        with manager.publish(
            epoch=epoch,
            launch_id=manager.launch_id,
            session_scope=manager.session_scope,
        ):
            manager.put_preview(token_hash, context)
    return {
        "context_token": context_token,
        "manifest_hash": manifest_hash,
        "expires_at": _iso(expires_at),
        "selection": copy.deepcopy(manifest["selection"]),
        "items": copy.deepcopy(manifest["items"]),
        "missing": copy.deepcopy(manifest["missing"]),
        "warnings": copy.deepcopy(manifest["warnings"]),
        "warnings_as_of": manifest["warnings_as_of"],
        "suggested_filename": "周工作计划.docx",
    }
def _slot_view(slot: Any) -> dict | None:
    if not isinstance(slot, dict):
        return None
    return {
        "source_kind": slot.get("source_kind"),
        "name": slot.get("name") or "",
        "shared_objectives": slot.get("shared_objectives") or "",
        "guidance_points": slot.get("guidance_points") or "",
        "focus_guidance": slot.get("focus_guidance") or "",
    }


def _focus_view(focus: Any) -> dict | None:
    if not isinstance(focus, dict):
        return None
    return {
        "source_kind": focus.get("source_kind"),
        "context_kind": focus.get("context_kind"),
        "area": focus.get("area") or "",
        "name": focus.get("name") or "",
        "objectives": focus.get("objectives") or "",
        "guidance": focus.get("guidance") or "",
        "support_strategy": focus.get("support_strategy") or "",
    }


def _view_from_item(item: dict) -> dict:
    content = item["content"]
    creation = item["creation_context"]
    by_date = {
        row["date"]: row
        for row in content.get("deterministic") or []
        if isinstance(row, dict)
    }
    columns = []
    for frozen in item["columns"]:
        day = date.fromisoformat(frozen["date"])
        state = frozen["day_state"]
        if state == "teaching":
            row = by_date.get(frozen["date"]) or {}
            effective = row.get("effective") or {}
            source = row.get("source") or {}
            columns.append(
                {
                    "date": frozen["date"],
                    "weekday": day.isoweekday(),
                    "day_state": "teaching",
                    "holiday": False,
                    "outside_term": False,
                    "morning_talk_topic": effective.get("morning_talk_topic") or "",
                    "group_activity_theme": effective.get("group_activity_theme") or "",
                    "plan_state": row.get("plan_state"),
                    "source_missing": source.get("daily_plan_id") is None,
                }
            )
        else:
            outside = state == "outside_term"
            columns.append(
                {
                    "date": frozen["date"],
                    "weekday": day.isoweekday(),
                    "day_state": "rest",
                    "holiday": state == "rest",
                    "outside_term": outside,
                    "morning_talk_topic": "",
                    "group_activity_theme": "",
                    "plan_state": None,
                    "source_missing": False,
                }
            )
    header = dict(item["header"])
    header["theme"] = content.get("theme") or ""
    header["grade"] = mapping.grade_display(header.get("grade"))
    slots = content.get("outdoor_game_slots") or {}
    return {
        "kind": mapping.KIND_WEEKLY,
        "plan_id": item["weekly_plan_id"],
        "term_id": item["term_id"],
        "week_number": creation["week_number_snapshot"],
        "confirmed_version": item["confirmation_version"],
        "header": header,
        "date_range": {
            "start": date.fromisoformat(item["date_range"]["start"]),
            "end": date.fromisoformat(item["date_range"]["end"]),
        },
        "columns": columns,
        "outdoor_game_slots": {
            key: _slot_view(slots.get(key)) for key in mapping.OUTDOOR_SLOT_KEYS
        },
        "focus_area": _focus_view(content.get("focus_area")),
        "weekly_columns": {
            key: (content.get("weekly_columns") or {}).get(key) or ""
            for key in mapping.WEEKLY_COLUMN_KEYS
        },
        "materials": content.get("materials"),
        "warnings": list(item["facts"].get("warnings") or []),
    }
def _generate_docx(manifest: dict) -> bytes:
    views = [_view_from_item(item) for item in manifest["items"]]
    data = generate_weekly_export_docx(views)
    if not data or len(data) > MAX_DOCX_BYTES:
        raise LocalWeeklyExportUnavailable()
    return data
def create_export(
    session: Session,
    manager: WeeklyExportManager,
    *,
    profile_id: str,
    request_id: Any,
    context_token: Any,
    ack_missing: Any,
    launch_id: str,
    session_scope: str,
) -> tuple[dict, bool]:
    rid = normalize_request_id(request_id)
    if not isinstance(ack_missing, bool):
        raise LocalWeeklyInvalid("ack_missing 必须是布尔值")
    token_hash = tokens.token_hash(str(context_token))
    fingerprint = operations.fingerprint(
        "export_create",
        {
            "profile_id": profile_id,
            "context_token_hash": token_hash,
            "ack_missing": ack_missing,
        },
    )
    with read_scope(session):
        receipt = operations.find_receipt(
            session,
            profile_id=profile_id,
            request_id=rid,
            action="export_create",
            fingerprint=fingerprint,
        )
        if receipt is not None:
            return _operation_response(session, manager, receipt, _now()), False
    if manager is None or manager.is_closed:
        raise LocalWeeklyExportUnavailable()
    manager._check_binding(launch_id, session_scope)
    artifact_token_hash: str | None = None
    try:
        with manager.activity(
            kind="generate",
            launch_id=manager.launch_id,
            session_scope=manager.session_scope,
        ) as epoch:
            context = manager.take_preview(token_hash)
            if context is None or context.get("profile_id") != profile_id:
                raise LocalWeeklyPreviewExpired()
            manifest = snapshots.validate_export_manifest(context["manifest"])
            manifest_hash = context["manifest_hash"]
            if snapshots.snapshot_hash(manifest) != manifest_hash:
                raise LocalWeeklyPreviewStale()
            tokens.verify_token(
                manager.runtime,
                context_token,
                purpose="export",
                profile_id=profile_id,
                launch_id=manager.launch_id,
                session_scope_hash=manager.session_scope_hash,
                object_id=manifest_hash,
                target_hash=manifest_hash,
            )
            now = _now()
            if now > context["expires_at"]:
                raise LocalWeeklyPreviewExpired()
            if manifest["missing"] and not ack_missing:
                raise LocalWeeklyAckRequired(details={"reason": "missing"})
            data = _generate_docx(manifest)
            snapshot_id = new_opaque_id()
            token_id = new_opaque_id()
            export_id = tokens.derive_export_id(
                manager.runtime,
                profile_id=profile_id,
                snapshot_id=snapshot_id,
                token_id=token_id,
                request_id=rid,
                launch_id=manager.launch_id,
                session_scope_hash=manager.session_scope_hash,
            )
            artifact_token_hash = tokens.export_id_hash(export_id)
            expires_at = min(
                now + timedelta(seconds=TOKEN_TTL_SECONDS),
                context["expires_at"],
            )
            _write_artifact(
                manager,
                artifact_id=snapshot_id,
                token_hash=artifact_token_hash,
                data=data,
                snapshot_id=snapshot_id,
                manifest_hash=manifest_hash,
                expires_at=expires_at,
            )
            with manager.publish(
                epoch=epoch,
                launch_id=manager.launch_id,
                session_scope=manager.session_scope,
            ):
                begin_immediate(session)
                try:
                    replay = operations.find_receipt(
                        session,
                        profile_id=profile_id,
                        request_id=rid,
                        action="export_create",
                        fingerprint=fingerprint,
                    )
                    if replay is not None:
                        response = _operation_response(
                            session, manager, replay, _now()
                        )
                        rollback(session)
                        manager.discard_artifact(artifact_token_hash)
                        return response, False
                    now = _now()
                    if now > context["expires_at"]:
                        raise LocalWeeklyPreviewExpired()
                    if now > expires_at:
                        raise LocalWeeklyExportConflict()
                    if snapshots.snapshot_hash(manifest) != manifest_hash:
                        raise LocalWeeklyPreviewStale()
                    for selected in manifest["selection"]:
                        _plan, confirmation, fixed, _content = _load_confirmation(
                            session,
                            profile_id=profile_id,
                            plan_id=selected["weekly_plan_id"],
                            confirmation_id=selected["confirmation_id"],
                        )
                        if (
                            confirmation.version != selected["confirmation_version"]
                            or snapshots.snapshot_hash(fixed) != selected["confirmation_hash"]
                            or fixed["content_hash"] != selected["content_hash"]
                        ):
                            raise LocalWeeklyPreviewStale()
                    session.add(
                        LocalWeeklyExportSnapshot(
                            id=snapshot_id,
                            profile_id=profile_id,
                            launch_id=manager.launch_id,
                            session_scope_hash=manager.session_scope_hash,
                            manifest_json=manifest,
                            manifest_hash=manifest_hash,
                            created_at=now,
                            expires_at=expires_at,
                        )
                    )
                    session.add(
                        LocalWeeklyExportToken(
                            id=token_id,
                            snapshot_id=snapshot_id,
                            profile_id=profile_id,
                            token_hash=artifact_token_hash,
                            expires_at=expires_at,
                            consumed_at=None,
                            parent_attempt_id=None,
                            created_at=now,
                        )
                    )
                    session.flush()
                    metadata = {
                        "schema_version": 1,
                        "weekly_plan_id": None,
                        "draft_id": None,
                        "draft_version": None,
                        "confirmation_id": None,
                        "confirmation_version": None,
                        "snapshot_id": snapshot_id,
                        "token_id": token_id,
                    }
                    operation = operations.store_receipt(
                        session,
                        profile_id=profile_id,
                        request_id=rid,
                        action="export_create",
                        fingerprint=fingerprint,
                        result=metadata,
                        result_snapshot_id=snapshot_id,
                        result_token_id=token_id,
                        launch_id=manager.launch_id,
                        session_scope_hash=manager.session_scope_hash,
                    )
                    response = _operation_response(session, manager, operation, _now())
                    session.commit()
                    return response, True
                except BaseException:
                    rollback(session)
                    manager.discard_artifact(artifact_token_hash)
                    raise
    except BaseException:
        if artifact_token_hash is not None:
            manager.discard_artifact(artifact_token_hash)
        raise
def read_export_content(
    session: Session,
    manager: WeeklyExportManager,
    *,
    profile_id: str,
    export_id: Any,
    launch_id: str,
    session_scope: str,
) -> ExportArtifact:
    if manager is None or manager.is_closed:
        raise LocalWeeklyExportUnavailable()
    manager._check_binding(launch_id, session_scope)
    token_hash = tokens.export_id_hash(str(export_id))
    now = _now()
    activity = manager.activity(
        kind="download",
        launch_id=manager.launch_id,
        session_scope=manager.session_scope,
    )
    activity.__enter__()
    handle = None
    acquired = False
    try:
        with read_scope(session):
            token = session.scalars(
                select(LocalWeeklyExportToken).where(
                    LocalWeeklyExportToken.token_hash == token_hash
                )
            ).first()
            if token is None or token.profile_id != profile_id:
                raise LocalWeeklyExportNotFound()
            snapshot = session.get(LocalWeeklyExportSnapshot, token.snapshot_id)
            if (
                snapshot is None
                or snapshot.profile_id != profile_id
                or snapshot.launch_id != manager.launch_id
                or snapshot.session_scope_hash != manager.session_scope_hash
                or token.consumed_at is not None
                or now > token.expires_at
                or now > snapshot.expires_at
            ):
                raise LocalWeeklyExportNotFound()
            operation = session.scalars(
                select(LocalWeeklyPlanOperation).where(
                    LocalWeeklyPlanOperation.profile_id == profile_id,
                    LocalWeeklyPlanOperation.result_token_id == token.id,
                    LocalWeeklyPlanOperation.action.in_(
                        ("export_create", "export_retry")
                    ),
                )
            ).first()
            if operation is None:
                raise LocalWeeklyExportNotFound()
            snapshot_id = snapshot.id
            manifest_hash = snapshot.manifest_hash
            expires_at = min(token.expires_at, snapshot.expires_at)
        entry = manager.acquire_artifact(token_hash)
        acquired = True
        handle = manager.open_artifact(token_hash)
        meta = manager.read_artifact_meta(token_hash)
        if (
            meta.get("artifact_id") != entry["artifact_id"]
            or meta.get("snapshot_id") != snapshot_id
            or meta.get("manifest_hash") != manifest_hash
            or not isinstance(meta.get("artifact_hash"), str)
            or not _HASH_RE.match(meta["artifact_hash"])
            or type(meta.get("byte_size")) is not int
            or meta["byte_size"] <= 0
            or meta["byte_size"] > MAX_DOCX_BYTES
            or meta["byte_size"] != entry["byte_size"]
            or meta["artifact_hash"] != entry["artifact_hash"]
        ):
            raise LocalWeeklyExportUnavailable()
        st = os.fstat(handle.fileno())
        if int(st.st_size) != meta["byte_size"]:
            raise LocalWeeklyExportUnavailable()
        handle.seek(0)
        digest = hashlib.sha256()
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        if digest.hexdigest() != meta["artifact_hash"]:
            raise LocalWeeklyExportUnavailable()
        handle.seek(0)

        artifact_id = entry["artifact_id"]

        def release() -> None:
            try:
                manager.release_artifact_id(artifact_id)
            finally:
                activity.__exit__(None, None, None)

        return ExportArtifact(
            handle=handle,
            size=meta["byte_size"],
            digest=meta["artifact_hash"],
            expires_at=expires_at,
            token_hash=token_hash,
            _release=release,
            _complete=lambda: manager.protect_artifact(token_hash, downloaded=True),
        )
    except BaseException:
        if handle is not None:
            try:
                handle.close()
            except OSError:
                pass
        if acquired:
            manager.release_artifact_id(entry["artifact_id"])
        activity.__exit__(None, None, None)
        raise
def _attempt_payload(
    attempt: LocalWeeklyExportAttempt,
    *,
    filename: str,
    should_prompt: bool,
) -> dict:
    return {
        "attempt_id": attempt.id,
        "status": attempt.status,
        "filename": filename,
        "should_prompt": should_prompt,
        "byte_size": attempt.byte_size,
        "result_hash": attempt.result_hash,
        "started_at": _iso(attempt.started_at),
        "ended_at": _iso(attempt.ended_at) if attempt.ended_at else None,
    }


def _attempt_lookup(
    session: Session, *, profile_id: str, export_id: Any
) -> tuple[LocalWeeklyExportToken, LocalWeeklyExportSnapshot]:
    token_hash = tokens.export_id_hash(str(export_id))
    token = session.scalars(
        select(LocalWeeklyExportToken).where(
            LocalWeeklyExportToken.token_hash == token_hash
        )
    ).first()
    if token is None or token.profile_id != profile_id:
        raise LocalWeeklyExportNotFound()
    snapshot = session.get(LocalWeeklyExportSnapshot, token.snapshot_id)
    if snapshot is None or snapshot.profile_id != profile_id:
        raise LocalWeeklyExportNotFound()
    return token, snapshot
def start_attempt(
    session: Session,
    manager: WeeklyExportManager,
    *,
    profile_id: str,
    export_id: Any,
    filename: Any,
    launch_id: str,
    session_scope: str,
) -> dict:
    if manager is None or manager.is_closed:
        raise LocalWeeklyExportUnavailable()
    manager._check_binding(launch_id, session_scope)
    name = _filename(filename)
    fingerprint = _fingerprint_name(name)
    export_hash = tokens.export_id_hash(str(export_id))
    with manager.activity(
        kind="native",
        launch_id=manager.launch_id,
        session_scope=manager.session_scope,
    ) as epoch:
        with read_scope(session):
            token, snapshot = _attempt_lookup(
                session, profile_id=profile_id, export_id=export_id
            )
            existing = session.scalars(
                select(LocalWeeklyExportAttempt).where(
                    LocalWeeklyExportAttempt.profile_id == profile_id,
                    LocalWeeklyExportAttempt.export_id_hash == export_hash,
                )
            ).first()
            if existing is not None:
                if existing.filename_fingerprint != fingerprint:
                    raise LocalWeeklyExportConflict()
                return _attempt_payload(
                    existing, filename=name, should_prompt=False
                )
            now = _now()
            if (
                token.consumed_at is not None
                or now > token.expires_at
                or now > snapshot.expires_at
                or snapshot.launch_id != manager.launch_id
                or snapshot.session_scope_hash != manager.session_scope_hash
            ):
                raise LocalWeeklyExportConflict()
        with manager.publish(
            epoch=epoch,
            launch_id=manager.launch_id,
            session_scope=manager.session_scope,
        ):
            begin_immediate(session)
            try:
                token, snapshot = _attempt_lookup(
                    session, profile_id=profile_id, export_id=export_id
                )
                existing = session.scalars(
                    select(LocalWeeklyExportAttempt).where(
                        LocalWeeklyExportAttempt.profile_id == profile_id,
                        LocalWeeklyExportAttempt.export_id_hash == export_hash,
                    )
                ).first()
                if existing is not None:
                    if existing.filename_fingerprint != fingerprint:
                        raise LocalWeeklyExportConflict()
                    result = _attempt_payload(
                        existing, filename=name, should_prompt=False
                    )
                    rollback(session)
                    return result
                now = _now()
                if (
                    token.consumed_at is not None
                    or now > token.expires_at
                    or now > snapshot.expires_at
                    or snapshot.launch_id != manager.launch_id
                    or snapshot.session_scope_hash != manager.session_scope_hash
                ):
                    raise LocalWeeklyExportConflict()
                attempt = LocalWeeklyExportAttempt(
                    id=new_opaque_id(),
                    profile_id=profile_id,
                    snapshot_id=token.snapshot_id,
                    token_id=token.id,
                    export_id_hash=export_hash,
                    filename_fingerprint=fingerprint,
                    status="in_progress",
                    result_hash=None,
                    byte_size=0,
                    started_at=now,
                    ended_at=None,
                    created_at=now,
                )
                session.add(attempt)
                session.flush()
                result = _attempt_payload(attempt, filename=name, should_prompt=True)
                session.commit()
                manager.protect_artifact(export_hash)
                return result
            except BaseException:
                rollback(session)
                raise

def read_latest_attempt(
    session: Session,
    *,
    profile_id: str,
    export_id: Any,
    filename: Any,
) -> dict:
    name = _filename(filename)
    fingerprint = _fingerprint_name(name)
    export_hash = tokens.export_id_hash(str(export_id))
    with read_scope(session):
        attempt = session.scalars(
            select(LocalWeeklyExportAttempt)
            .where(
                LocalWeeklyExportAttempt.profile_id == profile_id,
                LocalWeeklyExportAttempt.export_id_hash == export_hash,
            )
            .order_by(
                LocalWeeklyExportAttempt.started_at.desc(),
                LocalWeeklyExportAttempt.id.desc(),
            )
            .limit(1)
        ).first()
        if attempt is None:
            raise LocalWeeklyExportNotFound()
        if attempt.filename_fingerprint != fingerprint:
            raise LocalWeeklyExportConflict()
        return _attempt_payload(attempt, filename=name, should_prompt=False)
def finish_attempt(
    session: Session,
    manager: WeeklyExportManager,
    *,
    profile_id: str,
    export_id: Any,
    attempt_id: Any,
    filename: Any,
    status: Any,
    byte_size: Any,
    result_hash: Any,
    launch_id: str,
    session_scope: str,
) -> dict:
    if manager is None or manager.is_closed:
        raise LocalWeeklyExportUnavailable()
    manager._check_binding(launch_id, session_scope)
    if status not in ("saved", "cancelled", "failed", "indeterminate"):
        raise LocalWeeklyExportConflict()
    if not isinstance(attempt_id, str) or not attempt_id:
        raise LocalWeeklyExportConflict()
    name = _filename(filename)
    fingerprint = _fingerprint_name(name)
    export_hash = tokens.export_id_hash(str(export_id))
    if not isinstance(byte_size, int) or isinstance(byte_size, bool) or byte_size < 0:
        raise LocalWeeklyExportConflict()
    if status == "saved":
        if byte_size <= 0 or not isinstance(result_hash, str) or not _HASH_RE.match(result_hash):
            raise LocalWeeklyExportConflict()
    elif byte_size != 0 or result_hash is not None:
        raise LocalWeeklyExportConflict()
    with manager.activity(
        kind="receipt",
        launch_id=manager.launch_id,
        session_scope=manager.session_scope,
    ) as epoch:
        with read_scope(session):
            token, snapshot = _attempt_lookup(
                session, profile_id=profile_id, export_id=export_id
            )
            if (
                snapshot.launch_id != manager.launch_id
                or snapshot.session_scope_hash != manager.session_scope_hash
            ):
                raise LocalWeeklyExportConflict()
            attempt = session.get(LocalWeeklyExportAttempt, attempt_id)
            if (
                attempt is None
                or attempt.profile_id != profile_id
                or attempt.export_id_hash != export_hash
                or attempt.snapshot_id != token.snapshot_id
                or attempt.token_id != token.id
                or attempt.filename_fingerprint != fingerprint
            ):
                raise LocalWeeklyExportNotFound()
            if attempt.status != "in_progress":
                if (
                    attempt.status == status
                    and attempt.byte_size == byte_size
                    and attempt.result_hash == result_hash
                ):
                    return _attempt_payload(
                        attempt, filename=name, should_prompt=False
                    )
                raise LocalWeeklyExportConflict()
            if status == "saved":
                meta = _read_artifact_meta(
                    manager,
                    token_hash=export_hash,
                    snapshot_id=snapshot.id,
                    manifest_hash=snapshot.manifest_hash,
                    now=_now(),
                    allow_expired=True,
                )
                if (
                    meta["artifact_hash"] != result_hash
                    or meta["byte_size"] != byte_size
                ):
                    raise LocalWeeklyExportConflict()
        with manager.publish(
            epoch=epoch,
            launch_id=manager.launch_id,
            session_scope=manager.session_scope,
        ):
            begin_immediate(session)
            try:
                token, snapshot = _attempt_lookup(
                    session, profile_id=profile_id, export_id=export_id
                )
                attempt = session.get(LocalWeeklyExportAttempt, attempt_id)
                if (
                    attempt is None
                    or attempt.profile_id != profile_id
                    or attempt.export_id_hash != export_hash
                    or attempt.snapshot_id != token.snapshot_id
                    or attempt.token_id != token.id
                    or attempt.filename_fingerprint != fingerprint
                ):
                    raise LocalWeeklyExportNotFound()
                if attempt.status != "in_progress":
                    if (
                        attempt.status == status
                        and attempt.byte_size == byte_size
                        and attempt.result_hash == result_hash
                    ):
                        result = _attempt_payload(
                            attempt, filename=name, should_prompt=False
                        )
                        rollback(session)
                        return result
                    raise LocalWeeklyExportConflict()
                if token.consumed_at is not None:
                    raise LocalWeeklyExportConflict()
                now = _now()
                attempt.status = status
                attempt.byte_size = byte_size
                attempt.result_hash = result_hash
                attempt.ended_at = now
                token.consumed_at = now
                session.flush()
                result = _attempt_payload(attempt, filename=name, should_prompt=False)
                session.commit()
                if status == "saved":
                    manager.discard_artifact(export_hash)
                return result
            except BaseException:
                rollback(session)
                raise
def retry_export(
    session: Session,
    manager: WeeklyExportManager,
    *,
    profile_id: str,
    request_id: Any,
    snapshot_id: Any,
    old_export_id: Any,
    attempt_id: Any,
    launch_id: str,
    session_scope: str,
) -> tuple[dict, bool]:
    rid = normalize_request_id(request_id)
    if not isinstance(attempt_id, str) or not attempt_id:
        raise LocalWeeklyExportConflict()
    old_hash = tokens.export_id_hash(str(old_export_id))
    fingerprint = operations.fingerprint(
        "export_retry",
        {
            "profile_id": profile_id,
            "snapshot_id": str(snapshot_id),
            "old_export_id_hash": old_hash,
            "attempt_id": attempt_id,
        },
    )
    with read_scope(session):
        receipt = operations.find_receipt(
            session,
            profile_id=profile_id,
            request_id=rid,
            action="export_retry",
            fingerprint=fingerprint,
        )
        if receipt is not None:
            return _operation_response(session, manager, receipt, _now()), False
    if manager is None or manager.is_closed:
        raise LocalWeeklyExportUnavailable()
    manager._check_binding(launch_id, session_scope)
    with read_scope(session):
        old_token, snapshot = _attempt_lookup(
            session, profile_id=profile_id, export_id=old_export_id
        )
        if snapshot.id != snapshot_id:
            raise LocalWeeklyExportConflict()
        old_attempt = session.get(LocalWeeklyExportAttempt, attempt_id)
        if (
            old_attempt is None
            or old_attempt.profile_id != profile_id
            or old_attempt.export_id_hash != old_hash
            or old_attempt.snapshot_id != snapshot.id
            or old_attempt.token_id != old_token.id
        ):
            raise LocalWeeklyExportNotFound()
        now = _now()
        if (
            old_attempt.status not in ("failed", "cancelled")
            or snapshot.launch_id != manager.launch_id
            or snapshot.session_scope_hash != manager.session_scope_hash
            or now > snapshot.expires_at
        ):
            raise LocalWeeklyExportConflict()
        successor = session.scalars(
            select(LocalWeeklyExportToken).where(
                LocalWeeklyExportToken.profile_id == profile_id,
                LocalWeeklyExportToken.snapshot_id == snapshot.id,
                LocalWeeklyExportToken.parent_attempt_id == attempt_id,
            )
        ).first()
        if successor is not None:
            raise LocalWeeklyExportConflict()
        _read_artifact_meta(
            manager,
            token_hash=old_token.token_hash,
            snapshot_id=snapshot.id,
            manifest_hash=snapshot.manifest_hash,
            now=now,
        )
        token_id = new_opaque_id()
        export_id = tokens.derive_export_id(
            manager.runtime,
            profile_id=profile_id,
            snapshot_id=snapshot.id,
            token_id=token_id,
            request_id=rid,
            launch_id=manager.launch_id,
            session_scope_hash=manager.session_scope_hash,
        )
        token_hash = tokens.export_id_hash(export_id)
        expires_at = min(now + timedelta(seconds=TOKEN_TTL_SECONDS), snapshot.expires_at)
    with manager.activity(
        kind="receipt",
        launch_id=manager.launch_id,
        session_scope=manager.session_scope,
    ) as epoch:
        with manager.publish(
            epoch=epoch,
            launch_id=manager.launch_id,
            session_scope=manager.session_scope,
        ):
            rollback(session)
            begin_immediate(session)
            try:
                replay = operations.find_receipt(
                    session,
                    profile_id=profile_id,
                    request_id=rid,
                    action="export_retry",
                    fingerprint=fingerprint,
                )
                if replay is not None:
                    result = _operation_response(session, manager, replay, _now())
                    rollback(session)
                    return result, False
                old_token2, snapshot2 = _attempt_lookup(
                    session, profile_id=profile_id, export_id=old_export_id
                )
                old_attempt2 = session.get(LocalWeeklyExportAttempt, attempt_id)
                now2 = _now()
                if (
                    snapshot2.id != snapshot_id
                    or snapshot2.launch_id != manager.launch_id
                    or snapshot2.session_scope_hash != manager.session_scope_hash
                    or now2 > snapshot2.expires_at
                    or old_attempt2 is None
                    or old_attempt2.profile_id != profile_id
                    or old_attempt2.export_id_hash != old_hash
                    or old_attempt2.snapshot_id != snapshot2.id
                    or old_attempt2.token_id != old_token2.id
                    or old_attempt2.status not in ("failed", "cancelled")
                ):
                    raise LocalWeeklyExportConflict()
                expires_at = min(
                    now2 + timedelta(seconds=TOKEN_TTL_SECONDS),
                    snapshot2.expires_at,
                )
                old_token_hash = old_token2.token_hash
                successor = session.scalars(
                    select(LocalWeeklyExportToken).where(
                        LocalWeeklyExportToken.profile_id == profile_id,
                        LocalWeeklyExportToken.snapshot_id == snapshot2.id,
                        LocalWeeklyExportToken.parent_attempt_id == attempt_id,
                    )
                ).first()
                if successor is not None:
                    raise LocalWeeklyExportConflict()
                session.add(
                    LocalWeeklyExportToken(
                        id=token_id,
                        snapshot_id=snapshot2.id,
                        profile_id=profile_id,
                        token_hash=token_hash,
                        expires_at=expires_at,
                        consumed_at=None,
                        parent_attempt_id=attempt_id,
                        created_at=now2,
                    )
                )
                if not manager.alias_artifact(
                    old_token2.token_hash, token_hash, expires_at
                ):
                    raise LocalWeeklyExportConflict()
                session.flush()
                metadata = {
                    "schema_version": 1,
                    "weekly_plan_id": None,
                    "draft_id": None,
                    "draft_version": None,
                    "confirmation_id": None,
                    "confirmation_version": None,
                    "snapshot_id": snapshot2.id,
                    "token_id": token_id,
                }
                operation = operations.store_receipt(
                    session,
                    profile_id=profile_id,
                    request_id=rid,
                    action="export_retry",
                    fingerprint=fingerprint,
                    result=metadata,
                    result_snapshot_id=snapshot2.id,
                    result_token_id=token_id,
                    launch_id=manager.launch_id,
                    session_scope_hash=manager.session_scope_hash,
                )
                response = _operation_response(session, manager, operation, _now())
                session.commit()
                manager.drop_alias(old_token_hash)
                return response, True
            except BaseException:
                rollback(session)
                manager.drop_alias(token_hash)
                raise
def read_operation(
    session: Session,
    manager: WeeklyExportManager | None,
    *,
    profile_id: str,
    request_id: Any,
) -> dict:
    rid = normalize_request_id(request_id)
    with read_scope(session):
        row = operations.find_receipt(
            session, profile_id=profile_id, request_id=rid
        )
        if row is None or row.action not in ("export_create", "export_retry"):
            raise LocalWeeklyOperationNotFound()
        return _operation_response(session, manager, row, _now())
