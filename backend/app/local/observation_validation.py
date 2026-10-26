"""Pure validation and canonical hashing for game-observation payloads.

This module is deliberately independent of FastAPI, SQLAlchemy and image
decoding.  It defines the E01 field contract, the three validation layers
(missing / invalid / contradictory warning), the fixed five-domain skeleton and
the single aggregate hash algorithm:

    SHA256(canonical_json([flat_payload, ordered_original_photo_manifest]))

``term_snapshot`` is part of the flat payload exactly once.  AI working images
are not the original-photo authority and do not participate in this hash.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any

from app.local.errors import LocalValidationError

RECORD_TYPES: tuple[str, ...] = ("public", "indoor", "outdoor")
EVALUATION_KEYS: tuple[str, ...] = (
    "health",
    "language",
    "social",
    "science",
    "arts",
)
SUPPORTED_IMAGE_FORMATS: tuple[str, ...] = (
    "jpeg",
    "png",
    "webp",
    "gif",
    "bmp",
)

PAYLOAD_KEYS: tuple[str, ...] = (
    "record_type",
    "observation_date",
    "start_time",
    "end_time",
    "term_id",
    "term_snapshot",
    "school_name",
    "class_name",
    "observer_name",
    "adult_count",
    "child_count",
    "age_years",
    "subjects",
    "environment",
    "observation_goal",
    "observation_process",
    "support_strategy",
    "analysis_evaluation",
)

PHOTO_MANIFEST_KEYS: tuple[str, ...] = (
    "asset_id",
    "content_hash",
    "format",
    "width",
    "height",
    "orientation",
    "sort_order",
    "caption",
)

_TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class ObservationValidationError(LocalValidationError):
    """A field-level observation validation failure (safe details only)."""

    code = "OBS_VALIDATION_INVALID"

    def __init__(
        self,
        message: str,
        *,
        field: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        payload = dict(details or {})
        if field is not None:
            payload["field"] = field
        super().__init__(message, details=payload or None)
        self.field = field


@dataclass(frozen=True)
class ObservationAnalysis:
    payload: dict[str, Any]
    missing_fields: tuple[str, ...]
    warnings: tuple[dict[str, str], ...]


def canonical_json(value: Any) -> str:
    """Deterministic UTF-8 JSON: sorted keys, no extra whitespace."""
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _text(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ObservationValidationError(f"{field} 必须是字符串或空", field=field)
    cleaned = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    return cleaned or None


def _required_text(value: Any, field: str) -> str:
    cleaned = _text(value, field)
    if cleaned is None:
        raise ObservationValidationError(f"{field} 不能为空", field=field)
    return cleaned


def _date(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str):
        raise ObservationValidationError(f"{field} 必须是 ISO 日期或空", field=field)
    try:
        return date.fromisoformat(value.strip()).isoformat()
    except ValueError:
        raise ObservationValidationError(
            f"{field} 必须是有效的 ISO 日期", field=field
        ) from None


def _time(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        value = value.time()
    if isinstance(value, time):
        return value.strftime("%H:%M")
    if not isinstance(value, str):
        raise ObservationValidationError(f"{field} 必须是 HH:mm 或空", field=field)
    cleaned = value.strip()
    if not _TIME_RE.fullmatch(cleaned):
        raise ObservationValidationError(
            f"{field} 必须是 HH:mm 格式", field=field
        )
    return cleaned


def _non_negative_int(value: Any, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ObservationValidationError(
            f"{field} 必须是整数或空（bool/float/字符串非法）", field=field
        )
    if value < 0:
        raise ObservationValidationError(f"{field} 不能为负数", field=field)
    return value


def _subjects(value: Any) -> list[dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ObservationValidationError("subjects 必须是数组", field="subjects")
    result: list[dict[str, str]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict) or set(item.keys()) != {"name"}:
            raise ObservationValidationError(
                "subjects 每项必须只含 name", field=f"subjects[{index}]"
            )
        name = _text(item.get("name"), f"subjects[{index}].name")
        if name is not None:
            result.append({"name": name})
    return result


def _evaluation(value: Any) -> dict[str, str]:
    if value is None:
        return {key: "" for key in EVALUATION_KEYS}
    if not isinstance(value, dict):
        raise ObservationValidationError(
            "analysis_evaluation 必须是对象", field="analysis_evaluation"
        )
    unknown = set(value.keys()) - set(EVALUATION_KEYS)
    if unknown:
        raise ObservationValidationError(
            "analysis_evaluation 含未知领域", field="analysis_evaluation"
        )
    result: dict[str, str] = {}
    for key in EVALUATION_KEYS:
        result[key] = _text(value.get(key), f"analysis_evaluation.{key}") or ""
    return result


def _term_snapshot(value: Any) -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ObservationValidationError(
            "term_snapshot 必须是对象或空", field="term_snapshot"
        )
    expected = {"term_id", "name", "start_date", "end_date"}
    if set(value.keys()) != expected:
        raise ObservationValidationError(
            "term_snapshot 字段集不合法", field="term_snapshot"
        )
    term_id = _required_text(value.get("term_id"), "term_snapshot.term_id")
    name = _required_text(value.get("name"), "term_snapshot.name")
    start = _date(value.get("start_date"), "term_snapshot.start_date")
    end = _date(value.get("end_date"), "term_snapshot.end_date")
    if start is None or end is None:
        raise ObservationValidationError(
            "term_snapshot 起止日期不能为空", field="term_snapshot"
        )
    if start > end:
        raise ObservationValidationError(
            "term_snapshot 起始日期不能晚于结束日期", field="term_snapshot"
        )
    return {
        "term_id": term_id,
        "name": name,
        "start_date": start,
        "end_date": end,
    }


def normalize_term_snapshot(value: Any) -> dict[str, str] | None:
    """Public wrapper for the service/history term snapshot shape."""
    return _term_snapshot(value)


def normalize_payload(
    raw: Any,
    *,
    term_snapshot: Any = None,
) -> dict[str, Any]:
    """Return the canonical flat payload.

    ``term_snapshot`` is a service-supplied companion; a client must not send a
    ``term_snapshot`` key.  If a snapshot is supplied, its ``term_id`` must equal
    the payload ``term_id`` (including both null).
    """
    if not isinstance(raw, dict):
        raise ObservationValidationError("payload 必须是对象")
    unknown = set(raw.keys()) - set(PAYLOAD_KEYS)
    if unknown:
        # Never echo arbitrary keys: a malicious caller could put a child name,
        # body text or path in a key.  The fixed count is enough for diagnosis.
        raise ObservationValidationError(
            "payload 含未列字段",
            field="payload",
            details={"unknown_field_count": len(unknown)},
        )
    if "term_snapshot" in raw:
        raise ObservationValidationError(
            "term_snapshot 只能由服务端提供", field="term_snapshot"
        )

    record_type = raw.get("record_type")
    if record_type not in RECORD_TYPES:
        raise ObservationValidationError(
            "record_type 必须是 public/indoor/outdoor", field="record_type"
        )

    term_id = _text(raw.get("term_id"), "term_id")
    snapshot = _term_snapshot(term_snapshot)
    if snapshot is not None and term_id != snapshot["term_id"]:
        raise ObservationValidationError(
            "term_id 与 term_snapshot 不一致", field="term_id"
        )

    payload: dict[str, Any] = {
        "record_type": record_type,
        "observation_date": _date(raw.get("observation_date"), "observation_date"),
        "start_time": _time(raw.get("start_time"), "start_time"),
        "end_time": _time(raw.get("end_time"), "end_time"),
        "term_id": term_id,
        "term_snapshot": snapshot,
        "school_name": _text(raw.get("school_name"), "school_name"),
        "class_name": _text(raw.get("class_name"), "class_name"),
        "observer_name": _text(raw.get("observer_name"), "observer_name"),
        "adult_count": _non_negative_int(raw.get("adult_count"), "adult_count"),
        "child_count": _non_negative_int(raw.get("child_count"), "child_count"),
        "age_years": _non_negative_int(raw.get("age_years"), "age_years"),
        "subjects": _subjects(raw.get("subjects")),
        "environment": _text(raw.get("environment"), "environment"),
        "observation_goal": _text(raw.get("observation_goal"), "observation_goal"),
        "observation_process": _text(
            raw.get("observation_process"), "observation_process"
        ),
        "support_strategy": _text(
            raw.get("support_strategy"), "support_strategy"
        ),
        "analysis_evaluation": _evaluation(raw.get("analysis_evaluation")),
    }
    return payload


def _is_empty_text(value: Any) -> bool:
    return not isinstance(value, str) or not value.strip()


def missing_fields(payload: dict[str, Any]) -> tuple[str, ...]:
    """Optional-field gaps; never a save/AI hard block by itself."""
    missing: list[str] = []
    for key in (
        "observation_date",
        "start_time",
        "end_time",
        "school_name",
        "class_name",
        "observer_name",
        "adult_count",
        "child_count",
        "age_years",
        "environment",
        "observation_goal",
        "observation_process",
        "support_strategy",
    ):
        if payload.get(key) is None or payload.get(key) == "":
            missing.append(key)
    if not payload.get("subjects"):
        missing.append("subjects")
    evaluation = payload.get("analysis_evaluation") or {}
    for key in EVALUATION_KEYS:
        if _is_empty_text(evaluation.get(key)):
            missing.append(f"analysis_evaluation.{key}")
    return tuple(missing)


def warnings(payload: dict[str, Any]) -> tuple[dict[str, str], ...]:
    """Contradictory facts are surfaced, never silently rewritten."""
    result: list[dict[str, str]] = []
    child_count = payload.get("child_count")
    subjects = payload.get("subjects") or []
    if isinstance(child_count, int) and child_count < len(subjects):
        result.append(
            {
                "code": "subjects_exceed_child_count",
                "message": "重点观察姓名数多于儿童总数，请复核",
            }
        )
    start = payload.get("start_time")
    end = payload.get("end_time")
    if isinstance(start, str) and isinstance(end, str) and end < start:
        result.append(
            {
                "code": "end_before_start",
                "message": "结束时间早于开始时间，请复核",
            }
        )
    return tuple(result)


def analyze_payload(
    raw: Any, *, term_snapshot: Any = None
) -> ObservationAnalysis:
    payload = normalize_payload(raw, term_snapshot=term_snapshot)
    return ObservationAnalysis(
        payload=payload,
        missing_fields=missing_fields(payload),
        warnings=warnings(payload),
    )


def ai_readiness(
    payload: dict[str, Any], *, valid_photo_count: int
) -> tuple[bool, tuple[str, ...]]:
    """AI-only minimum: names, unified age, environment and one valid photo."""
    required: list[str] = []
    if not payload.get("subjects"):
        required.append("subjects")
    if payload.get("age_years") is None:
        required.append("age_years")
    if _is_empty_text(payload.get("environment")):
        required.append("environment")
    if valid_photo_count < 1:
        required.append("photos")
    return (not required, tuple(required))


def is_empty_record(payload: dict[str, Any], *, valid_photo_count: int) -> bool:
    """Only header data, no actual four-column body and no valid photo."""
    if valid_photo_count > 0:
        return False
    if not _is_empty_text(payload.get("observation_goal")):
        return False
    if not _is_empty_text(payload.get("observation_process")):
        return False
    if not _is_empty_text(payload.get("support_strategy")):
        return False
    evaluation = payload.get("analysis_evaluation") or {}
    return all(_is_empty_text(evaluation.get(key)) for key in EVALUATION_KEYS)


def normalize_photo_manifest(manifest: Any) -> list[dict[str, Any]]:
    """Validate the ordered *original* photo manifest used by the business hash."""
    if not isinstance(manifest, list):
        raise ObservationValidationError(
            "photo_manifest 必须是数组", field="photo_manifest"
        )
    result: list[dict[str, Any]] = []
    seen_assets: set[str] = set()
    for index, item in enumerate(manifest):
        if not isinstance(item, dict):
            raise ObservationValidationError(
                f"photo_manifest[{index}] 必须是对象",
                field=f"photo_manifest[{index}]",
            )
        unknown = set(item.keys()) - set(PHOTO_MANIFEST_KEYS)
        if unknown:
            raise ObservationValidationError(
                f"photo_manifest[{index}] 含未列字段",
                field=f"photo_manifest[{index}]",
                details={"unknown_field_count": len(unknown)},
            )
        asset_id = _required_text(
            item.get("asset_id"), f"photo_manifest[{index}].asset_id"
        )
        if asset_id in seen_assets:
            raise ObservationValidationError(
                "photo_manifest asset_id 不能重复",
                field=f"photo_manifest[{index}].asset_id",
            )
        seen_assets.add(asset_id)
        content_hash = _required_text(
            item.get("content_hash"), f"photo_manifest[{index}].content_hash"
        )
        if not re.fullmatch(r"[0-9a-fA-F]{64}", content_hash):
            raise ObservationValidationError(
                f"photo_manifest[{index}].content_hash 必须是 64 位十六进制",
                field=f"photo_manifest[{index}].content_hash",
            )
        content_hash = content_hash.lower()
        image_format = item.get("format")
        if image_format not in SUPPORTED_IMAGE_FORMATS:
            raise ObservationValidationError(
                f"photo_manifest[{index}].format 不受支持",
                field=f"photo_manifest[{index}].format",
            )
        width = _non_negative_int(
            item.get("width"), f"photo_manifest[{index}].width"
        )
        height = _non_negative_int(
            item.get("height"), f"photo_manifest[{index}].height"
        )
        if width is None or height is None or width < 1 or height < 1:
            raise ObservationValidationError(
                f"photo_manifest[{index}] 尺寸必须为正整数",
                field=f"photo_manifest[{index}].size",
            )
        orientation = item.get("orientation")
        if orientation is not None:
            if isinstance(orientation, bool) or not isinstance(orientation, int):
                raise ObservationValidationError(
                    f"photo_manifest[{index}].orientation 必须是整数或空",
                    field=f"photo_manifest[{index}].orientation",
                )
            # Pillow exif_transpose covers all EXIF orientation values 1..8,
            # including mirrored 2/4/5/7.  E01 only validates metadata; image
            # decoding remains E03.
            if orientation < 1 or orientation > 8:
                raise ObservationValidationError(
                    f"photo_manifest[{index}].orientation 不合法",
                    field=f"photo_manifest[{index}].orientation",
                )
        sort_order = _non_negative_int(
            item.get("sort_order"), f"photo_manifest[{index}].sort_order"
        )
        if sort_order is None:
            raise ObservationValidationError(
                f"photo_manifest[{index}].sort_order 不能为空",
                field=f"photo_manifest[{index}].sort_order",
            )
        # One authority: the manifest array is already in display order and
        # sort_order must equal its index.  A reversed array with stale
        # sort_order values is rejected, not silently reinterpreted.
        if sort_order != index:
            raise ObservationValidationError(
                "photo_manifest 数组次序必须与 sort_order 一致",
                field=f"photo_manifest[{index}].sort_order",
            )
        caption = _text(item.get("caption"), f"photo_manifest[{index}].caption")
        result.append(
            {
                "asset_id": asset_id,
                "content_hash": content_hash,
                "format": image_format,
                "width": width,
                "height": height,
                "orientation": orientation,
                "sort_order": sort_order,
                "caption": caption,
            }
        )
    return result


def aggregate_hash(
    payload: dict[str, Any], photo_manifest: Any
) -> str:
    """The one E01 business hash: payload once + ordered original manifest."""
    manifest = normalize_photo_manifest(photo_manifest)
    return hashlib.sha256(
        canonical_json([payload, manifest]).encode("utf-8")
    ).hexdigest()


__all__ = [
    "RECORD_TYPES",
    "EVALUATION_KEYS",
    "SUPPORTED_IMAGE_FORMATS",
    "ObservationValidationError",
    "ObservationAnalysis",
    "normalize_term_snapshot",
    "normalize_payload",
    "analyze_payload",
    "missing_fields",
    "warnings",
    "ai_readiness",
    "is_empty_record",
    "normalize_photo_manifest",
    "aggregate_hash",
    "canonical_json",
]
