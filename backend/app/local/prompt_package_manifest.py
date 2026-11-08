"""Signed latest-manifest support for the two fixed prompt-package channels.

The manifest is a small Ed25519-signed pointer to one immutable version file.
It contains no editable guidance and never supplies a URL.  The package URL is
constructed only from the fixed trusted HTTPS source directory and the signed
channel/sequence/sha fields.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from app.local.prompt_bundles import canonical_json
from app.local.prompt_package import (
    MAX_KEY_ID_CHARS,
    PackageTrust,
    PromptPackageError,
    VerifiedPackage,
    strict_json_object,
)

CHANNELS = ("preview", "stable")
FORMAT_VERSION = 1
MAX_MANIFEST_BYTES = 64 * 1024
_SIGNING_PREFIX = b"kgm-prompt-manifest-v1\n"
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_MANIFEST_KEYS = frozenset(
    {
        "format_version",
        "channel",
        "release_sequence",
        "package_sha256",
        "key_id",
        "signature",
    }
)


@dataclass(frozen=True)
class PromptManifest:
    channel: str
    release_sequence: int
    package_sha256: str
    key_id: str
    signature: str
    content_sha256: str

    def package_filename(self) -> str:
        return f"v{self.release_sequence}-{self.package_sha256}.json"


def _strict_int(value: Any, code: str, message: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise PromptPackageError(code, message)
    return value


def _strict_str(value: Any, code: str, message: str, *, maximum: int) -> str:
    if not isinstance(value, str) or len(value) > maximum:
        raise PromptPackageError(code, message)
    return value


def _decode_signature(value: Any) -> bytes:
    if not isinstance(value, str) or len(value) > 256:
        raise PromptPackageError(
            "PACKAGE_MANIFEST_SIGNATURE_INVALID", "清单签名格式无效"
        )
    try:
        raw = base64.b64decode(value.encode("ascii"), validate=True)
    except (UnicodeEncodeError, binascii.Error) as exc:
        raise PromptPackageError(
            "PACKAGE_MANIFEST_SIGNATURE_INVALID", "清单签名格式无效"
        ) from exc
    if len(raw) != 64:
        raise PromptPackageError(
            "PACKAGE_MANIFEST_SIGNATURE_INVALID", "清单签名长度无效"
        )
    return raw


def _origin(trust: PackageTrust) -> str:
    if not trust.source_url:
        raise PromptPackageError(
            "PACKAGE_SOURCE_UNCONFIGURED", "提示词包来源未配置"
        )
    parsed = urlsplit(trust.source_url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise PromptPackageError(
            "PACKAGE_SOURCE_INVALID", "提示词包来源必须是固定 HTTPS 地址"
        )
    if (
        parsed.username
        or parsed.password
        or parsed.fragment
        or parsed.query
        or parsed.path not in ("", "/")
    ):
        raise PromptPackageError(
            "PACKAGE_SOURCE_INVALID",
            "提示词包来源必须是固定 HTTPS 源地址（不含路径、查询或片段）",
        )
    return f"https://{parsed.netloc}"


def manifest_url(trust: PackageTrust) -> str:
    if trust.channel not in CHANNELS:
        raise PromptPackageError(
            "PACKAGE_SOURCE_INVALID", "提示词包渠道未配置"
        )
    base = _origin(trust)
    return f"{base}/prompt-packages/{trust.channel}/latest.json"


def package_url(trust: PackageTrust, manifest: PromptManifest) -> str:
    if manifest.channel != trust.channel:
        raise PromptPackageError(
            "PACKAGE_MANIFEST_CHANNEL", "清单渠道与当前构建渠道不一致"
        )
    if not _SHA256_RE.fullmatch(manifest.package_sha256):
        raise PromptPackageError("PACKAGE_MANIFEST_INVALID", "清单包摘要无效")
    base = _origin(trust)
    return (
        f"{base}/prompt-packages/{manifest.channel}/"
        f"{manifest.package_filename()}"
    )


def verify_manifest(
    raw: bytes | str,
    trust: PackageTrust,
    *,
    channel: str | None = None,
) -> PromptManifest:
    if trust.channel not in CHANNELS:
        raise PromptPackageError(
            "PACKAGE_SOURCE_INVALID", "提示词包渠道未配置"
        )
    expected_channel = channel or trust.channel
    if expected_channel != trust.channel:
        raise PromptPackageError(
            "PACKAGE_MANIFEST_CHANNEL", "清单渠道与当前构建渠道不一致"
        )
    if isinstance(raw, str):
        raw_bytes = raw.encode("utf-8")
    elif isinstance(raw, bytes):
        raw_bytes = raw
    else:
        raise PromptPackageError(
            "PACKAGE_MANIFEST_INVALID", "清单内容类型无效"
        )
    if len(raw_bytes) > MAX_MANIFEST_BYTES:
        raise PromptPackageError(
            "PACKAGE_MANIFEST_INVALID", "清单超过大小上限"
        )
    document = strict_json_object(raw_bytes)
    if set(document) != _MANIFEST_KEYS:
        raise PromptPackageError("PACKAGE_MANIFEST_INVALID", "清单字段无效")
    format_version = _strict_int(
        document["format_version"],
        "PACKAGE_MANIFEST_INVALID",
        "清单格式版本无效",
    )
    if format_version != FORMAT_VERSION:
        raise PromptPackageError(
            "PACKAGE_MANIFEST_INVALID", "清单格式版本不兼容"
        )
    manifest_channel = _strict_str(
        document["channel"],
        "PACKAGE_MANIFEST_INVALID",
        "清单渠道无效",
        maximum=16,
    )
    if manifest_channel not in CHANNELS:
        raise PromptPackageError("PACKAGE_MANIFEST_INVALID", "清单渠道无效")
    if manifest_channel != expected_channel:
        raise PromptPackageError(
            "PACKAGE_MANIFEST_CHANNEL", "清单渠道与当前构建渠道不一致"
        )
    sequence = _strict_int(
        document["release_sequence"],
        "PACKAGE_MANIFEST_INVALID",
        "清单发布序号无效",
    )
    if sequence < 1:
        raise PromptPackageError("PACKAGE_MANIFEST_INVALID", "清单发布序号无效")
    package_sha = _strict_str(
        document["package_sha256"],
        "PACKAGE_MANIFEST_INVALID",
        "清单包摘要无效",
        maximum=64,
    )
    if _SHA256_RE.fullmatch(package_sha) is None:
        raise PromptPackageError("PACKAGE_MANIFEST_INVALID", "清单包摘要无效")
    key_id = _strict_str(
        document["key_id"],
        "PACKAGE_MANIFEST_SIGNATURE_INVALID",
        "清单签名密钥编号无效",
        maximum=MAX_KEY_ID_CHARS,
    )
    if key_id not in trust.keys:
        raise PromptPackageError(
            "PACKAGE_MANIFEST_KEY_UNKNOWN", "清单签名密钥不受信任"
        )
    signature = _decode_signature(document["signature"])
    unsigned = dict(document)
    del unsigned["signature"]
    signed_bytes = _SIGNING_PREFIX + canonical_json(unsigned).encode("utf-8")
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey,
        )

        Ed25519PublicKey.from_public_bytes(trust.keys[key_id]).verify(
            signature, signed_bytes
        )
    except (InvalidSignature, ValueError) as exc:
        raise PromptPackageError(
            "PACKAGE_MANIFEST_SIGNATURE_INVALID", "清单签名校验失败"
        ) from exc
    return PromptManifest(
        channel=manifest_channel,
        release_sequence=sequence,
        package_sha256=package_sha,
        key_id=key_id,
        signature=document["signature"],
        content_sha256=hashlib.sha256(signed_bytes).hexdigest(),
    )


def verify_package_for_manifest(
    raw: bytes,
    manifest: PromptManifest,
    trust: PackageTrust,
    *,
    client_version: str | None = None,
) -> VerifiedPackage:
    """Check the raw version-file digest before returning the package bytes."""
    digest = hashlib.sha256(raw).hexdigest()
    if digest != manifest.package_sha256:
        raise PromptPackageError(
            "PACKAGE_MANIFEST_HASH", "版本包摘要与清单不一致"
        )
    from app.local.prompt_package import verify_package

    package = verify_package(
        raw, trust, client_version=client_version or trust.client_version
    )
    if package.release_sequence != manifest.release_sequence:
        raise PromptPackageError(
            "PACKAGE_MANIFEST_SEQUENCE", "版本包发布序号与清单不一致"
        )
    if package.key_id != manifest.key_id:
        raise PromptPackageError(
            "PACKAGE_MANIFEST_KEY", "版本包签名密钥与清单不一致"
        )
    return package


__all__ = [
    "CHANNELS",
    "FORMAT_VERSION",
    "MAX_MANIFEST_BYTES",
    "PromptManifest",
    "manifest_url",
    "package_url",
    "verify_manifest",
    "verify_package_for_manifest",
]
