"""Administrator authentication and one-time teacher-code transactions.

The administrator is deliberately independent from teacher bearer identities.
Passwords are stored with scrypt, session and CSRF tokens are stored only as
keyed digests, and one-time codes are stored only as keyed digests.  Code
redemption is a single transaction: the code row is locked, the teacher and
school are rechecked, the code is consumed and the teacher bearer token is
issued, then everything commits or rolls back together.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from .admin_models import AdminCode, AdminSession, AdminUser
from .config import CollaborationSettings
from .class_promotion_models import CollaborationTerm, effective_class_name_now
from .errors import CollaborationError
from .models import Classroom, School, Teacher, TeacherClassMembership, TeacherToken
from .schemas import MembershipOut
from .security import issue_bearer_token

ADMIN_COOKIE = "kgm_admin_session"
ADMIN_CSRF_COOKIE = "kgm_admin_csrf"
ADMIN_CSRF_HEADER = "x-csrf-token"
ADMIN_SESSION_TTL_SECONDS = 3600
ADMIN_CODE_TTL_SECONDS = 86400
ADMIN_LOCK_SECONDS = 300
ADMIN_MAX_FAILED_ATTEMPTS = 5
ADMIN_TEACHER_TOKEN_TTL_DAYS = 30
ADMIN_PASSWORD_MIN_CHARS = 12
ADMIN_PASSWORD_MAX_CHARS = 4096

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32
_USERNAME_RE = re.compile(r"[A-Za-z0-9_.-]{3,80}\Z")
_CODE_MAX_CHARS = 512


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, value))


def _session_ttl_seconds() -> int:
    return _env_int("KGM_COLLAB_ADMIN_SESSION_TTL_SECONDS", ADMIN_SESSION_TTL_SECONDS, 300, 86400)


def _code_ttl_seconds() -> int:
    return _env_int("KGM_COLLAB_ADMIN_CODE_TTL_SECONDS", ADMIN_CODE_TTL_SECONDS, 300, 604800)


def _lock_seconds() -> int:
    return _env_int("KGM_COLLAB_ADMIN_LOCK_SECONDS", ADMIN_LOCK_SECONDS, 30, 86400)


def _max_failed_attempts() -> int:
    return _env_int("KGM_COLLAB_ADMIN_MAX_FAILED_ATTEMPTS", ADMIN_MAX_FAILED_ATTEMPTS, 3, 20)


def _teacher_token_ttl_days() -> int:
    return _env_int("KGM_COLLAB_TEACHER_TOKEN_TTL_DAYS", ADMIN_TEACHER_TOKEN_TTL_DAYS, 1, 3650)


def admin_cookie_secure() -> bool:
    value = os.environ.get("KGM_COLLAB_ADMIN_COOKIE_SECURE", "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def _password_hash_with_salt(password: str, salt: bytes) -> str:
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_DKLEN,
    )
    return (
        f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}"
        f"${_b64(salt)}${_b64(digest)}"
    )


def validate_admin_username(username: str) -> str:
    value = username.strip() if isinstance(username, str) else ""
    if _USERNAME_RE.fullmatch(value) is None:
        raise ValueError("管理员用户名需为 3–80 位字母、数字、点、下划线或连字符")
    return value


def validate_admin_password(password: str) -> str:
    if not isinstance(password, str):
        raise ValueError("密码必须是字符串")
    if not (
        ADMIN_PASSWORD_MIN_CHARS
        <= len(password)
        <= ADMIN_PASSWORD_MAX_CHARS
    ):
        raise ValueError(
            f"管理员密码长度必须为 {ADMIN_PASSWORD_MIN_CHARS}–"
            f"{ADMIN_PASSWORD_MAX_CHARS} 个字符"
        )
    if "\x00" in password:
        raise ValueError("管理员密码不能包含空字符")
    return password


def hash_password(password: str) -> str:
    validated = validate_admin_password(password)
    return _password_hash_with_salt(validated, secrets.token_bytes(16))


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, n_text, r_text, p_text, salt_text, digest_text = encoded.split("$")
        if scheme != "scrypt":
            return False
        n, r, p = int(n_text), int(r_text), int(p_text)
        if (n, r, p) != (_SCRYPT_N, _SCRYPT_R, _SCRYPT_P):
            return False
        salt = _unb64(salt_text)
        expected = _unb64(digest_text)
        if len(expected) != _SCRYPT_DKLEN:
            return False
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=n,
            r=r,
            p=p,
            dklen=_SCRYPT_DKLEN,
        )
        return hmac.compare_digest(actual, expected)
    except (AttributeError, TypeError, ValueError, UnicodeError):
        return False


# A fixed-format dummy hash keeps unknown-user login work roughly comparable to
# a real verification without ever accepting a password.
_DUMMY_HASH = _password_hash_with_salt(
    "this-password-is-never-accepted", b"kgm-admin-dummy"
)


def _secret_digest(settings: CollaborationSettings, value: str) -> str:
    return hmac.new(
        settings.token_pepper.encode("utf-8"),
        value.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def digest_code(settings: CollaborationSettings, code: str) -> str:
    return _secret_digest(settings, f"admin-code:{code}")


def digest_session_token(settings: CollaborationSettings, token: str) -> str:
    return _secret_digest(settings, f"admin-session:{token}")


def digest_csrf_token(settings: CollaborationSettings, token: str) -> str:
    return _secret_digest(settings, f"admin-csrf:{token}")


def admin_auth_required() -> CollaborationError:
    return CollaborationError(
        401,
        "ADMIN_AUTH_REQUIRED",
        "需要有效的管理员会话",
        headers={"WWW-Authenticate": "Cookie"},
    )


def admin_login_failed() -> CollaborationError:
    return CollaborationError(401, "ADMIN_LOGIN_FAILED", "管理员账号或密码不正确")


def admin_login_locked(retry_after: int) -> CollaborationError:
    return CollaborationError(
        429,
        "ADMIN_LOGIN_LOCKED",
        "登录尝试过多，请稍后再试",
        details={"retry_after_seconds": max(1, int(retry_after))},
        headers={"Retry-After": str(max(1, int(retry_after)))},
    )


def admin_csrf_invalid() -> CollaborationError:
    return CollaborationError(403, "ADMIN_CSRF_INVALID", "请求校验失败，请刷新管理页")


def admin_forbidden(message: str = "管理员无权执行该操作") -> CollaborationError:
    return CollaborationError(403, "ADMIN_FORBIDDEN", message)


def admin_validation(message: str) -> CollaborationError:
    return CollaborationError(422, "ADMIN_VALIDATION", message)


def admin_code_invalid() -> CollaborationError:
    # Deliberately does not distinguish unknown, expired, consumed or
    # school/teacher-mismatched codes.
    return CollaborationError(400, "REDEEM_CODE_INVALID", "兑换码无效或已使用")


def admin_teacher_inactive() -> CollaborationError:
    return CollaborationError(409, "TEACHER_INACTIVE", "该教师已停用，不能签发兑换码")


@dataclass(frozen=True)
class AdminPrincipal:
    admin_id: UUID
    username: str
    session_id: UUID
    csrf_hash: str


@dataclass(frozen=True)
class AdminLoginResult:
    principal: AdminPrincipal
    session_token: str
    csrf_token: str
    expires_at: datetime


@dataclass(frozen=True)
class RedeemResult:
    token: str
    token_id: UUID
    teacher_id: UUID
    teacher_name: str
    school_id: UUID
    school_name: str
    purpose: str
    membership: MembershipOut | None


@dataclass(frozen=True)
class IssuedCode:
    code: str
    code_id: UUID
    purpose: str
    teacher_id: UUID
    teacher_name: str
    school_id: UUID
    expires_at: datetime


def bootstrap_admin(
    session: Session, username: str, password: str
) -> AdminUser:
    """Create the first global administrator.  The plaintext is never stored."""
    name = validate_admin_username(username)
    password_hash = hash_password(password)
    with session.begin():
        existing = session.scalars(
            select(AdminUser).where(AdminUser.username == name)
        ).one_or_none()
        if existing is not None:
            raise ValueError("管理员用户名已存在")
        row = AdminUser(
            id=uuid4(),
            username=name,
            password_hash=password_hash,
            active=True,
            failed_attempts=0,
        )
        session.add(row)
        session.flush()
        return row


def login_admin(
    session: Session,
    settings: CollaborationSettings,
    username: str,
    password: str,
) -> AdminLoginResult:
    name = username.strip() if isinstance(username, str) else ""
    failure: str | None = None
    retry_after = 0
    result: AdminLoginResult | None = None
    with session.begin():
        # Lock the same account row before reading/updating the failure count.
        # Concurrent password attempts then serialize, so no increment is lost.
        user = session.scalars(
            select(AdminUser)
            .where(AdminUser.username == name)
            .with_for_update()
        ).one_or_none()
        now = _utcnow()
        encoded = user.password_hash if user is not None else _DUMMY_HASH
        password_ok = verify_password(password, encoded)
        locked_until = _as_utc(user.locked_until) if user is not None else None
        if user is not None and locked_until is not None and locked_until > now:
            retry_after = max(1, int((locked_until - now).total_seconds()))
            failure = "locked"
        elif user is None or not user.active or not password_ok:
            if user is not None:
                if locked_until is not None and locked_until <= now:
                    user.failed_attempts = 0
                    user.locked_until = None
                user.failed_attempts = int(user.failed_attempts or 0) + 1
                if user.failed_attempts >= _max_failed_attempts():
                    user.failed_attempts = 0
                    user.locked_until = now + timedelta(seconds=_lock_seconds())
            failure = "invalid"
        else:
            user.failed_attempts = 0
            user.locked_until = None
            session_token = secrets.token_urlsafe(32)
            csrf_token = secrets.token_urlsafe(32)
            expires_at = now + timedelta(seconds=_session_ttl_seconds())
            row = AdminSession(
                id=uuid4(),
                admin_id=user.id,
                token_hash=digest_session_token(settings, session_token),
                csrf_hash=digest_csrf_token(settings, csrf_token),
                created_at=now,
                expires_at=expires_at,
            )
            session.add(row)
            session.flush()
            result = AdminLoginResult(
                principal=AdminPrincipal(
                    admin_id=user.id,
                    username=user.username,
                    session_id=row.id,
                    csrf_hash=row.csrf_hash,
                ),
                session_token=session_token,
                csrf_token=csrf_token,
                expires_at=expires_at,
            )
    if failure == "locked":
        raise admin_login_locked(retry_after)
    if failure == "invalid" or result is None:
        raise admin_login_failed()
    return result


def authenticate_admin(
    session: Session, settings: CollaborationSettings, token: str
) -> AdminPrincipal:
    if not token or not isinstance(token, str):
        raise admin_auth_required()
    digest = digest_session_token(settings, token)
    row = session.execute(
        select(AdminSession, AdminUser)
        .join(AdminUser, AdminSession.admin_id == AdminUser.id)
        .where(
            AdminSession.token_hash == digest,
            AdminSession.revoked_at.is_(None),
        )
    ).one_or_none()
    if row is None:
        session.rollback()
        raise admin_auth_required()
    session_row, user = row
    expires = _as_utc(session_row.expires_at)
    now = _utcnow()
    if expires is None or expires <= now or not user.active:
        session.rollback()
        raise admin_auth_required()
    principal = AdminPrincipal(
        admin_id=user.id,
        username=user.username,
        session_id=session_row.id,
        csrf_hash=session_row.csrf_hash,
    )
    session.rollback()
    return principal


def verify_csrf(
    settings: CollaborationSettings, principal: AdminPrincipal, token: str
) -> None:
    if not token or not isinstance(token, str):
        raise admin_csrf_invalid()
    supplied = digest_csrf_token(settings, token)
    if not hmac.compare_digest(supplied, principal.csrf_hash):
        raise admin_csrf_invalid()


def revoke_admin_session(session: Session, principal: AdminPrincipal) -> None:
    with session.begin():
        row = session.get(AdminSession, principal.session_id)
        if row is None:
            return
        row.revoked_at = _utcnow()


def list_schools(session: Session) -> list[School]:
    return list(
        session.scalars(select(School).order_by(School.name, School.id)).all()
    )


def list_teachers(session: Session, school_id: UUID) -> list[Teacher]:
    return list(
        session.scalars(
            select(Teacher)
            .where(Teacher.school_id == school_id)
            .order_by(Teacher.active.desc(), Teacher.display_name, Teacher.id)
        ).all()
    )


@dataclass(frozen=True)
class AdminTerm:
    term_id: UUID
    school_id: UUID
    name: str
    start_date: date
    end_date: date


def _term_view(row: CollaborationTerm) -> AdminTerm:
    return AdminTerm(
        term_id=row.id,
        school_id=row.school_id,
        name=row.name,
        start_date=row.start_date,
        end_date=row.end_date,
    )


def term_name_conflict(current_name: str) -> CollaborationError:
    return CollaborationError(
        409,
        "TERM_NAME_CONFLICT",
        "学期名称已被其他窗口修改，请刷新后重试",
        details={"current_name": current_name},
    )


def _valid_term_name(value: object) -> str:
    if not isinstance(value, str):
        raise admin_validation("学期名称必须是字符串")
    name = value.strip()
    if not (1 <= len(name) <= 80) or "\x00" in name:
        raise admin_validation("学期名称长度必须为 1–80 个字符")
    return name


def list_terms(session: Session, school_id: UUID) -> list[AdminTerm]:
    school = session.get(School, school_id)
    if school is None:
        raise admin_validation("所选的园所不存在")
    rows = session.scalars(
        select(CollaborationTerm)
        .where(CollaborationTerm.school_id == school_id)
        .order_by(CollaborationTerm.start_date, CollaborationTerm.id)
    ).all()
    return [_term_view(row) for row in rows]


def update_term_name(
    session: Session,
    principal: AdminPrincipal,
    *,
    school_id: UUID,
    term_id: UUID,
    expected_name: object,
    new_name: object,
) -> AdminTerm:
    """Rename one existing term without touching its ID or dates.

    ``expected_name`` is the old-name baseline.  A retry after a successful
    rename is idempotent when the current name already equals ``new_name``; a
    different concurrent name returns a 409 with the current value.
    """
    if not isinstance(expected_name, str):
        raise admin_validation("旧名称必须是字符串")
    expected = expected_name
    if not (1 <= len(expected.strip()) <= 80) or "\x00" in expected:
        raise admin_validation("旧名称长度必须为 1–80 个字符")
    new = _valid_term_name(new_name)
    with session.begin():
        admin = session.get(AdminUser, principal.admin_id)
        if admin is None or not admin.active:
            raise admin_auth_required()
        term = session.get(
            CollaborationTerm, term_id, with_for_update=True
        )
        if term is None or term.school_id != school_id:
            raise CollaborationError(404, "TERM_NOT_FOUND", "没有找到该学期")
        current = term.name
        if current == expected:
            if new != current:
                term.name = new
                session.flush()
            return _term_view(term)
        if current == new:
            # Same request retried after the first response was lost.
            return _term_view(term)
        raise term_name_conflict(current)


def issue_code(
    session: Session,
    settings: CollaborationSettings,
    principal: AdminPrincipal,
    *,
    school_id: UUID,
    teacher_id: UUID,
    purpose: str,
) -> IssuedCode:
    if purpose not in ("join", "recovery"):
        raise admin_validation("兑换码类型必须是首次加入或换机恢复")
    code = secrets.token_urlsafe(32)
    code_hash = digest_code(settings, code)
    now = _utcnow()
    expires_at = now + timedelta(seconds=_code_ttl_seconds())
    with session.begin():
        admin = session.get(AdminUser, principal.admin_id)
        if admin is None or not admin.active:
            raise admin_auth_required()
        school = session.get(School, school_id)
        teacher = session.get(Teacher, teacher_id)
        if school is None or teacher is None or teacher.school_id != school.id:
            raise admin_validation("选择的教师不属于所选园所")
        if not teacher.active:
            raise admin_teacher_inactive()
        row = AdminCode(
            id=uuid4(),
            code_hash=code_hash,
            purpose=purpose,
            teacher_id=teacher.id,
            school_id=school.id,
            created_by_admin_id=admin.id,
            created_at=now,
            expires_at=expires_at,
        )
        session.add(row)
        session.flush()
        return IssuedCode(
            code=code,
            code_id=row.id,
            purpose=purpose,
            teacher_id=teacher.id,
            teacher_name=teacher.display_name,
            school_id=school.id,
            expires_at=expires_at,
        )


def redeem_code(
    session: Session, settings: CollaborationSettings, code: str
) -> RedeemResult:
    if (
        not isinstance(code, str)
        or not code
        or len(code) > _CODE_MAX_CHARS
    ):
        raise admin_code_invalid()
    code_hash = digest_code(settings, code)
    with session.begin():
        row = session.scalars(
            select(AdminCode)
            .where(AdminCode.code_hash == code_hash)
            .with_for_update()
        ).one_or_none()
        # Read the clock only after the row lock is held: a request that waited
        # behind another redemption must not use its pre-wait timestamp.
        now = _utcnow()
        if row is None or row.used_at is not None:
            raise admin_code_invalid()
        expires_at = _as_utc(row.expires_at)
        if expires_at is None or expires_at <= now:
            raise admin_code_invalid()
        teacher = session.get(Teacher, row.teacher_id)
        school = session.get(School, row.school_id)
        if (
            teacher is None
            or school is None
            or not teacher.active
            or teacher.school_id != school.id
        ):
            raise admin_code_invalid()

        membership: MembershipOut | None = None
        if row.purpose == "recovery":
            current = session.scalars(
                select(TeacherClassMembership).where(
                    TeacherClassMembership.teacher_id == teacher.id
                )
            ).one_or_none()
            if current is not None and current.school_id == school.id:
                classroom = session.get(Classroom, current.class_id)
                if classroom is not None and classroom.school_id == school.id:
                    membership = MembershipOut(
                        teacher_id=teacher.id,
                        school_id=school.id,
                        class_id=classroom.id,
                        class_name=effective_class_name_now(
                            session, classroom.id, classroom.display_name
                        ),
                        selected_at=current.selected_at,
                    )

        token, token_hash = issue_bearer_token(settings.token_pepper)
        token_row = TeacherToken(
            id=uuid4(),
            teacher_id=teacher.id,
            token_hash=token_hash,
            created_at=now,
            expires_at=now + timedelta(days=_teacher_token_ttl_days()),
        )
        session.add(token_row)
        row.used_at = now
        session.flush()
        return RedeemResult(
            token=token,
            token_id=token_row.id,
            teacher_id=teacher.id,
            teacher_name=teacher.display_name,
            school_id=school.id,
            school_name=school.name,
            purpose=row.purpose,
            membership=membership,
        )
