"""Pure B3 network-guard regression tests.

These tests exercise only ``maintenance_source_guard.NetworkGuard`` and one
generated ordinary Python child interpreter.  They never create a LocalRuntime,
local service, AI executor, GUI, supplier client, WebDAV client, credential
store or installer, and they never read real teacher data or credentials.

Before install, the underlying socket functions are replaced with spies so a
non-loopback attempt proves it never reaches the real stack.  Loopback is tested
against a server this test binds on port 0.  Global socket functions are
restored after every test.  The child process is ended only through its own
Popen handle; no global process scan or kill is performed.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import pytest

from maintenance_source_guard import NetworkGuard


@pytest.fixture(autouse=True)
def _restore_socket_api():
    originals = (
        socket.getaddrinfo,
        socket.socket.connect,
        socket.socket.connect_ex,
    )
    try:
        yield
    finally:
        socket.getaddrinfo = originals[0]
        socket.socket.connect = originals[1]
        socket.socket.connect_ex = originals[2]


def _make_spies():
    calls: list[tuple[str, object]] = []

    def getaddrinfo(host, *args, **kwargs):
        calls.append(("getaddrinfo", host))
        return [("spy", host)]

    def connect(sock, address):
        calls.append(("connect", address))
        return "spy-connect"

    def connect_ex(sock, address):
        calls.append(("connect_ex", address))
        return 4242

    return calls, getaddrinfo, connect, connect_ex


def _wait_json(path: Path, process: subprocess.Popen, timeout: float):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
        if process.poll() is not None:
            return None
        time.sleep(0.02)
    return None


def _communicate(process: subprocess.Popen, timeout: float = 30.0):
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate()
        raise AssertionError("guard child timed out")
    return stdout.decode("utf-8", "replace"), stderr.decode("utf-8", "replace")


CHILD_WORKER_SOURCE = '''\
import json
import os
import socket
import sys
from pathlib import Path

TOKEN = os.environ["KGM_B3_GUARD_TOKEN"]
READY = Path(os.environ["KGM_B3_GUARD_READY"])
BLOCKED = Path(os.environ["KGM_B3_GUARD_BLOCKED"])
FAIL = Path(os.environ["KGM_B3_GUARD_FAIL"])
GUARD_DIR = Path(os.environ["KGM_B3_GUARD_DIR"]).resolve()
CHILD_LOG = os.environ.get("KGM_B3_NETWORK_GUARD_LOG", "")


def publish(target, data):
    payload = dict(data)
    payload.update(
        token=TOKEN,
        pid=os.getpid(),
        python=sys.executable,
        log=CHILD_LOG,
    )
    temp = target.with_name(target.name + ".tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(temp, target)


try:
    import sitecustomize
except BaseException as exc:
    publish(
        FAIL,
        {
            "stage": "sitecustomize-import",
            "error": type(exc).__name__,
            "message": str(exc),
        },
    )
    sys.exit(10)

loaded = (
    getattr(sitecustomize, "__file__", None) is not None
    and Path(sitecustomize.__file__).resolve()
    == (GUARD_DIR / "sitecustomize.py").resolve()
)
try:
    socket.getaddrinfo(
        "192.0.2.1",
        443,
        type=socket.SOCK_STREAM,
        flags=socket.AI_NUMERICHOST,
    )
except BaseException as exc:
    preflight = {"error": type(exc).__name__, "message": str(exc)}
else:
    publish(
        FAIL,
        {
            "stage": "preflight-not-blocked",
            "sitecustomize_loaded": loaded,
        },
    )
    sys.exit(11)

publish(
    READY,
    {
        "sitecustomize_loaded": loaded,
        "preflight_host": "192.0.2.1",
        "preflight_error": preflight["message"],
    },
)

try:
    socket.getaddrinfo(
        "198.51.100.1",
        443,
        type=socket.SOCK_STREAM,
        flags=socket.AI_NUMERICHOST,
    )
except BaseException as exc:
    publish(BLOCKED, {"error": type(exc).__name__, "message": str(exc)})
    sys.exit(0)

publish(FAIL, {"stage": "controlled-lookup-returned"})
sys.exit(12)
'''


def test_parent_guard_blocks_nonloopback_without_touching_spies(tmp_path):
    calls, spy_gai, spy_connect, spy_connect_ex = _make_spies()
    socket.getaddrinfo = spy_gai
    socket.socket.connect = spy_connect
    socket.socket.connect_ex = spy_connect_ex

    guard = NetworkGuard(tmp_path / "evidence")
    guard.install()
    try:
        dummy = object()
        with pytest.raises(OSError):
            socket.getaddrinfo("192.0.2.1", 443)
        assert calls == []
        with pytest.raises(OSError):
            socket.socket.connect(dummy, ("192.0.2.1", 443))
        assert calls == []
        try:
            result = socket.socket.connect_ex(dummy, ("192.0.2.1", 443))
        except OSError:
            result = None
        assert result is None or result != 0
        assert calls == []
        assert guard.attempts() == 3

        log_lines = [
            line
            for line in guard.log_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert "192.0.2.1" in guard.log_path.read_text(encoding="utf-8")
        assert len(log_lines) >= 3

        before = guard.attempts()
        assert socket.getaddrinfo("127.0.0.1", 443) == [
            ("spy", "127.0.0.1")
        ]
        assert socket.getaddrinfo("localhost", 443) == [
            ("spy", "localhost")
        ]
        assert socket.getaddrinfo(None, 443) == [("spy", None)]
        assert (
            socket.socket.connect(dummy, ("127.0.0.1", 9))
            == "spy-connect"
        )
        assert (
            socket.socket.connect_ex(dummy, ("127.0.0.1", 9))
            == 4242
        )
        assert guard.attempts() == before
    finally:
        guard.uninstall()

    assert socket.getaddrinfo is spy_gai
    assert socket.socket.connect is spy_connect
    assert socket.socket.connect_ex is spy_connect_ex
    calls.clear()
    assert socket.getaddrinfo("example.com", 443) == [
        ("spy", "example.com")
    ]
    assert calls == [("getaddrinfo", "example.com")]
    assert guard.attempts() == 3


def test_install_uninstall_restores_and_is_idempotent(tmp_path):
    originals = (
        socket.getaddrinfo,
        socket.socket.connect,
        socket.socket.connect_ex,
    )
    guard = NetworkGuard(tmp_path / "evidence")
    guard.install()
    installed = (
        socket.getaddrinfo,
        socket.socket.connect,
        socket.socket.connect_ex,
    )
    assert installed != originals
    guard.install()
    assert (
        socket.getaddrinfo,
        socket.socket.connect,
        socket.socket.connect_ex,
    ) == installed
    guard.uninstall()
    assert (
        socket.getaddrinfo,
        socket.socket.connect,
        socket.socket.connect_ex,
    ) == originals
    guard.uninstall()
    assert (
        socket.getaddrinfo,
        socket.socket.connect,
        socket.socket.connect_ex,
    ) == originals
    assert guard.attempts() == 0


def test_loopback_to_owned_server_is_allowed(tmp_path):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    server.settimeout(10)
    port = int(server.getsockname()[1])
    accepted: list[object] = []
    finished = threading.Event()

    def serve_one():
        try:
            connection, address = server.accept()
            accepted.append(address)
            connection.close()
        except BaseException as exc:  # noqa: BLE001 - reported to the test
            accepted.append(exc)
        finally:
            finished.set()

    thread = threading.Thread(target=serve_one, daemon=True)
    thread.start()
    guard = NetworkGuard(tmp_path / "evidence")
    guard.install()
    try:
        assert socket.getaddrinfo("127.0.0.1", port)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            client.settimeout(10)
            client.connect(("127.0.0.1", port))
        assert finished.wait(10)
        assert accepted and not isinstance(accepted[0], BaseException)
        assert guard.attempts() == 0
    finally:
        guard.uninstall()
        server.close()
        thread.join(timeout=5)


def test_log_write_failure_keeps_nonzero_attempts(tmp_path):
    evidence = tmp_path / "evidence"
    guard = NetworkGuard(evidence)
    initial_log = evidence / "guard-log-initial-before-write-failure.txt"
    if guard.log_path.exists():
        assert guard.log_path.is_file(), (
            f"unexpected initial log type: {guard.log_path}"
        )
        guard.log_path.replace(initial_log)
        assert initial_log.is_file(), f"evidence={evidence}"
    guard.log_path.mkdir()
    guard.install()
    try:
        with pytest.raises(OSError):
            socket.getaddrinfo("192.0.2.1", 443)
        assert guard.attempts() == 1, f"evidence={evidence}"
        audit_ok = getattr(guard, "audit_ok", None)
        if audit_ok is not None:
            assert audit_ok() is False, f"evidence={evidence}"
        log_attempts = getattr(guard, "log_attempts", None)
        if log_attempts is not None:
            try:
                value = log_attempts()
            except BaseException:
                value = "raised"
            assert value != 0, (
                "a blocked attempt with an unavailable log must not be "
                f"reported as zero; evidence={evidence}"
            )
    finally:
        guard.uninstall()


def test_log_read_failure_after_blocked_attempt_does_not_report_zero(tmp_path):
    evidence = tmp_path / "evidence"
    guard = NetworkGuard(evidence)
    guard.install()
    log_attempts = getattr(guard, "log_attempts", None)
    try:
        with pytest.raises(OSError):
            socket.getaddrinfo("192.0.2.1", 443)
        assert guard.attempts() == 1, f"evidence={evidence}"
        if log_attempts is None:
            pytest.skip(
                "guard exposes no log count; in-memory attempts stayed nonzero"
            )
        assert guard.log_path.is_file(), f"evidence={evidence}"
        preserved = evidence / "guard-log-before-read-failure.txt"
        preserved.write_text(
            guard.log_path.read_text(encoding="utf-8"), encoding="utf-8"
        )
        guard.log_path.unlink()
        try:
            value = log_attempts()
        except BaseException:
            value = "raised"
        assert value != 0, (
            "a blocked attempt with a missing/unreadable log must not be "
            f"reported as zero; evidence={evidence}"
        )
    finally:
        guard.uninstall()


def test_child_interpreter_proves_guard_then_blocks_controlled_lookup(tmp_path):
    evidence = tmp_path / "evidence"
    guard = NetworkGuard(evidence)
    guard_dir = guard.install_child_guard()
    assert (guard_dir / "sitecustomize.py").is_file()

    worker = tmp_path / "guard_child_worker.py"
    worker.write_text(CHILD_WORKER_SOURCE, encoding="utf-8")
    token = uuid.uuid4().hex
    ready = tmp_path / "child-ready.json"
    blocked = tmp_path / "child-blocked.json"
    fail = tmp_path / "child-fail.json"
    child_log = evidence / "child-network-guard.log"

    child_temp = tmp_path / "child-temp"
    child_local = tmp_path / "child-localappdata"
    child_temp.mkdir()
    child_local.mkdir()

    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(guard_dir) + (
        os.pathsep + existing if existing else ""
    )
    env["KGM_B3_NETWORK_GUARD_LOG"] = str(child_log)
    env["KGM_B3_GUARD_DIR"] = str(guard_dir)
    env["KGM_B3_GUARD_TOKEN"] = token
    env["KGM_B3_GUARD_READY"] = str(ready)
    env["KGM_B3_GUARD_BLOCKED"] = str(blocked)
    env["KGM_B3_GUARD_FAIL"] = str(fail)
    env["PYTHONNOUSERSITE"] = "1"
    env["TEMP"] = str(child_temp)
    env["TMP"] = str(child_temp)
    env["LOCALAPPDATA"] = str(child_local)

    executable = getattr(sys, "_base_executable", sys.executable)
    process = subprocess.Popen(
        [executable, str(worker)],
        cwd=str(tmp_path),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        ready_data = _wait_json(ready, process, 30)
        if ready_data is None:
            stdout, stderr = _communicate(process)
            fail_data = (
                json.loads(fail.read_text(encoding="utf-8"))
                if fail.is_file()
                else None
            )
            raise AssertionError(
                "child did not prove the guard before the controlled lookup: "
                f"rc={process.returncode} fail={fail_data} "
                f"stdout={stdout!r} stderr={stderr!r} evidence={evidence}"
            )
        assert ready_data["token"] == token
        assert ready_data["pid"] == process.pid
        assert ready_data["python"] == executable
        assert ready_data["sitecustomize_loaded"] is True
        assert ready_data["preflight_host"] == "192.0.2.1"
        assert ready_data["preflight_error"], ready_data

        stdout, stderr = _communicate(process)
        assert process.returncode == 0, (
            f"child rc={process.returncode} stdout={stdout!r} "
            f"stderr={stderr!r} evidence={evidence}"
        )
        blocked_data = json.loads(blocked.read_text(encoding="utf-8"))
        assert blocked_data["token"] == token
        assert blocked_data["error"]
        assert blocked_data["message"]
        text = child_log.read_text(encoding="utf-8")
        assert "198.51.100.1" in text, f"evidence={evidence}"
        assert [line for line in text.splitlines() if line.strip()]
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass
