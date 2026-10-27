"""E06 observation AI input projection and material preparation.

The service owns the *actual send projection*.  Internal source identities
(asset/derivative/record/profile/term) stay in SQLite; the provider payload
contains only the nine base business fields, the four current columns, ordered
photo facts (original/work hashes, format, dimensions, orientation, order and
caption), and the rewrite target/source.  The dependency hash is computed over
exactly that send projection, never over a later current draft.

Material reads use E03's verified derivative reader outside any write
transaction.  The caller freezes the returned image data URLs in the task
input; the worker only receives those verified bytes.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.local import ai_transport
from app.local.errors import (
    LocalAiInputInvalid,
    LocalAiInputTooLarge,
    LocalStorageError,
)
from app.local.models import (
    LocalAIInput,
    LocalObservationAIInputPhoto,
    LocalObservationAsset,
    LocalObservationAssetDerivative,
)
from app.local.observation_assets import (
    AI_PARAMS_VERSION,
    AI_TARGET_BYTES,
    inspect_managed_asset,
    managed_asset_path,
    managed_derivative_path,
    read_derivative_bytes,
)
from app.local.observation_service import _load_current
from app.local.observation_validation import (
    EVALUATION_KEYS,
    PHOTO_MANIFEST_KEYS,
    ai_readiness,
    canonical_json,
    missing_fields,
    warnings as observation_warnings,
)

OBSERVATION_INPUT_SCHEMA_VERSION = 1
INTERNAL_INPUT_SCHEMA_VERSION = 1
WIRE_INPUT_SCHEMA_VERSION = 1
WIRE_PROJECTION_ID = "observation_wire_v1"
OBSERVATION_TASK_TYPES = (
    "game_observation_generate",
    "game_observation_rewrite",
)
TARGETS = (
    "observation_goal",
    "observation_process",
    "analysis_evaluation",
    "support_strategy",
)
CONTEXT_TOKEN_LIMIT = 1_000_000
CONTEXT_OUTPUT_RESERVE_TOKENS = 8192
DEEPSEEK_IMAGE_TOKEN_CAP = 1024
MIMO_PATCH_SIZE = 16
MIMO_SPATIAL_MERGE = 2
MIMO_MIN_PIXELS = 8192
MIMO_MAX_PIXELS = 8_388_608
BASE_FIELDS = (
    "record_type",
    "observation_date",
    "start_time",
    "end_time",
    "adult_count",
    "child_count",
    "age_years",
    "subjects",
    "environment",
)
GENERATE_TARGETS = TARGETS
REWRITE_CONTEXT = {
    "observation_goal": ("observation_process",),
    "observation_process": ("observation_goal",),
    "analysis_evaluation": ("observation_goal", "observation_process"),
    "support_strategy": (
        "observation_goal",
        "observation_process",
        "analysis_evaluation",
    ),
}


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def vision_capability(base_url: Any, model: Any) -> bool:
    """Only the two official standard vision adapters are authorized."""
    return ai_transport.vision_capability(base_url, model)


def mimo_image_tokens(width: int, height: int) -> int:
    """Official MiMo estimate; conservative rounding, not a billing claim."""
    import math

    factor = MIMO_PATCH_SIZE * MIMO_SPATIAL_MERGE
    h_bar = int(round(height / factor)) * factor
    w_bar = int(round(width / factor)) * factor
    if h_bar * w_bar > MIMO_MAX_PIXELS:
        beta = math.sqrt((height * width) / MIMO_MAX_PIXELS)
        h_bar = math.floor(height / beta / factor) * factor
        w_bar = math.floor(width / beta / factor) * factor
    elif h_bar * w_bar < MIMO_MIN_PIXELS:
        beta = math.sqrt(MIMO_MIN_PIXELS / (height * width))
        h_bar = math.ceil(height / beta / factor) * factor
        w_bar = math.ceil(width / beta / factor) * factor
    grid_h = max(h_bar // MIMO_PATCH_SIZE, 1)
    grid_w = max(w_bar // MIMO_PATCH_SIZE, 1)
    return max(
        1,
        (grid_h * grid_w) // (MIMO_SPATIAL_MERGE**2),
    )


def deepseek_image_tokens(width: int, height: int) -> int:
    """Conservative upper bound: DeepSeek caps one image at 1024 tokens."""
    return DEEPSEEK_IMAGE_TOKEN_CAP


def check_vision_context(
    *,
    base_url: str,
    model: str,
    system_text: str,
    user_text: str,
    work_dimensions: list[tuple[int, int]],
) -> dict[str, int]:
    """Reject a request whose estimated image+text tokens exceed context.

    The estimate uses the frozen AI work-image dimensions and the actual
    system/user UTF-8 text plus a fixed output/protocol reserve.  It is a
    conservative admission check, not a provider token or billing measurement.
    """
    host = ""
    try:
        from urllib.parse import urlsplit

        host = (urlsplit(base_url).hostname or "").lower()
    except ValueError:
        host = ""
    if host == "api.deepseek.com":
        image_tokens = sum(
            deepseek_image_tokens(width, height)
            for width, height in work_dimensions
        )
    elif host == "api.xiaomimimo.com":
        image_tokens = sum(
            mimo_image_tokens(width, height)
            for width, height in work_dimensions
        )
    else:
        raise LocalAiInputTooLarge("不支持的视觉供应商")
    text_tokens = len((system_text + user_text).encode("utf-8"))
    total = image_tokens + text_tokens + CONTEXT_OUTPUT_RESERVE_TOKENS
    if total > CONTEXT_TOKEN_LIMIT:
        raise LocalAiInputTooLarge(
            "图文输入超过模型上下文，未创建任务",
            details={
                "estimated_tokens": total,
                "limit": CONTEXT_TOKEN_LIMIT,
                "image_tokens": image_tokens,
                "text_bytes": text_tokens,
                "reserve_tokens": CONTEXT_OUTPUT_RESERVE_TOKENS,
            },
        )
    return {
        "estimated_tokens": total,
        "image_tokens": image_tokens,
        "text_bytes": text_tokens,
        "reserve_tokens": CONTEXT_OUTPUT_RESERVE_TOKENS,
    }


def value_hash(value: Any) -> str:
    return _digest(value)


def _current_value(payload: dict[str, Any], target: str) -> Any:
    if target == "analysis_evaluation":
        evaluation = payload.get("analysis_evaluation") or {}
        return {
            key: (evaluation.get(key) or "") for key in EVALUATION_KEYS
        }
    return payload.get(target) or ""


def _send_photo(item: dict[str, Any]) -> dict[str, Any]:
    # Internal asset/derivative ids deliberately never enter this projection.
    return {
        "content_hash": item["content_hash"],
        "work_hash": item["work_hash"],
        "format": item["format"],
        "width": item["width"],
        "height": item["height"],
        "orientation": item.get("orientation"),
        "sort_order": item["sort_order"],
        "caption": item.get("caption"),
    }


def business_manifest(manifest: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Original-photo manifest accepted by the E01/E05 business hash."""
    return [
        {key: item.get(key) for key in PHOTO_MANIFEST_KEYS}
        for item in manifest
    ]


def _photo_manifest(
    session: Session,
    observation_id: str,
    manifest: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in manifest:
        asset = session.get(LocalObservationAsset, item["asset_id"])
        if asset is None or asset.observation_id != observation_id:
            raise LocalStorageError("观察照片来源缺失")
        derivative = session.scalars(
            select(LocalObservationAssetDerivative)
            .where(
                LocalObservationAssetDerivative.observation_id == observation_id,
                LocalObservationAssetDerivative.asset_id == asset.id,
                LocalObservationAssetDerivative.purpose == "ai",
            )
            .order_by(
                LocalObservationAssetDerivative.created_at.desc(),
                LocalObservationAssetDerivative.id.desc(),
            )
            .limit(1)
        ).first()
        if derivative is None:
            raise LocalStorageError("观察 AI 工作图缺失")
        if derivative.content_hash != item.get("work_hash", derivative.content_hash):
            raise LocalStorageError("观察 AI 工作图摘要不一致")
        result.append(
            {
                **dict(item),
                "work_hash": derivative.content_hash,
                "work_width": derivative.width,
                "work_height": derivative.height,
                "derivative_id": derivative.id,
                "params_version": derivative.params_version,
            }
        )
    return result


def load_current_ai_manifest(
    session: Session, *, profile_id: str, observation_id: str
) -> tuple[Any, Any, list[dict[str, Any]]]:
    record, draft, manifest = _load_current(session, profile_id, observation_id)
    return record, draft, _photo_manifest(session, observation_id, manifest)


@dataclass(frozen=True)
class ProjectedObservationInput:
    payload: dict[str, Any]
    dependencies: dict[str, Any]
    dependency_hash: str
    target_hashes: dict[str, str]
    photos: tuple[dict[str, Any], ...]
    missing_fields: tuple[str, ...]
    warnings: tuple[dict[str, str], ...]
    task_type: str
    target: str | None


def _build_send_payload(
    payload: dict[str, Any],
    manifest: list[dict[str, Any]],
    task_type: str,
    target: str | None,
    *,
    dependency_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    send: dict[str, Any] = {}
    for key in BASE_FIELDS:
        send[key] = payload.get(key)
    send["subjects"] = list(payload.get("subjects") or [])
    send["photos"] = [_send_photo(item) for item in manifest]

    if task_type == "game_observation_generate":
        for key in TARGETS:
            send[key] = _current_value(payload, key)
    else:
        if target not in TARGETS:
            raise LocalAiInputInvalid("重写目标不合法")
        send["target"] = target
        if target == "analysis_evaluation":
            send["analysis_evaluation"] = _current_value(payload, target)
        else:
            send["rewrite_source"] = _current_value(payload, target)
        for context in REWRITE_CONTEXT[target]:
            send[context] = _current_value(payload, context)
    if dependency_overrides:
        for key, value in dependency_overrides.items():
            send[key] = value
    return send


def project_input(
    session: Session,
    *,
    profile_id: str,
    observation_id: str,
    task_type: str,
    target: str | None = None,
    record: Any | None = None,
    draft: Any | None = None,
    manifest: list[dict[str, Any]] | None = None,
    dependency_overrides: dict[str, Any] | None = None,
) -> ProjectedObservationInput:
    if task_type not in OBSERVATION_TASK_TYPES:
        raise LocalAiInputInvalid("不支持的观察 AI 任务类型")
    if task_type == "game_observation_generate":
        if target is not None:
            raise LocalAiInputInvalid("生成任务不接受重写目标")
    elif target not in TARGETS:
        raise LocalAiInputInvalid("重写目标不合法")
    if record is None or draft is None or manifest is None:
        record, draft, manifest = load_current_ai_manifest(
            session, profile_id=profile_id, observation_id=observation_id
        )
    payload = dict(draft.payload_json or {})
    ready, required = ai_readiness(payload, valid_photo_count=len(manifest))
    if not ready:
        raise LocalAiInputInvalid(
            "观察 AI 输入未满足最低要求",
            details={"missing_fields": list(required)},
        )
    send = _build_send_payload(
        payload,
        manifest,
        task_type,
        target,
        dependency_overrides=dependency_overrides,
    )
    target_hashes = {
        key: value_hash(_current_value(payload, key))
        for key in (TARGETS if task_type == "game_observation_generate" else (target,))
    }
    return ProjectedObservationInput(
        payload=send,
        dependencies=send,
        dependency_hash=_digest(send),
        target_hashes=target_hashes,
        photos=tuple(manifest),
        missing_fields=missing_fields(payload),
        warnings=observation_warnings(payload),
        task_type=task_type,
        target=target,
    )


def input_photos(
    session: Session, input_row: LocalAIInput
) -> list[LocalObservationAIInputPhoto]:
    return list(
        session.scalars(
            select(LocalObservationAIInputPhoto)
            .where(LocalObservationAIInputPhoto.input_id == input_row.id)
            .order_by(LocalObservationAIInputPhoto.sort_order)
        ).all()
    )


def _data_url(media_type: str, raw: bytes) -> str:
    encoded = base64.b64encode(raw).decode("ascii")
    if len(encoded) != 4 * ((len(raw) + 2) // 3):
        raise LocalStorageError("工作图 Base64 长度不一致")
    return f"data:{media_type};base64,{encoded}"


def inspect_input_materials(
    session: Session,
    runtime: Any,
    *,
    observation_id: str,
    photos: list[Any],
) -> list[dict[str, Any]]:
    """Real original/work-image verification outside any write transaction.

    Returns stable file identities for the final short identity check.  The
    provider image bytes are not retained here.
    """
    result: list[dict[str, Any]] = []
    for row in photos:
        if isinstance(row, dict):
            asset_id = row["asset_id"]
            derivative_id = row["derivative_id"]
            content_hash = row.get("content_hash") or row.get("original_hash")
            work_hash = row["work_hash"]
        else:
            asset_id = row.asset_id
            derivative_id = row.derivative_id
            content_hash = row.original_hash
            work_hash = row.work_hash
        asset = session.get(LocalObservationAsset, asset_id)
        if asset is None or asset.observation_id != observation_id:
            raise LocalStorageError("观察原图来源缺失")
        derivative = session.get(LocalObservationAssetDerivative, derivative_id)
        if (
            derivative is None
            or derivative.observation_id != observation_id
            or derivative.asset_id != asset_id
            or derivative.purpose != "ai"
        ):
            raise LocalStorageError("观察 AI 工作图来源缺失")
        original_path = managed_asset_path(
            runtime, asset.relative_path, observation_id, asset_id
        )
        original = inspect_managed_asset(original_path, runtime.data_dir)
        if original.content_hash != content_hash:
            raise LocalStorageError("观察原图摘要不一致")
        work_path = managed_derivative_path(
            runtime, derivative.relative_path, observation_id, asset_id, derivative_id
        )
        work = inspect_managed_asset(work_path, runtime.data_dir)
        if work.content_hash != work_hash:
            raise LocalStorageError("观察 AI 工作图摘要不一致")
        result.append(
            {
                "asset_id": asset_id,
                "derivative_id": derivative_id,
                "original_identity": list(original.identity),
                "work_identity": list(work.identity),
            }
        )
    return result


def material_image_urls(
    session: Session,
    runtime: Any,
    *,
    profile_id: str,
    observation_id: str,
    photos: list[Any],
) -> tuple[list[str], int]:
    """Read verified AI derivatives outside the caller's write transaction.

    Count and per-image byte caps are checked before any read; the accumulated
    JSON image payload is bounded by the vision limits during the loop, so an
    over-budget request never accumulates all 600 work images in memory.
    """
    if not photos:
        raise LocalStorageError("观察 AI 输入没有照片")
    if len(photos) > ai_transport.VISION_MAX_IMAGES:
        raise LocalAiInputTooLarge(
            details={
                "image_count": len(photos),
                "limit": ai_transport.VISION_MAX_IMAGES,
            }
        )
    urls: list[str] = []
    total = 0
    image_json_bytes = 0
    for row in photos:
        if isinstance(row, dict):
            asset_id = row["asset_id"]
            derivative_id = row["derivative_id"]
            work_hash = row["work_hash"]
            content_hash = row.get("content_hash") or row.get("original_hash")
        else:
            asset_id = row.asset_id
            derivative_id = row.derivative_id
            work_hash = row.work_hash
            content_hash = row.original_hash
        asset = session.get(LocalObservationAsset, asset_id)
        if asset is None or asset.observation_id != observation_id:
            raise LocalStorageError("观察原图来源缺失")
        original_path = managed_asset_path(
            runtime, asset.relative_path, observation_id, asset_id
        )
        original = inspect_managed_asset(original_path, runtime.data_dir)
        if original.content_hash != content_hash:
            raise LocalStorageError("观察原图摘要不一致")
        raw = read_derivative_bytes(
            session,
            runtime,
            profile_id=profile_id,
            observation_id=observation_id,
            asset_id=asset_id,
            derivative_id=derivative_id,
            max_bytes=AI_TARGET_BYTES,
        )
        if not raw or hashlib.sha256(raw).hexdigest() != work_hash:
            raise LocalStorageError("观察 AI 工作图摘要不一致")
        url = _data_url("image/jpeg", raw)
        total += len(raw)
        urls.append(url)
        image_json_bytes += len(
            json.dumps(
                {"type": "image_url", "image_url": {"url": url}},
                ensure_ascii=False,
                separators=(",", ":"),
            )
        ) + 1
        if image_json_bytes > ai_transport.VISION_BODY_MAX_BYTES - 4096:
            raise LocalAiInputTooLarge(
                "AI 输入序列化后超过单次请求上限，未创建任务",
                details={
                    "image_json_bytes_lower_bound": image_json_bytes,
                    "limit": ai_transport.VISION_BODY_MAX_BYTES,
                },
            )
        if image_json_bytes > ai_transport.VISION_IPC_FRAME_MAX - 4096:
            raise LocalAiInputTooLarge(
                "AI 输入序列化后超过 IPC 帧上限，未创建任务",
                details={
                    "image_json_bytes_lower_bound": image_json_bytes,
                    "limit": ai_transport.VISION_IPC_FRAME_MAX,
                },
            )
    return urls, total


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
    synthetic: dict[str, Any] | None = None,
) -> list[bytes]:
    """Exact small-header + large-body frames for a vision claim.

    ``deadline_ms`` is part of the body metadata; a preflight uses a
    conservative maximum so the real frame can only be shorter.
    """
    vision_meta = {
        "protocol": ai_transport.VISION_PROTOCOL_ID,
        "schema_version": OBSERVATION_INPUT_SCHEMA_VERSION,
        "source_kind": "game_observation",
        "task_type": task_type,
        "contract_version": contract_version,
        "image_count": len(image_urls),
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
    body_raw = json.dumps(
        body, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    header = {
        "type": "bootstrap_header",
        "vision": True,
        **vision_meta,
        "frame_size": len(body_raw),
    }
    header_raw = json.dumps(header, separators=(",", ":")).encode("utf-8")
    return [header_raw, body_raw]


def preflight_vision_request(
    *,
    base_url: str,
    model: str,
    secret: str,
    system_text: str,
    user_text: str,
    image_urls: list[str],
    task_type: str = "game_observation_generate",
    contract_version: int = 1,
    work_dimensions: list[tuple[int, int]] | None = None,
) -> dict[str, int]:
    """Exact layered size check for a vision request and its IPC bootstrap."""
    if len(image_urls) > ai_transport.VISION_MAX_IMAGES:
        raise LocalAiInputTooLarge(
            details={
                "image_count": len(image_urls),
                "limit": ai_transport.VISION_MAX_IMAGES,
            }
        )
    if work_dimensions is not None:
        context = check_vision_context(
            base_url=base_url,
            model=model,
            system_text=system_text,
            user_text=user_text,
            work_dimensions=work_dimensions,
        )
    else:
        context = {}
    for url in image_urls:
        if not isinstance(url, str) or not url.startswith("data:image/"):
            raise LocalAiInputTooLarge("图片 data URL 非法")
    try:
        body = ai_transport.build_vision_request(
            model=model,
            system_text=system_text,
            user_text=user_text,
            image_urls=image_urls,
        )
    except ValueError as exc:
        raise LocalAiInputTooLarge("图片 data URL 非法") from exc
    total = ai_transport.build_http_request(
        base_url=base_url, secret=secret, body=body
    )
    # Conservative maximum deadline digits; the real claim uses a smaller
    # integer, so its complete frame cannot be longer than this preflight.
    frames = build_vision_frames(
        base_url=base_url,
        model=model,
        secret=secret,
        system_text=system_text,
        user_text=user_text,
        image_urls=image_urls,
        deadline_ms=9_999_999_999_999,
        task_type=task_type,
        contract_version=contract_version,
    )
    frame = sum(len(item) for item in frames)
    if len(body) > ai_transport.VISION_BODY_MAX_BYTES:
        raise LocalAiInputTooLarge(
            "AI 输入序列化后超过单次请求上限，未创建任务",
            details={
                "serialized_bytes": len(body),
                "limit": ai_transport.VISION_BODY_MAX_BYTES,
            },
        )
    if len(total) > ai_transport.VISION_HTTP_MAX_BYTES:
        raise LocalAiInputTooLarge(
            "AI 输入序列化后超过 HTTP 请求上限，未创建任务",
            details={
                "http_bytes": len(total),
                "limit": ai_transport.VISION_HTTP_MAX_BYTES,
            },
        )
    if frame > ai_transport.VISION_IPC_FRAME_MAX:
        raise LocalAiInputTooLarge(
            "AI 输入序列化后超过 IPC 帧上限，未创建任务",
            details={
                "frame_bytes": frame,
                "limit": ai_transport.VISION_IPC_FRAME_MAX,
            },
        )
    return {
        "body_bytes": len(body),
        "http_bytes": len(total),
        "frame_bytes": frame,
        "header_bytes": len(frames[0]),
        "image_count": len(image_urls),
        **context,
    }


__all__ = [
    "BASE_FIELDS",
    "CONTEXT_TOKEN_LIMIT",
    "CONTEXT_OUTPUT_RESERVE_TOKENS",
    "DEEPSEEK_IMAGE_TOKEN_CAP",
    "GENERATE_TARGETS",
    "MIMO_MAX_PIXELS",
    "MIMO_MIN_PIXELS",
    "MIMO_PATCH_SIZE",
    "MIMO_SPATIAL_MERGE",
    "OBSERVATION_INPUT_SCHEMA_VERSION",
    "OBSERVATION_TASK_TYPES",
    "ProjectedObservationInput",
    "REWRITE_CONTEXT",
    "TARGETS",
    "build_vision_frames",
    "business_manifest",
    "check_vision_context",
    "deepseek_image_tokens",
    "inspect_input_materials",
    "input_photos",
    "load_current_ai_manifest",
    "material_image_urls",
    "mimo_image_tokens",
    "preflight_vision_request",
    "project_input",
    "value_hash",
    "vision_capability",
]
