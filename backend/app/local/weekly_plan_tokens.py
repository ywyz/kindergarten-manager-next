"""Private weekly-plan preview/export tokens.

Keys are random per ``LocalRuntime`` instance and live only in memory, so a
restore/reopen generation (which retires the runtime) can never accept a
token minted before it.  Tokens are HMAC-SHA256 over canonical JSON and are
scoped to one purpose, profile, launch, app-session scope, object/version,
source context and facts/target hash.  The plaintext token is returned only
to the restricted caller; only its SHA-256 digest is stored.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from typing import Any

from app.local.errors import LocalWeeklyPreviewExpired, LocalWeeklyPreviewStale

TOKEN_VERSION = 1
PREVIEW_TTL_SECONDS = 600
PURPOSES = frozenset({"create", "refresh", "confirm", "export"})
_KEY_ATTRIBUTE = "_weekly_hmac_key"
_DOMAIN = b"kgm-weekly-token-v1\x00"
_EXPORT_DOMAIN = b"kgm-weekly-export-id-v1\x00"
_KEY_LOCK = threading.Lock()


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def sha256_hex(value: bytes | str) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def scope_hash(session_scope: str) -> str:
    return sha256_hex(f"scope:{session_scope}")


def token_hash(token: str) -> str:
    return sha256_hex(f"token:{token}")


def export_id_hash(export_id: str) -> str:
    return sha256_hex(f"export:{export_id}")


def _key(runtime: Any) -> bytes:
    if runtime is None:
        raise LocalWeeklyPreviewStale()
    with _KEY_LOCK:
        key = getattr(runtime, _KEY_ATTRIBUTE, None)
        if key is None:
            key = secrets.token_bytes(32)
            setattr(runtime, _KEY_ATTRIBUTE, key)
        return key


def rotate_key(runtime: Any) -> None:
    """Retire every outstanding weekly token for this runtime generation."""
    if runtime is not None:
        with _KEY_LOCK:
            setattr(runtime, _KEY_ATTRIBUTE, secrets.token_bytes(32))


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _sign(key: bytes, purpose: str, payload: bytes) -> bytes:
    return hmac.new(
        key, _DOMAIN + purpose.encode("ascii") + b"\x00" + payload,
        hashlib.sha256,
    ).digest()


def issue_token(
    runtime: Any,
    *,
    purpose: str,
    profile_id: str,
    launch_id: str,
    session_scope_hash: str,
    object_id: str,
    expected_version: int | None = None,
    source_context_hash: str | None = None,
    facts_hash: str | None = None,
    target_hash: str | None = None,
    ttl: int = PREVIEW_TTL_SECONDS,
) -> str:
    if purpose not in PURPOSES:
        raise ValueError("unknown weekly token purpose")
    now = int(time.time())
    payload = {
        "v": TOKEN_VERSION,
        "purpose": purpose,
        "profile_id": profile_id,
        "launch_id": launch_id,
        "scope": session_scope_hash,
        "object_id": object_id,
        "expected_version": expected_version,
        "source_context_hash": source_context_hash,
        "facts_hash": facts_hash,
        "target_hash": target_hash,
        "iat": now,
        "exp": now + int(ttl),
        "nonce": secrets.token_hex(8),
    }
    raw = canonical_json(payload).encode("utf-8")
    signature = _sign(_key(runtime), purpose, raw)
    return f"v{TOKEN_VERSION}.{_b64(raw)}.{_b64(signature)}"


def verify_token(
    runtime: Any,
    token: object,
    *,
    purpose: str,
    profile_id: str,
    launch_id: str,
    session_scope_hash: str,
    object_id: str | None = None,
    expected_version: int | None = None,
    source_context_hash: str | None = None,
    facts_hash: str | None = None,
    target_hash: str | None = None,
) -> dict:
    if not isinstance(token, str) or len(token) > 4096:
        raise LocalWeeklyPreviewStale()
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != f"v{TOKEN_VERSION}":
        raise LocalWeeklyPreviewStale()
    try:
        raw = _unb64(parts[1])
        signature = _unb64(parts[2])
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, TypeError):
        raise LocalWeeklyPreviewStale() from None
    if not isinstance(payload, dict) or payload.get("v") != TOKEN_VERSION:
        raise LocalWeeklyPreviewStale()
    expected_signature = _sign(_key(runtime), purpose, raw)
    if not hmac.compare_digest(signature, expected_signature):
        raise LocalWeeklyPreviewStale()
    if payload.get("purpose") != purpose:
        raise LocalWeeklyPreviewStale()
    if payload.get("profile_id") != profile_id:
        raise LocalWeeklyPreviewStale()
    if payload.get("launch_id") != launch_id:
        raise LocalWeeklyPreviewStale()
    if payload.get("scope") != session_scope_hash:
        raise LocalWeeklyPreviewStale()
    if object_id is not None and payload.get("object_id") != object_id:
        raise LocalWeeklyPreviewStale()
    if (
        expected_version is not None
        and payload.get("expected_version") != expected_version
    ):
        raise LocalWeeklyPreviewStale()
    if (
        source_context_hash is not None
        and payload.get("source_context_hash") != source_context_hash
    ):
        raise LocalWeeklyPreviewStale()
    if facts_hash is not None and payload.get("facts_hash") != facts_hash:
        raise LocalWeeklyPreviewStale()
    if target_hash is not None and payload.get("target_hash") != target_hash:
        raise LocalWeeklyPreviewStale()
    expires = payload.get("exp")
    if not isinstance(expires, int) or expires < int(time.time()):
        raise LocalWeeklyPreviewExpired()
    return payload


def derive_export_id(
    runtime: Any,
    *,
    profile_id: str,
    snapshot_id: str,
    token_id: str,
    request_id: str,
    launch_id: str,
    session_scope_hash: str,
) -> str:
    """Deterministic opaque export id for one committed export receipt."""
    payload = canonical_json(
        {
            "profile_id": profile_id,
            "snapshot_id": snapshot_id,
            "token_id": token_id,
            "request_id": request_id,
            "launch_id": launch_id,
            "scope": session_scope_hash,
        }
    ).encode("utf-8")
    digest = hmac.new(
        _key(runtime), _EXPORT_DOMAIN + payload, hashlib.sha256
    ).digest()
    return "w" + _b64(digest)
