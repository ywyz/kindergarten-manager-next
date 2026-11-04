"""Source-only verifier: native renderer fault -> explicit same-database reopen.

Run with the repository venv, a fresh synthetic data/credential root, the
reviewed frontend directory and an output path:

    python desktop/verify_renderer_recovery_window.py \
        --data <temp>/data --credential-root <temp>/credentials \
        --frontend <round>/recovery-frontend --out <round>/result.json

It is never a normal product switch and is not packaged.  It uses the real
d1_main runtime/service/window wiring, the fixture's full saved archive, and
B's native prompt; it never calls a real AI supplier.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import webview
import webview.platforms.edgechromium  # noqa: F401 - load WebView2 CLR
from System import Action, Func, Object
from System.Windows.Forms import Application, Button

import d1_main
import maintenance_lifecycle
import renderer_recovery


PROMPT_TITLE = "页面已停止"
REOPEN_TEXT = "重新打开最后保存的档案"
KEEP_TEXT = "保留当前窗口"


class VerifierArgs(SimpleNamespace):
    def __getattr__(self, name):  # noqa: D105 - optional d1_main CLI fields
        return None


def _find_prompt_controls(owner) -> tuple[int, list[str]]:
    for form in Application.OpenForms:
        if str(getattr(form, "Text", "")) != PROMPT_TITLE:
            continue
        buttons = [
            str(getattr(control, "Text", ""))
            for control in form.Controls
            if isinstance(control, Button)
        ]
        return len(buttons), buttons
    return 0, []


def _wait_for_prompt(owner, timeout: float = 15.0) -> tuple[int, list[str]]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            count, texts = owner.Invoke(
                Func[Object](lambda: _find_prompt_controls(owner))
            )
        except Exception:
            return 0, []
        if count:
            return int(count), list(texts)
        time.sleep(0.05)
    return 0, []


def _click_prompt(owner, text: str) -> bool:
    def action():
        for form in Application.OpenForms:
            if str(getattr(form, "Text", "")) != PROMPT_TITLE:
                continue
            for control in form.Controls:
                if isinstance(control, Button) and str(
                    getattr(control, "Text", "")
                ) == text:
                    control.PerformClick()
                    return True
        return False

    try:
        return bool(owner.Invoke(Func[Object](action)))
    except Exception:
        return False


def _query_counts(runtime) -> dict[str, int]:
    import sqlite3

    connection = sqlite3.connect(str(runtime.db_path))
    try:
        names = (
            "local_ai_tasks",
            "local_ai_executions",
            "local_ai_attempts",
            "local_daily_plan_contents",
            "local_observation_records",
            "local_observation_assets",
        )
        result = {}
        for name in names:
            try:
                result[name] = int(
                    connection.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]
                )
            except sqlite3.Error:
                result[name] = -1
        return result
    finally:
        connection.close()


def _ui_form_alive(form) -> bool:
    try:
        return bool(form) and not bool(form.IsDisposed)
    except Exception:
        return False


def _persist_check(cli) -> int:
    """Child-process persistence readback; no window, JS, provider or AI."""
    import sqlite3

    from app.local.runtime import LocalRuntime

    data_root = Path(cli.data)
    out = Path(cli.persist_out)
    expected = json.loads(Path(cli.expected_counts).read_text(encoding="utf-8"))
    runtime = LocalRuntime(
        str(data_root), credential_root=str(cli.credential_root)
    )
    try:
        runtime.prepare()
        counts = _query_counts(runtime)
        connection = sqlite3.connect(str(runtime.db_path))
        try:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            foreign = connection.execute("PRAGMA foreign_key_check").fetchall()
        finally:
            connection.close()
        result = {
            "counts": counts,
            "expected": expected,
            "counts_match": counts == expected,
            "integrity_check": integrity,
            "foreign_key_ok": not foreign,
        }
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0 if result["counts_match"] and integrity == "ok" and not foreign else 1
    finally:
        runtime.dispose()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    parser.add_argument("--credential-root", required=True)
    parser.add_argument("--frontend")
    parser.add_argument("--out")
    parser.add_argument("--persist-check", action="store_true")
    parser.add_argument("--expected-counts")
    parser.add_argument("--persist-out")
    cli = parser.parse_args()
    if cli.persist_check:
        return _persist_check(cli)
    if not cli.frontend or not cli.out:
        parser.error("--frontend and --out are required for the window mode")

    data_root = Path(cli.data)
    credential_root = Path(cli.credential_root)
    frontend = Path(cli.frontend)
    out = Path(cli.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    args = VerifierArgs(
        data=str(data_root),
        credential_root=str(credential_root),
        frontend=str(frontend),
        selftest=False,
        phase="",
        out=str(out),
        screenshot_dir=None,
        word_out=None,
        b3_config=None,
        u3_config=None,
        u3_source_identity=None,
        u3_verify_stop=None,
        u3_close_cancel=False,
        synthetic_executor_fail=None,
        synthetic_provider_port=None,
        synthetic_provider_ip=None,
        synthetic_provider_ca=None,
    )

    result: dict = {
        "stage": "start",
        "prompt_keep": None,
        "prompt_reopen": None,
        "normal_close": None,
        "persist": None,
        "errors": [],
    }
    service = None
    runtime = None
    lifecycle = None
    old_window = None
    old_form = None
    recovery = None
    evidence = None
    before_counts = None
    old_ticket = None
    old_host = None
    old_port = None
    old_launch_token = None
    finished = threading.Event()

    def fail(code: str, exc: BaseException | None = None) -> None:
        result["stage"] = code
        if exc is not None:
            result["errors"].append({"code": code, "type": type(exc).__name__})
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        from tests.local import backup_fixture_support as fixture

        service, host_api, runtime = d1_main.build_runtime(args)
        old_executor = runtime.ai_executor
        # Seed only while the production executor is briefly frozen: the
        # fixture creates terminal/paused receipts, never a real provider call.
        # Unfreeze immediately after seeding so recovery must perform the real
        # owner freeze/atomic stop; verification must not mask ownership.
        if old_executor is not None:
            old_executor.freeze(owner="verifier:seed")
        evidence = fixture.seed_existing_runtime(runtime)
        if old_executor is not None:
            old_executor.unfreeze(owner="verifier:seed")
        if not service.start_and_wait():
            raise RuntimeError(f"service start failed: {service.error}")

        lifecycle = maintenance_lifecycle.LifecycleManager()
        old_window = webview.create_window(
            "幼儿园教师工作台（本地）",
            url=f"http://127.0.0.1:{service.port}/",
            js_api=host_api,
            width=1180,
            height=820,
            min_size=(760, 560),
            text_select=True,
        )
        old_form = old_window.native if old_window is not None else None
        host_api._bind_window(old_window)
        recovery_holder: dict = {}
        d1_main._install_close_handlers(
            old_window,
            host_api,
            runtime,
            weekly_export_manager=getattr(service, "weekly_export_manager", None),
            recovery_holder=recovery_holder,
        )
        bundle = maintenance_lifecycle.LifecycleBundle(
            generation=lifecycle.next_generation(),
            service=service,
            host_api=host_api,
            runtime=runtime,
            window=old_window,
            executor=old_executor,
        )
        lifecycle.install(bundle)
        bundle.retire_destroy = lambda: d1_main._retire_destroy_window(bundle)
        host_api._bind_maintenance(
            d1_main._build_maintenance_host(args, runtime, lifecycle, bundle)
        )
        recovery = d1_main._install_renderer_recovery(
            old_window, host_api, lifecycle, bundle, runtime, args, recovery_holder
        )
        if recovery is None:
            raise RuntimeError("renderer recovery was not installed")

        def driver():
            nonlocal old_form, old_ticket, old_host, before_counts, recovery
            nonlocal old_port, old_launch_token
            try:
                if not old_window.events.loaded.wait(30):
                    fail("page_not_loaded")
                    return
                old_form = old_window.native
                if old_form is None:
                    fail("native_form_missing")
                    return
                if not host_api._wait_business_ready(60):
                    fail("business_not_ready")
                    return
                old_host = host_api
                bootstrap = host_api.get_bootstrap()
                old_ticket = bootstrap["page_ticket"]
                old_port = int(service.port)
                old_launch_token = str(bootstrap.get("launch_token") or "")
                before_counts = _query_counts(runtime)
                result["before_counts"] = before_counts
                result["fixture_fingerprint"] = evidence.fingerprint["combined_sha256"]

                def crash_on_ui():
                    form = old_window.native
                    if form is None or form.pywebview_window is not old_window:
                        return "ownership"
                    browser = getattr(form, "browser", None)
                    control = getattr(browser, "webview", None)
                    core = getattr(control, "CoreWebView2", None)
                    if core is None:
                        return "core"
                    result["crash_browser_pid"] = int(core.BrowserProcessId)
                    core.CallDevToolsProtocolMethodAsync("Page.crash", "{}")
                    return "sent"

                sent = old_form.Invoke(Func[Object](crash_on_ui))
                result["crash_send"] = str(sent)
                if sent != "sent":
                    fail("crash_not_sent")
                    return
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline and not recovery.faulted:
                    time.sleep(0.05)
                if not recovery.faulted:
                    fail("fault_not_observed")
                    return

                count, texts = _wait_for_prompt(old_form, 20)
                result["prompt_keep"] = {"count": count, "texts": texts}
                if count != 2 or sorted(texts) != sorted([REOPEN_TEXT, KEEP_TEXT]):
                    fail("prompt_not_exact")
                    return
                if not _click_prompt(old_form, KEEP_TEXT):
                    fail("keep_click_failed")
                    return
                if not recovery._worker_done.wait(15):
                    fail("keep_worker_timeout")
                    return
                result["keep_state"] = recovery.state
                if recovery.state != recovery.KEPT:
                    fail("keep_state_wrong")
                    return
                if not _ui_form_alive(old_form):
                    fail("old_window_lost_after_keep")
                    return

                old_form.Invoke(Action(lambda: old_form.Close()))
                count, texts = _wait_for_prompt(old_form, 20)
                result["prompt_reopen"] = {"count": count, "texts": texts}
                if count != 2 or sorted(texts) != sorted([REOPEN_TEXT, KEEP_TEXT]):
                    fail("second_prompt_not_exact")
                    return
                if not _click_prompt(old_form, REOPEN_TEXT):
                    fail("reopen_click_failed")
                    return
                if not recovery._worker_done.wait(90):
                    fail("reopen_worker_timeout")
                    return
                result["reopen_state"] = recovery.state
                if recovery.state != recovery.RECOVERED:
                    fail("reopen_failed")
                    return

                new_bundle = lifecycle.current()
                new_window = getattr(new_bundle, "window", None)
                if new_window is None or new_window is old_window:
                    fail("new_window_missing")
                    return
                if not new_window.events.loaded.wait(30):
                    fail("new_window_not_loaded")
                    return
                result["new_window_uid"] = str(getattr(new_window, "uid", ""))
                result["old_window_alive_after_reopen"] = _ui_form_alive(old_form)
                if _ui_form_alive(old_form):
                    fail("old_window_still_alive")
                    return

                after_counts = _query_counts(runtime)
                result["after_counts"] = after_counts
                if after_counts != before_counts:
                    fail("task_or_attempt_delta")
                    return
                old_stopped = (
                    old_executor is None
                    or getattr(old_executor, "_thread", "missing") is None
                )
                result["old_executor_stopped"] = bool(old_stopped)
                if not old_stopped:
                    fail("old_executor_not_stopped")
                    return
                try:
                    fixture.validate_fixture(runtime, evidence)
                except Exception as exc:  # noqa: BLE001 - fixture is authoritative
                    result["fixture_validation_error"] = type(exc).__name__
                    fail("saved_data_validation_failed", exc)
                    return
                result["saved_data"] = "ok"

                old_bootstrap = old_host.get_bootstrap()
                result["old_host_retired"] = bool(old_bootstrap.get("retired"))
                if not result["old_host_retired"]:
                    fail("old_host_not_retired")
                    return
                new_bootstrap = new_bundle.host_api.get_bootstrap()
                result["recovery_notice"] = new_bootstrap.get("maintenance_notice")
                if result["recovery_notice"] != renderer_recovery.RECOVERY_NOTICE:
                    fail("recovery_notice_missing")
                    return
                new_ticket = new_bootstrap.get("page_ticket")
                result["new_ticket_changed"] = bool(new_ticket and new_ticket != old_ticket)
                if not result["new_ticket_changed"]:
                    fail("page_ticket_reused")
                    return
                if new_bundle.host_api.page_business_ready(
                    {"page_ticket": old_ticket}
                )["accepted"]:
                    fail("old_ticket_accepted")
                    return
                result["old_ticket_rejected"] = True
                result["launch_token_changed"] = bool(
                    old_launch_token
                    and new_bootstrap.get("launch_token") != old_launch_token
                )
                if not result["launch_token_changed"]:
                    fail("launch_token_reused")
                    return
                try:
                    connection = http.client.HTTPConnection(
                        "127.0.0.1", old_port, timeout=3
                    )
                    connection.request(
                        "POST",
                        "/api/daily-plans",
                        body=b"{}",
                        headers={
                            "Host": f"127.0.0.1:{old_port}",
                            "Origin": f"http://127.0.0.1:{old_port}",
                            "X-App-Session": old_launch_token,
                            "Content-Type": "application/json",
                        },
                    )
                    status = int(connection.getresponse().status)
                    connection.close()
                    result["old_http_status"] = status
                    if status not in (401, 403):
                        fail("old_http_token_not_rejected")
                        return
                    result["old_http_token_rejected"] = True
                except OSError:
                    result["old_http_token_rejected"] = True
                    result["old_http_status"] = "connection_refused"

                new_form = getattr(new_window, "native", None)
                if new_form is None:
                    fail("new_form_missing")
                    return
                result["normal_close"] = "issued"
                new_form.Invoke(Action(lambda: new_form.Close()))
                if not new_window.events.closed.wait(45):
                    fail("new_window_close_timeout")
                    return
                result["normal_close"] = "closed"
                result["stage"] = "reopened"
            except Exception as exc:  # noqa: BLE001 - verifier boundary
                fail("driver_exception", exc)
            finally:
                finished.set()
                out.write_text(
                    json.dumps(result, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                if result.get("stage") != "reopened":
                    try:
                        old_window.destroy()
                    except Exception:
                        pass

        def watchdog():
            if not finished.wait(180):
                fail("watchdog_timeout")
                os._exit(3)

        threading.Thread(target=watchdog, daemon=True).start()
        result["stage"] = "window_start"
        webview.start(gui="edgechromium", func=driver, debug=False)
        finished.set()
        result["webview_start_returned"] = True

        try:
            if lifecycle is not None:
                result["close_latest"] = bool(lifecycle.close_latest(timeout=10.0))
        except Exception as exc:  # noqa: BLE001 - report only
            result["close_latest_error"] = type(exc).__name__

        # True child-process persistence: only the counts/integrity are read
        # back, and no real provider or credential is touched.
        try:
            expected_path = out.parent / "recovery-persist-expected.json"
            child_path = out.parent / "recovery-persist-child.json"
            expected_path.write_text(
                json.dumps(result.get("before_counts") or {}, indent=2),
                encoding="utf-8",
            )
            env = os.environ.copy()
            env["APP_DISABLE_DOTENV"] = "1"
            child = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--persist-check",
                    "--data",
                    str(data_root),
                    "--credential-root",
                    str(credential_root),
                    "--expected-counts",
                    str(expected_path),
                    "--persist-out",
                    str(child_path),
                ],
                cwd=str(Path(__file__).resolve().parent.parent),
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
            )
            child_result = (
                json.loads(child_path.read_text(encoding="utf-8"))
                if child_path.is_file()
                else {}
            )
            result["persist_subprocess"] = {
                "exit": child.returncode,
                "counts_match": bool(child_result.get("counts_match")),
                "integrity_check": child_result.get("integrity_check"),
                "foreign_key_ok": bool(child_result.get("foreign_key_ok")),
            }
            if child.returncode == 0 and child_result.get("counts_match"):
                result["persist"] = "ok"
            else:
                result["persist"] = "failed"
                result["persist_error"] = "PERSIST_SUBPROCESS"
        except Exception as exc:  # noqa: BLE001 - persistent evidence
            result["persist"] = "failed"
            result["persist_error"] = type(exc).__name__

        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0 if result.get("stage") == "reopened" and result.get("persist") == "ok" else 1
    except Exception as exc:  # noqa: BLE001 - verifier boundary
        fail("top_level_exception", exc)
        return 1
    finally:
        # Never leave this verifier's own windows/services behind on failure.
        try:
            if old_window is not None and old_form is not None and _ui_form_alive(old_form):
                old_form.Invoke(Action(lambda: old_form.Close()))
        except Exception:
            pass
        try:
            if lifecycle is not None and lifecycle.current() is not None:
                lifecycle.close_latest(timeout=10.0)
        except Exception:
            pass
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
