"""D2 W6 full desktop package build (Windows-only helper).

Produces the **complete** D2 onedir verification package
``build/desktop-d2/package/KGNext-D2Verify/`` (real WebView2 window + local API +
SQLite + AI executor + Word export), bundling:

* the real D2 frontend build (``vite.d1.config.ts`` → ``build/desktop-d2/frontend``),
* the controlled Word templates,
* the local Alembic INI and the frozen ``migrations_local`` (0001–0004),
* ``cryptography`` (DPAPI/AES-GCM), ``chinese_calendar`` and the host modules.

This entry **never** runs ``npm ci``/``npm install`` (the existing
``frontend/node_modules`` is reused; W6 authorization forbids installing or
upgrading dependencies) and it never touches the D1/D0/W3 build outputs. The
temporary PyInstaller spec lands in the build workpath, not the source tree.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import d0_paths
from build_d0 import resolve_node_tool

BUILD_ROOT = d0_paths.REPO_ROOT / "build" / "desktop-d2"
FRONTEND_DIR = BUILD_ROOT / "frontend"
PACKAGE_DIR = BUILD_ROOT / "package"
WORK_DIR = BUILD_ROOT / "pyinstaller-work"
SPEC_DIR = BUILD_ROOT / "spec"

TEMPLATE_DIR = d0_paths.BACKEND_ROOT / "app" / "assets" / "word_templates"
ALEMBIC_INI = d0_paths.BACKEND_ROOT / "alembic-local.ini"
MIGRATIONS_DIR = d0_paths.BACKEND_ROOT / "migrations_local"

APP_NAME = "KGNext-D2Verify"


def os_sep() -> str:
    return ";" if sys.platform.startswith("win") else ":"


def build_frontend(frontend_out: Path, *, reuse: bool) -> None:
    """Build the real D2 frontend **without any network install**.

    Uses the already-present local Vite CLI (``frontend/node_modules/vite``)
    directly; if it or Node is missing the build fails instead of falling back
    to a network fetch (``npx`` without ``--no-install`` may download).
    """
    if reuse and (frontend_out / "d1.html").is_file():
        print(f"== 复用现有 D2 前端输出 {frontend_out} ==")
        return
    frontend_root = d0_paths.REPO_ROOT / "frontend"
    node = resolve_node_tool("node")
    vite_js = frontend_root / "node_modules" / "vite" / "bin" / "vite.js"
    if not node:
        raise SystemExit("未找到 node：请确保 Node.js 在 PATH 中。")
    if not vite_js.is_file():
        raise SystemExit(
            "未找到本地 Vite CLI（frontend/node_modules/vite）。本轮不安装依赖，"
            "请先在仓库内准备现有 node_modules 后再构建。"
        )
    # Explicitly NEVER run npm ci / npx (which can fetch from the network): the
    # local Vite CLI is invoked directly with the existing node_modules.
    print(f"== D2 前端构建（直接调用本地 Vite，复用 node_modules，不安装依赖）==")
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
        raise SystemExit(f"D2 前端构建输出异常：{frontend_out}")


def build_package(dist_root: Path, frontend_out: Path) -> Path:
    print("== D2 PyInstaller onedir windowed package ==")
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
        f"{frontend_out}{separator}frontend",
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
        "--hidden-import",
        "chinese_calendar",
        "--hidden-import",
        "sqlalchemy.dialects.sqlite",
        "--hidden-import",
        "sqlalchemy.dialects.sqlite.pysqlite",
        "--hidden-import",
        "cryptography.hazmat.primitives.ciphers.aead",
        "--hidden-import",
        "d2_same_origin",
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
    parser = argparse.ArgumentParser(description="Build the D2 W6 full desktop package")
    parser.add_argument("--skip-frontend", action="store_true", help="复用已构建的 D2 前端输出")
    parser.add_argument("--reuse-frontend", action="store_true", help="已有输出则直接复用（不重建）")
    parser.add_argument("--dist-root", help="打包输出父目录（默认 build/desktop-d2/package）")
    parser.add_argument("--hash-out", help="将包内逐文件 SHA256 清单写入该 JSON 文件")
    args = parser.parse_args()

    build_frontend(FRONTEND_DIR, reuse=args.skip_frontend or args.reuse_frontend)
    dist_root = Path(args.dist_root) if args.dist_root else PACKAGE_DIR
    package_root = build_package(dist_root, FRONTEND_DIR)
    if args.hash_out:
        Path(args.hash_out).write_text(
            json.dumps(
                {"package": str(package_root), "files": hash_tree(package_root)},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"逐文件散列已写入：{args.hash_out}")
    print(f"D2 包输出目录：{package_root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
