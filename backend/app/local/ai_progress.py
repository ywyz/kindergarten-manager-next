"""D2 streaming progress: bounded, in-memory, display-only attempt snapshot.

The executor writes the *current* attempt's progress here; the read-only task
progress API projects it. Nothing is persisted (no DB, log, Word, backup or
next-prompt context) and nothing here starts or retries a provider request.

Bounds: exactly one current attempt plus at most one recent completed attempt;
the reasoning text is capped (the newest tail is kept and ``truncated`` is set).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from app.local import ai_transport

REASONING_MAX_CHARS = 64 * 1024
MAX_DELTA_CHARS = 16 * 1024
MAX_CONTENT_CHARS = ai_transport.RESPONSE_MAX_BYTES

PHASES = ("waiting", "thinking", "generating", "validating", "completed", "failed", "unknown")

_LOCK = threading.Lock()


@dataclass
class _Entry:
    task_id: str
    execution_id: str
    attempt_id: str
    attempt_no: int
    seq: int = 0
    phase: str = "waiting"
    reasoning: str = ""
    truncated: bool = False
    content_chars: int = 0
    started_ticks: int = field(default_factory=ai_transport.now_ticks)
    last_data_ticks: int = 0
    ended: bool = False
    ended_at_ticks: int = 0
    final_kind: str | None = None
    final_reason: str | None = None

    def matches(self, task_id: str, execution_id: str) -> bool:
        return self.task_id == task_id and self.execution_id == execution_id


_current: _Entry | None = None
_previous: _Entry | None = None


def _matches(entry: _Entry | None, claim: Any) -> bool:
    return (
        entry is not None
        and entry.task_id == claim.task_id
        and entry.execution_id == claim.execution_id
        and entry.attempt_id == claim.attempt_id
    )


def begin(claim: Any) -> None:
    """Start a new attempt snapshot; the previous one is kept only as the most
    recent completed fallback (a live current attempt is never retained)."""
    global _current, _previous
    with _LOCK:
        if _current is not None:
            _previous = _current
        _current = _Entry(
            task_id=claim.task_id,
            execution_id=claim.execution_id,
            attempt_id=claim.attempt_id,
            attempt_no=int(getattr(claim, "attempt_no", 0) or 0),
            started_ticks=int(getattr(claim, "started_ticks", 0) or 0)
            or ai_transport.now_ticks(),
        )


def begin_ids(
    *, task_id: str, execution_id: str, attempt_id: str, attempt_no: int = 0
) -> None:
    """Same as :func:`begin` for callers that only have ids (tests)."""
    global _current, _previous
    with _LOCK:
        if _current is not None:
            _previous = _current
        _current = _Entry(
            task_id=task_id,
            execution_id=execution_id,
            attempt_id=attempt_id,
            attempt_no=int(attempt_no),
        )


def update(
    claim: Any,
    *,
    seq: int,
    phase: str,
    reasoning_delta: str = "",
    content_chars: int = 0,
) -> bool:
    """Apply one monotonic progress frame for the current attempt.

    Returns False for an old/foreign attempt, a non-monotonic seq, or an entry
    that already ended; such frames never overwrite a newer task's progress.
    """
    with _LOCK:
        entry = _current
        if entry is None or not _matches(entry, claim) or entry.ended:
            return False
        if not isinstance(seq, int) or isinstance(seq, bool) or seq <= entry.seq:
            return False
        if phase not in PHASES or phase in ("completed", "failed", "unknown"):
            return False
        entry.seq = seq
        entry.phase = phase
        if reasoning_delta:
            delta = reasoning_delta[:MAX_DELTA_CHARS]
            combined = entry.reasoning + delta
            if len(combined) > REASONING_MAX_CHARS:
                entry.reasoning = combined[-REASONING_MAX_CHARS:]
                entry.truncated = True
            else:
                entry.reasoning = combined
        data_received = bool(reasoning_delta)
        if isinstance(content_chars, int) and not isinstance(content_chars, bool):
            bounded = max(0, min(content_chars, MAX_CONTENT_CHARS))
            data_received = data_received or bounded > entry.content_chars
            entry.content_chars = bounded
        # ``last_data_age`` means real supplier data only. Local validating or a
        # repeated cumulative count must not look like a fresh network chunk.
        if data_received:
            entry.last_data_ticks = ai_transport.now_ticks()
        return True


def heartbeat(claim: Any, *, seq: int) -> bool:
    """A real SSE keepalive updates only the last-data clock and seq.

    It never changes the phase, adds reasoning/content or reopens an ended
    attempt.
    """
    with _LOCK:
        entry = _current
        if entry is None or not _matches(entry, claim) or entry.ended:
            return False
        if not isinstance(seq, int) or isinstance(seq, bool) or seq <= entry.seq:
            return False
        entry.seq = seq
        entry.last_data_ticks = ai_transport.now_ticks()
        return True


def finish(claim: Any, result: Any) -> None:
    """Mark the current attempt finished; the snapshot stays readable."""
    with _LOCK:
        entry = _current
        if entry is None or not _matches(entry, claim):
            return
        kind = result.get("kind") if isinstance(result, dict) else None
        if kind == ai_transport.SUCCESS:
            entry.phase = "completed"
        elif kind == ai_transport.UNKNOWN:
            entry.phase = "unknown"
        else:
            entry.phase = "failed"
        entry.final_kind = kind if isinstance(kind, str) else None
        entry.final_reason = (
            result.get("reason") if isinstance(result, dict) and isinstance(result.get("reason"), str) else None
        )
        if not entry.ended:
            entry.ended = True
            entry.ended_at_ticks = ai_transport.now_ticks()


def snapshot(task_id: str, execution_id: str) -> dict[str, Any] | None:
    """Bounded snapshot for exactly this task/execution, or None."""
    with _LOCK:
        for entry in (_current, _previous):
            if entry is not None and entry.matches(task_id, execution_id):
                return {
                    "task_id": entry.task_id,
                    "execution_id": entry.execution_id,
                    "attempt_id": entry.attempt_id,
                    "attempt_no": entry.attempt_no,
                    "seq": entry.seq,
                    "phase": entry.phase,
                    "reasoning": entry.reasoning,
                    "truncated": entry.truncated,
                    "content_chars": entry.content_chars,
                    "started_ticks": entry.started_ticks,
                    "last_data_ticks": entry.last_data_ticks,
                    "ended": entry.ended,
                    "ended_at_ticks": entry.ended_at_ticks,
                    "final_kind": entry.final_kind,
                    "final_reason": entry.final_reason,
                }
    return None


def clear() -> None:
    global _current, _previous
    with _LOCK:
        _current = None
        _previous = None


__all__ = [
    "MAX_CONTENT_CHARS",
    "MAX_DELTA_CHARS",
    "PHASES",
    "REASONING_MAX_CHARS",
    "begin",
    "begin_ids",
    "clear",
    "finish",
    "heartbeat",
    "snapshot",
    "update",
]
