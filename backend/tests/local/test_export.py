"""D1 Word export (B4): ranges, limits, ack binding, snapshot and warnings.

Real temp file databases, real Uvicorn HTTP and real subprocess workers; the
DOCX bytes are real ZIPs and their document XML is inspected directly. No
mocks or in-memory databases; a generation failure is injected with a real
monkeypatch of the generator entry point in the live app process.
"""

from __future__ import annotations

import base64
import io
import json
import unittest
import uuid
import zipfile
from pathlib import Path
from unittest import mock

from tests.local.support import (
    LocalTestCase,
    StaticCalendarProvider,
    calendar_provider,
    wait_for_file,
)

SEP_START = "2026-09-01"
SEP_END = "2026-09-30"


def docx_text(payload: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    return xml


class ExportTestBase(LocalTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.provider = StaticCalendarProvider()
        self.enterContext(calendar_provider(self.provider))
        self.server = self.start_server()
        self.client = self.server.client()
        self.init = self.initialize(self.client)
        self.term_id = self.init["terms"][0]["id"]

    def create_plan(self, day: str, **body) -> dict:
        payload = {"plan_date": day, **body}
        status, response = self.client.post("/api/daily-plans", payload)
        self.assertEqual(status, 201, response)
        return response

    def export(self, payload: dict):
        return self.client.post("/api/exports/daily-plans", payload)

    def export_binary(self, payload: dict, *, token=None, client=None):
        """Raw HTTP export returning (status, headers, body bytes)."""
        import http.client

        target = client or self.client
        connection = http.client.HTTPConnection("127.0.0.1", target.port, timeout=60)
        headers = {
            "Content-Type": "application/json",
            "X-App-Session": token if token is not None else target.token,
            "Origin": target.origin,
        }
        connection.request(
            "POST",
            "/api/exports/daily-plans",
            body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
        )
        response = connection.getresponse()
        data = response.read()
        response_headers = {k.lower(): v for k, v in response.getheaders()}
        connection.close()
        return response.status, response_headers, data

    def export_binary_confirmed(self, payload: dict, *, client=None):
        """Export with the mandatory missing-facts confirmation when asked."""
        status, headers, body = self.export_binary(payload, client=client)
        if status == 409:
            details = json.loads(body.decode("utf-8"))["error"]["details"]
            payload = {
                **payload,
                "ack_missing": True,
                "expected_context": details["expected_context"],
            }
            status, headers, body = self.export_binary(payload, client=client)
        return status, headers, body


class ExportRangeTests(ExportTestBase):
    def test_single_day_and_range_export_real_docx(self):
        self.create_plan("2026-09-01", raw_lesson_plan="第一天教案")
        status, headers, body = self.export_binary_confirmed(
            {"from": "2026-09-01", "to": "2026-09-01"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            headers["content-type"],
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        self.assertEqual(body[:2], b"PK")
        self.assertIn("filename*=UTF-8''", headers["content-disposition"])
        warnings = json.loads(headers["x-export-warnings"])
        self.assertEqual(warnings[0]["code"], "no_split_baseline")
        self.assertIn("无法比较", warnings[0]["message"])
        # The fixed template renders the plan date and week line.
        xml = docx_text(body)
        self.assertIn("9 月 1 日", xml)
        self.assertIn("第 1 周", xml)

    def test_no_matching_plans_is_404_and_creates_nothing(self):
        status, payload = self.export({"from": "2026-09-10", "to": "2026-09-12"})
        self.assertEqual(status, 404, payload)
        self.assertEqual(payload["error"]["code"], "EXPORT_NOT_FOUND")

    def test_month_range_and_multi_plan_page_break(self):
        for day in ("2026-09-01", "2026-09-02", "2026-09-03"):
            self.create_plan(
                day, adopted_content={"reflection": f"{day} 反思"}
            )
        status, headers, body = self.export_binary_confirmed(
            {"from": "2026-09-01", "to": "2026-09-30"}
        )
        self.assertEqual(status, 200)
        xml = docx_text(body)
        for day in ("9 月 1 日", "9 月 2 日", "9 月 3 日"):
            self.assertIn(day, xml)
        for day in ("2026-09-01", "2026-09-02", "2026-09-03"):
            self.assertIn(f"{day} 反思", xml)
        # Each plan after the first starts on a new page (page break run).
        self.assertIn('w:type="page"', xml)

    def test_moved_out_plan_is_still_exported(self):
        plan = self.create_plan(
            "2026-09-30", adopted_content={"reflection": "移出范围反思"}
        )
        change = {
            "kind": "term_update",
            "term_id": self.term_id,
            "name": "2026 年秋季学期",
            "start_date": SEP_START,
            "end_date": "2026-09-15",
        }
        status, preview = self.client.post(
            "/api/local/config/preview",
            {"expected_config_version": 1, "change": change},
        )
        self.assertEqual(status, 200, preview)
        status, applied = self.client.post(
            "/api/local/config/apply",
            {
                "request_id": str(uuid.uuid4()),
                "expected_config_version": 1,
                "change": change,
                "preview_token": preview["preview_token"],
            },
        )
        self.assertEqual(status, 200, applied)
        # The date is now outside the term and non-eligible for creation, but
        # the export still includes the saved record.
        status, headers, body = self.export_binary_confirmed(
            {"from": "2026-09-30", "to": "2026-09-30"}
        )
        self.assertEqual(status, 200)
        self.assertIn("移出范围反思", docx_text(body))
        self.assertEqual(
            plan["id"],
            self.client.get("/api/daily-plans/by-date?date=2026-09-30")[1]["id"],
        )

    def test_invalid_ranges_and_ownership_fields_rejected(self):
        status, payload = self.export({"from": "2026-09-10", "to": "2026-09-01"})
        self.assertEqual(status, 422, payload)
        self.assertEqual(payload["error"]["code"], "VALIDATION_ERROR")
        status, payload = self.client.post(
            "/api/exports/daily-plans",
            {"from": "2026-09-01", "to": "2026-09-02", "class_id": "x"},
        )
        self.assertEqual(status, 422, payload)

    def test_31_exported_and_32_rejected(self):
        # A long term gives enough eligible days.
        body = dict(
            request_id=str(uuid.uuid4()),
            display_name="王老师",
            class_name="中一班",
            grade="middle",
            term_name="长学期",
            start_date="2026-09-01",
            end_date="2026-10-20",
            school_name=None,
        )
        server = self.start_server(self.make_runtime(self.tmp_root / "long"))
        client = server.client()
        status, payload = client.post("/api/local/initialize", body)
        self.assertEqual(status, 201, payload)
        # Eligible (teaching) days only: weekends are non-teaching.
        status, calendar = client.get(
            "/api/local/calendar?from=2026-09-01&to=2026-10-20"
        )
        self.assertEqual(status, 200, calendar)
        days = [item["date"] for item in calendar["items"] if item["date_eligible"]]
        self.assertGreaterEqual(len(days), 35)
        for day in days[:31]:
            status, created = client.post("/api/daily-plans", {"plan_date": day})
            self.assertEqual(status, 201, created)
        status, headers, _body = self.export_binary_confirmed(
            {"from": "2026-09-01", "to": "2026-10-20"}, client=client
        )
        self.assertEqual(status, 200)
        status, created = client.post("/api/daily-plans", {"plan_date": days[31]})
        self.assertEqual(status, 201, created)
        status, payload = client.post(
            "/api/exports/daily-plans",
            {"from": "2026-09-01", "to": "2026-10-20"},
        )
        self.assertEqual(status, 422, payload)
        self.assertEqual(payload["error"]["code"], "EXPORT_LIMIT_EXCEEDED")


class ExportR18FormatTests(ExportTestBase):
    """R18 (2026-10-17): the real export pipeline emits the daily format
    decision — explicit centered title, class+teacher signature without the
    grade part, and explicitly non-bold table text (spec §12.4)."""

    def _root(self, body: bytes):
        from lxml import etree

        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            return etree.fromstring(archive.read("word/document.xml"))

    def test_r18_export_single_and_merged_plan_format(self):
        self.create_plan("2026-09-01", raw_lesson_plan="第一天")
        self.create_plan("2026-09-02", raw_lesson_plan="第二天")
        status, _headers, body = self.export_binary_confirmed(
            {"from": "2026-09-01", "to": "2026-09-02"}
        )
        self.assertEqual(status, 200)
        root = self._root(body)
        namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

        def w(tag: str) -> str:
            return f"{{{namespace}}}{tag}"

        document_body = root.find(w("body"))
        paragraphs = [child for child in document_body if child.tag == w("p")]
        titles = [
            paragraph
            for paragraph in paragraphs
            if "".join(t.text or "" for t in paragraph.iter(w("t"))).endswith(
                "一日活动计划"
            )
        ]
        self.assertEqual(len(titles), 2)
        for title in titles:
            text = "".join(t.text or "" for t in title.iter(w("t")))
            self.assertEqual(text, "示范幼儿园一日活动计划")
            alignment = title.find(f"{w('pPr')}/{w('jc')}")
            self.assertIsNotNone(alignment)
            self.assertEqual(alignment.get(w("val")), "center")
        # Signature from the plan's own creation snapshot: class + teacher.
        subtitle_texts = [
            "".join(t.text or "" for t in paragraph.iter(w("t")))
            for paragraph in paragraphs
            if "".join(t.text or "" for t in paragraph.iter(w("t")))
            == "中一班 王老师"
        ]
        self.assertEqual(len(subtitle_texts), 2)
        full_text = "".join(t.text or "" for t in root.iter(w("t")))
        self.assertNotIn("中班", full_text)
        # Every table run carries direct bold-off (b and bCs).
        table = root.find(f".//{w('tbl')}")
        runs = list(table.iter(w("r")))
        self.assertGreater(len(runs), 20)
        for run in runs:
            bold = run.find(f"{w('rPr')}/{w('b')}")
            bold_cs = run.find(f"{w('rPr')}/{w('bCs')}")
            self.assertIsNotNone(bold)
            self.assertEqual(bold.get(w("val")), "false")
            self.assertIsNotNone(bold_cs)
            self.assertEqual(bold_cs.get(w("val")), "false")


class ExportAckTests(ExportTestBase):
    def test_missing_ack_flow_and_context_change(self):
        plan = self.create_plan("2026-09-01")  # empty content: many missing
        status, payload = self.export({"from": "2026-09-01", "to": "2026-09-01"})
        self.assertEqual(status, 409, payload)
        error = payload["error"]
        self.assertEqual(error["code"], "EXPORT_ACK_REQUIRED")
        details = error["details"]
        self.assertEqual(details["reason"], "missing")
        self.assertEqual(details["facts"][0]["daily_plan_id"], plan["id"])
        expected = details["expected_context"]
        self.assertEqual(expected["versions"][0]["content_version"], 1)
        self.assertGreater(expected["missing_count"], 0)

        # ack without the context can never bypass confirmation.
        status, payload = self.export(
            {
                "from": "2026-09-01",
                "to": "2026-09-01",
                "ack_missing": True,
            }
        )
        self.assertEqual(status, 422, payload)
        self.assertEqual(payload["error"]["code"], "VALIDATION_ERROR")

        # Fill everything so the missing set becomes empty; the old context is
        # still refused (context_changed) and a fresh confirmation succeeds.
        status, detail = self.client.get(f"/api/daily-plans/{plan['id']}")
        self.assertEqual(status, 200)
        filled = {
            "morning_games": [
                {
                    "group_kind": "collective",
                    "games": [{"name": "集体游戏"}],
                    "focus_guidance": "指导",
                    "shared_objectives": "目标",
                    "guidance_points": "要点",
                },
                {
                    "group_kind": "free_choice",
                    "games": [{"name": "自选游戏"}],
                    "focus_guidance": "指导",
                    "shared_objectives": "目标",
                    "guidance_points": "要点",
                },
            ],
            "morning_talk": {"topic": "话题", "questions": "问题"},
            "group_activity": {
                "theme": "主题",
                "objectives": "目标",
                "preparation": "准备",
                "key_points": "重点",
                "difficult_points": "难点",
                "process": "过程",
            },
            "post_group_games": [
                {
                    "context_kind": "area",
                    "area": "区域",
                    "games": [{"name": "游戏"}],
                    "focus_guidance": "指导",
                    "objectives": "目标",
                    "guidance": "指导",
                    "support_strategy": "策略",
                }
            ],
            "afternoon_outdoor": {
                "area": "户外",
                "games": [{"name": "游戏"}],
                "observation_focus": "观察",
                "objectives": "目标",
                "guidance": "指导",
                "support_strategy": "策略",
            },
            "reflection": "反思",
        }
        status, saved = self.client.patch(
            f"/api/daily-plans/{plan['id']}",
            {
                "expected_content_version": 1,
                "adopted_content": filled,
            },
        )
        self.assertEqual(status, 200, saved)
        status, payload = self.export(
            {
                "from": "2026-09-01",
                "to": "2026-09-01",
                "ack_missing": True,
                "expected_context": expected,
            }
        )
        self.assertEqual(status, 409, payload)
        self.assertEqual(payload["error"]["code"], "EXPORT_ACK_REQUIRED")
        self.assertEqual(payload["error"]["details"]["reason"], "context_changed")
        new_context = payload["error"]["details"]["expected_context"]
        self.assertEqual(new_context["versions"][0]["content_version"], 2)
        self.assertEqual(new_context["missing_count"], 0)

        status, headers, body = self.export_binary(
            {
                "from": "2026-09-01",
                "to": "2026-09-01",
                "ack_missing": True,
                "expected_context": new_context,
            }
        )
        self.assertEqual(status, 200)
        self.assertIn("反思", docx_text(body))

    def test_ack_confirmed_empty_content_exports_with_empty_columns(self):
        plan = self.create_plan("2026-09-01")
        status, payload = self.export({"from": "2026-09-01", "to": "2026-09-01"})
        self.assertEqual(status, 409)
        expected = payload["error"]["details"]["expected_context"]
        status, headers, body = self.export_binary(
            {
                "from": "2026-09-01",
                "to": "2026-09-01",
                "ack_missing": True,
                "expected_context": expected,
            }
        )
        self.assertEqual(status, 200)
        # A real DOCX that opens as a ZIP; empty columns stay empty.
        self.assertEqual(body[:2], b"PK")
        self.assertEqual(plan["current_content_version"], 1)

    def test_export_never_saves_or_bumps_versions(self):
        plan = self.create_plan("2026-09-01", raw_lesson_plan="原稿")
        before = self.client.get(f"/api/daily-plans/{plan['id']}")[1]
        status, payload = self.export({"from": "2026-09-01", "to": "2026-09-01"})
        self.assertEqual(status, 409)  # empty sections -> ack needed
        expected = payload["error"]["details"]["expected_context"]
        status, headers, body = self.export_binary(
            {
                "from": "2026-09-01",
                "to": "2026-09-01",
                "ack_missing": True,
                "expected_context": expected,
            }
        )
        self.assertEqual(status, 200)
        after = self.client.get(f"/api/daily-plans/{plan['id']}")[1]
        self.assertEqual(
            after["current_content_version"], before["current_content_version"]
        )
        self.assertEqual(after["updated_at"], before["updated_at"])

    def test_generation_failure_is_500_without_internals(self):
        self.create_plan("2026-09-01", raw_lesson_plan="内容")
        status, payload = self.export({"from": "2026-09-01", "to": "2026-09-01"})
        self.assertEqual(status, 409)
        expected = payload["error"]["details"]["expected_context"]
        import app.local.export_service as export_service

        with mock.patch.object(
            export_service,
            "generate_daily_export_docx",
            side_effect=RuntimeError("synthetic-internal-detail"),
        ):
            status, payload = self.export(
                {
                    "from": "2026-09-01",
                    "to": "2026-09-01",
                    "ack_missing": True,
                    "expected_context": expected,
                }
            )
        self.assertEqual(status, 500, payload)
        self.assertEqual(payload["error"]["code"], "EXPORT_GENERATION_FAILED")
        text = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("synthetic-internal-detail", text)
        self.assertNotIn("Traceback", text)


class ExportSnapshotTests(ExportTestBase):
    def test_read_snapshot_materializes_before_concurrent_save(self):
        plan = self.create_plan(
            "2026-09-01", adopted_content={"reflection": "旧快照反思"}
        )
        status, payload = self.export({"from": "2026-09-01", "to": "2026-09-01"})
        self.assertEqual(status, 409)
        expected = payload["error"]["details"]["expected_context"]

        spec = self.worker_spec("export_snapshot")
        spec.update(
            {
                "from_date": "2026-09-01",
                "to_date": "2026-09-01",
                "expected_context": expected,
                "wait_seconds": 30,
                "first_file": str(self.tmp_root / "export-first.json"),
                "proceed_file": str(self.tmp_root / "export-go.flag"),
            }
        )
        process = self.spawn_worker(spec)
        try:
            wait_for_file(spec["first_file"], timeout=60)
            # The worker is paused inside its read transaction after selecting
            # the plan rows; commit a new version from this process.
            status, saved = self.client.patch(
                f"/api/daily-plans/{plan['id']}",
                {
                    "expected_content_version": 1,
                    "adopted_content": {"reflection": "新版本反思"},
                },
            )
            self.assertEqual(status, 200, saved)
        finally:
            Path(spec["proceed_file"]).write_text("go", encoding="utf-8")
        result = self.collect_worker(process, spec, timeout=120)
        self.assertEqual(result["versions"], [1])
        body = base64.b64decode(result["docx_base64"])
        xml = docx_text(body)
        self.assertIn("旧快照反思", xml)
        self.assertNotIn("新版本反思", xml)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
