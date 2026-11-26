"""Administrator authentication and one-time teacher-code transactions.

The administrator is deliberately independent from teacher bearer identities.
Passwords are stored with scrypt, session and CSRF tokens are stored only as
keyed digests, and one-time codes are stored only as keyed digests.  Code
redemption is a single transaction: the code row is locked, the teacher and
school are rechecked, the code is consumed and the teacher bearer token is
issued, then everything commits or rolls back together.

The service also owns the small administrator provisioning transactions for
the admin page: creating schools, registered classes (with their grade and
class number in the same transaction, because the shared weekly plan and
promotion flows refuse an unregistered class), named teachers and school
terms.  Every create is idempotent on its visible identity so a retry after
a lost response never mints a duplicate row.
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

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from .admin_models import AdminCode, AdminSession, AdminUser
from .config import CollaborationSettings
from .class_promotion_models import (
    GRADES,
    ClassPromotionHistory,
    ClassPromotionOperation,
    ClassPromotionState,
    CollaborationTerm,
    effective_class_name_now,
    make_class_name,
)
from .feedback_models import FeedbackSubmission  # noqa: F401 (history tables)
from .weekly_plan_models import (
    WeeklyPlanConfirmation,
    WeeklyPlanOperation,
    WeeklyPlanWeek,
)
from .errors import CollaborationError
from .models import (
    Classroom,
    CollaborationOperation,
    School,
    Teacher,
    TeacherClassMembership,
    TeacherGameConfig,
    TeacherToken,
)
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
# MySQL error 1213 (ER_LOCK_DEADLOCK): InnoDB already rolled the whole
# transaction back and asks the client to restart it.  A create request is
# replay-safe through its explicit entity id, so a bounded retry of the
# SAME transaction is the controlled resolution; any other database error
# propagates unchanged.
_MYSQL_DEADLOCK_ERROR = 1213
_CREATE_DEADLOCK_ATTEMPTS = 3


def _is_innodb_deadlock(exc: BaseException) -> bool:
    origin = getattr(exc, "orig", None)
    args = getattr(origin, "args", None)
    return bool(args) and args[0] == _MYSQL_DEADLOCK_ERROR


def _run_create_transaction(transaction):
    """Run one create transaction, retrying an InnoDB deadlock a bounded
    number of times.

    A 1213 deadlock is reported after the server rolled the transaction
    back, so replaying the same create request (same entity id, same
    input) is safe by construction: the replay then observes the
    concurrent winner through the normal read path.  Unrelated
    OperationalErrors, every other database error and a deadlock that
    persists after the last attempt all propagate unchanged — nothing is
    converted or swallowed here.
    """
    for attempt in range(1, _CREATE_DEADLOCK_ATTEMPTS + 1):
        try:
            return transaction()
        except OperationalError as exc:
            if (
                not _is_innodb_deadlock(exc)
                or attempt == _CREATE_DEADLOCK_ATTEMPTS
            ):
                raise


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
        session.scalars(
            select(School)
            .where(School.deleted_at.is_(None))
            .order_by(School.name, School.id)
        ).all()
    )


def school_name_conflict(current_name: str) -> CollaborationError:
    return CollaborationError(
        409,
        "SCHOOL_NAME_CONFLICT",
        "园所名称已被其他窗口修改，请刷新后重试",
        details={"current_name": current_name},
    )


def _valid_school_name(value: object) -> str:
    if not isinstance(value, str):
        raise admin_validation("园所名称必须是字符串")
    name = value.strip()
    if not (1 <= len(name) <= 120) or "\x00" in name:
        raise admin_validation("园所名称长度必须为 1–120 个字符")
    return name


def update_school_name(
    session: Session,
    principal: AdminPrincipal,
    *,
    school_id: UUID,
    expected_name: object,
    new_name: object,
) -> School:
    """Rename one existing school without touching any stable ID.

    ``expected_name`` is the old-name baseline.  A retry after a successful
    rename is idempotent when the current name already equals ``new_name``; a
    different concurrent name returns a 409 with the current value.
    """
    if not isinstance(expected_name, str):
        raise admin_validation("旧名称必须是字符串")
    expected = expected_name
    if not (1 <= len(expected.strip()) <= 120) or "\x00" in expected:
        raise admin_validation("旧名称长度必须为 1–120 个字符")
    new = _valid_school_name(new_name)
    with session.begin():
        admin = session.get(AdminUser, principal.admin_id)
        if admin is None or not admin.active:
            raise admin_auth_required()
        school = session.get(School, school_id, with_for_update=True)
        if school is None or school.deleted_at is not None:
            raise CollaborationError(
                404, "SCHOOL_NOT_FOUND", "没有找到该园所"
            )
        current = school.name
        if current == expected:
            if new != current:
                school.name = new
                session.flush()
            return school
        if current == new:
            # Same request retried after the first response was lost.
            return school
        raise school_name_conflict(current)


def _committed_school_or_conflict(row: School, name: str) -> School:
    """Verify a committed same-id school against this request's input.

    The same check serves the pre-read hit and the insert-conflict path, so
    a replay resolved through either route behaves identically.
    """
    if row.name != name:
        raise CollaborationError(
            409,
            "SCHOOL_CREATE_CONFLICT",
            "该园所 ID 已绑定其他名称，请重新发起新增",
        )
    return row


def create_school(
    session: Session,
    principal: AdminPrincipal,
    *,
    school_id: UUID,
    name: object,
) -> tuple[School, bool]:
    """Create a school from an explicit client-supplied entity id.

    ``school_id`` identifies the create request itself: replaying the same
    id with the same name returns the committed school with
    ``created=False``, so a retry after a lost response never mints a
    duplicate row.  A second, independently generated request id is a
    deliberate second school even when the display name matches, which
    mirrors the offline provisioning tool and never silently merges two
    distinct requests.  No other school, class, teacher or code row is
    touched.

    Two truly concurrent creates with the same id may both pass their
    first read; the committed primary key then makes exactly one insert
    win.  The loser never surfaces a driver error: an insert conflict is
    re-read and resolved through the same check (the same input returns a
    normal replay with ``created=False``, a different input is a
    controlled 409), and a pre-commit InnoDB deadlock — the server has
    already rolled that transaction back — is retried as the same request
    a bounded number of times.
    """
    clean = _valid_school_name(name)

    def transaction() -> tuple[School, bool]:
        with session.begin():
            admin = session.get(AdminUser, principal.admin_id)
            if admin is None or not admin.active:
                raise admin_auth_required()
            existing = session.get(School, school_id)
            if existing is not None:
                return (
                    _committed_school_or_conflict(existing, clean),
                    False,
                )
            row = School(id=school_id, name=clean)
            session.add(row)
            session.flush()
            return row, True

    try:
        return _run_create_transaction(transaction)
    except IntegrityError as original:
        # A concurrent create with the same entity id committed between
        # this request's read and its insert.  The failed transaction is
        # already rolled back; resolve against the committed row.
        row = session.get(School, school_id)
        if row is None:
            raise original from None
        return _committed_school_or_conflict(row, clean), False


def list_teachers(session: Session, school_id: UUID) -> list[Teacher]:
    return list(
        session.scalars(
            select(Teacher)
            .join(School, School.id == Teacher.school_id)
            .where(
                Teacher.school_id == school_id,
                Teacher.deleted_at.is_(None),
                School.deleted_at.is_(None),
            )
            .order_by(Teacher.active.desc(), Teacher.display_name, Teacher.id)
        ).all()
    )


def _valid_teacher_name(value: object) -> str:
    if not isinstance(value, str):
        raise admin_validation("教师名称必须是字符串")
    name = value.strip()
    if not (1 <= len(name) <= 120) or "\x00" in name:
        raise admin_validation("教师名称长度必须为 1–120 个字符")
    return name


def _committed_teacher_or_conflict(
    row: Teacher, *, school_id: UUID, name: str
) -> Teacher:
    """Verify a committed same-id teacher against this request's input."""
    if row.school_id != school_id or row.display_name != name:
        raise CollaborationError(
            409,
            "TEACHER_CREATE_CONFLICT",
            "该教师 ID 已绑定其他园所或名称，请重新发起新增",
        )
    return row


def create_teacher(
    session: Session,
    principal: AdminPrincipal,
    *,
    school_id: UUID,
    teacher_id: UUID,
    name: object,
) -> tuple[Teacher, bool]:
    """Create one named teacher from an explicit client-supplied entity id.

    ``teacher_id`` identifies the create request itself: replaying the same
    id with the same school and name returns the committed teacher with
    ``created=False``, so a retry after a lost response never mints a
    duplicate row.  A different, independently generated id is a
    deliberate second teacher even when the display name matches — the
    offline provisioning tool also allows same-name teachers with distinct
    ids — and the returned rows keep their own ``active`` flag so the
    issue-code list can tell them apart by stable id.  The school row lock
    serializes concurrent creates within one school; a same-id create
    racing in another school is resolved against the committed row, never
    with a driver error, and a pre-commit InnoDB deadlock is retried as
    the same request a bounded number of times.  Other teachers,
    memberships and codes are never touched.
    """
    clean = _valid_teacher_name(name)

    def transaction() -> tuple[Teacher, bool]:
        with session.begin():
            admin = session.get(AdminUser, principal.admin_id)
            if admin is None or not admin.active:
                raise admin_auth_required()
            school = session.get(School, school_id, with_for_update=True)
            if school is None or school.deleted_at is not None:
                raise CollaborationError(
                    404, "SCHOOL_NOT_FOUND", "没有找到该园所"
                )
            existing = session.get(Teacher, teacher_id)
            if existing is not None:
                return (
                    _committed_teacher_or_conflict(
                        existing, school_id=school.id, name=clean
                    ),
                    False,
                )
            row = Teacher(
                id=teacher_id,
                school_id=school.id,
                display_name=clean,
                active=True,
            )
            session.add(row)
            session.flush()
            return row, True

    try:
        return _run_create_transaction(transaction)
    except IntegrityError as original:
        # A concurrent create with the same teacher id committed first
        # (possibly in another school).  Resolve against the committed row.
        row = session.get(Teacher, teacher_id)
        if row is None:
            raise original from None
        return (
            _committed_teacher_or_conflict(
                row, school_id=school_id, name=clean
            ),
            False,
        )


def update_teacher_name(
    session: Session,
    principal: AdminPrincipal,
    *,
    school_id: UUID,
    teacher_id: UUID,
    expected_name: object,
    new_name: object,
) -> Teacher:
    """Update only a teacher display name inside one school.

    ``expected_name`` is the old-name baseline, mirroring the school/class
    rename semantics: a lost-response retry is idempotent when the current
    name already equals ``new_name``, while a different concurrent name
    returns a 409 with the current value.  Teacher ID, school binding,
    active flag, memberships and existing codes are never touched.
    """
    if not isinstance(expected_name, str):
        raise admin_validation("旧名称必须是字符串")
    expected = expected_name
    if not (1 <= len(expected.strip()) <= 120) or "\x00" in expected:
        raise admin_validation("旧名称长度必须为 1–120 个字符")
    new = _valid_teacher_name(new_name)
    with session.begin():
        admin = session.get(AdminUser, principal.admin_id)
        if admin is None or not admin.active:
            raise admin_auth_required()
        teacher = session.get(Teacher, teacher_id, with_for_update=True)
        if (
            teacher is None
            or teacher.school_id != school_id
            or teacher.deleted_at is not None
        ):
            raise CollaborationError(404, "TEACHER_NOT_FOUND", "没有找到该教师")
        current = teacher.display_name
        if current == expected:
            if new != current:
                teacher.display_name = new
                session.flush()
            return teacher
        if current == new:
            # Same request retried after the first response was lost.
            return teacher
        raise CollaborationError(
            409,
            "TEACHER_NAME_CONFLICT",
            "教师名称已被其他窗口修改，请刷新后重试",
            details={"current_name": current},
        )


@dataclass(frozen=True)
class AdminTerm:
    term_id: UUID
    school_id: UUID
    name: str
    start_date: date
    end_date: date


@dataclass(frozen=True)
class AdminClass:
    class_id: UUID
    school_id: UUID
    name: str


def _class_view(session: Session, row: Classroom) -> AdminClass:
    if row.display_name_override is not None and row.display_name_override.strip():
        name = row.display_name_override
    else:
        name = row.display_name
    return AdminClass(
        class_id=row.id,
        school_id=row.school_id,
        name=name,
    )

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
    if school is None or school.deleted_at is not None:
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


def _valid_class_name(value: object) -> str:
    if not isinstance(value, str):
        raise admin_validation("班级显示名称必须是字符串")
    name = value.strip()
    if not (1 <= len(name) <= 120) or "\x00" in name:
        raise admin_validation("班级显示名称长度必须为 1–120 个字符")
    return name


def list_classes(session: Session, school_id: UUID) -> list[AdminClass]:
    if session.get(School, school_id) is None:
        raise admin_validation("所选的园所不存在")
    rows = session.scalars(
        select(Classroom)
        .join(School, School.id == Classroom.school_id)
        .where(
            Classroom.school_id == school_id,
            Classroom.deleted_at.is_(None),
            School.deleted_at.is_(None),
        )
        .order_by(Classroom.display_name, Classroom.id)
    ).all()
    return [_class_view(session, row) for row in rows]

def update_class_name(
    session: Session,
    principal: AdminPrincipal,
    *,
    school_id: UUID,
    class_id: UUID,
    expected_name: object,
    new_name: object,
) -> AdminClass:
    """Update only a class display name; stable IDs and promotion stay."""
    if not isinstance(expected_name, str):
        raise admin_validation("旧名称必须是字符串")
    expected = expected_name
    if not (1 <= len(expected.strip()) <= 120) or "\x00" in expected:
        raise admin_validation("旧名称长度必须为 1–120 个字符")
    new = _valid_class_name(new_name)
    with session.begin():
        admin = session.get(AdminUser, principal.admin_id)
        if admin is None or not admin.active:
            raise admin_auth_required()
        classroom = session.get(Classroom, class_id, with_for_update=True)
        if (
            classroom is None
            or classroom.school_id != school_id
            or classroom.deleted_at is not None
        ):
            raise CollaborationError(
                404, "CLASS_NOT_FOUND", "没有找到该班级"
            )
        current = (
            classroom.display_name_override
            if classroom.display_name_override is not None
            and classroom.display_name_override.strip()
            else classroom.display_name
        )
        if current == expected:
            if new != current:
                classroom.display_name_override = new
                session.flush()
            return _class_view(session, classroom)
        if current == new:
            return _class_view(session, classroom)
        raise CollaborationError(
            409,
            "CLASS_NAME_CONFLICT",
            "班级显示名称已被其他窗口修改，请刷新后重试",
            details={"current_name": current},
        )


@dataclass(frozen=True)
class AdminClassCreate:
    view: AdminClass
    grade: str
    class_number: int
    created: bool


def _valid_class_registration(
    grade: object, class_number: object
) -> tuple[str, int]:
    if grade not in GRADES:
        raise admin_validation("年级只能是小班、中班或大班")
    if (
        not isinstance(class_number, int)
        or isinstance(class_number, bool)
        or not (1 <= class_number <= 99)
    ):
        raise admin_validation("班号必须是 1–99 的整数")
    return grade, class_number


def _committed_class_or_conflict(
    session: Session,
    row: Classroom,
    *,
    school_id: UUID,
    grade: str,
    class_number: int,
) -> tuple[Classroom, ClassPromotionState]:
    """Verify a committed same-id class against this request's input."""
    state = session.get(ClassPromotionState, row.id)
    if (
        row.school_id != school_id
        or state is None
        or state.base_grade != grade
        or state.class_number != class_number
    ):
        raise CollaborationError(
            409,
            "CLASS_CREATE_CONFLICT",
            "该班级 ID 已绑定其他园所、年级或班号，请重新发起新增",
        )
    return row, state


def create_class(
    session: Session,
    principal: AdminPrincipal,
    *,
    school_id: UUID,
    class_id: UUID,
    grade: object,
    class_number: object,
) -> AdminClassCreate:
    """Create one class with its grade and class number in one transaction.

    ``class_id`` identifies the create request itself: replaying the same id
    with the same school, grade and class number returns the committed
    class with ``created=False``, so a retry after a lost response never
    mints a duplicate row, and a concurrent replay of one request is
    serialized by the committed primary key.  A new, independently
    generated id always creates a new class — including a replacement
    cohort with the same grade and number after promotion moved the
    previous cohort up — because the class identity is the request id, and
    an old class is never silently returned or reported as a conflict for a
    fresh request.

    The same-transaction registration is required, not optional: the shared
    weekly-plan context and the promotion read both refuse a class without
    a ``ClassPromotionState`` row, so leaving a new class unregistered would
    hand teachers a class that lists and pairs but can never share a weekly
    plan.  The display name is derived with the existing ``make_class_name``
    standard, so the admin list (display name), the teacher list (registered
    name) and the promotion view all show the same name.  Existing classes,
    their semester/promotion history, game configurations and old pairings
    are never touched.  The school row lock serializes concurrent creates
    within one school; a same-id create racing in another school is
    resolved against the committed row, never with a driver error, and a
    pre-commit InnoDB deadlock is retried as the same request a bounded
    number of times.
    """
    clean_grade, clean_number = _valid_class_registration(grade, class_number)

    def transaction() -> AdminClassCreate:
        with session.begin():
            admin = session.get(AdminUser, principal.admin_id)
            if admin is None or not admin.active:
                raise admin_auth_required()
            school = session.get(School, school_id, with_for_update=True)
            if school is None or school.deleted_at is not None:
                raise CollaborationError(
                    404, "SCHOOL_NOT_FOUND", "没有找到该园所"
                )
            existing = session.get(Classroom, class_id)
            if existing is not None:
                _row, state = _committed_class_or_conflict(
                    session,
                    existing,
                    school_id=school.id,
                    grade=clean_grade,
                    class_number=clean_number,
                )
                return AdminClassCreate(
                    view=_class_view(session, existing),
                    grade=state.base_grade,
                    class_number=state.class_number,
                    created=False,
                )
            classroom = Classroom(
                id=class_id,
                school_id=school.id,
                display_name=make_class_name(clean_grade, clean_number),
            )
            session.add(classroom)
            # The registration row references (class_id, school_id) in
            # ``classes`` through a composite foreign key, and MySQL 8.4
            # enforces it at INSERT time.  The two mappers share no ORM
            # relationship, so one combined flush may emit the registration
            # INSERT first; the parent classroom row is therefore flushed
            # into this transaction before the registration row is added.
            # Both rows still commit or roll back together in this single
            # transaction.
            session.flush()
            state = ClassPromotionState(
                class_id=class_id,
                school_id=school.id,
                class_number=clean_number,
                base_grade=clean_grade,
                version=1,
            )
            session.add(state)
            session.flush()
            return AdminClassCreate(
                view=_class_view(session, classroom),
                grade=clean_grade,
                class_number=clean_number,
                created=True,
            )

    try:
        return _run_create_transaction(transaction)
    except IntegrityError as original:
        # A concurrent create with the same class id committed first
        # (possibly in another school).  Resolve against the committed row.
        row = session.get(Classroom, class_id)
        if row is None:
            raise original from None
        _row, state = _committed_class_or_conflict(
            session,
            row,
            school_id=school_id,
            grade=clean_grade,
            class_number=clean_number,
        )
        return AdminClassCreate(
            view=_class_view(session, row),
            grade=state.base_grade,
            class_number=state.class_number,
            created=False,
        )


def _valid_term_dates(
    start_date: object, end_date: object
) -> tuple[date, date]:
    if not isinstance(start_date, date) or isinstance(start_date, datetime):
        raise admin_validation("学期开始日期必须是 YYYY-MM-DD")
    if not isinstance(end_date, date) or isinstance(end_date, datetime):
        raise admin_validation("学期结束日期必须是 YYYY-MM-DD")
    if start_date > end_date:
        raise admin_validation("学期开始日期不能晚于结束日期")
    return start_date, end_date


def _committed_term_or_conflict(
    row: CollaborationTerm,
    *,
    school_id: UUID,
    name: str,
    start_date: date,
    end_date: date,
) -> CollaborationTerm:
    """Verify a committed same-id term against this request's input."""
    if (
        row.school_id != school_id
        or row.name != name
        or row.start_date != start_date
        or row.end_date != end_date
    ):
        raise CollaborationError(
            409,
            "TERM_CREATE_CONFLICT",
            "该学期 ID 已绑定其他园所、名称或日期，请重新发起新增",
        )
    return row


def create_term(
    session: Session,
    principal: AdminPrincipal,
    *,
    school_id: UUID,
    term_id: UUID,
    name: object,
    start_date: object,
    end_date: object,
) -> tuple[AdminTerm, bool]:
    """Create one school term from an explicit id, name and dates.

    ``term_id`` identifies the create request itself: replaying the same id
    with the same school, name and dates returns the committed term with
    ``created=False``, so a retry after a lost response never mints a
    duplicate row.  The dates are never guessed and no batch of terms is
    ever derived: the administrator types the name, start and end dates,
    and the existing term rules apply unchanged (school scoping, 1–80
    character name, ordered dates, and no date overlap with another term of
    the same school).  Any other date overlap — including a different id
    with identical name and dates — is a 409 that names the conflicting
    term, never a silent merge.  Existing terms and their promotion history
    are never modified.  The school row lock serializes concurrent creates
    within one school; a same-id create racing in another school is
    resolved against the committed row, never with a driver error, and a
    pre-commit InnoDB deadlock is retried as the same request a bounded
    number of times.
    """
    clean = _valid_term_name(name)
    start, end = _valid_term_dates(start_date, end_date)

    def transaction() -> tuple[AdminTerm, bool]:
        with session.begin():
            admin = session.get(AdminUser, principal.admin_id)
            if admin is None or not admin.active:
                raise admin_auth_required()
            school = session.get(School, school_id, with_for_update=True)
            if school is None or school.deleted_at is not None:
                raise CollaborationError(
                    404, "SCHOOL_NOT_FOUND", "没有找到该园所"
                )
            existing = session.get(CollaborationTerm, term_id)
            if existing is not None:
                return (
                    _term_view(
                        _committed_term_or_conflict(
                            existing,
                            school_id=school.id,
                            name=clean,
                            start_date=start,
                            end_date=end,
                        )
                    ),
                    False,
                )
            overlaps = session.scalars(
                select(CollaborationTerm)
                .where(
                    CollaborationTerm.school_id == school.id,
                    CollaborationTerm.start_date <= end,
                    CollaborationTerm.end_date >= start,
                )
                .order_by(CollaborationTerm.start_date, CollaborationTerm.id)
                .with_for_update()
            ).all()
            if overlaps:
                conflict = overlaps[0]
                raise CollaborationError(
                    409,
                    "TERM_OVERLAP",
                    "学期日期与现有学期重叠，请调整日期",
                    details={
                        "conflict_name": conflict.name,
                        "conflict_start_date": conflict.start_date.isoformat(),
                        "conflict_end_date": conflict.end_date.isoformat(),
                    },
                )
            row = CollaborationTerm(
                id=term_id,
                school_id=school.id,
                name=clean,
                start_date=start,
                end_date=end,
            )
            session.add(row)
            session.flush()
            return _term_view(row), True

    try:
        return _run_create_transaction(transaction)
    except IntegrityError as original:
        # A concurrent create with the same term id committed first
        # (possibly in another school).  Resolve against the committed row.
        row = session.get(CollaborationTerm, term_id)
        if row is None:
            raise original from None
        return (
            _term_view(
                _committed_term_or_conflict(
                    row,
                    school_id=school_id,
                    name=clean,
                    start_date=start,
                    end_date=end,
                )
            ),
            False,
        )

def _count(session: Session, model, *conditions) -> int:
    return int(
        session.scalar(
            select(func.count()).select_from(model).where(*conditions)
        )
        or 0
    )


def school_history_counts(session: Session, school_id: UUID) -> dict[str, int]:
    """Rows that keep a school history and force a deactivation delete."""
    return {
        "teachers": _count(session, Teacher, Teacher.school_id == school_id),
        "classes": _count(session, Classroom, Classroom.school_id == school_id),
        "terms": _count(
            session, CollaborationTerm, CollaborationTerm.school_id == school_id
        ),
        "codes": _count(session, AdminCode, AdminCode.school_id == school_id),
    }


def teacher_history_counts(
    session: Session, teacher_id: UUID
) -> dict[str, int]:
    """Rows that keep a teacher history and force a deactivation delete."""
    return {
        "memberships": _count(
            session,
            TeacherClassMembership,
            TeacherClassMembership.teacher_id == teacher_id,
        ),
        "game_configs": _count(
            session,
            TeacherGameConfig,
            TeacherGameConfig.teacher_id == teacher_id,
        ),
        "codes": _count(session, AdminCode, AdminCode.teacher_id == teacher_id),
        "operations": _count(
            session,
            CollaborationOperation,
            CollaborationOperation.actor_teacher_id == teacher_id,
        )
        + _count(
            session,
            CollaborationOperation,
            CollaborationOperation.source_teacher_id == teacher_id,
        ),
        "promotion_operations": _count(
            session,
            ClassPromotionOperation,
            ClassPromotionOperation.actor_teacher_id == teacher_id,
        ),
        "weekly_plan_operations": _count(
            session,
            WeeklyPlanOperation,
            WeeklyPlanOperation.actor_teacher_id == teacher_id,
        ),
        "weekly_plan_confirmations": _count(
            session,
            WeeklyPlanConfirmation,
            WeeklyPlanConfirmation.confirmed_by == teacher_id,
        ),
    }


def class_history_counts(session: Session, class_id: UUID) -> dict[str, int]:
    """Rows that keep a class history and force a deactivation delete."""
    return {
        "memberships": _count(
            session,
            TeacherClassMembership,
            TeacherClassMembership.class_id == class_id,
        ),
        "game_configs": _count(
            session,
            TeacherGameConfig,
            TeacherGameConfig.class_id == class_id,
        ),
        "operations": _count(
            session,
            CollaborationOperation,
            CollaborationOperation.class_id == class_id,
        ),
        "promotion_history": _count(
            session,
            ClassPromotionHistory,
            ClassPromotionHistory.class_id == class_id,
        ),
        "promotion_operations": _count(
            session,
            ClassPromotionOperation,
            ClassPromotionOperation.class_id == class_id,
        ),
        "weekly_plan_weeks": _count(
            session, WeeklyPlanWeek, WeeklyPlanWeek.class_id == class_id
        ),
        "weekly_plan_confirmations": _count(
            session,
            WeeklyPlanConfirmation,
            WeeklyPlanConfirmation.class_id == class_id,
        ),
        "weekly_plan_operations": _count(
            session,
            WeeklyPlanOperation,
            WeeklyPlanOperation.class_id == class_id,
        ),
    }


def delete_school(
    session: Session,
    principal: AdminPrincipal,
    *,
    school_id: UUID,
    confirm_deactivate: bool = False,
) -> dict:
    """Delete one school, or deactivate and hide it when it has history.

    An empty school (no teachers, classes, terms or codes) is removed
    outright.  With history the row keeps its stable id and every referencing
    row; deleted_at is set, every admin list hides it and no teacher of that
    school can authenticate or redeem again.  The first call without
    confirmation reports 409 SCHOOL_DELETE_BLOCKED with the counts, so the
    admin page can ask for the explicit deactivation confirmation.
    """
    with session.begin():
        admin = session.get(AdminUser, principal.admin_id)
        if admin is None or not admin.active:
            raise admin_auth_required()
        school = session.get(School, school_id, with_for_update=True)
        if school is None or school.deleted_at is not None:
            raise CollaborationError(404, "SCHOOL_NOT_FOUND", "没有找到该园所")
        counts = school_history_counts(session, school_id)
        if sum(counts.values()) == 0:
            session.delete(school)
            session.flush()
            return {"outcome": "deleted", "counts": counts}
        if not confirm_deactivate:
            raise CollaborationError(
                409,
                "SCHOOL_DELETE_BLOCKED",
                "该园所存在教师、班级、学期或兑换码记录：删除将停用并隐藏该园所（其教师不能再登录或使用在线协作）；请确认后重试。",
                details={"counts": counts},
            )
        school.deleted_at = _utcnow()
        session.flush()
        return {"outcome": "deactivated", "counts": counts}


def delete_teacher(
    session: Session,
    principal: AdminPrincipal,
    *,
    school_id: UUID,
    teacher_id: UUID,
    confirm_deactivate: bool = False,
) -> dict:
    """Delete one teacher, or deactivate and hide them when they have history.

    An empty teacher (no memberships, game configs, operations, codes or
    weekly-plan records) is removed outright.  With history the row keeps its
    stable id: active is cleared, every bearer token is revoked and the list
    hides the row, so the teacher can no longer log in, act or receive codes
    while every historical record stays intact.
    """
    with session.begin():
        admin = session.get(AdminUser, principal.admin_id)
        if admin is None or not admin.active:
            raise admin_auth_required()
        teacher = session.get(Teacher, teacher_id, with_for_update=True)
        if (
            teacher is None
            or teacher.school_id != school_id
            or teacher.deleted_at is not None
        ):
            raise CollaborationError(404, "TEACHER_NOT_FOUND", "没有找到该教师")
        counts = teacher_history_counts(session, teacher_id)
        if sum(counts.values()) == 0:
            session.delete(teacher)
            session.flush()
            return {"outcome": "deleted", "counts": counts}
        if not confirm_deactivate:
            raise CollaborationError(
                409,
                "TEACHER_DELETE_BLOCKED",
                "该教师存在关系、操作或兑换码记录：删除将停用并隐藏该教师（不能再登录或使用在线协作）；请确认后重试。",
                details={"counts": counts},
            )
        now = _utcnow()
        teacher.active = False
        teacher.deleted_at = now
        session.execute(
            update(TeacherToken)
            .where(
                TeacherToken.teacher_id == teacher.id,
                TeacherToken.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        session.flush()
        return {"outcome": "deactivated", "counts": counts}


def delete_class(
    session: Session,
    principal: AdminPrincipal,
    *,
    school_id: UUID,
    class_id: UUID,
    confirm_deactivate: bool = False,
) -> dict:
    """Delete one class, or deactivate and hide it when it has history.

    An empty class (no memberships, game configs, operations, promotion or
    weekly-plan records) is removed outright together with its registration
    state row.  With history the row keeps its stable id and every record;
    deleted_at is set, the class disappears from every list and can no longer
    be selected, paired or written to.
    """
    with session.begin():
        admin = session.get(AdminUser, principal.admin_id)
        if admin is None or not admin.active:
            raise admin_auth_required()
        classroom = session.get(Classroom, class_id, with_for_update=True)
        if (
            classroom is None
            or classroom.school_id != school_id
            or classroom.deleted_at is not None
        ):
            raise CollaborationError(404, "CLASS_NOT_FOUND", "没有找到该班级")
        counts = class_history_counts(session, class_id)
        if sum(counts.values()) == 0:
            state = session.get(ClassPromotionState, class_id)
            if state is not None:
                session.delete(state)
            session.delete(classroom)
            session.flush()
            return {"outcome": "deleted", "counts": counts}
        if not confirm_deactivate:
            raise CollaborationError(
                409,
                "CLASS_DELETE_BLOCKED",
                "该班级存在成员、配置或计划记录：删除将停用并隐藏该班级（不能再被选择或写入）；请确认后重试。",
                details={"counts": counts},
            )
        classroom.deleted_at = _utcnow()
        session.flush()
        return {"outcome": "deactivated", "counts": counts}


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
        if (
            school is None
            or school.deleted_at is not None
            or teacher is None
            or teacher.school_id != school.id
        ):
            raise admin_validation("选择的教师不属于所选园所")
        if not teacher.active or teacher.deleted_at is not None:
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
            or teacher.deleted_at is not None
            or school.deleted_at is not None
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
                if (
                    classroom is not None
                    and classroom.school_id == school.id
                    and classroom.deleted_at is None
                ):
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
