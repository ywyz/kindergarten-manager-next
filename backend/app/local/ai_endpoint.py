"""Pure standard-library HTTPS endpoint helpers (no ORM, no DB, no DPAPI).

Extracted from the reviewed W1 configuration service so the network worker can
normalize a target without importing the SQLAlchemy models, the credential
store or ``cryptography``. Behavior is byte-for-byte the W1 rule (R08); the
configuration service re-exports these names so its callers and tests are
unchanged.

Rules: UTF-8 encodable, no whitespace/control/backslash, no query/fragment or
user-info, no empty port, no IPv6 zone id, no non-canonical numeric host, no
private/loopback/link-local/reserved/multicast/unspecified/non-global address
(an IPv4-mapped IPv6 is judged by its IPv4), IDNA/punycode hostnames are
normalized, and a path that already ends in ``/chat/completions`` is refused.
No DNS and no connection happen here.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit, urlunsplit

from app.local.errors import LocalValidationError

MAX_BASE_URL_LEN = 2048


class AiEndpointInvalid(LocalValidationError):
    code = "AI_ENDPOINT_INVALID"
    status_code = 422
    message = "base_url 不是有效的本地 HTTPS 端点"


def _has_forbidden_control(value: str) -> bool:
    """True for C0, DEL and C1 control characters (value-free check)."""
    for ch in value:
        code = ord(ch)
        if code < 0x20 or code == 0x7F or 0x80 <= code <= 0x9F:
            return True
    return False


def _is_utf8_encodable(value: str) -> bool:
    """True only for text that encodes cleanly as strict UTF-8."""
    try:
        value.encode("utf-8")
        return True
    except UnicodeEncodeError:
        return False


def _has_whitespace_or_control(value: str) -> bool:
    for ch in value:
        code = ord(ch)
        if ch.isspace() or code < 0x20 or code == 0x7F or 0x80 <= code <= 0x9F:
            return True
    return False


def _looks_numeric_host(host: str) -> bool:
    """True for numeric/hex-only hosts (non-canonical numeric IP forms)."""
    labels = host.split(".")
    if not labels:
        return False
    for label in labels:
        if label.isdigit():
            continue
        if label.lower().startswith("0x"):
            try:
                int(label, 16)
                continue
            except ValueError:
                return False
        return False
    return True


def _ip_allowed(ip: object) -> bool:
    """True only for global-unicast IPs (IPv4-mapped judged by its IPv4)."""
    if getattr(ip, "ipv4_mapped", None) is not None:
        ip = ip.ipv4_mapped
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        return False
    return bool(ip.is_global)


def _valid_hostname(host: str) -> bool:
    h = host.rstrip(".")
    if not h or len(h) > 253:
        return False
    for label in h.split("."):
        if not 1 <= len(label) <= 63:
            return False
        if label[0] == "-" or label[-1] == "-":
            return False
        for ch in label:
            if not (ch.isascii() and (ch.isalnum() or ch == "-")):
                return False
    return True


def _is_completions_path(path: str) -> bool:
    p = path.rstrip("/")
    return p == "/chat/completions" or p.endswith("/chat/completions")


def _normalize_base_url(value: object) -> str:
    """Pure local HTTPS syntax normalization (R08). No DNS, no connection."""
    if not isinstance(value, str) or not value:
        raise AiEndpointInvalid("base_url 必须是字符串")
    if not _is_utf8_encodable(value):
        raise AiEndpointInvalid("base_url 必须是有效 UTF-8 文本")
    if len(value) > MAX_BASE_URL_LEN:
        raise AiEndpointInvalid("base_url 长度必须在 1–2048 个字符之间")
    if "\\" in value or _has_whitespace_or_control(value):
        raise AiEndpointInvalid("base_url 不得包含空白、控制字符或反斜杠")
    if "?" in value or "#" in value:
        raise AiEndpointInvalid("base_url 不得包含查询或片段")
    try:
        parts = urlsplit(value)
    except ValueError:
        raise AiEndpointInvalid("base_url 语法不合法")
    if parts.scheme != "https":
        raise AiEndpointInvalid("base_url 必须使用 https")
    if "@" in parts.netloc:
        raise AiEndpointInvalid("base_url 不得包含用户信息")
    if parts.netloc.endswith(":"):
        raise AiEndpointInvalid("base_url 端口不得为空")
    raw_host = (parts.hostname or "").rstrip(".")
    if not raw_host:
        raise AiEndpointInvalid("base_url 缺少主机名")
    if "%" in raw_host:
        raise AiEndpointInvalid("base_url 主机名不得包含 IPv6 zone id")
    try:
        port = parts.port
    except ValueError:
        raise AiEndpointInvalid("base_url 端口不合法")
    if port is not None and not 1 <= port <= 65535:
        raise AiEndpointInvalid("base_url 端口超出范围")
    path = (parts.path or "").rstrip("/")
    if _is_completions_path(path):
        raise AiEndpointInvalid("base_url 不得直接是补全端点路径")

    # IDNA/ASCII host, no DNS.
    try:
        ascii_host = (
            raw_host.lower()
            if raw_host.isascii()
            else raw_host.encode("idna").decode("ascii")
        )
    except (UnicodeError, UnicodeDecodeError):
        raise AiEndpointInvalid("base_url 主机名不合法")

    is_v6 = False
    try:
        ip = ipaddress.ip_address(ascii_host)
    except ValueError:
        ip = None
    if ip is not None:
        if not _ip_allowed(ip):
            raise AiEndpointInvalid("base_url 主机名不得为私有或保留地址")
        is_v6 = ip.version == 6
    else:
        if _looks_numeric_host(ascii_host):
            raise AiEndpointInvalid("base_url 主机名不得为非常规数字地址")
        if not _valid_hostname(ascii_host):
            raise AiEndpointInvalid("base_url 主机名不合法")
        if (
            ascii_host == "localhost"
            or ascii_host.endswith(".localhost")
            or ascii_host == "localhost.localdomain"
        ):
            raise AiEndpointInvalid("base_url 主机名不得为本地回环名称")

    host_for_netloc = f"[{ascii_host}]" if is_v6 else ascii_host
    netloc = (
        host_for_netloc
        if (port is None or port == 443)
        else f"{host_for_netloc}:{port}"
    )
    return urlunsplit(("https", netloc, path, "", ""))


__all__ = [
    "MAX_BASE_URL_LEN",
    "AiEndpointInvalid",
    "_has_forbidden_control",
    "_is_utf8_encodable",
    "_has_whitespace_or_control",
    "_looks_numeric_host",
    "_ip_allowed",
    "_valid_hostname",
    "_is_completions_path",
    "_normalize_base_url",
]
