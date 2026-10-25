"""Windows path-safety checks for the D3-U update staging tree.

The checks are intentionally independent of ``Path.resolve()``: a junction or
hardlink must be refused before it can redirect the managed staging authority.
Only a definite not-found may be treated as safe; any other attribute/open
failure is a refusal.
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from pathlib import Path

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_GET_FILE_EX_INFO_STANDARD = 0
_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
_FILE_ATTRIBUTE_DIRECTORY = 0x00000010
_FILE_READ_ATTRIBUTES = 0x00000080
_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_FILE_SHARE_DELETE = 0x00000004
_OPEN_EXISTING = 3
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_ERROR_FILE_NOT_FOUND = 2
_ERROR_PATH_NOT_FOUND = 3
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class _WIN32_FILE_ATTRIBUTE_DATA(ctypes.Structure):
    _fields_ = [
        ("dwFileAttributes", wintypes.DWORD),
        ("ftCreationTime", wintypes.FILETIME),
        ("ftLastAccessTime", wintypes.FILETIME),
        ("ftLastWriteTime", wintypes.FILETIME),
        ("nFileSizeHigh", wintypes.DWORD),
        ("nFileSizeLow", wintypes.DWORD),
    ]


class _BY_HANDLE_FILE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("dwFileAttributes", wintypes.DWORD),
        ("ftCreationTime", wintypes.FILETIME),
        ("ftLastAccessTime", wintypes.FILETIME),
        ("ftLastWriteTime", wintypes.FILETIME),
        ("dwVolumeSerialNumber", wintypes.DWORD),
        ("nFileSizeHigh", wintypes.DWORD),
        ("nFileSizeLow", wintypes.DWORD),
        ("nNumberOfLinks", wintypes.DWORD),
        ("nFileIndexHigh", wintypes.DWORD),
        ("nFileIndexLow", wintypes.DWORD),
    ]


_kernel32.GetFileAttributesExW.argtypes = [
    wintypes.LPCWSTR,
    ctypes.c_int,
    ctypes.POINTER(_WIN32_FILE_ATTRIBUTE_DATA),
]
_kernel32.GetFileAttributesExW.restype = wintypes.BOOL
_kernel32.CreateFileW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.c_void_p,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.HANDLE,
]
_kernel32.CreateFileW.restype = wintypes.HANDLE
_kernel32.GetFileInformationByHandle.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(_BY_HANDLE_FILE_INFORMATION),
]
_kernel32.GetFileInformationByHandle.restype = wintypes.BOOL
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL


class PathSafetyError(RuntimeError):
    pass


def is_reparse_point(path: Path) -> bool:
    if path.is_symlink():
        return True
    info = _WIN32_FILE_ATTRIBUTE_DATA()
    if _kernel32.GetFileAttributesExW(
        str(path), _GET_FILE_EX_INFO_STANDARD, ctypes.byref(info)
    ) == 0:
        error = ctypes.get_last_error()
        if error in (_ERROR_FILE_NOT_FOUND, _ERROR_PATH_NOT_FOUND):
            return False
        raise PathSafetyError(f"无法读取路径属性（错误 {error}）")
    return bool(info.dwFileAttributes & _FILE_ATTRIBUTE_REPARSE_POINT)


def has_multiple_hard_links(path: Path) -> bool:
    handle = _kernel32.CreateFileW(
        str(path),
        _FILE_READ_ATTRIBUTES,
        _FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE,
        None,
        _OPEN_EXISTING,
        _FILE_FLAG_BACKUP_SEMANTICS,
        None,
    )
    if handle == _INVALID_HANDLE_VALUE:
        error = ctypes.get_last_error()
        if error in (_ERROR_FILE_NOT_FOUND, _ERROR_PATH_NOT_FOUND):
            return False
        raise PathSafetyError(f"无法读取文件链接信息（错误 {error}）")
    try:
        info = _BY_HANDLE_FILE_INFORMATION()
        if _kernel32.GetFileInformationByHandle(handle, ctypes.byref(info)) == 0:
            raise PathSafetyError("无法读取文件链接计数")
        return int(info.nNumberOfLinks) > 1
    finally:
        _kernel32.CloseHandle(handle)


def ensure_safe_path(path: Path, *, include_self: bool = True) -> None:
    """Reject a reparse point on the path itself and every existing ancestor."""
    raw = Path(path).expanduser().absolute()
    candidates = [raw, *raw.parents] if include_self else list(raw.parents)
    for candidate in candidates:
        if os.path.lexists(candidate) and is_reparse_point(candidate):
            raise PathSafetyError(f"受管路径包含 junction/符号链接：{candidate.name}")


def ensure_safe_tree(root: Path) -> None:
    """Reject links/reparse points/hardlinks anywhere in an extracted tree."""
    ensure_safe_path(root)
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in list(dirnames):
            path = Path(dirpath) / name
            if is_reparse_point(path):
                raise PathSafetyError(f"包内目录是链接或重解析点：{name}")
        for name in filenames:
            path = Path(dirpath) / name
            if is_reparse_point(path):
                raise PathSafetyError(f"包内文件是链接或重解析点：{name}")
            if has_multiple_hard_links(path):
                raise PathSafetyError(f"包内文件存在硬链接：{name}")
