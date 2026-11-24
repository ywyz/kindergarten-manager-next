"""Bounded local diagnostic events for the in-app feedback entry.

The store records small, fixed-shape events *at the time the original
operation happens*.  The fixed vocabulary — event types, results and the
finite error-code set — is owned by :mod:`app.diagnostics_contract` and
shared with the transport model and the collaboration receiver, so every
recorded (and forwarded) code is a real fixed code or a fixed family
classification; anything unclassified is merged to ``UNKNOWN_ERROR``.

Recorded sources:

- the desktop host Word save channels (``export_word``),
- the desktop backup engines (``local_backup`` / ``webdav_backup``),
- the update discovery/download state machine (``update_check`` /
  ``update_download``),
- the real local API record-save routes (``save_daily_plan`` …), wrapped by
  :func:`records_save_event`, which records every success and every
  validation/conflict/storage failure with a fixed classification and never
  the route's own raw identifiers or exception text.

Never recorded: input content, raw logs, exception text, paths, URLs,
originals, business ids or credentials.  A failure of this module
(recording, persisting or reading) must never hinder the business
operation: every public entry swallows its own errors and stays
best-effort.

Bounded by design:

- the process keeps at most ``MAX_STORED_EVENTS`` events and drops events
  older than ``MAX_AGE_DAYS`` (the retention also applies when a restarted
  application reloads the file);
- the feedback attachment reads only the newest events inside a
  ``FEEDBACK_WINDOW_DAYS`` window, capped at ``FEEDBACK_MAX_EVENTS`` items;
- persistence is one small JSON file under the configured data directory
  (never anywhere else; an unconfigured store is memory-only), written
  atomically.  The memory update, the pruning and the file write happen
  under one lock hold, so concurrent recorders cannot interleave partial
  snapshots and an older snapshot can never overwrite a newer one.  The
  directory swap, the bounded recovery read and the snapshot replacement
  of a rebind run under the same lock, so a slow read for one directory
  can never leak into another directory's snapshot;
- the file read is bounded (at most ``MAX_STORE_FILE_BYTES`` plus one byte)
  and a corrupt or oversized file is ignored, never repaired in place.

The store is process-memory shared between the desktop host threads and the
local API server thread; the feedback form reads it through the local API only.
"""

from __future__ import annotations

import functools
import json
import os
import threading
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.diagnostics_contract import (
    ERROR_CODES,
    EVENT_TYPES,
    RESULTS,
    TIME_PATTERN,
    UNKNOWN_ERROR,
    normalize_error_code,
)

__all__ = [
    "EVENT_TYPES",
    "RESULTS",
    "ERROR_CODES",
    "FEEDBACK_WINDOW_DAYS",
    "FEEDBACK_MAX_EVENTS",
    "MAX_STORED_EVENTS",
    "MAX_AGE_DAYS",
    "configure",
    "record",
    "recent_events",
    "records_save_event",
    "save_error_code",
    "DiagnosticsStore",
]

# Store bounds.
MAX_STORED_EVENTS = 200
MAX_AGE_DAYS = 30
# Feedback attachment bounds (the bounded window handed to the form).
FEEDBACK_WINDOW_DAYS = 7
FEEDBACK_MAX_EVENTS = 50
# One store file is at most this big; the valid event list stays far below.
MAX_STORE_FILE_BYTES = 512 * 1024

_STORE_FILENAME = "diagnostics-events.json"
_STORE_VERSION = 1


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _format_time(value: datetime) -> str:
    """UTC second-resolution stamp: ``YYYY-MM-DDTHH:MM:SSZ``."""
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_time(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc
    )


def _valid_event_dict(value: object) -> bool:
    """Strict shape check for one event (no extra keys, fixed enums)."""
    if not isinstance(value, dict):
        return False
    if set(value) != {"event_type", "time", "result", "error_code"}:
        return False
    if value.get("event_type") not in EVENT_TYPES:
        return False
    if value.get("result") not in RESULTS:
        return False
    time_value = value.get("time")
    if not isinstance(time_value, str) or TIME_PATTERN.match(time_value) is None:
        return False
    try:
        _parse_time(time_value)
    except ValueError:
        return False
    code = value.get("error_code")
    if value.get("result") in ("failed", "unknown"):
        if not isinstance(code, str) or code not in ERROR_CODES:
            return False
    else:
        if code is not None:
            return False
    return True


class DiagnosticsStore:
    """Thread-safe bounded event ring with best-effort file persistence."""

    def __init__(self, data_dir: str | Path | None = None) -> None:
        self._lock = threading.Lock()
        self._events: list[dict] = []
        self._data_dir: Path | None = (
            Path(data_dir) if data_dir is not None else None
        )
        if self._data_dir is not None:
            self._load()

    # -- configuration ----------------------------------------------------
    def bind(self, data_dir: str | Path | None) -> None:
        """(Re)bind the persistence directory; reload from it.

        Rebinding to a *different* directory resets the in-memory events to
        that directory's file (tests rely on this for isolation); rebinding
        to the same directory keeps the in-memory state.  The directory
        swap, the bounded recovery read and the snapshot replacement run
        under the same lock as ``record``/``recent_events``: a slow (or
        blocked) read for one directory can never interleave with a rebind
        and leak that directory's events into another root's snapshot.
        """
        new_dir = Path(data_dir) if data_dir is not None else None
        with self._lock:
            if new_dir == self._data_dir:
                return
            self._data_dir = new_dir
            self._events = []
            if new_dir is not None:
                self._load_locked()

    # -- persistence -------------------------------------------------------
    def _store_path(self) -> Path | None:
        data_dir = self._data_dir
        if data_dir is None:
            return None
        return data_dir / _STORE_FILENAME

    def _load(self) -> None:
        """Reload the bounded snapshot; never raises (lock-taking entry)."""
        with self._lock:
            self._load_locked()

    def _load_locked(self) -> None:
        """Bounded recovery read; the caller must already hold ``self._lock``.

        The read is bounded (at most one byte past the cap), and the
        historical retention (count and age) applies to the recovered
        events exactly as it does to new ones.  Split from ``_load`` so
        ``bind`` can order the swap, the read and the snapshot replacement
        atomically without recursively acquiring a plain ``Lock``.
        """
        path = self._store_path()
        if path is None:
            return
        try:
            with open(path, "rb") as handle:
                raw = handle.read(MAX_STORE_FILE_BYTES + 1)
        except OSError:
            return
        if len(raw) > MAX_STORE_FILE_BYTES:
            return
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict):
            return
        if payload.get("version") != _STORE_VERSION:
            return
        events = payload.get("events")
        if not isinstance(events, list):
            return
        clean = [e for e in events if _valid_event_dict(e)]
        clean = self._retention_prune(clean)
        self._events = clean

    def _persist(self, events: list[dict]) -> None:
        """Write the bounded snapshot atomically; never raises.

        The caller must hold ``self._lock``: the memory update, the pruning
        and the file write stay totally ordered, so two concurrent
        recorders can never interleave partial snapshots or let an older
        snapshot overwrite a newer one.
        """
        path = self._store_path()
        data_dir = self._data_dir
        if path is None or data_dir is None:
            return
        tmp_path: Path | None = None
        try:
            data_dir.mkdir(parents=True, exist_ok=True)
            body = json.dumps(
                {"version": _STORE_VERSION, "events": events},
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            tmp_path = data_dir / f".{_STORE_FILENAME}.{os.getpid()}.tmp"
            with open(tmp_path, "wb") as handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, path)
        except Exception:  # noqa: BLE001 - persistence is best effort
            if tmp_path is not None:
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError:
                    pass

    # -- retention ---------------------------------------------------------
    def _retention_prune(self, events: list[dict]) -> list[dict]:
        """Drop over-age and over-cap events; the newest events survive."""
        cutoff = _utcnow() - timedelta(days=MAX_AGE_DAYS)
        kept = [
            event
            for event in events
            if _parse_time(event["time"]) >= cutoff
        ]
        if len(kept) > MAX_STORED_EVENTS:
            kept = kept[-MAX_STORED_EVENTS:]
        return kept

    # -- recording ---------------------------------------------------------
    def record(
        self,
        event_type: str,
        result: str,
        error_code: str | None = None,
    ) -> bool:
        """Append one fixed-shape event; bounded and never raises.

        Returns True when the event was accepted.  Invalid combinations
        (unknown event type/result, a code on a non-failure result) are
        dropped, not guessed; a failure code outside the finite vocabulary
        is merged to ``UNKNOWN_ERROR`` instead of being stored verbatim.
        """
        if result in ("failed", "unknown") and error_code is not None:
            error_code = normalize_error_code(error_code, UNKNOWN_ERROR)
        event = {
            "event_type": event_type,
            "time": _format_time(_utcnow()),
            "result": result,
            "error_code": error_code,
        }
        if not _valid_event_dict(event):
            return False
        with self._lock:
            self._events.append(event)
            self._events = self._retention_prune(self._events)
            snapshot = list(self._events)
            self._persist(snapshot)
        return True

    # -- reading -----------------------------------------------------------
    def recent_events(
        self,
        *,
        window_days: int = FEEDBACK_WINDOW_DAYS,
        limit: int = FEEDBACK_MAX_EVENTS,
    ) -> list[dict]:
        """The bounded recent window, newest first (deep-copied dicts)."""
        window_days = max(0, int(window_days))
        limit = max(0, min(int(limit), MAX_STORED_EVENTS))
        cutoff = _utcnow() - timedelta(days=window_days)
        with self._lock:
            selected = [
                dict(event)
                for event in self._events
                if _parse_time(event["time"]) >= cutoff
            ]
        selected.reverse()
        return selected[:limit] if limit else []


# Module-level store: one per process (the desktop host threads and the
# local API server thread share it). Never written anywhere except the
# directory explicitly bound via configure().
_store = DiagnosticsStore()


def configure(data_dir: str | Path | None) -> None:
    """Bind the process store to one data directory (idempotent, no raise)."""
    try:
        _store.bind(data_dir)
    except Exception:  # noqa: BLE001 - configuration never blocks launch
        pass


def record(
    event_type: str,
    result: str,
    error_code: str | None = None,
) -> bool:
    """Record one event in the process store; never raises."""
    try:
        return _store.record(event_type, result, error_code)
    except Exception:  # noqa: BLE001 - recording never hinders business
        return False


def recent_events(
    *,
    window_days: int = FEEDBACK_WINDOW_DAYS,
    limit: int = FEEDBACK_MAX_EVENTS,
) -> list[dict]:
    """Read the bounded recent window; never raises."""
    try:
        return _store.recent_events(window_days=window_days, limit=limit)
    except Exception:  # noqa: BLE001 - reading never hinders feedback
        return []


# ---------------------------------------------------------------------------
# Business record-save events (real local API write routes)
# ---------------------------------------------------------------------------


def save_error_code(exc: BaseException) -> str:
    """Classify one local save failure into the fixed diagnostics classes.

    The route's own fixed error code (which may carry structured ids) never
    travels: only the finite classification does.
    """
    from app.local.errors import LocalValidationError

    status_code = int(getattr(exc, "status_code", 0) or 0)
    if isinstance(exc, LocalValidationError) or status_code == 422:
        return "VALIDATION_FAILED"
    if status_code >= 500:
        return "STORAGE_FAILED"
    if status_code == 409:
        return "VERSION_CONFLICT"
    code = str(getattr(exc, "code", "") or "")
    if "CONFLICT" in code:
        return "VERSION_CONFLICT"
    return UNKNOWN_ERROR


def records_save_event(event_type: str) -> Callable:
    """Decorate one real record-save route with fixed diagnostics events.

    Exactly one event is recorded per route outcome: ``ok`` on success and a
    classified failure (validation / version conflict / storage) when the
    route raises — the original error still propagates unchanged, so the
    teacher-visible behaviour is untouched.  Recording itself never raises.
    """
    if event_type not in EVENT_TYPES:
        raise ValueError(f"unknown diagnostics save event type: {event_type}")

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any):
            try:
                result = fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - re-raised below
                record(event_type, "failed", save_error_code(exc))
                raise
            record(event_type, "ok")
            return result

        return wrapper

    return decorator
