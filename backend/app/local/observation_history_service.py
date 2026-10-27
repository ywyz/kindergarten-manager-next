"""Observation history and restore service (E05/E08).

Only the service layer is implemented here.  Restore preview tokens are
one-time, digest-only bindings; a restore commit is idempotent through the
observation operation receipt, not through the token row.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import date, datetime, timedelta
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ids import new_opaque_id
from app.local.base import utc_now
from app.local.errors import LocalError
from app.local.models import (
    LocalObservationAsset,
    LocalObservationDraft,
    LocalObservationOperation,
    LocalObservationRecord,
    LocalObservationRestore,
    LocalObservationRestorePreview,
    LocalObservationVersion,
    LocalObservationVersionPhoto,
    LocalObservationDraftPhoto,
    LocalTerm,
)
from app.local.normalize import normalize_request_id
from app.local.observation_assets import (
    MAX_SOURCE_BYTES,
    inspect_managed_asset,
    managed_asset_path,
    verify_managed_asset_identity,
)
from app.local.observation_service import (
    ObservationHistoryCorrupt,
    ObservationNotFound,
    ObservationProjectionMismatch,
    ObservationRequestConflict,
    ObservationRestorePreviewExpired,
    ObservationRestorePreviewInvalid,
    ObservationRestoreSourceInvalid,
    ObservationRestoreTokenConsumed,
    ObservationRestoreUnprotected,
    ObservationStorageError,
    _audit,
    _create_version,
    _fingerprint,
    _format_for_mime,
    _latest_version,
    _load_current,
    _manifest_for_assets,
    _operation,
    _projection,
    _receipt,
    _replay,
    _replace_draft_photos,
    _target_hashes,
    validate_version,
)
from app.local.observation_terms import get_term_snapshot, snapshot_from_term
from app.local.observation_validation import (
    aggregate_hash,
    canonical_json,
    normalize_payload,
    normalize_photo_manifest,
)
from app.local.tx import begin_immediate, read_scope, rollback

RESTORE_PREVIEW_TTL_SECONDS = 15 * 60
_TERM_DECISIONS = frozenset(
    {"keep_history", "keep_current", "assign_selected", "unassigned"}
)


class ObservationHistoryNotFound(LocalError):
    code = "OBS_HISTORY_NOT_FOUND"
    status_code = 404
    message = "未找到该观察历史版本"


def _version_manifest(
    session: Session, version: LocalObservationVersion
) -> list[dict[str, Any]]:
    _payload, manifest = validate_version(
        session, version, profile_id=version.creator_profile_id
    )
    return manifest


def _version_row(
    session: Session, profile_id: str, observation_id: str, version: int
) -> LocalObservationVersion:
    record = session.get(LocalObservationRecord, observation_id)
    if record is None or record.creator_profile_id != profile_id:
        raise ObservationNotFound()
    row = session.scalars(
        select(LocalObservationVersion)
        .where(
            LocalObservationVersion.observation_id == observation_id,
            LocalObservationVersion.version == version,
        )
        .limit(1)
    ).first()
    if row is None:
        raise ObservationHistoryNotFound()
    if row.creator_profile_id != profile_id:
        raise ObservationHistoryNotFound()
    return row


def list_history(
    session: Session, *, profile_id: str, observation_id: str
) -> list[dict[str, Any]]:
    with read_scope(session):
        record = session.get(LocalObservationRecord, observation_id)
        if record is None or record.creator_profile_id != profile_id:
            raise ObservationNotFound()
        rows = session.execute(
            select(
                LocalObservationVersion.version,
                LocalObservationVersion.id,
                LocalObservationVersion.payload_hash,
                LocalObservationVersion.source_kind,
                LocalObservationVersion.created_at,
            )
            .where(LocalObservationVersion.observation_id == observation_id)
            .order_by(LocalObservationVersion.version.desc())
        ).all()
        return [
            {
                "version": row.version,
                "id": row.id,
                "payload_hash": row.payload_hash,
                "source_kind": row.source_kind,
                "created_at": row.created_at.isoformat(),
                "is_current": row.version == record.current_version,
            }
            for row in rows
        ]


def read_history_version(
    session: Session,
    *,
    profile_id: str,
    observation_id: str,
    version: int,
) -> dict[str, Any]:
    with read_scope(session):
        row = _version_row(session, profile_id, observation_id, version)
        payload, manifest = validate_version(
            session, row, profile_id=profile_id
        )
        return {
            "version": row.version,
            "id": row.id,
            "payload": payload,
            "payload_hash": row.payload_hash,
            "photos": manifest,
            "source_kind": row.source_kind,
            "created_at": row.created_at.isoformat(),
        }


def _material_hash(manifest: list[dict[str, Any]]) -> str:
    raw = json.dumps(
        [
            {
                "asset_id": item["asset_id"],
                "content_hash": item["content_hash"],
                "sort_order": item["sort_order"],
                "caption": item["caption"],
            }
            for item in manifest
        ],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _date_in_snapshot(value: Any, snapshot: dict[str, str] | None) -> bool:
    if value is None or snapshot is None:
        return True
    try:
        day = date.fromisoformat(str(value))
        start = date.fromisoformat(snapshot["start_date"])
        end = date.fromisoformat(snapshot["end_date"])
    except (TypeError, ValueError, KeyError):
        return False
    return start <= day <= end


def _effective_payload(
    session: Session,
    *,
    source_payload: dict[str, Any],
    current_payload: dict[str, Any],
    term_decision: str,
    selected_term_id: str | None,
) -> tuple[dict[str, Any], dict[str, str] | None, list[str]]:
    if term_decision not in _TERM_DECISIONS:
        raise ObservationRestoreSourceInvalid()
    base = {
        key: value
        for key, value in source_payload.items()
        if key != "term_snapshot"
    }
    warnings: list[str] = []
    if term_decision == "keep_history":
        term_id = source_payload.get("term_id")
        snapshot = source_payload.get("term_snapshot")
        if term_id is not None:
            live_source = _live_term_snapshot(session, term_id, required=True)
            if snapshot is None:
                raise ObservationRestoreSourceInvalid(
                    details={"reason": "history_term_missing"}
                )
            if not _date_in_snapshot(base.get("observation_date"), snapshot):
                raise ObservationRestoreSourceInvalid(
                    details={"reason": "history_term_date_outside"}
                )
            if live_source is not None and not _date_in_snapshot(
                base.get("observation_date"), live_source
            ):
                raise ObservationRestoreSourceInvalid(
                    details={"reason": "history_term_range_changed"}
                )
    elif term_decision == "keep_current":
        term_id = current_payload.get("term_id")
        snapshot = current_payload.get("term_snapshot")
        if term_id is not None:
            if session.get(LocalTerm, term_id) is None or snapshot is None:
                raise ObservationRestoreSourceInvalid(
                    details={"reason": "current_term_missing"}
                )
            if not _date_in_snapshot(base.get("observation_date"), snapshot):
                warnings.append("date_outside_current_term")
    elif term_decision == "assign_selected":
        if selected_term_id is None:
            raise ObservationRestoreSourceInvalid(
                details={"reason": "selected_term_required"}
            )
        resolved = get_term_snapshot(session, selected_term_id)
        term_id = resolved.term_id
        snapshot = resolved.as_json()
        if not _date_in_snapshot(base.get("observation_date"), snapshot):
            warnings.append("date_outside_selected_term")
    else:
        term_id = None
        snapshot = None
    base["term_id"] = term_id
    try:
        normalized = normalize_payload(base, term_snapshot=snapshot)
    except LocalError as exc:
        raise ObservationRestoreSourceInvalid() from exc
    return normalized, snapshot, warnings


def _live_term_snapshot(
    session: Session, term_id: str | None, *, required: bool = False
) -> dict[str, str] | None:
    if term_id is None:
        return None
    term = session.get(LocalTerm, term_id)
    if term is None:
        if required:
            raise ObservationRestoreSourceInvalid(
                details={"reason": "term_missing"}
            )
        return None
    return snapshot_from_term(term).as_json()


def _term_binding_context(
    session: Session,
    *,
    source_payload: dict[str, Any],
    current_payload: dict[str, Any],
    term_decision: str,
    selected_term_id: str | None,
) -> dict[str, Any]:
    current = _live_term_snapshot(
        session, current_payload.get("term_id"), required=True
    )
    source_required = term_decision == "keep_history"
    source = _live_term_snapshot(
        session, source_payload.get("term_id"), required=source_required
    )
    selected = (
        _live_term_snapshot(session, selected_term_id, required=True)
        if term_decision == "assign_selected"
        else None
    )
    return {
        "current_term": current,
        "source_term": source,
        "selected_term": selected,
    }


def _term_snapshot_hash(
    snapshot: dict[str, str] | None,
    term_decision: str,
    selected_term_id: str | None,
    binding_context: dict[str, Any],
) -> str:
    # The hash is a binding, not a display value.  It must remain distinct even
    # when the effective term is null, so a token cannot be reused with another
    # keep_history/keep_current/unassigned decision or after an involved term
    # configuration changes.
    return hashlib.sha256(
        canonical_json(
            {
                "snapshot": snapshot,
                "term_decision": term_decision,
                "selected_term_id": selected_term_id,
                "binding_context": binding_context,
            }
        ).encode("utf-8")
    ).hexdigest()


def _verify_material(
    session: Session,
    runtime: Any,
    *,
    profile_id: str,
    observation_id: str,
    manifest: list[dict[str, Any]],
) -> dict[str, tuple[int, int, int, int]]:
    """Decode and hash each original through E03's checked staging handle.

    The returned identity snapshot is only a short final-lock check; no image
    decode or multi-image byte retention happens after this point.
    """
    snapshots: dict[str, tuple[int, int, int, int]] = {}
    for item in manifest:
        asset = session.get(LocalObservationAsset, item["asset_id"])
        if asset is None or asset.observation_id != observation_id:
            raise ObservationRestoreSourceInvalid()
        if (
            asset.content_hash != item["content_hash"]
            or asset.byte_size <= 0
            or asset.width != item["width"]
            or asset.height != item["height"]
            or asset.orientation != item["orientation"]
            or _format_for_mime(asset.mime_type) != item["format"]
        ):
            raise ObservationRestoreSourceInvalid()
        try:
            path = managed_asset_path(
                runtime, asset.relative_path, observation_id, asset.id
            )
            inspection = inspect_managed_asset(path, runtime.data_dir)
        except LocalError as exc:
            raise ObservationRestoreSourceInvalid() from exc
        except Exception as exc:  # noqa: BLE001
            raise ObservationRestoreSourceInvalid() from exc
        if (
            inspection.content_hash != item["content_hash"]
            or inspection.byte_size != asset.byte_size
            or inspection.image_format != item["format"]
            or inspection.width != item["width"]
            or inspection.height != item["height"]
            or inspection.orientation != item["orientation"]
        ):
            raise ObservationRestoreSourceInvalid()
        snapshots[item["asset_id"]] = inspection.identity
    return snapshots


def _short_material_check(
    session: Session,
    runtime: Any,
    *,
    observation_id: str,
    manifest: list[dict[str, Any]],
    snapshots: dict[str, tuple[int, int, int, int]],
) -> None:
    for item in manifest:
        asset = session.get(LocalObservationAsset, item["asset_id"])
        if asset is None or asset.observation_id != observation_id:
            raise ObservationRestoreSourceInvalid()
        if (
            asset.content_hash != item["content_hash"]
            or asset.byte_size <= 0
            or asset.byte_size > MAX_SOURCE_BYTES
            or asset.width != item["width"]
            or asset.height != item["height"]
            or asset.orientation != item["orientation"]
        ):
            raise ObservationRestoreSourceInvalid()
        expected = snapshots.get(item["asset_id"])
        if expected is None:
            raise ObservationRestoreSourceInvalid()
        try:
            path = managed_asset_path(
                runtime, asset.relative_path, observation_id, asset.id
            )
            verify_managed_asset_identity(path, runtime.data_dir, expected)
        except LocalError as exc:
            raise ObservationRestoreSourceInvalid() from exc
        except Exception as exc:  # noqa: BLE001
            raise ObservationRestoreSourceInvalid() from exc


def preview_restore(
    session: Session,
    runtime: Any,
    *,
    profile_id: str,
    observation_id: str,
    source_version: int,
    request_id: Any,
    base_draft_revision: int,
    base_draft_hash: str,
    term_decision: str,
    selected_term_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    rid = normalize_request_id(request_id)
    if term_decision not in _TERM_DECISIONS:
        raise ObservationRestoreSourceInvalid()
    with read_scope(session):
        record, draft, _current_manifest = _load_current(
            session, profile_id, observation_id
        )
        if draft.revision != base_draft_revision or draft.payload_hash != base_draft_hash:
            raise ObservationRestorePreviewInvalid()
        latest = _latest_version(session, observation_id)
        if latest is None or latest.payload_hash != draft.payload_hash:
            raise ObservationRestoreUnprotected()
        source = _version_row(session, profile_id, observation_id, source_version)
        source_manifest = _version_manifest(session, source)
        binding_context = _term_binding_context(
            session,
            source_payload=dict(source.payload_json or {}),
            current_payload=dict(draft.payload_json or {}),
            term_decision=term_decision,
            selected_term_id=selected_term_id,
        )
        effective, snapshot, term_warnings = _effective_payload(
            session,
            source_payload=dict(source.payload_json or {}),
            current_payload=dict(draft.payload_json or {}),
            term_decision=term_decision,
            selected_term_id=selected_term_id,
        )
        effective_hash = aggregate_hash(effective, source_manifest)
        material_hash = _material_hash(source_manifest)
        source_hash = source.payload_hash
        source_id = source.id
        current_version = record.current_version
    _verify_material(
        session,
        runtime,
        profile_id=profile_id,
        observation_id=observation_id,
        manifest=source_manifest,
    )
    now = now or utc_now()
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    expires_at = now + timedelta(seconds=RESTORE_PREVIEW_TTL_SECONDS)
    begin_immediate(session)
    try:
        # Re-check the base and source after material verification; no long
        # decode/hash runs while this short write transaction is open.
        record2, draft2, _ = _load_current(session, profile_id, observation_id)
        latest2 = _latest_version(session, observation_id)
        if (
            latest2 is None
            or latest2.payload_hash != draft2.payload_hash
            or draft2.revision != base_draft_revision
            or draft2.payload_hash != base_draft_hash
        ):
            raise ObservationRestorePreviewInvalid()
        source2 = _version_row(session, profile_id, observation_id, source_version)
        source_manifest2 = _version_manifest(session, source2)
        binding_context2 = _term_binding_context(
            session,
            source_payload=dict(source2.payload_json or {}),
            current_payload=dict(draft2.payload_json or {}),
            term_decision=term_decision,
            selected_term_id=selected_term_id,
        )
        effective2, snapshot2, term_warnings2 = _effective_payload(
            session,
            source_payload=dict(source2.payload_json or {}),
            current_payload=dict(draft2.payload_json or {}),
            term_decision=term_decision,
            selected_term_id=selected_term_id,
        )
        effective_hash2 = aggregate_hash(effective2, source_manifest2)
        if (
            source2.id != source_id
            or source2.payload_hash != source_hash
            or effective_hash2 != effective_hash
            or _material_hash(source_manifest2) != material_hash
        ):
            raise ObservationRestorePreviewInvalid()
        row = LocalObservationRestorePreview(
            id=new_opaque_id(),
            token_hash=token_hash,
            profile_id=profile_id,
            observation_id=observation_id,
            source_version=source_version,
            source_hash=source_hash,
            base_draft_revision=base_draft_revision,
            base_draft_hash=base_draft_hash,
            effective_term_id=effective2.get("term_id"),
            term_snapshot_hash=_term_snapshot_hash(
                snapshot2,
                term_decision,
                selected_term_id,
                binding_context2,
            ),
            effective_payload_hash=effective_hash2,
            material_hash=material_hash,
            request_id=rid,
            expires_at=expires_at,
            consumed_at=None,
            created_at=now,
        )
        session.add(row)
        session.commit()
    except LocalError:
        rollback(session)
        raise
    except IntegrityError as exc:
        rollback(session)
        raise ObservationStorageError() from exc
    except Exception as exc:
        rollback(session)
        raise ObservationStorageError() from exc
    return {
        "restore_token": token,
        "source_version": source_version,
        "base_draft_revision": base_draft_revision,
        "base_draft_hash": base_draft_hash,
        "effective_payload_hash": effective_hash,
        "effective_term_id": effective.get("term_id"),
        "effective_term_snapshot": effective.get("term_snapshot"),
        "material_hash": material_hash,
        "effective_payload": effective,
        "photos": source_manifest,
        "expires_at": expires_at.isoformat(),
        "request_id": rid,
        "current_version": current_version,
        "warnings": term_warnings2,
    }


def _preview_by_token(
    session: Session, token: str, profile_id: str, observation_id: str
) -> LocalObservationRestorePreview:
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    row = session.scalars(
        select(LocalObservationRestorePreview).where(
            LocalObservationRestorePreview.token_hash == token_hash
        )
    ).first()
    if row is None or row.profile_id != profile_id or row.observation_id != observation_id:
        raise ObservationRestorePreviewInvalid()
    if row.consumed_at is not None:
        raise ObservationRestoreTokenConsumed()
    return row


def restore_observation(
    session: Session,
    runtime: Any,
    *,
    profile_id: str,
    observation_id: str,
    request_id: Any,
    restore_token: Any,
    expected_base_revision: int,
    expected_base_hash: str,
    term_decision: str,
    selected_term_id: str | None = None,
    now: datetime | None = None,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    rid = normalize_request_id(request_id)
    if not isinstance(restore_token, str) or not restore_token:
        raise ObservationRestorePreviewInvalid()
    if term_decision not in _TERM_DECISIONS:
        raise ObservationRestoreSourceInvalid()
    token_hash = hashlib.sha256(restore_token.encode("utf-8")).hexdigest()
    fingerprint = _fingerprint(
        "observation_restore",
        {
            "profile_id": profile_id,
            "observation_id": observation_id,
            "token_hash": token_hash,
            "expected_base_revision": expected_base_revision,
            "expected_base_hash": expected_base_hash,
            "term_decision": term_decision,
            "selected_term_id": selected_term_id,
        },
    )
    with read_scope(session):
        replay = _replay(session, profile_id, rid, fingerprint)
    if replay is not None:
        return replay
    injected_now = now is not None
    now = now or (clock() if clock is not None else utc_now())
    # Material verification and source read happen outside the write lock.
    try:
        with read_scope(session):
            preview = _preview_by_token(session, restore_token, profile_id, observation_id)
            if now > preview.expires_at:
                raise ObservationRestorePreviewExpired()
            if (
                preview.request_id != rid
                or preview.base_draft_revision != expected_base_revision
                or preview.base_draft_hash != expected_base_hash
            ):
                raise ObservationRestorePreviewInvalid()
            source = _version_row(session, profile_id, observation_id, preview.source_version)
            source_manifest = _version_manifest(session, source)
            if source.payload_hash != preview.source_hash:
                raise ObservationRestorePreviewInvalid()
            current_record, current_draft, _ = _load_current(
                session, profile_id, observation_id
            )
            if (
                current_draft.revision != preview.base_draft_revision
                or current_draft.payload_hash != preview.base_draft_hash
            ):
                raise ObservationRestorePreviewInvalid()
            latest = _latest_version(session, observation_id)
            if latest is None or latest.payload_hash != current_draft.payload_hash:
                raise ObservationRestoreUnprotected()
            effective, snapshot, term_warnings = _effective_payload(
                session,
                source_payload=dict(source.payload_json or {}),
                current_payload=dict(current_draft.payload_json or {}),
                term_decision=term_decision,
                selected_term_id=selected_term_id,
            )
            binding_context = _term_binding_context(
                session,
                source_payload=dict(source.payload_json or {}),
                current_payload=dict(current_draft.payload_json or {}),
                term_decision=term_decision,
                selected_term_id=selected_term_id,
            )
            effective_hash = aggregate_hash(effective, source_manifest)
            material_hash = _material_hash(source_manifest)
            if (
                effective_hash != preview.effective_payload_hash
                or material_hash != preview.material_hash
                or _term_snapshot_hash(snapshot, term_decision, selected_term_id, binding_context) != preview.term_snapshot_hash
            ):
                raise ObservationRestorePreviewInvalid()
            preview_id = preview.id
            before_revision = current_draft.revision
            before_hash = current_draft.payload_hash
            before_version = current_record.current_version
        material_snapshots = _verify_material(
            session,
            runtime,
            profile_id=profile_id,
            observation_id=observation_id,
            manifest=source_manifest,
        )
    except LocalError as exc:
        # A concurrent identical restore may have committed after the first
        # receipt lookup and before/while this preflight read.  Receipts take
        # priority over a now-consumed token or a changed current draft.
        with read_scope(session):
            replay = _replay(session, profile_id, rid, fingerprint)
        if replay is not None:
            return replay
        raise
    begin_immediate(session)
    try:
        commit_now = (
            clock()
            if clock is not None
            else (now if injected_now else utc_now())
        )
        replay = _replay(session, profile_id, rid, fingerprint)
        if replay is not None:
            rollback(session)
            return replay
        preview = session.get(LocalObservationRestorePreview, preview_id)
        if preview is None:
            raise ObservationRestorePreviewInvalid()
        if (
            preview.token_hash != token_hash
            or preview.profile_id != profile_id
            or preview.observation_id != observation_id
            or preview.request_id != rid
        ):
            raise ObservationRestorePreviewInvalid()
        if preview.consumed_at is not None:
            raise ObservationRestoreTokenConsumed()
        if commit_now > preview.expires_at:
            raise ObservationRestorePreviewExpired()
        # Drop any identity-map copies read during the long material phase so
        # the final short transaction sees current asset/projection rows.
        session.expire_all()
        record, draft, _ = _load_current(session, profile_id, observation_id)
        if (
            draft.revision != preview.base_draft_revision
            or draft.payload_hash != preview.base_draft_hash
            or draft.revision != before_revision
            or draft.payload_hash != before_hash
            or record.current_version != before_version
        ):
            raise ObservationRestorePreviewInvalid()
        latest = _latest_version(session, observation_id)
        if latest is None or latest.payload_hash != draft.payload_hash:
            raise ObservationRestoreUnprotected()
        source = _version_row(session, profile_id, observation_id, preview.source_version)
        source_manifest = _version_manifest(session, source)
        if source.payload_hash != preview.source_hash:
            raise ObservationRestorePreviewInvalid()
        effective, snapshot, term_warnings = _effective_payload(
            session,
            source_payload=dict(source.payload_json or {}),
            current_payload=dict(draft.payload_json or {}),
            term_decision=term_decision,
            selected_term_id=selected_term_id,
        )
        binding_context = _term_binding_context(
            session,
            source_payload=dict(source.payload_json or {}),
            current_payload=dict(draft.payload_json or {}),
            term_decision=term_decision,
            selected_term_id=selected_term_id,
        )
        effective_hash = aggregate_hash(effective, source_manifest)
        if (
            effective_hash != preview.effective_payload_hash
            or _material_hash(source_manifest) != preview.material_hash
            or _term_snapshot_hash(snapshot, term_decision, selected_term_id, binding_context) != preview.term_snapshot_hash
        ):
            raise ObservationRestorePreviewInvalid()
        _short_material_check(
            session,
            runtime,
            observation_id=observation_id,
            manifest=source_manifest,
            snapshots=material_snapshots,
        )
        changed = draft.payload_hash != effective_hash
        if changed:
            _replace_draft_photos(session, observation_id, source_manifest)
            draft.payload_json = effective
            draft.revision += 1
            draft.payload_hash = effective_hash
            draft.updated_at = commit_now
            _projection(record, effective, draft, now=commit_now)
            session.flush()
            version = _create_version(
                session,
                profile_id=profile_id,
                record=record,
                payload=effective,
                manifest=source_manifest,
                payload_hash=effective_hash,
                source_kind="restore",
                now=commit_now,
            )
            result_version = version.version
        else:
            # Unchanged restore must point to the actual current retained
            # result, not an older source version that happens to share a hash.
            if record.current_version is None:
                raise ObservationRestoreUnprotected()
            result_version = record.current_version
        restore = LocalObservationRestore(
            id=new_opaque_id(),
            operation_id=new_opaque_id(),
            profile_id=profile_id,
            observation_id=observation_id,
            source_version=preview.source_version,
            result_version=result_version,
            before_draft_revision=before_revision,
            before_version=before_version,
            changed=1 if changed else 0,
            term_decision=term_decision,
            effective_term_id=effective.get("term_id"),
            effective_payload_hash=effective_hash,
            created_at=commit_now,
        )
        # Operation and restore detail share the same short transaction.
        operation = _operation(
            session,
            profile_id=profile_id,
            request_id=rid,
            kind="observation_restore",
            observation_id=observation_id,
            fingerprint=fingerprint,
            result={
                "observation_id": observation_id,
                "changed": changed,
                "revision": draft.revision,
                "payload_hash": effective_hash,
                "current_version": record.current_version,
                "source_version": preview.source_version,
                "result_version": result_version,
                "term_decision": term_decision,
                "effective_term_id": effective.get("term_id"),
                "photos": source_manifest,
                "target_hashes": _target_hashes(effective),
                "saved_at": commit_now.isoformat(),
            },
            now=commit_now,
        )
        restore.operation_id = operation.id
        session.add(restore)
        preview.consumed_at = commit_now
        _audit(
            session,
            profile_id=profile_id,
            action="observation_restore",
            observation_id=observation_id,
            version_after=draft.revision,
            now=commit_now,
        )
        session.flush()
        result = dict(operation.result_json)
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
    "RESTORE_PREVIEW_TTL_SECONDS",
    "ObservationHistoryNotFound",
    "list_history",
    "read_history_version",
    "preview_restore",
    "restore_observation",
]
