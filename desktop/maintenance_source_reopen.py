"""B3 controlled reopen failure after a real committed restore."""

from __future__ import annotations

import re
import threading
import time
import traceback
from pathlib import Path
from typing import Any

from maintenance_lifecycle import LifecycleManager


def run_reopen_failure_driver(
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
        _js_visible,
        _js_visible_enabled,
        _write_summary,
    )

    driver = d1_main.JsDriver(window)
    destroy_ok = False
    try:
        from tests.local import backup_fixture_support as fixture

        pre_db = fixture.database_fingerprint(
            runtime.db_path, include_runtime_fields=True
        )
        pre_business = fixture.database_fingerprint(runtime.db_path)
        pre_resources = fixture.resource_fingerprint(config["data_dir"])
        driver.wait_until(
            "Boolean(window.__d1App && window.__d1App.state() === 'ready')",
            what="重开失败页面",
            timeout=60,
        )
        assert _js_click_visible(driver, '[data-d1="open-settings"]')
        driver.wait_until(
            "Boolean(document.querySelector('[data-d1=\"open-backup-restore\"]'))",
            what="设置页",
            timeout=30,
        )
        panel_attempts = 0
        while panel_attempts < 2:
            panel_attempts += 1
            assert _js_visible_enabled(driver, '[data-d1="open-backup-restore"]')
            assert _js_click_visible(driver, '[data-d1="open-backup-restore"]')
            try:
                driver.wait_until(
                    "Boolean(document.querySelector('[data-d1=\"backup-restore-panel\"]'))",
                    what="维护面板",
                    timeout=10,
                )
                break
            except Exception:  # noqa: BLE001 - bounded UI settle retry
                checks[f"reopen_panel_attempt_{panel_attempts}"] = driver.eval(
                    "document.body.innerText"
                )
        checks["reopen_panel_attempts"] = panel_attempts
        driver.wait_until(
            "Boolean(document.querySelector('[data-d1=\"backup-restore-panel\"]'))",
            what="维护面板",
            timeout=30,
        )
        assert _js_click_visible(
            driver, '[data-d1="backup-restore-panel"] [data-d1="backup-restore"]'
        )
        driver.wait_until(
            "Boolean(document.querySelector('[data-d1=\"backup-preview\"]'))"
            " || Boolean(document.querySelector('[data-d1=\"backup-error\"]'))",
            what="重开失败预览",
            timeout=120,
        )
        preview_text = driver.eval(
            "document.querySelector('[data-d1=\"backup-restore-panel\"]').innerText"
        )
        checks["reopen_preview_text"] = preview_text
        checks["reopen_preview_ready"] = (
            "恢复" in preview_text and "校验完成" in preview_text
        )
        assert checks["reopen_preview_ready"], preview_text
        assert not _js_visible(driver, '[data-d1="backup-error"]'), preview_text

        maintenance = getattr(host_api, "_maintenance_host", None)
        assert maintenance is not None
        op = next(
            (
                item
                for item in maintenance._ops.values()
                if item.get("kind") == "restore"
                and item.get("phase") == "preview"
            ),
            None,
        )
        assert op is not None
        operation_id = str(op.get("operation_id") or "")
        operation_generation = int(op.get("generation") or 0)
        assert operation_id and operation_generation

        called = {"value": False}
        mode = str(config.get("reopen_failure_mode") or "host")

        if mode == "service":
            import d1_main as _d1_main

            base_service = _d1_main.ServiceRun

            class FailingNewServiceRun(base_service):
                def start_and_wait(self):
                    return False

                def stop_and_confirm(self, timeout: float = 10.0):
                    return False

            _d1_main.ServiceRun = FailingNewServiceRun
            checks["reopen_service_failure_injected"] = True
            called["value"] = True
        else:

            def injected_reopen_failure():
                called["value"] = True
                return {
                    "state": "reopen_failed",
                    "code": "B3_INJECTED_REOPEN_FAILURE",
                }

            maintenance.reopen_host = injected_reopen_failure

        assert _js_click(driver, '[data-d1="backup-confirm-check"]')
        assert _js_visible_enabled(driver, '[data-d1="backup-confirm-restore"]')
        assert _js_click_visible(driver, '[data-d1="backup-confirm-restore"]')

        driver.wait_until(
            "Boolean(document.querySelector('[data-d1=\"backup-error\"]'))",
            what="重开失败错误视图",
            timeout=180,
        )
        checks["reopen_injected_failure_used"] = called["value"]
        assert checks["reopen_injected_failure_used"]
        status = host_api.query_maintenance(
            {
                "operation_id": operation_id,
                "generation": operation_generation,
            }
        )
        checks["reopen_status"] = status
        error_text = driver.eval(
            "document.querySelector('[data-d1=\"backup-error\"]').innerText"
        )
        checks["reopen_error_text"] = error_text
        checks["reopen_error_visible"] = bool(error_text)
        checks["reopen_error_message"] = (
            "资料已恢复，重新打开失败" in str(error_text)
            and "请重启应用" in str(error_text)
        )
        assert checks["reopen_error_message"], error_text
        protection_text = driver.eval(
            "document.querySelector('[data-d1=\"backup-protection-location-error\"]')"
            " ? document.querySelector('[data-d1=\"backup-protection-location-error\"]')"
            ".innerText : ''"
        )
        checks["reopen_protection_text"] = protection_text
        checks["reopen_protection_visible"] = "恢复前保护副本" in str(
            protection_text
        )
        assert checks["reopen_protection_visible"], protection_text
        notice_path = Path(
            re.search(r"恢复前保护副本：(.+?)。", str(protection_text)).group(1)
        )
        checks["reopen_protection_path"] = str(notice_path)
        checks["reopen_protection_exists"] = notice_path.is_file()
        assert checks["reopen_protection_exists"]

        checks["reopen_status_error"] = (
            isinstance(status, dict)
            and (status.get("status") or {}).get("phase") == "error"
            and ((status.get("status") or {}).get("error") or {}).get("code")
            == "REOPEN_FAILED"
        )
        assert checks["reopen_status_error"], status

        from app.local.backup_snapshot import SnapshotService

        verifier = SnapshotService(
            runtime, app_version="b3-reopen", source_identity={"b3": "reopen"}
        )
        verified = verifier.verify(notice_path, password=None, cancel=threading.Event())
        copy_db = fixture.database_fingerprint(
            verified.database_path, include_runtime_fields=True
        )
        copy_business = fixture.database_fingerprint(verified.database_path)
        copy_resources = fixture.resource_fingerprint(verified.resources_root)
        checks["reopen_protection_matches_pre_restore"] = (
            copy_db["fingerprint_sha256"] == pre_db["fingerprint_sha256"]
            and copy_business["fingerprint_sha256"]
            == pre_business["fingerprint_sha256"]
            and copy_resources.get("fingerprint_sha256")
            == pre_resources.get("fingerprint_sha256")
        )
        try:
            verifier.discard_verified(verified)
        except Exception:  # noqa: BLE001
            pass
        assert checks["reopen_protection_matches_pre_restore"]

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
        checks["reopen_data_committed"] = bool(
            checks["database_equal_full"] and checks["resources_equal"]
        )
        assert checks["reopen_data_committed"]

        import webview

        checks["reopen_old_window_kept"] = window in list(webview.windows)
        assert checks["reopen_old_window_kept"]
        checks["reopen_recovery_required"] = bool(
            getattr(maintenance, "_recovery_required", False)
            and host_api._recovery_required_probe()
        )
        assert checks["reopen_recovery_required"]

        assert _js_click_visible(driver, '[data-d1="backup-error-close"]')
        driver.wait_until(
            "!document.querySelector('[data-d1=\"backup-error\"]')",
            what="关闭重开失败面板",
            timeout=30,
        )
        checks["reopen_normal_close"] = _destroy_owned_windows([window], force=False)
        checks["driver_destroy_confirmed"] = checks["reopen_normal_close"]
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
        destroy_ok = _destroy_owned_windows([window], force=True)
        checks["driver_destroy_confirmed"] = destroy_ok
    finally:
        if destroy_ok:
            finished.set()
