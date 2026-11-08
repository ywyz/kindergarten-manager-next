"""Build the E14 complete desktop package (independent root; old packages kept).

The package is a PyInstaller onedir/windowed distribution of the real D1/E14
entry, current frontend build, controlled observation and one-to-one listening
templates, the complete local migration chain and Pillow imaging plugins. It
reuses the existing venv/node_modules and never installs or upgrades
dependencies.

Path safety (E14-R01): every write target is resolved and checked *before* any
frontend/package write. The build root must be a fresh direct child of
``<repo>/build`` named ``desktop-e14-*`` (the r01 ``desktop-e14`` root and all
older build roots are protected), and the hash/source-freeze outputs must be
outside the repository and outside every protected source/build root.

Source freeze (E14-R02): product/build sources are hashed both before and after
the build (cache files excluded); the build fails if the two lists differ.

Build identity/licence (E14-R03): the candidate receives a real UUID
``_internal/build_identity.json`` carrying the resolved release version,
channel and current source migration head; a missing Pillow licence, imaging
plugin or controlled listening-template file aborts the build instead of
producing a package that claims to be complete.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import d0_paths
import update_identity
from build_d0 import resolve_node_tool
from verify_e14_package import (
    discover_migration_chain,
    resolve_release_identity,
    source_migration_files,
)

BUILD_ROOT = d0_paths.REPO_ROOT / "build" / "desktop-e14-win11-r01"
PRODUCT_NAME = "KGNext-E14"
APP_NAME = PRODUCT_NAME  # compatibility with the existing builder/tests
PORTABLE_DIR_NAME = "dist"
ARCHIVE_NAME = "KGNext-E14-win11-r01.zip"
README_NAME = "README-KGNext-E14-win11-r01.txt"
MANIFEST_NAME = "package-files.json"
SUMS_NAME = "SHA256SUMS.txt"
MANIFEST_SCHEMA_VERSION = 1
PILLOW_VERSION = "13.0.0"

TEMPLATE_DIR = d0_paths.BACKEND_ROOT / "app" / "assets" / "word_templates"
LISTENING_TEMPLATE_DIR = (
    d0_paths.BACKEND_ROOT / "app" / "assets" / "listening_templates"
)
LISTENING_TEMPLATE_GRADES = ("small", "middle", "large")
LISTENING_TEMPLATE_DOMAINS = ("health", "language", "social", "science", "art")
LISTENING_TEMPLATE_DOCX = tuple(
    f"v1/{grade}_{domain}.docx"
    for grade in LISTENING_TEMPLATE_GRADES
    for domain in LISTENING_TEMPLATE_DOMAINS
)
LISTENING_TEMPLATE_REQUIRED_FILES = (
    "README.md",
    "manifest.json",
    *LISTENING_TEMPLATE_DOCX,
)
ALEMBIC_INI = d0_paths.BACKEND_ROOT / "alembic-local.ini"
MIGRATIONS_DIR = d0_paths.BACKEND_ROOT / "migrations_local"
PILLOW_LICENSE = (
    d0_paths.REPO_ROOT
    / "desktop"
    / ".venv-d1"
    / "Lib"
    / "site-packages"
    / f"pillow-{PILLOW_VERSION}.dist-info"
    / "licenses"
    / "LICENSE"
)
PILLOW_PLUGIN_DIR = d0_paths.REPO_ROOT / "desktop" / ".venv-d1" / "Lib" / "site-packages" / "PIL"
PILLOW_REQUIRED_PLUGINS = (
    "_imaging.cp314-win_amd64.pyd",
    "_imagingft.cp314-win_amd64.pyd",
    "_imagingcms.cp314-win_amd64.pyd",
    "_webp.cp314-win_amd64.pyd",
    "_avif.cp314-win_amd64.pyd",
)

# SQLAlchemy 2.0.54 treats these Cython extensions as optional and falls back
# to its pure-Python implementations when they cannot be imported.  Package
# them as absent so the frozen app never loads the unsigned optional binaries.
SQLALCHEMY_CYEXTENSION_MODULES = (
    "sqlalchemy.cyextension",
    "sqlalchemy.cyextension.collections",
    "sqlalchemy.cyextension.immutabledict",
    "sqlalchemy.cyextension.processors",
    "sqlalchemy.cyextension.resultproxy",
    "sqlalchemy.cyextension.util",
)
SQLALCHEMY_COMPILED_SUFFIXES = (".pyd", ".dll")

# Never write into these roots. ``desktop-e14`` and ``desktop-e14-r02`` are
# preserved candidates; ``desktop-e14-r03`` and later suffixed roots are the
# only allowed build-root family.
PROTECTED_BUILD_ROOTS = (
    d0_paths.REPO_ROOT / "build" / "desktop-d1",
    d0_paths.REPO_ROOT / "build" / "desktop-d2",
    d0_paths.REPO_ROOT / "build" / "desktop-d2-manual-ai",
    d0_paths.REPO_ROOT / "build" / "desktop-e14",
    d0_paths.REPO_ROOT / "build" / "desktop-e14-r02",
    d0_paths.REPO_ROOT / "build" / "desktop-e14-r03",
    d0_paths.REPO_ROOT / "build" / "desktop-e14-r03-pre-prune",
)
PROTECTED_SOURCE_ROOTS = (
    d0_paths.REPO_ROOT / "frontend",
    d0_paths.REPO_ROOT / "backend",
    d0_paths.REPO_ROOT / "desktop",
    d0_paths.REPO_ROOT / "docs",
)

SOURCE_GROUPS: dict[str, tuple[str, ...]] = {
    "product": (
        "backend/app",
        "backend/migrations_local",
        "backend/alembic-local.ini",
        "desktop/d0_main.py",
        "desktop/d0_paths.py",
        # Actual D0/PyInstaller archived production inputs (r01 CArchive/PYZ).
        "desktop/d0_db.py",
        "desktop/d0_driver.py",
        "desktop/d0_host_api.py",
        "desktop/d0_server.py",
        "desktop/d0_word.py",
        "desktop/d1_main.py",
        "desktop/d1_host_api.py",
        "desktop/d1_server.py",
        "desktop/d1_paths.py",
        "desktop/renderer_recovery.py",
        "desktop/renderer_recovery_native.py",
        "desktop/maintenance_host.py",
        "desktop/maintenance_lifecycle.py",
        "desktop/d2_same_origin.py",
        "desktop/update_fs.py",
        "desktop/update_github.py",
        "desktop/update_helper.py",
        "desktop/update_identity.py",
        "desktop/update_install.py",
        "desktop/update_manifest.py",
        "desktop/update_paths.py",
        "desktop/update_process.py",
        "desktop/update_service.py",
        "desktop/update_trust.py",
        "desktop/update_u3_harness.py",
        "frontend/src",
        "frontend/d1.html",
        "frontend/tsconfig.json",
        "frontend/vite.d1.config.ts",
        "frontend/package.json",
        "frontend/package-lock.json",
    ),
    "build": (
        "desktop/build_e14.py",
        "desktop/build_d0.py",
        "desktop/verify_e14_package.py",
        "desktop/requirements-d1.in",
        "desktop/requirements-d1.lock.txt",
        "desktop/requirements-d1-build-constraints.txt",
    ),
    "verification": (
        "desktop/verify_observation_window.py",
        "desktop/verify_observation_multi.py",
        "desktop/verify_observation_old_upgrade.py",
        "desktop/verify_e14_portable_archive.py",
        "desktop/verify_renderer_recovery_window.py",
        "desktop/tests/test_renderer_recovery_verifier.py",
        "desktop/tests/test_e14_build_guard.py",
        "desktop/tests/test_windows11_portable_static.py",
        "desktop/check_windows11_target.ps1",
    ),
    "resources": (
        "backend/app/assets/word_templates",
        "backend/app/assets/listening_templates",
    ),
}
CACHE_PARTS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
CACHE_SUFFIXES = {".pyc", ".pyo"}
OPTIONAL_SOURCE_PATHS = {
    "desktop/tests/test_windows11_portable_static.py",
    "desktop/check_windows11_target.ps1",
}


def os_sep() -> str:
    return ";" if sys.platform.startswith("win") else ":"


def _overlaps(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _iter_source_files(relative: str, *, optional: bool = False) -> list[Path]:
    root = d0_paths.REPO_ROOT / relative
    if not root.exists():
        if optional:
            return []
        raise SystemExit(f"拒绝：配置来源缺失 {relative}；不得静默漏掉生产/构建来源")
    if root.is_file():
        return [root]
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in CACHE_PARTS for part in path.parts):
            continue
        if path.suffix.lower() in CACHE_SUFFIXES:
            continue
        files.append(path)
    return files


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _freeze_digest(files: list[dict]) -> str:
    payload = json.dumps(
        [{"path": item["path"], "sha256": item["sha256"]} for item in files],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def source_freeze() -> dict:
    """Hash product/build sources; caches are excluded from both snapshots."""
    files: list[dict] = []
    seen: set[str] = set()
    missing_optional: list[str] = []
    for group, relatives in SOURCE_GROUPS.items():
        for relative in relatives:
            optional = relative in OPTIONAL_SOURCE_PATHS
            found = _iter_source_files(relative, optional=optional)
            if not found and optional:
                missing_optional.append(relative)
            for path in found:
                rel = path.relative_to(d0_paths.REPO_ROOT).as_posix()
                if rel in seen:
                    continue
                seen.add(rel)
                files.append(
                    {
                        "path": rel,
                        "group": group,
                        "size": path.stat().st_size,
                        "sha256": _sha256_file(path),
                    }
                )
    files.sort(key=lambda item: item["path"])
    missing_optional.sort()
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=d0_paths.REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=d0_paths.REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    diff_names = subprocess.run(
        ["git", "diff", "--name-only"],
        cwd=d0_paths.REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return {
        "commit": commit,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "groups": {name: list(paths) for name, paths in SOURCE_GROUPS.items()},
        "file_count": len(files),
        "digest": _freeze_digest(files),
        "files": files,
        "git_status": [
            line for line in (status.stdout or "").splitlines() if line.strip()
        ],
        "git_diff_names": [
            line for line in (diff_names.stdout or "").splitlines() if line.strip()
        ],
        "missing_optional": missing_optional,
    }


def _freeze_changes(before: dict, after: dict) -> dict:
    before_map = {item["path"]: item for item in before["files"]}
    after_map = {item["path"]: item for item in after["files"]}
    changed = sorted(
        path
        for path in before_map.keys() & after_map.keys()
        if before_map[path]["sha256"] != after_map[path]["sha256"]
    )
    added = sorted(after_map.keys() - before_map.keys())
    removed = sorted(before_map.keys() - after_map.keys())
    before_digest = _freeze_digest(before.get("files") or [])
    after_digest = _freeze_digest(after.get("files") or [])
    stable = bool(
        not changed
        and not added
        and not removed
        and before_digest == after_digest
        and len(before.get("files") or []) == len(after.get("files") or [])
    )
    return {
        "stable": stable,
        "changed": changed,
        "added": added,
        "removed": removed,
        "before_digest": before_digest,
        "after_digest": after_digest,
    }


def _safe_walk_entries(root: Path) -> tuple[list[Path], list[Path]]:
    """Walk a directory without following symlinks/junctions/reparse points.

    Every existing raw ancestor and every nested entry is checked before any
    bytes are read or any cache path is deleted.  The returned paths are inside
    the resolved trusted root.
    """
    raw_root = root
    if ".." in raw_root.parts:
        raise SystemExit(f"拒绝：目录路径含 .. 段 {raw_root}")
    raw_abs = raw_root if raw_root.is_absolute() else Path.cwd() / raw_root
    if _has_reparse_component(raw_abs):
        raise SystemExit(f"拒绝：目录路径含 symlink／junction／reparse {raw_root}")
    if not raw_abs.is_dir():
        raise SystemExit(f"拒绝：目录不存在或不是目录 {raw_root}")
    trusted = raw_abs.resolve()
    dirs: list[Path] = []
    files: list[Path] = []

    def visit(directory: Path) -> None:
        if _is_reparse_point(directory):
            raise SystemExit(f"拒绝：目录含 reparse 点 {directory}")
        try:
            entries = sorted(os.scandir(directory), key=lambda item: item.name)
        except OSError as exc:
            raise SystemExit(f"拒绝：无法读取目录 {directory}: {exc}") from exc
        for entry in entries:
            path = Path(entry.path)
            is_junction = getattr(entry, "is_junction", None)
            if entry.is_symlink() or (callable(is_junction) and is_junction()):
                raise SystemExit(f"拒绝：目录含 symlink／junction {path}")
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise SystemExit(f"拒绝：无法读取目录项 {path}: {exc}") from exc
            if getattr(info, "st_file_attributes", 0) & getattr(
                stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400
            ):
                raise SystemExit(f"拒绝：目录含 reparse 点 {path}")
            resolved = path.resolve()
            if resolved != trusted and trusted not in resolved.parents:
                raise SystemExit(f"拒绝：目录项解析到受信根之外 {path} -> {resolved}")
            if entry.is_dir(follow_symlinks=False):
                dirs.append(path)
                visit(path)
            elif entry.is_file(follow_symlinks=False):
                files.append(path)
            else:
                raise SystemExit(f"拒绝：目录含特殊文件 {path}")

    visit(trusted)
    return dirs, files


def hash_tree(root: Path) -> list[dict]:
    _, files = _safe_walk_entries(root)
    trusted = root if root.is_absolute() else Path.cwd() / root
    trusted = trusted.resolve()
    entries: list[dict] = []
    for path in sorted(files):
        resolved = path.resolve()
        if trusted not in resolved.parents:
            raise SystemExit(f"拒绝：哈希文件不在受信目录 {path}")
        entries.append(
            {
                "path": resolved.relative_to(trusted).as_posix(),
                "size": resolved.stat().st_size,
                "sha256": _sha256_file(resolved),
            }
        )
    return entries


def tree_digest(entries: list[dict]) -> str:
    """Canonical path+SHA-256 digest used by package-info.frontend_digest.

    The formula is the SHA-256 of compact JSON for a path-sorted list of
    ``{"path": POSIX-relative-path, "sha256": lower64hex}`` objects.  Size is
    deliberately excluded so A and B can share the exact same formula.
    """
    normalized = sorted(
        (
            {"path": str(item["path"]).replace("\\", "/"), "sha256": str(item["sha256"]).lower()}
            for item in entries
        ),
        key=lambda item: item["path"],
    )
    payload = json.dumps(
        normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def product_tree_digest(entries: list[dict]) -> str:
    """Package/frontend tree digest using the same canonical JSON as tree_digest."""
    return tree_digest(entries)


def _is_reparse_point(path: Path) -> bool:
    try:
        info = os.lstat(path)
    except OSError:
        return False
    return bool(stat.S_ISLNK(info.st_mode)) or bool(
        getattr(info, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _has_reparse_component(path: Path) -> bool:
    current = path
    while True:
        if _is_reparse_point(current):
            return True
        parent = current.parent
        if parent == current:
            return False
        current = parent


def validate_write_plan(
    *,
    build_root: Path,
    frontend: Path,
    dist_root: Path,
    work_dir: Path,
    spec_dir: Path,
    hash_out: Path | None,
    source_freeze_out: Path | None,
    frontend_is_input: bool,
    refuse_existing_package: bool = True,
    portable_dir: Path | None = None,
    require_fresh_root: bool = False,
) -> dict:
    """Resolve and reject every unsafe write target before any build step.

    This function is deliberately side-effect free so regression tests and the
    ``--check-paths`` probe can exercise it without creating or deleting files.
    A read-only ``--frontend-dir`` must not overlap any directory this build
    will write (dist/work/spec/portable/package), because PyInstaller cleanup or
    Vite ``--emptyOutDir`` would otherwise mutate the supposedly read-only
    input.  Existing reparse points are rejected rather than followed.
    """
    raw_build_root = build_root
    raw_frontend = frontend
    raw_dist_root = dist_root
    raw_work_dir = work_dir
    raw_spec_dir = spec_dir
    raw_portable_dir = (
        portable_dir if portable_dir is not None else raw_build_root / PORTABLE_DIR_NAME
    )
    raw_hash_out = hash_out
    raw_source_freeze_out = source_freeze_out
    raw_paths: dict[str, Path | None] = {
        "build-root": raw_build_root,
        "frontend": raw_frontend,
        "dist-root": raw_dist_root,
        "work-dir": raw_work_dir,
        "spec-dir": raw_spec_dir,
        "portable-dir": raw_portable_dir,
        "hash-out": raw_hash_out,
        "source-freeze-out": raw_source_freeze_out,
    }
    file_roles = {"hash-out", "source-freeze-out"}
    for label, raw in raw_paths.items():
        if raw is None:
            continue
        if ".." in raw.parts:
            raise SystemExit(f"拒绝 {label}：原始路径含 .. 段 {raw}")
        raw_abs = raw if raw.is_absolute() else Path.cwd() / raw
        if _has_reparse_component(raw_abs):
            raise SystemExit(f"拒绝 {label}：原始路径含 symlink／junction／reparse {raw}")
        if raw_abs.exists():
            if label in file_roles:
                if not raw_abs.is_file():
                    raise SystemExit(f"拒绝 {label}：必须是文件角色 {raw}")
            elif not raw_abs.is_dir():
                raise SystemExit(f"拒绝 {label}：必须是目录角色 {raw}")

    repo = d0_paths.REPO_ROOT.resolve()
    build_parent = (repo / "build").resolve()
    build_root = raw_build_root.resolve()
    frontend = raw_frontend.resolve()
    dist_root = raw_dist_root.resolve()
    work_dir = raw_work_dir.resolve()
    spec_dir = raw_spec_dir.resolve()
    portable_dir = raw_portable_dir.resolve()
    hash_out = raw_hash_out.resolve() if raw_hash_out is not None else None
    source_freeze_out = (
        raw_source_freeze_out.resolve() if raw_source_freeze_out is not None else None
    )

    if build_root.parent != build_parent or not build_root.name.startswith(
        "desktop-e14-"
    ):
        raise SystemExit(
            "拒绝构建根：必须是 "
            f"{build_parent} 下以 desktop-e14- 开头的新目录，实际 {build_root}"
        )
    if require_fresh_root and build_root.exists():
        if not build_root.is_dir():
            raise SystemExit(f"拒绝构建根：现有对象不是目录 {build_root}")
        if any(build_root.iterdir()):
            raise SystemExit(f"拒绝复用非空构建根：{build_root}")
    for root in PROTECTED_BUILD_ROOTS:
        if _overlaps(build_root, root.resolve()):
            raise SystemExit(f"拒绝写入受保护的旧构建根: {build_root} 与 {root} 相交")
    for root in PROTECTED_SOURCE_ROOTS:
        if _overlaps(build_root, root.resolve()):
            raise SystemExit(f"拒绝把构建根放进源码目录: {build_root} 与 {root} 相交")

    write_targets: dict[str, Path] = {
        "dist-root": dist_root,
        "work-dir": work_dir,
        "spec-dir": spec_dir,
        "portable-dir": portable_dir,
    }
    if not frontend_is_input:
        write_targets["frontend"] = frontend
    for label, target in write_targets.items():
        if target == build_root or build_root not in target.parents:
            raise SystemExit(
                f"拒绝 {label}：必须位于本次独立构建根内部，实际 {target}"
            )
        if _has_reparse_component(target):
            raise SystemExit(f"拒绝 {label}：路径含 symlink／junction／reparse 别名 {target}")

    package_root = dist_root / APP_NAME
    if package_root == build_root or build_root not in package_root.parents:
        raise SystemExit(f"拒绝包输出目录：{package_root} 不在 {build_root} 内")
    write_pairs: list[tuple[str, Path]] = [
        ("dist-root", dist_root),
        ("work-dir", work_dir),
        ("spec-dir", spec_dir),
        ("portable-dir", portable_dir),
    ]
    if not frontend_is_input:
        write_pairs.append(("frontend", frontend))
    for index, (left_label, left) in enumerate(write_pairs):
        for right_label, right in write_pairs[index + 1 :]:
            if _overlaps(left, right):
                raise SystemExit(
                    f"拒绝写入目录相交：{left_label} 与 {right_label} ({left} / {right})"
                )
    for label, target in (
        ("dist-root", dist_root),
        ("work-dir", work_dir),
        ("spec-dir", spec_dir),
        ("frontend", frontend),
        ("package-root", package_root),
    ):
        if _overlaps(portable_dir, target):
            raise SystemExit(
                f"拒绝 portable-dir：不得与 {label} 相交 ({portable_dir} / {target})"
            )
    package_exists = package_root.exists()
    if refuse_existing_package and package_exists:
        raise SystemExit(
            f"拒绝覆盖既有候选包：{package_root} 已存在；请使用新的独立构建根"
        )
    portable_exists = portable_dir.exists()
    if portable_exists and not portable_dir.is_dir():
        raise SystemExit(f"拒绝 portable-dir：现有对象不是目录 {portable_dir}")
    if portable_exists and any(portable_dir.iterdir()):
        raise SystemExit(f"拒绝复用非空 portable-dir：{portable_dir}")

    if frontend_is_input:
        read_only_targets = {
            **write_targets,
            "package-root": package_root,
        }
        for label, target in read_only_targets.items():
            if _overlaps(frontend, target):
                raise SystemExit(
                    "拒绝只读 --frontend-dir：不得与本次实际写入目录相交 "
                    f"({frontend} 与 {label}: {target})"
                )

    external: dict[str, Path] = {}
    if hash_out is not None:
        external["hash-out"] = hash_out
    if source_freeze_out is not None:
        external["source-freeze-out"] = source_freeze_out
    if hash_out is not None and source_freeze_out is not None:
        if _overlaps(hash_out, source_freeze_out):
            raise SystemExit("拒绝：--hash-out 与 --source-freeze-out 不能别名或互相包含")
    for label, target in external.items():
        if _overlaps(target, repo):
            raise SystemExit(
                f"拒绝 {label}：不得写入仓库、仓库祖先或仓库内部，实际 {target}"
            )
        if _overlaps(target, build_root):
            raise SystemExit(f"拒绝 {label}：不得写入本次构建根，实际 {target}")
        if target.exists():
            raise SystemExit(f"拒绝 {label}：输出已存在，不得覆盖 {target}")
        if target.is_dir():
            raise SystemExit(f"拒绝 {label}：输出必须是文件路径 {target}")
        if _has_reparse_component(target):
            raise SystemExit(f"拒绝 {label}：路径含 reparse 别名 {target}")
        parent = target.parent
        if parent.exists() and not parent.is_dir():
            raise SystemExit(f"拒绝 {label}：父路径不是目录 {parent}")
        for root in PROTECTED_BUILD_ROOTS + PROTECTED_SOURCE_ROOTS:
            if _overlaps(target, root.resolve()):
                raise SystemExit(
                    f"拒绝 {label}：与受保护路径相交 {target} / {root}"
                )

    return {
        "repo": str(repo),
        "build_root": str(build_root),
        "frontend": str(frontend),
        "frontend_is_input": frontend_is_input,
        "dist_root": str(dist_root),
        "package_root": str(package_root),
        "package_exists": package_exists,
        "portable_dir": str(portable_dir),
        "portable_exists": portable_exists,
        "work_dir": str(work_dir),
        "spec_dir": str(spec_dir),
        "hash_out": str(hash_out) if hash_out else None,
        "source_freeze_out": str(source_freeze_out) if source_freeze_out else None,
        "fresh_root_required": require_fresh_root,
        "reparse_checked": True,
    }


def build_frontend(frontend_out: Path) -> None:
    if not frontend_out.is_absolute():
        raise SystemExit(f"拒绝：Vite 输出必须是绝对路径 {frontend_out}")
    frontend_out = frontend_out.resolve()
    frontend_root = d0_paths.REPO_ROOT / "frontend"
    node = resolve_node_tool("node")
    vite_js = frontend_root / "node_modules" / "vite" / "bin" / "vite.js"
    if not node:
        raise SystemExit("未找到 node：请确保 Node.js 在 PATH 中。")
    if not vite_js.is_file():
        raise SystemExit("未找到本地 Vite CLI（不安装依赖）")
    print("== E14 frontend build (local Vite, no install) ==")
    subprocess.run(
        [
            *node,
            str(vite_js),
            "build",
            "--config",
            "vite.d1.config.ts",
            "--outDir",
            str(frontend_out),
            "--emptyOutDir",
        ],
        cwd=frontend_root,
        check=True,
        shell=False,
    )
    if not (frontend_out / "d1.html").is_file():
        raise SystemExit(f"E14 frontend output missing: {frontend_out}")


def sqlalchemy_compiled_extensions(package_root: Path) -> list[str]:
    """Return packaged SQLAlchemy optional/compiled-extension paths (must be empty)."""
    base = package_root / "_internal" / "sqlalchemy"
    if not base.is_dir():
        return []
    return sorted(
        path.relative_to(package_root).as_posix()
        for path in base.rglob("*")
        if path.is_file()
        and (
            "cyextension" in path.relative_to(base).parts
            or path.suffix.lower() in SQLALCHEMY_COMPILED_SUFFIXES
        )
    )


def require_no_sqlalchemy_cyextension(package_root: Path) -> None:
    offending = sqlalchemy_compiled_extensions(package_root)
    if offending:
        raise SystemExit(
            "拒绝构建：SQLAlchemy 可选编译扩展必须使用纯 Python 回退，"
            f"但包内仍存在 {offending}"
        )


def build_package(
    dist_root: Path, frontend_dir: Path, work_dir: Path, spec_dir: Path
) -> Path:
    print("== E14 PyInstaller onedir windowed package ==")
    separator = os_sep()
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--windowed",
        "--name",
        APP_NAME,
        "--distpath",
        str(dist_root),
        "--workpath",
        str(work_dir),
        "--specpath",
        str(spec_dir),
        "--paths",
        str(d0_paths.APP_DIR),
        "--paths",
        str(d0_paths.BACKEND_ROOT),
        "--add-data",
        f"{frontend_dir}{separator}frontend",
        "--add-data",
        f"{TEMPLATE_DIR}{separator}app/assets/word_templates",
        "--add-data",
        f"{LISTENING_TEMPLATE_DIR}{separator}app/assets/listening_templates",
        "--add-data",
        f"{ALEMBIC_INI}{separator}.",
        "--add-data",
        f"{MIGRATIONS_DIR}{separator}migrations_local",
        "--collect-submodules",
        "webview",
        "--collect-submodules",
        "uvicorn",
        "--collect-submodules",
        "chinese_calendar",
        "--collect-submodules",
        "PIL",
    ]
    for module in SQLALCHEMY_CYEXTENSION_MODULES:
        command.extend(["--exclude-module", module])
    command += [
        "--hidden-import",
        "chinese_calendar",
        "--hidden-import",
        "sqlalchemy.dialects.sqlite",
        "--hidden-import",
        "sqlalchemy.dialects.sqlite.pysqlite",
        "--hidden-import",
        "cryptography.hazmat.primitives.ciphers.aead",
        "--hidden-import",
        "d1_main",
        "--hidden-import",
        "d2_same_origin",
        "--hidden-import",
        "d1_host_api",
        "--hidden-import",
        "d1_server",
        "--hidden-import",
        "maintenance_host",
        "--hidden-import",
        "maintenance_lifecycle",
        "--hidden-import",
        "app.local.runtime",
        "--hidden-import",
        "app.local.credentials",
        "--hidden-import",
        "app.local.config_tokens",
        "--hidden-import",
        "app.local.backup_barrier",
        "--hidden-import",
        "app.local.backup_format",
        "--hidden-import",
        "app.local.backup_fs",
        "--hidden-import",
        "app.local.backup_snapshot",
        "--hidden-import",
        "app.local.backup_validate",
        "--hidden-import",
        "app.local.backup_zip",
        "--hidden-import",
        "app.local.restore_fs",
        "--hidden-import",
        "app.local.restore_group",
        "--hidden-import",
        "app.local.restore_journal",
        "--hidden-import",
        "app.local.restore_recovery",
        "--hidden-import",
        "app.local.restore_service",
        "--hidden-import",
        "app.local.restore_types",
        "--hidden-import",
        "app.local.weekly_ai_adoption",
        "--hidden-import",
        "app.local.weekly_ai_api",
        "--hidden-import",
        "app.local.weekly_ai_candidates",
        "--hidden-import",
        "app.local.weekly_ai_contracts",
        "--hidden-import",
        "app.local.weekly_ai_inputs",
        "--hidden-import",
        "app.local.weekly_ai_service",
        "--hidden-import",
        "app.local.weekly_ai_sources",
        "--hidden-import",
        "app.local.weekly_materials",
        "--hidden-import",
        "app.local.listening_service",
        "--hidden-import",
        "app.local.listening_templates",
        "--hidden-import",
        "app.local.listening_assets",
        "--hidden-import",
        "app.local.listening_api",
        "--hidden-import",
        "app.local.listening_export_service",
        "--hidden-import",
        "app.local.listening_export_api",
        "--hidden-import",
        "app.local.listening_ai_contracts",
        "--hidden-import",
        "app.local.listening_ai_inputs",
        "--hidden-import",
        "app.local.listening_ai_service",
        "--hidden-import",
        "app.local.listening_ai_adoption",
        "--hidden-import",
        "app.local.listening_ai_api",
        "--hidden-import",
        "app.services.word_export_listening",
        "--hidden-import",
        "app.local.ai_executor",
        "--hidden-import",
        "app.local.ai_worker",
        "--hidden-import",
        "app.local.ai_transport",
        "--hidden-import",
        "app.local.ai_spawn",
        "--hidden-import",
        "app.local.ai_task_service",
        "--hidden-import",
        "app.local.observation_export_service",
        "--hidden-import",
        "app.local.observation_export_api",
        "--hidden-import",
        "app.services.word_export_observation",
        "--hidden-import",
        "PIL._imaging",
        "--hidden-import",
        "PIL._webp",
        "--hidden-import",
        "PIL._avif",
        "--hidden-import",
        "PIL._imagingft",
        "--hidden-import",
        "PIL._imagingcms",
        "--hidden-import",
        "PIL.JpegImagePlugin",
        "--hidden-import",
        "PIL.PngImagePlugin",
        "--hidden-import",
        "PIL.WebPImagePlugin",
        "--hidden-import",
        "PIL.AvifImagePlugin",
        "--hidden-import",
        "PIL.GifImagePlugin",
        "--hidden-import",
        "PIL.BmpImagePlugin",
        "--hidden-import",
        "PIL.TiffImagePlugin",
        str(d0_paths.APP_DIR / "d1_main.py"),
    ]
    subprocess.run(command, check=True, cwd=d0_paths.REPO_ROOT)
    package_root = dist_root / APP_NAME
    executable = package_root / f"{APP_NAME}.exe"
    if not executable.is_file():
        raise SystemExit(f"E14 package output missing: {package_root}")
    require_no_sqlalchemy_cyextension(package_root)
    return package_root


def prune_package_caches(package_root: Path) -> list[str]:
    """Remove Python bytecode caches after validating every nested entry.

    The entire raw root, ancestors and nested tree are validated for reparse
    points and containment before the first deletion.  Cache files are removed
    individually and cache directories are removed bottom-up with ``rmdir``;
    a junction is never followed or recursively deleted.
    """
    dirs, files = _safe_walk_entries(package_root)
    trusted = package_root if package_root.is_absolute() else Path.cwd() / package_root
    trusted = trusted.resolve()
    cache_files = [
        path
        for path in files
        if path.name.lower().endswith((".pyc", ".pyo"))
        or any(part == "__pycache__" for part in path.parts)
    ]
    cache_dirs = [
        path
        for path in dirs
        if path.name == "__pycache__"
        or any(part == "__pycache__" for part in path.parts)
    ]
    # Validate all candidates before the first unlink/rmdir.
    for path in cache_files + cache_dirs:
        resolved = path.resolve()
        if trusted not in resolved.parents:
            raise SystemExit(f"拒绝：缓存路径不在受信包内 {path}")
        if _is_reparse_point(path):
            raise SystemExit(f"拒绝：缓存路径含 reparse 点 {path}")
    removed: list[str] = []
    for path in sorted(cache_files):
        resolved = path.resolve()
        if trusted not in resolved.parents or _is_reparse_point(path):
            raise SystemExit(f"拒绝：缓存文件在删除前失去受信身份 {path}")
        removed.append(resolved.relative_to(trusted).as_posix())
        resolved.unlink()
    for path in sorted(cache_dirs, key=lambda item: len(item.parts), reverse=True):
        resolved = path.resolve()
        if trusted not in resolved.parents or _is_reparse_point(path):
            raise SystemExit(f"拒绝：缓存目录在删除前失去受信身份 {path}")
        try:
            resolved.rmdir()
        except OSError as exc:
            raise SystemExit(f"拒绝：缓存目录非空或无法删除 {path}: {exc}") from exc
    return removed


def require_pillow_license() -> None:
    if not PILLOW_LICENSE.is_file():
        raise SystemExit(
            f"拒绝构建：Pillow {PILLOW_VERSION} 许可证缺失 {PILLOW_LICENSE}"
        )
    if not PILLOW_PLUGIN_DIR.is_dir():
        raise SystemExit(f"拒绝构建：Pillow 插件目录缺失 {PILLOW_PLUGIN_DIR}")


def require_listening_templates() -> None:
    """Require the complete controlled listening-template tree before build."""
    if not LISTENING_TEMPLATE_DIR.is_dir():
        raise SystemExit(f"拒绝构建：缺少倾听模板目录 {LISTENING_TEMPLATE_DIR}")
    if _has_reparse_component(LISTENING_TEMPLATE_DIR):
        raise SystemExit(f"拒绝构建：倾听模板目录含 reparse 别名 {LISTENING_TEMPLATE_DIR}")
    for relative in LISTENING_TEMPLATE_REQUIRED_FILES:
        path = LISTENING_TEMPLATE_DIR / relative
        if not path.is_file() or _has_reparse_component(path):
            raise SystemExit(f"拒绝构建：倾听模板文件缺失或不可读 {path}")


def install_package_metadata(
    package_root: Path,
    build_id: str,
    freeze_digest: str,
    pruned_cache_files: int = 0,
    *,
    frontend_digest: str = "",
    frontend_file_count: int = 0,
    source_commit: str = "",
    release_version: str | None = None,
    release_channel: str | None = None,
    migration_files: list[str] | None = None,
    migration_head: str | None = None,
) -> dict:
    internal = package_root / "_internal"
    if not internal.is_dir():
        raise SystemExit(f"拒绝：包内缺少 _internal 目录 {package_root}")
    try:
        version, channel = resolve_release_identity(
            release_version, release_channel
        )
    except ValueError as exc:
        raise SystemExit(f"拒绝：发布身份不合法 {exc}") from exc
    try:
        chain = discover_migration_chain(MIGRATIONS_DIR)
        expected_files = source_migration_files(MIGRATIONS_DIR)
        expected_head = str(chain["head_revision"])
    except ValueError as exc:
        raise SystemExit(f"拒绝：迁移链不合法 {exc}") from exc
    if migration_files is None:
        migration_files = expected_files
    elif migration_files != expected_files:
        raise SystemExit("拒绝：迁移文件清单与源码不一致")
    if migration_head is None:
        migration_head = expected_head
    elif migration_head != expected_head:
        raise SystemExit("拒绝：迁移头与源码不一致")

    # R03: a missing licence must fail the build, never become a false
    # ``pillow_license_included=false`` in a package advertised as complete.
    require_pillow_license()
    license_dir = package_root / "licenses"
    license_dir.mkdir(parents=True, exist_ok=True)
    license_target = license_dir / "Pillow-LICENSE.txt"
    shutil.copyfile(PILLOW_LICENSE, license_target)
    license_hash = _sha256_file(license_target)
    if license_hash != _sha256_file(PILLOW_LICENSE):
        raise SystemExit("拒绝：复制后的 Pillow 许可证与来源不一致")

    bundled_plugins = {
        path.name
        for path in (internal / "PIL").glob("_*.cp314-win_amd64.pyd")
        if path.is_file()
    }
    missing_plugins = sorted(set(PILLOW_REQUIRED_PLUGINS) - bundled_plugins)
    if missing_plugins:
        raise SystemExit(f"拒绝：包内缺少 Pillow 插件 {missing_plugins}")

    identity = update_identity.AppIdentity(
        app_id=update_identity.APP_ID,
        app_name=update_identity.APP_NAME,
        channel=channel,
        version=version,
        build_id=build_id,
        package_format=update_identity.PACKAGE_FORMAT,
        platform=update_identity.PLATFORM,
        arch=update_identity.ARCH,
        python=update_identity.PYTHON_VERSION,
        database_revision=migration_head,
    )
    identity_path = internal / "build_identity.json"
    identity_path.write_text(
        json.dumps(identity.as_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    loaded = update_identity.load_app_identity(
        database_revision=migration_head,
        path=identity_path,
        require_packaged=True,
    )
    if loaded != identity:
        raise SystemExit("拒绝：写入后的 build_identity.json 无法通过 AppIdentity 校验")

    info = {
        "app": APP_NAME,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "package": APP_NAME,
        "version": identity.version,
        "channel": identity.channel,
        "build_id": identity.build_id,
        "database_revision": identity.database_revision,
        "build_identity": str(identity_path.relative_to(package_root)),
        "source_freeze_digest": freeze_digest,
        "source_commit": source_commit,
        "unsigned_internal_test": True,
        "frontend_digest": frontend_digest,
        "frontend_file_count": int(frontend_file_count),
        "pillow_version": PILLOW_VERSION,
        "pillow_license_included": True,
        "pillow_license_sha256": license_hash,
        "pillow_plugins": sorted(bundled_plugins),
        "cache_files_pruned": pruned_cache_files,
        "migrations": migration_files,
        "templates": sorted(path.name for path in TEMPLATE_DIR.glob("*.docx")),
        "listening_templates": sorted(
            path.relative_to(LISTENING_TEMPLATE_DIR).as_posix()
            for path in LISTENING_TEMPLATE_DIR.rglob("*")
            if path.is_file()
        ),
    }
    (package_root / "package-info.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return info


def _validate_manifest_entries(entries: list[dict]) -> list[dict]:
    if not entries:
        raise SystemExit("拒绝：产品清单为空")
    seen: set[str] = set()
    normalized: list[dict] = []
    for item in entries:
        if set(item) != {"path", "size", "sha256"}:
            raise SystemExit(f"拒绝：产品清单条目字段不合法 {item!r}")
        path = str(item["path"])
        if not path or path.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", path):
            raise SystemExit(f"拒绝：产品清单含绝对路径 {path!r}")
        if "\\" in path:
            raise SystemExit(f"拒绝：产品清单路径必须使用 POSIX 分隔符 {path!r}")
        parts = path.split("/")
        if any(part in ("", ".", "..") for part in parts):
            raise SystemExit(f"拒绝：产品清单路径含空段／.／.. {path!r}")
        if path in seen:
            raise SystemExit(f"拒绝：产品清单路径重复 {path!r}")
        size = item["size"]
        if type(size) is not int or size < 0:
            raise SystemExit(f"拒绝：产品清单 size 不是非负整数 {path!r}")
        sha = str(item["sha256"])
        if not re.fullmatch(r"[0-9a-f]{64}", sha):
            raise SystemExit(f"拒绝：产品清单 sha256 不是小写 64 hex {path!r}")
        seen.add(path)
        normalized.append({"path": path, "size": size, "sha256": sha})
    normalized.sort(key=lambda item: item["path"])
    return normalized


def build_manifest_payload(package_root: Path, package_info: dict) -> dict:
    entries = _validate_manifest_entries(hash_tree(package_root))
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "package": PRODUCT_NAME,
        "build_id": str(package_info["build_id"]),
        "database_revision": str(package_info["database_revision"]),
        "source_freeze_digest": str(package_info["source_freeze_digest"]),
        "generated_at": str(package_info["built_at"]),
        "files": entries,
    }


def _write_text_exclusive(path: Path, text: str) -> None:
    with path.open("x", encoding="utf-8", newline=chr(10)) as handle:
        handle.write(text)


def _basename_only(label: str, value: str) -> str:
    if not value or value in (".", ".."):
        raise SystemExit(f"拒绝 {label}：空名称或点名称")
    if (
        "/" in value
        or "\\" in value
        or re.match(r"^[A-Za-z]:", value)
        or Path(value).is_absolute()
        or Path(value).name != value
    ):
        raise SystemExit(f"拒绝 {label}：只允许单层 basename，实际 {value!r}")
    return value


def write_portable_readme(path: Path, package_info: dict) -> None:
    text = f"""KGNext-E14 Windows 11 内部测试候选

身份
- 版本：{package_info.get("version", "0.1.0")}
- 渠道：{package_info.get("channel", "stable")}
- build_id：{package_info.get("build_id", "")}
- 数据库 revision：{package_info.get("database_revision", "")}
- 构建基线：{package_info.get("source_commit", "")}
- 包内前端摘要：{package_info.get("frontend_digest", "")}
- package-info.json 的 package 字段为相对值 {PRODUCT_NAME}。

性质
- 未签名内部测试候选，不是正式发行、已签名包或教师体验通过。
- 不含教师数据库、备份、DPAPI／密钥、原照片、日志、EVIDENCE 或构建机私有 freeze。

使用
- 解压完整目录，不要只复制主 EXE。
- 用 SHA256SUMS.txt 核对产品文件、README 和 package-files.json。
- 需要 Windows 11 x64 与 WebView2 Runtime；用普通权限启动 KGNext-E14.exe。
- 先使用显式新合成 data／credential 根测试，不碰已有真实资料。
- 备份／恢复、保护包再恢复、新进程接续、原生保存和 Word 需按本轮手动清单逐项验收。

未验
- 目标机实际运行、Word 逐页人工检查、真实 AI、WebDAV、签名和发行未验。
"""
    _write_text_exclusive(path, text)


def write_portable_sums(
    path: Path,
    package_root: Path,
    readme_path: Path,
    manifest_path: Path,
) -> None:
    entries: dict[str, str] = {}
    for item in hash_tree(package_root):
        entries[f"{PRODUCT_NAME}/{item['path']}"] = item["sha256"]
    entries[readme_path.name] = _sha256_file(readme_path)
    entries[manifest_path.name] = _sha256_file(manifest_path)
    lines = "".join(
        f"{entries[name]}  {name}" + chr(10) for name in sorted(entries)
    )
    _write_text_exclusive(path, lines)


def write_portable_archive(
    package_root: Path,
    portable_dir: Path,
    package_info: dict,
    *,
    archive_name: str = ARCHIVE_NAME,
    readme_name: str = README_NAME,
    manifest_name: str = MANIFEST_NAME,
    sums_name: str = SUMS_NAME,
) -> dict:
    """Write the deterministic outer README/manifest/sums/ZIP layout.

    All raw paths, roles, basenames, existing outputs and reparse points are
    validated before the first write.  The ZIP contains only file entries,
    sorted by archive name, with fixed timestamps; it is created exclusively.
    """
    raw_package_root = package_root
    raw_portable_dir = portable_dir
    for label, raw in (
        ("package-root", raw_package_root),
        ("portable-dir", raw_portable_dir),
    ):
        if ".." in raw.parts:
            raise SystemExit(f"拒绝 {label}：原始路径含 .. 段 {raw}")
        raw_abs = raw if raw.is_absolute() else Path.cwd() / raw
        if _has_reparse_component(raw_abs):
            raise SystemExit(f"拒绝 {label}：原始路径含 symlink／junction／reparse {raw}")
    if not raw_package_root.is_dir():
        raise SystemExit(f"拒绝 package-root：必须是现有目录 {raw_package_root}")
    if raw_portable_dir.exists() and not raw_portable_dir.is_dir():
        raise SystemExit(f"拒绝 portable-dir：现有对象不是目录 {raw_portable_dir}")
    package_root = raw_package_root.resolve()
    portable_dir = raw_portable_dir.resolve()
    if _overlaps(package_root, portable_dir):
        raise SystemExit(
            f"拒绝：portable-dir 不得与 package-root 相交 ({portable_dir} / {package_root})"
        )
    if package_root.name != PRODUCT_NAME:
        raise SystemExit(f"拒绝：产品目录名必须是 {PRODUCT_NAME}，实际 {package_root.name}")
    names = {
        "archive": _basename_only("archive-name", archive_name),
        "readme": _basename_only("readme-name", readme_name),
        "manifest": _basename_only("manifest-name", manifest_name),
        "sums": _basename_only("sums-name", sums_name),
    }
    if len(set(names.values())) != 4:
        raise SystemExit(f"拒绝：README／manifest／sums／archive 名称必须互不相同 {names}")
    readme_path = portable_dir / names["readme"]
    manifest_path = portable_dir / names["manifest"]
    sums_path = portable_dir / names["sums"]
    archive_path = portable_dir / names["archive"]
    for existing in (readme_path, manifest_path, sums_path, archive_path):
        if existing.exists():
            raise SystemExit(f"拒绝：便携输出已存在 {existing}")
    if portable_dir.exists() and any(portable_dir.iterdir()):
        raise SystemExit(f"拒绝复用非空 portable-dir：{portable_dir}")
    portable_dir.mkdir(parents=True, exist_ok=True)
    write_portable_readme(readme_path, package_info)
    manifest = build_manifest_payload(package_root, package_info)
    _write_text_exclusive(
        manifest_path,
        json.dumps(manifest, ensure_ascii=False, indent=2) + chr(10),
    )
    write_portable_sums(sums_path, package_root, readme_path, manifest_path)

    product_entries = [
        (f"{PRODUCT_NAME}/{item['path']}", package_root / item["path"])
        for item in hash_tree(package_root)
    ]
    outer_entries = [
        (names["readme"], readme_path),
        (names["manifest"], manifest_path),
        (names["sums"], sums_path),
    ]
    all_entries = sorted(product_entries + outer_entries, key=lambda item: item[0])
    with zipfile.ZipFile(
        archive_path,
        "x",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6,
    ) as archive:
        for archive_name_value, source in all_entries:
            info = zipfile.ZipInfo(
                archive_name_value,
                date_time=(1980, 1, 1, 0, 0, 0),
            )
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 0
            info.external_attr = 0o100644 << 16
            archive.writestr(
                info,
                source.read_bytes(),
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=6,
            )
    return {
        "archive_path": str(archive_path),
        "archive_name": names["archive"],
        "archive_sha256": _sha256_file(archive_path),
        "archive_bytes": archive_path.stat().st_size,
        "readme_path": str(readme_path),
        "manifest_path": str(manifest_path),
        "manifest_sha256": _sha256_file(manifest_path),
        "sums_path": str(sums_path),
        "sums_sha256": _sha256_file(sums_path),
        "product_file_count": len(product_entries),
        "product_bytes": sum(source.stat().st_size for _, source in product_entries),
        "product_tree_sha256": product_tree_digest(hash_tree(package_root)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the E14 complete desktop package")
    parser.add_argument("--skip-frontend", action="store_true")
    parser.add_argument("--frontend-dir", help="read-only frontend build input")
    parser.add_argument("--build-root", help="independent build root")
    parser.add_argument("--dist-root", help="package output parent")
    parser.add_argument(
        "--portable-dir",
        help="portable README/manifest/SHA/ZIP output directory inside the build root",
    )
    parser.add_argument("--hash-out", help="package file SHA256 JSON")
    parser.add_argument("--source-freeze-out", help="source freeze JSON")
    parser.add_argument(
        "--version",
        help="explicit full release version (stable X.Y.Z or preview X.Y.Z-listening-test.N)",
    )
    parser.add_argument(
        "--channel",
        choices=("stable", "preview"),
        help="explicit release channel; must be supplied together with --version",
    )
    parser.add_argument(
        "--check-paths",
        action="store_true",
        help="validate all write targets and exit without building or writing",
    )
    args = parser.parse_args()

    try:
        release_version, release_channel = resolve_release_identity(
            args.version, args.channel
        )
        migration_chain = discover_migration_chain(MIGRATIONS_DIR)
        migration_files = source_migration_files(MIGRATIONS_DIR)
    except ValueError as exc:
        print(f"拒绝：发布身份或迁移链不合法 {exc}", file=sys.stderr)
        return 2
    migration_head = str(migration_chain["head_revision"])

    raw_build_root = Path(args.build_root) if args.build_root else BUILD_ROOT
    raw_frontend = (
        Path(args.frontend_dir)
        if args.frontend_dir
        else raw_build_root / "frontend"
    )
    raw_dist_root = (
        Path(args.dist_root)
        if args.dist_root
        else raw_build_root / "package"
    )
    raw_portable_dir = (
        Path(args.portable_dir)
        if args.portable_dir
        else raw_build_root / PORTABLE_DIR_NAME
    )
    raw_work_dir = raw_build_root / "pyinstaller-work"
    raw_spec_dir = raw_build_root / "spec"
    raw_hash_out = Path(args.hash_out) if args.hash_out else None
    raw_source_freeze_out = (
        Path(args.source_freeze_out) if args.source_freeze_out else None
    )
    plan = validate_write_plan(
        build_root=raw_build_root,
        frontend=raw_frontend,
        dist_root=raw_dist_root,
        work_dir=raw_work_dir,
        spec_dir=raw_spec_dir,
        hash_out=raw_hash_out,
        source_freeze_out=raw_source_freeze_out,
        frontend_is_input=bool(args.frontend_dir),
        refuse_existing_package=not args.check_paths,
        portable_dir=raw_portable_dir,
        require_fresh_root=True,
    )
    if args.check_paths:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    build_root = Path(plan["build_root"])
    frontend = Path(plan["frontend"])
    dist_root = Path(plan["dist_root"])
    portable_dir = Path(plan["portable_dir"])
    work_dir = Path(plan["work_dir"])
    spec_dir = Path(plan["spec_dir"])
    hash_out = Path(plan["hash_out"]) if plan["hash_out"] else None
    source_freeze_out = (
        Path(plan["source_freeze_out"]) if plan["source_freeze_out"] else None
    )

    require_pillow_license()
    if not ALEMBIC_INI.is_file():
        raise SystemExit(f"拒绝构建：缺少本地 Alembic 配置 {ALEMBIC_INI}")
    if not TEMPLATE_DIR.is_dir():
        raise SystemExit(f"拒绝构建：缺少 Word 模板目录 {TEMPLATE_DIR}")
    require_listening_templates()

    # The first freeze must cover the *entire* write chain, including Vite and
    # PyInstaller. It therefore runs before any frontend output is touched.
    before = source_freeze()

    if args.frontend_dir:
        if not (frontend / "d1.html").is_file():
            raise SystemExit(f"缺少前端构建: {frontend}")
    elif args.skip_frontend:
        if not (frontend / "d1.html").is_file():
            raise SystemExit(f"缺少前端构建: {frontend}")
    else:
        if frontend.exists() and any(frontend.iterdir()):
            raise SystemExit(f"拒绝复用非空 Vite 输出: {frontend}")
        build_frontend(frontend)

    package_root = build_package(
        dist_root.resolve(), frontend.resolve(), work_dir.resolve(), spec_dir.resolve()
    )
    pruned = prune_package_caches(package_root)
    build_id = str(uuid.uuid4())
    portable_requested = bool(args.portable_dir)
    frontend_digest = ""
    frontend_file_count = 0
    portable = None
    if portable_requested:
        frontend_entries = hash_tree(frontend.resolve())
        frontend_digest = tree_digest(frontend_entries)
        frontend_file_count = len(frontend_entries)
        info = install_package_metadata(
            package_root,
            build_id,
            before["digest"],
            len(pruned),
            frontend_digest=frontend_digest,
            frontend_file_count=frontend_file_count,
            source_commit=before["commit"],
            release_version=release_version,
            release_channel=release_channel,
            migration_files=migration_files,
            migration_head=migration_head,
        )
        portable = write_portable_archive(package_root, portable_dir, info)
    else:
        # Keep the historical 4-argument call/CLI behavior when no portable
        # output is requested.  The authorized portable build always passes
        # --portable-dir explicitly.
        info = install_package_metadata(
            package_root,
            build_id,
            before["digest"],
            len(pruned),
            release_version=release_version,
            release_channel=release_channel,
            migration_files=migration_files,
            migration_head=migration_head,
        )

    # The second freeze covers the entire write chain, including the portable
    # archive.  It must match the pre-Vite snapshot exactly.
    after = source_freeze()
    changes = _freeze_changes(before, after)
    freeze_report = {
        "commit": before["commit"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "before": before,
        "after": after,
        "changes": changes,
        "stable": changes["stable"],
        "build_id": info["build_id"],
        "version": info["version"],
        "channel": info.get("channel", release_channel),
        "database_revision": info["database_revision"],
        "private_only": True,
        "package_included": False,
    }
    if portable is not None:
        freeze_report.update(
            {
                "frontend_input_digest": tree_digest(
                    [
                        item
                        for item in before["files"]
                        if item["path"].startswith("frontend/")
                    ]
                ),
                "frontend_output_digest": frontend_digest,
                "frontend_file_count": frontend_file_count,
                "package_tree_digest": portable["product_tree_sha256"],
                "manifest_sha256": portable["manifest_sha256"],
                "sums_sha256": portable["sums_sha256"],
                "archive_sha256": portable["archive_sha256"],
                "archive_bytes": portable["archive_bytes"],
            }
        )
    if source_freeze_out is not None:
        source_freeze_out.parent.mkdir(parents=True, exist_ok=True)
        source_freeze_out.write_text(
            json.dumps(freeze_report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    if not changes["stable"]:
        raise SystemExit(
            "拒绝：构建前后产品/构建源码不一致 "
            f"changed={changes['changed']} added={changes['added']} removed={changes['removed']}"
        )

    if hash_out is not None:
        hash_out.parent.mkdir(parents=True, exist_ok=True)
        hash_payload = {
            "package": APP_NAME,
            "build_id": info["build_id"],
            "version": info["version"],
            "channel": info.get("channel", release_channel),
            "database_revision": info["database_revision"],
            "source_freeze_digest": before["digest"],
            "files": hash_tree(package_root),
        }
        if portable is not None:
            hash_payload.update(
                {
                    "frontend_digest": frontend_digest,
                    "frontend_file_count": frontend_file_count,
                    "manifest_sha256": portable["manifest_sha256"],
                    "sums_sha256": portable["sums_sha256"],
                    "archive_sha256": portable["archive_sha256"],
                    "archive_bytes": portable["archive_bytes"],
                    "product_tree_sha256": portable["product_tree_sha256"],
                }
            )
        hash_out.write_text(
            json.dumps(hash_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    output = {
        "package": str(package_root),
        "build_id": info["build_id"],
        "version": info["version"],
        "channel": info.get("channel", release_channel),
        "database_revision": info["database_revision"],
        "source_freeze_digest": before["digest"],
        "source_freeze_stable": True,
    }
    if portable is not None:
        output.update(
            {
                "portable_dir": str(portable_dir),
                "archive": portable["archive_path"],
                "archive_sha256": portable["archive_sha256"],
                "frontend_digest": frontend_digest,
                "frontend_file_count": frontend_file_count,
            }
        )
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
