"""Parent-driven restore crash worker for the B2 fault matrix.

Only the test suite starts this module.  Two modes exist:

``restore_kill``
    Open the target runtime, run the real restore core up to one named
    group-rename boundary, write a marker *after* the actual
    ``MoveFileExW``/group helper returned but before the journal phase is
    updated, then wait forever.  The parent reads the marker and terminates
    this one process through its own ``Popen`` handle (Windows
    ``TerminateProcess``).  This module never calls ``os._exit``, never
    enumerates processes and never kills anything by image name, so the
    evidence is a real process termination, not a simulated power loss.

``resume``
    Start a fresh process, run ``LocalRuntime.prepare()`` (which resolves the
    interrupted restore before schema inspection, migration, prompt sync, AI
    or HTTP), and report the notice, counts, receipt state and whether a
    requested normal edit exists.  Controlled startup refusals are reported as
    a typed ``error_code`` with exit 0 so the parent can assert them without
    losing the output.

Every mode installs a socket guard: any connect/getaddrinfo attempt is counted
and refused, proving the restore core starts no supplier request and no real
AI executor.
"""

from __future__ import annotations

import json
import os
import socket
import sqlite3
import sys
import threading
import uuid
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import text

from app.local import observation_service, restore_journal
from app.local.errors import LocalDatabaseStateError
from app.local.restore_fs import operation_paths
from app.local.restore_service import RestoreCore
from app.local.restore_types import RestoreFailure
from app.local.runtime import LocalRuntime


APP_VERSION = "restore-crash-test"
RESUME_TIMEOUT_SECONDS = 600


class NetworkGuard:
    """Count and refuse every outbound socket attempt in this process."""

    def __init__(self) -> None:
        self.attempts: list[str] = []
        self._connect = None
        self._connect_ex = None
        self._getaddrinfo = None

    def __enter__(self) -> "NetworkGuard":
        self._connect = socket.socket.connect
        self._connect_ex = socket.socket.connect_ex
        self._getaddrinfo = socket.getaddrinfo

        def refuse_connect(sock, address):  # noqa: ANN001
            self.attempts.append(f"connect:{address!r}"[:200])
            raise OSError("network disabled by restore crash harness")

        def refuse_connect_ex(sock, address):  # noqa: ANN001
            self.attempts.append(f"connect_ex:{address!r}"[:200])
            raise OSError("network disabled by restore crash harness")

        def refuse_getaddrinfo(host, port, *args, **kwargs):  # noqa: ANN001
            self.attempts.append(f"getaddrinfo:{host!r}:{port!r}"[:200])
            raise OSError("network disabled by restore crash harness")

        socket.socket.connect = refuse_connect
        socket.socket.connect_ex = refuse_connect_ex
        socket.getaddrinfo = refuse_getaddrinfo
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self._connect is not None:
            socket.socket.connect = self._connect
        if self._connect_ex is not None:
            socket.socket.connect_ex = self._connect_ex
        if self._getaddrinfo is not None:
            socket.getaddrinfo = self._getaddrinfo


class _Hooks:
    def wait_host_idle(self, cancel) -> bool:
        return not cancel.is_set()

    def stop_transport(self) -> bool:
        return True


def _write_json(path: str | Path, data: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f".{target.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}")
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, target)


def _paths(spec: dict, operation_id: str):
    return operation_paths(
        SimpleNamespace(
            data_dir=spec["data_dir"],
            credential_root=spec["credential_root"],
        ),
        operation_id,
        create=False,
    )


def _journal_view(spec: dict, operation_id: str) -> dict | None:
    try:
        journal = restore_journal.read_journal(_paths(spec, operation_id))
    except RestoreFailure as exc:
        return {"error_code": exc.code}
    if journal is None:
        return None
    return {
        "phase": journal.get("phase"),
        "terminal": bool(journal.get("terminal")),
        "rollback_authority": bool(journal.get("rollback_authority")),
        "first_live_change_at": journal.get("first_live_change_at"),
    }


def _marker_payload(spec: dict, stage: str, guard: NetworkGuard) -> dict:
    operation_id = spec["operation_id"]
    paths = _paths(spec, operation_id)
    data_dir = Path(spec["data_dir"])
    return {
        "mode": spec["mode"],
        "stage": stage,
        "pid": os.getpid(),
        "python_executable": sys.executable,
        "python_prefix": sys.prefix,
        "operation_id": operation_id,
        "journal": _journal_view(spec, operation_id),
        "journal_exists": paths.journal_path.is_file(),
        "receipt_exists": restore_journal.receipt_path(paths, operation_id).is_file(),
        "live_main": (data_dir / "kindergarten.db").is_file(),
        "old_main": (paths.old_dir / "db" / "kindergarten.db").is_file(),
        "prepared_main": (paths.prepared_dir / "db" / "kindergarten.db").is_file(),
        "live_assets": (data_dir / "observations" / "assets").is_dir(),
        "old_assets": (paths.old_dir / "assets").is_dir(),
        "prepared_assets": (paths.prepared_dir / "assets").is_dir(),
        "network_attempts": list(guard.attempts),
    }


def _counts(db_path: str | Path) -> dict:
    connection = sqlite3.connect(str(db_path))
    try:
        def count(table: str) -> int:
            return int(
                connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            )

        return {
            "profile": count("local_profile"),
            "daily_plans": count("local_daily_plans"),
            "daily_plan_contents": count("local_daily_plan_contents"),
            "observation_records": count("local_observation_records"),
            "observation_assets": count("local_observation_assets"),
        }
    finally:
        connection.close()


def _observation_present(db_path: str | Path, observation_id: str) -> bool:
    connection = sqlite3.connect(str(db_path))
    try:
        row = connection.execute(
            "SELECT 1 FROM local_observation_records WHERE id = ?",
            (observation_id,),
        ).fetchone()
        return row is not None
    finally:
        connection.close()


def _restore_kill(spec: dict) -> dict:
    guard = NetworkGuard()
    runtime = LocalRuntime(
        spec["data_dir"], credential_root=spec["credential_root"]
    )
    result: dict = {"mode": spec["mode"], "ok": False}
    stop = threading.Event()
    kill_stage = str(spec.get("kill_stage") or "")

    def fault(stage: str) -> None:
        if not kill_stage or stage != kill_stage:
            return
        _write_json(spec["marker_file"], _marker_payload(spec, stage, guard))
        stop.wait(RESUME_TIMEOUT_SECONDS)

    try:
        with guard:
            runtime.prepare()
            core = RestoreCore(
                runtime,
                app_version=str(spec.get("app_version") or APP_VERSION),
                fault_injector=fault,
            )
            cancel = threading.Event()
            preview = core.preview(
                spec["package"],
                None,
                operation_id=spec["operation_id"],
                cancel=cancel,
            )
            prepared = core.prepare(preview, cancel=cancel)
            installed = core.install(prepared, hooks=_Hooks(), cancel=cancel)
            result.update(
                ok=installed.state == "installed_retired",
                state=installed.state,
                warnings=list(installed.warnings),
                counts=_counts(runtime.db_path),
                ai_executor_present=getattr(runtime, "ai_executor", None) is not None,
                python_executable=sys.executable,
                python_prefix=sys.prefix,
                network_attempts=list(guard.attempts),
            )
            return result
    finally:
        try:
            runtime.dispose()
        finally:
            result.setdefault("network_attempts", list(guard.attempts))


def _resume(spec: dict) -> dict:
    operation_id = spec["operation_id"]
    paths = _paths(spec, operation_id)
    guard = NetworkGuard()
    runtime = LocalRuntime(
        spec["data_dir"], credential_root=spec["credential_root"]
    )
    result: dict = {
        "mode": spec["mode"],
        "operation_id": operation_id,
        "ok": False,
        "journal_exists": paths.journal_path.is_file(),
        "receipt_exists": restore_journal.receipt_path(paths, operation_id).is_file(),
        "python_executable": sys.executable,
        "python_prefix": sys.prefix,
    }
    try:
        with guard:
            try:
                runtime.prepare()
            except LocalDatabaseStateError as exc:
                result.update(
                    ok=False,
                    error_code=exc.code,
                    error_message=exc.message,
                    journal_exists=paths.journal_path.is_file(),
                    receipt_exists=restore_journal.receipt_path(
                        paths, operation_id
                    ).is_file(),
                )
                return result
            notice = runtime.restore_notice
            result.update(
                ok=True,
                notice=notice,
                notice_state=(notice or {}).get("state"),
                revision=runtime.current_revision,
                prompt_sync_error=getattr(runtime, "prompt_sync_error", None),
                ai_executor_present=getattr(runtime, "ai_executor", None) is not None,
                counts=_counts(runtime.db_path),
            )
            expected = spec.get("expect_observation_id")
            if expected:
                result["expected_observation_present"] = _observation_present(
                    runtime.db_path, str(expected)
                )
            if spec.get("write"):
                session = runtime.session()
                try:
                    profile_id = session.execute(
                        text("SELECT id FROM local_profile LIMIT 1")
                    ).scalar_one()
                    created = observation_service.create_observation(
                        session,
                        profile_id=profile_id,
                        request_id=uuid.uuid4().hex,
                        record_type="public",
                        payload={
                            "observation_date": "2026-09-24",
                            "record_type": "public",
                            "subjects": [{"name": "恢复后新写"}],
                            "environment": "积木区",
                            "observation_goal": "恢复后新写",
                            "observation_process": "恢复后全新进程保存的合成观察。",
                            "support_strategy": "",
                        },
                    )
                    session.commit()
                    result["written_observation_id"] = created["observation_id"]
                    result["written_observation_present"] = _observation_present(
                        runtime.db_path, created["observation_id"]
                    )
                finally:
                    session.close()
                result["counts"] = _counts(runtime.db_path)
            journal = restore_journal.read_journal(paths)
            receipt = restore_journal.read_receipt(paths, operation_id)
            result.update(
                journal_exists=paths.journal_path.is_file(),
                receipt_exists=restore_journal.receipt_path(
                    paths, operation_id
                ).is_file(),
                journal_after=(
                    None
                    if journal is None
                    else {
                        "phase": journal.get("phase"),
                        "terminal": bool(journal.get("terminal")),
                    }
                ),
                receipt_terminal=(
                    None if receipt is None else bool(receipt.get("terminal"))
                ),
            )
            return result
    finally:
        try:
            runtime.dispose()
        finally:
            result["network_attempts"] = list(guard.attempts)


def main() -> int:
    spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    result_file = Path(spec["result_file"])
    try:
        mode = str(spec.get("mode") or "")
        if mode == "restore_kill":
            result = _restore_kill(spec)
        elif mode == "resume":
            result = _resume(spec)
        else:
            raise RuntimeError(f"unknown restore crash worker mode: {mode!r}")
        rc = 0
    except BaseException as exc:  # noqa: BLE001 - the parent needs the failure
        result = {
            "mode": spec.get("mode"),
            "ok": False,
            "error": type(exc).__name__,
            "error_message": str(exc)[:1000],
        }
        rc = 1
    _write_json(result_file, result)
    return rc


if __name__ == "__main__":
    sys.exit(main())
