"""Pure batch-photo contract tests for #39 (no database, no migrations)."""

from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
import uuid
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from app.local import listening_assets
from app.local import listening_batch_assets as batch
from app.local import listening_service as service
from app.local import observation_assets as obs
from app.local.errors import LocalStorageError


def multipart(
    parts: list[tuple[str, str | None, bytes]],
    boundary: bytes = b"batch-boundary",
    *,
    close: bool = True,
    trailing: bytes = b"",
) -> bytes:
    chunks: list[bytes] = []
    for name, filename, payload in parts:
        chunks.append(b"--" + boundary + b"\r\n")
        disposition = f'form-data; name="{name}"'
        if filename is not None:
            disposition += f'; filename="{filename}"'
        chunks.append(f"Content-Disposition: {disposition}\r\n".encode())
        if filename is not None:
            chunks.append(b"Content-Type: application/octet-stream\r\n")
        chunks.append(b"\r\n")
        chunks.append(payload)
        chunks.append(b"\r\n")
    if close:
        chunks.append(b"--" + boundary + b"--\r\n")
    chunks.append(trailing)
    return b"".join(chunks)


def fields(request_id: str | None = None) -> list[tuple[str, str | None, bytes]]:
    return [
        ("request_id", None, (request_id or str(uuid.uuid4())).encode()),
        ("expected_revision", None, b"3"),
        (
            "assignments",
            None,
            (
                '[{"index":0,"domain":"health","group_id":"g-health-0",'
                '"display_name":"a.png"}]'
            ).encode(),
        ),
    ]


def assignment(index: int, domain: str, group_id: str, name: str) -> dict:
    return {
        "index": index,
        "domain": domain,
        "group_id": group_id,
        "display_name": name,
    }


class BatchMultipartTests(unittest.TestCase):
    def test_strict_parser_keeps_order_and_index(self) -> None:
        body = multipart(
            fields()
            + [
                ("file_0", "a.png", b"first"),
                ("file_1", "b.png", b"second"),
            ]
        )
        parsed_fields, files = batch.parse_batch_multipart(body, b"batch-boundary")
        self.assertEqual(parsed_fields["expected_revision"], "3")
        self.assertEqual(files, {0: b"first", 1: b"second"})

    def test_fifteen_files_are_accepted(self) -> None:
        assignments = [
            assignment(index, "health", f"g-{index}", f"{index}.png")
            for index in range(15)
        ]
        body = multipart(
            [
                ("request_id", None, b"request"),
                ("expected_revision", None, b"1"),
                ("assignments", None, json.dumps(assignments).encode()),
            ]
            + [
                (f"file_{index}", f"{index}.png", b"x")
                for index in range(15)
            ]
        )
        _parsed, files = batch.parse_batch_multipart(body, b"batch-boundary")
        self.assertEqual(sorted(files), list(range(15)))

    def test_parser_refuses_sixteen_files(self) -> None:
        body = multipart(
            fields()
            + [
                (f"file_{index}", f"{index}.png", b"x")
                for index in range(16)
            ]
        )
        with self.assertRaises(batch.ListeningBatchInvalid):
            batch.parse_batch_multipart(body, b"batch-boundary")

    def test_parser_refuses_duplicate_unknown_and_trailing_parts(self) -> None:
        duplicate = multipart(
            fields()
            + [
                ("file_0", "a.png", b"a"),
                ("file_0", "b.png", b"b"),
            ]
        )
        with self.assertRaises(batch.ListeningBatchInvalid):
            batch.parse_batch_multipart(duplicate, b"batch-boundary")

        unknown = multipart(fields() + [("other", "a.png", b"a")])
        with self.assertRaises(batch.ListeningBatchInvalid):
            batch.parse_batch_multipart(unknown, b"batch-boundary")

        trailing = multipart(fields() + [("file_0", "a.png", b"a")], trailing=b"junk")
        with self.assertRaises(batch.ListeningBatchInvalid):
            batch.parse_batch_multipart(trailing, b"batch-boundary")

        missing_close = multipart(
            fields() + [("file_0", "a.png", b"a")], close=False
        )
        with self.assertRaises(batch.ListeningBatchInvalid):
            batch.parse_batch_multipart(missing_close, b"batch-boundary")

    def test_parser_refuses_unknown_text_or_duplicate_field(self) -> None:
        unknown = multipart(
            fields()
            + [
                ("unknown_field", None, b"x"),
                ("file_0", "a.png", b"a"),
            ]
        )
        with self.assertRaises(batch.ListeningBatchInvalid):
            batch.parse_batch_multipart(unknown, b"batch-boundary")

        duplicate = multipart(
            [
                ("request_id", None, b"one"),
                ("request_id", None, b"two"),
                ("file_0", "a.png", b"a"),
            ]
        )
        with self.assertRaises(batch.ListeningBatchInvalid):
            batch.parse_batch_multipart(duplicate, b"batch-boundary")


class BatchApiContractTests(unittest.TestCase):
    def test_batch_route_and_assignments_parser(self) -> None:
        from app.local.listening_api import _batch_assignments, listening_router

        routes = {
            (route.path, tuple(sorted(route.methods)))
            for route in listening_router.routes
        }
        self.assertIn(
            ("/api/listening/records/{record_id}/photos/batch", ("POST",)),
            routes,
        )
        self.assertEqual(
            _batch_assignments({"assignments": '[{"index": 0}]'}),
            [{"index": 0}],
        )
        with self.assertRaises(batch.ListeningBatchInvalid):
            _batch_assignments({})
        with self.assertRaises(batch.ListeningBatchInvalid):
            _batch_assignments({"assignments": "{"})


class BatchNormalizationTests(unittest.TestCase):
    def test_hashes_each_file_and_rejects_duplicate_targets(self) -> None:
        items = batch._normalize_assignments(
            [
                assignment(0, "health", "g-health-0", "a.png"),
                assignment(1, "language", "g-language-0", "b.png"),
            ],
            {0: b"one", 1: b"two"},
        )
        self.assertEqual(
            items[0]["content_hash"], hashlib.sha256(b"one").hexdigest()
        )
        self.assertEqual(items[1]["display_name"], "b.png")

        with self.assertRaises(batch.ListeningBatchInvalid):
            batch._normalize_assignments(
                [
                    assignment(0, "health", "same", "a.png"),
                    assignment(1, "language", "same", "b.png"),
                ],
                {0: b"one", 1: b"two"},
            )

    def test_count_domain_and_index_rules(self) -> None:
        for assignments, files in (
            ([], {}),
            (
                [assignment(index, "health", f"g-{index}", "a") for index in range(16)],
                {index: b"x" for index in range(16)},
            ),
            ([assignment(0, "unknown", "g", "a")], {0: b"x"}),
            ([assignment(1, "health", "g", "a")], {0: b"x"}),
            ([assignment(0, "health", "g", "a")], {1: b"x"}),
            ([assignment(0, "health", "", "a")], {0: b"x"}),
        ):
            with self.subTest(assignments=assignments, files=files):
                with self.assertRaises(batch.ListeningBatchInvalid):
                    batch._normalize_assignments(assignments, files)

    def test_per_file_and_total_limits(self) -> None:
        with patch.object(obs, "MAX_SOURCE_BYTES", 4):
            with self.assertRaises(listening_assets.ListeningMaterialLimit):
                batch._normalize_assignments(
                    [assignment(0, "health", "g", "a.png")], {0: b"12345"}
                )
        with patch.object(batch, "MAX_BATCH_TOTAL_BYTES", 5):
            with self.assertRaises(listening_assets.ListeningMaterialLimit):
                batch._normalize_assignments(
                    [
                        assignment(0, "health", "g0", "a.png"),
                        assignment(1, "health", "g1", "b.png"),
                    ],
                    {0: b"123", 1: b"456"},
                )

    def test_unsafe_display_names_are_refused(self) -> None:
        for name in ("../escape.png", "CON", "a/b.png", "x" * 256):
            with self.subTest(name=name):
                with self.assertRaises(listening_assets.ListeningMaterialInvalid):
                    batch._normalize_assignments(
                        [assignment(0, "health", "g", name)], {0: b"x"}
                    )

    def test_fingerprint_is_deterministic_and_order_sensitive(self) -> None:
        first = batch._normalize_assignments(
            [
                assignment(0, "health", "g0", "a.png"),
                assignment(1, "language", "g1", "b.png"),
            ],
            {0: b"one", 1: b"two"},
        )
        second = batch._normalize_assignments(
            [
                assignment(0, "language", "g1", "b.png"),
                assignment(1, "health", "g0", "a.png"),
            ],
            {0: b"two", 1: b"one"},
        )
        one = batch.batch_fingerprint(
            profile_id="p", record_id="r", expected_revision=2, items=first
        )
        two = batch.batch_fingerprint(
            profile_id="p", record_id="r", expected_revision=2, items=first
        )
        three = batch.batch_fingerprint(
            profile_id="p", record_id="r", expected_revision=2, items=second
        )
        four = batch.batch_fingerprint(
            profile_id="p", record_id="r", expected_revision=3, items=first
        )
        self.assertEqual(one, two)
        self.assertNotEqual(one, three)
        self.assertNotEqual(one, four)
        self.assertEqual(len(one), 64)


class _FakeSession:
    def __init__(self, *, commit_error: Exception | None = None) -> None:
        self.added: list[object] = []
        self.commits = 0
        self.rollbacks = 0
        self.commit_error = commit_error

    def add(self, value: object) -> None:
        self.added.append(value)

    def commit(self) -> None:
        if self.commit_error is not None:
            raise self.commit_error
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def png(color=(40, 100, 200)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (2, 2), color).save(buffer, format="PNG")
    return buffer.getvalue()


class BatchTransactionBoundaryTests(unittest.TestCase):
    def test_occupied_target_refuses_before_staging_or_transaction(self) -> None:
        session = _FakeSession()
        with (
            patch.object(batch, "read_scope", lambda _session: nullcontext()),
            patch.object(service, "_replay", return_value=None),
            patch.object(
                service,
                "_load_record",
                return_value=(SimpleNamespace(revision=3, updated_at=None), None),
            ),
            patch.object(
                service,
                "_groups",
                return_value=[SimpleNamespace(id="g", asset_id="existing")],
            ),
        ):
            with self.assertRaises(batch.ListeningBatchTargetOccupied):
                batch._import_batch_impl(
                    session,
                    object(),
                    profile_id="p",
                    record_id="r",
                    request_id=str(uuid.uuid4()),
                    expected_revision=3,
                    assignments=[assignment(0, "health", "g", "a.png")],
                    files={0: b"x"},
                )
        self.assertEqual(session.added, [])
        self.assertEqual(session.commits, 0)
        self.assertEqual(session.rollbacks, 0)

    def test_replay_returns_without_staging_runtime_or_writes(self) -> None:
        session = _FakeSession()
        receipt = {"record_id": "r", "revision": 9, "items": []}
        with (
            patch.object(batch, "read_scope", lambda _session: nullcontext()),
            patch.object(service, "_replay", return_value=receipt),
        ):
            result = batch._import_batch_impl(
                session,
                object(),
                profile_id="p",
                record_id="r",
                request_id=str(uuid.uuid4()),
                expected_revision=2,
                assignments=[assignment(0, "health", "g", "a.png")],
                files={0: b"x"},
            )
        self.assertIs(result, receipt)
        self.assertEqual(session.added, [])
        self.assertEqual(session.commits, 0)

    def test_invalid_image_removes_staging_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data = Path(temporary) / "data"
            data.mkdir()
            runtime = SimpleNamespace(data_dir=data)
            with (
                patch.object(batch, "read_scope", lambda _session: nullcontext()),
                patch.object(service, "_replay", return_value=None),
                patch.object(
                    service,
                    "_load_record",
                    return_value=(SimpleNamespace(revision=1), None),
                ),
                patch.object(batch, "_check_targets_empty"),
            ):
                with self.assertRaises(listening_assets.ListeningMaterialInvalid):
                    batch._import_batch_impl(
                        object(),
                        runtime,
                        profile_id="p",
                        record_id="record-1",
                        request_id=str(uuid.uuid4()),
                        expected_revision=1,
                        assignments=[
                            assignment(0, "health", "g2", "synthetic.png")
                        ],
                        files={0: b"not a decodable image"},
                    )
            leftovers = [path for path in data.rglob("*") if path.is_file()]
            self.assertEqual(leftovers, [])

    def test_write_lock_refusal_removes_published_files(self) -> None:
        image = io.BytesIO()
        Image.new("RGB", (2, 2), (40, 100, 200)).save(image, format="PNG")
        with tempfile.TemporaryDirectory() as temporary:
            data = Path(temporary) / "data"
            data.mkdir()
            runtime = SimpleNamespace(data_dir=data)
            with (
                patch.object(batch, "read_scope", lambda _session: nullcontext()),
                patch.object(service, "_replay", return_value=None),
                patch.object(
                    service,
                    "_load_record",
                    return_value=(SimpleNamespace(revision=1), None),
                ),
                patch.object(batch, "_check_targets_empty"),
                patch.object(
                    batch,
                    "begin_immediate",
                    side_effect=LocalStorageError("synthetic write lock"),
                ),
            ):
                with self.assertRaises(LocalStorageError):
                    batch._import_batch_impl(
                        object(),
                        runtime,
                        profile_id="p",
                        record_id="record-1",
                        request_id=str(uuid.uuid4()),
                        expected_revision=1,
                        assignments=[
                            assignment(0, "health", "g2", "synthetic.png")
                        ],
                        files={0: image.getvalue()},
                    )
            leftovers = [path for path in data.rglob("*") if path.is_file()]
            self.assertEqual(leftovers, [])

    def test_two_file_publish_failure_removes_published_and_staged_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data = Path(temporary) / "data"
            data.mkdir()
            runtime = SimpleNamespace(data_dir=data)
            first, second = png((40, 100, 200)), png((200, 100, 40))
            real_move = obs._move_file
            calls = 0

            def flaky_move(*args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise obs.ObservationAssetStorage("synthetic second move")
                return real_move(*args, **kwargs)

            with (
                patch.object(batch, "read_scope", lambda _session: nullcontext()),
                patch.object(service, "_replay", return_value=None),
                patch.object(
                    service,
                    "_load_record",
                    return_value=(SimpleNamespace(revision=1), None),
                ),
                patch.object(batch, "_check_targets_empty"),
                patch.object(obs, "_move_file", side_effect=flaky_move),
            ):
                with self.assertRaises(listening_assets.ListeningAssetStorage):
                    batch._import_batch_impl(
                        object(),
                        runtime,
                        profile_id="p",
                        record_id="record-1",
                        request_id=str(uuid.uuid4()),
                        expected_revision=1,
                        assignments=[
                            assignment(0, "health", "g2", "a.png"),
                            assignment(1, "health", "g3", "b.png"),
                        ],
                        files={0: first, 1: second},
                    )
            self.assertEqual(calls, 2)
            leftovers = [path for path in data.rglob("*") if path.is_file()]
            self.assertEqual(leftovers, [])

    def test_uncertain_commit_keeps_published_files_for_receipt_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data = Path(temporary) / "data"
            data.mkdir()
            runtime = SimpleNamespace(data_dir=data)
            group = SimpleNamespace(id="g2", asset_id=None, updated_at=None)
            session = _FakeSession(commit_error=RuntimeError("synthetic commit uncertainty"))
            image = png()
            with (
                patch.object(batch, "read_scope", lambda _session: nullcontext()),
                patch.object(service, "_replay", return_value=None),
                patch.object(
                    service,
                    "_load_record",
                    return_value=(SimpleNamespace(revision=1, updated_at=None), None),
                ),
                patch.object(service, "_groups", return_value=[group]),
                patch.object(batch, "_check_targets_empty"),
                patch.object(batch, "begin_immediate"),
                patch.object(service, "_operation", return_value=None),
                patch.object(service, "_audit", return_value=None),
            ):
                with self.assertRaises(batch.ListeningBatchCommitUncertain) as raised:
                    batch._import_batch_impl(
                        session,
                        runtime,
                        profile_id="p",
                        record_id="record-1",
                        request_id=str(uuid.uuid4()),
                        expected_revision=1,
                        assignments=[assignment(0, "health", "g2", "a.png")],
                        files={0: image},
                    )
                self.assertEqual(
                    raised.exception.code, "LISTENING_BATCH_COMMIT_UNCERTAIN"
                )
            kept = [path for path in data.rglob("*") if path.is_file()]
            self.assertEqual(len(kept), 1)
            self.assertTrue(kept[0].name.startswith("original."))

            receipt = {"record_id": "record-1", "revision": 2, "items": []}
            with (
                patch.object(batch, "read_scope", lambda _session: nullcontext()),
                patch.object(service, "_replay", return_value=receipt),
            ):
                result = batch._import_batch_impl(
                    object(),
                    runtime,
                    profile_id="p",
                    record_id="record-1",
                    request_id=str(uuid.uuid4()),
                    expected_revision=1,
                    assignments=[assignment(0, "health", "g2", "a.png")],
                    files={0: image},
                )
            self.assertIs(result, receipt)
            self.assertEqual(
                [path for path in data.rglob("*") if path.is_file()], kept
            )

    def test_replay_after_publish_cleans_only_this_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data = Path(temporary) / "data"
            data.mkdir()
            runtime = SimpleNamespace(data_dir=data)
            receipt = {"record_id": "record-1", "revision": 7, "items": []}
            session = _FakeSession()
            with (
                patch.object(batch, "read_scope", lambda _session: nullcontext()),
                patch.object(service, "_replay", side_effect=[None, receipt]),
                patch.object(
                    service,
                    "_load_record",
                    return_value=(SimpleNamespace(revision=1), None),
                ),
                patch.object(batch, "_check_targets_empty"),
                patch.object(batch, "begin_immediate"),
            ):
                result = batch._import_batch_impl(
                    session,
                    runtime,
                    profile_id="p",
                    record_id="record-1",
                    request_id=str(uuid.uuid4()),
                    expected_revision=1,
                    assignments=[assignment(0, "health", "g2", "a.png")],
                    files={0: png()},
                )
            self.assertIs(result, receipt)
            self.assertEqual(session.commits, 0)
            self.assertEqual(session.rollbacks, 1)
            self.assertEqual(
                [path for path in data.rglob("*") if path.is_file()], []
            )

    def test_cleanup_only_touches_absolute_managed_leaf_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data"
            data.mkdir()
            runtime = SimpleNamespace(data_dir=data)
            outside = root / "outside.png"
            outside.write_bytes(b"keep")
            inside = (
                data / "observations" / "assets" / "listening"
                / "record-1" / "asset-1" / "original.png"
            )
            inside.parent.mkdir(parents=True)
            inside.write_bytes(b"remove")
            batch._cleanup_exact(
                [outside, Path("relative.png"), inside], runtime
            )
            self.assertEqual(outside.read_bytes(), b"keep")
            self.assertEqual(inside.exists(), False)

    def test_source_keeps_one_transaction_and_one_revision_increment(self) -> None:
        source = Path(batch.__file__).read_text(encoding="utf-8")
        self.assertEqual(source.count("record.revision += 1"), 1)
        self.assertEqual(source.count("session.commit()"), 1)
        self.assertEqual(source.count("service._operation("), 1)
        self.assertIn("commit_started = True", source)
        self.assertIn("if commit_started:", source)
        self.assertIn("ListeningBatchCommitUncertain", source)
        self.assertIn('kind="listening_asset_batch_import"', source)
        self.assertIn('action="listening_asset_batch_import"', source)
        self.assertNotIn("shutil.rmtree", source)
        self.assertNotIn("delete(", source)

        inspect_at = source.index("obs.inspect_managed_asset(")
        move_at = source.index("obs._move_file(")
        begin_at = source.index("begin_immediate(session)")
        first_replay = source.index("with read_scope(session):")
        self.assertLess(first_replay, inspect_at)
        self.assertLess(inspect_at, move_at)
        self.assertLess(move_at, begin_at)
        self.assertLess(
            source.index("if record.revision != revision:"),
            source.index("record.revision += 1"),
        )


if __name__ == "__main__":
    unittest.main()
