"""R02 batch fixture: real-process DB occupation and WAL-commit helpers.

Both actions run as a subprocess so the parent can observe real Windows
file-sharing and WAL behaviour of *another* process (the old D1 program does
not know the runtime lock, so only a genuine database-handle occupation is a
valid signal). The parent reaps only the processes it created.

Actions (selected by ``spec["action"]``):

- ``hold_open``: open the database, hold a real read transaction, signal
  ``ready_file`` and wait for ``release_file``. The main database file handle
  stays open, so the parent's exclusive (share mode 0) occupation probe must
  fail with a sharing violation.
- ``wal_commit_exit``: open the database, run ``statements``, commit and then
  ``os._exit`` without closing, so the committed frames stay in the ``-wal``
  file (no checkpoint/delete on close).
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from pathlib import Path


def _read_spec() -> dict:
    return json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))


def _signal(path: str, payload: dict | None = None) -> None:
    Path(path).write_text(
        json.dumps(payload or {}, ensure_ascii=False), encoding="utf-8"
    )


def hold_open(spec: dict) -> int:
    connection = sqlite3.connect(spec["db_path"], timeout=30.0)
    # Autocommit mode so the explicit BEGIN is the only transaction.
    connection.isolation_level = None
    try:
        connection.execute("BEGIN")
        connection.execute("SELECT count(*) FROM sqlite_master").fetchone()
        _signal(spec["ready_file"], {"state": "held"})
        release = Path(spec["release_file"])
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline and not release.exists():
            time.sleep(0.02)
        connection.execute("ROLLBACK")
    finally:
        connection.close()
    _signal(spec["result_file"], {"state": "released"})
    return 0


def wal_commit_exit(spec: dict) -> int:
    connection = sqlite3.connect(spec["db_path"], timeout=30.0)
    mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
    if str(mode).lower() != "wal":
        connection.execute("PRAGMA journal_mode=WAL")
    for statement, params in spec.get("statements", []):
        connection.execute(statement, params or [])
    connection.commit()
    _signal(spec["result_file"], {"state": "committed", "journal_mode": mode})
    sys.stdout.flush()
    # Leave without closing: the committed frames remain in the -wal file.
    os._exit(0)


_ACTIONS = {
    "hold_open": hold_open,
    "wal_commit_exit": wal_commit_exit,
}


def main() -> int:
    spec = _read_spec()
    action = _ACTIONS.get(spec["action"])
    if action is None:
        _signal(spec.get("result_file", ""), {"error": "unknown action"})
        return 2
    return action(spec)


if __name__ == "__main__":
    raise SystemExit(main())
