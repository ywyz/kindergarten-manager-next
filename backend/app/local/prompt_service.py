"""D2 W2 local personal prompt service (engineering spec §5.1-§5.3).

Three daily tasks only. Reads never write a version. Every mutating action
(PATCH guidance / accept-default / reject-default / adapt) uses a global
``local_ai_operations`` receipt with a plain SHA-256 fingerprint (no secret
material is ever involved), so the same ``request_id`` returns the original
persisted result even when the expected revision or contract already moved.
A receipt key reused for a different operation domain or different content is
``AI_REQUEST_CONFLICT``.

Version rules:

* a no-content / already-applied action does not bump the personal revision;
* ``accept`` binds the actually viewed ``(contract_version, default_revision)``
  and overwrites only the selected fields; a later default for the same
  contract does not invalidate or apply that target;
* ``reject`` records the exact rejected revision, changes no guidance text and
  does not clear an outstanding contract adaptation;
* a required-contract upgrade never rewrites personal text (normal edits stay
  on the old contract); new fields use the target default and removed fields
  move to ``orphaned_guidance``; only an explicit ``adapt`` to the current
  required contract clears ``adaptation_required``.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ids import new_opaque_id
from app.local.base import utc_now
from app.local.errors import (
    LocalAiNotFound,
    LocalAiRequestConflict,
    LocalPromptAdaptationRequired,
    LocalPromptContractChanged,
    LocalPromptVersionConflict,
    LocalStorageError,
    LocalValidationError,
)
from app.local.models import (
    LocalAIOperation,
    LocalOperationRecord,
    LocalPersonalPromptHead,
    LocalPersonalPromptVersion,
    LocalPromptBundle,
)
from app.local.normalize import normalize_request_id
from app.local.profile_service import require_context
from app.local.prompt_bundles import (
    GUIDANCE_MAX_CHARS,
    TASK_TYPES,
    canonical_json,
)
from app.local.tx import begin_immediate, read_scope, rollback

OPERATION_EDIT = "ai_prompt_edit"
OPERATION_ACCEPT = "ai_prompt_accept"
OPERATION_REJECT = "ai_prompt_reject"
OPERATION_ADAPT = "ai_prompt_adapt"

_PROMPT_ACTIONS = (OPERATION_EDIT, OPERATION_ACCEPT, OPERATION_REJECT, OPERATION_ADAPT)


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------


def _normalize_task_type(value: object) -> str:
    if not isinstance(value, str) or value not in TASK_TYPES:
        raise LocalValidationError("不支持的日任务类型")
    return value


def _strict_positive_int(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise LocalValidationError(f"{name} 必须是 >= 1 的整数")
    return value


def _normalize_guidance_raw(value: object) -> dict[str, str]:
    """Structural guidance map check (field set is contract-checked later)."""
    if not isinstance(value, dict):
        raise LocalValidationError("guidance 必须是对象")
    normalized: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise LocalValidationError("指导字段名必须是字符串")
        if not isinstance(item, str):
            raise LocalValidationError(f"指导字段 {key} 必须是字符串")
        if len(item) > GUIDANCE_MAX_CHARS:
            raise LocalValidationError(
                f"指导字段 {key} 不能超过 {GUIDANCE_MAX_CHARS} 个字符"
            )
        normalized[key] = item
    return normalized


def _normalize_selected_fields(value: object) -> list[str]:
    if not isinstance(value, list) or not value:
        raise LocalValidationError("selected_fields 不能为空")
    seen: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise LocalValidationError("selected_fields 项必须是字符串")
        if item in seen:
            raise LocalValidationError("selected_fields 不能重复")
        seen.append(item)
    return seen


def _profile_id(session: Session) -> str:
    context = require_context(session, date.today())
    assert context.profile is not None
    return context.profile.id


def _head(
    session: Session, profile_id: str, task_type: str
) -> LocalPersonalPromptHead:
    head = session.get(LocalPersonalPromptHead, (profile_id, task_type))
    if head is None:
        raise LocalStorageError("个人指导头缺失")
    return head


def _version(
    session: Session, profile_id: str, task_type: str, revision: int
) -> LocalPersonalPromptVersion:
    version = session.get(
        LocalPersonalPromptVersion, (profile_id, task_type, revision)
    )
    if version is None:
        raise LocalStorageError("个人指导版本缺失")
    return version


def _bundle(
    session: Session, task_type: str, contract_version: int, default_revision: int
) -> LocalPromptBundle | None:
    return session.get(
        LocalPromptBundle, (task_type, contract_version, default_revision)
    )


def _require_bundle(
    session: Session, task_type: str, contract_version: int, default_revision: int
) -> LocalPromptBundle:
    bundle = _bundle(session, task_type, contract_version, default_revision)
    if bundle is None:
        raise LocalAiNotFound(
            details={
                "task_type": task_type,
                "contract_version": contract_version,
                "default_revision": default_revision,
            }
        )
    return bundle


def _bundle_fields(bundle: LocalPromptBundle) -> tuple[str, ...]:
    guidance = bundle.guidance_defaults_json
    if not isinstance(guidance, dict):
        raise LocalStorageError("提示词包默认指导损坏")
    return tuple(guidance.keys())


def _check_field_set(
    bundle: LocalPromptBundle, guidance: dict[str, str]
) -> None:
    expected = _bundle_fields(bundle)
    if sorted(guidance.keys()) != sorted(expected):
        raise LocalValidationError("guidance 字段集必须与目标契约完全一致")


def _fields(bundle: LocalPromptBundle) -> list[dict]:
    guidance = bundle.guidance_defaults_json
    return [
        {"key": key, "label": key, "default_text": guidance[key]}
        for key in guidance.keys()
    ]


def _merge_orphaned(
    stored: dict | None, active_fields, guidance: dict
) -> dict:
    """Merge a personal version's orphaned guidance with latest-wins semantics.

    Fields that are active in the current/target contract are dropped from the
    orphaned set (a re-added field is no longer orphaned). Every field present
    in ``guidance`` but not active is (re)written with its *current* value, so
    a field removed again after being re-added and edited keeps the latest
    teacher text instead of a stale first-removal copy. Historical version rows
    are never modified; only the newly written version's set is computed.
    """
    orphaned = dict(stored or {})
    active = set(active_fields)
    for key in list(orphaned.keys()):
        if key in active:
            del orphaned[key]
    for key, value in guidance.items():
        if key not in active:
            orphaned[key] = value
    return orphaned


def _prompt_out(
    session: Session,
    head: LocalPersonalPromptHead,
    version: LocalPersonalPromptVersion,
) -> dict:
    required = _require_bundle(
        session,
        head.task_type,
        head.required_contract_version,
        head.latest_default_revision,
    )
    required_fields = _bundle_fields(required)
    guidance = dict(version.guidance_json)
    # Fields the personal version still keeps but the required contract no
    # longer defines are surfaced as orphaned (never sent to the model); a
    # re-added field keeps its latest value, not a stale removal copy.
    orphaned = _merge_orphaned(
        version.orphaned_guidance_json, required_fields, guidance
    )
    return {
        "task_type": head.task_type,
        "personal_revision": head.current_revision,
        "contract_version": version.contract_version,
        "based_default_revision": version.based_default_revision,
        "required_contract_version": head.required_contract_version,
        "latest_default_revision": head.latest_default_revision,
        "guidance": guidance,
        "fields": _fields(required),
        "rejected_default_revision": version.rejected_default_revision,
        "adaptation_required": (
            version.contract_version != head.required_contract_version
        ),
        "orphaned_guidance": orphaned,
    }


# ---------------------------------------------------------------------------
# Receipts
# ---------------------------------------------------------------------------


def _find_receipt(
    session: Session, profile_id: str, request_id: str
) -> LocalAIOperation | None:
    return session.scalars(
        select(LocalAIOperation).where(
            LocalAIOperation.profile_id == profile_id,
            LocalAIOperation.request_id == request_id,
        )
    ).first()


def _fingerprint(operation_kind: str, payload: dict) -> str:
    import hashlib

    body = {"operation_kind": operation_kind, **payload}
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def _replay(receipt: LocalAIOperation, operation_kind: str, fingerprint: str) -> dict:
    if receipt.operation_kind != operation_kind:
        raise LocalAiRequestConflict(details={"expected_operation": receipt.operation_kind})
    if receipt.request_fingerprint != fingerprint:
        raise LocalAiRequestConflict()
    result = receipt.result_json
    if not isinstance(result, dict):
        raise LocalStorageError("提示词回执数据损坏")
    return dict(result)


def _store_receipt(
    session: Session,
    *,
    profile_id: str,
    request_id: str,
    operation_kind: str,
    fingerprint: str,
    result: dict,
    now,
) -> None:
    session.add(
        LocalAIOperation(
            id=new_opaque_id(),
            profile_id=profile_id,
            request_id=request_id,
            operation_kind=operation_kind,
            request_fingerprint=fingerprint,
            fingerprint_kind="sha256",
            fingerprint_key_id=None,
            result_json=result,
            created_at=now,
        )
    )
    session.add(
        LocalOperationRecord(
            id=new_opaque_id(),
            created_at=now,
            actor_id=profile_id,
            action="update_local_prompt",
            target_type="local_prompt",
            target_id=operation_kind,
            target_version_after=int(result.get("personal_revision", 1)),
        )
    )
    session.flush()


def _new_version(
    session: Session,
    *,
    profile_id: str,
    task_type: str,
    head: LocalPersonalPromptHead,
    action: str,
    contract_version: int,
    based_default_revision: int,
    guidance: dict,
    orphaned: dict | None,
    rejected_default_revision: int | None,
    now,
) -> LocalPersonalPromptVersion:
    revision = head.current_revision + 1
    version = LocalPersonalPromptVersion(
        profile_id=profile_id,
        task_type=task_type,
        revision=revision,
        contract_version=contract_version,
        based_default_revision=based_default_revision,
        guidance_json=guidance,
        orphaned_guidance_json=orphaned,
        action=action,
        rejected_default_revision=rejected_default_revision,
        created_at=now,
    )
    session.add(version)
    head.current_revision = revision
    head.updated_at = now
    return version


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def list_prompts(session: Session) -> dict:
    with read_scope(session):
        profile_id = _profile_id(session)
        items = []
        for task_type in TASK_TYPES:
            head = _head(session, profile_id, task_type)
            version = _version(session, profile_id, task_type, head.current_revision)
            items.append(_prompt_out(session, head, version))
        return {"items": items}


def get_prompt(session: Session, *, task_type: object) -> dict:
    tt = _normalize_task_type(task_type)
    with read_scope(session):
        profile_id = _profile_id(session)
        head = _head(session, profile_id, tt)
        version = _version(session, profile_id, tt, head.current_revision)
        return _prompt_out(session, head, version)


def get_default(
    session: Session,
    *,
    task_type: object,
    contract_version: object,
    default_revision: object,
) -> dict:
    tt = _normalize_task_type(task_type)
    contract = _strict_positive_int(contract_version, "contract_version")
    default = _strict_positive_int(default_revision, "default_revision")
    with read_scope(session):
        _profile_id(session)
        bundle = _require_bundle(session, tt, contract, default)
        return {
            "task_type": tt,
            "contract_version": contract,
            "default_revision": default,
            "guidance": dict(bundle.guidance_defaults_json),
            "fields": _fields(bundle),
            "bundle_hash": bundle.bundle_hash,
        }


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


def _load_head_version(session: Session, profile_id: str, task_type: str):
    head = _head(session, profile_id, task_type)
    version = _version(session, profile_id, task_type, head.current_revision)
    return head, version


def save_prompt(
    session: Session,
    *,
    task_type: object,
    expected_personal_revision: object,
    contract_version: object,
    guidance: object,
    request_id: object,
) -> dict:
    """PATCH /api/local/ai/prompts/{task_type}: full current-contract map."""
    tt = _normalize_task_type(task_type)
    expected = _strict_positive_int(
        expected_personal_revision, "expected_personal_revision"
    )
    contract = _strict_positive_int(contract_version, "contract_version")
    normalized = _normalize_guidance_raw(guidance)
    rid = normalize_request_id(request_id)
    fingerprint = _fingerprint(
        OPERATION_EDIT,
        {
            "task_type": tt,
            "expected_personal_revision": expected,
            "contract_version": contract,
            "guidance": normalized,
        },
    )

    with read_scope(session):
        profile_id = _profile_id(session)
        receipt = _find_receipt(session, profile_id, rid)
        if receipt is not None:
            return _replay(receipt, OPERATION_EDIT, fingerprint)

    begin_immediate(session)
    try:
        profile_id = _profile_id(session)
        receipt = _find_receipt(session, profile_id, rid)
        if receipt is not None:
            result = _replay(receipt, OPERATION_EDIT, fingerprint)
            rollback(session)
            return result
        head, version = _load_head_version(session, profile_id, tt)
        if head.current_revision != expected:
            raise LocalPromptVersionConflict(
                details={"personal_revision": head.current_revision}
            )
        if contract != version.contract_version:
            if contract == head.required_contract_version:
                raise LocalPromptAdaptationRequired()
            raise LocalPromptContractChanged(
                details={"contract_version": version.contract_version}
            )
        bundle = _require_bundle(
            session, tt, version.contract_version, version.based_default_revision
        )
        _check_field_set(bundle, normalized)
        now = utc_now()
        if normalized == dict(version.guidance_json):
            result = _prompt_out(session, head, version)
        else:
            new_version = _new_version(
                session,
                profile_id=profile_id,
                task_type=tt,
                head=head,
                action="edit",
                contract_version=version.contract_version,
                based_default_revision=version.based_default_revision,
                guidance=normalized,
                orphaned=_merge_orphaned(
                    version.orphaned_guidance_json,
                    _bundle_fields(bundle),
                    normalized,
                ),
                rejected_default_revision=version.rejected_default_revision,
                now=now,
            )
            result = _prompt_out(session, head, new_version)
        _store_receipt(
            session,
            profile_id=profile_id,
            request_id=rid,
            operation_kind=OPERATION_EDIT,
            fingerprint=fingerprint,
            result=result,
            now=now,
        )
        session.commit()
    except BaseException:
        rollback(session)
        raise
    return result


def _require_same_required_contract(
    head: LocalPersonalPromptHead, version: LocalPersonalPromptVersion, target_contract: int
) -> None:
    """Accept/reject only apply to the contract the person and app agree on."""
    if version.contract_version != head.required_contract_version:
        raise LocalPromptAdaptationRequired()
    if target_contract != head.required_contract_version:
        raise LocalPromptContractChanged(
            details={"required_contract_version": head.required_contract_version}
        )


def accept_default(
    session: Session,
    *,
    task_type: object,
    expected_personal_revision: object,
    target_contract_version: object,
    target_default_revision: object,
    selected_fields: object,
    request_id: object,
) -> dict:
    tt = _normalize_task_type(task_type)
    expected = _strict_positive_int(
        expected_personal_revision, "expected_personal_revision"
    )
    target_contract = _strict_positive_int(
        target_contract_version, "target_contract_version"
    )
    target_default = _strict_positive_int(
        target_default_revision, "target_default_revision"
    )
    fields = _normalize_selected_fields(selected_fields)
    rid = normalize_request_id(request_id)
    fingerprint = _fingerprint(
        OPERATION_ACCEPT,
        {
            "task_type": tt,
            "expected_personal_revision": expected,
            "target_contract_version": target_contract,
            "target_default_revision": target_default,
            "selected_fields": fields,
        },
    )

    with read_scope(session):
        profile_id = _profile_id(session)
        receipt = _find_receipt(session, profile_id, rid)
        if receipt is not None:
            return _replay(receipt, OPERATION_ACCEPT, fingerprint)

    begin_immediate(session)
    try:
        profile_id = _profile_id(session)
        receipt = _find_receipt(session, profile_id, rid)
        if receipt is not None:
            result = _replay(receipt, OPERATION_ACCEPT, fingerprint)
            rollback(session)
            return result
        head, version = _load_head_version(session, profile_id, tt)
        if head.current_revision != expected:
            raise LocalPromptVersionConflict(
                details={"personal_revision": head.current_revision}
            )
        _require_same_required_contract(head, version, target_contract)
        bundle = _require_bundle(session, tt, target_contract, target_default)
        allowed = _bundle_fields(bundle)
        for field in fields:
            if field not in allowed:
                raise LocalValidationError(f"未知指导字段 {field}")
        defaults = bundle.guidance_defaults_json
        new_guidance = dict(version.guidance_json)
        for field in fields:
            new_guidance[field] = defaults[field]
        now = utc_now()
        if (
            new_guidance == dict(version.guidance_json)
            and version.based_default_revision == target_default
        ):
            result = _prompt_out(session, head, version)
        else:
            new_version = _new_version(
                session,
                profile_id=profile_id,
                task_type=tt,
                head=head,
                action="accept",
                contract_version=version.contract_version,
                based_default_revision=target_default,
                guidance=new_guidance,
                orphaned=_merge_orphaned(
                    version.orphaned_guidance_json, allowed, new_guidance
                ),
                rejected_default_revision=version.rejected_default_revision,
                now=now,
            )
            result = _prompt_out(session, head, new_version)
        _store_receipt(
            session,
            profile_id=profile_id,
            request_id=rid,
            operation_kind=OPERATION_ACCEPT,
            fingerprint=fingerprint,
            result=result,
            now=now,
        )
        session.commit()
    except BaseException:
        rollback(session)
        raise
    return result


def reject_default(
    session: Session,
    *,
    task_type: object,
    expected_personal_revision: object,
    target_contract_version: object,
    target_default_revision: object,
    request_id: object,
) -> dict:
    tt = _normalize_task_type(task_type)
    expected = _strict_positive_int(
        expected_personal_revision, "expected_personal_revision"
    )
    target_contract = _strict_positive_int(
        target_contract_version, "target_contract_version"
    )
    target_default = _strict_positive_int(
        target_default_revision, "target_default_revision"
    )
    rid = normalize_request_id(request_id)
    fingerprint = _fingerprint(
        OPERATION_REJECT,
        {
            "task_type": tt,
            "expected_personal_revision": expected,
            "target_contract_version": target_contract,
            "target_default_revision": target_default,
        },
    )

    with read_scope(session):
        profile_id = _profile_id(session)
        receipt = _find_receipt(session, profile_id, rid)
        if receipt is not None:
            return _replay(receipt, OPERATION_REJECT, fingerprint)

    begin_immediate(session)
    try:
        profile_id = _profile_id(session)
        receipt = _find_receipt(session, profile_id, rid)
        if receipt is not None:
            result = _replay(receipt, OPERATION_REJECT, fingerprint)
            rollback(session)
            return result
        head, version = _load_head_version(session, profile_id, tt)
        if head.current_revision != expected:
            raise LocalPromptVersionConflict(
                details={"personal_revision": head.current_revision}
            )
        _require_same_required_contract(head, version, target_contract)
        bundle = _require_bundle(session, tt, target_contract, target_default)
        now = utc_now()
        if version.rejected_default_revision == target_default:
            result = _prompt_out(session, head, version)
        else:
            new_version = _new_version(
                session,
                profile_id=profile_id,
                task_type=tt,
                head=head,
                action="reject",
                contract_version=version.contract_version,
                based_default_revision=version.based_default_revision,
                guidance=dict(version.guidance_json),
                orphaned=_merge_orphaned(
                    version.orphaned_guidance_json,
                    _bundle_fields(bundle),
                    dict(version.guidance_json),
                ),
                rejected_default_revision=target_default,
                now=now,
            )
            result = _prompt_out(session, head, new_version)
        _store_receipt(
            session,
            profile_id=profile_id,
            request_id=rid,
            operation_kind=OPERATION_REJECT,
            fingerprint=fingerprint,
            result=result,
            now=now,
        )
        session.commit()
    except BaseException:
        rollback(session)
        raise
    return result


def adapt_prompt(
    session: Session,
    *,
    task_type: object,
    expected_personal_revision: object,
    target_contract_version: object,
    target_default_revision: object,
    guidance: object,
    request_id: object,
) -> dict:
    tt = _normalize_task_type(task_type)
    expected = _strict_positive_int(
        expected_personal_revision, "expected_personal_revision"
    )
    target_contract = _strict_positive_int(
        target_contract_version, "target_contract_version"
    )
    target_default = _strict_positive_int(
        target_default_revision, "target_default_revision"
    )
    normalized = _normalize_guidance_raw(guidance)
    rid = normalize_request_id(request_id)
    fingerprint = _fingerprint(
        OPERATION_ADAPT,
        {
            "task_type": tt,
            "expected_personal_revision": expected,
            "target_contract_version": target_contract,
            "target_default_revision": target_default,
            "guidance": normalized,
        },
    )

    with read_scope(session):
        profile_id = _profile_id(session)
        receipt = _find_receipt(session, profile_id, rid)
        if receipt is not None:
            return _replay(receipt, OPERATION_ADAPT, fingerprint)

    begin_immediate(session)
    try:
        profile_id = _profile_id(session)
        receipt = _find_receipt(session, profile_id, rid)
        if receipt is not None:
            result = _replay(receipt, OPERATION_ADAPT, fingerprint)
            rollback(session)
            return result
        head, version = _load_head_version(session, profile_id, tt)
        if head.current_revision != expected:
            raise LocalPromptVersionConflict(
                details={"personal_revision": head.current_revision}
            )
        if target_contract != head.required_contract_version:
            raise LocalPromptContractChanged(
                details={"required_contract_version": head.required_contract_version}
            )
        bundle = _require_bundle(session, tt, target_contract, target_default)
        _check_field_set(bundle, normalized)
        new_fields = set(_bundle_fields(bundle))
        orphaned = _merge_orphaned(
            version.orphaned_guidance_json,
            new_fields,
            dict(version.guidance_json),
        )
        now = utc_now()
        if (
            version.contract_version == target_contract
            and normalized == dict(version.guidance_json)
        ):
            result = _prompt_out(session, head, version)
        else:
            # A contract change cannot carry a rejection from another contract
            # (the composite FK pins the rejected revision to the row contract).
            rejected = (
                version.rejected_default_revision
                if version.contract_version == target_contract
                else None
            )
            new_version = _new_version(
                session,
                profile_id=profile_id,
                task_type=tt,
                head=head,
                action="adapt",
                contract_version=target_contract,
                based_default_revision=target_default,
                guidance=normalized,
                orphaned=orphaned or None,
                rejected_default_revision=rejected,
                now=now,
            )
            result = _prompt_out(session, head, new_version)
        _store_receipt(
            session,
            profile_id=profile_id,
            request_id=rid,
            operation_kind=OPERATION_ADAPT,
            fingerprint=fingerprint,
            result=result,
            now=now,
        )
        session.commit()
    except BaseException:
        rollback(session)
        raise
    return result
