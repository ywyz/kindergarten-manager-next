"""Pure listening display-direction, Word and AI working-image contracts."""

from __future__ import annotations

import contextlib
import hashlib
import io
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image, ImageOps
from pydantic import ValidationError

from app.local import (
    listening_ai_inputs,
    listening_assets,
    listening_direction,
    listening_export_service,
    listening_service,
    listening_templates,
)
from app.local.errors import LocalStorageError
from app.services.word_export_listening import ListeningWordPhoto
from tests.local.test_listening_word import _parts, _unit


def _payload(*, exif_orientation: int | None = None, fmt: str = "PNG") -> bytes:
    image = Image.new("RGB", (4, 3))
    colors = [
        (220, 20, 20), (20, 220, 20), (20, 20, 220), (240, 240, 20),
        (240, 20, 240), (20, 240, 240), (120, 20, 20), (20, 120, 20),
        (20, 20, 120), (240, 120, 20), (120, 240, 20), (20, 240, 120),
    ]
    image.putdata(colors)
    buffer = io.BytesIO()
    if fmt == "JPEG":
        exif = Image.Exif()
        if exif_orientation is not None:
            exif[0x0112] = exif_orientation
        image.save(buffer, format=fmt, quality=100, exif=exif)
    else:
        image.save(buffer, format=fmt)
    return buffer.getvalue()


def _reference(payload: bytes, orientation: int | None, quarters: int) -> Image.Image:
    with Image.open(io.BytesIO(payload)) as opened:
        opened.load()
        reference = (
            ImageOps.exif_transpose(opened).convert("RGB")
            if orientation is not None
            else opened.convert("RGB")
        )
        if quarters:
            reference = reference.rotate(-90 * quarters, expand=True)
        return reference.copy()


def _metadata(payload: bytes, orientation: int | None, quarters: int) -> dict:
    with Image.open(io.BytesIO(payload)) as opened:
        width, height = opened.size
    return {
        "mime_type": "image/jpeg" if payload[:2] == b"\xff\xd8" else "image/png",
        "width": width,
        "height": height,
        "orientation": orientation,
        "rotation_quarters": quarters,
    }


class DirectionHelperTests(unittest.TestCase):
    def test_all_exif_codes_and_quarter_turns_match_exif_transpose(self) -> None:
        payload = _payload(exif_orientation=1, fmt="JPEG")
        for orientation in range(1, 9):
            exif_payload = _payload(exif_orientation=orientation, fmt="JPEG")
            with Image.open(io.BytesIO(exif_payload)) as opened:
                opened.load()
                for quarters in range(4):
                    with self.subTest(orientation=orientation, quarters=quarters):
                        reference = _reference(
                            exif_payload, orientation, quarters
                        )
                        actual = listening_direction.apply_display_orientation(
                            opened,
                            orientation=orientation,
                            rotation_quarters=quarters,
                        ).convert("RGB")
                        self.assertEqual(actual.size, reference.size)
                        self.assertEqual(
                            list(actual.getdata()), list(reference.getdata())
                        )
        with Image.open(io.BytesIO(payload)) as opened:
            opened.load()
            self.assertEqual(
                listening_direction.apply_display_orientation(
                    opened, orientation=1, rotation_quarters=0
                ).size,
                opened.size,
            )

    def test_left_then_right_quarter_turns_restore(self) -> None:
        payload = _payload(fmt="PNG")
        with Image.open(io.BytesIO(payload)) as opened:
            opened.load()
            left = listening_direction.apply_display_orientation(
                opened, orientation=1, rotation_quarters=3
            )
            restored = listening_direction.apply_display_orientation(
                left, orientation=1, rotation_quarters=1
            )
            self.assertEqual(list(restored.getdata()), list(opened.getdata()))
            self.assertEqual(restored.size, opened.size)
            # The UI sends absolute targets: left 0→3, then right 3→0.
            self.assertEqual(
                listening_direction.apply_display_orientation(
                    opened, orientation=1, rotation_quarters=0
                ).size,
                opened.size,
            )

    def test_invalid_values_are_refused(self) -> None:
        for value in (-1, 4, True, None, "1"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    listening_direction.normalize_rotation_quarters(value)
        for value in (0, 9, True, "1"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    listening_direction.normalize_exif_orientation(value)


class WorkingImageTests(unittest.TestCase):
    def test_manual_rotation_keeps_source_hash_and_rotates_working_pixels(self) -> None:
        payload = _payload(fmt="PNG")
        metadata = _metadata(payload, 1, 1)
        prepared = listening_export_service._prepare_word_photo(payload, metadata)
        reference = _reference(payload, 1, 1)
        self.assertEqual(prepared["source_sha256"], hashlib.sha256(payload).hexdigest())
        self.assertEqual(prepared["source_bytes"], len(payload))
        self.assertEqual(prepared["rotation_quarters"], 1)
        self.assertEqual((prepared["width"], prepared["height"]), reference.size)
        with Image.open(io.BytesIO(prepared["data"])) as opened:
            opened.load()
            self.assertEqual(opened.convert("RGB").size, reference.size)
            self.assertEqual(
                list(opened.convert("RGB").getdata()), list(reference.getdata())
            )

    def test_orientation_one_zero_rotation_keeps_original_bytes(self) -> None:
        payload = _payload(fmt="PNG")
        metadata = _metadata(payload, 1, 0)
        prepared = listening_export_service._prepare_word_photo(payload, metadata)
        self.assertEqual(prepared["data"], payload)
        self.assertEqual(prepared["mime_type"], "image/png")
        self.assertEqual(prepared["rotation_quarters"], 0)

    def test_exif_orientation_plus_manual_rotation_dimensions(self) -> None:
        payload = _payload(exif_orientation=6, fmt="JPEG")
        metadata = _metadata(payload, 6, 1)
        prepared = listening_export_service._prepare_word_photo(payload, metadata)
        reference = _reference(payload, 6, 1)
        self.assertEqual((prepared["width"], prepared["height"]), reference.size)
        with Image.open(io.BytesIO(prepared["data"])) as opened:
            opened.load()
            self.assertEqual(opened.size, reference.size)

    def test_ai_working_image_uses_the_same_direction(self) -> None:
        payload = _payload(fmt="PNG")
        metadata = _metadata(payload, 1, 1)
        prepared = listening_ai_inputs._prepare_ai_image(payload, metadata)
        reference = _reference(payload, 1, 1)
        self.assertEqual((prepared["width"], prepared["height"]), reference.size)
        self.assertEqual(prepared["rotation_quarters"], 1)
        with Image.open(io.BytesIO(prepared["data"])) as output:
            output.load()
            actual = output.convert("RGB")
            expected = reference.getpixel((0, 0))
            got = actual.getpixel((0, 0))
            distance = sum(
                (got[index] - expected[index]) ** 2 for index in range(3)
            ) ** 0.5
            self.assertLess(distance, 60, (got, expected))

    def test_word_package_embeds_the_same_rotated_pixels(self) -> None:
        template = next(
            item
            for item in listening_templates.list_templates()
            if item.grade == "middle" and item.domain == "language"
        )
        payload = _payload(fmt="PNG")
        metadata = _metadata(payload, 1, 1)
        prepared = listening_export_service._prepare_word_photo(payload, metadata)
        photo = ListeningWordPhoto(
            "rotated-asset",
            prepared["data"],
            prepared["mime_type"],
            prepared["width"],
            prepared["height"],
            orientation=1,
        )
        output = listening_export_service.generate_listening_docx(
            (_unit(template, photos=(photo, None, None)),)
        )
        members = _parts(output)
        media = [name for name in members if name.startswith("word/media/")]
        self.assertEqual(len(media), 1)
        with Image.open(io.BytesIO(members[media[0]])) as embedded:
            embedded.load()
            reference = _reference(payload, 1, 1)
            self.assertEqual(embedded.size, reference.size)
            self.assertEqual(
                list(embedded.convert("RGB").getdata()),
                list(reference.getdata()),
            )


class _FakeSession:
    def __init__(self, asset: SimpleNamespace, commit_error=None) -> None:
        self.asset = asset
        self.added: list[object] = []
        self.commits = 0
        self.rollbacks = 0
        self.commit_error = commit_error

    def get(self, _model, key):
        return self.asset if key == self.asset.id else None

    def add(self, value: object) -> None:
        self.added.append(value)

    def commit(self) -> None:
        if self.commit_error is not None:
            raise self.commit_error
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class RotationPersistenceTests(unittest.TestCase):
    def _call(self, session, *, target=2, record_revision=5, replay=None):
        record = SimpleNamespace(revision=record_revision, updated_at=None)
        group = SimpleNamespace(id="group-1", asset_id="asset-1")
        with (
            patch.object(listening_assets, "read_scope", lambda _session: contextlib.nullcontext()),
            patch.object(listening_assets, "begin_immediate"),
            patch.object(listening_service, "_replay", return_value=replay),
            patch.object(
                listening_service,
                "_load_record",
                return_value=(record, None),
            ),
            patch.object(listening_service, "_groups", return_value=[group]),
            patch.object(listening_service, "_operation", return_value=None),
            patch.object(listening_service, "_audit", return_value=None),
        ):
            return listening_assets.rotate_group_photo(
                session,
                profile_id="profile-1",
                record_id="record-1",
                domain="health",
                group_id="group-1",
                request_id=str(uuid.uuid4()),
                expected_revision=5,
                rotation_quarters=target,
            )

    def test_rotation_persists_one_revision_without_asset_bytes(self) -> None:
        asset = SimpleNamespace(
            id="asset-1", record_id="record-1", rotation_quarters=1, orientation=6
        )
        session = _FakeSession(asset)
        result = self._call(session, target=2)
        self.assertEqual(asset.rotation_quarters, 2)
        self.assertEqual(result["old_rotation_quarters"], 1)
        self.assertEqual(result["rotation_quarters"], 2)
        self.assertEqual(result["orientation"], 6)
        self.assertEqual(result["revision"], 6)
        self.assertEqual(session.commits, 1)
        self.assertEqual(session.added, [])

    def test_revision_conflict_leaves_direction_and_assets_unchanged(self) -> None:
        asset = SimpleNamespace(
            id="asset-1", record_id="record-1", rotation_quarters=1, orientation=1
        )
        session = _FakeSession(asset)
        with self.assertRaises(listening_assets.ListeningAssetRevisionConflict):
            self._call(session, target=3, record_revision=4)
        self.assertEqual(asset.rotation_quarters, 1)
        self.assertEqual(session.commits, 0)
        self.assertEqual(session.rollbacks, 1)

    def test_replay_returns_without_read_or_write(self) -> None:
        asset = SimpleNamespace(
            id="asset-1", record_id="record-1", rotation_quarters=1, orientation=1
        )
        session = _FakeSession(asset)
        receipt = {"record_id": "record-1", "rotation_quarters": 3}
        result = self._call(session, target=3, replay=receipt)
        self.assertIs(result, receipt)
        self.assertEqual(asset.rotation_quarters, 1)
        self.assertEqual(session.commits, 0)

    def test_precommit_lock_failure_is_not_commit_uncertain(self) -> None:
        asset = SimpleNamespace(
            id="asset-1", record_id="record-1", rotation_quarters=1, orientation=1
        )
        session = _FakeSession(asset)
        with (
            patch.object(listening_assets, "read_scope", lambda _session: contextlib.nullcontext()),
            patch.object(
                listening_assets,
                "begin_immediate",
                side_effect=LocalStorageError("synthetic lock refusal"),
            ),
            patch.object(listening_service, "_replay", return_value=None),
        ):
            with self.assertRaises(LocalStorageError):
                listening_assets.rotate_group_photo(
                    session,
                    profile_id="profile-1",
                    record_id="record-1",
                    domain="health",
                    group_id="group-1",
                    request_id=str(uuid.uuid4()),
                    expected_revision=5,
                    rotation_quarters=2,
                )
        self.assertEqual(asset.rotation_quarters, 1)
        self.assertEqual(session.commits, 0)

    def test_commit_uncertainty_uses_the_dedicated_code(self) -> None:
        asset = SimpleNamespace(
            id="asset-1", record_id="record-1", rotation_quarters=1, orientation=1
        )
        session = _FakeSession(
            asset, commit_error=RuntimeError("synthetic commit uncertainty")
        )
        with self.assertRaises(listening_assets.ListeningRotationCommitUncertain):
            self._call(session, target=2)
        self.assertEqual(asset.rotation_quarters, 2)
        self.assertEqual(session.commits, 0)
        self.assertEqual(session.rollbacks, 1)

    def test_invalid_target_is_refused_before_any_session_work(self) -> None:
        asset = SimpleNamespace(
            id="asset-1", record_id="record-1", rotation_quarters=1, orientation=1
        )
        session = _FakeSession(asset)
        with self.assertRaises(listening_assets.ListeningMaterialInvalid):
            listening_assets.rotate_group_photo(
                session,
                profile_id="profile-1",
                record_id="record-1",
                domain="health",
                group_id="group-1",
                request_id=str(uuid.uuid4()),
                expected_revision=5,
                rotation_quarters=4,
            )
        self.assertEqual(asset.rotation_quarters, 1)
        self.assertEqual(session.commits, 0)


class MigrationSourceTests(unittest.TestCase):
    def test_rotation_migration_and_model_column_are_forward_only(self) -> None:
        backend_root = Path(__file__).resolve().parents[2]
        migration = (
            backend_root
            / "migrations_local"
            / "versions"
            / "20261108_0012_local_listening_rotation.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'revision: str = "20261108_0012_local_listening_rotation"',
            migration,
        )
        self.assertIn(
            'down_revision: Union[str, None] = "20261108_0011_local_config_ai"',
            migration,
        )
        self.assertIn("rotation_quarters", migration)
        self.assertIn("ck_local_listening_assets_rotation", migration)
        self.assertIn("Forward-only", migration)
        models = (backend_root / "app" / "local" / "models.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("rotation_quarters", models)
        self.assertIn("ck_local_listening_assets_rotation", models)

    def test_rotation_api_and_assets_keep_original_files(self) -> None:
        from app.local.listening_api import LocalListeningRotateIn, listening_router

        paths = {route.path for route in listening_router.routes}
        self.assertIn(
            "/api/listening/records/{record_id}/photos/rotations",
            paths,
        )
        self.assertIn(
            "/api/listening/records/{record_id}/domains/{domain}/photos/{group_id}/rotate",
            paths,
        )
        with self.assertRaises(ValidationError):
            LocalListeningRotateIn(
                request_id="request",
                expected_revision=1,
                rotation_quarters=4,
            )
        backend_root = Path(__file__).resolve().parents[2]
        assets_source = (
            backend_root / "app" / "local" / "listening_assets.py"
        ).read_text(encoding="utf-8")
        rotate_body = assets_source.split("def rotate_group_photo", 1)[1].split(
            "def read_asset", 1
        )[0]
        self.assertIn("asset.rotation_quarters = target", rotate_body)
        self.assertIn("ListeningRotationCommitUncertain", rotate_body)
        self.assertIn("commit_started = True", rotate_body)
        self.assertNotIn("_write_staging", rotate_body)
        self.assertNotIn("_move_file", rotate_body)
        self.assertNotIn("os.unlink", rotate_body)
        service_source = (
            backend_root / "app" / "local" / "listening_service.py"
        ).read_text(encoding="utf-8")
        self.assertIn('"rotations": {', service_source)
        self.assertIn("LocalListeningAsset.record_id == record.id", service_source)


if __name__ == "__main__":
    unittest.main()
