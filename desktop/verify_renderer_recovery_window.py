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
import hashlib
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


def _is_link_like(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        stat = path.stat(follow_symlinks=False)
    except OSError:
        return False
    return bool(getattr(stat, "st_file_attributes", 0) & 0x400)


def _has_raw_parent(path: Path) -> bool:
    raw = str(path).replace("\\", "/")
    return any(part == ".." for part in raw.split("/"))


def _check_existing_chain(path: Path) -> None:
    current = Path(os.path.abspath(str(path)))
    while True:
        if current.exists() or current.is_symlink():
            if _is_link_like(current):
                raise ValueError(f"reparse point in path: {current.name}")
        if current.parent == current:
            break
        current = current.parent


def _validate_synthetic_paths(
    data_root: Path, credential_root: Path, out: Path
) -> dict[str, str]:
    """Fail closed on the verifier's synthetic roots/output boundaries."""
    paths = {
        "data": data_root,
        "credential": credential_root,
        "output": out,
    }
    for label, path in paths.items():
        if _has_raw_parent(path):
            raise ValueError(f"{label}: raw parent segment")
        _check_existing_chain(path)
        if path.exists() or path.is_symlink():
            raise ValueError(f"{label}: path must be fresh")
    resolved = {
        label: Path(os.path.abspath(str(path))).resolve(strict=False)
        for label, path in paths.items()
    }
    for left_label, left in resolved.items():
        for right_label, right in resolved.items():
            if left_label >= right_label:
                continue
            if left == right or left in right.parents or right in left.parents:
                raise ValueError(
                    f"{left_label}/{right_label}: paths overlap"
                )
    return {label: str(path) for label, path in resolved.items()}


def _validate_persist_paths(cli) -> dict[str, Path]:
    """Fail closed before the cold child can create/read a wrong archive."""
    if not cli.expected_fingerprint or not cli.persist_out:
        raise ValueError("expected/output arguments are required")
    data_root = Path(cli.data)
    credential_root = Path(cli.credential_root)
    expected = Path(cli.expected_fingerprint)
    output = Path(cli.persist_out)
    for label, path in (
        ("data", data_root),
        ("credential", credential_root),
        ("expected", expected),
        ("output", output),
    ):
        if _has_raw_parent(path):
            raise ValueError(f"{label}: raw parent segment")
        _check_existing_chain(path)
    if not data_root.is_dir():
        raise ValueError("data root missing or not a directory")
    db_path = data_root / "kindergarten.db"
    if not db_path.is_file():
        raise ValueError("data root has no kindergarten.db")
    _check_existing_chain(db_path)
    if not credential_root.is_dir():
        raise ValueError("credential root missing or not a directory")
    if not expected.is_file():
        raise ValueError("expected fingerprint file missing")
    if output.exists() or output.is_symlink():
        raise ValueError("persist output must be fresh")
    if not output.parent.is_dir():
        raise ValueError("persist output parent missing")
    resolved = {
        "data": data_root.resolve(strict=False),
        "credential": credential_root.resolve(strict=False),
        "expected": expected.resolve(strict=False),
        "output": output.resolve(strict=False),
    }
    for label in ("expected", "output"):
        target = resolved[label]
        for root_label in ("data", "credential"):
            root = resolved[root_label]
            if target == root or target in root.parents or root in target.parents:
                raise ValueError(f"{label}/{root_label}: paths overlap")
    if resolved["expected"] == resolved["output"]:
        raise ValueError("expected/output paths overlap")
    return {
        "data": data_root,
        "credential": credential_root,
        "expected": expected,
        "output": output,
        "db": db_path,
    }


def _validate_output_directory(out: Path) -> dict[str, Path]:
    """Require one fresh per-window output directory and no stale sidecars."""
    parent = out.parent
    if out.name.casefold() in (
        "recovery-persist-expected.json",
        "recovery-persist-child.json",
    ):
        raise ValueError("main output collides with a fixed sidecar")
    if parent.exists() or parent.is_symlink():
        if _is_link_like(parent) or not parent.is_dir():
            raise ValueError("output parent must be a plain directory")
        if any(parent.iterdir()):
            raise ValueError("output directory must be fresh and empty")
    return {
        "expected": parent / "recovery-persist-expected.json",
        "child": parent / "recovery-persist-child.json",
    }


def _host_page_state(host) -> dict:
    """Read the exact bound page state under the host's own page lock."""
    lock = getattr(host, "_page_lock", None)
    if lock is None:
        raise RuntimeError("host page lock missing")
    with lock:
        business_ready = getattr(host, "_business_ready", None)
        return {
            "retired": bool(getattr(host, "_retired", False)),
            "page_ready": bool(getattr(host, "_page_ready", False)),
            "ticket_bound": bool(getattr(host, "_page_ticket_bound", False)),
            "business_ready": bool(
                business_ready.is_set()
                if business_ready is not None
                and callable(getattr(business_ready, "is_set", None))
                else False
            ),
            "ticket": getattr(host, "_page_ticket", None),
            "launch_token": getattr(host, "_launch_token", None),
            "maintenance_notice": getattr(host, "_maintenance_notice", None),
            "document_generation": getattr(host, "_document_generation", None),
            "page_busy": bool(getattr(host, "_page_busy", False)),
        }


def _fingerprint(value) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _public_host_state(state: dict) -> dict:
    return {
        "retired": bool(state.get("retired")),
        "page_ready": bool(state.get("page_ready")),
        "ticket_bound": bool(state.get("ticket_bound")),
        "business_ready": bool(state.get("business_ready")),
        "ticket_fingerprint": _fingerprint(state.get("ticket")),
        "launch_fingerprint": _fingerprint(state.get("launch_token")),
        "maintenance_notice": state.get("maintenance_notice"),
        "document_generation": state.get("document_generation"),
        "page_busy": bool(state.get("page_busy")),
    }


def _active_page(state: dict) -> bool:
    return bool(
        state.get("page_ready")
        and state.get("ticket_bound")
        and state.get("business_ready")
        and state.get("ticket")
        and state.get("launch_token")
        and not state.get("retired")
    )


def _readonly_status(port: int, token: str) -> int:
    connection = http.client.HTTPConnection("127.0.0.1", int(port), timeout=3)
    try:
        connection.request(
            "GET",
            "/api/local/context",
            headers={
                "Host": f"127.0.0.1:{int(port)}",
                "Origin": f"http://127.0.0.1:{int(port)}",
                "X-App-Session": token,
            },
        )
        response = connection.getresponse()
        response.read()
        return int(response.status)
    finally:
        connection.close()


def _fingerprint_summary(fingerprint: dict) -> dict:
    database = fingerprint.get("database") or {}
    resources = fingerprint.get("resources") or {}
    return {
        "combined_sha256": fingerprint.get("combined_sha256"),
        "database_sha256": database.get("fingerprint_sha256"),
        "resources_sha256": resources.get("fingerprint_sha256"),
        "schema_revision": database.get("schema_revision"),
        "table_count": len(database.get("tables") or {}),
        "resource_count": resources.get("file_count"),
        "resource_total_bytes": resources.get("total_bytes"),
        "semantic_counts": database.get("counts"),
    }


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
    """Child-process full persistence readback; no window, JS, provider or AI."""
    import sqlite3

    from app.local.runtime import LocalRuntime
    from tests.local import backup_fixture_support as fixture

    try:
        paths = _validate_persist_paths(cli)
        expected = json.loads(
            paths["expected"].read_text(encoding="utf-8")
        )
    except Exception as exc:  # noqa: BLE001 - CLI boundary is fail-closed
        print(f"PERSIST_INVALID: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    data_root = paths["data"]
    out = paths["output"]
    try:
        expected_fingerprint = expected["fingerprint"]
        expected_counts = expected["table_counts"]
    except Exception as exc:  # noqa: BLE001 - malformed expected file
        print(f"PERSIST_INVALID: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    runtime = LocalRuntime(
        str(data_root), credential_root=str(paths["credential"])
    )
    try:
        runtime.prepare()
        fingerprint = fixture.runtime_fingerprint(runtime)
        counts = _query_counts(runtime)
        connection = sqlite3.connect(str(runtime.db_path))
        try:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            foreign = connection.execute("PRAGMA foreign_key_check").fetchall()
        finally:
            connection.close()
        result = {
            "counts": counts,
            "expected_counts": expected_counts,
            "counts_match": counts == expected_counts,
            "fingerprint_match": fingerprint == expected_fingerprint,
            "combined_sha256": fingerprint.get("combined_sha256"),
            "database_sha256": (
                fingerprint.get("database") or {}
            ).get("fingerprint_sha256"),
            "resources_sha256": (
                fingerprint.get("resources") or {}
            ).get("fingerprint_sha256"),
            "integrity_check": integrity,
            "foreign_key_ok": not foreign,
        }
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0 if (
            result["fingerprint_match"]
            and result["counts_match"]
            and integrity == "ok"
            and not foreign
        ) else 1
    finally:
        runtime.dispose()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    parser.add_argument("--credential-root", required=True)
    parser.add_argument("--frontend")
    parser.add_argument("--out")
    parser.add_argument("--persist-check", action="store_true")
    parser.add_argument("--expected-fingerprint")
    parser.add_argument("--persist-out")
    parser.add_argument(
        "--fault-kind",
        choices=("Page.crash", "Browser.crash"),
        default="Page.crash",
    )
    cli = parser.parse_args()
    if cli.persist_check:
        return _persist_check(cli)
    if not cli.frontend or not cli.out:
        parser.error("--frontend and --out are required for the window mode")

    data_root = Path(cli.data)
    credential_root = Path(cli.credential_root)
    frontend = Path(cli.frontend)
    out = Path(cli.out)
    try:
        boundary = _validate_synthetic_paths(data_root, credential_root, out)
        sidecars = _validate_output_directory(out)
    except ValueError as exc:
        print(f"BOUNDARY_INVALID: {exc}", file=sys.stderr)
        return 2
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
        "fault_kind": cli.fault_kind,
        "boundary": boundary,
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
    before_fingerprint = None
    old_ticket = None
    old_host = None
    old_launch_token = None
    old_state = None
    new_host = None
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
            nonlocal before_fingerprint, old_launch_token, old_state, new_host
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
                old_state = _host_page_state(old_host)
                result["old_page_state"] = _public_host_state(old_state)
                if not _active_page(old_state):
                    fail("old_page_not_bound_business_ready")
                    return
                old_ticket = old_state["ticket"]
                old_launch_token = str(old_state["launch_token"] or "")
                before_counts = _query_counts(runtime)
                before_fingerprint = fixture.runtime_fingerprint(runtime)
                if before_fingerprint != evidence.fingerprint:
                    fail("fixture_fingerprint_mismatch_before")
                    return
                fixture.validate_fixture(runtime, evidence)
                result["fixture_validation_before"] = "ok"
                result["before_counts"] = before_counts
                result["before_archive_fingerprint"] = _fingerprint_summary(
                    before_fingerprint
                )
                result["fixture_fingerprint"] = before_fingerprint["combined_sha256"]

                def crash_on_ui():
                    form = old_window.native
                    browser = getattr(form, "browser", None)
                    control = getattr(browser, "webview", None)
                    core = getattr(control, "CoreWebView2", None)
                    ownership = {
                        "form_current": form is not None and form is old_form,
                        "form_owns_window": (
                            form is not None
                            and getattr(form, "pywebview_window", None)
                            is old_window
                        ),
                        "browser_owns_window": (
                            browser is not None
                            and getattr(browser, "pywebview_window", None)
                            is old_window
                        ),
                        "webview_identity": (
                            control is not None
                            and control is getattr(form, "webview", None)
                            and control is getattr(browser, "webview", None)
                        ),
                        "core_present": core is not None,
                    }
                    result["crash_ownership"] = ownership
                    if not all(ownership.values()):
                        return "ownership"
                    result["crash_browser_pid"] = int(core.BrowserProcessId)
                    result["crash_kind"] = cli.fault_kind
                    core.CallDevToolsProtocolMethodAsync(cli.fault_kind, "{}")
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

                new_host = getattr(new_bundle, "host_api", None)
                if new_host is None:
                    fail("new_host_missing")
                    return
                new_state = _host_page_state(new_host)
                result["new_page_state"] = _public_host_state(new_state)
                if not _active_page(new_state):
                    fail("new_page_not_bound_business_ready")
                    return

                after_counts = _query_counts(runtime)
                after_fingerprint = fixture.runtime_fingerprint(runtime)
                result["after_counts"] = after_counts
                result["after_archive_fingerprint"] = _fingerprint_summary(
                    after_fingerprint
                )
                archive_unchanged = bool(
                    after_fingerprint == before_fingerprint == evidence.fingerprint
                )
                result["archive_fingerprint_unchanged"] = archive_unchanged
                if after_counts != before_counts:
                    fail("task_or_attempt_delta")
                    return
                if not archive_unchanged:
                    fail("archive_fingerprint_changed")
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
                result["fixture_validation_after"] = "ok"
                result["task_attempt_ai_receipts_unchanged"] = bool(
                    after_fingerprint["database"]["tables"]
                    == before_fingerprint["database"]["tables"]
                )

                old_after = _host_page_state(old_host)
                result["old_host_state_after"] = _public_host_state(old_after)
                old_bootstrap = old_host.get_bootstrap()
                result["old_host_retired"] = bool(
                    old_after.get("retired")
                    and not old_after.get("page_ready")
                    and old_bootstrap.get("retired") is True
                )
                if not result["old_host_retired"]:
                    fail("old_host_not_retired")
                    return
                result["recovery_notice"] = new_state.get("maintenance_notice")
                if result["recovery_notice"] != renderer_recovery.RECOVERY_NOTICE:
                    fail("recovery_notice_missing")
                    return
                new_ticket = new_state.get("ticket")
                new_launch_token = new_state.get("launch_token")
                result["new_ticket_changed"] = bool(
                    old_ticket and new_ticket and new_ticket != old_ticket
                )
                result["launch_token_changed"] = bool(
                    old_launch_token
                    and new_launch_token
                    and new_launch_token != old_launch_token
                )
                result["old_ticket_fingerprint"] = _fingerprint(old_ticket)
                result["new_ticket_fingerprint"] = _fingerprint(new_ticket)
                result["old_launch_fingerprint"] = _fingerprint(old_launch_token)
                result["new_launch_fingerprint"] = _fingerprint(new_launch_token)
                if not result["new_ticket_changed"]:
                    fail("page_ticket_reused")
                    return
                if not result["launch_token_changed"]:
                    fail("launch_token_reused")
                    return

                before_ticket_submission = _host_page_state(new_host)
                result["old_ticket_submission_before"] = _public_host_state(
                    before_ticket_submission
                )
                submission = new_host.page_business_ready(
                    {"page_ticket": old_ticket}
                )
                after_ticket_submission = _host_page_state(new_host)
                submission_state_unchanged = bool(
                    before_ticket_submission == after_ticket_submission
                )
                result["old_ticket_submission"] = {
                    "accepted": submission.get("accepted"),
                    "state_unchanged": submission_state_unchanged,
                    "after": _public_host_state(after_ticket_submission),
                }
                if (
                    submission.get("accepted") is not False
                    or not submission_state_unchanged
                ):
                    fail("old_ticket_not_rejected_cleanly")
                    return
                result["old_ticket_rejected"] = True

                new_port = int(new_bundle.service.port)
                old_status = _readonly_status(new_port, old_launch_token)
                new_status = _readonly_status(new_port, new_launch_token)
                result["new_port_old_token_status"] = old_status
                result["new_port_new_token_status"] = new_status
                if old_status != 401 or new_status != 200:
                    fail("new_port_token_auth_failed")
                    return
                result["new_port_auth"] = "ok"

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

        # True child-process full fingerprint readback after a cold LocalRuntime
        # prepare; no window, JS, provider or AI, and no data copy.
        try:
            expected_path = sidecars["expected"]
            child_path = sidecars["child"]
            if before_fingerprint is None:
                raise RuntimeError("before fingerprint missing")
            expected_path.write_text(
                json.dumps(
                    {
                        "fingerprint": before_fingerprint,
                        "table_counts": before_counts,
                    },
                    ensure_ascii=False,
                ),
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
                    "--expected-fingerprint",
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
                "fingerprint_match": bool(child_result.get("fingerprint_match")),
                "counts_match": bool(child_result.get("counts_match")),
                "combined_sha256": child_result.get("combined_sha256"),
                "database_sha256": child_result.get("database_sha256"),
                "resources_sha256": child_result.get("resources_sha256"),
                "integrity_check": child_result.get("integrity_check"),
                "foreign_key_ok": bool(child_result.get("foreign_key_ok")),
            }
            if (
                child.returncode == 0
                and child_result.get("fingerprint_match")
                and child_result.get("counts_match")
                and child_result.get("integrity_check") == "ok"
                and child_result.get("foreign_key_ok")
            ):
                result["persist"] = "ok"
            else:
                result["persist"] = "failed"
                result["persist_error"] = "PERSIST_SUBPROCESS"
        except Exception as exc:  # noqa: BLE001 - persistent evidence
            result["persist"] = "failed"
            result["persist_error"] = type(exc).__name__

        success = bool(
            result.get("stage") == "reopened"
            and result.get("normal_close") == "closed"
            and result.get("close_latest") is True
            and result.get("persist") == "ok"
            and result.get("archive_fingerprint_unchanged") is True
            and result.get("task_attempt_ai_receipts_unchanged") is True
            and result.get("fixture_validation_before") == "ok"
            and result.get("fixture_validation_after") == "ok"
            and result.get("old_host_retired") is True
            and result.get("old_ticket_rejected") is True
            and result.get("new_ticket_changed") is True
            and result.get("launch_token_changed") is True
            and result.get("new_port_auth") == "ok"
        )
        result["success"] = success
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0 if success else 1
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
