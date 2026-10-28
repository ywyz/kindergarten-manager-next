"""Verify the E14 complete package from an out-of-repo Chinese/space path.

Covers the frozen entry/resources/migrations/Pillow bundle, the controlled
provider resource probe, a real WebView2 observation flow on an empty synthetic
DB, and an old 0005 synthetic DB upgraded/reopened by the frozen package. It
does not claim real provider credentials when none are available.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import marshal
import os
import shutil
import sqlite3
import sys
import tempfile
import uuid
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
BACKEND = REPO / "backend"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(HERE))

from tests.local import w3_tls  # noqa: E402
from tests.local.test_observation_migration import _build_0005  # noqa: E402
from verify_d2_w6_common import (  # noqa: E402
    base_env,
    load_summary,
    make_reply_factory,
    run_window,
    sanitize_package_env,
)
from verify_d2_w6_package import (  # noqa: E402
    RESOURCE_CHECKS,
    _archive_entry_fingerprint,
    _package_path,
    _run_resources,
    _sha,
    _tree,
)

PACKAGE = REPO / "build" / "desktop-e14-r03" / "package" / "KGNext-E14"
FRONTEND = REPO / "build" / "desktop-e14-r03" / "frontend"
TEMPLATES = BACKEND / "app" / "assets" / "word_templates"
MIGRATIONS = BACKEND / "migrations_local"
ALEMBIC = BACKEND / "alembic-local.ini"
DATABASE_REVISION = "20261025_0006_local_game_observations"
ARCHIVE_REQUIRED_MODULES = (
    "app.local.observation_service",
    "app.local.observation_export_service",
    "app.local.observation_export_api",
    "app.local.observation_assets",
    "app.local.observation_history_service",
    "app.local.observation_ai_service",
    "app.local.observation_ai_inputs",
    "app.local.observation_validation",
    "app.local.observation_terms",
    "app.local.ai_executor",
    "app.local.ai_worker",
    "app.local.ai_transport",
    "app.local.ai_task_service",
    "app.local.ai_config_service",
    "app.local.ai_adoption",
    "app.local.ai_candidates",
    "app.local.ai_provenance",
    "app.local.ai_inputs",
    "app.local.ai_spawn",
    "app.local.runtime",
    "app.local.migrate",
    "app.local.credentials",
    "app.local.export_service",
    "app.local.daily_plan_service",
    "app.local.prompt_bundles",
    "app.services.word_export_observation",
    "app.services.word_export_docx",
    "app.services.word_export_mapping",
    "app.services.daily_plan_content",
    "update_identity",
    "update_install",
    "update_service",
    "update_trust",
    "update_manifest",
    "d1_host_api",
    "d1_server",
    "d1_paths",
    "d2_same_origin",
)
PILLOW_LICENSE = (
    REPO
    / "desktop"
    / ".venv-d1"
    / "Lib"
    / "site-packages"
    / "pillow-13.0.0.dist-info"
    / "licenses"
    / "LICENSE"
)
EXPECTED_OBS_CHECKS = (
    "obs_initialized",
    "obs_create_and_edit",
    "obs_history_restore",
    "obs_conflict_and_leave",
    "obs_export_from_editor",
    "obs_export_cancel_from_editor",
    "obs_export_host_busy_cleared",
    "obs_export_app_busy_cleared",
    "obs_export_cancel_busy_cleared",
    "obs_multi_page_mixed_export",
    "obs_multi_export_schools",
    "obs_multi_export_busy_cleared",
    "obs_ok",
)


def _source_fingerprints(modules_file: Path) -> dict[str, dict]:
    import d2_same_origin

    for name in (
        "d1_main",
        "d1_host_api",
        "d1_server",
        "d1_paths",
        "app.local.observation_service",
        "app.local.observation_export_service",
        "app.local.observation_export_api",
        "app.local.observation_assets",
        "app.local.observation_history_service",
        "app.local.observation_ai_service",
        "app.services.word_export_observation",
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
        except Exception:  # noqa: BLE001
            pass
    names = d2_same_origin.loaded_production_modules()
    modules_file.write_text(
        json.dumps([name for name in names if name != "d1_main"], ensure_ascii=False),
        encoding="utf-8",
    )
    return {name: d2_same_origin.fingerprint_imported_module(name) for name in names}


def _run_obs(exe, root, data_dir, out, timeout=600):
    env = sanitize_package_env(base_env(root, "obs"))
    env["KGM_D1_VERIFY_SAVE_DIR"] = str(root / "saved-obs")
    Path(env["KGM_D1_VERIFY_SAVE_DIR"]).mkdir(parents=True, exist_ok=True)
    env["KGM_D1_STARTUP_LOG"] = str(root / "startup-obs.log")
    args = [
        "--selftest",
        "--phase",
        "obs-ui",
        "--data",
        str(data_dir),
        "--out",
        str(out),
        "--date",
        "2026-09-15",
        "--term-start",
        "2026-09-01",
        "--term-end",
        "2026-09-30",
    ]
    return run_window(
        exe,
        args,
        env,
        root / f"obs-{out.stem}.log",
        timeout,
        cwd=Path(exe[0]).parent,
    )


def _query(db: Path, sql: str):
    connection = sqlite3.connect(str(db))
    try:
        return connection.execute(sql).fetchall()
    finally:
        connection.close()


def _tree_clean(root: Path) -> dict[str, str]:
    """File hashes excluding Python bytecode caches (package data is clean)."""
    if root.is_file():
        return {"": _sha(root)}
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if "__pycache__" in path.parts or path.suffix.lower() in {".pyc", ".pyo"}:
            continue
        result[str(path.relative_to(root))] = _sha(path)
    return result


def _module_source_path(name: str) -> Path | None:
    if name.startswith("app."):
        base = BACKEND / "app"
        relative = Path(*name.split(".")[1:])
        candidate = base / relative.with_suffix(".py")
        if candidate.is_file():
            return candidate
        candidate = base / relative / "__init__.py"
        if candidate.is_file():
            return candidate
        return None
    candidate = HERE / f"{name}.py"
    return candidate if candidate.is_file() else None


def _archive_static_report(package_root: Path) -> dict:
    """Compare the real CArchive entry and every bundled app/host module.

    This reads the EXE archive directly; it never launches the executable, so
    it remains valid under the local Smart App Control 4551 block.
    """
    import d2_same_origin
    from PyInstaller.archive.readers import CArchiveReader

    exe = package_root / f"{package_root.name}.exe"
    reader = CArchiveReader(str(exe))
    entry_data = reader.extract("d1_main")
    if not isinstance(entry_data, (bytes, bytearray)):
        raise TypeError("CArchive d1_main is not marshalled bytes")
    entry_fingerprint = d2_same_origin.fingerprint_code(marshal.loads(bytes(entry_data)))
    source_entry = d2_same_origin.fingerprint_source(HERE / "d1_main.py")
    pyz = reader.open_embedded_archive("PYZ.pyz")
    modules: dict[str, dict] = {}
    for name in sorted(pyz.toc):
        if not (
            name.startswith("app.")
            or name.startswith(("update_", "d0_", "d1_"))
            or name == "d2_same_origin"
        ):
            continue
        source = _module_source_path(name)
        if source is None:
            modules[name] = {"status": "source_missing"}
            continue
        try:
            code = pyz.extract(name)
            frozen = d2_same_origin.fingerprint_code(code)
            source_hash = d2_same_origin.fingerprint_source(source)
            modules[name] = {
                "status": "ok" if frozen == source_hash else "mismatch",
                "sha256": frozen,
                "source_sha256": source_hash,
                "source": str(source.relative_to(REPO)),
            }
        except Exception as exc:  # noqa: BLE001 - recorded, never a silent pass
            modules[name] = {
                "status": "error",
                "reason": f"{type(exc).__name__}: {exc}",
            }
    mismatched = sorted(
        name for name, item in modules.items() if item["status"] == "mismatch"
    )
    unavailable = sorted(
        name for name, item in modules.items() if item["status"] != "ok"
    )
    missing_required = sorted(
        name for name in ARCHIVE_REQUIRED_MODULES if name not in pyz.toc
    )
    return {
        "entry": {
            "name": "d1_main",
            "frozen_sha256": entry_fingerprint,
            "source_sha256": source_entry,
            "matches": entry_fingerprint == source_entry,
        },
        "pyz_module_count": len(modules),
        "pyz_all_match": not mismatched and not unavailable,
        "mismatched": mismatched,
        "unavailable": unavailable,
        "required": list(ARCHIVE_REQUIRED_MODULES),
        "missing_required": missing_required,
        "modules": modules,
    }


def _identity_report(package_root: Path) -> dict:
    import update_identity

    path = package_root / "_internal" / "build_identity.json"
    report: dict = {"path": str(path), "present": path.is_file(), "valid": False}
    identity = None
    if path.is_file():
        identity = update_identity.load_app_identity(
            database_revision=DATABASE_REVISION,
            path=path,
            require_packaged=True,
        )
    if identity is not None:
        report["valid"] = True
        report["identity"] = identity.as_dict()
        try:
            uuid.UUID(identity.build_id)
            report["build_id_is_uuid"] = True
        except (ValueError, AttributeError):
            report["build_id_is_uuid"] = False
        report["build_id_is_real"] = (
            identity.build_id != update_identity.SOURCE_BUILD_ID
        )
        report["version_ok"] = identity.version == update_identity.APP_VERSION
        report["revision_ok"] = identity.database_revision == DATABASE_REVISION
        info_path = package_root / "package-info.json"
        if info_path.is_file():
            try:
                info = json.loads(info_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                info = {}
            report["package_info_build_id"] = info.get("build_id")
            report["package_info_matches"] = (
                info.get("build_id") == identity.build_id
                and info.get("database_revision") == identity.database_revision
            )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", default=str(PACKAGE))
    parser.add_argument("--out", default=None)
    parser.add_argument("--keep", action="store_true")
    parser.add_argument(
        "--static-only",
        action="store_true",
        help="verify package bytes/resources without launching the frozen EXE",
    )
    args = parser.parse_args()
    source_package = Path(args.package).resolve()
    root = Path(tempfile.mkdtemp(prefix="kgm-e14-package-")).resolve()
    report: dict = {"ok": False, "checks": {}, "steps": {}, "root": str(root)}
    checks: dict = report["checks"]
    try:
        exe_name = source_package.name + ".exe"
        if not (source_package / exe_name).is_file():
            raise SystemExit(f"package exe missing: {source_package / exe_name}")
        dest_parent = root / "Kg 中文 %# 名"
        copied = dest_parent / source_package.name
        shutil.copytree(source_package, copied)
        exe = [str(copied / exe_name)]
        checks["special_path_copied"] = all(
            token in str(copied) for token in (" ", "中", "%", "#")
        )
        checks["out_of_repo"] = str(REPO) not in str(copied)

        def compare(label: str, pkg_rel: str, source: Path) -> bool:
            bundled = _package_path(copied, pkg_rel)
            if not bundled.exists():
                return False
            if source.is_file():
                return bundled.is_file() and _sha(bundled) == _sha(source)
            return _tree_clean(bundled) == _tree_clean(source)

        checks["bundle_frontend_matches"] = compare("frontend", "frontend", FRONTEND)
        checks["bundle_templates_match"] = compare(
            "templates", "app/assets/word_templates", TEMPLATES
        )
        checks["bundle_migrations_match"] = compare(
            "migrations", "migrations_local", MIGRATIONS
        )
        checks["bundle_alembic_matches"] = compare(
            "alembic", "alembic-local.ini", ALEMBIC
        )
        internal = copied / "_internal"
        checks["entry_exe"] = (copied / exe_name).is_file()
        cache_dirs = [path for path in copied.rglob("__pycache__") if path.is_dir()]
        cache_files = [path for path in copied.rglob("*.pyc") if path.is_file()]
        checks["no_package_cache_files"] = not cache_dirs and not cache_files
        checks["observation_templates"] = all(
            (internal / "app/assets/word_templates" / name).is_file()
            for name in (
                "observation_public.docx",
                "observation_indoor.docx",
                "observation_outdoor.docx",
            )
        )
        checks["migration_0006"] = (
            internal / "migrations_local/versions/20261025_0006_local_game_observations.py"
        ).is_file()
        pillow_plugins = list((internal / "PIL").glob("_*.cp314-win_amd64.pyd"))
        checks["pillow_plugins_present"] = len(pillow_plugins) >= 8
        checks["pillow_license_present"] = (copied / "licenses/Pillow-LICENSE.txt").is_file()
        checks["pillow_license_matches_source"] = (
            (copied / "licenses/Pillow-LICENSE.txt").is_file()
            and PILLOW_LICENSE.is_file()
            and _sha(copied / "licenses/Pillow-LICENSE.txt") == _sha(PILLOW_LICENSE)
        )
        checks["package_info_present"] = (copied / "package-info.json").is_file()
        package_info_path = copied / "package-info.json"
        package_info = {}
        if package_info_path.is_file():
            try:
                package_info = json.loads(
                    package_info_path.read_text(encoding="utf-8")
                )
            except json.JSONDecodeError:
                package_info = {}
        package_value = package_info.get("package")
        checks["package_info_portable"] = (
            package_value == copied.name
            and not Path(str(package_value)).is_absolute()
        )

        # R02: static CArchive/PYZ structural comparison (no EXE launch).
        archive = _archive_static_report(copied)
        report["archive"] = archive
        checks["archive_entry_matches_source"] = bool(archive["entry"]["matches"])
        checks["archive_pyz_all_match"] = bool(archive["pyz_all_match"])
        checks["archive_required_modules_present"] = not archive["missing_required"]
        checks["archive_module_count"] = archive["pyz_module_count"] >= 40

        # R03: real packaged identity (UUID build id, 0.1.0, revision 0006).
        identity = _identity_report(copied)
        report["build_identity"] = identity
        checks["build_identity_present"] = bool(identity["present"])
        checks["build_identity_valid"] = bool(identity["valid"])
        checks["build_identity_uuid"] = bool(identity.get("build_id_is_uuid"))
        checks["build_identity_not_source_id"] = bool(identity.get("build_id_is_real"))
        checks["build_identity_version"] = bool(identity.get("version_ok"))
        checks["build_identity_revision"] = bool(identity.get("revision_ok"))
        checks["build_identity_matches_package_info"] = bool(
            identity.get("package_info_matches")
        )

        if args.static_only:
            report["frozen_runtime"] = "not_run_static_only"
            report["real_ai"] = (
                "source-level real DeepSeek closure recorded in r02/real-ai; "
                "frozen package real AI unverified because this machine blocks "
                "the EXE with WinError 4551"
            )
            report["ok"] = all(checks.values())
            out_path = Path(args.out) if args.out else root / "verify-report.json"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({"ok": report["ok"], "report": str(out_path)}, ensure_ascii=False))
            return 0 if report["ok"] else 1

        # Controlled-provider resource probe (synthetic, not real AI).
        modules_file = root / "same-origin-modules.json"
        source_fp = _source_fingerprints(modules_file)
        ca_dir = root / "tls-ca"
        w3_tls.create_ca(ca_dir)
        leaf = w3_tls.create_leaf(ca_dir, root / "tls-leaf")
        seen: dict = {}
        server = w3_tls.TlsServer(
            cert=leaf[0], key=leaf[1], reply_factory=make_reply_factory(seen)
        ).start()
        try:
            data_dir = root / "resources-data"
            out1 = root / "resources-1.json"
            out2 = root / "resources-2.json"
            try:
                rc1 = _run_resources(
                    exe, root, server.port, ca_dir / "ca.pem", data_dir, out1, modules_file
                )
                rc2 = _run_resources(
                    exe, root, server.port, ca_dir / "ca.pem", data_dir, out2, modules_file
                )
            except OSError as exc:
                report["frozen_runtime"] = {
                    "blocked": True,
                    "winerror": getattr(exc, "winerror", None),
                    "message": "frozen executable blocked by local application control policy",
                }
                checks["frozen_execution_blocked_4551"] = (
                    getattr(exc, "winerror", None) == 4551
                )
                report["ok"] = False
                out_path = Path(args.out) if args.out else root / "verify-report.json"
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(
                    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                print(json.dumps({"ok": False, "report": str(out_path)}, ensure_ascii=False))
                return 2
            s1 = load_summary(out1)
            s2 = load_summary(out2)
            report["steps"]["resources_exit"] = [rc1, rc2]
            report["steps"]["resources_summary"] = s1
            for key in RESOURCE_CHECKS:
                checks[f"res_{key}"] = bool(s1.get("checks", {}).get(key))
            checks["res_exit_zero"] = rc1 == 0 and rc2 == 0
            checks["res_no_duplicate_migration"] = (
                s1.get("migration_rows") == s2.get("migration_rows")
                and s1.get("schema_revision") == s2.get("schema_revision")
                and len(s1.get("migration_rows") or []) == 1
            )
            frozen_fp = dict(s1.get("module_fingerprints") or {})
            if source_fp.get("d1_main", {}).get("status") == "ok":
                frozen_fp["d1_main"] = s1.get("entry_fingerprint") or {
                    "status": "unavailable"
                }
            mismatched = [
                name
                for name, source in source_fp.items()
                if (frozen_fp.get(name) or {}).get("status") == "ok"
                and frozen_fp[name].get("sha256") != source.get("sha256")
            ]
            unavailable = [
                name
                for name, source in source_fp.items()
                if (frozen_fp.get(name) or {}).get("status") != "ok"
            ]
            report["same_origin"] = {
                "compared": len(source_fp) - len(unavailable) - len(mismatched),
                "mismatched": mismatched,
                "unavailable": unavailable,
            }
            checks["same_origin_all_match"] = not mismatched and not unavailable
            try:
                checks["archive_entry_matches_source"] = (
                    _archive_entry_fingerprint(copied / exe_name)
                    == source_fp.get("d1_main", {}).get("sha256")
                )
            except Exception as exc:  # noqa: BLE001
                report["archive_entry_error"] = f"{type(exc).__name__}: {exc}"
                checks["archive_entry_matches_source"] = False
        finally:
            server.stop()

        # Real WebView2 observation flow on a cold empty synthetic DB.
        empty_data = root / "empty-data"
        empty_out = root / "obs-empty.json"
        try:
            rc_empty = _run_obs(exe, root, empty_data, empty_out)
        except OSError as exc:
            report["frozen_runtime"] = {
                "blocked": True,
                "winerror": getattr(exc, "winerror", None),
                "message": "frozen executable blocked by local application control policy",
            }
            checks["frozen_execution_blocked_4551"] = (
                getattr(exc, "winerror", None) == 4551
            )
            report["ok"] = False
            out_path = Path(args.out) if args.out else root / "verify-report.json"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(json.dumps({"ok": False, "report": str(out_path)}, ensure_ascii=False))
            return 2
        empty = load_summary(empty_out)
        report["steps"]["obs_empty_exit"] = rc_empty
        report["steps"]["obs_empty_summary"] = empty
        checks["obs_empty_exit_zero"] = rc_empty == 0
        for key in EXPECTED_OBS_CHECKS:
            checks[f"empty_{key}"] = bool(empty.get("checks", {}).get(key))
        save_dir = root / "saved-obs"
        checks["obs_empty_saved_docx"] = any(save_dir.glob("*.docx"))

        # Old 0005 synthetic DB: upgrade and reopen through the frozen package.
        old_data = root / "old-data"
        old_data.mkdir(parents=True, exist_ok=True)
        _build_0005(old_data / "kindergarten.db")
        old_out = root / "obs-old.json"
        rc_old = _run_obs(exe, root, old_data, old_out)
        old = load_summary(old_out)
        report["steps"]["obs_old_exit"] = rc_old
        report["steps"]["obs_old_summary"] = old
        checks["obs_old_exit_zero"] = rc_old == 0
        for key in EXPECTED_OBS_CHECKS:
            checks[f"old_{key}"] = bool(old.get("checks", {}).get(key))
        db = old_data / "kindergarten.db"
        version = _query(db, "SELECT version_num FROM local_alembic_version")
        checks["old_upgraded_0006"] = version and version[0][0] == (
            "20261025_0006_local_game_observations"
        )
        checks["old_plan_preserved"] = bool(
            _query(db, "SELECT count(*) FROM local_daily_plans")[0][0]
        )
        checks["old_content_preserved"] = (
            _query(db, "SELECT count(*) FROM local_daily_plan_contents")[0][0] >= 2
        )
        old_out2 = root / "obs-old-reopen.json"
        rc_reopen = _run_obs(exe, root, old_data, old_out2)
        reopen = load_summary(old_out2)
        report["steps"]["obs_old_reopen_exit"] = rc_reopen
        report["steps"]["obs_old_reopen_summary"] = reopen
        checks["obs_old_reopen_exit_zero"] = rc_reopen == 0
        checks["obs_old_reopen_ok"] = bool(reopen.get("checks", {}).get("obs_ok"))

        report["real_ai"] = (
            "source-level real DeepSeek closure recorded in r02/real-ai; "
            "frozen package real AI unverified because this machine blocks "
            "the EXE with WinError 4551"
        )
        report["ok"] = all(checks.values())
        out_path = Path(args.out) if args.out else root / "verify-report.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"ok": report["ok"], "report": str(out_path)}, ensure_ascii=False))
        return 0 if report["ok"] else 1
    finally:
        if not args.keep:
            # The caller may need the report; it is written before cleanup.
            pass


if __name__ == "__main__":
    raise SystemExit(main())
