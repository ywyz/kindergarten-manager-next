"""D2 W1 R04/R05: credential file-level ACL, path and atomic-save hardening.

Covers engineering spec §3 (Windows credential storage):

* Real DPAPI + AES-256-GCM round trips with a non-ASCII test secret and exact
  AAD list ``["kgm-local-ai-v1", database_uuid, profile_id, credential_id,
  key_id]`` (values are never printed).
* Restricted owner/DACL for the managed ``credential_root``, the
  ``<database_uuid>`` directory and the key file, verified with the real
  Windows API on an open handle (``GetSecurityInfo``); adding ``Everyone`` to
  any of the three levels makes read *and* save refuse.
* Fail-closed raw-path checks (only Win32 error 2/3 counts as "absent") and
  same-handle verification of the final key file (type, reparse, link count,
  size, bounded read).
* Fault injection that proves each failure branch fires: attribute/open/handle
  info error 5, root/UUID directory open failure, reparse/hardlink attribute,
  WriteFile fail/short/zero, Flush/Move failure, read-back mismatch and the
  no-clobber target collision. Original targets are hash-stable and temp files
  are cleaned up on every refusal.

Every root lives under ``%TEMP%/kgm-d2-w1-cred-*``; the production
``%LOCALAPPDATA%`` and real credentials are never touched. Real junctions use
``cmd /c mklink /J`` and assert ``is_junction`` (no extra privilege needed);
real hard links use ``os.link``. Cross-user decryption cannot be exercised
without creating another Windows account, which is out of scope, so it is
*not* claimed here.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wtypes
import fnmatch
import hashlib
import os
import secrets
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.local import credentials as cred_module
from app.local.credentials import (
    MAX_BLOB_LEN,
    MASTER_KEY_LEN,
    NONCE_LEN,
    CredentialStore,
    SavedSecret,
)
from app.local.errors import LocalStorageError, LocalValidationError

TEST_UUID = "550e8400-e29b-41d4-a716-446655440000"
OTHER_UUID = "11111111-2222-3333-4444-555555555555"
SID_EVERYONE = "*S-1-1-0"

_INVALID = cred_module.INVALID_HANDLE_VALUE
_ERROR_ACCESS_DENIED = cred_module.ERROR_ACCESS_DENIED
_ERROR_ALREADY_EXISTS = cred_module.ERROR_ALREADY_EXISTS


def _make_junction(link: Path, target: Path) -> None:
    """Create a real directory junction ``link`` -> ``target`` (target exists)."""
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


def _norm(path: Path | str) -> str:
    return os.path.normcase(str(path))


class _FaultKernel32:
    """Proxy around the real kernel32 that fails/alters selected calls.

    Only the recorded ``fired`` counters matter: a test asserts the intended
    injection really triggered, so a branch reached for another reason cannot
    be mistaken for the injected one.
    """

    def __init__(
        self,
        real,
        *,
        fail_attributes_paths=(),
        fail_create_paths=(),
        fail_reparse_paths=(),
        fail_info_paths=(),
        fail_info_reparse_paths=(),
        info_overrides=None,
        write_mode=None,
        read_mode=None,
        fail_flush=False,
        fail_move=False,
        move_error=_ERROR_ACCESS_DENIED,
    ):
        self._real = real
        self._fail_attributes = {_norm(p) for p in fail_attributes_paths}
        self._fail_create = {_norm(p) for p in fail_create_paths}
        self._fail_reparse = {_norm(p) for p in fail_reparse_paths}
        self._fail_info = {_norm(p) for p in fail_info_paths}
        self._fail_info_reparse = {_norm(p) for p in fail_info_reparse_paths}
        self._info_overrides = dict(info_overrides or {})
        self._write_mode = write_mode
        self._read_mode = read_mode
        self._fail_flush = fail_flush
        self._fail_move = fail_move
        self._move_error = move_error
        self._opened: dict[int, str] = {}
        self._opened_reparse: set[int] = set()
        self.fired = {
            "attributes": 0,
            "create": 0,
            "info": 0,
            "override": 0,
            "write": 0,
            "read": 0,
            "flush": 0,
            "move": 0,
        }

    def _override_for(self, raw_path: str) -> dict | None:
        for pattern, override in self._info_overrides.items():
            if fnmatch.fnmatch(raw_path, pattern):
                return override
        return None

    def GetFileAttributesExW(self, path, level, info):  # noqa: ANN001
        if _norm(path) in self._fail_attributes:
            self.fired["attributes"] += 1
            ctypes.set_last_error(_ERROR_ACCESS_DENIED)
            return 0
        return self._real.GetFileAttributesExW(path, level, info)

    def CreateFileW(self, path, *args):  # noqa: ANN001
        key = _norm(path)
        if key in self._fail_create:
            self.fired["create"] += 1
            ctypes.set_last_error(_ERROR_ACCESS_DENIED)
            return _INVALID
        flags = args[4] if len(args) > 4 else 0
        reparse_open = bool(flags & cred_module.FILE_FLAG_OPEN_REPARSE_POINT)
        if reparse_open and key in self._fail_reparse:
            self.fired["create"] += 1
            ctypes.set_last_error(_ERROR_ACCESS_DENIED)
            return _INVALID
        handle = self._real.CreateFileW(path, *args)
        if handle != _INVALID:
            self._opened[int(handle)] = str(path)
            if reparse_open:
                self._opened_reparse.add(int(handle))
        return handle

    def GetFileInformationByHandle(self, handle, info):  # noqa: ANN001
        recorded = self._opened.get(int(handle)) if handle is not None else None
        if recorded is not None and _norm(recorded) in self._fail_info:
            self.fired["info"] += 1
            ctypes.set_last_error(_ERROR_ACCESS_DENIED)
            return 0
        if (
            handle is not None
            and int(handle) in self._opened_reparse
            and recorded is not None
            and _norm(recorded) in self._fail_info_reparse
        ):
            self.fired["info"] += 1
            ctypes.set_last_error(_ERROR_ACCESS_DENIED)
            return 0
        ok = self._real.GetFileInformationByHandle(handle, info)
        if ok and recorded is not None:
            override = self._override_for(recorded)
            if override:
                self.fired["override"] += 1
                if override.get("reparse"):
                    info.dwFileAttributes |= cred_module.FILE_ATTRIBUTE_REPARSE_POINT
                if "links" in override:
                    info.nNumberOfLinks = override["links"]
        return ok

    def WriteFile(self, handle, buf, size, written, overlapped):  # noqa: ANN001
        if self._write_mode is not None:
            self.fired["write"] += 1
            if self._write_mode == "fail":
                ctypes.set_last_error(_ERROR_ACCESS_DENIED)
                return 0
            if self._write_mode == "zero":
                written.value = 0
                return 1
            if self._write_mode == "short":
                # Really write one byte so the loop must advance repeatedly.
                return self._real.WriteFile(handle, buf, 1, written, overlapped)
        return self._real.WriteFile(handle, buf, size, written, overlapped)

    def ReadFile(self, handle, buf, size, read, overlapped):  # noqa: ANN001
        if self._read_mode == "zero":
            self.fired["read"] += 1
            read.value = 0
            return 1
        return self._real.ReadFile(handle, buf, size, read, overlapped)

    def FlushFileBuffers(self, handle):  # noqa: ANN001
        if self._fail_flush:
            self.fired["flush"] += 1
            ctypes.set_last_error(_ERROR_ACCESS_DENIED)
            return 0
        return self._real.FlushFileBuffers(handle)

    def MoveFileExW(self, src, dst, flags):  # noqa: ANN001
        if self._fail_move:
            self.fired["move"] += 1
            ctypes.set_last_error(self._move_error)
            return 0
        return self._real.MoveFileExW(src, dst, flags)

    def __getattr__(self, name):  # noqa: ANN001
        return getattr(self._real, name)


class _CredentialCase(unittest.TestCase):
    """Synthetic ``%TEMP%/kgm-d2-w1-cred-*`` root with an injected credential root."""

    def setUp(self) -> None:
        super().setUp()
        self._root = Path(
            tempfile.mkdtemp(prefix="kgm-d2-w1-cred-", dir=Path(tempfile.gettempdir()))
        )
        self._junctions: list[Path] = []
        self.addCleanup(self._cleanup_root)
        self.cred_root = self._root / "credentials"
        self.store = CredentialStore(self.cred_root, TEST_UUID)

    def _cleanup_root(self) -> None:
        for link in reversed(self._junctions):
            try:
                os.rmdir(link)
            except OSError:
                pass
        shutil.rmtree(self._root, ignore_errors=True)

    def _junction(self, link: Path, target: Path) -> Path:
        _make_junction(link, target)
        self._junctions.append(link)
        return link

    # -- fixtures ---------------------------------------------------------
    def _key_dir(self, uuid: str = TEST_UUID) -> Path:
        return self.cred_root / uuid

    def _key_file(self, key_id: str, uuid: str = TEST_UUID) -> Path:
        return self._key_dir(uuid) / f"{key_id}.dpapi"

    def _temp_files(self) -> list[Path]:
        directory = self._key_dir()
        if not directory.is_dir():
            return []
        return sorted(directory.glob(".tmp-*.dpapi"))

    def _sha256(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _tree_snapshot(self) -> dict[str, str]:
        snapshot: dict[str, str] = {}
        for path in sorted(self._root.rglob("*")):
            rel = str(path.relative_to(self._root))
            snapshot[rel] = self._sha256(path) if path.is_file() else "<dir>"
        return snapshot

    def _grant_everyone(self, path: Path) -> None:
        completed = subprocess.run(
            ["icacls", str(path), "/grant", f"{SID_EVERYONE}:(F)"],
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            raise AssertionError(
                "icacls grant failed: "
                + completed.stderr.decode("utf-8", "replace")
            )

    def _patch_kernel(self, **kwargs):
        fault = _FaultKernel32(cred_module._kernel32, **kwargs)
        return patch.object(cred_module, "_kernel32", fault), fault


class CryptoRoundTripTests(_CredentialCase):
    """Real DPAPI + AES-256-GCM positive evidence (no mocks)."""

    def test_master_key_roundtrip_and_sizes(self):
        self.assertEqual((MASTER_KEY_LEN, NONCE_LEN), (32, 12))
        master = self.store.save_master_key("key_1")
        self.assertEqual(len(master), MASTER_KEY_LEN)
        self.assertEqual(self.store.load_master_key("key_1"), master)
        # A second key is a different random 32-byte value persisted separately.
        master2 = self.store.save_master_key("key_2")
        self.assertNotEqual(master, master2)
        self.assertEqual(self.store.load_master_key("key_2"), master2)

    def test_aes_gcm_roundtrip_non_ascii_secret(self):
        master = self.store.save_master_key("key_1")
        secret = "sëcret-秘密-🔑"
        saved = self.store.encrypt_secret(master, secret, "prof-1", "cred-1", "key_1")
        self.assertIsInstance(saved, SavedSecret)
        self.assertEqual(len(saved.nonce), NONCE_LEN)
        self.assertEqual(len(saved.ciphertext), len(secret.encode("utf-8")) + 16)
        self.assertEqual(
            self.store.decrypt_secret(master, saved, "prof-1", "cred-1"), secret
        )

    def test_aad_binds_profile_credential_and_key_id(self):
        master = self.store.save_master_key("key_1")
        saved = self.store.encrypt_secret(master, "top-secret", "prof-1", "cred-1", "key_1")
        for label, profile, credential in (
            ("profile", "prof-2", "cred-1"),
            ("credential", "prof-1", "cred-2"),
        ):
            with self.subTest(field=label):
                with self.assertRaises(Exception):  # aesgcm.InvalidTag
                    self.store.decrypt_secret(master, saved, profile, credential)
        mismatched_key = SavedSecret("key_2", saved.nonce, saved.ciphertext)
        with self.assertRaises(Exception):
            self.store.decrypt_secret(master, mismatched_key, "prof-1", "cred-1")


class RestrictedAclTests(_CredentialCase):
    """Real owner/DACL evidence for both managed dirs and the key file."""

    def test_created_dirs_and_file_have_restricted_owner_and_dacl(self):
        self.store.save_master_key("key_1")
        owner_sid = cred_module._current_user_sid()
        # A successful verified open proves owner == current user and a
        # protected non-NULL DACL granting only SYSTEM + the current user.
        root_handle = cred_module._open_managed_dir(self.cred_root, owner_sid)
        try:
            dir_handle = cred_module._open_managed_dir(self._key_dir(), owner_sid)
            try:
                file_handle = cred_module._open_verified_file(
                    self._key_file("key_1"), owner_sid, "密钥文件"
                )
                cred_module._kernel32.CloseHandle(file_handle)
            finally:
                cred_module._kernel32.CloseHandle(dir_handle)
        finally:
            cred_module._kernel32.CloseHandle(root_handle)

    def test_everyone_on_root_dir_is_rejected_for_read_and_save(self):
        self.store.save_master_key("key_1")
        self._grant_everyone(self.cred_root)
        with self.assertRaises((LocalStorageError, LocalValidationError)):
            self.store.load_master_key("key_1")
        with self.assertRaises((LocalStorageError, LocalValidationError)):
            self.store.save_master_key("key_2")
        self.assertFalse(self._key_file("key_2").exists())

    def test_everyone_on_uuid_dir_is_rejected_for_read_and_save(self):
        self.store.save_master_key("key_1")
        self._grant_everyone(self._key_dir())
        with self.assertRaises((LocalStorageError, LocalValidationError)):
            self.store.load_master_key("key_1")
        with self.assertRaises((LocalStorageError, LocalValidationError)):
            self.store.save_master_key("key_2")
        self.assertFalse(self._key_file("key_2").exists())

    def test_everyone_on_key_file_rejects_read_but_new_key_save_works(self):
        self.store.save_master_key("key_1")
        self._grant_everyone(self._key_file("key_1"))
        with self.assertRaises((LocalStorageError, LocalValidationError)):
            self.store.load_master_key("key_1")
        # The managed directories are still safe, so the explicit re-fill
        # recovery path (a brand-new key_id) must still work.
        master = self.store.save_master_key("key_2")
        self.assertEqual(self.store.load_master_key("key_2"), master)
        # Reusing the existing (bad) key_id is still refused.
        with self.assertRaises(LocalValidationError):
            self.store.save_master_key("key_1")

    def test_get_style_read_has_no_side_effects(self):
        self.store.save_master_key("key_1")
        before = self._tree_snapshot()
        self.assertEqual(len(self.store.load_master_key("key_1")), MASTER_KEY_LEN)
        self.assertEqual(self._tree_snapshot(), before)
        # Constructing a store and loading never create the root either.
        missing_root = self._root / "never-created"
        missing = CredentialStore(missing_root, TEST_UUID)
        with self.assertRaises(LocalStorageError):
            missing.load_master_key("key_1")
        self.assertFalse(missing_root.exists())


class PathAliasTests(_CredentialCase):
    """Real junction / hardlink rejection."""

    def test_real_junction_credential_root_rejected_at_construct(self):
        real = self._root / "real-creds"
        real.mkdir()
        link = self._junction(self._root / "link-creds", real)
        with self.assertRaises(LocalValidationError):
            CredentialStore(link, TEST_UUID)

    def test_real_junction_uuid_dir_rejected(self):
        # Create the restricted credential root under a different UUID first.
        CredentialStore(self.cred_root, OTHER_UUID).save_master_key("seed")
        target = self._root / "elsewhere"
        self._junction(self._key_dir(), target)
        store = CredentialStore(self.cred_root, TEST_UUID)
        with self.assertRaises(LocalValidationError):
            store.save_master_key("key_1")
        # The junction target stays empty: nothing was written through it.
        self.assertEqual(list(target.iterdir()), [])

    def test_real_hardlink_key_file_rejected_on_load(self):
        self.store.save_master_key("key_1")
        key_file = self._key_file("key_1")
        os.link(key_file, self._key_dir() / "alias.dpapi")
        self.assertEqual(os.stat(key_file).st_nlink, 2)
        with self.assertRaises(LocalValidationError):
            self.store.load_master_key("key_1")
        # Only the aliased file is refused; a fresh key_id can still be saved
        # because the managed directories themselves remain safe.
        master = self.store.save_master_key("key_2")
        self.assertEqual(self.store.load_master_key("key_2"), master)


class ReadIntegrityTests(_CredentialCase):
    """Missing / corrupt / wrong-size / empty blobs are refused."""

    def test_missing_key_file_rejected(self):
        self.store.save_master_key("key_1")
        self._key_file("key_1").unlink()
        with self.assertRaises(LocalStorageError):
            self.store.load_master_key("key_1")

    def test_missing_managed_dir_rejected(self):
        with self.assertRaises(LocalStorageError):
            self.store.load_master_key("key_1")
        self.assertFalse(self.cred_root.exists())

    def test_corrupt_blob_rejected(self):
        self.store.save_master_key("key_1")
        self._key_file("key_1").write_bytes(b"not-a-dpapi-blob")
        with self.assertRaises(LocalStorageError):
            self.store.load_master_key("key_1")

    def test_wrong_master_length_rejected(self):
        self.store.save_master_key("key_1")
        blob = cred_module._dpapi_protect(b"\x01" * 16, "wrong-length")
        self._key_file("key_1").write_bytes(blob)
        with self.assertRaises(LocalStorageError):
            self.store.load_master_key("key_1")

    def test_overlong_blob_rejected(self):
        self.store.save_master_key("key_1")
        self._key_file("key_1").write_bytes(b"\x00" * (MAX_BLOB_LEN + 1))
        with self.assertRaises(LocalStorageError):
            self.store.load_master_key("key_1")

    def test_empty_blob_rejected(self):
        self.store.save_master_key("key_1")
        self._key_file("key_1").write_bytes(b"")
        with self.assertRaises(LocalStorageError):
            self.store.load_master_key("key_1")


class WritePathFaultTests(_CredentialCase):
    """Each injected failure branch must fire and refuse safely."""

    def test_attribute_query_failure_is_refusal(self):
        target = self._root / "existing.bin"
        target.write_bytes(b"x")
        patcher, fault = self._patch_kernel(fail_attributes_paths=[target])
        with patcher:
            with self.assertRaises(LocalValidationError):
                cred_module._is_reparse_point(target)
            with self.assertRaises(LocalValidationError):
                CredentialStore(target, TEST_UUID)
        self.assertGreater(fault.fired["attributes"], 0, fault.fired)

    def test_path_alias_open_failure_is_refusal(self):
        target = self._root / "existing.bin"
        target.write_bytes(b"x")
        patcher, fault = self._patch_kernel(fail_create_paths=[target])
        with patcher:
            with self.assertRaises(LocalValidationError):
                cred_module._has_multiple_hard_links(target)
        self.assertGreater(fault.fired["create"], 0, fault.fired)

    def test_path_alias_info_failure_is_refusal(self):
        target = self._root / "existing.bin"
        target.write_bytes(b"x")
        patcher, fault = self._patch_kernel(fail_info_paths=[target])
        with patcher:
            with self.assertRaises(LocalValidationError):
                cred_module._has_multiple_hard_links(target)
        self.assertGreater(fault.fired["info"], 0, fault.fired)

    def test_root_dir_open_failure_rejected(self):
        self.store.save_master_key("key_1")
        patcher, fault = self._patch_kernel(fail_reparse_paths=[self.cred_root])
        with patcher:
            with self.assertRaises(LocalStorageError):
                self.store.load_master_key("key_1")
        self.assertGreater(fault.fired["create"], 0, fault.fired)

    def test_uuid_dir_open_failure_rejected(self):
        self.store.save_master_key("key_1")
        patcher, fault = self._patch_kernel(fail_reparse_paths=[self._key_dir()])
        with patcher:
            with self.assertRaises(LocalStorageError):
                self.store.load_master_key("key_1")
        self.assertGreater(fault.fired["create"], 0, fault.fired)

    def test_handle_info_failure_rejected(self):
        self.store.save_master_key("key_1")
        patcher, fault = self._patch_kernel(
            fail_info_reparse_paths=[self._key_file("key_1")]
        )
        with patcher:
            with self.assertRaises(LocalStorageError):
                self.store.load_master_key("key_1")
        self.assertGreater(fault.fired["info"], 0, fault.fired)

    def test_temp_file_reparse_attribute_rejected(self):
        patcher, fault = self._patch_kernel(
            info_overrides={"*.tmp-*.dpapi": {"reparse": True}}
        )
        with patcher:
            with self.assertRaises(LocalValidationError):
                self.store.save_master_key("key_1")
        self.assertGreater(fault.fired["override"], 0, fault.fired)
        self.assertFalse(self._key_file("key_1").exists())
        self.assertEqual(self._temp_files(), [])

    def test_key_file_reparse_attribute_rejected_on_load(self):
        self.store.save_master_key("key_1")
        patcher, fault = self._patch_kernel(
            info_overrides={"*.dpapi": {"reparse": True}}
        )
        with patcher:
            with self.assertRaises(LocalValidationError):
                self.store.load_master_key("key_1")
        self.assertGreater(fault.fired["override"], 0, fault.fired)

    def test_key_file_hardlink_attribute_rejected_on_load(self):
        self.store.save_master_key("key_1")
        patcher, fault = self._patch_kernel(
            info_overrides={"*.dpapi": {"links": 2}}
        )
        with patcher:
            with self.assertRaises(LocalValidationError):
                self.store.load_master_key("key_1")
        self.assertGreater(fault.fired["override"], 0, fault.fired)

    def test_write_failure_rejected(self):
        patcher, fault = self._patch_kernel(write_mode="fail")
        with patcher:
            with self.assertRaises(LocalStorageError):
                self.store.save_master_key("key_1")
        self.assertGreater(fault.fired["write"], 0, fault.fired)
        self.assertFalse(self._key_file("key_1").exists())
        self.assertEqual(self._temp_files(), [])

    def test_short_writes_are_completed(self):
        patcher, fault = self._patch_kernel(write_mode="short")
        with patcher:
            master = self.store.save_master_key("key_1")
        self.assertGreater(fault.fired["write"], 1, fault.fired)
        # One byte at a time: full blob written, read-back matches.
        self.assertEqual(self.store.load_master_key("key_1"), master)
        self.assertGreater(self._key_file("key_1").stat().st_size, MASTER_KEY_LEN)

    def test_zero_progress_write_rejected(self):
        patcher, fault = self._patch_kernel(write_mode="zero")
        with patcher:
            with self.assertRaises(LocalStorageError):
                self.store.save_master_key("key_1")
        self.assertEqual(fault.fired["write"], 1, fault.fired)
        self.assertFalse(self._key_file("key_1").exists())
        self.assertEqual(self._temp_files(), [])

    def test_flush_failure_rejected(self):
        patcher, fault = self._patch_kernel(fail_flush=True)
        with patcher:
            with self.assertRaises(LocalStorageError):
                self.store.save_master_key("key_1")
        self.assertEqual(fault.fired["flush"], 1, fault.fired)
        self.assertFalse(self._key_file("key_1").exists())
        self.assertEqual(self._temp_files(), [])

    def test_move_failure_rejected_cleans_temp_and_keeps_target(self):
        self.store.save_master_key("key_1")
        before_hash = self._sha256(self._key_file("key_1"))
        patcher, fault = self._patch_kernel(fail_move=True)
        with patcher:
            with self.assertRaises(LocalStorageError):
                self.store.save_master_key("key_2")
        self.assertEqual(fault.fired["move"], 1, fault.fired)
        self.assertFalse(self._key_file("key_2").exists())
        self.assertEqual(self._temp_files(), [])
        self.assertEqual(self._sha256(self._key_file("key_1")), before_hash)

    def test_read_zero_progress_rejected(self):
        master = self.store.save_master_key("key_1")
        patcher, fault = self._patch_kernel(read_mode="zero")
        with patcher:
            with self.assertRaises(LocalStorageError):
                self.store.load_master_key("key_1")
        self.assertEqual(fault.fired["read"], 1, fault.fired)
        self.assertEqual(len(master), MASTER_KEY_LEN)

    def test_readback_mismatch_rejected(self):
        patcher = patch.object(
            cred_module, "_dpapi_unprotect", return_value=b"\x00" * MASTER_KEY_LEN
        )
        with patcher:
            with self.assertRaises(LocalStorageError):
                self.store.save_master_key("key_1")
        # The blob landed but no inconsistent value was reported as success.
        self.assertTrue(self._key_file("key_1").is_file())

    def test_existing_target_not_overwritten_before_write(self):
        master = self.store.save_master_key("key_1")
        before_hash = self._sha256(self._key_file("key_1"))
        with self.assertRaises(LocalValidationError):
            self.store.save_master_key("key_1")
        self.assertEqual(self._sha256(self._key_file("key_1")), before_hash)
        self.assertEqual(self.store.load_master_key("key_1"), master)
        self.assertEqual(self._temp_files(), [])

    def test_move_no_clobber_on_race(self):
        self.store.save_master_key("key_1")
        target = self._key_file("key_1")
        before_hash = self._sha256(target)
        real_raw = cred_module._raw_attributes
        target_key = _norm(target)

        def fake_raw(path):  # noqa: ANN001
            if _norm(path) == target_key:
                return None  # pretend the target is absent -> reach the move
            return real_raw(path)

        with patch.object(cred_module, "_raw_attributes", fake_raw):
            with self.assertRaises(LocalValidationError):
                self.store.save_master_key("key_1")
        self.assertEqual(self._sha256(target), before_hash)
        self.assertEqual(self._temp_files(), [])

    def test_missing_unmanaged_parents_are_created_on_save_only(self):
        nested = self._root / "missing-a" / "missing-b" / "credentials"
        store = CredentialStore(nested, TEST_UUID)
        # Construction and reading never create anything.
        self.assertFalse((self._root / "missing-a").exists())
        with self.assertRaises(LocalStorageError):
            store.load_master_key("key_1")
        self.assertFalse((self._root / "missing-a").exists())
        # Saving creates the missing unmanaged parents (default ACL) and the
        # managed root/uuid directories (restricted DACL).
        master = store.save_master_key("key_1")
        self.assertTrue((self._root / "missing-a" / "missing-b").is_dir())
        owner_sid = cred_module._current_user_sid()
        handle = cred_module._open_managed_dir(nested, owner_sid)
        cred_module._kernel32.CloseHandle(handle)
        self.assertEqual(store.load_master_key("key_1"), master)

    def test_temp_name_collision_does_not_delete_existing_file(self):
        self.store.save_master_key("seed")  # restricted key dir exists
        sentinel = self._key_dir() / ".tmp-fixed.dpapi"
        sentinel.write_bytes(b"pre-existing-sentinel")
        before = self._sha256(sentinel)
        with patch.object(cred_module.secrets, "token_hex", return_value="fixed"):
            with self.assertRaises(LocalStorageError):
                self.store.save_master_key("key_1")
        # The colliding file is never touched and the target is not created.
        self.assertTrue(sentinel.is_file())
        self.assertEqual(self._sha256(sentinel), before)
        self.assertEqual(sentinel.read_bytes(), b"pre-existing-sentinel")
        self.assertFalse(self._key_file("key_1").exists())

    def test_handle_release_allows_recovery_after_failure(self):
        patcher, fault = self._patch_kernel(fail_flush=True)
        with patcher:
            with self.assertRaises(LocalStorageError):
                self.store.save_master_key("key_1")
        self.assertGreater(fault.fired["flush"], 0, fault.fired)
        # All directory handles were released; a fresh save succeeds.
        master = self.store.save_master_key("key_1")
        self.assertEqual(self.store.load_master_key("key_1"), master)


if __name__ == "__main__":
    unittest.main()
