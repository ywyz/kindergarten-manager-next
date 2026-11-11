"""Local term rename scope: preserve/update options and record-time reads."""

from __future__ import annotations

import sqlite3
import threading
import unittest
import uuid
from datetime import date, datetime

from alembic import command

from app.local import (
    config_service,
    listening_export_service,
    listening_service,
    observation_service,
    profile_service,
)
from app.local.backup_snapshot import SnapshotService
from app.local.migrate import alembic_config, head_revision
from app.local.normalize import normalize_initialization
from app.local.runtime import LocalRuntime
from app.local.term_names import (
    TermNameChange,
    load_term_name_changes,
    resolve_term_name,
)
from tests.local.support import (
    LocalTestCase,
    StaticCalendarProvider,
    calendar_provider,
    initialize_body,
    query_rows,
    query_scalar,
)

_OMITTED = object()
_PRE_FEATURE_REVISION = "20261111_0020_local_todo_archive"


class TermNameScopeTests(LocalTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.provider = StaticCalendarProvider()
        self.enterContext(calendar_provider(self.provider))
        self.runtime = self.make_runtime()
        session = self.runtime.session()
        try:
            profile_service.initialize(
                session,
                normalize_initialization(**initialize_body(term_name="原始学期")),
            )
            context = profile_service.require_context(
                session, date(2026, 9, 15)
            )
            self.profile_id = context.profile.id
            self.term_id = context.terms[0].id
        finally:
            session.close()
        self.manager = listening_export_service.ListeningExportManager(
            self.runtime, launch_id="term-name-scope-test"
        )

    # -- fixtures ---------------------------------------------------------
    def _rename(
        self,
        name: str,
        update_existing_documents=_OMITTED,
        *,
        term_id: str | None = None,
        start_date: str = "2026-09-01",
        end_date: str = "2026-09-30",
    ):
        change = {
            "kind": "term_update",
            "term_id": self.term_id if term_id is None else term_id,
            "name": name,
            "start_date": start_date,
            "end_date": end_date,
        }
        if update_existing_documents is not _OMITTED:
            change["update_existing_documents"] = update_existing_documents
        version = int(
            query_scalar(
                self.runtime.db_path,
                "SELECT config_version FROM local_settings",
            )
        )
        session = self.runtime.session()
        try:
            preview = config_service.preview(
                session,
                expected_config_version=version,
                change=change,
            )
            applied = config_service.apply(
                session,
                request_id=str(uuid.uuid4()),
                expected_config_version=version,
                change=change,
                preview_token=preview["preview_token"],
            )
            return preview, applied
        finally:
            session.close()

    def _create_term(self, name: str, start_date: str, end_date: str) -> str:
        change = {
            "kind": "term_create",
            "name": name,
            "start_date": start_date,
            "end_date": end_date,
        }
        version = int(
            query_scalar(
                self.runtime.db_path,
                "SELECT config_version FROM local_settings",
            )
        )
        session = self.runtime.session()
        try:
            preview = config_service.preview(
                session,
                expected_config_version=version,
                change=change,
            )
            config_service.apply(
                session,
                request_id=str(uuid.uuid4()),
                expected_config_version=version,
                change=change,
                preview_token=preview["preview_token"],
            )
        finally:
            session.close()
        return query_scalar(
            self.runtime.db_path,
            "SELECT id FROM local_terms WHERE name = ?",
            (name,),
        )

    def _move_observation(
        self, observation_id: str, term_id: str, day: str
    ) -> dict:
        session = self.runtime.session()
        try:
            current = observation_service.read_current(
                session,
                profile_id=self.profile_id,
                observation_id=observation_id,
            )
            return observation_service.save_observation(
                session,
                profile_id=self.profile_id,
                observation_id=observation_id,
                request_id=str(uuid.uuid4()),
                expected_revision=current["revision"],
                payload={"observation_date": day},
                term_decision="assign_selected",
                selected_term_id=term_id,
            )
        finally:
            session.close()

    def _observation(
        self,
        name: str,
        *,
        term_id: str | None = None,
        day: str = "2026-09-15",
    ) -> str:
        target_term = self.term_id if term_id is None else term_id
        session = self.runtime.session()
        try:
            result = observation_service.create_observation(
                session,
                profile_id=self.profile_id,
                request_id=str(uuid.uuid4()),
                record_type="public",
                payload={
                    "observation_date": day,
                    "subjects": [{"name": name}],
                    "environment": "合成区域",
                },
                observation_date=day,
                term_id=target_term,
            )
            return result["observation_id"]
        finally:
            session.close()

    def _listening(self, name: str) -> str:
        session = self.runtime.session()
        try:
            result = listening_service.create_record(
                session,
                profile_id=self.profile_id,
                request_id=str(uuid.uuid4()),
                term_id=self.term_id,
                child_name=name,
            )
            return result["record_id"]
        finally:
            session.close()

    def _observation_name(
        self, observation_id: str, *, term_id: str | None = None
    ) -> str | None:
        session = self.runtime.session()
        try:
            listing = observation_service.list_observations(
                session,
                profile_id=self.profile_id,
                term_id=self.term_id if term_id is None else term_id,
                limit=100,
            )
        finally:
            session.close()
        for item in listing["items"]:
            if item["observation_id"] == observation_id:
                return item["term_name"]
        raise AssertionError("observation not listed")

    def _observation_snapshot_name(self, observation_id: str) -> str | None:
        return query_scalar(
            self.runtime.db_path,
            "SELECT json_extract(term_snapshot_json, '$.name') "
            "FROM local_observation_records WHERE id = ?",
            (observation_id,),
        )

    def _listening_name(self, record_id: str) -> str:
        session = self.runtime.session()
        try:
            context = profile_service.require_context(
                session, date(2026, 9, 15)
            )
            preview = self.manager.preview(
                session,
                profile_id=self.profile_id,
                context=context,
                mode="record",
                record_id=record_id,
                term_id=self.term_id,
            )
            cached = self.manager._previews[preview["preview_id"]]
            self.assertEqual(len(cached.units), 5)
            names = {unit.word.term_name for unit in cached.units}
            self.assertEqual(len(names), 1)
            return names.pop()
        finally:
            session.close()

    # -- option semantics -------------------------------------------------
    def test_false_rename_keeps_existing_and_new_records_use_new_name(self):
        old_observation = self._observation("旧观察")
        old_listening = self._listening("旧倾听")
        preview, applied = self._rename(
            "保留后新名", update_existing_documents=False
        )
        self.assertTrue(preview["changed"])
        self.assertEqual(
            preview["normalized_change"]["update_existing_documents"], False
        )
        self.assertEqual(applied["status"], "applied")
        new_observation = self._observation("新观察")
        new_listening = self._listening("新倾听")

        self.assertEqual(self._observation_name(old_observation), "原始学期")
        self.assertEqual(self._observation_name(new_observation), "保留后新名")
        self.assertEqual(self._listening_name(old_listening), "原始学期")
        self.assertEqual(self._listening_name(new_listening), "保留后新名")
        self.assertEqual(
            self._observation_snapshot_name(old_observation), "原始学期"
        )
        self.assertEqual(
            self._observation_snapshot_name(new_observation), "保留后新名"
        )
        rows = query_rows(
            self.runtime.db_path,
            "SELECT old_name, new_name, update_existing_documents "
            "FROM local_term_name_changes",
        )
        self.assertEqual(
            rows,
            [
                {
                    "old_name": "原始学期",
                    "new_name": "保留后新名",
                    "update_existing_documents": 0,
                }
            ],
        )

    def test_legacy_true_flag_does_not_rewrite_existing_projection(self):
        old_observation = self._observation("旧观察")
        old_listening = self._listening("旧倾听")
        snapshot_before = query_scalar(
            self.runtime.db_path,
            "SELECT term_snapshot_json FROM local_observation_records "
            "WHERE id = ?",
            (old_observation,),
        )
        preview, applied = self._rename(
            "更新后新名", update_existing_documents=True
        )
        self.assertTrue(preview["changed"])
        self.assertEqual(
            preview["normalized_change"]["update_existing_documents"], True
        )
        self.assertEqual(applied["status"], "applied")

        # The legacy bool is accepted for old clients but never performs a
        # global display rewrite.  Existing records keep snapshot/record-time
        # names; only a new explicit reissue version can carry the new name.
        self.assertEqual(self._observation_name(old_observation), "原始学期")
        self.assertEqual(self._listening_name(old_listening), "原始学期")
        self.assertEqual(
            self._observation_snapshot_name(old_observation), "原始学期"
        )
        self.assertEqual(
            query_scalar(
                self.runtime.db_path,
                "SELECT term_snapshot_json FROM local_observation_records "
                "WHERE id = ?",
                (old_observation,),
            ),
            snapshot_before,
        )
        self.assertEqual(
            query_scalar(
                self.runtime.db_path,
                "SELECT name FROM local_terms WHERE id = ?",
                (self.term_id,),
            ),
            "更新后新名",
        )
        new_observation = self._observation("新观察")
        new_listening = self._listening("新倾听")
        self.assertEqual(self._observation_name(new_observation), "更新后新名")
        self.assertEqual(self._listening_name(new_listening), "更新后新名")

    def test_moved_observation_keeps_saved_snapshot_after_ordinary_rename(self):
        moved_term = self._create_term(
            "新归属学期", "2026-10-01", "2026-10-31"
        )
        self._rename(
            "归属原名",
            update_existing_documents=False,
            term_id=moved_term,
            start_date="2026-10-01",
            end_date="2026-10-31",
        )
        # The record is created after the moved term's first rename but still
        # belongs to the original term at this point.
        observation_id = self._observation("原学期观察")
        self._rename(
            "归属中间名",
            update_existing_documents=False,
            term_id=moved_term,
            start_date="2026-10-01",
            end_date="2026-10-31",
        )
        self._move_observation(observation_id, moved_term, "2026-10-15")
        self.assertEqual(
            self._observation_snapshot_name(observation_id), "归属中间名"
        )

        # A later ordinary rename must not replace the saved new-term snapshot
        # with an older timeline base from before the move.
        self._rename(
            "归属最终名",
            update_existing_documents=False,
            term_id=moved_term,
            start_date="2026-10-01",
            end_date="2026-10-31",
        )
        self.assertEqual(
            self._observation_name(observation_id, term_id=moved_term),
            "归属中间名",
        )
        self.assertEqual(
            self._observation_snapshot_name(observation_id), "归属中间名"
        )

        # Even a legacy true rename must not overlay the saved snapshot; the
        # explicit historical reissue flow is the only name-change path.
        self._rename(
            "归属追溯名",
            update_existing_documents=True,
            term_id=moved_term,
            start_date="2026-10-01",
            end_date="2026-10-31",
        )
        self.assertEqual(
            self._observation_name(observation_id, term_id=moved_term),
            "归属中间名",
        )
        self.assertEqual(
            self._observation_snapshot_name(observation_id), "归属中间名"
        )

    def test_omitted_option_keeps_legacy_normalized_change(self):
        old = self._observation("旧观察")
        preview, _applied = self._rename("省略选项新名")
        self.assertNotIn(
            "update_existing_documents", preview["normalized_change"]
        )
        # Omission means the same preserve-old-name behavior as explicit false.
        self.assertEqual(self._observation_name(old), "原始学期")
        new = self._observation("新观察")
        self.assertEqual(self._observation_name(new), "省略选项新名")

    def test_invalid_option_and_non_rename_do_not_append_history(self):
        with self.assertRaises(config_service.LocalValidationError):
            config_service.normalize_change(
                {
                    "kind": "term_update",
                    "term_id": self.term_id,
                    "name": "新名",
                    "start_date": "2026-09-01",
                    "end_date": "2026-09-30",
                    "update_existing_documents": "yes",
                }
            )
        preview, applied = self._rename(
            "原始学期", update_existing_documents=True
        )
        self.assertFalse(preview["changed"])
        self.assertEqual(applied["status"], "unchanged")
        self.assertEqual(
            query_scalar(
                self.runtime.db_path,
                "SELECT count(*) FROM local_term_name_changes",
            ),
            0,
        )

    def test_apply_retry_replays_receipt_without_duplicate_history(self):
        change = {
            "kind": "term_update",
            "term_id": self.term_id,
            "name": "重试新名",
            "start_date": "2026-09-01",
            "end_date": "2026-09-30",
            "update_existing_documents": True,
        }
        version = int(
            query_scalar(
                self.runtime.db_path,
                "SELECT config_version FROM local_settings",
            )
        )
        request_id = str(uuid.uuid4())
        session = self.runtime.session()
        try:
            preview = config_service.preview(
                session,
                expected_config_version=version,
                change=change,
            )
            first = config_service.apply(
                session,
                request_id=request_id,
                expected_config_version=version,
                change=change,
                preview_token=preview["preview_token"],
            )
            retried = config_service.apply(
                session,
                request_id=request_id,
                expected_config_version=version,
                change=change,
                preview_token=preview["preview_token"],
            )
        finally:
            session.close()
        self.assertEqual(first["status"], "applied")
        self.assertEqual(retried["status"], "applied")
        self.assertTrue(retried["replayed"])
        self.assertEqual(
            query_scalar(
                self.runtime.db_path,
                "SELECT count(*) FROM local_term_name_changes",
            ),
            1,
        )
        self.assertEqual(
            query_scalar(
                self.runtime.db_path,
                "SELECT config_version FROM local_settings",
            ),
            version + 1,
        )

    # -- two historical renames ------------------------------------------
    def test_two_historical_renames_resolve_by_record_time(self):
        before = self._observation("更名前")
        before_listening = self._listening("更名前倾听")
        self._rename("中间名", update_existing_documents=True)
        between = self._observation("中间时点")
        between_listening = self._listening("中间倾听")
        self._rename("最终名", update_existing_documents=False)
        after = self._observation("最终时点")
        after_listening = self._listening("最终倾听")

        # Record-time semantics ignore the legacy true flag: the record made
        # before the first rename stays on its original snapshot/name.  Records
        # created after a rename use the name current at their creation.
        self.assertEqual(self._observation_name(before), "原始学期")
        self.assertEqual(self._listening_name(before_listening), "原始学期")
        self.assertEqual(self._observation_name(between), "中间名")
        self.assertEqual(self._listening_name(between_listening), "中间名")
        self.assertEqual(self._observation_name(after), "最终名")
        self.assertEqual(self._listening_name(after_listening), "最终名")

        self.assertEqual(self._observation_snapshot_name(before), "原始学期")
        self.assertEqual(self._observation_snapshot_name(between), "中间名")
        self.assertEqual(self._observation_snapshot_name(after), "最终名")
        self.assertEqual(
            query_rows(
                self.runtime.db_path,
                "SELECT old_name, new_name, update_existing_documents "
                "FROM local_term_name_changes ORDER BY config_version",
            ),
            [
                {
                    "old_name": "原始学期",
                    "new_name": "中间名",
                    "update_existing_documents": 1,
                },
                {
                    "old_name": "中间名",
                    "new_name": "最终名",
                    "update_existing_documents": 0,
                },
            ],
        )

    def test_resolver_uses_record_time_and_ignores_legacy_true(self):
        # Pure timeline check: a record before every rename keeps A; a record
        # created after a rename uses that rename's new name.  A legacy true
        # row does not retroactively rewrite an older record.
        changes = (
            TermNameChange(
                old_name="A",
                new_name="B",
                update_existing_documents=False,
                config_version=2,
                changed_at=datetime(2026, 9, 2),
            ),
            TermNameChange(
                old_name="B",
                new_name="C",
                update_existing_documents=False,
                config_version=3,
                changed_at=datetime(2026, 9, 3),
            ),
            TermNameChange(
                old_name="C",
                new_name="D",
                update_existing_documents=True,
                config_version=4,
                changed_at=datetime(2026, 9, 4),
            ),
        )
        for recorded_at, expected in (
            (datetime(2026, 9, 1), "A"),
            (datetime(2026, 9, 2, 12), "B"),
            (datetime(2026, 9, 3, 12), "C"),
            (datetime(2026, 9, 4, 12), "D"),
        ):
            self.assertEqual(
                resolve_term_name(
                    changes,
                    recorded_at=recorded_at,
                    fallback_name="A",
                ),
                expected,
            )

    # -- pre-feature database and backup ---------------------------------
    def test_pre_feature_database_upgrades_without_rewriting_existing_names(self):
        observation_id = self._observation("升级前观察")
        self._listening("升级前倾听")
        self.runtime.dispose()

        connection = sqlite3.connect(str(self.runtime.db_path))
        try:
            connection.execute("DROP TABLE local_term_name_changes")
            connection.execute(
                "UPDATE local_alembic_version SET version_num = ?",
                (_PRE_FEATURE_REVISION,),
            )
            connection.commit()
        finally:
            connection.close()

        upgraded = LocalRuntime(
            self.data_dir, credential_root=self.credential_root
        )
        try:
            upgraded.prepare()
            self.addCleanup(upgraded.dispose)
            self.assertEqual(
                query_scalar(
                    upgraded.db_path,
                    "SELECT version_num FROM local_alembic_version",
                ),
                head_revision(),
            )
            self.assertEqual(
                query_scalar(
                    upgraded.db_path,
                    "SELECT count(*) FROM local_term_name_changes",
                ),
                0,
            )
            self.assertEqual(
                query_scalar(
                    upgraded.db_path,
                    "SELECT name FROM local_terms WHERE id = ?",
                    (self.term_id,),
                ),
                "原始学期",
            )
            session = upgraded.session()
            try:
                listing = observation_service.list_observations(
                    session,
                    profile_id=self.profile_id,
                    term_id=self.term_id,
                    limit=100,
                )
            finally:
                session.close()
            self.assertEqual(listing["items"][0]["term_name"], "原始学期")

            # A legacy true rename after upgrade does not rewrite the old
            # observation projection; an explicit reissue is required.
            version = int(
                query_scalar(
                    upgraded.db_path,
                    "SELECT config_version FROM local_settings",
                )
            )
            change = {
                "kind": "term_update",
                "term_id": self.term_id,
                "name": "升级后新名",
                "start_date": "2026-09-01",
                "end_date": "2026-09-30",
                "update_existing_documents": True,
            }
            session = upgraded.session()
            try:
                preview = config_service.preview(
                    session,
                    expected_config_version=version,
                    change=change,
                )
                config_service.apply(
                    session,
                    request_id=str(uuid.uuid4()),
                    expected_config_version=version,
                    change=change,
                    preview_token=preview["preview_token"],
                )
            finally:
                session.close()
            session = upgraded.session()
            try:
                listing = observation_service.list_observations(
                    session,
                    profile_id=self.profile_id,
                    term_id=self.term_id,
                    limit=100,
                )
            finally:
                session.close()
            self.assertEqual(listing["items"][0]["term_name"], "原始学期")
            self.assertEqual(
                self._observation_snapshot_name(observation_id), "原始学期"
            )

            # The new table is included in a verified snapshot.
            output = self.tmp_root / "term-history.kgmbackup"
            service = SnapshotService(
                upgraded,
                app_version="0.1.0-test",
                source_identity={"commit": "test", "tree": "test-tree"},
            )
            result = service.create(
                output,
                password=None,
                cancel=threading.Event(),
                progress=lambda _item: None,
            )
            self.assertTrue(result.verified)
            verified = service.verify(
                output, password=None, cancel=threading.Event()
            )
            try:
                connection = sqlite3.connect(str(verified.database_path))
                try:
                    rows = connection.execute(
                        "SELECT old_name, new_name, update_existing_documents "
                        "FROM local_term_name_changes"
                    ).fetchall()
                finally:
                    connection.close()
            finally:
                service.discard_verified(verified)
            self.assertEqual(
                rows, [("原始学期", "升级后新名", 1)]
            )
        finally:
            upgraded.dispose()

    def test_name_history_loading_is_ordered_and_empty_for_unknown_term(self):
        self._rename("第二版", update_existing_documents=False)
        session = self.runtime.session()
        try:
            changes = load_term_name_changes(
                session, [self.term_id, "unknown-term"]
            )
        finally:
            session.close()
        self.assertEqual(len(changes[self.term_id]), 1)
        self.assertNotIn("unknown-term", changes)


if __name__ == "__main__":
    unittest.main()
