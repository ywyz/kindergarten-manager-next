"""D2 W6 real Windows **source** window verifier (re-runnable driver).

Drives the *source* ``d1_main.py`` through the W6 selftest phases against
isolated synthetic roots, an isolated ``credential_root``/``LOCALAPPDATA`` and
``APP_DISABLE_DOTENV=1``, with a controlled local TLS provider (real
cert/hostname validation, real ``AiExecutor`` + Windows spawn/Job — never an
external network).

Phases: ``w6-ui`` + ``w6-ui-verify`` (G14 closed loop and restart) and four
``g15-noexec`` degradation branches (no config / executor start failure /
network unavailable / credential unavailable), each with a real manual save and
native export.

Usage:
    python verify_d2_w6_window.py [--frontend DIR] [--python EXE] [--out FILE]

A run without WebView2 is reported as a recorded failure, never a pass.
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import socket
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
BACKEND = REPO_ROOT / "backend"
FRONTEND_DEFAULT = REPO_ROOT / "build" / "desktop-d2" / "frontend"
PYTHON_DEFAULT = HERE / ".venv-d1" / "Scripts" / "python.exe"

sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(HERE))

from tests.local import w3_tls  # noqa: E402
from verify_d2_w6_common import (  # noqa: E402
    base_env,
    closed_port,
    corrupt_credentials,
    expected_g14,
    expected_g15,
    make_reply_factory,
    run_g14,
    run_g15_branch,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the D2 W6 source window")
    parser.add_argument("--frontend", default=str(FRONTEND_DEFAULT))
    parser.add_argument("--python", default=str(PYTHON_DEFAULT))
    parser.add_argument("--out", default=None)
    parser.add_argument("--date", default="2026-09-15")
    parser.add_argument("--date2", default="2026-09-16")
    parser.add_argument("--clean", action="store_true", help="全部通过时删除合成根")
    args = parser.parse_args()

    token = f"{random.randrange(16**8):08x}"
    root = Path(tempfile.gettempdir()) / f"kgm-d2-w6-window-{token}"
    root.mkdir(parents=True, exist_ok=True)
    report: dict = {"ok": False, "checks": {}, "root": str(root), "steps": {}}
    checks: dict = report["checks"]
    seen: dict = {}
    server = None
    try:
        frontend = Path(args.frontend).resolve()
        if not (frontend / "d1.html").is_file():
            report["script_failure"] = f"前端构建缺失: {frontend}（先运行 build_d2）"
            return 2
        python = Path(args.python)
        if not python.is_file():
            report["script_failure"] = f"解释器缺失: {python}"
            return 2
        program = [str(python), str(HERE / "d1_main.py")]
        dates = {"date": args.date, "date2": args.date2}

        ca_dir = root / "tls-ca"
        w3_tls.create_ca(ca_dir)
        leaf = w3_tls.create_leaf(ca_dir, root / "tls-leaf")
        server = w3_tls.TlsServer(
            cert=leaf[0], key=leaf[1], reply_factory=make_reply_factory(seen)
        ).start()
        report["provider_port"] = server.port

        # G14 closed loop + restart.
        run_g14(
            program, frontend, root, dates, server.port, ca_dir / "ca.pem",
            checks, report, seen,
        )

        # G15 branch 1: no AI configuration.
        run_g15_branch(
            program, frontend, root, dates, "no-config", expect="none",
            configure=False, checks=checks, report=report, prefix="g15_a_",
        )
        # G15 branch 2: executor start failure (verification-only injection).
        run_g15_branch(
            program, frontend, root, dates, "executor", expect="executor",
            configure=False, checks=checks, report=report, prefix="g15_b_",
            extra=["--synthetic-executor-fail", "start"],
        )
        # G15 branch 3: network unavailable (real closed port, config in-launch).
        run_g15_branch(
            program, frontend, root, dates, "network", expect="network",
            configure=True, checks=checks, report=report, prefix="g15_c_",
            provider_port=closed_port(),
        )
        # G15 branch 4: credential unavailable — configure on one launch (pure
        # configuration, no AI request), corrupt that SAME branch's DPAPI
        # material, then re-launch reading the same store.
        run_g15_branch(
            program, frontend, root, dates, "credential-setup", expect="none",
            configure=True, checks=checks, report=report, prefix="g15_d_setup_",
            env_label="credential", extra=["--g15-no-ai-trigger"],
        )
        corrupted = corrupt_credentials(root, "credential")
        report["credential_blobs_corrupted"] = corrupted
        checks["g15_d_corrupted_material"] = corrupted >= 1
        run_g15_branch(
            program, frontend, root, dates, "credential", expect="config_error",
            configure=False, checks=checks, report=report, prefix="g15_d_",
            env_label="credential",
        )

        expected: set[str] = set()
        expected |= expected_g14("ui_")
        expected |= expected_g15("g15_a_", "none")
        expected |= expected_g15("g15_b_", "executor")
        expected |= expected_g15("g15_c_", "network")
        expected |= expected_g15("g15_d_setup_", "none")
        expected |= expected_g15("g15_d_", "config_error")
        expected |= {"g15_d_corrupted_material"}
        report["expected_checks"] = sorted(expected)
        report["missing_checks"] = sorted(k for k in expected if k not in checks)
        report["failed_checks"] = sorted(k for k in expected if checks.get(k) is not True)
        report["extra_checks"] = sorted(set(checks) - expected)
        report["ok"] = (
            not report["missing_checks"]
            and not report["failed_checks"]
            and all(checks[k] is True for k in expected)
        )
    except Exception as exc:  # noqa: BLE001 - a script fault is recorded, not a pass
        import traceback

        report["script_failure"] = traceback.format_exc()
        report["script_failure_type"] = type(exc).__name__
    finally:
        if server is not None:
            server.stop()
        out_path = Path(args.out) if args.out else root / "verify-report.json"
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        if report.get("ok") and args.clean:
            shutil.rmtree(root, ignore_errors=True)
        print(
            json.dumps(
                {"ok": report.get("ok"), "failed": report.get("failed"), "root": str(root)},
                ensure_ascii=False,
            )
        )
    return 0 if report.get("ok") else 3


if __name__ == "__main__":
    sys.exit(main())
