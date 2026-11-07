"""Listening export HTTP routes through a real loopback server."""

from __future__ import annotations

import uuid

from tests.local.listening_fixture_support import get_bytes
from tests.local.support import LocalTestCase


class ListeningExportApiTests(LocalTestCase):
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

    def test_preview_generate_content_and_strict_payloads(self) -> None:
        server = self.start_server()
        client = server.client()
        self.initialize(client)
        context = self._context(client)
        term_id = context["terms"][0]["id"]
        record = self._create(client, term_id, "虚构乙/合成")

        status, preview = client.post(
            "/api/listening-exports/preview",
            {
                "mode": "record",
                "record_id": record["record_id"],
                "term_id": term_id,
            },
        )
        self.assertEqual(status, 200, preview)
        self.assertEqual(preview["term_id"], term_id)
        self.assertNotIn("/", preview["default_filename"])
        self.assertEqual(
            [unit["domain"] for unit in preview["units"]],
            ["language", "science", "health", "social", "art"],
        )

        for invalid in (
            {
                "mode": "record",
                "record_id": record["record_id"],
                "term_id": term_id,
                "extra": True,
            },
            {
                "mode": "record",
                "record_id": record["record_id"],
                "term_id": "not-a-term",
            },
            {
                "mode": "domain",
                "domain": "science",
                "term_id": term_id,
                "record_ids": [record["record_id"]],
                "unknown": 1,
            },
        ):
            status, payload = client.post(
                "/api/listening-exports/preview", invalid
            )
            self.assertEqual(status, 422, payload)

        status, domain_preview = client.post(
            "/api/listening-exports/preview",
            {"mode": "domain", "domain": "science", "term_id": term_id},
        )
        self.assertEqual(status, 200, domain_preview)
        self.assertEqual(
            domain_preview["record_ids"], [record["record_id"]]
        )

        status, payload = client.post(
            "/api/listening-exports/preview",
            {"mode": "domain", "domain": "science"},
        )
        self.assertEqual(status, 422, payload)

        request = str(uuid.uuid4())
        for invalid in (
            {
                "preview_id": preview["preview_id"],
                "request_id": request,
                "filename": preview["default_filename"],
                "ack_missing": "yes",
            },
            {
                "preview_id": preview["preview_id"],
                "request_id": request,
                "filename": preview["default_filename"],
                "ack_missing": True,
                "extra": 1,
            },
        ):
            status, payload = client.post(
                "/api/listening-exports/generate", invalid
            )
            self.assertEqual(status, 422, payload)

        status, ready = client.post(
            "/api/listening-exports/generate",
            {
                "preview_id": preview["preview_id"],
                "request_id": request,
                "filename": preview["default_filename"],
                "ack_missing": True,
            },
        )
        self.assertEqual(status, 200, ready)
        self.assertEqual(ready["status"], "ready")
        self.assertNotEqual(ready["status"], "saved")

        status, meta = client.get(
            f"/api/listening-exports/{ready['export_id']}/meta"
        )
        self.assertEqual(status, 200, meta)
        self.assertEqual(
            (meta["sha256"], meta["bytes"]),
            (ready["sha256"], ready["bytes"]),
        )

        status, content, headers = get_bytes(
            client, f"/api/listening-exports/{ready['export_id']}/content"
        )
        self.assertEqual(status, 200)
        self.assertTrue(content.startswith(b"PK"))
        self.assertEqual(headers["x-content-sha256"], ready["sha256"])
        self.assertEqual(int(headers["content-length"]), ready["bytes"])
        self.assertIn("wordprocessingml.document", headers["content-type"])

        status, receipt = client.get(
            f"/api/listening-exports/operations/{request}"
        )
        self.assertEqual(status, 200, receipt)
        self.assertEqual(receipt["export_id"], ready["export_id"])

        status, conflict = client.post(
            "/api/listening-exports/generate",
            {
                "preview_id": preview["preview_id"],
                "request_id": request,
                "filename": "不同文件名.docx",
                "ack_missing": True,
            },
        )
        self.assertEqual(status, 409, conflict)
        self.assertEqual(
            conflict["error"]["code"], "LISTENING_EXPORT_REQUEST_CONFLICT"
        )
