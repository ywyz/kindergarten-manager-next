"""Managed observation image material: import, derivation, ordering and access.

E03 only.  Original bytes are immutable; AI/export JPEG derivatives are
separate, metadata-free working copies.  Decode/derive work happens outside the
database write transaction; only short metadata writes are transactional.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import hashlib
import io
import json
import msvcrt
import os
import re
import stat
import threading
import warnings
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO, Iterator

from PIL import Image, ImageCms, ImageOps
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ids import new_opaque_id
from app.local.base import utc_now
from app.local.errors import LocalError, LocalStorageError, LocalValidationError
from app.local.models import (
    LocalObservationAsset,
    LocalObservationAssetDerivative,
    LocalObservationDraft,
    LocalObservationDraftPhoto,
    LocalObservationOperation,
    LocalObservationRecord,
    LocalOperationRecord,
)
from app.local.normalize import normalize_request_id
from app.local.observation_validation import aggregate_hash
from app.local.tx import begin_immediate, read_scope, rollback

# Technical protection parameters measured from the delivered pipeline.  They
# are not teacher-facing business quotas; the working-set value is a review
# threshold, not a frozen product limit.
MAX_SOURCE_BYTES = 25 * 1024 * 1024
MAX_SOURCE_PIXELS = 40_000_000
MAX_SOURCE_SIDE = 8192
AI_MAX_SIDE = 2048
AI_QUALITY = 85
AI_TARGET_BYTES = 2 * 1024 * 1024
AI_PARAMS_VERSION = "ai-v2-2048-q85-target2mib-scale085"
EXPORT_MAX_SIDE = 2400
EXPORT_QUALITY = 90
EXPORT_PARAMS_VERSION = "export-v1-2400-q90"
WORKING_SET_BUDGET_MB = 1024

ASSET_ROOT = Path("observations") / "assets"
STAGING_ROOT = Path("observations") / "staging"
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_FORMAT_BY_MIME = {
    "image/jpeg": "jpeg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
    "image/bmp": "bmp",
}
_MIME_BY_FORMAT = {value: key for key, value in _FORMAT_BY_MIME.items()}
_EXT_BY_FORMAT = {
    "jpeg": ".jpg",
    "png": ".png",
    "webp": ".webp",
    "gif": ".gif",
    "bmp": ".bmp",
}
_DEVICE_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}
_IMAGE_LOCK = threading.Lock()
# Pillow's own bomb guard is aligned with the measured pixel ceiling.  The
# service also checks dimensions before load; this makes the warning/error path
# deterministic for crafted headers.
Image.MAX_IMAGE_PIXELS = MAX_SOURCE_PIXELS


class ObservationMaterialInvalid(LocalValidationError):
    code = "OBS_MATERIAL_INVALID"


class ObservationMaterialLimit(LocalValidationError):
    code = "OBS_MATERIAL_LIMIT"


class ObservationMaterialMissing(LocalError):
    code = "OBS_MATERIAL_MISSING"
    status_code = 404


class ObservationMaterialCorrupt(LocalError):
    code = "OBS_MATERIAL_CORRUPT"
    status_code = 409


class ObservationAssetNotFound(LocalError):
    code = "OBS_NOT_FOUND"
    status_code = 404


class ObservationAssetRevisionConflict(LocalError):
    code = "OBS_REVISION_CONFLICT"
    status_code = 409


class ObservationAssetRequestConflict(LocalError):
    code = "OBS_IDEMPOTENCY_CONFLICT"
    status_code = 409


class ObservationAssetStorage(LocalError):
    code = "OBS_STORAGE_IO"
    status_code = 503


class ObservationStorageProjectionMismatch(LocalError):
    code = "OBS_STORAGE_PROJECTION_MISMATCH"
    status_code = 409


@dataclass(frozen=True)
class ManagedAssetInspection:
    content_hash: str
    byte_size: int
    image_format: str
    width: int
    height: int
    orientation: int | None
    identity: tuple[int, int, int, int]


@dataclass(frozen=True)
class PreparedAsset:
    content_hash: str
    byte_size: int
    image_format: str
    mime_type: str
    width: int
    height: int
    orientation: int | None
    ai_bytes: bytes
    ai_width: int
    ai_height: int
    export_bytes: bytes
    export_width: int
    export_height: int


def _require_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise ObservationAssetNotFound("未找到该观察记录或材料")
    return value


def _normalize_caption(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ObservationMaterialInvalid("图片说明必须是字符串")
    cleaned = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    return cleaned or None


def _safe_display_name(value: Any) -> str:
    if not isinstance(value, str):
        raise ObservationMaterialInvalid("图片文件名不合法")
    if value != value.strip() or value.endswith(".") or value.endswith(" "):
        raise ObservationMaterialInvalid("图片文件名不合法")
    name = value.strip()
    if not name or len(name) > 255 or "\x00" in name:
        raise ObservationMaterialInvalid("图片文件名不合法")
    if any(ord(ch) < 32 for ch in name):
        raise ObservationMaterialInvalid("图片文件名不合法")
    if name in (".", "..") or "/" in name or "\\" in name or ":" in name:
        raise ObservationMaterialInvalid("图片文件名不合法")
    if name.endswith(".") or name.endswith(" "):
        raise ObservationMaterialInvalid("图片文件名不合法")
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", name):
        raise ObservationMaterialInvalid("图片文件名不合法")
    stem = name.split(".", 1)[0].lower()
    if stem in _DEVICE_NAMES:
        raise ObservationMaterialInvalid("图片文件名不合法")
    return name


def _fingerprint(kind: str, payload: dict[str, Any]) -> str:
    raw = json.dumps(
        {"kind": kind, "payload": payload},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _import_fingerprint(
    profile_id: str,
    observation_id: str,
    expected_revision: int,
    display_name: str,
    content_hash: str,
    caption: str | None,
) -> str:
    return _fingerprint(
        "asset_import",
        {
            "profile_id": profile_id,
            "observation_id": observation_id,
            "expected_revision": expected_revision,
            "display_name": display_name,
            "content_hash": content_hash,
            "caption": caption,
        },
    )


def _hash_stream(stream: BinaryIO) -> str:
    hasher = hashlib.sha256()
    total = 0
    while True:
        chunk = stream.read(1024 * 1024)
        if not chunk:
            break
        if not isinstance(chunk, (bytes, bytearray)):
            raise ObservationMaterialInvalid("图片流内容不合法")
        total += len(chunk)
        if total > MAX_SOURCE_BYTES:
            raise ObservationMaterialLimit("图片超过单图字节上限")
        hasher.update(chunk)
    return hasher.hexdigest()


def _discard_attempt(path: Path) -> None:
    """Do not recursively delete a path after the write boundary.

    The first E03 slice deliberately keeps successful staging directories and
    replay orphans for review.  A recursive delete here would allow an
    ancestor junction swap to remove files outside the managed root; cleanup
    requires a separately reviewed, handle-bound implementation.  This no-op
    never deletes assets or history.
    """
    return None


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
        raise ObservationAssetRequestConflict(
            "同一请求 ID 使用了不同图片或操作内容"
        )
    return dict(row.result_json or {})


def _record_draft(
    session: Session, profile_id: str, observation_id: str
) -> tuple[LocalObservationRecord, LocalObservationDraft]:
    record = session.get(LocalObservationRecord, observation_id)
    if record is None or record.creator_profile_id != profile_id:
        raise ObservationAssetNotFound("未找到该观察记录")
    draft = session.get(LocalObservationDraft, observation_id)
    if draft is None:
        raise ObservationAssetNotFound("观察草稿不存在")
    if record.current_draft_revision != draft.revision:
        raise ObservationStorageProjectionMismatch()
    manifest = _manifest(session, observation_id)
    expected = aggregate_hash(dict(draft.payload_json or {}), manifest)
    if draft.payload_hash != expected:
        raise ObservationStorageProjectionMismatch()
    return record, draft


def _manifest(
    session: Session, observation_id: str
) -> list[dict[str, Any]]:
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
    for photo, asset in rows:
        image_format = _FORMAT_BY_MIME.get(asset.mime_type)
        if image_format is None:
            raise ObservationMaterialCorrupt("图片格式记录损坏")
        manifest.append(
            {
                "asset_id": asset.id,
                "content_hash": asset.content_hash,
                "format": image_format,
                "width": asset.width,
                "height": asset.height,
                "orientation": asset.orientation,
                "sort_order": photo.sort_order,
                "caption": photo.caption,
            }
        )
    return manifest


def _photos(session: Session, observation_id: str) -> list[dict[str, Any]]:
    return _manifest(session, observation_id)


def _refresh_draft(
    session: Session,
    record: LocalObservationRecord,
    draft: LocalObservationDraft,
    *,
    now: datetime,
) -> str:
    manifest = _manifest(session, record.id)
    payload = dict(draft.payload_json or {})
    digest = aggregate_hash(payload, manifest)
    draft.revision += 1
    draft.payload_hash = digest
    draft.updated_at = now
    record.current_draft_revision = draft.revision
    record.updated_at = now
    return digest


def _staging_root(runtime: Any) -> Path:
    return runtime.data_dir / STAGING_ROOT


def _asset_root(runtime: Any) -> Path:
    return runtime.data_dir / ASSET_ROOT


def _check_no_reparse(path: Path, *, missing_ok: bool = True) -> None:
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        if missing_ok:
            return
        raise ObservationMaterialMissing("材料不存在") from None
    except OSError as exc:
        raise ObservationAssetStorage("无法检查材料路径") from exc
    if stat.S_ISLNK(info.st_mode) or (
        getattr(info, "st_file_attributes", 0) & 0x400
    ):
        raise ObservationMaterialInvalid("材料路径包含链接或重解析点")


def _ensure_managed_dir(root: Path, path: Path) -> None:
    try:
        relative = path.relative_to(root)
    except ValueError:
        raise ObservationMaterialInvalid("材料路径越界") from None
    current = root
    _check_no_reparse(current)
    for part in relative.parts:
        if part in ("", ".", "..") or ":" in part:
            raise ObservationMaterialInvalid("材料路径越界")
        current = current / part
        _check_no_reparse(current)
        if current.exists() and not current.is_dir():
            raise ObservationMaterialInvalid("材料路径不是目录")


def _relative(runtime: Any, path: Path) -> str:
    try:
        return path.relative_to(runtime.data_dir).as_posix()
    except ValueError:
        raise ObservationMaterialInvalid("材料路径越界") from None


def _validate_relative_components(relative: str) -> None:
    if (
        not isinstance(relative, str)
        or not relative
        or relative.startswith("/")
        or relative.startswith("\\")
        or "\\" in relative
        or "\x00" in relative
    ):
        raise ObservationMaterialInvalid("材料路径不合法")
    parts = relative.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ObservationMaterialInvalid("材料路径不合法")
    for part in parts:
        if ":" in part or part.endswith(".") or part.endswith(" "):
            raise ObservationMaterialInvalid("材料路径不合法")
        if any(ord(ch) < 32 for ch in part):
            raise ObservationMaterialInvalid("材料路径不合法")
        if part.split(".", 1)[0].lower() in _DEVICE_NAMES:
            raise ObservationMaterialInvalid("材料路径不合法")


def _managed_path(runtime: Any, relative: str) -> Path:
    _validate_relative_components(relative)
    path = runtime.data_dir / relative
    try:
        path.relative_to(runtime.data_dir)
    except ValueError:
        raise ObservationMaterialInvalid("材料路径越界") from None
    _ensure_managed_dir(runtime.data_dir, path.parent)
    return path


def _final_path_from_handle_value(handle: int) -> Path | None:
    """Windows final path for a native HANDLE; None if unverifiable."""
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.GetFinalPathNameByHandleW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
        ]
        kernel32.GetFinalPathNameByHandleW.restype = ctypes.c_uint32
        buffer = ctypes.create_unicode_buffer(32768)
        length = kernel32.GetFinalPathNameByHandleW(
            ctypes.c_void_p(handle), buffer, len(buffer), 0
        )
        if not length:
            return None
        value = buffer.value
        if value.startswith("\\\\?\\UNC\\"):
            value = "\\\\" + value[8:]
        elif value.startswith("\\\\?\\"):
            value = value[4:]
        return Path(value)
    except Exception:
        return None


def _final_path_from_handle(fd: int) -> Path | None:
    try:
        return _final_path_from_handle_value(msvcrt.get_osfhandle(fd))
    except Exception:
        return None


def _same_object(left: os.stat_result, right: os.stat_result) -> bool:
    if not left.st_ino or not right.st_ino:
        return False
    if not left.st_dev or not right.st_dev:
        return False
    return left.st_ino == right.st_ino and left.st_dev == right.st_dev


def _same_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return _same_object(left, right) and left.st_size == right.st_size


def _normalized_path(path: Path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def _verify_open_file(fd: int, path: Path, root: Path) -> os.stat_result:
    info = os.fstat(fd)
    if (
        not stat.S_ISREG(info.st_mode)
        or getattr(info, "st_file_attributes", 0) & 0x400
        or getattr(info, "st_nlink", 1) != 1
    ):
        raise ObservationMaterialCorrupt("材料文件不安全或已损坏")
    final = _final_path_from_handle(fd)
    if final is None:
        raise ObservationMaterialCorrupt("材料最终路径不可验证")
    try:
        final.relative_to(root)
    except ValueError:
        raise ObservationMaterialCorrupt("材料最终路径越界") from None
    if _normalized_path(final) != _normalized_path(path):
        raise ObservationMaterialCorrupt("材料最终路径不一致")
    return info


def _verify_handle_path(
    fd: int, path: Path, root: Path, *, error_cls: type[LocalError]
) -> os.stat_result:
    final = _final_path_from_handle(fd)
    if final is None:
        raise error_cls("材料句柄最终路径不可验证")
    try:
        final.relative_to(root)
    except ValueError:
        raise error_cls("材料最终路径越界") from None
    if _normalized_path(final) != _normalized_path(path):
        raise error_cls("材料最终路径不一致")
    info = os.fstat(fd)
    if (
        not stat.S_ISREG(info.st_mode)
        or getattr(info, "st_file_attributes", 0) & 0x400
        or getattr(info, "st_nlink", 1) != 1
    ):
        raise error_cls("材料文件不安全或已损坏")
    return info


def _open_dir_handle(path: Path) -> int:
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateFileW.argtypes = [
        ctypes.wintypes.LPCWSTR,
        ctypes.wintypes.DWORD,
        ctypes.wintypes.DWORD,
        ctypes.wintypes.LPVOID,
        ctypes.wintypes.DWORD,
        ctypes.wintypes.DWORD,
        ctypes.wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = ctypes.wintypes.HANDLE
    handle = kernel32.CreateFileW(
        str(path),
        0x00000080,  # FILE_READ_ATTRIBUTES
        0x00000001 | 0x00000002,  # share read/write, deliberately not delete
        None,
        3,  # OPEN_EXISTING
        0x02000000,  # FILE_FLAG_BACKUP_SEMANTICS
        None,
    )
    if handle in (None, ctypes.c_void_p(-1).value):
        raise ObservationAssetStorage("无法锁定材料目录")
    return int(handle)


@contextmanager
def _hold_managed_dirs(root: Path, path: Path) -> Iterator[None]:
    """Keep every parent directory open without delete sharing during I/O.

    A rename/junction swap of any checked ancestor is denied by Windows while
    the directory handles are held.  Each handle is also checked against its
    actual final path, so a junction that existed before the hold is rejected.
    """
    handles: list[int] = []
    try:
        current = root
        handles.append(_open_verified_dir(current, current))
        relative = path.parent.relative_to(root)
        for part in relative.parts:
            current = current / part
            handles.append(_open_verified_dir(current, current))
        yield
    finally:
        for handle in handles:
            try:
                ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(handle))
            except Exception:
                pass


def _open_verified_dir(path: Path, expected: Path) -> int:
    handle = _open_dir_handle(path)
    try:
        final = _final_path_from_handle_value(handle)
        if final is None or _normalized_path(final) != _normalized_path(expected):
            raise ObservationMaterialInvalid("材料目录最终路径不一致")
        return handle
    except Exception:
        try:
            ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(handle))
        except Exception:
            pass
        raise


def _prepare_managed_dir(root: Path, path: Path) -> None:
    try:
        _ensure_managed_dir(root, path)
        path.mkdir(parents=True, exist_ok=True)
        _ensure_managed_dir(root, path)
    except LocalError:
        raise
    except OSError as exc:
        raise ObservationAssetStorage("创建材料目录失败") from exc


def _write_staging(path: Path, stream: BinaryIO, root: Path) -> tuple[str, int]:
    _prepare_managed_dir(root, path.parent)
    hasher = hashlib.sha256()
    total = 0
    fd: int | None = None
    try:
        with _hold_managed_dirs(root, path):
            fd = os.open(
                path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
                0o600,
            )
            info = _verify_handle_path(
                fd, path, root, error_cls=ObservationAssetStorage
            )
            with os.fdopen(fd, "wb") as handle:
                fd = None
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    if not isinstance(chunk, (bytes, bytearray)):
                        raise ObservationMaterialInvalid("图片流内容不合法")
                    total += len(chunk)
                    if total > MAX_SOURCE_BYTES:
                        raise ObservationMaterialLimit("图片超过单图字节上限")
                    hasher.update(chunk)
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
                written = os.fstat(handle.fileno())
            if not _same_object(info, written) or written.st_size != total:
                raise ObservationAssetStorage("图片临时文件写入期间被替换")
            path_info = os.lstat(path)
            if (
                not _same_identity(written, path_info)
                or getattr(path_info, "st_file_attributes", 0) & 0x400
                or getattr(path_info, "st_nlink", 1) != 1
                or written.st_size != total
            ):
                raise ObservationAssetStorage("图片临时文件写入后身份不一致")
    except LocalError:
        raise
    except OSError as exc:
        raise ObservationAssetStorage("写入图片临时文件失败") from exc
    finally:
        if fd is not None:
            os.close(fd)
    return hasher.hexdigest(), total


def _validate_dimensions(width: int, height: int) -> None:
    if width < 1 or height < 1:
        raise ObservationMaterialInvalid("图片尺寸不合法")
    if width > MAX_SOURCE_SIDE or height > MAX_SOURCE_SIDE:
        raise ObservationMaterialLimit("图片单边超过技术上限")
    if width * height > MAX_SOURCE_PIXELS:
        raise ObservationMaterialLimit("图片像素总数超过技术上限")


def _validate_icc(image: Image.Image) -> None:
    icc = image.info.get("icc_profile")
    if not icc:
        return
    try:
        ImageCms.ImageCmsProfile(io.BytesIO(icc))
    except Exception:
        raise ObservationMaterialInvalid("图片 ICC 配置损坏") from None


_EXIF_TYPE_SIZES = {
    1: 1,   # BYTE
    2: 1,   # ASCII
    3: 2,   # SHORT
    4: 4,   # LONG
    5: 8,   # RATIONAL
    6: 1,   # SBYTE
    7: 1,   # UNDEFINED
    8: 2,   # SSHORT
    9: 4,   # SLONG
    10: 8,  # SRATIONAL
    11: 4,  # FLOAT
    12: 8,  # DOUBLE
    13: 4,  # IFD
}


_EXIF_POINTER_TAGS = {
    0x8769,  # Exif IFD
    0x8825,  # GPS IFD
    0xA005,  # Interop IFD
    0x014A,  # SubIFDs
}


def _u16(payload: bytes, offset: int, endian: str) -> int:
    return int.from_bytes(payload[offset:offset + 2], endian)


def _u32(payload: bytes, offset: int, endian: str) -> int:
    return int.from_bytes(payload[offset:offset + 4], endian)


def _entry_u32_values(
    payload: bytes, entry: bytes, endian: str, field_type: int, item_count: int
) -> list[int]:
    size = _EXIF_TYPE_SIZES[field_type] * item_count
    if size > 4:
        value_offset = _u32(entry, 8, endian)
        raw = payload[value_offset:value_offset + size]
    else:
        raw = entry[8:8 + size]
    if len(raw) != size or size % 4:
        raise ObservationMaterialInvalid("图片 EXIF 结构损坏")
    return [
        int.from_bytes(raw[index:index + 4], endian)
        for index in range(0, size, 4)
    ]


def _validate_tiff_exif(payload: bytes) -> None:
    if len(payload) < 8:
        raise ObservationMaterialInvalid("图片 EXIF 结构损坏")
    if payload[:2] == b"II":
        endian = "little"
    elif payload[:2] == b"MM":
        endian = "big"
    else:
        raise ObservationMaterialInvalid("图片 EXIF 结构损坏")
    if _u16(payload, 2, endian) != 42:
        raise ObservationMaterialInvalid("图片 EXIF 结构损坏")
    first_ifd = _u32(payload, 4, endian)
    if first_ifd < 8 or first_ifd + 2 > len(payload):
        raise ObservationMaterialInvalid("图片 EXIF 结构损坏")
    visiting: set[int] = set()
    validated: set[int] = set()

    def parse_ifd(offset: int, depth: int) -> None:
        if depth > 16 or offset < 8 or offset in visiting:
            raise ObservationMaterialInvalid("图片 EXIF 结构损坏")
        if offset in validated:
            return
        if offset + 2 > len(payload):
            raise ObservationMaterialInvalid("图片 EXIF 结构损坏")
        visiting.add(offset)
        count = _u16(payload, offset, endian)
        if count > 4096:
            raise ObservationMaterialInvalid("图片 EXIF 结构损坏")
        entries_start = offset + 2
        entries_end = entries_start + count * 12
        if entries_end + 4 > len(payload):
            raise ObservationMaterialInvalid("图片 EXIF 结构损坏")
        for index in range(count):
            start = entries_start + index * 12
            entry = payload[start:start + 12]
            field_type = _u16(entry, 2, endian)
            item_count = _u32(entry, 4, endian)
            if field_type not in _EXIF_TYPE_SIZES:
                raise ObservationMaterialInvalid("图片 EXIF 结构损坏")
            size = _EXIF_TYPE_SIZES[field_type] * item_count
            if item_count > 1_000_000:
                raise ObservationMaterialInvalid("图片 EXIF 结构损坏")
            if size > 4:
                value_offset = _u32(entry, 8, endian)
                if value_offset < 8 or value_offset + size > len(payload):
                    raise ObservationMaterialInvalid("图片 EXIF 结构损坏")
            tag = _u16(entry, 0, endian)
            if tag in _EXIF_POINTER_TAGS:
                if field_type not in (4, 13):
                    raise ObservationMaterialInvalid("图片 EXIF 结构损坏")
                for child in _entry_u32_values(
                    payload, entry, endian, field_type, item_count
                ):
                    parse_ifd(child, depth + 1)
        next_ifd = _u32(payload, entries_end, endian)
        if next_ifd:
            parse_ifd(next_ifd, depth + 1)
        visiting.remove(offset)
        validated.add(offset)

    parse_ifd(first_ifd, 0)


def _validate_exif_container(image: Image.Image) -> None:
    # Read the EXIF block through the already-open image/codec.  Re-opening the
    # path here would reintroduce the staging-path race R10 describes.
    raw = image.info.get("exif")
    if isinstance(raw, bytes) and raw:
        payload = raw[6:] if raw.startswith(b"Exif\x00\x00") else raw
        _validate_tiff_exif(payload)


def _orientation(image: Image.Image) -> int | None:
    try:
        value = image.getexif().get(0x0112)
    except Exception:
        raise ObservationMaterialInvalid("图片 EXIF 方向损坏") from None
    if value is None:
        return None
    if not isinstance(value, int) or not 1 <= value <= 8:
        raise ObservationMaterialInvalid("图片 EXIF 方向不合法")
    return value


def _encode_derivative(master: Image.Image, purpose: str) -> tuple[bytes, int, int]:
    if purpose == "ai":
        max_side, quality, target = AI_MAX_SIDE, AI_QUALITY, AI_TARGET_BYTES
    elif purpose == "export":
        max_side, quality, target = EXPORT_MAX_SIDE, EXPORT_QUALITY, None
    else:
        raise ValueError(purpose)
    if max(master.size) > max_side:
        scale = max_side / max(master.size)
        work = master.resize(
            (max(1, round(master.width * scale)), max(1, round(master.height * scale))),
            Image.Resampling.LANCZOS,
        )
        owns_work = True
    else:
        work = master
        owns_work = False
    clean: Image.Image | None = None
    try:
        # Never save ``work`` directly: Pillow copies ``info`` through
        # copy/convert and JPEG may inherit a source comment/ICC/EXIF block.
        # Paste pixels into a fresh container with empty metadata instead.
        if work.mode in ("RGBA", "LA", "P"):
            rgba = work.convert("RGBA")
            try:
                clean = Image.new("RGB", rgba.size, (255, 255, 255))
                clean.paste(rgba, mask=rgba.getchannel("A"))
            finally:
                rgba.close()
        else:
            rgb = work.convert("RGB")
            try:
                clean = Image.new("RGB", rgb.size)
                clean.paste(rgb)
            finally:
                rgb.close()
        clean.info = {}
        try:
            clean.getexif().clear()
        except Exception:
            pass
        for _attempt in range(6):
            buffer = io.BytesIO()
            clean.save(buffer, "JPEG", quality=quality, optimize=True)
            data = buffer.getvalue()
            if target is None or len(data) <= target:
                return data, clean.width, clean.height
            if min(clean.size) <= 256:
                break
            smaller = clean.resize(
                (max(1, int(clean.width * 0.85)), max(1, int(clean.height * 0.85))),
                Image.Resampling.LANCZOS,
            )
            clean.close()
            clean = smaller
        raise ObservationMaterialLimit("AI 派生图无法压缩到目标大小")
    finally:
        if clean is not None:
            clean.close()
        if owns_work:
            work.close()


def _master_image(image: Image.Image, max_side: int) -> Image.Image:
    if max(image.size) <= max_side:
        return image
    scale = max_side / max(image.size)
    return image.resize(
        (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
        Image.Resampling.LANCZOS,
    )


def _prepare_asset(source: Any) -> PreparedAsset:
    with _IMAGE_LOCK:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(source) as image:
                    image_format = (image.format or "").lower()
                    if image_format not in _MIME_BY_FORMAT:
                        raise ObservationMaterialInvalid("图片格式不受支持")
                    if getattr(image, "is_animated", False) or getattr(
                        image, "n_frames", 1
                    ) != 1:
                        raise ObservationMaterialInvalid("不支持动画图片")
                    width, height = image.size
                    _validate_dimensions(width, height)
                    _validate_exif_container(image)
                    orientation = _orientation(image)
                    _validate_icc(image)
                    master_side = max(AI_MAX_SIDE, EXPORT_MAX_SIDE)
                    if image_format == "jpeg" and max(width, height) > master_side:
                        image.draft("RGB", (master_side, master_side))
                    image.load()
                    # Downscale before an EXIF rotation.  Rotating the full
                    # 40MP transparent image first doubles the pixel buffer and
                    # was measured above the working-set budget.  The master
                    # only ever needs ``master_side``; 90/270 rotations keep
                    # the long side unchanged.
                    pre_oriented = _master_image(image, master_side)
                    owns_pre_oriented = pre_oriented is not image
                    try:
                        if orientation in (None, 1):
                            transposed = pre_oriented
                            owns_transposed = False
                        else:
                            transposed = ImageOps.exif_transpose(pre_oriented)
                            owns_transposed = transposed is not pre_oriented
                            transposed.load()
                        if owns_pre_oriented:
                            image.close()
                        master = transposed
                        try:
                            ai_bytes, ai_w, ai_h = _encode_derivative(master, "ai")
                            export_bytes, export_w, export_h = _encode_derivative(
                                master, "export"
                            )
                        finally:
                            if master is not transposed:
                                master.close()
                            if owns_transposed:
                                transposed.close()
                    finally:
                        if owns_pre_oriented:
                            pre_oriented.close()
                    return PreparedAsset(
                        content_hash="",
                        byte_size=0,
                        image_format=image_format,
                        mime_type=_MIME_BY_FORMAT[image_format],
                        width=width,
                        height=height,
                        orientation=orientation,
                        ai_bytes=ai_bytes,
                        ai_width=ai_w,
                        ai_height=ai_h,
                        export_bytes=export_bytes,
                        export_width=export_w,
                        export_height=export_h,
                    )
        except LocalError:
            raise
        except (Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise ObservationMaterialLimit("图片像素总数超过技术上限") from None
        except Image.UnidentifiedImageError:
            raise ObservationMaterialInvalid("无法识别图片格式") from None
        except (OSError, ValueError) as exc:
            raise ObservationMaterialCorrupt("图片解码失败或文件损坏") from exc


def managed_asset_path(
    runtime: Any,
    relative: str,
    observation_id: str,
    asset_id: str,
) -> Path:
    """Strict fixed layout/ownership check for a managed original."""
    return _asset_relative(
        runtime,
        relative,
        observation_id,
        asset_id,
        expected_leaf="original",
    )


def managed_derivative_path(
    runtime: Any,
    relative: str,
    observation_id: str,
    asset_id: str,
    derivative_id: str,
) -> Path:
    """Strict fixed layout/ownership check for one managed derivative."""
    return _asset_relative(
        runtime,
        relative,
        observation_id,
        asset_id,
        expected_leaf=derivative_id,
    )


def _prepare_staged_asset(path: Path, root: Path) -> PreparedAsset:
    """Decode the staging file through one verified handle while parents are pinned."""
    try:
        with _hold_managed_dirs(root, path):
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
            try:
                info = _verify_handle_path(
                    fd, path, root, error_cls=ObservationMaterialCorrupt
                )
                with os.fdopen(os.dup(fd), "rb") as handle:
                    prepared = _prepare_asset(handle)
                after = os.fstat(fd)
                path_info = os.lstat(path)
                if (
                    not _same_identity(info, after)
                    or not _same_identity(info, path_info)
                    or getattr(path_info, "st_file_attributes", 0) & 0x400
                    or getattr(path_info, "st_nlink", 1) != 1
                ):
                    raise ObservationMaterialCorrupt("材料文件在解码期间被替换")
                return prepared
            finally:
                os.close(fd)
    except LocalError:
        raise
    except OSError as exc:
        raise ObservationAssetStorage("读取图片临时文件失败") from exc


def inspect_managed_asset(path: Path, root: Path) -> ManagedAssetInspection:
    """Hash and decode one managed asset through the same verified handle.

    This is a read-only inspection for restore/history verification.  It does
    not rebuild AI/export derivatives and it never opens the path a second time.
    """
    try:
        with _hold_managed_dirs(root, path):
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
            try:
                info = _verify_handle_path(
                    fd, path, root, error_cls=ObservationMaterialCorrupt
                )
                if info.st_size > MAX_SOURCE_BYTES:
                    raise ObservationMaterialLimit("材料超过单图字节上限")
                hasher = hashlib.sha256()
                total = 0
                while True:
                    chunk = os.read(fd, 1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_SOURCE_BYTES:
                        raise ObservationMaterialLimit("材料超过单图字节上限")
                    hasher.update(chunk)
                os.lseek(fd, 0, os.SEEK_SET)
                with _IMAGE_LOCK:
                    with os.fdopen(os.dup(fd), "rb") as handle:
                        with warnings.catch_warnings():
                            warnings.simplefilter(
                                "error", Image.DecompressionBombWarning
                            )
                            with Image.open(handle) as image:
                                image_format = (image.format or "").lower()
                                if image_format not in _MIME_BY_FORMAT:
                                    raise ObservationMaterialInvalid("图片格式不受支持")
                                if getattr(image, "is_animated", False) or getattr(
                                    image, "n_frames", 1
                                ) != 1:
                                    raise ObservationMaterialInvalid("不支持动画图片")
                                width, height = image.size
                                _validate_dimensions(width, height)
                                _validate_exif_container(image)
                                orientation = _orientation(image)
                                _validate_icc(image)
                                image.load()
                after = os.fstat(fd)
                path_info = os.lstat(path)
                if (
                    not _same_identity(info, after)
                    or not _same_identity(info, path_info)
                    or getattr(path_info, "st_file_attributes", 0) & 0x400
                    or getattr(path_info, "st_nlink", 1) != 1
                ):
                    raise ObservationMaterialCorrupt("材料文件在核验期间被替换")
                identity = (
                    int(info.st_dev),
                    int(info.st_ino),
                    int(info.st_size),
                    int(info.st_mtime_ns),
                )
                return ManagedAssetInspection(
                    content_hash=hasher.hexdigest(),
                    byte_size=total,
                    image_format=image_format,
                    width=width,
                    height=height,
                    orientation=orientation,
                    identity=identity,
                )
            finally:
                os.close(fd)
    except LocalError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ObservationMaterialLimit("图片像素总数超过技术上限") from None
    except Image.UnidentifiedImageError:
        raise ObservationMaterialInvalid("无法识别图片格式") from None
    except OSError as exc:
        raise ObservationAssetStorage("核验材料失败") from exc


def verify_managed_asset_identity(
    path: Path,
    root: Path,
    expected_identity: tuple[int, int, int, int],
) -> None:
    """Short final-lock check: path/parents/final handle and identity only."""
    try:
        with _hold_managed_dirs(root, path):
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
            try:
                info = _verify_handle_path(
                    fd, path, root, error_cls=ObservationMaterialCorrupt
                )
                path_info = os.lstat(path)
                identity = (
                    int(info.st_dev),
                    int(info.st_ino),
                    int(info.st_size),
                    int(info.st_mtime_ns),
                )
                if (
                    identity != expected_identity
                    or not _same_identity(info, path_info)
                    or getattr(path_info, "st_file_attributes", 0) & 0x400
                    or getattr(path_info, "st_nlink", 1) != 1
                ):
                    raise ObservationMaterialCorrupt("材料文件身份已变化")
            finally:
                os.close(fd)
    except LocalError:
        raise
    except OSError as exc:
        raise ObservationAssetStorage("核验材料身份失败") from exc


def _move_file(
    source: Path,
    target: Path,
    root: Path,
    *,
    expected_hash: str,
    expected_size: int,
) -> None:
    try:
        _prepare_managed_dir(root, target.parent)
        if os.path.lexists(target):
            raise ObservationAssetStorage("材料目标已存在")
        source_fd = os.open(source, os.O_RDONLY | getattr(os, "O_BINARY", 0))
        try:
            source_info = _verify_handle_path(
                source_fd, source, root, error_cls=ObservationAssetStorage
            )
            if source_info.st_size != expected_size:
                raise ObservationAssetStorage("材料源文件大小不一致")
            hasher = hashlib.sha256()
            while True:
                chunk = os.read(source_fd, 1024 * 1024)
                if not chunk:
                    break
                hasher.update(chunk)
            if hasher.hexdigest() != expected_hash:
                raise ObservationAssetStorage("材料源文件哈希不一致")
        finally:
            os.close(source_fd)
        with _hold_managed_dirs(root, source), _hold_managed_dirs(root, target):
            source_path_info = os.lstat(source)
            if (
                not _same_identity(source_info, source_path_info)
                or getattr(source_path_info, "st_file_attributes", 0) & 0x400
                or getattr(source_path_info, "st_nlink", 1) != 1
                or os.path.lexists(target)
            ):
                raise ObservationAssetStorage("材料源文件或目标在落盘前被替换")
            os.replace(source, target)
            target_fd = os.open(target, os.O_RDONLY | getattr(os, "O_BINARY", 0))
            try:
                target_info = _verify_handle_path(
                    target_fd, target, root, error_cls=ObservationAssetStorage
                )
                if target_info.st_size != expected_size:
                    raise ObservationAssetStorage("材料落盘后大小不一致")
                hasher = hashlib.sha256()
                while True:
                    chunk = os.read(target_fd, 1024 * 1024)
                    if not chunk:
                        break
                    hasher.update(chunk)
                if hasher.hexdigest() != expected_hash:
                    raise ObservationAssetStorage("材料落盘后哈希不一致")
                target_path_info = os.lstat(target)
                if (
                    not _same_identity(target_info, target_path_info)
                    or getattr(target_path_info, "st_file_attributes", 0) & 0x400
                    or getattr(target_path_info, "st_nlink", 1) != 1
                ):
                    raise ObservationAssetStorage("材料落盘后身份不一致")
            finally:
                os.close(target_fd)
    except LocalError:
        raise
    except OSError as exc:
        raise ObservationAssetStorage("图片落盘失败") from exc


def import_asset(
    session: Session,
    runtime: Any,
    *,
    profile_id: str,
    observation_id: str,
    request_id: Any,
    expected_revision: Any,
    stream: BinaryIO,
    display_name: Any,
    caption: Any = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Import one image; return the committed result or an idempotent replay."""
    rid = normalize_request_id(request_id)
    if (
        not isinstance(expected_revision, int)
        or isinstance(expected_revision, bool)
        or expected_revision < 1
    ):
        raise ObservationMaterialInvalid("expected_revision 必须是正整数")
    _require_id(profile_id, "profile_id")
    _require_id(observation_id, "observation_id")
    name = _safe_display_name(display_name)
    normalized_caption = _normalize_caption(caption)
    now = now or utc_now()

    # Receipt priority: an already committed import can be read back by
    # request_id without a writable staging directory, image decode, or a
    # still-current draft.  The stream is hashed only to prove same content.
    with read_scope(session):
        existing = _receipt(session, profile_id, rid)
    if existing is not None:
        content_hash = _hash_stream(stream)
        fingerprint = _import_fingerprint(
            profile_id, observation_id, expected_revision, name,
            content_hash, normalized_caption,
        )
        with read_scope(session):
            replay = _replay(session, profile_id, rid, fingerprint)
        if replay is None:
            raise ObservationAssetRequestConflict()
        return replay

    with read_scope(session):
        _record_draft(session, profile_id, observation_id)

    attempt_id = new_opaque_id()
    staging_dir = _staging_root(runtime) / attempt_id
    _prepare_managed_dir(runtime.data_dir, staging_dir)
    staged = staging_dir / "upload.bin"
    content_hash, byte_size = _write_staging(staged, stream, runtime.data_dir)
    fingerprint = _import_fingerprint(
        profile_id, observation_id, expected_revision, name,
        content_hash, normalized_caption,
    )
    with read_scope(session):
        replay = _replay(session, profile_id, rid, fingerprint)
    if replay is not None:
        _discard_attempt(staging_dir)
        return replay

    prepared = _prepare_staged_asset(staged, runtime.data_dir)
    prepared = PreparedAsset(
        content_hash=content_hash,
        byte_size=byte_size,
        image_format=prepared.image_format,
        mime_type=prepared.mime_type,
        width=prepared.width,
        height=prepared.height,
        orientation=prepared.orientation,
        ai_bytes=prepared.ai_bytes,
        ai_width=prepared.ai_width,
        ai_height=prepared.ai_height,
        export_bytes=prepared.export_bytes,
        export_width=prepared.export_width,
        export_height=prepared.export_height,
    )
    asset_id = new_opaque_id()
    ai_id = new_opaque_id()
    export_id = new_opaque_id()
    asset_dir = _asset_root(runtime) / observation_id / asset_id
    _prepare_managed_dir(_asset_root(runtime), asset_dir)
    derivative_dir = asset_dir / "derivatives"
    _prepare_managed_dir(_asset_root(runtime), derivative_dir)
    original_path = asset_dir / f"original{_EXT_BY_FORMAT[prepared.image_format]}"
    ai_path = derivative_dir / f"{ai_id}.jpg"
    export_path = derivative_dir / f"{export_id}.jpg"
    staged_ai = staging_dir / f"{ai_id}.jpg"
    staged_export = staging_dir / f"{export_id}.jpg"
    ai_hash = hashlib.sha256(prepared.ai_bytes).hexdigest()
    export_hash = hashlib.sha256(prepared.export_bytes).hexdigest()
    _write_bytes_staging(staged_ai, prepared.ai_bytes, runtime.data_dir)
    _write_bytes_staging(staged_export, prepared.export_bytes, runtime.data_dir)
    _move_file(
        staged,
        original_path,
        runtime.data_dir,
        expected_hash=content_hash,
        expected_size=byte_size,
    )
    _move_file(
        staged_ai,
        ai_path,
        runtime.data_dir,
        expected_hash=ai_hash,
        expected_size=len(prepared.ai_bytes),
    )
    _move_file(
        staged_export,
        export_path,
        runtime.data_dir,
        expected_hash=export_hash,
        expected_size=len(prepared.export_bytes),
    )

    begin_immediate(session)
    try:
        replay = _replay(session, profile_id, rid, fingerprint)
        if replay is not None:
            rollback(session)
            _discard_attempt(staging_dir)
            _discard_attempt(asset_dir)
            return replay
        record, draft = _record_draft(session, profile_id, observation_id)
        if draft.revision != expected_revision:
            raise ObservationAssetRevisionConflict()
        session.add(
            LocalObservationAsset(
                id=asset_id,
                observation_id=observation_id,
                relative_path=_relative(runtime, original_path),
                display_name=name,
                mime_type=prepared.mime_type,
                content_hash=prepared.content_hash,
                byte_size=prepared.byte_size,
                width=prepared.width,
                height=prepared.height,
                orientation=prepared.orientation,
                created_at=now,
            )
        )
        session.add(
            LocalObservationAssetDerivative(
                id=ai_id,
                observation_id=observation_id,
                asset_id=asset_id,
                purpose="ai",
                params_version=AI_PARAMS_VERSION,
                content_hash=hashlib.sha256(prepared.ai_bytes).hexdigest(),
                mime_type="image/jpeg",
                width=prepared.ai_width,
                height=prepared.ai_height,
                relative_path=_relative(runtime, ai_path),
                created_at=now,
            )
        )
        session.add(
            LocalObservationAssetDerivative(
                id=export_id,
                observation_id=observation_id,
                asset_id=asset_id,
                purpose="export",
                params_version=EXPORT_PARAMS_VERSION,
                content_hash=hashlib.sha256(prepared.export_bytes).hexdigest(),
                mime_type="image/jpeg",
                width=prepared.export_width,
                height=prepared.export_height,
                relative_path=_relative(runtime, export_path),
                created_at=now,
            )
        )
        current = session.scalars(
            select(LocalObservationDraftPhoto)
            .where(LocalObservationDraftPhoto.observation_id == observation_id)
            .order_by(LocalObservationDraftPhoto.sort_order.desc())
        ).first()
        sort_order = (current.sort_order + 1) if current is not None else 0
        session.add(
            LocalObservationDraftPhoto(
                observation_id=observation_id,
                asset_id=asset_id,
                sort_order=sort_order,
                caption=normalized_caption,
            )
        )
        session.flush()
        digest = _refresh_draft(session, record, draft, now=now)
        result = {
            "asset_id": asset_id,
            "derivative_ids": {"ai": ai_id, "export": export_id},
            "revision": draft.revision,
            "payload_hash": digest,
            "photos": _photos(session, observation_id),
            "content_hash": prepared.content_hash,
            "format": prepared.image_format,
            "width": prepared.width,
            "height": prepared.height,
            "orientation": prepared.orientation,
            "changed": True,
        }
        session.add(
            LocalOperationRecord(
                id=new_opaque_id(),
                created_at=now,
                actor_id=profile_id,
                action="observation_asset_import",
                target_type="observation",
                target_id=observation_id,
                target_version_after=draft.revision,
            )
        )
        _operation(
            session,
            profile_id=profile_id,
            request_id=rid,
            kind="asset_import",
            observation_id=observation_id,
            fingerprint=fingerprint,
            result=result,
            now=now,
        )
        session.commit()
        _discard_attempt(staging_dir)
        return result
    except LocalError:
        rollback(session)
        raise
    except IntegrityError as exc:
        rollback(session)
        raise ObservationAssetStorage("图片数据库约束失败") from exc
    except Exception as exc:
        rollback(session)
        raise ObservationAssetStorage("图片数据库提交失败") from exc


def _write_bytes_staging(path: Path, data: bytes, root: Path) -> None:
    _write_staging(path, io.BytesIO(data), root)


def reorder_photos(
    session: Session,
    *,
    profile_id: str,
    observation_id: str,
    request_id: Any,
    expected_revision: Any,
    asset_ids: Any,
    now: datetime | None = None,
) -> dict[str, Any]:
    rid = normalize_request_id(request_id)
    if (
        not isinstance(expected_revision, int)
        or isinstance(expected_revision, bool)
        or expected_revision < 1
    ):
        raise ObservationMaterialInvalid("expected_revision 必须是正整数")
    if not isinstance(asset_ids, list) or any(
        not isinstance(item, str) for item in asset_ids
    ):
        raise ObservationMaterialInvalid("照片顺序不合法")
    if len(set(asset_ids)) != len(asset_ids):
        raise ObservationMaterialInvalid("照片顺序包含重复项")
    fingerprint = _fingerprint(
        "photo_reorder",
        {
            "profile_id": profile_id,
            "observation_id": observation_id,
            "expected_revision": expected_revision,
            "asset_ids": asset_ids,
        },
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
        record, draft = _record_draft(session, profile_id, observation_id)
        if draft.revision != expected_revision:
            raise ObservationAssetRevisionConflict()
        rows = session.scalars(
            select(LocalObservationDraftPhoto).where(
                LocalObservationDraftPhoto.observation_id == observation_id
            )
        ).all()
        current = {row.asset_id: row.caption for row in rows}
        if set(current) != set(asset_ids):
            raise ObservationMaterialInvalid("照片顺序与当前集合不一致")
        current_order = [
            row.asset_id
            for row in sorted(rows, key=lambda item: item.sort_order)
        ]
        if current_order == asset_ids:
            result = {
                "revision": draft.revision,
                "payload_hash": draft.payload_hash,
                "photos": _photos(session, observation_id),
                "changed": False,
            }
            _operation(
                session,
                profile_id=profile_id,
                request_id=rid,
                kind="photo_reorder",
                observation_id=observation_id,
                fingerprint=fingerprint,
                result=result,
                now=now,
            )
            session.commit()
            return result
        session.execute(
            delete(LocalObservationDraftPhoto).where(
                LocalObservationDraftPhoto.observation_id == observation_id
            )
        )
        session.flush()
        for order, asset_id in enumerate(asset_ids):
            session.add(
                LocalObservationDraftPhoto(
                    observation_id=observation_id,
                    asset_id=asset_id,
                    sort_order=order,
                    caption=current[asset_id],
                )
            )
        session.flush()
        digest = _refresh_draft(session, record, draft, now=now)
        result = {
            "revision": draft.revision,
            "payload_hash": digest,
            "photos": _photos(session, observation_id),
            "changed": True,
        }
        session.add(
            LocalOperationRecord(
                id=new_opaque_id(),
                created_at=now,
                actor_id=profile_id,
                action="observation_photo_reorder",
                target_type="observation",
                target_id=observation_id,
                target_version_after=draft.revision,
            )
        )
        _operation(
            session,
            profile_id=profile_id,
            request_id=rid,
            kind="photo_reorder",
            observation_id=observation_id,
            fingerprint=fingerprint,
            result=result,
            now=now,
        )
        session.commit()
        return result
    except LocalError:
        rollback(session)
        raise
    except IntegrityError as exc:
        rollback(session)
        raise ObservationAssetStorage("图片数据库约束失败") from exc
    except Exception as exc:
        rollback(session)
        raise ObservationAssetStorage("照片顺序保存失败") from exc


def set_caption(
    session: Session,
    *,
    profile_id: str,
    observation_id: str,
    request_id: Any,
    expected_revision: Any,
    asset_id: str,
    caption: Any,
    now: datetime | None = None,
) -> dict[str, Any]:
    rid = normalize_request_id(request_id)
    if (
        not isinstance(expected_revision, int)
        or isinstance(expected_revision, bool)
        or expected_revision < 1
    ):
        raise ObservationMaterialInvalid("expected_revision 必须是正整数")
    _require_id(asset_id, "asset_id")
    normalized_caption = _normalize_caption(caption)
    fingerprint = _fingerprint(
        "photo_caption",
        {
            "profile_id": profile_id,
            "observation_id": observation_id,
            "expected_revision": expected_revision,
            "asset_id": asset_id,
            "caption": normalized_caption,
        },
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
        record, draft = _record_draft(session, profile_id, observation_id)
        if draft.revision != expected_revision:
            raise ObservationAssetRevisionConflict()
        photo = session.get(LocalObservationDraftPhoto, (observation_id, asset_id))
        if photo is None:
            raise ObservationAssetNotFound("未找到当前图片")
        if photo.caption == normalized_caption:
            result = {
                "revision": draft.revision,
                "payload_hash": draft.payload_hash,
                "photos": _photos(session, observation_id),
                "changed": False,
            }
            _operation(
                session,
                profile_id=profile_id,
                request_id=rid,
                kind="photo_caption",
                observation_id=observation_id,
                fingerprint=fingerprint,
                result=result,
                now=now,
            )
            session.commit()
            return result
        photo.caption = normalized_caption
        session.flush()
        digest = _refresh_draft(session, record, draft, now=now)
        result = {
            "revision": draft.revision,
            "payload_hash": digest,
            "photos": _photos(session, observation_id),
            "changed": True,
        }
        session.add(
            LocalOperationRecord(
                id=new_opaque_id(),
                created_at=now,
                actor_id=profile_id,
                action="observation_photo_caption",
                target_type="observation",
                target_id=observation_id,
                target_version_after=draft.revision,
            )
        )
        _operation(
            session,
            profile_id=profile_id,
            request_id=rid,
            kind="photo_caption",
            observation_id=observation_id,
            fingerprint=fingerprint,
            result=result,
            now=now,
        )
        session.commit()
        return result
    except LocalError:
        rollback(session)
        raise
    except IntegrityError as exc:
        rollback(session)
        raise ObservationAssetStorage("图片数据库约束失败") from exc
    except Exception as exc:
        rollback(session)
        raise ObservationAssetStorage("图片说明保存失败") from exc


def remove_photo(
    session: Session,
    *,
    profile_id: str,
    observation_id: str,
    request_id: Any,
    expected_revision: Any,
    asset_id: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    rid = normalize_request_id(request_id)
    if (
        not isinstance(expected_revision, int)
        or isinstance(expected_revision, bool)
        or expected_revision < 1
    ):
        raise ObservationMaterialInvalid("expected_revision 必须是正整数")
    _require_id(asset_id, "asset_id")
    fingerprint = _fingerprint(
        "photo_remove",
        {
            "profile_id": profile_id,
            "observation_id": observation_id,
            "expected_revision": expected_revision,
            "asset_id": asset_id,
        },
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
        record, draft = _record_draft(session, profile_id, observation_id)
        if draft.revision != expected_revision:
            raise ObservationAssetRevisionConflict()
        rows = session.scalars(
            select(LocalObservationDraftPhoto)
            .where(LocalObservationDraftPhoto.observation_id == observation_id)
            .order_by(LocalObservationDraftPhoto.sort_order)
        ).all()
        if not any(row.asset_id == asset_id for row in rows):
            raise ObservationAssetNotFound("未找到当前图片")
        remaining = [
            (row.asset_id, row.caption) for row in rows if row.asset_id != asset_id
        ]
        # Rebuild the current association instead of updating sort_order in
        # place.  SQLAlchemy may order UPDATE statements by primary key, which
        # can transiently violate UNIQUE(observation_id, sort_order) when asset
        # IDs and display order differ.  Draft photos are the current
        # order/caption authority; this rebuilds that association in the same
        # transaction while assets, versions and AI inputs remain untouched.
        session.execute(
            delete(LocalObservationDraftPhoto).where(
                LocalObservationDraftPhoto.observation_id == observation_id
            )
        )
        session.flush()
        for order, (remaining_asset_id, caption) in enumerate(remaining):
            session.add(
                LocalObservationDraftPhoto(
                    observation_id=observation_id,
                    asset_id=remaining_asset_id,
                    sort_order=order,
                    caption=caption,
                )
            )
        session.flush()
        digest = _refresh_draft(session, record, draft, now=now)
        result = {
            "revision": draft.revision,
            "payload_hash": digest,
            "photos": _photos(session, observation_id),
            "changed": True,
        }
        session.add(
            LocalOperationRecord(
                id=new_opaque_id(),
                created_at=now,
                actor_id=profile_id,
                action="observation_photo_remove",
                target_type="observation",
                target_id=observation_id,
                target_version_after=draft.revision,
            )
        )
        _operation(
            session,
            profile_id=profile_id,
            request_id=rid,
            kind="photo_remove",
            observation_id=observation_id,
            fingerprint=fingerprint,
            result=result,
            now=now,
        )
        session.commit()
        return result
    except LocalError:
        rollback(session)
        raise
    except IntegrityError as exc:
        rollback(session)
        raise ObservationAssetStorage("图片数据库约束失败") from exc
    except Exception as exc:
        rollback(session)
        raise ObservationAssetStorage("图片移除保存失败") from exc


def list_photos(
    session: Session, *, profile_id: str, observation_id: str
) -> list[dict[str, Any]]:
    with read_scope(session):
        _record_draft(session, profile_id, observation_id)
        return _photos(session, observation_id)


def _asset_relative(
    runtime: Any,
    relative: str,
    observation_id: str,
    asset_id: str,
    *,
    expected_leaf: str,
) -> Path:
    path = _managed_path(runtime, relative)
    try:
        rel = path.relative_to(runtime.data_dir / ASSET_ROOT)
    except ValueError:
        raise ObservationMaterialInvalid("材料路径越界") from None
    parts = rel.parts
    if len(parts) < 3 or parts[0] != observation_id or parts[1] != asset_id:
        raise ObservationMaterialInvalid("材料归属不一致")
    if expected_leaf == "original":
        if len(parts) != 3 or not parts[2].startswith("original."):
            raise ObservationMaterialInvalid("材料布局不一致")
        if parts[2].split(".", 1)[1] not in ("jpg", "png", "webp", "gif", "bmp"):
            raise ObservationMaterialInvalid("材料布局不一致")
    else:
        if (
            len(parts) != 4
            or parts[2] != "derivatives"
            or parts[3] != f"{expected_leaf}.jpg"
        ):
            raise ObservationMaterialInvalid("材料布局不一致")
    return path


def _read_verified_file(
    runtime: Any,
    relative: str,
    *,
    observation_id: str,
    asset_id: str,
    expected_hash: str,
    expected_size: int | None,
    expected_leaf: str,
    max_bytes: int | None = None,
) -> bytes:
    path = _asset_relative(
        runtime, relative, observation_id, asset_id, expected_leaf=expected_leaf
    )
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags | nofollow)
    except OSError:
        raise ObservationMaterialMissing("材料不存在") from None
    try:
        info = _verify_open_file(fd, path, runtime.data_dir / ASSET_ROOT)
        if expected_size is not None and info.st_size != expected_size:
            raise ObservationMaterialCorrupt("材料文件大小不一致")
        if max_bytes is not None and info.st_size > max_bytes:
            raise ObservationMaterialLimit("材料超过读取上限")
        hasher = hashlib.sha256()
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if max_bytes is not None and total > max_bytes:
                raise ObservationMaterialLimit("材料超过读取上限")
            hasher.update(chunk)
            chunks.append(chunk)
        after = os.fstat(fd)
        if not _same_identity(info, after):
            raise ObservationMaterialCorrupt("材料文件在读取期间发生变化")
        if hasher.hexdigest() != expected_hash:
            raise ObservationMaterialCorrupt("材料文件哈希不一致")
        try:
            path_info = os.lstat(path)
        except OSError:
            raise ObservationMaterialCorrupt("材料文件在读取期间被替换") from None
        if (
            not _same_identity(info, path_info)
            or getattr(path_info, "st_file_attributes", 0) & 0x400
            or getattr(path_info, "st_nlink", 1) != 1
        ):
            raise ObservationMaterialCorrupt("材料文件在读取期间被替换")
        return b"".join(chunks)
    except LocalError:
        raise
    except OSError as exc:
        raise ObservationAssetStorage("读取材料失败") from exc
    finally:
        os.close(fd)


def read_asset_bytes(
    session: Session,
    runtime: Any,
    *,
    profile_id: str,
    observation_id: str,
    asset_id: str,
) -> bytes:
    with read_scope(session):
        _record_draft(session, profile_id, observation_id)
        asset = session.scalars(
            select(LocalObservationAsset).where(
                LocalObservationAsset.observation_id == observation_id,
                LocalObservationAsset.id == asset_id,
            )
        ).first()
        if asset is None:
            raise ObservationAssetNotFound("未找到图片")
        relative = asset.relative_path
        expected_hash = asset.content_hash
        expected_size = asset.byte_size
    return _read_verified_file(
        runtime,
        relative,
        observation_id=observation_id,
        asset_id=asset_id,
        expected_hash=expected_hash,
        expected_size=expected_size,
        expected_leaf="original",
    )


def read_derivative_bytes(
    session: Session,
    runtime: Any,
    *,
    profile_id: str,
    observation_id: str,
    asset_id: str,
    derivative_id: str | None = None,
    purpose: str | None = None,
    params_version: str | None = None,
    max_bytes: int | None = None,
) -> bytes:
    if derivative_id is None and (purpose is None or params_version is None):
        raise ObservationMaterialInvalid(
            "读取派生图片必须给出 derivative_id，或 purpose 与 params_version"
        )
    with read_scope(session):
        _record_draft(session, profile_id, observation_id)
        statement = select(LocalObservationAssetDerivative).where(
            LocalObservationAssetDerivative.observation_id == observation_id,
            LocalObservationAssetDerivative.asset_id == asset_id,
        )
        if derivative_id is not None:
            statement = statement.where(
                LocalObservationAssetDerivative.id == derivative_id
            )
        else:
            statement = statement.where(
                LocalObservationAssetDerivative.purpose == purpose,
                LocalObservationAssetDerivative.params_version == params_version,
            )
        derivative = session.scalars(statement).first()
        if derivative is None:
            raise ObservationAssetNotFound("未找到派生图片")
        if purpose is not None and derivative.purpose != purpose:
            raise ObservationMaterialInvalid("派生图片用途不一致")
        if params_version is not None and derivative.params_version != params_version:
            raise ObservationMaterialInvalid("派生图片参数版本不一致")
        relative = derivative.relative_path
        expected_hash = derivative.content_hash
        expected_size = None
        expected_leaf = derivative.id
    return _read_verified_file(
        runtime,
        relative,
        observation_id=observation_id,
        asset_id=asset_id,
        expected_hash=expected_hash,
        expected_size=expected_size,
        expected_leaf=expected_leaf,
        max_bytes=max_bytes,
    )


__all__ = [
    "MAX_SOURCE_BYTES",
    "MAX_SOURCE_PIXELS",
    "MAX_SOURCE_SIDE",
    "AI_MAX_SIDE",
    "AI_QUALITY",
    "AI_TARGET_BYTES",
    "AI_PARAMS_VERSION",
    "EXPORT_MAX_SIDE",
    "EXPORT_PARAMS_VERSION",
    "EXPORT_QUALITY",
    "WORKING_SET_BUDGET_MB",
    "ObservationMaterialInvalid",
    "ObservationMaterialLimit",
    "ObservationMaterialMissing",
    "ObservationMaterialCorrupt",
    "ObservationAssetNotFound",
    "ObservationAssetRevisionConflict",
    "ObservationAssetRequestConflict",
    "ObservationAssetStorage",
    "ManagedAssetInspection",
    "managed_asset_path",
    "managed_derivative_path",
    "inspect_managed_asset",
    "verify_managed_asset_identity",
    "import_asset",
    "reorder_photos",
    "set_caption",
    "remove_photo",
    "list_photos",
    "read_asset_bytes",
    "read_derivative_bytes",
]
