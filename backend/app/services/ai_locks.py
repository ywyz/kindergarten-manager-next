"""Internal lock/identity helpers shared by the AI 1A config and prompt
services (purely internal file; added because both services need the exact
same identity + anchor-lock sequence and auth_service must not be refactored).

Identity / session verification reuses ``auth_service`` rules unchanged
(excluding ``auth_service._lock_account`` and ``validate_locked_session``).
Lock order everywhere: account -> interaction session -> own head ->
contract anchor (never reversed, no business locks taken in this slice).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Account,
    AccountSession,
    AiConfigHead,
    PersonalPromptHead,
    PromptContractVersion,
)
from app.services import auth_service


def lock_self(db: Session, snapshot: auth_service.AuthSnapshot) -> Account:
    """Lock the operator's account row and re-verify the trusted snapshot
    and the interaction session under it (same rules as I3/I4 services)."""
    account = auth_service._lock_account(db, snapshot.account_id)
    if account is None or not account.is_active:
        raise auth_service.AuthRequired()
    if account.auth_version != snapshot.auth_version:
        raise auth_service.AuthRequired()
    if account.role != snapshot.role:
        raise auth_service.AuthRequired()
    auth_service.validate_locked_session(db, snapshot)
    return account


def verify_self_read(db: Session, snapshot: auth_service.AuthSnapshot) -> Account:
    """Read-path verification of the trusted identity (no locks, no writes)."""
    account = db.get(Account, snapshot.account_id)
    if account is None or not account.is_active:
        raise auth_service.AuthRequired()
    if account.auth_version != snapshot.auth_version:
        raise auth_service.AuthRequired()
    if account.role != snapshot.role:
        raise auth_service.AuthRequired()
    session = db.execute(
        select(AccountSession).where(AccountSession.id == snapshot.session_id)
    ).scalar_one_or_none()
    if (
        session is None
        or session.account_id != snapshot.account_id
        or session.revoked_at is not None
        or session.expires_at <= auth_service.utc_now()
        or session.auth_version != snapshot.auth_version
    ):
        raise auth_service.AuthRequired()
    return account


def assert_self(operator_snapshot_id: str, target_account_id: str) -> None:
    """Personal settings are strictly operator == target."""
    if target_account_id != operator_snapshot_id:
        raise auth_service.Forbidden()


def require_admin(account: Account) -> None:
    if account.role != "admin" or not account.is_active:
        raise auth_service.Forbidden()


def lock_config_head(db: Session, account_id: str) -> AiConfigHead | None:
    """Lock (and freshly read) the account's config head row after the
    account lock; ``populate_existing`` avoids a stale REPEATABLE READ
    snapshot even if the row was read earlier in this transaction."""
    return db.execute(
        select(AiConfigHead)
        .where(AiConfigHead.account_id == account_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()


def lock_personal_head(
    db: Session, account_id: str, task_type: str
) -> PersonalPromptHead | None:
    return db.execute(
        select(PersonalPromptHead)
        .where(
            PersonalPromptHead.account_id == account_id,
            PersonalPromptHead.task_type == task_type,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()


def lock_contract_anchor(
    db: Session, task_type: str, *, for_update: bool
) -> PromptContractVersion:
    """Lock the fixed contract_version==1 seed row for this task type.

    Share lock synchronizes personal writes with each other; publish paths
    (contract/default publishing) take the exclusive FOR UPDATE lock on the
    same row.
    """
    query = (
        select(PromptContractVersion)
        .where(
            PromptContractVersion.task_type == task_type,
            PromptContractVersion.contract_version == 1,
        )
        .execution_options(populate_existing=True)
    )
    if for_update:
        query = query.with_for_update()
    else:
        query = query.with_for_update(read=True)
    row = db.execute(query).scalar_one_or_none()
    if row is None:
        raise auth_service.AuthServiceError(
            f"缺少任务 {task_type!r} 的 contract v1 锁锚点（迁移种子缺失）"
        )
    return row


def latest_contract_locked(db: Session, task_type: str) -> PromptContractVersion:
    return latest_contract_row_locked(db, task_type, share=True)


def latest_contract_row_locked(
    db: Session, task_type: str, *, share: bool = True
) -> PromptContractVersion:
    """Locking read of the task's latest contract row (§7.3).

    Uses a real row lock with ``populate_existing`` so an earlier plain read
    in the same transaction (REPEATABLE READ snapshot) cannot mask a contract
    published between that read and the critical section.
    """
    query = (
        select(PromptContractVersion)
        .where(PromptContractVersion.task_type == task_type)
        .order_by(PromptContractVersion.contract_version.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )
    if share:
        query = query.with_for_update(read=True)
    else:
        query = query.with_for_update()
    row = db.execute(query).scalar_one_or_none()
    if row is None:
        raise auth_service.AuthServiceError(
            f"任务 {task_type!r} 没有任何契约版本行"
        )
    return row

def contract_row_locked(
    db: Session, task_type: str, contract_version: int
) -> PromptContractVersion | None:
    """Locking read (FOR SHARE) of one specific contract row (R6)."""
    return db.execute(
        select(PromptContractVersion)
        .where(
            PromptContractVersion.task_type == task_type,
            PromptContractVersion.contract_version == contract_version,
        )
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
