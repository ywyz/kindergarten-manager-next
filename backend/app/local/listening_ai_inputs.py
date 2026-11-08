"""Listening AI server projection and verified image material loading."""

from __future__ import annotations

import base64
import hashlib
import io
from dataclasses import dataclass
from typing import Any

from PIL import Image
from sqlalchemy.orm import Session

from app.local import listening_assets, listening_service, listening_templates
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
    item_ids = [item.item_id for item in template.items]
    photos: list[dict[str, Any]] = []
    selected_groups = groups
    if task_type == TASK_NOTE:
        selected_groups = [group for group in groups if group["group_id"] == group_id]
        if len(selected_groups) != 1:
            raise LocalStorageError("倾听小组不存在")
    elif task_type == TASK_GROUP:
        selected_groups = [group for group in groups if group.get("asset_id")]
        if not 1 <= len(selected_groups) <= 3:
            raise ListeningAIContractError("本领域没有可发送的有效照片图位")
    elif task_type == TASK_GOAL:
        selected_groups = [
            group
            for group in groups
            if group.get("asset_id") or (group.get("listening_text") or "").strip()
        ]
        if not 1 <= len(selected_groups) <= 3:
            raise ListeningAIContractError(
                "本领域没有可发送的已保存文字或照片材料"
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
        text = (group.get("listening_text") or "").strip() or None
        if text is None and photo is None:
            raise ListeningAIContractError("本组没有可发送的已保存正文或作品图")
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
            "work_date": (group.get("work_date") or "").strip() or None,
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
                    "work_date": (group.get("work_date") or "").strip() or None,
                    "listening_text": (
                        group.get("listening_text") or ""
                    ).strip()
                    or None,
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
                (group.get("listening_text") or "").strip()
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
                    "work_date": (group.get("work_date") or "").strip() or None,
                    "listening_text": (
                        group.get("listening_text") or ""
                    ).strip()
                    or None,
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
        goal = (domain_dto.get("goal") or "").strip() or None
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
        for group in groups:
            photo = photo_by_group.get(group["group_id"])
            payload_groups.append(
                {
                    "position": int(group["position"]),
                    "work_date": (group.get("work_date") or "").strip() or None,
                    "listening_text": (group.get("listening_text") or "").strip() or None,
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
            "goal": (domain_dto.get("goal") or "").strip() or None,
            "observation_date": (domain_dto.get("observation_date") or "").strip() or None,
            "adult_count": (domain_dto.get("adult_count") or "").strip() or None,
            "child_age": (domain_dto.get("child_age") or "").strip() or None,
            "observation_area": (domain_dto.get("observation_area") or "").strip() or None,
            "groups": payload_groups,
            "items": payload_items,
        }
        stars = {
            item["item_id"]: item.get("stars")
            for item in domain_dto.get("evaluation") or []
        }
        target_hashes = {
            "overall_evaluation": value_hash((domain_dto.get("overall_evaluation") or "").strip()),
            "support_strategy": value_hash((domain_dto.get("support_strategy") or "").strip()),
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
