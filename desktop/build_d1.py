"""D1 build orchestration (Windows-only helper).

Steps:
1. build the D1 frontend entry into ``build/desktop-d1/frontend`` via
   ``vite.d1.config.ts`` (separate from the D0 probe and legacy outputs);
2. produce the PyInstaller **onedir** verification package in
   ``build/desktop-d1/package/KGNext-D1Verify/`` bundling the real D1
   frontend, the controlled Word templates, the local Alembic INI and the
   local migration scripts so ``app.local.migrate`` resolves its resources
   inside the package.

The build never runs from a spec file stored in the source tree; the
temporary spec lands in the build workpath. The D0 builder and D0 package
are untouched.
"""

from __future__ import annotations

import argparse
import json
import hashlib
import os
import subprocess
import sys
from pathlib import Path

import d0_paths
from build_d0 import resolve_node_tool

BUILD_ROOT = d0_paths.REPO_ROOT / "build" / "desktop-d1"
FRONTEND_DIR = BUILD_ROOT / "frontend"
PACKAGE_DIR = BUILD_ROOT / "package"
WORK_DIR = BUILD_ROOT / "pyinstaller-work"
SPEC_DIR = BUILD_ROOT / "spec"

TEMPLATE_DIR = d0_paths.BACKEND_ROOT / "app" / "assets" / "word_templates"
ALEMBIC_INI = d0_paths.BACKEND_ROOT / "alembic-local.ini"
MIGRATIONS_DIR = d0_paths.BACKEND_ROOT / "migrations_local"

APP_NAME = "KGNext-D1Verify"


def os_sep() -> str:
    return ";" if sys.platform.startswith("win") else ":"


def build_frontend() -> None:
    frontend_root = d0_paths.REPO_ROOT / "frontend"
    npm = resolve_node_tool("npm")
    npx = resolve_node_tool("npx")
    if not npm or not npx:
        raise SystemExit(
            "未找到 npm/npx：请安装 Node.js 并确保其在 PATH 中；"
            "或先手工构建 D1 前端后使用 --skip-frontend。"
        )
    print(f"== D1 frontend build (npm={npm[-1]}) ==")
    subprocess.run(
        [*npm, "ci", "--no-audit", "--no-fund"],
        cwd=frontend_root,
        check=True,
        shell=False,
    )
    subprocess.run(
        [*npx, "vite", "build", "--config", "vite.d1.config.ts"],
        cwd=frontend_root,
        check=True,
        shell=False,
    )
    if not (FRONTEND_DIR / "d1.html").is_file():
        raise SystemExit(f"D1 前端构建输出异常：{FRONTEND_DIR}")


def build_package(dist_root: Path) -> Path:
    print("== D1 PyInstaller onedir package ==")
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
        str(WORK_DIR),
        "--specpath",
        str(SPEC_DIR),
        "--paths",
        str(d0_paths.APP_DIR),
        "--paths",
        str(d0_paths.BACKEND_ROOT),
        "--add-data",
        f"{FRONTEND_DIR}{separator}frontend",
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
        "--hidden-import",
        "chinese_calendar",
        "--hidden-import",
        "sqlalchemy.dialects.sqlite",
        "--hidden-import",
        "sqlalchemy.dialects.sqlite.pysqlite",
        str(d0_paths.APP_DIR / "d1_main.py"),
    ]
    subprocess.run(command, check=True, cwd=d0_paths.REPO_ROOT)
    package_root = dist_root / APP_NAME
    executable = package_root / f"{APP_NAME}.exe"
    if not executable.is_file():
        raise SystemExit(f"打包输出异常：{package_root}")
    return package_root


def hash_tree(root: Path) -> list[dict]:
    entries: list[dict] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        entries.append(
            {
                "path": str(path.relative_to(root)),
                "size": path.stat().st_size,
                "sha256": digest.hexdigest(),
            }
        )
    return entries


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the D1 desktop verification package")
    parser.add_argument(
        "--skip-frontend",
        action="store_true",
        help="复用已构建的 D1 前端输出，只做打包",
    )
    parser.add_argument(
        "--dist-root",
        help=(
            "打包输出父目录（默认 build/desktop-d1/package）。"
            "当前包仍在使用时用独立目录，不覆盖在用文件"
        ),
    )
    parser.add_argument(
        "--hash-out",
        help="将包内逐文件 SHA256 清单写入该 JSON 文件",
    )
    args = parser.parse_args()
    if not args.skip_frontend:
        build_frontend()
    else:
        if not (FRONTEND_DIR / "d1.html").is_file():
            raise SystemExit("前端构建缺失；请先运行不带 --skip-frontend 的完整构建")
    dist_root = Path(args.dist_root) if args.dist_root else PACKAGE_DIR
    package_root = build_package(dist_root)
    if args.hash_out:
        payload = {
            "package": str(package_root),
            "files": hash_tree(package_root),
        }
        Path(args.hash_out).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"逐文件散列已写入：{args.hash_out}")
    print(f"D1 包输出目录：{package_root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
