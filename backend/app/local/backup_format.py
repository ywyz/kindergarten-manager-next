"""Format 1 backup container: bounded header, STORED ZIP payload, optional
password encryption.

The format is intentionally not a general-purpose archive.  It is a single
application-recognised file:

    header (128 bytes) + payload + optional 16-byte GCM tag

The payload is a deterministic ZIP whose first member is ``manifest.json`` and
whose second member is ``db/kindergarten.db``.  Format 1 uses ZIP_STORED only,
so there is no decompression bomb inside the payload.  Password mode wraps the
ZIP bytes with AES-256-GCM; the full header is authenticated as AAD.
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Callable, Iterator

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

FORMAT_VERSION = 1
MAGIC = b"KGMBKP1\0"
HEADER_LEN = 128
EXTENSION = ".kgmbackup"
MODE_PLAINTEXT = 1
MODE_PASSWORD = 2
FLAGS = 0

KDF_ID_SCRYPT = 1
KDF_LOG2_N = 17
KDF_R = 8
KDF_P = 1
SALT_LEN = 32
NONCE_LEN = 12
KEY_LEN = 32
TAG_LEN = 16

MANIFEST_NAME = "manifest.json"
DATABASE_NAME = "db/kindergarten.db"

MAX_TOTAL_BYTES = 64 * 1024 * 1024 * 1024
MAX_EXPANDED_BYTES = 64 * 1024 * 1024 * 1024
MAX_DATABASE_BYTES = 8 * 1024 * 1024 * 1024
MAX_RESOURCE_BYTES = 64 * 1024 * 1024
MAX_MANIFEST_BYTES = 64 * 1024 * 1024
MAX_MEMBERS = 250_000
MAX_CENTRAL_DIR_BYTES = 256 * 1024 * 1024
MAX_MEMBER_NAME_BYTES = 4096
CHUNK = 1024 * 1024
_ZIP_DATE = (1980, 1, 1, 0, 0, 0)
_RESERVED = b"\0" * 3
_RESERVED_TAIL = b"\0" * 20


class BackupFormatError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class BackupHeader:
    mode: int
    payload_len: int
    salt: bytes
    nonce: bytes
    kdf: tuple[int, int, int]


def _pack_header(
    *,
    mode: int,
    payload_len: int,
    salt: bytes,
    nonce: bytes,
    kdf: tuple[int, int, int],
    header_digest: bytes,
) -> bytes:
    log2_n, r, p = kdf
    return b"".join(
        (
            MAGIC,
            struct.pack("<HBBHBBBBBBB", FORMAT_VERSION, mode, FLAGS, HEADER_LEN,
                        KDF_ID_SCRYPT if mode == MODE_PASSWORD else 0,
                        log2_n, r, p,
                        len(salt), len(nonce),
                        TAG_LEN if mode == MODE_PASSWORD else 0),
            _RESERVED,
            struct.pack("<Q", payload_len),
            salt.ljust(SALT_LEN, b"\0")[:SALT_LEN],
            nonce.ljust(NONCE_LEN, b"\0")[:NONCE_LEN],
            header_digest,
            _RESERVED_TAIL,
        )
    )


def encode_header(
    *,
    mode: int,
    payload_len: int,
    salt: bytes = b"",
    nonce: bytes = b"",
) -> bytes:
    if mode not in (MODE_PLAINTEXT, MODE_PASSWORD):
        raise BackupFormatError("BACKUP_MODE_INVALID", "备份模式不合法")
    if payload_len < 0 or payload_len > MAX_TOTAL_BYTES:
        raise BackupFormatError("BACKUP_SIZE_INVALID", "备份载荷超过上限")
    if mode == MODE_PLAINTEXT:
        if salt or nonce:
            raise BackupFormatError("BACKUP_HEADER_INVALID", "明文模式不携带盐或 nonce")
        header = _pack_header(
            mode=mode,
            payload_len=payload_len,
            salt=b"",
            nonce=b"",
            kdf=(0, 0, 0),
            header_digest=b"\0" * 32,
        )
        digest = hashlib.sha256(header).digest()
        return header[:76] + digest + header[108:]
    if len(salt) != SALT_LEN or len(nonce) != NONCE_LEN:
        raise BackupFormatError("BACKUP_HEADER_INVALID", "加密盐或 nonce 长度不合法")
    return _pack_header(
        mode=mode,
        payload_len=payload_len,
        salt=salt,
        nonce=nonce,
        kdf=(KDF_LOG2_N, KDF_R, KDF_P),
        header_digest=b"\0" * 32,
    )


def parse_header(raw: bytes, *, file_size: int | None = None) -> BackupHeader:
    if not isinstance(raw, (bytes, bytearray)) or len(raw) != HEADER_LEN:
        raise BackupFormatError("BACKUP_HEADER_INVALID", "备份头长度不合法")
    data = bytes(raw)
    if data[:8] != MAGIC:
        raise BackupFormatError("BACKUP_MAGIC_INVALID", "备份 magic 不匹配")
    (
        version,
        mode,
        flags,
        header_len,
        kdf_id,
        log2_n,
        r,
        p,
        salt_len,
        nonce_len,
        tag_len,
    ) = struct.unpack("<HBBHBBBBBBB", data[8:21])
    if version != FORMAT_VERSION:
        raise BackupFormatError("BACKUP_FORMAT_UNSUPPORTED", "备份格式版本不支持")
    if mode not in (MODE_PLAINTEXT, MODE_PASSWORD):
        raise BackupFormatError("BACKUP_MODE_INVALID", "备份模式不合法")
    if flags != FLAGS or header_len != HEADER_LEN:
        raise BackupFormatError("BACKUP_HEADER_INVALID", "备份头保留字段不合法")
    if data[21:24] != _RESERVED or data[108:128] != _RESERVED_TAIL:
        raise BackupFormatError("BACKUP_HEADER_INVALID", "备份头保留字段不合法")
    payload_len = struct.unpack("<Q", data[24:32])[0]
    if payload_len > MAX_TOTAL_BYTES:
        raise BackupFormatError("BACKUP_SIZE_INVALID", "备份载荷超过上限")
    salt = data[32:64]
    nonce = data[64:76]
    digest = data[76:108]
    if mode == MODE_PLAINTEXT:
        if (kdf_id, log2_n, r, p, salt_len, nonce_len, tag_len) != (0, 0, 0, 0, 0, 0, 0):
            raise BackupFormatError("BACKUP_HEADER_INVALID", "明文 KDF 参数必须为零")
        if salt != b"\0" * SALT_LEN or nonce != b"\0" * NONCE_LEN:
            raise BackupFormatError("BACKUP_HEADER_INVALID", "明文盐或 nonce 必须为零")
        expected = hashlib.sha256(data[:76] + b"\0" * 32 + data[108:]).digest()
        if digest != expected:
            raise BackupFormatError("BACKUP_HEADER_DIGEST", "备份头校验失败")
    else:
        if (kdf_id, log2_n, r, p, salt_len, nonce_len, tag_len) != (
            KDF_ID_SCRYPT, KDF_LOG2_N, KDF_R, KDF_P, SALT_LEN, NONCE_LEN, TAG_LEN
        ):
            raise BackupFormatError("BACKUP_KDF_INVALID", "备份 KDF 参数不受支持")
        if digest != b"\0" * 32:
            raise BackupFormatError("BACKUP_HEADER_INVALID", "加密头 digest 必须为零")
    expected_size = HEADER_LEN + payload_len + (
        TAG_LEN if mode == MODE_PASSWORD else 0
    )
    if expected_size > MAX_TOTAL_BYTES:
        raise BackupFormatError("BACKUP_SIZE_INVALID", "备份文件总长度超过上限")
    if file_size is not None:
        if file_size != expected_size:
            raise BackupFormatError("BACKUP_SIZE_INVALID", "备份文件总长度不匹配")
    return BackupHeader(
        mode=mode,
        payload_len=payload_len,
        salt=salt if mode == MODE_PASSWORD else b"",
        nonce=nonce if mode == MODE_PASSWORD else b"",
        kdf=(log2_n, r, p) if mode == MODE_PASSWORD else (0, 0, 0),
    )


def read_header(path: Path) -> tuple[BackupHeader, bytes]:
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            raw = handle.read(HEADER_LEN)
    except OSError as exc:
        raise BackupFormatError("BACKUP_READ_FAILED", "无法读取备份头") from exc
    header = parse_header(raw, file_size=size)
    return header, raw


def derive_key(password: str, salt: bytes) -> bytes:
    if not isinstance(password, str) or not password:
        raise BackupFormatError("BACKUP_PASSWORD_REQUIRED", "加密备份必须提供非空密码")
    if len(salt) != SALT_LEN:
        raise BackupFormatError("BACKUP_KDF_INVALID", "盐长度不合法")
    try:
        return Scrypt(
            salt=salt,
            length=KEY_LEN,
            n=2 ** KDF_LOG2_N,
            r=KDF_R,
            p=KDF_P,
        ).derive(password.encode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - fixed-parameter KDF refusal
        raise BackupFormatError("BACKUP_KDF_FAILED", "密码派生失败") from exc


def _cipher(key: bytes, nonce: bytes) -> Cipher:
    return Cipher(algorithms.AES(key), modes.GCM(nonce))


def _check_cancel(cancel) -> None:
    if cancel is not None and cancel.is_set():
        raise BackupFormatError("BACKUP_CANCELLED", "备份已取消")


def encrypt_payload(
    source: BinaryIO,
    target: BinaryIO,
    *,
    key: bytes,
    nonce: bytes,
    aad: bytes,
    length: int,
    cancel=None,
    progress: Callable[[int, int], None] | None = None,
) -> bytes:
    encryptor = _cipher(key, nonce).encryptor()
    encryptor.authenticate_additional_data(aad)
    remaining = length
    done = 0
    while remaining:
        _check_cancel(cancel)
        chunk = source.read(min(CHUNK, remaining))
        if not chunk:
            raise BackupFormatError("BACKUP_TRUNCATED", "备份载荷提前结束")
        target.write(encryptor.update(chunk))
        remaining -= len(chunk)
        done += len(chunk)
        if progress is not None:
            progress(done, length)
    _check_cancel(cancel)
    target.write(encryptor.finalize())
    return encryptor.tag


def decrypt_payload(
    source: BinaryIO,
    target: BinaryIO,
    *,
    key: bytes,
    nonce: bytes,
    aad: bytes,
    length: int,
    tag: bytes,
    cancel=None,
    progress: Callable[[int, int], None] | None = None,
) -> None:
    if len(tag) != TAG_LEN:
        raise BackupFormatError("BACKUP_TAG_INVALID", "认证标签长度不合法")
    decryptor = _cipher(key, nonce).decryptor()
    decryptor.authenticate_additional_data(aad)
    remaining = length
    done = 0
    try:
        while remaining:
            _check_cancel(cancel)
            chunk = source.read(min(CHUNK, remaining))
            if not chunk:
                raise BackupFormatError("BACKUP_TRUNCATED", "备份载荷提前结束")
            target.write(decryptor.update(chunk))
            remaining -= len(chunk)
            done += len(chunk)
            if progress is not None:
                progress(done, length)
        _check_cancel(cancel)
        decryptor.finalize_with_tag(tag)
    except BackupFormatError:
        raise
    except Exception as exc:  # noqa: BLE001 - authentication failure
        raise BackupFormatError("BACKUP_AUTH_FAILED", "备份密码或认证失败") from exc


def sha256_file(path: Path, *, cancel=None) -> str:
    hasher = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while True:
                if cancel is not None and cancel.is_set():
                    raise BackupFormatError("BACKUP_CANCELLED", "备份已取消")
                chunk = handle.read(CHUNK)
                if not chunk:
                    break
                hasher.update(chunk)
    except OSError as exc:
        raise BackupFormatError("BACKUP_READ_FAILED", "无法读取备份文件") from exc
    return hasher.hexdigest()


def zip_info(name: str, size: int) -> "object":
    import zipfile

    info = zipfile.ZipInfo(name, date_time=_ZIP_DATE)
    info.compress_type = zipfile.ZIP_STORED
    info.external_attr = 0o600 << 16
    info.file_size = size
    return info


def iter_file_chunks(handle: BinaryIO, length: int, *, cancel=None) -> Iterator[bytes]:
    remaining = length
    while remaining:
        if cancel is not None and cancel.is_set():
            raise BackupFormatError("BACKUP_CANCELLED", "备份已取消")
        chunk = handle.read(min(CHUNK, remaining))
        if not chunk:
            raise BackupFormatError("BACKUP_TRUNCATED", "文件提前结束")
        remaining -= len(chunk)
        yield chunk
