"""D2 W3 standard-library transport for the OpenAI-compatible text subset.

Engineering spec §4.2 / §11. This module owns everything from URL
normalization to a strictly parsed candidate. It never opens the database and
never imports the legacy ``.env`` / account / MySQL chain.

Hard rules:

* the HTTPS prefix is normalized by the reviewed configuration validator and
  ``/chat/completions`` is appended exactly once to the *prefix path* (a
  ``/v1`` or vendor prefix is preserved and never duplicated);
* every attempt resolves A/AAAA to at most 32 addresses that must *all* be
  global unicast (an IPv4-mapped IPv6 is judged by its IPv4); a mixed
  public/private batch is refused; the connection uses the verified numeric
  sockaddr and re-checks ``getpeername``; TLS keeps the original hostname for
  SNI and certificate verification and the ``Host`` header stays same-origin;
* no proxy, no redirect, no CONNECT, no certificate-verification bypass, no
  automatic decompression; ``Accept-Encoding: identity``,
  ``Connection: close``;
* the whole 10 s connect budget (DNS **and** TCP **and** TLS) runs from the
  start of preparation, and the parent additionally supervises the same phase
  so a hung DNS resolver cannot exceed it;
* response framing is validated by hand: duplicate/conflicting
  ``Content-Length`` / ``Transfer-Encoding`` / ``Content-Encoding`` values,
  a non-``chunked`` transfer coding, a declared length that does not match the
  bytes actually read, an oversized body or a truncated frame are all refused —
  a malformed HTTP frame can never become a candidate; response headers are
  capped at 64 KiB and the body at 1 MiB (chunked reads included);
* provider metadata (request id, returned model, usage) is whitelisted in type,
  length and keys; diagnostic details use fixed codes and never embed a
  model-supplied key name or the raw response text;
* the network phase is split into ``prepare`` (DNS + TCP + TLS, no HTTP bytes)
  and ``send`` (the single write). The caller only calls ``send`` after the
  parent's SEND frame, so no request byte is written before the dispatch mark
  and the final permission check.

A *synthetic* transport (pre-resolved numeric addresses + a test CA, optional
private-address allowance) may only be supplied through this module's explicit
parameters by a dedicated synthetic verification entry; it is never derived
from an environment variable or an ordinary HTTP request.
"""

from __future__ import annotations

import http.client
import io
import ipaddress
import json
import math
import re
import socket
import ssl
import time
from dataclasses import dataclass, field
from typing import Any, Sequence
from urllib.parse import urlsplit

from app.local.ai_endpoint import (
    AiEndpointInvalid,
    _normalize_base_url,
)
COMPLETIONS_PATH = "/chat/completions"
PROTOCOL_ID = "chat_completions_v1"

CONNECT_BUDGET_MS = 10_000
ATTEMPT_BUDGET_MS = 120_000
REQUEST_MAX_BYTES = 1_048_576
RESPONSE_MAX_BYTES = 1_048_576
HEADER_MAX_BYTES = 64 * 1024
MAX_RESOLVED_ADDRESSES = 32
MAX_REQUEST_ID_LEN = 128
MAX_MODEL_LEN = 200

# Transport outcome kinds (mapped to task reasons by the executor).
SUCCESS = "success"
NOT_SENT = "not_sent"          # provably no HTTP byte was written
UNKNOWN = "unknown"            # possibly sent, no confirmed result
AUTH = "auth"                  # 401 / 403
CONFIG_REJECTED = "config_rejected"  # other 4xx
RATE_LIMITED = "rate_limited"  # 429
PROVIDER_ERROR = "provider_error"  # 5xx / malformed frame / unreadable result
OUTPUT_INVALID = "output_invalid"
POLICY = "policy"              # refused target / redirect / bad framing policy
TLS_INVALID = "tls_invalid"

# Fixed, material-free diagnostic codes.
DETAIL = {
    "endpoint_invalid": "endpoint_invalid",
    "resolution_invalid": "resolution_invalid",
    "resolution_policy": "resolution_policy",
    "resolution_empty": "resolution_empty",
    "resolution_too_many": "resolution_too_many",
    "dns_failure": "dns_failure",
    "connect_timeout": "connect_timeout",
    "connect_failed": "connect_failed",
    "connect_budget": "connect_budget",
    "peer_mismatch": "peer_mismatch",
    "tls_verify": "tls_verify",
    "tls_handshake": "tls_handshake",
    "prepare_timeout": "prepare_timeout",
    "request_too_large": "request_too_large",
    "pre_send_timeout": "pre_send_timeout",
    "send_failed": "send_failed",
    "duplicate_header": "duplicate_header",
    "bad_transfer_encoding": "bad_transfer_encoding",
    "bad_content_encoding": "bad_content_encoding",
    "length_conflict": "length_conflict",
    "bad_content_length": "bad_content_length",
    "body_too_large": "body_too_large",
    "length_mismatch": "length_mismatch",
    "incomplete_body": "incomplete_body",
    "malformed_frame": "malformed_frame",
    "redirect": "redirect",
    "invalid_json_envelope": "invalid_json_envelope",
    "invalid_candidate_json": "invalid_candidate_json",
    "choices_count": "choices_count",
    "unexpected_finish": "unexpected_finish",
    "forbidden_field": "forbidden_field",
    "non_text_content": "non_text_content",
    "response_not_utf8": "response_not_utf8",
    "stream_truncated": "stream_truncated",
    "stream_invalid": "stream_invalid",
    "stream_too_large": "stream_too_large",
    "stream_unsupported": "stream_unsupported",
}

_USAGE_KEYS = frozenset(
    {
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "input_tokens",
        "output_tokens",
        "cached_tokens",
    }
)
_MAX_USAGE_KEYS = 8

_HEADER_NAME_RE = re.compile(r"^[A-Za-z0-9!#$%&'*+\-.^_`|~]+$")

_kernel32 = None


def now_ticks() -> int:
    """``GetTickCount64`` in milliseconds (monotonic across sleep)."""
    global _kernel32
    try:
        if _kernel32 is None:
            import ctypes  # noqa: PLC0415

            _kernel32 = ctypes.windll.kernel32
            _kernel32.GetTickCount64.restype = ctypes.c_ulonglong
        return int(_kernel32.GetTickCount64())
    except Exception:  # noqa: BLE001 - non-Windows unit-test host
        return int(time.monotonic() * 1000)


class _ResponseTooLarge(Exception):
    """Response framing exceeded an explicit cap."""


@dataclass
class TransportResult:
    """One attempt's classified outcome (no secret, no full response text)."""

    kind: str
    reason: str | None = None
    transient_not_sent: bool = False
    sent: bool = False
    http_status: int | None = None
    provider_request_id: str | None = None
    returned_model: str | None = None
    usage: dict[str, Any] | None = None
    candidate_text: str | None = None
    detail: str | None = None

    def to_wire(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "reason": self.reason,
            "transient_not_sent": self.transient_not_sent,
            "sent": self.sent,
            "http_status": self.http_status,
            "provider_request_id": self.provider_request_id,
            "returned_model": self.returned_model,
            "usage": self.usage,
            "candidate_text": self.candidate_text,
            "detail": self.detail,
        }

    @classmethod
    def from_wire(cls, data: dict[str, Any]) -> "TransportResult":
        return cls(
            kind=str(data.get("kind") or UNKNOWN),
            reason=data.get("reason") if isinstance(data.get("reason"), str) else None,
            transient_not_sent=bool(data.get("transient_not_sent")),
            sent=bool(data.get("sent")),
            http_status=data.get("http_status") if isinstance(data.get("http_status"), int) else None,
            provider_request_id=_sanitize_token(data.get("provider_request_id"), MAX_REQUEST_ID_LEN),
            returned_model=_sanitize_token(data.get("returned_model"), MAX_MODEL_LEN),
            usage=_sanitize_usage(data.get("usage")),
            candidate_text=data.get("candidate_text") if isinstance(data.get("candidate_text"), str) else None,
            detail=data.get("detail") if isinstance(data.get("detail"), str) else None,
        )


def _sanitize_token(value: Any, max_len: int) -> str | None:
    if not isinstance(value, str) or not value or len(value) > max_len:
        return None
    if any(ord(ch) < 0x20 or ch == "\x7f" for ch in value):
        return None
    return value


def _sanitize_usage(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict) or len(value) > _MAX_USAGE_KEYS:
        return None
    result: dict[str, Any] = {}
    for key, item in value.items():
        if not isinstance(key, str) or key not in _USAGE_KEYS:
            continue
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            continue
        # ``1e999`` parses to inf, which is not valid JSON: a non-finite value
        # is dropped rather than persisted as a non-JSON diagnostic.
        if isinstance(item, float) and not math.isfinite(item):
            continue
        result[key] = item
    return result or None


# ---------------------------------------------------------------------------
# URL / address policy
# ---------------------------------------------------------------------------


def build_target(base_url: str) -> tuple[str, str, int, str, str]:
    """Return ``(url, host, port, netloc, request_path)``.

    ``request_path`` is the normalized prefix path plus exactly one
    ``/chat/completions`` (``/v1`` and other vendor prefixes are preserved).
    """
    prefix = _normalize_base_url(base_url)  # raises AiEndpointInvalid
    parts = urlsplit(prefix)
    host = parts.hostname or ""
    port = parts.port or 443
    netloc = parts.netloc
    base_path = parts.path or ""
    path = base_path + COMPLETIONS_PATH
    return prefix + COMPLETIONS_PATH, host, port, netloc, path


def _address_allowed(ip: ipaddress._BaseAddress) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if ip.is_multicast or ip.is_unspecified or ip.is_reserved:
        return False
    if ip.is_private or ip.is_loopback or ip.is_link_local:
        return False
    return ip.is_global


def resolve_addresses(
    host: str,
    port: int,
    *,
    resolver: Sequence[dict[str, Any]] | None = None,
) -> tuple[list[tuple[int, str, int]], TransportResult | None]:
    """Resolve to numeric sockaddrs enforcing the policy."""
    raw: list[tuple[int, str, int]] = []
    if resolver is not None:
        for item in resolver:
            try:
                family = int(item["family"])
                address = str(item["ip"])
                sock_port = int(item.get("port", port))
            except (KeyError, TypeError, ValueError):
                return [], TransportResult(POLICY, reason="endpoint_blocked", detail=DETAIL["resolution_invalid"])
            if family not in (socket.AF_INET, socket.AF_INET6):
                return [], TransportResult(POLICY, reason="endpoint_blocked", detail=DETAIL["resolution_invalid"])
            raw.append((family, address, sock_port))
    else:
        try:
            infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except socket.gaierror:
            return [], TransportResult(
                NOT_SENT, reason="connection_unavailable", transient_not_sent=True, detail=DETAIL["dns_failure"]
            )
        except OSError:
            return [], TransportResult(
                NOT_SENT, reason="connection_unavailable", transient_not_sent=True, detail=DETAIL["dns_failure"]
            )
        for family, _type, _proto, _canon, sockaddr in infos:
            if family not in (socket.AF_INET, socket.AF_INET6):
                continue
            raw.append((family, sockaddr[0], int(sockaddr[1])))

    seen: set[tuple[int, str, int]] = set()
    addresses: list[tuple[int, str, int]] = []
    allow_private = resolver is not None
    for family, address, sock_port in raw:
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError:
            return [], TransportResult(POLICY, reason="endpoint_blocked", detail=DETAIL["resolution_invalid"])
        if not allow_private and not _address_allowed(parsed):
            return [], TransportResult(POLICY, reason="endpoint_blocked", detail=DETAIL["resolution_policy"])
        key = (family, str(parsed), sock_port)
        if key in seen:
            continue
        seen.add(key)
        addresses.append(key)
    if not addresses:
        return [], TransportResult(NOT_SENT, reason="connection_unavailable", transient_not_sent=True, detail=DETAIL["resolution_empty"])
    if len(addresses) > MAX_RESOLVED_ADDRESSES:
        return [], TransportResult(POLICY, reason="endpoint_blocked", detail=DETAIL["resolution_too_many"])
    return addresses, None


# ---------------------------------------------------------------------------
# Request serialization
# ---------------------------------------------------------------------------


def build_request(
    *, model: str, system_text: str, user_text: str, stream: bool = True
) -> bytes:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_text},
            {"role": "user", "content": user_text},
        ],
        "stream": bool(stream),
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _http_request_bytes(*, netloc: str, path: str, secret: str, body: bytes) -> bytes:
    head = (
        f"POST {path} HTTP/1.1\r\n"
        f"Host: {netloc}\r\n"
        f"Authorization: Bearer {secret}\r\n"
        "Content-Type: application/json\r\n"
        "Accept: application/json\r\n"
        "Accept-Encoding: identity\r\n"
        "Connection: close\r\n"
        f"Content-Length: {len(body)}\r\n"
        "\r\n"
    ).encode("ascii")
    return head + body


# ---------------------------------------------------------------------------
# Prepare / send
# ---------------------------------------------------------------------------


@dataclass
class Prepared:
    sock: ssl.SSLSocket
    host: str
    netloc: str
    path: str
    request_bytes: bytes
    _sent: bool = field(default=False, init=False)


def _connect_deadline(deadline_ms: int, start_ticks: int) -> int:
    return min(deadline_ms, start_ticks + CONNECT_BUDGET_MS)


def _remaining_ms(deadline_ms: int) -> int:
    return deadline_ms - now_ticks()


def prepare(
    *,
    base_url: str,
    model: str,
    secret: str,
    system_text: str,
    user_text: str,
    deadline_ms: int,
    resolver: Sequence[dict[str, Any]] | None = None,
    ca_pem: str | None = None,
) -> tuple[Prepared | None, TransportResult | None]:
    """DNS + TCP + TLS within the 10 s connect budget; no HTTP byte."""
    start_ticks = now_ticks()
    connect_deadline = _connect_deadline(deadline_ms, start_ticks)
    try:
        _url, host, port, netloc, path = build_target(base_url)
    except Exception:  # noqa: BLE001 - AiEndpointInvalid and friends
        return None, TransportResult(POLICY, reason="endpoint_blocked", detail=DETAIL["endpoint_invalid"])

    # DNS is part of the same 10 s budget as TCP and TLS.
    addresses, failure = resolve_addresses(host, port, resolver=resolver)
    if failure is not None:
        return None, failure

    context = ssl.create_default_context(cadata=ca_pem) if ca_pem else ssl.create_default_context()
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED

    last_transient: TransportResult | None = None
    for family, address, sock_port in addresses:
        remaining = connect_deadline - now_ticks()
        if remaining <= 0:
            break
        sock: socket.socket | None = None
        try:
            sock = socket.socket(family, socket.SOCK_STREAM)
            sock.settimeout(max(remaining, 1) / 1000.0)
            sock.connect((address, sock_port))
            peer = sock.getpeername()
            if str(peer[0]) != str(address):
                sock.close()
                return None, TransportResult(POLICY, reason="endpoint_blocked", detail=DETAIL["peer_mismatch"])
            remaining = connect_deadline - now_ticks()
            if remaining <= 0:
                sock.close()
                break
            sock.settimeout(max(remaining, 1) / 1000.0)
            tls_sock = context.wrap_socket(sock, server_hostname=host)
        except ssl.SSLCertVerificationError:
            if sock is not None:
                sock.close()
            return None, TransportResult(TLS_INVALID, reason="tls_invalid", detail=DETAIL["tls_verify"])
        except ssl.SSLError:
            if sock is not None:
                sock.close()
            return None, TransportResult(TLS_INVALID, reason="tls_invalid", detail=DETAIL["tls_handshake"])
        except (socket.timeout, TimeoutError):
            if sock is not None:
                sock.close()
            last_transient = TransportResult(NOT_SENT, reason="connection_unavailable", transient_not_sent=True, detail=DETAIL["connect_timeout"])
            continue
        except OSError:
            if sock is not None:
                sock.close()
            last_transient = TransportResult(NOT_SENT, reason="connection_unavailable", transient_not_sent=True, detail=DETAIL["connect_failed"])
            continue
        except Exception:  # noqa: BLE001
            if sock is not None:
                sock.close()
            last_transient = TransportResult(NOT_SENT, reason="connection_unavailable", transient_not_sent=True, detail=DETAIL["connect_failed"])
            continue

        if _remaining_ms(deadline_ms) <= 0:
            tls_sock.close()
            return None, TransportResult(NOT_SENT, reason="connection_unavailable", transient_not_sent=True, detail=DETAIL["prepare_timeout"])
        body = build_request(model=model, system_text=system_text, user_text=user_text)
        if len(body) > REQUEST_MAX_BYTES:
            tls_sock.close()
            return None, TransportResult(OUTPUT_INVALID, reason="output_invalid", detail=DETAIL["request_too_large"])
        request_bytes = _http_request_bytes(netloc=netloc, path=path, secret=secret, body=body)
        if len(request_bytes) > REQUEST_MAX_BYTES + 4096:
            tls_sock.close()
            return None, TransportResult(OUTPUT_INVALID, reason="output_invalid", detail=DETAIL["request_too_large"])
        return (
            Prepared(sock=tls_sock, host=host, netloc=netloc, path=path, request_bytes=request_bytes),
            None,
        )

    if last_transient is not None:
        return None, last_transient
    return None, TransportResult(NOT_SENT, reason="connection_unavailable", transient_not_sent=True, detail=DETAIL["connect_budget"])


class _BoundedFile(io.RawIOBase):
    """File wrapper that caps the header section and the body separately."""

    def __init__(self, raw: Any, *, header_limit: int, body_limit: int):
        self._raw = raw
        self._header_limit = header_limit
        self._body_limit = body_limit
        self._total = 0
        self._phase = "headers"

    def readable(self) -> bool:  # pragma: no cover - trivial
        return True

    def start_body(self) -> None:
        self._phase = "body"
        self._total = 0

    def _count(self, n: int) -> None:
        self._total += n
        if self._phase == "headers" and self._total > self._header_limit:
            raise _ResponseTooLarge("headers")
        if self._phase == "body" and self._total > self._body_limit:
            raise _ResponseTooLarge("body")

    def readline(self, size: int = -1) -> bytes:
        line = self._raw.readline(size)
        self._count(len(line))
        return line

    def read(self, size: int = -1) -> bytes:
        chunk = self._raw.read(size)
        self._count(len(chunk))
        return chunk

    def read1(self, size: int = -1) -> bytes:
        reader = getattr(self._raw, "read1", None)
        chunk = reader(size) if reader is not None else self._raw.read(size)
        self._count(len(chunk))
        return chunk

    def readinto(self, buffer) -> int:  # pragma: no cover - delegated
        n = self._raw.readinto(buffer)
        self._count(n or 0)
        return n

    def close(self) -> None:  # pragma: no cover - owned by the socket
        pass


class _SockAdapter:
    """Minimal socket facade so ``HTTPResponse`` uses our bounded file."""

    def __init__(self, sock: ssl.SSLSocket, fp: _BoundedFile):
        self._sock = sock
        self._fp = fp

    def makefile(self, *args: Any, **kwargs: Any) -> _BoundedFile:
        return self._fp

    def close(self) -> None:  # pragma: no cover - socket closed by caller
        pass


def _duplicate_header(headers: Any, name: str) -> bool:
    values = headers.get_all(name) or []
    return len(values) > 1


def _check_framing(headers: Any) -> tuple[int | None, bool, str | None]:
    """Return ``(content_length, chunked, error_code)`` for the response.

    A duplicated framing header, a non-``chunked`` ``Transfer-Encoding``, a
    ``Content-Length`` together with ``Transfer-Encoding``, a non-identity
    ``Content-Encoding`` or a non-canonical/oversized length is refused.
    """
    for name in ("Content-Length", "Transfer-Encoding", "Content-Encoding"):
        if _duplicate_header(headers, name):
            return None, False, DETAIL["duplicate_header"]
    encoding = headers.get("Content-Encoding")
    if encoding is not None and encoding.strip().lower() != "identity":
        return None, False, DETAIL["bad_content_encoding"]
    te = headers.get("Transfer-Encoding")
    chunked = False
    if te is not None:
        tokens = [token.strip().lower() for token in te.split(",") if token.strip()]
        if tokens != ["chunked"]:
            return None, False, DETAIL["bad_transfer_encoding"]
        chunked = True
    length = None
    raw_length = headers.get("Content-Length")
    if raw_length is not None:
        if chunked:
            return None, False, DETAIL["length_conflict"]
        raw = raw_length.strip()
        if not raw.isascii() or not raw.isdigit() or (len(raw) > 1 and raw.startswith("0")):
            return None, False, DETAIL["bad_content_length"]
        length = int(raw)
        if length > RESPONSE_MAX_BYTES:
            return None, False, DETAIL["body_too_large"]
    return length, chunked, None


def send(
    prepared: Prepared,
    *,
    deadline_ms: int,
    on_progress: Any = None,
    on_heartbeat: Any = None,
) -> TransportResult:
    """Write the single HTTP request and read the strictly validated response.

    ``on_progress(reasoning_delta, content_delta)`` is called for real SSE
    deltas only; ``on_heartbeat()`` is called for real SSE comments/keepalives.
    Both are display hooks and never change the final validation. A 200 response
    may be ``text/event-stream`` (streamed) or a plain JSON document
    (compatibility); a failed attempt is never retried here.
    """
    if _remaining_ms(deadline_ms) <= 0:
        prepared.sock.close()
        return TransportResult(NOT_SENT, reason="connection_unavailable", transient_not_sent=True, detail=DETAIL["pre_send_timeout"])
    sock = prepared.sock
    try:
        sock.sendall(prepared.request_bytes)
        prepared._sent = True
    except (socket.timeout, TimeoutError):
        sock.close()
        return TransportResult(UNKNOWN, reason="timeout_after_dispatch")
    except OSError:
        sock.close()
        # A socket send error does not prove that zero bytes left the process.
        return TransportResult(UNKNOWN, reason="timeout_after_dispatch", detail=DETAIL["send_failed"])

    raw = sock.makefile("rb", buffering=0)
    bounded = _BoundedFile(raw, header_limit=HEADER_MAX_BYTES, body_limit=RESPONSE_MAX_BYTES)
    adapter = _SockAdapter(sock, bounded)
    sock.settimeout(max(_remaining_ms(deadline_ms), 1) / 1000.0)
    response = http.client.HTTPResponse(adapter, method="POST")
    status: int | None = None
    provider_request_id: str | None = None
    length: int | None = None
    try:
        response.begin()
        status = response.status
        provider_request_id = _sanitize_token(
            response.getheader("x-request-id") or response.getheader("openai-request-id"),
            MAX_REQUEST_ID_LEN,
        )
        length, chunked, framing_error = _check_framing(response.headers)
        if framing_error is not None:
            return TransportResult(PROVIDER_ERROR, reason="provider_error", sent=True, http_status=status, detail=framing_error)
        bounded.start_body()
        content_type = (response.getheader("Content-Type") or "").lower()
        if status == 200 and "text/event-stream" in content_type:
            return _read_stream(
                response,
                deadline_ms,
                provider_request_id,
                on_progress,
                on_heartbeat,
                length,
                chunked,
            )
        body = response.read(RESPONSE_MAX_BYTES + 1)
    except _ResponseTooLarge:
        return TransportResult(PROVIDER_ERROR, reason="provider_error", sent=True, http_status=status, detail=DETAIL["body_too_large"])
    except http.client.IncompleteRead:
        return TransportResult(PROVIDER_ERROR, reason="provider_error", sent=True, http_status=status, detail=DETAIL["malformed_frame"])
    except (http.client.HTTPException, ValueError, OSError):
        return TransportResult(PROVIDER_ERROR, reason="provider_error", sent=True, http_status=status, detail=DETAIL["malformed_frame"])
    finally:
        try:
            response.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            sock.close()
        except Exception:  # noqa: BLE001
            pass

    if len(body) > RESPONSE_MAX_BYTES:
        return TransportResult(PROVIDER_ERROR, reason="provider_error", sent=True, http_status=status, detail=DETAIL["body_too_large"])
    if length is not None and len(body) != length:
        # A declared length that does not match the bytes read (short or long)
        # is a malformed frame, never a candidate.
        return TransportResult(PROVIDER_ERROR, reason="provider_error", sent=True, http_status=status, detail=DETAIL["length_mismatch"])

    if status == 200:
        return _parse_success(body, provider_request_id, sent=True)
    return _classify_http_status(status, provider_request_id, sent=True)


def _sse_event_boundary(text: str) -> int:
    return text.find("\n\n")


def _sse_data(event: str) -> str | None:
    data_lines: list[str] = []
    for line in event.split("\n"):
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip(" "))
    if not data_lines:
        return None
    return "\n".join(data_lines)


def _normalize_sse_buffer(text: str, *, final: bool) -> str:
    """Normalize SSE line endings without losing a split CRLF.

    A trailing CR is kept until the next chunk (or EOF), because ``\r`` may be
    the first half of a ``\r\n`` pair. Replacing it eagerly would turn a split
    CRLF into an extra blank line and end a multi-``data:`` event early.
    """
    normalized = text.replace("\r\n", "\n")
    if final:
        return normalized.replace("\r", "\n")
    if normalized.endswith("\r"):
        return normalized[:-1].replace("\r", "\n") + "\r"
    return normalized.replace("\r", "\n")


def _sse_has_comment(event: str) -> bool:
    return any(line.startswith(":") for line in event.split("\n"))


def _read_stream(
    response: Any,
    deadline_ms: int,
    provider_request_id: str | None,
    on_progress: Any,
    on_heartbeat: Any,
    expected_length: int | None,
    chunked: bool,
) -> TransportResult:
    """Incrementally parse a standard SSE chat-completions stream.

    Only ``delta.reasoning_content`` (display-only, forwarded to the progress
    hook) and ``delta.content`` (the final answer) are accumulated. A complete
    stream must carry ``finish_reason=stop`` on the single choice; ``[DONE]``
    only ends the event stream and never substitutes for that normal finish.
    The HTTP body is read to EOF and its declared Content-Length / chunked
    termination is verified before any success, so a short declared body is not
    a confirmed response. The final content then goes through the same strict
    JSON object validation as the non-stream path. A socket break/timeout is
    ``UNKNOWN`` (possibly sent, no confirmed result); a complete but malformed
    stream is refused as invalid output.
    """
    import codecs

    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    buffer = ""
    content_parts: list[str] = []
    state: dict[str, Any] = {
        "usage": None,
        "model": None,
        "finish_reason": None,
        "choice_index": None,
    }
    done = False
    body_bytes = 0

    def emit(reasoning: str, content: str) -> None:
        if on_progress is None:
            return
        try:
            on_progress(reasoning, content)
        except Exception:  # noqa: BLE001 - a display hook never breaks the attempt
            pass

    def heartbeat() -> None:
        if on_heartbeat is None:
            return
        try:
            on_heartbeat()
        except Exception:  # noqa: BLE001 - a display hook never breaks the attempt
            pass

    def apply_event(event_text: str) -> str | None:
        """Apply one data event; return an error detail or ``__done__``."""
        if event_text.strip() == "[DONE]":
            return "__done__"
        try:
            event = parse_strict_json_object(event_text)
        except ValueError:
            return DETAIL["stream_invalid"]
        if event.get("error") is not None:
            return DETAIL["stream_invalid"]
        if isinstance(event.get("usage"), dict):
            state["usage"] = _sanitize_usage(event["usage"])
        if not state["model"]:
            state["model"] = _sanitize_token(event.get("model"), MAX_MODEL_LEN)
        choices = event.get("choices")
        if not isinstance(choices, list):
            return DETAIL["stream_invalid"]
        if len(choices) > 1:
            return DETAIL["stream_invalid"]
        if len(choices) == 0:
            # Only a usage-only frame is legal; an empty frame is otherwise a
            # malformed stream.
            if not isinstance(event.get("usage"), dict):
                return DETAIL["stream_invalid"]
            return None
        choice = choices[0]
        if not isinstance(choice, dict):
            return DETAIL["stream_invalid"]
        index = choice.get("index")
        if index is not None:
            if not isinstance(index, int) or isinstance(index, bool) or index != 0:
                return DETAIL["stream_invalid"]
            if state["choice_index"] is not None and index != state["choice_index"]:
                return DETAIL["stream_invalid"]
            state["choice_index"] = index
        stopped_before = state["finish_reason"] is not None
        finish_reason = choice.get("finish_reason")
        if finish_reason is not None:
            if finish_reason != "stop":
                return DETAIL["unexpected_finish"]
            state["finish_reason"] = "stop"
        delta = choice.get("delta")
        if delta is None:
            # Compatibility with a provider that returns a full message chunk;
            # a finish-only/usage-adjacent terminal choice is also accepted.
            message = choice.get("message")
            if isinstance(message, dict):
                # A non-streaming-shaped message must pass the same forbidden
                # field checks even when its content is not a string and stop is
                # already present.
                for forbidden in ("tool_calls", "function_call", "refusal"):
                    if message.get(forbidden):
                        return DETAIL["forbidden_field"]
                if isinstance(message.get("content"), str):
                    delta = message
                elif state["finish_reason"] is not None:
                    return None
                else:
                    return DETAIL["stream_invalid"]
            elif state["finish_reason"] is not None:
                return None
            else:
                return DETAIL["stream_invalid"]
        if not isinstance(delta, dict):
            return DETAIL["stream_invalid"]
        for forbidden in ("tool_calls", "function_call", "refusal"):
            if delta.get(forbidden):
                return DETAIL["forbidden_field"]
        reasoning = delta.get("reasoning_content")
        content = delta.get("content")
        if reasoning is not None and not isinstance(reasoning, str):
            return DETAIL["stream_invalid"]
        if content is not None and not isinstance(content, str):
            return DETAIL["stream_invalid"]
        # Content/reasoning in the *same* chunk as the stop marker is the normal
        # final token; content after a previous stop is a different answer and
        # must never be appended.
        if stopped_before and (reasoning or content):
            return DETAIL["stream_invalid"]
        if reasoning:
            emit(reasoning, "")
        if content:
            content_parts.append(content)
            emit("", content)
        return None

    def process_buffer(*, final: bool) -> TransportResult | None:
        nonlocal buffer, done
        buffer = _normalize_sse_buffer(buffer, final=final)
        while True:
            if done:
                buffer = ""
                return None
            boundary = _sse_event_boundary(buffer)
            if boundary < 0:
                return None
            event_text, buffer = buffer[:boundary], buffer[boundary + 2:]
            if _sse_has_comment(event_text):
                heartbeat()
            data = _sse_data(event_text)
            if data is None or not data.strip():
                continue
            error = apply_event(data)
            if error == "__done__":
                done = True
                buffer = ""
                return None
            if error is not None:
                return TransportResult(
                    OUTPUT_INVALID,
                    reason="output_invalid",
                    sent=True,
                    http_status=200,
                    provider_request_id=provider_request_id,
                    detail=error,
                )

    while True:
        if _remaining_ms(deadline_ms) <= 0:
            return TransportResult(
                UNKNOWN,
                reason="timeout_after_dispatch",
                sent=True,
                http_status=200,
                provider_request_id=provider_request_id,
                detail=DETAIL["stream_truncated"],
            )
        try:
            chunk = response.read1(65536)
        except _ResponseTooLarge:
            return TransportResult(PROVIDER_ERROR, reason="provider_error", sent=True, http_status=200, provider_request_id=provider_request_id, detail=DETAIL["body_too_large"])
        except (socket.timeout, TimeoutError):
            return TransportResult(UNKNOWN, reason="timeout_after_dispatch", sent=True, http_status=200, provider_request_id=provider_request_id, detail=DETAIL["stream_truncated"])
        except (http.client.IncompleteRead, OSError, ValueError):
            return TransportResult(UNKNOWN, reason="timeout_after_dispatch", sent=True, http_status=200, provider_request_id=provider_request_id, detail=DETAIL["stream_truncated"])
        if not chunk:
            break
        body_bytes += len(chunk)
        try:
            buffer += decoder.decode(chunk)
        except UnicodeDecodeError:
            return TransportResult(OUTPUT_INVALID, reason="output_invalid", sent=True, http_status=200, provider_request_id=provider_request_id, detail=DETAIL["response_not_utf8"])
        if done:
            # The answer ended at [DONE]; keep reading only to validate the
            # transport and UTF-8 tail, never to append more content.
            continue
        failure = process_buffer(final=False)
        if failure is not None:
            return failure

    # A split trailing CR is a real line ending at EOF; process any final event
    # before the strict decoder flush catches an incomplete multibyte tail.
    failure = process_buffer(final=True)
    if failure is not None:
        return failure
    try:
        decoder.decode(b"", final=True)
    except UnicodeDecodeError:
        return TransportResult(OUTPUT_INVALID, reason="output_invalid", sent=True, http_status=200, provider_request_id=provider_request_id, detail=DETAIL["response_not_utf8"])

    if expected_length is not None and body_bytes != expected_length:
        return TransportResult(
            UNKNOWN,
            reason="timeout_after_dispatch",
            sent=True,
            http_status=200,
            provider_request_id=provider_request_id,
            detail=DETAIL["incomplete_body"],
        )
    if chunked and not bool(getattr(response, "isclosed", lambda: True)()):
        return TransportResult(
            UNKNOWN,
            reason="timeout_after_dispatch",
            sent=True,
            http_status=200,
            provider_request_id=provider_request_id,
            detail=DETAIL["incomplete_body"],
        )
    if state["finish_reason"] != "stop":
        # [DONE] alone, a truncated stream, or a missing normal finish is not a
        # complete answer, regardless of any partial content received.
        return TransportResult(
            OUTPUT_INVALID,
            reason="output_invalid",
            sent=True,
            http_status=200,
            provider_request_id=provider_request_id,
            detail=DETAIL["stream_truncated"],
        )
    content = "".join(content_parts)
    try:
        parse_strict_json_object(content)
    except ValueError:
        return TransportResult(OUTPUT_INVALID, reason="output_invalid", sent=True, http_status=200, provider_request_id=provider_request_id, detail=DETAIL["invalid_candidate_json"])
    return TransportResult(
        SUCCESS,
        sent=True,
        http_status=200,
        provider_request_id=provider_request_id,
        returned_model=state["model"],
        usage=state["usage"],
        candidate_text=content,
    )


def _classify_http_status(status: int, provider_request_id: str | None, *, sent: bool) -> TransportResult:
    if 300 <= status < 400:
        return TransportResult(POLICY, reason="endpoint_blocked", sent=sent, http_status=status, provider_request_id=provider_request_id, detail=DETAIL["redirect"])
    if status in (401, 403):
        return TransportResult(AUTH, reason="auth_rejected", sent=sent, http_status=status, provider_request_id=provider_request_id)
    if status == 429:
        return TransportResult(RATE_LIMITED, reason="rate_limited", sent=sent, http_status=status, provider_request_id=provider_request_id)
    if 400 <= status < 500:
        return TransportResult(CONFIG_REJECTED, reason="provider_error", sent=sent, http_status=status, provider_request_id=provider_request_id)
    return TransportResult(PROVIDER_ERROR, reason="provider_error", sent=sent, http_status=status, provider_request_id=provider_request_id)


def _reject_constant(value: str) -> Any:
    raise ValueError("illegal json constant")


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def parse_strict_json_object(text: str) -> dict[str, Any]:
    """Parse exactly one JSON object; duplicate keys and NaN are refused."""
    obj = json.loads(
        text,
        object_pairs_hook=_reject_duplicates,
        parse_constant=_reject_constant,
    )
    if not isinstance(obj, dict):
        raise ValueError("not an object")
    return obj


def _parse_success(body: bytes, provider_request_id: str | None, *, sent: bool) -> TransportResult:
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return TransportResult(OUTPUT_INVALID, reason="output_invalid", sent=sent, http_status=200, provider_request_id=provider_request_id, detail=DETAIL["response_not_utf8"])
    try:
        envelope = parse_strict_json_object(text)
    except ValueError:
        return TransportResult(OUTPUT_INVALID, reason="output_invalid", sent=sent, http_status=200, provider_request_id=provider_request_id, detail=DETAIL["invalid_json_envelope"])
    choices = envelope.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        return TransportResult(OUTPUT_INVALID, reason="output_invalid", sent=sent, http_status=200, provider_request_id=provider_request_id, detail=DETAIL["choices_count"])
    choice = choices[0]
    if not isinstance(choice, dict):
        return TransportResult(OUTPUT_INVALID, reason="output_invalid", sent=sent, http_status=200, provider_request_id=provider_request_id, detail=DETAIL["choices_count"])
    if choice.get("finish_reason") != "stop":
        return TransportResult(OUTPUT_INVALID, reason="output_invalid", sent=sent, http_status=200, provider_request_id=provider_request_id, detail=DETAIL["unexpected_finish"])
    message = choice.get("message")
    if not isinstance(message, dict):
        return TransportResult(OUTPUT_INVALID, reason="output_invalid", sent=sent, http_status=200, provider_request_id=provider_request_id, detail=DETAIL["choices_count"])
    for forbidden in ("tool_calls", "function_call", "refusal"):
        if message.get(forbidden):
            return TransportResult(OUTPUT_INVALID, reason="output_invalid", sent=sent, http_status=200, provider_request_id=provider_request_id, detail=DETAIL["forbidden_field"])
    content = message.get("content")
    if not isinstance(content, str):
        return TransportResult(OUTPUT_INVALID, reason="output_invalid", sent=sent, http_status=200, provider_request_id=provider_request_id, detail=DETAIL["non_text_content"])
    try:
        parse_strict_json_object(content)
    except ValueError:
        return TransportResult(OUTPUT_INVALID, reason="output_invalid", sent=sent, http_status=200, provider_request_id=provider_request_id, detail=DETAIL["invalid_candidate_json"])
    return TransportResult(
        SUCCESS,
        sent=sent,
        http_status=200,
        provider_request_id=provider_request_id,
        returned_model=_sanitize_token(envelope.get("model"), MAX_MODEL_LEN),
        usage=_sanitize_usage(envelope.get("usage")),
        candidate_text=content,
    )


__all__ = [
    "ATTEMPT_BUDGET_MS",
    "COMPLETIONS_PATH",
    "CONNECT_BUDGET_MS",
    "CONFIG_REJECTED",
    "HEADER_MAX_BYTES",
    "MAX_RESOLVED_ADDRESSES",
    "NOT_SENT",
    "OUTPUT_INVALID",
    "POLICY",
    "PROTOCOL_ID",
    "PROVIDER_ERROR",
    "RATE_LIMITED",
    "REQUEST_MAX_BYTES",
    "RESPONSE_MAX_BYTES",
    "SUCCESS",
    "TLS_INVALID",
    "UNKNOWN",
    "AUTH",
    "DETAIL",
    "Prepared",
    "TransportResult",
    "build_request",
    "build_target",
    "now_ticks",
    "parse_strict_json_object",
    "prepare",
    "resolve_addresses",
    "send",
]
