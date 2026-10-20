"""Build the complete persisted calendar candidate for one term.

Reuses the reviewed default-calendar rules: the pinned library's workday
judgement, ``unknown`` (never a guessed workday) for years the library does
not cover, and a runtime library failure maps to ``CALENDAR_UNAVAILABLE``
(never to "year not covered"). Week numbering comes from
``calendar_service.week_info``: Monday–Sunday weeks, week 1 is the week
containing the term start, holidays count and cross-year never resets.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.local.errors import LocalCalendarUnavailable
from app.services import calendar_service as cal


@dataclass(frozen=True)
class CalendarDayCandidate:
    day: date
    base_state: str
    base_library_version: str
    effective_state: str


def build_calendar_candidate(
    start_date: date, end_date: date
) -> tuple[list[CalendarDayCandidate], str]:
    """Return the full day snapshot and the library version used."""
    library_version = cal.library_version()
    candidates: list[CalendarDayCandidate] = []
    for day in cal.iter_dates(start_date, end_date):
        try:
            state, day_version = cal.default_state(day)
        except cal.CalendarLibraryError as exc:
            raise LocalCalendarUnavailable() from exc
        candidates.append(
            CalendarDayCandidate(
                day=day,
                base_state=state,
                base_library_version=day_version,
                effective_state=state,
            )
        )
    return candidates, library_version
