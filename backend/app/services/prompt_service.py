"""1A personal/default prompt guidance service (pure service layer).

Checklist §4.2, §6 and §7:

* append-only contracts (migration-seeded), default revisions (admin) and
  personal versions (owner), with composite-FK head pointers;
* the fixed contract_version=1 seed row is the permanent lock anchor:
  personal writes take FOR SHARE on it (read=True → FOR SHARE on MySQL),
  default publishing takes FOR UPDATE; latest contract/default inside a
  critical section use locking reads with ``populate_existing`` (never a
  plain REPEATABLE-READ snapshot);
* adaptation state is authoritative from the personal version's
  ``based_contract_version`` vs the latest contract; head columns are an
  aligned cache written only inside successful write paths; pure reads
  derive state without touching rows (GET never advances a revision);
* reject creates no personal version; accept/reject are blocked while
  adaptation is required; explicit ``initialize_task`` is the only way a
  first personal version + head appear, in one atomic transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import security
from app.models import (
    PersonalPromptHead,
    PersonalPromptVersion,
    PromptChangeRecord,
    PromptContractVersion,
    PromptDefaultVersion,
)
from app.services import ai_locks, ai_prompt_registry, auth_service
from app.services.ai_prompt_registry import (
    FieldViolation,
    MAX_GUIDANCE_FIELD_CHARS,
    UnknownTaskType,
    get_registry,
    require_task_type,
)

EVENT_KIND_INIT = "personal_init"
EVENT_KIND_EDIT = "personal_edit"
EVENT_KIND_ACCEPT = "accept_default"
EVENT_KIND_REJECT = "reject_default"
EVENT_KIND_ADAPT = "adapt"
EVENT_KIND_DEFAULT_UPDATE = "default_update"

STATE_CURRENT = "current"
STATE_ADAPTATION_REQUIRED = "adaptation_required"


class PromptAdaptationRequired(Exception):
    """AI paused until assist completes; accept/reject blocked (§6.2)."""


class ContractAdvanced(Exception):
    """The contract advanced between read and commit (locking-read check)."""


class DefaultContractMismatch(Exception):
    """Target default revision is not contract-compatible."""


class PromptNotInitialized(Exception):
    """No personal head exists for this (account, task type)."""


@dataclass(frozen=True)
class PromptResolution:
    """``resolve_prompt`` result — executor-facing, no secrets."""

    personal_revision: int | None
    guidance_map: dict[str, str] | None
    based_contract_version: int | None
    contract_version: int | None
    adaptation_state: str
    ready: bool
    ready_reason: str | None


@dataclass(frozen=True)
class TaskStatus:
    task_type: str
    initialized: bool
    adaptation_state: str
    required_contract_version: int | None
    pending_default_update: bool
    latest_default_revision: int
    latest_contract_version: int


def _begin(db: Session) -> None:
    if not db.in_transaction():
        db.begin()


def _utc_now() -> Any:
    return auth_service.utc_now()


def _latest_contract_row(
    db: Session, task_type: str
) -> PromptContractVersion | None:
    return db.execute(
        select(PromptContractVersion)
        .where(PromptContractVersion.task_type == task_type)
        .order_by(PromptContractVersion.contract_version.desc())
        .limit(1)
    ).scalar_one_or_none()


def _latest_default_row(
    db: Session,
    task_type: str,
    contract_version: int,
    *,
    lock: str | None = None,
) -> PromptDefaultVersion | None:
    """Latest default revision under a contract.

    R6: 发布路径必须使用 current 锁定读（``lock='share'`` 个人写锁内共享读、
    ``lock='update'`` 管理员发布路径排他读），不可由于 REPEATABLE READ
    旧快照计算重复修订；纯展示读（``lock=None``）维持普通读。
    """
    query = (
        select(PromptDefaultVersion)
        .where(
            PromptDefaultVersion.task_type == task_type,
            PromptDefaultVersion.contract_version == contract_version,
        )
        .order_by(PromptDefaultVersion.default_revision.desc())
        .limit(1)
    )
    if lock == "share":
        query = query.with_for_update(read=True)
    elif lock == "update":
        query = query.with_for_update()
    return db.execute(query).scalar_one_or_none()


def _default_row_locked(
    db: Session, task_type: str, default_revision: int
) -> PromptDefaultVersion | None:
    return db.execute(
        select(PromptDefaultVersion)
        .where(
            PromptDefaultVersion.task_type == task_type,
            PromptDefaultVersion.default_revision == default_revision,
        )
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()


def _derive_state(
    based_contract_version: int | None, latest_contract_version: int
) -> tuple[str, int | None]:
    if based_contract_version is None:
        raise PromptNotInitialized()
    if based_contract_version < latest_contract_version:
        return STATE_ADAPTATION_REQUIRED, latest_contract_version
    return STATE_CURRENT, None


def get_task_types() -> tuple[str, ...]:
    """Service-level task whitelist (R1); used by real list_tasks entry."""
    return ai_prompt_registry.TASK_TYPES


# ---------------------------------------------------------------------------
# read entry points (no writes; GET never advances processed revisions)
# ---------------------------------------------------------------------------


def _read_head(
    db: Session, account_id: str, task_type: str
) -> PersonalPromptHead | None:
    return db.execute(
        select(PersonalPromptHead).where(
            PersonalPromptHead.account_id == account_id,
            PersonalPromptHead.task_type == task_type,
        )
    ).scalar_one_or_none()


def _read_current_version(
    db: Session, head: PersonalPromptHead, *, current: bool = False
) -> PersonalPromptVersion:
    """Read the version row the head points at.

    ``current=False``：纯展示读（普通快照即可，无锁）；``current=True``：
    写事务在 head 已被 locking read 锁定后的 current 锁定读
    （FOR SHARE ＋ populate_existing，R6）——不能用旧 REPEATABLE READ
    快照读新指针指向的行。
    """
    query = select(PersonalPromptVersion).where(
        PersonalPromptVersion.account_id == head.account_id,
        PersonalPromptVersion.task_type == head.task_type,
        PersonalPromptVersion.personal_revision
        == head.current_personal_revision,
    )
    if current:
        query = query.with_for_update(read=True).execution_options(
            populate_existing=True
        )
    return db.execute(query).scalar_one()


def list_tasks(
    db: Session,
    snapshot: auth_service.AuthSnapshot,
    target_account_id: str,
) -> list[TaskStatus]:
    ai_locks.assert_self(snapshot.account_id, target_account_id)
    ai_locks.verify_self_read(db, snapshot)
    return [_task_status(db, target_account_id, t) for t in get_task_types()]


def _task_status(db: Session, account_id: str, task_type: str) -> TaskStatus:
    latest_contract = _latest_contract_row(db, task_type)
    if latest_contract is None:
        # 已知任务缺契约行为数据库不一致：503，而不是假的 version=0 可用态。
        raise UnknownTaskType(f"任务 {task_type} 没有契约版本行")
    latest_default = _latest_default_row(
        db, task_type, latest_contract.contract_version, lock=None
    )
    if latest_default is None:
        raise UnknownTaskType(f"任务 {task_type} 没有匹配契约的默认修订")
    latest_contract_version = latest_contract.contract_version
    latest_default_revision = latest_default.default_revision
    head = _read_head(db, account_id, task_type)
    if head is None:
        return TaskStatus(
            task_type=task_type,
            initialized=False,
            adaptation_state=STATE_CURRENT,
            required_contract_version=None,
            pending_default_update=False,
            latest_default_revision=latest_default_revision,
            latest_contract_version=latest_contract_version,
        )
    version = _read_current_version(db, head)
    state, required = _derive_state(
        version.based_contract_version, latest_contract_version
    )
    return TaskStatus(
        task_type=task_type,
        initialized=True,
        adaptation_state=state,
        required_contract_version=required,
        pending_default_update=(
            (head.last_seen_default_revision or 0) < latest_default_revision
        ),
        latest_default_revision=latest_default_revision,
        latest_contract_version=latest_contract_version,
    )


def read_task(
    db: Session,
    snapshot: auth_service.AuthSnapshot,
    target_account_id: str,
    task_type: str,
) -> dict[str, Any]:
    """Read view: not_initialized -> current contract + full default map;
    otherwise the current personal revision and states. Never writes."""
    ai_locks.assert_self(snapshot.account_id, target_account_id)
    ai_locks.verify_self_read(db, snapshot)
    get_registry(require_task_type(task_type))  # registry must know it

    latest_contract = _latest_contract_row(db, task_type)
    if latest_contract is None:
        raise UnknownTaskType(f"任务 {task_type} 没有契约版本行")
    head = _read_head(db, target_account_id, task_type)
    latest_default = _latest_default_row(
        db, task_type, latest_contract.contract_version, lock=None
    )
    if latest_default is None:
        raise UnknownTaskType(f"任务 {task_type} 没有匹配契约的默认修订")
    latest_default_revision = latest_default.default_revision
    base_view = dict(
        task_type=task_type,
        latest_contract_version=latest_contract.contract_version,
        latest_default_revision=latest_default_revision,
        guidance_fields=list(latest_contract.guidance_fields),
        latest_default=dict(
            default_revision=latest_default.default_revision,
            contract_version=latest_contract.contract_version,
            guidance_map=dict(latest_default.guidance_map),
        ),
    )
    if head is None:
        return dict(
            base_view,
            state="not_initialized",
            personal_revision=None,
            guidance_map=None,
            based_contract_version=None,
            accepted_default_revision=None,
            based_guidance_fields=[],
            adaptation_state=STATE_CURRENT,
            required_contract_version=None,
            pending_default_update=False,
            last_rejected_default_revision=None,
        )
    version = _read_current_version(db, head)
    state, required = _derive_state(
        version.based_contract_version, latest_contract.contract_version
    )
    based_contract = db.execute(
        select(PromptContractVersion).where(
            PromptContractVersion.task_type == task_type,
            PromptContractVersion.contract_version
            == version.based_contract_version,
        )
    ).scalar_one_or_none()
    if based_contract is None:
        raise UnknownTaskType(
            f"个人版本 based contract {version.based_contract_version} 不存在"
        )
    return dict(
        base_view,
        state="initialized",
        personal_revision=version.personal_revision,
        guidance_map=dict(version.guidance_map),
        based_contract_version=version.based_contract_version,
        accepted_default_revision=version.accepted_default_revision,
        based_guidance_fields=list(based_contract.guidance_fields),
        adaptation_state=state,
        required_contract_version=required,
        pending_default_update=(
            (head.last_seen_default_revision or 0) < latest_default_revision
        ),
        last_rejected_default_revision=head.last_rejected_default_revision,
    )


def resolve_prompt(
    db: Session,
    target_account_id: str,
    task_type: str,
    *,
    pinned_revision: int | None = None,
) -> PromptResolution:
    """Internal resolution shared by future API/worker (§4.2).

    No locks, no writes, no session needed. Without ``pinned_revision`` the
    result reflects the head-derived current states; with it, the exact
    revision plus its based contract, with no adaptation/readiness filtering
    (the caller decides). An unfit prompt only pauses THIS task type.
    """
    require_task_type(task_type)
    head = _read_head(db, target_account_id, task_type)
    latest_contract = _latest_contract_row(db, task_type)
    latest_contract_version = (
        latest_contract.contract_version if latest_contract else None
    )
    if head is None:
        return PromptResolution(
            personal_revision=None,
            guidance_map=None,
            based_contract_version=None,
            contract_version=latest_contract_version,
            adaptation_state=STATE_CURRENT,
            ready=False,
            ready_reason="PROMPT_NOT_INITIALIZED",
        )
    version = _read_current_version(db, head)
    if pinned_revision is not None:
        pinned = db.execute(
            select(PersonalPromptVersion).where(
                PersonalPromptVersion.account_id == target_account_id,
                PersonalPromptVersion.task_type == task_type,
                PersonalPromptVersion.personal_revision == pinned_revision,
            )
        ).scalar_one_or_none()
        if pinned is None:
            raise PromptNotInitialized()
        return PromptResolution(
            personal_revision=pinned.personal_revision,
            guidance_map=dict(pinned.guidance_map),
            based_contract_version=pinned.based_contract_version,
            contract_version=pinned.based_contract_version,
            adaptation_state=STATE_CURRENT,
            ready=True,
            ready_reason=None,
        )
    state, _required = _derive_state(
        version.based_contract_version, latest_contract_version
    )
    ready = state == STATE_CURRENT
    return PromptResolution(
        personal_revision=version.personal_revision,
        guidance_map=dict(version.guidance_map),
        based_contract_version=version.based_contract_version,
        contract_version=latest_contract_version,
        adaptation_state=state,
        ready=ready,
        ready_reason=None if ready else "ADAPTATION_REQUIRED",
    )


# ---------------------------------------------------------------------------
# write entry points
# ---------------------------------------------------------------------------


def _person_op_record(db: Session, account: Any, action: str) -> str:
    """审计先行并 flush 取得引用（§7.3）；记录真实 accounts.version。"""
    record = auth_service.record_operation(
        db,
        operator_id=account.id,
        operator_type="account",
        action=action,
        target_type="account",
        target_id=account.id,
        target_version_after=account.version,
    )
    db.flush()
    return record.id


def _ensure_writable_state(head: PersonalPromptHead | None) -> None:
    if head is not None and head.adaptation_state == STATE_ADAPTATION_REQUIRED:
        # 普通编辑不解除适配；接受／拒绝在此状态被拒（§6.2）。
        raise PromptAdaptationRequired()


def _check_expected_revision(
    head: PersonalPromptHead | None, expected_personal_revision: Any
) -> None:
    if not isinstance(expected_personal_revision, int) or isinstance(
        expected_personal_revision, bool
    ):
        raise FieldViolation("expected_personal_revision 必须是正整数")
    if head is None:
        raise PromptNotInitialized(
            "未初始化不支持 expected=0 的写入；请先显式 initialize_task"
        )
    if expected_personal_revision != head.current_personal_revision:
        raise auth_service.VersionConflict(
            f"expected_personal_revision {expected_personal_revision} "
            f"与当前 {head.current_personal_revision} 不一致"
        )


def _new_personal_version(
    db: Session,
    *,
    account_id: str,
    task_type: str,
    personal_revision: int,
    guidance_map: dict[str, str],
    based_contract_version: int,
    accepted_default_revision: int,
    created_by: str,
) -> PersonalPromptVersion:
    version = PersonalPromptVersion(
        id=security.generate_id(),
        account_id=account_id,
        task_type=task_type,
        personal_revision=personal_revision,
        guidance_map=dict(guidance_map),
        based_contract_version=based_contract_version,
        accepted_default_revision=accepted_default_revision,
        created_by=created_by,
        created_at=_utc_now(),
    )
    db.add(version)
    return version


def _new_head(
    db: Session,
    *,
    account_id: str,
    task_type: str,
    current_personal_revision: int,
    required_contract_version: int | None,
    last_seen_default_revision: int | None,
    last_rejected_default_revision: int | None,
) -> PersonalPromptHead:
    head = PersonalPromptHead(
        account_id=account_id,
        task_type=task_type,
        current_personal_revision=current_personal_revision,
        adaptation_state=STATE_CURRENT,
        required_contract_version=required_contract_version,
        last_seen_default_revision=last_seen_default_revision,
        last_rejected_default_revision=last_rejected_default_revision,
        created_at=_utc_now(),
        updated_at=_utc_now(),
    )
    db.add(head)
    return head


def _add_event(
    db: Session,
    *,
    operation_record_id: str,
    task_type: str,
    event_kind: str,
    personal_revision_before: int | None,
    personal_revision_after: int | None,
    default_revision_target: int | None,
    contract_version_target: int | None,
    changed_fields: list[str],
) -> None:
    db.add(
        PromptChangeRecord(
            id=security.generate_id(),
            operation_record_id=operation_record_id,
            task_type=task_type,
            event_kind=event_kind,
            personal_revision_before=personal_revision_before,
            personal_revision_after=personal_revision_after,
            default_revision_target=default_revision_target,
            contract_version_target=contract_version_target,
            changed_fields=list(changed_fields),
            created_at=_utc_now(),
        )
    )


def _validate_map_for_fields(
    field_names: Any, mapping: Any, *, task_type: str
) -> dict[str, str]:
    """Validate a FULL guidance_map against the CONTRACT's field set (R2).

    The task whitelist / output structure still come from the system
    registry; the guidance field set is read from the published contract row
    that the write targets — never the fixed v1 registry.
    """
    if not isinstance(field_names, list):
        raise FieldViolation(f"契约 {task_type} 的字段集不是列表")
    if not isinstance(mapping, dict):
        raise FieldViolation("guidance_map 必须是对象")
    if sorted(mapping.keys()) != sorted(field_names):
        raise FieldViolation(
            f"guidance_map 字段集必须与契约完全一致 ({list(field_names)})"
        )
    for name, value in mapping.items():
        if not isinstance(value, str):
            raise FieldViolation(f"指导字段 {name!r} 必须为字符串")
        if len(value) > MAX_GUIDANCE_FIELD_CHARS:
            raise FieldViolation(
                f"指导字段 {name!r} 单字段长度不能超过 "
                f"{MAX_GUIDANCE_FIELD_CHARS} 字符"
            )
    return dict(mapping)


def _validate_patch_for_fields(
    field_names: Any, names: Any, *, task_type: str
) -> list[str]:
    """Validate an accepted-fields / patch NAME list against the contract."""
    if not isinstance(field_names, list):
        raise FieldViolation(f"契约 {task_type} 的字段集不是列表")
    if not isinstance(names, list) or not names:
        raise FieldViolation("选定字段列表必须是显式指定的字段名列表")
    for name in names:
        if not isinstance(name, str) or name not in field_names:
            raise FieldViolation(f"未知的契约指导字段 {name!r}")
    if len(set(names)) != len(names):
        raise FieldViolation("选定字段列表不能有重复")
    return list(names)


def initialize_task(
    db: Session,
    snapshot: auth_service.AuthSnapshot,
    target_account_id: str,
    task_type: str,
) -> dict[str, Any]:
    """Explicit first initialization (idempotent once initialized).

    One transaction: first personal version row + NOT NULL head pointer;
    accepted_default_revision records the default revision whose literal
    snapshot becomes the first map (traceable origin, §4.2).
    """
    ai_locks.assert_self(snapshot.account_id, target_account_id)
    registry = get_registry(require_task_type(task_type))
    _begin(db)
    try:
        account = ai_locks.lock_self(db, snapshot)
        head = ai_locks.lock_personal_head(db, account.id, task_type)
        if head is not None:
            version = _read_current_version(db, head, current=True)
            db.commit()
            return dict(
                state="initialized",
                idempotent=True,
                task_type=task_type,
                personal_revision=version.personal_revision,
                guidance_map=dict(version.guidance_map),
                based_contract_version=version.based_contract_version,
                accepted_default_revision=version.accepted_default_revision,
            )

        ai_locks.lock_contract_anchor(db, task_type, for_update=False)
        latest_contract = ai_locks.latest_contract_locked(db, task_type)
        latest_default = _latest_default_row(
            db, task_type, latest_contract.contract_version, lock="share"
        )
        if latest_default is None:
            raise UnknownTaskType(f"任务 {task_type} 没有匹配契约的默认修订")
        # R2: 用目标 contract 的字段集验证（非固定 v1 registry）。
        guidance_map = _validate_map_for_fields(
            latest_contract.guidance_fields, latest_default.guidance_map,
            task_type=task_type,
        )
        record_id = _person_op_record(db, account, "prompt_personal_init")
        _new_personal_version(
            db,
            account_id=account.id,
            task_type=task_type,
            personal_revision=1,
            guidance_map=guidance_map,
            based_contract_version=latest_contract.contract_version,
            accepted_default_revision=latest_default.default_revision,
            created_by=account.id,
        )
        db.flush()
        _new_head(
            db,
            account_id=account.id,
            task_type=task_type,
            current_personal_revision=1,
            required_contract_version=None,
            last_seen_default_revision=latest_default.default_revision,
            last_rejected_default_revision=None,
        )
        _add_event(
            db,
            operation_record_id=record_id,
            task_type=task_type,
            event_kind=EVENT_KIND_INIT,
            personal_revision_before=None,
            personal_revision_after=1,
            default_revision_target=latest_default.default_revision,
            contract_version_target=latest_contract.contract_version,
            changed_fields=list(guidance_map.keys()),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return dict(
        state="initialized",
        idempotent=False,
        task_type=task_type,
        personal_revision=1,
        guidance_map=guidance_map,
        based_contract_version=latest_contract.contract_version,
        accepted_default_revision=latest_default.default_revision,
    )


def save_guidance(
    db: Session,
    snapshot: auth_service.AuthSnapshot,
    target_account_id: str,
    task_type: str,
    patch: dict[str, str],
    expected_personal_revision: int,
) -> dict[str, Any]:
    """Partial edit: selected fields overridden; new revision + head move.

    Personal edit keeps the personal version's OWN based contract: the field
    set is validated against THAT contract (R2), structure/defaults are not
    silently rewritten to newer fields.
    """
    ai_locks.assert_self(snapshot.account_id, target_account_id)
    require_task_type(task_type)  # task whitelist only (R2)
    if not isinstance(patch, dict) or not patch:
        raise FieldViolation("字段更新内容不能为空")
    # 与契约无关的 shape 检查可提前（值类型／长度）；字段名集必须在锁内按
    # based contract 校验，不得用 v1 registry 提前拒绝 v2 合法提交。
    for name, value in patch.items():
        if not isinstance(name, str):
            raise FieldViolation("指导字段名必须是字符串")
        if not isinstance(value, str):
            raise FieldViolation(f"指导字段 {name!r} 必须为字符串")
        if len(value) > MAX_GUIDANCE_FIELD_CHARS:
            raise FieldViolation(
                f"指导字段 {name!r} 单字段长度不能超过 "
                f"{MAX_GUIDANCE_FIELD_CHARS} 字符"
            )
    _begin(db)
    try:
        account = ai_locks.lock_self(db, snapshot)
        head = ai_locks.lock_personal_head(db, account.id, task_type)
        _check_expected_revision(head, expected_personal_revision)

        ai_locks.lock_contract_anchor(db, task_type, for_update=False)
        latest_contract = ai_locks.latest_contract_locked(db, task_type)
        base_version = _read_current_version(db, head, current=True)
        based_contract = ai_locks.contract_row_locked(
            db, task_type, base_version.based_contract_version
        )
        if based_contract is None:
            raise UnknownTaskType(
                f"个人版本 based contract {base_version.based_contract_version} 不存在"
            )
        _validate_patch_for_fields(
            based_contract.guidance_fields, list(patch.keys()),
            task_type=task_type,
        )
        merged_map = dict(base_version.guidance_map)
        merged_map.update(patch)
        merged_map = _validate_map_for_fields(
            based_contract.guidance_fields, merged_map, task_type=task_type
        )

        record_id = _person_op_record(db, account, "prompt_personal_edit")
        new_revision = head.current_personal_revision + 1
        version = _new_personal_version(
            db,
            account_id=account.id,
            task_type=task_type,
            personal_revision=new_revision,
            guidance_map=merged_map,
            based_contract_version=base_version.based_contract_version,
            accepted_default_revision=base_version.accepted_default_revision,
            created_by=account.id,
        )
        db.flush()
        head.current_personal_revision = new_revision
        # 事务内对齐缓存（§7.2；based 不变，仅保险重算）。
        state, required = _derive_state(
            base_version.based_contract_version, latest_contract.contract_version
        )
        head.adaptation_state = state
        head.required_contract_version = required
        # personal_edit 不修改 last_seen／last_rejected（§7.2）。
        head.updated_at = _utc_now()
        _add_event(
            db,
            operation_record_id=record_id,
            task_type=task_type,
            event_kind=EVENT_KIND_EDIT,
            personal_revision_before=new_revision - 1,
            personal_revision_after=new_revision,
            default_revision_target=None,
            contract_version_target=None,
            changed_fields=list(patch.keys()),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    final_state, _ = _derive_state(
        version.based_contract_version,
        latest_contract.contract_version,
    )
    return dict(
        state="initialized",
        task_type=task_type,
        personal_revision=version.personal_revision,
        guidance_map=merged_map,
        based_contract_version=version.based_contract_version,
        accepted_default_revision=version.accepted_default_revision,
        adaptation_state=final_state,
    )


def reject_default(
    db: Session,
    snapshot: auth_service.AuthSnapshot,
    target_account_id: str,
    task_type: str,
    target_default_revision: int,
    expected_personal_revision: int,
) -> dict[str, Any]:
    """Record a normal default rejection; NO new personal version (§7.4).

    Validation order: identity -> expected -> target revision existence and
    contract compatibility -> idempotency. If already rejected (same
    effective state) return idempotently without a new event (PF-3).
    Blocked entirely in the adaptation_required state.
    """
    ai_locks.assert_self(snapshot.account_id, target_account_id)
    get_registry(require_task_type(task_type))
    if (
        not isinstance(target_default_revision, int)
        or isinstance(target_default_revision, bool)
        or target_default_revision < 1
    ):
        raise FieldViolation("target_default_revision 必须是正整数修订号")
    _begin(db)
    try:
        account = ai_locks.lock_self(db, snapshot)
        head = ai_locks.lock_personal_head(db, account.id, task_type)
        _check_expected_revision(head, expected_personal_revision)
        if head.adaptation_state == STATE_ADAPTATION_REQUIRED:
            raise PromptAdaptationRequired()
        ai_locks.lock_contract_anchor(db, task_type, for_update=False)
        latest_contract = ai_locks.latest_contract_locked(db, task_type)
        base_version = _read_current_version(db, head, current=True)
        state_now, _required_now = _derive_state(
            base_version.based_contract_version, latest_contract.contract_version
        )
        if state_now == STATE_ADAPTATION_REQUIRED:
            raise PromptAdaptationRequired()

        target_default = _default_row_locked(
            db, task_type, target_default_revision
        )
        if (
            target_default is None
            or target_default.contract_version
            != latest_contract.contract_version
        ):
            raise DefaultContractMismatch(
                f"目标默认修订 {target_default_revision} "
                "不是该任务当前契约下的修订"
            )
        # 幂等判定放在目标存在及契约兼容核对之后（勘误顺序）；
        # 同一有效状态重复拒绝 -> 幂等返回，不写事件。
        if (
            head.last_rejected_default_revision == target_default_revision
            and (head.last_seen_default_revision or 0)
            >= target_default_revision
        ):
            db.commit()
            return dict(
                state="unchanged",
                idempotent=True,
                task_type=task_type,
                personal_revision=base_version.personal_revision,
                last_rejected_default_revision=head.last_rejected_default_revision,
            )

        before = head.current_personal_revision
        record_id = _person_op_record(db, account, "prompt_default_reject")
        head.last_rejected_default_revision = target_default_revision
        head.last_seen_default_revision = max(
            head.last_seen_default_revision or 0, target_default_revision
        )
        head.updated_at = _utc_now()
        # 头缓存按事务重对齐（based 未变，仅保险重算）。
        state, required = _derive_state(
            base_version.based_contract_version, latest_contract.contract_version
        )
        head.adaptation_state = state
        head.required_contract_version = required
        _add_event(
            db,
            operation_record_id=record_id,
            task_type=task_type,
            event_kind=EVENT_KIND_REJECT,
            personal_revision_before=before,
            personal_revision_after=before,  # 拒绝不推进个人版本
            default_revision_target=target_default_revision,
            contract_version_target=latest_contract.contract_version,
            changed_fields=[],
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return dict(
        state="unchanged",
        idempotent=False,
        task_type=task_type,
        personal_revision=before,
        last_rejected_default_revision=target_default_revision,
    )


def accept_default(
    db: Session,
    snapshot: auth_service.AuthSnapshot,
    target_account_id: str,
    task_type: str,
    target_default_revision: int,
    accepted_fields: list[str],
    expected_personal_revision: int,
) -> dict[str, Any]:
    """Accept selected fields from a contract-compatible default revision.

    - non-empty, duplicate-free field-name subset only; the rest of the map
      is preserved (文字来自所选默认);
    - the target revision must be an EXISTING revision under BOTH the
      personal version's based contract AND the currently valid contract,
      otherwise DefaultContractMismatch (no auto-mapping);
    - new revision + event in the same transaction; recorded
      ``last_seen_default_revision = max(old or 0, target)`` and the reject
      marker cleared when it equals the target (§7.2/§7.5).
    """
    ai_locks.assert_self(snapshot.account_id, target_account_id)
    require_task_type(task_type)
    # 契约无关的 shape 检查提前；字段名集在锁内按属于的契约校验（R2）。
    if not isinstance(accepted_fields, list) or not accepted_fields:
        raise FieldViolation("选定字段列表不能为空")
    for name in accepted_fields:
        if not isinstance(name, str):
            raise FieldViolation("选定字段名必须是字符串")
    if (
        not isinstance(target_default_revision, int)
        or isinstance(target_default_revision, bool)
        or target_default_revision < 1
    ):
        raise FieldViolation("target_default_revision 必须是正整数修订号")
    _begin(db)
    try:
        account = ai_locks.lock_self(db, snapshot)
        head = ai_locks.lock_personal_head(db, account.id, task_type)
        _check_expected_revision(head, expected_personal_revision)

        ai_locks.lock_contract_anchor(db, task_type, for_update=False)
        latest_contract = ai_locks.latest_contract_locked(db, task_type)
        target_default = _default_row_locked(
            db, task_type, target_default_revision
        )
        before_version = _read_current_version(db, head, current=True)
        # 待适配态优先阻断（§6.2）：普通接受不能绕过必需字段适配。
        state_now, _required_now = _derive_state(
            before_version.based_contract_version, latest_contract.contract_version
        )
        if state_now == STATE_ADAPTATION_REQUIRED:
            raise PromptAdaptationRequired()
        if (
            target_default is None
            or target_default.contract_version
            != latest_contract.contract_version
            or latest_contract.contract_version
            != before_version.based_contract_version
        ):
            raise DefaultContractMismatch(
                f"目标默认修订 {target_default_revision} 与当前契约不兼容"
            )
        # R2: 契约兼容核对完成后，按该 contract 的字段集校验选定字段和
        # 合成后的完整新映射。
        _validate_patch_for_fields(
            latest_contract.guidance_fields, accepted_fields, task_type=task_type
        )
        selected_map = {
            name: target_default.guidance_map[name] for name in accepted_fields
        }
        merged_map = dict(before_version.guidance_map)
        merged_map.update(selected_map)
        merged_map = _validate_map_for_fields(
            latest_contract.guidance_fields, merged_map, task_type=task_type
        )

        new_revision = head.current_personal_revision + 1
        record_id = _person_op_record(db, account, "prompt_default_accept")
        _new_personal_version(
            db,
            account_id=account.id,
            task_type=task_type,
            personal_revision=new_revision,
            guidance_map=merged_map,
            based_contract_version=latest_contract.contract_version,
            accepted_default_revision=target_default_revision,
            created_by=account.id,
        )
        db.flush()
        head.current_personal_revision = new_revision
        state, required = _derive_state(
            latest_contract.contract_version, latest_contract.contract_version
        )
        head.adaptation_state = state
        head.required_contract_version = required
        head.last_seen_default_revision = max(
            head.last_seen_default_revision or 0, target_default_revision
        )
        if head.last_rejected_default_revision == target_default_revision:
            head.last_rejected_default_revision = None
        head.updated_at = _utc_now()
        _add_event(
            db,
            operation_record_id=record_id,
            task_type=task_type,
            event_kind=EVENT_KIND_ACCEPT,
            personal_revision_before=before_version.personal_revision,
            personal_revision_after=new_revision,
            default_revision_target=target_default_revision,
            contract_version_target=latest_contract.contract_version,
            changed_fields=list(accepted_fields),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return dict(
        state="initialized",
        task_type=task_type,
        personal_revision=new_revision,
        guidance_map=merged_map,
        based_contract_version=latest_contract.contract_version,
        accepted_default_revision=target_default_revision,
        adaptation_state=STATE_CURRENT,
    )


def adapt(
    db: Session,
    snapshot: auth_service.AuthSnapshot,
    target_account_id: str,
    task_type: str,
    target_contract_version: int,
    full_guidance_map: dict[str, str],
    expected_personal_revision: int,
) -> dict[str, Any]:
    """Finish adaptation: full map for the target contract (§6.2).

    Inside the anchor lock the target must STILL be the newest contract
    version (locking read), otherwise ``ContractAdvanced`` and the whole
    transaction rolls back. The user submits the complete field set (new
    fields are prefilled by the caller from the matching default); missing
    fields are never silently prefilled after submission. The matched latest
    default revision for the target contract is recorded as the new personal
    version's accepted_default_revision (§6.2).
    """
    ai_locks.assert_self(snapshot.account_id, target_account_id)
    require_task_type(task_type)
    if not isinstance(full_guidance_map, dict):
        raise FieldViolation("full_guidance_map 必须是对象")
    # 契约无关的 shape 检查提前；目标 contract 的字段集在锁内校验（R2），
    # 不得在访问数据库前用 v1 registry 拒绝合法的 v2 全量映射。
    for name, value in full_guidance_map.items():
        if not isinstance(name, str):
            raise FieldViolation("指导字段名必须是字符串")
        if not isinstance(value, str):
            raise FieldViolation(f"指导字段 {name!r} 必须为字符串")
        if len(value) > MAX_GUIDANCE_FIELD_CHARS:
            raise FieldViolation(
                f"指导字段 {name!r} 单字段长度不能超过 "
                f"{MAX_GUIDANCE_FIELD_CHARS} 字符"
            )
    if (
        not isinstance(target_contract_version, int)
        or isinstance(target_contract_version, bool)
        or target_contract_version < 1
    ):
        raise FieldViolation("target_contract_version 必须是正整数契约版本")
    _begin(db)
    try:
        account = ai_locks.lock_self(db, snapshot)
        head = ai_locks.lock_personal_head(db, account.id, task_type)
        _check_expected_revision(head, expected_personal_revision)

        ai_locks.lock_contract_anchor(db, task_type, for_update=False)
        latest_contract = ai_locks.latest_contract_locked(db, task_type)
        latest_default = _latest_default_row(
            db, task_type, latest_contract.contract_version, lock="share"
        )
        if latest_default is None:
            raise UnknownTaskType(
                f"契约 {latest_contract.contract_version} 没有匹配默认修订"
            )
        if target_contract_version != latest_contract.contract_version:
            raise ContractAdvanced(
                f"目标契约 {target_contract_version} 已不是最新 "
                f"{latest_contract.contract_version}，请重新读取后再适配"
            )
        base_version = _read_current_version(db, head, current=True)
        # 合法提交顺序«adapt先提交、发布随后推进»要求 adapt 可在 based ==
        # latest 且无缓存待适配时执行（§7.4：旧契约仍有效时 adapt 合法提交）；
        # 只需 expected 与契约目标经锚点锁保护再次核验。
        _validate_map_for_fields(
            latest_contract.guidance_fields, full_guidance_map,
            task_type=task_type,
        )
        new_revision = head.current_personal_revision + 1
        record_id = _person_op_record(db, account, "prompt_adapt")
        _new_personal_version(
            db,
            account_id=account.id,
            task_type=task_type,
            personal_revision=new_revision,
            guidance_map=full_guidance_map,
            based_contract_version=latest_contract.contract_version,
            accepted_default_revision=latest_default.default_revision,
            created_by=account.id,
        )
        db.flush()
        head.current_personal_revision = new_revision
        head.adaptation_state = STATE_CURRENT
        head.required_contract_version = None
        head.last_seen_default_revision = max(
            head.last_seen_default_revision or 0, latest_default.default_revision
        )
        head.updated_at = _utc_now()
        _add_event(
            db,
            operation_record_id=record_id,
            task_type=task_type,
            event_kind=EVENT_KIND_ADAPT,
            personal_revision_before=base_version.personal_revision,
            personal_revision_after=new_revision,
            default_revision_target=latest_default.default_revision,
            contract_version_target=latest_contract.contract_version,
            changed_fields=list(full_guidance_map.keys()),  # 完整字段集
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return dict(
        state="initialized",
        task_type=task_type,
        personal_revision=new_revision,
        guidance_map=full_guidance_map,
        based_contract_version=latest_contract.contract_version,
        accepted_default_revision=latest_default.default_revision,
        adaptation_state=STATE_CURRENT,
    )


def read_default(
    db: Session,
    snapshot: auth_service.AuthSnapshot,
    task_type: str,
) -> dict[str, Any]:
    """Admin default read (GET 路径): verify the trusted identity read,
    then require a real admin account. Returns the latest default under
    the latest contract together with that contract's field set."""
    account = ai_locks.verify_self_read(db, snapshot)
    ai_locks.require_admin(account)
    require_task_type(task_type)
    latest_contract = _latest_contract_row(db, task_type)
    if latest_contract is None:
        raise UnknownTaskType(f"任务 {task_type} 没有契约版本行")
    latest_default = _latest_default_row(
        db, task_type, latest_contract.contract_version, lock=None
    )
    if latest_default is None:
        raise UnknownTaskType(f"任务 {task_type} 没有匹配契约的默认修订")
    return dict(
        task_type=task_type,
        default_revision=latest_default.default_revision,
        contract_version=latest_contract.contract_version,
        guidance_fields=list(latest_contract.guidance_fields),
        guidance_map=dict(latest_default.guidance_map),
    )


def update_default(
    db: Session,
    snapshot: auth_service.AuthSnapshot,
    task_type: str,
    patch: dict[str, str],
    expected_default_revision: int,
) -> dict[str, Any]:
    """Admin default-guidance revision append (§4.2 / §7.3 / PF-1).

    Admin-only; contract/schema advancement stays in reviewed registry +
    migrations and is NOT reachable from this function. The new default
    revision keeps unselected fields from the current revision of the same
    contract. Audit target is school with ``target_version_after NULL``
    (PF-1); ``changed_fields`` records ONLY field names, never text.
    """
    require_task_type(task_type)
    _begin(db)
    try:
        account = ai_locks.lock_self(db, snapshot)
        ai_locks.require_admin(account)
        if (
            not isinstance(expected_default_revision, int)
            or isinstance(expected_default_revision, bool)
            or expected_default_revision < 1
        ):
            raise FieldViolation("expected_default_revision 必须是正整数修订号")
        if not isinstance(patch, dict) or not patch:
            raise FieldViolation("字段更新内容不能为空")
        # 契约无关 shape 检查提前；字段集在锚点锁内按最新 contract 校验。
        for name, value in patch.items():
            if not isinstance(name, str):
                raise FieldViolation("指导字段名必须是字符串")

        ai_locks.lock_contract_anchor(db, task_type, for_update=True)
        latest_contract = ai_locks.latest_contract_row_locked(
            db, task_type, share=False
        )
        # 管理员发布：默认行读取为排他 current locking read（R6），
        # 不可能因旧快照读出重复修订。
        latest_default = _latest_default_row(
            db, task_type, latest_contract.contract_version, lock="update"
        )
        if latest_default is None:
            raise UnknownTaskType(f"任务 {task_type} 没有匹配契约的默认修订")
        if expected_default_revision != latest_default.default_revision:
            raise auth_service.VersionConflict(
                f"expected_default_revision {expected_default_revision} "
                f"与当前 {latest_default.default_revision} 不一致"
            )
        # R2: 用最新目标 contract 的字段集验证 patch 与合成后映射。
        _validate_patch_for_fields(
            latest_contract.guidance_fields, list(patch.keys()),
            task_type=task_type,
        )
        for name, value in patch.items():
            if not isinstance(value, str):
                raise FieldViolation(f"指导字段 {name!r} 必须为字符串")
            if len(value) > MAX_GUIDANCE_FIELD_CHARS:
                raise FieldViolation(
                    f"指导字段 {name!r} 单字段长度不能超过 "
                    f"{MAX_GUIDANCE_FIELD_CHARS} 字符"
                )
        merged = dict(latest_default.guidance_map)
        merged.update(patch)
        merged = _validate_map_for_fields(
            latest_contract.guidance_fields, merged, task_type=task_type
        )

        new_revision = latest_default.default_revision + 1
        record = auth_service.record_operation(
            db,
            operator_id=account.id,
            operator_type="account",
            action="prompt_default_update",
            target_type="school",
            target_id="singleton",
            # PF-1: 默认发布不修改 school_settings.version，目标版本 NULL。
            target_version_after=None,
        )
        db.flush()
        new_default = PromptDefaultVersion(
            id=security.generate_id(),
            task_type=task_type,
            default_revision=new_revision,
            contract_version=latest_contract.contract_version,
            guidance_map=merged,
            created_by=account.id,
            created_at=_utc_now(),
        )
        db.add(new_default)
        db.flush()
        _add_event(
            db,
            operation_record_id=record.id,
            task_type=task_type,
            event_kind=EVENT_KIND_DEFAULT_UPDATE,
            personal_revision_before=None,
            personal_revision_after=None,
            default_revision_target=new_revision,
            contract_version_target=latest_contract.contract_version,
            changed_fields=list(patch.keys()),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return dict(
        task_type=task_type,
        default_revision=new_revision,
        contract_version=latest_contract.contract_version,
        guidance_fields=list(latest_contract.guidance_fields),
        guidance_map=merged,
    )
