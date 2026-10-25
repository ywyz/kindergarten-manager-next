"""D1 desktop entry (pywebview + WebView2), packaged as KGNext-D1Verify.

Startup: resolve resources → verify WebView2 → build the local app with the
injected synthetic data directory → start uvicorn in a bounded readiness
window → open the real D1 window with the restricted host API → on window
close, stop the server, release the database and exit.

``--selftest --phase first|restart|verify`` drives the *real* page through
``evaluate_js`` hooks for the packaged verification runs (real WebView2
window, real DOM operations through the real page functions, real API and
real SQLite file); the human interactive flow is the default.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import threading
import time
from pathlib import Path

import d0_paths
import d1_paths

# Source runs need the backend package on sys.path (the frozen package
# bundles it); never manipulate paths when frozen.
if not getattr(sys, "frozen", False):
    _backend = str(d0_paths.BACKEND_ROOT)
    if _backend not in sys.path:
        sys.path.insert(0, _backend)

# Divert a frozen spawn child bootstrap before any argument parsing, GUI import
# or other startup side effect (PyInstaller requirement). A no-op in the normal
# parent process and in a source run.
from app.local.ai_spawn import freeze_support_guarded  # noqa: E402

freeze_support_guarded()

from d0_main import (  # noqa: E402
    ServiceRun,
    STARTUP_STREAM_STATE,
    ensure_console_streams,
    free_loopback_port,
    show_error,
    webview2_runtime_version,
)

SELFTEST_DEADLINE_SECONDS = 240.0

# Optional startup diagnostics (verification only): when set, each startup
# step appends one line to this file. Never writes elsewhere and is inert
# for normal runs.
STARTUP_LOG_ENV = "KGM_D1_STARTUP_LOG"


def _startup_log(message: str) -> None:
    target = os.environ.get(STARTUP_LOG_ENV)
    if not target:
        return
    try:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%H:%M:%S')} {message}\n")
            handle.flush()
    except OSError:
        pass


# Dedicated synthetic verification phases: the only phases that may receive a
# controlled provider resolution / test CA / executor-failure injection. *Every*
# dedicated phase must be given an explicit synthetic data root (checked before
# any LocalRuntime construction); every other launch (interactive or a D1
# selftest) never accepts an injection.
_DEDICATED_SYNTHETIC_PHASES = (
    "w5-ui",
    "w6-ui",
    "w6-ui-verify",
    "g15-noexec",
    "w6-resources",
    "d3-h2-ui",
    "d3-h2-verify",
    "u3-update",
    "u3-verify",
)
# Phases that must run with a controlled provider (they exercise the real
# executor/worker/TLS).
_PROVIDER_REQUIRED_PHASES = ("w5-ui", "w6-ui", "w6-resources", "d3-h2-ui")
# Phases that may optionally receive a controlled provider resolution (the G15
# network branch uses a closed local port); ``w6-ui-verify`` deliberately may
# not accept one.
_PROVIDER_ALLOWED_PHASES = _PROVIDER_REQUIRED_PHASES + ("g15-noexec",)

# W6 G14 discriminating process texts (shared with the controlled provider).
# The model baseline keeps its first two lines; the teacher's final process
# keeps an *unchanged* paragraph, contains a replacement and an added
# paragraph, and differs from both the preview edit and the adapt result — so
# the Word redline can actually distinguish a drifted baseline.
W6_MODEL_PROCESS = "一、导入\n二、观察\n三、比较"
W6_PREVIEW_PROCESS = "一、导入\n二、观察\n三、比较（预览版）"
W6_ADAPT_PROCESS = "一、导入\n二、观察\n三、比较（适龄版）"
W6_FINAL_PROCESS = "一、导入\n二、观察（教师改为细致观察）\n三、比较\n四、教师新增段落"

# D3-A H2 synthetic history fixture: the split baseline stays at the model
# process; the historical manual version differs, and the later current version
# differs again. A restore of the historical version must export a redline
# against the baseline, not against the later current text.
H2_BASELINE_PROCESS = "一、导入\n二、观察\n三、比较"
H2_HISTORY_PROCESS = "一、导入\n二、观察（历史版）\n三、比较\n四、历史新增"
H2_CURRENT_PROCESS = "一、导入\n二、观察（当前版）\n三、比较"
H2_SPLIT_OUT = json.dumps(
    {
        "group_activity": {
            "theme": "H2 合成主题",
            "objectives": "H2 合成目标",
            "preparation": "H2 合成准备",
            "key_points": "H2 合成重点",
            "difficult_points": "H2 合成难点",
            "process": H2_BASELINE_PROCESS,
        }
    },
    ensure_ascii=False,
)

# Verification-only page injection used by drive_d3_h2_ui. Kept as a module
# constant so the cleanup regression executes the exact production JS, not a
# copied/simplified reimplementation.
H2_DELAYED_GET_INSTALL_JS = (
    "(() => {"
    " const real = window.fetch.bind(window);"
    " window.__h2RealFetch = real;"
    " window.__h2DelayNextPlanGet = true;"
    " window.__h2DelayedGetStarted = false;"
    " window.__h2ReleaseCalled = false;"
    " window.__h2ReleaseGet = null;"
    " window.__h2CleanupFetch = function() {"
    "   if (window.__h2ReleaseGet) {"
    "     try { window.__h2ReleaseGet(); } catch (e) {}"
    "   }"
    "   if (window.__h2RealFetch) window.fetch = window.__h2RealFetch;"
    " };"
    " window.fetch = function(url, options) {"
    "   const method = ((options || {}).method || 'GET').toUpperCase();"
    "   const text = String(url);"
    "   if (window.__h2DelayNextPlanGet && method === 'GET'"
    "       && /\\/api\\/daily-plans\\/[^/?]+$/.test(text)) {"
    "     window.__h2DelayNextPlanGet = false;"
    "     window.__h2DelayedGetStarted = true;"
    "     return new Promise(function(resolve, reject) {"
    "       window.__h2ReleaseGet = function() {"
    "         if (window.__h2ReleaseCalled) return;"
    "         window.__h2ReleaseCalled = true;"
    "         return real(url, options).then(resolve, reject);"
    "       };"
    "     });"
    "   }"
    "   return real(url, options);"
    " };"
    " return true;"
    "})()"
)

H2_CLEANUP_JS = (
    "(() => {"
    " let cleanupError = null;"
    " if (window.__h2CleanupFetch) {"
    "   try { window.__h2CleanupFetch(); } catch (e) { cleanupError = e; }"
    " }"
    " if (window.__h2ReleaseGet) {"
    "   try { window.__h2ReleaseGet(); } catch (e) {"
    "     if (!cleanupError) cleanupError = e;"
    "   }"
    " }"
    " if (window.__h2RealFetch) window.fetch = window.__h2RealFetch;"
    " if (cleanupError) throw cleanupError;"
    " return true;"
    "})()"
)


def _dedicated_synthetic(args) -> bool:
    return (
        bool(getattr(args, "selftest", False))
        and getattr(args, "phase", "") in _DEDICATED_SYNTHETIC_PHASES
    )


def _validate_synthetic_entry(args) -> None:
    """Validate the dedicated synthetic entry BEFORE any runtime/lock/prepare.

    Rules (W6 R09):

    * an injection argument outside a dedicated selftest phase is refused;
    * **every** dedicated phase must carry an explicit synthetic ``--data``
      root, so a missing argument can never fall back to the real teacher data
      directory (the check runs before ``LocalRuntime`` is even constructed);
    * a provider-required phase must supply the controlled provider port;
    * a non-provider phase (except the optional-network ``g15-noexec``) must not
      receive a private-resolution injection;
    * the executor-failure injection is only accepted by ``g15-noexec``.
    """
    phase = getattr(args, "phase", "")
    dedicated = _dedicated_synthetic(args)
    port = getattr(args, "synthetic_provider_port", None)
    executor_fail = getattr(args, "synthetic_executor_fail", None)
    if not dedicated:
        if port is not None or executor_fail is not None:
            raise RuntimeError(
                "受控 provider 解析/CA 与执行器失败注入仅允许专用自检相位"
            )
        return
    if not getattr(args, "data", None):
        raise RuntimeError(f"{phase} 自检必须显式提供 --data 合成数据根")
    if phase in ("u3-update", "u3-verify") and not getattr(
        args, "credential_root", None
    ):
        raise RuntimeError(f"{phase} 自检必须显式提供 --credential-root 合成凭据根")
    if phase == "u3-update" and not getattr(args, "u3_config", None):
        raise RuntimeError("u3-update 自检必须提供 --u3-config")
    if phase == "u3-verify" and not getattr(args, "u3_source_identity", None):
        raise RuntimeError("u3-verify 自检必须提供 --u3-source-identity")
    if phase == "u3-verify" and not getattr(args, "u3_verify_stop", None):
        raise RuntimeError("u3-verify 自检必须提供 --u3-verify-stop")
    if phase in _PROVIDER_REQUIRED_PHASES and port is None:
        raise RuntimeError(f"{phase} 自检必须提供受控 provider 端口")
    if phase not in _PROVIDER_ALLOWED_PHASES and port is not None:
        raise RuntimeError(f"{phase} 自检不接受受控 provider/私网解析注入")
    if executor_fail is not None and phase != "g15-noexec":
        raise RuntimeError("执行器失败注入仅允许 g15-noexec 自检")


def _synthetic_transport_from_args(args):
    """A verification-only controlled transport (never available via env).

    Only a dedicated verification CLI (the W5 window driver) supplies a
    synthetic provider host/port + test CA; an ordinary run passes neither, so
    the production transport keeps rejecting private/loopback targets.
    """
    port = getattr(args, "synthetic_provider_port", None)
    if not port:
        return None
    ca = getattr(args, "synthetic_provider_ca", None)
    ca_pem = Path(ca).read_text(encoding="utf-8") if ca else None
    return {
        "resolution": [
            {
                "family": 2,
                "ip": getattr(args, "synthetic_provider_ip", "127.0.0.1"),
                "port": int(port),
            }
        ],
        "ca_pem": ca_pem,
    }


class _ExecutorUnconfirmed(RuntimeError):
    """The AI executor could not be torn down; startup is refused.

    Carries the executor so the host keeps ownership; the runtime lock is
    deliberately **not** released while a worker is unconfirmed.
    """

    def __init__(self, executor):
        super().__init__("AI worker 未能确认退出，拒绝启动且不释放运行锁")
        self.executor = executor


def _failing_start_thread_factory(**kwargs):
    """A real ``threading.Thread`` whose second ``start()`` raises.

    Used only by the dedicated verification entry to exercise a genuine
    ``threading.Thread.start`` failure: a harmless thread is started with a
    no-op target, so the factory-returned object's next ``start()`` raises the
    standard-library ``RuntimeError`` ("threads can only be started once")
    without ever running the coordinator loop or any worker.
    """
    import threading as _threading

    def _noop() -> None:
        return None

    thread = _threading.Thread(
        target=_noop, name=kwargs.get("name"), daemon=True
    )
    thread.start()
    return thread


def _start_ai_executor(runtime, args):
    """Start the AI executor, or degrade to "unavailable" when it cannot run.

    Returns ``(executor_or_None, reason_or_None, unconfirmed_bool)``.

    G15 (engineering spec §6 / product spec C9): an executor that cannot be
    imported, constructed or started must not fail the whole application. The
    manual path (read/edit/save/restart/native export) stays fully usable and
    the AI endpoints answer 503 ``AI_EXECUTOR_UNAVAILABLE`` — the executor is
    never silently reported as available.

    Degradation is only allowed when no worker can be left running. Any failure
    after an executor object exists must be confirmed gone by ``dispose()``:
    an unconfirmed worker returns ``unconfirmed=True`` so the host keeps the
    executor and refuses startup without releasing the runtime lock. A
    ``start()`` that returns False (cold-start recovery failed) keeps the
    executor object (``is_runnable()`` False) so close coordination still owns
    it while scheduling stays blocked.
    """
    executor = None
    try:
        from app.local.ai_executor import AiExecutor
    except Exception as exc:  # noqa: BLE001 - import failure degrades, never kills the app
        return None, f"{type(exc).__name__}: {exc}", False

    fail_at = getattr(args, "synthetic_executor_fail", None) or ""
    try:
        if fail_at == "construct":
            raise RuntimeError("synthetic executor construction failure")
        thread_factory = (
            _failing_start_thread_factory if fail_at == "start" else None
        )
        executor = AiExecutor(
            runtime,
            synthetic_transport=_synthetic_transport_from_args(args),
            thread_factory=thread_factory,
        )
        started = executor.start()
        if started is False:
            return executor, "recovery_failed", False
        return executor, None, False
    except Exception as exc:  # noqa: BLE001 - G15 degradation path
        reason = f"{type(exc).__name__}: {exc}"
        if executor is None:
            return None, reason, False
        confirmed = False
        try:
            confirmed = bool(executor.dispose())
        except Exception:  # noqa: BLE001
            confirmed = False
        if confirmed:
            return None, reason, False
        return executor, reason, True


def _source_verification_context(args) -> bool:
    """Only the validated, non-frozen U3 source phase may relax target exe."""
    return bool(
        not getattr(sys, "frozen", False)
        and getattr(args, "selftest", False)
        and getattr(args, "phase", "") == "u3-verify"
        and getattr(args, "u3_source_identity", None)
        and os.environ.get("KGM_UPDATE_VERIFICATION_CONTEXT") == "1"
    )


def build_runtime(args):
    """Create (service, host_api, runtime) for one window run."""
    _startup_log("build_runtime:start")
    _validate_synthetic_entry(args)
    u3_args = bool(
        getattr(args, "u3_config", None)
        or getattr(args, "u3_source_identity", None)
        or getattr(args, "u3_verify_stop", None)
        or getattr(args, "u3_close_cancel", False)
    )
    if u3_args and (
        getattr(sys, "frozen", False)
        or not (
            getattr(args, "selftest", False)
            and getattr(args, "phase", "") in ("u3-update", "u3-verify")
        )
    ):
        raise RuntimeError("U3 源码验证参数只允许专用源码验证相位")
    from app.local.runtime import LocalRuntime

    _startup_log("build_runtime:app.local.runtime imported")
    import d1_host_api
    import d1_server

    _startup_log("build_runtime:d1 modules imported")
    data_dir = args.data
    if data_dir:
        os.environ["KGM_LOCAL_DATA_DIR"] = str(Path(data_dir))
    runtime = LocalRuntime(
        args.data,
        credential_root=getattr(args, "credential_root", None),
    )
    _startup_log(f"build_runtime:runtime at {runtime.db_path}")
    service = None
    executor = None
    try:
        # Prepare (lock + migrations + prompt-bundle sync) BEFORE the executor
        # starts its cold-start classification, so recovery runs against a
        # ready database and before the API can accept a request.
        runtime.prepare()
        port = free_loopback_port()
        token = secrets.token_urlsafe(32)
        # One AI executor per application launch; it owns the coordinator
        # thread, the spawn workers and the Job Objects. A construction/start
        # failure degrades to "AI unavailable" (G15) instead of failing the
        # whole launch; an unconfirmed worker still refuses the launch.
        executor, ai_reason, ai_unconfirmed = _start_ai_executor(runtime, args)
        if ai_unconfirmed:
            # Keep the executor owned by the runtime: the only thing that may
            # end the unconfirmed worker is a later dispose attempt or process
            # exit. The runtime lock is NOT released here.
            runtime.ai_executor = executor
            raise _ExecutorUnconfirmed(executor)
        if executor is None:
            _startup_log(f"build_runtime:AI executor unavailable ({ai_reason})")
        runtime.ai_executor = executor
        app = d1_server.build_d1_app(
            runtime=runtime,
            port=port,
            session_token=token,
            frontend_dir=args.frontend,
            executor=executor,
        )
        _startup_log(f"build_runtime:app built port {port}")
        service = ServiceRun(app, port)
        import update_identity
        import update_install
        import update_paths
        import update_service
        import update_trust
        import update_u3_harness

        u3_config = None
        if getattr(args, "u3_config", None):
            u3_config = update_u3_harness.load_config(args.u3_config)
        launch_plan = update_install.read_launch_plan_from_env()
        identity = update_identity.load_app_identity(
            database_revision=runtime.current_revision or ""
        )
        if getattr(args, "u3_source_identity", None):
            identity = update_identity.load_app_identity(
                database_revision=runtime.current_revision or "",
                path=args.u3_source_identity,
                require_packaged=True,
            )
        if launch_plan is not None:
            expected = launch_plan.target
            if (
                identity is None
                or identity.app_id != expected.get("app_id")
                or identity.version != expected.get("version")
                or identity.build_id != expected.get("build_id")
                or identity.package_format != expected.get("package_format")
                or identity.database_revision != expected.get("database_revision")
            ):
                raise RuntimeError("更新后的程序构建身份与安装计划不一致")
        source = None
        update_enabled = bool(getattr(sys, "frozen", False))
        if u3_config is not None:
            source = update_u3_harness.release_source(u3_config)
            update_enabled = True
        identity_unavailable = identity is None
        if identity is None:
            # A frozen package without a trustworthy build identity must not
            # silently become a source checkout. Keep manual work available,
            # but disable product updates.
            identity = update_identity.load_app_identity(
                database_revision=runtime.current_revision or "",
                require_packaged=False,
            )
            update_enabled = False
        if update_enabled and u3_config is None:
            try:
                source = update_trust.load_release_source()
            except update_trust.ReleaseConfigError:
                source = None
        update_manager = update_service.UpdateManager(
            identity,
            source=source,
            enabled=update_enabled,
            disabled_reason=(
                "UPDATE_IDENTITY_UNAVAILABLE"
                if identity_unavailable
                else "UPDATE_DISABLED_SOURCE_RUN"
            ),
            data_dir=runtime.data_dir,
            credential_root=runtime.credential_root,
            staging_root=(
                Path(u3_config["staging_root"]) if u3_config is not None else None
            ),
        )
        install_coordinator = None
        if update_enabled:
            try:
                if u3_config is not None:
                    install_coordinator = update_install.InstallCoordinator(
                        identity=identity,
                        data_dir=runtime.data_dir,
                        credential_root=runtime.credential_root,
                        install_root=Path(u3_config["install_root"]),
                        app_dir=Path(u3_config["app_dir"]),
                        helper_command=list(u3_config["helper_command"]),
                        release_config=u3_config.get(
                            "release_config", args.u3_config
                        ),
                        test_only=True,
                        new_app_command=list(u3_config["new_app_command"]),
                    )
                else:
                    install_coordinator = update_install.InstallCoordinator(
                        identity=identity,
                        data_dir=runtime.data_dir,
                        credential_root=runtime.credential_root,
                        install_root=update_paths.install_root(),
                        app_dir=Path(sys.executable).parent,
                        helper_command=[str(update_paths.updater_exe())],
                        release_config=(
                            d1_paths.package_root() / "update_release.json"
                        ),
                    )
            except Exception:
                install_coordinator = None
        ready_receipt = None
        if launch_plan is not None:
            verification_context = _source_verification_context(args)
            ready_receipt = update_install.ReadyReceiptWriter(
                launch_plan,
                identity=identity,
                runtime=runtime,
                service=service,
                service_port=port,
                verification_context=verification_context,
            )
        host_api = d1_host_api.D1HostApi(
            launch_token=token,
            update_manager=update_manager,
            install_coordinator=install_coordinator,
            ready_receipt=ready_receipt,
        )
        _startup_log("build_runtime:done")
    except _ExecutorUnconfirmed:
        # An unconfirmed AI worker must never be released: keep the executor and
        # the runtime lock, and refuse startup.
        raise
    except Exception:
        if executor is not None:
            try:
                executor.dispose()
            except Exception:  # noqa: BLE001
                pass
        runtime.dispose()
        raise
    return service, host_api, runtime


# ---------------------------------------------------------------------------
# Selftest driver (real window; page hooks run the real component functions)
# ---------------------------------------------------------------------------


class JsDriver:
    """evaluate_js wrapper that can never hang the driver forever.

    pywebview's evaluate_js waits for the page's JS bridge without a timeout;
    each call here runs on a worker thread with a hard timeout, so a page
    whose bridge never responds turns into a bounded failure (and the
    watchdog can then end the process) instead of an eternal hang.
    """

    EVAL_TIMEOUT = 25.0

    def __init__(self, window):
        self.window = window

    def eval(self, script: str):
        _startup_log(f"eval: {script[:100]}")
        outcome: dict = {}

        def call():
            try:
                outcome["value"] = self.window.evaluate_js(script)
            except Exception as exc:  # noqa: BLE001
                outcome["error"] = exc

        worker = threading.Thread(target=call, daemon=True)
        worker.start()
        worker.join(self.EVAL_TIMEOUT)
        if worker.is_alive():
            _startup_log(f"eval timeout: {script[:100]}")
            raise RuntimeError(f"evaluate_js 未在时限内返回：{script[:120]}")
        if "error" in outcome:
            raise outcome["error"]
        return outcome.get("value")

    def eval_json(self, script: str):
        value = self.eval(script)
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        return value

    def wait_until(self, script: str, *, timeout: float = 30.0, what: str = "条件"):
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            try:
                last = self.eval(script)
            except Exception as exc:  # window may not be ready yet
                last = f"error: {exc}"
            if last is True:
                return
            time.sleep(0.1)
        raise RuntimeError(f"等待超时（{what}），最后结果：{last!r}")


def probe_http(port: int) -> dict:
    """HTTP evidence for the packaged shell (works even if JS is dead)."""
    import urllib.error
    import urllib.request

    report: dict = {}
    for path in ("/", "/d1.html"):
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}{path}", timeout=10
            ) as response:
                body = response.read()
                report[path] = {
                    "status": response.status,
                    "bytes": len(body),
                    "has_app_marker": b"__d1App" not in body
                    and b"/assets/" in body,
                }
        except Exception as exc:  # noqa: BLE001
            report[path] = {"error": str(exc)}
    return report


def _http_json(port: int, token: str, method: str, path: str, body: dict | None = None):
    """Raw local-API call for the verification driver (real HTTP)."""
    import urllib.error
    import urllib.request

    data = None
    headers = {
        "X-App-Session": token,
        "Host": f"127.0.0.1:{port}",
        "Accept": "application/json",
    }
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
        headers["Origin"] = f"http://127.0.0.1:{port}"
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=data, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
            return response.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8")
        try:
            return error.code, json.loads(raw)
        except json.JSONDecodeError:
            return error.code, raw


def _http_bytes(port: int, token: str, method: str, path: str, body: dict | None = None):
    """Raw local-API call that returns bytes (DOCX export evidence)."""
    import urllib.error
    import urllib.request

    data = None
    headers = {
        "X-App-Session": token,
        "Host": f"127.0.0.1:{port}",
        "Accept": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
        headers["Origin"] = f"http://127.0.0.1:{port}"
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=data, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.status, response.read(), dict(response.headers)
    except urllib.error.HTTPError as error:
        return error.code, error.read(), dict(error.headers)


def _capture_window_bmp(path: Path, title: str) -> None:
    """Capture the visible WebView2 window to a BMP (no external dependency).

    The source window is the only visible top-level window with this exact
    title. ``PrintWindow`` is tried first (WebView2 renders through composition);
    a screen BitBlt is the fallback. The screenshot is evidence for human
    visual review, not an automated pixel oracle.
    """
    import ctypes
    import struct
    import time
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
    user32.FindWindowW.restype = wintypes.HWND
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.GetWindowDC.argtypes = [wintypes.HWND]
    user32.GetWindowDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, ctypes.c_uint]
    user32.PrintWindow.restype = wintypes.BOOL
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.BitBlt.argtypes = [
        wintypes.HDC,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HDC,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.DWORD,
    ]
    gdi32.BitBlt.restype = wintypes.BOOL
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteDC.argtypes = [wintypes.HDC]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]

    hwnd = user32.FindWindowW(None, title)
    if not hwnd:
        raise RuntimeError(f"未找到验证窗口：{title}")
    user32.ShowWindow(hwnd, 5)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.6)
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise RuntimeError("GetWindowRect failed")
    width = max(1, rect.right - rect.left)
    height = max(1, rect.bottom - rect.top)
    hdc = user32.GetWindowDC(hwnd)
    memdc = gdi32.CreateCompatibleDC(hdc)
    bitmap = gdi32.CreateCompatibleBitmap(hdc, width, height)
    old = gdi32.SelectObject(memdc, bitmap)
    try:
        # PW_RENDERFULLCONTENT = 2; fall back to a screen/window BitBlt.
        if not user32.PrintWindow(hwnd, memdc, 2):
            gdi32.BitBlt(memdc, 0, 0, width, height, hdc, 0, 0, 0x00CC0020)
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = width
        bmi.bmiHeader.biHeight = height
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 24
        bmi.bmiHeader.biCompression = 0
        stride = ((width * 3 + 3) // 4) * 4
        size = stride * height
        buffer = ctypes.create_string_buffer(size)
        gdi32.GetDIBits.argtypes = [
            wintypes.HDC,
            wintypes.HBITMAP,
            wintypes.UINT,
            wintypes.UINT,
            ctypes.c_void_p,
            ctypes.POINTER(BITMAPINFO),
            wintypes.UINT,
        ]
        gdi32.GetDIBits.restype = ctypes.c_int
        copied = gdi32.GetDIBits(
            memdc, bitmap, 0, height, buffer, ctypes.byref(bmi), 0
        )
        if copied != height:
            raise RuntimeError(f"GetDIBits copied {copied}/{height} rows")
        header = b"BM" + struct.pack(
            "<IHHI", 14 + 40 + size, 0, 0, 54
        ) + struct.pack(
            "<IiiHHIIiiII",
            40,
            width,
            height,
            1,
            24,
            0,
            size,
            2835,
            2835,
            0,
            0,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(header + buffer.raw)
    finally:
        gdi32.SelectObject(memdc, old)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memdc)
        user32.ReleaseDC(hwnd, hdc)


def _screenshot(args, summary: dict, name: str) -> None:
    target = getattr(args, "screenshot_dir", None)
    if not target:
        return
    path = Path(target) / f"{name}.bmp"
    _capture_window_bmp(path, f"D1 验证窗口（{args.phase}）")
    summary.setdefault("screenshots", []).append(str(path))


class _H2StepFailed(RuntimeError):
    """A verification step failed; the remaining dependent chain must stop."""


def _h2_step(summary: dict, checks: dict, name: str, fn, *, error_key: str = "h2_errors") -> None:
    """Run one verification step, record its first error and abort the chain.

    Continuing after a failed prerequisite would let a later successful step
    hide the first failure. The summary keeps the first error and the caller's
    driver task exits; no dependent step is executed.
    """
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 - evidence, then stop
        checks[name] = False
        summary.setdefault(error_key, {})[name] = str(exc)
        summary.setdefault("h2_first_error", {"step": name, "error": str(exc)})
        _startup_log(f"h2 step failed {name}: {exc}")
        raise _H2StepFailed(f"{name}: {exc}") from exc
    checks[name] = True


def _cleanup_h2_fetch(driver, summary: dict) -> None:
    """Release a delayed restore GET and restore the real page fetch.

    Called from a ``finally`` so a failed DOM assertion cannot leave the
    synthetic fetch wrapper installed or the parent GET suspended. Cleanup
    failures are recorded but never replace the original step error.
    """
    try:
        driver.eval(H2_CLEANUP_JS)
    except Exception as exc:  # noqa: BLE001 - preserve the original error
        summary.setdefault("h2_cleanup_errors", []).append(str(exc))
        _startup_log(f"h2 fetch cleanup failed: {exc}")


def drive_d3_h2_ui(driver, args, summary, checks, host_api, port) -> None:
    """D3-A H2 real-window history/restore flow (source WebView2).

    A controlled local TLS provider supplies only the split candidate used to
    create a real split baseline; no external supplier or real credential is
    involved. The window then creates a historical manual version (process Y),
    a later current version (process Z, historical groups removed), compares
    and restores Y, and verifies the restored current content/identity.
    """
    token = getattr(host_api, "_launch_token", "")
    if not token:
        raise RuntimeError("d3-h2-ui: host token missing")

    def http(method, path, body=None):
        return _http_json(port, token, method, path, body)

    def step(name, fn):
        _h2_step(summary, checks, name, fn, error_key="h2_errors")

    driver.wait_until(
        "Boolean(window.__d1App && window.__d1App.ready())", what="H2 页面启动", timeout=40
    )
    if driver.eval("window.__d1App.state()") == "uninitialized":
        driver.eval(
            "window.__d1Setup.fill("
            + json.dumps(
                {
                    "display_name": "H2教师",
                    "class_name": "H2中一班",
                    "grade": "middle",
                    "term_name": "H2学期",
                    "start_date": args.term_start,
                    "end_date": args.term_end,
                    "school_name": "H2园所",
                },
                ensure_ascii=False,
            )
            + ")"
        )
        driver.eval("window.__d1Setup.submit()")
        driver.wait_until("window.__d1App.state() === 'ready'", what="H2 初始化", timeout=60)
    checks["h2_initialized"] = True

    def configure_ai():
        status, config = http(
            "PATCH",
            "/api/local/ai/config",
            {
                "request_id": "d3a11111-2222-4333-8444-555566667777",
                "expected_ai_config_version": 0,
                "protocol_id": "chat_completions_v1",
                "base_url": "https://api.example.com/v1",
                "model": "h2-synthetic",
                "secret": "h2-synthetic-secret",
            },
        )
        summary["h2_config_status"] = status
        assert status == 200 and isinstance(config, dict) and config.get("configured"), (
            f"AI configuration failed: {status} {config!r}"
        )

    step("h2_ai_configured", configure_ai)

    driver.wait_until(
        "Boolean(window.__d1Workbench && typeof window.__d1Workbench.openDate === 'function')",
        what="H2 工作台就绪",
        timeout=30,
    )
    driver.eval(f"window.__d1Workbench.openDate({json.dumps(args.date)})")
    driver.wait_until("window.__d1App.view() === 'editor'", what="H2 进入编辑器", timeout=30)
    driver.wait_until(
        "window.__d1Editor && ['ready','create_confirmation'].includes(window.__d1Editor.phase())",
        what="H2 编辑器就绪",
        timeout=30,
    )
    if driver.eval("window.__d1Editor.phase()") == "create_confirmation":
        driver.eval("window.__d1Editor.confirmCreate()")
        driver.wait_until(
            "window.__d1Editor.phase() === 'ready'", what="H2 创建日计划", timeout=30
        )
    plan_id = driver.eval("window.__d1Editor.planId()")
    summary["h2_plan_id"] = plan_id

    def save_initial():
        driver.eval("window.__d1Editor.fillAll('历史v1')")
        driver.wait_until("window.__d1Editor.dirty() === true", what="H2 初始内容变脏", timeout=15)
        driver.eval("window.__d1Editor.save()")
        driver.wait_until(
            "window.__d1Editor.phase() === 'ready' && window.__d1Editor.dirty() === false",
            what="H2 初始内容保存",
            timeout=30,
        )
        summary["h2_initial_version"] = driver.eval("window.__d1Editor.version()")
        assert summary["h2_initial_version"] >= 2, "initial content version missing"

    step("h2_initial_saved", save_initial)

    baseline_version = None

    def create_baseline():
        nonlocal baseline_version
        driver.eval("window.__d1AiTasks.trigger('daily_lesson_split')")
        driver.wait_until(
            "window.__d1AiTasks.tasks().some(function(t){return"
            " t.task_type==='daily_lesson_split' && t.status==='succeeded'"
            " && t.candidate_id})",
            what="H2 拆分候选",
            timeout=120,
        )
        task = next(
            task
            for task in driver.eval("window.__d1AiTasks.tasks()")
            if task.get("task_type") == "daily_lesson_split"
        )
        candidate_id = task.get("candidate_id")
        summary["h2_candidate_id"] = candidate_id
        driver.eval(f"window.__d1Editor.openCandidate({json.dumps(candidate_id)})")
        driver.wait_until(
            "window.__d1Candidate && window.__d1Candidate.phase() === 'ready'",
            what="H2 候选就绪",
            timeout=30,
        )
        driver.eval("window.__d1Candidate.requestPreview()")
        driver.wait_until("Boolean(window.__d1Candidate.preview())", what="H2 采用预览", timeout=30)
        driver.eval("window.__d1Candidate.adopt()")
        driver.wait_until(
            "Boolean(window.__d1Candidate.resultText())", what="H2 采用完成", timeout=60
        )
        driver.wait_until(
            "window.__d1Editor.phase() === 'ready' && window.__d1Editor.dirty() === false",
            what="H2 采用后编辑器就绪",
            timeout=30,
        )
        status, plan = http("GET", f"/api/daily-plans/{plan_id}")
        assert status == 200 and isinstance(plan, dict), "plan read failed"
        content = plan.get("content") or {}
        baseline = content.get("split_baseline") or {}
        assert baseline.get("group_activity_process") == H2_BASELINE_PROCESS, (
            f"unexpected baseline: {baseline!r}"
        )
        baseline_version = plan.get("current_content_version")
        summary["h2_baseline_version"] = baseline_version
        summary["h2_baseline_process"] = baseline.get("group_activity_process")

    step("h2_baseline_adopted", create_baseline)

    history_version = None

    def save_history_version():
        nonlocal history_version
        before = driver.eval("window.__d1Editor.version()")
        driver.eval(
            "window.__d1Editor.setSplitProcess("
            + json.dumps(H2_HISTORY_PROCESS, ensure_ascii=False)
            + ")"
        )
        driver.eval(
            "window.__d1Editor.setText("
            + json.dumps("H2 历史原文\n第二行", ensure_ascii=False)
            + ", "
            + json.dumps("H2 历史反思", ensure_ascii=False)
            + ")"
        )
        driver.wait_until("window.__d1Editor.dirty() === true", what="H2 历史版变脏", timeout=15)
        driver.eval("window.__d1Editor.save()")
        driver.wait_until(
            f"window.__d1Editor.phase() === 'ready' && window.__d1Editor.version() === {before + 1}",
            what="H2 历史版保存",
            timeout=30,
        )
        history_version = driver.eval("window.__d1Editor.version()")
        summary["h2_history_version"] = history_version
        assert driver.eval("window.__d1Editor.groups().length") >= 1, "historical groups missing"

    step("h2_history_version_saved", save_history_version)

    current_version = None

    def save_current_version():
        nonlocal current_version
        before = driver.eval("window.__d1Editor.version()")
        # A new current-version group set (new server identities) replaces the
        # historical groups; this keeps the three delete controls present for
        # the delayed-GET DOM check while the old v4 group identities are absent.
        driver.eval("window.__d1Editor.fillAll('当前v5')")
        driver.eval(
            "window.__d1Editor.setSplitProcess("
            + json.dumps(H2_CURRENT_PROCESS, ensure_ascii=False)
            + ")"
        )
        driver.eval(
            "window.__d1Editor.setText("
            + json.dumps("H2 当前原文", ensure_ascii=False)
            + ", "
            + json.dumps("H2 当前反思", ensure_ascii=False)
            + ")"
        )
        driver.wait_until("window.__d1Editor.dirty() === true", what="H2 当前版变脏", timeout=15)
        driver.eval("window.__d1Editor.save()")
        driver.wait_until(
            f"window.__d1Editor.phase() === 'ready' && window.__d1Editor.version() === {before + 1}",
            what="H2 当前版保存",
            timeout=30,
        )
        current_version = driver.eval("window.__d1Editor.version()")
        summary["h2_current_version"] = current_version
        groups = driver.eval("window.__d1Editor.groups()")
        assert groups and "当前v5" in (groups[0].get("game_name") or ""), (
            f"current version groups missing: {groups!r}"
        )
        summary["h2_current_groups"] = groups

    step("h2_current_version_saved", save_current_version)

    def open_history_list():
        driver.eval("window.__d1Editor.openHistory()")
        driver.wait_until(
            "Boolean(window.__d1History && window.__d1History.phase() === 'ready')",
            what="H2 历史列表",
            timeout=30,
        )
        items = driver.eval("window.__d1History.items()")
        versions = [item.get("version") for item in items]
        summary["h2_history_versions"] = versions
        assert current_version in versions, f"current version missing: {versions}"
        assert history_version in versions, f"historical version missing: {versions}"
        assert driver.eval("window.__d1History.currentVersion()") == current_version
        _screenshot(args, summary, "h2-history-list")

    step("h2_history_list_opened", open_history_list)

    def baseline_warning_visible():
        # The first version has no split baseline while the current one does;
        # the expandable region must show the real stored processes, not just
        # a warning string.
        driver.eval("window.__d1History.selectVersion(1)")
        driver.wait_until(
            "window.__d1History.selectedVersion() === 1"
            " && Boolean(window.__d1History.detail())",
            what="H2 无基准历史详情",
            timeout=30,
        )
        driver.wait_until(
            "Boolean(window.__d1History.baselineCompare())",
            what="H2 基准比较对象",
            timeout=30,
        )
        comparison = driver.eval("window.__d1History.baselineCompare()")
        summary["h2_baseline_compare"] = comparison
        assert comparison.get("changed") is True
        assert comparison.get("current", {}).get("present") is True
        assert comparison.get("current", {}).get("process") == H2_BASELINE_PROCESS
        assert comparison.get("historical", {}).get("present") is False
        assert comparison.get("historical", {}).get("display") == "无基准"
        detail_baseline = driver.eval("window.__d1History.detailBaseline()")
        summary["h2_detail_baseline"] = detail_baseline
        assert detail_baseline.get("present") is False
        assert detail_baseline.get("display") == "无基准"
        driver.eval(
            "(document.querySelector('[data-d1=\"history-baseline-warning\"] "
            ".el-collapse-item__header')||{click:function(){}}).click()"
        )
        driver.eval(
            "(document.querySelector('[data-d1=\"history-baseline-warning\"]')"
            "||{scrollIntoView:function(){}}).scrollIntoView({block:'start'})"
        )
        time.sleep(0.4)
        _screenshot(args, summary, "h2-history-baseline-warning")

    step("h2_baseline_warning_visible", baseline_warning_visible)

    def compare_historical_version():
        driver.eval(f"window.__d1History.selectVersion({history_version})")
        driver.wait_until(
            f"window.__d1History.selectedVersion() === {history_version}"
            " && Boolean(window.__d1History.preview())",
            what="H2 历史比较",
            timeout=30,
        )
        assert driver.eval("window.__d1History.canRestore()") is True
        changed = driver.eval("window.__d1History.changedCount()")
        summary["h2_changed_count"] = changed
        assert changed > 0, "history comparison has no changed fields"
        sections = driver.eval("window.__d1History.fullSections()")
        serialized = json.dumps(sections, ensure_ascii=False)
        assert "历史v1" in serialized, "historical group content missing from full view"
        assert "group_id" not in serialized and "game_id" not in serialized
        driver.eval(
            "(document.querySelector('[data-d1=\"history-compare-head\"]')"
            "||{scrollIntoView:function(){}}).scrollIntoView({block:'start'})"
        )
        time.sleep(0.4)
        _screenshot(args, summary, "h2-history-compare")

    step("h2_history_compared", compare_historical_version)

    restored_version = None

    def _confirm_and_restore_body():
        nonlocal restored_version
        driver.eval("window.__d1History.requestRestore()")
        driver.wait_until(
            "window.__d1History.confirmOpen() === true", what="H2 恢复确认", timeout=15
        )
        driver.eval(
            "(document.querySelector('[data-d1=\"history-confirm\"]')"
            "||{scrollIntoView:function(){}}).scrollIntoView({block:'start'})"
        )
        time.sleep(0.4)
        _screenshot(args, summary, "h2-history-confirm")
        # Delay only the parent's post-restore GET. This is a verification
        # injection at the page fetch boundary, so the real window can prove
        # that the whole settle window (not just the POST) blocks form edits.
        driver.eval(H2_DELAYED_GET_INSTALL_JS)
        driver.eval("window.__d1History.confirmRestore()")
        driver.wait_until(
            "window.__h2DelayedGetStarted === true", what="H2 恢复后 GET 已挂起", timeout=30
        )
        assert driver.eval("window.__d1Editor.historyBusy()") is True
        assert driver.eval("window.__d1Editor.editDisabled()") is True
        controls = driver.eval(
            "Array.from(document.querySelectorAll('[data-d1=\"editor\"] .el-card textarea,"
            " [data-d1=\"editor\"] .el-card input'))"
            ".map(function(el){return {tag: el.tagName, disabled: el.disabled,"
            " type: el.type, readonly: el.readOnly, placeholder: el.placeholder,"
            " cls: el.className, outer: el.outerHTML.slice(0, 180)};})"
        )
        assert controls, "no form controls found during the delayed GET"
        summary["h2_restore_delayed_controls"] = controls
        editable_controls = [item for item in controls if not item.get("readonly")]
        assert editable_controls, "no editable form controls found during the delayed GET"
        assert all(item.get("disabled") is True for item in editable_controls), controls
        delete_buttons = driver.eval(
            "Array.from(document.querySelectorAll("
            "'[data-d1=\"delete-morning-game\"],"
            "[data-d1=\"delete-post-game\"],"
            "[data-d1=\"delete-afternoon-game\"]'))"
            ".map(function(el){return el.disabled;})"
        )
        assert len(delete_buttons) >= 3, f"three game delete buttons missing: {delete_buttons!r}"
        assert all(delete_buttons), delete_buttons
        before_structure = driver.eval("window.__d1Editor.structureCounts()")
        driver.eval(
            "Array.from(document.querySelectorAll("
            "'[data-d1=\"delete-morning-game\"],"
            "[data-d1=\"delete-post-game\"],"
            "[data-d1=\"delete-afternoon-game\"]')).forEach(function(el){el.click();})"
        )
        assert driver.eval("window.__d1Editor.structureCounts()") == before_structure
        summary["h2_restore_delayed_get"] = {
            "controls": len(controls),
            "delete_buttons": len(delete_buttons),
            "structure": before_structure,
        }
        driver.eval("window.__h2ReleaseGet()")
        driver.wait_until(
            f"window.__d1Editor.phase() === 'ready'"
            f" && window.__d1Editor.version() === {current_version + 1}"
            " && window.__d1Editor.dirty() === false"
            " && window.__d1Editor.editDisabled() === false",
            what="H2 恢复完成",
            timeout=60,
        )
        _cleanup_h2_fetch(driver, summary)
        assert driver.eval("window.__h2ReleaseCalled === true") is True
        assert driver.eval("window.fetch === window.__h2RealFetch") is True
        summary["h2_restore_fetch_cleanup"] = {
            "release_called": True,
            "fetch_restored": True,
        }
        restored_version = driver.eval("window.__d1Editor.version()")
        summary["h2_restored_version"] = restored_version
        groups = driver.eval("window.__d1Editor.groups()")
        summary["h2_restored_groups"] = groups
        assert groups and groups[0].get("group_id"), f"restored group identity missing: {groups!r}"
        assert "历史v1" in (groups[0].get("game_name") or ""), (
            f"restored historical game missing: {groups!r}"
        )
        assert driver.eval("window.__d1Editor.raw()") == "H2 历史原文\n第二行"

    def confirm_and_restore():
        try:
            _confirm_and_restore_body()
        finally:
            # A failed DOM assertion must still release the synthetic delayed
            # GET and restore the real fetch; the original exception remains.
            _cleanup_h2_fetch(driver, summary)

    step("h2_restored", confirm_and_restore)

    def verify_restored_history_source():
        driver.eval("window.__d1Editor.openHistory()")
        driver.wait_until(
            "Boolean(window.__d1History && window.__d1History.phase() === 'ready')",
            what="H2 恢复后历史列表",
            timeout=30,
        )
        items = driver.eval("window.__d1History.items()")
        current = next(
            (item for item in items if item.get("version") == restored_version), None
        )
        assert current is not None, f"restored version missing: {items!r}"
        assert current.get("is_current") is True
        assert current.get("restored_from_version") == history_version
        summary["h2_restored_source"] = current.get("restored_from_version")
        driver.eval(f"window.__d1History.selectVersion({restored_version})")
        driver.wait_until(
            f"window.__d1History.selectedVersion() === {restored_version}"
            " && Boolean(window.__d1History.detail())",
            what="H2 恢复后当前版本详情",
            timeout=30,
        )
        assert driver.eval("window.__d1History.canRestore()") is False
        _screenshot(args, summary, "h2-history-restored")
        driver.eval("window.__d1History.requestClose()")

    step("h2_restored_history_source", verify_restored_history_source)


def drive_d3_h2_verify(driver, args, summary, checks, host_api, port) -> None:
    """Cold-restart readback after the H2 restore, plus a real DOCX export."""
    token = getattr(host_api, "_launch_token", "")
    if not token:
        raise RuntimeError("d3-h2-verify: host token missing")

    def step(name, fn):
        _h2_step(summary, checks, name, fn, error_key="h2_verify_errors")

    driver.wait_until(
        "Boolean(window.__d1App && window.__d1App.ready())", what="H2 冷重启页面", timeout=40
    )
    driver.wait_until(
        "Boolean(window.__d1Workbench && typeof window.__d1Workbench.openDate === 'function')",
        what="H2 冷重启工作台",
        timeout=30,
    )
    driver.eval(f"window.__d1Workbench.openDate({json.dumps(args.date)})")
    driver.wait_until(
        "window.__d1App.view() === 'editor' && window.__d1Editor"
        " && window.__d1Editor.phase() === 'ready'",
        what="H2 冷重启编辑器",
        timeout=30,
    )

    def content_readback():
        version = driver.eval("window.__d1Editor.version()")
        summary["h2_restart_version"] = version
        assert args.expect_version is None or version == args.expect_version, (
            f"version after restart {version} != {args.expect_version}"
        )
        raw = driver.eval("window.__d1Editor.raw()")
        summary["h2_restart_raw"] = raw
        assert raw == "H2 历史原文\n第二行", f"raw after restart: {raw!r}"
        groups = driver.eval("window.__d1Editor.groups()")
        summary["h2_restart_groups"] = groups
        assert groups and groups[0].get("group_id"), "group identity lost after restart"
        assert "历史v1" in (groups[0].get("game_name") or ""), "historical game lost after restart"

    step("h2_cold_restart_content", content_readback)

    def history_readback():
        driver.eval("window.__d1Editor.openHistory()")
        driver.wait_until(
            "Boolean(window.__d1History && window.__d1History.phase() === 'ready')",
            what="H2 冷重启历史",
            timeout=30,
        )
        items = driver.eval("window.__d1History.items()")
        summary["h2_restart_history_versions"] = [item.get("version") for item in items]
        current = next(
            (item for item in items if item.get("version") == args.expect_version), None
        )
        assert current is not None and current.get("is_current") is True
        assert current.get("restored_from_version") is not None
        summary["h2_restart_source"] = current.get("restored_from_version")
        _screenshot(args, summary, "h2-history-cold-restart")
        driver.eval("window.__d1History.requestClose()")

    step("h2_cold_restart_history", history_readback)

    def word_export():
        if not args.word_out:
            raise RuntimeError("--word-out is required for d3-h2-verify")
        status, payload, headers = _http_bytes(
            port,
            token,
            "POST",
            "/api/exports/daily-plans",
            {"from": args.date, "to": args.date},
        )
        summary["h2_word_status"] = status
        if status == 409:
            try:
                error = json.loads(payload.decode("utf-8"))
            except Exception:  # noqa: BLE001
                error = {}
            details = (error.get("error") or {}).get("details") or {}
            if (error.get("error") or {}).get("code") == "EXPORT_ACK_REQUIRED":
                # The synthetic fixture intentionally leaves some optional
                # sections empty. Export the same pinned snapshot after the
                # explicit missing-facts acknowledgement; this is the real
                # production confirmation path, not a bypass.
                summary["h2_word_ack_reason"] = details.get("reason")
                status, payload, headers = _http_bytes(
                    port,
                    token,
                    "POST",
                    "/api/exports/daily-plans",
                    {
                        "from": args.date,
                        "to": args.date,
                        "ack_missing": True,
                        "expected_context": details.get("expected_context"),
                    },
                )
                summary["h2_word_status_after_ack"] = status
        summary["h2_word_status"] = status
        summary["h2_word_bytes"] = len(payload)
        summary["h2_word_content_type"] = headers.get("Content-Type")
        assert status == 200, f"Word export failed: {status} {payload[:500]!r}"
        assert payload[:2] == b"PK", "Word export is not a DOCX zip"
        Path(args.word_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.word_out).write_bytes(payload)

    step("h2_word_export", word_export)


def _click_d1(driver, selector: str) -> bool:
    return bool(
        driver.eval(
            "(function(){const e=document.querySelector("
            + json.dumps(selector)
            + "); if(!e) return false; e.click(); return true;})()"
        )
    )


def drive_u3_update(driver, args, summary, checks, host_api, port) -> None:
    """Actual Vue/WebView2 old window → UI download → confirm → close."""
    driver.wait_until(
        "Boolean(window.__d1App && window.__d1App.ready())",
        what="U3 页面启动",
        timeout=60,
    )
    summary["u3_initial_page_update_state"] = driver.eval(
        "JSON.stringify(window.__d1App.updateState())"
    )
    if getattr(host_api, "_update_manager", None) is not None:
        summary["u3_initial_host_update_state"] = host_api._update_manager.state()
    driver.wait_until(
        "Boolean(window.__d1App.updateState() && "
        "window.__d1App.updateState().state === 'available')",
        what="U3 启动检查发现新版",
        timeout=120,
    )
    checks["u3_startup_update_available"] = True
    driver.wait_until(
        "Boolean(window.__d1App.updateOpen())",
        what="U3 更新面板自动打开",
        timeout=30,
    )
    _screenshot(args, summary, "u3-update-available")

    assert _click_d1(driver, '[data-d1="update-download"]'), "download button missing"
    summary["u3_state_after_download_click"] = driver.eval(
        "JSON.stringify(window.__d1App.updateState())"
    )
    progress_observed = False
    deadline = time.monotonic() + 60
    last_state = None
    while time.monotonic() < deadline:
        last_state = driver.eval("JSON.stringify(window.__d1App.updateState())")
        try:
            parsed = json.loads(last_state) if isinstance(last_state, str) else last_state
        except (TypeError, ValueError):
            parsed = {}
        if (
            parsed.get("state") == "downloading"
            and (parsed.get("progress") or {}).get("downloaded", 0) > 0
        ):
            progress_observed = True
            break
        if parsed.get("state") in ("failed", "ready", "cancelled"):
            break
        time.sleep(0.05)
    summary["u3_progress_last_state"] = last_state
    assert progress_observed, f"U3 download progress not observed: {last_state}"
    checks["u3_ui_download_progress"] = True
    _screenshot(args, summary, "u3-update-downloading")
    assert _click_d1(driver, '[data-d1="update-cancel"]'), "cancel button missing"
    driver.wait_until(
        "window.__d1App.updateState().state === 'cancelled'",
        what="U3 下载取消",
        timeout=30,
    )
    checks["u3_ui_cancel_keeps_old_app"] = bool(
        driver.eval("window.__d1App.state() === 'ready'")
    )
    _screenshot(args, summary, "u3-update-cancelled")

    assert _click_d1(driver, '[data-d1="update-retry"]'), "retry button missing"
    driver.wait_until(
        "window.__d1App.updateState().state === 'available'",
        what="U3 重试检查",
        timeout=90,
    )
    assert _click_d1(driver, '[data-d1="update-download"]'), "second download missing"
    driver.wait_until(
        "window.__d1App.updateState().state === 'ready'",
        what="U3 下载校验完成",
        timeout=120,
    )
    checks["u3_ui_package_ready"] = True
    driver.wait_until(
        "Boolean(document.querySelector('[data-d1=\"update-install\"]'))",
        what="U3 安装按钮",
        timeout=30,
    )
    _screenshot(args, summary, "u3-update-ready")

    driver.eval(f"window.__d1Workbench.openDate({json.dumps(args.date)})")
    driver.wait_until(
        "window.__d1App.view() === 'editor' && window.__d1Editor"
        " && window.__d1Editor.phase() === 'ready'",
        what="U3 更新前编辑器",
        timeout=30,
    )
    current = driver.eval("window.__d1Editor.raw()") or ""
    driver.eval(
        "window.__d1Editor.setText("
        + json.dumps(current + "\nU3 关闭前保存输入", ensure_ascii=False)
        + ", "
        + json.dumps("U3 关闭前反思", ensure_ascii=False)
        + ")"
    )
    driver.wait_until(
        "window.__d1Editor.dirty() === true",
        what="U3 更新前未保存输入",
        timeout=15,
    )
    checks["u3_dirty_before_install"] = True
    _screenshot(args, summary, "u3-update-dirty")

    if getattr(args, "u3_close_cancel", False):
        # First real close attempt: make only the daily-plan PATCH fail, so the
        # existing editor-save/close handshake cancels.  This is page fetch
        # injection, not a direct host install call.
        driver.eval(
            "(() => {"
            " window.__u3RealFetch = window.fetch.bind(window);"
            " window.__u3FailSave = true;"
            " window.fetch = function(input, init) {"
            "   const method = ((init || {}).method || 'GET').toUpperCase();"
            "   const url = String(input);"
            "   if (window.__u3FailSave && method === 'PATCH'"
            "       && url.indexOf('/api/daily-plans/') >= 0) {"
            "     return Promise.resolve(new Response("
            "       JSON.stringify({detail: 'synthetic close save failure'}),"
            "       {status: 500, headers: {'Content-Type': 'application/json'}}));"
            "   }"
            "   return window.__u3RealFetch(input, init);"
            " }; return true; })()"
        )
        assert _click_d1(driver, '[data-d1="update-install"]'), "install button missing"
        driver.wait_until(
            "Boolean(document.querySelector('[data-d1=\"update-install-confirm\"]'))",
            what="U3 取消安装确认对话框",
            timeout=15,
        )
        assert _click_d1(driver, '[data-d1="update-install-confirm-button"]'), (
            "cancel-install confirmation button missing"
        )
        import update_install

        coordinator = getattr(host_api, "_install_coordinator", None)
        deadline = time.monotonic() + 90
        revoked = None
        while time.monotonic() < deadline:
            if coordinator is not None and coordinator._plan is not None:
                revoked = update_install.read_result(coordinator._plan)
                if revoked is not None and revoked.get("status") == "revoked":
                    break
            time.sleep(0.05)
        config_path = Path(args.u3_config)
        config = json.loads(config_path.read_text(encoding="utf-8"))
        old_marker = Path(config["app_dir"]) / "old-marker.txt"
        page_state = driver.eval(
            "JSON.stringify({requested: window.__d1App.installRequested(),"
            " locked: window.__d1App.closeState().locked,"
            " dirty: window.__d1Editor.dirty()})"
        )
        summary["u3_cancel_page_state"] = page_state
        summary["u3_cancel_install_result"] = revoked
        page_info = json.loads(page_state) if isinstance(page_state, str) else {}
        checks["u3_close_cancel_revoked"] = bool(
            revoked is not None and revoked.get("status") == "revoked"
        )
        checks["u3_close_cancel_page_kept"] = bool(
            page_info.get("requested") is False
            and page_info.get("locked") is False
            and page_info.get("dirty") is True
        )
        checks["u3_close_cancel_old_program_intact"] = old_marker.is_file()
        _screenshot(args, summary, "u3-close-cancelled")
        driver.eval(
            "(() => { window.__u3FailSave = false;"
            " if (window.__u3RealFetch) window.fetch = window.__u3RealFetch;"
            " window.__d1App.openUpdate();"
            " void window.__d1App.refreshUpdate(); return true; })()"
        )
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            try:
                state_text = driver.eval(
                    "JSON.stringify(window.__d1App.updateState())"
                )
            except Exception:
                state_text = ""
            summary["u3_after_cancel_update_state"] = state_text
            if driver.eval(
                "Boolean(document.querySelector('[data-d1=\"update-install\"]'))"
            ):
                break
            try:
                driver.eval("window.__d1App.openUpdate();")
            except Exception:
                pass
            time.sleep(0.1)
        assert driver.eval(
            "Boolean(document.querySelector('[data-d1=\"update-install\"]'))"
        ), "install button did not return after canceled close"

    assert _click_d1(driver, '[data-d1="update-install"]'), "install button missing"
    driver.wait_until(
        "Boolean(document.querySelector('[data-d1=\"update-install-confirm\"]'))",
        what="U3 安装确认对话框",
        timeout=15,
    )
    assert _click_d1(driver, '[data-d1="update-install-confirm-button"]'), (
        "install confirmation button missing"
    )
    checks["u3_ui_install_confirmed"] = True
    # Once the host consumes the one-shot allow it destroys the window.  Do
    # not keep calling evaluate_js while WebView2 is tearing down; observe the
    # host close coordinator instead.  A save/draft failure leaves it
    # pending/canceled and this wait fails.
    coordinator = getattr(host_api, "_close_coordinator", None)
    deadline = time.monotonic() + 90
    close_allowed = False
    while time.monotonic() < deadline:
        if coordinator is not None and getattr(coordinator, "_state", None) == "closing":
            close_allowed = True
            break
        time.sleep(0.05)
    checks["u3_close_handshake_allowed"] = close_allowed
    assert close_allowed, "U3 close handshake did not finish"


def drive_u3_verify(driver, args, summary, checks, host_api, port) -> None:
    """Actual new source window: page_ready and target identity are live."""
    driver.wait_until(
        "Boolean(window.__d1App && window.__d1App.ready())",
        what="U3 新版页面就绪",
        timeout=60,
    )
    checks["u3_new_page_ready"] = True
    # The host identity is recorded after the real page/bridge handshake.
    summary["u3_verify_identity"] = host_api.get_app_identity()
    summary["u3_verify_pid"] = os.getpid()
    stop = Path(args.u3_verify_stop) if args.u3_verify_stop else None
    if stop is not None:
        stop.parent.mkdir(parents=True, exist_ok=True)
    if args.word_out:
        token = getattr(host_api, "_launch_token", "")
        status, payload, headers = _http_bytes(
            port,
            token,
            "POST",
            "/api/exports/daily-plans",
            {"from": args.date, "to": args.date},
        )
        summary["u3_word_status"] = status
        if status == 409:
            try:
                error = json.loads(payload.decode("utf-8"))
            except Exception:  # noqa: BLE001
                error = {}
            details = (error.get("error") or {}).get("details") or {}
            if (error.get("error") or {}).get("code") == "EXPORT_ACK_REQUIRED":
                summary["u3_word_ack_reason"] = details.get("reason")
                status, payload, headers = _http_bytes(
                    port,
                    token,
                    "POST",
                    "/api/exports/daily-plans",
                    {
                        "from": args.date,
                        "to": args.date,
                        "ack_missing": True,
                        "expected_context": details.get("expected_context"),
                    },
                )
                summary["u3_word_status_after_ack"] = status
        summary["u3_word_status"] = status
        summary["u3_word_bytes"] = len(payload)
        summary["u3_word_content_type"] = headers.get("Content-Type")
        assert status == 200 and payload[:2] == b"PK", (
            f"U3 Word export failed: {status} {payload[:200]!r}"
        )
        Path(args.word_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.word_out).write_bytes(payload)
        checks["u3_new_word_export"] = True
    _screenshot(args, summary, "u3-new-page-ready")
    deadline = time.monotonic() + 120
    while stop is not None and time.monotonic() < deadline and not stop.exists():
        time.sleep(0.05)
    checks["u3_external_stop_seen"] = stop is None or stop.exists()


def drive_selftest(window, host_api, args, summary: dict, port: int | None = None) -> None:
    driver = JsDriver(window)
    checks = summary.setdefault("checks", {})
    if args.phase == "w5-ui":
        # Dedicated D2 W5 real-window flow; it owns its own setup / tail and
        # never runs the D1 leave flow.
        drive_w5_ui(driver, args, summary, checks, host_api, port)
        return
    if args.phase == "w6-ui":
        drive_w6_ui(driver, args, summary, checks, host_api, port)
        return
    if args.phase == "w6-ui-verify":
        drive_w6_ui_verify(driver, args, summary, checks, host_api, port)
        return
    if args.phase == "g15-noexec":
        drive_g15_noexec(driver, args, summary, checks, host_api, port)
        return
    if args.phase == "d3-h2-ui":
        drive_d3_h2_ui(driver, args, summary, checks, host_api, port)
        return
    if args.phase == "d3-h2-verify":
        drive_d3_h2_verify(driver, args, summary, checks, host_api, port)
        return
    if args.phase == "u3-update":
        drive_u3_update(driver, args, summary, checks, host_api, port)
        return
    if args.phase == "u3-verify":
        drive_u3_verify(driver, args, summary, checks, host_api, port)
        return
    if port is not None:
        summary["http_probe"] = probe_http(port)
    try:
        summary["page_loaded_event"] = bool(
            getattr(window, "events", None)
            and window.events.loaded.is_set()
        )
    except Exception:  # noqa: BLE001
        summary["page_loaded_event"] = None

    def run_export(label: str, mode: str, custom: tuple[str, str] | None = None) -> None:
        if custom:
            driver.eval(
                "window.__d1Export.setCustom("
                + json.dumps(custom[0])
                + ", "
                + json.dumps(custom[1])
                + ")"
            )
        else:
            driver.eval(f"window.__d1Export.setMode({json.dumps(mode)})")
        before = driver.eval("window.__d1Export.seq()")
        driver.eval("window.__d1Export.runConfirmed()")
        terminal = (
            "['saved','canceled','save_failed','generation_failed',"
            "'export_not_found','save_result_unknown'].includes("
            "window.__d1Export.phase())"
        )
        driver.wait_until(
            f"window.__d1Export.seq() > {before} && {terminal}",
            what=f"导出（{label}）",
            timeout=120,
        )
        phase = driver.eval("window.__d1Export.phase()")
        filename = driver.eval("window.__d1Export.savedFilename()")
        summary.setdefault("samples", {})[label] = {
            "phase": phase,
            "filename": filename,
        }
        checks[f"export_{label}"] = phase == "saved"
        driver.wait_until(
            "window.__d1Editor.phase() === 'ready'",
            what="导出后编辑器仍就绪",
            timeout=30,
        )

    def save_text(raw: str, reflection: str) -> int:
        driver.eval(
            "window.__d1Editor.setText("
            + json.dumps(raw, ensure_ascii=False)
            + ", "
            + json.dumps(reflection, ensure_ascii=False)
            + ")"
        )
        driver.eval("window.__d1Editor.save()")
        driver.wait_until(
            "window.__d1Editor.phase() === 'ready' && window.__d1Editor.dirty() === false",
            what="保存完成",
            timeout=60,
        )
        return driver.eval("window.__d1Editor.version()")

    try:
        driver.wait_until(
            "Boolean(window.__d1App && window.__d1App.ready())",
            what="页面启动",
            timeout=30,
        )
        state = driver.eval("window.__d1App.state()")
        summary["app_state_initial"] = state
        if state == "error":
            raise RuntimeError(
                "页面启动失败：" + str(driver.eval("window.__d1App.error()"))
            )
        if state == "uninitialized":
            driver.eval(
                "window.__d1Setup.fill("
                + json.dumps(
                    {
                        "display_name": "验证教师",
                        "class_name": "验证中一班",
                        "grade": "middle",
                        "term_name": "验证学期",
                        "start_date": args.term_start,
                        "end_date": args.term_end,
                        "school_name": args.init_school,
                    },
                    ensure_ascii=False,
                )
                + ")"
            )
            driver.eval("window.__d1Setup.submit()")
            driver.wait_until(
                "window.__d1App.state() === 'ready'",
                what="初始化完成",
                timeout=60,
            )
        checks["initialized"] = True

        driver.wait_until(
            "Boolean(window.__d1Workbench && typeof window.__d1Workbench.openDate === 'function')",
            what="工作台就绪",
            timeout=30,
        )
        driver.eval(
            f"window.__d1Workbench.openDate({json.dumps(args.date)})"
        )
        driver.wait_until(
            "window.__d1App.view() === 'editor'", what="进入编辑器", timeout=30
        )
        driver.wait_until(
            "window.__d1Editor && ['ready','create_confirmation'].includes(window.__d1Editor.phase())",
            what="编辑器就绪",
            timeout=30,
        )
        phase = driver.eval("window.__d1Editor.phase()")
        if phase == "create_confirmation":
            driver.eval("window.__d1Editor.confirmCreate()")
            driver.wait_until(
                "window.__d1Editor.phase() === 'ready'",
                what="创建日计划",
                timeout=30,
            )

        if args.phase == "first":
            # 空内容样本：尚未输入任何内容时按“所在周”导出单份计划（与其他
            # 样本文件名区分，避免保存目录内互相覆盖）。
            run_export("empty-week-range", "week")
            version = save_text(
                f"代表内容 {args.session_tag}", f"{args.session_tag} 代表性反思"
            )
            checks["saved_first"] = version is not None
            run_export("representative-single-day", "day")
            summary["version_after_first"] = version
            summary["raw_after_first"] = driver.eval("window.__d1Editor.raw()")
        elif args.phase == "restart":
            # 读回第一次写入并继续修改（长内容）。
            current_raw = driver.eval("window.__d1Editor.raw()") or ""
            current_reflection_version = driver.eval("window.__d1Editor.version()")
            checks["restart_read_old_content"] = args.expect_raw is None or current_raw == args.expect_raw
            long_text = ("长内容重复段落。" * 200)
            version = save_text(
                current_raw + "\n" + f"重启续写 {args.session_tag}",
                f"{args.session_tag} 长内容反思：{long_text}",
            )
            checks["restart_saved_again"] = version == current_reflection_version + 1
            summary["version_after_restart"] = version
            summary["raw_after_restart"] = driver.eval("window.__d1Editor.raw()")
            # 第二个日期：创建并写入较短内容，用于多份导出样本。
            driver.eval("window.__d1Editor.leaveToCalendar()")
            driver.wait_until(
                "window.__d1App.view() === 'workbench'",
                what="返回工作台（第二日期）",
                timeout=30,
            )
            driver.wait_until(
                "Boolean(window.__d1Workbench && typeof window.__d1Workbench.openDate === 'function')",
                what="工作台就绪（第二日期）",
                timeout=30,
            )
            driver.eval(
                f"window.__d1Workbench.openDate({json.dumps(args.date2)})"
            )
            driver.wait_until(
                "window.__d1Editor && ['ready','create_confirmation'].includes(window.__d1Editor.phase())",
                what="第二日期编辑器",
                timeout=30,
            )
            if driver.eval("window.__d1Editor.phase()") == "create_confirmation":
                driver.eval("window.__d1Editor.confirmCreate()")
                driver.wait_until(
                    "window.__d1Editor.phase() === 'ready'",
                    what="创建第二日计划",
                    timeout=30,
                )
            save_text(f"第二日内容 {args.session_tag}", f"{args.session_tag} 第二日反思")
            run_export(
                "long-custom-range", "custom", custom=(args.date, args.date2)
            )
        elif args.phase == "verify":
            current_raw = driver.eval("window.__d1Editor.raw()") or ""
            version = driver.eval("window.__d1Editor.version()")
            if args.expect_raw is not None:
                checks["verify_raw_matches"] = current_raw == args.expect_raw
            if args.expect_version is not None:
                checks["verify_version_matches"] = version == args.expect_version
            run_export("verify-single-day", "day")
            summary["version_verified"] = version
            summary["raw_verified"] = current_raw
        elif args.phase == "word-r18":
            # R18 (spec §12.4): a real long 活动过程 written through a real DOM
            # input event, then real single-day and merged-range exports whose
            # output must carry the new title / signature / non-bold rules.
            # The range spans ``--date2`` (an existing earlier plan) to
            # ``--date`` (this phase's date) so one document mixes snapshots.
            expected_process = "长过程段落。" * 120
            set_result = driver.eval(
                "(() => {"
                " const label = Array.from(document.querySelectorAll('label'))"
                "   .find((el) => el.textContent.trim() === '过程');"
                " if (!label) return 'no-label';"
                " const field = label.closest('.field') || label.parentElement;"
                " const input = field && field.querySelector('textarea, input');"
                " if (!input) return 'no-input';"
                " input.value = "
                + json.dumps(expected_process, ensure_ascii=False)
                + ";"
                " input.dispatchEvent(new Event('input', { bubbles: true }));"
                " return 'ok';"
                " })()"
            )
            checks["r18_process_input"] = set_result == "ok"
            driver.wait_until(
                "window.__d1Editor.dirty() === true",
                what="R18 长过程进入表单",
                timeout=15,
            )
            version_before = driver.eval("window.__d1Editor.version()") or 0
            driver.eval("window.__d1Editor.save()")
            driver.wait_until(
                "window.__d1Editor.phase() === 'ready'"
                " && window.__d1Editor.dirty() === false",
                what="R18 长过程保存完成",
                timeout=60,
            )
            version_after = driver.eval("window.__d1Editor.version()")
            checks["r18_process_saved"] = version_after == version_before + 1
            summary["r18_process_version_before"] = version_before
            summary["r18_process_version_after"] = version_after
            summary["r18_process_length"] = len(expected_process)
            run_export("r18-long-process-single-day", "day")
            run_export(
                "r18-long-process-merged",
                "custom",
                custom=(args.date2, args.date),
            )
        elif args.phase == "fix-regression":
            checks["fix_editor_ready_initial"] = (
                driver.eval("window.__d1Editor.phase()") == "ready"
            )
            drive_fix_regression(
                driver, args, summary, checks, host_api, port, run_export
            )
        elif args.phase == "fix-regression2":
            # This phase ends by really closing the window (the close waits
            # for an in-flight native save): the generic leave tail must not
            # run afterwards.
            drive_fix_regression2(driver, args, summary, checks, host_api, port)
            return
        elif args.phase == "close-order":
            # R1 §13.3: the new close B arrives before A's delayed/lost abort;
            # R1 §15.3 lastack: A's final confirmation answer arrives after B
            # was confirmed. Both end by really closing the window.
            if args.close_order_request == "lastack":
                drive_close_lastack(driver, args, summary, checks, host_api)
            else:
                drive_close_order(driver, args, summary, checks, host_api, port)
            return
        elif args.phase == "late-input-close":
            # R17 §15.2: real form input during the final confirmation wait
            # must not be lost and the window must not close with it unsaved;
            # the retry close then saves it and really closes.
            drive_late_input_close(driver, args, summary, checks, host_api, port)
            return
        elif args.phase == "settings-draft-close":
            # R17 §16.3: a settings draft created during the final
            # confirmation wait must keep the page (never applied or lost);
            # after the explicit cancel the next close really closes.
            drive_settings_draft_close(driver, args, summary, checks, host_api, port)
            return
        elif args.phase == "save-dialog":
            # Real native Save As dialog flows (spec §13.2): Chinese name,
            # cancel, real file-in-use failure, release + new-id retry.
            drive_save_dialog(driver, args, summary, checks, host_api, port)
            return
        elif args.phase == "clean-ime-close":
            # The window is closed from outside the driver (finally) while an
            # IME composition is active; the close must save the final text.
            drive_clean_ime_close(driver, args, summary, checks)
            return
        else:  # dirty-close: leave the editor DIRTY and let the close save it
            current_raw = driver.eval("window.__d1Editor.raw()") or ""
            driver.eval(
                "window.__d1Editor.setText("
                + json.dumps(
                    current_raw + f"\n关闭自动保存 {args.session_tag}",
                    ensure_ascii=False,
                )
                + ", "
                + json.dumps(f"{args.session_tag} 关闭前未保存输入", ensure_ascii=False)
                + ")"
            )
            driver.wait_until(
                "window.__d1Editor.dirty() === true",
                what="未保存输入就绪",
                timeout=15,
            )
            checks["dirty_before_close"] = True
            summary["dirty_before_close"] = True
            summary["version_before_close"] = driver.eval(
                "window.__d1Editor.version()"
            )
            summary["ok"] = all(
                value is not False for value in checks.values()
            )
            # Skip the usual leave flow: the close handshake itself must save.
            return

        # Exercise the real leave-save path: switch back to the calendar.
        driver.eval("window.__d1Editor.leaveToCalendar()")
        driver.wait_until(
            "window.__d1App.view() === 'workbench'",
            what="返回工作台",
            timeout=30,
        )
        checks["leave_flow"] = True
        summary["ok"] = all(
            value is not False for value in checks.values()
        )
    except Exception as exc:
        summary["driver_error"] = str(exc)
        summary["ok"] = False


def drive_fix_regression(driver, args, summary, checks, host_api, port, run_export) -> None:
    """D1B fix regression through the real WebView2 window (R1-R14 slice).

    Covers: full-form round-trip, no-modify save, write-lock failure keeping
    input, 409 + explicit resubmit with dead group/game ids, multi-region
    settings drafts across apply, leave actions (calendar/settings/date) and
    a real export through the verification save directory.
    """
    import sqlite3

    token = host_api._launch_token

    def http(method: str, path: str, body: dict | None = None):
        return _http_json(port, token, method, path, body)

    def editor(script: str):
        return driver.eval(f"window.__d1Editor.{script}")

    tag = args.session_tag
    driver.wait_until(
        "window.__d1Editor.phase() === 'ready'", what="修复回归编辑器就绪", timeout=30
    )
    plan_id = editor("planId()")

    # 1) no-modify manual save: stays clean, no new version
    version_before = editor("version()")
    driver.eval("window.__d1Editor.save()")
    time.sleep(1.0)
    checks["fix_noop_save"] = (
        editor("version()") == version_before and editor("dirty()") is False
    )

    # 1b) clean-page IME boundary (R15): the plan is saved and clean, an IME
    # composition is active and the final text has not reached the model yet.
    # A manual save must wait for the composition instead of returning
    # "unchanged"; no new version appears until the final text is committed.
    driver.wait_until(
        "window.__d1Editor.dirty() === false", what="clean 状态（组合前）", timeout=15
    )
    version_clean_ime = editor("version()")
    driver.eval(
        """(() => {
          const list = [...document.querySelectorAll('textarea')];
          const el = list.find((t) => (t.placeholder || '').includes('原始教案'))
            || list[list.length - 1];
          if (!el) { throw new Error('no textarea found'); }
          window.__cleanImeElement = el;
          el.focus();
          el.dispatchEvent(new CompositionEvent('compositionstart', { bubbles: true }));
          const setter = Object.getOwnPropertyDescriptor(
            window.HTMLTextAreaElement.prototype, 'value').set;
          setter.call(el, '清洁组合中');
          el.dispatchEvent(new Event('input', { bubbles: true }));
          return true;
        })()"""
    )
    driver.wait_until(
        "window.__d1Editor.composing() === true", what="clean 组合开始", timeout=15
    )
    checks["fix_clean_ime_dirty_before_final"] = editor("dirty()") is False
    driver.eval("window.__d1Editor.save()")
    time.sleep(1.0)
    checks["fix_clean_ime_save_waits"] = (
        editor("version()") == version_clean_ime
        and editor("phase()") == "ready"
        and editor("dirty()") is False
    )
    driver.eval(
        """(() => {
          const el = window.__cleanImeElement;
          const setter = Object.getOwnPropertyDescriptor(
            window.HTMLTextAreaElement.prototype, 'value').set;
          setter.call(el, '清洁组合最终文本');
          el.dispatchEvent(new Event('input', { bubbles: true }));
          el.dispatchEvent(
            new CompositionEvent('compositionend', { bubbles: true, data: '最终文本' }));
          return true;
        })()"""
    )
    driver.wait_until(
        "window.__d1Editor.phase() === 'ready' && window.__d1Editor.dirty() === false",
        what="clean 组合保存完成",
        timeout=60,
    )
    status, detail = http("GET", f"/api/daily-plans/{plan_id}")
    checks["fix_clean_ime_final_text_saved"] = (
        (detail or {}).get("content", {}).get("raw_lesson_plan") == "清洁组合最终文本"
        and (detail or {}).get("current_content_version") == version_clean_ime + 1
    )
    version_clean_manual = editor("version()")

    # 1c) clean-page IME + leave: switching the date must wait for the final
    # composed text, save it, and only then run the navigation. The final
    # text is verified in the database; while the composition is active the
    # page stays on the original date (no early "clean" leave).
    driver.wait_until(
        "window.__d1Editor.dirty() === false", what="clean 状态（离开组合前）", timeout=15
    )
    driver.eval(
        """(() => {
          const list = [...document.querySelectorAll('textarea')];
          const el = list.find((t) => (t.placeholder || '').includes('原始教案'))
            || list[list.length - 1];
          if (!el) { throw new Error('no textarea found'); }
          window.__cleanLeaveImeElement = el;
          el.focus();
          el.dispatchEvent(new CompositionEvent('compositionstart', { bubbles: true }));
          const setter = Object.getOwnPropertyDescriptor(
            window.HTMLTextAreaElement.prototype, 'value').set;
          setter.call(el, '清洁离开组合中');
          el.dispatchEvent(new Event('input', { bubbles: true }));
          return true;
        })()"""
    )
    driver.wait_until(
        "window.__d1Editor.composing() === true", what="clean 离开组合开始", timeout=15
    )
    driver.eval(
        "window.__d1Editor.switchDate(" + json.dumps(args.date2) + ")"
    )
    time.sleep(0.8)
    checks["fix_clean_ime_leave_waits"] = (
        editor("planDate()") == args.date
        and editor("version()") == version_clean_manual
        and editor("dirty()") is False
    )
    driver.eval(
        """(() => {
          const el = window.__cleanLeaveImeElement;
          const setter = Object.getOwnPropertyDescriptor(
            window.HTMLTextAreaElement.prototype, 'value').set;
          setter.call(el, '清洁离开最终文本');
          el.dispatchEvent(new Event('input', { bubbles: true }));
          el.dispatchEvent(
            new CompositionEvent('compositionend', { bubbles: true, data: '离开最终文本' }));
          return true;
        })()"""
    )
    driver.wait_until(
        "window.__d1Editor && window.__d1Editor.planDate() === "
        + json.dumps(args.date2),
        what="clean 组合后完成切日期",
        timeout=60,
    )
    status, detail = http("GET", f"/api/daily-plans/{plan_id}")
    checks["fix_clean_ime_leave_saved"] = (
        (detail or {}).get("content", {}).get("raw_lesson_plan") == "清洁离开最终文本"
        and (detail or {}).get("current_content_version") == version_clean_manual + 1
    )
    # Back to the first date (the second date is not created here): the empty
    # second-date editor leaves cleanly, then the workbench reopens the plan.
    driver.wait_until(
        "['ready','create_confirmation'].includes(window.__d1Editor.phase())",
        what="第二日期编辑器就绪（clean-IME）",
        timeout=30,
    )
    driver.eval("window.__d1Editor.leaveToCalendar()")
    driver.wait_until(
        "window.__d1App.view() === 'workbench'", what="返回工作台（clean-IME 后）", timeout=30
    )
    driver.wait_until(
        "Boolean(window.__d1Workbench && typeof window.__d1Workbench.openDate === 'function')",
        what="工作台就绪（clean-IME 后）",
        timeout=30,
    )
    driver.eval(f"window.__d1Workbench.openDate({json.dumps(args.date)})")
    driver.wait_until(
        "window.__d1App.view() === 'editor'", what="回到原日期编辑器", timeout=30
    )
    driver.wait_until(
        "window.__d1Editor.phase() === 'ready'", what="原日期编辑器就绪", timeout=30
    )
    version_before = editor("version()")

    # 2) full form round-trip through the real API
    driver.eval(
        "window.__d1Editor.fillAll(" + json.dumps(tag, ensure_ascii=False) + ")"
    )
    driver.wait_until("window.__d1Editor.dirty() === true", what="全部表单输入", timeout=15)
    driver.eval("window.__d1Editor.save()")
    driver.wait_until(
        "window.__d1Editor.phase() === 'ready' && window.__d1Editor.dirty() === false",
        what="全部表单保存",
        timeout=60,
    )
    checks["fix_form_save_version"] = editor("version()") == version_before + 1
    status, detail = http("GET", f"/api/daily-plans/{plan_id}")
    checks["fix_form_read_status"] = status == 200
    adopted = (detail or {}).get("content", {}).get("adopted_content", {})
    checks["fix_form_roundtrip"] = (
        adopted.get("morning_games", [{}])[0].get("games", [{}])[0].get("name")
        == f"晨间游戏 {tag}"
        and adopted.get("morning_talk", {}).get("topic") == f"晨间谈话 {tag}"
        and adopted.get("group_activity", {}).get("process") == f"活动过程 {tag}"
        and adopted.get("post_group_games", [{}])[0].get("support_strategy")
        == f"支持策略 {tag}"
        and adopted.get("afternoon_outdoor", {}).get("observation_focus")
        == f"观察重点 {tag}"
        and adopted.get("reflection") == f"反思 {tag}"
        and (detail or {}).get("content", {}).get("raw_lesson_plan")
        == f"原始教案 {tag}"
    )
    groups = driver.eval_json("JSON.stringify(window.__d1Editor.groups())")
    old_group_id = groups[0]["group_id"] if groups else None
    old_game_id = groups[0]["game_id"] if groups else None
    checks["fix_server_ids_present"] = bool(old_group_id and old_game_id)

    # 2b) composition (IME) boundary: a save started mid-composition waits for
    # compositionend and captures the final composed text (not a stale value);
    # the in-flight save is never dropped and the final keystrokes are kept.
    driver.eval(
        "window.__d1Editor.setText("
        + json.dumps("组合前已有内容", ensure_ascii=False)
        + ", "
        + json.dumps("组合前反思", ensure_ascii=False)
        + ")"
    )
    driver.wait_until(
        "window.__d1Editor.dirty() === true", what="组合前已有输入", timeout=15
    )
    version_before_ime = editor("version()")
    summary["fix_ime_dom"] = driver.eval_json(
        "JSON.stringify({"
        "title: document.title,"
        "count: document.querySelectorAll('*').length,"
        "textareas: document.querySelectorAll('textarea').length,"
        "elinputs: document.querySelectorAll('.el-input').length"
        "})"
    )
    driver.eval(
        """(() => {
          const list = [...document.querySelectorAll('textarea')];
          const el = list.find((t) => (t.placeholder || '').includes('原始教案'))
            || list[list.length - 1];
          if (!el) { throw new Error('no textarea found'); }
          window.__imeElement = el;
          el.focus();
          el.dispatchEvent(new CompositionEvent('compositionstart', { bubbles: true }));
          const setter = Object.getOwnPropertyDescriptor(
            window.HTMLTextAreaElement.prototype, 'value').set;
          setter.call(el, '组合前已有内容组合中');
          el.dispatchEvent(new Event('input', { bubbles: true }));
          return true;
        })()"""
    )
    driver.eval("window.__d1Editor.save()")
    time.sleep(1.0)
    checks["fix_ime_save_waits"] = (
        editor("version()") == version_before_ime and editor("dirty()") is True
    )
    driver.eval(
        """(() => {
          const el = window.__imeElement;
          const setter = Object.getOwnPropertyDescriptor(
            window.HTMLTextAreaElement.prototype, 'value').set;
          setter.call(el, '组合前已有内容+组合末段');
          el.dispatchEvent(new Event('input', { bubbles: true }));
          el.dispatchEvent(
            new CompositionEvent('compositionend', { bubbles: true, data: '组合末段' }));
          return true;
        })()"""
    )
    driver.wait_until(
        "window.__d1Editor.phase() === 'ready' && window.__d1Editor.dirty() === false",
        what="组合结束后完成保存",
        timeout=60,
    )
    status, detail = http("GET", f"/api/daily-plans/{plan_id}")
    checks["fix_ime_final_text_saved"] = (
        (detail or {}).get("content", {}).get("raw_lesson_plan")
        == "组合前已有内容+组合末段"
        and (detail or {}).get("current_content_version") == version_before_ime + 1
    )

    # 3) write-lock failure keeps the input; the retry after release saves
    lock_connection = sqlite3.connect(summary["db_path"], timeout=30)
    lock_connection.execute("PRAGMA busy_timeout=200")
    lock_connection.execute("BEGIN IMMEDIATE")
    try:
        driver.eval(
            "window.__d1Editor.setText("
            + json.dumps(f"写锁失败内容 {tag}", ensure_ascii=False)
            + ", "
            + json.dumps(f"写锁失败反思 {tag}", ensure_ascii=False)
            + ")"
        )
        driver.wait_until(
            "window.__d1Editor.dirty() === true", what="写锁前输入", timeout=15
        )
        started = time.time()
        driver.eval("window.__d1Editor.save()")
        driver.wait_until(
            "window.__d1Editor.phase() === 'save_failed'",
            what="写锁失败留页",
            timeout=30,
        )
        elapsed = time.time() - started
        checks["fix_write_lock_stayed"] = editor("dirty()") is True
        checks["fix_write_lock_busy_wait"] = elapsed >= 3.0
        summary["fix_write_lock_elapsed"] = round(elapsed, 2)
        summary["fix_write_lock_error"] = editor("errorText()")
    finally:
        lock_connection.rollback()
        lock_connection.close()
    driver.eval("window.__d1Editor.save()")
    driver.wait_until(
        "window.__d1Editor.phase() === 'ready' && window.__d1Editor.dirty() === false",
        what="写锁释放后重试保存",
        timeout=60,
    )
    checks["fix_write_lock_retry_saved"] = True

    # 4) 409 + explicit resubmit with dead group/game ids
    status, detail = http("GET", f"/api/daily-plans/{plan_id}")
    current_version = (detail or {}).get("current_content_version")
    stripped = dict((detail or {}).get("content", {}).get("adopted_content", {}))
    stripped["morning_games"] = []
    status, patched = http(
        "PATCH",
        f"/api/daily-plans/{plan_id}",
        {"expected_content_version": current_version, "adopted_content": stripped},
    )
    checks["fix_external_conflict_patch"] = status == 200
    driver.eval(
        "window.__d1Editor.setText("
        + json.dumps(f"冲突后文字 {tag}", ensure_ascii=False)
        + ", "
        + json.dumps(f"冲突反思 {tag}", ensure_ascii=False)
        + ")"
    )
    driver.eval("window.__d1Editor.save()")
    driver.wait_until(
        "window.__d1Editor.phase() === 'conflict'", what="409 冲突留稿", timeout=30
    )
    checks["fix_conflict_kept_input"] = editor("dirty()") is True
    driver.eval("window.__d1Editor.resubmit()")
    driver.wait_until(
        "window.__d1Editor.phase() === 'ready' && window.__d1Editor.dirty() === false",
        what="显式重提",
        timeout=60,
    )
    groups_after = driver.eval_json("JSON.stringify(window.__d1Editor.groups())")
    checks["fix_resubmit_new_ids"] = bool(
        groups_after
        and groups_after[0]["group_id"] not in (None, old_group_id)
        and groups_after[0]["game_id"] not in (None, old_game_id)
    )
    status, detail = http("GET", f"/api/daily-plans/{plan_id}")
    checks["fix_resubmit_text_kept"] = (
        (detail or {}).get("content", {}).get("raw_lesson_plan")
        == f"冲突后文字 {tag}"
        and (detail or {})
        .get("content", {})
        .get("adopted_content", {})
        .get("reflection")
        == f"冲突反思 {tag}"
    )

    # 5) settings: an unrelated multi-region draft survives apply + reload
    driver.eval("window.__d1Editor.leaveToCalendar()")
    driver.wait_until(
        "window.__d1App.view() === 'workbench'", what="返回工作台", timeout=30
    )
    driver.eval(f"window.__d1Workbench.openDate({json.dumps(args.date)})")
    driver.wait_until(
        "window.__d1App.view() === 'editor'", what="再次进入编辑器", timeout=30
    )
    driver.wait_until(
        "window.__d1Editor.phase() === 'ready'", what="编辑器就绪（设置前）", timeout=30
    )
    driver.eval("window.__d1Editor.goSettings()")
    driver.wait_until(
        "window.__d1App.view() === 'settings'", what="进入设置", timeout=30
    )
    driver.wait_until("Boolean(window.__d1Settings)", what="设置钩子就绪", timeout=30)
    status, context_now = http("GET", "/api/local/context")
    config_version = (context_now or {}).get("config_version")
    driver.eval(
        "window.__d1Settings.setClassDraft("
        + json.dumps("本地班级草稿", ensure_ascii=False)
        + ")"
    )
    driver.eval(
        "window.__d1Settings.setProfile("
        + json.dumps(
            (context_now or {}).get("profile", {}).get("display_name", ""),
            ensure_ascii=False,
        )
        + ", "
        + json.dumps(f"回归园所 {tag}", ensure_ascii=False)
        + ")"
    )
    driver.eval("window.__d1Settings.previewProfile()")
    driver.wait_until(
        "window.__d1Settings.previewVisible() === true", what="资料预览", timeout=30
    )
    checks["fix_settings_preview_changed"] = (
        driver.eval("window.__d1Settings.previewChanged()") is True
    )
    driver.eval("window.__d1Settings.applyPreview()")
    driver.wait_until(
        "window.__d1Settings.applyResult() !== ''", what="配置应用回执", timeout=30
    )
    deadline = time.time() + 30
    new_config_version = config_version
    while time.time() < deadline and new_config_version == config_version:
        status, context_now = http("GET", "/api/local/context")
        new_config_version = (context_now or {}).get("config_version")
        if new_config_version == config_version:
            time.sleep(0.2)
    checks["fix_settings_applied"] = new_config_version == config_version + 1
    kept = False
    deadline = time.time() + 20
    while time.time() < deadline:
        if (
            driver.eval("window.__d1Settings.draftActive()") is True
            and driver.eval("window.__d1Settings.classDraft()") == "本地班级草稿"
        ):
            kept = True
            break
        time.sleep(0.2)
    checks["fix_settings_other_draft_kept"] = kept
    driver.eval("window.__d1Settings.cancelDraft()")
    driver.wait_until(
        "window.__d1Settings.draftActive() === false", what="取消编辑", timeout=15
    )
    driver.eval("window.__d1Settings.back()")
    driver.wait_until(
        "window.__d1App.view() === 'workbench'", what="返回工作台（设置）", timeout=30
    )

    # 6) date switch with unsaved input saves before leaving
    driver.eval(f"window.__d1Workbench.openDate({json.dumps(args.date)})")
    driver.wait_until(
        "window.__d1App.view() === 'editor'", what="编辑器（切日期前）", timeout=30
    )
    driver.wait_until(
        "window.__d1Editor.phase() === 'ready'", what="编辑器就绪（切日期前）", timeout=30
    )
    driver.eval(
        "window.__d1Editor.setText("
        + json.dumps(f"切日期前内容 {tag}", ensure_ascii=False)
        + ", "
        + json.dumps(f"切日期前反思 {tag}", ensure_ascii=False)
        + ")"
    )
    driver.wait_until(
        "window.__d1Editor.dirty() === true", what="切日期前输入", timeout=15
    )
    status, detail = http("GET", f"/api/daily-plans/{plan_id}")
    version_before_switch = (detail or {}).get("current_content_version")
    driver.eval("window.__d1Editor.switchDate(" + json.dumps(args.date2) + ")")
    driver.wait_until(
        "window.__d1Editor && window.__d1Editor.planDate() === "
        + json.dumps(args.date2)
        + " && ['ready','create_confirmation'].includes(window.__d1Editor.phase())",
        what="切日期完成",
        timeout=60,
    )
    if driver.eval("window.__d1Editor.phase()") == "create_confirmation":
        driver.eval("window.__d1Editor.confirmCreate()")
        driver.wait_until(
            "window.__d1Editor.phase() === 'ready'", what="创建第二个日期", timeout=30
        )
    status, detail = http("GET", f"/api/daily-plans/{plan_id}")
    checks["fix_date_switch_saved"] = (
        status == 200
        and (detail or {}).get("current_content_version") == version_before_switch + 1
        and (detail or {}).get("content", {}).get("raw_lesson_plan")
        == f"切日期前内容 {tag}"
    )

    # 7) a real export through the range/confirmation/save flow
    run_export("fix-regression-day", "day")
    summary["fix_regression"] = {"plan_id": plan_id, "tag": tag}


def drive_fix_regression2(driver, args, summary, checks, host_api, port) -> None:
    """Second fix regression through the real WebView2 window (R1/R6 slice).

    Window-level asynchronous paths that component probes cannot replace:

    1. a close whose bridge reply is lost: the host leaves the request
       pending, its real 30s timeout aborts it and notifies the page through
       the real evaluate_js transport; the page must release the close freeze
       and coordinator wait (R1) and a later close must succeed;
    2. an export whose native result is authoritatively pending while a late
       query for an older operation arrives: the late answer must never touch
       the new operation (R6);
    3. a settings preview overtaken by newer input: the stale answer must not
       restore an old confirmation and no apply may run (R4 window path);
    4. clean-IME leave paths (calendar / settings): the final composed text
       must be saved before the navigation runs;
    5. a final close while a native Word save is in flight: the page waits for
       the save result and only then sends the allow that really destroys the
       window (the host-side revoke path is covered by the closed R11 probes).
    """
    tag = args.session_tag

    def editor(script: str):
        return driver.eval(f"window.__d1Editor.{script}")

    def settings(script: str):
        return driver.eval(f"window.__d1Settings.{script}")

    # --- 1) close with a lost bridge reply: the host 30s timeout aborts ------
    driver.wait_until(
        "window.__d1Editor.phase() === 'ready' && window.__d1Editor.dirty() === false",
        what="fix2 编辑器就绪且 clean",
        timeout=30,
    )
    driver.eval(
        """(() => {
          const api = window.pywebview.api;
          window.__fix2Close = { sent: [], received: [], aborted: [], finalSent: [] };
          window.__fix2RealCompleteClose = api.complete_close;
          api.complete_close = (payload) => {
            // Simulated lost bridge reply: the page never receives an answer
            // and the host is not told either, so only its real 30s timeout
            // can cancel this request.
            window.__fix2Close.sent.push({
              id: payload.close_request_id, allow: payload.allow, at: Date.now() });
            return new Promise(() => {});
          };
          const handlers = window.__kgmHandlers;
          window.__fix2RealOnRequest = handlers.onRequestClose;
          window.__fix2RealOnAborted = handlers.onCloseAborted;
          handlers.onRequestClose = (id, generation) => {
            window.__fix2Close.received.push(id);
            return window.__fix2RealOnRequest(id, generation);
          };
          handlers.onCloseAborted = (id, reason) => {
            window.__fix2Close.aborted.push({ id: id, reason: reason });
            return window.__fix2RealOnAborted(id, reason);
          };
          return true;
        })()"""
    )
    window = host_api._window()
    window.destroy()
    driver.wait_until(
        "window.__fix2Close.received.length >= 1",
        what="fix2 关闭请求到达页面",
        timeout=20,
    )
    request_id = driver.eval("window.__fix2Close.received[0]")
    driver.wait_until(
        "window.__fix2Close.sent.length >= 1",
        what="fix2 页面尝试完成关闭（回包丢失）",
        timeout=20,
    )
    # While the reply is lost the close freeze must keep the page (a
    # communication failure never unlocks by itself).
    driver.eval("window.__d1Editor.leaveToCalendar()")
    time.sleep(1.0)
    checks["fix2_lost_reply_freeze_blocks_navigation"] = (
        driver.eval("window.__d1App.view()") == "editor"
    )
    # The host's real timeout aborts this request through evaluate_js.
    started = time.time()
    driver.wait_until(
        "window.__fix2Close.aborted.some((entry) => entry.reason === 'timeout')",
        what="fix2 宿主 30 秒超时撤销",
        timeout=45,
    )
    summary["fix2_timeout_elapsed"] = round(time.time() - started, 1)
    aborted_id = driver.eval(
        "window.__fix2Close.aborted.find((entry) => entry.reason === 'timeout').id"
    )
    checks["fix2_timeout_abort_for_same_id"] = aborted_id == request_id
    # R1: the coordinator wait was released with the authoritative cancel, so
    # navigation works while the old promise is still unanswered.
    driver.eval("window.__d1Editor.leaveToCalendar()")
    driver.wait_until(
        "window.__d1App.view() === 'workbench'",
        what="fix2 超时撤销后返回工作台",
        timeout=30,
    )
    checks["fix2_navigation_after_abort"] = True
    checks["fix2_host_canceled_after_timeout"] = (
        host_api._close_coordinator is not None
        and host_api._close_coordinator.state(request_id) == "canceled"
    )

    # --- 1b) abort while the close waits for an in-flight native save --------
    # (review §12.3: the close lifecycle must cover the native-save wait
    # before the coordinator entry; the authoritative cancel is kept by id.)
    driver.eval("window.__d1Workbench.openDate(" + json.dumps(args.date) + ")")
    driver.wait_until(
        "window.__d1App.view() === 'editor'", what="fix2 编辑器（保存等待撤销）", timeout=30
    )
    driver.wait_until(
        "window.__d1Editor.phase() === 'ready' && window.__d1Editor.dirty() === false",
        what="fix2 编辑器就绪（保存等待撤销）",
        timeout=30,
    )
    sent_before_1b = driver.eval("window.__fix2Close.sent.length")
    received_before_1b = driver.eval("window.__fix2Close.received.length")
    release_1b = threading.Event()
    real_perform_1b = host_api._perform_save  # type: ignore[attr-defined]

    def slow_perform_1b(filename: str, data: bytes) -> dict:
        _startup_log("fix2 slow save begin (save-wait abort)")
        release_1b.wait(40)
        result = real_perform_1b(filename, data)
        _startup_log("fix2 slow save completed (save-wait abort)")
        return result

    host_api._perform_save = slow_perform_1b  # type: ignore[attr-defined]
    driver.eval("window.__d1Export.setMode('day')")
    driver.eval("window.__d1Export.runConfirmed()")
    deadline = time.time() + 30
    while time.time() < deadline and not host_api._save_in_progress():
        time.sleep(0.1)
    checks["fix2_savewait_save_started"] = host_api._save_in_progress()
    coordinator = host_api._close_coordinator
    original_timeout = coordinator._timeout_seconds if coordinator else None
    if coordinator is not None:
        # Same timeout path, shortened bound so the scenario stays bounded.
        coordinator._timeout_seconds = 5.0
    window = host_api._window()
    window.destroy()
    driver.wait_until(
        f"window.__fix2Close.received.length >= {received_before_1b + 1}",
        what="fix2 保存等待中的关闭请求到达页面",
        timeout=20,
    )
    request_id_1b = driver.eval(
        f"window.__fix2Close.received[{received_before_1b}]"
    )
    driver.wait_until(
        f"window.__fix2Close.aborted.some((entry) => entry.id === "
        f"{json.dumps(request_id_1b)} && entry.reason === 'timeout')",
        what="fix2 保存等待期间宿主超时撤销",
        timeout=20,
    )
    checks["fix2_savewait_abort_notified"] = True
    checks["fix2_savewait_a_silent_while_saving"] = bool(
        driver.eval("window.__fix2Close.sent.length") == sent_before_1b
        and host_api._save_in_progress()
    )
    # Release the still-running save: the export settles normally (consumed).
    release_1b.set()
    deadline = time.time() + 60
    while time.time() < deadline and (
        host_api._save_in_progress()
        or driver.eval("window.__d1Export.busy()") is not False
    ):
        time.sleep(0.2)
    checks["fix2_savewait_export_settled"] = bool(
        not host_api._save_in_progress()
        and driver.eval("window.__d1Export.busy()") is False
    )
    checks["fix2_savewait_a_never_sent"] = (
        driver.eval("window.__fix2Close.sent.length") == sent_before_1b
    )
    checks["fix2_savewait_host_canceled"] = bool(
        coordinator is not None
        and coordinator.state(request_id_1b) == "canceled"
    )
    driver.eval("window.__d1Editor.leaveToCalendar()")
    driver.wait_until(
        "window.__d1App.view() === 'workbench'",
        what="fix2 保存等待撤销后导航",
        timeout=30,
    )
    checks["fix2_savewait_navigation"] = True
    if coordinator is not None and original_timeout is not None:
        coordinator._timeout_seconds = original_timeout
    host_api._perform_save = real_perform_1b  # type: ignore[attr-defined]

    # --- 2) export pending + a late query from the old operation -------------
    driver.eval("window.__d1Workbench.openDate(" + json.dumps(args.date) + ")")
    driver.wait_until(
        "window.__d1App.view() === 'editor'", what="fix2 重新进入编辑器", timeout=30
    )
    driver.wait_until(
        "window.__d1Editor.phase() === 'ready'", what="fix2 编辑器就绪（导出）", timeout=30
    )
    driver.wait_until(
        "Boolean(window.__d1Export && typeof window.__d1Export.runConfirmed === 'function')",
        what="fix2 导出钩子就绪",
        timeout=30,
    )
    driver.eval(
        """(() => {
          const api = window.pywebview.api;
          window.__fix2Export = {
            saveCalls: 0, ids: [], queriesA: 0, finishB: false, q1Settled: false };
          window.__fix2RealSave = api.save_docx;
          window.__fix2RealQuery = api.get_save_result;
          api.save_docx = (payload) => {
            window.__fix2Export.saveCalls += 1;
            window.__fix2Export.ids.push(payload.request_id);
            return Promise.resolve({ status: 'pending' });
          };
          api.get_save_result = (payload) => {
            const firstId = window.__fix2Export.ids[0];
            if (payload.request_id === firstId) {
              window.__fix2Export.queriesA += 1;
              if (window.__fix2Export.queriesA === 1) {
                const q1 = new Promise((resolve) => {
                  window.__fix2Export.resolveQ1 = () =>
                    resolve({ status: 'saved', filename: 'A.docx', bytes: 3 });
                });
                return q1.then((value) => {
                  window.__fix2Export.q1Settled = true;
                  return value;
                });
              }
              return Promise.resolve({ status: 'saved', filename: 'A.docx', bytes: 3 });
            }
            if (window.__fix2Export.finishB) {
              return Promise.resolve({ status: 'saved', filename: 'B.docx', bytes: 3 });
            }
            return Promise.resolve({ status: 'pending' });
          };
          return true;
        })()"""
    )
    driver.eval("window.__d1Export.setMode('day')")
    driver.eval("window.__d1Export.runConfirmed()")
    driver.wait_until(
        "window.__d1Export.phase() === 'save_result_unknown'"
        " && window.__d1Export.unresolvedKind() === 'pending'",
        what="fix2 导出 A 权威 pending",
        timeout=60,
    )
    driver.eval("window.__d1Export.queryLastResult()")  # Q1: delayed
    driver.wait_until(
        "window.__fix2Export.queriesA >= 1",
        what="fix2 Q1 已发出",
        timeout=15,
    )
    driver.eval("window.__d1Export.queryLastResult()")  # Q2: saved
    driver.wait_until(
        "window.__d1Export.phase() === 'saved'", what="fix2 A 终态（Q2 saved）", timeout=30
    )
    driver.eval("window.__d1Export.runConfirmed()")  # B: authoritatively pending
    driver.wait_until(
        "window.__d1Export.phase() === 'save_result_unknown'"
        " && window.__d1Export.unresolvedKind() === 'pending'",
        what="fix2 导出 B 权威 pending",
        timeout=60,
    )
    driver.eval("window.__fix2Export.resolveQ1()")  # the late A saved arrives
    driver.wait_until(
        "window.__fix2Export.q1Settled === true",
        what="fix2 Q1 迟到回包已返回（微任务已全部处理）",
        timeout=15,
    )
    before_late = driver.eval_json(
        "JSON.stringify({"
        "phase: window.__d1Export.phase(),"
        "kind: window.__d1Export.unresolvedKind(),"
        "busy: window.__d1Export.busy(),"
        "saveCalls: window.__fix2Export.saveCalls,"
        "ids: window.__fix2Export.ids"
        "})"
    )
    summary["fix2_export_after_late"] = before_late
    checks["fix2_export_late_query_never_touches_b"] = bool(
        before_late.get("phase") == "save_result_unknown"
        and before_late.get("kind") == "pending"
        and before_late.get("busy") is True
        and before_late.get("saveCalls") == 2
        and len(set(before_late.get("ids") or [])) == 2
    )
    # A retry while B is unresolved must not start a third save.
    driver.eval("window.__d1Export.runConfirmed()")
    time.sleep(0.8)
    checks["fix2_export_no_third_save"] = (
        driver.eval("window.__fix2Export.saveCalls") == 2
    )
    # Finish B through the read-only query path, then restore the real bridge.
    driver.eval("window.__fix2Export.finishB = true")
    driver.eval("window.__d1Export.queryLastResult()")
    driver.wait_until(
        "window.__d1Export.phase() === 'saved'", what="fix2 B 终态", timeout=30
    )
    driver.eval(
        "(() => { window.pywebview.api.save_docx = window.__fix2RealSave;"
        " window.pywebview.api.get_save_result = window.__fix2RealQuery; return true; })()"
    )

    # --- 2b) R6 residual: the actual query button after a retired query ------
    # A explicit unknown → the real query button starts Q1 which never
    # answers → the user checks the target file → the dialog is closed /
    # reopened → operation B is pending. B's query button must be usable
    # again and B's query must resolve; the late Q1 must not touch B
    # (review §12.3). Controlled bridge states; real DOM buttons.
    def sel(selector: str) -> str:
        return "document.querySelector(" + json.dumps(selector) + ")"

    def export_dialog_visible() -> str:
        return (
            "(() => { const el = " + sel('[data-d1="export-dialog"]') + ";"
            " if (!el) return false;"
            " const overlay = el.closest('.el-overlay');"
            " if (overlay && getComputedStyle(overlay).display === 'none') return false;"
            " const rect = el.getBoundingClientRect();"
            " return rect.width > 0 && rect.height > 0; })()"
        )

    def query_button_disabled() -> str:
        return (
            "Boolean(" + sel('[data-d1="query-save-result"]') + " && "
            + sel('[data-d1="query-save-result"]') + ".disabled)"
        )

    def click_run_until_native_phase(target_kind: str, what: str) -> bool:
        """Drive the real export button through the possible 409 ack loop."""
        ack_js = "Boolean(" + sel('[data-d1="export-ack"]') + ")"
        terminal_js = (
            "window.__d1Export.phase() === 'save_result_unknown'"
            f" && window.__d1Export.unresolvedKind() === {json.dumps(target_kind)}"
        )
        driver.eval(sel('[data-d1="export-run"]') + ".click()")
        driver.wait_until(
            ack_js + " || " + terminal_js,
            what=what + "（启动或缺项确认）",
            timeout=60,
        )
        ack_seen = bool(driver.eval(ack_js))
        if ack_seen:
            driver.eval(
                sel('[data-d1="export-ack"]') + ".querySelector('input').click()"
            )
            driver.wait_until(
                "!(" + sel('[data-d1="export-run"]') + ".disabled)",
                what=what + "（确认缺项后按钮可用）",
                timeout=15,
            )
            driver.eval(sel('[data-d1="export-run"]') + ".click()")
            driver.wait_until(terminal_js, what=what, timeout=60)
        return ack_seen

    driver.eval(sel('[data-d1="open-export"]') + ".click()")
    driver.wait_until(export_dialog_visible(), what="fix2b 导出对话框打开", timeout=15)
    driver.eval(
        """(() => {
          const api = window.pywebview.api;
          window.__fix2Q = { saveCalls: 0, ids: [], q1Calls: 0, hungSettled: false };
          window.__fix2RealSave2 = api.save_docx;
          window.__fix2RealQuery2 = api.get_save_result;
          api.save_docx = (payload) => {
            window.__fix2Q.saveCalls += 1;
            window.__fix2Q.ids.push(payload.request_id);
            return Promise.resolve(
              window.__fix2Q.saveCalls === 1 ? { status: 'unknown' } : { status: 'pending' });
          };
          api.get_save_result = (payload) => {
            window.__fix2Q.q1Calls += 1;
            if (payload.request_id === window.__fix2Q.ids[0]) {
              const hung = new Promise((resolve) => {
                window.__fix2Q.resolveHung = () =>
                  resolve({ status: 'saved', filename: 'A.docx', bytes: 3 });
              });
              return hung.then((value) => {
                window.__fix2Q.hungSettled = true;
                return value;
              });
            }
            return Promise.resolve({ status: 'saved', filename: 'B.docx', bytes: 3 });
          };
          return true;
        })()"""
    )
    driver.eval("window.__d1Export.setMode('day')")
    ack_first = click_run_until_native_phase("unknown", "fix2b A 显式 unknown")
    summary["fix2b_ack_first_export"] = ack_first
    summary["fix2b_after_run_click"] = driver.eval_json(
        "JSON.stringify({"
        "seq: window.__d1Export.seq(),"
        "phase: window.__d1Export.phase(),"
        "kind: window.__d1Export.unresolvedKind(),"
        "busy: window.__d1Export.busy(),"
        "saveCalls: window.__fix2Q.saveCalls"
        "})"
    )
    checks["fix2b_query_button_enabled_for_unknown"] = (
        driver.eval(query_button_disabled()) is False
    )
    # The real query button starts Q1, which never answers.
    driver.eval(sel('[data-d1="query-save-result"]') + ".click()")
    driver.wait_until(
        "window.__fix2Q.q1Calls >= 1", what="fix2b Q1 已由按钮发出", timeout=15
    )
    driver.wait_until(
        query_button_disabled() + " === true",
        what="fix2b Q1 在途：查询按钮 loading/disabled",
        timeout=15,
    )
    checks["fix2b_q1_button_loading"] = True
    # The user checks the target file through the real confirm button.
    driver.wait_until(
        "Boolean(" + sel('[data-d1="confirm-file-checked"]') + ")",
        what="fix2b 文件核对按钮可见",
        timeout=15,
    )
    driver.eval(sel('[data-d1="confirm-file-checked"]') + ".click()")
    driver.wait_until(
        "window.__d1Export.unresolvedKind() === null",
        what="fix2b 显式文件核对完成",
        timeout=15,
    )
    # Close / reopen through the real controls, then run B.
    driver.eval(sel('[data-d1="export-cancel"]') + ".click()")
    driver.wait_until(
        "!(" + export_dialog_visible() + ")",
        what="fix2b 导出对话框已关闭",
        timeout=15,
    )
    driver.eval(sel('[data-d1="open-export"]') + ".click()")
    driver.wait_until(export_dialog_visible(), what="fix2b 导出对话框重开", timeout=15)
    driver.eval("window.__d1Export.setMode('day')")
    ack_b = click_run_until_native_phase("pending", "fix2b B 权威 pending")
    summary["fix2b_ack_second_export"] = ack_b
    checks["fix2b_b_query_button_enabled"] = (
        driver.eval(query_button_disabled()) is False
    )
    driver.eval(sel('[data-d1="query-save-result"]') + ".click()")
    driver.wait_until(
        "window.__d1Export.phase() === 'saved'", what="fix2b B 查询 saved", timeout=30
    )
    checks["fix2b_b_query_resolves"] = (
        driver.eval("window.__d1Export.savedFilename()") == "B.docx"
    )
    # The retired Q1 finally answers late: B is untouched.
    driver.eval("window.__fix2Q.resolveHung()")
    driver.wait_until(
        "window.__fix2Q.hungSettled === true", what="fix2b 旧 Q1 回包返回", timeout=15
    )
    checks["fix2b_old_q1_late_never_touches_b"] = bool(
        driver.eval("window.__d1Export.savedFilename()") == "B.docx"
        and driver.eval("window.__d1Export.phase()") == "saved"
        and driver.eval("window.__fix2Q.saveCalls") == 2
    )
    # Cleanup: restore the real bridge and close the dialog.
    driver.eval(
        "(() => { window.pywebview.api.save_docx = window.__fix2RealSave2;"
        " window.pywebview.api.get_save_result = window.__fix2RealQuery2; return true; })()"
    )
    driver.eval(sel('[data-d1="export-cancel"]') + ".click()")
    driver.wait_until(
        "!(" + export_dialog_visible() + ")",
        what="fix2b 导出对话框关闭（清理）",
        timeout=15,
    )

    # --- 3) settings preview overtaken by newer input ------------------------
    driver.eval("window.__d1Editor.goSettings()")
    driver.wait_until(
        "window.__d1App.view() === 'settings'", what="fix2 进入设置", timeout=30
    )
    driver.wait_until("Boolean(window.__d1Settings)", what="fix2 设置钩子", timeout=30)
    driver.eval(
        """(() => {
          const realFetch = window.fetch.bind(window);
          window.__fix2RealFetch = realFetch;
          window.__fix2Preview = { held: false, released: false, served: false, status: null };
          window.fetch = (input, init) => {
            const url = typeof input === 'string' ? input : (input && input.url) || '';
            if (!window.__fix2Preview.held
                && url.indexOf('/api/local/config/preview') >= 0) {
              window.__fix2Preview.held = true;
              return new Promise((resolve, reject) => {
                window.__fix2Preview.release = () => {
                  window.__fix2Preview.released = true;
                  realFetch(input, init).then(
                    (response) => {
                      window.__fix2Preview.served = true;
                      window.__fix2Preview.status = response.status;
                      resolve(response);
                    },
                    (error) => {
                      window.__fix2Preview.served = true;
                      window.__fix2Preview.status = -1;
                      reject(error);
                    },
                  );
                };
              });
            }
            return realFetch(input, init);
          };
          return true;
        })()"""
    )
    driver.eval("window.__d1Settings.setProfile('预览乱序老师', '预览乱序园所')")
    driver.wait_until(
        "window.__d1Settings.draftActive() === true",
        what="fix2 预览输入已进入模型",
        timeout=15,
    )
    driver.eval("window.__d1Settings.previewProfile()")
    driver.wait_until(
        "window.__fix2Preview.held === true", what="fix2 预览被挂起", timeout=15
    )
    driver.wait_until(
        "(" + sel('[data-d1="preview-profile"]') + ".disabled)",
        what="fix2 预览在途：按钮 loading",
        timeout=15,
    )
    input_version_before = driver.eval("window.__d1Settings.inputVersion()")
    driver.eval("window.__d1Settings.setClassDraft('乱序期间的班级草稿')")
    # The new input must have invalidated the in-flight preview binding before
    # the response is allowed to arrive (the watcher flush, not a fixed sleep).
    driver.wait_until(
        f"window.__d1Settings.inputVersion() > {input_version_before}",
        what="fix2 乱序输入已生效（旧预览绑定失效）",
        timeout=15,
    )
    driver.eval("window.__fix2Preview.release()")
    driver.wait_until(
        "window.__fix2Preview.served === true",
        what="fix2 预览响应真实返回",
        timeout=30,
    )
    # The component finished processing the response when its preview button
    # leaves loading (previewing=false in its finally).
    driver.wait_until(
        "!(" + sel('[data-d1="preview-profile"]') + ".disabled)",
        what="fix2 预览按钮结束 loading（响应已处理）",
        timeout=30,
    )
    preview_status = driver.eval("window.__fix2Preview.status")
    summary["fix2_preview_status"] = preview_status
    # Strengthened boundary: the stale preview really completed as an HTTP
    # response (status recorded — not just "the request settled") and the
    # component finished processing it (button left loading above) before the
    # assertions. Neither replaces the dropped-response reasoning.
    checks["fix2_stale_preview_http_status"] = preview_status == 200
    checks["fix2_stale_preview_dropped"] = settings("previewVisible()") is False
    checks["fix2_stale_preview_keeps_draft"] = settings("draftActive()") is True
    driver.eval("window.__d1Settings.applyPreview()")
    checks["fix2_stale_apply_refused"] = (
        settings("applyResult()") == "" and settings("previewVisible()") is False
    )
    # Cleanup: cancel the draft, restore fetch, go back to the workbench.
    driver.eval("window.__d1Settings.cancelDraft()")
    driver.eval("window.fetch = window.__fix2RealFetch")
    driver.wait_until(
        "window.__d1Settings.draftActive() === false",
        what="fix2 设置草稿已取消",
        timeout=15,
    )
    driver.eval("window.__d1Settings.back()")
    driver.wait_until(
        "window.__d1App.view() === 'workbench'", what="fix2 设置返回", timeout=30
    )

    # --- 4) clean-IME leave paths (calendar / settings) ----------------------
    def open_editor_clean() -> None:
        driver.eval("window.__d1Workbench.openDate(" + json.dumps(args.date) + ")")
        driver.wait_until(
            "window.__d1App.view() === 'editor'", what="fix2 进入编辑器", timeout=30
        )
        driver.wait_until(
            "window.__d1Editor.phase() === 'ready'"
            " && window.__d1Editor.dirty() === false",
            what="fix2 编辑器就绪且 clean",
            timeout=30,
        )

    def start_composition(element_name: str, hold_text: str) -> None:
        driver.eval(
            "(() => {"
            " const list = [...document.querySelectorAll('textarea')];"
            " const el = list.find((t) => (t.placeholder || '').includes('原始教案'))"
            "   || list[list.length - 1];"
            " if (!el) { throw new Error('no textarea found'); }"
            f" window.{element_name} = el;"
            " el.focus();"
            " el.dispatchEvent(new CompositionEvent('compositionstart', { bubbles: true }));"
            " const setter = Object.getOwnPropertyDescriptor("
            "   window.HTMLTextAreaElement.prototype, 'value').set;"
            f" setter.call(el, {json.dumps(hold_text, ensure_ascii=False)});"
            " el.dispatchEvent(new Event('input', { bubbles: true }));"
            " return true;"
            " })()"
        )
        driver.wait_until(
            "window.__d1Editor.composing() === true", what="组合开始", timeout=15
        )

    def end_composition(element_name: str, final_text: str) -> None:
        driver.eval(
            "(() => {"
            f" const el = window.{element_name};"
            " const setter = Object.getOwnPropertyDescriptor("
            "   window.HTMLTextAreaElement.prototype, 'value').set;"
            f" setter.call(el, {json.dumps(final_text, ensure_ascii=False)});"
            " el.dispatchEvent(new Event('input', { bubbles: true }));"
            " el.dispatchEvent(new CompositionEvent("
            "   'compositionend', { bubbles: true, data: '最终' }));"
            " return true;"
            " })()"
        )

    def plan_raw_via_api(plan_id_value: str):
        token = host_api._launch_token
        _status, detail = _http_json(
            port, token, "GET", f"/api/daily-plans/{plan_id_value}"
        )
        if not isinstance(detail, dict):
            return None, None
        return (
            (detail.get("content") or {}).get("raw_lesson_plan"),
            detail.get("current_content_version"),
        )

    # calendar path
    open_editor_clean()
    plan_id = editor("planId()")
    version_before = editor("version()")
    start_composition("__fix2ImeCalendar", "日历离开组合中")
    driver.eval("window.__d1Editor.leaveToCalendar()")
    time.sleep(0.8)
    checks["fix2_clean_ime_calendar_waits"] = bool(
        driver.eval("window.__d1App.view()") == "editor"
        and editor("version()") == version_before
        and editor("dirty()") is False
    )
    end_composition("__fix2ImeCalendar", "日历离开最终文本")
    driver.wait_until(
        "window.__d1App.view() === 'workbench'",
        what="fix2 clean-IME 返回日历",
        timeout=60,
    )
    raw_now, version_now = plan_raw_via_api(plan_id)
    checks["fix2_clean_ime_calendar_saved"] = bool(
        raw_now == "日历离开最终文本" and version_now == version_before + 1
    )

    # settings path
    open_editor_clean()
    plan_id = editor("planId()")
    version_before = editor("version()")
    start_composition("__fix2ImeSettings", "设置离开组合中")
    driver.eval("window.__d1Editor.goSettings()")
    time.sleep(0.8)
    checks["fix2_clean_ime_settings_waits"] = bool(
        driver.eval("window.__d1App.view()") == "editor"
        and editor("version()") == version_before
        and editor("dirty()") is False
    )
    end_composition("__fix2ImeSettings", "设置离开最终文本")
    driver.wait_until(
        "window.__d1App.view() === 'settings'",
        what="fix2 clean-IME 进入设置",
        timeout=60,
    )
    raw_now, version_now = plan_raw_via_api(plan_id)
    checks["fix2_clean_ime_settings_saved"] = bool(
        raw_now == "设置离开最终文本" and version_now == version_before + 1
    )
    driver.eval("window.__d1Settings.back()")
    driver.wait_until(
        "window.__d1App.view() === 'workbench'", what="fix2 设置返回（close）", timeout=30
    )

    # --- 5) final close waits for an in-flight native save --------------------
    open_editor_clean()
    driver.eval(
        """(() => {
          const api = window.pywebview.api;
          const realComplete = window.__fix2RealCompleteClose.bind(api);
          api.complete_close = (payload) => {
            window.__fix2Close.finalSent.push({
              id: payload.close_request_id, allow: payload.allow, at: Date.now() });
            return realComplete(payload);
          };
          return true;
        })()"""
    )
    close_order: dict = {}
    save_release = threading.Event()
    real_perform = host_api._perform_save  # type: ignore[attr-defined]

    def slow_perform(filename: str, data: bytes) -> dict:
        _startup_log("fix2 slow save begin")
        save_release.wait(30)
        result = real_perform(filename, data)
        close_order["save_done_at"] = time.monotonic()
        _startup_log("fix2 slow save completed")
        return result

    host_api._perform_save = slow_perform  # type: ignore[attr-defined]
    coordinator = host_api._close_coordinator
    real_complete = coordinator.complete

    def audited_complete(close_request_id: str, allow: bool) -> dict:
        result = real_complete(close_request_id, allow)
        if allow:
            close_order.setdefault("allow_at", time.monotonic())
            close_order["allow_result"] = result
        return result

    coordinator.complete = audited_complete  # type: ignore[method-assign]

    driver.eval("window.__d1Export.setMode('day')")
    driver.eval("window.__d1Export.runConfirmed()")
    deadline = time.time() + 30
    while time.time() < deadline and not host_api._save_in_progress():
        time.sleep(0.1)
    checks["fix2_close_save_started"] = host_api._save_in_progress()

    window = host_api._window()
    window.destroy()  # the close request arrives while the Word save runs
    driver.wait_until(
        "window.__fix2Close.received.length >= 2",
        what="fix2 保存中的关闭请求到达页面",
        timeout=20,
    )
    time.sleep(1.5)
    checks["fix2_close_no_allow_while_save_running"] = bool(
        driver.eval("window.__fix2Close.finalSent.length") == 0
        and host_api._save_in_progress()
    )
    save_release.set()
    deadline = time.time() + 30
    while time.time() < deadline and "allow_at" not in close_order:
        time.sleep(0.1)
    summary["fix2_close_order"] = {
        "save_done_at": close_order.get("save_done_at"),
        "allow_at": close_order.get("allow_at"),
        "allow_result": close_order.get("allow_result"),
    }
    checks["fix2_close_allow_after_save"] = bool(
        close_order.get("save_done_at") is not None
        and close_order.get("allow_at") is not None
        and close_order["save_done_at"] <= close_order["allow_at"]
    )
    checks["fix2_close_allow_accepted"] = bool(
        (close_order.get("allow_result") or {}).get("accepted") is True
        and (close_order.get("allow_result") or {}).get("state") == "closing"
    )
    summary["fix2_tag"] = tag


class _Win32SaveDialogAutomation:
    """Verification-only Win32 automation of the real native Save As dialog.

    The product page opens the real modal dialog (no ``KGM_D1_VERIFY_SAVE_DIR``
    preauthorized directory); this helper runs on the driver thread of the same
    process, locates that dialog, pastes the requested full path into the real
    file-name edit (clipboard + ``WM_PASTE``: the IFileDialog ignores plain
    ``WM_SETTEXT``) and activates the real Save / Cancel buttons or the
    overwrite confirmation. It never writes the file itself: the production
    host save path performs every write.
    """

    _BM_CLICK = 0x00F5
    _EM_SETSEL = 0x00B1
    _WM_PASTE = 0x0302
    _CF_UNICODETEXT = 13
    _GMEM_MOVEABLE = 0x0002

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        self._ctypes = ctypes
        self._wintypes = wintypes
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32 = self._user32
        kernel32 = self._kernel32
        user32.EnumWindows.argtypes = [
            ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p),
            ctypes.c_void_p,
        ]
        user32.GetWindowThreadProcessId.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.DWORD),
        ]
        user32.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
        user32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
        user32.GetDlgCtrlID.argtypes = [ctypes.c_void_p]
        user32.FindWindowExW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
        ]
        user32.FindWindowExW.restype = ctypes.c_void_p
        user32.SendMessageW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_size_t,
            ctypes.c_ssize_t,
        ]
        user32.SendMessageW.restype = ctypes.c_ssize_t
        user32.PostMessageW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_size_t,
            ctypes.c_ssize_t,
        ]
        user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
        user32.IsWindow.argtypes = [ctypes.c_void_p]
        user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
        user32.OpenClipboard.argtypes = [ctypes.c_void_p]
        user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
        user32.SetClipboardData.restype = ctypes.c_void_p
        kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
        kernel32.GlobalAlloc.restype = ctypes.c_void_p
        kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        self._EnumWindowsProc = ctypes.WINFUNCTYPE(
            ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p
        )

    # -- window helpers ----------------------------------------------------
    def _class_name(self, hwnd: int) -> str:
        buf = self._ctypes.create_unicode_buffer(256)
        self._user32.GetClassNameW(hwnd, buf, 256)
        return buf.value

    def _window_text(self, hwnd: int) -> str:
        buf = self._ctypes.create_unicode_buffer(512)
        self._user32.GetWindowTextW(hwnd, buf, 512)
        return buf.value

    def _top_level_dialogs(self) -> list:
        import os

        pid = os.getpid()
        found: list = []

        @self._EnumWindowsProc
        def callback(hwnd, _lparam):
            wpid = self._wintypes.DWORD()
            self._user32.GetWindowThreadProcessId(hwnd, self._ctypes.byref(wpid))
            if (
                wpid.value == pid
                and self._user32.IsWindowVisible(hwnd)
                and self._class_name(hwnd) == "#32770"
            ):
                found.append(hwnd)
            return True

        self._user32.EnumWindows(callback, None)
        return found

    def _children(self, hwnd: int) -> list:
        out: list = []
        child = self._user32.FindWindowExW(hwnd, None, None, None)
        while child:
            out.append(child)
            child = self._user32.FindWindowExW(hwnd, child, None, None)
        return out

    def _controls(self, hwnd: int, cls: str) -> list:
        out: list = []
        for child in self._children(hwnd):
            if self._class_name(child) == cls:
                out.append(child)
            out.extend(self._controls(child, cls))
        return out

    def button_texts(self, dialog: int) -> list:
        return [
            f"{self._window_text(button)} (id={self._user32.GetDlgCtrlID(button)})"
            for button in self._controls(dialog, "Button")
        ]

    def title(self, dialog: int) -> str:
        return self._window_text(dialog)

    def dialog_alive(self, dialog: int) -> bool:
        return bool(self._user32.IsWindow(dialog))

    # -- dialog actions ----------------------------------------------------
    def wait_for_dialog(self, timeout: float, exclude: int | None = None):
        import time

        deadline = time.time() + timeout
        while time.time() < deadline:
            for hwnd in self._top_level_dialogs():
                if hwnd != exclude:
                    return hwnd
            time.sleep(0.1)
        return None

    def _find_filename_edit(self, dialog: int):
        for edit in self._controls(dialog, "Edit"):
            if self._user32.GetDlgCtrlID(edit) == 1001:
                return edit
        return None

    def _button_matching(self, dialog: int, needles):
        for button in self._controls(dialog, "Button"):
            if any(needle in self._window_text(button) for needle in needles):
                return button
        return None

    def _set_clipboard_text(self, text: str) -> None:
        user32 = self._user32
        kernel32 = self._kernel32
        user32.OpenClipboard(None)
        try:
            user32.EmptyClipboard()
            data = text.encode("utf-16-le") + b"\x00\x00"
            handle = kernel32.GlobalAlloc(self._GMEM_MOVEABLE, len(data))
            ptr = kernel32.GlobalLock(handle)
            try:
                self._ctypes.memmove(ptr, data, len(data))
            finally:
                kernel32.GlobalUnlock(handle)
            user32.SetClipboardData(self._CF_UNICODETEXT, handle)
        finally:
            user32.CloseClipboard()

    def set_filename(self, dialog: int, path: str) -> bool:
        """Paste the full path into the real file-name field; verify it stuck."""
        import time

        edit = self._find_filename_edit(dialog)
        if edit is None:
            return False
        self._user32.SetForegroundWindow(dialog)
        time.sleep(0.3)
        self._set_clipboard_text(path)
        self._user32.SendMessageW(edit, self._EM_SETSEL, 0, -1)
        time.sleep(0.1)
        self._user32.SendMessageW(edit, self._WM_PASTE, 0, 0)
        time.sleep(0.4)
        return self._window_text(edit) == path

    def current_filename_text(self, dialog: int) -> str:
        edit = self._find_filename_edit(dialog)
        return self._window_text(edit) if edit else ""

    def click_save(self, dialog: int) -> bool:
        save = self._button_matching(dialog, ["保存", "Save"])
        if save is None:
            return False
        # PostMessage: BM_CLICK via SendMessage blocks this thread while the
        # dialog's own message loop shows the overwrite confirmation (the
        # button proc does not return until that nested loop ends).
        self._user32.PostMessageW(save, self._BM_CLICK, 0, 0)
        return True

    def click_cancel(self, dialog: int) -> bool:
        cancel = self._button_matching(dialog, ["取消", "Cancel"])
        if cancel is None:
            return False
        self._user32.PostMessageW(cancel, self._BM_CLICK, 0, 0)
        return True

    def click_confirm_yes(self, dialog: int) -> bool:
        yes = self._button_matching(
            dialog, ["是(&Y)", "是", "Yes", "确定", "OK", "重试", "Retry"]
        )
        if yes is None:
            return False
        self._user32.PostMessageW(yes, self._BM_CLICK, 0, 0)
        return True


def _lock_target_exclusive(path) -> int:
    """Hold a real share-limited handle on the target (verification only).

    ``FILE_SHARE_READ`` lets the dialog still read/inspect the file while the
    atomic ``os.replace`` of the production save path is refused until the
    handle is closed -- the real "file in use" failure, not a mocked one.
    """
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel32.CreateFileW
    create.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create.restype = wintypes.HANDLE
    close = kernel32.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    GENERIC_READ = 0x80000000
    GENERIC_WRITE = 0x40000000
    FILE_SHARE_READ = 0x00000001
    OPEN_EXISTING = 3
    FILE_ATTRIBUTE_NORMAL = 0x80
    handle = create(
        str(path),
        GENERIC_READ | GENERIC_WRITE,
        FILE_SHARE_READ,
        None,
        OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL,
        None,
    )
    if not handle or handle == wintypes.HANDLE(-1).value:
        raise OSError(ctypes.get_last_error(), f"无法占用目标文件：{path}")
    return close, handle


def drive_save_dialog(driver, args, summary, checks, host_api, port) -> None:
    """Real native Save As dialog flows (spec §13.2 shortest manual steps).

    Verification-only Win32 automation drives the real modal dialog controls
    (Chinese file name, cancel, real file-in-use failure, release + new-id
    retry, old target protection); every write still goes through the
    production host save path with the native dialog deciding the target --
    ``KGM_D1_VERIFY_SAVE_DIR`` must not be set for this phase.
    """
    import os
    import time
    from pathlib import Path

    if host_api._verify_save_dir is not None:  # type: ignore[attr-defined]
        raise RuntimeError("save-dialog 阶段不能在预授权保存目录下运行")

    target_dir = Path(
        args.save_dialog_dir
        or (Path(args.data or os.environ.get("TEMP", ".")) / "save-dialog")
    )
    target_dir.mkdir(parents=True, exist_ok=True)
    chinese_path = target_dir / "中文名-真实验证.docx"
    locked_path = target_dir / "占用目标.docx"
    old_bytes = "旧目标内容-不得被失败保存改写".encode("utf-8")
    if chinese_path.exists():
        chinese_path.unlink()
    locked_path.write_bytes(old_bytes)

    automation = _Win32SaveDialogAutomation()
    import d1_host_api

    driver.wait_until(
        "window.__d1Editor.phase() === 'ready' && window.__d1Editor.dirty() === false",
        what="save-dialog 编辑器就绪且 clean",
        timeout=30,
    )

    terminal = (
        "['saved','canceled','save_failed','generation_failed','export_not_found']"
        ".includes(window.__d1Export.phase()) && window.__d1Export.busy() === false"
    )

    def export_dialog_visible() -> str:
        selector = json.dumps('[data-d1="export-dialog"]')
        return (
            "(() => { const el = document.querySelector(" + selector + ");"
            " if (!el) return false;"
            " const overlay = el.closest('.el-overlay');"
            " if (overlay && getComputedStyle(overlay).display === 'none') return false;"
            " const rect = el.getBoundingClientRect();"
            " return rect.width > 0 && rect.height > 0; })()"
        )

    def open_fresh_export_dialog() -> None:
        """Close/reopen the export dialog: a fresh session has no stale ack
        context, so one export attempt opens exactly one native dialog."""
        visible = export_dialog_visible()
        if driver.eval(visible) is True:
            driver.eval(
                "document.querySelector('[data-d1=\"export-cancel\"]').click()"
            )
            driver.wait_until(
                "!(" + visible + ")",
                what="save-dialog 关闭旧导出对话框",
                timeout=15,
            )
        driver.eval("document.querySelector('[data-d1=\"open-export\"]').click()")
        driver.wait_until(visible, what="save-dialog 打开导出对话框", timeout=15)

    def drive_one(name: str, path, cancel: bool = False) -> dict:
        info: dict = {
            "dialogs": [],
            "cancel_clicked": False,
            "save_clicked": False,
            "pasted": False,
        }
        stop = threading.Event()
        _startup_log(f"save-dialog {name}: begin")
        open_fresh_export_dialog()

        def handle_dialog(dialog: int) -> None:
            entry = {"title": automation.title(dialog)}
            info["dialogs"].append(entry)
            _startup_log(f"save-dialog {name}: dialog {entry['title']!r}")
            if cancel:
                entry["cancel_clicked"] = automation.click_cancel(dialog)
                info["cancel_clicked"] = True
                _startup_log(f"save-dialog {name}: cancel clicked")
                return
            entry["filename_text"] = automation.current_filename_text(dialog)
            entry["pasted"] = automation.set_filename(dialog, str(path))
            info["pasted"] = info["pasted"] or bool(entry["pasted"])
            entry["save_clicked"] = automation.click_save(dialog)
            info["save_clicked"] = True
            _startup_log(
                f"save-dialog {name}: pasted={entry['pasted']} text={entry['filename_text']!r}"
            )
            deadline = time.time() + 20
            while time.time() < deadline and not stop.is_set():
                if not automation.dialog_alive(dialog):
                    break
                confirm = automation.wait_for_dialog(0.3, exclude=dialog)
                if confirm is None:
                    time.sleep(0.1)
                    continue
                confirm_entry = {
                    "title": automation.title(confirm),
                    "buttons": automation.button_texts(confirm),
                }
                info["dialogs"].append({"confirm": confirm_entry})
                _startup_log(
                    f"save-dialog {name}: confirm {confirm_entry['buttons']}"
                )
                automation.click_confirm_yes(confirm)
                time.sleep(0.3)

        def dialog_thread():
            while not stop.is_set():
                dialog = automation.wait_for_dialog(1.0)
                if dialog is None:
                    continue
                if stop.is_set():
                    return
                try:
                    handle_dialog(dialog)
                except Exception as exc:  # noqa: BLE001
                    info["dialog_error"] = repr(exc)
                    _startup_log(f"save-dialog {name}: dialog error {exc!r}")

        thread = threading.Thread(target=dialog_thread, daemon=True)
        thread.start()
        driver.eval("window.__d1Export.setMode('day')")
        driver.eval("window.__d1Export.runConfirmed()")
        try:
            driver.wait_until(terminal, what=f"save-dialog {name} 终态", timeout=150)
        except Exception:
            info["timeout_state"] = driver.eval_json(
                "JSON.stringify({"
                "phase: window.__d1Export.phase(),"
                "busy: window.__d1Export.busy(),"
                "kind: window.__d1Export.unresolvedKind(),"
                "seq: window.__d1Export.seq(),"
                "result: window.__d1Export.result()"
                "})"
            )
            summary.setdefault("save_dialog", {})[name] = {"info": info}
            _startup_log(f"save-dialog {name}: timeout state {info['timeout_state']}")
            raise
        finally:
            stop.set()
        thread.join(timeout=10)
        info["phase"] = driver.eval("window.__d1Export.phase()")
        info["saved_filename"] = driver.eval("window.__d1Export.savedFilename()")
        info["result_text"] = driver.eval("window.__d1Export.result()")
        info["dialog_count"] = len(
            [d for d in info["dialogs"] if d.get("title")]
        )
        _startup_log(f"save-dialog {name}: done phase={info['phase']}")
        return info

    def last_record_id(before: set):
        new_ids = [key for key in host_api._save_records if key not in before]
        return new_ids[-1] if new_ids else None

    def result_of(record_id):
        if record_id is None:
            return {}
        return dict(host_api._save_records.get(record_id, {}).get("result") or {})

    summary.setdefault("save_dialog", {})
    try:
        # --- A) real Chinese file name through the native dialog ----------
        before = set(host_api._save_records)
        info_a = drive_one("A 中文名保存", chinese_path)
        result_a = result_of(last_record_id(before))
        bytes_a = chinese_path.read_bytes() if chinese_path.exists() else b""
        summary["save_dialog"]["chinese"] = {"info": info_a, "result": result_a}
        checks["save_dialog_dialog_opened"] = bool(info_a["dialog_count"] >= 1)
        checks["save_dialog_chinese_pasted"] = bool(info_a.get("pasted"))
        checks["save_dialog_chinese_saved"] = bool(
            info_a["phase"] == "saved"
            and result_a.get("status") == "saved"
            and result_a.get("filename") == chinese_path.name
            and info_a["saved_filename"] == chinese_path.name
            and bytes_a
            and len(bytes_a) == result_a.get("bytes")
            and d1_host_api.validate_docx_bytes(bytes_a) is None
        )

        # --- B) cancel the native dialog: nothing is written --------------
        listing_before = sorted(p.name for p in target_dir.iterdir())
        info_b = drive_one("B 取消", None, cancel=True)
        listing_after = sorted(p.name for p in target_dir.iterdir())
        summary["save_dialog"]["cancel"] = {"info": info_b}
        checks["save_dialog_cancel"] = bool(
            info_b["dialog_count"] >= 1
            and info_b["cancel_clicked"]
            and info_b["phase"] == "canceled"
            and listing_before == listing_after
        )

        # --- C) real file-in-use failure keeps the old target -------------
        locked_id = None
        close_handle, lock_handle = _lock_target_exclusive(locked_path)
        try:
            before = set(host_api._save_records)
            info_c = drive_one("C 占用失败", locked_path)
            locked_id = last_record_id(before)
            result_c = result_of(locked_id)
            locked_after_c = locked_path.read_bytes()
            temps = [p.name for p in target_dir.glob(f".{locked_path.name}.*.tmp")]
            cached_c = host_api.get_save_result({"request_id": locked_id})
            message_c = str(result_c.get("message") or "")
            cached_message = str(cached_c.get("message") or "")
            text_c = str(info_c.get("result_text") or "")

            def _desensitized(value: str) -> bool:
                # R16: no absolute path, target/temp name or exception detail
                # may appear in the first response, the cache or the page.
                return not any(
                    token in value
                    for token in (
                        str(target_dir),
                        str(locked_path),
                        locked_path.name,
                        ".tmp",
                        "WinError",
                        "winerror",
                    )
                )

            summary["save_dialog"]["locked"] = {
                "info": info_c,
                "result": result_c,
                "request_id": locked_id,
                "cached": cached_c,
            }
            checks["save_dialog_locked_failed"] = bool(
                info_c["dialog_count"] >= 1
                and info_c["phase"] == "save_failed"
                and result_c.get("status") == "failed"
                and locked_after_c == old_bytes
                and not temps
            )
            checks["save_dialog_locked_reason_desensitized"] = bool(
                result_c.get("code") == "SAVE_TARGET_IN_USE"
                and "占用" in message_c
                and cached_c.get("code") == "SAVE_TARGET_IN_USE"
                and cached_message == message_c
                and "占用" in text_c
                and _desensitized(message_c)
                and _desensitized(cached_message)
                and _desensitized(text_c)
            )
        finally:
            close_handle(lock_handle)

        # --- D) release + retry with a new operation id -------------------
        before = set(host_api._save_records)
        info_d = drive_one("D 解除后重试", locked_path)
        retry_id = last_record_id(before)
        result_d = result_of(retry_id)
        bytes_d = locked_path.read_bytes()
        summary["save_dialog"]["retry"] = {
            "info": info_d,
            "result": result_d,
            "retry_id": retry_id,
        }
        checks["save_dialog_retry_new_id_saved"] = bool(
            info_d["dialog_count"] >= 1
            and info_d["phase"] == "saved"
            and result_d.get("status") == "saved"
            and result_d.get("filename") == locked_path.name
            and retry_id
            and locked_id
            and retry_id != locked_id
            and bytes_d != old_bytes
            and len(bytes_d) == result_d.get("bytes")
            and d1_host_api.validate_docx_bytes(bytes_d) is None
        )
        summary["save_dialog"]["target_dir"] = str(target_dir)
    except Exception as exc:
        summary["save_dialog_error"] = str(exc)
        raise


def drive_close_order(driver, args, summary, checks, host_api, port) -> None:
    """R1 close-notification ordering: §13.3 abort variants and §14.3 request
    variants, all inside the real window with the real host state machine,
    real timeouts and real evaluate_js notifications.

    Default family (``--close-order-abort delayed|lost``, §13.3):

    1. a native Word save is really in flight (the driver process slows one
       ``_perform_save`` down; the page sees its real save state);
    2. the first close A begins; the host's real timeout (same path, bound
       shortened to 5s) cancels A, and the verification wrapper holds back
       its ``close_aborted`` notification (released late / dropped);
    3. the second close B begins and reaches the page while A's abort is
       still undelivered: the page must retire A on the confirmed new id,
       not on the old notification;
    4. the save ends: the replaced A must send nothing and B must reach the
       host with allow=true on its own and really close the window;
    5. the host-side audit then proves a single allow (B) was ever sent.

    Request family (``--close-order-request delayed|lost``, review §14.3):

    1. the same native save is in flight;
    2. A begins but its **request notification** is held back/dropped while
       the host's real timeout cancels A; A's abort is delivered first (the
       page never saw A);
    3. B begins and its request reaches the page first; the late/dropped A
       request must be rejected by the host-authority confirmation and must
       never retire B (a duplicate late A is ignored the same way);
    4. the save ends: A stays silent end-to-end, B allows and closes.

    Everything the page sends goes through the real bridge; the audit wraps
    ``CloseCoordinator.complete`` in the driver process, so "A stayed silent"
    is verified end-to-end and does not depend on page-side bookkeeping.
    """
    tag = args.session_tag
    variant = args.close_order_abort
    request_variant = args.close_order_request or ""

    driver.wait_until(
        "window.__d1Editor.phase() === 'ready' && window.__d1Editor.dirty() === false",
        what="close-order 编辑器就绪且 clean",
        timeout=30,
    )

    # Page-side audit: wrap the real bridge so the window evidence keeps the
    # page's own send/receive order (the host-side audit below is the
    # authoritative end-to-end record).
    driver.eval(
        """(() => {
          const api = window.pywebview.api;
          window.__closeOrder = { sent: [], received: [], receivedGens: [], aborted: [] };
          window.__closeOrderRealComplete = api.complete_close;
          api.complete_close = (payload) => {
            window.__closeOrder.sent.push({
              id: payload.close_request_id, allow: payload.allow, at: Date.now() });
            return window.__closeOrderRealComplete(payload);
          };
          const handlers = window.__kgmHandlers;
          window.__closeOrderRealOnRequest = handlers.onRequestClose;
          window.__closeOrderRealOnAborted = handlers.onCloseAborted;
          handlers.onRequestClose = (id, generation) => {
            window.__closeOrder.received.push(id);
            window.__closeOrder.receivedGens.push(generation);
            return window.__closeOrderRealOnRequest(id, generation);
          };
          handlers.onCloseAborted = (id, reason) => {
            window.__closeOrder.aborted.push({ id: id, reason: reason });
            return window.__closeOrderRealOnAborted(id, reason);
          };
          return true;
        })()"""
    )

    coordinator = host_api._close_coordinator
    if coordinator is None:
        raise RuntimeError("close-order 阶段缺少关闭协调器")
    original_timeout = coordinator._timeout_seconds
    coordinator._timeout_seconds = 5.0  # same timeout path, shortened bound
    complete_calls: list = []
    aborted_calls: list = []
    abort_release = threading.Event()
    request_release = threading.Event()
    held_requests: list = []
    held_generations: list = []
    real_complete = coordinator.complete
    real_notify_aborted = host_api._notify_close_aborted  # type: ignore[attr-defined]
    real_notify_request = host_api._notify_request_close  # type: ignore[attr-defined]

    def audited_complete(close_request_id: str, allow: bool) -> dict:
        complete_calls.append(
            {"id": close_request_id, "allow": allow, "at": time.monotonic()}
        )
        return real_complete(close_request_id, allow)

    def held_notify_aborted(close_request_id: str, reason: str) -> None:
        aborted_calls.append(
            {"id": close_request_id, "reason": reason, "at": time.monotonic()}
        )
        if variant == "delayed":
            # Deliver the held notification as soon as the driver releases it
            # (before the save ends): an out-of-order but legal timing.
            abort_release.wait(30)
            real_notify_aborted(close_request_id, reason)
        # "lost": the notification is never delivered at all.

    def audited_notify_aborted(close_request_id: str, reason: str) -> None:
        # Request family: the abort is real and delivered first (review §14.3
        # step 2); only the request notification itself is withheld.
        aborted_calls.append(
            {"id": close_request_id, "reason": reason, "at": time.monotonic()}
        )
        real_notify_aborted(close_request_id, reason)

    def held_first_request(
        close_request_id: str, generation: int | None = None
    ) -> None:
        # Withhold only the first request notification (A): it is delivered
        # late or not at all, while every later request is forwarded.
        if not held_requests:
            held_requests.append(close_request_id)
            held_generations.append(generation)
            if request_variant == "delayed":
                # Deliver the held notification as soon as the driver releases
                # it, with the generation the host bound at announcement time.
                request_release.wait(60)
                real_notify_request(close_request_id, generation)
            # "lost": the request notification is never delivered at all.
            return
        real_notify_request(close_request_id, generation)

    coordinator.complete = audited_complete  # type: ignore[method-assign]
    if request_variant:
        host_api._notify_request_close = held_first_request  # type: ignore[attr-defined]
        host_api._notify_close_aborted = audited_notify_aborted  # type: ignore[attr-defined]
    else:
        host_api._notify_close_aborted = held_notify_aborted  # type: ignore[attr-defined]

    save_release = threading.Event()
    save_state: dict = {}
    real_perform = host_api._perform_save  # type: ignore[attr-defined]

    def slow_perform(filename: str, data: bytes) -> dict:
        save_state["started_at"] = time.monotonic()
        _startup_log("close-order slow save begin")
        save_release.wait(60)
        result = real_perform(filename, data)
        save_state["done_at"] = time.monotonic()
        _startup_log("close-order slow save completed")
        return result

    host_api._perform_save = slow_perform  # type: ignore[attr-defined]

    try:
        driver.eval("window.__d1Export.setMode('day')")
        driver.eval("window.__d1Export.runConfirmed()")
        deadline = time.time() + 30
        while time.time() < deadline and not host_api._save_in_progress():
            time.sleep(0.1)
        checks["close_order_save_started"] = host_api._save_in_progress()

        # --- close A while the native save is really in flight -------------
        window = host_api._window()
        window.destroy()
        if request_variant:
            deadline = time.time() + 20
            while time.time() < deadline and not held_requests:
                time.sleep(0.05)
            if not held_requests:
                raise RuntimeError("close-order: A 的 request 通知未被暂扣")
            request_a = held_requests[0]
            checks["close_order_a_request_held"] = isinstance(request_a, str) and bool(
                request_a
            )
            checks["close_order_a_request_not_delivered"] = (
                driver.eval("window.__closeOrder.received.length") == 0
            )
        else:
            driver.wait_until(
                "window.__closeOrder.received.length === 1",
                what="close-order A 到达页面",
                timeout=20,
            )
            request_a = driver.eval("window.__closeOrder.received[0]")
            checks["close_order_a_received"] = isinstance(request_a, str) and bool(
                request_a
            )

        # The host's real timeout cancels A.
        deadline = time.time() + 30
        while time.time() < deadline and not aborted_calls:
            time.sleep(0.05)
        if not aborted_calls:
            raise RuntimeError("close-order: 宿主超时撤销未触发")
        if request_variant:
            checks["close_order_a_timeout_notified"] = bool(
                aborted_calls[0]["id"] == request_a
                and aborted_calls[0]["reason"] == "timeout"
            )
            # The abort is delivered first, before A's request ever arrives.
            driver.wait_until(
                "window.__closeOrder.aborted.length >= 1",
                what="close-order A 撤销先送达",
                timeout=20,
            )
            checks["close_order_abort_first_delivered"] = bool(
                driver.eval("window.__closeOrder.received.length") == 0
            )
        else:
            checks["close_order_a_timeout_held"] = bool(
                aborted_calls[0]["id"] == request_a
                and aborted_calls[0]["reason"] == "timeout"
            )
            checks["close_order_abort_not_delivered_yet"] = (
                driver.eval("window.__closeOrder.aborted.length") == 0
            )

        # --- close B begins and arrives (while the held signal is pending) --
        window.destroy()
        if request_variant:
            driver.wait_until(
                "window.__closeOrder.received.length === 1",
                what="close-order B 先到达页面",
                timeout=20,
            )
            request_b = driver.eval("window.__closeOrder.received[0]")
            checks["close_order_b_first_request"] = bool(
                isinstance(request_b, str) and request_b and request_b != request_a
            )
        else:
            driver.wait_until(
                "window.__closeOrder.received.length === 2",
                what="close-order B 在旧撤销送达前到达页面",
                timeout=20,
            )
            request_b = driver.eval("window.__closeOrder.received[1]")
            checks["close_order_b_first_before_abort"] = bool(
                isinstance(request_b, str)
                and request_b
                and request_b != request_a
                and driver.eval("window.__closeOrder.aborted.length") == 0
            )
        checks["close_order_no_send_while_save_running"] = bool(
            driver.eval("window.__closeOrder.sent.length") == 0
            and host_api._save_in_progress()
            and not complete_calls
        )

        # The withheld first signal is now released / confirmed lost, still
        # before the save ends.
        if request_variant == "delayed":
            request_release.set()
            driver.wait_until(
                "window.__closeOrder.received.length === 2",
                what="close-order 旧 A request 迟到送达",
                timeout=20,
            )
            checks["close_order_late_request_delivered"] = bool(
                driver.eval("window.__closeOrder.received[1]") == request_a
            )
            checks["close_order_late_request_a_unknown"] = (
                coordinator.state(request_a) == "unknown"
            )
            # A duplicated late request is ignored the same way (re-delivered
            # with the generation the host bound at announcement time).
            real_notify_request(request_a, held_generations[0])
            driver.wait_until(
                "window.__closeOrder.received.length === 3",
                what="close-order 旧 A request 重复送达",
                timeout=20,
            )
            checks["close_order_late_request_duplicate_received"] = bool(
                driver.eval("window.__closeOrder.received[2]") == request_a
            )
        elif request_variant == "lost":
            checks["close_order_request_lost_not_delivered"] = bool(
                driver.eval("window.__closeOrder.received.length") == 1
            )
        elif variant == "delayed":
            abort_release.set()
            driver.wait_until(
                "window.__closeOrder.aborted.some((e) => e.reason === 'timeout')",
                what="close-order A 撤销迟到送达",
                timeout=20,
            )
            checks["close_order_late_abort_delivered"] = True

        # --- the save ends: A silent, B really closes the window -----------
        # Capture the page-side receive order before B's allow really closes
        # the window (no page evaluation happens after destruction).
        received_json = driver.eval_json("JSON.stringify(window.__closeOrder.received)")
        received_count_before_save = driver.eval("window.__closeOrder.received.length")
        save_release.set()
        deadline = time.time() + 30
        while time.time() < deadline and not complete_calls:
            time.sleep(0.05)
        time.sleep(1.5)  # the real destroy runs on the host side now
        allows = [call for call in complete_calls if call["allow"]]
        a_calls = [call for call in complete_calls if call["id"] == request_a]
        checks["close_order_a_silent"] = len(a_calls) == 0
        checks["close_order_b_single_allow"] = bool(
            len(complete_calls) == 1
            and len(allows) == 1
            and allows[0]["id"] == request_b
        )
        checks["close_order_b_host_closing"] = coordinator.state(request_b) == "closing"
        checks["close_order_allow_after_save"] = bool(
            save_state.get("done_at") is not None
            and allows
            and save_state["done_at"] <= allows[0]["at"]
        )
        if request_variant == "lost":
            checks["close_order_request_lost_after_close"] = bool(
                received_count_before_save == 1 and len(held_requests) == 1
            )
        elif not request_variant and variant == "lost":
            checks["close_order_abort_lost_not_delivered"] = True
        summary["close_order"] = {
            "variant": variant,
            "request_variant": request_variant,
            "request_a": request_a,
            "request_b": request_b,
            "held_requests": list(held_requests),
            "held_generations": list(held_generations),
            "received": received_json,
            "received_gens": driver.eval_json(
                "JSON.stringify(window.__closeOrder.receivedGens)"
            ),
            "save_started_at": save_state.get("started_at"),
            "save_done_at": save_state.get("done_at"),
            "aborted_calls": aborted_calls,
            "complete_calls": complete_calls,
            "host_state_a": coordinator.state(request_a),
            "host_state_b": coordinator.state(request_b),
        }
        summary["close_order_tag"] = tag
    finally:
        save_release.set()
        abort_release.set()
        request_release.set()
        coordinator._timeout_seconds = original_timeout
        coordinator.complete = real_complete  # type: ignore[method-assign]
        host_api._notify_request_close = real_notify_request  # type: ignore[attr-defined]
        host_api._notify_close_aborted = real_notify_aborted  # type: ignore[attr-defined]
        host_api._perform_save = real_perform  # type: ignore[attr-defined]


_CLOSE_AUDIT_SCRIPT = """(() => {
  const api = window.pywebview.api;
  window.__closeOrder = { sent: [], received: [], receivedGens: [], aborted: [] };
  window.__closeOrderRealComplete = api.complete_close;
  api.complete_close = (payload) => {
    window.__closeOrder.sent.push({
      id: payload.close_request_id, allow: payload.allow, at: Date.now() });
    return window.__closeOrderRealComplete(payload);
  };
  const handlers = window.__kgmHandlers;
  window.__closeOrderRealOnRequest = handlers.onRequestClose;
  window.__closeOrderRealOnAborted = handlers.onCloseAborted;
  handlers.onRequestClose = (id, generation) => {
    window.__closeOrder.received.push(id);
    window.__closeOrder.receivedGens.push(generation);
    return window.__closeOrderRealOnRequest(id, generation);
  };
  handlers.onCloseAborted = (id, reason) => {
    window.__closeOrder.aborted.push({ id: id, reason: reason });
    return window.__closeOrderRealOnAborted(id, reason);
  };
  return true;
})()"""

# Shortened host timeout bound for the lastack/late-input phases: the real
# timeout path with a small bound so the next close begins before the page's
# 2s per-attempt query bound expires (the page-side handling is unchanged).
_CLOSE_FAST_TIMEOUT_SECONDS = 1.2


def drive_close_lastack(driver, args, summary, checks, host_api) -> None:
    """R1 §15.3 last-confirmation variant of the close-order phase.

    A's first authority answer arrives; the host produces A's second answer
    (``pending`` bound to A's generation) but it stays in transit. A's real
    timeout cancels it (``--close-order-abort delayed`` delivers the real
    abort while the confirmation is in flight; ``lost`` drops it) and B
    begins and is confirmed while the stale answer is still undelivered.
    Only then is the stale answer released: the page must reject it by the
    host generation binding — A stays silent and never retires B — and B
    alone allows and really closes the window. The test asserts the held
    answer was produced while A was current (``pending`` + A's generation).
    """
    variant = args.close_order_abort or "delayed"
    tag = args.session_tag

    driver.wait_until(
        "window.__d1Editor.phase() === 'ready' && window.__d1Editor.dirty() === false",
        what="close-order lastack 编辑器就绪且 clean",
        timeout=30,
    )
    driver.eval(_CLOSE_AUDIT_SCRIPT)

    coordinator = host_api._close_coordinator
    if coordinator is None:
        raise RuntimeError("close-order lastack 阶段缺少关闭协调器")
    original_timeout = coordinator._timeout_seconds
    coordinator._timeout_seconds = _CLOSE_FAST_TIMEOUT_SECONDS

    complete_calls: list = []
    aborted_calls: list = []
    state_calls: list = []
    held_answers: list = []
    gate = threading.Event()
    counts: dict = {}
    real_complete = coordinator.complete
    real_state = host_api.get_close_state  # type: ignore[attr-defined]
    real_notify_aborted = host_api._notify_close_aborted  # type: ignore[attr-defined]

    def audited_complete(close_request_id: str, allow: bool) -> dict:
        complete_calls.append(
            {"id": close_request_id, "allow": allow, "at": time.monotonic()}
        )
        return real_complete(close_request_id, allow)

    def gated_state(payload: object = None) -> dict:
        answer = real_state(payload)
        rid = (
            str(payload.get("close_request_id") or "")
            if isinstance(payload, dict)
            else ""
        )
        state_calls.append(
            {"id": rid, "answer": dict(answer), "at": time.monotonic()}
        )
        counts[rid] = counts.get(rid, 0) + 1
        if (
            not held_answers
            and counts[rid] == 2
            and answer.get("state") == "pending"
        ):
            # The second answer is produced while this id is still current;
            # its delivery is withheld (like a reply lost in transit).
            held_answers.append(
                {"id": rid, "answer": dict(answer), "at": time.monotonic()}
            )
            _startup_log("close-order lastack: A second answer produced (held)")
            gate.wait(60)
            _startup_log("close-order lastack: held A answer released")
        elif held_answers and held_answers[0]["id"] == rid:
            # A retry after the page's per-attempt bound: hold it too so the
            # withheld delivery cannot be bypassed by a second attempt. Once
            # released every wait returns immediately.
            gate.wait(60)
        return answer

    def abort_wrapper(close_request_id: str, reason: str) -> None:
        aborted_calls.append(
            {"id": close_request_id, "reason": reason, "at": time.monotonic()}
        )
        if variant == "delayed":
            real_notify_aborted(close_request_id, reason)
        # "lost": the abort notification is never delivered.

    coordinator.complete = audited_complete  # type: ignore[method-assign]
    host_api.get_close_state = gated_state  # type: ignore[method-assign]
    host_api._notify_close_aborted = abort_wrapper  # type: ignore[attr-defined]

    try:
        window = host_api._window()
        window.destroy()
        deadline = time.time() + 30
        while time.time() < deadline and not held_answers:
            time.sleep(0.05)
        if not held_answers:
            raise RuntimeError("close-order lastack: A 第二问回包未被暂扣")
        request_a = held_answers[0]["id"]
        generation_a = held_answers[0]["answer"].get("generation")
        checks["lastack_a_second_answer_pending"] = (
            held_answers[0]["answer"].get("state") == "pending"
        )
        checks["lastack_a_generation_bound"] = (
            isinstance(generation_a, int) and generation_a > 0
        )
        driver.wait_until(
            "window.__closeOrder.received.length === 1",
            what="close-order lastack A 到达页面",
            timeout=20,
        )
        checks["lastack_a_received"] = bool(
            driver.eval("window.__closeOrder.received[0]") == request_a
        )
        # The host's real timeout cancels A (abort delivered or dropped).
        deadline = time.time() + 30
        while time.time() < deadline and not aborted_calls:
            time.sleep(0.05)
        if not aborted_calls:
            raise RuntimeError("close-order lastack: 宿主超时撤销未触发")
        checks["lastack_a_timeout"] = bool(
            aborted_calls[0]["id"] == request_a
            and aborted_calls[0]["reason"] == "timeout"
        )
        if variant == "delayed":
            driver.wait_until(
                "window.__closeOrder.aborted.length >= 1",
                what="close-order lastack A 撤销已送达",
                timeout=20,
            )
            checks["lastack_abort_delivered_while_verifying"] = True
        else:
            checks["lastack_abort_lost"] = bool(
                driver.eval("window.__closeOrder.aborted.length") == 0
            )
        # B begins and the page confirms it while A's answer is still held.
        window.destroy()
        driver.wait_until(
            "window.__closeOrder.received.length === 2",
            what="close-order lastack B 到达页面",
            timeout=20,
        )
        request_b = driver.eval("window.__closeOrder.received[1]")
        checks["lastack_b_request"] = bool(
            isinstance(request_b, str) and request_b and request_b != request_a
        )
        request_b_expr = json.dumps(request_b)
        driver.wait_until(
            f"window.__d1App.closeState().open.includes({request_b_expr})",
            what="close-order lastack B 在页面侧确认",
            timeout=20,
        )
        request_a_expr = json.dumps(request_a)
        checks["lastack_a_still_verifying_at_b_confirmation"] = bool(
            driver.eval(
                f"window.__d1App.closeState().verifying.includes({request_a_expr})"
            )
        )
        checks["lastack_no_send_before_release"] = bool(
            driver.eval("window.__closeOrder.sent.length === 0")
            and coordinator.state(request_b) == "pending"
        )
        # Release the held stale answer: it must be rejected silently while
        # B alone proceeds to allow and really close the window.
        gate.set()
        deadline = time.time() + 30
        while time.time() < deadline and not complete_calls:
            time.sleep(0.05)
        if not complete_calls:
            raise RuntimeError("close-order lastack: B 未发送最终许可")
        time.sleep(1.5)  # the real destroy runs on the host side now
        a_calls = [call for call in complete_calls if call["id"] == request_a]
        allows = [call for call in complete_calls if call["allow"]]
        checks["lastack_a_silent"] = len(a_calls) == 0
        checks["lastack_b_single_allow"] = bool(
            len(complete_calls) == 1
            and len(allows) == 1
            and allows[0]["id"] == request_b
        )
        checks["lastack_b_host_closing"] = coordinator.state(request_b) == "closing"
        summary["close_order"] = {
            "variant": "lastack",
            "abort_variant": variant,
            "request_a": request_a,
            "request_b": request_b,
            "generation_a": generation_a,
            "generation_b": coordinator.state_answer(request_b).get("generation"),
            "held_answer": held_answers[0]["answer"],
            "state_calls": state_calls,
            "aborted_calls": aborted_calls,
            "complete_calls": complete_calls,
            "host_state_a": coordinator.state(request_a),
            "host_state_b": coordinator.state(request_b),
        }
        summary["close_order_tag"] = tag
    finally:
        gate.set()
        coordinator._timeout_seconds = original_timeout
        coordinator.complete = real_complete  # type: ignore[method-assign]
        host_api.get_close_state = real_state  # type: ignore[method-assign]
        host_api._notify_close_aborted = real_notify_aborted  # type: ignore[attr-defined]


def drive_late_input_close(driver, args, summary, checks, host_api, port) -> None:
    """R17 §15.2: input typed during the final confirmation wait is never
    lost to a close allow.

    A's first authority answer is produced while A is current and held in
    transit. A's real timeout cancels it (``--close-order-abort delayed``
    delivers the real abort while the confirmation is in flight; ``lost``
    drops it); B begins, is confirmed and waits for A's verification — the
    page is still editable there. The driver types into the real textarea
    (DOM input event), then releases the stale answer: A stays silent and B
    must stay on the page and keep the input (explicit deny), no allow and
    no PATCH. A following real close then saves the text (real PATCH) and
    really closes; the post-close database check confirms the content and
    version.
    """
    variant = args.close_order_abort or "delayed"
    tag = args.session_tag

    driver.wait_until(
        "window.__d1Editor.phase() === 'ready' && window.__d1Editor.dirty() === false",
        what="late-input 编辑器就绪且 clean",
        timeout=30,
    )
    plan_id = driver.eval("window.__d1Editor.planId()")
    version_before = driver.eval("window.__d1Editor.version()")
    current_raw = driver.eval("window.__d1Editor.raw()") or ""
    injected = f"关闭确认等待期间的未保存输入 {tag}"
    expected_raw = current_raw + "\n" + injected
    summary["late_input"] = {
        "plan_id": plan_id,
        "version_before": version_before,
        "raw_before": current_raw,
        "expected_raw": expected_raw,
        "injected": injected,
    }
    driver.eval(_CLOSE_AUDIT_SCRIPT)

    coordinator = host_api._close_coordinator
    if coordinator is None:
        raise RuntimeError("late-input 阶段缺少关闭协调器")
    original_timeout = coordinator._timeout_seconds
    coordinator._timeout_seconds = _CLOSE_FAST_TIMEOUT_SECONDS

    complete_calls: list = []
    aborted_calls: list = []
    state_calls: list = []
    held_answers: list = []
    gate = threading.Event()
    real_complete = coordinator.complete
    real_state = host_api.get_close_state  # type: ignore[attr-defined]
    real_notify_aborted = host_api._notify_close_aborted  # type: ignore[attr-defined]

    def audited_complete(close_request_id: str, allow: bool) -> dict:
        complete_calls.append(
            {"id": close_request_id, "allow": allow, "at": time.monotonic()}
        )
        return real_complete(close_request_id, allow)

    def gated_state(payload: object = None) -> dict:
        answer = real_state(payload)
        rid = (
            str(payload.get("close_request_id") or "")
            if isinstance(payload, dict)
            else ""
        )
        state_calls.append(
            {"id": rid, "answer": dict(answer), "at": time.monotonic()}
        )
        if not held_answers and answer.get("state") == "pending":
            # A's first authority answer is produced while A is current and
            # withheld; the page stays in its confirmation for A.
            held_answers.append(
                {"id": rid, "answer": dict(answer), "at": time.monotonic()}
            )
            _startup_log("late-input: A answer produced (held)")
            gate.wait(60)
            _startup_log("late-input: held A answer released")
        elif held_answers and held_answers[0]["id"] == rid:
            # A retry after the page's per-attempt bound: hold it too so the
            # withheld delivery cannot be bypassed by a second attempt. Once
            # released every wait returns immediately.
            gate.wait(60)
        return answer

    def abort_wrapper(close_request_id: str, reason: str) -> None:
        aborted_calls.append(
            {"id": close_request_id, "reason": reason, "at": time.monotonic()}
        )
        if variant == "delayed":
            real_notify_aborted(close_request_id, reason)
        # "lost": the abort notification is never delivered.

    coordinator.complete = audited_complete  # type: ignore[method-assign]
    host_api.get_close_state = gated_state  # type: ignore[method-assign]
    host_api._notify_close_aborted = abort_wrapper  # type: ignore[attr-defined]

    try:
        window = host_api._window()
        window.destroy()
        deadline = time.time() + 30
        while time.time() < deadline and not held_answers:
            time.sleep(0.05)
        if not held_answers:
            raise RuntimeError("late-input: A 第一问回包未被暂扣")
        request_a = held_answers[0]["id"]
        checks["late_input_a_answer_held"] = bool(
            held_answers[0]["answer"].get("state") == "pending"
        )
        # The host's real timeout cancels A (abort delivered or dropped).
        deadline = time.time() + 30
        while time.time() < deadline and not aborted_calls:
            time.sleep(0.05)
        if not aborted_calls:
            raise RuntimeError("late-input: 宿主超时撤销未触发")
        checks["late_input_a_timeout"] = bool(
            aborted_calls[0]["id"] == request_a
            and aborted_calls[0]["reason"] == "timeout"
        )
        if variant == "delayed":
            driver.wait_until(
                "window.__closeOrder.aborted.length >= 1",
                what="late-input A 撤销已送达",
                timeout=20,
            )
            checks["late_input_abort_delivered_while_verifying"] = True
        else:
            checks["late_input_abort_lost"] = bool(
                driver.eval("window.__closeOrder.aborted.length") == 0
            )
        # B begins and is confirmed while A's stale answer is still held; the
        # page must still be editable in that final-confirmation wait.
        window.destroy()
        driver.wait_until(
            "window.__closeOrder.received.length === 2",
            what="late-input B 到达页面",
            timeout=20,
        )
        request_b = driver.eval("window.__closeOrder.received[1]")
        checks["late_input_b_request"] = bool(
            isinstance(request_b, str) and request_b and request_b != request_a
        )
        request_a_expr = json.dumps(request_a)
        request_b_expr = json.dumps(request_b)
        driver.wait_until(
            f"window.__d1App.closeState().open.includes({request_b_expr})"
            f" && window.__d1App.closeState().verifying.includes({request_a_expr})",
            what="late-input B 确认且等待 A 的确认结束",
            timeout=20,
        )
        checks["late_input_wait_window_open"] = bool(
            driver.eval("window.__d1Editor.phase()") == "ready"
            and driver.eval("window.__d1Editor.dirty()") is False
            and driver.eval("window.__closeOrder.sent.length") == 0
        )
        editable = driver.eval(
            """(() => {
              const list = [...document.querySelectorAll('textarea')];
              const el = list.find((t) => (t.placeholder || '').includes('原始教案'))
                || list[list.length - 1];
              return Boolean(el && !el.disabled);
            })()"""
        )
        checks["late_input_editor_still_editable"] = editable is True
        # Real DOM input into the real textarea (controlled page, real event
        # path; not an actual IME key sequence).
        driver.eval(
            "window.__lateInputExpected = "
            + json.dumps(expected_raw, ensure_ascii=False)
        )
        driver.eval(
            """(() => {
              const list = [...document.querySelectorAll('textarea')];
              const el = list.find((t) => (t.placeholder || '').includes('原始教案'))
                || list[list.length - 1];
              if (!el) { throw new Error('no textarea found'); }
              el.focus();
              const setter = Object.getOwnPropertyDescriptor(
                window.HTMLTextAreaElement.prototype, 'value').set;
              setter.call(el, window.__lateInputExpected);
              el.dispatchEvent(new Event('input', { bubbles: true }));
              return true;
            })()"""
        )
        driver.wait_until(
            "window.__d1Editor.dirty() === true",
            what="late-input 新输入就绪（真实 DOM）",
            timeout=15,
        )
        checks["late_input_dom_input_dirty"] = bool(
            driver.eval("window.__d1Editor.raw()") == expected_raw
        )
        # Release the held stale answer: A must stay silent, B must stay on
        # the page and keep the input (explicit deny; no allow, no PATCH).
        gate.set()
        deadline = time.time() + 30
        while time.time() < deadline:
            if driver.eval("window.__closeOrder.sent.length") >= 1:
                break
            time.sleep(0.05)
        sent = driver.eval_json("JSON.stringify(window.__closeOrder.sent)")
        a_calls = [call for call in complete_calls if call["id"] == request_a]
        b_calls = [call for call in complete_calls if call["id"] == request_b]
        checks["late_input_a_silent"] = len(a_calls) == 0
        checks["late_input_b_denied_only"] = bool(
            len(b_calls) == 1 and b_calls[0]["allow"] is False
        )
        checks["late_input_b_not_closing"] = coordinator.state(request_b) != "closing"
        checks["late_input_stayed_unlocked"] = bool(
            driver.eval("window.__closeOrder.sent.length") == 1
            and driver.eval("window.__d1Editor.dirty()") is True
            and driver.eval("window.__d1Editor.raw()") == expected_raw
            and driver.eval("window.__d1Editor.version()") == version_before
        )
        state_after_deny = driver.eval_json(
            "JSON.stringify(window.__d1App.closeState())"
        )
        checks["late_input_no_final_allow"] = bool(
            state_after_deny.get("finalAllowed") is False
            and state_after_deny.get("locked") is False
        )
        summary["late_input"]["sent_after_deny"] = sent
        summary["late_input"]["state_after_deny"] = state_after_deny
        summary["late_input"]["complete_calls"] = list(complete_calls)
        summary["late_input"]["state_calls"] = list(state_calls)
        summary["late_input"]["aborted_calls"] = list(aborted_calls)
        # A following real close saves the kept input and really closes.
        coordinator._timeout_seconds = 10.0
        window.destroy()
        deadline = time.time() + 60
        while time.time() < deadline:
            c_allows = [
                call
                for call in complete_calls
                if call["id"] not in (request_a, request_b) and call["allow"]
            ]
            if c_allows:
                break
            time.sleep(0.05)
        time.sleep(1.5)  # the real destroy runs on the host side now
        request_c = None
        for call in complete_calls:
            if call["id"] not in (request_a, request_b):
                request_c = call["id"]
                break
        checks["late_input_retry_closes"] = bool(
            request_c
            and any(
                call["id"] == request_c and call["allow"] is True
                for call in complete_calls
            )
            and coordinator.state(request_c) == "closing"
        )
        summary["late_input"]["request_c"] = request_c
        summary["late_input"]["version_before_retry"] = version_before
        summary["late_input"]["complete_calls"] = list(complete_calls)
        summary["late_input_audited"] = True
    finally:
        gate.set()
        coordinator._timeout_seconds = original_timeout
        coordinator.complete = real_complete  # type: ignore[method-assign]
        host_api.get_close_state = real_state  # type: ignore[method-assign]
        host_api._notify_close_aborted = real_notify_aborted  # type: ignore[attr-defined]


def drive_settings_draft_close(driver, args, summary, checks, host_api, port) -> None:
    """R17 §16.3: a settings draft created while the close confirmation wait
    is open must keep the page.

    The real settings page starts clean; A's authority answers are produced
    and withheld, the real timeout cancels A (``--close-order-abort delayed``
    delivers the abort while the confirmation is in flight; ``lost`` drops
    it), B begins and is confirmed and waits for A's verification. The driver
    then types into the real profile-name input (real DOM ``input`` event),
    waits for the actual SettingsView ``draftActive`` state, and releases the
    stale answer: B must stay on the page (explicit deny, no allow, no
    configuration POST), keeping the draft. The user then explicitly cancels
    the draft through the real control, and the next close really closes.
    The post-close database check confirms the profile/configuration were
    never changed by the discarded draft.
    """
    import sqlite3

    variant = args.close_order_abort or "delayed"
    tag = args.session_tag

    driver.wait_until(
        "window.__d1Editor.phase() === 'ready' && window.__d1Editor.dirty() === false",
        what="settings-draft 编辑器就绪且 clean",
        timeout=30,
    )
    driver.eval("window.__d1Editor.goSettings()")
    driver.wait_until(
        "window.__d1App.view() === 'settings' && Boolean(window.__d1Settings)",
        what="settings 页面就绪",
        timeout=30,
    )
    driver.wait_until(
        "window.__d1Settings.draftActive() === false",
        what="settings 初始无草稿",
        timeout=15,
    )
    token = host_api._launch_token  # type: ignore[attr-defined]
    context_status, context_before = _http_json(
        port, token, "GET", "/api/local/context"
    )
    if context_status != 200 or not isinstance(context_before, dict):
        raise RuntimeError(
            f"settings-draft: 无法读取本地上下文（status={context_status}）"
        )
    name_before = (context_before.get("profile") or {}).get("display_name")
    version_before = context_before.get("config_version")
    new_name = f"关闭等待期间修改姓名 {tag}"
    config_ops_before = None
    db_path = summary.get("db_path")
    if db_path:
        try:
            connection = sqlite3.connect(
                f"file:{Path(db_path).as_posix()}?mode=ro", uri=True, timeout=10
            )
            try:
                config_ops_before = connection.execute(
                    "SELECT count(*) FROM local_config_operations"
                ).fetchone()[0]
            finally:
                connection.close()
        except Exception:  # noqa: BLE001
            config_ops_before = None
    summary["settings_draft"] = {
        "name_before": name_before,
        "config_version_before": version_before,
        "new_name": new_name,
        "config_ops_before": config_ops_before,
        "variant": variant,
    }

    driver.eval(_CLOSE_AUDIT_SCRIPT)
    # Record every POST the page makes from now on (the close must never
    # apply the draft; a real preview/apply by the user is handled later).
    driver.eval(
        """(() => {
          window.__configPosts = [];
          const realFetch = window.fetch.bind(window);
          window.fetch = (input, init) => {
            const url = typeof input === 'string' ? input : input.url;
            if (init && init.method === 'POST') window.__configPosts.push(url);
            return realFetch(input, init);
          };
          return true;
        })()"""
    )
    coordinator = host_api._close_coordinator
    if coordinator is None:
        raise RuntimeError("settings-draft 阶段缺少关闭协调器")
    original_timeout = coordinator._timeout_seconds
    coordinator._timeout_seconds = _CLOSE_FAST_TIMEOUT_SECONDS

    complete_calls: list = []
    aborted_calls: list = []
    answers: list = []
    held_answers: list = []
    gate = threading.Event()
    real_complete = coordinator.complete
    real_state = host_api.get_close_state  # type: ignore[attr-defined]
    real_notify_aborted = host_api._notify_close_aborted  # type: ignore[attr-defined]

    def audited_complete(close_request_id: str, allow: bool) -> dict:
        item = {"id": close_request_id, "allow": allow, "at": time.monotonic()}
        complete_calls.append(item)
        item["result"] = real_complete(close_request_id, allow)
        return item["result"]

    def gated_state(payload: object = None) -> dict:
        answer = real_state(payload)
        rid = (
            str(payload.get("close_request_id") or "")
            if isinstance(payload, dict)
            else ""
        )
        answers.append({"id": rid, "answer": dict(answer)})
        if not held_answers and answer.get("state") == "pending":
            held_answers.append(rid)
            gate.wait(60)
        elif held_answers and rid == held_answers[0]:
            gate.wait(60)
        return answer

    def abort_wrapper(close_request_id: str, reason: str) -> None:
        aborted_calls.append(
            {"id": close_request_id, "reason": reason, "at": time.monotonic()}
        )
        if variant == "delayed":
            real_notify_aborted(close_request_id, reason)
        # "lost": the abort notification is never delivered.

    coordinator.complete = audited_complete  # type: ignore[method-assign]
    host_api.get_close_state = gated_state  # type: ignore[method-assign]
    host_api._notify_close_aborted = abort_wrapper  # type: ignore[attr-defined]

    closed = threading.Event()
    try:
        window = host_api._window()
        window.events.closed += lambda: closed.set()
    except Exception:  # noqa: BLE001
        closed = None  # type: ignore[assignment]

    try:
        window.destroy()
        deadline = time.time() + 30
        while time.time() < deadline and not held_answers:
            time.sleep(0.05)
        if not held_answers:
            raise RuntimeError("settings-draft: A 回答未被暂扣")
        request_a = held_answers[0]
        deadline = time.time() + 30
        while time.time() < deadline and not aborted_calls:
            time.sleep(0.05)
        if not aborted_calls:
            raise RuntimeError("settings-draft: 宿主超时撤销未触发")
        if variant == "delayed":
            driver.wait_until(
                "window.__closeOrder.aborted.length >= 1",
                what="settings-draft A 撤销已送达",
                timeout=20,
            )
            checks["settings_draft_abort_delivered_while_verifying"] = True
        else:
            checks["settings_draft_abort_lost"] = bool(
                driver.eval("window.__closeOrder.aborted.length") == 0
            )
        window.destroy()
        driver.wait_until(
            "window.__closeOrder.received.length === 2",
            what="settings-draft B 到达页面",
            timeout=20,
        )
        request_b = driver.eval("window.__closeOrder.received[1]")
        request_a_expr = json.dumps(request_a)
        request_b_expr = json.dumps(request_b)
        driver.wait_until(
            f"window.__d1App.closeState().open.includes({request_b_expr})"
            f" && window.__d1App.closeState().verifying.includes({request_a_expr})",
            what="settings-draft B 确认且等待 A",
            timeout=20,
        )
        before = driver.eval_json(
            "JSON.stringify({close:window.__d1App.closeState(),"
            "draft:window.__d1Settings.draftActive(),"
            "view:window.__d1App.view(),"
            "sent:window.__closeOrder.sent})"
        )
        checks["settings_draft_initially_clean"] = bool(
            before["draft"] is False
            and before["close"]["locked"] is False
            and before["close"]["finalAllowed"] is False
        )
        checks["settings_draft_view_is_settings"] = before["view"] == "settings"
        checks["settings_draft_no_send_before_input"] = before["sent"] == []
        driver.eval(
            "window.__settingsDraftName = "
            + json.dumps(new_name, ensure_ascii=False)
        )
        editable = driver.eval(
            """(() => {
              const root = document.querySelector('[data-d1="settings-profile-name"]');
              const el = root && (root.tagName === 'INPUT' ? root : root.querySelector('input'));
              return Boolean(el && !el.disabled);
            })()"""
        )
        checks["settings_draft_input_editable"] = editable is True
        # Real DOM input into the real profile-name field (not an IME key
        # sequence; no programmatic model setter).
        input_result = driver.eval_json(
            """JSON.stringify((() => {
              const root = document.querySelector('[data-d1="settings-profile-name"]');
              const el = root.tagName === 'INPUT' ? root : root.querySelector('input');
              const previous = el.value;
              el.focus();
              Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(
                el, window.__settingsDraftName);
              el.dispatchEvent(new Event('input', { bubbles: true }));
              return {disabled: el.disabled, previous: previous, value: el.value};
            })())"""
        )
        driver.wait_until(
            "window.__d1Settings.draftActive() === true",
            what="真实设置草稿已产生",
            timeout=15,
        )
        after_input = driver.eval_json(
            "JSON.stringify({draft:window.__d1Settings.draftActive(),"
            "close:window.__d1App.closeState(),"
            "posts:window.__configPosts ?? [],"
            "sent:window.__closeOrder.sent})"
        )
        checks["settings_draft_active_before_release"] = (
            after_input["draft"] is True
        )
        checks["settings_draft_no_post_before_release"] = (
            after_input["posts"] == []
        )
        # Release the withheld A answer: B makes its final decision.
        gate.set()
        deadline = time.time() + 20
        while time.time() < deadline and not complete_calls:
            time.sleep(0.05)
        if not complete_calls:
            raise RuntimeError("settings-draft: 页面未给出关闭决定")
        b_calls = [call for call in complete_calls if call["id"] == request_b]
        a_calls = [call for call in complete_calls if call["id"] == request_a]
        allowed = any(call["allow"] is True for call in b_calls)
        checks["settings_draft_never_allow"] = not allowed
        summary["settings_draft"].update(
            {
                "before": before,
                "input": input_result,
                "after_input": after_input,
                "answers": answers,
                "aborts": aborted_calls,
            }
        )
        if allowed:
            # Counterexample (pre-fix): the window really closes and the
            # draft disappears with it.
            did_close = bool(closed is not None and closed.wait(10))
            checks["settings_draft_window_closed_after_allow"] = did_close
            summary["settings_draft"]["complete_calls"] = list(complete_calls)
            summary["settings_draft"]["actual_window_closed"] = did_close
            raise RuntimeError(
                "settings-draft 反例：未确认设置草稿被关窗丢弃（B allow=true）"
            )
        checks["settings_draft_b_denied_only"] = bool(
            len(b_calls) == 1 and b_calls[0]["allow"] is False
        )
        checks["settings_draft_b_not_closing"] = coordinator.state(request_b) != "closing"
        checks["settings_draft_a_silent"] = len(a_calls) == 0
        checks["settings_draft_window_stays"] = bool(
            closed is None or not closed.is_set()
        )
        retained = driver.eval_json(
            """JSON.stringify((() => {
              const root = document.querySelector('[data-d1="settings-profile-name"]');
              const el = root && (root.tagName === 'INPUT' ? root : root.querySelector('input'));
              return {
                value: el ? el.value : null,
                draft: window.__d1Settings.draftActive(),
                view: window.__d1App.view(),
                locked: window.__d1App.closeState().locked,
                final: window.__d1App.closeState().finalAllowed,
                posts: window.__configPosts ?? [],
              };
            })())"""
        )
        checks["settings_draft_input_retained"] = retained["value"] == new_name
        checks["settings_draft_stays_on_settings"] = retained["view"] == "settings"
        checks["settings_draft_page_unlocked"] = bool(
            retained["locked"] is False and retained["final"] is False
        )
        checks["settings_draft_no_post_after_deny"] = retained["posts"] == []
        # The user explicitly cancels the draft through the real control.
        driver.eval(
            """(() => {
              const button = document.querySelector('[data-d1="cancel-draft"]');
              if (!button) throw new Error('no cancel-draft control');
              button.click();
              return true;
            })()"""
        )
        driver.wait_until(
            "window.__d1Settings.draftActive() === false",
            what="settings-draft 草稿取消后 clean",
            timeout=15,
        )
        # The next close (clean settings, no draft) really closes.
        coordinator._timeout_seconds = 10.0
        window.destroy()
        deadline = time.time() + 60
        while time.time() < deadline:
            if any(
                call["id"] not in (request_a, request_b) and call["allow"]
                for call in complete_calls
            ):
                break
            time.sleep(0.05)
        if closed is not None:
            closed.wait(15)
        time.sleep(1.0)
        request_c = next(
            (
                call["id"]
                for call in complete_calls
                if call["id"] not in (request_a, request_b)
            ),
            None,
        )
        checks["settings_draft_retry_closes"] = bool(
            request_c
            and any(
                call["id"] == request_c and call["allow"] is True
                for call in complete_calls
            )
            and coordinator.state(request_c) == "closing"
            and (closed is None or closed.is_set())
        )
        summary["settings_draft"].update(
            {
                "retained": retained,
                "request_c": request_c,
                "complete_calls": list(complete_calls),
                "actual_window_closed_after_retry": bool(
                    closed is not None and closed.is_set()
                ),
            }
        )
        summary["settings_draft_audited"] = True
    finally:
        gate.set()
        coordinator._timeout_seconds = original_timeout
        coordinator.complete = real_complete  # type: ignore[method-assign]
        host_api.get_close_state = real_state  # type: ignore[method-assign]
        host_api._notify_close_aborted = real_notify_aborted  # type: ignore[attr-defined]


def drive_clean_ime_close(driver, args, summary, checks) -> None:

    """Close the window while a clean page has an active IME composition.

    The composition ends on a page-side timer shortly after the real close
    request (driven by the caller's finally), so the leave save must wait for
    the final text, persist it and only then allow the destruction. The
    database check runs after the window closed.
    """
    driver.wait_until(
        "window.__d1Editor.phase() === 'ready' && window.__d1Editor.dirty() === false",
        what="fix3 关窗组合前 clean",
        timeout=30,
    )
    plan_id = driver.eval("window.__d1Editor.planId()")
    version_before = driver.eval("window.__d1Editor.version()")
    driver.eval(
        """(() => {
          const list = [...document.querySelectorAll('textarea')];
          const el = list.find((t) => (t.placeholder || '').includes('原始教案'))
            || list[list.length - 1];
          if (!el) { throw new Error('no textarea found'); }
          window.__imeCloseElement = el;
          el.focus();
          el.dispatchEvent(new CompositionEvent('compositionstart', { bubbles: true }));
          const setter = Object.getOwnPropertyDescriptor(
            window.HTMLTextAreaElement.prototype, 'value').set;
          setter.call(el, '关窗前组合文字');
          el.dispatchEvent(new Event('input', { bubbles: true }));
          window.__imeCloseEnded = false;
          window.setTimeout(() => {
            setter.call(el, '关窗前组合最终文字');
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new CompositionEvent(
              'compositionend', { bubbles: true, data: '最终文字' }));
            window.__imeCloseEnded = true;
          }, 2500);
          return true;
        })()"""
    )
    driver.wait_until(
        "window.__d1Editor.composing() === true && window.__d1Editor.dirty() === false",
        what="fix3 关窗组合进行中且页面看似 clean",
        timeout=15,
    )
    summary["ime_close_plan_id"] = plan_id
    summary["ime_close_version_before"] = version_before
    summary["ime_close_expected_raw"] = "关窗前组合最终文字"
    checks["fix3_ime_close_clean_during_composition"] = True
    # The caller's finally triggers the real close; the page-side timer ends
    # the composition and the leave save persists the final text.


def _verify_late_input_close(summary: dict) -> None:
    """Post-close database check for the late-input phase (R17 §15.2): the
    retry close must have saved the kept new input as the next content
    version, with the input never having been lost to the first close."""
    import sqlite3

    checks = summary.setdefault("checks", {})
    info = summary.get("late_input") or {}
    db_path = summary.get("db_path")
    plan_id = info.get("plan_id")
    expected_raw = info.get("expected_raw")
    version_before = info.get("version_before")
    if not (db_path and plan_id and expected_raw is not None):
        checks["late_input_saved_after_retry"] = False
        return
    try:
        connection = sqlite3.connect(db_path, timeout=10)
        try:
            row = connection.execute(
                "SELECT c.raw_lesson_plan, c.version "
                "FROM local_daily_plan_contents c JOIN local_daily_plans p "
                "ON p.id = c.daily_plan_id AND p.current_content_id = c.id "
                "WHERE p.id = ?",
                (plan_id,),
            ).fetchone()
        finally:
            connection.close()
        checks["late_input_saved_after_retry"] = bool(
            row
            and row[0] == expected_raw
            and row[1] == (version_before or 0) + 1
        )
    except Exception as exc:  # noqa: BLE001
        summary["late_input_db_error"] = str(exc)
        checks["late_input_saved_after_retry"] = False


def _verify_settings_draft_close(summary: dict) -> None:
    """Post-close database check for the settings-draft phase (R17 §16.3):
    the draft must have been explicitly cancelled, never applied or saved by
    the close; the retry close leaves profile/configuration unchanged."""
    import sqlite3

    checks = summary.setdefault("checks", {})
    info = summary.get("settings_draft") or {}
    db_path = summary.get("db_path")
    name_before = info.get("name_before")
    version_before = info.get("config_version_before")
    ops_before = info.get("config_ops_before")
    if not (db_path and name_before is not None and version_before is not None):
        checks["settings_draft_profile_unchanged"] = False
        checks["settings_draft_config_version_unchanged"] = False
        return
    try:
        connection = sqlite3.connect(
            f"file:{Path(db_path).as_posix()}?mode=ro", uri=True, timeout=10
        )
        try:
            row = connection.execute(
                "SELECT display_name FROM local_profile"
            ).fetchone()
            config = connection.execute(
                "SELECT config_version FROM local_settings"
            ).fetchone()
            ops = connection.execute(
                "SELECT count(*) FROM local_config_operations"
            ).fetchone()
        finally:
            connection.close()
        checks["settings_draft_profile_unchanged"] = bool(
            row and row[0] == name_before
        )
        checks["settings_draft_config_version_unchanged"] = bool(
            config and config[0] == version_before
        )
        checks["settings_draft_no_config_operation_added"] = bool(
            ops_before is not None and ops and ops[0] == ops_before
        )
    except Exception as exc:  # noqa: BLE001
        summary["settings_draft_db_error"] = str(exc)
        checks["settings_draft_profile_unchanged"] = False
        checks["settings_draft_config_version_unchanged"] = False
        checks["settings_draft_no_config_operation_added"] = False


def _verify_clean_ime_close(summary: dict) -> None:
    """Post-close database check for the clean-IME close phase."""
    import sqlite3

    checks = summary.setdefault("checks", {})
    db_path = summary.get("db_path")
    plan_id = summary.get("ime_close_plan_id")
    expected_raw = summary.get("ime_close_expected_raw")
    version_before = summary.get("ime_close_version_before")
    if not (db_path and plan_id and expected_raw is not None):
        checks["fix3_ime_close_saved"] = False
        return
    try:
        connection = sqlite3.connect(db_path, timeout=10)
        try:
            row = connection.execute(
                "SELECT c.raw_lesson_plan, c.version "
                "FROM local_daily_plan_contents c JOIN local_daily_plans p "
                "ON p.id = c.daily_plan_id AND p.current_content_id = c.id "
                "WHERE p.id = ?",
                (plan_id,),
            ).fetchone()
        finally:
            connection.close()
        checks["fix3_ime_close_saved"] = bool(
            row
            and row[0] == expected_raw
            and row[1] == (version_before or 0) + 1
        )
    except Exception as exc:  # noqa: BLE001
        summary["fix3_ime_close_db_error"] = str(exc)
        checks["fix3_ime_close_saved"] = False


def _pe_subsystem(path) -> int | None:
    """PE OptionalHeader.Subsystem (2 = GUI/windows, 3 = console)."""
    import struct

    try:
        with open(path, "rb") as handle:
            data = handle.read(0x400)
    except OSError:
        return None
    if len(data) < 0x40 or data[:2] != b"MZ":
        return None
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    if data[e_lfanew : e_lfanew + 4] != b"PE\0\0" or e_lfanew + 24 + 0x46 > len(data):
        return None
    return struct.unpack_from("<H", data, e_lfanew + 24 + 0x44)[0]


def _has_console_window() -> bool:
    """True only when this process is actually attached to a console window."""
    try:
        import ctypes

        return int(ctypes.WinDLL("kernel32", use_last_error=True).GetConsoleWindow()) != 0
    except Exception:  # noqa: BLE001
        return False


def _write_summary(summary: dict, out: str | None) -> None:
    text = json.dumps(summary, ensure_ascii=False, indent=2)
    if out:
        Path(out).write_text(text, encoding="utf-8")
        return
    stream = getattr(sys, "stdout", None)
    if stream is not None:
        try:
            print(text)
        except Exception:
            pass


def _bundle_rows_match_manifest(rows, manifest) -> bool:
    """Exact package-to-DB bundle equality, including revision and hash.

    The resource self-check must accept the current three tasks at r1+r2 (six
    rows) and reject a missing row, an unknown revision, a duplicate, or a hash
    mismatch. Comparing only task_type names would silently accept r1-only or
    duplicate revisions.
    """
    expected = {
        (
            bundle["task_type"],
            bundle["contract_version"],
            bundle["default_revision"],
            bundle["bundle_hash"],
        )
        for bundle in manifest
    }
    actual = {tuple(row) for row in rows}
    return len(rows) == len(expected) and actual == expected


def run_w6_resources(args) -> int:
    """Headless W6 resource / same-origin probe (no window, no console output).

    Runs inside the packaged D2 executable (or a source run) and proves, in one
    phase, that the frozen bundle can really:

    * open the local migrations + prompt-bundle snapshot (single head, no
      duplicate migration on a repeated launch);
    * protect/unprotect a secret through the real Windows DPAPI credential
      store (ACL-checked files) and read it back as ``ready``;
    * create a Windows Job Object, run the real ``multiprocessing`` spawn worker
      and confirm its exit;
    * complete a real TLS + JSON chat completion against the controlled
      provider through the *production* transport (no injected bypass);
    * fingerprint the production code objects it actually executes for the
      same-origin comparison.

    Every fact is written to ``--out``; failures are recorded, never printed
    (a windowed frozen build has no usable console).
    """
    import json as _json
    import socket
    import ssl

    # Validate the dedicated synthetic entry (explicit data root + provider)
    # BEFORE any runtime/lock/prepare and before the broad failure handler.
    _validate_synthetic_entry(args)

    summary: dict = {"checks": {}}
    checks = summary["checks"]
    runtime = None
    executor = None
    try:
        summary["frozen"] = bool(getattr(sys, "frozen", False))
        summary["executable"] = sys.executable
        summary["python_version"] = sys.version
        summary["implementation"] = sys.implementation.name
        # ``sys.stdout`` may be re-attached by ``ensure_console_streams`` in
        # ``main``; the honest no-console evidence is the PE GUI subsystem plus
        # a real ``GetConsoleWindow()`` probe, NOT whether stdio was redirected
        # by the launcher (a redirected pipe is not a console window).
        summary["startup_streams"] = dict(STARTUP_STREAM_STATE)
        summary["stdout_none"] = sys.stdout is None
        summary["stderr_none"] = sys.stderr is None
        summary["gil_disabled"] = bool(getattr(sys, "_is_gil_enabled", lambda: True)() is False)
        summary["pe_subsystem"] = _pe_subsystem(sys.executable)
        summary["has_console_window"] = _has_console_window()
        checks["frozen_entry"] = bool(getattr(sys, "frozen", False))
        checks["no_console_when_frozen"] = (not summary["frozen"]) or (
            summary["pe_subsystem"] == 2 and summary["has_console_window"] is False
        )

        # --- migrations + prompt snapshot ---------------------------------
        from app.local import (
            ai_config_service,
            ai_task_service,
            daily_plan_service,
            profile_service,
        )
        from app.local.normalize import normalize_initialization
        from app.local.prompt_bundles import PROMPT_BUNDLE_MANIFEST
        from app.local.runtime import LocalRuntime

        os.environ["KGM_LOCAL_DATA_DIR"] = str(Path(args.data).resolve())
        runtime = LocalRuntime(args.data)
        inspection = runtime.prepare()
        summary["db_path"] = str(runtime.db_path)
        summary["data_dir"] = str(runtime.data_dir)
        summary["schema_state"] = getattr(inspection, "state", None)
        summary["schema_revision"] = getattr(inspection, "current_revision", None)
        summary["prompt_sync_error"] = runtime.prompt_sync_error

        session = runtime.session()
        try:
            from sqlalchemy import text

            revisions = [
                row[0]
                for row in session.execute(
                    text("SELECT version_num FROM local_alembic_version")
                ).fetchall()
            ]
            integrity = session.execute(text("PRAGMA integrity_check")).scalar()
            fk_rows = session.execute(text("PRAGMA foreign_key_check")).fetchall()
            bundles = [
                tuple(row)
                for row in session.execute(
                    text(
                        "SELECT task_type, contract_version, default_revision, bundle_hash "
                        "FROM local_prompt_bundles "
                        "ORDER BY task_type, contract_version, default_revision"
                    )
                ).fetchall()
            ]
            summary["migration_rows"] = revisions
            summary["migration_single_head"] = len(revisions) == 1
            summary["integrity"] = integrity
            summary["foreign_key_violations"] = len(fk_rows)
            summary["prompt_bundle_rows"] = [list(row) for row in bundles]
            summary["prompt_bundle_tasks"] = [row[0] for row in bundles]
            checks["migration_single_head"] = len(revisions) == 1
            checks["integrity_ok"] = integrity == "ok"
            checks["foreign_keys_ok"] = not fk_rows
            checks["prompt_bundles_present"] = _bundle_rows_match_manifest(
                bundles, PROMPT_BUNDLE_MANIFEST
            )
            checks["prompt_sync_ok"] = runtime.prompt_sync_error is None
        finally:
            session.close()

        # --- cryptography (used by the credential store) ------------------
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM

            key = os.urandom(32)
            nonce = os.urandom(12)
            blob = AESGCM(key).encrypt(nonce, b"kgm-d2-w6", None)
            checks["cryptography_aesgcm"] = (
                AESGCM(key).decrypt(nonce, blob, None) == b"kgm-d2-w6"
            )
        except Exception:  # noqa: BLE001
            checks["cryptography_aesgcm"] = False

        # --- DPAPI credential store (real save + read back) ----------------
        summary["credential_root"] = str(runtime.credential_root)
        try:
            session = runtime.session()
            try:
                profile_service.initialize(
                    session,
                    normalize_initialization(
                        request_id="66666666-6666-4666-8666-666666666666",
                        display_name="W6资源教师",
                        class_name="W6中一班",
                        grade="middle",
                        term_name="2026 年秋季学期",
                        start_date="2026-09-01",
                        end_date="2026-12-31",
                        school_name="W6园所",
                    ),
                )
                session.commit()
                ai_config_service.patch_config(
                    session,
                    expected_ai_config_version=0,
                    base_url="https://api.example.com/v1",
                    model="w6-resource-model",
                    secret="w6-resource-secret",
                    secret_provided=True,
                    request_id="77777777-7777-4777-8777-777777777777",
                    credential_root=runtime.credential_root,
                )
                config = ai_config_service.get_config(
                    session, credential_root=runtime.credential_root
                )
                if hasattr(config, "to_dict"):
                    config_dict = config.to_dict()
                elif hasattr(config, "model_dump"):
                    config_dict = config.model_dump()
                else:
                    from dataclasses import asdict, is_dataclass

                    config_dict = asdict(config) if is_dataclass(config) else dict(config)
                summary["config_ready"] = bool(config_dict.get("ready"))
                summary["config_reason"] = config_dict.get("reason")
                summary["config_configured"] = bool(config_dict.get("configured"))
                checks["dpapi_config_saved"] = bool(config_dict.get("configured"))
                checks["dpapi_config_ready"] = bool(config_dict.get("ready"))
            finally:
                session.close()
            # A readback of the protected key material proves the DPAPI blob is
            # decryptable by this user (not merely written).
            blobs = list(runtime.credential_root.rglob("*.dpapi"))
            summary["credential_blob_count"] = len(blobs)
            checks["dpapi_blob_present"] = len(blobs) >= 1
        except Exception as exc:  # noqa: BLE001
            summary["dpapi_error"] = type(exc).__name__
            checks["dpapi_config_saved"] = False
            checks["dpapi_config_ready"] = False
            checks["dpapi_blob_present"] = False

        # --- TLS (real handshake with the controlled provider) -------------
        ca_pem = Path(args.synthetic_provider_ca).read_text(encoding="utf-8") if args.synthetic_provider_ca else None
        try:
            if ca_pem:
                context = ssl.create_default_context(cafile=args.synthetic_provider_ca)
                context.check_hostname = True
                raw = socket.create_connection(
                    (args.synthetic_provider_ip, int(args.synthetic_provider_port)), timeout=10
                )
                with context.wrap_socket(raw, server_hostname="api.example.com") as tls:
                    summary["tls_version"] = tls.version()
                    checks["tls_handshake"] = True
            else:
                checks["tls_handshake"] = False
        except Exception as exc:  # noqa: BLE001
            summary["tls_error"] = type(exc).__name__
            checks["tls_handshake"] = False
        checks["tls_context_created"] = ca_pem is not None

        # --- real spawn worker + Job + production transport ---------------
        if args.synthetic_provider_port:
            from app.local.ai_executor import AiExecutor
            from app.local import ai_progress
            import time as _time

            # 1) Create the plan only; the task is registered *after* the
            #    executor is started, so cold-start recovery cannot pause it.
            session = runtime.session()
            try:
                plan, _created = daily_plan_service.create_or_open(
                    session,
                    plan_date=__import__("datetime").date(2026, 9, 3),
                    raw_lesson_plan="W6 资源探针原始教案：一、导入；二、观察；三、比较。",
                )
            finally:
                session.close()

            events: list[str] = []
            worker_pid = {"pid": None}

            def on_event(name, _claim, info=None):
                events.append(name)
                if isinstance(info, dict) and isinstance(info.get("pid"), int):
                    worker_pid["pid"] = info["pid"]

            # 2) Start the executor first (no pre-existing task to pause).
            executor = AiExecutor(
                runtime,
                synthetic_transport=_synthetic_transport_from_args(args),
                on_event=on_event,
            )
            started = executor.start()
            checks["executor_started"] = bool(started)

            # 3) Register the task now that the coordinator is running. A unique
            #    request_id per launch means a repeated resource launch really
            #    creates (and spawns for) a new task, never a receipt read-back.
            session = runtime.session()
            try:
                task, _made = ai_task_service.create_task(
                    session,
                    plan_id=plan["id"],
                    task_type="daily_lesson_split",
                    expected_content_version=plan["current_content_version"],
                    target_grade="middle",
                    request_id=str(__import__("uuid").uuid4()),
                )
            finally:
                session.close()
            executor.notify()

            deadline = _time.monotonic() + 90
            status = None
            stream_phases: set[str] = set()
            stream_reasoning = 0
            stream_last_phase = None
            while _time.monotonic() < deadline:
                session = runtime.session()
                execution_id = None
                try:
                    from app.local.models import LocalAITask

                    task_row = session.get(LocalAITask, task["id"], populate_existing=True)
                    status = task_row.status if task_row else None
                    execution_id = (
                        task_row.current_execution_id if task_row is not None else None
                    )
                finally:
                    session.close()
                if execution_id:
                    snapshot = ai_progress.snapshot(task["id"], execution_id)
                    if snapshot is not None:
                        if snapshot.get("phase"):
                            stream_phases.add(str(snapshot["phase"]))
                            stream_last_phase = str(snapshot["phase"])
                        reasoning = snapshot.get("reasoning") or ""
                        if reasoning:
                            stream_reasoning = max(stream_reasoning, len(reasoning))
                if status in ("succeeded", "failed", "outcome_unknown", "cancelled", "paused"):
                    break
                _time.sleep(0.05)
            summary["task_status"] = status
            summary["executor_events"] = events
            summary["worker_pid"] = worker_pid["pid"]
            # Display-only streaming evidence from the in-package executor cache.
            # It is metadata (the source-level test proves the "before final"
            # ordering); a non-streaming synthetic provider legitimately leaves
            # this false and the verifier only enforces it with --stream.
            summary["streaming_progress_seen"] = stream_reasoning > 0
            summary["streaming_progress_phases"] = sorted(stream_phases)
            summary["streaming_progress_reasoning_chars"] = stream_reasoning
            summary["streaming_progress_final_phase"] = stream_last_phase
            # Job usage is a real event, not inferred from child_started.
            checks["job_object_used"] = "job_assigned" in events
            checks["spawn_child_ran"] = worker_pid["pid"] is not None
            checks["ai_task_succeeded"] = status == "succeeded"
            confirmed = bool(executor.dispose())
            summary["worker_exit_confirmed"] = confirmed
            checks["worker_exit_confirmed"] = confirmed
            # Only drop the local reference once the worker exit is confirmed;
            # an unconfirmed worker stays owned so the finally block keeps the
            # runtime lock (never release it with a live worker).
            if confirmed:
                executor = None

        # --- same-origin fingerprints -------------------------------------
        if getattr(args, "same_origin_modules", None):
            import d2_same_origin

            names = _json.loads(
                Path(args.same_origin_modules).read_text(encoding="utf-8")
            )
            summary["module_fingerprints"] = {
                name: d2_same_origin.fingerprint_imported_module(name)
                for name in names
            }
            # The frozen entry script runs as ``__main__`` and may not expose a
            # readable code object; this is recorded as metadata only and never
            # forced into the check. The verifier compares the real entry code
            # extracted from the EXE archive instead.
            summary["entry_fingerprint"] = d2_same_origin.fingerprint_imported_module(
                "__main__"
            )
            checks["same_origin_fingerprinted"] = all(
                entry.get("status") == "ok"
                for entry in summary["module_fingerprints"].values()
            )
    except Exception as exc:  # noqa: BLE001 - a probe fault is recorded, not printed
        import traceback

        summary["probe_failure"] = type(exc).__name__
        summary["probe_failure_tail"] = traceback.format_exc().splitlines()[-1][:300]
        summary["ok"] = False
    finally:
        executor_confirmed = True
        if executor is not None:
            try:
                executor_confirmed = bool(executor.dispose())
            except Exception:  # noqa: BLE001
                executor_confirmed = False
        summary["executor_exit_confirmed"] = executor_confirmed
        # The runtime lock is released only once no AI worker may still be
        # running (mirrors the host's unconfirmed-worker rule).
        if runtime is not None and executor_confirmed:
            try:
                runtime.dispose()
                summary["runtime_lock_released"] = True
            except Exception:  # noqa: BLE001
                summary["runtime_lock_released"] = False
        elif runtime is not None:
            summary["runtime_lock_released"] = False
    if summary.get("ok") is not False:
        summary["ok"] = all(value is not False for value in checks.values())
    _write_summary(summary, args.out)
    return 0 if summary.get("ok") else 3


def drive_w5_ui(driver, args, summary, checks, host_api, port) -> None:
    """D2 W5 real WebView2 source-window flow (R10/R11/Q6 close choice).

    A controlled synthetic provider answers the three task types through the
    real executor + Windows spawn/Job (no external network). The driver covers:
    profile + AI config via the real local API, the three explicit triggers
    with body-save-first, candidate edit/adopt against the real saved version,
    candidate/settings draft leave protection, and the close task choice
    (keep_waiting / stop_and_exit) including a real abort of the first request.
    """
    token = getattr(host_api, "_launch_token", "")
    if not token:
        raise RuntimeError("w5-ui: host token missing")

    def http(method, path, body=None):
        return _http_json(port, token, method, path, body)

    def step(name, fn):
        try:
            fn()
            checks[name] = True
        except Exception as exc:  # noqa: BLE001 - record and continue
            checks[name] = False
            summary.setdefault("w5_errors", {})[name] = str(exc)
            _startup_log(f"w5 step failed {name}: {exc}")

    # 1. Page bootstrap + single local profile.
    driver.wait_until(
        "Boolean(window.__d1App && window.__d1App.ready())", what="W5 页面启动", timeout=40
    )
    if driver.eval("window.__d1App.state()") == "uninitialized":
        driver.eval(
            "window.__d1Setup.fill("
            + json.dumps(
                {
                    "display_name": "W5教师",
                    "class_name": "W5中一班",
                    "grade": "middle",
                    "term_name": "W5学期",
                    "start_date": args.term_start,
                    "end_date": args.term_end,
                    "school_name": "W5园所",
                },
                ensure_ascii=False,
            )
            + ")"
        )
        driver.eval("window.__d1Setup.submit()")
        driver.wait_until("window.__d1App.state() === 'ready'", what="W5 初始化", timeout=60)
    checks["w5_initialized"] = True

    # 2. AI configuration through the real local API (format-only, no supplier).
    status, config = http(
        "PATCH",
        "/api/local/ai/config",
        {
            "request_id": "11111111-2222-4333-8444-555555555555",
            "expected_ai_config_version": 0,
            "protocol_id": "chat_completions_v1",
            "base_url": "https://api.example.com/v1",
            "model": "w5-synthetic",
            "secret": "w5-synthetic-secret",
        },
    )
    summary["w5_config_status"] = status
    summary["w5_config_body"] = config
    checks["w5_ai_configured"] = bool(
        status == 200 and isinstance(config, dict) and config.get("configured")
    )

    # 3. Open the editor for the seeded plan date.
    driver.wait_until(
        "Boolean(window.__d1Workbench && typeof window.__d1Workbench.openDate === 'function')",
        what="W5 工作台就绪",
        timeout=30,
    )
    driver.eval(f"window.__d1Workbench.openDate({json.dumps(args.date)})")
    driver.wait_until("window.__d1App.view() === 'editor'", what="W5 进入编辑器", timeout=30)
    driver.wait_until(
        "window.__d1Editor && ['ready','create_confirmation'].includes(window.__d1Editor.phase())",
        what="W5 编辑器就绪",
        timeout=30,
    )
    if driver.eval("window.__d1Editor.phase()") == "create_confirmation":
        driver.eval("window.__d1Editor.confirmCreate()")
        driver.wait_until(
            "window.__d1Editor.phase() === 'ready'", what="W5 创建日计划", timeout=30
        )
    plan_id = driver.eval("window.__d1Editor.planId()")
    summary["w5_plan_id"] = plan_id

    # 4. A close-blocking save failure: force a version conflict, then close;
    #    the page must stay (no allow) and surface the conflict, then recover.
    def close_save_conflict_stays():
        version = driver.eval("window.__d1Editor.version()")
        driver.eval(
            "window.__d1Editor.setText('未保存的冲突输入-必须保留', '冲突反思')"
        )
        driver.wait_until("window.__d1Editor.dirty() === true", what="W5 冲突前变脏", timeout=15)
        status, body = http(
            "PATCH",
            f"/api/daily-plans/{plan_id}",
            {
                "expected_content_version": version,
                "raw_lesson_plan": "服务器抢先保存的原文",
                "adopted_content": {},
            },
        )
        assert status == 200 and isinstance(body, dict), f"forcing conflict failed: {status}"
        new_version = body.get("current_content_version")
        summary["w5_conflict_version"] = new_version
        window = host_api._window()
        window.destroy()
        driver.wait_until(
            "window.__d1App.closeState().locked === false"
            " && window.__d1Editor.phase() === 'conflict'",
            what="W5 保存冲突拒绝关闭",
            timeout=40,
        )
        assert driver.eval("window.__d1App.view()") == "editor", "save conflict left the page"
        # Recover through the reviewed conflict action, then reload the editor.
        driver.eval("window.__d1Editor.discardLocal()")
        driver.wait_until("window.__d1Editor.phase() === 'ready'", what="W5 冲突恢复", timeout=30)
        driver.eval("window.__d1Editor.leaveToCalendar()")
        driver.wait_until("window.__d1App.view() === 'workbench'", what="W5 冲突后返回", timeout=30)
        driver.eval(f"window.__d1Workbench.openDate({json.dumps(args.date)})")
        driver.wait_until(
            "window.__d1App.view() === 'editor' && window.__d1Editor.phase() === 'ready'",
            what="W5 冲突后重载编辑器",
            timeout=30,
        )

    step("w5_close_save_conflict_stays", close_save_conflict_stays)

    # 5. Body save-before-register (R10): an unsaved raw text must be persisted
    #    by the trigger before the task is registered.
    unsaved_raw = "教师尚未保存的原文-必须保留"

    def trigger_split():
        version_before = driver.eval("window.__d1Editor.version()")
        driver.eval(
            "window.__d1Editor.setText("
            + json.dumps(unsaved_raw, ensure_ascii=False)
            + ", "
            + json.dumps("W5 未保存反思", ensure_ascii=False)
            + ")"
        )
        driver.wait_until("window.__d1Editor.dirty() === true", what="W5 正文变脏", timeout=15)
        driver.eval("window.__d1AiTasks.trigger('daily_lesson_split')")
        driver.wait_until(
            "window.__d1Editor.dirty() === false"
            f" && window.__d1Editor.version() === {version_before + 1}",
            what="W5 触发先保存正文",
            timeout=60,
        )
        summary["w5_version_before"] = version_before
        summary["w5_version_after_trigger"] = driver.eval("window.__d1Editor.version()")

    step("w5_trigger_split_saved", trigger_split)

    def split_stream_progress_visible():
        # R08: the controlled split response is delayed, so the real frozen
        # window must show reasoning before the final answer. Assert the DOM,
        # default expansion and collapse/expand, not a backend flag.
        driver.wait_until(
            "Boolean(document.querySelector('[data-d1^=\"ai-progress-text-\"]'))",
            what="W5 流式思考文字",
            timeout=40,
        )
        text = driver.eval(
            "(document.querySelector('[data-d1^=\"ai-progress-text-\"]')||{}).textContent || ''"
        )
        assert "W5 合成思考过程" in text, f"stream reasoning missing: {text!r}"
        phase_text = driver.eval(
            "(document.querySelector('[data-d1^=\"ai-progress-\"]')||{}).textContent || ''"
        )
        assert ("正在思考" in phase_text or "正在生成结果" in phase_text), phase_text
        checks["w5_stream_progress_visible"] = True
        checks["w5_stream_progress_default_expanded"] = True
        checks["w5_stream_progress_phase"] = True
        driver.eval(
            "(document.querySelector('[data-d1^=\"ai-progress-toggle-\"]')||{}).click?.()"
        )
        driver.wait_until(
            "!document.querySelector('[data-d1^=\"ai-progress-text-\"]')",
            what="W5 折叠思考",
            timeout=15,
        )
        checks["w5_stream_progress_collapsed"] = True
        driver.eval(
            "(document.querySelector('[data-d1^=\"ai-progress-toggle-\"]')||{}).click?.()"
        )
        driver.wait_until(
            "Boolean(document.querySelector('[data-d1^=\"ai-progress-text-\"]'))",
            what="W5 展开思考",
            timeout=15,
        )
        checks["w5_stream_progress_re_expanded"] = True

    step("w5_stream_progress", split_stream_progress_visible)

    def split_succeeded_and_raw_preserved():
        driver.wait_until(
            "window.__d1AiTasks.tasks().some(function(t){return t.task_type==='daily_lesson_split'"
            " && t.status==='succeeded' && t.candidate_id})",
            what="W5 拆分候选",
            timeout=90,
        )
        status, plan = http("GET", f"/api/daily-plans/{plan_id}")
        assert status == 200 and isinstance(plan, dict), "plan read failed"
        raw = (plan.get("content") or {}).get("raw_lesson_plan")
        assert raw == unsaved_raw, f"raw not saved first: {raw!r}"
        split_task = next(
            t
            for t in driver.eval("window.__d1AiTasks.tasks()")
            if t.get("task_type") == "daily_lesson_split"
        )
        summary["w5_split_candidate_id"] = split_task.get("candidate_id")
        return split_task.get("candidate_id")

    candidate_id = None

    def run_split_steps():
        nonlocal candidate_id
        candidate_id = split_succeeded_and_raw_preserved()
        driver.eval(f"window.__d1Editor.openCandidate({json.dumps(candidate_id)})")
        driver.wait_until(
            "window.__d1Candidate && window.__d1Candidate.phase() === 'ready'",
            what="W5 候选就绪",
            timeout=30,
        )
        assert "group_activity" in (driver.eval("window.__d1Candidate.selected()") or []), (
            "split candidate target not selected"
        )
        driver.eval("window.__d1Candidate.setSplitField('process', '教师预览修改后的过程')")
        driver.eval("window.__d1Candidate.requestPreview()")
        driver.wait_until(
            "Boolean(window.__d1Candidate.preview())", what="W5 候选预览", timeout=30
        )
        driver.eval("window.__d1Candidate.adopt()")
        driver.wait_until(
            "Boolean(window.__d1Candidate.resultText())", what="W5 采用完成", timeout=60
        )
        status, plan = http("GET", f"/api/daily-plans/{plan_id}")
        assert status == 200, "plan read failed after adopt"
        content = plan.get("content") or {}
        group = (content.get("adopted_content") or {}).get("group_activity") or {}
        assert group.get("process") == "教师预览修改后的过程", "adopted process missing"
        assert (content.get("raw_lesson_plan")) == unsaved_raw, "raw changed by adopt"
        assert content.get("split_baseline") is not None, "split baseline missing"
        summary["w5_adopted_version"] = plan.get("current_content_version")

    step("w5_split_edit_adopt", run_split_steps)

    # 5. Candidate draft blocks leaving (component + coordinator in the real page).
    def candidate_draft_blocks_leave():
        driver.eval(f"window.__d1Editor.openCandidate({json.dumps(candidate_id)})")
        driver.wait_until(
            "window.__d1Candidate && window.__d1Candidate.phase() === 'ready'",
            what="W5 候选再次就绪",
            timeout=30,
        )
        driver.eval("window.__d1Candidate.setSplitField('theme', '未采用的草稿主题')")
        driver.wait_until(
            "window.__d1Candidate.dirty() === true", what="W5 候选变脏", timeout=15
        )
        driver.eval("window.__d1Editor.leaveToCalendar()")
        time.sleep(1.5)
        assert driver.eval("window.__d1App.view()") == "editor", "candidate draft left the page"
        assert driver.eval("window.__d1Candidate.dirty()") is True
        driver.eval("window.__d1Candidate.cancelEdit()")
        driver.wait_until(
            "window.__d1App.view() === 'editor'", what="W5 取消候选编辑仍在编辑器", timeout=15
        )

    step("w5_candidate_draft_blocks_leave", candidate_draft_blocks_leave)

    # 6. Other-activities trigger (a second capability) succeeds.
    def trigger_other():
        driver.eval("window.__d1AiTasks.trigger('daily_other_activities')")
        driver.wait_until(
            "window.__d1AiTasks.tasks().some(function(t){return"
            " t.task_type==='daily_other_activities' && t.status==='succeeded'"
            " && t.candidate_id})",
            what="W5 其他活动候选",
            timeout=90,
        )

    step("w5_trigger_other_activities", trigger_other)

    # 7. Settings draft blocks leaving; explicit discard restores.
    def settings_draft_blocks_leave():
        driver.eval("window.__d1Editor.goSettings()")
        driver.wait_until("window.__d1App.view() === 'settings'", what="W5 进入设置", timeout=30)
        driver.wait_until("Boolean(window.__d1AiSettings)", what="W5 AI 设置就绪", timeout=30)
        driver.eval(
            "window.__d1AiSettings.setConfigDraft('https://api.example.com/v1',"
            " 'w5-changed-model', '')"
        )
        driver.wait_until(
            "window.__d1AiSettings.draftActive() === true", what="W5 设置草稿", timeout=15
        )
        driver.eval("window.__d1Settings.back()")
        time.sleep(1.0)
        assert driver.eval("window.__d1App.view()") == "settings", "settings draft left the page"
        driver.eval("window.__d1AiSettings.discardDrafts()")
        driver.wait_until(
            "window.__d1AiSettings.draftActive() === false", what="W5 设置草稿取消", timeout=15
        )
        driver.eval("window.__d1Settings.back()")
        driver.wait_until(
            "window.__d1App.view() === 'workbench'", what="W5 返回工作台", timeout=30
        )
        driver.eval(f"window.__d1Workbench.openDate({json.dumps(args.date)})")
        driver.wait_until("window.__d1App.view() === 'editor'", what="W5 回到编辑器", timeout=30)
        driver.wait_until(
            "window.__d1Editor.phase() === 'ready'", what="W5 编辑器就绪（关闭前）", timeout=30
        )

    step("w5_settings_draft_blocks_leave", settings_draft_blocks_leave)

    # 8. A live task (the provider keeps the adapt request open) + close choice.
    def start_live_task():
        driver.eval("window.__d1AiTasks.trigger('daily_process_adapt')")
        driver.wait_until(
            "window.__d1AiTasks.liveCount() >= 1", what="W5 活跃任务", timeout=60
        )
        # Do not infer supplier receipt from pending/claimed/dispatching. The
        # test provider's adapt response first emits this unique reasoning, so a
        # visible text node is real evidence that the request reached it.
        driver.wait_until(
            "Array.from(document.querySelectorAll('[data-d1^=\"ai-progress-text-\"]'))"
            ".some(function(el){return (el.textContent || '').indexOf('W5 适配准备') >= 0})",
            what="W5 适配请求已真实返回思考",
            timeout=60,
        )
        checks["w5_live_task_received"] = True

    step("w5_live_task", start_live_task)

    def close_choice_keep_waiting():
        window = host_api._window()
        window.destroy()
        driver.wait_until(
            "window.__d1App.closeState().taskChoiceVisible === true",
            what="W5 关闭选择弹窗",
            timeout=30,
        )
        driver.eval("window.__d1AppCloseChoice.resolve('keep_waiting')")
        driver.wait_until(
            "window.__d1App.closeState().locked === false",
            what="W5 继续等待解除锁定",
            timeout=30,
        )
        assert driver.eval("window.__d1App.view()") == "editor", "keep_waiting left the page"

    step("w5_close_keep_waiting", close_choice_keep_waiting)

    # 9. An aborted old close must retire its dialog without answering it (R13).
    def close_old_request_aborted():
        window = host_api._window()
        window.destroy()
        driver.wait_until(
            "window.__d1App.closeState().taskChoiceVisible === true",
            what="W5 第二次关闭选择",
            timeout=30,
        )
        coordinator = host_api._close_coordinator
        request_id = coordinator._current_id
        summary["w5_aborted_request"] = request_id
        coordinator._on_timeout(request_id)
        driver.wait_until(
            "window.__d1App.closeState().taskChoiceVisible === false",
            what="W5 旧请求选择被撤销",
            timeout=30,
        )
        time.sleep(0.5)
        assert driver.eval("window.__d1App.closeState().finalAllowed") is False, (
            "aborted request was answered with an allow"
        )
        assert driver.eval("window.__d1App.view()") == "editor", "abort left the page"

    step("w5_close_old_request_aborted", close_old_request_aborted)

    # 10. Stop waiting and exit: resolve the choice and hand the confirmation to
    #     the post-close host/DB verification — never poll page JS after the
    #     window is destroyed.
    def close_stop_and_exit():
        window = host_api._window()
        window.destroy()
        driver.wait_until(
            "window.__d1App.closeState().taskChoiceVisible === true",
            what="W5 第三次关闭选择",
            timeout=30,
        )
        request_id = driver.eval("window.__d1App.closeState().taskChoiceId")
        summary["w5_stop_exit_request"] = request_id
        driver.eval("window.__d1AppCloseChoice.resolve('stop_and_exit')")
        summary["w5_stop_exit_choice_resolved"] = True

    step("w5_close_stop_and_exit_choice", close_stop_and_exit)


def _verify_w5_close(summary: dict, runtime, host_api=None) -> None:
    """Post-close W5 confirmation from host/process/database (window gone).

    The *adapt* request was actually received by the controlled provider and
    then stopped by the host drain, so the persisted classification must be
    ``outcome_unknown`` (sent) — never a silent success. ``paused`` is only
    valid for the provably-not-sent branch, and the cross-assert lives in the
    verifier. The window itself is already closed here (this runs after
    ``webview.start`` returned).
    """
    checks = summary.setdefault("checks", {})
    try:
        from sqlalchemy import text

        session = runtime.session()
        try:
            row = session.execute(
                text(
                    "SELECT status, reason FROM local_ai_tasks "
                    "WHERE task_type = 'daily_process_adapt' "
                    "ORDER BY created_at DESC LIMIT 1"
                )
            ).fetchone()
            status = row[0] if row else None
            reason = row[1] if row else None
            summary["w5_adapt_final_status"] = status
            summary["w5_adapt_final_reason"] = reason
            checks["w5_adapt_final_unknown_or_paused"] = status in (
                "outcome_unknown",
                "paused",
            )
            open_attempts = session.execute(
                text("SELECT count(*) FROM local_ai_attempts WHERE ended_at IS NULL")
            ).scalar()
            checks["w5_no_open_attempt"] = int(open_attempts or 0) == 0
        finally:
            session.close()
    except Exception as exc:  # noqa: BLE001
        checks["w5_adapt_final_unknown_or_paused"] = False
        summary["w5_verify_error"] = str(exc)
    checks["w5_window_closed"] = True
    request_id = summary.get("w5_stop_exit_request")
    host_state = None
    if host_api is not None and request_id:
        try:
            host_state = host_api._close_coordinator.state(request_id)
        except Exception:  # noqa: BLE001
            host_state = None
    summary["w5_host_close_state"] = host_state
    checks["w5_host_close_state"] = host_state in ("closing",)
    checks["w5_close_stop_and_exit"] = bool(
        summary.get("w5_stop_exit_choice_resolved")
        and summary.get("w5_adapt_final_status") == "outcome_unknown"
        and checks["w5_host_close_state"]
    )


def drive_w6_ui(driver, args, summary, checks, host_api, port) -> None:
    """D2 W6 G14 real-window closed loop (source or packaged D2 executable).

    One window: split -> candidate preview with an edited process -> adopt ->
    age-appropriate adapt -> adopt -> teacher manual process edit -> save ->
    single-day and merged native DOCX export. The controlled provider answers
    split/adapt/other through the real executor + Windows spawn/Job (never an
    external network). Baseline (raw model process) and the redline are checked
    by the verifier from the exported files and the real local API.
    """
    token = getattr(host_api, "_launch_token", "")
    if not token:
        raise RuntimeError("w6-ui: host token missing")

    def http(method, path, body=None):
        return _http_json(port, token, method, path, body)

    def step(name, fn):
        try:
            fn()
            checks[name] = True
        except Exception as exc:  # noqa: BLE001 - record and continue
            checks[name] = False
            summary.setdefault("w6_errors", {})[name] = str(exc)
            _startup_log(f"w6 step failed {name}: {exc}")

    driver.wait_until(
        "Boolean(window.__d1App && window.__d1App.ready())", what="W6 页面启动", timeout=40
    )
    if driver.eval("window.__d1App.state()") == "uninitialized":
        driver.eval(
            "window.__d1Setup.fill("
            + json.dumps(
                {
                    "display_name": "W6教师",
                    "class_name": "W6中一班",
                    "grade": "middle",
                    "term_name": "W6学期",
                    "start_date": args.term_start,
                    "end_date": args.term_end,
                    "school_name": "W6园所",
                },
                ensure_ascii=False,
            )
            + ")"
        )
        driver.eval("window.__d1Setup.submit()")
        driver.wait_until("window.__d1App.state() === 'ready'", what="W6 初始化", timeout=60)
    checks["w6_initialized"] = True

    status, config = http(
        "PATCH",
        "/api/local/ai/config",
        {
            "request_id": "aaaa1111-2222-4333-8444-555566667777",
            "expected_ai_config_version": 0,
            "protocol_id": "chat_completions_v1",
            "base_url": "https://api.example.com/v1",
            "model": "w6-synthetic",
            "secret": "w6-synthetic-secret",
        },
    )
    summary["w6_config_status"] = status
    checks["w6_ai_configured"] = bool(
        status == 200 and isinstance(config, dict) and config.get("configured")
    )

    driver.wait_until(
        "Boolean(window.__d1Workbench && typeof window.__d1Workbench.openDate === 'function')",
        what="W6 工作台就绪",
        timeout=30,
    )
    driver.eval(f"window.__d1Workbench.openDate({json.dumps(args.date)})")
    driver.wait_until("window.__d1App.view() === 'editor'", what="W6 进入编辑器", timeout=30)
    driver.wait_until(
        "window.__d1Editor && ['ready','create_confirmation'].includes(window.__d1Editor.phase())",
        what="W6 编辑器就绪",
        timeout=30,
    )
    if driver.eval("window.__d1Editor.phase()") == "create_confirmation":
        driver.eval("window.__d1Editor.confirmCreate()")
        driver.wait_until(
            "window.__d1Editor.phase() === 'ready'", what="W6 创建日计划", timeout=30
        )
    plan_id = driver.eval("window.__d1Editor.planId()")
    summary["w6_plan_id"] = plan_id
    raw_text = "W6拆分用原文：一、导入\n二、观察\n三、比较"

    def split_flow():
        driver.eval(
            "window.__d1Editor.setText("
            + json.dumps(raw_text, ensure_ascii=False)
            + ", "
            + json.dumps("W6反思", ensure_ascii=False)
            + ")"
        )
        driver.wait_until("window.__d1Editor.dirty() === true", what="W6 正文变脏", timeout=15)
        version_before = driver.eval("window.__d1Editor.version()")
        driver.eval("window.__d1AiTasks.trigger('daily_lesson_split')")
        driver.wait_until(
            "window.__d1Editor.dirty() === false"
            f" && window.__d1Editor.version() === {version_before + 1}",
            what="W6 触发先保存正文",
            timeout=60,
        )
        driver.wait_until(
            "window.__d1AiTasks.tasks().some(function(t){return t.task_type==='daily_lesson_split'"
            " && t.status==='succeeded' && t.candidate_id})",
            what="W6 拆分候选",
            timeout=90,
        )
        task = next(
            t
            for t in driver.eval("window.__d1AiTasks.tasks()")
            if t.get("task_type") == "daily_lesson_split"
        )
        candidate_id = task.get("candidate_id")
        summary["w6_split_candidate_id"] = candidate_id
        driver.eval(f"window.__d1Editor.openCandidate({json.dumps(candidate_id)})")
        driver.wait_until(
            "window.__d1Candidate && window.__d1Candidate.phase() === 'ready'",
            what="W6 拆分候选就绪",
            timeout=30,
        )
        driver.eval("window.__d1Candidate.setSplitField('process', " + json.dumps(W6_PREVIEW_PROCESS, ensure_ascii=False) + ")")
        driver.eval("window.__d1Candidate.requestPreview()")
        driver.wait_until("Boolean(window.__d1Candidate.preview())", what="W6 拆分预览", timeout=30)
        driver.eval("window.__d1Candidate.adopt()")
        driver.wait_until(
            "Boolean(window.__d1Candidate.resultText())", what="W6 拆分采用", timeout=60
        )
        status, plan = http("GET", f"/api/daily-plans/{plan_id}")
        assert status == 200, "plan read failed"
        content = plan.get("content") or {}
        group = (content.get("adopted_content") or {}).get("group_activity") or {}
        assert group.get("process") == W6_PREVIEW_PROCESS, "adopted split process missing"
        baseline = content.get("split_baseline") or {}
        summary["w6_split_baseline"] = baseline
        summary["w6_adopt_split_version"] = plan.get("current_content_version")

    step("w6_split_preview_edit_adopt", split_flow)

    def adapt_flow():
        driver.wait_until(
            "['ready'].includes(window.__d1Editor.phase())",
            what="W6 拆分采用后编辑器就绪",
            timeout=30,
        )
        driver.eval("window.__d1AiTasks.trigger('daily_process_adapt')")
        driver.wait_until(
            "window.__d1AiTasks.tasks().some(function(t){return t.task_type==='daily_process_adapt'"
            " && t.status==='succeeded' && t.candidate_id})",
            what="W6 适龄候选",
            timeout=90,
        )
        task = next(
            t
            for t in driver.eval("window.__d1AiTasks.tasks()")
            if t.get("task_type") == "daily_process_adapt"
        )
        candidate_id = task.get("candidate_id")
        driver.eval(f"window.__d1Editor.openCandidate({json.dumps(candidate_id)})")
        driver.wait_until(
            "window.__d1Candidate && window.__d1Candidate.phase() === 'ready'",
            what="W6 适龄候选就绪",
            timeout=30,
        )
        driver.eval("window.__d1Candidate.setAdaptProcess(" + json.dumps(W6_ADAPT_PROCESS, ensure_ascii=False) + ")")
        driver.eval("window.__d1Candidate.requestPreview()")
        driver.wait_until("Boolean(window.__d1Candidate.preview())", what="W6 适龄预览", timeout=30)
        driver.eval("window.__d1Candidate.adopt()")
        driver.wait_until(
            "Boolean(window.__d1Candidate.resultText())", what="W6 适龄采用", timeout=60
        )
        status, plan = http("GET", f"/api/daily-plans/{plan_id}")
        content = (plan or {}).get("content") or {}
        group = (content.get("adopted_content") or {}).get("group_activity") or {}
        assert group.get("process") == W6_ADAPT_PROCESS, "adapt process not adopted"
        assert (content.get("split_baseline") or {}) == summary["w6_split_baseline"], (
            "baseline drifted across adapt"
        )
        summary["w6_adopt_adapt_version"] = plan.get("current_content_version")

    step("w6_adapt_adopt", adapt_flow)

    def manual_edit_save():
        # Teacher edits the process again through the real form and saves. The
        # final text keeps the model baseline's unchanged paragraphs and adds a
        # replacement + an insertion so the Word redline can prove the baseline
        # did not drift to the preview or adapt value.
        set_result = driver.eval(
            "(() => {"
            " const label = Array.from(document.querySelectorAll('label'))"
            "   .find((el) => el.textContent.trim() === '过程');"
            " if (!label) return 'no-label';"
            " const field = label.closest('.field') || label.parentElement;"
            " const input = field && field.querySelector('textarea, input');"
            " if (!input) return 'no-input';"
            " input.value = " + json.dumps(W6_FINAL_PROCESS, ensure_ascii=False) + ";"
            " input.dispatchEvent(new Event('input', { bubbles: true }));"
            " return 'ok';"
            " })()"
        )
        assert set_result == "ok", f"process input not found: {set_result}"
        driver.wait_until("window.__d1Editor.dirty() === true", what="W6 手工改动变脏", timeout=15)
        version_before = driver.eval("window.__d1Editor.version()")
        driver.eval("window.__d1Editor.save()")
        driver.wait_until(
            "window.__d1Editor.phase() === 'ready' && window.__d1Editor.dirty() === false",
            what="W6 手工保存",
            timeout=60,
        )
        assert driver.eval("window.__d1Editor.version()") == version_before + 1, "manual save no version"
        status, plan = http("GET", f"/api/daily-plans/{plan_id}")
        content = (plan or {}).get("content") or {}
        group = (content.get("adopted_content") or {}).get("group_activity") or {}
        assert group.get("process") == W6_FINAL_PROCESS, "manual process not saved"
        assert (content.get("split_baseline") or {}) == summary["w6_split_baseline"], (
            "baseline drifted across manual save"
        )
        summary["w6_final_process"] = group.get("process")
        summary["w6_manual_save_version"] = plan.get("current_content_version")

    step("w6_teacher_manual_save", manual_edit_save)

    def export_single():
        before = driver.eval("window.__d1Export.seq()")
        driver.eval("window.__d1Export.setMode('day')")
        driver.eval("window.__d1Export.runConfirmed()")
        terminal = (
            "['saved','canceled','save_failed','generation_failed','export_not_found',"
            "'save_result_unknown'].includes(window.__d1Export.phase())"
        )
        driver.wait_until(
            f"window.__d1Export.seq() > {before} && {terminal}",
            what="W6 单日导出",
            timeout=120,
        )
        phase = driver.eval("window.__d1Export.phase()")
        summary["w6_export_single"] = {
            "phase": phase,
            "filename": driver.eval("window.__d1Export.savedFilename()"),
        }
        assert phase == "saved", f"single export phase {phase}"

    step("w6_export_single_day", export_single)

    def second_plan_and_merged_export():
        driver.eval("window.__d1Editor.leaveToCalendar()")
        driver.wait_until("window.__d1App.view() === 'workbench'", what="W6 返回工作台", timeout=30)
        driver.eval(f"window.__d1Workbench.openDate({json.dumps(args.date2)})")
        driver.wait_until(
            "window.__d1Editor && ['ready','create_confirmation'].includes(window.__d1Editor.phase())",
            what="W6 第二日期编辑器",
            timeout=30,
        )
        if driver.eval("window.__d1Editor.phase()") == "create_confirmation":
            driver.eval("window.__d1Editor.confirmCreate()")
            driver.wait_until(
                "window.__d1Editor.phase() === 'ready'", what="W6 创建第二日计划", timeout=30
            )
        driver.eval(
            "window.__d1Editor.setText('第二日内容 W6', '第二日反思 W6')"
        )
        driver.wait_until("window.__d1Editor.dirty() === true", what="W6 第二日输入", timeout=15)
        driver.eval("window.__d1Editor.save()")
        driver.wait_until(
            "window.__d1Editor.phase() === 'ready' && window.__d1Editor.dirty() === false",
            what="W6 第二日保存",
            timeout=60,
        )
        before = driver.eval("window.__d1Export.seq()")
        driver.eval(
            "window.__d1Export.setCustom("
            + json.dumps(args.date)
            + ", "
            + json.dumps(args.date2)
            + ")"
        )
        driver.eval("window.__d1Export.runConfirmed()")
        terminal = (
            "['saved','canceled','save_failed','generation_failed','export_not_found',"
            "'save_result_unknown'].includes(window.__d1Export.phase())"
        )
        driver.wait_until(
            f"window.__d1Export.seq() > {before} && {terminal}",
            what="W6 合并导出",
            timeout=120,
        )
        phase = driver.eval("window.__d1Export.phase()")
        summary["w6_export_merged"] = {
            "phase": phase,
            "filename": driver.eval("window.__d1Export.savedFilename()"),
        }
        assert phase == "saved", f"merged export phase {phase}"

    step("w6_export_merged_range", second_plan_and_merged_export)

    summary["w6_done"] = True


def drive_w6_ui_verify(driver, args, summary, checks, host_api, port) -> None:
    """W6 restart evidence: reopen the saved plan and export it again.

    Same synthetic data root as ``w6-ui``; proves the adopted baseline and the
    teacher's manual edit survived a restart and that export reads only the
    saved version.
    """
    token = getattr(host_api, "_launch_token", "")
    if not token:
        raise RuntimeError("w6-ui-verify: host token missing")

    def http(method, path, body=None):
        return _http_json(port, token, method, path, body)

    driver.wait_until(
        "Boolean(window.__d1App && window.__d1App.ready())", what="W6 重启页面", timeout=40
    )
    checks["w6v_initialized"] = driver.eval("window.__d1App.state()") == "ready"
    driver.wait_until(
        "Boolean(window.__d1Workbench && typeof window.__d1Workbench.openDate === 'function')",
        what="W6 重启工作台",
        timeout=30,
    )
    driver.eval(f"window.__d1Workbench.openDate({json.dumps(args.date)})")
    driver.wait_until("window.__d1App.view() === 'editor'", what="W6 重启进入编辑器", timeout=30)
    driver.wait_until(
        "window.__d1Editor.phase() === 'ready'", what="W6 重启编辑器就绪", timeout=30
    )
    plan_id = driver.eval("window.__d1Editor.planId()")
    status, plan = http("GET", f"/api/daily-plans/{plan_id}")
    content = (plan or {}).get("content") or {}
    group = (content.get("adopted_content") or {}).get("group_activity") or {}
    summary["w6v_plan_id"] = plan_id
    summary["w6v_version"] = plan.get("current_content_version")
    summary["w6v_process"] = group.get("process")
    summary["w6v_baseline"] = content.get("split_baseline")
    summary["w6v_raw"] = content.get("raw_lesson_plan")
    checks["w6v_process_saved"] = group.get("process") == W6_FINAL_PROCESS
    checks["w6v_baseline_present"] = isinstance(content.get("split_baseline"), dict)
    checks["w6v_baseline_is_model_process"] = (
        (content.get("split_baseline") or {}).get("group_activity_process")
        == W6_MODEL_PROCESS
    )

    before = driver.eval("window.__d1Export.seq()")
    driver.eval("window.__d1Export.setMode('day')")
    driver.eval("window.__d1Export.runConfirmed()")
    terminal = (
        "['saved','canceled','save_failed','generation_failed','export_not_found',"
        "'save_result_unknown'].includes(window.__d1Export.phase())"
    )
    driver.wait_until(
        f"window.__d1Export.seq() > {before} && {terminal}",
        what="W6 重启导出",
        timeout=120,
    )
    phase = driver.eval("window.__d1Export.phase()")
    summary["w6v_export"] = {
        "phase": phase,
        "filename": driver.eval("window.__d1Export.savedFilename()"),
    }
    checks["w6v_export_saved"] = phase == "saved"


def drive_g15_noexec(driver, args, summary, checks, host_api, port) -> None:
    """G15 no-AI degradation in a real window: manual save + native export work.

    The AI capability is unavailable for one of the four branches (no config /
    credential undecryptable / network unavailable / executor start failure);
    reading, editing, saving and the native DOCX export must stay complete and
    the AI state must be readable (never a silent "available").
    """
    token = getattr(host_api, "_launch_token", "")
    if not token:
        raise RuntimeError("g15-noexec: host token missing")

    def http(method, path, body=None):
        return _http_json(port, token, method, path, body)

    expect = getattr(args, "g15_expect_ai", "none")
    driver.wait_until(
        "Boolean(window.__d1App && window.__d1App.ready())", what="G15 页面启动", timeout=40
    )
    if driver.eval("window.__d1App.state()") == "uninitialized":
        driver.eval(
            "window.__d1Setup.fill("
            + json.dumps(
                {
                    "display_name": "G15教师",
                    "class_name": "G15中一班",
                    "grade": "middle",
                    "term_name": "G15学期",
                    "start_date": args.term_start,
                    "end_date": args.term_end,
                    "school_name": "G15园所",
                },
                ensure_ascii=False,
            )
            + ")"
        )
        driver.eval("window.__d1Setup.submit()")
        driver.wait_until("window.__d1App.state() === 'ready'", what="G15 初始化", timeout=60)
    checks["g15_initialized"] = True

    if getattr(args, "g15_configure", False):
        status, configured = http(
            "PATCH",
            "/api/local/ai/config",
            {
                "request_id": "bbbb1111-2222-4333-8444-555566667777",
                "expected_ai_config_version": 0,
                "protocol_id": "chat_completions_v1",
                "base_url": "https://api.example.com/v1",
                "model": "g15-window-model",
                "secret": "g15-window-secret",
            },
        )
        summary["g15_configure_status"] = status
        checks["g15_configured"] = bool(
            status == 200 and isinstance(configured, dict) and configured.get("configured")
        )

    # Readable AI state through the real API (every branch).
    status, config = http("GET", "/api/local/ai/config")
    summary["g15_config"] = config if isinstance(config, dict) else {"raw": config}
    summary["g15_config_status"] = status
    checks["g15_config_readable"] = (
        status == 200 and isinstance(config, dict) and "configured" in config
    )

    driver.wait_until(
        "Boolean(window.__d1Workbench && typeof window.__d1Workbench.openDate === 'function')",
        what="G15 工作台就绪",
        timeout=30,
    )
    driver.eval(f"window.__d1Workbench.openDate({json.dumps(args.date)})")
    driver.wait_until("window.__d1App.view() === 'editor'", what="G15 进入编辑器", timeout=30)
    driver.wait_until(
        "window.__d1Editor && ['ready','create_confirmation'].includes(window.__d1Editor.phase())",
        what="G15 编辑器就绪",
        timeout=30,
    )
    if driver.eval("window.__d1Editor.phase()") == "create_confirmation":
        driver.eval("window.__d1Editor.confirmCreate()")
        driver.wait_until(
            "window.__d1Editor.phase() === 'ready'", what="G15 创建日计划", timeout=30
        )
    plan_id = driver.eval("window.__d1Editor.planId()")
    summary["g15_plan_id"] = plan_id

    # Manual edit + save (must work regardless of the AI state). The text is
    # unique per launch so a re-launch on the same plan is really a new version,
    # never a no-op dirty=false wait.
    tag = getattr(args, "g15_tag", "") or "g15"
    manual_raw = f"G15无AI手工原文-{tag}"
    manual_reflection = f"G15无AI手工反思-{tag}"
    summary["g15_manual_raw"] = manual_raw
    summary["g15_manual_reflection"] = manual_reflection
    driver.eval(
        "window.__d1Editor.setText("
        + json.dumps(manual_raw, ensure_ascii=False)
        + ", "
        + json.dumps(manual_reflection, ensure_ascii=False)
        + ")"
    )
    driver.wait_until("window.__d1Editor.dirty() === true", what="G15 手工输入", timeout=15)
    version_before = driver.eval("window.__d1Editor.version()")
    driver.eval("window.__d1Editor.save()")
    driver.wait_until(
        "window.__d1Editor.phase() === 'ready' && window.__d1Editor.dirty() === false",
        what="G15 手工保存",
        timeout=60,
    )
    checks["g15_manual_save"] = (
        driver.eval("window.__d1Editor.version()") == version_before + 1
    )

    if getattr(args, "g15_no_ai_trigger", False):
        # Pure configuration launch (credential preparation): never send an AI
        # request, so no live task can block the close.
        summary["g15_ai_error"] = None
        summary["g15_split_task_status"] = None
    else:
        # AI trigger: record the readable state / task outcome for this branch.
        driver.eval("window.__d1AiTasks.trigger('daily_lesson_split')")
        time.sleep(2.0)
        summary["g15_ai_error"] = driver.eval(
            "window.__d1AiTasks.createError('daily_lesson_split')"
        )
        tasks = driver.eval("window.__d1AiTasks.tasks()") or []
        split_tasks = [t for t in tasks if t.get("task_type") == "daily_lesson_split"]
        summary["g15_split_task_status"] = (
            split_tasks[0].get("status") if split_tasks else None
        )

        if expect == "executor":
            # The 503 reads "本机 AI 执行器暂不可用；手工功能不受影响".
            checks["g15_ai_unavailable_readable"] = "执行器" in str(
                summary.get("g15_ai_error") or ""
            )
            checks["g15_no_task_created"] = not split_tasks
        elif expect == "config_error":
            err = str(summary.get("g15_ai_error") or "")
            checks["g15_ai_unavailable_readable"] = bool(err)
            checks["g15_no_task_created"] = not split_tasks
        elif expect == "network":
            deadline = time.time() + 90
            status_value = summary.get("g15_split_task_status")
            while time.time() < deadline and status_value not in (
                "failed",
                "outcome_unknown",
                "paused",
                "succeeded",
            ):
                time.sleep(1.0)
                tasks = driver.eval("window.__d1AiTasks.tasks()") or []
                split_tasks = [
                    t for t in tasks if t.get("task_type") == "daily_lesson_split"
                ]
                status_value = split_tasks[0].get("status") if split_tasks else None
            summary["g15_split_task_status"] = status_value
            checks["g15_ai_failed_without_blocking"] = status_value in (
                "failed",
                "paused",
                "outcome_unknown",
            )
        else:
            # No specific expectation: whatever the AI state is, it must be
            # *recorded and readable* (an error message or a real task status).
            checks["g15_ai_state_recorded"] = bool(
                summary.get("g15_ai_error")
            ) or (summary.get("g15_split_task_status") is not None)

    # Native export must still succeed.
    before = driver.eval("window.__d1Export.seq()")
    driver.eval("window.__d1Export.setMode('day')")
    driver.eval("window.__d1Export.runConfirmed()")
    terminal = (
        "['saved','canceled','save_failed','generation_failed','export_not_found',"
        "'save_result_unknown'].includes(window.__d1Export.phase())"
    )
    driver.wait_until(
        f"window.__d1Export.seq() > {before} && {terminal}",
        what="G15 原生导出",
        timeout=120,
    )
    phase = driver.eval("window.__d1Export.phase()")
    summary["g15_export"] = {
        "phase": phase,
        "filename": driver.eval("window.__d1Export.savedFilename()"),
    }
    checks["g15_native_export_saved"] = phase == "saved"
    # The manual save still holds after the AI attempt (no version drift).
    status, plan = http("GET", f"/api/daily-plans/{plan_id}")
    content = (plan or {}).get("content") or {}
    checks["g15_manual_content_intact"] = (
        content.get("raw_lesson_plan") == manual_raw
        and (content.get("adopted_content") or {}).get("reflection")
        == manual_reflection
    )


def run_selftest(args) -> int:
    _startup_log("run_selftest:start")
    finished = threading.Event()
    closing_finished = threading.Event()
    summary: dict = {"checks": {}}
    service = None
    runtime = None
    try:
        try:
            service, host_api, runtime = build_runtime(args)
            _startup_log("run_selftest:runtime ready")
        except Exception as exc:
            summary["startup_error"] = str(exc)
            summary["ok"] = False
            _write_summary(summary, args.out)
            _startup_log(f"run_selftest:startup_error {exc}")
            return 2
        if not service.start_and_wait():
            summary["startup_error"] = service.error
            _write_summary(summary, args.out)
            _startup_log(f"run_selftest:service error {service.error}")
            return 2
        _startup_log(f"run_selftest:service ready port {service.port}")
        summary["data_dir"] = str(runtime.data_dir)
        summary["db_path"] = str(runtime.db_path)
        import webview

        window = webview.create_window(
            f"D1 验证窗口（{args.phase}）",
            url=f"http://127.0.0.1:{service.port}/",
            js_api=host_api,
            width=1180,
            height=820,
            min_size=(760, 560),
            text_select=True,
        )
        _install_close_handlers(window, host_api, runtime)
        _startup_log("run_selftest:window created")

        def driver_task():
            try:
                drive_selftest(window, host_api, args, summary, port=service.port)
            finally:
                finished.set()
                try:
                    window.destroy()
                except Exception as exc:
                    summary["destroy_error"] = str(exc)

        def watchdog():
            # Hard bound on the whole window run (a driver that cannot fix
            # the hang, e.g. a page whose JS bridge never responds). The
            # async regression phase includes the real 30s close timeout on
            # purpose, so it gets a wider bound.
            deadline = SELFTEST_DEADLINE_SECONDS
            if args.phase in (
                "fix-regression2",
                "close-order",
                "late-input-close",
                "settings-draft-close",
                "save-dialog",
                "w5-ui",
                "w6-ui",
                "w6-ui-verify",
                "g15-noexec",
                "d3-h2-ui",
                "d3-h2-verify",
                "u3-update",
                "u3-verify",
            ):
                deadline = 420.0
            if not finished.wait(deadline):
                summary["watchdog_timeout"] = True
                summary["ok"] = False
                _write_summary(summary, args.out)
                os._exit(3)
            # The driver finished but the process must still exit through the
            # normal close path; if the window cannot be destroyed (dead
            # bridge), end with an explicit failure instead of hanging.
            if not closing_finished.wait(45):
                summary["destroy_timeout"] = True
                summary["ok"] = False
                _write_summary(summary, args.out)
                os._exit(3)

        threading.Thread(target=watchdog, daemon=True).start()
        _startup_log("run_selftest:webview.start begin")
        webview.start(gui="edgechromium", func=driver_task)
        _startup_log("run_selftest:webview.start returned")
        closing_finished.set()
        if args.phase == "w5-ui":
            # The final check (stop_and_exit allow) is recorded by the driver
            # thread right before the window is really destroyed: wait for the
            # driver to finish so the summary keeps the complete W5 evidence.
            finished.wait(20)
            # Confirm the live-task outcome from the host/process/database, not
            # from page JS after the window is gone.
            _verify_w5_close(summary, runtime, host_api)
        if args.phase == "close-order":
            # The phase really closes the window and completes its host-side
            # audit right after; give the driver thread a bounded head start
            # so the summary keeps the full post-close evidence.
            deadline = time.time() + 15
            while time.time() < deadline and "close_order" not in summary:
                time.sleep(0.02)
        if args.phase == "late-input-close":
            # The retry close saves the kept input and really closes; the
            # database check can only run after the window closed while the
            # runtime is still open. The audit marker is written by the
            # driver thread after the real destroy.
            deadline = time.time() + 15
            while time.time() < deadline and "late_input_audited" not in summary:
                time.sleep(0.02)
            _verify_late_input_close(summary)
        if args.phase == "settings-draft-close":
            # The retry close really closes after the explicit draft cancel;
            # the post-close database check confirms the discarded draft was
            # never applied or saved. The audit marker (or a driver error)
            # ends the wait; the verifier still runs for the failed case.
            deadline = time.time() + 15
            while (
                time.time() < deadline
                and "settings_draft_audited" not in summary
                and "driver_error" not in summary
            ):
                time.sleep(0.02)
            _verify_settings_draft_close(summary)
        if args.phase == "clean-ime-close":
            # The composition close can only be verified after the real
            # window closed; the runtime/database is still open here.
            _verify_clean_ime_close(summary)
        if runtime is not None:
            if _dispose_executor(runtime, summary):
                runtime.dispose()
                runtime = None
            else:
                summary.setdefault("checks", {})["runtime_lock_released"] = False
        _stop_service(service)
        service = None
        summary.setdefault("checks", {})
        summary["checks"]["server_stopped"] = True
        if summary.get("ok") is not False:
            summary["ok"] = all(
                value is not False for value in summary["checks"].values()
            )
        _write_summary(summary, args.out)
        return 0 if summary.get("ok") else 3
    finally:
        finished.set()
        _stop_service(service)
        if runtime is not None:
            if _dispose_executor(runtime, summary):
                runtime.dispose()


def _dispose_executor(runtime, summary: dict | None = None) -> bool:
    """Confirm every AI worker exited before the runtime lock is released.

    A worker whose exit cannot be confirmed blocks a normal close: the runtime
    lock is still released (the process is ending) but the run is recorded as
    not clean rather than claiming success.
    """
    executor = getattr(runtime, "ai_executor", None)
    if executor is None:
        # A degraded host has no AI worker at all: nothing to wait for, and the
        # check is still recorded so the evidence is complete.
        if summary is not None:
            summary.setdefault("checks", {})
            summary["checks"]["ai_worker_confirmed_exit"] = True
        return True
    confirmed = False
    try:
        confirmed = bool(executor.dispose())
    except Exception:  # noqa: BLE001
        confirmed = False
    if summary is not None:
        summary.setdefault("checks", {})
        summary["checks"]["ai_worker_confirmed_exit"] = confirmed
    return confirmed


def _install_close_handlers(window, host_api, runtime=None) -> None:
    import d1_host_api

    executor = getattr(runtime, "ai_executor", None) if runtime is not None else None
    install_coordinator = getattr(host_api, "_install_coordinator", None)

    def notify_page(close_request_id: str, generation: int | None = None) -> None:
        host_api._notify_request_close(close_request_id, generation)

    def notify_aborted(close_request_id: str, reason: str) -> None:
        host_api._notify_close_aborted(close_request_id, reason)

    def task_snapshot() -> dict:
        if executor is None:
            return {"live": 0, "in_flight": False}
        snapshot = executor.active_snapshot()
        if (
            snapshot.get("attempt_in_flight")
            or snapshot.get("unconfirmed")
            or snapshot.get("pending_persist")
        ):
            return {"live": 1, "in_flight": True}
        from app.local import ai_task_service

        session = runtime.session()
        try:
            counts = ai_task_service.active_task_snapshot(session)
        except Exception:  # noqa: BLE001 - fail safe: keep the close refused
            return {"live": 1, "in_flight": True}
        finally:
            session.close()
        return {"live": counts["live"], "in_flight": False}

    def on_close_intent() -> None:
        if executor is not None:
            executor.freeze()

    def on_close_canceled() -> None:
        if executor is not None:
            executor.unfreeze()
            executor.notify()

    def drain_tasks() -> bool:
        if executor is None:
            return True
        return executor.stop_and_drain(deadline=5.0)

    def on_install_intent(close_request_id: str, generation: int) -> None:
        if install_coordinator is not None:
            install_coordinator.bind_close(close_request_id, generation)

    def on_install_canceled(close_request_id: str | None, reason: str) -> None:
        if install_coordinator is not None:
            install_coordinator.cancel_close(close_request_id, reason)

    def on_install_final(close_request_id: str, generation: int) -> None:
        if install_coordinator is not None:
            install_coordinator.finalize_close(close_request_id, generation)

    coordinator = d1_host_api.CloseCoordinator(
        notify_page=notify_page,
        destroy_window=window.destroy,
        notify_aborted=notify_aborted,
        # The host never destroys the window while a native Word save (dialog
        # or atomic write) is still in flight (spec §12.3 / R11).
        busy_probe=host_api._save_in_progress,
        # D2 §4.3: freeze AI on the close intent and require an explicit task
        # choice before releasing the window.
        task_snapshot=task_snapshot,
        on_close_intent=on_close_intent,
        on_close_canceled=on_close_canceled,
        on_install_intent=on_install_intent,
        on_install_canceled=on_install_canceled,
        on_install_final=on_install_final,
        drain_tasks=drain_tasks,
    )
    host_api._close_coordinator = coordinator

    def on_closing():
        # Never wait for JS/database in the synchronous closing callback.
        return coordinator.handle_closing()

    window.events.closing += on_closing


def _stop_service(service) -> None:
    if service is None:
        return
    try:
        service.stop()
    except Exception:
        pass


def run_interactive(args) -> int:
    version = webview2_runtime_version()
    if version is None:
        show_error(
            "WebView2 缺失",
            "未检测到 WebView2 Runtime。本应用依赖系统 WebView2 组件，"
            "请先安装 Microsoft Edge WebView2 Runtime。",
        )
        return 2
    service = None
    runtime = None
    try:
        try:
            service, host_api, runtime = build_runtime(args)
        except Exception as exc:
            show_error("启动失败", f"初始化本地运行时失败：\n{exc}")
            return 2
        if not service.start_and_wait():
            error = service.error
            _stop_service(service)
            show_error("启动失败", f"本地服务启动失败：\n{error}")
            return 2
        import webview

        window = webview.create_window(
            "幼儿园教师工作台（本地）",
            url=f"http://127.0.0.1:{service.port}/",
            js_api=host_api,
            width=1180,
            height=820,
            min_size=(760, 560),
            text_select=True,
        )
        _install_close_handlers(window, host_api, runtime)
        try:
            webview.start(gui="edgechromium")
        except Exception as exc:
            _stop_service(service)
            show_error("窗口失败", f"窗口启动失败：\n{exc}")
            return 2
        _stop_service(service)
        try:
            if getattr(host_api, "_update_manager", None) is not None:
                host_api._update_shutdown_confirmed = bool(
                    host_api._update_manager.shutdown()
                )
                if not host_api._update_shutdown_confirmed:
                    _startup_log("update manager shutdown not confirmed")
            install_coordinator = getattr(host_api, "_install_coordinator", None)
            if install_coordinator is not None:
                install_coordinator.shutdown()
        except Exception:
            host_api._update_shutdown_confirmed = False
        return 0
    finally:
        _stop_service(service)
        if runtime is not None:
            if _dispose_executor(runtime) or getattr(
                runtime, "ai_executor", None
            ) is None:
                runtime.dispose()


def main() -> int:
    STARTUP_STREAM_STATE["stdout_none"] = sys.stdout is None
    STARTUP_STREAM_STATE["stderr_none"] = sys.stderr is None
    opened = ensure_console_streams()
    parser = argparse.ArgumentParser(description="D1 desktop application")
    parser.add_argument("--data", help="合成数据目录（验证时注入）")
    parser.add_argument(
        "--credential-root",
        default=None,
        help="内部更新启动使用：保留原同机凭据根（页面不可传入）",
    )
    parser.add_argument("--frontend", help="D1 前端构建目录")
    parser.add_argument("--selftest", action="store_true", help="自动化窗口流程")
    parser.add_argument("--out", help="自检结果 JSON 输出文件")
    parser.add_argument(
        "--screenshot-dir",
        default=None,
        help="验证专用：真实源码窗口截图输出目录（d3-h2-ui）",
    )
    parser.add_argument(
        "--word-out",
        default=None,
        help="验证专用：d3-h2-verify 导出的 DOCX 目标文件",
    )
    parser.add_argument("--u3-config", default=None, help="验证专用：U3 源码合成更新配置")
    parser.add_argument("--u3-source-identity", default=None, help="验证专用：新版源码构建身份文件")
    parser.add_argument("--u3-verify-stop", default=None, help="验证专用：u3-verify 等待外部收口文件")
    parser.add_argument(
        "--u3-close-cancel",
        action="store_true",
        help="验证专用：先注入正文保存失败取消关闭，再用同一 UI 安装",
    )
    parser.add_argument(
        "--phase",
        choices=[
            "first",
            "restart",
            "verify",
            "dirty-close",
            "fix-regression",
            "fix-regression2",
            "close-order",
            "late-input-close",
            "settings-draft-close",
            "word-r18",
            "save-dialog",
            "clean-ime-close",
            "w5-ui",
            "w6-ui",
            "w6-ui-verify",
            "w6-resources",
            "g15-noexec",
            "d3-h2-ui",
            "d3-h2-verify",
            "u3-update",
            "u3-verify",
        ],
        default="first",
    )
    parser.add_argument(
        "--init-school",
        default="验证园所",
        help="first 阶段首次设置的园所名称；传空串用于空园所快照验证",
    )
    parser.add_argument("--date", default="2026-09-15", help="自检使用的计划日期")
    parser.add_argument("--date2", default="2026-09-16", help="多份导出用的第二个日期")
    parser.add_argument("--term-start", default="2026-09-01")
    parser.add_argument("--term-end", default="2026-09-30")
    parser.add_argument("--session-tag", default="D1验证")
    parser.add_argument(
        "--close-order-abort",
        choices=["delayed", "lost"],
        default="delayed",
        help="close-order 阶段：A 的宿主撤销通知迟到送达或完全丢失",
    )
    parser.add_argument(
        "--close-order-request",
        choices=["delayed", "lost", "lastack"],
        default=None,
        help=(
            "close-order 阶段（review §14.3/§15.3）：A 的 request_close 通知迟到送达、"
            "完全丢失，或 lastack 时其最终确认回包迟到"
        ),
    )
    parser.add_argument(
        "--save-dialog-dir",
        help="save-dialog 阶段：真实另存为对话框写入的合成目标目录",
    )
    parser.add_argument("--expect-version", type=int, default=None)
    parser.add_argument("--expect-raw", default=None)
    parser.add_argument(
        "--synthetic-provider-port",
        type=int,
        default=None,
        help="验证专用：受控本机 TLS 供应商端口（仅 w5-ui 源码窗口）",
    )
    parser.add_argument("--synthetic-provider-ca", default=None)
    parser.add_argument("--synthetic-provider-ip", default="127.0.0.1")
    parser.add_argument(
        "--synthetic-executor-fail",
        choices=["construct", "start"],
        default=None,
        help="验证专用：在专用自检中注入 AI 执行器构造/启动失败（G15 降级）",
    )
    parser.add_argument(
        "--g15-expect-ai",
        choices=["none", "config_error", "network", "executor"],
        default="none",
        help="g15-noexec 阶段断言的 AI 降级类别",
    )
    parser.add_argument(
        "--g15-configure",
        action="store_true",
        help="g15-noexec 阶段：先通过真实 API 写入一份 AI 配置",
    )
    parser.add_argument(
        "--g15-no-ai-trigger",
        action="store_true",
        help="g15-noexec 阶段：纯配置，不触发任何 AI 请求（凭据准备用）",
    )
    parser.add_argument(
        "--g15-tag",
        default="",
        help="g15-noexec 阶段：本次手工保存文本的唯一后缀",
    )
    parser.add_argument(
        "--same-origin-modules",
        default=None,
        help="w6-resources 阶段：待同源指纹的生产模块名 JSON 列表文件",
    )
    try:
        args = parser.parse_args()
        if args.selftest:
            if args.phase == "w6-resources":
                return run_w6_resources(args)
            return run_selftest(args)
        return run_interactive(args)
    finally:
        for stream in opened:
            try:
                stream.close()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
