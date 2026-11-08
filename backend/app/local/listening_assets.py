"""Managed listening photos: import, replace, remove, reorder and read.

Physical originals live under the existing atomic-restore asset root at
``observations/assets/listening/{record_id}/{asset_id}/original.<ext>``.
Ownership is always proven by the listening asset row plus the record/domain
guards; an observation record is never fabricated.

The low-level staging, handle verification, immutable move and byte-read
helpers are reused from :mod:`app.local.observation_assets` on purpose.  This
module adds the listening ownership, layout and database rules rather than a
second image I/O implementation.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ids import new_opaque_id
from app.local import backup_barrier, listening_direction
from app.local import listening_service as service
from app.local import observation_assets as obs
from app.local.base import utc_now
from app.local.errors import LocalError, LocalValidationError
from app.local.models import LocalListeningAsset
from app.local.normalize import normalize_request_id
from app.local.tx import begin_immediate, read_scope, rollback

LISTENING_ROOT = obs.ASSET_ROOT / "listening"
_EXTENSIONS = frozenset({"jpg", "png", "webp", "gif", "bmp"})


class ListeningAssetNotFound(LocalError):
    code = "LISTENING_ASSET_NOT_FOUND"
    status_code = 404
    message = "未找到该倾听照片"


class ListeningMaterialInvalid(LocalValidationError):
    code = "LISTENING_MATERIAL_INVALID"
    status_code = 422
    message = "倾听照片不合法"


class ListeningMaterialLimit(LocalValidationError):
    code = "LISTENING_MATERIAL_LIMIT"
    status_code = 422
    message = "倾听照片超过技术上限"


class ListeningMaterialMissing(LocalError):
    code = "LISTENING_MATERIAL_MISSING"
    status_code = 404
    message = "倾听照片文件不存在"


class ListeningMaterialCorrupt(LocalError):
    code = "LISTENING_MATERIAL_CORRUPT"
    status_code = 409
    message = "倾听照片文件损坏或身份不一致"


class ListeningAssetStorage(LocalError):
    code = "LISTENING_STORAGE_IO"
    status_code = 503
    message = "倾听照片保存失败"


class ListeningAssetRevisionConflict(LocalError):
    code = "LISTENING_REVISION_CONFLICT"
    status_code = 409
    message = "倾听记录已被其他保存更新，请刷新后重试"


class ListeningAssetRequestConflict(LocalError):
    code = "LISTENING_IDEMPOTENCY_CONFLICT"
    status_code = 409
    message = "同一请求 ID 使用了不同倾听照片操作内容"


class ListeningAssetProjectionMismatch(LocalError):
    code = "LISTENING_PROJECTION_MISMATCH"
    status_code = 409
    message = "倾听照片关联结构不一致"


class ListeningRotationCommitUncertain(LocalError):
    code = "LISTENING_ROTATION_COMMIT_UNCERTAIN"
    status_code = 503
    message = "照片方向提交结果不确定，请用原请求核对回执"


def _map_observation_error(exc: BaseException) -> LocalError:
    if isinstance(exc, obs.ObservationMaterialLimit):
        return ListeningMaterialLimit(str(exc))
    if isinstance(exc, obs.ObservationMaterialInvalid):
        return ListeningMaterialInvalid(str(exc))
    if isinstance(exc, obs.ObservationMaterialCorrupt):
        return ListeningMaterialCorrupt(str(exc))
    if isinstance(exc, obs.ObservationMaterialMissing):
        return ListeningMaterialMissing(str(exc))
    if isinstance(exc, obs.ObservationAssetStorage):
        return ListeningAssetStorage(str(exc))
    return ListeningAssetStorage("倾听照片操作失败")


def _safe_display_name(value: Any) -> str:
    try:
        return obs._safe_display_name(value)
    except LocalError as exc:
        raise _map_observation_error(exc) from None


def _hash_stream(stream: BinaryIO) -> str:
    try:
        return obs._hash_stream(stream)
    except LocalError as exc:
        raise _map_observation_error(exc) from None


def _asset_path(runtime: Any, record_id: str, asset_id: str, extension: str) -> Path:
    return (
        Path(runtime.data_dir)
        / LISTENING_ROOT
        / record_id
        / asset_id
        / f"original{extension}"
    )


def _asset_relative(
    runtime: Any, relative: str, record_id: str, asset_id: str
) -> Path:
    try:
        path = obs._managed_path(runtime, relative)
    except LocalError as exc:
        raise _map_observation_error(exc) from None
    try:
        rel = path.relative_to(Path(runtime.data_dir) / obs.ASSET_ROOT)
    except ValueError:
        raise ListeningMaterialInvalid("倾听照片路径越界") from None
    parts = rel.parts
    if (
        len(parts) != 4
        or parts[0] != "listening"
        or parts[1] != record_id
        or parts[2] != asset_id
    ):
        raise ListeningMaterialInvalid("倾听照片归属不一致")
    leaf = parts[3]
    if not leaf.startswith("original."):
        raise ListeningMaterialInvalid("倾听照片布局不一致")
    extension = leaf.split(".", 1)[1]
    if extension not in _EXTENSIONS:
        raise ListeningMaterialInvalid("倾听照片布局不一致")
    return path


def _group_for(
    session: Session, record_id: str, domain: str, group_id: str
):
    groups = service._groups(session, record_id, domain)
    for group in groups:
        if group.id == group_id:
            return group
    raise ListeningAssetNotFound()


def _read_verified_file(
    runtime: Any,
    relative: str,
    *,
    record_id: str,
    asset_id: str,
    expected_hash: str,
    expected_size: int,
) -> bytes:
    path = _asset_relative(runtime, relative, record_id, asset_id)
    root = Path(runtime.data_dir) / obs.ASSET_ROOT
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags | nofollow)
    except OSError:
        raise ListeningMaterialMissing() from None
    try:
        info = obs._verify_open_file(fd, path, root)
        if info.st_size != expected_size:
            raise ListeningMaterialCorrupt("倾听照片文件大小不一致")
        hasher = hashlib.sha256()
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            hasher.update(chunk)
            chunks.append(chunk)
        after = os.fstat(fd)
        if not obs._same_identity(info, after):
            raise ListeningMaterialCorrupt("倾听照片在读取期间发生变化")
        if hasher.hexdigest() != expected_hash:
            raise ListeningMaterialCorrupt("倾听照片文件哈希不一致")
        try:
            path_info = os.lstat(path)
        except OSError:
            raise ListeningMaterialCorrupt("倾听照片在读取期间被替换") from None
        if (
            not obs._same_identity(info, path_info)
            or getattr(path_info, "st_file_attributes", 0) & 0x400
            or getattr(path_info, "st_nlink", 1) != 1
        ):
            raise ListeningMaterialCorrupt("倾听照片在读取期间被替换")
        return b"".join(chunks)
    except LocalError as exc:
        raise _map_observation_error(exc) from None
    except OSError as exc:
        raise ListeningAssetStorage("读取倾听照片失败") from exc
    finally:
        os.close(fd)


def _import_fingerprint(
    *,
    profile_id: str,
    record_id: str,
    domain: str,
    group_id: str,
    expected_revision: int,
    display_name: str,
    content_hash: str,
) -> str:
    return service._fingerprint(
        "listening_asset_import",
        {
            "profile_id": profile_id,
            "record_id": record_id,
            "domain": domain,
            "group_id": group_id,
            "expected_revision": expected_revision,
            "display_name": display_name,
            "content_hash": content_hash,
        },
    )


def import_group_photo(
    session: Session,
    runtime: Any,
    *,
    profile_id: str,
    record_id: str,
    domain: str,
    group_id: str,
    request_id: Any,
    expected_revision: Any,
    stream: BinaryIO,
    display_name: Any,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Hold the file barrier across staging, publish and registration.

    The low-level helpers do not acquire the barrier themselves.  As in
    ``observation_assets.import_asset``, the entire file phase must be covered
    so an exclusive maintenance lease cannot observe or cross a partially
    written asset.  A refused scope performs zero managed writes.
    """
    with backup_barrier.file_scope(runtime.data_dir):
        return _import_group_photo_impl(
            session,
            runtime,
            profile_id=profile_id,
            record_id=record_id,
            domain=domain,
            group_id=group_id,
            request_id=request_id,
            expected_revision=expected_revision,
            stream=stream,
            display_name=display_name,
            now=now,
        )


def _import_group_photo_impl(
    session: Session,
    runtime: Any,
    *,
    profile_id: str,
    record_id: str,
    domain: str,
    group_id: str,
    request_id: Any,
    expected_revision: Any,
    stream: BinaryIO,
    display_name: Any,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate, stage, publish and register one listening original."""
    rid = normalize_request_id(request_id)
    revision = service._strict_revision(expected_revision)
    if domain not in service.DOMAINS:
        raise ListeningMaterialInvalid("领域标识不合法")
    if not isinstance(group_id, str) or not group_id:
        raise ListeningAssetNotFound()
    name = _safe_display_name(display_name)
    try:
        content_hash = _hash_stream(stream)
        stream.seek(0)
    except (AttributeError, OSError):
        raise ListeningMaterialInvalid("照片内容流不可重复读取") from None
    fingerprint = _import_fingerprint(
        profile_id=profile_id,
        record_id=record_id,
        domain=domain,
        group_id=group_id,
        expected_revision=revision,
        display_name=name,
        content_hash=content_hash,
    )
    with read_scope(session):
        replay = service._replay(
            session,
            profile_id,
            rid,
            fingerprint,
            expected_record_id=record_id,
            expected_kind="listening_asset_import",
        )
    if replay is not None:
        return replay
    with read_scope(session):
        service._load_record(session, profile_id, record_id)
        _group_for(session, record_id, domain, group_id)

    now = now or utc_now()
    attempt_id = new_opaque_id()
    staging_dir = obs._staging_root(runtime) / attempt_id
    try:
        obs._prepare_managed_dir(Path(runtime.data_dir), staging_dir)
        staged = staging_dir / "upload.bin"
        actual_hash, byte_size = obs._write_staging(
            staged, stream, Path(runtime.data_dir)
        )
        if actual_hash != content_hash:
            raise ListeningMaterialCorrupt("倾听照片暂存散列不一致")
        inspection = obs.inspect_managed_asset(
            staged, Path(runtime.data_dir), max_bytes=obs.MAX_SOURCE_BYTES
        )
        if (
            inspection.content_hash != actual_hash
            or inspection.byte_size != byte_size
        ):
            raise ListeningMaterialCorrupt("倾听照片暂存核验不一致")
        extension = obs._EXT_BY_FORMAT.get(inspection.image_format)
        if extension is None:
            raise ListeningMaterialInvalid("倾听照片格式不受支持")
        asset_id = new_opaque_id()
        target = _asset_path(runtime, record_id, asset_id, extension)
        obs._prepare_managed_dir(
            Path(runtime.data_dir) / LISTENING_ROOT, target.parent
        )
        obs._move_file(
            staged,
            target,
            Path(runtime.data_dir),
            expected_hash=inspection.content_hash,
            expected_size=inspection.byte_size,
        )
    except LocalError as exc:
        raise _map_observation_error(exc) from None
    except OSError as exc:
        raise ListeningAssetStorage("倾听照片暂存失败") from exc
    try:
        relative = obs._relative(runtime, target)
    except LocalError as exc:
        raise _map_observation_error(exc) from None

    begin_immediate(session)
    try:
        replay = service._replay(
            session,
            profile_id,
            rid,
            fingerprint,
            expected_record_id=record_id,
            expected_kind="listening_asset_import",
        )
        if replay is not None:
            rollback(session)
            return replay
        record, _context_value = service._load_record(
            session, profile_id, record_id
        )
        if record.revision != revision:
            raise ListeningAssetRevisionConflict()
        group = _group_for(session, record_id, domain, group_id)
        old_asset_id = group.asset_id
        session.add(
            LocalListeningAsset(
                id=asset_id,
                record_id=record_id,
                relative_path=relative,
                display_name=name,
                mime_type=obs._MIME_BY_FORMAT[inspection.image_format],
                content_hash=inspection.content_hash,
                byte_size=inspection.byte_size,
                width=inspection.width,
                height=inspection.height,
                orientation=inspection.orientation,
                rotation_quarters=0,
                created_at=now,
            )
        )
        group.asset_id = asset_id
        group.updated_at = now
        record.revision += 1
        record.updated_at = now
        result = {
            "record_id": record_id,
            "domain": domain,
            "group_id": group_id,
            "asset_id": asset_id,
            "old_asset_id": old_asset_id,
            "revision": record.revision,
            "content_hash": inspection.content_hash,
            "format": inspection.image_format,
            "width": inspection.width,
            "height": inspection.height,
            "orientation": inspection.orientation,
            "rotation_quarters": 0,
            "byte_size": inspection.byte_size,
            "changed": True,
            "saved_at": now.isoformat(),
        }
        service._operation(
            session,
            profile_id=profile_id,
            request_id=rid,
            kind="listening_asset_import",
            record_id=record_id,
            fingerprint=fingerprint,
            result=result,
            now=now,
        )
        service._audit(
            session,
            profile_id=profile_id,
            action="listening_asset_import",
            record_id=record_id,
            revision_after=record.revision,
            now=now,
        )
        session.commit()
        return result
    except LocalError:
        rollback(session)
        raise
    except IntegrityError as exc:
        rollback(session)
        raise ListeningAssetStorage() from exc
    except Exception as exc:
        rollback(session)
        raise ListeningAssetStorage() from exc


def remove_group_photo(
    session: Session,
    *,
    profile_id: str,
    record_id: str,
    domain: str,
    group_id: str,
    request_id: Any,
    expected_revision: Any,
    now: datetime | None = None,
) -> dict[str, Any]:
    rid = normalize_request_id(request_id)
    revision = service._strict_revision(expected_revision)
    if domain not in service.DOMAINS:
        raise ListeningMaterialInvalid("领域标识不合法")
    fingerprint = service._fingerprint(
        "listening_asset_remove",
        {
            "profile_id": profile_id,
            "record_id": record_id,
            "domain": domain,
            "group_id": group_id,
            "expected_revision": revision,
        },
    )
    with read_scope(session):
        replay = service._replay(
            session,
            profile_id,
            rid,
            fingerprint,
            expected_record_id=record_id,
            expected_kind="listening_asset_remove",
        )
    if replay is not None:
        return replay
    now = now or utc_now()
    begin_immediate(session)
    try:
        replay = service._replay(
            session,
            profile_id,
            rid,
            fingerprint,
            expected_record_id=record_id,
            expected_kind="listening_asset_remove",
        )
        if replay is not None:
            rollback(session)
            return replay
        record, _context_value = service._load_record(
            session, profile_id, record_id
        )
        if record.revision != revision:
            raise ListeningAssetRevisionConflict()
        group = _group_for(session, record_id, domain, group_id)
        old_asset_id = group.asset_id
        changed = old_asset_id is not None
        if changed:
            group.asset_id = None
            group.updated_at = now
            record.revision += 1
            record.updated_at = now
        result = {
            "record_id": record_id,
            "domain": domain,
            "group_id": group_id,
            "asset_id": None,
            "old_asset_id": old_asset_id,
            "revision": record.revision,
            "changed": changed,
            "saved_at": now.isoformat(),
        }
        service._operation(
            session,
            profile_id=profile_id,
            request_id=rid,
            kind="listening_asset_remove",
            record_id=record_id,
            fingerprint=fingerprint,
            result=result,
            now=now,
        )
        if changed:
            service._audit(
                session,
                profile_id=profile_id,
                action="listening_asset_remove",
                record_id=record_id,
                revision_after=record.revision,
                now=now,
            )
        session.commit()
        return result
    except LocalError:
        rollback(session)
        raise
    except IntegrityError as exc:
        rollback(session)
        raise ListeningAssetStorage() from exc
    except Exception as exc:
        rollback(session)
        raise ListeningAssetStorage() from exc


def reorder_groups(
    session: Session,
    *,
    profile_id: str,
    record_id: str,
    domain: str,
    request_id: Any,
    expected_revision: Any,
    group_ids: Any,
    now: datetime | None = None,
) -> dict[str, Any]:
    rid = normalize_request_id(request_id)
    revision = service._strict_revision(expected_revision)
    if domain not in service.DOMAINS:
        raise ListeningMaterialInvalid("领域标识不合法")
    if (
        not isinstance(group_ids, list)
        or len(group_ids) != 3
        or any(not isinstance(group_id, str) for group_id in group_ids)
        or len(set(group_ids)) != 3
    ):
        raise ListeningMaterialInvalid("排序必须提供三个不重复的图文组标识")
    fingerprint = service._fingerprint(
        "listening_photo_reorder",
        {
            "profile_id": profile_id,
            "record_id": record_id,
            "domain": domain,
            "expected_revision": revision,
            "group_ids": list(group_ids),
        },
    )
    with read_scope(session):
        replay = service._replay(
            session,
            profile_id,
            rid,
            fingerprint,
            expected_record_id=record_id,
            expected_kind="listening_photo_reorder",
        )
    if replay is not None:
        return replay
    now = now or utc_now()
    begin_immediate(session)
    try:
        replay = service._replay(
            session,
            profile_id,
            rid,
            fingerprint,
            expected_record_id=record_id,
            expected_kind="listening_photo_reorder",
        )
        if replay is not None:
            rollback(session)
            return replay
        record, _context_value = service._load_record(
            session, profile_id, record_id
        )
        if record.revision != revision:
            raise ListeningAssetRevisionConflict()
        groups = service._groups(session, record_id, domain)
        by_id = {group.id: group for group in groups}
        if set(group_ids) != set(by_id):
            raise ListeningMaterialInvalid("图文组不属于当前领域")
        current_order = [
            group.id for group in sorted(groups, key=lambda row: int(row.position))
        ]
        changed = current_order != group_ids
        if changed:
            # The unique (record, domain, position) constraint permits
            # multiple NULLs in SQLite.  NULL is therefore the intra-
            # transaction swap placeholder; the service never commits it.
            for group in groups:
                group.position = None
            session.flush()
            for position, group_id in enumerate(group_ids):
                group = by_id[group_id]
                group.position = position
                group.updated_at = now
            session.flush()
            record.revision += 1
            record.updated_at = now
        result = {
            "record_id": record_id,
            "domain": domain,
            "group_ids": list(group_ids),
            "revision": record.revision,
            "changed": changed,
            "saved_at": now.isoformat(),
        }
        service._operation(
            session,
            profile_id=profile_id,
            request_id=rid,
            kind="listening_photo_reorder",
            record_id=record_id,
            fingerprint=fingerprint,
            result=result,
            now=now,
        )
        if changed:
            service._audit(
                session,
                profile_id=profile_id,
                action="listening_photo_reorder",
                record_id=record_id,
                revision_after=record.revision,
                now=now,
            )
        session.commit()
        return result
    except LocalError:
        rollback(session)
        raise
    except IntegrityError as exc:
        rollback(session)
        raise ListeningAssetStorage() from exc
    except Exception as exc:
        rollback(session)
        raise ListeningAssetStorage() from exc


def _asset_for_group(
    session: Session, record_id: str, domain: str, group_id: str
):
    group = _group_for(session, record_id, domain, group_id)
    if not group.asset_id:
        raise ListeningAssetNotFound()
    asset = session.get(LocalListeningAsset, group.asset_id)
    if asset is None or asset.record_id != record_id:
        raise ListeningAssetProjectionMismatch()
    return group, asset


def read_rotations(
    session: Session,
    *,
    profile_id: str,
    record_id: str,
) -> dict[str, Any]:
    """Read-only map of current asset ids to manual quarter turns."""
    with read_scope(session):
        record, _context_value = service._load_record(
            session, profile_id, record_id
        )
        assets = session.scalars(
            select(LocalListeningAsset).where(
                LocalListeningAsset.record_id == record_id
            )
        ).all()
        by_id = {asset.id: asset for asset in assets}
        rotations: dict[str, int] = {}
        orientations: dict[str, int | None] = {}
        for domain in service.DOMAINS:
            for group in service._groups(session, record_id, domain):
                if group.asset_id is None:
                    continue
                asset = by_id.get(group.asset_id)
                if asset is None or asset.record_id != record_id:
                    raise ListeningAssetProjectionMismatch()
                rotations[asset.id] = int(asset.rotation_quarters or 0)
                orientations[asset.id] = asset.orientation
        return {
            "record_id": record_id,
            "revision": record.revision,
            "rotations": rotations,
            "orientations": orientations,
        }


def rotate_group_photo(
    session: Session,
    *,
    profile_id: str,
    record_id: str,
    domain: str,
    group_id: str,
    request_id: Any,
    expected_revision: Any,
    rotation_quarters: Any,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Persist one manual display rotation without touching original bytes."""
    rid = normalize_request_id(request_id)
    revision = service._strict_revision(expected_revision)
    if domain not in service.DOMAINS:
        raise ListeningMaterialInvalid("领域标识不合法")
    if not isinstance(group_id, str) or not group_id:
        raise ListeningAssetNotFound()
    try:
        target = listening_direction.normalize_rotation_quarters(
            rotation_quarters
        )
    except ValueError as exc:
        raise ListeningMaterialInvalid(str(exc)) from None
    fingerprint = service._fingerprint(
        "listening_asset_rotate",
        {
            "profile_id": profile_id,
            "record_id": record_id,
            "domain": domain,
            "group_id": group_id,
            "expected_revision": revision,
            "rotation_quarters": target,
        },
    )
    with read_scope(session):
        replay = service._replay(
            session,
            profile_id,
            rid,
            fingerprint,
            expected_record_id=record_id,
            expected_kind="listening_asset_rotate",
        )
    if replay is not None:
        return replay

    now = now or utc_now()
    commit_started = False
    try:
        begin_immediate(session)
        replay = service._replay(
            session,
            profile_id,
            rid,
            fingerprint,
            expected_record_id=record_id,
            expected_kind="listening_asset_rotate",
        )
        if replay is not None:
            rollback(session)
            return replay
        record, _context_value = service._load_record(
            session, profile_id, record_id
        )
        if record.revision != revision:
            raise ListeningAssetRevisionConflict()
        group, asset = _asset_for_group(
            session, record_id, domain, group_id
        )
        old_rotation = int(asset.rotation_quarters or 0)
        changed = old_rotation != target
        if changed:
            asset.rotation_quarters = target
            record.revision += 1
            record.updated_at = now
        result = {
            "record_id": record_id,
            "domain": domain,
            "group_id": group.id,
            "asset_id": asset.id,
            "revision": record.revision,
            "old_rotation_quarters": old_rotation,
            "rotation_quarters": int(asset.rotation_quarters or 0),
            "orientation": asset.orientation,
            "changed": changed,
            "saved_at": now.isoformat(),
        }
        service._operation(
            session,
            profile_id=profile_id,
            request_id=rid,
            kind="listening_asset_rotate",
            record_id=record_id,
            fingerprint=fingerprint,
            result=result,
            now=now,
        )
        if changed:
            service._audit(
                session,
                profile_id=profile_id,
                action="listening_asset_rotate",
                record_id=record_id,
                revision_after=record.revision,
                now=now,
            )
        commit_started = True
        session.commit()
        return result
    except LocalError as exc:
        rollback(session)
        if commit_started:
            raise ListeningRotationCommitUncertain() from exc
        raise
    except IntegrityError as exc:
        rollback(session)
        if commit_started:
            raise ListeningRotationCommitUncertain() from exc
        raise ListeningAssetStorage() from exc
    except Exception as exc:
        rollback(session)
        if commit_started:
            raise ListeningRotationCommitUncertain() from exc
        raise ListeningAssetStorage() from exc


def read_asset(
    session: Session,
    runtime: Any,
    *,
    profile_id: str,
    record_id: str,
    asset_id: str,
) -> tuple[bytes, dict[str, Any]]:
    with read_scope(session):
        service._load_record(session, profile_id, record_id)
        asset = session.scalars(
            select(LocalListeningAsset).where(
                LocalListeningAsset.record_id == record_id,
                LocalListeningAsset.id == asset_id,
            )
        ).first()
        if asset is None:
            raise ListeningAssetNotFound()
        metadata = {
            "asset_id": asset.id,
            "record_id": asset.record_id,
            "display_name": asset.display_name,
            "mime_type": asset.mime_type,
            "content_hash": asset.content_hash,
            "byte_size": asset.byte_size,
            "width": asset.width,
            "height": asset.height,
            "orientation": asset.orientation,
            "rotation_quarters": int(asset.rotation_quarters or 0),
        }
        relative = asset.relative_path
        expected_hash = asset.content_hash
        expected_size = asset.byte_size
    payload = _read_verified_file(
        runtime,
        relative,
        record_id=record_id,
        asset_id=asset_id,
        expected_hash=expected_hash,
        expected_size=expected_size,
    )
    return payload, metadata


__all__ = [
    "ListeningAssetNotFound",
    "ListeningMaterialInvalid",
    "ListeningMaterialLimit",
    "ListeningMaterialMissing",
    "ListeningMaterialCorrupt",
    "ListeningAssetStorage",
    "ListeningAssetRevisionConflict",
    "ListeningAssetRequestConflict",
    "ListeningAssetProjectionMismatch",
    "ListeningRotationCommitUncertain",
    "import_group_photo",
    "read_asset",
    "read_rotations",
    "remove_group_photo",
    "reorder_groups",
    "rotate_group_photo",
]
