"""D2 W6 G14 Word closed-loop test (split -> preview edit -> adopt -> adapt ->
teacher manual edit -> save -> cold restart -> single/merged DOCX).

Candidates are produced by the real W3 chain (never inserted rows) and adopted
over the real local HTTP API. The DOCX is a real ZIP whose red comparison runs
are inspected directly. The split baseline is asserted against the *model*
process (never the teacher's preview edit), and must survive the adapt adoption
and the later manual save across a cold restart (runtime lock released, engine
disposed, runtime re-prepared on the same data root).

Environment: temporary data root and isolated credential root via
``LocalTestCase``; ``APP_DISABLE_DOTENV=1`` is set by the shared base. No real
supplier is contacted (candidates come from the W4 test's normal chain).
"""

from __future__ import annotations

import http.client
import io
import json
import unittest
import uuid
import zipfile
from datetime import date

from app.services.word_export_mapping import diff_process
from tests.local.test_d2_w4_api import W4ApiCase
from tests.local.test_d2_w4_candidates import ADAPT_CANDIDATE, SPLIT_CANDIDATE

BASELINE_KEY = "group_activity_process"
P0 = SPLIT_CANDIDATE["group_activity"]["process"]  # model raw process (baseline)
P1 = "一、导入\n二、观察\n三、比较"  # teacher preview edit used at adopt
P2 = ADAPT_CANDIDATE["process"]  # adapt candidate process
P3 = "一、导入\n二、观察\n三、比较（适龄）\n四、教师补充"  # later manual edit
DAY = date(2026, 9, 2)
DAY2 = date(2026, 9, 3)
DAY_ISO = "2026-09-02"
DAY2_ISO = "2026-09-03"

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def docx_root(payload: bytes):
    from lxml import etree

    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        return etree.fromstring(archive.read("word/document.xml"))


def all_text(root) -> str:
    return "".join(node.text or "" for node in root.iter(f"{W}t"))


def red_and_plain_text(root) -> tuple[str, str]:
    red: list[str] = []
    plain: list[str] = []
    for node in root.iter(f"{W}t"):
        color = node.getparent().find(f"{W}rPr/{W}color")
        is_red = color is not None and color.get(f"{W}val") == "FF0000"
        (red if is_red else plain).append(node.text or "")
    return "".join(red), "".join(plain)


class W6ExportClosureCase(W4ApiCase):
    def setUp(self) -> None:
        super().setUp()
        self.plan = self.make_plan(plan_date=DAY, raw="W6 拆分用原文：一、导入；二、观察；三、比较")

    # -- helpers -----------------------------------------------------------
    def export_docx(self, from_date: str, to_date: str):
        body = {"from": from_date, "to": to_date}
        client = self.client
        headers = {
            "Content-Type": "application/json",
            "X-App-Session": client.token,
            "Origin": client.origin,
        }

        def one_call(payload):
            connection = http.client.HTTPConnection("127.0.0.1", client.port, timeout=60)
            try:
                connection.request(
                    "POST",
                    "/api/exports/daily-plans",
                    body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                    headers=headers,
                )
                response = connection.getresponse()
                return (
                    response.status,
                    {k.lower(): v for k, v in response.getheaders()},
                    response.read(),
                )
            finally:
                connection.close()

        status, response_headers, payload = one_call(body)
        if status == 409:
            details = json.loads(payload.decode("utf-8"))["error"]["details"]
            status, response_headers, payload = one_call(
                {
                    **body,
                    "ack_missing": True,
                    "expected_context": details["expected_context"],
                }
            )
        self.assertEqual(status, 200, payload)
        return payload, response_headers

    def plan_content(self, plan_id=None):
        status, plan = self.client.get(f"/api/daily-plans/{plan_id or self.plan['id']}")
        self.assertEqual(status, 200, plan)
        return plan

    def _adopt(self, candidate_id, selected, edited):
        status, preview = self.preview_http(candidate_id, selected, edited)
        self.assertEqual(status, 200, preview)
        status, adopted = self.adopt_http(
            candidate_id, preview["preview_token"], request_id=str(uuid.uuid4())
        )
        self.assertEqual(status, 200, adopted)
        return adopted

    def cold_restart(self) -> None:
        """Release the runtime lock/engine and re-prepare on the same root."""
        self.server.stop()
        try:
            self.session.close()
        except Exception:  # noqa: BLE001 - already closed
            pass
        self.runtime.dispose()
        self.runtime = self.make_runtime(self.data_dir)
        self.session = self.runtime.session()
        self.addCleanup(self.session.close)
        self.server = self.start_server(self.runtime)
        self.client = self.server.client()

    # -- the closure -------------------------------------------------------
    def test_g14_full_closure_baseline_and_redline(self):
        plan_id = self.plan["id"]

        # 1) split candidate -> preview edit process (P1) -> adopt. The baseline
        #    must be the MODEL process (P0), never the teacher's preview edit.
        split_id = self.generate(plan_id, "daily_lesson_split", SPLIT_CANDIDATE)
        edited = json.loads(json.dumps(SPLIT_CANDIDATE))
        edited["group_activity"]["process"] = P1
        self._adopt(split_id, ["group_activity"], edited)
        content = self.plan_content()["content"]
        self.assertEqual(
            content["split_baseline"], {BASELINE_KEY: P0},
            "baseline must be the MODEL process, not the preview edit",
        )
        self.assertEqual(content["adopted_content"]["group_activity"]["process"], P1)

        # 2) adapt (age-appropriate) -> adopt; only the process changes.
        adapt_id = self.generate(plan_id, "daily_process_adapt", ADAPT_CANDIDATE)
        self._adopt(adapt_id, ["group_activity.process"], ADAPT_CANDIDATE)
        content = self.plan_content()["content"]
        self.assertEqual(content["adopted_content"]["group_activity"]["process"], P2)
        self.assertEqual(
            content["split_baseline"], {BASELINE_KEY: P0},
            "adapt must keep the original baseline",
        )

        # 3) teacher manual edit of the process, then save.
        adopted = json.loads(json.dumps(content["adopted_content"]))
        adopted["group_activity"]["process"] = P3
        status, saved = self.client.patch(
            f"/api/daily-plans/{plan_id}",
            {
                "expected_content_version": self.content_version(plan_id),
                "adopted_content": adopted,
            },
        )
        self.assertEqual(status, 200, saved)
        content = self.plan_content()["content"]
        self.assertEqual(content["adopted_content"]["group_activity"]["process"], P3)
        self.assertEqual(
            content["split_baseline"], {BASELINE_KEY: P0},
            "manual save must inherit the original baseline",
        )
        saved_version = self.content_version(plan_id)

        # 4) cold restart (lock released, engine disposed, re-prepared) reads
        #    the same baseline and content.
        self.cold_restart()
        content = self.plan_content()["content"]
        self.assertEqual(content["adopted_content"]["group_activity"]["process"], P3)
        self.assertEqual(content["split_baseline"], {BASELINE_KEY: P0})

        # 5) single-day export of the saved version: real redline structure.
        payload, headers = self.export_docx(DAY_ISO, DAY_ISO)
        self.assertEqual(payload[:2], b"PK")
        self.assertEqual(
            headers["content-type"],
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        # Export never bumps or re-saves the plan.
        self.assertEqual(self.content_version(plan_id), saved_version)

        root = docx_root(payload)
        red_text, plain_text = red_and_plain_text(root)
        # The unchanged prefix paragraphs stay non-red.
        self.assertIn("一、导入", plain_text)
        self.assertIn("二、观察", plain_text)
        # The teacher's added paragraph is red.
        self.assertIn("四、教师补充", red_text)

        # 6) merged export over two real plans: both titles/content present and
        #    each plan starts on a new page.
        second = self.make_plan(
            plan_date=DAY2, raw="W6 第二日原文", adopted={"reflection": "第二日反思"}
        )
        merged_payload, _merged_headers = self.export_docx(DAY_ISO, DAY2_ISO)
        merged_root = docx_root(merged_payload)
        merged_text = all_text(merged_root)
        self.assertEqual(merged_text.count("一日活动计划"), 2, merged_text[:200])
        self.assertIn("9 月 2 日", merged_text)
        self.assertIn("9 月 3 日", merged_text)
        self.assertIn("四、教师补充", merged_text)  # first plan content
        self.assertIn("第二日反思", merged_text)  # second plan content
        page_breaks = [
            br
            for br in merged_root.findall(f".//{W}br")
            if br.get(f"{W}type") == "page"
        ]
        self.assertGreaterEqual(len(page_breaks), 1, "merged export needs a page break")
        self.assertTrue(second["id"])

    def test_redline_rules_pure_delete_move_format(self):
        # Pure delete: removed text is not shown and nothing turns red.
        deleted = diff_process("第一段\n第二段", "第一段")
        self.assertNotIn("第二段", "".join(run["text"] for run in deleted["runs"]))
        self.assertFalse(any(run["red"] for run in deleted["runs"]))

        # Pure move: reordered paragraphs are not red.
        moved = diff_process("第一段\n第二段", "第二段\n第一段")
        self.assertFalse(any(run["red"] for run in moved["runs"]))

        # Format-only change (leading/trailing whitespace) is not red.
        formatted = diff_process("第一段", "  第一段  ")
        self.assertFalse(any(run["red"] for run in formatted["runs"]))

        # A real replacement and an insertion are red.
        replaced = diff_process("第一段", "第一段（新）")
        self.assertTrue(any(run["red"] for run in replaced["runs"]))
        inserted = diff_process("第一段", "第一段\n新增段")
        self.assertTrue(any(run["red"] for run in inserted["runs"]))
        self.assertIn("新增段", "".join(run["text"] for run in inserted["runs"]))

    def test_manual_plan_without_baseline_exports_with_warning(self):
        self.make_plan(plan_date=date(2026, 9, 4), raw="手工原文", adopted={"reflection": "手工"})
        _payload, headers = self.export_docx("2026-09-04", "2026-09-04")
        warnings = json.loads(headers["x-export-warnings"])
        self.assertIn("no_split_baseline", [w["code"] for w in warnings])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
