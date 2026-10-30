"""Windows handle-bound helpers for backup isolation, output and cleanup.

The backup path must never trust a path after an ``lstat``: a directory can be
renamed and replaced by a junction between the check and the next open.  These
helpers keep real Win32 handles open for the whole operation, verify the final
path on the handle, and create the private workspace with the same restricted
DACL primitive used for local credentials.

The module is deliberately small and Windows-specific; the product is
Windows-first and the local credential module already owns the native
security-descriptor primitives.
"""

from __future__ import annotations

import ctypes
import msvcrt
import os
import secrets
import stat
import warnings
from pathlib import Path

from app.local import credentials
from app.local.errors import LocalError

FILE_READ_ATTRIBUTES = 0x00000080
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
CREATE_NEW = 1
FILE_ATTRIBUTE_NORMAL = 0x00000080
FILE_ATTRIBUTE_DIRECTORY = 0x00000010
FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
GENERIC_WRITE = 0x40000000
GENERIC_READ = 0x80000000


class BackupPathError(LocalError):
    """A path could not be held, verified or safely cleaned."""

    code = "LOCAL_BACKUP_STORAGE"
    status_code = 503
    message = "备份文件操作失败"

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _normalized(path: Path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def _handle_info(handle) -> credentials._BY_HANDLE_FILE_INFORMATION:  # noqa: SLF001
    info = credentials._BY_HANDLE_FILE_INFORMATION()
    if not credentials._kernel32.GetFileInformationByHandle(
        handle, ctypes.byref(info)
    ):
        raise BackupPathError("BACKUP_PATH_INVALID", "无法读取备份路径句柄")
    return info


def _final_path(handle) -> Path:
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.GetFinalPathNameByHandleW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
        ]
        kernel32.GetFinalPathNameByHandleW.restype = ctypes.c_uint32
        buffer = ctypes.create_unicode_buffer(32768)
        length = kernel32.GetFinalPathNameByHandleW(
            ctypes.c_void_p(handle), buffer, len(buffer), 0
        )
    except Exception as exc:  # noqa: BLE001 - native path query refusal
        raise BackupPathError("BACKUP_PATH_INVALID", "备份路径句柄无法核验") from exc
    if not length:
        raise BackupPathError("BACKUP_PATH_INVALID", "备份路径句柄无法核验")
    value = buffer.value
    if value.startswith("\\\\?\\UNC\\"):
        value = "\\\\" + value[8:]
    elif value.startswith("\\\\?\\"):
        value = value[4:]
    return Path(value)


def _close_handle(handle) -> None:
    if handle not in (None, INVALID_HANDLE_VALUE):
        credentials._kernel32.CloseHandle(handle)  # noqa: SLF001


def _open_directory(path: Path):
    handle = credentials._kernel32.CreateFileW(  # noqa: SLF001
        str(path),
        GENERIC_READ,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        None,
        OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL
        | FILE_FLAG_BACKUP_SEMANTICS
        | FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    if handle == INVALID_HANDLE_VALUE:
        raise BackupPathError("BACKUP_PATH_INVALID", "无法打开备份目录")
    try:
        info = _handle_info(handle)
        if (
            not info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY
            or info.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise BackupPathError("BACKUP_PATH_INVALID", "备份目录不是普通目录")
        final = _final_path(handle)
        if _normalized(final) != _normalized(path):
            raise BackupPathError("BACKUP_PATH_INVALID", "备份目录最终路径不一致")
    except BaseException:
        _close_handle(handle)
        raise
    return handle


class DirectoryGuard:
    """Hold every ancestor directory without delete sharing.

    Windows denies a rename/replacement of a directory while a handle without
    ``FILE_SHARE_DELETE`` is open on it (and on any descendant).  Opening the
    whole chain also rejects a junction that existed before the hold because
    the final path of each handle must equal the requested path.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self.handles: list = []
        self.final_path: Path | None = None

    def __enter__(self) -> "DirectoryGuard":
        absolute = Path(os.path.abspath(str(self.path)))
        if not absolute.is_absolute():
            raise BackupPathError("BACKUP_PATH_INVALID", "备份目录必须是绝对路径")
        current = Path(absolute.anchor)
        parts = absolute.parts
        try:
            # ``parts[0]`` is the anchor; open it and every component below it.
            for part in parts:
                if part == absolute.anchor:
                    continue
                current = current / part
                self.handles.append(_open_directory(current))
            if not self.handles:
                self.handles.append(_open_directory(current))
            self.final_path = _final_path(self.handles[-1])
        except BaseException:
            self.close()
            raise
        return self

    @property
    def handle(self):
        return self.handles[-1] if self.handles else None

    def close(self) -> None:
        while self.handles:
            _close_handle(self.handles.pop())

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


class FileLease:
    """Open one regular file for reading and keep its identity verified.

    The handle denies write and delete sharing, is opened without following a
    reparse point, and its final path must equal the requested path.  All bytes
    are read from this same handle; the path is never reopened.
    """

    def __init__(self, path: Path, *, expected: Path | None = None, root: Path | None = None):
        self.path = Path(path)
        self.expected = Path(expected) if expected is not None else self.path
        self.root = Path(root) if root is not None else None
        self.handle = None
        self.fd: int | None = None
        self.size = 0
        self.identity: tuple[int, int, int, int] | None = None

    def __enter__(self) -> "FileLease":
        handle = credentials._kernel32.CreateFileW(  # noqa: SLF001
            str(self.path),
            GENERIC_READ,
            FILE_SHARE_READ,
            None,
            OPEN_EXISTING,
            FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OPEN_REPARSE_POINT,
            None,
        )
        if handle == INVALID_HANDLE_VALUE:
            raise BackupPathError("BACKUP_PATH_INVALID", "无法打开备份文件")
        try:
            info = _handle_info(handle)
            if (
                info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY
                or info.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT
                or info.nNumberOfLinks != 1
            ):
                raise BackupPathError("BACKUP_PATH_INVALID", "备份文件身份不合法")
            final = _final_path(handle)
            if _normalized(final) != _normalized(self.expected):
                raise BackupPathError("BACKUP_PATH_INVALID", "备份文件最终路径不一致")
            if self.root is not None:
                try:
                    final.relative_to(self.root)
                except ValueError:
                    raise BackupPathError("BACKUP_PATH_INVALID", "备份文件越界") from None
            self.fd = msvcrt.open_osfhandle(
                int(handle), os.O_RDONLY | getattr(os, "O_BINARY", 0)
            )
            self.handle = handle
            self.size = os.fstat(self.fd).st_size
            stat_info = os.fstat(self.fd)
            self.identity = (
                int(stat_info.st_dev),
                int(stat_info.st_ino),
                int(stat_info.st_size),
                int(stat_info.st_mtime_ns),
            )
        except BaseException:
            if self.fd is not None:
                os.close(self.fd)
                self.fd = None
                self.handle = None
            else:
                _close_handle(handle)
            raise
        return self

    def read(self, size: int) -> bytes:
        if self.fd is None:
            raise BackupPathError("BACKUP_PATH_INVALID", "备份文件句柄已关闭")
        return os.read(self.fd, size)

    def seek(self, offset: int) -> None:
        if self.fd is None:
            raise BackupPathError("BACKUP_PATH_INVALID", "备份文件句柄已关闭")
        os.lseek(self.fd, offset, os.SEEK_SET)

    def close(self) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
            self.handle = None
        else:
            _close_handle(self.handle)
            self.handle = None

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


class PrivateWorkArea:
    """Application-managed, current-user-only directory for plaintext work.

    The supplied root is created with the same protected DACL used by the
    credential store.  Every nested directory and every plaintext file is
    created with that DACL.  The root and each subdirectory handle are held for
    the lifetime of the area so the tree cannot be renamed away before cleanup.
    """

    def __init__(
        self,
        root: Path,
        kind: str,
        *,
        prefix: str | None = None,
        managed_root: bool = True,
    ):
        self.root = Path(root)
        self.path = self.root / f"{prefix or kind + '-'}{secrets.token_hex(12)}"
        self.owner_sid = credentials._current_user_sid()  # noqa: SLF001
        self.managed_root = managed_root
        self._root_handle = None
        self._root_guard: DirectoryGuard | None = None
        self._parent_guard: DirectoryGuard | None = None
        self._handles: list = []
        self._closed = False
        self.path_identity: tuple[int, int] | None = None

    def __enter__(self) -> "PrivateWorkArea":
        try:
            if self.managed_root:
                self._parent_guard = DirectoryGuard(self.root.parent)
                self._parent_guard.__enter__()
                self._root_handle = credentials._ensure_managed_dir(  # noqa: SLF001
                    self.root, self.owner_sid
                )
                self._handles.append(
                    credentials._ensure_managed_dir(  # noqa: SLF001
                        self.path, self.owner_sid
                    )
                )
                self._set_path_identity()
            else:
                self._root_guard = DirectoryGuard(self.root)
                self._root_guard.__enter__()
                credentials._create_managed_dir(  # noqa: SLF001
                    self.path, self.owner_sid
                )
                self._handles.append(
                    credentials._open_managed_dir(  # noqa: SLF001
                        self.path, self.owner_sid
                    )
                )
                self._set_path_identity()
        except BaseException:
            self.close_handles()
            _close_handle(self._root_handle)
            self._root_handle = None
            if self._root_guard is not None:
                self._root_guard.close()
                self._root_guard = None
            if self._parent_guard is not None:
                self._parent_guard.close()
                self._parent_guard = None
            raise
        return self

    def _set_path_identity(self) -> None:
        info = os.lstat(self.path)
        self.path_identity = (int(info.st_dev), int(info.st_ino))

    def subdir(self, *parts: str) -> Path:
        current = self.path
        for part in parts:
            current = current / part
            self._handles.append(
                credentials._ensure_managed_dir(current, self.owner_sid)  # noqa: SLF001
            )
        return current

    def create_file(self, path: Path) -> int:
        """Create a new restricted file and return its writable fd."""
        parent = path.parent
        if parent != self.path:
            self.subdir(*parent.relative_to(self.path).parts)
        sa = credentials._make_security_attributes(self.owner_sid)  # noqa: SLF001
        handle = INVALID_HANDLE_VALUE
        try:
            handle = credentials._kernel32.CreateFileW(  # noqa: SLF001
                str(path),
                GENERIC_WRITE,
                0,
                ctypes.byref(sa),
                CREATE_NEW,
                FILE_ATTRIBUTE_NORMAL,
                None,
            )
            if handle == INVALID_HANDLE_VALUE:
                raise BackupPathError("BACKUP_PATH_INVALID", "无法创建备份临时文件")
            try:
                return msvcrt.open_osfhandle(
                    int(handle), os.O_WRONLY | getattr(os, "O_BINARY", 0)
                )
            except OSError as exc:
                _close_handle(handle)
                raise BackupPathError(
                    "BACKUP_PATH_INVALID", "无法接管备份临时文件句柄"
                ) from exc
        finally:
            credentials._free_sa(sa)  # noqa: SLF001

    def close_handles(self) -> None:
        while self._handles:
            _close_handle(self._handles.pop())

    def detach(self) -> None:
        """Close handles but leave the verified tree for the caller (B2)."""
        if self._closed:
            return
        self._closed = True
        self.close_handles()
        _close_handle(self._root_handle)
        self._root_handle = None
        if self._root_guard is not None:
            self._root_guard.close()
            self._root_guard = None
        if self._parent_guard is not None:
            self._parent_guard.close()
            self._parent_guard = None

    def cleanup(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.close_handles()
        try:
            remove_tree(self.path, expected_identity=self.path_identity)
        finally:
            _close_handle(self._root_handle)
            self._root_handle = None
            if self._root_guard is not None:
                self._root_guard.close()
                self._root_guard = None
            if self._parent_guard is not None:
                self._parent_guard.close()
                self._parent_guard = None

    def __exit__(self, exc_type, exc, tb) -> None:
        self.cleanup()


def remove_tree(
    path: Path, *, expected_identity: tuple[int, int] | None = None
) -> None:
    """Remove exactly one process-created private directory tree.

    Every directory level is opened and held with a no-delete-share handle
    *before* it is inspected or enumerated.  The handle denies a rename or
    junction replacement for the whole time that level is being walked; only
    after all children are gone is the handle released and a single
    non-recursive ``rmdir`` attempted.  Parent handles stay held through the
    recursive walk, so an ancestor replacement cannot redirect deletion.

    ``expected_identity`` binds the root to the identity observed when the
    caller detached/created it.  Child directory identities are bound to the
    ``DirEntry`` stat captured while the parent handle was held.
    """

    def identity(info: os.stat_result) -> tuple[int, int]:
        return (int(info.st_dev), int(info.st_ino))

    guard = DirectoryGuard(path)
    guard.__enter__()
    try:
        info = os.lstat(path)
        if getattr(info, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT:
            raise BackupPathError("BACKUP_CLEANUP_UNSAFE", "清理路径包含重解析点")
        if not stat.S_ISDIR(info.st_mode):
            raise BackupPathError("BACKUP_CLEANUP_UNSAFE", "清理路径不是目录")
        current_identity = identity(info)
        if expected_identity is not None and current_identity != expected_identity:
            raise BackupPathError("BACKUP_CLEANUP_UNSAFE", "清理目录身份已变化")
        with os.scandir(path) as entries:
            for entry in entries:
                child = Path(entry.path)
                child_info = entry.stat(follow_symlinks=False)
                if (
                    getattr(child_info, "st_file_attributes", 0)
                    & FILE_ATTRIBUTE_REPARSE_POINT
                ):
                    raise BackupPathError(
                        "BACKUP_CLEANUP_UNSAFE", "清理路径包含重解析点"
                    )
                child_inode = int(entry.inode())
                if child_inode == 0:
                    raise BackupPathError(
                        "BACKUP_CLEANUP_UNSAFE", "清理子项身份不可核验"
                    )
                child_identity = (int(current_identity[0]), child_inode)
                if entry.is_dir(follow_symlinks=False):
                    remove_tree(
                        child,
                        expected_identity=child_identity,
                    )
                elif entry.is_file(follow_symlinks=False):
                    _unlink_file(child, child_identity)
                else:
                    raise BackupPathError(
                        "BACKUP_CLEANUP_UNSAFE", "清理路径含未知对象"
                    )
    finally:
        guard.close()
    try:
        os.rmdir(path)
    except OSError as exc:
        raise BackupPathError("BACKUP_CLEANUP_FAILED", "备份目录清理失败") from exc


def _unlink_file(path: Path, expected_identity: tuple[int, int]) -> None:
    try:
        with FileLease(path) as lease:
            if lease.identity is None or lease.identity[:2] != expected_identity:
                raise BackupPathError("BACKUP_CLEANUP_UNSAFE", "清理文件身份已变化")
    except BackupPathError:
        raise
    except LocalError as exc:
        raise BackupPathError("BACKUP_CLEANUP_UNSAFE", "清理文件无法核验") from exc
    try:
        os.unlink(path)
    except OSError as exc:
        raise BackupPathError("BACKUP_CLEANUP_FAILED", "备份文件清理失败") from exc

def create_output_temp(parent: Path, stem: str) -> tuple[int, Path]:
    """Create an exclusive temp file in the (held) output parent directory."""
    for _ in range(32):
        candidate = parent / f".{stem}-{secrets.token_hex(8)}.tmp"
        try:
            fd = os.open(
                candidate,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_BINARY", 0),
                0o600,
            )
        except FileExistsError:
            continue
        except OSError as exc:
            raise BackupPathError("BACKUP_TARGET_INVALID", "无法创建备份目标临时文件") from exc
        return fd, candidate
    raise BackupPathError("BACKUP_TARGET_INVALID", "无法创建备份目标临时文件")


def publish_no_replace(temp: Path, target: Path) -> None:
    """Atomically create ``target`` from ``temp`` without ever replacing it."""
    try:
        os.link(temp, target)
    except FileExistsError as exc:
        raise BackupPathError("BACKUP_TARGET_EXISTS", "备份目标已存在，拒绝覆盖") from exc
    except OSError as exc:
        raise BackupPathError("BACKUP_TARGET_INVALID", "备份目标无法原子发布") from exc
    try:
        os.unlink(temp)
    except OSError as exc:
        warnings.warn(
            f"backup temp output cleanup failed: {exc}",
            RuntimeWarning,
            stacklevel=2,
        )
