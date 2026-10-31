"""B3 post-restore UI checks: editor save, history, photos, Word export."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def run_post_checks(driver, host_api, source: dict[str, Any], config: dict[str, Any], checks: dict[str, Any]) -> None:
    from maintenance_source_verify import (
        _js_click,
        _js_click_visible,
        _js_visible,
        _js_visible_enabled,
    )

    # Select the restored term so its plan list is actually populated.
    evidence = source.get("evidence")
    term_id = str(getattr(evidence, "term_id", "") or "")
    assert term_id, "source evidence missing term_id"
    term_selector = f'[data-d1="term-{term_id}"]'
    assert _js_visible_enabled(driver, term_selector)
    assert _js_click_visible(driver, term_selector)
    driver.wait_until(
        "Boolean(document.querySelector('[data-d1=\"plan-list\"] [data-d1=\"open-plan\"]'))",
        what="恢复后计划列表",
        timeout=60,
    )
    assert _js_click_visible(driver, '[data-d1="plan-list"] [data-d1="open-plan"]')
    driver.wait_until(
        "Boolean(document.querySelector('[data-d1=\"editor\"]'))",
        what="恢复后编辑器",
        timeout=60,
    )
    driver.wait_until(
        "Boolean(window.__d1Editor && window.__d1Editor.phase() === 'ready')",
        what="编辑器就绪",
        timeout=60,
    )
    checks["post_editor_opened"] = True

    marker = "B3 POST RESTORE SAVED BODY 2026-10-31"
    driver.eval(
        "window.__d1Editor.setText("
        + repr(marker)
        + ", 'B3 POST RESTORE REFLECTION')"
    )
    driver.wait_until(
        "Boolean(window.__d1Editor && window.__d1Editor.dirty())"
        " || Boolean(document.querySelector('[data-d1=\"dirty\"]'))",
        what="编辑后未保存标记",
        timeout=30,
    )
    checks["post_dirty"] = True
    assert _js_visible_enabled(driver, '[data-d1="manual-save"]')
    assert _js_click_visible(driver, '[data-d1="manual-save"]')
    driver.wait_until(
        "!document.querySelector('[data-d1=\"dirty\"]')",
        what="手工保存完成",
        timeout=90,
    )
    checks["post_saved"] = True

    # History list/detail through the real editor panel.
    assert _js_click_visible(driver, '[data-d1="open-history"]')
    driver.wait_until(
        "Boolean(document.querySelector('[data-d1=\"history-panel\"]'))",
        what="历史面板",
        timeout=30,
    )
    driver.wait_until(
        "Boolean(document.querySelector('[data-d1=\"history-select-1\"]'))",
        what="历史版本入口",
        timeout=30,
    )
    assert _js_click_visible(driver, '[data-d1="history-select-1"]')
    driver.wait_until(
        "Boolean(document.querySelector('[data-d1=\"history-detail\"]'))"
        " || Boolean(document.querySelector('[data-d1=\"history-compare\"]'))",
        what="历史详情",
        timeout=30,
    )
    checks["post_history_detail"] = True
    checks["post_history_source_text"] = driver.eval(
        "document.querySelector('[data-d1=\"history-panel\"]').innerText"
    )
    checks["post_history_source_visible"] = (
        "保存记录" in str(checks["post_history_source_text"])
        or "从 v" in str(checks["post_history_source_text"])
    )
    assert _js_click(driver, '[data-d1="history-close"]')

    # Observation list, editor and decoded photos.
    assert _js_click_visible(driver, '[data-d1="back-calendar"]')
    driver.wait_until(
        "Boolean(document.querySelector('[data-d1=\"calendar\"]'))",
        what="返回日历",
        timeout=30,
    )
    assert _js_click_visible(driver, '[data-d1="open-observations"]')
    driver.wait_until(
        "Boolean(document.querySelector('[data-d1=\"observations\"]'))",
        what="观察列表",
        timeout=30,
    )
    driver.wait_until(
        "Boolean(document.querySelector('[data-d1=\"obs-list\"] [data-d1=\"obs-open\"]'))",
        what="观察记录入口",
        timeout=30,
    )
    assert _js_click_visible(driver, '[data-d1="obs-list"] [data-d1="obs-open"]')
    driver.wait_until(
        "Boolean(document.querySelector('[data-d1=\"obs-editor\"]'))",
        what="观察编辑器",
        timeout=60,
    )
    driver.wait_until(
        "(()=>{const imgs=[...document.querySelectorAll('[data-d1=\"obs-photos\"] img')];"
        " return imgs.length>0 && imgs.every(i=>i.naturalWidth>0);})()",
        what="观察照片实际解码",
        timeout=60,
    )
    checks["post_obs_photos"] = True
    assert _js_click_visible(driver, '[data-d1="obs-open-history"]')
    driver.wait_until(
        "Boolean(document.querySelector('[data-d1=\"obs-history\"]'))",
        what="观察历史面板",
        timeout=30,
    )
    driver.wait_until(
        "Boolean(document.querySelector('[data-d1=\"obs-history-1\"]'))",
        what="观察历史版本",
        timeout=30,
    )
    assert _js_click(driver, '[data-d1="obs-history-1"]')
    driver.wait_until(
        "Boolean(document.querySelector('[data-d1=\"obs-history-photos\"]'))",
        what="观察历史照片",
        timeout=30,
    )
    driver.wait_until(
        "(()=>{const p=document.querySelector('[data-d1=\"obs-history-photos\"]');"
        " const imgs=[...p.querySelectorAll('img')]; return imgs.length>0"
        " && imgs.every(i=>i.naturalWidth>0);})()",
        what="观察历史照片实际解码",
        timeout=60,
    )
    checks["post_history_photos"] = True
    checks["post_history_photo_text"] = driver.eval(
        "document.querySelector('[data-d1=\"obs-history-photos\"]').innerText"
    )
    assert _js_click(driver, '[data-d1="obs-history"] .el-dialog__headerbtn')

    # Return to workbench, reopen plan, export through the real dialog.
    assert _js_click(driver, '[data-d1="obs-back-list"]')
    driver.wait_until(
        "Boolean(document.querySelector('[data-d1=\"observations\"]'))",
        what="观察列表返回",
        timeout=30,
    )
    assert _js_click(driver, '[data-d1="obs-back"]')
    driver.wait_until(
        "Boolean(document.querySelector('[data-d1=\"calendar\"]'))",
        what="工作台返回",
        timeout=30,
    )
    assert _js_visible_enabled(driver, term_selector)
    assert _js_click_visible(driver, term_selector)
    driver.wait_until(
        "Boolean(document.querySelector('[data-d1=\"plan-list\"] [data-d1=\"open-plan\"]'))",
        what="导出前计划列表",
        timeout=30,
    )
    assert _js_click_visible(driver, '[data-d1="plan-list"] [data-d1="open-plan"]')
    driver.wait_until(
        "Boolean(document.querySelector('[data-d1=\"editor\"]'))",
        what="导出前编辑器",
        timeout=30,
    )
    assert _js_click_visible(driver, '[data-d1="open-export"]')
    driver.wait_until(
        "Boolean(document.querySelector('[data-d1=\"export-dialog\"]'))",
        what="导出对话框",
        timeout=30,
    )
    assert _js_click_visible(driver, '[data-d1="export-run"]')
    driver.wait_until(
        "Boolean(document.querySelector('[data-d1=\"export-result\"]'))"
        " || Boolean(document.querySelector('[data-d1=\"export-ack\"]'))"
        " || Boolean(document.querySelector('[data-d1=\"query-save-result\"]'))",
        what="导出结果或确认",
        timeout=120,
    )
    if _js_visible(driver, '[data-d1="export-ack"]'):
        assert _js_click(driver, '[data-d1="export-ack"]')
        assert _js_click_visible(driver, '[data-d1="export-run"]')
        driver.wait_until(
            "Boolean(document.querySelector('[data-d1=\"export-result\"]'))",
            what="导出最终结果",
            timeout=120,
        )
    checks["post_export_result"] = driver.eval(
        "document.querySelector('[data-d1=\"export-result\"]')"
        " ? document.querySelector('[data-d1=\"export-result\"]').innerText : null"
    )
    word_dir = Path(config["word_dir"])
    word_files = sorted(word_dir.glob("*.docx"))
    checks["post_word_files"] = [path.name for path in word_files]
    checks["post_word_saved"] = bool(
        word_files and word_files[0].stat().st_size > 0
        and word_files[0].read_bytes()[:2] == b"PK"
    )
    assert checks["post_word_saved"], checks["post_word_files"]
