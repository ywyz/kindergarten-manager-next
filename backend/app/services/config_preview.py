"""Immutable candidate produced by I2 configuration builders."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ChangePreview:
    kind: str
    target_id: str
    # JSON-safe normalized proposal. Term/calendar kinds embed the full
    # per-day payload so apply never regenerates the calendar.
    proposal: dict[str, Any]
    base_versions: dict[str, Any]
    changes: tuple[dict[str, Any], ...]
    impact: dict[str, Any]
    blockers: tuple[str, ...]
