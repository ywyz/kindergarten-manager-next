from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app import security
from app.database import get_db
from app.deps import get_auth_snapshot, get_current_account
from app.models import Account
from app.schemas import PasswordIn, ProfileIn
from app.services import auth_service

router = APIRouter(prefix="/settings", tags=["settings"])


@router.patch("/profile")
def update_profile(
    request: Request,
    data: ProfileIn,
    db: Session = Depends(get_db),
    snapshot: auth_service.AuthSnapshot = Depends(get_auth_snapshot),
):
    try:
        account = auth_service.update_profile(
            db,
            snapshot,
            data.display_name,
            data.expected_version,
        )
    except auth_service.VersionConflict:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="VERSION_CONFLICT",
        )
    except auth_service.InvalidCredentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="AUTH_REQUIRED",
        )
    except auth_service.AuthRequired:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="AUTH_REQUIRED",
        )
    except auth_service.Forbidden:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="FORBIDDEN",
        )
    return auth_service.account_to_out(account)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    request: Request,
    response: Response,
    data: PasswordIn,
    db: Session = Depends(get_db),
    snapshot: auth_service.AuthSnapshot = Depends(get_auth_snapshot),
):
    new_password_hash = security.hash_password(data.new_password)
    try:
        auth_service.change_own_password(
            db,
            snapshot,
            data.current_password,
            new_password_hash,
            data.expected_version,
        )
    except auth_service.InvalidCredentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="INVALID_CREDENTIALS",
        )
    except auth_service.AuthRequired:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="AUTH_REQUIRED",
        )
    except auth_service.VersionConflict:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="VERSION_CONFLICT",
        )
    except auth_service.Forbidden:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="FORBIDDEN",
        )

    security.clear_session_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
