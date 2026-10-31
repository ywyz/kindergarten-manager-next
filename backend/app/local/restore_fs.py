"""Handle-bound filesystem helpers for the B2 restore core.

The module reuses the already-audited backup primitives for directory guards,
file leases, private work areas and identity-bound cleanup.  It adds only the
restore-specific layout, bounded copy, no-replace same-volume move and durable
JSON write used by the maintenance journal.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import msvcrt
import os
import re
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.local import backup_fs, credentials
from app.local.errors import LocalError
from app.local.restore_types import RestoreFailure

_OP_ID = re.compile(r"^[0-9a-f]{32}$")
_CHUNK = 1024 * 1024
_REPARSE = 0x00000400
_MOVEFILE_REPLACE_EXISTING = 0x1
_MOVEFILE_WRITE_THROUGH = 0x8
_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_OPEN_EXISTING = 3
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_ERROR_SHARING_VIOLATION = 32
_ERROR_LOCK_VIOLATION = 33
_ERROR_ACCESS_DENIED = 5
_ERROR_FILE_NOT_FOUND = 2
_ERROR_PATH_NOT_FOUND = 3

_kernel32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)
_kernel32.MoveFileExW.restype = ctypes.c_bool
_kernel32.MoveFileExW.argtypes = [
    ctypes.c_wchar_p,
    ctypes.c_wchar_p,
    ctypes.c_uint32,
]


@dataclass(frozen=True)
class FileIdentity:
    present: bool
    volume: int = 0
    file_id: int = 0
    size: int = 0
    mtime_ns: int = 0
    sha256: str = ""
    is_dir: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "present": self.present,
            "volume": self.volume,
            "file_id": self.file_id,
            "size": self.size,
            "mtime_ns": self.mtime_ns,
            "sha256": self.sha256,
            "is_dir": self.is_dir,
        }


@dataclass(frozen=True)
class RestorePathSet:
    data_dir: Path
    work_root: Path
    guard_root: Path
    operation_dir: Path
    old_dir: Path
    prepared_dir: Path
    guard_dir: Path
    protection_path: Path
    journal_path: Path
    receipts_dir: Path


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(str(path)))


def _norm(path: Path) -> str:
    return os.path.normcase(_absolute(path).as_posix()).replace("\\", "/")


def _is_within(path: Path, root: Path) -> bool:
    left = _norm(path)
    right = _norm(root)
    return left == right or left.startswith(right.rstrip("/") + "/")


def _ensure_private_dir(path: Path) -> None:
    """Create a current-user restricted directory, rejecting aliases."""
    path = _absolute(path)
    # Do not let the credential helper create intermediate levels with an
    # inherited public DACL: every missing component in this private tree is
    # created with the restricted security descriptor itself.
    missing: list[Path] = []
    cursor = path
    while not os.path.lexists(cursor):
        missing.append(cursor)
        parent = cursor.parent
        if parent == cursor:
            break
        cursor = parent
    if os.path.lexists(cursor):
        if credentials._is_reparse_point(cursor):  # noqa: SLF001
            raise RestoreFailure(
                "RESTORE_PATH_UNSAFE", "prepare", "恢复目录祖先包含重解析点"
            )
    for level in reversed(missing):
        credentials._create_managed_dir(  # noqa: SLF001
            level, credentials._current_user_sid()  # noqa: SLF001
        )
    handle = credentials._ensure_managed_dir(  # noqa: SLF001
        path, credentials._current_user_sid()  # noqa: SLF001
    )
    credentials._kernel32.CloseHandle(handle)  # noqa: SLF001


def _directory_identity(path: Path) -> tuple[int, int]:
    info = os.lstat(path)
    if getattr(info, "st_file_attributes", 0) & _REPARSE:
        raise RestoreFailure(
            "RESTORE_PATH_UNSAFE", "prepare", "恢复目录不得是重解析点"
        )
    if not os.path.isdir(path):
        raise RestoreFailure(
            "RESTORE_PATH_UNSAFE", "prepare", "恢复目录不是普通目录"
        )
    return (int(info.st_dev), int(info.st_ino))


def operation_paths(runtime: Any, operation_id: str, *, create: bool) -> RestorePathSet:
    if not isinstance(operation_id, str) or not _OP_ID.fullmatch(operation_id):
        raise RestoreFailure(
            "RESTORE_OPERATION_INVALID", "choose", "恢复操作标识不合法"
        )
    data_dir = _absolute(Path(runtime.data_dir))
    credential_root = _absolute(Path(runtime.credential_root))
    name = data_dir.name or "data"
    work_root = _absolute(data_dir.parent / f"{name}.restore-work")
    guard_root = _absolute(data_dir.parent / f"{name}.restore-guard")
    for root in (work_root, guard_root):
        if _is_within(root, data_dir) or _is_within(root, credential_root):
            raise RestoreFailure(
                "RESTORE_PATH_UNSAFE",
                "prepare",
                "恢复工作根不得位于数据根或凭据根内",
            )
    operation_dir = work_root / operation_id
    guard_dir = guard_root / operation_id
    paths = RestorePathSet(
        data_dir=data_dir,
        work_root=work_root,
        guard_root=guard_root,
        operation_dir=operation_dir,
        old_dir=operation_dir / "old",
        prepared_dir=operation_dir / "prepared",
        guard_dir=guard_dir,
        protection_path=guard_dir / "pre-restore.kgmbackup",
        journal_path=data_dir / ".restore-journal.json",
        receipts_dir=data_dir / ".restore-receipts",
    )
    if create:
        data_stat = os.stat(data_dir)
        for root in (work_root, guard_root):
            _ensure_private_dir(root)
            if os.stat(root).st_dev != data_stat.st_dev:
                raise RestoreFailure(
                    "RESTORE_NOT_SAME_VOLUME",
                    "prepare",
                    "恢复工作根必须与数据根同卷",
                )
        for path in (operation_dir, paths.old_dir, paths.prepared_dir, guard_dir):
            _ensure_private_dir(path)
        _ensure_private_dir(paths.receipts_dir)
    return paths


def ensure_private_dir(path: Path) -> None:
    """Public wrapper for creating one restricted application directory."""
    _ensure_private_dir(path)


def directory_identity(path: Path) -> tuple[int, int]:
    return _directory_identity(path)


def file_identity(path: Path, *, hash_content: bool = True) -> FileIdentity:
    path = _absolute(path)
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return FileIdentity(present=False)
    if getattr(info, "st_file_attributes", 0) & _REPARSE:
        raise RestoreFailure(
            "RESTORE_PATH_UNSAFE", "verify", "恢复组件不得是重解析点"
        )
    if not os.path.isfile(path):
        raise RestoreFailure(
            "RESTORE_PATH_UNSAFE", "verify", "恢复组件不是普通文件"
        )
    with backup_fs.FileLease(path) as lease:
        digest = ""
        if hash_content:
            hasher = hashlib.sha256()
            total = 0
            while True:
                chunk = lease.read(_CHUNK)
                if not chunk:
                    break
                total += len(chunk)
                hasher.update(chunk)
            if total != lease.size:
                raise RestoreFailure(
                    "RESTORE_COMPONENT_CHANGED",
                    "verify",
                    "恢复组件在读取期间发生变化",
                )
            digest = hasher.hexdigest()
        identity = lease.identity or (0, 0, 0, 0)
    return FileIdentity(
        present=True,
        volume=int(identity[0]),
        file_id=int(identity[1]),
        size=int(identity[2]),
        mtime_ns=int(identity[3]),
        sha256=digest,
    )


def _entry_identity(info: os.stat_result) -> tuple[int, int]:
    return (int(info.st_dev), int(info.st_ino))


def tree_manifest(root: Path, *, strict_regular: bool) -> dict[str, Any]:
    """Hash every object under one assets directory without following links."""
    root = _absolute(root)
    if not root.exists():
        return {
            "present": False,
            "root_identity": None,
            "entries": [],
            "digest": hashlib.sha256(b"[]").hexdigest(),
        }
    root_identity = _directory_identity(root)
    entries: list[dict[str, Any]] = []

    def walk(current: Path, relative: str) -> None:
        with os.scandir(current) as scan:
            for entry in sorted(scan, key=lambda item: item.name):
                child = Path(entry.path)
                child_rel = f"{relative}/{entry.name}" if relative else entry.name
                info = entry.stat(follow_symlinks=False)
                attrs = getattr(info, "st_file_attributes", 0)
                if attrs & _REPARSE:
                    if strict_regular:
                        raise RestoreFailure(
                            "RESTORE_ASSETS_UNSAFE",
                            "prepare",
                            "恢复资产树不得包含链接或重解析点",
                        )
                    entries.append(
                        {
                            "path": child_rel,
                            "kind": "link",
                            "identity": list(_entry_identity(info)),
                        }
                    )
                    continue
                if entry.is_dir(follow_symlinks=False):
                    entries.append(
                        {
                            "path": child_rel,
                            "kind": "dir",
                            "identity": list(_entry_identity(info)),
                        }
                    )
                    walk(child, child_rel)
                    continue
                if entry.is_file(follow_symlinks=False):
                    try:
                        with backup_fs.FileLease(child) as lease:
                            hasher = hashlib.sha256()
                            total = 0
                            while True:
                                chunk = lease.read(_CHUNK)
                                if not chunk:
                                    break
                                total += len(chunk)
                                hasher.update(chunk)
                            if total != lease.size:
                                raise RestoreFailure(
                                    "RESTORE_ASSETS_CHANGED",
                                    "verify",
                                    "恢复资产在读取期间发生变化",
                                )
                    except (LocalError, OSError):
                        if strict_regular:
                            raise
                        entries.append(
                            {
                                "path": child_rel,
                                "kind": "opaque",
                                "identity": list(_entry_identity(info)),
                            }
                        )
                        continue
                    entries.append(
                        {
                            "path": child_rel,
                            "kind": "file",
                            "size": total,
                            "sha256": hasher.hexdigest(),
                            "identity": list(_entry_identity(info)),
                        }
                    )
                    continue
                if strict_regular:
                    raise RestoreFailure(
                        "RESTORE_ASSETS_UNSAFE",
                        "prepare",
                        "恢复资产树包含未知对象",
                    )
                entries.append(
                    {
                        "path": child_rel,
                        "kind": "opaque",
                        "identity": list(_entry_identity(info)),
                    }
                )

    walk(root, "")
    digest = hashlib.sha256(
        json.dumps(
            entries,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "present": True,
        "root_identity": list(root_identity),
        "entries": entries,
        "digest": digest,
    }


def verify_tree(
    root: Path,
    expected: dict[str, Any],
    *,
    strict_regular: bool,
    compare_identity: bool = True,
) -> None:
    actual = tree_manifest(root, strict_regular=strict_regular)
    if bool(actual["present"]) != bool(expected.get("present")):
        raise RestoreFailure(
            "RESTORE_ASSETS_MISMATCH", "verify", "恢复资产树存在状态不一致"
        )
    if not actual["present"]:
        return
    if compare_identity and actual["root_identity"] != expected.get("root_identity"):
        raise RestoreFailure(
            "RESTORE_ASSETS_MISMATCH", "verify", "恢复资产树目录身份不一致"
        )
    actual_entries = actual["entries"]
    expected_entries = expected.get("entries") or []
    if len(actual_entries) != len(expected_entries):
        raise RestoreFailure(
            "RESTORE_ASSETS_MISMATCH", "verify", "恢复资产数量不一致"
        )
    for left, right in zip(actual_entries, expected_entries):
        if left == right:
            continue
        if not compare_identity:
            left = {k: v for k, v in left.items() if k != "identity"}
            right = {k: v for k, v in right.items() if k != "identity"}
            if left == right:
                continue
        raise RestoreFailure(
            "RESTORE_ASSETS_MISMATCH", "verify", "恢复资产身份或内容不一致"
        )


def _create_private_file(path: Path, *, private_parent: bool = True) -> int:
    if private_parent:
        _ensure_private_dir(path.parent)
    sa = credentials._make_security_attributes(  # noqa: SLF001
        credentials._current_user_sid()  # noqa: SLF001
    )
    handle = _INVALID_HANDLE_VALUE
    try:
        handle = credentials._kernel32.CreateFileW(  # noqa: SLF001
            str(path),
            _GENERIC_WRITE,
            0,
            ctypes.byref(sa),
            1,  # CREATE_NEW
            0x80,
            None,
        )
        if handle == _INVALID_HANDLE_VALUE:
            raise RestoreFailure(
                "RESTORE_STORAGE_UNAVAILABLE", "prepare", "无法创建恢复临时文件"
            )
        try:
            return msvcrt.open_osfhandle(
                int(handle), os.O_WRONLY | getattr(os, "O_BINARY", 0)
            )
        except OSError as exc:
            credentials._kernel32.CloseHandle(handle)  # noqa: SLF001
            raise RestoreFailure(
                "RESTORE_STORAGE_UNAVAILABLE", "prepare", "无法接管恢复临时文件"
            ) from exc
    finally:
        credentials._free_sa(sa)  # noqa: SLF001


def copy_file(
    source: Path,
    target: Path,
    *,
    expected_size: int | None = None,
    expected_sha256: str | None = None,
    cancel=None,
) -> FileIdentity:
    source = _absolute(source)
    target = _absolute(target)
    if target.exists():
        raise RestoreFailure(
            "RESTORE_TARGET_EXISTS", "prepare", "恢复目标已存在，拒绝覆盖"
        )
    _ensure_private_dir(target.parent)
    fd = _create_private_file(target)
    hasher = hashlib.sha256()
    total = 0
    try:
        with backup_fs.FileLease(source) as lease, os.fdopen(fd, "wb") as out:
            fd = -1
            while True:
                if cancel is not None and cancel.is_set():
                    raise RestoreFailure(
                        "RESTORE_CANCELED", "prepare", "恢复已取消"
                    )
                chunk = lease.read(_CHUNK)
                if not chunk:
                    break
                total += len(chunk)
                hasher.update(chunk)
                out.write(chunk)
            out.flush()
            os.fsync(out.fileno())
            written = os.fstat(out.fileno())
            if written.st_size != total:
                raise RestoreFailure(
                    "RESTORE_COMPONENT_CHANGED",
                    "prepare",
                    "恢复复制大小不一致",
                )
            identity = (int(written.st_dev), int(written.st_ino))
            size = int(written.st_size)
            mtime_ns = int(written.st_mtime_ns)
    except BaseException:
        if fd >= 0:
            os.close(fd)
        try:
            target.unlink()
        except OSError:
            pass
        raise
    if expected_size is not None and total != expected_size:
        raise RestoreFailure(
            "RESTORE_COMPONENT_CHANGED", "prepare", "恢复组件大小不一致"
        )
    digest = hasher.hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise RestoreFailure(
            "RESTORE_COMPONENT_CHANGED", "prepare", "恢复组件 hash 不一致"
        )
    final = os.lstat(target)
    if (int(final.st_dev), int(final.st_ino)) != identity or final.st_size != size:
        raise RestoreFailure(
            "RESTORE_COMPONENT_CHANGED", "prepare", "恢复组件落盘后被替换"
        )
    return FileIdentity(
        present=True,
        volume=identity[0],
        file_id=identity[1],
        size=size,
        mtime_ns=mtime_ns,
        sha256=digest,
    )


def move_no_replace(
    source: Path, target: Path, *, private_parent: bool = False
) -> None:
    source = _absolute(source)
    target = _absolute(target)
    if not source.exists() and not os.path.lexists(source):
        raise RestoreFailure(
            "RESTORE_COMPONENT_MISSING", "switch", "恢复源组件不存在"
        )
    if os.path.lexists(target):
        raise RestoreFailure(
            "RESTORE_TARGET_EXISTS", "switch", "恢复目标已存在，拒绝覆盖"
        )
    if private_parent:
        _ensure_private_dir(target.parent)
    elif not target.parent.is_dir():
        target.parent.mkdir(parents=True, exist_ok=True)
    if not _kernel32.MoveFileExW(str(source), str(target), _MOVEFILE_WRITE_THROUGH):
        error = ctypes.get_last_error()
        if error in (_ERROR_SHARING_VIOLATION, _ERROR_LOCK_VIOLATION):
            raise RestoreFailure(
                "RESTORE_FILE_IN_USE", "switch", "恢复组件被占用，拒绝移动"
            )
        raise RestoreFailure(
            "RESTORE_SWITCH_FAILED", "switch", f"恢复组件移动失败（错误 {error}）"
        )


def atomic_write_json(
    path: Path, data: dict[str, Any], *, replace: bool, private_parent: bool = False
) -> FileIdentity:
    path = _absolute(path)
    if private_parent:
        _ensure_private_dir(path.parent)
    elif not path.parent.is_dir():
        raise RestoreFailure(
            "RESTORE_STORAGE_UNAVAILABLE", "switch", "恢复日志父目录不存在"
        )
    raw = json.dumps(
        data, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    temp = path.with_name(f".{path.name}.tmp-{secrets.token_hex(8)}")
    fd = _create_private_file(temp, private_parent=private_parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        if fd >= 0:
            os.close(fd)
        try:
            temp.unlink()
        except OSError:
            pass
        raise
    flags = _MOVEFILE_WRITE_THROUGH
    if replace:
        flags |= _MOVEFILE_REPLACE_EXISTING
    moved = False
    error = 0
    for attempt in range(20):
        if _kernel32.MoveFileExW(str(temp), str(path), flags):
            moved = True
            error = 0
            break
        error = ctypes.get_last_error()
        if error not in (
            _ERROR_SHARING_VIOLATION,
            _ERROR_LOCK_VIOLATION,
            _ERROR_ACCESS_DENIED,
        ):
            break
        time.sleep(0.005 * (attempt + 1))
    if not moved:
        try:
            temp.unlink()
        except OSError:
            pass
        raise RestoreFailure(
            "RESTORE_JOURNAL_FAILED",
            "switch",
            f"恢复日志落盘失败（错误 {error}）",
        )
    return file_identity(path)


def read_json(path: Path) -> dict[str, Any] | None:
    path = _absolute(path)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise RestoreFailure(
            "RESTORE_JOURNAL_INVALID", "recovery", "恢复日志无法解析"
        ) from exc
    if not isinstance(value, dict):
        raise RestoreFailure(
            "RESTORE_JOURNAL_INVALID", "recovery", "恢复日志不是对象"
        )
    return value


def probe_database_family(db_path: Path) -> bool:
    """True only when no other handle holds any existing DB-family member."""
    db_path = _absolute(db_path)
    family = [
        db_path,
        db_path.with_name(db_path.name + "-wal"),
        db_path.with_name(db_path.name + "-shm"),
        db_path.with_name(db_path.name + "-journal"),
    ]
    for path in family:
        if not path.exists():
            continue
        handle = credentials._kernel32.CreateFileW(  # noqa: SLF001
            str(path),
            _GENERIC_READ | _GENERIC_WRITE,
            0,
            None,
            _OPEN_EXISTING,
            0x80,
            None,
        )
        if handle == _INVALID_HANDLE_VALUE:
            error = ctypes.get_last_error()
            if error in (_ERROR_SHARING_VIOLATION, _ERROR_LOCK_VIOLATION, _ERROR_ACCESS_DENIED):
                return False
            if error in (_ERROR_FILE_NOT_FOUND, _ERROR_PATH_NOT_FOUND):
                continue
            return False
        credentials._kernel32.CloseHandle(handle)  # noqa: SLF001
    return True


def same_volume(path: Path, other: Path) -> bool:
    return os.stat(_absolute(path)).st_dev == os.stat(_absolute(other)).st_dev


def path_is_within(path: Path, root: Path) -> bool:
    return _is_within(path, root)


def _real_path(path: Path) -> Path:
    return Path(os.path.realpath(str(_absolute(path))))


def _ancestor_reparse(path: Path) -> bool:
    current = _absolute(path)
    for candidate in (current, *current.parents):
        try:
            if credentials._is_reparse_point(candidate):  # noqa: SLF001
                return True
        except Exception:  # noqa: BLE001 - unverifiable is unsafe here
            return True
        if candidate == candidate.parent:
            break
    return False


def credential_overlap(runtime: Any, paths: RestorePathSet) -> bool:
    """True when the configured credential root overlaps a managed group.

    This check is restore-only: ordinary startup may run with a missing or
    nested credential root (AI degrades), but a restore must never move or
    copy the Windows DPAPI material with ``observations/assets``.
    """
    credential = _absolute(Path(runtime.credential_root))
    if _ancestor_reparse(credential):
        return True
    targets = [
        paths.data_dir,
        paths.data_dir / "observations" / "assets",
        paths.work_root,
        paths.guard_root,
        paths.prepared_dir,
        paths.old_dir,
    ]
    credential_real = _real_path(credential)
    for target in targets:
        target = _absolute(target)
        for left, right in (
            (credential, target),
            (credential_real, _real_path(target)),
        ):
            if _is_within(left, right) or _is_within(right, left):
                return True
    return False


def cleanup_own_operation(paths: RestorePathSet, identity: tuple[int, int]) -> None:
    """Remove only this operation's own work tree, bound to its identity."""
    target = _absolute(paths.operation_dir)
    if target.parent != _absolute(paths.work_root) or not _OP_ID.fullmatch(target.name):
        raise RestoreFailure(
            "RESTORE_CLEANUP_UNSAFE", "cleanup", "拒绝清理非本次恢复工作目录"
        )
    with backup_fs.DirectoryGuard(paths.work_root):
        backup_fs.remove_tree(target, expected_identity=identity)
