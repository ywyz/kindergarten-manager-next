"""E06/E07 observation AI execution, candidates, preview and adoption tests."""

from __future__ import annotations

import io
import json
import os
import shutil
import sqlite3
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path
from unittest import mock

from PIL import Image
from sqlalchemy import select, text

from app.local import (
    ai_config_service,
    ai_executor,
    ai_task_service,
    ai_transport,
    ai_worker,
    observation_ai_inputs,
    observation_ai_service,
    observation_assets,
    observation_service,
    profile_service,
)
from app.local.errors import (
    LocalAiInputTooLarge,
    LocalAiPreviewExpired,
    LocalAiSourceChanged,
    LocalAiTargetChanged,
    LocalStorageError,
)
from app.local.models import (
    LocalAICandidate,
    LocalAIInput,
    LocalAIState,
    LocalAIOperation,
    LocalAITask,
    LocalObservationAIInputPhoto,
    LocalObservationAIProvenance,
    LocalObservationAsset,
    LocalObservationAssetDerivative,
    LocalObservationDraft,
    LocalObservationOperation,
    LocalObservationVersion,
    LocalProfile,
)
from app.local.normalize import normalize_initialization
from tests.local.obs_ai_workers import observation_worker_entry
from tests.local.support import LocalTestCase, initialize_body, query_scalar


class ObservationAiCase(LocalTestCase):
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
        self.configure_ai()

    def tearDown(self) -> None:
        self.session.close()
        super().tearDown()

    def configure_ai(
        self,
        *,
        model="deepseek-flash",
        base_url="https://api.deepseek.com/v1",
        secret="s3cret",
    ):
        version = query_scalar(self.runtime.db_path, "SELECT current_config_version FROM local_ai_state") or 0
        ai_config_service.patch_config(
            self.session,
            expected_ai_config_version=version,
            base_url=base_url,
            model=model,
            secret=secret,
            secret_provided=True,
            request_id=str(uuid.uuid4()),
            credential_root=self.runtime.credential_root,
        )

    def _payload(self, **overrides):
        value = {
            "observation_date": "2026-09-15",
            "record_type": "public",
            "subjects": [{"name": "小明"}, {"name": "小红"}],
            "age_years": 5,
            "environment": "积木区",
            "observation_goal": "",
            "observation_process": "",
            "support_strategy": "",
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

    def _current(self, observation_id):
        return observation_service.read_current(
            self.session, profile_id=self.profile.id, observation_id=observation_id
        )

    def _import_photo(self, observation_id, color="red"):
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
            caption="观察",
            now=self.now,
        )
        return result["asset_id"]

    def _save(self, observation_id, payload, *, photos=None, reason="manual"):
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
            now=self.now,
        )

    def _ready_observation(self):
        created = self._create()
        observation_id = created["observation_id"]
        asset_id = self._import_photo(observation_id)
        self._save(
            observation_id,
            {
                "observation_goal": "观察合作",
                "observation_process": "幼儿在积木区搭建。",
            },
            photos=[{"asset_id": asset_id, "caption": "观察"}],
        )
        return observation_id, asset_id

    def _create_task(self, observation_id, task_type="game_observation_generate", target=None):
        current = self._current(observation_id)
        result, created = observation_ai_service.create_observation_task(
            self.session,
            self.runtime,
            profile_id=self.profile.id,
            observation_id=observation_id,
            task_type=task_type,
            expected_revision=current["revision"],
            expected_hash=current["payload_hash"],
            target=target,
            request_id=str(uuid.uuid4()),
        )
        self.assertTrue(created)
        return result

    def _start_executor(self):
        executor = ai_executor.AiExecutor(
            self.runtime, worker_target=observation_worker_entry
        )
        executor.start()
        self.addCleanup(executor.dispose)
        return executor

    def _wait_status(self, task_id, timeout=25.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.session.expire_all()
            task = self.session.get(LocalAITask, task_id)
            if task is not None and task.status in (
                "succeeded",
                "failed",
                "paused",
                "outcome_unknown",
            ):
                return task.status
            time.sleep(0.05)
        task = self.session.get(LocalAITask, task_id)
        raise AssertionError(
            f"task did not finish: {task.status if task else None} "
            f"{task.reason if task else None}"
        )

    def _run_generate(self, observation_id):
        executor = self._start_executor()
        task = self._create_task(observation_id)
        executor.notify()
        status = self._wait_status(task["id"])
        self.assertEqual(status, "succeeded")
        return self._candidate_id(task["id"]), task, executor

    def _preview(self, observation_id, candidate_id, targets, *, runtime=None, review=None):
        current = self._current(observation_id)
        return observation_ai_service.preview_adoption(
            self.session,
            runtime or self.runtime,
            profile_id=self.profile.id,
            observation_id=observation_id,
            candidate_id=candidate_id,
            expected_revision=current["revision"],
            expected_hash=current["payload_hash"],
            selected_targets=targets,
            request_id=str(uuid.uuid4()),
        )

    def _adopt(self, observation_id, candidate_id, targets, preview, *, runtime=None, review=None, rid=None):
        current = self._current(observation_id)
        return observation_ai_service.adopt(
            self.session,
            runtime or self.runtime,
            profile_id=self.profile.id,
            observation_id=observation_id,
            candidate_id=candidate_id,
            expected_revision=current["revision"],
            expected_hash=current["payload_hash"],
            selected_targets=targets,
            preview_token=preview["adoption_token"],
            request_id=rid or str(uuid.uuid4()),
            review_decision=review,
        )

    def _evidence_root(self) -> Path:
        """Lazy per-test evidence root; unique unless explicitly overridden."""
        root = getattr(self, "_evidence_root_path", None)
        if root is None:
            override = os.environ.get("E0607_EVIDENCE_ROOT")
            if override:
                root = Path(override)
            else:
                root = Path(tempfile.mkdtemp(prefix="kgm-observation-e0607-"))
            root.mkdir(parents=True, exist_ok=True)
            self._evidence_root_path = root
        return root

    def _preserve_evidence(self, name: str, summary: dict) -> None:
        target = self._evidence_root() / name
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
                observations, target / "observations", dirs_exist_ok=True
            )
        (target / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    def _delete_work_file(self, observation_id, asset_id):
        self.session.expire_all()
        derivative = self.session.scalars(
            select(LocalObservationAssetDerivative).where(
                LocalObservationAssetDerivative.observation_id == observation_id,
                LocalObservationAssetDerivative.asset_id == asset_id,
                LocalObservationAssetDerivative.purpose == "ai",
            )
        ).one()
        path = self.runtime.data_dir / derivative.relative_path
        path.unlink()
        return derivative, path

    def _delete_original_file(self, asset_id):
        self.session.expire_all()
        asset = self.session.get(LocalObservationAsset, asset_id)
        path = self.runtime.data_dir / asset.relative_path
        path.unlink()
        return asset, path

    def _candidate_id(self, task_id):
        self.session.expire_all()
        candidate = self.session.scalars(
            select(LocalAICandidate).where(LocalAICandidate.task_id == task_id)
        ).one()
        return candidate.id


class ObservationAiInputTests(ObservationAiCase):
    def test_create_task_freezes_send_projection_without_internal_asset_ids(self):
        observation_id, asset_id = self._ready_observation()
        task = self._create_task(observation_id)
        self.assertEqual(task["status"], "pending")
        self.assertEqual(task["source_kind"], "game_observation")
        self.assertEqual(task["observation_id"], observation_id)
        inp = self.session.get(
            LocalAIInput,
            query_scalar(
                self.runtime.db_path,
                "SELECT input_id FROM local_ai_tasks WHERE id = ?",
                (task["id"],),
            ),
        )
        self.assertEqual(inp.source_kind, "game_observation")
        self.assertEqual(inp.observation_id, observation_id)
        self.assertEqual(inp.source_revision, self._current(observation_id)["revision"])
        photo = inp.payload_json["photos"][0]
        self.assertNotIn("asset_id", photo)
        self.assertNotIn("derivative_id", photo)
        self.assertIn("content_hash", photo)
        self.assertIn("work_hash", photo)
        rows = self.session.scalars(
            select(LocalObservationAIInputPhoto).where(
                LocalObservationAIInputPhoto.input_id == inp.id
            )
        ).all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].asset_id, asset_id)

    def test_rewrite_task_has_target_and_only_target_source(self):
        observation_id, _asset_id = self._ready_observation()
        task = self._create_task(
            observation_id,
            task_type="game_observation_rewrite",
            target="observation_process",
        )
        inp = self.session.get(
            LocalAIInput,
            query_scalar(
                self.runtime.db_path,
                "SELECT input_id FROM local_ai_tasks WHERE id = ?",
                (task["id"],),
            ),
        )
        self.assertEqual(inp.payload_json["target"], "observation_process")
        self.assertEqual(inp.payload_json["rewrite_source"], "幼儿在积木区搭建。")
        self.assertIn("observation_goal", inp.payload_json)
        self.assertNotIn("support_strategy", inp.payload_json)

    def test_image_count_601_rejected_before_reads(self):
        photos = [
            {
                "asset_id": f"a{i}",
                "derivative_id": f"d{i}",
                "work_hash": "0" * 64,
                "content_hash": "0" * 64,
            }
            for i in range(601)
        ]
        with self.assertRaises(LocalAiInputTooLarge):
            observation_ai_inputs.material_image_urls(
                self.session,
                self.runtime,
                profile_id=self.profile.id,
                observation_id="missing",
                photos=photos,
            )

    def test_vision_capability_exact_hosts_and_prefixes(self):
        self.assertTrue(
            ai_transport.vision_capability(
                "https://api.deepseek.com/v1", "deepseek-flash"
            )
        )
        self.assertTrue(
            ai_transport.vision_capability(
                "https://api.xiaomimimo.com/v1", "mimo-v2.6-flash"
            )
        )
        for base_url, model in (
            ("https://evil.xiaomimimo.com/v1", "mimo-v2.6-flash"),
            ("https://api.xiaomimimo.com/token-plan/v1", "mimo-v2.6-flash"),
            ("https://api.deepseek.com/go", "deepseek-flash"),
            ("http://api.deepseek.com/v1", "deepseek-flash"),
            ("https://api.deepseek.com:8443/v1", "deepseek-flash"),
        ):
            with self.subTest(base_url=base_url):
                self.assertFalse(ai_transport.vision_capability(base_url, model))


class ObservationAiExecutorTests(ObservationAiCase):
    def test_generate_candidate_preview_and_adopt(self):
        observation_id, _asset_id = self._ready_observation()
        executor = self._start_executor()
        task = self._create_task(observation_id)
        executor.notify()
        self.assertEqual(self._wait_status(task["id"]), "succeeded")
        candidate_id = self._candidate_id(task["id"])
        detail = observation_ai_service.get_candidate(
            self.session,
            profile_id=self.profile.id,
            observation_id=observation_id,
            candidate_id=candidate_id,
        )
        self.assertEqual(detail["available_targets"], list(observation_ai_inputs.TARGETS))
        self.assertIn("review_warning", detail)
        self.assertIn("review_fragments", detail)
        current = self._current(observation_id)
        preview = observation_ai_service.preview_adoption(
            self.session,
            self.runtime,
            profile_id=self.profile.id,
            observation_id=observation_id,
            candidate_id=candidate_id,
            expected_revision=current["revision"],
            expected_hash=current["payload_hash"],
            selected_targets=["observation_goal", "analysis_evaluation"],
            request_id=str(uuid.uuid4()),
        )
        self.assertEqual(preview["source_state"], "eligible")
        self.assertFalse(preview["requires_review_decision"])
        result = observation_ai_service.adopt(
            self.session,
            self.runtime,
            profile_id=self.profile.id,
            observation_id=observation_id,
            candidate_id=candidate_id,
            expected_revision=current["revision"],
            expected_hash=current["payload_hash"],
            selected_targets=["observation_goal", "analysis_evaluation"],
            preview_token=preview["adoption_token"],
            request_id=str(uuid.uuid4()),
        )
        self.assertTrue(result["changed"])
        after = self._current(observation_id)
        self.assertEqual(after["payload"]["observation_goal"], "观察幼儿合作搭建")
        self.assertEqual(after["payload"]["analysis_evaluation"]["social"], "轮流协商")
        provenance = self.session.scalars(
            select(LocalObservationAIProvenance).where(
                LocalObservationAIProvenance.observation_id == observation_id
            )
        ).one()
        self.assertEqual(provenance.candidate_id, candidate_id)
        self.assertEqual(result["current_version"], provenance.version)

    def test_rewrite_candidate_only_target(self):
        observation_id, _asset_id = self._ready_observation()
        executor = self._start_executor()
        task = self._create_task(
            observation_id,
            task_type="game_observation_rewrite",
            target="observation_goal",
        )
        executor.notify()
        self.assertEqual(self._wait_status(task["id"]), "succeeded")
        candidate_id = self._candidate_id(task["id"])
        detail = observation_ai_service.get_candidate(
            self.session,
            profile_id=self.profile.id,
            observation_id=observation_id,
            candidate_id=candidate_id,
        )
        self.assertEqual(detail["available_targets"], ["observation_goal"])
        current = self._current(observation_id)
        preview = observation_ai_service.preview_adoption(
            self.session,
            self.runtime,
            profile_id=self.profile.id,
            observation_id=observation_id,
            candidate_id=candidate_id,
            expected_revision=current["revision"],
            expected_hash=current["payload_hash"],
            selected_targets=["observation_goal"],
            request_id=str(uuid.uuid4()),
        )
        result = observation_ai_service.adopt(
            self.session,
            self.runtime,
            profile_id=self.profile.id,
            observation_id=observation_id,
            candidate_id=candidate_id,
            expected_revision=current["revision"],
            expected_hash=current["payload_hash"],
            selected_targets=["observation_goal"],
            preview_token=preview["adoption_token"],
            request_id=str(uuid.uuid4()),
        )
        self.assertTrue(result["changed"])
        self.assertEqual(
            self._current(observation_id)["payload"]["observation_goal"],
            "重写后的observation_goal",
        )
        self.assertEqual(
            self._current(observation_id)["payload"]["observation_process"],
            "幼儿在积木区搭建。",
        )


class ObservationAiReviewTests(ObservationAiCase):
    def _metadata_row(self, candidate_id):
        self.session.expire_all()
        return self.session.scalars(
            select(LocalAIOperation).where(
                LocalAIOperation.request_id == "cr:" + candidate_id,
                LocalAIOperation.operation_kind == "observation_ai_candidate_review",
            )
        ).one()

    def _delete_work_file(self, observation_id, asset_id):
        self.session.expire_all()
        derivative = self.session.scalars(
            select(LocalObservationAssetDerivative).where(
                LocalObservationAssetDerivative.observation_id == observation_id,
                LocalObservationAssetDerivative.asset_id == asset_id,
                LocalObservationAssetDerivative.purpose == "ai",
            )
        ).one()
        asset = self.session.get(LocalObservationAsset, asset_id)
        path = self.runtime.data_dir / derivative.relative_path
        path.unlink()
        return asset, derivative, path

    def _delete_original_file(self, asset_id):
        self.session.expire_all()
        asset = self.session.get(LocalObservationAsset, asset_id)
        path = self.runtime.data_dir / asset.relative_path
        path.unlink()
        return asset, path

    def test_partial_adoption_then_evaluation_and_support(self):
        observation_id, _asset_id = self._ready_observation()
        candidate_id, _task, _executor = self._run_generate(observation_id)
        goal = self._preview(observation_id, candidate_id, ["observation_goal"])
        self._adopt(observation_id, candidate_id, ["observation_goal"], goal)
        detail = observation_ai_service.get_candidate(
            self.session,
            profile_id=self.profile.id,
            observation_id=observation_id,
            candidate_id=candidate_id,
        )
        self.assertEqual(detail["adoption_state"], "eligible")
        evaluation = self._preview(
            observation_id, candidate_id, ["analysis_evaluation"]
        )
        self.assertEqual(evaluation["source_state"], "eligible")
        self._adopt(
            observation_id, candidate_id, ["analysis_evaluation"], evaluation
        )
        self.assertEqual(
            self._current(observation_id)["payload"]["analysis_evaluation"]["arts"],
            "",
        )
        support = self._preview(
            observation_id, candidate_id, ["support_strategy"]
        )
        self.assertEqual(support["source_state"], "eligible")
        result = self._adopt(
            observation_id, candidate_id, ["support_strategy"], support
        )
        self.assertTrue(result["changed"])

    def test_auto_roundtrip_clears_trust(self):
        observation_id, _asset_id = self._ready_observation()
        candidate_id, _task, _executor = self._run_generate(observation_id)
        goal = self._preview(observation_id, candidate_id, ["observation_goal"])
        self._adopt(observation_id, candidate_id, ["observation_goal"], goal)
        self._save(observation_id, {"observation_goal": "临时目标"}, reason="auto")
        self._save(
            observation_id,
            {"observation_goal": "观察幼儿合作搭建"},
            reason="auto",
        )
        preview = self._preview(
            observation_id, candidate_id, ["analysis_evaluation"]
        )
        self.assertEqual(preview["source_state"], "source_changed")
        self.assertTrue(preview["requires_review_decision"])
        with self.assertRaises(LocalAiSourceChanged):
            self._adopt(
                observation_id,
                candidate_id,
                ["analysis_evaluation"],
                preview,
            )
        preview2 = self._preview(
            observation_id, candidate_id, ["analysis_evaluation"]
        )
        result = self._adopt(
            observation_id,
            candidate_id,
            ["analysis_evaluation"],
            preview2,
            review="adopt_reviewed",
        )
        self.assertTrue(result["changed"])

    def test_hand_edited_adopted_target_cannot_be_overwritten(self):
        observation_id, _asset_id = self._ready_observation()
        candidate_id, _task, _executor = self._run_generate(observation_id)
        goal = self._preview(observation_id, candidate_id, ["observation_goal"])
        self._adopt(observation_id, candidate_id, ["observation_goal"], goal)
        self._save(observation_id, {"observation_goal": "手工目标"})
        preview = self._preview(observation_id, candidate_id, ["observation_goal"])
        self.assertEqual(preview["source_state"], "source_changed")
        with self.assertRaises(LocalAiTargetChanged):
            self._adopt(
                observation_id,
                candidate_id,
                ["observation_goal"],
                preview,
                review="adopt_reviewed",
            )

    def test_other_candidate_same_text_not_trusted(self):
        observation_id, _asset_id = self._ready_observation()
        candidate1, _task1, _executor = self._run_generate(observation_id)
        candidate2, _task2, _executor2 = self._run_generate(observation_id)
        goal = self._preview(observation_id, candidate1, ["observation_goal"])
        self._adopt(observation_id, candidate1, ["observation_goal"], goal)
        detail = observation_ai_service.get_candidate(
            self.session,
            profile_id=self.profile.id,
            observation_id=observation_id,
            candidate_id=candidate2,
        )
        self.assertEqual(detail["adoption_state"], "source_changed")
        self.assertNotEqual(candidate1, candidate2)

    def test_ledger_missing_clears_trust(self):
        observation_id, _asset_id = self._ready_observation()
        candidate_id, _task, _executor = self._run_generate(observation_id)
        goal = self._preview(observation_id, candidate_id, ["observation_goal"])
        self._adopt(observation_id, candidate_id, ["observation_goal"], goal)
        provenance = self.session.scalars(
            select(LocalObservationAIProvenance).where(
                LocalObservationAIProvenance.observation_id == observation_id
            )
        ).one()
        self.session.delete(provenance)
        self.session.commit()
        preview = self._preview(
            observation_id, candidate_id, ["analysis_evaluation"]
        )
        self.assertEqual(preview["source_state"], "source_changed")

    def test_receipt_replay_survives_consumed_token_bad_material_and_new_revision(self):
        observation_id, asset_id = self._ready_observation()
        candidate_id, _task, _executor = self._run_generate(observation_id)
        original = self._current(observation_id)
        preview = self._preview(observation_id, candidate_id, ["observation_goal"])
        rid = str(uuid.uuid4())
        result = self._adopt(
            observation_id,
            candidate_id,
            ["observation_goal"],
            preview,
            rid=rid,
        )
        self._save(observation_id, {"observation_goal": "后来修改"})
        self._delete_work_file(observation_id, asset_id)
        replay = observation_ai_service.adopt(
            self.session,
            self.runtime,
            profile_id=self.profile.id,
            observation_id=observation_id,
            candidate_id=candidate_id,
            expected_revision=original["revision"],
            expected_hash=original["payload_hash"],
            selected_targets=["observation_goal"],
            preview_token=preview["adoption_token"],
            request_id=rid,
        )
        self.assertEqual(replay, result)

    def test_same_token_two_request_ids_only_one_succeeds(self):
        observation_id, _asset_id = self._ready_observation()
        candidate_id, _task, _executor = self._run_generate(observation_id)
        preview = self._preview(observation_id, candidate_id, ["observation_goal"])
        current = self._current(observation_id)
        self._adopt(observation_id, candidate_id, ["observation_goal"], preview)
        with self.assertRaises(LocalAiPreviewExpired):
            observation_ai_service.adopt(
                self.session,
                self.runtime,
                profile_id=self.profile.id,
                observation_id=observation_id,
                candidate_id=candidate_id,
                expected_revision=current["revision"],
                expected_hash=current["payload_hash"],
                selected_targets=["observation_goal"],
                preview_token=preview["adoption_token"],
                request_id=str(uuid.uuid4()),
            )

    def test_candidate_hash_binding_rejects_changed_candidate(self):
        observation_id, _asset_id = self._ready_observation()
        candidate_id, _task, _executor = self._run_generate(observation_id)
        preview = self._preview(observation_id, candidate_id, ["observation_goal"])
        candidate = self.session.get(LocalAICandidate, candidate_id)
        raw = dict(candidate.raw_candidate_json)
        raw["observation_goal"] = "另一个候选"
        candidate.raw_candidate_json = raw
        from app.local.observation_validation import canonical_json
        import hashlib

        candidate.candidate_hash = hashlib.sha256(
            canonical_json(raw).encode("utf-8")
        ).hexdigest()
        self.session.commit()
        with self.assertRaises(LocalAiPreviewExpired):
            self._adopt(observation_id, candidate_id, ["observation_goal"], preview)

    def test_added_photo_valid_review_and_bad_work_rejected(self):
        observation_id, _asset_id = self._ready_observation()
        candidate_id, _task, _executor = self._run_generate(observation_id)
        self._import_photo(observation_id, "blue")
        preview = self._preview(observation_id, candidate_id, ["observation_goal"])
        self.assertEqual(preview["source_state"], "source_changed")
        self._adopt(
            observation_id,
            candidate_id,
            ["observation_goal"],
            preview,
            review="adopt_reviewed",
        )
        self.assertEqual(len(self._current(observation_id)["photos"]), 2)

        observation_id2, _asset2 = self._ready_observation()
        candidate2, _task2, _executor2 = self._run_generate(observation_id2)
        new_asset2 = self._import_photo(observation_id2, "green")
        preview2 = self._preview(observation_id2, candidate2, ["observation_goal"])
        self.assertEqual(preview2["source_state"], "source_changed")
        self._delete_work_file(observation_id2, new_asset2)
        with self.assertRaises(LocalStorageError):
            self._adopt(
                observation_id2,
                candidate2,
                ["observation_goal"],
                preview2,
                review="adopt_reviewed",
            )

    def test_added_original_missing_rejected(self):
        observation_id, _asset_id = self._ready_observation()
        candidate_id, _task, _executor = self._run_generate(observation_id)
        new_asset = self._import_photo(observation_id, "yellow")
        preview = self._preview(observation_id, candidate_id, ["observation_goal"])
        self._delete_original_file(new_asset)
        with self.assertRaises(LocalStorageError):
            self._adopt(
                observation_id,
                candidate_id,
                ["observation_goal"],
                preview,
                review="adopt_reviewed",
            )

    def test_claim_original_missing_pauses(self):
        observation_id, asset_id = self._ready_observation()
        executor = self._start_executor()
        task = self._create_task(observation_id)
        self._delete_original_file(asset_id)
        executor.notify()
        self.assertEqual(self._wait_status(task["id"]), "paused")
        self.session.expire_all()
        row = self.session.get(LocalAITask, task["id"])
        self.assertEqual(row.reason, "material_invalid")

    def test_review_metadata_persisted_and_bad_fragment_downgraded(self):
        observation_id, _asset_id = self._ready_observation()
        candidate_id, _task, _executor = self._run_generate(observation_id)
        detail = observation_ai_service.get_candidate(
            self.session,
            profile_id=self.profile.id,
            observation_id=observation_id,
            candidate_id=candidate_id,
        )
        self.assertTrue(detail["review_fragments"])
        metadata = self._metadata_row(candidate_id)
        broken = dict(metadata.result_json)
        broken["fragments"] = [dict(broken["fragments"][0], start=9999)]
        metadata.result_json = broken
        self.session.commit()
        again = observation_ai_service.get_candidate(
            self.session,
            profile_id=self.profile.id,
            observation_id=observation_id,
            candidate_id=candidate_id,
        )
        self.assertEqual(again["review_fragments"], [])
        self.assertIn("observation_goal", again["raw_candidate"])

    def test_rewrite_does_not_inherit_old_fragments(self):
        observation_id, _asset_id = self._ready_observation()
        _candidate1, _task1, _executor = self._run_generate(observation_id)
        executor = self._start_executor()
        task = self._create_task(
            observation_id,
            task_type="game_observation_rewrite",
            target="observation_goal",
        )
        executor.notify()
        self.assertEqual(self._wait_status(task["id"]), "succeeded")
        candidate_id = self._candidate_id(task["id"])
        detail = observation_ai_service.get_candidate(
            self.session,
            profile_id=self.profile.id,
            observation_id=observation_id,
            candidate_id=candidate_id,
        )
        self.assertEqual(detail["review_fragments"], [])


class ObservationAiPinnedConfigTests(ObservationAiCase):
    def _pick(self, task):
        inp = self.session.get(
            LocalAIInput,
            query_scalar(
                self.runtime.db_path,
                "SELECT input_id FROM local_ai_tasks WHERE id = ?",
                (task["id"],),
            ),
        )
        return ai_task_service._Pick(
            task_id=task["id"],
            task_status="pending",
            plan_id=None,
            input_id=inp.id,
            task_type=task["task_type"],
            generation=0,
            current_execution_id=None,
            existing_execution_id=None,
            permit_id=None,
            launch_id=None,
            config_version=1,
            personal_revision=1,
            contract_version=1,
            default_revision=1,
            source_kind="game_observation",
            observation_id=task["observation_id"],
        )

    def test_loader_uses_pinned_config_and_secret(self):
        observation_id, _asset_id = self._ready_observation()
        task = self._create_task(observation_id)
        pick = self._pick(task)
        material, failure = observation_ai_service.load_observation_material(
            self.runtime, pick
        )
        self.assertIsNone(failure)
        self.assertEqual(material["model"], "deepseek-flash")
        self.assertEqual(material["secret"], "s3cret")
        self.assertEqual(material["config_version"], 1)

    def test_pending_claim_takes_latest_config(self):
        from app.local.base import utc_now

        observation_id, _asset_id = self._ready_observation()
        task = self._create_task(observation_id)
        self.configure_ai(model="deepseek-flash", secret="new-secret")
        claim = ai_task_service.claim_next(
            self.runtime, now=utc_now(), started_ticks=ai_transport.now_ticks()
        )
        self.assertIsNotNone(claim)
        self.assertEqual(claim.config_version, 2)
        self.assertEqual(claim.secret, "new-secret")

    def test_unknown_input_schema_pauses(self):
        observation_id, _asset_id = self._ready_observation()
        task = self._create_task(observation_id)
        inp_id = query_scalar(
            self.runtime.db_path,
            "SELECT input_id FROM local_ai_tasks WHERE id = ?",
            (task["id"],),
        )
        from tests.local.support import execute_sql

        execute_sql(
            self.runtime.db_path,
            "UPDATE local_ai_inputs SET input_schema_version = 2 WHERE id = ?",
            (inp_id,),
        )
        material, failure = observation_ai_service.load_observation_material(
            self.runtime, self._pick(task)
        )
        self.assertIsNone(material)
        self.assertEqual(failure, "schema_unsupported")

    def test_retry_wait_reuses_pinned_execution_config(self):
        from datetime import timedelta

        from app.local.base import utc_now

        observation_id, _asset_id = self._ready_observation()
        task = self._create_task(observation_id)
        claim = ai_task_service.claim_next(
            self.runtime, now=utc_now(), started_ticks=ai_transport.now_ticks()
        )
        self.assertIsNotNone(claim)
        self.assertTrue(
            ai_task_service.finalize_failure(
                self.session,
                claim,
                {
                    "kind": "not_sent",
                    "transient_not_sent": True,
                    "sent": False,
                    "reason": "connection_unavailable",
                },
                utc_now(),
            )
        )
        self.configure_ai(model="deepseek-flash")
        again = ai_task_service.claim_next(
            self.runtime,
            now=utc_now() + timedelta(seconds=10),
            started_ticks=ai_transport.now_ticks(),
        )
        self.assertIsNotNone(again)
        self.assertEqual(again.config_version, 1)
        self.assertEqual(again.model, "deepseek-flash")
        self.assertEqual(again.secret, "s3cret")

    def test_oversized_work_image_rejected_before_full_read(self):
        observation_id, asset_id = self._ready_observation()
        self.session.expire_all()
        derivative = self.session.scalars(
            select(LocalObservationAssetDerivative).where(
                LocalObservationAssetDerivative.observation_id == observation_id,
                LocalObservationAssetDerivative.asset_id == asset_id,
                LocalObservationAssetDerivative.purpose == "ai",
            )
        ).one()
        path = self.runtime.data_dir / derivative.relative_path
        with path.open("wb") as handle:
            handle.write(b"\xff" * (observation_assets.AI_TARGET_BYTES + 1))
        asset = self.session.get(LocalObservationAsset, asset_id)
        with self.assertRaises(observation_assets.ObservationMaterialLimit):
            observation_ai_inputs.material_image_urls(
                self.session,
                self.runtime,
                profile_id=self.profile.id,
                observation_id=observation_id,
                photos=[
                    {
                        "asset_id": asset_id,
                        "derivative_id": derivative.id,
                        "content_hash": asset.content_hash,
                        "work_hash": derivative.content_hash,
                    }
                ],
            )

    def test_internal_context_persists_warnings_and_derivation(self):
        observation_id, _asset_id = self._ready_observation()
        task = self._create_task(observation_id)
        inp = self.session.get(
            LocalAIInput,
            query_scalar(
                self.runtime.db_path,
                "SELECT input_id FROM local_ai_tasks WHERE id = ?",
                (task["id"],),
            ),
        )
        self.assertEqual(inp.input_schema_version, 1)
        deps = dict(inp.dependencies_json)
        self.assertIn("wire", deps)
        self.assertIn("internal", deps)
        internal = deps["internal"]
        self.assertEqual(internal["internal_schema_version"], 1)
        self.assertEqual(internal["wire_schema_version"], 1)
        self.assertIn("missing_fields", internal)
        self.assertIn("warnings", internal)
        self.assertEqual(internal["photos"][0]["params_version"], observation_assets.AI_PARAMS_VERSION)
        self.assertGreater(internal["photos"][0]["work_width"], 0)
        self.assertIn("warnings", task["input_summary"])

    def test_new_derivative_params_do_not_break_old_candidate(self):
        from datetime import timedelta

        observation_id, asset_id = self._ready_observation()
        candidate_id, _task, _executor = self._run_generate(observation_id)
        self.session.expire_all()
        old = self.session.scalars(
            select(LocalObservationAssetDerivative).where(
                LocalObservationAssetDerivative.observation_id == observation_id,
                LocalObservationAssetDerivative.asset_id == asset_id,
                LocalObservationAssetDerivative.purpose == "ai",
            )
        ).one()
        new_id = uuid.uuid4().hex
        new_path = (self.runtime.data_dir / old.relative_path).parent / f"{new_id}.jpg"
        shutil.copyfile(self.runtime.data_dir / old.relative_path, new_path)
        self.session.add(
            LocalObservationAssetDerivative(
                id=new_id,
                observation_id=observation_id,
                asset_id=asset_id,
                purpose="ai",
                params_version="ai-v9-test",
                content_hash=old.content_hash,
                mime_type=old.mime_type,
                width=old.width,
                height=old.height,
                relative_path=(Path(old.relative_path).parent / f"{new_id}.jpg").as_posix(),
                created_at=old.created_at + timedelta(seconds=1),
            )
        )
        self.session.commit()
        detail = observation_ai_service.get_candidate(
            self.session,
            profile_id=self.profile.id,
            observation_id=observation_id,
            candidate_id=candidate_id,
        )
        self.assertEqual(detail["adoption_state"], "eligible")
        preview = self._preview(observation_id, candidate_id, ["observation_goal"])
        self.assertEqual(preview["source_state"], "eligible")
        result = self._adopt(
            observation_id,
            candidate_id,
            ["observation_goal"],
            preview,
        )
        self.assertTrue(result["changed"])

    def test_candidate_hash_changed_between_inspection_and_write_lock_is_rejected(self):
        import hashlib

        from app.local.observation_validation import canonical_json

        observation_id, _asset_id = self._ready_observation()
        candidate_id, _task, _executor = self._run_generate(observation_id)
        preview = self._preview(observation_id, candidate_id, ["observation_goal"])
        current = self._current(observation_id)
        candidate = self.session.get(LocalAICandidate, candidate_id)
        original_raw = dict(candidate.raw_candidate_json)
        original_hash = candidate.candidate_hash
        real_inspect = observation_ai_service._inspect_materials

        def interleaving(*args, **kwargs):
            result = real_inspect(*args, **kwargs)
            other = self.runtime.session()
            try:
                row = other.get(LocalAICandidate, candidate_id)
                changed = dict(row.raw_candidate_json)
                changed["support_strategy"] = "另一 session 改的未选栏"
                row.raw_candidate_json = changed
                row.candidate_hash = hashlib.sha256(
                    canonical_json(changed).encode("utf-8")
                ).hexdigest()
                other.commit()
            finally:
                other.close()
            return result

        before_versions = len(
            self.session.scalars(
                select(LocalObservationVersion).where(
                    LocalObservationVersion.observation_id == observation_id
                )
            ).all()
        )
        with mock.patch.object(
            observation_ai_service, "_inspect_materials", side_effect=interleaving
        ):
            with self.assertRaises(LocalAiPreviewExpired):
                observation_ai_service.adopt(
                    self.session,
                    self.runtime,
                    profile_id=self.profile.id,
                    observation_id=observation_id,
                    candidate_id=candidate_id,
                    expected_revision=current["revision"],
                    expected_hash=current["payload_hash"],
                    selected_targets=["observation_goal"],
                    preview_token=preview["adoption_token"],
                    request_id=str(uuid.uuid4()),
                )
        self.assertEqual(self._current(observation_id)["revision"], current["revision"])
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
        self.session.expire_all()
        row = self.session.get(LocalAICandidate, candidate_id)
        row.raw_candidate_json = original_raw
        row.candidate_hash = original_hash
        self.session.commit()
        # The failed attempt released the reservation; the same token can be
        # retried after the external candidate change is reverted.
        retry = observation_ai_service.adopt(
            self.session,
            self.runtime,
            profile_id=self.profile.id,
            observation_id=observation_id,
            candidate_id=candidate_id,
            expected_revision=current["revision"],
            expected_hash=current["payload_hash"],
            selected_targets=["observation_goal"],
            preview_token=preview["adoption_token"],
            request_id=str(uuid.uuid4()),
        )
        self.assertTrue(retry["changed"])

    def test_current_added_work_missing_rejected_at_preview(self):
        observation_id, _asset_id = self._ready_observation()
        candidate_id, _task, _executor = self._run_generate(observation_id)
        new_asset = self._import_photo(observation_id, "purple")
        self._delete_work_file(observation_id, new_asset)
        with self.assertRaises(LocalStorageError):
            self._preview(observation_id, candidate_id, ["observation_goal"])

    def test_current_added_original_missing_rejected_at_preview(self):
        observation_id, _asset_id = self._ready_observation()
        candidate_id, _task, _executor = self._run_generate(observation_id)
        new_asset = self._import_photo(observation_id, "orange")
        self._delete_original_file(new_asset)
        with self.assertRaises(LocalStorageError):
            self._preview(observation_id, candidate_id, ["observation_goal"])

    def test_material_replaced_between_inspection_and_commit_is_rejected(self):
        observation_id, asset_id = self._ready_observation()
        candidate_id, _task, _executor = self._run_generate(observation_id)
        preview = self._preview(observation_id, candidate_id, ["observation_goal"])
        current = self._current(observation_id)
        self.session.expire_all()
        derivative = self.session.scalars(
            select(LocalObservationAssetDerivative).where(
                LocalObservationAssetDerivative.observation_id == observation_id,
                LocalObservationAssetDerivative.asset_id == asset_id,
                LocalObservationAssetDerivative.purpose == "ai",
            )
        ).one()
        path = self.runtime.data_dir / derivative.relative_path
        original_bytes = path.read_bytes()
        real_inspect = observation_ai_service._inspect_materials

        def replace_after_inspect(*args, **kwargs):
            result = real_inspect(*args, **kwargs)
            path.write_bytes(b"different bytes")
            return result

        try:
            with mock.patch.object(
                observation_ai_service,
                "_inspect_materials",
                side_effect=replace_after_inspect,
            ):
                with self.assertRaises((LocalStorageError, LocalAiPreviewExpired)):
                    observation_ai_service.adopt(
                        self.session,
                        self.runtime,
                        profile_id=self.profile.id,
                        observation_id=observation_id,
                        candidate_id=candidate_id,
                        expected_revision=current["revision"],
                        expected_hash=current["payload_hash"],
                        selected_targets=["observation_goal"],
                        preview_token=preview["adoption_token"],
                        request_id=str(uuid.uuid4()),
                    )
        finally:
            path.write_bytes(original_bytes)

    def test_same_process_reopen_receipt_replay_after_consumed_token(self):
        observation_id, _asset_id = self._ready_observation()
        candidate_id, _task, _executor = self._run_generate(observation_id)
        original = self._current(observation_id)
        preview = self._preview(observation_id, candidate_id, ["observation_goal"])
        rid = str(uuid.uuid4())
        result = self._adopt(
            observation_id,
            candidate_id,
            ["observation_goal"],
            preview,
            rid=rid,
        )
        data_dir = self.data_dir
        self.session.close()
        self.runtime.dispose()
        self.runtime = self.make_runtime(data_dir)
        self.session = self.runtime.session()
        self.profile = self.session.scalars(select(LocalProfile)).one()
        replay = observation_ai_service.adopt(
            self.session,
            self.runtime,
            profile_id=self.profile.id,
            observation_id=observation_id,
            candidate_id=candidate_id,
            expected_revision=original["revision"],
            expected_hash=original["payload_hash"],
            selected_targets=["observation_goal"],
            preview_token=preview["adoption_token"],
            request_id=rid,
        )
        self.assertEqual(replay, result)

    def test_real_subprocess_cold_restart_after_commit_and_receipt_replay(self):
        observation_id, _asset_id = self._ready_observation()
        candidate_id, _task, _executor = self._run_generate(observation_id)
        current = self._current(observation_id)
        profile_id = self.profile.id
        data_dir = self.data_dir
        preview_request = str(uuid.uuid4())
        request_id = str(uuid.uuid4())
        attempts_before = query_scalar(
            self.runtime.db_path, "SELECT count(*) FROM local_ai_attempts"
        )
        tasks_before = query_scalar(
            self.runtime.db_path, "SELECT count(*) FROM local_ai_tasks"
        )
        self.session.close()
        self.runtime.dispose()
        self.runtime = None
        self.session = None
        spec = self.worker_spec(
            "observation_ai_adopt", data_dir=data_dir, connect_only=False
        )
        spec.update(
            {
                "profile_id": profile_id,
                "observation_id": observation_id,
                "candidate_id": candidate_id,
                "expected_revision": current["revision"],
                "expected_hash": current["payload_hash"],
                "selected_targets": ["observation_goal"],
                "preview_request_id": preview_request,
                "request_id": request_id,
                "exit_mode": "after_commit",
            }
        )
        process = self.spawn_worker(spec)
        stdout, stderr = process.communicate(timeout=120)
        self.assertEqual(process.returncode, 17, stderr.decode("utf-8", "replace"))
        child = json.loads(Path(spec["result_file"]).read_text(encoding="utf-8"))
        self.runtime = self.make_runtime(data_dir)
        self.session = self.runtime.session()
        self.profile = self.session.scalars(select(LocalProfile)).one()
        self.assertEqual(
            self._current(observation_id)["payload"]["observation_goal"],
            "观察幼儿合作搭建",
        )
        # Reopening the candidate and current draft performs no AI task/attempt.
        detail = observation_ai_service.get_candidate(
            self.session,
            profile_id=profile_id,
            observation_id=observation_id,
            candidate_id=candidate_id,
        )
        self.assertEqual(detail["id"], candidate_id)
        self.assertEqual(
            query_scalar(self.runtime.db_path, "SELECT count(*) FROM local_ai_attempts"),
            attempts_before,
        )
        self.assertEqual(
            query_scalar(self.runtime.db_path, "SELECT count(*) FROM local_ai_tasks"),
            tasks_before,
        )
        self._preserve_evidence(
            "v01-cold-restart-after-commit",
            {
                "current": self._current(observation_id),
                "candidate": detail,
                "attempts": attempts_before,
                "tasks": tasks_before,
                "child_result": child["result"],
            },
        )
        replay = observation_ai_service.adopt(
            self.session,
            self.runtime,
            profile_id=profile_id,
            observation_id=observation_id,
            candidate_id=candidate_id,
            expected_revision=child["expected_revision"],
            expected_hash=child["expected_hash"],
            selected_targets=["observation_goal"],
            preview_token=child["preview_token"],
            request_id=request_id,
        )
        self.assertEqual(replay, child["result"])
        self._preserve_evidence(
            "v01-cold-restart-replay",
            {"replay": replay, "current": self._current(observation_id)},
        )


class ObservationAiRealTransportTests(ObservationAiCase):
    def test_real_worker_sends_complete_vision_request_without_internal_ids(self):
        import socket

        from app.local import ai_executor
        from tests.local import w3_tls
        from tests.local.obs_ai_workers import GENERATE

        ca_dir = self.tmp_root / "tls" / "ca"
        _cert, _key, ca_pem = w3_tls.create_ca(ca_dir)
        leaf_cert, leaf_key = w3_tls.create_leaf(
            ca_dir, self.tmp_root / "tls" / "leaf", hostname="api.deepseek.com"
        )
        server = w3_tls.TlsServer(
            cert=leaf_cert,
            key=leaf_key,
            reply=w3_tls.envelope(json.dumps(GENERATE, ensure_ascii=False)),
        ).start()
        self.addCleanup(server.stop)
        observation_id, asset_id = self._ready_observation()
        executor = ai_executor.AiExecutor(
            self.runtime,
            synthetic_transport={
                "resolution": [
                    {"family": socket.AF_INET, "ip": "127.0.0.1", "port": server.port}
                ],
                "ca_pem": ca_pem.decode("utf-8"),
            },
        )
        executor.start()
        self.addCleanup(executor.dispose)
        task = self._create_task(observation_id)
        executor.notify()
        self.assertEqual(self._wait_status(task["id"]), "succeeded")
        self.assertEqual(len(server.requests), 1)
        request = server.requests[0]
        headers, _, body = request.partition(b"\r\n\r\n")
        self.assertTrue(headers.startswith(b"POST /v1/chat/completions HTTP/1.1"))
        outer = json.loads(body.decode("utf-8"))
        self.assertEqual(outer["messages"][0]["role"], "system")
        content = outer["messages"][1]["content"]
        self.assertEqual(content[0]["type"], "text")
        image_items = [item for item in content if item["type"] == "image_url"]
        self.assertEqual(len(image_items), 1)
        self.assertTrue(
            image_items[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
        )
        decoded = __import__("base64").b64decode(
            image_items[0]["image_url"]["url"].split(",", 1)[1]
        )
        self.session.expire_all()
        derivative = self.session.scalars(
            select(LocalObservationAssetDerivative).where(
                LocalObservationAssetDerivative.observation_id == observation_id,
                LocalObservationAssetDerivative.asset_id == asset_id,
                LocalObservationAssetDerivative.purpose == "ai",
            )
        ).one()
        self.assertEqual(
            __import__("hashlib").sha256(decoded).hexdigest(),
            derivative.content_hash,
        )
        user_text = content[0]["text"]
        self.assertIn('"observation_date":"2026-09-15"', user_text)
        for forbidden in (
            "asset_id",
            "derivative_id",
            "term_id",
            "school_name",
            "class_name",
            "observer_name",
            "review_warning",
            "ai_supplemented_details",
        ):
            self.assertNotIn(forbidden, user_text)

    def test_post_send_unknown_is_not_replayed_on_notify_or_reopen(self):
        observation_id, _asset_id = self._ready_observation()
        executor = ai_executor.AiExecutor(
            self.runtime,
            worker_target=observation_worker_entry,
            synthetic_transport={"obs_mode": "exit_after_send"},
        )
        executor.start()
        self.addCleanup(executor.dispose)
        task = self._create_task(observation_id)
        executor.notify()
        self.assertEqual(self._wait_status(task["id"]), "outcome_unknown")
        attempts = query_scalar(
            self.runtime.db_path, "SELECT count(*) FROM local_ai_attempts"
        )
        executor.notify()
        time.sleep(0.5)
        self.assertEqual(
            query_scalar(self.runtime.db_path, "SELECT count(*) FROM local_ai_attempts"),
            attempts,
        )
        self.session.expire_all()
        self.assertEqual(self.session.get(LocalAITask, task["id"]).status, "outcome_unknown")

    def test_multi_target_late_sqlite_fault_rolls_back_all_and_token_retries(self):
        observation_id, _asset_id = self._ready_observation()
        candidate_id, _task, _executor = self._run_generate(observation_id)
        current = self._current(observation_id)
        preview = self._preview(
            observation_id,
            candidate_id,
            ["observation_goal", "analysis_evaluation"],
        )
        rid = str(uuid.uuid4())
        before = {
            "revision": current["revision"],
            "hash": current["payload_hash"],
            "versions": query_scalar(
                self.runtime.db_path,
                "SELECT count(*) FROM local_observation_versions WHERE observation_id = ?",
                (observation_id,),
            ),
            "version_photos": query_scalar(
                self.runtime.db_path,
                "SELECT count(*) FROM local_observation_version_photos",
            ),
            "provenance": query_scalar(
                self.runtime.db_path,
                "SELECT count(*) FROM local_observation_ai_provenance",
            ),
            "operations": query_scalar(
                self.runtime.db_path,
                "SELECT count(*) FROM local_observation_operations",
            ),
            "audits": query_scalar(
                self.runtime.db_path,
                "SELECT count(*) FROM local_operation_records WHERE action LIKE 'observation_%'",
            ),
        }
        self.session.execute(text("CREATE TABLE e0607_fault (id INTEGER PRIMARY KEY)"))
        self.session.execute(
            text(
                "CREATE TRIGGER e0607_fault_abort BEFORE INSERT ON e0607_fault "
                "BEGIN SELECT RAISE(ABORT, 'late adopt fault'); END"
            )
        )
        self.session.commit()
        marker = {}
        real_commit = self.session.commit

        def late_fault_commit():
            self.session.flush()
            self.session.expire_all()
            draft = self.session.get(LocalObservationDraft, observation_id)
            marker.update(
                {
                    "revision": draft.revision,
                    "hash": draft.payload_hash,
                    "versions": self.session.execute(
                        text("SELECT count(*) FROM local_observation_versions WHERE observation_id = :oid"),
                        {"oid": observation_id},
                    ).scalar_one(),
                    "version_photos": self.session.execute(
                        text("SELECT count(*) FROM local_observation_version_photos")
                    ).scalar_one(),
                    "provenance": self.session.execute(
                        text("SELECT count(*) FROM local_observation_ai_provenance")
                    ).scalar_one(),
                    "operations": self.session.execute(
                        text("SELECT count(*) FROM local_observation_operations")
                    ).scalar_one(),
                    "audits": self.session.execute(
                        text("SELECT count(*) FROM local_operation_records WHERE action LIKE 'observation_%'")
                    ).scalar_one(),
                    "reserved_by": observation_ai_service._TOKENS._items[
                        preview["adoption_token"]
                    ]["reserved_by"],
                }
            )
            self.session.execute(text("INSERT INTO e0607_fault DEFAULT VALUES"))

        try:
            with mock.patch.object(
                self.session, "commit", side_effect=late_fault_commit
            ):
                with self.assertRaises(Exception):
                    observation_ai_service.adopt(
                        self.session,
                        self.runtime,
                        profile_id=self.profile.id,
                        observation_id=observation_id,
                        candidate_id=candidate_id,
                        expected_revision=current["revision"],
                        expected_hash=current["payload_hash"],
                        selected_targets=["observation_goal", "analysis_evaluation"],
                        preview_token=preview["adoption_token"],
                        request_id=rid,
                    )
        finally:
            self.session.execute(text("DROP TRIGGER e0607_fault_abort"))
            self.session.execute(text("DROP TABLE e0607_fault"))
            self.session.commit()
        self.assertEqual(marker["revision"], current["revision"] + 1)
        self.assertEqual(marker["versions"], before["versions"] + 1)
        self.assertEqual(marker["version_photos"], before["version_photos"] + 1)
        self.assertEqual(marker["provenance"], before["provenance"] + 1)
        self.assertEqual(marker["operations"], before["operations"] + 1)
        self.assertEqual(marker["audits"], before["audits"] + 1)
        self.assertEqual(marker["reserved_by"], rid)
        after = self._current(observation_id)
        self.assertEqual(after["revision"], before["revision"])
        self.assertEqual(after["payload_hash"], before["hash"])
        for key, sql in (
            ("versions", "SELECT count(*) FROM local_observation_versions WHERE observation_id = ?"),
            ("version_photos", "SELECT count(*) FROM local_observation_version_photos"),
            ("provenance", "SELECT count(*) FROM local_observation_ai_provenance"),
            ("operations", "SELECT count(*) FROM local_observation_operations"),
            ("audits", "SELECT count(*) FROM local_operation_records WHERE action LIKE 'observation_%'"),
        ):
            params = (observation_id,) if key == "versions" else ()
            self.assertEqual(
                query_scalar(self.runtime.db_path, sql, params), before[key], key
            )
        self.assertIsNone(
            observation_ai_service._TOKENS._items[preview["adoption_token"]][
                "reserved_by"
            ]
        )
        evidence_root = self._evidence_root()
        (evidence_root / "r09-adopt-late-marker.json").write_text(
            json.dumps(marker, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self._preserve_evidence(
            "r09-adopt-late-fault",
            {"marker": marker, "before": before, "after": after},
        )
        retry = observation_ai_service.adopt(
            self.session,
            self.runtime,
            profile_id=self.profile.id,
            observation_id=observation_id,
            candidate_id=candidate_id,
            expected_revision=current["revision"],
            expected_hash=current["payload_hash"],
            selected_targets=["observation_goal", "analysis_evaluation"],
            preview_token=preview["adoption_token"],
            request_id=str(uuid.uuid4()),
        )
        self.assertTrue(retry["changed"])
        self._preserve_evidence(
            "r09-adopt-retry",
            {"retry": retry, "after_retry": self._current(observation_id)},
        )

    def test_same_token_two_concurrent_no_change_requests(self):
        import threading

        observation_id, _asset_id = self._ready_observation()
        candidate_id, _task, _executor = self._run_generate(observation_id)
        first = self._preview(observation_id, candidate_id, ["observation_goal"])
        self._adopt(observation_id, candidate_id, ["observation_goal"], first)
        current = self._current(observation_id)
        preview = self._preview(observation_id, candidate_id, ["observation_goal"])
        self.assertFalse(preview["changed"])
        barrier = threading.Barrier(2)
        results = []
        errors = []
        profile_id = self.profile.id

        def worker():
            session = self.runtime.session()
            try:
                barrier.wait(5)
                results.append(
                    observation_ai_service.adopt(
                        session,
                        self.runtime,
                        profile_id=profile_id,
                        observation_id=observation_id,
                        candidate_id=candidate_id,
                        expected_revision=current["revision"],
                        expected_hash=current["payload_hash"],
                        selected_targets=["observation_goal"],
                        preview_token=preview["adoption_token"],
                        request_id=str(uuid.uuid4()),
                    )
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                session.close()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(20)
        self.assertEqual(len(results), 1)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], LocalAiPreviewExpired)
        self.assertFalse(results[0]["changed"])

    def test_observation_attempt_uses_vision_budget_and_unknown_after_deadline(self):
        observation_id, _asset_id = self._ready_observation()
        with mock.patch.object(
            observation_ai_service.ai_transport,
            "VISION_ATTEMPT_BUDGET_MS",
            1500,
        ):
            executor = ai_executor.AiExecutor(
                self.runtime,
                worker_target=observation_worker_entry,
                synthetic_transport={"obs_mode": "silent_after_send"},
            )
            executor.start()
            self.addCleanup(executor.dispose)
            task = self._create_task(observation_id)
            executor.notify()
            self.assertEqual(self._wait_status(task["id"], timeout=15), "outcome_unknown")
        attempts = query_scalar(
            self.runtime.db_path, "SELECT count(*) FROM local_ai_attempts"
        )
        self.assertEqual(attempts, 1)
        executor.notify()
        time.sleep(0.5)
        self.assertEqual(
            query_scalar(self.runtime.db_path, "SELECT count(*) FROM local_ai_attempts"),
            1,
        )

    def _versions(self, observation_id):
        self.session.expire_all()
        return self.session.scalars(
            select(LocalObservationVersion)
            .where(LocalObservationVersion.observation_id == observation_id)
            .order_by(LocalObservationVersion.version)
        ).all()

    def test_auto_after_candidate_still_creates_history_node_without_revision(self):
        from tests.local.obs_ai_workers import GENERATE

        observation_id, _asset_id = self._ready_observation()
        candidate_id, _task, _executor = self._run_generate(observation_id)
        self._save(
            observation_id,
            {"observation_goal": GENERATE["observation_goal"]},
            reason="auto",
        )
        before_versions = len(self._versions(observation_id))
        current = self._current(observation_id)
        preview = self._preview(observation_id, candidate_id, ["observation_goal"])
        self.assertEqual(preview["source_state"], "source_changed")
        rid = str(uuid.uuid4())
        result = observation_ai_service.adopt(
            self.session,
            self.runtime,
            profile_id=self.profile.id,
            observation_id=observation_id,
            candidate_id=candidate_id,
            expected_revision=current["revision"],
            expected_hash=current["payload_hash"],
            selected_targets=["observation_goal"],
            preview_token=preview["adoption_token"],
            request_id=rid,
            review_decision="adopt_reviewed",
        )
        self.assertFalse(result["changed"])
        self.assertTrue(result["history_created"])
        self.assertEqual(result["revision"], current["revision"])
        versions = self._versions(observation_id)
        self.assertEqual(len(versions), before_versions + 1)
        self.assertEqual(versions[-1].payload_hash, self._current(observation_id)["payload_hash"])
        replay = observation_ai_service.adopt(
            self.session,
            self.runtime,
            profile_id=self.profile.id,
            observation_id=observation_id,
            candidate_id=candidate_id,
            expected_revision=current["revision"],
            expected_hash=current["payload_hash"],
            selected_targets=["observation_goal"],
            preview_token=preview["adoption_token"],
            request_id=rid,
            review_decision="adopt_reviewed",
        )
        self.assertEqual(replay, result)
        self.assertEqual(len(self._versions(observation_id)), before_versions + 1)

    def test_first_no_change_adoption_creates_first_history_node(self):
        from tests.local.obs_ai_workers import GENERATE

        created = self._create(observation_goal=GENERATE["observation_goal"])
        observation_id = created["observation_id"]
        self._import_photo(observation_id)
        current = self._current(observation_id)
        self._save(
            observation_id,
            {
                "observation_goal": GENERATE["observation_goal"],
                "observation_process": "幼儿在积木区搭建。",
            },
            reason="manual",
        )
        # Remove retained history while keeping the current draft, then make a
        # candidate whose selected goal already equals the current value.
        self.session.execute(
            text("UPDATE local_observation_records SET current_version = NULL")
        )
        self.session.execute(
            text("DELETE FROM local_observation_version_photos")
        )
        self.session.execute(text("DELETE FROM local_observation_versions"))
        self.session.commit()
        current = self._current(observation_id)
        self.assertEqual(self._versions(observation_id), [])
        candidate_id, _task, _executor = self._run_generate(observation_id)
        preview = self._preview(observation_id, candidate_id, ["observation_goal"])
        result = self._adopt(observation_id, candidate_id, ["observation_goal"], preview)
        self.assertFalse(result["changed"])
        self.assertTrue(result["history_created"])
        self.assertEqual(len(self._versions(observation_id)), 1)

    def test_auto_away_then_back_to_retained_content_does_not_duplicate_history(self):
        observation_id, _asset_id = self._ready_observation()
        candidate_id, _task, _executor = self._run_generate(observation_id)
        first = self._preview(observation_id, candidate_id, ["observation_goal"])
        self._adopt(observation_id, candidate_id, ["observation_goal"], first)
        versions_before = len(self._versions(observation_id))
        current_version = self._current(observation_id)["current_version"]
        self._save(observation_id, {"observation_goal": "临时离开"}, reason="auto")
        # A *new* candidate whose output happens to equal the retained node is
        # the authorized path for returning to that retained content.  The old
        # already-adopted candidate is never allowed to overwrite the auto edit.
        old_preview = self._preview(
            observation_id, candidate_id, ["observation_goal"]
        )
        self.assertEqual(old_preview["source_state"], "source_changed")
        with self.assertRaises(LocalAiTargetChanged):
            self._adopt(
                observation_id,
                candidate_id,
                ["observation_goal"],
                old_preview,
                review="adopt_reviewed",
            )
        new_candidate, _task2, _executor2 = self._run_generate(observation_id)
        preview = self._preview(
            observation_id, new_candidate, ["observation_goal"]
        )
        result = self._adopt(
            observation_id,
            new_candidate,
            ["observation_goal"],
            preview,
        )
        self.assertTrue(result["changed"])
        self.assertFalse(result["history_created"])
        self.assertEqual(len(self._versions(observation_id)), versions_before)
        self.assertEqual(self._current(observation_id)["current_version"], current_version)

    def test_review_fragments_are_bounded_for_large_valid_candidate(self):
        from app.local.prompt_bundles import validate_candidate
        from app.local.models import LocalAICandidate

        process = "\n".join('“短句”' for _ in range(20_000))
        raw = {
            "observation_goal": "目标",
            "observation_process": process,
            "analysis_evaluation": {
                "health": "",
                "language": "",
                "social": "",
                "science": "",
                "arts": "",
            },
            "support_strategy": "",
        }
        self.assertLessEqual(len(process), 100_000)
        validated = validate_candidate("game_observation_generate", raw)
        self.assertEqual(validated["observation_process"], process)
        candidate = LocalAICandidate(
            id="candidate",
            profile_id=self.profile.id,
            execution_id="execution",
            task_id="task",
            source_kind="game_observation",
            source_id="observation",
            observation_id="observation",
            daily_plan_id=None,
            input_id="input",
            task_type="game_observation_generate",
            contract_version=1,
            schema_version=1,
            raw_candidate_json=validated,
            candidate_hash="0" * 64,
        )
        metadata = observation_ai_service.candidate_review_metadata(
            candidate, validated
        )
        self.assertLessEqual(
            len(metadata["fragments"]), observation_ai_service.REVIEW_MAX_FRAGMENTS
        )
        self.assertLessEqual(
            len(json.dumps(metadata, ensure_ascii=False).encode("utf-8")),
            observation_ai_service.REVIEW_MAX_METADATA_BYTES,
        )
        self.assertTrue(metadata["fragments_truncated"])
        hints = observation_ai_service._validated_review_hints(
            validated,
            "game_observation_generate",
            list(observation_ai_inputs.TARGETS),
            metadata,
        )
        self.assertLessEqual(
            len(hints["fragments"]), observation_ai_service.REVIEW_MAX_FRAGMENTS
        )
        self.assertTrue(hints["fragments_truncated"])

    def test_begin_immediate_failure_releases_token_and_allows_retry(self):
        observation_id, _asset_id = self._ready_observation()
        candidate_id, _task, _executor = self._run_generate(observation_id)
        current = self._current(observation_id)
        preview = self._preview(observation_id, candidate_id, ["observation_goal"])
        rid = str(uuid.uuid4())
        before_versions = query_scalar(
            self.runtime.db_path,
            "SELECT count(*) FROM local_observation_versions WHERE observation_id = ?",
            (observation_id,),
        )
        before_operations = query_scalar(
            self.runtime.db_path,
            "SELECT count(*) FROM local_observation_operations",
        )
        with mock.patch.object(
            observation_ai_service,
            "begin_immediate",
            side_effect=sqlite3.OperationalError("database is locked"),
        ):
            with self.assertRaises(sqlite3.OperationalError):
                observation_ai_service.adopt(
                    self.session,
                    self.runtime,
                    profile_id=self.profile.id,
                    observation_id=observation_id,
                    candidate_id=candidate_id,
                    expected_revision=current["revision"],
                    expected_hash=current["payload_hash"],
                    selected_targets=["observation_goal"],
                    preview_token=preview["adoption_token"],
                    request_id=rid,
                )
        self.assertIsNone(
            observation_ai_service._TOKENS._items[preview["adoption_token"]][
                "reserved_by"
            ]
        )
        self.assertEqual(self._current(observation_id)["payload_hash"], current["payload_hash"])
        self.assertEqual(
            query_scalar(
                self.runtime.db_path,
                "SELECT count(*) FROM local_observation_versions WHERE observation_id = ?",
                (observation_id,),
            ),
            before_versions,
        )
        self.assertEqual(
            query_scalar(
                self.runtime.db_path,
                "SELECT count(*) FROM local_observation_operations",
            ),
            before_operations,
        )
        retry = observation_ai_service.adopt(
            self.session,
            self.runtime,
            profile_id=self.profile.id,
            observation_id=observation_id,
            candidate_id=candidate_id,
            expected_revision=current["revision"],
            expected_hash=current["payload_hash"],
            selected_targets=["observation_goal"],
            preview_token=preview["adoption_token"],
            request_id=str(uuid.uuid4()),
        )
        self.assertTrue(retry["changed"])
