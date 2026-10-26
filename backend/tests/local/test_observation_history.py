"""E05/E08 service tests: save, retained history, preview and restore."""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from PIL import Image
from sqlalchemy import event, select, text

from app.local import (
    observation_assets,
    observation_history_service,
    observation_service,
    profile_service,
)
from app.local.models import (
    LocalObservationAsset,
    LocalObservationDraft,
    LocalObservationOperation,
    LocalObservationRecord,
    LocalObservationRestore,
    LocalObservationRestorePreview,
    LocalObservationVersion,
    LocalObservationVersionPhoto,
    LocalOperationRecord,
    LocalProfile,
    LocalTerm,
)
from app.local.normalize import normalize_initialization
from app.local.observation_validation import aggregate_hash
from tests.local.support import LocalTestCase, initialize_body


class ObservationHistoryServiceTests(LocalTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.runtime = self.make_runtime()
        self.session = self.runtime.session()
        profile_service.initialize(
            self.session, normalize_initialization(**initialize_body())
        )
        self.session.commit()
        self.profile = self.session.scalars(select(LocalProfile)).one()
        self.now = datetime(2026, 10, 27, 9, 0, 0)

    def tearDown(self) -> None:
        self.session.close()
        super().tearDown()

    def _payload(self, **overrides):
        value = {
            "observation_date": "2026-09-15",
            "record_type": "public",
            "observation_goal": "观察目标",
            "observation_process": "观察记录",
            "support_strategy": "支持策略",
        }
        value.update(overrides)
        return value

    def _create(self, **payload):
        return observation_service.create_observation(
            self.session,
            profile_id=self.profile.id,
            request_id=str(uuid.uuid4()),
            record_type="public",
            payload=self._payload(**payload),
            now=self.now,
        )

    def _current(self, observation_id: str):
        return observation_service.read_current(
            self.session,
            profile_id=self.profile.id,
            observation_id=observation_id,
        )

    def _save(
        self,
        observation_id: str,
        payload: dict,
        *,
        reason: str = "manual",
        photos=None,
        term_decision=None,
        selected_term_id=None,
    ):
        current = self._current(observation_id)
        return observation_service.save_observation(
            self.session,
            profile_id=self.profile.id,
            observation_id=observation_id,
            request_id=str(uuid.uuid4()),
            expected_revision=current["revision"],
            payload=payload,
            photos=photos,
            save_reason=reason,
            term_decision=term_decision,
            selected_term_id=selected_term_id,
            now=self.now,
        )

    def _jpeg(self) -> bytes:
        buffer = io.BytesIO()
        Image.new("RGB", (40, 30), "red").save(buffer, "JPEG", quality=90)
        return buffer.getvalue()

    def _import_photo(self, observation_id: str, color: str = "red") -> str:
        buffer = io.BytesIO()
        Image.new("RGB", (40, 30), color).save(buffer, "JPEG", quality=90)
        current = self._current(observation_id)
        result = observation_assets.import_asset(
            self.session,
            self.runtime,
            profile_id=self.profile.id,
            observation_id=observation_id,
            request_id=str(uuid.uuid4()),
            expected_revision=current["revision"],
            stream=io.BytesIO(buffer.getvalue()),
            display_name=f"{color}.jpg",
            caption=None,
            now=self.now,
        )
        return result["asset_id"]

    def _preserve_evidence(self, name: str, summary: dict) -> None:
        root = os.environ.get("E0508_EVIDENCE_ROOT")
        if not root or self.runtime is None:
            return
        target = Path(root) / name
        target.mkdir(parents=True, exist_ok=True)
        source = sqlite3.connect(str(self.runtime.db_path))
        destination = sqlite3.connect(str(target / "kindergarten.db"))
        try:
            source.backup(destination)
            destination.execute("PRAGMA wal_checkpoint(FULL)")
        finally:
            destination.close()
            source.close()
        observations = self.data_dir / "observations"
        if observations.exists():
            shutil.copytree(
                observations,
                target / "observations",
                dirs_exist_ok=True,
            )
        (target / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    def test_create_defaults_empty_and_term_snapshot(self):
        result = self._create()
        self.assertEqual(result["revision"], 1)
        self.assertIsNone(result["current_version"])
        self.assertEqual(result["photos"], [])
        current = self._current(result["observation_id"])
        self.assertEqual(current["payload"]["school_name"], "示范幼儿园")
        self.assertEqual(current["payload"]["class_name"], "中一班")
        self.assertEqual(current["payload"]["observer_name"], "王老师")
        self.assertEqual(current["payload"]["observation_date"], "2026-09-15")
        self.assertIsNotNone(current["payload"]["term_snapshot"])
        self.assertEqual(current["payload"]["term_snapshot"]["name"], "2026 年秋季学期")
        self.assertEqual(
            current["payload_hash"],
            aggregate_hash(current["payload"], []),
        )
        empty = observation_service.create_observation(
            self.session,
            profile_id=self.profile.id,
            request_id=str(uuid.uuid4()),
            record_type="public",
            payload={"record_type": "public", "observation_date": None},
            now=self.now,
        )
        empty_current = self._current(empty["observation_id"])
        self.assertIsNone(empty_current["payload"]["observation_date"])
        self.assertIsNone(empty_current["payload"]["term_id"])
        self.assertIsNone(empty_current["payload"]["term_snapshot"])
        self.assertEqual(empty_current["payload"]["analysis_evaluation"]["health"], "")

    def test_auto_manual_history_and_a_b_a(self):
        created = self._create(observation_goal="A")
        observation_id = created["observation_id"]
        auto = self._save(observation_id, {"observation_goal": "B"}, reason="auto")
        self.assertTrue(auto["changed"])
        self.assertFalse(auto["history_created"])
        self.assertEqual(auto["revision"], 2)
        manual_same = self._save(observation_id, {"observation_goal": "B"}, reason="manual")
        self.assertFalse(manual_same["changed"])
        self.assertTrue(manual_same["history_created"])
        self.assertEqual(manual_same["revision"], 2)
        self.assertEqual(manual_same["current_version"], 1)
        auto_c = self._save(observation_id, {"observation_goal": "C"}, reason="auto")
        self.assertEqual(auto_c["revision"], 3)
        self.assertFalse(auto_c["history_created"])
        manual_c = self._save(observation_id, {"observation_goal": "C"}, reason="manual")
        self.assertFalse(manual_c["changed"])
        self.assertTrue(manual_c["history_created"])
        self.assertEqual(manual_c["current_version"], 2)
        manual_a = self._save(observation_id, {"observation_goal": "A"}, reason="manual")
        self.assertTrue(manual_a["changed"])
        self.assertEqual(manual_a["revision"], 4)
        self.assertEqual(manual_a["current_version"], 3)
        noop = self._save(observation_id, {"observation_goal": "A"}, reason="auto")
        self.assertFalse(noop["changed"])
        self.assertFalse(noop["history_created"])
        self.assertEqual(noop["revision"], 4)
        versions = observation_history_service.list_history(
            self.session,
            profile_id=self.profile.id,
            observation_id=observation_id,
        )
        self.assertEqual([row["version"] for row in versions], [3, 2, 1])
        self.assertEqual(
            [row["payload_hash"] for row in versions],
            [
                self._current(observation_id)["payload_hash"],
                self._history_hash(observation_id, 2),
                self._history_hash(observation_id, 1),
            ],
        )

    def _history_hash(self, observation_id: str, version: int) -> str:
        row = self.session.scalars(
            select(LocalObservationVersion).where(
                LocalObservationVersion.observation_id == observation_id,
                LocalObservationVersion.version == version,
            )
        ).one()
        return row.payload_hash

    def test_photo_order_caption_and_current_remove_keep_history(self):
        created = self._create()
        observation_id = created["observation_id"]
        first = self._import_photo(observation_id, "red")
        second = self._import_photo(observation_id, "blue")
        saved = self._save(
            observation_id,
            {"observation_goal": "有图"},
            photos=[
                {"asset_id": second, "caption": "第二张"},
                {"asset_id": first, "caption": "第一张"},
            ],
        )
        self.assertTrue(saved["changed"])
        self.assertEqual(
            [photo["asset_id"] for photo in saved["photos"]], [second, first]
        )
        self.assertEqual(
            [photo["caption"] for photo in saved["photos"]], ["第二张", "第一张"]
        )
        history = observation_history_service.read_history_version(
            self.session,
            profile_id=self.profile.id,
            observation_id=observation_id,
            version=saved["current_version"],
        )
        self.assertEqual(
            [photo["asset_id"] for photo in history["photos"]], [second, first]
        )
        self.assertEqual(
            [photo["caption"] for photo in history["photos"]], ["第二张", "第一张"]
        )
        removed = self._save(
            observation_id,
            {"observation_goal": "移除第一张"},
            photos=[{"asset_id": second, "caption": "第二张"}],
            reason="auto",
        )
        self.assertEqual([photo["asset_id"] for photo in removed["photos"]], [second])
        old = observation_history_service.read_history_version(
            self.session,
            profile_id=self.profile.id,
            observation_id=observation_id,
            version=saved["current_version"],
        )
        self.assertEqual([photo["asset_id"] for photo in old["photos"]], [second, first])
        self.assertIsNotNone(self.session.get(LocalObservationAsset, first))
        self.assertTrue(
            observation_assets.read_asset_bytes(
                self.session,
                self.runtime,
                profile_id=self.profile.id,
                observation_id=observation_id,
                asset_id=first,
            ).startswith(b"\xff\xd8")
        )

    def test_history_preview_restore_and_receipt_replay(self):
        created = self._create(observation_goal="A")
        observation_id = created["observation_id"]
        first = self._save(observation_id, {"observation_goal": "A"}, reason="manual")
        second = self._save(observation_id, {"observation_goal": "B"}, reason="manual")
        protected = self._save(observation_id, {"observation_goal": "B"}, reason="pre_restore")
        current = self._current(observation_id)
        preview_request = str(uuid.uuid4())
        preview = observation_history_service.preview_restore(
            self.session,
            self.runtime,
            profile_id=self.profile.id,
            observation_id=observation_id,
            source_version=first["current_version"],
            request_id=preview_request,
            base_draft_revision=current["revision"],
            base_draft_hash=current["payload_hash"],
            term_decision="keep_history",
            now=self.now,
        )
        self.assertEqual(preview["source_version"], first["current_version"])
        restore_request = preview_request
        restored = observation_history_service.restore_observation(
            self.session,
            self.runtime,
            profile_id=self.profile.id,
            observation_id=observation_id,
            request_id=restore_request,
            restore_token=preview["restore_token"],
            expected_base_revision=current["revision"],
            expected_base_hash=current["payload_hash"],
            term_decision="keep_history",
            now=self.now,
        )
        self.assertTrue(restored["changed"])
        self.assertEqual(restored["revision"], current["revision"] + 1)
        self.assertEqual(restored["current_version"], second["current_version"] + 1)
        after = self._current(observation_id)
        self.assertEqual(after["payload"]["observation_goal"], "A")
        replay = observation_history_service.restore_observation(
            self.session,
            self.runtime,
            profile_id=self.profile.id,
            observation_id=observation_id,
            request_id=restore_request,
            restore_token=preview["restore_token"],
            expected_base_revision=current["revision"],
            expected_base_hash=current["payload_hash"],
            term_decision="keep_history",
            now=self.now,
        )
        self.assertEqual(replay, restored)
        with self.assertRaises(
            observation_history_service.ObservationRestoreTokenConsumed
        ):
            observation_history_service.restore_observation(
                self.session,
                self.runtime,
                profile_id=self.profile.id,
                observation_id=observation_id,
                request_id=str(uuid.uuid4()),
                restore_token=preview["restore_token"],
                expected_base_revision=current["revision"],
                expected_base_hash=current["payload_hash"],
                term_decision="keep_history",
                now=self.now,
            )
        restore_row = self.session.scalars(
            select(LocalObservationRestore).where(
                LocalObservationRestore.observation_id == observation_id
            )
        ).one()
        self.assertEqual(restore_row.changed, 1)

    def test_restore_requires_protection_and_rejects_late_edit(self):
        created = self._create(observation_goal="A")
        observation_id = created["observation_id"]
        current = self._current(observation_id)
        with self.assertRaises(
            observation_service.ObservationRestoreUnprotected
        ):
            observation_history_service.preview_restore(
                self.session,
                self.runtime,
                profile_id=self.profile.id,
                observation_id=observation_id,
                source_version=1,
                request_id=str(uuid.uuid4()),
                base_draft_revision=current["revision"],
                base_draft_hash=current["payload_hash"],
                term_decision="keep_history",
                now=self.now,
            )
        version = self._save(observation_id, {"observation_goal": "A"}, reason="manual")
        current = self._current(observation_id)
        preview_request = str(uuid.uuid4())
        preview = observation_history_service.preview_restore(
            self.session,
            self.runtime,
            profile_id=self.profile.id,
            observation_id=observation_id,
            source_version=version["current_version"],
            request_id=preview_request,
            base_draft_revision=current["revision"],
            base_draft_hash=current["payload_hash"],
            term_decision="keep_history",
            now=self.now,
        )
        self._save(observation_id, {"observation_goal": "late"}, reason="auto")
        with self.assertRaises(
            observation_history_service.ObservationRestorePreviewInvalid
        ):
            observation_history_service.restore_observation(
                self.session,
                self.runtime,
                profile_id=self.profile.id,
                observation_id=observation_id,
                request_id=preview_request,
                restore_token=preview["restore_token"],
                expected_base_revision=current["revision"],
                expected_base_hash=current["payload_hash"],
                term_decision="keep_history",
                now=self.now,
            )
        self.assertEqual(
            self._current(observation_id)["payload"]["observation_goal"], "late"
        )

    def test_restore_expired_token_and_projection_mismatch(self):
        created = self._create(observation_goal="A")
        observation_id = created["observation_id"]
        version = self._save(observation_id, {"observation_goal": "A"}, reason="manual")
        current = self._current(observation_id)
        preview_request = str(uuid.uuid4())
        preview = observation_history_service.preview_restore(
            self.session,
            self.runtime,
            profile_id=self.profile.id,
            observation_id=observation_id,
            source_version=version["current_version"],
            request_id=preview_request,
            base_draft_revision=current["revision"],
            base_draft_hash=current["payload_hash"],
            term_decision="keep_history",
            now=self.now,
        )
        with self.assertRaises(
            observation_history_service.ObservationRestorePreviewExpired
        ):
            observation_history_service.restore_observation(
                self.session,
                self.runtime,
                profile_id=self.profile.id,
                observation_id=observation_id,
                request_id=preview_request,
                restore_token=preview["restore_token"],
                expected_base_revision=current["revision"],
                expected_base_hash=current["payload_hash"],
                term_decision="keep_history",
                now=self.now
                + timedelta(
                    seconds=observation_history_service.RESTORE_PREVIEW_TTL_SECONDS
                    + 1
                ),
            )
        record = self.session.get(
            __import__("app.local.models", fromlist=["LocalObservationRecord"]).LocalObservationRecord,
            observation_id,
        )
        record.current_draft_revision += 1
        self.session.commit()
        with self.assertRaises(observation_service.ObservationProjectionMismatch):
            self._current(observation_id)

    def test_real_sqlite_trigger_rolls_back_history_and_operation(self):
        created = self._create(observation_goal="A")
        observation_id = created["observation_id"]
        first = self._save(observation_id, {"observation_goal": "A"}, reason="manual")
        current = self._current(observation_id)
        before_versions = len(
            self.session.scalars(
                select(LocalObservationVersion).where(
                    LocalObservationVersion.observation_id == observation_id
                )
            ).all()
        )
        before_operations = len(
            self.session.scalars(select(LocalObservationOperation)).all()
        )
        self.session.execute(
            text(
                "CREATE TRIGGER e0508_abort_version "
                "BEFORE INSERT ON local_observation_versions "
                "BEGIN SELECT RAISE(ABORT, 'synthetic'); END"
            )
        )
        self.session.commit()
        try:
            with self.assertRaises(observation_service.ObservationStorageError):
                observation_service.save_observation(
                    self.session,
                    profile_id=self.profile.id,
                    observation_id=observation_id,
                    request_id=str(uuid.uuid4()),
                    expected_revision=current["revision"],
                    payload={"observation_goal": "B"},
                    save_reason="manual",
                    now=self.now,
                )
        finally:
            self.session.execute(text("DROP TRIGGER e0508_abort_version"))
            self.session.commit()
        self.assertEqual(
            len(
                self.session.scalars(
                    select(LocalObservationVersion).where(
                        LocalObservationVersion.observation_id == observation_id
                    )
                ).all()
            ),
            before_versions,
        )
        self.assertEqual(
            len(self.session.scalars(select(LocalObservationOperation)).all()),
            before_operations,
        )
        self.assertEqual(
            self._current(observation_id)["payload"]["observation_goal"], "A"
        )
        self.assertEqual(
            self._current(observation_id)["current_version"],
            first["current_version"],
        )

    def test_projection_history_integrity_and_creator_isolation(self):
        created = self._create(observation_goal="A")
        observation_id = created["observation_id"]
        self._save(observation_id, {"observation_goal": "A"}, reason="manual")
        self._save(observation_id, {"observation_goal": "B"}, reason="manual")
        current = self._current(observation_id)
        self.assertEqual(current["current_version"], 2)
        record = self.session.get(LocalObservationRecord, observation_id)
        original_class = record.class_name
        original_term = record.term_id
        record.class_name = "被篡改班级"
        self.session.commit()
        with self.assertRaises(observation_service.ObservationProjectionMismatch):
            self._current(observation_id)
        record.class_name = original_class
        record.term_id = None
        self.session.commit()
        with self.assertRaises(observation_service.ObservationProjectionMismatch):
            self._current(observation_id)
        record.term_id = original_term
        record.subjects_json = [{"name": "被篡改"}]
        self.session.commit()
        with self.assertRaises(observation_service.ObservationProjectionMismatch):
            self._current(observation_id)
        record.subjects_json = []
        record.current_version = 1
        self.session.commit()
        with self.assertRaises(observation_service.ObservationProjectionMismatch):
            self._current(observation_id)
        record.current_version = 2
        self.session.commit()
        version = self.session.scalars(
            select(LocalObservationVersion).where(
                LocalObservationVersion.observation_id == observation_id,
                LocalObservationVersion.version == 1,
            )
        ).one()
        damaged = dict(version.payload_json)
        damaged.pop("observation_goal")
        version.payload_json = damaged
        version.payload_hash = aggregate_hash(damaged, [])
        self.session.commit()
        with self.assertRaises(observation_service.ObservationProjectionMismatch):
            observation_history_service.read_history_version(
                self.session,
                profile_id=self.profile.id,
                observation_id=observation_id,
                version=1,
            )
        with self.assertRaises(observation_service.ObservationNotFound):
            observation_history_service.read_history_version(
                self.session,
                profile_id="x" * 32,
                observation_id=observation_id,
                version=1,
            )

    def test_create_default_empty_and_term_decision_protocol(self):
        defaulted = observation_service.create_observation(
            self.session,
            profile_id=self.profile.id,
            request_id=str(uuid.uuid4()),
            record_type="public",
            payload=None,
            now=self.now,
        )
        self.assertEqual(defaulted["revision"], 1)
        self.assertIsNone(defaulted["current_version"])
        created = self._create(observation_goal="A")
        observation_id = created["observation_id"]
        self._save(observation_id, {"observation_goal": "A"}, reason="manual")
        current = self._current(observation_id)
        term_id = current["payload"]["term_id"]
        with self.assertRaises(observation_service.ObservationTermDecisionRequired):
            self._save(
                observation_id,
                {
                    "observation_date": "2026-10-15",
                    "term_id": term_id,
                    "observation_goal": "跨学期",
                },
            )
        self.assertEqual(self._current(observation_id)["payload"]["observation_date"], "2026-09-15")
        moved = self._save(
            observation_id,
            {
                "observation_date": "2026-10-15",
                "term_id": term_id,
                "observation_goal": "未归属",
            },
            reason="manual",
            term_decision="unassigned",
        )
        self.assertEqual(moved["term_warnings"], [])
        self.assertIsNone(self._current(observation_id)["payload"]["term_id"])
        unassigned = observation_service.create_observation(
            self.session,
            profile_id=self.profile.id,
            request_id=str(uuid.uuid4()),
            record_type="public",
            payload={"record_type": "public", "observation_date": None},
            now=self.now,
        )
        unassigned_id = unassigned["observation_id"]
        self._save(unassigned_id, {"observation_date": None}, reason="manual")
        with self.assertRaises(observation_service.ObservationTermDecisionRequired):
            self._save(
                unassigned_id,
                {"observation_date": "2026-09-15"},
            )
        assigned = observation_service.save_observation(
            self.session,
            profile_id=self.profile.id,
            observation_id=unassigned_id,
            request_id=str(uuid.uuid4()),
            expected_revision=self._current(unassigned_id)["revision"],
            payload={"observation_date": "2026-09-15"},
            save_reason="manual",
            term_decision="assign_selected",
            selected_term_id=term_id,
            now=self.now,
        )
        self.assertEqual(assigned["term_warnings"], [])

    def test_create_fingerprint_ignores_incidental_whitespace(self):
        request_id = str(uuid.uuid4())
        first = observation_service.create_observation(
            self.session,
            profile_id=self.profile.id,
            request_id=request_id,
            record_type="public",
            payload={"observation_date": "2026-09-15", "observation_goal": "  A  "},
            now=self.now,
        )
        again = observation_service.create_observation(
            self.session,
            profile_id=self.profile.id,
            request_id=request_id,
            record_type="public",
            payload={"observation_date": "2026-09-15", "observation_goal": "A"},
            now=self.now,
        )
        self.assertEqual(first, again)

    def test_empty_term_decision_binding_and_no_change_restore_result(self):
        created = observation_service.create_observation(
            self.session,
            profile_id=self.profile.id,
            request_id=str(uuid.uuid4()),
            record_type="public",
            payload={"record_type": "public", "observation_date": None},
            now=self.now,
        )
        observation_id = created["observation_id"]
        version = self._save(observation_id, {"observation_date": None}, reason="manual")
        current = self._current(observation_id)
        preview_request = str(uuid.uuid4())
        preview = observation_history_service.preview_restore(
            self.session,
            self.runtime,
            profile_id=self.profile.id,
            observation_id=observation_id,
            source_version=version["current_version"],
            request_id=preview_request,
            base_draft_revision=current["revision"],
            base_draft_hash=current["payload_hash"],
            term_decision="keep_history",
            now=self.now,
        )
        with self.assertRaises(observation_history_service.ObservationRestorePreviewInvalid):
            observation_history_service.restore_observation(
                self.session,
                self.runtime,
                profile_id=self.profile.id,
                observation_id=observation_id,
                request_id=str(uuid.uuid4()),
                restore_token=preview["restore_token"],
                expected_base_revision=current["revision"],
                expected_base_hash=current["payload_hash"],
                term_decision="keep_history",
                now=self.now,
            )
        with self.assertRaises(observation_history_service.ObservationRestorePreviewInvalid):
            observation_history_service.restore_observation(
                self.session,
                self.runtime,
                profile_id=self.profile.id,
                observation_id=observation_id,
                request_id=preview_request,
                restore_token=preview["restore_token"],
                expected_base_revision=current["revision"],
                expected_base_hash=current["payload_hash"],
                term_decision="unassigned",
                now=self.now,
            )
        result = observation_history_service.restore_observation(
            self.session,
            self.runtime,
            profile_id=self.profile.id,
            observation_id=observation_id,
            request_id=preview_request,
            restore_token=preview["restore_token"],
            expected_base_revision=current["revision"],
            expected_base_hash=current["payload_hash"],
            term_decision="keep_history",
            now=self.now,
        )
        self.assertFalse(result["changed"])
        self.assertEqual(result["result_version"], version["current_version"])
        self.assertEqual(result["revision"], current["revision"])

    def test_restore_rejects_same_shape_material_and_ancestor_junction(self):
        created = self._create(observation_goal="A")
        observation_id = created["observation_id"]
        asset_id = self._import_photo(observation_id, "red")
        version = self._save(
            observation_id,
            {"observation_goal": "A"},
            photos=[{"asset_id": asset_id, "caption": "图"}],
            reason="manual",
        )
        current = self._current(observation_id)
        preview_request = str(uuid.uuid4())
        preview = observation_history_service.preview_restore(
            self.session,
            self.runtime,
            profile_id=self.profile.id,
            observation_id=observation_id,
            source_version=version["current_version"],
            request_id=preview_request,
            base_draft_revision=current["revision"],
            base_draft_hash=current["payload_hash"],
            term_decision="keep_history",
            now=self.now,
        )
        asset = self.session.get(LocalObservationAsset, asset_id)
        asset_path = self.runtime.data_dir / asset.relative_path
        original = asset_path.read_bytes()
        blue = io.BytesIO()
        Image.new("RGB", (40, 30), "blue").save(blue, "JPEG", quality=90)
        asset_path.write_bytes(blue.getvalue())
        with self.assertRaises(observation_history_service.ObservationRestoreSourceInvalid):
            observation_history_service.restore_observation(
                self.session,
                self.runtime,
                profile_id=self.profile.id,
                observation_id=observation_id,
                request_id=preview_request,
                restore_token=preview["restore_token"],
                expected_base_revision=current["revision"],
                expected_base_hash=current["payload_hash"],
                term_decision="keep_history",
                now=self.now,
            )
        self.assertEqual(
            self._current(observation_id)["payload"]["observation_goal"], "A"
        )
        asset_path.write_bytes(original)
        preview2_request = str(uuid.uuid4())
        preview2 = observation_history_service.preview_restore(
            self.session,
            self.runtime,
            profile_id=self.profile.id,
            observation_id=observation_id,
            source_version=version["current_version"],
            request_id=preview2_request,
            base_draft_revision=current["revision"],
            base_draft_hash=current["payload_hash"],
            term_decision="keep_history",
            now=self.now,
        )
        outside = self.tmp_root / "outside-assets"
        outside.mkdir()
        shutil.copy2(asset_path, outside / "original.jpg")
        backup = asset_path.parent.with_name(asset_path.parent.name + "-backup")
        asset_path.parent.rename(backup)
        completed = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(asset_path.parent), str(outside)],
            capture_output=True,
        )
        try:
            self.assertEqual(completed.returncode, 0, completed.stderr)
            with self.assertRaises(observation_history_service.ObservationRestoreSourceInvalid):
                observation_history_service.restore_observation(
                    self.session,
                    self.runtime,
                    profile_id=self.profile.id,
                    observation_id=observation_id,
                    request_id=preview2_request,
                    restore_token=preview2["restore_token"],
                    expected_base_revision=current["revision"],
                    expected_base_hash=current["payload_hash"],
                    term_decision="keep_history",
                    now=self.now,
                )
        finally:
            os.rmdir(asset_path.parent)
            shutil.rmtree(backup, ignore_errors=True)

    def test_read_receipt_is_side_effect_free_and_profile_scoped(self):
        created = self._create(observation_goal="A")
        operation = self.session.scalars(
            select(LocalObservationOperation).where(
                LocalObservationOperation.observation_id == created["observation_id"]
            )
        ).one()
        before = len(self.session.scalars(select(LocalObservationOperation)).all())
        receipt = observation_service.read_operation_receipt(
            self.session,
            profile_id=self.profile.id,
            request_id=operation.request_id,
        )
        self.assertEqual(receipt["operation_kind"], "observation_create")
        self.assertEqual(
            len(self.session.scalars(select(LocalObservationOperation)).all()), before
        )
        with self.assertRaises(observation_service.ObservationOperationNotFound):
            observation_service.read_operation_receipt(
                self.session,
                profile_id="x" * 32,
                request_id=operation.request_id,
            )


    def test_restore_rejects_late_manual_edit(self):
        created = self._create(observation_goal="A")
        observation_id = created["observation_id"]
        version = self._save(observation_id, {"observation_goal": "A"}, reason="manual")
        current = self._current(observation_id)
        preview_request = str(uuid.uuid4())
        preview = observation_history_service.preview_restore(
            self.session,
            self.runtime,
            profile_id=self.profile.id,
            observation_id=observation_id,
            source_version=version["current_version"],
            request_id=preview_request,
            base_draft_revision=current["revision"],
            base_draft_hash=current["payload_hash"],
            term_decision="keep_history",
            now=self.now,
        )
        self._save(observation_id, {"observation_goal": "B"}, reason="manual")
        with self.assertRaises(observation_history_service.ObservationRestorePreviewInvalid):
            observation_history_service.restore_observation(
                self.session,
                self.runtime,
                profile_id=self.profile.id,
                observation_id=observation_id,
                request_id=preview_request,
                restore_token=preview["restore_token"],
                expected_base_revision=current["revision"],
                expected_base_hash=current["payload_hash"],
                term_decision="keep_history",
                now=self.now,
            )
        self.assertEqual(self._current(observation_id)["payload"]["observation_goal"], "B")

    def test_restore_final_short_material_check_rejects_after_verify(self):
        created = self._create(observation_goal="A")
        observation_id = created["observation_id"]
        asset_id = self._import_photo(observation_id, "red")
        version = self._save(
            observation_id,
            {"observation_goal": "A"},
            photos=[{"asset_id": asset_id, "caption": "图"}],
            reason="manual",
        )
        current = self._current(observation_id)
        preview_request = str(uuid.uuid4())
        preview = observation_history_service.preview_restore(
            self.session,
            self.runtime,
            profile_id=self.profile.id,
            observation_id=observation_id,
            source_version=version["current_version"],
            request_id=preview_request,
            base_draft_revision=current["revision"],
            base_draft_hash=current["payload_hash"],
            term_decision="keep_history",
            now=self.now,
        )
        asset = self.session.get(LocalObservationAsset, asset_id)
        asset_path = self.runtime.data_dir / asset.relative_path
        real_verify = observation_history_service._verify_material
        blue = io.BytesIO()
        Image.new("RGB", (40, 30), "blue").save(blue, "JPEG", quality=90)

        def verify_then_change(*args, **kwargs):
            snapshots = real_verify(*args, **kwargs)
            asset_path.write_bytes(blue.getvalue())
            return snapshots

        with mock.patch.object(
            observation_history_service, "_verify_material", side_effect=verify_then_change
        ):
            with self.assertRaises(observation_history_service.ObservationRestoreSourceInvalid):
                observation_history_service.restore_observation(
                    self.session,
                    self.runtime,
                    profile_id=self.profile.id,
                    observation_id=observation_id,
                    request_id=preview_request,
                    restore_token=preview["restore_token"],
                    expected_base_revision=current["revision"],
                    expected_base_hash=current["payload_hash"],
                    term_decision="keep_history",
                    now=self.now,
                )
        self.assertEqual(self._current(observation_id)["payload"]["observation_goal"], "A")


    def test_restore_preview_source_hash_binding_is_rechecked(self):
        created = observation_service.create_observation(
            self.session,
            profile_id=self.profile.id,
            request_id=str(uuid.uuid4()),
            record_type="public",
            payload={"record_type": "public", "observation_date": None},
            now=self.now,
        )
        observation_id = created["observation_id"]
        version = self._save(observation_id, {"observation_date": None}, reason="manual")
        current = self._current(observation_id)
        preview_request = str(uuid.uuid4())
        preview = observation_history_service.preview_restore(
            self.session,
            self.runtime,
            profile_id=self.profile.id,
            observation_id=observation_id,
            source_version=version["current_version"],
            request_id=preview_request,
            base_draft_revision=current["revision"],
            base_draft_hash=current["payload_hash"],
            term_decision="keep_history",
            now=self.now,
        )
        row = self.session.scalars(
            select(LocalObservationRestorePreview).where(
                LocalObservationRestorePreview.observation_id == observation_id
            )
        ).one()
        row.source_hash = "0" * 64
        self.session.commit()
        with self.assertRaises(observation_history_service.ObservationRestorePreviewInvalid):
            observation_history_service.restore_observation(
                self.session,
                self.runtime,
                profile_id=self.profile.id,
                observation_id=observation_id,
                request_id=preview_request,
                restore_token=preview["restore_token"],
                expected_base_revision=current["revision"],
                expected_base_hash=current["payload_hash"],
                term_decision="keep_history",
                now=self.now,
            )
        self.assertEqual(self._current(observation_id)["payload"]["observation_date"], None)

    def test_restore_final_short_check_rejects_after_material_verification(self):
        created = self._create(observation_goal="A")
        observation_id = created["observation_id"]
        asset_id = self._import_photo(observation_id, "red")
        version = self._save(
            observation_id,
            {"observation_goal": "A"},
            photos=[{"asset_id": asset_id, "caption": "图"}],
            reason="manual",
        )
        current = self._current(observation_id)
        preview_request = str(uuid.uuid4())
        preview = observation_history_service.preview_restore(
            self.session,
            self.runtime,
            profile_id=self.profile.id,
            observation_id=observation_id,
            source_version=version["current_version"],
            request_id=preview_request,
            base_draft_revision=current["revision"],
            base_draft_hash=current["payload_hash"],
            term_decision="keep_history",
            now=self.now,
        )
        asset = self.session.get(LocalObservationAsset, asset_id)
        asset_path = self.runtime.data_dir / asset.relative_path
        blue = io.BytesIO()
        Image.new("RGB", (40, 30), "blue").save(blue, "JPEG", quality=90)
        real_verify = observation_history_service._verify_material

        def verify_then_change(*args, **kwargs):
            snapshots = real_verify(*args, **kwargs)
            asset_path.write_bytes(blue.getvalue())
            return snapshots

        with mock.patch.object(
            observation_history_service, "_verify_material", side_effect=verify_then_change
        ):
            with self.assertRaises(observation_history_service.ObservationRestoreSourceInvalid):
                observation_history_service.restore_observation(
                    self.session,
                    self.runtime,
                    profile_id=self.profile.id,
                    observation_id=observation_id,
                    request_id=preview_request,
                    restore_token=preview["restore_token"],
                    expected_base_revision=current["revision"],
                    expected_base_hash=current["payload_hash"],
                    term_decision="keep_history",
                    now=self.now,
                )
        self.assertEqual(self._current(observation_id)["payload"]["observation_goal"], "A")


    def test_history_queries_do_not_load_all_payloads(self):
        created = self._create(observation_goal="A")
        observation_id = created["observation_id"]
        for value in ("B", "C", "D"):
            self._save(observation_id, {"observation_goal": value}, reason="manual")
        statements: list[str] = []

        def capture(_conn, _cursor, statement, _params, _ctx, _many):
            statements.append(" ".join(statement.split()))

        event.listen(self.runtime.engine, "before_cursor_execute", capture)
        try:
            observation_history_service.list_history(
                self.session,
                profile_id=self.profile.id,
                observation_id=observation_id,
            )
            history_statements = list(statements)
            statements.clear()
            self._current(observation_id)
            current_statements = list(statements)
        finally:
            event.remove(self.runtime.engine, "before_cursor_execute", capture)
        self.assertFalse(any("payload_json" in sql for sql in history_statements))
        self.assertTrue(
            any(
                "local_observation_versions" in sql and "LIMIT" in sql
                for sql in current_statements
            ),
            current_statements,
        )


    def test_restore_expiry_rechecked_at_final_lock_clock(self):
        created = self._create(observation_goal="A")
        observation_id = created["observation_id"]
        version = self._save(observation_id, {"observation_goal": "A"}, reason="manual")
        current = self._current(observation_id)
        preview_request = str(uuid.uuid4())
        preview = observation_history_service.preview_restore(
            self.session,
            self.runtime,
            profile_id=self.profile.id,
            observation_id=observation_id,
            source_version=version["current_version"],
            request_id=preview_request,
            base_draft_revision=current["revision"],
            base_draft_hash=current["payload_hash"],
            term_decision="keep_history",
            now=self.now,
        )
        with self.assertRaises(observation_history_service.ObservationRestorePreviewExpired):
            observation_history_service.restore_observation(
                self.session,
                self.runtime,
                profile_id=self.profile.id,
                observation_id=observation_id,
                request_id=preview_request,
                restore_token=preview["restore_token"],
                expected_base_revision=current["revision"],
                expected_base_hash=current["payload_hash"],
                term_decision="keep_history",
                now=self.now,
                clock=lambda: self.now
                + timedelta(
                    seconds=observation_history_service.RESTORE_PREVIEW_TTL_SECONDS
                    + 1
                ),
            )
        self.assertEqual(self._current(observation_id)["revision"], current["revision"])

    def test_restore_rechecks_asset_row_after_material_verification(self):
        created = self._create(observation_goal="A")
        observation_id = created["observation_id"]
        asset_id = self._import_photo(observation_id, "red")
        version = self._save(
            observation_id,
            {"observation_goal": "A"},
            photos=[{"asset_id": asset_id, "caption": "图"}],
            reason="manual",
        )
        current = self._current(observation_id)
        preview_request = str(uuid.uuid4())
        preview = observation_history_service.preview_restore(
            self.session,
            self.runtime,
            profile_id=self.profile.id,
            observation_id=observation_id,
            source_version=version["current_version"],
            request_id=preview_request,
            base_draft_revision=current["revision"],
            base_draft_hash=current["payload_hash"],
            term_decision="keep_history",
            now=self.now,
        )
        real_verify = observation_history_service._verify_material

        def verify_then_change_db(*args, **kwargs):
            snapshots = real_verify(*args, **kwargs)
            asset = self.session.get(LocalObservationAsset, asset_id)
            asset.relative_path = "observations/assets/other/asset/original.jpg"
            self.session.commit()
            return snapshots

        with mock.patch.object(
            observation_history_service, "_verify_material", side_effect=verify_then_change_db
        ):
            with self.assertRaises(observation_history_service.ObservationRestoreSourceInvalid):
                observation_history_service.restore_observation(
                    self.session,
                    self.runtime,
                    profile_id=self.profile.id,
                    observation_id=observation_id,
                    request_id=preview_request,
                    restore_token=preview["restore_token"],
                    expected_base_revision=current["revision"],
                    expected_base_hash=current["payload_hash"],
                    term_decision="keep_history",
                    now=self.now,
                )
        self.assertEqual(self._current(observation_id)["payload"]["observation_goal"], "A")

    def test_restore_term_config_change_invalidates_preview(self):
        created = self._create(observation_goal="A")
        observation_id = created["observation_id"]
        version = self._save(observation_id, {"observation_goal": "A"}, reason="manual")
        current = self._current(observation_id)
        preview_request = str(uuid.uuid4())
        preview = observation_history_service.preview_restore(
            self.session,
            self.runtime,
            profile_id=self.profile.id,
            observation_id=observation_id,
            source_version=version["current_version"],
            request_id=preview_request,
            base_draft_revision=current["revision"],
            base_draft_hash=current["payload_hash"],
            term_decision="keep_history",
            now=self.now,
        )
        term_id = current["payload"]["term_id"]
        term = self.session.get(LocalTerm, term_id)
        term.end_date = term.end_date + timedelta(days=1)
        self.session.commit()
        with self.assertRaises(observation_history_service.ObservationRestorePreviewInvalid):
            observation_history_service.restore_observation(
                self.session,
                self.runtime,
                profile_id=self.profile.id,
                observation_id=observation_id,
                request_id=preview_request,
                restore_token=preview["restore_token"],
                expected_base_revision=current["revision"],
                expected_base_hash=current["payload_hash"],
                term_decision="keep_history",
                now=self.now,
            )


    def test_all_save_reasons_and_noop_rules(self):
        created = self._create(observation_goal="A")
        observation_id = created["observation_id"]
        self._save(observation_id, {"observation_goal": "A"}, reason="manual")
        auto = self._save(observation_id, {"observation_goal": "B"}, reason="auto")
        self.assertFalse(auto["history_created"])
        manual = self._save(observation_id, {"observation_goal": "B"}, reason="manual")
        self.assertTrue(manual["history_created"])
        leave = self._save(observation_id, {"observation_goal": "C"}, reason="leave")
        self.assertTrue(leave["history_created"])
        pre_restore = self._save(
            observation_id, {"observation_goal": "D"}, reason="pre_restore"
        )
        self.assertTrue(pre_restore["history_created"])
        pre_export = self._save(
            observation_id, {"observation_goal": "E"}, reason="pre_export"
        )
        self.assertTrue(pre_export["history_created"])
        noop = self._save(observation_id, {"observation_goal": "E"}, reason="manual")
        self.assertFalse(noop["changed"])
        self.assertFalse(noop["history_created"])
        versions = observation_history_service.list_history(
            self.session,
            profile_id=self.profile.id,
            observation_id=observation_id,
        )
        self.assertEqual([row["version"] for row in versions], [5, 4, 3, 2, 1])

    def test_restore_full_payload_and_photo_manifest(self):
        created = self._create(
            observation_goal="目标",
            observation_process="记录",
            support_strategy="支持",
            subjects=[{"name": "小明"}, {"name": "小红"}],
            age_years=5,
            adult_count=2,
            child_count=8,
            environment="室内",
            analysis_evaluation={
                "health": "健康",
                "language": "语言",
                "social": "社会",
                "science": "科学",
                "arts": "艺术",
            },
        )
        observation_id = created["observation_id"]
        first = self._import_photo(observation_id, "red")
        second = self._import_photo(observation_id, "blue")
        version = self._save(
            observation_id,
            {"observation_goal": "目标", "observation_process": "记录"},
            photos=[
                {"asset_id": second, "caption": "第二"},
                {"asset_id": first, "caption": "第一"},
            ],
            reason="manual",
        )
        self._save(
            observation_id,
            {"observation_goal": "后来"},
            photos=[{"asset_id": first, "caption": "第一"}],
            reason="auto",
        )
        self._save(
            observation_id,
            {"observation_goal": "后来"},
            photos=[{"asset_id": first, "caption": "第一"}],
            reason="pre_restore",
        )
        current = self._current(observation_id)
        preview_request = str(uuid.uuid4())
        preview = observation_history_service.preview_restore(
            self.session,
            self.runtime,
            profile_id=self.profile.id,
            observation_id=observation_id,
            source_version=version["current_version"],
            request_id=preview_request,
            base_draft_revision=current["revision"],
            base_draft_hash=current["payload_hash"],
            term_decision="keep_history",
            now=self.now,
        )
        restored = observation_history_service.restore_observation(
            self.session,
            self.runtime,
            profile_id=self.profile.id,
            observation_id=observation_id,
            request_id=preview_request,
            restore_token=preview["restore_token"],
            expected_base_revision=current["revision"],
            expected_base_hash=current["payload_hash"],
            term_decision="keep_history",
            now=self.now,
        )
        self.assertTrue(restored["changed"])
        current = self._current(observation_id)
        self.assertEqual(current["payload"]["observation_goal"], "目标")
        self.assertEqual(current["payload"]["observation_process"], "记录")
        self.assertEqual(current["payload"]["subjects"], [{"name": "小明"}, {"name": "小红"}])
        self.assertEqual(current["payload"]["analysis_evaluation"]["arts"], "艺术")
        self.assertEqual(
            [photo["asset_id"] for photo in current["photos"]], [second, first]
        )
        self.assertEqual(
            [photo["caption"] for photo in current["photos"]], ["第二", "第一"]
        )

    def test_restore_trigger_rollback_keeps_token_and_current(self):
        created = self._create(observation_goal="A")
        observation_id = created["observation_id"]
        first = self._save(observation_id, {"observation_goal": "A"}, reason="manual")
        second = self._save(observation_id, {"observation_goal": "B"}, reason="manual")
        current = self._current(observation_id)
        preview_request = str(uuid.uuid4())
        preview = observation_history_service.preview_restore(
            self.session,
            self.runtime,
            profile_id=self.profile.id,
            observation_id=observation_id,
            source_version=first["current_version"],
            request_id=preview_request,
            base_draft_revision=current["revision"],
            base_draft_hash=current["payload_hash"],
            term_decision="keep_history",
            now=self.now,
        )
        self.session.execute(
            text(
                "CREATE TRIGGER e0508_restore_abort "
                "BEFORE INSERT ON local_observation_versions "
                "BEGIN SELECT RAISE(ABORT, 'synthetic'); END"
            )
        )
        self.session.commit()
        try:
            with self.assertRaises(observation_service.ObservationStorageError):
                observation_history_service.restore_observation(
                    self.session,
                    self.runtime,
                    profile_id=self.profile.id,
                    observation_id=observation_id,
                    request_id=preview_request,
                    restore_token=preview["restore_token"],
                    expected_base_revision=current["revision"],
                    expected_base_hash=current["payload_hash"],
                    term_decision="keep_history",
                    now=self.now,
                )
        finally:
            self.session.execute(text("DROP TRIGGER e0508_restore_abort"))
            self.session.commit()
        self.assertEqual(self._current(observation_id)["payload"]["observation_goal"], "B")
        self.assertEqual(self._current(observation_id)["current_version"], second["current_version"])
        self.assertEqual(
            len(
                self.session.scalars(
                    select(LocalObservationVersion).where(
                        LocalObservationVersion.observation_id == observation_id
                    )
                ).all()
            ),
            2,
        )
        self.assertEqual(
            self.session.scalars(
                select(LocalObservationRestore).where(
                    LocalObservationRestore.observation_id == observation_id
                )
            ).all(),
            [],
        )
        preview_row = self.session.scalars(
            select(LocalObservationRestorePreview).where(
                LocalObservationRestorePreview.observation_id == observation_id
            )
        ).one()
        self.assertIsNone(preview_row.consumed_at)
        retry = observation_history_service.restore_observation(
            self.session,
            self.runtime,
            profile_id=self.profile.id,
            observation_id=observation_id,
            request_id=preview_request,
            restore_token=preview["restore_token"],
            expected_base_revision=current["revision"],
            expected_base_hash=current["payload_hash"],
            term_decision="keep_history",
            now=self.now,
        )
        self.assertTrue(retry["changed"])
        self.assertEqual(self._current(observation_id)["payload"]["observation_goal"], "A")


    def test_cross_process_save_commit_before_commit_and_replay(self):
        created = self._create(observation_goal="A")
        observation_id = created["observation_id"]
        profile_id = self.profile.id
        data_dir = self.data_dir
        self.session.close()
        self.runtime.dispose()
        self.runtime = None
        self.session = None

        def spec(action: str, **extra):
            value = self.worker_spec(
                action, data_dir=data_dir, connect_only=False
            )
            value.update(extra)
            return value

        def crash(value):
            process = self.spawn_worker(value)
            stdout, stderr = process.communicate(timeout=120)
            return process.returncode, stderr.decode("utf-8", "replace")

        def reopen():
            self.runtime = self.make_runtime(data_dir)
            self.session = self.runtime.session()
            self.profile = self.session.scalars(select(LocalProfile)).one()

        request_id = str(uuid.uuid4())
        committed_spec = spec(
            "observation_service_save",
            profile_id=profile_id,
            observation_id=observation_id,
            request_id=request_id,
            expected_revision=1,
            payload={"observation_goal": "B"},
            save_reason="auto",
            exit_mode="after_commit",
        )
        rc, stderr = crash(committed_spec)
        self.assertEqual(rc, 17, stderr)
        reopen()
        self.assertEqual(self._current(observation_id)["payload"]["observation_goal"], "B")
        self.assertEqual(self._current(observation_id)["revision"], 2)

        read_spec = spec(
            "observation_service_read",
            profile_id=profile_id,
            observation_id=observation_id,
        )
        self.session.close()
        self.runtime.dispose()
        self.runtime = None
        self.session = None
        read = self.run_worker(read_spec)
        self.assertEqual(read["current"]["payload"]["observation_goal"], "B")
        reopen()

        replay_spec = spec(
            "observation_service_save",
            profile_id=profile_id,
            observation_id=observation_id,
            request_id=request_id,
            expected_revision=1,
            payload={"observation_goal": "B"},
            save_reason="auto",
        )
        self.session.close()
        self.runtime.dispose()
        self.runtime = None
        self.session = None
        replay = self.run_worker(replay_spec)["result"]
        reopen()
        self.assertEqual(replay["revision"], 2)
        self.assertEqual(self._current(observation_id)["revision"], 2)

        before_spec = spec(
            "observation_service_save",
            profile_id=profile_id,
            observation_id=observation_id,
            request_id=str(uuid.uuid4()),
            expected_revision=2,
            payload={"observation_goal": "C"},
            save_reason="auto",
            exit_mode="before_commit",
        )
        self.session.close()
        self.runtime.dispose()
        self.runtime = None
        self.session = None
        rc, stderr = crash(before_spec)
        self.assertEqual(rc, 17, stderr)
        reopen()
        self.assertEqual(self._current(observation_id)["payload"]["observation_goal"], "B")
        self.assertEqual(self._current(observation_id)["revision"], 2)


    def test_keep_current_outside_range_is_warning_and_previewable(self):
        created = self._create(observation_goal="A")
        observation_id = created["observation_id"]
        self._save(observation_id, {"observation_goal": "A"}, reason="manual")
        current = self._current(observation_id)
        moved = observation_service.save_observation(
            self.session,
            profile_id=self.profile.id,
            observation_id=observation_id,
            request_id=str(uuid.uuid4()),
            expected_revision=current["revision"],
            payload={"observation_date": "2026-10-15"},
            save_reason="manual",
            term_decision="keep_current",
            now=self.now,
        )
        self.assertIn("date_outside_current_term", moved["term_warnings"])
        current = self._current(observation_id)
        preview = observation_history_service.preview_restore(
            self.session,
            self.runtime,
            profile_id=self.profile.id,
            observation_id=observation_id,
            source_version=current["current_version"],
            request_id=str(uuid.uuid4()),
            base_draft_revision=current["revision"],
            base_draft_hash=current["payload_hash"],
            term_decision="keep_current",
            now=self.now,
        )
        self.assertIn("date_outside_current_term", preview["warnings"])


    def test_restore_binds_source_term_configuration_when_current_is_unassigned(self):
        created = self._create(observation_goal="A")
        observation_id = created["observation_id"]
        version = self._save(observation_id, {"observation_goal": "A"}, reason="manual")
        current = self._current(observation_id)
        self._save(
            observation_id,
            {"observation_date": None},
            reason="manual",
            term_decision="unassigned",
        )
        current = self._current(observation_id)
        preview_request = str(uuid.uuid4())
        preview = observation_history_service.preview_restore(
            self.session,
            self.runtime,
            profile_id=self.profile.id,
            observation_id=observation_id,
            source_version=version["current_version"],
            request_id=preview_request,
            base_draft_revision=current["revision"],
            base_draft_hash=current["payload_hash"],
            term_decision="keep_history",
            now=self.now,
        )
        source_term_id = version["current_version"] and self.session.scalars(
            select(LocalObservationVersion).where(
                LocalObservationVersion.observation_id == observation_id,
                LocalObservationVersion.version == version["current_version"],
            )
        ).one().payload_json["term_id"]
        term = self.session.get(LocalTerm, source_term_id)
        term.end_date = term.end_date - timedelta(days=20)
        self.session.commit()
        with self.assertRaises(observation_history_service.ObservationRestoreSourceInvalid):
            observation_history_service.restore_observation(
                self.session,
                self.runtime,
                profile_id=self.profile.id,
                observation_id=observation_id,
                request_id=preview_request,
                restore_token=preview["restore_token"],
                expected_base_revision=current["revision"],
                expected_base_hash=current["payload_hash"],
                term_decision="keep_history",
                now=self.now,
            )
        with self.assertRaises(observation_history_service.ObservationRestoreSourceInvalid):
            observation_history_service.preview_restore(
                self.session,
                self.runtime,
                profile_id=self.profile.id,
                observation_id=observation_id,
                source_version=version["current_version"],
                request_id=str(uuid.uuid4()),
                base_draft_revision=current["revision"],
                base_draft_hash=current["payload_hash"],
                term_decision="keep_history",
                now=self.now,
            )
        self.assertEqual(self._current(observation_id)["payload"]["term_id"], None)

    def test_restore_rejects_expanded_asset_without_unbounded_read(self):
        created = self._create(observation_goal="A")
        observation_id = created["observation_id"]
        asset_id = self._import_photo(observation_id, "red")
        version = self._save(
            observation_id,
            {"observation_goal": "A"},
            photos=[{"asset_id": asset_id, "caption": "图"}],
            reason="manual",
        )
        current = self._current(observation_id)
        preview_request = str(uuid.uuid4())
        preview = observation_history_service.preview_restore(
            self.session,
            self.runtime,
            profile_id=self.profile.id,
            observation_id=observation_id,
            source_version=version["current_version"],
            request_id=preview_request,
            base_draft_revision=current["revision"],
            base_draft_hash=current["payload_hash"],
            term_decision="keep_history",
            now=self.now,
        )
        asset = self.session.get(LocalObservationAsset, asset_id)
        asset_path = self.runtime.data_dir / asset.relative_path
        with asset_path.open("r+b") as handle:
            handle.truncate(25 * 1024 * 1024 + 1)
        with self.assertRaises(observation_history_service.ObservationRestoreSourceInvalid):
            observation_history_service.restore_observation(
                self.session,
                self.runtime,
                profile_id=self.profile.id,
                observation_id=observation_id,
                request_id=preview_request,
                restore_token=preview["restore_token"],
                expected_base_revision=current["revision"],
                expected_base_hash=current["payload_hash"],
                term_decision="keep_history",
                now=self.now,
            )
        self.assertEqual(self._current(observation_id)["payload"]["observation_goal"], "A")


    def test_restore_late_audit_trigger_rolls_back_all_and_allows_retry(self):
        created = self._create(observation_goal="A")
        observation_id = created["observation_id"]
        first = self._save(observation_id, {"observation_goal": "A"}, reason="manual")
        second = self._save(observation_id, {"observation_goal": "B"}, reason="manual")
        current = self._current(observation_id)
        before_versions = len(
            self.session.scalars(
                select(LocalObservationVersion).where(
                    LocalObservationVersion.observation_id == observation_id
                )
            ).all()
        )
        preview_request = str(uuid.uuid4())
        preview = observation_history_service.preview_restore(
            self.session,
            self.runtime,
            profile_id=self.profile.id,
            observation_id=observation_id,
            source_version=first["current_version"],
            request_id=preview_request,
            base_draft_revision=current["revision"],
            base_draft_hash=current["payload_hash"],
            term_decision="keep_history",
            now=self.now,
        )
        self.session.execute(
            text(
                "CREATE TRIGGER e0508_late_restore_abort "
                "BEFORE INSERT ON local_operation_records "
                "WHEN NEW.action = 'observation_restore' "
                "BEGIN SELECT RAISE(ABORT, 'synthetic late'); END"
            )
        )
        self.session.commit()
        try:
            with self.assertRaises(observation_service.ObservationStorageError):
                observation_history_service.restore_observation(
                    self.session,
                    self.runtime,
                    profile_id=self.profile.id,
                    observation_id=observation_id,
                    request_id=preview_request,
                    restore_token=preview["restore_token"],
                    expected_base_revision=current["revision"],
                    expected_base_hash=current["payload_hash"],
                    term_decision="keep_history",
                    now=self.now,
                )
        finally:
            self.session.execute(text("DROP TRIGGER e0508_late_restore_abort"))
            self.session.commit()
        self.assertEqual(self._current(observation_id)["payload"]["observation_goal"], "B")
        self.assertEqual(
            len(
                self.session.scalars(
                    select(LocalObservationVersion).where(
                        LocalObservationVersion.observation_id == observation_id
                    )
                ).all()
            ),
            before_versions,
        )
        self.assertEqual(
            len(
                self.session.scalars(
                    select(LocalObservationRestore).where(
                        LocalObservationRestore.observation_id == observation_id
                    )
                ).all()
            ),
            0,
        )
        preview_row = self.session.scalars(
            select(LocalObservationRestorePreview).where(
                LocalObservationRestorePreview.observation_id == observation_id
            )
        ).one()
        self.assertIsNone(preview_row.consumed_at)
        retry = observation_history_service.restore_observation(
            self.session,
            self.runtime,
            profile_id=self.profile.id,
            observation_id=observation_id,
            request_id=preview_request,
            restore_token=preview["restore_token"],
            expected_base_revision=current["revision"],
            expected_base_hash=current["payload_hash"],
            term_decision="keep_history",
            now=self.now,
        )
        self.assertTrue(retry["changed"])


    def test_concurrent_same_restore_returns_same_receipt_and_one_result(self):
        created = self._create(observation_goal="A")
        observation_id = created["observation_id"]
        first = self._save(observation_id, {"observation_goal": "A"}, reason="manual")
        self._save(observation_id, {"observation_goal": "B"}, reason="manual")
        current = self._current(observation_id)
        preview_request = str(uuid.uuid4())
        preview = observation_history_service.preview_restore(
            self.session,
            self.runtime,
            profile_id=self.profile.id,
            observation_id=observation_id,
            source_version=first["current_version"],
            request_id=preview_request,
            base_draft_revision=current["revision"],
            base_draft_hash=current["payload_hash"],
            term_decision="keep_history",
            now=self.now,
        )
        real_preview_by_token = observation_history_service._preview_by_token
        nested = {"result": None, "entered": False}

        def concurrent_preview_by_token(session, token, profile_id, observation_id):
            if not nested["entered"]:
                nested["entered"] = True
                other = self.runtime.session()
                try:
                    nested["result"] = observation_history_service.restore_observation(
                        other,
                        self.runtime,
                        profile_id=profile_id,
                        observation_id=observation_id,
                        request_id=preview_request,
                        restore_token=preview["restore_token"],
                        expected_base_revision=current["revision"],
                        expected_base_hash=current["payload_hash"],
                        term_decision="keep_history",
                        now=self.now,
                    )
                finally:
                    other.close()
            return real_preview_by_token(session, token, profile_id, observation_id)

        with mock.patch.object(
            observation_history_service,
            "_preview_by_token",
            side_effect=concurrent_preview_by_token,
        ):
            result = observation_history_service.restore_observation(
                self.session,
                self.runtime,
                profile_id=self.profile.id,
                observation_id=observation_id,
                request_id=preview_request,
                restore_token=preview["restore_token"],
                expected_base_revision=current["revision"],
                expected_base_hash=current["payload_hash"],
                term_decision="keep_history",
                now=self.now,
            )
        self.assertEqual(result, nested["result"])
        self.assertEqual(
            len(
                self.session.scalars(
                    select(LocalObservationVersion).where(
                        LocalObservationVersion.observation_id == observation_id
                    )
                ).all()
            ),
            3,
        )
        self.assertEqual(
            len(
                self.session.scalars(
                    select(LocalObservationRestore).where(
                        LocalObservationRestore.observation_id == observation_id
                    )
                ).all()
            ),
            1,
        )


    def test_cross_process_restore_after_commit_and_before_commit(self):
        created = self._create(observation_goal="A")
        observation_id = created["observation_id"]
        first = self._save(observation_id, {"observation_goal": "A"}, reason="manual")
        second = self._save(observation_id, {"observation_goal": "B"}, reason="manual")
        current = self._current(observation_id)
        preview_request = str(uuid.uuid4())
        preview = observation_history_service.preview_restore(
            self.session,
            self.runtime,
            profile_id=self.profile.id,
            observation_id=observation_id,
            source_version=first["current_version"],
            request_id=preview_request,
            base_draft_revision=current["revision"],
            base_draft_hash=current["payload_hash"],
            term_decision="keep_history",
            now=self.now,
        )
        profile_id = self.profile.id
        data_dir = self.data_dir
        self.session.close()
        self.runtime.dispose()
        self.runtime = None
        self.session = None

        def spec(action: str, **extra):
            value = self.worker_spec(action, data_dir=data_dir, connect_only=False)
            value.update(extra)
            return value

        def crash(value):
            process = self.spawn_worker(value)
            stdout, stderr = process.communicate(timeout=120)
            return process.returncode, stderr.decode("utf-8", "replace")

        def reopen():
            self.runtime = self.make_runtime(data_dir)
            self.session = self.runtime.session()
            self.profile = self.session.scalars(select(LocalProfile)).one()

        committed = spec(
            "observation_service_restore",
            profile_id=profile_id,
            observation_id=observation_id,
            request_id=preview_request,
            restore_token=preview["restore_token"],
            expected_base_revision=current["revision"],
            expected_base_hash=current["payload_hash"],
            term_decision="keep_history",
            exit_mode="after_commit",
        )
        rc, stderr = crash(committed)
        self.assertEqual(rc, 17, stderr)
        reopen()
        self.assertEqual(self._current(observation_id)["payload"]["observation_goal"], "A")
        self.assertEqual(self._current(observation_id)["revision"], current["revision"] + 1)

        next_source = second["current_version"]
        next_current = self._current(observation_id)
        next_request = str(uuid.uuid4())
        next_preview = observation_history_service.preview_restore(
            self.session,
            self.runtime,
            profile_id=profile_id,
            observation_id=observation_id,
            source_version=next_source,
            request_id=next_request,
            base_draft_revision=next_current["revision"],
            base_draft_hash=next_current["payload_hash"],
            term_decision="keep_history",
            now=self.now,
        )
        self.session.close()
        self.runtime.dispose()
        self.runtime = None
        self.session = None
        failed = spec(
            "observation_service_restore",
            profile_id=profile_id,
            observation_id=observation_id,
            request_id=next_request,
            restore_token=next_preview["restore_token"],
            expected_base_revision=next_current["revision"],
            expected_base_hash=next_current["payload_hash"],
            term_decision="keep_history",
            exit_mode="before_commit",
        )
        rc, stderr = crash(failed)
        self.assertEqual(rc, 17, stderr)
        reopen()
        self.assertEqual(self._current(observation_id)["payload"]["observation_goal"], "A")
        self.assertEqual(self._current(observation_id)["revision"], next_current["revision"])
        self._preserve_evidence(
            "r08-cross-process-restore",
            {
                "revision": self._current(observation_id)["revision"],
                "current_version": self._current(observation_id)["current_version"],
                "payload_hash": self._current(observation_id)["payload_hash"],
                "history": observation_history_service.list_history(
                    self.session,
                    profile_id=profile_id,
                    observation_id=observation_id,
                ),
                "receipts": len(
                    self.session.scalars(select(LocalObservationOperation)).all()
                ),
            },
        )


    def test_create_explicit_term_outside_range_warns_without_blocking(self):
        term_id = self.session.scalars(select(LocalTerm)).one().id
        request_id = str(uuid.uuid4())
        created = observation_service.create_observation(
            self.session,
            profile_id=self.profile.id,
            request_id=request_id,
            record_type="public",
            payload={
                "record_type": "public",
                "observation_date": "2026-10-15",
                "term_id": term_id,
            },
            now=self.now,
        )
        self.assertEqual(created["term_warnings"], ["date_outside_selected_term"])
        self.assertEqual(
            self._current(created["observation_id"])["payload"]["term_id"], term_id
        )
        replay = observation_service.create_observation(
            self.session,
            profile_id=self.profile.id,
            request_id=request_id,
            record_type="public",
            payload={
                "record_type": "public",
                "observation_date": "2026-10-15",
                "term_id": term_id,
            },
            now=self.now,
        )
        self.assertEqual(replay["term_warnings"], ["date_outside_selected_term"])
        inside = observation_service.create_observation(
            self.session,
            profile_id=self.profile.id,
            request_id=str(uuid.uuid4()),
            record_type="public",
            payload={
                "record_type": "public",
                "observation_date": "2026-09-15",
                "term_id": term_id,
            },
            now=self.now,
        )
        self.assertEqual(inside["term_warnings"], [])
        undated = observation_service.create_observation(
            self.session,
            profile_id=self.profile.id,
            request_id=str(uuid.uuid4()),
            record_type="public",
            payload={"record_type": "public", "observation_date": None, "term_id": term_id},
            now=self.now,
        )
        self.assertEqual(undated["term_warnings"], [])


    def test_restore_late_all_flush_fault_and_evidence(self):
        created = self._create(observation_goal="A")
        observation_id = created["observation_id"]
        asset_id = self._import_photo(observation_id, "red")
        first = self._save(
            observation_id,
            {"observation_goal": "A"},
            photos=[{"asset_id": asset_id, "caption": "历史图"}],
            reason="manual",
        )
        self._save(
            observation_id,
            {"observation_goal": "B"},
            photos=[{"asset_id": asset_id, "caption": "历史图"}],
            reason="manual",
        )
        current = self._current(observation_id)
        preview_request = str(uuid.uuid4())
        preview = observation_history_service.preview_restore(
            self.session,
            self.runtime,
            profile_id=self.profile.id,
            observation_id=observation_id,
            source_version=first["current_version"],
            request_id=preview_request,
            base_draft_revision=current["revision"],
            base_draft_hash=current["payload_hash"],
            term_decision="keep_history",
            now=self.now,
        )
        before = {
            "draft_revision": current["revision"],
            "draft_hash": current["payload_hash"],
            "current_version": current["current_version"],
            "versions": len(self.session.scalars(select(LocalObservationVersion).where(
                LocalObservationVersion.observation_id == observation_id)).all()),
            "version_photos": len(self.session.scalars(select(LocalObservationVersionPhoto)).all()),
            "restores": len(self.session.scalars(select(LocalObservationRestore).where(
                LocalObservationRestore.observation_id == observation_id)).all()),
            "operations": len(self.session.scalars(select(LocalObservationOperation)).all()),
            "audits": len([row for row in self.session.scalars(select(LocalOperationRecord)).all()
                           if row.action.startswith("observation_")]),
        }
        self.session.execute(text("CREATE TABLE e0508_fault (id INTEGER PRIMARY KEY, note TEXT)"))
        self.session.execute(text(
            "CREATE TRIGGER e0508_fault_abort BEFORE INSERT ON e0508_fault "
            "BEGIN SELECT RAISE(ABORT, 'synthetic late all-flush'); END"))
        self.session.commit()
        marker = {}

        def late_fault_commit():
            self.session.flush()
            draft = self.session.get(LocalObservationDraft, observation_id)
            marker.update({
                "draft_revision": draft.revision,
                "draft_hash": draft.payload_hash,
                "current_version": self.session.get(
                    LocalObservationRecord, observation_id
                ).current_version,
                "version_count": len(self.session.scalars(select(LocalObservationVersion).where(
                    LocalObservationVersion.observation_id == observation_id)).all()),
                "version_photo_count": len(self.session.scalars(select(LocalObservationVersionPhoto)).all()),
                "restore_count": len(self.session.scalars(select(LocalObservationRestore).where(
                    LocalObservationRestore.observation_id == observation_id)).all()),
                "operation_count": len(self.session.scalars(select(LocalObservationOperation)).all()),
                "audit_count": len([row for row in self.session.scalars(select(LocalOperationRecord)).all()
                                     if row.action.startswith("observation_")]),
                "token_consumed": self.session.scalars(select(LocalObservationRestorePreview).where(
                    LocalObservationRestorePreview.observation_id == observation_id)).one().consumed_at is not None,
            })
            evidence = os.environ.get("E0508_EVIDENCE_ROOT")
            path = Path(evidence) / "r08-late-stage-marker.json" if evidence else self.tmp_root / "r08-late-stage-marker.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(marker, ensure_ascii=False, indent=2), encoding="utf-8")
            self.session.execute(text("INSERT INTO e0508_fault (note) VALUES ('late-fault')"))

        try:
            with mock.patch.object(self.session, "commit", side_effect=late_fault_commit):
                with self.assertRaises(observation_service.ObservationStorageError):
                    observation_history_service.restore_observation(
                        self.session, self.runtime,
                        profile_id=self.profile.id,
                        observation_id=observation_id,
                        request_id=preview_request,
                        restore_token=preview["restore_token"],
                        expected_base_revision=current["revision"],
                        expected_base_hash=current["payload_hash"],
                        term_decision="keep_history",
                        now=self.now,
                    )
        finally:
            self.session.execute(text("DROP TRIGGER e0508_fault_abort"))
            self.session.execute(text("DROP TABLE e0508_fault"))
            self.session.commit()
        self.assertEqual(marker["draft_revision"], current["revision"] + 1)
        self.assertEqual(marker["version_count"], before["versions"] + 1)
        self.assertEqual(marker["version_photo_count"], before["version_photos"] + 1)
        self.assertEqual(marker["restore_count"], 1)
        self.assertGreater(marker["operation_count"], before["operations"])
        self.assertGreater(marker["audit_count"], before["audits"])
        self.assertTrue(marker["token_consumed"])
        after = self._current(observation_id)
        self.assertEqual(after["revision"], before["draft_revision"])
        self.assertEqual(after["payload_hash"], before["draft_hash"])
        self.assertEqual(after["current_version"], before["current_version"])
        after_counts = {
            "versions": len(self.session.scalars(select(LocalObservationVersion).where(
                LocalObservationVersion.observation_id == observation_id)).all()),
            "version_photos": len(self.session.scalars(select(LocalObservationVersionPhoto)).all()),
            "restores": len(self.session.scalars(select(LocalObservationRestore).where(
                LocalObservationRestore.observation_id == observation_id)).all()),
            "operations": len(self.session.scalars(select(LocalObservationOperation)).all()),
            "audits": len([row for row in self.session.scalars(select(LocalOperationRecord)).all()
                           if row.action.startswith("observation_")]),
        }
        for key, value in after_counts.items():
            self.assertEqual(value, before[key], key)
        preview_row = self.session.scalars(select(LocalObservationRestorePreview).where(
            LocalObservationRestorePreview.observation_id == observation_id)).one()
        self.assertIsNone(preview_row.consumed_at)
        asset = self.session.get(LocalObservationAsset, asset_id)
        photo_summary = {
            "asset_id": asset.id,
            "content_hash": asset.content_hash,
            "file_sha256": hashlib.sha256(
                (self.data_dir / asset.relative_path).read_bytes()
            ).hexdigest(),
        }
        photo_summary["matches"] = (
            photo_summary["content_hash"] == photo_summary["file_sha256"]
        )
        self.assertTrue(photo_summary["matches"])
        self._preserve_evidence(
            "r08-late-stage-fault",
            {
                "marker": marker,
                "before": before,
                "after": after,
                "after_counts": after_counts,
                "original_photo": photo_summary,
            },
        )
        retry = observation_history_service.restore_observation(
            self.session, self.runtime,
            profile_id=self.profile.id,
            observation_id=observation_id,
            request_id=preview_request,
            restore_token=preview["restore_token"],
            expected_base_revision=current["revision"],
            expected_base_hash=current["payload_hash"],
            term_decision="keep_history",
            now=self.now,
        )
        self.assertTrue(retry["changed"])
        self._preserve_evidence(
            "r08-late-stage-retry",
            {
                "retry": retry,
                "after_retry": self._current(observation_id),
                "original_photo": photo_summary,
            },
        )
