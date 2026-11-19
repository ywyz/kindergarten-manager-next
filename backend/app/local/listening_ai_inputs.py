"""Listening AI server projection and verified image material loading."""

from __future__ import annotations

import base64
import hashlib
import io
from dataclasses import dataclass
from typing import Any, Mapping

from PIL import Image
from sqlalchemy.orm import Session

from app.local import (
    listening_ai_contracts,
    listening_assets,
    listening_service,
    listening_templates,
)
from app.local.errors import LocalAiInputTooLarge, LocalStorageError
from app.local.listening_ai_contracts import (
    INPUT_SCHEMA_VERSION,
    TASK_DOMAIN,
    TASK_GOAL,
    TASK_GROUP,
    TASK_NOTE,
    TASK_TYPES,
    ListeningAIContractError,
    group_note_target_key as listening_group_note_target_key,
    validate_input,
    value_hash,
)
from app.local.models import LocalAIInput
from app.local.prompt_bundles import canonical_json
from app.local.listening_export_service import _prepare_word_photo

AI_SCHEMA_VERSION = 1
MAX_AI_IMAGE_SIDE = 2048
MAX_AI_IMAGE_BYTES = 5 * 1024 * 1024
MAX_DOMAIN_PHOTOS = 3
MAX_OUTPUT_BYTES = 1_048_576


@dataclass(frozen=True)
class Projection:
    task_type: str
    record_id: str
    domain: str
    group_id: str | None
    payload: dict[str, Any]
    dependencies: dict[str, Any]
    dependency_hash: str
    target_hashes: dict[str, str]
    source_revision: int
    item_ids: tuple[str, ...]


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _prepare_ai_image(payload: bytes, metadata: dict[str, Any]) -> dict[str, Any]:
    prepared = _prepare_word_photo(payload, metadata)
    data = prepared["data"]
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            if max(image.width, image.height) > MAX_AI_IMAGE_SIDE:
                image.thumbnail((MAX_AI_IMAGE_SIDE, MAX_AI_IMAGE_SIDE))
            if image.mode in ("RGBA", "LA") or "transparency" in image.info:
                working = image.convert("RGBA")
                fmt, mime = "PNG", "image/png"
                output = io.BytesIO()
                working.save(output, format=fmt, optimize=True)
            else:
                working = image.convert("RGB")
                fmt, mime = "JPEG", "image/jpeg"
                output = io.BytesIO()
                for quality in (88, 80, 70):
                    output = io.BytesIO()
                    working.save(output, format=fmt, quality=quality, optimize=True)
                    if output.tell() <= MAX_AI_IMAGE_BYTES:
                        break
                if output.tell() > MAX_AI_IMAGE_BYTES:
                    raise LocalAiInputTooLarge("倾听 AI 工作图超过技术上限")
            if output.tell() > MAX_AI_IMAGE_BYTES:
                raise LocalAiInputTooLarge("倾听 AI 工作图超过技术上限")
            return {
                "data": output.getvalue(),
                "mime_type": mime,
                "width": int(working.width),
                "height": int(working.height),
                "source_hash": prepared["source_sha256"],
                "orientation": prepared.get("orientation"),
                "rotation_quarters": prepared.get("rotation_quarters", 0),
            }
    except LocalAiInputTooLarge:
        raise
    except Exception as exc:  # noqa: BLE001
        raise LocalStorageError("倾听 AI 图片无法解码") from exc


def _read_photo(
    session: Session,
    runtime: Any,
    *,
    profile_id: str,
    record_id: str,
    asset_id: str,
    group_id: str,
    position: int,
    include_data: bool = False,
) -> dict[str, Any]:
    payload, metadata = listening_assets.read_asset(
        session,
        runtime,
        profile_id=profile_id,
        record_id=record_id,
        asset_id=asset_id,
    )
    prepared = _prepare_ai_image(payload, metadata)
    return {
        "asset_id": asset_id,
        "group_id": group_id,
        "position": position,
        "source_hash": prepared["source_hash"],
        "work_hash": hashlib.sha256(prepared["data"]).hexdigest(),
        "mime_type": prepared["mime_type"],
        "width": prepared["width"],
        "height": prepared["height"],
        "orientation": prepared["orientation"],
        "rotation_quarters": prepared.get("rotation_quarters", 0),
        "source_bytes": len(payload),
        "work_bytes": len(prepared["data"]),
        **({"data": prepared["data"]} if include_data else {}),
    }


def _wire_photo(photo: dict[str, Any] | None) -> dict[str, Any] | None:
    if photo is None:
        return None
    return {
        "work_hash": photo["work_hash"],
        "format": photo["mime_type"].split("/", 1)[-1],
        "width": photo["width"],
        "height": photo["height"],
        "orientation": photo["orientation"],
    }


def _load(session: Session, profile_id: str, record_id: str, domain: str):
    dto = listening_service.read_record_no_tx(
        session, profile_id=profile_id, record_id=record_id
    )
    domain_dto = next(
        (item for item in dto["domains"] if item["domain"] == domain), None
    )
    if domain_dto is None:
        raise LocalStorageError("倾听领域缺失")
    template = listening_templates.get_template(
        dto["grade"], domain, domain_dto["template_version"]
    )
    if template.sha256 != domain_dto["template_sha256"]:
        raise LocalStorageError("倾听模板版本/散列不一致")
    return dto, domain_dto, template


def _domain_state(domain_dto: dict[str, Any], item_ids: list[str]) -> tuple[str | None, str | None, dict[str, int | None]]:
    stars = {
        item["item_id"]: item.get("stars")
        for item in domain_dto.get("evaluation") or []
    }
    return stars


def _groups(domain_dto: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(
        domain_dto.get("groups") or [], key=lambda item: item["position"]
    )


CURRENT_FORM_SCHEMA_VERSION = 1
_CURRENT_FORM_KEYS = frozenset(
    {
        "schema_version",
        "observation_date",
        "adult_count",
        "child_age",
        "goal",
        "observation_area",
        "overall_evaluation",
        "support_strategy",
        "groups",
        "evaluation",
    }
)
_CURRENT_GROUP_KEYS = frozenset(
    {"group_id", "position", "work_date", "listening_text", "asset_id"}
)
_CURRENT_EVALUATION_KEYS = frozenset({"item_id", "stars"})
_MAX_SHORT_FORM_FIELD = 200
_MAX_DATE_FORM_FIELD = 80


def _form_text(
    value: object, field: str, maximum: int
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ListeningAIContractError(f"当前表单 {field} 必须是字符串")
    text = value.strip()
    if not text:
        return None
    if len(text) > maximum:
        raise ListeningAIContractError(f"当前表单 {field} 超过长度上限")
    return text


def normalize_current_form(
    value: object,
    *,
    dto: Mapping[str, Any],
    domain_dto: Mapping[str, Any],
    task_type: str,
    group_id: str | None,
) -> dict[str, Any]:
    """Validate one teacher-supplied current domain form.

    The snapshot may contain unsaved text, dates, goals, evaluation stars and
    an unsaved group order.  Stable group ids and asset ids, however, must still
    belong to this record/domain: the AI must never be pointed at a different
    child record or a photo that is not already saved for that group.
    """

    if not isinstance(value, Mapping):
        raise ListeningAIContractError("当前表单必须是对象")
    if set(value) != _CURRENT_FORM_KEYS:
        raise ListeningAIContractError("当前表单字段不合法")
    if value.get("schema_version") != CURRENT_FORM_SCHEMA_VERSION:
        raise ListeningAIContractError("当前表单版本不合法")
    saved_groups = {
        str(group["group_id"]): group
        for group in domain_dto.get("groups") or []
    }
    if len(saved_groups) != 3:
        raise LocalStorageError("倾听图文组数量不是三组")
    raw_groups = value.get("groups")
    if not isinstance(raw_groups, list) or len(raw_groups) != 3:
        raise ListeningAIContractError("当前表单必须包含三组图文")
    groups: list[dict[str, Any]] = []
    seen_groups: set[str] = set()
    for index, raw in enumerate(raw_groups):
        if not isinstance(raw, Mapping) or set(raw) != _CURRENT_GROUP_KEYS:
            raise ListeningAIContractError("当前表单图组字段不合法")
        group_key = raw.get("group_id")
        position = raw.get("position")
        asset_id = raw.get("asset_id")
        if (
            not isinstance(group_key, str)
            or group_key not in saved_groups
            or group_key in seen_groups
            or isinstance(position, bool)
            or not isinstance(position, int)
            or position != index
            or (asset_id is not None and not isinstance(asset_id, str))
        ):
            raise ListeningAIContractError("当前表单图组身份不合法")
        saved = saved_groups[group_key]
        if saved.get("asset_id") != asset_id:
            raise ListeningAIContractError("当前表单照片与已保存图组不一致")
        seen_groups.add(group_key)
        groups.append(
            {
                "group_id": group_key,
                "position": position,
                "work_date": _form_text(
                    raw.get("work_date"),
                    f"第 {index + 1} 组作品日期",
                    _MAX_DATE_FORM_FIELD,
                ),
                "listening_text": _form_text(
                    raw.get("listening_text"),
                    f"第 {index + 1} 组倾听正文",
                    listening_ai_contracts.MAX_TEXT,
                ),
                "asset_id": asset_id,
            }
        )
    if seen_groups != set(saved_groups):
        raise ListeningAIContractError("当前表单图组不完整")

    raw_evaluation = value.get("evaluation")
    if not isinstance(raw_evaluation, list):
        raise ListeningAIContractError("当前表单评价字段不合法")
    saved_item_ids = {
        str(item["item_id"])
        for item in domain_dto.get("evaluation") or []
    }
    evaluation: list[dict[str, Any]] = []
    seen_items: set[str] = set()
    for raw in raw_evaluation:
        if not isinstance(raw, Mapping) or set(raw) != _CURRENT_EVALUATION_KEYS:
            raise ListeningAIContractError("当前表单评价项字段不合法")
        item_id = raw.get("item_id")
        stars = raw.get("stars")
        if (
            not isinstance(item_id, str)
            or item_id not in saved_item_ids
            or item_id in seen_items
            or (
                stars is not None
                and (isinstance(stars, bool) or stars not in (1, 2, 3))
            )
        ):
            raise ListeningAIContractError("当前表单评价项不合法")
        seen_items.add(item_id)
        evaluation.append({"item_id": item_id, "stars": stars})
    if seen_items != saved_item_ids:
        raise ListeningAIContractError("当前表单评价项不完整")

    normalized = {
        "schema_version": CURRENT_FORM_SCHEMA_VERSION,
        "observation_date": _form_text(
            value.get("observation_date"),
            "观察月份",
            _MAX_DATE_FORM_FIELD,
        ),
        "adult_count": _form_text(
            value.get("adult_count"),
            "成人数目",
            _MAX_SHORT_FORM_FIELD,
        ),
        "child_age": _form_text(
            value.get("child_age"),
            "幼儿年龄",
            _MAX_SHORT_FORM_FIELD,
        ),
        "goal": _form_text(
            value.get("goal"),
            "观察目标",
            listening_ai_contracts.MAX_GOAL,
        ),
        "observation_area": _form_text(
            value.get("observation_area"),
            "观察区域",
            _MAX_SHORT_FORM_FIELD,
        ),
        "overall_evaluation": _form_text(
            value.get("overall_evaluation"),
            "综合评价",
            listening_ai_contracts.MAX_TEXT,
        ),
        "support_strategy": _form_text(
            value.get("support_strategy"),
            "支持策略",
            listening_ai_contracts.MAX_TEXT,
        ),
        "groups": groups,
        "evaluation": evaluation,
    }
    if task_type == TASK_NOTE:
        if not group_id:
            raise ListeningAIContractError("倾听小组任务缺少 group_id")
        group = next(
            (item for item in groups if item["group_id"] == group_id), None
        )
        if group is None:
            raise ListeningAIContractError("倾听小组不属于当前表单")
        if not group["listening_text"] and not group["asset_id"]:
            raise ListeningAIContractError("本组没有可发送的当前正文或作品图")
    elif task_type == TASK_GROUP:
        if not any(group["asset_id"] for group in groups):
            raise ListeningAIContractError("本领域没有可发送的有效照片图位")
    elif task_type == TASK_GOAL:
        if not any(
            group["asset_id"] or group["listening_text"] for group in groups
        ):
            raise ListeningAIContractError("本领域没有可发送的当前材料")
    return normalized


def is_current_form_input(inp: LocalAIInput) -> bool:
    dependencies = getattr(inp, "dependencies_json", None)
    return (
        isinstance(dependencies, Mapping)
        and dependencies.get("source_mode") == "current_form"
    )


def stored_projection(inp: LocalAIInput) -> Projection:
    """The exact immutable input captured when the task was created."""

    payload = dict(inp.payload_json or {})
    item_ids = tuple(
        str(item["item_id"]) for item in payload.get("items") or []
    )
    return Projection(
        task_type=str(inp.task_type),
        record_id=str(inp.listening_record_id),
        domain=str(inp.listening_domain),
        group_id=inp.listening_group_id,
        payload=payload,
        dependencies=dict(inp.dependencies_json or {}),
        dependency_hash=str(inp.dependency_hash),
        target_hashes=dict(inp.target_hashes_json or {}),
        source_revision=int(inp.source_revision or 0),
        item_ids=item_ids,
    )



def _read_photo_isolated(
    runtime: Any,
    *,
    profile_id: str,
    record_id: str,
    asset_id: str,
    group_id: str,
    position: int,
    include_data: bool = False,
) -> dict[str, Any]:
    """Read/decode one listening image in its own short read transaction."""
    session = runtime.session()
    try:
        return _read_photo(
            session,
            runtime,
            profile_id=profile_id,
            record_id=record_id,
            asset_id=asset_id,
            group_id=group_id,
            position=position,
            include_data=include_data,
        )
    finally:
        session.close()

def project(
    session: Session,
    runtime: Any | None,
    *,
    profile_id: str,
    record_id: str,
    domain: str,
    group_id: str | None,
    task_type: str,
    current_form: object | None = None,
    stored_photos: dict[str, dict[str, Any]] | None = None,
) -> Projection:
    if task_type not in TASK_TYPES:
        raise ListeningAIContractError("未知倾听 AI 任务类型")
    if task_type == TASK_NOTE and not group_id:
        raise ListeningAIContractError("倾听小组任务缺少 group_id")
    if task_type == TASK_DOMAIN and group_id is not None:
        raise ListeningAIContractError("领域评价任务不得绑定小组")
    if task_type == TASK_GROUP and group_id is not None:
        raise ListeningAIContractError("多图位整理不得绑定单个小组")
    if task_type == TASK_GOAL and group_id is not None:
        raise ListeningAIContractError("观察目标不得绑定单个小组")
    dto, domain_dto, template = _load(
        session, profile_id, record_id, domain
    )
    groups = _groups(domain_dto)
    if len(groups) != 3:
        raise LocalStorageError("倾听图文组数量不是三组")
    form = (
        normalize_current_form(
            current_form,
            dto=dto,
            domain_dto=domain_dto,
            task_type=task_type,
            group_id=group_id,
        )
        if current_form is not None
        else None
    )
    saved_by_group = {str(group["group_id"]): group for group in groups}
    if form is not None:
        current_groups = [
            {
                **saved_by_group[item["group_id"]],
                "position": item["position"],
                "work_date": item["work_date"],
                "listening_text": item["listening_text"],
                "asset_id": item["asset_id"],
            }
            for item in form["groups"]
        ]
    else:
        current_groups = groups

    def group_text(group: Mapping[str, Any]) -> str | None:
        return (group.get("listening_text") or "").strip() or None

    def group_date(group: Mapping[str, Any]) -> str | None:
        return (group.get("work_date") or "").strip() or None

    def form_value(field: str) -> str | None:
        if form is not None:
            return form[field]
        return (domain_dto.get(field) or "").strip() or None

    item_ids = [item.item_id for item in template.items]
    photos: list[dict[str, Any]] = []
    selected_groups = current_groups
    if task_type == TASK_NOTE:
        selected_groups = [
            group for group in current_groups if group["group_id"] == group_id
        ]
        if len(selected_groups) != 1:
            raise LocalStorageError("倾听小组不存在")
    elif task_type == TASK_GROUP:
        selected_groups = [
            group for group in current_groups if group.get("asset_id")
        ]
        if not 1 <= len(selected_groups) <= 3:
            raise ListeningAIContractError("本领域没有可发送的有效照片图位")
    elif task_type == TASK_GOAL:
        selected_groups = [
            group
            for group in current_groups
            if group.get("asset_id") or group_text(group)
        ]
        if not 1 <= len(selected_groups) <= 3:
            raise ListeningAIContractError(
                "本领域没有可发送的当前文字或照片材料"
            )
    stored = stored_photos or {}
    for group in selected_groups:
        current_asset = group.get("asset_id")
        if runtime is None:
            dep = stored.get(group["group_id"])
            if dep is None and current_asset:
                raise ListeningAIContractError("倾听图片来源已变化")
            if dep is not None and dep.get("asset_id") != current_asset:
                raise ListeningAIContractError("倾听图片来源已变化")
            if dep is not None:
                photos.append(dep)
        elif current_asset:
            photos.append(
                _read_photo_isolated(
                    runtime,
                    profile_id=profile_id,
                    record_id=record_id,
                    asset_id=current_asset,
                    group_id=group["group_id"],
                    position=int(group["position"]),
                )
            )
    photo_by_group = {item["group_id"]: item for item in photos}
    if task_type == TASK_NOTE:
        group = selected_groups[0]
        photo = photo_by_group.get(group["group_id"])
        text = group_text(group)
        if text is None and photo is None:
            raise ListeningAIContractError("本组没有可发送的当前正文或作品图")
        payload = {
            "schema_version": INPUT_SCHEMA_VERSION,
            "mode": "group_note",
            "domain": domain,
            "domain_label": listening_templates.DOMAIN_LABELS[domain],
            "grade": dto["grade"],
            "grade_label": listening_templates.GRADE_LABELS[dto["grade"]],
            "template_version": template.version,
            "template_sha256": template.sha256,
            "group_position": int(group["position"]),
            "work_date": group_date(group),
            "listening_text": text,
            "photo": _wire_photo(photo),
            "photo_only": bool(photo is not None and text is None),
        }
        stars = _domain_state(domain_dto, item_ids)
        target_hashes = {
            "listening_text": value_hash(text or ""),
        }
        dependencies = {
            "wire_schema_version": AI_SCHEMA_VERSION,
            "internal_schema_version": AI_SCHEMA_VERSION,
            "record_id": record_id,
            "domain": domain,
            "group_id": group["group_id"],
            "group_position": int(group["position"]),
            "template_version": template.version,
            "template_sha256": template.sha256,
            "photos": photos,
            "photo_only": payload["photo_only"],
            "source_revision": dto["revision"],
        }
    elif task_type == TASK_GROUP:
        payload_groups = []
        for group in selected_groups:
            photo = photo_by_group.get(group["group_id"])
            if photo is None:
                raise ListeningAIContractError("倾听图片来源已变化")
            payload_groups.append(
                {
                    "position": int(group["position"]),
                    "work_date": group_date(group),
                    "listening_text": group_text(group),
                    "photo": _wire_photo(photo),
                }
            )
        payload = {
            "schema_version": INPUT_SCHEMA_VERSION,
            "mode": "group_notes",
            "domain": domain,
            "domain_label": listening_templates.DOMAIN_LABELS[domain],
            "grade": dto["grade"],
            "grade_label": listening_templates.GRADE_LABELS[dto["grade"]],
            "template_version": template.version,
            "template_sha256": template.sha256,
            "groups": payload_groups,
        }
        target_hashes = {
            listening_group_note_target_key(domain, int(group["position"])): value_hash(
                group_text(group) or ""
            )
            for group in selected_groups
        }
        dependencies = {
            "wire_schema_version": AI_SCHEMA_VERSION,
            "internal_schema_version": AI_SCHEMA_VERSION,
            "record_id": record_id,
            "domain": domain,
            "group_id": None,
            "group_positions": [
                int(group["position"]) for group in selected_groups
            ],
            "template_version": template.version,
            "template_sha256": template.sha256,
            "photos": photos,
            "source_revision": dto["revision"],
        }
    elif task_type == TASK_GOAL:
        payload_groups = []
        for group in selected_groups:
            photo = photo_by_group.get(group["group_id"])
            payload_groups.append(
                {
                    "position": int(group["position"]),
                    "work_date": group_date(group),
                    "listening_text": group_text(group),
                    "photo": _wire_photo(photo),
                }
            )
        payload_items = [
            {
                "item_id": item.item_id,
                "level1": item.level1,
                "level2": item.level2,
                "requirement": item.requirement,
                "standards": dict(item.standards),
            }
            for item in template.items
        ]
        goal = form_value("goal")
        payload = {
            "schema_version": INPUT_SCHEMA_VERSION,
            "mode": "goal_suggest",
            "domain": domain,
            "domain_label": listening_templates.DOMAIN_LABELS[domain],
            "grade": dto["grade"],
            "grade_label": listening_templates.GRADE_LABELS[dto["grade"]],
            "template_version": template.version,
            "template_sha256": template.sha256,
            "goal": goal,
            "groups": payload_groups,
            "items": payload_items,
        }
        target_hashes = {
            "goal": value_hash(goal or ""),
        }
        dependencies = {
            "wire_schema_version": AI_SCHEMA_VERSION,
            "internal_schema_version": AI_SCHEMA_VERSION,
            "record_id": record_id,
            "domain": domain,
            "group_id": None,
            "group_positions": [
                int(group["position"]) for group in selected_groups
            ],
            "template_version": template.version,
            "template_sha256": template.sha256,
            "photos": photos,
            "source_revision": dto["revision"],
        }
    else:
        payload_groups = []
        for group in current_groups:
            photo = photo_by_group.get(group["group_id"])
            payload_groups.append(
                {
                    "position": int(group["position"]),
                    "work_date": group_date(group),
                    "listening_text": group_text(group),
                    "photo": _wire_photo(photo),
                }
            )
        payload_items = [
            {
                "item_id": item.item_id,
                "level1": item.level1,
                "level2": item.level2,
                "requirement": item.requirement,
                "standards": dict(item.standards),
            }
            for item in template.items
        ]
        payload = {
            "schema_version": INPUT_SCHEMA_VERSION,
            "mode": "domain_evaluate",
            "domain": domain,
            "domain_label": listening_templates.DOMAIN_LABELS[domain],
            "grade": dto["grade"],
            "grade_label": listening_templates.GRADE_LABELS[dto["grade"]],
            "template_version": template.version,
            "template_sha256": template.sha256,
            "goal": form_value("goal"),
            "observation_date": form_value("observation_date"),
            "adult_count": form_value("adult_count"),
            "child_age": form_value("child_age"),
            "observation_area": form_value("observation_area"),
            "groups": payload_groups,
            "items": payload_items,
        }
        stars = (
            {item["item_id"]: item.get("stars") for item in form["evaluation"]}
            if form is not None
            else {
                item["item_id"]: item.get("stars")
                for item in domain_dto.get("evaluation") or []
            }
        )
        target_hashes = {
            "overall_evaluation": value_hash(form_value("overall_evaluation") or ""),
            "support_strategy": value_hash(form_value("support_strategy") or ""),
            **{item_id: value_hash(stars.get(item_id)) for item_id in item_ids},
        }
        dependencies = {
            "wire_schema_version": AI_SCHEMA_VERSION,
            "internal_schema_version": AI_SCHEMA_VERSION,
            "record_id": record_id,
            "domain": domain,
            "group_id": None,
            "template_version": template.version,
            "template_sha256": template.sha256,
            "photos": photos,
            "source_revision": dto["revision"],
        }
    if form is not None:
        dependencies.update(
            {
                "source_mode": "current_form",
                "current_form_schema_version": CURRENT_FORM_SCHEMA_VERSION,
                "current_form_hash": _digest(form),
                "current_form_groups": [
                    {
                        "group_id": item["group_id"],
                        "position": item["position"],
                        "asset_id": item["asset_id"],
                    }
                    for item in form["groups"]
                ],
            }
        )
    validate_input(task_type, payload)
    dependency_hash = _digest(
        {
            "payload": payload,
            "photos": [
                {
                    "group_id": item["group_id"],
                    "position": item["position"],
                    "work_hash": item["work_hash"],
                }
                for item in photos
            ],
        }
    )
    return Projection(
        task_type=task_type,
        record_id=record_id,
        domain=domain,
        group_id=group_id,
        payload=payload,
        dependencies=dependencies,
        dependency_hash=dependency_hash,
        target_hashes=target_hashes,
        source_revision=int(dto["revision"]),
        item_ids=tuple(item_ids),
    )


def revalidate_source(session: Session, task: Any) -> bool:
    if task.source_kind != "one_to_one_listening" or not task.listening_record_id:
        return False
    inp = session.get(LocalAIInput, task.input_id)
    if (
        inp is None
        or inp.source_kind != "one_to_one_listening"
        or inp.source_id != task.listening_record_id
        or inp.listening_record_id != task.listening_record_id
        or inp.listening_domain != task.listening_domain
        or inp.listening_group_id != task.listening_group_id
        or inp.profile_id != task.profile_id
        or inp.task_type != task.task_type
    ):
        return False
    deps = dict(inp.dependencies_json or {})
    if deps.get("wire_schema_version") != AI_SCHEMA_VERSION:
        return False
    photos = list(deps.get("photos") or [])
    if len(photos) > MAX_DOMAIN_PHOTOS:
        return False
    if deps.get("source_mode") == "current_form":
        # A current-form task intentionally does not require the saved revision
        # or saved text to stay unchanged: generation must use the form the
        # teacher explicitly submitted, without forcing an auto-save.  Stable
        # record/domain/group/photo identity is still required so a candidate
        # can never be pointed at another child, domain or replacement image.
        try:
            dto, domain_dto, template = _load(
                session,
                task.profile_id,
                task.listening_record_id,
                task.listening_domain,
            )
            if template.version != deps.get("template_version") or (
                template.sha256 != deps.get("template_sha256")
            ):
                return False
            frozen_groups = list(deps.get("current_form_groups") or [])
            if len(frozen_groups) != 3:
                return False
            saved_groups = {
                str(group["group_id"]): group
                for group in domain_dto.get("groups") or []
            }
            if len(saved_groups) != 3:
                return False
            for item in frozen_groups:
                group = saved_groups.get(str(item.get("group_id")))
                if group is None or group.get("asset_id") != item.get("asset_id"):
                    return False
            if deps.get("current_form_schema_version") != CURRENT_FORM_SCHEMA_VERSION:
                return False
        except Exception:  # noqa: BLE001 - unreadable identity is stale
            return False
        if task.task_type == TASK_NOTE and len(photos) > 1:
            return False
        if task.task_type == TASK_DOMAIN and len(photos) > MAX_DOMAIN_PHOTOS:
            return False
        if task.task_type == TASK_GROUP:
            positions = [
                int(group["position"])
                for group in dict(inp.payload_json or {}).get("groups") or []
            ]
            if (
                not 1 <= len(positions) <= MAX_DOMAIN_PHOTOS
                or len(photos) != len(positions)
                or deps.get("group_positions") != positions
            ):
                return False
        if task.task_type == TASK_GOAL:
            positions = [
                int(group["position"])
                for group in dict(inp.payload_json or {}).get("groups") or []
            ]
            if (
                not 1 <= len(positions) <= MAX_DOMAIN_PHOTOS
                or len(photos) > MAX_DOMAIN_PHOTOS
                or deps.get("group_positions") != positions
            ):
                return False
        return True
    try:
        projected = project(
            session,
            None,
            profile_id=task.profile_id,
            record_id=task.listening_record_id,
            domain=task.listening_domain,
            group_id=task.listening_group_id,
            task_type=task.task_type,
            stored_photos={item["group_id"]: item for item in photos},
        )
    except Exception:  # noqa: BLE001
        return False
    if projected.dependency_hash != inp.dependency_hash:
        return False
    if task.task_type == TASK_NOTE and len(photos) > 1:
        return False
    if task.task_type == TASK_DOMAIN and len(photos) > MAX_DOMAIN_PHOTOS:
        return False
    if task.task_type == TASK_GROUP:
        positions = [
            int(group["position"])
            for group in dict(inp.payload_json or {}).get("groups") or []
        ]
        if (
            not 1 <= len(positions) <= MAX_DOMAIN_PHOTOS
            or len(photos) != len(positions)
            or deps.get("group_positions") != positions
        ):
            return False
    if task.task_type == TASK_GOAL:
        positions = [
            int(group["position"])
            for group in dict(inp.payload_json or {}).get("groups") or []
        ]
        if (
            not 1 <= len(positions) <= MAX_DOMAIN_PHOTOS
            or len(photos) > MAX_DOMAIN_PHOTOS
            or deps.get("group_positions") != positions
        ):
            return False
    return True



def build_vision_frames(
    *,
    base_url: str,
    model: str,
    secret: str,
    system_text: str,
    user_text: str,
    image_urls: list[str],
    deadline_ms: int,
    task_type: str,
    contract_version: int,
    record_id: str,
    domain: str,
    group_id: str | None,
    synthetic: dict[str, Any] | None = None,
) -> list[bytes]:
    import json as _json

    from app.local import ai_transport

    vision_meta = {
        "protocol": ai_transport.VISION_PROTOCOL_ID,
        "schema_version": AI_SCHEMA_VERSION,
        "source_kind": "one_to_one_listening",
        "task_type": task_type,
        "contract_version": contract_version,
        "image_count": len(image_urls),
        "listening_record_id": record_id,
        "listening_domain": domain,
        "listening_group_id": group_id,
    }
    request = {
        "protocol": ai_transport.VISION_PROTOCOL_ID,
        "vision": vision_meta,
        "base_url": base_url,
        "model": model,
        "secret": secret,
        "system_text": system_text,
        "user_text": user_text,
        "image_urls": image_urls,
    }
    body = {
        "type": "bootstrap",
        "deadline_ms": deadline_ms,
        "synthetic": synthetic,
        "request": request,
    }
    body_raw = _json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    header = {
        "type": "bootstrap_header",
        "vision": True,
        **vision_meta,
        "frame_size": len(body_raw),
    }
    return [
        _json.dumps(header, separators=(",", ":")).encode("utf-8"),
        body_raw,
    ]

def load_material(runtime: Any, pick: Any) -> tuple[dict[str, Any] | None, str | None]:
    from app.local.ai_config_service import _build_store, _decrypt_secret
    from app.local.ai_task_service import _meta
    from app.local.models import (
        LocalAIConfigVersion,
        LocalAICredential,
        LocalAIState,
        LocalPersonalPromptVersion,
        LocalPromptBundle,
    )
    from app.local.tx import read_scope
    import app.local.ai_task_service as task_service

    session = runtime.session()
    try:
        with read_scope(session):
            profile_id = task_service._profile_id(session)
            task = session.get(task_service.LocalAITask, pick.task_id)
            if (
                task is None
                or task.profile_id != profile_id
                or task.source_kind != "one_to_one_listening"
                or task.input_id != pick.input_id
                or task.task_type != pick.task_type
                or task.listening_record_id != pick.listening_record_id
                or task.listening_domain != pick.listening_domain
                or task.listening_group_id != pick.listening_group_id
            ):
                return None, "input_missing"
            if not revalidate_source(session, task):
                return None, "source_changed"
            state = session.get(LocalAIState, profile_id)
            config = (
                session.get(
                    LocalAIConfigVersion,
                    (profile_id, pick.config_version),
                )
                if state is not None and pick.config_version is not None
                else None
            )
            if state is None or config is None:
                return None, "not_configured"
            credential = (
                session.get(LocalAICredential, config.credential_id)
                if config.credential_id is not None
                else None
            )
            if (
                config.base_url is None
                or config.model is None
                or credential is None
                or credential.profile_id != profile_id
                or credential.state != "active"
                or credential.key_id is None
                or credential.nonce is None
                or credential.ciphertext is None
            ):
                return None, "not_configured"
            version = session.get(
                LocalPersonalPromptVersion,
                (profile_id, pick.task_type, pick.personal_revision),
            )
            bundle = session.get(
                LocalPromptBundle,
                (pick.task_type, pick.contract_version, pick.default_revision),
            )
            inp = session.get(LocalAIInput, pick.input_id)
            if version is None or bundle is None:
                return None, "prompt_missing"
            if (
                inp is None
                or inp.source_kind != "one_to_one_listening"
                or inp.profile_id != profile_id
                or inp.listening_record_id != pick.listening_record_id
                or inp.listening_domain != pick.listening_domain
                or inp.listening_group_id != pick.listening_group_id
                or inp.task_type != pick.task_type
            ):
                return None, "input_missing"
            payload = dict(inp.payload_json or {})
            try:
                validate_input(inp.task_type, payload)
            except ListeningAIContractError:
                return None, "input_invalid"
            deps = dict(inp.dependencies_json or {})
            photos = list(deps.get("photos") or [])
            if len(photos) > (1 if inp.task_type == TASK_NOTE else MAX_DOMAIN_PHOTOS):
                return None, "input_invalid"
            if len(photos) != int(
                (payload.get("photo") is not None)
                if inp.task_type == TASK_NOTE
                else sum(
                    1
                    for group in payload.get("groups") or []
                    if group.get("photo") is not None
                )
            ):
                return None, "input_invalid"
            if photos and not ai_transport_vision(config.base_url, config.model):
                return None, "vision_model_unsupported"
            guidance = dict(version.guidance_json or {})
            output_schema = dict(bundle.output_schema_json or {})
            record_id = inp.listening_record_id
            base_url = config.base_url
            model = config.model
            database_uuid = state.database_uuid
            credential_id = config.credential_id
            credential_key_id = str(credential.key_id)
            credential_nonce = bytes(credential.nonce)
            credential_ciphertext = bytes(credential.ciphertext)
            image_deps = photos
    finally:
        session.close()
    store = _build_store(profile_id, database_uuid, getattr(runtime, "credential_root", None))
    if store is None or len(credential_nonce) != 12:
        return None, "credential_unavailable"
    try:
        from app.local.credentials import SavedSecret

        master_key = store.load_master_key(credential_key_id)
        secret = store.decrypt_secret(
            master_key,
            SavedSecret(
                key_id=credential_key_id,
                nonce=credential_nonce,
                ciphertext=credential_ciphertext,
            ),
            profile_id,
            credential_id,
        )
    except Exception:  # noqa: BLE001
        return None, "credential_unavailable"
    if secret is None:
        return None, "credential_unavailable"
    image_urls: list[str] = []
    work_dimensions: list[tuple[int, int]] = []
    session = runtime.session()
    try:
        for photo in image_deps:
            try:
                prepared = _read_photo(
                    session,
                    runtime,
                    profile_id=profile_id,
                    record_id=record_id,
                    asset_id=photo["asset_id"],
                    group_id=photo["group_id"],
                    position=int(photo["position"]),
                    include_data=True,
                )
            except Exception:  # noqa: BLE001
                return None, "material_invalid"
            if (
                prepared["work_hash"] != photo["work_hash"]
                or prepared["source_hash"] != photo["source_hash"]
            ):
                return None, "material_invalid"
            image_urls.append(
                f"data:{prepared['mime_type']};base64,"
                + base64.b64encode(prepared["data"]).decode("ascii")
            )
            work_dimensions.append((prepared["width"], prepared["height"]))
    finally:
        session.close()
    from app.local.ai_task_service import _render_system_text

    system_text = _render_system_text(
        pick.task_type,
        pick.contract_version,
        output_schema,
        guidance,
        protocol=(
            "chat_completions_vision_v1" if image_urls else "chat_completions_v1"
        ),
    )
    return {
        "payload": payload,
        "system_text": system_text,
        "base_url": base_url,
        "model": model,
        "secret": secret,
        "image_urls": tuple(image_urls),
        "work_dimensions": tuple(work_dimensions),
        "attempt_budget_ms": 180_000 if image_urls else 120_000,
        "vision_authorized": bool(image_urls),
        "vision_schema_version": AI_SCHEMA_VERSION if image_urls else None,
        "vision_protocol": "chat_completions_vision_v1" if image_urls else None,
    }, None


def ai_transport_vision(base_url: Any, model: Any) -> bool:
    from app.local import ai_transport

    return ai_transport.vision_capability(base_url, model)
