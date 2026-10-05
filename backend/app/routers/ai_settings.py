"""1B AI settings API (ai-settings-api-1b.md).

Personal AI config and prompt guidance under ``/settings`` plus admin
default-guidance read/publish under ``/admin``. All identity comes from the
cookie session via ``get_auth_snapshot``; the target is always the snapshot
account. No typed service error text, request body or credential material
ever appears in a response or application log.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_auth_snapshot
from app.schemas import (
    AdminPromptDefaultPatchIn,
    AiConfigDeleteIn,
    AiConfigOut,
    AiConfigPatchIn,
    PersonalInitOut,
    PersonalRejectOut,
    PersonalWriteOut,
    PromptAcceptDefaultIn,
    PromptAdaptIn,
    PromptDefaultOut,
    PromptDetailOut,
    PromptEditIn,
    PromptInitializeIn,
    PromptRejectDefaultIn,
    TaskStatusListOut,
    TaskStatusOut,
)
from app.services import (
    ai_config_service,
    ai_crypto,
    auth_service,
    prompt_service,
)
from app.services.ai_config_service import AiConfigValidationError
from app.services.ai_config_url import AiInputInvalid, BaseUrlInvalid
from app.services.ai_prompt_registry import (
    FieldViolation,
    UnknownTaskType,
)
from app.services.auth_service import AuthSnapshot

router = APIRouter(prefix="/settings", tags=["ai-settings"])
admin_router = APIRouter(prefix="/admin", tags=["admin-prompt-defaults"])

_SERVICE_UNAVAILABLE = HTTPException(
    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    detail="SERVICE_UNAVAILABLE",
)


def _check_task_type(task_type: str) -> None:
    """Explicit whitelist: unknown task types are 404, never a 422 from a
    Literal path parameter and never a misleading 404 for known-task seed
    gaps (those surface as 503 from the service layer)."""
    if task_type not in prompt_service.get_task_types():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="TASK_TYPE_NOT_FOUND",
        )


def _check_admin_snapshot(snapshot: AuthSnapshot) -> None:
    if snapshot.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="FORBIDDEN"
        )


def _map_errors(exc: Exception) -> HTTPException:
    """Typed service errors -> fixed contract; never leaks text."""
    if isinstance(exc, auth_service.AuthRequired):
        return HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="AUTH_REQUIRED",
        )
    if isinstance(exc, auth_service.Forbidden):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="FORBIDDEN"
        )
    if isinstance(
        exc,
        (
            prompt_service.PromptNotInitialized,
        ),
    ):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="PROMPT_NOT_INITIALIZED",
        )
    if isinstance(exc, prompt_service.PromptAdaptationRequired):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="PROMPT_ADAPTATION_REQUIRED",
        )
    if isinstance(exc, prompt_service.ContractAdvanced):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="PROMPT_CONTRACT_CHANGED",
        )
    if isinstance(exc, prompt_service.DefaultContractMismatch):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="PROMPT_DEFAULT_CONTRACT_MISMATCH",
        )
    if isinstance(exc, auth_service.VersionConflict):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="VERSION_CONFLICT",
        )
    if isinstance(
        exc,
        (FieldViolation, AiConfigValidationError, AiInputInvalid, BaseUrlInvalid),
    ):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="VALIDATION_ERROR",
        )
    if isinstance(
        exc,
        (
            ai_crypto.KeyMaterialMissing,
            ai_crypto.KeyMaterialInvalid,
            ai_crypto.DecryptUnavailable,
        ),
    ):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI_CONFIG_UNAVAILABLE",
        )
    if isinstance(exc, UnknownTaskType):
        # Only reachable for KNOWN task types (whitelist checked first),
        # so this means missing database seed/inconsistent row.
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SERVICE_UNAVAILABLE",
        )
    if isinstance(exc, ValidationError):
        # 1B repair R4: a service that ever returned data outside the
        # fixed response DTO contract (unknown ready_reason/protocol,
        # non-positive latest versions, ...) must surface as the fixed
        # JSON error, never as a 200 passthrough or an unhandled
        # traceback that could echo the service value.
        return _SERVICE_UNAVAILABLE
    if isinstance(exc, (auth_service.AuthServiceError, SQLAlchemyError)):
        return _SERVICE_UNAVAILABLE
    return _SERVICE_UNAVAILABLE


def _config_out(view: ai_config_service.AiConfigView) -> AiConfigOut:
    return AiConfigOut(
        version=view.version if view.version is not None else 0,
        protocol_id=view.protocol_id,
        base_url=view.base_url,
        model=view.model,
        has_secret=view.has_secret,
        secret_mask="********" if view.has_secret else None,
        ready=view.ready,
        ready_reason=view.ready_reason if not view.ready else None,
    )


# ---------------------------------------------------------------------------
# AI config (self)
# ---------------------------------------------------------------------------


@router.get("/ai-config", response_model=AiConfigOut)
def get_ai_config(
    db: Session = Depends(get_db),
    snapshot: AuthSnapshot = Depends(get_auth_snapshot),
):
    try:
        view = ai_config_service.get_config(db, snapshot, snapshot.account_id)
        return _config_out(view)
    except Exception as exc:
        raise _map_errors(exc) from None


@router.patch("/ai-config", response_model=AiConfigOut)
def patch_ai_config(
    data: AiConfigPatchIn,
    db: Session = Depends(get_db),
    snapshot: AuthSnapshot = Depends(get_auth_snapshot),
):
    if "secret" in data.model_fields_set:
        secret = data.secret  # non-empty validated string
    else:
        secret = ai_config_service.SECRET_UNSET
    try:
        view = ai_config_service.save_config(
            db,
            snapshot,
            data.expected_version,
            data.protocol_id,
            data.base_url,
            data.model,
            secret,
        )
        return _config_out(view)
    except Exception as exc:
        raise _map_errors(exc) from None


@router.delete("/ai-config", response_model=AiConfigOut)
def delete_ai_config(
    data: AiConfigDeleteIn,
    db: Session = Depends(get_db),
    snapshot: AuthSnapshot = Depends(get_auth_snapshot),
):
    try:
        view = ai_config_service.clear_secret(
            db, snapshot, data.expected_version
        )
        return _config_out(view)
    except Exception as exc:
        raise _map_errors(exc) from None


# ---------------------------------------------------------------------------
# Personal prompt guidance
# ---------------------------------------------------------------------------


@router.get("/prompts", response_model=TaskStatusListOut)
def list_prompts(
    db: Session = Depends(get_db),
    snapshot: AuthSnapshot = Depends(get_auth_snapshot),
):
    try:
        items = prompt_service.list_tasks(db, snapshot, snapshot.account_id)
        return TaskStatusListOut(
            items=[TaskStatusOut(**vars(item)) for item in items]
        )
    except Exception as exc:
        raise _map_errors(exc) from None


@router.get("/prompts/{task_type}", response_model=PromptDetailOut)
def read_prompt(
    task_type: str,
    db: Session = Depends(get_db),
    snapshot: AuthSnapshot = Depends(get_auth_snapshot),
):
    _check_task_type(task_type)
    try:
        view = prompt_service.read_task(
            db, snapshot, snapshot.account_id, task_type
        )
        return PromptDetailOut(**view)
    except Exception as exc:
        raise _map_errors(exc) from None


@router.post("/prompts/{task_type}/initialize", response_model=PersonalInitOut)
def initialize_prompt(
    task_type: str,
    data: PromptInitializeIn,
    db: Session = Depends(get_db),
    snapshot: AuthSnapshot = Depends(get_auth_snapshot),
):
    _check_task_type(task_type)
    try:
        result = prompt_service.initialize_task(
            db, snapshot, snapshot.account_id, task_type
        )
        return PersonalInitOut(**result)
    except Exception as exc:
        raise _map_errors(exc) from None


@router.patch("/prompts/{task_type}", response_model=PersonalWriteOut)
def edit_prompt(
    task_type: str,
    data: PromptEditIn,
    db: Session = Depends(get_db),
    snapshot: AuthSnapshot = Depends(get_auth_snapshot),
):
    _check_task_type(task_type)
    try:
        result = prompt_service.save_guidance(
            db,
            snapshot,
            snapshot.account_id,
            task_type,
            data.guidance_map,
            data.expected_personal_revision,
        )
        return PersonalWriteOut(**result)
    except Exception as exc:
        raise _map_errors(exc) from None


@router.post(
    "/prompts/{task_type}/accept-default", response_model=PersonalWriteOut
)
def accept_prompt_default(
    task_type: str,
    data: PromptAcceptDefaultIn,
    db: Session = Depends(get_db),
    snapshot: AuthSnapshot = Depends(get_auth_snapshot),
):
    _check_task_type(task_type)
    try:
        result = prompt_service.accept_default(
            db,
            snapshot,
            snapshot.account_id,
            task_type,
            data.target_default_revision,
            data.accepted_fields,
            data.expected_personal_revision,
        )
        return PersonalWriteOut(**result)
    except Exception as exc:
        raise _map_errors(exc) from None


@router.post(
    "/prompts/{task_type}/reject-default", response_model=PersonalRejectOut
)
def reject_prompt_default(
    task_type: str,
    data: PromptRejectDefaultIn,
    db: Session = Depends(get_db),
    snapshot: AuthSnapshot = Depends(get_auth_snapshot),
):
    _check_task_type(task_type)
    try:
        result = prompt_service.reject_default(
            db,
            snapshot,
            snapshot.account_id,
            task_type,
            data.target_default_revision,
            data.expected_personal_revision,
        )
        return PersonalRejectOut(**result)
    except Exception as exc:
        raise _map_errors(exc) from None


@router.post("/prompts/{task_type}/adapt", response_model=PersonalWriteOut)
def adapt_prompt(
    task_type: str,
    data: PromptAdaptIn,
    db: Session = Depends(get_db),
    snapshot: AuthSnapshot = Depends(get_auth_snapshot),
):
    _check_task_type(task_type)
    try:
        result = prompt_service.adapt(
            db,
            snapshot,
            snapshot.account_id,
            task_type,
            data.target_contract_version,
            data.guidance_map,
            data.expected_personal_revision,
        )
        return PersonalWriteOut(**result)
    except Exception as exc:
        raise _map_errors(exc) from None


# ---------------------------------------------------------------------------
# Admin default guidance
# ---------------------------------------------------------------------------


@admin_router.get(
    "/prompt-defaults/{task_type}", response_model=PromptDefaultOut
)
def read_prompt_default(
    task_type: str,
    db: Session = Depends(get_db),
    snapshot: AuthSnapshot = Depends(get_auth_snapshot),
):
    _check_admin_snapshot(snapshot)
    _check_task_type(task_type)
    try:
        result = prompt_service.read_default(db, snapshot, task_type)
        return PromptDefaultOut(**result)
    except Exception as exc:
        raise _map_errors(exc) from None


@admin_router.patch(
    "/prompt-defaults/{task_type}", response_model=PromptDefaultOut
)
def patch_prompt_default(
    task_type: str,
    data: AdminPromptDefaultPatchIn,
    db: Session = Depends(get_db),
    snapshot: AuthSnapshot = Depends(get_auth_snapshot),
):
    _check_admin_snapshot(snapshot)
    _check_task_type(task_type)
    try:
        result = prompt_service.update_default(
            db,
            snapshot,
            task_type,
            data.guidance_map,
            data.expected_default_revision,
        )
        return PromptDefaultOut(**result)
    except Exception as exc:
        raise _map_errors(exc) from None
