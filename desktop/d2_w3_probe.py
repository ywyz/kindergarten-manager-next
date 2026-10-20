"""D2 W3 minimal frozen spawn probe (no window, no UI).

Verifies the real executor/worker/transport in a *frozen* PyInstaller package:
the same production worker and transport, a real Windows Job Object, real TLS
against a controlled local server, and the JSON-bytes IPC. It is driven by
``verify_d2_w3_probe.py`` and mirrors the process-crash windows of G09 by
exiting abruptly at a chosen event (the Job kills the child; the reboot
classification must then match the persisted evidence).

Phases:

* ``setup`` — create the synthetic data root, prepare the runtime, initialize
  the single profile, configure the AI endpoint (synthetic TLS server) and
  create one split task. Writes the ids to ``--out``.
* ``run`` — start the executor with the synthetic transport and exit at
  ``--kill-at`` (a parent-crash simulation).
* ``recover`` — cold-start classification only; never starts an outbound
  request. Writes the task/execution/candidate facts to ``--out``.

The synthetic transport (fixed 127.0.0.1 resolution + the test CA) is only ever
supplied through this dedicated verification entry.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _bootstrap_backend() -> None:
    """Put the backend package on sys.path for a source (non-frozen) run."""
    if getattr(sys, "frozen", False):
        return
    here = Path(__file__).resolve()
    backend = here.parents[1] / "backend"
    if backend.is_dir() and str(backend) not in sys.path:
        sys.path.insert(0, str(backend))


_bootstrap_backend()

# Divert the frozen spawn child bootstrap before any other side effect (a
# no-op in the parent and in a source run).
from app.local.ai_spawn import freeze_support_guarded  # noqa: E402

freeze_support_guarded()


def _bootstrap_backend() -> None:
    """Put the backend package on sys.path for a source (non-frozen) run."""
    if getattr(sys, "frozen", False):
        return
    here = Path(__file__).resolve()
    backend = here.parents[1] / "backend"
    if backend.is_dir() and str(backend) not in sys.path:
        sys.path.insert(0, str(backend))


def _out(path: str, payload: dict) -> None:
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def phase_setup(args) -> int:
    from app.local import ai_config_service, daily_plan_service, profile_service
    from app.local.normalize import normalize_initialization
    from app.local.runtime import LocalRuntime

    os.environ["KGM_LOCAL_DATA_DIR"] = str(Path(args.data).resolve())
    runtime = LocalRuntime(args.data, credential_root=args.cred)
    try:
        runtime.prepare()
        session = runtime.session()
        try:
            from datetime import date

            profile_service.initialize(
                session,
                normalize_initialization(
                    request_id="11111111-1111-4111-8111-111111111111",
                    display_name="探针教师",
                    class_name="探针中一班",
                    grade="middle",
                    term_name="2026 年秋季学期",
                    start_date="2026-09-01",
                    end_date="2026-12-31",
                    school_name="探针幼儿园",
                ),
            )
            session.commit()
            ai_config_service.patch_config(
                session,
                expected_ai_config_version=0,
                base_url="https://api.example.com/v1",
                model="probe-model",
                secret="probe-secret",
                secret_provided=True,
                request_id="22222222-2222-4222-8222-222222222222",
                credential_root=runtime.credential_root,
            )
            plan, _created = daily_plan_service.create_or_open(
                session,
                plan_date=date(2026, 9, 2),
                raw_lesson_plan="探针原始教案：一、导入；二、观察；三、比较。",
                adopted_content={
                    "group_activity": {"process": "一、导入\n二、观察"},
                    "reflection": "探针反思",
                },
            )
            from app.local import ai_task_service

            task = ai_task_service.create_task(
                session,
                plan_id=plan["id"],
                task_type="daily_lesson_split",
                expected_content_version=1,
                target_grade="middle",
                request_id="33333333-3333-4333-8333-333333333333",
            )[0]
        finally:
            session.close()
        _out(args.out, {"plan_id": plan["id"], "task_id": task["id"]})
        _write_state(args.out, task_id=task["id"], plan_id=plan["id"])
        return 0
    finally:
        runtime.dispose()


def _state_path(out: str) -> str:
    return str(Path(out).with_suffix(".state.json"))


def _write_state(out: str, **fields) -> None:
    path = Path(_state_path(out))
    data = {}
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            data = {}
    data.update(fields)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_state(args) -> dict:
    path = Path(_state_path(args.out))
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _task_id(args) -> str:
    return _read_state(args).get("task_id") or ""


def phase_run(args) -> int:
    import time
    import uuid as _uuid

    from app.local import ai_task_service
    from app.local.ai_executor import AiExecutor
    from app.local.models import LocalAITask
    from app.local.runtime import LocalRuntime
    from sqlalchemy import text

    os.environ["KGM_LOCAL_DATA_DIR"] = str(Path(args.data).resolve())
    runtime = LocalRuntime(args.data, credential_root=args.cred)
    runtime.prepare()
    kill_at = args.kill_at or ""
    ca_pem = Path(args.ca).read_text(encoding="utf-8") if args.ca else None
    task_id = _task_id(args)

    facts: dict = {"events": [], "worker_pid": None, "armed": False}

    def on_event(name, _claim, info=None):
        facts["events"].append(name)
        if name in ("child_started", "job_assigned") and isinstance(info, dict):
            pid = info.get("pid")
            if isinstance(pid, int):
                facts["worker_pid"] = pid
                _write_state(args.out, worker_pid=pid)
        if kill_at and facts["armed"] and name == kill_at:
            # Parent-crash simulation: the OS closes the Job handle, which
            # kills the child via KILL_ON_JOB_CLOSE.
            os._exit(9)

    executor = AiExecutor(
        runtime,
        synthetic_transport={
            "resolution": [
                {"family": 2, "ip": "127.0.0.1", "port": int(args.port)}
            ],
            "ca_pem": ca_pem,
        },
        on_event=on_event,
    )
    if kill_at:
        # Pending-close barrier BEFORE start: the coordinator must not claim
        # before the explicit resume/unfreeze below.
        executor.freeze()
    executor.start()
    if task_id:
        # Cold-start recovery correctly paused the pre-existing task; an
        # explicit manual resume is the real product path back to a claim.
        session = runtime.session()
        try:
            task = session.get(LocalAITask, task_id, populate_existing=True)
            if task is not None and task.status == "paused":
                ai_task_service.resume_task(
                    session,
                    task_id=task_id,
                    expected_execution_id=task.current_execution_id,
                    request_id=str(_uuid.uuid4()),
                )
        finally:
            session.close()
    # Arm the kill point only after the resume, so no event is missed and the
    # harmless first-loop event is never the target.
    facts["armed"] = True
    executor.unfreeze()
    executor.notify()

    started = time.monotonic()
    deadline = started + 90
    terminal = ("succeeded", "failed", "outcome_unknown", "cancelled", "paused")
    status = None
    while time.monotonic() < deadline:
        if not executor.active_snapshot()["attempt_in_flight"]:
            if not task_id:
                break
            session = runtime.session()
            try:
                status = session.execute(
                    text("SELECT status FROM local_ai_tasks WHERE id = :id"),
                    {"id": task_id},
                ).scalar()
            finally:
                session.close()
            if status in terminal:
                break
        time.sleep(0.05)
    confirmed = bool(executor.dispose())
    elapsed = round(time.monotonic() - started, 2)
    _out(
        args.out,
        {
            "dispose_confirmed": confirmed,
            "task_status": status,
            "events": facts["events"],
            "worker_pid": facts["worker_pid"],
            "elapsed": elapsed,
        },
    )
    _write_state(args.out, dispose_confirmed=confirmed, events=facts["events"])
    runtime.dispose()
    # A normal run is only successful on a real succeeded result with a
    # confirmed child exit; a timeout or failure is a non-zero exit.
    if kill_at:
        return 0
    return 0 if (status == "succeeded" and confirmed) else 4


def phase_recover(args) -> int:
    from app.local import ai_task_service
    from app.local.runtime import LocalRuntime

    os.environ["KGM_LOCAL_DATA_DIR"] = str(Path(args.data).resolve())
    runtime = LocalRuntime(args.data, credential_root=args.cred)
    try:
        runtime.prepare()
        session = runtime.session()
        try:
            ai_task_service.recover_on_start(session, now=__import__("app.local.base", fromlist=["utc_now"]).utc_now())
            session.commit()
            from sqlalchemy import text

            task_id = _task_id(args)
            task = session.execute(
                text(
                    "SELECT status, reason, runtime_meta_json, generation, "
                    "current_execution_id FROM local_ai_tasks WHERE id = :id"
                ),
                {"id": task_id},
            ).fetchone()
            candidates = session.execute(
                text("SELECT count(*) FROM local_ai_candidates WHERE task_id = :id"),
                {"id": task_id},
            ).scalar()
            attempts = session.execute(
                text("SELECT count(*) FROM local_ai_attempts"),
            ).scalar()
            executions = session.execute(
                text("SELECT count(*) FROM local_ai_executions"),
            ).scalar()
            dispatched = session.execute(
                text("SELECT count(*) FROM local_ai_attempts WHERE dispatch_marked_at IS NOT NULL"),
            ).scalar()
            open_attempts = session.execute(
                text("SELECT count(*) FROM local_ai_attempts WHERE ended_at IS NULL"),
            ).scalar()
            _out(
                args.out,
                {
                    "task_status": task[0] if task else None,
                    "task_reason": task[1] if task else None,
                    "runtime_meta": json.loads(task[2]) if task and task[2] else None,
                    "generation": task[3] if task else None,
                    "execution_id": task[4] if task else None,
                    "candidates": int(candidates or 0),
                    "attempts": int(attempts or 0),
                    "executions": int(executions or 0),
                    "dispatched_attempts": int(dispatched or 0),
                    "open_attempts": int(open_attempts or 0),
                    "integrity": session.execute(text("PRAGMA integrity_check")).scalar(),
                    "foreign_keys": len(session.execute(text("PRAGMA foreign_key_check")).fetchall()),
                    # A frozen console exe launched without a console (or a
                    # windowed child) reports no usable streams.
                    "stdout_none": sys.stdout is None,
                    "stderr_none": sys.stderr is None,
                    "frozen": bool(getattr(sys, "frozen", False)),
                },
            )
        finally:
            session.close()
        return 0
    finally:
        runtime.dispose()


def main() -> int:
    _bootstrap_backend()
    parser = argparse.ArgumentParser(description="D2 W3 frozen spawn probe")
    parser.add_argument("--phase", required=True, choices=["setup", "run", "recover"])
    parser.add_argument("--data", required=True)
    parser.add_argument("--cred", required=True)
    parser.add_argument("--ca")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--kill-at", default="")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    try:
        if args.phase == "setup":
            return phase_setup(args)
        if args.phase == "run":
            return phase_run(args)
        return phase_recover(args)
    except BaseException as exc:  # noqa: BLE001 - never an interactive dialog
        # A windowed (noconsole) build has no stdout/stderr: record a fixed,
        # material-free failure into --out and exit non-zero. No secret or
        # lesson material is written.
        import traceback

        try:
            _out(
                args.out,
                {
                    "probe_failure": type(exc).__name__,
                    "probe_failure_code": "PROBE_PHASE_FAILED",
                    "phase": args.phase,
                    "traceback_tail": traceback.format_exc().splitlines()[-1][:300],
                },
            )
        except Exception:  # noqa: BLE001
            pass
        return 5


if __name__ == "__main__":
    sys.exit(main())
