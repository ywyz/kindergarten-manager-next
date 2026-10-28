"""Build the E14 complete desktop package (independent root; old packages kept).

The package is a PyInstaller onedir/windowed distribution of the real D1/E14
entry, current frontend build, controlled observation templates, local
migrations (including 0006) and Pillow imaging plugins. It reuses the existing
venv/node_modules and never installs or upgrades dependencies.

Path safety (E14-R01): every write target is resolved and checked *before* any
frontend/package write. The build root must be a fresh direct child of
``<repo>/build`` named ``desktop-e14-*`` (the r01 ``desktop-e14`` root and all
older build roots are protected), and the hash/source-freeze outputs must be
outside the repository and outside every protected source/build root.

Source freeze (E14-R02): product/build sources are hashed both before and after
the build (cache files excluded); the build fails if the two lists differ.

Build identity/licence (E14-R03): the candidate receives a real UUID
``_internal/build_identity.json`` (version 0.1.0, database revision 0006); a
missing Pillow licence or imaging plugin aborts the build instead of producing
a package that claims to be complete.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import d0_paths
import update_identity
from build_d0 import resolve_node_tool

BUILD_ROOT = d0_paths.REPO_ROOT / "build" / "desktop-e14-r03"
APP_NAME = "KGNext-E14"
DATABASE_REVISION = "20261025_0006_local_game_observations"
PILLOW_VERSION = "13.0.0"

TEMPLATE_DIR = d0_paths.BACKEND_ROOT / "app" / "assets" / "word_templates"
ALEMBIC_INI = d0_paths.BACKEND_ROOT / "alembic-local.ini"
MIGRATIONS_DIR = d0_paths.BACKEND_ROOT / "migrations_local"
MIGRATION_FILE = (
    MIGRATIONS_DIR / "versions" / f"{DATABASE_REVISION}.py"
)
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

# Never write into these roots. ``desktop-e14`` and ``desktop-e14-r02`` are
# preserved candidates; ``desktop-e14-r03`` and later suffixed roots are the
# only allowed build-root family.
PROTECTED_BUILD_ROOTS = (
    d0_paths.REPO_ROOT / "build" / "desktop-d1",
    d0_paths.REPO_ROOT / "build" / "desktop-d2",
    d0_paths.REPO_ROOT / "build" / "desktop-d2-manual-ai",
    d0_paths.REPO_ROOT / "build" / "desktop-e14",
    d0_paths.REPO_ROOT / "build" / "desktop-e14-r02",
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
        "desktop/d1_main.py",
        "desktop/d1_host_api.py",
        "desktop/d1_server.py",
        "desktop/d1_paths.py",
        "desktop/d2_same_origin.py",
        "desktop/update_fs.py",
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
        "frontend/vite.d1.config.ts",
        "frontend/package.json",
        "frontend/package-lock.json",
    ),
    "build": (
        "desktop/build_e14.py",
        "desktop/build_d0.py",
        "desktop/verify_e14_package.py",
        "desktop/requirements-d1.lock.txt",
        "desktop/requirements-d1-build-constraints.txt",
    ),
    "verification": (
        "desktop/verify_observation_window.py",
        "desktop/verify_observation_multi.py",
        "desktop/verify_observation_old_upgrade.py",
        "desktop/verify_e14_portable_archive.py",
        "desktop/tests/test_e14_build_guard.py",
    ),
    "resources": ("backend/app/assets/word_templates",),
}
CACHE_PARTS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
CACHE_SUFFIXES = {".pyc", ".pyo"}


def os_sep() -> str:
    return ";" if sys.platform.startswith("win") else ":"


def _overlaps(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _iter_source_files(relative: str) -> list[Path]:
    root = d0_paths.REPO_ROOT / relative
    if not root.exists():
        return []
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
    for group, relatives in SOURCE_GROUPS.items():
        for relative in relatives:
            for path in _iter_source_files(relative):
                rel = str(path.relative_to(d0_paths.REPO_ROOT))
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
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=d0_paths.REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return {
        "commit": commit,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "groups": {name: list(paths) for name, paths in SOURCE_GROUPS.items()},
        "file_count": len(files),
        "digest": _freeze_digest(files),
        "files": files,
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
    return {
        "stable": not changed and not added and not removed,
        "changed": changed,
        "added": added,
        "removed": removed,
    }


def hash_tree(root: Path) -> list[dict]:
    entries: list[dict] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        entries.append(
            {
                "path": str(path.relative_to(root)),
                "size": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    return entries


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
) -> dict:
    """Resolve and reject every unsafe write target before any build step.

    This function is deliberately side-effect free so regression tests and the
    ``--check-paths`` probe can exercise it without creating or deleting files.
    A read-only ``--frontend-dir`` must not overlap any directory this build
    will write (dist/work/spec/package), because PyInstaller cleanup would
    otherwise mutate the supposedly read-only input.
    """
    repo = d0_paths.REPO_ROOT.resolve()
    build_parent = (repo / "build").resolve()
    build_root = build_root.resolve()
    frontend = frontend.resolve()
    dist_root = dist_root.resolve()
    work_dir = work_dir.resolve()
    spec_dir = spec_dir.resolve()
    hash_out = hash_out.resolve() if hash_out is not None else None
    source_freeze_out = (
        source_freeze_out.resolve() if source_freeze_out is not None else None
    )

    if build_root.parent != build_parent or not build_root.name.startswith(
        "desktop-e14-"
    ):
        raise SystemExit(
            "拒绝构建根：必须是 "
            f"{build_parent} 下以 desktop-e14- 开头的新目录，实际 {build_root}"
        )
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
    }
    if not frontend_is_input:
        write_targets["frontend"] = frontend
    for label, target in write_targets.items():
        if target == build_root or build_root not in target.parents:
            raise SystemExit(
                f"拒绝 {label}：必须位于本次独立构建根内部，实际 {target}"
            )
    package_root = dist_root / APP_NAME
    if package_root == build_root or build_root not in package_root.parents:
        raise SystemExit(f"拒绝包输出目录：{package_root} 不在 {build_root} 内")
    package_exists = package_root.exists()
    if refuse_existing_package and package_exists:
        raise SystemExit(
            f"拒绝覆盖既有候选包：{package_root} 已存在；请使用新的独立构建根"
        )

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
        if hash_out == source_freeze_out:
            raise SystemExit("拒绝：--hash-out 与 --source-freeze-out 不能是同一文件")
    for label, target in external.items():
        if _overlaps(target, repo):
            raise SystemExit(
                f"拒绝 {label}：不得写入仓库、仓库祖先或仓库内部，实际 {target}"
            )
        if _overlaps(target, build_root):
            raise SystemExit(f"拒绝 {label}：不得写入本次构建根，实际 {target}")
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
        "work_dir": str(work_dir),
        "spec_dir": str(spec_dir),
        "hash_out": str(hash_out) if hash_out else None,
        "source_freeze_out": str(source_freeze_out) if source_freeze_out else None,
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
    return package_root


def prune_package_caches(package_root: Path) -> list[str]:
    """Remove Python bytecode caches from the packaged data tree.

    ``migrations_local`` is copied as data and may otherwise carry
    ``__pycache__`` files whose embedded ``co_filename`` leaks the build
    machine path. The portable package must not contain them.
    """
    removed: list[str] = []
    for cache_dir in sorted(package_root.rglob("__pycache__")):
        if not cache_dir.is_dir():
            continue
        for path in sorted(cache_dir.rglob("*")):
            if path.is_file():
                removed.append(str(path.relative_to(package_root)))
        shutil.rmtree(cache_dir)
    for path in sorted(package_root.rglob("*.pyc")):
        if path.is_file():
            removed.append(str(path.relative_to(package_root)))
            path.unlink()
    for path in sorted(package_root.rglob("*.pyo")):
        if path.is_file():
            removed.append(str(path.relative_to(package_root)))
            path.unlink()
    return removed


def require_pillow_license() -> None:
    if not PILLOW_LICENSE.is_file():
        raise SystemExit(
            f"拒绝构建：Pillow {PILLOW_VERSION} 许可证缺失 {PILLOW_LICENSE}"
        )
    if not PILLOW_PLUGIN_DIR.is_dir():
        raise SystemExit(f"拒绝构建：Pillow 插件目录缺失 {PILLOW_PLUGIN_DIR}")


def install_package_metadata(
    package_root: Path, build_id: str, freeze_digest: str, pruned_cache_files: int = 0
) -> dict:
    internal = package_root / "_internal"
    if not internal.is_dir():
        raise SystemExit(f"拒绝：包内缺少 _internal 目录 {package_root}")

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
        channel=update_identity.CHANNEL,
        version=update_identity.APP_VERSION,
        build_id=build_id,
        package_format=update_identity.PACKAGE_FORMAT,
        platform=update_identity.PLATFORM,
        arch=update_identity.ARCH,
        python=update_identity.PYTHON_VERSION,
        database_revision=DATABASE_REVISION,
    )
    identity_path = internal / "build_identity.json"
    identity_path.write_text(
        json.dumps(identity.as_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    loaded = update_identity.load_app_identity(
        database_revision=DATABASE_REVISION,
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
        "build_id": identity.build_id,
        "database_revision": identity.database_revision,
        "build_identity": str(identity_path.relative_to(package_root)),
        "source_freeze_digest": freeze_digest,
        "pillow_version": PILLOW_VERSION,
        "pillow_license_included": True,
        "pillow_license_sha256": license_hash,
        "pillow_plugins": sorted(bundled_plugins),
        "cache_files_pruned": pruned_cache_files,
        "migrations": sorted(
            str(path.relative_to(MIGRATIONS_DIR))
            for path in MIGRATIONS_DIR.rglob("*.py")
            if path.is_file() and "__pycache__" not in path.parts
        ),
        "templates": sorted(path.name for path in TEMPLATE_DIR.glob("*.docx")),
    }
    (package_root / "package-info.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return info


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the E14 complete desktop package")
    parser.add_argument("--skip-frontend", action="store_true")
    parser.add_argument("--frontend-dir", help="read-only frontend build input")
    parser.add_argument("--build-root", help="independent build root")
    parser.add_argument("--dist-root", help="package output parent")
    parser.add_argument("--hash-out", help="package file SHA256 JSON")
    parser.add_argument("--source-freeze-out", help="source freeze JSON")
    parser.add_argument(
        "--check-paths",
        action="store_true",
        help="validate all write targets and exit without building or writing",
    )
    args = parser.parse_args()

    build_root = (
        Path(args.build_root) if args.build_root else BUILD_ROOT
    ).resolve()
    frontend = (
        Path(args.frontend_dir) if args.frontend_dir else build_root / "frontend"
    ).resolve()
    dist_root = (
        Path(args.dist_root) if args.dist_root else build_root / "package"
    ).resolve()
    work_dir = (build_root / "pyinstaller-work").resolve()
    spec_dir = (build_root / "spec").resolve()
    hash_out = Path(args.hash_out).resolve() if args.hash_out else None
    source_freeze_out = (
        Path(args.source_freeze_out).resolve() if args.source_freeze_out else None
    )
    plan = validate_write_plan(
        build_root=build_root,
        frontend=frontend,
        dist_root=dist_root,
        work_dir=work_dir,
        spec_dir=spec_dir,
        hash_out=hash_out,
        source_freeze_out=source_freeze_out,
        frontend_is_input=bool(args.frontend_dir),
        refuse_existing_package=not args.check_paths,
    )
    if args.check_paths:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0

    require_pillow_license()
    if not MIGRATION_FILE.is_file():
        raise SystemExit(f"拒绝构建：缺少 0006 迁移 {MIGRATION_FILE}")
    if not ALEMBIC_INI.is_file():
        raise SystemExit(f"拒绝构建：缺少本地 Alembic 配置 {ALEMBIC_INI}")
    if not TEMPLATE_DIR.is_dir():
        raise SystemExit(f"拒绝构建：缺少 Word 模板目录 {TEMPLATE_DIR}")

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
        build_frontend(frontend)

    package_root = build_package(
        dist_root.resolve(), frontend.resolve(), work_dir.resolve(), spec_dir.resolve()
    )
    pruned = prune_package_caches(package_root)
    build_id = str(uuid.uuid4())
    info = install_package_metadata(
        package_root, build_id, before["digest"], len(pruned)
    )
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
    }
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
        hash_out.write_text(
            json.dumps(
                {
                    "package": APP_NAME,
                    "build_id": info["build_id"],
                    "source_freeze_digest": before["digest"],
                    "files": hash_tree(package_root),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    print(json.dumps(
        {
            "package": str(package_root),
            "build_id": info["build_id"],
            "version": info["version"],
            "database_revision": info["database_revision"],
            "source_freeze_digest": before["digest"],
            "source_freeze_stable": True,
        },
        ensure_ascii=False,
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
