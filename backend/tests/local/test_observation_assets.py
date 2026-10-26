"""E03 managed observation material tests (synthetic images only)."""

from __future__ import annotations

import base64
import errno
import hashlib
import io
import json
import os
import shutil
import subprocess
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from unittest import mock

from PIL import Image, ImageCms
from PIL.PngImagePlugin import PngInfo
from sqlalchemy import select, text

from app.local import observation_assets, profile_service
from app.local.models import (
    LocalAIInput,
    LocalObservationAIInputPhoto,
    LocalObservationAsset,
    LocalObservationAssetDerivative,
    LocalObservationDraft,
    LocalObservationDraftPhoto,
    LocalObservationOperation,
    LocalObservationRecord,
    LocalObservationVersion,
    LocalObservationVersionPhoto,
    LocalOperationRecord,
    LocalProfile,
)
from app.local.normalize import normalize_initialization
from app.local.observation_validation import aggregate_hash, normalize_payload
from tests.local.support import LocalTestCase, initialize_body


class ObservationAssetTests(LocalTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.runtime = self.make_runtime()
        self.session = self.runtime.session()
        profile_service.initialize(
            self.session, normalize_initialization(**initialize_body())
        )
        self.session.commit()
        self.profile = self.session.scalars(select(LocalProfile)).one()
        self.now = datetime(2026, 10, 26, 10, 0, 0)
        self.payload = normalize_payload({"record_type": "public"})
        self._make_record("obs-1")
        self._make_record("obs-2")

    def tearDown(self) -> None:
        self.session.close()
        super().tearDown()

    def _make_record(self, observation_id: str) -> None:
        record = LocalObservationRecord(
            id=observation_id,
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
        self.session.flush()
        self.session.add(
            LocalObservationDraft(
                observation_id=observation_id,
                revision=1,
                payload_json=self.payload,
                payload_hash=aggregate_hash(self.payload, []),
                created_at=self.now,
                updated_at=self.now,
            )
        )
        self.session.commit()

    def _jpeg(
        self,
        *,
        size=(64, 48),
        orientation=None,
        comment=None,
        exif=None,
        icc=None,
        color="red",
    ) -> bytes:
        image = Image.new("RGB", size, color)
        buffer = io.BytesIO()
        kwargs = {}
        if orientation is not None:
            exif_obj = Image.Exif()
            exif_obj[0x0112] = orientation
            kwargs["exif"] = exif_obj.tobytes()
        elif exif is not None:
            kwargs["exif"] = exif
        if comment is not None:
            kwargs["comment"] = comment
        if icc is not None:
            kwargs["icc_profile"] = icc
        image.save(buffer, "JPEG", quality=90, **kwargs)
        return buffer.getvalue()

    def _png(self, *, text=False, exif=False, xmp=False) -> bytes:
        image = Image.new("RGBA", (40, 30), (20, 80, 160, 128))
        buffer = io.BytesIO()
        info = PngInfo()
        kwargs = {}
        if text:
            info.add_text("private-note", "synthetic-private-text")
        if xmp:
            info.add_itxt("XML:com.adobe.xmp", "<x:xmpmeta>private</x:xmpmeta>")
        if exif:
            exif_obj = Image.Exif()
            exif_obj[0x0112] = 6
            kwargs["exif"] = exif_obj.tobytes()
        image.save(buffer, "PNG", pnginfo=info, **kwargs)
        return buffer.getvalue()

    def _webp(self, *, exif=False, xmp=False, icc=False) -> bytes:
        image = Image.new("RGBA", (40, 30), (20, 80, 160, 128))
        buffer = io.BytesIO()
        kwargs = {}
        if exif:
            exif_obj = Image.Exif()
            exif_obj[0x0112] = 6
            kwargs["exif"] = exif_obj.tobytes()
        if xmp:
            kwargs["xmp"] = b"<x:xmpmeta>private</x:xmpmeta>"
        if icc:
            profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
            kwargs["icc_profile"] = profile.tobytes()
        image.save(buffer, "WEBP", quality=90, **kwargs)
        return buffer.getvalue()

    def _import(self, data: bytes, *, name="a.jpg", caption=None, request_id=None, expected=1, record="obs-1"):
        return observation_assets.import_asset(
            self.session,
            self.runtime,
            profile_id=self.profile.id,
            observation_id=record,
            request_id=request_id or str(uuid.uuid4()),
            expected_revision=expected,
            stream=io.BytesIO(data),
            display_name=name,
            caption=caption,
        )

    def _assert_no_private_metadata(self, data: bytes) -> None:
        with Image.open(io.BytesIO(data)) as image:
            self.assertNotIn("comment", image.info)
            self.assertNotIn("exif", image.info)
            self.assertNotIn("xmp", image.info)
            self.assertNotIn("icc_profile", image.info)
            self.assertNotIn("XML:com.adobe.xmp", image.info)
            self.assertEqual(dict(image.getexif()), {})

    def test_jpeg_orientation_comment_and_original_bytes(self):
        source = self._jpeg(
            size=(80, 40),
            orientation=6,
            comment=b"synthetic-private-comment",
        )
        result = self._import(source, caption="说明")
        self.assertTrue(result["changed"])
        self.assertEqual(result["revision"], 2)
        self.assertEqual(result["orientation"], 6)
        self.assertEqual((result["width"], result["height"]), (80, 40))
        self.assertEqual(
            observation_assets.read_asset_bytes(
                self.session,
                self.runtime,
                profile_id=self.profile.id,
                observation_id="obs-1",
                asset_id=result["asset_id"],
            ),
            source,
        )
        ai = observation_assets.read_derivative_bytes(
            self.session,
            self.runtime,
            profile_id=self.profile.id,
            observation_id="obs-1",
            asset_id=result["asset_id"],
            purpose="ai",
            params_version=observation_assets.AI_PARAMS_VERSION,
        )
        export = observation_assets.read_derivative_bytes(
            self.session,
            self.runtime,
            profile_id=self.profile.id,
            observation_id="obs-1",
            asset_id=result["asset_id"],
            derivative_id=result["derivative_ids"]["export"],
        )
        self._assert_no_private_metadata(ai)
        self._assert_no_private_metadata(export)
        with Image.open(io.BytesIO(ai)) as image:
            self.assertEqual(image.size, (40, 80))
        with Image.open(io.BytesIO(export)) as image:
            self.assertEqual(image.size, (40, 80))

    def test_ai_target_failure_and_params_version(self):
        result = self._import(self._jpeg(size=(600, 400)), name="params.jpg")
        derivative = self.session.scalars(
            select(LocalObservationAssetDerivative).where(
                LocalObservationAssetDerivative.asset_id == result["asset_id"],
                LocalObservationAssetDerivative.purpose == "ai",
            )
        ).one()
        self.assertEqual(derivative.params_version, observation_assets.AI_PARAMS_VERSION)
        self.assertIn("target2mib", derivative.params_version)
        self.assertIn("scale085", derivative.params_version)
        with mock.patch.object(observation_assets, "AI_TARGET_BYTES", 1):
            with self.assertRaises(observation_assets.ObservationMaterialLimit):
                self._import(self._jpeg(size=(600, 400)), name="target.jpg", expected=2)
        self.assertEqual(
            len(
                self.session.scalars(
                    select(LocalObservationAsset).where(
                        LocalObservationAsset.observation_id == "obs-1"
                    )
                ).all()
            ),
            1,
        )

    def test_nested_exif_gps_is_valid_and_broken_pointers_are_rejected(self):
        import struct

        # IFD0 -> GPS IFD -> GPSLatitude data.  The GPS IFD is legal nested
        # EXIF, not a malformed pointer, and must remain in the original bytes.
        tiff = b"II*\x00" + struct.pack("<I", 8)
        tiff += struct.pack("<H", 1)
        tiff += struct.pack("<HHII", 0x8825, 4, 1, 26)
        tiff += struct.pack("<I", 0)
        tiff += struct.pack("<H", 2)
        tiff += struct.pack("<HHII", 1, 2, 2, int.from_bytes(b"N\x00\x00\x00", "little"))
        tiff += struct.pack("<HHII", 2, 5, 3, 56)
        tiff += struct.pack("<I", 0)
        tiff += struct.pack("<II", 1, 1)
        tiff += struct.pack("<II", 2, 1)
        tiff += struct.pack("<II", 3, 1)
        source = self._jpeg(exif=b"Exif\x00\x00" + tiff)
        result = self._import(source, name="gps.jpg")
        self.assertEqual(
            observation_assets.read_asset_bytes(
                self.session,
                self.runtime,
                profile_id=self.profile.id,
                observation_id="obs-1",
                asset_id=result["asset_id"],
            ),
            source,
        )
        ai = observation_assets.read_derivative_bytes(
            self.session,
            self.runtime,
            profile_id=self.profile.id,
            observation_id="obs-1",
            asset_id=result["asset_id"],
            purpose="ai",
            params_version=observation_assets.AI_PARAMS_VERSION,
        )
        self._assert_no_private_metadata(ai)

        thumbnail = b"II*\x00" + struct.pack("<I", 8)
        thumbnail += struct.pack("<H", 0) + struct.pack("<I", 14)
        thumbnail += struct.pack("<H", 2)
        thumbnail += struct.pack("<HHII", 0x0201, 4, 1, 44)
        thumbnail += struct.pack("<HHII", 0x0202, 4, 1, 4)
        thumbnail += struct.pack("<I", 0)
        thumbnail += b"\xff\xd8\xff\xd9"
        thumbnail_source = self._jpeg(exif=b"Exif\x00\x00" + thumbnail)
        thumbnail_result = self._import(
            thumbnail_source, name="thumbnail.jpg", expected=2
        )
        self.assertEqual(
            observation_assets.read_asset_bytes(
                self.session,
                self.runtime,
                profile_id=self.profile.id,
                observation_id="obs-1",
                asset_id=thumbnail_result["asset_id"],
            ),
            thumbnail_source,
        )

        bad_gps = (
            b"II*\x00" + struct.pack("<I", 8) + struct.pack("<H", 1)
            + struct.pack("<HHII", 0x8825, 4, 1, 0xFFFFFF00)
            + struct.pack("<I", 0)
        )
        bad_next = (
            b"II*\x00" + struct.pack("<I", 8) + struct.pack("<H", 0)
            + struct.pack("<I", 0xFFFFFF00)
        )
        bad_cycle = (
            b"II*\x00" + struct.pack("<I", 8) + struct.pack("<H", 1)
            + struct.pack("<HHII", 0x8825, 4, 1, 8)
            + struct.pack("<I", 0)
        )
        for name, payload in (
            ("gps.jpg", bad_gps),
            ("next.jpg", bad_next),
            ("cycle.jpg", bad_cycle),
        ):
            with self.subTest(name=name):
                with self.assertRaises(observation_assets.ObservationMaterialInvalid):
                    self._import(
                        self._jpeg(exif=b"Exif\x00\x00" + payload),
                        name=name,
                        expected=3,
                    )
        self.assertEqual(
            len(
                self.session.scalars(
                    select(LocalObservationAsset).where(
                        LocalObservationAsset.observation_id == "obs-1"
                    )
                ).all()
            ),
            2,
        )

    def test_shared_exif_ifd_is_not_a_cycle_but_true_cycle_is_rejected(self):
        import struct

        shared = b"II*\x00" + struct.pack("<I", 8)
        shared += struct.pack("<H", 2)
        shared += struct.pack("<HHII", 0x8825, 4, 1, 38)
        shared += struct.pack("<HHII", 0x8769, 4, 1, 38)
        shared += struct.pack("<I", 0)
        shared += struct.pack("<H", 1)
        shared += struct.pack("<HHII", 1, 2, 2, int.from_bytes(b"N\x00\x00\x00", "little"))
        shared += struct.pack("<I", 0)
        source = self._jpeg(exif=b"Exif\x00\x00" + shared)
        result = self._import(source, name="shared-ifd.jpg")
        self.assertEqual(
            observation_assets.read_asset_bytes(
                self.session,
                self.runtime,
                profile_id=self.profile.id,
                observation_id="obs-1",
                asset_id=result["asset_id"],
            ),
            source,
        )
        cycle = (
            b"II*\x00" + struct.pack("<I", 8) + struct.pack("<H", 1)
            + struct.pack("<HHII", 0x8825, 4, 1, 8)
            + struct.pack("<I", 0)
        )
        with self.assertRaises(observation_assets.ObservationMaterialInvalid):
            self._import(
                self._jpeg(exif=b"Exif\x00\x00" + cycle),
                name="cycle.jpg",
                expected=2,
            )

    def test_broken_exif_is_rejected(self):
        source = self._jpeg(exif=b"Exif\x00\x00broken-exif")
        with self.assertRaises(observation_assets.ObservationMaterialInvalid):
            self._import(source)
        self.assertEqual(
            self.session.scalar(select(LocalObservationAsset).where(LocalObservationAsset.observation_id == "obs-1")),
            None,
        )

    def test_png_and_webp_metadata_are_stripped(self):
        png = self._png(text=True, exif=True, xmp=True)
        result = self._import(png, name="a.png")
        ai = observation_assets.read_derivative_bytes(
            self.session,
            self.runtime,
            profile_id=self.profile.id,
            observation_id="obs-1",
            asset_id=result["asset_id"],
            purpose="ai",
            params_version=observation_assets.AI_PARAMS_VERSION,
        )
        self._assert_no_private_metadata(ai)
        webp = self._webp(exif=True, xmp=True, icc=True)
        result2 = self._import(webp, name="b.webp", expected=2)
        ai2 = observation_assets.read_derivative_bytes(
            self.session,
            self.runtime,
            profile_id=self.profile.id,
            observation_id="obs-1",
            asset_id=result2["asset_id"],
            purpose="ai",
            params_version=observation_assets.AI_PARAMS_VERSION,
        )
        self._assert_no_private_metadata(ai2)

    def test_static_gif_and_bmp_and_animated_gif(self):
        buffer = io.BytesIO()
        Image.new("P", (20, 20), 0).save(buffer, "GIF")
        self._import(buffer.getvalue(), name="a.gif")
        buffer = io.BytesIO()
        Image.new("RGB", (20, 20), "blue").save(buffer, "BMP")
        self._import(buffer.getvalue(), name="a.bmp", expected=2)
        frames = [
            Image.new("RGB", (20, 20), (255, 0, 0)),
            Image.new("RGB", (20, 20), (0, 0, 255)),
        ]
        buffer = io.BytesIO()
        frames[0].save(
            buffer, "GIF", save_all=True, append_images=frames[1:],
            duration=100, loop=0,
        )
        with self.assertRaises(observation_assets.ObservationMaterialInvalid):
            self._import(buffer.getvalue(), name="animated.gif", expected=3)

    def test_truncated_animated_and_broken_metadata_are_rejected(self):
        jpeg = self._jpeg(size=(200, 160))
        with self.assertRaises(
            (
                observation_assets.ObservationMaterialCorrupt,
                observation_assets.ObservationMaterialInvalid,
            )
        ):
            self._import(jpeg[: len(jpeg) // 2], name="truncated.jpg")
        with self.assertRaises(observation_assets.ObservationMaterialInvalid):
            self._import(self._jpeg(icc=b"not-an-icc"), name="icc.jpg")
        frames = [
            Image.new("RGBA", (40, 30), (255, 0, 0, 128)),
            Image.new("RGBA", (40, 30), (0, 0, 255, 128)),
        ]
        webp = io.BytesIO()
        frames[0].save(
            webp, "WEBP", save_all=True, append_images=frames[1:], duration=100
        )
        with self.assertRaises(observation_assets.ObservationMaterialInvalid):
            self._import(webp.getvalue(), name="animated.webp")
        apng = io.BytesIO()
        frames[0].save(
            apng, "PNG", save_all=True, append_images=frames[1:], duration=100
        )
        with self.assertRaises(observation_assets.ObservationMaterialInvalid):
            self._import(apng.getvalue(), name="animated.png")

    def test_extension_spoof_uses_actual_format_and_preserves_bytes(self):
        source = self._png()
        result = self._import(source, name="claimed.jpg")
        self.assertEqual(result["format"], "png")
        self.assertEqual(
            observation_assets.read_asset_bytes(
                self.session,
                self.runtime,
                profile_id=self.profile.id,
                observation_id="obs-1",
                asset_id=result["asset_id"],
            ),
            source,
        )
        asset = self.session.get(LocalObservationAsset, result["asset_id"])
        self.assertTrue(asset.relative_path.endswith(".png"))

    def test_external_source_removal_and_version_reference_keep_managed_bytes(self):
        source_path = self.tmp_root / "external-source.jpg"
        source = self._jpeg(size=(120, 80))
        source_path.write_bytes(source)
        with source_path.open("rb") as handle:
            result = self._import(handle.read(), name="external.jpg", caption="外部")
        source_path.unlink()
        self.assertEqual(
            observation_assets.read_asset_bytes(
                self.session,
                self.runtime,
                profile_id=self.profile.id,
                observation_id="obs-1",
                asset_id=result["asset_id"],
            ),
            source,
        )
        version = LocalObservationVersion(
            id="ver-external",
            observation_id="obs-1",
            version=1,
            payload_json=self.payload,
            payload_hash=aggregate_hash(self.payload, []),
            source_kind="manual",
            creator_profile_id=self.profile.id,
            created_at=self.now,
        )
        self.session.add(version)
        self.session.flush()
        self.session.add(
            LocalObservationVersionPhoto(
                version_id="ver-external",
                asset_id=result["asset_id"],
                observation_id="obs-1",
                sort_order=0,
                caption="外部",
            )
        )
        self.session.commit()
        observation_assets.remove_photo(
            self.session,
            profile_id=self.profile.id,
            observation_id="obs-1",
            request_id=str(uuid.uuid4()),
            expected_revision=2,
            asset_id=result["asset_id"],
        )
        self.assertIsNotNone(self.session.get(LocalObservationAsset, result["asset_id"]))
        self.assertIsNotNone(
            self.session.get(
                LocalObservationVersionPhoto, ("ver-external", result["asset_id"])
            )
        )
        self.assertEqual(
            observation_assets.read_asset_bytes(
                self.session,
                self.runtime,
                profile_id=self.profile.id,
                observation_id="obs-1",
                asset_id=result["asset_id"],
            ),
            source,
        )

    def test_display_name_path_traversal_is_rejected(self):
        data = self._jpeg()
        for name in ("../a.jpg", r"C:\a.jpg", "CON.jpg", "a.jpg.", "a.jpg ", "http://x/a.jpg"):
            with self.subTest(name=name):
                with self.assertRaises(observation_assets.ObservationMaterialInvalid):
                    self._import(data, name=name)

    def test_limits_reject_before_asset_commit(self):
        with self.assertRaises(observation_assets.ObservationMaterialLimit):
            self._import(b"x" * (observation_assets.MAX_SOURCE_BYTES + 1), name="big.jpg")
        image = Image.new("RGB", (6500, 6500), "red")
        buffer = io.BytesIO()
        image.save(buffer, "JPEG")
        with self.assertRaises(observation_assets.ObservationMaterialLimit):
            self._import(buffer.getvalue(), name="pixels.jpg")
        image = Image.new("RGB", (9000, 1000), "red")
        buffer = io.BytesIO()
        image.save(buffer, "JPEG")
        with self.assertRaises(observation_assets.ObservationMaterialLimit):
            self._import(buffer.getvalue(), name="side.jpg")
        self.assertEqual(
            self.session.scalar(select(LocalObservationAsset).where(LocalObservationAsset.observation_id == "obs-1")),
            None,
        )

    def test_ai_target_failure_rejects_without_committing(self):
        with mock.patch.object(observation_assets, "AI_TARGET_BYTES", 1):
            with self.assertRaises(observation_assets.ObservationMaterialLimit):
                self._import(self._jpeg())
        self.assertIsNone(
            self.session.scalar(
                select(LocalObservationAsset).where(
                    LocalObservationAsset.observation_id == "obs-1"
                )
            )
        )

    def test_reorder_caption_noop_and_remove_keep_asset_and_history(self):
        one = self._import(self._jpeg(), name="a.jpg")
        two = self._import(self._jpeg(), name="b.jpg", expected=2)
        reordered = observation_assets.reorder_photos(
            self.session,
            profile_id=self.profile.id,
            observation_id="obs-1",
            request_id=str(uuid.uuid4()),
            expected_revision=3,
            asset_ids=[two["asset_id"], one["asset_id"]],
        )
        self.assertTrue(reordered["changed"])
        self.assertEqual([p["asset_id"] for p in reordered["photos"]], [two["asset_id"], one["asset_id"]])
        noop = observation_assets.reorder_photos(
            self.session,
            profile_id=self.profile.id,
            observation_id="obs-1",
            request_id=str(uuid.uuid4()),
            expected_revision=4,
            asset_ids=[two["asset_id"], one["asset_id"]],
        )
        self.assertFalse(noop["changed"])
        self.assertEqual(noop["revision"], 4)
        caption = observation_assets.set_caption(
            self.session,
            profile_id=self.profile.id,
            observation_id="obs-1",
            request_id=str(uuid.uuid4()),
            expected_revision=4,
            asset_id=one["asset_id"],
            caption="  新说明  ",
        )
        self.assertTrue(caption["changed"])
        noop_caption = observation_assets.set_caption(
            self.session,
            profile_id=self.profile.id,
            observation_id="obs-1",
            request_id=str(uuid.uuid4()),
            expected_revision=5,
            asset_id=one["asset_id"],
            caption="新说明",
        )
        self.assertFalse(noop_caption["changed"])
        version = LocalObservationVersion(
            id="ver-1",
            observation_id="obs-1",
            version=1,
            payload_json=self.payload,
            payload_hash=aggregate_hash(self.payload, []),
            source_kind="manual",
            creator_profile_id=self.profile.id,
            created_at=self.now,
        )
        self.session.add(version)
        self.session.flush()
        self.session.add(
            LocalObservationVersionPhoto(
                version_id="ver-1",
                asset_id=one["asset_id"],
                observation_id="obs-1",
                sort_order=0,
                caption="旧说明",
            )
        )
        self.session.commit()
        removed = observation_assets.remove_photo(
            self.session,
            profile_id=self.profile.id,
            observation_id="obs-1",
            request_id=str(uuid.uuid4()),
            expected_revision=5,
            asset_id=one["asset_id"],
        )
        self.assertTrue(removed["changed"])
        self.assertIsNotNone(self.session.get(LocalObservationAsset, one["asset_id"]))
        self.assertIsNotNone(self.session.get(LocalObservationVersionPhoto, ("ver-1", one["asset_id"])))

    def test_remove_rebuilds_dense_order_for_three_and_four_photos(self):
        for count in (3, 4):
            for remove_index in (0, 1, count - 1):
                with self.subTest(count=count, remove_index=remove_index):
                    observation_id = f"remove-{count}-{remove_index}"
                    self._make_record(observation_id)
                    sources = [
                        self._jpeg(color=(index * 30 + 20, 40, 60))
                        for index in range(count)
                    ]
                    results = [
                        self._import(
                            sources[index],
                            name=f"{index}.jpg",
                            caption=f"说明{index}",
                            expected=index + 1,
                            record=observation_id,
                        )
                        for index in range(count)
                    ]
                    asset_ids = [result["asset_id"] for result in results]
                    sorted_ids = sorted(asset_ids)
                    order = list(reversed(asset_ids))
                    if order == sorted_ids:
                        order = asset_ids[1:] + asset_ids[:1]
                    self.assertNotEqual(order, asset_ids)
                    self.assertNotEqual(order, sorted_ids)
                    reordered = observation_assets.reorder_photos(
                        self.session,
                        profile_id=self.profile.id,
                        observation_id=observation_id,
                        request_id=str(uuid.uuid4()),
                        expected_revision=count + 1,
                        asset_ids=order,
                    )
                    self.assertEqual(
                        [photo["asset_id"] for photo in reordered["photos"]], order
                    )
                    self.assertEqual(reordered["revision"], count + 2)
                    self.assertNotEqual(order, sorted(asset_ids))
                    target = order[remove_index]
                    target_result = results[asset_ids.index(target)]
                    input_id = uuid.uuid4().hex
                    ai_derivative = self.session.scalars(
                        select(LocalObservationAssetDerivative).where(
                            LocalObservationAssetDerivative.asset_id == target,
                            LocalObservationAssetDerivative.purpose == "ai",
                        )
                    ).one()
                    self.session.add(
                        LocalAIInput(
                            id=input_id,
                            profile_id=self.profile.id,
                            source_kind="game_observation",
                            source_id=observation_id,
                            observation_id=observation_id,
                            source_revision=count + 2,
                            task_type="game_observation_generate",
                            input_schema_version=1,
                            payload_json={"synthetic": True},
                            dependencies_json={},
                            dependency_hash="0" * 64,
                            target_hashes_json={},
                            created_at=self.now,
                        )
                    )
                    self.session.flush()
                    input_photo_id = uuid.uuid4().hex
                    self.session.add(
                        LocalObservationAIInputPhoto(
                            id=input_photo_id,
                            profile_id=self.profile.id,
                            source_kind="game_observation",
                            source_id=observation_id,
                            observation_id=observation_id,
                            input_id=input_id,
                            asset_id=target,
                            derivative_id=ai_derivative.id,
                            sort_order=0,
                            caption=f"说明{asset_ids.index(target)}",
                            original_hash=target_result["content_hash"],
                            work_hash=ai_derivative.content_hash,
                        )
                    )
                    self.session.commit()
                    ai_derivative_bytes = observation_assets.read_derivative_bytes(
                        self.session,
                        self.runtime,
                        profile_id=self.profile.id,
                        observation_id=observation_id,
                        asset_id=target,
                        derivative_id=ai_derivative.id,
                    )
                    rid = str(uuid.uuid4())
                    removed = observation_assets.remove_photo(
                        self.session,
                        profile_id=self.profile.id,
                        observation_id=observation_id,
                        request_id=rid,
                        expected_revision=count + 2,
                        asset_id=target,
                    )
                    expected_order = [asset_id for asset_id in order if asset_id != target]
                    self.assertEqual(
                        [photo["asset_id"] for photo in removed["photos"]],
                        expected_order,
                    )
                    self.assertEqual(
                        [photo["sort_order"] for photo in removed["photos"]],
                        list(range(len(expected_order))),
                    )
                    self.assertEqual(
                        [photo["caption"] for photo in removed["photos"]],
                        [f"说明{asset_ids.index(asset_id)}" for asset_id in expected_order],
                    )
                    self.assertEqual(
                        removed["payload_hash"],
                        aggregate_hash(self.payload, removed["photos"]),
                    )
                    again = observation_assets.remove_photo(
                        self.session,
                        profile_id=self.profile.id,
                        observation_id=observation_id,
                        request_id=rid,
                        expected_revision=count + 2,
                        asset_id=target,
                    )
                    self.assertEqual(again, removed)
                    self.assertIsNotNone(
                        self.session.get(LocalObservationAIInputPhoto, input_photo_id)
                    )
                    self.assertIsNotNone(self.session.get(LocalAIInput, input_id))
                    self.assertEqual(
                        observation_assets.read_derivative_bytes(
                            self.session,
                            self.runtime,
                            profile_id=self.profile.id,
                            observation_id=observation_id,
                            asset_id=target,
                            derivative_id=ai_derivative.id,
                        ),
                        ai_derivative_bytes,
                    )

                    version_id = f"ver-{observation_id}"
                    self.session.add(
                        LocalObservationVersion(
                            id=version_id,
                            observation_id=observation_id,
                            version=1,
                            payload_json=self.payload,
                            payload_hash=aggregate_hash(self.payload, []),
                            source_kind="manual",
                            creator_profile_id=self.profile.id,
                            created_at=self.now,
                        )
                    )
                    self.session.flush()
                    for index, asset_id in enumerate(order):
                        self.session.add(
                            LocalObservationVersionPhoto(
                                version_id=version_id,
                                asset_id=asset_id,
                                observation_id=observation_id,
                                sort_order=index,
                                caption=f"历史{index}",
                            )
                        )
                    self.session.commit()
                    self.assertIsNotNone(
                        self.session.get(LocalObservationVersionPhoto, (version_id, target))
                    )
                    self.assertEqual(
                        observation_assets.read_asset_bytes(
                            self.session,
                            self.runtime,
                            profile_id=self.profile.id,
                            observation_id=observation_id,
                            asset_id=target,
                        ),
                        sources[asset_ids.index(target)],
                    )

    def test_idempotent_replay_stale_revision_and_audit(self):
        rid = str(uuid.uuid4())
        data = self._jpeg()
        first = self._import(data, request_id=rid, expected=1)
        # Advance the draft after the original request; replay keeps expected=1.
        observation_assets.set_caption(
            self.session,
            profile_id=self.profile.id,
            observation_id="obs-1",
            request_id=str(uuid.uuid4()),
            expected_revision=2,
            asset_id=first["asset_id"],
            caption="later",
        )
        again = self._import(data, request_id=rid, expected=1)
        self.assertEqual(first, again)
        with self.assertRaises(observation_assets.ObservationAssetRequestConflict):
            self._import(data, request_id=rid, expected=999)
        with self.assertRaises(observation_assets.ObservationAssetRequestConflict):
            self._import(self._jpeg(color="blue"), request_id=rid, expected=1)
        with self.assertRaises(observation_assets.ObservationAssetRevisionConflict):
            self._import(self._jpeg(color="green"), expected=1)
        audits = [
            row
            for row in self.session.scalars(select(LocalOperationRecord)).all()
            if row.action.startswith("observation_")
        ]
        self.assertEqual(len(audits), 2)
        self.assertEqual(audits[0].action, "observation_asset_import")
        self.assertEqual(audits[1].action, "observation_photo_caption")
        self.assertNotIn("a.jpg", str(audits[0].__dict__))

    def test_receipt_readback_without_staging_or_decode(self):
        rid = str(uuid.uuid4())
        data = self._jpeg()
        first = self._import(data, request_id=rid, expected=1)
        observation_assets.set_caption(
            self.session,
            profile_id=self.profile.id,
            observation_id="obs-1",
            request_id=str(uuid.uuid4()),
            expected_revision=2,
            asset_id=first["asset_id"],
            caption="later",
        )
        with mock.patch.object(observation_assets, "_write_staging", side_effect=AssertionError("must not stage")):
            again = self._import(data, request_id=rid, expected=1)
        self.assertEqual(first, again)
        with mock.patch.object(observation_assets, "_write_staging", side_effect=AssertionError("must not stage")):
            with self.assertRaises(observation_assets.ObservationAssetRequestConflict):
                self._import(data, request_id=rid, expected=999)

    def test_db_failure_leaves_orphan_files_but_no_rows(self):
        before = self.session.scalar(select(LocalObservationDraft).where(LocalObservationDraft.observation_id == "obs-1"))
        with mock.patch.object(self.session, "commit", side_effect=RuntimeError("injected db failure")):
            with self.assertRaises(observation_assets.ObservationAssetStorage):
                self._import(self._jpeg())
        self.assertEqual(
            self.session.scalar(select(LocalObservationAsset).where(LocalObservationAsset.observation_id == "obs-1")),
            None,
        )
        self.assertEqual(self.session.get(LocalObservationDraft, "obs-1").revision, before.revision)

    def test_disk_failure_does_not_commit(self):
        first_data = self._jpeg()
        first = self._import(first_data, name="old.jpg", caption="旧说明")
        self.session.expire_all()
        draft = self.session.get(LocalObservationDraft, "obs-1")
        before = (
            draft.revision,
            draft.payload_hash,
            len(self.session.scalars(select(LocalObservationAsset)).all()),
            len(self.session.scalars(select(LocalObservationOperation)).all()),
            len(
                [
                    row
                    for row in self.session.scalars(select(LocalOperationRecord)).all()
                    if row.action.startswith("observation_")
                ]
            ),
        )
        staging_before = set(observation_assets._staging_root(self.runtime).glob("*"))

        def unchanged() -> None:
            self.session.expire_all()
            current = self.session.get(LocalObservationDraft, "obs-1")
            self.assertEqual(
                (
                    current.revision,
                    current.payload_hash,
                    len(self.session.scalars(select(LocalObservationAsset)).all()),
                    len(self.session.scalars(select(LocalObservationOperation)).all()),
                    len(
                        [
                            row
                            for row in self.session.scalars(select(LocalOperationRecord)).all()
                            if row.action.startswith("observation_")
                        ]
                    ),
                ),
                before,
            )
            self.assertEqual(
                observation_assets.read_asset_bytes(
                    self.session,
                    self.runtime,
                    profile_id=self.profile.id,
                    observation_id="obs-1",
                    asset_id=first["asset_id"],
                ),
                first_data,
            )
            self.assertGreater(
                len(set(observation_assets._staging_root(self.runtime).glob("*"))),
                len(staging_before),
            )

        with mock.patch(
            "app.local.observation_assets.os.fsync",
            side_effect=OSError(errno.ENOSPC, "synthetic no space"),
        ):
            with self.assertRaises(observation_assets.ObservationAssetStorage):
                self._import(self._jpeg(color="blue"), name="staging.jpg")
        unchanged()

        calls = {"n": 0}

        def derivative_fsync(fd):
            calls["n"] += 1
            if calls["n"] >= 2:
                raise OSError(errno.ENOSPC, "synthetic no space")
            return None

        with mock.patch("app.local.observation_assets.os.fsync", side_effect=derivative_fsync):
            with self.assertRaises(observation_assets.ObservationAssetStorage):
                self._import(self._jpeg(color="green"), name="derivative.jpg")
        unchanged()

        with mock.patch(
            "app.local.observation_assets.os.replace",
            side_effect=OSError(errno.ENOSPC, "synthetic no space"),
        ):
            with self.assertRaises(observation_assets.ObservationAssetStorage):
                self._import(self._jpeg(color="yellow"), name="move.jpg")
        unchanged()

        with mock.patch(
            "pathlib.Path.mkdir",
            side_effect=OSError(errno.ENOSPC, "synthetic no space"),
        ):
            with self.assertRaises(observation_assets.ObservationAssetStorage):
                self._import(self._jpeg(color="purple"), name="mkdir.jpg")
        unchanged()

    def test_enospc_at_staging_derivative_and_move_preserves_previous_state(self):
        first = self._import(self._jpeg(), caption="old")
        observation_assets.set_caption(
            self.session,
            profile_id=self.profile.id,
            observation_id="obs-1",
            request_id=str(uuid.uuid4()),
            expected_revision=2,
            asset_id=first["asset_id"],
            caption="old-caption",
        )

        def snapshot():
            self.session.expire_all()
            return {
                "assets": [
                    (row.id, row.relative_path, row.content_hash)
                    for row in self.session.scalars(
                        select(LocalObservationAsset).order_by(LocalObservationAsset.id)
                    ).all()
                ],
                "photos": [
                    (row.asset_id, row.sort_order, row.caption)
                    for row in self.session.scalars(
                        select(LocalObservationDraftPhoto).order_by(
                            LocalObservationDraftPhoto.observation_id,
                            LocalObservationDraftPhoto.sort_order,
                        )
                    ).all()
                ],
                "drafts": [
                    (row.observation_id, row.revision, row.payload_hash)
                    for row in self.session.scalars(
                        select(LocalObservationDraft).order_by(LocalObservationDraft.observation_id)
                    ).all()
                ],
                "receipts": len(
                    self.session.scalars(select(LocalObservationOperation)).all()
                ),
                "audits": len(
                    self.session.scalars(select(LocalOperationRecord)).all()
                ),
            }

        before = snapshot()
        staging_root = observation_assets._staging_root(self.runtime)
        staging_before = {path.name for path in staging_root.iterdir()} if staging_root.exists() else set()

        def fsync_fail_on(index: int):
            calls = 0

            def fail(fd):  # noqa: ANN001
                nonlocal calls
                calls += 1
                if calls == index:
                    raise OSError(errno.ENOSPC, "synthetic ENOSPC")

            return fail

        failures = [
            ("staging_fsync", mock.patch(
                "app.local.observation_assets.os.fsync", side_effect=fsync_fail_on(1)
            )),
            ("derivative_fsync", mock.patch(
                "app.local.observation_assets.os.fsync", side_effect=fsync_fail_on(2)
            )),
            ("move", mock.patch(
                "app.local.observation_assets.os.replace",
                side_effect=OSError(errno.ENOSPC, "synthetic ENOSPC"),
            )),
            ("mkdir", mock.patch(
                "pathlib.Path.mkdir",
                side_effect=OSError(errno.ENOSPC, "synthetic ENOSPC"),
            )),
        ]
        for name, patcher in failures:
            with self.subTest(name=name):
                with patcher:
                    with self.assertRaises(observation_assets.ObservationAssetStorage) as raised:
                        self._import(self._jpeg(color="blue"), name="new.jpg", expected=3)
                self.assertEqual(raised.exception.code, "OBS_STORAGE_IO")
                self.assertEqual(snapshot(), before)
                if name != "mkdir":
                    current = {path.name for path in staging_root.iterdir()} if staging_root.exists() else set()
                    self.assertGreater(len(current), len(staging_before))
                    staging_before = current

    def test_real_sqlite_trigger_failure_rolls_back_with_orphan_files(self):
        first = self._import(self._jpeg(), caption="old")
        before_assets = [
            (row.id, row.relative_path)
            for row in self.session.scalars(
                select(LocalObservationAsset).order_by(LocalObservationAsset.id)
            ).all()
        ]
        before_draft = self.session.get(LocalObservationDraft, "obs-1")
        before_revision = before_draft.revision
        before_hash = before_draft.payload_hash
        before_receipts = len(self.session.scalars(select(LocalObservationOperation)).all())
        before_audits = len(self.session.scalars(select(LocalOperationRecord)).all())
        asset_root = observation_assets._asset_root(self.runtime) / "obs-1"
        dirs_before = {path.name for path in asset_root.iterdir()} if asset_root.exists() else set()
        self.session.execute(
            text(
                "CREATE TRIGGER e03_abort_asset BEFORE INSERT ON local_observation_assets "
                "BEGIN SELECT RAISE(ABORT, 'synthetic trigger'); END"
            )
        )
        self.session.commit()
        try:
            with self.assertRaises(observation_assets.ObservationAssetStorage) as raised:
                self._import(self._jpeg(color="blue"), name="trigger.jpg", expected=2)
        finally:
            self.session.execute(text("DROP TRIGGER e03_abort_asset"))
            self.session.commit()
        self.assertEqual(raised.exception.code, "OBS_STORAGE_IO")
        self.assertNotEqual(raised.exception.code, "OBS_REVISION_CONFLICT")
        self.session.expire_all()
        self.assertEqual(
            [
                (row.id, row.relative_path)
                for row in self.session.scalars(
                    select(LocalObservationAsset).order_by(LocalObservationAsset.id)
                ).all()
            ],
            before_assets,
        )
        draft = self.session.get(LocalObservationDraft, "obs-1")
        self.assertEqual((draft.revision, draft.payload_hash), (before_revision, before_hash))
        self.assertEqual(
            len(self.session.scalars(select(LocalObservationOperation)).all()),
            before_receipts,
        )
        self.assertEqual(
            len(self.session.scalars(select(LocalOperationRecord)).all()),
            before_audits,
        )
        self.assertEqual(
            observation_assets.read_asset_bytes(
                self.session,
                self.runtime,
                profile_id=self.profile.id,
                observation_id="obs-1",
                asset_id=first["asset_id"],
            ),
            self._jpeg(),
        )
        dirs_after = {path.name for path in asset_root.iterdir()} if asset_root.exists() else set()
        orphan_names = dirs_after - dirs_before
        self.assertEqual(len(orphan_names), 1)
        orphan = asset_root / next(iter(orphan_names))
        self.assertTrue((orphan / "original.jpg").is_file())
        self.assertEqual(
            len(list((orphan / "derivatives").glob("*.jpg"))),
            2,
        )

    def test_managed_path_rejects_ads_trailing_dot_junction_and_hardlink(self):
        import hashlib
        import os
        import subprocess
        from pathlib import Path
        from types import SimpleNamespace

        root = self.tmp_root / "path-probe"
        asset_dir = root / "observations" / "assets" / "r" / "a"
        asset_dir.mkdir(parents=True)
        data = b"synthetic-only"
        original = asset_dir / "original.jpg"
        original.write_bytes(data)
        runtime = SimpleNamespace(data_dir=root)
        expected = hashlib.sha256(data).hexdigest()
        self.assertEqual(
            observation_assets._read_verified_file(
                runtime,
                "observations/assets/r/a/original.jpg",
                observation_id="r",
                asset_id="a",
                expected_leaf="original",
                expected_hash=expected,
                expected_size=len(data),
            ),
            data,
        )
        for relative in (
            "observations/assets/r/a/original.jpg:synthetic-stream",
            "observations/assets/r/a/original.jpg.",
        ):
            with self.subTest(relative=relative):
                with self.assertRaises(observation_assets.ObservationMaterialInvalid):
                    observation_assets._read_verified_file(
                        runtime,
                        relative,
                        observation_id="r",
                        asset_id="a",
                        expected_leaf="original",
                        expected_hash=expected,
                        expected_size=len(data),
                    )
        outside = root / "outside"
        outside.mkdir()
        (outside / "original.jpg").write_bytes(data)
        junction = asset_dir / "junction"
        completed = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
            capture_output=True,
        )
        if completed.returncode == 0:
            with self.assertRaises(observation_assets.ObservationMaterialInvalid):
                observation_assets._read_verified_file(
                    runtime,
                    "observations/assets/r/a/junction/original.jpg",
                    observation_id="r",
                    asset_id="a",
                    expected_leaf="original",
                    expected_hash=expected,
                    expected_size=len(data),
                )
        hardlink = asset_dir / "hardlink.jpg"
        os.link(original, hardlink)
        with self.assertRaises(observation_assets.ObservationMaterialCorrupt):
            observation_assets._read_verified_file(
                runtime,
                "observations/assets/r/a/original.jpg",
                observation_id="r",
                asset_id="a",
                expected_leaf="original",
                expected_hash=expected,
                expected_size=len(data),
            )

    def test_unverifiable_handle_path_is_rejected_for_read_and_write(self):
        from types import SimpleNamespace

        root = self.tmp_root / "path-unverifiable"
        asset_dir = root / "observations" / "assets" / "r" / "a"
        asset_dir.mkdir(parents=True)
        payload = b"synthetic-only"
        original = asset_dir / "original.jpg"
        original.write_bytes(payload)
        runtime = SimpleNamespace(data_dir=root)
        with mock.patch.object(
            observation_assets, "_final_path_from_handle", return_value=None
        ):
            with self.assertRaises(observation_assets.ObservationMaterialCorrupt):
                observation_assets._read_verified_file(
                    runtime,
                    "observations/assets/r/a/original.jpg",
                    observation_id="r",
                    asset_id="a",
                    expected_leaf="original",
                    expected_hash=hashlib.sha256(payload).hexdigest(),
                    expected_size=len(payload),
                )
        staging = root / "observations" / "staging" / "attempt" / "upload.bin"
        with mock.patch.object(
            observation_assets, "_final_path_from_handle", return_value=None
        ):
            with self.assertRaises(observation_assets.ObservationAssetStorage):
                observation_assets._write_staging(
                    staging, io.BytesIO(payload), root
                )

    def test_write_staging_rejects_existing_junction_parent(self):
        import subprocess
        from types import SimpleNamespace

        root = self.tmp_root / "path-write-junction"
        outside = root / "outside"
        outside.mkdir(parents=True)
        staging_parent = root / "observations" / "staging" / "attempt"
        staging_parent.parent.mkdir(parents=True)
        completed = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(staging_parent), str(outside)],
            capture_output=True,
        )
        if completed.returncode != 0:
            self.skipTest(f"junction unavailable: {completed.stderr!r}")
        runtime = SimpleNamespace(data_dir=root)
        with self.assertRaises(observation_assets.ObservationMaterialInvalid):
            observation_assets._write_staging(
                staging_parent / "upload.bin", io.BytesIO(b"synthetic"), root
            )

    def test_ancestor_replaced_with_junction_after_check_is_rejected(self):
        import hashlib
        import os
        import subprocess
        from pathlib import Path
        from types import SimpleNamespace

        root = self.tmp_root / "path-swap"
        asset_dir = root / "observations" / "assets" / "r" / "a"
        asset_dir.mkdir(parents=True)
        payload = b"synthetic-only"
        (asset_dir / "original.jpg").write_bytes(payload)
        outside = root / "outside"
        outside.mkdir()
        (outside / "original.jpg").write_bytes(payload)
        runtime = SimpleNamespace(data_dir=root)
        real_open = os.open
        swapped = False

        def swap_then_open(path, flags, mode=0o777):
            nonlocal swapped
            if not swapped:
                swapped = True
                moved = asset_dir.with_name("a-checked")
                asset_dir.rename(moved)
                completed = subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(asset_dir), str(outside)],
                    capture_output=True,
                )
                if completed.returncode != 0:
                    raise AssertionError(completed.stderr)
            return real_open(path, flags, mode)

        with mock.patch("app.local.observation_assets.os.open", side_effect=swap_then_open):
            with self.assertRaises(observation_assets.ObservationMaterialCorrupt):
                observation_assets._read_verified_file(
                    runtime,
                    "observations/assets/r/a/original.jpg",
                    observation_id="r",
                    asset_id="a",
                    expected_leaf="original",
                    expected_hash=hashlib.sha256(payload).hexdigest(),
                    expected_size=len(payload),
                )

    def test_cleanup_junction_swap_does_not_delete_outside_and_receipt_replays(self):
        import subprocess
        from types import SimpleNamespace

        request_id = str(uuid.uuid4())
        source = self._jpeg(color="red")
        first = self._import(source, request_id=request_id, name="cleanup.jpg")
        staging_root = observation_assets._staging_root(self.runtime)
        self.assertTrue(staging_root.is_dir())
        backup = self.tmp_root / "staging-backup"
        staging_root.rename(backup)
        outside = self.tmp_root / "outside" / "synthetic-attempt"
        outside.mkdir(parents=True)
        keep = outside / "keep.txt"
        keep.write_text("synthetic-only", encoding="utf-8")
        completed = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(staging_root), str(self.tmp_root / "outside")],
            capture_output=True,
        )
        if completed.returncode != 0:
            self.skipTest(f"junction unavailable: {completed.stderr!r}")
        runtime = SimpleNamespace(data_dir=self.runtime.data_dir)
        observation_assets._discard_attempt(staging_root / "synthetic-attempt")
        self.assertEqual(keep.read_text(encoding="utf-8"), "synthetic-only")
        replay = observation_assets.import_asset(
            self.session,
            runtime,
            profile_id=self.profile.id,
            observation_id="obs-1",
            request_id=request_id,
            expected_revision=1,
            stream=io.BytesIO(source),
            display_name="cleanup.jpg",
            caption=None,
        )
        self.assertEqual(replay, first)
        self.assertEqual(keep.read_text(encoding="utf-8"), "synthetic-only")

    def test_staging_ancestor_swap_before_decode_is_rejected(self):
        import subprocess

        baseline_data = self._jpeg(color="red")
        baseline = self._import(baseline_data, name="baseline.jpg", caption="基线")
        self.session.expire_all()
        draft = self.session.get(LocalObservationDraft, "obs-1")
        before = (
            draft.revision,
            len(self.session.scalars(select(LocalObservationAsset)).all()),
            len(self.session.scalars(select(LocalObservationOperation)).all()),
        )
        outside = self.tmp_root / "outside"
        outside.mkdir()
        outside_file = outside / "upload.bin"
        outside_file.write_bytes(self._jpeg(color="blue"))
        real_write = observation_assets._write_staging
        swapped = False

        def write_then_swap(path, stream, root):
            nonlocal swapped
            result = real_write(path, stream, root)
            if path.name == "upload.bin" and not swapped:
                swapped = True
                backup = path.parent.with_name(path.parent.name + "-original")
                path.parent.rename(backup)
                completed = subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(path.parent), str(outside)],
                    capture_output=True,
                )
                if completed.returncode != 0:
                    raise AssertionError(completed.stderr)
            return result

        with mock.patch.object(
            observation_assets, "_write_staging", side_effect=write_then_swap
        ), mock.patch.object(
            observation_assets,
            "_prepare_asset",
            side_effect=AssertionError("outside staging must not be decoded"),
        ):
            with self.assertRaises(observation_assets.ObservationMaterialInvalid):
                self._import(self._jpeg(color="green"), name="swap.jpg", expected=2)
        self.session.expire_all()
        self.assertEqual(
            (
                self.session.get(LocalObservationDraft, "obs-1").revision,
                len(self.session.scalars(select(LocalObservationAsset)).all()),
                len(self.session.scalars(select(LocalObservationOperation)).all()),
            ),
            before,
        )
        self.assertEqual(
            observation_assets.read_asset_bytes(
                self.session,
                self.runtime,
                profile_id=self.profile.id,
                observation_id="obs-1",
                asset_id=baseline["asset_id"],
            ),
            baseline_data,
        )
        self.assertEqual(outside_file.read_bytes(), self._jpeg(color="blue"))

    def test_staging_decode_rejects_ancestor_junction_swap_before_codec(self):
        import subprocess

        baseline_data = self._jpeg(color="red")
        baseline = self._import(baseline_data, name="baseline.jpg")
        before_revision = self.session.get(LocalObservationDraft, "obs-1").revision
        before_assets = len(
            self.session.scalars(
                select(LocalObservationAsset).where(
                    LocalObservationAsset.observation_id == "obs-1"
                )
            ).all()
        )
        before_receipts = len(
            self.session.scalars(select(LocalObservationOperation)).all()
        )
        before_audits = len(
            [
                row
                for row in self.session.scalars(select(LocalOperationRecord)).all()
                if row.action.startswith("observation_")
            ]
        )
        root = self.tmp_root / "r10"
        outside = root / "outside"
        outside.mkdir(parents=True)
        outside_payload = self._jpeg(color="blue")
        (outside / "upload.bin").write_bytes(outside_payload)
        real_write = observation_assets._write_staging
        junction_path = None
        swapped = False

        def write_then_swap(path, stream, staging_root):
            nonlocal junction_path, swapped
            result = real_write(path, stream, staging_root)
            if path.name == "upload.bin" and not swapped:
                swapped = True
                attempt = path.parent
                backup = attempt.with_name(attempt.name + "-original")
                attempt.rename(backup)
                target = outside / attempt.name
                target.mkdir(parents=True, exist_ok=True)
                (target / "upload.bin").write_bytes(outside_payload)
                completed = subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(attempt), str(target)],
                    capture_output=True,
                )
                if completed.returncode != 0:
                    raise AssertionError(completed.stderr)
                junction_path = attempt
            return result

        with mock.patch.object(observation_assets, "_write_staging", side_effect=write_then_swap):
            with mock.patch.object(
                observation_assets,
                "_prepare_asset",
                side_effect=AssertionError("outside staging was decoded"),
            ) as decode:
                with self.assertRaises(observation_assets.ObservationMaterialInvalid):
                    self._import(
                        self._jpeg(color="green"),
                        name="r10.jpg",
                        expected=2,
                    )
        self.assertFalse(decode.called)
        self.assertEqual((outside / "upload.bin").read_bytes(), outside_payload)
        self.session.expire_all()
        self.assertEqual(
            len(
                self.session.scalars(
                    select(LocalObservationAsset).where(
                        LocalObservationAsset.observation_id == "obs-1"
                    )
                ).all()
            ),
            before_assets,
        )
        self.assertEqual(
            self.session.get(LocalObservationDraft, "obs-1").revision,
            before_revision,
        )
        self.assertEqual(
            len(self.session.scalars(select(LocalObservationOperation)).all()),
            before_receipts,
        )
        self.assertEqual(
            len(
                [
                    row
                    for row in self.session.scalars(select(LocalOperationRecord)).all()
                    if row.action.startswith("observation_")
                ]
            ),
            before_audits,
        )
        self.assertEqual(
            observation_assets.read_asset_bytes(
                self.session,
                self.runtime,
                profile_id=self.profile.id,
                observation_id="obs-1",
                asset_id=baseline["asset_id"],
            ),
            baseline_data,
        )
        if junction_path is not None:
            subprocess.run(["cmd", "/c", "rmdir", str(junction_path)], capture_output=True)
        shutil.rmtree(root, ignore_errors=True)

    def test_cross_record_path_tamper_is_rejected(self):
        one = self._import(self._jpeg(), name="a.jpg")
        two = self._import(self._jpeg(), name="b.jpg", expected=2)
        asset = self.session.get(LocalObservationAsset, one["asset_id"])
        other = self.session.get(LocalObservationAsset, two["asset_id"])
        asset.relative_path = other.relative_path
        self.session.commit()
        with self.assertRaises(observation_assets.ObservationMaterialInvalid):
            observation_assets.read_asset_bytes(
                self.session,
                self.runtime,
                profile_id=self.profile.id,
                observation_id="obs-1",
                asset_id=one["asset_id"],
            )

    def test_cross_process_commit_crash_and_restart(self):
        import sqlite3

        baseline_data = self._jpeg(color="red")
        baseline = self._import(baseline_data, name="baseline.jpg", caption="基线")
        profile_id = self.profile.id
        data_dir = self.data_dir
        self.session.close()
        self.runtime.dispose()
        self.runtime = None
        self.session = None
        markers: dict[str, dict] = {}

        def worker_spec(action: str, **extra) -> dict:
            spec = self.worker_spec(action, data_dir=data_dir, connect_only=False)
            spec.update(extra)
            spec["marker_file"] = str(
                self.tmp_root / f"marker-{uuid.uuid4().hex}.json"
            )
            return spec

        def crash(spec: dict) -> tuple[int, str]:
            process = self.spawn_worker(spec)
            stdout, stderr = process.communicate(timeout=120)
            return process.returncode, stderr.decode("utf-8", "replace")

        def reopen() -> None:
            if self.session is not None:
                self.session.close()
            if self.runtime is not None:
                self.runtime.dispose()
            self.runtime = self.make_runtime(data_dir)
            self.session = self.runtime.session()
            self.profile = self.session.scalars(select(LocalProfile)).one()

        def marker(spec: dict) -> dict:
            path = Path(spec["marker_file"])
            self.assertTrue(path.is_file(), f"worker did not hit stage: {spec}")
            return json.loads(path.read_text(encoding="utf-8"))

        def counts() -> tuple[int, int, int, int]:
            self.session.expire_all()
            return (
                len(
                    self.session.scalars(
                        select(LocalObservationAsset).where(
                            LocalObservationAsset.observation_id == "obs-1"
                        )
                    ).all()
                ),
                len(self.session.scalars(select(LocalObservationOperation)).all()),
                len(
                    [
                        row
                        for row in self.session.scalars(select(LocalOperationRecord)).all()
                        if row.action.startswith("observation_")
                    ]
                ),
                self.session.get(LocalObservationDraft, "obs-1").revision,
            )

        def derivatives_for(result: dict) -> list[str]:
            return [
                result["derivative_ids"]["ai"],
                result["derivative_ids"]["export"],
            ]

        committed_data = self._jpeg(color="blue")
        committed_request = str(uuid.uuid4())
        committed_spec = worker_spec(
            "observation_import",
            profile_id=profile_id,
            observation_id="obs-1",
            request_id=committed_request,
            expected_revision=2,
            image_base64=base64.b64encode(committed_data).decode("ascii"),
            display_name="committed.jpg",
            caption="进程提交",
            exit_mode="after_commit",
        )
        rc, stderr = crash(committed_spec)
        self.assertEqual(rc, 17, stderr)
        markers["after_commit"] = marker(committed_spec)
        self.assertEqual(markers["after_commit"]["stage"], "after_commit")
        committed_result = json.loads(
            Path(committed_spec["result_file"]).read_text(encoding="utf-8")
        )["result"]
        committed_id = committed_result["asset_id"]
        reopen()
        self.assertEqual(counts(), (2, 2, 2, 3))

        read_spec = worker_spec(
            "observation_read",
            profile_id=profile_id,
            observation_id="obs-1",
            asset_ids=[baseline["asset_id"], committed_id],
            derivatives={
                baseline["asset_id"]: derivatives_for(baseline),
                committed_id: derivatives_for(committed_result),
            },
        )
        self.session.close()
        self.runtime.dispose()
        self.runtime = None
        self.session = None
        read = self.run_worker(read_spec)
        self.assertEqual(
            [asset["sha256"] for asset in read["assets"]],
            [
                hashlib.sha256(baseline_data).hexdigest(),
                hashlib.sha256(committed_data).hexdigest(),
            ],
        )
        self.assertEqual(
            [tuple(row) for row in read["draft_photos"]],
            [
                (baseline["asset_id"], 0, "基线"),
                (committed_id, 1, "进程提交"),
            ],
        )
        self.assertEqual(read["receipts"], 2)
        self.assertEqual(read["audits"], 2)
        self.assertEqual(
            [set(asset["derivatives"]) for asset in read["assets"]],
            [{"ai", "export"}, {"ai", "export"}],
        )
        for asset in read["assets"]:
            for derivative in asset["derivatives"].values():
                self.assertNotIn("error", derivative)
                self.assertEqual(len(derivative["sha256"]), 64)
                self.assertGreater(derivative["bytes"], 0)
                self.assertGreater(derivative["width"], 0)
                self.assertGreater(derivative["height"], 0)
                self.assertIn(derivative["params_version"], (
                    observation_assets.AI_PARAMS_VERSION,
                    observation_assets.EXPORT_PARAMS_VERSION,
                ))
        reopen()
        self.assertEqual(counts(), (2, 2, 2, 3))

        replay_spec = worker_spec(
            "observation_import",
            profile_id=profile_id,
            observation_id="obs-1",
            request_id=committed_request,
            expected_revision=2,
            image_base64=base64.b64encode(committed_data).decode("ascii"),
            display_name="committed.jpg",
            caption="进程提交",
        )
        self.session.close()
        self.runtime.dispose()
        self.runtime = None
        self.session = None
        replay = self.run_worker(replay_spec)["result"]
        self.assertEqual(replay, committed_result)
        reopen()
        self.assertEqual(counts(), (2, 2, 2, 3))

        for mode in ("after_files", "partial", "before_commit"):
            with self.subTest(mode=mode):
                before_counts = counts()
                before_dirs = set(
                    (data_dir / "observations" / "assets" / "obs-1").glob("*")
                )
                before_staging = set(
                    (data_dir / "observations" / "staging").glob("*")
                )
                self.session.close()
                self.runtime.dispose()
                self.runtime = None
                self.session = None
                spec = worker_spec(
                    "observation_import",
                    profile_id=profile_id,
                    observation_id="obs-1",
                    request_id=str(uuid.uuid4()),
                    expected_revision=3,
                    image_base64=base64.b64encode(
                        self._jpeg(color="green")
                    ).decode("ascii"),
                    display_name=f"{mode}.jpg",
                    caption="崩溃",
                    exit_mode=mode,
                )
                rc, stderr = crash(spec)
                result_text = (
                    Path(spec["result_file"]).read_text(encoding="utf-8")
                    if Path(spec["result_file"]).is_file()
                    else "<no result>"
                )
                self.assertEqual(rc, 17, f"{mode}: {stderr} {result_text}")
                markers[mode] = marker(spec)
                self.assertEqual(markers[mode]["stage"], mode)
                if mode in ("partial", "before_commit"):
                    self.assertGreaterEqual(markers[mode]["asset_rows"], 1)
                reopen()
                self.assertEqual(counts(), before_counts)
                self.assertEqual(
                    observation_assets.read_asset_bytes(
                        self.session,
                        self.runtime,
                        profile_id=profile_id,
                        observation_id="obs-1",
                        asset_id=baseline["asset_id"],
                    ),
                    baseline_data,
                )
                after_dirs = set(
                    (data_dir / "observations" / "assets" / "obs-1").glob("*")
                )
                new_dirs = after_dirs - before_dirs
                self.assertEqual(len(new_dirs), 1)
                orphan = next(iter(new_dirs))
                self.assertTrue((orphan / "original.jpg").is_file())
                self.assertEqual(
                    len(list((orphan / "derivatives").glob("*.jpg"))), 2
                )
                self.assertGreater(
                    len(set((data_dir / "observations" / "staging").glob("*"))),
                    len(before_staging),
                )

        evidence_root = os.environ.get("E03_EVIDENCE_ROOT")
        if evidence_root:
            db_path = self.runtime.db_path
            self.session.close()
            self.runtime.dispose()
            self.runtime = None
            self.session = None
            target = Path(evidence_root) / "r06-cross-process"
            shutil.rmtree(target, ignore_errors=True)
            target.mkdir(parents=True, exist_ok=True)
            source = sqlite3.connect(str(db_path))
            destination = sqlite3.connect(str(target / "kindergarten.db"))
            try:
                source.backup(destination)
                integrity = destination.execute("PRAGMA integrity_check").fetchall()
                foreign_keys = destination.execute("PRAGMA foreign_key_check").fetchall()
            finally:
                destination.close()
                source.close()
            shutil.copytree(
                data_dir / "observations",
                target / "observations",
                dirs_exist_ok=True,
            )
            (target / "summary.json").write_text(
                json.dumps(
                    {
                        "baseline_asset": baseline["asset_id"],
                        "committed_asset": committed_id,
                        "committed_sha256": hashlib.sha256(committed_data).hexdigest(),
                        "modes": ["after_commit", "after_files", "partial", "before_commit"],
                        "markers": markers,
                        "readback": read,
                        "replay_equal": replay == committed_result,
                        "integrity_check": integrity,
                        "foreign_key_check": foreign_keys,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            self.assertEqual(integrity, [("ok",)])
            self.assertEqual(foreign_keys, [])
            self.runtime = self.make_runtime(data_dir)
            self.session = self.runtime.session()

    def test_same_request_concurrent_import_has_one_asset(self):
        data = self._jpeg()
        rid = str(uuid.uuid4())

        def run():
            session = self.runtime.session()
            try:
                return observation_assets.import_asset(
                    session,
                    self.runtime,
                    profile_id=self.profile.id,
                    observation_id="obs-1",
                    request_id=rid,
                    expected_revision=1,
                    stream=io.BytesIO(data),
                    display_name="a.jpg",
                    caption=None,
                )
            finally:
                session.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [future.result() for future in [pool.submit(run), pool.submit(run)]]
        self.assertEqual(results[0], results[1])
        self.assertEqual(
            len(self.session.scalars(select(LocalObservationAsset).where(LocalObservationAsset.observation_id == "obs-1")).all()),
            1,
        )


if __name__ == "__main__":
    unittest.main()
