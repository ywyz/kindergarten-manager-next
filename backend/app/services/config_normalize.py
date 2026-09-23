"""Pure normalization helpers for I2 configuration inputs."""

from datetime import date, datetime

from app.services.config_errors import MAX_HEADER_NAMES, ValidationError


def normalize_school_name(value) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError("园所名称必须是字符串")
    cleaned = value.strip()
    if cleaned == "":
        return None
    if len(cleaned) > 120:
        raise ValidationError("园所名称长度应为 1–120 个字符")
    return cleaned


def normalize_term_name(value) -> str:
    if not isinstance(value, str):
        raise ValidationError("学期名称必须是字符串")
    cleaned = value.strip()
    if len(cleaned) < 1 or len(cleaned) > 80:
        raise ValidationError("学期名称长度应为 1–80 个字符")
    return cleaned


def normalize_class_name(value) -> str:
    if not isinstance(value, str):
        raise ValidationError("班级名称必须是字符串")
    cleaned = value.strip()
    if len(cleaned) < 1 or len(cleaned) > 80:
        raise ValidationError("班级名称长度应为 1–80 个字符")
    return cleaned


def normalize_header_names(values) -> list[str]:
    if not isinstance(values, list) or len(values) > MAX_HEADER_NAMES:
        raise ValidationError("表头教师名单最多包含 20 项")
    result: list[str] = []
    for item in values:
        if not isinstance(item, str):
            raise ValidationError("表头教师姓名必须是字符串")
        cleaned = item.strip()
        if len(cleaned) < 1 or len(cleaned) > 80:
            raise ValidationError("表头教师姓名长度应为 1–80 个字符")
        result.append(cleaned)
    return result


def normalize_caregiver_name(value) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError("保育员姓名必须是字符串")
    cleaned = value.strip()
    if cleaned == "":
        return None
    if len(cleaned) > 80:
        raise ValidationError("保育员姓名长度应为 1–80 个字符")
    return cleaned


def normalize_grade(value) -> str:
    if value not in ("small", "middle", "large"):
        raise ValidationError("年级只能是 small、middle、large")
    return value


def parse_date(value) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        raise ValidationError("日期必须是 YYYY-MM-DD 字符串")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError(f"非法日期：{value!r}") from exc


def normalize_reason(value) -> str:
    if not isinstance(value, str):
        raise ValidationError("例外原因必须是字符串")
    cleaned = value.strip()
    if len(cleaned) < 1 or len(cleaned) > 200:
        raise ValidationError("例外原因长度应为 1–200 个字符")
    return cleaned
