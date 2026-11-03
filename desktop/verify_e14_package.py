"""Verify the Windows 11 portable candidate without executing it.

Static mode is the contract default for this round: it reads the candidate
directory and the EXE's CArchive/PYZ bytes directly, compares them with the
current source and the private pre-build source freeze, and never launches the
EXE, a helper, a TLS server, or a subprocess.  Frozen mode is the legacy
execution flow and must be selected explicitly with ``--mode frozen``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import marshal
import os
import re
import sys
import types
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
BACKEND = REPO / "backend"

PRODUCT = "KGNext-E14"
README_NAME = "README-KGNext-E14-win11-r01.txt"
ARCHIVE_NAME = "KGNext-E14-win11-r01.zip"
PACKAGE = REPO / "build" / "desktop-e14-win11-r01" / "package" / PRODUCT
FRONTEND = REPO / "build" / "desktop-e14-win11-r01" / "frontend"
TEMPLATES = BACKEND / "app" / "assets" / "word_templates"
MIGRATIONS = BACKEND / "migrations_local"
ALEMBIC = BACKEND / "alembic-local.ini"
DATABASE_REVISION = "20261102_0008_local_weekly_ai"
APP_VERSION = "0.1.0"
PACKAGE_FORMAT = "pyinstaller-onedir-zip-v1"
PLATFORM = "windows"
ARCH = "x64"
PYTHON_VERSION = "3.14.10"
APP_ID = "kindergarten-manager-next"
APP_NAME = "KindergartenManager"
SOURCE_BUILD_ID = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{APP_ID}:{APP_VERSION}:source"))
PILLOW_VERSION = "13.0.0"
REQUIRED_PILLOW_PLUGINS = (
    "_imaging.cp314-win_amd64.pyd",
    "_imagingft.cp314-win_amd64.pyd",
    "_imagingcms.cp314-win_amd64.pyd",
    "_webp.cp314-win_amd64.pyd",
    "_avif.cp314-win_amd64.pyd",
)
ARCHIVE_REQUIRED_MODULES = (
    "app.local.appearance_service",
    "app.local.weekly_plan_api",
    "app.local.weekly_plan_service",
    "app.local.weekly_plan_sources",
    "app.local.weekly_plan_content",
    "app.local.weekly_plan_tokens",
    "app.local.weekly_plan_operations",
    "app.local.weekly_plan_snapshot",
    "app.local.weekly_plan_export_service",
    "app.local.weekly_plan_export_api",
    "app.local.weekly_ai_adoption",
    "app.local.weekly_ai_api",
    "app.local.weekly_ai_candidates",
    "app.local.weekly_ai_contracts",
    "app.local.weekly_ai_inputs",
    "app.local.weekly_ai_service",
    "app.local.weekly_ai_sources",
    "app.local.weekly_materials",
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
    "app.local.config_tokens",
    "app.local.export_service",
    "app.local.daily_plan_service",
    "app.local.prompt_bundles",
    "app.services.word_export_observation",
    "app.services.word_export_docx",
    "app.services.word_export_mapping",
    "app.services.daily_plan_content",
    "app.local.backup_barrier",
    "app.local.backup_format",
    "app.local.backup_fs",
    "app.local.backup_snapshot",
    "app.local.backup_validate",
    "app.local.backup_zip",
    "app.local.restore_fs",
    "app.local.restore_group",
    "app.local.restore_journal",
    "app.local.restore_recovery",
    "app.local.restore_service",
    "app.local.restore_types",
    "maintenance_host",
    "maintenance_lifecycle",
    "update_identity",
    "update_install",
    "update_service",
    "update_github",
    "update_trust",
    "update_manifest",
    "d1_host_api",
    "d1_server",
    "d1_paths",
)
REQUIRED_MAINTENANCE_MODULES = ("maintenance_host", "maintenance_lifecycle")
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
REQUIRED_BACKUP_RESTORE_MODULES = tuple(
    name for name in ARCHIVE_REQUIRED_MODULES if name.startswith("app.local.") and (
        ".backup_" in name or ".restore_" in name
    )
)
VERIFICATION_SUPPORT_PREFIXES = ("maintenance_source_", "verify_", "build_", "test_")
VERIFICATION_SUPPORT_MODULES = ("d2_same_origin",)
REQUIRED_FREEZE_PATHS = (
    "desktop/d1_main.py",
    "desktop/d1_host_api.py",
    "desktop/maintenance_host.py",
    "desktop/maintenance_lifecycle.py",
    "desktop/build_e14.py",
    "desktop/verify_e14_package.py",
    "desktop/verify_e14_portable_archive.py",
    "desktop/requirements-d1.in",
    "desktop/tests/test_windows11_portable_static.py",
    "desktop/check_windows11_target.ps1",
    "frontend/d1.html",
    "frontend/tsconfig.json",
    "backend/app/local/backup_snapshot.py",
    "backend/app/local/backup_barrier.py",
    "backend/app/local/backup_format.py",
    "backend/app/local/backup_fs.py",
    "backend/app/local/backup_validate.py",
    "backend/app/local/backup_zip.py",
    "backend/app/local/restore_service.py",
    "backend/app/local/restore_recovery.py",
    "backend/app/local/restore_group.py",
    "backend/app/local/restore_fs.py",
    "backend/app/local/restore_journal.py",
    "backend/app/local/restore_types.py",
    "backend/app/local/runtime.py",
    "backend/app/local/credentials.py",
    "backend/app/local/config_tokens.py",
    "backend/app/assets/word_templates/daily_plan.docx",
    "backend/app/assets/word_templates/weekly_plan.docx",
    "backend/app/local/appearance_service.py",
    "backend/app/local/weekly_plan_api.py",
    "backend/app/local/weekly_plan_service.py",
    "backend/app/local/weekly_plan_sources.py",
    "backend/app/local/weekly_plan_content.py",
    "backend/app/local/weekly_plan_tokens.py",
    "backend/app/local/weekly_plan_operations.py",
    "backend/app/local/weekly_plan_snapshot.py",
    "backend/app/local/weekly_plan_export_service.py",
    "backend/app/local/weekly_plan_export_api.py",
    "backend/app/local/weekly_ai_adoption.py",
    "backend/app/local/weekly_ai_api.py",
    "backend/app/local/weekly_ai_candidates.py",
    "backend/app/local/weekly_ai_contracts.py",
    "backend/app/local/weekly_ai_inputs.py",
    "backend/app/local/weekly_ai_service.py",
    "backend/app/local/weekly_ai_sources.py",
    "backend/app/local/weekly_materials.py",
    "backend/migrations_local/versions/20261101_0007_local_weekly_plans.py",
    "backend/migrations_local/versions/20261102_0008_local_weekly_ai.py",
)
REQUIRED_STATIC_CHECKS = (
    "static_no_execution",
    "static_no_production_imports",
    "package_root_present",
    "package_exe_present",
    "entry_exe",
    "package_info_present",
    "package_info_portable",
    "package_info_metadata_exact",
    "package_info_source_commit",
    "package_info_unsigned_internal_test",
    "package_info_frontend_digest",
    "build_identity_present",
    "build_identity_valid",
    "build_identity_uuid",
    "build_identity_not_source_id",
    "build_identity_version",
    "build_identity_revision",
    "build_identity_matches_package_info",
    "source_freeze_present",
    "source_freeze_schema",
    "source_freeze_stable",
    "source_freeze_digest_matches",
    "source_freeze_current_matches",
    "source_freeze_required_paths",
    "source_freeze_before_build",
    "verifier_matches_freeze",
    "package_tree_digest_matches_freeze",
    "archive_entry_matches_source",
    "archive_entry_matches_freeze",
    "archive_pyz_all_match",
    "archive_pyz_matches_freeze",
    "archive_required_modules_present",
    "archive_maintenance_modules_present",
    "archive_backup_restore_modules_present",
    "archive_module_count_ok",
    "archive_verification_support_separated",
    "archive_no_unexpected_production_modules",
    "bundle_frontend_matches",
    "frontend_digest_matches",
    "bundle_templates_match",
    "bundle_migrations_match",
    "bundle_alembic_matches",
    "no_package_cache_files",
    "observation_templates",
    "migration_0006",
    "pillow_plugins_present",
    "pillow_license_present",
    "pillow_license_matches_source",
    "privacy_no_private_paths",
    "privacy_no_private_keys",
    "no_absolute_paths_in_metadata",
    "privacy_no_absolute_paths_in_code",
    "privacy_no_absolute_paths_in_text",
    "signature_not_claimed",
)
TEXT_SUFFIXES = {
    ".txt", ".md", ".json", ".html", ".htm", ".js", ".mjs", ".cjs", ".css",
    ".map", ".ini", ".cfg", ".yaml", ".yml", ".xml", ".py", ".ts", ".mako",
}
FORBIDDEN_PATH_TOKENS = (
    "evidence/", "source-freeze", "source_freeze", "real-ai", "old-upgrade",
    "source-hash", ".dpapi", ".kgmbackup", ".db", ".db-wal", ".db-shm",
    ".sqlite", ".sqlite3", ".log", ".env", "id_rsa", "id_ed25519",
    ".p12", ".pfx", ".key", "__pycache__", ".pyc", ".pyo",
)
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".avif")
MAX_PUBLIC_CERT_BYTES = 4 * 1024 * 1024
ABS_PATH_RE = re.compile(
    r"(?i)(?:^|[^A-Za-z0-9])(?:[A-Za-z]:[\\/]|\\\\[^\\/\s]+[\\/]|/(?:Users|home)/)"
)
KNOWN_SBOM_REL = (
    "_internal/cryptography-50.0.1.dist-info/sboms/cryptography-rust.cyclonedx.json"
)
UPSTREAM_SBOM_REF_RE = re.compile(
    r"file:///[A-Za-z]:/[^\"'\s]*/cryptography/wheelhouse/"
    r"[^\"'\s]*/cryptography-50\.0\.1/src/rust(?:/[A-Za-z0-9_.-]+)?"
    r"#[A-Za-z0-9_.@-]*0\.50\.1"
)
PRIVATE_HOME_RE = re.compile(
    r"(?i)(?<![\w])(?:[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s\"']+"
    r"|/Users/[^/\s\"']+|/home/[^/\s\"']+)"
)
POSIX_HOME_RE = re.compile(r"(?<![\w])/(?:Users|home)/[^/\s\"']+")
UNC_RE = re.compile(r"(?<![\w])\\\\[A-Za-z0-9._-]+[\\/][A-Za-z0-9._$-]+")
UNC_EXTENDED_RE = re.compile(r"(?i)\\\\\?\\[A-Za-z]:[\\/][^\s\"']*")
DRIVE_RE = re.compile(r"(?i)(?<![\w])([A-Za-z]):[\\/](?![\\/])[^\s\"']+")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
RESERVED_NAMES = {
    "con", "prn", "aux", "nul",
    *{f"com{i}" for i in range(1, 10)},
    *{f"lpt{i}" for i in range(1, 10)},
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_bool(value: Any) -> bool:
    return type(value) is bool


def _is_reparse(path: Path) -> bool:
    try:
        stat = path.lstat()
    except OSError:
        return False
    attributes = getattr(stat, "st_file_attributes", 0)
    return path.is_symlink() or bool(attributes & 0x400)


def _plain_dir(path: Path) -> bool:
    return path.is_dir() and not _is_reparse(path)


def _iter_plain_files(root: Path) -> list[Path]:
    if _is_reparse(root):
        raise ValueError("reparse point in package tree")
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if _is_reparse(path):
            raise ValueError(f"reparse point: {path}")
        if path.is_file():
            files.append(path)
    return files


def _posix(relative: Path) -> str:
    return relative.as_posix()


def _json_loads(raw: bytes) -> Any:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def bad_number(text: str):
        raise ValueError(f"non-finite number: {text}")

    return json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=pairs,
        parse_constant=bad_number,
    )


def _read_json(path: Path, limit: int = 16 * 1024 * 1024) -> Any:
    raw = path.read_bytes()
    if len(raw) > limit:
        raise ValueError(f"JSON too large: {path}")
    return _json_loads(raw)


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _validate_rel_path(raw: Any, *, max_length: int = 512, max_depth: int = 24) -> str | None:
    if not isinstance(raw, str) or not raw or len(raw) > max_length:
        return None
    if "\x00" in raw or any(ord(ch) < 32 or ord(ch) == 127 for ch in raw):
        return None
    if "\\" in raw or raw.startswith("/") or raw.startswith("//"):
        return None
    if len(raw) >= 2 and raw[1] == ":":
        return None
    if unicodedata.normalize("NFC", raw) != raw:
        return None
    parts = raw.split("/")
    if len(parts) > max_depth or any(part in ("", ".", "..") for part in parts):
        return None
    for part in parts:
        if part.endswith(" ") or part.endswith("."):
            return None
        if ":" in part:
            return None
        stem = part.split(".", 1)[0].casefold()
        if stem in RESERVED_NAMES:
            return None
    return raw


def _contains_forbidden_name(relative: str) -> str | None:
    lower = relative.casefold()
    for token in FORBIDDEN_PATH_TOKENS:
        if token in lower:
            return token
    if lower.endswith(IMAGE_SUFFIXES) and not lower.startswith("_internal/frontend/"):
        return "image-outside-frontend"
    return None


def _tree_entries(root: Path) -> list[dict]:
    files = _iter_plain_files(root)
    entries = []
    for path in files:
        relative = _posix(path.relative_to(root))
        if "__pycache__" in path.parts or path.suffix.lower() in {".pyc", ".pyo"}:
            continue
        entries.append(
            {
                "path": relative,
                "size": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    return entries


def _digest_entries(entries: Iterable[Mapping[str, Any]]) -> str:
    payload = [
        {"path": str(item["path"]), "sha256": str(item["sha256"])}
        for item in sorted(entries, key=lambda item: str(item["path"]))
    ]
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _sha256_bytes(text.encode("utf-8"))


def _tree_digest(root: Path) -> tuple[str, int, list[dict]]:
    entries = _tree_entries(root)
    return _digest_entries(entries), len(entries), entries


def _freeze_digest(files: Iterable[Mapping[str, Any]]) -> str:
    return _digest_entries(files)


def _freeze_files_map(files: Any) -> tuple[dict[str, dict], list[str]]:
    errors: list[str] = []
    result: dict[str, dict] = {}
    if not isinstance(files, list) or not files:
        return {}, ["freeze files missing or empty"]
    for item in files:
        if not isinstance(item, dict):
            errors.append("freeze file entry is not an object")
            continue
        relative = _validate_rel_path(item.get("path"))
        if relative is None:
            errors.append(f"freeze path unsafe: {item.get('path')!r}")
            continue
        size = item.get("size")
        digest = item.get("sha256")
        if type(size) is not int or size < 0:
            errors.append(f"freeze size invalid: {relative}")
        if not isinstance(digest, str) or not SHA_RE.match(digest):
            errors.append(f"freeze sha invalid: {relative}")
        if relative in result:
            errors.append(f"freeze duplicate path: {relative}")
        result[relative] = item
    return result, errors


def _freeze_current_mismatches(files: Mapping[str, dict]) -> list[str]:
    mismatches: list[str] = []
    for relative, item in files.items():
        path = (REPO / relative)
        try:
            path.resolve(strict=True).relative_to(REPO.resolve())
        except (OSError, ValueError):
            mismatches.append(relative)
            continue
        if not path.is_file() or _is_reparse(path):
            mismatches.append(relative)
            continue
        if path.stat().st_size != item.get("size") or _sha256(path) != item.get("sha256"):
            mismatches.append(relative)
    return sorted(mismatches)


def _freeze_changes(before: Mapping[str, dict], after: Mapping[str, dict]) -> dict:
    changed = sorted(
        key for key in before.keys() & after.keys()
        if before[key].get("sha256") != after[key].get("sha256")
    )
    added = sorted(after.keys() - before.keys())
    removed = sorted(before.keys() - after.keys())
    return {
        "stable": not changed and not added and not removed,
        "changed": changed,
        "added": added,
        "removed": removed,
    }


def _load_freeze(path: Path, package_info: Mapping[str, Any], self_rel: str) -> dict:
    result = {
        "present": False,
        "sha256": None,
        "commit": None,
        "digest": None,
        "before": {},
        "after": {},
        "schema_ok": False,
        "stable": False,
        "changes_ok": False,
        "digest_ok": False,
        "current_mismatches": [],
        "required_missing": [],
        "self_matches": False,
        "before_build": False,
        "package_tree_digest": None,
        "errors": [],
    }
    if not path.is_file():
        result["errors"].append("source freeze missing")
        return result
    result["present"] = True
    result["sha256"] = _sha256(path)
    try:
        report = _read_json(path)
    except Exception as exc:  # noqa: BLE001
        result["errors"].append(f"freeze JSON: {type(exc).__name__}: {exc}")
        return result
    if not isinstance(report, dict):
        result["errors"].append("freeze root is not an object")
        return result
    before = report.get("before")
    after = report.get("after")
    if not isinstance(before, dict) or not isinstance(after, dict):
        result["errors"].append("freeze before/after missing")
        return result
    before_files, before_errors = _freeze_files_map(before.get("files"))
    after_files, after_errors = _freeze_files_map(after.get("files"))
    result["before"] = before_files
    result["after"] = after_files
    result["errors"].extend(before_errors + after_errors)
    result["commit"] = report.get("commit") or before.get("commit")
    if not isinstance(result["commit"], str) or not COMMIT_RE.match(result["commit"]):
        result["errors"].append("freeze commit invalid")
    before_digest = _freeze_digest(before_files.values()) if before_files else None
    after_digest = _freeze_digest(after_files.values()) if after_files else None
    result["digest"] = before_digest
    result["digest_ok"] = (
        before_digest is not None
        and before_digest == after_digest
        and before.get("digest") == before_digest
        and after.get("digest") == after_digest
        and before.get("file_count") == len(before_files)
        and after.get("file_count") == len(after_files)
    )
    computed_changes = _freeze_changes(before_files, after_files)
    declared_changes = report.get("changes")
    result["changes_ok"] = (
        isinstance(declared_changes, dict)
        and declared_changes.get("stable") is True
        and declared_changes.get("changed") == computed_changes["changed"]
        and declared_changes.get("added") == computed_changes["added"]
        and declared_changes.get("removed") == computed_changes["removed"]
    )
    result["stable"] = (
        report.get("stable") is True
        and computed_changes["stable"]
        and result["digest_ok"]
        and result["changes_ok"]
        and not result["errors"]
    )
    result["current_mismatches"] = _freeze_current_mismatches(before_files)
    result["required_missing"] = sorted(
        path for path in REQUIRED_FREEZE_PATHS if path not in before_files or path not in after_files
    )
    self_entry = before_files.get(self_rel)
    result["self_matches"] = (
        self_entry is not None
        and self_entry.get("sha256") == _sha256(Path(__file__))
        and self_entry.get("size") == Path(__file__).stat().st_size
    )
    built_at = _parse_iso(package_info.get("built_at"))
    before_at = _parse_iso(before.get("generated_at"))
    result["before_build"] = (
        built_at is not None and before_at is not None and before_at <= built_at
    )
    package_tree = report.get("package_tree_digest")
    if isinstance(package_tree, str) and SHA_RE.match(package_tree):
        result["package_tree_digest"] = package_tree
    result["schema_ok"] = (
        bool(before_files)
        and bool(after_files)
        and result["commit"] is not None
        and not result["errors"]
        and all(
            isinstance(files.get("generated_at"), str)
            for files in (before, after)
        )
    )
    return result


def _package_info_checks(data: Any, expected_product: str) -> dict:
    checks = {
        "present": isinstance(data, dict),
        "portable": False,
        "metadata_exact": False,
        "source_commit": False,
        "unsigned_internal_test": False,
        "frontend_digest": False,
        "errors": [],
    }
    if not isinstance(data, dict):
        checks["errors"].append("package-info missing or not an object")
        return checks
    package = data.get("package")
    checks["portable"] = package == expected_product and not Path(str(package)).is_absolute()
    commit = data.get("source_commit")
    checks["source_commit"] = isinstance(commit, str) and bool(COMMIT_RE.match(commit))
    checks["unsigned_internal_test"] = data.get("unsigned_internal_test") is True
    frontend_digest = data.get("frontend_digest")
    frontend_count = data.get("frontend_file_count")
    checks["frontend_digest"] = (
        isinstance(frontend_digest, str)
        and bool(SHA_RE.match(frontend_digest))
        and type(frontend_count) is int
        and frontend_count > 0
    )
    required_strings = (
        "app", "built_at", "package", "version", "build_id",
        "database_revision", "build_identity", "source_freeze_digest",
    )
    exact = all(isinstance(data.get(key), str) and data.get(key) for key in required_strings)
    exact = exact and data.get("app") == expected_product
    exact = exact and data.get("version") == APP_VERSION
    exact = exact and data.get("database_revision") == DATABASE_REVISION
    exact = exact and data.get("package") == expected_product
    exact = exact and isinstance(data.get("source_freeze_digest"), str)
    exact = exact and bool(SHA_RE.match(str(data.get("source_freeze_digest"))))
    exact = exact and isinstance(data.get("build_id"), str)
    try:
        uuid.UUID(str(data.get("build_id")))
    except (ValueError, TypeError, AttributeError):
        exact = False
    exact = exact and data.get("pillow_version") == PILLOW_VERSION
    exact = exact and data.get("pillow_license_included") is True
    exact = exact and isinstance(data.get("pillow_license_sha256"), str)
    exact = exact and bool(SHA_RE.match(str(data.get("pillow_license_sha256"))))
    plugins = data.get("pillow_plugins")
    exact = exact and isinstance(plugins, list) and all(
        isinstance(name, str) for name in plugins
    )
    exact = exact and all(name in plugins for name in REQUIRED_PILLOW_PLUGINS)
    exact = exact and type(data.get("cache_files_pruned")) is int
    exact = exact and data.get("cache_files_pruned") >= 0
    migrations = data.get("migrations")
    exact = exact and isinstance(migrations, list)
    if isinstance(migrations, list):
        names = {str(item).replace("\\", "/") for item in migrations}
        exact = exact and all(
            any(name.endswith(suffix) for name in names)
            for suffix in (
                "20261012_0001_local_baseline.py",
                "20261012_0002_local_require_first_revision.py",
                "20261014_0003_local_config_maintenance.py",
                "20261017_0004_local.py",
                "20261023_0005_local_history.py",
                "20261025_0006_local_game_observations.py",
                "20261101_0007_local_weekly_plans.py",
                "20261102_0008_local_weekly_ai.py",
            )
        )
    templates = data.get("templates")
    exact = exact and isinstance(templates, list)
    if isinstance(templates, list):
        exact = exact and all(
            name in templates
            for name in (
                "daily_plan.docx", "weekly_plan.docx", "observation_public.docx",
                "observation_indoor.docx", "observation_outdoor.docx",
            )
        )
    checks["metadata_exact"] = bool(exact)
    if not exact:
        checks["errors"].append("package-info required fields/types invalid")
    if _has_absolute_path(data):
        checks["errors"].append("package-info contains an absolute path")
        checks["metadata_exact"] = False
    return checks


def _has_absolute_path(value: Any) -> bool:
    if isinstance(value, str):
        return bool(ABS_PATH_RE.search(value))
    if isinstance(value, list):
        return any(_has_absolute_path(item) for item in value)
    if isinstance(value, dict):
        return any(_has_absolute_path(item) for item in value.values())
    return False


def _known_sbom_info(package_root: Path) -> dict:
    source = (
        REPO
        / "desktop"
        / ".venv-d1"
        / "Lib"
        / "site-packages"
        / "cryptography-50.0.1.dist-info"
        / "sboms"
        / "cryptography-rust.cyclonedx.json"
    )
    actual = package_root / KNOWN_SBOM_REL
    actual_sha = _sha256(actual) if actual.is_file() else None
    source_sha = _sha256(source) if source.is_file() else None
    return {
        "path": KNOWN_SBOM_REL,
        "actual_sha256": actual_sha,
        "source_sha256": source_sha,
        "matches_source": bool(actual_sha and source_sha and actual_sha == source_sha),
    }


def scan_text_private_paths(
    text: str,
    *,
    source_path: str = "",
    metadata: bool = False,
    known_sbom: Mapping[str, Any] | None = None,
) -> dict:
    """Discriminate real private path tokens from regex/escape grammar.

    Metadata stays strict.  General text rejects user/home paths, real UNC
    tokens and non-upstream absolute paths; the one known cryptography SBOM
    may carry its publisher build reference only when its bytes match the
    installed dependency source.
    """
    result = {
        "source_path": source_path,
        "metadata": bool(metadata),
        "violations": [],
        "allowed_build_references": [],
        "known_sbom": dict(known_sbom) if known_sbom else None,
    }
    if not isinstance(text, str):
        result["violations"].append(
            {"kind": "invalid-text", "match": "", "reason": "not text"}
        )
        return result
    known_allowed = bool(
        not metadata
        and known_sbom
        and known_sbom.get("matches_source")
        and source_path == str(known_sbom.get("path"))
    )
    allowed_spans: list[tuple[int, int]] = []
    seen_refs: set[str] = set()
    if known_allowed:
        for match in UPSTREAM_SBOM_REF_RE.finditer(text):
            allowed_spans.append(match.span())
            value = match.group(0)
            if value not in seen_refs:
                seen_refs.add(value)
                result["allowed_build_references"].append(
                    {
                        "class": "upstream-sbom-build-reference",
                        "match": value,
                        "source_sha256": known_sbom.get("source_sha256"),
                    }
                )
    if known_sbom and not known_sbom.get("matches_source"):
        result["violations"].append(
            {
                "kind": "known-sbom-modified",
                "match": source_path,
                "reason": "known SBOM bytes differ from installed publisher metadata",
            }
        )
    spans: list[tuple[int, int, str, str]] = []
    for kind, regex in (
        ("user-home", PRIVATE_HOME_RE),
        ("posix-home", POSIX_HOME_RE),
        ("unc", UNC_RE),
        ("unc-extended", UNC_EXTENDED_RE),
        ("drive-path", DRIVE_RE),
    ):
        for match in regex.finditer(text):
            spans.append((match.start(), match.end(), kind, match.group(0)))
    spans.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    non_drive_spans = [(start, end) for start, end, kind, _ in spans if kind != "drive-path"]
    occupied: list[tuple[int, int]] = []
    for start, end, kind, value in spans:
        if metadata:
            pass
        elif kind == "drive-path":
            if any(left <= start and end <= right for left, right in allowed_spans):
                continue
            if any(left <= start and end <= right for left, right in non_drive_spans):
                continue
        if any(left <= start and end <= right for left, right in occupied):
            continue
        if any(start <= left and right <= end for left, right in occupied):
            continue
        occupied.append((start, end))
        result["violations"].append(
            {"kind": kind, "match": value[:160], "reason": kind}
        )
    return result


def _identity_checks(package_root: Path, package_info: Mapping[str, Any]) -> dict:
    result = {
        "present": False,
        "valid": False,
        "uuid": False,
        "not_source_id": False,
        "version": False,
        "revision": False,
        "matches_package_info": False,
        "data": None,
        "errors": [],
    }
    path = package_root / "_internal" / "build_identity.json"
    result["present"] = path.is_file()
    if not path.is_file():
        result["errors"].append("build_identity.json missing")
        return result
    try:
        data = _read_json(path)
    except Exception as exc:  # noqa: BLE001
        result["errors"].append(f"build_identity JSON: {type(exc).__name__}: {exc}")
        return result
    if not isinstance(data, dict):
        result["errors"].append("build_identity not an object")
        return result
    result["data"] = data
    expected = {
        "app_id": APP_ID,
        "app_name": APP_NAME,
        "channel": "stable",
        "version": APP_VERSION,
        "package_format": PACKAGE_FORMAT,
        "platform": PLATFORM,
        "arch": ARCH,
        "python": PYTHON_VERSION,
        "database_revision": DATABASE_REVISION,
    }
    valid = all(data.get(key) == value for key, value in expected.items())
    build_id = data.get("build_id")
    try:
        parsed = uuid.UUID(str(build_id))
        result["uuid"] = True
    except (ValueError, TypeError, AttributeError):
        parsed = None
    valid = valid and parsed is not None
    result["not_source_id"] = bool(parsed is not None and str(parsed) != SOURCE_BUILD_ID)
    result["version"] = data.get("version") == APP_VERSION
    result["revision"] = data.get("database_revision") == DATABASE_REVISION
    result["matches_package_info"] = (
        data.get("build_id") == package_info.get("build_id")
        and data.get("database_revision") == package_info.get("database_revision")
    )
    result["valid"] = bool(valid)
    return result


def _module_source_path(name: str) -> Path | None:
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_.]*$", name):
        return None
    if name.startswith("app."):
        base = BACKEND / "app"
        relative = Path(*name.split(".")[1:])
        candidate = base / relative.with_suffix(".py")
        if candidate.is_file():
            return candidate
        candidate = base / relative / "__init__.py"
        return candidate if candidate.is_file() else None
    if name.startswith("tests."):
        candidate = BACKEND / "tests" / Path(*name.split(".")[1:]).with_suffix(".py")
        return candidate if candidate.is_file() else None
    candidate = HERE / f"{name}.py"
    return candidate if candidate.is_file() else None


def _module_class(name: str) -> str:
    if name == "d1_main":
        return "entry"
    if name in VERIFICATION_SUPPORT_MODULES or name.startswith(VERIFICATION_SUPPORT_PREFIXES):
        return "verification_support"
    if name.startswith("app.") or name in REQUIRED_MAINTENANCE_MODULES:
        return "production"
    if name.startswith(("update_", "d0_", "d1_")):
        return "production"
    return "other"


def _code_filenames(code: types.CodeType) -> list[str]:
    names = [code.co_filename]
    for constant in code.co_consts:
        if isinstance(constant, types.CodeType):
            names.extend(_code_filenames(constant))
    return names


def _pyinstaller_reader_paths() -> tuple[Path, Path]:
    """Locate the installed PyInstaller leaf files without importing it.

    Importing ``PyInstaller`` or ``PyInstaller.archive.readers`` executes the
    top-level package/compat platform probe, which may call WMI and even
    spawn ``ver``.  Static verification must not launch processes.  The
    distribution metadata gives us the files directly.
    """
    from importlib import metadata

    try:
        distribution = metadata.distribution("pyinstaller")
    except metadata.PackageNotFoundError as exc:
        raise RuntimeError("PyInstaller distribution unavailable") from exc
    package_root = Path(distribution.locate_file("PyInstaller"))
    leaf = package_root / "loader" / "pyimod01_archive.py"
    reader = package_root / "archive" / "readers.py"
    if not leaf.is_file() or not reader.is_file():
        raise RuntimeError("PyInstaller archive reader files unavailable")
    return leaf, reader


def _load_carchive_reader():
    """Load the real installed CArchiveReader with a local leaf dependency.

    ``archive/readers.py`` imports exactly two names from
    ``PyInstaller.loader.pyimod01_archive``.  That loader leaf is pure stdlib.
    Bind those names directly in the reader module and execute the installed
    source, so the real parser is used without importing the PyInstaller
    parent package or faking its ``sys.modules`` entries.
    """
    import importlib.util

    leaf_path, reader_path = _pyinstaller_reader_paths()
    leaf_source = leaf_path.read_text(encoding="utf-8")
    if (
        "class ArchiveReadError" not in leaf_source
        or "class ZlibArchiveReader" not in leaf_source
    ):
        raise RuntimeError("PyInstaller archive leaf incompatible")
    leaf_spec = importlib.util.spec_from_file_location(
        "_kgm_pyinstaller_archive_leaf", leaf_path
    )
    if leaf_spec is None or leaf_spec.loader is None:
        raise RuntimeError("PyInstaller archive leaf cannot be loaded")
    leaf_module = importlib.util.module_from_spec(leaf_spec)
    leaf_spec.loader.exec_module(leaf_module)

    reader_source = reader_path.read_text(encoding="utf-8")
    import_line = (
        "from PyInstaller.loader.pyimod01_archive import "
        "ZlibArchiveReader, ArchiveReadError"
    )
    if reader_source.count(import_line) != 1:
        raise RuntimeError("PyInstaller archive reader dependency shape incompatible")
    reader_module = types.ModuleType("_kgm_pyinstaller_archive_reader")
    reader_module.__file__ = str(reader_path)
    reader_module.__dict__["ZlibArchiveReader"] = leaf_module.ZlibArchiveReader
    reader_module.__dict__["ArchiveReadError"] = leaf_module.ArchiveReadError
    exec(
        compile(reader_source.replace(import_line, ""), str(reader_path), "exec"),
        reader_module.__dict__,
    )
    reader_class = getattr(reader_module, "CArchiveReader", None)
    if not isinstance(reader_class, type):
        raise RuntimeError("PyInstaller CArchiveReader missing")
    return reader_class


def _archive_static_report(package_root: Path, freeze: Mapping[str, Any]) -> dict:
    import d2_same_origin
    CArchiveReader = _load_carchive_reader()

    exe = package_root / f"{package_root.name}.exe"
    result = {
        "exe": str(exe),
        "exe_present": exe.is_file(),
        "readable": False,
        "entry": {},
        "pyz_total_modules": 0,
        "scanned_modules": 0,
        "production_mismatched": [],
        "production_unavailable": [],
        "support_mismatched": [],
        "support_unavailable": [],
        "support_modules": {},
        "missing_required": [],
        "missing_maintenance": [],
        "missing_backup_restore": [],
        "module_count": 0,
        "production_all_match": False,
        "production_match_freeze": False,
        "unexpected_production": [],
        "code_absolute_paths": [],
        "error": None,
    }
    if not exe.is_file():
        result["error"] = "package EXE missing"
        return result
    if _is_reparse(exe):
        result["error"] = "package EXE is a reparse point"
        return result
    if exe.stat().st_size > 512 * 1024 * 1024:
        result["error"] = "package EXE exceeds 512 MiB"
        return result
    try:
        reader = CArchiveReader(str(exe))
        if "PYZ.pyz" not in reader.toc:
            result["error"] = "PYZ.pyz missing"
            return result
        entry_data = reader.extract("d1_main")
        if not isinstance(entry_data, (bytes, bytearray)):
            result["error"] = "d1_main entry is not marshalled bytes"
            return result
        entry_code = marshal.loads(bytes(entry_data))
        entry_fp = d2_same_origin.fingerprint_code(entry_code)
        source_entry = d2_same_origin.fingerprint_source(HERE / "d1_main.py")
        freeze_entry = freeze.get("before", {}).get("desktop/d1_main.py")
        result["entry"] = {
            "frozen_sha256": entry_fp,
            "source_sha256": source_entry,
            "freeze_sha256": (freeze_entry or {}).get("sha256"),
            "matches_source": entry_fp == source_entry,
            "matches_freeze": bool(
                freeze_entry and entry_fp == source_entry
                and freeze_entry.get("sha256") == _sha256(HERE / "d1_main.py")
            ),
        }
        result["code_absolute_paths"].extend(
            name for name in _code_filenames(entry_code) if ABS_PATH_RE.search(name)
        )
        pyz = reader.open_embedded_archive("PYZ.pyz")
        result["pyz_total_modules"] = len(pyz.toc)
        modules: dict[str, dict] = {}
        for name in sorted(pyz.toc):
            kind = _module_class(name)
            if kind == "other" or kind == "entry":
                continue
            result["scanned_modules"] += 1
            source = _module_source_path(name)
            target = "verification_support" if kind == "verification_support" else "production"
            if source is None:
                modules[name] = {"class": target, "status": "source_missing"}
                continue
            try:
                code = pyz.extract(name)
                if code is None:
                    modules[name] = {"class": target, "status": "namespace"}
                    continue
                frozen = d2_same_origin.fingerprint_code(code)
                source_hash = d2_same_origin.fingerprint_source(source)
                freeze_sha = (freeze.get("before", {}).get(
                    str(source.relative_to(REPO)).replace("\\", "/")
                ) or {}).get("sha256")
                status = "ok" if frozen == source_hash else "mismatch"
                if freeze_sha is not None and freeze_sha != _sha256(source):
                    status = "freeze_mismatch"
                modules[name] = {
                    "class": target,
                    "status": status,
                    "sha256": frozen,
                    "source_sha256": source_hash,
                    "freeze_sha256": freeze_sha,
                    "source": str(source.relative_to(REPO)).replace("\\", "/"),
                }
                for filename in _code_filenames(code):
                    if ABS_PATH_RE.search(filename):
                        result["code_absolute_paths"].append(filename)
            except Exception as exc:  # noqa: BLE001
                modules[name] = {
                    "class": target,
                    "status": "error",
                    "reason": f"{type(exc).__name__}: {exc}",
                }
        result["module_count"] = len(modules)
        result["support_modules"] = {
            name: item for name, item in modules.items()
            if item["class"] == "verification_support"
        }
        result["production_mismatched"] = sorted(
            name for name, item in modules.items()
            if item["class"] == "production" and item["status"] == "mismatch"
        )
        result["production_unavailable"] = sorted(
            name for name, item in modules.items()
            if item["class"] == "production" and item["status"] != "ok"
        )
        result["support_mismatched"] = sorted(
            name for name, item in modules.items()
            if item["class"] == "verification_support" and item["status"] != "ok"
        )
        result["support_unavailable"] = sorted(
            name for name, item in modules.items()
            if item["class"] == "verification_support" and item["status"] != "ok"
        )
        result["missing_required"] = sorted(
            name for name in ARCHIVE_REQUIRED_MODULES if name not in pyz.toc
        )
        result["missing_maintenance"] = sorted(
            name for name in REQUIRED_MAINTENANCE_MODULES if name not in pyz.toc
        )
        result["missing_backup_restore"] = sorted(
            name for name in REQUIRED_BACKUP_RESTORE_MODULES if name not in pyz.toc
        )
        result["unexpected_production"] = sorted(
            name for name, item in modules.items()
            if item["class"] == "production" and item["status"] != "ok"
        )
        result["readable"] = True
        result["production_all_match"] = bool(
            result["readable"]
            and result["scanned_modules"] > 0
            and not result["production_mismatched"]
            and not result["production_unavailable"]
        )
        result["production_match_freeze"] = bool(
            result["production_all_match"]
            and freeze.get("before")
            and all(
                item.get("freeze_sha256") is not None
                for name, item in modules.items()
                if item["class"] == "production"
            )
        )
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def _frontend_checks(package_root: Path, frontend_build: Path | None, package_info: Mapping[str, Any]) -> dict:
    result = {
        "present": False,
        "matches": False,
        "digest": None,
        "file_count": 0,
        "digest_matches": False,
        "count_matches": False,
        "errors": [],
    }
    bundled = package_root / "_internal" / "frontend"
    result["present"] = _plain_dir(bundled) and (bundled / "d1.html").is_file()
    if not result["present"]:
        result["errors"].append("bundled frontend/d1.html missing")
        return result
    try:
        digest, count, entries = _tree_digest(bundled)
    except Exception as exc:  # noqa: BLE001
        result["errors"].append(f"frontend tree: {type(exc).__name__}: {exc}")
        return result
    result["digest"] = digest
    result["file_count"] = count
    result["digest_matches"] = (
        isinstance(package_info.get("frontend_digest"), str)
        and package_info.get("frontend_digest") == digest
    )
    result["count_matches"] = package_info.get("frontend_file_count") == count
    if frontend_build is None or not _plain_dir(frontend_build):
        result["errors"].append("frontend build input missing")
        return result
    try:
        expected = _tree_entries(frontend_build)
        actual = {entry["path"]: entry for entry in entries}
        wanted = {entry["path"]: entry for entry in expected}
        result["matches"] = (
            set(actual) == set(wanted)
            and all(
                actual[path]["size"] == wanted[path]["size"]
                and actual[path]["sha256"] == wanted[path]["sha256"]
                for path in wanted
            )
        )
    except Exception as exc:  # noqa: BLE001
        result["errors"].append(f"frontend build tree: {type(exc).__name__}: {exc}")
    return result


def _tree_matches(package_root: Path, relative: str, source: Path) -> bool:
    bundled = package_root / relative
    if not bundled.exists() or _is_reparse(bundled):
        return False
    try:
        if source.is_file():
            return bundled.is_file() and _sha256(bundled) == _sha256(source)
        if not source.is_dir():
            return False
        actual = {entry["path"]: entry for entry in _tree_entries(bundled)}
        expected = {entry["path"]: entry for entry in _tree_entries(source)}
        return (
            set(actual) == set(expected)
            and all(
                actual[path]["size"] == expected[path]["size"]
                and actual[path]["sha256"] == expected[path]["sha256"]
                for path in expected
            )
        )
    except Exception:  # noqa: BLE001
        return False


def _resource_checks(package_root: Path) -> dict:
    internal = package_root / "_internal"
    checks = {
        "templates_match": _tree_matches(package_root, "_internal/app/assets/word_templates", TEMPLATES),
        "migrations_match": _tree_matches(package_root, "_internal/migrations_local", MIGRATIONS),
        "alembic_match": _tree_matches(package_root, "_internal/alembic-local.ini", ALEMBIC),
        "observation_templates": all(
            (internal / "app/assets/word_templates" / name).is_file()
            for name in (
                "observation_public.docx",
                "observation_indoor.docx",
                "observation_outdoor.docx",
            )
        ),
        "migration_0006": (
            internal / "migrations_local/versions/20261025_0006_local_game_observations.py"
        ).is_file(),
        "pillow_plugins": sorted(
            path.name for path in (internal / "PIL").glob("_*.cp314-win_amd64.pyd")
        ),
        "license_present": (package_root / "licenses/Pillow-LICENSE.txt").is_file(),
        "license_matches": False,
        "caches": [],
    }
    license_path = package_root / "licenses/Pillow-LICENSE.txt"
    source_license = (
        REPO / "desktop/.venv-d1/Lib/site-packages/pillow-13.0.0.dist-info/licenses/LICENSE"
    )
    checks["license_matches"] = (
        checks["license_present"] and source_license.is_file()
        and _sha256(license_path) == _sha256(source_license)
    )
    checks["caches"] = [
        str(path.relative_to(package_root)).replace("\\", "/")
        for path in package_root.rglob("*")
        if path.name == "__pycache__" or path.suffix.lower() in {".pyc", ".pyo"}
    ]
    return checks


def _privacy_checks(package_root: Path, archive: Mapping[str, Any]) -> dict:
    result = {
        "private_paths": [],
        "private_keys": [],
        "absolute_metadata": [],
        "absolute_text": [],
        "allowed_build_references": [],
        "known_sbom": None,
        "text_scan_complete": True,
        "errors": [],
    }
    known_sbom = _known_sbom_info(package_root)
    result["known_sbom"] = known_sbom
    try:
        files = _iter_plain_files(package_root)
    except Exception as exc:  # noqa: BLE001
        result["errors"].append(f"package tree: {type(exc).__name__}: {exc}")
        return result
    for path in files:
        relative = str(path.relative_to(package_root)).replace("\\", "/")
        token = _contains_forbidden_name(relative)
        if token:
            result["private_paths"].append({"path": relative, "reason": token})
        lower = relative.casefold()
        if lower.endswith((".pem", ".crt", ".cer")):
            try:
                with path.open("rb") as handle:
                    head = handle.read(MAX_PUBLIC_CERT_BYTES)
                text = head.decode("utf-8", errors="ignore")
            except OSError:
                result["private_keys"].append({"path": relative, "reason": "unreadable"})
                continue
            if "PRIVATE KEY" in text or "BEGIN CERTIFICATE" not in text:
                result["private_keys"].append({"path": relative, "reason": "not-public-certificate"})
        elif lower.endswith((".key", ".p12", ".pfx", ".dpapi")):
            result["private_keys"].append({"path": relative, "reason": "private-key-material"})
        elif path.suffix.lower() in TEXT_SUFFIXES and path.stat().st_size <= 16 * 1024 * 1024:
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if "PRIVATE KEY" in text:
                result["private_keys"].append({"path": relative, "reason": "private-key-marker"})
            scan = scan_text_private_paths(
                text,
                source_path=relative,
                known_sbom=known_sbom if relative == KNOWN_SBOM_REL else None,
            )
            for violation in scan["violations"]:
                result["absolute_text"].append({"path": relative, **violation})
            result["allowed_build_references"].extend(scan["allowed_build_references"])
        elif path.suffix.lower() in TEXT_SUFFIXES:
            result["text_scan_complete"] = False
    for relative in ("package-info.json", "_internal/build_identity.json"):
        path = package_root / relative
        if path.is_file():
            try:
                data = _read_json(path)
            except Exception:
                continue
            scan = scan_text_private_paths(
                json.dumps(data, ensure_ascii=False),
                source_path=relative,
                metadata=True,
            )
            for violation in scan["violations"]:
                result["absolute_metadata"].append({"path": relative, **violation})
    result["absolute_code"] = sorted(set(archive.get("code_absolute_paths") or []))
    return result


def _required_status(
    checks: Mapping[str, Any], required: Iterable[str], unknowns: Mapping[str, Any]
) -> dict:
    missing = sorted(name for name in required if name not in checks)
    non_bool = sorted(name for name, value in checks.items() if type(value) is not bool)
    unknown = sorted(name for name in unknowns if name in required or name in checks)
    failed = sorted(
        name for name in required
        if name in checks and type(checks[name]) is bool and checks[name] is not True
    )
    ok = not missing and not non_bool and not unknown and not failed
    return {
        "missing": missing,
        "non_bool": non_bool,
        "unknown": unknown,
        "failed": failed,
        "ok": ok,
    }


def _existing_components(path: Path) -> tuple[bool, str | None]:
    """Check every existing component, including the leaf, before resolving."""
    raw = str(path).replace("\\", "/")
    if any(part == ".." for part in raw.split("/")):
        return False, f"parent segment in path: {path}"
    absolute = Path(os.path.abspath(str(path)))
    current = absolute
    while True:
        if current.exists() or current.is_symlink():
            if _is_reparse(current):
                return False, f"reparse point in path: {current}"
            if current != absolute and not current.is_dir():
                return False, f"file used as parent: {current}"
        if current.parent == current:
            break
        current = current.parent
    return True, None


def _plain_input(path: Path, label: str) -> tuple[Path | None, str | None]:
    ok, reason = _existing_components(path)
    if not ok:
        return None, f"{label}: {reason}"
    absolute = Path(os.path.abspath(str(path)))
    return absolute.resolve(strict=False), None


def _report_path_ok(
    out: Path, forbidden: Iterable[Path]
) -> tuple[bool, str | None]:
    ok, reason = _existing_components(out)
    if not ok:
        return False, reason
    target = Path(os.path.abspath(str(out)))
    if target.exists() or target.is_symlink():
        return False, "report output already exists or is a link"
    target_resolved = target.resolve(strict=False)
    for root in forbidden:
        ok, reason = _existing_components(root)
        if not ok:
            return False, f"forbidden input: {reason}"
        root_path = Path(os.path.abspath(str(root)))
        root_resolved = root_path.resolve(strict=False)
        try:
            if (
                target_resolved == root_resolved
                or root_resolved in target_resolved.parents
                or target_resolved in root_resolved.parents
            ):
                return False, f"report output overlaps forbidden root: {root_resolved}"
        except ValueError:
            continue
    return True, None


def _write_report(out: Path, report: Mapping[str, Any]) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    if _is_reparse(out.parent):
        raise ValueError("report parent became a reparse point")
    with out.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


class _ProcessAudit:
    def __init__(self) -> None:
        self.events: list[str] = []

    def hook(self, event: str, args: tuple) -> None:
        if event in ("subprocess.Popen", "os.system", "os.startfile", "os.exec", "os.spawn"):
            self.events.append(event)


def _install_process_audit() -> _ProcessAudit:
    audit = _ProcessAudit()
    sys.addaudithook(audit.hook)
    return audit


def _static_check() -> dict:
    forbidden = (
        "app.", "d1_main", "d1_host_api", "d1_server", "d1_paths",
        "maintenance_host", "maintenance_lifecycle", "webview", "uvicorn",
        "verify_d2_w6_common", "verify_d2_w6_package", "tests.local",
    )
    loaded = sorted(
        name for name in sys.modules
        if any(name == item or name.startswith(item) for item in forbidden)
    )
    return {
        "ok": not loaded,
        "loaded": loaded,
    }


def _query(db: Path, sql: str):  # pragma: no cover - legacy
    import sqlite3

    connection = sqlite3.connect(str(db))
    try:
        return connection.execute(sql).fetchall()
    finally:
        connection.close()


def _run_obs(exe, root, data_dir, out, timeout=600):  # pragma: no cover - legacy
    from verify_d2_w6_common import base_env, run_window, sanitize_package_env

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


def _legacy_run(args, parser_error) -> int:  # pragma: no cover - legacy frozen path
    """Original frozen execution flow, reachable only with --mode frozen."""
    import shutil
    import sqlite3
    import tempfile

    from tests.local import w3_tls
    from tests.local.test_observation_migration import _build_0005
    from verify_d2_w6_common import (
        base_env,
        load_summary,
        make_reply_factory,
        run_window,
        sanitize_package_env,
    )
    from verify_d2_w6_package import (
        RESOURCE_CHECKS,
        _archive_entry_fingerprint,
        _package_path,
        _run_resources,
        _sha,
        _tree,
    )

    source_package = Path(args.package).resolve()
    root = Path(tempfile.mkdtemp(prefix="kgm-e14-package-")).resolve()
    report: dict = {"ok": False, "mode": "frozen", "checks": {}, "steps": {}, "root": str(root)}
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

        def compare(pkg_rel: str, source: Path) -> bool:
            bundled = _package_path(copied, pkg_rel)
            if not bundled.exists():
                return False
            if source.is_file():
                return bundled.is_file() and _sha(bundled) == _sha(source)
            return _tree(bundled) == _tree(source)

        checks["bundle_frontend_matches"] = compare("frontend", FRONTEND)
        checks["bundle_templates_match"] = compare("app/assets/word_templates", TEMPLATES)
        checks["bundle_migrations_match"] = compare("migrations_local", MIGRATIONS)
        checks["bundle_alembic_matches"] = compare("alembic-local.ini", ALEMBIC)
        internal = copied / "_internal"
        checks["entry_exe"] = (copied / exe_name).is_file()
        cache_dirs = [path for path in copied.rglob("__pycache__") if path.is_dir()]
        cache_files = [path for path in copied.rglob("*.pyc") if path.is_file()]
        checks["no_package_cache_files"] = not cache_dirs and not cache_files
        checks["observation_templates"] = all(
            (internal / "app/assets/word_templates" / name).is_file()
            for name in (
                "observation_public.docx", "observation_indoor.docx",
                "observation_outdoor.docx",
            )
        )
        checks["migration_0006"] = (
            internal / "migrations_local/versions/20261025_0006_local_game_observations.py"
        ).is_file()
        checks["pillow_plugins_present"] = len(list((internal / "PIL").glob("_*.cp314-win_amd64.pyd"))) >= 8
        checks["pillow_license_present"] = (copied / "licenses/Pillow-LICENSE.txt").is_file()
        checks["pillow_license_matches_source"] = (
            (copied / "licenses/Pillow-LICENSE.txt").is_file()
            and (REPO / "desktop/.venv-d1/Lib/site-packages/pillow-13.0.0.dist-info/licenses/LICENSE").is_file()
            and _sha(copied / "licenses/Pillow-LICENSE.txt")
            == _sha(REPO / "desktop/.venv-d1/Lib/site-packages/pillow-13.0.0.dist-info/licenses/LICENSE")
        )
        checks["package_info_present"] = (copied / "package-info.json").is_file()
        package_info_path = copied / "package-info.json"
        package_info = {}
        if package_info_path.is_file():
            try:
                package_info = json.loads(package_info_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                package_info = {}
        package_value = package_info.get("package")
        checks["package_info_portable"] = (
            package_value == copied.name and not Path(str(package_value)).is_absolute()
        )
        archive = _archive_static_report(copied, {"before": {}})
        report["archive"] = archive
        checks["archive_entry_matches_source"] = bool(archive["entry"].get("matches_source"))
        checks["archive_pyz_all_match"] = bool(archive.get("production_all_match"))
        checks["archive_required_modules_present"] = bool(
            archive.get("readable") and not archive.get("missing_required")
        )
        checks["archive_maintenance_modules_present"] = bool(
            archive.get("readable") and not archive.get("missing_maintenance")
        )
        checks["archive_backup_restore_modules_present"] = bool(
            archive.get("readable") and not archive.get("missing_backup_restore")
        )
        checks["archive_module_count_ok"] = bool(
            archive.get("readable") and archive.get("pyz_total_modules", 0) >= 40
        )
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
                report["ok"] = False
                report["real_ai"] = "not_run"
                _write_report(Path(args.out), report)
                print(json.dumps({"ok": False, "mode": "frozen", "report": str(args.out)}, ensure_ascii=False))
                return 2
            s1 = load_summary(out1)
            s2 = load_summary(out2)
            report["steps"]["resources_exit"] = [rc1, rc2]
            for key in RESOURCE_CHECKS:
                checks[f"res_{key}"] = bool(s1.get("checks", {}).get(key))
            checks["res_exit_zero"] = rc1 == 0 and rc2 == 0
            checks["res_no_duplicate_migration"] = (
                s1.get("migration_rows") == s2.get("migration_rows")
                and s1.get("schema_revision") == s2.get("schema_revision")
                and len(s1.get("migration_rows") or []) == 1
            )
        finally:
            server.stop()
        frozen_fp = dict(s1.get("module_fingerprints") or {})
        if source_fp.get("d1_main", {}).get("status") == "ok":
            frozen_fp["d1_main"] = s1.get("entry_fingerprint") or {"status": "unavailable"}
        mismatched = [
            name for name, source in source_fp.items()
            if (frozen_fp.get(name) or {}).get("status") == "ok"
            and frozen_fp[name].get("sha256") != source.get("sha256")
        ]
        unavailable = [
            name for name, source in source_fp.items()
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
            report["real_ai"] = "not_run"
            _write_report(Path(args.out), report)
            print(json.dumps({"ok": False, "mode": "frozen", "report": str(args.out)}, ensure_ascii=False))
            return 2
        empty = load_summary(empty_out)
        report["steps"]["obs_empty_exit"] = rc_empty
        checks["obs_empty_exit_zero"] = rc_empty == 0
        for key in EXPECTED_OBS_CHECKS:
            checks[f"empty_{key}"] = bool(empty.get("checks", {}).get(key))
        save_dir = root / "saved-obs"
        checks["obs_empty_saved_docx"] = any(save_dir.glob("*.docx"))

        old_data = root / "old-data"
        old_data.mkdir(parents=True, exist_ok=True)
        _build_0005(old_data / "kindergarten.db")
        old_out = root / "obs-old.json"
        rc_old = _run_obs(exe, root, old_data, old_out)
        old = load_summary(old_out)
        report["steps"]["obs_old_exit"] = rc_old
        checks["obs_old_exit_zero"] = rc_old == 0
        for key in EXPECTED_OBS_CHECKS:
            checks[f"old_{key}"] = bool(old.get("checks", {}).get(key))
        db = old_data / "kindergarten.db"
        version = _query(db, "SELECT version_num FROM local_alembic_version")
        checks["old_upgraded_0006"] = version and version[0][0] == DATABASE_REVISION
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
        checks["obs_old_reopen_exit_zero"] = rc_reopen == 0
        checks["obs_old_reopen_ok"] = bool(reopen.get("checks", {}).get("obs_ok"))
        report["ok"] = all(checks.values())
        report["frozen_runtime"] = "legacy_frozen_flow"
        report["real_ai"] = "not_run"
        report["signatures"] = {"checked": False, "status": "not_checked_static", "unsigned_internal_test": True}
        _write_report(Path(args.out), report)
        print(json.dumps({"ok": report["ok"], "mode": "frozen", "report": str(args.out)}, ensure_ascii=False))
        return 0 if report["ok"] else 1
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        report["errors"] = [{"type": type(exc).__name__, "message": str(exc)}]
        report["ok"] = False
        _write_report(Path(args.out), report)
        print(json.dumps({"ok": False, "mode": "frozen", "report": str(args.out)}, ensure_ascii=False))
        return 2


def _source_fingerprints(modules_file: Path) -> dict[str, dict]:  # pragma: no cover - legacy
    import importlib

    import d2_same_origin

    for name in (
        "d1_main", "d1_host_api", "d1_server", "d1_paths",
        "maintenance_host", "maintenance_lifecycle",
        "app.local.backup_snapshot", "app.local.backup_barrier",
        "app.local.backup_format", "app.local.backup_fs",
        "app.local.backup_validate", "app.local.backup_zip",
        "app.local.restore_service", "app.local.restore_recovery",
        "app.local.restore_group", "app.local.restore_fs",
        "app.local.restore_journal", "app.local.restore_types",
        "app.local.appearance_service",
    "app.local.weekly_plan_api",
    "app.local.weekly_plan_service",
    "app.local.weekly_plan_sources",
    "app.local.weekly_plan_content",
    "app.local.weekly_plan_tokens",
    "app.local.weekly_plan_operations",
    "app.local.weekly_plan_snapshot",
    "app.local.weekly_plan_export_service",
    "app.local.weekly_plan_export_api",
    "app.local.observation_service", "app.local.observation_export_service",
        "app.local.observation_export_api", "app.local.observation_assets",
        "app.local.observation_history_service", "app.local.observation_ai_service",
        "app.services.word_export_observation", "app.local.ai_executor",
        "app.local.ai_worker", "app.local.ai_transport", "app.local.ai_task_service",
        "app.local.ai_config_service", "app.local.ai_adoption",
        "app.local.ai_candidates", "app.local.ai_provenance", "app.local.ai_inputs",
        "app.local.export_service", "app.local.daily_plan_service",
        "app.local.prompt_bundles", "app.local.credentials",
    ):
        try:
            importlib.import_module(name)
        except Exception:  # noqa: BLE001
            pass
    names = d2_same_origin.loaded_production_modules()
    names = sorted(set(names) | {"maintenance_host", "maintenance_lifecycle"})
    modules_file.write_text(
        json.dumps([name for name in names if name != "d1_main"], ensure_ascii=False),
        encoding="utf-8",
    )
    return {name: d2_same_origin.fingerprint_imported_module(name) for name in names}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the Windows 11 portable candidate")
    parser.add_argument("--package", default=None)
    parser.add_argument("--mode", choices=("static", "frozen"), default=None)
    parser.add_argument("--static-only", action="store_true")
    parser.add_argument("--source-freeze", default=None)
    parser.add_argument("--frontend-build", "--frontend", dest="frontend_build", default=None)
    parser.add_argument("--out", default=None)
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args(argv)
    if args.mode is None:
        if args.static_only:
            mode = "static"
        else:
            print("explicit --mode static (or --static-only) is required", file=sys.stderr)
            return 2
    else:
        mode = args.mode
    if args.static_only and mode == "frozen":
        print("--static-only conflicts with --mode frozen", file=sys.stderr)
        return 2
    if args.out is None:
        print("--out is required", file=sys.stderr)
        return 2
    out = Path(args.out)
    forbidden = [REPO]
    if args.package:
        forbidden.append(Path(args.package))
    if args.frontend_build:
        forbidden.append(Path(args.frontend_build))
    if args.source_freeze:
        forbidden.append(Path(args.source_freeze))
    ok, reason = _report_path_ok(out, forbidden)
    if not ok:
        print(f"invalid --out: {reason}", file=sys.stderr)
        return 2
    if args.package is None:
        print("--package is required", file=sys.stderr)
        return 2
    if mode == "frozen":
        return _legacy_run(args, parser)
    if not args.source_freeze:
        print("--source-freeze is required in static mode", file=sys.stderr)
        return 2
    if not args.frontend_build:
        print("--frontend-build (or --frontend) is required in static mode", file=sys.stderr)
        return 2

    package_root, path_error = _plain_input(Path(args.package), "package")
    if path_error:
        print(path_error, file=sys.stderr)
        return 2
    frontend_build, path_error = _plain_input(Path(args.frontend_build), "frontend-build")
    if path_error:
        print(path_error, file=sys.stderr)
        return 2
    freeze_path, path_error = _plain_input(Path(args.source_freeze), "source-freeze")
    if path_error:
        print(path_error, file=sys.stderr)
        return 2
    assert package_root is not None and frontend_build is not None and freeze_path is not None
    started = _now()
    report: dict = {
        "schema_version": 1,
        "mode": "static",
        "ok": False,
        "tool": {
            "name": "verify_e14_package.py",
            "sha256": _sha256(Path(__file__)),
            "python": sys.version,
        },
        "package": {
            "path": str(package_root),
            "name": package_root.name,
            "tree_sha256": None,
            "file_count": 0,
            "bytes": 0,
        },
        "source_freeze": {},
        "checks": {},
        "required_checks": list(REQUIRED_STATIC_CHECKS),
        "missing_checks": [],
        "non_bool_checks": [],
        "unknown_checks": [],
        "failed_checks": [],
        "errors": [],
        "limitations": [],
        "frozen_runtime": "not_run_static_only",
        "real_ai": "not_run",
        "signatures": {
            "checked": False,
            "status": "not_checked_static",
            "unsigned_internal_test": True,
        },
        "started_at": started,
        "finished_at": None,
    }
    checks: dict[str, Any] = report["checks"]
    unknowns: dict[str, str] = {}
    exit_code = 2
    process_audit = _install_process_audit()
    try:
        checks["static_no_execution"] = not process_audit.events
        static_state = _static_check()
        checks["static_no_production_imports"] = static_state["ok"]
        if static_state["loaded"]:
            report["privacy"] = {"unexpected_loaded_modules": static_state["loaded"]}
        checks["package_root_present"] = _plain_dir(package_root)
        exe = package_root / f"{package_root.name}.exe"
        checks["package_exe_present"] = exe.is_file()
        checks["entry_exe"] = exe.is_file()
        if not checks["package_root_present"]:
            raise FileNotFoundError(f"package root missing: {package_root}")
        if _is_reparse(package_root) or _is_reparse(package_root / f"{package_root.name}.exe"):
            raise ValueError("package root or EXE is a reparse point")
        _iter_plain_files(package_root)
        package_info_path = package_root / "package-info.json"
        package_info_present = package_info_path.is_file()
        checks["package_info_present"] = package_info_present
        package_info: dict = {}
        if package_info_present:
            try:
                package_info = _read_json(package_info_path)
            except Exception as exc:  # noqa: BLE001
                report["errors"].append(f"package-info: {type(exc).__name__}: {exc}")
                package_info = {}
        if not isinstance(package_info, dict):
            package_info = {}
        info_checks = _package_info_checks(package_info, PRODUCT)
        checks["package_info_portable"] = bool(info_checks["portable"])
        checks["package_info_metadata_exact"] = bool(info_checks["metadata_exact"])
        checks["package_info_source_commit"] = bool(info_checks["source_commit"])
        checks["package_info_unsigned_internal_test"] = bool(info_checks["unsigned_internal_test"])
        checks["package_info_frontend_digest"] = bool(info_checks["frontend_digest"])
        if info_checks["errors"]:
            report["errors"].extend(info_checks["errors"])

        identity = _identity_checks(package_root, package_info)
        checks["build_identity_present"] = bool(identity["present"])
        checks["build_identity_valid"] = bool(identity["valid"])
        checks["build_identity_uuid"] = bool(identity["uuid"])
        checks["build_identity_not_source_id"] = bool(identity["not_source_id"])
        checks["build_identity_version"] = bool(identity["version"])
        checks["build_identity_revision"] = bool(identity["revision"])
        checks["build_identity_matches_package_info"] = bool(identity["matches_package_info"])
        report["build_identity"] = {key: value for key, value in identity.items() if key != "data"}

        freeze = _load_freeze(freeze_path, package_info, "desktop/verify_e14_package.py")
        report["source_freeze"] = {
            key: value for key, value in freeze.items()
            if key not in ("before", "after")
        }
        checks["source_freeze_present"] = bool(freeze["present"])
        checks["source_freeze_schema"] = bool(freeze["schema_ok"])
        checks["source_freeze_stable"] = bool(freeze["stable"])
        checks["source_freeze_digest_matches"] = bool(
            freeze.get("digest")
            and package_info.get("source_freeze_digest") == freeze.get("digest")
        )
        checks["source_freeze_current_matches"] = bool(
            freeze.get("present") and freeze.get("schema_ok")
            and not freeze.get("current_mismatches")
        )
        checks["source_freeze_required_paths"] = bool(
            freeze.get("present") and freeze.get("schema_ok")
            and not freeze.get("required_missing")
        )
        checks["source_freeze_before_build"] = bool(freeze.get("before_build"))
        checks["verifier_matches_freeze"] = bool(freeze.get("self_matches"))
        if freeze.get("errors"):
            report["errors"].extend(freeze["errors"])

        tree_digest, tree_count, tree_entries = _tree_digest(package_root)
        report["package"]["tree_sha256"] = tree_digest
        report["package"]["file_count"] = tree_count
        report["package"]["bytes"] = sum(int(item["size"]) for item in tree_entries)
        checks["package_tree_digest_matches_freeze"] = bool(
            freeze.get("package_tree_digest")
            and freeze.get("package_tree_digest") == tree_digest
        )

        frontend = _frontend_checks(package_root, frontend_build, package_info)
        checks["bundle_frontend_matches"] = bool(frontend["matches"])
        checks["frontend_digest_matches"] = bool(frontend["digest_matches"])
        report["frontend"] = {
            key: value for key, value in frontend.items() if key != "errors"
        }
        if frontend["errors"]:
            report["errors"].extend(frontend["errors"])

        resources = _resource_checks(package_root)
        checks["bundle_templates_match"] = bool(resources["templates_match"])
        checks["bundle_migrations_match"] = bool(resources["migrations_match"])
        checks["bundle_alembic_matches"] = bool(resources["alembic_match"])
        checks["observation_templates"] = bool(resources["observation_templates"])
        checks["migration_0006"] = bool(resources["migration_0006"])
        plugins = resources["pillow_plugins"]
        checks["pillow_plugins_present"] = (
            len(plugins) >= 8 and all(name in plugins for name in REQUIRED_PILLOW_PLUGINS)
        )
        checks["pillow_license_present"] = bool(resources["license_present"])
        checks["pillow_license_matches_source"] = bool(resources["license_matches"])
        checks["no_package_cache_files"] = not resources["caches"]
        report["resources"] = {
            "templates_match": resources["templates_match"],
            "migrations_match": resources["migrations_match"],
            "alembic_match": resources["alembic_match"],
            "pillow_plugins": plugins,
            "cache_files": resources["caches"],
        }

        archive = _archive_static_report(package_root, freeze)
        report["archive"] = archive
        checks["archive_entry_matches_source"] = bool(archive.get("entry", {}).get("matches_source"))
        checks["archive_entry_matches_freeze"] = bool(archive.get("entry", {}).get("matches_freeze"))
        checks["archive_pyz_all_match"] = bool(archive.get("production_all_match"))
        checks["archive_pyz_matches_freeze"] = bool(archive.get("production_match_freeze"))
        checks["archive_required_modules_present"] = bool(
            archive.get("readable") and not archive.get("missing_required")
        )
        checks["archive_maintenance_modules_present"] = bool(
            archive.get("readable") and not archive.get("missing_maintenance")
        )
        checks["archive_backup_restore_modules_present"] = bool(
            archive.get("readable") and not archive.get("missing_backup_restore")
        )
        checks["archive_module_count_ok"] = bool(
            archive.get("readable")
            and int(archive.get("pyz_total_modules") or 0) >= max(40, len(ARCHIVE_REQUIRED_MODULES))
        )
        checks["archive_verification_support_separated"] = bool(archive.get("readable"))
        checks["archive_no_unexpected_production_modules"] = bool(
            archive.get("readable") and not archive.get("unexpected_production")
        )
        if archive.get("error"):
            report["errors"].append(f"archive: {archive['error']}")

        privacy = _privacy_checks(package_root, archive)
        report["privacy"] = {
            "private_paths": privacy["private_paths"],
            "private_keys": privacy["private_keys"],
            "absolute_metadata": privacy["absolute_metadata"],
            "absolute_text": privacy["absolute_text"],
            "absolute_code": privacy["absolute_code"],
            "allowed_build_references": privacy["allowed_build_references"],
            "known_sbom": privacy["known_sbom"],
            "text_scan_complete": privacy["text_scan_complete"],
        }
        checks["privacy_no_private_paths"] = bool(
            not privacy.get("errors") and not privacy["private_paths"]
        )
        checks["privacy_no_private_keys"] = bool(
            not privacy.get("errors") and not privacy["private_keys"]
        )
        checks["no_absolute_paths_in_metadata"] = bool(
            not privacy.get("errors") and not privacy["absolute_metadata"]
        )
        checks["privacy_no_absolute_paths_in_code"] = bool(
            not privacy.get("errors") and not privacy["absolute_code"]
        )
        checks["privacy_no_absolute_paths_in_text"] = bool(
            not privacy.get("errors")
            and privacy["text_scan_complete"]
            and not privacy["absolute_text"]
        )
        checks["signature_not_claimed"] = True
        if privacy.get("errors"):
            report["errors"].extend(privacy["errors"])

        checks["static_no_execution"] = not process_audit.events
        if process_audit.events:
            report["privacy"] = {
                **(report.get("privacy") or {}),
                "process_events": list(process_audit.events),
            }
        status = _required_status(checks, REQUIRED_STATIC_CHECKS, unknowns)
        report["missing_checks"] = status["missing"]
        report["non_bool_checks"] = status["non_bool"]
        report["unknown_checks"] = status["unknown"]
        report["failed_checks"] = status["failed"]
        report["ok"] = bool(status["ok"])
        report["limitations"] = [
            "frontend is verified against the build input, not rebuilt from source in static mode",
            "freeze timestamp proves ordering only as reported evidence, not a trusted timestamp",
            "CArchive/PYZ is a local trusted build artifact; marshal is not a hardened parser",
            "verification-support modules may be present in PYZ and are reported separately",
            "Authenticode is not checked in static mode; unsigned internal test only",
        ]
        exit_code = 0 if report["ok"] else 1
    except Exception as exc:  # noqa: BLE001
        report["errors"].append({"type": type(exc).__name__, "message": str(exc)})
        report["ok"] = False
        checks["static_no_execution"] = not process_audit.events
        exit_code = 2
    report["finished_at"] = _now()
    try:
        _write_report(out, report)
    except Exception as exc:  # noqa: BLE001
        print(f"cannot write report: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"ok": report["ok"], "mode": "static", "report": str(out)}, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
