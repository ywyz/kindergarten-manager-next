"""Strict ConfirmationSnapshotV1 schema shared by service, backup and D.

§11.6 freezes one exact shape; this module is the single validator/hash
implementation.  It is not a second content authority: ``content`` is the
exact saved draft and B's ``validate_content`` remains the content validator.
"""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import date, datetime, timedelta
from typing import Any

from app.local.errors import LocalWeeklyInvalid

SNAPSHOT_KEYS = frozenset(
    {
        "schema_version",
        "weekly_plan_id",
        "profile_id",
        "class_id",
        "term_id",
        "draft_id",
        "draft_version",
        "content_hash",
        "header",
        "creation_context",
        "content",
        "date_range",
        "columns",
        "facts",
    }
)
SNAPSHOT_OPTIONAL_KEYS = frozenset(
    {"term_name", "reissued_from_confirmation_id"}
)
SNAPSHOT_ALL_KEYS = SNAPSHOT_KEYS | SNAPSHOT_OPTIONAL_KEYS
CREATION_CONTEXT_KEYS = frozenset(
    {
        "week_anchor_date",
        "week_number_snapshot",
        "term_start",
        "term_end",
        "calendar_revision_id",
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
DATE_RANGE_KEYS = frozenset({"start", "end"})
COLUMN_KEYS = frozenset({"date", "day_state"})
FACTS_KEYS = frozenset({"missing", "stale_sources", "warnings"})
DAY_STATES = ("teaching", "rest", "outside_term")
EXPORT_MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "profile_id",
        "mode",
        "requested_range",
        "selection",
        "warnings_as_of",
        "missing",
        "warnings",
        "items",
    }
)
EXPORT_SELECTION_KEYS = frozenset(
    {
        "weekly_plan_id",
        "confirmation_id",
        "confirmation_version",
        "draft_id",
        "draft_version",
        "content_hash",
        "confirmation_hash",
        "week_anchor_date",
        "week_number",
        "date_range",
    }
)
EXPORT_ITEM_KEYS = SNAPSHOT_KEYS | {
    "confirmation_id",
    "confirmation_version",
    "confirmation_hash",
}
EXPORT_ITEM_OPTIONAL_KEYS = SNAPSHOT_OPTIONAL_KEYS


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def snapshot_hash(snapshot: dict) -> str:
    return hashlib.sha256(canonical_json(snapshot).encode("utf-8")).hexdigest()


def _fail(message: str) -> None:
    raise LocalWeeklyInvalid(message)


def _iso_date(value: Any, label: str) -> date:
    if not isinstance(value, str):
        _fail(f"{label} 必须是 ISO 日期")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        _fail(f"{label} 必须是 ISO 日期")
    if parsed.isoformat() != value:
        _fail(f"{label} 必须是规范 ISO 日期")
    return parsed


def _positive_int(value: Any, label: str) -> int:
    if type(value) is not int or value < 1:
        _fail(f"{label} 必须是正整数")
    return value


def _exact_one(value: Any, label: str) -> int:
    if type(value) is not int or value != 1:
        _fail(f"{label} 必须严格为整数 1")
    return value


def _id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not (1 <= len(value) <= 32):
        _fail(f"{label} 不合法")
    return value


def _hash(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        _fail(f"{label} 必须是 64 位十六进制")
    return value


def _term_name(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not (1 <= len(value) <= 80)
        or value != value.strip()
        or "\x00" in value
    ):
        _fail("确认快照 term_name 不合法")
    return value


def validate_header(header: Any) -> dict:
    if not isinstance(header, dict) or set(header) != HEADER_KEYS:
        _fail("确认快照 header 字段不完整")
    names = header.get("header_teacher_names")
    if not isinstance(names, list) or len(names) > 100:
        _fail("确认快照教师名单不合法")
    normalized: list[str] = []
    for item in names:
        if not isinstance(item, str):
            _fail("确认快照教师名单不合法")
        name = item.strip()
        if not (1 <= len(name) <= 80) or "\x00" in name:
            _fail("确认快照教师名单不合法")
        normalized.append(name)
    if len(canonical_json(normalized).encode("utf-8")) > 32 * 1024:
        _fail("确认快照教师名单超过 32KiB")
    caregiver = header.get("caregiver_name")
    if caregiver is not None:
        if not isinstance(caregiver, str):
            _fail("确认快照保育员姓名不合法")
        caregiver = caregiver.strip() or None
        if caregiver is not None and (
            len(caregiver) > 80 or "\x00" in caregiver
        ):
            _fail("确认快照保育员姓名不合法")
    class_name = header.get("class_name")
    if not isinstance(class_name, str) or not (1 <= len(class_name) <= 80):
        _fail("确认快照班级名称不合法")
    school_name = header.get("school_name")
    if school_name is not None and (
        not isinstance(school_name, str) or not (1 <= len(school_name) <= 120)
    ):
        _fail("确认快照园所名称不合法")
    grade = header.get("grade")
    if grade not in ("small", "middle", "large"):
        _fail("确认快照年级不合法")
    return {
        "school_name": school_name,
        "class_name": class_name,
        "grade": grade,
        "header_teacher_names": normalized,
        "caregiver_name": caregiver,
    }


def _basis_days(content: dict) -> dict[str, str]:
    basis = content.get("calendar_basis")
    if not isinstance(basis, dict):
        _fail("确认快照 content 缺少 calendar_basis")
    days = basis.get("days")
    if not isinstance(days, list) or len(days) != 7:
        _fail("确认快照 calendar_basis.days 必须为 7 天")
    result: dict[str, str] = {}
    for item in days:
        if not isinstance(item, dict) or set(item) != {"date", "day_state"}:
            _fail("确认快照 calendar_basis 日期项不合法")
        day = _iso_date(item.get("date"), "calendar_basis.date")
        state = item.get("day_state")
        if state not in DAY_STATES:
            _fail("确认快照 calendar_basis.day_state 不合法")
        result[day.isoformat()] = state
    return result


def date_range_for(
    content: dict,
    *,
    creation_term_start: str,
    creation_term_end: str,
) -> dict:
    """Teaching-day span, or creation-term ∩ fixed week when none teach."""
    basis = content["calendar_basis"]
    anchor = _iso_date(basis.get("week_anchor_date"), "calendar_basis.week_anchor_date")
    states = _basis_days(content)
    teaching = [
        date.fromisoformat(day)
        for day, state in states.items()
        if state == "teaching"
    ]
    if teaching:
        return {
            "start": min(teaching).isoformat(),
            "end": max(teaching).isoformat(),
        }
    basis_start = _iso_date(
        basis.get("term_start"), "calendar_basis.term_start"
    )
    basis_end = _iso_date(basis.get("term_end"), "calendar_basis.term_end")
    start = max(anchor, basis_start)
    end = min(anchor + timedelta(days=6), basis_end)
    if start > end:
        creation_start = _iso_date(
            creation_term_start, "creation_context.term_start"
        )
        creation_end = _iso_date(
            creation_term_end, "creation_context.term_end"
        )
        start = max(anchor, creation_start)
        end = min(anchor + timedelta(days=6), creation_end)
    if start > end:
        _fail("确认快照没有可用的日期范围")
    return {"start": start.isoformat(), "end": end.isoformat()}


def columns_for(content: dict) -> list[dict]:
    """Monday-Friday plus weekend days that are teaching in the saved basis."""
    basis = content["calendar_basis"]
    anchor = _iso_date(basis.get("week_anchor_date"), "calendar_basis.week_anchor_date")
    states = _basis_days(content)
    columns: list[dict] = []
    for offset in range(7):
        day = anchor + timedelta(days=offset)
        state = states.get(day.isoformat())
        if state is None:
            _fail("确认快照 calendar_basis 缺少日期")
        if day.isoweekday() <= 5 or state == "teaching":
            columns.append({"date": day.isoformat(), "day_state": state})
    return columns


FACT_KEYS = frozenset({"code", "field_path", "old_ref", "new_ref", "details"})
FACT_OPTIONAL_KEYS = frozenset({"message"})


def validate_fact_list(value: Any, label: str) -> list[dict]:
    if not isinstance(value, list):
        _fail(f"{label} 必须是数组")
    result: list[dict] = []
    for item in value:
        if not isinstance(item, dict):
            _fail(f"{label} 每项必须是对象")
        keys = set(item)
        if not FACT_KEYS <= keys or keys - FACT_KEYS - FACT_OPTIONAL_KEYS:
            _fail(f"{label} 事实字段不合法")
        if not isinstance(item.get("code"), str) or not item["code"]:
            _fail(f"{label} code 不合法")
        if not isinstance(item.get("field_path"), str):
            _fail(f"{label} field_path 不合法")
        if not isinstance(item.get("details"), dict):
            _fail(f"{label} details 必须是对象")
        if "message" in item and not isinstance(item["message"], str):
            _fail(f"{label} message 不合法")
        result.append(item)
    return result


def build_confirmation_snapshot(
    *,
    weekly_plan_id: str,
    profile_id: str,
    class_id: str,
    term_id: str,
    draft_id: str,
    draft_version: int,
    content_hash: str,
    header: dict,
    creation_context: dict,
    content: dict,
    facts: dict,
    term_name: str | None = None,
    reissued_from_confirmation_id: str | None = None,
) -> dict:
    snapshot = {
        "schema_version": 1,
        "weekly_plan_id": weekly_plan_id,
        "profile_id": profile_id,
        "class_id": class_id,
        "term_id": term_id,
        "draft_id": draft_id,
        "draft_version": draft_version,
        "content_hash": content_hash,
        "header": header,
        "creation_context": creation_context,
        "content": content,
        "date_range": date_range_for(
            content,
            creation_term_start=creation_context["term_start"],
            creation_term_end=creation_context["term_end"],
        ),
        "columns": columns_for(content),
        "facts": facts,
    }
    if term_name is not None:
        snapshot["term_name"] = term_name
    if reissued_from_confirmation_id is not None:
        snapshot["reissued_from_confirmation_id"] = (
            reissued_from_confirmation_id
        )
    return validate_confirmation_snapshot(snapshot)


def validate_confirmation_snapshot(snapshot: Any) -> dict:
    if (
        not isinstance(snapshot, dict)
        or not SNAPSHOT_KEYS <= set(snapshot)
        or set(snapshot) - SNAPSHOT_ALL_KEYS
    ):
        _fail("确认快照字段不完整")
    _exact_one(snapshot.get("schema_version"), "schema_version")
    for key in ("weekly_plan_id", "profile_id", "class_id", "term_id", "draft_id"):
        _id(snapshot.get(key), key)
    if "term_name" in snapshot:
        _term_name(snapshot.get("term_name"))
    if "reissued_from_confirmation_id" in snapshot:
        if "term_name" not in snapshot:
            _fail("确认快照的另存来源必须带 term_name")
        _id(
            snapshot.get("reissued_from_confirmation_id"),
            "reissued_from_confirmation_id",
        )
    draft_version = _positive_int(snapshot.get("draft_version"), "draft_version")
    content_hash = _hash(snapshot.get("content_hash"), "content_hash")
    header = validate_header(snapshot.get("header"))
    creation = snapshot.get("creation_context")
    if not isinstance(creation, dict) or set(creation) != CREATION_CONTEXT_KEYS:
        _fail("确认快照 creation_context 字段不完整")
    anchor = _iso_date(
        creation.get("week_anchor_date"), "creation_context.week_anchor_date"
    )
    if anchor.isoweekday() != 1:
        _fail("确认快照 week_anchor_date 必须是周一")
    week_number = _positive_int(
        creation.get("week_number_snapshot"), "week_number_snapshot"
    )
    term_start = _iso_date(creation.get("term_start"), "creation_context.term_start")
    term_end = _iso_date(creation.get("term_end"), "creation_context.term_end")
    if term_start > term_end:
        _fail("确认快照学期范围不合法")
    _id(creation.get("calendar_revision_id"), "calendar_revision_id")
    content = snapshot.get("content")
    if not isinstance(content, dict):
        _fail("确认快照 content 必须是对象")
    try:
        from app.local import weekly_plan_content

        normalized = weekly_plan_content.validate_content(content)
        actual_content_hash = weekly_plan_content.content_hash(normalized)
    except weekly_plan_content.WeeklyContentError as exc:
        raise LocalWeeklyInvalid(exc.message) from None
    if canonical_json(normalized) != canonical_json(content):
        _fail("确认快照 content 不是 B 规范化后的确切内容")
    if actual_content_hash != content_hash:
        _fail("确认快照 content_hash 与 content 不一致")
    manifest = content.get("source_manifest")
    if not isinstance(manifest, dict):
        _fail("确认快照 content 缺少 source_manifest")
    if (
        manifest.get("profile_id") != snapshot.get("profile_id")
        or manifest.get("class_id") != snapshot.get("class_id")
        or manifest.get("term_id") != snapshot.get("term_id")
        or manifest.get("header") != snapshot.get("header")
        or manifest.get("week_number") != week_number
    ):
        _fail("确认快照 content 归属/周次不一致")
    basis = content.get("calendar_basis")
    if not isinstance(basis, dict):
        _fail("确认快照 content 缺少 calendar_basis")
    if (
        basis.get("week_anchor_date") != anchor.isoformat()
        or manifest.get("week_anchor_date") != anchor.isoformat()
    ):
        _fail("确认快照 content 周锚点不一致")
    if anchor + timedelta(days=6) < term_start or anchor > term_end:
        _fail("确认快照创建学期与固定周没有交集")
    expected_range = date_range_for(
        content,
        creation_term_start=term_start.isoformat(),
        creation_term_end=term_end.isoformat(),
    )
    if snapshot.get("date_range") != expected_range:
        _fail("确认快照 date_range 不一致")
    expected_columns = columns_for(content)
    if snapshot.get("columns") != expected_columns:
        _fail("确认快照 columns 不一致")
    facts = snapshot.get("facts")
    if not isinstance(facts, dict) or set(facts) != FACTS_KEYS:
        _fail("确认快照 facts 字段不完整")
    for key in FACTS_KEYS:
        validate_fact_list(facts.get(key), f"facts.{key}")
    if snapshot.get("content_hash") != content_hash:
        _fail("确认快照 content_hash 不一致")
    if snapshot.get("draft_version") != draft_version:
        _fail("确认快照 draft_version 不一致")
    if header != snapshot.get("header"):
        _fail("确认快照 header 不一致")
    return snapshot


def _timestamp(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) < 20:
        _fail(f"{label} 必须是带时区的 ISO 时间")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _fail(f"{label} 必须是带时区的 ISO 时间")
    if parsed.tzinfo is None:
        _fail(f"{label} 必须带时区")
    return value


def validate_export_manifest(manifest: Any) -> dict:
    """Pure §11.7 export manifest validation (no DB access)."""
    if not isinstance(manifest, dict) or set(manifest) != EXPORT_MANIFEST_KEYS:
        _fail("导出 manifest 顶层字段不完整")
    _exact_one(manifest.get("schema_version"), "manifest.schema_version")
    _id(manifest.get("profile_id"), "manifest.profile_id")
    mode = manifest.get("mode")
    if mode not in ("single", "range"):
        _fail("导出 manifest mode 不合法")
    requested = manifest.get("requested_range")
    if requested is not None:
        if not isinstance(requested, dict) or set(requested) != {"start", "end"}:
            _fail("导出 manifest requested_range 不合法")
        req_start = _iso_date(requested.get("start"), "requested_range.start")
        req_end = _iso_date(requested.get("end"), "requested_range.end")
        if req_start > req_end:
            _fail("导出 manifest requested_range 顺序不合法")
    _timestamp(manifest.get("warnings_as_of"), "warnings_as_of")
    selection = manifest.get("selection")
    items = manifest.get("items")
    if not isinstance(selection, list) or not isinstance(items, list):
        _fail("导出 manifest selection/items 必须是数组")
    if len(selection) != len(items) or len(selection) > 8 or not items:
        _fail("导出 manifest 选集数量不合法")
    if mode == "single" and len(items) != 1:
        _fail("单份导出必须恰好一项")
    if mode == "single" and requested is not None:
        _fail("单份导出 requested_range 必须为 null")
    if mode == "range" and requested is None:
        _fail("范围导出必须提供 requested_range")
    selected_ids: set[tuple[str, str]] = set()
    plans: set[str] = set()
    previous_key = None
    derived_selection: list[dict] = []
    for item in items:
        if (
            not isinstance(item, dict)
            or not EXPORT_ITEM_KEYS <= set(item)
            or set(item) - EXPORT_ITEM_KEYS - EXPORT_ITEM_OPTIONAL_KEYS
        ):
            _fail("导出 manifest item 字段不完整")
        projection = {
            key: item[key]
            for key in SNAPSHOT_KEYS
        }
        for key in SNAPSHOT_OPTIONAL_KEYS:
            if key in item:
                projection[key] = item[key]
        snapshot = validate_confirmation_snapshot(projection)
        confirmation_id = _id(item.get("confirmation_id"), "item.confirmation_id")
        confirmation_version = _positive_int(
            item.get("confirmation_version"), "item.confirmation_version"
        )
        confirmation_hash = _hash(
            item.get("confirmation_hash"), "item.confirmation_hash"
        )
        if confirmation_hash != snapshot_hash(snapshot):
            _fail("导出 item confirmation_hash 不等于快照投影 hash")
        if snapshot["profile_id"] != manifest.get("profile_id"):
            _fail("导出 item profile 与 manifest 不一致")
        creation = snapshot["creation_context"]
        anchor = creation["week_anchor_date"]
        date_range = snapshot["date_range"]
        if requested is not None:
            teaching = [
                date.fromisoformat(day["date"])
                for day in snapshot["content"]["calendar_basis"]["days"]
                if day.get("day_state") == "teaching"
            ]
            if not any(req_start <= day <= req_end for day in teaching):
                _fail("导出 item 在 requested_range 内没有冻结教学日")
        plan_id = snapshot["weekly_plan_id"]
        key = (anchor, snapshot["term_id"], plan_id)
        if previous_key is not None and key < previous_key:
            _fail("导出 selection 顺序不合法")
        previous_key = key
        if plan_id in plans:
            _fail("同一计划在导出中重复")
        plans.add(plan_id)
        if (plan_id, confirmation_id) in selected_ids:
            _fail("导出确认重复")
        selected_ids.add((plan_id, confirmation_id))
        derived_selection.append(
            {
                "weekly_plan_id": plan_id,
                "confirmation_id": confirmation_id,
                "confirmation_version": confirmation_version,
                "draft_id": snapshot["draft_id"],
                "draft_version": snapshot["draft_version"],
                "content_hash": snapshot["content_hash"],
                "confirmation_hash": confirmation_hash,
                "week_anchor_date": anchor,
                "week_number": creation["week_number_snapshot"],
                "date_range": date_range,
            }
        )
    if len(selection) != len(derived_selection):
        _fail("导出 selection 数量不等于 items")
    for entry, expected in zip(selection, derived_selection):
        if not isinstance(entry, dict) or set(entry) != EXPORT_SELECTION_KEYS:
            _fail("导出 selection 项字段不完整")
        _id(entry.get("weekly_plan_id"), "selection.weekly_plan_id")
        _id(entry.get("confirmation_id"), "selection.confirmation_id")
        _positive_int(
            entry.get("confirmation_version"), "selection.confirmation_version"
        )
        _id(entry.get("draft_id"), "selection.draft_id")
        _positive_int(entry.get("draft_version"), "selection.draft_version")
        _hash(entry.get("content_hash"), "selection.content_hash")
        _hash(entry.get("confirmation_hash"), "selection.confirmation_hash")
        _iso_date(entry.get("week_anchor_date"), "selection.week_anchor_date")
        _positive_int(entry.get("week_number"), "selection.week_number")
        range_value = entry.get("date_range")
        if not isinstance(range_value, dict) or set(range_value) != {"start", "end"}:
            _fail("导出 selection.date_range 不合法")
        start = _iso_date(range_value.get("start"), "selection.date_range.start")
        end = _iso_date(range_value.get("end"), "selection.date_range.end")
        if start > end:
            _fail("导出 selection.date_range 顺序不合法")
        if canonical_json(entry) != canonical_json(expected):
            _fail("导出 selection 不等于 items 的确定性投影")
    if canonical_json(selection) != canonical_json(derived_selection):
        _fail("导出 selection 不等于 items 的确定性投影")
    missing = manifest.get("missing")
    warnings = manifest.get("warnings")
    if not isinstance(missing, list) or not isinstance(warnings, list):
        _fail("导出 missing/warnings 必须是数组")
    validate_fact_list(missing, "manifest.missing")
    expected_missing: list[dict] = []
    for item, selected in zip(items, derived_selection):
        facts = item["facts"]
        for fact in facts["missing"]:
            copied = copy.deepcopy(fact)
            copied["details"] = dict(copied.get("details") or {})
            copied["details"]["weekly_plan_id"] = selected["weekly_plan_id"]
            copied["details"]["confirmation_id"] = selected["confirmation_id"]
            expected_missing.append(copied)
    if canonical_json(missing) != canonical_json(expected_missing):
        _fail("导出 missing 不等于 items.facts.missing 的静态汇总")
    validate_fact_list(warnings, "manifest.warnings")
    for fact in warnings:
        details = fact["details"]
        plan_id = _id(
            details.get("weekly_plan_id"), "warnings.details.weekly_plan_id"
        )
        confirmation_id = _id(
            details.get("confirmation_id"),
            "warnings.details.confirmation_id",
        )
        if (plan_id, confirmation_id) not in selected_ids:
            _fail("导出 warnings 归属不在选集")
    return manifest
