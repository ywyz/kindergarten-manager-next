"""Pure observation-month and work-date rules for listening records.

Only explicit canonical values are interpreted:

* observation month: ``YYYY-MM``
* work date: ``YYYY-MM-DD``

Legacy free text such as ``11月1—3日`` or ``上午观察`` is never parsed,
formatted or rewritten.  It is preserved unless the teacher explicitly
replaces or clears it.  When the observation month changes, every existing
work date in the affected domain must be either empty, a canonical date inside
the month/term intersection, or explicitly replaced/cleared.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date

# Canonical values are ASCII-only, matching the browser month/date inputs.
_MONTH_RE = re.compile(r"^([0-9]{4})-([0-9]{2})$")
_DATE_RE = re.compile(r"^([0-9]{4})-([0-9]{2})-([0-9]{2})$")


@dataclass(frozen=True)
class DateIssue:
    group_id: str
    position: int
    value: str
    reason: str


def parse_month(value: object) -> tuple[int, int] | None:
    if not isinstance(value, str):
        return None
    match = _MONTH_RE.fullmatch(value)
    if match is None:
        return None
    year, month = int(match.group(1)), int(match.group(2))
    if year < 1 or not 1 <= month <= 12:
        return None
    return year, month


def parse_date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    match = _DATE_RE.fullmatch(value)
    if match is None:
        return None
    try:
        return date(
            int(match.group(1)), int(match.group(2)), int(match.group(3))
        )
    except ValueError:
        return None


def month_bounds(month: tuple[int, int]) -> tuple[date, date]:
    year, number = month
    last = calendar.monthrange(year, number)[1]
    return date(year, number, 1), date(year, number, last)


def month_intersection(
    month: tuple[int, int], term_start: date, term_end: date
) -> tuple[date, date] | None:
    first, last = month_bounds(month)
    start = max(first, term_start)
    end = min(last, term_end)
    return (start, end) if start <= end else None


def term_month_text(term_start: date, term_end: date) -> tuple[str, str]:
    return (
        f"{term_start.year:04d}-{term_start.month:02d}",
        f"{term_end.year:04d}-{term_end.month:02d}",
    )


def observation_month_issue(
    value: str | None, term_start: date, term_end: date
) -> str | None:
    if value is None or value == "":
        return None
    month = parse_month(value)
    if month is None:
        return "观察月份必须是 YYYY-MM 或清空"
    if month_intersection(month, term_start, term_end) is None:
        return "观察月份不在该记录所属学期内"
    return None


def work_date_issue(
    value: str | None,
    month: tuple[int, int],
    term_start: date,
    term_end: date,
) -> str | None:
    if value is None or value == "":
        return None
    chosen = parse_date(value)
    if chosen is None:
        return "原作品日期不是规范日期，请选择日期替换或清空"
    intersection = month_intersection(month, term_start, term_end)
    if intersection is None:
        return "观察月与学期没有可用日期"
    first, last = intersection
    if not first <= chosen <= last:
        return (
            f"作品日期不在 {first.isoformat()}～{last.isoformat()} 交集内"
        )
    return None


def validate_save_dates(
    *,
    old_observation: str | None,
    new_observation: str | None,
    observation_changed: bool,
    groups: list[tuple[str, int, str | None]],
    patch_work_dates: dict[str, str | None],
    term_start: date,
    term_end: date,
) -> list[DateIssue]:
    """Validate only proactive date changes and their related group dates."""
    issues: list[DateIssue] = []
    month = None
    if observation_changed and new_observation:
        message = observation_month_issue(new_observation, term_start, term_end)
        if message is not None:
            raise ValueError(message)
        month = parse_month(new_observation)
    elif not observation_changed:
        month = parse_month(new_observation)

    for group_id, position, current in groups:
        in_patch = group_id in patch_work_dates
        proposed = patch_work_dates[group_id] if in_patch else current
        changed = in_patch and proposed != current
        if not observation_changed and not changed:
            continue
        if proposed is None or proposed == "":
            continue
        if observation_changed and new_observation is None:
            # Clearing the observation month does not rewrite legacy work dates.
            continue
        if month is None:
            if changed:
                issues.append(
                    DateIssue(
                        group_id,
                        position,
                        proposed,
                        "请先选择规范观察月份，再选择规范作品日期",
                    )
                )
            continue
        message = work_date_issue(proposed, month, term_start, term_end)
        if message is not None:
            issues.append(DateIssue(group_id, position, proposed, message))
    return issues


__all__ = [
    "DateIssue",
    "parse_month",
    "parse_date",
    "month_bounds",
    "month_intersection",
    "term_month_text",
    "observation_month_issue",
    "work_date_issue",
    "validate_save_dates",
]
