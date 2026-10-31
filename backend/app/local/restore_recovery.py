"""Startup resolution for an interrupted restore.

Runs after the data-root lock is acquired and before schema inspection,
migration, prompt sync, AI recovery, HTTP or UI.  A terminal journal/receipt
has no rollback authority: normal startup writes must never be compared with
the install-time database hash again.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.local import restore_group, restore_journal
from app.local.errors import LocalDatabaseStateError
from app.local.restore_fs import operation_paths
from app.local.restore_types import RestoreFailure


def _notice(
    state: str,
    journal: dict[str, Any],
    paths,
    *,
    receipt_id: str | None = None,
) -> dict[str, Any]:
    protection = paths.protection_path
    return {
        "state": state,
        "operation_id": str(journal.get("operation_id") or ""),
        "message_key": f"restore.recovery.{state}",
        "protection_display_path": str(protection) if protection.exists() else "",
        "receipt_id": receipt_id,
    }


class _RuntimeProxy:
    """The two attributes operation path derivation needs, without importing."""

    def __init__(self, data_dir: Path, credential_root: Path):
        self.data_dir = data_dir
        self.credential_root = credential_root


def resolve_startup_restore(runtime) -> dict[str, Any] | None:
    proxy = _RuntimeProxy(Path(runtime.data_dir), Path(runtime.credential_root))
    empty_paths = operation_paths(proxy, "0" * 32, create=False)
    try:
        journal = restore_journal.read_journal(empty_paths)
    except RestoreFailure as exc:
        raise LocalDatabaseStateError(
            "LOCAL_RESTORE_RECOVERY_REQUIRED",
            "恢复日志无法读取或完整性校验失败；拒绝写入",
        ) from exc
    if journal is None:
        return None
    operation_id = str(journal["operation_id"])
    try:
        paths = operation_paths(proxy, operation_id, create=False)
    except RestoreFailure as exc:
        raise LocalDatabaseStateError(
            "LOCAL_RESTORE_RECOVERY_REQUIRED",
            "恢复日志操作标识不合法；拒绝写入",
        ) from exc
    try:
        receipt = restore_journal.read_receipt(paths, operation_id)
    except RestoreFailure as exc:
        raise LocalDatabaseStateError(
            "LOCAL_RESTORE_RECOVERY_REQUIRED",
            "恢复回执无法读取或完整性校验失败；拒绝写入",
        ) from exc
    if receipt is not None:
        # A terminal receipt for this operation makes any active journal a
        # stale replay.  Never compare current DB bytes with the install hash.
        try:
            restore_journal.remove_active_journal(paths)
        except Exception:  # noqa: BLE001 - receipt remains authoritative
            pass
        return _notice(
            str(receipt.get("result_state") or "installed"),
            receipt,
            paths,
            receipt_id=operation_id,
        )
    if journal.get("terminal"):
        try:
            restore_journal.archive_terminal(paths, journal)
        except Exception:  # noqa: BLE001 - terminal journal still authoritative
            pass
        return _notice(
            str(journal.get("result_state") or "installed"),
            journal,
            paths,
            receipt_id=operation_id,
        )

    phase = str(journal.get("phase") or "")
    new_group = journal.get("new") or {}
    old_group = journal.get("old") or {}
    if phase in ("installed", "committed"):
        try:
            if not new_group:
                raise RestoreFailure(
                    "RESTORE_RECOVERY_REQUIRED", "recovery", "缺少安装组身份"
                )
            location = restore_group.new_group_complete(paths, new_group)
            if location is None or location.get("db") != "live":
                raise RestoreFailure(
                    "RESTORE_RECOVERY_REQUIRED", "recovery", "安装组不完整"
                )
            restore_group.verify_installed_group(
                paths, new_group, paths.operation_dir / "recovery-schema"
            )
        except Exception as exc:  # noqa: BLE001 - refuse rather than guess
            raise LocalDatabaseStateError(
                "LOCAL_RESTORE_RECOVERY_REQUIRED",
                "恢复安装组无法核对；已保留旧组和保护副本，拒绝写入",
            ) from exc
        terminal = restore_journal.terminal_journal(paths, journal)
        try:
            restore_journal.write_receipt(paths, terminal)
            restore_journal.archive_terminal(paths, terminal)
        except Exception:  # noqa: BLE001 - terminal journal is sufficient
            pass
        return _notice("installed", terminal, paths, receipt_id=operation_id)

    if (
        not journal.get("first_live_change_at")
        and phase in ("preparing", "protection_ready", "quiesced")
    ):
        # No live component was renamed yet: the old group is still the
        # authoritative one.  Archive the intent without touching data.
        journal = restore_journal.set_phase(paths, journal, "failed_keep_old")
        terminal = restore_journal.terminal_journal(paths, journal)
        try:
            restore_journal.write_receipt(paths, terminal)
            restore_journal.archive_terminal(paths, terminal)
        except Exception:  # noqa: BLE001 - terminal journal is sufficient
            pass
        return _notice("failed_keep_old", terminal, paths, receipt_id=operation_id)

    old_location = restore_group.old_group_complete(paths, old_group) if old_group else None
    new_location = restore_group.new_group_complete(paths, new_group) if new_group else None
    if old_location is not None and new_location is None:
        try:
            restore_group.rollback_to_old(paths, new_group)
        except Exception as exc:  # noqa: BLE001
            raise LocalDatabaseStateError(
                "LOCAL_RESTORE_RECOVERY_REQUIRED",
                "无法回滚完整旧组；已保留两组，拒绝写入",
            ) from exc
        journal = restore_journal.set_phase(paths, journal, "rolled_back")
        terminal = restore_journal.terminal_journal(paths, journal)
        try:
            restore_journal.write_receipt(paths, terminal)
            restore_journal.archive_terminal(paths, terminal)
        except Exception:  # noqa: BLE001
            pass
        return _notice("rolled_back", terminal, paths, receipt_id=operation_id)
    if new_location is not None and old_location is None:
        if new_location.get("db") != "live":
            raise LocalDatabaseStateError(
                "LOCAL_RESTORE_RECOVERY_REQUIRED",
                "新组只存在于 prepared 区，未安装到现用组；拒绝猜测",
            )
        try:
            restore_group.verify_installed_group(
                paths, new_group, paths.operation_dir / "recovery-schema"
            )
        except Exception as exc:  # noqa: BLE001
            raise LocalDatabaseStateError(
                "LOCAL_RESTORE_RECOVERY_REQUIRED",
                "新组校验失败；已保留旧组和保护副本，拒绝写入",
            ) from exc
        terminal = restore_journal.terminal_journal(paths, journal)
        try:
            restore_journal.write_receipt(paths, terminal)
            restore_journal.archive_terminal(paths, terminal)
        except Exception:  # noqa: BLE001
            pass
        return _notice("installed", terminal, paths, receipt_id=operation_id)
    if old_location is not None and new_location is not None:
        # Both groups are complete: the journal phase is only a tie-break.
        if phase in ("installed", "committed", "terminal"):
            return _notice("installed", journal, paths, receipt_id=operation_id)
        try:
            restore_group.rollback_to_old(paths, new_group)
        except Exception as exc:  # noqa: BLE001
            raise LocalDatabaseStateError(
                "LOCAL_RESTORE_RECOVERY_REQUIRED",
                "两组都完整但旧组回滚失败；拒绝写入",
            ) from exc
        journal = restore_journal.set_phase(paths, journal, "rolled_back")
        terminal = restore_journal.terminal_journal(paths, journal)
        try:
            restore_journal.write_receipt(paths, terminal)
            restore_journal.archive_terminal(paths, terminal)
        except Exception:  # noqa: BLE001
            pass
        return _notice("rolled_back", terminal, paths, receipt_id=operation_id)
    raise LocalDatabaseStateError(
        "LOCAL_RESTORE_RECOVERY_REQUIRED",
        "恢复日志不明或旧／新组不完整；已保留两组，拒绝迁移和写入",
    )
