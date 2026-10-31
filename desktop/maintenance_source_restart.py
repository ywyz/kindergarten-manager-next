"""B3 new-process continuation check (real new process, not load_url)."""

from __future__ import annotations

import threading
import traceback
from pathlib import Path
from typing import Any

from maintenance_lifecycle import LifecycleManager


def run_restart_driver(
    window,
    host_api,
    runtime,
    lifecycle: LifecycleManager,
    config: dict[str, Any],
    summary: dict[str, Any],
    checks: dict[str, Any],
    source: dict[str, Any],
    out_path: Path,
    finished: threading.Event,
    dialog_stub=None,
    dialog_calls=None,
) -> None:
    import d1_main
    from maintenance_source_verify import (
        _cleanup_unswitched_maintenance,
        _destroy_owned_windows,
        _js_click,
        _js_click_visible,
        _js_visible,
        _js_visible_enabled,
        _write_summary,
    )

    driver = d1_main.JsDriver(window)
    destroy_ok = False

    import sqlite3

    def _version_counts(db_path: str) -> tuple[int, int]:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            count, max_version = con.execute(
                "select count(*), coalesce(max(version),0)"
                " from local_daily_plan_contents"
            ).fetchone()
            return int(count), int(max_version)
        finally:
            con.close()

    try:
        checks["restart_existing_target"] = True
        checks["restart_versions_before"] = _version_counts(runtime.db_path)
        driver.wait_until(
            "Boolean(document.querySelector('[data-d1=\"calendar\"]'))",
            what="新进程工作台",
            timeout=60,
        )
        checks["restart_workbench"] = True
        term_selector = (
            "[data-d1^=\"term-\"]:not([data-d1=\"term-all\"])"
        )
        driver.wait_until(
            "Boolean(document.querySelector('" + term_selector + "'))",
            what="新进程学期入口",
            timeout=30,
        )
        assert _js_click_visible(driver, term_selector)
        driver.wait_until(
            "Boolean(document.querySelector('[data-d1=\"plan-list\"] [data-d1=\"open-plan\"]'))",
            what="新进程计划列表",
            timeout=30,
        )
        assert _js_click_visible(
            driver, '[data-d1="plan-list"] [data-d1="open-plan"]'
        )
        driver.wait_until(
            "Boolean(document.querySelector('[data-d1=\"editor\"]'))"
            " && Boolean(window.__d1Editor && window.__d1Editor.phase() === 'ready')",
            what="新进程编辑器",
            timeout=60,
        )
        checks["restart_plan_opened"] = True
        raw = driver.eval("window.__d1Editor.raw()")
        expected_marker = str(
            config.get("restart_expected_marker")
            or "B3 POST RESTORE SAVED BODY 2026-10-31"
        )
        checks["restart_expected_marker"] = expected_marker
        checks["restart_body_marker"] = (
            isinstance(raw, str) and expected_marker in raw
        )
        assert checks["restart_body_marker"], raw
        checks["restart_versions_after_open"] = _version_counts(runtime.db_path)
        if config.get("restart_require_stable_versions"):
            checks["restart_versions_stable"] = (
                checks["restart_versions_after_open"]
                == checks["restart_versions_before"]
            )
            assert checks["restart_versions_stable"], (
                checks["restart_versions_before"],
                checks["restart_versions_after_open"],
            )
        save_marker = str(config.get("restart_user_save_marker") or "")
        if save_marker:
            driver.eval(
                "window.__d1Editor.setText("
                + repr(save_marker)
                + ", 'B3 RESTART USER REFLECTION')"
            )
            driver.wait_until(
                "Boolean(window.__d1Editor && window.__d1Editor.dirty())"
                " || Boolean(document.querySelector('[data-d1=\"dirty\"]'))",
                what="重启后用户编辑未保存标记",
                timeout=30,
            )
            assert _js_visible_enabled(driver, '[data-d1="manual-save"]')
            assert _js_click_visible(driver, '[data-d1="manual-save"]')
            driver.wait_until(
                "!document.querySelector('[data-d1=\"dirty\"]')",
                what="重启后用户保存完成",
                timeout=90,
            )
            checks["restart_user_save"] = True
            checks["restart_versions_after_save"] = _version_counts(runtime.db_path)
            before_count, before_max = checks["restart_versions_after_open"]
            after_count, after_max = checks["restart_versions_after_save"]
            checks["restart_only_user_version_added"] = (
                after_count == before_count + 1 and after_max == before_max + 1
            )
            assert checks["restart_only_user_version_added"], (
                checks["restart_versions_after_open"],
                checks["restart_versions_after_save"],
            )
            raw_after = driver.eval("window.__d1Editor.raw()")
            checks["restart_saved_marker_visible"] = (
                isinstance(raw_after, str) and save_marker in raw_after
            )
            assert checks["restart_saved_marker_visible"]
        destroy_ok = _destroy_owned_windows([window], force=False)
        checks["driver_destroy_confirmed"] = destroy_ok
    except Exception as exc:  # noqa: BLE001
        checks["driver_error"] = f"{type(exc).__name__}: {exc}"
        checks["driver_trace"] = traceback.format_exc()
        summary["ok"] = False
        try:
            checks["failure_body_text"] = driver.eval("document.body.innerText")
            checks["failure_buttons"] = driver.eval(
                "JSON.stringify([...document.querySelectorAll('button')].map(b=>({"
                "text:(b.innerText||'').trim(),disabled:!!b.disabled,"
                "visible:(()=>{const r=b.getBoundingClientRect();return r.width>0&&r.height>0})()"
                "})))"
            )
            if dialog_calls is not None:
                checks["failure_dialog_calls"] = list(dialog_calls)
        except Exception:  # noqa: BLE001
            pass
        _write_summary(summary, out_path)
        checks["driver_cleanup_cancelled"] = _cleanup_unswitched_maintenance(host_api)
        try:
            if not host_api._maintenance_busy_probe():
                host_api._request_retire_destroy()
        except Exception:  # noqa: BLE001
            pass
        destroy_ok = _destroy_owned_windows([window], force=True)
        checks["driver_destroy_confirmed"] = destroy_ok
    finally:
        if destroy_ok:
            finished.set()
