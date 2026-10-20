"""Dedicated subprocess helper for the D2 W1 runtime-lock tests.

Kept separate from ``tests.local.worker`` (the service-level worker) because
the runtime lock is about the *startup* boundary: a second process must report
the exact refusal code instead of crashing, and a holder must keep the OS
handle open until it is explicitly released or killed.

Two actions:

- ``hold``: construct and ``prepare()`` a runtime, signal readiness, then keep
  holding the lock until the release file appears (or the timeout expires) and
  dispose cleanly.
- ``probe``: construct a runtime and try to ``prepare()`` it, reporting either
  ``{"outcome": "ok"}`` or ``{"outcome": "refused", "code": <error code>}``.

Every runtime receives an explicit injected ``credential_root`` so the real
teacher credential directory is never touched.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from app.local.errors import LocalDatabaseStateError, LocalError
from app.local.runtime import LocalRuntime


def _run_hold(spec: dict) -> dict:
    runtime = LocalRuntime(
        data_dir=spec["data_dir"], credential_root=spec["credential_root"]
    )
    runtime.prepare()
    Path(spec["ready_file"]).write_text("ready", encoding="utf-8")
    release = Path(spec["release_file"])
    deadline = time.time() + float(spec.get("hold_seconds", 60))
    while time.time() < deadline:
        if release.exists():
            break
        time.sleep(0.02)
    runtime.dispose()
    return {"outcome": "released"}


def _run_probe(spec: dict) -> dict:
    runtime = LocalRuntime(
        data_dir=spec["data_dir"], credential_root=spec["credential_root"]
    )
    try:
        runtime.prepare()
    except LocalDatabaseStateError as exc:
        return {"outcome": "refused", "code": exc.code}
    except LocalError as exc:
        return {"outcome": "refused", "code": exc.code}
    finally:
        runtime.dispose()
    return {"outcome": "ok"}


def main() -> int:
    spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    result = {"hold": _run_hold, "probe": _run_probe}[spec["action"]](spec)
    Path(spec["result_file"]).write_text(
        json.dumps(result, ensure_ascii=False), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
