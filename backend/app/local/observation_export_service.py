"""Observation export preview, fixed snapshot, token and host-attempt service.

The preview freezes current drafts, ordered export derivatives and missing
facts.  Export creation generates the DOCX outside the write lock, writes it
to a managed temporary object with a sidecar manifest (content hash/size),
then rechecks the *minimal* current binding inside ``BEGIN IMMEDIATE`` before
committing the bearer token.  A concurrent draft/photo change therefore
refuses the export instead of delivering an old confirmation.

The snapshot manifest is the only content authority after preview: DOCX
generation reads frozen payloads and frozen export-derivative ids/hashes,
never the current draft.  Artifacts are served from the managed file with a
refcount, so terminal/expired cleanup never unlinks a file still being
streamed to the host.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import secrets
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.ids import new_opaque_id
from app.local.base import utc_now
from app.local.errors import LocalError
from app.local.models import (
    LocalObservationAsset,
    LocalObservationAssetDerivative,
    LocalObservationDraft,
    LocalObservationDraftPhoto,
    LocalObservationExportAttempt,
    LocalObservationExportSnapshot,
    LocalObservationExportToken,
    LocalObservationOperation,
    LocalObservationRecord,
    LocalOperationRecord,
)
from app.local.normalize import normalize_request_id
from app.local.observation_assets import (
    ObservationAssetNotFound,
    ObservationMaterialCorrupt,
    ObservationMaterialInvalid,
    ObservationMaterialMissing,
    _check_no_reparse,
    _hold_managed_dirs,
    _prepare_managed_dir,
    _same_identity,
    _verify_handle_path,
    read_derivative_bytes,
)
from app.local.observation_service import (
    _canonical_request,
    _fingerprint,
    _load_current,
    _operation,
    _replay,
    read_current,
    save_observation,
)
from app.local.observation_validation import (
    canonical_json,
    is_empty_record,
    missing_fields,
    warnings,
)
from app.local.tx import begin_immediate, read_scope, rollback
from app.services.word_export_observation import (
    ObservationWordError,
    ObservationWordPhoto,
    ObservationWordRecord,
    generate_observation_export_docx,
)

PREVIEW_TTL_SECONDS = 15 * 60
TOKEN_TTL_SECONDS = 10 * 60
# Technical bounds only: no business record-count quota.  The selection is
# bounded by its actual serialized bytes; the frozen set is bounded by the
# aggregate text/photo bytes and pixels it really contains.
MAX_EXPORT_SELECTION_BYTES = 2 * 1024 * 1024
MAX_EXPORT_TOTAL_PAYLOAD_BYTES = 8 * 1024 * 1024
MAX_EXPORT_TOTAL_PHOTO_BYTES = 64 * 1024 * 1024
MAX_EXPORT_DOCX_BYTES = 128 * 1024 * 1024
EXPORT_TEMP_ROOT = Path("observations") / "export-temp"
_ARTIFACT_CHUNK = 1024 * 1024
_MAX_CLEANUP_SCAN = 1000
_META_MAX_BYTES = 64 * 1024
_SNAPSHOT_CLEANUP_SCAN = 200
_RELEASED_MANIFEST_VERSION = 1
_TYPE_LABELS = {"public": "公共", "indoor": "室内", "outdoor": "户外"}
_FORBIDDEN_FILENAME = set('<>:"/\\|?*')
_CONTROL = {chr(i) for i in range(32)}
_RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_TOKEN_HASH_RE = re.compile(r"^[0-9a-f]{64}$")

# In-flight streaming refs and pending deletions, keyed by token hash.
_ARTIFACT_LOCK = threading.Lock()
_ARTIFACT_REFS: dict[str, int] = {}
_ARTIFACT_PENDING_DELETE: set[str] = set()


class ObservationExportError(LocalError):
    code = "OBS_EXPORT_INVALID"
    status_code = 409
    message = "观察导出请求不合法"


class ObservationExportNotFound(ObservationExportError):
    code = "OBS_EXPORT_NOT_FOUND"
    status_code = 404
    message = "未找到观察导出快照或产物"


class ObservationExportEmpty(ObservationExportError):
    code = "OBS_EXPORT_EMPTY"
    status_code = 409
    message = "选集中存在空观察记录，请先处理"


class ObservationExportBadMaterial(ObservationExportError):
    code = "OBS_EXPORT_BAD_MATERIAL"
    status_code = 409
    message = "选集中存在损坏或缺失的照片，请先处理"


class ObservationExportMissingUnconfirmed(ObservationExportError):
    code = "OBS_EXPORT_MISSING_UNCONFIRMED"
    status_code = 409
    message = "存在缺项，请确认后留空导出"


class ObservationExportSnapshotStale(ObservationExportError):
    code = "OBS_EXPORT_SNAPSHOT_STALE"
    status_code = 409
    message = "选集或当前稿已变化，请重新预览导出"


class ObservationExportTokenInvalid(ObservationExportError):
    code = "OBS_EXPORT_TOKEN_INVALID"
    status_code = 409
    message = "导出凭证无效或已过期，请重新预览"


class ObservationExportAttemptConflict(ObservationExportError):
    code = "OBS_EXPORT_ATTEMPT_CONFLICT"
    status_code = 409
    message = "同一导出凭证已用于不同文件名"


class ObservationExportAttemptState(ObservationExportError):
    code = "OBS_EXPORT_ATTEMPT_STATE"
    status_code = 409
    message = "导出保存尝试状态不合法"


class ObservationExportRetryUnavailable(ObservationExportError):
    code = "OBS_EXPORT_RETRY_UNAVAILABLE"
    status_code = 409
    message = "尚无已生成的导出产物，请重新预览后再试"


class ObservationExportAttemptInProgress(ObservationExportError):
    code = "OBS_EXPORT_ATTEMPT_IN_PROGRESS"
    status_code = 409
    message = "导出保存仍在进行中，请先查询结果"


class ObservationExportTooLarge(ObservationExportError):
    code = "OBS_EXPORT_TOO_LARGE"
    status_code = 413
    message = "导出的 Word 文件超过技术上限，请减少照片后重新预览"


class ObservationExportSelectionTooLarge(ObservationExportError):
    code = "OBS_EXPORT_SELECTION_TOO_LARGE"
    status_code = 413
    message = "选集的序列化体积超过技术上限，请分批导出"


class ObservationExportContentTooLarge(ObservationExportError):
    code = "OBS_EXPORT_CONTENT_TOO_LARGE"
    status_code = 413
    message = "选集累计正文或照片超过技术上限，请减少选集后重新预览"


class ObservationExportArtifactMissing(ObservationExportError):
    code = "OBS_EXPORT_ARTIFACT_MISSING"
    status_code = 409
    message = "导出临时产物已释放，请重新预览导出"


class ObservationExportArtifactMismatch(ObservationExportError):
    code = "OBS_EXPORT_ARTIFACT_MISMATCH"
    status_code = 409
    message = "导出产物与创建回执不一致，已拒绝交付"


class ObservationExportStorage(ObservationExportError):
    code = "OBS_EXPORT_STORAGE"
    status_code = 503
    message = "导出临时产物写入失败"


@dataclass
class ExportArtifact:
    """One opened managed artifact; the handle is streamed to the host."""

    token_hash: str
    path: Path
    digest: str
    size: int
    expires_at: datetime
    handle: Any
    dir_hold: Any = None
    released: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)


def _safe_record_ref(
    payload: dict[str, Any], observation_id: str, *, photo_count: int | None = None
) -> dict[str, Any]:
    """Safe record identifiers for UI diagnosis; never names, text or paths."""
    ref: dict[str, Any] = {
        "observation_id": observation_id,
        "record_type": payload.get("record_type"),
        "observation_date": payload.get("observation_date"),
        "start_time": payload.get("start_time"),
        "subject_count": len(payload.get("subjects") or []),
    }
    if photo_count is not None:
        ref["photo_count"] = photo_count
    return ref


def _empty_record_error(
    payload: dict[str, Any], observation_id: str, photo_count: int
) -> ObservationExportEmpty:
    return ObservationExportEmpty(
        details=_safe_record_ref(payload, observation_id, photo_count=photo_count)
    )


def _bad_material_error(
    payload: dict[str, Any] | None,
    observation_id: str,
    *,
    asset_id: str | None = None,
    derivative_id: str | None = None,
    sort_order: int | None = None,
    reason: str = "unavailable",
) -> ObservationExportBadMaterial:
    details: dict[str, Any] = (
        _safe_record_ref(payload, observation_id) if payload is not None
        else {"observation_id": observation_id}
    )
    details["reason"] = reason
    if asset_id is not None:
        details["asset_id"] = asset_id
    if derivative_id is not None:
        details["derivative_id"] = derivative_id
    if sort_order is not None:
        details["sort_order"] = sort_order
    return ObservationExportBadMaterial(details=details)


def _cleanup_expired_snapshots(
    session: Session,
    runtime: Any,
    now: datetime,
    *,
    current_launch_id: str = "",
    current_session_scope: str = "",
) -> int:
    """Release expired frozen manifests without touching history/material.

    Already-released tombstones are excluded, so repeated cleanup is a no-op
    and does not grow the audit log.  The scan uses keyset pagination and a
    bounded batch loop, so more than one 200-row batch is released in a single
    trigger.  A live attempt is kept only when it belongs to the current
    launch/session scope (the teacher's dialog may still be open).  An
    in-progress attempt from an ended launch can never receive a host receipt,
    so it is recorded as ``indeterminate`` (never ``saved``), its token is
    consumed, its temporary artifact is released, and the snapshot is
    tombstoned while attempt/token receipt anchors remain.
    """
    try:
        begin_immediate(session)
        current_scope_hash = _scope_hash(current_session_scope)
        released = 0
        last_id = ""
        for _batch in range(50):
            rows = list(
                session.scalars(
                    select(LocalObservationExportSnapshot)
                    .where(
                        LocalObservationExportSnapshot.expires_at < now,
                        LocalObservationExportSnapshot.id > last_id,
                        text("json_extract(manifest_json, '$.released') IS NOT 1"),
                    )
                    .order_by(LocalObservationExportSnapshot.id)
                    .limit(_SNAPSHOT_CLEANUP_SCAN)
                ).all()
            )
            if not rows:
                break
            for row in rows:
                last_id = row.id
                in_progress = list(
                    session.scalars(
                        select(LocalObservationExportAttempt).where(
                            LocalObservationExportAttempt.snapshot_id == row.id,
                            LocalObservationExportAttempt.status == "in_progress",
                        )
                    ).all()
                )
                active_skip = False
                for attempt in in_progress:
                    same_launch = (
                        row.launch_id == current_launch_id
                        and row.session_scope_hash == current_scope_hash
                    )
                    if same_launch:
                        active_skip = True
                        continue
                    attempt.status = "indeterminate"
                    attempt.byte_size = None
                    attempt.result_hash = None
                    attempt.ended_at = now
                    token = session.scalars(
                        select(LocalObservationExportToken).where(
                            LocalObservationExportToken.token_hash
                            == attempt.export_id_hash
                        )
                    ).first()
                    if token is not None:
                        token.consumed_at = now
                        _delete_artifact(runtime, token.token_hash)
                    _audit_export(
                        session,
                        profile_id=row.profile_id,
                        action="observation_export_attempt_indeterminate",
                        target_id=row.id,
                        now=now,
                    )
                if active_skip:
                    continue
                attempts = int(
                    session.scalar(
                        select(func.count())
                        .select_from(LocalObservationExportAttempt)
                        .where(
                            LocalObservationExportAttempt.snapshot_id == row.id
                        )
                    )
                    or 0
                )
                if attempts:
                    tombstone = {
                        "version": _RELEASED_MANIFEST_VERSION,
                        "released": True,
                        "released_at": now.isoformat(),
                    }
                    row.manifest_json = tombstone
                    row.manifest_hash = hashlib.sha256(
                        canonical_json(tombstone).encode("utf-8")
                    ).hexdigest()
                else:
                    session.execute(
                        delete(LocalObservationExportToken).where(
                            LocalObservationExportToken.snapshot_id == row.id
                        )
                    )
                    session.delete(row)
                _audit_export(
                    session,
                    profile_id=row.profile_id,
                    action="observation_export_snapshot_released",
                    target_id=row.id,
                    now=now,
                )
                released += 1
            if len(rows) < _SNAPSHOT_CLEANUP_SCAN:
                break
        session.commit()
        return released
    except Exception:
        rollback(session)
        return 0


def _scope_hash(session_scope: str) -> str:
    return hashlib.sha256(session_scope.encode("utf-8")).hexdigest()


def _export_hash(export_id: str) -> str:
    return hashlib.sha256(export_id.encode("utf-8")).hexdigest()


def _safe_filename(value: str) -> str:
    cleaned = "".join(
        char for char in value if char not in _FORBIDDEN_FILENAME and char not in _CONTROL
    ).strip().strip(".")
    cleaned = " ".join(cleaned.split())
    if not cleaned:
        cleaned = "游戏观察记录"
    if not cleaned.lower().endswith(".docx"):
        cleaned += ".docx"
    if len(cleaned) > 120:
        digest = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:8]
        stem = cleaned[:-5][:100].rstrip()
        cleaned = f"{stem}-{digest}.docx"
    return cleaned


def _record_date(payload: dict[str, Any]) -> str:
    value = payload.get("observation_date")
    return str(value) if value else "未填日期"


def _subject_names(payload: dict[str, Any]) -> list[str]:
    return [
        str(item.get("name"))
        for item in payload.get("subjects") or []
        if isinstance(item, dict) and item.get("name")
    ]


def _suggested_filename(records: list[dict[str, Any]]) -> str:
    if len(records) == 1:
        payload = records[0]["payload"]
        date_part = _record_date(payload)
        type_label = _TYPE_LABELS.get(str(payload.get("record_type")), "观察")
        names = "、".join(_subject_names(payload))
        suffix = f"{date_part}{type_label}观察记录"
        if names:
            suffix += names
        return _safe_filename(f"{suffix}.docx")
    dates = [
        str(record["payload"].get("observation_date"))
        for record in records
        if record["payload"].get("observation_date")
    ]
    valid = sorted(set(dates))
    if not valid:
        span = "未填日期"
    elif len(valid) == len(records) and len(valid) == 1:
        span = valid[0]
    elif len(dates) == len(records):
        span = f"{valid[0]}至{valid[-1]}"
    else:
        span = f"{valid[0]}至{valid[-1]}含未填日期"
    return _safe_filename(f"游戏观察记录{span}共{len(records)}份.docx")


def _audit_export(
    session: Session, *, profile_id: str, action: str, target_id: str, now: datetime
) -> None:
    session.add(
        LocalOperationRecord(
            id=new_opaque_id(),
            created_at=now,
            actor_id=profile_id,
            action=action,
            target_type="observation_export",
            target_id=target_id,
            target_version_after=None,
        )
    )


# ---------------------------------------------------------------------------
# Managed temporary artifacts
# ---------------------------------------------------------------------------


def _export_temp_root(runtime: Any) -> Path:
    return runtime.data_dir / EXPORT_TEMP_ROOT


def _artifact_paths(runtime: Any, token_hash: str) -> tuple[Path, Path]:
    if not _TOKEN_HASH_RE.match(token_hash):
        raise ObservationExportStorage()
    root = _export_temp_root(runtime)
    return root / f"{token_hash}.docx", root / f"{token_hash}.json"


def _write_managed_bytes(root: Path, path: Path, data: bytes) -> None:
    _prepare_managed_dir(root, path.parent)
    temp = path.with_name(f"{path.name}.tmp-{new_opaque_id()}")
    fd: int | None = None
    hold = _hold_managed_dirs(root, temp)
    try:
        hold.__enter__()
        fd = os.open(
            temp,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
            0o600,
        )
        info = _verify_handle_path(
            fd, temp, root, error_cls=ObservationExportStorage
        )
        with os.fdopen(fd, "wb") as handle:
            fd = None
            view = memoryview(data)
            for offset in range(0, len(data), _ARTIFACT_CHUNK):
                handle.write(view[offset : offset + _ARTIFACT_CHUNK])
            handle.flush()
            os.fsync(handle.fileno())
        try:
            existing = os.lstat(path)
        except FileNotFoundError:
            existing = None
        if existing is not None and (
            not stat.S_ISREG(existing.st_mode)
            or getattr(existing, "st_nlink", 1) != 1
            or getattr(existing, "st_file_attributes", 0) & 0x400
        ):
            raise ObservationExportStorage()
        os.replace(temp, path)
        temp = None
        final = os.lstat(path)
        if (
            final.st_size != len(data)
            or getattr(final, "st_nlink", 1) != 1
            or getattr(final, "st_file_attributes", 0) & 0x400
        ):
            raise ObservationExportStorage()
    except LocalError:
        raise
    except OSError as exc:
        raise ObservationExportStorage() from exc
    finally:
        if fd is not None:
            os.close(fd)
        if temp is not None:
            try:
                os.unlink(temp)
            except OSError:
                pass
        try:
            hold.__exit__(None, None, None)
        except Exception:  # noqa: BLE001 - directory handles are best-effort close
            pass


def _write_artifact(
    runtime: Any,
    *,
    token_hash: str,
    data: bytes,
    digest: str,
    expires_at: datetime,
    snapshot_id: str,
    manifest_hash: str,
    now: datetime,
) -> None:
    if len(data) > MAX_EXPORT_DOCX_BYTES:
        raise ObservationExportTooLarge()
    root = _export_temp_root(runtime)
    docx_path, meta_path = _artifact_paths(runtime, token_hash)
    _write_managed_bytes(root, docx_path, data)
    meta = {
        "version": 1,
        "token_hash": token_hash,
        "snapshot_id": snapshot_id,
        "manifest_hash": manifest_hash,
        "content_hash": digest,
        "byte_size": len(data),
        "created_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
    }
    try:
        _write_managed_bytes(
            root,
            meta_path,
            json.dumps(meta, ensure_ascii=False, sort_keys=True).encode("utf-8"),
        )
    except Exception:
        _safe_unlink_managed(root, docx_path)
        raise


def _safe_unlink_managed(root: Path, path: Path) -> bool:
    """Unlink only a regular, single-link, non-reparse file under root.

    Hardlinks and junctions are refused: removing a link could otherwise
    affect an object outside the managed root. Parent directories are held
    without delete sharing for the duration of the check/unlink.
    """
    try:
        with _hold_managed_dirs(root, path):
            info = os.lstat(path)
            if (
                not stat.S_ISREG(info.st_mode)
                or getattr(info, "st_nlink", 1) != 1
                or getattr(info, "st_file_attributes", 0) & 0x400
            ):
                return False
            os.unlink(path)
            return True
    except FileNotFoundError:
        return False
    except (LocalError, OSError):
        return False


def _delete_artifact_now(runtime: Any, token_hash: str) -> None:
    root = _export_temp_root(runtime)
    docx_path, meta_path = _artifact_paths(runtime, token_hash)
    for path in (docx_path, meta_path):
        _safe_unlink_managed(root, path)


def _delete_artifact(runtime: Any, token_hash: str) -> None:
    with _ARTIFACT_LOCK:
        if _ARTIFACT_REFS.get(token_hash, 0) > 0:
            _ARTIFACT_PENDING_DELETE.add(token_hash)
            return
        _ARTIFACT_PENDING_DELETE.discard(token_hash)
    _delete_artifact_now(runtime, token_hash)


def _acquire_ref(token_hash: str) -> None:
    with _ARTIFACT_LOCK:
        _ARTIFACT_REFS[token_hash] = _ARTIFACT_REFS.get(token_hash, 0) + 1


def _release_ref(runtime: Any, token_hash: str) -> None:
    pending = False
    with _ARTIFACT_LOCK:
        current = _ARTIFACT_REFS.get(token_hash, 0)
        if current <= 1:
            _ARTIFACT_REFS.pop(token_hash, None)
            pending = token_hash in _ARTIFACT_PENDING_DELETE
            _ARTIFACT_PENDING_DELETE.discard(token_hash)
        else:
            _ARTIFACT_REFS[token_hash] = current - 1
    if pending:
        _delete_artifact_now(runtime, token_hash)


def release_artifact(runtime: Any, artifact: ExportArtifact) -> None:
    """Idempotent release used by the streaming response and its background."""
    with artifact.lock:
        if artifact.released:
            return
        artifact.released = True
    try:
        artifact.handle.close()
    finally:
        if artifact.dir_hold is not None:
            try:
                artifact.dir_hold.__exit__(None, None, None)
            except Exception:  # noqa: BLE001
                pass
        _release_ref(runtime, artifact.token_hash)


def _read_artifact_meta(root: Path, meta_path: Path) -> dict[str, Any]:
    """Bounded same-handle metadata read with managed-path checks.

    The file is opened only after every parent directory is held without
    delete sharing; the handle's final path, regular-file type, reparse flag,
    single-link count, size and identity are checked before and after the
    bounded read. A hardlink to a file outside the managed root is refused.
    """
    fd: int | None = None
    try:
        with _hold_managed_dirs(root, meta_path):
            fd = os.open(
                meta_path,
                os.O_RDONLY
                | getattr(os, "O_BINARY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
            )
            info = _verify_handle_path(
                fd, meta_path, root, error_cls=ObservationExportStorage
            )
            if info.st_size <= 0 or info.st_size > _META_MAX_BYTES:
                raise ObservationExportStorage()
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = os.read(fd, 4096)
                if not chunk:
                    break
                total += len(chunk)
                if total > _META_MAX_BYTES:
                    raise ObservationExportStorage()
                chunks.append(chunk)
            after = os.fstat(fd)
            if not _same_identity(info, after):
                raise ObservationExportStorage()
            path_info = os.lstat(meta_path)
            if (
                not _same_identity(info, path_info)
                or getattr(path_info, "st_nlink", 1) != 1
                or getattr(path_info, "st_file_attributes", 0) & 0x400
            ):
                raise ObservationExportStorage()
        try:
            meta = json.loads(b"".join(chunks).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ObservationExportStorage() from exc
        if not isinstance(meta, dict) or meta.get("version") != 1:
            raise ObservationExportStorage()
        return meta
    except FileNotFoundError as exc:
        raise ObservationExportArtifactMissing() from exc
    except ObservationMaterialMissing as exc:
        raise ObservationExportArtifactMissing() from exc
    except ObservationMaterialInvalid as exc:
        raise ObservationExportStorage() from exc
    except LocalError:
        raise
    except OSError as exc:
        raise ObservationExportStorage() from exc
    finally:
        if fd is not None:
            os.close(fd)


def _open_artifact(
    runtime: Any, *, token_hash: str, now: datetime, expected: dict[str, Any]
) -> ExportArtifact:
    root = _export_temp_root(runtime)
    docx_path, meta_path = _artifact_paths(runtime, token_hash)
    meta = _read_artifact_meta(root, meta_path)
    if (
        meta.get("token_hash") != token_hash
        or meta.get("snapshot_id") != expected["snapshot_id"]
        or meta.get("manifest_hash") != expected["manifest_hash"]
        or meta.get("content_hash") != expected["content_hash"]
        or meta.get("byte_size") != expected["byte_size"]
        or not isinstance(meta.get("content_hash"), str)
        or not _HASH_RE.match(str(meta.get("content_hash")))
        or not isinstance(meta.get("byte_size"), int)
        or isinstance(meta.get("byte_size"), bool)
        or meta.get("byte_size") <= 0
        or meta.get("byte_size") > MAX_EXPORT_DOCX_BYTES
    ):
        raise ObservationExportArtifactMismatch()
    try:
        expires_at = datetime.fromisoformat(str(meta.get("expires_at")))
    except ValueError as exc:
        raise ObservationExportStorage() from exc
    if now > expires_at:
        _delete_artifact(runtime, token_hash)
        raise ObservationExportTokenInvalid()
    _acquire_ref(token_hash)
    hold = _hold_managed_dirs(root, docx_path)
    fd: int | None = None
    try:
        hold.__enter__()
        fd = os.open(
            docx_path,
            os.O_RDONLY
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        info = _verify_handle_path(
            fd, docx_path, root, error_cls=ObservationExportStorage
        )
        if info.st_size != expected["byte_size"]:
            raise ObservationExportArtifactMismatch()
        hasher = hashlib.sha256()
        total = 0
        while True:
            chunk = os.read(fd, _ARTIFACT_CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_EXPORT_DOCX_BYTES:
                raise ObservationExportStorage()
            hasher.update(chunk)
        after = os.fstat(fd)
        if not _same_identity(info, after) or total != meta["byte_size"]:
            raise ObservationExportStorage()
        path_info = os.lstat(docx_path)
        if (
            not _same_identity(info, path_info)
            or getattr(path_info, "st_nlink", 1) != 1
            or getattr(path_info, "st_file_attributes", 0) & 0x400
        ):
            raise ObservationExportStorage()
        if hasher.hexdigest() != expected["content_hash"]:
            raise ObservationExportArtifactMismatch()
        os.lseek(fd, 0, os.SEEK_SET)
        handle = os.fdopen(fd, "rb")
        fd = None
        artifact = ExportArtifact(
            token_hash=token_hash,
            path=docx_path,
            digest=expected["content_hash"],
            size=expected["byte_size"],
            expires_at=expires_at,
            handle=handle,
            dir_hold=hold,
        )
        hold = None
        return artifact
    except FileNotFoundError as exc:
        raise ObservationExportArtifactMissing() from exc
    except ObservationMaterialMissing as exc:
        raise ObservationExportArtifactMissing() from exc
    except ObservationMaterialInvalid as exc:
        raise ObservationExportStorage() from exc
    except LocalError:
        raise
    except OSError as exc:
        raise ObservationExportStorage() from exc
    finally:
        if fd is not None:
            os.close(fd)
        if hold is not None:
            try:
                hold.__exit__(None, None, None)
            except Exception:  # noqa: BLE001
                pass
        if "artifact" not in locals():
            _release_ref(runtime, token_hash)


def _cleanup_expired_artifacts(runtime: Any, now: datetime) -> None:
    root = _export_temp_root(runtime)
    try:
        if not root.is_dir():
            return
        metas = list(root.glob("*.json"))[:_MAX_CLEANUP_SCAN]
    except OSError:
        return
    for meta_path in metas:
        token_hash = meta_path.stem
        if not _TOKEN_HASH_RE.match(token_hash):
            continue
        try:
            meta = _read_artifact_meta(root, meta_path)
            expires_at = datetime.fromisoformat(str(meta.get("expires_at")))
        except LocalError:
            continue
        except ValueError:
            continue
        if now > expires_at:
            _delete_artifact(runtime, token_hash)


# ---------------------------------------------------------------------------
# Snapshot construction and revalidation
# ---------------------------------------------------------------------------


def _build_manifest(
    session: Session,
    runtime: Any,
    *,
    profile_id: str,
    observation_ids: list[str],
    now: datetime,
    launch_id: str,
    session_scope: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    missing: list[dict[str, str]] = []
    warning_rows: list[dict[str, str]] = []
    total_payload_bytes = 0
    total_pixels = 0
    total_photo_bytes = 0
    with read_scope(session):
        for observation_id in observation_ids:
            _record, draft, manifest = _load_current(
                session, profile_id, observation_id
            )
            payload = dict(draft.payload_json or {})
            payload_bytes = len(canonical_json(payload).encode("utf-8"))
            total_payload_bytes += payload_bytes
            if total_payload_bytes > MAX_EXPORT_TOTAL_PAYLOAD_BYTES:
                raise ObservationExportContentTooLarge(
                    details={
                        "kind": "text",
                        "actual_bytes": total_payload_bytes,
                        "limit_bytes": MAX_EXPORT_TOTAL_PAYLOAD_BYTES,
                    }
                )
            photos: list[dict[str, Any]] = []
            for item in manifest:
                derivative = session.scalars(
                    select(LocalObservationAssetDerivative)
                    .where(
                        LocalObservationAssetDerivative.observation_id
                        == observation_id,
                        LocalObservationAssetDerivative.asset_id == item["asset_id"],
                        LocalObservationAssetDerivative.purpose == "export",
                    )
                    .order_by(
                        LocalObservationAssetDerivative.created_at.desc(),
                        LocalObservationAssetDerivative.id.desc(),
                    )
                ).first()
                if derivative is None:
                    raise _bad_material_error(
                        payload,
                        observation_id,
                        asset_id=item["asset_id"],
                        sort_order=item["sort_order"],
                        reason="derivative_missing",
                    )
                total_pixels += int(derivative.width) * int(derivative.height)
                photos.append(
                    {
                        "asset_id": item["asset_id"],
                        "derivative_id": derivative.id,
                        "content_hash": derivative.content_hash,
                        "format": item.get("format"),
                        "width": derivative.width,
                        "height": derivative.height,
                        "sort_order": item["sort_order"],
                    }
                )
            if is_empty_record(payload, valid_photo_count=len(photos)):
                raise _empty_record_error(payload, observation_id, len(photos))
            for field in missing_fields(payload):
                missing.append(
                    {"observation_id": observation_id, "field": field}
                )
            for warning in warnings(payload):
                warning_rows.append(
                    {"observation_id": observation_id, **dict(warning)}
                )
            records.append(
                {
                    "observation_id": observation_id,
                    "revision": draft.revision,
                    "payload_hash": draft.payload_hash,
                    "payload": payload,
                    "photos": photos,
                }
            )
    # Material hash/decode happens outside the read transaction.  Only the
    # frozen derivative ids/hashes recorded above are read.
    for record in records:
        for photo in record["photos"]:
            try:
                data = read_derivative_bytes(
                    session,
                    runtime,
                    profile_id=profile_id,
                    observation_id=record["observation_id"],
                    asset_id=photo["asset_id"],
                    derivative_id=photo["derivative_id"],
                )
            except (
                ObservationAssetNotFound,
                ObservationMaterialMissing,
                ObservationMaterialCorrupt,
                ObservationMaterialInvalid,
            ) as exc:
                raise _bad_material_error(
                    record["payload"],
                    record["observation_id"],
                    asset_id=photo["asset_id"],
                    derivative_id=photo["derivative_id"],
                    sort_order=photo["sort_order"],
                    reason="read_failed",
                ) from exc
            if hashlib.sha256(data).hexdigest() != photo["content_hash"]:
                raise _bad_material_error(
                    record["payload"],
                    record["observation_id"],
                    asset_id=photo["asset_id"],
                    derivative_id=photo["derivative_id"],
                    sort_order=photo["sort_order"],
                    reason="hash_mismatch",
                )
            total_photo_bytes += len(data)
            if total_photo_bytes > MAX_EXPORT_TOTAL_PHOTO_BYTES:
                raise ObservationExportContentTooLarge(
                    details={
                        "kind": "photo_bytes",
                        "actual_bytes": total_photo_bytes,
                        "limit_bytes": MAX_EXPORT_TOTAL_PHOTO_BYTES,
                    }
                )
    selection_hash = _selection_hash(records)
    missing_hash = _missing_hash(missing, warning_rows)
    manifest = {
        "version": 1,
        "template_version": "observation-templates-v1",
        "render_version": "observation-docx-v1",
        "profile_id": profile_id,
        "launch_id": launch_id,
        "session_scope_hash": _scope_hash(session_scope),
        "records": records,
        "missing": missing,
        "warnings": warning_rows,
        "missing_hash": missing_hash,
        "selection_hash": selection_hash,
        "total_payload_bytes": total_payload_bytes,
        "total_photo_bytes": total_photo_bytes,
        "total_pixels": total_pixels,
        "suggested_filename": _suggested_filename(records),
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(seconds=PREVIEW_TTL_SECONDS)).isoformat(),
    }
    return manifest, records


def _selection_hash(records: list[dict[str, Any]]) -> str:
    return hashlib.sha256(
        canonical_json(
            [
                {
                    "observation_id": record["observation_id"],
                    "revision": record["revision"],
                    "payload_hash": record["payload_hash"],
                    "photos": [
                        {
                            "asset_id": photo["asset_id"],
                            "derivative_id": photo["derivative_id"],
                            "content_hash": photo["content_hash"],
                            "sort_order": photo["sort_order"],
                        }
                        for photo in record["photos"]
                    ],
                }
                for record in records
            ]
        ).encode("utf-8")
    ).hexdigest()


def _missing_hash(
    missing: list[dict[str, Any]], warning_rows: list[dict[str, Any]]
) -> str:
    return hashlib.sha256(
        canonical_json({"missing": missing, "warnings": warning_rows}).encode("utf-8")
    ).hexdigest()


def _preview_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "observation_id": record["observation_id"],
            "record_type": record["payload"].get("record_type"),
            "observation_date": record["payload"].get("observation_date"),
            "start_time": record["payload"].get("start_time"),
            "subjects": _subject_names(record["payload"]),
            "revision": record["revision"],
            "payload_hash": record["payload_hash"],
            "photo_count": len(record["photos"]),
        }
        for record in records
    ]


def _binding_matches_locked(
    session: Session, *, profile_id: str, manifest: dict[str, Any]
) -> bool:
    """Minimal current-binding recheck; never decodes images or generates.

    Runs only inside the final ``BEGIN IMMEDIATE`` transaction.  It compares
    the ordered selected ids, each draft revision/aggregate hash, each draft
    photo association and its frozen export derivative id/hash/order, plus the
    stored missing-fact hash.  Any difference refuses the export.
    """
    records = manifest.get("records")
    if not isinstance(records, list) or not records:
        return False
    ids = [record.get("observation_id") for record in records]
    if (
        any(not isinstance(item, str) or not item for item in ids)
        or len(set(ids)) != len(ids)
    ):
        return False
    current_selection: list[dict[str, Any]] = []
    for record in records:
        observation_id = record["observation_id"]
        row = session.get(LocalObservationRecord, observation_id)
        draft = session.get(LocalObservationDraft, observation_id)
        if (
            row is None
            or row.creator_profile_id != profile_id
            or draft is None
            or row.current_draft_revision != draft.revision
            or draft.revision != record.get("revision")
            or draft.payload_hash != record.get("payload_hash")
        ):
            return False
        photos = list(
            session.scalars(
                select(LocalObservationDraftPhoto)
                .where(LocalObservationDraftPhoto.observation_id == observation_id)
                .order_by(LocalObservationDraftPhoto.sort_order)
            ).all()
        )
        expected_photos = record.get("photos") or []
        if len(photos) != len(expected_photos):
            return False
        asset_ids = [photo.asset_id for photo in photos]
        assets = {
            asset.id: asset
            for asset in session.scalars(
                select(LocalObservationAsset).where(
                    LocalObservationAsset.observation_id == observation_id,
                    LocalObservationAsset.id.in_(asset_ids),
                )
            ).all()
        } if asset_ids else {}
        derivatives: dict[str, LocalObservationAssetDerivative] = {}
        if asset_ids:
            for derivative in session.scalars(
                select(LocalObservationAssetDerivative)
                .where(
                    LocalObservationAssetDerivative.observation_id == observation_id,
                    LocalObservationAssetDerivative.purpose == "export",
                    LocalObservationAssetDerivative.asset_id.in_(asset_ids),
                )
                .order_by(
                    LocalObservationAssetDerivative.created_at.desc(),
                    LocalObservationAssetDerivative.id.desc(),
                )
            ).all():
                derivatives.setdefault(derivative.asset_id, derivative)
        compact_photos: list[dict[str, Any]] = []
        for index, photo in enumerate(photos):
            expected = expected_photos[index]
            asset = assets.get(photo.asset_id)
            derivative = derivatives.get(photo.asset_id)
            if (
                photo.sort_order != index
                or asset is None
                or derivative is None
                or asset.id != expected.get("asset_id")
                or derivative.id != expected.get("derivative_id")
                or derivative.content_hash != expected.get("content_hash")
                or expected.get("sort_order") != index
            ):
                return False
            compact_photos.append(
                {
                    "asset_id": asset.id,
                    "derivative_id": derivative.id,
                    "content_hash": derivative.content_hash,
                    "sort_order": index,
                }
            )
        current_selection.append(
            {
                "observation_id": observation_id,
                "revision": draft.revision,
                "payload_hash": draft.payload_hash,
                "photos": compact_photos,
            }
        )
    if _selection_hash(current_selection) != manifest.get("selection_hash"):
        return False
    if manifest.get("missing_hash") != _missing_hash(
        list(manifest.get("missing") or []),
        list(manifest.get("warnings") or []),
    ):
        return False
    return True


def prepare_export(
    session: Session,
    *,
    profile_id: str,
    request_id: Any,
    observation_ids: Any,
    launch_id: str,
    session_scope: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Explicit pre-export save for already-selected current drafts.

    This is a business save, deliberately separate from the read-only preview:
    every selected draft is saved with ``pre_export`` so a retained history
    node exists when the aggregate differs from the latest node (including
    after an auto save).  The request is receipt-backed; a retry replays the
    same deterministic per-record save requests.
    """
    if (
        not isinstance(observation_ids, list)
        or not observation_ids
        or any(not isinstance(item, str) or not item for item in observation_ids)
        or len(set(observation_ids)) != len(observation_ids)
    ):
        raise ObservationExportError(
            "observation_ids 必须是非空且不重复的 ID 数组"
        )
    selection_bytes = len(canonical_json(observation_ids).encode("utf-8"))
    if selection_bytes > MAX_EXPORT_SELECTION_BYTES:
        raise ObservationExportSelectionTooLarge(
            details={
                "actual_bytes": selection_bytes,
                "limit_bytes": MAX_EXPORT_SELECTION_BYTES,
            }
        )
    rid = normalize_request_id(request_id)
    fingerprint = _fingerprint(
        "observation_export_prepare",
        _canonical_request(
            {
                "profile_id": profile_id,
                "observation_ids": observation_ids,
                "launch_id": launch_id,
                "session_scope_hash": _scope_hash(session_scope),
            }
        ),
    )
    with read_scope(session):
        replay = _replay(session, profile_id, rid, fingerprint)
    if replay is not None:
        return replay
    now = now or utc_now()
    results: list[dict[str, Any]] = []
    for observation_id in observation_ids:
        current = read_current(
            session, profile_id=profile_id, observation_id=observation_id
        )
        payload = {
            key: value
            for key, value in current["payload"].items()
            if key != "term_snapshot"
        }
        photos = [
            {"asset_id": photo["asset_id"], "caption": photo.get("caption")}
            for photo in current["photos"]
        ]
        save_request_id = str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"{rid}:{observation_id}")
        )
        saved = save_observation(
            session,
            profile_id=profile_id,
            observation_id=observation_id,
            request_id=save_request_id,
            expected_revision=current["revision"],
            payload=payload,
            photos=photos,
            save_reason="pre_export",
            term_decision="keep_current",
            now=now,
        )
        results.append(
            {
                "observation_id": observation_id,
                "revision": saved["revision"],
                "payload_hash": saved["payload_hash"],
                "changed": saved["changed"],
                "history_created": saved["history_created"],
            }
        )
    result = {"records": results}
    begin_immediate(session)
    try:
        replay = _replay(session, profile_id, rid, fingerprint)
        if replay is not None:
            rollback(session)
            return replay
        _operation(
            session,
            profile_id=profile_id,
            request_id=rid,
            kind="observation_export_prepare",
            observation_id=None,
            fingerprint=fingerprint,
            result=result,
            now=now,
        )
        _audit_export(
            session,
            profile_id=profile_id,
            action="observation_export_prepare",
            target_id=observation_ids[0],
            now=now,
        )
        session.commit()
    except LocalError:
        rollback(session)
        raise
    except Exception:
        rollback(session)
        raise ObservationExportError("导出前保存回执写入失败")
    return result


def preview_export(
    session: Session,
    runtime: Any,
    *,
    profile_id: str,
    request_id: Any,
    observation_ids: Any,
    launch_id: str,
    session_scope: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    if (
        not isinstance(observation_ids, list)
        or not observation_ids
        or any(not isinstance(item, str) or not item for item in observation_ids)
        or len(set(observation_ids)) != len(observation_ids)
    ):
        raise ObservationExportError(
            "observation_ids 必须是非空且不重复的 ID 数组"
        )
    selection_bytes = len(canonical_json(observation_ids).encode("utf-8"))
    if selection_bytes > MAX_EXPORT_SELECTION_BYTES:
        raise ObservationExportSelectionTooLarge(
            details={
                "actual_bytes": selection_bytes,
                "limit_bytes": MAX_EXPORT_SELECTION_BYTES,
            }
        )
    rid = normalize_request_id(request_id)
    fingerprint = _fingerprint(
        "observation_export_preview",
        _canonical_request(
            {
                "profile_id": profile_id,
                "observation_ids": observation_ids,
                "launch_id": launch_id,
                "session_scope_hash": _scope_hash(session_scope),
            }
        ),
    )
    with read_scope(session):
        replay = _replay(session, profile_id, rid, fingerprint)
    if replay is not None:
        return replay
    now = now or utc_now()
    _cleanup_expired_snapshots(
        session,
        runtime,
        now,
        current_launch_id=launch_id,
        current_session_scope=session_scope,
    )
    manifest, records = _build_manifest(
        session,
        runtime,
        profile_id=profile_id,
        observation_ids=observation_ids,
        now=now,
        launch_id=launch_id,
        session_scope=session_scope,
    )
    manifest_hash = hashlib.sha256(canonical_json(manifest).encode("utf-8")).hexdigest()
    snapshot_id = new_opaque_id()
    result = {
        "snapshot_id": snapshot_id,
        "manifest_hash": manifest_hash,
        "expires_at": manifest["expires_at"],
        "selection_hash": manifest["selection_hash"],
        "missing_hash": manifest["missing_hash"],
        "missing": manifest["missing"],
        "warnings": manifest["warnings"],
        "requires_ack": bool(manifest["missing"]),
        "suggested_filename": manifest["suggested_filename"],
        "records": _preview_records(records),
    }
    begin_immediate(session)
    try:
        replay = _replay(session, profile_id, rid, fingerprint)
        if replay is not None:
            rollback(session)
            return replay
        session.add(
            LocalObservationExportSnapshot(
                id=snapshot_id,
                profile_id=profile_id,
                launch_id=launch_id,
                session_scope_hash=_scope_hash(session_scope),
                manifest_json=manifest,
                manifest_hash=manifest_hash,
                created_at=now,
                expires_at=now + timedelta(seconds=PREVIEW_TTL_SECONDS),
            )
        )
        _operation(
            session,
            profile_id=profile_id,
            request_id=rid,
            kind="observation_export_preview",
            observation_id=None,
            fingerprint=fingerprint,
            result=result,
            now=now,
        )
        _audit_export(
            session,
            profile_id=profile_id,
            action="observation_export_preview",
            target_id=snapshot_id,
            now=now,
        )
        session.commit()
    except LocalError:
        rollback(session)
        raise
    except Exception:
        rollback(session)
        raise ObservationExportError("导出预览保存失败")
    return result


def read_operation_receipt(
    session: Session, *, profile_id: str, request_id: Any
) -> dict[str, Any]:
    """Read a preview/create receipt; export kinds only."""
    from app.local.observation_service import (
        read_operation_receipt as _read_operation_receipt,
    )

    receipt = _read_operation_receipt(
        session, profile_id=profile_id, request_id=request_id
    )
    if receipt.get("operation_kind") not in (
        "observation_export_prepare",
        "observation_export_preview",
        "observation_export_create",
    ):
        raise ObservationExportNotFound()
    return receipt


def _snapshot(
    session: Session,
    *,
    profile_id: str,
    snapshot_id: str,
    launch_id: str,
    session_scope: str,
    now: datetime,
) -> LocalObservationExportSnapshot:
    row = session.get(LocalObservationExportSnapshot, snapshot_id)
    if (
        row is None
        or row.profile_id != profile_id
        or row.launch_id != launch_id
        or row.session_scope_hash != _scope_hash(session_scope)
    ):
        raise ObservationExportNotFound()
    if now > row.expires_at:
        raise ObservationExportSnapshotStale()
    return row


def check_export_content_limits(manifest: dict[str, Any]) -> None:
    """Check the aggregate byte budgets before materializing all photos.

    The pixel sum is deliberately diagnostic only: images are decoded one at
    a time during preview, so an aggregate pixel threshold would reject normal
    multi-record sets without protecting the real peak (the bytes held by the
    renderer plus the generated DOCX).
    """
    photo_bytes = int(manifest.get("total_photo_bytes") or 0)
    if photo_bytes > MAX_EXPORT_TOTAL_PHOTO_BYTES:
        raise ObservationExportContentTooLarge(
            details={
                "kind": "photo_bytes",
                "actual_bytes": photo_bytes,
                "limit_bytes": MAX_EXPORT_TOTAL_PHOTO_BYTES,
            }
        )
    payload_bytes = int(manifest.get("total_payload_bytes") or 0)
    if payload_bytes > MAX_EXPORT_TOTAL_PAYLOAD_BYTES:
        raise ObservationExportContentTooLarge(
            details={
                "kind": "text",
                "actual_bytes": payload_bytes,
                "limit_bytes": MAX_EXPORT_TOTAL_PAYLOAD_BYTES,
            }
        )


def _word_records(
    session: Session,
    runtime: Any,
    *,
    profile_id: str,
    manifest: dict[str, Any],
) -> tuple[ObservationWordRecord, ...]:
    result: list[ObservationWordRecord] = []
    check_export_content_limits(manifest)
    for record in manifest["records"]:
        photos: list[ObservationWordPhoto] = []
        for photo in record["photos"]:
            try:
                data = read_derivative_bytes(
                    session,
                    runtime,
                    profile_id=profile_id,
                    observation_id=record["observation_id"],
                    asset_id=photo["asset_id"],
                    derivative_id=photo["derivative_id"],
                )
            except (
                ObservationAssetNotFound,
                ObservationMaterialMissing,
                ObservationMaterialCorrupt,
                ObservationMaterialInvalid,
            ) as exc:
                raise _bad_material_error(
                    record["payload"],
                    record["observation_id"],
                    asset_id=photo["asset_id"],
                    derivative_id=photo["derivative_id"],
                    sort_order=photo["sort_order"],
                    reason="read_failed",
                ) from exc
            if hashlib.sha256(data).hexdigest() != photo["content_hash"]:
                raise _bad_material_error(
                    record["payload"],
                    record["observation_id"],
                    asset_id=photo["asset_id"],
                    derivative_id=photo["derivative_id"],
                    sort_order=photo["sort_order"],
                    reason="hash_mismatch",
                )
            photos.append(
                ObservationWordPhoto(
                    data=data,
                    width=int(photo["width"]),
                    height=int(photo["height"]),
                    content_hash=photo["content_hash"],
                )
            )
        result.append(
            ObservationWordRecord(
                payload=dict(record["payload"]), photos=tuple(photos)
            )
        )
    return tuple(result)


def _generate(
    session: Session, runtime: Any, *, profile_id: str, manifest: dict[str, Any]
) -> bytes:
    try:
        data = generate_observation_export_docx(
            _word_records(
                session, runtime, profile_id=profile_id, manifest=manifest
            )
        )
    except ObservationWordError as exc:
        raise ObservationExportBadMaterial(
            details={"reason": "generation_failed"}
        ) from exc
    if len(data) > MAX_EXPORT_DOCX_BYTES:
        raise ObservationExportTooLarge()
    return data


def _current_matches(
    session: Session,
    runtime: Any,
    *,
    profile_id: str,
    manifest: dict[str, Any],
    now: datetime,
) -> bool:
    try:
        current, _records = _build_manifest(
            session,
            runtime,
            profile_id=profile_id,
            observation_ids=[
                record["observation_id"] for record in manifest["records"]
            ],
            now=now,
            launch_id=manifest["launch_id"],
            session_scope="",
        )
    except LocalError:
        return False
    # _build_manifest binds a scope hash; compare the content facts only.
    return (
        current["selection_hash"] == manifest["selection_hash"]
        and current["missing_hash"] == manifest["missing_hash"]
    )


def _snapshot_retry_state(session: Session, snapshot_id: str) -> tuple[int, int]:
    token_count = int(
        session.scalar(
            select(func.count())
            .select_from(LocalObservationExportToken)
            .where(LocalObservationExportToken.snapshot_id == snapshot_id)
        )
        or 0
    )
    in_progress = int(
        session.scalar(
            select(func.count())
            .select_from(LocalObservationExportAttempt)
            .where(
                LocalObservationExportAttempt.snapshot_id == snapshot_id,
                LocalObservationExportAttempt.status == "in_progress",
            )
        )
        or 0
    )
    return token_count, in_progress


def create_export(
    session: Session,
    runtime: Any,
    *,
    profile_id: str,
    request_id: Any,
    snapshot_id: Any,
    ack_missing: Any,
    retry_existing: bool = False,
    launch_id: str,
    session_scope: str,
    now: datetime | None = None,
    _before_lock: Callable[[], None] | None = None,
) -> dict[str, Any]:
    if not isinstance(snapshot_id, str) or not snapshot_id:
        raise ObservationExportError("snapshot_id 不合法")
    if not isinstance(ack_missing, bool):
        raise ObservationExportError("ack_missing 必须是布尔值")
    if not isinstance(retry_existing, bool):
        raise ObservationExportError("retry_existing 必须是布尔值")
    rid = normalize_request_id(request_id)
    fingerprint = _fingerprint(
        "observation_export_create",
        _canonical_request(
            {
                "profile_id": profile_id,
                "snapshot_id": snapshot_id,
                "ack_missing": ack_missing,
                "retry_existing": retry_existing,
                "launch_id": launch_id,
                "session_scope_hash": _scope_hash(session_scope),
            }
        ),
    )
    with read_scope(session):
        replay = _replay(session, profile_id, rid, fingerprint)
    if replay is not None:
        return replay
    now = now or utc_now()
    _cleanup_expired_artifacts(runtime, now)
    _cleanup_expired_snapshots(
        session,
        runtime,
        now,
        current_launch_id=launch_id,
        current_session_scope=session_scope,
    )
    with read_scope(session):
        snapshot = _snapshot(
            session,
            profile_id=profile_id,
            snapshot_id=snapshot_id,
            launch_id=launch_id,
            session_scope=session_scope,
            now=now,
        )
        manifest = dict(snapshot.manifest_json or {})
        manifest_hash = snapshot.manifest_hash
        retry_state = (
            _snapshot_retry_state(session, snapshot_id) if retry_existing else None
        )
    if retry_existing:
        assert retry_state is not None
        token_count, in_progress = retry_state
        if token_count < 1:
            raise ObservationExportRetryUnavailable()
        if in_progress:
            raise ObservationExportAttemptInProgress()
    elif not _current_matches(
        session, runtime, profile_id=profile_id, manifest=manifest, now=now
    ):
        raise ObservationExportSnapshotStale()
    missing = list(manifest.get("missing") or [])
    if missing and not ack_missing:
        raise ObservationExportMissingUnconfirmed(details={"missing": missing})
    data = _generate(session, runtime, profile_id=profile_id, manifest=manifest)
    content_hash = hashlib.sha256(data).hexdigest()
    export_id = secrets.token_urlsafe(32)
    token_hash = _export_hash(export_id)
    expires_at = now + timedelta(seconds=TOKEN_TTL_SECONDS)
    _write_artifact(
        runtime,
        token_hash=token_hash,
        data=data,
        digest=content_hash,
        expires_at=expires_at,
        snapshot_id=snapshot_id,
        manifest_hash=manifest_hash,
        now=now,
    )
    try:
        if _before_lock is not None:
            _before_lock()
        begin_immediate(session)
        try:
            replay = _replay(session, profile_id, rid, fingerprint)
            if replay is not None:
                rollback(session)
                _delete_artifact(runtime, token_hash)
                return replay
            current_snapshot = session.get(
                LocalObservationExportSnapshot,
                snapshot_id,
                populate_existing=True,
            )
            if current_snapshot is None or now > current_snapshot.expires_at:
                rollback(session)
                _delete_artifact(runtime, token_hash)
                raise ObservationExportSnapshotStale()
            if retry_existing:
                token_count, in_progress = _snapshot_retry_state(
                    session, snapshot_id
                )
                if token_count < 1:
                    rollback(session)
                    _delete_artifact(runtime, token_hash)
                    raise ObservationExportRetryUnavailable()
                if in_progress:
                    rollback(session)
                    _delete_artifact(runtime, token_hash)
                    raise ObservationExportAttemptInProgress()
            elif not _binding_matches_locked(
                session, profile_id=profile_id, manifest=manifest
            ):
                rollback(session)
                _delete_artifact(runtime, token_hash)
                raise ObservationExportSnapshotStale()
            if missing and not ack_missing:
                rollback(session)
                _delete_artifact(runtime, token_hash)
                raise ObservationExportMissingUnconfirmed(
                    details={"missing": missing}
                )
            session.add(
                LocalObservationExportToken(
                    id=new_opaque_id(),
                    snapshot_id=snapshot_id,
                    profile_id=profile_id,
                    token_hash=token_hash,
                    expires_at=expires_at,
                    consumed_at=None,
                    created_at=now,
                )
            )
            result = {
                "export_id": export_id,
                "snapshot_id": snapshot_id,
                "manifest_hash": manifest_hash,
                "expires_at": expires_at.isoformat(),
                "filename": manifest.get("suggested_filename")
                or "游戏观察记录.docx",
                "byte_size": len(data),
                "content_hash": content_hash,
                "missing": missing,
                "warnings": list(manifest.get("warnings") or []),
            }
            _operation(
                session,
                profile_id=profile_id,
                request_id=rid,
                kind="observation_export_create",
                observation_id=None,
                fingerprint=fingerprint,
                result=result,
                now=now,
            )
            _audit_export(
                session,
                profile_id=profile_id,
                action="observation_export_create",
                target_id=snapshot_id,
                now=now,
            )
            session.commit()
        except LocalError:
            rollback(session)
            _delete_artifact(runtime, token_hash)
            raise
        except Exception:
            rollback(session)
            _delete_artifact(runtime, token_hash)
            raise ObservationExportError("导出凭证保存失败")
    except LocalError:
        _delete_artifact(runtime, token_hash)
        raise
    except Exception:
        _delete_artifact(runtime, token_hash)
        raise
    return result


def _token_row(
    session: Session,
    *,
    profile_id: str,
    export_id: str,
    launch_id: str,
    session_scope: str,
    now: datetime,
    require_active: bool,
) -> tuple[LocalObservationExportToken, LocalObservationExportSnapshot]:
    token_hash = _export_hash(export_id)
    row = session.scalars(
        select(LocalObservationExportToken).where(
            LocalObservationExportToken.token_hash == token_hash
        )
    ).first()
    if row is None or row.profile_id != profile_id:
        raise ObservationExportTokenInvalid()
    snapshot = session.get(LocalObservationExportSnapshot, row.snapshot_id)
    if (
        snapshot is None
        or snapshot.profile_id != profile_id
        or snapshot.launch_id != launch_id
        or snapshot.session_scope_hash != _scope_hash(session_scope)
    ):
        raise ObservationExportTokenInvalid()
    if require_active:
        if (
            row.consumed_at is not None
            or now > row.expires_at
            or now > snapshot.expires_at
        ):
            raise ObservationExportTokenInvalid()
    return row, snapshot


def _create_receipt_facts(
    session: Session,
    *,
    profile_id: str,
    export_id: str,
    token: LocalObservationExportToken,
    snapshot: LocalObservationExportSnapshot,
) -> dict[str, Any]:
    """Locate the exact committed create receipt for this bearer export id.

    The operation's JSON result contains the plaintext export id; SQLite JSON
    extraction finds that exact receipt without a recency scan/window.  A
    sidecar is mutable; this committed receipt is the persistent anchor for
    export_id/content hash/byte size/snapshot identity.
    """
    row = session.scalars(
        select(LocalObservationOperation).where(
            LocalObservationOperation.profile_id == profile_id,
            LocalObservationOperation.operation_kind
            == "observation_export_create",
            text(
                "json_extract(result_json, '$.export_id') = :export_id"
            ).bindparams(export_id=export_id),
        )
    ).first()
    if row is None:
        raise ObservationExportArtifactMismatch()
    result = dict(row.result_json or {})
    content_hash = result.get("content_hash")
    byte_size = result.get("byte_size")
    if (
        hashlib.sha256(export_id.encode("utf-8")).hexdigest() != token.token_hash
        or result.get("snapshot_id") != token.snapshot_id
        or result.get("manifest_hash") != snapshot.manifest_hash
        or not isinstance(content_hash, str)
        or not _HASH_RE.match(content_hash)
        or not isinstance(byte_size, int)
        or isinstance(byte_size, bool)
        or byte_size <= 0
        or byte_size > MAX_EXPORT_DOCX_BYTES
    ):
        raise ObservationExportArtifactMismatch()
    return {
        "token_hash": token.token_hash,
        "snapshot_id": token.snapshot_id,
        "manifest_hash": snapshot.manifest_hash,
        "content_hash": content_hash,
        "byte_size": byte_size,
    }


def read_export_content(
    session: Session,
    runtime: Any,
    *,
    profile_id: str,
    export_id: str,
    launch_id: str,
    session_scope: str,
    now: datetime | None = None,
) -> ExportArtifact:
    now = now or utc_now()
    with read_scope(session):
        token, snapshot_row = _token_row(
            session,
            profile_id=profile_id,
            export_id=export_id,
            launch_id=launch_id,
            session_scope=session_scope,
            now=now,
            require_active=True,
        )
        expected = _create_receipt_facts(
            session,
            profile_id=profile_id,
            export_id=export_id,
            token=token,
            snapshot=snapshot_row,
        )
    return _open_artifact(
        runtime, token_hash=token.token_hash, now=now, expected=expected
    )


def _filename(value: Any) -> str:
    if not isinstance(value, str):
        raise ObservationExportError("filename 必须是字符串")
    name = value.strip()
    if (
        not name
        or name in (".", "..")
        or len(name) > 200
        or any(char in _CONTROL for char in name)
        or "/" in name
        or "\\" in name
        or name.endswith(" ")
        or name.endswith(".")
    ):
        raise ObservationExportError("filename 不合法")
    stem = name.rsplit(".", 1)[0].strip().lower()
    if stem in _RESERVED_NAMES:
        raise ObservationExportError("filename 不合法")
    if not name.lower().endswith(".docx"):
        raise ObservationExportError("filename 必须是 .docx 文件")
    return name


def _attempt_payload(
    attempt: LocalObservationExportAttempt, *, filename: str, should_prompt: bool
) -> dict[str, Any]:
    return {
        "attempt_id": attempt.id,
        "status": attempt.status,
        "filename": filename,
        "should_prompt": should_prompt,
        "byte_size": attempt.byte_size,
        "result_hash": attempt.result_hash,
        "started_at": attempt.started_at.isoformat(),
        "ended_at": attempt.ended_at.isoformat() if attempt.ended_at else None,
    }


def _find_attempt(
    session: Session, *, profile_id: str, export_hash: str
) -> LocalObservationExportAttempt | None:
    return session.scalars(
        select(LocalObservationExportAttempt).where(
            LocalObservationExportAttempt.profile_id == profile_id,
            LocalObservationExportAttempt.export_id_hash == export_hash,
        )
    ).first()


def start_attempt(
    session: Session,
    runtime: Any,
    *,
    profile_id: str,
    export_id: str,
    filename: Any,
    launch_id: str,
    session_scope: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or utc_now()
    _cleanup_expired_snapshots(
        session,
        runtime,
        now,
        current_launch_id=launch_id,
        current_session_scope=session_scope,
    )
    name = _filename(filename)
    export_hash = _export_hash(export_id)
    fingerprint = hashlib.sha256(name.encode("utf-8")).hexdigest()
    begin_immediate(session)
    try:
        token, snapshot_row = _token_row(
            session,
            profile_id=profile_id,
            export_id=export_id,
            launch_id=launch_id,
            session_scope=session_scope,
            now=now,
            require_active=False,
        )
        existing = _find_attempt(
            session, profile_id=profile_id, export_hash=export_hash
        )
        if existing is not None:
            if existing.filename_fingerprint != fingerprint:
                rollback(session)
                raise ObservationExportAttemptConflict()
            if existing.snapshot_id != token.snapshot_id:
                rollback(session)
                raise ObservationExportTokenInvalid()
            payload = _attempt_payload(
                existing, filename=name, should_prompt=False
            )
            rollback(session)
            return payload
        if (
            token.consumed_at is not None
            or now > token.expires_at
            or now > snapshot_row.expires_at
        ):
            rollback(session)
            raise ObservationExportTokenInvalid()
        attempt = LocalObservationExportAttempt(
            id=new_opaque_id(),
            profile_id=profile_id,
            snapshot_id=token.snapshot_id,
            export_id_hash=export_hash,
            filename_fingerprint=fingerprint,
            status="in_progress",
            result_hash=None,
            byte_size=None,
            started_at=now,
            ended_at=None,
            created_at=now,
        )
        session.add(attempt)
        _audit_export(
            session,
            profile_id=profile_id,
            action="observation_export_attempt_start",
            target_id=token.snapshot_id,
            now=now,
        )
        session.commit()
        return _attempt_payload(attempt, filename=name, should_prompt=True)
    except LocalError:
        rollback(session)
        raise
    except Exception:
        rollback(session)
        raise ObservationExportError("导出保存尝试建立失败")


def read_attempt(
    session: Session,
    *,
    profile_id: str,
    export_id: str,
    attempt_id: str,
    launch_id: str,
    session_scope: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or utc_now()
    with read_scope(session):
        _token_row(
            session,
            profile_id=profile_id,
            export_id=export_id,
            launch_id=launch_id,
            session_scope=session_scope,
            now=now,
            require_active=False,
        )
        attempt = session.get(LocalObservationExportAttempt, attempt_id)
        if (
            attempt is None
            or attempt.profile_id != profile_id
            or attempt.export_id_hash != _export_hash(export_id)
        ):
            raise ObservationExportNotFound()
        return _attempt_result_payload(attempt)


def read_latest_attempt(
    session: Session,
    *,
    profile_id: str,
    export_id: str,
    launch_id: str,
    session_scope: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Read-only latest attempt query; never creates an attempt/dialog."""
    now = now or utc_now()
    with read_scope(session):
        _token_row(
            session,
            profile_id=profile_id,
            export_id=export_id,
            launch_id=launch_id,
            session_scope=session_scope,
            now=now,
            require_active=False,
        )
        attempt = session.scalars(
            select(LocalObservationExportAttempt)
            .where(
                LocalObservationExportAttempt.profile_id == profile_id,
                LocalObservationExportAttempt.export_id_hash == _export_hash(
                    export_id
                ),
            )
            .order_by(
                LocalObservationExportAttempt.started_at.desc(),
                LocalObservationExportAttempt.id.desc(),
            )
            .limit(1)
        ).first()
        if attempt is None:
            raise ObservationExportNotFound()
        return _attempt_result_payload(attempt)


def _attempt_result_payload(
    attempt: LocalObservationExportAttempt,
) -> dict[str, Any]:
    return {
        "attempt_id": attempt.id,
        "status": attempt.status,
        "byte_size": attempt.byte_size,
        "result_hash": attempt.result_hash,
        "started_at": attempt.started_at.isoformat(),
        "ended_at": attempt.ended_at.isoformat() if attempt.ended_at else None,
    }


def finish_attempt(
    session: Session,
    runtime: Any,
    *,
    profile_id: str,
    export_id: str,
    attempt_id: str,
    status: Any,
    byte_size: Any = None,
    result_hash: Any = None,
    launch_id: str,
    session_scope: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    if status not in ("saved", "cancelled", "failed", "indeterminate"):
        raise ObservationExportAttemptState()
    if byte_size is not None and (
        not isinstance(byte_size, int)
        or isinstance(byte_size, bool)
        or byte_size < 0
    ):
        raise ObservationExportAttemptState("byte_size 不合法")
    if result_hash is not None and (
        not isinstance(result_hash, str) or not _HASH_RE.match(result_hash)
    ):
        raise ObservationExportAttemptState("result_hash 不合法")
    if status == "saved" and (not byte_size or result_hash is None):
        raise ObservationExportAttemptState("成功保存必须报告字节数和摘要")
    now = now or utc_now()
    _cleanup_expired_snapshots(
        session,
        runtime,
        now,
        current_launch_id=launch_id,
        current_session_scope=session_scope,
    )
    token_hash = _export_hash(export_id)
    begin_immediate(session)
    try:
        token, _snapshot_row = _token_row(
            session,
            profile_id=profile_id,
            export_id=export_id,
            launch_id=launch_id,
            session_scope=session_scope,
            now=now,
            require_active=False,
        )
        attempt = session.get(LocalObservationExportAttempt, attempt_id)
        if (
            attempt is None
            or attempt.profile_id != profile_id
            or attempt.export_id_hash != token_hash
            or attempt.snapshot_id != token.snapshot_id
        ):
            rollback(session)
            raise ObservationExportNotFound()
        if attempt.status != "in_progress":
            if attempt.status == status:
                payload = {
                    "attempt_id": attempt.id,
                    "status": attempt.status,
                    "byte_size": attempt.byte_size,
                    "result_hash": attempt.result_hash,
                }
                rollback(session)
                return payload
            rollback(session)
            raise ObservationExportAttemptState()
        attempt.status = status
        attempt.byte_size = byte_size
        attempt.result_hash = result_hash
        attempt.ended_at = now
        token.consumed_at = now
        _audit_export(
            session,
            profile_id=profile_id,
            action="observation_export_attempt_result",
            target_id=attempt.snapshot_id,
            now=now,
        )
        session.commit()
    except LocalError:
        rollback(session)
        raise
    except Exception:
        rollback(session)
        raise ObservationExportError("导出保存结果记录失败")
    # The artifact is released only after the terminal receipt commits; an
    # in-flight stream keeps a ref and delays the unlink.
    _delete_artifact(runtime, token_hash)
    return {
        "attempt_id": attempt.id,
        "status": attempt.status,
        "byte_size": attempt.byte_size,
        "result_hash": attempt.result_hash,
    }
