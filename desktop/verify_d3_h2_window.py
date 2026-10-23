"""D3-A H2 real Windows source WebView2 verifier.

Runs the *source* desktop entry against an independent synthetic data root:

1. ``d3-h2-ui``: real window, controlled local TLS split provider, creates a
   real split baseline, a historical manual version, a later current version
   with historical groups removed, compares and restores the historical
   version. Saves screenshots for human visual review.
2. ``d3-h2-verify``: cold restart on the same root, reads the restored content
   and history source back, and exports a real DOCX from the saved version.
3. The verifier inspects the DOCX XML: restored adopted reflection/group text
   must be present; the raw lesson-plan text is not printed by the product Word
   export and is instead verified by the cold-restart readback. The redline
   must compare the restored historical process against the retained baseline
   (not the later current text).

No external network, real credentials, package build or frozen-package run is
used. The controlled provider is local TLS only and receives a synthetic split
request through the real executor.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
FRONTEND_DEFAULT = REPO_ROOT / "build" / "desktop-d3-h2" / "frontend"
PYTHON_DEFAULT = HERE / ".venv-d1" / "Scripts" / "python.exe"
BACKEND = REPO_ROOT / "backend"

sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(HERE))

from tests.local import w3_tls  # noqa: E402
from verify_d2_w6_common import sse_segments  # noqa: E402

H2_SPLIT_OUT = json.dumps(
    {
        "group_activity": {
            "theme": "H2 合成主题",
            "objectives": "H2 合成目标",
            "preparation": "H2 合成准备",
            "key_points": "H2 合成重点",
            "difficult_points": "H2 合成难点",
            "process": "一、导入\n二、观察\n三、比较",
        }
    },
    ensure_ascii=False,
)
W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
REQUIRED_FIRST_CHECKS = {
    "h2_initialized",
    "h2_ai_configured",
    "h2_initial_saved",
    "h2_baseline_adopted",
    "h2_history_version_saved",
    "h2_current_version_saved",
    "h2_history_list_opened",
    "h2_baseline_warning_visible",
    "h2_history_compared",
    "h2_restored",
    "h2_restored_history_source",
}
REQUIRED_SECOND_CHECKS = {
    "h2_cold_restart_content",
    "h2_cold_restart_history",
    "h2_word_export",
}


class VerificationAbort(RuntimeError):
    """A verification prerequisite failed; dependent phases must not run."""


def require_first_phase(
    first: dict,
    exit_code: int,
    *,
    provider_split_count: int | None = None,
    required_screenshots: set[str] | None = None,
) -> int:
    """Validate phase 1 completely before allowing phase 2 or Word export."""
    if not isinstance(first, dict):
        raise VerificationAbort("first phase summary missing")
    first_error = first.get("h2_first_error")
    if first_error:
        step = first_error.get("step", "unknown")
        error = first_error.get("error", "")
        raise VerificationAbort(f"first phase step {step}: {error}")
    if exit_code != 0:
        raise VerificationAbort(f"first phase exit {exit_code}")
    if provider_split_count is None:
        provider_split_count = first.get("provider_split_count")
    if provider_split_count is None:
        raise VerificationAbort("first phase provider split count missing")
    if provider_split_count != 1:
        raise VerificationAbort(
            f"first phase provider split count {provider_split_count} != 1"
        )
    checks = first.get("checks", {})
    missing = sorted(
        key for key in REQUIRED_FIRST_CHECKS if checks.get(key) is not True
    )
    if missing:
        raise VerificationAbort(f"first phase missing checks: {missing}")
    version = first.get("h2_restored_version")
    if not isinstance(version, int):
        raise VerificationAbort("first phase did not return h2_restored_version")
    if required_screenshots:
        shot_names = {Path(item).name for item in first.get("screenshots", [])}
        missing_shots = sorted(required_screenshots - shot_names)
        if missing_shots:
            raise VerificationAbort(f"first phase missing screenshots: {missing_shots}")
    return version


def require_second_phase(second: dict, exit_code: int) -> None:
    if not isinstance(second, dict):
        raise VerificationAbort("second phase summary missing")
    if exit_code != 0:
        raise VerificationAbort(f"second phase exit {exit_code}")
    checks = second.get("checks", {})
    missing = sorted(
        key for key in REQUIRED_SECOND_CHECKS if checks.get(key) is not True
    )
    if missing:
        raise VerificationAbort(f"second phase missing checks: {missing}")


def run_chain(
    first_runner,
    second_runner,
    docx_inspector,
    *,
    provider_split_count: int | None = None,
    required_screenshots: set[str] | None = None,
):
    """Run the dependent chain, stopping on the first failed prerequisite.

    This is the same entry used by ``main``; tests inject runners/spies to
    prove a phase-1 failure (including a version being present), a provider
    count other than one, or a phase-2 failure never invokes the next stage.
    """
    first_exit, first = first_runner()
    restored_version = require_first_phase(
        first,
        first_exit,
        provider_split_count=provider_split_count,
        required_screenshots=required_screenshots,
    )
    second_exit, second = second_runner(restored_version)
    require_second_phase(second, second_exit)
    return docx_inspector()


def _segment_factory(seen: dict):
    def factory(request: bytes):
        text = request.decode("utf-8", "replace")
        seen["requests"] = seen.get("requests", 0) + 1
        seen["split"] = seen.get("split", 0) + 1
        if "process_source" in text or "morning_games" in text:
            raise AssertionError("H2 synthetic provider only expects a split request")
        return sse_segments(H2_SPLIT_OUT, delay=0.8)

    return factory


def _run(command: list[str], env: dict, log: Path, timeout: int) -> int:
    with log.open("wb") as handle:
        process = subprocess.run(
            command,
            cwd=str(HERE),
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
    return process.returncode


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _inspect_docx(path: Path) -> dict:
    if not path.is_file():
        raise AssertionError(f"DOCX missing: {path}")
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml")
    root = ElementTree.fromstring(xml)
    all_text = "".join(node.text or "" for node in root.iter(f"{W_NS}t"))
    red_text = ""
    for run in root.iter(f"{W_NS}r"):
        color = run.find(f"{W_NS}rPr/{W_NS}color")
        if color is None or color.get(f"{W_NS}val") != "FF0000":
            continue
        red_text += "".join(node.text or "" for node in run.iter(f"{W_NS}t"))
    return {
        "bytes": path.stat().st_size,
        "all_text": all_text,
        "red_text": red_text,
        "observed_historical_raw_in_docx": "H2 历史原文" in all_text,
        "raw_export_expected": False,
        "has_historical_reflection": "H2 历史反思" in all_text,
        "has_historical_group": "历史v1" in all_text,
        "red_has_historical_process": "历史版" in red_text and "历史新增" in red_text,
        "red_excludes_current_process": "当前版" not in red_text,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the D3-A H2 source window")
    parser.add_argument("--frontend", default=str(FRONTEND_DEFAULT))
    parser.add_argument("--python", default=str(PYTHON_DEFAULT))
    parser.add_argument("--out", default=None)
    parser.add_argument("--date", default="2026-09-15")
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()

    token = f"{random.randrange(16**8):08x}"
    root = Path(tempfile.gettempdir()) / f"kgm-d3-h2-window-{token}"
    root.mkdir(parents=True, exist_ok=True)
    report: dict = {"ok": False, "root": str(root), "checks": {}, "commands": []}
    server = None
    try:
        frontend = Path(args.frontend).resolve()
        if not (frontend / "d1.html").is_file():
            report["script_failure"] = f"前端构建缺失: {frontend}（先构建独立 H2 前端目录）"
            return 2
        python = Path(args.python)
        if not python.is_file():
            report["script_failure"] = f"解释器缺失: {python}"
            return 2

        ca_dir = root / "tls-ca"
        _cert, _key, _pem = w3_tls.create_ca(ca_dir)
        leaf = w3_tls.create_leaf(ca_dir, root / "tls-leaf")
        seen: dict = {}
        server = w3_tls.TlsServer(
            cert=leaf[0], key=leaf[1], segment_factory=_segment_factory(seen)
        ).start()
        report["provider_port"] = server.port

        data_dir = root / "data"
        localappdata = root / "localappdata"
        screenshots = root / "screenshots"
        screenshots.mkdir(parents=True, exist_ok=True)
        first_out = root / "first.json"
        second_out = root / "verify.json"
        word_out = root / "word" / "h2-restored.docx"
        first_log = root / "first-window.log"
        second_log = root / "verify-window.log"
        startup_log = root / "startup.log"

        env = dict(os.environ)
        env["LOCALAPPDATA"] = str(localappdata)
        env["APP_DISABLE_DOTENV"] = "1"
        env["KGM_D1_STARTUP_LOG"] = str(startup_log)
        env.pop("KGM_D1_VERIFY_SAVE_DIR", None)
        env.pop("KGM_LOCAL_DATA_DIR", None)

        first_command = [
            str(python),
            str(HERE / "d1_main.py"),
            "--selftest",
            "--phase",
            "d3-h2-ui",
            "--data",
            str(data_dir),
            "--frontend",
            str(frontend),
            "--out",
            str(first_out),
            "--date",
            args.date,
            "--screenshot-dir",
            str(screenshots),
            "--synthetic-provider-port",
            str(server.port),
            "--synthetic-provider-ca",
            str(ca_dir / "ca.pem"),
        ]
        required_screenshots = {
            "h2-history-list.bmp",
            "h2-history-baseline-warning.bmp",
            "h2-history-compare.bmp",
            "h2-history-confirm.bmp",
            "h2-history-restored.bmp",
        }

        def first_runner():
            report["commands"].append(first_command)
            exit_code = _run(first_command, env, first_log, 480)
            first = _read_json(first_out)
            report["first"] = first
            report["first_exit"] = exit_code
            report["provider_requests"] = seen
            first_checks = first.get("checks", {}) if isinstance(first, dict) else {}
            report["checks"]["first_exit_zero"] = exit_code == 0
            report["checks"]["first_expected_checks"] = REQUIRED_FIRST_CHECKS.issubset(
                {key for key, value in first_checks.items() if value is True}
            )
            report["checks"]["first_restored_version"] = isinstance(
                first.get("h2_restored_version"), int
            )
            report["checks"]["first_provider_split_once"] = seen.get("split", 0) == 1
            first["provider_split_count"] = seen.get("split", 0)
            shot_names = {Path(item).name for item in first.get("screenshots", [])}
            report["checks"]["screenshots_present"] = required_screenshots.issubset(
                shot_names
            )
            report["screenshot_files"] = sorted(
                str(path) for path in screenshots.glob("*.bmp")
            )
            return exit_code, first

        def second_runner(restored_version: int):
            second_command = [
                str(python),
                str(HERE / "d1_main.py"),
                "--selftest",
                "--phase",
                "d3-h2-verify",
                "--data",
                str(data_dir),
                "--frontend",
                str(frontend),
                "--out",
                str(second_out),
                "--date",
                args.date,
                "--expect-version",
                str(restored_version),
                "--word-out",
                str(word_out),
                "--screenshot-dir",
                str(screenshots),
            ]
            report["commands"].append(second_command)
            exit_code = _run(second_command, env, second_log, 300)
            second = _read_json(second_out)
            report["second"] = second
            report["second_exit"] = exit_code
            second_checks = second.get("checks", {}) if isinstance(second, dict) else {}
            report["checks"]["second_exit_zero"] = exit_code == 0
            report["checks"]["second_expected_checks"] = REQUIRED_SECOND_CHECKS.issubset(
                {key for key, value in second_checks.items() if value is True}
            )
            return exit_code, second

        def docx_inspector():
            docx = _inspect_docx(word_out)
            report["docx"] = docx
            report["checks"]["docx_historical_content"] = bool(
                docx["has_historical_reflection"] and docx["has_historical_group"]
            )
            report["checks"]["docx_historical_baseline_redline"] = bool(
                docx["red_has_historical_process"]
                and docx["red_excludes_current_process"]
            )
            return docx

        try:
            run_chain(
                first_runner,
                second_runner,
                docx_inspector,
                required_screenshots=required_screenshots,
            )
        except VerificationAbort as exc:
            first_error = (report.get("first") or {}).get("h2_first_error")
            if first_error:
                report["script_failure"] = (
                    f"first phase step {first_error.get('step')}: "
                    f"{first_error.get('error')}"
                )
            else:
                report["script_failure"] = str(exc)
            return 3

        report["ok"] = all(report["checks"].values())
        report["startup_log_tail"] = (
            startup_log.read_text(encoding="utf-8", errors="replace").splitlines()[-60:]
            if startup_log.is_file()
            else []
        )
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
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        if report.get("ok") and not args.keep:
            # Keep the screenshots and report; only the large data root is removed
            # when explicitly requested by the caller (default keeps evidence).
            pass
        failed = [key for key, value in report.get("checks", {}).items() if not value]
        print(json.dumps({"ok": report.get("ok"), "failed": failed, "root": str(root)}, ensure_ascii=False))
    return 0 if report.get("ok") else 3


if __name__ == "__main__":
    raise SystemExit(main())
