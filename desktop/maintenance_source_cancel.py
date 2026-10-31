"""B3 cancel boundaries: verify-stage cancel and post-switch too-late cancel."""

from __future__ import annotations

import re
import threading
import time
import traceback
from pathlib import Path
from typing import Any

from maintenance_lifecycle import LifecycleManager


def run_cancel_driver(
    window,
    host_api,
    runtime,
    lifecycle: LifecycleManager,
    config: dict[str, Any],
    summary: dict[str, Any],
    checks: dict[str, Any],
    source: dict[str, Any],
    target_pre: dict[str, Any],
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
        _js_set_input,
        _js_visible,
        _js_visible_enabled,
        _write_summary,
    )

    driver = d1_main.JsDriver(window)
    new_window = None
    destroy_ok = False
    old_generation = lifecycle.current().generation
    try:
        from tests.local import backup_fixture_support as fixture

        pre_db = fixture.database_fingerprint(
            runtime.db_path, include_runtime_fields=True
        )
        pre_business = fixture.database_fingerprint(runtime.db_path)
        pre_resources = fixture.resource_fingerprint(config["data_dir"])
        maintenance = getattr(host_api, "_maintenance_host", None)
        assert maintenance is not None

        driver.wait_until(
            "Boolean(window.__d1App && window.__d1App.state() === 'ready')",
            what="取消边界页面",
            timeout=60,
        )
        assert _js_click_visible(driver, '[data-d1="open-settings"]')
        driver.wait_until(
            "Boolean(document.querySelector('[data-d1=\"open-backup-restore\"]'))",
            what="设置页",
            timeout=30,
        )

        def open_panel() -> None:
            for attempt in (1, 2):
                assert _js_visible_enabled(driver, '[data-d1="open-backup-restore"]')
                assert _js_click_visible(driver, '[data-d1="open-backup-restore"]')
                try:
                    driver.wait_until(
                        "Boolean(document.querySelector('[data-d1=\"backup-restore-panel\"]'))",
                        what="维护面板",
                        timeout=10,
                    )
                    return
                except Exception:  # noqa: BLE001 - bounded UI settle retry
                    checks[f"cancel_panel_attempt_{attempt}"] = driver.eval(
                        "document.body.innerText"
                    )
            raise AssertionError("维护面板未打开")

        def start_verify() -> None:
            assert _js_click_visible(
                driver,
                '[data-d1="backup-restore-panel"] [data-d1="backup-restore"]',
            )
            driver.wait_until(
                "Boolean(document.querySelector('[data-d1=\"backup-password\"]'))"
                " || Boolean(document.querySelector('[data-d1=\"backup-preview\"]'))",
                what="恢复密码",
                timeout=120,
            )
            if _js_visible(driver, '[data-d1="backup-password"]'):
                assert _js_set_input(
                    driver,
                    '[data-d1="backup-password"]',
                    str(config["source_password"]),
                )
                assert _js_click_visible(
                    driver, '[data-d1="backup-password-submit"]'
                )

        open_panel()
        start_verify()
        driver.wait_until(
            "Boolean(document.querySelector('[data-d1=\"backup-preview\"]'))"
            " || Boolean(document.querySelector('[data-d1=\"backup-error\"]'))",
            what="取消前预览",
            timeout=240,
        )
        assert not _js_visible(driver, '[data-d1="backup-error"]')
        preview_op = next(
            (
                item
                for item in maintenance._ops.values()
                if item.get("kind") == "restore" and item.get("phase") == "preview"
            ),
            None,
        )
        assert preview_op is not None
        checks["cancel_preview_phase_ready"] = True
        checks["cancel_verify_phase"] = preview_op.get("phase")
        assert _js_visible_enabled(driver, '[data-d1="backup-preview-cancel"]')
        assert _js_click_visible(driver, '[data-d1="backup-preview-cancel"]')
        driver.wait_until(
            "Boolean(document.querySelector('[data-d1=\"backup-cancelled\"]'))",
            what="预览取消终态",
            timeout=120,
        )
        checks["cancel_preview_ui_cancelled"] = True
        checks["cancel_preview_no_switch"] = (
            lifecycle.current().generation == old_generation
            and window in __import__("webview").windows
        )
        target_db = fixture.database_fingerprint(
            runtime.db_path, include_runtime_fields=True
        )
        target_business = fixture.database_fingerprint(runtime.db_path)
        target_resources = fixture.resource_fingerprint(config["data_dir"])
        checks["cancel_preview_target_unchanged"] = (
            target_db["fingerprint_sha256"] == pre_db["fingerprint_sha256"]
            and target_business["fingerprint_sha256"]
            == pre_business["fingerprint_sha256"]
            and target_resources.get("fingerprint_sha256")
            == pre_resources.get("fingerprint_sha256")
        )
        assert checks["cancel_preview_no_switch"]
        assert checks["cancel_preview_target_unchanged"]
        assert _js_click_visible(driver, '[data-d1="backup-cancelled-close"]')
        driver.wait_until(
            "!document.querySelector('[data-d1=\"backup-restore-panel\"]')",
            what="关闭取消面板",
            timeout=30,
        )

        open_panel()
        start_verify()
        driver.wait_until(
            "Boolean(document.querySelector('[data-d1=\"backup-preview\"]'))"
            " || Boolean(document.querySelector('[data-d1=\"backup-error\"]'))",
            what="第二次恢复预览",
            timeout=240,
        )
        assert not _js_visible(driver, '[data-d1="backup-error"]')
        op = next(
            (
                item
                for item in maintenance._ops.values()
                if item.get("kind") == "restore" and item.get("phase") == "preview"
            ),
            None,
        )
        assert op is not None
        op_id = str(op.get("operation_id") or "")
        op_generation = int(op.get("generation") or 0)
        assert op_id and op_generation
        original_mark = maintenance._mark_switching

        def delayed_mark():
            original_mark()
            time.sleep(1.0)

        maintenance._mark_switching = delayed_mark
        checks["cancel_switch_delay_injected"] = True
        assert _js_click(driver, '[data-d1="backup-confirm-check"]')
        assert _js_visible_enabled(driver, '[data-d1="backup-confirm-restore"]')
        assert _js_click_visible(driver, '[data-d1="backup-confirm-restore"]')

        deadline = time.monotonic() + 120
        ack = None
        while time.monotonic() < deadline:
            phase = op.get("phase")
            if phase in ("switching", "reopening"):
                ack = host_api.cancel_maintenance(
                    {"operation_id": op_id, "generation": op_generation}
                )
                checks["cancel_phase_at_probe"] = phase
                break
            if phase in ("completed", "error", "cancelled"):
                checks["cancel_phase_at_probe"] = phase
                break
            time.sleep(0.01)
        checks["cancel_too_late_ack"] = ack
        checks["cancel_too_late_not_cancelled"] = bool(
            isinstance(ack, dict)
            and ack.get("accepted") is False
            and ack.get("state") == "too_late"
        )
        assert checks["cancel_too_late_not_cancelled"], ack

        deadline = time.monotonic() + config["timeout"]
        new_bundle = None
        while time.monotonic() < deadline:
            current = lifecycle.current()
            if (
                current is not None
                and current.generation > old_generation
                and current.window is not None
            ):
                new_bundle = current
                break
            time.sleep(0.05)
        assert new_bundle is not None, "取消后切换未创建新窗口"
        new_window = new_bundle.window
        new_driver = d1_main.JsDriver(new_window)
        new_driver.wait_until(
            "Boolean(window.__d1App && window.__d1App.ready()"
            " && window.__d1App.state() === 'ready')",
            what="取消后新页面",
            timeout=120,
        )
        new_driver.wait_until(
            "Boolean(document.querySelector('[data-d1=\"calendar\"]'))",
            what="取消后新页业务 DOM",
            timeout=60,
        )
        checks["cancel_switch_completed"] = True
        checks["cancel_new_page_ready"] = True
        checks["cancel_not_shown_cancelled"] = not bool(
            new_driver.eval(
                "Boolean(document.querySelector('[data-d1=\"backup-cancelled\"]'))"
            )
        )
        notice = new_driver.eval(
            "document.querySelector('[data-d1=\"restore-notice\"]')"
            " ? document.querySelector('[data-d1=\"restore-notice\"]').innerText : ''"
        )
        checks["cancel_restore_notice"] = notice
        checks["cancel_protection_exists"] = False
        match = re.search(r"恢复前保护副本：(.+?)。", str(notice))
        if match:
            checks["cancel_protection_exists"] = Path(match.group(1)).is_file()
        assert checks["cancel_protection_exists"]

        target_db = fixture.database_fingerprint(
            runtime.db_path, include_runtime_fields=True
        )
        target_business = fixture.database_fingerprint(runtime.db_path)
        target_resources = fixture.resource_fingerprint(config["data_dir"])
        checks["database_equal_full"] = (
            target_db["fingerprint_sha256"] == source["database"]["fingerprint_sha256"]
        )
        checks["database_equal_business"] = (
            target_business["fingerprint_sha256"]
            == source["database_business"]["fingerprint_sha256"]
        )
        checks["resources_equal"] = (
            target_resources.get("fingerprint_sha256")
            == source["resources"].get("fingerprint_sha256")
        )
        assert checks["database_equal_full"]
        assert checks["resources_equal"]
        destroy_ok = _destroy_owned_windows([new_window, window])
        checks["driver_destroy_confirmed"] = destroy_ok
    except Exception as exc:  # noqa: BLE001
        checks["driver_error"] = f"{type(exc).__name__}: {exc}"
        checks["driver_trace"] = traceback.format_exc()
        summary["ok"] = False
        try:
            checks["failure_body_text"] = driver.eval("document.body.innerText")
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
        destroy_ok = _destroy_owned_windows([new_window, window], force=True)
        checks["driver_destroy_confirmed"] = destroy_ok
    finally:
        if destroy_ok:
            finished.set()
