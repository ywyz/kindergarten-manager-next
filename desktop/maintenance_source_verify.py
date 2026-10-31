"""B3 source-window verification entry (source-only, synthetic roots only).

The module is intentionally separate from ``d1_main``: the main entry only
dispatches the dedicated phase.  It builds the real D1 app/window/host and
drives the actual Vue panel through DOM buttons; native file dialogs are
replaced by a controlled substitute returning only configured synthetic paths.
No real supplier, WebDAV, frozen EXE, teacher data or credential root is used.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
import time
import traceback
from pathlib import Path
from typing import Any

from maintenance_lifecycle import LifecycleBundle, LifecycleManager
from maintenance_source_guard import NetworkGuard


class SourceVerifyError(RuntimeError):
    pass


def _load_config(args) -> dict[str, Any]:
    raw = getattr(args, "b3_config", None)
    if not raw:
        raise SourceVerifyError("b3-source-window 必须提供 --b3-config")
    path = Path(raw).resolve()
    if not path.is_file():
        raise SourceVerifyError("b3 config 不存在")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SourceVerifyError(f"b3 config 读取失败: {type(exc).__name__}") from exc
    if not isinstance(data, dict):
        raise SourceVerifyError("b3 config 必须是对象")
    return data


def _require_under(root: Path, path: Path, label: str) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise SourceVerifyError(f"{label} 必须位于本次合成 root 内") from exc
    return resolved


def _validate_config(args, config: dict[str, Any]) -> dict[str, Any]:
    if not getattr(args, "selftest", False) or getattr(args, "phase", "") != "b3-source-window":
        raise SourceVerifyError("只允许 b3-source-window 专用相位")
    if not getattr(args, "data", None) or not getattr(args, "credential_root", None):
        raise SourceVerifyError("必须显式提供 --data 与 --credential-root")
    raw_root = config.get("root")
    if not isinstance(raw_root, str) or not raw_root:
        raise SourceVerifyError("config.root 缺失")
    root = Path(raw_root).resolve()
    temp_root = Path(os.environ.get("TEMP") or os.environ.get("TMP") or "").resolve()
    if not temp_root or temp_root not in root.parents:
        raise SourceVerifyError("config.root 必须在系统临时根下")
    if len(str(root)) > 120:
        raise SourceVerifyError("合成 root 过长，避免 Windows 长根边界")
    target_data = _require_under(root, Path(args.data), "data")
    target_cred = _require_under(root, Path(args.credential_root), "credential")
    source_data = _require_under(root, Path(str(config.get("source_data_dir") or "")), "source_data")
    source_cred = _require_under(root, Path(str(config.get("source_credential_root") or "")), "source_credential")
    evidence = _require_under(root, Path(str(config.get("evidence_dir") or "")), "evidence")
    source_package = _require_under(root, Path(str(config.get("source_package") or "")), "source_package")
    target_backup = _require_under(root, Path(str(config.get("target_backup") or "")), "target_backup")
    bad_package = _require_under(root, Path(str(config.get("bad_package") or (root / "bad.kgmbackup"))), "bad_package")
    encrypted_package = _require_under(root, Path(str(config.get("encrypted_package") or (root / "old-encrypted.kgmbackup"))), "encrypted_package")
    word_dir = _require_under(root, Path(str(config.get("word_dir") or (root / "word"))), "word_dir")
    raw_out = getattr(args, "out", None)
    out_path = (
        _require_under(root, Path(raw_out), "out")
        if raw_out
        else (evidence / "b3-result.json").resolve()
    )
    config_path = Path(args.b3_config).resolve()
    file_artifacts = {
        "config": config_path,
        "source_package": source_package,
        "target_backup": target_backup,
        "bad_package": bad_package,
        "encrypted_package": encrypted_package,
        "out": out_path,
    }
    directory_artifacts = {
        "source_data": source_data,
        "source_credential_root": source_cred,
        "target_data": target_data,
        "target_credential_root": target_cred,
        "evidence_dir": evidence,
        "word_dir": word_dir,
    }
    seen_files: dict[Path, str] = {}
    for label, path in file_artifacts.items():
        resolved = path.resolve()
        if resolved in seen_files:
            raise SourceVerifyError(
                f"{label} 与 {seen_files[resolved]} 是同一文件路径（别名）；拒绝输出互相覆盖"
            )
        seen_files[resolved] = label
    seen_dirs: dict[Path, str] = {}
    for label, path in directory_artifacts.items():
        resolved = path.resolve()
        if resolved in seen_dirs:
            raise SourceVerifyError(
                f"{label} 与 {seen_dirs[resolved]} 是同一目录路径；拒绝角色重叠"
            )
        seen_dirs[resolved] = label
    for label, path in file_artifacts.items():
        if path.exists() and not path.is_file():
            raise SourceVerifyError(f"{label} 必须是文件路径，现有对象不是文件")
        if path.resolve() in seen_dirs:
            raise SourceVerifyError(
                f"{label} 不得别名目录角色 {seen_dirs[path.resolve()]}"
            )
    for label, path in directory_artifacts.items():
        if path.exists() and not path.is_dir():
            raise SourceVerifyError(f"{label} 必须是目录路径，现有对象不是目录")
    data_roots = (source_data, source_cred, target_data, target_cred)
    for label, path in file_artifacts.items():
        for data_root in data_roots:
            if path == data_root or data_root in path.parents:
                raise SourceVerifyError(f"{label} 不得位于数据／凭据根内")
    if resolved_case := str(config.get("case") or "plaintext"):
        if resolved_case not in {"plaintext", "setup", "restart", "protection", "encrypted-backup", "capacity", "late", "reopen-failure", "reopen-service-failure", "ai-cold", "cancel-window", "cancel-gates"}:
            raise SourceVerifyError("config.case 不受支持")
    evidence.mkdir(parents=True, exist_ok=True)
    word_dir.mkdir(parents=True, exist_ok=True)
    source_package.parent.mkdir(parents=True, exist_ok=True)
    target_backup.parent.mkdir(parents=True, exist_ok=True)
    return {
        "root": root,
        "data_dir": target_data,
        "credential_root": target_cred,
        "source_data_dir": source_data,
        "source_credential_root": source_cred,
        "evidence_dir": evidence,
        "source_package": source_package,
        "target_backup": target_backup,
        "capacity_photo_count": int(config.get("capacity_photo_count", 3)),
        "case": str(config.get("case") or "plaintext"),
        "post": config.get("post") is True,
        "word_dir": str(word_dir),
        "source_password": str(config.get("source_password") or "synthetic-b3-source-password"),
        "bad_package": str(bad_package),
        "encrypted_package": str(encrypted_package),
        "out_path": str(out_path),
        "frontend": config.get("frontend"),
        "timeout": float(config.get("timeout", 240.0)),
        "seed_target": config.get("seed_target") is True,
        "restart_expected_marker": config.get("restart_expected_marker"),
        "restart_require_stable_versions": config.get("restart_require_stable_versions")
        is True,
        "restart_user_save_marker": config.get("restart_user_save_marker"),
        "reopen_failure_mode": str(config.get("reopen_failure_mode") or "host"),
    }


def _preflight_paths(config: dict[str, Any]) -> None:
    """Refuse existing packages/roots; never delete or overwrite evidence."""
    out_raw = config.get("out_path")
    if out_raw and Path(out_raw).exists():
        raise SourceVerifyError("out 已存在；拒绝覆盖未知结果，请使用新 root／out")
    if config.get("case") in ("restart", "ai-cold"):
        return
    if config.get("case") in ("protection", "capacity", "cancel-window"):
        if not Path(config["source_package"]).is_file():
            raise SourceVerifyError("source_package 必须已存在")
        return
    if config.get("case") == "encrypted-backup":
        if Path(config["target_backup"]).exists():
            raise SourceVerifyError("target_backup 已存在；拒绝覆盖未知包，请使用新 root")
        return
    for label in ("bad_package", "encrypted_package"):
        value = config.get(label)
        if value and Path(value).exists():
            raise SourceVerifyError(f"{label} 已存在；拒绝覆盖未知包，请使用新 root")
    for label, path in (
        ("source_package", Path(config["source_package"])),
        ("target_backup", Path(config["target_backup"])),
    ):
        if path.exists():
            raise SourceVerifyError(f"{label} 已存在；拒绝覆盖未知包，请使用新 root")
    for label, path in (
        ("source_data_dir", Path(config["source_data_dir"])),
        ("source_credential_root", Path(config["source_credential_root"])),
        ("target data_dir", Path(config["data_dir"])),
        ("target credential_root", Path(config["credential_root"])),
    ):
        if path.exists() and any(path.iterdir()):
            raise SourceVerifyError(f"{label} 非空；拒绝复用未知根")


def _save_body_marker(runtime, evidence, marker: str) -> dict[str, Any]:
    """Write a distinct body/history marker through the normal save service."""
    from app.local import daily_plan_service

    session = runtime.session()
    try:
        return daily_plan_service.save(
            session,
            plan_id=evidence.daily_plan_id,
            expected_content_version=evidence.daily_plan_current_version,
            raw_lesson_plan=marker,
        )
    finally:
        session.close()



def _latest_plan_raw(db_path: str | Path) -> str:
    """Latest saved daily-plan body text; an exact oracle, never a prefix rule."""
    import sqlite3

    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        row = con.execute(
            "select raw_lesson_plan from local_daily_plan_contents"
            " order by version desc limit 1"
        ).fetchone()
        return str(row[0] or "") if row else ""
    finally:
        con.close()


def _resource_asset_counts(
    db_path: str | Path, resources_root: str | Path
) -> dict[str, int]:
    """Count managed originals separately from derivatives and total files."""
    import sqlite3

    root = Path(resources_root)
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        original_rows = [
            str(row[0])
            for row in con.execute(
                "select relative_path from local_observation_assets"
            )
        ]
        derivative_rows = [
            str(row[0])
            for row in con.execute(
                "select relative_path from local_observation_asset_derivatives"
            )
        ]
    finally:
        con.close()
    original_files = [rel for rel in original_rows if (root / rel).is_file()]
    derivative_files = [rel for rel in derivative_rows if (root / rel).is_file()]
    return {
        "original_assets": len(original_rows),
        "original_files": len(original_files),
        "derivative_assets": len(derivative_rows),
        "derivative_files": len(derivative_files),
    }


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _prepare_source(config: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    """Create the old fixture and its plaintext package through the real core."""
    from app.local.backup_snapshot import SnapshotService
    from app.local.runtime import LocalRuntime
    from tests.local import backup_fixture_support as fixture

    source_data = config["source_data_dir"]
    source_cred = config["source_credential_root"]
    package = config["source_package"]
    if package.exists():
        raise SourceVerifyError("source_package 已存在；拒绝覆盖未知包，请使用新 root")
    if source_data.exists() and any(source_data.iterdir()):
        raise SourceVerifyError("source_data_dir 非空；拒绝复用未知数据根")
    # LocalRuntime owns creation of the data root and the restricted-DACL
    # credential root.  Pre-creating the credential root with mkdir would
    # inherit a normal DACL and the credential store correctly refuses it.
    runtime = LocalRuntime(source_data, credential_root=source_cred)
    try:
        runtime.prepare()
        evidence = fixture.seed_existing_runtime(
            runtime, capacity_photo_count=config["capacity_photo_count"]
        )
        marker_result = _save_body_marker(
            runtime, evidence, "B3 SOURCE BODY MARKER 2026-10-31"
        )
        db_fp = fixture.database_fingerprint(
            runtime.db_path, include_runtime_fields=True
        )
        db_business = fixture.database_fingerprint(runtime.db_path)
        resource_fp = fixture.resource_fingerprint(source_data)
        service = SnapshotService(
            runtime,
            app_version="b3-source",
            source_identity={"b3": "source", "fixture": "capacity"},
        )
        cancel = threading.Event()
        result = service.create(
            package, password=None, cancel=cancel, progress=None
        )
        verified = service.verify(package, password=None, cancel=cancel)
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
            for item in (resource_fp.get("files") or [])
        )
        if verified_db["fingerprint_sha256"] != db_fp["fingerprint_sha256"]:
            raise SourceVerifyError("源完整包的数据库指纹与源运行时不符")
        if manifest_resources != pre_files:
            raise SourceVerifyError("源完整包的资源清单与源运行时不符")
        bad = Path(config["bad_package"])
        encrypted = Path(config["encrypted_package"])
        if bad.exists() or encrypted.exists():
            raise SourceVerifyError("bad/encrypted source package 已存在；拒绝覆盖")
        bad.write_bytes(package.read_bytes()[:11])
        encrypted_result = service.create(
            encrypted,
            password=config["source_password"],
            cancel=cancel,
            progress=None,
        )
        encrypted_verified = service.verify(
            encrypted, password=config["source_password"], cancel=cancel
        )
        try:
            service.discard_verified(verified)
            service.discard_verified(encrypted_verified)
        except Exception:  # noqa: BLE001 - cleanup evidence only
            pass
        summary["source"] = {
            "package": str(package),
            "package_bytes": package.stat().st_size,
            "package_sha256": _sha256(package),
            "fixture": evidence.as_dict(),
            "body_marker_version": marker_result.get("current_content_version"),
            "body_marker_text": marker_result.get("content", {}).get("raw_lesson_plan"),
            "database_sha256": db_fp["fingerprint_sha256"],
            "database_business_sha256": db_business["fingerprint_sha256"],
            "package_database_sha256": verified_db["fingerprint_sha256"],
            "package_resources_equal": manifest_resources == pre_files,
            "bad_package": str(bad),
            "bad_package_bytes": bad.stat().st_size,
            "encrypted_package": str(encrypted),
            "encrypted_package_bytes": encrypted.stat().st_size,
            "resource_sha256": resource_fp.get("fingerprint_sha256"),
            "resource_files": resource_fp.get("files"),
            "counts": evidence.counts,
        }
        return {
            "database": db_fp,
            "database_business": db_business,
            "resources": resource_fp,
            "evidence": evidence,
        }
    finally:
        runtime.dispose()


def _prepare_target(config: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    """Seed the target BEFORE the real executor starts (no queued claim race)."""
    from app.local.runtime import LocalRuntime
    from tests.local import backup_fixture_support as fixture

    target_data = config["data_dir"]
    target_cred = config["credential_root"]
    if target_data.exists() and any(target_data.iterdir()):
        raise SourceVerifyError("target data_dir 非空；拒绝复用未知数据根")
    if target_cred.exists() and any(target_cred.iterdir()):
        raise SourceVerifyError("target credential_root 非空；拒绝复用未知凭据根")
    runtime = LocalRuntime(target_data, credential_root=target_cred)
    try:
        runtime.prepare()
        evidence = fixture.seed_existing_runtime(runtime)
        marker_result = _save_body_marker(
            runtime, evidence, "B3 TARGET BODY MARKER 2026-10-31"
        )
        fp = fixture.database_fingerprint(
            runtime.db_path, include_runtime_fields=True
        )
        business = fixture.database_fingerprint(runtime.db_path)
        resources = fixture.resource_fingerprint(target_data)
        summary["target_pre"] = {
            "fixture": evidence.as_dict(),
            "body_marker_version": marker_result.get("current_content_version"),
            "body_marker_text": marker_result.get("content", {}).get("raw_lesson_plan"),
            "database_sha256": fp["fingerprint_sha256"],
            "database_business_sha256": business["fingerprint_sha256"],
            "resource_sha256": resources.get("fingerprint_sha256"),
            "resource_files": resources.get("files"),
        }
        return {
            "database": fp,
            "database_business": business,
            "resources": resources,
            "evidence": evidence,
        }
    finally:
        runtime.dispose()


def _write_summary(summary: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _cleanup_unswitched_maintenance(host_api) -> int:
    """Cancel only this driver's pre-switch maintenance; never a real switch."""
    maintenance = getattr(host_api, "_maintenance_host", None)
    ops = getattr(maintenance, "_ops", None)
    if not isinstance(ops, dict):
        return 0
    cancelled = 0
    for op in list(ops.values()):
        if not isinstance(op, dict):
            continue
        if op.get("phase") not in {
            "creating",
            "verifying",
            "preview",
            "waiting",
            "protection",
        }:
            continue
        try:
            maintenance.cancel(
                {
                    "operation_id": op.get("operation_id"),
                    "generation": op.get("generation"),
                }
            )
            cancelled += 1
        except Exception:  # noqa: BLE001 - cleanup never fakes UI success
            pass
    return cancelled


def _destroy_owned_windows(windows, *, force: bool = False) -> bool:
    """Destroy only the windows passed by this driver and confirm they are gone."""
    try:
        import webview
    except Exception:  # noqa: BLE001 - unit fake without webview
        webview = None
    confirmed = True
    for candidate in windows:
        if candidate is None:
            continue
        if not force and webview is not None:
            try:
                if candidate not in list(webview.windows):
                    continue
            except Exception:  # noqa: BLE001
                pass
        try:
            candidate.destroy()
        except Exception:  # noqa: BLE001 - a refused destroy is not success
            confirmed = False
    if webview is not None:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            try:
                live = [w for w in windows if w is not None and w in list(webview.windows)]
            except Exception:  # noqa: BLE001
                live = []
            if not live:
                break
            time.sleep(0.05)
        try:
            confirmed = confirmed and not any(
                w is not None and w in list(webview.windows) for w in windows
            )
        except Exception:  # noqa: BLE001
            confirmed = False
    return confirmed


def _js_click(driver, selector: str) -> bool:
    return bool(
        driver.eval(
            "(function(){const e=document.querySelector("
            + json.dumps(selector)
            + "); if(!e) return false; e.click(); return true;})()"
        )
    )


def _js_visible(driver, selector: str) -> bool:
    return bool(
        driver.eval(
            "(function(){const e=document.querySelector("
            + json.dumps(selector)
            + "); if(!e) return false; const r=e.getBoundingClientRect();"
            " const s=getComputedStyle(e); return r.width>0 && r.height>0"
            " && s.visibility!=='hidden' && s.display!=='none';})()"
        )
    )


def _js_visible_enabled(driver, selector: str) -> bool:
    return bool(
        driver.eval(
            "(function(){const e=document.querySelector("
            + json.dumps(selector)
            + "); if(!e) return false; const r=e.getBoundingClientRect();"
            " const s=getComputedStyle(e); return r.width>0 && r.height>0"
            " && s.visibility!=='hidden' && s.display!=='none' && !e.disabled;})()"
        )
    )


def _js_click_visible(driver, selector: str) -> bool:
    return bool(
        driver.eval(
            "(function(){const e=document.querySelector("
            + json.dumps(selector)
            + "); if(!e) return false; const r=e.getBoundingClientRect();"
            " const s=getComputedStyle(e); if(r.width<=0 || r.height<=0"
            " || s.visibility==='hidden' || s.display==='none' || e.disabled) return false;"
            " e.click(); return true;})()"
        )
    )


def _js_click_text(driver, container: str, text: str) -> bool:
    return bool(
        driver.eval(
            "(function(){const root=document.querySelector("
            + json.dumps(container)
            + "); if(!root) return false; const all=[...root.querySelectorAll('.el-radio,.el-checkbox,button,.el-button')];"
            "const e=all.find(x=>x.textContent && x.textContent.includes("
            + json.dumps(text, ensure_ascii=False)
            + ")); if(!e) return false; e.click(); return true;})()"
        )
    )


def _clear_settings_draft(driver) -> None:
    """Cancel an existing unsaved settings/AI draft before opening maintenance.

    This is a driver setup step (source fixture has no user draft); it never
    saves or applies settings and is not an UI acceptance action.
    """
    driver.eval(
        "(()=>{const app=window.__d1App; if(!app) return false;"
        " const s=app.closeState && app.closeState();"
        " if(!s || !s.settingsDraft) return false;"
        " const b=document.querySelector('[data-d1=\"ai-discard-settings\"]');"
        " if(!b || b.disabled) return false; b.click(); return true;})()"
    )
    try:
        driver.wait_until(
            "!window.__d1App.closeState().settingsDraft",
            what="设置草稿已取消",
            timeout=15,
        )
    except Exception:  # noqa: BLE001 - the panel open wait below reports
        pass


def _open_settings_panel(driver) -> None:
    _clear_settings_draft(driver)
    driver.wait_until(
        "(()=>{const e=document.querySelector('[data-d1=\"open-backup-restore\"]');"
        " if(!e) return false; const r=e.getBoundingClientRect();"
        " return r.width>0 && r.height>0 && !e.disabled;})()",
        what="设置页恢复入口可见",
        timeout=30,
    )
    assert _js_click_visible(driver, '[data-d1="open-backup-restore"]')
    driver.wait_until(
        "Boolean(document.querySelector('[data-d1=\"backup-restore-panel\"]'))",
        what="维护面板",
        timeout=30,
    )


def _js_set_input(driver, selector: str, value: str) -> bool:
    return bool(
        driver.eval(
            "(function(){const e=document.querySelector("
            + json.dumps(selector)
            + "); if(!e) return false; const i=e.matches('input,textarea')?e:e.querySelector('input,textarea');"
            "if(!i) return false; i.value="
            + json.dumps(value, ensure_ascii=False)
            + "; i.dispatchEvent(new Event('input',{bubbles:true})); i.dispatchEvent(new Event('change',{bubbles:true})); return true;})()"
        )
    )


def _run_driver(
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

    old_generation = lifecycle.current().generation
    driver = d1_main.JsDriver(window)
    new_window = None
    destroy_ok = False
    try:
        driver.wait_until(
            "Boolean(window.__d1App && window.__d1App.ready())",
            what="B3 页面启动",
            timeout=60,
        )
        checks["initial_page_ready"] = True
        checks["initial_state"] = driver.eval("window.__d1App.state()")
        checks["initial_view"] = driver.eval("window.__d1App.view()")
        assert checks["initial_state"] == "ready", checks

        # Settings page entry.
        assert _js_click(driver, '[data-d1="open-settings"]')
        driver.wait_until(
            "window.__d1App.view() === 'settings'",
            what="设置页",
            timeout=30,
        )
        checks["settings_entry"] = True
        _open_settings_panel(driver)
        checks["panel_open"] = True

        # Actual button: create plaintext backup.
        assert _js_visible_enabled(driver, '[data-d1="backup-create"]')
        assert _js_click_visible(driver, '[data-d1="backup-create"]')
        driver.wait_until(
            "Boolean(document.querySelector('[data-d1=\"backup-password-mode\"]'))",
            what="备份密码模式",
            timeout=30,
        )
        assert _js_click_text(driver, '[data-d1="backup-password-mode"]', "不加密")
        driver.wait_until(
            "Boolean(document.querySelector('[data-d1=\"backup-plaintext-ack\"]'))",
            what="明文确认",
            timeout=10,
        )
        assert _js_click(driver, '[data-d1="backup-plaintext-ack"]')
        assert _js_visible_enabled(driver, '[data-d1="backup-password-submit"]')
        assert _js_click_visible(driver, '[data-d1="backup-password-submit"]')
        driver.wait_until(
            "Boolean(document.querySelector('[data-d1=\"backup-protection-location-complete\"]')"
            " || document.querySelector('[data-d1=\"backup-error\"]'))",
            what="备份终态",
            timeout=120,
        )
        panel_text = driver.eval("document.querySelector('[data-d1=\"backup-restore-panel\"]').innerText")
        checks["backup_completed"] = "备份" in panel_text and not driver.eval(
            "Boolean(document.querySelector('[data-d1=\"backup-error\"]'))"
        )
        checks["backup_panel_text"] = panel_text
        assert checks["backup_completed"], panel_text
        assert _js_click(driver, '[data-d1="backup-close"]')
        driver.wait_until(
            "!document.querySelector('[data-d1=\"backup-restore-panel\"]')",
            what="关闭备份面板",
            timeout=30,
        )

        # Re-open the panel from the real settings entry; the previous panel
        # was closed by backup-close, so its internal restore button is gone.
        _open_settings_panel(driver)

        driver.wait_until(
            "Boolean(document.querySelector('[data-d1=\"backup-restore-panel\"] [data-d1=\"backup-restore\"]'))",
            what="重新打开恢复按钮",
            timeout=30,
        )

        # Verify the actual package independently (read-only core verify).
        from app.local.backup_snapshot import SnapshotService

        verifier = SnapshotService(
            runtime, app_version="b3-target", source_identity={"b3": "target"}
        )
        cancel = threading.Event()
        verified = verifier.verify(
            config["target_backup"], password=None, cancel=cancel
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
            verified_db["fingerprint_sha256"] == target_pre["database"]["fingerprint_sha256"]
        )
        checks["target_backup_resources_equal"] = manifest_resources == pre_files
        checks["target_backup_manifest"] = {
            "counts": verified.manifest.get("counts"),
            "resources": len(manifest_resources),
            "source_revision": verified.source_revision,
            "target_revision": verified.target_revision,
        }
        checks["target_backup_verified"] = (
            checks["target_backup_database_equal"]
            and checks["target_backup_resources_equal"]
        )
        try:
            verifier.discard_verified(verified)
        except Exception:  # noqa: BLE001
            pass

        # Restore the old source package through the real panel.
        restore_selector = '[data-d1="backup-restore-panel"] [data-d1="backup-restore"]'
        assert _js_visible_enabled(driver, restore_selector)
        assert _js_click_visible(driver, restore_selector)
        driver.wait_until(
            "Boolean(document.querySelector('[data-d1=\"backup-preview\"]'))"
            " || document.querySelector('[data-d1=\"backup-error\"]')"
            " || document.querySelector('[data-d1=\"backup-password\"]')",
            what="恢复预览",
            timeout=120,
        )
        preview_text = driver.eval("document.querySelector('[data-d1=\"backup-restore-panel\"]').innerText")
        checks["restore_preview"] = preview_text
        checks["restore_preview_ready"] = "恢复" in preview_text and (
            "校验完成" in preview_text or "预览" in preview_text
        )
        assert checks["restore_preview_ready"], preview_text
        assert not driver.eval("Boolean(document.querySelector('[data-d1=\"backup-error\"]'))"), preview_text
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
        try:
            new_bundle.host_api._verify_save_dir = Path(config["word_dir"])
        except Exception as exc:  # noqa: BLE001
            checks["new_verify_save_dir_error"] = str(exc)
        checks["new_window_generation"] = new_bundle.generation
        checks["new_window_created"] = new_bundle.generation > old_generation
        if dialog_stub is not None:
            try:
                new_window.create_file_dialog = dialog_stub
            except Exception as exc:  # noqa: BLE001
                checks["new_dialog_stub_error"] = str(exc)
        new_driver = d1_main.JsDriver(new_window)
        new_driver.wait_until(
            "Boolean(window.__d1App && window.__d1App.ready() && window.__d1App.state() === 'ready')",
            what="新页面业务就绪",
            timeout=120,
        )
        new_driver.wait_until(
            "Boolean(document.querySelector('[data-d1=\"restore-notice\"]'))",
            what="新页保护位置通知",
            timeout=30,
        )
        checks["new_page_state"] = new_driver.eval("window.__d1App.state()")
        checks["new_page_view"] = new_driver.eval("window.__d1App.view()")
        new_driver.wait_until(
            "Boolean(document.querySelector('[data-d1=\"calendar\"]'))"
            " || Boolean(document.querySelector('[data-d1=\"setup\"]'))",
            what="新页实际业务 DOM",
            timeout=60,
        )
        checks["new_page_ready"] = checks["new_page_state"] == "ready"
        checks["new_page_has_calendar"] = bool(
            new_driver.eval("Boolean(document.querySelector('[data-d1=\"calendar\"]'))")
        )
        checks["new_page_has_setup"] = bool(
            new_driver.eval("Boolean(document.querySelector('[data-d1=\"setup\"]'))")
        )
        checks["new_page_business_dom"] = bool(
            checks["new_page_has_calendar"] or checks["new_page_has_setup"]
        )
        checks["new_page_business_visible"] = checks["new_page_business_dom"]
        checks["restore_notice"] = new_driver.eval(
            "document.querySelector('[data-d1=\"restore-notice\"]').innerText"
        )
        checks["restore_notice_present"] = "恢复前保护副本" in str(
            checks["restore_notice"]
        )
        import webview

        old_destroy_deadline = time.monotonic() + 30
        while time.monotonic() < old_destroy_deadline:
            if window not in list(webview.windows):
                break
            time.sleep(0.05)
        checks["old_window_destroyed"] = window not in list(webview.windows)
        assert "恢复前保护副本" in str(checks["restore_notice"]), checks["restore_notice"]
        assert checks["new_page_view"] in ("workbench", "setup"), checks

        # Compare restored target to the old source through read-only fingerprints.
        from tests.local import backup_fixture_support as fixture

        target_db = fixture.database_fingerprint(
            runtime.db_path, include_runtime_fields=True
        )
        target_business = fixture.database_fingerprint(runtime.db_path)
        target_resources = fixture.resource_fingerprint(config["data_dir"])
        checks["database_sha256"] = target_db["fingerprint_sha256"]
        checks["database_business_sha256"] = target_business["fingerprint_sha256"]
        checks["resource_sha256"] = target_resources.get("fingerprint_sha256")
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
        if not checks["database_equal_business"]:
            source_tables = source["database_business"].get("tables", {})
            target_tables = target_business.get("tables", {})
            checks["database_diff_tables"] = sorted(
                name
                for name in set(source_tables) | set(target_tables)
                if source_tables.get(name, {}).get("rows_sha256")
                != target_tables.get(name, {}).get("rows_sha256")
            )
        if not checks["database_equal_full"]:
            source_tables = source["database"].get("tables", {})
            target_tables = target_db.get("tables", {})
            checks["database_full_diff_tables"] = sorted(
                name
                for name in set(source_tables) | set(target_tables)
                if source_tables.get(name, {}).get("rows_sha256")
                != target_tables.get(name, {}).get("rows_sha256")
            )
        if not checks["resources_equal"]:
            checks["resource_diff"] = {
                "source": source["resources"].get("files"),
                "target": target_resources.get("files"),
            }

        if config.get("post"):
            from maintenance_source_post import run_post_checks

            run_post_checks(new_driver, host_api, source, config, checks)

        # Close the new window through the real window object; process cleanup
        # still owns the latest bundle/server/executor.  A destroy call that
        # raises or leaves a live window is not driver completion.
        destroy_ok = _destroy_owned_windows([new_window, window])
        checks["driver_destroy_confirmed"] = destroy_ok
        if not destroy_ok:
            checks["new_window_destroy_error"] = "owned window destroy not confirmed"
    except Exception as exc:  # noqa: BLE001 - summary carries the first failure
        checks["driver_error"] = f"{type(exc).__name__}: {exc}"
        checks["driver_trace"] = traceback.format_exc()
        try:
            checks["failure_view"] = driver.eval("window.__d1App.view()")
            checks["failure_close_state"] = driver.eval(
                "JSON.stringify(window.__d1App.closeState())"
            )
            checks["failure_body_text"] = driver.eval("document.body.innerText")
            checks["failure_panel_text"] = driver.eval(
                "document.querySelector('[data-d1=\"backup-restore-panel\"]')"
                " ? document.querySelector('[data-d1=\"backup-restore-panel\"]').innerText : null"
            )
            checks["failure_buttons"] = driver.eval(
                "JSON.stringify([...document.querySelectorAll('button')].map(b=>({"
                "text:(b.innerText||'').trim(),disabled:!!b.disabled,"
                "visible:(()=>{const r=b.getBoundingClientRect();return r.width>0&&r.height>0})()"
                "})))"
            )
            if dialog_calls is not None:
                checks["failure_dialog_calls"] = list(dialog_calls)
        except Exception:  # noqa: BLE001 - diagnostics only
            pass
        summary["ok"] = False
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


def _best_effort_destroy(candidate) -> None:
    try:
        candidate.destroy()
    except Exception:  # noqa: BLE001
        pass


def run_source_verify(args) -> int:
    summary: dict[str, Any] = {"phase": "b3-source-window", "checks": {}}
    checks = summary["checks"]
    config = _validate_config(args, _load_config(args))
    case = config["case"]
    summary["case"] = case
    summary["config"] = {
        "root": str(config["root"]),
        "data_dir": str(config["data_dir"]),
        "credential_root": str(config["credential_root"]),
        "source_data_dir": str(config["source_data_dir"]),
        "source_credential_root": str(config["source_credential_root"]),
        "source_package": str(config["source_package"]),
        "target_backup": str(config["target_backup"]),
        "capacity_photo_count": config["capacity_photo_count"],
    }
    if config["frontend"]:
        args.frontend = str(config["frontend"])
    _preflight_paths(config)

    # The guard and isolated environment are installed BEFORE any Runtime,
    # executor or fixture can touch the network or the teacher's LOCALAPPDATA.
    guard = NetworkGuard(config["evidence_dir"])
    guard.install()
    localappdata = config["root"] / "localappdata"
    localappdata.mkdir(parents=True, exist_ok=True)
    os.environ["LOCALAPPDATA"] = str(localappdata)
    os.environ["APP_DISABLE_DOTENV"] = "1"
    os.environ.pop("KGM_LOCAL_DATA_DIR", None)
    guard_dir = guard.install_child_guard()
    existing_pythonpath = os.environ.get("PYTHONPATH", "")
    os.environ["PYTHONPATH"] = (
        str(guard_dir)
        + (os.pathsep + existing_pythonpath if existing_pythonpath else "")
    )
    os.environ["KGM_B3_NETWORK_GUARD_LOG"] = str(guard.log_path)
    os.environ["KGM_B3_GUARD_FAILURE"] = str(guard.failure_path)
    summary["network_guard"] = {
        "log": str(guard.log_path),
        "child_guard": str(guard_dir / "sitecustomize.py"),
        "loopback_only": True,
    }
    checks["child_guard_verified"] = guard.verify_child_guard()
    if not checks["child_guard_verified"]:
        raise SourceVerifyError("spawned Python guard self-test failed")

    import d1_main

    out_path = Path(config["out_path"])
    lifecycle = LifecycleManager()
    service = None
    runtime = None
    finished = threading.Event()
    cleanup_done = threading.Event()
    window = None
    closed_ok = False
    dialog_calls: list[dict[str, Any]] = []
    try:
        # Old source package first, then seed the target BEFORE build_runtime
        # starts the real executor.  No queued fixture task can race a claim.
        if case in (
            "plaintext",
            "setup",
            "late",
            "reopen-failure",
            "reopen-service-failure",
            "cancel-gates",
        ):
            source = _prepare_source(config, summary)
        elif case in ("protection", "capacity"):
            source = None
        else:
            source = None
        if case in (
            "plaintext",
            "encrypted-backup",
            "capacity",
            "late",
            "reopen-failure",
            "reopen-service-failure",
            "cancel-window",
            "cancel-gates",
        ):
            target_pre = _prepare_target(config, summary)
        elif case == "protection" and config.get("seed_target"):
            target_pre = _prepare_target(config, summary)
        elif case in ("protection", "restart", "ai-cold"):
            target_dir = Path(config["data_dir"])
            if not target_dir.is_dir() or not any(target_dir.iterdir()):
                raise SourceVerifyError(
                    f"{case} 必须读取既有目标数据；拒绝在空目录上新建"
                )
            checks[
                "ai_cold_existing_target" if case == "ai-cold" else f"{case}_existing_target"
            ] = True
            target_pre = {}
        elif case == "setup":
            target_pre = {}
        else:
            target_pre = {}
        if case == "ai-cold":
            # Start the app without its own executor, capture the queued-task
            # baseline, then start one real AiExecutor in the driver.
            d1_main._start_ai_executor = (
                lambda _runtime, _args: (None, "b3-deferred-cold-start", False)
            )
        service, host_api, runtime = d1_main.build_runtime(args)
        if case in ("protection", "capacity", "cancel-window"):
            from app.local.backup_snapshot import SnapshotService
            from tests.local import backup_fixture_support as fixture

            verifier = SnapshotService(
                runtime, app_version="b3-protection", source_identity={"b3": "protection"}
            )
            verified = verifier.verify(
                config["source_package"],
                password=(
                    str(config.get("source_password"))
                    if case in ("capacity", "cancel-window")
                    else None
                ),
                cancel=threading.Event(),
            )
            source = {
                "database": fixture.database_fingerprint(
                    verified.database_path, include_runtime_fields=True
                ),
                "database_business": fixture.database_fingerprint(verified.database_path),
                "resources": fixture.resource_fingerprint(verified.resources_root),
                "latest_raw": _latest_plan_raw(verified.database_path),
                "asset_counts": _resource_asset_counts(
                    verified.database_path, verified.resources_root
                ),
            }
            try:
                verifier.discard_verified(verified)
            except Exception:  # noqa: BLE001
                pass
            target_pre = {}
        if case in ("plaintext", "encrypted-backup"):
            # The target backup is created after runtime prepare/executor
            # classification; refresh the comparison baseline before the window.
            from tests.local import backup_fixture_support as fixture

            target_pre["database"] = fixture.database_fingerprint(
                runtime.db_path, include_runtime_fields=True
            )
            target_pre["database_business"] = fixture.database_fingerprint(runtime.db_path)
            target_pre["resources"] = fixture.resource_fingerprint(config["data_dir"])
            summary["target_pre"]["database_sha256"] = target_pre["database"]["fingerprint_sha256"]
            summary["target_pre"]["database_business_sha256"] = target_pre["database_business"]["fingerprint_sha256"]
            summary["target_pre"]["resource_sha256"] = target_pre["resources"].get("fingerprint_sha256")
            summary["target_pre"]["resource_files"] = target_pre["resources"].get("files")
        executor = getattr(runtime, "ai_executor", None)
        snapshot = executor.active_snapshot() if executor is not None else {}
        idle = not any(
            bool(snapshot.get(key))
            for key in ("live", "in_flight", "attempt_in_flight", "unconfirmed", "pending_persist")
        )
        checks["executor_initial_idle"] = idle
        if not idle:
            raise SourceVerifyError(f"执行器启动后仍有在途任务: {snapshot!r}")
        # Version discovery is intentionally disabled: the source window must
        # not perform a GitHub update check during this B3 run.
        host_api._update_manager = None
        checks["update_network_disabled"] = True

        bundle = LifecycleBundle(
            generation=lifecycle.next_generation(),
            service=service,
            host_api=host_api,
            runtime=runtime,
        )
        lifecycle.install(bundle)
        if not service.start_and_wait():
            raise SourceVerifyError(f"目标本地服务启动失败: {service.error}")
        import webview

        window = webview.create_window(
            "B3 源码恢复验证窗口",
            url=f"http://127.0.0.1:{service.port}/",
            js_api=host_api,
            width=1180,
            height=820,
            min_size=(760, 560),
            text_select=True,
        )
        bundle.window = window
        host_api._bind_window(window)
        host_api._verify_save_dir = Path(config["word_dir"])
        d1_main._install_close_handlers(window, host_api, runtime)
        bundle.retire_destroy = lambda: d1_main._retire_destroy_window(bundle)
        host_api._bind_maintenance(
            d1_main._build_maintenance_host(args, runtime, lifecycle, bundle)
        )

        # Controlled native-dialog substitute: only the configured synthetic
        # backup target and source package are returned.
        open_queue: list[Any] = []
        save_queue: list[Any] = []
        if case == "encrypted-backup":
            save_queue = [config["target_backup"]]
            open_queue = []
        elif case in ("cancel-window", "cancel-gates"):
            save_queue = []
            open_queue = [[config["source_package"]], [config["source_package"]]]
        elif case in (
            "protection",
            "capacity",
            "late",
            "reopen-failure",
            "reopen-service-failure",
        ):
            save_queue = []
            open_queue = [[config["source_package"]]]
        elif case == "ai-cold":
            save_queue = []
            open_queue = []
        elif case == "setup":
            open_queue = [
                None,
                [config["bad_package"]],
                [config["encrypted_package"]],
            ]
        else:
            save_queue = [config["target_backup"]]
            open_queue = [[config["source_package"]]]

        def fake_dialog(dialog_type, *a, **kwargs):
            save = bool(kwargs.get("save_filename"))
            dialog_calls.append(
                {
                    "save": save,
                    "save_filename": kwargs.get("save_filename"),
                    "allow_multiple": kwargs.get("allow_multiple"),
                }
            )
            if save:
                return save_queue.pop(0) if save_queue else None
            return open_queue.pop(0) if open_queue else None

        window.create_file_dialog = fake_dialog

        def driver_task():
            if case == "cancel-gates":
                from maintenance_source_cancel_gates import run_cancel_gates_driver

                run_cancel_gates_driver(
                    window,
                    host_api,
                    runtime,
                    lifecycle,
                    config,
                    summary,
                    checks,
                    source,
                    target_pre,
                    out_path,
                    finished,
                    dialog_stub=fake_dialog,
                    dialog_calls=dialog_calls,
                )
            elif case == "cancel-window":
                from maintenance_source_cancel import run_cancel_driver

                run_cancel_driver(
                    window,
                    host_api,
                    runtime,
                    lifecycle,
                    config,
                    summary,
                    checks,
                    source,
                    target_pre,
                    out_path,
                    finished,
                    dialog_stub=fake_dialog,
                    dialog_calls=dialog_calls,
                )
            elif case == "ai-cold":
                from maintenance_source_ai_cold import run_ai_cold_driver

                run_ai_cold_driver(
                    window,
                    host_api,
                    runtime,
                    lifecycle,
                    config,
                    summary,
                    checks,
                    source,
                    target_pre,
                    out_path,
                    finished,
                    dialog_stub=fake_dialog,
                    dialog_calls=dialog_calls,
                )
            elif case in ("reopen-failure", "reopen-service-failure"):
                from maintenance_source_reopen import run_reopen_failure_driver

                run_reopen_failure_driver(
                    window,
                    host_api,
                    runtime,
                    lifecycle,
                    config,
                    summary,
                    checks,
                    source,
                    target_pre,
                    out_path,
                    finished,
                    dialog_stub=fake_dialog,
                    dialog_calls=dialog_calls,
                )
            elif case == "late":
                from maintenance_source_late import run_late_driver

                run_late_driver(
                    window,
                    host_api,
                    runtime,
                    lifecycle,
                    config,
                    summary,
                    checks,
                    source,
                    target_pre,
                    out_path,
                    finished,
                    dialog_stub=fake_dialog,
                    dialog_calls=dialog_calls,
                )
            elif case in ("protection", "capacity"):
                from maintenance_source_protection import run_protection_driver

                run_protection_driver(
                    window,
                    host_api,
                    runtime,
                    lifecycle,
                    config,
                    summary,
                    checks,
                    source,
                    target_pre,
                    out_path,
                    finished,
                    dialog_stub=fake_dialog,
                    dialog_calls=dialog_calls,
                )
            elif case == "encrypted-backup":
                from maintenance_source_encrypted import run_encrypted_driver

                run_encrypted_driver(
                    window,
                    host_api,
                    runtime,
                    lifecycle,
                    config,
                    summary,
                    checks,
                    source,
                    target_pre,
                    out_path,
                    finished,
                    dialog_stub=fake_dialog,
                    dialog_calls=dialog_calls,
                )
            elif case == "restart":
                from maintenance_source_restart import run_restart_driver

                run_restart_driver(
                    window,
                    host_api,
                    runtime,
                    lifecycle,
                    config,
                    summary,
                    checks,
                    source,
                    out_path,
                    finished,
                    dialog_stub=fake_dialog,
                    dialog_calls=dialog_calls,
                )
            elif case == "setup":
                from maintenance_source_setup import run_setup_driver

                run_setup_driver(
                    window,
                    host_api,
                    runtime,
                    lifecycle,
                    config,
                    summary,
                    checks,
                    source,
                    out_path,
                    finished,
                    dialog_stub=fake_dialog,
                    dialog_calls=dialog_calls,
                )
            else:
                _run_driver(
                    window,
                    host_api,
                    runtime,
                    lifecycle,
                    config,
                    summary,
                    checks,
                    source,
                    target_pre,
                    out_path,
                    finished,
                    dialog_stub=fake_dialog,
                    dialog_calls=dialog_calls,
                )

        def watchdog():
            import webview as _watchdog_webview

            deadline = time.monotonic() + config["timeout"] + 120.0
            while time.monotonic() < deadline:
                if cleanup_done.is_set():
                    current = lifecycle.current()
                    current_window = current.window if current is not None else None
                    try:
                        live = list(_watchdog_webview.windows)
                    except Exception:  # noqa: BLE001
                        live = []
                    owned_live = [
                        candidate
                        for candidate in (window, current_window)
                        if candidate is not None and candidate in live
                    ]
                    if not owned_live:
                        return
                time.sleep(0.2)
            checks["watchdog_timeout"] = True
            summary["watchdog_terminated"] = True
            summary["ok"] = False
            try:
                _write_summary(summary, out_path)
            except Exception:  # noqa: BLE001 - hard exit still runs
                pass
            candidates = [window]
            current = lifecycle.current()
            if current is not None and current.window is not None:
                candidates.append(current.window)
            try:
                candidates.extend(list(_watchdog_webview.windows))
            except Exception:  # noqa: BLE001
                pass
            seen = set()
            for candidate in candidates:
                if candidate is None or id(candidate) in seen:
                    continue
                seen.add(id(candidate))
                # Best effort only: a native destroy may block; never await it
                # on the hard-timeout path.
                threading.Thread(
                    target=_best_effort_destroy,
                    args=(candidate,),
                    daemon=True,
                ).start()
            os._exit(3)

        threading.Thread(target=watchdog, daemon=True).start()
        webview.start(gui="edgechromium", func=driver_task)
        finished.set()
        closed_ok = bool(lifecycle.close_latest(timeout=10.0))
        checks["latest_bundle_closed"] = closed_ok
        if not closed_ok:
            checks["runtime_lock_retained"] = True
        cleanup_done.set()
        service = None
        runtime = None
    except Exception as exc:  # noqa: BLE001 - first failure is evidence
        checks["startup_error"] = f"{type(exc).__name__}: {exc}"
        checks["startup_trace"] = traceback.format_exc()
    finally:
        finished.set()
        if lifecycle.current() is not None:
            try:
                closed_ok = bool(lifecycle.close_latest(timeout=10.0))
            except Exception:  # noqa: BLE001
                closed_ok = False
            checks["latest_bundle_closed"] = closed_ok
        cleanup_done.set()
        if runtime is not None and closed_ok:
            try:
                d1_main._dispose_executor(runtime)
                runtime.dispose()
            except Exception:  # noqa: BLE001
                pass
        elif runtime is not None:
            checks["runtime_lock_retained"] = True
        if service is not None and closed_ok:
            d1_main._stop_service(service)
        logged_attempts = guard.log_attempts()
        checks["network_guard_attempts"] = guard.attempts()
        checks["network_guard_logged_attempts"] = logged_attempts
        checks["network_guard_audit_ok"] = guard.audit_ok() and logged_attempts is not None
        checks["network_guard_zero"] = (
            guard.attempts() == 0 and logged_attempts == 0
        )
        checks["dialog_call_count"] = len(dialog_calls)
        checks["dialog_calls"] = list(dialog_calls)
        if case == "cancel-gates":
            required = (
                "cancel_gate_scope_verify_return",
                "cancel_verify_gate_held",
                "cancel_verify_gate_cancel_seen",
                "cancel_verify_gate_released",
                "cancel_verify_ui_cancelled",
                "cancel_verify_no_transport_stop",
                "cancel_verify_no_switch",
                "cancel_verify_target_unchanged",
                "cancel_protection_gate_held",
                "cancel_protection_gate_cancel_seen",
                "cancel_protection_gate_released",
                "cancel_protection_ui_cancelled",
                "cancel_protection_no_transport_stop",
                "cancel_protection_no_switch",
                "cancel_protection_target_unchanged",
                "driver_destroy_confirmed",
                "latest_bundle_closed",
                "executor_initial_idle",
                "update_network_disabled",
                "child_guard_verified",
                "network_guard_audit_ok",
                "network_guard_zero",
            )
        elif case == "cancel-window":
            required = (
                "cancel_preview_phase_ready",
                "cancel_preview_ui_cancelled",
                "cancel_preview_no_switch",
                "cancel_preview_target_unchanged",
                "cancel_too_late_not_cancelled",
                "cancel_switch_completed",
                "cancel_new_page_ready",
                "cancel_protection_exists",
                "database_equal_full",
                "database_equal_business",
                "resources_equal",
                "driver_destroy_confirmed",
                "latest_bundle_closed",
                "executor_initial_idle",
                "update_network_disabled",
                "child_guard_verified",
                "network_guard_audit_ok",
                "network_guard_zero",
            )
        elif case == "ai-cold":
            required = (
                "ai_cold_existing_target",
                "ai_cold_new_page_ready",
                "ai_cold_baseline_captured",
                "ai_cold_executor_started",
                "ai_cold_executor_disposed",
                "ai_cold_resources_unchanged",
                "ai_cold_source_task_pending",
                "ai_cold_task_paused",
                "ai_cold_target_meta_exact",
                "ai_cold_task_reason_restart",
                "ai_cold_only_expected_columns",
                "ai_cold_no_execution",
                "ai_cold_no_claim_event",
                "ai_cold_no_send_event",
                "ai_cold_no_provider_event",
                "ai_cold_only_expected_delta",
                "ai_cold_executor_idle",
                "resources_equal",
                "driver_destroy_confirmed",
                "latest_bundle_closed",
                "executor_initial_idle",
                "update_network_disabled",
                "child_guard_verified",
                "network_guard_audit_ok",
                "network_guard_zero",
            )
        elif case == "reopen-service-failure":
            required = (
                "reopen_preview_ready",
                "reopen_service_failure_injected",
                "reopen_injected_failure_used",
                "reopen_error_visible",
                "reopen_error_message",
                "reopen_protection_visible",
                "reopen_protection_exists",
                "reopen_protection_matches_pre_restore",
                "reopen_data_committed",
                "reopen_old_window_kept",
                "reopen_recovery_required",
                "reopen_normal_close",
                "runtime_lock_retained",
                "database_equal_full",
                "database_equal_business",
                "resources_equal",
                "driver_destroy_confirmed",
                "executor_initial_idle",
                "update_network_disabled",
                "child_guard_verified",
                "network_guard_audit_ok",
                "network_guard_zero",
            )
        elif case == "reopen-failure":
            required = (
                "reopen_preview_ready",
                "reopen_injected_failure_used",
                "reopen_error_visible",
                "reopen_error_message",
                "reopen_protection_visible",
                "reopen_protection_exists",
                "reopen_protection_matches_pre_restore",
                "reopen_data_committed",
                "reopen_old_window_kept",
                "reopen_recovery_required",
                "reopen_normal_close",
                "database_equal_full",
                "database_equal_business",
                "resources_equal",
                "driver_destroy_confirmed",
                "latest_bundle_closed",
                "executor_initial_idle",
                "update_network_disabled",
                "child_guard_verified",
                "network_guard_audit_ok",
                "network_guard_zero",
            )
        elif case == "late":
            required = (
                "late_restore_completed",
                "late_old_window_destroyed",
                "late_new_page_ready",
                "late_old_bootstrap_retired",
                "late_old_page_ready_rejected",
                "late_old_page_busy_rejected",
                "late_old_business_ready_rejected",
                "late_old_guard_retired",
                "late_old_native_save_rejected",
                "late_old_observation_save_rejected",
                "late_old_close_rejected",
                "late_old_maintenance_rejected",
                "late_old_confirm_rejected",
                "late_new_old_ticket_rejected",
                "late_new_old_preview_rejected",
                "late_old_token_rejected",
                "late_new_token_read",
                "late_new_token_preview",
                "late_config_preview_hmac_rejected",
                "late_new_work_unchanged",
                "database_equal_full",
                "database_equal_business",
                "resources_equal",
                "driver_destroy_confirmed",
                "latest_bundle_closed",
                "executor_initial_idle",
                "update_network_disabled",
                "child_guard_verified",
                "network_guard_audit_ok",
                "network_guard_zero",
            )
        elif case == "protection":
            required = (
                "restore_preview_ready",
                "new_window_created",
                "new_page_ready",
                "new_page_business_visible",
                "new_page_has_calendar",
                "restore_notice_present",
                "old_window_destroyed",
                "database_equal_full",
                "database_equal_business",
                "resources_equal",
                "protection_copy_exists",
                "protection_copy_inside_target",
                "protection_source_preserved",
                "protection_copy_distinct_from_source",
                "protection_copy_database_equal",
                "protection_copy_business_equal",
                "protection_copy_resources_equal",
                "protection_copy_matches_pre_restore_body",
                "restored_matches_source_body",
                "protection_copy_distinct_body_marker",
                "driver_destroy_confirmed",
                "latest_bundle_closed",
                "executor_initial_idle",
                "update_network_disabled",
                "child_guard_verified",
                "network_guard_audit_ok",
                "network_guard_zero",
            )
        elif case == "capacity":
            required = (
                "restore_preview_ready",
                "new_window_created",
                "new_page_ready",
                "new_page_business_visible",
                "new_page_has_calendar",
                "restore_notice_present",
                "old_window_destroyed",
                "database_equal_full",
                "database_equal_business",
                "resources_equal",
                "capacity_photo_requirement",
                "capacity_original_requirement",
                "capacity_resource_counts_equal",
                "driver_destroy_confirmed",
                "latest_bundle_closed",
                "executor_initial_idle",
                "update_network_disabled",
                "child_guard_verified",
                "network_guard_audit_ok",
                "network_guard_zero",
            )
        elif case == "encrypted-backup":
            required = (
                "plaintext_unack_ack_visible",
                "plaintext_unack_submit_disabled",
                "plaintext_unack_no_file",
                "encrypted_empty_disabled",
                "encrypted_empty_no_terminal",
                "encrypted_no_file_before_password",
                "encrypted_requires_password",
                "encrypted_completed",
                "target_backup_verified",
                "target_backup_database_equal",
                "target_backup_resources_equal",
                "driver_destroy_confirmed",
                "latest_bundle_closed",
                "executor_initial_idle",
                "update_network_disabled",
                "child_guard_verified",
                "network_guard_audit_ok",
                "network_guard_zero",
            )
        elif case == "restart":
            required = (
                "restart_workbench",
                "restart_plan_opened",
                "restart_body_marker",
                "restart_existing_target",
                "driver_destroy_confirmed",
                "latest_bundle_closed",
                "executor_initial_idle",
                "update_network_disabled",
                "child_guard_verified",
                "network_guard_audit_ok",
                "network_guard_zero",
            )
        elif case == "setup":
            required = (
                "initial_page_ready",
                "setup_visible",
                "setup_restore_only",
                "setup_cancel_silent",
                "bad_package_error",
                "wrong_password_error",
                "setup_form_preserved",
                "setup_no_temp_profile",
                "setup_still_visible",
                "setup_no_calendar",
                "setup_negative_full41_unchanged",
                "setup_negative_resources_unchanged",
                "setup_correct_retry_preview",
                "setup_retry_cancel_form_preserved",
                "setup_first_restore_completed",
                "setup_empty_protection_verified_full",
                "setup_protection_ui_restore_completed",
                "setup_returned_empty_profile",
                "setup_empty_full41_restored",
                "driver_destroy_confirmed",
                "latest_bundle_closed",
                "executor_initial_idle",
                "update_network_disabled",
                "child_guard_verified",
                "network_guard_audit_ok",
                "network_guard_zero",
            )
        else:
            required = (
            "initial_page_ready",
            "settings_entry",
            "panel_open",
            "backup_completed",
            "target_backup_verified",
            "restore_preview_ready",
            "new_window_created",
            "new_page_ready",
            "new_page_business_visible",
            "new_page_has_calendar",
            "restore_notice_present",
            "old_window_destroyed",
            "database_equal_full",
            "database_equal_business",
            "resources_equal",
            "latest_bundle_closed",
            "executor_initial_idle",
            "update_network_disabled",
            "child_guard_verified",
            "network_guard_audit_ok",
            "network_guard_zero",
            "driver_destroy_confirmed",
            )
            if config.get("post"):
                required = required + (
                    "post_editor_opened",
                    "post_dirty",
                    "post_saved",
                    "post_history_detail",
                    "post_history_source_visible",
                    "post_obs_photos",
                    "post_history_photos",
                    "post_word_saved",
                )
        if case == "restart":
            extra = []
            if config.get("restart_require_stable_versions"):
                extra.append("restart_versions_stable")
            if config.get("restart_user_save_marker"):
                extra.extend(
                    (
                        "restart_user_save",
                        "restart_only_user_version_added",
                        "restart_saved_marker_visible",
                    )
                )
            required = tuple(required) + tuple(extra)
        checks["missing_checks"] = [key for key in required if key not in checks]
        checks["failed_checks"] = [
            key for key in required if key in checks and checks[key] is not True
        ]
        summary["ok"] = (
            all(checks.get(key) is True for key in required)
            and not checks.get("watchdog_timeout")
            and not checks.get("driver_error")
            and not checks.get("startup_error")
        )
        _write_summary(summary, out_path)
        print(json.dumps({"ok": summary["ok"], "out": str(out_path)}, ensure_ascii=False))
    return 0 if summary.get("ok") else 3
