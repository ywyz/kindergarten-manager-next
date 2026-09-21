"""Atomic identity write operations shared by routers and CLI.

All functions accept a short-lived read snapshot and perform writes inside a
single transaction with explicit ``FOR UPDATE``/``populate_existing`` reloads.
Password hashing is the caller's responsibility and must happen outside the
write transaction.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import security
from app.config import settings
from app.models import Account, AccountSession, OperationRecord


def utc_now() -> datetime:
    """Return a naive UTC datetime for MySQL DateTime columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass(frozen=True, slots=True)
class AuthSnapshot:
    """Immutable authentication facts collected during dependency resolution."""

    account_id: str
    role: str
    auth_version: int
    session_id: str
    is_active: bool
    password_hash: str


class AuthServiceError(Exception):
    pass


class InvalidCredentials(AuthServiceError):
    pass


class Forbidden(AuthServiceError):
    pass


class VersionConflict(AuthServiceError):
    pass


class AccountNotFound(AuthServiceError):
    pass


class AuthRequired(AuthServiceError):
    pass


def account_to_out(account: Account) -> dict:
    return {
        "id": account.id,
        "username": account.username,
        "display_name": account.display_name,
        "role": account.role,
        "is_active": account.is_active,
        "version": account.version,
    }


def me_response(account: Account) -> dict:
    assignment_status = (
        "not_applicable" if account.role == "admin" else "pending_assignment"
    )
    return {
        "account": account_to_out(account),
        "class_id": None,
        "assignment_status": assignment_status,
        "can_prepare": False,
    }


def record_operation(
    db: Session,
    *,
    operator_id: str | None,
    operator_type: str,
    action: str,
    target_account_id: str,
    account_version_after: int,
) -> OperationRecord:
    record = OperationRecord(
        id=security.generate_id(),
        created_at=utc_now(),
        operator_id=operator_id,
        operator_type=operator_type,
        action=action,
        target_account_id=target_account_id,
        account_version_after=account_version_after,
    )
    db.add(record)
    return record


def _lock_account(db: Session, account_id: str) -> Account | None:
    return db.execute(
        select(Account)
        .where(Account.id == account_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()


def _lock_accounts(db: Session, account_ids: set[str]) -> dict[str, Account]:
    locked: dict[str, Account] = {}
    for aid in sorted(account_ids):
        account = _lock_account(db, aid)
        if account is not None:
            locked[aid] = account
    return locked


def validate_locked_session(db: Session, snapshot: AuthSnapshot) -> AccountSession:
    """Lock the current session for update and verify it is still valid.

    Must be called after locking the owning account to maintain the
    account -> session lock order. Raises AuthRequired on any mismatch.
    """
    session = db.execute(
        select(AccountSession)
        .where(AccountSession.id == snapshot.session_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if session is None:
        raise AuthRequired()
    if (
        session.account_id != snapshot.account_id
        or session.revoked_at is not None
        or session.expires_at <= utc_now()
        or session.auth_version != snapshot.auth_version
    ):
        raise AuthRequired()
    return session


def _apply_password_reset(
    db: Session,
    account: Account,
    new_password_hash: str,
    *,
    operator_id: str | None,
    operator_type: str,
    action: str,
) -> None:
    """Shared atomic password update: hash, versions, sessions, audit."""
    now = utc_now()
    account.password_hash = new_password_hash
    account.auth_version += 1
    account.version += 1
    account.updated_at = now
    revoke_sessions_for_account(db, account.id, now)
    record_operation(
        db,
        operator_id=operator_id,
        operator_type=operator_type,
        action=action,
        target_account_id=account.id,
        account_version_after=account.version,
    )


def revoke_sessions_for_account(db: Session, account_id: str, now: datetime) -> int:
    result = db.execute(
        update(AccountSession)
        .where(
            AccountSession.account_id == account_id,
            AccountSession.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    return result.rowcount


def create_login_session(
    db: Session,
    account_id: str,
    auth_version: int,
    now: datetime,
    expires_at: datetime,
) -> tuple[str, AccountSession]:
    token, token_hash = security.create_session()
    session = AccountSession(
        id=security.generate_id(),
        token_hash=token_hash,
        account_id=account_id,
        auth_version=auth_version,
        created_at=now,
        expires_at=expires_at,
    )
    db.add(session)
    return token, session


def authenticate_for_login(db: Session, username: str, password: str) -> tuple[Account, str]:
    """Authenticate and create a session with read/hash/write separation."""
    account = db.scalar(select(Account).where(Account.username == username))
    if account is None or not account.is_active:
        raise InvalidCredentials()

    snapshot_id = account.id
    snapshot_hash = account.password_hash
    snapshot_auth_version = account.auth_version

    # End the read transaction before the slow password hash.
    db.commit()

    if not security.verify_password(password, snapshot_hash):
        raise InvalidCredentials()

    # Re-lock the account and verify it still matches the immutable snapshot.
    db.begin()
    locked = _lock_account(db, snapshot_id)
    if (
        locked is None
        or not locked.is_active
        or locked.password_hash != snapshot_hash
        or locked.auth_version != snapshot_auth_version
    ):
        raise InvalidCredentials()

    now = utc_now()
    expires_at = now + timedelta(seconds=settings.session_ttl_seconds)
    token, _ = create_login_session(db, locked.id, locked.auth_version, now, expires_at)
    db.commit()
    return locked, token


def update_profile(
    db: Session,
    snapshot: AuthSnapshot,
    display_name: str | None,
    expected_version: int,
) -> Account:
    if not db.in_transaction():
        db.begin()
    locked = _lock_account(db, snapshot.account_id)
    if locked is None or not locked.is_active:
        raise InvalidCredentials()
    if locked.role != snapshot.role:
        raise Forbidden()
    if locked.auth_version != snapshot.auth_version:
        raise InvalidCredentials()
    validate_locked_session(db, snapshot)
    if locked.version != expected_version:
        raise VersionConflict()

    now = utc_now()
    locked.display_name = display_name
    locked.version += 1
    locked.updated_at = now
    record_operation(
        db,
        operator_id=locked.id,
        operator_type="account",
        action="update_profile",
        target_account_id=locked.id,
        account_version_after=locked.version,
    )
    db.commit()
    return locked


def change_own_password(
    db: Session,
    snapshot: AuthSnapshot,
    current_password: str,
    new_password_hash: str,
    expected_version: int,
) -> Account:
    # Verify the current password outside the write transaction.
    if not security.verify_password(current_password, snapshot.password_hash):
        raise InvalidCredentials()

    if not db.in_transaction():
        db.begin()
    locked = _lock_account(db, snapshot.account_id)
    if locked is None or not locked.is_active:
        raise AuthRequired()
    if locked.role != snapshot.role:
        raise Forbidden()
    if (
        locked.auth_version != snapshot.auth_version
        or locked.password_hash != snapshot.password_hash
    ):
        raise AuthRequired()
    validate_locked_session(db, snapshot)
    if locked.version != expected_version:
        raise VersionConflict()

    _apply_password_reset(
        db,
        locked,
        new_password_hash,
        operator_id=locked.id,
        operator_type="account",
        action="change_password",
    )
    db.commit()
    return locked


def admin_reset_password(
    db: Session,
    admin_snapshot: AuthSnapshot,
    target_id: str,
    new_password_hash: str,
    expected_version: int,
) -> Account:
    # Lock accounts in stable ID order to avoid deadlocks.
    if not db.in_transaction():
        db.begin()
    locked = _lock_accounts(db, {admin_snapshot.account_id, target_id})

    admin_locked = locked.get(admin_snapshot.account_id)
    if admin_locked is None or not admin_locked.is_active:
        raise AuthRequired()
    if admin_locked.auth_version != admin_snapshot.auth_version:
        raise AuthRequired()
    if admin_locked.role != "admin":
        raise Forbidden()

    # Lock and validate the admin's own session before checking the target.
    validate_locked_session(db, admin_snapshot)

    target = locked.get(target_id)
    if target is None:
        raise AccountNotFound()
    if target.role != "teacher":
        raise Forbidden()

    if target.version != expected_version:
        raise VersionConflict()

    _apply_password_reset(
        db,
        target,
        new_password_hash,
        operator_id=admin_snapshot.account_id,
        operator_type="account",
        action="admin_password_reset",
    )
    db.commit()
    return target


def revoke_single_session(db: Session, snapshot: AuthSnapshot) -> None:
    """Revoke the session from the snapshot, serializing with account writes."""
    if not db.in_transaction():
        db.begin()
    # Lock the account first to maintain the account -> session lock order.
    _lock_account(db, snapshot.account_id)
    db.execute(
        update(AccountSession)
        .where(
            AccountSession.id == snapshot.session_id,
            AccountSession.revoked_at.is_(None),
        )
        .values(revoked_at=utc_now())
    )
    db.commit()
