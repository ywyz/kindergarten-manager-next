from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app import security
from app.config import settings
from app.database import get_db
from app.deps import get_auth_snapshot, get_current_account
from app.models import Account, AccountSession, FirstAdminControl, OperationRecord
from app.rate_limit import limiter
from app.schemas import LoginIn, MeOut, RegisterIn, RegisterOut
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _is_mysql_duplicate_username_error(exc: IntegrityError) -> bool:
    """Detect the MySQL duplicate-key error on the named username constraint.

    Only ``uq_accounts_username`` (or its SQLAlchemy-prefixed form) maps to
    ``USERNAME_TAKEN``. Other unique violations (primary key, session token,
    audit id) are treated as service-unavailable.
    """
    orig = getattr(exc, "orig", None)
    if orig is None:
        return False
    # PyMySQL IntegrityError args: (error_code, error_message)
    args = getattr(orig, "args", ())
    if len(args) < 2:
        return False
    code = args[0]
    message = str(args[1]) if len(args) > 1 else ""
    if code != 1062 or "Duplicate entry" not in message:
        return False
    return (
        "uq_accounts_username" in message
        or "for key 'username'" in message
    )


@router.post("/register", response_model=RegisterOut, status_code=status.HTTP_201_CREATED)
def register(
    request: Request,
    response: Response,
    data: RegisterIn,
    db: Session = Depends(get_db),
):
    client_host = request.client.host if request.client else "unknown"
    allowed, retry_after = limiter.is_allowed(f"register:ip:{client_host}")
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="RATE_LIMITED",
            headers={"Retry-After": str(retry_after)},
        )

    password_hash = security.hash_password(data.password)
    account_id = security.generate_id()
    now = auth_service.utc_now()

    try:
        control = db.execute(
            select(FirstAdminControl)
            .where(FirstAdminControl.id == "singleton")
            .with_for_update()
        ).scalar_one_or_none()
        if control is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="SERVICE_UNAVAILABLE",
            )

        role = "teacher" if control.claimed else "admin"
        account = Account(
            id=account_id,
            username=data.username,
            password_hash=password_hash,
            display_name=None,
            role=role,
            is_active=True,
            version=1,
            auth_version=1,
            created_at=now,
            updated_at=now,
        )
        db.add(account)
        db.flush()

        if not control.claimed:
            control.claimed = True
            control.first_admin_id = account_id

        auth_service.record_operation(
            db,
            operator_id=account_id,
            operator_type="account",
            action="register",
            target_account_id=account_id,
            account_version_after=1,
        )
        db.commit()
        return {
            "account": auth_service.account_to_out(account),
            "next_action": "login",
        }
    except IntegrityError as exc:
        db.rollback()
        if _is_mysql_duplicate_username_error(exc):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="USERNAME_TAKEN",
            )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SERVICE_UNAVAILABLE",
        )
    except OperationalError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SERVICE_UNAVAILABLE",
        )


@router.post("/login", response_model=MeOut)
def login(
    request: Request,
    response: Response,
    data: LoginIn,
    db: Session = Depends(get_db),
):
    client_host = request.client.host if request.client else "unknown"
    ip_allowed, ip_retry = limiter.is_allowed(f"login:ip:{client_host}")
    user_allowed, user_retry = limiter.is_allowed(f"login:user:{data.username}")
    if not ip_allowed or not user_allowed:
        retry_after = max(ip_retry or 0, user_retry or 0) or 1
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="RATE_LIMITED",
            headers={"Retry-After": str(retry_after)},
        )

    try:
        account, token = auth_service.authenticate_for_login(
            db, data.username, data.password
        )
    except auth_service.InvalidCredentials:
        limiter.record_failure(f"login:ip:{client_host}")
        limiter.record_failure(f"login:user:{data.username}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="INVALID_CREDENTIALS",
        )

    security.set_session_cookie(response, token, settings.session_ttl_seconds)
    assignments = auth_service.assignment_map(db, [account.id])
    class_id = assignments[account.id].class_id if account.id in assignments else None
    return auth_service.me_response(account, class_id)


@router.get("/me", response_model=MeOut)
def me(
    account: Account = Depends(get_current_account),
    db: Session = Depends(get_db),
):
    assignments = auth_service.assignment_map(db, [account.id])
    class_id = assignments[account.id].class_id if account.id in assignments else None
    return auth_service.me_response(account, class_id)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    token = request.cookies.get("session")
    if not token:
        security.clear_session_cookie(response)
        response.status_code = status.HTTP_204_NO_CONTENT
        return response

    token_hash = security.safe_hash_token(token)
    if token_hash is None:
        security.clear_session_cookie(response)
        response.status_code = status.HTTP_204_NO_CONTENT
        return response

    session = db.scalar(
        select(AccountSession).where(AccountSession.token_hash == token_hash)
    )
    if (
        session is None
        or session.revoked_at is not None
        or session.expires_at <= auth_service.utc_now()
    ):
        security.clear_session_cookie(response)
        response.status_code = status.HTTP_204_NO_CONTENT
        return response

    account = db.get(Account, session.account_id)
    if (
        account is None
        or not account.is_active
        or account.auth_version != session.auth_version
    ):
        security.clear_session_cookie(response)
        response.status_code = status.HTTP_204_NO_CONTENT
        return response

    snapshot = auth_service.AuthSnapshot(
        account_id=account.id,
        role=account.role,
        auth_version=account.auth_version,
        session_id=session.id,
        is_active=account.is_active,
        password_hash=account.password_hash,
    )
    # End the read transaction before taking the account->session write locks.
    db.rollback()
    auth_service.revoke_single_session(db, snapshot)

    security.clear_session_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
