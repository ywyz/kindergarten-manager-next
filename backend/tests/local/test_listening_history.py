"""Retained listening save history: versions, baselines and read-only APIs.

Covers the 0022 retention semantics end to end on synthetic databases only:
creation retains the initial (possibly empty) version, every actual content
change (manual save, rename, photo import/batch/remove/reorder/rotate, the
AI-adoption kernel) retains exactly one new version, no-change saves / replay
receipts / revision conflicts retain nothing, a pre-feature record keeps its
usable pre-modification original at the first post-feature save without
fabricating older revisions, and every retained snapshot is full, owned,
read-only and integrity-checked.  The loopback class exercises the real HTTP
routes including historical photo reads through the existing asset route.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import date

import pytest

from app.local import (
    listening_batch_assets,
    listening_history,
    listening_service,
    profile_service,
)
from app.local.errors import (
    LocalError,
    LocalHistoryNotFound,
    LocalStorageError,
    LocalValidationError,
)
from app.local.migrate import head_revision
from app.local.normalize import normalize_initialization
from app.local.runtime import LocalRuntime
from tests.local.listening_fixture_support import (
    get_bytes,
    jpeg_bytes,
    post_multipart,
)
from tests.local.support import (
    LocalTestCase,
    execute_sql,
    initialize_body,
    query_rows,
    query_scalar,
)


def _runtime(tmp_path, name="data") -> LocalRuntime:
    runtime = LocalRuntime(
        tmp_path / name, credential_root=tmp_path / (name + "-cred")
    )
    runtime.prepare()
    session = runtime.session()
    try:
        profile_service.initialize(
            session, normalize_initialization(**initialize_body())
        )
        session.commit()
    finally:
        session.close()
    return runtime


def _initials(runtime: LocalRuntime):
    session = runtime.session()
    try:
        context = profile_service.require_context(session, date.today())
        return context.profile.id, context.terms[0].id
    finally:
        session.close()


def _create(runtime: LocalRuntime, name: str = "历史幼儿"):
    profile_id, term_id = _initials(runtime)
    session = runtime.session()
    try:
        return listening_service.create_record(
            session,
            profile_id=profile_id,
            request_id=str(uuid.uuid4()),
            term_id=term_id,
            child_name=name,
        )
    finally:
        session.close()


def _save_goal(runtime: LocalRuntime, record_id: str, revision: int, goal, request_id=None):
    profile_id, _term_id = _initials(runtime)
    session = runtime.session()
    try:
        rid = request_id or str(uuid.uuid4())
        result = listening_service.save_domain(
            session,
            profile_id=profile_id,
            record_id=record_id,
            domain="health",
            request_id=rid,
            expected_revision=revision,
            patch={"goal": goal},
        )
        return {**result, "request_id": rid}
    finally:
        session.close()


def _versions(runtime: LocalRuntime, record_id: str):
    profile_id, _term_id = _initials(runtime)
    session = runtime.session()
    try:
        return listening_history.list_versions(
            session, profile_id=profile_id, record_id=record_id
        )
    finally:
        session.close()


def _read_version(runtime: LocalRuntime, record_id: str, version: int):
    profile_id, _term_id = _initials(runtime)
    session = runtime.session()
    try:
        return listening_history.read_version(
            session, profile_id=profile_id, record_id=record_id, version=version
        )
    finally:
        session.close()


def _read_record(runtime: LocalRuntime, record_id: str):
    profile_id, _term_id = _initials(runtime)
    session = runtime.session()
    try:
        return listening_service.read_record(
            session, profile_id=profile_id, record_id=record_id
        )
    finally:
        session.close()


def test_create_retains_initial_empty_version(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    created = _create(runtime, "初版幼儿")
    record_id = created["record_id"]

    listed = _versions(runtime, record_id)
    assert listed == {
        "items": [{"version": 1, "saved_at": created["created_at"]}]
    }

    detail = _read_version(runtime, record_id, 1)
    current = _read_record(runtime, record_id)
    assert detail["content"] == current
    assert detail["content"]["revision"] == 1
    assert detail["content"]["child_name"] == "初版幼儿"
    for domain in detail["content"]["domains"]:
        assert domain["goal"] is None
        assert all(item["stars"] is None for item in domain["evaluation"])
        assert all(group["asset_id"] is None for group in domain["groups"])
    assert detail["content"]["rotations"] == {}


def test_actual_change_appends_and_no_change_or_replay_do_not(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    record_id = _create(runtime)["record_id"]

    first = _save_goal(runtime, record_id, 1, "目标一")
    assert first["changed"] is True and first["revision"] == 2
    replay = _save_goal(
        runtime, record_id, 1, "目标一", request_id=first["request_id"]
    )
    assert replay == first
    unchanged = _save_goal(runtime, record_id, 2, "目标一")
    assert unchanged["changed"] is False and unchanged["revision"] == 2
    _save_goal(runtime, record_id, 2, "目标二")

    versions = [item["version"] for item in _versions(runtime, record_id)["items"]]
    assert versions == [3, 2, 1]
    assert _read_version(runtime, record_id, 2)["content"]["domains"][0][
        "goal"
    ] == "目标一"
    assert _read_version(runtime, record_id, 3)["content"]["domains"][0][
        "goal"
    ] == "目标二"


def test_revision_conflict_writes_no_history(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    record_id = _create(runtime)["record_id"]
    with pytest.raises(LocalError) as raised:
        _save_goal(runtime, record_id, 99, "冲突目标")
    assert raised.value.code == "LISTENING_REVISION_CONFLICT"
    assert [item["version"] for item in _versions(runtime, record_id)["items"]] == [1]


def test_rename_retains_child_name_version(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    record_id = _create(runtime, "旧名字")["record_id"]
    profile_id, _term_id = _initials(runtime)
    session = runtime.session()
    try:
        renamed = listening_service.patch_record_name(
            session,
            profile_id=profile_id,
            record_id=record_id,
            request_id=str(uuid.uuid4()),
            expected_revision=1,
            child_name="新名字",
        )
    finally:
        session.close()
    assert renamed["changed"] is True and renamed["revision"] == 2
    assert _read_version(runtime, record_id, 1)["content"]["child_name"] == "旧名字"
    assert _read_version(runtime, record_id, 2)["content"]["child_name"] == "新名字"


def test_pre_feature_record_keeps_original_without_fabricating(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    record_id = _create(runtime, "老档案幼儿")["record_id"]
    _save_goal(runtime, record_id, 1, "旧目标")  # revision 2, pre-feature style

    # Simulate a database saved before the feature existed: the record and
    # its content stay, the retained versions do not.
    execute_sql(
        runtime.db_path,
        "DELETE FROM local_listening_record_versions WHERE record_id = ?",
        (record_id,),
    )
    assert _versions(runtime, record_id) == {"items": []}
    pre_edit_updated_at = _read_record(runtime, record_id)["updated_at"]

    _save_goal(runtime, record_id, 2, "新目标")  # first post-feature change

    listed = _versions(runtime, record_id)["items"]
    assert [item["version"] for item in listed] == [3, 2]
    baseline, newest = listed[1], listed[0]
    assert baseline["version"] == 2 and baseline["saved_at"] == pre_edit_updated_at
    assert _read_version(runtime, record_id, 2)["content"]["domains"][0][
        "goal"
    ] == "旧目标"
    assert _read_version(runtime, record_id, 3)["content"]["domains"][0][
        "goal"
    ] == "新目标"
    # No unknown intermediate revisions are invented.
    with pytest.raises(LocalHistoryNotFound):
        _read_version(runtime, record_id, 1)


def test_corrupt_or_missing_history_is_refused(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    record_id = _create(runtime)["record_id"]
    _save_goal(runtime, record_id, 1, "将被篡改")

    with pytest.raises(LocalHistoryNotFound):
        _read_version(runtime, record_id, 99)
    for invalid in (0, "2", 2.0, True):
        with pytest.raises(LocalValidationError):
            _read_version(runtime, record_id, invalid)

    execute_sql(
        runtime.db_path,
        "UPDATE local_listening_record_versions SET content_json = ? "
        "WHERE record_id = ? AND version = 2",
        (
            json.dumps(
                {"record_id": record_id, "revision": 2, "goal": "伪造"},
                ensure_ascii=False,
            ),
            record_id,
        ),
    )
    with pytest.raises(LocalStorageError):
        _read_version(runtime, record_id, 2)


def test_foreign_or_missing_record_is_not_readable(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    _create(runtime)
    profile_id, _term_id = _initials(runtime)
    session = runtime.session()
    try:
        with pytest.raises(LocalError) as raised:
            listening_history.list_versions(
                session, profile_id=profile_id, record_id="no-such-record"
            )
        assert raised.value.code == "LISTENING_NOT_FOUND"
    finally:
        session.close()


def test_adoption_kernel_retains_history(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    record_id = _create(runtime)["record_id"]
    profile_id, _term_id = _initials(runtime)
    session = runtime.session()
    try:
        result, changed = listening_service.domain_patch_kernel_no_tx(
            session,
            profile_id=profile_id,
            record_id=record_id,
            domain="health",
            expected_revision=1,
            patch={"goal": "AI 采用目标", "evaluation": {"health_1": 3}},
        )
        session.commit()
    finally:
        session.close()
    assert changed is True and result["revision"] == 2
    content = _read_version(runtime, record_id, 2)["content"]
    health = content["domains"][0]
    assert health["goal"] == "AI 采用目标"
    assert health["evaluation"][0]["stars"] == 3


def test_batch_import_retains_one_version(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    record_id = _create(runtime, "批量幼儿")["record_id"]
    current = _read_record(runtime, record_id)
    groups = current["domains"][0]["groups"]
    profile_id, _term_id = _initials(runtime)
    session = runtime.session()
    try:
        batched = listening_batch_assets.import_batch_photos(
            session,
            runtime,
            profile_id=profile_id,
            record_id=record_id,
            request_id=str(uuid.uuid4()),
            expected_revision=1,
            assignments=[
                {
                    "index": 0,
                    "domain": "health",
                    "group_id": groups[0]["group_id"],
                    "display_name": "a.jpg",
                },
                {
                    "index": 1,
                    "domain": "health",
                    "group_id": groups[1]["group_id"],
                    "display_name": "b.jpg",
                },
            ],
            files={0: jpeg_bytes(), 1: jpeg_bytes((30, 90, 60))},
        )
    finally:
        session.close()
    assert batched["changed"] is True and batched["revision"] == 2
    content = _read_version(runtime, record_id, 2)["content"]
    batch_groups = content["domains"][0]["groups"]
    assert batch_groups[0]["asset_id"] == batched["items"][0]["asset_id"]
    assert batch_groups[1]["asset_id"] == batched["items"][1]["asset_id"]
    assert len(content["rotations"]) == 2


def test_version_table_constraints_are_enforced(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    record_id = _create(runtime)["record_id"]
    connection = sqlite3.connect(str(runtime.db_path))
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        base = {
            "record_id": record_id,
            "content_json": json.dumps({"record_id": record_id, "revision": 9}),
            "content_hash": "0" * 64,
            "created_at": "2026-11-22 00:00:00",
        }
        with pytest.raises(sqlite3.IntegrityError):
            # CHECK: version must be a positive integer.
            connection.execute(
                "INSERT INTO local_listening_record_versions "
                "(id, record_id, profile_id, version, content_json, "
                "content_hash, created_at) VALUES "
                "('ck1', :record_id, 'p', 0, :content_json, "
                ":content_hash, :created_at)",
                base,
            )
        with pytest.raises(sqlite3.IntegrityError):
            # CHECK: the content hash must be 64 hex characters.
            connection.execute(
                "INSERT INTO local_listening_record_versions "
                "(id, record_id, profile_id, version, content_json, "
                "content_hash, created_at) VALUES "
                "('ck2', :record_id, 'p', 9, :content_json, 'short', "
                ":created_at)",
                base,
            )
        with pytest.raises(sqlite3.IntegrityError):
            # FK: the record must exist for this profile.
            connection.execute(
                "INSERT INTO local_listening_record_versions "
                "(id, record_id, profile_id, version, content_json, "
                "content_hash, created_at) VALUES "
                "('fk1', 'unknown-record', 'p', 9, :content_json, "
                ":content_hash, :created_at)",
                base,
            )
    finally:
        connection.close()


class ListeningHistoryHttpTests(LocalTestCase):
    def _context(self, client):
        status, payload = client.get("/api/local/context")
        self.assertEqual(status, 200, payload)
        return payload

    def _create(self, client, term_id: str, name: str):
        status, payload = client.post(
            "/api/listening/records",
            {
                "request_id": str(uuid.uuid4()),
                "term_id": term_id,
                "child_name": name,
            },
        )
        self.assertEqual(status, 201, payload)
        return payload

    def _versions(self, client, record_id: str):
        status, payload = client.get(
            f"/api/listening/records/{record_id}/versions"
        )
        self.assertEqual(status, 200, payload)
        return payload

    def test_version_routes_shapes_ownership_and_errors(self) -> None:
        server = self.start_server()
        client = server.client()
        self.initialize(client)
        term_id = self._context(client)["terms"][0]["id"]
        record = self._create(client, term_id, "接口幼儿")
        record_id = record["record_id"]
        other = self._create(client, term_id, "另一个幼儿")

        listed = self._versions(client, record_id)
        self.assertEqual(
            listed, {"items": [{"version": 1, "saved_at": record["created_at"]}]}
        )

        status, saved = client.patch(
            f"/api/listening/records/{record_id}/domains/health",
            {
                "request_id": str(uuid.uuid4()),
                "expected_revision": 1,
                "goal": "接口目标",
                "evaluation": {"health_1": 2},
            },
        )
        self.assertEqual(status, 200, saved)
        self.assertEqual(saved["revision"], 2)

        listed = self._versions(client, record_id)
        self.assertEqual([item["version"] for item in listed["items"]], [2, 1])

        status, detail = client.get(
            f"/api/listening/records/{record_id}/versions/2"
        )
        self.assertEqual(status, 200, detail)
        status, current = client.get(f"/api/listening/records/{record_id}")
        self.assertEqual(status, 200, current)
        self.assertEqual(detail["version"], 2)
        self.assertEqual(detail["saved_at"], saved["saved_at"])
        # The retained snapshot is exactly the record detail structure.
        self.assertEqual(detail["content"], current)
        self.assertEqual(detail["content"]["domains"][0]["goal"], "接口目标")
        self.assertEqual(
            detail["content"]["domains"][0]["evaluation"][0]["stars"], 2
        )

        # Cross-record, unknown version and malformed input rules.
        other_listed = self._versions(client, other["record_id"])
        self.assertEqual([item["version"] for item in other_listed["items"]], [1])
        status, payload = client.get(
            f"/api/listening/records/{record_id}/versions/99"
        )
        self.assertEqual(status, 404, payload)
        self.assertEqual(payload["error"]["code"], "HISTORY_NOT_FOUND")
        status, payload = client.get(
            f"/api/listening/records/{record_id}/versions/0"
        )
        self.assertEqual(status, 422, payload)
        status, payload = client.get(
            f"/api/listening/records/{record_id}/versions/not-a-number"
        )
        self.assertEqual(status, 422, payload)
        status, payload = client.get(
            "/api/listening/records/does-not-exist/versions"
        )
        self.assertEqual(status, 404, payload)
        self.assertEqual(payload["error"]["code"], "LISTENING_NOT_FOUND")

    def test_photo_history_each_operation_retains_one_version(self) -> None:
        server = self.start_server()
        client = server.client()
        self.initialize(client)
        term_id = self._context(client)["terms"][0]["id"]
        record = self._create(client, term_id, "照片幼儿")
        record_id = record["record_id"]

        status, current = client.get(f"/api/listening/records/{record_id}")
        self.assertEqual(status, 200, current)
        health = current["domains"][0]
        group0, group1, group2 = health["groups"]

        photo = jpeg_bytes()
        status, imported = post_multipart(
            client,
            f"/api/listening/records/{record_id}/domains/health/photos/"
            f"{group0['group_id']}",
            {"request_id": str(uuid.uuid4()), "expected_revision": "1"},
            filename="photo.jpg",
            content=photo,
            content_type="image/jpeg",
        )
        self.assertEqual(status, 201, imported)
        asset_id = imported["asset_id"]
        self.assertEqual(imported["revision"], 2)

        status, rotated = client.post(
            f"/api/listening/records/{record_id}/domains/health/photos/"
            f"{group0['group_id']}/rotate",
            {
                "request_id": str(uuid.uuid4()),
                "expected_revision": 2,
                "rotation_quarters": 3,
            },
        )
        self.assertEqual(status, 200, rotated)
        self.assertEqual(rotated["revision"], 3)

        status, reordered = client.post(
            f"/api/listening/records/{record_id}/domains/health/photos/order",
            {
                "request_id": str(uuid.uuid4()),
                "expected_revision": 3,
                "group_ids": [
                    group2["group_id"],
                    group1["group_id"],
                    group0["group_id"],
                ],
            },
        )
        self.assertEqual(status, 200, reordered)
        self.assertEqual(reordered["revision"], 4)

        status, removed = client.request(
            "DELETE",
            f"/api/listening/records/{record_id}/domains/health/photos/"
            f"{group0['group_id']}",
            {"request_id": str(uuid.uuid4()), "expected_revision": 4},
        )
        self.assertEqual(status, 200, removed)
        self.assertEqual(removed["revision"], 5)

        listed = self._versions(client, record_id)
        self.assertEqual(
            [item["version"] for item in listed["items"]], [5, 4, 3, 2, 1]
        )

        # Version 2: the photo as first imported, rotation 0, original order.
        status, v2 = client.get(
            f"/api/listening/records/{record_id}/versions/2"
        )
        self.assertEqual(status, 200, v2)
        groups = v2["content"]["domains"][0]["groups"]
        self.assertEqual(
            [group["group_id"] for group in groups],
            [group0["group_id"], group1["group_id"], group2["group_id"]],
        )
        self.assertEqual(groups[0]["asset_id"], asset_id)
        self.assertEqual(v2["content"]["rotations"], {asset_id: 0})

        # Version 3: rotation applied; version 4: new order; version 5: gone.
        status, v3 = client.get(
            f"/api/listening/records/{record_id}/versions/3"
        )
        self.assertEqual(status, 200, v3)
        self.assertEqual(v3["content"]["rotations"], {asset_id: 3})
        status, v4 = client.get(
            f"/api/listening/records/{record_id}/versions/4"
        )
        self.assertEqual(status, 200, v4)
        self.assertEqual(
            [
                group["group_id"]
                for group in v4["content"]["domains"][0]["groups"]
            ],
            [group2["group_id"], group1["group_id"], group0["group_id"]],
        )
        status, v5 = client.get(
            f"/api/listening/records/{record_id}/versions/5"
        )
        self.assertEqual(status, 200, v5)
        self.assertIsNone(v5["content"]["domains"][0]["groups"][0]["asset_id"])
        # The removed photo's asset stays in the retained rotation map so a
        # historical viewer can still render it with its recorded rotation.
        self.assertEqual(v5["content"]["rotations"], {asset_id: 3})

        # The current detail equals the newest retained snapshot.
        status, current = client.get(f"/api/listening/records/{record_id}")
        self.assertEqual(status, 200, current)
        self.assertEqual(current, v5["content"])

        # The historical photo stays readable through the existing route even
        # though no current group references it any more.
        status, payload, headers = get_bytes(
            client,
            f"/api/listening/records/{record_id}/assets/{asset_id}/content",
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload, photo)
        self.assertEqual(headers.get("cache-control"), "no-store")


def test_migration_0022_upgrade_from_previous_head(tmp_path) -> None:
    from alembic import command

    from app.local.migrate import alembic_config, ensure_local_schema

    db_path = tmp_path / "old.db"
    config = alembic_config(db_path)
    previous_head = "20261112_0021_local_term_name_changes"
    command.upgrade(config, previous_head)
    connection = sqlite3.connect(str(db_path))
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    finally:
        connection.close()
    assert "local_listening_record_versions" not in tables
    assert "local_curriculum_deliberation_versions" not in tables

    inspection = ensure_local_schema(db_path)
    assert inspection.state == "current"
    assert inspection.current_revision == head_revision()
    connection = sqlite3.connect(str(db_path))
    try:
        for table in (
            "local_listening_record_versions",
            "local_curriculum_deliberation_versions",
        ):
            assert (
                connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                == 0
            )
    finally:
        connection.close()


def test_backup_validate_accepts_history_and_rejects_corruption(tmp_path) -> None:
    import shutil

    from app.local import backup_validate

    runtime = _runtime(tmp_path, "src")
    record_id = _create(runtime, "备份幼儿")["record_id"]
    _save_goal(runtime, record_id, 1, "备份目标")
    assert (
        query_scalar(
            runtime.db_path,
            "SELECT COUNT(*) AS n FROM local_listening_record_versions",
        )
        == 2
    )
    runtime.dispose()

    good = tmp_path / "good-copy.db"
    shutil.copyfile(runtime.db_path, good)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    facts = backup_validate.validate_database(
        good, migrate_old=False, scratch_dir=scratch
    )
    assert facts["revision"] == head_revision()

    corrupted = tmp_path / "corrupt-copy.db"
    shutil.copyfile(good, corrupted)
    rows = query_rows(
        corrupted,
        "SELECT id, content_json FROM local_listening_record_versions "
        "WHERE version = 2",
    )
    execute_sql(
        corrupted,
        "UPDATE local_listening_record_versions SET content_json = ? WHERE id = ?",
        (
            json.dumps(
                {**json.loads(rows[0]["content_json"]), "goal": "篡改文本"},
                ensure_ascii=False,
            ),
            rows[0]["id"],
        ),
    )
    scratch2 = tmp_path / "scratch2"
    scratch2.mkdir()
    with pytest.raises(backup_validate.BackupValidationError) as raised:
        backup_validate.validate_database(
            corrupted, migrate_old=False, scratch_dir=scratch2
        )
    assert raised.value.code == "BACKUP_DB_LOGICAL_INVALID"


def test_history_contains_no_credentials_or_foreign_objects(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    record_id = _create(runtime, "边界幼儿")["record_id"]
    _save_goal(runtime, record_id, 1, "边界目标")
    rows = query_rows(
        runtime.db_path,
        "SELECT version, content_json FROM local_listening_record_versions "
        "WHERE record_id = ? ORDER BY version",
        (record_id,),
    )
    assert len(rows) == 2
    for row in rows:
        content = json.loads(row["content_json"])
        assert set(content) == {
            "record_id",
            "child_name",
            "class_id",
            "term_id",
            "grade",
            "revision",
            "created_at",
            "updated_at",
            "domains",
            "rotations",
        }
        text = json.dumps(content, ensure_ascii=False)
        for forbidden in ("secret", "credential", "dpapi", "password"):
            assert forbidden not in text.lower()
