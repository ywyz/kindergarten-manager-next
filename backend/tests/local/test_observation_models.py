"""E02 model/source-chain and same-record material constraint tests."""

from __future__ import annotations

import unittest
from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.local import profile_service
from app.local.models import (
    LocalAICandidate,
    LocalAIConfigVersion,
    LocalAIExecution,
    LocalAIInput,
    LocalAITask,
    LocalObservationAIInputPhoto,
    LocalObservationAIProvenance,
    LocalObservationAsset,
    LocalObservationAssetDerivative,
    LocalObservationDraft,
    LocalObservationDraftPhoto,
    LocalObservationExportAttempt,
    LocalObservationExportSnapshot,
    LocalObservationExportToken,
    LocalObservationOperation,
    LocalObservationRecord,
    LocalObservationRestore,
    LocalObservationRestorePreview,
    LocalObservationVersion,
    LocalObservationVersionPhoto,
    LocalProfile,
)
from app.local.normalize import normalize_initialization
from tests.local.support import LocalTestCase, initialize_body, query_rows


class ObservationModelTests(LocalTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.runtime = self.make_runtime()
        self.session = self.runtime.session()
        profile_service.initialize(
            self.session, normalize_initialization(**initialize_body())
        )
        self.session.commit()
        self.profile = self.session.scalars(select(LocalProfile)).one()
        self.now = datetime(2026, 10, 26, 9, 0, 0)
        self.session.add(
            LocalAIConfigVersion(
                profile_id=self.profile.id,
                version=1,
                protocol_id="chat_completions_v1",
                base_url=None,
                model=None,
                credential_id=None,
                created_at=self.now,
            )
        )
        self.session.commit()

    def tearDown(self) -> None:
        self.session.close()
        super().tearDown()

    def _record(self, record_id: str) -> LocalObservationRecord:
        record = LocalObservationRecord(
            id=record_id,
            creator_profile_id=self.profile.id,
            observation_date=None,
            record_type="public",
            start_time=None,
            end_time=None,
            term_id=None,
            term_snapshot_json=None,
            school_name=None,
            class_name=None,
            observer_name=None,
            adult_count=None,
            child_count=None,
            age_years=None,
            subjects_json=[],
            environment=None,
            current_draft_revision=1,
            current_version=None,
            created_at=self.now,
            updated_at=self.now,
        )
        self.session.add(record)
        return record

    def _asset(self, asset_id: str, record_id: str) -> LocalObservationAsset:
        asset = LocalObservationAsset(
            id=asset_id,
            observation_id=record_id,
            relative_path=f"{record_id}/{asset_id}.jpg",
            display_name="a.jpg",
            mime_type="image/jpeg",
            content_hash="b" * 64,
            byte_size=10,
            width=10,
            height=10,
            orientation=1,
            created_at=self.now,
        )
        self.session.add(asset)
        return asset

    def _derivative(
        self, derivative_id: str, record_id: str, asset_id: str
    ) -> LocalObservationAssetDerivative:
        derivative = LocalObservationAssetDerivative(
            id=derivative_id,
            observation_id=record_id,
            asset_id=asset_id,
            purpose="ai",
            params_version="v1",
            content_hash="c" * 64,
            mime_type="image/jpeg",
            width=10,
            height=10,
            relative_path=f"{record_id}/{derivative_id}.jpg",
            created_at=self.now,
        )
        self.session.add(derivative)
        return derivative

    def _input(self, input_id: str, record_id: str) -> LocalAIInput:
        input_row = LocalAIInput(
            id=input_id,
            profile_id=self.profile.id,
            source_kind="game_observation",
            source_id=record_id,
            observation_id=record_id,
            source_revision=1,
            daily_plan_id=None,
            content_id=None,
            content_version=None,
            task_type="game_observation_generate",
            target_grade=None,
            input_schema_version=1,
            payload_json={},
            dependencies_json={},
            dependency_hash="d" * 64,
            target_hashes_json={},
            created_at=self.now,
        )
        self.session.add(input_row)
        return input_row

    def _chain(self, suffix: str = "1") -> dict:
        record_id = f"obs-{suffix}"
        asset_id = f"asset-{suffix}"
        derivative_id = f"deriv-{suffix}"
        input_id = f"input-{suffix}"
        task_id = f"task-{suffix}"
        execution_id = f"exec-{suffix}"
        candidate_id = f"cand-{suffix}"
        version_id = f"ver-{suffix}"
        self._record(record_id)
        self.session.flush()
        self._asset(asset_id, record_id)
        self._derivative(derivative_id, record_id, asset_id)
        self.session.flush()
        version = LocalObservationVersion(
            id=version_id,
            observation_id=record_id,
            version=1,
            payload_json={},
            payload_hash="a" * 64,
            source_kind="manual",
            creator_profile_id=self.profile.id,
            created_at=self.now,
        )
        self.session.add(version)
        self.session.flush()
        record = self.session.get(LocalObservationRecord, record_id)
        record.current_version = 1
        self.session.add(
            LocalObservationDraft(
                observation_id=record_id,
                revision=1,
                payload_json={},
                payload_hash="a" * 64,
                created_at=self.now,
                updated_at=self.now,
            )
        )
        self.session.add(
            LocalObservationDraftPhoto(
                observation_id=record_id,
                asset_id=asset_id,
                sort_order=0,
                caption="说明",
            )
        )
        self.session.add(
            LocalObservationVersionPhoto(
                version_id=version_id,
                asset_id=asset_id,
                observation_id=record_id,
                sort_order=0,
                caption="说明",
            )
        )
        input_row = self._input(input_id, record_id)
        self.session.flush()
        self.session.add(
            LocalObservationAIInputPhoto(
                id=f"input-photo-{suffix}",
                profile_id=self.profile.id,
                source_kind="game_observation",
                source_id=record_id,
                observation_id=record_id,
                input_id=input_id,
                asset_id=asset_id,
                derivative_id=derivative_id,
                sort_order=0,
                caption="说明",
                original_hash="b" * 64,
                work_hash="c" * 64,
            )
        )
        task = LocalAITask(
            id=task_id,
            profile_id=self.profile.id,
            source_kind="game_observation",
            source_id=record_id,
            observation_id=record_id,
            daily_plan_id=None,
            task_type="game_observation_generate",
            input_id=input_id,
            status="succeeded",
            reason=None,
            current_execution_id=None,
            generation=1,
            runtime_meta_json={},
            created_at=self.now,
            updated_at=self.now,
        )
        self.session.add(task)
        self.session.flush()
        execution = LocalAIExecution(
            id=execution_id,
            task_id=task_id,
            source_kind="game_observation",
            source_id=record_id,
            observation_id=record_id,
            daily_plan_id=None,
            input_id=input_id,
            task_type="game_observation_generate",
            generation=1,
            launch_id="launch-1",
            permit_id="permit-1",
            config_version=1,
            profile_id=self.profile.id,
            personal_revision=1,
            contract_version=1,
            default_revision=1,
            state="succeeded",
            runtime_meta_json={},
            started_at=self.now,
            created_at=self.now,
            ended_at=self.now,
        )
        self.session.add(execution)
        self.session.flush()
        candidate = LocalAICandidate(
            id=candidate_id,
            profile_id=self.profile.id,
            execution_id=execution_id,
            task_id=task_id,
            source_kind="game_observation",
            source_id=record_id,
            observation_id=record_id,
            daily_plan_id=None,
            input_id=input_id,
            task_type="game_observation_generate",
            contract_version=1,
            schema_version=1,
            raw_candidate_json={},
            candidate_hash="e" * 64,
            created_at=self.now,
        )
        self.session.add(candidate)
        self.session.flush()
        self.session.add(
            LocalObservationAIProvenance(
                id=f"prov-{suffix}",
                profile_id=self.profile.id,
                source_kind="game_observation",
                source_id=record_id,
                observation_id=record_id,
                version=1,
                candidate_id=candidate_id,
                adopted_targets_json={"observation_goal": "x"},
                input_hash="d" * 64,
                output_hash="e" * 64,
                created_at=self.now,
            )
        )
        operation = LocalObservationOperation(
            id=f"op-{suffix}",
            profile_id=self.profile.id,
            request_id=f"req-{suffix}",
            operation_kind="restore",
            observation_id=record_id,
            request_fingerprint="f" * 64,
            status="committed",
            result_json={},
            created_at=self.now,
        )
        self.session.add(operation)
        self.session.flush()
        self.session.add(
            LocalObservationRestore(
                id=f"restore-{suffix}",
                operation_id=operation.id,
                profile_id=self.profile.id,
                observation_id=record_id,
                source_version=1,
                result_version=1,
                before_draft_revision=1,
                before_version=1,
                changed=0,
                term_decision="keep_history",
                effective_term_id=None,
                effective_payload_hash="a" * 64,
                created_at=self.now,
            )
        )
        self.session.add(
            LocalObservationRestorePreview(
                id=f"preview-{suffix}",
                token_hash=("9" * 63) + suffix,
                profile_id=self.profile.id,
                observation_id=record_id,
                source_version=1,
                source_hash="a" * 64,
                base_draft_revision=1,
                base_draft_hash="a" * 64,
                effective_term_id=None,
                term_snapshot_hash=None,
                effective_payload_hash="a" * 64,
                material_hash="b" * 64,
                request_id=f"preview-req-{suffix}",
                expires_at=datetime(2026, 10, 27),
                created_at=self.now,
            )
        )
        snapshot = LocalObservationExportSnapshot(
            id=f"snap-{suffix}",
            profile_id=self.profile.id,
            launch_id="launch-1",
            session_scope_hash="1" * 64,
            manifest_json={},
            manifest_hash="2" * 64,
            created_at=self.now,
            expires_at=datetime(2026, 10, 27),
        )
        self.session.add(snapshot)
        self.session.flush()
        self.session.add(
            LocalObservationExportToken(
                id=f"token-{suffix}",
                snapshot_id=snapshot.id,
                profile_id=self.profile.id,
                token_hash=("3" * 63) + suffix,
                expires_at=datetime(2026, 10, 27),
                created_at=self.now,
            )
        )
        self.session.add(
            LocalObservationExportAttempt(
                id=f"attempt-{suffix}",
                profile_id=self.profile.id,
                snapshot_id=snapshot.id,
                export_id_hash=("4" * 63) + suffix,
                filename_fingerprint="5" * 64,
                status="saved",
                result_hash="6" * 64,
                byte_size=100,
                started_at=self.now,
                ended_at=self.now,
                created_at=self.now,
            )
        )
        self.session.commit()
        return {
            "record": record_id,
            "asset": asset_id,
            "derivative": derivative_id,
            "input": input_id,
            "task": task_id,
            "execution": execution_id,
            "candidate": candidate_id,
        }

    def test_full_observation_chain_and_record_pointer(self):
        ids = self._chain()
        record = self.session.get(LocalObservationRecord, ids["record"])
        self.assertEqual(record.current_version, 1)
        self.assertEqual(record.current_draft_revision, 1)
        self.assertEqual(self.session.get(LocalAITask, ids["task"]).source_id, ids["record"])
        self.assertEqual(
            self.session.get(LocalAICandidate, ids["candidate"]).observation_id,
            ids["record"],
        )

    def test_cross_record_input_and_task_are_rejected(self):
        ids = self._chain("1")
        self._record("obs-2")
        self.session.commit()
        try:
            self.session.add(
                LocalAIInput(
                    id="bad-input",
                    profile_id=self.profile.id,
                    source_kind="game_observation",
                    source_id="obs-2",
                    observation_id=ids["record"],
                    source_revision=1,
                    daily_plan_id=None,
                    content_id=None,
                    content_version=None,
                    task_type="game_observation_generate",
                    target_grade=None,
                    input_schema_version=1,
                    payload_json={},
                    dependencies_json={},
                    dependency_hash="d" * 64,
                    target_hashes_json={},
                    created_at=self.now,
                )
            )
            self.session.commit()
            self.fail("cross-record source check passed")
        except IntegrityError:
            self.session.rollback()

        try:
            self.session.add(
                LocalAITask(
                    id="bad-task",
                    profile_id=self.profile.id,
                    source_kind="game_observation",
                    source_id="obs-2",
                    observation_id="obs-2",
                    daily_plan_id=None,
                    task_type="game_observation_generate",
                    input_id=ids["input"],
                    status="pending",
                    reason=None,
                    current_execution_id=None,
                    generation=0,
                    runtime_meta_json={},
                    created_at=self.now,
                    updated_at=self.now,
                )
            )
            self.session.commit()
            self.fail("cross-record task FK passed")
        except IntegrityError:
            self.session.rollback()

    def test_wrong_derivative_for_asset_is_rejected(self):
        self._chain("1")
        self._chain("2")
        try:
            self.session.add(
                LocalObservationAIInputPhoto(
                    id="bad-photo",
                    profile_id=self.profile.id,
                    source_kind="game_observation",
                    source_id="obs-1",
                    observation_id="obs-1",
                    input_id="input-1",
                    asset_id="asset-1",
                    derivative_id="deriv-2",
                    sort_order=1,
                    caption=None,
                    original_hash="b" * 64,
                    work_hash="c" * 64,
                )
            )
            self.session.commit()
            self.fail("wrong derivative passed")
        except IntegrityError:
            self.session.rollback()

    def test_duplicate_photo_order_is_rejected(self):
        self._chain("1")
        self._asset("asset-extra", "obs-1")
        self.session.flush()
        try:
            self.session.add(
                LocalObservationDraftPhoto(
                    observation_id="obs-1",
                    asset_id="asset-extra",
                    sort_order=0,
                    caption=None,
                )
            )
            self.session.commit()
            self.fail("duplicate sort order passed")
        except IntegrityError:
            self.session.rollback()

    def test_daily_null_grade_and_observation_daily_fields_are_rejected(self):
        try:
            self.session.add(
                LocalAIInput(
                    id="bad-daily",
                    profile_id=self.profile.id,
                    source_kind="daily_plan",
                    source_id="plan-x",
                    observation_id=None,
                    source_revision=None,
                    daily_plan_id="plan-x",
                    content_id="content-x",
                    content_version=1,
                    task_type="daily_lesson_split",
                    target_grade=None,
                    input_schema_version=1,
                    payload_json={},
                    dependencies_json={},
                    dependency_hash="d" * 64,
                    target_hashes_json={},
                    created_at=self.now,
                )
            )
            self.session.commit()
            self.fail("daily null grade passed")
        except IntegrityError:
            self.session.rollback()

    def test_record_pointer_must_reference_existing_version(self):
        self._chain("1")
        try:
            self.session.execute(
                text(
                    "UPDATE local_observation_records SET current_version=99 "
                    "WHERE id='obs-1'"
                )
            )
            self.session.commit()
            self.fail("bad current_version passed")
        except IntegrityError:
            self.session.rollback()

    def test_fractional_integers_are_rejected_by_observation_checks(self):
        self._chain("1")
        cases = (
            ("UPDATE local_observation_records SET current_draft_revision=1.5 "
             "WHERE id='obs-1'", "record current_draft_revision"),
            ("UPDATE local_observation_drafts SET revision=1.5 "
             "WHERE observation_id='obs-1'", "draft revision"),
            ("UPDATE local_observation_versions SET version=1.5 "
             "WHERE id='ver-1'", "version"),
            ("UPDATE local_observation_draft_photos SET sort_order=0.5 "
             "WHERE observation_id='obs-1'", "draft photo sort_order"),
            ("UPDATE local_observation_assets SET byte_size=1.5 "
             "WHERE id='asset-1'", "asset byte_size"),
            ("UPDATE local_observation_assets SET width=1.5 "
             "WHERE id='asset-1'", "asset width"),
        )
        for sql, label in cases:
            with self.subTest(label=label):
                try:
                    self.session.execute(text(sql))
                    self.session.commit()
                    self.fail(f"{label} accepted fractional value")
                except IntegrityError:
                    self.session.rollback()

    def test_new_source_indexes_and_partial_unique_are_present(self):
        db = self.runtime.db_path
        index_names = {
            row["name"]
            for row in query_rows(db, "PRAGMA index_list('local_ai_tasks')")
        }
        self.assertIn("ix_local_ai_tasks_source_status", index_names)
        self.assertIn("uq_local_ai_tasks_active_per_source_type", index_names)
        partial = [
            row
            for row in query_rows(db, "PRAGMA index_list('local_ai_tasks')")
            if row["name"] == "uq_local_ai_tasks_active_per_source_type"
        ][0]
        self.assertEqual(partial["unique"], 1)
        self.assertEqual(partial["partial"], 1)
        for table, name in (
            ("local_ai_inputs", "ix_local_ai_inputs_source_task"),
            ("local_ai_executions", "ix_local_ai_executions_source_task"),
            ("local_ai_candidates", "ix_local_ai_candidates_source_created"),
        ):
            names = {
                row["name"]
                for row in query_rows(db, f"PRAGMA index_list('{table}')")
            }
            self.assertIn(name, names)

    def test_two_active_observation_tasks_for_same_source_type_are_rejected(self):
        self._chain("1")
        self.session.execute(
            text("UPDATE local_ai_tasks SET status='pending' WHERE id='task-1'")
        )
        self.session.commit()
        try:
            self.session.add(
                LocalAITask(
                    id="task-active-2",
                    profile_id=self.profile.id,
                    source_kind="game_observation",
                    source_id="obs-1",
                    observation_id="obs-1",
                    daily_plan_id=None,
                    task_type="game_observation_generate",
                    input_id="input-1",
                    status="pending",
                    reason=None,
                    current_execution_id=None,
                    generation=0,
                    runtime_meta_json={},
                    created_at=self.now,
                    updated_at=self.now,
                )
            )
            self.session.commit()
            self.fail("second active observation task passed")
        except IntegrityError:
            self.session.rollback()


if __name__ == "__main__":
    unittest.main()
