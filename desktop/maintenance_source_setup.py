"""B3 DOM case: first-run setup restore, empty protection and empty rollback.

The driver starts on the real setup page (``local_profile`` empty), keeps the
existing native-cancel/bad-package/wrong-password negatives, then proves the
complete P06 path through the real Vue panel, host bridge and restore core:

1. correct-password retry reaches a real preview and is cancelled with the
   four unsubmitted setup fields unchanged;
2. a full source package is restored through the setup restore entry, the old
   window is retired and the new window shows the calendar plus its automatic
   pre-restore protection location;
3. that automatic empty protection package is verified read-only and must be
   exactly the pre-UI empty baseline (41 business tables, resources, profile 0);
4. the same empty package is restored from the new workbench settings entry;
   the third window returns to the setup page and the final database/resources
   must again equal the initial empty baseline.

No real supplier, WebDAV, frozen EXE, teacher data or credential root is used.
Native file dialogs are module-owned substitutes bound to each window this
driver creates; every returned path is resolved under ``config["root"]``.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import traceback
from pathlib import Path
from typing import Any

from maintenance_lifecycle import LifecycleManager

_PROTECTION_PREFIX = "恢复前保护副本："
_PROTECTION_SUFFIX = "。自动保留，不会自动删除。"
_BUSINESS_TABLE_COUNT = 41
_SETUP_CHECKS = (
    "setup_negative_full41_unchanged",
    "setup_negative_resources_unchanged",
    "setup_correct_retry_preview",
    "setup_retry_cancel_form_preserved",
    "setup_first_restore_completed",
    "setup_empty_protection_verified_full",
    "setup_protection_ui_restore_completed",
    "setup_returned_empty_profile",
    "setup_empty_full41_restored",
)


class SetupFlowError(RuntimeError):
    """A bounded first-run setup driver failure."""


class _SetupDialogs:
    """Module-owned native dialog substitute for one exact window instance.

    ``save`` calls are never expected by this case and return ``None`` (a
    native cancel).  Each ``open`` call consumes exactly one synthetic path
    supplied by the driver.  The path is validated when it is queued, so a
    late/extra native call can never escape ``config["root"]``.
    """

    def __init__(
        self,
        root: Path,
        calls: list[dict[str, Any]] | None,
        label: str,
    ) -> None:
        self._root = root
        self._calls = calls
        self._label = label
        self._lock = threading.Lock()
        self._open_queue: list[str | None] = []
        self.unexpected = 0

    def expect_open(self, path: Path | None, *, label: str) -> None:
        value: str | None
        if path is None:
            value = None
        else:
            value = str(_require_under(self._root, path, label, must_exist=True))
        with self._lock:
            if self._open_queue:
                raise SetupFlowError(f"{label}: 上一个原生选择尚未消费")
            self._open_queue.append(value)

    def pending(self) -> int:
        with self._lock:
            return len(self._open_queue)

    def __call__(self, dialog_type, *args, **kwargs):
        save = bool(kwargs.get("save_filename"))
        record: dict[str, Any] = {
            "save": save,
            "save_filename": kwargs.get("save_filename"),
            "allow_multiple": kwargs.get("allow_multiple"),
            "controller": self._label,
        }
        if save:
            # This case never creates a backup from the setup window.
            record["result"] = "unexpected_save_cancel"
            with self._lock:
                self.unexpected += 1
            if self._calls is not None:
                self._calls.append(record)
            return None
        with self._lock:
            if self._open_queue:
                value = self._open_queue.pop(0)
            else:
                value = None
                self.unexpected += 1
                record["error"] = "empty_open_queue"
        record["path"] = value
        if self._calls is not None:
            self._calls.append(record)
        if value is None:
            return None
        return [value]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_under(
    root: Path,
    raw: str | Path,
    label: str,
    *,
    must_exist: bool = False,
) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        raise SetupFlowError(f"{label} 必须是绝对路径: {raw!r}")
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise SetupFlowError(f"{label} 不在本次合成 root 内: {raw!r}") from exc
    if must_exist and not resolved.is_file():
        raise SetupFlowError(f"{label} 不是现有文件: {resolved}")
    return resolved


def _profile_count(db_path: Path) -> int:
    connection = sqlite3.connect(
        f"{Path(db_path).resolve().as_uri()}?mode=ro", uri=True
    )
    try:
        return int(
            connection.execute("SELECT count(*) FROM local_profile").fetchone()[0]
        )
    finally:
        connection.close()


def _capture_fixture(runtime, data_dir: str | Path) -> dict[str, Any]:
    """Read-only semantic baseline: full 41 tables and all managed resources."""
    from tests.local import backup_fixture_support as fixture

    return {
        "database": fixture.database_fingerprint(
            runtime.db_path, include_runtime_fields=True
        ),
        "database_business": fixture.database_fingerprint(runtime.db_path),
        "resources": fixture.resource_fingerprint(data_dir),
    }


def _fingerprint_brief(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "sha256": value.get("fingerprint_sha256"),
        "tables": len(value.get("tables") or {}),
    }


def _tables_of(value: dict[str, Any]) -> dict[str, Any]:
    return dict(value.get("tables") or {})


def _table_diff(left: dict[str, Any], right: dict[str, Any]) -> list[str]:
    left_tables = _tables_of(left)
    right_tables = _tables_of(right)
    return sorted(
        name
        for name in set(left_tables) | set(right_tables)
        if left_tables.get(name, {}).get("rows_sha256")
        != right_tables.get(name, {}).get("rows_sha256")
    )


def _assert_same_database(
    actual: dict[str, Any], expected: dict[str, Any], label: str
) -> None:
    if actual.get("fingerprint_sha256") != expected.get("fingerprint_sha256"):
        raise SetupFlowError(
            f"{label} 数据库 full41 不一致；差异表={_table_diff(actual, expected)}"
        )
    if len(_tables_of(actual)) != _BUSINESS_TABLE_COUNT:
        raise SetupFlowError(
            f"{label} 数据库表数不是 {_BUSINESS_TABLE_COUNT}: "
            f"{len(_tables_of(actual))}"
        )


def _assert_same_resources(
    actual: dict[str, Any], expected: dict[str, Any], label: str
) -> None:
    if actual.get("fingerprint_sha256") != expected.get("fingerprint_sha256"):
        raise SetupFlowError(f"{label} 资源指纹不一致")


def _assert_baseline(
    actual: dict[str, Any], expected: dict[str, Any], label: str
) -> None:
    _assert_same_database(actual["database"], expected["database"], label)
    _assert_same_resources(actual["resources"], expected["resources"], label)


def _visible_all_script(selectors: tuple[str, ...] | list[str]) -> str:
    return (
        "(function(){const sels="
        + json.dumps(list(selectors), ensure_ascii=False)
        + ";const vis=(sel)=>{const e=document.querySelector(sel);"
        " if(!e) return false; const r=e.getBoundingClientRect();"
        " const s=getComputedStyle(e); return r.width>0 && r.height>0"
        " && s.visibility!=='hidden' && s.display!=='none';};"
        " return sels.every(vis);})()"
    )


def _wait_visible_all(
    driver,
    selectors: tuple[str, ...] | list[str],
    *,
    what: str,
    timeout: float,
) -> None:
    driver.wait_until(_visible_all_script(selectors), what=what, timeout=timeout)


def _wait_visible_enabled(
    driver, selector: str, *, what: str, timeout: float = 15.0
) -> None:
    driver.wait_until(
        "(function(){const e=document.querySelector("
        + json.dumps(selector)
        + "); if(!e) return false; const r=e.getBoundingClientRect();"
        " const s=getComputedStyle(e); return r.width>0 && r.height>0"
        " && s.visibility!=='hidden' && s.display!=='none' && !e.disabled;})()",
        what=what,
        timeout=timeout,
    )


def _wait_new_bundle(
    lifecycle: LifecycleManager,
    previous_generation: int,
    timeout: float,
):
    deadline = time.monotonic() + max(1.0, float(timeout))
    while time.monotonic() < deadline:
        current = lifecycle.current()
        if (
            current is not None
            and current.generation > previous_generation
            and current.window is not None
        ):
            return current
        time.sleep(0.05)
    raise SetupFlowError("新的 Window/host generation 未在时限内出现")


def _wait_window_gone(window, timeout: float = 30.0) -> bool:
    try:
        import webview
    except Exception:  # noqa: BLE001 - unit fake without webview
        return False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if window not in list(webview.windows):
                return True
        except Exception:  # noqa: BLE001 - unknown is never success
            return False
        time.sleep(0.05)
    try:
        return window not in list(webview.windows)
    except Exception:  # noqa: BLE001
        return False


def _protection_path_from_notice(
    notice: object, root: Path, label: str
) -> tuple[Path, str]:
    text = str(notice or "")
    if _PROTECTION_PREFIX not in text or _PROTECTION_SUFFIX not in text:
        raise SetupFlowError(f"{label}: 宿主通知缺少保护副本位置: {text!r}")
    start = text.index(_PROTECTION_PREFIX) + len(_PROTECTION_PREFIX)
    end = text.index(_PROTECTION_SUFFIX, start)
    raw = text[start:end].strip().strip("\"'“”")
    if not raw:
        raise SetupFlowError(f"{label}: 保护副本路径为空")
    path = _require_under(root, raw, label, must_exist=True)
    if path.suffix.lower() != ".kgmbackup":
        raise SetupFlowError(f"{label}: 保护副本扩展名不合法: {path}")
    return path, text


def _assert_protection_operation(
    runtime, protection_path: Path, label: str
) -> dict[str, str]:
    """Prove the package sits in this runtime's real automatic guard tree."""
    data_dir = Path(runtime.data_dir).resolve()
    guard_root = data_dir.parent / f"{data_dir.name}.restore-guard"
    _require_under(guard_root, protection_path, label, must_exist=True)
    operation_id = protection_path.parent.name
    if not operation_id:
        raise SetupFlowError(f"{label}: 操作目录名为空")
    old_dir = data_dir.parent / f"{data_dir.name}.restore-work" / operation_id / "old"
    old_db = old_dir / "db" / "kindergarten.db"
    if not old_db.is_file():
        raise SetupFlowError(f"{label}: 旧组未保留: {old_db}")
    return {
        "operation_id": operation_id,
        "guard_dir": str(protection_path.parent),
        "old_group": str(old_dir),
        "old_group_db": str(old_db),
    }


def _existing_protection_paths(root: Path) -> set[str]:
    paths: set[str] = set()
    try:
        for candidate in root.rglob("pre-restore.kgmbackup"):
            try:
                paths.add(str(candidate.resolve()))
            except OSError:
                continue
    except OSError:
        pass
    return paths


def _verify_protection_package(
    runtime, package: Path, label: str
) -> dict[str, Any]:
    """Read-only verification of an automatic protection package."""
    from app.local.backup_snapshot import SnapshotService
    from tests.local import backup_fixture_support as fixture

    verifier = SnapshotService(
        runtime,
        app_version="b3-setup-protection",
        source_identity={"b3": "setup", "purpose": label},
    )
    verified = None
    try:
        verified = verifier.verify(
            package, password=None, cancel=threading.Event()
        )
        database = fixture.database_fingerprint(
            verified.database_path, include_runtime_fields=True
        )
        resources = fixture.resource_fingerprint(verified.resources_root)
        return {
            "path": str(package),
            "sha256": _sha256_file(package),
            "database": database,
            "database_business": fixture.database_fingerprint(
                verified.database_path
            ),
            "resources": resources,
            "profile_count": _profile_count(verified.database_path),
            "table_count": len(_tables_of(database)),
            "snapshot_id": verified.manifest.get("snapshot_id"),
        }
    finally:
        if verified is not None:
            try:
                verifier.discard_verified(verified)
            except Exception:  # noqa: BLE001 - staging cleanup only
                pass


def _has_inflight_switch(hosts: list[Any]) -> bool:
    for host in hosts:
        maintenance = getattr(host, "_maintenance_host", None)
        ops = getattr(maintenance, "_ops", None)
        if not isinstance(ops, dict):
            continue
        for op in ops.values():
            if isinstance(op, dict) and op.get("phase") in (
                "switching",
                "reopening",
            ):
                return True
    return False


def _record_failure_dom(
    checks: dict[str, Any],
    drivers: list[Any],
    dialog_calls: list[dict[str, Any]] | None,
) -> None:
    for driver in reversed(drivers):
        try:
            checks["failure_body_text"] = driver.eval("document.body.innerText")
            checks["failure_panel_text"] = driver.eval(
                "document.querySelector('[data-d1=\"backup-restore-panel\"]')"
                " ? document.querySelector('[data-d1=\"backup-restore-panel\"]').innerText : null"
            )
            checks["failure_view"] = driver.eval(
                "window.__d1App ? window.__d1App.view() : null"
            )
            checks["failure_buttons"] = driver.eval(
                "JSON.stringify([...document.querySelectorAll('button')].map(b=>({"
                "text:(b.innerText||'').trim(),disabled:!!b.disabled,"
                "visible:(()=>{const r=b.getBoundingClientRect();return r.width>0&&r.height>0})()"
                "})))"
            )
            break
        except Exception:  # noqa: BLE001 - diagnostics only
            continue
    if dialog_calls is not None:
        checks["failure_dialog_calls"] = list(dialog_calls)
        checks["failure_dialog_call_count"] = len(dialog_calls)


def _input_value(driver, key: str):
    return driver.eval(
        "(()=>{const e=document.querySelector('[data-d1=\""
        + key
        + "\"]'); if(!e) return null; const i=e.matches('input,textarea')"
        " ? e : e.querySelector('input,textarea'); return i ? i.value : null;})()"
    )


def run_setup_driver(
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
        _js_set_input,
        _js_visible,
        _js_visible_enabled,
        _open_settings_panel,
        _write_summary,
    )

    del dialog_stub  # main's stub served the three negatives; positives bind below.
    root = Path(config["root"]).resolve()
    data_dir = Path(config["data_dir"]).resolve()
    timeout = float(config.get("timeout") or 240.0)
    source_package = Path(config["source_package"]).resolve()
    source_password = str(config.get("source_password") or "")

    driver = d1_main.JsDriver(window)
    drivers: list[Any] = [driver]
    owned_windows: list[Any] = [window]
    owned_hosts: list[Any] = [host_api]
    current_bundle = lifecycle.current()
    initial_generation = current_bundle.generation if current_bundle is not None else 0
    destroy_ok = False
    for key in _SETUP_CHECKS:
        checks.setdefault(key, False)

    fields = {
        "display-name": "王老师",
        "class-name": "中一班",
        "term-name": "2026 年秋季学期",
        "school-name": "合成园所",
    }
    restore_selector = (
        '[data-d1="backup-restore-panel"] [data-d1="backup-restore"]'
    )

    try:
        if Path(runtime.data_dir).resolve() != data_dir:
            raise SetupFlowError("config.data_dir 与 runtime.data_dir 不一致")
        _require_under(root, data_dir, "data_dir")
        driver.wait_until(
            "Boolean(document.querySelector('[data-d1=\"setup\"]'))",
            what="首次设置页",
            timeout=60,
        )
        checks["initial_page_ready"] = True
        checks["setup_visible"] = _js_visible(driver, '[data-d1="setup"]')

        # Capture the empty target before any setup/panel UI action.  The
        # empty runtime has 41 business tables, no profile and no resources.
        baseline = _capture_fixture(runtime, data_dir)
        baseline_profile_count = _profile_count(runtime.db_path)
        checks["setup_initial_profile_count"] = baseline_profile_count
        checks["setup_initial_baseline"] = {
            "database": _fingerprint_brief(baseline["database"]),
            "database_business": _fingerprint_brief(
                baseline["database_business"]
            ),
            "resources": {
                "sha256": baseline["resources"].get("fingerprint_sha256"),
                "files": len(baseline["resources"].get("files") or []),
            },
        }
        if len(_tables_of(baseline["database"])) != _BUSINESS_TABLE_COUNT:
            raise SetupFlowError(
                "初始空档案不是 41 表: "
                f"{len(_tables_of(baseline['database']))}"
            )
        if baseline_profile_count != 0:
            raise SetupFlowError(
                f"首次设置前已有档案: {baseline_profile_count}"
            )

        for selector, value in fields.items():
            assert _js_visible_enabled(driver, f'[data-d1="{selector}"]'), selector
            assert _js_set_input(driver, f'[data-d1="{selector}"]', value), selector
        before = {key: _input_value(driver, key) for key in fields}
        checks["setup_form_before"] = before
        for key, value in fields.items():
            assert before[key] == value, {key: before[key]}
        assert _js_visible_enabled(driver, '[data-d1="setup-restore"]')
        assert _js_click_visible(driver, '[data-d1="setup-restore"]')
        driver.wait_until(
            "Boolean(document.querySelector('[data-d1=\"backup-restore-panel\"]'))",
            what="首次恢复面板",
            timeout=30,
        )
        checks["setup_restore_only"] = not _js_visible_enabled(
            driver, '[data-d1="backup-create"]'
        )
        checks["panel_open"] = True

        # 1) Native chooser cancel keeps the setup form untouched.
        assert _js_visible_enabled(driver, restore_selector)
        assert _js_click_visible(driver, restore_selector)
        driver.wait_until(
            "(()=>{const p=document.querySelector('[data-d1=\"backup-restore-panel\"]');"
            " if(!p) return false; return Boolean(p.querySelector('[data-d1=\"backup-restore\"]'));})()",
            what="选择取消回到空闲",
            timeout=30,
        )
        checks["setup_cancel_silent"] = not _js_visible(
            driver, '[data-d1="backup-error"]'
        )
        assert _js_click(
            driver,
            '[data-d1="backup-restore-panel"] .el-dialog__headerbtn',
        )
        driver.wait_until(
            "!document.querySelector('[data-d1=\"backup-restore-panel\"]')",
            what="关闭取消后的面板",
            timeout=30,
        )

        # 2) Bad package is an honest error, no data change.
        assert _js_click_visible(driver, '[data-d1="setup-restore"]')
        driver.wait_until(
            "Boolean(document.querySelector('[data-d1=\"backup-restore-panel\"]'))",
            what="坏包恢复面板",
            timeout=30,
        )
        assert _js_click_visible(driver, restore_selector)
        driver.wait_until(
            "Boolean(document.querySelector('[data-d1=\"backup-error\"]'))",
            what="坏包错误",
            timeout=60,
        )
        bad_text = driver.eval(
            "document.querySelector('[data-d1=\"backup-error\"]').innerText"
        )
        checks["bad_package_error"] = bool(bad_text)
        checks["bad_package_text"] = bad_text
        assert _js_click(driver, '[data-d1="backup-error-close"]')
        driver.wait_until(
            "!document.querySelector('[data-d1=\"backup-restore-panel\"]')",
            what="关闭坏包面板",
            timeout=30,
        )

        # 3) Encrypted source: wrong password, then the real correct-password
        #    retry reaches a real preview and is cancelled.
        assert _js_click_visible(driver, '[data-d1="setup-restore"]')
        driver.wait_until(
            "Boolean(document.querySelector('[data-d1=\"backup-restore-panel\"]'))",
            what="密码恢复面板",
            timeout=30,
        )
        assert _js_click_visible(driver, restore_selector)
        driver.wait_until(
            "Boolean(document.querySelector('[data-d1=\"backup-password\"]'))",
            what="密码输入",
            timeout=30,
        )
        assert _js_set_input(
            driver,
            '[data-d1="backup-password"]',
            "synthetic-wrong-password",
        )
        assert _js_click_visible(driver, '[data-d1="backup-password-submit"]')
        driver.wait_until(
            "Boolean(document.querySelector('[data-d1=\"backup-password-error\"]'))",
            what="错误密码反馈",
            timeout=60,
        )
        wrong_text = driver.eval(
            "document.querySelector('[data-d1=\"backup-password-error\"]').innerText"
        )
        checks["wrong_password_error"] = bool(wrong_text)
        checks["wrong_password_text"] = wrong_text
        assert source_password, "config.source_password 为空，无法重试正确密码"
        assert _js_set_input(
            driver, '[data-d1="backup-password"]', source_password
        )
        _wait_visible_enabled(
            driver,
            '[data-d1="backup-password-submit"]',
            what="正确密码提交可用",
        )
        assert _js_click_visible(driver, '[data-d1="backup-password-submit"]')
        driver.wait_until(
            "Boolean(document.querySelector('[data-d1=\"backup-preview\"]'))"
            " || Boolean(document.querySelector('[data-d1=\"backup-password-error\"]'))"
            " || Boolean(document.querySelector('[data-d1=\"backup-error\"]'))",
            what="正确密码重试结果",
            timeout=timeout,
        )
        if _js_visible(driver, '[data-d1="backup-error"]'):
            raise SetupFlowError(
                driver.eval(
                    "document.querySelector('[data-d1=\"backup-error\"]').innerText"
                )
            )
        checks["setup_correct_retry_preview"] = _js_visible(
            driver, '[data-d1="backup-preview"]'
        )
        retry_preview_text = driver.eval(
            "document.querySelector('[data-d1=\"backup-restore-panel\"]').innerText"
        )
        checks["setup_retry_preview_text"] = retry_preview_text
        assert checks["setup_correct_retry_preview"], retry_preview_text
        assert not _js_visible(driver, '[data-d1="backup-password-error"]')
        assert _js_click(driver, '[data-d1="backup-preview-cancel"]')
        driver.wait_until(
            "Boolean(document.querySelector('[data-d1=\"backup-cancelled\"]'))",
            what="预览取消终态",
            timeout=60,
        )
        assert not _js_visible(driver, '[data-d1="backup-error"]')
        assert _js_click(driver, '[data-d1="backup-cancelled-close"]')
        driver.wait_until(
            "!document.querySelector('[data-d1=\"backup-restore-panel\"]')",
            what="关闭密码取消面板",
            timeout=30,
        )

        after = {key: _input_value(driver, key) for key in fields}
        checks["setup_form_after"] = after
        checks["setup_form_preserved"] = before == after
        checks["setup_still_visible"] = _js_visible(driver, '[data-d1="setup"]')
        checks["setup_no_calendar"] = not _js_visible(
            driver, '[data-d1="calendar"]'
        )
        setup_profile_count = _profile_count(runtime.db_path)
        checks["setup_profile_count"] = setup_profile_count
        checks["setup_no_temp_profile"] = setup_profile_count == 0
        checks["setup_retry_cancel_form_preserved"] = bool(
            checks["setup_form_preserved"]
            and setup_profile_count == 0
            and checks["setup_still_visible"]
            and checks["setup_no_calendar"]
        )
        assert checks["setup_form_preserved"], {
            "before": before,
            "after": after,
        }
        assert checks["setup_no_temp_profile"], setup_profile_count
        assert checks["setup_retry_cancel_form_preserved"], checks

        negative = _capture_fixture(runtime, data_dir)
        checks["setup_negative_baseline"] = {
            "database": _fingerprint_brief(negative["database"]),
            "resources": {
                "sha256": negative["resources"].get("fingerprint_sha256"),
                "files": len(negative["resources"].get("files") or []),
            },
        }
        checks["setup_negative_full41_unchanged"] = (
            negative["database"].get("fingerprint_sha256")
            == baseline["database"].get("fingerprint_sha256")
            and len(_tables_of(negative["database"]))
            == _BUSINESS_TABLE_COUNT
        )
        checks["setup_negative_resources_unchanged"] = (
            negative["resources"].get("fingerprint_sha256")
            == baseline["resources"].get("fingerprint_sha256")
        )
        _assert_baseline(negative, baseline, "负向与预览取消后")
        assert checks["setup_negative_full41_unchanged"]
        assert checks["setup_negative_resources_unchanged"]

        # 4) First real restore from the setup entry: full plaintext source.
        preexisting_protections = _existing_protection_paths(root)
        first_dialogs = _SetupDialogs(
            root, dialog_calls, "setup-first-restore"
        )
        first_dialogs.expect_open(source_package, label="源完整包")
        window.create_file_dialog = first_dialogs
        assert _js_click_visible(driver, '[data-d1="setup-restore"]')
        driver.wait_until(
            "Boolean(document.querySelector('[data-d1=\"backup-restore-panel\"]'))",
            what="首个正向恢复面板",
            timeout=30,
        )
        assert _js_visible_enabled(driver, restore_selector)
        assert _js_click_visible(driver, restore_selector)
        driver.wait_until(
            "Boolean(document.querySelector('[data-d1=\"backup-preview\"]'))"
            " || Boolean(document.querySelector('[data-d1=\"backup-password\"]'))"
            " || Boolean(document.querySelector('[data-d1=\"backup-error\"]'))",
            what="首个恢复预览或密码",
            timeout=timeout,
        )
        assert first_dialogs.pending() == 0, "首个正向恢复未消费原生选择"
        assert first_dialogs.unexpected == 0, "首个正向恢复出现额外原生选择"
        if _js_visible(driver, '[data-d1="backup-password"]'):
            assert source_password, "源包需要密码但 config 未提供"
            assert _js_set_input(
                driver, '[data-d1="backup-password"]', source_password
            )
            _wait_visible_enabled(
                driver,
                '[data-d1="backup-password-submit"]',
                what="首个恢复密码提交可用",
            )
            assert _js_click_visible(
                driver, '[data-d1="backup-password-submit"]'
            )
            driver.wait_until(
                "Boolean(document.querySelector('[data-d1=\"backup-preview\"]'))"
                " || Boolean(document.querySelector('[data-d1=\"backup-error\"]'))",
                what="首个恢复密码后预览",
                timeout=timeout,
            )
        if _js_visible(driver, '[data-d1="backup-error"]'):
            raise SetupFlowError(
                driver.eval(
                    "document.querySelector('[data-d1=\"backup-error\"]').innerText"
                )
            )
        first_preview_text = driver.eval(
            "document.querySelector('[data-d1=\"backup-restore-panel\"]').innerText"
        )
        checks["setup_first_restore_preview"] = first_preview_text
        assert _js_visible(driver, '[data-d1="backup-preview"]'), first_preview_text
        assert _js_click(driver, '[data-d1="backup-confirm-check"]')
        _wait_visible_enabled(
            driver,
            '[data-d1="backup-confirm-restore"]',
            what="首个恢复确认可用",
        )
        assert _js_click_visible(driver, '[data-d1="backup-confirm-restore"]')
        checks["setup_first_restore_confirmed"] = True

        first_bundle = _wait_new_bundle(
            lifecycle, initial_generation, timeout
        )
        first_window = first_bundle.window
        first_driver = d1_main.JsDriver(first_window)
        drivers.append(first_driver)
        if all(first_window is not item for item in owned_windows):
            owned_windows.append(first_window)
        if all(first_bundle.host_api is not item for item in owned_hosts):
            owned_hosts.append(first_bundle.host_api)
        first_window.create_file_dialog = _SetupDialogs(
            root, dialog_calls, f"setup-window-{first_bundle.generation}"
        )
        _wait_visible_all(
            first_driver,
            ('[data-d1="calendar"]', '[data-d1="restore-notice"]'),
            what="首个恢复新窗日历与保护位置同时可见",
            timeout=120,
        )
        first_notice_dom = first_driver.eval(
            "document.querySelector('[data-d1=\"restore-notice\"]').innerText"
        )
        first_protection, first_notice_host = _protection_path_from_notice(
            getattr(first_bundle.host_api, "_maintenance_notice", None),
            root,
            "首次恢复自动保护副本",
        )
        assert str(first_protection) not in preexisting_protections
        assert first_protection != source_package
        assert str(first_protection) in str(first_notice_dom), first_notice_dom
        assert _wait_window_gone(window, 30.0), "旧窗口未销毁"
        checks["setup_first_window_generation"] = first_bundle.generation
        checks["setup_first_notice"] = first_notice_host
        checks["setup_first_notice_dom"] = first_notice_dom
        checks["setup_first_protection_path"] = str(first_protection)
        checks["setup_first_protection_sha256"] = _sha256_file(first_protection)
        checks["setup_first_restore_completed"] = True

        # 5) Prove the automatic empty protection package is exactly the
        #    pre-UI empty baseline, with no profile, and its old group remains.
        first_verified = _verify_protection_package(
            runtime, first_protection, "empty-protection"
        )
        checks["setup_empty_protection"] = {
            "path": first_verified["path"],
            "sha256": first_verified["sha256"],
            "database": _fingerprint_brief(first_verified["database"]),
            "resources": {
                "sha256": first_verified["resources"].get("fingerprint_sha256"),
                "files": len(first_verified["resources"].get("files") or []),
            },
            "profile_count": first_verified["profile_count"],
            "snapshot_id": first_verified["snapshot_id"],
        }
        empty_ok = (
            first_verified["database"].get("fingerprint_sha256")
            == baseline["database"].get("fingerprint_sha256")
            and first_verified["resources"].get("fingerprint_sha256")
            == baseline["resources"].get("fingerprint_sha256")
            and first_verified["profile_count"] == 0
            and first_verified["table_count"] == _BUSINESS_TABLE_COUNT
        )
        if not empty_ok:
            raise SetupFlowError(
                "空保护包与初始空基线不一致；"
                f"tables={_table_diff(first_verified['database'], baseline['database'])} "
                f"profiles={first_verified['profile_count']}"
            )
        checks["setup_empty_protection_verified_full"] = True
        first_operation = _assert_protection_operation(
            runtime, first_protection, "首次恢复保护副本"
        )
        checks["setup_first_old_group"] = first_operation
        loaded_source = _capture_fixture(runtime, data_dir)
        loaded_profile_count = _profile_count(runtime.db_path)
        checks["setup_loaded_source"] = {
            "database": _fingerprint_brief(loaded_source["database"]),
            "resources": {
                "sha256": loaded_source["resources"].get("fingerprint_sha256"),
                "files": len(loaded_source["resources"].get("files") or []),
            },
            "profile_count": loaded_profile_count,
            "equals_package_full": (
                loaded_source["database"].get("fingerprint_sha256")
                == source.get("database", {}).get("fingerprint_sha256")
            ),
        }
        if loaded_profile_count < 1:
            raise SetupFlowError("首个恢复后新窗口没有源档案")

        # 6) From the new workbench settings entry, restore the automatic
        #    empty package through the real panel and switch a third window.
        second_protection_before = _existing_protection_paths(root)
        second_dialogs = _SetupDialogs(
            root, dialog_calls, "setup-empty-protection-restore"
        )
        second_dialogs.expect_open(
            first_protection, label="本次自动空保护副本"
        )
        first_window.create_file_dialog = second_dialogs
        assert _js_click_visible(first_driver, '[data-d1="open-settings"]')
        _open_settings_panel(first_driver)
        assert _js_visible_enabled(first_driver, restore_selector)
        assert _js_click_visible(first_driver, restore_selector)
        first_driver.wait_until(
            "Boolean(document.querySelector('[data-d1=\"backup-preview\"]'))"
            " || Boolean(document.querySelector('[data-d1=\"backup-password\"]'))"
            " || Boolean(document.querySelector('[data-d1=\"backup-error\"]'))",
            what="空保护包预览或密码",
            timeout=timeout,
        )
        assert second_dialogs.pending() == 0, "空保护包恢复未消费原生选择"
        assert second_dialogs.unexpected == 0, "空保护包恢复出现额外原生选择"
        if _js_visible(first_driver, '[data-d1="backup-error"]'):
            raise SetupFlowError(
                first_driver.eval(
                    "document.querySelector('[data-d1=\"backup-error\"]').innerText"
                )
            )
        empty_preview_text = first_driver.eval(
            "document.querySelector('[data-d1=\"backup-restore-panel\"]').innerText"
        )
        checks["setup_protection_restore_preview"] = empty_preview_text
        assert _js_visible(first_driver, '[data-d1="backup-preview"]'), empty_preview_text
        assert "日计划 0" in empty_preview_text, empty_preview_text
        assert "照片 0" in empty_preview_text, empty_preview_text
        second_source_baseline = _capture_fixture(runtime, data_dir)
        second_source_profile = _profile_count(runtime.db_path)
        checks["setup_second_source_baseline"] = {
            "database": _fingerprint_brief(second_source_baseline["database"]),
            "resources": {
                "sha256": second_source_baseline["resources"].get(
                    "fingerprint_sha256"
                ),
                "files": len(
                    second_source_baseline["resources"].get("files") or []
                ),
            },
            "profile_count": second_source_profile,
        }
        if second_source_profile < 1:
            raise SetupFlowError("空保护包恢复前源档案已消失")
        assert _js_click(first_driver, '[data-d1="backup-confirm-check"]')
        _wait_visible_enabled(
            first_driver,
            '[data-d1="backup-confirm-restore"]',
            what="空保护包确认可用",
        )
        assert _js_click_visible(
            first_driver, '[data-d1="backup-confirm-restore"]'
        )
        checks["setup_protection_restore_confirmed"] = True

        second_bundle = _wait_new_bundle(
            lifecycle, first_bundle.generation, timeout
        )
        second_window = second_bundle.window
        second_driver = d1_main.JsDriver(second_window)
        drivers.append(second_driver)
        if all(second_window is not item for item in owned_windows):
            owned_windows.append(second_window)
        if all(second_bundle.host_api is not item for item in owned_hosts):
            owned_hosts.append(second_bundle.host_api)
        second_window.create_file_dialog = _SetupDialogs(
            root, dialog_calls, f"setup-window-{second_bundle.generation}"
        )
        _wait_visible_all(
            second_driver,
            ('[data-d1="setup"]', '[data-d1="restore-notice"]'),
            what="空保护包恢复后设置页与保护位置同时可见",
            timeout=120,
        )
        second_notice_dom = second_driver.eval(
            "document.querySelector('[data-d1=\"restore-notice\"]').innerText"
        )
        second_protection, second_notice_host = _protection_path_from_notice(
            getattr(second_bundle.host_api, "_maintenance_notice", None),
            root,
            "空保护包恢复自动保护副本",
        )
        assert str(second_protection) not in second_protection_before
        assert second_protection != first_protection
        assert str(second_protection) in str(second_notice_dom), second_notice_dom
        assert _wait_window_gone(first_window, 30.0), "第二个窗口未销毁"
        checks["setup_protection_ui_window_generation"] = second_bundle.generation
        checks["setup_protection_notice"] = second_notice_host
        checks["setup_protection_notice_dom"] = second_notice_dom
        checks["setup_protection_ui_restore_completed"] = True

        # 7) Final state is the initial empty baseline, and the second
        #    automatic protection contains the replaced full source profile.
        final = _capture_fixture(runtime, data_dir)
        final_profile_count = _profile_count(runtime.db_path)
        final_setup_visible = _js_visible(second_driver, '[data-d1="setup"]')
        final_calendar_visible = _js_visible(
            second_driver, '[data-d1="calendar"]'
        )
        checks["setup_final_profile_count"] = final_profile_count
        checks["setup_final_baseline"] = {
            "database": _fingerprint_brief(final["database"]),
            "resources": {
                "sha256": final["resources"].get("fingerprint_sha256"),
                "files": len(final["resources"].get("files") or []),
            },
        }
        checks["setup_returned_empty_profile"] = bool(
            final_profile_count == 0
            and final_setup_visible
            and not final_calendar_visible
        )
        checks["setup_empty_full41_restored"] = bool(
            final["database"].get("fingerprint_sha256")
            == baseline["database"].get("fingerprint_sha256")
            and final["resources"].get("fingerprint_sha256")
            == baseline["resources"].get("fingerprint_sha256")
            and len(_tables_of(final["database"])) == _BUSINESS_TABLE_COUNT
        )
        checks["setup_empty_resources_restored"] = (
            final["resources"].get("fingerprint_sha256")
            == baseline["resources"].get("fingerprint_sha256")
        )
        _assert_baseline(final, baseline, "空保护包 UI 恢复后")
        assert checks["setup_returned_empty_profile"], checks["setup_final_baseline"]
        assert checks["setup_empty_full41_restored"]
        assert checks["setup_empty_resources_restored"]

        second_verified = _verify_protection_package(
            runtime, second_protection, "replaced-source-protection"
        )
        checks["setup_second_protection"] = {
            "path": second_verified["path"],
            "sha256": second_verified["sha256"],
            "database": _fingerprint_brief(second_verified["database"]),
            "resources": {
                "sha256": second_verified["resources"].get("fingerprint_sha256"),
                "files": len(second_verified["resources"].get("files") or []),
            },
            "profile_count": second_verified["profile_count"],
            "snapshot_id": second_verified["snapshot_id"],
        }
        second_source_ok = bool(
            second_verified["database"].get("fingerprint_sha256")
            == second_source_baseline["database"].get("fingerprint_sha256")
            and second_verified["resources"].get("fingerprint_sha256")
            == second_source_baseline["resources"].get("fingerprint_sha256")
            and second_verified["profile_count"] >= 1
            and second_verified["table_count"] == _BUSINESS_TABLE_COUNT
        )
        checks["setup_second_protection_source_full"] = second_source_ok
        if not second_source_ok:
            raise SetupFlowError(
                "第二份保护包未包含被替换的完整源档案；"
                f"tables={_table_diff(second_verified['database'], second_source_baseline['database'])} "
                f"profiles={second_verified['profile_count']}"
            )

        first_operation_after = _assert_protection_operation(
            runtime, first_protection, "第二恢复后首个保护副本"
        )
        second_operation = _assert_protection_operation(
            runtime, second_protection, "第二恢复保护副本"
        )
        first_still_there = (
            first_protection.is_file()
            and _sha256_file(first_protection)
            == checks["setup_first_protection_sha256"]
        )
        checks["setup_first_protection_preserved"] = first_still_there
        checks["setup_first_old_group_after"] = first_operation_after
        checks["setup_second_old_group"] = second_operation
        assert first_still_there, "原空保护包被删除或改写"
        assert (
            first_operation_after["old_group"] == first_operation["old_group"]
        ), "原空旧组位置改变"
        assert Path(first_operation_after["old_group_db"]).is_file()
        assert Path(second_operation["old_group_db"]).is_file()

        destroy_ok = _destroy_owned_windows([second_window])
        checks["driver_destroy_confirmed"] = destroy_ok
        if not destroy_ok:
            checks["new_window_destroy_error"] = (
                "owned window destroy not confirmed"
            )
    except Exception as exc:  # noqa: BLE001 - first failure is evidence
        checks["driver_error"] = f"{type(exc).__name__}: {exc}"
        checks["driver_trace"] = traceback.format_exc()
        summary["ok"] = False
        _record_failure_dom(checks, drivers, dialog_calls)
        checks["failure_initial_generation"] = initial_generation
        try:
            current = lifecycle.current()
            checks["failure_current_generation"] = (
                current.generation if current is not None else None
            )
        except Exception:  # noqa: BLE001 - diagnostics only
            checks["failure_current_generation"] = None
        checks["failure_owned_window_count"] = len(owned_windows)
        _write_summary(summary, out_path)
        cancelled = 0
        for owned_host in owned_hosts:
            try:
                cancelled += _cleanup_unswitched_maintenance(owned_host)
            except Exception:  # noqa: BLE001 - cleanup never fakes success
                pass
        checks["driver_cleanup_cancelled"] = cancelled
        if _has_inflight_switch(owned_hosts):
            # The switch is already past cancel; adopt the one new window this
            # driver's own operation is creating so it cannot outlive failure.
            deadline = time.monotonic() + 20.0
            while time.monotonic() < deadline:
                current = lifecycle.current()
                if (
                    current is not None
                    and current.generation > initial_generation
                    and current.window is not None
                ):
                    if all(current.window is not item for item in owned_windows):
                        owned_windows.append(current.window)
                    if all(
                        current.host_api is not item for item in owned_hosts
                    ):
                        owned_hosts.append(current.host_api)
                    break
                time.sleep(0.05)
        for owned_host in owned_hosts:
            try:
                if not owned_host._maintenance_busy_probe():
                    owned_host._request_retire_destroy()
            except Exception:  # noqa: BLE001
                pass
        destroy_ok = _destroy_owned_windows(owned_windows, force=True)
        checks["driver_destroy_confirmed"] = destroy_ok
    finally:
        if destroy_ok:
            finished.set()
