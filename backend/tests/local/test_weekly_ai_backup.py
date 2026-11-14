"""G1 weekly AI backup/history compatibility and old-archive preservation."""
from __future__ import annotations
import io, json, os, shutil, sqlite3, threading, uuid, zipfile
import pytest
from datetime import datetime, timezone
from pathlib import Path
from alembic import command
from app.local import (backup_format, backup_snapshot, backup_validate,
                       weekly_plan_content, weekly_plan_snapshot)
from app.local.migrate import alembic_config, head_revision
from app.local.restore_service import RestoreCore
from app.local.restore_types import MaintenanceHooks
from app.local.runtime import LocalRuntime
from tests.local.backup_fixture_support import (
    OLD_0007_TABLE_COLUMNS, create_old_0007_fixture, migration_rows,
    resource_fingerprint,
)
PROMPT_TABLES = {"local_prompt_bundles", "local_personal_prompt_heads",
                  "local_personal_prompt_versions"}
# Current build adds one built-in default revision to these three tasks.  Their
# uncustomised heads advance latest_default_revision while retaining the same
# current personal revision; all other old heads must stay byte-identical.
DEFAULT_HEAD_BUMP_TASKS = {
    "daily_other_activities",
    "game_observation_generate",
    "game_observation_rewrite",
}
HEAD_KEY_COLUMNS = ("profile_id", "task_type")
# Original 0007 archive/fidelity and plaintext/password restore tests use
# create_old_0007_fixture() with its default frozen rows.  Current-build weekly
# AI business tests explicitly pass align_default_prompts=True; that synthetic
# alignment is not evidence about the untouched original package.
class _Hooks(MaintenanceHooks):
    def wait_host_idle(self, cancel) -> bool:
        return not cancel.is_set()
    def stop_transport(self) -> bool:
        return True
def _copy_old_tree(source: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source / "kindergarten.db", target / "kindergarten.db")
    for item in (source / "observations").rglob("*"):
        if item.is_file():
            destination = target / item.relative_to(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, destination)

def _sql_value(value: object) -> object:
    if not isinstance(value, list) or not value:
        return value
    if value[0] == "null":
        return None
    if value[0] in ("text", "int", "float"):
        return value[1]
    return value


def _row_value(row: str) -> dict:
    return {key: _sql_value(value) for key, value in json.loads(row)}


def _head_key(row: dict) -> tuple:
    return tuple(
        json.dumps(row[column], ensure_ascii=False, sort_keys=True)
        for column in HEAD_KEY_COLUMNS
    )


def _old_head_rows_preserved(old_rows: list[str], new_rows: list[str]) -> None:
    new_by_key = {
        _head_key(_row_value(row)): _row_value(row)
        for row in new_rows
    }
    for row in old_rows:
        before_row = _row_value(row)
        key = _head_key(before_row)
        after_row = new_by_key.get(key)
        assert after_row is not None, key
        task_type = before_row["task_type"]
        if task_type in DEFAULT_HEAD_BUMP_TASKS:
            # Only the default pointer and update stamp may advance, and only
            # when the current sync actually registers that new default.  The
            # chosen personal revision (customised or not) stays put; the
            # existing personal version row is checked by the additive table
            # assertion below.  Migration-only paths legitimately leave it
            # unchanged.
            assert after_row["current_revision"] == before_row["current_revision"], key
            assert (
                after_row["required_contract_version"]
                == before_row["required_contract_version"]
            ), key
            assert after_row["created_at"] == before_row["created_at"], key
            if after_row != before_row:
                assert (
                    after_row["latest_default_revision"]
                    == before_row["latest_default_revision"] + 1
                ), key
        else:
            assert after_row == before_row, key


def _old_rows_preserved(before: dict, after: dict, *,
                        allow_default_head_bump: bool = False) -> None:
    # The three default head bumps are only legal where the current build runs
    # its ordinary package sync against an old archive: the 0007 runtime
    # prepare and the reopen after restoring an old package.  Migration-only
    # mirrors and restores of an already-current package stay row-for-row
    # strict, so the default is False and only those two callers opt in.
    for table, item in before["tables"].items():
        old = item["rows"]
        new = after["tables"][table]["rows"]
        if table == "local_personal_prompt_heads":
            if allow_default_head_bump:
                _old_head_rows_preserved(old, new)
            else:
                assert old == new, table
        elif table in PROMPT_TABLES:
            assert all(new.count(row) >= old.count(row) for row in old), table
        else:
            assert old == new, table
def _write_old_package(db_path: Path, data_dir: Path, output: Path,
                       password: str | None) -> None:
    scratch = output.parent / "package-scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    facts = backup_validate.inspect_source_database(db_path, scratch_dir=scratch)
    resources: dict[str, bytes] = {}
    entries = []
    for entry in backup_validate.iter_registered_resources(db_path):
        payload = data_dir.joinpath(*entry["path"].split("/")).read_bytes()
        resources[entry["path"]] = payload
        entries.append({
            "asset_id": entry["asset_id"], "bytes": len(payload),
            "derivative_id": entry["derivative_id"], "kind": entry["kind"],
            "observation_id": entry["observation_id"], "path": entry["path"],
            "sha256": entry["sha256"],
        })
    db_bytes = db_path.read_bytes()
    manifest = {
        "format_version": 1, "snapshot_id": "b" * 32,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "app_version": "g1-old-fixture",
        "database_revision": facts["source_revision"],
        "ai_contracts": facts["source_ai_contracts"],
        "database": {"path": "db/kindergarten.db", "bytes": len(db_bytes),
                     "sha256": facts["source_sha256"]},
        "resources": entries,
        "counts": {"database_bytes": len(db_bytes), "resources": len(entries),
                   "resources_bytes": sum(len(v) for v in resources.values())},
        "source_identity": {"fixture": "old-0007"},
    }
    payload_buffer = io.BytesIO()
    with zipfile.ZipFile(payload_buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("manifest.json",
                         json.dumps(manifest, ensure_ascii=False).encode("utf-8"))
        archive.writestr("db/kindergarten.db", db_bytes)
        for name in sorted(resources):
            archive.writestr(name, resources[name])
    payload = payload_buffer.getvalue()
    if password is None:
        header = backup_format.encode_header(mode=1, payload_len=len(payload))
        output.write_bytes(header + payload)
        return
    salt = os.urandom(backup_format.SALT_LEN)
    nonce = os.urandom(backup_format.NONCE_LEN)
    key = backup_format.derive_key(password, salt)
    header = backup_format.encode_header(mode=2, payload_len=len(payload),
                                         salt=salt, nonce=nonce)
    cipher = io.BytesIO()
    tag = backup_format.encrypt_payload(io.BytesIO(payload), cipher, key=key,
                                        nonce=nonce, aad=header,
                                        length=len(payload))
    output.write_bytes(header + cipher.getvalue() + tag)
def test_0007_archive_migration_preserves_raw_old_rows_and_photos(tmp_path):
    old = tmp_path / "old-data"
    db = old / "kindergarten.db"
    create_old_0007_fixture(db, old)
    before = migration_rows(db)
    before_resources = resource_fingerprint(old)
    migrated = tmp_path / "migrated-data"
    _copy_old_tree(old, migrated)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    facts = backup_validate.validate_database(
        migrated / "kindergarten.db", migrate_old=True,
        require_current=False, scratch_dir=scratch,
    )
    assert facts["source_revision"] == "20261101_0007_local_weekly"
    assert facts["revision"] == head_revision()
    after = migration_rows(migrated / "kindergarten.db")
    _old_rows_preserved(before, after)
    assert resource_fingerprint(migrated) == before_resources
    assert len(before["tables"]) == 48
    con = sqlite3.connect(str(migrated / "kindergarten.db"))
    try:
        for table, columns in {
            "local_ai_inputs": ("weekly_plan_id", "weekly_draft_id", "create_operation_id"),
            "local_ai_tasks": ("weekly_plan_id",),
            "local_ai_executions": ("weekly_plan_id",),
            "local_ai_candidates": ("weekly_plan_id",),
        }.items():
            for column in columns:
                assert con.execute(
                    f'SELECT COUNT(*) FROM "{table}" WHERE "{column}" IS NOT NULL'
                ).fetchone()[0] == 0
        assert con.execute(
            "SELECT COUNT(*) FROM local_weekly_plan_ai_adoption"
        ).fetchone()[0] == 0
    finally:
        con.close()

def test_0007_original_archive_accepts_known_historical_other_activities(
    tmp_path,
):
    """The frozen 0007 one-character wording is a known historical default.

    It is accepted by exact local re-computation, without rewriting the old row,
    and the rest of the normal package sync still runs.
    """
    old = tmp_path / "old-data"
    db = old / "kindergarten.db"
    create_old_0007_fixture(db, old)
    connection = sqlite3.connect(str(db))
    try:
        original = connection.execute(
            "SELECT bundle_hash, guidance_defaults_json "
            "FROM local_prompt_bundles WHERE task_type = "
            "'daily_other_activities' AND contract_version = 1 "
            "AND default_revision = 2"
        ).fetchone()
    finally:
        connection.close()
    assert original is not None
    from app.local.prompt_bundles import PROMPT_BUNDLE_MANIFEST
    current = next(
        item for item in PROMPT_BUNDLE_MANIFEST
        if item["task_type"] == "daily_other_activities"
        and item["contract_version"] == 1
        and item["default_revision"] == 2
    )
    assert original[0] != current["bundle_hash"]
    current_hashes = {
        (item["task_type"], item["contract_version"], item["default_revision"]):
        item["bundle_hash"]
        for item in PROMPT_BUNDLE_MANIFEST
    }
    connection = sqlite3.connect(str(db))
    try:
        old_hashes = {
            (row[0], row[1], row[2]): row[3]
            for row in connection.execute(
                "SELECT task_type, contract_version, default_revision, "
                "bundle_hash FROM local_prompt_bundles"
            )
        }
    finally:
        connection.close()
    assert {
        key for key in old_hashes.keys() & current_hashes.keys()
        if old_hashes[key] != current_hashes[key]
    } == {("daily_other_activities", 1, 2)}
    runtime_data = tmp_path / "runtime-data"
    _copy_old_tree(old, runtime_data)
    runtime = LocalRuntime(runtime_data, credential_root=tmp_path / "credentials")
    try:
        runtime.prepare()
        assert runtime.prompt_sync_error is None
        connection = sqlite3.connect(str(runtime_data / "kindergarten.db"))
        try:
            assert connection.execute(
                "SELECT bundle_hash, guidance_defaults_json "
                "FROM local_prompt_bundles WHERE task_type = "
                "'daily_other_activities' AND contract_version = 1 "
                "AND default_revision = 2"
            ).fetchone() == original
            assert connection.execute(
                "SELECT COUNT(*) FROM local_prompt_bundles "
                "WHERE task_type LIKE 'weekly_%'"
            ).fetchone()[0] == 6
            assert connection.execute(
                "SELECT COUNT(*) FROM local_personal_prompt_heads "
                "WHERE task_type LIKE 'weekly_%'"
            ).fetchone()[0] >= 6
        finally:
            connection.close()
    finally:
        runtime.dispose()


def test_0007_aligned_runtime_sync_adds_only_weekly_prompt_rows(tmp_path):
    """Deliberately aligned synthetic 0007: current-build weekly registration is
    normal.  This is not an original-package fidelity test."""
    old = tmp_path / "old-data"
    db = old / "kindergarten.db"
    create_old_0007_fixture(db, old, align_default_prompts=True)
    before = migration_rows(db)
    runtime_data = tmp_path / "runtime-data"
    _copy_old_tree(old, runtime_data)
    runtime = LocalRuntime(runtime_data, credential_root=tmp_path / "credentials")
    try:
        runtime.prepare()
    finally:
        runtime.dispose()
    after = migration_rows(runtime_data / "kindergarten.db")
    _old_rows_preserved(before, after, allow_default_head_bump=True)
    before_heads = {
        _head_key(row): row
        for row in map(_row_value, before["tables"]["local_personal_prompt_heads"]["rows"])
    }
    after_heads = {
        _head_key(row): row
        for row in map(_row_value, after["tables"]["local_personal_prompt_heads"]["rows"])
    }
    changed_head_keys = {
        key for key, row in before_heads.items() if after_heads.get(key) != row
    }
    assert {
        before_heads[key]["task_type"] for key in changed_head_keys
    } == DEFAULT_HEAD_BUMP_TASKS
    assert len(changed_head_keys) == 3
    # The frozen archive may already carry this build's current defaults; the
    # meaningful invariant is that no old bundle is removed and the full
    # weekly set is registered below.
    assert len(after["tables"]["local_prompt_bundles"]["rows"]) >= len(
        before["tables"]["local_prompt_bundles"]["rows"]
    )
    assert len(after["tables"]["local_personal_prompt_heads"]["rows"]) >= len(
        before["tables"]["local_personal_prompt_heads"]["rows"]
    )

    weekly_types = {
        "weekly_games_select", "weekly_key_week_focus",
        "weekly_environment_setup", "weekly_habit_culture",
        "weekly_home_cooperation", "weekly_materials_generate",
    }
    con = sqlite3.connect(str(runtime_data / "kindergarten.db"))
    try:
        bundles = {
            row[0] for row in con.execute(
                "SELECT task_type FROM local_prompt_bundles "
                "WHERE task_type LIKE 'weekly_%'"
            )
        }
        heads = {
            row[0] for row in con.execute(
                "SELECT task_type FROM local_personal_prompt_heads "
                "WHERE task_type LIKE 'weekly_%'"
            )
        }
        versions = {
            row[0] for row in con.execute(
                "SELECT task_type FROM local_personal_prompt_versions "
                "WHERE task_type LIKE 'weekly_%'"
            )
        }
    finally:
        con.close()
    assert bundles == weekly_types
    assert heads == weekly_types
    assert versions == weekly_types

def test_0007_plain_and_encrypted_packages_verify_and_restore(tmp_path):
    old = tmp_path / "old-data"
    db = old / "kindergarten.db"
    create_old_0007_fixture(db, old)
    before = migration_rows(db)
    for password in (None, "synthetic-old-password"):
        label = "plain" if password is None else "encrypted"
        package = tmp_path / f"old-{label}.kgmbackup"
        _write_old_package(db, old, package, password)
        target_data = tmp_path / f"target-{label}"
        target = LocalRuntime(target_data, credential_root=tmp_path / f"cred-{label}")
        target.prepare()
        try:
            service = backup_snapshot.SnapshotService(
                target, app_version="g1-test", source_identity={"fixture": label}
            )
            verified = service.verify(package, password=password,
                                      cancel=threading.Event())
            assert verified.source_revision == "20261101_0007_local_weekly"
            assert verified.target_revision == head_revision()
            core = RestoreCore(target, app_version="g1-test",
                               weekly_export_manager=None)
            preview = core.preview(package, password,
                                   operation_id=uuid.uuid4().hex,
                                   cancel=threading.Event())
            prepared = core.prepare(preview, cancel=threading.Event())
            result = core.install(prepared, hooks=_Hooks(),
                                  cancel=threading.Event())
            assert result.state == "installed_retired", result
            assert core.reopen().state == "reopened"
            after = migration_rows(target_data / "kindergarten.db")
            _old_rows_preserved(before, after, allow_default_head_bump=True)
            assert target.launch_id is None
        finally:
            target.dispose()

def test_0008_aligned_restore_protection_package_round_trip(tmp_path):
    """Current weekly-AI restore protection after deliberate synthetic
    alignment; untouched 0007 restore is covered by the default plaintext and
    encrypted package test above."""
    old = tmp_path / "old-data"
    db = old / "kindergarten.db"
    create_old_0007_fixture(db, old, align_default_prompts=True)
    source_data = tmp_path / "source-data"
    _copy_old_tree(old, source_data)
    source = LocalRuntime(source_data, credential_root=tmp_path / "source-cred")
    source.prepare()
    package = tmp_path / "current.kgmbackup"
    try:
        backup_snapshot.SnapshotService(
            source, app_version="g1-test", source_identity={"fixture": "current"}
        ).create(package, password=None, cancel=threading.Event())
    finally:
        source.dispose()
    target_data = tmp_path / "target-data"
    _copy_old_tree(old, target_data)
    target = LocalRuntime(target_data, credential_root=tmp_path / "target-cred")
    target.prepare()
    try:
        _seed_real_adoption(target)
        target_before = migration_rows(target_data / "kindergarten.db")
        from tests.local.backup_fixture_support import database_fingerprint
        before_fingerprint = database_fingerprint(target_data / "kindergarten.db",
                                                    include_runtime_fields=True)
        core = RestoreCore(target, app_version="g1-test")
        preview = core.preview(package, None, operation_id=uuid.uuid4().hex,
                               cancel=threading.Event())
        prepared = core.prepare(preview, cancel=threading.Event())
        result = core.install(prepared, hooks=_Hooks(), cancel=threading.Event())
        assert result.state == "installed_retired", result
        protection = Path(result.protection_display_path)
        assert protection.is_file()
        verify = backup_snapshot.SnapshotService(
            target, app_version="g1-test", source_identity={}
        ).verify(protection, password=None, cancel=threading.Event())
        assert verify.source_revision == head_revision()
        target.dispose()
        restored_data = tmp_path / "protection-restored"
        restored = LocalRuntime(restored_data, credential_root=tmp_path / "restored-cred")
        restored.prepare()
        try:
            core2 = RestoreCore(restored, app_version="g1-test")
            p2 = core2.preview(protection, None, operation_id=uuid.uuid4().hex,
                               cancel=threading.Event())
            prep2 = core2.prepare(p2, cancel=threading.Event())
            res2 = core2.install(prep2, hooks=_Hooks(), cancel=threading.Event())
            assert res2.state == "installed_retired", res2
            assert core2.reopen().state == "reopened"
            after = migration_rows(restored_data / "kindergarten.db")
            _old_rows_preserved(target_before, after)
            assert database_fingerprint(restored_data / "kindergarten.db",
                                       include_runtime_fields=True) == before_fingerprint
        finally:
            restored.dispose()
    finally:
        target.dispose()

def test_schema2_mixed_confirmation_validates_on_real_sqlite(tmp_path):
    old = tmp_path / "old-data"
    db = old / "kindergarten.db"
    create_old_0007_fixture(db, old)
    migrated = tmp_path / "migrated"
    _copy_old_tree(old, migrated)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    backup_validate.validate_database(migrated / "kindergarten.db",
                                      migrate_old=True, require_current=False,
                                      scratch_dir=scratch)
    con = sqlite3.connect(str(migrated / "kindergarten.db"))
    try:
        plan_id, draft_id, draft_version, content_json = con.execute(
            "SELECT weekly_plan_id, id, version, content_json FROM "
            "local_weekly_plan_contents ORDER BY version DESC LIMIT 1"
        ).fetchone()
        conf = con.execute(
            "SELECT id, version, snapshot_json, facts_json FROM "
            "local_weekly_plan_confirmations WHERE weekly_plan_id=? "
            "ORDER BY version DESC LIMIT 1", (plan_id,)
        ).fetchone()
        snapshot = json.loads(conf[2])
        content2 = weekly_plan_content.promote_to_schema2(json.loads(content_json))
        new_content_id = uuid.uuid4().hex
        new_version = draft_version + 1
        new_hash = weekly_plan_content.content_hash(content2)
        snapshot2 = weekly_plan_snapshot.build_confirmation_snapshot(
            weekly_plan_id=plan_id, profile_id=snapshot["profile_id"],
            class_id=snapshot["class_id"], term_id=snapshot["term_id"],
            draft_id=new_content_id, draft_version=new_version,
            content_hash=new_hash, header=snapshot["header"],
            creation_context=snapshot["creation_context"], content=content2,
            facts=json.loads(conf[3]),
        )
        snapshot_hash = weekly_plan_snapshot.snapshot_hash(snapshot2)
        facts_obj = json.loads(conf[3])
        facts_hash = weekly_plan_snapshot.snapshot_hash(facts_obj)
        now = datetime.utcnow().isoformat()
        con.execute(
            "INSERT INTO local_weekly_plan_contents (id, weekly_plan_id, version, "
            "schema_version, content_json, content_hash, editor_profile_id, "
            "created_at) VALUES (?,?,?,?,?,?,?,?)",
            (new_content_id, plan_id, new_version, 2,
             json.dumps(content2, ensure_ascii=False, sort_keys=True,
                        separators=(",", ":")), new_hash,
             snapshot["profile_id"], now),
        )
        con.execute(
            "INSERT INTO local_weekly_plan_confirmations (id, weekly_plan_id, "
            "version, draft_id, draft_version, schema_version, snapshot_json, "
            "snapshot_hash, facts_json, facts_hash, note, confirmed_by, "
            "confirmed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (uuid.uuid4().hex, plan_id, conf[1] + 1, new_content_id, new_version,
             1, json.dumps(snapshot2, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":")), snapshot_hash,
             conf[3], facts_hash, None, snapshot["profile_id"], now),
        )
        con.commit()
    finally:
        con.close()
    facts = backup_validate.validate_database(
        migrated / "kindergarten.db", migrate_old=False,
        require_current=True, scratch_dir=scratch,
    )
    assert facts["revision"] == head_revision()
    assert weekly_plan_snapshot.validate_confirmation_snapshot(snapshot2)

from app.local import (weekly_ai_adoption, weekly_ai_contracts, weekly_ai_service,
                       weekly_plan_service)
from app.local.models import (LocalAICandidate, LocalAIExecution, LocalAIInput,
                              LocalAITask, LocalWeeklyPlan)
def _seed_real_adoption(runtime: LocalRuntime) -> dict:
    session = runtime.session()
    try:
        plan = session.query(LocalWeeklyPlan).one()
        result, _created = weekly_ai_service.create_weekly_tasks(
            session, runtime=None, profile_id=plan.profile_id,
            plan_id=plan.id, request_id=uuid.uuid4().hex,
            expected_draft_version=plan.current_draft_version,
            operation_kind="weekly_ai_columns_create",
            task_specs=[weekly_ai_service.WeeklyTaskSpec(
                "weekly_key_week_focus", "key_week_focus")],
        )
        task = session.get(LocalAITask, result["tasks"][0]["task_id"])
        input_row = session.get(LocalAIInput, task.input_id)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        execution = LocalAIExecution(
            id=uuid.uuid4().hex, task_id=task.id, source_kind="weekly_plan",
            source_id=plan.id, observation_id=None, daily_plan_id=None,
            weekly_plan_id=plan.id, input_id=input_row.id,
            task_type=task.task_type, generation=1,
            launch_id=str(uuid.uuid4()), permit_id=str(uuid.uuid4()),
            config_version=1, profile_id=plan.profile_id,
            personal_revision=1, contract_version=1, default_revision=1,
            state="succeeded", runtime_meta_json={}, started_at=now,
            created_at=now, ended_at=now,
        )
        session.add(execution)
        session.flush()
        raw = weekly_ai_contracts.parse_column_candidate(
            json.dumps({"text": "合成重点：观察自然"}).encode(),
            task_type=task.task_type,
        )
        candidate = LocalAICandidate(
            id=uuid.uuid4().hex, profile_id=plan.profile_id,
            execution_id=execution.id, task_id=task.id,
            source_kind="weekly_plan", source_id=plan.id,
            observation_id=None, daily_plan_id=None, weekly_plan_id=plan.id,
            input_id=input_row.id, task_type=task.task_type,
            contract_version=1, schema_version=1, raw_candidate_json=raw,
            candidate_hash=weekly_ai_contracts.candidate_hash(raw),
            created_at=now,
        )
        session.add(candidate)
        task.current_execution_id = execution.id
        task.generation = 1
        task.status = "succeeded"
        session.commit()
        unsubmitted = weekly_ai_adoption.preview_adoption(
            session, runtime=runtime, profile_id=plan.profile_id,
            plan_id=plan.id, expected_draft_version=plan.current_draft_version,
            selections=[{"candidate_id": candidate.id,
                         "target": "key_week_focus"}],
            launch_id="g1-launch", session_scope_hash="c" * 64,
        )["preview_token"]
        preview = weekly_ai_adoption.preview_adoption(
            session, runtime=runtime, profile_id=plan.profile_id,
            plan_id=plan.id, expected_draft_version=plan.current_draft_version,
            selections=[{"candidate_id": candidate.id,
                         "target": "key_week_focus"}],
            launch_id="g1-launch", session_scope_hash="c" * 64,
        )
        adopted = weekly_ai_adoption.adopt(
            session, runtime=runtime, profile_id=plan.profile_id,
            plan_id=plan.id, request_id=uuid.uuid4().hex,
            expected_draft_version=plan.current_draft_version,
            preview_token=preview["preview_token"], launch_id="g1-launch",
            session_scope_hash="c" * 64,
        )
        saved = weekly_plan_service.save_draft(
            session, profile_id=plan.profile_id, request_id=uuid.uuid4().hex,
            plan_id=plan.id, expected_draft_version=adopted["draft"]["version"],
            patch={"weekly_columns": {"key_week_focus": "手工保存后"}},
        )
        unrelated = weekly_plan_service.save_draft(
            session, profile_id=plan.profile_id, request_id=uuid.uuid4().hex,
            plan_id=plan.id, expected_draft_version=saved["draft"]["version"],
            patch={"theme": "无关保存"},
        )
        return {"plan_id": plan.id, "candidate_id": candidate.id,
                "adopted": adopted, "saved": saved, "unrelated": unrelated, "unsubmitted": unsubmitted}
    finally:
        session.close()

def test_real_adoption_manual_save_backup_and_restore(tmp_path):
    old = tmp_path / "old-data"
    db = old / "kindergarten.db"
    create_old_0007_fixture(db, old, align_default_prompts=True)
    source_data = tmp_path / "source-data"
    _copy_old_tree(old, source_data)
    source = LocalRuntime(source_data, credential_root=tmp_path / "source-cred")
    source.prepare()
    try:
        seeded = _seed_real_adoption(source)
        assert seeded["saved"]["draft"]["version"] == 4
        assert seeded["unrelated"]["draft"]["version"] == 5
        from tests.local.backup_fixture_support import database_fingerprint
        package = tmp_path / "adopted.kgmbackup"
        backup_snapshot.SnapshotService(
            source, app_version="g1-test", source_identity={"fixture": "adopted"}
        ).create(package, password=None, cancel=threading.Event())
        expected = database_fingerprint(source_data / "kindergarten.db",
                                        include_runtime_fields=True)
        source.dispose()
        (tmp_path / "scratch").mkdir(exist_ok=True)
        backup_validate.validate_database(
            source_data / "kindergarten.db", migrate_old=False,
            require_current=True, scratch_dir=tmp_path / "scratch",
        )
    finally:
        source.dispose()
    target_data = tmp_path / "target-data"
    target = LocalRuntime(target_data, credential_root=tmp_path / "target-cred")
    target.prepare()
    try:
        core = RestoreCore(target, app_version="g1-test")
        preview = core.preview(package, None, operation_id=uuid.uuid4().hex,
                               cancel=threading.Event())
        prepared = core.prepare(preview, cancel=threading.Event())
        installed = core.install(prepared, hooks=_Hooks(),
                                 cancel=threading.Event())
        assert installed.state == "installed_retired", installed
        assert core.reopen().state == "reopened"
        from tests.local.backup_fixture_support import database_fingerprint
        actual = database_fingerprint(target_data / "kindergarten.db",
                                      include_runtime_fields=True)
        assert actual == expected
        assert target.launch_id is None
        assert not getattr(target, "ai_executor", None)
        session = target.session()
        try:
            restored_plan = session.query(LocalWeeklyPlan).filter_by(
                id=seeded["adopted"]["weekly_plan_id"]).one()
            operation = weekly_ai_service.get_operation(
                session, profile_id=restored_plan.profile_id,
                plan_id=restored_plan.id,
                request_id=seeded["adopted"]["request_id"],
            )
            assert operation["status"] == "committed"
            with pytest.raises(LocalWeeklyAiPreviewExpired):
                weekly_ai_adoption.adopt(
                    session, runtime=target,
                    profile_id=restored_plan.profile_id,
                    plan_id=restored_plan.id,
                    request_id=uuid.uuid4().hex,
                    expected_draft_version=seeded["unrelated"]["draft"]["version"],
                    preview_token=seeded["unsubmitted"], launch_id="g1-launch",
                    session_scope_hash="c" * 64,
                )
        finally:
            session.close()
    finally:
        target.dispose()

def test_forged_weekly_ai_chain_is_rejected(tmp_path):
    old = tmp_path / "old-data"
    db = old / "kindergarten.db"
    create_old_0007_fixture(db, old, align_default_prompts=True)
    source_data = tmp_path / "source-data"
    _copy_old_tree(old, source_data)
    source = LocalRuntime(source_data, credential_root=tmp_path / "source-cred")
    source.prepare()
    try:
        _seed_real_adoption(source)
    finally:
        source.dispose()
    (tmp_path / "scratch").mkdir(exist_ok=True)
    original = source_data / "kindergarten.db"
    for label, sql in (
        ("candidate", "UPDATE local_ai_candidates SET raw_candidate_json=? "
                      "WHERE source_kind='weekly_plan'"),
        ("event", "UPDATE local_weekly_plan_ai_adoption SET before_hash=? "),
        ("operation", "UPDATE local_ai_operations SET result_json=? "
                      "WHERE operation_kind='weekly_ai_adopt'"),
        ("payload", "UPDATE local_ai_inputs SET payload_json=? "
                    "WHERE source_kind='weekly_plan'"),
        ("input_schema", "UPDATE local_ai_inputs SET input_schema_version=? "
                         "WHERE source_kind='weekly_plan'"),
        ("candidate_schema", "UPDATE local_ai_candidates SET schema_version=? "
                             "WHERE source_kind='weekly_plan'"),
        ("candidate_contract", "UPDATE local_ai_candidates SET contract_version=? "
                               "WHERE source_kind='weekly_plan'"),
    ):
        bad = tmp_path / f"bad-{label}.db"
        shutil.copy2(original, bad)
        con = sqlite3.connect(str(bad))
        try:
            if label == "candidate":
                con.execute(sql, (json.dumps({"text": "forged"}),))
            elif label == "payload":
                con.execute(sql, (json.dumps({"text": "forged"}),))
            elif label in ("input_schema", "candidate_schema", "candidate_contract"):
                con.execute(sql, (99,))
            elif label == "event":
                con.execute(sql, ("0" * 64,))
            else:
                con.execute(sql, ('{"status":"forged"}',))
            con.commit()
        finally:
            con.close()
        with pytest.raises(backup_validate.BackupValidationError):
            backup_validate.validate_database(
                bad, migrate_old=False, require_current=True,
                scratch_dir=tmp_path / "scratch",
            )
def test_0008_encrypted_snapshot_restores_complete_archive(tmp_path):
    old = tmp_path / "old-data"
    db = old / "kindergarten.db"
    create_old_0007_fixture(db, old)
    source_data = tmp_path / "source-data"
    _copy_old_tree(old, source_data)
    source = LocalRuntime(source_data, credential_root=tmp_path / "source-cred")
    source.prepare()
    package = tmp_path / "current-encrypted.kgmbackup"
    try:
        backup_snapshot.SnapshotService(
            source, app_version="g1-test", source_identity={"fixture": "encrypted"}
        ).create(package, password="g1-password", cancel=threading.Event())
        before = migration_rows(source_data / "kindergarten.db")
    finally:
        source.dispose()
    target_data = tmp_path / "target-data"
    target = LocalRuntime(target_data, credential_root=tmp_path / "target-cred")
    target.prepare()
    try:
        core = RestoreCore(target, app_version="g1-test")
        preview = core.preview(package, "g1-password",
                               operation_id=uuid.uuid4().hex,
                               cancel=threading.Event())
        prepared = core.prepare(preview, cancel=threading.Event())
        result = core.install(prepared, hooks=_Hooks(), cancel=threading.Event())
        assert result.state == "installed_retired", result
        assert core.reopen().state == "reopened"
        after = migration_rows(target_data / "kindergarten.db")
        _old_rows_preserved(before, after)
    finally:
        target.dispose()

def test_forged_successor_provenance_is_rejected(tmp_path):
    old = tmp_path / "old-data"
    db = old / "kindergarten.db"
    create_old_0007_fixture(db, old, align_default_prompts=True)
    source_data = tmp_path / "source-data"
    _copy_old_tree(old, source_data)
    source = LocalRuntime(source_data, credential_root=tmp_path / "source-cred")
    source.prepare()
    try:
        _seed_real_adoption(source)
    finally:
        source.dispose()
    bad = tmp_path / "forged-provenance.db"
    shutil.copy2(source_data / "kindergarten.db", bad)
    con = sqlite3.connect(str(bad))
    try:
        row = con.execute(
            "SELECT id, content_json FROM local_weekly_plan_contents "
            "ORDER BY version DESC LIMIT 1"
        ).fetchone()
        content = json.loads(row[1])
        content["ai_provenance"]["key_week_focus"]["candidate_hash"] = "0" * 64
        new_hash = weekly_plan_content.content_hash(content)
        con.execute(
            "UPDATE local_weekly_plan_contents SET content_json=?, content_hash=? "
            "WHERE id=?",
            (json.dumps(content, ensure_ascii=False, sort_keys=True,
                        separators=(",", ":")), new_hash, row[0]),
        )
        con.commit()
    finally:
        con.close()
    (tmp_path / "scratch").mkdir(exist_ok=True)
    with pytest.raises(backup_validate.BackupValidationError):
        backup_validate.validate_database(
            bad, migrate_old=False, require_current=True,
            scratch_dir=tmp_path / "scratch",
        )
from app.local.errors import LocalWeeklyAiPreviewExpired

def _seed_materials_adoption(runtime: LocalRuntime, *, contract_version: int = 2) -> dict:
    from app.local import daily_plan_service
    from app.local.models import LocalDailyPlan
    session = runtime.session()
    try:
        daily = session.query(LocalDailyPlan).one()
        current = daily_plan_service.get_plan(session, plan_id=daily.id)
        adopted = dict(current["content"]["adopted_content"])
        adopted["post_group_games"] = [{
            "context_kind": "area", "area": "积木区",
            "games": [{"name": "搭小桥"}], "objectives": "合作",
            "guidance": "协商", "support_strategy": "提供材料",
        }]
        daily_plan_service.save(
            session, plan_id=daily.id,
            expected_content_version=current["content"]["version"],
            adopted_content=adopted,
        )
        plan = session.query(LocalWeeklyPlan).one()
        snapshot = weekly_plan_service._live_snapshot(session, plan)
        focus = next(c for c in weekly_plan_content.build_source_candidates(snapshot)
                     if c["section"] == "post_group_games")
        selector = {key: focus[key] for key in (
            "source_kind", "daily_plan_id", "content_id", "content_version",
            "content_hash", "section", "group_id", "game_id")}
        weekly_plan_service.save_draft(
            session, profile_id=plan.profile_id, request_id=uuid.uuid4().hex,
            plan_id=plan.id, expected_draft_version=plan.current_draft_version,
            patch={"focus_area": selector},
        )
        result, _ = weekly_ai_service.create_weekly_tasks(
            session, runtime=None, profile_id=plan.profile_id, plan_id=plan.id,
            request_id=uuid.uuid4().hex,
            expected_draft_version=plan.current_draft_version,
            operation_kind=weekly_ai_service.MATERIALS,
            task_specs=[weekly_ai_service.WeeklyTaskSpec(
                "weekly_materials_generate", "materials")],
        )
        task = session.get(LocalAITask, result["tasks"][0]["task_id"])
        input_row = session.get(LocalAIInput, task.input_id)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        execution = LocalAIExecution(
            id=uuid.uuid4().hex, task_id=task.id, source_kind="weekly_plan",
            source_id=plan.id, observation_id=None, daily_plan_id=None,
            weekly_plan_id=plan.id, input_id=input_row.id,
            task_type=task.task_type, generation=1,
            launch_id=str(uuid.uuid4()), permit_id=str(uuid.uuid4()),
            config_version=1, profile_id=plan.profile_id,
            personal_revision=1, contract_version=contract_version, default_revision=1,
            state="succeeded", runtime_meta_json={}, started_at=now,
            created_at=now, ended_at=now,
        )
        session.add(execution)
        session.flush()
        manifest = dict(input_row.dependencies_json or {})["_server_manifest"]
        raw = weekly_ai_contracts.parse_materials_candidate(
            b'{"items":[]}', server_manifest=manifest)
        candidate = LocalAICandidate(
            id=uuid.uuid4().hex, profile_id=plan.profile_id,
            execution_id=execution.id, task_id=task.id,
            source_kind="weekly_plan", source_id=plan.id,
            observation_id=None, daily_plan_id=None, weekly_plan_id=plan.id,
            input_id=input_row.id, task_type=task.task_type,
            contract_version=contract_version, schema_version=1, raw_candidate_json=raw,
            candidate_hash=weekly_ai_contracts.candidate_hash(raw),
            created_at=now,
        )
        session.add(candidate)
        task.current_execution_id = execution.id
        task.generation = 1
        task.status = "succeeded"
        session.commit()
        preview = weekly_ai_adoption.preview_adoption(
            session, runtime=runtime, profile_id=plan.profile_id,
            plan_id=plan.id, expected_draft_version=plan.current_draft_version,
            selections=[{"candidate_id": candidate.id, "target": "materials"}],
            launch_id="g1-launch", session_scope_hash="c" * 64,
        )
        adopted = weekly_ai_adoption.adopt(
            session, runtime=runtime, profile_id=plan.profile_id,
            plan_id=plan.id, request_id=uuid.uuid4().hex,
            expected_draft_version=plan.current_draft_version,
            preview_token=preview["preview_token"], launch_id="g1-launch",
            session_scope_hash="c" * 64,
        )
        cleared = weekly_plan_service.save_draft(
            session, profile_id=plan.profile_id, request_id=uuid.uuid4().hex,
            plan_id=plan.id, expected_draft_version=adopted["draft"]["version"],
            patch={"materials": None},
        )
        return {"plan_id": plan.id, "adopted": adopted, "cleared": cleared}
    finally:
        session.close()

def test_real_materials_adoption_clear_confirmation_backup_restore(tmp_path):
    old = tmp_path / "old-data"
    db = old / "kindergarten.db"
    create_old_0007_fixture(db, old, align_default_prompts=True)
    source_data = tmp_path / "source-data"
    _copy_old_tree(old, source_data)
    source = LocalRuntime(source_data, credential_root=tmp_path / "source-cred")
    source.prepare()
    try:
        seeded = _seed_materials_adoption(source)
        session = source.session()
        try:
            plan = session.query(LocalWeeklyPlan).one()
            preview = weekly_plan_service.confirmation_preview(
                session, runtime=source, profile_id=plan.profile_id,
                launch_id="g1-launch", session_scope_hash="c" * 64,
                plan_id=plan.id,
                expected_draft_version=seeded["cleared"]["draft"]["version"],
            )
            weekly_plan_service.confirm(
                session, runtime=source, profile_id=plan.profile_id,
                launch_id="g1-launch", session_scope_hash="c" * 64,
                request_id=uuid.uuid4().hex, plan_id=plan.id,
                expected_draft_version=seeded["cleared"]["draft"]["version"],
                context_token=preview["preview_token"], ack_missing=True,
                ack_stale=True, note="材料清除确认",
            )
        finally:
            session.close()
        from tests.local.backup_fixture_support import database_fingerprint
        expected = database_fingerprint(source_data / "kindergarten.db",
                                        include_runtime_fields=True)
        package = tmp_path / "materials.kgmbackup"
        backup_snapshot.SnapshotService(
            source, app_version="g1-test", source_identity={"fixture": "materials"}
        ).create(package, password=None, cancel=threading.Event())
        source.dispose()
    finally:
        source.dispose()
    target_data = tmp_path / "target-data"
    target = LocalRuntime(target_data, credential_root=tmp_path / "target-cred")
    target.prepare()
    try:
        core = RestoreCore(target, app_version="g1-test")
        preview = core.preview(package, None, operation_id=uuid.uuid4().hex,
                               cancel=threading.Event())
        prepared = core.prepare(preview, cancel=threading.Event())
        installed = core.install(prepared, hooks=_Hooks(),
                                 cancel=threading.Event())
        assert installed.state == "installed_retired", installed
        assert core.reopen().state == "reopened"
        actual = database_fingerprint(target_data / "kindergarten.db",
                                      include_runtime_fields=True)
        assert actual == expected
        assert target.launch_id is None
    finally:
        target.dispose()

def _seed_games_adoption(runtime: LocalRuntime, *, contract_version: int = 2) -> dict:
    session = runtime.session()
    try:
        plan = session.query(LocalWeeklyPlan).one()
        result, _ = weekly_ai_service.create_weekly_tasks(
            session, runtime=None, profile_id=plan.profile_id,
            plan_id=plan.id, request_id=uuid.uuid4().hex,
            expected_draft_version=plan.current_draft_version,
            operation_kind=weekly_ai_service.GAMES,
            task_specs=[weekly_ai_service.WeeklyTaskSpec(
                "weekly_games_select", "games")],
        )
        task = session.get(LocalAITask, result["tasks"][0]["task_id"])
        input_row = session.get(LocalAIInput, task.input_id)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        execution = LocalAIExecution(
            id=uuid.uuid4().hex, task_id=task.id, source_kind="weekly_plan",
            source_id=plan.id, observation_id=None, daily_plan_id=None,
            weekly_plan_id=plan.id, input_id=input_row.id,
            task_type=task.task_type, generation=1,
            launch_id=str(uuid.uuid4()), permit_id=str(uuid.uuid4()),
            config_version=1, profile_id=plan.profile_id,
            personal_revision=1, contract_version=contract_version, default_revision=1,
            state="succeeded", runtime_meta_json={}, started_at=now,
            created_at=now, ended_at=now,
        )
        session.add(execution)
        session.flush()
        manifest = dict(input_row.dependencies_json or {})["_server_manifest"]
        text = (
            '{"outdoor_game_slots":{"collective_1":{"kind":"ai_supplement",'
            '"name":"补足游戏","shared_objectives":"目标","guidance_points":"指导",'
            '"focus_guidance":"关注","basis_handles":[]},"collective_2":null,'
            '"free_choice_1":null},"focus_area":null}'
        )
        raw = weekly_ai_contracts.parse_games_candidate(
            text.encode(), server_manifest=manifest)
        candidate = LocalAICandidate(
            id=uuid.uuid4().hex, profile_id=plan.profile_id,
            execution_id=execution.id, task_id=task.id,
            source_kind="weekly_plan", source_id=plan.id,
            observation_id=None, daily_plan_id=None, weekly_plan_id=plan.id,
            input_id=input_row.id, task_type=task.task_type,
            contract_version=contract_version, schema_version=1, raw_candidate_json=raw,
            candidate_hash=weekly_ai_contracts.candidate_hash(raw),
            created_at=now,
        )
        session.add(candidate)
        task.current_execution_id = execution.id
        task.generation = 1
        task.status = "succeeded"
        session.commit()
        preview = weekly_ai_adoption.preview_adoption(
            session, runtime=runtime, profile_id=plan.profile_id,
            plan_id=plan.id, expected_draft_version=plan.current_draft_version,
            selections=[{"candidate_id": candidate.id, "target": "games"}],
            launch_id="g1-launch", session_scope_hash="c" * 64,
        )
        adopted = weekly_ai_adoption.adopt(
            session, runtime=runtime, profile_id=plan.profile_id,
            plan_id=plan.id, request_id=uuid.uuid4().hex,
            expected_draft_version=plan.current_draft_version,
            preview_token=preview["preview_token"], launch_id="g1-launch",
            session_scope_hash="c" * 64,
        )
        saved = weekly_plan_service.save_draft(
            session, profile_id=plan.profile_id, request_id=uuid.uuid4().hex,
            plan_id=plan.id, expected_draft_version=adopted["draft"]["version"],
            patch={"theme": "游戏采用后手改"},
        )
        return {"adopted": adopted, "saved": saved}
    finally:
        session.close()

def test_real_games_adoption_hand_save_backup_restore(tmp_path):
    old = tmp_path / "old-data"
    db = old / "kindergarten.db"
    create_old_0007_fixture(db, old, align_default_prompts=True)
    source_data = tmp_path / "source-data"
    _copy_old_tree(old, source_data)
    source = LocalRuntime(source_data, credential_root=tmp_path / "source-cred")
    source.prepare()
    try:
        seeded = _seed_games_adoption(source)
        assert seeded["saved"]["draft"]["version"] == 4
        from tests.local.backup_fixture_support import database_fingerprint
        expected = database_fingerprint(source_data / "kindergarten.db",
                                        include_runtime_fields=True)
        package = tmp_path / "games.kgmbackup"
        backup_snapshot.SnapshotService(
            source, app_version="g1-test", source_identity={"fixture": "games"}
        ).create(package, password=None, cancel=threading.Event())
        source.dispose()
    finally:
        source.dispose()
    target_data = tmp_path / "target-data"
    target = LocalRuntime(target_data, credential_root=tmp_path / "target-cred")
    target.prepare()
    try:
        core = RestoreCore(target, app_version="g1-test")
        preview = core.preview(package, None, operation_id=uuid.uuid4().hex,
                               cancel=threading.Event())
        prepared = core.prepare(preview, cancel=threading.Event())
        result = core.install(prepared, hooks=_Hooks(), cancel=threading.Event())
        assert core.reopen().state == "reopened"
        from tests.local.backup_fixture_support import database_fingerprint
        assert database_fingerprint(target_data / "kindergarten.db",
                                    include_runtime_fields=True) == expected
    finally:
        target.dispose()

def test_forged_materials_provenance_origin_is_rejected(tmp_path):
    old = tmp_path / "old-data"
    db = old / "kindergarten.db"
    create_old_0007_fixture(db, old, align_default_prompts=True)
    source_data = tmp_path / "source-data"
    _copy_old_tree(old, source_data)
    source = LocalRuntime(source_data, credential_root=tmp_path / "source-cred")
    source.prepare()
    try:
        _seed_materials_adoption(source)
    finally:
        source.dispose()
    bad = tmp_path / "forged-materials.db"
    shutil.copy2(source_data / "kindergarten.db", bad)
    con = sqlite3.connect(str(bad))
    try:
        row = con.execute(
            "SELECT id, content_json FROM local_weekly_plan_contents "
            "ORDER BY version DESC LIMIT 1"
        ).fetchone()
        content = json.loads(row[1])
        content["materials_provenance"]["basis"]["grade"] = "large"
        new_hash = weekly_plan_content.content_hash(content)
        con.execute(
            "UPDATE local_weekly_plan_contents SET content_json=?, content_hash=? "
            "WHERE id=?",
            (json.dumps(content, ensure_ascii=False, sort_keys=True,
                        separators=(",", ":")), new_hash, row[0]),
        )
        con.commit()
    finally:
        con.close()
    (tmp_path / "scratch").mkdir(exist_ok=True)
    with pytest.raises(backup_validate.BackupValidationError):
        backup_validate.validate_database(
            bad, migrate_old=False, require_current=True,
            scratch_dir=tmp_path / "scratch",
        )
def test_forged_origin_metadata_swap_is_rejected(tmp_path):
    old = tmp_path / "old-data"
    db = old / "kindergarten.db"
    create_old_0007_fixture(db, old, align_default_prompts=True)
    source_data = tmp_path / "source-data"
    _copy_old_tree(old, source_data)
    source = LocalRuntime(source_data, credential_root=tmp_path / "source-cred")
    source.prepare()
    try:
        _seed_real_adoption(source)
    finally:
        source.dispose()
    bad = tmp_path / "forged-metadata-swap.db"
    shutil.copy2(source_data / "kindergarten.db", bad)
    con = sqlite3.connect(str(bad))
    try:
        row = con.execute(
            "SELECT id, content_json FROM local_weekly_plan_contents "
            "WHERE schema_version=2 ORDER BY version LIMIT 1"
        ).fetchone()
        content = json.loads(row[1])
        other = (uuid.uuid4().hex, uuid.uuid4().hex)
        content["ai_provenance"]["key_week_focus"]["input_id"] = other[0]
        content["ai_provenance"]["key_week_focus"]["execution_id"] = other[1]
        new_hash = weekly_plan_content.content_hash(content)
        con.execute(
            "UPDATE local_weekly_plan_contents SET content_json=?, content_hash=? "
            "WHERE id=?", (json.dumps(content, ensure_ascii=False, sort_keys=True,
                                      separators=(",", ":")), new_hash, row[0]))
        con.commit()
    finally:
        con.close()
    (tmp_path / "scratch").mkdir(exist_ok=True)
    with pytest.raises(backup_validate.BackupValidationError):
        backup_validate.validate_database(bad, migrate_old=False,
                                          require_current=True,
                                          scratch_dir=tmp_path / "scratch")

def test_forged_origin_adopted_value_is_rejected(tmp_path):
    old = tmp_path / "old-data"
    db = old / "kindergarten.db"
    create_old_0007_fixture(db, old, align_default_prompts=True)
    source_data = tmp_path / "source-data"
    _copy_old_tree(old, source_data)
    source = LocalRuntime(source_data, credential_root=tmp_path / "source-cred")
    source.prepare()
    try:
        _seed_real_adoption(source)
    finally:
        source.dispose()
    bad = tmp_path / "forged-origin-value.db"
    shutil.copy2(source_data / "kindergarten.db", bad)
    con = sqlite3.connect(str(bad))
    try:
        row = con.execute(
            "SELECT id, content_json FROM local_weekly_plan_contents "
            "WHERE schema_version=2 ORDER BY version LIMIT 1"
        ).fetchone()
        content = json.loads(row[1])
        provenance = content["ai_provenance"]["key_week_focus"]
        provenance["adopted_value"]["text"] = "篡改原点"
        content["weekly_columns"]["key_week_focus"] = "篡改原点"
        provenance["adopted_value_hash"] = weekly_plan_content.content_hash(
            provenance["adopted_value"])
        new_hash = weekly_plan_content.content_hash(content)
        con.execute(
            "UPDATE local_weekly_plan_contents SET content_json=?, content_hash=? "
            "WHERE id=?", (json.dumps(content, ensure_ascii=False, sort_keys=True,
                                      separators=(",", ":")), new_hash, row[0]))
        con.execute(
            "UPDATE local_weekly_plan_ai_adoption SET after_hash=? "
            "WHERE draft_id=? AND target_key='key_week_focus'",
            (weekly_ai_inputs.target_hash(content, "key_week_focus"), row[0]))
        result = con.execute(
            "SELECT result_json FROM local_ai_operations "
            "WHERE operation_kind='weekly_ai_adopt' LIMIT 1").fetchone()
        operation = json.loads(result[0])
        operation["draft"]["content_hash"] = new_hash
        con.execute("UPDATE local_ai_operations SET result_json=? "
                    "WHERE operation_kind='weekly_ai_adopt'",
                    (json.dumps(operation, ensure_ascii=False),))
        con.commit()
    finally:
        con.close()
    (tmp_path / "scratch").mkdir(exist_ok=True)
    (tmp_path / "scratch").mkdir(exist_ok=True)
    with pytest.raises(backup_validate.BackupValidationError):
        backup_validate.validate_database(bad, migrate_old=False,
                                          require_current=True,
                                          scratch_dir=tmp_path / "scratch")
from app.local import weekly_ai_inputs
def _pending_weekly_claim(runtime: LocalRuntime, dispatched: bool):
    runtime.launch_id = uuid.uuid4().hex
    session = runtime.session()
    try:
        plan = session.query(LocalWeeklyPlan).one()
        from app.local import ai_config_service
        from app.local.models import LocalAIState
        from app.local import ai_task_service
        state = session.query(LocalAIState).filter_by(
            profile_id=plan.profile_id).one()
        ai_config_service.patch_config(
            session, expected_ai_config_version=int(state.current_config_version or 0),
            base_url="https://api.example.com/v1", model="test-model",
            secret="synthetic-secret", secret_provided=True,
            request_id=uuid.uuid4().hex,
            credential_root=runtime.credential_root,
        )
        session.commit()
        result, _ = weekly_ai_service.create_weekly_tasks(
            session, runtime=runtime, profile_id=plan.profile_id,
            plan_id=plan.id, request_id=uuid.uuid4().hex,
            expected_draft_version=plan.current_draft_version,
            operation_kind=weekly_ai_service.COLUMNS,
            task_specs=[weekly_ai_service.WeeklyTaskSpec(
                "weekly_key_week_focus", "key_week_focus")],
        )
        claim = ai_task_service.claim_next(
            runtime, now=ai_task_service._now(), started_ticks=1)
        assert claim is not None
        if dispatched:
            assert ai_task_service.commit_dispatch_mark(
                session, claim, ai_task_service._now())
        task_id = claim.task_id
        return claim, task_id
    finally:
        session.close()

def test_restore_rejects_old_weekly_claim_and_does_not_dispatch(tmp_path):
    for dispatched in (False, True):
        label = "sent" if dispatched else "unsent"
        old = tmp_path / f"old-{label}"
        db = old / "kindergarten.db"
        create_old_0007_fixture(db, old, align_default_prompts=True)
        source_data = tmp_path / f"source-{label}"
        _copy_old_tree(old, source_data)
        source = LocalRuntime(source_data, credential_root=tmp_path / f"cred-{label}")
        source.prepare()
        try:
            claim, task_id = _pending_weekly_claim(source, dispatched)
            source.dispose()
            package = tmp_path / f"pending-{label}.kgmbackup"
            _write_old_package(source_data / "kindergarten.db", source_data,
                               package, None)
        finally:
            source.dispose()
        target_data = tmp_path / f"target-{label}"
        target = LocalRuntime(target_data, credential_root=tmp_path / f"tcred-{label}")
        target.prepare()
        try:
            core = RestoreCore(target, app_version="g1-test")
            preview = core.preview(package, None, operation_id=uuid.uuid4().hex,
                                   cancel=threading.Event())
            prepared = core.prepare(preview, cancel=threading.Event())
            core.install(prepared, hooks=_Hooks(), cancel=threading.Event())
            assert core.reopen().state == "reopened"
            session = target.session()
            try:
                before = session.query(LocalAICandidate).count()
                counts = ai_task_service.recover_on_start(
                    session, now=ai_task_service._now())
                task = session.get(LocalAITask, task_id)
                assert task.status in ("paused", "outcome_unknown")
                assert task.status == ("outcome_unknown" if dispatched else "paused")
                assert ai_task_service.commit_dispatch_mark(
                    session, claim, ai_task_service._now()) is False
                assert ai_task_service.finalize_success(
                    session, claim,
                    {"kind": "success", "candidate_text": '{"text":"旧许可"}'},
                    ai_task_service._now()) is False
                assert session.query(LocalAICandidate).count() == before
                assert target.launch_id is None
                assert not getattr(target, "ai_executor", None)
            finally:
                session.close()
        finally:
            target.dispose()
from app.local import ai_task_service

def test_contract_predicate_versions_and_synthetic_rejections(tmp_path):
    from app.local import weekly_ai_contracts as contracts
    for task in ("weekly_games_select", "weekly_materials_generate"):
        assert contracts.supports_prompt_contract(task, 1) is True
        assert contracts.supports_prompt_contract(task, 2) is True
        assert contracts.supports_prompt_contract(task, 3) is False
        assert contracts.supports_prompt_contract(task, True) is False
        assert contracts.supports_prompt_contract(task, "2") is False
    for task in (
        "weekly_key_week_focus", "weekly_environment_setup",
        "weekly_habit_culture", "weekly_home_cooperation",
    ):
        assert contracts.supports_prompt_contract(task, 1) is True
        assert contracts.supports_prompt_contract(task, 2) is False
    assert contracts.supports_prompt_contract("unknown", 1) is False
    old = tmp_path / "old-data"
    db = old / "kindergarten.db"
    create_old_0007_fixture(db, old, align_default_prompts=True)
    source_data = tmp_path / "source-data"
    _copy_old_tree(old, source_data)
    source = LocalRuntime(source_data, credential_root=tmp_path / "source-cred")
    source.prepare()
    try:
        _seed_real_adoption(source)
    finally:
        source.dispose()
    (tmp_path / "scratch").mkdir(exist_ok=True)
    for label, task_type, version in (
        ("columns2", "weekly_key_week_focus", 2),
        ("columns99", "weekly_key_week_focus", 99),
    ):
        bad = tmp_path / f"bad-{label}.db"
        shutil.copy2(source_data / "kindergarten.db", bad)
        con = sqlite3.connect(str(bad))
        try:
            con.execute(
                "UPDATE local_ai_candidates SET contract_version=? "
                "WHERE task_type=?", (version, task_type))
            con.commit()
        finally:
            con.close()
        with pytest.raises(backup_validate.BackupValidationError):
            backup_validate.validate_database(
                bad, migrate_old=False, require_current=True,
                scratch_dir=tmp_path / "scratch")
