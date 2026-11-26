"""Shared diagnostics-event contract (2026-11-24 in-app feedback adjustment).

This module is the one authoritative, fixed vocabulary for the optional
diagnostic events attached to an in-app feedback submission.  The desktop
local collector (:mod:`app.local.diagnostics`), the local transport model
(:mod:`app.local.feedback`) and the collaboration receiver
(:mod:`app.collaboration.feedback_service`) all validate against exactly
these values, so a code that was never collected — e.g. a crafted
``SYNTHETIC_PRIVATE_CANARY`` — can never travel to the admin list.

It is deliberately a leaf module: standard-library imports only, no
dependency on the local runtime or the collaboration stack, so both
deployments load it independently.

One event carries exactly four fixed fields:

- ``event_type`` — one of ``EVENT_TYPES`` (a fixed route/operation family);
- ``time`` — a UTC second-resolution stamp ``YYYY-MM-DDTHH:MM:SSZ``;
- ``result`` — one of ``RESULTS``;
- ``error_code`` — one of ``ERROR_CODES`` (a real fixed code or a fixed
  classification) for a ``failed``/``unknown`` result, ``null`` otherwise.

Never part of an event: teacher-typed content, child/class data, photos,
file paths, URLs, business ids, credentials or raw exception text.
"""

from __future__ import annotations

import re

__all__ = [
    "EVENT_TYPES",
    "RESULTS",
    "ERROR_CODES",
    "UNKNOWN_ERROR",
    "MAX_DIAGNOSTICS_EVENTS",
    "MAX_DIAGNOSTICS_JSON_CHARS",
    "FUTURE_TOLERANCE_SECONDS",
    "MIN_EVENT_YEAR",
    "TIME_PATTERN",
    "normalize_error_code",
]

# Fixed operation families (strict enum; the recorder picks one per event).
EVENT_TYPES = (
    # Host Word save/export channels (保存/导出到磁盘).
    "export_word",
    # Desktop backup engines.
    "local_backup",
    "webdav_backup",
    # Remote-version download and restore engines (WebDAV).  The restore
    # families distinguish a local-file restore from a WebDAV-staged one
    # so the fixed codes stay fine-grained without any path or URL.
    "webdav_download",
    "webdav_restore",
    "local_restore",
    # Update discovery/download outcomes.
    "update_check",
    "update_download",
    # Business record saves (real local API write routes).
    "save_daily_plan",
    "save_weekly_plan",
    "save_observation",
    "save_listening",
    "save_curriculum",
)

RESULTS = ("ok", "canceled", "failed", "unknown")

# The finite error-code vocabulary: real fixed codes from the recording
# operations plus fixed family classifications.  Anything else is merged to
# UNKNOWN_ERROR at collection time and rejected at both validation layers.
ERROR_CODES = frozenset(
    {
        # Host Word save/export: the common, desensitized host errors are
        # kept verbatim; every other save/export failure classifies as
        # EXPORT_FAILED.
        "SAVE_DIALOG_FAILED",
        "SAVE_TARGET_IN_USE",
        "SAVE_PERMISSION_DENIED",
        "SAVE_IO_ERROR",
        "SAVE_RESULT_UNKNOWN",
        "EXPORT_FAILED",
        # Backup engines: fixed families (the detailed core code stays in
        # the operation status the teacher already sees), plus the common
        # real WebDAV host/network errors kept verbatim.
        "BACKUP_FAILED",
        "WEBDAV_BACKUP_FAILED",
        "WEBDAV_CONNECT_FAILED",
        "WEBDAV_AUTH_FAILED",
        "WEBDAV_CERTIFICATE_INVALID",
        "WEBDAV_TLS_FAILED",
        "WEBDAV_TIMEOUT",
        # Remote-version download (WebDAV staging) and restore engines:
        # fixed families for the download/verify/install/reopen phases.
        # The detailed core code stays in the operation status the teacher
        # already sees; these codes never carry a path, URL or credential.
        "WEBDAV_DOWNLOAD_FAILED",
        "WEBDAV_TRANSFER_INCOMPLETE",
        "RESTORE_FAILED",
        "RESTORE_VERIFY_FAILED",
        "RESTORE_PACKAGE_INVALID",
        "RESTORE_PASSWORD_INVALID",
        "RESTORE_INSTALL_FAILED",
        "RESTORE_REOPEN_FAILED",
        "RESTORE_RECOVERY_REQUIRED",
        # Update discovery/download: the common fixed codes; other update
        # failures classify into the check/download family fallbacks.
        "UPDATE_CHECK_FAILED",
        "UPDATE_DOWNLOAD_FAILED",
        "UPDATE_DOWNLOAD_TIMEOUT",
        "UPDATE_RATE_LIMITED",
        "UPDATE_METADATA_UNAVAILABLE",
        "UPDATE_METADATA_INVALID",
        "UPDATE_ASSETS_MISSING",
        "UPDATE_TRUST_UNCONFIGURED",
        "UPDATE_STAGING_UNSAFE",
        "UPDATE_STAGING_UNAVAILABLE",
        # Business record saves: fixed classes (validation / state conflict /
        # storage).  The route's own fixed error code never travels.
        "VALIDATION_FAILED",
        "VERSION_CONFLICT",
        "STORAGE_FAILED",
        # Universal merge for anything unclassified.
        "UNKNOWN_ERROR",
    }
)

UNKNOWN_ERROR = "UNKNOWN_ERROR"

# Attachment window bounds (items and the serialized stored form).
MAX_DIAGNOSTICS_EVENTS = 50
MAX_DIAGNOSTICS_JSON_CHARS = 65_536

# A recorded stamp may be ahead of the receiving clock by this much: the
# teacher's machine is never required to be accurate to the second.
FUTURE_TOLERANCE_SECONDS = 24 * 3600
MIN_EVENT_YEAR = 2000

# Fixed UTC second-resolution stamp.
TIME_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def normalize_error_code(
    code: str | None,
    fallback: str = UNKNOWN_ERROR,
) -> str:
    """Map one operation code onto the finite vocabulary.

    A code already part of ``ERROR_CODES`` passes through; anything else
    (unknown, malformed, or simply not classified) is merged to ``fallback``
    — which itself must be a member, else ``UNKNOWN_ERROR``.
    """
    value = str(code or "")
    if value in ERROR_CODES:
        return value
    if fallback in ERROR_CODES:
        return fallback
    return UNKNOWN_ERROR
