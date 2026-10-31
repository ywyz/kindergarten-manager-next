"""Typed boundary objects for the B2 restore core.

The core is deliberately backend-only: it never imports desktop, FastAPI,
webview or frontend code.  The host supplies two bounded callbacks through
``MaintenanceHooks``; all filesystem and SQLite work stays here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class RestoreProgress:
    stage: str
    done: int = 0
    total: int = 0
    message_key: str | None = None


@dataclass(frozen=True)
class PreviewDTO:
    operation_id: str
    preview_id: str
    package_name: str
    package_bytes: int
    package_sha256: str
    snapshot_id: str
    created_at: str
    app_version: str
    source_revision: str
    target_revision: str
    counts: dict[str, int]
    profile_present: bool
    profile_name: str | None
    class_name: str | None
    term_names: tuple[str, ...]
    credential_configured: bool
    credential_ready: bool
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class PreparedDTO:
    operation_id: str
    prepared_id: str
    package_sha256: str
    db_sha256: str
    assets_manifest_hash: str
    resource_count: int
    resource_bytes: int
    auth_change_count: int
    profile_present: bool


@dataclass(frozen=True)
class InstallResult:
    operation_id: str
    state: str
    protection_display_path: str
    receipt_id: str | None
    old_group_preserved: bool
    lease_released: bool
    reopen_required: bool
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReopenResult:
    operation_id: str
    state: str
    prompt_sync_error: str | None
    notice: dict[str, Any] | None = None
    error_code: str | None = None


@dataclass(frozen=True)
class RecoveryResult:
    state: str
    operation_id: str | None
    notice: dict[str, Any] | None
    receipt_id: str | None = None


@dataclass(frozen=True)
class CancelResult:
    operation_id: str
    state: str
    accepted: bool


@dataclass
class RestoreFailure(Exception):
    """A controlled restore refusal with a safe public code."""

    code: str
    phase: str
    message: str
    retryable: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        super().__init__(f"{self.code}: {self.message}")


@runtime_checkable
class MaintenanceHooks(Protocol):
    """The only host-bound operations the restore core may call."""

    def wait_host_idle(self, cancel) -> bool:
        """Wait for page saves, native IO and update work; never write DB."""

    def stop_transport(self) -> bool:
        """Stop the local HTTP service and confirm its thread is dead."""
