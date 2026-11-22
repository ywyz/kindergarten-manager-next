"""Retained curriculum deliberation save history and the per-record task list.

Synthetic coverage for the 0022 retention semantics: creation retains version
1, every actual save retains the full content/document snapshot under the
record's own version, the one-behind identical retry retains nothing, a
pre-feature record keeps its usable pre-modification original at the first
post-feature save, retained rows are read-only and integrity-checked, and the
new per-record ``GET /{record_id}/ai/tasks`` route is scoped, filtered and
does not change the existing task routes.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import uuid
from datetime import date

import pytest

from app.local import (
    ai_config_service,
    ai_task_service,
    backup_validate,
    curriculum_content,
    curriculum_history,
    curriculum_service,
    profile_service,
)
from app.local.curriculum_service import (
    CurriculumNotFound,
    CurriculumVersionConflict,
)
from app.local.errors import (
    LocalHistoryNotFound,
    LocalStorageError,
    LocalValidationError,
)
from app.local.migrate import head_revision
from app.local.normalize import normalize_initialization
from app.local.runtime import LocalRuntime
from tests.local.support import (
    LocalTestCase,
    execute_sql,
    initialize_body,
    query_rows,
    query_scalar,
)


def _content(**overrides: str) -> dict[str, str]:
    content = curriculum_content.empty_content()
    content.update(
        {
            "activity_name": "纸桥怎样更稳",
            "activity_form": "small_group",
            "child_count": "18",
            "organizer": "王老师",
            "recorder": "李老师",
            "institution": "示范幼儿园",
            "class_name": "中一班",
            "activity_date": "2026-11-22",
            "goals_original": "1. 比较平放与折过的桥面。",
            "goals_status": "unchanged",
            "preparation_original": "1. 每组准备卡纸和积木。",
            "preparation_status": "adjusted",
            "preparation_adjustment": "加上桌面定位线。",
            "process_original": "一、试搭纸桥。",
            "process_adjustment": "两轮试搭使用同一距离。",
            "reason": "统一间距便于比较。",
            "lesson_original": "活动名称  纸桥怎样更稳\n\n一、活动目标\n1. 比较不同桥面。",
            "lesson_revised": "活动名称  纸桥怎样更稳\n\n一、活动目标\n1. 对准定位线。",
        }
    )
    content.update(overrides)
    return content


def _document() -> dict:
    return {
        "schema_version": 1,
        "blocks": [
            {"section": "goals", "text": "一、活动目标\n1. 比较不同桥面。"},
            {"section": "process", "text": "一、试搭纸桥。"},
        ],
    }


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


def _profile(runtime: LocalRuntime) -> str:
    session = runtime.session()
    try:
        context = profile_service.require_context(session, date.today())
        return context.profile.id
    finally:
        session.close()


def _save(
    runtime: LocalRuntime,
    record_id: str,
    expected: int,
    content: dict,
    document=None,
):
    profile_id = _profile(runtime)
    session = runtime.session()
    try:
        if document is None:
            return curriculum_service.save_record(
                session,
                profile_id=profile_id,
                record_id=record_id,
                expected_version=expected,
                content=content,
            )
        return curriculum_service.save_record(
            session,
            profile_id=profile_id,
            record_id=record_id,
            expected_version=expected,
            content=content,
            document=document,
        )
    finally:
        session.close()


def _versions(runtime: LocalRuntime, record_id: str):
    profile_id = _profile(runtime)
    session = runtime.session()
    try:
        return curriculum_history.list_versions(
            session, profile_id=profile_id, record_id=record_id
        )
    finally:
        session.close()


def _read_version(runtime: LocalRuntime, record_id: str, version: int):
    profile_id = _profile(runtime)
    session = runtime.session()
    try:
        return curriculum_history.read_version(
            session, profile_id=profile_id, record_id=record_id, version=version
        )
    finally:
        session.close()


def test_create_retains_version_one_with_content_and_document(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    record_id = str(uuid.uuid4())
    created = _save(runtime, record_id, 0, _content(), _document())

    listed = _versions(runtime, record_id)
    assert listed == {
        "items": [{"version": 1, "saved_at": created["updated_at"]}]
    }
    detail = _read_version(runtime, record_id, 1)
    assert detail["version"] == 1
    assert detail["content"] == created["content"] == _content()
    assert detail["document"] == _document()
    assert detail["content"]["activity_name"] == "纸桥怎样更稳"
    assert detail["content"]["lesson_revised"] == (
        "活动名称  纸桥怎样更稳\n\n一、活动目标\n1. 对准定位线。"
    )


def test_update_appends_and_identical_retry_appends_nothing(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    record_id = str(uuid.uuid4())
    _save(runtime, record_id, 0, _content())

    updated = _save(
        runtime,
        record_id,
        1,
        _content(reason="调整后统一间距。"),
        _document(),
    )
    assert updated["version"] == 2
    # The one-behind identical retry returns the committed result unchanged.
    retried = _save(
        runtime,
        record_id,
        1,
        _content(reason="调整后统一间距。"),
        _document(),
    )
    assert retried == updated
    assert [item["version"] for item in _versions(runtime, record_id)["items"]] == [
        2,
        1,
    ]

    # A genuinely different save appends the next version.
    third = _save(runtime, record_id, 2, _content(reason="再次修订。"))
    assert third["version"] == 3
    listed = _versions(runtime, record_id)["items"]
    assert [item["version"] for item in listed] == [3, 2, 1]
    assert _read_version(runtime, record_id, 3)["content"]["reason"] == "再次修订。"
    assert _read_version(runtime, record_id, 2)["content"][
        "reason"
    ] == "调整后统一间距。"
    assert _read_version(runtime, record_id, 2)["document"] == _document()
    # An unset document carries the existing one forward, so the retained
    # snapshot for version 3 records that same carried document.
    assert _read_version(runtime, record_id, 3)["document"] == _document()


def test_version_conflict_writes_no_history(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    record_id = str(uuid.uuid4())
    _save(runtime, record_id, 0, _content())
    with pytest.raises(CurriculumVersionConflict):
        _save(runtime, record_id, 5, _content(activity_name="冲突"))
    assert [item["version"] for item in _versions(runtime, record_id)["items"]] == [1]


def test_pre_feature_record_keeps_original_without_fabricating(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    record_id = str(uuid.uuid4())
    _save(runtime, record_id, 0, _content())
    second = _save(
        runtime, record_id, 1, _content(reason="旧间距理由。"), _document()
    )

    # Simulate a database saved before the feature existed.
    execute_sql(
        runtime.db_path,
        "DELETE FROM local_curriculum_deliberation_versions "
        "WHERE record_id = ?",
        (record_id,),
    )
    assert _versions(runtime, record_id) == {"items": []}
    pre_edit_updated_at = second["updated_at"]

    third = _save(runtime, record_id, 2, _content(reason="新间距理由。"))
    assert third["version"] == 3

    listed = _versions(runtime, record_id)["items"]
    assert [item["version"] for item in listed] == [3, 2]
    baseline = listed[1]
    assert baseline["version"] == 2 and baseline["saved_at"] == pre_edit_updated_at
    assert _read_version(runtime, record_id, 2)["content"][
        "reason"
    ] == "旧间距理由。"
    assert _read_version(runtime, record_id, 2)["document"] == _document()
    assert _read_version(runtime, record_id, 3)["content"][
        "reason"
    ] == "新间距理由。"
    with pytest.raises(LocalHistoryNotFound):
        _read_version(runtime, record_id, 1)


def test_read_version_scoping_and_integrity(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    record_id = str(uuid.uuid4())
    _save(runtime, record_id, 0, _content())
    _save(runtime, record_id, 1, _content(reason="篡改前。"))

    with pytest.raises(LocalHistoryNotFound):
        _read_version(runtime, record_id, 99)
    for invalid in (0, "2", 2.0, True):
        with pytest.raises(LocalValidationError):
            _read_version(runtime, record_id, invalid)
    with pytest.raises(CurriculumNotFound):
        _versions(runtime, str(uuid.uuid4()))

    rows = query_rows(
        runtime.db_path,
        "SELECT id, content_json FROM local_curriculum_deliberation_versions "
        "WHERE version = 2",
    )
    execute_sql(
        runtime.db_path,
        "UPDATE local_curriculum_deliberation_versions SET content_json = ? "
        "WHERE id = ?",
        (
            json.dumps(
                {**json.loads(rows[0]["content_json"]), "reason": "篡改。"},
                ensure_ascii=False,
            ),
            rows[0]["id"],
        ),
    )
    with pytest.raises(LocalStorageError):
        _read_version(runtime, record_id, 2)


def test_read_version_rejects_malformed_document_and_keeps_legacy_null(
    tmp_path,
) -> None:
    runtime = _runtime(tmp_path)
    # Legacy record that never saved a linkage document: the retained null
    # is a readable full version.
    null_id = str(uuid.uuid4())
    _save(runtime, null_id, 0, _content())
    detail = _read_version(runtime, null_id, 1)
    assert detail["document"] is None
    assert detail["content"]["activity_name"] == "纸桥怎样更稳"

    # A malformed retained document (tampered snapshot) is not a readable
    # full version.
    doc_id = str(uuid.uuid4())
    _save(runtime, doc_id, 0, _content(), _document())
    rows = query_rows(
        runtime.db_path,
        "SELECT id FROM local_curriculum_deliberation_versions "
        "WHERE record_id = ? AND version = 1",
        (doc_id,),
    )
    execute_sql(
        runtime.db_path,
        "UPDATE local_curriculum_deliberation_versions "
        "SET document_json = ? WHERE id = ?",
        (json.dumps([1, 2]), rows[0]["id"]),
    )
    with pytest.raises(LocalStorageError):
        _read_version(runtime, doc_id, 1)
    # The untouched legacy-null record stays readable.
    assert _read_version(runtime, null_id, 1)["document"] is None


def test_version_table_constraints_are_enforced(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    record_id = str(uuid.uuid4())
    _save(runtime, record_id, 0, _content())
    connection = sqlite3.connect(str(runtime.db_path))
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        base = {
            "record_id": record_id,
            "content_json": json.dumps({"activity_name": "x"}, ensure_ascii=False),
            "content_hash": "0" * 64,
            "created_at": "2026-11-22 00:00:00",
        }
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO local_curriculum_deliberation_versions "
                "(id, record_id, profile_id, version, content_json, "
                "content_hash, created_at) VALUES "
                "('ck1', :record_id, 'p', 0, :content_json, :content_hash, "
                ":created_at)",
                base,
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO local_curriculum_deliberation_versions "
                "(id, record_id, profile_id, version, content_json, "
                "content_hash, created_at) VALUES "
                "('ck2', :record_id, 'p', 1, :content_json, 'short', "
                ":created_at)",
                base,
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO local_curriculum_deliberation_versions "
                "(id, record_id, profile_id, version, content_json, "
                "content_hash, created_at) VALUES "
                "('fk1', '00000000-0000-0000-0000-000000000000', 'p', 1, "
                ":content_json, :content_hash, :created_at)",
                base,
            )
    finally:
        connection.close()


def test_backup_validate_accepts_history_and_rejects_corruption(tmp_path) -> None:
    runtime = _runtime(tmp_path, "src")
    record_id = str(uuid.uuid4())
    _save(runtime, record_id, 0, _content())
    _save(runtime, record_id, 1, _content(reason="备份后理由。"))
    assert (
        query_scalar(
            runtime.db_path,
            "SELECT COUNT(*) AS n FROM local_curriculum_deliberation_versions",
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
    execute_sql(
        corrupted,
        "UPDATE local_curriculum_deliberation_versions "
        "SET content_json = '{\"activity_name\": \"伪造\"}' WHERE version = 1",
    )
    scratch2 = tmp_path / "scratch2"
    scratch2.mkdir()
    with pytest.raises(backup_validate.BackupValidationError) as raised:
        backup_validate.validate_database(
            corrupted, migrate_old=False, scratch_dir=scratch2
        )
    assert raised.value.code == "BACKUP_DB_LOGICAL_INVALID"

    # A malformed retained linkage document refuses the backup as well.
    doc_corrupt = tmp_path / "doc-corrupt-copy.db"
    shutil.copyfile(good, doc_corrupt)
    execute_sql(
        doc_corrupt,
        "UPDATE local_curriculum_deliberation_versions "
        "SET document_json = '[1, 2]' WHERE version = 1",
    )
    scratch3 = tmp_path / "scratch3"
    scratch3.mkdir()
    with pytest.raises(backup_validate.BackupValidationError) as raised_doc:
        backup_validate.validate_database(
            doc_corrupt, migrate_old=False, scratch_dir=scratch3
        )
    assert raised_doc.value.code == "BACKUP_DB_LOGICAL_INVALID"


class CurriculumHistoryHttpTests(LocalTestCase):
    def _context(self, client):
        status, payload = client.get("/api/local/context")
        self.assertEqual(status, 200, payload)
        return payload

    def _save(self, client, record_id: str, expected: int, content: dict, document=None):
        body = {
            "expected_version": expected,
            "content": content,
        }
        if document is not None:
            body["document"] = document
        status, payload = client.post(
            f"/api/local/curriculum-deliberations/{record_id}/save", body
        )
        self.assertEqual(status, 200, payload)
        return payload

    def _versions(self, client, record_id: str):
        status, payload = client.get(
            f"/api/local/curriculum-deliberations/{record_id}/versions"
        )
        self.assertEqual(status, 200, payload)
        return payload

    def test_version_routes_shapes_ownership_and_errors(self) -> None:
        server = self.start_server()
        client = server.client()
        self.initialize(client)
        record_id = str(uuid.uuid4())
        other_id = str(uuid.uuid4())

        created = self._save(client, record_id, 0, _content(), _document())
        self.assertEqual(created["version"], 1)
        self.assertEqual(
            self._versions(client, record_id),
            {"items": [{"version": 1, "saved_at": created["updated_at"]}]},
        )

        updated = self._save(
            client, record_id, 1, _content(reason="接口调整。")
        )
        self.assertEqual(updated["version"], 2)
        listed = self._versions(client, record_id)["items"]
        self.assertEqual([item["version"] for item in listed], [2, 1])

        status, detail = client.get(
            f"/api/local/curriculum-deliberations/{record_id}/versions/2"
        )
        self.assertEqual(status, 200, detail)
        self.assertEqual(detail["content"], updated["content"])
        # The unset document carries forward, so the retained snapshot for
        # version 2 keeps the same linkage document as the creation save.
        self.assertEqual(detail["document"], _document())

        status, first = client.get(
            f"/api/local/curriculum-deliberations/{record_id}/versions/1"
        )
        self.assertEqual(status, 200, first)
        self.assertEqual(first["content"]["reason"], "统一间距便于比较。")
        self.assertEqual(first["document"], _document())

        # Unknown record, unknown version and malformed input rules.
        status, payload = client.get(
            f"/api/local/curriculum-deliberations/{other_id}/versions"
        )
        self.assertEqual(status, 404, payload)
        self.assertEqual(payload["error"]["code"], "CURRICULUM_NOT_FOUND")
        status, payload = client.get(
            f"/api/local/curriculum-deliberations/{record_id}/versions/99"
        )
        self.assertEqual(status, 404, payload)
        self.assertEqual(payload["error"]["code"], "HISTORY_NOT_FOUND")
        status, payload = client.get(
            f"/api/local/curriculum-deliberations/{record_id}/versions/0"
        )
        self.assertEqual(status, 422, payload)
        status, payload = client.get(
            f"/api/local/curriculum-deliberations/{record_id}/versions/x"
        )
        self.assertEqual(status, 422, payload)
        status, payload = client.get(
            "/api/local/curriculum-deliberations/not-a-uuid/versions"
        )
        self.assertEqual(status, 422, payload)

        # The retained snapshot is exactly the record detail structure.
        status, current = client.get(
            f"/api/local/curriculum-deliberations/{record_id}"
        )
        self.assertEqual(status, 200, current)
        self.assertEqual(current["content"], detail["content"])

    def test_ai_tasks_list_route_scoping_filters_and_shapes(self) -> None:
        runtime = self.make_runtime()
        server = self.start_server(runtime)
        client = server.client()
        self.initialize(client)
        profile_id = None
        session = runtime.session()
        try:
            context = profile_service.require_context(session, date.today())
            profile_id = context.profile.id
            # A synthetic local AI configuration (never a real credential)
            # lets the shared task lifecycle create real curriculum tasks.
            ai_config_service.patch_config(
                session,
                expected_ai_config_version=0,
                base_url="https://api.deepseek.com/v1",
                model="deepseek-v4-flash",
                secret="synthetic-secret",
                secret_provided=True,
                request_id=str(uuid.uuid4()),
                credential_root=runtime.credential_root,
            )
            session.commit()
        finally:
            session.close()

        record_id = str(uuid.uuid4())
        other_id = str(uuid.uuid4())
        self._save(client, record_id, 0, _content())
        self._save(client, other_id, 0, _content())

        def _create_task(rid: str):
            session = runtime.session()
            try:
                result, created = ai_task_service.create_curriculum_task(
                    session,
                    runtime=None,
                    record_id=rid,
                    kind="split",
                    version=1,
                    content=_content(),
                    request_id=str(uuid.uuid4()),
                )
                return result, created
            finally:
                session.close()

        def _cancel_task(rid: str, task_id: str):
            session = runtime.session()
            try:
                result, _abort_id, _abort_kind = ai_task_service.cancel_task(
                    session,
                    task_id=task_id,
                    expected_execution_id=None,
                    request_id=str(uuid.uuid4()),
                    source_kind="curriculum_deliberation",
                    source_id=rid,
                )
                return result
            finally:
                session.close()

        first, _ = _create_task(record_id)
        _cancel_task(record_id, first["id"])
        second, _ = _create_task(record_id)
        other, _ = _create_task(other_id)

        status, payload = client.get(
            f"/api/local/curriculum-deliberations/{record_id}/ai/tasks"
        )
        self.assertEqual(status, 200, payload)
        items = payload["items"]
        self.assertEqual(len(items), 2)
        self.assertIsNone(payload["next_cursor"])
        for item in items:
            self.assertEqual(item["task_id"], item["id"])
            self.assertEqual(item["source_kind"], "curriculum_deliberation")
            self.assertEqual(item["record_id"], record_id)
            self.assertIn("task_type", item)
            self.assertIn("status", item)
            self.assertIn("created_at", item)
        self.assertEqual(
            {item["id"] for item in items}, {first["id"], second["id"]}
        )
        self.assertEqual(
            {item["status"] for item in items}, {"cancelled", "pending"}
        )

        # Status filter, pagination and cross-record isolation.
        status, pending = client.get(
            f"/api/local/curriculum-deliberations/{record_id}"
            "/ai/tasks?status=pending"
        )
        self.assertEqual(status, 200, pending)
        self.assertEqual([item["id"] for item in pending["items"]], [second["id"]])
        status, cancelled = client.get(
            f"/api/local/curriculum-deliberations/{record_id}"
            "/ai/tasks?status=cancelled"
        )
        self.assertEqual(status, 200, cancelled)
        self.assertEqual([item["id"] for item in cancelled["items"]], [first["id"]])
        status, empty = client.get(
            f"/api/local/curriculum-deliberations/{record_id}"
            "/ai/tasks?status=succeeded"
        )
        self.assertEqual(status, 200, empty)
        self.assertEqual(empty["items"], [])
        status, page = client.get(
            f"/api/local/curriculum-deliberations/{record_id}/ai/tasks?limit=1"
        )
        self.assertEqual(status, 200, page)
        self.assertEqual([item["id"] for item in page["items"]], [first["id"]])
        self.assertIsNotNone(page["next_cursor"])
        status, rest = client.get(
            f"/api/local/curriculum-deliberations/{record_id}"
            f"/ai/tasks?limit=1&cursor={page['next_cursor']}"
        )
        self.assertEqual(status, 200, rest)
        self.assertEqual([item["id"] for item in rest["items"]], [second["id"]])
        self.assertIsNone(rest["next_cursor"])
        status, other_list = client.get(
            f"/api/local/curriculum-deliberations/{other_id}/ai/tasks"
        )
        self.assertEqual(status, 200, other_list)
        self.assertEqual(
            [item["id"] for item in other_list["items"]], [other["id"]]
        )
        status, invalid = client.get(
            f"/api/local/curriculum-deliberations/{record_id}/ai/tasks?limit=0"
        )
        self.assertEqual(status, 422, invalid)
        status, unknown = client.get(
            f"/api/local/curriculum-deliberations/{uuid.uuid4().hex}/ai/tasks"
        )
        self.assertEqual(status, 404, unknown)
        self.assertEqual(unknown["error"]["code"], "CURRICULUM_NOT_FOUND")

        # The existing single-task route and POST behaviour stay unchanged.
        status, task = client.get(
            f"/api/local/curriculum-deliberations/{record_id}/ai/tasks/"
            f"{first['id']}"
        )
        self.assertEqual(status, 200, task)
        self.assertEqual(task["id"], first["id"])
        self.assertNotIn("task_id", task)
