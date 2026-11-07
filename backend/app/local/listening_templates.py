"""Controlled one-to-one listening Word template registry.

The registry is a manifest plus versioned DOCX assets.  It deliberately has
no database table: a record stores the exact template version and SHA-256 it
was created with, and an old record keeps reading that version even after a
newer manifest version is added.  There is no fallback to "latest" for an
explicit missing version.

The manifest records the cleaned asset SHA-256, the stable evaluation item
ids (for example ``health_1``) and the original per-star text.  The DOCX
bytes remain the layout authority; the manifest is the evaluation-item
authority used to create and validate choice rows.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any

from app.local.errors import LocalError

TEMPLATE_ROOT = (
    Path(__file__).resolve().parent.parent / "assets" / "listening_templates"
)
MANIFEST_PATH = TEMPLATE_ROOT / "manifest.json"

GRADES: tuple[str, ...] = ("small", "middle", "large")
DOMAINS: tuple[str, ...] = ("health", "language", "social", "science", "art")
DOMAIN_LABELS: dict[str, str] = {
    "health": "健康",
    "language": "语言",
    "social": "社会",
    "science": "科学",
    "art": "艺术",
}
GRADE_LABELS: dict[str, str] = {
    "small": "小班",
    "middle": "中班",
    "large": "大班",
}
ITEM_ID_RE = re.compile(r"^(health|language|social|science|art)_([1-9][0-9]*)$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class ListeningTemplateNotFound(LocalError):
    code = "LISTENING_TEMPLATE_NOT_FOUND"
    status_code = 422
    message = "未找到该年级、领域和版本的倾听模板"


class ListeningTemplateInvalid(LocalError):
    code = "LISTENING_TEMPLATE_INVALID"
    status_code = 500
    message = "倾听模板资源损坏或登记不一致"


@dataclass(frozen=True)
class ListeningEvaluationItem:
    item_id: str
    level1: str
    level2: str
    requirement: str
    standards: dict[str, str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "level1": self.level1,
            "level2": self.level2,
            "requirement": self.requirement,
            "standards": dict(self.standards),
        }


@dataclass(frozen=True)
class ListeningTemplate:
    grade: str
    domain: str
    version: str
    path: str
    sha256: str
    title: str | None
    items: tuple[ListeningEvaluationItem, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "grade": self.grade,
            "grade_label": GRADE_LABELS[self.grade],
            "domain": self.domain,
            "domain_label": DOMAIN_LABELS[self.domain],
            "version": self.version,
            "sha256": self.sha256,
            "title": self.title,
            "items": [item.as_dict() for item in self.items],
        }


def _invalid(message: str) -> ListeningTemplateInvalid:
    return ListeningTemplateInvalid(message)


def _require_text(value: Any, label: str, *, maximum: int = 4000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise _invalid(f"模板清单字段不合法：{label}")
    return value


def _parse_manifest(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise _invalid("模板清单不是严格 UTF-8 JSON") from exc
    if not isinstance(value, dict) or set(value) != {
        "format_version",
        "default_version",
        "templates",
    }:
        raise _invalid("模板清单顶层字段不合法")
    if value["format_version"] != 1:
        raise _invalid("模板清单格式版本不受支持")
    default_version = _require_text(value["default_version"], "default_version", maximum=20)
    entries = value["templates"]
    if not isinstance(entries, list) or not entries:
        raise _invalid("模板清单条目为空")
    seen: set[tuple[str, str, str]] = set()
    parsed: list[ListeningTemplate] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or set(entry) != {
            "grade",
            "grade_label",
            "domain",
            "domain_label",
            "version",
            "path",
            "sha256",
            "source_name",
            "title",
            "items",
        }:
            raise _invalid(f"模板条目字段不合法：templates[{index}]")
        grade = entry["grade"]
        domain = entry["domain"]
        version = entry["version"]
        if grade not in GRADES or domain not in DOMAINS:
            raise _invalid(f"模板年级或领域不合法：templates[{index}]")
        if entry["grade_label"] != GRADE_LABELS[grade]:
            raise _invalid(f"模板年级标签不合法：templates[{index}]")
        if entry["domain_label"] != DOMAIN_LABELS[domain]:
            raise _invalid(f"模板领域标签不合法：templates[{index}]")
        if not isinstance(version, str) or not re.fullmatch(r"v[1-9][0-9]*", version):
            raise _invalid(f"模板版本不合法：templates[{index}]")
        path = entry["path"]
        if not isinstance(path, str) or not path or "\\" in path or ":" in path:
            raise _invalid(f"模板路径不合法：templates[{index}]")
        pure = PurePosixPath(path)
        if pure.is_absolute() or any(part in ("", ".", "..") for part in pure.parts):
            raise _invalid(f"模板路径不合法：templates[{index}]")
        sha = entry["sha256"]
        if not isinstance(sha, str) or not _SHA_RE.fullmatch(sha):
            raise _invalid(f"模板散列不合法：templates[{index}]")
        key = (grade, domain, version)
        if key in seen:
            raise _invalid(f"模板条目重复：templates[{index}]")
        seen.add(key)
        source_name = entry["source_name"]
        if not isinstance(source_name, str) or len(source_name) > 255:
            raise _invalid(f"模板来源名不合法：templates[{index}]")
        title = entry["title"]
        if title is not None and (not isinstance(title, str) or len(title) > 500):
            raise _invalid(f"模板标题不合法：templates[{index}]")
        items_raw = entry["items"]
        if not isinstance(items_raw, list) or not items_raw:
            raise _invalid(f"模板评价项为空：templates[{index}]")
        items: list[ListeningEvaluationItem] = []
        seen_items: set[str] = set()
        for item_index, item in enumerate(items_raw):
            if not isinstance(item, dict) or set(item) != {
                "item_id",
                "level1",
                "level2",
                "requirement",
                "standards",
            }:
                raise _invalid(
                    f"评价项字段不合法：templates[{index}].items[{item_index}]"
                )
            item_id = item["item_id"]
            match = ITEM_ID_RE.fullmatch(item_id) if isinstance(item_id, str) else None
            if match is None or match.group(1) != domain:
                raise _invalid(
                    f"评价项编号不合法：templates[{index}].items[{item_index}]"
                )
            if item_id in seen_items:
                raise _invalid(f"评价项编号重复：{item_id}")
            seen_items.add(item_id)
            level1 = item["level1"]
            level2 = item["level2"]
            if not isinstance(level1, str) or len(level1) > 120:
                raise _invalid(f"一级指标不合法：{item_id}")
            if not isinstance(level2, str) or len(level2) > 120:
                raise _invalid(f"二级指标不合法：{item_id}")
            requirement = item["requirement"]
            if not isinstance(requirement, str) or not requirement.strip():
                raise _invalid(f"评价要求不合法：{item_id}")
            if len(requirement) > 4000:
                raise _invalid(f"评价要求过长：{item_id}")
            standards = item["standards"]
            if not isinstance(standards, dict) or set(standards) != {"1", "2", "3"}:
                raise _invalid(f"星级标准不合法：{item_id}")
            clean_standards: dict[str, str] = {}
            for star in ("1", "2", "3"):
                text = standards[star]
                if not isinstance(text, str) or not text.strip() or len(text) > 4000:
                    raise _invalid(f"星级标准文本不合法：{item_id}.{star}")
                clean_standards[star] = text
            items.append(
                ListeningEvaluationItem(
                    item_id=item_id,
                    level1=level1,
                    level2=level2,
                    requirement=requirement,
                    standards=clean_standards,
                )
            )
        file_path = TEMPLATE_ROOT.joinpath(*pure.parts)
        try:
            payload = file_path.read_bytes()
        except OSError as exc:
            raise _invalid(f"模板文件缺失：{path}") from exc
        if hashlib.sha256(payload).hexdigest() != sha:
            raise _invalid(f"模板文件散列不一致：{path}")
        parsed.append(
            ListeningTemplate(
                grade=grade,
                domain=domain,
                version=version,
                path=path,
                sha256=sha,
                title=title,
                items=tuple(items),
            )
        )
    if default_version not in {entry.version for entry in parsed}:
        raise _invalid("默认模板版本不存在")
    return {
        "default_version": default_version,
        "templates": tuple(parsed),
    }


@lru_cache(maxsize=1)
def _manifest() -> dict[str, Any]:
    try:
        raw = MANIFEST_PATH.read_bytes()
    except OSError as exc:
        raise _invalid("模板清单缺失") from exc
    return _parse_manifest(raw)


def manifest_version() -> str:
    return str(_manifest()["default_version"])


def list_templates() -> tuple[ListeningTemplate, ...]:
    return tuple(_manifest()["templates"])


def get_template(
    grade: str, domain: str, version: str | None = None
) -> ListeningTemplate:
    if grade not in GRADES:
        raise ListeningTemplateNotFound()
    if domain not in DOMAINS:
        raise ListeningTemplateNotFound()
    target_version = version or str(_manifest()["default_version"])
    if not isinstance(target_version, str):
        raise ListeningTemplateNotFound()
    for entry in _manifest()["templates"]:
        if (
            entry.grade == grade
            and entry.domain == domain
            and entry.version == target_version
        ):
            return entry
    # An explicit or stored old version is never silently replaced by the
    # newest version: the caller must handle the missing template.
    raise ListeningTemplateNotFound()


def read_template_bytes(template: ListeningTemplate) -> bytes:
    path = TEMPLATE_ROOT.joinpath(*PurePosixPath(template.path).parts)
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise ListeningTemplateInvalid("倾听模板文件缺失") from exc
    if hashlib.sha256(payload).hexdigest() != template.sha256:
        raise ListeningTemplateInvalid("倾听模板文件散列不一致")
    return payload


def templates_for_grade(grade: str) -> tuple[ListeningTemplate, ...]:
    if grade not in GRADES:
        raise ListeningTemplateNotFound()
    return tuple(entry for entry in _manifest()["templates"] if entry.grade == grade)


__all__ = [
    "GRADES",
    "DOMAINS",
    "DOMAIN_LABELS",
    "GRADE_LABELS",
    "ListeningEvaluationItem",
    "ListeningTemplate",
    "ListeningTemplateNotFound",
    "ListeningTemplateInvalid",
    "TEMPLATE_ROOT",
    "get_template",
    "list_templates",
    "manifest_version",
    "read_template_bytes",
    "templates_for_grade",
]
