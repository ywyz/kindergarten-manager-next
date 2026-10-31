"""Subprocess worker for controlled restore crash/restart tests.

Only the test suite runs this module.  It owns its synthetic target root and
may terminate itself at a named restore stage with os._exit(70), leaving the
real journal/prepared/old groups exactly as a process kill would.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path

from app.local.restore_service import RestoreCore
from app.local.runtime import LocalRuntime


class _Hooks:
    def wait_host_idle(self, cancel) -> bool:
        return not cancel.is_set()

    def stop_transport(self) -> bool:
        return True


def main() -> int:
    spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    fault = str(spec.get("fault_stage") or "")
    target = LocalRuntime(
        spec["data_dir"], credential_root=spec["credential_root"]
    )
    target.prepare()
    core = RestoreCore(
        target,
        app_version="restore-test",
        fault_injector=(
            lambda stage: os._exit(70) if fault and stage == fault else None
        ),
    )
    cancel = threading.Event()
    preview = core.preview(
        spec["package"],
        None,
        operation_id=spec["operation_id"],
        cancel=cancel,
    )
    prepared = core.prepare(preview, cancel=cancel)
    result = core.install(prepared, hooks=_Hooks(), cancel=cancel)
    output = {
        "state": result.state,
        "operation_id": result.operation_id,
    }
    Path(spec["result_file"]).write_text(
        json.dumps(output, ensure_ascii=False), encoding="utf-8"
    )
    target.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
