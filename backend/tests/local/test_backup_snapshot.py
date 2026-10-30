"""B1 snapshot/verification tests over real SQLite and managed files.

The fixtures use real JPEG bytes, real SQLite databases and real Windows
handles.  No product path, credential root, real template or old backup is
touched; every root is created by ``LocalTestCase`` under the system temp
directory.
"""

from __future__ import annotations

import ctypes
import hashlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import tracemalloc
import types
from unittest import mock
import uuid
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from alembic import command
from PIL import Image
from sqlalchemy import select, text

from app.local import (
    ai_config_service,
    backup_zip,
    credentials,
    ai_task_service,
    backup_barrier,
    backup_format,
    backup_fs,
    backup_validate,
    daily_plan_service,
    observation_assets,
    observation_service,
    profile_service,
)
from app.local.base import utc_now
from app.local.migrate import alembic_config
from app.local.models import (
    LocalAICredential,
    LocalObservationAsset,
    LocalObservationAssetDerivative,
    LocalProfile,
)
from app.local.normalize import normalize_initialization
from app.local.tx import begin_immediate
from tests.local.support import LocalTestCase, initialize_body


class _PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def working_set_bytes() -> int:
    from ctypes import wintypes

    counters = _PROCESS_MEMORY_COUNTERS()
    counters.cb = ctypes.sizeof(_PROCESS_MEMORY_COUNTERS)
    psapi = ctypes.WinDLL("psapi.dll")
    psapi.GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_PROCESS_MEMORY_COUNTERS),
        wintypes.DWORD,
    ]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    kernel32 = ctypes.WinDLL("kernel32.dll")
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    if not psapi.GetProcessMemoryInfo(
        kernel32.GetCurrentProcess(),
        ctypes.byref(counters),
        counters.cb,
    ):
        raise RuntimeError("GetProcessMemoryInfo failed")
    return int(counters.WorkingSetSize)


class BackupSnapshotCase(LocalTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.runtime = self.make_runtime()
        self.session = self.runtime.session()
        profile_service.initialize(
            self.session, normalize_initialization(**initialize_body())
        )
        self.session.commit()
        self.profile = self.session.scalars(select(LocalProfile)).one()
        self._noise_jpeg: bytes | None = None

    def tearDown(self) -> None:
        self.session.close()
        super().tearDown()
        self.doCleanups()

    def jpeg(self, color=(200, 30, 30), size=(64, 48)) -> bytes:
        buffer = io.BytesIO()
        Image.new("RGB", size, color).save(buffer, "JPEG", quality=90)
        return buffer.getvalue()

    def noise_jpeg(self, size=(400, 300)) -> bytes:
        if self._noise_jpeg is None:
            image = Image.effect_noise(size, 64).convert("RGB")
            buffer = io.BytesIO()
            image.save(buffer, "JPEG", quality=85)
            self._noise_jpeg = buffer.getvalue()
        return self._noise_jpeg

    def create_observation(self, day="2026-09-15") -> str:
        result = observation_service.create_observation(
            self.session,
            profile_id=self.profile.id,
            request_id=str(uuid.uuid4()),
            record_type="public",
            payload={
                "observation_date": day,
                "subjects": [{"name": "小明"}],
                "environment": "积木区",
            },
        )
        return result["observation_id"]

    def import_photo(self, observation_id: str, color=(200, 30, 30)) -> str:
        current = observation_service.read_current(
            self.session, profile_id=self.profile.id, observation_id=observation_id
        )
        result = observation_assets.import_asset(
            self.session,
            self.runtime,
            profile_id=self.profile.id,
            observation_id=observation_id,
            request_id=str(uuid.uuid4()),
            expected_revision=current["revision"],
            stream=io.BytesIO(self.jpeg(color)),
            display_name="观察.jpg",
            caption="观察",
        )
        return result["asset_id"]

    def add_direct_asset(
        self,
        observation_id: str,
        *,
        data: bytes | None = None,
        purpose: str = "ai",
    ) -> tuple[str, Path]:
        data = data if data is not None else self.noise_jpeg()
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
        asset_id = uuid.uuid4().hex[:20]
        asset_dir = (
            self.runtime.data_dir
            / "observations"
            / "assets"
            / observation_id
            / asset_id
        )
        asset_dir.mkdir(parents=True)
        relative = f"observations/assets/{observation_id}/{asset_id}/original.jpg"
        path = self.runtime.data_dir.joinpath(*relative.split("/"))
        path.write_bytes(data)
        self.session.add(
            LocalObservationAsset(
                id=asset_id,
                observation_id=observation_id,
                relative_path=relative,
                display_name="direct.jpg",
                mime_type="image/jpeg",
                content_hash=hashlib.sha256(data).hexdigest(),
                byte_size=len(data),
                width=width,
                height=height,
                orientation=None,
                created_at=utc_now(),
            )
        )
        if purpose:
            derivative_id = uuid.uuid4().hex[:20]
            drelative = (
                f"observations/assets/{observation_id}/{asset_id}/derivatives/"
                f"{derivative_id}.jpg"
            )
            dpath = self.runtime.data_dir.joinpath(*drelative.split("/"))
            dpath.parent.mkdir(parents=True)
            with Image.open(io.BytesIO(data)) as image:
                derivative = image.convert("RGB").resize((160, 120))
                buffer = io.BytesIO()
                derivative.save(buffer, "JPEG", quality=85)
            ddata = buffer.getvalue()
            dpath.write_bytes(ddata)
            self.session.add(
                LocalObservationAssetDerivative(
                    id=derivative_id,
                    observation_id=observation_id,
                    asset_id=asset_id,
                    purpose=purpose,
                    params_version="test-v1",
                    content_hash=hashlib.sha256(ddata).hexdigest(),
                    mime_type="image/jpeg",
                    width=160,
                    height=120,
                    relative_path=drelative,
                    created_at=utc_now(),
                )
            )
        self.session.commit()
        return asset_id, path

    def service(self, **kwargs):
        from app.local.backup_snapshot import SnapshotService

        return SnapshotService(
            self.runtime,
            app_version="0.1.0-test",
            source_identity={"commit": "test", "tree": "test-tree"},
            **kwargs,
        )

    def create_snapshot(self, name="backup.kgmbackup", password=None, **kwargs):
        progress = []
        cancel = threading.Event()
        result = self.service(**kwargs).create(
            self.tmp_root / name,
            password=password,
            cancel=cancel,
            progress=progress.append,
        )
        return result, progress


def _plain_parts(path: Path) -> tuple[bytes, bytes, dict[str, bytes]]:
    raw = path.read_bytes()
    header = backup_format.parse_header(raw[:128], file_size=len(raw))
    payload = raw[128:128 + header.payload_len]
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        manifest_raw = archive.read("manifest.json")
        database = archive.read("db/kindergarten.db")
        resources = {
            name: archive.read(name)
            for name in archive.namelist()
            if name not in ("manifest.json", "db/kindergarten.db")
        }
    return manifest_raw, database, resources


def _write_plain(
    path: Path,
    manifest_raw: bytes,
    database: bytes,
    resources: dict[str, bytes],
    extra: dict[str, bytes] | None = None,
) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("manifest.json", manifest_raw)
        archive.writestr("db/kindergarten.db", database)
        for name in sorted(resources):
            archive.writestr(name, resources[name])
        for name, data in (extra or {}).items():
            archive.writestr(name, data)
    payload = buffer.getvalue()
    header = backup_format.encode_header(mode=1, payload_len=len(payload))
    path.write_bytes(header + payload)


def _assert_rejected(case: BackupSnapshotCase, path: Path) -> None:
    with pytest.raises(
        (backup_format.BackupFormatError, backup_validate.BackupValidationError)
    ):
        case.service().verify(path, password=None, cancel=threading.Event())


def test_plain_snapshot_captures_db_and_all_registered_photos():
    case = BackupSnapshotCase()
    case.setUp()
    try:
        observation_id = case.create_observation()
        first = case.import_photo(observation_id, (200, 30, 30))
        second = case.import_photo(observation_id, (30, 200, 30))
        original_row = case.session.execute(
            text(
                "SELECT relative_path FROM local_observation_assets WHERE id = :id"
            ),
            {"id": first},
        ).one()
        original_path = case.runtime.data_dir.joinpath(*original_row[0].split("/"))
        original_bytes = original_path.read_bytes()
        derivative_row = case.session.execute(
            text(
                "SELECT relative_path FROM local_observation_asset_derivatives "
                "WHERE asset_id = :id LIMIT 1"
            ),
            {"id": first},
        ).one()
        derivative_path = case.runtime.data_dir.joinpath(
            *derivative_row[0].split("/")
        )
        derivative_bytes = derivative_path.read_bytes()
        current = observation_service.read_current(
            case.session, profile_id=case.profile.id, observation_id=observation_id
        )
        observation_assets.remove_photo(
            case.session,
            profile_id=case.profile.id,
            observation_id=observation_id,
            request_id=str(uuid.uuid4()),
            expected_revision=current["revision"],
            asset_id=first,
        )
        current = observation_service.read_current(
            case.session, profile_id=case.profile.id, observation_id=observation_id
        )
        observation_service.save_observation(
            case.session,
            profile_id=case.profile.id,
            observation_id=observation_id,
            request_id=str(uuid.uuid4()),
            expected_revision=current["revision"],
            payload={},
            photos=None,
            save_reason="manual",
        )
        case.add_direct_asset(observation_id)
        result, progress = case.create_snapshot()
        assert original_path.read_bytes() == original_bytes
        assert derivative_path.read_bytes() == derivative_bytes
        assert result.verified is True
        assert result.path.is_file()
        assert any(item.stage == "commit" for item in progress)
        verified = case.service().verify(
            result.path, password=None, cancel=threading.Event()
        )
        try:
            paths = {item["path"] for item in verified.manifest["resources"]}
            assert len(paths) == 8
            assert any(item.endswith("original.jpg") for item in paths)
            assert any("/derivatives/" in item for item in paths)
            # Removed current photo and its historical version still exist.
            assert len(
                [
                    item
                    for item in verified.manifest["resources"]
                    if item["kind"] == "original"
                ]
            ) == 3
            assert len(
                [
                    item
                    for item in verified.manifest["resources"]
                    if item["kind"] == "ai"
                ]
            ) == 3
            connection = sqlite3.connect(str(verified.database_path))
            try:
                assert connection.execute(
                    "SELECT COUNT(*) FROM local_observation_assets"
                ).fetchone()[0] == 3
                assert connection.execute(
                    "SELECT COUNT(*) FROM local_observation_version_photos"
                ).fetchone()[0] >= 1
            finally:
                connection.close()
        finally:
            case.service().discard_verified(verified)
    finally:
        case.tearDown()


def test_password_snapshot_wrong_password_tamper_and_truncation():
    case = BackupSnapshotCase()
    case.setUp()
    try:
        observation_id = case.create_observation()
        case.import_photo(observation_id)
        result, _ = case.create_snapshot("encrypted.kgmbackup", password="correct horse")
        assert result.verified is True
        header, _raw = backup_format.read_header(result.path)
        assert header.mode == backup_format.MODE_PASSWORD
        service = case.service()
        with pytest.raises(backup_format.BackupFormatError) as wrong:
            service.verify(result.path, password="wrong", cancel=threading.Event())
        assert wrong.value.code in ("BACKUP_AUTH_FAILED", "BACKUP_KDF_FAILED")

        tampered = case.tmp_root / "tampered.kgmbackup"
        raw = bytearray(result.path.read_bytes())
        raw[backup_format.HEADER_LEN + 5] ^= 0x01
        tampered.write_bytes(raw)
        with pytest.raises(backup_format.BackupFormatError):
            service.verify(tampered, password="correct horse", cancel=threading.Event())

        truncated = case.tmp_root / "truncated.kgmbackup"
        truncated.write_bytes(result.path.read_bytes()[:-1])
        with pytest.raises(backup_format.BackupFormatError):
            service.verify(truncated, password="correct horse", cancel=threading.Event())
    finally:
        case.tearDown()


def test_barrier_exclusive_blocks_ai_scope_nested_and_stale_lease():
    case = BackupSnapshotCase()
    case.setUp()
    try:
        barrier = backup_barrier.get_barrier(case.runtime.data_dir)
        lease = barrier.begin_intent("snapshot-test")
        try:
            with pytest.raises(backup_barrier.SnapshotBusy):
                begin_immediate(case.session)
            with pytest.raises(backup_barrier.SnapshotBusy):
                with backup_barrier.file_scope(case.runtime.data_dir):
                    pass
            # An accepted continuation may cross intent...
            with backup_barrier.ai_write_scope():
                begin_immediate(case.session)
                case.session.rollback()
            assert barrier.active_counts == (0, 0)
            barrier.acquire_exclusive(lease)
            assert barrier.exclusive_owner == "snapshot-test"
            # ...but never exclusive.
            with pytest.raises(backup_barrier.SnapshotBusy):
                with backup_barrier.ai_write_scope():
                    begin_immediate(case.session)
            with pytest.raises(backup_barrier.SnapshotBusy):
                begin_immediate(case.session)
            assert barrier.active_counts == (0, 0)
        finally:
            lease.release()
        assert barrier.intent_owner is None
        assert barrier.exclusive_owner is None

        # A stale lease with a reused owner name must not clear the new owner.
        first = barrier.begin_intent("same-owner")
        first.release()
        second = barrier.begin_intent("same-owner")
        try:
            first.release()
            assert barrier.intent_owner == "same-owner"
            with pytest.raises(backup_barrier.SnapshotBusy):
                barrier.begin_intent("another")
        finally:
            second.release()

        # A failed nested BEGIN must release the outer writer slot on rollback.
        begin_immediate(case.session)
        assert barrier.active_counts == (1, 0)
        with pytest.raises(Exception):
            begin_immediate(case.session)
        case.session.rollback()
        assert barrier.active_counts == (0, 0)
        begin_immediate(case.session)
        case.session.close()
        assert barrier.active_counts == (0, 0)
    finally:
        case.tearDown()


def test_file_scope_waits_for_inflight_import_scope():
    case = BackupSnapshotCase()
    case.setUp()
    try:
        barrier = backup_barrier.get_barrier(case.runtime.data_dir)
        entered = threading.Event()
        release = threading.Event()
        committed = threading.Event()

        def hold():
            with backup_barrier.file_scope(case.runtime.data_dir):
                entered.set()
                release.wait(5)
                begin_immediate(case.session)
                case.session.rollback()
                committed.set()

        thread = threading.Thread(target=hold)
        thread.start()
        assert entered.wait(2)
        lease = barrier.begin_intent("wait-test")
        try:
            with pytest.raises(backup_barrier.SnapshotBusy):
                with backup_barrier.file_scope(case.runtime.data_dir):
                    pass
            release.set()
            assert committed.wait(5)
            thread.join(5)
            barrier.wait_idle(lease, timeout=2)
            barrier.acquire_exclusive(lease)
        finally:
            release.set()
            lease.release()
            thread.join(5)
    finally:
        case.tearDown()


def test_unknown_trigger_sqlitexprobe_and_fake_schema_rejected(tmp_path):
    case = BackupSnapshotCase()
    case.setUp()
    try:
        observation_id = case.create_observation()
        case.import_photo(observation_id)
        result, _ = case.create_snapshot()
        verified = case.service().verify(
            result.path, password=None, cancel=threading.Event()
        )
        triggered = tmp_path / "triggered.db"
        fake = tmp_path / "fake.db"
        shutil.copy2(verified.database_path, triggered)
        shutil.copy2(verified.database_path, fake)
        case.service().discard_verified(verified)
        connection = sqlite3.connect(str(triggered))
        try:
            connection.execute(
                "CREATE TRIGGER sqliteXprobe AFTER INSERT ON local_profile "
                "BEGIN SELECT 1; END"
            )
            connection.commit()
        finally:
            connection.close()
        with pytest.raises(backup_validate.BackupValidationError) as trigger:
            backup_validate.validate_database(
                triggered, migrate_old=False, require_current=True
            )
        assert trigger.value.code == "BACKUP_DB_SCHEMA_UNTRUSTED"

        connection = sqlite3.connect(str(fake))
        try:
            connection.execute("PRAGMA foreign_keys=OFF")
            connection.execute(
                "ALTER TABLE local_ai_credentials RENAME TO old_credentials"
            )
            connection.execute(
                "CREATE TABLE local_ai_credentials ("
                "id TEXT PRIMARY KEY, profile_id TEXT NOT NULL, key_id TEXT, "
                "nonce BLOB, ciphertext BLOB, state TEXT NOT NULL, "
                "created_at TIMESTAMP NOT NULL, updated_at TIMESTAMP NOT NULL)"
            )
            connection.execute(
                "INSERT INTO local_ai_credentials SELECT * FROM old_credentials"
            )
            connection.execute("DROP TABLE old_credentials")
            connection.commit()
        finally:
            connection.close()
        with pytest.raises(backup_validate.BackupValidationError) as schema:
            backup_validate.validate_database(
                fake, migrate_old=False, require_current=True
            )
        assert schema.value.code == "BACKUP_DB_SCHEMA_UNTRUSTED"
    finally:
        case.tearDown()


def test_target_no_replace_preserves_existing_bytes(tmp_path):
    case = BackupSnapshotCase()
    case.setUp()
    try:
        temp = tmp_path / "temp"
        target = tmp_path / "target"
        temp.write_bytes(b"new")
        target.write_bytes(b"existing")
        with pytest.raises(backup_fs.BackupPathError) as error:
            backup_fs.publish_no_replace(temp, target)
        assert error.value.code == "BACKUP_TARGET_EXISTS"
        assert target.read_bytes() == b"existing"
        assert temp.read_bytes() == b"new"
    finally:
        case.tearDown()


def test_600_real_jpegs_and_working_set():
    case = BackupSnapshotCase()
    case.setUp()
    try:
        observation_id = case.create_observation()
        base = case.noise_jpeg()
        for _ in range(600):
            case.add_direct_asset(observation_id, data=base)
        baseline = working_set_bytes()
        peak = [baseline]
        cancel = threading.Event()

        def progress(item):
            peak[0] = max(peak[0], working_set_bytes())

        tracemalloc.start()
        try:
            result = case.service().create(
                case.tmp_root / "large.kgmbackup",
                password=None,
                cancel=cancel,
                progress=progress,
            )
            _current, traced_peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        assert result.size > 30 * 1024 * 1024
        assert traced_peak < 256 * 1024 * 1024
        assert peak[0] - baseline < 1024 * 1024 * 1024
        verified = case.service().verify(
            result.path, password=None, cancel=threading.Event()
        )
        try:
            assert len(verified.manifest["resources"]) == 1200
            assert sum(
                item["bytes"] for item in verified.manifest["resources"]
            ) > 30 * 1024 * 1024
        finally:
            case.service().discard_verified(verified)
    finally:
        case.tearDown()



def test_size_budget_fault_injection_fails_closed(monkeypatch):
    case = BackupSnapshotCase()
    case.setUp()
    try:
        observation_id = case.create_observation()
        case.import_photo(observation_id)
        result, _ = case.create_snapshot("budget.kgmbackup")
        manifest_raw, database, resources = _plain_parts(result.path)
        manifest = backup_validate.parse_manifest_json(manifest_raw)
        oversized = dict(manifest)
        oversized["resources"] = [manifest["resources"][0]] * (
            backup_format.MAX_MEMBERS + 1
        )
        with pytest.raises(backup_validate.BackupValidationError):
            backup_validate._validate_manifest_schema(oversized)  # noqa: SLF001

        payload = case.tmp_root / "members.zip"
        with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr("manifest.json", b"{}")
            archive.writestr("db/kindergarten.db", b"db")
            archive.writestr("observations/assets/a/b.jpg", b"x")
        monkeypatch.setattr(backup_format, "MAX_MEMBERS", 1)
        with pytest.raises(backup_format.BackupFormatError):
            backup_zip.precheck_payload_zip(payload)
        monkeypatch.setattr(backup_format, "MAX_MEMBERS", 250_000)
        monkeypatch.setattr(backup_format, "MAX_CENTRAL_DIR_BYTES", 1)
        with pytest.raises(backup_format.BackupFormatError):
            backup_zip.precheck_payload_zip(payload)
        monkeypatch.setattr(backup_format, "MAX_CENTRAL_DIR_BYTES", 256 * 1024 * 1024)

        monkeypatch.setattr(backup_format, "MAX_TOTAL_BYTES", 1)
        with pytest.raises(backup_format.BackupFormatError):
            case.service().create(
                case.tmp_root / "too-total.kgmbackup",
                password=None,
                cancel=threading.Event(),
                progress=lambda _p: None,
            )
        monkeypatch.setattr(backup_format, "MAX_TOTAL_BYTES", 64 * 1024 * 1024 * 1024)
        monkeypatch.setattr(backup_format, "MAX_RESOURCE_BYTES", 16)
        with pytest.raises(backup_format.BackupFormatError):
            case.service().create(
                case.tmp_root / "too-resource.kgmbackup",
                password=None,
                cancel=threading.Event(),
                progress=lambda _p: None,
            )
    finally:
        case.tearDown()

def test_header_modes_and_malformed_headers():
    plain = backup_format.encode_header(mode=1, payload_len=10)
    parsed = backup_format.parse_header(plain, file_size=128 + 10)
    assert parsed.mode == 1 and parsed.payload_len == 10
    password = backup_format.encode_header(
        mode=2, payload_len=10, salt=b"s" * 32, nonce=b"n" * 12
    )
    parsed2 = backup_format.parse_header(password, file_size=128 + 10 + 16)
    assert parsed2.mode == 2 and parsed2.kdf == (17, 8, 1)
    for raw in (
        b"bad" + plain[3:],
        plain[:8] + bytes([2]) + plain[9:],
        plain[:21] + bytes([1]) + plain[22:],
        plain[:76] + bytes([0]) * 32 + plain[108:],
    ):
        with pytest.raises(backup_format.BackupFormatError):
            backup_format.parse_header(raw, file_size=128 + 10)
    with pytest.raises(backup_format.BackupFormatError):
        backup_format.parse_header(plain, file_size=129 + 10)


def test_cancel_before_snapshot_does_not_create_output():
    case = BackupSnapshotCase()
    case.setUp()
    try:
        cancel = threading.Event()
        cancel.set()
        target = case.tmp_root / "cancelled.kgmbackup"
        with pytest.raises(backup_barrier.SnapshotCancelled):
            case.service().create(
                target, password=None, cancel=cancel, progress=lambda _p: None
            )
        assert not target.exists()
    finally:
        case.tearDown()


def test_cancel_after_publish_is_monotonic():
    case = BackupSnapshotCase()
    case.setUp()
    try:
        case.import_photo(case.create_observation())
        cancel = threading.Event()

        def progress(item):
            if item.stage == "commit":
                cancel.set()

        result = case.service().create(
            case.tmp_root / "committed.kgmbackup",
            password=None,
            cancel=cancel,
            progress=progress,
        )
        assert result.verified is True
        assert result.path.is_file()
        assert cancel.is_set()
    finally:
        case.tearDown()


def test_cancel_during_database_copy_leaves_no_output():
    case = BackupSnapshotCase()
    case.setUp()
    try:
        case.import_photo(case.create_observation())
        cancel = threading.Event()

        def progress(item):
            if item.stage == "db" and item.done > 0:
                cancel.set()

        target = case.tmp_root / "cancelled-db.kgmbackup"
        with pytest.raises(backup_barrier.SnapshotCancelled):
            case.service().create(
                target, password=None, cancel=cancel, progress=progress
            )
        assert not target.exists()
    finally:
        case.tearDown()


def test_final_publish_race_preserves_existing_target(monkeypatch):
    case = BackupSnapshotCase()
    case.setUp()
    try:
        case.import_photo(case.create_observation())
        target = case.tmp_root / "race.kgmbackup"
        original = backup_fs.publish_no_replace

        def racing_publish(temp, destination):
            if not destination.exists():
                destination.write_bytes(b"concurrent-target")
            return original(temp, destination)

        monkeypatch.setattr(backup_fs, "publish_no_replace", racing_publish)
        with pytest.raises(backup_fs.BackupPathError) as error:
            case.service().create(
                target,
                password=None,
                cancel=threading.Event(),
                progress=lambda _p: None,
            )
        assert error.value.code == "BACKUP_TARGET_EXISTS"
        assert target.read_bytes() == b"concurrent-target"
    finally:
        case.tearDown()


def test_unknown_revision_is_rejected_without_stamp(tmp_path):
    case = BackupSnapshotCase()
    case.setUp()
    try:
        copy = tmp_path / "unknown.db"
        shutil.copy2(case.runtime.db_path, copy)
        with sqlite3.connect(str(copy)) as connection:
            connection.execute(
                "UPDATE local_alembic_version SET version_num = '99999999_9999_unknown'"
            )
            connection.commit()
        with pytest.raises(backup_validate.BackupValidationError) as error:
            backup_validate.validate_database(
                copy, migrate_old=True, require_current=False
            )
        assert error.value.code == "BACKUP_DB_REVISION_UNSUPPORTED"
    finally:
        case.tearDown()


def test_plaintext_tamper_is_rejected():
    case = BackupSnapshotCase()
    case.setUp()
    try:
        case.import_photo(case.create_observation())
        result, _ = case.create_snapshot("plain.kgmbackup")
        raw = bytearray(result.path.read_bytes())
        raw[backup_format.HEADER_LEN + 3] ^= 0x01
        tampered = case.tmp_root / "plain-tampered.kgmbackup"
        tampered.write_bytes(raw)
        _assert_rejected(case, tampered)
    finally:
        case.tearDown()


def test_password_mode_keeps_plaintext_in_private_work_area():
    case = BackupSnapshotCase()
    case.setUp()
    try:
        observation_id = case.create_observation()
        case.import_photo(observation_id)
        output_parent = case.tmp_root / "target"
        output_parent.mkdir()
        seen = []

        def progress(item):
            if item.stage in ("db", "resources", "encrypt"):
                for path in output_parent.iterdir():
                    if path.is_file():
                        data = path.read_bytes()[:16]
                        seen.append((path.name, data))

        result = case.service().create(
            output_parent / "encrypted.kgmbackup",
            password="correct horse",
            cancel=threading.Event(),
            progress=progress,
        )
        assert result.verified is True
        assert all(
            not data.startswith(b"SQLite format 3\x00") for _name, data in seen
        )
        assert not any(name.endswith(".kgmbackup") for name, _data in seen)
        verified = case.service().verify(
            result.path, password="correct horse", cancel=threading.Event()
        )
        try:
            owned_root = Path(case.runtime.credential_root).parent
            assert verified.staging_root.is_relative_to(owned_root)
            assert verified.staging_root.name.startswith("verify-")
            assert case.runtime.data_dir not in verified.staging_root.parents
            assert case.runtime.credential_root not in verified.staging_root.parents
            assert output_parent not in verified.staging_root.parents
            handle = credentials._open_verified_file(  # noqa: SLF001
                verified.database_path,
                credentials._current_user_sid(),  # noqa: SLF001
                "备份校验数据库",
            )
            credentials._kernel32.CloseHandle(handle)  # noqa: SLF001
        finally:
            case.service().discard_verified(verified)
    finally:
        case.tearDown()


def test_strict_manifest_and_extra_member_rejected():
    case = BackupSnapshotCase()
    case.setUp()
    try:
        observation_id = case.create_observation()
        case.import_photo(observation_id)
        result, _ = case.create_snapshot("strict.kgmbackup")
        manifest_raw, database, resources = _plain_parts(result.path)
        base = case.tmp_root / "strict-base.kgmbackup"
        _write_plain(base, manifest_raw, database, resources)
        case.service().verify(base, password=None, cancel=threading.Event())

        duplicate = manifest_raw.replace(
            b'"format_version":1',
            b'"format_version":1,"format_version":1',
            1,
        )
        unknown = manifest_raw.replace(b"{", b'{"unknown":1,', 1)
        nan = manifest_raw.replace(b'"format_version":1', b'"format_version":NaN', 1)
        boolean = manifest_raw.replace(b'"format_version":1', b'"format_version":true', 1)
        for name, raw in (
            ("duplicate.kgmbackup", duplicate),
            ("unknown.kgmbackup", unknown),
            ("nan.kgmbackup", nan),
            ("bool.kgmbackup", boolean),
        ):
            path = case.tmp_root / name
            _write_plain(path, raw, database, resources)
            _assert_rejected(case, path)

        extra = case.tmp_root / "extra.kgmbackup"
        _write_plain(
            extra,
            manifest_raw,
            database,
            resources,
            {"observations/assets/extra/extra.jpg": case.noise_jpeg()},
        )
        _assert_rejected(case, extra)

        conflict = case.tmp_root / "conflict.kgmbackup"
        _write_plain(
            conflict,
            manifest_raw,
            database,
            resources,
            {
                "observations/assets/extra": b"x",
                "observations/assets/extra/child.jpg": b"y",
            },
        )
        _assert_rejected(case, conflict)
    finally:
        case.tearDown()


def test_known_old_database_is_migrated_only_in_isolated_copy(tmp_path):
    case = BackupSnapshotCase()
    case.setUp()
    try:
        old = tmp_path / "old.db"
        command.upgrade(alembic_config(old), "20261023_0005_local_history")
        original_hash = hashlib.sha256(old.read_bytes()).hexdigest()
        facts = backup_validate.inspect_source_database(old, scratch_dir=tmp_path)
        assert facts["source_revision"] == "20261023_0005_local_history"
        assert facts["source_sha256"] == original_hash
        manifest = {
            "format_version": 1,
            "snapshot_id": "a" * 32,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "app_version": "0.1.0-test",
            "database_revision": facts["source_revision"],
            "ai_contracts": facts["source_ai_contracts"],
            "database": {
                "path": "db/kindergarten.db",
                "bytes": facts["source_bytes"],
                "sha256": facts["source_sha256"],
            },
            "resources": [],
            "counts": {
                "database_bytes": facts["source_bytes"],
                "resources": 0,
                "resources_bytes": 0,
            },
            "source_identity": {"commit": "test", "tree": "test-tree"},
        }
        container = tmp_path / "old.kgmbackup"
        _write_plain(
            container,
            json.dumps(manifest, ensure_ascii=False).encode("utf-8"),
            old.read_bytes(),
            {},
        )
        verified = case.service().verify(
            container, password=None, cancel=threading.Event()
        )
        try:
            assert verified.source_revision == "20261023_0005_local_history"
            assert verified.target_revision == "20261025_0006_local_game_observations"
            assert verified.source_sha256 == original_hash
            assert verified.manifest["database"]["sha256"] == original_hash
            assert hashlib.sha256(old.read_bytes()).hexdigest() == original_hash
            connection = sqlite3.connect(str(verified.database_path))
            try:
                assert connection.execute(
                    "SELECT version_num FROM local_alembic_version"
                ).fetchone()[0] == verified.target_revision
            finally:
                connection.close()
        finally:
            case.service().discard_verified(verified)
    finally:
        case.tearDown()


def test_snapshot_freezes_by_owner_without_revoking_ai():
    case = BackupSnapshotCase()
    case.setUp()
    try:
        case.import_photo(case.create_observation())

        class FakeExecutor:
            def __init__(self):
                self.freeze_owners = []
                self.unfreeze_owners = []
                self.stop_calls = 0

            def freeze(self, owner="close"):
                self.freeze_owners.append(owner)

            def unfreeze(self, owner="close"):
                self.unfreeze_owners.append(owner)

            def is_runnable(self):
                return True

            def is_snapshot_idle(self):
                return True

            def stop_and_drain(self, **kwargs):
                self.stop_calls += 1
                return False

        fake = FakeExecutor()
        result, _ = case.create_snapshot(executor=fake)
        assert result.verified is True
        assert len(fake.freeze_owners) == 1
        assert len(fake.unfreeze_owners) == 1
        assert fake.freeze_owners == fake.unfreeze_owners
        assert fake.stop_calls == 0
    finally:
        case.tearDown()


def _seed_ai_material(case: BackupSnapshotCase) -> str:
    plan, _created = daily_plan_service.create_or_open(
        case.session,
        plan_date=date(2026, 9, 2),
        raw_lesson_plan="原始教案正文",
        adopted_content={
            "group_activity": {"process": "一、导入\n二、观察"},
            "reflection": "反思",
        },
    )
    version = case.session.execute(
        text("SELECT current_config_version FROM local_ai_state")
    ).scalar()
    ai_config_service.patch_config(
        case.session,
        expected_ai_config_version=version or 0,
        base_url="https://api.example.com/v1",
        model="test-model",
        secret="s3cret",
        secret_provided=True,
        request_id=str(uuid.uuid4()),
        credential_root=case.runtime.credential_root,
    )
    statuses = ["succeeded", "failed", "outcome_unknown"]
    for task_type, status in zip(
        ("daily_lesson_split", "daily_process_adapt", "daily_other_activities"),
        statuses,
    ):
        task, _created = ai_task_service.create_task(
            case.session,
            plan_id=plan["id"],
            task_type=task_type,
            expected_content_version=1,
            target_grade="middle",
            request_id=str(uuid.uuid4()),
        )
        task_id = task["id"]
        row = case.session.execute(
            text(
                "SELECT input_id, source_id, daily_plan_id FROM local_ai_tasks "
                "WHERE id = :id"
            ),
            {"id": task_id},
        ).one()
        input_id, source_id, daily_plan_id = row
        config_version = case.session.execute(
            text("SELECT current_config_version FROM local_ai_state")
        ).scalar()
        personal_revision = case.session.execute(
            text(
                "SELECT current_revision FROM local_personal_prompt_heads "
                "WHERE profile_id = :profile AND task_type = :task_type"
            ),
            {"profile": case.profile.id, "task_type": task_type},
        ).scalar()
        bundle = case.session.execute(
            text(
                "SELECT contract_version, default_revision FROM local_prompt_bundles "
                "WHERE task_type = :task_type ORDER BY contract_version, default_revision "
                "LIMIT 1"
            ),
            {"task_type": task_type},
        ).one()
        execution_id = uuid.uuid4().hex[:20]
        now = utc_now()
        case.session.execute(
            text(
                "INSERT INTO local_ai_executions ("
                "id, task_id, source_kind, source_id, observation_id, daily_plan_id, "
                "input_id, task_type, generation, launch_id, permit_id, config_version, "
                "profile_id, personal_revision, contract_version, default_revision, "
                "state, runtime_meta_json, started_at, created_at, ended_at"
                ") VALUES ("
                ":id, :task_id, 'daily_plan', :source_id, NULL, :daily_plan_id, "
                ":input_id, :task_type, 1, :launch_id, :permit_id, :config_version, "
                ":profile_id, :personal_revision, :contract_version, :default_revision, "
                ":state, '{}', :now, :now, :now)"
            ),
            {
                "id": execution_id,
                "task_id": task_id,
                "source_id": source_id,
                "daily_plan_id": daily_plan_id,
                "input_id": input_id,
                "task_type": task_type,
                "launch_id": str(uuid.uuid4()),
                "permit_id": str(uuid.uuid4()),
                "config_version": config_version,
                "profile_id": case.profile.id,
                "personal_revision": personal_revision,
                "contract_version": bundle[0],
                "default_revision": bundle[1],
                "state": status,
                "now": now,
            },
        )
        case.session.execute(
            text(
                "INSERT INTO local_ai_attempts ("
                "id, execution_id, attempt_no, state, created_at"
                ") VALUES (:id, :execution_id, 1, :state, :now)"
            ),
            {
                "id": uuid.uuid4().hex[:20],
                "execution_id": execution_id,
                "state": status,
                "now": now,
            },
        )
        if status == "succeeded":
            case.session.execute(
                text(
                    "INSERT INTO local_ai_candidates ("
                    "id, profile_id, execution_id, task_id, source_kind, source_id, "
                    "observation_id, daily_plan_id, input_id, task_type, "
                    "contract_version, schema_version, raw_candidate_json, "
                    "candidate_hash, created_at"
                    ") VALUES ("
                    ":id, :profile_id, :execution_id, :task_id, 'daily_plan', "
                    ":source_id, NULL, :daily_plan_id, :input_id, :task_type, "
                    ":contract_version, 1, '{}', :candidate_hash, :now)"
                ),
                {
                    "id": uuid.uuid4().hex[:20],
                    "profile_id": case.profile.id,
                    "execution_id": execution_id,
                    "task_id": task_id,
                    "source_id": source_id,
                    "daily_plan_id": daily_plan_id,
                    "input_id": input_id,
                    "task_type": task_type,
                    "contract_version": bundle[0],
                    "candidate_hash": "e" * 64,
                    "now": now,
                },
            )
        case.session.execute(
            text(
                "UPDATE local_ai_tasks SET status = :status, "
                "current_execution_id = :execution_id, runtime_meta_json = '{}', "
                "updated_at = :now WHERE id = :id"
            ),
            {
                "status": status,
                "execution_id": execution_id,
                "now": now,
                "id": task_id,
            },
        )
    case.session.add(
        LocalAICredential(
            id=uuid.uuid4().hex[:20],
            profile_id=case.profile.id,
            key_id=None,
            nonce=None,
            ciphertext=None,
            state="cleared",
            created_at=utc_now(),
            updated_at=utc_now(),
        )
    )
    case.session.commit()
    return plan["id"]


def test_daily_plan_ai_material_history_and_synthetic_ciphertext_preserved():
    case = BackupSnapshotCase()
    case.setUp()
    try:
        plan_id = _seed_ai_material(case)
        observations = [case.create_observation(f"2026-09-{day:02d}") for day in (3, 4, 5)]
        for observation_id in observations:
            case.import_photo(observation_id)
        first_observation = observations[0]
        first_asset = case.session.execute(
            text(
                "SELECT id FROM local_observation_assets "
                "WHERE observation_id = :observation_id LIMIT 1"
            ),
            {"observation_id": first_observation},
        ).scalar()
        current = observation_service.read_current(
            case.session, profile_id=case.profile.id, observation_id=first_observation
        )
        observation_service.save_observation(
            case.session,
            profile_id=case.profile.id,
            observation_id=first_observation,
            request_id=str(uuid.uuid4()),
            expected_revision=current["revision"],
            payload={},
            photos=None,
            save_reason="manual",
        )
        current = observation_service.read_current(
            case.session, profile_id=case.profile.id, observation_id=first_observation
        )
        observation_assets.remove_photo(
            case.session,
            profile_id=case.profile.id,
            observation_id=first_observation,
            request_id=str(uuid.uuid4()),
            expected_revision=current["revision"],
            asset_id=first_asset,
        )
        current = observation_service.read_current(
            case.session, profile_id=case.profile.id, observation_id=first_observation
        )
        observation_service.save_observation(
            case.session,
            profile_id=case.profile.id,
            observation_id=first_observation,
            request_id=str(uuid.uuid4()),
            expected_revision=current["revision"],
            payload={},
            photos=None,
            save_reason="manual",
        )
        result, _ = case.create_snapshot("materials.kgmbackup")
        verified = case.service().verify(
            result.path, password=None, cancel=threading.Event()
        )
        try:
            connection = sqlite3.connect(str(verified.database_path))
            try:
                assert connection.execute(
                    "SELECT COUNT(*) FROM local_daily_plans"
                ).fetchone()[0] == 1
                assert connection.execute(
                    "SELECT COUNT(*) FROM local_observation_records"
                ).fetchone()[0] == 3
                assert connection.execute(
                    "SELECT COUNT(*) FROM local_observation_versions"
                ).fetchone()[0] >= 1
                assert connection.execute(
                    "SELECT COUNT(*) FROM local_ai_tasks WHERE status = 'succeeded'"
                ).fetchone()[0] == 1
                assert connection.execute(
                    "SELECT COUNT(*) FROM local_ai_tasks WHERE status = 'failed'"
                ).fetchone()[0] == 1
                assert connection.execute(
                    "SELECT COUNT(*) FROM local_ai_tasks "
                    "WHERE status = 'outcome_unknown'"
                ).fetchone()[0] == 1
                active = connection.execute(
                    "SELECT nonce, ciphertext, key_id FROM local_ai_credentials "
                    "WHERE state = 'active'"
                ).fetchone()
                assert active is not None and len(active[0]) == 12 and active[1]
                cleared = connection.execute(
                    "SELECT COUNT(*) FROM local_ai_credentials WHERE state = 'cleared'"
                ).fetchone()[0]
                assert cleared == 1
                assert connection.execute(
                    "SELECT COUNT(*) FROM local_observation_version_photos "
                    "WHERE asset_id = ?",
                    (first_asset,),
                ).fetchone()[0] >= 1
                assert connection.execute(
                    "SELECT COUNT(*) FROM local_observation_operations"
                ).fetchone()[0] >= 1
            finally:
                connection.close()
            assert all(
                "credential" not in item["path"]
                for item in verified.manifest["resources"]
            )
        finally:
            case.service().discard_verified(verified)
    finally:
        case.tearDown()


def test_bad_current_photo_rejected_without_touching_original():
    case = BackupSnapshotCase()
    case.setUp()
    try:
        observation_id = case.create_observation()
        asset_id = case.import_photo(observation_id)
        row = case.session.execute(
            text(
                "SELECT relative_path FROM local_observation_assets WHERE id = :id"
            ),
            {"id": asset_id},
        ).one()
        path = case.runtime.data_dir.joinpath(*row[0].split("/"))
        bad = b"not a real jpeg"
        path.write_bytes(bad)
        case.session.execute(
            text(
                "UPDATE local_observation_assets SET content_hash = :hash, "
                "byte_size = :size WHERE id = :id"
            ),
            {
                "hash": hashlib.sha256(bad).hexdigest(),
                "size": len(bad),
                "id": asset_id,
            },
        )
        case.session.execute(
            text(
                "UPDATE local_observation_drafts SET payload_hash = :hash "
                "WHERE observation_id = :observation_id"
            ),
            {"hash": "f" * 64, "observation_id": observation_id},
        )
        case.session.commit()
        target = case.tmp_root / "bad.kgmbackup"
        with pytest.raises(
            (backup_format.BackupFormatError, backup_validate.BackupValidationError)
        ) as error:
            case.service().create(
                target,
                password=None,
                cancel=threading.Event(),
                progress=lambda _p: None,
            )
        assert "IMAGE_INVALID" in getattr(error.value, "code", "")
        assert not target.exists()
        assert path.read_bytes() == bad
    finally:
        case.tearDown()


def test_output_parent_swap_is_denied_and_marker_survives():
    case = BackupSnapshotCase()
    case.setUp()
    try:
        case.import_photo(case.create_observation())
        outside = case.tmp_root / "outside"
        outside.mkdir()
        marker = outside / "keep.txt"
        marker.write_bytes(b"keep")
        parent = case.tmp_root / "out"
        parent.mkdir()
        moved = case.tmp_root / "moved"
        rename_error: list[BaseException] = []

        def progress(item):
            if item.stage == "db" and not rename_error and not moved.exists():
                try:
                    os.rename(parent, moved)
                except BaseException as exc:  # noqa: BLE001 - expected denial
                    rename_error.append(exc)
                    return
                subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(parent), str(outside)],
                    check=False,
                    capture_output=True,
                )

        try:
            case.service().create(
                parent / "backup.kgmbackup",
                password=None,
                cancel=threading.Event(),
                progress=progress,
            )
        except (backup_fs.BackupPathError, backup_format.BackupFormatError):
            pass
        assert rename_error, "output parent rename was not blocked by the held handle"
        assert marker.read_bytes() == b"keep"
    finally:
        case.tearDown()



def test_http_mutation_during_intent_returns_local_backup_busy():
    case = BackupSnapshotCase()
    case.setUp()
    try:
        server = case.start_server(case.runtime)
        client = server.client()
        barrier = backup_barrier.get_barrier(case.runtime.data_dir)
        lease = barrier.begin_intent("http-test")
        try:
            status, result = client.post(
                "/api/observations",
                {
                    "request_id": str(uuid.uuid4()),
                    "record_type": "public",
                    "payload": {
                        "observation_date": "2026-09-15",
                        "subjects": [{"name": "小明"}],
                        "environment": "积木区",
                    },
                },
            )
            assert status == 409, result
            assert result["error"]["code"] == "LOCAL_BACKUP_BUSY"
        finally:
            lease.release()
    finally:
        case.tearDown()




def test_schema_check_literal_case_is_rejected(tmp_path):
    case = BackupSnapshotCase()
    case.setUp()
    try:
        observation_id = case.create_observation()
        case.import_photo(observation_id)
        result, _ = case.create_snapshot("literal-case.kgmbackup")
        verified = case.service().verify(
            result.path, password=None, cancel=threading.Event()
        )
        target = tmp_path / "changed-check-literal.db"
        shutil.copy2(verified.database_path, target)
        case.service().discard_verified(verified)
        connection = sqlite3.connect(str(target))
        try:
            ddl = connection.execute(
                "SELECT sql FROM sqlite_master WHERE name='local_ai_credentials'"
            ).fetchone()[0]
            changed = ddl.replace("state <> 'active'", "state <> 'ACTIVE'", 1)
            assert changed != ddl
            connection.execute("PRAGMA writable_schema=ON")
            connection.execute(
                "UPDATE sqlite_master SET sql=? WHERE name='local_ai_credentials'",
                (changed,),
            )
            version = connection.execute("PRAGMA schema_version").fetchone()[0]
            connection.execute(f"PRAGMA schema_version={version + 1}")
            connection.commit()
        finally:
            connection.close()
        with pytest.raises(backup_validate.BackupValidationError) as error:
            backup_validate.validate_database(
                target, migrate_old=False, require_current=True
            )
        assert error.value.code == "BACKUP_DB_SCHEMA_UNTRUSTED"
    finally:
        case.tearDown()


def test_detached_cleanup_swap_keeps_outside_marker():
    case = BackupSnapshotCase()
    case.setUp()
    service = case.service()
    verified = None
    moved = None
    original_lstat = os.lstat
    state = {"attempted": False, "swap_blocked": False}
    outside = case.tmp_root / "cleanup-outside"
    outside.mkdir()
    marker = outside / "keep.txt"
    marker.write_bytes(b"CONTROL-MUST-STAY")
    try:
        output = case.tmp_root / "cleanup-source.kgmbackup"
        service.create(output, password=None, cancel=threading.Event())
        verified = service.verify(
            output, password=None, cancel=threading.Event()
        )
        target = Path(verified.staging_root).absolute()
        moved = target.with_name(target.name + "-audit-original")

        def swap_after_lstat(path, *args, **kwargs):
            value = original_lstat(path, *args, **kwargs)
            if Path(path).absolute() == target and not state["attempted"]:
                state["attempted"] = True
                try:
                    os.rename(target, moved)
                except OSError:
                    state["swap_blocked"] = True
                    return value
                result = subprocess.run(
                    [
                        "cmd",
                        "/c",
                        "mklink",
                        "/J",
                        str(target),
                        str(outside),
                    ],
                    check=False,
                    capture_output=True,
                )
                assert result.returncode == 0
            return value

        with mock.patch.object(
            backup_fs.os, "lstat", side_effect=swap_after_lstat
        ):
            service.discard_verified(verified)
        assert state["attempted"] is True
        assert state["swap_blocked"] is True
        assert marker.read_bytes() == b"CONTROL-MUST-STAY"
    finally:
        if verified is not None:
            target = Path(verified.staging_root).absolute()
            try:
                info = original_lstat(target)
                if getattr(info, "st_file_attributes", 0) & 0x400:
                    target.rmdir()
            except FileNotFoundError:
                pass
            if moved is not None and moved.exists() and not target.exists():
                os.rename(moved, target)
            if target.exists():
                try:
                    service.discard_verified(verified)
                except Exception:
                    pass
        case.tearDown()

def test_device_paths_are_rejected_before_any_open():
    case = BackupSnapshotCase()
    case.setUp()
    try:
        target = Path(r"\\.\PhysicalDrive0.kgmbackup")
        with pytest.raises(backup_format.BackupFormatError):
            case.service().create(
                target,
                password=None,
                cancel=threading.Event(),
                progress=lambda _p: None,
            )
        with pytest.raises(backup_format.BackupFormatError):
            case.service().verify(
                target, password=None, cancel=threading.Event()
            )
    finally:
        case.tearDown()


def test_snapshot_work_root_checks_every_fallback_candidate():
    from app.local.backup_snapshot import SnapshotService

    temp_root = Path(tempfile.gettempdir())
    data_root = temp_root / "KindergartenManager-backup-work"
    credential_root = data_root / "credentials"
    runtime = types.SimpleNamespace(
        data_dir=data_root, credential_root=credential_root
    )
    service = SnapshotService(
        runtime,
        app_version="audit",
        source_identity={"commit": "synthetic"},
    )
    selected = service._snapshot_work_root()
    assert selected != data_root
    assert not SnapshotService._overlaps(selected, data_root)
    assert not SnapshotService._overlaps(selected, credential_root)


def test_snapshot_work_root_rejects_when_all_candidates_overlap():
    from app.local.backup_snapshot import SnapshotService

    temp_root = Path(tempfile.gettempdir())
    runtime = types.SimpleNamespace(
        data_dir=temp_root, credential_root=temp_root / "backup-work"
    )
    service = SnapshotService(
        runtime,
        app_version="audit",
        source_identity={"commit": "synthetic"},
    )
    with pytest.raises(backup_fs.BackupPathError) as error:
        service._snapshot_work_root()
    assert error.value.code == "BACKUP_WORK_ROOT_UNSAFE"


def test_canonical_schema_cleanup_swap_keeps_outside_marker():
    case = BackupSnapshotCase()
    case.setUp()
    service = case.service()
    original_lstat = os.lstat
    state = {"attempted": False, "swap_blocked": False}
    outside = case.tmp_root / "canonical-outside"
    outside.mkdir()
    marker = outside / "keep.txt"
    marker.write_bytes(b"CANONICAL-CONTROL-MUST-STAY")
    moved: list[Path] = []
    try:
        case.import_photo(case.create_observation())
        backup_validate._SCHEMA_CACHE.clear()

        def swap_after_lstat(path, *args, **kwargs):
            value = original_lstat(path, *args, **kwargs)
            candidate = Path(path).absolute()
            if (
                candidate.name.startswith("kgm-schema-")
                and candidate.is_relative_to(case.tmp_root.absolute())
                and not state["attempted"]
            ):
                state["attempted"] = True
                target = candidate.with_name(candidate.name + "-audit-original")
                moved.append(target)
                try:
                    os.rename(candidate, target)
                except OSError:
                    state["swap_blocked"] = True
                    return value
                result = subprocess.run(
                    [
                        "cmd",
                        "/c",
                        "mklink",
                        "/J",
                        str(candidate),
                        str(outside),
                    ],
                    check=False,
                    capture_output=True,
                )
                assert result.returncode == 0
            return value

        with mock.patch.object(
            os, "lstat", side_effect=swap_after_lstat
        ):
            service.create(
                case.tmp_root / "canonical-swap.kgmbackup",
                password=None,
                cancel=threading.Event(),
                progress=lambda _p: None,
            )
        assert state["attempted"] is True
        assert state["swap_blocked"] is True
        assert marker.read_bytes() == b"CANONICAL-CONTROL-MUST-STAY"
    finally:
        for target in moved:
            if target.exists():
                try:
                    os.rename(target, target.with_name(target.name[: -len("-audit-original")]))
                except OSError:
                    pass
        case.tearDown()

def test_private_work_area_files_are_current_user_restricted():
    case = BackupSnapshotCase()
    case.setUp()
    try:
        work = backup_fs.PrivateWorkArea(
            case.service()._snapshot_work_root(), "dacl-test"
        )
        work.__enter__()
        try:
            path = work.path / "plain.db"
            fd = work.create_file(path)
            try:
                os.write(fd, b"SQLite format 3" + bytes([0]))
            finally:
                os.close(fd)
            handle = credentials._open_verified_file(  # noqa: SLF001
                path, credentials._current_user_sid(), "备份临时文件"  # noqa: SLF001
            )
            credentials._kernel32.CloseHandle(handle)  # noqa: SLF001
        finally:
            work.cleanup()
    finally:
        case.tearDown()

def test_private_cleanup_refuses_junction_and_preserves_external_marker():
    case = BackupSnapshotCase()
    case.setUp()
    try:
        outside = case.tmp_root / "outside-cleanup"
        outside.mkdir()
        marker = outside / "keep.txt"
        marker.write_bytes(b"keep")
        work = backup_fs.PrivateWorkArea(
            case.service()._snapshot_work_root(), "cleanup-test"
        )
        work.__enter__()
        try:
            junction = work.path / "junction"
            result = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
                check=False,
                capture_output=True,
            )
            if result.returncode != 0:
                pytest.skip("junction creation unavailable")
            with pytest.raises(backup_fs.BackupPathError):
                work.cleanup()
        finally:
            try:
                work.cleanup()
            except Exception:
                pass
        assert marker.read_bytes() == b"keep"
    finally:
        case.tearDown()
