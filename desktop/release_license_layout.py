"""Compact legal license layout and managed Windows install-path budgets.

The signed preview payload carries every third-party license text plus the
application, CPython and supplemental notices.  The original layout mirrored
each distribution's directory tree, which produced a 270 UTF-16-unit path in
the default install root and failed with WinError 206 when long paths were
disabled.

This module converts the complete set of texts into deterministic, fixed-length
names under ``licenses/redistribution/texts/<id>.txt`` and keeps an index that
binds every text back to its original relative position, package identity,
source link, size and SHA-256.  It also validates the final application tree
against the real managed update layouts:

* ``app/``
* ``updates/staging/<24>/KindergartenManager/``
* ``install-state/<32>/verified/KindergartenManager/``
* ``backups/<32>/``

The budget covers both file paths and every parent directory, using UTF-16 code
units (the unit used by the Windows path limit).  It is deliberately
conservative: the supported install-root budget is 98 units, and a 126-unit
verification prefix before the canonical archive root is kept as the real-machine
regression case.  Longer unknown teacher roots are not claimed as covered.

The module never reads credentials, writes outside the supplied redistribution
directory, or follows reparse points.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

TEXT_ID_LENGTH = 32
REDISTRIBUTION_REL = Path("licenses/redistribution")
TEXTS_REL = Path("texts")
INDEX_NAME = "components.json"
LAYOUT_SCHEMA = "compact-license-texts/1"
COMPONENTS_SCHEMA_VERSION = 2
MAX_PATH_UTF16_UNITS = 260
# Windows non-long-path directory creation is limited to MAX_PATH-12 = 248
# UTF-16 units including the terminating NUL/conservative boundary. The actual
# observed boundary on this machine is 247 succeeds, 248 fails with WinError206.
# Store the maximum allowed value explicitly, so the rejection rule is >247.
# https://learn.microsoft.com/en-us/windows/win32/fileio/maximum-file-path-limitation
MAX_DIRECTORY_UTF16_UNITS = 247
# Provisional verification target, now a checked product-support budget: an
# install root of at most 98 units keeps every full path <=258 and every parent
# directory <=247. Actual default 70 and planned old-helper test root 93 fit.
DEFAULT_INSTALL_ROOT_BUDGET = 98
REGRESSION_VERIFY_PREFIX_UNITS = 126

# Prefixes are relative to the managed install root. The fixed-width IDs match
# the production update plan/download identities.
MANAGED_LAYOUTS: tuple[tuple[str, str], ...] = (
    ("app", "app/"),
    ("update-staging", "updates/staging/" + "0" * 24 + "/KindergartenManager/"),
    ("install-state-verified", "install-state/" + "0" * 32 + "/verified/KindergartenManager/"),
    ("install-backup", "backups/" + "0" * 32 + "/"),
)

_RELATIVE_PART = re.compile(r"^[^/\\:*?\"<>|\x00]+$")
_ECOSYSTEM = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_TEXT_ID = re.compile(r"^[0-9a-f]{%d}$" % TEXT_ID_LENGTH)


class LicenseLayoutError(ValueError):
    """A license source, id, index or stored text is not acceptable."""


class PathBudgetError(ValueError):
    """A managed path exceeds the conservative Windows path budget."""


@dataclass(frozen=True)
class LicenseTextSource:
    """One immutable license text and its original release-relative position."""

    ecosystem: str
    package: str
    version: str
    source_relative_path: str
    source_path: Path
    source_url: str = ""


def utf16_units(text: str) -> int:
    """Length in UTF-16 code units, matching the Windows path accounting."""
    return len(str(text).encode("utf-16-le")) // 2


def _validate_relative_path(value: str, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise LicenseLayoutError(f"{label} is empty")
    if value.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", value):
        raise LicenseLayoutError(f"{label} is absolute: {value!r}")
    if "\\" in value:
        raise LicenseLayoutError(f"{label} must use POSIX separators: {value!r}")
    if ":" in value:
        raise LicenseLayoutError(f"{label} contains an ADS/stream separator: {value!r}")
    parts = value.split("/")
    if any(not part or part in (".", "..") for part in parts):
        raise LicenseLayoutError(f"{label} has an empty/dot segment: {value!r}")
    if any(not _RELATIVE_PART.match(part) for part in parts):
        raise LicenseLayoutError(f"{label} has an unexpected character: {value!r}")
    return value


def _validate_identity(source: LicenseTextSource) -> None:
    if not _ECOSYSTEM.match(source.ecosystem):
        raise LicenseLayoutError(f"invalid ecosystem: {source.ecosystem!r}")
    if not isinstance(source.package, str) or not source.package.strip():
        raise LicenseLayoutError("package name is empty")
    if not isinstance(source.version, str) or not source.version.strip():
        raise LicenseLayoutError("package version is empty")
    _validate_relative_path(source.source_relative_path, "source relative path")
    if not isinstance(source.source_url, str):
        raise LicenseLayoutError("source URL must be a string")
    if source.source_url:
        if not source.source_url.startswith("https://") or any(
            char.isspace() or ord(char) < 0x20 for char in source.source_url
        ):
            raise LicenseLayoutError("source URL must be a non-absolute HTTPS link")


def canonical_text_id(
    ecosystem: str,
    package: str,
    version: str,
    source_relative_path: str,
) -> str:
    """Deterministic fixed-length ID from ecosystem+package+version+source path."""
    regular = LicenseTextSource(
        ecosystem=ecosystem,
        package=package,
        version=version,
        source_relative_path=source_relative_path,
        source_path=Path("."),
    )
    _validate_identity(regular)
    payload = "\x00".join(
        (
            ecosystem,
            package,
            version,
            source_relative_path,
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:TEXT_ID_LENGTH]


def _read_source(source: LicenseTextSource) -> bytes:
    path = Path(source.source_path)
    assert_no_reparse_ancestors(path)
    if not path.is_file():
        raise LicenseLayoutError(f"license text is missing: {source.source_relative_path}")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise LicenseLayoutError(f"license text is unreadable: {source.source_relative_path}: {exc}")


def build_compact_layout(sources: Iterable[LicenseTextSource]) -> dict:
    """Build the deterministic layout/index without writing anything."""
    texts: list[dict] = []
    seen_ids: dict[str, tuple[str, str, str, str]] = {}
    seen_sources: set[tuple[str, str, str, str]] = set()
    components: dict[tuple[str, str, str, str], list[str]] = {}

    for source in sources:
        _validate_identity(source)
        identity = (
            source.ecosystem,
            source.package,
            source.version,
            source.source_relative_path,
        )
        if identity in seen_sources:
            raise LicenseLayoutError(f"duplicate license source: {identity!r}")
        seen_sources.add(identity)
        text_id = canonical_text_id(*identity)
        previous = seen_ids.get(text_id)
        if previous is not None:
            raise LicenseLayoutError(
                f"compact license id collision: {text_id} for {previous!r} and {identity!r}"
            )
        seen_ids[text_id] = identity
        data = _read_source(source)
        digest = hashlib.sha256(data).hexdigest()
        target = f"{TEXTS_REL.as_posix()}/{text_id}.txt"
        texts.append(
            {
                "id": text_id,
                "ecosystem": source.ecosystem,
                "package": source.package,
                "version": source.version,
                "source_relative_path": source.source_relative_path,
                "target_relative_path": target,
                "sha256": digest,
                "size": len(data),
                "source_url": source.source_url,
            }
        )
        components.setdefault(
            (source.ecosystem, source.package, source.version, source.source_url),
            [],
        ).append(text_id)

    if not texts:
        raise LicenseLayoutError("no license texts supplied")
    texts.sort(key=lambda item: item["id"])
    component_list = [
        {
            "ecosystem": ecosystem,
            "package": package,
            "version": version,
            "source": source_url,
            "texts": sorted(ids),
        }
        for (ecosystem, package, version, source_url), ids in sorted(components.items())
    ]
    return {
        "schema": LAYOUT_SCHEMA,
        "schema_version": COMPONENTS_SCHEMA_VERSION,
        "text_id_length": TEXT_ID_LENGTH,
        "texts": texts,
        "components": component_list,
    }


def _layout_json(layout: dict) -> bytes:
    return (json.dumps(layout, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def materialize_compact_layout(sources: Sequence[LicenseTextSource], redistribution_root: Path) -> dict:
    """Write the compact texts and index into a new redistribution directory."""
    # Validate raw output path (including every ancestor) BEFORE any mkdir/write.
    root = assert_no_reparse_ancestors(Path(redistribution_root))
    if root.exists():
        raise LicenseLayoutError(f"redistribution root already exists: {root}")
    layout = build_compact_layout(sources)
    by_id = {item["id"]: item for item in layout["texts"]}
    root.mkdir(parents=True, exist_ok=False)
    texts_root = root / TEXTS_REL
    texts_root.mkdir()
    for source in sources:
        text_id = canonical_text_id(
            source.ecosystem,
            source.package,
            source.version,
            source.source_relative_path,
        )
        entry = by_id[text_id]
        data = _read_source(source)
        if len(data) != entry["size"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise LicenseLayoutError(f"license text changed during layout: {source.source_relative_path}")
        target = root / entry["target_relative_path"]
        if target.exists():
            raise LicenseLayoutError(f"compact license target already exists: {target}")
        with target.open("xb") as handle:
            handle.write(data)
    index = root / INDEX_NAME
    if index.exists():
        raise LicenseLayoutError(f"components index already exists: {index}")
    with index.open("xb") as handle:
        handle.write(_layout_json(layout))
    verify_compact_layout(root, layout)
    return layout


def assert_no_reparse_ancestors(path: Path) -> Path:
    """Reject ``..`` and every reparse point on the raw path, then resolve.

    Only a definitively missing path is walked past.  Permission errors, IO
    errors and every other attribute failure are refused before materialization;
    otherwise an unknown ancestor reparse state could allow a write.
    """
    raw = path if path.is_absolute() else Path.cwd() / path
    if ".." in raw.parts:
        raise LicenseLayoutError(f"path contains '..': {raw}")
    current = Path(os.path.abspath(raw))
    while True:
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            info = None
        except OSError as exc:
            missing = exc.errno == errno.ENOENT or getattr(exc, "winerror", None) in (2, 3)
            if not missing:
                raise LicenseLayoutError(
                    f"cannot inspect path attributes before writing: {current}: {exc}"
                ) from exc
            info = None
        if info is not None:
            if stat.S_ISLNK(info.st_mode) or (
                getattr(info, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            ):
                raise LicenseLayoutError(f"path contains a reparse point: {current}")
        parent = current.parent
        if parent == current:
            break
        current = parent
    return raw.resolve()


def _walk_regular_files(root: Path) -> list[Path]:
    resolved = assert_no_reparse_ancestors(root)
    if not resolved.is_dir():
        raise LicenseLayoutError(f"license layout root is not a directory: {root}")
    files: list[Path] = []

    def visit(directory: Path) -> None:
        for entry in sorted(os.scandir(directory), key=lambda item: item.name):
            path = Path(entry.path)
            if entry.is_symlink():
                raise LicenseLayoutError(f"reparse/symlink entry in license layout: {path}")
            info = entry.stat(follow_symlinks=False)
            if getattr(info, "st_file_attributes", 0) & getattr(
                stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400
            ):
                raise LicenseLayoutError(f"reparse entry in license layout: {path}")
            if entry.is_dir(follow_symlinks=False):
                visit(path)
            elif entry.is_file(follow_symlinks=False):
                files.append(path)
            else:
                raise LicenseLayoutError(f"special entry in license layout: {path}")

    visit(resolved)
    return files


def verify_compact_layout(redistribution_root: Path, layout: dict | None = None) -> dict:
    """Verify index/size/hash/one-to-one coverage of a compact layout tree."""
    root = assert_no_reparse_ancestors(Path(redistribution_root))
    index_path = root / INDEX_NAME
    if not index_path.is_file():
        raise LicenseLayoutError(f"components index is missing: {index_path}")
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LicenseLayoutError(f"components index is unreadable: {exc}")
    if not isinstance(index, dict) or index.get("schema") != LAYOUT_SCHEMA:
        raise LicenseLayoutError("components index schema is not compact-license-texts/1")
    if layout is not None and index != json.loads(json.dumps(layout, ensure_ascii=False)):
        raise LicenseLayoutError("components index differs from the supplied layout")
    entries = index.get("texts")
    if not isinstance(entries, list) or not entries:
        raise LicenseLayoutError("components index has no texts")
    by_target: dict[str, dict] = {}
    by_id: dict[str, dict] = {}
    for item in entries:
        if not isinstance(item, dict):
            raise LicenseLayoutError("components index has a non-object text entry")
        text_id = item.get("id")
        if not isinstance(text_id, str) or not _TEXT_ID.match(text_id):
            raise LicenseLayoutError(f"invalid compact text id: {text_id!r}")
        if text_id in by_id:
            raise LicenseLayoutError(f"duplicate compact text id: {text_id}")
        target = item.get("target_relative_path")
        _validate_relative_path(target, "target relative path")
        if target != f"texts/{text_id}.txt":
            raise LicenseLayoutError(f"compact target does not match its id: {target}")
        if target in by_target:
            raise LicenseLayoutError(f"duplicate compact target: {target}")
        sha = item.get("sha256")
        size = item.get("size")
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
            raise LicenseLayoutError(f"invalid text sha256: {target}")
        if type(size) is not int or size < 0:
            raise LicenseLayoutError(f"invalid text size: {target}")
        for field in ("ecosystem", "package", "version", "source_relative_path"):
            if not isinstance(item.get(field), str) or not item.get(field):
                raise LicenseLayoutError(f"missing {field} for {target}")
        _validate_relative_path(item["source_relative_path"], "source relative path")
        if item.get("source_url"):
            if not str(item["source_url"]).startswith("https://") or any(
                char.isspace() or ord(char) < 0x20 for char in str(item["source_url"])
            ):
                raise LicenseLayoutError(f"source URL is not an HTTPS link: {target}")
        recomputed = canonical_text_id(
            item["ecosystem"],
            item["package"],
            item["version"],
            item["source_relative_path"],
        )
        if recomputed != text_id:
            raise LicenseLayoutError(f"compact text id does not match its provenance: {target}")
        by_target[target] = item
        by_id[text_id] = item

    components = index.get("components")
    if not isinstance(components, list) or not components:
        raise LicenseLayoutError("components index has no component groups")
    grouped: list[str] = []
    for component in components:
        if not isinstance(component, dict):
            raise LicenseLayoutError("non-object component entry")
        ids = component.get("texts")
        if not isinstance(ids, list) or not ids:
            raise LicenseLayoutError("component has no text ids")
        for text_id in ids:
            if text_id not in by_id:
                raise LicenseLayoutError(f"component references an unknown text id: {text_id}")
            text_entry = by_id[text_id]
            if (
                component.get("ecosystem") != text_entry.get("ecosystem")
                or component.get("package") != text_entry.get("package")
                or component.get("version") != text_entry.get("version")
                or component.get("source") != text_entry.get("source_url")
            ):
                raise LicenseLayoutError(f"component metadata does not match text provenance: {text_id}")
            grouped.append(text_id)
    if sorted(grouped) != sorted(by_id):
        raise LicenseLayoutError("component groups do not cover each text exactly once")

    actual_files = {path.relative_to(root).as_posix(): path for path in _walk_regular_files(root)}
    expected_files = {INDEX_NAME, *by_target}
    extra = sorted(set(actual_files) - expected_files)
    missing = sorted(expected_files - set(actual_files))
    if extra or missing:
        raise LicenseLayoutError(f"license tree differs from index: extra={extra[:3]} missing={missing[:3]}")
    total_bytes = 0
    for target, item in by_target.items():
        data = actual_files[target].read_bytes()
        if len(data) != item["size"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
            raise LicenseLayoutError(f"compact text content differs: {target}")
        total_bytes += len(data)
    return {
        "schema": LAYOUT_SCHEMA,
        "text_count": len(by_target),
        "component_count": len(components),
        "total_bytes": total_bytes,
        "index_sha256": hashlib.sha256(index_path.read_bytes()).hexdigest(),
    }


def synthetic_install_root(units: int) -> str:
    """A deterministic Windows-style root string with exactly ``units`` units."""
    if not isinstance(units, int) or units < 4:
        raise PathBudgetError("synthetic root needs at least 4 UTF-16 units")
    return "C:\\" + "r" * (units - 3)


def assert_root_supported(install_root: str | Path, budget: int = DEFAULT_INSTALL_ROOT_BUDGET) -> int:
    """Reject an install root outside the conservative supported budget."""
    units = utf16_units(str(install_root))
    if units > budget:
        raise PathBudgetError(
            f"install root is {units} UTF-16 units, beyond the supported {budget}-unit budget"
        )
    return units


def _directory_chain(root: str, prefix: str, relative: str) -> list[str]:
    parts = [part for part in prefix.replace("/", "\\").split("\\") if part]
    parts += [part for part in relative.replace("/", "\\").split("\\") if part]
    chain: list[str] = []
    current = root
    for part in parts:
        current = current + "\\" + part
        chain.append(current)
    return chain


def audit_managed_paths(
    install_root: str | Path,
    relative_files: Sequence[str],
    relative_directories: Sequence[str] = (),
    *,
    layouts: Sequence[tuple[str, str]] = MANAGED_LAYOUTS,
    max_path_units: int = MAX_PATH_UTF16_UNITS,
    max_directory_units: int = MAX_DIRECTORY_UTF16_UNITS,
) -> dict:
    """Audit files and every directory against the traditional Windows limits."""
    root = str(install_root).rstrip("\\/")
    root_units = utf16_units(root)
    violations: list[dict] = []
    checked_files = 0
    checked_directories: set[str] = set()
    layout_reports: list[dict] = []

    def check_directory(path: str, layout: str) -> None:
        if path in checked_directories:
            return
        checked_directories.add(path)
        units = utf16_units(path)
        if units > max_directory_units:
            violations.append(
                {
                    "layout": layout,
                    "kind": "directory",
                    "path": path,
                    "units": units,
                    "limit": max_directory_units,
                    "limit_kind": "max-directory",
                }
            )

    check_directory(root, "install-root")
    for layout_name, prefix in layouts:
        layout_violations_start = len(violations)
        layout_root = root
        for directory in _directory_chain(root, prefix, ""):
            layout_root = directory
            check_directory(directory, layout_name)
        for relative in relative_files:
            _validate_relative_path(relative, "install file")
            full = layout_root + "\\" + relative.replace("/", "\\")
            checked_files += 1
            units = utf16_units(full)
            if units >= max_path_units:
                violations.append(
                    {
                        "layout": layout_name,
                        "kind": "file",
                        "path": full,
                        "units": units,
                        "limit": max_path_units,
                    }
                )
            for directory in _directory_chain(root, prefix, relative)[:-1]:
                check_directory(directory, layout_name)
        for relative in relative_directories:
            _validate_relative_path(relative, "install directory")
            for directory in _directory_chain(root, prefix, relative):
                check_directory(directory, layout_name)
        layout_reports.append(
            {
                "name": layout_name,
                "prefix": prefix,
                "violations": len(violations) - layout_violations_start,
            }
        )

    return {
        "install_root": root,
        "install_root_units": root_units,
        "within_supported_root_budget": root_units <= DEFAULT_INSTALL_ROOT_BUDGET,
        "max_path_units": max_path_units,
        "max_directory_units": max_directory_units,
        "checked_files": checked_files,
        "checked_directories": len(checked_directories),
        "layouts": layout_reports,
        "violations": violations,
        "ok": not violations,
        "supported_root_budget": DEFAULT_INSTALL_ROOT_BUDGET,
        "regression_verify_prefix_units": REGRESSION_VERIFY_PREFIX_UNITS,
        "support_note": (
            "Supported install roots are at most 98 UTF-16 units. File paths must "
            "remain below 260; directory paths must be at most 247 (observed actual "
            "boundary: 247 succeeds, 248 fails with WinError206 without long "
            "paths). The 126-unit regression is a verify-prefix length before the "
            "canonical archive root, not an install root. Unknown longer teacher "
            "install roots are not covered; 100 units is an explicitly unsupported "
            "verification boundary."
        ),
    }


def audit_verify_prefix(
    verify_prefix: str | Path,
    relative_files: Sequence[str],
    relative_directories: Sequence[str] = (),
    *,
    archive_root: str = "KindergartenManager",
    max_path_units: int = MAX_PATH_UTF16_UNITS,
    max_directory_units: int = MAX_DIRECTORY_UTF16_UNITS,
) -> dict:
    """Audit the exact unpack shape: prefix + archive root + entry paths."""
    if not isinstance(archive_root, str) or not archive_root or any(
        part in ("", ".", "..") or "\\" in part or ":" in part
        for part in archive_root.split("/")
    ):
        raise PathBudgetError("archive root must be one canonical path component")
    report = audit_managed_paths(
        verify_prefix,
        relative_files,
        relative_directories,
        layouts=(("verify-prefix", f"{archive_root}/"),),
        max_path_units=max_path_units,
        max_directory_units=max_directory_units,
    )
    return {
        "verify_prefix": report["install_root"],
        "verify_prefix_units": report["install_root_units"],
        "archive_root": archive_root,
        "max_path_units": report["max_path_units"],
        "max_directory_units": report["max_directory_units"],
        "checked_files": report["checked_files"],
        "checked_directories": report["checked_directories"],
        "violations": report["violations"],
        "ok": report["ok"],
        "support_note": (
            "This is the exact verify-prefix + canonical archive root + entry "
            "shape. It is arithmetic path auditing, not a ZIP extraction result."
        ),
    }


def assert_verify_prefix(
    verify_prefix: str | Path,
    relative_files: Sequence[str],
    relative_directories: Sequence[str] = (),
    *,
    archive_root: str = "KindergartenManager",
    max_path_units: int = MAX_PATH_UTF16_UNITS,
    max_directory_units: int = MAX_DIRECTORY_UTF16_UNITS,
) -> dict:
    report = audit_verify_prefix(
        verify_prefix,
        relative_files,
        relative_directories,
        archive_root=archive_root,
        max_path_units=max_path_units,
        max_directory_units=max_directory_units,
    )
    if report["violations"]:
        raise PathBudgetError(f"verify-prefix path budget exceeded: {report['violations'][:3]}")
    return report


def assert_managed_paths(
    install_root: str | Path,
    relative_files: Sequence[str],
    relative_directories: Sequence[str] = (),
    *,
    layouts: Sequence[tuple[str, str]] = MANAGED_LAYOUTS,
    max_path_units: int = MAX_PATH_UTF16_UNITS,
    max_directory_units: int = MAX_DIRECTORY_UTF16_UNITS,
) -> dict:
    report = audit_managed_paths(
        install_root,
        relative_files,
        relative_directories,
        layouts=layouts,
        max_path_units=max_path_units,
        max_directory_units=max_directory_units,
    )
    if report["violations"]:
        first = report["violations"][:3]
        raise PathBudgetError(f"managed path budget exceeded: {first}")
    return report
