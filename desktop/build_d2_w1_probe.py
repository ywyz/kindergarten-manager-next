"""D2 W1 frozen probe build (Windows-only helper).

Produces a PyInstaller **onedir** console package in
``build/desktop-d2-w1/package/KGNext-D2W1Probe/``. Unlike ``build_d1.py`` this
helper:

- never runs ``npm ci`` or any frontend build (the probe is a no-UI console
  verification, not the application);
- never touches or calls ``build/desktop-d1`` or ``build/desktop-d0``;
- bundles the real local runtime, the local Alembic INI and the local
  migration scripts so ``app.local.migrate`` resolves its resources *inside*
  the package, plus ``cryptography`` for the DPAPI/AES credential path.

The executable is a console program so the parent verifier can feed the secret
through stdin. It is started by the parent with ``CREATE_NO_WINDOW``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
REPO_ROOT = APP_DIR.parent
BACKEND_ROOT = REPO_ROOT / "backend"

BUILD_ROOT = REPO_ROOT / "build" / "desktop-d2-w1"
PACKAGE_DIR = BUILD_ROOT / "package"
WORK_DIR = BUILD_ROOT / "pyinstaller-work"
SPEC_DIR = BUILD_ROOT / "spec"

ALEMBIC_INI = BACKEND_ROOT / "alembic-local.ini"
MIGRATIONS_DIR = BACKEND_ROOT / "migrations_local"

APP_NAME = "KGNext-D2W1Probe"


def os_sep() -> str:
    return ";" if sys.platform.startswith("win") else ":"


def build_package(dist_root: Path) -> Path:
    print("== D2 W1 PyInstaller onedir console probe ==")
    separator = os_sep()
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--console",
        "--name",
        APP_NAME,
        "--distpath",
        str(dist_root),
        "--workpath",
        str(WORK_DIR),
        "--specpath",
        str(SPEC_DIR),
        "--paths",
        str(APP_DIR),
        "--paths",
        str(BACKEND_ROOT),
        "--add-data",
        f"{ALEMBIC_INI}{separator}.",
        "--add-data",
        f"{MIGRATIONS_DIR}{separator}migrations_local",
        "--hidden-import",
        "chinese_calendar",
        "--collect-submodules",
        "chinese_calendar",
        "--hidden-import",
        "sqlalchemy.dialects.sqlite",
        "--hidden-import",
        "sqlalchemy.dialects.sqlite.pysqlite",
        "--hidden-import",
        "cryptography.hazmat.primitives.ciphers.aead",
        str(APP_DIR / "d2_w1_probe.py"),
    ]
    subprocess.run(command, check=True, cwd=REPO_ROOT)
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
    parser = argparse.ArgumentParser(description="Build the D2 W1 frozen probe")
    parser.add_argument(
        "--dist-root",
        help="打包输出父目录（默认 build/desktop-d2-w1/package）",
    )
    parser.add_argument(
        "--hash-out",
        help="将包内逐文件 SHA256 清单写入该 JSON 文件",
    )
    args = parser.parse_args()
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
    print(f"D2 W1 探针包输出目录：{package_root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
