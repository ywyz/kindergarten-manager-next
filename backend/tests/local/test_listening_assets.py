"""Listening photo ownership, barrier and failure behaviour."""

from __future__ import annotations

import io
import sqlite3
import threading
import time
import uuid

import pytest
from PIL import Image

from app.local import (
    backup_barrier,
    listening_assets,
    listening_service,
    observation_assets,
    profile_service,
)
from app.local.normalize import normalize_initialization
from app.local.runtime import LocalRuntime
from tests.local.support import initialize_body

from datetime import date


def _runtime(tmp_path, name="data") -> LocalRuntime:
    runtime = LocalRuntime(
        tmp_path / name, credential_root=tmp_path / (name + "-cred")
    )
    runtime.prepare()
    session = runtime.session()
    try:
        profile_service.initialize(
            session, normalize_initialization(**initialize_body())
        )
        session.commit()
    finally:
        session.close()
    return runtime


def _context(runtime: LocalRuntime):
    session = runtime.session()
    try:
        context = profile_service.require_context(session, date.today())
        return context.profile.id, context.terms[0].id
    finally:
        session.close()


def _record(runtime: LocalRuntime, name="照片幼儿"):
    profile_id, term_id = _context(runtime)
    session = runtime.session()
    try:
        created = listening_service.create_record(
            session,
            profile_id=profile_id,
            request_id=str(uuid.uuid4()),
            term_id=term_id,
            child_name=name,
        )
        record = listening_service.read_record(
            session, profile_id=profile_id, record_id=created["record_id"]
        )
        return profile_id, record
    finally:
        session.close()


def _image(color=(20, 120, 200), size=(32, 24), fmt="PNG") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, fmt)
    return buffer.getvalue()


def _files(root) -> dict[str, int]:
    result: dict[str, int] = {}
    base = root / "observations"
    if base.exists():
        for path in base.rglob("*"):
            if path.is_file():
                result[str(path.relative_to(root))] = path.stat().st_size
    return result


def test_import_replace_remove_and_old_asset_read(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    try:
        profile_id, record = _record(runtime)
        group_id = record["domains"][0]["groups"][0]["group_id"]
        session = runtime.session()
        try:
            first = listening_assets.import_group_photo(
                session,
                runtime,
                profile_id=profile_id,
                record_id=record["record_id"],
                domain="health",
                group_id=group_id,
                request_id=str(uuid.uuid4()),
                expected_revision=record["revision"],
                stream=io.BytesIO(_image((1, 2, 3), fmt="JPEG")),
                display_name="first.jpg",
            )
            assert first["revision"] == record["revision"] + 1
            payload, metadata = listening_assets.read_asset(
                session,
                runtime,
                profile_id=profile_id,
                record_id=record["record_id"],
                asset_id=first["asset_id"],
            )
            assert len(payload) == first["byte_size"]
            assert metadata["content_hash"] == first["content_hash"]
            current = listening_service.read_record(
                session, profile_id=profile_id, record_id=record["record_id"]
            )
            second = listening_assets.import_group_photo(
                session,
                runtime,
                profile_id=profile_id,
                record_id=record["record_id"],
                domain="health",
                group_id=group_id,
                request_id=str(uuid.uuid4()),
                expected_revision=current["revision"],
                stream=io.BytesIO(_image((200, 10, 10), fmt="PNG")),
                display_name="second.png",
            )
            assert second["old_asset_id"] == first["asset_id"]
            # Replaced original remains readable and its file is retained.
            old_payload, _old_meta = listening_assets.read_asset(
                session,
                runtime,
                profile_id=profile_id,
                record_id=record["record_id"],
                asset_id=first["asset_id"],
            )
            assert old_payload == _image((1, 2, 3), fmt="JPEG")
            current = listening_service.read_record(
                session, profile_id=profile_id, record_id=record["record_id"]
            )
            removed = listening_assets.remove_group_photo(
                session,
                profile_id=profile_id,
                record_id=record["record_id"],
                domain="health",
                group_id=group_id,
                request_id=str(uuid.uuid4()),
                expected_revision=current["revision"],
            )
            assert removed["changed"] is True
            assert removed["old_asset_id"] == second["asset_id"]
            current = listening_service.read_record(
                session, profile_id=profile_id, record_id=record["record_id"]
            )
            assert current["domains"][0]["groups"][0]["asset_id"] is None
            still_readable, _meta = listening_assets.read_asset(
                session,
                runtime,
                profile_id=profile_id,
                record_id=record["record_id"],
                asset_id=second["asset_id"],
            )
            assert still_readable == _image((200, 10, 10), fmt="PNG")
        finally:
            session.close()
    finally:
        runtime.dispose()


def test_reorder_swaps_unique_positions_once(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    try:
        profile_id, record = _record(runtime)
        session = runtime.session()
        try:
            groups = record["domains"][0]["groups"]
            group_ids = [group["group_id"] for group in groups]
            order = [group_ids[2], group_ids[0], group_ids[1]]
            request_id = str(uuid.uuid4())
            result = listening_assets.reorder_groups(
                session,
                profile_id=profile_id,
                record_id=record["record_id"],
                domain="health",
                request_id=request_id,
                expected_revision=record["revision"],
                group_ids=order,
            )
            assert result["changed"] is True
            current = listening_service.read_record(
                session, profile_id=profile_id, record_id=record["record_id"]
            )
            assert [group["group_id"] for group in current["domains"][0]["groups"]] == order
            # A replay of the same request id returns the original receipt and
            # must not swap a second time.
            replay = listening_assets.reorder_groups(
                session,
                profile_id=profile_id,
                record_id=record["record_id"],
                domain="health",
                request_id=request_id,
                expected_revision=record["revision"],
                group_ids=order,
            )
            assert replay == result
            after = listening_service.read_record(
                session, profile_id=profile_id, record_id=record["record_id"]
            )
            assert [group["group_id"] for group in after["domains"][0]["groups"]] == order
            # Changing the same request id to a different order is refused.
            with pytest.raises(listening_service.ListeningRequestConflict):
                listening_assets.reorder_groups(
                    session,
                    profile_id=profile_id,
                    record_id=record["record_id"],
                    domain="health",
                    request_id=request_id,
                    expected_revision=record["revision"],
                    group_ids=[group_ids[0], group_ids[1], group_ids[2]],
                )
        finally:
            session.close()
    finally:
        runtime.dispose()


def test_invalid_image_keeps_old_association_and_releases_barrier(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    try:
        profile_id, record = _record(runtime)
        group_id = record["domains"][0]["groups"][0]["group_id"]
        session = runtime.session()
        try:
            good = listening_assets.import_group_photo(
                session,
                runtime,
                profile_id=profile_id,
                record_id=record["record_id"],
                domain="health",
                group_id=group_id,
                request_id=str(uuid.uuid4()),
                expected_revision=record["revision"],
                stream=io.BytesIO(_image()),
                display_name="good.png",
            )
            current = listening_service.read_record(
                session, profile_id=profile_id, record_id=record["record_id"]
            )
            with pytest.raises(listening_assets.ListeningMaterialInvalid):
                listening_assets.import_group_photo(
                    session,
                    runtime,
                    profile_id=profile_id,
                    record_id=record["record_id"],
                    domain="health",
                    group_id=group_id,
                    request_id=str(uuid.uuid4()),
                    expected_revision=current["revision"],
                    stream=io.BytesIO(b"not an image"),
                    display_name="bad.jpg",
                )
            after = listening_service.read_record(
                session, profile_id=profile_id, record_id=record["record_id"]
            )
            assert after["revision"] == current["revision"]
            assert after["domains"][0]["groups"][0]["asset_id"] == good["asset_id"]
            payload, _meta = listening_assets.read_asset(
                session,
                runtime,
                profile_id=profile_id,
                record_id=record["record_id"],
                asset_id=good["asset_id"],
            )
            assert payload == _image()
            barrier = backup_barrier.get_barrier(runtime.data_dir)
            assert barrier.active_counts == (0, 0)
        finally:
            session.close()
    finally:
        runtime.dispose()


def test_exclusive_lease_refuses_import_with_zero_file_writes(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    try:
        profile_id, record = _record(runtime)
        group_id = record["domains"][0]["groups"][0]["group_id"]
        barrier = backup_barrier.get_barrier(runtime.data_dir)
        before = _files(tmp_path / "data")
        lease = barrier.begin_intent("test-exclusive")
        try:
            barrier.wait_idle(lease, timeout=5)
            barrier.acquire_exclusive(lease)
            session = runtime.session()
            try:
                with pytest.raises(backup_barrier.SnapshotBusy) as caught:
                    listening_assets.import_group_photo(
                        session,
                        runtime,
                        profile_id=profile_id,
                        record_id=record["record_id"],
                        domain="health",
                        group_id=group_id,
                        request_id=str(uuid.uuid4()),
                        expected_revision=record["revision"],
                        stream=io.BytesIO(_image()),
                        display_name="blocked.png",
                    )
                assert caught.value.code == "LOCAL_BACKUP_BUSY"
            finally:
                session.close()
            assert _files(tmp_path / "data") == before
            assert barrier.active_counts == (0, 0)
            db = sqlite3.connect(str(runtime.db_path))
            try:
                assert db.execute(
                    "SELECT COUNT(*) FROM local_listening_assets"
                ).fetchone()[0] == 0
                assert db.execute(
                    "SELECT revision FROM local_listening_records WHERE id = ?",
                    (record["record_id"],),
                ).fetchone()[0] == record["revision"]
            finally:
                db.close()
        finally:
            lease.release()
    finally:
        runtime.dispose()


def test_exclusive_waits_for_paused_publish(tmp_path, monkeypatch) -> None:
    runtime = _runtime(tmp_path)
    try:
        profile_id, record = _record(runtime)
        group_id = record["domains"][0]["groups"][0]["group_id"]
        paused = threading.Event()
        resume = threading.Event()
        real_move = observation_assets._move_file

        def slow_move(*args, **kwargs):
            paused.set()
            if not resume.wait(15):
                raise RuntimeError("publish pause timed out")
            return real_move(*args, **kwargs)

        monkeypatch.setattr(observation_assets, "_move_file", slow_move)
        result: dict[str, object] = {}

        def importer() -> None:
            session = runtime.session()
            try:
                result["value"] = listening_assets.import_group_photo(
                    session,
                    runtime,
                    profile_id=profile_id,
                    record_id=record["record_id"],
                    domain="health",
                    group_id=group_id,
                    request_id=str(uuid.uuid4()),
                    expected_revision=record["revision"],
                    stream=io.BytesIO(_image()),
                    display_name="paused.png",
                )
            except BaseException as exc:  # noqa: BLE001 - recorded for assertion
                result["error"] = repr(exc)
            finally:
                session.close()

        thread = threading.Thread(target=importer, daemon=True)
        thread.start()
        try:
            assert paused.wait(10)
            barrier = backup_barrier.get_barrier(runtime.data_dir)
            assert barrier.active_counts == (0, 1)
            backup_done = threading.Event()

            def backup() -> None:
                lease = barrier.begin_intent("test-wait")
                try:
                    barrier.wait_idle(lease, timeout=10)
                    barrier.acquire_exclusive(lease)
                    backup_done.set()
                    time.sleep(0.2)
                finally:
                    lease.release()

            backup_thread = threading.Thread(target=backup, daemon=True)
            backup_thread.start()
            time.sleep(0.5)
            assert backup_done.is_set() is False
            assert barrier.active_counts == (0, 1)
            resume.set()
            thread.join(15)
            backup_thread.join(15)
            assert backup_done.is_set() is True
            assert "value" in result, result
            assert barrier.active_counts == (0, 0)
        finally:
            resume.set()
            thread.join(15)
    finally:
        runtime.dispose()


def test_cross_record_and_group_guards(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    try:
        profile_id, first = _record(runtime, "甲")
        _profile_id, second = _record(runtime, "乙")
        session = runtime.session()
        try:
            first_group = first["domains"][0]["groups"][0]["group_id"]
            second_group = second["domains"][0]["groups"][0]["group_id"]
            with pytest.raises(listening_assets.ListeningAssetNotFound):
                listening_assets.import_group_photo(
                    session,
                    runtime,
                    profile_id=profile_id,
                    record_id=first["record_id"],
                    domain="health",
                    group_id=second_group,
                    request_id=str(uuid.uuid4()),
                    expected_revision=first["revision"],
                    stream=io.BytesIO(_image()),
                    display_name="cross.png",
                )
            with pytest.raises(listening_assets.ListeningMaterialInvalid):
                listening_assets.reorder_groups(
                    session,
                    profile_id=profile_id,
                    record_id=first["record_id"],
                    domain="health",
                    request_id=str(uuid.uuid4()),
                    expected_revision=first["revision"],
                    group_ids=[
                        first_group,
                        first["domains"][0]["groups"][1]["group_id"],
                        second_group,
                    ],
                )
            imported = listening_assets.import_group_photo(
                session,
                runtime,
                profile_id=profile_id,
                record_id=first["record_id"],
                domain="health",
                group_id=first_group,
                request_id=str(uuid.uuid4()),
                expected_revision=first["revision"],
                stream=io.BytesIO(_image()),
                display_name="first.png",
            )
            with pytest.raises(listening_assets.ListeningAssetNotFound):
                listening_assets.read_asset(
                    session,
                    runtime,
                    profile_id=profile_id,
                    record_id=second["record_id"],
                    asset_id=imported["asset_id"],
                )
            # Only the three domain groups exist; no fourth group can be
            # addressed even by a random id.
            with pytest.raises(listening_assets.ListeningAssetNotFound):
                listening_assets.import_group_photo(
                    session,
                    runtime,
                    profile_id=profile_id,
                    record_id=first["record_id"],
                    domain="health",
                    group_id="fourth_group_id",
                    request_id=str(uuid.uuid4()),
                    expected_revision=first["revision"],
                    stream=io.BytesIO(_image()),
                    display_name="fourth.png",
                )
            current = listening_service.read_record(
                session, profile_id=profile_id, record_id=first["record_id"]
            )
            assert len(current["domains"][0]["groups"]) == 3
        finally:
            session.close()
    finally:
        runtime.dispose()


def test_path_layout_tamper_is_refused(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    try:
        profile_id, record = _record(runtime)
        group_id = record["domains"][0]["groups"][0]["group_id"]
        session = runtime.session()
        try:
            imported = listening_assets.import_group_photo(
                session,
                runtime,
                profile_id=profile_id,
                record_id=record["record_id"],
                domain="health",
                group_id=group_id,
                request_id=str(uuid.uuid4()),
                expected_revision=record["revision"],
                stream=io.BytesIO(_image()),
                display_name="tamper.png",
            )
        finally:
            session.close()
        db = sqlite3.connect(str(runtime.db_path))
        try:
            db.execute(
                "UPDATE local_listening_assets SET relative_path = ? WHERE id = ?",
                (
                    "observations/assets/listening/../outside.png",
                    imported["asset_id"],
                ),
            )
            db.commit()
        finally:
            db.close()
        session = runtime.session()
        try:
            with pytest.raises(listening_assets.ListeningMaterialInvalid):
                listening_assets.read_asset(
                    session,
                    runtime,
                    profile_id=profile_id,
                    record_id=record["record_id"],
                    asset_id=imported["asset_id"],
                )
        finally:
            session.close()
    finally:
        runtime.dispose()


def test_exclusive_waits_for_paused_staging(tmp_path, monkeypatch) -> None:
    runtime = _runtime(tmp_path)
    try:
        profile_id, record = _record(runtime)
        group_id = record["domains"][0]["groups"][0]["group_id"]
        paused = threading.Event()
        resume = threading.Event()
        real_write = observation_assets._write_staging

        def slow_write(*args, **kwargs):
            paused.set()
            if not resume.wait(15):
                raise RuntimeError("staging pause timed out")
            return real_write(*args, **kwargs)

        monkeypatch.setattr(observation_assets, "_write_staging", slow_write)
        result: dict[str, object] = {}

        def importer() -> None:
            session = runtime.session()
            try:
                result["value"] = listening_assets.import_group_photo(
                    session,
                    runtime,
                    profile_id=profile_id,
                    record_id=record["record_id"],
                    domain="health",
                    group_id=group_id,
                    request_id=str(uuid.uuid4()),
                    expected_revision=record["revision"],
                    stream=io.BytesIO(_image()),
                    display_name="paused-staging.png",
                )
            except BaseException as exc:  # noqa: BLE001 - recorded for assertion
                result["error"] = repr(exc)
            finally:
                session.close()

        thread = threading.Thread(target=importer, daemon=True)
        thread.start()
        try:
            assert paused.wait(10)
            barrier = backup_barrier.get_barrier(runtime.data_dir)
            assert barrier.active_counts == (0, 1)
            backup_done = threading.Event()

            def backup() -> None:
                lease = barrier.begin_intent("test-staging-wait")
                try:
                    barrier.wait_idle(lease, timeout=10)
                    barrier.acquire_exclusive(lease)
                    backup_done.set()
                    time.sleep(0.2)
                finally:
                    lease.release()

            backup_thread = threading.Thread(target=backup, daemon=True)
            backup_thread.start()
            time.sleep(0.5)
            assert backup_done.is_set() is False
            assert barrier.active_counts == (0, 1)
            resume.set()
            thread.join(15)
            backup_thread.join(15)
            assert backup_done.is_set() is True
            assert "value" in result, result
            assert barrier.active_counts == (0, 0)
        finally:
            resume.set()
            thread.join(15)
    finally:
        runtime.dispose()


def test_publish_failure_releases_barrier_and_keeps_old_asset(
    tmp_path, monkeypatch
) -> None:
    runtime = _runtime(tmp_path)
    try:
        profile_id, record = _record(runtime)
        group_id = record["domains"][0]["groups"][0]["group_id"]
        session = runtime.session()
        try:
            old = listening_assets.import_group_photo(
                session,
                runtime,
                profile_id=profile_id,
                record_id=record["record_id"],
                domain="health",
                group_id=group_id,
                request_id=str(uuid.uuid4()),
                expected_revision=record["revision"],
                stream=io.BytesIO(_image()),
                display_name="old.png",
            )
            current = listening_service.read_record(
                session, profile_id=profile_id, record_id=record["record_id"]
            )

            def fail_move(*args, **kwargs):
                raise observation_assets.ObservationAssetStorage("injected move failure")

            monkeypatch.setattr(observation_assets, "_move_file", fail_move)
            with pytest.raises(listening_assets.ListeningAssetStorage):
                listening_assets.import_group_photo(
                    session,
                    runtime,
                    profile_id=profile_id,
                    record_id=record["record_id"],
                    domain="health",
                    group_id=group_id,
                    request_id=str(uuid.uuid4()),
                    expected_revision=current["revision"],
                    stream=io.BytesIO(_image((9, 9, 9))),
                    display_name="new.png",
                )
            after = listening_service.read_record(
                session, profile_id=profile_id, record_id=record["record_id"]
            )
            assert after["revision"] == current["revision"]
            assert after["domains"][0]["groups"][0]["asset_id"] == old["asset_id"]
            payload, _meta = listening_assets.read_asset(
                session,
                runtime,
                profile_id=profile_id,
                record_id=record["record_id"],
                asset_id=old["asset_id"],
            )
            assert payload == _image()
            assert backup_barrier.get_barrier(runtime.data_dir).active_counts == (0, 0)
        finally:
            session.close()
    finally:
        runtime.dispose()
