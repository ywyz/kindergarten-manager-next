"""W6 本机合成 AI 人工验收入口（独立新增；不改既有生产入口）。

只用于**人工**验收：由独立控制器（``verify_d2_manual_ai.py``）在新的合成会话根
上启动受控 loopback TLS 供应商，然后打开普通交互窗口（无自动点按钮、无自动
采用/导出/关窗、人类模式无 watchdog）。复用已核查的 ``d1_main.build_runtime``
与关闭/释放协调，不调用 ``d1_main.run_selftest``。

安全边界在**任何 LocalRuntime 构造/prepare 之前**校验：显式会话根与
``<session>/data``、控制器标记（含 source_root/source_data）、会话与源根不
重叠、LOCALAPPDATA 与会话隔离且一致、显式禁止根、provider 仅 127.0.0.1 +
本机 CA。既有普通入口仍拒绝合成注入；本入口通过既有专用相位参数复用
``build_runtime``，不新增生产网络旁路。

冻结 spawn child 在任何 GUI/参数副作用之前由 ``freeze_support_guarded`` 分流。
"""

from __future__ import annotations

import sys
from pathlib import Path

if not getattr(sys, "frozen", False):
    _here = Path(__file__).resolve().parent
    for _entry in (str(_here.parent / "backend"), str(_here)):
        if _entry not in sys.path:
            sys.path.insert(0, _entry)

# Divert the frozen spawn child bootstrap before argparse/GUI/import side effects.
from app.local.ai_spawn import freeze_support_guarded  # noqa: E402

freeze_support_guarded()

import argparse  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from pathlib import Path as _Path  # noqa: E402

MARKER_NAME = ".w6-manual-session.json"
WINDOW_TITLE = "W6本机合成人工验收"
SMOKE_HARD_LIMIT_SECONDS = 240

SMOKE_SPLIT_RAW = "W6人工验收合成原文：一、导入；二、观察；三、比较。"


def _logs_dir(manual_root: Path) -> Path:
    path = manual_root / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _is_under(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _overlap(a: Path, b: Path) -> bool:
    return _is_under(a, b) or _is_under(b, a)


def validate_args(args) -> None:
    """Validate the manual entry BEFORE any LocalRuntime construction."""
    if not getattr(args, "manual_root", None):
        raise RuntimeError("必须显式提供 --manual-root 合成会话根")
    if not getattr(args, "data", None):
        raise RuntimeError("必须显式提供 --data（会话根内的合成数据目录）")
    root = Path(args.manual_root).resolve()
    data = Path(args.data).resolve()
    if data != (root / "data").resolve():
        raise RuntimeError("--data 必须固定为 <manual-root>/data")
    marker_path = root / MARKER_NAME
    if not marker_path.is_file():
        raise RuntimeError("会话根缺少控制器标记 .w6-manual-session.json，拒绝启动")
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("会话标记无法读取") from exc
    if Path(marker.get("manual_root", "")).resolve() != root:
        raise RuntimeError("会话标记的 manual_root 不一致")
    if Path(marker.get("data", "")).resolve() != data:
        raise RuntimeError("会话标记的 data 不一致")

    source_root_raw = marker.get("source_root")
    source_data_raw = marker.get("source_data")
    if not source_root_raw or not source_data_raw:
        raise RuntimeError("会话标记缺少 source_root/source_data（不能猜测原根）")
    source_root = Path(source_root_raw).resolve()
    source_data = Path(source_data_raw).resolve()
    if _overlap(root, source_root) or _overlap(data, source_data):
        raise RuntimeError("会话根不得与源根/源数据重叠")

    localappdata = os.environ.get("LOCALAPPDATA")
    if not localappdata:
        raise RuntimeError("必须显式设置隔离的 LOCALAPPDATA")
    expected_local = (root / "localappdata").resolve()
    if Path(localappdata).resolve() != expected_local:
        raise RuntimeError("LOCALAPPDATA 必须与会话根隔离目录一致")

    for forbidden in getattr(args, "forbid_root", None) or ():
        forbidden_path = Path(forbidden).resolve()
        if _overlap(root, forbidden_path) or _overlap(data, forbidden_path):
            raise RuntimeError(f"拒绝使用被禁止的根: {forbidden_path}")

    if getattr(args, "provider_ip", "127.0.0.1") != "127.0.0.1":
        raise RuntimeError("受控 provider 只允许 127.0.0.1")
    port = getattr(args, "provider_port", None)
    if not isinstance(port, int) or not (1 <= port <= 65535):
        raise RuntimeError("受控 provider 端口无效")
    ca = getattr(args, "provider_ca", None)
    if not ca or not _Path(ca).is_file():
        raise RuntimeError("受控 provider 测试 CA 缺失")


def _build_runtime_args(args):
    """Shim namespace for the reviewed ``d1_main.build_runtime``."""
    return argparse.Namespace(
        data=str(args.data),
        frontend=args.frontend,
        selftest=True,
        phase="w6-ui",
        synthetic_provider_port=int(args.provider_port),
        synthetic_provider_ca=str(args.provider_ca),
        synthetic_provider_ip="127.0.0.1",
        synthetic_executor_fail=None,
    )


def _fingerprint(out_path: str) -> int:
    """Headless same-origin fingerprint mode (no window)."""
    import d2_same_origin

    for name in (
        "d1_main",
        "d1_host_api",
        "d1_server",
        "d1_paths",
        "app.local.ai_executor",
        "app.local.ai_worker",
        "app.local.ai_transport",
        "app.local.ai_task_service",
        "app.local.ai_config_service",
        "app.local.ai_adoption",
        "app.local.ai_candidates",
        "app.local.ai_provenance",
        "app.local.ai_inputs",
        "app.local.export_service",
        "app.local.daily_plan_service",
        "app.local.prompt_bundles",
        "app.local.credentials",
        "app.services.word_export_docx",
        "app.services.word_export_mapping",
        "app.services.daily_plan_content",
    ):
        try:
            __import__(name)
        except Exception:  # noqa: BLE001 - coverage is recorded, not hidden
            pass
    names = d2_same_origin.loaded_production_modules()
    payload = {
        "frozen": bool(getattr(sys, "frozen", False)),
        "modules": {
            name: d2_same_origin.fingerprint_imported_module(name) for name in names
        },
    }
    _write_json(Path(out_path), payload)
    return 0


def _drive_dom_check(driver, window, summary: dict, dom_date: str) -> None:
    """H06-R01 real-window DOM check (native input events + button.disabled/.click).

    Automated verification mode only (never the human session). It creates a
    fresh split candidate on the given date so no old historical candidate is
    reused, scopes every selector to the *visible candidate dialog*, injects the
    process text with real newlines, and proves the adopted body/baseline plus
    the full close path (candidate X -> host close -> native cancel -> clean exit).
    """
    import json as _json
    import time as _time

    edited_process = "一、导入\n二、观察\n三、比较（教师确认）"
    baseline_process = "一、导入\n二、观察\n三、比较"
    result: dict = {
        "edited_process": edited_process,
        "baseline_process": baseline_process,
    }

    driver.wait_until(
        "Boolean(window.__d1App && window.__d1App.ready())", what="dom app ready", timeout=40
    )
    if driver.eval("window.__d1App.state()") != "ready":
        raise RuntimeError("dom-check clone lacks an initialized profile")
    driver.wait_until(
        "Boolean(window.__d1Workbench && typeof window.__d1Workbench.openDate === 'function')",
        what="dom workbench",
        timeout=30,
    )
    driver.eval(f"window.__d1Workbench.openDate({_json.dumps(dom_date)})")
    driver.wait_until("window.__d1App.view() === 'editor'", what="dom editor", timeout=30)
    driver.wait_until(
        "window.__d1Editor && ['ready','create_confirmation'].includes(window.__d1Editor.phase())",
        what="dom editor phase",
        timeout=30,
    )
    if driver.eval("window.__d1Editor.phase()") == "create_confirmation":
        driver.eval("document.querySelector('button[data-d1=\"confirm-create\"]').click()")
        driver.wait_until(
            "window.__d1Editor.phase() === 'ready'", what="dom create", timeout=30
        )

    set_raw = (
        "(() => {"
        " const areas = [...document.querySelectorAll('textarea')];"
        " const el = areas.find((t) => (t.placeholder || '').includes('原始教案'))"
        "   || areas[areas.length - 1];"
        " if (!el) return 'no-raw';"
        " const setter = Object.getOwnPropertyDescriptor("
        "   window.HTMLTextAreaElement.prototype, 'value').set;"
        f" setter.call(el, {_json.dumps('H06R01 原始教案：一、导入；二、观察；三、比较。', ensure_ascii=False)});"
        " el.dispatchEvent(new Event('input', { bubbles: true }));"
        " return 'ok';"
        " })()"
    )
    if driver.eval(set_raw) != "ok":
        raise RuntimeError("dom-check raw textarea not found")
    driver.wait_until("window.__d1Editor.dirty() === true", what="dom dirty", timeout=15)
    driver.eval("document.querySelector('button[data-d1=\"manual-save\"]').click()")
    driver.wait_until(
        "window.__d1Editor.phase() === 'ready' && window.__d1Editor.dirty() === false",
        what="dom save",
        timeout=60,
    )
    result["plan_id"] = driver.eval("window.__d1Editor.planId()")
    result["plan_date"] = driver.eval("window.__d1Editor.planDate()")
    result["body_version_saved"] = driver.eval("window.__d1Editor.version()")

    driver.eval(
        "document.querySelector('button[data-d1=\"ai-trigger-daily_lesson_split\"]').click()"
    )
    driver.wait_until(
        "window.__d1AiTasks.tasks().some(function(t){return t.task_type==='daily_lesson_split'"
        " && t.status==='succeeded' && t.candidate_id})",
        what="dom split candidate",
        timeout=90,
    )
    task = next(
        t
        for t in driver.eval("window.__d1AiTasks.tasks()")
        if t.get("task_type") == "daily_lesson_split"
    )
    task_id = task.get("id")
    open_view = (
        "(() => {"
        f" const b = document.querySelector('button[data-d1=\"ai-view-' + {_json.dumps(task_id)} + '\"]');"
        " if (!b) return false;"
        " b.click();"
        " return true;"
        " })()"
    )

    def open_candidate_fresh() -> None:
        if driver.eval(open_view) is not True:
            raise RuntimeError("dom-check view-candidate button not found")
        driver.wait_until(
            "window.__d1Editor.candidateOpen() === true"
            " && window.__d1Candidate && window.__d1Candidate.phase() === 'ready'"
            " && window.__d1Candidate.preview() === null",
            what="dom candidate fresh load",
            timeout=30,
        )

    set_process = (
        "(() => {"
        " const dlg = document.querySelector('[data-d1=\"candidate-preview\"]');"
        " if (!dlg) return 'no-dialog';"
        " const label = [...dlg.querySelectorAll('label')]"
        "   .find((l) => l.textContent.trim() === '过程');"
        " if (!label) return 'no-label';"
        " const field = label.closest('.field') || label.parentElement;"
        " const el = field.querySelector('textarea');"
        " if (!el || el.offsetParent === null) return 'no-input';"
        " const setter = Object.getOwnPropertyDescriptor("
        "   window.HTMLTextAreaElement.prototype, 'value').set;"
        f" setter.call(el, {_json.dumps(edited_process, ensure_ascii=False)});"
        " el.dispatchEvent(new Event('input', { bubbles: true }));"
        " return 'ok';"
        " })()"
    )
    read_process = (
        "(() => {"
        " const dlg = document.querySelector('[data-d1=\"candidate-preview\"]');"
        " if (!dlg) return null;"
        " const label = [...dlg.querySelectorAll('label')]"
        "   .find((l) => l.textContent.trim() === '过程');"
        " const el = label && (label.closest('.field') || label.parentElement)"
        "   .querySelector('textarea');"
        " return el ? el.value : null;"
        " })()"
    )

    open_candidate_fresh()
    if driver.eval(set_process) != "ok":
        raise RuntimeError("dom-check process textarea not found")
    driver.wait_until("window.__d1Candidate.dirty() === true", what="dom candidate dirty", timeout=15)
    result["body_dirty_after_edit"] = driver.eval("window.__d1Editor.dirty()")
    result["body_version_after_edit"] = driver.eval("window.__d1Editor.version()")
    result["preview_disabled_after_edit"] = driver.eval(
        "document.querySelector('button[data-d1=\"candidate-preview\"]').disabled"
    )
    result["cancel_disabled_after_edit"] = driver.eval(
        "document.querySelector('button[data-d1=\"candidate-cancel-edit\"]').disabled"
    )
    if (
        result["preview_disabled_after_edit"] is not False
        or result["cancel_disabled_after_edit"] is not False
        or result["body_dirty_after_edit"] is not False
        or result["body_version_after_edit"] != result["body_version_saved"]
    ):
        raise RuntimeError("dom-check: edit/compare preconditions failed (H06-R01)")
    driver.eval("document.querySelector('button[data-d1=\"candidate-preview\"]').click()")
    driver.wait_until(
        "Boolean(document.querySelector('[data-d1=\"candidate-preview-compare\"]'))",
        what="dom comparison",
        timeout=60,
    )
    result["adopt_disabled_after_compare"] = driver.eval(
        "document.querySelector('button[data-d1=\"candidate-adopt\"]').disabled"
    )
    if result["adopt_disabled_after_compare"] is not False:
        raise RuntimeError("dom-check: adopt not strictly enabled after comparison")
    driver.eval("document.querySelector('button[data-d1=\"candidate-adopt\"]').click()")
    driver.wait_until(
        "Boolean(document.querySelector('[data-d1=\"candidate-adopted\"]'))",
        what="dom adopted",
        timeout=60,
    )
    result["adopted"] = True
    result["version_after_adopt"] = driver.eval("window.__d1Editor.version()")

    open_candidate_fresh()
    if driver.eval(set_process) != "ok":
        raise RuntimeError("dom-check: process textarea not found on reopen")
    driver.wait_until("window.__d1Candidate.dirty() === true", what="dom dirty reopen", timeout=15)
    if (
        driver.eval("document.querySelector('button[data-d1=\"candidate-cancel-edit\"]').disabled")
        is not False
    ):
        raise RuntimeError("dom-check: cancel disabled while dirty")
    driver.eval("document.querySelector('button[data-d1=\"candidate-cancel-edit\"]').click()")
    driver.wait_until(
        "window.__d1Editor.candidateOpen() === false", what="dom cancel closed", timeout=30
    )
    result["cancel_closed"] = True
    result["version_after_cancel"] = driver.eval("window.__d1Editor.version()")

    open_candidate_fresh()
    if driver.eval(set_process) != "ok":
        raise RuntimeError("dom-check: process textarea not found for X close")
    driver.wait_until("window.__d1Candidate.dirty() === true", what="dom x dirty", timeout=15)
    driver.eval(
        "document.querySelector('[data-d1=\"candidate-preview\"] .el-dialog__headerbtn').click()"
    )
    _time.sleep(0.8)
    result["x_close_blocked"] = driver.eval("window.__d1Editor.candidateOpen() === true")
    result["x_close_kept_text"] = driver.eval(read_process) == edited_process
    result["x_close_message"] = driver.eval(
        "(document.querySelector('[data-d1=\"candidate-error\"]')||{}).textContent || ''"
    )
    if not result["x_close_blocked"] or not result["x_close_kept_text"]:
        raise RuntimeError("dom-check: candidate X close did not keep the draft")

    window.destroy()
    _time.sleep(1.5)
    close_state = driver.eval("JSON.stringify(window.__d1App.closeState())")
    result["close_state_after_block"] = close_state
    result["close_blocked_by_draft"] = driver.eval("window.__d1Editor.candidateOpen() === true")
    result["close_window_still_open"] = driver.eval("window.__d1App.view()") == "editor"
    result["close_locked_after_block"] = bool(
        isinstance(close_state, str) and _json.loads(close_state).get("locked") is True
    )
    if not (
        result["close_blocked_by_draft"]
        and result["close_window_still_open"]
        and not result["close_locked_after_block"]
    ):
        raise RuntimeError("dom-check: host close was not cleanly blocked by the draft")

    driver.eval("document.querySelector('button[data-d1=\"candidate-cancel-edit\"]').click()")
    driver.wait_until(
        "window.__d1Editor.candidateOpen() === false", what="dom exit cancel", timeout=30
    )
    result["exit_cancel_closed"] = True
    summary["dom_check"] = result


def _drive_smoke(driver, window, summary: dict, smoke_date: str) -> None:
    """Limited automated smoke (never used for the formal human session)."""
    driver.wait_until(
        "Boolean(window.__d1App && window.__d1App.ready())", what="smoke 页面启动", timeout=40
    )
    if driver.eval("window.__d1App.state()") != "ready":
        raise RuntimeError("smoke 克隆缺少已初始化档案")
    driver.wait_until(
        "Boolean(window.__d1Workbench && typeof window.__d1Workbench.openDate === 'function')",
        what="smoke 工作台",
        timeout=30,
    )
    driver.eval(f"window.__d1Workbench.openDate({json.dumps(smoke_date)})")
    driver.wait_until("window.__d1App.view() === 'editor'", what="smoke 编辑器", timeout=30)
    driver.wait_until(
        "window.__d1Editor && ['ready','create_confirmation'].includes(window.__d1Editor.phase())",
        what="smoke 编辑器就绪",
        timeout=30,
    )
    if driver.eval("window.__d1Editor.phase()") == "create_confirmation":
        raise RuntimeError("smoke 克隆缺少目标日期计划（拒绝自动创建）")
    driver.eval(
        "window.__d1Editor.setText("
        + json.dumps(SMOKE_SPLIT_RAW, ensure_ascii=False)
        + ", "
        + json.dumps("W6人工验收合成反思", ensure_ascii=False)
        + ")"
    )
    driver.wait_until("window.__d1Editor.dirty() === true", what="smoke 输入", timeout=15)
    driver.eval("window.__d1Editor.save()")
    driver.wait_until(
        "window.__d1Editor.phase() === 'ready' && window.__d1Editor.dirty() === false",
        what="smoke 保存",
        timeout=60,
    )
    results: dict = {}
    for task_type, key in (
        ("daily_lesson_split", "split"),
        ("daily_process_adapt", "adapt"),
        ("daily_other_activities", "other"),
    ):
        driver.eval(f"window.__d1AiTasks.trigger({json.dumps(task_type)})")
        driver.wait_until(
            "window.__d1AiTasks.tasks().some(function(t){return t.task_type==="
            + json.dumps(task_type)
            + " && t.status==='succeeded' && t.candidate_id})",
            what=f"smoke {key} 候选",
            timeout=120,
        )
        task = next(
            t
            for t in driver.eval("window.__d1AiTasks.tasks()")
            if t.get("task_type") == task_type
        )
        results[key] = {
            "task_id": task.get("id"),
            "candidate_id": task.get("candidate_id"),
            "status": task.get("status"),
        }
    summary["smoke"] = results


def _cleanup(service, runtime, *, worker_unconfirmed: bool = False) -> dict:
    """Unified cleanup for normal and error paths; reports only real facts."""
    executor = getattr(runtime, "ai_executor", None) if runtime is not None else None
    worker_ok = not worker_unconfirmed
    if executor is not None:
        try:
            worker_ok = bool(executor.dispose()) and worker_ok
        except Exception:  # noqa: BLE001 - never claim a clean worker
            worker_ok = False
    server_ok = True
    if service is not None:
        try:
            service.stop()
        except Exception:  # noqa: BLE001 - recorded, never hidden
            server_ok = False
        try:
            server_ok = server_ok and not service.alive()
        except Exception:  # noqa: BLE001
            server_ok = False
    runtime_released = False
    # The runtime lock may be released only when BOTH the AI worker and the
    # local service are confirmed stopped.
    if runtime is not None and worker_ok and server_ok:
        try:
            runtime.dispose()
            runtime_released = True
        except Exception:  # noqa: BLE001
            runtime_released = False
    if not worker_ok or not server_ok:
        runtime_released = False
    return {
        "worker_exit_confirmed": bool(worker_ok),
        "server_stopped": bool(server_ok),
        "runtime_lock_released": bool(runtime_released),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="W6 本机合成 AI 人工验收（独立入口）")
    parser.add_argument("--manual-root", help="独立合成会话根（控制器创建并标记）")
    parser.add_argument("--data", help="必须为 <manual-root>/data")
    parser.add_argument("--frontend", help="源码运行时的前端构建目录")
    parser.add_argument("--provider-port", type=int, default=None)
    parser.add_argument("--provider-ca", default=None)
    parser.add_argument("--provider-ip", default="127.0.0.1")
    parser.add_argument(
        "--forbid-root",
        action="append",
        default=[],
        help="禁止作为会话/数据根的显式路径（可重复）",
    )
    parser.add_argument("--smoke", action="store_true", help="有限验证模式（非人工会话）")
    parser.add_argument("--smoke-date", default="2026-10-19")
    parser.add_argument(
        "--dom-check",
        action="store_true",
        help="H06-R01 真实窗口 DOM 按钮验证模式（非人工会话）",
    )
    parser.add_argument("--dom-date", default="2026-10-20")
    parser.add_argument("--fingerprint-out", default=None)
    args = parser.parse_args()

    if args.fingerprint_out:
        return _fingerprint(args.fingerprint_out)

    validate_args(args)
    root = Path(args.manual_root).resolve()
    logs = _logs_dir(root)
    exit_report = logs / "entry-exit.json"

    import d1_main

    summary: dict = {"checks": {}}
    service = None
    runtime = None
    error: str | None = None
    exit_code = 0
    worker_unconfirmed = False
    started = time.time()
    smoke_timer: threading.Timer | None = None
    smoke_timed_out = {"value": False}

    def _smoke_hard_stop():
        smoke_timed_out["value"] = True
        _write_json(
            logs / "smoke-timeout.json",
            {"ok": False, "reason": "smoke hard limit", "limit": SMOKE_HARD_LIMIT_SECONDS},
        )
        # Only smoke gets a hard external bound; a stuck close/task must fail
        # explicitly instead of hanging forever.
        os._exit(4)

    try:
        try:
            service, host_api, runtime = d1_main.build_runtime(_build_runtime_args(args))
        except d1_main._ExecutorUnconfirmed as exc:
            # build_runtime refused to start because an AI worker could not be
            # confirmed gone. The runtime (and its lock) is owned internally;
            # the carried executor is the only handle. Attempt one teardown but
            # NEVER claim the lock was released.
            worker_unconfirmed = True
            try:
                exc.executor.dispose()
            except Exception:  # noqa: BLE001
                pass
            error = "startup: AI worker unconfirmed; runtime lock kept"
            exit_code = 2
        except Exception as exc:  # noqa: BLE001
            error = f"startup: {type(exc).__name__}: {exc}"
            exit_code = 2
        if error is None and not service.start_and_wait():
            error = f"service: {service.error}"
            exit_code = 2
        if error is None:
            import webview

            window = webview.create_window(
                WINDOW_TITLE,
                url=f"http://127.0.0.1:{service.port}/",
                js_api=host_api,
                width=1180,
                height=820,
                min_size=(760, 560),
                text_select=True,
            )
            d1_main._install_close_handlers(window, host_api, runtime)
            if args.smoke or args.dom_check:
                from d1_main import JsDriver

                driver = JsDriver(window)
                automated = "smoke" if args.smoke else "dom"

                def automated_task():
                    try:
                        if args.smoke:
                            _drive_smoke(driver, window, summary, args.smoke_date)
                        else:
                            _drive_dom_check(driver, window, summary, args.dom_date)
                    except Exception as exc:  # noqa: BLE001
                        summary[f"{automated}_error"] = f"{type(exc).__name__}: {exc}"
                    finally:
                        try:
                            window.destroy()
                        except Exception:  # noqa: BLE001
                            pass
                        _write_json(logs / f"{automated}-result.json", summary)

                smoke_timer = threading.Timer(SMOKE_HARD_LIMIT_SECONDS, _smoke_hard_stop)
                smoke_timer.daemon = True
                smoke_timer.start()
                webview.start(gui="edgechromium", func=automated_task)
            else:
                # Human mode: no driver, no auto actions, no watchdog.
                webview.start(gui="edgechromium")
    except BaseException as exc:  # noqa: BLE001 - keep cleanup on GUI faults
        error = f"run: {type(exc).__name__}: {exc}"
        exit_code = 2 if exit_code == 0 else exit_code
    finally:
        if smoke_timer is not None:
            smoke_timer.cancel()
        cleanup = _cleanup(
            service, runtime, worker_unconfirmed=worker_unconfirmed
        )
        mode = "smoke" if args.smoke else ("dom" if args.dom_check else "human")
        automated_error = summary.get("smoke_error") or summary.get("dom_error")
        report = {
            "ok": False,
            "mode": mode,
            "window_title": WINDOW_TITLE,
            "error": error,
            "elapsed_seconds": round(time.time() - started, 3),
            **cleanup,
            "smoke": summary.get("smoke"),
            "dom_check": summary.get("dom_check"),
            "automated_error": automated_error,
            "smoke_timed_out": smoke_timed_out["value"],
            "data": str(root / "data"),
            "manual_root": str(root),
        }
        if args.dom_check:
            report["dom_ok"] = bool(summary.get("dom_check")) and not automated_error
        report["ok"] = (
            error is None
            and cleanup["worker_exit_confirmed"]
            and cleanup["server_stopped"]
            and cleanup["runtime_lock_released"]
            and not automated_error
            and not smoke_timed_out["value"]
        )
        if not report["ok"]:
            exit_code = exit_code or 3
        _write_json(exit_report, report)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
