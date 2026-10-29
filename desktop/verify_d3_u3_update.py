"""D3-U U3 source/WebView2 full-chain verifier (Windows only).

The verifier uses the real Vue page in a real WebView2 window for the old
version: startup discovery, download progress, one cancel, retry, package
ready, a dirty daily plan, the reviewed close handshake, and UI install
confirmation.  The real U2 helper then switches a complete synthetic program
directory, starts the real new source entry, and the new page writes a receipt
through the real Runtime/service/page_ready path.  A dedicated source context
supplies the local TLS release source and synthetic roots; no product entry
URL, path, command, key or test switch is added.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import tempfile
import shutil
import sqlite3
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from xml.etree import ElementTree

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
BACKEND = REPO_ROOT / "backend"
PYTHON_DEFAULT = HERE / ".venv-d1" / "Scripts" / "python.exe"
FRONTEND_DEFAULT = REPO_ROOT / "build" / "desktop-d1" / "frontend"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tests"))

from cryptography.hazmat.primitives import serialization  # noqa: E402
from tests.local import w3_tls  # noqa: E402
from verify_d3_h2_window import (  # noqa: E402
    REQUIRED_FIRST_CHECKS,
    _inspect_docx,
    _segment_factory,
)
import update_install  # noqa: E402
import update_process  # noqa: E402
from update_identity import AppIdentity  # noqa: E402
from app.local import ai_config_service  # noqa: E402
from app.local.runtime import LocalRuntime  # noqa: E402
import test_update_u2 as u2  # noqa: E402

HEAD_REV = "20261023_0005_local_history"
W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _run(command: list[str], env: dict, log: Path, timeout: int) -> int:
    log.parent.mkdir(parents=True, exist_ok=True)
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


def _snapshot(db: Path) -> dict:
    connection = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name LIKE 'local_%' ORDER BY name"
            )
        ]
        out = {}
        for table in tables:
            columns = [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')]
            raw_rows = list(connection.execute(f'SELECT * FROM "{table}"'))
            rows = [tuple(row) for row in raw_rows]
            dict_rows = [dict(zip(columns, row)) for row in raw_rows]
            encoded = json.dumps(rows, ensure_ascii=False, default=str, sort_keys=True)
            out[table] = {
                "count": len(rows),
                "sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
                "rows": rows,
                "columns": columns,
                "dict_rows": dict_rows,
            }
        return out
    finally:
        connection.close()


def _files_digest(root: Path) -> dict:
    out = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            out[path.relative_to(root).as_posix()] = digest
    return out


def _http_response(body: bytes, content_type: str) -> bytes:
    return (
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: " + content_type.encode("ascii") + b"\r\n"
        b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n"
        b"Connection: close\r\n\r\n" + body
    )


def _make_update_server(root: Path):
    ca_dir = root / "update-ca"
    _cert, _key, ca_pem = w3_tls.create_ca(ca_dir)
    leaf_cert, leaf_key = w3_tls.create_leaf(
        ca_dir, root / "update-leaf", hostname="updates.example.test"
    )
    pkg_dir = root / "pkg"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    archive, metadata, key, _build = u2._make_package(
        pkg_dir, target_revision=HEAD_REV
    )
    public = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    package_bytes = archive.read_bytes()

    def segments(request: bytes):
        if b"/stable/windows-x64/manifest.json" in request:
            return [(_http_response(metadata, "application/json"), 0)]
        if b"/releases/package.zip" in request:
            header = (
                b"HTTP/1.1 200 OK\r\nContent-Type: application/octet-stream\r\n"
                b"Content-Length: " + str(len(package_bytes)).encode() + b"\r\n"
                b"Connection: close\r\n\r\n"
            )
            # Deliberately drip the package so the real UI can show progress
            # and exercise cancel before the package is complete.
            chunks = [
                (package_bytes[index : index + 256], 0.25)
                for index in range(0, len(package_bytes), 256)
            ]
            if not chunks:
                chunks = [(b"", 0)]
            first, _delay = chunks[0]
            return [(header + first, 0)] + chunks[1:]
        return [
            (
                b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
                0,
            )
        ]

    server = w3_tls.TlsServer(
        cert=leaf_cert, key=leaf_key, segment_factory=segments
    ).start()
    return server, ca_pem, archive, metadata, base64.b64encode(public).decode("ascii")


def _seed_h2(root: Path, python: Path, frontend: Path, data: Path, cred: Path) -> dict:
    ca_dir = root / "h2-ca"
    w3_tls.create_ca(ca_dir)
    leaf = w3_tls.create_leaf(ca_dir, root / "h2-leaf")
    seen: dict = {}
    provider = w3_tls.TlsServer(
        cert=leaf[0], key=leaf[1], segment_factory=_segment_factory(seen)
    ).start()
    screenshots = root / "screenshots"
    screenshots.mkdir(parents=True, exist_ok=True)
    out = root / "seed.json"
    log = root / "seed.log"
    env = dict(os.environ)
    env["LOCALAPPDATA"] = str(root / "localappdata")
    env["APP_DISABLE_DOTENV"] = "1"
    env["KGM_D1_STARTUP_LOG"] = str(root / "seed-startup.log")
    env.pop("KGM_D1_VERIFY_SAVE_DIR", None)
    env.pop("KGM_LOCAL_DATA_DIR", None)
    command = [
        str(python),
        str(HERE / "d1_main.py"),
        "--selftest",
        "--phase",
        "d3-h2-ui",
        "--data",
        str(data),
        "--credential-root",
        str(cred),
        "--frontend",
        str(frontend),
        "--out",
        str(out),
        "--date",
        "2026-09-15",
        "--screenshot-dir",
        str(screenshots),
        "--synthetic-provider-port",
        str(provider.port),
        "--synthetic-provider-ca",
        str(ca_dir / "ca.pem"),
    ]
    code = _run(command, env, log, 600)
    summary = _read_json(out)
    checks = summary.get("checks", {})
    return {
        "exit": code,
        "summary": summary,
        "provider_requests": seen,
        "required_checks": REQUIRED_FIRST_CHECKS.issubset(
            {key for key, value in checks.items() if value is True}
        ),
        "screenshots": sorted(str(p) for p in screenshots.glob("*.bmp")),
        "log": str(log),
        "command": command,
        "provider": provider,
    }


def _plan_paths(root: Path) -> list[Path]:
    return sorted(
        (root / "program" / "install-state").glob("*/install-result.json")
    ) if (root / "program" / "install-state").is_dir() else []


def _all_plan_results(root: Path) -> list[tuple[Path, dict]]:
    found = []
    for path in _plan_paths(root):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(value, dict):
            found.append((path, value))
    return found


def _wait_success_result(root: Path, timeout: float) -> tuple[Path, dict]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for path, value in _all_plan_results(root):
            if value.get("status") == "success":
                return path, value
        time.sleep(0.1)
    raise AssertionError("U3 successful install result not found")


def main() -> int:
    parser = argparse.ArgumentParser(description="D3-U U3 source chain verifier")
    parser.add_argument("--python", default=str(PYTHON_DEFAULT))
    parser.add_argument("--frontend", default=str(FRONTEND_DEFAULT))
    parser.add_argument("--out", default=None)
    parser.add_argument("--date", default="2026-09-15")
    parser.add_argument(
        "--u3-close-cancel",
        action="store_true",
        help="exercise a real close/save-failure cancellation before the successful install",
    )
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()
    root = Path(tempfile.mkdtemp(prefix="kgmu-u3-chain-"))
    root.mkdir(parents=True, exist_ok=True)
    report: dict = {"ok": False, "root": str(root), "checks": {}, "commands": []}
    update_server = None
    h2_provider = None
    new_process = None
    old_process = None
    try:
        python = Path(args.python).resolve()
        frontend = Path(args.frontend).resolve()
        if not (frontend / "d1.html").is_file():
            raise AssertionError(f"frontend missing: {frontend}")
        data = root / "data"
        cred = root / "credentials"
        screenshots = root / "screenshots"
        screenshots.mkdir(parents=True, exist_ok=True)
        report["frontend"] = str(frontend)

        seed = _seed_h2(root, python, frontend, data, cred)
        h2_provider = seed.pop("provider", None)
        report["seed"] = seed
        report["checks"]["seed_exit_zero"] = seed["exit"] == 0
        report["checks"]["seed_required_checks"] = seed["required_checks"]
        report["checks"]["seed_provider_split_once"] = (
            seed["provider_requests"].get("split", 0) == 1
        )
        if not report["checks"]["seed_exit_zero"] or not seed["required_checks"]:
            raise AssertionError("H2 seed phase did not complete")

        before = _snapshot(data / "kindergarten.db")
        credential_before = _files_digest(cred)
        report["before_tables"] = {
            table: value["count"] for table, value in before.items()
        }

        update_server, ca_pem, archive, metadata, public_b64 = _make_update_server(root)
        report["package"] = {
            "path": str(archive),
            "size": archive.stat().st_size,
            "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            "metadata_sha256": hashlib.sha256(metadata).hexdigest(),
        }
        release_config = root / "release-config.json"
        release_config.write_text(
            json.dumps(
                {
                    "origin": f"https://updates.example.test:{update_server.port}",
                    "metadata_path": "/stable/windows-x64/manifest.json",
                    "channel": "stable",
                    "public_keys": {"test-key": public_b64},
                    "ca_pem_path": str(root / "update-ca" / "ca.pem"),
                    "connect_host": "127.0.0.1",
                    "server_hostname": "updates.example.test",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        program = root / "program"
        app = program / "app"
        app.mkdir(parents=True, exist_ok=True)
        (app / "old-marker.txt").write_text("old-program", encoding="utf-8")
        (app / "KindergartenManager.exe").write_bytes(b"MZ old synthetic exe")
        (root / "updates" / "staging").mkdir(parents=True, exist_ok=True)
        new_summary = root / "new-summary.json"
        new_stop = root / "new-stop"
        new_log = root / "new-window.log"
        word_out = root / "u3-new.docx"
        target_identity = app / "_internal" / "build_identity.json"
        new_command = [
            str(python),
            str(HERE / "d1_main.py"),
            "--selftest",
            "--phase",
            "u3-verify",
            "--data",
            str(data),
            "--credential-root",
            str(cred),
            "--frontend",
            str(frontend),
            "--out",
            str(new_summary),
            "--date",
            args.date,
            "--word-out",
            str(word_out),
            "--screenshot-dir",
            str(screenshots),
            "--u3-source-identity",
            str(target_identity),
            "--u3-verify-stop",
            str(new_stop),
        ]
        helper_release_config = root / "helper-release-config.json"
        helper_release_config.write_text(
            json.dumps(
                {
                    "origin": f"https://updates.example.test:{update_server.port}",
                    "metadata_path": "/stable/windows-x64/manifest.json",
                    "channel": "stable",
                    "public_keys": {"test-key": public_b64},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        config = {
            "release_source": {
                "origin": f"https://updates.example.test:{update_server.port}",
                "metadata_path": "/stable/windows-x64/manifest.json",
                "channel": "stable",
                "public_keys": {"test-key": public_b64},
                "ca_pem_path": str(root / "update-ca" / "ca.pem"),
                "connect_host": "127.0.0.1",
                "server_hostname": "updates.example.test",
            },
            "release_config": str(helper_release_config),
            "install_root": str(program),
            "app_dir": str(app),
            "staging_root": str(root / "updates" / "staging"),
            "helper_command": [
                str(python),
                str(HERE / "update_helper.py"),
                "--verification-context",
                "--allow-launcher",
            ],
            "new_app_command": new_command,
        }
        config_path = root / "u3-config.json"
        config_path.write_text(
            json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        old_summary = root / "old-summary.json"
        old_log = root / "old-window.log"
        env = dict(os.environ)
        env["LOCALAPPDATA"] = str(root / "localappdata")
        env["APP_DISABLE_DOTENV"] = "1"
        env["KGM_D1_STARTUP_LOG"] = str(root / "old-startup.log")
        env.pop("KGM_D1_VERIFY_SAVE_DIR", None)
        env.pop("KGM_LOCAL_DATA_DIR", None)
        old_command = [
            str(python),
            str(HERE / "d1_main.py"),
            "--selftest",
            "--phase",
            "u3-update",
            "--data",
            str(data),
            "--credential-root",
            str(cred),
            "--frontend",
            str(frontend),
            "--out",
            str(old_summary),
            "--date",
            args.date,
            "--screenshot-dir",
            str(screenshots),
            "--u3-config",
            str(config_path),
        ]
        if args.u3_close_cancel:
            old_command.append("--u3-close-cancel")
        report["commands"] += [seed["command"], old_command, new_command]
        report["old_command"] = old_command
        report["old_exit"] = _run(old_command, env, old_log, 600)
        old = _read_json(old_summary)
        report["old"] = old
        report["checks"]["old_exit_zero"] = report["old_exit"] == 0
        old_checks = old.get("checks", {})
        old_required = [
            "u3_startup_update_available",
            "u3_ui_download_progress",
            "u3_ui_cancel_keeps_old_app",
            "u3_ui_package_ready",
            "u3_dirty_before_install",
            "u3_ui_install_confirmed",
            "u3_close_handshake_allowed",
        ]
        if args.u3_close_cancel:
            old_required += [
                "u3_close_cancel_revoked",
                "u3_close_cancel_page_kept",
                "u3_close_cancel_old_program_intact",
            ]
        for key in old_required:
            report["checks"][key] = old_checks.get(key) is True
        if not report["checks"]["old_exit_zero"]:
            raise AssertionError(f"old U3 window failed: {report['old_exit']}")

        result_path, result = _wait_success_result(root, 90)
        report["install_result_path"] = str(result_path)
        report["install_result"] = result
        all_results = _all_plan_results(root)
        report["plan_results"] = [
            {
                "path": str(path),
                "plan_id": value.get("plan_id"),
                "nonce": value.get("nonce"),
                "status": value.get("status"),
                "code": value.get("code"),
            }
            for path, value in all_results
        ]
        final_plan_path = result_path.parent / "install-plan.json"
        final_plan = json.loads(final_plan_path.read_text(encoding="utf-8"))
        receipt_binding = result.get("receipt") or {}
        report["checks"]["final_plan_result_binding"] = bool(
            result.get("plan_id") == final_plan.get("plan_id")
            and result.get("nonce") == final_plan.get("nonce")
            and receipt_binding.get("plan_id") == final_plan.get("plan_id")
            and receipt_binding.get("nonce") == final_plan.get("nonce")
        )
        if args.u3_close_cancel:
            revoked_ids = {
                value.get("plan_id")
                for _path, value in all_results
                if value.get("status") == "revoked"
            }
            report["checks"]["canceled_plan_revoked"] = bool(revoked_ids)
            report["checks"]["success_plan_distinct"] = bool(
                result.get("plan_id") not in revoked_ids
            )
        plan_path = result_path.parent / "install-plan.json"
        if plan_path.is_file():
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            report["install_plan"] = {
                "plan_id": plan.get("plan_id"),
                "nonce": plan.get("nonce"),
                "old_process": plan.get("old_process"),
                "target": plan.get("target"),
            }
        report["checks"]["helper_success"] = result.get("status") == "success"
        if result.get("status") != "success":
            raise AssertionError(f"helper result not success: {result}")
        receipt = result.get("receipt") or {}
        report["receipt"] = receipt
        report["checks"]["helper_receipt_ready"] = (
            receipt.get("page_ready") is True
            and receipt.get("service_ready") is True
            and receipt.get("runtime_ready") is True
        )
        new_stop.write_text("stop", encoding="utf-8")
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline and not new_summary.is_file():
            time.sleep(0.1)
        new = _read_json(new_summary)
        report["new"] = new
        report["checks"]["new_summary_present"] = bool(new)
        new_checks = new.get("checks", {})
        report["checks"]["new_page_ready"] = new_checks.get("u3_new_page_ready") is True
        report["checks"]["new_word_export"] = (
            new_checks.get("u3_new_word_export") is True
        )
        identity = new.get("u3_verify_identity") or {}
        report["new_identity"] = identity
        report["checks"]["new_target_identity"] = (
            identity.get("version") == "0.2.0"
            and identity.get("build_id") == receipt.get("build_id")
            and identity.get("database_revision") == HEAD_REV
        )
        report["checks"]["new_process_matches_receipt"] = (
            isinstance(new.get("u3_verify_pid"), int)
            and new.get("u3_verify_pid") == receipt.get("pid")
        )
        report["checks"]["new_source_running"] = isinstance(
            new.get("u3_verify_pid"), int
        )
        new_pid = new.get("u3_verify_pid")
        new_creation = receipt.get("creation_time")
        if isinstance(new_pid, int) and isinstance(new_creation, int):
            update_process.wait_for_process_exit(
                update_process.ProcessIdentity(
                    pid=new_pid,
                    creation_time=new_creation,
                    executable=str(receipt.get("executable") or ""),
                ),
                20,
            )
        coordinator = update_install.InstallCoordinator(
            identity=AppIdentity(**receipt["identity"]),
            data_dir=data,
            credential_root=cred,
            install_root=program,
            app_dir=app,
            helper_command=list(config["helper_command"]),
            release_config=helper_release_config,
            test_only=True,
        )
        state_deadline = time.monotonic() + 30
        while time.monotonic() < state_deadline and not coordinator.install_available():
            time.sleep(0.1)
        report["checks"]["install_state_recovered"] = coordinator.install_available()
        credential_runtime = LocalRuntime(data, credential_root=cred)
        try:
            credential_runtime.prepare()
            session = credential_runtime.session()
            try:
                config_out = ai_config_service.get_config(
                    session, credential_root=cred
                )
                report["credential_readback"] = {
                    "configured": config_out.configured,
                    "ready": config_out.ready,
                    "has_secret": config_out.has_secret,
                    "reason": config_out.reason,
                }
                report["checks"]["synthetic_credential_readable"] = bool(
                    config_out.configured
                    and config_out.ready
                    and config_out.has_secret
                )
            finally:
                session.close()
        finally:
            credential_runtime.dispose()
        report["checks"]["new_app_complete"] = (
            (app / "KindergartenManager.exe").is_file()
            and (app / "_internal" / "build_identity.json").is_file()
        )
        report["checks"]["old_app_backup_preserved"] = any(
            (backup / "old-marker.txt").is_file()
            for backup in (program / "backups").glob("*")
        )
        report["target_app_dir"] = str(app)

        after = _snapshot(data / "kindergarten.db")
        credential_after = _files_digest(cred)
        mutable = {
            "local_daily_plan_contents",
            "local_operation_records",
            "local_daily_plans",
            "local_daily_plan_ai_provenance",
        }
        preserved = [
            table
            for table in before
            if table not in mutable and table in after
        ]
        report["checks"]["preserved_tables"] = all(
            before[table]["sha256"] == after[table]["sha256"]
            for table in preserved
        )
        report["checks"]["credentials_preserved"] = credential_before == credential_after
        ai_tables = [table for table in before if table.startswith("local_ai_")]
        report["checks"]["ai_tables_preserved"] = all(
            before[table]["sha256"] == after.get(table, {}).get("sha256")
            for table in ai_tables
        )
        report["table_deltas"] = {
            table: {
                "before": before.get(table, {}).get("count"),
                "after": after.get(table, {}).get("count"),
            }
            for table in sorted(set(before) | set(after))
            if before.get(table, {}).get("sha256")
            != after.get(table, {}).get("sha256")
        }
        # Prior content/op rows must remain present, even though the close
        # handshake legitimately adds a new saved version/operation.
        for table in (
            "local_daily_plan_contents",
            "local_operation_records",
            "local_daily_plan_ai_provenance",
        ):
            if table in before and table in after:
                before_rows = set(before[table]["rows"])
                after_rows = set(after[table]["rows"])
                report["checks"][f"{table}_preserved"] = before_rows.issubset(after_rows)
        if (
            before.get("local_daily_plans", {}).get("dict_rows")
            and after.get("local_daily_plans", {}).get("dict_rows")
        ):
            before_plan = before["local_daily_plans"]["dict_rows"][0]
            after_plan = after["local_daily_plans"]["dict_rows"][0]
            allowed = {
                "current_content_id",
                "current_content_version",
                "updated_at",
            }
            unchanged = all(
                before_plan.get(key) == after_plan.get(key)
                for key in before_plan
                if key not in allowed
            )
            report["checks"]["daily_plan_fields_preserved"] = unchanged
            report["checks"]["daily_plan_version_increment"] = (
                isinstance(after_plan.get("current_content_version"), int)
                and after_plan["current_content_version"]
                == int(before_plan.get("current_content_version") or 0) + 1
            )
        docx = _inspect_docx(word_out)
        report["docx"] = docx
        report["checks"]["word_export_present"] = word_out.is_file() and word_out.stat().st_size > 0
        report["checks"]["word_saved_content"] = (
            "U3 关闭前反思" in docx["all_text"]
        )
        report["checks"]["word_historical_source"] = (
            "历史v1" in docx["all_text"]
        )
        report["checks"]["update_server_requests"] = len(update_server.requests) >= 2
        report["update_requests"] = [r.decode("utf-8", "replace")[:120] for r in update_server.requests]
        report["provider_requests_after_chain"] = dict(seed["provider_requests"])
        report["checks"]["no_post_update_ai_provider_requests"] = (
            seed["provider_requests"].get("split", 0) == 1
            and seed["provider_requests"].get("requests", 0) == 1
        )
        report["ok"] = all(report["checks"].values())
    except subprocess.TimeoutExpired:
        report["script_failure"] = "U3 window run timed out"
    except Exception as exc:  # noqa: BLE001
        import traceback

        report["script_failure"] = traceback.format_exc()
        report["script_failure_type"] = type(exc).__name__
    finally:
        if update_server is not None:
            update_server.stop()
        if h2_provider is not None:
            h2_provider.stop()
        if old_process is not None and old_process.poll() is None:
            old_process.terminate()
        out_path = Path(args.out) if args.out else root / "u3-report.json"
        out_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "ok": report.get("ok"),
                    "failed": [
                        key for key, value in report.get("checks", {}).items() if not value
                    ],
                    "root": str(root),
                    "out": str(out_path),
                },
                ensure_ascii=False,
            )
        )
    return 0 if report.get("ok") else 3


if __name__ == "__main__":
    raise SystemExit(main())
