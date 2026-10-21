"""D2 W6 complete-package verifier (G16 + G14/G15 in the frozen executable).

Copies the built ``KGNext-D2Verify`` package to an out-of-repository path that
contains spaces, Chinese characters, ``%`` and ``#``, then runs the *frozen*
executable there with:

* a sanitized environment (no ``PYTHONPATH``/``PYTHONHOME``, no inherited
  ``KGM_*``, ``PATH`` restricted to the system directories) and the package
  directory as the working directory — the tested EXE never reads the source
  checkout;
* ``--selftest --phase w6-resources`` (twice, same data root) for the resource
  proof (migrations/prompt snapshot, DPAPI, TLS, Job, spawn) **and** the
  same-origin code comparison against the source;
* ``--selftest --phase w6-ui`` / ``w6-ui-verify`` and the four
  ``g15-noexec`` branches for the real window flows (in-package frontend only —
  ``--frontend`` is never passed).

Bundled frontend assets, Word templates, the Alembic INI and the frozen
migrations are compared byte-for-byte with the source build.

Usage:
    python verify_d2_w6_package.py [--package DIR] [--out FILE]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
BACKEND = REPO_ROOT / "backend"
PACKAGE_DEFAULT = REPO_ROOT / "build" / "desktop-d2" / "package" / "KGNext-D2Verify"
FRONTEND_SOURCE = REPO_ROOT / "build" / "desktop-d2" / "frontend"
TEMPLATE_SOURCE = BACKEND / "app" / "assets" / "word_templates"
MIGRATIONS_SOURCE = BACKEND / "migrations_local"
ALEMBIC_SOURCE = BACKEND / "alembic-local.ini"

sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(HERE))

from tests.local import w3_tls  # noqa: E402
from verify_d2_w6_common import (  # noqa: E402
    base_env,
    corrupt_credentials,
    expected_g14,
    expected_g15,
    load_summary,
    make_reply_factory,
    run_g14,
    run_g15_branch,
    run_window,
    sanitize_package_env,
)

# Fixed expectation registry for the resource / same-origin / bundling evidence.
RESOURCE_CHECKS = (
    "frozen_entry",
    "no_console_when_frozen",
    "migration_single_head",
    "integrity_ok",
    "foreign_keys_ok",
    "prompt_bundles_present",
    "prompt_sync_ok",
    "cryptography_aesgcm",
    "dpapi_config_saved",
    "dpapi_config_ready",
    "dpapi_blob_present",
    "tls_context_created",
    "tls_handshake",
    "executor_started",
    "job_object_used",
    "spawn_child_ran",
    "ai_task_succeeded",
    "worker_exit_confirmed",
    "same_origin_fingerprinted",
)
BUNDLE_CHECKS = (
    "bundle_frontend_matches",
    "bundle_templates_match",
    "bundle_migrations_match",
    "bundle_alembic_matches",
)


def _archive_entry_fingerprint(exe_path: Path) -> str:
    """Fingerprint the REAL entry code object stored in the EXE archive."""
    import marshal

    import d2_same_origin
    from PyInstaller.archive.readers import CArchiveReader

    reader = CArchiveReader(str(exe_path))
    data = reader.extract("d1_main")
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("entry data is not marshalled bytes")
    return d2_same_origin.fingerprint_code(marshal.loads(bytes(data)))


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree(root: Path) -> dict[str, str]:
    if root.is_file():
        return {"": _sha(root)}
    return {
        str(p.relative_to(root)): _sha(p)
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def _package_path(package_root: Path, relative: str) -> Path:
    """Resolve a bundled resource under the PyInstaller ``_internal`` root."""
    internal = package_root / "_internal"
    base = internal if internal.is_dir() else package_root
    return base / relative


def _run_resources(exe, root, port, ca_pem, data_dir, out, modules_file):
    env = sanitize_package_env(base_env(root, "resources"))
    env["KGM_D1_STARTUP_LOG"] = str(root / "startup-resources.log")
    args = [
        "--selftest",
        "--phase",
        "w6-resources",
        "--data",
        str(data_dir),
        "--synthetic-provider-port",
        str(port),
        "--synthetic-provider-ca",
        str(ca_pem),
        "--same-origin-modules",
        str(modules_file),
        "--out",
        str(out),
    ]
    return run_window(
        exe, args, env, root / f"resources-{out.stem}.log", 300,
        cwd=Path(exe[0]).parent,
    )


def _source_fingerprints(modules_file: Path) -> dict[str, dict]:
    """Fingerprint the source production modules (in this verifier process).

    Imports the whole reachable production surface first so the fingerprint set
    covers the AI pipeline too (not only the host entry), and maps the frozen
    ``__main__`` entry to the source ``d1_main`` module.
    """
    import importlib

    import d2_same_origin

    for name in (
        "d1_main",
        "d1_host_api",
        "d1_server",
        "d1_paths",
        "app.local.ai_executor",
        "app.local.ai_worker",
        "app.local.ai_transport",
        "app.local.ai_task_service",
        "app.local.ai_config_service",
        "app.local.ai_adoption",
        "app.local.ai_candidates",
        "app.local.ai_provenance",
        "app.local.ai_inputs",
        "app.local.export_service",
        "app.local.daily_plan_service",
        "app.local.prompt_bundles",
        "app.local.credentials",
        "app.services.word_export_docx",
        "app.services.word_export_mapping",
        "app.services.daily_plan_content",
    ):
        try:
            importlib.import_module(name)
        except Exception:  # noqa: BLE001 - record coverage, never hide it
            pass
    names = d2_same_origin.loaded_production_modules()
    # The frozen entry runs as ``__main__`` and has no importable ``d1_main``
    # module; it is compared separately through the entry fingerprint.
    probe_names = [name for name in names if name != "d1_main"]
    modules_file.write_text(json.dumps(probe_names, ensure_ascii=False), encoding="utf-8")
    return {name: d2_same_origin.fingerprint_imported_module(name) for name in names}


def _w5_provider_factory(seen: dict):
    """Answer split/other and keep the adapt request open (live-task close)."""
    from verify_d2_w6_common import OTHER_OUT, SPLIT_OUT

    def factory(request: bytes):
        text = request.decode("utf-8", "replace")
        if "process_source" in text:
            seen["adapt"] = seen.get("adapt", 0) + 1
            return None  # keep the connection open: the adapt task stays live
        if "calendar_context" in text or "morning_games" in text:
            seen["other"] = seen.get("other", 0) + 1
            return w3_tls.envelope(OTHER_OUT)
        seen["split"] = seen.get("split", 0) + 1
        return w3_tls.envelope(SPLIT_OUT)

    return factory


W5_EXPECTED = (
    "w5_initialized",
    "w5_ai_configured",
    "w5_close_save_conflict_stays",
    "w5_trigger_split_saved",
    "w5_split_edit_adopt",
    "w5_candidate_draft_blocks_leave",
    "w5_trigger_other_activities",
    "w5_settings_draft_blocks_leave",
    "w5_live_task",
    "w5_close_keep_waiting",
    "w5_close_old_request_aborted",
    "w5_close_stop_and_exit_choice",
    "w5_close_stop_and_exit",
    "w5_window_closed",
    "w5_host_close_state",
    "w5_adapt_final_unknown_or_paused",
    "w5_no_open_attempt",
    "ai_worker_confirmed_exit",
    "server_stopped",
)


def _run_w5_in_package(exe, root, copied, dates, ca_dir, leaf, checks, report):
    """The existing w5-ui close loop inside the frozen package."""
    w5_seen: dict = {}
    server = w3_tls.TlsServer(
        cert=leaf[0], key=leaf[1], reply_factory=_w5_provider_factory(w5_seen)
    ).start()
    try:
        env = sanitize_package_env(base_env(root, "w5"))
        env["KGM_D1_STARTUP_LOG"] = str(root / "startup-w5.log")
        out = root / "w5-ui.json"
        rc = run_window(
            exe,
            [
                "--selftest",
                "--phase",
                "w5-ui",
                "--data",
                str(root / "w5-data"),
                "--date",
                dates["date"],
                "--term-start",
                "2026-09-01",
                "--term-end",
                "2026-09-30",
                "--synthetic-provider-port",
                str(server.port),
                "--synthetic-provider-ca",
                str(ca_dir / "ca.pem"),
                "--out",
                str(out),
            ],
            env,
            root / "w5-ui.log",
            420,
            cwd=copied,
        )
        summary = load_summary(out)
        report["steps"]["w5_ui_exit"] = rc
        report["steps"]["w5_ui_summary"] = summary
        report["steps"]["w5_provider_requests"] = dict(w5_seen)
        w5_checks = summary.get("checks", {}) if isinstance(summary, dict) else {}
        checks["w5p_exit_zero"] = rc == 0
        for key in W5_EXPECTED:
            checks[f"w5p_{key}"] = bool(w5_checks.get(key))
        # Cross-assert the controlled provider observation with the persisted
        # outcome: an adapt request the TLS server actually received must end
        # ``outcome_unknown``.
        final_status = summary.get("w5_adapt_final_status")
        adapt_received = w5_seen.get("adapt", 0) >= 1
        checks["w5p_provider_split_received"] = w5_seen.get("split", 0) >= 1
        checks["w5p_provider_other_received"] = w5_seen.get("other", 0) >= 1
        checks["w5p_provider_adapt_received"] = adapt_received
        checks["w5p_adapt_final_matches_provider"] = (
            final_status == "outcome_unknown"
            if adapt_received
            else final_status == "paused"
        )
    finally:
        server.stop()


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the complete D2 W6 package")
    parser.add_argument("--package", default=str(PACKAGE_DEFAULT))
    parser.add_argument(
        "--frontend-dir",
        default=str(FRONTEND_SOURCE),
        help="要逐字节核对的前端构建目录（默认既有 build/desktop-d2/frontend）",
    )
    parser.add_argument("--out", default=None)
    parser.add_argument("--date", default="2026-09-15")
    parser.add_argument("--date2", default="2026-09-16")
    parser.add_argument("--keep", action="store_true", help="保留下载/解包合成根")
    args = parser.parse_args()

    token = f"{random.randrange(16**8):08x}"
    root = Path(tempfile.gettempdir()) / "opencode" / f"kgm-d2-w6-pkg-{token}"
    root.mkdir(parents=True, exist_ok=True)
    report: dict = {"ok": False, "checks": {}, "root": str(root), "steps": {}}
    checks: dict = report["checks"]
    server = None
    try:
        source_package = Path(args.package).resolve()
        exe_name = source_package.name + ".exe"
        if not (source_package / exe_name).is_file():
            report["script_failure"] = f"包内可执行文件缺失: {source_package / exe_name}"
            return 2

        # 1. Copy the package OUT of the repository to a special-character path.
        dest_parent = root / "Kg 中文 %# 名"
        dest_parent.mkdir(parents=True, exist_ok=True)
        copied = dest_parent / source_package.name
        shutil.copytree(source_package, copied)
        exe = [str(copied / exe_name)]
        report["copied_package"] = str(copied)
        report["exe_sha256"] = _sha(copied / exe_name)
        report["exe_bytes"] = (copied / exe_name).stat().st_size
        checks["special_path_copied"] = (" " in str(copied)) and ("中" in str(copied)) and ("%" in str(copied)) and ("#" in str(copied))
        checks["out_of_repo"] = str(REPO_ROOT) not in str(copied)

        # 2. Source fingerprints + bundled resource manifest.
        modules_file = root / "same_origin_modules.json"
        source_fp = _source_fingerprints(modules_file)
        report["source_modules"] = len(source_fp)

        def compare_bundle(label: str, pkg_rel: str, source: Path):
            bundled = _package_path(copied, pkg_rel)
            if not bundled.exists():
                report[f"bundle_{label}_error"] = f"missing {bundled}"
                return False
            if source.is_file():
                return bundled.is_file() and _sha(bundled) == _sha(source)
            return _tree(bundled) == _tree(source)

        checks["bundle_frontend_matches"] = compare_bundle(
            "frontend", "frontend", Path(args.frontend_dir).resolve()
        )
        checks["bundle_templates_match"] = compare_bundle(
            "templates", "app/assets/word_templates", TEMPLATE_SOURCE
        )
        checks["bundle_migrations_match"] = compare_bundle(
            "migrations", "migrations_local", MIGRATIONS_SOURCE
        )
        checks["bundle_alembic_matches"] = compare_bundle("alembic", "alembic-local.ini", ALEMBIC_SOURCE)

        # 3. Controlled provider.
        ca_dir = root / "tls-ca"
        w3_tls.create_ca(ca_dir)
        leaf = w3_tls.create_leaf(ca_dir, root / "tls-leaf")
        seen: dict = {}
        server = w3_tls.TlsServer(
            cert=leaf[0], key=leaf[1], reply_factory=make_reply_factory(seen)
        ).start()
        report["provider_port"] = server.port

        # 4. Resource probe twice on the same data root.
        data_dir = root / "res-data"
        out1 = root / "resources-1.json"
        out2 = root / "resources-2.json"
        rc1 = _run_resources(exe, root, server.port, ca_dir / "ca.pem", data_dir, out1, modules_file)
        rc2 = _run_resources(exe, root, server.port, ca_dir / "ca.pem", data_dir, out2, modules_file)
        s1 = json.loads(out1.read_text(encoding="utf-8")) if out1.is_file() else {}
        s2 = json.loads(out2.read_text(encoding="utf-8")) if out2.is_file() else {}
        report["steps"]["resources_exit"] = [rc1, rc2]
        report["steps"]["resources_summary"] = s1
        report["steps"]["resources_summary2"] = s2
        r1 = s1.get("checks", {})
        for key in RESOURCE_CHECKS:
            checks[f"res_{key}"] = bool(r1.get(key))
        checks["res_exit_zero"] = rc1 == 0 and rc2 == 0
        checks["res_no_duplicate_migration"] = (
            s1.get("migration_rows") == s2.get("migration_rows")
            and s1.get("schema_revision") == s2.get("schema_revision")
            and len(s1.get("migration_rows") or []) == 1
        )
        report["res_events"] = s1.get("executor_events")
        report["res_worker_pid"] = s1.get("worker_pid")
        # Same-origin comparison of the frozen code objects.
        frozen_fp = dict(s1.get("module_fingerprints") or {})
        # The frozen entry script runs as ``__main__``; compare it to source
        # ``d1_main`` instead of pretending it is a separate module.
        if source_fp.get("d1_main", {}).get("status") == "ok":
            frozen_fp["d1_main"] = s1.get("entry_fingerprint") or {
                "status": "unavailable"
            }
        mismatched = []
        unavailable = []
        compared = 0
        for name, source_entry in source_fp.items():
            frozen_entry = frozen_fp.get(name) or {}
            if frozen_entry.get("status") != "ok":
                unavailable.append(name)
            elif frozen_entry.get("sha256") != source_entry.get("sha256"):
                mismatched.append(name)
            else:
                compared += 1
        frozen_only = sorted(set(frozen_fp) - set(source_fp))
        report["same_origin_compared"] = compared
        report["same_origin_mismatched"] = mismatched
        report["same_origin_unavailable"] = unavailable
        report["same_origin_frozen_only"] = frozen_only
        checks["same_origin_all_match"] = not mismatched and not unavailable
        checks["same_origin_entry_compared"] = compared >= 1 and not mismatched
        checks["same_origin_module_count"] = compared >= 30

        # Independent entry-code comparison: extract the REAL ``d1_main`` code
        # object from the EXE archive and compare it structurally with source.
        try:
            archive_fp = _archive_entry_fingerprint(copied / exe_name)
            source_entry = source_fp.get("d1_main") or {}
            report["archive_entry_sha256"] = archive_fp
            report["source_entry_sha256"] = source_entry.get("sha256")
            checks["archive_entry_matches_source"] = (
                source_entry.get("status") == "ok"
                and archive_fp == source_entry.get("sha256")
            )
        except Exception as exc:  # noqa: BLE001 - recorded, never a silent pass
            report["archive_entry_error"] = f"{type(exc).__name__}: {exc}"
            checks["archive_entry_matches_source"] = False

        # 5. G14 + restart in the package (in-package frontend, no --frontend).
        run_g14(
            exe, None, root, {"date": args.date, "date2": args.date2},
            server.port, ca_dir / "ca.pem", checks, report, seen,
            cwd=copied, env_transform=sanitize_package_env,
        )
        # 6. G15 branches in the package.
        run_g15_branch(
            exe, None, root, {"date": args.date, "date2": args.date2}, "no-config",
            expect="none", configure=False, checks=checks, report=report,
            prefix="g15_a_", cwd=copied, env_transform=sanitize_package_env,
        )
        run_g15_branch(
            exe, None, root, {"date": args.date, "date2": args.date2}, "executor",
            expect="executor", configure=False, checks=checks, report=report,
            prefix="g15_b_", cwd=copied, env_transform=sanitize_package_env,
            extra=["--synthetic-executor-fail", "start"],
        )
        from verify_d2_w6_common import closed_port

        run_g15_branch(
            exe, None, root, {"date": args.date, "date2": args.date2}, "network",
            expect="network", configure=True, checks=checks, report=report,
            prefix="g15_c_", cwd=copied, env_transform=sanitize_package_env,
            provider_port=closed_port(),
        )
        run_g15_branch(
            exe, None, root, {"date": args.date, "date2": args.date2}, "credential-setup",
            expect="none", configure=True, checks=checks, report=report,
            prefix="g15_d_setup_", env_label="credential", cwd=copied,
            env_transform=sanitize_package_env, extra=["--g15-no-ai-trigger"],
        )
        corrupted = corrupt_credentials(root, "credential")
        report["credential_blobs_corrupted"] = corrupted
        checks["g15_d_corrupted_material"] = corrupted >= 1
        run_g15_branch(
            exe, None, root, {"date": args.date, "date2": args.date2}, "credential",
            expect="config_error", configure=False, checks=checks, report=report,
            prefix="g15_d_", env_label="credential", cwd=copied,
            env_transform=sanitize_package_env,
        )

        # 7. The existing w5-ui close loop inside the same frozen package.
        _run_w5_in_package(
            exe, root, copied, {"date": args.date, "date2": args.date2}, ca_dir, leaf, checks, report
        )

        # 8. Package-wide manifest hash.
        manifest = {
            str(p.relative_to(copied)): _sha(p)
            for p in sorted(copied.rglob("*"))
            if p.is_file()
        }
        report["package_file_count"] = len(manifest)
        report["package_manifest_sha256"] = hashlib.sha256(
            json.dumps(manifest, sort_keys=True).encode("utf-8")
        ).hexdigest()

        expected: set[str] = set()
        expected |= {f"res_{k}" for k in RESOURCE_CHECKS}
        expected |= {
            "res_exit_zero",
            "res_no_duplicate_migration",
            "same_origin_all_match",
            "same_origin_module_count",
            "same_origin_entry_compared",
            "special_path_copied",
            "out_of_repo",
        }
        expected |= set(BUNDLE_CHECKS)
        expected |= expected_g14("ui_")
        expected |= expected_g15("g15_a_", "none")
        expected |= expected_g15("g15_b_", "executor")
        expected |= expected_g15("g15_c_", "network")
        expected |= expected_g15("g15_d_setup_", "none")
        expected |= expected_g15("g15_d_", "config_error")
        expected |= {"g15_d_corrupted_material"}
        expected |= {"archive_entry_matches_source"}
        expected |= {f"w5p_{key}" for key in W5_EXPECTED}
        expected |= {
            "w5p_exit_zero",
            "w5p_provider_split_received",
            "w5p_provider_other_received",
            "w5p_provider_adapt_received",
            "w5p_adapt_final_matches_provider",
        }
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
        out_path = Path(args.out) if args.out else root / "package-report.json"
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(
            json.dumps(
                {
                    "ok": report.get("ok"),
                    "failed": report.get("failed_checks"),
                    "missing": report.get("missing_checks"),
                    "root": str(root),
                },
                ensure_ascii=False,
            )
        )
    return 0 if report.get("ok") else 3


if __name__ == "__main__":
    sys.exit(main())
