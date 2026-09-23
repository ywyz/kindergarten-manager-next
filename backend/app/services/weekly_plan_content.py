"""I4 weekly plan content pure functions (structure, seeds, patch, facts).

Pure content layer: no API, no schema, no transaction, no DB access.
``entries`` are ``WeekPlanEntry`` rows for the week; ``days`` maps ISO date
-> ``teaching``/``rest``. Manual overrides live in ``override`` and survive
recompute/refresh; ``source`` is server-owned; ``effective`` is derived.
"""

import copy
from datetime import date
from typing import Any

from app import security
from app.services.weekly_plan_sync_service import WeekPlanEntry


class ContentValidationError(Exception):
    """Structure or identity violation in weekly plan content (maps to 422)."""

    code = "VALIDATION_ERROR"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


SLOT_KEYS = ("collective_1", "collective_2", "free_choice_1")
COLLECTIVE_SLOTS = ("collective_1", "collective_2")
FREE_CHOICE_SLOTS = ("free_choice_1",)
DETERMINISTIC_FIELDS = ("morning_talk_topic", "group_activity_theme")
DAILY_REF_FIELDS = (
    "daily_plan_id",
    "content_id",
    "content_version",
    "group_id",
    "game_id",
)
SOURCE_KINDS = frozenset({"daily_plan", "manual"})
SLOT_KINDS = SOURCE_KINDS  # ``ai`` reserved but rejected in I4
FOCUS_KINDS = frozenset({"daily_plan"})
WEEKLY_COLUMN_KEYS = (
    "key_week_focus",
    "environment_setup",
    "habit_culture",
    "home_cooperation",
)
DAY_STATES = frozenset({"teaching", "rest"})
PATCH_KEYS = frozenset(
    {
        "expected_draft_version",
        "theme",
        "deterministic_overrides",
        "outdoor_game_slots",
        "focus_area",
        "weekly_columns",
    }
)
OUTDOOR_SLOT_KEYS = frozenset(
    {
        "source_kind",
        "manual_item_id",
        "daily_plan_id",
        "content_id",
        "content_version",
        "group_id",
        "game_id",
        "name",
        "shared_objectives",
        "guidance_points",
        "focus_guidance",
    }
)
MANUAL_SLOT_KEYS = frozenset(
    {
        "source_kind",
        "manual_item_id",
        "daily_plan_id",
        "content_id",
        "content_version",
        "group_id",
        "game_id",
        "name",
        "shared_objectives",
        "guidance_points",
        "focus_guidance",
    }
)
FOCUS_KEYS = frozenset(
    {
        "source_kind",
        "manual_item_id",
        "daily_plan_id",
        "content_id",
        "content_version",
        "group_id",
        "game_id",
        "context_kind",
        "area",
        "name",
        "objectives",
        "guidance",
        "support_strategy",
    }
)


def build_source_candidates(entries) -> list[dict]:
    """Outdoor + focus candidates with ``source_section`` / ``category``.

    Outdoor candidates come only from ``morning_games`` (category
    ``collective``/``free_choice``); focus candidates only from
    ``post_group_games`` (category ``focus`` with ``context_kind``).
    Whole-group text always comes from the same source group.
    """
    candidates: list[dict] = []
    for entry in _sorted_entries(entries):
        content = entry.adopted_content or {}
        base = {
            "daily_plan_id": entry.plan_id,
            "content_id": entry.content_id,
            "content_version": entry.content_version,
            "date": entry.plan_date.isoformat(),
        }

        for group in content.get("morning_games") or []:
            if not isinstance(group, dict):
                continue
            group_id = group.get("group_id")
            if not isinstance(group_id, str) or not group_id:
                continue
            group_kind = group.get("group_kind")
            if group_kind != "collective" and group_kind != "free_choice":
                continue
            for game in group.get("games") or []:
                if not isinstance(game, dict):
                    continue
                game_id = game.get("game_id")
                if not isinstance(game_id, str) or not game_id:
                    continue
                name = game.get("name")
                if not isinstance(name, str):
                    continue
                item = dict(base)
                item.update(
                    {
                        "source_kind": "daily_plan",
                        "source_section": "morning_games",
                        "category": group_kind,
                        "group_kind": group_kind,
                        "context_kind": None,
                        "group_id": group_id,
                        "game_id": game_id,
                        "name": name,
                        "shared_objectives": group.get("shared_objectives"),
                        "guidance_points": group.get("guidance_points"),
                        "focus_guidance": group.get("focus_guidance"),
                    }
                )
                candidates.append(item)

        for group in content.get("post_group_games") or []:
            if not isinstance(group, dict):
                continue
            group_id = group.get("group_id")
            if not isinstance(group_id, str) or not group_id:
                continue
            context_kind = group.get("context_kind")
            if context_kind != "area" and context_kind != "outdoor" and context_kind != "special_room":
                continue
            for game in group.get("games") or []:
                if not isinstance(game, dict):
                    continue
                game_id = game.get("game_id")
                if not isinstance(game_id, str) or not game_id:
                    continue
                name = game.get("name")
                if not isinstance(name, str):
                    continue
                item = dict(base)
                item.update(
                    {
                        "source_kind": "daily_plan",
                        "source_section": "post_group_games",
                        "category": "focus",
                        "group_kind": None,
                        "context_kind": context_kind,
                        "area": group.get("area"),
                        "group_id": group_id,
                        "game_id": game_id,
                        "name": name,
                        "objectives": group.get("objectives"),
                        "guidance": group.get("guidance"),
                        "support_strategy": group.get("support_strategy"),
                    }
                )
                candidates.append(item)
    return candidates


def build_deterministic(
    entries,
    days: dict[date, str],
    previous: dict | None = None,
    *,
    overrides: dict[str, dict] | None = None,
) -> list[dict]:
    """Per-date source / override / effective three-layer rows for the week.

    ``source`` is recomputed from the current daily plan; ``override`` is
    taken from the explicit ``overrides`` mapping when given, otherwise from
    ``previous``'s deterministic rows; ``effective`` derives per field.
    Rest days always keep an all-null ``source``. ``previous``/``overrides``
    inputs are not mutated.
    """
    entries_by_date: dict[date, WeekPlanEntry] = {}
    for entry in _sorted_entries(entries):
        if entry.plan_date not in days:
            continue
        day_state = days.get(entry.plan_date)
        if day_state != "teaching":
            continue
        entries_by_date.setdefault(entry.plan_date, entry)

    if overrides is not None:
        previous_overrides = {
            day: {
                "morning_talk_topic": (value or {}).get("morning_talk_topic"),
                "group_activity_theme": (value or {}).get(
                    "group_activity_theme"
                ),
            }
            for day, value in overrides.items()
        }
    else:
        previous_overrides = _previous_overrides(previous)

    ordered_dates = sorted(days, key=_date_sort_key)

    rows: list[dict] = []
    for day in ordered_dates:
        day_state = days[day]
        if day_state not in DAY_STATES:
            continue

        if day_state == "rest":
            plan_state = "none_required"
            source = {
                "daily_plan_id": None,
                "content_id": None,
                "content_version": None,
                "morning_talk_topic": None,
                "group_activity_theme": None,
            }
        else:
            if day in entries_by_date:
                plan_state = "saved"
                entry = entries_by_date[day]
                content = entry.adopted_content or {}
                talk = content.get("morning_talk") or {}
                activity = content.get("group_activity") or {}
                source = {
                    "daily_plan_id": entry.plan_id,
                    "content_id": entry.content_id,
                    "content_version": entry.content_version,
                    "morning_talk_topic": talk.get("topic") or "",
                    "group_activity_theme": activity.get("theme") or "",
                }
            else:
                plan_state = "no_plan"
                source = {
                    "daily_plan_id": None,
                    "content_id": None,
                    "content_version": None,
                    "morning_talk_topic": None,
                    "group_activity_theme": None,
                }

        override = previous_overrides.get(
            day.isoformat(),
            {"morning_talk_topic": None, "group_activity_theme": None},
        )
        override = {
            "morning_talk_topic": override.get("morning_talk_topic"),
            "group_activity_theme": override.get("group_activity_theme"),
        }
        effective = {
            field: (
                override[field] if override[field] is not None else source[field]
            )
            for field in DETERMINISTIC_FIELDS
        }
        rows.append(
            {
                "date": day.isoformat(),
                "day_state": day_state,
                "plan_state": plan_state,
                "source": source,
                "override": override,
                "effective": effective,
            }
        )
    return rows


def new_content(
    entries, days: dict[date, str], theme: str | None = None
) -> dict[str, Any]:
    """Seed draft content: deterministic layers, empty manual regions."""
    if theme is None:
        theme = ""
    if not isinstance(theme, str):
        raise ContentValidationError("theme 必须是字符串")

    return {
        "theme": theme,
        "deterministic": build_deterministic(entries, days),
        "outdoor_game_slots": {key: None for key in SLOT_KEYS},
        "focus_area": None,
        "weekly_columns": {key: "" for key in WEEKLY_COLUMN_KEYS},
        "materials": None,
    }


def prepare_patch(
    previous: dict,
    patch: dict,
    entries,
    days: dict[date, str],
) -> dict[str, Any]:
    """Validate a PATCH payload and return a deep-copied new draft content.

    ``source``/``effective`` recompute from current entries; explicit
    override nulls clear prior overrides while omitted dates keep them.
    Same-identity daily refs keep the entire previous object (no re-stamp);
    only new/changed identities re-resolve current sources. Omitted slot /
    weekly_columns subfields inherit previous values. Existing manual ids
    stay stable; new manual entries get a server-generated id.
    """
    if not isinstance(previous, dict):
        raise ContentValidationError("previous content 必须是 JSON 对象")
    if not isinstance(patch, dict):
        raise ContentValidationError("patch 必须是 JSON 对象")

    unknown = set(patch) - PATCH_KEYS
    if unknown:
        raise ContentValidationError(f"未知字段：{sorted(unknown)}")

    known_manual_ids = _manual_item_ids(previous)
    used_manual_ids: set[str] = set()  # final-slot dedup, starts empty
    reserved_ids = set(known_manual_ids)

    if "theme" in patch:
        theme = patch["theme"]
        if theme is None:
            theme = ""
        if not isinstance(theme, str):
            raise ContentValidationError("theme 必须是字符串")
        result_theme = theme
    else:
        result_theme = previous.get("theme")
        if result_theme is None:
            result_theme = ""

    if "deterministic_overrides" in patch:
        merged_overrides = _merge_overrides(
            previous, patch["deterministic_overrides"], days
        )
    else:
        merged_overrides = _previous_overrides(previous)
    deterministic = build_deterministic(
        entries, days, overrides=merged_overrides
    )

    previous_slots_raw = previous.get("outdoor_game_slots") or {}
    previous_slots = {
        key: previous_slots_raw.get(key) for key in SLOT_KEYS
    }
    if "outdoor_game_slots" in patch:
        outdoor_game_slots = _prepare_slots(
            patch["outdoor_game_slots"],
            entries,
            previous_slots=previous_slots,
            known_manual_ids=known_manual_ids,
            used_manual_ids=used_manual_ids,
            reserved_ids=reserved_ids,
        )
    else:
        outdoor_game_slots = _validate_slots(
            previous_slots,
            entries,
            used_manual_ids=used_manual_ids,
            reserved_ids=reserved_ids,
        )

    if "focus_area" in patch:
        focus_area = _prepare_focus(
            patch["focus_area"], entries, previous_focus=previous.get("focus_area")
        )
    else:
        focus_area = _validate_focus(previous.get("focus_area"), entries)

    if "weekly_columns" in patch:
        weekly_columns = _prepare_weekly_columns(
            patch["weekly_columns"], previous.get("weekly_columns") or {}
        )
    else:
        weekly_columns = _prepare_weekly_columns(
            previous.get("weekly_columns") or {}
        )

    return {
        "theme": result_theme,
        "deterministic": deterministic,
        "outdoor_game_slots": outdoor_game_slots,
        "focus_area": focus_area,
        "weekly_columns": weekly_columns,
        "materials": None,
    }


def refresh_content(
    previous: dict, entries, days: dict[date, str]
) -> tuple[dict[str, Any], list[dict]]:
    """Recompute deterministic layers and re-resolve existing daily refs.

    Manual regions (theme, overrides, weekly_columns, manual games) are kept.
    ``daily_plan`` refs that still exist refresh to current
    ``content_id``/``content_version`` and whole-group text; vanished refs
    keep the old entry and a missing audit note. Audit also records every
    deterministic source ``from``/``to`` change (including null -> real).
    Post-refresh same-category same-name collisions raise
    ``ContentValidationError`` (no silent drop of manual choices).
    """
    if not isinstance(previous, dict):
        raise ContentValidationError("previous content 必须是 JSON 对象")

    audit: list[dict] = []
    result: dict[str, Any] = {}

    result["theme"] = previous.get("theme")
    if result["theme"] is None:
        result["theme"] = ""

    previous_rows = previous.get("deterministic") or []
    result["deterministic"] = build_deterministic(entries, days, previous)
    current_by_date = {
        row["date"]: row for row in result["deterministic"]
    }
    for old_row in previous_rows:
        if not isinstance(old_row, dict):
            continue
        day_key = old_row.get("date")
        new_row = current_by_date.get(day_key)
        if new_row is None:
            continue
        old_source = old_row.get("source") or {}
        new_source = new_row.get("source") or {}
        from_key = {
            "daily_plan_id": old_source.get("daily_plan_id"),
            "content_id": old_source.get("content_id"),
            "content_version": old_source.get("content_version"),
        }
        to_key = {
            "daily_plan_id": new_source.get("daily_plan_id"),
            "content_id": new_source.get("content_id"),
            "content_version": new_source.get("content_version"),
        }
        if from_key != to_key:
            audit.append(
                {
                    "slot": "deterministic",
                    "date": day_key,
                    "from": from_key,
                    "to": to_key,
                    "missing": to_key["daily_plan_id"] is None,
                    "current_item_exists": to_key["daily_plan_id"] is not None,
                }
            )

    outdoor_by_ref = _outdoor_candidates_by_ref(entries)
    focus_by_ref = _focus_candidates_by_ref(entries)

    previous_slots_raw = previous.get("outdoor_game_slots") or {}
    refreshed_slots: dict[str, Any] = {}
    for slot_key in SLOT_KEYS:
        slot = previous_slots_raw.get(slot_key)
        if slot is None:
            refreshed_slots[slot_key] = None
            continue
        if not isinstance(slot, dict):
            raise ContentValidationError(f"槽位 {slot_key} 必须是对象或 null")
        kind = slot.get("source_kind")
        if kind == "manual":
            refreshed_slots[slot_key] = copy.deepcopy(slot)
            continue
        if kind != "daily_plan":
            raise ContentValidationError(f"槽位 {slot_key} 的 source_kind 非法")

        ref = (
            slot.get("daily_plan_id"),
            slot.get("group_id"),
            slot.get("game_id"),
        )
        candidate = outdoor_by_ref.get(ref)
        if candidate is None:
            # Source vanished: keep old ref/text, do not fabricate.
            refreshed_slots[slot_key] = copy.deepcopy(slot)
            audit.append(
                {
                    "slot": slot_key,
                    "kind": "missing_facts",
                    "daily_plan_id": slot.get("daily_plan_id"),
                    "group_id": slot.get("group_id"),
                    "game_id": slot.get("game_id"),
                    "from": {
                        "content_id": slot.get("content_id"),
                        "content_version": slot.get("content_version"),
                    },
                    "to": None,
                    "missing": True,
                    "current_item_exists": False,
                }
            )
            continue

        updated = {
            "source_kind": "daily_plan",
            "manual_item_id": None,
            "daily_plan_id": candidate["daily_plan_id"],
            "content_id": candidate["content_id"],
            "content_version": candidate["content_version"],
            "group_id": candidate["group_id"],
            "game_id": candidate["game_id"],
            "name": candidate["name"],
            "shared_objectives": candidate["shared_objectives"],
            "guidance_points": candidate["guidance_points"],
            "focus_guidance": candidate["focus_guidance"],
        }
        refreshed_slots[slot_key] = updated
        from_key = {
            "content_id": slot.get("content_id"),
            "content_version": slot.get("content_version"),
        }
        to_key = {
            "content_id": candidate["content_id"],
            "content_version": candidate["content_version"],
        }
        if from_key != to_key:
            audit.append(
                {
                    "slot": slot_key,
                    "kind": "refreshed",
                    "daily_plan_id": candidate["daily_plan_id"],
                    "group_id": candidate["group_id"],
                    "game_id": candidate["game_id"],
                    "from": from_key,
                    "to": to_key,
                    "missing": False,
                    "current_item_exists": True,
                }
            )

    # Post-refresh same-name collision must fail loudly, not silently.
    _assert_slot_name_uniqueness(refreshed_slots)

    focus = previous.get("focus_area")
    if focus is None:
        result_focus = None
    else:
        if not isinstance(focus, dict):
            raise ContentValidationError("focus_area 必须是对象或 null")
        if focus.get("source_kind") != "daily_plan":
            raise ContentValidationError(
                "focus_area 的 source_kind 必须是 daily_plan 或 null"
            )
        ref = (
            focus.get("daily_plan_id"),
            focus.get("group_id"),
            focus.get("game_id"),
        )
        candidate_focus = focus_by_ref.get(ref)
        if candidate_focus is None:
            result_focus = copy.deepcopy(focus)
            audit.append(
                {
                    "slot": "focus_area",
                    "kind": "missing_facts",
                    "daily_plan_id": focus.get("daily_plan_id"),
                    "group_id": focus.get("group_id"),
                    "game_id": focus.get("game_id"),
                    "from": {
                        "content_id": focus.get("content_id"),
                        "content_version": focus.get("content_version"),
                    },
                    "to": None,
                    "missing": True,
                    "current_item_exists": False,
                }
            )
        else:
            result_focus = {
                "source_kind": "daily_plan",
                "daily_plan_id": candidate_focus["daily_plan_id"],
                "content_id": candidate_focus["content_id"],
                "content_version": candidate_focus["content_version"],
                "group_id": candidate_focus["group_id"],
                "game_id": candidate_focus["game_id"],
                "context_kind": candidate_focus["context_kind"],
                "area": candidate_focus["area"],
                "name": candidate_focus["name"],
                "objectives": candidate_focus["objectives"],
                "guidance": candidate_focus["guidance"],
                "support_strategy": candidate_focus["support_strategy"],
            }
            from_key = {
                "content_id": focus.get("content_id"),
                "content_version": focus.get("content_version"),
            }
            to_key = {
                "content_id": candidate_focus["content_id"],
                "content_version": candidate_focus["content_version"],
            }
            if from_key != to_key:
                audit.append(
                    {
                        "slot": "focus_area",
                        "kind": "refreshed",
                        "daily_plan_id": candidate_focus["daily_plan_id"],
                        "group_id": candidate_focus["group_id"],
                        "game_id": candidate_focus["game_id"],
                        "from": from_key,
                        "to": to_key,
                        "missing": False,
                        "current_item_exists": True,
                    }
                )

    result["outdoor_game_slots"] = refreshed_slots
    result["focus_area"] = result_focus
    result["weekly_columns"] = _prepare_weekly_columns(
        previous.get("weekly_columns") or {},
        previous.get("weekly_columns") or {},
    )
    result["materials"] = None
    return result, audit


def build_facts(
    content: dict, entries, days: dict[date, str]
) -> dict[str, Any]:
    """System missing/stale facts for confirm (``ack``/``note`` excluded).

    Stale compares ``daily_plan_id``/``content_id``/``content_version``
    including null -> real (deterministic gain a plan). Vanished refs
    produce missing AND stale with both-side keys and
    ``current_item_exists=false``. Manual refs skip version compare but not
    content emptiness. Empty weekly columns, empty selected game names /
    objectives / guidance, empty focus and materials are missing facts.
    """
    if not isinstance(content, dict):
        raise ContentValidationError("content 必须是 JSON 对象")

    missing: list[dict] = []
    stale_sources: list[dict] = []

    if not (content.get("theme") or ""):
        missing.append({"kind": "empty_theme"})

    entries_by_date = {
        e.plan_date: e
        for e in _sorted_entries(entries)
        if e.plan_date in days and days.get(e.plan_date) == "teaching"
    }
    for row in content.get("deterministic") or []:
        if not isinstance(row, dict):
            continue
        day = _parse_date(row.get("date"))
        if day is None:
            continue
        day_state = days.get(day)
        source = row.get("source") or {}
        effective = row.get("effective") or {}

        if day_state == "rest":
            continue

        if day_state == "teaching" and source.get("daily_plan_id") is None:
            missing.append(
                {"kind": "missing_daily_plan_date", "date": row.get("date")}
            )

        # Unified stale compare: null->real included; both-side keys recorded.
        entry = entries_by_date.get(day)
        draft_key = {
            "daily_plan_id": source.get("daily_plan_id"),
            "content_id": source.get("content_id"),
            "content_version": source.get("content_version"),
        }
        if entry is None:
            current_key = {
                "daily_plan_id": None,
                "content_id": None,
                "content_version": None,
            }
        else:
            current_key = {
                "daily_plan_id": entry.plan_id,
                "content_id": entry.content_id,
                "content_version": entry.content_version,
            }
        if draft_key != current_key:
            stale_sources.append(
                {
                    "slot": "deterministic",
                    "date": row.get("date"),
                    "group_id": None,
                    "game_id": None,
                    "draft": draft_key,
                    "current": current_key,
                    "daily_plan_id": draft_key["daily_plan_id"],
                    "current_daily_plan_id": current_key["daily_plan_id"],
                    "current_item_exists": entry is not None,
                }
            )
            if source.get("daily_plan_id") is not None and entry is None:
                missing.append(
                    {
                        "kind": "source_missing",
                        "date": row.get("date"),
                        "daily_plan_id": source.get("daily_plan_id"),
                        "content_id": source.get("content_id"),
                        "content_version": source.get("content_version"),
                    }
                )

        if day_state == "teaching":
            for field in DETERMINISTIC_FIELDS:
                value = effective.get(field)
                if value is None or value == "":
                    missing.append(
                        {
                            "kind": "empty_field",
                            "date": row.get("date"),
                            "field": field,
                        }
                    )

    columns = content.get("weekly_columns") or {}
    for key in WEEKLY_COLUMN_KEYS:
        if not (columns.get(key) or ""):
            missing.append({"kind": "empty_field", "field": f"weekly_columns.{key}"})

    slots = content.get("outdoor_game_slots") or {}
    for slot_key in SLOT_KEYS:
        slot = slots.get(slot_key)
        if slot is None:
            missing.append({"kind": "outdoor_slot", "slot": slot_key})
            continue
        _collect_ref_facts(slot, slot_key, entries, missing, stale_sources)

    focus = content.get("focus_area")
    if focus is None:
        missing.append({"kind": "empty_field", "field": "focus_area"})
    else:
        _collect_ref_facts(focus, "focus_area", entries, missing, stale_sources)

    if content.get("materials") is not None:
        raise ContentValidationError("materials 在 I4 必须为 null")
    missing.append({"kind": "materials"})

    return {"missing": missing, "stale_sources": stale_sources}


def _collect_ref_facts(
    ref: dict,
    slot_key: str,
    entries,
    missing: list[dict],
    stale_sources: list[dict],
) -> None:
    if not isinstance(ref, dict):
        raise ContentValidationError(f"{slot_key} 必须是对象或 null")
    kind = ref.get("source_kind")
    if not isinstance(kind, str):
        raise ContentValidationError(f"{slot_key} 的 source_kind 必须是字符串")

    if slot_key == "focus_area" and kind != "daily_plan":
        raise ContentValidationError(
            "focus_area 的 source_kind 必须是 daily_plan 或 null"
        )
    if kind != "daily_plan" and kind != "manual":
        raise ContentValidationError(f"{slot_key} 的 source_kind 非法")

    if kind == "manual":
        if not ref.get("manual_item_id"):
            missing.append({"kind": "manual_item_missing", "slot": slot_key})
        _collect_content_emptiness(ref, slot_key, missing, is_manual=True)
        return  # manual skips version compare only

    for field in DAILY_REF_FIELDS:
        value = ref.get(field)
        if value is None:
            missing.append(
                {"kind": "source_missing", "slot": slot_key, "field": field}
            )
            return
        if field == "content_version":
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                missing.append(
                    {"kind": "source_missing", "slot": slot_key, "field": field}
                )
                return
        elif not isinstance(value, str) or not value:
            missing.append(
                {"kind": "source_missing", "slot": slot_key, "field": field}
            )
            return

    daily_plan_id = ref["daily_plan_id"]
    entry = next(
        (e for e in _sorted_entries(entries) if e.plan_id == daily_plan_id),
        None,
    )
    group_id = ref["group_id"]
    game_id = ref["game_id"]

    draft = {
        "content_id": ref["content_id"],
        "content_version": ref["content_version"],
    }
    if entry is None:
        current = {"content_id": None, "content_version": None}
        missing.append(
            {
                "kind": "source_missing",
                "slot": slot_key,
                "daily_plan_id": daily_plan_id,
                "group_id": group_id,
                "game_id": game_id,
                "content_id": draft["content_id"],
                "content_version": draft["content_version"],
            }
        )
        stale_sources.append(
            {
                "slot": slot_key,
                "daily_plan_id": daily_plan_id,
                "group_id": group_id,
                "game_id": game_id,
                "draft": draft,
                "current": current,
                "current_daily_plan_id": None,
                "current_item_exists": False,
            }
        )
        _collect_content_emptiness(ref, slot_key, missing, is_manual=False)
        return

    current = {
        "content_id": entry.content_id,
        "content_version": entry.content_version,
    }
    stale = draft != current
    item_exists = _ref_exists_in_content(entry, group_id, game_id)
    if not item_exists:
        missing.append(
            {
                "kind": "source_missing",
                "slot": slot_key,
                "daily_plan_id": daily_plan_id,
                "group_id": group_id,
                "game_id": game_id,
                "content_id": draft["content_id"],
                "content_version": draft["content_version"],
            }
        )
    if stale:
        stale_sources.append(
            {
                "slot": slot_key,
                "daily_plan_id": daily_plan_id,
                "group_id": group_id,
                "game_id": game_id,
                "draft": draft,
                "current": current,
                "current_daily_plan_id": entry.plan_id,
                "current_item_exists": item_exists,
            }
        )
    _collect_content_emptiness(ref, slot_key, missing, is_manual=False)


def _collect_content_emptiness(
    ref: dict, slot_key: str, missing: list[dict], *, is_manual: bool
) -> None:
    if not (ref.get("name") or ""):
        missing.append(
            {"kind": "empty_field", "slot": slot_key, "field": "name"}
        )
    if is_manual:
        text_fields = (
            "shared_objectives",
            "guidance_points",
            "focus_guidance",
        )
    elif slot_key == "focus_area":
        text_fields = ("objectives", "guidance")
    else:
        text_fields = ("shared_objectives", "guidance_points")
    for field in text_fields:
        if not (ref.get(field) or ""):
            missing.append(
                {"kind": "empty_field", "slot": slot_key, "field": field}
            )


def _sorted_entries(entries) -> list[WeekPlanEntry]:
    return sorted(entries, key=lambda e: (e.plan_date, e.plan_id))


def _date_sort_key(day: date) -> tuple[int, int, int]:
    return (day.year, day.month, day.day)


def _parse_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _previous_overrides(previous: dict | None) -> dict[str, dict]:
    if not isinstance(previous, dict):
        return {}
    overrides: dict[str, dict] = {}
    for row in previous.get("deterministic") or []:
        if not isinstance(row, dict):
            continue
        day = row.get("date")
        if not isinstance(day, str):
            continue
        override = row.get("override") or {}
        overrides[day] = {
            "morning_talk_topic": override.get("morning_talk_topic"),
            "group_activity_theme": override.get("group_activity_theme"),
        }
    return overrides


def _merge_overrides(
    previous: dict, payload: Any, days: dict[date, str]
) -> dict[str, dict]:
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ContentValidationError("deterministic_overrides 必须是 JSON 对象")

    merged = _previous_overrides(previous)
    allowed_dates = {day.isoformat() for day in days}
    for day_key, value in payload.items():
        if not isinstance(day_key, str):
            raise ContentValidationError(
                "deterministic_overrides 的日期键必须是字符串"
            )
        if day_key not in allowed_dates:
            raise ContentValidationError(
                f"deterministic_overrides 含未知日期：{day_key}"
            )
        if value is None:
            value = {}
        if not isinstance(value, dict):
            raise ContentValidationError("deterministic_overrides 的值必须是对象")
        unknown = set(value) - set(DETERMINISTIC_FIELDS)
        if unknown:
            raise ContentValidationError(
                f"deterministic_overrides 含未知字段：{sorted(unknown)}"
            )
        current = merged.get(
            day_key,
            {"morning_talk_topic": None, "group_activity_theme": None},
        )
        updated = dict(current)
        for field in DETERMINISTIC_FIELDS:
            if field in value:
                field_value = value[field]
                if field_value is not None and not isinstance(field_value, str):
                    raise ContentValidationError(
                        f"deterministic_overrides.{field} 必须是字符串或 null"
                    )
                updated[field] = field_value
        merged[day_key] = updated
    return merged


def _outdoor_candidates_by_ref(entries) -> dict[tuple, dict]:
    by_key: dict[tuple, dict] = {}
    for candidate in build_source_candidates(entries):
        if candidate.get("source_section") != "morning_games":
            continue
        key = (
            candidate["daily_plan_id"],
            candidate["group_id"],
            candidate["game_id"],
        )
        by_key[key] = candidate
    return by_key


def _focus_candidates_by_ref(entries) -> dict[tuple, dict]:
    by_key: dict[tuple, dict] = {}
    for candidate in build_source_candidates(entries):
        if candidate.get("source_section") != "post_group_games":
            continue
        key = (
            candidate["daily_plan_id"],
            candidate["group_id"],
            candidate["game_id"],
        )
        by_key[key] = candidate
    return by_key


def _ref_exists_in_content(entry: WeekPlanEntry, group_id, game_id) -> bool:
    if not isinstance(group_id, str) or not isinstance(game_id, str):
        return False
    content = entry.adopted_content or {}
    for section in ("morning_games", "post_group_games"):
        for group in content.get(section) or []:
            if isinstance(group, dict) and group.get("group_id") == group_id:
                for game in group.get("games") or []:
                    if isinstance(game, dict) and game.get("game_id") == game_id:
                        return True
    return False


def _manual_item_ids(previous: dict) -> set[str]:
    ids: set[str] = set()
    if not isinstance(previous, dict):
        return ids
    slots = previous.get("outdoor_game_slots") or {}
    for slot_key in SLOT_KEYS:
        slot = slots.get(slot_key)
        if isinstance(slot, dict) and slot.get("source_kind") == "manual":
            manual_id = slot.get("manual_item_id")
            if isinstance(manual_id, str):
                ids.add(manual_id)
    return ids


def _reject_unknown_keys(obj: dict, allowed: frozenset[str], label: str) -> None:
    unknown = set(obj) - set(allowed)
    if unknown:
        raise ContentValidationError(f"{label} 含未知字段：{sorted(unknown)}")


def _validate_ref_fields(obj: dict, label: str) -> None:
    for field in DAILY_REF_FIELDS:
        value = obj.get(field)
        if field == "content_version":
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 1
            ):
                raise ContentValidationError(f"{label}.{field} 必须是正整数")
        else:
            if not isinstance(value, str) or not value:
                raise ContentValidationError(f"{label}.{field} 必须是非空字符串")


def _same_identity(obj: dict, previous_obj: dict | None) -> bool:
    if not isinstance(previous_obj, dict):
        return False
    if previous_obj.get("source_kind") != obj.get("source_kind"):
        return False
    if obj.get("source_kind") == "manual":
        return bool(obj.get("manual_item_id")) and (
            obj.get("manual_item_id") == previous_obj.get("manual_item_id")
        )
    return all(
        obj.get(field) == previous_obj.get(field)
        for field in ("daily_plan_id", "group_id", "game_id")
    )


def _assert_slot_name_uniqueness(slots: dict) -> None:
    seen: dict[str, str] = {}
    for slot_key in COLLECTIVE_SLOTS:
        slot = slots.get(slot_key)
        if not isinstance(slot, dict):
            continue
        name = slot.get("name")
        if not isinstance(name, str) or not name:
            continue
        if name in seen:
            raise ContentValidationError(
                f"同类别同名游戏 {name} 同时占据 {seen[name]} 与 {slot_key}，请明确改选"
            )
        seen[name] = slot_key
    for slot_key in FREE_CHOICE_SLOTS:
        slot = slots.get(slot_key)
        if not isinstance(slot, dict):
            continue
        name = slot.get("name")
        if not isinstance(name, str) or not name:
            continue
        # free_choice is its own category: only self-collision possible
        # (single slot), kept for symmetry with category rules.
        _ = name


def _validate_slots(
    slots: dict,
    entries,
    *,
    used_manual_ids: set[str],
    reserved_ids: set[str],
) -> dict[str, Any]:
    if not isinstance(slots, dict):
        raise ContentValidationError("outdoor_game_slots 必须是 JSON 对象")
    _reject_unknown_keys(slots, frozenset(SLOT_KEYS), "outdoor_game_slots")
    result: dict[str, Any] = {}

    for slot_key in SLOT_KEYS:
        slot = slots.get(slot_key)
        if slot is None:
            result[slot_key] = None
            continue
        if not isinstance(slot, dict):
            raise ContentValidationError(f"槽位 {slot_key} 必须是对象或 null")
        kind = slot.get("source_kind")
        if not isinstance(kind, str) or (
            kind != "daily_plan" and kind != "manual"
        ):
            raise ContentValidationError(
                f"槽位 {slot_key} 的 source_kind 必须是 daily_plan 或 manual"
            )
        if kind == "daily_plan":
            _reject_unknown_keys(
                slot, OUTDOOR_SLOT_KEYS, f"槽位 {slot_key}"
            )
            if slot.get("manual_item_id") is not None:
                raise ContentValidationError(
                    f"槽位 {slot_key} 的 daily_plan 条目不得携带 manual_item_id"
                )
            _validate_ref_fields(slot, f"槽位 {slot_key}")
            # Existing refs are not re-stamped: identity+text kept as-is;
            # candidates may have moved on (stale is a facts concern).
            name = slot.get("name")
            if not isinstance(name, str):
                raise ContentValidationError(f"槽位 {slot_key} 缺少名称")
            result[slot_key] = copy.deepcopy(slot)
        else:
            _reject_unknown_keys(slot, MANUAL_SLOT_KEYS, f"槽位 {slot_key}")
            _assert_manual_refs_null(slot, f"槽位 {slot_key}")
            manual_id = slot.get("manual_item_id")
            if not isinstance(manual_id, str) or not manual_id:
                raise ContentValidationError(
                    f"槽位 {slot_key} 的 manual 条目缺少 manual_item_id"
                )
            if manual_id in used_manual_ids:
                raise ContentValidationError(
                    f"槽位 {slot_key} 的 manual_item_id 重复"
                )
            used_manual_ids.add(manual_id)
            reserved_ids.add(manual_id)
            name = slot.get("name")
            if not isinstance(name, str) or not name.strip():
                raise ContentValidationError(
                    f"槽位 {slot_key} 的 manual 条目缺少名称"
                )
            result[slot_key] = _manual_slot(manual_id, slot)

    _assert_slot_name_uniqueness(result)
    return result


def _prepare_slots(
    payload: Any,
    entries,
    *,
    previous_slots: dict,
    known_manual_ids: set[str],
    used_manual_ids: set[str],
    reserved_ids: set[str],
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ContentValidationError("outdoor_game_slots 必须是 JSON 对象")
    _reject_unknown_keys(payload, frozenset(SLOT_KEYS), "outdoor_game_slots")

    outdoor_by_ref = _outdoor_candidates_by_ref(entries)
    result: dict[str, Any] = {}

    for slot_key in SLOT_KEYS:
        previous_slot = previous_slots.get(slot_key)
        if slot_key not in payload:
            # Omitted subfield inherits previous value entirely.
            if previous_slot is None:
                result[slot_key] = None
                continue
            result[slot_key] = _validate_one_slot(
                slot_key,
                previous_slot,
                entries,
                outdoor_by_ref=outdoor_by_ref,
                known_manual_ids=known_manual_ids,
                used_manual_ids=used_manual_ids,
                reserved_ids=reserved_ids,
                is_patch=False,
            )
            continue

        slot = payload.get(slot_key)
        if slot is None:
            result[slot_key] = None
            continue
        if not isinstance(slot, dict):
            raise ContentValidationError(f"槽位 {slot_key} 必须是对象或 null")
        kind = slot.get("source_kind")
        if not isinstance(kind, str) or (
            kind != "daily_plan" and kind != "manual"
        ):
            raise ContentValidationError(
                f"槽位 {slot_key} 的 source_kind 必须是 daily_plan 或 manual"
            )
        if kind == "daily_plan":
            _reject_unknown_keys(slot, OUTDOOR_SLOT_KEYS, f"槽位 {slot_key}")
            if slot.get("manual_item_id") is not None:
                raise ContentValidationError(
                    f"槽位 {slot_key} 的 daily_plan 条目不得携带 manual_item_id"
                )
            _validate_ref_fields(slot, f"槽位 {slot_key}")

            if _same_identity(slot, previous_slot):
                # Same identity: keep entire previous object, no re-stamp,
                # client text/version not trusted.
                result[slot_key] = copy.deepcopy(previous_slot)
                continue

            # New / changed identity: re-resolve current source.
            ref = (
                slot.get("daily_plan_id"),
                slot.get("group_id"),
                slot.get("game_id"),
            )
            candidate = outdoor_by_ref.get(ref)
            if candidate is None:
                raise ContentValidationError(
                    f"槽位 {slot_key} 引用的日计划来源不存在或已变化，请重新选择"
                )
            required_kind = (
                "collective" if slot_key in COLLECTIVE_SLOTS else "free_choice"
            )
            if candidate.get("group_kind") != required_kind:
                raise ContentValidationError(
                    f"槽位 {slot_key} 的 group_kind 与槽位类别不符"
                )
            result[slot_key] = {
                "source_kind": "daily_plan",
                "manual_item_id": None,
                "daily_plan_id": candidate["daily_plan_id"],
                "content_id": candidate["content_id"],
                "content_version": candidate["content_version"],
                "group_id": candidate["group_id"],
                "game_id": candidate["game_id"],
                "name": candidate["name"],
                "shared_objectives": candidate["shared_objectives"],
                "guidance_points": candidate["guidance_points"],
                "focus_guidance": candidate["focus_guidance"],
            }
        else:
            _reject_unknown_keys(slot, MANUAL_SLOT_KEYS, f"槽位 {slot_key}")
            _assert_manual_refs_null(slot, f"槽位 {slot_key}")
            manual_id = slot.get("manual_item_id")
            if manual_id is None:
                manual_id = _fresh_id(reserved_ids)
                reserved_ids.add(manual_id)
            elif not isinstance(manual_id, str) or not manual_id:
                raise ContentValidationError(
                    f"槽位 {slot_key} 的 manual_item_id 必须是非空字符串"
                )
            elif manual_id not in known_manual_ids:
                raise ContentValidationError(
                    f"槽位 {slot_key} 的 manual_item_id 不属于本草稿"
                )
            if manual_id in used_manual_ids:
                raise ContentValidationError(
                    f"槽位 {slot_key} 的 manual_item_id 重复"
                )
            used_manual_ids.add(manual_id)

            name = slot.get("name")
            if not isinstance(name, str) or not name.strip():
                raise ContentValidationError(
                    f"槽位 {slot_key} 的 manual 条目缺少名称"
                )
            for label in (
                "shared_objectives",
                "guidance_points",
                "focus_guidance",
            ):
                value = slot.get(label)
                if value is not None and not isinstance(value, str):
                    raise ContentValidationError(
                        f"槽位 {slot_key} 的 {label} 必须是字符串或 null"
                    )
            result[slot_key] = _manual_slot(manual_id, slot)

    _assert_slot_name_uniqueness(result)
    return result


def _manual_slot(manual_id: str, slot: dict) -> dict:
    return {
        "source_kind": "manual",
        "manual_item_id": manual_id,
        "daily_plan_id": None,
        "content_id": None,
        "content_version": None,
        "group_id": None,
        "game_id": None,
        "name": slot.get("name"),
        "shared_objectives": slot.get("shared_objectives"),
        "guidance_points": slot.get("guidance_points"),
        "focus_guidance": slot.get("focus_guidance"),
    }


def _assert_manual_refs_null(obj: dict, label: str) -> None:
    for field in DAILY_REF_FIELDS:
        if obj.get(field) is not None:
            raise ContentValidationError(
                f"{label} 的 manual 条目不得携带非空日计划引用字段 {field}"
            )


def _validate_one_slot(
    slot_key: str,
    slot: dict,
    entries,
    *,
    outdoor_by_ref: dict,
    known_manual_ids: set[str],
    used_manual_ids: set[str],
    reserved_ids: set[str],
    is_patch: bool,
) -> dict | None:
    if not isinstance(slot, dict):
        raise ContentValidationError(f"槽位 {slot_key} 必须是对象或 null")
    kind = slot.get("source_kind")
    if not isinstance(kind, str) or (
        kind != "daily_plan" and kind != "manual"
    ):
        raise ContentValidationError(
            f"槽位 {slot_key} 的 source_kind 必须是 daily_plan 或 manual"
        )
    if kind == "daily_plan":
        _reject_unknown_keys(slot, OUTDOOR_SLOT_KEYS, f"槽位 {slot_key}")
        if slot.get("manual_item_id") is not None:
            raise ContentValidationError(
                f"槽位 {slot_key} 的 daily_plan 条目不得携带 manual_item_id"
            )
        _validate_ref_fields(slot, f"槽位 {slot_key}")
        name = slot.get("name")
        if not isinstance(name, str):
            raise ContentValidationError(f"槽位 {slot_key} 缺少名称")
        return copy.deepcopy(slot)

    _reject_unknown_keys(slot, MANUAL_SLOT_KEYS, f"槽位 {slot_key}")
    _assert_manual_refs_null(slot, f"槽位 {slot_key}")
    manual_id = slot.get("manual_item_id")
    if not isinstance(manual_id, str) or not manual_id:
        raise ContentValidationError(
            f"槽位 {slot_key} 的 manual 条目缺少 manual_item_id"
        )
    if is_patch and manual_id not in known_manual_ids:
        raise ContentValidationError(
            f"槽位 {slot_key} 的 manual_item_id 不属于本草稿"
        )
    if manual_id in used_manual_ids:
        raise ContentValidationError(
            f"槽位 {slot_key} 的 manual_item_id 重复"
        )
    used_manual_ids.add(manual_id)
    reserved_ids.add(manual_id)
    name = slot.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ContentValidationError(f"槽位 {slot_key} 的 manual 条目缺少名称")
    return _manual_slot(manual_id, slot)


def _prepare_focus(
    payload: Any, entries, *, previous_focus: dict | None = None
) -> dict | None:
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise ContentValidationError("focus_area 必须是对象或 null")
    kind = payload.get("source_kind")
    if not isinstance(kind, str) or kind != "daily_plan":
        raise ContentValidationError(
            "focus_area 的 source_kind 必须是 daily_plan 或 null"
        )
    _reject_unknown_keys(payload, FOCUS_KEYS, "focus_area")
    if payload.get("manual_item_id") is not None:
        raise ContentValidationError("focus_area 不得携带 manual_item_id")
    _validate_ref_fields(payload, "focus_area")

    if _same_identity(payload, previous_focus):
        # Same identity: keep entire previous object, no re-stamp.
        return copy.deepcopy(previous_focus)

    focus_by_ref = _focus_candidates_by_ref(entries)
    ref = (
        payload.get("daily_plan_id"),
        payload.get("group_id"),
        payload.get("game_id"),
    )
    candidate = focus_by_ref.get(ref)
    if candidate is None:
        raise ContentValidationError(
            "focus_area 引用的日计划来源不存在或已变化，请重新选择"
        )
    return {
        "source_kind": "daily_plan",
        "manual_item_id": None,
        "daily_plan_id": candidate["daily_plan_id"],
        "content_id": candidate["content_id"],
        "content_version": candidate["content_version"],
        "group_id": candidate["group_id"],
        "game_id": candidate["game_id"],
        "context_kind": candidate["context_kind"],
        "area": candidate.get("area"),
        "name": candidate["name"],
        "objectives": candidate.get("objectives"),
        "guidance": candidate.get("guidance"),
        "support_strategy": candidate.get("support_strategy"),
    }


def _validate_focus(focus: Any, entries) -> dict | None:
    if focus is None:
        return None
    if not isinstance(focus, dict):
        raise ContentValidationError("focus_area 必须是对象或 null")
    kind = focus.get("source_kind")
    if not isinstance(kind, str) or kind != "daily_plan":
        raise ContentValidationError(
            "focus_area 的 source_kind 必须是 daily_plan 或 null"
        )
    _reject_unknown_keys(focus, FOCUS_KEYS, "focus_area")
    if focus.get("manual_item_id") is not None:
        raise ContentValidationError("focus_area 不得携带 manual_item_id")
    _validate_ref_fields(focus, "focus_area")
    return copy.deepcopy(focus)


def _prepare_weekly_columns(
    payload: Any, previous: dict | None = None
) -> dict[str, str]:
    if not isinstance(payload, dict):
        raise ContentValidationError("weekly_columns 必须是 JSON 对象")
    _reject_unknown_keys(payload, frozenset(WEEKLY_COLUMN_KEYS), "weekly_columns")
    prev = previous or {}
    columns: dict[str, str] = {}
    for key in WEEKLY_COLUMN_KEYS:
        if key in payload:
            value = payload[key]
            if value is None:
                value = ""
            if not isinstance(value, str):
                raise ContentValidationError(f"weekly_columns.{key} 必须是字符串")
            columns[key] = value
        else:
            # Omitted subfield inherits previous value.
            value = prev.get(key, "")
            if value is None:
                value = ""
            if not isinstance(value, str):
                raise ContentValidationError(f"weekly_columns.{key} 必须是字符串")
            columns[key] = value
    return columns


def _fresh_id(reserved: set[str]) -> str:
    while True:
        candidate = security.generate_id()
        if candidate not in reserved:
            return candidate
