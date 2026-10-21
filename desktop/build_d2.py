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
LEGACY_BUILD_ROOT = BUILD_ROOT
PROTECTED_BUILD_ROOTS = (
    d0_paths.REPO_ROOT / "build" / "desktop-d2",
    d0_paths.REPO_ROOT / "build" / "desktop-d2-manual-ai",
    d0_paths.REPO_ROOT / "build" / "desktop-d2-manual-ai-h06-r01",
)
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


def build_package(dist_root: Path, frontend_out: Path, work_dir: Path, spec_dir: Path) -> Path:
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
        str(work_dir),
        "--specpath",
        str(spec_dir),
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


def _overlaps(left: Path, right: Path) -> bool:
    """True when either path is the other or one is an ancestor (resolved)."""
    return left == right or left in right.parents or right in left.parents


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the D2 W6 full desktop package")
    parser.add_argument("--skip-frontend", action="store_true", help="复用已构建的 D2 前端输出")
    parser.add_argument("--reuse-frontend", action="store_true", help="已有输出则直接复用（不重建）")
    parser.add_argument(
        "--build-root",
        help="独立构建根（默认 build/desktop-d2；旧根受保护）",
    )
    parser.add_argument(
        "--frontend-dir",
        help="显式指定已构建前端目录（只读输入，不重建）",
    )
    parser.add_argument("--dist-root", help="打包输出父目录（默认 <build-root>/package）")
    parser.add_argument("--hash-out", help="将包内逐文件 SHA256 清单写入该 JSON 文件")
    args = parser.parse_args()

    build_root = (
        Path(args.build_root).resolve()
        if args.build_root
        else LEGACY_BUILD_ROOT.resolve()
    )
    frontend_out = (
        Path(args.frontend_dir).resolve() if args.frontend_dir else build_root / "frontend"
    )
    work_dir = build_root / "pyinstaller-work"
    spec_dir = build_root / "spec"
    dist_root = Path(args.dist_root).resolve() if args.dist_root else build_root / "package"

    # Every path this run will WRITE must be checked (resolved) before any build
    # or file write. An explicit --frontend-dir is a read-only input and is
    # deliberately not checked as a write target (reusing an old frontend is
    # allowed); it still must exist below.
    write_paths: dict[str, Path] = {
        "work": work_dir.resolve(),
        "spec": spec_dir.resolve(),
        "package": dist_root.resolve(),
    }
    if args.frontend_dir is None:
        write_paths["frontend"] = frontend_out.resolve()
    if args.hash_out:
        write_paths["hash-out"] = Path(args.hash_out).resolve()
    protected = tuple(root.resolve() for root in PROTECTED_BUILD_ROOTS)
    locations: dict[str, Path] = {
        "build-root": build_root,
        "dist-root": dist_root,
        **write_paths,
    }
    for label, target in locations.items():
        for root in protected:
            if _overlaps(target, root):
                raise SystemExit(
                    f"拒绝写入受保护的旧构建根（{label}: {target} 与 {root} 相交）；"
                    "请使用独立 --build-root／--dist-root／--hash-out。"
                )

    if args.frontend_dir is None:
        build_frontend(frontend_out, reuse=args.skip_frontend or args.reuse_frontend)
    elif not (frontend_out / "d1.html").is_file():
        raise SystemExit(f"显式前端目录缺少 d1.html: {frontend_out}")
    else:
        print(f"== 复用显式前端目录 {frontend_out} ==")

    package_root = build_package(dist_root, frontend_out, work_dir, spec_dir)
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
