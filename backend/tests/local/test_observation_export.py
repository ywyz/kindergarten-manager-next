"""Observation export HTTP/service tests over a real loopback server.

Synthetic temporary database, synthetic JPEGs and the real local API guard
are used; no application AI call, real teacher data or real package is
touched.
"""

from __future__ import annotations

import hashlib
import http.client
import io
import json
import os
import subprocess
import unittest
import unittest.mock
import uuid
import zipfile
from datetime import datetime, timedelta

from PIL import Image
from sqlalchemy import select

from app.local import profile_service
from app.local import observation_export_service, observation_service
from app.local.models import (
    LocalObservationExportAttempt,
    LocalObservationExportSnapshot,
    LocalObservationExportToken,
    LocalObservationOperation,
    LocalProfile,
)
from app.local.normalize import normalize_initialization
from tests.local.support import LocalTestCase, initialize_body, query_scalar


class ObservationExportCase(LocalTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.runtime = self.make_runtime()
        self.session = self.runtime.session()
        profile_service.initialize(
            self.session, normalize_initialization(**initialize_body())
        )
        self.session.commit()
        self.profile = self.session.scalars(select(LocalProfile)).one()
        self.server = self.start_server(self.runtime)
        self.client = self.server.client()

    def tearDown(self) -> None:
        self.session.close()
        super().tearDown()

    # -- helpers -----------------------------------------------------------
    def jpeg(self, color=(200, 30, 30), size=(96, 72)) -> bytes:
        buffer = io.BytesIO()
        Image.new("RGB", size, color).save(buffer, "JPEG", quality=90)
        return buffer.getvalue()

    def raw(
        self, method, path, body=None, *, content_type=None, token=True, origin=True
    ):
        headers = {"Host": f"127.0.0.1:{self.server.port}"}
        if token:
            headers["X-App-Session"] = self.server.token
        if origin:
            headers["Origin"] = self.server.origin
        if content_type:
            headers["Content-Type"] = content_type
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.server.port, timeout=60
        )
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            raw = response.read()
            status = response.status
            out_headers = {
                key.lower(): value for key, value in response.getheaders()
            }
        finally:
            connection.close()
        try:
            return status, json.loads(raw.decode("utf-8")), out_headers
        except (UnicodeDecodeError, json.JSONDecodeError):
            return status, raw, out_headers

    def upload(self, observation_id, data: bytes, name="a.jpg"):
        current = self.client.get(f"/api/observations/{observation_id}")[1]
        boundary = "----kgm" + uuid.uuid4().hex
        body = bytearray()
        for key, value in {
            "request_id": str(uuid.uuid4()),
            "expected_revision": str(current["revision"]),
            "display_name": name,
        }.items():
            body += (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'
                f"{value}\r\n"
            ).encode("utf-8")
        body += (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="a.jpg"\r\n'
            "Content-Type: image/jpeg\r\n\r\n"
        ).encode("utf-8")
        body += data + b"\r\n"
        body += f"--{boundary}--\r\n".encode("utf-8")
        status, result, _headers = self.raw(
            "POST",
            f"/api/observations/{observation_id}/photos",
            bytes(body),
            content_type=f"multipart/form-data; boundary={boundary}",
        )
        self.assertEqual(status, 201, result)
        return result

    def create_record(
        self,
        *,
        record_type="public",
        date="2026-09-15",
        subjects=("小明",),
        body_text="幼儿在积木区合作搭建。",
        photos=0,
        full=True,
    ):
        payload = {
            "observation_date": date,
            "subjects": [{"name": name} for name in subjects],
            "age_years": 5,
            "environment": "积木区",
        }
        status, created = self.client.post(
            "/api/observations",
            {
                "request_id": str(uuid.uuid4()),
                "record_type": record_type,
                "payload": payload,
            },
        )
        self.assertEqual(status, 201, created)
        observation_id = created["observation_id"]
        asset_ids = []
        for index in range(photos):
            uploaded = self.upload(
                observation_id,
                self.jpeg((40 + index * 40, 30, 200 - index * 30)),
                name=f"{index}.jpg",
            )
            asset_ids.append(uploaded["asset_id"])
        save_payload = {
            "observation_date": date,
            "subjects": [{"name": name} for name in subjects],
            "age_years": 5,
            "environment": "积木区",
        }
        if full:
            save_payload.update(
                {
                    "start_time": "10:00",
                    "end_time": "10:20",
                    "adult_count": 2,
                    "child_count": 5,
                    "observation_goal": "观察合作",
                    "observation_process": body_text,
                    "analysis_evaluation": {
                        "health": "动作协调",
                        "language": "表达清楚",
                        "social": "合作",
                        "science": "尝试",
                        "arts": "表现",
                    },
                    "support_strategy": "提供更多材料",
                }
            )
        current = self.client.get(f"/api/observations/{observation_id}")[1]
        body = {
            "request_id": str(uuid.uuid4()),
            "expected_revision": current["revision"],
            "payload": save_payload,
            "save_reason": "manual",
        }
        if asset_ids:
            body["photos"] = [
                {"asset_id": asset_id, "caption": None} for asset_id in asset_ids
            ]
        status, saved = self.client.patch(
            f"/api/observations/{observation_id}", body
        )
        self.assertEqual(status, 200, saved)
        return observation_id, saved

    def preview(self, ids):
        return self.client.post(
            "/api/observation-exports/preview",
            {"request_id": str(uuid.uuid4()), "observation_ids": ids},
        )

    def create_export(self, snapshot_id, *, ack=True):
        return self.client.post(
            "/api/observation-exports",
            {
                "request_id": str(uuid.uuid4()),
                "snapshot_id": snapshot_id,
                "ack_missing": ack,
            },
        )

    def content(self, export_id):
        return self.raw("GET", f"/api/observation-exports/{export_id}/content")

    def start(self, export_id, filename):
        return self.client.post(
            f"/api/observation-exports/{export_id}/attempts",
            {"filename": filename},
        )

    def finish(self, export_id, attempt_id, status, *, size=None, digest=None):
        body = {"status": status}
        if size is not None:
            body["byte_size"] = size
        if digest is not None:
            body["result_hash"] = digest
        return self.client.post(
            f"/api/observation-exports/{export_id}/attempts/{attempt_id}/result",
            body,
        )

    # -- tests -------------------------------------------------------------
    def test_preview_requires_explicit_unique_ids(self):
        observation_id, _saved = self.create_record()
        status, result = self.preview([])
        self.assertEqual(status, 422, result)
        status, result = self.preview([observation_id, observation_id])
        self.assertEqual(status, 409, result)
        self.assertEqual(result["error"]["code"], "OBS_EXPORT_INVALID")
        status, result = self.preview([observation_id])
        self.assertEqual(status, 200, result)
        self.assertEqual(result["records"][0]["observation_id"], observation_id)
        self.assertTrue(result["snapshot_id"])
        self.assertEqual(result["records"][0]["photo_count"], 0)

    def test_missing_ack_and_create_content_attempt_lifecycle(self):
        observation_id, _saved = self.create_record(
            full=False, photos=2, body_text="只有观察记录正文"
        )
        status, preview = self.preview([observation_id])
        self.assertEqual(status, 200, preview)
        self.assertTrue(preview["requires_ack"])
        self.assertTrue(preview["missing"])
        status, blocked = self.create_export(preview["snapshot_id"], ack=False)
        self.assertEqual(status, 409, blocked)
        self.assertEqual(
            blocked["error"]["code"], "OBS_EXPORT_MISSING_UNCONFIRMED"
        )
        status, created = self.create_export(preview["snapshot_id"], ack=True)
        self.assertEqual(status, 201, created)
        export_id = created["export_id"]
        self.assertEqual(created["byte_size"] > 0, True)
        status, data, headers = self.content(export_id)
        self.assertEqual(status, 200)
        self.assertIsInstance(data, bytes)
        self.assertEqual(hashlib.sha256(data).hexdigest(), created["content_hash"])
        self.assertEqual(headers["x-content-sha256"], created["content_hash"])
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            document = archive.read("word/document.xml").decode("utf-8")
            media = [name for name in archive.namelist() if name.startswith("word/media/")]
        self.assertIn("游戏观察记录", document)
        self.assertEqual(len(media), 2)
        filename = created["filename"]
        status, attempt = self.start(export_id, filename)
        self.assertEqual(status, 200, attempt)
        self.assertTrue(attempt["should_prompt"])
        self.assertEqual(attempt["status"], "in_progress")
        # Same token + filename re-entry only reads the in-flight attempt.
        status, again = self.start(export_id, filename)
        self.assertEqual(status, 200, again)
        self.assertFalse(again["should_prompt"])
        self.assertEqual(again["attempt_id"], attempt["attempt_id"])
        self.assertEqual(again["status"], "in_progress")
        # A different filename fingerprint is refused.
        status, conflict = self.start(export_id, "另一个名字.docx")
        self.assertEqual(status, 409, conflict)
        self.assertEqual(conflict["error"]["code"], "OBS_EXPORT_ATTEMPT_CONFLICT")
        status, finished = self.finish(
            export_id,
            attempt["attempt_id"],
            "saved",
            size=len(data),
            digest=hashlib.sha256(data).hexdigest(),
        )
        self.assertEqual(status, 200, finished)
        self.assertEqual(finished["status"], "saved")
        # A repeated result report is idempotent.
        status, repeated = self.finish(
            export_id,
            attempt["attempt_id"],
            "saved",
            size=len(data),
            digest=hashlib.sha256(data).hexdigest(),
        )
        self.assertEqual(status, 200, repeated)
        # The one-time token no longer serves content.
        status, body, _headers = self.content(export_id)
        self.assertEqual(status, 409, body)
        self.assertEqual(body["error"]["code"], "OBS_EXPORT_TOKEN_INVALID")
        # Re-entry after terminal state reads the original result.
        status, terminal = self.start(export_id, filename)
        self.assertEqual(status, 200, terminal)
        self.assertFalse(terminal["should_prompt"])
        self.assertEqual(terminal["status"], "saved")

    def test_snapshot_becomes_stale_after_draft_change(self):
        observation_id, _saved = self.create_record()
        status, preview = self.preview([observation_id])
        self.assertEqual(status, 200, preview)
        status, current = self.client.get(f"/api/observations/{observation_id}")
        self.assertEqual(status, 200)
        changed_payload = {
            key: value
            for key, value in current["payload"].items()
            if key != "term_snapshot"
        }
        changed_payload["observation_process"] = "修改后的正文"
        status, saved = self.client.patch(
            f"/api/observations/{observation_id}",
            {
                "request_id": str(uuid.uuid4()),
                "expected_revision": current["revision"],
                "payload": changed_payload,
                "save_reason": "manual",
            },
        )
        self.assertEqual(status, 200, saved)
        status, stale = self.create_export(preview["snapshot_id"], ack=True)
        self.assertEqual(status, 409, stale)
        self.assertEqual(stale["error"]["code"], "OBS_EXPORT_SNAPSHOT_STALE")

    def test_empty_record_blocks_whole_selection(self):
        empty_id, _saved = self.create_record(full=False)
        full_id, _saved = self.create_record(body_text="有正文")
        status, blocked = self.preview([full_id, empty_id])
        self.assertEqual(status, 409, blocked)
        self.assertEqual(blocked["error"]["code"], "OBS_EXPORT_EMPTY")
        details = blocked["error"]["details"]
        self.assertEqual(details["observation_id"], empty_id)
        self.assertEqual(details["record_type"], "public")
        self.assertEqual(details["photo_count"], 0)
        self.assertNotIn("小明", json.dumps(details, ensure_ascii=False))
        self.assertNotIn(str(self.tmp_root), json.dumps(details, ensure_ascii=False))

    def test_bad_material_reports_safe_asset_and_record_ids(self):
        observation_id, _saved = self.create_record(photos=1)
        status, preview = self.preview([observation_id])
        self.assertEqual(status, 200, preview)
        from app.local.models import LocalObservationAssetDerivative

        derivative = self.session.scalars(
            select(LocalObservationAssetDerivative).where(
                LocalObservationAssetDerivative.observation_id == observation_id,
                LocalObservationAssetDerivative.purpose == "export",
            )
        ).first()
        self.assertIsNotNone(derivative)
        path = self.runtime.data_dir / derivative.relative_path
        path.unlink()
        status, blocked = self.preview([observation_id])
        self.assertEqual(status, 409, blocked)
        self.assertEqual(blocked["error"]["code"], "OBS_EXPORT_BAD_MATERIAL")
        details = blocked["error"]["details"]
        self.assertEqual(details["observation_id"], observation_id)
        self.assertEqual(details["asset_id"], derivative.asset_id)
        self.assertEqual(details["derivative_id"], derivative.id)
        self.assertEqual(details["sort_order"], 0)
        self.assertEqual(details["reason"], "read_failed")
        serialized = json.dumps(details, ensure_ascii=False)
        self.assertNotIn("小明", serialized)
        self.assertNotIn(str(self.tmp_root), serialized)

    def test_cross_scope_token_is_refused(self):
        observation_id, _saved = self.create_record()
        status, preview = self.preview([observation_id])
        self.assertEqual(status, 200, preview)
        status, created = self.create_export(preview["snapshot_id"], ack=True)
        self.assertEqual(status, 201, created)
        # A different app session scope (same launch token) must not read it.
        status, body, _headers = self.raw(
            "GET",
            f"/api/observation-exports/{created['export_id']}/content",
            token=self.server.token,
        )
        self.assertEqual(status, 200)
        # A different launch id is represented by a second app instance.
        other_runtime = self.make_runtime(data_dir=self.tmp_root / "other")
        other = self.start_server(other_runtime)
        other_client = other.client()
        status, _ = other_client.get(
            f"/api/observation-exports/{created['export_id']}/content"
        )
        self.assertIn(status, (401, 409))
        # The real app's content remains readable before the attempt.
        status, _body, _headers = self.content(created["export_id"])
        self.assertEqual(status, 200)

    # -- R02: write-lock binding recheck and explicit fixed-snapshot retry --
    def _scope(self):
        return (
            str(getattr(self.runtime, "launch_id", "") or ""),
            str(self.server.app.state.session_scope),
        )

    def _direct_create(
        self, snapshot_id, *, retry_existing=False, ack=True, before_lock=None
    ):
        launch_id, session_scope = self._scope()
        return observation_export_service.create_export(
            self.session,
            self.runtime,
            profile_id=self.profile.id,
            request_id=str(uuid.uuid4()),
            snapshot_id=snapshot_id,
            ack_missing=ack,
            retry_existing=retry_existing,
            launch_id=launch_id,
            session_scope=session_scope,
            _before_lock=before_lock,
        )

    def test_write_lock_recheck_rejects_concurrent_change(self):
        observation_id, saved = self.create_record(body_text="原始正文")
        status, preview = self.preview([observation_id])
        self.assertEqual(status, 200, preview)
        snapshot_id = preview["snapshot_id"]

        def concurrent_save():
            current = observation_service.read_current(
                self.session,
                profile_id=self.profile.id,
                observation_id=observation_id,
            )
            payload = {
                key: value
                for key, value in current["payload"].items()
                if key != "term_snapshot"
            }
            payload["observation_process"] = "并发修改后的正文"
            observation_service.save_observation(
                self.session,
                profile_id=self.profile.id,
                observation_id=observation_id,
                request_id=str(uuid.uuid4()),
                expected_revision=current["revision"],
                payload=payload,
                photos=None,
                save_reason="manual",
            )

        with self.assertRaises(observation_export_service.ObservationExportSnapshotStale):
            self._direct_create(snapshot_id, before_lock=concurrent_save)
        # No token/attempt survived the refused write.
        self.assertEqual(
            query_scalar(
                self.runtime.db_path,
                "SELECT count(*) AS n FROM local_observation_export_tokens "
                "WHERE snapshot_id = ?",
                (snapshot_id,),
            ),
            0,
        )
        self.assertEqual(
            query_scalar(
                self.runtime.db_path,
                "SELECT count(*) AS n FROM local_observation_export_attempts "
                "WHERE snapshot_id = ?",
                (snapshot_id,),
            ),
            0,
        )
        temp_root = self.runtime.data_dir / observation_export_service.EXPORT_TEMP_ROOT
        self.assertEqual(
            [p.name for p in temp_root.glob("*") if p.is_file()] if temp_root.exists() else [],
            [],
        )
        # A fresh create for the old snapshot is refused after the change.
        with self.assertRaises(observation_export_service.ObservationExportSnapshotStale):
            self._direct_create(snapshot_id)

    def test_retry_existing_uses_frozen_snapshot_without_current_recheck(self):
        observation_id, _saved = self.create_record(body_text="冻结正文")
        status, preview = self.preview([observation_id])
        self.assertEqual(status, 200, preview)
        snapshot_id = preview["snapshot_id"]
        first = self._direct_create(snapshot_id)
        status, attempt = self.start(first["export_id"], first["filename"])
        self.assertEqual(status, 200, attempt)
        status, finished = self.finish(
            first["export_id"], attempt["attempt_id"], "cancelled"
        )
        self.assertEqual(status, 200, finished)
        # Change the current draft after the fixed snapshot was confirmed.
        current = observation_service.read_current(
            self.session,
            profile_id=self.profile.id,
            observation_id=observation_id,
        )
        payload = {
            key: value
            for key, value in current["payload"].items()
            if key != "term_snapshot"
        }
        payload["observation_process"] = "修改后的正文"
        observation_service.save_observation(
            self.session,
            profile_id=self.profile.id,
            observation_id=observation_id,
            request_id=str(uuid.uuid4()),
            expected_revision=current["revision"],
            payload=payload,
            photos=None,
            save_reason="manual",
        )
        # A fresh export of this snapshot must recheck and refuse.
        with self.assertRaises(observation_export_service.ObservationExportSnapshotStale):
            self._direct_create(snapshot_id)
        # The explicit fixed-snapshot retry creates a new token and keeps the
        # frozen content (not the modified current draft).
        second = self._direct_create(snapshot_id, retry_existing=True)
        self.assertNotEqual(second["export_id"], first["export_id"])
        self.assertEqual(second["content_hash"], first["content_hash"])
        status, data, _headers = self.content(second["export_id"])
        self.assertEqual(status, 200)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            document = archive.read("word/document.xml").decode("utf-8")
        self.assertIn("冻结正文", document)
        self.assertNotIn("修改后的正文", document)

    # -- R03: managed artifact, refcount, missing/expired/oversize ----------
    def _artifact_paths(self, export_id):
        token_hash = hashlib.sha256(export_id.encode("utf-8")).hexdigest()
        root = self.runtime.data_dir / observation_export_service.EXPORT_TEMP_ROOT
        return root / f"{token_hash}.docx", root / f"{token_hash}.json"

    def test_managed_artifact_refcount_protects_inflight_stream(self):
        observation_id, _saved = self.create_record(photos=1)
        status, preview = self.preview([observation_id])
        self.assertEqual(status, 200, preview)
        created = self._direct_create(preview["snapshot_id"])
        docx_path, meta_path = self._artifact_paths(created["export_id"])
        self.assertTrue(docx_path.is_file())
        self.assertTrue(meta_path.is_file())
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        self.assertEqual(meta["content_hash"], created["content_hash"])
        self.assertEqual(meta["byte_size"], created["byte_size"])
        status, attempt = self.start(created["export_id"], created["filename"])
        self.assertEqual(status, 200, attempt)
        launch_id, session_scope = self._scope()
        artifact = observation_export_service.read_export_content(
            self.session,
            self.runtime,
            profile_id=self.profile.id,
            export_id=created["export_id"],
            launch_id=launch_id,
            session_scope=session_scope,
        )
        try:
            body = artifact.handle.read()
            self.assertEqual(hashlib.sha256(body).hexdigest(), created["content_hash"])
            status, finished = self.finish(
                created["export_id"],
                attempt["attempt_id"],
                "saved",
                size=len(body),
                digest=created["content_hash"],
            )
            self.assertEqual(status, 200, finished)
            # The terminal receipt committed, but the open stream keeps the
            # managed file alive.
            self.assertTrue(docx_path.is_file())
            self.assertTrue(meta_path.is_file())
        finally:
            observation_export_service.release_artifact(self.runtime, artifact)
        self.assertFalse(docx_path.exists())
        self.assertFalse(meta_path.exists())

    def test_missing_or_tampered_artifact_is_not_silently_regenerated(self):
        observation_id, _saved = self.create_record()
        status, preview = self.preview([observation_id])
        self.assertEqual(status, 200, preview)
        created = self._direct_create(preview["snapshot_id"])
        docx_path, meta_path = self._artifact_paths(created["export_id"])
        docx_path.unlink()
        status, body, _headers = self.content(created["export_id"])
        self.assertEqual(status, 409, body)
        self.assertEqual(body["error"]["code"], "OBS_EXPORT_ARTIFACT_MISSING")
        # A new explicit token from the still-valid fixed snapshot works.
        retry = self._direct_create(
            preview["snapshot_id"], retry_existing=True
        )
        status, data, _headers = self.content(retry["export_id"])
        self.assertEqual(status, 200)
        self.assertEqual(hashlib.sha256(data).hexdigest(), retry["content_hash"])

    def test_tampered_artifact_and_oversize_are_refused(self):
        observation_id, _saved = self.create_record()
        status, preview = self.preview([observation_id])
        self.assertEqual(status, 200, preview)
        created = self._direct_create(preview["snapshot_id"])
        docx_path, _meta_path = self._artifact_paths(created["export_id"])
        data = docx_path.read_bytes()
        docx_path.write_bytes(data[:-10])
        status, body, _headers = self.content(created["export_id"])
        self.assertEqual(status, 409, body)
        self.assertEqual(body["error"]["code"], "OBS_EXPORT_ARTIFACT_MISMATCH")
        with unittest.mock.patch.object(
            observation_export_service, "MAX_EXPORT_DOCX_BYTES", 100
        ):
            with self.assertRaises(observation_export_service.ObservationExportTooLarge):
                self._direct_create(preview["snapshot_id"])

    def test_expired_token_and_artifact_cleanup(self):
        observation_id, _saved = self.create_record()
        status, preview = self.preview([observation_id])
        self.assertEqual(status, 200, preview)
        created = self._direct_create(preview["snapshot_id"])
        docx_path, meta_path = self._artifact_paths(created["export_id"])
        # Expire the token row and the managed sidecar, then verify content is
        # refused and cleanup removes the artifact.
        import sqlite3

        connection = sqlite3.connect(str(self.runtime.db_path))
        try:
            connection.execute(
                "UPDATE local_observation_export_tokens SET expires_at = ? "
                "WHERE token_hash = ?",
                ("2000-01-01 00:00:00.000000", hashlib.sha256(created["export_id"].encode()).hexdigest()),
            )
            connection.commit()
        finally:
            connection.close()
        status, body, _headers = self.content(created["export_id"])
        self.assertEqual(status, 409, body)
        self.assertEqual(body["error"]["code"], "OBS_EXPORT_TOKEN_INVALID")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["expires_at"] = "2000-01-01T00:00:00"
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
        observation_export_service._cleanup_expired_artifacts(
            self.runtime, observation_export_service.utc_now()
        )
        self.assertFalse(docx_path.exists())
        self.assertFalse(meta_path.exists())

    # -- R04: no business count quota; byte/aggregate technical bounds ------
    def test_more_than_31_selected_records_are_not_truncated(self):
        ids = []
        for index in range(32):
            observation_id, _saved = self.create_record(
                date="2026-09-15",
                subjects=(f"幼儿{index}",),
                body_text=f"第 {index} 份正文",
            )
            ids.append(observation_id)
        status, preview = self.preview(ids)
        self.assertEqual(status, 200, preview)
        self.assertEqual(len(preview["records"]), 32)
        self.assertEqual(
            [record["observation_id"] for record in preview["records"]], ids
        )

    def test_schema_and_service_do_not_impose_a_500_id_count_limit(self):
        from app.local.schemas import LocalObservationExportPreviewIn

        model = LocalObservationExportPreviewIn(
            request_id=str(uuid.uuid4()),
            observation_ids=[f"obs-{index:04d}" for index in range(501)],
        )
        self.assertEqual(len(model.observation_ids), 501)
        launch_id, session_scope = self._scope()
        fake_ids = [f"{index:032d}" for index in range(501)]
        with self.assertRaises(observation_service.ObservationNotFound):
            observation_export_service.preview_export(
                self.session,
                self.runtime,
                profile_id=self.profile.id,
                request_id=str(uuid.uuid4()),
                observation_ids=fake_ids,
                launch_id=launch_id,
                session_scope=session_scope,
            )

    def test_selection_bound_is_serialized_bytes_not_a_record_count(self):
        launch_id, session_scope = self._scope()
        many_ids = [f"{index:032d}" for index in range(70000)]
        with self.assertRaises(observation_export_service.ObservationExportSelectionTooLarge) as caught:
            observation_export_service.preview_export(
                self.session,
                self.runtime,
                profile_id=self.profile.id,
                request_id=str(uuid.uuid4()),
                observation_ids=many_ids,
                launch_id=launch_id,
                session_scope=session_scope,
            )
        self.assertGreater(
            caught.exception.details["actual_bytes"],
            observation_export_service.MAX_EXPORT_SELECTION_BYTES,
        )

    def test_aggregate_text_and_photo_limits_are_enforced_before_generation(self):
        # Aggregate pixels are diagnostic only: serial decode does not hold
        # all decoded images, so a 100M-pixel multi-record set is not refused.
        observation_export_service.check_export_content_limits(
            {
                "total_photo_bytes": 1024,
                "total_payload_bytes": 1024,
                "total_pixels": 500_000_000,
            }
        )
        with self.assertRaises(observation_export_service.ObservationExportContentTooLarge):
            observation_export_service.check_export_content_limits(
                {
                    "total_photo_bytes": observation_export_service.MAX_EXPORT_TOTAL_PHOTO_BYTES + 1,
                    "total_payload_bytes": 0,
                    "total_pixels": 1,
                }
            )
        text_id, _saved = self.create_record(body_text="长" * 300)
        launch_id, session_scope = self._scope()
        with unittest.mock.patch.object(
            observation_export_service, "MAX_EXPORT_TOTAL_PAYLOAD_BYTES", 100
        ):
            with self.assertRaises(observation_export_service.ObservationExportContentTooLarge) as caught:
                observation_export_service.preview_export(
                    self.session,
                    self.runtime,
                    profile_id=self.profile.id,
                    request_id=str(uuid.uuid4()),
                    observation_ids=[text_id],
                    launch_id=launch_id,
                    session_scope=session_scope,
                )
            self.assertEqual(caught.exception.details["kind"], "text")
        photo_id, _saved = self.create_record(photos=1)
        with unittest.mock.patch.object(
            observation_export_service, "MAX_EXPORT_TOTAL_PHOTO_BYTES", 100
        ):
            with self.assertRaises(observation_export_service.ObservationExportContentTooLarge) as caught:
                observation_export_service.preview_export(
                    self.session,
                    self.runtime,
                    profile_id=self.profile.id,
                    request_id=str(uuid.uuid4()),
                    observation_ids=[photo_id],
                    launch_id=launch_id,
                    session_scope=scope if False else session_scope,
                )
            self.assertEqual(caught.exception.details["kind"], "photo_bytes")

    # -- R07: managed metadata/DOCX hardlinks and junction swaps ------------
    def test_metadata_hardlink_is_refused_and_not_cleaned(self):
        observation_id, _saved = self.create_record()
        status, preview = self.preview([observation_id])
        self.assertEqual(status, 200, preview)
        created = self._direct_create(preview["snapshot_id"])
        docx_path, meta_path = self._artifact_paths(created["export_id"])
        outside = self.tmp_root / "outside-meta.json"
        os.link(meta_path, outside)
        try:
            status, body, _headers = self.content(created["export_id"])
            self.assertEqual(status, 503, body)
            self.assertEqual(body["error"]["code"], "OBS_EXPORT_STORAGE")
            # The outside hardlink target is untouched and never parsed.
            outside.write_text('{"version":1,"token_hash":"stolen"}', encoding="utf-8")
            status, body, _headers = self.content(created["export_id"])
            self.assertEqual(status, 503, body)
            self.assertTrue(outside.is_file())
        finally:
            try:
                outside.unlink()
            except OSError:
                pass

    def test_docx_hardlink_is_refused_and_not_cleaned(self):
        observation_id, _saved = self.create_record()
        status, preview = self.preview([observation_id])
        self.assertEqual(status, 200, preview)
        created = self._direct_create(preview["snapshot_id"])
        docx_path, _meta_path = self._artifact_paths(created["export_id"])
        outside = self.tmp_root / "outside.docx"
        os.link(docx_path, outside)
        original = outside.read_bytes()
        try:
            status, body, _headers = self.content(created["export_id"])
            self.assertEqual(status, 503, body)
            self.assertEqual(body["error"]["code"], "OBS_EXPORT_STORAGE")
            self.assertEqual(outside.read_bytes(), original)
        finally:
            try:
                outside.unlink()
            except OSError:
                pass

    @unittest.skipUnless(os.name == "nt", "Windows junction test")
    def test_junction_swap_is_refused_and_outside_files_survive(self):
        observation_id, _saved = self.create_record()
        status, preview = self.preview([observation_id])
        self.assertEqual(status, 200, preview)
        created = self._direct_create(preview["snapshot_id"])
        docx_path, meta_path = self._artifact_paths(created["export_id"])
        root = self.runtime.data_dir / observation_export_service.EXPORT_TEMP_ROOT
        outside = self.tmp_root / "outside-export-temp"
        outside.mkdir()
        (outside / docx_path.name).write_bytes(docx_path.read_bytes())
        (outside / meta_path.name).write_bytes(meta_path.read_bytes())
        backup = self.runtime.data_dir / "export-temp-backup"
        os.rename(root, backup)
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(root), str(outside)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            os.rename(backup, root)
            self.skipTest("junction creation unavailable")
        try:
            status, body, _headers = self.content(created["export_id"])
            self.assertIn(status, (409, 503))
            self.assertTrue((outside / docx_path.name).is_file())
            self.assertTrue((outside / meta_path.name).is_file())
        finally:
            try:
                os.rmdir(root)
            except OSError:
                pass
            os.rename(backup, root)

    # -- R07: expired snapshot manifest release ----------------------------
    def _expire_snapshot(self, snapshot_id):
        import sqlite3

        connection = sqlite3.connect(str(self.runtime.db_path))
        try:
            connection.execute(
                "UPDATE local_observation_export_snapshots SET expires_at = ? "
                "WHERE id = ?",
                ("2000-01-01 00:00:00.000000", snapshot_id),
            )
            connection.commit()
        finally:
            connection.close()

    def _snapshot_row(self, snapshot_id):
        from app.local.models import LocalObservationExportSnapshot

        self.session.expire_all()
        return self.session.get(LocalObservationExportSnapshot, snapshot_id)

    def test_expired_snapshot_without_attempt_is_deleted(self):
        observation_id, _saved = self.create_record()
        status, preview = self.preview([observation_id])
        self.assertEqual(status, 200, preview)
        snapshot_id = preview["snapshot_id"]
        self._expire_snapshot(snapshot_id)
        released = observation_export_service._cleanup_expired_snapshots(
            self.session, self.runtime, observation_export_service.utc_now()
        )
        self.assertGreaterEqual(released, 1)
        self.assertIsNone(self._snapshot_row(snapshot_id))
        self.assertEqual(
            query_scalar(
                self.runtime.db_path,
                "SELECT count(*) AS n FROM local_observation_export_tokens "
                "WHERE snapshot_id = ?",
                (snapshot_id,),
            ),
            0,
        )

    def test_expired_snapshot_with_terminal_attempt_keeps_receipt_anchor(self):
        observation_id, _saved = self.create_record()
        status, preview = self.preview([observation_id])
        self.assertEqual(status, 200, preview)
        snapshot_id = preview["snapshot_id"]
        created = self._direct_create(snapshot_id)
        status, attempt = self.start(created["export_id"], created["filename"])
        self.assertEqual(status, 200, attempt)
        status, _finished = self.finish(
            created["export_id"], attempt["attempt_id"], "cancelled"
        )
        self.assertEqual(status, 200)
        self._expire_snapshot(snapshot_id)
        released = observation_export_service._cleanup_expired_snapshots(
            self.session, self.runtime, observation_export_service.utc_now()
        )
        self.assertGreaterEqual(released, 1)
        row = self._snapshot_row(snapshot_id)
        self.assertIsNotNone(row)
        self.assertTrue(row.manifest_json.get("released"))
        self.assertNotIn("records", row.manifest_json)
        self.assertNotIn("payload", row.manifest_json)
        # Attempt and token anchors remain queryable.
        status, receipt = self.client.get(
            f"/api/observation-exports/{created['export_id']}/attempts/latest"
        )
        self.assertEqual(status, 200, receipt)
        self.assertEqual(receipt["attempt_id"], attempt["attempt_id"])
        self.assertEqual(receipt["status"], "cancelled")

    def test_in_progress_attempt_blocks_snapshot_release(self):
        observation_id, _saved = self.create_record()
        status, preview = self.preview([observation_id])
        self.assertEqual(status, 200, preview)
        snapshot_id = preview["snapshot_id"]
        created = self._direct_create(snapshot_id)
        status, attempt = self.start(created["export_id"], created["filename"])
        self.assertEqual(status, 200, attempt)
        self._expire_snapshot(snapshot_id)
        launch_id, session_scope = self._scope()
        observation_export_service._cleanup_expired_snapshots(
            self.session,
            self.runtime,
            observation_export_service.utc_now(),
            current_launch_id=launch_id,
            current_session_scope=session_scope,
        )
        row = self._snapshot_row(snapshot_id)
        self.assertIsNotNone(row)
        self.assertIn("records", row.manifest_json)
        status, _finished = self.finish(
            created["export_id"], attempt["attempt_id"], "cancelled"
        )
        self.assertEqual(status, 200)
        observation_export_service._cleanup_expired_snapshots(
            self.session,
            self.runtime,
            observation_export_service.utc_now(),
            current_launch_id=launch_id,
            current_session_scope=session_scope,
        )
        row = self._snapshot_row(snapshot_id)
        self.assertTrue(row.manifest_json.get("released"))
        self.assertNotIn("records", row.manifest_json)

    def test_terminal_attempt_report_is_idempotent_for_each_status(self):
        observation_id, _saved = self.create_record()
        status, preview = self.preview([observation_id])
        self.assertEqual(status, 200, preview)
        created = self._direct_create(preview["snapshot_id"])
        status, attempt = self.start(created["export_id"], created["filename"])
        self.assertEqual(status, 200, attempt)
        status, first = self.finish(
            created["export_id"], attempt["attempt_id"], "failed"
        )
        self.assertEqual(status, 200, first)
        self.assertEqual(first["status"], "failed")
        status, second = self.finish(
            created["export_id"], attempt["attempt_id"], "failed"
        )
        self.assertEqual(status, 200, second)
        self.assertEqual(second["status"], "failed")
        status, conflict = self.finish(
            created["export_id"], attempt["attempt_id"], "cancelled"
        )
        self.assertEqual(status, 409, conflict)
        self.assertEqual(conflict["error"]["code"], "OBS_EXPORT_ATTEMPT_STATE")

    # -- R12: artifact must stay bound to the fixed create receipt ----------
    def test_artifact_rebinding_is_refused(self):
        observation_id, _saved = self.create_record()
        status, preview = self.preview([observation_id])
        self.assertEqual(status, 200, preview)
        created = self._direct_create(preview["snapshot_id"])
        docx_path, meta_path = self._artifact_paths(created["export_id"])
        original = docx_path.read_bytes()
        replacement = original + b"rebound"
        new_hash = hashlib.sha256(replacement).hexdigest()
        docx_path.write_bytes(replacement)
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["content_hash"] = new_hash
        meta["byte_size"] = len(replacement)
        meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        status, body, _headers = self.content(created["export_id"])
        self.assertEqual(status, 409, body)
        self.assertEqual(body["error"]["code"], "OBS_EXPORT_ARTIFACT_MISMATCH")
        # The original receipt hash is still the authority, not the sidecar.
        self.assertNotEqual(new_hash, created["content_hash"])

    def test_active_token_receipt_survives_more_than_200_later_creates(self):
        observation_id, _saved = self.create_record()
        status, preview = self.preview([observation_id])
        self.assertEqual(status, 200, preview)
        created = self._direct_create(preview["snapshot_id"])
        # Insert 205 later create operations. The exact export-id JSON lookup
        # must still find the old token's receipt, not lose it to a scan cap.
        for index in range(205):
            self.session.add(
                LocalObservationOperation(
                    id=uuid.uuid4().hex,
                    profile_id=self.profile.id,
                    request_id=str(uuid.uuid4()),
                    operation_kind="observation_export_create",
                    observation_id=None,
                    request_fingerprint="a" * 64,
                    status="committed",
                    result_json={
                        "export_id": f"synthetic-later-{index}",
                        "snapshot_id": "other-snapshot",
                        "manifest_hash": "b" * 64,
                        "content_hash": "c" * 64,
                        "byte_size": 1,
                    },
                )
            )
        self.session.commit()
        status, data, _headers = self.content(created["export_id"])
        self.assertEqual(status, 200)
        self.assertEqual(hashlib.sha256(data).hexdigest(), created["content_hash"])

    def test_sidecar_snapshot_rebinding_is_refused(self):
        observation_id, _saved = self.create_record()
        status, preview = self.preview([observation_id])
        self.assertEqual(status, 200, preview)
        created = self._direct_create(preview["snapshot_id"])
        _docx_path, meta_path = self._artifact_paths(created["export_id"])
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["snapshot_id"] = "another-snapshot"
        meta["manifest_hash"] = "f" * 64
        meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        status, body, _headers = self.content(created["export_id"])
        self.assertEqual(status, 409, body)
        self.assertEqual(body["error"]["code"], "OBS_EXPORT_ARTIFACT_MISMATCH")

    def test_reopened_session_reads_the_original_artifact(self):
        observation_id, _saved = self.create_record()
        status, preview = self.preview([observation_id])
        self.assertEqual(status, 200, preview)
        created = self._direct_create(preview["snapshot_id"])
        launch_id, session_scope = self._scope()
        other = self.runtime.session()
        try:
            artifact = observation_export_service.read_export_content(
                other,
                self.runtime,
                profile_id=self.profile.id,
                export_id=created["export_id"],
                launch_id=launch_id,
                session_scope=session_scope,
            )
            try:
                data = artifact.handle.read()
            finally:
                observation_export_service.release_artifact(self.runtime, artifact)
        finally:
            other.close()
        self.assertEqual(hashlib.sha256(data).hexdigest(), created["content_hash"])
        self.assertEqual(len(data), created["byte_size"])

    # -- R11: idempotent/bounded snapshot cleanup --------------------------
    def test_repeated_expired_cleanup_is_idempotent(self):
        observation_id, _saved = self.create_record()
        status, preview = self.preview([observation_id])
        self.assertEqual(status, 200, preview)
        snapshot_id = preview["snapshot_id"]
        created = self._direct_create(snapshot_id)
        status, attempt = self.start(created["export_id"], created["filename"])
        self.assertEqual(status, 200, attempt)
        status, _finished = self.finish(
            created["export_id"], attempt["attempt_id"], "cancelled"
        )
        self.assertEqual(status, 200)
        self._expire_snapshot(snapshot_id)
        launch_id, session_scope = self._scope()
        first = observation_export_service._cleanup_expired_snapshots(
            self.session,
            self.runtime,
            observation_export_service.utc_now(),
            current_launch_id=launch_id,
            current_session_scope=session_scope,
        )
        self.assertGreaterEqual(first, 1)
        row = self._snapshot_row(snapshot_id)
        released_hash = row.manifest_hash
        audit_before = query_scalar(
            self.runtime.db_path,
            "SELECT count(*) AS n FROM local_operation_records "
            "WHERE action = 'observation_export_snapshot_released'",
        )
        second = observation_export_service._cleanup_expired_snapshots(
            self.session,
            self.runtime,
            observation_export_service.utc_now(),
            current_launch_id=launch_id,
            current_session_scope=session_scope,
        )
        self.assertEqual(second, 0)
        row = self._snapshot_row(snapshot_id)
        self.assertEqual(row.manifest_hash, released_hash)
        self.assertEqual(
            query_scalar(
                self.runtime.db_path,
                "SELECT count(*) AS n FROM local_operation_records "
                "WHERE action = 'observation_export_snapshot_released'",
            ),
            audit_before,
        )

    def test_more_than_200_expired_snapshots_are_all_released(self):
        expired = datetime.now() - timedelta(days=1)
        self.session.add_all(
            [
                LocalObservationExportSnapshot(
                    id=f"cleanup{index:025d}",
                    profile_id=self.profile.id,
                    launch_id="",
                    session_scope_hash=hashlib.sha256(b"").hexdigest(),
                    manifest_json={"version": 1, "records": []},
                    manifest_hash="a" * 64,
                    created_at=expired,
                    expires_at=expired,
                )
                for index in range(205)
            ]
        )
        self.session.commit()
        released = observation_export_service._cleanup_expired_snapshots(
            self.session, self.runtime, observation_export_service.utc_now()
        )
        self.assertGreaterEqual(released, 205)
        self.assertEqual(
            query_scalar(
                self.runtime.db_path,
                "SELECT count(*) AS n FROM local_observation_export_snapshots "
                "WHERE id LIKE 'cleanup%'",
            ),
            0,
        )

    def test_ended_launch_in_progress_attempt_becomes_indeterminate(self):
        observation_id, _saved = self.create_record()
        status, preview = self.preview([observation_id])
        self.assertEqual(status, 200, preview)
        snapshot_id = preview["snapshot_id"]
        created = self._direct_create(snapshot_id)
        status, attempt = self.start(created["export_id"], created["filename"])
        self.assertEqual(status, 200, attempt)
        docx_path, _meta_path = self._artifact_paths(created["export_id"])
        self.assertTrue(docx_path.is_file())
        import sqlite3

        connection = sqlite3.connect(str(self.runtime.db_path))
        try:
            connection.execute(
                "UPDATE local_observation_export_snapshots "
                "SET launch_id = ?, session_scope_hash = ?, expires_at = ? "
                "WHERE id = ?",
                (
                    "ended-launch",
                    hashlib.sha256(b"ended-scope").hexdigest(),
                    "2000-01-01 00:00:00.000000",
                    snapshot_id,
                ),
            )
            connection.commit()
        finally:
            connection.close()
        released = observation_export_service._cleanup_expired_snapshots(
            self.session,
            self.runtime,
            observation_export_service.utc_now(),
            current_launch_id="new-launch",
            current_session_scope="new-scope",
        )
        self.assertGreaterEqual(released, 1)
        attempt_row = self.session.get(
            LocalObservationExportAttempt, attempt["attempt_id"]
        )
        self.assertIsNotNone(attempt_row)
        self.assertEqual(attempt_row.status, "indeterminate")
        token_row = self.session.scalars(
            select(LocalObservationExportToken).where(
                LocalObservationExportToken.snapshot_id == snapshot_id
            )
        ).first()
        self.assertIsNotNone(token_row)
        self.assertIsNotNone(token_row.consumed_at)
        self.assertFalse(docx_path.exists())

    # -- R09: explicit pre-export save for list selection -------------------
    def _auto_change(self, observation_id, text):
        current = observation_service.read_current(
            self.session, profile_id=self.profile.id, observation_id=observation_id
        )
        payload = {
            key: value
            for key, value in current["payload"].items()
            if key != "term_snapshot"
        }
        payload["observation_process"] = text
        observation_service.save_observation(
            self.session,
            profile_id=self.profile.id,
            observation_id=observation_id,
            request_id=str(uuid.uuid4()),
            expected_revision=current["revision"],
            payload=payload,
            photos=None,
            save_reason="auto",
        )

    def test_prepare_saves_pre_export_history_without_creating_snapshot(self):
        first_id, _saved = self.create_record(body_text="第一份")
        second_id, _saved = self.create_record(body_text="第二份")
        # Both records now have an auto-saved aggregate that differs from the
        # latest retained node; prepare must create the missing nodes.
        self._auto_change(first_id, "自动保存后的第一份")
        self._auto_change(second_id, "自动保存后的第二份")
        before_snapshots = query_scalar(
            self.runtime.db_path,
            "SELECT count(*) AS n FROM local_observation_export_snapshots",
        )
        launch_id, session_scope = self._scope()
        prepare_request_id = str(uuid.uuid4())
        prepared = observation_export_service.prepare_export(
            self.session,
            profile_id=self.profile.id,
            request_id=prepare_request_id,
            observation_ids=[second_id, first_id],
            launch_id=launch_id,
            session_scope=session_scope,
        )
        self.assertEqual(
            [record["observation_id"] for record in prepared["records"]],
            [second_id, first_id],
        )
        self.assertTrue(all(record["history_created"] for record in prepared["records"]))
        self.assertEqual(
            query_scalar(
                self.runtime.db_path,
                "SELECT count(*) AS n FROM local_observation_export_snapshots",
            ),
            before_snapshots,
        )
        for observation_id in (first_id, second_id):
            self.assertEqual(
                query_scalar(
                    self.runtime.db_path,
                    "SELECT count(*) AS n FROM local_observation_versions "
                    "WHERE observation_id = ?",
                    (observation_id,),
                ),
                2,
            )
        # A repeated prepare with the same request id replays its receipt and
        # does not create another history node.
        prepared_again = observation_export_service.prepare_export(
            self.session,
            profile_id=self.profile.id,
            request_id=prepare_request_id,
            observation_ids=[second_id, first_id],
            launch_id=launch_id,
            session_scope=session_scope,
        )
        self.assertEqual(prepared_again["records"], prepared["records"])


if __name__ == "__main__":
    unittest.main()
