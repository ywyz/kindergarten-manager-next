"""Local AI credential encryption: Windows DPAPI + AES-256-GCM.

Hard rules (engineering spec §3):
- Master key (32 random bytes) is protected by Windows DPAPI (current user,
  UI forbidden) and stored under an injected ``credential_root``, never the
  real teacher directory in tests and never the legacy ``.env``.
- Each secret is encrypted with AES-256-GCM using a random 12-byte nonce;
  AAD is canonical JSON of
  ``["kgm-local-ai-v1", database_uuid, profile_id, credential_id, key_id]``.
- The credential directory and each blob file are created with a restricted
  DACL (current user SID + SYSTEM full control) at creation time via
  SECURITY_ATTRIBUTES; no wide-open write followed by tightening.
- Path safety is fail-closed: every load/save re-checks the *raw* (unresolved)
  path and its ancestors. Only Win32 error 2/3 ("not found") may be treated as
  "does not exist"; any other attribute/open/handle-info failure is a refusal.
  Above ``credential_root`` only alias (reparse/hardlink) checks apply; their
  DACLs are neither required nor modified.
- The managed ``credential_root`` and ``<database_uuid>`` directories are each
  opened, held and verified (owner, protected non-NULL DACL with only SYSTEM +
  the current user, directory type, not a reparse point) for the duration of
  the access, so the final key file is never read through an unverified or
  replaceable directory.
- The final key file is opened once (reparse-follow disabled, no write/delete
  sharing) and its type / reparse / link count / security info is verified on
  that same handle; the size and bounded read also use that handle.
- File save is atomic: restricted temp file in the same directory → full write
  loop → FlushFileBuffers → verify the temp file's security → MoveFileEx to a
  never-before-used key_id path (no overwrite) → read back and unprotect to
  compare with the original 32-byte master.
- Missing / corrupt / wrong-ACL / other-user key files degrade to
  ``ready=false, reason=CREDENTIAL_UNAVAILABLE`` without touching DB state.
- GET解密验证AES-GCM及AAD才ready；GET不创建目录、不修ACL、不新建密钥。
- No old ``.env``, no cloud key chain, no new dependencies beyond the
  already-locked ``cryptography`` package.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wtypes
import hashlib
import json
import re
import secrets
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.local.errors import LocalStorageError, LocalValidationError

# ---------------------------------------------------------------------------
# Windows API constants and ctypes bindings
# ---------------------------------------------------------------------------

CRYPTPROTECT_UI_FORBIDDEN = 0x00000001
CRYPTPROTECT_LOCAL_MACHINE = 0x00000004  # deliberately not used

GENERIC_WRITE = 0x40000000
GENERIC_READ = 0x80000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
FILE_SHARE_DELETE = 0x00000004
CREATE_NEW = 1
OPEN_EXISTING = 3
FILE_ATTRIBUTE_NORMAL = 0x00000080
FILE_ATTRIBUTE_DIRECTORY = 0x00000010
FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
GET_FILE_EX_INFO_STANDARD = 0
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

MOVEFILE_WRITE_THROUGH = 0x00000008

ERROR_ACCESS_DENIED = 5
ERROR_FILE_NOT_FOUND = 2
ERROR_INVALID_HANDLE = 6
ERROR_ALREADY_EXISTS = 183
ERROR_PATH_NOT_FOUND = 3

# Managed directories are held open with read+write sharing: this denies a
# rename/replacement of the directory itself (which needs delete access) while
# still allowing a temp file to be created and moved within it.
_MANAGED_DIR_SHARE = FILE_SHARE_READ | FILE_SHARE_WRITE

# SECURITY_DESCRIPTOR control flags.
SE_DACL_PROTECTED = 0x00001000
SE_DACL_PRESENT = 0x00000004
DACL_SECURITY_INFORMATION = 0x00000004
OWNER_SECURITY_INFORMATION = 0x00000001

# ACE types.
ACCESS_ALLOWED_ACE_TYPE = 0x0
ACCESS_DENIED_ACE_TYPE = 0x1

# ACE access masks.
GENERIC_ALL = 0x10000000
FILE_ALL_ACCESS = 0x001F01FF

# Well-known SIDs.
SID_SYSTEM = "S-1-5-18"

# Key identifier format: 1..64 url-safe opaque characters.
_KEY_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{12}$"
)


def _validate_key_id(key_id: str) -> None:
    if not isinstance(key_id, str) or not _KEY_ID_RE.fullmatch(key_id):
        raise LocalValidationError("key_id 格式不合法")


def _validate_database_uuid(database_uuid: str) -> None:
    if not isinstance(database_uuid, str) or not _UUID_RE.fullmatch(database_uuid):
        raise LocalValidationError("database_uuid 格式不合法")


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wtypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


class _CRYPTPROTECT_PROMPTSTRUCT(ctypes.Structure):
    _fields_ = [
        ("cbSize", wtypes.DWORD),
        ("dwPromptFlags", wtypes.DWORD),
        ("hwnd", wtypes.HWND),
        ("szPrompt", wtypes.LPCWSTR),
    ]


class _SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("nLength", wtypes.DWORD),
        ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", wtypes.BOOL),
    ]


class _ACE_HEADER(ctypes.Structure):
    _fields_ = [
        ("AceType", ctypes.c_byte),
        ("AceFlags", ctypes.c_byte),
        ("AceSize", wtypes.WORD),
    ]


class _ACL(ctypes.Structure):
    _fields_ = [
        ("AclRevision", ctypes.c_byte),
        ("Sbz1", ctypes.c_byte),
        ("AclSize", wtypes.WORD),
        ("AceCount", wtypes.WORD),
        ("Sbz2", wtypes.WORD),
    ]


class _WIN32_FILE_ATTRIBUTE_DATA(ctypes.Structure):
    """64-bit-accurate ``WIN32_FILE_ATTRIBUTE_DATA`` (GetFileAttributesExW)."""

    _fields_ = [
        ("dwFileAttributes", wtypes.DWORD),
        ("ftCreationTime", wtypes.FILETIME),
        ("ftLastAccessTime", wtypes.FILETIME),
        ("ftLastWriteTime", wtypes.FILETIME),
        ("nFileSizeHigh", wtypes.DWORD),
        ("nFileSizeLow", wtypes.DWORD),
    ]


class _BY_HANDLE_FILE_INFORMATION(ctypes.Structure):
    """64-bit-accurate ``BY_HANDLE_FILE_INFORMATION`` (GetFileInformationByHandle)."""

    _fields_ = [
        ("dwFileAttributes", wtypes.DWORD),
        ("ftCreationTime", wtypes.FILETIME),
        ("ftLastAccessTime", wtypes.FILETIME),
        ("ftLastWriteTime", wtypes.FILETIME),
        ("dwVolumeSerialNumber", wtypes.DWORD),
        ("nFileSizeHigh", wtypes.DWORD),
        ("nFileSizeLow", wtypes.DWORD),
        ("nNumberOfLinks", wtypes.DWORD),
        ("nFileIndexHigh", wtypes.DWORD),
        ("nFileIndexLow", wtypes.DWORD),
    ]


_advapi32 = ctypes.WinDLL("advapi32.dll", use_last_error=True)
_crypt32 = ctypes.WinDLL("crypt32.dll", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)

_crypt32.CryptProtectData.restype = wtypes.BOOL
_crypt32.CryptProtectData.argtypes = [
    ctypes.POINTER(_DATA_BLOB),
    wtypes.LPCWSTR,
    ctypes.POINTER(_DATA_BLOB),
    ctypes.c_void_p,
    ctypes.POINTER(_CRYPTPROTECT_PROMPTSTRUCT),
    wtypes.DWORD,
    ctypes.POINTER(_DATA_BLOB),
]

_crypt32.CryptUnprotectData.restype = wtypes.BOOL
_crypt32.CryptUnprotectData.argtypes = [
    ctypes.POINTER(_DATA_BLOB),
    ctypes.POINTER(ctypes.c_wchar_p),
    ctypes.POINTER(_DATA_BLOB),
    ctypes.c_void_p,
    ctypes.POINTER(_CRYPTPROTECT_PROMPTSTRUCT),
    wtypes.DWORD,
    ctypes.POINTER(_DATA_BLOB),
]

_kernel32.LocalFree.restype = ctypes.c_void_p
_kernel32.LocalFree.argtypes = [ctypes.c_void_p]

_kernel32.CreateFileW.restype = wtypes.HANDLE
_kernel32.CreateFileW.argtypes = [
    wtypes.LPCWSTR,
    wtypes.DWORD,
    wtypes.DWORD,
    ctypes.POINTER(_SECURITY_ATTRIBUTES),
    wtypes.DWORD,
    wtypes.DWORD,
    wtypes.HANDLE,
]

_kernel32.WriteFile.restype = wtypes.BOOL
_kernel32.WriteFile.argtypes = [
    wtypes.HANDLE,
    ctypes.c_void_p,
    wtypes.DWORD,
    ctypes.POINTER(wtypes.DWORD),
    ctypes.c_void_p,
]

_kernel32.FlushFileBuffers.restype = wtypes.BOOL
_kernel32.FlushFileBuffers.argtypes = [wtypes.HANDLE]

_kernel32.CloseHandle.restype = wtypes.BOOL
_kernel32.CloseHandle.argtypes = [wtypes.HANDLE]

_kernel32.MoveFileExW.restype = wtypes.BOOL
_kernel32.MoveFileExW.argtypes = [
    wtypes.LPCWSTR,
    wtypes.LPCWSTR,
    wtypes.DWORD,
]

_kernel32.GetFileAttributesExW.restype = wtypes.BOOL
_kernel32.GetFileAttributesExW.argtypes = [
    wtypes.LPCWSTR,
    ctypes.c_int,
    ctypes.POINTER(_WIN32_FILE_ATTRIBUTE_DATA),
]

_kernel32.GetFileInformationByHandle.restype = wtypes.BOOL
_kernel32.GetFileInformationByHandle.argtypes = [
    wtypes.HANDLE,
    ctypes.POINTER(_BY_HANDLE_FILE_INFORMATION),
]

_kernel32.CreateDirectoryW.restype = wtypes.BOOL
_kernel32.CreateDirectoryW.argtypes = [
    wtypes.LPCWSTR,
    ctypes.POINTER(_SECURITY_ATTRIBUTES),
]

_kernel32.ReadFile.restype = wtypes.BOOL
_kernel32.ReadFile.argtypes = [
    wtypes.HANDLE,
    ctypes.c_void_p,
    wtypes.DWORD,
    ctypes.POINTER(wtypes.DWORD),
    ctypes.c_void_p,
]

_kernel32.GetFileSizeEx.restype = wtypes.BOOL
_kernel32.GetFileSizeEx.argtypes = [
    wtypes.HANDLE,
    ctypes.POINTER(ctypes.c_longlong),
]

_advapi32.OpenProcessToken.restype = wtypes.BOOL
_advapi32.OpenProcessToken.argtypes = [
    wtypes.HANDLE,
    wtypes.DWORD,
    ctypes.POINTER(wtypes.HANDLE),
]

_advapi32.GetTokenInformation.restype = wtypes.BOOL
_advapi32.GetTokenInformation.argtypes = [
    wtypes.HANDLE,
    wtypes.DWORD,
    ctypes.c_void_p,
    wtypes.DWORD,
    ctypes.POINTER(wtypes.DWORD),
]

_advapi32.ConvertSidToStringSidW.restype = wtypes.BOOL
_advapi32.ConvertSidToStringSidW.argtypes = [
    ctypes.c_void_p,
    ctypes.POINTER(ctypes.c_wchar_p),
]

_advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wtypes.BOOL
_advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
    wtypes.LPCWSTR,
    wtypes.DWORD,
    ctypes.POINTER(ctypes.c_void_p),
    ctypes.POINTER(wtypes.DWORD),
]

_advapi32.GetSecurityInfo.restype = wtypes.DWORD
_advapi32.GetSecurityInfo.argtypes = [
    wtypes.HANDLE,
    wtypes.DWORD,
    wtypes.DWORD,
    ctypes.POINTER(ctypes.c_void_p),
    ctypes.POINTER(ctypes.c_void_p),
    ctypes.POINTER(ctypes.c_void_p),
    ctypes.POINTER(ctypes.c_void_p),
    ctypes.POINTER(ctypes.c_void_p),
]

_advapi32.GetSecurityDescriptorControl.restype = wtypes.BOOL
_advapi32.GetSecurityDescriptorControl.argtypes = [
    ctypes.c_void_p,
    ctypes.POINTER(wtypes.WORD),
    ctypes.POINTER(wtypes.DWORD),
]

_advapi32.GetSecurityDescriptorDacl.restype = wtypes.BOOL
_advapi32.GetSecurityDescriptorDacl.argtypes = [
    ctypes.c_void_p,
    ctypes.POINTER(wtypes.BOOL),
    ctypes.POINTER(ctypes.c_void_p),
    ctypes.POINTER(wtypes.BOOL),
]


def _current_user_sid() -> str:
    """Return the current user's SID string (S-1-5-21-...)."""
    token = wtypes.HANDLE()
    if not _advapi32.OpenProcessToken(
        _kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token)
    ):  # TOKEN_QUERY
        raise LocalStorageError("无法打开当前进程令牌")
    try:
        needed = wtypes.DWORD()
        _advapi32.GetTokenInformation(token, 1, None, 0, ctypes.byref(needed))
        buf = ctypes.create_string_buffer(needed.value)
        if not _advapi32.GetTokenInformation(
            token, 1, buf, needed.value, ctypes.byref(needed)
        ):
            raise LocalStorageError("无法读取当前用户 SID")
        class _SID_AND_ATTRIBUTES(ctypes.Structure):
            _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wtypes.DWORD)]

        class _TOKEN_USER(ctypes.Structure):
            _fields_ = [("User", _SID_AND_ATTRIBUTES)]

        token_user = ctypes.cast(buf, ctypes.POINTER(_TOKEN_USER)).contents
        sid_ptr = token_user.User.Sid
        sid_string = ctypes.c_wchar_p()
        _advapi32.ConvertSidToStringSidW(sid_ptr, ctypes.byref(sid_string))
        try:
            return sid_string.value
        finally:
            _kernel32.LocalFree(ctypes.cast(sid_string, ctypes.c_void_p))
    finally:
        _kernel32.CloseHandle(token)


def _make_restricted_sddl(owner_sid: str) -> str:
    """SDDL: D:P (protected DACL) + SYSTEM + current user full control."""
    return (
        f"D:P(A;;FA;;;SY)(A;;FA;;;{owner_sid})"
        f"O:{owner_sid}G:S-1-5-32-545"
    )


def _make_security_attributes(owner_sid: str) -> _SECURITY_ATTRIBUTES:
    """Build SECURITY_ATTRIBUTES with a restricted DACL from SDDL."""
    sddl = _make_restricted_sddl(owner_sid)
    sd_ptr = ctypes.c_void_p()
    sd_size = wtypes.DWORD()
    if not _advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        sddl, 1, ctypes.byref(sd_ptr), ctypes.byref(sd_size)
    ):
        raise LocalStorageError("无法构建凭据安全描述符")
    sa = _SECURITY_ATTRIBUTES()
    sa.nLength = ctypes.sizeof(_SECURITY_ATTRIBUTES)
    sa.lpSecurityDescriptor = sd_ptr
    sa.bInheritHandle = False
    return sa


def _free_sa(sa: _SECURITY_ATTRIBUTES) -> None:
    if sa.lpSecurityDescriptor:
        _kernel32.LocalFree(sa.lpSecurityDescriptor)
        sa.lpSecurityDescriptor = None


def _validate_handle_security(
    handle: wtypes.HANDLE, expected_owner_sid: str
) -> None:
    """Validate owner, DACL presence/protection and ACEs via
    GetSecurityInfo + GetSecurityDescriptorControl/GetSecurityDescriptorDacl
    on an already-open handle. Rejects NULL DACL, unprotected DACL, and any
    ACE not granting full control to SYSTEM or the current user only."""
    owner_ptr = ctypes.c_void_p()
    group_ptr = ctypes.c_void_p()
    dacl_ptr = ctypes.c_void_p()
    sacl_ptr = ctypes.c_void_p()
    sd_ptr = ctypes.c_void_p()
    result = _advapi32.GetSecurityInfo(
        handle,
        1,  # SE_FILE_OBJECT
        OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
        ctypes.byref(owner_ptr),
        ctypes.byref(group_ptr),
        ctypes.byref(dacl_ptr),
        ctypes.byref(sacl_ptr),
        ctypes.byref(sd_ptr),
    )
    if result != 0:
        raise LocalStorageError(f"无法读取句柄安全信息 (错误 {result})")
    try:
        # Owner SID.
        owner_sid_str = ctypes.c_wchar_p()
        _advapi32.ConvertSidToStringSidW(owner_ptr, ctypes.byref(owner_sid_str))
        try:
            owner = owner_sid_str.value
        finally:
            _kernel32.LocalFree(ctypes.cast(owner_sid_str, ctypes.c_void_p))
        if owner != expected_owner_sid:
            raise LocalStorageError("凭据路径所有者不符")

        # DACL Present + non-NULL via GetSecurityDescriptorDacl.
        dacl_present = wtypes.BOOL(False)
        dacl = ctypes.c_void_p()
        dacl_defaulted = wtypes.BOOL(False)
        ok = _advapi32.GetSecurityDescriptorDacl(
            sd_ptr,
            ctypes.byref(dacl_present),
            ctypes.byref(dacl),
            ctypes.byref(dacl_defaulted),
        )
        if not ok:
            raise LocalStorageError("无法读取DACL")
        if not dacl_present.value or not dacl.value:
            raise LocalStorageError("凭据路径缺少DACL")

        # DACL protected via GetSecurityDescriptorControl (pControl is WORD).
        control = wtypes.WORD(0)
        revision = wtypes.DWORD(0)
        ok = _advapi32.GetSecurityDescriptorControl(
            sd_ptr, ctypes.byref(control), ctypes.byref(revision)
        )
        if not ok:
            raise LocalStorageError("无法读取安全描述符控制标志")
        if not (control.value & SE_DACL_PROTECTED):
            raise LocalStorageError("凭据路径DACL未设置保护位")

        # Walk DACL ACEs.
        acl = _ACL.from_address(dacl.value)
        ace_base = dacl.value + ctypes.sizeof(_ACL)
        end = dacl.value + acl.AclSize
        found_system = False
        found_user = False
        for _ in range(acl.AceCount):
            if ace_base + ctypes.sizeof(_ACE_HEADER) > end:
                raise LocalStorageError("凭据路径ACE越界")
            ace = _ACE_HEADER.from_address(ace_base)
            if ace.AceType != ACCESS_ALLOWED_ACE_TYPE:
                raise LocalStorageError("凭据路径存在非允许类型ACE")
            if ace_base + ace.AceSize > end:
                raise LocalStorageError("凭据路径ACE越界")
            # Mask follows the 8-byte header for ACCESS_ALLOWED_ACE.
            ace_mask = ctypes.c_uint32.from_address(ace_base + 4).value
            ace_sid_ptr = ctypes.c_void_p(ace_base + 8)
            ace_sid_str = ctypes.c_wchar_p()
            _advapi32.ConvertSidToStringSidW(
                ace_sid_ptr, ctypes.byref(ace_sid_str)
            )
            try:
                ace_sid = ace_sid_str.value
            finally:
                _kernel32.LocalFree(ctypes.cast(ace_sid_str, ctypes.c_void_p))
            if ace_sid == SID_SYSTEM:
                found_system = True
            elif ace_sid == expected_owner_sid:
                found_user = True
            else:
                raise LocalStorageError("凭据路径DACL包含非系统/当前用户ACE")
            # Must grant FILE_ALL_ACCESS (low word), not just GENERIC_ALL.
            if ace_mask & FILE_ALL_ACCESS != FILE_ALL_ACCESS:
                raise LocalStorageError("凭据路径ACE未授予文件完全控制")
            ace_base += ace.AceSize
        if not found_system or not found_user:
            raise LocalStorageError("凭据路径缺少系统或当前用户ACE")
    finally:
        if sd_ptr.value:
            _kernel32.LocalFree(sd_ptr)


# ---------------------------------------------------------------------------
# Fail-closed path / handle checks
# ---------------------------------------------------------------------------

def _raw_attributes(path: Path) -> int | None:
    """Raw attributes of ``path`` (reparse information intact).

    ``None`` means a definite "not found" (Win32 error 2/3), so the path is
    legitimately absent. Any other attribute-query failure is a safe refusal:
    an unverifiable path must never be reported as normal.
    """
    info = _WIN32_FILE_ATTRIBUTE_DATA()
    if _kernel32.GetFileAttributesExW(
        str(path), GET_FILE_EX_INFO_STANDARD, ctypes.byref(info)
    ):
        return int(info.dwFileAttributes)
    error = ctypes.get_last_error()
    if error in (ERROR_FILE_NOT_FOUND, ERROR_PATH_NOT_FOUND):
        return None
    raise LocalValidationError(f"无法读取路径属性 (错误 {error}): {path}")


def _is_reparse_point(path: Path) -> bool:
    """True if ``path`` itself is a reparse point (junction/symlink).

    Only error 2/3 counts as "absent, therefore not a reparse point".
    """
    attributes = _raw_attributes(path)
    if attributes is None:
        return False
    return bool(attributes & FILE_ATTRIBUTE_REPARSE_POINT)


def _has_multiple_hard_links(path: Path) -> bool:
    """True if an existing path has more than one hard link.

    Only error 2/3 (absent) returns ``False``; a failed open or handle-info
    query is a safe refusal.
    """
    handle = _kernel32.CreateFileW(
        str(path),
        GENERIC_READ,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        None,
        OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL | FILE_FLAG_BACKUP_SEMANTICS,
        None,
    )
    if handle == INVALID_HANDLE_VALUE:
        error = ctypes.get_last_error()
        if error in (ERROR_FILE_NOT_FOUND, ERROR_PATH_NOT_FOUND):
            return False
        raise LocalValidationError(
            f"无法打开路径校验硬链接 (错误 {error}): {path}"
        )
    try:
        info = _BY_HANDLE_FILE_INFORMATION()
        if not _kernel32.GetFileInformationByHandle(handle, info):
            error = ctypes.get_last_error()
            raise LocalValidationError(
                f"无法读取路径句柄信息 (错误 {error}): {path}"
            )
        return info.nNumberOfLinks > 1
    finally:
        _kernel32.CloseHandle(handle)


def _validate_raw_aliases(path: Path) -> str:
    """Reject a reparse/hardlink alias on the raw path or any ancestor.

    The raw (unresolved) path is used so junction/symlink information is still
    visible. Above ``credential_root`` the ancestors are only alias-checked:
    their DACLs are neither required nor modified. Returns the current user SID.
    """
    owner_sid = _current_user_sid()
    cursor = path
    while True:
        if _is_reparse_point(cursor):
            raise LocalValidationError(
                f"路径不得是重解析点或符号链接: {cursor}"
            )
        if _has_multiple_hard_links(cursor):
            raise LocalValidationError(f"路径不得是硬链接别名: {cursor}")
        parent = cursor.parent
        if parent == cursor:
            break
        cursor = parent
    return owner_sid


def _verify_dir_handle(handle: wtypes.HANDLE, owner_sid: str) -> None:
    """Verify an open managed-directory handle: directory, not a reparse
    point, and restricted owner/DACL (SYSTEM + current user only)."""
    info = _BY_HANDLE_FILE_INFORMATION()
    if not _kernel32.GetFileInformationByHandle(handle, info):
        error = ctypes.get_last_error()
        raise LocalStorageError(f"无法读取凭据目录句柄信息 (错误 {error})")
    if info.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT:
        raise LocalValidationError("凭据目录不得是重解析点或符号链接")
    if not (info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY):
        raise LocalValidationError("凭据路径不是目录")
    _validate_handle_security(handle, owner_sid)


def _open_managed_dir(raw_dir: Path, owner_sid: str) -> wtypes.HANDLE:
    """Open and verify an existing managed directory, returning a held handle.

    The handle is opened without following a reparse point and held with
    read+write sharing (denies replacement of the directory itself). Missing or
    unsafe directories raise ``LocalStorageError``/``LocalValidationError``.
    """
    handle = _kernel32.CreateFileW(
        str(raw_dir),
        GENERIC_READ,
        _MANAGED_DIR_SHARE,
        None,
        OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL | FILE_FLAG_BACKUP_SEMANTICS
        | FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    if handle == INVALID_HANDLE_VALUE:
        error = ctypes.get_last_error()
        raise LocalStorageError(
            f"无法打开凭据目录 (错误 {error}): {raw_dir.name}"
        )
    try:
        _verify_dir_handle(handle, owner_sid)
    except BaseException:
        _kernel32.CloseHandle(handle)
        raise
    return handle


def _create_managed_dir(raw_dir: Path, owner_sid: str) -> None:
    """Create a managed directory with the restricted DACL in one step."""
    sa = _make_security_attributes(owner_sid)
    try:
        if not _kernel32.CreateDirectoryW(str(raw_dir), ctypes.byref(sa)):
            error = ctypes.get_last_error()
            if error != ERROR_ALREADY_EXISTS:
                raise LocalStorageError(
                    f"无法创建凭据目录 (错误 {error}): {raw_dir.name}"
                )
    finally:
        _free_sa(sa)


def _ensure_unmanaged_parents(raw_dir: Path) -> None:
    """Create missing *unmanaged* ancestor directories above ``raw_dir``.

    Only genuinely absent levels (Win32 error 2/3) are created, with default
    (inherited) ACLs — existing parent directories are never modified and no
    reparse point is ever followed. ``raw_dir`` itself is created separately
    with a restricted DACL.
    """
    missing: list[Path] = []
    cursor = raw_dir.parent
    while True:
        if _raw_attributes(cursor) is not None:
            break
        missing.append(cursor)
        parent = cursor.parent
        if parent == cursor:
            break
        cursor = parent
    for level in reversed(missing):
        if _is_reparse_point(level):
            raise LocalValidationError(
                f"路径不得是重解析点或符号链接: {level}"
            )
        if not _kernel32.CreateDirectoryW(str(level), None):
            error = ctypes.get_last_error()
            if error != ERROR_ALREADY_EXISTS:
                raise LocalStorageError(
                    f"无法创建凭据父目录 (错误 {error}): {level.name}"
                )


def _ensure_managed_dir(raw_dir: Path, owner_sid: str) -> wtypes.HANDLE:
    """Return a held, verified handle for a managed directory.

    The directory is created with a restricted DACL when absent; an existing
    directory is never modified and must already satisfy the owner/DACL and
    type requirements.
    """
    if _raw_attributes(raw_dir) is None:
        _create_managed_dir(raw_dir, owner_sid)
    return _open_managed_dir(raw_dir, owner_sid)


def _verify_regular_file_handle(
    handle: wtypes.HANDLE, owner_sid: str, label: str
) -> None:
    """Verify an open file handle: regular single-link file, not a reparse
    point, with a restricted owner/DACL."""
    info = _BY_HANDLE_FILE_INFORMATION()
    if not _kernel32.GetFileInformationByHandle(handle, info):
        error = ctypes.get_last_error()
        raise LocalStorageError(f"{label}句柄信息读取失败 (错误 {error})")
    if info.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT:
        raise LocalValidationError(f"{label}不得是重解析点或符号链接")
    if info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY:
        raise LocalValidationError(f"{label}不是普通文件")
    if info.nNumberOfLinks != 1:
        raise LocalValidationError(f"{label}不得是硬链接别名")
    _validate_handle_security(handle, owner_sid)


def _open_verified_file(
    path: Path, owner_sid: str, label: str
) -> wtypes.HANDLE:
    """Open a single-link regular file for reading, without following a
    reparse point and denying write/delete sharing, then verify it on the
    very handle that will be read from."""
    handle = _kernel32.CreateFileW(
        str(path),
        GENERIC_READ,
        FILE_SHARE_READ,
        None,
        OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    if handle == INVALID_HANDLE_VALUE:
        error = ctypes.get_last_error()
        raise LocalStorageError(f"无法打开{label} (错误 {error})")
    try:
        _verify_regular_file_handle(handle, owner_sid, label)
    except BaseException:
        _kernel32.CloseHandle(handle)
        raise
    return handle


def _read_file_bounded(handle: wtypes.HANDLE, label: str) -> bytes:
    """Size-cap and read the whole file through an already-verified handle."""
    size = ctypes.c_longlong(0)
    if not _kernel32.GetFileSizeEx(handle, ctypes.byref(size)):
        error = ctypes.get_last_error()
        raise LocalStorageError(f"{label}大小读取失败 (错误 {error})")
    if size.value <= 0:
        raise LocalStorageError(f"{label}长度为 0")
    if size.value > MAX_BLOB_LEN:
        raise LocalStorageError(f"{label}超出允许大小")
    buf = ctypes.create_string_buffer(size.value)
    total = 0
    while total < size.value:
        read = wtypes.DWORD(0)
        if not _kernel32.ReadFile(
            handle,
            ctypes.byref(buf, total),
            size.value - total,
            read,
            None,
        ):
            error = ctypes.get_last_error()
            raise LocalStorageError(f"{label}读取失败 (错误 {error})")
        if read.value == 0:
            raise LocalStorageError(f"{label}读取不完整")
        total += read.value
    return bytes(buf.raw[:total])


# ---------------------------------------------------------------------------
# DPAPI wrapper
# ---------------------------------------------------------------------------

def _dpapi_protect(plaintext: bytes, description: str) -> bytes:
    """Encrypt bytes with DPAPI current-user, UI forbidden. pPromptStruct=None."""
    buf = (ctypes.c_byte * len(plaintext))(*plaintext)
    data_in = _DATA_BLOB(len(plaintext), buf)
    data_out = _DATA_BLOB()
    ok = _crypt32.CryptProtectData(
        ctypes.byref(data_in),
        description,
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(data_out),
    )
    if not ok:
        raise LocalStorageError("DPAPI 保护失败")
    try:
        result = ctypes.string_at(data_out.pbData, data_out.cbData)
    finally:
        _kernel32.LocalFree(data_out.pbData)
    return result


def _dpapi_unprotect(blob: bytes) -> bytes:
    """Decrypt DPAPI-protected bytes (current user). pPromptStruct=None."""
    buf = (ctypes.c_byte * len(blob))(*blob)
    data_in = _DATA_BLOB(len(blob), buf)
    data_out = _DATA_BLOB()
    desc_out = ctypes.c_wchar_p()
    ok = _crypt32.CryptUnprotectData(
        ctypes.byref(data_in),
        ctypes.byref(desc_out),
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(data_out),
    )
    if not ok:
        raise LocalStorageError("DPAPI 解保护失败（密钥材料不可用）")
    try:
        result = ctypes.string_at(data_out.pbData, data_out.cbData)
    finally:
        _kernel32.LocalFree(data_out.pbData)
        if desc_out:
            _kernel32.LocalFree(ctypes.cast(desc_out, ctypes.c_void_p))
    return result


# ---------------------------------------------------------------------------
# Credential store
# ---------------------------------------------------------------------------

CREDENTIAL_SUBDIR = "credentials"
CREDENTIAL_SUFFIX = ".dpapi"
MASTER_KEY_LEN = 32
NONCE_LEN = 12
MAX_BLOB_LEN = 1 << 20  # 1 MiB safety cap
AAD_CONTEXT = ["kgm-local-ai-v1"]


@dataclass(frozen=True)
class SavedSecret:
    key_id: str
    nonce: bytes
    ciphertext: bytes


class CredentialStore:
    """Encrypts and persists AI secrets under an injected credential root.

    Layout::

        <credential_root>/<database_uuid>/<key_id>.dpapi

    Each file contains a DPAPI-protected 32-byte AES-256 master key. The
    master key encrypts individual secrets with AES-256-GCM.
    """

    def __init__(
        self,
        credential_root: str | Path,
        database_uuid: str,
    ) -> None:
        _validate_database_uuid(database_uuid)
        # Preserve the raw absolute path (no resolve yet); ancestors are checked raw.
        root = Path(credential_root)
        if not root.is_absolute():
            raise LocalValidationError("credential_root 必须是绝对路径")
        self.credential_root = root
        self.database_uuid = database_uuid
        self._key_dir = self.credential_root / self.database_uuid
        # Validate the credential root itself for reparse/hardlink before any
        # file access, without creating anything.
        _validate_raw_aliases(self.credential_root)

    def _key_path(self, key_id: str) -> Path:
        _validate_key_id(key_id)
        return self._key_dir / f"{key_id}{CREDENTIAL_SUFFIX}"

    def _master_key_path(self, key_id: str) -> Path:
        _validate_key_id(key_id)
        return self._key_path(key_id)

    def _aad(self, profile_id: str, credential_id: str, key_id: str) -> bytes:
        payload = AAD_CONTEXT + [
            self.database_uuid,
            profile_id,
            credential_id,
            key_id,
        ]
        return json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")

    # -- managed directory handles ---------------------------------------

    def _open_managed_chain(self, owner_sid: str) -> tuple:
        """Open + verify ``credential_root`` and ``<database_uuid>`` and return
        both held handles (root first). Raises when either is missing/unsafe.
        """
        root_handle = _open_managed_dir(self.credential_root, owner_sid)
        try:
            dir_handle = _open_managed_dir(self._key_dir, owner_sid)
        except BaseException:
            _kernel32.CloseHandle(root_handle)
            raise
        return root_handle, dir_handle

    def _ensure_managed_chain(self, owner_sid: str) -> tuple:
        """Create (with restricted DACL) then open + verify both managed dirs.

        Missing *unmanaged* parents above ``credential_root`` are created with
        default ACLs first, so a nested ``credential_root`` (for example
        ``%LOCALAPPDATA%/KindergartenManager/credentials``) can be created on a
        machine where ``KindergartenManager`` does not exist yet. Reading and
        construction never create anything.
        """
        _ensure_unmanaged_parents(self.credential_root)
        root_handle = _ensure_managed_dir(self.credential_root, owner_sid)
        try:
            dir_handle = _ensure_managed_dir(self._key_dir, owner_sid)
        except BaseException:
            _kernel32.CloseHandle(root_handle)
            raise
        return root_handle, dir_handle

    def _write_temp_and_move(
        self, path: Path, data: bytes, owner_sid: str
    ) -> None:
        """Write ``data`` to a restricted temp file in the verified key dir,
        flush, verify, then atomically move it to the never-before-used target.

        A temp file is only ever removed when *this* call created it (CREATE_NEW
        succeeded) and the move did not complete; a name collision or any other
        failure leaves any pre-existing file of that name untouched.
        """
        tmp_path = self._key_dir / f".tmp-{secrets.token_hex(8)}.dpapi"
        sa = _make_security_attributes(owner_sid)
        handle = INVALID_HANDLE_VALUE
        created = False
        moved = False
        try:
            handle = _kernel32.CreateFileW(
                str(tmp_path),
                GENERIC_WRITE,
                0,  # exclusive
                ctypes.byref(sa),
                CREATE_NEW,
                FILE_ATTRIBUTE_NORMAL,
                None,
            )
            if handle == INVALID_HANDLE_VALUE:
                error = ctypes.get_last_error()
                if error == ERROR_ALREADY_EXISTS:
                    raise LocalStorageError("凭据临时文件已存在，拒绝覆盖")
                raise LocalStorageError(
                    f"无法创建凭据临时文件 (错误 {error})"
                )
            created = True
            # Write the whole blob, advancing through positive short writes.
            view = memoryview(data)
            written_total = 0
            while written_total < len(view):
                chunk = bytes(view[written_total:])
                written = wtypes.DWORD(0)
                if not _kernel32.WriteFile(
                    handle, chunk, len(chunk), written, None
                ):
                    raise LocalStorageError("凭据临时文件写入失败")
                if written.value == 0:
                    raise LocalStorageError("凭据临时文件写入未完成")
                written_total += written.value
            if not _kernel32.FlushFileBuffers(handle):
                raise LocalStorageError("凭据临时文件刷盘失败")
            # Close the write handle before re-opening/verifying/moving.
            _kernel32.CloseHandle(handle)
            handle = INVALID_HANDLE_VALUE
            # Re-open the temp file, verify it on the handle, then move without
            # ever replacing an existing target.
            check = _open_verified_file(tmp_path, owner_sid, "凭据临时文件")
            _kernel32.CloseHandle(check)
            if not _kernel32.MoveFileExW(
                str(tmp_path), str(path), MOVEFILE_WRITE_THROUGH
            ):
                error = ctypes.get_last_error()
                if error == ERROR_ALREADY_EXISTS:
                    raise LocalValidationError(
                        f"密钥 ID 已存在，拒绝覆盖: {path.name}"
                    )
                raise LocalStorageError(
                    f"凭据文件原子移动失败 (错误 {error})"
                )
            moved = True
        finally:
            if handle != INVALID_HANDLE_VALUE:
                _kernel32.CloseHandle(handle)
            _free_sa(sa)
            if created and not moved:
                self._discard_temp(tmp_path)

    @staticmethod
    def _discard_temp(tmp_path: Path) -> None:
        """Remove a temp file this process created; never a colliding file."""
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass

    def _atomic_write_restricted(
        self, path: Path, data: bytes, owner_sid: str
    ) -> None:
        root_handle, dir_handle = self._ensure_managed_chain(owner_sid)
        try:
            self._write_temp_and_move(path, data, owner_sid)
        finally:
            _kernel32.CloseHandle(dir_handle)
            _kernel32.CloseHandle(root_handle)

    # -- public operations -----------------------------------------------

    def save_master_key(self, key_id: str) -> bytes:
        """Generate and persist a new random master key under ``key_id``.

        Returns the plaintext master key (caller keeps it in memory only;
        never persisted in plaintext).
        """
        _validate_key_id(key_id)
        path = self._key_path(key_id)
        owner_sid = _validate_raw_aliases(path)
        # Only a never-before-used key_id may be created; never overwrite/reuse.
        if _raw_attributes(path) is not None:
            raise LocalValidationError(f"密钥 ID 已存在: {key_id}")
        master_key = secrets.token_bytes(MASTER_KEY_LEN)
        protected = _dpapi_protect(
            master_key, "KindergartenManager local AI master key"
        )
        self._atomic_write_restricted(path, protected, owner_sid)
        # Read back, unprotect, and compare to the original master key.
        loaded = self.load_master_key(key_id)
        if loaded != master_key:
            raise LocalStorageError("凭据主密钥读回校验不一致")
        return master_key

    def load_master_key(self, key_id: str) -> bytes:
        """Load and unprotect the master key for ``key_id``.

        Validates the raw path chain, the two managed directories (owner,
        protected DACL, type, reparse) and the final key file on the very
        handle used to read it (reparse/type/link count/security, size cap,
        bounded read), then DPAPI-unprotects and requires exactly 32 bytes.
        Creates nothing and never modifies an ACL.
        """
        path = self._master_key_path(key_id)
        owner_sid = _validate_raw_aliases(path)
        root_handle, dir_handle = self._open_managed_chain(owner_sid)
        try:
            handle = _open_verified_file(path, owner_sid, "密钥文件")
            try:
                blob = _read_file_bounded(handle, "密钥文件")
            finally:
                _kernel32.CloseHandle(handle)
        finally:
            _kernel32.CloseHandle(dir_handle)
            _kernel32.CloseHandle(root_handle)
        try:
            key = _dpapi_unprotect(blob)
        except LocalStorageError:
            raise LocalStorageError(f"密钥文件损坏或不可解密: {key_id}")
        if len(key) != MASTER_KEY_LEN:
            raise LocalStorageError(f"密钥材料长度非法: {len(key)}")
        return key

    def encrypt_secret(
        self,
        master_key: bytes,
        secret: str,
        profile_id: str,
        credential_id: str,
        key_id: str,
    ) -> SavedSecret:
        """Encrypt ``secret`` with AES-256-GCM under ``master_key``."""
        aesgcm = AESGCM(master_key)
        nonce = secrets.token_bytes(NONCE_LEN)
        aad = self._aad(profile_id, credential_id, key_id)
        ciphertext = aesgcm.encrypt(nonce, secret.encode("utf-8"), aad)
        return SavedSecret(
            key_id=key_id,
            nonce=nonce,
            ciphertext=ciphertext,
        )

    def decrypt_secret(
        self,
        master_key: bytes,
        saved: SavedSecret,
        profile_id: str,
        credential_id: str,
    ) -> str:
        """Decrypt a saved secret back to plaintext (verifies AAD)."""
        aesgcm = AESGCM(master_key)
        aad = self._aad(profile_id, credential_id, saved.key_id)
        plaintext = aesgcm.decrypt(saved.nonce, saved.ciphertext, aad)
        return plaintext.decode("utf-8")

    def clear_master_key(self, key_id: str) -> None:
        """Remove the protected master key file for ``key_id``.

        Missing file is not an error (idempotent clear). The file is only
        removed after verifying it is a genuine single-link regular file with a
        restricted DACL, so a junction/hardlink alias is never unlinked.
        """
        path = self._master_key_path(key_id)
        owner_sid = _validate_raw_aliases(path)
        if _raw_attributes(path) is None:
            return
        root_handle, dir_handle = self._open_managed_chain(owner_sid)
        try:
            handle = _open_verified_file(path, owner_sid, "密钥文件")
            _kernel32.CloseHandle(handle)
        finally:
            _kernel32.CloseHandle(dir_handle)
            _kernel32.CloseHandle(root_handle)
        path.unlink()


def derive_hmac_key(master_key: bytes, salt: bytes) -> bytes:
    """Derive an independent HMAC key from the random master key (not the
    secret itself) using pbkdf2_hmac (standard library). Used to key the
    operation-request fingerprint so a different secret under the same
    key_id yields a 409 on receipt verification."""
    return hashlib.pbkdf2_hmac("sha256", master_key, salt, 100_000, dklen=32)
