"""Shared helpers for the local (D1A) test suite.

Every test injects a temporary data directory; a guard keeps the resolved
database path under that temporary root so the real teacher directory
(``%LOCALAPPDATA%\\KindergartenManager\\data``) is never touched. HTTP is
exercised through a real Uvicorn server and the standard-library
``http.client`` (no TestClient/mocks), process tests spawn the worker
module, and direct SQLite access is used only for evidence and fault
injection.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from contextlib import contextmanager
from datetime import date, timedelta
from http.client import HTTPConnection
from pathlib import Path

import uvicorn

from app.local.app import create_local_app
from app.local.runtime import LocalRuntime
from app.services import calendar_service as cal

BACKEND_DIR = Path(__file__).resolve().parents[2]
WORKER_MODULE = "tests.local.worker"
DEFAULT_HOST = "127.0.0.1"


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((DEFAULT_HOST, 0))
        return int(sock.getsockname()[1])


def term_dates(start: date, end: date) -> list[date]:
    days: list[date] = []
    current = start
    while current <= end:
        days.append(current)
        current += timedelta(days=1)
    return days


class StaticCalendarProvider:
    """Deterministic calendar input provider (fixtures control the library)."""

    def __init__(
        self,
        *,
        version: str = "test-calendar-1.0",
        workdays: set[date] | None = None,
        weekend_workdays: set[date] | None = None,
        unknown_years: set[int] | None = None,
        fail: bool = False,
        fail_years: set[int] | None = None,
    ):
        self.version = version
        self._workdays = set(workdays) if workdays is not None else None
        self._weekend_workdays = set(weekend_workdays or ())
        self._unknown_years = set(unknown_years or ())
        self._fail = fail
        self._fail_years = set(fail_years or ())

    def is_workday(self, day: date) -> bool:
        if self._fail or day.year in self._fail_years:
            raise cal.CalendarLibraryError("injected calendar library failure")
        if day.year in self._unknown_years:
            raise NotImplementedError(f"no coverage for {day.year}")
        if self._workdays is not None:
            return day in self._workdays or day in self._weekend_workdays
        return day.isoweekday() <= 5 or day in self._weekend_workdays


@contextmanager
def calendar_provider(provider: StaticCalendarProvider):
    cal.register_provider(provider, provider.version)
    try:
        yield provider
    finally:
        cal.reset_provider()


def assert_inside(root: Path, path: Path) -> None:
    root = root.resolve()
    path = path.resolve()
    if root not in path.parents and path != root:
        raise AssertionError(f"test path escaped the temp root: {path}")


def sqlite_connect(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(db_path), timeout=30.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def query_rows(db_path: Path, sql: str, params: tuple = ()) -> list[dict]:
    connection = sqlite_connect(db_path)
    try:
        return [dict(row) for row in connection.execute(sql, params).fetchall()]
    finally:
        connection.close()


def query_scalar(db_path: Path, sql: str, params: tuple = ()):
    rows = query_rows(db_path, sql, params)
    if not rows:
        return None
    return rows[0][next(iter(rows[0]))]


def execute_sql(db_path: Path, sql: str, params: tuple = ()) -> None:
    connection = sqlite_connect(db_path)
    try:
        connection.execute(sql, params)
        connection.commit()
    finally:
        connection.close()


class LocalClient:
    """Minimal real-HTTP client with explicit token/origin/host control."""

    def __init__(self, port: int, token: str, host: str = DEFAULT_HOST):
        self.port = port
        self.token = token
        self.host = host
        self.origin = f"http://{host}:{port}"

    def request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        *,
        token: str | None = "__launch__",
        origin: str | None = "__default__",
        host: str | None = "__default__",
        timeout: float = 60.0,
    ) -> tuple[int, object]:
        headers: dict[str, str] = {}
        payload: bytes | None = None
        if body is not None:
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if token == "__launch__":
            token = self.token
        if origin == "__default__":
            origin = self.origin
        if host == "__default__":
            host = f"{self.host}:{self.port}"
        if token is not None:
            headers["X-App-Session"] = token
        if origin is not None:
            headers["Origin"] = origin
        if host is not None:
            headers["Host"] = host
        connection = HTTPConnection(self.host, self.port, timeout=timeout)
        try:
            connection.request(method, path, body=payload, headers=headers)
            response = connection.getresponse()
            raw = response.read().decode("utf-8")
            status = response.status
        finally:
            connection.close()
        if not raw:
            return status, None
        try:
            return status, json.loads(raw)
        except json.JSONDecodeError:
            return status, raw

    def get(self, path: str, **kwargs):
        return self.request("GET", path, **kwargs)

    def post(self, path: str, body: dict | None = None, **kwargs):
        return self.request("POST", path, body, **kwargs)

    def patch(self, path: str, body: dict | None = None, **kwargs):
        return self.request("PATCH", path, body, **kwargs)


class LocalServer:
    def __init__(
        self,
        runtime: LocalRuntime,
        token: str,
        host: str = DEFAULT_HOST,
        *,
        executor: object | None = None,
    ):
        self.runtime = runtime
        self.token = token
        self.host = host
        self.port = free_port()
        self.origin = f"http://{host}:{self.port}"
        self.app = create_local_app(
            port=self.port, session_token=token, runtime=runtime, executor=executor
        )
        config = uvicorn.Config(
            self.app,
            host=host,
            port=self.port,
            log_level="warning",
            access_log=False,
        )
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(
            target=self.server.run, name="local-test-server", daemon=True
        )

    def start(self) -> "LocalServer":
        self.thread.start()
        deadline = time.time() + 20
        while time.time() < deadline:
            if self.server.started:
                return self
            if not self.thread.is_alive():
                raise AssertionError("local test server thread exited")
            time.sleep(0.02)
        raise AssertionError("local test server did not start")

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=20)
        if self.thread.is_alive():
            raise AssertionError("local test server did not stop")

    def client(self) -> LocalClient:
        return LocalClient(self.port, self.token, self.host)


def initialize_body(**overrides) -> dict:
    body = {
        "request_id": str(uuid.uuid4()),
        "display_name": "王老师",
        "class_name": "中一班",
        "grade": "middle",
        "term_name": "2026 年秋季学期",
        "start_date": "2026-09-01",
        "end_date": "2026-09-30",
        "school_name": "示范幼儿园",
    }
    body.update(overrides)
    return body


def worker_env() -> dict:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(BACKEND_DIR) + (os.pathsep + existing if existing else "")
    env["APP_DISABLE_DOTENV"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def spawn_worker(spec: dict) -> subprocess.Popen:
    input_file = Path(spec["input_file"])
    input_file.write_text(
        json.dumps(spec, ensure_ascii=False, default=str), encoding="utf-8"
    )
    return subprocess.Popen(
        [sys.executable, "-m", WORKER_MODULE, str(input_file)],
        cwd=str(BACKEND_DIR),
        env=worker_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def collect_worker(process: subprocess.Popen, spec: dict, *, timeout: float = 120):
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate()
        raise AssertionError(
            f"worker timed out\nstdout={stdout.decode('utf-8', 'replace')}\n"
            f"stderr={stderr.decode('utf-8', 'replace')}"
        )
    if process.returncode != 0:
        raise AssertionError(
            f"worker failed rc={process.returncode}\n"
            f"stdout={stdout.decode('utf-8', 'replace')}\n"
            f"stderr={stderr.decode('utf-8', 'replace')}"
        )
    result_file = Path(spec["result_file"])
    if not result_file.is_file():
        raise AssertionError("worker produced no result file")
    return json.loads(result_file.read_text(encoding="utf-8"))


def run_worker(spec: dict, *, timeout: float = 120):
    return collect_worker(spawn_worker(spec), spec, timeout=timeout)


def wait_for_file(path: str | Path, *, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    target = Path(path)
    while time.monotonic() < deadline:
        if target.exists():
            return
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {target}")


class _LogCollector(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.lines.append(self.format(record))
        except Exception:  # noqa: BLE001 - a broken format must not hide the test
            self.lines.append(str(record.msg))


class ServerLogCapture:
    """Collect the log records Uvicorn/FastAPI write during a test.

    Uvicorn's protocol layer reports ASGI application exceptions (including
    ``ResponseValidationError``) through ``uvicorn.error``; the handler is
    attached to the named loggers so diagnostics can be asserted to contain
    no persisted content, paths or session material.
    """

    _LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi")

    def __init__(self) -> None:
        self._handler = _LogCollector()
        self._handler.setLevel(logging.DEBUG)
        self._attached: list[logging.Logger] = []
        for name in self._LOGGERS:
            logger = logging.getLogger(name)
            logger.addHandler(self._handler)
            self._attached.append(logger)

    def text(self) -> str:
        return "\n".join(self._handler.lines)

    def close(self) -> None:
        for logger in self._attached:
            logger.removeHandler(self._handler)
        self._attached.clear()


def capture_server_logs() -> ServerLogCapture:
    return ServerLogCapture()


class LocalTestCase(unittest.TestCase):
    """Temporary data root + runtimes/servers with automatic cleanup."""

    def setUp(self) -> None:
        self._tempdir = tempfile.TemporaryDirectory(prefix="kgm-d1a-test-")
        self.addCleanup(self._tempdir.cleanup)
        self.tmp_root = Path(self._tempdir.name)
        self.data_dir = self.tmp_root / "data"
        # Explicit synthetic credential root: no test ever reaches the real
        # teacher credential directory under the production %LOCALAPPDATA%.
        self.credential_root = self.tmp_root / "credentials"
        self.token = secrets.token_urlsafe(32)
        self._servers: list[LocalServer] = []
        self._workers: list[subprocess.Popen] = []
        self.addCleanup(self._reap_workers)

    # -- runtimes ---------------------------------------------------------
    def make_runtime(
        self,
        data_dir: Path | None = None,
        *,
        credential_root: Path | None = None,
    ) -> LocalRuntime:
        runtime = LocalRuntime(
            data_dir or self.data_dir,
            credential_root=credential_root or self.credential_root,
        )
        assert_inside(self.tmp_root, runtime.db_path)
        assert_inside(self.tmp_root, runtime.credential_root)
        runtime.prepare()
        self.addCleanup(runtime.dispose)
        return runtime

    # -- workers ----------------------------------------------------------
    def worker_spec(
        self,
        action: str,
        *,
        data_dir: Path | None = None,
        connect_only: bool = True,
    ) -> dict:
        """Spec for the cross-process worker.

        ``connect_only=True`` (the default) tells the worker to attach to an
        already-prepared synthetic database *without* migrating and *without*
        taking the runtime lock: the parent test remains the single lock owner.
        ``connect_only=False`` is used only by true restart flows where each
        worker fully owns and then releases the runtime in sequence.
        """
        name = f"worker-{action}-{secrets.token_hex(6)}"
        return {
            "action": action,
            "data_dir": str(data_dir or self.data_dir),
            "credential_root": str(self.credential_root),
            "connect_only": connect_only,
            "input_file": str(self.tmp_root / f"{name}.in.json"),
            "result_file": str(self.tmp_root / f"{name}.out.json"),
        }

    def spawn_worker(self, spec: dict) -> subprocess.Popen:
        """Spawn a worker and register it for guaranteed cleanup."""
        process = spawn_worker(spec)
        self._workers.append(process)
        return process

    def collect_worker(self, process: subprocess.Popen, spec: dict, *, timeout: float = 120):
        return collect_worker(process, spec, timeout=timeout)

    def run_worker(self, spec: dict, *, timeout: float = 120):
        return collect_worker(self.spawn_worker(spec), spec, timeout=timeout)

    def _reap_workers(self) -> None:
        """Kill and reap every worker this test spawned, closing its pipes.

        Runs on the failure path too, so a timed-out or crashed worker never
        leaves a stray process or unclosed pipe behind.
        """
        for process in self._workers:
            if process.poll() is None:
                process.kill()
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:  # pragma: no cover - defensive
                process.kill()
                process.wait(timeout=30)
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass

    # -- servers ----------------------------------------------------------
    def start_server(
        self, runtime: LocalRuntime | None = None, *, executor: object | None = None
    ) -> LocalServer:
        server = LocalServer(runtime or self.make_runtime(), self.token, executor=executor)
        server.start()
        self._servers.append(server)
        self.addCleanup(self._stop_server, server)
        return server

    def _stop_server(self, server: LocalServer) -> None:
        server.stop()

    # -- convenience ------------------------------------------------------
    def initialize(self, client: LocalClient, **overrides):
        status, payload = client.post("/api/local/initialize", initialize_body(**overrides))
        self.assertEqual(status, 201, payload)
        return payload

    def db_path(self, runtime: LocalRuntime | None = None) -> Path:
        return (runtime or self.make_runtime()).db_path

    def counts(self, db_path: Path) -> dict:
        tables = (
            "local_profile",
            "local_settings",
            "local_classes",
            "local_terms",
            "local_calendar_revisions",
            "local_calendar_days",
            "local_daily_plans",
            "local_daily_plan_contents",
            "local_operation_records",
        )
        return {
            table: query_scalar(db_path, f"SELECT count(*) AS n FROM {table}")
            for table in tables
        }
