"""D0 desktop verification entry (pywebview + WebView2 candidate).

Startup contract (D0-1 / D0-7):
1. make the process safe without a console (a ``--windowed`` build has
   ``sys.stdout``/``sys.stderr`` = ``None``; every library that logs or
   prints must still work without an external shell or redirection - R1);
2. resolve resources (frontend dist, controlled Word template, data dir);
3. pick a free loopback port and generate fresh per-launch session material;
4. build the isolated D0 FastAPI app and start uvicorn in a daemon thread;
5. wait for a bounded readiness window; on failure, show an understandable
   native error, release the probe/service resources and exit (never a blank
   window);
6. open the WebView2 window pointing at the loopback origin, with no token
   in the URL;
7. after the window closes, stop the server and join the thread (D0-2 exit
   cleanup), release the SQLite engine, then exit the process.

``--selftest`` runs the automated window flow instead of waiting for a human
close (used for packaged verification; the interactive mode is the default).
The self-test combines every required assertion; a timeout, a refused write
or a failed process cleanup makes the run return non-zero (R10).
"""

import argparse
import json
import os
import secrets
import socket
import sys
import threading
import time
from pathlib import Path

import d0_paths

WEBVIEW2_CLIENT_GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"

# Captured before ensure_console_streams() so the self-test can prove it ran
# with no inherited console/std handles (the real double-click condition).
STARTUP_STREAM_STATE: dict = {"stdout_none": None, "stderr_none": None}


def ensure_console_streams() -> list:
    """Give a windowed process writable stdout/stderr (R1).

    ``pythonw``/PyInstaller ``--windowed`` set these to ``None``; uvicorn's
    default formatter then calls ``sys.stdout.isatty()`` and the whole
    startup dies with ``AttributeError``. Binding a devnull sink is enough
    for libraries that merely need a writable stream, and it means the run
    never depends on a console or an external redirection. Returns the
    streams opened here so callers/tests can close them.
    """
    opened = []
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
        opened.append(sys.stdout)
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
        opened.append(sys.stderr)
    return opened


def _native_message_box(title: str, message: str) -> None:
    import ctypes  # noqa: PLC0415

    ctypes.windll.user32.MessageBoxW(0, message, title, 0x00000010)  # MB_ICONERROR


def show_error(title: str, message: str, *, box=None) -> None:
    """Show a blocking native error (works without a console)."""
    box = box or _native_message_box
    try:
        box(title, message)
        return
    except Exception:
        pass
    stream = getattr(sys, "stderr", None)
    if stream is not None:
        try:
            print(f"[{title}] {message}", file=stream)
        except Exception:
            pass


def _default_registry_reader(root_name: str, subkey: str) -> str | None:
    import winreg  # noqa: PLC0415

    roots = {
        "HKEY_LOCAL_MACHINE": winreg.HKEY_LOCAL_MACHINE,
        "HKEY_CURRENT_USER": winreg.HKEY_CURRENT_USER,
    }
    with winreg.OpenKey(roots[root_name], subkey) as key:
        value, _type = winreg.QueryValueEx(key, "pv")
    return str(value)


def webview2_registry_candidates() -> list[tuple[str, str]]:
    """Hive/architecture candidates for the WebView2 Runtime (R8).

    Per-user installs live under HKCU ``Software\\Microsoft\\EdgeUpdate``
    (no WOW6432Node), while a system install on 64-bit Windows lives under
    HKLM ``Software\\WOW6432Node\\...``. The previous code only looked at the
    WOW6432Node path for both hives and therefore missed the per-user case.
    """
    guid = WEBVIEW2_CLIENT_GUID
    return [
        ("HKEY_CURRENT_USER", rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{guid}"),
        (
            "HKEY_LOCAL_MACHINE",
            rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{guid}",
        ),
        ("HKEY_LOCAL_MACHINE", rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{guid}"),
    ]


def webview2_runtime_version(reader=None) -> str | None:
    """Read the installed WebView2 Runtime version, or ``None`` if absent.

    ``None`` means not found: the launcher reports a clear installation need
    and exits instead of silently degrading (D0-7). ``reader`` is injectable
    so the registry branches can be tested without touching the real hive.
    """
    reader = reader or _default_registry_reader
    for root_name, subkey in webview2_registry_candidates():
        try:
            value = reader(root_name, subkey)
        except OSError:
            continue
        except Exception:
            continue
        if value is None:
            continue
        text = str(value)
        if text and text not in ("0", "0.0.0.0"):
            return text
    return None


def free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class ServiceRun:
    """Bounded readiness wait around a uvicorn server thread."""

    def __init__(self, app, port: int, timeout: float = 10.0):
        self.port = port
        self.timeout = timeout
        self.error: str | None = None
        self.server = None
        self.thread: threading.Thread | None = None
        self._thread_error: str | None = None
        try:
            import uvicorn  # noqa: PLC0415
        except ImportError as exc:
            self.error = f"uvicorn 未安装: {exc}"
            return
        try:
            config = uvicorn.Config(
                app,
                host="127.0.0.1",
                port=port,
                log_level="warning",
                access_log=False,
                lifespan="on",
            )
            self.server = uvicorn.Server(config)
        except Exception as exc:
            self.error = f"uvicorn 配置失败：{exc}"
            return
        self.thread = threading.Thread(
            target=self._run_server, name="d0-uvicorn", daemon=True
        )

    def _run_server(self) -> None:
        try:
            self.server.run()
        except SystemExit as exc:
            # uvicorn calls sys.exit() when binding/startup fails; contain it
            # inside the daemon thread instead of leaking an unhandled thread
            # exception (port-occupied regression, R1/D0-3).
            self._thread_error = f"服务启动退出（code={exc.code}）"
        except BaseException as exc:  # noqa: BLE001 - intentionally contained
            self._thread_error = f"服务线程异常：{exc!r}"

    def start_and_wait(self) -> bool:
        if self.server is None or self.thread is None:
            return False
        self.thread.start()
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            if self.server.started:
                return True
            if not self.thread.is_alive():
                self.error = (
                    self._thread_error
                    or "uvicorn 线程已退出（可能是端口占用或绑定失败）"
                )
                return False
            time.sleep(0.05)
        self.error = self.error or f"服务在 {self.timeout:.0f}s 内未就绪"
        return False

    def alive(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def stop(self, timeout: float = 10.0) -> None:
        if self.server is not None:
            self.server.should_exit = True
        if self.thread is not None and self.thread.is_alive():
            self.thread.join(timeout)


def build_runtime(args) -> tuple[ServiceRun, object, object]:
    """Create (service, host api, probe) for a window run.

    Any failure after the SQLite engine is created disposes it here, so a
    failed initialisation does not leak the engine/connection (R1).
    """
    from d0_db import SQLiteProbe
    from d0_server import LaunchContext, create_app

    if args.frontend:
        os.environ["KGM_D0_FRONTEND_DIR"] = str(args.frontend)
    if args.data:
        os.environ["KGM_D0_DATA_DIR"] = str(args.data)

    probe = SQLiteProbe(d0_paths.data_dir())
    service = None
    try:
        frontend_dir = (
            str(args.frontend) if args.frontend else str(d0_paths.frontend_dist())
        )
        context = LaunchContext(
            port=free_loopback_port(), launch_token=secrets.token_urlsafe(32)
        )
        environment = {
            "python_version": sys.version.split(" ")[0],
            "frozen": d0_paths.is_frozen(),
            "webview2_runtime_version": webview2_runtime_version(),
            "frontend_dir": frontend_dir,
            **probe.meta(),
        }
        app = create_app(context, probe, environment)
        service = ServiceRun(app, context.port)
        import d0_host_api  # noqa: PLC0415

        host_api = d0_host_api.D0HostApi(launch_token=context.launch_token)
    except Exception:
        # Release anything already created before propagating (R1 cleanup).
        _stop_service(service)
        probe.close()
        raise
    return service, host_api, probe


def _stop_service(service) -> str | None:
    """Stop/join a service run; returns an error string if stopping failed.

    Safe on ``None`` and safe to call more than once (``stop`` sets
    ``should_exit`` and joins an already-finished thread). Used on every
    failure path so a timed-out or failed startup never leaves this run's
    server trying to come up in the background (R1).
    """
    if service is None:
        return None
    try:
        service.stop()
    except Exception as exc:  # never let cleanup mask the real failure
        return str(exc)
    return None


# Hard bound for the automated self-test: if the GUI loop is still blocking
# after the driver has finished (e.g. a window that refuses to close) the run
# is force-ended with a failure instead of waiting for a human (R10).
SELFTEST_TOTAL_DEADLINE_SECONDS = 300.0


def close_selftest_windows(summary: dict) -> bool:
    """Close every open self-test window; return False if any stayed open.

    A driver exception must never leave the WebView2 window waiting for a
    human to click the close button (R10 abnormal end). A close failure is
    recorded in ``summary['window_close_error']`` so the run can still report
    an explicit failure instead of hanging. Idempotent: a window already
    closed by a previous call is skipped.
    """
    try:
        import webview  # noqa: PLC0415
    except Exception as exc:
        summary["window_close_error"] = f"webview 不可用：{exc}"
        return False
    windows = list(getattr(webview, "windows", []) or [])
    error: str | None = None
    for window in windows:
        if getattr(window, "_d0_closed", False):
            continue
        try:
            window.destroy()
        except Exception as exc:
            error = str(exc)
            continue
        try:
            setattr(window, "_d0_closed", True)
        except Exception:
            pass
    if error is not None:
        summary["window_close_error"] = error
        return False
    return True


def open_window(service: ServiceRun, host_api, *, driver=None) -> None:
    import webview  # noqa: PLC0415

    title = "D0 验证窗口（合成数据）"
    port = service.port
    url = f"http://127.0.0.1:{port}/"  # no token in the URL, ever
    webview.create_window(
        title,
        url,
        js_api=host_api,
        width=1080,
        height=800,
        min_size=(720, 560),
        text_select=True,
    )
    start_kwargs = {"gui": "edgechromium"}
    if driver is not None:
        start_kwargs["func"] = driver

    webview.start(**start_kwargs)


def run_interactive(args) -> int:
    version = webview2_runtime_version()
    if version is None:
        show_error(
            "WebView2 缺失",
            "未检测到 WebView2 Runtime。本验证依赖系统 WebView2 组件，"
            "需要先安装 Microsoft Edge WebView2 Runtime（记录缺失条件并交由协调者处理）。",
        )
        return 2
    probe = None
    service = None
    try:
        try:
            service, host_api, probe = build_runtime(args)
        except Exception as exc:
            show_error("D0 启动失败", f"初始化验证运行时失败：\n{exc}")
            return 2
        if not service.start_and_wait():
            error = service.error
            # Release this run's server BEFORE the blocking error box is shown,
            # otherwise it can keep coming up while the modal waits for a human
            # (R1). ``_stop_service`` is safe to call again below.
            _stop_service(service)
            show_error("D0 启动失败", f"本地服务启动失败：\n{error}")
            return 2
        try:
            open_window(service, host_api)
        except Exception as exc:
            _stop_service(service)
            show_error("D0 窗口失败", f"窗口启动失败：\n{exc}")
            return 2
        _stop_service(service)
        if service.alive():
            show_error("D0 退出异常", "本地服务线程未能在退出时限内结束。")
            return 3
        return 0
    finally:
        _stop_service(service)
        if probe is not None:
            probe.close()


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


def run_selftest(args) -> int:
    """Automated window flow (in-window real UI operates the API + host save).

    Every required assertion is collected in ``summary['checks']`` and
    combined with ``combine_ok``; a driver exception, window error, failed
    server cleanup or any false check makes the process return non-zero
    (R10).
    """
    from d0_driver import combine_ok

    finished = threading.Event()
    try:
        try:
            service, host_api, probe = build_runtime(args)
        except Exception as exc:
            # Automated mode: record the failure (non-zero exit) instead of a
            # blocking native dialog that would hang a headless verification.
            _write_summary(
                {
                    "ok": False,
                    "checks": {},
                    "startup_error": str(exc),
                    "startup_streams": dict(STARTUP_STREAM_STATE),
                },
                args.out,
            )
            return 2
        try:
            if not service.start_and_wait():
                error = service.error
                # Release the server before returning so a timed-out or failed
                # startup cannot keep binding in the background (R1).
                _stop_service(service)
                _write_summary(
                    {
                        "ok": False,
                        "checks": {},
                        "startup_error": error,
                        "startup_streams": dict(STARTUP_STREAM_STATE),
                    },
                    args.out,
                )
                return 2
            summary: dict = {}
            summary.setdefault("checks", {})
            summary["startup_streams"] = dict(STARTUP_STREAM_STATE)

            def drive_task():
                try:
                    from d0_driver import drive_window  # noqa: PLC0415

                    summary.update(
                        drive_window(
                            probe,
                            phase=args.selftest_phase,
                            expect_content=args.expect_content,
                            expect_version=args.expect_version,
                            session_tag=args.session_tag,
                        )
                    )
                except Exception as exc:
                    summary["driver_error"] = str(exc)
                    summary.setdefault("checks", {})["driver_completed"] = False
                finally:
                    # Always close this run's window so ``webview.start``
                    # returns without a human even after a driver exception,
                    # and record an explicit failure if closing failed (R10).
                    closed = close_selftest_windows(summary)
                    summary.setdefault("checks", {})["selftest_window_closed"] = (
                        closed
                    )

            def watchdog():
                # Bounded end for the class of hangs a driver cannot fix (the
                # window refuses to close). Normal runs finish long before.
                if finished.wait(SELFTEST_TOTAL_DEADLINE_SECONDS):
                    return
                close_selftest_windows(summary)
                checks = summary.setdefault("checks", {})
                checks["selftest_window_closed"] = False
                checks.setdefault("driver_completed", False)
                summary["window_close_timeout"] = True
                summary["ok"] = False
                _write_summary(summary, args.out)
                os._exit(3)

            threading.Thread(
                target=watchdog, name="d0-selftest-watchdog", daemon=True
            ).start()

            try:
                open_window(service, host_api, driver=drive_task)
            except Exception as exc:
                summary["window_error"] = str(exc)
                closed = close_selftest_windows(summary)
                summary.setdefault("checks", {})["selftest_window_closed"] = closed

            summary.setdefault("checks", {})
            checks = summary["checks"]
            if not any(key != "driver_completed" for key in checks):
                # Nothing ran (window failed before the driver): never success.
                checks["driver_completed"] = False
            checks["selftest_window_closed"] = (
                checks.get("selftest_window_closed") is True
            )
            stop_error = _stop_service(service)
            if stop_error is not None:
                summary["stop_error"] = stop_error
            checks["server_stopped_clean"] = not service.alive()
            checks["no_window_error"] = "window_error" not in summary
            checks["no_stop_error"] = "stop_error" not in summary
            checks["no_driver_error"] = "driver_error" not in summary
            checks["window_closed_without_error"] = "window_close_error" not in summary
            summary["server_stopped_clean"] = checks["server_stopped_clean"]
            summary["ok"] = combine_ok(checks)
            _write_summary(summary, args.out)
            return 0 if summary["ok"] else 3
        finally:
            probe.close()
    finally:
        finished.set()


def main() -> int:
    STARTUP_STREAM_STATE["stdout_none"] = sys.stdout is None
    STARTUP_STREAM_STATE["stderr_none"] = sys.stderr is None
    opened = ensure_console_streams()
    parser = argparse.ArgumentParser(description="D0 desktop feasibility probe")
    parser.add_argument("--frontend", help="前端构建目录（默认 build/desktop-d0/frontend）")
    parser.add_argument(
        "--data", help="合成数据目录（默认 LOCALAPPDATA/KindergartenManager-D0/data）"
    )
    parser.add_argument(
        "--selftest", action="store_true", help="自动化窗口流程（打包后复验用）"
    )
    parser.add_argument("--out", help="自检结果 JSON 输出文件")
    parser.add_argument(
        "--selftest-phase",
        choices=["first", "restart", "verify"],
        default="first",
        help="自检阶段：first 保存 A；restart 读回 A 后保存 B；verify 只读回",
    )
    parser.add_argument("--expect-content", help="restart/verify 阶段期望的旧内容")
    parser.add_argument("--expect-version", type=int, help="restart/verify 阶段期望的旧版本")
    parser.add_argument("--session-tag", help="本次运行的独特内容标记")
    try:
        args = parser.parse_args()
        if args.selftest:
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
