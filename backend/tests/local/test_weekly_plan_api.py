"""Real-loopback HTTP tests for weekly plan routes (A-owned)."""

from __future__ import annotations

import unittest
import uuid

from sqlalchemy import select

from app.local.models import LocalWeeklyPlanOperation
from app.local.runtime import LocalRuntime
from tests.local.support import LocalTestCase


class WeeklyPlanApiTests(LocalTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.runtime = self.make_runtime()
        self.server = self.start_server(self.runtime)
        self.client = self.server.client()
        self.context = self.initialize(self.client)
        self.term_id = self.context["terms"][0]["id"]

    def _create_preview(self, anchor: str = "2026-09-07") -> dict:
        status, preview = self.client.post(
            "/api/weekly-plans/create-preview",
            {"term_id": self.term_id, "week_anchor_date": anchor},
        )
        self.assertEqual(status, 200, preview)
        self.assertEqual(preview["status"], "new")
        self.assertIsInstance(preview["expected_config_version"], int)
        self.assertIsInstance(preview["expires_at"], str)
        return preview

    def _create(self, anchor: str = "2026-09-07") -> dict:
        preview = self._create_preview(anchor)
        status, result = self.client.post(
            "/api/weekly-plans",
            {
                "request_id": str(uuid.uuid4()),
                "term_id": self.term_id,
                "week_anchor_date": anchor,
                "expected_config_version": preview["expected_config_version"],
                "context_token": preview["create_token"],
            },
        )
        self.assertEqual(status, 201, result)
        return result

    def test_list_filter_cursor_and_invalid_dates(self) -> None:
        status, listed = self.client.get(
            f"/api/weekly-plans?term_id={self.term_id}&from=2026-09-01&to=2026-10-30"
        )
        self.assertEqual(status, 200, listed)
        self.assertEqual(listed["items"], [])
        self.assertIsNone(listed["next_cursor"])
        first = self._create("2026-09-07")
        second = self._create("2026-09-14")
        status, page = self.client.get(
            f"/api/weekly-plans?term_id={self.term_id}&limit=1"
        )
        self.assertEqual(status, 200, page)
        self.assertEqual(len(page["items"]), 1)
        self.assertIsNotNone(page["next_cursor"])
        status, page2 = self.client.get(
            f"/api/weekly-plans?term_id={self.term_id}&limit=1"
            f"&cursor={page['next_cursor']}"
        )
        self.assertEqual(status, 200, page2)
        self.assertEqual(len(page2["items"]), 1)
        self.assertNotEqual(page["items"][0]["id"], page2["items"][0]["id"])
        for bad in ("2026-9-7", "2026-09-07T00:00:00", "1757203200"):
            status, payload = self.client.get(
                f"/api/weekly-plans?from={bad}"
            )
            self.assertEqual(status, 422, (bad, payload))

    def test_operation_returns_original_immutable_business_result(self) -> None:
        create_request = str(uuid.uuid4())
        preview = self._create_preview()
        status, created = self.client.post(
            "/api/weekly-plans",
            {
                "request_id": create_request,
                "term_id": self.term_id,
                "week_anchor_date": "2026-09-07",
                "expected_config_version": preview["expected_config_version"],
                "context_token": preview["create_token"],
            },
        )
        self.assertEqual(status, 201, created)
        self.assertTrue(created["operation_id"])
        self.assertEqual(created["request_id"], create_request)
        self.assertEqual(created["draft"]["version"], 1)
        plan_id = created["weekly_plan_id"]
        for expected, theme in ((2, "第二版"), (3, "第三版")):
            status, saved = self.client.patch(
                f"/api/weekly-plans/{plan_id}",
                {
                    "request_id": str(uuid.uuid4()),
                    "expected_draft_version": expected - 1,
                    "patch": {"theme": theme},
                },
            )
            self.assertEqual(status, 200, saved)
            self.assertEqual(saved["draft"]["version"], expected)
        status, detail = self.client.get(f"/api/weekly-plans/{plan_id}")
        self.assertEqual(status, 200, detail)
        self.assertEqual(detail["draft"]["version"], 3)
        status, operation = self.client.get(
            f"/api/weekly-plans/operations/{create_request}"
        )
        self.assertEqual(status, 200, operation)
        self.assertEqual(operation["operation_id"], created["operation_id"])
        self.assertEqual(operation["request_id"], create_request)
        self.assertEqual(operation["draft"]["version"], 1)
        self.assertEqual(operation["draft"]["content"]["theme"], "")
        status, missing = self.client.get(
            "/api/weekly-plans/operations/" + str(uuid.uuid4())
        )
        self.assertEqual(status, 404, missing)
        # Refresh preview also carries the same TTL field type.
        status, refresh = self.client.post(
            f"/api/weekly-plans/{plan_id}/refresh-preview",
            {"expected_draft_version": 3},
        )
        self.assertEqual(status, 200, refresh)
        self.assertIsInstance(refresh["expires_at"], str)

    def test_operation_survives_cold_runtime_reopen(self) -> None:
        create_request = str(uuid.uuid4())
        preview = self._create_preview()
        status, created = self.client.post(
            "/api/weekly-plans",
            {
                "request_id": create_request,
                "term_id": self.term_id,
                "week_anchor_date": "2026-09-07",
                "expected_config_version": preview["expected_config_version"],
                "context_token": preview["create_token"],
            },
        )
        self.assertEqual(status, 201, created)
        self.server.stop()
        self.runtime.dispose()
        reopened = LocalRuntime(
            data_dir=self.runtime.data_dir,
            credential_root=self.runtime.credential_root,
        )
        reopened.prepare()
        self.addCleanup(reopened.dispose)
        server = self.start_server(reopened)
        client = server.client()
        status, operation = client.get(
            f"/api/weekly-plans/operations/{create_request}"
        )
        self.assertEqual(status, 200, operation)
        self.assertEqual(operation["draft"]["version"], 1)
        session = reopened.session()
        try:
            row = session.scalars(
                select(LocalWeeklyPlanOperation).where(
                    LocalWeeklyPlanOperation.request_id == create_request
                )
            ).one()
            self.assertEqual(
                set(row.result_json),
                {
                    "schema_version",
                    "weekly_plan_id",
                    "draft_id",
                    "draft_version",
                    "confirmation_id",
                    "confirmation_version",
                    "snapshot_id",
                    "token_id",
                },
            )
        finally:
            session.close()
