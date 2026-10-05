"""1A offline HTTPS base-URL normalization & validation.

Per checklist §9.1 / AI Service spec: the stored ``base_url`` is a public
HTTPS provider prefix. Normalization only adjusts scheme/host case, port
presence and a single trailing slash; intermediate paths are kept as typed
by the user and are never silently rewritten. No endpoint is appended here
(final endpoint is composed once by the future transport slice).

Offline string checks only — no DNS resolution, no network connection.
This does NOT equal full SSRF protection; DNS/TLS/redirect-level checks
belong to the transport slice.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

MAX_BASE_URL_LEN = 500

_PROTOCOLS = ("chat_completions_v1",)


class AiInputInvalid(ValueError):
    """Typed 422-class input error (HTTP mapping in 1B)."""


class BaseUrlInvalid(AiInputInvalid):
    pass


def _reject_reason(reason: str) -> BaseUrlInvalid:
    return BaseUrlInvalid(reason)


# Hostnames that would obviously resolve to this machine / local net even
# without DNS (string-level rejection only).
_LOCAL_HOSTNAME_FRAGMENTS = ("localhost", ".localdomain", ".local", ".localhost")

# S1: 解析类失败统一固定消息，不回显原始地址。
_PARSE_INVALID_MESSAGE = (
    "base_url 无效：解析失败或组成部分不合法（请填写 HTTPS 供应商前缀）"
)


def _ip_literal_rank(host: str) -> str | None:
    """Return a rank tag if host is an IP literal, else None."""
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return None
    # IPv4-mapped IPv6 一律拒绝（避免映射绕过 IPv4 校验）。
    if addr.version == 6 and addr.ipv4_mapped is not None:
        return "non-public"
    if (
        addr.is_loopback
        or addr.is_private
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
        or not addr.is_global
    ):
        return "non_public"
    return None


def normalize_https_base_url(raw: str, *, protocol_id: str = "chat_completions_v1") -> str:
    """Validate and normalize a base_url; returns the normalized string."""
    if protocol_id not in _PROTOCOLS:
        raise AiInputInvalid(f"不支持的协议 {protocol_id!r}")
    if not isinstance(raw, str):
        raise BaseUrlInvalid("base_url 必须为字符串")
    value = raw.strip()
    if not value:
        raise BaseUrlInvalid("base_url 不能为空")
    if len(value) > MAX_BASE_URL_LEN:
        raise BaseUrlInvalid(f"base_url 长度不能超过 {MAX_BASE_URL_LEN} 字符")

    # S1: 原始输入带 ? 或 # 分隔符即拒绝（百分号编码路径保持原样，
    # 不因分隔字符被解码或改写）。
    if "?" in value or "#" in value:
        raise _reject_reason("base_url 不得包含 query 或 fragment 分隔符")
    try:
        parts = urlsplit(value)
        host = parts.hostname
    except ValueError:
        raise _reject_reason(_PARSE_INVALID_MESSAGE) from None
    if parts.scheme.lower() != "https":
        raise _reject_reason("base_url 必须是 HTTPS")
    if not host:
        raise _reject_reason(_PARSE_INVALID_MESSAGE)
    if parts.username is not None or parts.password is not None:
        raise _reject_reason("base_url 不得包含 userinfo（用户名／密码）")
    # 未加方括号的 IPv6 字面量（多余冒号）等畸形 netloc：拒绝。
    if host and ":" in host and not parts.netloc.lstrip(" ").startswith("["):
        raise _reject_reason("base_url 的 IPv6 主机必须加方括号")
    if _ip_literal_rank(host) is not None:
        raise _reject_reason(
            "base_url 不得是本机、内网、链路局部或保留 IP 字面量"
        )
    lower_host = host.lower()
    if any(frag in lower_host for frag in _LOCAL_HOSTNAME_FRAGMENTS):
        raise _reject_reason("base_url 不得是显然的本机主机名")
    # Backward-compat: IPv6 literal brackets preserved on rebuild.

    path = parts.path
    if "/chat/completions" in path.lower() or "/completions" in path.lower():
        raise _reject_reason(
            "base_url 是供应商前缀，不得包含 /chat/completions 完整端点；"
            "请填写前缀，最终端点由系统追加一次"
        )
    while path.endswith("/"):
        path = path[:-1]
    netloc = lower_host
    if ":" in lower_host:  # IPv6 literal
        netloc = f"[{lower_host}]"
    try:
        port = parts.port
    except ValueError:
        raise _reject_reason(_PARSE_INVALID_MESSAGE) from None
    if port is not None:
        netloc = f"{netloc}:{port}"

    normalized = "https://" + netloc + path
    return normalized
