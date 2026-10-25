"""Real old-process fixture for U2: hold the actual LocalRuntime lock."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path


def _publish_ready(path: str, value: dict) -> None:
    """Publish a complete ready record atomically; readers never see empty JSON."""
    target = Path(path)
    temp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        with temp.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps(value, ensure_ascii=False))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, target)
    finally:
        try:
            temp.unlink()
        except OSError:
            pass

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.local.runtime import LocalRuntime  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    parser.add_argument("--credential-root", required=True)
    parser.add_argument("--ready", required=True)
    parser.add_argument("--stop", required=True)
    parser.add_argument("--db-only", action="store_true")
    args = parser.parse_args()
    if args.db_only:
        db = Path(args.data) / "kindergarten.db"
        connection = sqlite3.connect(db, timeout=30.0)
        connection.isolation_level = None
        try:
            connection.execute("BEGIN IMMEDIATE")
            revision = connection.execute(
                "SELECT version_num FROM local_alembic_version"
            ).fetchone()[0]
            _publish_ready(
                args.ready,
                {"pid": os.getpid(), "revision": revision},
            )
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline and not Path(args.stop).exists():
                time.sleep(0.02)
            connection.execute("ROLLBACK")
        finally:
            connection.close()
        return 0
    runtime = LocalRuntime(args.data, credential_root=args.credential_root)
    try:
        runtime.prepare()
        _publish_ready(
            args.ready,
            {
                "pid": os.getpid(),
                "revision": runtime.current_revision,
                "data_dir": str(runtime.data_dir),
                "credential_root": str(runtime.credential_root),
            },
        )
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline and not Path(args.stop).exists():
            time.sleep(0.02)
    finally:
        runtime.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
