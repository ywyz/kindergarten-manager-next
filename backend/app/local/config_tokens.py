"""Preview tokens for configuration maintenance (D1B spec §10.2).

The token binds one preview to this launch's in-memory HMAC-SHA256 key,
the normalized change, the configuration version, the candidate calendar
digest and the complete impact facts digest. Keys live in memory only:
after a process restart every outstanding token is invalid and the user
must preview again. The token never contains lesson-plan content.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time

from app.local.errors import LocalConfigPreviewExpired, LocalValidationError

# Fixed by the spec: preview tokens are valid for 10 minutes.
PREVIEW_TTL_SECONDS = 600
TOKEN_VERSION = 1

_signing_key: bytes | None = None


def _key() -> bytes:
    """Per-process signing key; generated on first use, never persisted."""
    global _signing_key
    if _signing_key is None:
        _signing_key = secrets.token_bytes(32)
    return _signing_key


def _canonical(value) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    )


def digest(value) -> str:
    """Canonical sha256 over any JSON-able structure (stable key order)."""
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _json_default(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    raise TypeError(f"not JSON serializable: {type(value)!r}")


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def sign_preview_token(payload: dict) -> str:
    """Sign one preview payload; returns ``body.signature``."""
    body = _b64encode(_canonical(payload).encode("utf-8"))
    signature = hmac.new(
        _key(), body.encode("ascii"), hashlib.sha256
    ).hexdigest()
    return f"{body}.{signature}"


def new_preview_payload(
    *,
    config_version: int,
    change: dict,
    changed: bool,
    premise_digest: str,
    candidate_digest: str,
    impact_digest: str,
) -> dict:
    return {
        "v": TOKEN_VERSION,
        "exp": int(time.time()) + PREVIEW_TTL_SECONDS,
        "config_version": config_version,
        "change": change,
        "changed": changed,
        "premise_digest": premise_digest,
        "candidate_digest": candidate_digest,
        "impact_digest": impact_digest,
    }


def verify_preview_token(token: object) -> dict:
    """Verify signature and freshness; invalid tokens are 422, expired 409."""
    if not isinstance(token, str) or token.count(".") != 1:
        raise LocalValidationError("预览令牌无效")
    body, signature = token.split(".")
    if not body or not signature:
        raise LocalValidationError("预览令牌无效")
    # Non-ASCII bodies/signatures (e.g. ``中文.abcd``) are invalid input, not
    # internal errors: encode defensively and report the normal 422.
    try:
        body_bytes = body.encode("ascii")
        signature_bytes = signature.encode("ascii")
    except UnicodeEncodeError:
        raise LocalValidationError("预览令牌无效") from None
    expected = hmac.new(_key(), body_bytes, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature_bytes, expected.encode("ascii")):
        raise LocalValidationError("预览令牌无效")
    try:
        payload = json.loads(_b64decode(body).decode("utf-8"))
    except (ValueError, UnicodeError):
        raise LocalValidationError("预览令牌无效") from None
    if not isinstance(payload, dict) or payload.get("v") != TOKEN_VERSION:
        raise LocalValidationError("预览令牌无效")
    expires = payload.get("exp")
    if not isinstance(expires, int):
        raise LocalValidationError("预览令牌无效")
    if time.time() > expires:
        raise LocalConfigPreviewExpired()
    return payload
