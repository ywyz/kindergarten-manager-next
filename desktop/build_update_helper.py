"""Build the small independent U2 updater (Windows PyInstaller support).

The updater is a separate onedir program under
``%LOCALAPPDATA%/Programs/KindergartenManager/updater`` and never loads the
application package it is switching.  This script is build support only; the
U2 engineering round does not execute it or build/run a frozen package.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import d0_paths

APP_NAME = "KindergartenManagerUpdater"


def build(dist_root: Path, work_dir: Path, spec_dir: Path) -> Path:
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
        "--hidden-import",
        "cryptography.hazmat.primitives.asymmetric.ed25519",
        str(d0_paths.APP_DIR / "update_helper.py"),
    ]
    subprocess.run(command, check=True, cwd=d0_paths.REPO_ROOT)
    package = dist_root / APP_NAME
    executable = package / f"{APP_NAME}.exe"
    if not executable.is_file():
        raise SystemExit(f"更新器打包输出异常：{package}")
    return package


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the independent U2 updater")
    parser.add_argument("--dist-root", default=str(d0_paths.REPO_ROOT / "build" / "desktop-update" / "package"))
    parser.add_argument("--work-dir", default=str(d0_paths.REPO_ROOT / "build" / "desktop-update" / "work"))
    parser.add_argument("--spec-dir", default=str(d0_paths.REPO_ROOT / "build" / "desktop-update" / "spec"))
    parser.add_argument(
        "--release-config",
        default=None,
        help="build-time fixed release trust config copied beside the updater exe",
    )
    args = parser.parse_args()
    package = build(Path(args.dist_root), Path(args.work_dir), Path(args.spec_dir))
    if args.release_config:
        shutil.copy2(args.release_config, package / "update_release.json")
    print(package)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
