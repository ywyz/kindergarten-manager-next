"""独立 W6 人工验收包构建（新目录/新工作/新 spec；不改原包）。

产物：``build/desktop-d2-manual-ai/package/KGNext-D2ManualAI/``，入口为
``d2_manual_ai_main.py``（人工窗口），复用**已有**的
``build/desktop-d2/frontend``、Word 模板、``alembic-local.ini`` 与冻结
``migrations_local``；不运行 npm/npx，不安装/升级依赖，不覆盖
``build/desktop-d2/package/KGNext-D2Verify``（原 182 文件包）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import d0_paths

BUILD_ROOT = d0_paths.REPO_ROOT / "build" / "desktop-d2-manual-ai"
PACKAGE_DIR = BUILD_ROOT / "package"
WORK_DIR = BUILD_ROOT / "pyinstaller-work"
SPEC_DIR = BUILD_ROOT / "spec"

FRONTEND_DIR = d0_paths.REPO_ROOT / "build" / "desktop-d2" / "frontend"
TEMPLATE_DIR = d0_paths.BACKEND_ROOT / "app" / "assets" / "word_templates"
ALEMBIC_INI = d0_paths.BACKEND_ROOT / "alembic-local.ini"
MIGRATIONS_DIR = d0_paths.BACKEND_ROOT / "migrations_local"

APP_NAME = "KGNext-D2ManualAI"


def os_sep() -> str:
    return ";" if sys.platform.startswith("win") else ":"


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


def build_package(dist_root: Path, frontend_dir: Path) -> Path:
    if not (frontend_dir / "d1.html").is_file():
        raise SystemExit(
            f"缺少 D2 前端构建: {frontend_dir}（本构建不重建前端，不安装依赖）"
        )
    print("== D2 人工验收 PyInstaller onedir windowed package ==")
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
        str(d0_paths.APP_DIR / "d2_manual_ai_main.py"),
    ]
    subprocess.run(command, check=True, cwd=d0_paths.REPO_ROOT)
    package_root = dist_root / APP_NAME
    executable = package_root / f"{APP_NAME}.exe"
    if not executable.is_file():
        raise SystemExit(f"打包输出异常：{package_root}")
    return package_root


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the W6 manual-acceptance package")
    parser.add_argument("--dist-root", help="打包输出父目录（默认 build/desktop-d2-manual-ai/package）")
    parser.add_argument(
        "--frontend-dir",
        default=str(FRONTEND_DIR),
        help="要打包的 D2 前端构建目录（默认既有 build/desktop-d2/frontend）",
    )
    parser.add_argument("--hash-out", help="将包内逐文件 SHA256 清单写入该 JSON 文件")
    args = parser.parse_args()
    dist_root = Path(args.dist_root) if args.dist_root else PACKAGE_DIR
    protected = (d0_paths.REPO_ROOT / "build" / "desktop-d2" / "package").resolve()
    resolved = dist_root.resolve()
    if resolved == protected or protected in resolved.parents:
        raise SystemExit(f"拒绝把独立人工包写入原 182 文件生产包目录: {resolved}")
    package_root = build_package(dist_root.resolve(), Path(args.frontend_dir).resolve())
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
    print(f"D2 人工验收包输出目录：{package_root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
