"""Pure weekly AI raw-manifest validation, projection and fact derivation.

A owns database reads; this module only accepts A's frozen raw manifest and a
validated saved weekly content value.  It returns the exact model payload,
business dependencies, input-local typed handle manifest, dependency hash and
target hashes required by the frozen engineering contract.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from app.local import weekly_ai_contracts as contracts
from app.local import weekly_materials, weekly_plan_content

CONTRACT_VERSION = 1
AI_INPUT_SCHEMA_VERSION = 1
MAX_MANIFEST_BYTES = 1_048_576
MAX_DEPENDENCIES_BYTES = 2_097_152
MAX_PAYLOAD_BYTES = 1_048_576
MAX_AI_TEXT_CHARS = 100_000
MAX_AI_ARRAY_ITEMS = 100
MAX_ID_CHARS = 32
MAX_NAME_CHARS = 80
MAX_HEADER_NAMES = 100
MAX_HEADER_JSON_BYTES = 32 * 1024
MAX_CONFIG_LOCATIONS = 100
MAX_DAY_GROUPS = 100
MAX_GROUP_GAMES = 100

DAY_STATES = ("teaching", "rest", "outside_term")
CALENDAR_DAY_STATES = (*DAY_STATES, "unknown")
SOURCE_STATES = ("saved", "no_plan", "none_required")
CONTEXT_KINDS = ("area", "outdoor", "special_room")
GRADES = ("small", "middle", "large")
TARGETS = ("games", *contracts.COLUMN_FIELDS, "materials")
TASK_TARGETS = dict(contracts.TASK_TARGETS)
GRADE_LABELS = {"small": "小班", "middle": "中班", "large": "大班"}
WEEKLY_STAGE = "kindergarten"
WEEKLY_STAGE_LABEL = "幼儿园"
WEEKLY_AGE_GUIDANCE = (
    "本任务属于幼儿园周计划；所有活动、表述、材料和家园建议必须符合本班幼儿"
    "年龄适宜性，避免小学化、中学化、考试、作业或学科训练场景。"
)


def _weekly_context(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Program-owned minimal week context from the validated raw manifest.

    It intentionally carries no profile/class/term IDs, teacher names or other
    internal identifiers; only the kindergarten stage, class grade, term bounds
    and the current Monday-Sunday week range.
    """
    anchor = date.fromisoformat(raw["week_anchor_date"])
    grade = raw["header"]["grade"]
    return {
        "stage": WEEKLY_STAGE,
        "stage_label": WEEKLY_STAGE_LABEL,
        "grade": grade,
        "grade_label": GRADE_LABELS[grade],
        "term_start": raw["term_start"],
        "term_end": raw["term_end"],
        "week_number": raw["week_number"],
        "week_start": anchor.isoformat(),
        "week_end": (anchor + timedelta(days=6)).isoformat(),
        "age_guidance": WEEKLY_AGE_GUIDANCE,
    }

RAW_KEYS = frozenset(
    {
        "schema_version",
        "contract_version",
        "source_kind",
        "profile_id",
        "class_id",
        "term_id",
        "weekly_plan_id",
        "draft_id",
        "draft_version",
        "content_hash",
        "week_anchor_date",
        "week_number",
        "term_start",
        "term_end",
        "calendar_revision_id",
        "config_version",
        "header",
        "source_context_hash",
        "days",
        "calendar_window",
        "game_config",
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
DAY_KEYS = frozenset(
    {
        "date",
        "day_state",
        "source_state",
        "source",
        "morning_groups",
        "post_group_groups",
    }
)
SOURCE_KEYS = frozenset(
    {
        "daily_plan_id",
        "content_id",
        "content_version",
        "content_hash",
        "morning_talk_topic",
        "group_activity_theme",
        "group_activity_objectives",
        "group_activity_process",
    }
)
MORNING_GROUP_KEYS = frozenset(
    {
        "group_id",
        "group_kind",
        "games",
        "shared_objectives",
        "guidance_points",
        "focus_guidance",
    }
)
POST_GROUP_KEYS = frozenset(
    {
        "group_id",
        "context_kind",
        "area",
        "games",
        "objectives",
        "guidance",
        "support_strategy",
    }
)
GAME_KEYS = frozenset({"game_id", "name"})
CALENDAR_WINDOW_KEYS = frozenset({"start", "end", "days"})
CALENDAR_DAY_KEYS = frozenset({"date", "day_state", "holiday_names", "coverage"})
CONFIG_KEYS = frozenset(
    {"revision_id", "revision_no", "locations", "game_scope", "guidance"}
)
CONFIG_LOCATION_KEYS = frozenset({"kind", "name", "occurrence", "guidance"})

BUSINESS_DEPENDENCY_KEYS = frozenset(
    {
        "schema_version",
        "task_type",
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
_UNDERSCORE_KEYS = frozenset({"_server_manifest", "_batch_snapshot_hash"})


def _fail(
    message: str,
    field_path: str = "",
    *,
    code: str = "WEEKLY_AI_INPUT_INVALID",
    details: Mapping[str, Any] | None = None,
) -> None:
    raise contracts.WeeklyAIContractError(
        message, code=code, field_path=field_path, details=details
    )


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError):
        _fail("值不可规范序列化", "value")


def _size(value: Any) -> int:
    return len(_canonical(value).encode("utf-8"))


def _map(value: Any, path: str) -> dict:
    if not isinstance(value, Mapping):
        _fail("必须是对象", path)
    return dict(value)


def _exact(value: Mapping[str, Any], keys: frozenset[str], path: str) -> None:
    if set(value) != set(keys):
        _fail(
            "键不匹配",
            path,
            details={
                "missing_count": len(set(keys) - set(value)),
                "extra_count": len(set(value) - set(keys)),
            },
        )


def _text(
    value: Any,
    path: str,
    *,
    allow_none: bool = False,
    maximum: int = MAX_AI_TEXT_CHARS,
    nonempty: bool = False,
) -> str | None:
    if value is None:
        if allow_none:
            return None
        _fail("必须是字符串", path)
    if not isinstance(value, str):
        _fail("必须是字符串", path)
    if "\x00" in value:
        _fail("字符串不得包含 NUL", path)
    if len(value) > maximum:
        _fail("文本超限", path, details={"max": maximum})
    if nonempty and not value.strip():
        _fail("文本不能为空", path)
    return value


def _id(value: Any, path: str) -> str:
    if not isinstance(value, str) or not (1 <= len(value) <= MAX_ID_CHARS) or "\x00" in value:
        _fail("ID 不合法", path)
    return value


def _hash(value: Any, path: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(
        ch not in "0123456789abcdef" for ch in value
    ):
        _fail("必须是 64 位小写十六进制", path)
    return value


def _positive_int(value: Any, path: str) -> int:
    if type(value) is not int or value < 1:
        _fail("必须是正整数", path)
    return value


def _iso_date(value: Any, path: str) -> str:
    text = _text(value, path, nonempty=True)
    try:
        parsed = date.fromisoformat(text)
    except ValueError:
        _fail("必须是 ISO 日期", path)
    if parsed.isoformat() != text:
        _fail("日期必须规范为 YYYY-MM-DD", path)
    return text


def _header(value: Any) -> dict:
    data = _map(value, "header")
    _exact(data, HEADER_KEYS, "header")
    school = data.get("school_name")
    if school is not None:
        school = _text(school, "header.school_name", maximum=120)
        if school == "":
            school = None
    class_name = _text(data.get("class_name"), "header.class_name", maximum=80, nonempty=True)
    grade = _text(data.get("grade"), "header.grade")
    if grade not in GRADES:
        _fail("grade 非法", "header.grade")
    names_raw = data.get("header_teacher_names")
    if not isinstance(names_raw, list) or len(names_raw) > MAX_HEADER_NAMES:
        _fail("header_teacher_names 必须是有限数组", "header.header_teacher_names")
    names: list[str] = []
    for index, item in enumerate(names_raw):
        names.append(
            _text(
                item,
                f"header.header_teacher_names[{index}]",
                maximum=MAX_NAME_CHARS,
                nonempty=True,
            ).strip()
        )
    caregiver = data.get("caregiver_name")
    if caregiver is not None:
        caregiver = _text(caregiver, "header.caregiver_name", maximum=MAX_NAME_CHARS)
        if caregiver == "":
            caregiver = None
    result = {
        "school_name": school,
        "class_name": class_name,
        "grade": grade,
        "header_teacher_names": names,
        "caregiver_name": caregiver,
    }
    if _size(result) > MAX_HEADER_JSON_BYTES:
        _fail("header 超过 32KiB", "header")
    return result


def _game(value: Any, path: str) -> dict:
    data = _map(value, path)
    _exact(data, GAME_KEYS, path)
    return {
        "game_id": _id(data.get("game_id"), f"{path}.game_id"),
        "name": _text(data.get("name"), f"{path}.name", maximum=MAX_NAME_CHARS),
    }


def _games(value: Any, path: str) -> list[dict]:
    if not isinstance(value, list) or len(value) > MAX_GROUP_GAMES:
        _fail("games 必须是有限数组", path)
    return [_game(item, f"{path}[{index}]") for index, item in enumerate(value)]


def _morning_group(value: Any, path: str) -> dict:
    data = _map(value, path)
    _exact(data, MORNING_GROUP_KEYS, path)
    kind = _text(data.get("group_kind"), f"{path}.group_kind")
    if kind not in ("collective", "free_choice"):
        _fail("group_kind 非法", f"{path}.group_kind")
    return {
        "group_id": _id(data.get("group_id"), f"{path}.group_id"),
        "group_kind": kind,
        "games": _games(data.get("games"), f"{path}.games"),
        "shared_objectives": _text(
            data.get("shared_objectives"), f"{path}.shared_objectives", allow_none=True
        ),
        "guidance_points": _text(
            data.get("guidance_points"), f"{path}.guidance_points", allow_none=True
        ),
        "focus_guidance": _text(
            data.get("focus_guidance"), f"{path}.focus_guidance", allow_none=True
        ),
    }


def _post_group(value: Any, path: str) -> dict:
    data = _map(value, path)
    _exact(data, POST_GROUP_KEYS, path)
    kind = _text(data.get("context_kind"), f"{path}.context_kind")
    if kind not in CONTEXT_KINDS:
        _fail("context_kind 非法", f"{path}.context_kind")
    return {
        "group_id": _id(data.get("group_id"), f"{path}.group_id"),
        "context_kind": kind,
        "area": _text(data.get("area"), f"{path}.area", allow_none=True),
        "games": _games(data.get("games"), f"{path}.games"),
        "objectives": _text(data.get("objectives"), f"{path}.objectives", allow_none=True),
        "guidance": _text(data.get("guidance"), f"{path}.guidance", allow_none=True),
        "support_strategy": _text(
            data.get("support_strategy"), f"{path}.support_strategy", allow_none=True
        ),
    }


def _source(value: Any, path: str) -> dict:
    data = _map(value, path)
    _exact(data, SOURCE_KEYS, path)
    return {
        "daily_plan_id": _id(data.get("daily_plan_id"), f"{path}.daily_plan_id"),
        "content_id": _id(data.get("content_id"), f"{path}.content_id"),
        "content_version": _positive_int(
            data.get("content_version"), f"{path}.content_version"
        ),
        "content_hash": _hash(data.get("content_hash"), f"{path}.content_hash"),
        "morning_talk_topic": _text(
            data.get("morning_talk_topic"), f"{path}.morning_talk_topic", allow_none=True
        ),
        "group_activity_theme": _text(
            data.get("group_activity_theme"),
            f"{path}.group_activity_theme",
            allow_none=True,
        ),
        "group_activity_objectives": _text(
            data.get("group_activity_objectives"),
            f"{path}.group_activity_objectives",
            allow_none=True,
        ),
        "group_activity_process": _text(
            data.get("group_activity_process"),
            f"{path}.group_activity_process",
            allow_none=True,
        ),
    }


def _day(value: Any, path: str) -> dict:
    data = _map(value, path)
    _exact(data, DAY_KEYS, path)
    day_state = _text(data.get("day_state"), f"{path}.day_state")
    if day_state not in DAY_STATES:
        _fail("day_state 非法", f"{path}.day_state")
    source_state = _text(data.get("source_state"), f"{path}.source_state")
    if source_state not in SOURCE_STATES:
        _fail("source_state 非法", f"{path}.source_state")
    source_raw = data.get("source")
    source = _source(source_raw, f"{path}.source") if source_raw is not None else None
    if source_state == "saved":
        if source is None:
            _fail("saved 必须提供 source", f"{path}.source")
    elif source is not None:
        _fail("no_plan/none_required 的 source 必须为 null", f"{path}.source")
    if day_state == "teaching":
        if source_state not in ("saved", "no_plan"):
            _fail("teaching 的 source_state 只能是 saved/no_plan", f"{path}.source_state")
    elif source_state != "none_required":
        _fail("非教学日 source_state 必须是 none_required", f"{path}.source_state")
    mornings_raw = data.get("morning_groups")
    posts_raw = data.get("post_group_groups")
    if not isinstance(mornings_raw, list) or not isinstance(posts_raw, list):
        _fail("游戏组必须是数组", path)
    if len(mornings_raw) > MAX_DAY_GROUPS or len(posts_raw) > MAX_DAY_GROUPS:
        _fail("游戏组数量超限", path)
    if day_state != "teaching" and (mornings_raw or posts_raw):
        _fail("非教学日不得携带游戏组", path)
    return {
        "date": _iso_date(data.get("date"), f"{path}.date"),
        "day_state": day_state,
        "source_state": source_state,
        "source": source,
        "morning_groups": [
            _morning_group(item, f"{path}.morning_groups[{index}]")
            for index, item in enumerate(mornings_raw)
        ],
        "post_group_groups": [
            _post_group(item, f"{path}.post_group_groups[{index}]")
            for index, item in enumerate(posts_raw)
        ],
    }


def _calendar_window(value: Any, anchor: date) -> dict:
    data = _map(value, "calendar_window")
    _exact(data, CALENDAR_WINDOW_KEYS, "calendar_window")
    start = _iso_date(data.get("start"), "calendar_window.start")
    end = _iso_date(data.get("end"), "calendar_window.end")
    expected_start = (anchor - timedelta(days=7)).isoformat()
    expected_end = (anchor + timedelta(days=13)).isoformat()
    if start != expected_start or end != expected_end:
        _fail("calendar_window 必须是 anchor-7 至 anchor+13", "calendar_window")
    days_raw = data.get("days")
    if not isinstance(days_raw, list) or len(days_raw) != 21:
        _fail("calendar_window.days 必须恰好 21 天", "calendar_window.days")
    days: list[dict] = []
    expected_dates = [
        (anchor - timedelta(days=7) + timedelta(days=index)).isoformat()
        for index in range(21)
    ]
    for index, item in enumerate(days_raw):
        path = f"calendar_window.days[{index}]"
        row = _map(item, path)
        _exact(row, CALENDAR_DAY_KEYS, path)
        state = _text(row.get("day_state"), f"{path}.day_state")
        if state not in CALENDAR_DAY_STATES:
            _fail("calendar day_state 非法", f"{path}.day_state")
        coverage = _text(row.get("coverage"), f"{path}.coverage")
        if coverage not in ("known", "unknown"):
            _fail("calendar coverage 非法", f"{path}.coverage")
        names_raw = row.get("holiday_names")
        if not isinstance(names_raw, list) or len(names_raw) > 8:
            _fail("holiday_names 必须是有限数组", f"{path}.holiday_names")
        names: list[str] = []
        for name_index, name in enumerate(names_raw):
            text = _text(
                name,
                f"{path}.holiday_names[{name_index}]",
                maximum=MAX_NAME_CHARS,
                nonempty=True,
            )
            if text in names:
                _fail("holiday_names 重复", f"{path}.holiday_names")
            names.append(text)
        names.sort()
        days.append(
            {
                "date": _iso_date(row.get("date"), f"{path}.date"),
                "day_state": state,
                "holiday_names": names,
                "coverage": coverage,
            }
        )
    if [item["date"] for item in days] != expected_dates:
        _fail("calendar_window.days 必须连续覆盖窗口", "calendar_window.days")
    return {"start": start, "end": end, "days": days}


def _game_config(value: Any) -> dict:
    data = _map(value, "game_config")
    _exact(data, CONFIG_KEYS, "game_config")
    revision_id = _id(data.get("revision_id"), "game_config.revision_id")
    revision_no = _positive_int(data.get("revision_no"), "game_config.revision_no")
    locations_raw = data.get("locations")
    if not isinstance(locations_raw, list) or len(locations_raw) > MAX_CONFIG_LOCATIONS:
        _fail("game_config.locations 必须是有限数组", "game_config.locations")
    locations: list[dict] = []
    seen_occurrence: dict[tuple[str, str], int] = {}
    seen_triple: set[tuple[str, str, int]] = set()
    for index, item in enumerate(locations_raw):
        path = f"game_config.locations[{index}]"
        row = _map(item, path)
        _exact(row, CONFIG_LOCATION_KEYS, path)
        kind = _text(row.get("kind"), f"{path}.kind")
        if kind not in CONTEXT_KINDS:
            _fail("配置 kind 非法", f"{path}.kind")
        name = _text(row.get("name"), f"{path}.name", maximum=MAX_NAME_CHARS, nonempty=True)
        occurrence = _positive_int(row.get("occurrence"), f"{path}.occurrence")
        expected = seen_occurrence.get((kind, name), 0) + 1
        if occurrence != expected:
            _fail("配置 occurrence 必须从 1 连续编号", f"{path}.occurrence")
        seen_occurrence[(kind, name)] = occurrence
        if (kind, name, occurrence) in seen_triple:
            _fail("配置三元组重复", path)
        seen_triple.add((kind, name, occurrence))
        locations.append(
            {
                "kind": kind,
                "name": name,
                "occurrence": occurrence,
                "guidance": _text(
                    row.get("guidance"), f"{path}.guidance", allow_none=True
                ),
            }
        )
    locations.sort(key=lambda item: (item["kind"], item["name"], item["occurrence"]))
    return {
        "revision_id": revision_id,
        "revision_no": revision_no,
        "locations": locations,
        "game_scope": _text(data.get("game_scope"), "game_config.game_scope", allow_none=True),
        "guidance": _text(data.get("guidance"), "game_config.guidance", allow_none=True),
    }


def validate_raw_manifest(raw: object) -> dict:
    """Validate A's full trusted raw manifest and return a deep copy."""
    data = _map(raw, "raw_manifest")
    _exact(data, RAW_KEYS, "raw_manifest")
    if data.get("schema_version") != 1 or type(data.get("schema_version")) is not int:
        _fail("schema_version 必须严格为 1", "raw_manifest.schema_version")
    if data.get("contract_version") != 1 or type(data.get("contract_version")) is not int:
        _fail("contract_version 必须严格为 1", "raw_manifest.contract_version")
    if data.get("source_kind") != "weekly_plan":
        _fail("source_kind 必须是 weekly_plan", "raw_manifest.source_kind")
    result: dict[str, Any] = {
        "schema_version": 1,
        "contract_version": 1,
        "source_kind": "weekly_plan",
        "profile_id": _id(data.get("profile_id"), "raw_manifest.profile_id"),
        "class_id": _id(data.get("class_id"), "raw_manifest.class_id"),
        "term_id": _id(data.get("term_id"), "raw_manifest.term_id"),
        "weekly_plan_id": _id(data.get("weekly_plan_id"), "raw_manifest.weekly_plan_id"),
        "draft_id": _id(data.get("draft_id"), "raw_manifest.draft_id"),
        "draft_version": _positive_int(
            data.get("draft_version"), "raw_manifest.draft_version"
        ),
        "content_hash": _hash(data.get("content_hash"), "raw_manifest.content_hash"),
        "week_anchor_date": _iso_date(
            data.get("week_anchor_date"), "raw_manifest.week_anchor_date"
        ),
        "week_number": _positive_int(data.get("week_number"), "raw_manifest.week_number"),
        "term_start": _iso_date(data.get("term_start"), "raw_manifest.term_start"),
        "term_end": _iso_date(data.get("term_end"), "raw_manifest.term_end"),
        "calendar_revision_id": _id(
            data.get("calendar_revision_id"), "raw_manifest.calendar_revision_id"
        ),
        "config_version": _positive_int(
            data.get("config_version"), "raw_manifest.config_version"
        ),
        "header": _header(data.get("header")),
        "source_context_hash": _hash(
            data.get("source_context_hash"), "raw_manifest.source_context_hash"
        ),
    }
    anchor = date.fromisoformat(result["week_anchor_date"])
    if anchor.weekday() != 0:
        _fail("week_anchor_date 必须是周一", "raw_manifest.week_anchor_date")
    term_start = date.fromisoformat(result["term_start"])
    term_end = date.fromisoformat(result["term_end"])
    if term_start > term_end:
        _fail("term_start 不能晚于 term_end", "raw_manifest.term_start")
    days_raw = data.get("days")
    if not isinstance(days_raw, list) or len(days_raw) != 7:
        _fail("days 必须恰好 7 天", "raw_manifest.days")
    days = [_day(item, f"raw_manifest.days[{index}]") for index, item in enumerate(days_raw)]
    expected_dates = [(anchor + timedelta(days=index)).isoformat() for index in range(7)]
    if [item["date"] for item in days] != expected_dates:
        _fail("days 必须从 anchor 连续 7 天", "raw_manifest.days")
    result["days"] = days
    result["calendar_window"] = _calendar_window(data.get("calendar_window"), anchor)
    result["game_config"] = _game_config(data.get("game_config"))
    if _size(result) > MAX_MANIFEST_BYTES:
        _fail(
            "raw manifest 超过 1MiB",
            "raw_manifest",
            code="WEEKLY_CONTENT_TOO_LARGE",
        )
    return copy.deepcopy(result)


def _teacher_entered(content: Mapping[str, Any], date_text: str) -> dict:
    row = next(
        (item for item in content["deterministic"] if item["date"] == date_text), None
    )
    if row is None:
        return {"morning_talk_topic": None, "group_activity_theme": None}
    override = row.get("override") or {}
    return {
        "morning_talk_topic": override.get("morning_talk_topic"),
        "group_activity_theme": override.get("group_activity_theme"),
    }


def _basis_morning_groups(groups: Sequence[Mapping[str, Any]]) -> list[dict]:
    result = []
    for group in groups:
        result.append(
            {
                "group_id": group["group_id"],
                "group_kind": group["group_kind"],
                "games": copy.deepcopy(group["games"]),
                "shared_objectives": group.get("shared_objectives") or "",
                "guidance_points": group.get("guidance_points") or "",
                "focus_guidance": group.get("focus_guidance") or "",
            }
        )
    return result


def _basis_post_groups(groups: Sequence[Mapping[str, Any]]) -> list[dict]:
    result = []
    for group in groups:
        result.append(
            {
                "group_id": group["group_id"],
                "context_kind": group["context_kind"],
                "area": group.get("area") or "",
                "games": copy.deepcopy(group["games"]),
                "objectives": group.get("objectives") or "",
                "guidance": group.get("guidance") or "",
                "support_strategy": group.get("support_strategy") or "",
            }
        )
    return result


def _daily_basis(
    raw_day: Mapping[str, Any],
    content: Mapping[str, Any],
    *,
    source_text_fields: tuple[str, ...] = (),
    teacher_entered: bool = False,
    morning_groups: bool = False,
    post_groups: bool = False,
) -> dict:
    source = raw_day.get("source")
    values = {
        "morning_talk_topic": None,
        "group_activity_theme": None,
        "group_activity_objectives": None,
        "group_activity_process": None,
    }
    if source is not None:
        for field in source_text_fields:
            values[field] = source.get(field)
    entered = (
        _teacher_entered(content, raw_day["date"])
        if teacher_entered
        else {"morning_talk_topic": None, "group_activity_theme": None}
    )
    return {
        "date": raw_day["date"],
        "day_state": raw_day["day_state"],
        "source_state": raw_day["source_state"],
        "daily_plan_id": source["daily_plan_id"] if source else None,
        "content_id": source["content_id"] if source else None,
        "content_version": source["content_version"] if source else None,
        "content_hash": source["content_hash"] if source else None,
        "morning_talk_topic": values["morning_talk_topic"],
        "group_activity_theme": values["group_activity_theme"],
        "group_activity_objectives": values["group_activity_objectives"],
        "group_activity_process": values["group_activity_process"],
        "teacher_entered": entered,
        "morning_groups": _basis_morning_groups(raw_day["morning_groups"]) if morning_groups else [],
        "post_group_groups": _basis_post_groups(raw_day["post_group_groups"]) if post_groups else [],
    }


def _config_basis(config: Mapping[str, Any]) -> dict:
    return {
        "revision_id": config["revision_id"],
        "revision_no": config["revision_no"],
        "game_scope": config.get("game_scope"),
        "guidance": config.get("guidance"),
        "locations": copy.deepcopy(config.get("locations") or []),
    }


def _calendar_basis(window: Mapping[str, Any]) -> dict:
    return {
        "window_start": window["start"],
        "window_end": window["end"],
        "days": copy.deepcopy(window["days"]),
    }


def _check_saved_against_raw(raw: Mapping[str, Any], saved: Mapping[str, Any]) -> None:
    manifest = saved["source_manifest"]
    for raw_key, manifest_key in (
        ("profile_id", "profile_id"),
        ("class_id", "class_id"),
        ("term_id", "term_id"),
        ("week_anchor_date", "week_anchor_date"),
        ("week_number", "week_number"),
        ("term_start", "term_start"),
        ("term_end", "term_end"),
        ("calendar_revision_id", "calendar_revision_id"),
        ("header", "header"),
    ):
        if raw[raw_key] != manifest[manifest_key]:
            _fail(
                "raw manifest 与已存周稿归属不一致",
                f"raw_manifest.{raw_key}",
            )
    if raw["content_hash"] != weekly_plan_content.content_hash(saved):
        _fail("raw manifest content_hash 与 saved_content 不一致", "raw_manifest.content_hash")
    if [item["date"] for item in raw["days"]] != [
        item["date"] for item in saved["deterministic"]
    ]:
        _fail("raw manifest dates 与已存周稿不一致", "raw_manifest.days")


class _HandleAllocator:
    def __init__(self) -> None:
        self._counts: dict[str, int] = {}
        self.handles: dict[str, dict] = {}

    def add(self, kind: str, payload: Mapping[str, Any]) -> str:
        prefix = contracts.HANDLE_PREFIX[kind]
        self._counts[prefix] = self._counts.get(prefix, 0) + 1
        handle = f"{prefix}{self._counts[prefix]}"
        self.handles[handle] = {"kind": kind, **copy.deepcopy(dict(payload))}
        return handle

    def sorted_handles(self) -> dict[str, dict]:
        return {key: copy.deepcopy(self.handles[key]) for key in sorted(self.handles)}


def _morning_handle_payload(
    raw_day: Mapping[str, Any], group: Mapping[str, Any], game: Mapping[str, Any]
) -> dict:
    source = raw_day["source"]
    return {
        "date": raw_day["date"],
        "daily_plan_id": source["daily_plan_id"],
        "content_id": source["content_id"],
        "content_version": source["content_version"],
        "content_hash": source["content_hash"],
        "group_id": group["group_id"],
        "group_kind": group["group_kind"],
        "game_id": game["game_id"],
        "name": game["name"],
        "shared_objectives": group.get("shared_objectives"),
        "guidance_points": group.get("guidance_points"),
        "focus_guidance": group.get("focus_guidance"),
    }


def _post_handle_payload(
    raw_day: Mapping[str, Any], group: Mapping[str, Any], game: Mapping[str, Any]
) -> dict:
    source = raw_day["source"]
    return {
        "date": raw_day["date"],
        "daily_plan_id": source["daily_plan_id"],
        "content_id": source["content_id"],
        "content_version": source["content_version"],
        "content_hash": source["content_hash"],
        "group_id": group["group_id"],
        "context_kind": group["context_kind"],
        "area": group.get("area"),
        "game_id": game["game_id"],
        "name": game["name"],
        "objectives": group.get("objectives"),
        "guidance": group.get("guidance"),
        "support_strategy": group.get("support_strategy"),
    }


def _config_handle_payload(
    config: Mapping[str, Any], location: Mapping[str, Any]
) -> dict:
    return {
        "revision_id": config["revision_id"],
        "revision_no": config["revision_no"],
        "location_kind": location["kind"],
        "name": location["name"],
        "occurrence": location["occurrence"],
        "guidance": location.get("guidance"),
        "game_scope": config.get("game_scope"),
        "config_guidance": config.get("guidance"),
    }


def _find_raw_slot(
    raw: Mapping[str, Any], value: Mapping[str, Any]
) -> tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]:
    for raw_day in raw["days"]:
        source = raw_day["source"]
        if source is None or source["daily_plan_id"] != value.get("daily_plan_id"):
            continue
        if (
            source["content_id"] != value.get("content_id")
            or source["content_version"] != value.get("content_version")
            or source["content_hash"] != value.get("content_hash")
        ):
            continue
        if value.get("section") == "morning_games":
            for group in raw_day["morning_groups"]:
                if group["group_id"] != value.get("group_id"):
                    continue
                for game in group["games"]:
                    if game["game_id"] == value.get("game_id"):
                        return raw_day, group, game
        else:
            for group in raw_day["post_group_groups"]:
                if group["group_id"] != value.get("group_id"):
                    continue
                for game in group["games"]:
                    if game["game_id"] == value.get("game_id"):
                        return raw_day, group, game
    _fail("选中的日来源已不存在", "selected")


def _resolved_daily_value(raw: Mapping[str, Any], value: Mapping[str, Any]) -> dict:
    raw_day, group, game = _find_raw_slot(raw, value)
    source = raw_day["source"]
    if value.get("section") == "morning_games":
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
            "shared_objectives": group.get("shared_objectives") or "",
            "guidance_points": group.get("guidance_points") or "",
            "focus_guidance": group.get("focus_guidance") or "",
        }
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
        "area": group.get("area") or "",
        "name": game["name"],
        "objectives": group.get("objectives") or "",
        "guidance": group.get("guidance") or "",
        "support_strategy": group.get("support_strategy") or "",
    }


def _resolved_selected_basis(
    raw: Mapping[str, Any], content: Mapping[str, Any]
) -> dict:
    selected = weekly_materials.build_selected_basis(
        grade=raw["header"]["grade"], content=content
    )
    for item in selected["outdoor_game_slots"].values():
        if item is not None and item["value"].get("source_kind") == "daily_plan":
            item["value"] = _resolved_daily_value(raw, item["value"])
    focus = selected["focus_area"]
    if focus is not None and focus["value"].get("source_kind") == "daily_plan":
        focus["value"] = _resolved_daily_value(raw, focus["value"])
    return selected


def _selected_handles(
    raw: Mapping[str, Any], selected: Mapping[str, Any], allocator: _HandleAllocator
) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for key in weekly_plan_content.OUTDOOR_SLOT_KEYS:
        item = selected["outdoor_game_slots"].get(key)
        slot = item["value"] if item is not None else None
        if slot is None:
            continue
        kind = slot["source_kind"]
        if kind == "daily_plan":
            raw_day, group, game = _find_raw_slot(raw, slot)
            mapping[key] = allocator.add("morning_game", _morning_handle_payload(raw_day, group, game))
        elif kind == "manual":
            mapping[key] = allocator.add(
                "manual_outdoor",
                {
                    "manual_item_id": slot["manual_item_id"],
                    "slot_key": key,
                    "name": slot["name"],
                    "shared_objectives": slot.get("shared_objectives"),
                    "guidance_points": slot.get("guidance_points"),
                    "focus_guidance": slot.get("focus_guidance"),
                },
            )
        elif kind == "ai_supplement":
            mapping[key] = allocator.add(
                "ai_outdoor",
                {
                    "ai_item_id": slot["ai_item_id"],
                    "candidate_id": slot["candidate_id"],
                    "input_id": slot["input_id"],
                    "slot_key": key,
                    "name": slot["name"],
                    "shared_objectives": slot.get("shared_objectives"),
                    "guidance_points": slot.get("guidance_points"),
                    "focus_guidance": slot.get("focus_guidance"),
                },
            )
        else:
            _fail("选中户外项 source_kind 非法", f"selected.{key}")
    focus_item = selected["focus_area"]
    focus = focus_item["value"] if focus_item is not None else None
    if focus is not None:
        kind = focus["source_kind"]
        if kind == "daily_plan":
            raw_day, group, game = _find_raw_slot(raw, focus)
            mapping["focus_area"] = allocator.add("post_group_game", _post_handle_payload(raw_day, group, game))
        elif kind == "ai_supplement":
            mapping["focus_area"] = allocator.add(
                "ai_focus",
                {
                    "ai_item_id": focus["ai_item_id"],
                    "candidate_id": focus["candidate_id"],
                    "input_id": focus["input_id"],
                    "context_kind": focus["context_kind"],
                    "area": focus.get("area"),
                    "name": focus["name"],
                    "objectives": focus.get("objectives"),
                    "guidance": focus.get("guidance"),
                    "support_strategy": focus.get("support_strategy"),
                },
            )
        else:
            _fail("选中重点区域 source_kind 非法", "selected.focus_area")
    return mapping


def _config_refs_for_selected(selected: Mapping[str, Any]) -> list[dict]:
    refs: list[dict] = []
    for item in selected["outdoor_game_slots"].values():
        if item is not None and item["ai_basis"] is not None:
            refs.extend(item["ai_basis"]["config_refs"])
    if selected["focus_area"] is not None and selected["focus_area"]["ai_basis"] is not None:
        refs.extend(selected["focus_area"]["ai_basis"]["config_refs"])
    unique: dict[tuple[Any, ...], dict] = {}
    for ref in refs:
        unique[
            (
                ref["revision_id"],
                ref["revision_no"],
                ref["kind"],
                ref["name"],
                ref["occurrence"],
            )
        ] = copy.deepcopy(ref)
    return [unique[key] for key in sorted(unique, key=lambda item: (str(item[2]), str(item[3]), int(item[4])))]


def _filtered_config(
    raw: Mapping[str, Any],
    selected: Mapping[str, Any] | None = None,
    *,
    relevant_focus: bool = False,
) -> dict:
    config = raw["game_config"]
    if selected is None:
        return config
    wanted: set[tuple[Any, ...]] = set()
    for ref in _config_refs_for_selected(selected):
        wanted.add((ref["kind"], ref["name"], ref["occurrence"]))
    if relevant_focus:
        focus = selected["focus_area"]
        if focus is not None:
            value = focus["value"]
            area = value.get("area")
            if area:
                wanted.add((value["context_kind"], area, 1))
    if not wanted:
        return {**copy.deepcopy(config), "locations": []}
    locations = [
        location
        for location in config["locations"]
        if (location["kind"], location["name"], location["occurrence"]) in wanted
    ]
    return {**copy.deepcopy(config), "locations": locations}


def _selected_payload(
    selected: Mapping[str, Any], handles: Mapping[str, str]
) -> dict:
    slots: dict[str, Any] = {}
    for key in weekly_plan_content.OUTDOOR_SLOT_KEYS:
        item = selected["outdoor_game_slots"].get(key)
        slot = item["value"] if item is not None else None
        if slot is None:
            slots[key] = None
            continue
        entry = {
            "origin": slot["source_kind"],
            "name": slot["name"],
            "shared_objectives": slot.get("shared_objectives"),
            "guidance_points": slot.get("guidance_points"),
            "focus_guidance": slot.get("focus_guidance"),
        }
        if slot["source_kind"] in ("daily_plan", "manual", "ai_supplement"):
            entry["source_handle"] = handles[key]
        slots[key] = entry
    focus_item = selected["focus_area"]
    focus = focus_item["value"] if focus_item is not None else None
    if focus is None:
        focus_payload = None
    else:
        focus_payload = {
            "origin": focus["source_kind"],
            "context_kind": focus["context_kind"],
            "area": focus.get("area"),
            "name": focus["name"],
            "objectives": focus.get("objectives"),
            "guidance": focus.get("guidance"),
            "support_strategy": focus.get("support_strategy"),
        }
        if focus["source_kind"] in ("daily_plan", "ai_supplement"):
            focus_payload["source_handle"] = handles["focus_area"]
    return {"outdoor_game_slots": slots, "focus_area": focus_payload}


def _material_selected_payload(
    selected_basis: Mapping[str, Any],
    handles: Mapping[str, str],
    ref_to_handle: Mapping[tuple[str, str, int], str],
) -> dict:
    selected = _selected_payload(selected_basis, handles)

    def refs(item: Mapping[str, Any]) -> list[str]:
        ai_basis = item.get("ai_basis")
        if ai_basis is None:
            return []
        return sorted(
            {
                ref_to_handle[(ref["kind"], ref["name"], ref["occurrence"])]
                for ref in ai_basis.get("config_refs") or []
                if (ref["kind"], ref["name"], ref["occurrence"]) in ref_to_handle
            }
        )

    for key, item in selected["outdoor_game_slots"].items():
        if item is None:
            continue
        item["basis_handles"] = refs(selected_basis["outdoor_game_slots"][key])
    if selected["focus_area"] is not None:
        selected["focus_area"]["basis_handles"] = refs(selected_basis["focus_area"])
    return selected


def _config_payload(config: Mapping[str, Any], config_handles: Mapping[int, str]) -> dict:
    locations = []
    for index, location in enumerate(config.get("locations") or []):
        handle = config_handles.get(index)
        if handle is None:
            continue
        locations.append(
            {
                "source_handle": handle,
                "kind": location["kind"],
                "name": location["name"],
                "guidance": location.get("guidance"),
            }
        )
    return {
        "revision_no": config["revision_no"],
        "game_scope": config.get("game_scope"),
        "guidance": config.get("guidance"),
        "locations": locations,
    }


def _games_payload(
    raw: Mapping[str, Any],
    content: Mapping[str, Any],
    morning_handles: Mapping[tuple[str, str, str], str],
    post_handles: Mapping[tuple[str, str, str], str],
    config_handles: Mapping[int, str],
) -> dict:
    days: list[dict] = []
    for raw_day in raw["days"]:
        if raw_day["day_state"] != "teaching":
            continue
        mornings = []
        for group in raw_day["morning_groups"]:
            mornings.append(
                {
                    "group_kind": group["group_kind"],
                    "games": [
                        {
                            "source_handle": morning_handles[
                                (raw_day["date"], group["group_id"], game["game_id"])
                            ],
                            "name": game["name"],
                        }
                        for game in group["games"]
                    ],
                    "shared_objectives": group.get("shared_objectives"),
                    "guidance_points": group.get("guidance_points"),
                    "focus_guidance": group.get("focus_guidance"),
                }
            )
        posts = []
        for group in raw_day["post_group_groups"]:
            posts.append(
                {
                    "context_kind": group["context_kind"],
                    "area": group.get("area"),
                    "games": [
                        {
                            "source_handle": post_handles[
                                (raw_day["date"], group["group_id"], game["game_id"])
                            ],
                            "name": game["name"],
                        }
                        for game in group["games"]
                    ],
                    "objectives": group.get("objectives"),
                    "guidance": group.get("guidance"),
                    "support_strategy": group.get("support_strategy"),
                }
            )
        days.append(
            {
                "date": raw_day["date"],
                "morning_games": mornings,
                "post_group_games": posts,
            }
        )
    return {
        "schema_version": 1,
        "task_type": "weekly_games_select",
        "grade": raw["header"]["grade"],
        "weekly_context": _weekly_context(raw),
        "days": days,
        "config": _config_payload(raw["game_config"], config_handles),
    }


def _focus_payload(raw: Mapping[str, Any], content: Mapping[str, Any]) -> dict:
    days = []
    for raw_day in raw["days"]:
        if raw_day["day_state"] != "teaching":
            continue
        source = raw_day["source"]
        entered = _teacher_entered(content, raw_day["date"])
        if source is None and not any(entered.values()):
            continue
        days.append(
            {
                "date": raw_day["date"],
                "source": (
                    {
                        "morning_talk_topic": source.get("morning_talk_topic"),
                        "group_activity_theme": source.get("group_activity_theme"),
                        "group_activity_objectives": source.get("group_activity_objectives"),
                        "group_activity_process": source.get("group_activity_process"),
                    }
                    if source
                    else None
                ),
                "teacher_entered": entered,
            }
        )
    return {
        "schema_version": 1,
        "task_type": "weekly_key_week_focus",
        "grade": raw["header"]["grade"],
        "weekly_context": _weekly_context(raw),
        "theme": content["theme"],
        "days": days,
        "teacher_text": content["weekly_columns"]["key_week_focus"],
    }


def _environment_payload(
    raw: Mapping[str, Any],
    content: Mapping[str, Any],
    selected: Mapping[str, Any],
    handles: Mapping[str, str],
    config: Mapping[str, Any],
    config_handles: Mapping[int, str],
) -> dict:
    return {
        "schema_version": 1,
        "task_type": "weekly_environment_setup",
        "grade": raw["header"]["grade"],
        "weekly_context": _weekly_context(raw),
        "theme": content["theme"],
        "selection": _selected_payload(selected, handles),
        "config": _config_payload(config, config_handles),
        "teacher_text": content["weekly_columns"]["environment_setup"],
    }


def _habit_payload(raw: Mapping[str, Any], content: Mapping[str, Any]) -> dict:
    days = []
    for raw_day in raw["days"]:
        if raw_day["day_state"] != "teaching" or raw_day["source"] is None:
            continue
        source = raw_day["source"]
        days.append(
            {
                "date": raw_day["date"],
                "morning_talk_topic": source.get("morning_talk_topic"),
                "morning_groups": [
                    {
                        "guidance_points": group.get("guidance_points"),
                        "focus_guidance": group.get("focus_guidance"),
                    }
                    for group in raw_day["morning_groups"]
                ],
                "post_support": [
                    {"support_strategy": group.get("support_strategy")}
                    for group in raw_day["post_group_groups"]
                ],
            }
        )
    return {
        "schema_version": 1,
        "task_type": "weekly_habit_culture",
        "grade": raw["header"]["grade"],
        "weekly_context": _weekly_context(raw),
        "theme": content["theme"],
        "days": days,
        "teacher_text": content["weekly_columns"]["habit_culture"],
    }


def _holidays(window: Mapping[str, Any]) -> list[dict]:
    result: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for item in window["days"]:
        for name in item["holiday_names"]:
            key = (item["date"], name)
            if key in seen:
                continue
            seen.add(key)
            result.append({"date": item["date"], "name": name})
    result.sort(key=lambda item: (item["date"], item["name"]))
    return result


def _home_payload(
    raw: Mapping[str, Any], content: Mapping[str, Any], window: Mapping[str, Any]
) -> dict:
    group_activities = []
    teacher_entered = []
    for raw_day in raw["days"]:
        source = raw_day["source"]
        if source is not None:
            group_activities.append(
                {
                    "date": raw_day["date"],
                    "theme": source.get("group_activity_theme"),
                    "objectives": source.get("group_activity_objectives"),
                }
            )
        teacher_entered.append(
            {"date": raw_day["date"], **_teacher_entered(content, raw_day["date"])}
        )
    return {
        "schema_version": 1,
        "task_type": "weekly_home_cooperation",
        "grade": raw["header"]["grade"],
        "weekly_context": _weekly_context(raw),
        "theme": content["theme"],
        "group_activities": group_activities,
        "teacher_entered": teacher_entered,
        "calendar": {
            "window_start": window["start"],
            "window_end": window["end"],
            "holidays": _holidays(window),
        },
        "teacher_text": content["weekly_columns"]["home_cooperation"],
    }


def _materials_payload(
    raw: Mapping[str, Any],
    content: Mapping[str, Any],
    selected_basis: Mapping[str, Any],
    handles: Mapping[str, str],
    config: Mapping[str, Any],
    config_handles: Mapping[int, str],
) -> dict:
    ref_to_handle = {
        (location["kind"], location["name"], location["occurrence"]): config_handles[index]
        for index, location in enumerate(config.get("locations") or [])
        if index in config_handles
    }
    payload = {
        "schema_version": 1,
        "task_type": "weekly_materials_generate",
        "grade": raw["header"]["grade"],
        "weekly_context": _weekly_context(raw),
        "selection": _material_selected_payload(
            selected_basis, handles, ref_to_handle
        ),
        "config": _config_payload(config, config_handles),
    }
    if selected_basis.get("focus_area") is None:
        # Payload-only suggestion context; the frozen basis/provenance schema
        # is unchanged and still has no focus entry in this mode.
        payload["suggestion_context"] = {
            "mode": "suggested",
            "reason": "no_focus_area",
            "grade": raw["header"]["grade"],
            "grade_label": GRADE_LABELS[raw["header"]["grade"]],
            "theme": content["theme"],
            "has_selected_context": any(
                item is not None
                for item in (selected_basis.get("outdoor_game_slots") or {}).values()
            ),
        }
    return payload


def _habit_basis_morning_groups(groups: Sequence[Mapping[str, Any]]) -> list[dict]:
    result = []
    for group in groups:
        result.append(
            {
                "group_id": group["group_id"],
                "group_kind": group["group_kind"],
                "games": [],
                "shared_objectives": "",
                "guidance_points": group.get("guidance_points") or "",
                "focus_guidance": group.get("focus_guidance") or "",
            }
        )
    return result


def _habit_basis_post_groups(groups: Sequence[Mapping[str, Any]]) -> list[dict]:
    result = []
    for group in groups:
        result.append(
            {
                "group_id": group["group_id"],
                "context_kind": group["context_kind"],
                "area": "",
                "games": [],
                "objectives": "",
                "guidance": "",
                "support_strategy": group.get("support_strategy") or "",
            }
        )
    return result


def _daily_sources(
    raw: Mapping[str, Any],
    content: Mapping[str, Any],
    *,
    mode: str,
) -> list[dict]:
    rows: list[dict] = []
    for raw_day in raw["days"]:
        source = raw_day["source"]
        if mode == "games":
            if source is None:
                continue
            rows.append(
                _daily_basis(
                    raw_day,
                    content,
                    morning_groups=True,
                    post_groups=True,
                )
            )
        elif mode == "focus":
            entered = _teacher_entered(content, raw_day["date"])
            if source is None and not any(entered.values()):
                continue
            rows.append(
                _daily_basis(
                    raw_day,
                    content,
                    source_text_fields=(
                        "morning_talk_topic",
                        "group_activity_theme",
                        "group_activity_objectives",
                        "group_activity_process",
                    ),
                    teacher_entered=True,
                )
            )
        elif mode == "habit":
            if source is None:
                continue
            row = _daily_basis(
                raw_day,
                content,
                source_text_fields=("morning_talk_topic",),
            )
            row["morning_groups"] = _habit_basis_morning_groups(
                raw_day["morning_groups"]
            )
            row["post_group_groups"] = _habit_basis_post_groups(
                raw_day["post_group_groups"]
            )
            rows.append(row)
        elif mode == "home":
            entered = _teacher_entered(content, raw_day["date"])
            if source is None and not any(entered.values()):
                continue
            rows.append(
                _daily_basis(
                    raw_day,
                    content,
                    source_text_fields=("group_activity_theme", "group_activity_objectives"),
                    teacher_entered=True,
                )
            )
        else:
            _fail("未知日来源模式", "daily_sources")
    rows.sort(key=lambda item: item["date"])
    return rows


def _task_config(
    raw: Mapping[str, Any],
    content: Mapping[str, Any],
    selected: Mapping[str, Any] | None,
    task_type: str,
) -> list[dict]:
    if task_type == "weekly_games_select":
        return [_config_basis(raw["game_config"])]
    if task_type in ("weekly_environment_setup", "weekly_materials_generate"):
        config = _filtered_config(
            raw,
            selected,
            relevant_focus=task_type == "weekly_environment_setup",
        )
        return [_config_basis(config)]
    return []


def _dependency_view(
    task_type: str,
    target: str,
    raw: Mapping[str, Any],
    content: Mapping[str, Any],
    selected: Mapping[str, Any] | None,
    server_manifest: Mapping[str, Any],
) -> dict:
    grade = raw["header"]["grade"]
    view: dict[str, Any] = {
        "schema_version": 1,
        "task_type": task_type,
        "target": target,
        "grade": grade,
        "theme": None,
        "manual_text": None,
        "daily_sources": [],
        "selected": None,
        "config": [],
        "calendar": None,
        "_server_manifest": copy.deepcopy(server_manifest),
    }
    if task_type == "weekly_games_select":
        view["daily_sources"] = _daily_sources(raw, content, mode="games")
        view["config"] = _task_config(raw, content, None, task_type)
    elif task_type == "weekly_key_week_focus":
        view["theme"] = content["theme"]
        view["manual_text"] = content["weekly_columns"]["key_week_focus"]
        view["daily_sources"] = _daily_sources(raw, content, mode="focus")
    elif task_type == "weekly_environment_setup":
        view["theme"] = content["theme"]
        view["manual_text"] = content["weekly_columns"]["environment_setup"]
        view["selected"] = copy.deepcopy(dict(selected or {}))
        view["config"] = _task_config(raw, content, selected, task_type)
    elif task_type == "weekly_habit_culture":
        view["theme"] = content["theme"]
        view["manual_text"] = content["weekly_columns"]["habit_culture"]
        view["daily_sources"] = _daily_sources(raw, content, mode="habit")
    elif task_type == "weekly_home_cooperation":
        view["theme"] = content["theme"]
        view["manual_text"] = content["weekly_columns"]["home_cooperation"]
        view["daily_sources"] = _daily_sources(raw, content, mode="home")
        view["calendar"] = _calendar_basis(raw["calendar_window"])
    elif task_type == "weekly_materials_generate":
        view["selected"] = copy.deepcopy(dict(selected or {}))
        view["config"] = _task_config(raw, content, selected, task_type)
    else:
        _fail("不支持的周任务类型", "task_type")
    return view


def _server_manifest(
    task_type: str,
    raw: Mapping[str, Any],
    handles: Mapping[str, dict],
) -> dict:
    return contracts.validate_handle_manifest(
        {
            "schema_version": 1,
            "task_type": task_type,
            "plan": {
                "weekly_plan_id": raw["weekly_plan_id"],
                "draft_id": raw["draft_id"],
                "draft_version": raw["draft_version"],
                "content_hash": raw["content_hash"],
                "profile_id": raw["profile_id"],
                "class_id": raw["class_id"],
                "term_id": raw["term_id"],
                "week_anchor_date": raw["week_anchor_date"],
                "week_number": raw["week_number"],
            },
            "source_context_hash": raw["source_context_hash"],
            "handles": handles,
        }
    )


def _build_handles(
    task_type: str,
    raw: Mapping[str, Any],
    content: Mapping[str, Any],
    selected: Mapping[str, Any] | None,
) -> tuple[dict[str, str], dict[str, dict], dict[str, Any] | None]:
    allocator = _HandleAllocator()
    mapping: dict[str, str] = {}
    config: dict[str, Any] | None = None
    if task_type == "weekly_games_select":
        for raw_day in raw["days"]:
            if raw_day["day_state"] != "teaching":
                continue
            for group in raw_day["morning_groups"]:
                for game in group["games"]:
                    allocator.add("morning_game", _morning_handle_payload(raw_day, group, game))
            for group in raw_day["post_group_groups"]:
                for game in group["games"]:
                    allocator.add("post_group_game", _post_handle_payload(raw_day, group, game))
        config = raw["game_config"]
        for location in config["locations"]:
            allocator.add("config_location", _config_handle_payload(config, location))
    elif task_type in ("weekly_environment_setup", "weekly_materials_generate"):
        assert selected is not None
        mapping = _selected_handles(raw, selected or {}, allocator)
        config = _filtered_config(
            raw,
            selected,
            relevant_focus=task_type == "weekly_environment_setup",
        )
        for location in config["locations"]:
            allocator.add("config_location", _config_handle_payload(config, location))
    return mapping, allocator.sorted_handles(), config


@dataclass(frozen=True)
class ProjectedWeeklyInput:
    task_type: str
    target: str
    payload: dict[str, Any]
    dependencies: dict[str, Any]
    dependency_hash: str
    target_hashes: dict[str, str]
    server_manifest: dict[str, Any]

    def as_row_kwargs(self) -> dict:
        return {
            "payload_json": copy.deepcopy(self.payload),
            "dependencies_json": copy.deepcopy(self.dependencies),
            "dependency_hash": self.dependency_hash,
            "target_hashes_json": copy.deepcopy(self.target_hashes),
        }


def _comparison_view(view: Mapping[str, Any], *, drop_manual_text: bool = False) -> dict:
    data = copy.deepcopy(dict(view))
    if drop_manual_text and "manual_text" in data:
        data["manual_text"] = None
    for config in data.get("config") or []:
        config.pop("revision_id", None)
        config.pop("revision_no", None)
    selected = data.get("selected")
    if isinstance(selected, Mapping):
        items = list(selected.get("outdoor_game_slots", {}).values())
        items.append(selected.get("focus_area"))
        for item in items:
            if not isinstance(item, Mapping):
                continue
            ai_basis = item.get("ai_basis")
            if isinstance(ai_basis, Mapping):
                for ref in ai_basis.get("config_refs") or []:
                    ref.pop("revision_id", None)
                    ref.pop("revision_no", None)
    return data


def build_business_dependency_view(dependencies: Mapping[str, Any]) -> dict:
    """Return only business keys; underscore audit keys never enter hashes."""
    if not isinstance(dependencies, Mapping):
        _fail("dependencies 必须是对象", "dependencies")
    return copy.deepcopy(
        {key: value for key, value in dependencies.items() if not str(key).startswith("_")}
    )


def dependency_hash(dependencies: Mapping[str, Any]) -> str:
    view = build_business_dependency_view(dependencies)
    comparison = _comparison_view(view)
    return hashlib.sha256(_canonical(comparison).encode("utf-8")).hexdigest()


def server_manifest_from_dependencies(dependencies: Mapping[str, Any]) -> dict:
    if not isinstance(dependencies, Mapping):
        _fail("dependencies 必须是对象", "dependencies")
    manifest = dependencies.get("_server_manifest")
    if manifest is None:
        _fail("dependencies 缺少 _server_manifest", "dependencies._server_manifest")
    return contracts.validate_handle_manifest(manifest)


def target_projection(content: Mapping[str, Any], target: object) -> dict:
    fixed = weekly_plan_content.validate_content(content)
    if target not in TARGETS:
        _fail("target 非法", "target")
    if target == "games":
        value = {
            "outdoor_game_slots": copy.deepcopy(fixed["outdoor_game_slots"]),
            "focus_area": copy.deepcopy(fixed["focus_area"]),
        }
        provenance = (fixed.get("ai_provenance") or {}).get("games")
        adoption = (
            {
                "candidate_id": provenance["candidate_id"],
                "candidate_hash": provenance["candidate_hash"],
                "adopted_value_hash": provenance["adopted_value_hash"],
                "manual_edited": provenance["manual_edited"],
            }
            if provenance
            else None
        )
    elif target in contracts.COLUMN_FIELDS:
        value = {"text": fixed["weekly_columns"][target]}
        provenance = (fixed.get("ai_provenance") or {}).get(target)
        adoption = (
            {
                "candidate_id": provenance["candidate_id"],
                "candidate_hash": provenance["candidate_hash"],
                "adopted_value_hash": provenance["adopted_value_hash"],
                "manual_edited": provenance["manual_edited"],
            }
            if provenance
            else None
        )
    else:
        value = {"materials": fixed["materials"]}
        provenance = fixed.get("materials_provenance")
        adoption = (
            {
                "candidate_id": provenance["candidate_id"],
                "candidate_hash": provenance["candidate_hash"],
                "basis_hash": provenance["basis_hash"],
                "edited": provenance["edited"],
            }
            if provenance
            else None
        )
    return {
        "schema_version": 1,
        "target": target,
        "value": value,
        "adoption": adoption,
    }


def target_hash(content: Mapping[str, Any], target: object) -> str:
    return hashlib.sha256(
        _canonical(target_projection(content, target)).encode("utf-8")
    ).hexdigest()


REVISION_INSTRUCTION_MAX_CHARS = 500
REQUEST_EXTRA_KEYS = frozenset({"base_candidate", "revision_instruction"})


def minimal_candidate_value(target: str, candidate_value: Mapping[str, Any]) -> dict:
    """Original suggestion as a minimal text body, without local source ids."""
    value = dict(candidate_value)
    if target in contracts.COLUMN_FIELDS:
        text = value.get("text")
        if not isinstance(text, str):
            _fail("原候选栏目正文不可用", "base_candidate.text")
        return {"text": text}
    if target == "materials":
        items = value.get("items")
        if not isinstance(items, list):
            _fail("原候选材料项不可用", "base_candidate.items")
        result = []
        for index, item in enumerate(items):
            if not isinstance(item, Mapping):
                _fail("原候选材料项不可用", f"base_candidate.items[{index}]")
            text = item.get("text")
            origin = item.get("origin")
            if not isinstance(text, str) or not isinstance(origin, str):
                _fail("原候选材料项不可用", f"base_candidate.items[{index}]")
            result.append({"text": text, "origin": origin})
        return {"items": result}
    if target != "games":
        _fail("target 非法", "target")
    slots = value.get("outdoor_game_slots")
    if not isinstance(slots, Mapping):
        _fail("原候选游戏槽不可用", "base_candidate.outdoor_game_slots")
    minimal_slots: dict[str, Any] = {}
    for key in contracts.OUTDOOR_KEYS:
        item = slots.get(key)
        if not isinstance(item, Mapping):
            minimal_slots[key] = None
            continue
        minimal_slots[key] = {
            "name": item.get("name"),
            "shared_objectives": item.get("shared_objectives") or "",
            "guidance_points": item.get("guidance_points") or "",
            "focus_guidance": item.get("focus_guidance") or "",
        }
    focus = value.get("focus_area")
    minimal_focus = None
    if isinstance(focus, Mapping):
        minimal_focus = {
            "name": focus.get("name"),
            "objectives": focus.get("objectives") or "",
            "guidance": focus.get("guidance") or "",
            "support_strategy": focus.get("support_strategy") or "",
        }
    return {
        "outdoor_game_slots": minimal_slots,
        "focus_area": minimal_focus,
    }


def validate_base_candidate(task_type: str, value: object) -> dict:
    """Validate the minimal original suggestion by task and legal fields."""
    if task_type not in contracts.TASK_TARGETS:
        _fail("base_candidate task_type 不合法", "base_candidate.task_type")
    if not isinstance(value, Mapping):
        _fail("base_candidate 必须是对象", "base_candidate")
    data = dict(value)
    target = contracts.TASK_TARGETS[task_type]
    if target in contracts.COLUMN_FIELDS:
        if set(data) != {"text"}:
            _fail("base_candidate 栏目字段不合法", "base_candidate")
        contracts._text(
            data.get("text"),
            "base_candidate.text",
            maximum=contracts.MAX_AI_TEXT_CHARS,
            nonempty=True,
        )
        return data
    if target == "materials":
        if set(data) != {"items"}:
            _fail("base_candidate 材料字段不合法", "base_candidate")
        items = data.get("items")
        if not isinstance(items, list) or len(items) > contracts.MAX_MATERIAL_ITEMS:
            _fail("base_candidate.items 不合法", "base_candidate.items")
        total = 0
        for index, item in enumerate(items):
            path = f"base_candidate.items[{index}]"
            if not isinstance(item, Mapping) or set(item) != {"text", "origin"}:
                _fail("base_candidate 材料项字段不合法", path)
            text = contracts._text(
                item.get("text"),
                f"{path}.text",
                maximum=contracts.MAX_MATERIAL_ITEM_TEXT,
                nonempty=True,
            )
            if item.get("origin") not in ("extracted", "suggested"):
                _fail("base_candidate 材料项 origin 不合法", f"{path}.origin")
            total += len(text) + (1 if index else 0)
        if total > contracts.MAX_MATERIAL_SYNTHESIS:
            _fail("base_candidate 材料正文超限", "base_candidate.items")
        return data
    if target != "games":
        _fail("base_candidate target 不合法", "base_candidate")
    if set(data) != {"outdoor_game_slots", "focus_area"}:
        _fail("base_candidate 游戏字段不合法", "base_candidate")
    slots = data.get("outdoor_game_slots")
    if not isinstance(slots, Mapping) or set(slots) != set(contracts.OUTDOOR_KEYS):
        _fail("base_candidate 游戏槽不合法", "base_candidate.outdoor_game_slots")
    names: set[str] = set()
    for key in contracts.OUTDOOR_KEYS:
        item = slots.get(key)
        path = f"base_candidate.outdoor_game_slots.{key}"
        if item is None:
            continue
        if not isinstance(item, Mapping) or set(item) != {
            "name",
            "shared_objectives",
            "guidance_points",
            "focus_guidance",
        }:
            _fail("base_candidate 游戏槽字段不合法", path)
        name = contracts._text(
            item.get("name"),
            f"{path}.name",
            maximum=contracts.MAX_NAME_CHARS,
            nonempty=True,
        )
        if key in ("collective_1", "collective_2"):
            if name in names:
                _fail("base_candidate 集体游戏名称重复", path)
            names.add(name)
        for field in ("shared_objectives", "guidance_points", "focus_guidance"):
            contracts._text(
                item.get(field),
                f"{path}.{field}",
                maximum=contracts.MAX_AI_TEXT_CHARS,
            )
    focus = data.get("focus_area")
    if focus is not None:
        if not isinstance(focus, Mapping) or set(focus) != {
            "name",
            "objectives",
            "guidance",
            "support_strategy",
        }:
            _fail("base_candidate 重点区域字段不合法", "base_candidate.focus_area")
        contracts._text(
            focus.get("name"),
            "base_candidate.focus_area.name",
            maximum=contracts.MAX_NAME_CHARS,
            nonempty=True,
        )
        for field in ("objectives", "guidance", "support_strategy"):
            contracts._text(
                focus.get(field),
                f"base_candidate.focus_area.{field}",
                maximum=contracts.MAX_AI_TEXT_CHARS,
            )
    return data


def _normalize_request_extras(
    *,
    base_candidate: object,
    revision_instruction: object,
    task_type: str | None = None,
) -> tuple[dict | None, str | None]:
    base = dict(base_candidate) if isinstance(base_candidate, Mapping) else base_candidate
    if base is not None and not isinstance(base, dict):
        _fail("base_candidate 必须是对象", "base_candidate")
    if revision_instruction is None:
        instruction = None
    elif not isinstance(revision_instruction, str):
        _fail("revision_instruction 必须是字符串", "revision_instruction")
    else:
        instruction = revision_instruction.strip() or None
        if instruction is not None and len(instruction) > REVISION_INSTRUCTION_MAX_CHARS:
            _fail("revision_instruction 超过长度上限", "revision_instruction")
    if instruction is not None and base is None:
        _fail("定向修改要求必须绑定原候选", "revision_instruction")
    if base is not None:
        if task_type is None:
            _fail("base_candidate 缺少任务类型", "base_candidate")
        validate_base_candidate(task_type, base)
    return base, instruction


def _with_request_extras(
    payload: dict[str, Any],
    base_candidate: object,
    revision_instruction: object,
    *,
    task_type: str | None = None,
) -> dict[str, Any]:
    base, instruction = _normalize_request_extras(
        base_candidate=base_candidate,
        revision_instruction=revision_instruction,
        task_type=task_type,
    )
    result = dict(payload)
    if base is not None:
        result["base_candidate"] = copy.deepcopy(base)
    if instruction is not None:
        result["revision_instruction"] = instruction
    return result


def project_weekly_input(
    task_type: object,
    raw_manifest: Mapping[str, Any],
    saved_content: Mapping[str, Any],
    *,
    base_candidate: object = None,
    revision_instruction: object = None,
) -> ProjectedWeeklyInput:
    """Project one frozen weekly task input from A's raw manifest."""
    if task_type not in contracts.TASK_TARGETS:
        _fail("不支持的周任务类型", "task_type")
    raw = validate_raw_manifest(raw_manifest)
    saved = weekly_plan_content.validate_content(saved_content)
    _check_saved_against_raw(raw, saved)
    target = contracts.TASK_TARGETS[task_type]
    grade = raw["header"]["grade"]
    selected: dict | None = None
    if task_type in ("weekly_environment_setup", "weekly_materials_generate"):
        selected = _resolved_selected_basis(raw, saved)
    handles_mapping, handles, filtered_config = _build_handles(
        task_type, raw, saved, selected
    )
    manifest = _server_manifest(task_type, raw, handles)
    payload: dict[str, Any]
    if task_type == "weekly_games_select":
        morning_handles: dict[tuple[str, str, str], str] = {}
        post_handles: dict[tuple[str, str, str], str] = {}
        last_morning = 0
        last_post = 0
        inventory: list[tuple[str, str, str]] = []
        allocator_handles = manifest["handles"]
        cursor_m = 0
        cursor_p = 0
        for raw_day in raw["days"]:
            if raw_day["day_state"] != "teaching":
                continue
            for group in raw_day["morning_groups"]:
                for game in group["games"]:
                    cursor_m += 1
                    inventory.append(
                        ("morning", raw_day["date"], group["group_id"], game["game_id"], f"m{cursor_m}")
                    )
            for group in raw_day["post_group_groups"]:
                for game in group["games"]:
                    cursor_p += 1
                    inventory.append(
                        ("post", raw_day["date"], group["group_id"], game["game_id"], f"p{cursor_p}")
                    )
        for kind, date_text, group_id, game_id, handle in inventory:
            if kind == "morning":
                morning_handles[(date_text, group_id, game_id)] = handle
            else:
                post_handles[(date_text, group_id, game_id)] = handle
        config = filtered_config or raw["game_config"]
        config_handles = {
            index: f"c{index + 1}" for index in range(len(config.get("locations") or []))
        }
        payload = _games_payload(raw, saved, morning_handles, post_handles, config_handles)
    elif task_type == "weekly_key_week_focus":
        payload = _focus_payload(raw, saved)
    elif task_type == "weekly_environment_setup":
        config = filtered_config or {**copy.deepcopy(raw["game_config"]), "locations": []}
        config_handles = {
            index: f"c{index + 1}" for index in range(len(config.get("locations") or []))
        }
        payload = _environment_payload(
            raw, saved, selected or {}, handles_mapping, config, config_handles
        )
    elif task_type == "weekly_habit_culture":
        payload = _habit_payload(raw, saved)
    elif task_type == "weekly_home_cooperation":
        payload = _home_payload(raw, saved, raw["calendar_window"])
    else:
        config = filtered_config or {**copy.deepcopy(raw["game_config"]), "locations": []}
        config_handles = {
            index: f"c{index + 1}" for index in range(len(config.get("locations") or []))
        }
        payload = _materials_payload(
            raw,
            saved,
            selected or {},
            handles_mapping,
            config,
            config_handles,
        )
    dependencies = _dependency_view(
        task_type, target, raw, saved, selected, manifest
    )
    business = build_business_dependency_view(dependencies)
    if set(business) != set(BUSINESS_DEPENDENCY_KEYS):
        _fail("dependencies 业务键不匹配", "dependencies")
    payload = _with_request_extras(
        payload, base_candidate, revision_instruction, task_type=task_type
    )
    if _size(payload) > MAX_PAYLOAD_BYTES:
        _fail("模型 payload 超过 1MiB", "payload", code="WEEKLY_CONTENT_TOO_LARGE")
    if _size(dependencies) > MAX_DEPENDENCIES_BYTES:
        _fail(
            "dependencies 超过 2MiB",
            "dependencies",
            code="WEEKLY_CONTENT_TOO_LARGE",
        )
    return ProjectedWeeklyInput(
        task_type=task_type,
        target=target,
        payload=copy.deepcopy(payload),
        dependencies=copy.deepcopy(dependencies),
        dependency_hash=dependency_hash(dependencies),
        target_hashes={target: target_hash(saved, target)},
        server_manifest=copy.deepcopy(manifest),
    )


def _current_dependencies(
    task_type: str, raw: Mapping[str, Any], content: Mapping[str, Any]
) -> dict:
    projection = project_weekly_input(task_type, raw, content)
    return build_business_dependency_view(projection.dependencies)


_BASIS_COMPARE_KEYS = (
    "schema_version",
    "target",
    "grade",
    "theme",
    "manual_text",
    "daily_sources",
    "selected",
    "config",
    "calendar",
)


def _basis_view(view: Mapping[str, Any]) -> dict:
    return {key: copy.deepcopy(view.get(key)) for key in _BASIS_COMPARE_KEYS}


def build_ai_facts(
    content: Mapping[str, Any], raw_manifest: Mapping[str, Any]
) -> dict:
    """Derive source staleness without treating the adopted target as source."""
    fixed = weekly_plan_content.validate_content(content)
    if fixed["schema_version"] == weekly_plan_content.SCHEMA1_VERSION:
        return {"missing": [], "stale_sources": [], "warnings": []}
    raw = validate_raw_manifest(raw_manifest)
    if raw["content_hash"] != weekly_plan_content.content_hash(fixed):
        _fail("raw manifest content_hash 与 content 不一致", "raw_manifest.content_hash")
    missing: list[dict] = []
    stale: list[dict] = []
    warnings: list[dict] = []

    def fact(
        bucket: list[dict],
        code: str,
        field_path: str,
        *,
        old_ref: Any = None,
        new_ref: Any = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        bucket.append(
            {
                "code": code,
                "field_path": field_path,
                "old_ref": copy.deepcopy(old_ref),
                "new_ref": copy.deepcopy(new_ref),
                "details": dict(details or {}),
            }
        )

    def mark_target_stale(target: str, reason: str) -> None:
        if target == "games":
            for key in weekly_plan_content.OUTDOOR_SLOT_KEYS:
                slot = fixed["outdoor_game_slots"].get(key)
                if slot is not None and slot.get("source_kind") == "ai_supplement":
                    fact(
                        stale,
                        "stale_source",
                        f"outdoor_game_slots.{key}",
                        details={"reason": reason},
                    )
            focus = fixed["focus_area"]
            if focus is not None and focus.get("source_kind") == "ai_supplement":
                fact(
                    stale,
                    "stale_source",
                    "focus_area",
                    details={"reason": reason},
                )
        elif target in contracts.COLUMN_FIELDS:
            fact(
                stale,
                "stale_source",
                f"weekly_columns.{target}",
                details={"reason": reason},
            )

    provenance = fixed.get("ai_provenance") or {}
    for target, adoption in provenance.items():
        if adoption is None:
            continue
        if adoption.get("contract_version") != 1:
            fact(
                warnings,
                "ai_contract_obsolete",
                f"ai_provenance.{target}",
                details={"contract_version": adoption.get("contract_version")},
            )
            continue
        task_type = (
            contracts.COLUMN_TASK[target] if target in contracts.COLUMN_FIELDS else "weekly_games_select"
        )
        basis = adoption.get("basis") or {}
        try:
            current = _current_dependencies(task_type, raw, fixed)
        except contracts.WeeklyAIContractError:
            mark_target_stale(target, "ai_basis_unresolved")
            continue
        if _canonical(_comparison_view(_basis_view(basis), drop_manual_text=True)) == _canonical(
            _comparison_view(_basis_view(current), drop_manual_text=True)
        ):
            continue
        mark_target_stale(target, "ai_basis_changed")
    materials = fixed.get("materials_provenance")
    if materials is not None:
        current: dict | None
        try:
            current = _current_dependencies(
                "weekly_materials_generate", raw, fixed
            )
        except contracts.WeeklyAIContractError as exc:
            if exc.code == "MATERIAL_CONTEXT_REQUIRED":
                fact(missing, "materials_context_missing", "materials_provenance.basis")
            else:
                fact(
                    stale,
                    "stale_source",
                    "materials_provenance.basis",
                    details={"reason": "materials_basis_unresolved"},
                )
            current = None
        if current is not None and _canonical(
            _comparison_view(_basis_view(materials["basis"]), drop_manual_text=True)
        ) != _canonical(
            _comparison_view(_basis_view(current), drop_manual_text=True)
        ):
            fact(
                stale,
                "stale_source",
                "materials_provenance.basis",
                details={"reason": "materials_basis_changed"},
            )
    return {"missing": missing, "stale_sources": stale, "warnings": warnings}


def _stored_fail(message: str, field_path: str) -> None:
    _fail(message, field_path, code="WEEKLY_AI_INPUT_INVALID")


def _stored_same_text(left: Any, right: Any) -> bool:
    return ("" if left is None else left) == ("" if right is None else right)


def _stored_plan(
    manifest: Mapping[str, Any], plan_identity: object
) -> dict:
    if not isinstance(plan_identity, Mapping):
        _stored_fail("存储输入 plan 不合法", "plan_identity")
    candidate = dict(manifest)
    candidate["plan"] = dict(plan_identity)
    try:
        validated = contracts.validate_handle_manifest(candidate)
    except contracts.WeeklyAIContractError:
        _stored_fail("存储输入 plan 不合法", "plan_identity")
    plan = validated["plan"]
    if plan != dict(plan_identity) or manifest["plan"] != plan:
        _stored_fail("存储输入 manifest plan 不一致", "plan_identity")
    return plan


def _stored_config_from_basis(
    config_list: object, frozen: Mapping[str, Any]
) -> dict:
    if not isinstance(config_list, list):
        _stored_fail("存储输入 config 不合法", "dependencies.config")
    if len(config_list) > 1:
        _stored_fail("存储输入 config 修订不唯一", "dependencies.config")
    if not config_list:
        game_context = frozen["source_manifest"].get("game_context") or {}
        return {
            "revision_id": game_context.get("revision_id") or "0" * 32,
            "revision_no": game_context.get("revision_no") or 1,
            "locations": [],
            "game_scope": None,
            "guidance": None,
        }
    entry = dict(config_list[0])
    return {
        "revision_id": entry["revision_id"],
        "revision_no": entry["revision_no"],
        "locations": copy.deepcopy(entry["locations"]),
        "game_scope": entry.get("game_scope"),
        "guidance": entry.get("guidance"),
    }


def _stored_raw_source(item: Mapping[str, Any]) -> dict | None:
    if item.get("daily_plan_id") is None:
        return None
    return {
        "daily_plan_id": item["daily_plan_id"],
        "content_id": item["content_id"],
        "content_version": item["content_version"],
        "content_hash": item["content_hash"],
        "morning_talk_topic": item.get("morning_talk_topic"),
        "group_activity_theme": item.get("group_activity_theme"),
        "group_activity_objectives": item.get("group_activity_objectives"),
        "group_activity_process": item.get("group_activity_process"),
    }


def _stored_raw_like(
    business: Mapping[str, Any], frozen: Mapping[str, Any]
) -> dict:
    by_date: dict[str, dict] = {}
    for row in frozen["deterministic"]:
        source = row.get("source")
        by_date[row["date"]] = {
            "date": row["date"],
            "day_state": row["day_state"],
            "source_state": row["source_state"],
            "source": (
                {
                    "daily_plan_id": source["daily_plan_id"],
                    "content_id": source["content_id"],
                    "content_version": source["content_version"],
                    "content_hash": source["content_hash"],
                    "morning_talk_topic": source.get("morning_talk_topic"),
                    "group_activity_theme": source.get("group_activity_theme"),
                    "group_activity_objectives": None,
                    "group_activity_process": None,
                }
                if source
                else None
            ),
            "morning_groups": [],
            "post_group_groups": [],
        }
    for item in business["daily_sources"]:
        day = by_date.get(item["date"])
        if day is None:
            _stored_fail("存储输入日来源不在冻结稿中", "dependencies.daily_sources")
        day["day_state"] = item["day_state"]
        day["source_state"] = item["source_state"]
        day["source"] = _stored_raw_source(item)
        day["morning_groups"] = copy.deepcopy(item["morning_groups"])
        day["post_group_groups"] = copy.deepcopy(item["post_group_groups"])
    calendar = business.get("calendar")
    if calendar is None:
        calendar_window = {"start": "", "end": "", "days": []}
    else:
        calendar_window = {
            "start": calendar["window_start"],
            "end": calendar["window_end"],
            "days": copy.deepcopy(calendar["days"]),
        }
    source_manifest = frozen["source_manifest"]
    return {
        "header": {"grade": source_manifest["header"]["grade"]},
        "week_anchor_date": source_manifest["week_anchor_date"],
        "week_number": source_manifest["week_number"],
        "term_start": source_manifest["term_start"],
        "term_end": source_manifest["term_end"],
        "days": [by_date[key] for key in sorted(by_date)],
        "game_config": _stored_config_from_basis(business.get("config"), frozen),
        "calendar_window": calendar_window,
    }


def _stored_handle_for_value(
    manifest: Mapping[str, Any],
    value: Mapping[str, Any],
    slot_key: str | None,
) -> str:
    matches = [
        handle
        for handle, source in manifest["handles"].items()
        if weekly_plan_content._matches_selected_source(source, value, slot_key)
    ]
    if len(matches) != 1:
        _stored_fail("存储输入 handle 与依据不唯一", "dependencies")
    return matches[0]


def _stored_config_handles(
    manifest: Mapping[str, Any],
    config_list: object,
    used: set[str],
) -> dict[int, str]:
    if not isinstance(config_list, list) or len(config_list) > 1:
        _stored_fail("存储输入 config 不合法", "dependencies.config")
    if not config_list:
        return {}
    entry = dict(config_list[0])
    result: dict[int, str] = {}
    for index, location in enumerate(entry["locations"]):
        matches = []
        for handle, source in manifest["handles"].items():
            if source["kind"] != "config_location":
                continue
            if (
                source["revision_id"] == entry["revision_id"]
                and source["revision_no"] == entry["revision_no"]
                and source["location_kind"] == location["kind"]
                and source["name"] == location["name"]
                and source["occurrence"] == location["occurrence"]
                and _stored_same_text(source.get("guidance"), location.get("guidance"))
                and _stored_same_text(source.get("game_scope"), entry.get("game_scope"))
                and _stored_same_text(
                    source.get("config_guidance"), entry.get("guidance")
                )
            ):
                matches.append(handle)
        if len(matches) != 1:
            _stored_fail("存储输入 config handle 不唯一", "dependencies.config")
        result[index] = matches[0]
        used.add(matches[0])
    return result


def _stored_game_value(
    item: Mapping[str, Any],
    group: Mapping[str, Any],
    game: Mapping[str, Any],
    *,
    focus: bool,
) -> dict:
    base = {
        "source_kind": "daily_plan",
        "manual_item_id": None,
        "daily_plan_id": item["daily_plan_id"],
        "content_id": item["content_id"],
        "content_version": item["content_version"],
        "content_hash": item["content_hash"],
    }
    if focus:
        return {
            **base,
            "section": "post_group_games",
            "group_id": group["group_id"],
            "game_id": game["game_id"],
            "context_kind": group["context_kind"],
            "area": group.get("area"),
            "name": game["name"],
            "objectives": group.get("objectives"),
            "guidance": group.get("guidance"),
            "support_strategy": group.get("support_strategy"),
        }
    return {
        **base,
        "section": "morning_games",
        "group_id": group["group_id"],
        "game_id": game["game_id"],
        "name": game["name"],
        "shared_objectives": group.get("shared_objectives"),
        "guidance_points": group.get("guidance_points"),
        "focus_guidance": group.get("focus_guidance"),
    }


def _stored_game_handles(
    manifest: Mapping[str, Any], business: Mapping[str, Any]
) -> tuple[dict[tuple[str, str, str], str], dict[tuple[str, str, str], str], dict[int, str]]:
    used: set[str] = set()
    morning: dict[tuple[str, str, str], str] = {}
    post: dict[tuple[str, str, str], str] = {}
    for item in business["daily_sources"]:
        for group in item["morning_groups"]:
            slot_key = (
                "collective_1"
                if group["group_kind"] == "collective"
                else "free_choice_1"
            )
            for game in group["games"]:
                key = (item["date"], group["group_id"], game["game_id"])
                if key in morning:
                    _stored_fail("存储输入日游戏重复", "dependencies.daily_sources")
                handle = _stored_handle_for_value(
                    manifest,
                    _stored_game_value(item, group, game, focus=False),
                    slot_key,
                )
                morning[key] = handle
                used.add(handle)
        for group in item["post_group_groups"]:
            for game in group["games"]:
                key = (item["date"], group["group_id"], game["game_id"])
                if key in post:
                    _stored_fail("存储输入日游戏重复", "dependencies.daily_sources")
                handle = _stored_handle_for_value(
                    manifest,
                    _stored_game_value(item, group, game, focus=True),
                    None,
                )
                post[key] = handle
                used.add(handle)
    config = _stored_config_handles(manifest, business.get("config"), used)
    if used != set(manifest["handles"]):
        _stored_fail("存储输入存在未使用或缺失 handle", "dependencies")
    return morning, post, config


def _stored_selected_handles(
    manifest: Mapping[str, Any], business: Mapping[str, Any]
) -> tuple[dict[str, str], dict[int, str]]:
    used: set[str] = set()
    selected = business["selected"]
    mapping: dict[str, str] = {}
    for key in weekly_plan_content.OUTDOOR_SLOT_KEYS:
        item = selected["outdoor_game_slots"].get(key)
        if item is None:
            continue
        handle = _stored_handle_for_value(manifest, item["value"], key)
        mapping[key] = handle
        used.add(handle)
    focus = selected.get("focus_area")
    if focus is not None:
        handle = _stored_handle_for_value(manifest, focus["value"], None)
        mapping["focus_area"] = handle
        used.add(handle)
    config = _stored_config_handles(manifest, business.get("config"), used)
    if used != set(manifest["handles"]):
        _stored_fail("存储输入存在未使用或缺失 handle", "dependencies")
    return mapping, config


def _stored_payload_compare(
    *,
    task_type: str,
    payload: object,
    expected: Mapping[str, Any],
) -> dict:
    if not isinstance(payload, Mapping):
        _stored_fail("存储输入 payload 不合法", "payload")
    actual = dict(payload)
    if _size(actual) > MAX_PAYLOAD_BYTES:
        _stored_fail("存储输入 payload 超限", "payload")
    expected_copy = copy.deepcopy(dict(expected))
    if "weekly_context" not in actual:
        # Backward compatibility: inputs persisted before the program-owned
        # week context was introduced have no weekly_context key.  They must
        # still validate against the exact legacy payload, and the stored
        # shape is returned unchanged so receipt/candidate chain comparisons
        # remain identical.  A present context is always checked exactly.
        legacy_expected = copy.deepcopy(expected_copy)
        legacy_expected.pop("weekly_context", None)
        if _canonical(actual) != _canonical(legacy_expected):
            _stored_fail("存储输入 payload 与投影不一致", "payload")
        return copy.deepcopy(actual)
    if _canonical(actual) != _canonical(expected_copy):
        _stored_fail("存储输入 payload 与投影不一致", "payload")
    return expected_copy


def _validate_stored_weekly_input_impl(
    task_type: object,
    payload: object,
    dependencies: Mapping[str, Any],
    frozen_content: Mapping[str, Any],
    plan_identity: object,
) -> ProjectedWeeklyInput:
    if task_type not in contracts.TASK_TARGETS:
        _stored_fail("存储输入 task_type 不合法", "task_type")
    if not isinstance(dependencies, Mapping):
        _stored_fail("存储输入 dependencies 不合法", "dependencies")
    deps = dict(dependencies)
    if _size(deps) > MAX_DEPENDENCIES_BYTES:
        _stored_fail("存储输入 dependencies 超限", "dependencies")
    allowed = set(BUSINESS_DEPENDENCY_KEYS) | {
        "_server_manifest",
        "_batch_snapshot_hash",
    }
    if not set(BUSINESS_DEPENDENCY_KEYS).issubset(deps) or set(deps) - allowed:
        _stored_fail("存储输入 dependencies 键不合法", "dependencies")
    if "_server_manifest" not in deps:
        _stored_fail("存储输入缺少 server manifest", "dependencies._server_manifest")
    if "_batch_snapshot_hash" in deps:
        _hash(deps["_batch_snapshot_hash"], "dependencies._batch_snapshot_hash")
    try:
        manifest = contracts.validate_handle_manifest(deps["_server_manifest"])
    except contracts.WeeklyAIContractError:
        _stored_fail("存储输入 server manifest 不合法", "dependencies._server_manifest")
    if manifest["task_type"] != task_type:
        _stored_fail("存储输入 manifest task_type 不一致", "dependencies._server_manifest.task_type")
    plan = _stored_plan(manifest, plan_identity)
    frozen = weekly_plan_content.validate_content(frozen_content)
    source_manifest = frozen["source_manifest"]
    if plan["content_hash"] != weekly_plan_content.content_hash(frozen):
        _stored_fail("存储输入 plan content_hash 不一致", "plan_identity.content_hash")
    for key in ("profile_id", "class_id", "term_id", "week_anchor_date", "week_number"):
        if plan[key] != source_manifest[key]:
            _stored_fail("存储输入 plan 与冻结稿归属不一致", f"plan_identity.{key}")
    business = build_business_dependency_view(deps)
    if set(business) != set(BUSINESS_DEPENDENCY_KEYS):
        _stored_fail("存储输入业务依赖键不合法", "dependencies")
    target = contracts.target_for_task(task_type)
    if business.get("task_type") != task_type or business.get("target") != target:
        _stored_fail("存储输入 task/target 不一致", "dependencies")
    grade = source_manifest["header"]["grade"]
    if business.get("grade") != grade:
        _stored_fail("存储输入 grade 不一致", "dependencies.grade")
    basis_input = {
        key: business[key] for key in weekly_plan_content.BASIS_KEYS
    }
    try:
        normalized_basis = weekly_plan_content._normalize_basis(
            basis_input, "dependencies", expected_target=target, grade=grade
        )
    except weekly_plan_content.WeeklyContentError:
        _stored_fail("存储输入 basis 不合法", "dependencies")
    if _canonical(normalized_basis) != _canonical(basis_input):
        _stored_fail("存储输入 basis 被静默规范化", "dependencies")
    business = {**business, **normalized_basis}
    expected_config_count = (
        1
        if task_type
        in (
            "weekly_games_select",
            "weekly_environment_setup",
            "weekly_materials_generate",
        )
        else 0
    )
    if len(business["config"]) != expected_config_count:
        _stored_fail("存储输入 config basis 数量不一致", "dependencies.config")
    if task_type in ("weekly_environment_setup", "weekly_materials_generate"):
        expected_selected = weekly_materials.build_selected_basis(
            grade=grade, content=frozen
        )
        if _canonical(expected_selected) != _canonical(business["selected"]):
            _stored_fail("存储输入 selected 与冻结稿不一致", "dependencies.selected")
        selected = business["selected"]
    else:
        selected = None
    raw_like = _stored_raw_like(business, frozen)
    if task_type == "weekly_games_select":
        morning, post, config_handles = _stored_game_handles(manifest, business)
        expected_payload = _games_payload(
            raw_like, frozen, morning, post, config_handles
        )
        expected_dependencies = _dependency_view(
            task_type, target, raw_like, frozen, None, manifest
        )
    elif task_type == "weekly_key_week_focus":
        if manifest["handles"]:
            _stored_fail("存储输入存在未使用 handle", "dependencies._server_manifest.handles")
        expected_payload = _focus_payload(raw_like, frozen)
        expected_dependencies = _dependency_view(
            task_type, target, raw_like, frozen, None, manifest
        )
    elif task_type == "weekly_environment_setup":
        selected_map, config_handles = _stored_selected_handles(manifest, business)
        config = raw_like["game_config"]
        expected_payload = _environment_payload(
            raw_like, frozen, selected, selected_map, config, config_handles
        )
        expected_dependencies = _dependency_view(
            task_type, target, raw_like, frozen, selected, manifest
        )
    elif task_type == "weekly_habit_culture":
        if manifest["handles"]:
            _stored_fail("存储输入存在未使用 handle", "dependencies._server_manifest.handles")
        expected_payload = _habit_payload(raw_like, frozen)
        expected_dependencies = _dependency_view(
            task_type, target, raw_like, frozen, None, manifest
        )
    elif task_type == "weekly_home_cooperation":
        if manifest["handles"]:
            _stored_fail("存储输入存在未使用 handle", "dependencies._server_manifest.handles")
        expected_payload = _home_payload(
            raw_like, frozen, raw_like["calendar_window"]
        )
        expected_dependencies = _dependency_view(
            task_type, target, raw_like, frozen, None, manifest
        )
    else:
        selected_map, config_handles = _stored_selected_handles(manifest, business)
        config = raw_like["game_config"]
        expected_payload = _materials_payload(
            raw_like, frozen, selected, selected_map, config, config_handles
        )
        expected_dependencies = _dependency_view(
            task_type, target, raw_like, frozen, selected, manifest
        )
    expected_dependencies["_server_manifest"] = copy.deepcopy(manifest)
    if "_batch_snapshot_hash" in deps:
        expected_dependencies["_batch_snapshot_hash"] = copy.deepcopy(
            deps["_batch_snapshot_hash"]
        )
    expected_business = build_business_dependency_view(expected_dependencies)
    if _canonical(expected_business) != _canonical(business):
        _stored_fail("存储输入 dependencies 与投影不一致", "dependencies")
    stored_extras = {
        key: dict(payload).get(key)
        for key in REQUEST_EXTRA_KEYS
        if isinstance(payload, Mapping) and key in payload
    }
    expected_payload = _with_request_extras(
        expected_payload,
        stored_extras.get("base_candidate"),
        stored_extras.get("revision_instruction"),
        task_type=task_type,
    )
    expected_payload = _stored_payload_compare(
        task_type=task_type,
        payload=payload,
        expected=expected_payload,
    )
    expected_manifest = {
        **copy.deepcopy(manifest),
        "plan": copy.deepcopy(plan),
        "handles": {
            key: copy.deepcopy(manifest["handles"][key])
            for key in sorted(manifest["handles"])
        },
    }
    if _canonical(expected_manifest) != _canonical(manifest):
        _stored_fail("存储输入 manifest 与依据不一致", "dependencies._server_manifest")
    return ProjectedWeeklyInput(
        task_type=task_type,
        target=target,
        payload=copy.deepcopy(expected_payload),
        dependencies=copy.deepcopy(expected_dependencies),
        dependency_hash=dependency_hash(expected_dependencies),
        target_hashes={target: target_hash(frozen, target)},
        server_manifest=copy.deepcopy(manifest),
    )


def validate_stored_weekly_input(
    task_type: object,
    payload: object,
    dependencies: Mapping[str, Any],
    frozen_content: Mapping[str, Any],
    *,
    plan_identity: Mapping[str, Any],
) -> ProjectedWeeklyInput:
    """Validate one persisted weekly AI input against its frozen projection."""
    try:
        return _validate_stored_weekly_input_impl(
            task_type,
            payload,
            dependencies,
            frozen_content,
            plan_identity,
        )
    except contracts.WeeklyAIContractError:
        raise
    except weekly_plan_content.WeeklyContentError:
        raise contracts.WeeklyAIContractError(
            "存储输入不合法",
            code="WEEKLY_AI_INPUT_INVALID",
            field_path="dependencies",
            details={"reason": "stored_input_invalid"},
        ) from None
    except (TypeError, ValueError, KeyError):
        raise contracts.WeeklyAIContractError(
            "存储输入不合法",
            code="WEEKLY_AI_INPUT_INVALID",
            field_path="dependencies",
            details={"reason": "stored_input_invalid"},
        ) from None


__all__ = [
    "CONTRACT_VERSION",
    "AI_INPUT_SCHEMA_VERSION",
    "TARGETS",
    "TASK_TARGETS",
    "ProjectedWeeklyInput",
    "validate_raw_manifest",
    "project_weekly_input",
    "validate_stored_weekly_input",
    "build_business_dependency_view",
    "dependency_hash",
    "server_manifest_from_dependencies",
    "target_projection",
    "target_hash",
    "build_ai_facts",
]
