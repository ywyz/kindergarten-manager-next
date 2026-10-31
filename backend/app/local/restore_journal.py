"""Durable restore journal and terminal receipts.

The journal is deliberately *not* a multi-file transaction.  It records the
application-generated component identities and the observed phase; recovery
combines it with the actual filesystem state.  A terminal journal has no
rollback authority and may be archived to a receipt before normal startup
writes begin.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.local import backup_fs
from app.local.restore_fs import (
    RestorePathSet,
    atomic_write_json,
    read_json,
)
from app.local.restore_types import RestoreFailure

JOURNAL_VERSION = 1
_RECEIPT_PHASE = "terminal"


def _canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _with_integrity(data: dict[str, Any]) -> dict[str, Any]:
    result = dict(data)
    result.pop("integrity", None)
    result["integrity"] = hashlib.sha256(_canonical(result)).hexdigest()
    return result


def _validate(data: dict[str, Any], *, source: str) -> dict[str, Any]:
    if data.get("journal_version") != JOURNAL_VERSION:
        raise RestoreFailure(
            "RESTORE_JOURNAL_INVALID", "recovery", f"{source} 版本不支持"
        )
    actual = data.get("integrity")
    if not isinstance(actual, str):
        raise RestoreFailure(
            "RESTORE_JOURNAL_INVALID", "recovery", f"{source} 缺少完整性摘要"
        )
    copy = dict(data)
    copy.pop("integrity", None)
    expected = hashlib.sha256(_canonical(copy)).hexdigest()
    if actual != expected:
        raise RestoreFailure(
            "RESTORE_JOURNAL_INVALID", "recovery", f"{source} 完整性校验失败"
        )
    operation_id = data.get("operation_id")
    if not isinstance(operation_id, str) or not operation_id:
        raise RestoreFailure(
            "RESTORE_JOURNAL_INVALID", "recovery", f"{source} 缺少操作标识"
        )
    return data


def new_journal(
    *,
    operation_id: str,
    package: dict[str, Any],
    protection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    return _with_integrity(
        {
            "journal_version": JOURNAL_VERSION,
            "operation_id": operation_id,
            "phase": "preparing",
            "terminal": False,
            "rollback_authority": True,
            "created_at": now,
            "updated_at": now,
            "first_live_change_at": None,
            "package": dict(package),
            "protection": dict(protection or {}),
            "old": {},
            "new": {},
            "auth_changes": {},
            "history": [{"phase": "preparing", "at": now}],
        }
    )


def write_journal(paths: RestorePathSet, journal: dict[str, Any]) -> dict[str, Any]:
    data = dict(journal)
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    data = _with_integrity(data)
    atomic_write_json(paths.journal_path, data, replace=True, private_parent=False)
    return data


def read_journal(paths: RestorePathSet) -> dict[str, Any] | None:
    data = read_json(paths.journal_path)
    if data is None:
        return None
    return _validate(data, source="恢复日志")


def set_phase(
    paths: RestorePathSet, journal: dict[str, Any], phase: str, **extra: Any
) -> dict[str, Any]:
    journal = dict(journal)
    journal["phase"] = phase
    journal.update(extra)
    now = datetime.now(timezone.utc).isoformat()
    journal.setdefault("history", []).append({"phase": phase, "at": now})
    return write_journal(paths, journal)


def receipt_path(paths: RestorePathSet, operation_id: str) -> Path:
    return paths.receipts_dir / f"{operation_id}.json"


def read_receipt(paths: RestorePathSet, operation_id: str) -> dict[str, Any] | None:
    data = read_json(receipt_path(paths, operation_id))
    if data is None:
        return None
    return _validate(data, source="恢复回执")


def write_receipt(paths: RestorePathSet, journal: dict[str, Any]) -> dict[str, Any]:
    operation_id = str(journal["operation_id"])
    existing = read_receipt(paths, operation_id)
    if existing is not None:
        if existing.get("operation_id") != operation_id:
            raise RestoreFailure(
                "RESTORE_RECEIPT_INVALID", "recovery", "恢复回执操作标识冲突"
            )
        return existing
    data = dict(journal)
    data["terminal"] = True
    data["rollback_authority"] = False
    data["result_state"] = str(
        journal.get("result_state")
        or journal.get("phase")
        or "installed"
    )
    data["phase"] = _RECEIPT_PHASE
    data["retired_at"] = datetime.now(timezone.utc).isoformat()
    data = _with_integrity(data)
    atomic_write_json(
        receipt_path(paths, operation_id),
        data,
        replace=False,
        private_parent=True,
    )
    return data


def terminal_journal(paths: RestorePathSet, journal: dict[str, Any]) -> dict[str, Any]:
    """Make the active journal terminal before lease release/reopen."""
    data = dict(journal)
    data["result_state"] = str(
        journal.get("result_state")
        or journal.get("phase")
        or "installed"
    )
    data["terminal"] = True
    data["rollback_authority"] = False
    data["phase"] = _RECEIPT_PHASE
    data["retired_at"] = datetime.now(timezone.utc).isoformat()
    data = write_journal(paths, data)
    return data


def archive_terminal(paths: RestorePathSet, journal: dict[str, Any]) -> str:
    """Archive a terminal active journal; return the receipt id."""
    operation_id = str(journal["operation_id"])
    receipt = write_receipt(paths, journal)
    try:
        with backup_fs.FileLease(paths.journal_path) as lease:
            if lease.size <= 0:
                raise RestoreFailure(
                    "RESTORE_JOURNAL_INVALID", "recovery", "恢复日志为空"
                )
        paths.journal_path.unlink()
    except FileNotFoundError:
        pass
    return str(receipt["operation_id"])


def remove_active_journal(paths: RestorePathSet) -> None:
    try:
        with backup_fs.FileLease(paths.journal_path):
            pass
    except FileNotFoundError:
        return
    paths.journal_path.unlink()


def journal_state(paths: RestorePathSet) -> dict[str, Any] | None:
    return read_journal(paths)
