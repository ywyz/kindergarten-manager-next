"""Hard loopback-only network guard for the B3 source-window verifier.

Installed before any LocalRuntime/executor/fixture is created.  A temporary
``sitecustomize.py`` applies the same guard to Python multiprocessing workers;
the guard log is evidence of blocked attempts, not an OS packet-capture claim.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

_LOOPBACK = {"127.0.0.1", "::1", "localhost", None}
_LOCK = threading.Lock()


class NetworkGuard:
    def __init__(self, evidence_dir: Path):
        self.log_path = Path(evidence_dir) / "network-guard.log"
        self.failure_path = Path(evidence_dir) / "guard-child-failure.txt"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._installed = False
        self._originals = None
        self._attempt_count = 0
        self._audit_ok = True
        self._log_initialized = False
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            self.log_path.touch(exist_ok=True)
            self._log_initialized = True
        except OSError:
            self._audit_ok = False

    def _record(self, kind: str, value: object) -> None:
        with _LOCK:
            # The in-memory count is authoritative even when the evidence
            # file is unavailable; audit failure is fail-closed, never zero.
            self._attempt_count += 1
            try:
                with self.log_path.open("a", encoding="utf-8") as handle:
                    handle.write(f"{time.time():.6f} {kind} {value!r}\n")
                    handle.flush()
            except OSError:
                self._audit_ok = False

    @staticmethod
    def _allowed(host: object) -> bool:
        return host in _LOOPBACK or (
            isinstance(host, str) and host.lower() in _LOOPBACK
        )

    def install(self) -> None:
        if self._installed:
            return
        orig_gai = socket.getaddrinfo
        orig_connect = socket.socket.connect
        orig_connect_ex = socket.socket.connect_ex

        def guarded_gai(host, *args, **kwargs):
            if self._allowed(host):
                return orig_gai(host, *args, **kwargs)
            self._record("getaddrinfo", host)
            raise OSError("B3_NETWORK_BLOCKED")

        def guarded_connect(sock, address):
            host = address[0] if isinstance(address, tuple) and address else address
            if self._allowed(host):
                return orig_connect(sock, address)
            self._record("connect", host)
            raise OSError("B3_NETWORK_BLOCKED")

        def guarded_connect_ex(sock, address):
            host = address[0] if isinstance(address, tuple) and address else address
            if self._allowed(host):
                return orig_connect_ex(sock, address)
            self._record("connect_ex", host)
            return 10013

        self._originals = (orig_gai, orig_connect, orig_connect_ex)
        socket.getaddrinfo = guarded_gai
        socket.socket.connect = guarded_connect
        socket.socket.connect_ex = guarded_connect_ex
        self._installed = True

    def uninstall(self) -> None:
        if not self._installed or self._originals is None:
            return
        orig_gai, orig_connect, orig_connect_ex = self._originals
        socket.getaddrinfo = orig_gai
        socket.socket.connect = orig_connect
        socket.socket.connect_ex = orig_connect_ex
        self._installed = False

    def install_child_guard(self) -> Path:
        guard_dir = self.log_path.parent / "guard"
        guard_dir.mkdir(parents=True, exist_ok=True)
        (guard_dir / "sitecustomize.py").write_text(
            CHILD_GUARD_SOURCE, encoding="utf-8"
        )
        return guard_dir

    def verify_child_guard(self, timeout: float = 30.0) -> bool:
        """Prove a real spawned Python interpreter loads and enforces the guard.

        This is a pure guard self-test: no LocalRuntime, service, executor or
        GUI is created.  A child that cannot audit its log is a failure, not
        an assumed zero.
        """
        guard_dir = self.install_child_guard()
        ready = self.log_path.parent / "guard-child-ready.txt"
        blocked = self.log_path.parent / "guard-child-blocked.txt"
        self_test_log = self.log_path.parent / "network-guard-child-selftest.log"
        for path in (ready, blocked):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        code = """
import os,sys
try:
    open(os.environ['KGM_B3_NETWORK_GUARD_LOG'],'a',encoding='utf-8').write('child-start')
except OSError:
    sys.exit(4)
open(os.environ['KGM_B3_GUARD_READY'],'w',encoding='utf-8').write('ready')
import socket
try:
    socket.getaddrinfo('blocked.invalid',443)
except OSError as exc:
    if 'B3_NETWORK_BLOCKED' not in str(exc):
        sys.exit(2)
    open(os.environ['KGM_B3_GUARD_BLOCKED'],'w',encoding='utf-8').write(str(exc))
    sys.exit(0)
sys.exit(3)
"""
        env = dict(os.environ)
        env["PYTHONPATH"] = str(guard_dir) + (
            os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
        )
        env["KGM_B3_NETWORK_GUARD_LOG"] = str(self_test_log)
        env["KGM_B3_GUARD_FAILURE"] = str(self.failure_path)
        env["KGM_B3_GUARD_READY"] = str(ready)
        env["KGM_B3_GUARD_BLOCKED"] = str(blocked)
        try:
            completed = subprocess.run(
                [sys.executable, "-c", code],
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except Exception:
            return False
        return (
            completed.returncode == 0
            and not self.failure_path.exists()
            and ready.is_file()
            and blocked.is_file()
            and "B3_NETWORK_BLOCKED" in blocked.read_text(encoding="utf-8")
        )

    def attempts(self) -> int:
        with _LOCK:
            return int(self._attempt_count)

    def audit_ok(self) -> bool:
        with _LOCK:
            return bool(self._audit_ok) and not self.failure_path.exists()

    def log_attempts(self) -> int | None:
        """Count logged attempts; None means the audit state is unknown.

        A missing file is only 0 when this guard never initialized a log and
        never saw an attempt.  After initialization/attempts, deletion or an
        unreadable file is unknown, never a fabricated zero.
        """
        try:
            return sum(
                1
                for line in self.log_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            )
        except FileNotFoundError:
            if self._log_initialized or self._attempt_count:
                self._audit_ok = False
                return None
            return 0
        except OSError:
            self._audit_ok = False
            return None


CHILD_GUARD_SOURCE = """import atexit
import os
import socket
import time

_LOG = os.environ.get("KGM_B3_NETWORK_GUARD_LOG")
_AUDIT_FAILED = False
_ALLOWED = {"127.0.0.1", "::1", "localhost", None}
_orig_gai = socket.getaddrinfo
_orig_connect = socket.socket.connect
_orig_connect_ex = socket.socket.connect_ex


def _record(kind, value):
    if not _LOG:
        return
    try:
        with open(_LOG, "a", encoding="utf-8") as handle:
            handle.write("%.6f %s %r\\n" % (time.time(), kind, value))
            handle.flush()
    except OSError as exc:
        global _AUDIT_FAILED
        _AUDIT_FAILED = True
        failure = os.environ.get("KGM_B3_GUARD_FAILURE")
        if failure:
            try:
                fd = os.open(
                    failure, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600
                )
                try:
                    os.write(fd, b"audit-write-failed")
                finally:
                    os.close(fd)
            except OSError:
                pass
        raise OSError("B3_GUARD_AUDIT_FAILED") from exc


def _force_exit_on_audit_failure():
    if _AUDIT_FAILED:
        os._exit(70)


atexit.register(_force_exit_on_audit_failure)


def _allowed(host):
    return host in _ALLOWED or (isinstance(host, str) and host.lower() in _ALLOWED)


def _gai(host, *args, **kwargs):
    if _allowed(host):
        return _orig_gai(host, *args, **kwargs)
    _record("child-getaddrinfo", host)
    raise OSError("B3_NETWORK_BLOCKED")


def _connect(sock, address):
    host = address[0] if isinstance(address, tuple) and address else address
    if _allowed(host):
        return _orig_connect(sock, address)
    _record("child-connect", host)
    raise OSError("B3_NETWORK_BLOCKED")


def _connect_ex(sock, address):
    host = address[0] if isinstance(address, tuple) and address else address
    if _allowed(host):
        return _orig_connect_ex(sock, address)
    _record("child-connect_ex", host)
    return 10013


socket.getaddrinfo = _gai
socket.socket.connect = _connect
socket.socket.connect_ex = _connect_ex
"""
