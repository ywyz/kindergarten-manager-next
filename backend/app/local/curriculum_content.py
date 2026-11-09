"""Content contract for desktop curriculum deliberations.

The wire contract is a flat object of twenty strings.  Empty fields stay as
empty strings; this module validates every value before it can reach SQLite or
the Word generator, and provides the one canonical hash used for retry
detection.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import date
from typing import Any, Mapping

from app.local.errors import LocalStorageError, LocalValidationError

_ILLEGAL_XML = re.compile(
    "[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]"
)
_BODY_CF_KEEP = frozenset("\u200c\u200d")

FIELDS: tuple[str, ...] = (
    "activity_name",
    "activity_form",
    "activity_form_other",
    "institution",
    "class_name",
    "child_count",
    "organizer",
    "recorder",
    "activity_date",
    "goals_original",
    "goals_status",
    "goals_adjustment",
    "preparation_original",
    "preparation_status",
    "preparation_adjustment",
    "process_original",
    "process_adjustment",
    "reason",
    "lesson_original",
    "lesson_revised",
)

ACTIVITY_FORMS = ("", "collective", "area", "parent_child", "small_group", "other")
REVISION_STATUSES = ("", "unchanged", "adjusted")

MISSING_LABELS: tuple[tuple[str, str], ...] = (
    ("activity_name", "活动名称"),
    ("activity_form", "活动形式"),
    ("institution", "实施单位"),
    ("class_name", "班级（年龄段）"),
    ("child_count", "幼儿人数"),
    ("organizer", "组织教师"),
    ("recorder", "记录人"),
    ("activity_date", "活动时间"),
    ("goals_original", "活动目标"),
    ("preparation_original", "活动准备"),
    ("process_original", "活动过程记录"),
    ("reason", "调整理由"),
)


def empty_content() -> dict[str, str]:
    return {field: "" for field in FIELDS}


def sanitize_export_text(value: object) -> str:
    """Remove XML-disallowed paste data while keeping ZWJ/ZWNJ in body text."""
    text = str(value or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _ILLEGAL_XML.sub("", text)
    return "".join(
        char
        for char in text
        if unicodedata.category(char) != "Cf" or char in _BODY_CF_KEEP
    )


def is_substantive(value: object) -> bool:
    """True only when text remains after ignoring whitespace and Unicode Cf."""
    for char in sanitize_export_text(value):
        if char.isspace() or unicodedata.category(char) == "Cf":
            continue
        return True
    return False


def appendix_lines(value: object) -> list[str]:
    """Trim only exterior lines without substance; keep internal blank lines."""
    lines = sanitize_export_text(value).split("\n")
    start = 0
    end = len(lines)
    while start < end and not is_substantive(lines[start]):
        start += 1
    while end > start and not is_substantive(lines[end - 1]):
        end -= 1
    if start >= end:
        return []
    return lines[start:end]


def default_content(
    *,
    school_name: str | None,
    class_name: str,
    recorder_name: str,
) -> dict[str, str]:
    content = empty_content()
    content["institution"] = school_name or ""
    content["class_name"] = class_name
    content["recorder"] = recorder_name
    return content


def _validate_date(value: str) -> None:
    if value == "":
        return
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise LocalValidationError("activity_date 必须是 ISO 日期或空") from None
    if parsed.isoformat() != value:
        raise LocalValidationError("activity_date 必须是规范 ISO 日期")


def normalize_content(value: object) -> dict[str, str]:
    """Return the complete canonical object or raise a 422 validation error."""
    if not isinstance(value, dict):
        raise LocalValidationError("content 必须是对象")
    unknown = sorted(set(value) - set(FIELDS))
    if unknown:
        raise LocalValidationError(
            "content 包含未知字段：" + "、".join(str(item) for item in unknown)
        )
    content = empty_content()
    for field in FIELDS:
        raw = value.get(field, "")
        if not isinstance(raw, str):
            raise LocalValidationError(f"{field} 必须是字符串")
        content[field] = raw

    if content["activity_form"] not in ACTIVITY_FORMS:
        raise LocalValidationError("activity_form 不合法")
    if content["goals_status"] not in REVISION_STATUSES:
        raise LocalValidationError("goals_status 不合法")
    if content["preparation_status"] not in REVISION_STATUSES:
        raise LocalValidationError("preparation_status 不合法")
    if content["goals_status"] == "unchanged" and content["goals_adjustment"].strip():
        raise LocalValidationError("活动目标保持原设计不变时不能同时填写调整内容")
    if (
        content["preparation_status"] == "unchanged"
        and content["preparation_adjustment"].strip()
    ):
        raise LocalValidationError("活动准备保持原设计不变时不能同时填写调整内容")

    count = content["child_count"]
    if count and (not count.isascii() or not count.isdigit()):
        raise LocalValidationError("child_count 必须为空或非负整数字符串")
    _validate_date(content["activity_date"])
    return content


def stored_content(value: object) -> dict[str, str]:
    """Read a complete stored object; a malformed row is a storage failure."""
    if not isinstance(value, dict):
        raise LocalStorageError("课程审议内容存储损坏")
    content = empty_content()
    for field in FIELDS:
        raw = value.get(field, "")
        if not isinstance(raw, str):
            raise LocalStorageError("课程审议内容存储损坏")
        content[field] = raw
    return content


def normalize_document(value: object) -> dict[str, Any] | None:
    """Validate the optional local linkage document is JSON-safe and bounded."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise LocalValidationError("document 必须是对象或 null")
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
    except (TypeError, ValueError):
        raise LocalValidationError("document 必须可序列化为 JSON") from None
    if len(encoded.encode("utf-8")) > 1_048_576:
        raise LocalValidationError("document 超过长度上限")
    return json.loads(encoded)


def content_hash(content: Mapping[str, str]) -> str:
    payload = json.dumps(
        content,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def missing_fields(content: Mapping[str, str]) -> list[str]:
    """Chinese labels of blank main-table fields, in form order."""
    missing = [
        label
        for field, label in MISSING_LABELS
        if not is_substantive(content.get(field, ""))
    ]
    if content.get("goals_status") == "adjusted":
        if not is_substantive(content.get("goals_adjustment", "")):
            missing.append("活动目标调整内容")
    elif (
        not content.get("goals_status")
        and is_substantive(content.get("goals_adjustment", ""))
    ):
        missing.append("活动目标修订状态")
    if content.get("preparation_status") == "adjusted":
        if not is_substantive(content.get("preparation_adjustment", "")):
            missing.append("活动准备调整内容")
    elif (
        not content.get("preparation_status")
        and is_substantive(content.get("preparation_adjustment", ""))
    ):
        missing.append("活动准备修订状态")
    return missing


def appendices(content: Mapping[str, str]) -> list[str]:
    """Appendix identifiers in export order; whitespace-only material is empty."""
    result: list[str] = []
    if is_substantive(content.get("lesson_original", "")):
        result.append("original")
    if is_substantive(content.get("lesson_revised", "")):
        result.append("revised")
    return result


def list_summary(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "version": row.version,
        "activity_name": row.activity_name,
        "activity_date": (
            row.activity_date.isoformat() if row.activity_date is not None else ""
        ),
        "updated_at": row.updated_at.isoformat(),
    }


__all__ = [
    "ACTIVITY_FORMS",
    "FIELDS",
    "MISSING_LABELS",
    "REVISION_STATUSES",
    "appendices",
    "appendix_lines",
    "content_hash",
    "default_content",
    "empty_content",
    "is_substantive",
    "list_summary",
    "missing_fields",
    "normalize_content",
    "normalize_document",
    "sanitize_export_text",
    "stored_content",
]
