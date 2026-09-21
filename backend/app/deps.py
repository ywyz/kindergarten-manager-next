from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import security
from app.database import get_db
from app.models import Account, AccountSession
from app.services.auth_service import AuthSnapshot, utc_now


def get_current_account(
    request: Request, db: Session = Depends(get_db)
) -> Account:
    token = request.cookies.get("session")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="AUTH_REQUIRED",
        )
    token_hash = security.safe_hash_token(token)
    if token_hash is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="AUTH_REQUIRED",
        )
    session = db.scalar(
        select(AccountSession).where(AccountSession.token_hash == token_hash)
    )
    if session is None or session.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="AUTH_REQUIRED",
        )
    if session.expires_at <= utc_now():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="AUTH_REQUIRED",
        )
    account = db.get(Account, session.account_id)
    if account is None or not account.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="AUTH_REQUIRED",
        )
    if account.auth_version != session.auth_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="AUTH_REQUIRED",
        )
    return account


def get_auth_snapshot(
    request: Request, db: Session = Depends(get_db)
) -> AuthSnapshot:
    token = request.cookies.get("session")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="AUTH_REQUIRED",
        )
    token_hash = security.safe_hash_token(token)
    if token_hash is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="AUTH_REQUIRED",
        )
    session = db.scalar(
        select(AccountSession).where(AccountSession.token_hash == token_hash)
    )
    if session is None or session.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="AUTH_REQUIRED",
        )
    if session.expires_at <= utc_now():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="AUTH_REQUIRED",
        )
    account = db.get(Account, session.account_id)
    if account is None or not account.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="AUTH_REQUIRED",
        )
    if account.auth_version != session.auth_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="AUTH_REQUIRED",
        )
    snapshot = AuthSnapshot(
        account_id=account.id,
        role=account.role,
        auth_version=account.auth_version,
        session_id=session.id,
        is_active=account.is_active,
        password_hash=account.password_hash,
    )
    db.rollback()
    return snapshot


def require_admin(account: Account = Depends(get_current_account)) -> Account:
    if account.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="FORBIDDEN",
        )
    return account
