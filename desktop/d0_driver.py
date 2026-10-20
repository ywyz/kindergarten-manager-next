"""Automated window driver for the D0 self-test.

Drives the REAL WebView2 window (the same Vue/Element Plus page a teacher
sees) through the actual page functions via ``window.evaluate_js``:
  - host-provided session retrieval (window.pywebview.api),
  - guarded and unguarded API access from the window,
  - SQLite probe save / read-back / simulated failure from the UI,
  - Word generation through the real page export entry, its ``/api`` call
    and the restricted host save.

Every required assertion is recorded in ``results['checks']`` and combined
by :func:`combine_ok`; a timeout, a refused save, a missing restart read-back
or a failed process cleanup can never be reported as success (R10).

Every *successful* save is additionally checked to advance the record version
by exactly one (a first save into an empty DB must be version 1), and the API
view is compared against an independent SQLite read for both content and
version. A save that keeps or skips the version, or an API/DB disagreement, is
a failure even when the content looks right.

The human save dialog (choosing a Chinese/space path, cancel, occupied target)
remains a manual acceptance step; the automated path uses the pre-authorized
autosave directory. Window closing is owned by the caller (``d0_main``) so an
abnormal self-test can shut the window without a human.
"""

import io
import json
import sys
import time
import zipfile

_TUNNEL_VERBOSE = True


def combine_ok(checks: dict) -> bool:
    """Overall success requires at least one check and every check true."""
    return bool(checks) and all(bool(value) for value in checks.values())


def _log(message: str) -> None:
    if not _TUNNEL_VERBOSE:
        return
    stream = getattr(sys, "stdout", None)
    if stream is None:
        return
    try:
        stream.write(f"[d0-driver] {message}\n")
        stream.flush()
    except Exception:
        pass


def _evaluate(window, expression: str):
    return window.evaluate_js(expression)


def _await_js(window, expression: str, timeout: float = 15.0):
    """Run an async JS expression and poll for its JSON result."""
    window.evaluate_js(
        "window.__d0Result = null; window.__d0Done = false;"
        f"window.__d0Expr = (async () => ({expression}))()"
        ".then(v => {window.__d0Result = JSON.stringify(v ?? null);"
        "window.__d0Done = true;})"
        ".catch(e => {window.__d0Result = JSON.stringify({__error: String(e)});"
        "window.__d0Done = true;});"
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        done = _evaluate(window, "window.__d0Done === true")
        if done:
            raw = _evaluate(window, "window.__d0Result")
            try:
                return json.loads(raw)
            except (TypeError, ValueError):
                return {"__error": f"unparseable: {raw!r}"}
        time.sleep(0.1)
    _log(f"await timeout for: {expression[:120]}")
    return {"__error": "timeout"}


def _wait_page_ready(window, timeout: float = 40.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if _evaluate(window, "window.__d0PageReady === true"):
                return True
        except Exception:
            pass
        time.sleep(0.2)
    return False


def _record_compat(results: dict, window) -> None:
    """Non-sensitive readiness diagnostics (no token) for page_ready failures."""
    compat: dict = {}
    for key, expr in (
        ("mount_stage", "window.__d0MountStage ?? null"),
        ("page_ready", "window.__d0PageReady === true"),
        ("title", "document.title"),
        ("pywebview_type", "typeof window.pywebview"),
        (
            "session_api_ready",
            "!!(window.pywebview && window.pywebview.api && "
            "typeof window.pywebview.api.get_session === 'function')",
        ),
    ):
        try:
            compat[key] = _evaluate(window, expr)
        except Exception as exc:
            compat[key] = f"__error: {exc}"
    results["compat"] = compat


def _verify_docx_file(path: str) -> bool:
    """Read back the saved DOCX (verification only, never generation)."""
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError:
        return False
    if not data:
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return archive.testzip() is None
    except zipfile.BadZipFile:
        return False


def drive_window(
    probe,
    *,
    phase: str = "first",
    expect_content: str | None = None,
    expect_version: int | None = None,
    session_tag: str | None = None,
) -> dict:
    """Return a JSON-serializable evidence summary; requires no human input."""
    import webview  # noqa: PLC0415

    window = webview.windows[0]
    results: dict = {"phase": phase}
    checks: dict = {}
    results["checks"] = checks

    page_ready = _wait_page_ready(window)
    _record_compat(results, window)
    results["page_ready"] = page_ready
    checks["page_ready"] = page_ready
    _log(f"page_ready={page_ready}")
    if not page_ready:
        results["ok"] = combine_ok(checks)
        return results

    def step(name, expr, timeout=15.0):
        value = _await_js(window, expr, timeout)
        results[name] = value
        errored = isinstance(value, dict) and bool(value.get("__error"))
        checks[f"{name}_ran"] = not errored
        if errored:
            _log(f"step {name} error: {value!r}"[:220])
        else:
            _log(f"step end {name}: {value!r}"[:220])
        return value

    # -- session + guards ---------------------------------------------------
    session = step("host_session", "window.__d0.collectSession()", timeout=20.0)
    checks["session_has_token"] = bool(
        isinstance(session, dict) and session.get("hasToken")
    )
    results["token_in_url"] = "token" in (window.get_current_url() or "").lower()
    checks["token_not_in_url"] = not results["token_in_url"]

    unauth = step("state_get_without_session", "window.__d0.getStateNoHeader()")
    checks["unauth_rejected"] = bool(
        isinstance(unauth, dict)
        and unauth.get("ok") is False
        and unauth.get("status") == 401
    )
    health = step("health_no_session", "window.__d0.getHealth()")
    checks["health_minimal"] = bool(
        isinstance(health, dict)
        and health.get("status") == "ok"
        and "data_dir" not in json.dumps(health)
        and "db_path" not in json.dumps(health)
    )

    # -- read old state BEFORE any write (restart evidence) -----------------
    initial = step("initial_state", "window.__d0.getStateWithHeader()")
    initial_ok = isinstance(initial, dict) and initial.get("status") in ("ok", "empty")
    checks["initial_state_read"] = initial_ok
    results["initial_state"] = initial
    initial_content = initial.get("content") if isinstance(initial, dict) else None
    initial_version = initial.get("version") if isinstance(initial, dict) else None
    results["initial_content"] = initial_content
    results["initial_version"] = initial_version
    if expect_content is not None:
        checks["restart_content_matches"] = initial_content == expect_content
        results["expected_content"] = expect_content
    if expect_version is not None:
        checks["restart_version_matches"] = initial_version == expect_version
        results["expected_version"] = expect_version

    tag = session_tag or str(int(time.time()))
    content_a = f"D0 合成内容A {tag}"
    content_b = f"D0 合成内容B {tag}"
    results["content_a"] = content_a
    results["content_b"] = content_b

    if phase == "first":
        old_version = initial_version if isinstance(initial_version, int) else 0
        results["expected_first_version"] = old_version + 1
        saved = step(
            "ui_save_a",
            "window.__d0.triggerUiSave(" + json.dumps({"content": content_a}) + ")",
        )
        checks["ui_save_a_message"] = bool(
            isinstance(saved, dict) and saved.get("messageVisible")
        )
        state_a = step("state_after_save_a", "window.__d0.getStateWithHeader()")
        state_a_content = state_a.get("content") if isinstance(state_a, dict) else None
        state_a_version = state_a.get("version") if isinstance(state_a, dict) else None
        read_a = probe.read()
        read_a_content = read_a.get("content")
        read_a_version = read_a.get("version")
        results["api_state_a"] = {
            "content": state_a_content,
            "version": state_a_version,
        }
        results["python_readback_a"] = {
            "status": read_a.get("status"),
            "version": read_a_version,
            "content_matches": read_a_content == content_a,
        }
        checks["save_a_visible"] = bool(
            state_a_content == content_a and isinstance(state_a_version, int)
        )
        # R10: a successful save must land exactly on old + 1 (a first save
        # into an empty DB is version 1). Version unchanged/skipped fails.
        checks["save_a_version_advanced"] = state_a_version == old_version + 1
        # The API view and the independent SQLite read must agree on both
        # content and version; matching content alone is not enough.
        checks["save_a_api_db_consistent"] = bool(
            read_a.get("status") == "ok"
            and read_a_content == state_a_content
            and read_a_version == state_a_version
            and read_a_content == content_a
        )
        _run_word_check(step, results, checks)
    elif phase == "restart":
        # edit to B, force a write failure: DB stays at A, input stays B.
        failed = step(
            "ui_save_b_failure",
            "window.__d0.triggerUiSave("
            + json.dumps({"content": content_b, "simulateFailure": True})
            + ")",
        )
        checks["failure_message_shown"] = bool(
            isinstance(failed, dict) and failed.get("failureMessageVisible")
        )
        checks["failure_input_kept_b"] = bool(
            isinstance(failed, dict) and failed.get("inputContent") == content_b
        )
        state_fail = step("state_after_failure", "window.__d0.getStateWithHeader()")
        checks["failure_kept_previous"] = bool(
            isinstance(state_fail, dict)
            and state_fail.get("content") == expect_content
            and state_fail.get("version") == expect_version
        )
        read_fail = probe.read()
        checks["db_unchanged_after_failure"] = bool(
            read_fail.get("content") == expect_content
            and read_fail.get("version") == expect_version
        )
        checks["failure_api_db_consistent"] = bool(
            isinstance(state_fail, dict)
            and read_fail.get("status") == "ok"
            and read_fail.get("content") == state_fail.get("content")
            and read_fail.get("version") == state_fail.get("version")
        )
        # uncheck the simulation and retry the same B explicitly.
        retried = step(
            "ui_save_b_retry",
            "window.__d0.triggerUiSave("
            + json.dumps({"content": content_b, "simulateFailure": False})
            + ")",
        )
        checks["retry_message_success"] = bool(
            isinstance(retried, dict) and retried.get("messageVisible")
        )
        state_b = step("state_after_retry", "window.__d0.getStateWithHeader()")
        state_b_content = state_b.get("content") if isinstance(state_b, dict) else None
        state_b_version = state_b.get("version") if isinstance(state_b, dict) else None
        read_b = probe.read()
        read_b_content = read_b.get("content")
        read_b_version = read_b.get("version")
        results["api_state_b"] = {
            "content": state_b_content,
            "version": state_b_version,
        }
        results["python_readback_b"] = {
            "status": read_b.get("status"),
            "version": read_b_version,
            "content_matches": read_b_content == content_b,
        }
        expected_b_version = (
            expect_version + 1 if isinstance(expect_version, int) else None
        )
        results["expected_retry_version"] = expected_b_version
        checks["retry_saved_b"] = state_b_content == content_b
        # The failed attempt must not have moved the version, so the retry has
        # to land exactly on old + 1 (R10); content alone is not evidence.
        checks["retry_version_advanced"] = bool(
            isinstance(expected_b_version, int) and state_b_version == expected_b_version
        )
        checks["retry_api_db_consistent"] = bool(
            read_b.get("status") == "ok"
            and read_b_content == state_b_content
            and read_b_version == state_b_version
            and read_b_content == content_b
        )
    elif phase == "verify":
        if expect_content is not None:
            checks["verify_content"] = initial_content == expect_content
    else:
        raise ValueError(f"unknown selftest phase: {phase}")

    results["ok"] = combine_ok(checks)
    return results


def _run_word_check(step, results: dict, checks: dict) -> None:
    """Generate through the real page export entry -> API -> host save."""
    word = step(
        "ui_word_export",
        "window.__d0.triggerWordExportAutosave("
        + json.dumps("D0自动保存_日计划.docx")
        + ")",
        timeout=60.0,
    )
    status = word.get("status") if isinstance(word, dict) else None
    path = word.get("path") if isinstance(word, dict) else None
    results["docx_saved_status"] = status
    results["docx_saved_path"] = path
    checks["docx_saved_via_page"] = status == "saved"
    checks["docx_file_valid"] = bool(
        status == "saved" and isinstance(path, str) and _verify_docx_file(path)
    )
