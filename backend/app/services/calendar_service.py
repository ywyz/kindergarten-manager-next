"""Calendar default inputs, week numbering and snapshot construction.

The default working-day input is the pinned ``chinese_calendar`` package.
Administrator exceptions override the default; years the library does not
cover produce ``unknown`` defaults instead of guessed workdays.

The library is imported lazily so the rest of the application works before
the dependency is installed; only term/calendar builders need it. A provider
registry lets deterministic fixtures replace the real library in tests
(fixtures control only the library input; transactions remain real MySQL).
"""

from datetime import date, timedelta
from typing import Callable, Protocol

# States used on persisted calendar days.
TEACHING = "teaching"
NON_TEACHING = "non_teaching"
UNKNOWN = "unknown"
OUTSIDE_TERM = "outside_term"


class CalendarLibraryError(Exception):
    """General (non-coverage) failure of the default calendar library."""


class CalendarInputProvider(Protocol):
    def is_workday(self, day: date) -> bool: ...


# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------

_provider: CalendarInputProvider | None = None
_provider_version: str | None = None


def register_provider(provider: CalendarInputProvider, version: str) -> None:
    """Install a deterministic provider (tests/fixtures)."""
    global _provider, _provider_version
    _provider = provider
    _provider_version = version


def reset_provider() -> None:
    global _provider, _provider_version
    _provider = None
    _provider_version = None


def library_version() -> str:
    """Return the version string of the active library input.

    Uses the registered provider if present; otherwise reads the installed
    ``chinesecalendar`` distribution version without importing the package.
    """
    if _provider_version is not None:
        return _provider_version
    try:
        from importlib.metadata import PackageNotFoundError, version

        return version("chinesecalendar")
    except (ImportError, PackageNotFoundError):
        return "unavailable"


def _load_library():
    if _provider is not None:
        return _provider
    try:
        import chinese_calendar as cc  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise CalendarLibraryError("default calendar library is not installed") from exc
    return cc


def is_library_workday(day: date) -> bool:
    """Return the library's workday judgement for one day.

    Coverage gaps raise ``NotImplementedError`` (the library signals missing
    years this way); general runtime failures raise CalendarLibraryError.
    """
    lib = _load_library()
    try:
        if hasattr(lib, "is_workday"):
            return bool(lib.is_workday(day))
        return not bool(lib.is_holiday(day))
    except NotImplementedError:
        raise
    except Exception as exc:  # general library failure, not a coverage gap
        raise CalendarLibraryError(str(exc)) from exc


def default_state(day: date) -> tuple[str, str]:
    """Return ``(base_state, library_version)`` for a single date."""
    version = library_version()
    try:
        workday = is_library_workday(day)
    except NotImplementedError:
        return UNKNOWN, version
    return (TEACHING if workday else NON_TEACHING), version


# ---------------------------------------------------------------------------
# Pure week numbering
# ---------------------------------------------------------------------------


def week_anchor(start_date: date) -> date:
    """Monday of the week containing the term start date."""
    return start_date - timedelta(days=start_date.isoweekday() - 1)


def week_info(start_date: date, day: date) -> tuple[int, date, int]:
    """Return ``(week_number, week_start, weekday)`` for ``day``.

    Week 1 is the week containing the term start. Holidays do not break
    numbering, cross-year dates keep counting, and make-up workdays belong to
    their actual calendar week.
    """
    anchor = week_anchor(start_date)
    delta = (day - anchor).days
    week_number = delta // 7 + 1
    week_start = anchor + timedelta(days=7 * (week_number - 1))
    weekday = day.isoweekday()
    return week_number, week_start, weekday


# ---------------------------------------------------------------------------
# Range helpers
# ---------------------------------------------------------------------------


def iter_dates(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def validate_range(start: date, end: date, *, max_days: int) -> int:
    if start > end:
        raise ValueError("start_date must be <= end_date")
    count = (end - start).days + 1
    if count > max_days:
        raise ValueError(f"range exceeds {max_days} days")
    return count


def ranges_overlap(
    start_a: date, end_a: date, start_b: date, end_b: date
) -> bool:
    """Closed-interval overlap; sharing an endpoint counts as overlap (P1)."""
    return start_a <= end_b and start_b <= end_a
