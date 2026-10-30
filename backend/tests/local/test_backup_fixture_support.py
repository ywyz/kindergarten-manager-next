"""Self-test for the reusable synthetic backup/restore fixture.

These tests prove the fixture itself is legal and complete: they re-read the
synthetic SQLite database through the ordinary business services, decode every
managed image with Pillow, check hashes/sizes/references, and demonstrate that
the fingerprints do not depend on SQLite page layout but do react to business
and schema changes.  They do not run B1 backup/restore code, do not call a
supplier and do not measure the 600-photo capacity package (that measurement is
left to the later capacity test).
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from app.local import prompt_service
from app.local.base import LocalBase
from app.local.models import (
    LocalDailyPlanRestore,
    LocalObservationAsset,
    LocalObservationAssetDerivative,
    LocalPersonalPromptVersion,
)
from sqlalchemy import select

from tests.local import backup_fixture_support as fixture
from tests.local.support import LocalTestCase


class BackupFixtureSupportTests(LocalTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.runtime = self.make_runtime()
        self.evidence = fixture.seed_existing_runtime(self.runtime)

    # -- fixture completeness ------------------------------------------------
    def test_fixture_is_legal_complete_and_business_readable(self) -> None:
        evidence = self.evidence
        self.assertTrue(evidence.verified)
        self.assertEqual(evidence.capacity_photo_count, 0)
        self.assertEqual(
            evidence.schema_revision, self.runtime.current_revision
        )
        self.assertEqual(
            len(evidence.fingerprint["database"]["tables"]),
            len(LocalBase.metadata.tables),
        )
        self.assertEqual(
            len(LocalBase.metadata.tables), 41
        )
        self.assertEqual(len(evidence.calendar_revision_ids), 2)
        self.assertEqual(len(evidence.class_game_revision_ids), 2)
        self.assertEqual(evidence.daily_plan_content_versions, (1, 2, 3, 4))
        self.assertEqual(evidence.daily_plan_current_version, 4)
        self.assertEqual(evidence.settings_config_version, 5)
        for label in ("public", "indoor", "outdoor"):
            self.assertGreaterEqual(
                len(evidence.observation_versions[label]), 2, label
            )
        self.assertEqual(evidence.observation_versions["public"], (1, 2, 3, 4))
        self.assertEqual(evidence.observation_versions["indoor"], (1, 2))
        self.assertEqual(evidence.observation_versions["outdoor"], (1, 2))
        self.assertEqual(fixture.staging_report(self.runtime.data_dir)["files"], [])

        counts = evidence.counts
        self.assertEqual(counts["local_ai_tasks.status.succeeded"], 2)
        self.assertEqual(counts["local_ai_tasks.status.failed"], 1)
        self.assertEqual(counts["local_ai_tasks.status.outcome_unknown"], 1)
        self.assertEqual(counts["local_observation_records.type.public"], 1)
        self.assertEqual(counts["local_observation_records.type.indoor"], 1)
        self.assertEqual(counts["local_observation_records.type.outdoor"], 1)
        self.assertEqual(counts["local_observation_assets"], 4)
        self.assertEqual(
            counts["local_observation_asset_derivatives"], 8
        )
        self.assertEqual(
            counts["local_observation_asset_derivatives.purpose.ai"], 4
        )
        self.assertEqual(
            counts["local_observation_asset_derivatives.purpose.export"], 4
        )
        self.assertEqual(counts["local_ai_credentials.state.active"], 1)
        self.assertEqual(counts["local_daily_plan_restores"], 1)
        self.assertEqual(counts["local_observation_restores"], 1)
        self.assertEqual(counts["local_observation_restore_previews"], 1)
        self.assertEqual(counts["local_config_operations"], 4)
        self.assertGreaterEqual(counts["local_prompt_bundles"], 5)
        self.assertGreaterEqual(counts["local_personal_prompt_versions"], 5)
        self.assertEqual(
            set(evidence.asset_ids),
            {"primary_current", "primary_historical", "failed", "unknown"},
        )
        self.assertEqual(
            json.loads(json.dumps(evidence.as_dict(), ensure_ascii=False))[
                "verified"
            ],
            True,
        )

        # The initial personal prompt revision survives the teacher edit.
        session = self.runtime.session()
        try:
            versions = session.scalars(
                select(LocalPersonalPromptVersion)
            ).all()
            split_versions = [
                item
                for item in versions
                if item.task_type == "daily_lesson_split"
            ]
            self.assertEqual(
                sorted(item.revision for item in split_versions), [1, 2]
            )
            output = prompt_service.get_prompt(
                session, task_type="daily_lesson_split"
            )
            self.assertEqual(output["personal_revision"], 2)
            self.assertEqual(output["contract_version"], 1)
        finally:
            session.close()

        # Old execution parameters are preserved while the current head moved.
        old = evidence.ai_executions["daily_plan_split"]
        current = evidence.ai_executions["primary_generate"]
        self.assertEqual(old["config_version"], 1)
        self.assertEqual(old["personal_revision"], 1)
        self.assertEqual(old["contract_version"], 1)
        self.assertEqual(current["config_version"], 2)
        self.assertEqual(current["personal_revision"], 1)
        self.assertEqual(current["contract_version"], 1)
        self.assertEqual(
            evidence.ai_tasks["failed_generate"]["reason"],
            "connection_unavailable",
        )
        self.assertEqual(
            evidence.ai_tasks["unknown_generate"]["reason"],
            "timeout_after_dispatch",
        )

        # The historical-only photo really exists on disk, is referenced by a
        # retained version and is absent from the current draft.
        self.assertEqual(len(evidence.historical_only_asset_ids), 1)
        historical_asset_id = evidence.historical_only_asset_ids[0]
        session = self.runtime.session()
        try:
            restore_receipt = session.scalars(
                select(LocalDailyPlanRestore)
            ).one()
            self.assertEqual(
                restore_receipt.request_id,
                evidence.daily_plan_restore_request_id,
            )
            asset = session.get(LocalObservationAsset, historical_asset_id)
            self.assertIsNotNone(asset)
            path = Path(self.runtime.data_dir) / asset.relative_path
            self.assertTrue(path.is_file())
            with Image.open(path) as image:
                image.load()
                self.assertEqual((image.width, image.height), (asset.width, asset.height))
            self.assertNotIn(
                historical_asset_id,
                evidence.current_photo_asset_ids["public"],
            )
            self.assertIn(
                historical_asset_id,
                evidence.version_photo_refs["public"][1],
            )
        finally:
            session.close()

        # Every original/derivative is a real decodable image with matching
        # database metadata, and the AI input pins original/work hashes.
        session = self.runtime.session()
        try:
            assets = session.scalars(select(LocalObservationAsset)).all()
            derivatives = session.scalars(
                select(LocalObservationAssetDerivative)
            ).all()
        finally:
            session.close()
        for asset in assets:
            with Image.open(
                Path(self.runtime.data_dir) / asset.relative_path
            ) as image:
                image.load()
                self.assertEqual(image.size, (asset.width, asset.height))
                self.assertEqual(
                    image.format.lower(),
                    "jpeg" if asset.mime_type == "image/jpeg" else "png",
                )
        for derivative in derivatives:
            with Image.open(
                Path(self.runtime.data_dir) / derivative.relative_path
            ) as image:
                image.load()
                self.assertEqual(image.format, "JPEG")
                self.assertEqual(
                    image.size, (derivative.width, derivative.height)
                )

        # Synthetic credential material is encrypted, isolated and comparable,
        # and the plaintext never appears in the SQLite file.
        credential = evidence.credential
        self.assertEqual(credential["nonce_size"], 12)
        self.assertGreaterEqual(credential["ciphertext_size"], 16)
        self.assertTrue(credential["synthetic_plaintext_absent"])
        dpapi_path = (
            Path(evidence.credential_root)
            / credential["database_uuid"]
            / f"{credential['key_id']}.dpapi"
        )
        self.assertTrue(dpapi_path.is_file())
        self.assertGreater(dpapi_path.stat().st_size, 0)

        # The independent verifier re-reads everything and agrees.
        checks = fixture.validate_fixture(self.runtime, evidence)
        self.assertEqual(checks["integrity_check"], "ok")
        self.assertEqual(checks["foreign_key_check"], "ok")
        self.assertEqual(checks["business_reads"], "ok")
        self.assertEqual(checks["photos"], "ok")
        self.assertEqual(checks["ai"], "ok")
        self.assertEqual(checks["credentials"], "ok")
        self.assertEqual(
            checks["runtime_fingerprint"], evidence.fingerprint
        )

        # A second seed must not append to a non-empty business database.
        with self.assertRaises(fixture.FixtureError):
            fixture.seed_existing_runtime(self.runtime)

    # -- fingerprints --------------------------------------------------------
    def test_fingerprint_ignores_page_layout_and_detects_business_change(
        self,
    ) -> None:
        source_db = Path(self.runtime.db_path)
        baseline = fixture.database_fingerprint(source_db)
        excluded = baseline["excluded_fields"]
        self.assertGreaterEqual(len(excluded), 1)
        self.assertTrue(all(item["reason"] for item in excluded))
        strict = fixture.database_fingerprint(
            source_db, include_runtime_fields=True
        )
        self.assertEqual(strict["excluded_fields"], [])
        self.assertNotEqual(
            strict["fingerprint_sha256"], baseline["fingerprint_sha256"]
        )

        copy_dir = self.tmp_root / "fingerprint-copy"
        copy_dir.mkdir()
        copy_db = copy_dir / "kindergarten.db"
        self._copy_database(source_db, copy_db)

        # Same rows, different physical page layout/page size/journal mode.
        connection = sqlite3.connect(str(copy_db))
        try:
            before_page_size = connection.execute(
                "PRAGMA page_size"
            ).fetchone()[0]
            # SQLite keeps the old page size on VACUUM while the copy is in
            # WAL mode; switch the *copy* to rollback journal first.
            connection.execute("PRAGMA journal_mode=DELETE")
            connection.execute("PRAGMA page_size=2048")
            connection.execute("VACUUM")
            after_page_size = connection.execute(
                "PRAGMA page_size"
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(after_page_size, 2048)
        self.assertNotEqual(before_page_size, after_page_size)
        vacuumed = fixture.database_fingerprint(copy_db)
        self.assertEqual(vacuumed, baseline)
        self.assertEqual(
            vacuumed["fingerprint_sha256"], baseline["fingerprint_sha256"]
        )

        # A real business value change must change the fingerprint.
        self._mutate(copy_db, "UPDATE local_settings SET school_name='别的幼儿园'")
        changed = fixture.database_fingerprint(copy_db)
        self.assertNotEqual(
            changed["fingerprint_sha256"], baseline["fingerprint_sha256"]
        )
        self.assertNotEqual(
            changed["tables"]["local_settings"]["rows_sha256"],
            baseline["tables"]["local_settings"]["rows_sha256"],
        )

        # A schema change (extra column) must change the fingerprint too.
        schema_dir = self.tmp_root / "fingerprint-schema"
        schema_dir.mkdir()
        schema_db = schema_dir / "kindergarten.db"
        self._copy_database(source_db, schema_db)
        self._mutate(schema_db, "ALTER TABLE local_settings ADD COLUMN probe TEXT")
        schema_changed = fixture.database_fingerprint(schema_db)
        self.assertNotEqual(
            schema_changed["fingerprint_sha256"], baseline["fingerprint_sha256"]
        )
        self.assertEqual(
            schema_changed["tables"]["local_settings"]["db_only_columns"],
            ["probe"],
        )

        # A changed image byte must change the resource fingerprint.
        resources = fixture.resource_fingerprint(self.runtime.data_dir)
        copied_data = self.tmp_root / "fingerprint-resources"
        shutil.copytree(
            Path(self.runtime.data_dir) / "observations",
            copied_data / "observations",
        )
        copied = fixture.resource_fingerprint(copied_data)
        self.assertEqual(copied, resources)
        first_file = sorted(
            (copied_data / "observations" / "assets").rglob("*")
        )
        first_file = next(path for path in first_file if path.is_file())
        payload = bytearray(first_file.read_bytes())
        payload[0] ^= 0xFF
        first_file.write_bytes(bytes(payload))
        mutated = fixture.resource_fingerprint(copied_data)
        self.assertNotEqual(
            mutated["fingerprint_sha256"], resources["fingerprint_sha256"]
        )
        self.assertNotEqual(
            mutated["files"], resources["files"]
        )

    # -- optional capacity mode ---------------------------------------------
    def test_capacity_mode_uses_real_decodable_photos(self) -> None:
        capacity_data = self.tmp_root / "capacity-data"
        capacity_credentials = self.tmp_root / "capacity-credentials"
        runtime = self.make_runtime(
            data_dir=capacity_data, credential_root=capacity_credentials
        )
        evidence = fixture.seed_existing_runtime(
            runtime,
            capacity_photo_count=6,
            capacity_photo_size=(240, 180),
        )
        self.assertTrue(evidence.verified)
        self.assertEqual(evidence.capacity_photo_count, 6)
        self.assertEqual(len(evidence.capacity_asset_ids), 6)
        self.assertEqual(
            evidence.counts["local_observation_records.type.public"], 2
        )
        self.assertEqual(evidence.counts["local_observation_assets"], 10)
        self.assertEqual(
            evidence.counts["local_observation_asset_derivatives"], 20
        )
        self.assertGreaterEqual(fixture.MAX_CAPACITY_PHOTOS, 600)
        session = runtime.session()
        try:
            for asset_id in evidence.capacity_asset_ids:
                asset = session.get(LocalObservationAsset, asset_id)
                self.assertIsNotNone(asset)
                path = Path(runtime.data_dir) / asset.relative_path
                self.assertTrue(path.is_file())
                self.assertGreater(path.stat().st_size, 0)
                with Image.open(path) as image:
                    image.load()
                    self.assertEqual(
                        image.size, (asset.width, asset.height)
                    )
        finally:
            session.close()
        fixture.validate_fixture(runtime, evidence)

    # -- root guard ----------------------------------------------------------
    def test_refuses_default_user_roots_and_overlapping_roots(self) -> None:
        fake_local = self.tmp_root / "fake-localappdata"
        default_data = fake_local / "KindergartenManager" / "data"
        default_credentials = (
            fake_local / "KindergartenManager" / "credentials"
        )
        runtime = self.make_runtime(
            data_dir=default_data, credential_root=default_credentials
        )
        with mock.patch.dict(
            "os.environ", {"LOCALAPPDATA": str(fake_local)}, clear=False
        ):
            with self.assertRaises(fixture.FixtureRootError):
                fixture.seed_existing_runtime(runtime)

        overlap = self.tmp_root / "overlap"
        overlap_runtime = self.make_runtime(
            data_dir=overlap, credential_root=overlap
        )
        with self.assertRaises(fixture.FixtureRootError):
            fixture.seed_existing_runtime(overlap_runtime)

    # -- helpers -------------------------------------------------------------
    @staticmethod
    def _copy_database(source: Path, destination: Path) -> None:
        source_connection = sqlite3.connect(str(source))
        destination_connection = sqlite3.connect(str(destination))
        try:
            source_connection.backup(destination_connection)
        finally:
            destination_connection.close()
            source_connection.close()

    @staticmethod
    def _mutate(db_path: Path, sql: str) -> None:
        connection = sqlite3.connect(str(db_path))
        try:
            connection.execute(sql)
            connection.commit()
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
