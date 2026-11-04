"""Verify a Windows 11 portable ZIP without extracting or executing it.

The inspector reads the central directory first, validates every member name
and bound, and only then opens bounded member streams for hashing and small
text inspection.  It never calls ``extractall`` and never writes archive
contents to disk.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import unicodedata
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

PRODUCT = "KGNext-E14"
README_NAME = "README-KGNext-E14-win11-r01.txt"
ARCHIVE_NAME = "KGNext-E14-win11-r01.zip"
MANIFEST = "package-files.json"
SUMS = "SHA256SUMS.txt"
DATABASE_REVISION = "20261102_0008_local_weekly_ai"
APP_VERSION = "0.1.0"
MAX_ENTRIES = 20000
MAX_FILE_BYTES = 1024 * 1024 * 1024
MAX_TOTAL_BYTES = 3 * 1024 * 1024 * 1024
MAX_RATIO = 200
MAX_PATH_CHARS = 512
MAX_PATH_DEPTH = 24
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_PUBLIC_CERT_BYTES = 4 * 1024 * 1024
MAX_README_BYTES = 1024 * 1024
MAX_SUMS_BYTES = 16 * 1024 * 1024
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
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SUMS_RE = re.compile(r"^([0-9a-f]{64})  (.+)$")
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
RESERVED_NAMES = {
    "con", "prn", "aux", "nul",
    *{f"com{i}" for i in range(1, 10)},
    *{f"lpt{i}" for i in range(1, 10)},
}
REQUIRED_ARCHIVE_CHECKS = (
    "static_no_execution",
    "archive_not_empty",
    "archive_bytes_bounds",
    "zip_entry_limit_ok",
    "zip_no_absolute_paths",
    "zip_no_parent_segments",
    "zip_no_drive_paths",
    "zip_no_backslash",
    "zip_no_controls",
    "zip_no_empty_parts",
    "zip_no_trailing_dot_space",
    "zip_no_ads",
    "zip_no_reserved_names",
    "zip_no_directory_entries",
    "zip_no_duplicate_names",
    "zip_no_casefold_collisions",
    "zip_no_normalized_collisions",
    "zip_no_symlinks",
    "zip_no_special_entries",
    "zip_no_encrypted_members",
    "zip_compression_allowed",
    "zip_single_file_limit_ok",
    "zip_total_size_limit_ok",
    "zip_ratio_limit_ok",
    "zip_streamed_without_extract",
    "only_allowed_top_level",
    "product_dir_only",
    "product_dir_present",
    "readme_present",
    "manifest_present",
    "checksums_present",
    "manifest_sha256_format",
    "manifest_schema_exact",
    "manifest_no_duplicate_keys",
    "manifest_package_relative",
    "manifest_paths_relative",
    "manifest_no_duplicate_paths",
    "manifest_files_nonempty",
    "product_file_set_exact",
    "product_sizes_and_hashes_exact",
    "sqlalchemy_cyextension_absent",
    "checksums_schema_exact",
    "checksums_no_duplicates",
    "checksums_cover_product_and_outer",
    "package_info_present",
    "package_info_portable",
    "package_info_metadata_exact",
    "package_info_matches_manifest",
    "source_freeze_present",
    "source_freeze_schema",
    "source_freeze_stable",
    "source_freeze_matches_manifest",
    "package_dir_matches_zip",
    "no_private_audit_entries",
    "no_private_material",
    "public_ca_and_licenses_preserved",
    "readme_no_private_paths",
    "no_absolute_paths_in_text",
    "privacy_text_scan_complete",
    "archive_sha256_recorded",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_bool(value: Any) -> bool:
    return type(value) is bool


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_reparse(path: Path) -> bool:
    try:
        stat = path.lstat()
    except OSError:
        return False
    return path.is_symlink() or bool(getattr(stat, "st_file_attributes", 0) & 0x400)


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


def _read_json_bytes(raw: bytes) -> Any:
    if len(raw) > MAX_JSON_BYTES:
        raise ValueError("JSON member too large")
    return _json_loads(raw)


def _name_codes(name: Any) -> set[str]:
    codes: set[str] = set()
    if not isinstance(name, str) or not name:
        return {"invalid_name"}
    if len(name) > MAX_PATH_CHARS:
        codes.add("too_long")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in name):
        codes.add("control_char")
    if "\\" in name:
        codes.add("backslash")
    if name.startswith("//"):
        codes.add("unc_path")
    elif name.startswith("/"):
        codes.add("absolute_path")
    if len(name) >= 2 and name[1] == ":":
        codes.add("drive_path")
    if name.endswith("/"):
        codes.add("directory_entry")
    if unicodedata.normalize("NFC", name) != name:
        codes.add("unicode_not_nfc")
    parts = name.rstrip("/").split("/")
    if len(parts) > MAX_PATH_DEPTH:
        codes.add("too_deep")
    for part in parts:
        if part in ("", ".", ".."):
            codes.add("empty_or_dot_component" if part != ".." else "parent_segment")
            continue
        if part.endswith(" ") or part.endswith("."):
            codes.add("trailing_dot_space")
        if ":" in part:
            codes.add("ads")
        stem = part.split(".", 1)[0].casefold()
        if stem in RESERVED_NAMES:
            codes.add("reserved_name")
    return codes


def _sqlalchemy_compiled_members(relative_names: Iterable[str]) -> list[str]:
    """Return SQLAlchemy compiled/cyextension members; the list must be empty."""
    prefix = "_internal/sqlalchemy/"
    return sorted(
        name
        for name in relative_names
        if name.startswith(prefix)
        and (
            "/cyextension/" in name
            or name.lower().endswith((".pyd", ".dll"))
        )
    )


def validate_manifest_path(raw: Any) -> str | None:
    """Return the exact safe relative path, or None; never normalizes unsafe input."""
    if _name_codes(raw):
        return None
    return raw


def _entry_name(entry: Any) -> Any:
    if isinstance(entry, Mapping):
        return entry.get("filename", entry.get("name"))
    original = getattr(entry, "orig_filename", None)
    if isinstance(original, str):
        return original
    return getattr(entry, "filename", getattr(entry, "name", None))


def _entry_value(entry: Any, key: str, default: Any = 0) -> Any:
    if isinstance(entry, Mapping):
        return entry.get(key, default)
    return getattr(entry, key, default)


def validate_member_names(entries: Iterable[Any]) -> list[str]:
    """Return sorted violation codes; an empty list means every member is safe."""
    codes: set[str] = set()
    names: list[str] = []
    total = 0
    for entry in entries:
        name = _entry_name(entry)
        names.append(name if isinstance(name, str) else "")
        current = _name_codes(name)
        codes.update(current)
        external = _entry_value(entry, "external_attr", 0)
        if type(external) is not int:
            codes.add("invalid_external_attr")
            external = 0
        unix_mode = (external >> 16) & 0o170000
        if unix_mode == 0o120000:
            codes.add("symlink")
        elif unix_mode == 0o040000:
            codes.add("directory_entry")
        elif unix_mode not in (0, 0o100000):
            codes.add("special_entry")
        if external & 0x400:
            codes.add("reparse_point")
        flags = _entry_value(entry, "flag_bits", 0)
        if type(flags) is int and flags & 0x1:
            codes.add("encrypted")
        compression = _entry_value(entry, "compress_type", zipfile.ZIP_STORED)
        if compression not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            codes.add("unsupported_compression")
        size = _entry_value(entry, "file_size", 0)
        compressed = _entry_value(entry, "compress_size", 0)
        if type(size) is int and type(compressed) is int:
            total += max(0, size)
            if size > MAX_FILE_BYTES:
                codes.add("member_too_large")
            if compressed == 0 and size > 0:
                codes.add("ratio_exceeded")
            elif compressed > 0 and size > compressed * MAX_RATIO:
                codes.add("ratio_exceeded")
    if len(names) > MAX_ENTRIES:
        codes.add("too_many_entries")
    if total > MAX_TOTAL_BYTES:
        codes.add("total_too_large")
    folded: dict[str, str] = {}
    normalized: dict[str, str] = {}
    exact: set[str] = set()
    for name in names:
        if name in exact:
            codes.add("duplicate_exact")
        exact.add(name)
        key = name.casefold()
        if key in folded:
            codes.add("duplicate_casefold")
        folded[key] = name
        nfc = unicodedata.normalize("NFC", name)
        if nfc in normalized:
            codes.add("duplicate_nfc")
        normalized[nfc] = name
    return sorted(codes)


def required_status(
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


def _freeze_files_map(files: Any) -> tuple[dict[str, dict], list[str]]:
    errors: list[str] = []
    result: dict[str, dict] = {}
    if not isinstance(files, list) or not files:
        return {}, ["freeze files missing or empty"]
    for item in files:
        if not isinstance(item, dict):
            errors.append("freeze entry not an object")
            continue
        relative = validate_manifest_path(item.get("path"))
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
            errors.append(f"freeze duplicate: {relative}")
        result[relative] = item
    return result, errors


def _freeze_digest(files: Iterable[Mapping[str, Any]]) -> str:
    payload = [
        {"path": str(item["path"]), "sha256": str(item["sha256"])}
        for item in sorted(files, key=lambda item: str(item["path"]))
    ]
    return _sha256_bytes(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )


def _load_freeze_basic(path: Path) -> dict:
    result = {
        "present": False,
        "sha256": None,
        "digest": None,
        "commit": None,
        "schema": False,
        "stable": False,
        "errors": [],
    }
    if not path.is_file():
        result["errors"].append("source freeze missing")
        return result
    result["present"] = True
    result["sha256"] = _sha256_file(path)
    try:
        raw = path.read_bytes()
        if len(raw) > MAX_JSON_BYTES:
            raise ValueError("freeze too large")
        report = _json_loads(raw)
    except Exception as exc:  # noqa: BLE001
        result["errors"].append(f"freeze JSON: {type(exc).__name__}: {exc}")
        return result
    if not isinstance(report, dict):
        result["errors"].append("freeze root not an object")
        return result
    before = report.get("before")
    after = report.get("after")
    if not isinstance(before, dict) or not isinstance(after, dict):
        result["errors"].append("freeze before/after missing")
        return result
    before_files, before_errors = _freeze_files_map(before.get("files"))
    after_files, after_errors = _freeze_files_map(after.get("files"))
    result["errors"].extend(before_errors + after_errors)
    before_digest = _freeze_digest(before_files.values()) if before_files else None
    after_digest = _freeze_digest(after_files.values()) if after_files else None
    result["digest"] = before_digest
    result["commit"] = report.get("commit") or before.get("commit")
    schema = (
        not result["errors"]
        and bool(before_files)
        and bool(after_files)
        and before_digest == after_digest
        and before.get("digest") == before_digest
        and after.get("digest") == after_digest
        and before.get("file_count") == len(before_files)
        and after.get("file_count") == len(after_files)
        and isinstance(result["commit"], str)
        and bool(COMMIT_RE.match(result["commit"]))
        and isinstance(before.get("generated_at"), str)
        and isinstance(after.get("generated_at"), str)
    )
    result["schema"] = bool(schema)
    declared = report.get("changes")
    result["stable"] = bool(
        schema
        and report.get("stable") is True
        and isinstance(declared, dict)
        and declared.get("stable") is True
        and declared.get("changed") == []
        and declared.get("added") == []
        and declared.get("removed") == []
    )
    return result


def _read_member_bytes(zf: zipfile.ZipFile, name: str, limit: int) -> bytes:
    info = zf.getinfo(name)
    if info.file_size > limit:
        raise ValueError(f"member too large: {name}")
    with zf.open(name, "r") as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"member exceeds limit: {name}")
    return data


def _hash_member(zf: zipfile.ZipFile, name: str) -> tuple[int, str]:
    info = zf.getinfo(name)
    if info.file_size > MAX_FILE_BYTES:
        raise ValueError(f"member too large: {name}")
    digest = hashlib.sha256()
    total = 0
    with zf.open(name, "r") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            total += len(chunk)
            if total > MAX_FILE_BYTES or total > info.file_size:
                raise ValueError(f"member exceeds declared or allowed size: {name}")
            digest.update(chunk)
    if total != info.file_size:
        raise ValueError(f"member size mismatch: {name}")
    return total, digest.hexdigest()


def _validate_manifest(data: Any, product: str) -> dict:
    result = {
        "schema": False,
        "package_relative": False,
        "paths_relative": False,
        "no_duplicates": False,
        "files_nonempty": False,
        "sha_format": False,
        "files": {},
        "errors": [],
    }
    if not isinstance(data, dict):
        result["errors"].append("manifest not an object")
        return result
    expected_keys = {
        "schema_version", "package", "build_id", "database_revision",
        "source_freeze_digest", "generated_at", "files",
    }
    if set(data) != expected_keys:
        result["errors"].append("manifest top-level keys are not exact")
    if data.get("schema_version") != 1 or type(data.get("schema_version")) is not int:
        result["errors"].append("manifest schema_version invalid")
    package = data.get("package")
    result["package_relative"] = (
        isinstance(package, str) and package == product and not Path(package).is_absolute()
    )
    try:
        uuid.UUID(str(data.get("build_id")))
        build_id_ok = True
    except (ValueError, TypeError, AttributeError):
        build_id_ok = False
    revision_ok = data.get("database_revision") == DATABASE_REVISION
    freeze_digest = data.get("source_freeze_digest")
    digest_ok = isinstance(freeze_digest, str) and bool(SHA_RE.match(freeze_digest))
    generated_ok = isinstance(data.get("generated_at"), str) and bool(data.get("generated_at"))
    files = data.get("files")
    if not isinstance(files, list) or not files:
        result["errors"].append("manifest files missing or empty")
        result["schema"] = False
        return result
    mapping: dict[str, dict] = {}
    exact: set[str] = set()
    folded: dict[str, str] = {}
    normalized: dict[str, str] = {}
    paths_ok = True
    sha_ok = True
    for item in files:
        if not isinstance(item, dict) or set(item) != {"path", "size", "sha256"}:
            result["errors"].append("manifest entry keys are not exact")
            paths_ok = False
            continue
        raw_path = item.get("path")
        path = validate_manifest_path(raw_path)
        if path is None:
            paths_ok = False
            result["errors"].append(f"manifest path unsafe: {raw_path!r}")
            continue
        size = item.get("size")
        digest = item.get("sha256")
        if type(size) is not int or size < 0:
            result["errors"].append(f"manifest size invalid: {path}")
            paths_ok = False
        if not isinstance(digest, str) or not SHA_RE.match(digest):
            sha_ok = False
            result["errors"].append(f"manifest sha invalid: {path}")
        if path in exact:
            result["no_duplicates"] = False
            result["errors"].append(f"manifest duplicate path: {path}")
        exact.add(path)
        folded_key = path.casefold()
        if folded_key in folded:
            result["no_duplicates"] = False
            result["errors"].append(f"manifest casefold collision: {path}")
        folded[folded_key] = path
        nfc = unicodedata.normalize("NFC", path)
        if nfc in normalized:
            result["no_duplicates"] = False
            result["errors"].append(f"manifest NFC collision: {path}")
        normalized[nfc] = path
        mapping[path] = item
    sorted_paths = [item.get("path") for item in files if isinstance(item, dict)]
    result["no_duplicates"] = bool(
        result["no_duplicates"] or (len(exact) == len(files) and len(folded) == len(files))
    )
    result["paths_relative"] = bool(paths_ok)
    result["sha_format"] = bool(sha_ok)
    result["files_nonempty"] = bool(mapping)
    result["files"] = mapping
    result["schema"] = bool(
        not result["errors"]
        and type(data.get("schema_version")) is int
        and data.get("schema_version") == 1
        and build_id_ok and revision_ok and digest_ok and generated_ok
        and result["package_relative"] and result["paths_relative"]
        and result["no_duplicates"] and result["files_nonempty"] and result["sha_format"]
        and sorted_paths == sorted(sorted_paths)
    )
    return result


def _parse_sums(raw: bytes, product: str, manifest_files: Mapping[str, dict], readme: str) -> dict:
    result = {
        "schema": False,
        "no_duplicates": False,
        "covers": False,
        "map": {},
        "errors": [],
    }
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        result["errors"].append("SHA256SUMS is not UTF-8")
        return result
    lines = text.splitlines()
    if not lines:
        result["errors"].append("SHA256SUMS is empty")
        return result
    mapping: dict[str, str] = {}
    valid = True
    for line in lines:
        if not line:
            valid = False
            result["errors"].append("blank SHA256SUMS line")
            continue
        match = SUMS_RE.match(line)
        if match is None:
            valid = False
            result["errors"].append("invalid SHA256SUMS line")
            continue
        digest, path = match.group(1), match.group(2)
        if validate_manifest_path(path) is None:
            valid = False
            result["errors"].append(f"unsafe SHA256SUMS path: {path!r}")
            continue
        if path in mapping:
            result["no_duplicates"] = False
            result["errors"].append(f"duplicate SHA256SUMS path: {path}")
        mapping[path] = digest
    ordered = [line.split("  ", 1)[1] for line in lines if "  " in line]
    expected = {f"{product}/{path}" for path in manifest_files}
    expected.add(readme)
    expected.add(MANIFEST)
    result["map"] = mapping
    result["no_duplicates"] = bool(len(mapping) == len(lines) and len(mapping) == len(set(mapping)))
    result["schema"] = bool(valid and ordered == sorted(ordered))
    result["covers"] = set(mapping) == expected
    return result


def _zip_member_info(zf: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    return list(zf.infolist())


def _zip_top_level_checks(infos: Iterable[zipfile.ZipInfo], product: str, readme_name: str) -> dict:
    names = [info.filename for info in infos]
    return {
        "not_empty": bool(names),
        "only_allowed": all(
            name.startswith(product + "/")
            or name in (readme_name, MANIFEST, SUMS)
            for name in names
        ),
        "product_only": all(
            name.startswith(product + "/")
            for name in names
            if name not in (readme_name, MANIFEST, SUMS)
        ),
        "product_present": any(name.startswith(product + "/") for name in names),
        "readme": readme_name in names,
        "manifest": MANIFEST in names,
        "sums": SUMS in names,
    }


def _check_codes(violations: Iterable[str]) -> dict[str, bool]:
    codes = set(violations)
    return {
        "zip_no_absolute_paths": not ({"absolute_path", "drive_path", "unc_path"} & codes),
        "zip_no_parent_segments": "parent_segment" not in codes,
        "zip_no_drive_paths": "drive_path" not in codes,
        "zip_no_backslash": "backslash" not in codes,
        "zip_no_controls": "control_char" not in codes,
        "zip_no_empty_parts": not ({"empty_or_dot_component", "invalid_name"} & codes),
        "zip_no_trailing_dot_space": "trailing_dot_space" not in codes,
        "zip_no_ads": "ads" not in codes,
        "zip_no_reserved_names": "reserved_name" not in codes,
        "zip_no_directory_entries": "directory_entry" not in codes,
        "zip_no_duplicate_names": "duplicate_exact" not in codes,
        "zip_no_casefold_collisions": "duplicate_casefold" not in codes,
        "zip_no_normalized_collisions": not ({"duplicate_nfc", "unicode_not_nfc"} & codes),
        "zip_no_symlinks": not ({"symlink", "reparse_point"} & codes),
        "zip_no_special_entries": "special_entry" not in codes,
        "zip_no_encrypted_members": "encrypted" not in codes,
        "zip_compression_allowed": "unsupported_compression" not in codes,
        "zip_entry_limit_ok": "too_many_entries" not in codes,
        "zip_single_file_limit_ok": "member_too_large" not in codes,
        "zip_total_size_limit_ok": "total_too_large" not in codes,
        "zip_ratio_limit_ok": "ratio_exceeded" not in codes,
    }


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


def _private_name_violations(names: Iterable[str]) -> list[dict]:
    hits: list[dict] = []
    for name in names:
        lower = name.casefold()
        for token in FORBIDDEN_PATH_TOKENS:
            if token in lower:
                hits.append({"path": name, "reason": token})
                break
        if lower.endswith(IMAGE_SUFFIXES) and f"/frontend/" not in lower and not lower.startswith("frontend/"):
            hits.append({"path": name, "reason": "image-outside-frontend"})
    return hits


def scan_text_private_paths(
    text: str,
    *,
    source_path: str = "",
    metadata: bool = False,
    known_sbom: Mapping[str, Any] | None = None,
) -> dict:
    """Discriminate real private path tokens from regex/escape grammar."""
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


def _known_sbom_info(actual_bytes: bytes | None) -> dict:
    source = (
        Path(__file__).resolve().parent.parent
        / "desktop"
        / ".venv-d1"
        / "Lib"
        / "site-packages"
        / "cryptography-50.0.1.dist-info"
        / "sboms"
        / "cryptography-rust.cyclonedx.json"
    )
    actual_sha = _sha256_bytes(actual_bytes) if actual_bytes is not None else None
    source_sha = _sha256_file(source) if source.is_file() else None
    return {
        "path": KNOWN_SBOM_REL,
        "actual_sha256": actual_sha,
        "source_sha256": source_sha,
        "matches_source": bool(actual_sha and source_sha and actual_sha == source_sha),
    }


def _text_abs_paths(
    zf: zipfile.ZipFile, names: Iterable[str]
) -> tuple[list[dict], list[dict], list[dict], dict, list[dict], bool]:
    hits: list[dict] = []
    private_hits: list[dict] = []
    allowed_refs: list[dict] = []
    readme_violations: list[dict] = []
    complete = True
    names = list(names)
    known_member = f"{PRODUCT}/{KNOWN_SBOM_REL}"
    known_bytes = None
    if known_member in names:
        try:
            known_bytes = _read_member_bytes(zf, known_member, 16 * 1024 * 1024)
        except Exception:  # noqa: BLE001
            complete = False
    known_sbom = _known_sbom_info(known_bytes)
    metadata_names = {
        MANIFEST,
        SUMS,
        README_NAME,
        f"{PRODUCT}/package-info.json",
        f"{PRODUCT}/_internal/build_identity.json",
    }
    for name in names:
        suffix = Path(name).suffix.lower()
        if suffix not in TEXT_SUFFIXES:
            continue
        info = zf.getinfo(name)
        if info.file_size > 16 * 1024 * 1024:
            complete = False
            continue
        try:
            data = _read_member_bytes(zf, name, 16 * 1024 * 1024)
            text = data.decode("utf-8", errors="ignore")
        except Exception:  # noqa: BLE001
            complete = False
            continue
        if "PRIVATE KEY" in text:
            private_hits.append({"path": name, "reason": "private-key-marker"})
        relative = name[len(PRODUCT) + 1:] if name.startswith(PRODUCT + "/") else name
        scan = scan_text_private_paths(
            text,
            source_path=relative,
            metadata=name in metadata_names,
            known_sbom=known_sbom if relative == KNOWN_SBOM_REL else None,
        )
        for violation in scan["violations"]:
            hits.append({"path": name, **violation})
            if name == README_NAME:
                readme_violations.append({"path": name, **violation})
        allowed_refs.extend(scan["allowed_build_references"])
    return hits, private_hits, allowed_refs, known_sbom, readme_violations, complete


def _package_dir_entries(package: Path) -> list[dict]:
    if _is_reparse(package):
        raise ValueError("package root is a reparse point")
    entries: list[dict] = []
    for path in sorted(package.rglob("*")):
        if _is_reparse(path):
            raise ValueError(f"package tree reparse point: {path}")
        if path.is_file():
            entries.append(
                {
                    "path": path.relative_to(package).as_posix(),
                    "size": path.stat().st_size,
                    "sha256": _sha256_file(path),
                }
            )
    return entries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify an E14 portable ZIP")
    parser.add_argument("--archive", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--source-freeze", required=True)
    parser.add_argument("--package", default=None)
    parser.add_argument("--product", default=PRODUCT)
    parser.add_argument("--readme", default=README_NAME)
    args = parser.parse_args(argv)
    archive, path_error = _plain_input(Path(args.archive), "archive")
    if path_error:
        print(path_error, file=sys.stderr)
        return 2
    out = Path(args.out)
    package_dir = None
    if args.package:
        package_dir, path_error = _plain_input(Path(args.package), "package")
        if path_error:
            print(path_error, file=sys.stderr)
            return 2
    freeze_path, path_error = _plain_input(Path(args.source_freeze), "source-freeze")
    if path_error:
        print(path_error, file=sys.stderr)
        return 2
    assert archive is not None and freeze_path is not None
    forbidden = [archive, Path(__file__).resolve().parent.parent, freeze_path]
    if package_dir is not None:
        forbidden.append(package_dir)
    ok, reason = _report_path_ok(out, forbidden)
    if not ok:
        print(f"invalid --out: {reason}", file=sys.stderr)
        return 2
    started = _now()
    report: dict = {
        "schema_version": 1,
        "mode": "static",
        "ok": False,
        "tool": {
            "name": "verify_e14_portable_archive.py",
            "sha256": _sha256_file(Path(__file__)),
            "python": sys.version,
        },
        "archive": {
            "path": str(archive),
            "sha256": None,
            "bytes": 0,
            "entries": 0,
        },
        "source_freeze": {},
        "checks": {},
        "required_checks": list(REQUIRED_ARCHIVE_CHECKS),
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
        checks["zip_streamed_without_extract"] = True
        if not archive.is_file():
            raise FileNotFoundError(f"archive missing: {archive}")
        report["archive"]["bytes"] = archive.stat().st_size
        if archive.stat().st_size > 4 * 1024 * 1024 * 1024:
            checks["archive_bytes_bounds"] = False
        else:
            checks["archive_bytes_bounds"] = True
        freeze = _load_freeze_basic(freeze_path)
        report["source_freeze"] = freeze
        checks["source_freeze_present"] = bool(freeze["present"])
        checks["source_freeze_schema"] = bool(freeze["schema"])
        checks["source_freeze_stable"] = bool(freeze["stable"])
        with zipfile.ZipFile(archive) as zf:
            infos = _zip_member_info(zf)
            names = [info.filename for info in infos]
            report["archive"]["entries"] = len(infos)
            top = _zip_top_level_checks(infos, args.product, args.readme)
            checks["archive_not_empty"] = top["not_empty"]
            checks["only_allowed_top_level"] = top["only_allowed"]
            checks["product_dir_only"] = top["product_only"]
            checks["product_dir_present"] = top["product_present"]
            checks["readme_present"] = top["readme"]
            checks["manifest_present"] = top["manifest"]
            checks["checksums_present"] = top["sums"]
            violations = validate_member_names(infos)
            for key, value in _check_codes(violations).items():
                checks[key] = bool(value)
            if violations:
                report["zip_violations"] = violations
                # Do not open any member stream after an unsafe name is seen.
                checks["static_no_execution"] = not process_audit.events
                status = required_status(checks, REQUIRED_ARCHIVE_CHECKS, unknowns)
                report.update(
                    missing_checks=status["missing"],
                    non_bool_checks=status["non_bool"],
                    unknown_checks=status["unknown"],
                    failed_checks=status["failed"],
                    ok=False,
                )
                report["finished_at"] = _now()
                _write_report(out, report)
                print(json.dumps({"ok": False, "mode": "static", "report": str(out)}, ensure_ascii=False))
                return 1

            manifest_raw = _read_member_bytes(zf, MANIFEST, MAX_JSON_BYTES)
            report["manifest_sha256"] = _sha256_bytes(manifest_raw)
            manifest_data: Any = None
            try:
                manifest_data = _json_loads(manifest_raw)
                manifest = _validate_manifest(manifest_data, args.product)
            except Exception as exc:  # noqa: BLE001
                report["errors"].append(f"manifest: {type(exc).__name__}: {exc}")
                manifest = _validate_manifest(None, args.product)
            report["manifest"] = {key: value for key, value in manifest.items() if key != "files"}
            checks["manifest_sha256_format"] = bool(
                isinstance(report.get("manifest_sha256"), str)
                and SHA_RE.match(report["manifest_sha256"])
            )
            checks["manifest_schema_exact"] = bool(manifest["schema"])
            checks["manifest_no_duplicate_keys"] = bool(
                isinstance(manifest_data, dict)
                and not any("duplicate JSON key" in str(item) for item in manifest.get("errors", []))
            )
            checks["manifest_package_relative"] = bool(manifest["package_relative"])
            checks["manifest_paths_relative"] = bool(manifest["paths_relative"])
            checks["manifest_no_duplicate_paths"] = bool(manifest["no_duplicates"])
            checks["manifest_files_nonempty"] = bool(manifest["files_nonempty"])
            if manifest.get("errors"):
                report["errors"].extend(manifest["errors"])

            product_prefix = args.product + "/"
            product_infos = {
                info.filename[len(product_prefix):]: info
                for info in infos
                if info.filename.startswith(product_prefix)
            }
            product_files: dict[str, dict] = {}
            hash_errors: list[str] = []
            for relative, info in sorted(product_infos.items()):
                try:
                    size, digest = _hash_member(zf, info.filename)
                    product_files[relative] = {"size": size, "sha256": digest}
                except Exception as exc:  # noqa: BLE001
                    hash_errors.append(f"{relative}: {type(exc).__name__}: {exc}")
            checks["product_file_set_exact"] = (
                set(product_files) == set(manifest["files"])
            )
            checks["product_sizes_and_hashes_exact"] = bool(
                not hash_errors
                and all(
                    product_files.get(path, {}).get("size") == item.get("size")
                    and product_files.get(path, {}).get("sha256") == item.get("sha256")
                    for path, item in manifest["files"].items()
                )
            )
            sqlalchemy_compiled_members = _sqlalchemy_compiled_members(product_files)
            checks["sqlalchemy_cyextension_absent"] = not sqlalchemy_compiled_members
            report["sqlalchemy"] = {
                "compiled_members": sqlalchemy_compiled_members,
            }
            if hash_errors:
                report["errors"].extend(hash_errors[:20])

            try:
                sums_raw = _read_member_bytes(zf, SUMS, MAX_SUMS_BYTES)
            except Exception as exc:  # noqa: BLE001
                report["errors"].append(f"sums: {type(exc).__name__}: {exc}")
                sums_raw = b""
            sums = _parse_sums(sums_raw, args.product, manifest["files"], args.readme)
            report["checksums_sha256"] = _sha256_bytes(sums_raw)
            checks["checksums_schema_exact"] = bool(sums["schema"])
            checks["checksums_no_duplicates"] = bool(sums["no_duplicates"])
            checks["checksums_cover_product_and_outer"] = bool(sums["covers"])
            checks["checksums_cover_product_and_outer"] = bool(
                checks["checksums_cover_product_and_outer"]
                and all(
                    sums["map"].get(f"{args.product}/{path}") == item.get("sha256")
                    for path, item in manifest["files"].items()
                )
            )
            if sums.get("errors"):
                report["errors"].extend(sums["errors"])

            package_info_name = f"{args.product}/package-info.json"
            package_info: dict = {}
            if package_info_name in names:
                try:
                    package_info = _read_json_bytes(_read_member_bytes(zf, package_info_name, MAX_JSON_BYTES))
                except Exception as exc:  # noqa: BLE001
                    report["errors"].append(f"package-info: {type(exc).__name__}: {exc}")
                    package_info = {}
            checks["package_info_present"] = isinstance(package_info, dict) and bool(package_info)
            checks["package_info_portable"] = bool(
                isinstance(package_info, dict)
                and package_info.get("package") == args.product
                and not Path(str(package_info.get("package"))).is_absolute()
            )
            checks["package_info_metadata_exact"] = bool(
                isinstance(package_info, dict)
                and package_info.get("version") == APP_VERSION
                and package_info.get("database_revision") == DATABASE_REVISION
                and package_info.get("unsigned_internal_test") is True
                and isinstance(package_info.get("source_commit"), str)
                and bool(COMMIT_RE.match(package_info.get("source_commit", "")))
                and isinstance(package_info.get("frontend_digest"), str)
                and bool(SHA_RE.match(package_info.get("frontend_digest", "")))
                and type(package_info.get("frontend_file_count")) is int
                and package_info.get("frontend_file_count") > 0
            )
            manifest_ok = isinstance(manifest_data, dict)
            checks["package_info_matches_manifest"] = bool(
                isinstance(package_info, dict)
                and manifest_ok
                and package_info.get("package") == manifest_data.get("package")
                and package_info.get("build_id") == manifest_data.get("build_id")
                and package_info.get("database_revision") == manifest_data.get("database_revision")
                and package_info.get("source_freeze_digest") == manifest_data.get("source_freeze_digest")
            )
            report["package_info"] = {
                "package": package_info.get("package"),
                "build_id": package_info.get("build_id"),
                "database_revision": package_info.get("database_revision"),
                "source_freeze_digest": package_info.get("source_freeze_digest"),
                "unsigned_internal_test": package_info.get("unsigned_internal_test"),
            }

            checks["source_freeze_matches_manifest"] = bool(
                freeze.get("digest")
                and isinstance(manifest_data, dict)
                and manifest_data.get("source_freeze_digest") == freeze.get("digest")
                and package_info.get("source_freeze_digest") == freeze.get("digest")
            )

            if package_dir is None:
                checks["package_dir_matches_zip"] = False
                unknowns["package_dir_matches_zip"] = "--package is required for candidate acceptance"
            else:
                try:
                    expected_dir = _package_dir_entries(package_dir)
                    expected_map = {
                        item["path"]: {"size": item["size"], "sha256": item["sha256"]}
                        for item in expected_dir
                    }
                    checks["package_dir_matches_zip"] = bool(expected_map == product_files)
                except Exception as exc:  # noqa: BLE001
                    checks["package_dir_matches_zip"] = False
                    report["errors"].append(f"package dir: {type(exc).__name__}: {exc}")

            private_names = _private_name_violations(names)
            checks["no_private_audit_entries"] = not private_names
            text_hits, text_private_hits, allowed_refs, known_sbom, readme_violations, text_complete = _text_abs_paths(zf, names)
            checks["no_absolute_paths_in_text"] = bool(text_complete and not text_hits)
            checks["privacy_text_scan_complete"] = bool(text_complete)
            checks["readme_no_private_paths"] = bool(not readme_violations)
            report["allowed_build_references"] = allowed_refs
            report["known_sbom"] = known_sbom
            try:
                readme_bytes = _read_member_bytes(zf, args.readme, MAX_README_BYTES)
                readme_text = readme_bytes.decode("utf-8", errors="ignore")
                checks["checksums_cover_product_and_outer"] = bool(
                    checks["checksums_cover_product_and_outer"]
                    and sums["map"].get(args.readme) == _sha256_bytes(readme_bytes)
                    and sums["map"].get(MANIFEST) == report.get("manifest_sha256")
                )
            except Exception as exc:  # noqa: BLE001
                report["errors"].append(f"README: {type(exc).__name__}: {exc}")
                checks["readme_no_private_paths"] = False
            private_keys = list(text_private_hits)
            for name in names:
                lower = name.casefold()
                if lower.endswith((".key", ".p12", ".pfx", ".dpapi")):
                    private_keys.append({"path": name, "reason": "private-key-material"})
                elif lower.endswith((".pem", ".crt", ".cer")):
                    try:
                        head = _read_member_bytes(zf, name, MAX_PUBLIC_CERT_BYTES)
                        text = head.decode("utf-8", errors="ignore")
                    except Exception:  # noqa: BLE001
                        private_keys.append({"path": name, "reason": "unreadable"})
                        continue
                    if "PRIVATE KEY" in text or "BEGIN CERTIFICATE" not in text:
                        private_keys.append({"path": name, "reason": "not-public-certificate"})
            checks["no_private_material"] = bool(not private_names and not private_keys)
            public_ca_ok = True
            for name in names:
                if not name.casefold().endswith(".pem"):
                    continue
                try:
                    text = _read_member_bytes(zf, name, MAX_PUBLIC_CERT_BYTES).decode("utf-8", errors="ignore")
                except Exception:  # noqa: BLE001
                    public_ca_ok = False
                    continue
                if "PRIVATE KEY" in text:
                    public_ca_ok = False
            checks["public_ca_and_licenses_preserved"] = bool(public_ca_ok)
            if not public_ca_ok:
                report["errors"].append("private key material under public certificate path")
            if text_hits:
                report["absolute_text_hits"] = text_hits[:50]
            if private_keys:
                report["private_key_hits"] = private_keys

        report["archive"]["sha256"] = _sha256_file(archive)
        checks["archive_sha256_recorded"] = bool(SHA_RE.match(report["archive"]["sha256"]))
        checks["static_no_execution"] = not process_audit.events
        if process_audit.events:
            report["process_events"] = list(process_audit.events)
        status = required_status(checks, REQUIRED_ARCHIVE_CHECKS, unknowns)
        report["missing_checks"] = status["missing"]
        report["non_bool_checks"] = status["non_bool"]
        report["unknown_checks"] = status["unknown"]
        report["failed_checks"] = status["failed"]
        report["ok"] = bool(status["ok"])
        report["limitations"] = [
            "archive is streamed read-only; no extraction or execution",
            "public CA/license presence is not a signature or trust validation",
            "manifest and SHA256SUMS are checked against actual ZIP bytes, not self-reported values",
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
