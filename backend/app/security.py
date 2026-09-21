import base64
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from fastapi import Request, Response

from app.config import settings


_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 64
_SALT_BYTES = 32


def generate_id() -> str:
    """Opaque stable identifier (22 url-safe characters)."""
    return secrets.token_urlsafe(16)


def hash_password(password: str) -> str:
    """Hash a password with scrypt and a random salt."""
    salt = secrets.token_bytes(_SALT_BYTES)
    hashed = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        maxmem=0,
        dklen=_SCRYPT_DKLEN,
    )
    return (
        f"$scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}"
        f"${base64.b64encode(salt).decode('ascii')}"
        f"${base64.b64encode(hashed).decode('ascii')}"
    )


def verify_password(password: str, phc: str) -> bool:
    """Verify a password against a stored scrypt PHC string."""
    try:
        parts = phc.split("$")
        if len(parts) != 7 or parts[1] != "scrypt":
            return False
        n = int(parts[2])
        r = int(parts[3])
        p = int(parts[4])
        salt = base64.b64decode(parts[5].encode("ascii"))
        stored_hash = base64.b64decode(parts[6].encode("ascii"))
        computed = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=n,
            r=r,
            p=p,
            maxmem=0,
            dklen=len(stored_hash),
        )
        return hmac.compare_digest(computed, stored_hash)
    except Exception:
        return False


def create_session() -> tuple[str, str]:
    """Return (plain token, sha256 hex hash) for a new session."""
    token = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
    return token, token_hash


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def set_session_cookie(response: Response, token: str, max_age: int) -> None:
    response.set_cookie(
        key="session",
        value=token,
        max_age=max_age,
        path="/",
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key="session",
        path="/",
        samesite="lax",
        secure=settings.cookie_secure,
        httponly=True,
    )


def normalize_username(username: str) -> str:
    u = username.strip().lower()
    if len(u) < 3 or len(u) > 32:
        raise ValueError("用户名长度应为 3–32 位")
    if not re.fullmatch(r"^[a-z0-9_.-]+$", u):
        raise ValueError("用户名只能包含字母、数字、下划线、连字符或点")
    if not any(c.isalnum() for c in u):
        raise ValueError("用户名至少需要一位字母或数字")
    return u


def validate_password(password: str) -> None:
    if len(password) < 12 or len(password) > 128:
        raise ValueError("密码长度应为 12–128 位")


def normalize_display_name(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if cleaned == "":
        return None
    if len(cleaned) > 80:
        raise ValueError("姓名长度不能超过 80 个字符")
    return cleaned


def is_safe_origin(request: Request) -> bool:
    """Allow requests whose Origin header exactly matches an allowed origin.

    The Origin header is browser-controlled; a missing header or a Referer
    fallback is not accepted.
    """
    allowed = settings.allowed_origin_list()
    origin = request.headers.get("origin")
    if not origin:
        return False
    return _origin_matches(origin, allowed)


def _origin_matches(origin: str, allowed: list[str]) -> bool:
    return any(hmac.compare_digest(origin, a) for a in allowed)


def safe_hash_token(token: str) -> str | None:
    """Hash a session token, treating non-ASCII tokens as invalid."""
    try:
        return hashlib.sha256(token.encode("ascii")).hexdigest()
    except UnicodeEncodeError:
        return None


def session_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=settings.session_ttl_seconds)
