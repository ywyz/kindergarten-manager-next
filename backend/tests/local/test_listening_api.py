"""Listening API through a real loopback Uvicorn server (no TestClient)."""

from __future__ import annotations

import uuid
from urllib.parse import quote

from app.local import listening_service, listening_templates
from tests.local.listening_fixture_support import (
    get_bytes,
    jpeg_bytes,
    png_bytes,
    post_multipart,
)
from tests.local.support import LocalTestCase


class ListeningApiTests(LocalTestCase):
    def _context(self, client):
        status, payload = client.get("/api/local/context")
        self.assertEqual(status, 200, payload)
        return payload

    def _create(self, client, term_id: str, name: str):
        status, payload = client.post(
            "/api/listening/records",
            {
                "request_id": str(uuid.uuid4()),
                "term_id": term_id,
                "child_name": name,
            },
        )
        self.assertEqual(status, 201, payload)
        return payload

    def test_real_http_lifecycle_and_ownership(self) -> None:
        server = self.start_server()
        client = server.client()
        self.initialize(client)
        context = self._context(client)
        term_id = context["terms"][0]["id"]
        first = self._create(client, term_id, "同名幼儿")
        second = self._create(client, term_id, "同名幼儿")
        self.assertNotEqual(first["record_id"], second["record_id"])

        status, record = client.get(
            f"/api/listening/records/{first['record_id']}"
        )
        self.assertEqual(status, 200, record)
        self.assertEqual(
            [domain["domain"] for domain in record["domains"]],
            ["health", "language", "social", "science", "art"],
        )
        health = record["domains"][0]
        group_id = health["groups"][0]["group_id"]

        save_request = str(uuid.uuid4())
        save_body = {
            "request_id": save_request,
            "expected_revision": record["revision"],
            "observation_date": "9月1日 上午",
            "goal": "目标",
            "evaluation": {"health_1": 2},
            "groups": [
                {
                    "group_id": group_id,
                    "work_date": "9月2日",
                    "listening_text": "孩子说：\n我想画太阳。",
                }
            ],
        }
        status, saved = client.patch(
            f"/api/listening/records/{first['record_id']}/domains/health",
            save_body,
        )
        self.assertEqual(status, 200, saved)
        self.assertEqual(saved["revision"], 2)
        status, replay = client.patch(
            f"/api/listening/records/{first['record_id']}/domains/health",
            save_body,
        )
        self.assertEqual(status, 200, replay)
        self.assertEqual(replay, saved)
        status, conflict = client.patch(
            f"/api/listening/records/{first['record_id']}/domains/health",
            {**save_body, "goal": "不同内容"},
        )
        self.assertEqual(status, 409, conflict)
        status, stale = client.patch(
            f"/api/listening/records/{first['record_id']}/domains/health",
            {
                "request_id": str(uuid.uuid4()),
                "expected_revision": 1,
                "goal": "过期",
            },
        )
        self.assertEqual(status, 409, stale)

        for invalid in (
            {"evaluation": {"health_1": 4}},
            {"evaluation": {"health_1": True}},
            {"evaluation": {"health_unknown": 2}},
            {"evaluation": {"health_1": 2}, "unknown_field": "x"},
        ):
            status, payload = client.patch(
                f"/api/listening/records/{first['record_id']}/domains/health",
                {
                    "request_id": str(uuid.uuid4()),
                    "expected_revision": 2,
                    **invalid,
                },
            )
            self.assertEqual(status, 422, payload)
        status, current = client.get(
            f"/api/listening/records/{first['record_id']}"
        )
        self.assertEqual(current["revision"], 2)
        self.assertEqual(current["domains"][0]["goal"], "目标")
        self.assertEqual(current["domains"][0]["evaluation"][0]["stars"], 2)

        # Upload a synthetic JPEG through the real multipart envelope.
        jpeg = jpeg_bytes((10, 20, 30), (137, 89))
        status, uploaded = post_multipart(
            client,
            f"/api/listening/records/{first['record_id']}/domains/health/photos/{group_id}",
            {
                "request_id": str(uuid.uuid4()),
                "expected_revision": str(current["revision"]),
                "display_name": "画.jpg",
            },
            filename="画.jpg",
            content=jpeg,
            content_type="image/jpeg",
        )
        self.assertEqual(status, 201, uploaded)
        self.assertEqual(uploaded["width"], 137)
        self.assertEqual(uploaded["height"], 89)
        status, payload, headers = get_bytes(
            client,
            f"/api/listening/records/{first['record_id']}/assets/"
            f"{uploaded['asset_id']}/content",
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload, jpeg)
        self.assertEqual(headers.get("content-type"), "image/jpeg")

        status, current = client.get(
            f"/api/listening/records/{first['record_id']}"
        )
        replacement = post_multipart(
            client,
            f"/api/listening/records/{first['record_id']}/domains/health/photos/{group_id}",
            {
                "request_id": str(uuid.uuid4()),
                "expected_revision": str(current["revision"]),
                "display_name": "替换.png",
            },
            filename="替换.png",
            content=png_bytes((200, 10, 10), (48, 32)),
            content_type="image/png",
        )
        self.assertEqual(replacement[0], 201, replacement[1])
        replacement = replacement[1]
        self.assertEqual(replacement["old_asset_id"], uploaded["asset_id"])
        status, old_payload, _headers = get_bytes(
            client,
            f"/api/listening/records/{first['record_id']}/assets/"
            f"{uploaded['asset_id']}/content",
        )
        self.assertEqual(status, 200)
        self.assertEqual(old_payload, jpeg)

        status, current = client.get(
            f"/api/listening/records/{first['record_id']}"
        )
        group_ids = [group["group_id"] for group in current["domains"][0]["groups"]]
        order = [group_ids[1], group_ids[2], group_ids[0]]
        reorder_request = str(uuid.uuid4())
        reorder_body = {
            "request_id": reorder_request,
            "expected_revision": current["revision"],
            "group_ids": order,
        }
        status, reordered = client.post(
            f"/api/listening/records/{first['record_id']}/domains/health/photos/order",
            reorder_body,
        )
        self.assertEqual(status, 200, reordered)
        self.assertTrue(reordered["changed"])
        status, after = client.get(
            f"/api/listening/records/{first['record_id']}"
        )
        self.assertEqual(
            [group["group_id"] for group in after["domains"][0]["groups"]],
            order,
        )
        status, replay_order = client.post(
            f"/api/listening/records/{first['record_id']}/domains/health/photos/order",
            reorder_body,
        )
        self.assertEqual(status, 200, replay_order)
        self.assertEqual(replay_order, reordered)
        status, after_replay = client.get(
            f"/api/listening/records/{first['record_id']}"
        )
        self.assertEqual(
            [group["group_id"] for group in after_replay["domains"][0]["groups"]],
            order,
        )

        # Remove only the current association; the replaced original remains
        # readable by asset id.
        status, removed = client.request(
            "DELETE",
            f"/api/listening/records/{first['record_id']}/domains/health/photos/{group_id}",
            {
                "request_id": str(uuid.uuid4()),
                "expected_revision": after_replay["revision"],
            },
        )
        self.assertEqual(status, 200, removed)
        self.assertIsNone(removed["asset_id"])
        status, old_payload, _headers = get_bytes(
            client,
            f"/api/listening/records/{first['record_id']}/assets/"
            f"{replacement['asset_id']}/content",
        )
        self.assertEqual(status, 200)
        self.assertTrue(old_payload.startswith(b"\x89PNG"))

        # Same-name peer remains isolated.
        status, peer = client.get(
            f"/api/listening/records/{second['record_id']}"
        )
        self.assertEqual(status, 200, peer)
        self.assertNotEqual(peer["revision"], after_replay["revision"])
        self.assertTrue(
            all(
                group["asset_id"] is None
                for domain in peer["domains"]
                for group in domain["groups"]
            )
        )
        status, cross = client.get(
            f"/api/listening/records/{second['record_id']}/assets/"
            f"{replacement['asset_id']}/content"
        )
        self.assertEqual(status, 404, cross)
        status, cross_upload = post_multipart(
            client,
            f"/api/listening/records/{second['record_id']}/domains/health/photos/{group_id}",
            {
                "request_id": str(uuid.uuid4()),
                "expected_revision": str(peer["revision"]),
                "display_name": "cross.png",
            },
            filename="cross.png",
            content=png_bytes(),
            content_type="image/png",
        )
        self.assertEqual(status, 404, cross_upload)
        status, fourth = post_multipart(
            client,
            f"/api/listening/records/{first['record_id']}/domains/health/photos/fourth_group",
            {
                "request_id": str(uuid.uuid4()),
                "expected_revision": str(removed["revision"]),
                "display_name": "fourth.png",
            },
            filename="fourth.png",
            content=png_bytes(),
            content_type="image/png",
        )
        self.assertEqual(status, 404, fourth)

        # Name correction is shared by the record, not copied per domain.
        status, renamed = client.patch(
            f"/api/listening/records/{first['record_id']}",
            {
                "request_id": str(uuid.uuid4()),
                "expected_revision": removed["revision"],
                "child_name": "新名",
            },
        )
        self.assertEqual(status, 200, renamed)
        self.assertEqual(renamed["revision"], removed["revision"] + 1)
        status, renamed_record = client.get(
            f"/api/listening/records/{first['record_id']}"
        )
        self.assertEqual(renamed_record["child_name"], "新名")
        status, peer_after = client.get(
            f"/api/listening/records/{second['record_id']}"
        )
        self.assertEqual(peer_after["child_name"], "同名幼儿")

        status, listed = client.get(
            f"/api/listening/records?term_id={term_id}"
            f"&child_name={quote('同名幼儿')}"
        )
        self.assertEqual(status, 200, listed)
        self.assertEqual(listed["total"], 1)
        self.assertEqual(listed["items"][0]["record_id"], second["record_id"])
        status, templates = client.get("/api/listening/templates")
        self.assertEqual(status, 200, templates)
        self.assertEqual(len(templates["templates"]), 5)
        status, template = client.get(
            "/api/listening/templates?domain=health&version=v1"
        )
        self.assertEqual(status, 200, template)
        self.assertEqual(template["templates"][0]["version"], "v1")
        status, missing = client.get(
            "/api/listening/templates?domain=health&version=v0"
        )
        self.assertEqual(status, 422, missing)

        # Ownership fields are not accepted from the client.
        status, payload = client.post(
            "/api/listening/records",
            {
                "request_id": str(uuid.uuid4()),
                "term_id": term_id,
                "child_name": "注入",
                "profile_id": "forged",
            },
        )
        self.assertEqual(status, 422, payload)
        status, payload = client.post(
            "/api/listening/records",
            {
                "request_id": str(uuid.uuid4()),
                "term_id": "not-a-term",
                "child_name": "无效学期",
            },
        )
        self.assertEqual(status, 422, payload)

    def test_record_bound_templates_after_class_upgrade(self) -> None:
        server = self.start_server()
        client = server.client()
        self.initialize(client)
        context = self._context(client)
        term_id = context["terms"][0]["id"]
        old = self._create(client, term_id, "绑定旧生")
        status, old_record = client.get(
            f"/api/listening/records/{old['record_id']}"
        )
        self.assertEqual(status, 200, old_record)
        self.assertEqual(old_record["grade"], "middle")
        status, saved = client.patch(
            f"/api/listening/records/{old['record_id']}/domains/health",
            {
                "request_id": str(uuid.uuid4()),
                "expected_revision": old_record["revision"],
                "evaluation": {"health_1": 2},
            },
        )
        self.assertEqual(status, 200, saved)
        change = {
            "kind": "current_class",
            "name": context["class"]["name"],
            "grade": "large",
        }
        status, preview = client.post(
            "/api/local/config/preview",
            {
                "expected_config_version": context["config_version"],
                "change": change,
            },
        )
        self.assertEqual(status, 200, preview)
        status, applied = client.post(
            "/api/local/config/apply",
            {
                "request_id": str(uuid.uuid4()),
                "expected_config_version": context["config_version"],
                "change": change,
                "preview_token": preview["preview_token"],
            },
        )
        self.assertEqual(status, 200, applied)
        new = self._create(client, term_id, "绑定新生")
        middle = listening_templates.get_template("middle", "health")
        large = listening_templates.get_template("large", "health")

        status, bound = client.get(
            f"/api/listening/templates?domain=health&version=v1"
            f"&record_id={old['record_id']}"
        )
        self.assertEqual(status, 200, bound)
        self.assertEqual(bound["grade"], "middle")
        self.assertEqual(bound["record_id"], old["record_id"])
        self.assertEqual(bound["templates"][0]["sha256"], middle.sha256)
        self.assertEqual(
            bound["templates"][0]["items"], middle.as_dict()["items"]
        )

        status, five = client.get(
            f"/api/listening/templates?record_id={old['record_id']}"
        )
        self.assertEqual(status, 200, five)
        self.assertEqual(five["grade"], "middle")
        self.assertEqual(five["record_id"], old["record_id"])
        self.assertEqual(
            [item["domain"] for item in five["templates"]],
            ["health", "language", "social", "science", "art"],
        )
        self.assertEqual(
            [item["sha256"] for item in five["templates"]],
            [
                listening_templates.get_template("middle", domain).sha256
                for domain in listening_service.DOMAINS
            ],
        )

        status, new_bound = client.get(
            f"/api/listening/templates?domain=health"
            f"&record_id={new['record_id']}"
        )
        self.assertEqual(status, 200, new_bound)
        self.assertEqual(new_bound["grade"], "large")
        self.assertEqual(new_bound["templates"][0]["sha256"], large.sha256)

        status, current = client.get("/api/listening/templates")
        self.assertEqual(status, 200, current)
        self.assertEqual(current["grade"], "large")
        self.assertNotIn("record_id", current)
        status, current_domain = client.get(
            "/api/listening/templates?domain=health&version=v1"
        )
        self.assertEqual(status, 200, current_domain)
        self.assertEqual(current_domain["grade"], "large")
        self.assertEqual(
            current_domain["templates"][0]["sha256"], large.sha256
        )

        status, bad_version = client.get(
            f"/api/listening/templates?domain=health&version=v0"
            f"&record_id={old['record_id']}"
        )
        self.assertEqual(status, 422, bad_version)
        status, bad_version_all = client.get(
            f"/api/listening/templates?version=v0&record_id={old['record_id']}"
        )
        self.assertEqual(status, 422, bad_version_all)
        status, missing = client.get(
            "/api/listening/templates?record_id=missing-record"
        )
        self.assertEqual(status, 404, missing)
        status, no_record_bad = client.get(
            "/api/listening/templates?version=v0"
        )
        self.assertEqual(status, 422, no_record_bad)

        status, old_after = client.get(
            f"/api/listening/records/{old['record_id']}"
        )
        self.assertEqual(status, 200, old_after)
        self.assertEqual(old_after["grade"], "middle")
        self.assertEqual(
            old_after["domains"][0]["template_sha256"], middle.sha256
        )
        self.assertEqual(
            old_after["domains"][0]["evaluation"][0]["stars"], 2
        )

    def test_uninitialized_profile_is_refused(self) -> None:
        server = self.start_server()
        client = server.client()
        status, payload = client.post(
            "/api/listening/records",
            {
                "request_id": str(uuid.uuid4()),
                "term_id": "any",
                "child_name": "未建档",
            },
        )
        self.assertEqual(status, 409, payload)
        self.assertEqual(payload["error"]["code"], "LOCAL_PROFILE_REQUIRED")
