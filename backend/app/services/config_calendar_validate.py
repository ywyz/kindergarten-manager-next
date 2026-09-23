"""Server-side full-calendar candidate validation (never trusts the client).

A new revision must cover the whole term range: exactly one row per date,
continuous, valid states, reason present for every override, and
effective = COALESCE(override, base). Any failure is data corruption or an
illegal candidate -> the caller rolls back (mapped to 409/503).
"""

from datetime import date, timedelta

_STATES = {"teaching", "non_teaching", "unknown"}
_OVERRIDES = {"teaching", "non_teaching"}


class CandidateInvalid(Exception):
    pass


def validate_full_days(term, payloads) -> None:
    start, end = term.start_date, term.end_date
    expected_count = (end - start).days + 1

    if len(payloads) != expected_count:
        raise CandidateInvalid("calendar candidate day count mismatch")

    seen: set[date] = set()
    by_date: dict[date, dict] = {}
    for payload in payloads:
        try:
            day = date.fromisoformat(payload["date"])
        except (KeyError, TypeError, ValueError) as exc:
            raise CandidateInvalid("calendar candidate has an invalid date") from exc
        if day in seen:
            raise CandidateInvalid("calendar candidate has a duplicate date")
        seen.add(day)
        by_date[day] = payload

    current = start
    while current <= end:
        payload = by_date.get(current)
        if payload is None:
            raise CandidateInvalid("calendar candidate is not continuous")

        base = payload.get("base_state")
        if base not in _STATES:
            raise CandidateInvalid("calendar candidate base state invalid")

        version = payload.get("base_library_version")
        if not isinstance(version, str) or not version:
            raise CandidateInvalid("calendar candidate library version invalid")

        override = payload.get("override_state")
        if override is not None and override not in _OVERRIDES:
            raise CandidateInvalid("calendar candidate override state invalid")

        reason = payload.get("override_reason")
        if override is not None:
            if not isinstance(reason, str) or not (1 <= len(reason.strip()) <= 200):
                raise CandidateInvalid("calendar candidate override reason invalid")
        elif reason is not None:
            raise CandidateInvalid("calendar candidate reason without override")

        expected_effective = override or base
        if payload.get("effective_state") != expected_effective:
            raise CandidateInvalid("calendar candidate effective state mismatch")

        current += timedelta(days=1)
