"""D0 build orchestration (Windows-only helper).

Steps:
1. build the D0 frontend entry into ``build/desktop-d0/frontend``
   (separate from any leftover main-app build directory);
2. produce the PyInstaller **onedir** test package in
   ``build/desktop-d0/package/KGNext-D0Verify/`` bundling the Vue assets and
   the controlled daily Word template.

The build never runs from a spec file stored in the source tree; the
temporary spec lands in the build workpath.

On native Windows ``npm``/``npx`` are ``.cmd`` shims which CreateProcess
cannot execute directly (``FileNotFoundError [WinError 2]``). The tools are
resolved with PATHEXT and routed through ``cmd /c`` when needed (R4).
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

import d0_paths

BUILD_ROOT = d0_paths.REPO_ROOT / "build" / "desktop-d0"
FRONTEND_DIR = BUILD_ROOT / "frontend"
PACKAGE_DIR = BUILD_ROOT / "package"
WORK_DIR = BUILD_ROOT / "pyinstaller-work"
SPEC_DIR = BUILD_ROOT / "spec"
TEMPLATE_FILE = (
    d0_paths.BACKEND_ROOT / "app" / "assets" / "word_templates" / "daily_plan.docx"
)

APP_NAME = "KGNext-D0Verify"


def resolve_node_tool(name: str) -> list[str]:
    """Resolve ``npm``/``npx`` to a runnable argv prefix on native Windows.

    ``shutil.which`` applies ``PATHEXT`` so it returns ``...\\npm.CMD``; a
    ``.cmd``/``.bat`` shim is launched through ``cmd /c``. Returns ``[]`` when
    the tool is missing so the caller can give a clear message.
    """
    path = shutil.which(name)
    if not path:
        return []
    if path.lower().endswith((".cmd", ".bat")):
        comspec = os.environ.get("COMSPEC") or "cmd.exe"
        return [comspec, "/c", path]
    return [path]


def build_frontend() -> None:
    frontend_root = d0_paths.REPO_ROOT / "frontend"
    npm = resolve_node_tool("npm")
    npx = resolve_node_tool("npx")
    if not npm or not npx:
        raise SystemExit(
            "未找到 npm/npx：请安装 Node.js 并确保其在 PATH 中；"
            "或先手工构建 D0 前端后使用 --skip-frontend。"
        )
    print(f"== D0 frontend build (npm={npm[-1]}) ==")
    subprocess.run(
        [*npm, "ci", "--no-audit", "--no-fund"],
        cwd=frontend_root,
        check=True,
        shell=False,
    )
    subprocess.run(
        [*npx, "vite", "build", "--config", "vite.d0.config.ts"],
        cwd=frontend_root,
        check=True,
        shell=False,
    )
    if not (FRONTEND_DIR / "d0.html").is_file():
        raise SystemExit(f"D0 前端构建输出异常：{FRONTEND_DIR}")


def build_package() -> Path:
    print("== D0 PyInstaller onedir package ==")
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
        str(PACKAGE_DIR),
        "--workpath",
        str(WORK_DIR),
        "--specpath",
        str(SPEC_DIR),
        "--paths",
        str(d0_paths.APP_DIR),
        "--paths",
        str(d0_paths.BACKEND_ROOT),
        "--add-data",
        f"{FRONTEND_DIR}{os_sep()}desktop_resources/frontend",
        "--add-data",
        f"{TEMPLATE_FILE}{os_sep()}desktop_resources/word_templates",
        "--collect-submodules",
        "webview",
        "--collect-submodules",
        "uvicorn",
        str(d0_paths.APP_DIR / "d0_main.py"),
    ]
    subprocess.run(command, check=True, cwd=d0_paths.REPO_ROOT)
    package_root = PACKAGE_DIR / APP_NAME
    executable = package_root / f"{APP_NAME}.exe"
    if not executable.is_file():
        raise SystemExit(f"打包输出异常：{package_root}")
    return package_root


def os_sep() -> str:
    return ";" if sys.platform.startswith("win") else ":"  # add-data separator


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the D0 desktop test package")
    parser.add_argument(
        "--skip-frontend",
        action="store_true",
        help="复用已构建的 D0 前端输出，只做打包",
    )
    parser.add_argument(
        "--package-only",
        action="store_true",
        help="（已废弃）等同 --skip-frontend",
    )
    args = parser.parse_args()
    skip_frontend = args.skip_frontend or args.package_only
    if not skip_frontend:
        build_frontend()
    else:
        if not (FRONTEND_DIR / "d0.html").is_file():
            raise SystemExit("前端构建缺失；请先运行不带 --skip-frontend 的完整构建")
    package_root = build_package()
    print(f"D0 包输出目录：{package_root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
