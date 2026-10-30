"""Bounded ZIP central-directory precheck for Format 1 payloads.

``zipfile.ZipFile`` allocates ``ZipInfo`` objects from whatever the central
directory claims, so the payload is inspected with explicit byte/entry/name
budgets before that allocation.  The payload is a deterministic STORED archive
written by this application; the precheck therefore rejects ZIP features the
writer never emits (encryption, data descriptors, compression, spanning).
"""

from __future__ import annotations

import struct
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from . import backup_format

_ZIP_LOCAL = b"PK\x03\x04"
_ZIP_CENTRAL = b"PK\x01\x02"
_ZIP_EOCD = b"PK\x05\x06"
_ZIP64_EOCD = b"PK\x06\x06"
_ZIP64_LOCATOR = b"PK\x06\x07"
_DEVICE_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


@dataclass(frozen=True)
class ZipMember:
    name: str
    size: int
    local_offset: int
    data_offset: int


def _u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def _u64(data: bytes, offset: int) -> int:
    return struct.unpack_from("<Q", data, offset)[0]


def _error(message: str) -> backup_format.BackupFormatError:
    return backup_format.BackupFormatError("BACKUP_PAYLOAD_INVALID", message)


def _check_cancel(cancel) -> None:
    if cancel is not None and cancel.is_set():
        raise backup_format.BackupFormatError("BACKUP_CANCELLED", "备份已取消")


def _find_eocd(handle: BinaryIO, size: int) -> tuple[int, int, int, int]:
    tail_len = min(size, 65_557 + 20 + 56)
    handle.seek(size - tail_len)
    tail = handle.read(tail_len)
    position = tail.rfind(_ZIP_EOCD)
    if position < 0:
        raise _error("备份 ZIP 缺少中央目录结尾")
    eocd_offset = size - tail_len + position
    if position + 22 > len(tail):
        raise _error("备份 ZIP 结尾截断")
    disk, cd_disk, entries_disk, entries_total, cd_size, cd_offset, comment = (
        struct.unpack_from("<4H2IH", tail, position + 4)
    )
    if disk != 0 or cd_disk != 0 or entries_disk != entries_total:
        raise _error("备份 ZIP 跨盘或条目计数不一致")
    if eocd_offset + 22 + comment != size:
        raise _error("备份 ZIP 结尾长度不一致")
    if entries_total == 0xFFFF or cd_size == 0xFFFFFFFF or cd_offset == 0xFFFFFFFF:
        if eocd_offset < 20:
            raise _error("备份 ZIP64 定位器缺失")
        handle.seek(eocd_offset - 20)
        locator = handle.read(20)
        if len(locator) != 20 or locator[:4] != _ZIP64_LOCATOR:
            raise _error("备份 ZIP64 定位器不合法")
        locator_disk = _u32(locator, 4)
        zip64_offset = _u64(locator, 8)
        total_disks = _u32(locator, 16)
        if locator_disk != 0 or total_disks != 1:
            raise _error("备份 ZIP64 定位器不合法")
        if zip64_offset + 56 > eocd_offset - 20:
            raise _error("备份 ZIP64 记录越界")
        handle.seek(zip64_offset)
        record = handle.read(56)
        if len(record) != 56 or record[:4] != _ZIP64_EOCD:
            raise _error("备份 ZIP64 记录不合法")
        record_size = _u64(record, 4)
        if record_size < 44 or zip64_offset + 12 + record_size != eocd_offset - 20:
            raise _error("备份 ZIP64 记录长度不合法")
        disk, cd_disk = _u32(record, 16), _u32(record, 20)
        entries_disk, entries_total = _u64(record, 24), _u64(record, 32)
        cd_size, cd_offset = _u64(record, 40), _u64(record, 48)
        if disk != 0 or cd_disk != 0 or entries_disk != entries_total:
            raise _error("备份 ZIP64 跨盘或条目计数不一致")
        cd_end = zip64_offset
    else:
        cd_end = eocd_offset
    if entries_total > backup_format.MAX_MEMBERS:
        raise _error("备份 ZIP 成员数量超过上限")
    if cd_size > backup_format.MAX_CENTRAL_DIR_BYTES:
        raise _error("备份 ZIP 中央目录超过上限")
    if cd_offset + cd_size != cd_end or cd_offset > size:
        raise _error("备份 ZIP 中央目录位置不合法")
    return cd_offset, cd_size, entries_total, cd_end


def _zip64_extra(extra: bytes, need: dict[str, int]) -> dict[str, int]:
    values = dict(need)
    offset = 0
    while offset + 4 <= len(extra):
        header_id, length = struct.unpack_from("<HH", extra, offset)
        offset += 4
        if offset + length > len(extra):
            raise _error("备份 ZIP 额外字段越界")
        if header_id == 0x0001:
            cursor = offset
            end = offset + length
            for field in ("usize", "csize", "local_offset", "disk_start"):
                if values.get(field) != 0xFFFFFFFF:
                    continue
                width = 4 if field == "disk_start" else 8
                if cursor + width > end:
                    raise _error("备份 ZIP64 字段截断")
                values[field] = (
                    _u64(extra, cursor) if width == 8 else _u32(extra, cursor)
                )
                cursor += width
        offset += length
    return values


def _safe_member_name(name: str) -> None:
    if not name or "\x00" in name or "\\" in name or ":" in name:
        raise _error("备份 ZIP 成员路径不合法")
    if name.startswith("/"):
        raise _error("备份 ZIP 成员路径不合法")
    parts = name.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise _error("备份 ZIP 成员路径不合法")
    if any(len(part) > 255 for part in parts):
        raise _error("备份 ZIP 成员路径不合法")
    if any(part.endswith((".", " ")) for part in parts):
        raise _error("备份 ZIP 成员路径不合法")
    if any(part.split(".", 1)[0].lower() in _DEVICE_NAMES for part in parts):
        raise _error("备份 ZIP 成员路径不合法")


def precheck_payload_zip(path: Path, *, cancel=None) -> list[ZipMember]:
    """Return the exact bounded member list of a Format 1 payload ZIP."""

    try:
        size = path.stat().st_size
    except OSError as exc:
        raise _error("备份载荷无法读取") from exc
    if size < 22:
        raise _error("备份载荷过短")
    with path.open("rb") as handle:
        cd_offset, cd_size, entries_total, _cd_end = _find_eocd(handle, size)
        _check_cancel(cancel)
        handle.seek(cd_offset)
        central = handle.read(cd_size)
        if len(central) != cd_size:
            raise _error("备份 ZIP 中央目录截断")
        members: list[ZipMember] = []
        seen: set[str] = set()
        folded: set[str] = set()
        prefix_parts: set[str] = set()
        ranges: list[tuple[int, int]] = []
        total = 0
        cursor = 0
        for _ in range(entries_total):
            _check_cancel(cancel)
            if cursor + 46 > len(central):
                raise _error("备份 ZIP 中央目录截断")
            if central[cursor:cursor + 4] != _ZIP_CENTRAL:
                raise _error("备份 ZIP 中央目录签名不合法")
            (
                _sig,
                _made,
                _needed,
                flags,
                method,
                _mtime,
                _mdate,
                _crc,
                csize,
                usize,
                name_len,
                extra_len,
                comment_len,
                disk_start,
                _iattr,
                _eattr,
                local_offset,
            ) = struct.unpack_from("<4s6H3I5H2I", central, cursor)
            cursor += 46
            if cursor + name_len + extra_len + comment_len > len(central):
                raise _error("备份 ZIP 中央目录条目越界")
            name_bytes = central[cursor:cursor + name_len]
            extra = central[cursor + name_len:cursor + name_len + extra_len]
            cursor += name_len + extra_len + comment_len
            if name_len == 0 or name_len > backup_format.MAX_MEMBER_NAME_BYTES:
                raise _error("备份 ZIP 成员名长度不合法")
            if flags & 0x1:
                raise _error("备份 ZIP 含加密成员")
            if flags & ~0x800:
                raise _error("备份 ZIP 成员标志不合法")
            if method != zipfile.ZIP_STORED:
                raise _error("备份 ZIP 成员必须为 STORED")
            if disk_start not in (0, 0xFFFF):
                raise _error("备份 ZIP 成员跨盘")
            if csize == 0xFFFFFFFF or usize == 0xFFFFFFFF or local_offset == 0xFFFFFFFF:
                values = _zip64_extra(
                    extra,
                    {
                        "usize": usize,
                        "csize": csize,
                        "local_offset": local_offset,
                        "disk_start": disk_start,
                    },
                )
                usize, csize, local_offset = (
                    values["usize"],
                    values["csize"],
                    values["local_offset"],
                )
                if values.get("disk_start") != 0:
                    raise _error("备份 ZIP 成员跨盘")
            if csize != usize:
                raise _error("备份 ZIP 成员长度不一致")
            if usize > backup_format.MAX_EXPANDED_BYTES:
                raise _error("备份 ZIP 成员超过上限")
            try:
                name = name_bytes.decode("utf-8" if flags & 0x800 else "ascii")
            except UnicodeDecodeError as exc:
                raise _error("备份 ZIP 成员名编码不合法") from exc
            _safe_member_name(name)
            folded_name = unicodedata.normalize("NFC", name).casefold()
            if name in seen or folded_name in folded:
                raise _error("备份 ZIP 成员重复或大小写冲突")
            seen.add(name)
            folded.add(folded_name)
            parts = name.split("/")
            for index in range(1, len(parts)):
                prefix = "/".join(parts[:index])
                if prefix in seen:
                    raise _error("备份 ZIP 成员路径冲突")
                prefix_parts.add(prefix)
            if name in prefix_parts:
                raise _error("备份 ZIP 成员路径冲突")
            if local_offset + 30 > cd_offset:
                raise _error("备份 ZIP 本地头越界")
            handle.seek(local_offset)
            local = handle.read(30)
            if len(local) != 30 or local[:4] != _ZIP_LOCAL:
                raise _error("备份 ZIP 本地头不合法")
            local_flags, local_method = _u16(local, 6), _u16(local, 8)
            local_name_len, local_extra_len = _u16(local, 26), _u16(local, 28)
            if local_flags != flags or local_method != method:
                raise _error("备份 ZIP 本地头与中央目录不一致")
            if local_name_len != name_len:
                raise _error("备份 ZIP 本地成员名长度不一致")
            local_name = handle.read(local_name_len)
            if local_name != name_bytes:
                raise _error("备份 ZIP 本地成员名不一致")
            data_offset = local_offset + 30 + local_name_len + local_extra_len
            data_end = data_offset + csize
            if data_end > cd_offset:
                raise _error("备份 ZIP 成员数据越界")
            ranges.append((data_offset, data_end))
            total += usize
            if total > backup_format.MAX_EXPANDED_BYTES:
                raise backup_format.BackupFormatError(
                    "BACKUP_SIZE_INVALID", "备份展开体积超过上限"
                )
            members.append(ZipMember(name, usize, local_offset, data_offset))
        if cursor != len(central):
            raise _error("备份 ZIP 中央目录条目数不一致")
        ranges.sort()
        for (start, end), (next_start, _next_end) in zip(ranges, ranges[1:]):
            if end > next_start:
                raise _error("备份 ZIP 成员数据重叠")
    return members
