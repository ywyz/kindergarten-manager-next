"""Observation service: current draft creation, save and retained history.

This module owns the E05 service layer only.  Pages, HTTP routes, AI adoption,
Word export and host integration remain outside this slice.  The current
content authority is always ``LocalObservationDraft`` plus the ordered
``LocalObservationDraftPhoto`` association; retained versions are immutable
snapshots of the same canonical payload and original-photo manifest.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ids import new_opaque_id
from app.local import profile_service
from app.local.base import utc_now
from app.local.errors import LocalError, LocalProfileRequired
from app.local.models import (
    LocalObservationAsset,
    LocalObservationDraft,
    LocalObservationDraftPhoto,
    LocalObservationOperation,
    LocalObservationRecord,
    LocalObservationVersion,
    LocalObservationVersionPhoto,
    LocalOperationRecord,
    LocalTerm,
)
from app.local.normalize import normalize_request_id
from app.local.observation_terms import (
    apply_term_resolution,
    get_term_snapshot,
    resolve_edit,
    resolve_new,
)
from app.local.observation_validation import (
    EVALUATION_KEYS,
    aggregate_hash,
    canonical_json,
    normalize_payload,
    normalize_photo_manifest,
)
from app.local.tx import begin_immediate, read_scope, rollback

_UNSET = object()
SAVE_REASONS = frozenset({"auto", "manual", "leave", "pre_restore", "pre_export"})
_FORMAT_BY_MIME = {
    "image/jpeg": "jpeg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
    "image/bmp": "bmp",
}
_MIME_BY_FORMAT = {value: key for key, value in _FORMAT_BY_MIME.items()}


class ObservationNotFound(LocalError):
    code = "OBS_NOT_FOUND"
    status_code = 404
    message = "未找到该观察记录"


class ObservationRevisionConflict(LocalError):
    code = "OBS_REVISION_CONFLICT"
    status_code = 409
    message = "观察草稿已被其他保存更新，请刷新后重试"


class ObservationRequestConflict(LocalError):
    code = "OBS_IDEMPOTENCY_CONFLICT"
    status_code = 409
    message = "同一请求 ID 使用了不同观察操作内容"


class ObservationTermDecisionRequired(LocalError):
    code = "OBS_TERM_DECISION_REQUIRED"
    status_code = 409
    message = "日期变更涉及学期归属，请明确选择学期"


class ObservationStorageError(LocalError):
    code = "OBS_STORAGE_IO"
    status_code = 503
    message = "观察数据保存失败"


class ObservationProjectionMismatch(LocalError):
    code = "OBS_STORAGE_PROJECTION_MISMATCH"
    status_code = 409
    message = "观察草稿与记录投影不一致"


class ObservationHistoryCorrupt(LocalError):
    code = "OBS_HISTORY_CORRUPT"
    status_code = 409
    message = "观察历史快照损坏"


class ObservationRestoreUnprotected(LocalError):
    code = "OBS_RESTORE_UNPROTECTED"
    status_code = 409
    message = "当前稿尚未保存为可恢复的保留节点"


class ObservationRestorePreviewInvalid(LocalError):
    code = "OBS_RESTORE_PREVIEW_INVALID"
    status_code = 409
    message = "历史恢复预览已失效，请重新预览"


class ObservationRestorePreviewExpired(LocalError):
    code = "OBS_RESTORE_PREVIEW_EXPIRED"
    status_code = 409
    message = "历史恢复预览已过期，请重新预览"


class ObservationRestoreTokenConsumed(LocalError):
    code = "OBS_RESTORE_TOKEN_CONSUMED"
    status_code = 409
    message = "历史恢复预览已使用"


class ObservationRestoreSourceInvalid(LocalError):
    code = "OBS_RESTORE_SOURCE_INVALID"
    status_code = 409
    message = "历史版本或归属已失效，请重新预览"


class ObservationOperationNotFound(LocalError):
    code = "OBS_OPERATION_NOT_FOUND"
    status_code = 404
    message = "未找到该观察操作回执"


def _fingerprint(kind: str, payload: dict[str, Any]) -> str:
    raw = json.dumps(
        {"kind": kind, "payload": payload},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _canonical_request(value: Any) -> Any:
    """Normalize only request text for a stable fingerprint.

    This intentionally does not merge with current state or fill defaults; the
    same semantic whitespace/newline request must fingerprint identically even
    after the current draft has advanced.
    """
    if isinstance(value, str):
        return value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if isinstance(value, list):
        return [_canonical_request(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _canonical_request(item)
            for key, item in sorted(value.items(), key=lambda pair: pair[0])
        }
    return value


def _validate_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ObservationProjectionMismatch()
    raw = {key: value for key, value in payload.items() if key != "term_snapshot"}
    try:
        normalized = normalize_payload(
            raw, term_snapshot=payload.get("term_snapshot")
        )
    except LocalError:
        raise ObservationProjectionMismatch() from None
    if normalized != payload:
        raise ObservationProjectionMismatch()
    term_id = normalized.get("term_id")
    snapshot = normalized.get("term_snapshot")
    if term_id is None and snapshot is not None:
        raise ObservationProjectionMismatch()
    if term_id is not None and (
        snapshot is None or snapshot.get("term_id") != term_id
    ):
        raise ObservationProjectionMismatch()
    return normalized


def _manifest_for_version(
    session: Session, version: LocalObservationVersion
) -> list[dict[str, Any]]:
    rows = session.execute(
        select(LocalObservationVersionPhoto, LocalObservationAsset)
        .join(
            LocalObservationAsset,
            (LocalObservationAsset.observation_id == LocalObservationVersionPhoto.observation_id)
            & (LocalObservationAsset.id == LocalObservationVersionPhoto.asset_id),
        )
        .where(LocalObservationVersionPhoto.version_id == version.id)
        .order_by(LocalObservationVersionPhoto.sort_order)
    ).all()
    manifest: list[dict[str, Any]] = []
    for index, (photo, asset) in enumerate(rows):
        if photo.sort_order != index:
            raise ObservationProjectionMismatch()
        manifest.append(
            {
                "asset_id": asset.id,
                "content_hash": asset.content_hash,
                "format": _format_for_mime(asset.mime_type),
                "width": asset.width,
                "height": asset.height,
                "orientation": asset.orientation,
                "sort_order": index,
                "caption": photo.caption,
            }
        )
    try:
        return normalize_photo_manifest(manifest)
    except LocalError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ObservationProjectionMismatch() from exc


def validate_version(
    session: Session,
    version: LocalObservationVersion,
    *,
    profile_id: str | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    record = session.get(LocalObservationRecord, version.observation_id)
    if record is None or (profile_id is not None and record.creator_profile_id != profile_id):
        raise ObservationNotFound()
    if profile_id is not None and version.creator_profile_id != profile_id:
        raise ObservationHistoryCorrupt()
    payload = _validate_payload(version.payload_json)
    manifest = _manifest_for_version(session, version)
    if aggregate_hash(payload, manifest) != version.payload_hash:
        raise ObservationHistoryCorrupt()
    return payload, manifest


def _receipt(
    session: Session, profile_id: str, request_id: str
) -> LocalObservationOperation | None:
    return session.scalars(
        select(LocalObservationOperation).where(
            LocalObservationOperation.profile_id == profile_id,
            LocalObservationOperation.request_id == request_id,
        )
    ).first()


def _replay(
    session: Session,
    profile_id: str,
    request_id: str,
    fingerprint: str,
) -> dict[str, Any] | None:
    row = _receipt(session, profile_id, request_id)
    if row is None:
        return None
    if row.request_fingerprint != fingerprint:
        raise ObservationRequestConflict()
    return dict(row.result_json or {})


def _operation(
    session: Session,
    *,
    profile_id: str,
    request_id: str,
    kind: str,
    observation_id: str,
    fingerprint: str,
    result: dict[str, Any],
    now: datetime,
) -> LocalObservationOperation:
    row = LocalObservationOperation(
        id=new_opaque_id(),
        profile_id=profile_id,
        request_id=request_id,
        operation_kind=kind,
        observation_id=observation_id,
        request_fingerprint=fingerprint,
        status="committed",
        result_json=result,
        created_at=now,
    )
    session.add(row)
    return row


def _audit(
    session: Session,
    *,
    profile_id: str,
    action: str,
    observation_id: str,
    version_after: int | None,
    now: datetime,
) -> None:
    session.add(
        LocalOperationRecord(
            id=new_opaque_id(),
            created_at=now,
            actor_id=profile_id,
            action=action,
            target_type="observation",
            target_id=observation_id,
            target_version_after=version_after,
        )
    )


def _format_for_mime(mime_type: str) -> str:
    image_format = _FORMAT_BY_MIME.get(mime_type)
    if image_format is None:
        raise ObservationHistoryCorrupt()
    return image_format


def _manifest_for_assets(session: Session, observation_id: str) -> list[dict[str, Any]]:
    rows = session.execute(
        select(LocalObservationDraftPhoto, LocalObservationAsset)
        .join(
            LocalObservationAsset,
            (LocalObservationAsset.observation_id == LocalObservationDraftPhoto.observation_id)
            & (LocalObservationAsset.id == LocalObservationDraftPhoto.asset_id),
        )
        .where(LocalObservationDraftPhoto.observation_id == observation_id)
        .order_by(LocalObservationDraftPhoto.sort_order)
    ).all()
    manifest: list[dict[str, Any]] = []
    for index, (photo, asset) in enumerate(rows):
        if photo.sort_order != index:
            raise ObservationProjectionMismatch()
        manifest.append(
            {
                "asset_id": asset.id,
                "content_hash": asset.content_hash,
                "format": _format_for_mime(asset.mime_type),
                "width": asset.width,
                "height": asset.height,
                "orientation": asset.orientation,
                "sort_order": index,
                "caption": photo.caption,
            }
        )
    try:
        return normalize_photo_manifest(manifest)
    except LocalError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ObservationHistoryCorrupt() from exc


def _load_current(
    session: Session, profile_id: str, observation_id: str
) -> tuple[LocalObservationRecord, LocalObservationDraft, list[dict[str, Any]]]:
    record = session.get(LocalObservationRecord, observation_id)
    if record is None or record.creator_profile_id != profile_id:
        raise ObservationNotFound()
    draft = session.get(LocalObservationDraft, observation_id)
    if draft is None:
        raise ObservationNotFound()
    if record.current_draft_revision != draft.revision:
        raise ObservationProjectionMismatch()
    payload = _validate_payload(draft.payload_json)
    manifest = _manifest_for_assets(session, observation_id)
    expected = aggregate_hash(payload, manifest)
    if draft.payload_hash != expected:
        raise ObservationProjectionMismatch()
    expected_projection = {
        "observation_date": (
            date.fromisoformat(payload["observation_date"])
            if payload.get("observation_date")
            else None
        ),
        "record_type": payload["record_type"],
        "start_time": payload.get("start_time"),
        "end_time": payload.get("end_time"),
        "term_id": payload.get("term_id"),
        "term_snapshot_json": payload.get("term_snapshot"),
        "school_name": payload.get("school_name"),
        "class_name": payload.get("class_name"),
        "observer_name": payload.get("observer_name"),
        "adult_count": payload.get("adult_count"),
        "child_count": payload.get("child_count"),
        "age_years": payload.get("age_years"),
        "subjects_json": list(payload.get("subjects") or []),
        "environment": payload.get("environment"),
    }
    for field, value in expected_projection.items():
        if getattr(record, field) != value:
            raise ObservationProjectionMismatch()
    latest = _latest_version(session, observation_id)
    expected_current = latest.version if latest is not None else None
    if record.current_version != expected_current:
        raise ObservationProjectionMismatch()
    if latest is not None:
        validate_version(session, latest, profile_id=profile_id)
    return record, draft, manifest


def _latest_version(
    session: Session, observation_id: str
) -> LocalObservationVersion | None:
    return session.scalars(
        select(LocalObservationVersion)
        .where(LocalObservationVersion.observation_id == observation_id)
        .order_by(LocalObservationVersion.version.desc())
        .limit(1)
    ).first()


def _replace_draft_photos(
    session: Session,
    observation_id: str,
    manifest: list[dict[str, Any]],
) -> None:
    session.execute(
        delete(LocalObservationDraftPhoto).where(
            LocalObservationDraftPhoto.observation_id == observation_id
        )
    )
    session.flush()
    for item in manifest:
        session.add(
            LocalObservationDraftPhoto(
                observation_id=observation_id,
                asset_id=item["asset_id"],
                sort_order=item["sort_order"],
                caption=item["caption"],
            )
        )
    session.flush()


def _create_version(
    session: Session,
    *,
    profile_id: str,
    record: LocalObservationRecord,
    payload: dict[str, Any],
    manifest: list[dict[str, Any]],
    payload_hash: str,
    source_kind: str,
    now: datetime,
) -> LocalObservationVersion:
    latest = _latest_version(session, record.id)
    version_no = (latest.version + 1) if latest is not None else 1
    version = LocalObservationVersion(
        id=new_opaque_id(),
        observation_id=record.id,
        version=version_no,
        payload_json=payload,
        payload_hash=payload_hash,
        source_kind=source_kind,
        creator_profile_id=profile_id,
        created_at=now,
    )
    session.add(version)
    session.flush()
    for item in manifest:
        session.add(
            LocalObservationVersionPhoto(
                version_id=version.id,
                asset_id=item["asset_id"],
                observation_id=record.id,
                sort_order=item["sort_order"],
                caption=item["caption"],
            )
        )
    session.flush()
    record.current_version = version_no
    return version


def _projection(
    record: LocalObservationRecord,
    payload: dict[str, Any],
    draft: LocalObservationDraft,
    *,
    now: datetime,
) -> None:
    record.observation_date = (
        date.fromisoformat(payload["observation_date"])
        if payload.get("observation_date")
        else None
    )
    record.record_type = payload["record_type"]
    record.start_time = payload.get("start_time")
    record.end_time = payload.get("end_time")
    record.term_id = payload.get("term_id")
    record.term_snapshot_json = payload.get("term_snapshot")
    record.school_name = payload.get("school_name")
    record.class_name = payload.get("class_name")
    record.observer_name = payload.get("observer_name")
    record.adult_count = payload.get("adult_count")
    record.child_count = payload.get("child_count")
    record.age_years = payload.get("age_years")
    record.subjects_json = list(payload.get("subjects") or [])
    record.environment = payload.get("environment")
    record.current_draft_revision = draft.revision
    record.updated_at = now


def _caption(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ObservationRequestConflict()
    cleaned = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    return cleaned or None


def _photos_for_save(
    session: Session,
    observation_id: str,
    photos: Any,
    current: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if photos is None:
        return list(current)
    if not isinstance(photos, list):
        raise ObservationRequestConflict()
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(photos):
        if isinstance(item, str):
            asset_id = item
            caption = None
        elif isinstance(item, dict):
            if set(item) - {"asset_id", "caption"}:
                raise ObservationRequestConflict()
            asset_id = item.get("asset_id")
            caption = _caption(item.get("caption"))
        else:
            raise ObservationRequestConflict()
        if not isinstance(asset_id, str) or not asset_id or asset_id in seen:
            raise ObservationRequestConflict()
        seen.add(asset_id)
        asset = session.get(LocalObservationAsset, asset_id)
        if asset is None or asset.observation_id != observation_id:
            raise ObservationRequestConflict()
        result.append(
            {
                "asset_id": asset.id,
                "content_hash": asset.content_hash,
                "format": _format_for_mime(asset.mime_type),
                "width": asset.width,
                "height": asset.height,
                "orientation": asset.orientation,
                "sort_order": index,
                "caption": caption,
            }
        )
    return normalize_photo_manifest(result)


def _date_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        return value.strip()
    return None


def _new_payload(
    session: Session,
    *,
    raw: dict[str, Any],
    observation_date: Any,
    term_id: Any,
) -> tuple[dict[str, Any], Any, list[str]]:
    if not isinstance(raw, dict):
        raise ObservationRequestConflict()
    merged = dict(raw)
    if "term_snapshot" in merged:
        raise ObservationRequestConflict()
    if observation_date is not _UNSET:
        merged["observation_date"] = observation_date
    if "observation_date" not in merged:
        merged["observation_date"] = date.today().isoformat()
    if term_id is not _UNSET:
        merged["term_id"] = term_id
    snapshot = None
    warnings: list[str] = []
    if "term_id" in merged and merged.get("term_id") is not None:
        snapshot = get_term_snapshot(session, merged["term_id"]).as_json()
        day = _date_value(merged.get("observation_date"))
        if day is not None:
            start = date.fromisoformat(snapshot["start_date"])
            end = date.fromisoformat(snapshot["end_date"])
            if not (start <= date.fromisoformat(day) <= end):
                warnings.append("date_outside_selected_term")
    elif "term_id" not in merged:
        resolution = resolve_new(
            session, observation_date=merged.get("observation_date")
        )
        if resolution.requires_decision:
            raise ObservationTermDecisionRequired(
                details={"options": [o.as_json() for o in resolution.options]}
            )
        snapshot = resolution.snapshot.as_json() if resolution.snapshot else None
        merged["term_id"] = resolution.term_id
        warnings.extend(resolution.warnings)
    return merged, snapshot, warnings


def _save_term(
    session: Session,
    *,
    current_payload: dict[str, Any],
    merged: dict[str, Any],
    raw_has_term: bool,
    term_decision: str | None,
    selected_term_id: str | None,
) -> tuple[dict[str, Any], Any, list[str]]:
    current_term_id = current_payload.get("term_id")
    current_snapshot = current_payload.get("term_snapshot")
    current_date = _date_value(current_payload.get("observation_date"))
    new_date = _date_value(merged.get("observation_date"))
    warnings: list[str] = []
    if term_decision is not None:
        if term_decision == "keep_current":
            if current_term_id is None:
                merged["term_id"] = None
                return merged, None, warnings
            if current_snapshot is None:
                raise ObservationTermDecisionRequired(
                    details={"reason": "current_term_snapshot_missing"}
                )
            merged["term_id"] = current_term_id
            if new_date is not None:
                start = date.fromisoformat(current_snapshot["start_date"])
                end = date.fromisoformat(current_snapshot["end_date"])
                if not (start <= date.fromisoformat(new_date) <= end):
                    warnings.append("date_outside_current_term")
            return merged, current_snapshot, warnings
        if term_decision == "assign_selected":
            if selected_term_id is None:
                raise ObservationTermDecisionRequired(
                    details={"reason": "selected_term_required"}
                )
            selected = get_term_snapshot(session, selected_term_id)
            if new_date is not None:
                start = date.fromisoformat(selected.start_date)
                end = date.fromisoformat(selected.end_date)
                if not (start <= date.fromisoformat(new_date) <= end):
                    warnings.append("date_outside_selected_term")
            merged["term_id"] = selected.term_id
            return merged, selected.as_json(), warnings
        if term_decision == "unassigned":
            merged["term_id"] = None
            return merged, None, warnings
        raise ObservationRequestConflict()

    # A page-supplied term_id is not a term decision.  It may repeat the
    # current attribution, but changing/clearing it requires the explicit
    # term_decision protocol above.
    requested_term = merged.get("term_id")
    if raw_has_term and requested_term != current_term_id:
        raise ObservationTermDecisionRequired(
            details={"reason": "explicit_term_decision_required"}
        )
    merged["term_id"] = current_term_id
    if new_date != current_date:
        resolution = resolve_edit(
            session,
            current_term_id=current_term_id,
            new_date=new_date,
            previous_date=current_date,
            current_snapshot=current_snapshot,
            decision=None,
        )
        if resolution.requires_decision:
            raise ObservationTermDecisionRequired(
                details={"options": [o.as_json() for o in resolution.options]}
            )
        if resolution.term_id is None:
            merged["term_id"] = None
            return merged, None, list(resolution.warnings)
        merged["term_id"] = resolution.term_id
        return (
            merged,
            resolution.snapshot.as_json() if resolution.snapshot else None,
            list(resolution.warnings),
        )
    return merged, current_snapshot, warnings


def _target_hashes(payload: dict[str, Any]) -> dict[str, str]:
    """Hashes used by the AI provenance ledger; no text is persisted here."""
    evaluation = payload.get("analysis_evaluation") or {}
    values = {
        "observation_goal": payload.get("observation_goal") or "",
        "observation_process": payload.get("observation_process") or "",
        "support_strategy": payload.get("support_strategy") or "",
        "analysis_evaluation": {
            key: evaluation.get(key) or "" for key in EVALUATION_KEYS
        },
    }
    return {
        key: hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
        for key, value in values.items()
    }


def _create_result(
    record: LocalObservationRecord,
    draft: LocalObservationDraft,
    manifest: list[dict[str, Any]],
    now: datetime,
    term_warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "observation_id": record.id,
        "revision": draft.revision,
        "payload_hash": draft.payload_hash,
        "photos": manifest,
        "current_version": record.current_version,
        "changed": True,
        "term_warnings": list(term_warnings or []),
        "target_hashes": _target_hashes(dict(draft.payload_json or {})),
        "saved_at": now.isoformat(),
    }


def create_observation(
    session: Session,
    *,
    profile_id: str,
    request_id: Any,
    record_type: Any,
    payload: Any = None,
    observation_date: Any = _UNSET,
    term_id: Any = _UNSET,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Create one observation with an empty or supplied canonical payload."""
    rid = normalize_request_id(request_id)
    if record_type not in ("public", "indoor", "outdoor"):
        raise ObservationRequestConflict()
    if payload is not None and not isinstance(payload, dict):
        raise ObservationRequestConflict()
    raw = dict(payload or {})
    if raw.get("record_type") not in (None, record_type):
        raise ObservationRequestConflict()
    fingerprint = _fingerprint(
        "observation_create",
        _canonical_request(
            {
                "profile_id": profile_id,
                "record_type": record_type,
                "payload": raw,
                "observation_date": observation_date
                if observation_date is not _UNSET
                else "<unset>",
                "term_id": term_id if term_id is not _UNSET else "<unset>",
            }
        ),
    )
    with read_scope(session):
        replay = _replay(session, profile_id, rid, fingerprint)
    if replay is not None:
        return replay
    now = now or utc_now()
    begin_immediate(session)
    try:
        replay = _replay(session, profile_id, rid, fingerprint)
        if replay is not None:
            rollback(session)
            return replay
        context = profile_service.require_context(session, date.today())
        if context.profile is None or context.profile.id != profile_id:
            raise ObservationNotFound()
        assert context.school_class is not None
        merged, snapshot, term_warnings = _new_payload(
            session,
            raw=raw,
            observation_date=observation_date,
            term_id=term_id,
        )
        merged.setdefault("record_type", record_type)
        if merged.get("record_type") != record_type:
            raise ObservationRequestConflict()
        if "school_name" not in merged:
            merged["school_name"] = context.settings.school_name
        if "class_name" not in merged:
            merged["class_name"] = context.school_class.name
        if "observer_name" not in merged:
            merged["observer_name"] = context.profile.display_name
        canonical = normalize_payload(merged, term_snapshot=snapshot)
        record_id = new_opaque_id()
        record = LocalObservationRecord(
            id=record_id,
            creator_profile_id=profile_id,
            observation_date=(
                date.fromisoformat(canonical["observation_date"])
                if canonical.get("observation_date")
                else None
            ),
            record_type=canonical["record_type"],
            start_time=canonical.get("start_time"),
            end_time=canonical.get("end_time"),
            term_id=canonical.get("term_id"),
            term_snapshot_json=canonical.get("term_snapshot"),
            school_name=canonical.get("school_name"),
            class_name=canonical.get("class_name"),
            observer_name=canonical.get("observer_name"),
            adult_count=canonical.get("adult_count"),
            child_count=canonical.get("child_count"),
            age_years=canonical.get("age_years"),
            subjects_json=list(canonical.get("subjects") or []),
            environment=canonical.get("environment"),
            current_draft_revision=1,
            current_version=None,
            created_at=now,
            updated_at=now,
        )
        session.add(record)
        session.flush()
        digest = aggregate_hash(canonical, [])
        draft = LocalObservationDraft(
            observation_id=record_id,
            revision=1,
            payload_json=canonical,
            payload_hash=digest,
            created_at=now,
            updated_at=now,
        )
        session.add(draft)
        session.flush()
        result = _create_result(record, draft, [], now, term_warnings)
        _operation(
            session,
            profile_id=profile_id,
            request_id=rid,
            kind="observation_create",
            observation_id=record_id,
            fingerprint=fingerprint,
            result=result,
            now=now,
        )
        _audit(
            session,
            profile_id=profile_id,
            action="observation_create",
            observation_id=record_id,
            version_after=None,
            now=now,
        )
        session.commit()
        return result
    except LocalError:
        rollback(session)
        raise
    except IntegrityError as exc:
        rollback(session)
        raise ObservationStorageError() from exc
    except Exception as exc:
        rollback(session)
        raise ObservationStorageError() from exc


def read_current(
    session: Session, *, profile_id: str, observation_id: str
) -> dict[str, Any]:
    with read_scope(session):
        record, draft, manifest = _load_current(session, profile_id, observation_id)
        return {
            "observation_id": record.id,
            "revision": draft.revision,
            "payload": dict(draft.payload_json or {}),
            "payload_hash": draft.payload_hash,
            "photos": manifest,
            "current_version": record.current_version,
            "updated_at": record.updated_at.isoformat(),
        }


def read_operation_receipt(
    session: Session,
    *,
    profile_id: str,
    request_id: Any,
    operation_kind: str | None = None,
) -> dict[str, Any]:
    """Read-only receipt lookup; never performs a business write."""
    rid = normalize_request_id(request_id)
    with read_scope(session):
        row = session.scalars(
            select(LocalObservationOperation).where(
                LocalObservationOperation.profile_id == profile_id,
                LocalObservationOperation.request_id == rid,
            )
        ).first()
        if row is None or (
            operation_kind is not None and row.operation_kind != operation_kind
        ):
            raise ObservationOperationNotFound()
        return {
            "request_id": row.request_id,
            "operation_kind": row.operation_kind,
            "status": row.status,
            "result": dict(row.result_json or {}),
            "created_at": row.created_at.isoformat(),
        }


def save_observation(
    session: Session,
    *,
    profile_id: str,
    observation_id: str,
    request_id: Any,
    expected_revision: Any,
    payload: Any,
    photos: Any = None,
    save_reason: Any = "manual",
    term_decision: str | None = None,
    selected_term_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Save the full current draft and retain history for non-auto reasons."""
    rid = normalize_request_id(request_id)
    if (
        not isinstance(expected_revision, int)
        or isinstance(expected_revision, bool)
        or expected_revision < 1
    ):
        raise ObservationRequestConflict()
    if save_reason not in SAVE_REASONS:
        raise ObservationRequestConflict()
    if not isinstance(payload, dict):
        raise ObservationRequestConflict()
    if term_decision not in (None, "keep_current", "assign_selected", "unassigned"):
        raise ObservationRequestConflict()
    fingerprint = _fingerprint(
        "observation_save",
        _canonical_request(
            {
                "profile_id": profile_id,
                "observation_id": observation_id,
                "expected_revision": expected_revision,
                "payload": payload,
                "photos": photos,
                "save_reason": save_reason,
                "term_decision": term_decision,
                "selected_term_id": selected_term_id,
            }
        ),
    )
    with read_scope(session):
        replay = _replay(session, profile_id, rid, fingerprint)
    if replay is not None:
        return replay
    now = now or utc_now()
    begin_immediate(session)
    try:
        replay = _replay(session, profile_id, rid, fingerprint)
        if replay is not None:
            rollback(session)
            return replay
        record, draft, current_manifest = _load_current(
            session, profile_id, observation_id
        )
        if draft.revision != expected_revision:
            raise ObservationRevisionConflict()
        current_payload = dict(draft.payload_json or {})
        raw_has_term = "term_id" in payload
        merged = {
            key: value
            for key, value in current_payload.items()
            if key != "term_snapshot"
        }
        merged.update(payload)
        if "term_snapshot" in payload:
            raise ObservationRequestConflict()
        merged, snapshot, term_warnings = _save_term(
            session,
            current_payload=current_payload,
            merged=merged,
            raw_has_term=raw_has_term,
            term_decision=term_decision,
            selected_term_id=selected_term_id,
        )
        canonical = normalize_payload(merged, term_snapshot=snapshot)
        manifest = _photos_for_save(
            session, observation_id, photos, current_manifest
        )
        digest = aggregate_hash(canonical, manifest)
        changed = digest != draft.payload_hash
        latest = _latest_version(session, observation_id)
        version_created = False
        if changed:
            _replace_draft_photos(session, observation_id, manifest)
            draft.payload_json = canonical
            draft.revision += 1
            draft.payload_hash = digest
            draft.updated_at = now
            _projection(record, canonical, draft, now=now)
            session.flush()
        if save_reason != "auto" and (latest is None or latest.payload_hash != digest):
            _create_version(
                session,
                profile_id=profile_id,
                record=record,
                payload=canonical,
                manifest=manifest,
                payload_hash=digest,
                source_kind="manual",
                now=now,
            )
            version_created = True
            _projection(record, canonical, draft, now=now)
            session.flush()
        result = {
            "observation_id": observation_id,
            "revision": draft.revision,
            "payload_hash": digest,
            "photos": manifest,
            "current_version": record.current_version,
            "changed": changed,
            "history_created": version_created,
            "term_warnings": term_warnings,
            "target_hashes": _target_hashes(canonical),
            "saved_at": now.isoformat(),
        }
        _operation(
            session,
            profile_id=profile_id,
            request_id=rid,
            kind="observation_save",
            observation_id=observation_id,
            fingerprint=fingerprint,
            result=result,
            now=now,
        )
        if changed or version_created:
            _audit(
                session,
                profile_id=profile_id,
                action="observation_save",
                observation_id=observation_id,
                version_after=draft.revision,
                now=now,
            )
        session.commit()
        return result
    except LocalError:
        rollback(session)
        raise
    except IntegrityError as exc:
        rollback(session)
        raise ObservationStorageError() from exc
    except Exception as exc:
        rollback(session)
        raise ObservationStorageError() from exc


__all__ = [
    "SAVE_REASONS",
    "ObservationNotFound",
    "ObservationRevisionConflict",
    "ObservationRequestConflict",
    "ObservationTermDecisionRequired",
    "ObservationStorageError",
    "ObservationProjectionMismatch",
    "ObservationHistoryCorrupt",
    "ObservationRestoreUnprotected",
    "ObservationRestorePreviewInvalid",
    "ObservationRestorePreviewExpired",
    "ObservationRestoreTokenConsumed",
    "ObservationRestoreSourceInvalid",
    "ObservationOperationNotFound",
    "create_observation",
    "read_current",
    "read_operation_receipt",
    "save_observation",
]
