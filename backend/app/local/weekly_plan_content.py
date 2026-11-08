"""Pure weekly-plan content rules for the local desktop app.

This module deliberately has no database, session, runtime, API or model
imports.  The trusted source snapshot is assembled by the caller (A); this
module only validates that snapshot, derives the canonical draft, applies
explicit manual patches, refreshes resolvable references, and computes
point-in-time facts.

``schema_version`` is 1 or 2.  Schema 1 is read with its original exact key
set; schema 2 adds trusted AI and materials provenance.  All string values are
UTF-8 text; IDs are opaque server values (at most 32 characters); ``client_key``
is only a patch-time correlation key and never enters stored content.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
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

SCHEMA1_VERSION = 1
SCHEMA2_VERSION = 2
SCHEMA_VERSION = SCHEMA2_VERSION
CONTENT_KEYS_V1 = CONTENT_KEYS
AI_PROVENANCE_KEYS = frozenset(
    {
        "games",
        "key_week_focus",
        "environment_setup",
        "habit_culture",
        "home_cooperation",
    }
)
CONTENT_KEYS_V2 = CONTENT_KEYS | frozenset({"ai_provenance", "materials_provenance"})
ADOPTION_KEYS = frozenset(
    {
        "candidate_id",
        "candidate_hash",
        "input_id",
        "execution_id",
        "contract_version",
        "dependency_hash",
        "adopted_draft_id",
        "adopted_draft_version",
        "adopter_profile_id",
        "adopted_at",
        "adopted_value",
        "adopted_value_hash",
        "manual_edited",
        "basis",
    }
)
MATERIALS_PROVENANCE_KEYS = frozenset(
    {
        "candidate_id",
        "candidate_hash",
        "input_id",
        "execution_id",
        "contract_version",
        "dependency_hash",
        "basis",
        "basis_hash",
        "items",
        "original_text",
        "edited",
        "adopter_profile_id",
        "adopted_draft_id",
        "adopted_draft_version",
        "adopted_at",
    }
)
AI_ITEM_KEYS = frozenset({"ai_item_id", "candidate_id", "input_id", "basis_keys"})
OUTDOOR_KEYS_V2 = SLOT_KEYS + ("ai_item_id", "candidate_id", "input_id", "basis_keys")
FOCUS_KEYS_V2 = FOCUS_KEYS + ("ai_item_id", "candidate_id", "input_id", "basis_keys")
BASIS_KEYS = frozenset(
    {
        "schema_version",
        "target",
        "grade",
        "theme",
        "manual_text",
        "daily_sources",
        "selected",
        "config",
        "calendar",
    }
)
DAILY_BASIS_KEYS = frozenset(
    {
        "date",
        "day_state",
        "source_state",
        "daily_plan_id",
        "content_id",
        "content_version",
        "content_hash",
        "morning_talk_topic",
        "group_activity_theme",
        "group_activity_objectives",
        "group_activity_process",
        "teacher_entered",
        "morning_groups",
        "post_group_groups",
    }
)
TEACHER_ENTERED_KEYS = frozenset({"morning_talk_topic", "group_activity_theme"})
SELECTED_BASIS_KEYS = frozenset({"outdoor_game_slots", "focus_area"})
SELECTED_ITEM_KEYS = frozenset({"value", "ai_basis"})
AI_SELECTED_BASIS_KEYS = frozenset(
    {
        "candidate_id",
        "candidate_hash",
        "input_id",
        "execution_id",
        "contract_version",
        "dependency_hash",
        "adopted_value_hash",
        "ai_item_id",
        "source_ref",
        "config_refs",
    }
)
CONFIG_BASIS_KEYS = frozenset(
    {"revision_id", "revision_no", "game_scope", "guidance", "locations"}
)
CONFIG_REF_KEYS = frozenset(
    {"revision_id", "revision_no", "kind", "name", "occurrence"}
)
CALENDAR_BASIS_CONTEXT_KEYS = frozenset({"window_start", "window_end", "days"})
CALENDAR_CONTEXT_DAY_KEYS = frozenset(
    {"date", "day_state", "holiday_names", "coverage"}
)
MATERIAL_ITEM_KEYS = frozenset({"text", "origin", "evidence_refs"})
MATERIAL_EVIDENCE_KEYS = frozenset(
    {"source_handle", "field_path", "start", "end", "quote", "source"}
)
MAX_MATERIAL_ITEMS = 100
MAX_MATERIAL_ITEM_TEXT = 300
MAX_MATERIAL_QUOTE = 2_000
MAX_MATERIAL_SYNTHESIS = 20_000
MAX_PROVENANCE_BYTES = 524_288
MAX_BASIS_HANDLES = 100
HANDLE_RE = re.compile(r"^[a-z][0-9]{1,5}$")
BASIS_TARGETS = ("games", *WEEKLY_COLUMN_KEYS, "materials")


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
        _fail(
            f"键不匹配 missing_count={len(wanted - actual)} extra_count={len(actual - wanted)}",
            field_path,
        )


def _text(
    value: Any,
    field_path: str,
    *,
    allow_none: bool = False,
    strip: bool = False,
    maximum: int | None = None,
    nonempty: bool = False,
) -> str:
    if value is None and allow_none:
        return ""
    if not isinstance(value, str):
        _fail("必须是字符串", field_path)
    if "\x00" in value:
        _fail("字符串不得包含 NUL", field_path)
    result = value.strip() if strip else value
    if maximum is not None and len(result) > maximum:
        _fail(
            "文本超限",
            field_path,
            code="WEEKLY_CONTENT_TOO_LARGE",
            details={"max": maximum},
        )
    if nonempty and not result.strip():
        _fail("文本不能为空", field_path)
    return result


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


def _normalize_slot(value: Any, field_path: str, *, allow_ai: bool = False) -> dict | None:
    if value is None:
        return None
    data = _map(value, field_path)
    if allow_ai and data.get("source_kind") == "ai_supplement":
        _exact_keys(data, frozenset(OUTDOOR_KEYS_V2), field_path)
        return _normalize_ai_outdoor(data, field_path)
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


def _normalize_focus(
    value: Any,
    *,
    allow_ai: bool = False,
    field_path: str = "content.focus_area",
) -> dict | None:
    if value is None:
        return None
    data = _map(value, field_path)
    if allow_ai and data.get("source_kind") == "ai_supplement":
        _exact_keys(data, frozenset(FOCUS_KEYS_V2), field_path)
        return _normalize_ai_focus(data, field_path)
    _exact_keys(data, FOCUS_KEYS, field_path)
    if data.get("source_kind") != "daily_plan":
        _fail("focus_area 只允许日来源", f"{field_path}.source_kind")
    if data.get("manual_item_id") is not None:
        _fail("focus_area 不得携带 manual_item_id", f"{field_path}.manual_item_id")
    if data.get("section") != "post_group_games":
        _fail("focus_area section 必须是 post_group_games", f"{field_path}.section")
    context = _text(data.get("context_kind"), f"{field_path}.context_kind")
    if context not in CONTEXT_KINDS:
        _fail("context_kind 非法", f"{field_path}.context_kind")
    return {
        "source_kind": "daily_plan",
        "manual_item_id": None,
        "daily_plan_id": _id(data.get("daily_plan_id"), f"{field_path}.daily_plan_id"),
        "content_id": _id(data.get("content_id"), f"{field_path}.content_id"),
        "content_version": _positive_int(
            data.get("content_version"), f"{field_path}.content_version"
        ),
        "content_hash": _hash(data.get("content_hash"), f"{field_path}.content_hash"),
        "section": "post_group_games",
        "group_id": _id(data.get("group_id"), f"{field_path}.group_id"),
        "game_id": _id(data.get("game_id"), f"{field_path}.game_id"),
        "context_kind": context,
        "area": _text(data.get("area"), f"{field_path}.area", allow_none=True),
        "name": _text(data.get("name"), f"{field_path}.name"),
        "objectives": _text(data.get("objectives"), f"{field_path}.objectives", allow_none=True),
        "guidance": _text(data.get("guidance"), f"{field_path}.guidance", allow_none=True),
        "support_strategy": _text(
            data.get("support_strategy"), f"{field_path}.support_strategy", allow_none=True
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


def _bool(value: Any, field_path: str) -> bool:
    if type(value) is not bool:
        _fail("必须是布尔值", field_path)
    return value


def _optional_text(value: Any, field_path: str) -> str | None:
    if value is None:
        return None
    return _text(value, field_path, allow_none=True)


def _handle_list(value: Any, field_path: str) -> list[str]:
    if not isinstance(value, list) or len(value) > MAX_BASIS_HANDLES:
        _fail("handle 数组超限", field_path)
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not HANDLE_RE.fullmatch(item):
            _fail("handle 语法非法", f"{field_path}[{index}]")
        if item in result:
            _fail("handle 重复", f"{field_path}[{index}]")
        result.append(item)
    return sorted(result)


def _utc_timestamp(value: Any, field_path: str) -> str:
    text = _text(value, field_path, maximum=64, nonempty=True)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        _fail("必须是 ISO 时间", field_path)
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        _fail("必须是 UTC 时间", field_path)
    return text


def _normalize_ai_outdoor(data: Mapping[str, Any], field_path: str) -> dict:
    if data.get("source_kind") != "ai_supplement":
        _fail("AI 户外项 source_kind 必须是 ai_supplement", f"{field_path}.source_kind")
    for key in (
        "manual_item_id",
        "daily_plan_id",
        "content_id",
        "content_version",
        "content_hash",
        "section",
        "group_id",
        "game_id",
    ):
        if data.get(key) is not None:
            _fail("AI 户外项日/手工引用必须为 null", f"{field_path}.{key}")
    return {
        "source_kind": "ai_supplement",
        "manual_item_id": None,
        "daily_plan_id": None,
        "content_id": None,
        "content_version": None,
        "content_hash": None,
        "section": None,
        "group_id": None,
        "game_id": None,
        "name": _name(data.get("name"), f"{field_path}.name"),
        "shared_objectives": _text(
            data.get("shared_objectives"), f"{field_path}.shared_objectives", allow_none=True
        ),
        "guidance_points": _text(
            data.get("guidance_points"), f"{field_path}.guidance_points", allow_none=True
        ),
        "focus_guidance": _text(
            data.get("focus_guidance"), f"{field_path}.focus_guidance", allow_none=True
        ),
        "ai_item_id": _id(data.get("ai_item_id"), f"{field_path}.ai_item_id"),
        "candidate_id": _id(data.get("candidate_id"), f"{field_path}.candidate_id"),
        "input_id": _id(data.get("input_id"), f"{field_path}.input_id"),
        "basis_keys": _handle_list(data.get("basis_keys"), f"{field_path}.basis_keys"),
    }


def _normalize_ai_focus(data: Mapping[str, Any], field_path: str) -> dict:
    if data.get("source_kind") != "ai_supplement":
        _fail("AI 重点区域 source_kind 必须是 ai_supplement", f"{field_path}.source_kind")
    for key in (
        "manual_item_id",
        "daily_plan_id",
        "content_id",
        "content_version",
        "content_hash",
        "section",
        "group_id",
        "game_id",
    ):
        if data.get(key) is not None:
            _fail("AI 重点区域日/手工引用必须为 null", f"{field_path}.{key}")
    context = _text(data.get("context_kind"), f"{field_path}.context_kind")
    if context not in CONTEXT_KINDS:
        _fail("context_kind 非法", f"{field_path}.context_kind")
    return {
        "source_kind": "ai_supplement",
        "manual_item_id": None,
        "daily_plan_id": None,
        "content_id": None,
        "content_version": None,
        "content_hash": None,
        "section": None,
        "group_id": None,
        "game_id": None,
        "context_kind": context,
        "area": _text(data.get("area"), f"{field_path}.area", allow_none=True),
        "name": _name(data.get("name"), f"{field_path}.name"),
        "objectives": _text(data.get("objectives"), f"{field_path}.objectives", allow_none=True),
        "guidance": _text(data.get("guidance"), f"{field_path}.guidance", allow_none=True),
        "support_strategy": _text(
            data.get("support_strategy"), f"{field_path}.support_strategy", allow_none=True
        ),
        "ai_item_id": _id(data.get("ai_item_id"), f"{field_path}.ai_item_id"),
        "candidate_id": _id(data.get("candidate_id"), f"{field_path}.candidate_id"),
        "input_id": _id(data.get("input_id"), f"{field_path}.input_id"),
        "basis_keys": _handle_list(data.get("basis_keys"), f"{field_path}.basis_keys"),
    }


def _normalize_games_target(value: Any, field_path: str) -> dict:
    data = _map(value, field_path)
    _exact_keys(data, frozenset({"outdoor_game_slots", "focus_area"}), field_path)
    slots_raw = _map(data.get("outdoor_game_slots"), f"{field_path}.outdoor_game_slots")
    _exact_keys(slots_raw, frozenset(OUTDOOR_SLOT_KEYS), f"{field_path}.outdoor_game_slots")
    slots = {
        key: _normalize_slot(
            slots_raw.get(key), f"{field_path}.outdoor_game_slots.{key}", allow_ai=True
        )
        for key in OUTDOOR_SLOT_KEYS
    }
    _validate_collective_slot_names(slots)
    focus = _normalize_focus(data.get("focus_area"), allow_ai=True, field_path=f"{field_path}.focus_area")
    return {"outdoor_game_slots": slots, "focus_area": focus}


def _normalize_daily_ref(value: Any, field_path: str) -> dict:
    data = _map(value, field_path)
    _exact_keys(data, frozenset({"daily_plan_id", "content_id", "content_version", "content_hash", "section", "group_id", "game_id"}), field_path)
    section = _text(data.get("section"), f"{field_path}.section")
    if section not in ("morning_games", "post_group_games"):
        _fail("section 非法", f"{field_path}.section")
    return {
        "daily_plan_id": _id(data.get("daily_plan_id"), f"{field_path}.daily_plan_id"),
        "content_id": _id(data.get("content_id"), f"{field_path}.content_id"),
        "content_version": _positive_int(data.get("content_version"), f"{field_path}.content_version"),
        "content_hash": _hash(data.get("content_hash"), f"{field_path}.content_hash"),
        "section": section,
        "group_id": _id(data.get("group_id"), f"{field_path}.group_id"),
        "game_id": _id(data.get("game_id"), f"{field_path}.game_id"),
    }


def _normalize_config_ref(value: Any, field_path: str) -> dict:
    data = _map(value, field_path)
    _exact_keys(data, CONFIG_REF_KEYS, field_path)
    kind = _text(data.get("kind"), f"{field_path}.kind")
    if kind not in CONTEXT_KINDS:
        _fail("配置 kind 非法", f"{field_path}.kind")
    return {
        "revision_id": _id(data.get("revision_id"), f"{field_path}.revision_id"),
        "revision_no": _positive_int(data.get("revision_no"), f"{field_path}.revision_no"),
        "kind": kind,
        "name": _name(data.get("name"), f"{field_path}.name"),
        "occurrence": _positive_int(data.get("occurrence"), f"{field_path}.occurrence"),
    }


def _normalize_config_basis(value: Any, field_path: str) -> dict:
    data = _map(value, field_path)
    _exact_keys(data, CONFIG_BASIS_KEYS, field_path)
    locations_raw = data.get("locations")
    if not isinstance(locations_raw, list) or len(locations_raw) > 100:
        _fail("配置 locations 必须是有限数组", f"{field_path}.locations")
    locations: list[dict] = []
    for index, item in enumerate(locations_raw):
        raw = _map(item, f"{field_path}.locations[{index}]")
        _exact_keys(raw, frozenset({"kind", "name", "occurrence", "guidance"}), f"{field_path}.locations[{index}]")
        kind = _text(raw.get("kind"), f"{field_path}.locations[{index}].kind")
        if kind not in CONTEXT_KINDS:
            _fail("配置 location kind 非法", f"{field_path}.locations[{index}].kind")
        locations.append(
            {
                "kind": kind,
                "name": _name(raw.get("name"), f"{field_path}.locations[{index}].name"),
                "occurrence": _positive_int(raw.get("occurrence"), f"{field_path}.locations[{index}].occurrence"),
                "guidance": _optional_text(raw.get("guidance"), f"{field_path}.locations[{index}].guidance"),
            }
        )
    locations.sort(key=lambda item: (item["kind"], item["name"], item["occurrence"]))
    return {
        "revision_id": _id(data.get("revision_id"), f"{field_path}.revision_id"),
        "revision_no": _positive_int(data.get("revision_no"), f"{field_path}.revision_no"),
        "game_scope": _optional_text(data.get("game_scope"), f"{field_path}.game_scope"),
        "guidance": _optional_text(data.get("guidance"), f"{field_path}.guidance"),
        "locations": locations,
    }


def _normalize_calendar_basis_context(value: Any, field_path: str) -> dict:
    data = _map(value, field_path)
    _exact_keys(data, CALENDAR_BASIS_CONTEXT_KEYS, field_path)
    start = _iso_date(data.get("window_start"), f"{field_path}.window_start")
    end = _iso_date(data.get("window_end"), f"{field_path}.window_end")
    start_date = date.fromisoformat(start)
    end_date = date.fromisoformat(end)
    if end_date < start_date:
        _fail("calendar window 顺序非法", field_path)
    days_raw = data.get("days")
    if not isinstance(days_raw, list) or len(days_raw) > 31:
        _fail("calendar days 必须是有限数组", f"{field_path}.days")
    days: list[dict] = []
    for index, item in enumerate(days_raw):
        raw = _map(item, f"{field_path}.days[{index}]")
        _exact_keys(raw, CALENDAR_CONTEXT_DAY_KEYS, f"{field_path}.days[{index}]")
        state = _text(raw.get("day_state"), f"{field_path}.days[{index}].day_state")
        if state not in (*DAY_STATES, "unknown"):
            _fail("calendar day_state 非法", f"{field_path}.days[{index}].day_state")
        coverage = _text(raw.get("coverage"), f"{field_path}.days[{index}].coverage")
        if coverage not in ("known", "unknown"):
            _fail("calendar coverage 非法", f"{field_path}.days[{index}].coverage")
        names_raw = raw.get("holiday_names")
        if not isinstance(names_raw, list) or len(names_raw) > 8:
            _fail("holiday_names 必须是有限数组", f"{field_path}.days[{index}].holiday_names")
        names: list[str] = []
        for name_index, name in enumerate(names_raw):
            text = _text(name, f"{field_path}.days[{index}].holiday_names[{name_index}]", maximum=80, nonempty=True)
            if text in names:
                _fail("holiday_names 重复", f"{field_path}.days[{index}].holiday_names")
            names.append(text)
        names.sort()
        days.append(
            {
                "date": _iso_date(raw.get("date"), f"{field_path}.days[{index}].date"),
                "day_state": state,
                "holiday_names": names,
                "coverage": coverage,
            }
        )
    expected = [(start_date + timedelta(days=index)).isoformat() for index in range((end_date - start_date).days + 1)]
    if [item["date"] for item in days] != expected:
        _fail("calendar days 必须从 start 到 end 连续", f"{field_path}.days")
    return {"window_start": start, "window_end": end, "days": days}


def _normalize_teacher_entered(value: Any, field_path: str) -> dict:
    data = _map(value, field_path)
    _exact_keys(data, TEACHER_ENTERED_KEYS, field_path)
    return {
        key: _optional_text(data.get(key), f"{field_path}.{key}")
        for key in ("morning_talk_topic", "group_activity_theme")
    }


def _normalize_daily_basis(value: Any, field_path: str) -> dict:
    data = _map(value, field_path)
    _exact_keys(data, DAILY_BASIS_KEYS, field_path)
    day_state = _text(data.get("day_state"), f"{field_path}.day_state")
    if day_state not in DAY_STATES:
        _fail("day_state 非法", f"{field_path}.day_state")
    source_state = _text(data.get("source_state"), f"{field_path}.source_state")
    if source_state not in SOURCE_STATES:
        _fail("source_state 非法", f"{field_path}.source_state")
    nullable_ids = (
        "daily_plan_id",
        "content_id",
        "content_version",
        "content_hash",
    )
    values = [data.get(key) for key in nullable_ids]
    if any(value is None for value in values) and not all(value is None for value in values):
        _fail("daily basis 来源 ID 必须全有或全无", field_path)
    if data.get("content_version") is not None:
        _positive_int(data.get("content_version"), f"{field_path}.content_version")
    if data.get("content_hash") is not None:
        _hash(data.get("content_hash"), f"{field_path}.content_hash")
    mornings = data.get("morning_groups")
    posts = data.get("post_group_groups")
    if not isinstance(mornings, list) or not isinstance(posts, list):
        _fail("daily basis 游戏组必须是数组", field_path)
    return {
        "date": _iso_date(data.get("date"), f"{field_path}.date"),
        "day_state": day_state,
        "source_state": source_state,
        "daily_plan_id": _id(data["daily_plan_id"], f"{field_path}.daily_plan_id") if data.get("daily_plan_id") is not None else None,
        "content_id": _id(data["content_id"], f"{field_path}.content_id") if data.get("content_id") is not None else None,
        "content_version": _positive_int(data["content_version"], f"{field_path}.content_version") if data.get("content_version") is not None else None,
        "content_hash": _hash(data["content_hash"], f"{field_path}.content_hash") if data.get("content_hash") is not None else None,
        "morning_talk_topic": _optional_text(data.get("morning_talk_topic"), f"{field_path}.morning_talk_topic"),
        "group_activity_theme": _optional_text(data.get("group_activity_theme"), f"{field_path}.group_activity_theme"),
        "group_activity_objectives": _optional_text(data.get("group_activity_objectives"), f"{field_path}.group_activity_objectives"),
        "group_activity_process": _optional_text(data.get("group_activity_process"), f"{field_path}.group_activity_process"),
        "teacher_entered": _normalize_teacher_entered(data.get("teacher_entered"), f"{field_path}.teacher_entered"),
        "morning_groups": [
            _normalize_morning_group(item, f"{field_path}.morning_groups[{index}]")
            for index, item in enumerate(mornings)
        ],
        "post_group_groups": [
            _normalize_post_group(item, f"{field_path}.post_group_groups[{index}]")
            for index, item in enumerate(posts)
        ],
    }


def _normalize_ai_selected_basis(value: Any, field_path: str) -> dict:
    data = _map(value, field_path)
    _exact_keys(data, AI_SELECTED_BASIS_KEYS, field_path)
    refs_raw = data.get("config_refs")
    if not isinstance(refs_raw, list) or len(refs_raw) > 100:
        _fail("config_refs 必须是有限数组", f"{field_path}.config_refs")
    refs = [
        _normalize_config_ref(item, f"{field_path}.config_refs[{index}]")
        for index, item in enumerate(refs_raw)
    ]
    refs.sort(key=lambda item: (item["revision_no"], item["revision_id"], item["kind"], item["name"], item["occurrence"]))
    source_ref = data.get("source_ref")
    return {
        "candidate_id": _id(data.get("candidate_id"), f"{field_path}.candidate_id"),
        "candidate_hash": _hash(data.get("candidate_hash"), f"{field_path}.candidate_hash"),
        "input_id": _id(data.get("input_id"), f"{field_path}.input_id"),
        "execution_id": _id(data.get("execution_id"), f"{field_path}.execution_id"),
        "contract_version": _positive_int(data.get("contract_version"), f"{field_path}.contract_version"),
        "dependency_hash": _hash(data.get("dependency_hash"), f"{field_path}.dependency_hash"),
        "adopted_value_hash": _hash(data.get("adopted_value_hash"), f"{field_path}.adopted_value_hash"),
        "ai_item_id": _id(data.get("ai_item_id"), f"{field_path}.ai_item_id"),
        "source_ref": _normalize_daily_ref(source_ref, f"{field_path}.source_ref") if source_ref is not None else None,
        "config_refs": refs,
    }


def _normalize_selected_basis(value: Any, field_path: str) -> dict:
    data = _map(value, field_path)
    _exact_keys(data, SELECTED_BASIS_KEYS, field_path)
    slots_raw = _map(data.get("outdoor_game_slots"), f"{field_path}.outdoor_game_slots")
    _exact_keys(slots_raw, frozenset(OUTDOOR_SLOT_KEYS), f"{field_path}.outdoor_game_slots")
    slots: dict[str, Any] = {}
    for key in OUTDOOR_SLOT_KEYS:
        raw = slots_raw.get(key)
        if raw is None:
            slots[key] = None
            continue
        item = _map(raw, f"{field_path}.outdoor_game_slots.{key}")
        _exact_keys(item, SELECTED_ITEM_KEYS, f"{field_path}.outdoor_game_slots.{key}")
        value = _normalize_slot(item.get("value"), f"{field_path}.outdoor_game_slots.{key}.value", allow_ai=True)
        ai_basis = item.get("ai_basis")
        if ai_basis is not None:
            ai_basis = _normalize_ai_selected_basis(ai_basis, f"{field_path}.outdoor_game_slots.{key}.ai_basis")
        if value is None:
            _fail("selected value 不能为空", f"{field_path}.outdoor_game_slots.{key}.value")
        if value["source_kind"] == "ai_supplement":
            if ai_basis is None:
                _fail("AI selected 必须有 ai_basis", f"{field_path}.outdoor_game_slots.{key}.ai_basis")
            if ai_basis["ai_item_id"] != value["ai_item_id"] or ai_basis["candidate_id"] != value["candidate_id"] or ai_basis["input_id"] != value["input_id"]:
                _fail("AI selected 与 ai_basis 身份不一致", f"{field_path}.outdoor_game_slots.{key}")
        elif ai_basis is not None:
            _fail("非 AI selected 的 ai_basis 必须为 null", f"{field_path}.outdoor_game_slots.{key}.ai_basis")
        slots[key] = {"value": value, "ai_basis": ai_basis}
    focus_raw = data.get("focus_area")
    if focus_raw is None:
        focus = None
    else:
        item = _map(focus_raw, f"{field_path}.focus_area")
        _exact_keys(item, SELECTED_ITEM_KEYS, f"{field_path}.focus_area")
        value = _normalize_focus(item.get("value"), allow_ai=True, field_path=f"{field_path}.focus_area.value")
        ai_basis = item.get("ai_basis")
        if ai_basis is not None:
            ai_basis = _normalize_ai_selected_basis(ai_basis, f"{field_path}.focus_area.ai_basis")
        if value is None:
            _fail("selected focus 不能为空", f"{field_path}.focus_area.value")
        if value["source_kind"] == "ai_supplement":
            if ai_basis is None:
                _fail("AI focus 必须有 ai_basis", f"{field_path}.focus_area.ai_basis")
            if ai_basis["ai_item_id"] != value["ai_item_id"] or ai_basis["candidate_id"] != value["candidate_id"] or ai_basis["input_id"] != value["input_id"]:
                _fail("AI focus 与 ai_basis 身份不一致", f"{field_path}.focus_area")
        elif ai_basis is not None:
            _fail("非 AI focus 的 ai_basis 必须为 null", f"{field_path}.focus_area.ai_basis")
        focus = {"value": value, "ai_basis": ai_basis}
    return {"outdoor_game_slots": slots, "focus_area": focus}


def _normalize_basis(value: Any, field_path: str, *, expected_target: str, grade: str) -> dict:
    data = _map(value, field_path)
    _exact_keys(data, BASIS_KEYS, field_path)
    if data.get("schema_version") != 1 or type(data.get("schema_version")) is not int:
        _fail("basis schema_version 必须为 1", f"{field_path}.schema_version")
    target = data.get("target")
    if target != expected_target or target not in BASIS_TARGETS:
        _fail("basis target 不匹配", f"{field_path}.target")
    if _text(data.get("grade"), f"{field_path}.grade") != grade:
        _fail("basis grade 与 content 不一致", f"{field_path}.grade")
    theme = _optional_text(data.get("theme"), f"{field_path}.theme")
    manual_text = _optional_text(data.get("manual_text"), f"{field_path}.manual_text")
    daily_raw = data.get("daily_sources")
    if not isinstance(daily_raw, list) or len(daily_raw) > 7:
        _fail("basis daily_sources 必须是有限数组", f"{field_path}.daily_sources")
    daily = [
        _normalize_daily_basis(item, f"{field_path}.daily_sources[{index}]")
        for index, item in enumerate(daily_raw)
    ]
    if [item["date"] for item in daily] != sorted(item["date"] for item in daily):
        _fail("daily_sources 必须日期升序", f"{field_path}.daily_sources")
    selected = data.get("selected")
    selected_value = _normalize_selected_basis(selected, f"{field_path}.selected") if selected is not None else None
    config_raw = data.get("config")
    if not isinstance(config_raw, list) or len(config_raw) > 20:
        _fail("basis config 必须是有限数组", f"{field_path}.config")
    config = [
        _normalize_config_basis(item, f"{field_path}.config[{index}]")
        for index, item in enumerate(config_raw)
    ]
    config.sort(key=lambda item: (item["revision_no"], item["revision_id"]))
    calendar = data.get("calendar")
    calendar_value = _normalize_calendar_basis_context(calendar, f"{field_path}.calendar") if calendar is not None else None

    if target == "games":
        if theme is not None or manual_text is not None or selected_value is not None or calendar_value is not None:
            _fail("games basis 含未使用字段", field_path)
        if not config:
            _fail("games basis 必须有 config", field_path)
    elif target in ("key_week_focus", "habit_culture"):
        if selected_value is not None or config or calendar_value is not None:
            _fail("栏目 basis 含未使用字段", field_path)
        if theme is None or manual_text is None:
            _fail("栏目 basis 必须保留 theme/manual_text", field_path)
    elif target == "environment_setup":
        if selected_value is None or calendar_value is not None:
            _fail("environment basis 缺少 selected 或含 calendar", field_path)
        if theme is None or manual_text is None:
            _fail("environment basis 必须保留 theme/manual_text", field_path)
    elif target == "home_cooperation":
        if selected_value is not None or config or calendar_value is None:
            _fail("home basis 缺少 calendar 或含未使用字段", field_path)
        if theme is None or manual_text is None:
            _fail("home basis 必须保留 theme/manual_text", field_path)
    elif target == "materials":
        if selected_value is None or theme is not None or manual_text is not None or calendar_value is not None or daily:
            _fail("materials basis 含未使用字段", field_path)
        if not config:
            # A material basis may consist of a manual/daily selection without
            # a config; allow empty config but selected is still required.
            pass
    return {
        "schema_version": 1,
        "target": target,
        "grade": _text(data.get("grade"), f"{field_path}.grade"),
        "theme": theme,
        "manual_text": manual_text,
        "daily_sources": daily,
        "selected": selected_value,
        "config": config,
        "calendar": calendar_value,
    }


def _normalize_adoption(value: Any, field_path: str, *, target: str, current_value: Any, grade: str) -> dict:
    data = _map(value, field_path)
    _exact_keys(data, ADOPTION_KEYS, field_path)
    for key in ("candidate_id", "input_id", "execution_id", "adopted_draft_id", "adopter_profile_id"):
        _id(data.get(key), f"{field_path}.{key}")
    _hash(data.get("candidate_hash"), f"{field_path}.candidate_hash")
    _positive_int(data.get("contract_version"), f"{field_path}.contract_version")
    _hash(data.get("dependency_hash"), f"{field_path}.dependency_hash")
    _positive_int(data.get("adopted_draft_version"), f"{field_path}.adopted_draft_version")
    _utc_timestamp(data.get("adopted_at"), f"{field_path}.adopted_at")
    basis = _normalize_basis(data.get("basis"), f"{field_path}.basis", expected_target=target, grade=grade)
    adopted_value = data.get("adopted_value")
    if target == "games":
        adopted_value = _normalize_games_target(adopted_value, f"{field_path}.adopted_value")
    elif target in WEEKLY_COLUMN_KEYS:
        raw = _map(adopted_value, f"{field_path}.adopted_value")
        _exact_keys(raw, frozenset({"text"}), f"{field_path}.adopted_value")
        adopted_value = {"text": _text(raw.get("text"), f"{field_path}.adopted_value.text", nonempty=True)}
    else:
        _fail("采用目标非法", f"{field_path}.target")
    adopted_hash = _hash(data.get("adopted_value_hash"), f"{field_path}.adopted_value_hash")
    if adopted_hash != content_hash(adopted_value):
        _fail("adopted_value_hash 不一致", f"{field_path}.adopted_value_hash")
    manual_edited = _bool(data.get("manual_edited"), f"{field_path}.manual_edited")
    if target == "games":
        expected_edited = canonical_json(adopted_value) != canonical_json(_normalize_games_target(current_value, "content.games"))
    else:
        expected_edited = adopted_value["text"] != _text(current_value, "weekly_columns.value")
    if manual_edited != expected_edited:
        _fail("manual_edited 与服务端派生值不一致", f"{field_path}.manual_edited")
    return {
        "candidate_id": data["candidate_id"],
        "candidate_hash": data["candidate_hash"],
        "input_id": data["input_id"],
        "execution_id": data["execution_id"],
        "contract_version": data["contract_version"],
        "dependency_hash": data["dependency_hash"],
        "adopted_draft_id": data["adopted_draft_id"],
        "adopted_draft_version": data["adopted_draft_version"],
        "adopter_profile_id": data["adopter_profile_id"],
        "adopted_at": data["adopted_at"],
        "adopted_value": adopted_value,
        "adopted_value_hash": adopted_hash,
        "manual_edited": manual_edited,
        "basis": basis,
    }


def _normalize_ai_provenance(
    value: Any,
    field_path: str,
    *,
    slots: Mapping[str, Any],
    focus: Any,
    columns: Mapping[str, Any],
    grade: str,
) -> dict:
    data = _map(value, field_path)
    _exact_keys(data, AI_PROVENANCE_KEYS, field_path)
    result: dict[str, Any] = {}
    for key in AI_PROVENANCE_KEYS:
        raw = data.get(key)
        if raw is None:
            result[key] = None
            continue
        if key == "games":
            current = {"outdoor_game_slots": slots, "focus_area": focus}
        elif key in WEEKLY_COLUMN_KEYS:
            current = columns[key]
        else:
            _fail("ai_provenance 键非法", f"{field_path}.{key}")
        result[key] = _normalize_adoption(
            raw,
            f"{field_path}.{key}",
            target=key,
            current_value=current,
            grade=grade,
        )
    return result


def _validate_ai_items_against_games(slots: Mapping[str, Any], focus: Any, provenance: Mapping[str, Any]) -> None:
    ai_items: list[tuple[str, dict]] = []
    for key, slot in slots.items():
        if slot is not None and slot.get("source_kind") == "ai_supplement":
            ai_items.append((key, slot))
    if focus is not None and focus.get("source_kind") == "ai_supplement":
        ai_items.append(("focus_area", focus))
    if not ai_items:
        return
    games = provenance.get("games")
    if games is None:
        _fail("AI 槽/重点区域缺少 games provenance", "content.ai_provenance.games")
    adopted = games["adopted_value"]
    for key, item in ai_items:
        if item["candidate_id"] != games["candidate_id"] or item["input_id"] != games["input_id"]:
            _fail("AI 项 candidate/input 与 games provenance 不一致", f"content.outdoor_game_slots.{key}")
        if key == "focus_area":
            adopted_item = adopted.get("focus_area")
        else:
            adopted_item = adopted["outdoor_game_slots"].get(key)
        if adopted_item is None or adopted_item.get("ai_item_id") != item["ai_item_id"]:
            _fail("AI 项未出现在 games adopted_value", f"content.outdoor_game_slots.{key}")
        for field in ("candidate_id", "input_id", "basis_keys"):
            if adopted_item.get(field) != item.get(field):
                _fail("AI 项与 games adopted_value 不一致", f"content.outdoor_game_slots.{key}")


def _normalize_materials_text(value: Any, field_path: str) -> str | None:
    if value is None:
        return None
    text = _text(value, field_path, maximum=MAX_MATERIAL_SYNTHESIS)
    return text


def _stored_source_text(source: Mapping[str, Any], field_path: str) -> str:
    value = source.get(field_path)
    if value is None:
        return ""
    return _text(value, f"source.{field_path}")


def _normalize_stored_material_item(value: Any, field_path: str) -> dict:
    from app.local import weekly_ai_contracts as contracts

    data = _map(value, field_path)
    _exact_keys(data, MATERIAL_ITEM_KEYS, field_path)
    text = _text(data.get("text"), f"{field_path}.text", maximum=MAX_MATERIAL_ITEM_TEXT, nonempty=True)
    origin = data.get("origin")
    if origin not in ("extracted", "suggested"):
        _fail("origin 非法", f"{field_path}.origin")
    refs_raw = data.get("evidence_refs")
    if not isinstance(refs_raw, list) or len(refs_raw) > MAX_MATERIAL_ITEMS:
        _fail("evidence_refs 必须是有限数组", f"{field_path}.evidence_refs")
    if origin == "extracted" and not refs_raw:
        _fail("extracted 必须有证据", f"{field_path}.evidence_refs")
    if origin == "suggested" and refs_raw:
        _fail("suggested 不得有证据", f"{field_path}.evidence_refs")
    refs: list[dict] = []
    seen: set[tuple[Any, ...]] = set()
    for index, raw_ref in enumerate(refs_raw):
        ref_path = f"{field_path}.evidence_refs[{index}]"
        ref = _map(raw_ref, ref_path)
        _exact_keys(ref, MATERIAL_EVIDENCE_KEYS, ref_path)
        handle = _text(ref.get("source_handle"), f"{ref_path}.source_handle", maximum=6, nonempty=True)
        if not HANDLE_RE.fullmatch(handle):
            _fail("source_handle 语法非法", f"{ref_path}.source_handle")
        source = contracts.validate_typed_handle(handle, ref.get("source"))
        field_path_value = _text(ref.get("field_path"), f"{ref_path}.field_path", maximum=64, nonempty=True)
        if field_path_value not in contracts.EVIDENCE_FIELD_PATHS[source["kind"]]:
            _fail("field_path 不允许", f"{ref_path}.field_path")
        start = ref.get("start")
        end = ref.get("end")
        if type(start) is not int or type(end) is not int or start < 0 or end <= start:
            _fail("证据位置非法", ref_path)
        quote = _text(ref.get("quote"), f"{ref_path}.quote", maximum=MAX_MATERIAL_QUOTE, nonempty=True)
        source_text = _stored_source_text(source, field_path_value)
        if end > len(source_text) or source_text[start:end] != quote:
            _fail("证据位置与原文不匹配", ref_path)
        key = (handle, field_path_value, start, end, quote)
        if key in seen:
            _fail("证据重复", ref_path)
        seen.add(key)
        refs.append({"source_handle": handle, "field_path": field_path_value, "start": start, "end": end, "quote": quote, "source": source})
    return {"text": text, "origin": origin, "evidence_refs": refs}


def _evidence_text(value: Any) -> str:
    return "" if value is None else value


def _selected_value_items(basis: Mapping[str, Any]) -> list[tuple[str | None, dict]]:
    result: list[tuple[str | None, dict]] = []
    selected = basis.get("selected") or {}
    for key, item in (selected.get("outdoor_game_slots") or {}).items():
        if item is not None:
            result.append((key, item["value"]))
    focus = selected.get("focus_area")
    if focus is not None:
        result.append((None, focus["value"]))
    return result


def _selected_ai_config_refs(basis: Mapping[str, Any]) -> set[tuple[Any, ...]]:
    refs: set[tuple[Any, ...]] = set()
    selected = basis.get("selected") or {}
    items: list[Mapping[str, Any]] = []
    for item in (selected.get("outdoor_game_slots") or {}).values():
        if item is not None:
            items.append(item)
    if selected.get("focus_area") is not None:
        items.append(selected["focus_area"])
    for item in items:
        if item["value"].get("source_kind") != "ai_supplement":
            continue
        for ref in (item.get("ai_basis") or {}).get("config_refs") or []:
            refs.add(
                (
                    ref["revision_id"],
                    ref["revision_no"],
                    ref["kind"],
                    ref["name"],
                    ref["occurrence"],
                )
            )
    return refs


def _matches_selected_source(
    source: Mapping[str, Any], value: Mapping[str, Any], slot_key: str | None
) -> bool:
    kind = source["kind"]
    source_kind = value.get("source_kind")
    if kind == "morning_game":
        if slot_key not in (*COLLECTIVE_SLOT_KEYS, *FREE_CHOICE_SLOT_KEYS):
            return False
        expected_group_kind = (
            "collective" if slot_key in COLLECTIVE_SLOT_KEYS else "free_choice"
        )
        return (
            source_kind == "daily_plan"
            and value.get("section") == "morning_games"
            and source["group_kind"] == expected_group_kind
            and all(
                source[key] == value.get(key)
                for key in (
                    "daily_plan_id",
                    "content_id",
                    "content_version",
                    "content_hash",
                    "group_id",
                    "game_id",
                    "name",
                )
            )
            and _evidence_text(source["shared_objectives"])
            == _evidence_text(value.get("shared_objectives"))
            and _evidence_text(source["guidance_points"])
            == _evidence_text(value.get("guidance_points"))
            and _evidence_text(source["focus_guidance"])
            == _evidence_text(value.get("focus_guidance"))
        )
    if kind == "post_group_game":
        return (
            slot_key is None
            and source_kind == "daily_plan"
            and value.get("section") == "post_group_games"
            and all(
                source[key] == value.get(key)
                for key in (
                    "daily_plan_id",
                    "content_id",
                    "content_version",
                    "content_hash",
                    "group_id",
                    "game_id",
                    "name",
                    "context_kind",
                )
            )
            and _evidence_text(source["area"]) == _evidence_text(value.get("area"))
            and _evidence_text(source["objectives"])
            == _evidence_text(value.get("objectives"))
            and _evidence_text(source["guidance"])
            == _evidence_text(value.get("guidance"))
            and _evidence_text(source["support_strategy"])
            == _evidence_text(value.get("support_strategy"))
        )
    if kind == "manual_outdoor":
        return (
            slot_key is not None
            and source_kind == "manual"
            and source["slot_key"] == slot_key
            and source["manual_item_id"] == value.get("manual_item_id")
            and _evidence_text(source["name"]) == _evidence_text(value.get("name"))
            and _evidence_text(source["shared_objectives"])
            == _evidence_text(value.get("shared_objectives"))
            and _evidence_text(source["guidance_points"])
            == _evidence_text(value.get("guidance_points"))
            and _evidence_text(source["focus_guidance"])
            == _evidence_text(value.get("focus_guidance"))
        )
    if kind == "ai_outdoor":
        return (
            slot_key is not None
            and source_kind == "ai_supplement"
            and source["slot_key"] == slot_key
            and source["ai_item_id"] == value.get("ai_item_id")
            and source["candidate_id"] == value.get("candidate_id")
            and source["input_id"] == value.get("input_id")
            and _evidence_text(source["name"]) == _evidence_text(value.get("name"))
            and _evidence_text(source["shared_objectives"])
            == _evidence_text(value.get("shared_objectives"))
            and _evidence_text(source["guidance_points"])
            == _evidence_text(value.get("guidance_points"))
            and _evidence_text(source["focus_guidance"])
            == _evidence_text(value.get("focus_guidance"))
        )
    if kind == "ai_focus":
        return (
            slot_key is None
            and source_kind == "ai_supplement"
            and source["ai_item_id"] == value.get("ai_item_id")
            and source["candidate_id"] == value.get("candidate_id")
            and source["input_id"] == value.get("input_id")
            and source["context_kind"] == value.get("context_kind")
            and _evidence_text(source["area"]) == _evidence_text(value.get("area"))
            and _evidence_text(source["name"]) == _evidence_text(value.get("name"))
            and _evidence_text(source["objectives"])
            == _evidence_text(value.get("objectives"))
            and _evidence_text(source["guidance"])
            == _evidence_text(value.get("guidance"))
            and _evidence_text(source["support_strategy"])
            == _evidence_text(value.get("support_strategy"))
        )
    return False


def _matches_basis_config(source: Mapping[str, Any], basis: Mapping[str, Any]) -> bool:
    refs = _selected_ai_config_refs(basis)
    if not refs:
        return False
    source_ref = (
        source["revision_id"],
        source["revision_no"],
        source["location_kind"],
        source["name"],
        source["occurrence"],
    )
    if source_ref not in refs:
        return False
    for entry in basis.get("config") or []:
        if (
            entry.get("revision_id") != source["revision_id"]
            or entry.get("revision_no") != source["revision_no"]
        ):
            continue
        if _evidence_text(entry.get("game_scope")) != _evidence_text(
            source.get("game_scope")
        ):
            continue
        if _evidence_text(entry.get("guidance")) != _evidence_text(
            source.get("config_guidance")
        ):
            continue
        for location in entry.get("locations") or []:
            if (
                location.get("kind") == source["location_kind"]
                and location.get("name") == source["name"]
                and location.get("occurrence") == source["occurrence"]
                and _evidence_text(location.get("guidance"))
                == _evidence_text(source.get("guidance"))
            ):
                return True
    return False


def _validate_materials_evidence_basis(
    items: Sequence[Mapping[str, Any]], basis: Mapping[str, Any]
) -> None:
    selected_values = _selected_value_items(basis)
    for item_index, item in enumerate(items):
        for ref_index, ref in enumerate(item.get("evidence_refs") or []):
            source = ref["source"]
            if source["kind"] == "config_location":
                matched = _matches_basis_config(source, basis)
            else:
                matched = any(
                    _matches_selected_source(source, value, slot_key)
                    for slot_key, value in selected_values
                )
            if not matched:
                _fail(
                    "证据来源不属于冻结材料依据",
                    f"materials_provenance.items[{item_index}].evidence_refs[{ref_index}]",
                )


def _normalize_materials_provenance(value: Any, field_path: str, *, materials: str | None, grade: str) -> dict | None:
    if value is None:
        if materials is not None:
            _fail("无 materials_provenance 时 materials 必须为 null", "content.materials")
        return None
    data = _map(value, field_path)
    _exact_keys(data, MATERIALS_PROVENANCE_KEYS, field_path)
    for key in ("candidate_id", "input_id", "execution_id", "adopted_draft_id", "adopter_profile_id"):
        _id(data.get(key), f"{field_path}.{key}")
    _hash(data.get("candidate_hash"), f"{field_path}.candidate_hash")
    _positive_int(data.get("contract_version"), f"{field_path}.contract_version")
    _hash(data.get("dependency_hash"), f"{field_path}.dependency_hash")
    _positive_int(data.get("adopted_draft_version"), f"{field_path}.adopted_draft_version")
    _utc_timestamp(data.get("adopted_at"), f"{field_path}.adopted_at")
    basis = _normalize_basis(data.get("basis"), f"{field_path}.basis", expected_target="materials", grade=grade)
    basis_hash = _hash(data.get("basis_hash"), f"{field_path}.basis_hash")
    if basis_hash != content_hash(basis):
        _fail("basis_hash 不一致", f"{field_path}.basis_hash")
    items_raw = data.get("items")
    if not isinstance(items_raw, list) or len(items_raw) > MAX_MATERIAL_ITEMS:
        _fail("items 必须是有限数组", f"{field_path}.items")
    items = [_normalize_stored_material_item(item, f"{field_path}.items[{index}]") for index, item in enumerate(items_raw)]
    _validate_materials_evidence_basis(items, basis)
    original_text = _text(data.get("original_text"), f"{field_path}.original_text", maximum=MAX_MATERIAL_SYNTHESIS)
    if original_text != "\n".join(item["text"] for item in items):
        _fail("original_text 与 items 不一致", f"{field_path}.original_text")
    edited = _bool(data.get("edited"), f"{field_path}.edited")
    if edited != (materials != original_text):
        _fail("edited 与服务端派生值不一致", f"{field_path}.edited")
    if materials is not None and len(materials) > MAX_MATERIAL_SYNTHESIS:
        _fail("materials 正文超限", "content.materials")
    return {
        "candidate_id": data["candidate_id"],
        "candidate_hash": data["candidate_hash"],
        "input_id": data["input_id"],
        "execution_id": data["execution_id"],
        "contract_version": data["contract_version"],
        "dependency_hash": data["dependency_hash"],
        "basis": basis,
        "basis_hash": basis_hash,
        "items": items,
        "original_text": original_text,
        "edited": edited,
        "adopter_profile_id": data["adopter_profile_id"],
        "adopted_draft_id": data["adopted_draft_id"],
        "adopted_draft_version": data["adopted_draft_version"],
        "adopted_at": data["adopted_at"],
    }


def validate_content(
    content: Any,
    *,
    snapshot: Mapping[str, Any] | None = None,
    expected_schema: int | None = None,
) -> dict:
    """Strictly validate stored/derived schema1/schema2 content."""
    data = _map(content, "content")
    schema_version = data.get("schema_version")
    if type(schema_version) is not int or schema_version not in (SCHEMA1_VERSION, SCHEMA2_VERSION):
        _fail("schema_version 必须严格为 1 或 2", "content.schema_version")
    if expected_schema is not None and schema_version != expected_schema:
        _fail("schema_version 与期望不一致", "content.schema_version")
    _exact_keys(
        data,
        CONTENT_KEYS_V2 if schema_version == SCHEMA2_VERSION else CONTENT_KEYS_V1,
        "content",
    )
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
    allow_ai = schema_version == SCHEMA2_VERSION
    slots = {
        key: _normalize_slot(
            slots_raw.get(key),
            f"content.outdoor_game_slots.{key}",
            allow_ai=allow_ai,
        )
        for key in OUTDOOR_SLOT_KEYS
    }
    manual_ids: set[str] = set()
    ai_item_ids: set[str] = set()
    for key, slot in slots.items():
        if slot is not None and slot["source_kind"] == "manual":
            if slot["manual_item_id"] in manual_ids:
                _fail("manual_item_id 重复", f"content.outdoor_game_slots.{key}")
            manual_ids.add(slot["manual_item_id"])
        if slot is not None and slot["source_kind"] == "ai_supplement":
            if slot["ai_item_id"] in ai_item_ids:
                _fail("ai_item_id 重复", f"content.outdoor_game_slots.{key}")
            ai_item_ids.add(slot["ai_item_id"])
    _validate_collective_slot_names(slots)
    focus = _normalize_focus(data.get("focus_area"), allow_ai=allow_ai)
    if focus is not None and focus["source_kind"] == "ai_supplement":
        if focus["ai_item_id"] in ai_item_ids:
            _fail("ai_item_id 重复", "content.focus_area")
        ai_item_ids.add(focus["ai_item_id"])
    columns = _normalize_columns(data.get("weekly_columns"), "content.weekly_columns")
    if schema_version == SCHEMA1_VERSION:
        if data.get("materials") is not None:
            _fail("schema1 materials 必须为 null", "content.materials")
        materials = None
        ai_provenance = None
        materials_provenance = None
    else:
        materials = _normalize_materials_text(data.get("materials"), "content.materials")
        ai_provenance = None
        materials_provenance = None
    manifest = _normalize_source_manifest(data.get("source_manifest"))
    calendar = _normalize_calendar_basis(data.get("calendar_basis"))
    if schema_version == SCHEMA2_VERSION:
        grade = manifest["header"]["grade"]
        ai_provenance = _normalize_ai_provenance(
            data.get("ai_provenance"),
            "content.ai_provenance",
            slots=slots,
            focus=focus,
            columns=columns,
            grade=grade,
        )
        materials_provenance = _normalize_materials_provenance(
            data.get("materials_provenance"),
            "content.materials_provenance",
            materials=materials,
            grade=grade,
        )
        if materials_provenance is None and materials is not None:
            _fail("无 materials_provenance 时 materials 必须为 null", "content.materials")
        _validate_ai_items_against_games(slots, focus, ai_provenance)
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
        "schema_version": schema_version,
        "theme": theme,
        "deterministic": rows,
        "outdoor_game_slots": slots,
        "focus_area": focus,
        "weekly_columns": columns,
        "materials": materials,
        "source_manifest": manifest,
        "calendar_basis": calendar,
    }
    if schema_version == SCHEMA2_VERSION:
        result["ai_provenance"] = ai_provenance
        result["materials_provenance"] = materials_provenance
        provenance_bytes = len(
            _canonical_json(
                {
                    "ai_provenance": ai_provenance,
                    "materials_provenance": materials_provenance,
                }
            ).encode("utf-8")
        )
        if provenance_bytes > MAX_PROVENANCE_BYTES:
            _fail("provenance 超过 512KiB", "content", "WEEKLY_CONTENT_TOO_LARGE")
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
        "schema_version": SCHEMA2_VERSION,
        "theme": theme,
        "deterministic": _rows_from_snapshot(snap),
        "outdoor_game_slots": {key: None for key in OUTDOOR_SLOT_KEYS},
        "focus_area": None,
        "weekly_columns": {key: "" for key in WEEKLY_COLUMN_KEYS},
        "materials": None,
        "source_manifest": _source_manifest_from_snapshot(snap),
        "calendar_basis": _calendar_basis_from_snapshot(snap),
        "ai_provenance": {key: None for key in AI_PROVENANCE_KEYS},
        "materials_provenance": None,
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


def _apply_slots(
    previous: Mapping[str, Any],
    payload: Any,
    snapshot: Mapping[str, Any],
    manual_ids: Mapping[str, str] | None,
    *,
    allow_ai: bool = False,
) -> dict:
    data = _map(payload, "outdoor_game_slots")
    unknown = set(data) - set(OUTDOOR_SLOT_KEYS)
    if unknown:
        _fail(
            f"outdoor_game_slots 含未知字段 count={len(unknown)}",
            "outdoor_game_slots",
        )
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
        if allow_ai and raw.get("source_kind") == "ai_supplement":
            old = previous_slots.get(key)
            if old is None or canonical_json(old) != canonical_json(raw):
                _fail("普通 PATCH 只能原样回传既有 AI 项", f"outdoor_game_slots.{key}")
            result[key] = copy.deepcopy(old)
            continue
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


def _apply_focus(
    previous: Mapping[str, Any],
    payload: Any,
    snapshot: Mapping[str, Any],
    *,
    allow_ai: bool = False,
) -> dict | None:
    if payload is None:
        return None
    raw = _map(payload, "focus_area")
    if allow_ai and raw.get("source_kind") == "ai_supplement":
        old = previous["focus_area"]
        if old is None or canonical_json(old) != canonical_json(raw):
            _fail("普通 PATCH 只能原样回传既有 AI 重点区域", "focus_area")
        return copy.deepcopy(old)
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


ADOPTION_METADATA_KEYS = frozenset(
    {
        "candidate_id",
        "candidate_hash",
        "input_id",
        "execution_id",
        "contract_version",
        "dependency_hash",
        "adopter_profile_id",
        "adopted_draft_id",
        "adopted_draft_version",
        "adopted_at",
    }
)


def apply_weekly_ai_adoption(
    previous: Mapping[str, Any],
    *,
    target: str,
    candidate_value: Mapping[str, Any],
    adoption: Mapping[str, Any],
    basis: Mapping[str, Any],
    edited_value: Mapping[str, Any] | None = None,
    server_manifest: Mapping[str, Any] | None = None,
    ai_item_ids: Mapping[str, str] | None = None,
) -> dict:
    """Pure adoption merge; the original source value stays the provenance.

    ``edited_value`` is the legal teacher-edited projection.  It changes the
    adopted draft value only; provenance continues to point at the original
    candidate and source value, and the existing manual_edited/edited flags
    are derived from the difference.
    """
    prev = validate_content(previous)
    if target not in BASIS_TARGETS:
        _fail("采用目标非法", "target")
    meta = _map(adoption, "adoption")
    _exact_keys(meta, ADOPTION_METADATA_KEYS, "adoption")
    value = _map(candidate_value, "candidate_value")
    edited = _map(edited_value, "edited_value") if edited_value is not None else value
    base = promote_to_schema2(prev) if prev["schema_version"] == SCHEMA1_VERSION else copy.deepcopy(prev)
    if target == "games":
        from app.local import weekly_ai_contracts as contracts

        original_finalized = contracts.finalize_games_value(
            value,
            candidate_id=meta["candidate_id"],
            input_id=meta["input_id"],
            ai_item_ids=ai_item_ids or {},
        )
        edited_finalized = contracts.finalize_games_value(
            edited,
            candidate_id=meta["candidate_id"],
            input_id=meta["input_id"],
            ai_item_ids=ai_item_ids or {},
        )
        base["outdoor_game_slots"] = copy.deepcopy(edited_finalized["outdoor_game_slots"])
        base["focus_area"] = copy.deepcopy(edited_finalized["focus_area"])
        adopted_value = {
            "outdoor_game_slots": copy.deepcopy(original_finalized["outdoor_game_slots"]),
            "focus_area": copy.deepcopy(original_finalized["focus_area"]),
        }
        base["ai_provenance"]["games"] = {
            **copy.deepcopy(meta),
            "adopted_value": adopted_value,
            "adopted_value_hash": content_hash(adopted_value),
            "manual_edited": False,
            "basis": copy.deepcopy(dict(basis)),
        }
    elif target in WEEKLY_COLUMN_KEYS:
        _exact_keys(value, frozenset({"text"}), "candidate_value")
        _exact_keys(edited, frozenset({"text"}), "edited_value")
        original_text = _text(value.get("text"), "candidate_value.text", nonempty=True)
        edited_text = _text(edited.get("text"), "edited_value.text", nonempty=True)
        base["weekly_columns"][target] = edited_text
        adopted_value = {"text": original_text}
        base["ai_provenance"][target] = {
            **copy.deepcopy(meta),
            "adopted_value": adopted_value,
            "adopted_value_hash": content_hash(adopted_value),
            "manual_edited": False,
            "basis": copy.deepcopy(dict(basis)),
        }
    elif target == "materials":
        if server_manifest is None:
            _fail("材料采用缺少 server_manifest", "server_manifest")
        from app.local import weekly_materials

        _exact_keys(value, frozenset({"items"}), "candidate_value")
        _exact_keys(edited, frozenset({"items"}), "edited_value")
        original_items = weekly_materials.materialize_materials_items(
            value.get("items"), server_manifest=server_manifest
        )
        edited_items = weekly_materials.materialize_materials_items(
            edited.get("items"), server_manifest=server_manifest
        )
        original_text = weekly_materials.synthesize_materials_text(original_items)
        edited_text = weekly_materials.synthesize_materials_text(edited_items)
        base["materials"] = edited_text
        base["materials_provenance"] = weekly_materials.build_materials_provenance(
            candidate_id=meta["candidate_id"],
            candidate_hash=meta["candidate_hash"],
            input_id=meta["input_id"],
            execution_id=meta["execution_id"],
            contract_version=meta["contract_version"],
            dependency_hash=meta["dependency_hash"],
            basis=basis,
            items=original_items,
            original_text=original_text,
            adopter_profile_id=meta["adopter_profile_id"],
            adopted_draft_id=meta["adopted_draft_id"],
            adopted_draft_version=meta["adopted_draft_version"],
            adopted_at=meta["adopted_at"],
        )
    else:
        _fail("采用目标非法", "target")
    _update_provenance_flags(base)
    return validate_content(base)


def content_schema_version(value: object) -> int:
    data = _map(value, "content")
    schema = data.get("schema_version")
    if type(schema) is not int or schema not in (SCHEMA1_VERSION, SCHEMA2_VERSION):
        _fail("schema_version 必须严格为 1 或 2", "content.schema_version")
    return schema


def promote_to_schema2(content: Mapping[str, Any]) -> dict:
    prev = validate_content(content, expected_schema=SCHEMA1_VERSION)
    promoted = {
        **copy.deepcopy(prev),
        "schema_version": SCHEMA2_VERSION,
        "ai_provenance": {key: None for key in AI_PROVENANCE_KEYS},
        "materials_provenance": None,
    }
    return validate_content(promoted, expected_schema=SCHEMA2_VERSION)


def _update_provenance_flags(result: dict) -> None:
    if result["schema_version"] != SCHEMA2_VERSION:
        return
    games = result["ai_provenance"].get("games")
    if games is not None:
        current = {
            "outdoor_game_slots": result["outdoor_game_slots"],
            "focus_area": result["focus_area"],
        }
        games["manual_edited"] = canonical_json(current) != canonical_json(games["adopted_value"])
    for field in WEEKLY_COLUMN_KEYS:
        adoption = result["ai_provenance"].get(field)
        if adoption is not None:
            adoption["manual_edited"] = (
                result["weekly_columns"][field] != adoption["adopted_value"]["text"]
            )
    materials_prov = result.get("materials_provenance")
    if materials_prov is not None:
        materials_prov["edited"] = result["materials"] != materials_prov["original_text"]


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
    schema_version = prev["schema_version"]
    data = _map(patch, "patch")
    allowed = set(PATCH_KEYS)
    if schema_version == SCHEMA2_VERSION:
        allowed.add("materials")
    unknown = set(data) - allowed
    if unknown:
        _fail(f"patch 含未知字段 count={len(unknown)}", "patch")
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
        slots = _apply_slots(
            prev,
            data["outdoor_game_slots"],
            snap,
            manual_ids,
            allow_ai=schema_version == SCHEMA2_VERSION,
        )
    focus = prev["focus_area"]
    if "focus_area" in data:
        focus = _apply_focus(
            prev,
            data["focus_area"],
            snap,
            allow_ai=schema_version == SCHEMA2_VERSION,
        )
    columns = prev["weekly_columns"]
    if "weekly_columns" in data:
        columns = _apply_columns(prev["weekly_columns"], data["weekly_columns"])
    materials = prev.get("materials")
    materials_provenance = copy.deepcopy(prev.get("materials_provenance"))
    if "materials" in data:
        submitted = data["materials"]
        if materials_provenance is None:
            if submitted is not None:
                _fail("无 materials_provenance 只允许维持 null", "patch.materials")
            materials = None
        elif submitted is None:
            materials = None
        elif isinstance(submitted, str):
            materials = _text(submitted, "patch.materials", maximum=MAX_MATERIAL_SYNTHESIS)
        else:
            _fail("materials 必须是字符串或 null", "patch.materials")
    business = {
        "theme": theme,
        "deterministic": rows,
        "outdoor_game_slots": slots,
        "focus_area": focus,
        "weekly_columns": columns,
        "materials": materials,
        "source_manifest": copy.deepcopy(prev["source_manifest"]),
        "calendar_basis": copy.deepcopy(prev["calendar_basis"]),
    }
    if schema_version == SCHEMA1_VERSION:
        # Business no-op is decided before any storage-format promotion.
        if canonical_json(business) == canonical_json(
            {key: prev[key] for key in business}
        ):
            return copy.deepcopy(prev)
        result = {
            "schema_version": SCHEMA2_VERSION,
            **business,
            "materials": None,
            "ai_provenance": {key: None for key in AI_PROVENANCE_KEYS},
            "materials_provenance": None,
        }
    else:
        result = {
            "schema_version": SCHEMA2_VERSION,
            **business,
            "ai_provenance": copy.deepcopy(prev.get("ai_provenance")),
            "materials_provenance": materials_provenance,
        }
        _update_provenance_flags(result)
        if canonical_json(result) == canonical_json(prev):
            return copy.deepcopy(prev)
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
        if old is None or old["source_kind"] in ("manual", "ai_supplement"):
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
    elif old_focus["source_kind"] == "ai_supplement":
        focus = copy.deepcopy(old_focus)
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
    if prev["schema_version"] == SCHEMA1_VERSION:
        if canonical_json(content) == canonical_json(prev):
            return {
                "content": copy.deepcopy(prev),
                "differences": differences,
                "preserved": preserved,
            }
        content["schema_version"] = SCHEMA2_VERSION
        content["ai_provenance"] = {key: None for key in AI_PROVENANCE_KEYS}
        content["materials_provenance"] = None
        content["materials"] = None
    else:
        _update_provenance_flags(content)
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
    if fixed["materials"] is None or not fixed["materials"].strip():
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
        if slot is None or slot["source_kind"] in ("manual", "ai_supplement"):
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
    if focus is not None and focus["source_kind"] != "ai_supplement":
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
    "content_schema_version",
    "promote_to_schema2",
    "apply_weekly_ai_adoption",
]
