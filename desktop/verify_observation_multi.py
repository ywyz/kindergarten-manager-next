"""Real-window multi-page selection/order/mixed export verification.

Called from d1_main's ``obs-ui`` selftest phase with the real WebView2 driver
and protected local HTTP API.  Synthetic records are created through the
protected API; selections and ordering use the rendered checkbox/button DOM.
"""

from __future__ import annotations

import json
import time
import uuid
import zipfile
import http.client as http_client
import io
from pathlib import Path

from PIL import Image
import lxml.etree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"


def make_payload(index: int) -> dict:
    return {
        "observation_date": f"2026-09-{index + 1:02d}",
        "start_time": f"09:{index:02d}",
        "end_time": "09:30",
        "adult_count": 2,
        "child_count": 6,
        "observer_name": "OBS教师",
        "age_years": 5,
        "subjects": [{"name": f"多页幼儿{index}"}],
        "environment": "多页合成区",
        "observation_goal": "跨页选集观察目标",
        "observation_process": f"跨页选集正文 {index}",
        "analysis_evaluation": {
            "health": "健康",
            "language": "语言",
            "social": "社会",
            "science": "科学",
            "arts": "艺术",
        },
        "support_strategy": "跨页选集支持策略",
    }


def run_multi_export(driver, http, summary, checks, host_api, port) -> None:
    created_ids = []
    for index in range(24):
        record_type = ("public", "indoor", "outdoor")[index % 3]
        payload = make_payload(index)
        status, created = http(
            "POST",
            "/api/observations",
            {
                "request_id": str(uuid.uuid4()),
                "record_type": record_type,
                "payload": payload,
            },
        )
        assert status == 201, f"multi create failed: {status} {created}"
        created_ids.append(created["observation_id"])

    def upload_photo(observation_id: str, expected_revision: int) -> dict:
        image = Image.new("RGB", (640, 480), (200, 60, 60))
        buffer = io.BytesIO()
        image.save(buffer, "JPEG", quality=90)
        boundary = "----kgm" + uuid.uuid4().hex
        body = bytearray()
        for key, value in {
            "request_id": str(uuid.uuid4()),
            "expected_revision": str(expected_revision),
            "display_name": "multi-photo.jpg",
        }.items():
            body += (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'
                f"{value}\r\n"
            ).encode("utf-8")
        body += (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="multi-photo.jpg"\r\n'
            "Content-Type: image/jpeg\r\n\r\n"
        ).encode("utf-8")
        body += buffer.getvalue() + b"\r\n"
        body += f"--{boundary}--\r\n".encode("utf-8")
        token = getattr(host_api, "_launch_token", "")
        connection = http_client.HTTPConnection("127.0.0.1", port, timeout=60)
        try:
            connection.request(
                "POST",
                f"/api/observations/{observation_id}/photos",
                body=bytes(body),
                headers={
                    "Host": f"127.0.0.1:{port}",
                    "Origin": f"http://127.0.0.1:{port}",
                    "X-App-Session": token,
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                },
            )
            response = connection.getresponse()
            raw = response.read()
            status = response.status
        finally:
            connection.close()
        assert status == 201, f"multi photo upload failed: {status} {raw[:200]}"
        return json.loads(raw.decode("utf-8"))

    photo_payload = make_payload(100)
    photo_payload["observation_date"] = "2026-09-05"
    photo_payload["start_time"] = "09:50"
    photo_payload["record_type"] = "outdoor"
    photo_payload["subjects"] = [{"name": "多页照片"}]
    status, photo_created = http(
        "POST",
        "/api/observations",
        {
            "request_id": str(uuid.uuid4()),
            "record_type": "outdoor",
            "payload": photo_payload,
        },
    )
    assert status == 201, f"multi photo create failed: {status} {photo_created}"
    photo_id = photo_created["observation_id"]
    status, photo_current = http("GET", f"/api/observations/{photo_id}")
    assert status == 200, f"multi photo read failed: {status}"
    uploaded = upload_photo(photo_id, photo_current["revision"])
    status, photo_current = http("GET", f"/api/observations/{photo_id}")
    assert status == 200, f"multi photo reread failed: {status}"
    save_payload = {
        key: value
        for key, value in photo_current["payload"].items()
        if key != "term_snapshot"
    }
    status, photo_saved = http(
        "PATCH",
        f"/api/observations/{photo_id}",
        {
            "request_id": str(uuid.uuid4()),
            "expected_revision": photo_current["revision"],
            "payload": save_payload,
            "photos": [{"asset_id": uploaded["asset_id"], "caption": None}],
            "save_reason": "manual",
            "term_decision": "keep_current",
        },
    )
    assert status == 200, f"multi photo save failed: {status} {photo_saved}"

    driver.eval("window.__d1Observations.clearSelected()")
    driver.eval("window.__d1Observations.setMonth('2026-09')")
    driver.eval("window.__d1Observations.reload()")
    driver.wait_until(
        "window.__d1Observations.total() >= 25",
        what="OBS 多页记录就绪",
        timeout=30,
    )
    summary["obs_multi_stage"] = "first_page"
    summary["obs_multi_photo_id"] = photo_id
    summary["obs_multi_items_debug"] = driver.eval(
        "window.__d1Observations.items().map(x => ({id: x.observation_id, date: x.observation_date}))"
    )
    first_page_ids = driver.eval(
        "window.__d1Observations.items().slice(0, 10).map(x => x.observation_id)"
    )
    def click_type_select() -> None:
        driver.eval(
            "(() => { const root = document.querySelector('[data-d1=\"obs-type\"]');"
            " const target = (root && root.querySelector('.el-select__wrapper')) || root;"
            " if (target) target.click(); return Boolean(target); })()"
        )

    def click_checkbox(observation_id: str) -> bool:
        return bool(
            driver.eval(
                "(() => { const el = document.querySelector('[data-d1="
                + json.dumps("obs-select-" + observation_id)
                + "]'); const input = el && el.querySelector('input');"
                " if (!el) return false; (input || el).click(); return true; })()"
            )
        )

    missing_checkboxes = [
        observation_id
        for observation_id in first_page_ids
        if not click_checkbox(observation_id)
    ]
    summary["obs_multi_missing_checkboxes"] = missing_checkboxes
    assert not missing_checkboxes, f"missing checkboxes: {missing_checkboxes}"
    driver.wait_until(
        "window.__d1Observations.selectedCount() === 10",
        what="OBS 第一页勾选",
        timeout=20,
    )
    first_page_first = first_page_ids[0]
    driver.eval("document.querySelector('[data-d1=\"obs-next\"]').click()")
    driver.wait_until(
        "(() => { const ids = window.__d1Observations.items().map(x => x.observation_id);"
        " return ids.length > 0 && ids[0] !== "
        + json.dumps(first_page_first)
        + " && ids.every(id => !"
        + json.dumps(first_page_ids)
        + ".includes(id)); })()",
        what="OBS 第二页稳定身份",
        timeout=20,
    )
    second_page_ids = driver.eval(
        "window.__d1Observations.items().map(x => x.observation_id)"
    )
    assert second_page_ids, "second page has no items"
    for observation_id in second_page_ids:
        click_checkbox(observation_id)
    expected_selected = 10 + len(second_page_ids)
    if not driver.eval(
        "window.__d1Observations.selectedIds().includes("
        + json.dumps(photo_id)
        + ")"
    ):
        click_checkbox(photo_id)
        expected_selected += 1
    driver.wait_until(
        "window.__d1Observations.selectedCount() === "
        + json.dumps(expected_selected),
        what="OBS 跨页勾选精确计数",
        timeout=20,
    )
    driver.wait_until(
        "window.__d1Observations.selectedIds().includes("
        + json.dumps(photo_id)
        + ")",
        what="OBS 勾选带照片记录",
        timeout=20,
    )
    # Change the real date filter: the explicit selection must survive.
    summary["obs_multi_stage"] = "month"
    driver.eval("document.querySelector('[data-d1=\"obs-this-month\"]').click()")
    driver.wait_until(
        "window.__d1Observations.selectedCount() === "
        + json.dumps(expected_selected),
        what="OBS 筛选后选集保留",
        timeout=20,
    )
    summary["obs_multi_stage"] = "all_dates"
    driver.eval("document.querySelector('[data-d1=\"obs-all-dates\"]').click()")
    driver.wait_until(
        "window.__d1Observations.total() >= 25",
        what="OBS 日期筛选重置",
        timeout=20,
    )
    before_order = driver.eval("window.__d1Observations.selectedIds()")
    first_id = before_order[0]
    summary["obs_multi_stage"] = "down"
    driver.eval(
        "document.querySelector('[data-d1="
        + json.dumps("obs-selected-down-" + first_id)
        + "]').click()"
    )
    driver.wait_until(
        "window.__d1Observations.selectedIds()[0] !== "
        + json.dumps(first_id),
        what="OBS 手调顺序",
        timeout=20,
    )
    selected_order = driver.eval("window.__d1Observations.selectedIds()")
    status, listed = http("GET", "/api/observations?limit=100")
    assert status == 200, f"multi list failed: {status}"
    by_id = {item["observation_id"]: item for item in listed["items"]}
    labels = {"public": "公共", "indoor": "室内", "outdoor": "户外"}
    expected_titles = [
        "OBS园所游戏观察记录（" + labels[by_id[item]["record_type"]] + "）"
        for item in selected_order
    ]
    expected_subjects = [
        "、".join(by_id[item].get("subjects") or []) for item in selected_order
    ]
    summary["obs_multi_stage"] = "export_open"
    driver.eval("document.querySelector('[data-d1=\"obs-export-open\"]').click()")
    driver.wait_until(
        "window.__d1Observations.exportPhase() === 'preview_ready'",
        what="OBS 多页导出预览",
        timeout=60,
    )
    driver.eval("window.__d1Observations.setExportAck(true)")
    driver.eval("window.__d1Observations.confirmExport(false)")
    driver.wait_until(
        "window.__d1Observations.exportPhase() === 'saved'",
        what="OBS 多页导出保存",
        timeout=90,
    )
    save_dir = getattr(host_api, "_verify_save_dir", None)
    assert save_dir is not None, "multi export save dir missing"
    files = sorted(
        Path(save_dir).glob("*.docx"),
        key=lambda item: item.stat().st_mtime,
    )
    assert files, "multi export did not write a DOCX"
    saved = files[-1]
    with zipfile.ZipFile(saved) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
        body = root.find(W + "body")
        titles = [
            "".join(node.text or "" for node in paragraph.iter(W + "t"))
            for paragraph in body.findall(W + "p")
        ]
        actual_subjects = []
        for table in body.findall(W + "tbl"):
            rows = table.findall(W + "tr")
            cells = rows[2].findall(W + "tc") if len(rows) >= 3 else []
            actual_subjects.append(
                "".join(node.text or "" for node in cells[1].iter(W + "t"))
                if len(cells) >= 2
                else ""
            )
        inline = len(root.findall(".//" + WP + "inline"))
        doc_pr = len(root.findall(".//" + WP + "docPr"))
    assert titles == expected_titles, (
        "multi export title/order mismatch: " + repr(titles[:3])
    )
    assert actual_subjects == expected_subjects, (
        "multi export subject/order mismatch: "
        + repr(actual_subjects[:3])
        + " != "
        + repr(expected_subjects[:3])
    )
    assert inline == 1 and doc_pr == 1, (
        f"multi export photos inline={inline} docPr={doc_pr}"
    )
    checks["obs_multi_export"] = True
    checks["obs_multi_export_order"] = True
    checks["obs_multi_export_photos"] = True
    summary["obs_multi_export"] = {
        "selected": len(selected_order),
        "titles": len(titles),
        "photos": inline,
        "file": saved.name,
    }
    driver.eval("window.__d1Observations.closeExport()")
    driver.wait_until(
        "window.__d1Observations.exportOpen() === false"
        " && window.__d1Observations.exportBusy() === false",
        what="OBS 多页导出关闭",
        timeout=20,
    )
    deadline = time.time() + 10
    while time.time() < deadline and getattr(host_api, "_page_busy", False):
        time.sleep(0.1)
    checks["obs_multi_export_busy_cleared"] = not bool(
        getattr(host_api, "_page_busy", False)
    )
