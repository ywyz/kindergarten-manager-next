"""B3 late-capability probes after a real UI restore switch."""

from __future__ import annotations

import json
import threading
import time
import traceback
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from maintenance_lifecycle import LifecycleManager


def _http_json(
    port: int,
    token: str,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    url = f"http://127.0.0.1:{port}{path}"
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("X-App-Session", token)
    if data is not None:
        request.add_header("Content-Type", "application/json")
        request.add_header("Origin", f"http://127.0.0.1:{port}")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read()
            try:
                payload = json.loads(raw.decode("utf-8"))
            except Exception:  # noqa: BLE001
                payload = {"raw": raw.decode("utf-8", "replace")}
            return response.status, payload
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:  # noqa: BLE001
            payload = {"raw": raw.decode("utf-8", "replace")}
        return exc.code, payload


def run_late_driver(
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
    new_window = None
    destroy_ok = False
    old_bundle = lifecycle.current()
    old_generation = old_bundle.generation if old_bundle is not None else 0
    old_token = str(getattr(host_api, "_launch_token", ""))
    old_port = int(old_bundle.service.port) if old_bundle is not None else 0
    old_ticket = str(getattr(host_api, "_page_ticket", "") or "")
    try:
        driver.wait_until(
            "Boolean(window.__d1App && window.__d1App.state() === 'ready')",
            what="迟滞能力页面",
            timeout=60,
        )
        assert _js_click_visible(driver, '[data-d1="open-settings"]')
        driver.wait_until(
            "Boolean(document.querySelector('[data-d1=\"open-backup-restore\"]'))",
            what="设置页",
            timeout=30,
        )
        assert _js_visible_enabled(driver, '[data-d1="open-backup-restore"]')
        assert _js_click_visible(driver, '[data-d1="open-backup-restore"]')
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
            what="迟滞预览",
            timeout=120,
        )
        preview_text = driver.eval(
            "document.querySelector('[data-d1=\"backup-restore-panel\"]').innerText"
        )
        checks["late_preview_text"] = preview_text
        checks["late_preview_ready"] = (
            "恢复" in preview_text and "校验完成" in preview_text
        )
        assert checks["late_preview_ready"], preview_text
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
        assert op is not None, "未捕获旧 restore 预览操作"
        preview = dict(op.get("preview") or {})
        old_preview_id = str(preview.get("preview_id") or "")
        old_operation_id = str(op.get("operation_id") or "")
        old_operation_generation = int(op.get("generation") or 0)
        old_selection_ids = list(maintenance._selections)
        assert old_preview_id and old_operation_id and old_operation_generation
        assert old_selection_ids
        checks["late_old_preview_captured"] = True

        # Old app/old token read and old config preview HMAC before switch.
        old_status, old_context = _http_json(
            old_port, old_token, "GET", "/api/local/context"
        )
        checks["late_old_context_status"] = old_status
        assert old_status == 200, old_context
        config_version = int(old_context.get("config_version") or 0)
        assert config_version >= 1, old_context
        preview_body = {
            "expected_config_version": config_version,
            "change": {"kind": "class_games", "locations": []},
        }
        old_preview_status, old_preview_payload = _http_json(
            old_port, old_token, "POST", "/api/local/config/preview", preview_body
        )
        checks["late_old_config_preview_status"] = old_preview_status
        assert old_preview_status == 200, old_preview_payload
        old_config_preview_token = str(
            old_preview_payload.get("preview_token") or ""
        )
        old_preview_config_version = int(
            old_preview_payload.get("expected_config_version") or config_version
        )
        old_preview_change = old_preview_payload.get("normalized_change")
        assert old_config_preview_token
        assert isinstance(old_preview_change, dict) and old_preview_change
        checks["late_old_config_preview_captured"] = True
        checks["late_old_config_preview_version"] = old_preview_config_version
        checks["late_old_config_preview_change"] = old_preview_change

        assert _js_click(driver, '[data-d1="backup-confirm-check"]')
        assert _js_visible_enabled(driver, '[data-d1="backup-confirm-restore"]')
        assert _js_click_visible(driver, '[data-d1="backup-confirm-restore"]')

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
        assert new_bundle is not None, "新 Window/host generation 未出现"
        new_window = new_bundle.window
        new_host = new_bundle.host_api
        new_port = int(new_bundle.service.port)
        new_token = str(getattr(new_host, "_launch_token", ""))
        checks["late_new_window_created"] = True
        new_driver = d1_main.JsDriver(new_window)
        new_driver.wait_until(
            "Boolean(window.__d1App && window.__d1App.ready()"
            " && window.__d1App.state() === 'ready')",
            what="迟滞新页面",
            timeout=120,
        )
        new_driver.wait_until(
            "Boolean(document.querySelector('[data-d1=\"calendar\"]'))",
            what="迟滞新页业务 DOM",
            timeout=60,
        )
        checks["late_new_page_ready"] = True
        import webview

        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if window not in list(webview.windows):
                break
            time.sleep(0.05)
        checks["late_old_window_destroyed"] = window not in list(webview.windows)
        assert checks["late_old_window_destroyed"]
        checks["late_restore_completed"] = True

        def _probe(name: str, fn) -> Any:
            try:
                value = fn()
            except Exception as exc:  # noqa: BLE001
                value = {"exception": f"{type(exc).__name__}: {exc}"}
            checks[f"late_probe_{name}"] = value
            return value

        bridge = str(getattr(host_api, "BRIDGE_PROTOCOL", "d1-bridge-v1"))
        old_bootstrap = _probe("old_bootstrap", host_api.get_bootstrap)
        checks["late_old_bootstrap_retired"] = (
            isinstance(old_bootstrap, dict)
            and old_bootstrap.get("retired") is True
        )
        old_ready = _probe(
            "old_page_ready",
            lambda: host_api.page_ready(
                {"bridge_protocol": bridge, "page_ticket": old_ticket}
            ),
        )
        checks["late_old_page_ready_rejected"] = (
            isinstance(old_ready, dict) and old_ready.get("accepted") is False
        )
        old_busy = _probe(
            "old_page_busy",
            lambda: host_api.set_page_busy(
                {"page_ticket": old_ticket, "seq": 999, "busy": True}
            ),
        )
        checks["late_old_page_busy_rejected"] = (
            isinstance(old_busy, dict) and old_busy.get("accepted") is False
        )
        old_business = _probe(
            "old_business_ready",
            lambda: host_api.page_business_ready({"page_ticket": old_ticket}),
        )
        checks["late_old_business_ready_rejected"] = (
            isinstance(old_business, dict)
            and old_business.get("accepted") is False
        )
        old_guard = _probe("old_guard", host_api._maintenance_guard)
        checks["late_old_guard_retired"] = (
            isinstance(old_guard, dict)
            and (old_guard.get("error") or {}).get("code") == "HOST_RETIRED"
        )
        old_save = _probe(
            "old_native_save",
            lambda: host_api.save_docx(
                {"request_id": "late-native-save", "payload_base64": "eA=="}
            ),
        )
        checks["late_old_native_save_rejected"] = (
            isinstance(old_save, dict) and old_save.get("code") == "HOST_SWITCHING"
        )
        old_obs_save = _probe(
            "old_observation_save",
            lambda: host_api.save_observation_export(
                {"export_id": "late-export", "filename": "late.docx"}
            ),
        )
        checks["late_old_observation_save_rejected"] = (
            isinstance(old_obs_save, dict)
            and old_obs_save.get("code") == "HOST_SWITCHING"
        )
        old_close = _probe(
            "old_complete_close",
            lambda: host_api.complete_close(
                {"close_request_id": "late-close", "allow": True}
            ),
        )
        checks["late_old_close_rejected"] = (
            isinstance(old_close, dict) and old_close.get("accepted") is False
        )
        old_backup = _probe(
            "old_start_backup",
            lambda: host_api.start_backup({"request_id": "late-backup"}),
        )
        old_restore = _probe(
            "old_start_restore",
            lambda: host_api.start_restore_verify(
                {"request_id": "late-restore", "selection_id": old_selection_ids[0]}
            ),
        )
        old_confirm = _probe(
            "old_confirm_restore",
            lambda: host_api.confirm_restore(
                {
                    "request_id": "late-confirm",
                    "operation_id": old_operation_id,
                    "generation": old_operation_generation,
                    "confirmation_token": old_preview_id,
                }
            ),
        )
        checks["late_old_maintenance_rejected"] = all(
            isinstance(item, dict)
            and (item.get("error") or {}).get("code") == "HOST_RETIRED"
            for item in (old_backup, old_restore, old_confirm)
        )
        checks["late_old_confirm_rejected"] = (
            isinstance(old_confirm, dict)
            and (old_confirm.get("error") or {}).get("code") == "HOST_RETIRED"
        )
        old_cancel = _probe(
            "old_cancel",
            lambda: host_api.cancel_maintenance(
                {
                    "operation_id": old_operation_id,
                    "generation": old_operation_generation,
                }
            ),
        )
        checks["late_old_cancel_rejected"] = (
            isinstance(old_cancel, dict) and old_cancel.get("accepted") is False
        )

        new_ready_old = _probe(
            "new_page_ready_old_ticket",
            lambda: new_host.page_ready(
                {"bridge_protocol": bridge, "page_ticket": old_ticket}
            ),
        )
        new_business_old = _probe(
            "new_business_ready_old_ticket",
            lambda: new_host.page_business_ready({"page_ticket": old_ticket}),
        )
        new_busy_old = _probe(
            "new_page_busy_old_ticket",
            lambda: new_host.set_page_busy(
                {"page_ticket": old_ticket, "seq": 1000, "busy": True}
            ),
        )
        checks["late_new_old_ticket_rejected"] = all(
            isinstance(item, dict) and item.get("accepted") is False
            for item in (new_ready_old, new_business_old, new_busy_old)
        )
        new_confirm_old = _probe(
            "new_confirm_old_preview",
            lambda: new_host.confirm_restore(
                {
                    "request_id": "late-new-confirm",
                    "operation_id": old_operation_id,
                    "generation": old_operation_generation,
                    "confirmation_token": old_preview_id,
                }
            ),
        )
        checks["late_new_old_preview_rejected"] = (
            isinstance(new_confirm_old, dict)
            and (new_confirm_old.get("error") or {}).get("code")
            in {"PREVIEW_STALE", "HOST_RETIRED", "REQUEST_CONFLICT"}
        )
        new_restore_old_selection = _probe(
            "new_restore_old_selection",
            lambda: new_host.start_restore_verify(
                {
                    "request_id": "late-new-restore",
                    "selection_id": old_selection_ids[0],
                }
            ),
        )
        checks["late_new_old_selection_rejected"] = (
            isinstance(new_restore_old_selection, dict)
            and (new_restore_old_selection.get("error") or {}).get("code")
            in {"SELECTION_UNKNOWN", "HOST_RETIRED"}
        )
        generation_after_probes = lifecycle.current().generation
        checks["late_no_extra_generation"] = (
            generation_after_probes == new_bundle.generation
        )
        assert checks["late_no_extra_generation"]

        old_token_status, old_token_payload = _http_json(
            new_port, old_token, "GET", "/api/local/context"
        )
        checks["late_old_token_status"] = old_token_status
        checks["late_old_token_rejected"] = old_token_status == 401
        assert checks["late_old_token_rejected"], old_token_payload
        new_token_status, new_context = _http_json(
            new_port, new_token, "GET", "/api/local/context"
        )
        checks["late_new_token_status"] = new_token_status
        checks["late_new_token_read"] = (
            new_token_status == 200 and new_context.get("status") == "ready"
        )
        assert checks["late_new_token_read"], new_context
        new_config_version = int(new_context.get("config_version") or 0)
        new_preview_body = {
            "expected_config_version": new_config_version,
            "change": {"kind": "class_games", "locations": []},
        }
        new_write_status, new_write_payload = _http_json(
            new_port, new_token, "POST", "/api/local/config/preview", new_preview_body
        )
        checks["late_new_token_preview_status"] = new_write_status
        checks["late_new_token_preview"] = (
            new_write_status == 200
            and bool(new_write_payload.get("preview_token"))
        )
        assert checks["late_new_token_preview"], new_write_payload
        old_hmac_status, old_hmac_payload = _http_json(
            new_port,
            new_token,
            "POST",
            "/api/local/config/apply",
            {
                "request_id": str(uuid.uuid4()),
                "expected_config_version": old_preview_config_version,
                "change": old_preview_change,
                "preview_token": old_config_preview_token,
            },
        )
        checks["late_config_preview_hmac_status"] = old_hmac_status
        checks["late_config_preview_hmac_error"] = old_hmac_payload
        old_hmac_error = old_hmac_payload.get("error") or {}
        checks["late_config_preview_hmac_rejected"] = bool(
            old_hmac_status == 422
            and old_hmac_error.get("code") == "VALIDATION_ERROR"
            and old_hmac_error.get("message") == "预览令牌无效"
        )
        assert checks["late_config_preview_hmac_rejected"], old_hmac_payload

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
        checks["late_new_work_unchanged"] = bool(
            checks["database_equal_full"] and checks["resources_equal"]
        )
        assert checks["late_new_work_unchanged"]
        checks["late_new_page_still_ready"] = bool(
            new_driver.eval(
                "Boolean(window.__d1App && window.__d1App.state() === 'ready')"
            )
        )
        assert checks["late_new_page_still_ready"]

        destroy_ok = _destroy_owned_windows([new_window])
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
