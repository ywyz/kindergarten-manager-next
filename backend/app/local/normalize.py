"""Local input normalization and the initialization retry fingerprint.

Reuses the reviewed pure normalization rules (``config_normalize`` /
``config_errors``): whitespace trimming, 1–80 names, empty-or-1–120 school
name, small/middle/large grade and ISO dates. No sample values and no
guessed term dates are ever injected.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import date

from app.local.errors import LocalValidationError
from app.services import config_normalize as cfg
from app.services.config_errors import MAX_QUERY_DAYS, MAX_TERM_DAYS, ValidationError

MAX_DISPLAY_NAME = 80


@dataclass(frozen=True)
class NormalizedInitialization:
    """Validated, normalized initialization payload (retry-stable)."""

    request_id: str
    display_name: str
    class_name: str
    grade: str
    term_name: str
    start_date: date
    end_date: date
    school_name: str | None

    def fingerprint(self) -> str:
        """Stable sha256 of the normalized input, used for retry decisions."""
        payload = {
            "class_name": self.class_name,
            "display_name": self.display_name,
            "end_date": self.end_date.isoformat(),
            "grade": self.grade,
            "school_name": self.school_name,
            "start_date": self.start_date.isoformat(),
            "term_name": self.term_name,
        }
        canonical = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def normalize_request_id(value: object) -> str:
    if isinstance(value, uuid.UUID):
        return str(value)
    if not isinstance(value, str):
        raise LocalValidationError("request_id 必须是 UUID")
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError):
        raise LocalValidationError("request_id 必须是 UUID") from None


def normalize_display_name(value: object) -> str:
    if not isinstance(value, str):
        raise LocalValidationError("姓名必须是字符串")
    cleaned = value.strip()
    if len(cleaned) < 1 or len(cleaned) > MAX_DISPLAY_NAME:
        raise LocalValidationError("姓名长度应为 1–80 个字符")
    return cleaned


def normalize_initialization(
    *,
    request_id: object,
    display_name: object,
    class_name: object,
    grade: object,
    term_name: object,
    start_date: object,
    end_date: object,
    school_name: object = None,
) -> NormalizedInitialization:
    """Validate and normalize one initialization request."""
    try:
        normalized = NormalizedInitialization(
            request_id=normalize_request_id(request_id),
            display_name=normalize_display_name(display_name),
            class_name=cfg.normalize_class_name(class_name),
            grade=cfg.normalize_grade(grade),
            term_name=cfg.normalize_term_name(term_name),
            start_date=cfg.parse_date(start_date),
            end_date=cfg.parse_date(end_date),
            school_name=cfg.normalize_school_name(school_name),
        )
    except ValidationError as exc:
        raise LocalValidationError(str(exc)) from None
    if normalized.start_date > normalized.end_date:
        raise LocalValidationError("学期开始日期不能晚于结束日期")
    if (normalized.end_date - normalized.start_date).days + 1 > MAX_TERM_DAYS:
        raise LocalValidationError(f"学期范围不能超过 {MAX_TERM_DAYS} 天")
    return normalized


def normalize_raw_lesson_plan(value: object) -> str | None:
    """Raw lesson plan is free text; explicit null clears it."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise LocalValidationError("raw_lesson_plan 必须是字符串或 null")
    return value


def validate_date_range(from_date: date, to_date: date, *, max_days: int = MAX_QUERY_DAYS) -> None:
    """Closed interval, ordered, bounded (used by calendar and list reads)."""
    if from_date > to_date:
        raise LocalValidationError("from 不能晚于 to")
    if (to_date - from_date).days + 1 > max_days:
        raise LocalValidationError(f"日期范围不能超过 {max_days} 天")
