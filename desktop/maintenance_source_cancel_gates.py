"""B3 deterministic gates: cancel in-flight selection verify and protection verify."""

from __future__ import annotations

import threading
import time
import traceback
from pathlib import Path
from typing import Any

from maintenance_lifecycle import LifecycleManager


def run_cancel_gates_driver(
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
    old_generation = lifecycle.current().generation
    gate_state: dict[str, Any] = {"mode": "selection"}
    original_verify = None
    try:
        from app.local.backup_snapshot import SnapshotService
        from tests.local import backup_fixture_support as fixture

        pre_db = fixture.database_fingerprint(
            runtime.db_path, include_runtime_fields=True
        )
        pre_business = fixture.database_fingerprint(runtime.db_path)
        pre_resources = fixture.resource_fingerprint(config["data_dir"])
        maintenance = getattr(host_api, "_maintenance_host", None)
        assert maintenance is not None
        guard_root = Path(
            str(Path(config["data_dir"]).resolve()) + ".restore-guard"
        ).resolve()
        checks["cancel_gate_guard_root"] = str(guard_root)
        checks["cancel_gate_boundary"] = (
            "real SnapshotService.verify returned; held before caller phase "
            "transition (not resource-byte I/O)"
        )
        checks["cancel_gate_scope_verify_return"] = True
        original_verify = SnapshotService.verify

        def gated_verify(
            self,
            package_path,
            *,
            password=None,
            cancel=None,
            progress=None,
        ):
            result = original_verify(
                self,
                package_path,
                password=password,
                cancel=cancel,
                progress=progress,
            )
            path = Path(package_path).resolve()
            mode = gate_state.get("mode")
            should_gate = False
            if mode == "selection":
                should_gate = path == Path(config["source_package"]).resolve()
            elif mode == "protection":
                should_gate = (
                    path.name == "pre-restore.kgmbackup"
                    and path.parent.parent == guard_root
                )
            if should_gate:
                gate_state.update(
                    held=True,
                    released=False,
                    cancel_seen=False,
                    path=str(path),
                )
                try:
                    gate_state["cancel_seen"] = bool(
                        cancel is not None and cancel.wait(60.0)
                    )
                finally:
                    gate_state["released"] = True
            return result

        SnapshotService.verify = gated_verify

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
                    checks[f"cancel_gates_panel_attempt_{attempt}"] = driver.eval(
                        "document.body.innerText"
                    )
            raise AssertionError("维护面板未打开")

        def start_restore() -> None:
            assert _js_click_visible(
                driver,
                '[data-d1="backup-restore-panel"] [data-d1="backup-restore"]',
            )
            driver.wait_until(
                "Boolean(document.querySelector('[data-d1=\"backup-cancel\"]'))"
                " || Boolean(document.querySelector('[data-d1=\"backup-preview\"]'))"
                " || Boolean(document.querySelector('[data-d1=\"backup-error\"]'))",
                what="恢复活动状态",
                timeout=120,
            )
            assert not _js_visible(driver, '[data-d1="backup-error"]')

        def wait_gate_held() -> None:
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if gate_state.get("held") is True:
                    return
                time.sleep(0.01)
            raise AssertionError("实际 verify gate 未到达")

        def target_unchanged() -> bool:
            db = fixture.database_fingerprint(
                runtime.db_path, include_runtime_fields=True
            )
            business = fixture.database_fingerprint(runtime.db_path)
            resources = fixture.resource_fingerprint(config["data_dir"])
            return bool(
                db["fingerprint_sha256"] == pre_db["fingerprint_sha256"]
                and business["fingerprint_sha256"] == pre_business["fingerprint_sha256"]
                and resources.get("fingerprint_sha256")
                == pre_resources.get("fingerprint_sha256")
            )

        def no_transport_stop() -> bool:
            current = lifecycle.current()
            service = getattr(current, "service", None) if current else None
            alive = bool(getattr(service, "alive", lambda: False)())
            return bool(
                lifecycle.current().generation == old_generation
                and window in __import__("webview").windows
                and not getattr(maintenance, "_transport_stopped", False)
                and not getattr(host_api, "_retired", False)
                and not getattr(host_api, "_native_io_blocked", False)
                and alive
            )

        driver.wait_until(
            "Boolean(window.__d1App && window.__d1App.state() === 'ready')",
            what="取消 gate 页面",
            timeout=60,
        )
        assert _js_click_visible(driver, '[data-d1="open-settings"]')
        driver.wait_until(
            "Boolean(document.querySelector('[data-d1=\"open-backup-restore\"]'))",
            what="设置页",
            timeout=30,
        )

        # Case 1: hold the actual selection verify, then cancel from the panel.
        gate_state.update(mode="selection", held=False, released=False)
        open_panel()
        start_restore()
        wait_gate_held()
        checks["cancel_verify_gate_held"] = True
        assert _js_visible_enabled(driver, '[data-d1="backup-cancel"]')
        assert _js_click_visible(driver, '[data-d1="backup-cancel"]')
        driver.wait_until(
            "Boolean(document.querySelector('[data-d1=\"backup-cancelled\"]'))",
            what="选择校验取消终态",
            timeout=120,
        )
        checks["cancel_verify_gate_cancel_seen"] = bool(
            gate_state.get("cancel_seen")
        )
        checks["cancel_verify_gate_released"] = bool(gate_state.get("released"))
        checks["cancel_verify_ui_cancelled"] = True
        checks["cancel_verify_no_transport_stop"] = no_transport_stop()
        checks["cancel_verify_no_switch"] = (
            lifecycle.current().generation == old_generation
        )
        checks["cancel_verify_target_unchanged"] = target_unchanged()
        assert checks["cancel_verify_gate_cancel_seen"]
        assert checks["cancel_verify_gate_released"]
        assert checks["cancel_verify_no_transport_stop"]
        assert checks["cancel_verify_no_switch"]
        assert checks["cancel_verify_target_unchanged"]
        assert _js_click_visible(driver, '[data-d1="backup-cancelled-close"]')
        driver.wait_until(
            "!document.querySelector('[data-d1=\"backup-restore-panel\"]')",
            what="关闭选择校验取消面板",
            timeout=30,
        )

        # Case 2: hold only the automatic protection package verify after confirm.
        gate_state.update(mode="protection", held=False, released=False)
        open_panel()
        start_restore()
        driver.wait_until(
            "Boolean(document.querySelector('[data-d1=\"backup-preview\"]'))",
            what="保护校验前预览",
            timeout=120,
        )
        assert not _js_visible(driver, '[data-d1="backup-error"]')
        assert _js_click(driver, '[data-d1="backup-confirm-check"]')
        assert _js_visible_enabled(driver, '[data-d1="backup-confirm-restore"]')
        assert _js_click_visible(driver, '[data-d1="backup-confirm-restore"]')
        wait_gate_held()
        checks["cancel_protection_gate_held"] = True
        assert _js_visible_enabled(driver, '[data-d1="backup-cancel"]')
        assert _js_click_visible(driver, '[data-d1="backup-cancel"]')
        driver.wait_until(
            "Boolean(document.querySelector('[data-d1=\"backup-cancelled\"]'))",
            what="保护校验取消终态",
            timeout=120,
        )
        checks["cancel_protection_gate_cancel_seen"] = bool(
            gate_state.get("cancel_seen")
        )
        checks["cancel_protection_gate_released"] = bool(
            gate_state.get("released")
        )
        checks["cancel_protection_ui_cancelled"] = True
        checks["cancel_protection_no_transport_stop"] = no_transport_stop()
        checks["cancel_protection_no_switch"] = (
            lifecycle.current().generation == old_generation
        )
        checks["cancel_protection_target_unchanged"] = target_unchanged()
        assert checks["cancel_protection_gate_cancel_seen"]
        assert checks["cancel_protection_gate_released"]
        assert checks["cancel_protection_no_transport_stop"]
        assert checks["cancel_protection_no_switch"]
        assert checks["cancel_protection_target_unchanged"]
        assert _js_click_visible(driver, '[data-d1="backup-cancelled-close"]')
        driver.wait_until(
            "!document.querySelector('[data-d1=\"backup-restore-panel\"]')",
            what="关闭保护校验取消面板",
            timeout=30,
        )
        destroy_ok = _destroy_owned_windows([window])
        checks["driver_destroy_confirmed"] = destroy_ok
    except Exception as exc:  # noqa: BLE001
        checks["driver_error"] = f"{type(exc).__name__}: {exc}"
        checks["driver_trace"] = traceback.format_exc()
        summary["ok"] = False
        try:
            import webview as _failure_webview

            if window in list(_failure_webview.windows):
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
        owned = [window]
        current = lifecycle.current()
        if current is not None and current.window is not None:
            owned.append(current.window)
        destroy_ok = _destroy_owned_windows(owned, force=True)
        checks["driver_destroy_confirmed"] = destroy_ok
    finally:
        if original_verify is not None:
            from app.local.backup_snapshot import SnapshotService

            SnapshotService.verify = original_verify
        if destroy_ok:
            try:
                import webview as _finally_webview

                current = lifecycle.current()
                owned = [window]
                if current is not None and current.window is not None:
                    owned.append(current.window)
                remaining = [
                    candidate
                    for candidate in owned
                    if candidate is not None
                    and candidate in list(_finally_webview.windows)
                ]
            except Exception:  # noqa: BLE001
                remaining = []
            if not remaining:
                finished.set()
