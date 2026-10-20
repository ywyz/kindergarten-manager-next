"""D2 W1 R03: raw root / managed-path alias checks, lock and lifecycle.

R03-A covers raw roots and credential roots before resolve (real Windows
junctions, ``KGM_LOCAL_DATA_DIR``, tilde/USERPROFILE, explicit and default
credential roots). R03-B/C add: real hard links on the managed DB / WAL / SHM
/ lock files, fail-closed Win32 path-API fault injection, the final lock
handle verification, ``prepare`` idempotency and partial-initialisation
cleanup, ``dispose`` semantics, harmonised path checks (check-then-resolve),
and real two-process mutual exclusion.

Every test root lives under ``%TEMP%/kgm-d2-w1-*`` and every runtime gets an
explicit synthetic ``credential_root``; the real production ``%LOCALAPPDATA%``
and real credentials are never touched. Real junctions use ``cmd /c mklink /J``
with an ``is_junction`` assertion; the default credential-root case injects a
synthetic ``LOCALAPPDATA``.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wtypes
import gc
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch

from app.local import runtime as runtime_module
from app.local.credentials import CredentialStore
from app.local.errors import LocalDatabaseStateError, LocalValidationError
from app.local.runtime import (
    LOCK_FILENAME,
    LocalRuntime,
    _has_multiple_hard_links,
    _is_reparse_point,
)
from app.local.sqlite import DATA_DIR_ENV_VAR
from tests.local.support import BACKEND_DIR, LocalTestCase, worker_env

_FAULT_KERNEL32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)
_FAULT_KERNEL32.GetHandleInformation.restype = wtypes.BOOL
_FAULT_KERNEL32.GetHandleInformation.argtypes = [
    wtypes.HANDLE,
    ctypes.POINTER(wtypes.DWORD),
]
HANDLE_FLAG_INHERIT = 0x00000001

TEST_UUID = "550e8400-e29b-41d4-a716-446655440000"


def _make_junction(link: Path, target: Path) -> None:
    """Create a real directory junction ``link`` -> ``target`` (target must exist)."""
    target.mkdir(parents=True, exist_ok=True)
    if link.exists() or link.is_symlink() or link.is_junction():
        raise AssertionError(f"junction link already exists: {link}")
    completed = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "mklink /J failed rc=%d: %s"
            % (
                completed.returncode,
                completed.stderr.decode("utf-8", "replace"),
            )
        )
    if not link.is_junction():
        raise AssertionError(f"not a junction: {link}")


def _remove_junction(link: Path) -> None:
    """Remove the junction itself without touching its target."""
    os.rmdir(link)


class RuntimeRawRootAliasTests(LocalTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._root = Path(
            tempfile.mkdtemp(prefix="kgm-d2-w1-", dir=Path(tempfile.gettempdir()))
        )
        self.addCleanup(self._cleanup_root)
        self._junctions: list[Path] = []
        self._saved_env: dict[str, str | None] = {}
        self._saved_cwd = os.getcwd()
        self.addCleanup(self._restore_env)
        self.addCleanup(os.chdir, self._saved_cwd)

    def _cleanup_root(self) -> None:
        for link in self._junctions:
            try:
                _remove_junction(link)
            except OSError:
                pass
        shutil.rmtree(self._root, ignore_errors=True)

    def _restore_env(self) -> None:
        for key, value in self._saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _set_env(self, key: str, value: str) -> None:
        self._saved_env[key] = os.environ.get(key)
        os.environ[key] = value

    def _junction(self, link: Path, target: Path) -> Path:
        _make_junction(link, target)
        self._junctions.append(link)
        return link

    def _prepare_normally(self, runtime: LocalRuntime) -> None:
        """A runtime must prepare successfully without touching the credential root."""
        runtime.prepare()
        self.addCleanup(runtime.dispose)

    def test_explicit_data_dir_junction_rejected_before_resolve(self):
        real = self._root / "real-data"
        link = self._root / "link-data"
        self._junction(link, real)
        cred_root = self._root / "cred-explicit"
        with self.assertRaises(LocalValidationError) as caught:
            LocalRuntime(data_dir=link, credential_root=cred_root)
        self.assertIn("重解析点", str(caught.exception))
        # The refused construction creates no credential material.
        self.assertFalse(cred_root.exists())

    def test_env_data_dir_junction_rejected_before_resolve(self):
        real = self._root / "real-env"
        link = self._root / "link-env"
        self._junction(link, real)
        cred_root = self._root / "cred-env"
        self._set_env(DATA_DIR_ENV_VAR, str(link))
        try:
            with self.assertRaises(LocalValidationError) as caught:
                LocalRuntime(credential_root=cred_root)
            self.assertIn("重解析点", str(caught.exception))
        finally:
            self._restore_env()
            self._saved_env.clear()

    def test_db_path_under_junction_rejected(self):
        real = self._root / "real-db"
        link = self._root / "link-db"
        self._junction(link, real)
        cred_root = self._root / "cred-db"
        with self.assertRaises(LocalValidationError) as caught:
            LocalRuntime(
                db_path=link / "kindergarten.db", credential_root=cred_root
            )
        self.assertIn("重解析点", str(caught.exception))

    def test_db_path_tilde_under_userprofile_junction_rejected(self):
        real_profile = self._root / "real-profile"
        link_profile = self._root / "link-profile"
        self._junction(link_profile, real_profile)
        cred_root = self._root / "cred-tilde"
        self._set_env("USERPROFILE", str(link_profile))
        try:
            with self.assertRaises(LocalValidationError) as caught:
                LocalRuntime(db_path="~/tilde/kindergarten.db", credential_root=cred_root)
            self.assertIn("重解析点", str(caught.exception))
        finally:
            self._restore_env()
            self._saved_env.clear()

    def test_explicit_credential_root_junction_kept_unresolved(self):
        data_dir = self._root / "data"
        real = self._root / "real-cred"
        link = self._root / "link-cred"
        self._junction(link, real)
        runtime = LocalRuntime(data_dir=data_dir, credential_root=link)
        # Launch keeps the raw unresolved path.
        self.assertTrue(runtime.credential_root.is_absolute())
        self.assertEqual(runtime.credential_root, link)
        # Prepare succeeds and creates no credential directory or material:
        # the junction target stays empty even though the alias is refused.
        self._prepare_normally(runtime)
        self.assertEqual(list(real.iterdir()), [])
        # The credential store still rejects the raw junction ancestor.
        with self.assertRaises(LocalValidationError):
            CredentialStore(link, TEST_UUID)

    def test_default_credential_root_ancestor_junction_rejected_by_store(self):
        data_dir = self._root / "data"
        synthetic_localappdata = self._root / "synthetic-localappdata"
        synthetic_localappdata.mkdir(parents=True)
        link_appdata = self._root / "link-appdata"
        self._junction(link_appdata, synthetic_localappdata)
        self._set_env("LOCALAPPDATA", str(link_appdata))
        try:
            runtime = LocalRuntime(data_dir=data_dir)
            # Default root keeps the raw unresolved path under the junction.
            self.assertTrue(runtime.credential_root.is_absolute())
            self.assertEqual(
                runtime.credential_root,
                link_appdata / "KindergartenManager" / "credentials",
            )
            # Prepare succeeds and creates no credential directory.
            self._prepare_normally(runtime)
            self.assertFalse(runtime.credential_root.exists())
            # The credential store rejects the raw junction ancestor.
            with self.assertRaises(LocalValidationError):
                CredentialStore(runtime.credential_root, TEST_UUID)
        finally:
            self._restore_env()
            self._saved_env.clear()

    def test_relative_credential_root_kept_unresolved_absolute(self):
        data_dir = self._root / "data"
        work_root = self._root / "work"
        work_root.mkdir()
        previous = os.getcwd()
        os.chdir(work_root)
        try:
            runtime = LocalRuntime(data_dir=data_dir, credential_root="relative-credentials")
            self.assertTrue(runtime.credential_root.is_absolute())
            self.assertEqual(
                runtime.credential_root,
                Path("relative-credentials").absolute(),
            )
            self._prepare_normally(runtime)
        finally:
            os.chdir(previous)

    def test_normal_path_absolutes_and_no_extra_dirs(self):
        data_dir = self._root / "data"
        cred_root = self._root / "cred"
        runtime = LocalRuntime(data_dir=data_dir, credential_root=cred_root)
        self.assertTrue(runtime.data_dir.is_absolute())
        self.assertTrue(runtime.db_path.is_absolute())
        self.assertEqual(runtime.db_path, runtime.data_dir / "kindergarten.db")
        self.assertEqual(runtime.credential_root, cred_root)
        # Construction creates no directory or side file.
        self.assertFalse(data_dir.exists())
        self.assertEqual({entry.name for entry in self._root.iterdir()}, set())


class _D2RootTestCase(unittest.TestCase):
    """Synthetic ``%TEMP%/kgm-d2-w1-*`` root with explicit credential roots.

    No runtime ever uses the default (production) credential root here except
    the dedicated case that injects a synthetic ``LOCALAPPDATA``.
    """

    def setUp(self) -> None:
        super().setUp()
        self._root = Path(
            tempfile.mkdtemp(prefix="kgm-d2-w1-", dir=Path(tempfile.gettempdir()))
        )
        self.addCleanup(shutil.rmtree, self._root, ignore_errors=True)
        self._junctions: list[Path] = []
        self.addCleanup(self._remove_junctions)
        self._runtimes: list[LocalRuntime] = []
        self.addCleanup(self._dispose_runtimes)
        self._processes: list[subprocess.Popen] = []
        self.addCleanup(self._reap_processes)
        self._saved_env: dict[str, str | None] = {}
        self.addCleanup(self._restore_env)

    # -- cleanup ----------------------------------------------------------
    def _remove_junctions(self) -> None:
        for link in reversed(self._junctions):
            try:
                os.rmdir(link)
            except OSError:
                pass

    def _dispose_runtimes(self) -> None:
        for runtime in reversed(self._runtimes):
            try:
                runtime.dispose()
            except Exception:  # noqa: BLE001 - cleanup must not mask failures
                pass

    def _reap_processes(self) -> None:
        for process in self._processes:
            if process.poll() is None:
                process.kill()
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:  # pragma: no cover - defensive
                process.kill()
                process.wait(timeout=30)
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass

    def _restore_env(self) -> None:
        for key, value in self._saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _set_env(self, key: str, value: str) -> None:
        self._saved_env[key] = os.environ.get(key)
        os.environ[key] = value

    # -- fixtures ---------------------------------------------------------
    def _data_dir(self) -> Path:
        return self._root / "data"

    def _cred_root(self) -> Path:
        return self._root / "credentials"

    def _junction(self, link: Path, target: Path) -> Path:
        _make_junction(link, target)
        self._junctions.append(link)
        return link

    def _runtime(
        self,
        data_dir: Path | None = None,
        *,
        db_path: Path | None = None,
        credential_root: Path | None = None,
    ) -> LocalRuntime:
        runtime = LocalRuntime(
            None if db_path is not None else (data_dir or self._data_dir()),
            db_path=db_path,
            credential_root=credential_root or self._cred_root(),
        )
        self._runtimes.append(runtime)
        return runtime


class _FaultKernel32:
    """Proxy around the real kernel32 that fails selected calls.

    Only a definite "not found" (error 2/3) is a legitimate refusal reason; the
    injected access-denied (error 5) must be treated as "cannot verify", never
    as "no alias". ``fail_info_paths`` maps a ``GetFileInformationByHandle``
    failure to the exact path a handle was opened for, so the lock-handle case
    can be isolated from the ordinary file checks.
    """

    def __init__(
        self,
        real,
        *,
        fail_attributes: bool = False,
        fail_create: bool = False,
        fail_info_paths: list[str] | None = None,
    ):
        self._real = real
        self._fail_attributes = fail_attributes
        self._fail_create = fail_create
        self._fail_info_paths = {
            os.path.normcase(path) for path in (fail_info_paths or [])
        }
        self._opened_paths: dict[int, str] = {}

    def GetFileAttributesExW(self, path, level, info):  # noqa: ANN001
        if self._fail_attributes:
            ctypes.set_last_error(runtime_module.ERROR_ACCESS_DENIED)
            return 0
        return self._real.GetFileAttributesExW(path, level, info)

    def CreateFileW(self, path, *args):  # noqa: ANN001
        if self._fail_create:
            ctypes.set_last_error(runtime_module.ERROR_ACCESS_DENIED)
            return runtime_module.INVALID_HANDLE_VALUE
        handle = self._real.CreateFileW(path, *args)
        if handle != runtime_module.INVALID_HANDLE_VALUE:
            self._opened_paths[int(handle)] = os.path.normcase(str(path))
        return handle

    def GetFileInformationByHandle(self, handle, info):  # noqa: ANN001
        if handle is not None:
            recorded = self._opened_paths.get(int(handle))
            if recorded in self._fail_info_paths:
                ctypes.set_last_error(runtime_module.ERROR_ACCESS_DENIED)
                return 0
        return self._real.GetFileInformationByHandle(handle, info)

    def __getattr__(self, name):  # noqa: ANN001
        return getattr(self._real, name)


class ManagedPathAliasTests(_D2RootTestCase):
    """Real hard links on every managed file, plus normal-file usability."""

    def _hardlink(self, source: Path, alias_name: str) -> None:
        alias = source.with_name(alias_name)
        os.link(source, alias)
        self.assertEqual(os.stat(source).st_nlink, 2)

    def test_db_hard_link_alias_rejected_at_prepare(self):
        runtime = self._runtime()
        data = self._data_dir()
        data.mkdir()
        (data / "kindergarten.db").write_bytes(b"")
        self._hardlink(data / "kindergarten.db", "db-alias.bin")
        with self.assertRaises(LocalValidationError) as caught:
            runtime.prepare()
        self.assertIn("硬链接", str(caught.exception))
        self.assertFalse(runtime.prepared)

    def test_wal_hard_link_alias_rejected_at_prepare(self):
        runtime = self._runtime()
        data = self._data_dir()
        data.mkdir()
        (data / "kindergarten.db").write_bytes(b"")
        (data / "kindergarten.db-wal").write_bytes(b"")
        self._hardlink(data / "kindergarten.db-wal", "wal-alias.bin")
        with self.assertRaises(LocalValidationError) as caught:
            runtime.prepare()
        self.assertIn("硬链接", str(caught.exception))

    def test_shm_hard_link_alias_rejected_at_prepare(self):
        runtime = self._runtime()
        data = self._data_dir()
        data.mkdir()
        (data / "kindergarten.db").write_bytes(b"")
        (data / "kindergarten.db-shm").write_bytes(b"")
        self._hardlink(data / "kindergarten.db-shm", "shm-alias.bin")
        with self.assertRaises(LocalValidationError) as caught:
            runtime.prepare()
        self.assertIn("硬链接", str(caught.exception))

    def test_lock_hard_link_alias_rejected_and_handle_released(self):
        runtime = self._runtime()
        data = self._data_dir()
        data.mkdir()
        lock = data / LOCK_FILENAME
        lock.write_bytes(b"")
        self._hardlink(lock, "lock-alias.bin")
        with self.assertRaises(LocalValidationError) as caught:
            runtime.prepare()
        self.assertIn("硬链接", str(caught.exception))
        self.assertFalse(runtime.prepared)
        # The failed attempt must have closed its own handle: remove the alias
        # (back to one link) and a fresh runtime can acquire the same lock.
        (data / "lock-alias.bin").unlink()
        self.assertEqual(os.stat(lock).st_nlink, 1)
        recovered = self._runtime()
        recovered.prepare()
        self.assertTrue(recovered.prepared)

    def test_data_dir_replaced_with_junction_rejected_at_prepare(self):
        runtime = self._runtime()
        real = self._root / "real-data"
        self._junction(self._data_dir(), real)
        with self.assertRaises(LocalValidationError) as caught:
            runtime.prepare()
        self.assertIn("重解析点", str(caught.exception))

    def test_normal_managed_files_are_usable(self):
        runtime = self._runtime()
        inspection = runtime.prepare()
        self.assertTrue(runtime.prepared)
        self.assertEqual(inspection.state, "current")
        data = self._data_dir()
        lock = data / LOCK_FILENAME
        self.assertTrue(lock.is_file())
        self.assertEqual(os.stat(lock).st_nlink, 1)
        runtime.dispose()
        self.assertTrue((data / "kindergarten.db").is_file())
        self.assertFalse(_is_reparse_point(data / "kindergarten.db"))
        self.assertFalse(_has_multiple_hard_links(data / "kindergarten.db"))
        self.assertFalse(_is_reparse_point(lock))
        self.assertFalse(_has_multiple_hard_links(lock))
        for side in ("kindergarten.db-wal", "kindergarten.db-shm"):
            target = data / side
            if target.exists():
                self.assertFalse(_is_reparse_point(target))
                self.assertFalse(_has_multiple_hard_links(target))


class PathApiFaultTests(_D2RootTestCase):
    """A failed Win32 path query with error 5 must safely refuse, not pass."""

    def test_attribute_query_failure_is_safe_refusal(self):
        target = self._root / "existing.bin"
        target.write_bytes(b"x")
        fault = _FaultKernel32(runtime_module._kernel32, fail_attributes=True)
        with patch.object(runtime_module, "_kernel32", fault):
            with self.assertRaises(LocalValidationError):
                _is_reparse_point(target)
            # End to end: constructing a runtime must refuse as well.
            with self.assertRaises(LocalValidationError):
                LocalRuntime(
                    data_dir=self._data_dir(),
                    credential_root=self._cred_root(),
                )

    def test_open_failure_is_safe_refusal(self):
        target = self._root / "existing.bin"
        target.write_bytes(b"x")
        fault = _FaultKernel32(runtime_module._kernel32, fail_create=True)
        with patch.object(runtime_module, "_kernel32", fault):
            with self.assertRaises(LocalValidationError):
                _has_multiple_hard_links(target)

    def test_handle_info_failure_is_safe_refusal(self):
        target = self._root / "existing.bin"
        target.write_bytes(b"x")
        fault = _FaultKernel32(
            runtime_module._kernel32,
            fail_info_paths=[os.path.normcase(str(target))],
        )
        with patch.object(runtime_module, "_kernel32", fault):
            with self.assertRaises(LocalValidationError):
                _has_multiple_hard_links(target)

    def test_lock_handle_info_failure_closes_handle(self):
        runtime = self._runtime()
        lock_path = runtime.data_dir / LOCK_FILENAME
        fault = _FaultKernel32(
            runtime_module._kernel32,
            fail_info_paths=[os.path.normcase(str(lock_path))],
        )
        with patch.object(runtime_module, "_kernel32", fault):
            with self.assertRaises(LocalValidationError) as caught:
                runtime.prepare()
        self.assertIn("运行锁", str(caught.exception))
        self.assertFalse(runtime.prepared)
        self.assertIsNone(runtime._engine)
        # The failed attempt must have closed the handle: a fresh runtime on
        # the same root can acquire and verify the lock normally.
        recovered = self._runtime()
        recovered.prepare()
        self.assertTrue(recovered.prepared)


class RuntimeLifecycleTests(_D2RootTestCase):
    def test_prepare_is_idempotent_and_skips_schema(self):
        runtime = self._runtime()
        calls = {"n": 0}
        real_ensure = runtime_module.ensure_local_schema

        def counting(db_path):
            calls["n"] += 1
            return real_ensure(db_path)

        with patch.object(runtime_module, "ensure_local_schema", counting):
            first = runtime.prepare()
            second = runtime.prepare()
        self.assertEqual(calls["n"], 1)
        self.assertIs(second, first)
        self.assertEqual(second.state, "current")

    def test_sessionmaker_failure_clears_partial_prepare(self):
        runtime = self._runtime()

        def boom(*args, **kwargs):
            raise RuntimeError("injected sessionmaker failure")

        with patch.object(runtime_module, "sessionmaker", boom):
            with self.assertRaises(RuntimeError):
                runtime.prepare()
        self.assertFalse(runtime.prepared)
        self.assertIsNone(runtime._engine)
        self.assertIsNone(runtime._session_factory)
        self.assertIsNone(runtime._inspection)
        with self.assertRaises(RuntimeError):
            runtime.session()
        # The partially created engine and lock were released: a new runtime on
        # the same root prepares normally.
        recovered = self._runtime()
        recovered.prepare()
        self.assertTrue(recovered.prepared)

    def test_unprepared_dispose_does_not_release_holder(self):
        data = self._data_dir()
        holder = self._runtime()
        holder.prepare()
        bystander = self._runtime()
        bystander.dispose()
        bystander.dispose()
        self.assertTrue(holder.prepared)
        # The holder still owns the exclusive lock.
        blocked = self._runtime()
        with self.assertRaises(LocalDatabaseStateError) as caught:
            blocked.prepare()
        self.assertEqual(caught.exception.code, "LOCAL_APP_ALREADY_RUNNING")
        holder.dispose()
        holder.dispose()
        freed = self._runtime()
        freed.prepare()
        self.assertTrue(freed.prepared)
        self.assertEqual(data.name, "data")

    def test_dispose_releases_lock_when_engine_dispose_fails(self):
        runtime = self._runtime()
        runtime.prepare()
        # Hold the real engine: production dispose clears the pointer *before*
        # calling engine.dispose(), so the injected failure would otherwise
        # leak this engine's pool. Guarantee real cleanup via addCleanup so a
        # failing intermediate assertion or recovered.prepare() cannot skip it;
        # cleanups run after the mock context is restored.
        real_engine = runtime.engine
        self.addCleanup(gc.collect)
        self.addCleanup(real_engine.dispose)

        def failing_dispose(self):  # noqa: ANN001
            raise RuntimeError("injected engine dispose failure")

        with patch.object(runtime_module.Engine, "dispose", failing_dispose):
            with self.assertRaises(RuntimeError):
                runtime.dispose()
        self.assertFalse(runtime.prepared)
        recovered = self._runtime()
        recovered.prepare()
        self.assertTrue(recovered.prepared)

    def test_dispose_failure_leaves_no_open_sqlite_connection(self):
        runtime = self._runtime()
        runtime.prepare()
        real_engine = runtime.engine
        self.addCleanup(gc.collect)
        self.addCleanup(real_engine.dispose)

        def failing_dispose(self):  # noqa: ANN001
            raise RuntimeError("injected engine dispose failure")

        with patch.object(runtime_module.Engine, "dispose", failing_dispose):
            with self.assertRaises(RuntimeError):
                runtime.dispose()
        self.assertFalse(runtime.prepared)
        # The fixture itself must not leave an unclosed sqlite3 connection:
        # dispose the real engine, then assert no ResourceWarning appears when
        # the GC runs.
        real_engine.dispose()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            gc.collect()
        leaked = [
            warning
            for warning in caught
            if issubclass(warning.category, ResourceWarning)
            and "sqlite3" in str(warning.message)
        ]
        self.assertEqual(leaked, [])

    def test_lock_handle_is_not_inheritable(self):
        runtime = self._runtime()
        runtime.prepare()
        handle = runtime._lock_handle
        self.assertIsNotNone(handle)
        flags = wtypes.DWORD(0)
        ok = _FAULT_KERNEL32.GetHandleInformation(
            wtypes.HANDLE(handle), ctypes.byref(flags)
        )
        self.assertTrue(ok)
        self.assertEqual(flags.value & HANDLE_FLAG_INHERIT, 0)


class RuntimeLockProcessTests(_D2RootTestCase):
    """Real second processes: refusal, distinct roots, kill-then-reopen."""

    def _spawn(self, spec: dict) -> subprocess.Popen:
        spec_path = self._root / f"lock-{secrets.token_hex(6)}.json"
        spec_path.write_text(json.dumps(spec), encoding="utf-8")
        process = subprocess.Popen(
            [sys.executable, "-m", "tests.local.lock_worker", str(spec_path)],
            cwd=str(BACKEND_DIR),
            env=worker_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._processes.append(process)
        return process

    def _hold_and_wait_ready(self, data_dir: Path, cred_root: Path, tag: str):
        ready_file = self._root / f"{tag}.ready"
        spec = {
            "action": "hold",
            "data_dir": str(data_dir),
            "credential_root": str(cred_root),
            "ready_file": str(ready_file),
            "release_file": str(self._root / f"{tag}.release"),
            "hold_seconds": 120,
            "result_file": str(self._root / f"{tag}.result.json"),
        }
        process = self._spawn(spec)
        deadline = time.time() + 90
        while time.time() < deadline:
            if ready_file.exists():
                return process
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                raise AssertionError(
                    "holder exited early:\n"
                    f"stdout={stdout.decode('utf-8', 'replace')}\n"
                    f"stderr={stderr.decode('utf-8', 'replace')}"
                )
            time.sleep(0.02)
        raise AssertionError("holder did not become ready")

    def _probe(self, data_dir: Path, cred_root: Path) -> dict:
        result_file = self._root / f"probe-{secrets.token_hex(6)}.json"
        spec = {
            "action": "probe",
            "data_dir": str(data_dir),
            "credential_root": str(cred_root),
            "result_file": str(result_file),
        }
        process = self._spawn(spec)
        stdout, stderr = process.communicate(timeout=120)
        self.assertEqual(
            process.returncode,
            0,
            f"probe failed\nstdout={stdout.decode('utf-8', 'replace')}\n"
            f"stderr={stderr.decode('utf-8', 'replace')}",
        )
        return json.loads(result_file.read_text(encoding="utf-8"))

    def test_second_process_same_root_refused_other_root_succeeds(self):
        data = self._data_dir()
        cred = self._cred_root()
        holder = self._hold_and_wait_ready(data, cred, "holder")
        try:
            refused = self._probe(data, cred)
            self.assertEqual(refused["outcome"], "refused")
            self.assertEqual(refused["code"], "LOCAL_APP_ALREADY_RUNNING")

            other = self._probe(self._root / "other-data", self._root / "other-cred")
            self.assertEqual(other["outcome"], "ok")
        finally:
            (self._root / "holder.release").write_text("go", encoding="utf-8")
        stdout, stderr = holder.communicate(timeout=90)
        self.assertEqual(
            holder.returncode,
            0,
            f"holder failed\nstdout={stdout.decode('utf-8', 'replace')}\n"
            f"stderr={stderr.decode('utf-8', 'replace')}",
        )

    def test_lock_released_after_holder_killed(self):
        data = self._data_dir()
        cred = self._cred_root()
        holder = self._hold_and_wait_ready(data, cred, "killed")
        holder.kill()
        holder.wait(timeout=30)
        for stream in (holder.stdout, holder.stderr):
            if stream is not None:
                stream.close()
        probe = self._probe(data, cred)
        self.assertEqual(probe["outcome"], "ok")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()