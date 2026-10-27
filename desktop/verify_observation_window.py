"""D4 E09/E10 real WebView2 observation window verifier (re-runnable).

Launches the source ``d1_main.py --selftest --phase obs-ui`` window against an
isolated ``--data-dir`` / ``--credential-root`` and the built D1 frontend. The
window driver uses the real workbench button, real list/create, the real
editor save path, the real authenticated file input upload, history restore,
a forced version conflict and leave-with-save. It never calls a real AI
provider.

Usage:
    python verify_observation_window.py [--frontend DIR] [--data-dir DIR]
        [--output-dir DIR] [--keep] [--timeout 420]

Exit codes: 0 checks passed, 1 a check failed, 2 startup/environment failure.
A machine without WebView2 is reported as a recorded failure, never a pass.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
PYTHON_DEFAULT = HERE / ".venv-d1" / "Scripts" / "python.exe"
FRONTEND_DEFAULT = REPO_ROOT / "build" / "desktop-d1" / "frontend"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frontend", default=str(FRONTEND_DEFAULT))
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--timeout", type=float, default=420.0)
    args = parser.parse_args()

    frontend = Path(args.frontend).resolve()
    root_env = os.environ.get("KGM_OBSERVATION_EVIDENCE_ROOT")
    if args.output_dir:
        output_dir = Path(args.output_dir).resolve()
    elif root_env:
        output_dir = (
            Path(root_env).resolve()
            / f"verify-window-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        )
    else:
        output_dir = Path(tempfile.mkdtemp(prefix="kgm-obs-window-")).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    temporary = False
    if args.data_dir:
        data_dir = Path(args.data_dir).resolve()
        data_dir.mkdir(parents=True, exist_ok=True)
    else:
        data_dir = Path(tempfile.mkdtemp(prefix="kgm-obs-window-data-"))
        temporary = True
    credential_root = data_dir.parent / (data_dir.name + "-credentials")

    report: dict = {
        "ok": False,
        "generated_at": now_iso(),
        "frontend": str(frontend),
        "data_dir": str(data_dir),
        "credential_root": str(credential_root),
        "output_dir": str(output_dir),
        "python": sys.version,
        "platform": sys.platform,
        "checks": {},
        "notes": [],
    }
    summary_path = output_dir / "window-summary.json"
    stdout_path = output_dir / "window.stdout.log"
    stderr_path = output_dir / "window.stderr.log"

    if not (frontend / "d1.html").is_file():
        report["checks"]["frontend_build_present"] = False
        report["notes"].append(f"missing frontend build: {frontend / 'd1.html'}")
        _write(output_dir, report)
        return 2
    report["checks"]["frontend_build_present"] = True
    if not PYTHON_DEFAULT.is_file():
        report["checks"]["venv_python_present"] = False
        report["notes"].append(f"missing interpreter: {PYTHON_DEFAULT}")
        _write(output_dir, report)
        return 2
    report["checks"]["venv_python_present"] = True

    env = os.environ.copy()
    env["APP_DISABLE_DOTENV"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = str(REPO_ROOT / "backend") + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    command = [
        str(PYTHON_DEFAULT),
        str(HERE / "d1_main.py"),
        "--selftest",
        "--phase",
        "obs-ui",
        "--data",
        str(data_dir),
        "--credential-root",
        str(credential_root),
        "--frontend",
        str(frontend),
        "--out",
        str(summary_path),
        "--date",
        "2026-09-15",
        "--term-start",
        "2026-09-01",
        "--term-end",
        "2026-09-30",
    ]
    report["command"] = command
    with stdout_path.open("wb") as out, stderr_path.open("wb") as err:
        try:
            completed = subprocess.run(
                command,
                cwd=str(HERE),
                env=env,
                stdout=out,
                stderr=err,
                timeout=args.timeout,
            )
            returncode = completed.returncode
        except subprocess.TimeoutExpired:
            returncode = -1
            report["notes"].append("window run timed out")
    report["exit_code"] = returncode
    summary = {}
    if summary_path.is_file():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            report["notes"].append("window summary is not valid JSON")
    report["window_summary"] = summary
    checks = summary.get("checks") if isinstance(summary, dict) else None
    report["checks"]["window_exit_zero"] = returncode == 0
    report["checks"]["window_summary_ok"] = bool(
        isinstance(summary, dict) and summary.get("ok") is True
    )
    if isinstance(checks, dict):
        for name in (
            "obs_initialized",
            "obs_create_and_edit",
            "obs_history_restore",
            "obs_conflict_and_leave",
        ):
            report["checks"][name] = checks.get(name) is True
        report["checks"]["obs_ok"] = summary.get("obs_ok") is True
    else:
        for name in (
            "obs_initialized",
            "obs_create_and_edit",
            "obs_history_restore",
            "obs_conflict_and_leave",
            "obs_ok",
        ):
            report["checks"][name] = False
    if summary.get("obs_errors"):
        report["notes"].append(f"driver errors: {summary['obs_errors']}")
    if summary.get("startup_error"):
        report["notes"].append(f"startup error: {summary['startup_error']}")
    if stderr_path.is_file() and stderr_path.stat().st_size:
        tail = stderr_path.read_text(encoding="utf-8", errors="replace")[-4000:]
        if tail.strip():
            report["notes"].append(f"stderr tail: {tail}")
    report["ok"] = all(value is True for value in report["checks"].values())
    _write(output_dir, report)
    if temporary and not args.keep:
        shutil.rmtree(data_dir, ignore_errors=True)
        shutil.rmtree(credential_root, ignore_errors=True)
    return 0 if report["ok"] else 1


def _write(output_dir: Path, report: dict) -> None:
    report_path = output_dir / "report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    files = []
    for path in sorted(output_dir.glob("**/*")):
        if not path.is_file() or path.name == "manifest.json":
            continue
        files.append(
            {
                "path": str(path.relative_to(output_dir)),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "bytes": path.stat().st_size,
            }
        )
    manifest = {
        "generated_at": now_iso(),
        "report": "report.json",
        "report_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
        "evidence_files": files,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    raise SystemExit(main())
