"""Local runtime: data directory, schema readiness, engine and sessions.

The host injects the data directory and one launch's host/port/session
token into the app factory; this runtime resolves absolute paths, baselines
or upgrades the SQLite file with real Alembic, and owns the engine.

D2 W1 additions (engineering spec §2-3, §4.1):
- ``.app-runtime.lock`` exclusive file lock on the data root, held for the
  *full runtime lifetime*. Occupation is decided by the OS exclusive handle
  (share mode 0 on a persistent lock file opened with OPEN_ALWAYS), not by
  file existence: a crashed process that leaves a stale ``.app-runtime.lock``
  can still be reopened. A second instance reports
  ``LOCAL_APP_ALREADY_RUNNING``. Release only closes this runtime's own
  handle; the lock file persists across restarts.
- Independent ``credential_root`` (defaults to the Windows local app data
  credentials directory, injected for tests) used by the credential store.
- Cold upgrade: before any known old-library upgrade, probe exclusive
  database occupation, run a consistent SQLite backup (WAL included) with
  ``integrity_check`` / ``foreign_key_check`` and a version/time/hash
  manifest, then upgrade inside one explicit transaction. Unknown revisions
  are refused without backup or migration.
- Managed DB path rejects reparse-point / hardlink aliases on the raw path
  *before* any ``resolve()`` can swallow reparse information; an
  attribute/open/handle query that fails for any reason other than a definite
  "not found" is a safe refusal. The runtime lock is additionally verified
  through the handle actually acquired (attributes, file type, link count).
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wtypes
import hashlib
import json
import os
import sqlite3
import threading
import weakref
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.local import d1_digest
from app.local.errors import (
    LocalDatabaseStateError,
    LocalStorageError,
    LocalValidationError,
)
from app.local.migrate import (
    D1UpgradeGuard,
    DatabaseInspection,
    alembic_config,
    ensure_local_schema,
    head_revision,
    inspect_database,
)
from app.local.sqlite import (
    DB_FILENAME,
    create_local_engine,
    data_dir_raw,
    resolve_data_dir,
    sqlite_url,
)

_kernel32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)
_advapi32 = ctypes.WinDLL("advapi32.dll", use_last_error=True)


class _WIN32_FILE_ATTRIBUTE_DATA(ctypes.Structure):
    """64-bit-accurate ``WIN32_FILE_ATTRIBUTE_DATA`` for GetFileAttributesExW."""

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


_kernel32.CreateFileW.restype = wtypes.HANDLE
_kernel32.CreateFileW.argtypes = [
    wtypes.LPCWSTR,
    wtypes.DWORD,
    wtypes.DWORD,
    ctypes.c_void_p,
    wtypes.DWORD,
    wtypes.DWORD,
    wtypes.HANDLE,
]

_kernel32.CloseHandle.restype = wtypes.BOOL
_kernel32.CloseHandle.argtypes = [wtypes.HANDLE]

_kernel32.GetFileAttributesExW.restype = wtypes.BOOL
_kernel32.GetFileAttributesExW.argtypes = [
    wtypes.LPCWSTR,
    ctypes.c_int,  # GET_FILEEX_INFO_LEVELS (GetFileExInfoStandard = 0)
    ctypes.POINTER(_WIN32_FILE_ATTRIBUTE_DATA),
]

_kernel32.GetFileInformationByHandle.restype = wtypes.BOOL
_kernel32.GetFileInformationByHandle.argtypes = [
    wtypes.HANDLE,
    ctypes.POINTER(_BY_HANDLE_FILE_INFORMATION),
]

_advapi32.GetNamedSecurityInfoW.restype = wtypes.DWORD
_advapi32.GetNamedSecurityInfoW.argtypes = [
    wtypes.LPCWSTR,
    wtypes.DWORD,
    wtypes.DWORD,
    ctypes.POINTER(ctypes.c_void_p),
    ctypes.POINTER(ctypes.c_void_p),
    ctypes.POINTER(ctypes.c_void_p),
    ctypes.POINTER(ctypes.c_void_p),
    ctypes.POINTER(ctypes.c_void_p),
]

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
FILE_SHARE_DELETE = 0x00000004
OPEN_ALWAYS = 4
OPEN_EXISTING = 3
GET_FILE_EX_INFO_STANDARD = 0
FILE_ATTRIBUTE_DIRECTORY = 0x00000010
FILE_ATTRIBUTE_NORMAL = 0x00000080
FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

# Win32 error codes used to distinguish "the file certainly does not exist"
# (safe to treat as "no alias") from any other failure (must safely refuse).
ERROR_FILE_NOT_FOUND = 2
ERROR_PATH_NOT_FOUND = 3
ERROR_ACCESS_DENIED = 5

SE_FILE_OBJECT = 1
OWNER_SECURITY_INFORMATION = 0x00000001
GROUP_SECURITY_INFORMATION = 0x00000002
DACL_SECURITY_INFORMATION = 0x00000004

LOCK_FILENAME = ".app-runtime.lock"

# ERROR_SHARING_VIOLATION = 32: another process holds an incompatible share.
ERROR_SHARING_VIOLATION = 32
# ERROR_LOCK_VIOLATION = 33: lock conflict.
ERROR_LOCK_VIOLATION = 33

# Only this runtime's own handle may be closed; never a handle held by
# another process or a stale file left by a crashed instance.
_lock_handle_by_root: dict[str, wtypes.HANDLE] = {}


def _is_reparse_point(path: Path) -> bool:
    """True if ``path`` itself is a reparse point (junction/symlink).

    Checked on the raw path *before* any ``Path.resolve()`` can swallow
    reparse information. Only a definite "file/path not found" (Win32 error
    2/3) may be treated as "not a reparse point", because such a path simply
    does not exist yet. An access-denied or any other attribute-query failure
    is a safe refusal: an unverifiable path must never be reported as normal.
    """
    if path.is_symlink():
        return True
    info = _WIN32_FILE_ATTRIBUTE_DATA()
    if (
        _kernel32.GetFileAttributesExW(
            str(path), GET_FILE_EX_INFO_STANDARD, ctypes.byref(info)
        )
        == 0
    ):
        error = ctypes.get_last_error()
        if error in (ERROR_FILE_NOT_FOUND, ERROR_PATH_NOT_FOUND):
            return False
        raise LocalValidationError(f"无法读取路径属性 (错误 {error}): {path}")
    return bool(info.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT)


def _has_multiple_hard_links(path: Path) -> bool:
    """True if an existing file has more than one hard link (nNumberOfLinks).

    A definite "file/path not found" (Win32 error 2/3) means the file does not
    exist yet, so it cannot be a hardlink alias. Any other open or
    handle-information failure is a safe refusal: a file whose link count
    cannot be verified must never be treated as a normal single-link file.
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
        if not _kernel32.GetFileInformationByHandle(handle, ctypes.byref(info)):
            error = ctypes.get_last_error()
            raise LocalValidationError(
                f"无法读取路径句柄信息 (错误 {error}): {path}"
            )
        return info.nNumberOfLinks > 1
    finally:
        _kernel32.CloseHandle(handle)


def _default_credential_root() -> Path:
    """Windows default: %LOCALAPPDATA%\\KindergartenManager\\credentials.

    Fixed for the installed machine; tests inject a temporary root and must
    never touch the production directory.
    """
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return base / "KindergartenManager" / "credentials"


def _absolute_unresolved(path: Path) -> Path:
    """``expanduser`` and make absolute, but never ``resolve()``.

    The unresolved form keeps junction/symlink reparse information on the raw
    path and its ancestors available to the later alias checks.
    """
    path = path.expanduser()
    if not path.is_absolute():
        path = path.absolute()
    return path


def _backup_timestamp() -> str:
    """UTC stamp used in the backup file name (``YYYYMMDDThhmmssZ``)."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _unique_token() -> str:
    """Random name suffix so two backups in the same second never collide."""
    return os.urandom(8).hex()


def _write_fd(handle: int, data) -> int:
    """Thin seam over ``os.write`` (kept small so short writes are testable)."""
    return os.write(handle, data)


def _fsync_fd(handle: int) -> None:
    """Thin seam over ``os.fsync`` (kept small so flush failures are testable)."""
    os.fsync(handle)


def _reserve_exclusive(path: Path) -> None:
    """Create ``path`` exclusively; never overwrite an existing backup."""
    try:
        handle = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
    except FileExistsError as exc:
        raise LocalStorageError(f"备份目标已存在，拒绝覆盖: {path.name}") from exc
    except OSError as exc:
        raise LocalStorageError(
            f"无法创建备份文件 (错误 {exc.errno}): {path.name}"
        ) from exc
    os.close(handle)


def _write_exclusive_bytes(path: Path, data: bytes) -> None:
    """Write ``data`` to a brand-new file; never overwrite an existing one.

    The whole buffer must be written: positive short writes are advanced
    through a loop, and a zero-progress write, any OS error, or a failed
    ``fsync`` refuses the write instead of leaving a truncated/unflushed
    manifest. The file handle is always closed.
    """
    try:
        handle = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise LocalStorageError(f"清单目标已存在，拒绝覆盖: {path.name}") from exc
    except OSError as exc:
        raise LocalStorageError(
            f"无法创建清单文件 (错误 {exc.errno}): {path.name}"
        ) from exc
    try:
        view = memoryview(data)
        written = 0
        while written < len(view):
            try:
                count = _write_fd(handle, view[written:])
            except OSError as exc:
                raise LocalStorageError(
                    f"写入备份清单失败 (错误 {exc.errno}): {path.name}"
                ) from exc
            if not count or count < 0:
                raise LocalStorageError("写入备份清单未完成，拒绝迁移")
            written += count
        try:
            _fsync_fd(handle)
        except OSError as exc:
            raise LocalStorageError("备份清单刷盘失败，拒绝迁移") from exc
    finally:
        os.close(handle)


def _acquire_os_lock(lock_path: Path) -> wtypes.HANDLE:
    """Take an OS-exclusive handle on the persistent lock file.

    Opened with OPEN_ALWAYS so a stale lock file left by a crashed process
    is reused, not rejected. Share mode 0 makes the *handle* the exclusion
    unit: a second process attempting the same open gets
    ERROR_SHARING_VIOLATION and we report LOCAL_APP_ALREADY_RUNNING.
    ``FILE_FLAG_OPEN_REPARSE_POINT`` makes the handle refer to the lock path
    itself, so a reparse-point lock is detected on this very handle instead of
    being silently followed.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = _kernel32.CreateFileW(
        str(lock_path),
        GENERIC_READ | GENERIC_WRITE,
        0,  # share mode 0: exclusive
        None,  # not inheritable
        OPEN_ALWAYS,
        FILE_ATTRIBUTE_NORMAL
        | FILE_FLAG_BACKUP_SEMANTICS
        | FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    if handle != INVALID_HANDLE_VALUE:
        return handle
    error = ctypes.get_last_error()
    if error in (ERROR_SHARING_VIOLATION, ERROR_LOCK_VIOLATION):
        raise LocalDatabaseStateError(
            "LOCAL_APP_ALREADY_RUNNING",
            "本地应用已在运行，数据根已被独占",
        )
    raise LocalDatabaseStateError(
        "LOCAL_APP_ALREADY_RUNNING",
        f"无法取得数据根独占锁 (错误 {error})",
    )


def _release_os_lock(handle: wtypes.HANDLE) -> None:
    """Close only this runtime's own OS handle; never delete the lock file."""
    if handle is not None and handle != INVALID_HANDLE_VALUE:
        try:
            _kernel32.CloseHandle(handle)
        except OSError:
            pass


def _refuse_retired_connection(_dbapi_connection, _record) -> None:
    """Deny a retired SQLAlchemy engine any new DBAPI connection.

    ``Engine.dispose()`` closes the pool but does not make the engine object
    permanently unusable: an old Session can ask it for a new connection.
    The restore boundary therefore retires the old generation explicitly.
    """
    raise RuntimeError("retired local runtime engine cannot reconnect")


def _refuse_retired_creator():
    """Pool creator guard: runs *before* sqlite3 opens/creates any file."""
    raise RuntimeError("retired local runtime engine cannot reconnect")


class LocalRuntime:
    """Owns one data directory and its SQLite engine."""

    def __init__(
        self,
        data_dir: str | Path | None = None,
        *,
        db_path: str | Path | None = None,
        credential_root: str | Path | None = None,
    ):
        if db_path is not None:
            raw_db = _absolute_unresolved(Path(db_path))
            raw_data = raw_db.parent
        else:
            raw_data = _absolute_unresolved(data_dir_raw(data_dir))
            raw_db = raw_data / DB_FILENAME

        # Keep the raw, unresolved paths: the alias check runs on them before
        # any resolve() can swallow reparse information, and prepare() re-checks
        # the very same paths in case they were replaced after construction.
        self._raw_data_dir = raw_data
        self._raw_db_path = raw_db

        # Reject reparse/hardlink aliases on the raw data directory, its
        # ancestors and the raw database family *before* resolve().
        self._check_managed_paths()

        self.data_dir = raw_data.resolve()
        self.db_path = raw_db.resolve()

        # Credential root: expanduser + absolute (but *not* resolve) so the
        # store still sees raw reparse information. It is never validated or
        # refused here (spec §3): credential unavailability must not block the
        # application launch. An explicit root and the default root are treated
        # identically.
        if credential_root is not None:
            self.credential_root = _absolute_unresolved(Path(credential_root))
        else:
            self.credential_root = _absolute_unresolved(
                _default_credential_root()
            )
        self._engine: Engine | None = None
        self._session_factory: sessionmaker[Session] | None = None
        self._inspection: DatabaseInspection | None = None
        self._lock_handle: wtypes.HANDLE | None = None
        self._lock_path: Path | None = None
        self._owns_lock = False
        # Sessions created through this runtime are tracked only so an
        # explicit engine retirement can close them before the DB family is
        # moved.  They never carry business state into the new generation.
        self._session_lock = threading.RLock()
        self._live_sessions: weakref.WeakSet[Session] = weakref.WeakSet()
        # Set when the package prompt-bundle sync fails at startup: only the AI
        # prompt endpoints consult it, so the manual path stays fully usable.
        self.prompt_sync_error: str | None = None
        # Set by the startup restore resolver before migrations/prompt sync.
        self.restore_notice: dict | None = None

    @property
    def prepared(self) -> bool:
        return self._engine is not None

    @property
    def current_revision(self) -> str | None:
        """The current local Alembic revision, read-only (D3-U identity)."""
        return (
            self._inspection.current_revision
            if self._inspection is not None
            else None
        )

    @property
    def engine(self) -> Engine:
        if self._engine is None:
            raise RuntimeError("LocalRuntime.prepare() has not been called")
        return self._engine

    # ------------------------------------------------------------------
    # Raw-path alias checks (engineering spec §4.1)
    # ------------------------------------------------------------------

    def _check_managed_paths(self) -> None:
        """Safe-refuse reparse/hardlink aliases on the managed paths.

        Covers the raw data directory, its existing ancestors (reparse only)
        and the raw database, ``-wal`` and ``-shm`` files (reparse and link
        count), checked before any ``resolve()``. The lock file is deliberately
        *not* opened here: the runtime lock opens it with share mode 0, so a
        second handle — even a read-attribute probe — would turn a legitimate
        "already running" refusal into a misleading path error. The lock is
        verified through the handle actually acquired (``_validate_lock_handle``).
        """
        for ancestor in (self._raw_data_dir, *self._raw_data_dir.parents):
            self._reject_alias(ancestor)
        db = self._raw_db_path
        for managed in (
            db,
            db.with_name(db.name + "-wal"),
            db.with_name(db.name + "-shm"),
        ):
            self._reject_alias(managed)

    def _reject_alias(self, target: Path) -> None:
        """Raise ``LocalValidationError`` for a reparse/hardlink alias path."""
        if _is_reparse_point(target):
            raise LocalValidationError(
                f"路径不得是重解析点、符号链接或硬链接别名: {target}"
            )
        if _has_multiple_hard_links(target):
            raise LocalValidationError(f"路径不得是硬链接别名: {target}")

    def _validate_lock_handle(self) -> None:
        """Verify the acquired lock through its own handle.

        The lock must be a single-link regular file: not a directory, and not a
        junction, symlink or other reparse point. The check lands on the handle
        actually acquired (opened with ``FILE_FLAG_OPEN_REPARSE_POINT``), never a
        second handle. On failure the caller's cleanup closes this handle.
        """
        handle = self._lock_handle
        info = _BY_HANDLE_FILE_INFORMATION()
        if handle is None or not _kernel32.GetFileInformationByHandle(
            handle, ctypes.byref(info)
        ):
            error = ctypes.get_last_error()
            raise LocalValidationError(f"无法校验运行锁文件属性 (错误 {error})")
        if info.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT:
            raise LocalValidationError(
                f"运行锁文件不得是重解析点: {self._lock_path}"
            )
        if info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY:
            raise LocalValidationError(
                f"运行锁路径不是普通文件: {self._lock_path}"
            )
        if info.nNumberOfLinks != 1:
            raise LocalValidationError(
                f"运行锁文件不得是硬链接别名: {self._lock_path}"
            )

    # ------------------------------------------------------------------
    # Exclusive runtime lock (engineering spec §4.1)
    # ------------------------------------------------------------------

    def _acquire_lock(self) -> None:
        """Take the OS-exclusive `.app-runtime.lock` for this lifetime.

        The persistent lock file stays after release; occupation is decided
        by the OS handle, not file existence. Only this runtime's handle is
        ever closed. No per-process re-entrant bypass: two runtimes in the
        same process on the same root both attempt the OS open and one is
        refused (matching production single-instance semantics).
        """
        self._lock_path = self.data_dir / LOCK_FILENAME
        handle = _acquire_os_lock(self._lock_path)
        self._lock_handle = handle
        self._owns_lock = True
        root_key = str(self.data_dir.resolve())
        _lock_handle_by_root[root_key] = handle

    def _release_lock(self) -> None:
        """Close only this runtime's own OS handle; never another's."""
        root_key = str(self.data_dir.resolve())
        if _lock_handle_by_root.get(root_key) is self._lock_handle:
            _lock_handle_by_root.pop(root_key, None)
        _release_os_lock(self._lock_handle)
        self._lock_handle = None
        self._owns_lock = False

    # ------------------------------------------------------------------
    # Cold upgrade guards (engineering spec §2.3)
    # ------------------------------------------------------------------

    def check_database_not_occupied(self) -> None:
        """Probe exclusive database occupation for cold-upgrade safety.

        Raises ``LOCAL_DB_OCCUPIED`` when another process still holds the
        database file. The old instance is never killed; the user must close
        it first.
        """
        if not self.db_path.exists():
            return
        handle = _kernel32.CreateFileW(
            str(self.db_path),
            GENERIC_READ | GENERIC_WRITE,
            0,  # share mode 0: exclusive probe
            None,
            OPEN_EXISTING,
            FILE_ATTRIBUTE_NORMAL | FILE_FLAG_BACKUP_SEMANTICS,
            None,
        )
        if handle != INVALID_HANDLE_VALUE:
            _kernel32.CloseHandle(handle)
            return
        error = ctypes.get_last_error()
        if error in (ERROR_SHARING_VIOLATION, ERROR_LOCK_VIOLATION, 5):
            raise LocalDatabaseStateError(
                "LOCAL_DB_OCCUPIED",
                "数据库被其他进程占用，冷升级前请先关闭旧实例",
            )
        # ERROR_FILE_NOT_FOUND = 2: no database yet, nothing to occupy.
        if error != 2:
            raise LocalDatabaseStateError(
                "LOCAL_DB_OCCUPIED",
                f"无法探测数据库占用状态 (错误 {error})",
            )

    def _check_backup_dir(self, raw_backup_dir: Path) -> None:
        """Refuse a reparse-point backup directory or any raw ancestor.

        Runs on the *raw* (unresolved) path before the directory is created or
        written to, so a ``migration-backups`` junction can never redirect the
        backup elsewhere.
        """
        for candidate in (raw_backup_dir, *raw_backup_dir.parents):
            if _is_reparse_point(candidate):
                raise LocalValidationError(
                    f"备份目录不得是重解析点或符号链接: {candidate}"
                )

    def _write_sqlite_backup(self, backup_path: Path) -> None:
        """Copy the live database with the SQLite backup API (WAL included)."""
        source = sqlite3.connect(str(self.db_path))
        try:
            destination = sqlite3.connect(str(backup_path))
            try:
                source.backup(destination)
            finally:
                destination.close()
        finally:
            source.close()

    def _verify_backup(self, backup_path: Path, source_revision: str) -> None:
        """Verify a freshly written backup: integrity, FK and unique revision.

        The backup handle is closed by the caller's flow before the SHA-256 is
        computed, and the revision must equal the source revision checked just
        before the backup.
        """
        connection = sqlite3.connect(str(backup_path))
        try:
            integrity = connection.execute(
                "PRAGMA integrity_check"
            ).fetchone()[0]
            if integrity != "ok":
                raise LocalStorageError("备份完整性检查失败，已拒绝迁移")
            if connection.execute("PRAGMA foreign_key_check").fetchall():
                raise LocalStorageError("备份外键检查失败，已拒绝迁移")
            if d1_digest.single_revision(connection) != source_revision:
                raise LocalStorageError("备份版本与源库不一致，已拒绝迁移")
        finally:
            connection.close()

    def backup_before_migration(self, source_revision: str) -> Path:
        """Create a consistent pre-upgrade SQLite backup (WAL included).

        Writes to ``data_dir/migration-backups/pre-D2-<UTC>-<random>.sqlite``
        with an exclusive create (never overwrites a same-second/colliding
        file), verifies the backup's ``integrity_check`` /
        ``foreign_key_check`` / unique revision against ``source_revision``,
        closes every backup handle, then computes the SHA-256 and writes a
        manifest with only version, UTC time and hash (also exclusive). Any
        failure raises ``LocalStorageError`` and refuses the migration; the
        original database is never touched and a generated backup is kept.
        """
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self._check_backup_dir(self._raw_data_dir / "migration-backups")
            backup_dir = self.data_dir / "migration-backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
        except LocalValidationError:
            raise
        except OSError as exc:
            raise LocalStorageError("无法创建备份目录，已拒绝迁移") from exc

        stamp = _backup_timestamp()
        token = _unique_token()
        backup_path = backup_dir / f"pre-D2-{stamp}-{token}.sqlite"
        manifest_path = backup_dir / f"pre-D2-{stamp}-{token}.manifest.json"

        _reserve_exclusive(backup_path)
        try:
            self._write_sqlite_backup(backup_path)
            self._verify_backup(backup_path, source_revision)
        except LocalStorageError:
            raise
        except Exception as exc:  # noqa: BLE001 - reported as a storage refusal
            raise LocalStorageError("备份旧数据库失败，已拒绝迁移") from exc

        try:
            digest = hashlib.sha256(backup_path.read_bytes()).hexdigest()
        except OSError as exc:
            raise LocalStorageError("读取备份文件进行校验失败，已拒绝迁移") from exc
        manifest = {
            "version": source_revision,
            "utc": stamp,
            "sha256": digest,
        }
        try:
            _write_exclusive_bytes(
                manifest_path,
                json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
            )
        except LocalStorageError:
            raise
        except Exception as exc:  # noqa: BLE001 - reported as a storage refusal
            raise LocalStorageError("写入备份清单失败，已拒绝迁移") from exc
        return backup_path

    def _build_upgrade_guard(
        self, backup_path: Path, source_revision: str
    ) -> D1UpgradeGuard:
        """Capture the pre-upgrade schema/digest from the verified backup.

        Any OS/SQLite failure while reading the backup is mapped to a safe
        ``LocalStorageError`` (the original cause is kept, never SQL or rows).
        """
        try:
            connection = sqlite3.connect(str(backup_path))
        except sqlite3.Error as exc:
            raise LocalStorageError("无法打开备份数据库进行校验") from exc
        try:
            schema = d1_digest.capture_schema(connection)
            expected = d1_digest.digest(connection, schema)
        except LocalStorageError:
            raise
        except Exception as exc:  # noqa: BLE001 - reported as a storage refusal
            raise LocalStorageError("备份数据库结构无法摘要") from exc
        finally:
            connection.close()
        return D1UpgradeGuard(source_revision, schema, expected)

    def _verify_committed_upgrade(
        self, guard: D1UpgradeGuard, config
    ) -> None:
        """Post-COMMIT read-back: head, integrity/FK and the same D1 digest.

        A failure refuses startup. The already committed database and the
        backup are preserved: nothing is rolled back, restored or stamped.
        Any OS/SQLite failure here is mapped to a safe ``LocalStorageError``
        (original cause kept, no SQL or business content exposed).
        """
        try:
            connection = sqlite3.connect(str(self.db_path))
        except sqlite3.Error as exc:
            raise LocalStorageError("升级后数据库校验无法打开") from exc
        try:
            integrity = connection.execute(
                "PRAGMA integrity_check"
            ).fetchone()[0]
            if integrity != "ok":
                raise LocalStorageError("升级后数据库完整性检查失败")
            if connection.execute("PRAGMA foreign_key_check").fetchall():
                raise LocalStorageError("升级后数据库外键检查失败")
            if d1_digest.single_revision(connection) != head_revision(config):
                raise LocalStorageError("升级后数据库版本异常")
            if (
                d1_digest.digest(connection, guard.schema)
                != guard.expected_digest
            ):
                raise LocalStorageError("升级后旧 D1 数据摘要不一致")
        except LocalStorageError:
            raise
        except Exception as exc:  # noqa: BLE001 - reported as a storage refusal
            raise LocalStorageError("升级后数据库校验失败") from exc
        finally:
            connection.close()

    # ------------------------------------------------------------------
    # Prepare / dispose
    # ------------------------------------------------------------------

    def prepare(self) -> DatabaseInspection:
        """Hold the OS-exclusive runtime lock for the full lifetime.

        Before any schema work: classify the database. For a known old
        revision (non-empty, not already head) probe occupation, back up
        with WAL data, verify revision/integrity/FK, then run the Alembic
        upgrade inside one explicit transaction, and finally re-check D1
        logical summary. Unknown revisions are refused without backup or
        migration. The lock is released only in ``dispose()`` or on a failed
        ``prepare()``.
        """
        if self.prepared:
            # Idempotent: return the already-ready inspection without touching
            # schema, migration, backup or the lock again.
            assert self._inspection is not None
            return self._inspection

        # Re-validate the raw managed paths before the first SQLite check:
        # they may have been replaced with a junction/hardlink alias after
        # construction.
        self._check_managed_paths()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._acquire_lock()
        engine: Engine | None = None
        guard: D1UpgradeGuard | None = None
        try:
            # The lock is verified through the handle just acquired, not a
            # second handle, so a second instance still reports
            # LOCAL_APP_ALREADY_RUNNING rather than a path error.
            self._validate_lock_handle()
            # Restore repair runs while the data-root lock is held, before any
            # schema migration, prompt sync, AI executor, HTTP or UI.
            from app.local.restore_recovery import resolve_startup_restore

            self.restore_notice = resolve_startup_restore(self)
            config = alembic_config(self.db_path)
            inspection = inspect_database(self.db_path, config)

            if inspection.state in ("empty", "current"):
                # Nothing to upgrade: empty DB baselines by ensure path, or
                # already at head. No backup/summary is produced here.
                pass
            elif inspection.state == "upgrade":
                # Known non-empty old revision: cold-upgrade guards apply.
                # Probe real occupation (the old D1 program does not know the
                # runtime lock), take the consistent backup, then build the
                # in-transaction guard from that verified backup.
                self.check_database_not_occupied()
                if not inspection.current_revision:
                    raise LocalDatabaseStateError(
                        "LOCAL_DB_MIGRATION_FAILED",
                        "升级前无法确认旧数据库版本",
                    )
                backup_path = self.backup_before_migration(
                    inspection.current_revision
                )
                guard = self._build_upgrade_guard(
                    backup_path, inspection.current_revision
                )
            elif inspection.state in ("unknown_version",):
                raise LocalDatabaseStateError(
                    "LOCAL_DB_VERSION_UNSUPPORTED",
                    "数据库版本无法识别或来自更新的程序版本",
                )
            elif inspection.state in ("unmanaged", "unreadable"):
                raise LocalDatabaseStateError(
                    "LOCAL_DB_NOT_MANAGED",
                    "数据库文件包含无法识别的数据且没有本地版本记录",
                )

            if guard is None:
                inspection = ensure_local_schema(self.db_path)
            else:
                inspection = ensure_local_schema(
                    self.db_path, d1_guard=guard
                )
                # Post-COMMIT read-back; a failure refuses startup without
                # rolling back the already committed database.
                self._verify_committed_upgrade(guard, config)
            engine = create_local_engine(self.db_path)
            self._session_factory = sessionmaker(
                bind=engine,
                autocommit=False,
                autoflush=False,
                expire_on_commit=False,
            )
            self._engine = engine
            self._inspection = inspection
            self._sync_prompt_bundles_best_effort()
            return inspection
        except BaseException:
            # A partially created engine must not stay half-prepared: close it,
            # clear every handle, and release only this runtime's own lock.
            if engine is not None:
                try:
                    engine.dispose()
                except Exception:  # noqa: BLE001 - never mask the original failure
                    pass
            self._engine = None
            self._session_factory = None
            self._inspection = None
            self._release_lock()
            raise

    def _sync_prompt_bundles_best_effort(self) -> None:
        """Register this build's prompt bundles without blocking the app.

        A failure (e.g. a same-key/different-hash package conflict, or a
        refused contract downgrade) is recorded and only disables the AI prompt
        endpoints; every manual read/edit/save/export path keeps working.
        """
        self.prompt_sync_error = None
        if self._session_factory is None:  # pragma: no cover - caller ensures
            return
        from app.local.errors import LocalError
        from app.local.prompt_bundles import sync_prompt_bundles

        session = self._session_factory()
        try:
            sync_prompt_bundles(session)
        except LocalError as exc:
            self.prompt_sync_error = exc.code
        except Exception:  # noqa: BLE001 - AI-only degradation, never a crash
            self.prompt_sync_error = "PROMPT_SYNC_UNAVAILABLE"
        finally:
            session.close()

    def session(self) -> Session:
        with self._session_lock:
            if self._session_factory is None:
                raise RuntimeError("LocalRuntime.prepare() has not been called")
            session = self._session_factory()
            self._live_sessions.add(session)
            return session

    def _retire_engine(self, engine: Engine | None) -> None:
        """Close live sessions and permanently invalidate one engine generation.

        ``Engine.dispose()`` alone is not enough: an already held Session can
        obtain a fresh connection afterwards and write to whatever path the
        old engine still names.  The pool creator is replaced *before* any
        DBAPI connect, so an old generation cannot even create an empty SQLite
        file during the move gap.  A failure to install that guard is fatal to
        the retirement, never silently ignored.
        """
        if engine is None:
            return
        pool = getattr(engine, "pool", None)
        if pool is None or not hasattr(pool, "_creator"):
            raise RuntimeError("cannot install retired engine connection guard")
        pool._creator = _refuse_retired_creator  # noqa: SLF001 - mandatory guard
        try:
            event.listen(engine, "connect", _refuse_retired_connection)
        except Exception as exc:  # noqa: BLE001 - creator guard is primary
            raise RuntimeError("cannot install retired engine connect guard") from exc
        with self._session_lock:
            sessions = list(self._live_sessions)
            self._live_sessions.clear()
        for session in sessions:
            try:
                session.close()
            except Exception:  # noqa: BLE001 - retirement must not be masked
                pass
        engine.dispose()

    def close_engine_keep_lock(self) -> None:
        """Retire the current engine while retaining the data-root lock.

        Used by B2 restore before the DB family is moved.  The runtime object
        and ``.app-runtime.lock`` handle stay alive; only the engine family is
        invalidated.  ``reopen_after_restore()`` creates the next generation.
        """
        with self._session_lock:
            engine = self._engine
        if engine is None:
            return
        self._retire_engine(engine)
        with self._session_lock:
            self._engine = None
            self._session_factory = None
            self._inspection = None

    def reopen_after_restore(self) -> DatabaseInspection:
        """Create a new engine generation after a committed restore.

        The caller must still own the same runtime lock.  This is a normal
        local startup inspection on the installed database: no restore
        rollback authority remains, and prompt-bundle sync is the ordinary
        startup write.  A non-current schema is refused rather than silently
        migrated after a committed switch.
        """
        if not self._owns_lock:
            raise RuntimeError("runtime lock is not held by this instance")
        if self._engine is not None:
            raise RuntimeError("runtime engine must be closed before reopen")
        self._check_managed_paths()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        config = alembic_config(self.db_path)
        inspection = inspect_database(self.db_path, config)
        if inspection.state != "current":
            raise LocalDatabaseStateError(
                "LOCAL_RESTORE_REOPEN_FAILED",
                "恢复后的数据库缺失、为空或不是当前受管版本，拒绝打开",
            )
        engine = create_local_engine(self.db_path)
        try:
            session_factory = sessionmaker(
                bind=engine,
                autocommit=False,
                autoflush=False,
                expire_on_commit=False,
            )
            self._session_factory = session_factory
            self._engine = engine
            self._inspection = inspection
            # A new executor must build a new launch identity; never inherit
            # the old generation's launch_id.
            self.launch_id = None
            self._sync_prompt_bundles_best_effort()
            return inspection
        except BaseException:
            self._session_factory = None
            self._engine = None
            self._inspection = None
            self._retire_engine(engine)
            raise

    def dispose(self) -> None:
        """Close the engine generation and release this runtime's own lock.

        Safe to call repeatedly and on an unprepared instance (which never owns
        the lock, so another holder is unaffected). The lock is released even
        when engine retirement raises, so the exclusive handle is never
        leaked; a real dispose error still propagates.
        """
        with self._session_lock:
            engine = self._engine
            self._engine = None
            self._session_factory = None
            self._inspection = None
        try:
            self._retire_engine(engine)
        finally:
            if self._owns_lock:
                self._release_lock()
