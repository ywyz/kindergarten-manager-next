"""Protected batch import for one-to-one listening photos (teacher feedback #39).

The batch keeps the reviewed single-photo envelope: the whole file phase runs
under the backup barrier, bytes are staged and decoded before any association
is registered, and one SQLite transaction either links every target slot or
none.  A batch has its own request fingerprint and operation kind, but uses the
same listening asset rows, managed root and revision/audit records.

A target slot must still be empty at commit time.  Existing photos are never
replaced by the batch, even if another save filled a previewed slot while the
teacher was confirming.
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import stat
from datetime import datetime
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ids import new_opaque_id
from app.local import backup_barrier, listening_assets
from app.local import listening_service as service
from app.local import observation_assets as obs
from app.local.base import utc_now
from app.local.errors import LocalError, LocalValidationError
from app.local.models import LocalListeningAsset
from app.local.normalize import normalize_request_id
from app.local.tx import begin_immediate, read_scope, rollback

MAX_BATCH_FILES = 15
MAX_BATCH_TOTAL_BYTES = 75 * 1024 * 1024
MAX_BATCH_FIELD_BYTES = 8192
MAX_BATCH_PARTS = 3 + MAX_BATCH_FILES
_FILE_FIELD_RE = re.compile(r"^file_(\d{1,2})$")


class ListeningBatchTargetOccupied(LocalError):
    code = "LISTENING_BATCH_TARGET_OCCUPIED"
    status_code = 409
    message = "目标图位已有照片，已有照片不会被替换，请刷新预览后重试"


class ListeningBatchInvalid(LocalValidationError):
    code = "LISTENING_BATCH_INVALID"
    status_code = 422
    message = "批量倾听照片请求不合法"


class ListeningBatchCommitUncertain(LocalError):
    """The commit phase started, so deleting published files could lose photos.

    The receipt/retry path must decide whether the original operation exists.
    """

    code = "LISTENING_BATCH_COMMIT_UNCERTAIN"
    status_code = 503
    message = "批量照片提交结果不确定，请用原请求核对回执"


def _invalid(message: str) -> ListeningBatchInvalid:
    return ListeningBatchInvalid(message)


def _limit(message: str) -> listening_assets.ListeningMaterialLimit:
    return listening_assets.ListeningMaterialLimit(message)


def parse_batch_multipart(
    body: bytes, boundary: bytes
) -> tuple[dict[str, str], dict[int, bytes]]:
    """Parse the strict five-field batch envelope without python-multipart.

    Fields are ``request_id``, ``expected_revision`` and ``assignments`` (JSON),
    followed by ``file_0`` … ``file_14``.  The final boundary is mandatory,
    duplicate/unknown fields are refused, and the part/index limits are checked
    before the API ever touches the record.
    """
    marker = b"--" + boundary
    pos = 0
    if body.startswith(b"\r\n"):
        pos = 2
    if not body.startswith(marker, pos):
        raise _invalid("multipart 起始边界不合法")
    pos += len(marker)
    fields: dict[str, str] = {}
    files: dict[int, bytes] = {}
    parts = 0
    while True:
        if body.startswith(b"--", pos):
            pos += 2
            if body[pos : pos + 2] == b"\r\n":
                pos += 2
            if pos != len(body):
                raise _invalid("multipart 终止边界后存在多余内容")
            break
        if body[pos : pos + 2] != b"\r\n":
            raise _invalid("multipart 分段边界不合法")
        pos += 2
        header_end = body.find(b"\r\n\r\n", pos)
        if header_end < 0:
            raise _invalid("multipart 分段缺少头部终止")
        header_blob = body[pos:header_end]
        payload_start = header_end + 4
        next_marker = body.find(b"\r\n" + marker, payload_start)
        if next_marker < 0:
            raise _invalid("multipart 缺少终止边界")
        payload = body[payload_start:next_marker]
        pos = next_marker + 2 + len(marker)
        parts += 1
        if parts > MAX_BATCH_PARTS:
            raise _invalid("multipart 分段过多")
        headers = BytesParser(policy=policy.compat32).parsebytes(
            header_blob + b"\r\n\r\n"
        )
        disposition = str(headers.get("content-disposition") or "")
        if not disposition.lower().startswith("form-data"):
            raise _invalid("multipart 分段缺少表单声明")
        name = headers.get_param("name", header="content-disposition")
        if not name:
            raise _invalid("multipart 分段缺少字段名")
        filename = headers.get_filename()
        if filename is not None:
            match = _FILE_FIELD_RE.match(name)
            if match is None:
                raise _invalid("批量照片文件字段不合法")
            index = int(match.group(1))
            if index >= MAX_BATCH_FILES or index in files:
                raise _invalid("批量照片文件序号不合法或重复")
            files[index] = payload
            continue
        if name not in ("request_id", "expected_revision", "assignments"):
            raise _invalid("批量照片请求含未知字段")
        if name in fields:
            raise _invalid("multipart 字段重复")
        charset = headers.get_content_charset() or "utf-8"
        try:
            value = payload.decode(charset)
        except (LookupError, UnicodeDecodeError):
            raise _invalid("multipart 文本字段编码不合法") from None
        if len(value) > MAX_BATCH_FIELD_BYTES:
            raise _invalid("multipart 文本字段过长")
        fields[name] = value
    if not files:
        raise _invalid("缺少批量照片文件")
    return fields, files


def _normalize_assignments(
    assignments: Any, files: dict[int, bytes]
) -> list[dict[str, Any]]:
    if not isinstance(assignments, list):
        raise _invalid("照片落位信息必须是列表")
    if not 1 <= len(assignments) <= MAX_BATCH_FILES:
        raise _invalid(f"一次必须提交 1～{MAX_BATCH_FILES} 张照片")
    if len(files) != len(assignments):
        raise _invalid("照片数量与落位数量不一致")
    if sorted(files) != list(range(len(assignments))):
        raise _invalid("照片文件序号必须从 0 连续排列")
    items: list[dict[str, Any]] = []
    seen_groups: set[str] = set()
    total = 0
    for index, value in enumerate(assignments):
        if not isinstance(value, dict):
            raise _invalid("照片落位项必须是对象")
        if value.get("index") != index:
            raise _invalid("照片落位顺序不一致")
        domain = value.get("domain")
        if domain not in service.DOMAINS:
            raise _invalid("领域标识不合法")
        group_id = value.get("group_id")
        if not isinstance(group_id, str) or not group_id:
            raise _invalid("图位标识不合法")
        if group_id in seen_groups:
            raise _invalid("同一图位不能重复提交")
        seen_groups.add(group_id)
        display_name = listening_assets._safe_display_name(
            value.get("display_name") or f"photo-{index + 1}"
        )
        content = files[index]
        if not isinstance(content, (bytes, bytearray)) or len(content) == 0:
            raise _invalid("照片内容为空")
        if len(content) > obs.MAX_SOURCE_BYTES:
            raise _limit("图片超过单图字节上限")
        total += len(content)
        if total > MAX_BATCH_TOTAL_BYTES:
            raise _limit("批量照片合计超过总请求上限")
        items.append(
            {
                "index": index,
                "domain": domain,
                "group_id": group_id,
                "display_name": display_name,
                "content": bytes(content),
                "content_hash": hashlib.sha256(content).hexdigest(),
            }
        )
    return items


def batch_fingerprint(
    *,
    profile_id: str,
    record_id: str,
    expected_revision: int,
    items: list[dict[str, Any]],
) -> str:
    return service._fingerprint(
        "listening_asset_batch_import",
        {
            "profile_id": profile_id,
            "record_id": record_id,
            "expected_revision": expected_revision,
            "items": [
                {
                    "domain": item["domain"],
                    "group_id": item["group_id"],
                    "display_name": item["display_name"],
                    "content_hash": item["content_hash"],
                }
                for item in items
            ],
        },
    )


def _checksum(items: list[dict[str, Any]]) -> str:
    hasher = hashlib.sha256()
    for item in items:
        hasher.update(item["content_hash"].encode("ascii"))
        hasher.update(b"\0")
    return hasher.hexdigest()


def _target_groups(
    session: Session, record_id: str, items: list[dict[str, Any]]
) -> dict[str, Any]:
    groups_by_domain: dict[str, list[Any]] = {}
    resolved: dict[str, Any] = {}
    for item in items:
        domain = item["domain"]
        if domain not in groups_by_domain:
            groups_by_domain[domain] = service._groups(session, record_id, domain)
        group = next(
            (
                candidate
                for candidate in groups_by_domain[domain]
                if candidate.id == item["group_id"]
            ),
            None,
        )
        if group is None:
            raise listening_assets.ListeningAssetNotFound()
        resolved[item["group_id"]] = group
    return resolved


def _check_targets_empty(
    session: Session, record_id: str, items: list[dict[str, Any]]
) -> None:
    for group in _target_groups(session, record_id, items).values():
        if group.asset_id is not None:
            raise ListeningBatchTargetOccupied()


def _cleanup_roots(runtime: Any) -> tuple[Path, Path]:
    root = Path(runtime.data_dir).resolve()
    return (
        (root / listening_assets.LISTENING_ROOT).resolve(),
        (root / obs.STAGING_ROOT).resolve(),
    )


def _no_reparse_below_data(path: Path, runtime: Any) -> bool:
    """Check the leaf and every managed component below the data root."""
    base = Path(runtime.data_dir)
    current = path
    while current != base:
        try:
            info = os.lstat(current)
        except OSError:
            return False
        if (
            stat.S_ISLNK(info.st_mode)
            or getattr(info, "st_file_attributes", 0) & 0x400
        ):
            return False
        parent = current.parent
        if parent == current:
            return False
        current = parent
    return True


def _cleanup_exact(paths: list[Any], runtime: Any) -> None:
    """Remove only the exact leaf files this attempt created.

    No recursive directory deletion is used.  A path is unlinked only when it
    is absolute, resolves under this runtime's listening/staging root, is a
    regular file, and is not itself a link/reparse point.  Unknown or
    pre-existing entries are left for review.
    """
    asset_root, staging_root = _cleanup_roots(runtime)
    for value in paths:
        try:
            path = Path(value)
            if not path.is_absolute():
                continue
            resolved = path.resolve(strict=False)
            if not (
                resolved.is_relative_to(asset_root)
                or resolved.is_relative_to(staging_root)
            ):
                continue
            if not _no_reparse_below_data(path, runtime):
                continue
            info = os.lstat(path)
            if not stat.S_ISREG(info.st_mode):
                continue
            os.unlink(path)
        except (OSError, RuntimeError):
            continue


def _cleanup_staging_dir(staging_dir: Any, runtime: Any) -> None:
    """Remove one empty attempt directory directly under the staging root."""
    _, staging_root = _cleanup_roots(runtime)
    try:
        path = Path(staging_dir)
        if not path.is_absolute():
            return
        resolved = path.resolve(strict=False)
        if resolved.parent != staging_root:
            return
        if not _no_reparse_below_data(path, runtime):
            return
        info = os.lstat(path)
        if not stat.S_ISDIR(info.st_mode):
            return
        path.rmdir()
    except (OSError, RuntimeError):
        pass


def _cleanup_attempt(
    runtime: Any, paths: list[Any], staged: list[Any], staging_dir: Any
) -> None:
    _cleanup_exact(paths + staged, runtime)
    _cleanup_staging_dir(staging_dir, runtime)


def _rollback_quietly(session: Session) -> None:
    try:
        rollback(session)
    except Exception:  # noqa: BLE001 - preserve the original failure
        pass


def import_batch_photos(
    session: Session,
    runtime: Any,
    *,
    profile_id: str,
    record_id: str,
    request_id: Any,
    expected_revision: Any,
    assignments: Any,
    files: dict[int, bytes],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Publish and register 1–15 photos as one all-or-nothing operation."""
    with backup_barrier.file_scope(runtime.data_dir):
        return _import_batch_impl(
            session,
            runtime,
            profile_id=profile_id,
            record_id=record_id,
            request_id=request_id,
            expected_revision=expected_revision,
            assignments=assignments,
            files=files,
            now=now,
        )


def _import_batch_impl(
    session: Session,
    runtime: Any,
    *,
    profile_id: str,
    record_id: str,
    request_id: Any,
    expected_revision: Any,
    assignments: Any,
    files: dict[int, bytes],
    now: datetime | None = None,
) -> dict[str, Any]:
    rid = normalize_request_id(request_id)
    revision = service._strict_revision(expected_revision)
    items = _normalize_assignments(assignments, files)
    fingerprint = batch_fingerprint(
        profile_id=profile_id,
        record_id=record_id,
        expected_revision=revision,
        items=items,
    )
    with read_scope(session):
        replay = service._replay(
            session,
            profile_id,
            rid,
            fingerprint,
            expected_record_id=record_id,
            expected_kind="listening_asset_batch_import",
        )
    if replay is not None:
        return replay
    with read_scope(session):
        service._load_record(session, profile_id, record_id)
        _check_targets_empty(session, record_id, items)

    now = now or utc_now()
    attempt_id = new_opaque_id()
    staging_dir = obs._staging_root(runtime) / attempt_id
    staged_paths: list[Any] = []
    published_paths: list[Any] = []
    prepared: list[dict[str, Any]] = []
    try:
        obs._prepare_managed_dir(Path(runtime.data_dir), staging_dir)
        for item in items:
            staged = staging_dir / f"upload-{item['index']}.bin"
            staged_paths.append(staged)
            actual_hash, byte_size = obs._write_staging(
                staged, io.BytesIO(item["content"]), Path(runtime.data_dir)
            )
            if actual_hash != item["content_hash"]:
                raise listening_assets.ListeningMaterialCorrupt(
                    "倾听照片暂存散列不一致"
                )
            inspection = obs.inspect_managed_asset(
                staged, Path(runtime.data_dir), max_bytes=obs.MAX_SOURCE_BYTES
            )
            if (
                inspection.content_hash != actual_hash
                or inspection.byte_size != byte_size
            ):
                raise listening_assets.ListeningMaterialCorrupt(
                    "倾听照片暂存核验不一致"
                )
            extension = obs._EXT_BY_FORMAT.get(inspection.image_format)
            if extension is None:
                raise listening_assets.ListeningMaterialInvalid(
                    "倾听照片格式不受支持"
                )
            asset_id = new_opaque_id()
            target = listening_assets._asset_path(
                runtime, record_id, asset_id, extension
            )
            prepared.append(
                {
                    "item": item,
                    "staged": staged,
                    "target": target,
                    "asset_id": asset_id,
                    "inspection": inspection,
                }
            )
        # Every file has decoded successfully before the first publish.
        for entry in prepared:
            obs._prepare_managed_dir(
                Path(runtime.data_dir) / listening_assets.LISTENING_ROOT,
                entry["target"].parent,
            )
            obs._move_file(
                entry["staged"],
                entry["target"],
                Path(runtime.data_dir),
                expected_hash=entry["inspection"].content_hash,
                expected_size=entry["inspection"].byte_size,
            )
            published_paths.append(entry["target"])
        for entry in prepared:
            entry["relative"] = obs._relative(runtime, entry["target"])
    except LocalError as exc:
        _cleanup_attempt(runtime, published_paths, staged_paths, staging_dir)
        if isinstance(
            exc,
            (
                listening_assets.ListeningMaterialInvalid,
                listening_assets.ListeningMaterialLimit,
                listening_assets.ListeningMaterialCorrupt,
                listening_assets.ListeningMaterialMissing,
                listening_assets.ListeningAssetStorage,
                ListeningBatchTargetOccupied,
            ),
        ):
            raise
        raise listening_assets._map_observation_error(exc) from None
    except OSError as exc:
        _cleanup_attempt(runtime, published_paths, staged_paths, staging_dir)
        raise listening_assets.ListeningAssetStorage("倾听照片暂存失败") from exc

    commit_started = False
    try:
        # The write-lock acquisition is part of the same guarded phase: if it
        # refuses after publishing, the exact files created above are removed.
        begin_immediate(session)
        replay = service._replay(
            session,
            profile_id,
            rid,
            fingerprint,
            expected_record_id=record_id,
            expected_kind="listening_asset_batch_import",
        )
        if replay is not None:
            _rollback_quietly(session)
            _cleanup_attempt(runtime, published_paths, staged_paths, staging_dir)
            return replay
        record, _context_value = service._load_record(
            session, profile_id, record_id
        )
        if record.revision != revision:
            raise listening_assets.ListeningAssetRevisionConflict()
        groups = _target_groups(session, record_id, items)
        for entry in prepared:
            group = groups[entry["item"]["group_id"]]
            if group.asset_id is not None:
                raise ListeningBatchTargetOccupied()
        result_items: list[dict[str, Any]] = []
        for entry in prepared:
            item = entry["item"]
            inspection = entry["inspection"]
            group = groups[item["group_id"]]
            session.add(
                LocalListeningAsset(
                    id=entry["asset_id"],
                    record_id=record_id,
                    relative_path=entry["relative"],
                    display_name=item["display_name"],
                    mime_type=obs._MIME_BY_FORMAT[inspection.image_format],
                    content_hash=inspection.content_hash,
                    byte_size=inspection.byte_size,
                    width=inspection.width,
                    height=inspection.height,
                    orientation=inspection.orientation,
                    created_at=now,
                )
            )
            group.asset_id = entry["asset_id"]
            group.updated_at = now
            result_items.append(
                {
                    "domain": item["domain"],
                    "group_id": item["group_id"],
                    "asset_id": entry["asset_id"],
                    "old_asset_id": None,
                    "content_hash": inspection.content_hash,
                    "format": inspection.image_format,
                    "width": inspection.width,
                    "height": inspection.height,
                    "orientation": inspection.orientation,
                    "byte_size": inspection.byte_size,
                }
            )
        record.revision += 1
        record.updated_at = now
        result = {
            "record_id": record_id,
            "revision": record.revision,
            "changed": True,
            "saved_at": now.isoformat(),
            "batch_checksum": _checksum(items),
            "items": result_items,
        }
        service._operation(
            session,
            profile_id=profile_id,
            request_id=rid,
            kind="listening_asset_batch_import",
            record_id=record_id,
            fingerprint=fingerprint,
            result=result,
            now=now,
        )
        service._audit(
            session,
            profile_id=profile_id,
            action="listening_asset_batch_import",
            record_id=record_id,
            revision_after=record.revision,
            now=now,
        )
        commit_started = True
        session.commit()
        _cleanup_staging_dir(staging_dir, runtime)
        return result
    except LocalError as exc:
        _rollback_quietly(session)
        if commit_started:
            raise ListeningBatchCommitUncertain() from exc
        _cleanup_attempt(runtime, published_paths, staged_paths, staging_dir)
        raise
    except IntegrityError as exc:
        _rollback_quietly(session)
        if commit_started:
            raise ListeningBatchCommitUncertain() from exc
        _cleanup_attempt(runtime, published_paths, staged_paths, staging_dir)
        raise listening_assets.ListeningAssetStorage() from exc
    except Exception as exc:
        _rollback_quietly(session)
        if commit_started:
            raise ListeningBatchCommitUncertain() from exc
        _cleanup_attempt(runtime, published_paths, staged_paths, staging_dir)
        raise listening_assets.ListeningAssetStorage() from exc


__all__ = [
    "MAX_BATCH_FILES",
    "MAX_BATCH_TOTAL_BYTES",
    "MAX_BATCH_FIELD_BYTES",
    "ListeningBatchTargetOccupied",
    "ListeningBatchInvalid",
    "ListeningBatchCommitUncertain",
    "parse_batch_multipart",
    "batch_fingerprint",
    "import_batch_photos",
]
