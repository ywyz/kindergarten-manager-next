"""B3 protection-package restore through the real UI (restore-only)."""

from __future__ import annotations

import threading
import time
import traceback
from pathlib import Path
from typing import Any

from maintenance_lifecycle import LifecycleManager


def run_protection_driver(
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
        _latest_plan_raw,
        _resource_asset_counts,
        _write_summary,
    )

    driver = d1_main.JsDriver(window)
    new_window = None
    destroy_ok = False
    old_generation = lifecycle.current().generation
    try:
        from tests.local import backup_fixture_support as fixture

        pre_restore_db = fixture.database_fingerprint(
            runtime.db_path, include_runtime_fields=True
        )
        pre_restore_business = fixture.database_fingerprint(runtime.db_path)
        pre_restore_resources = fixture.resource_fingerprint(config["data_dir"])
        checks["pre_restore_database_sha256"] = pre_restore_db["fingerprint_sha256"]
        checks["pre_restore_resource_sha256"] = pre_restore_resources.get(
            "fingerprint_sha256"
        )
        pre_restore_latest_raw = _latest_plan_raw(runtime.db_path)
        pre_restore_asset_counts = _resource_asset_counts(
            runtime.db_path, config["data_dir"]
        )
        checks["pre_restore_latest_raw"] = pre_restore_latest_raw
        checks["pre_restore_asset_counts"] = pre_restore_asset_counts
        driver.wait_until(
            "Boolean(window.__d1App && window.__d1App.state() === 'ready')",
            what="保护包恢复页面",
            timeout=60,
        )
        assert _js_click_visible(driver, '[data-d1="open-settings"]')
        driver.wait_until(
            "Boolean(document.querySelector('[data-d1=\"open-backup-restore\"]'))",
            what="设置页",
            timeout=30,
        )
        checks["settings_entry_visible"] = _js_visible(
            driver, '[data-d1="open-backup-restore"]'
        )
        checks["settings_entry_enabled"] = _js_visible_enabled(
            driver, '[data-d1="open-backup-restore"]'
        )
        driver.eval(
            "window.__b3JsErrors=[];"
            "window.addEventListener('error',e=>window.__b3JsErrors.push('error:'+String(e.message)));"
            "window.addEventListener('unhandledrejection',"
            "e=>window.__b3JsErrors.push('rejection:'+String(e.reason)));true"
        )
        assert _js_click_visible(driver, '[data-d1="open-backup-restore"]')
        try:
            driver.wait_until(
                "Boolean(document.querySelector('[data-d1=\"backup-restore-panel\"]'))",
                what="维护面板",
                timeout=30,
            )
        except Exception:  # noqa: BLE001 - first failure keeps JS/DOM evidence
            checks["settings_after_click"] = driver.eval(
                "document.querySelector('[data-d1=\"settings\"]')"
                " ? document.querySelector('[data-d1=\"settings\"]').innerText : ''"
            )
            checks["js_errors"] = driver.eval("JSON.stringify(window.__b3JsErrors||[])")
            checks["panel_present_after_click"] = bool(
                driver.eval(
                    "Boolean(document.querySelector('[data-d1=\"backup-restore-panel\"]'))"
                )
            )
            raise
        restore_selector = (
            '[data-d1="backup-restore-panel"] [data-d1="backup-restore"]'
        )
        assert _js_visible_enabled(driver, restore_selector)
        assert _js_click_visible(driver, restore_selector)
        driver.wait_until(
            "Boolean(document.querySelector('[data-d1=\"backup-preview\"]'))"
            " || Boolean(document.querySelector('[data-d1=\"backup-error\"]'))"
            " || Boolean(document.querySelector('[data-d1=\"backup-password\"]'))",
            what="保护包预览",
            timeout=240,
        )
        if _js_visible(driver, '[data-d1="backup-password"]'):
            password = str(config.get("source_password") or "")
            assert password, "encrypted source requires source_password"
            from maintenance_source_verify import _js_set_input

            assert _js_set_input(driver, '[data-d1="backup-password"]', password)
            assert _js_click_visible(driver, '[data-d1="backup-password-submit"]')
            driver.wait_until(
                "Boolean(document.querySelector('[data-d1=\"backup-preview\"]'))"
                " || Boolean(document.querySelector('[data-d1=\"backup-error\"]'))",
                what="密码校验后的保护包预览",
                timeout=240,
            )
        preview_text = driver.eval(
            "document.querySelector('[data-d1=\"backup-restore-panel\"]').innerText"
        )
        checks["restore_preview"] = preview_text
        checks["restore_preview_ready"] = (
            "恢复" in preview_text
            and ("校验完成" in preview_text or "预览" in preview_text)
        )
        assert checks["restore_preview_ready"], preview_text
        assert not _js_visible(driver, '[data-d1="backup-error"]'), preview_text
        assert _js_click(driver, '[data-d1="backup-confirm-check"]')
        assert _js_visible_enabled(driver, '[data-d1="backup-confirm-restore"]')
        assert _js_click_visible(driver, '[data-d1="backup-confirm-restore"]')

        deadline = time.monotonic() + config["timeout"]
        new_bundle = None
        while time.monotonic() < deadline:
            current = lifecycle.current()
            if current is not None and current.generation > old_generation and current.window is not None:
                new_bundle = current
                break
            time.sleep(0.05)
        assert new_bundle is not None, "新 Window/host generation 未出现"
        new_window = new_bundle.window
        checks["new_window_created"] = True
        try:
            new_bundle.host_api._verify_save_dir = Path(config["word_dir"])
        except Exception:  # noqa: BLE001
            pass
        if dialog_stub is not None:
            try:
                new_window.create_file_dialog = dialog_stub
            except Exception:  # noqa: BLE001
                pass
        new_driver = d1_main.JsDriver(new_window)
        new_driver.wait_until(
            "Boolean(window.__d1App && window.__d1App.ready() && window.__d1App.state() === 'ready')",
            what="保护包新页面",
            timeout=120,
        )
        new_driver.wait_until(
            "Boolean(document.querySelector('[data-d1=\"calendar\"]'))"
            " || Boolean(document.querySelector('[data-d1=\"setup\"]'))",
            what="保护包新页业务 DOM",
            timeout=60,
        )
        checks["new_page_ready"] = True
        checks["new_page_has_calendar"] = bool(
            new_driver.eval("Boolean(document.querySelector('[data-d1=\"calendar\"]'))")
        )
        checks["new_page_business_visible"] = True
        checks["restore_notice"] = new_driver.eval(
            "document.querySelector('[data-d1=\"restore-notice\"]').innerText"
        )
        checks["restore_notice_present"] = "恢复前保护副本" in str(
            checks["restore_notice"]
        )
        import webview

        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if window not in list(webview.windows):
                break
            time.sleep(0.05)
        checks["old_window_destroyed"] = window not in list(webview.windows)
        assert checks["old_window_destroyed"]
        assert checks["restore_notice_present"], checks["restore_notice"]

        from tests.local import backup_fixture_support as fixture

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
        if config.get("case") == "capacity":
            source_files = source["resources"].get("files") or []
            target_files = target_resources.get("files") or []
            source_counts = dict(source.get("asset_counts") or {})
            target_counts = _resource_asset_counts(
                runtime.db_path, config["data_dir"]
            )
            checks["capacity_source_package_bytes"] = Path(
                config["source_package"]
            ).stat().st_size
            checks["capacity_source_resource_count"] = len(source_files)
            checks["capacity_restored_resource_count"] = len(target_files)
            checks["capacity_source_asset_counts"] = source_counts
            checks["capacity_restored_asset_counts"] = target_counts
            checks["capacity_source_original_assets"] = int(
                source_counts.get("original_assets") or 0
            )
            checks["capacity_source_original_files"] = int(
                source_counts.get("original_files") or 0
            )
            checks["capacity_source_derivative_assets"] = int(
                source_counts.get("derivative_assets") or 0
            )
            checks["capacity_source_derivative_files"] = int(
                source_counts.get("derivative_files") or 0
            )
            checks["capacity_restored_original_assets"] = int(
                target_counts.get("original_assets") or 0
            )
            checks["capacity_restored_original_files"] = int(
                target_counts.get("original_files") or 0
            )
            checks["capacity_restored_derivative_assets"] = int(
                target_counts.get("derivative_assets") or 0
            )
            checks["capacity_restored_derivative_files"] = int(
                target_counts.get("derivative_files") or 0
            )
            checks["capacity_original_requirement"] = (
                checks["capacity_source_original_files"] >= 600
                and checks["capacity_source_original_files"]
                == checks["capacity_source_original_assets"]
                and checks["capacity_restored_original_files"]
                == checks["capacity_source_original_files"]
                and checks["capacity_restored_original_assets"]
                == checks["capacity_source_original_assets"]
            )
            checks["capacity_resource_counts_equal"] = (
                checks["capacity_source_resource_count"]
                == checks["capacity_restored_resource_count"]
                and checks["capacity_source_derivative_files"]
                == checks["capacity_restored_derivative_files"]
                and checks["capacity_source_derivative_assets"]
                == checks["capacity_restored_derivative_assets"]
            )
            checks["capacity_photo_requirement"] = bool(
                checks["capacity_original_requirement"]
                and checks["capacity_resource_counts_equal"]
                and checks["capacity_source_package_bytes"] > 30 * 1024 * 1024
            )
            assert checks["capacity_photo_requirement"]
            assert checks["capacity_resource_counts_equal"]
        assert checks["database_equal_full"], "protection full41 mismatch"
        assert checks["resources_equal"], "protection resources mismatch"

        import re

        notice_path = Path(
            re.search(
                r"恢复前保护副本：(.+?)。", str(checks.get("restore_notice") or "")
            ).group(1)
        )
        checks["protection_copy_path"] = str(notice_path)
        checks["protection_copy_exists"] = notice_path.is_file()
        checks["protection_copy_inside_target"] = (
            Path(config["data_dir"]).resolve().parent in notice_path.resolve().parents
        )
        checks["protection_source_preserved"] = Path(
            config["source_package"]
        ).is_file()
        checks["protection_copy_distinct_from_source"] = (
            notice_path.resolve() != Path(config["source_package"]).resolve()
        )
        assert checks["protection_copy_exists"]
        assert checks["protection_copy_inside_target"]
        assert checks["protection_source_preserved"]
        assert checks["protection_copy_distinct_from_source"]
        from app.local.backup_snapshot import SnapshotService

        verifier = SnapshotService(
            runtime, app_version="b3-protection-copy", source_identity={"b3": "protection-copy"}
        )
        verified = verifier.verify(notice_path, password=None, cancel=threading.Event())
        copy_db = fixture.database_fingerprint(
            verified.database_path, include_runtime_fields=True
        )
        copy_business = fixture.database_fingerprint(verified.database_path)
        copy_resources = fixture.resource_fingerprint(verified.resources_root)
        checks["protection_copy_database_equal"] = (
            copy_db["fingerprint_sha256"] == pre_restore_db["fingerprint_sha256"]
        )
        checks["protection_copy_business_equal"] = (
            copy_business["fingerprint_sha256"]
            == pre_restore_business["fingerprint_sha256"]
        )
        checks["protection_copy_resources_equal"] = (
            copy_resources.get("fingerprint_sha256")
            == pre_restore_resources.get("fingerprint_sha256")
        )
        checks["protection_copy_resource_count"] = len(
            copy_resources.get("files") or []
        )
        checks["protection_copy_latest_raw"] = _latest_plan_raw(
            verified.database_path
        )
        checks["restored_latest_raw"] = _latest_plan_raw(Path(runtime.db_path))
        source_latest_raw = str(source.get("latest_raw") or "")
        checks["source_latest_raw"] = source_latest_raw
        checks["protection_copy_matches_pre_restore_body"] = (
            checks["protection_copy_latest_raw"] == pre_restore_latest_raw
        )
        checks["restored_matches_source_body"] = (
            bool(source_latest_raw)
            and checks["restored_latest_raw"] == source_latest_raw
        )
        if pre_restore_latest_raw != source_latest_raw:
            checks["protection_copy_distinct_body_marker"] = (
                checks["protection_copy_latest_raw"]
                != checks["restored_latest_raw"]
            )
        else:
            checks["protection_copy_distinct_body_marker"] = True
        try:
            verifier.discard_verified(verified)
        except Exception:  # noqa: BLE001
            pass
        assert checks["protection_copy_database_equal"]
        assert checks["protection_copy_business_equal"]
        assert checks["protection_copy_resources_equal"]
        assert checks["protection_copy_matches_pre_restore_body"]
        assert checks["restored_matches_source_body"], (
            checks["restored_latest_raw"],
            source_latest_raw,
        )
        assert checks["protection_copy_distinct_body_marker"], (
            checks["protection_copy_latest_raw"],
            checks["restored_latest_raw"],
        )
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
