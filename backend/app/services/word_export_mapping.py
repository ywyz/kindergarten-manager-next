"""I5 Word export mapping (pure functions: content JSON -> template view model).

No DB, no permissions, no HTTP, no docx bytes. The mapping layer only carries
an already-selected immutable content snapshot into the fixed-template view
model and computes the ``group_activity.process`` redline. It never fills
defaults, never invents fields, never re-derives content from live sources and
never re-parses a draft.

Inputs are plain objects/attributes so the module can be unit-tested without
any database; the read service passes its pinned records in.
"""

import difflib
import re
from collections import Counter
from datetime import date, timedelta
from typing import Any, Mapping

from app.services import calendar_service as cal

KIND_DAILY = "daily_plan"
KIND_WEEKLY = "weekly_plan"

# Fixed template title; not read from content (spec 5.1 "固定字样不改写").
DAILY_MORNING_EXERCISE_LABEL = "体能大循环"

WEEKLY_COLUMN_KEYS = (
    "key_week_focus",
    "environment_setup",
    "habit_culture",
    "home_cooperation",
)

OUTDOOR_SLOT_KEYS = ("collective_1", "collective_2", "free_choice_1")

# Tokenizer: ASCII word runs, horizontal whitespace runs, otherwise one char.
# CJK characters therefore diff per character, which keeps a replaced word /
# inserted sentence red without reddening unchanged neighbours.
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[ \t]+|.", re.DOTALL)


# ---------------------------------------------------------------------------
# small shared helpers
# ---------------------------------------------------------------------------


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    """Template text: a string stays as stored, everything else is empty."""
    return value if isinstance(value, str) else ""


def _to_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def split_baseline_process(split_baseline: Any) -> str | None:
    """The only redline baseline (spec 5.5): ``group_activity_process`` text."""
    if not isinstance(split_baseline, dict):
        return None
    value = split_baseline.get("group_activity_process")
    return value if isinstance(value, str) else None


# ---------------------------------------------------------------------------
# group_activity.process redline (spec 5.5)
# ---------------------------------------------------------------------------


def _merge_runs(runs: list[dict]) -> list[dict]:
    merged: list[dict] = []
    for run in runs:
        if run["text"] == "":
            continue
        if merged and merged[-1]["red"] == run["red"]:
            merged[-1] = {
                "text": merged[-1]["text"] + run["text"],
                "red": run["red"],
            }
        else:
            merged.append({"text": run["text"], "red": run["red"]})
    if not merged:
        merged.append({"text": "", "red": False})
    return merged


def _token_runs(baseline: str, final: str) -> list[dict]:
    """Character/word diff of one paragraph: inserted/replaced text is red,
    deleted text is dropped, equal text keeps the template colour."""
    base_tokens = _TOKEN_RE.findall(baseline)
    final_tokens = _TOKEN_RE.findall(final)
    matcher = difflib.SequenceMatcher(None, base_tokens, final_tokens, autojunk=False)
    runs: list[dict] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            runs.append({"text": "".join(base_tokens[i1:i2]), "red": False})
        elif tag == "delete":
            continue
        else:  # insert / replace
            runs.append({"text": "".join(final_tokens[j1:j2]), "red": True})
    return _merge_runs(runs)


def diff_process(baseline: Any, final: Any) -> dict:
    """Redline of ``group_activity.process``.

    ``baseline`` is ``split_baseline.group_activity_process`` (None when the
    plan has no split baseline). ``final`` is the adopted process text.

    Returns ``{"has_baseline": bool, "runs": [{"text", "red"}]}``:
    - no baseline -> whole final text, no red (caller raises no_split_baseline);
    - paragraph-level matching so a purely moved paragraph is not red;
    - intra-paragraph token diff so only new/replaced text is red;
    - pure deletions are omitted, no strikethrough is modelled.
    """
    final_text = final if isinstance(final, str) else ""
    if not isinstance(baseline, str):
        return {
            "has_baseline": False,
            "runs": _merge_runs([{"text": final_text, "red": False}]),
        }

    base_paras = baseline.split("\n")
    final_paras = final_text.split("\n")
    matcher = difflib.SequenceMatcher(
        None,
        [_norm(p) for p in base_paras],
        [_norm(p) for p in final_paras],
        autojunk=False,
    )
    opcodes = matcher.get_opcodes()

    # A paragraph that only moved is a base deletion plus a final insertion
    # with identical normalised text; count those so they are not red.
    deleted_pool: Counter = Counter()
    for tag, i1, i2, _j1, _j2 in opcodes:
        if tag in ("delete", "replace"):
            for para in base_paras[i1:i2]:
                norm = _norm(para)
                if norm:
                    deleted_pool[norm] += 1

    out: list[list[dict] | None] = [None] * len(final_paras)
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            for j in range(j1, j2):
                out[j] = [{"text": final_paras[j], "red": False}]
        elif tag == "insert":
            for j in range(j1, j2):
                norm = _norm(final_paras[j])
                if norm and deleted_pool.get(norm, 0) > 0:
                    deleted_pool[norm] -= 1  # pure move -> not red
                    out[j] = [{"text": final_paras[j], "red": False}]
                else:
                    out[j] = [{"text": final_paras[j], "red": True}]
        elif tag == "delete":
            continue
        else:  # replace
            base_block = list(range(i1, i2))
            final_block = list(range(j1, j2))
            base_used: set[int] = set()
            final_moved: set[int] = set()
            # Match moved paragraphs inside the replace block first.
            for bi in base_block:
                norm = _norm(base_paras[bi])
                if not norm:
                    continue
                for j in final_block:
                    if j in final_moved:
                        continue
                    if _norm(final_paras[j]) == norm and deleted_pool.get(norm, 0) > 0:
                        deleted_pool[norm] -= 1
                        base_used.add(bi)
                        final_moved.add(j)
                        break
            rem_base = [bi for bi in base_block if bi not in base_used]
            rem_final = [j for j in final_block if j not in final_moved]
            for bi, j in zip(rem_base, rem_final):
                out[j] = _token_runs(base_paras[bi], final_paras[j])
            for j in rem_final[len(rem_base):]:
                out[j] = [{"text": final_paras[j], "red": True}]
            for j in final_moved:
                out[j] = [{"text": final_paras[j], "red": False}]

    runs: list[dict] = []
    for j in range(len(final_paras)):
        if j > 0:
            runs.append({"text": "\n", "red": False})
        runs.extend(out[j] or [{"text": final_paras[j], "red": False}])
    return {"has_baseline": True, "runs": _merge_runs(runs)}


def _norm(paragraph: str) -> str:
    return paragraph.strip()


# ---------------------------------------------------------------------------
# daily plan -> two-column template view model (spec 5.1)
# ---------------------------------------------------------------------------


def _map_morning_group(group: Any) -> dict | None:
    if not isinstance(group, dict):
        return None
    return {
        "group_id": group.get("group_id"),
        "group_kind": group.get("group_kind"),
        "games": [
            {"game_id": g.get("game_id"), "name": _text(g.get("name"))}
            for g in group.get("games") or []
            if isinstance(g, dict)
        ],
        "focus_guidance": _text(group.get("focus_guidance")),
        "shared_objectives": _text(group.get("shared_objectives")),
        "guidance_points": _text(group.get("guidance_points")),
    }


def _map_post_group(group: Any) -> dict | None:
    if not isinstance(group, dict):
        return None
    return {
        "group_id": group.get("group_id"),
        "context_kind": group.get("context_kind"),
        "area": _text(group.get("area")),
        "games": [
            {"game_id": g.get("game_id"), "name": _text(g.get("name"))}
            for g in group.get("games") or []
            if isinstance(g, dict)
        ],
        "focus_guidance": _text(group.get("focus_guidance")),
        "objectives": _text(group.get("objectives")),
        "guidance": _text(group.get("guidance")),
        "support_strategy": _text(group.get("support_strategy")),
    }


def _map_afternoon_outdoor(value: Any) -> dict | None:
    if not isinstance(value, dict):
        return None
    return {
        "group_id": value.get("group_id"),
        "area": _text(value.get("area")),
        "games": [
            {"game_id": g.get("game_id"), "name": _text(g.get("name"))}
            for g in value.get("games") or []
            if isinstance(g, dict)
        ],
        "observation_focus": _text(value.get("observation_focus")),
        "objectives": _text(value.get("objectives")),
        "guidance": _text(value.get("guidance")),
        "support_strategy": _text(value.get("support_strategy")),
    }


def map_daily_plan(record) -> dict:
    """Map one pinned daily plan record to the fixed two-column view model."""
    content = _as_dict(record.adopted_content)
    groups = [
        g for g in content.get("morning_games") or [] if isinstance(g, dict)
    ]
    collective = next(
        (g for g in groups if g.get("group_kind") == "collective"), None
    )
    free_choice = next(
        (g for g in groups if g.get("group_kind") == "free_choice"), None
    )
    talk = _as_dict(content.get("morning_talk"))
    activity = _as_dict(content.get("group_activity"))

    baseline = split_baseline_process(record.split_baseline)
    process = diff_process(baseline, activity.get("process"))

    return {
        "kind": KIND_DAILY,
        "plan_id": record.plan_id,
        "plan_date": record.plan_date,
        "week_number": record.week_number,
        "weekday": record.weekday,
        "content_id": record.content_id,
        "content_version": record.content_version,
        "header": {
            "school_name": record.school_name,
            "class_name": record.class_name,
            "grade": record.grade,
            "creator_display_name": record.creator_display_name,
        },
        "morning_exercise_label": DAILY_MORNING_EXERCISE_LABEL,
        "morning_games": {
            "collective": _map_morning_group(collective),
            "free_choice": _map_morning_group(free_choice),
        },
        "morning_talk": {
            "topic": _text(talk.get("topic")),
            "questions": _text(talk.get("questions")),
        },
        "group_activity": {
            "theme": _text(activity.get("theme")),
            "objectives": _text(activity.get("objectives")),
            "preparation": _text(activity.get("preparation")),
            "key_points": _text(activity.get("key_points")),
            "difficult_points": _text(activity.get("difficult_points")),
            "process": _text(activity.get("process")),
        },
        "post_group_games": [
            mapped
            for mapped in (
                _map_post_group(g)
                for g in content.get("post_group_games") or []
                if isinstance(g, dict)
            )
            if mapped is not None
        ],
        "afternoon_outdoor": _map_afternoon_outdoor(
            content.get("afternoon_outdoor")
        ),
        "reflection": _text(content.get("reflection")),
        "process": {
            "has_baseline": process["has_baseline"],
            "runs": process["runs"],
        },
        "warnings": list(getattr(record, "warnings", ()) or ()),
    }


# ---------------------------------------------------------------------------
# weekly plan -> fixed template view model (spec 5.2 / 5.3 / 11.7 option 1)
# ---------------------------------------------------------------------------


def compute_header_range(
    term_start: date,
    term_end: date,
    week_number: int,
    week_days: Mapping[date, str],
) -> tuple[date, date]:
    """Header start/end for one week.

    Normal weeks: min/max of the teaching days of that actual week. A
    zero-teaching-day week (section 11.7 option 1) has no teaching day, so the
    range is ``term range INTERSECT actual calendar week`` and ``min``/``max``
    are never called on an empty teaching set.
    """
    teaching = sorted(
        day for day, state in week_days.items() if state == "teaching"
    )
    if teaching:
        return teaching[0], teaching[-1]
    week_start = cal.week_anchor(term_start) + timedelta(
        days=7 * (week_number - 1)
    )
    start = max(week_start, term_start)
    end = min(week_start + timedelta(days=6), term_end)
    return start, end


def build_week_columns(
    week_days: Mapping[date, str], content: Mapping[str, Any]
) -> list[dict]:
    """One column per date of the week window, ascending, holiday expressed.

    Column set follows the export-time calendar (spec 5.3); content comes from
    the confirmed snapshot's stored ``effective`` only. ``day_state=rest``
    columns are holidays; ``plan_state=no_plan`` never empties a non-empty
    ``effective`` and is never labelled as a holiday.
    """
    by_date: dict[str, dict] = {}
    for row in content.get("deterministic") or []:
        if isinstance(row, dict) and isinstance(row.get("date"), str):
            by_date[row["date"]] = row

    columns: list[dict] = []
    for day in sorted(
        d for d in week_days if isinstance(d, date)
    ):
        state = week_days[day]
        row = by_date.get(day.isoformat())
        if state != "teaching":
            columns.append(
                {
                    "date": day.isoformat(),
                    "weekday": day.isoweekday(),
                    "day_state": "rest",
                    "holiday": True,
                    "morning_talk_topic": "",
                    "group_activity_theme": "",
                    "plan_state": None,
                    "source_missing": False,
                }
            )
            continue
        effective = _as_dict((row or {}).get("effective"))
        source = _as_dict((row or {}).get("source"))
        columns.append(
            {
                "date": day.isoformat(),
                "weekday": day.isoweekday(),
                "day_state": "teaching",
                "holiday": False,
                "morning_talk_topic": _text(
                    effective.get("morning_talk_topic")
                ),
                "group_activity_theme": _text(
                    effective.get("group_activity_theme")
                ),
                "plan_state": (row or {}).get("plan_state"),
                "source_missing": source.get("daily_plan_id") is None,
            }
        )
    return columns


def _map_weekly_slot(slot: Any) -> dict | None:
    if not isinstance(slot, dict):
        return None
    return {
        "source_kind": slot.get("source_kind"),
        "name": _text(slot.get("name")),
        "shared_objectives": _text(slot.get("shared_objectives")),
        "guidance_points": _text(slot.get("guidance_points")),
        "focus_guidance": _text(slot.get("focus_guidance")),
    }


def _map_weekly_focus(focus: Any) -> dict | None:
    if not isinstance(focus, dict):
        return None
    return {
        "source_kind": focus.get("source_kind"),
        "context_kind": focus.get("context_kind"),
        "area": _text(focus.get("area")),
        "name": _text(focus.get("name")),
        "objectives": _text(focus.get("objectives")),
        "guidance": _text(focus.get("guidance")),
        "support_strategy": _text(focus.get("support_strategy")),
    }


def map_weekly_plan(item) -> dict:
    """Map one pinned confirmed weekly snapshot to the fixed view model."""
    content = _as_dict(item.content)
    week_days = {
        day: state
        for day, state in (item.week_days or {}).items()
        if isinstance(day, date)
    }
    header_start, header_end = compute_header_range(
        item.term_start,
        item.term_end,
        item.week_number,
        week_days,
    )

    slots_raw = _as_dict(content.get("outdoor_game_slots"))
    columns_raw = _as_dict(content.get("weekly_columns"))

    return {
        "kind": KIND_WEEKLY,
        "plan_id": item.plan_id,
        "term_id": item.term_id,
        "week_number": item.week_number,
        "confirmed_version": item.confirmed_version,
        "header": {
            "school_name": item.school_name,
            "class_name": item.class_name,
            "grade": item.grade,
            "header_teacher_names": list(item.header_teacher_names or []),
            "caregiver_name": item.caregiver_name,
            "theme": _text(content.get("theme")),
        },
        "date_range": {"start": header_start, "end": header_end},
        "columns": build_week_columns(week_days, content),
        "outdoor_game_slots": {
            key: _map_weekly_slot(slots_raw.get(key))
            for key in OUTDOOR_SLOT_KEYS
        },
        "focus_area": _map_weekly_focus(content.get("focus_area")),
        "weekly_columns": {
            key: _text(columns_raw.get(key)) for key in WEEKLY_COLUMN_KEYS
        },
        "materials": content.get("materials"),
        "warnings": list(getattr(item, "warnings", ()) or ()),
    }
