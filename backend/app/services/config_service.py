"""Thin orchestration for I2 preview/confirm writes.

Flow:
1. Read phase in a SHORT-LIVED read-only session (attributes remain usable
   after close), so gathering never shares a transaction with the write.
2. Build phase with no database session open (pure builders; calendar is
   generated here).
3. Write phase in the request session: fixed lock order, FOR UPDATE current
   reads verify baselines/constraints, then persist the SAME candidate.

No module-level request state exists; ReadState/ChangePreview are local.

Lock order: operator account -> operator session -> school_settings
-> classes (ID order) -> terms (ID order) -> configuration_changes.
"""

from typing import Any

from sqlalchemy.orm import Session

from app import security
from app.database import get_sessionlocal
from app.models import ConfigurationChange
from app.services import auth_service
from app.services.config_builders_calendar import build_calendar_override
from app.services.config_builders_reimport import build_calendar_reimport
from app.services.config_builders_school import (
    build_class_create,
    build_class_update,
    build_school_update,
)
from app.services.config_builders_term import build_term_create
from app.services.config_builders_term_update import build_term_update
from app.services.config_errors import *  # noqa: F401,F403
from app.services.config_locks import (
    lock_change,
    lock_class,
    lock_school,
    lock_term,
    validate_admin_locked,
)
from app.services.config_normalize import *  # noqa: F401,F403
from app.services.config_preview import ChangePreview
from app.services.config_state import gather_read_state
from app.services.config_verify import verify_candidate

_BUILDERS = {
    "school_update": build_school_update,
    "class_create": build_class_create,
    "class_update": build_class_update,
    "term_create": build_term_create,
    "term_update": build_term_update,
    "calendar_override": build_calendar_override,
    "calendar_reimport": build_calendar_reimport,
}

_CLASS_KINDS = {"class_update"}
_TERM_KINDS = {"term_update", "calendar_override", "calendar_reimport"}


def create_preview(
    db: Session,
    snapshot: auth_service.AuthSnapshot,
    kind: str,
    proposal: dict[str, Any],
) -> ConfigurationChange:
    if snapshot.role != "admin":
        raise PreviewForbidden()
    if kind not in _BUILDERS:
        raise ValidationError("不支持的变更类型")

    # 1+2: read in a throwaway session, close it, then build with no DB open.
    with get_sessionlocal()() as ro:
        state = gather_read_state(ro, kind, proposal)
        ro.commit()  # expire_on_commit=False keeps attributes populated
    preview = _BUILDERS[kind](state, proposal)

    now = auth_service.utc_now()
    change_id = security.generate_id()

    # 3: write transaction.
    db.begin()
    admin = auth_service._lock_account(db, snapshot.account_id)
    validate_admin_locked(admin, snapshot)
    auth_service.validate_locked_session(db, snapshot)

    school = lock_school(db)
    locked_classes = _lock_classes(db, kind, preview.target_id)
    locked_terms = _lock_terms(db, kind, preview.target_id)

    verify_candidate(
        db, preview, school, locked_classes, locked_terms
    )

    row = ConfigurationChange(
        id=change_id,
        operator_id=snapshot.account_id,
        kind=kind,
        target_id=preview.target_id,
        normalized_proposal=preview.proposal,
        base_versions=preview.base_versions,
        result_versions=None,
        impact_summary={
            "changes": list(preview.changes),
            "impact": preview.impact,
            "blockers": list(preview.blockers),
        },
        status="pending",
        expires_at=now + PREVIEW_TTL,
        created_at=now,
    )
    db.add(row)
    db.commit()
    return row


def get_preview(
    db: Session, snapshot: auth_service.AuthSnapshot, change_id: str
) -> ConfigurationChange:
    row = db.get(ConfigurationChange, change_id)
    if row is None:
        raise PreviewNotFound()
    if row.operator_id != snapshot.account_id:
        raise PreviewForbidden()
    return row


def apply_preview(
    db: Session,
    snapshot: auth_service.AuthSnapshot,
    change_id: str,
) -> ConfigurationChange:
    if snapshot.role != "admin":
        raise PreviewForbidden()

    # Read once in a throwaway session for ownership/expiry only.
    with get_sessionlocal()() as ro:
        row = ro.get(ConfigurationChange, change_id)
        if row is None:
            raise PreviewNotFound()
        if row.operator_id != snapshot.account_id:
            raise PreviewForbidden()
        stored_kind = row.kind
        stored_target = row.target_id
        stored_status = row.status
        stored_expires = row.expires_at
        stored_proposal = row.normalized_proposal
        stored_base = row.base_versions
        stored_impact = row.impact_summary
        ro.commit()

    preview = ChangePreview(
        kind=stored_kind,
        target_id=stored_target,
        proposal=stored_proposal,
        base_versions=stored_base,
        changes=tuple(stored_impact.get("changes", [])),
        impact=stored_impact.get("impact", {}),
        blockers=tuple(stored_impact.get("blockers", [])),
    )

    now = auth_service.utc_now()
    db.begin()
    admin = auth_service._lock_account(db, snapshot.account_id)
    validate_admin_locked(admin, snapshot)
    auth_service.validate_locked_session(db, snapshot)

    school = lock_school(db)
    locked_classes = _lock_classes(db, stored_kind, stored_target)
    locked_terms = _lock_terms(db, stored_kind, stored_target)

    # Change row lock LAST in the order.
    locked_change = lock_change(db, change_id)

    # Applied status first (idempotent), then expiry, before product checks.
    if locked_change.status == "applied":
        db.commit()
        return locked_change
    if now > locked_change.expires_at:
        db.commit()
        raise PreviewExpired()

    # Saved blockers: a restricted operation can never be applied, even if
    # the blocker was captured at preview time.
    if "DEPENDENCY_NOT_READY" in preview.blockers:
        db.commit()
        raise DependencyNotReady()
    # A live plans_started gate also blocks every edit kind except creating
    # a new class/term (which is allowed after plans exist).
    if (
        school.plans_started_at is not None
        and stored_kind not in ("class_create", "term_create")
    ):
        db.commit()
        raise DependencyNotReady()

    verify_candidate(db, preview, school, locked_classes, locked_terms)

    from app.services.config_apply_pipeline import (
        dispatch_effect,
        reference_for,
        write_operation_record,
    )

    result = dispatch_effect(
        db, preview, school,
        now=now,
        operator_id=snapshot.account_id,
        change_id=change_id,
    )
    write_operation_record(
        db,
        preview=preview,
        result=result,
        operator_id=snapshot.account_id,
        now=now,
    )
    locked_change.result_reference = reference_for(stored_kind, result)
    locked_change.status = "applied"
    locked_change.applied_at = now
    locked_change.result_versions = result
    db.commit()
    return locked_change


def _lock_classes(db: Session, kind: str, target_id: str) -> dict:
    if kind not in _CLASS_KINDS:
        return {}
    return {target_id: lock_class(db, target_id)}


def _lock_terms(db: Session, kind: str, target_id: str) -> dict:
    if kind not in _TERM_KINDS:
        return {}
    return {target_id: lock_term(db, target_id)}
