"""B2 restore core tests over real SQLite, WAL and managed images.

The heavy business fixture is reused read-only from the independent fixture
session; these tests add only restore-specific source roots and assertions.
"""

from __future__ import annotations

import json
import hashlib
import os
import subprocess
import sys
import threading
import uuid
from pathlib import Path
from unittest import mock

import pytest
from sqlalchemy import select, text

from app.local import (
    ai_config_service,
    backup_fs,
    config_tokens,
    observation_service,
    restore_group,
    restore_journal,
)
from app.local.backup_snapshot import SnapshotService
from app.local.errors import LocalDatabaseStateError, LocalValidationError
from app.local.models import LocalProfile
from app.local.restore_fs import atomic_write_json, operation_paths
from app.local.restore_recovery import resolve_startup_restore
from app.local.restore_service import RestoreCore
from app.local.restore_types import MaintenanceHooks, RestoreFailure
from app.local.runtime import LocalRuntime
from tests.local.backup_fixture_support import (
    database_fingerprint,
    resource_fingerprint,
    seed_existing_runtime,
    validate_fixture,
)
from tests.local.support import LocalTestCase


class _Hooks(MaintenanceHooks):
    def wait_host_idle(self, cancel) -> bool:
        return not cancel.is_set()

    def stop_transport(self) -> bool:
        return True


class RestoreCoreCase(LocalTestCase):
    def _source(self):
        source_dir = self.tmp_root / "source-data"
        source = self.make_runtime(data_dir=source_dir)
        evidence = seed_existing_runtime(source)
        validate_fixture(source, evidence)
        return source, evidence

    def _package(self, runtime, name: str) -> Path:
        target = self.tmp_root / f"{name}.kgmbackup"
        service = SnapshotService(
            runtime,
            app_version="restore-test",
            source_identity={"app_version": "restore-test"},
        )
        service.create(
            target,
            password=None,
            cancel=threading.Event(),
        )
        return target

    def test_preview_prepare_install_reopen_preserves_business(self):
        source, evidence = self._source()
        package = self._package(source, "full")
        target = self.make_runtime(data_dir=self.tmp_root / "target-data")
        old_session = target.session()
        assert old_session.execute(text("SELECT 1")).scalar_one() == 1
        core = RestoreCore(target, app_version="restore-test")
        operation_id = uuid.uuid4().hex
        preview = core.preview(
            package,
            None,
            operation_id=operation_id,
            cancel=threading.Event(),
        )
        assert preview.profile_present is True
        assert preview.profile_name
        prepared = core.prepare(preview, cancel=threading.Event())
        assert prepared.resource_count == len(evidence.resources["files"])
        result = core.install(
            prepared,
            hooks=_Hooks(),
            cancel=threading.Event(),
        )
        assert result.state == "installed_retired", result
        assert result.old_group_preserved is True
        assert Path(result.protection_display_path).is_file()
        with pytest.raises(Exception):
            old_session.execute(text("SELECT 1"))
        reopened = core.reopen()
        assert reopened.state == "reopened", reopened
        assert target.current_revision is not None
        session = target.session()
        try:
            config = ai_config_service.get_config(
                session, credential_root=target.credential_root
            )
            assert config.configured is True
            assert config.ready is True
        finally:
            session.close()
        validate_fixture(target, evidence)
        assert database_fingerprint(target.db_path) == database_fingerprint(
            source.db_path
        )
        assert resource_fingerprint(target.data_dir) == resource_fingerprint(
            source.data_dir
        )

    def test_empty_target_and_empty_protection_package(self):
        empty = self.make_runtime(data_dir=self.tmp_root / "empty-source")
        empty_package = self._package(empty, "empty-protection")
        source, _ = self._source()
        package = self._package(source, "nonempty")

        empty_preview = RestoreCore(empty, app_version="restore-test").preview(
            empty_package,
            None,
            operation_id=uuid.uuid4().hex,
            cancel=threading.Event(),
        )
        assert empty_preview.profile_present is False

        target = self.make_runtime(data_dir=self.tmp_root / "empty-target")
        core = RestoreCore(target, app_version="restore-test")
        preview = core.preview(
            package,
            None,
            operation_id=uuid.uuid4().hex,
            cancel=threading.Event(),
        )
        assert preview.profile_present is True
        prepared = core.prepare(preview, cancel=threading.Event())
        result = core.install(prepared, hooks=_Hooks(), cancel=threading.Event())
        assert result.state == "installed_retired", result
        assert Path(result.protection_display_path).is_file()
        # The automatic protection of the empty target is itself a valid
        # ordinary package and can be restored through the same entry.
        protection_path = Path(result.protection_display_path)
        SnapshotService(target, app_version="restore-test", source_identity={}).verify(
            protection_path,
            password=None,
            cancel=threading.Event(),
        )
        assert core.reopen().state == "reopened"
        assert target.session().execute(
            text("SELECT COUNT(*) FROM local_profile")
        ).scalar_one() == 1

        again = self.make_runtime(data_dir=self.tmp_root / "protection-target")
        core_again = RestoreCore(again, app_version="restore-test")
        protection_preview = core_again.preview(
            protection_path,
            None,
            operation_id=uuid.uuid4().hex,
            cancel=threading.Event(),
        )
        assert protection_preview.profile_present is False
        protection_prepared = core_again.prepare(
            protection_preview, cancel=threading.Event()
        )
        protection_result = core_again.install(
            protection_prepared, hooks=_Hooks(), cancel=threading.Event()
        )
        assert protection_result.state == "installed_retired"
        assert core_again.reopen().state == "reopened"
        assert again.session().execute(
            text("SELECT COUNT(*) FROM local_profile")
        ).scalar_one() == 0

    def test_retired_engine_cannot_reconnect_after_close(self):
        runtime = self.make_runtime(data_dir=self.tmp_root / "retire-data")
        old_session = runtime.session()
        assert old_session.execute(text("SELECT 1")).scalar_one() == 1
        runtime.close_engine_keep_lock()
        with pytest.raises(Exception):
            old_session.execute(text("SELECT 1"))
        runtime.reopen_after_restore()
        assert runtime.session().execute(text("SELECT 1")).scalar_one() == 1

    def test_retired_engine_guard_runs_before_sqlite_creates_file(self):
        runtime = self.make_runtime(data_dir=self.tmp_root / "retire-gap")
        old_session = runtime.session()
        runtime.close_engine_keep_lock()
        runtime.db_path.unlink()
        with pytest.raises(Exception):
            old_session.execute(text("SELECT 1"))
        assert runtime.db_path.exists() is False

    def test_partial_old_move_rolls_back_on_startup_without_mixing(self):
        source, _ = self._source()
        package = self._package(source, "partial")
        data_dir = self.tmp_root / "partial-target"
        target = self.make_runtime(data_dir=data_dir)
        core = RestoreCore(target, app_version="restore-test")
        operation_id = uuid.uuid4().hex
        preview = core.preview(
            package,
            None,
            operation_id=operation_id,
            cancel=threading.Event(),
        )
        prepared = core.prepare(preview, cancel=threading.Event())
        record = core._prepared[operation_id]  # test-only introspection
        paths = record.paths
        target.close_engine_keep_lock()
        old_group = restore_group.capture_old_group(paths)
        journal = restore_journal.new_journal(
            operation_id=operation_id,
            package={"sha256": prepared.package_sha256},
        )
        journal = restore_journal.set_phase(
            paths, journal, "switching", old=old_group, new=record.new_group
        )
        for name in restore_group.DB_COMPONENTS:
            restore_group.move_live_component_to_old(paths, name)
        journal = restore_journal.write_journal(paths, journal)

        notice = resolve_startup_restore(target)
        assert notice is not None
        assert notice["state"] == "rolled_back"
        target.reopen_after_restore()
        assert target.session().execute(
            text("SELECT COUNT(*) FROM local_profile")
        ).scalar_one() == 0
        assert not restore_group.live_assets_path(paths).exists()

    def test_wrong_password_retries_and_same_operation_is_idempotent(self):
        source, _ = self._source()
        package = self.tmp_root / "secret.kgmbackup"
        SnapshotService(
            source,
            app_version="restore-test",
            source_identity={"app_version": "restore-test"},
        ).create(
            package,
            password="correct horse",
            cancel=threading.Event(),
        )
        target = self.make_runtime(data_dir=self.tmp_root / "secret-target")
        core = RestoreCore(target, app_version="restore-test")
        operation_id = uuid.uuid4().hex
        with pytest.raises(RestoreFailure) as wrong:
            core.preview(
                package,
                "wrong",
                operation_id=operation_id,
                cancel=threading.Event(),
            )
        assert wrong.value.code == "WRONG_PASSWORD"
        assert wrong.value.retryable is True
        first = core.preview(
            package,
            "correct horse",
            operation_id=operation_id,
            cancel=threading.Event(),
        )
        second = core.preview(
            package,
            "correct horse",
            operation_id=operation_id,
            cancel=threading.Event(),
        )
        assert second.preview_id == first.preview_id
        assert second.package_sha256 == first.package_sha256

    def test_cancel_before_first_live_change_keeps_old_profile(self):
        source, _ = self._source()
        package = self._package(source, "cancel")
        target = self.make_runtime(data_dir=self.tmp_root / "cancel-target")
        core = RestoreCore(target, app_version="restore-test")
        preview = core.preview(
            package,
            None,
            operation_id=uuid.uuid4().hex,
            cancel=threading.Event(),
        )
        prepared = core.prepare(preview, cancel=threading.Event())
        cancel = threading.Event()
        cancel.set()
        result = core.install(prepared, hooks=_Hooks(), cancel=cancel)
        assert result.state == "canceled", result
        assert target.session().execute(
            text("SELECT COUNT(*) FROM local_profile")
        ).scalar_one() == 0

    def test_protection_failure_does_not_switch(self):
        source, _ = self._source()
        package = self._package(source, "protection-fail")
        target = self.make_runtime(data_dir=self.tmp_root / "protection-fail-target")
        core = RestoreCore(target, app_version="restore-test")
        operation_id = uuid.uuid4().hex
        preview = core.preview(
            package,
            None,
            operation_id=operation_id,
            cancel=threading.Event(),
        )
        prepared = core.prepare(preview, cancel=threading.Event())
        paths = operation_paths(target, operation_id, create=False)
        paths.protection_path.write_bytes(b"occupied")
        result = core.install(prepared, hooks=_Hooks(), cancel=threading.Event())
        assert result.state == "failed_keep_old", result
        assert target.session().execute(
            text("SELECT COUNT(*) FROM local_profile")
        ).scalar_one() == 0

    def test_reopen_refuses_missing_installed_database(self):
        runtime = self.make_runtime(data_dir=self.tmp_root / "missing-data")
        runtime.close_engine_keep_lock()
        runtime.db_path.unlink()
        with pytest.raises(LocalDatabaseStateError) as refused:
            runtime.reopen_after_restore()
        assert refused.value.code == "LOCAL_RESTORE_REOPEN_FAILED"

    def test_missing_credential_material_degrades_ai_only(self):
        source, _ = self._source()
        package = self._package(source, "missing-credential")
        target = self.make_runtime(
            data_dir=self.tmp_root / "missing-credential-target",
            credential_root=self.tmp_root / "other-credentials",
        )
        core = RestoreCore(target, app_version="restore-test")
        preview = core.preview(
            package,
            None,
            operation_id=uuid.uuid4().hex,
            cancel=threading.Event(),
        )
        assert preview.credential_configured is True
        assert preview.credential_ready is False
        prepared = core.prepare(preview, cancel=threading.Event())
        assert core.install(prepared, hooks=_Hooks(), cancel=threading.Event()).state == (
            "installed_retired"
        )
        assert core.reopen().state == "reopened"
        session = target.session()
        try:
            config = ai_config_service.get_config(
                session, credential_root=target.credential_root
            )
            assert config.configured is True
            assert config.ready is False
            assert session.execute(
                text("SELECT COUNT(*) FROM local_profile")
            ).scalar_one() == 1
        finally:
            session.close()

    def _crash_restore(self, stage: str, *, expect_profile: int) -> None:
        source, _ = self._source()
        package = self._package(source, f"crash-{stage}")
        root = self.tmp_root / f"crash-{stage}"
        data_dir = root / "data"
        credential_root = root / "credentials"
        spec = {
            "data_dir": str(data_dir),
            "credential_root": str(credential_root),
            "package": str(package),
            "operation_id": uuid.uuid4().hex,
            "fault_stage": stage,
            "result_file": str(root / "result.json"),
        }
        root.mkdir(parents=True, exist_ok=True)
        spec_path = root / "spec.json"
        spec_path.write_text(json.dumps(spec), encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, "-m", "tests.local.restore_worker", str(spec_path)],
            capture_output=True,
            text=True,
            timeout=180,
            env={**os.environ, "PYTHONPATH": str(Path(__file__).parents[2])},
        )
        assert completed.returncode == 70, (completed.returncode, completed.stderr)
        recovered = LocalRuntime(data_dir, credential_root=credential_root)
        recovered.prepare()
        try:
            count = recovered.session().execute(
                text("SELECT COUNT(*) FROM local_profile")
            ).scalar_one()
            assert count == expect_profile
        finally:
            recovered.dispose()

    def test_real_process_kill_after_quiesced_keeps_old(self):
        self._crash_restore("after_quiesced", expect_profile=0)

    def test_real_process_kill_after_old_db_main_keeps_old(self):
        self._crash_restore("after_old_db_main", expect_profile=0)

    def test_real_process_kill_after_installed_journal_keeps_new(self):
        self._crash_restore("after_installed_journal", expect_profile=1)

    def test_real_process_kill_after_terminal_journal_keeps_new(self):
        self._crash_restore("after_terminal_journal", expect_profile=1)

    def test_real_process_kill_after_new_assets_rolls_back_old(self):
        self._crash_restore("after_new_assets", expect_profile=0)

    def test_real_process_kill_after_new_db_rolls_back_old(self):
        self._crash_restore("after_new_db", expect_profile=0)

    def test_cancel_after_first_change_does_not_fake_cancel(self):
        source, _ = self._source()
        package = self._package(source, "late-cancel")
        target = self.make_runtime(data_dir=self.tmp_root / "late-cancel-target")
        cancel = threading.Event()

        def fault(stage: str) -> None:
            if stage == "after_old_db_main":
                cancel.set()

        core = RestoreCore(
            target, app_version="restore-test", fault_injector=fault
        )
        preview = core.preview(
            package,
            None,
            operation_id=uuid.uuid4().hex,
            cancel=threading.Event(),
        )
        prepared = core.prepare(preview, cancel=threading.Event())
        result = core.install(prepared, hooks=_Hooks(), cancel=cancel)
        assert result.state == "installed_retired", result
        assert core.reopen().state == "reopened"
        assert target.session().execute(
            text("SELECT COUNT(*) FROM local_profile")
        ).scalar_one() == 1

    def test_in_process_failure_after_old_move_rolls_back_and_archives(self):
        source, _ = self._source()
        package = self._package(source, "rollback-archive")
        target = self.make_runtime(data_dir=self.tmp_root / "rollback-archive-target")

        def fault(stage: str) -> None:
            if stage == "after_old_db_main":
                raise RuntimeError("injected after old move")

        core = RestoreCore(
            target, app_version="restore-test", fault_injector=fault
        )
        preview = core.preview(
            package,
            None,
            operation_id=uuid.uuid4().hex,
            cancel=threading.Event(),
        )
        prepared = core.prepare(preview, cancel=threading.Event())
        result = core.install(prepared, hooks=_Hooks(), cancel=threading.Event())
        assert result.state == "failed_keep_old", result
        assert result.reopen_required is False
        assert target.prepared is True
        assert target.session().execute(
            text("SELECT COUNT(*) FROM local_profile")
        ).scalar_one() == 0
        paths = operation_paths(target, result.operation_id, create=False)
        assert restore_journal.read_journal(paths) is None
        assert restore_journal.read_receipt(paths, result.operation_id) is not None

    def test_repeat_install_returns_original_result_without_second_switch(self):
        source, _ = self._source()
        package = self._package(source, "idempotent")
        target = self.make_runtime(data_dir=self.tmp_root / "idempotent-target")
        core = RestoreCore(target, app_version="restore-test")
        preview = core.preview(
            package,
            None,
            operation_id=uuid.uuid4().hex,
            cancel=threading.Event(),
        )
        prepared = core.prepare(preview, cancel=threading.Event())
        first = core.install(prepared, hooks=_Hooks(), cancel=threading.Event())
        assert first.state == "installed_retired", first
        second = core.install(prepared, hooks=_Hooks(), cancel=threading.Event())
        assert second == first
        assert core.reopen().state == "reopened"
        session = target.session()
        try:
            profile = session.scalars(select(LocalProfile)).one()
            observation_service.create_observation(
                session,
                profile_id=profile.id,
                request_id=uuid.uuid4().hex,
                record_type="public",
                payload={
                    "observation_date": "2026-09-18",
                    "subjects": [{"name": "重放后新写"}],
                    "environment": "积木区",
                },
            )
            session.commit()
            after = session.execute(
                text("SELECT COUNT(*) FROM local_observation_records")
            ).scalar_one()
        finally:
            session.close()
        third = core.install(prepared, hooks=_Hooks(), cancel=threading.Event())
        assert third == first
        assert target.session().execute(
            text("SELECT COUNT(*) FROM local_observation_records")
        ).scalar_one() == after

    def test_postrename_exception_uses_actual_group_to_rollback_old(self):
        source, _ = self._source()
        package = self._package(source, "postrename")
        current = database_fingerprint(source.db_path)
        session = source.session()
        try:
            profile = session.scalars(select(LocalProfile)).one()
            observation_service.create_observation(
                session,
                profile_id=profile.id,
                request_id=uuid.uuid4().hex,
                record_type="public",
                payload={
                    "observation_date": "2026-09-19",
                    "subjects": [{"name": "改名失败前写入"}],
                    "environment": "积木区",
                },
            )
            session.commit()
        finally:
            session.close()
        expected_old = database_fingerprint(source.db_path)
        core = RestoreCore(source, app_version="restore-test")
        preview = core.preview(
            package,
            None,
            operation_id=uuid.uuid4().hex,
            cancel=threading.Event(),
        )
        prepared = core.prepare(preview, cancel=threading.Event())
        actual_move = restore_group.move_live_component_to_old
        injected = {"done": False}

        def move_then_fail(paths, name):
            actual_move(paths, name)
            if not injected["done"]:
                injected["done"] = True
                raise OSError("injected after actual rename")

        with mock.patch.object(
            restore_group,
            "move_live_component_to_old",
            side_effect=move_then_fail,
        ):
            result = core.install(
                prepared, hooks=_Hooks(), cancel=threading.Event()
            )
        assert injected["done"] is True
        assert result.state == "failed_keep_old", result
        assert source.session().execute(
            text("SELECT COUNT(*) FROM local_profile")
        ).scalar_one() == 1
        assert database_fingerprint(source.db_path) == expected_old
        assert expected_old != current

    def test_credential_root_inside_assets_is_refused_before_switch(self):
        first = self.make_runtime(data_dir=self.tmp_root / "credential-overlap")
        seed_existing_runtime(first)
        package = self._package(first, "credential-overlap-package")
        area = backup_fs.PrivateWorkArea(
            first.data_dir / "observations" / "assets" / "nested-credentials",
            "keys",
        )
        area.__enter__()
        try:
            nested = area.path
            for source_file in first.credential_root.rglob("*.dpapi"):
                target = nested / source_file.relative_to(first.credential_root)
                fd = area.create_file(target)
                with os.fdopen(fd, "wb") as handle:
                    handle.write(source_file.read_bytes())
                    handle.flush()
                    os.fsync(handle.fileno())
            area.detach()
        finally:
            if not area._closed:
                area.detach()
        first.dispose()
        runtime = LocalRuntime(
            self.tmp_root / "credential-overlap",
            credential_root=nested,
        )
        runtime.prepare()
        self.addCleanup(runtime.dispose)
        before = database_fingerprint(runtime.db_path)
        credentials_before = {
            str(path.relative_to(nested)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in nested.rglob("*.dpapi")
        }
        assert credentials_before
        core = RestoreCore(runtime, app_version="restore-test")
        preview = core.preview(
            package,
            None,
            operation_id=uuid.uuid4().hex,
            cancel=threading.Event(),
        )
        assert preview.credential_ready is True
        prepared = core.prepare(preview, cancel=threading.Event())
        result = core.install(prepared, hooks=_Hooks(), cancel=threading.Event())
        assert result.state == "failed_keep_old", result
        assert any("CREDENTIAL" in item or "OVERLAP" in item for item in result.warnings)
        assert database_fingerprint(runtime.db_path) == before
        credentials_after = {
            str(path.relative_to(nested)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in nested.rglob("*.dpapi")
        }
        assert credentials_after == credentials_before

    def test_cancel_completed_preview_retires_staging_and_rejects_late_prepare(self):
        source, _ = self._source()
        package = self._package(source, "cancel-preview")
        target = self.make_runtime(data_dir=self.tmp_root / "cancel-preview-target")
        core = RestoreCore(target, app_version="restore-test")
        operation_id = uuid.uuid4().hex
        preview = core.preview(
            package,
            None,
            operation_id=operation_id,
            cancel=threading.Event(),
        )
        staging = core._previews[operation_id].verified.staging_root
        result = core.cancel(operation_id)
        assert result.accepted is True and result.state == "canceled"
        assert not staging.exists()
        with pytest.raises(RestoreFailure) as refused:
            core.prepare(preview, cancel=threading.Event())
        assert refused.value.code == "RESTORE_OPERATION_CANCELED"

    def test_cancel_prepared_retires_own_work_and_rejects_late_install(self):
        source, _ = self._source()
        package = self._package(source, "cancel-prepared")
        target = self.make_runtime(data_dir=self.tmp_root / "cancel-prepared-target")
        core = RestoreCore(target, app_version="restore-test")
        operation_id = uuid.uuid4().hex
        preview = core.preview(
            package,
            None,
            operation_id=operation_id,
            cancel=threading.Event(),
        )
        prepared = core.prepare(preview, cancel=threading.Event())
        paths = operation_paths(target, operation_id, create=False)
        result = core.cancel(operation_id)
        assert result.accepted is True and result.state == "canceled"
        assert not paths.operation_dir.exists()
        with pytest.raises(RestoreFailure) as refused:
            core.install(prepared, hooks=_Hooks(), cancel=threading.Event())
        assert refused.value.code == "RESTORE_OPERATION_CANCELED"

    def test_receipt_archive_preserves_true_result_state(self):
        runtime = self.make_runtime(data_dir=self.tmp_root / "receipt-state")
        for phase in ("installed", "rolled_back", "failed_keep_old", "canceled"):
            operation_id = uuid.uuid4().hex
            paths = operation_paths(runtime, operation_id, create=True)
            journal = restore_journal.new_journal(
                operation_id=operation_id,
                package={"sha256": "0" * 64},
            )
            journal = restore_journal.set_phase(paths, journal, phase)
            terminal = restore_journal.terminal_journal(paths, journal)
            receipt = restore_journal.write_receipt(paths, terminal)
            assert receipt["result_state"] == phase
            restore_journal.archive_terminal(paths, terminal)
            archived = restore_journal.read_receipt(paths, operation_id)
            assert archived is not None
            assert archived["result_state"] == phase
            assert restore_journal.read_journal(paths) is None

    def test_config_preview_key_rotates(self):
        payload = {"v": 1, "exp": 2**31 - 1}
        token = config_tokens.sign_preview_token(payload)
        assert config_tokens.verify_preview_token(token) == payload
        config_tokens.rotate_key()
        with pytest.raises(LocalValidationError):
            config_tokens.verify_preview_token(token)

    def test_terminal_journal_new_write_survives_two_restarts_and_replay(self):
        source, _ = self._source()
        package = self._package(source, "normal-write")
        data_dir = self.tmp_root / "write-target"
        target = self.make_runtime(data_dir=data_dir)
        core = RestoreCore(target, app_version="restore-test")
        operation_id = uuid.uuid4().hex
        preview = core.preview(
            package,
            None,
            operation_id=operation_id,
            cancel=threading.Event(),
        )
        prepared = core.prepare(preview, cancel=threading.Event())
        result = core.install(prepared, hooks=_Hooks(), cancel=threading.Event())
        assert result.state == "installed_retired", result
        assert core.reopen().state == "reopened"
        paths = operation_paths(target, operation_id, create=False)
        assert restore_journal.read_journal(paths) is None
        receipt = restore_journal.read_receipt(paths, operation_id)
        assert receipt is not None and receipt["terminal"] is True

        session = target.session()
        try:
            profile = session.scalars(select(LocalProfile)).one()
            before = session.execute(
                text("SELECT COUNT(*) FROM local_observation_records")
            ).scalar_one()
            observation_service.create_observation(
                session,
                profile_id=profile.id,
                request_id=uuid.uuid4().hex,
                record_type="public",
                payload={
                    "observation_date": "2026-09-17",
                    "subjects": [{"name": "恢复后新写"}],
                    "environment": "积木区",
                },
            )
            session.commit()
            after = session.execute(
                text("SELECT COUNT(*) FROM local_observation_records")
            ).scalar_one()
        finally:
            session.close()
        assert after == before + 1
        target.dispose()

        # First fresh process.
        first = LocalRuntime(data_dir, credential_root=target.credential_root)
        first.prepare()
        try:
            assert first.session().execute(
                text("SELECT COUNT(*) FROM local_observation_records")
            ).scalar_one() == after
        finally:
            first.dispose()

        # Replay a stale active journal for the same completed operation after
        # normal writes already exist; the terminal receipt must win.
        atomic_write_json(
            paths.journal_path,
            receipt,
            replace=True,
            private_parent=False,
        )
        second = LocalRuntime(data_dir, credential_root=target.credential_root)
        second.prepare()
        try:
            assert second.session().execute(
                text("SELECT COUNT(*) FROM local_observation_records")
            ).scalar_one() == after
        finally:
            second.dispose()

        # Second fresh process; replay must not have installed a rollback.
        third = LocalRuntime(data_dir, credential_root=target.credential_root)
        third.prepare()
        try:
            assert third.session().execute(
                text("SELECT COUNT(*) FROM local_observation_records")
            ).scalar_one() == after
        finally:
            third.dispose()
