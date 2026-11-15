"""Listening AI HTTP candidate binding and read-only adoption receipt."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime

from app.local import (
    ai_config_service,
    ai_task_service,
    listening_ai_service,
    listening_service,
    profile_service,
)
from tests.local.listening_fixture_support import jpeg_bytes, post_multipart
from tests.local.support import LocalTestCase


class ListeningAIApiTests(LocalTestCase):
    def _setup_candidate(self, client, runtime):
        status, context = client.get("/api/local/context")
        self.assertEqual(status, 200, context)
        profile_id = context["profile"]["id"]
        term_id = context["terms"][0]["id"]
        status, record = client.post(
            "/api/listening/records",
            {
                "request_id": str(uuid.uuid4()),
                "term_id": term_id,
                "child_name": "甲",
            },
        )
        self.assertEqual(status, 201, record)
        record_id = record["record_id"]
        status, dto = client.get(f"/api/listening/records/{record_id}")
        self.assertEqual(status, 200, dto)
        group_id = dto["domains"][0]["groups"][0]["group_id"]
        status, saved = client.patch(
            f"/api/listening/records/{record_id}/domains/health",
            {
                "request_id": str(uuid.uuid4()),
                "expected_revision": 1,
                "goal": "观察目标",
                "groups": [
                    {"group_id": group_id, "listening_text": "孩子说想画太阳。"}
                ],
            },
        )
        self.assertEqual(status, 200, saved)
        session = runtime.session()
        try:
            ai_config_service.patch_config(
                session,
                expected_ai_config_version=0,
                base_url="https://api.deepseek.com/v1",
                model="deepseek-v4-flash-vision-exp",
                secret="synthetic-secret",
                secret_provided=True,
                request_id=str(uuid.uuid4()),
                credential_root=runtime.credential_root,
            )
            session.commit()
            created, _ = listening_ai_service.create_task(
                session,
                runtime=runtime,
                profile_id=profile_id,
                record_id=record_id,
                domain="health",
                group_id=group_id,
                task_type="listening_note_draft",
                expected_revision=saved["revision"],
                request_id=str(uuid.uuid4()),
            )
        finally:
            session.close()
        claim = ai_task_service.claim_next(
            runtime, now=datetime.now(), started_ticks=0
        )
        self.assertIsNotNone(claim)
        session = runtime.session()
        try:
            self.assertTrue(
                ai_task_service.commit_dispatch_mark(session, claim, datetime.now())
            )
        finally:
            session.close()
        session = runtime.session()
        try:
            self.assertTrue(
                ai_task_service.finalize_success(
                    session,
                    claim,
                    {
                        "kind": "success",
                        "candidate_text": json.dumps(
                            {
                                "text": "孩子指着太阳说想画下来。",
                                "uncertainties": ["需核实"],
                            },
                            ensure_ascii=False,
                        ),
                    },
                    datetime.now(),
                )
            )
            candidate = listening_ai_service.get_candidate(
                session,
                profile_id=profile_id,
                record_id=record_id,
                task_id=created["task_id"],
            )
        finally:
            session.close()
        return record_id, candidate["candidate_id"]

    def _setup_group_candidate(self, client, runtime):
        status, context = client.get("/api/local/context")
        self.assertEqual(status, 200, context)
        profile_id = context["profile"]["id"]
        term_id = context["terms"][0]["id"]
        status, record = client.post(
            "/api/listening/records",
            {
                "request_id": str(uuid.uuid4()),
                "term_id": term_id,
                "child_name": "甲",
            },
        )
        self.assertEqual(status, 201, record)
        record_id = record["record_id"]
        status, dto = client.get(f"/api/listening/records/{record_id}")
        self.assertEqual(status, 200, dto)
        group = dto["domains"][0]["groups"][0]
        group_id = group["group_id"]
        position = group["position"]
        jpeg = jpeg_bytes((30, 80, 120), (64, 48))
        status, uploaded = post_multipart(
            client,
            f"/api/listening/records/{record_id}/domains/health/photos/{group_id}",
            {
                "request_id": str(uuid.uuid4()),
                "expected_revision": str(dto["revision"]),
                "display_name": "synthetic.jpg",
            },
            filename="synthetic.jpg",
            content=jpeg,
            content_type="image/jpeg",
        )
        self.assertEqual(status, 201, uploaded)
        status, dto = client.get(f"/api/listening/records/{record_id}")
        self.assertEqual(status, 200, dto)
        revision = dto["revision"]
        session = runtime.session()
        try:
            ai_config_service.patch_config(
                session,
                expected_ai_config_version=0,
                base_url="https://api.deepseek.com/v1",
                model="deepseek-v4-flash-vision-exp",
                secret="synthetic-secret",
                secret_provided=True,
                request_id=str(uuid.uuid4()),
                credential_root=runtime.credential_root,
            )
            session.commit()
            created, _ = listening_ai_service.create_task(
                session,
                runtime=runtime,
                profile_id=profile_id,
                record_id=record_id,
                domain="health",
                group_id=None,
                task_type="listening_group_notes",
                expected_revision=revision,
                request_id=str(uuid.uuid4()),
            )
        finally:
            session.close()
        claim = ai_task_service.claim_next(
            runtime, now=datetime.now(), started_ticks=0
        )
        self.assertIsNotNone(claim)
        session = runtime.session()
        try:
            self.assertTrue(
                ai_task_service.commit_dispatch_mark(session, claim, datetime.now())
            )
        finally:
            session.close()
        text = "孩子说想把积木放下面。"
        session = runtime.session()
        try:
            self.assertTrue(
                ai_task_service.finalize_success(
                    session,
                    claim,
                    {
                        "kind": "success",
                        "candidate_text": json.dumps(
                            {
                                "mode": "group_notes",
                                "groups": [
                                    {
                                        "position": position,
                                        "text": text,
                                        "uncertainties": [],
                                    }
                                ],
                            },
                            ensure_ascii=False,
                        ),
                    },
                    datetime.now(),
                )
            )
            candidate = listening_ai_service.get_candidate(
                session,
                profile_id=profile_id,
                record_id=record_id,
                task_id=created["task_id"],
            )
        finally:
            session.close()
        return record_id, candidate["candidate_id"], group_id, text

    def test_group_notes_preview_adopt_replay_uses_domain_groups(self) -> None:
        server = self.start_server()
        client = server.client()
        self.initialize(client)
        record_id, candidate_id, group_id, text = self._setup_group_candidate(
            client, server.runtime
        )
        status, preview = client.post(
            f"/api/listening/records/{record_id}/ai/candidates/"
            f"{candidate_id}/preview-adoption",
            {"candidate_id": candidate_id},
        )
        self.assertEqual(status, 200, preview)
        self.assertEqual(preview["task_type"], "listening_group_notes")
        proposed = preview["proposed"]["groups"]
        self.assertEqual(len(proposed), 1)
        target = proposed[0]["target"]
        self.assertTrue(target.startswith("health_"))
        request = str(uuid.uuid4())
        body = {
            "request_id": request,
            "expected_revision": preview["revision"],
            "preview_token": preview["preview_token"],
            "selections": [{"target": target, "value": text}],
        }
        status, adopted = client.post(
            f"/api/listening/records/{record_id}/ai/candidates/"
            f"{candidate_id}/adopt",
            body,
        )
        self.assertEqual(status, 201, adopted)
        self.assertEqual(adopted["domain"], "health")
        self.assertEqual(adopted["group_updates"][0]["group_id"], group_id)
        status, current = client.get(f"/api/listening/records/{record_id}")
        self.assertEqual(status, 200, current)
        saved_group = next(
            item
            for item in current["domains"][0]["groups"]
            if item["group_id"] == group_id
        )
        self.assertEqual(saved_group["listening_text"], text)

        status, replay = client.post(
            f"/api/listening/records/{record_id}/ai/candidates/"
            f"{candidate_id}/adopt",
            body,
        )
        self.assertEqual(status, 200, replay)
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["revision_after"], adopted["revision_after"])
        status, again = client.get(f"/api/listening/records/{record_id}")
        self.assertEqual(status, 200, again)
        self.assertEqual(again["revision"], adopted["revision_after"])

    def test_candidate_url_and_body_bind_before_write(self) -> None:
        server = self.start_server()
        client = server.client()
        self.initialize(client)
        record_id, candidate_id = self._setup_candidate(client, server.runtime)
        wrong = "wrong-candidate-id"
        status, payload = client.post(
            f"/api/listening/records/{record_id}/ai/candidates/{candidate_id}/preview-adoption",
            {"candidate_id": wrong},
        )
        self.assertEqual(status, 422, payload)

        status, preview = client.post(
            f"/api/listening/records/{record_id}/ai/candidates/{candidate_id}/preview-adoption",
            {"candidate_id": candidate_id},
        )
        self.assertEqual(status, 200, preview)
        request = str(uuid.uuid4())
        selections = [
            {"target": "listening_text", "value": "孩子指着太阳说想画下来。"}
        ]
        status, payload = client.post(
            f"/api/listening/records/{record_id}/ai/candidates/{wrong}/adopt",
            {
                "request_id": request,
                "expected_revision": preview["revision"],
                "preview_token": preview["preview_token"],
                "selections": selections,
            },
        )
        self.assertGreaterEqual(status, 400, payload)
        # The wrong URL must not have consumed or written the target.
        status, current = client.get(f"/api/listening/records/{record_id}")
        self.assertEqual(status, 200, current)
        text = current["domains"][0]["groups"][0]["listening_text"]
        self.assertEqual(text, "孩子说想画太阳。")

        status, adopted = client.post(
            f"/api/listening/records/{record_id}/ai/candidates/{candidate_id}/adopt",
            {
                "request_id": request,
                "expected_revision": preview["revision"],
                "preview_token": preview["preview_token"],
                "selections": selections,
            },
        )
        self.assertEqual(status, 201, adopted)
        self.assertEqual(adopted["domain"], "health")
        status, receipt = client.get(
            f"/api/listening/records/{record_id}/ai/operations/{request}"
        )
        self.assertEqual(status, 200, receipt)
        self.assertEqual(receipt["operation_kind"], "listening_ai_adopt")
        self.assertEqual(receipt["result"]["adopted"][0]["target"], "listening_text")
        # Read-only receipt query did not write another adoption or revision.
        status, again = client.get(f"/api/listening/records/{record_id}")
        self.assertEqual(status, 200, again)
        self.assertEqual(again["revision"], adopted["revision_after"])
