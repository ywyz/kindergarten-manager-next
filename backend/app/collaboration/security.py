"""Bearer and preview-token handling for online collaboration.

Teacher bearer tokens are high-entropy random values.  Only a keyed SHA-256
digest is stored; revocation and expiry are checked on every authenticated
request.  Preview tokens are stateless, signed values so cancelling a preview
needs no database write.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from .errors import auth_required, preview_expired, preview_invalid
from .models import School, Teacher, TeacherToken

_MAX_PREVIEW_TOKEN_CHARS = 4096
_PREVIEW_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]+\.[0-9a-f]{64}")


def normalize_utc(value: datetime | None) -> datetime | None:
    """Treat naive database values as UTC; normalize aware values to UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class TeacherPrincipal:
    teacher_id: UUID
    school_id: UUID
    display_name: str
    school_name: str
    token_id: UUID


@dataclass(frozen=True)
class PreviewClaims:
    request_id: UUID
    actor_teacher_id: UUID
    school_id: UUID
    class_id: UUID
    actor_membership_generation: UUID
    source_membership_generation: UUID
    source_teacher_id: UUID
    source_version: int
    target_version: int
    expires_at: int


def issue_bearer_token(pepper: str) -> tuple[str, str]:
    """Return (plaintext token, stored HMAC digest)."""
    token = secrets.token_urlsafe(32)
    return token, digest_bearer_token(token, pepper)


def digest_bearer_token(token: str, pepper: str) -> str:
    if not token or not pepper:
        raise ValueError("token and pepper are required")
    return hmac.new(
        pepper.encode("utf-8"), token.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def authenticate(
    session: Session, token: str, pepper: str
) -> TeacherPrincipal:
    if not token or not pepper:
        raise auth_required()
    try:
        digest = digest_bearer_token(token, pepper)
    except ValueError:
        raise auth_required() from None
    row = session.execute(
        select(TeacherToken, Teacher, School)
        .join(Teacher, TeacherToken.teacher_id == Teacher.id)
        .join(School, Teacher.school_id == School.id)
        .where(
            TeacherToken.token_hash == digest,
            TeacherToken.revoked_at.is_(None),
        )
    ).one_or_none()
    if row is None:
        session.rollback()
        raise auth_required()
    token_row, teacher, school = row
    now = datetime.now(timezone.utc)
    expires = normalize_utc(token_row.expires_at)
    if expires is not None:
        if expires <= now:
            session.rollback()
            raise auth_required()
    if not teacher.active:
        session.rollback()
        raise auth_required()
    principal = TeacherPrincipal(
        teacher_id=teacher.id,
        school_id=school.id,
        display_name=teacher.display_name,
        school_name=school.name,
        token_id=token_row.id,
    )
    # Authentication is a read-only preflight.  End write services begin a
    # fresh transaction after this closes the SELECT transaction.
    session.rollback()
    return principal


def _encode_body(payload: dict[str, Any]) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _decode_body(body: str) -> dict[str, Any]:
    padding = "=" * (-len(body) % 4)
    raw = base64.urlsafe_b64decode((body + padding).encode("ascii"))
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("preview payload is not an object")
    return value


def _signature(body: str, secret: str) -> str:
    return hmac.new(
        secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256
    ).hexdigest()


def issue_preview_token(
    *,
    secret: str,
    request_id: UUID,
    actor_teacher_id: UUID,
    school_id: UUID,
    class_id: UUID,
    actor_membership_generation: UUID,
    source_membership_generation: UUID,
    source_teacher_id: UUID,
    source_version: int,
    target_version: int,
    ttl_seconds: int,
    now: int | None = None,
) -> tuple[str, datetime]:
    issued_at = int(time.time() if now is None else now)
    expires_at = issued_at + int(ttl_seconds)
    body = _encode_body(
        {
            "request_id": str(request_id),
            "actor_teacher_id": str(actor_teacher_id),
            "school_id": str(school_id),
            "class_id": str(class_id),
            "actor_membership_generation": str(actor_membership_generation),
            "source_membership_generation": str(source_membership_generation),
            "source_teacher_id": str(source_teacher_id),
            "source_version": int(source_version),
            "target_version": int(target_version),
            "exp": expires_at,
        }
    )
    token = f"{body}.{_signature(body, secret)}"
    return token, datetime.fromtimestamp(expires_at, tz=timezone.utc)


def read_preview_token(
    *,
    secret: str,
    token: str,
    allow_expired: bool = False,
    now: int | None = None,
) -> PreviewClaims:
    # Check the bounded ASCII shape before HMAC/JSON/base64 work.  A token
    # carrying non-ASCII text must be a normal PREVIEW_INVALID response, not
    # a UnicodeEncodeError/TypeError turned into HTTP 500.
    if (
        not secret
        or not isinstance(token, str)
        or len(token) > _MAX_PREVIEW_TOKEN_CHARS
        or not token.isascii()
        or _PREVIEW_TOKEN_PATTERN.fullmatch(token) is None
    ):
        raise preview_invalid()
    body, supplied_signature = token.split(".", 1)
    expected_signature = _signature(body, secret)
    if not hmac.compare_digest(supplied_signature, expected_signature):
        raise preview_invalid()
    try:
        payload = _decode_body(body)
        claims = PreviewClaims(
            request_id=UUID(str(payload["request_id"])),
            actor_teacher_id=UUID(str(payload["actor_teacher_id"])),
            school_id=UUID(str(payload["school_id"])),
            class_id=UUID(str(payload["class_id"])),
            actor_membership_generation=UUID(
                str(payload["actor_membership_generation"])
            ),
            source_membership_generation=UUID(
                str(payload["source_membership_generation"])
            ),
            source_teacher_id=UUID(str(payload["source_teacher_id"])),
            source_version=int(payload["source_version"]),
            target_version=int(payload["target_version"]),
            expires_at=int(payload["exp"]),
        )
    except (
        KeyError,
        TypeError,
        ValueError,
        UnicodeError,
        binascii.Error,
        json.JSONDecodeError,
    ):
        raise preview_invalid() from None
    if claims.source_version < 1 or claims.target_version < 0:
        raise preview_invalid()
    current = int(time.time() if now is None else now)
    if current >= claims.expires_at and not allow_expired:
        raise preview_expired()
    return claims
