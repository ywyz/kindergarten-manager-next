"""Full listening backup, independent restore, cold open and refusal cases."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import threading
import uuid
from pathlib import Path

import pytest

from app.local import (
    backup_format,
    backup_validate,
    listening_assets,
    listening_service,
    profile_service,
)
from app.local.backup_snapshot import SnapshotService
from app.local.normalize import normalize_initialization
from app.local.restore_service import RestoreCore
from app.local.restore_types import MaintenanceHooks
from app.local.runtime import LocalRuntime
from tests.local import backup_fixture_support as fixture
from tests.local import listening_fixture_support as listening_fixture
from tests.local.support import BACKEND_DIR, initialize_body, worker_env


class _Hooks(MaintenanceHooks):
    def wait_host_idle(self, cancel) -> bool:
        return not cancel.is_set()

    def stop_transport(self) -> bool:
        return True


def _runtime(root: Path) -> LocalRuntime:
    runtime = LocalRuntime(root / "data", credential_root=root / "cred")
    runtime.prepare()
    return runtime


def _initialize(runtime: LocalRuntime) -> None:
    session = runtime.session()
    try:
        profile_service.initialize(
            session, normalize_initialization(**initialize_body())
        )
        session.commit()
    finally:
        session.close()


def _ids(runtime: LocalRuntime):
    session = runtime.session()
    try:
        context = profile_service.require_context(
            session, __import__("datetime").date.today()
        )
        return context.profile.id, context.terms[0].id
    finally:
        session.close()


def _listen(runtime: LocalRuntime, profile_id: str, record_id: str):
    return listening_fixture.listening_snapshot(
        runtime, profile_id=profile_id, record_id=record_id
    )


def _post_photo(runtime: LocalRuntime, profile_id: str, record: dict, domain: str,
                group_index: int, color, fmt: str = "JPEG") -> dict:
    session = runtime.session()
    try:
        group_id = record["domains"][
            listening_service.DOMAINS.index(domain)
        ]["groups"][group_index]["group_id"]
        return listening_assets.import_group_photo(
            session,
            runtime,
            profile_id=profile_id,
            record_id=record["record_id"],
            domain=domain,
            group_id=group_id,
            request_id=str(uuid.uuid4()),
            expected_revision=record["revision"],
            stream=__import__("io").BytesIO(
                listening_fixture.jpeg_bytes(color, (80, 60))
                if fmt == "JPEG"
                else listening_fixture.png_bytes(color, (80, 60))
            ),
            display_name=f"photo-{group_index}.{fmt.lower()}",
        )
    finally:
        session.close()


def _fill_domain(runtime: LocalRuntime, profile_id: str, record: dict,
                 domain: str, stars: dict[str, int], text: str) -> dict:
    session = runtime.session()
    try:
        index = listening_service.DOMAINS.index(domain)
        domain_dto = record["domains"][index]
        group_id = domain_dto["groups"][0]["group_id"]
        listening_service.save_domain(
            session,
            profile_id=profile_id,
            record_id=record["record_id"],
            domain=domain,
            request_id=str(uuid.uuid4()),
            expected_revision=record["revision"],
            patch={
                "observation_date": "9月1日 上午",
                "adult_count": "2",
                "child_age": "4岁",
                "goal": f"{domain}目标",
                "observation_area": "美工区",
                "overall_evaluation": f"{domain}综合评价",
                "support_strategy": f"{domain}支持策略",
                "evaluation": stars,
                "groups": [
                    {
                        "group_id": group_id,
                        "work_date": "9月2日",
                        "listening_text": text,
                    }
                ],
            },
        )
        return listening_service.read_record(
            session, profile_id=profile_id, record_id=record["record_id"]
        )
    finally:
        session.close()


def _make_source(root: Path) -> tuple[LocalRuntime, str, str, dict, dict]:
    runtime = _runtime(root)
    fixture.seed_existing_runtime(runtime)
    profile_id, term_id = _ids(runtime)
    session = runtime.session()
    try:
        first = listening_service.create_record(
            session,
            profile_id=profile_id,
            request_id=str(uuid.uuid4()),
            term_id=term_id,
            child_name="同名幼儿",
        )
        second = listening_service.create_record(
            session,
            profile_id=profile_id,
            request_id=str(uuid.uuid4()),
            term_id=term_id,
            child_name="同名幼儿",
        )
    finally:
        session.close()
    first_dto = _listen(runtime, profile_id, first["record_id"])["record"]
    second_dto = _listen(runtime, profile_id, second["record_id"])["record"]
    stars = {
        "health": {"health_1": 2, "health_2": 3},
        "language": {"language_1": 1},
        "social": {"social_1": 3},
        "science": {"science_1": 2},
        "art": {"art_1": 1},
    }
    for domain in listening_service.DOMAINS:
        first_dto = _fill_domain(
            runtime,
            profile_id,
            first_dto,
            domain,
            stars[domain],
            f"{domain} 倾听正文第一段\n第二段",
        )
    second_dto = _fill_domain(
        runtime,
        profile_id,
        second_dto,
        "art",
        {"art_1": 3},
        "乙的倾听正文",
    )
    first_dto = _post_photo(
        runtime, profile_id, first_dto, "health", 0, (200, 10, 10), "JPEG"
    )
    current = _listen(runtime, profile_id, first_dto["record_id"])["record"]
    first_dto = _post_photo(
        runtime, profile_id, current, "health", 1, (10, 200, 10), "PNG"
    )
    current = _listen(runtime, profile_id, first_dto["record_id"])["record"]
    first_dto = _post_photo(
        runtime, profile_id, current, "health", 2, (10, 10, 200), "JPEG"
    )
    second_dto = _post_photo(
        runtime, profile_id, second_dto, "art", 0, (90, 90, 90), "JPEG"
    )
    return runtime, profile_id, term_id, first, second


def _cold_open(root: Path) -> dict:
    output = root / "cold-open.json"
    env = worker_env()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["DISABLE_SQLALCHEMY_CEXT_RUNTIME"] = "1"
    tmp = root / "subprocess-tmp"
    tmp.mkdir(exist_ok=True)
    env["TEMP"] = str(tmp)
    env["TMP"] = str(tmp)
    process = subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "tests.local.listening_fixture_support",
            "cold_open",
            str(root / "data"),
            str(root / "cred"),
            str(output),
        ],
        cwd=str(BACKEND_DIR),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=180,
    )
    if process.returncode != 0:
        raise AssertionError(
            f"cold open failed rc={process.returncode}\n"
            f"stdout={process.stdout.decode('utf-8', 'replace')}\n"
            f"stderr={process.stderr.decode('utf-8', 'replace')}"
        )
    return json.loads(output.read_text(encoding="utf-8"))


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_full_listening_backup_restore_and_cold_open(tmp_path) -> None:
    source_root = tmp_path / "source"
    source, profile_id, _term_id, first, second = _make_source(source_root)
    try:
        first_snapshot = _listen(source, profile_id, first["record_id"])
        second_snapshot = _listen(source, profile_id, second["record_id"])
        source_db = fixture.database_fingerprint(source.db_path)
        source_resources = fixture.resource_fingerprint(source_root / "data")
        package = tmp_path / "full.kgmbackup"
        service = SnapshotService(
            source, app_version="listening-test", source_identity={"fixture": "l1"}
        )
        service.create(package, password=None, cancel=threading.Event())
        verified = service.verify(package, password=None, cancel=threading.Event())
        assert verified.source_revision == verified.target_revision == (
            "20261107_0010_local_listening_ai"
        )
        listening_entries = [
            entry
            for entry in verified.manifest["resources"]
            if entry.get("owner_kind") == "listening"
        ]
        observation_entries = [
            entry
            for entry in verified.manifest["resources"]
            if entry.get("owner_kind") is None
        ]
        assert listening_entries, verified.manifest["resources"]
        assert observation_entries, "the seeded observation resources must remain"
        for entry in observation_entries:
            assert "observation_id" in entry
            assert "listening_record_id" not in entry
        for entry in listening_entries:
            assert entry["owner_kind"] == "listening"
            assert "listening_record_id" in entry
            assert "observation_id" not in entry
            assert entry["path"].startswith("observations/assets/listening/")
        registered = {
            entry["path"]: entry
            for entry in backup_validate.iter_registered_resources(
                verified.database_path
            )
        }
        for entry in listening_entries:
            assert registered[entry["path"]]["owner_kind"] == "listening"
            assert (
                registered[entry["path"]]["listening_record_id"]
                == entry["listening_record_id"]
            )
    finally:
        source.dispose()

    target_root = tmp_path / "target"
    target = _runtime(target_root)
    try:
        core = RestoreCore(target, app_version="listening-test")
        preview = core.preview(
            package, None, operation_id=uuid.uuid4().hex, cancel=threading.Event()
        )
        assert preview.counts["listening_records"] == 2
        assert preview.counts["listening_assets"] == 4
        prepared = core.prepare(preview, cancel=threading.Event())
        result = core.install(prepared, hooks=_Hooks(), cancel=threading.Event())
        assert result.state == "installed_retired", result
        assert core.reopen().state == "reopened"
        assert fixture.database_fingerprint(target.db_path) == source_db
        assert fixture.resource_fingerprint(target_root / "data") == source_resources
        restored_first = _listen(target, profile_id, first["record_id"])
        restored_second = _listen(target, profile_id, second["record_id"])
        assert restored_first == first_snapshot
        assert restored_second == second_snapshot
    finally:
        target.dispose()

    cold = _cold_open(target_root)
    assert cold["revision"] == "20261107_0010_local_listening_ai"
    assert cold["profile_id"] == profile_id
    records = {record["record_id"]: record for record in cold["records"]}
    assert records[first["record_id"]] == first_snapshot["record"]
    assert records[second["record_id"]] == second_snapshot["record"]
    cold_assets = {asset["asset_id"]: asset for asset in cold["assets"]}
    for snapshot in (first_snapshot, second_snapshot):
        for asset in snapshot["assets"]:
            assert cold_assets[asset["asset_id"]]["content_hash"] == asset[
                "content_hash"
            ]
            assert cold_assets[asset["asset_id"]]["payload_sha256"] == asset[
                "payload_sha256"
            ]
    assert cold["counts"]["local_listening_records"] == 2
    assert cold["counts"]["local_listening_domains"] == 10
    assert cold["counts"]["local_listening_photo_groups"] == 30
    assert cold["counts"]["local_listening_assets"] == 4


def test_old_0008_package_restores_with_empty_listening_tables(tmp_path) -> None:
    old_root = tmp_path / "old"
    db, data = listening_fixture.build_old_0008_database(old_root)
    package = tmp_path / "old.kgmbackup"
    listening_fixture._write_old_package(
        db,
        data,
        package,
        password=None,
        app_version="old-0008",
    )
    target_root = tmp_path / "old-target"
    target = _runtime(target_root)
    try:
        service = SnapshotService(
            target, app_version="listening-test", source_identity={"fixture": "old"}
        )
        verified = service.verify(package, password=None, cancel=threading.Event())
        assert verified.source_revision == "20261102_0008_local_weekly_ai"
        assert verified.target_revision == "20261107_0010_local_listening_ai"
        connection = sqlite3.connect(str(verified.database_path))
        try:
            for table in (
                "local_listening_records",
                "local_listening_assets",
                "local_listening_operations",
            ):
                assert connection.execute(
                    f'SELECT COUNT(*) FROM "{table}"'
                ).fetchone()[0] == 0
        finally:
            connection.close()
        core = RestoreCore(target, app_version="listening-test")
        preview = core.preview(
            package, None, operation_id=uuid.uuid4().hex, cancel=threading.Event()
        )
        assert preview.counts["listening_records"] == 0
        prepared = core.prepare(preview, cancel=threading.Event())
        result = core.install(prepared, hooks=_Hooks(), cancel=threading.Event())
        assert result.state == "installed_retired", result
        assert core.reopen().state == "reopened"
        connection = sqlite3.connect(str(target.db_path))
        try:
            assert connection.execute(
                "SELECT version_num FROM local_alembic_version"
            ).fetchone() == ("20261107_0010_local_listening_ai",)
            assert connection.execute(
                "SELECT display_name FROM local_profile"
            ).fetchone()[0] == "王老师"
            assert connection.execute(
                "SELECT COUNT(*) FROM local_observation_records"
            ).fetchone()[0] >= 1
            assert connection.execute(
                "SELECT COUNT(*) FROM local_listening_records"
            ).fetchone()[0] == 0
        finally:
            connection.close()
    finally:
        target.dispose()
    cold = _cold_open(target_root)
    assert cold["records"] == []
    assert cold["counts"]["local_listening_records"] == 0
    assert cold["profile_id"]


def test_bad_image_hash_is_refused_without_publishing(tmp_path) -> None:
    root = tmp_path / "bad-image"
    runtime = _runtime(root)
    try:
        _initialize(runtime)
        profile_id, term_id = _ids(runtime)
        session = runtime.session()
        try:
            created = listening_service.create_record(
                session,
                profile_id=profile_id,
                request_id=str(uuid.uuid4()),
                term_id=term_id,
                child_name="坏图幼儿",
            )
            record = listening_service.read_record(
                session, profile_id=profile_id, record_id=created["record_id"]
            )
        finally:
            session.close()
        with_photo = _post_photo(
            runtime, profile_id, record, "health", 0, (1, 2, 3)
        )
        current = _listen(runtime, profile_id, record["record_id"])["record"]
        session = runtime.session()
        try:
            group_id = current["domains"][0]["groups"][0]["group_id"]
        finally:
            session.close()
        asset_path = None
        connection = sqlite3.connect(str(runtime.db_path))
        try:
            relative = connection.execute(
                "SELECT relative_path FROM local_listening_assets WHERE id = ?",
                (with_photo["asset_id"],),
            ).fetchone()[0]
            asset_path = root / "data" / Path(*relative.split("/"))
        finally:
            connection.close()
        assert asset_path is not None and asset_path.is_file()
        asset_path.write_bytes(b"not an image")
        db_before = _file_hash(runtime.db_path)
        package = tmp_path / "bad-image.kgmbackup"
        service = SnapshotService(
            runtime, app_version="listening-test", source_identity={"fixture": "bad"}
        )
        with pytest.raises(Exception) as caught:
            service.create(package, password=None, cancel=threading.Event())
        assert getattr(caught.value, "code", None) in {
            "BACKUP_RESOURCE_HASH",
            "BACKUP_RESOURCE_IMAGE_INVALID",
        }
        assert not package.exists()
        assert _file_hash(runtime.db_path) == db_before
        assert asset_path.read_bytes() == b"not an image"
    finally:
        runtime.dispose()


def test_bad_path_is_refused_without_publishing(tmp_path) -> None:
    root = tmp_path / "bad-path"
    runtime = _runtime(root)
    try:
        _initialize(runtime)
        profile_id, term_id = _ids(runtime)
        session = runtime.session()
        try:
            created = listening_service.create_record(
                session,
                profile_id=profile_id,
                request_id=str(uuid.uuid4()),
                term_id=term_id,
                child_name="坏路径幼儿",
            )
            record = listening_service.read_record(
                session, profile_id=profile_id, record_id=created["record_id"]
            )
        finally:
            session.close()
        imported = _post_photo(
            runtime, profile_id, record, "health", 0, (7, 8, 9)
        )
        connection = sqlite3.connect(str(runtime.db_path))
        try:
            connection.execute(
                "UPDATE local_listening_assets SET relative_path = ? WHERE id = ?",
                (
                    "observations/assets/listening/../outside.jpg",
                    imported["asset_id"],
                ),
            )
            connection.commit()
        finally:
            connection.close()
        with pytest.raises(backup_validate.BackupValidationError) as caught:
            list(backup_validate.iter_registered_resources(runtime.db_path))
        assert caught.value.code == "BACKUP_PATH_INVALID"
        db_before = _file_hash(runtime.db_path)
        package = tmp_path / "bad-path.kgmbackup"
        service = SnapshotService(
            runtime, app_version="listening-test", source_identity={"fixture": "bad"}
        )
        with pytest.raises(Exception):
            service.create(package, password=None, cancel=threading.Event())
        assert not package.exists()
        assert _file_hash(runtime.db_path) == db_before
    finally:
        runtime.dispose()
