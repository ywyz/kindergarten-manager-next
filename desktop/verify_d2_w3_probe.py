"""D2 W3 frozen spawn probe verifier (Windows-only).

Drives a *copy* of ``build/desktop-d2-w3/package/KGNext-D2W3Probe`` placed in an
out-of-repository path containing Chinese characters, a space, ``%`` and ``#``,
with ``PYTHONPATH``/``PYTHONHOME`` cleared and ``PATH`` restricted to the
Windows system directories — proving the package does not depend on the
development Python. It exercises the G09 process-crash windows against a
controlled local TLS server and asserts the persisted classification, the
external request count, worker teardown and restart stability.

Usage:
    python verify_d2_w3_probe.py [--package DIR] [--keep] [--out FILE]
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wtypes
import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
BACKEND = REPO_ROOT / "backend"
PACKAGE_DEFAULT = REPO_ROOT / "build" / "desktop-d2-w3" / "package" / "KGNext-D2W3Probe"
EXE_NAME = "KGNext-D2W3Probe.exe"

sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(REPO_ROOT / "desktop"))

from tests.local import w3_tls  # noqa: E402

CREATE_NO_WINDOW = 0x08000000
PROCESS_QUERY_LIMITED = 0x1000
SYNCHRONIZE = 0x00100000
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 0x102
STILL_ACTIVE = 259
ERROR_INVALID_PARAMETER = 87
ERROR_ACCESS_DENIED = 5

_kernel32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)
_kernel32.OpenProcess.restype = wtypes.HANDLE
_kernel32.OpenProcess.argtypes = [wtypes.DWORD, wtypes.BOOL, wtypes.DWORD]
_kernel32.GetExitCodeProcess.restype = wtypes.BOOL
_kernel32.GetExitCodeProcess.argtypes = [wtypes.HANDLE, ctypes.POINTER(wtypes.DWORD)]
_kernel32.WaitForSingleObject.restype = wtypes.DWORD
_kernel32.WaitForSingleObject.argtypes = [wtypes.HANDLE, wtypes.DWORD]
_kernel32.CloseHandle.argtypes = [wtypes.HANDLE]

SPLIT = json.dumps(
    {
        "group_activity": {
            "theme": "主题",
            "objectives": "目标",
            "preparation": "准备",
            "key_points": "重点",
            "difficult_points": "难点",
            "process": "一、导入\n二、观察",
        }
    },
    ensure_ascii=False,
)


def pe_subsystem(path: Path) -> int | None:
    """Read the PE OptionalHeader Subsystem (2 = GUI/no console, 3 = console)."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if data[:2] != b"MZ":
        return None
    offset = int.from_bytes(data[0x3C:0x40], "little")
    if data[offset : offset + 4] != b"PE\0\0":
        return None
    optional = offset + 24
    magic = int.from_bytes(data[optional : optional + 2], "little")
    if magic not in (0x10B, 0x20B):
        return None
    return int.from_bytes(data[optional + 68 : optional + 70], "little")


def process_state(pid: int) -> str:
    """``"gone"`` | ``"alive"`` | ``"unknown"``.

    "gone" requires a confirmed wait (``WAIT_OBJECT_0``) or an
    ``ERROR_INVALID_PARAMETER`` open failure (the PID no longer exists); an
    access-denied or any other failure is ``unknown`` and is never reported as
    "gone".
    """
    handle = _kernel32.OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED, False, int(pid))
    if not handle:
        error = ctypes.get_last_error()
        if error == ERROR_INVALID_PARAMETER:
            return "gone"
        return "unknown"
    try:
        waited = _kernel32.WaitForSingleObject(handle, 0)
        if waited == WAIT_OBJECT_0:
            return "gone"
        if waited == WAIT_TIMEOUT:
            return "alive"
        return "unknown"
    finally:
        _kernel32.CloseHandle(handle)


def system_only_env() -> dict:
    """Environment without any development Python / user site on the paths."""
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    env = {
        "SystemRoot": system_root,
        "windir": system_root,
        "TEMP": os.environ.get("TEMP", tempfile.gettempdir()),
        "TMP": os.environ.get("TMP", tempfile.gettempdir()),
        "LOCALAPPDATA": os.environ.get("LOCALAPPDATA", ""),
        "PATH": os.pathsep.join(
            [
                str(Path(system_root) / "System32"),
                system_root,
                str(Path(system_root) / "System32" / "Wbem"),
                str(Path(system_root) / "System32" / "WindowsPowerShell" / "v1.0"),
            ]
        ),
    }
    return {key: value for key, value in env.items() if value}


class Verifier:
    def __init__(self, exe: Path, root: Path):
        self.exe = exe
        self.root = root
        self.checks: dict[str, bool] = {}
        self.notes: list[str] = []

    # -- plumbing ---------------------------------------------------------
    def run_probe(self, *args: str, timeout: float = 120.0, kill_when=None, devnull: bool = False):
        command = [str(self.exe), *args]
        process = subprocess.Popen(
            command,
            cwd=str(self.root),
            env=system_only_env(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL if devnull else subprocess.PIPE,
            stderr=subprocess.DEVNULL if devnull else subprocess.PIPE,
            creationflags=CREATE_NO_WINDOW,
        )
        killed = False
        if kill_when is not None:
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    break
                if kill_when():
                    process.kill()
                    killed = True
                    break
                time.sleep(0.02)
        try:
            out, err = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            out, err = process.communicate()
            self.notes.append(f"probe timeout: {args}")
        # Full stdout/stderr are kept in the root for failure evidence.
        with (self.root / "probe-runs.log").open("a", encoding="utf-8") as log:
            log.write(f"=== {list(args)} rc={process.returncode} killed={killed}\n")
            log.write((out or b"").decode("utf-8", "replace") + "\n")
            if err:
                log.write((err or b"").decode("utf-8", "replace") + "\n")
        return process.returncode, killed

    def spec_paths(self, scenario: str) -> dict:
        base = self.root / scenario
        base.mkdir(parents=True, exist_ok=True)
        return {
            "data": base / "data",
            "cred": base / "credentials",
            "out": base / "phase.json",
            "state": base / "phase.state.json",
        }

    def read_json(self, path: Path) -> dict:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}

    # -- scenario ---------------------------------------------------------
    def scenario(
        self,
        name: str,
        kill_at: str,
        *,
        reply: bool,
        ca_path: Path,
        leaf,
        kill_on_http: bool = False,
        devnull: bool = False,
    ) -> dict:
        paths = self.spec_paths(name)
        server = w3_tls.TlsServer(
            cert=leaf[0],
            key=leaf[1],
            reply=w3_tls.envelope(SPLIT, usage={"prompt_tokens": 2}),
            hang_after_request=not reply,
        ).start()
        try:
            common = [
                "--data", str(paths["data"]),
                "--cred", str(paths["cred"]),
                "--ca", str(ca_path),
                "--port", str(server.port),
                "--out", str(paths["out"]),
            ]
            rc, _ = self.run_probe("--phase", "setup", *common, devnull=devnull)
            self.checks[f"{name}_setup_rc0"] = rc == 0
            state_setup = self.read_json(paths["state"])
            self.checks[f"{name}_task_created"] = bool(state_setup.get("task_id"))

            if kill_on_http:
                # A real parent crash *after* the request reached the provider:
                # wait until the TLS server has seen the request, then kill.
                rc, killed = self.run_probe(
                    "--phase", "run",
                    *common,
                    timeout=120,
                    kill_when=lambda: len(server.requests) > 0,
                )
                self.checks[f"{name}_killed_on_http"] = killed
            else:
                rc, _ = self.run_probe(
                    "--phase", "run", "--kill-at", kill_at, *common, timeout=90,
                    devnull=devnull,
                )
            state_run = self.read_json(paths["state"])
            worker_pid = state_run.get("worker_pid")
            if kill_at in ("before_claim", "claimed"):
                # Both are pre-spawn: no worker may have been created.
                self.checks[f"{name}_no_worker"] = worker_pid is None
            elif kill_at:
                self.checks[f"{name}_parent_exited_9"] = rc == 9
                if worker_pid:
                    deadline = time.monotonic() + 30
                    started = time.monotonic()
                    while time.monotonic() < deadline and process_state(worker_pid) != "gone":
                        time.sleep(0.1)
                    waited_ms = int((time.monotonic() - started) * 1000)
                    self.checks[f"{name}_child_gone"] = process_state(worker_pid) == "gone"
                    self.notes.append(f"{name}: child exit wait {waited_ms} ms")
                else:
                    self.checks[f"{name}_child_gone"] = False
            elif kill_on_http:
                # Killed while the request was in flight; no clean run result.
                self.checks[f"{name}_killed"] = killed
            else:
                self.checks[f"{name}_run_rc0"] = rc == 0
                self.checks[f"{name}_dispose_confirmed"] = bool(
                    state_run.get("dispose_confirmed")
                )
            requests_after_run = len(server.requests)
            worker_gone = False
            if kill_on_http and worker_pid:
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline and process_state(worker_pid) != "gone":
                    time.sleep(0.1)
                worker_gone = process_state(worker_pid) == "gone"
            rc, _ = self.run_probe("--phase", "recover", *common, devnull=devnull)
            self.checks[f"{name}_recover_rc0"] = rc == 0
            recovered = self.read_json(paths["out"])
            rc, _ = self.run_probe("--phase", "recover", *common, devnull=devnull)
            recovered_again = self.read_json(paths["out"])
            requests_final = len(server.requests)
            return {
                "kill_at": kill_at or ("http_sent" if kill_on_http else ""),
                "status": recovered.get("task_status"),
                "reason": recovered.get("task_reason"),
                "candidates": recovered.get("candidates"),
                "attempts": recovered.get("attempts"),
                "dispatched_attempts": recovered.get("dispatched_attempts"),
                "open_attempts": recovered.get("open_attempts"),
                "executions": recovered.get("executions"),
                "integrity": recovered.get("integrity"),
                "foreign_keys": recovered.get("foreign_keys"),
                "stdout_none": recovered.get("stdout_none"),
                "requests_after_run": requests_after_run,
                "requests_final": requests_final,
                "dispose_confirmed": bool(state_run.get("dispose_confirmed")),
                "worker_gone": worker_gone,
                "stable": recovered.get("task_status") == recovered_again.get("task_status")
                and recovered.get("candidates") == recovered_again.get("candidates"),
            }
        finally:
            server.stop()

    # -- main -------------------------------------------------------------
    def run(self) -> dict:
        ca_dir = self.root / "ca"
        _cert, _key, _pem = w3_tls.create_ca(ca_dir)
        leaf = w3_tls.create_leaf(ca_dir, self.root / "leaf")
        ca_path = ca_dir / "ca.pem"

        # (name, kill_at, reply, expected status/reason, candidates, requests)
        plan = [
            ("before_claim", "before_claim", False, ("paused", "restart"), 0, 0),
            ("claimed", "claimed", False, ("paused", "restart"), 0, 0),
            ("child_started", "child_started", False, ("paused", "restart"), 0, 0),
            ("job_assigned", "job_assigned", False, ("paused", "restart"), 0, 0),
            ("ready", "ready", False, ("paused", "restart"), 0, 0),
            ("marked", "marked", False, ("outcome_unknown", "restart"), 0, 0),
            ("sent", "sent", False, ("outcome_unknown", "restart"), 0, "0..1"),
            ("result_received", "result_received", True, ("outcome_unknown", "restart"), 0, 1),
            ("persisted", "persisted", True, ("succeeded", None), 1, 1),
        ]
        results: dict[str, dict] = {}
        for name, kill_at, reply, (status, reason), candidates, requests in plan:
            result = self.scenario(
                name, kill_at, reply=reply, ca_path=ca_path, leaf=leaf
            )
            results[name] = result
            self.checks[f"{name}_status"] = result["status"] == status
            if reason is not None:
                self.checks[f"{name}_reason"] = result["reason"] == reason
            if name == "before_claim":
                self.checks[f"{name}_no_execution"] = result["executions"] == 0
            self.checks[f"{name}_candidates"] = result["candidates"] == candidates
            self.checks[f"{name}_no_open_attempt"] = result["open_attempts"] == 0
            if requests == "0..1":
                self.checks[f"{name}_requests_0or1"] = 0 <= result["requests_final"] <= 1
            else:
                self.checks[f"{name}_requests"] = result["requests_final"] == requests
            self.checks[f"{name}_no_resend"] = (
                result["requests_final"] == result["requests_after_run"]
            )
            self.checks[f"{name}_stable"] = bool(result["stable"])
            self.checks[f"{name}_integrity"] = result["integrity"] == "ok"
            self.checks[f"{name}_fk"] = result["foreign_keys"] == 0

        # A real crash after the HTTP request was actually sent (server-observed).
        http = self.scenario(
            "http_sent", "", reply=False, ca_path=ca_path, leaf=leaf, kill_on_http=True
        )
        results["http_sent"] = http
        self.checks["http_sent_status"] = http["status"] == "outcome_unknown"
        self.checks["http_sent_reason"] = http["reason"] == "restart"
        self.checks["http_sent_requests"] = http["requests_final"] == 1
        self.checks["http_sent_candidates"] = http["candidates"] == 0
        self.checks["http_sent_no_resend"] = (
            http["requests_final"] == http["requests_after_run"]
        )
        self.checks["http_sent_integrity"] = http["integrity"] == "ok"
        self.checks["http_sent_fk"] = http["foreign_keys"] == 0
        self.checks["http_sent_no_open_attempt"] = http["open_attempts"] == 0
        self.checks["http_sent_stable"] = bool(http["stable"])
        self.checks["http_sent_worker_gone"] = bool(http.get("worker_gone"))

        # Normal run (no kill): a real succeeded and a confirmed child exit.
        normal = self.scenario("normal", "", reply=True, ca_path=ca_path, leaf=leaf)
        results["normal"] = normal
        self.checks["normal_status"] = normal["status"] == "succeeded"
        self.checks["normal_candidate"] = normal["candidates"] == 1
        self.checks["normal_requests"] = normal["requests_final"] == 1
        self.checks["normal_dispose"] = bool(normal.get("dispose_confirmed"))
        self.checks["normal_integrity"] = normal["integrity"] == "ok"

        # A windowed build launched with no console output at all still works
        # and writes its evidence through --out.
        no_stdout = self.scenario(
            "no_stdout", "", reply=True, ca_path=ca_path, leaf=leaf, devnull=True
        )
        results["no_stdout"] = no_stdout
        self.checks["no_stdout_status"] = no_stdout["status"] == "succeeded"
        self.checks["no_stdout_dispose"] = bool(no_stdout.get("dispose_confirmed"))
        self.checks["no_stdout_candidate"] = no_stdout["candidates"] == 1

        # A frozen probe must be a GUI (no console) executable: the PE
        # Subsystem is 2 (Windows GUI) rather than 3 (console), so it never
        # opens a console window. Its evidence goes only through --out.
        subsystem = pe_subsystem(self.exe)
        self.checks["noconsole_subsystem"] = subsystem == 2
        # The probe writes structured evidence only through --out; the captured
        # stdout/stderr must not be needed for the run to be correct (the
        # no_stdout scenario also runs with the streams pointed at DEVNULL).
        self.checks["probe_out_written"] = all(
            (self.root / name / "phase.json").is_file()
            for name in ("normal", "persisted", "no_stdout")
        )
        return {
            "checks": self.checks,
            "results": results,
            "notes": self.notes,
            "ok": all(self.checks.values()),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the D2 W3 frozen probe")
    parser.add_argument("--package", help="探针包目录（默认 build/desktop-d2-w3/package/...）")
    parser.add_argument(
        "--clean",
        action="store_true",
        help="验证全部通过时才删除合成根（失败一律保留证据）",
    )
    parser.add_argument("--out", help="证据 JSON 输出")
    args = parser.parse_args()

    source = Path(args.package) if args.package else PACKAGE_DEFAULT
    if not (source / EXE_NAME).is_file():
        print(f"探针可执行文件缺失：{source / EXE_NAME}（先运行 build_d2_w3_probe.py）")
        return 2

    token = f"{random.randrange(16**8):08x}"
    root = Path(tempfile.gettempdir()) / f"kgm-d2-w3-frozen-{token}-中文 空格%#"
    report: dict = {"ok": False, "checks": {}, "results": {}, "root": str(root)}
    try:
        package = root / "package" / "KGNext-D2W3Probe"
        package.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, package)
        exe = package / EXE_NAME
        verifier = Verifier(exe, root)
        report = verifier.run()
        report.update(
            {
                "source_package": str(source),
                "package": str(package),
                "root": str(root),
                "exe_sha256": hashlib.sha256(exe.read_bytes()).hexdigest(),
                "path_env": system_only_env()["PATH"],
                "python_env_cleared": "PYTHONPATH" not in system_only_env()
                and "PYTHONHOME" not in system_only_env(),
            }
        )
    except Exception as exc:  # noqa: BLE001 - a script fault is still evidence
        import traceback

        report["script_failure"] = traceback.format_exc()
        report["script_failure_type"] = type(exc).__name__
        report["ok"] = False
    finally:
        # Failure evidence is always preserved; only a fully passing run with
        # --clean removes the synthetic root.
        if args.out:
            Path(args.out).write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        failed = [k for k, v in report.get("checks", {}).items() if not v]
        if report.get("ok") and args.clean:
            shutil.rmtree(root, ignore_errors=True)
            report["root_removed"] = True
        else:
            report["root_kept"] = True
        print(json.dumps({"ok": report.get("ok"), "failed": failed,
                          "root": str(root)}, ensure_ascii=False))
    return 0 if report.get("ok") else 3


if __name__ == "__main__":
    sys.exit(main())
