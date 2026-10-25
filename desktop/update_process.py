"""Process identity and file-lock helpers for the D3-U U2 updater.

The updater must never treat a reusable PID as proof that the old application
is gone.  A process identity therefore combines the PID with the creation
time read from a process handle; the handle (not a late PID lookup) is used
while waiting.  The install lock is a separate OS-exclusive file outside the
application directory, so two updater instances cannot switch the same
program at the same time.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wtypes
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from update_fs import PathSafetyError, ensure_safe_path

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_QUERY_INFORMATION = 0x0400
SYNCHRONIZE = 0x00100000
WAIT_OBJECT_0 = 0x00000000
WAIT_TIMEOUT = 0x00000102
WAIT_FAILED = 0xFFFFFFFF
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_ALWAYS = 4
FILE_ATTRIBUTE_NORMAL = 0x00000080
FILE_SHARE_NONE = 0
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
ERROR_SHARING_VIOLATION = 32
ERROR_LOCK_VIOLATION = 33
ERROR_FILE_NOT_FOUND = 2
ERROR_PATH_NOT_FOUND = 3
ERROR_INVALID_PARAMETER = 87
ERROR_NOT_FOUND = 1168


class ProcessIdentityError(RuntimeError):
    pass


class InstallLockError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    creation_time: int
    executable: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


_kernel32.OpenProcess.argtypes = [
    wtypes.DWORD,
    wtypes.BOOL,
    wtypes.DWORD,
]
_kernel32.OpenProcess.restype = wtypes.HANDLE
_kernel32.CloseHandle.argtypes = [wtypes.HANDLE]
_kernel32.CloseHandle.restype = wtypes.BOOL
_kernel32.GetProcessTimes.argtypes = [
    wtypes.HANDLE,
    ctypes.POINTER(wtypes.FILETIME),
    ctypes.POINTER(wtypes.FILETIME),
    ctypes.POINTER(wtypes.FILETIME),
    ctypes.POINTER(wtypes.FILETIME),
]
_kernel32.GetProcessTimes.restype = wtypes.BOOL
_kernel32.WaitForSingleObject.argtypes = [wtypes.HANDLE, wtypes.DWORD]
_kernel32.WaitForSingleObject.restype = wtypes.DWORD
_kernel32.QueryFullProcessImageNameW.argtypes = [
    wtypes.HANDLE,
    wtypes.DWORD,
    wtypes.LPWSTR,
    ctypes.POINTER(wtypes.DWORD),
]
_kernel32.QueryFullProcessImageNameW.restype = wtypes.BOOL
_kernel32.CreateFileW.argtypes = [
    wtypes.LPCWSTR,
    wtypes.DWORD,
    wtypes.DWORD,
    ctypes.c_void_p,
    wtypes.DWORD,
    wtypes.DWORD,
    wtypes.HANDLE,
]
_kernel32.CreateFileW.restype = wtypes.HANDLE


def _filetime_value(value: wtypes.FILETIME) -> int:
    return (int(value.dwHighDateTime) << 32) | int(value.dwLowDateTime)


def _query_handle_identity(handle) -> tuple[int, str]:
    created = wtypes.FILETIME()
    exited = wtypes.FILETIME()
    kernel = wtypes.FILETIME()
    user = wtypes.FILETIME()
    if not _kernel32.GetProcessTimes(
        handle,
        ctypes.byref(created),
        ctypes.byref(exited),
        ctypes.byref(kernel),
        ctypes.byref(user),
    ):
        raise ProcessIdentityError(
            f"无法读取进程创建时间（错误 {ctypes.get_last_error()}）"
        )
    creation_time = _filetime_value(created)
    if creation_time <= 0:
        raise ProcessIdentityError("进程创建时间为空")
    size = wtypes.DWORD(32768)
    buffer = ctypes.create_unicode_buffer(size.value)
    if not _kernel32.QueryFullProcessImageNameW(
        handle, 0, buffer, ctypes.byref(size)
    ):
        raise ProcessIdentityError(
            f"无法读取进程可执行路径（错误 {ctypes.get_last_error()}）"
        )
    executable = buffer.value
    if not executable:
        raise ProcessIdentityError("进程可执行路径为空")
    return creation_time, executable


def current_process_identity() -> ProcessIdentity:
    pid = os.getpid()
    handle = _kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, pid
    )
    if not handle:
        raise ProcessIdentityError(
            f"无法打开当前进程（错误 {ctypes.get_last_error()}）"
        )
    try:
        creation_time, executable = _query_handle_identity(handle)
    finally:
        _kernel32.CloseHandle(handle)
    return ProcessIdentity(pid=pid, creation_time=creation_time, executable=executable)


def process_identity(pid: int) -> ProcessIdentity | None:
    """Return the identity for a live PID, or ``None`` if it is already gone."""
    handle = _kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, int(pid)
    )
    if not handle:
        error = ctypes.get_last_error()
        if error in (ERROR_FILE_NOT_FOUND, ERROR_PATH_NOT_FOUND):
            return None
        return None
    try:
        creation_time, executable = _query_handle_identity(handle)
    except ProcessIdentityError:
        return None
    finally:
        _kernel32.CloseHandle(handle)
    return ProcessIdentity(
        pid=int(pid), creation_time=creation_time, executable=executable
    )


def identity_from_dict(value: object) -> ProcessIdentity | None:
    if not isinstance(value, dict):
        return None
    pid = value.get("pid")
    creation_time = value.get("creation_time")
    executable = value.get("executable", "")
    if (
        not isinstance(pid, int)
        or isinstance(pid, bool)
        or pid <= 0
        or not isinstance(creation_time, int)
        or isinstance(creation_time, bool)
        or creation_time <= 0
        or not isinstance(executable, str)
    ):
        return None
    return ProcessIdentity(pid=pid, creation_time=creation_time, executable=executable)


def open_verified_process(identity: ProcessIdentity):
    """Open exactly the process identified by PID + creation time.

    Returns ``None`` when the process is already gone or the PID now belongs
    to a different process.  The returned handle must be closed by the caller.
    """
    handle = _kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE,
        False,
        int(identity.pid),
    )
    if not handle:
        return None
    try:
        creation_time, executable = _query_handle_identity(handle)
    except ProcessIdentityError:
        _kernel32.CloseHandle(handle)
        return None
    if creation_time != identity.creation_time:
        _kernel32.CloseHandle(handle)
        return None
    if identity.executable and executable:
        if os.path.normcase(os.path.abspath(identity.executable)) != os.path.normcase(
            os.path.abspath(executable)
        ):
            _kernel32.CloseHandle(handle)
            return None
    return handle


def _open_identity_handle(identity: ProcessIdentity):
    """Open the identity handle and report ``(handle, definitely_gone)``.

    An access-denied or otherwise unreadable process is *not* treated as
    gone: the installer must fail closed rather than switch while an old
    process may still own the data or program.
    """
    if not identity.executable:
        return None, False
    handle = _kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE,
        False,
        int(identity.pid),
    )
    if not handle:
        error = ctypes.get_last_error()
        if error in (ERROR_INVALID_PARAMETER, ERROR_NOT_FOUND):
            return None, True
        return None, False
    try:
        creation_time, executable = _query_handle_identity(handle)
    except ProcessIdentityError:
        _kernel32.CloseHandle(handle)
        return None, False
    if creation_time != identity.creation_time:
        _kernel32.CloseHandle(handle)
        return None, True
    if identity.executable:
        if os.path.normcase(os.path.abspath(identity.executable)) != os.path.normcase(
            os.path.abspath(executable)
        ):
            # Same live PID and creation time but a different executable is
            # not proof that the planned old process exited.  Treat it as
            # unknown and fail closed.
            _kernel32.CloseHandle(handle)
            return None, False
    return handle, False


def process_matches(identity: ProcessIdentity) -> bool:
    handle, gone = _open_identity_handle(identity)
    if handle is None:
        # Unknown access is conservatively "may still be running".
        return not gone
    try:
        return _kernel32.WaitForSingleObject(handle, 0) == WAIT_TIMEOUT
    finally:
        _kernel32.CloseHandle(handle)


def wait_for_process_exit(identity: ProcessIdentity, timeout: float) -> bool:
    """Wait on the *original handle*; never kill the process.

    Returns ``True`` when the process is gone, ``False`` on timeout or when
    its handle cannot be verified (fail closed).  A PID reused by an
    unrelated process cannot satisfy the wait because the creation time was
    checked before waiting.
    """
    handle, gone = _open_identity_handle(identity)
    if handle is None:
        return gone
    try:
        milliseconds = max(0, int(timeout * 1000))
        result = _kernel32.WaitForSingleObject(handle, milliseconds)
        if result == WAIT_OBJECT_0:
            return True
        if result == WAIT_FAILED:
            return False
        return False
    finally:
        _kernel32.CloseHandle(handle)


class ExclusiveFileLock:
    """A persistent, OS-exclusive file lock (share mode 0).

    The lock file is not deleted on release: existence is never used as the
    lock state, so a crashed helper leaves no permanent dead lock.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._handle = None

    def acquire(self) -> None:
        if self._handle is not None:
            raise InstallLockError("安装锁已经由当前对象持有")
        try:
            ensure_safe_path(self.path)
        except PathSafetyError as exc:
            raise InstallLockError(str(exc)) from exc
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = _kernel32.CreateFileW(
            str(self.path),
            GENERIC_READ | GENERIC_WRITE,
            FILE_SHARE_NONE,
            None,
            OPEN_ALWAYS,
            FILE_ATTRIBUTE_NORMAL
            | FILE_FLAG_BACKUP_SEMANTICS
            | FILE_FLAG_OPEN_REPARSE_POINT,
            None,
        )
        if handle == INVALID_HANDLE_VALUE:
            error = ctypes.get_last_error()
            if error in (ERROR_SHARING_VIOLATION, ERROR_LOCK_VIOLATION):
                raise InstallLockError("另一个更新安装进程正在运行")
            raise InstallLockError(f"无法取得安装锁（错误 {error}）")
        self._handle = handle

    def release(self) -> None:
        handle = self._handle
        self._handle = None
        if handle is not None:
            _kernel32.CloseHandle(handle)

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.release()
        return False


def probe_file_not_occupied(path: str | Path) -> bool:
    """True when an exclusive open succeeds; never changes file contents."""
    handle = _kernel32.CreateFileW(
        str(path),
        GENERIC_READ | GENERIC_WRITE,
        FILE_SHARE_NONE,
        None,
        3,  # OPEN_EXISTING
        FILE_ATTRIBUTE_NORMAL | FILE_FLAG_BACKUP_SEMANTICS,
        None,
    )
    if handle == INVALID_HANDLE_VALUE:
        return False
    _kernel32.CloseHandle(handle)
    return True
