"""Listening export manager: term scope, frozen snapshot, cache and image work bytes."""

from __future__ import annotations

import hashlib
import io
import threading
import time
import unittest
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from PIL import Image
from sqlalchemy import select

from app.local import (
    listening_assets,
    listening_export_service,
    listening_service,
    profile_service,
)
from app.local.models import LocalListeningAsset
from app.local.normalize import normalize_initialization
from app.local.runtime import LocalRuntime
from app.services.word_export_listening import ListeningWordPhoto
from tests.local.test_listening_word import _image

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _exif_jpeg(orientation: int) -> bytes:
    image = Image.new("RGB", (80, 40), (10, 20, 30))
    # Four colored corners make orientation visible without relying on text.
    image.paste((220, 20, 20), (0, 0, 20, 20))
    image.paste((20, 220, 20), (60, 0, 80, 20))
    image.paste((20, 20, 220), (0, 20, 20, 40))
    image.paste((220, 220, 20), (60, 20, 80, 40))
    exif = Image.Exif()
    exif[274] = orientation
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=100, subsampling=0, exif=exif)
    return buffer.getvalue()


class ListeningExportServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory(prefix="kgm-listening-export-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runtime = LocalRuntime(
            self.root / "data", credential_root=self.root / "credentials"
        )
        self.runtime.prepare()
        self.addCleanup(self.runtime.dispose)
        session = self.runtime.session()
        try:
            profile_service.initialize(
                session,
                normalize_initialization(
                    **{
                        "request_id": str(uuid.uuid4()),
                        "display_name": "合成教师",
                        "class_name": "中班合册联测",
                        "grade": "middle",
                        "term_name": "旧学期",
                        "start_date": "2026-03-01",
                        "end_date": "2026-06-30",
                        "school_name": "合成资料",
                    }
                ),
            )
            context = profile_service.require_context(session, date(2026, 11, 7))
            self.profile_id = context.profile.id
            self.term_id = context.terms[0].id
        finally:
            session.close()
        self.manager = listening_export_service.ListeningExportManager(
            self.runtime, launch_id="service-test-launch"
        )

    def _context(self, session):
        return profile_service.require_context(session, date(2026, 11, 7))

    def _create(self, name: str = "虚构甲") -> dict:
        session = self.runtime.session()
        try:
            return listening_service.create_record(
                session,
                profile_id=self.profile_id,
                request_id=str(uuid.uuid4()),
                term_id=self.term_id,
                child_name=name,
            )
        finally:
            session.close()

    def _preview(self, **kwargs):
        session = self.runtime.session()
        try:
            return self.manager.preview(
                session,
                profile_id=self.profile_id,
                context=self._context(session),
                **kwargs,
            )
        finally:
            session.close()

    def _patch(
        self,
        record_id: str,
        domain: str = "health",
        patch: dict | None = None,
        revision: int = 1,
    ):
        session = self.runtime.session()
        try:
            return listening_service.save_domain(
                session,
                profile_id=self.profile_id,
                record_id=record_id,
                domain=domain,
                request_id=str(uuid.uuid4()),
                expected_revision=revision,
                patch=patch or {"goal": "修改后的目标"},
            )
        finally:
            session.close()

    def _import(self, record_id: str, domain: str, payload: bytes, name: str = "图.jpg"):
        session = self.runtime.session()
        try:
            record = listening_service.read_record(
                session, profile_id=self.profile_id, record_id=record_id
            )
            group_id = next(
                item["groups"][0]["group_id"]
                for item in record["domains"]
                if item["domain"] == domain
            )
            return listening_assets.import_group_photo(
                session,
                self.runtime,
                profile_id=self.profile_id,
                record_id=record_id,
                domain=domain,
                group_id=group_id,
                request_id=str(uuid.uuid4()),
                expected_revision=record["revision"],
                stream=io.BytesIO(payload),
                display_name=name,
            )
        finally:
            session.close()

    def test_old_term_personal_and_domain_use_the_stored_term(self) -> None:
        record = self._create()
        personal = self._preview(
            mode="record",
            record_id=record["record_id"],
            term_id=self.term_id,
        )
        self.assertEqual(personal["term_id"], self.term_id)
        self.assertEqual(
            [unit["domain"] for unit in personal["units"]],
            ["language", "science", "health", "social", "art"],
        )
        without_term = self._preview(
            mode="record", record_id=record["record_id"]
        )
        self.assertEqual(without_term["term_id"], self.term_id)

        explicit = self._preview(
            mode="domain",
            domain="science",
            record_ids=[record["record_id"]],
        )
        self.assertEqual(explicit["record_ids"], [record["record_id"]])
        self.assertEqual(explicit["term_id"], self.term_id)
        default = self._preview(
            mode="domain", domain="science", term_id=self.term_id
        )
        self.assertEqual(default["record_ids"], [record["record_id"]])

        with self.assertRaises(
            listening_export_service.ListeningExportSelectionInvalid
        ):
            self._preview(mode="domain", domain="science")
        with self.assertRaises(
            listening_export_service.ListeningExportSelectionInvalid
        ):
            self._preview(
                mode="record",
                record_id=record["record_id"],
                term_id="not-a-term",
            )
        with self.assertRaises(
            listening_export_service.ListeningExportSelectionInvalid
        ):
            self._preview(
                mode="domain",
                domain="science",
                record_ids=[record["record_id"]],
                term_id="not-a-term",
            )

    def test_default_filename_sanitizes_only_the_fragment(self) -> None:
        record = self._create("虚构乙/合成")
        preview = self._preview(
            mode="record",
            record_id=record["record_id"],
            term_id=self.term_id,
        )
        self.assertNotIn("/", preview["default_filename"])
        self.assertLessEqual(len(preview["default_filename"]), 160)
        self.assertIn("虚构乙_合成", preview["default_filename"])
        # The stored record name remains untouched.
        session = self.runtime.session()
        try:
            dto = listening_service.read_record(
                session,
                profile_id=self.profile_id,
                record_id=record["record_id"],
            )
        finally:
            session.close()
        self.assertEqual(dto["child_name"], "虚构乙/合成")

        request = str(uuid.uuid4())
        first = self.manager.generate(
            preview_id=preview["preview_id"],
            request_id=request,
            filename=preview["default_filename"],
            ack_missing=True,
        )
        with self.assertRaises(
            listening_export_service.ListeningExportRequestConflict
        ):
            self.manager.generate(
                preview_id=preview["preview_id"],
                request_id=request,
                filename="不同文件名.docx",
                ack_missing=True,
            )
        self.assertEqual(
            self.manager.request_receipt(request)["export_id"],
            first["export_id"],
        )

    def test_shared_header_fallback_matches_display_and_word(self) -> None:
        record = self._create()
        self._patch(
            record["record_id"],
            "health",
            {"adult_count": "2 位", "child_age": "5 岁"},
            revision=1,
        )
        self._patch(
            record["record_id"],
            "language",
            {"adult_count": "3 位"},
            revision=2,
        )
        preview = self._preview(
            mode="record",
            record_id=record["record_id"],
            term_id=self.term_id,
        )
        ready = self.manager.generate(
            preview_id=preview["preview_id"],
            request_id=str(uuid.uuid4()),
            filename=preview["default_filename"],
            ack_missing=True,
        )
        payload = self.manager.content(ready["export_id"])
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            root = __import__("lxml.etree", fromlist=["etree"]).fromstring(
                archive.read("word/document.xml")
            )
        text = "".join(root.itertext())
        self.assertEqual(text.count("成人数目：2 位"), 4)
        self.assertEqual(text.count("成人数目：3 位"), 1)
        self.assertEqual(text.count("幼儿年龄：5 岁"), 5)

    def test_missing_ack_is_required_and_leaves_cells_blank(self) -> None:
        record = self._create()
        preview = self._preview(
            mode="record",
            record_id=record["record_id"],
            term_id=self.term_id,
        )
        self.assertGreater(preview["missing_count"], 0)
        with self.assertRaises(
            listening_export_service.ListeningExportAckRequired
        ):
            self.manager.generate(
                preview_id=preview["preview_id"],
                request_id=str(uuid.uuid4()),
                filename=preview["default_filename"],
                ack_missing=False,
            )
        ready = self.manager.generate(
            preview_id=preview["preview_id"],
            request_id=str(uuid.uuid4()),
            filename=preview["default_filename"],
            ack_missing=True,
        )
        payload = self.manager.content(ready["export_id"])
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            root = __import__("lxml.etree", fromlist=["etree"]).fromstring(
                archive.read("word/document.xml")
            )
        table = root.find(f"{W}body/{W}tbl")
        header = "".join(table.findall(f"{W}tr")[0].itertext())
        self.assertIn("观察日期：", header)
        self.assertNotIn("观察日期：虚构", header)
        first_group = table.findall(f"{W}tr")[2]
        self.assertEqual("".join(first_group.findall(f"{W}tc")[1].itertext()), "")

    def test_stale_preview_is_refused(self) -> None:
        record = self._create()
        preview = self._preview(
            mode="record",
            record_id=record["record_id"],
            term_id=self.term_id,
        )
        self._patch(record["record_id"])
        with self.assertRaises(listening_export_service.ListeningExportStale):
            self.manager.generate(
                preview_id=preview["preview_id"],
                request_id=str(uuid.uuid4()),
                filename=preview["default_filename"],
                ack_missing=True,
            )

    def test_registered_but_missing_image_is_an_error_not_missing_photo(self) -> None:
        record = self._create()
        imported = self._import(record["record_id"], "health", _image("JPEG"))
        session = self.runtime.session()
        try:
            asset = session.scalars(
                select(LocalListeningAsset).where(
                    LocalListeningAsset.id == imported["asset_id"]
                )
            ).one()
            path = Path(self.runtime.data_dir) / asset.relative_path
        finally:
            session.close()
        path.unlink()
        with self.assertRaises(
            listening_export_service.ListeningExportImageInvalid
        ):
            self._preview(
                mode="record",
                record_id=record["record_id"],
                term_id=self.term_id,
            )

    def test_exif_orientation_work_bytes_and_original_are_separate(self) -> None:
        record = self._create()
        source6 = _exif_jpeg(6)
        source8 = _exif_jpeg(8)
        imported6 = self._import(
            record["record_id"], "health", source6, "orientation6.jpg"
        )
        imported8 = self._import(
            record["record_id"], "language", source8, "orientation8.jpg"
        )
        preview = self._preview(
            mode="record",
            record_id=record["record_id"],
            term_id=self.term_id,
        )
        photos = {
            (unit["domain"], photo["group_id"]): photo
            for unit in preview["units"]
            for photo in unit["photos"]
        }
        for domain, imported, orientation, expected, source in (
            ("health", imported6, 6, (40, 80), source6),
            ("language", imported8, 8, (40, 80), source8),
        ):
            photo = next(
                value
                for (photo_domain, _group), value in photos.items()
                if photo_domain == domain
            )
            self.assertEqual(photo["orientation"], orientation)
            self.assertEqual((photo["source_width"], photo["source_height"]), (80, 40))
            self.assertEqual((photo["width"], photo["height"]), expected)
            self.assertNotEqual(photo["source_sha256"], photo["work_sha256"])
            self.assertEqual(photo["source_sha256"], hashlib.sha256(source).hexdigest())
            self.assertEqual(photo["source_bytes"], len(source))
        # The original asset bytes and registered hash are unchanged.
        session = self.runtime.session()
        try:
            for imported in (imported6, imported8):
                asset = session.scalars(
                    select(LocalListeningAsset).where(
                        LocalListeningAsset.id == imported["asset_id"]
                    )
                ).one()
                payload, metadata = listening_assets.read_asset(
                    session,
                    self.runtime,
                    profile_id=self.profile_id,
                    record_id=record["record_id"],
                    asset_id=asset.id,
                )
                self.assertEqual(metadata["orientation"] in (6, 8), True)
                self.assertEqual(
                    hashlib.sha256(payload).hexdigest(), asset.content_hash
                )
        finally:
            session.close()


    def test_retire_invalidates_previews_and_runtime_holds_manager(self) -> None:
        record = self._create()
        preview = self._preview(
            mode="record",
            record_id=record["record_id"],
            term_id=self.term_id,
        )
        self.runtime.listening_export_manager = self.manager
        self.runtime._retire_listening_exports()
        self.assertIsNone(self.runtime.listening_export_manager)
        self.assertTrue(self.manager._retired)
        with self.assertRaises(listening_export_service.ListeningExportNotFound):
            self.manager.generate(
                preview_id=preview["preview_id"],
                request_id=str(uuid.uuid4()),
                filename=preview["default_filename"],
                ack_missing=True,
            )

    def test_all_allowed_orientation_one_formats_keep_original_bytes(self) -> None:
        metadata = {
            "width": 10,
            "height": 20,
            "orientation": None,
            "mime_type": "image/png",
        }
        for fmt, mime in (
            ("PNG", "image/png"),
            ("JPEG", "image/jpeg"),
            ("WEBP", "image/webp"),
            ("GIF", "image/gif"),
            ("BMP", "image/bmp"),
        ):
            payload = _image(fmt, (10, 20))
            prepared = listening_export_service._prepare_word_photo(
                payload,
                {**metadata, "mime_type": mime, "width": 10, "height": 20},
            )
            self.assertEqual(prepared["data"], payload)
            self.assertEqual(prepared["mime_type"], mime)
            self.assertEqual((prepared["width"], prepared["height"]), (10, 20))

    def test_manager_replay_concurrency_capacity_and_expiry(self) -> None:
        record = self._create()
        original = listening_export_service.generate_listening_docx
        listing_export_service = listening_export_service

        def stub(_units):
            return b"PK\x03\x04stub"

        listing_export_service.generate_listening_docx = stub
        self.addCleanup(
            setattr,
            listening_export_service,
            "generate_listening_docx",
            original,
        )
        try:
            preview = self._preview(
                mode="record",
                record_id=record["record_id"],
                term_id=self.term_id,
            )
            request = str(uuid.uuid4())
            first = self.manager.generate(
                preview_id=preview["preview_id"],
                request_id=request,
                filename="a.docx",
                ack_missing=True,
            )
            again = self.manager.generate(
                preview_id=preview["preview_id"],
                request_id=request,
                filename="a.docx",
                ack_missing=True,
            )
            self.assertEqual(first["export_id"], again["export_id"])
            with self.assertRaises(
                listening_export_service.ListeningExportRequestConflict
            ):
                self.manager.generate(
                    preview_id=preview["preview_id"],
                    request_id=request,
                    filename="b.docx",
                    ack_missing=True,
                )

            race_preview = self._preview(
                mode="record",
                record_id=record["record_id"],
                term_id=self.term_id,
            )
            race_request = str(uuid.uuid4())
            entered = threading.Event()
            release = threading.Event()
            calls = [0]

            def slow(_units):
                calls[0] += 1
                entered.set()
                self.assertTrue(release.wait(10))
                return b"PK\x03\x04stub"

            listing_export_service.generate_listening_docx = slow

            def run():
                return self.manager.generate(
                    preview_id=race_preview["preview_id"],
                    request_id=race_request,
                    filename="race.docx",
                    ack_missing=True,
                )

            with ThreadPoolExecutor(max_workers=2) as pool:
                one = pool.submit(run)
                self.assertTrue(entered.wait(10))
                self.assertTrue(self.manager.has_active_work)
                two = pool.submit(run)
                time.sleep(0.1)
                release.set()
                results = [one.result(10), two.result(10)]
            self.assertEqual(calls[0], 1)
            self.assertEqual(results[0]["export_id"], results[1]["export_id"])
            self.assertFalse(self.manager.has_active_work)

            listing_export_service.generate_listening_docx = stub
            for index in range(listening_export_service.MAX_EXPORTS + 1):
                item = self._preview(
                    mode="record",
                    record_id=record["record_id"],
                    term_id=self.term_id,
                )
                self.manager.generate(
                    preview_id=item["preview_id"],
                    request_id=str(uuid.uuid4()),
                    filename=f"memory-{index}.docx",
                    ack_missing=True,
                )
            self.assertLessEqual(
                len(self.manager._exports), listening_export_service.MAX_EXPORTS
            )

            future = listening_export_service.utc_now() + timedelta(
                seconds=listening_export_service.EXPORT_TTL_SECONDS + 1
            )
            with self.assertRaises(listening_export_service.ListeningExportNotFound):
                self.manager.content(first["export_id"], now=future)
            with mock.patch.object(
                listening_export_service, "utc_now", return_value=future
            ):
                with self.assertRaises(
                    listening_export_service.ListeningExportNotFound
                ):
                    self.manager.request_receipt(request)
        finally:
            listing_export_service.generate_listening_docx = original
