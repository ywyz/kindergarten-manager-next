"""D2 W5 real Windows source WebView2 window verifier (re-runnable driver).

Launches the *source* ``d1_main.py --selftest --phase w5-ui`` window against a
synthetic data root, an isolated ``credential_root``/``LOCALAPPDATA`` and
``APP_DISABLE_DOTENV=1``, with a controlled local TLS provider that answers the
D2 task types through the real ``AiExecutor`` + Windows spawn/Job (never any
external network). The provider keeps the *adapt* request open so a live task
exists for the close-choice flow.

Usage:
    python verify_d2_w5_window.py [--frontend DIR] [--out FILE] [--keep]

The window phase (``d1_main.drive_w5_ui``) covers the three explicit triggers,
body-save-before-register, candidate edit/adopt against the real saved version,
candidate/settings draft leave protection and the close task choice
(keep_waiting / stop_and_exit + a real abort of an old request). A run with no
WebView2 / display is reported as a recorded failure, never as a pass.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
BACKEND = REPO_ROOT / "backend"
FRONTEND_DEFAULT = REPO_ROOT / "build" / "desktop-d1" / "frontend"
PYTHON_DEFAULT = HERE / ".venv-d1" / "Scripts" / "python.exe"

sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(HERE))

from tests.local import w3_tls  # noqa: E402
from verify_d2_w6_common import adapt_hold_segments, sse_segments  # noqa: E402

SPLIT_OUT = json.dumps(
    {
        "group_activity": {
            "theme": "合成主题",
            "objectives": "合成目标",
            "preparation": "合成准备",
            "key_points": "合成重点",
            "difficult_points": "合成难点",
            "process": "一、导入\n二、观察\n三、比较",
        }
    },
    ensure_ascii=False,
)
OTHER_OUT = json.dumps(
    {
        "morning_talk": {"topic": "合成晨谈话题", "questions": "合成问题设计"},
        "afternoon_outdoor": {"games": [{"name": "合成户外游戏"}]},
    },
    ensure_ascii=False,
)


def make_segment_factory(seen: dict):
    """Answer split with delayed SSE, other with JSON and keep adapt open."""

    def factory(request: bytes):
        text = request.decode("utf-8", "replace")
        if "process_source" in text:
            seen["adapt"] = seen.get("adapt", 0) + 1
            # Keep the connection open after real reasoning so the window can
            # prove the request was received, then abort it in the close flow.
            return adapt_hold_segments()
        if "calendar_context" in text or "morning_games" in text:
            seen["other"] = seen.get("other", 0) + 1
            return [(w3_tls.envelope(OTHER_OUT, usage={"prompt_tokens": 3}), 0.0)]
        seen["split"] = seen.get("split", 0) + 1
        # The source window must show real reasoning before the final answer,
        # exactly like the frozen-package verifier. Reuse the same delayed SSE
        # helper so the W5 DOM assertions are meaningful in both entries.
        return sse_segments(SPLIT_OUT, delay=2.5)

    return factory


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the D2 W5 source window")
    parser.add_argument("--frontend", default=str(FRONTEND_DEFAULT))
    parser.add_argument("--python", default=str(PYTHON_DEFAULT))
    parser.add_argument("--out", default=None)
    parser.add_argument("--date", default="2026-09-15")
    parser.add_argument("--clean", action="store_true", help="全部通过时删除合成根")
    args = parser.parse_args()

    token = f"{random.randrange(16**8):08x}"
    root = Path(tempfile.gettempdir()) / f"kgm-d2-w5-window-{token}"
    root.mkdir(parents=True, exist_ok=True)
    report: dict = {"ok": False, "checks": {}, "root": str(root)}
    server = None
    seen: dict = {}
    try:
        frontend = Path(args.frontend).resolve()
        if not (frontend / "d1.html").is_file():
            report["script_failure"] = f"前端构建缺失: {frontend}（先 npm run build:d1）"
            return 2
        python = Path(args.python)
        if not python.is_file():
            report["script_failure"] = f"解释器缺失: {python}"
            return 2

        # 1. Controlled TLS provider (real cert/hostname validation).
        ca_dir = root / "tls-ca"
        _cert, _key, _pem = w3_tls.create_ca(ca_dir)
        leaf = w3_tls.create_leaf(ca_dir, root / "tls-leaf")
        server = w3_tls.TlsServer(
            cert=leaf[0], key=leaf[1], segment_factory=make_segment_factory(seen)
        ).start()
        report["provider_port"] = server.port

        data_dir = root / "data"
        cred_dir = root / "credentials"
        localappdata = root / "localappdata"
        out = Path(args.out) if args.out else root / "summary.json"
        startup_log = root / "startup.log"

        env = dict(os.environ)
        env["LOCALAPPDATA"] = str(localappdata)
        env["APP_DISABLE_DOTENV"] = "1"
        env["KGM_D1_STARTUP_LOG"] = str(startup_log)
        env.pop("KGM_D1_VERIFY_SAVE_DIR", None)
        env.pop("KGM_LOCAL_DATA_DIR", None)

        command = [
            str(python),
            str(HERE / "d1_main.py"),
            "--selftest",
            "--phase",
            "w5-ui",
            "--data",
            str(data_dir),
            "--frontend",
            str(frontend),
            "--out",
            str(out),
            "--date",
            args.date,
            "--synthetic-provider-port",
            str(server.port),
            "--synthetic-provider-ca",
            str(ca_dir / "ca.pem"),
        ]
        report["command"] = command
        run_log = root / "window-run.log"
        with run_log.open("wb") as log:
            process = subprocess.run(
                command,
                cwd=str(HERE),
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=480,
            )
        report["exit_code"] = process.returncode

        summary = {}
        if out.is_file():
            summary = json.loads(out.read_text(encoding="utf-8"))
        report["window_summary"] = summary
        report["provider_requests"] = seen
        checks = summary.get("checks", {}) if isinstance(summary, dict) else {}
        w5_checks = {
            key: value for key, value in checks.items() if key.startswith("w5_")
        }
        provider_checks = {
            "provider_split_received": seen.get("split", 0) >= 1,
            "provider_other_received": seen.get("other", 0) >= 1,
            "provider_adapt_received": seen.get("adapt", 0) >= 1,
            # Progress polling, collapse/expand and repeated queries must not
            # create a second supplier request for any capability.
            "provider_split_once": seen.get("split", 0) == 1,
            "provider_other_once": seen.get("other", 0) == 1,
            "provider_adapt_once": seen.get("adapt", 0) == 1,
        }
        # Cross-assert the provider observation with the persisted outcome: a
        # request the controlled TLS actually received must finalize as
        # ``outcome_unknown``; ``paused`` is only valid when nothing was sent.
        final_status = summary.get("w5_adapt_final_status") if isinstance(summary, dict) else None
        adapt_received = seen.get("adapt", 0) >= 1
        provider_checks["w5_adapt_final_matches_provider"] = (
            final_status == "outcome_unknown" if adapt_received else final_status == "paused"
        )
        expected = {
            "w5_initialized",
            "w5_ai_configured",
            "w5_close_save_conflict_stays",
            "w5_trigger_split_saved",
            "w5_stream_progress_visible",
            "w5_stream_progress_default_expanded",
            "w5_stream_progress_collapsed",
            "w5_stream_progress_re_expanded",
            "w5_stream_progress_phase",
            "w5_split_edit_adopt",
            "w5_candidate_draft_blocks_leave",
            "w5_trigger_other_activities",
            "w5_settings_draft_blocks_leave",
            "w5_live_task",
            "w5_live_task_received",
            "w5_close_keep_waiting",
            "w5_close_old_request_aborted",
            "w5_close_stop_and_exit_choice",
            "w5_close_stop_and_exit",
            "w5_window_closed",
            "w5_host_close_state",
            "w5_adapt_final_unknown_or_paused",
            "w5_no_open_attempt",
            "ai_worker_confirmed_exit",
            "provider_split_received",
            "provider_other_received",
            "provider_adapt_received",
            "provider_split_once",
            "provider_other_once",
            "provider_adapt_once",
            "w5_adapt_final_matches_provider",
        }
        all_checks = {**checks, **provider_checks}
        missing = sorted(expected - set(all_checks))
        report["missing_checks"] = missing
        report["checks"] = all_checks
        report["ok"] = (
            not missing
            and all(all_checks.values())
            and process.returncode == 0
        )
        report["startup_log_tail"] = _tail(startup_log, 40)
    except subprocess.TimeoutExpired:
        report["script_failure"] = "window run timed out"
    except Exception as exc:  # noqa: BLE001 - a script fault is still evidence
        import traceback

        report["script_failure"] = traceback.format_exc()
        report["script_failure_type"] = type(exc).__name__
    finally:
        if server is not None:
            server.stop()
        out_path = Path(args.out) if args.out else root / "verify-report.json"
        out_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        failed = [k for k, v in report.get("checks", {}).items() if not v]
        if report.get("ok") and args.clean:
            import shutil

            shutil.rmtree(root, ignore_errors=True)
        print(
            json.dumps(
                {"ok": report.get("ok"), "failed": failed, "root": str(root)},
                ensure_ascii=False,
            )
        )
    return 0 if report.get("ok") else 3


def _tail(path: Path, lines: int) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
    except OSError:
        return []


if __name__ == "__main__":
    sys.exit(main())
