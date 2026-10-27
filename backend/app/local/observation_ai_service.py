"""E06/E07 observation AI execution, candidates and atomic adoption.

The daily task API remains daily-only.  Observation tasks live in the same AI
tables and executor, but use the versioned vision claim path and the frozen
observation bundles.  This module owns:

* freezing the actual send projection and ordered AI work-image references;
* submission receipts and the shared claim/material path;
* candidate chain validation, source-state classification and review hints;
* one-time adoption previews and the short atomic multi-target adoption.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ids import new_opaque_id
from app.local import ai_transport, observation_ai_inputs
from app.local.ai_config_service import _build_store, _decrypt_secret, _read_config
from app.local.ai_task_service import (
    LIVE_STATUSES,
    SUPPORTED_CONTRACT_VERSIONS,
    _current_prompt,
    _find_receipt,
    _fingerprint,
    _normalize_request_id,
    _profile_id,
    _render_system_text,
    _replay,
    _require_ai_ready,
    _store_receipt,
    require_task,
    task_out,
)
from app.local.base import utc_now
from app.local.errors import (
    LocalAiContractObsolete,
    LocalAiInputInvalid,
    LocalAiInputTooLarge,
    LocalAiNotFound,
    LocalAiNotConfigured,
    LocalAiPreviewExpired,
    LocalAiRequestConflict,
    LocalAiSourceChanged,
    LocalAiTargetChanged,
    LocalAiTaskActive,
    LocalPromptAdaptationRequired,
    LocalStorageError,
    LocalValidationError,
    LocalVersionConflict,
)
from app.local.models import (
    LocalAICandidate,
    LocalAIConfigVersion,
    LocalAICredential,
    LocalAIExecution,
    LocalAIInput,
    LocalAIOperation,
    LocalAIState,
    LocalAITask,
    LocalObservationAIInputPhoto,
    LocalObservationAIProvenance,
    LocalObservationAsset,
    LocalObservationAssetDerivative,
    LocalObservationDraft,
    LocalObservationOperation,
    LocalObservationRecord,
    LocalObservationVersion,
    LocalPersonalPromptHead,
    LocalPersonalPromptVersion,
    LocalPromptBundle,
)
from app.local.observation_ai_inputs import (
    OBSERVATION_INPUT_SCHEMA_VERSION,
    OBSERVATION_TASK_TYPES,
    TARGETS,
    business_manifest,
    inspect_input_materials,
    input_photos,
    load_current_ai_manifest,
    material_image_urls,
    preflight_vision_request,
    project_input,
    value_hash,
    vision_capability,
)
from app.local.observation_assets import (
    managed_asset_path,
    managed_derivative_path,
    verify_managed_asset_identity,
)
from app.local.observation_service import (
    _audit,
    _create_version,
    _fingerprint as _obs_fingerprint,
    _latest_version,
    _load_current,
    _operation,
    _projection,
    _receipt as _obs_receipt,
    _replay as _obs_replay,
)
from app.local.observation_validation import (
    EVALUATION_KEYS,
    aggregate_hash,
    canonical_json,
    normalize_payload,
)
from app.local.prompt_bundles import CandidateInvalid, validate_candidate, validate_input
from app.local.tx import begin_immediate, read_scope, rollback

OP_CREATE = "observation_ai_task_create"
OP_ADOPT = "observation_adopt_ai"
ADOPTION_TTL_SECONDS = 600
MAX_TOKENS = 64
REVIEW_DECISION = "adopt_reviewed"

_STATE_ELIGIBLE = "eligible"
_STATE_SOURCE_CHANGED = "source_changed"
_STATE_CONTRACT_OBSOLETE = "contract_obsolete"


# ---------------------------------------------------------------------------
# Bounded in-memory adoption tokens (never persisted)
# ---------------------------------------------------------------------------


class _TokenStore:
    def __init__(self) -> None:
        self._items: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
        self._lock = threading.Lock()

    def issue(self, payload: dict[str, Any], now: float) -> tuple[str, float]:
        token = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")
        expires_at = now + ADOPTION_TTL_SECONDS
        value = dict(payload)
        value["exp"] = expires_at
        with self._lock:
            while len(self._items) >= MAX_TOKENS:
                self._items.popitem(last=False)
            self._items[token] = {"payload": value, "reserved_by": None}
        return token, expires_at

    def get(self, token: Any) -> dict[str, Any] | None:
        if not isinstance(token, str) or not token:
            return None
        now = time.time()
        with self._lock:
            entry = self._items.get(token)
            if entry is None:
                return None
            if float(entry["payload"].get("exp", 0)) <= now:
                self._items.pop(token, None)
                return None
            return entry["payload"]

    def reserve(self, token: Any, request_id: str) -> dict[str, Any] | None:
        """Atomically bind a token to one request id before any DB write."""
        if not isinstance(token, str) or not token:
            return None
        now = time.time()
        with self._lock:
            entry = self._items.get(token)
            if entry is None:
                return None
            if float(entry["payload"].get("exp", 0)) <= now:
                self._items.pop(token, None)
                return None
            reserved = entry.get("reserved_by")
            if reserved is not None and reserved != request_id:
                return None
            entry["reserved_by"] = request_id
            return entry["payload"]

    def release(self, token: Any, request_id: str) -> None:
        if not isinstance(token, str):
            return
        with self._lock:
            entry = self._items.get(token)
            if entry is not None and entry.get("reserved_by") == request_id:
                entry["reserved_by"] = None

    def consume(self, token: Any) -> None:
        if isinstance(token, str):
            with self._lock:
                self._items.pop(token, None)

    def reset(self) -> None:
        with self._lock:
            self._items.clear()


_TOKENS = _TokenStore()


def reset_tokens() -> None:
    _TOKENS.reset()


# ---------------------------------------------------------------------------
# Source/material helpers
# ---------------------------------------------------------------------------


def revalidate_observation_source(session: Session, task: LocalAITask) -> bool:
    if task.source_kind != "game_observation" or task.observation_id is None:
        return False
    inp = session.get(LocalAIInput, task.input_id)
    if (
        inp is None
        or inp.source_kind != "game_observation"
        or inp.observation_id != task.observation_id
        or inp.profile_id != task.profile_id
        or inp.task_type != task.task_type
    ):
        return False
    record = session.get(LocalObservationRecord, task.observation_id)
    if record is None or record.creator_profile_id != task.profile_id:
        return False
    rows = input_photos(session, inp)
    if not rows:
        return False
    for row in rows:
        asset = session.get(LocalObservationAsset, row.asset_id)
        if asset is None or asset.observation_id != task.observation_id:
            return False
        derivative = session.get(LocalObservationAssetDerivative, row.derivative_id)
        if (
            derivative is None
            or derivative.observation_id != task.observation_id
            or derivative.asset_id != row.asset_id
            or derivative.purpose != "ai"
            or derivative.content_hash != row.work_hash
        ):
            return False
    return True


def _material_failure(exc: Exception) -> str:
    if isinstance(exc, LocalAiInputTooLarge):
        return "input_too_large"
    return "material_invalid"


def _photo_dicts(rows: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "asset_id": row.asset_id,
            "derivative_id": row.derivative_id,
            "original_hash": row.original_hash,
            "work_hash": row.work_hash,
        }
        for row in rows
    ]


def _material_union(
    input_rows: list[Any], current_manifest: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Frozen input photos plus every current draft photo, de-duplicated."""
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in input_rows:
        key = (row.asset_id, row.derivative_id)
        if key in seen:
            continue
        seen.add(key)
        result.append(
            {
                "asset_id": row.asset_id,
                "derivative_id": row.derivative_id,
                "original_hash": row.original_hash,
                "work_hash": row.work_hash,
            }
        )
    for item in current_manifest:
        key = (item["asset_id"], item["derivative_id"])
        if key in seen:
            continue
        seen.add(key)
        result.append(
            {
                "asset_id": item["asset_id"],
                "derivative_id": item["derivative_id"],
                "original_hash": item["content_hash"],
                "work_hash": item["work_hash"],
            }
        )
    return result


def _material_sources(photos: list[dict[str, Any]]) -> list[list[str]]:
    return [[item["asset_id"], item["derivative_id"]] for item in photos]


def _inspect_materials(
    session: Session,
    runtime: Any,
    *,
    observation_id: str,
    photos: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if runtime is None:
        raise LocalStorageError("材料核验运行时缺失")
    try:
        return inspect_input_materials(
            session,
            runtime,
            observation_id=observation_id,
            photos=photos,
        )
    except LocalStorageError:
        raise
    except Exception as exc:  # noqa: BLE001 - corrupt/missing material is not reviewable
        raise LocalStorageError("候选来源材料损坏") from exc


def _short_verify_materials(
    session: Session,
    runtime: Any,
    *,
    observation_id: str,
    identities: list[dict[str, Any]],
) -> None:
    if runtime is None:
        raise LocalStorageError("材料核验运行时缺失")
    for item in identities:
        asset = session.get(LocalObservationAsset, item["asset_id"])
        derivative = session.get(LocalObservationAssetDerivative, item["derivative_id"])
        if asset is None or derivative is None:
            raise LocalStorageError("候选来源材料缺失")
        try:
            verify_managed_asset_identity(
                managed_asset_path(
                    runtime, asset.relative_path, observation_id, asset.id
                ),
                runtime.data_dir,
                tuple(item["original_identity"]),
            )
            verify_managed_asset_identity(
                managed_derivative_path(
                    runtime,
                    derivative.relative_path,
                    observation_id,
                    asset.id,
                    derivative.id,
                ),
                runtime.data_dir,
                tuple(item["work_identity"]),
            )
        except LocalStorageError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise LocalStorageError("候选来源材料损坏") from exc


def load_observation_material(runtime: Any, pick: Any) -> tuple[dict[str, Any] | None, str | None]:
    """Claim phase 2 for observation tasks: DB rows, decrypt, image reads."""
    session = runtime.session()
    try:
        with read_scope(session):
            state = session.get(LocalAIState, _profile_id(session))
            if state is None:
                return None, "not_configured"
            config = session.get(
                LocalAIConfigVersion, (state.profile_id, pick.config_version)
            )
            credential = None
            if config is not None and config.credential_id is not None:
                credential = session.scalars(
                    select(LocalAICredential).where(
                        LocalAICredential.profile_id == state.profile_id,
                        LocalAICredential.id == config.credential_id,
                    )
                ).first()
            if config is None:
                return None, "not_configured"
            if (
                config.base_url is None
                or config.model is None
                or config.credential_id is None
                or credential is None
            ):
                return None, "not_configured"
            if pick.contract_version not in SUPPORTED_CONTRACT_VERSIONS:
                return None, "contract_unsupported"
            if not vision_capability(config.base_url, config.model):
                return None, "vision_model_unsupported"
            version = session.get(
                LocalPersonalPromptVersion,
                (state.profile_id, pick.task_type, pick.personal_revision),
            )
            bundle = session.get(
                LocalPromptBundle,
                (pick.task_type, pick.contract_version, pick.default_revision),
            )
            inp = session.get(LocalAIInput, pick.input_id)
            if version is None or bundle is None:
                return None, "prompt_missing"
            if version.contract_version != pick.contract_version:
                return None, "contract_unsupported"
            if inp is None or inp.observation_id != pick.observation_id:
                return None, "input_missing"
            if inp.input_schema_version != observation_ai_inputs.INTERNAL_INPUT_SCHEMA_VERSION:
                return None, "schema_unsupported"
            deps = dict(inp.dependencies_json or {})
            internal = deps.get("internal")
            if (
                not isinstance(internal, dict)
                or internal.get("internal_schema_version")
                != observation_ai_inputs.INTERNAL_INPUT_SCHEMA_VERSION
                or internal.get("wire_schema_version")
                != observation_ai_inputs.WIRE_INPUT_SCHEMA_VERSION
                or not isinstance(deps.get("wire"), dict)
            ):
                return None, "schema_unsupported"
            payload = dict(inp.payload_json or {})
            try:
                validate_input(inp.task_type, payload)
            except CandidateInvalid:
                return None, "input_invalid"
            profile_id = state.profile_id
            database_uuid = state.database_uuid
            base_url = config.base_url
            model = config.model
            credential_id = config.credential_id
            key_id = credential.key_id
            nonce = bytes(credential.nonce) if credential.nonce else None
            ciphertext = bytes(credential.ciphertext) if credential.ciphertext else None
            guidance = dict(version.guidance_json or {})
            output_schema = dict(bundle.output_schema_json or {})
            photo_rows = []
            for row in input_photos(session, inp):
                derivative = session.get(
                    LocalObservationAssetDerivative, row.derivative_id
                )
                if derivative is None:
                    return None, "material_invalid"
                photo_rows.append(
                    {
                        "asset_id": row.asset_id,
                        "derivative_id": row.derivative_id,
                        "work_hash": row.work_hash,
                        "content_hash": row.original_hash,
                        "work_width": derivative.width,
                        "work_height": derivative.height,
                    }
                )
            observation_id = inp.observation_id
            input_schema_version = inp.input_schema_version
    finally:
        session.close()

    if not photo_rows:
        return None, "material_invalid"
    if nonce is None or ciphertext is None or len(nonce) != 12:
        return None, "credential_unavailable"
    store = _build_store(profile_id, database_uuid, runtime.credential_root)
    if store is None:
        return None, "credential_unavailable"
    try:
        master_key = store.load_master_key(key_id)
        from app.local.credentials import SavedSecret

        secret = store.decrypt_secret(
            master_key,
            SavedSecret(key_id=key_id, nonce=nonce, ciphertext=ciphertext),
            profile_id,
            credential_id,
        )
    except Exception:  # noqa: BLE001
        return None, "credential_unavailable"

    system_text = _render_system_text(
        pick.task_type,
        pick.contract_version,
        output_schema,
        guidance,
        protocol=ai_transport.VISION_PROTOCOL_ID,
    )
    user_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    session = runtime.session()
    try:
        try:
            image_urls, _total = material_image_urls(
                session,
                runtime,
                profile_id=profile_id,
                observation_id=observation_id or "",
                photos=photo_rows,
            )
            preflight_vision_request(
                base_url=base_url,
                model=model,
                secret=secret,
                system_text=system_text,
                user_text=user_text,
                image_urls=image_urls,
                task_type=pick.task_type,
                contract_version=pick.contract_version,
                work_dimensions=[
                    (row["work_width"], row["work_height"]) for row in photo_rows
                ],
            )
        except Exception as exc:  # noqa: BLE001 - material failure is a pause
            return None, _material_failure(exc)
    finally:
        session.close()

    return {
        "base_url": base_url,
        "model": model,
        "secret": secret,
        "system_text": system_text,
        "payload": payload,
        "image_urls": image_urls,
        "config_version": pick.config_version,
        "personal_revision": pick.personal_revision,
        "contract_version": pick.contract_version,
        "default_revision": pick.default_revision,
        "attempt_budget_ms": ai_transport.VISION_ATTEMPT_BUDGET_MS,
        "vision_authorized": True,
        "vision_schema_version": input_schema_version,
        "vision_protocol": ai_transport.VISION_PROTOCOL_ID,
        "work_dimensions": tuple(
            (row["work_width"], row["work_height"]) for row in photo_rows
        ),
    }, None


def _validate_projected(projected: Any) -> None:
    try:
        validate_input(projected.task_type, projected.payload)
    except CandidateInvalid as exc:
        raise LocalAiInputInvalid("观察 AI 输入结构无效") from exc


def _internal_input_context(projected: Any) -> dict[str, Any]:
    return {
        "internal_schema_version": observation_ai_inputs.INTERNAL_INPUT_SCHEMA_VERSION,
        "wire_schema_version": observation_ai_inputs.WIRE_INPUT_SCHEMA_VERSION,
        "wire_projection": observation_ai_inputs.WIRE_PROJECTION_ID,
        "missing_fields": list(projected.missing_fields),
        "warnings": [dict(item) for item in projected.warnings],
        "photos": [
            {
                "asset_id": item["asset_id"],
                "derivative_id": item["derivative_id"],
                "params_version": item["params_version"],
                "work_width": item["work_width"],
                "work_height": item["work_height"],
                "work_hash": item["work_hash"],
                "original_hash": item["content_hash"],
            }
            for item in projected.photos
        ],
    }


def _preflight_observation_size(
    runtime: Any,
    session: Session,
    *,
    projected: Any,
    task_type: str,
    observation_id: str,
) -> None:
    with read_scope(session):
        state, config, _credential = _read_config(session)
        if state is None or config is None or config.base_url is None or config.model is None:
            raise LocalAiNotConfigured()
        if not vision_capability(config.base_url, config.model):
            raise LocalAiNotConfigured(details={"reason": "vision_model_unsupported"})
        head, version = _current_prompt(session, state.profile_id, task_type)
        if head is None or version is None:
            raise LocalStorageError("个人指导缺失")
        bundle = session.get(
            LocalPromptBundle,
            (task_type, version.contract_version, version.based_default_revision),
        )
        if bundle is None:
            raise LocalStorageError("提示词包缺失")
        guidance = dict(version.guidance_json or {})
        output_schema = dict(bundle.output_schema_json or {})
        profile_id = state.profile_id
        base_url = config.base_url
        model = config.model
    system_text = _render_system_text(
        task_type,
        version.contract_version,
        output_schema,
        guidance,
        protocol=ai_transport.VISION_PROTOCOL_ID,
    )
    image_urls, _total = material_image_urls(
        session,
        runtime,
        profile_id=profile_id,
        observation_id=observation_id,
        photos=list(projected.photos),
    )
    preflight_vision_request(
        base_url=base_url,
        model=model,
        secret="x" * 4096,  # conservative max header length
        system_text=system_text,
        user_text=json.dumps(projected.payload, ensure_ascii=False, separators=(",", ":")),
        image_urls=image_urls,
        task_type=task_type,
        contract_version=version.contract_version,
        work_dimensions=[
            (item["work_width"], item["work_height"])
            for item in projected.photos
        ],
    )


# ---------------------------------------------------------------------------
# Submission
# ---------------------------------------------------------------------------


def create_observation_task(
    session: Session,
    runtime: Any,
    *,
    profile_id: str,
    observation_id: str,
    task_type: str,
    expected_revision: Any,
    expected_hash: Any,
    target: Any = None,
    request_id: Any,
) -> tuple[dict[str, Any], bool]:
    if task_type not in OBSERVATION_TASK_TYPES:
        raise LocalValidationError("不支持的观察 AI 任务类型")
    if (
        not isinstance(expected_revision, int)
        or isinstance(expected_revision, bool)
        or expected_revision < 1
    ):
        raise LocalValidationError("expected_revision 必须是正整数")
    if not isinstance(expected_hash, str) or len(expected_hash) != 64:
        raise LocalValidationError("expected_hash 不合法")
    if task_type == "game_observation_generate":
        if target is not None:
            raise LocalValidationError("生成任务不接受 target")
    elif target not in TARGETS:
        raise LocalValidationError("重写目标不合法")
    rid = _normalize_request_id(request_id)
    fingerprint = _fingerprint(
        OP_CREATE,
        {
            "source_kind": "game_observation",
            "source_id": observation_id,
            "profile_id": profile_id,
            "observation_id": observation_id,
            "task_type": task_type,
            "expected_revision": expected_revision,
            "expected_hash": expected_hash,
            "target": target,
        },
    )
    with read_scope(session):
        receipt = _find_receipt(session, profile_id, rid)
    if receipt is not None:
        return _replay(receipt, OP_CREATE, fingerprint), False

    with read_scope(session):
        record, draft, manifest = load_current_ai_manifest(
            session, profile_id=profile_id, observation_id=observation_id
        )
        if draft.revision != expected_revision or draft.payload_hash != expected_hash:
            raise LocalVersionConflict(
                details={
                    "current_draft_revision": draft.revision,
                    "current_payload_hash": draft.payload_hash,
                }
            )
        projected = project_input(
            session,
            profile_id=profile_id,
            observation_id=observation_id,
            task_type=task_type,
            target=target,
            record=record,
            draft=draft,
            manifest=manifest,
        )
        _validate_projected(projected)
        _require_ai_ready(session, task_type)
    _preflight_observation_size(
        runtime,
        session,
        projected=projected,
        task_type=task_type,
        observation_id=observation_id,
    )

    now = utc_now()
    begin_immediate(session)
    try:
        receipt = _find_receipt(session, profile_id, rid)
        if receipt is not None:
            result = _replay(receipt, OP_CREATE, fingerprint)
            rollback(session)
            return result, False
        record, draft, manifest = load_current_ai_manifest(
            session, profile_id=profile_id, observation_id=observation_id
        )
        if draft.revision != expected_revision or draft.payload_hash != expected_hash:
            raise LocalVersionConflict(
                details={
                    "current_draft_revision": draft.revision,
                    "current_payload_hash": draft.payload_hash,
                }
            )
        active = session.scalars(
            select(LocalAITask).where(
                LocalAITask.profile_id == profile_id,
                LocalAITask.source_kind == "game_observation",
                LocalAITask.source_id == observation_id,
                LocalAITask.task_type == task_type,
                LocalAITask.status.in_(LIVE_STATUSES),
            )
        ).first()
        if active is not None:
            raise LocalAiTaskActive(details={"task_id": active.id})
        _require_ai_ready(session, task_type)
        projected = project_input(
            session,
            profile_id=profile_id,
            observation_id=observation_id,
            task_type=task_type,
            target=target,
            record=record,
            draft=draft,
            manifest=manifest,
        )
        _validate_projected(projected)
        input_id = new_opaque_id()
        session.add(
            LocalAIInput(
                id=input_id,
                profile_id=profile_id,
                source_kind="game_observation",
                source_id=observation_id,
                observation_id=observation_id,
                source_revision=draft.revision,
                daily_plan_id=None,
                content_id=None,
                content_version=None,
                task_type=task_type,
                target_grade=None,
                input_schema_version=observation_ai_inputs.INTERNAL_INPUT_SCHEMA_VERSION,
                payload_json=projected.payload,
                dependencies_json={
                    "wire": projected.dependencies,
                    "internal": _internal_input_context(projected),
                },
                dependency_hash=projected.dependency_hash,
                target_hashes_json=projected.target_hashes,
                created_at=now,
            )
        )
        session.flush()
        for item in projected.photos:
            session.add(
                LocalObservationAIInputPhoto(
                    id=new_opaque_id(),
                    profile_id=profile_id,
                    source_kind="game_observation",
                    source_id=observation_id,
                    observation_id=observation_id,
                    input_id=input_id,
                    asset_id=item["asset_id"],
                    derivative_id=item["derivative_id"],
                    sort_order=item["sort_order"],
                    caption=item.get("caption"),
                    original_hash=item["content_hash"],
                    work_hash=item["work_hash"],
                )
            )
        task = LocalAITask(
            id=new_opaque_id(),
            profile_id=profile_id,
            source_kind="game_observation",
            source_id=observation_id,
            observation_id=observation_id,
            daily_plan_id=None,
            task_type=task_type,
            input_id=input_id,
            status="pending",
            reason=None,
            current_execution_id=None,
            generation=0,
            runtime_meta_json={
                "processing_certainty": "not_sent",
                "user_stop_requested": False,
                "permit_revoked_at": None,
                "next_attempt_at": None,
            },
            created_at=now,
            updated_at=now,
        )
        session.add(task)
        session.flush()
        result = task_out(session, task)
        _store_receipt(
            session,
            profile_id=profile_id,
            request_id=rid,
            operation_kind=OP_CREATE,
            fingerprint=fingerprint,
            result=result,
        )
        session.commit()
        return result, True
    except IntegrityError as exc:
        rollback(session)
        raise LocalStorageError("观察 AI 任务写入失败") from exc
    except BaseException:
        rollback(session)
        raise


# ---------------------------------------------------------------------------
# Candidate reads and source state
# ---------------------------------------------------------------------------


def _candidate_row(
    session: Session, *, profile_id: str, observation_id: str, candidate_id: str
) -> LocalAICandidate:
    candidate = session.scalars(
        select(LocalAICandidate).where(
            LocalAICandidate.id == candidate_id,
            LocalAICandidate.profile_id == profile_id,
            LocalAICandidate.source_kind == "game_observation",
            LocalAICandidate.observation_id == observation_id,
        )
    ).first()
    if candidate is None:
        raise LocalAiNotFound("未找到该观察 AI 候选")
    return candidate


def _candidate_chain(
    session: Session,
    *,
    profile_id: str,
    observation_id: str,
    candidate_id: str,
) -> tuple[LocalAICandidate, dict[str, Any], LocalAIExecution, LocalAIInput]:
    candidate = _candidate_row(
        session,
        profile_id=profile_id,
        observation_id=observation_id,
        candidate_id=candidate_id,
    )
    try:
        raw = candidate.raw_candidate_json
    except ValueError:
        raise LocalStorageError("候选内容损坏") from None
    if not isinstance(raw, dict) or hashlib.sha256(
        canonical_json(raw).encode("utf-8")
    ).hexdigest() != candidate.candidate_hash:
        raise LocalStorageError("候选摘要与内容不一致")
    try:
        validated = validate_candidate(candidate.task_type, raw)
    except CandidateInvalid:
        raise LocalStorageError("候选结构损坏") from None
    if canonical_json(validated) != canonical_json(raw):
        raise LocalStorageError("候选结构损坏")
    execution = session.get(LocalAIExecution, candidate.execution_id)
    task = session.get(LocalAITask, candidate.task_id)
    inp = session.get(LocalAIInput, candidate.input_id)
    if execution is None or task is None or inp is None:
        raise LocalStorageError("候选关系链缺失")
    if (
        execution.state != "succeeded"
        or execution.profile_id != profile_id
        or execution.source_kind != "game_observation"
        or execution.observation_id != observation_id
        or execution.task_id != candidate.task_id
        or execution.input_id != candidate.input_id
        or execution.task_type != candidate.task_type
        or execution.contract_version != candidate.contract_version
    ):
        raise LocalStorageError("候选执行与候选不一致")
    if (
        task.status != "succeeded"
        or task.profile_id != profile_id
        or task.source_kind != "game_observation"
        or task.observation_id != observation_id
        or task.input_id != candidate.input_id
        or task.task_type != candidate.task_type
    ):
        raise LocalStorageError("候选任务与候选不一致")
    if (
        inp.profile_id != profile_id
        or inp.source_kind != "game_observation"
        or inp.observation_id != observation_id
        or inp.task_type != candidate.task_type
        or inp.input_schema_version != candidate.schema_version
        or candidate.schema_version
        != observation_ai_inputs.INTERNAL_INPUT_SCHEMA_VERSION
        or not input_photos(session, inp)
    ):
        raise LocalStorageError("候选输入来源关系损坏")
    deps = dict(inp.dependencies_json or {})
    internal = deps.get("internal")
    if (
        not isinstance(internal, dict)
        or internal.get("internal_schema_version")
        != observation_ai_inputs.INTERNAL_INPUT_SCHEMA_VERSION
        or internal.get("wire_schema_version")
        != observation_ai_inputs.WIRE_INPUT_SCHEMA_VERSION
    ):
        raise LocalStorageError("候选输入 schema 不一致")
    return candidate, validated, execution, inp


def _available_targets(task_type: str, raw: dict[str, Any]) -> list[str]:
    if task_type == "game_observation_generate":
        return list(TARGETS)
    target = raw.get("target")
    return [target] if target in TARGETS else []


def _candidate_value(raw: dict[str, Any], task_type: str, target: str) -> Any:
    if task_type == "game_observation_generate":
        value = raw.get(target)
    elif target == "analysis_evaluation":
        value = raw.get("analysis_evaluation")
    else:
        value = raw.get("text")
    if target == "analysis_evaluation":
        if not isinstance(value, dict):
            raise LocalStorageError("候选评价分析损坏")
        return {key: (value.get(key) or "") for key in EVALUATION_KEYS}
    if not isinstance(value, str):
        raise LocalStorageError("候选正文损坏")
    return value


def _target_value(payload: dict[str, Any], target: str) -> Any:
    if target == "analysis_evaluation":
        evaluation = payload.get("analysis_evaluation") or {}
        return {key: (evaluation.get(key) or "") for key in EVALUATION_KEYS}
    return payload.get(target) or ""


def _target_hashes(payload: dict[str, Any]) -> dict[str, str]:
    return {target: value_hash(_target_value(payload, target)) for target in TARGETS}


def _contract_required(session: Session, profile_id: str, task_type: str) -> int:
    head = session.get(LocalPersonalPromptHead, (profile_id, task_type))
    if head is None:
        raise LocalStorageError("个人指导缺失")
    return head.required_contract_version


def _contract_adoptable(
    session: Session, profile_id: str, candidate: LocalAICandidate
) -> bool:
    if candidate.contract_version not in SUPPORTED_CONTRACT_VERSIONS:
        return False
    return _contract_required(session, profile_id, candidate.task_type) == candidate.contract_version


def _provenance_row(
    session: Session,
    *,
    observation_id: str,
    version: int,
    candidate_id: str,
) -> LocalObservationAIProvenance | None:
    return session.scalars(
        select(LocalObservationAIProvenance).where(
            LocalObservationAIProvenance.observation_id == observation_id,
            LocalObservationAIProvenance.version == version,
            LocalObservationAIProvenance.candidate_id == candidate_id,
        )
    ).first()


def _operation_owners(
    session: Session, *, profile_id: str, observation_id: str
) -> tuple[dict[str, str | None], dict[str, str]]:
    """Replay committed content operations into per-target ownership.

    Operations are only the invalidation/order spine; an adoption is trusted
    only when its immutable provenance row for the resulting version matches
    the candidate, target hashes, input hash and output hash.  SQLite ``rowid``
    is the insertion order (all observation writes are serialized), avoiding
    clock rollback and random-id ordering.
    """
    from sqlalchemy import text

    owners: dict[str, str | None] = {target: None for target in TARGETS}
    hashes: dict[str, str] = {}
    rows = session.scalars(
        select(LocalObservationOperation)
        .where(
            LocalObservationOperation.profile_id == profile_id,
            LocalObservationOperation.observation_id == observation_id,
        )
        .order_by(text("rowid"))
    ).all()
    for row in rows:
        result = dict(row.result_json or {})
        new_hashes = result.get("target_hashes")
        kind = row.operation_kind
        if kind not in (
            "observation_create",
            "observation_save",
            "observation_restore",
            "observation_adopt_ai",
        ):
            continue
        if kind == "observation_create":
            for target in TARGETS:
                owners[target] = None
            if isinstance(new_hashes, dict):
                hashes = {t: str(new_hashes[t]) for t in TARGETS if t in new_hashes}
            continue
        if not isinstance(new_hashes, dict):
            # Older receipts without target hashes cannot prove a target's
            # current source; conservatively drop all ownership.
            for target in TARGETS:
                owners[target] = None
            continue
        if kind == "observation_restore":
            for target in TARGETS:
                owners[target] = None
        elif kind == "observation_adopt_ai":
            candidate_id = result.get("candidate_id")
            selected = result.get("selected_targets")
            version = result.get("result_version") or result.get("current_version")
            provenance = None
            if (
                isinstance(candidate_id, str)
                and isinstance(version, int)
                and isinstance(selected, list)
            ):
                provenance = _provenance_row(
                    session,
                    observation_id=observation_id,
                    version=version,
                    candidate_id=candidate_id,
                )
            for target in selected if isinstance(selected, list) else []:
                if target not in TARGETS:
                    continue
                trusted = False
                if provenance is not None and isinstance(
                    provenance.adopted_targets_json, dict
                ):
                    meta = provenance.adopted_targets_json.get(target)
                    if (
                        isinstance(meta, dict)
                        and meta.get("candidate_id") == candidate_id
                        and meta.get("output_hash") == new_hashes.get(target)
                        and provenance.input_hash == result.get("input_hash")
                        and provenance.output_hash == result.get("output_hash")
                    ):
                        trusted = True
                owners[target] = candidate_id if trusted else None
        else:  # save/auto/manual/leave/pre_restore/pre_export
            for target in TARGETS:
                new_hash = new_hashes.get(target)
                if not isinstance(new_hash, str):
                    owners[target] = None
                elif target in hashes and hashes[target] != new_hash:
                    owners[target] = None
        for target in TARGETS:
            if isinstance(new_hashes.get(target), str):
                hashes[target] = str(new_hashes[target])
    return owners, hashes


def _latest_target_hash(
    session: Session, *, observation_id: str, target: str
) -> str | None:
    latest = _latest_version(session, observation_id)
    if latest is None:
        return None
    return value_hash(_target_value(dict(latest.payload_json or {}), target))


def _ever_adopted_targets(
    session: Session, *, observation_id: str, candidate_id: str
) -> set[str]:
    result: set[str] = set()
    rows = session.scalars(
        select(LocalObservationAIProvenance).where(
            LocalObservationAIProvenance.observation_id == observation_id,
            LocalObservationAIProvenance.candidate_id == candidate_id,
        )
    ).all()
    for row in rows:
        if isinstance(row.adopted_targets_json, dict):
            result.update(
                target
                for target in row.adopted_targets_json
                if target in TARGETS
            )
    return result


def _trusted_overrides(
    session: Session,
    *,
    profile_id: str,
    observation_id: str,
    candidate: LocalAICandidate,
    input_row: LocalAIInput,
    current_payload: dict[str, Any],
) -> dict[str, Any]:
    owners, hashes = _operation_owners(
        session, profile_id=profile_id, observation_id=observation_id
    )
    raw = candidate.raw_candidate_json
    if not isinstance(raw, dict):
        return {}
    overrides: dict[str, Any] = {}
    input_payload = dict(input_row.payload_json or {})
    rewrite_target = input_payload.get("target")
    for target in TARGETS:
        if owners.get(target) != candidate.id:
            continue
        current_hash = value_hash(_target_value(current_payload, target))
        candidate_hash = value_hash(
            _candidate_value(raw, candidate.task_type, target)
        )
        if hashes.get(target) != current_hash or current_hash != candidate_hash:
            continue
        if candidate.task_type == "game_observation_generate":
            if target in input_payload:
                overrides[target] = input_payload[target]
        elif target == rewrite_target:
            if target == "analysis_evaluation":
                if "analysis_evaluation" in input_payload:
                    overrides["analysis_evaluation"] = input_payload["analysis_evaluation"]
            elif "rewrite_source" in input_payload:
                overrides["rewrite_source"] = input_payload["rewrite_source"]
        elif target in input_payload:
            overrides[target] = input_payload[target]
    return overrides


def _source_state(
    session: Session,
    *,
    profile_id: str,
    observation_id: str,
    candidate: LocalAICandidate,
    input_row: LocalAIInput,
    record: LocalObservationRecord,
    draft: LocalObservationDraft,
    manifest: list[dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    if not _contract_adoptable(session, profile_id, candidate):
        return _STATE_CONTRACT_OBSOLETE, {}
    payload = dict(draft.payload_json or {})
    target = input_row.payload_json.get("target") if isinstance(input_row.payload_json, dict) else None
    try:
        projected = project_input(
            session,
            profile_id=profile_id,
            observation_id=observation_id,
            task_type=candidate.task_type,
            target=target,
            record=record,
            draft=draft,
            manifest=manifest,
        )
    except Exception:  # noqa: BLE001 - not projectable is a source change
        return _STATE_SOURCE_CHANGED, {"changed_fields": ["source"]}
    if projected.dependency_hash == input_row.dependency_hash:
        return _STATE_ELIGIBLE, {}
    overrides = _trusted_overrides(
        session,
        profile_id=profile_id,
        observation_id=observation_id,
        candidate=candidate,
        input_row=input_row,
        current_payload=payload,
    )
    if overrides:
        try:
            trusted = project_input(
                session,
                profile_id=profile_id,
                observation_id=observation_id,
                task_type=candidate.task_type,
                target=target,
                record=record,
                draft=draft,
                manifest=manifest,
                dependency_overrides=overrides,
            )
        except Exception:  # noqa: BLE001
            trusted = None
        if trusted is not None and trusted.dependency_hash == input_row.dependency_hash:
            return _STATE_ELIGIBLE, {}
    old = dict(input_row.payload_json or {})
    changed = sorted(
        key
        for key in set(projected.dependencies) | set(old)
        if canonical_json(projected.dependencies.get(key)) != canonical_json(old.get(key))
    )
    return _STATE_SOURCE_CHANGED, {"changed_fields": changed[:32] or ["dependency_hash"]}


DEFAULT_REVIEW_WARNING = {
    "code": "ai_supplemented_details",
    "message": "候选中的对话、动作衔接等细节可能由 AI 补写，请结合观察核对；提示只在审核区显示，不进入正文。",
}
REVIEW_METADATA_VERSION = 1
REVIEW_METADATA_PREFIX = "cr:"
REVIEW_MAX_FRAGMENTS = 64
REVIEW_MAX_FRAGMENT_CHARS = 200
REVIEW_MAX_METADATA_BYTES = 64 * 1024


def _extract_fragments(
    raw: dict[str, Any], task_type: str
) -> tuple[list[dict[str, Any]], bool]:
    fragments: list[dict[str, Any]] = []
    total_bytes = 0
    for target in _available_targets(task_type, raw):
        values: list[tuple[str | None, str]] = []
        if target == "analysis_evaluation":
            evaluation = raw.get("analysis_evaluation")
            if isinstance(evaluation, dict):
                values = [
                    (domain, evaluation.get(domain) or "")
                    for domain in EVALUATION_KEYS
                ]
        else:
            value = _candidate_value(raw, task_type, target)
            values = [(None, value)]
        for domain, text in values:
            for match in re.finditer(
                rf"[“\"]([^”\"]{{1,{REVIEW_MAX_FRAGMENT_CHARS}}})[”\"]", text
            ):
                if len(fragments) >= REVIEW_MAX_FRAGMENTS:
                    return fragments, True
                fragment = match.group(1)
                start, end = match.span(1)
                if text[start:end] != fragment:
                    continue
                item = {
                    "target": target,
                    "domain": domain,
                    "start": start,
                    "end": end,
                    "text": fragment,
                    "hash": value_hash(fragment),
                }
                encoded = len(
                    json.dumps(item, ensure_ascii=False).encode("utf-8")
                )
                if total_bytes + encoded > REVIEW_MAX_METADATA_BYTES:
                    return fragments, True
                fragments.append(item)
                total_bytes += encoded
    return fragments, False


def candidate_review_metadata(
    candidate: LocalAICandidate, raw: dict[str, Any]
) -> dict[str, Any]:
    fragments, truncated = _extract_fragments(raw, candidate.task_type)
    return {
        "version": REVIEW_METADATA_VERSION,
        "candidate_id": candidate.id,
        "candidate_hash": candidate.candidate_hash,
        "task_type": candidate.task_type,
        "contract_version": candidate.contract_version,
        "schema_version": candidate.schema_version,
        "target_hashes": {
            target: value_hash(_candidate_value(raw, candidate.task_type, target))
            for target in _available_targets(candidate.task_type, raw)
        },
        "warning": DEFAULT_REVIEW_WARNING,
        "fragments": fragments,
        "fragments_truncated": truncated,
    }


def store_candidate_review_metadata(
    session: Session, candidate: LocalAICandidate, raw: dict[str, Any]
) -> None:
    metadata = candidate_review_metadata(candidate, raw)
    request_id = REVIEW_METADATA_PREFIX + candidate.id
    existing = session.scalars(
        select(LocalAIOperation).where(
            LocalAIOperation.profile_id == candidate.profile_id,
            LocalAIOperation.request_id == request_id,
        )
    ).first()
    if existing is not None:
        if existing.operation_kind != "observation_ai_candidate_review" or dict(
            existing.result_json or {}
        ) != metadata:
            raise LocalStorageError("候选审核元数据冲突")
        return
    fingerprint = hashlib.sha256(
        canonical_json(metadata).encode("utf-8")
    ).hexdigest()
    session.add(
        LocalAIOperation(
            id=new_opaque_id(),
            profile_id=candidate.profile_id,
            request_id=request_id,
            operation_kind="observation_ai_candidate_review",
            request_fingerprint=fingerprint,
            fingerprint_kind="sha256",
            fingerprint_key_id=None,
            result_json=metadata,
            created_at=utc_now(),
        )
    )


def _read_review_metadata(
    session: Session, *, profile_id: str, candidate: LocalAICandidate
) -> dict[str, Any] | None:
    try:
        row = session.scalars(
            select(LocalAIOperation).where(
                LocalAIOperation.profile_id == profile_id,
                LocalAIOperation.request_id == REVIEW_METADATA_PREFIX + candidate.id,
                LocalAIOperation.operation_kind == "observation_ai_candidate_review",
            )
        ).first()
        if row is None or not isinstance(row.result_json, dict):
            return None
        metadata = dict(row.result_json)
        if len(canonical_json(metadata).encode("utf-8")) > (
            REVIEW_MAX_METADATA_BYTES * 2
        ):
            return None
    except (ValueError, TypeError):
        return None
    if (
        metadata.get("version") != REVIEW_METADATA_VERSION
        or metadata.get("candidate_id") != candidate.id
        or metadata.get("candidate_hash") != candidate.candidate_hash
        or metadata.get("task_type") != candidate.task_type
        or metadata.get("contract_version") != candidate.contract_version
        or metadata.get("schema_version") != candidate.schema_version
    ):
        return None
    return metadata


def _validated_review_hints(
    raw: dict[str, Any],
    task_type: str,
    selected: list[str],
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    warning = DEFAULT_REVIEW_WARNING
    if metadata is None:
        return {
            "warning": warning,
            "fragments": [],
            "fragments_truncated": False,
        }
    candidate_warning = metadata.get("warning")
    if (
        isinstance(candidate_warning, dict)
        and candidate_warning.get("code") == DEFAULT_REVIEW_WARNING["code"]
        and isinstance(candidate_warning.get("message"), str)
    ):
        warning = {
            "code": DEFAULT_REVIEW_WARNING["code"],
            "message": candidate_warning["message"],
        }
    fragments: list[dict[str, Any]] = []
    total_bytes = 0
    truncated = bool(metadata.get("fragments_truncated"))
    for item in metadata.get("fragments") or []:
        if len(fragments) >= REVIEW_MAX_FRAGMENTS:
            truncated = True
            break
        if not isinstance(item, dict):
            continue
        target = item.get("target")
        domain = item.get("domain")
        start, end = item.get("start"), item.get("end")
        text, digest = item.get("text"), item.get("hash")
        if target not in selected or not isinstance(text, str):
            continue
        if not isinstance(start, int) or isinstance(start, bool):
            continue
        if not isinstance(end, int) or isinstance(end, bool):
            continue
        if not isinstance(digest, str) or value_hash(text) != digest:
            continue
        try:
            value = _candidate_value(raw, task_type, target)
        except LocalStorageError:
            continue
        if target == "analysis_evaluation":
            if domain not in EVALUATION_KEYS or not isinstance(value, dict):
                continue
            value = value.get(domain) or ""
        if not isinstance(value, str):
            continue
        if not (0 <= start <= end <= len(value)) or value[start:end] != text:
            continue
        fragment = {
            "target": target,
            "domain": domain,
            "start": start,
            "end": end,
            "text": text,
            "hash": digest,
        }
        encoded = len(json.dumps(fragment, ensure_ascii=False).encode("utf-8"))
        if total_bytes + encoded > REVIEW_MAX_METADATA_BYTES:
            truncated = True
            break
        fragments.append(fragment)
        total_bytes += encoded
    return {
        "warning": warning,
        "fragments": fragments,
        "fragments_truncated": truncated,
    }


def _review_hints(
    session: Session,
    *,
    profile_id: str,
    candidate: LocalAICandidate,
    raw: dict[str, Any],
    selected: list[str],
) -> dict[str, Any]:
    return _validated_review_hints(
        raw,
        candidate.task_type,
        selected,
        _read_review_metadata(session, profile_id=profile_id, candidate=candidate),
    )


def candidate_summary(
    session: Session,
    *,
    profile_id: str,
    observation_id: str,
    candidate: LocalAICandidate,
    raw: dict[str, Any],
    input_row: LocalAIInput,
    record: LocalObservationRecord,
    draft: LocalObservationDraft,
    manifest: list[dict[str, Any]],
) -> dict[str, Any]:
    state, diff = _source_state(
        session,
        profile_id=profile_id,
        observation_id=observation_id,
        candidate=candidate,
        input_row=input_row,
        record=record,
        draft=draft,
        manifest=manifest,
    )
    available = _available_targets(candidate.task_type, raw)
    metadata = _read_review_metadata(
        session, profile_id=profile_id, candidate=candidate
    )
    hints = _validated_review_hints(
        raw, candidate.task_type, available, metadata
    )
    return {
        "id": candidate.id,
        "observation_id": observation_id,
        "task_id": candidate.task_id,
        "execution_id": candidate.execution_id,
        "task_type": candidate.task_type,
        "contract_version": candidate.contract_version,
        "schema_version": candidate.schema_version,
        "candidate_hash": candidate.candidate_hash,
        "available_targets": available,
        "target_hashes": {
            target: value_hash(_candidate_value(raw, candidate.task_type, target))
            for target in available
        },
        "review_metadata_version": (
            metadata.get("version") if metadata is not None else None
        ),
        "review_warning": hints["warning"],
        "review_fragments": hints["fragments"],
        "review_fragments_truncated": hints["fragments_truncated"],
        "adoption_state": state,
        "source_change": diff,
        "created_at": candidate.created_at.isoformat() if candidate.created_at else None,
    }


def get_candidate(
    session: Session,
    *,
    profile_id: str,
    observation_id: str,
    candidate_id: str,
) -> dict[str, Any]:
    with read_scope(session):
        record, draft, manifest = load_current_ai_manifest(
            session, profile_id=profile_id, observation_id=observation_id
        )
        candidate, raw, _execution, inp = _candidate_chain(
            session,
            profile_id=profile_id,
            observation_id=observation_id,
            candidate_id=candidate_id,
        )
        detail = candidate_summary(
            session,
            profile_id=profile_id,
            observation_id=observation_id,
            candidate=candidate,
            raw=raw,
            input_row=inp,
            record=record,
            draft=draft,
            manifest=manifest,
        )
        detail["raw_candidate"] = raw
        deps = dict(inp.dependencies_json or {})
        internal = dict(deps.get("internal") or {})
        detail["source"] = {
            "source_revision": inp.source_revision,
            "dependency_hash": inp.dependency_hash,
            "dependencies": dict(deps.get("wire") or {}),
            "internal_context": {
                "internal_schema_version": internal.get("internal_schema_version"),
                "wire_schema_version": internal.get("wire_schema_version"),
                "wire_projection": internal.get("wire_projection"),
                "missing_fields": list(internal.get("missing_fields") or []),
                "warnings": list(internal.get("warnings") or []),
            },
        }
        return detail


def list_candidates(
    session: Session,
    *,
    profile_id: str,
    observation_id: str,
    limit: int = 20,
) -> dict[str, Any]:
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
        raise LocalValidationError("limit 必须在 1–100 之间")
    with read_scope(session):
        record, draft, manifest = load_current_ai_manifest(
            session, profile_id=profile_id, observation_id=observation_id
        )
        rows = session.scalars(
            select(LocalAICandidate)
            .where(
                LocalAICandidate.profile_id == profile_id,
                LocalAICandidate.source_kind == "game_observation",
                LocalAICandidate.observation_id == observation_id,
            )
            .order_by(LocalAICandidate.created_at, LocalAICandidate.id)
            .limit(limit)
        ).all()
        items = []
        for candidate in rows:
            _c, raw, _execution, inp = _candidate_chain(
                session,
                profile_id=profile_id,
                observation_id=observation_id,
                candidate_id=candidate.id,
            )
            items.append(
                candidate_summary(
                    session,
                    profile_id=profile_id,
                    observation_id=observation_id,
                    candidate=candidate,
                    raw=raw,
                    input_row=inp,
                    record=record,
                    draft=draft,
                    manifest=manifest,
                )
            )
        return {"items": items, "next_cursor": None}


# ---------------------------------------------------------------------------
# Preview / adopt
# ---------------------------------------------------------------------------


def _validate_targets(raw: dict[str, Any], task_type: str, selected: Any) -> list[str]:
    available = _available_targets(task_type, raw)
    if not isinstance(selected, list) or not selected:
        raise LocalValidationError("必须选择至少一个目标")
    result: list[str] = []
    for target in selected:
        if target not in available or target in result:
            raise LocalValidationError("目标集合不合法")
        result.append(target)
    if task_type == "game_observation_rewrite" and result != available:
        raise LocalValidationError("单栏重写只能采用其目标")
    return result


def _now_iso(expires: float) -> str:
    return datetime.fromtimestamp(expires, tz=timezone.utc).isoformat()


def preview_adoption(
    session: Session,
    runtime: Any,
    *,
    profile_id: str,
    observation_id: str,
    candidate_id: str,
    expected_revision: Any,
    expected_hash: Any,
    selected_targets: Any,
    request_id: Any,
) -> dict[str, Any]:
    if (
        not isinstance(expected_revision, int)
        or isinstance(expected_revision, bool)
        or expected_revision < 1
    ):
        raise LocalValidationError("expected_revision 必须是正整数")
    if not isinstance(expected_hash, str) or len(expected_hash) != 64:
        raise LocalValidationError("expected_hash 不合法")
    rid = _normalize_request_id(request_id)
    with read_scope(session):
        record, draft, manifest = load_current_ai_manifest(
            session, profile_id=profile_id, observation_id=observation_id
        )
        if draft.revision != expected_revision or draft.payload_hash != expected_hash:
            raise LocalVersionConflict(
                details={
                    "current_draft_revision": draft.revision,
                    "current_payload_hash": draft.payload_hash,
                }
            )
        candidate, raw, _execution, inp = _candidate_chain(
            session,
            profile_id=profile_id,
            observation_id=observation_id,
            candidate_id=candidate_id,
        )
        selected = _validate_targets(raw, candidate.task_type, selected_targets)
        state, diff = _source_state(
            session,
            profile_id=profile_id,
            observation_id=observation_id,
            candidate=candidate,
            input_row=inp,
            record=record,
            draft=draft,
            manifest=manifest,
        )
        if state == _STATE_CONTRACT_OBSOLETE:
            raise LocalAiContractObsolete()
        current_payload = dict(draft.payload_json or {})
        before = {target: _target_value(current_payload, target) for target in selected}
        after = {
            target: _candidate_value(raw, candidate.task_type, target)
            for target in selected
        }
        before_hashes = {target: value_hash(before[target]) for target in selected}
        after_hashes = {target: value_hash(after[target]) for target in selected}
        current_dependency_hash = project_input(
            session,
            profile_id=profile_id,
            observation_id=observation_id,
            task_type=candidate.task_type,
            target=inp.payload_json.get("target")
            if isinstance(inp.payload_json, dict)
            else None,
            record=record,
            draft=draft,
            manifest=manifest,
        ).dependency_hash
        hints = _review_hints(
            session,
            profile_id=profile_id,
            candidate=candidate,
            raw=raw,
            selected=selected,
        )
        photo_dicts = _material_union(input_photos(session, inp), manifest)
    identities = _inspect_materials(
        session,
        runtime,
        observation_id=observation_id,
        photos=photo_dicts,
    )
    now = time.time()
    payload = {
        "v": 1,
        "profile_id": profile_id,
        "observation_id": observation_id,
        "candidate_id": candidate.id,
        "candidate_hash": candidate.candidate_hash,
        "task_type": candidate.task_type,
        "contract_version": candidate.contract_version,
        "targets": selected,
        "draft_revision": draft.revision,
        "draft_hash": draft.payload_hash,
        "dependency_hash": current_dependency_hash,
        "input_dependency_hash": inp.dependency_hash,
        "before_hashes": before_hashes,
        "after_hashes": after_hashes,
        "source_state": state,
        "diff_hash": value_hash(diff),
        "request_id": rid,
        "material_identities": identities,
        "material_sources": _material_sources(photo_dicts),
    }
    token, expires = _TOKENS.issue(payload, now)
    return {
        "adoption_token": token,
        "expires_at": _now_iso(expires),
        "observation_id": observation_id,
        "candidate_id": candidate.id,
        "candidate_hash": candidate.candidate_hash,
        "draft_revision": draft.revision,
        "draft_hash": draft.payload_hash,
        "selected_targets": selected,
        "before": before,
        "after": after,
        "changed": any(before[target] != after[target] for target in selected),
        "source_state": state,
        "requires_review_decision": state == _STATE_SOURCE_CHANGED,
        "allowed_review_decisions": (
            [REVIEW_DECISION] if state == _STATE_SOURCE_CHANGED else []
        ),
        "diff": diff,
        "warning": hints["warning"],
        "fragments": hints["fragments"],
        "fragments_truncated": hints["fragments_truncated"],
        "request_id": rid,
    }


def _receipt_replay(session: Session, profile_id: str, rid: str, fingerprint: str):
    with read_scope(session):
        receipt = _obs_receipt(session, profile_id, rid)
    if receipt is None:
        return None
    return _obs_replay(session, profile_id, rid, fingerprint)


def adopt(
    session: Session,
    runtime: Any,
    *,
    profile_id: str,
    observation_id: str,
    candidate_id: str,
    expected_revision: Any,
    expected_hash: Any,
    selected_targets: Any,
    preview_token: Any,
    request_id: Any,
    review_decision: Any = None,
) -> dict[str, Any]:
    if (
        not isinstance(expected_revision, int)
        or isinstance(expected_revision, bool)
        or expected_revision < 1
    ):
        raise LocalValidationError("expected_revision 必须是正整数")
    if not isinstance(expected_hash, str) or len(expected_hash) != 64:
        raise LocalValidationError("expected_hash 不合法")
    if review_decision not in (None, REVIEW_DECISION):
        raise LocalValidationError("review_decision 不合法")
    rid = _normalize_request_id(request_id)
    token_str = preview_token if isinstance(preview_token, str) else ""
    if not token_str:
        raise LocalValidationError("preview_token 必须是字符串")
    fingerprint = _obs_fingerprint(
        OP_ADOPT,
        {
            "profile_id": profile_id,
            "observation_id": observation_id,
            "candidate_id": candidate_id,
            "expected_revision": expected_revision,
            "expected_hash": expected_hash,
            "selected_targets": selected_targets,
            "preview_token": token_str,
            "review_decision": review_decision,
        },
    )
    replayed = _receipt_replay(session, profile_id, rid, fingerprint)
    if replayed is not None:
        return replayed
    payload = _TOKENS.reserve(token_str, rid)
    if payload is None:
        replayed = _receipt_replay(session, profile_id, rid, fingerprint)
        if replayed is not None:
            return replayed
        raise LocalAiPreviewExpired(details={"reason": "unknown_or_expired"})
    if (
        payload.get("profile_id") != profile_id
        or payload.get("observation_id") != observation_id
        or payload.get("candidate_id") != candidate_id
        or payload.get("draft_revision") != expected_revision
        or payload.get("draft_hash") != expected_hash
    ):
        _TOKENS.release(token_str, rid)
        raise LocalAiPreviewExpired(details={"reason": "binding_mismatch"})
    try:
        with read_scope(session):
            _record_pre, _draft_pre, manifest_pre = load_current_ai_manifest(
                session, profile_id=profile_id, observation_id=observation_id
            )
            candidate_pre, _raw_pre, _execution_pre, inp_pre = _candidate_chain(
                session,
                profile_id=profile_id,
                observation_id=observation_id,
                candidate_id=candidate_id,
            )
            if (
                candidate_pre.candidate_hash != payload.get("candidate_hash")
                or inp_pre.dependency_hash != payload.get("input_dependency_hash")
            ):
                raise LocalAiPreviewExpired(details={"reason": "candidate_binding"})
            photo_dicts = _material_union(
                input_photos(session, inp_pre), manifest_pre
            )
        identities = _inspect_materials(
            session,
            runtime,
            observation_id=observation_id,
            photos=photo_dicts,
        )
        if (
            identities != payload.get("material_identities")
            or _material_sources(photo_dicts) != payload.get("material_sources")
        ):
            raise LocalAiPreviewExpired(details={"reason": "material_changed"})
    except BaseException:
        _TOKENS.release(token_str, rid)
        raise

    try:
        begin_immediate(session)
    except BaseException:
        rollback(session)
        _TOKENS.release(token_str, rid)
        raise
    try:
        session.expire_all()
        receipt = _obs_receipt(session, profile_id, rid)
        if receipt is not None:
            result = _obs_replay(session, profile_id, rid, fingerprint)
            rollback(session)
            _TOKENS.release(token_str, rid)
            return result
        try:
            expired = time.time() >= float(payload.get("exp", 0))
        except (TypeError, ValueError):
            expired = True
        if expired:
            raise LocalAiPreviewExpired(details={"reason": "expired"})
        record, draft, manifest = load_current_ai_manifest(
            session, profile_id=profile_id, observation_id=observation_id
        )
        if draft.revision != expected_revision or draft.payload_hash != expected_hash:
            raise LocalAiPreviewExpired(details={"reason": "late_edit"})
        candidate, raw, _execution, inp = _candidate_chain(
            session,
            profile_id=profile_id,
            observation_id=observation_id,
            candidate_id=candidate_id,
        )
        if (
            candidate.candidate_hash != payload.get("candidate_hash")
            or inp.dependency_hash != payload.get("input_dependency_hash")
        ):
            raise LocalAiPreviewExpired(details={"reason": "candidate_binding_late"})
        current_union = _material_union(input_photos(session, inp), manifest)
        if _material_sources(current_union) != payload.get("material_sources"):
            raise LocalAiPreviewExpired(details={"reason": "material_list_changed"})
        _short_verify_materials(
            session,
            runtime,
            observation_id=observation_id,
            identities=list(payload.get("material_identities") or []),
        )
        if not _contract_adoptable(session, profile_id, candidate):
            raise LocalAiContractObsolete()
        selected = _validate_targets(raw, candidate.task_type, selected_targets)
        if selected != payload.get("targets"):
            raise LocalAiPreviewExpired(details={"reason": "target_binding"})
        state, diff = _source_state(
            session,
            profile_id=profile_id,
            observation_id=observation_id,
            candidate=candidate,
            input_row=inp,
            record=record,
            draft=draft,
            manifest=manifest,
        )
        if state == _STATE_CONTRACT_OBSOLETE:
            raise LocalAiContractObsolete()
        if state != payload.get("source_state"):
            raise LocalAiPreviewExpired(details={"reason": "source_changed_after_preview"})
        if state == _STATE_SOURCE_CHANGED:
            if value_hash(diff) != payload.get("diff_hash"):
                raise LocalAiPreviewExpired(details={"reason": "diff_changed"})
            if review_decision != REVIEW_DECISION:
                raise LocalAiSourceChanged(details=diff)
        current_payload = dict(draft.payload_json or {})
        current_dependency_hash = project_input(
            session,
            profile_id=profile_id,
            observation_id=observation_id,
            task_type=candidate.task_type,
            target=inp.payload_json.get("target")
            if isinstance(inp.payload_json, dict)
            else None,
            record=record,
            draft=draft,
            manifest=manifest,
        ).dependency_hash
        if current_dependency_hash != payload.get("dependency_hash"):
            raise LocalAiPreviewExpired(details={"reason": "late_edit"})
        for target in selected:
            if value_hash(_target_value(current_payload, target)) != payload["before_hashes"][target]:
                raise LocalAiTargetChanged()
            if value_hash(_candidate_value(raw, candidate.task_type, target)) != payload["after_hashes"][target]:
                raise LocalAiPreviewExpired(details={"reason": "candidate_changed"})
        owners, owner_hashes = _operation_owners(
            session, profile_id=profile_id, observation_id=observation_id
        )
        for target in selected:
            if owners.get(target) == candidate.id:
                current_hash = value_hash(_target_value(current_payload, target))
                if owner_hashes.get(target) == current_hash:
                    if current_hash == payload["after_hashes"][target]:
                        continue
                raise LocalAiTargetChanged()
        ever = _ever_adopted_targets(
            session, observation_id=observation_id, candidate_id=candidate.id
        )
        for target in selected:
            if target in ever and value_hash(
                _target_value(current_payload, target)
            ) != payload["after_hashes"][target]:
                raise LocalAiTargetChanged()

        raw_payload = {
            key: value for key, value in current_payload.items() if key != "term_snapshot"
        }
        for target in selected:
            raw_payload[target] = _candidate_value(raw, candidate.task_type, target)
        merged = normalize_payload(
            raw_payload, term_snapshot=current_payload.get("term_snapshot")
        )
        changed = merged != current_payload
        now = utc_now()
        original_manifest = business_manifest(manifest)
        if changed:
            draft.payload_json = merged
            draft.revision += 1
            draft.payload_hash = aggregate_hash(merged, original_manifest)
            draft.updated_at = now
            _projection(record, merged, draft, now=now)
            session.flush()
        latest = _latest_version(session, observation_id)
        history_created = latest is None or latest.payload_hash != draft.payload_hash
        if history_created:
            version = _create_version(
                session,
                profile_id=profile_id,
                record=record,
                payload=merged,
                manifest=original_manifest,
                payload_hash=draft.payload_hash,
                source_kind="adopt",
                now=now,
            )
            result_version = version.version
        else:
            result_version = record.current_version
        if result_version is None:
            raise LocalStorageError("采用结果缺少保留版本")
        target_evidence = {
            target: {
                "candidate_id": candidate.id,
                "output_hash": payload["after_hashes"][target],
            }
            for target in selected
        }
        existing = _provenance_row(
            session,
            observation_id=observation_id,
            version=result_version,
            candidate_id=candidate.id,
        )
        if existing is None:
            session.add(
                LocalObservationAIProvenance(
                    id=new_opaque_id(),
                    profile_id=profile_id,
                    source_kind="game_observation",
                    source_id=observation_id,
                    observation_id=observation_id,
                    version=result_version,
                    candidate_id=candidate.id,
                    adopted_targets_json=target_evidence,
                    input_hash=inp.dependency_hash,
                    output_hash=candidate.candidate_hash,
                    created_at=now,
                )
            )
        else:
            merged_evidence = dict(existing.adopted_targets_json or {})
            merged_evidence.update(target_evidence)
            existing.adopted_targets_json = merged_evidence
            existing.input_hash = inp.dependency_hash
            existing.output_hash = candidate.candidate_hash
        result = {
            "changed": changed,
            "history_created": history_created,
            "observation_id": observation_id,
            "candidate_id": candidate.id,
            "selected_targets": selected,
            "revision": draft.revision,
            "payload_hash": draft.payload_hash,
            "current_version": result_version,
            "result_version": result_version,
            "target_hashes": _target_hashes(merged),
            "input_hash": inp.dependency_hash,
            "output_hash": candidate.candidate_hash,
            "saved_at": now.isoformat(),
        }
        _operation(
            session,
            profile_id=profile_id,
            request_id=rid,
            kind=OP_ADOPT,
            observation_id=observation_id,
            fingerprint=fingerprint,
            result=result,
            now=now,
        )
        if changed or history_created:
            _audit(
                session,
                profile_id=profile_id,
                action=OP_ADOPT,
                observation_id=observation_id,
                version_after=draft.revision,
                now=now,
            )
        session.flush()
        session.commit()
    except BaseException:
        rollback(session)
        _TOKENS.release(token_str, rid)
        raise
    _TOKENS.consume(token_str)
    return result


__all__ = [
    "ADOPTION_TTL_SECONDS",
    "MAX_TOKENS",
    "OP_ADOPT",
    "OP_CREATE",
    "REVIEW_DECISION",
    "adopt",
    "create_observation_task",
    "get_candidate",
    "list_candidates",
    "load_observation_material",
    "preview_adoption",
    "reset_tokens",
    "revalidate_observation_source",
]
