"""D3-U fixed release-source configuration and metadata trust table.

There is intentionally no runtime URL/key override. A release build supplies a
single ``update_release.json`` next to the packaged resources. Missing or
empty configuration means "channel not configured": U1 returns that state and
does not perform network I/O.
"""

from __future__ import annotations

import base64
import binascii
import ipaddress
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

_SCHEME = "https"
_DEFAULT_METADATA_PATH = "/stable/windows-x64/manifest.json"
_PATH_RE = re.compile(r"^/[A-Za-z0-9._~!$&'()*+,;=:@%/-]+$")
_HOST_RE = re.compile(r"^[A-Za-z0-9.-]+$")


class ReleaseConfigError(ValueError):
    """The release configuration is present but invalid."""


@dataclass(frozen=True)
class ReleaseSource:
    origin: str
    metadata_path: str
    public_keys: dict[str, bytes] = field(default_factory=dict)
    channel: str = "stable"
    # Test-only fields; the product constructor never sets them.
    ca_pem: str | None = None
    connect_host: str | None = None
    server_hostname: str | None = None
    test_only: bool = False

    @property
    def configured(self) -> bool:
        return bool(self.origin and self.public_keys)

    def validate(self) -> None:
        parts = urlsplit(self.origin)
        if parts.scheme != _SCHEME or not parts.netloc:
            raise ReleaseConfigError("更新源必须是固定 HTTPS 源")
        if parts.username is not None or parts.password is not None:
            raise ReleaseConfigError("更新源不得包含 userinfo")
        if parts.path not in ("", "/") or parts.query or parts.fragment:
            raise ReleaseConfigError("更新源只能包含 scheme/host/port")
        host = parts.hostname or ""
        if not host or not _HOST_RE.match(host):
            raise ReleaseConfigError("更新源主机名不合法")
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            ip = None
        if ip is not None and (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            if not self.test_only:
                raise ReleaseConfigError("产品更新源不得使用私网／回环地址")
        if host.lower() in ("localhost", "localhost.localdomain") and not self.test_only:
            raise ReleaseConfigError("产品更新源不得使用 localhost")
        if not _PATH_RE.match(self.metadata_path):
            raise ReleaseConfigError("元数据路径不合法")
        if ".." in self.metadata_path.split("/"):
            raise ReleaseConfigError("元数据路径不得越界")
        if not self.public_keys:
            raise ReleaseConfigError("更新信任表为空")
        for key_id, key in self.public_keys.items():
            if not isinstance(key_id, str) or not key_id:
                raise ReleaseConfigError("信任表 key_id 不合法")
            if not isinstance(key, (bytes, bytearray)) or len(key) != 32:
                raise ReleaseConfigError("Ed25519 公钥必须是 32 字节")
        if not self.test_only and (self.ca_pem or self.connect_host or self.server_hostname):
            raise ReleaseConfigError("测试 TLS 连接参数不得进入产品更新源")
        if self.test_only and self.connect_host is not None:
            try:
                ipaddress.ip_address(self.connect_host)
            except ValueError:
                raise ReleaseConfigError("测试 connect_host 必须是数值地址") from None

    def metadata_url(self) -> str:
        return self.origin.rstrip("/") + self.metadata_path

    def package_url(self, relative_path: str) -> str:
        if not isinstance(relative_path, str) or not relative_path.startswith("/"):
            raise ReleaseConfigError("包地址必须是同源相对路径")
        if relative_path.startswith("//") or "\\" in relative_path:
            raise ReleaseConfigError("包地址不合法")
        if ".." in relative_path.split("/"):
            raise ReleaseConfigError("包地址不得越界")
        if not _PATH_RE.match(relative_path):
            raise ReleaseConfigError("包地址不合法")
        return self.origin.rstrip("/") + relative_path

    def public_key(self, key_id: str):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        key = self.public_keys.get(key_id)
        if key is None:
            return None
        try:
            return Ed25519PublicKey.from_public_bytes(key)
        except ValueError:
            return None


def _decode_key(value: object) -> bytes:
    if not isinstance(value, str):
        raise ReleaseConfigError("公钥必须是 base64 字符串")
    try:
        raw = base64.b64decode(value.encode("ascii"), validate=True)
    except (ValueError, binascii.Error):
        raise ReleaseConfigError("公钥 base64 不合法") from None
    if len(raw) != 32:
        raise ReleaseConfigError("Ed25519 公钥必须是 32 字节")
    return raw


def load_release_source(path: str | Path | None = None) -> ReleaseSource | None:
    """Load the build-supplied fixed source; missing/empty means unconfigured."""
    if path is None:
        import d1_paths

        path = d1_paths.package_root() / "update_release.json"
    candidate = Path(path)
    if not candidate.is_file():
        return None
    try:
        data = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ReleaseConfigError("更新发行配置无法读取") from exc
    if not isinstance(data, dict):
        raise ReleaseConfigError("更新发行配置必须是对象")
    origin = data.get("origin")
    metadata_path = data.get("metadata_path", _DEFAULT_METADATA_PATH)
    channel = data.get("channel", "stable")
    raw_keys = data.get("public_keys")
    if not isinstance(origin, str) or not origin:
        return None
    if not isinstance(metadata_path, str) or not metadata_path:
        raise ReleaseConfigError("metadata_path 不合法")
    if not isinstance(channel, str) or not channel:
        raise ReleaseConfigError("channel 不合法")
    if not isinstance(raw_keys, dict) or not raw_keys:
        return None
    keys = {str(key_id): _decode_key(value) for key_id, value in raw_keys.items()}
    source = ReleaseSource(
        origin=origin,
        metadata_path=metadata_path,
        public_keys=keys,
        channel=channel,
    )
    source.validate()
    return source
