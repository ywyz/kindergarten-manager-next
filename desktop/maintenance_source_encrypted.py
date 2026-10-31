"""B3 encrypted backup: empty password never downgrades, then real package."""

from __future__ import annotations

import threading
import traceback
from pathlib import Path
from typing import Any

from maintenance_lifecycle import LifecycleManager


def run_encrypted_driver(
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
        _js_click_text,
        _js_click_visible,
        _js_set_input,
        _js_visible,
        _js_visible_enabled,
        _write_summary,
    )

    driver = d1_main.JsDriver(window)
    destroy_ok = False
    try:
        driver.wait_until(
            "Boolean(window.__d1App && window.__d1App.state() === 'ready')",
            what="加密备份页面",
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
                checks[f"encrypted_panel_attempt_{panel_attempts}"] = driver.eval(
                    "document.body.innerText"
                )
        checks["encrypted_panel_attempts"] = panel_attempts
        driver.wait_until(
            "Boolean(document.querySelector('[data-d1=\"backup-restore-panel\"]'))",
            what="维护面板",
            timeout=30,
        )
        assert _js_click_visible(driver, '[data-d1="backup-create"]')
        driver.wait_until(
            "Boolean(document.querySelector('[data-d1=\"backup-password-mode\"]'))",
            what="密码模式",
            timeout=30,
        )
        assert _js_click_text(driver, '[data-d1="backup-password-mode"]', "不加密")
        driver.wait_until(
            "Boolean(document.querySelector('[data-d1=\"backup-plaintext-ack\"]'))",
            what="明文确认",
            timeout=15,
        )
        checks["plaintext_unack_ack_visible"] = _js_visible(
            driver, '[data-d1="backup-plaintext-ack"]'
        )
        checks["plaintext_unack_submit_disabled"] = not _js_visible_enabled(
            driver, '[data-d1="backup-password-submit"]'
        )
        checks["plaintext_unack_no_file"] = not Path(config["target_backup"]).exists()
        assert checks["plaintext_unack_ack_visible"]
        assert checks["plaintext_unack_submit_disabled"]
        assert checks["plaintext_unack_no_file"]
        assert _js_click_text(driver, '[data-d1="backup-password-mode"]', "使用密码")
        driver.wait_until(
            "Boolean(document.querySelector('[data-d1=\"backup-password\"]'))",
            what="密码输入",
            timeout=15,
        )
        checks["encrypted_empty_disabled"] = not _js_visible_enabled(
            driver, '[data-d1="backup-password-submit"]'
        )
        checks["encrypted_no_file_before_password"] = not Path(
            config["target_backup"]
        ).exists()
        checks["encrypted_empty_no_terminal"] = (
            not _js_visible(driver, '[data-d1="backup-close"]')
            and not _js_visible(driver, '[data-d1="backup-error"]')
        )
        assert checks["encrypted_empty_disabled"]
        assert checks["encrypted_empty_no_terminal"]
        assert checks["encrypted_no_file_before_password"]

        password = str(config["source_password"])
        assert _js_set_input(driver, '[data-d1="backup-password"]', password)
        assert _js_click_visible(driver, '[data-d1="backup-password-submit"]')
        driver.wait_until(
            "Boolean(document.querySelector('[data-d1=\"backup-close\"]'))"
            " || Boolean(document.querySelector('[data-d1=\"backup-error\"]'))",
            what="加密备份终态",
            timeout=180,
        )
        panel_text = driver.eval(
            "document.querySelector('[data-d1=\"backup-restore-panel\"]').innerText"
        )
        checks["encrypted_completed"] = (
            "备份完成" in panel_text
            and not _js_visible(driver, '[data-d1="backup-error"]')
        )
        checks["encrypted_panel_text"] = panel_text
        assert checks["encrypted_completed"], panel_text

        from app.local.backup_snapshot import SnapshotService

        verifier = SnapshotService(
            runtime, app_version="b3-target", source_identity={"b3": "target"}
        )
        cancel = threading.Event()
        no_password_rejected = False
        try:
            verifier.verify(config["target_backup"], password=None, cancel=cancel)
        except Exception:  # noqa: BLE001 - encrypted package must reject no password
            no_password_rejected = True
        checks["encrypted_requires_password"] = no_password_rejected
        assert checks["encrypted_requires_password"]
        verified = verifier.verify(
            config["target_backup"], password=password, cancel=cancel
        )
        from tests.local import backup_fixture_support as fixture

        verified_db = fixture.database_fingerprint(
            verified.database_path, include_runtime_fields=True
        )

        def _rel(value: object) -> str:
            text = str(value).replace("\\", "/")
            prefix = "observations/assets/"
            return text[len(prefix):] if text.startswith(prefix) else text

        manifest_resources = sorted(
            (
                _rel(item.get("path")),
                int(item.get("bytes") or 0),
                str(item.get("sha256") or ""),
            )
            for item in (verified.manifest.get("resources") or [])
        )
        pre_files = sorted(
            (
                _rel(item.get("path")),
                int(item.get("size") or item.get("bytes") or 0),
                str(item.get("sha256") or ""),
            )
            for item in (target_pre.get("resources", {}).get("files") or [])
        )
        checks["target_backup_database_equal"] = (
            verified_db["fingerprint_sha256"]
            == target_pre["database"]["fingerprint_sha256"]
        )
        checks["target_backup_resources_equal"] = manifest_resources == pre_files
        checks["target_backup_resource_count"] = len(manifest_resources)
        checks["target_backup_verified"] = (
            checks["target_backup_database_equal"]
            and checks["target_backup_resources_equal"]
        )
        try:
            verifier.discard_verified(verified)
        except Exception:  # noqa: BLE001
            pass
        assert checks["target_backup_verified"]
        assert _js_click(driver, '[data-d1="backup-close"]')
        driver.wait_until(
            "!document.querySelector('[data-d1=\"backup-restore-panel\"]')",
            what="关闭加密备份面板",
            timeout=30,
        )
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
