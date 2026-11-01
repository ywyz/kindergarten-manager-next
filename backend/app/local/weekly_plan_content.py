"""Pure weekly-plan content rules for the local desktop app.

This module deliberately has no database, session, runtime, API or model
imports.  The trusted source snapshot is assembled by the caller (A); this
module only validates that snapshot, derives the canonical draft, applies
explicit manual patches, refreshes resolvable references, and computes
point-in-time facts.

``schema_version`` is 1.  All string values are UTF-8 text; IDs are opaque
server values (at most 32 characters); ``client_key`` is only a patch-time
correlation key and never enters stored content.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from datetime import date, timedelta
from typing import Any

SCHEMA_VERSION = 1
DETERMINISTIC_FIELDS = ("morning_talk_topic", "group_activity_theme")
OUTDOOR_SLOT_KEYS = ("collective_1", "collective_2", "free_choice_1")
COLLECTIVE_SLOT_KEYS = ("collective_1", "collective_2")
FREE_CHOICE_SLOT_KEYS = ("free_choice_1",)
WEEKLY_COLUMN_KEYS = (
    "key_week_focus",
    "environment_setup",
    "habit_culture",
    "home_cooperation",
)
DAY_STATES = ("teaching", "rest", "outside_term")
SOURCE_STATES = ("saved", "no_plan", "none_required")
PATCH_KEYS = frozenset(
    {
        "theme",
        "deterministic_overrides",
        "outdoor_game_slots",
        "focus_area",
        "weekly_columns",
    }
)
MAX_CONTENT_BYTES = 1_048_576
MAX_HEADER_NAMES = 100
MAX_HEADER_JSON_BYTES = 32 * 1024
MAX_NAME_CHARS = 80
MAX_ID_CHARS = 32
MAX_CLIENT_KEY_CHARS = 64
MAX_CONTEXT_HASH_CHARS = 64
GRADES = ("small", "middle", "large")
CONTEXT_KINDS = ("area", "outdoor", "special_room")
SOURCE_KEYS = (
    "daily_plan_id",
    "content_id",
    "content_version",
    "content_hash",
    "morning_talk_topic",
    "group_activity_theme",
)
SLOT_KEYS = (
    "source_kind",
    "manual_item_id",
    "daily_plan_id",
    "content_id",
    "content_version",
    "content_hash",
    "section",
    "group_id",
    "game_id",
    "name",
    "shared_objectives",
    "guidance_points",
    "focus_guidance",
)
FOCUS_KEYS = (
    "source_kind",
    "manual_item_id",
    "daily_plan_id",
    "content_id",
    "content_version",
    "content_hash",
    "section",
    "group_id",
    "game_id",
    "context_kind",
    "area",
    "name",
    "objectives",
    "guidance",
    "support_strategy",
)
SELECTOR_KEYS = (
    "source_kind",
    "daily_plan_id",
    "content_id",
    "content_version",
    "content_hash",
    "section",
    "group_id",
    "game_id",
)
MANUAL_PATCH_KEYS = (
    "source_kind",
    "manual_item_id",
    "client_key",
    "name",
    "shared_objectives",
    "guidance_points",
    "focus_guidance",
)
DETERMINISTIC_OVERRIDE_KEYS = frozenset(DETERMINISTIC_FIELDS)
DETERMINISTIC_ROW_KEYS = frozenset(
    {"date", "day_state", "source_state", "source", "override", "effective"}
)
CONTENT_KEYS = frozenset(
    {
        "schema_version",
        "theme",
        "deterministic",
        "outdoor_game_slots",
        "focus_area",
        "weekly_columns",
        "materials",
        "source_manifest",
        "calendar_basis",
    }
)
SOURCE_MANIFEST_KEYS = frozenset(
    {
        "source_context_hash",
        "profile_id",
        "class_id",
        "term_id",
        "week_anchor_date",
        "week_number",
        "term_start",
        "term_end",
        "calendar_revision_id",
        "config_version",
        "game_context",
        "header",
        "sources",
    }
)
HEADER_KEYS = frozenset(
    {
        "school_name",
        "class_name",
        "grade",
        "header_teacher_names",
        "caregiver_name",
    }
)
SOURCE_MANIFEST_SOURCE_KEYS = frozenset(
    {
        "date",
        "source_state",
        "daily_plan_id",
        "content_id",
        "content_version",
        "content_hash",
    }
)
CALENDAR_BASIS_KEYS = frozenset(
    {"week_anchor_date", "term_start", "term_end", "calendar_revision_id", "days"}
)
CALENDAR_DAY_KEYS = frozenset({"date", "day_state"})


class WeeklyContentError(ValueError):
    """A pure content validation/materialisation error for A to map."""

    code = "WEEKLY_CONTENT_INVALID"

    def __init__(
        self,
        message: str,
        *,
        field_path: str = "",
        details: Mapping[str, Any] | None = None,
        code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.field_path = field_path
        self.details = dict(details or {})
        if code is not None:
            self.code = code


def _fail(message: str, field_path: str = "", code: str | None = None) -> None:
    raise WeeklyContentError(message, field_path=field_path, code=code)


def _map(value: Any, field_path: str) -> dict:
    if not isinstance(value, Mapping):
        _fail("必须是对象", field_path)
    return dict(value)


def _exact_keys(value: Mapping[str, Any], expected: frozenset[str] | tuple[str, ...], field_path: str) -> None:
    wanted = set(expected)
    actual = set(value)
    if actual != wanted:
        missing = sorted(wanted - actual)
        extra = sorted(actual - wanted)
        _fail(f"键不匹配 missing={missing} extra={extra}", field_path)


def _text(value: Any, field_path: str, *, allow_none: bool = False, strip: bool = False) -> str:
    if value is None and allow_none:
        return ""
    if not isinstance(value, str):
        _fail("必须是字符串", field_path)
    if "\x00" in value:
        _fail("字符串不得包含 NUL", field_path)
    return value.strip() if strip else value


def _name(value: Any, field_path: str) -> str:
    text = _text(value, field_path, strip=True)
    if not text or len(text) > MAX_NAME_CHARS:
        _fail(f"名称长度必须为 1–{MAX_NAME_CHARS}", field_path)
    return text


def _id(value: Any, field_path: str) -> str:
    text = _text(value, field_path)
    if not text or len(text) > MAX_ID_CHARS:
        _fail(f"ID 长度必须为 1–{MAX_ID_CHARS}", field_path)
    return text


def _client_key(value: Any, field_path: str) -> str:
    text = _text(value, field_path, strip=True)
    if not text or len(text) > MAX_CLIENT_KEY_CHARS:
        _fail(f"client_key 长度必须为 1–{MAX_CLIENT_KEY_CHARS}", field_path)
    return text


def _hash(value: Any, field_path: str) -> str:
    text = _text(value, field_path)
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        _fail("必须是 64 位小写十六进制", field_path)
    return text


def _positive_int(value: Any, field_path: str) -> int:
    if type(value) is not int or value < 1:
        _fail("必须是正整数", field_path)
    return value


def _iso_date(value: Any, field_path: str) -> str:
    text = _text(value, field_path)
    try:
        parsed = date.fromisoformat(text)
    except ValueError:
        _fail("必须是 ISO 日期", field_path)
    if parsed.isoformat() != text:
        _fail("日期必须规范为 YYYY-MM-DD", field_path)
    return text


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise WeeklyContentError(
            f"内容不可规范序列化: {type(exc).__name__}"
        ) from None


def canonical_json(value: Any) -> str:
    """Stable JSON used by content hashes; non-finite values are rejected."""
    return _canonical_json(value)


def _canonical_size(value: Any, field_path: str) -> int:
    text = _canonical_json(value)
    size = len(text.encode("utf-8"))
    if size > MAX_CONTENT_BYTES:
        _fail(f"内容超过 {MAX_CONTENT_BYTES} 字节", field_path, "WEEKLY_CONTENT_TOO_LARGE")
    return size


def content_hash(content: Mapping[str, Any]) -> str:
    """SHA-256 of canonical content JSON (UTF-8)."""
    payload = _canonical_json(content)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _normalize_header(value: Any, field_path: str) -> dict:
    data = _map(value, field_path)
    _exact_keys(data, HEADER_KEYS, field_path)
    school = data.get("school_name")
    if school is not None:
        school = _text(school, f"{field_path}.school_name", strip=True)
        if len(school) > 120:
            _fail("school_name 不能超过 120 字符", f"{field_path}.school_name")
        if school == "":
            school = None
    class_name = _name(data.get("class_name"), f"{field_path}.class_name")
    grade = _text(data.get("grade"), f"{field_path}.grade")
    if grade not in GRADES:
        _fail("grade 非法", f"{field_path}.grade")
    names_raw = data.get("header_teacher_names")
    if not isinstance(names_raw, list) or len(names_raw) > MAX_HEADER_NAMES:
        _fail(f"header_teacher_names 必须是最多 {MAX_HEADER_NAMES} 项的数组", f"{field_path}.header_teacher_names")
    names: list[str] = []
    for index, item in enumerate(names_raw):
        names.append(_name(item, f"{field_path}.header_teacher_names[{index}]"))
    caregiver = data.get("caregiver_name")
    if caregiver is not None:
        caregiver = _text(caregiver, f"{field_path}.caregiver_name", strip=True)
        if len(caregiver) > MAX_NAME_CHARS:
            _fail("caregiver_name 不能超过 80 字符", f"{field_path}.caregiver_name")
        if caregiver == "":
            caregiver = None
    header = {
        "school_name": school,
        "class_name": class_name,
        "grade": grade,
        "header_teacher_names": names,
        "caregiver_name": caregiver,
    }
    if len(_canonical_json(header).encode("utf-8")) > MAX_HEADER_JSON_BYTES:
        _fail("表头 JSON 超过 32KiB", field_path, "WEEKLY_HEADER_TOO_LARGE")
    return header


def _normalize_game(value: Any, field_path: str) -> dict:
    data = _map(value, field_path)
    _exact_keys(data, ("game_id", "name"), field_path)
    return {
        "game_id": _id(data.get("game_id"), f"{field_path}.game_id"),
        "name": _text(data.get("name"), f"{field_path}.name"),
    }


def _normalize_games(value: Any, field_path: str) -> list[dict]:
    if not isinstance(value, list):
        _fail("games 必须是数组", field_path)
    return [_normalize_game(item, f"{field_path}[{i}]") for i, item in enumerate(value)]


def _normalize_morning_group(value: Any, field_path: str) -> dict:
    data = _map(value, field_path)
    _exact_keys(
        data,
        (
            "group_id",
            "group_kind",
            "games",
            "shared_objectives",
            "guidance_points",
            "focus_guidance",
        ),
        field_path,
    )
    kind = _text(data.get("group_kind"), f"{field_path}.group_kind")
    if kind not in ("collective", "free_choice"):
        _fail("group_kind 非法", f"{field_path}.group_kind")
    return {
        "group_id": _id(data.get("group_id"), f"{field_path}.group_id"),
        "group_kind": kind,
        "games": _normalize_games(data.get("games"), f"{field_path}.games"),
        "shared_objectives": _text(
            data.get("shared_objectives"), f"{field_path}.shared_objectives", allow_none=True
        ),
        "guidance_points": _text(
            data.get("guidance_points"), f"{field_path}.guidance_points", allow_none=True
        ),
        "focus_guidance": _text(
            data.get("focus_guidance"), f"{field_path}.focus_guidance", allow_none=True
        ),
    }


def _normalize_post_group(value: Any, field_path: str) -> dict:
    data = _map(value, field_path)
    _exact_keys(
        data,
        (
            "group_id",
            "context_kind",
            "area",
            "games",
            "objectives",
            "guidance",
            "support_strategy",
        ),
        field_path,
    )
    context = _text(data.get("context_kind"), f"{field_path}.context_kind")
    if context not in CONTEXT_KINDS:
        _fail("context_kind 非法", f"{field_path}.context_kind")
    return {
        "group_id": _id(data.get("group_id"), f"{field_path}.group_id"),
        "context_kind": context,
        "area": _text(data.get("area"), f"{field_path}.area", allow_none=True),
        "games": _normalize_games(data.get("games"), f"{field_path}.games"),
        "objectives": _text(data.get("objectives"), f"{field_path}.objectives", allow_none=True),
        "guidance": _text(data.get("guidance"), f"{field_path}.guidance", allow_none=True),
        "support_strategy": _text(
            data.get("support_strategy"), f"{field_path}.support_strategy", allow_none=True
        ),
    }


def _normalize_source(value: Any, field_path: str) -> dict | None:
    if value is None:
        return None
    data = _map(value, field_path)
    _exact_keys(data, SOURCE_KEYS, field_path)
    return {
        "daily_plan_id": _id(data.get("daily_plan_id"), f"{field_path}.daily_plan_id"),
        "content_id": _id(data.get("content_id"), f"{field_path}.content_id"),
        "content_version": _positive_int(
            data.get("content_version"), f"{field_path}.content_version"
        ),
        "content_hash": _hash(data.get("content_hash"), f"{field_path}.content_hash"),
        "morning_talk_topic": _text(
            data.get("morning_talk_topic"), f"{field_path}.morning_talk_topic", allow_none=True
        ),
        "group_activity_theme": _text(
            data.get("group_activity_theme"), f"{field_path}.group_activity_theme", allow_none=True
        ),
    }


def _normalize_day(value: Any, field_path: str) -> dict:
    data = _map(value, field_path)
    _exact_keys(
        data,
        ("date", "day_state", "source_state", "source", "morning_groups", "post_group_groups"),
        field_path,
    )
    day_date = _iso_date(data.get("date"), f"{field_path}.date")
    day_state = _text(data.get("day_state"), f"{field_path}.day_state")
    if day_state not in DAY_STATES:
        _fail("day_state 非法", f"{field_path}.day_state")
    source_state = _text(data.get("source_state"), f"{field_path}.source_state")
    if source_state not in SOURCE_STATES:
        _fail("source_state 非法", f"{field_path}.source_state")
    source = _normalize_source(data.get("source"), f"{field_path}.source")
    if source_state == "saved":
        if source is None:
            _fail("saved 必须提供 source", f"{field_path}.source")
    elif source is not None:
        _fail("no_plan/none_required 的 source 必须为 null", f"{field_path}.source")
    if day_state == "teaching":
        if source_state not in ("saved", "no_plan"):
            _fail("teaching 的 source_state 只能是 saved/no_plan", f"{field_path}.source_state")
    elif source_state != "none_required":
        _fail("rest/outside_term 的 source_state 必须是 none_required", f"{field_path}.source_state")
    mornings_raw = data.get("morning_groups")
    posts_raw = data.get("post_group_groups")
    if not isinstance(mornings_raw, list) or not isinstance(posts_raw, list):
        _fail("morning_groups/post_group_groups 必须是数组", field_path)
    if day_state != "teaching" and (mornings_raw or posts_raw):
        _fail("非教学日不得携带游戏组", field_path)
    mornings = [
        _normalize_morning_group(item, f"{field_path}.morning_groups[{i}]")
        for i, item in enumerate(mornings_raw)
    ]
    posts = [
        _normalize_post_group(item, f"{field_path}.post_group_groups[{i}]")
        for i, item in enumerate(posts_raw)
    ]
    return {
        "date": day_date,
        "day_state": day_state,
        "source_state": source_state,
        "source": source,
        "morning_groups": mornings,
        "post_group_groups": posts,
    }


def _normalize_game_context(value: Any, field_path: str) -> dict | None:
    if value is None:
        return None
    data = _map(value, field_path)
    _exact_keys(data, ("revision_id", "revision_no"), field_path)
    return {
        "revision_id": _id(data.get("revision_id"), f"{field_path}.revision_id"),
        "revision_no": _positive_int(data.get("revision_no"), f"{field_path}.revision_no"),
    }


def validate_source_snapshot(snapshot: Any) -> dict:
    """Validate and deeply normalize A's trusted weekly source snapshot."""
    data = _map(snapshot, "snapshot")
    _exact_keys(
        data,
        (
            "profile_id",
            "class_id",
            "term_id",
            "week_anchor_date",
            "week_number",
            "term_start",
            "term_end",
            "calendar_revision_id",
            "config_version",
            "game_context",
            "header",
            "source_context_hash",
            "days",
        ),
        "snapshot",
    )
    profile_id = _id(data.get("profile_id"), "snapshot.profile_id")
    class_id = _id(data.get("class_id"), "snapshot.class_id")
    term_id = _id(data.get("term_id"), "snapshot.term_id")
    anchor = _iso_date(data.get("week_anchor_date"), "snapshot.week_anchor_date")
    anchor_date = date.fromisoformat(anchor)
    if anchor_date.weekday() != 0:
        _fail("week_anchor_date 必须是周一", "snapshot.week_anchor_date")
    week_number = _positive_int(data.get("week_number"), "snapshot.week_number")
    term_start = _iso_date(data.get("term_start"), "snapshot.term_start")
    term_end = _iso_date(data.get("term_end"), "snapshot.term_end")
    if date.fromisoformat(term_start) > date.fromisoformat(term_end):
        _fail("term_start 不能晚于 term_end", "snapshot.term_start")
    days_raw = data.get("days")
    if not isinstance(days_raw, list) or len(days_raw) != 7:
        _fail("days 必须恰好 7 天", "snapshot.days")
    days = [_normalize_day(item, f"snapshot.days[{i}]") for i, item in enumerate(days_raw)]
    expected = [(anchor_date.fromordinal(anchor_date.toordinal() + i)).isoformat() for i in range(7)]
    if [item["date"] for item in days] != expected:
        _fail("days 必须从 week_anchor_date 起连续升序 7 天", "snapshot.days")
    return {
        "profile_id": profile_id,
        "class_id": class_id,
        "term_id": term_id,
        "week_anchor_date": anchor,
        "week_number": week_number,
        "term_start": term_start,
        "term_end": term_end,
        "calendar_revision_id": _id(
            data.get("calendar_revision_id"), "snapshot.calendar_revision_id"
        ),
        "config_version": _positive_int(data.get("config_version"), "snapshot.config_version"),
        "game_context": _normalize_game_context(data.get("game_context"), "snapshot.game_context"),
        "header": _normalize_header(data.get("header"), "snapshot.header"),
        "source_context_hash": _hash(
            data.get("source_context_hash"), "snapshot.source_context_hash"
        ),
        "days": days,
    }


def _normalize_override(value: Any, field_path: str) -> dict:
    data = _map(value, field_path)
    _exact_keys(data, DETERMINISTIC_OVERRIDE_KEYS, field_path)
    return {
        field: (
            None
            if data.get(field) is None
            else _text(data.get(field), f"{field_path}.{field}", allow_none=True)
        )
        for field in DETERMINISTIC_FIELDS
    }


def _normalize_effective(value: Any, field_path: str) -> dict:
    data = _map(value, field_path)
    _exact_keys(data, frozenset(DETERMINISTIC_FIELDS), field_path)
    return {
        field: _text(data.get(field), f"{field_path}.{field}", allow_none=True)
        for field in DETERMINISTIC_FIELDS
    }


def _normalize_source_manifest_source(value: Any, field_path: str) -> dict:
    data = _map(value, field_path)
    _exact_keys(data, SOURCE_MANIFEST_SOURCE_KEYS, field_path)
    date_text = _iso_date(data.get("date"), f"{field_path}.date")
    state = _text(data.get("source_state"), f"{field_path}.source_state")
    if state not in SOURCE_STATES:
        _fail("source_state 非法", f"{field_path}.source_state")
    if state == "saved":
        return {
            "date": date_text,
            "source_state": state,
            "daily_plan_id": _id(data.get("daily_plan_id"), f"{field_path}.daily_plan_id"),
            "content_id": _id(data.get("content_id"), f"{field_path}.content_id"),
            "content_version": _positive_int(
                data.get("content_version"), f"{field_path}.content_version"
            ),
            "content_hash": _hash(data.get("content_hash"), f"{field_path}.content_hash"),
        }
    for key in ("daily_plan_id", "content_id", "content_version", "content_hash"):
        if data.get(key) is not None:
            _fail("非 saved 来源的日引用必须为 null", f"{field_path}.{key}")
    return {
        "date": date_text,
        "source_state": state,
        "daily_plan_id": None,
        "content_id": None,
        "content_version": None,
        "content_hash": None,
    }


def _normalize_source_manifest(value: Any) -> dict:
    data = _map(value, "content.source_manifest")
    _exact_keys(data, SOURCE_MANIFEST_KEYS, "content.source_manifest")
    sources_raw = data.get("sources")
    if not isinstance(sources_raw, list) or len(sources_raw) != 7:
        _fail("source_manifest.sources 必须恰好 7 天", "content.source_manifest.sources")
    return {
        "source_context_hash": _hash(
            data.get("source_context_hash"), "content.source_manifest.source_context_hash"
        ),
        "profile_id": _id(data.get("profile_id"), "content.source_manifest.profile_id"),
        "class_id": _id(data.get("class_id"), "content.source_manifest.class_id"),
        "term_id": _id(data.get("term_id"), "content.source_manifest.term_id"),
        "week_anchor_date": _iso_date(
            data.get("week_anchor_date"), "content.source_manifest.week_anchor_date"
        ),
        "week_number": _positive_int(data.get("week_number"), "content.source_manifest.week_number"),
        "term_start": _iso_date(data.get("term_start"), "content.source_manifest.term_start"),
        "term_end": _iso_date(data.get("term_end"), "content.source_manifest.term_end"),
        "calendar_revision_id": _id(
            data.get("calendar_revision_id"), "content.source_manifest.calendar_revision_id"
        ),
        "config_version": _positive_int(
            data.get("config_version"), "content.source_manifest.config_version"
        ),
        "game_context": _normalize_game_context(
            data.get("game_context"), "content.source_manifest.game_context"
        ),
        "header": _normalize_header(data.get("header"), "content.source_manifest.header"),
        "sources": [
            _normalize_source_manifest_source(item, f"content.source_manifest.sources[{i}]")
            for i, item in enumerate(sources_raw)
        ],
    }


def _normalize_calendar_basis(value: Any) -> dict:
    data = _map(value, "content.calendar_basis")
    _exact_keys(data, CALENDAR_BASIS_KEYS, "content.calendar_basis")
    days_raw = data.get("days")
    if not isinstance(days_raw, list) or len(days_raw) != 7:
        _fail("calendar_basis.days 必须恰好 7 天", "content.calendar_basis.days")
    days: list[dict] = []
    for index, item in enumerate(days_raw):
        row = _map(item, f"content.calendar_basis.days[{index}]")
        _exact_keys(row, CALENDAR_DAY_KEYS, f"content.calendar_basis.days[{index}]")
        day_state = _text(row.get("day_state"), f"content.calendar_basis.days[{index}].day_state")
        if day_state not in DAY_STATES:
            _fail("day_state 非法", f"content.calendar_basis.days[{index}].day_state")
        days.append(
            {
                "date": _iso_date(row.get("date"), f"content.calendar_basis.days[{index}].date"),
                "day_state": day_state,
            }
        )
    return {
        "week_anchor_date": _iso_date(
            data.get("week_anchor_date"), "content.calendar_basis.week_anchor_date"
        ),
        "term_start": _iso_date(data.get("term_start"), "content.calendar_basis.term_start"),
        "term_end": _iso_date(data.get("term_end"), "content.calendar_basis.term_end"),
        "calendar_revision_id": _id(
            data.get("calendar_revision_id"), "content.calendar_basis.calendar_revision_id"
        ),
        "days": days,
    }


def _validate_week_structure(anchor: str, term_start: str, term_end: str, days: list[dict], field_path: str) -> None:
    anchor_date = date.fromisoformat(anchor)
    if anchor_date.weekday() != 0:
        _fail("week_anchor_date 必须是周一", f"{field_path}.week_anchor_date")
    if date.fromisoformat(term_start) > date.fromisoformat(term_end):
        _fail("term_start 不能晚于 term_end", f"{field_path}.term_start")
    expected = [(anchor_date + timedelta(days=index)).isoformat() for index in range(7)]
    if [item["date"] for item in days] != expected:
        _fail("日期必须从周一 anchor 连续 7 天", f"{field_path}.days")


def _normalize_slot(value: Any, field_path: str) -> dict | None:
    if value is None:
        return None
    data = _map(value, field_path)
    _exact_keys(data, SLOT_KEYS, field_path)
    kind = _text(data.get("source_kind"), f"{field_path}.source_kind")
    if kind == "daily_plan":
        section = _text(data.get("section"), f"{field_path}.section")
        if section != "morning_games":
            _fail("户外日来源 section 必须是 morning_games", f"{field_path}.section")
        if data.get("manual_item_id") is not None:
            _fail("日来源不得携带 manual_item_id", f"{field_path}.manual_item_id")
        return {
            "source_kind": "daily_plan",
            "manual_item_id": None,
            "daily_plan_id": _id(data.get("daily_plan_id"), f"{field_path}.daily_plan_id"),
            "content_id": _id(data.get("content_id"), f"{field_path}.content_id"),
            "content_version": _positive_int(
                data.get("content_version"), f"{field_path}.content_version"
            ),
            "content_hash": _hash(data.get("content_hash"), f"{field_path}.content_hash"),
            "section": section,
            "group_id": _id(data.get("group_id"), f"{field_path}.group_id"),
            "game_id": _id(data.get("game_id"), f"{field_path}.game_id"),
            "name": _text(data.get("name"), f"{field_path}.name"),
            "shared_objectives": _text(
                data.get("shared_objectives"), f"{field_path}.shared_objectives", allow_none=True
            ),
            "guidance_points": _text(
                data.get("guidance_points"), f"{field_path}.guidance_points", allow_none=True
            ),
            "focus_guidance": _text(
                data.get("focus_guidance"), f"{field_path}.focus_guidance", allow_none=True
            ),
        }
    if kind == "manual":
        for key in ("daily_plan_id", "content_id", "content_version", "content_hash", "section", "group_id", "game_id"):
            if data.get(key) is not None:
                _fail("手工条目日定位字段必须为 null", f"{field_path}.{key}")
        return {
            "source_kind": "manual",
            "manual_item_id": _id(data.get("manual_item_id"), f"{field_path}.manual_item_id"),
            "daily_plan_id": None,
            "content_id": None,
            "content_version": None,
            "content_hash": None,
            "section": None,
            "group_id": None,
            "game_id": None,
            "name": _text(data.get("name"), f"{field_path}.name"),
            "shared_objectives": _text(
                data.get("shared_objectives"), f"{field_path}.shared_objectives", allow_none=True
            ),
            "guidance_points": _text(
                data.get("guidance_points"), f"{field_path}.guidance_points", allow_none=True
            ),
            "focus_guidance": _text(
                data.get("focus_guidance"), f"{field_path}.focus_guidance", allow_none=True
            ),
        }
    _fail("source_kind 必须是 daily_plan/manual", f"{field_path}.source_kind")


def _normalize_focus(value: Any) -> dict | None:
    if value is None:
        return None
    data = _map(value, "content.focus_area")
    _exact_keys(data, FOCUS_KEYS, "content.focus_area")
    if data.get("source_kind") != "daily_plan":
        _fail("focus_area 只允许日来源", "content.focus_area.source_kind")
    if data.get("manual_item_id") is not None:
        _fail("focus_area 不得携带 manual_item_id", "content.focus_area.manual_item_id")
    if data.get("section") != "post_group_games":
        _fail("focus_area section 必须是 post_group_games", "content.focus_area.section")
    context = _text(data.get("context_kind"), "content.focus_area.context_kind")
    if context not in CONTEXT_KINDS:
        _fail("context_kind 非法", "content.focus_area.context_kind")
    return {
        "source_kind": "daily_plan",
        "manual_item_id": None,
        "daily_plan_id": _id(data.get("daily_plan_id"), "content.focus_area.daily_plan_id"),
        "content_id": _id(data.get("content_id"), "content.focus_area.content_id"),
        "content_version": _positive_int(
            data.get("content_version"), "content.focus_area.content_version"
        ),
        "content_hash": _hash(data.get("content_hash"), "content.focus_area.content_hash"),
        "section": "post_group_games",
        "group_id": _id(data.get("group_id"), "content.focus_area.group_id"),
        "game_id": _id(data.get("game_id"), "content.focus_area.game_id"),
        "context_kind": context,
        "area": _text(data.get("area"), "content.focus_area.area", allow_none=True),
        "name": _text(data.get("name"), "content.focus_area.name"),
        "objectives": _text(data.get("objectives"), "content.focus_area.objectives", allow_none=True),
        "guidance": _text(data.get("guidance"), "content.focus_area.guidance", allow_none=True),
        "support_strategy": _text(
            data.get("support_strategy"), "content.focus_area.support_strategy", allow_none=True
        ),
    }


def _normalize_columns(value: Any, field_path: str) -> dict:
    data = _map(value, field_path)
    _exact_keys(data, frozenset(WEEKLY_COLUMN_KEYS), field_path)
    return {
        key: _text(data.get(key), f"{field_path}.{key}", allow_none=True)
        for key in WEEKLY_COLUMN_KEYS
    }


def _validate_collective_slot_names(slots: Mapping[str, Any]) -> None:
    by_name: dict[str, str] = {}
    for key in COLLECTIVE_SLOT_KEYS:
        slot = slots.get(key)
        if slot is None:
            continue
        name = str(slot.get("name") or "").strip()
        if not name:
            continue
        if name in by_name:
            _fail("同类别同名游戏不能占两个集体槽", f"content.outdoor_game_slots.{key}")
        by_name[name] = key


def validate_content(content: Any, *, snapshot: Mapping[str, Any] | None = None) -> dict:
    """Strictly validate stored/derived content and return a deep copy."""
    data = _map(content, "content")
    _exact_keys(data, CONTENT_KEYS, "content")
    if data.get("schema_version") != SCHEMA_VERSION or type(data.get("schema_version")) is not int:
        _fail("schema_version 必须为 1", "content.schema_version")
    theme = _text(data.get("theme"), "content.theme")
    rows_raw = data.get("deterministic")
    if not isinstance(rows_raw, list) or len(rows_raw) != 7:
        _fail("deterministic 必须恰好 7 天", "content.deterministic")
    rows: list[dict] = []
    for index, item in enumerate(rows_raw):
        row = _map(item, f"content.deterministic[{index}]")
        _exact_keys(row, DETERMINISTIC_ROW_KEYS, f"content.deterministic[{index}]")
        day_state = _text(row.get("day_state"), f"content.deterministic[{index}].day_state")
        if day_state not in DAY_STATES:
            _fail("day_state 非法", f"content.deterministic[{index}].day_state")
        source_state = _text(
            row.get("source_state"), f"content.deterministic[{index}].source_state"
        )
        if source_state not in SOURCE_STATES:
            _fail("source_state 非法", f"content.deterministic[{index}].source_state")
        source = _normalize_source(row.get("source"), f"content.deterministic[{index}].source")
        if source is None:
            if day_state == "teaching" and source_state != "no_plan":
                _fail(
                    "teaching 且无 source 时 source_state 必须是 no_plan",
                    f"content.deterministic[{index}].source_state",
                )
            if day_state != "teaching" and source_state != "none_required":
                _fail(
                    "rest/outside_term 且无 source 时 source_state 必须是 none_required",
                    f"content.deterministic[{index}].source_state",
                )
        elif source_state != "saved":
            _fail(
                "有 source 时 source_state 必须是 saved",
                f"content.deterministic[{index}].source_state",
            )
        rows.append(
            {
                "date": _iso_date(row.get("date"), f"content.deterministic[{index}].date"),
                "day_state": day_state,
                "source_state": source_state,
                "source": source,
                "override": _normalize_override(
                    row.get("override"), f"content.deterministic[{index}].override"
                ),
                "effective": _normalize_effective(
                    row.get("effective"), f"content.deterministic[{index}].effective"
                ),
            }
        )
    for row in rows:
        expected = _effective_for(row["source"], row["override"], row["day_state"])
        if row["effective"] != expected:
            _fail("effective 与服务端派生值不一致", f"content.deterministic[{row['date']}].effective")
    slots_raw = _map(data.get("outdoor_game_slots"), "content.outdoor_game_slots")
    _exact_keys(slots_raw, frozenset(OUTDOOR_SLOT_KEYS), "content.outdoor_game_slots")
    slots = {
        key: _normalize_slot(slots_raw.get(key), f"content.outdoor_game_slots.{key}")
        for key in OUTDOOR_SLOT_KEYS
    }
    manual_ids: set[str] = set()
    for key, slot in slots.items():
        if slot is not None and slot["source_kind"] == "manual":
            if slot["manual_item_id"] in manual_ids:
                _fail("manual_item_id 重复", f"content.outdoor_game_slots.{key}")
            manual_ids.add(slot["manual_item_id"])
    _validate_collective_slot_names(slots)
    focus = _normalize_focus(data.get("focus_area"))
    columns = _normalize_columns(data.get("weekly_columns"), "content.weekly_columns")
    if data.get("materials") is not None:
        _fail("首片 materials 必须为 null", "content.materials")
    manifest = _normalize_source_manifest(data.get("source_manifest"))
    calendar = _normalize_calendar_basis(data.get("calendar_basis"))
    _validate_week_structure(
        calendar["week_anchor_date"],
        calendar["term_start"],
        calendar["term_end"],
        calendar["days"],
        "content.calendar_basis",
    )
    _validate_week_structure(
        manifest["week_anchor_date"],
        manifest["term_start"],
        manifest["term_end"],
        [{"date": item["date"], "day_state": "teaching"} for item in manifest["sources"]],
        "content.source_manifest",
    )
    _exact_dates = [day["date"] for day in calendar["days"]]
    if [row["date"] for row in rows] != _exact_dates:
        _fail("deterministic 日期必须与 calendar_basis 一致", "content.deterministic")
    if [row["day_state"] for row in rows] != [day["day_state"] for day in calendar["days"]]:
        _fail("deterministic day_state 必须与 calendar_basis 一致", "content.deterministic")
    if (
        manifest["week_anchor_date"] != calendar["week_anchor_date"]
        or manifest["term_start"] != calendar["term_start"]
        or manifest["term_end"] != calendar["term_end"]
        or manifest["calendar_revision_id"] != calendar["calendar_revision_id"]
    ):
        _fail("source_manifest 日历身份与 calendar_basis 不一致", "content.source_manifest")
    manifest_dates = [item["date"] for item in manifest["sources"]]
    if manifest_dates != _exact_dates:
        _fail("source_manifest.sources 日期必须与 calendar_basis 一致", "content.source_manifest.sources")
    by_date = {item["date"]: item for item in manifest["sources"]}
    for row in rows:
        item = by_date[row["date"]]
        if item["source_state"] != row["source_state"]:
            _fail("source_manifest 与 deterministic source_state 不一致", "content.source_manifest.sources")
        source = row["source"]
        if source is None:
            if any(item[key] is not None for key in ("daily_plan_id", "content_id", "content_version", "content_hash")):
                _fail("source_manifest 与 deterministic source 不一致", "content.source_manifest.sources")
        elif (
            item["daily_plan_id"] != source["daily_plan_id"]
            or item["content_id"] != source["content_id"]
            or item["content_version"] != source["content_version"]
            or item["content_hash"] != source["content_hash"]
        ):
            _fail("source_manifest 与 deterministic source 不一致", "content.source_manifest.sources")
    result = {
        "schema_version": SCHEMA_VERSION,
        "theme": theme,
        "deterministic": rows,
        "outdoor_game_slots": slots,
        "focus_area": focus,
        "weekly_columns": columns,
        "materials": None,
        "source_manifest": manifest,
        "calendar_basis": calendar,
    }
    if len(_canonical_json(result).encode("utf-8")) > MAX_CONTENT_BYTES:
        _fail("content 超过 1MiB", "content", "WEEKLY_CONTENT_TOO_LARGE")
    if snapshot is not None:
        snap = validate_source_snapshot(snapshot)
        if (
            manifest["profile_id"] != snap["profile_id"]
            or manifest["class_id"] != snap["class_id"]
            or manifest["term_id"] != snap["term_id"]
            or manifest["week_anchor_date"] != snap["week_anchor_date"]
            or manifest["week_number"] != snap["week_number"]
            or manifest["header"] != snap["header"]
        ):
            _fail("content 与 snapshot 的不可变归属不一致", "content.source_manifest")
    return copy.deepcopy(result)


def _source_manifest_from_snapshot(snapshot: Mapping[str, Any]) -> dict:
    sources = []
    for day in snapshot["days"]:
        source = day["source"]
        sources.append(
            {
                "date": day["date"],
                "source_state": day["source_state"],
                "daily_plan_id": source["daily_plan_id"] if source else None,
                "content_id": source["content_id"] if source else None,
                "content_version": source["content_version"] if source else None,
                "content_hash": source["content_hash"] if source else None,
            }
        )
    return {
        "source_context_hash": snapshot["source_context_hash"],
        "profile_id": snapshot["profile_id"],
        "class_id": snapshot["class_id"],
        "term_id": snapshot["term_id"],
        "week_anchor_date": snapshot["week_anchor_date"],
        "week_number": snapshot["week_number"],
        "term_start": snapshot["term_start"],
        "term_end": snapshot["term_end"],
        "calendar_revision_id": snapshot["calendar_revision_id"],
        "config_version": snapshot["config_version"],
        "game_context": copy.deepcopy(snapshot["game_context"]),
        "header": copy.deepcopy(snapshot["header"]),
        "sources": sources,
    }


def _calendar_basis_from_snapshot(snapshot: Mapping[str, Any]) -> dict:
    return {
        "week_anchor_date": snapshot["week_anchor_date"],
        "term_start": snapshot["term_start"],
        "term_end": snapshot["term_end"],
        "calendar_revision_id": snapshot["calendar_revision_id"],
        "days": [
            {"date": day["date"], "day_state": day["day_state"]}
            for day in snapshot["days"]
        ],
    }


def _effective_for(source: Mapping[str, Any] | None, override: Mapping[str, Any], day_state: str) -> dict:
    if day_state != "teaching":
        return {field: "" for field in DETERMINISTIC_FIELDS}
    return {
        field: (
            override[field]
            if override[field] is not None
            else (source.get(field) if source else "")
        )
        for field in DETERMINISTIC_FIELDS
    }


def _rows_from_snapshot(snapshot: Mapping[str, Any], overrides: Mapping[str, Mapping[str, Any]] | None = None) -> list[dict]:
    rows = []
    for day in snapshot["days"]:
        override = _normalize_override(
            (overrides or {}).get(day["date"], {"morning_talk_topic": None, "group_activity_theme": None}),
            f"deterministic_overrides.{day['date']}",
        )
        rows.append(
            {
                "date": day["date"],
                "day_state": day["day_state"],
                "source_state": day["source_state"],
                "source": copy.deepcopy(day["source"]),
                "override": override,
                "effective": _effective_for(day["source"], override, day["day_state"]),
            }
        )
    return rows


def new_content(snapshot: Mapping[str, Any], *, theme: str = "") -> dict:
    """Create the first canonical draft from a trusted source snapshot."""
    snap = validate_source_snapshot(snapshot)
    if theme is None:
        theme = ""
    if not isinstance(theme, str):
        _fail("theme 必须是字符串", "theme")
    content = {
        "schema_version": SCHEMA_VERSION,
        "theme": theme,
        "deterministic": _rows_from_snapshot(snap),
        "outdoor_game_slots": {key: None for key in OUTDOOR_SLOT_KEYS},
        "focus_area": None,
        "weekly_columns": {key: "" for key in WEEKLY_COLUMN_KEYS},
        "materials": None,
        "source_manifest": _source_manifest_from_snapshot(snap),
        "calendar_basis": _calendar_basis_from_snapshot(snap),
    }
    return validate_content(content)


def _merge_overrides(previous: Mapping[str, Any], payload: Any, snapshot: Mapping[str, Any]) -> dict[str, dict]:
    if payload is None:
        payload = {}
    data = _map(payload, "deterministic_overrides")
    previous_rows = {row["date"]: row for row in previous["deterministic"]}
    merged = {
        row["date"]: copy.deepcopy(row["override"])
        for row in previous["deterministic"]
    }
    for date_text, value in data.items():
        date_text = _iso_date(date_text, "deterministic_overrides date")
        if date_text not in previous_rows:
            _fail("deterministic_overrides 含未知日期", f"deterministic_overrides.{date_text}")
        if previous_rows[date_text]["day_state"] != "teaching":
            _fail("只能覆盖教学日", f"deterministic_overrides.{date_text}")
        raw = _map(value, f"deterministic_overrides.{date_text}")
        unknown = set(raw) - set(DETERMINISTIC_FIELDS)
        if unknown:
            _fail("deterministic_overrides 含未知字段", f"deterministic_overrides.{date_text}")
        for field in DETERMINISTIC_FIELDS:
            if field in raw:
                merged[date_text][field] = (
                    None
                    if raw[field] is None
                    else _text(raw[field], f"deterministic_overrides.{date_text}.{field}")
                )
    return merged


def _selector(value: Any, field_path: str, *, section: str) -> dict:
    data = _map(value, field_path)
    _exact_keys(data, SELECTOR_KEYS, field_path)
    if data.get("source_kind") != "daily_plan":
        _fail("selector source_kind 必须是 daily_plan", f"{field_path}.source_kind")
    if data.get("section") != section:
        _fail(f"selector section 必须是 {section}", f"{field_path}.section")
    return {
        "source_kind": "daily_plan",
        "daily_plan_id": _id(data.get("daily_plan_id"), f"{field_path}.daily_plan_id"),
        "content_id": _id(data.get("content_id"), f"{field_path}.content_id"),
        "content_version": _positive_int(data.get("content_version"), f"{field_path}.content_version"),
        "content_hash": _hash(data.get("content_hash"), f"{field_path}.content_hash"),
        "section": section,
        "group_id": _id(data.get("group_id"), f"{field_path}.group_id"),
        "game_id": _id(data.get("game_id"), f"{field_path}.game_id"),
    }


def _find_day(snapshot: Mapping[str, Any], daily_plan_id: str) -> dict | None:
    for day in snapshot["days"]:
        source = day["source"]
        if source is not None and source["daily_plan_id"] == daily_plan_id:
            return day
    return None


def _selector_ref(selector: Mapping[str, Any]) -> dict:
    return {
        "daily_plan_id": selector["daily_plan_id"],
        "content_id": selector["content_id"],
        "content_version": selector["content_version"],
        "content_hash": selector["content_hash"],
        "section": selector["section"],
        "group_id": selector["group_id"],
        "game_id": selector["game_id"],
    }


def _stored_ref(value: Mapping[str, Any]) -> dict:
    return {
        "daily_plan_id": value["daily_plan_id"],
        "content_id": value["content_id"],
        "content_version": value["content_version"],
        "content_hash": value["content_hash"],
        "section": value["section"],
        "group_id": value["group_id"],
        "game_id": value["game_id"],
    }


def _resolve_outdoor(selector: Mapping[str, Any], snapshot: Mapping[str, Any], slot_key: str) -> dict:
    day = _find_day(snapshot, selector["daily_plan_id"])
    if day is None or day["source"] is None:
        _fail("引用的日计划不存在或已变化", f"outdoor_game_slots.{slot_key}")
    source = day["source"]
    if (
        source["content_id"] != selector["content_id"]
        or source["content_version"] != selector["content_version"]
        or source["content_hash"] != selector["content_hash"]
    ):
        _fail("日来源版本或 hash 已变化", f"outdoor_game_slots.{slot_key}")
    required_kind = "collective" if slot_key in COLLECTIVE_SLOT_KEYS else "free_choice"
    for group in day["morning_groups"]:
        if group["group_id"] != selector["group_id"]:
            continue
        if group["group_kind"] != required_kind:
            _fail("group_kind 与槽位类别不符", f"outdoor_game_slots.{slot_key}")
        for game in group["games"]:
            if game["game_id"] == selector["game_id"]:
                return {
                    "source_kind": "daily_plan",
                    "manual_item_id": None,
                    "daily_plan_id": source["daily_plan_id"],
                    "content_id": source["content_id"],
                    "content_version": source["content_version"],
                    "content_hash": source["content_hash"],
                    "section": "morning_games",
                    "group_id": group["group_id"],
                    "game_id": game["game_id"],
                    "name": game["name"],
                    "shared_objectives": group["shared_objectives"],
                    "guidance_points": group["guidance_points"],
                    "focus_guidance": group["focus_guidance"],
                }
    _fail("引用的 group/game 不存在", f"outdoor_game_slots.{slot_key}")


def _resolve_focus(selector: Mapping[str, Any], snapshot: Mapping[str, Any]) -> dict:
    day = _find_day(snapshot, selector["daily_plan_id"])
    if day is None or day["source"] is None:
        _fail("引用的日计划不存在或已变化", "focus_area")
    source = day["source"]
    if (
        source["content_id"] != selector["content_id"]
        or source["content_version"] != selector["content_version"]
        or source["content_hash"] != selector["content_hash"]
    ):
        _fail("日来源版本或 hash 已变化", "focus_area")
    for group in day["post_group_groups"]:
        if group["group_id"] != selector["group_id"]:
            continue
        for game in group["games"]:
            if game["game_id"] == selector["game_id"]:
                return {
                    "source_kind": "daily_plan",
                    "manual_item_id": None,
                    "daily_plan_id": source["daily_plan_id"],
                    "content_id": source["content_id"],
                    "content_version": source["content_version"],
                    "content_hash": source["content_hash"],
                    "section": "post_group_games",
                    "group_id": group["group_id"],
                    "game_id": game["game_id"],
                    "context_kind": group["context_kind"],
                    "area": group["area"],
                    "name": game["name"],
                    "objectives": group["objectives"],
                    "guidance": group["guidance"],
                    "support_strategy": group["support_strategy"],
                }
    _fail("引用的 group/game 不存在", "focus_area")


def _manual_slot(value: Mapping[str, Any], path: str, previous_ids: set[str], manual_ids: Mapping[str, str] | None, used: set[str], clients: dict[str, str]) -> dict:
    data = _map(value, path)
    _exact_keys(data, MANUAL_PATCH_KEYS, path)
    if data.get("source_kind") != "manual":
        _fail("source_kind 必须是 manual", f"{path}.source_kind")
    manual_id = data.get("manual_item_id")
    client_key = data.get("client_key")
    if manual_id is not None and client_key is not None:
        _fail("manual_item_id 与 client_key 不能同时提供", path)
    if manual_id is None:
        if client_key is None:
            _fail("新手工条目必须提供 client_key", path)
        key = _client_key(client_key, f"{path}.client_key")
        if key in clients:
            _fail("client_key 重复", f"{path}.client_key")
        if manual_ids is None or key not in manual_ids:
            _fail("缺少 A 注入的 manual_id", f"{path}.client_key")
        final_id = _id(manual_ids[key], f"{path}.manual_item_id")
        clients[key] = final_id
    else:
        final_id = _id(manual_id, f"{path}.manual_item_id")
        if final_id not in previous_ids:
            _fail("manual_item_id 不属于本草稿", f"{path}.manual_item_id")
    if final_id in used:
        _fail("manual_item_id 重复", f"{path}.manual_item_id")
    used.add(final_id)
    return {
        "source_kind": "manual",
        "manual_item_id": final_id,
        "daily_plan_id": None,
        "content_id": None,
        "content_version": None,
        "content_hash": None,
        "section": None,
        "group_id": None,
        "game_id": None,
        "name": _text(data.get("name"), f"{path}.name", allow_none=True),
        "shared_objectives": _text(data.get("shared_objectives"), f"{path}.shared_objectives", allow_none=True),
        "guidance_points": _text(data.get("guidance_points"), f"{path}.guidance_points", allow_none=True),
        "focus_guidance": _text(data.get("focus_guidance"), f"{path}.focus_guidance", allow_none=True),
    }


def _apply_slots(previous: Mapping[str, Any], payload: Any, snapshot: Mapping[str, Any], manual_ids: Mapping[str, str] | None) -> dict:
    data = _map(payload, "outdoor_game_slots")
    unknown = set(data) - set(OUTDOOR_SLOT_KEYS)
    if unknown:
        _fail(f"outdoor_game_slots 含未知字段 {sorted(unknown)}", "outdoor_game_slots")
    previous_slots = previous["outdoor_game_slots"]
    previous_ids = {
        slot["manual_item_id"]
        for slot in previous_slots.values()
        if slot and slot["source_kind"] == "manual"
    }
    used: set[str] = set()
    clients: dict[str, str] = {}
    result: dict[str, Any] = {}
    for key in OUTDOOR_SLOT_KEYS:
        if key not in data:
            result[key] = copy.deepcopy(previous_slots[key])
            if result[key] and result[key]["source_kind"] == "manual":
                used.add(result[key]["manual_item_id"])
            continue
        value = data[key]
        if value is None:
            result[key] = None
            continue
        raw = _map(value, f"outdoor_game_slots.{key}")
        if raw.get("source_kind") == "manual":
            result[key] = _manual_slot(
                raw,
                f"outdoor_game_slots.{key}",
                previous_ids,
                manual_ids,
                used,
                clients,
            )
            continue
        selector = _selector(raw, f"outdoor_game_slots.{key}", section="morning_games")
        result[key] = _resolve_outdoor(selector, snapshot, key)
    by_name: dict[str, str] = {}
    for key in COLLECTIVE_SLOT_KEYS:
        slot = result[key]
        if slot is None:
            continue
        name = slot["name"].strip()
        if not name:
            continue
        if name in by_name:
            _fail("同类别同名游戏不能占两个集体槽", f"outdoor_game_slots.{key}")
        by_name[name] = key
    return result


def _apply_focus(previous: Mapping[str, Any], payload: Any, snapshot: Mapping[str, Any]) -> dict | None:
    if payload is None:
        return None
    selector = _selector(payload, "focus_area", section="post_group_games")
    return _resolve_focus(selector, snapshot)


def _apply_columns(previous: Mapping[str, Any], payload: Any) -> dict:
    data = _map(payload, "weekly_columns")
    unknown = set(data) - set(WEEKLY_COLUMN_KEYS)
    if unknown:
        _fail("weekly_columns 含未知字段", "weekly_columns")
    result = copy.deepcopy(previous)
    for key, value in data.items():
        result[key] = "" if value is None else _text(value, f"weekly_columns.{key}")
    return result


def apply_patch(
    previous: Mapping[str, Any],
    patch: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    *,
    manual_ids: Mapping[str, str] | None = None,
) -> dict:
    """Apply only the explicit manual-patch whitelist to an existing draft."""
    prev = validate_content(previous)
    snap = validate_source_snapshot(snapshot)
    data = _map(patch, "patch")
    unknown = set(data) - PATCH_KEYS
    if unknown:
        _fail(f"patch 含未知字段 {sorted(unknown)}", "patch")
    theme = prev["theme"]
    if "theme" in data:
        if data["theme"] is None:
            theme = ""
        else:
            theme = _text(data["theme"], "patch.theme")
    overrides = {
        row["date"]: copy.deepcopy(row["override"])
        for row in prev["deterministic"]
    }
    if "deterministic_overrides" in data:
        overrides = _merge_overrides(prev, data["deterministic_overrides"], snap)
    rows = []
    by_date = {row["date"]: row for row in prev["deterministic"]}
    for row in prev["deterministic"]:
        override = overrides.get(row["date"], copy.deepcopy(row["override"]))
        rows.append(
            {
                "date": row["date"],
                "day_state": row["day_state"],
                "source_state": row["source_state"],
                "source": copy.deepcopy(row["source"]),
                "override": override,
                "effective": _effective_for(row["source"], override, row["day_state"]),
            }
        )
    slots = prev["outdoor_game_slots"]
    if "outdoor_game_slots" in data:
        slots = _apply_slots(prev, data["outdoor_game_slots"], snap, manual_ids)
    focus = prev["focus_area"]
    if "focus_area" in data:
        focus = _apply_focus(prev, data["focus_area"], snap)
    columns = prev["weekly_columns"]
    if "weekly_columns" in data:
        columns = _apply_columns(prev["weekly_columns"], data["weekly_columns"])
    result = {
        **copy.deepcopy(prev),
        "theme": theme,
        "deterministic": rows,
        "outdoor_game_slots": slots,
        "focus_area": focus,
        "weekly_columns": columns,
        "materials": None,
    }
    return validate_content(result)


def _ref_for_row(row: Mapping[str, Any]) -> dict | None:
    source = row.get("source")
    if not source:
        return None
    return {
        "daily_plan_id": source["daily_plan_id"],
        "content_id": source["content_id"],
        "content_version": source["content_version"],
        "content_hash": source["content_hash"],
    }


def _ref_for_slot(slot: Mapping[str, Any] | None) -> dict | None:
    if not slot:
        return None
    return {
        "daily_plan_id": slot["daily_plan_id"],
        "content_id": slot["content_id"],
        "content_version": slot["content_version"],
        "content_hash": slot["content_hash"],
        "section": slot["section"],
        "group_id": slot["group_id"],
        "game_id": slot["game_id"],
    }


def _find_current_slot(snapshot: Mapping[str, Any], old: Mapping[str, Any], *, slot_key: str | None = None) -> dict | None:
    day = _find_day(snapshot, old["daily_plan_id"])
    if day is None or day["source"] is None:
        return None
    required_kind = None
    if old["section"] == "morning_games" and slot_key is not None:
        if slot_key in COLLECTIVE_SLOT_KEYS:
            required_kind = "collective"
        elif slot_key in FREE_CHOICE_SLOT_KEYS:
            required_kind = "free_choice"
    groups = day["morning_groups"] if old["section"] == "morning_games" else day["post_group_groups"]
    for group in groups:
        if group["group_id"] != old["group_id"]:
            continue
        if required_kind is not None and group["group_kind"] != required_kind:
            continue
        for game in group["games"]:
            if game["game_id"] == old["game_id"]:
                if old["section"] == "morning_games":
                    return {
                        "source_kind": "daily_plan",
                        "manual_item_id": None,
                        "daily_plan_id": day["source"]["daily_plan_id"],
                        "content_id": day["source"]["content_id"],
                        "content_version": day["source"]["content_version"],
                        "content_hash": day["source"]["content_hash"],
                        "section": "morning_games",
                        "group_id": group["group_id"],
                        "game_id": game["game_id"],
                        "name": game["name"],
                        "shared_objectives": group["shared_objectives"],
                        "guidance_points": group["guidance_points"],
                        "focus_guidance": group["focus_guidance"],
                    }
                return {
                    "source_kind": "daily_plan",
                    "manual_item_id": None,
                    "daily_plan_id": day["source"]["daily_plan_id"],
                    "content_id": day["source"]["content_id"],
                    "content_version": day["source"]["content_version"],
                    "content_hash": day["source"]["content_hash"],
                    "section": "post_group_games",
                    "group_id": group["group_id"],
                    "game_id": game["game_id"],
                    "context_kind": group["context_kind"],
                    "area": group["area"],
                    "name": game["name"],
                    "objectives": group["objectives"],
                    "guidance": group["guidance"],
                    "support_strategy": group["support_strategy"],
                }
    return None


def _calendar_differences(old: Mapping[str, Any], new: Mapping[str, Any]) -> list[dict]:
    differences: list[dict] = []
    for field in ("week_anchor_date", "term_start", "term_end", "calendar_revision_id"):
        if old.get(field) != new.get(field):
            differences.append(
                {
                    "code": "calendar_basis_changed",
                    "field_path": f"calendar_basis.{field}",
                    "old_ref": old.get(field),
                    "new_ref": new.get(field),
                }
            )
    old_days = {item["date"]: item["day_state"] for item in old.get("days", [])}
    for item in new.get("days", []):
        if old_days.get(item["date"]) != item["day_state"]:
            differences.append(
                {
                    "code": "calendar_basis_changed",
                    "field_path": f"calendar_basis.days[{item['date']}].day_state",
                    "old_ref": old_days.get(item["date"]),
                    "new_ref": item["day_state"],
                }
            )
    return differences


def refresh_content(previous: Mapping[str, Any], snapshot: Mapping[str, Any]) -> dict:
    """Build a full refresh target while preserving manual/old history."""
    prev = validate_content(previous)
    snap = validate_source_snapshot(snapshot)
    if (
        snap["profile_id"] != prev["source_manifest"]["profile_id"]
        or snap["class_id"] != prev["source_manifest"]["class_id"]
        or snap["term_id"] != prev["source_manifest"]["term_id"]
        or snap["week_anchor_date"] != prev["source_manifest"]["week_anchor_date"]
        or snap["week_number"] != prev["source_manifest"]["week_number"]
    ):
        _fail("刷新 snapshot 与计划固定归属不一致", "snapshot")
    differences: list[dict] = _calendar_differences(
        prev["calendar_basis"], _calendar_basis_from_snapshot(snap)
    )
    preserved: list[dict] = []
    rows: list[dict] = []
    current_by_date = {day["date"]: day for day in snap["days"]}
    for old in prev["deterministic"]:
        day = current_by_date[old["date"]]
        old_ref = _ref_for_row(old)
        new_source = day["source"]
        if new_source is not None:
            new_state = "saved"
            new_row_source = copy.deepcopy(new_source)
        elif old["source"] is not None:
            new_state = old["source_state"]
            new_row_source = copy.deepcopy(old["source"])
            preserved.append(
                {
                    "code": "preserved_source",
                    "field_path": f"deterministic[{old['date']}].source",
                    "old_ref": old_ref,
                    "new_ref": None,
                }
            )
        else:
            new_state = day["source_state"]
            new_row_source = None
        new_ref = _ref_for_row({"source": new_row_source})
        if old_ref != new_ref:
            differences.append(
                {
                    "code": "refreshed_source",
                    "field_path": f"deterministic[{old['date']}].source",
                    "old_ref": old_ref,
                    "new_ref": new_ref,
                }
            )
        override = copy.deepcopy(old["override"])
        rows.append(
            {
                "date": old["date"],
                "day_state": day["day_state"],
                "source_state": new_state,
                "source": new_row_source,
                "override": override,
                "effective": _effective_for(new_row_source, override, day["day_state"]),
            }
        )
    slots: dict[str, Any] = {}
    for key in OUTDOOR_SLOT_KEYS:
        old = prev["outdoor_game_slots"][key]
        if old is None or old["source_kind"] == "manual":
            slots[key] = copy.deepcopy(old)
            continue
        current = _find_current_slot(snap, old, slot_key=key)
        if current is None:
            slots[key] = copy.deepcopy(old)
            preserved.append(
                {
                    "code": "preserved_source",
                    "field_path": f"outdoor_game_slots.{key}",
                    "old_ref": _ref_for_slot(old),
                    "new_ref": None,
                }
            )
        else:
            slots[key] = current
            if _ref_for_slot(old) != _ref_for_slot(current):
                differences.append(
                    {
                        "code": "refreshed_source",
                        "field_path": f"outdoor_game_slots.{key}",
                        "old_ref": _ref_for_slot(old),
                        "new_ref": _ref_for_slot(current),
                    }
                )
    old_focus = prev["focus_area"]
    if old_focus is None:
        focus = None
    else:
        current = _find_current_slot(snap, old_focus)
        if current is None:
            focus = copy.deepcopy(old_focus)
            preserved.append(
                {
                    "code": "preserved_source",
                    "field_path": "focus_area",
                    "old_ref": _ref_for_slot(old_focus),
                    "new_ref": None,
                }
            )
        else:
            focus = current
            if _ref_for_slot(old_focus) != _ref_for_slot(current):
                differences.append(
                    {
                        "code": "refreshed_source",
                        "field_path": "focus_area",
                        "old_ref": _ref_for_slot(old_focus),
                        "new_ref": _ref_for_slot(current),
                    }
                )
    manifest = copy.deepcopy(prev["source_manifest"])
    manifest.update(
        {
            "source_context_hash": snap["source_context_hash"],
            "term_start": snap["term_start"],
            "term_end": snap["term_end"],
            "calendar_revision_id": snap["calendar_revision_id"],
            "config_version": snap["config_version"],
            "game_context": copy.deepcopy(snap["game_context"]),
            "sources": [
                {
                    "date": row["date"],
                    "source_state": row["source_state"],
                    "daily_plan_id": row["source"]["daily_plan_id"] if row["source"] else None,
                    "content_id": row["source"]["content_id"] if row["source"] else None,
                    "content_version": row["source"]["content_version"] if row["source"] else None,
                    "content_hash": row["source"]["content_hash"] if row["source"] else None,
                }
                for row in rows
            ],
        }
    )
    content = {
        **copy.deepcopy(prev),
        "deterministic": rows,
        "outdoor_game_slots": slots,
        "focus_area": focus,
        "source_manifest": manifest,
        "calendar_basis": _calendar_basis_from_snapshot(snap),
    }
    return {
        "content": validate_content(content),
        "differences": differences,
        "preserved": preserved,
    }


def _fact(code: str, field_path: str, *, old_ref: Any = None, new_ref: Any = None, details: Mapping[str, Any] | None = None, message: str = "") -> dict:
    item = {
        "code": code,
        "field_path": field_path,
        "old_ref": copy.deepcopy(old_ref),
        "new_ref": copy.deepcopy(new_ref),
        "details": dict(details or {}),
    }
    if message:
        item["message"] = message
    return item


def _missing_empty(value: Any, field_path: str, code: str = "empty_field") -> dict | None:
    if isinstance(value, str) and value.strip():
        return None
    return _fact(code, field_path)


def build_facts(content: Mapping[str, Any], snapshot: Mapping[str, Any]) -> dict:
    """Missing from the fixed draft; stale/warnings from the current snapshot."""
    fixed = validate_content(content)
    snap = validate_source_snapshot(snapshot)
    missing: list[dict] = []
    stale: list[dict] = []
    warnings: list[dict] = []
    header = fixed["source_manifest"]["header"]
    if not fixed["theme"].strip():
        missing.append(_fact("empty_theme", "theme"))
    if not header["header_teacher_names"]:
        missing.append(_fact("empty_header_teacher_names", "source_manifest.header.header_teacher_names"))
    if not (header["caregiver_name"] or "").strip():
        missing.append(_fact("empty_caregiver_name", "source_manifest.header.caregiver_name"))
    for row in fixed["deterministic"]:
        if row["day_state"] != "teaching":
            continue
        for field in DETERMINISTIC_FIELDS:
            if not row["effective"][field].strip():
                missing.append(_fact("empty_field", f"deterministic[{row['date']}].effective.{field}"))
    for key in WEEKLY_COLUMN_KEYS:
        if not fixed["weekly_columns"][key].strip():
            missing.append(_fact("empty_field", f"weekly_columns.{key}"))
    for key in OUTDOOR_SLOT_KEYS:
        slot = fixed["outdoor_game_slots"][key]
        if slot is None:
            missing.append(_fact("outdoor_slot_missing", f"outdoor_game_slots.{key}"))
            continue
        for field in ("name", "shared_objectives", "guidance_points", "focus_guidance"):
            if not (slot[field] or "").strip():
                missing.append(_fact("empty_field", f"outdoor_game_slots.{key}.{field}"))
    focus = fixed["focus_area"]
    if focus is None:
        missing.append(_fact("focus_area_missing", "focus_area"))
    else:
        for field in ("name", "objectives", "guidance", "support_strategy"):
            if not (focus[field] or "").strip():
                missing.append(_fact("empty_field", f"focus_area.{field}"))
    missing.append(_fact("materials_empty", "materials"))

    current_by_date = {day["date"]: day for day in snap["days"]}
    for row in fixed["deterministic"]:
        day = current_by_date.get(row["date"])
        old_ref = _ref_for_row(row)
        current = day["source"] if day else None
        new_ref = _ref_for_row({"source": current}) if current else None
        if old_ref != new_ref:
            stale.append(
                _fact(
                    "stale_source",
                    f"deterministic[{row['date']}].source",
                    old_ref=old_ref,
                    new_ref=new_ref,
                    details={"current_item_exists": current is not None},
                )
            )
    for key in OUTDOOR_SLOT_KEYS:
        slot = fixed["outdoor_game_slots"][key]
        if slot is None or slot["source_kind"] == "manual":
            continue
        current = _find_current_slot(snap, slot, slot_key=key)
        old_ref = _ref_for_slot(slot)
        new_ref = _ref_for_slot(current) if current else None
        if old_ref != new_ref:
            stale.append(
                _fact(
                    "stale_source",
                    f"outdoor_game_slots.{key}",
                    old_ref=old_ref,
                    new_ref=new_ref,
                    details={"current_item_exists": current is not None, "current_daily_plan_id": slot["daily_plan_id"]},
                )
            )
    focus = fixed["focus_area"]
    if focus is not None:
        current = _find_current_slot(snap, focus)
        old_ref = _ref_for_slot(focus)
        new_ref = _ref_for_slot(current) if current else None
        if old_ref != new_ref:
            stale.append(
                _fact(
                    "stale_source",
                    "focus_area",
                    old_ref=old_ref,
                    new_ref=new_ref,
                    details={"current_item_exists": current is not None, "current_daily_plan_id": focus["daily_plan_id"]},
                )
            )
    if fixed["calendar_basis"] != _calendar_basis_from_snapshot(snap):
        warnings.append(
            _fact(
                "calendar_basis_changed",
                "calendar_basis",
                old_ref=fixed["calendar_basis"],
                new_ref=_calendar_basis_from_snapshot(snap),
            )
        )
    old_hash = fixed["source_manifest"]["source_context_hash"]
    new_hash = snap["source_context_hash"]
    if old_hash != new_hash:
        warnings.append(
            _fact(
                "source_context_changed",
                "source_manifest.source_context_hash",
                old_ref=old_hash,
                new_ref=new_hash,
            )
        )
    return {"missing": missing, "stale_sources": stale, "warnings": warnings}


def build_source_candidates(snapshot: Mapping[str, Any]) -> list[dict]:
    """Read-only candidate projection derived from A's trusted snapshot."""
    snap = validate_source_snapshot(snapshot)
    candidates: list[dict] = []
    for day in snap["days"]:
        source = day["source"]
        if source is None:
            continue
        for group in day["morning_groups"]:
            for game in group["games"]:
                candidates.append(
                    {
                        "source_kind": "daily_plan",
                        "date": day["date"],
                        "daily_plan_id": source["daily_plan_id"],
                        "content_id": source["content_id"],
                        "content_version": source["content_version"],
                        "content_hash": source["content_hash"],
                        "section": "morning_games",
                        "category": group["group_kind"],
                        "group_kind": group["group_kind"],
                        "context_kind": None,
                        "area": None,
                        "group_id": group["group_id"],
                        "game_id": game["game_id"],
                        "name": game["name"],
                        "shared_objectives": group["shared_objectives"],
                        "guidance_points": group["guidance_points"],
                        "focus_guidance": group["focus_guidance"],
                        "objectives": None,
                        "guidance": None,
                        "support_strategy": None,
                    }
                )
        for group in day["post_group_groups"]:
            for game in group["games"]:
                candidates.append(
                    {
                        "source_kind": "daily_plan",
                        "date": day["date"],
                        "daily_plan_id": source["daily_plan_id"],
                        "content_id": source["content_id"],
                        "content_version": source["content_version"],
                        "content_hash": source["content_hash"],
                        "section": "post_group_games",
                        "category": "focus",
                        "group_kind": None,
                        "context_kind": group["context_kind"],
                        "area": group["area"],
                        "group_id": group["group_id"],
                        "game_id": game["game_id"],
                        "name": game["name"],
                        "shared_objectives": None,
                        "guidance_points": None,
                        "focus_guidance": None,
                        "objectives": group["objectives"],
                        "guidance": group["guidance"],
                        "support_strategy": group["support_strategy"],
                    }
                )
    return candidates


__all__ = [
    "SCHEMA_VERSION",
    "DETERMINISTIC_FIELDS",
    "OUTDOOR_SLOT_KEYS",
    "WEEKLY_COLUMN_KEYS",
    "DAY_STATES",
    "SOURCE_STATES",
    "MAX_CONTENT_BYTES",
    "WeeklyContentError",
    "validate_source_snapshot",
    "new_content",
    "apply_patch",
    "refresh_content",
    "build_facts",
    "build_source_candidates",
    "canonical_json",
    "content_hash",
    "validate_content",
]
