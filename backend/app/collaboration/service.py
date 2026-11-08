"""Business transactions for the online collaboration slice.

Every write follows one lock order: teacher row(s) in UUID order, then the
class row, then the target configuration row.  Read-only previews do not
write or lock.  This prevents cross-class writes and deadlocks while making
membership and source-version rechecks transactionally authoritative.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import and_, select
from sqlalchemy.orm import Session, aliased

from app.local.config_service import normalize_change
from app.local.errors import LocalValidationError
from app.local.schemas import ConfigClassGamesChangeIn

from .class_promotion_models import (
    effective_class_name_now,
    effective_class_names_now,
)
from .config import CollaborationSettings
from .errors import (
    auth_required,
    class_not_found,
    invalid_config,
    membership_changed,
    membership_required,
    operation_not_found,
    preview_binding_mismatch,
    preview_expired,
    request_conflict,
    source_config_missing,
    source_not_available,
    source_version_changed,
    target_version_changed,
)
from .models import (
    Classroom,
    CollaborationOperation,
    Teacher,
    TeacherClassMembership,
    TeacherGameConfig,
)
from .schemas import (
    ClassmateOut,
    ClassOut,
    ConfigConfirmIn,
    ConfigConfirmOut,
    ConfigCurrentOut,
    ConfigPreviewIn,
    ConfigPreviewOut,
    ConfigSaveIn,
    ConfigSaveOut,
    GameConfigDiff,
    GameConfigPayload,
    LocationsDiff,
    MembershipOut,
    OperationOut,
    TeacherOut,
    TextFieldDiff,
)
from .security import (
    PreviewClaims,
    TeacherPrincipal,
    issue_preview_token,
    read_preview_token,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _empty_payload() -> dict:
    return {"locations": [], "game_scope": None, "guidance": None}


def _game_payload(normalized: dict) -> dict:
    return {
        "locations": list(normalized.get("locations") or []),
        "game_scope": normalized.get("game_scope"),
        "guidance": normalized.get("guidance"),
    }


def normalize_class_games(change: ConfigClassGamesChangeIn) -> dict:
    if change.kind != "class_games":
        raise invalid_config("只接受班级游戏配置")
    try:
        normalized = normalize_change(change.model_dump(mode="python"))
    except LocalValidationError as exc:
        raise invalid_config(str(exc)) from None
    return _game_payload(normalized)


def _payload_hash(payload: dict) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _fingerprint(value: dict) -> str:
    return _payload_hash(value)


def _validated_payload(payload: dict) -> GameConfigPayload:
    return GameConfigPayload.model_validate(payload)


def build_diff(source: dict, target: dict) -> GameConfigDiff:
    source_locations = list(source.get("locations") or [])
    target_locations = list(target.get("locations") or [])
    source_scope = source.get("game_scope")
    target_scope = target.get("game_scope")
    source_guidance = source.get("guidance")
    target_guidance = target.get("guidance")
    locations_changed = source_locations != target_locations
    scope_changed = source_scope != target_scope
    guidance_changed = source_guidance != target_guidance
    return GameConfigDiff(
        locations=LocationsDiff(
            source=source_locations,
            target=target_locations,
            changed=locations_changed,
        ),
        game_scope=TextFieldDiff(
            source=source_scope,
            target=target_scope,
            changed=scope_changed,
        ),
        guidance=TextFieldDiff(
            source=source_guidance,
            target=target_guidance,
            changed=guidance_changed,
        ),
        changed=locations_changed or scope_changed or guidance_changed,
    )


def _lock_teachers(
    session: Session, teacher_ids: list[UUID]
) -> dict[UUID, Teacher]:
    ids = sorted(set(teacher_ids))
    rows = session.scalars(
        select(Teacher)
        .where(Teacher.id.in_(ids))
        .order_by(Teacher.id)
        .with_for_update()
    ).all()
    by_id = {row.id: row for row in rows}
    if len(by_id) != len(ids):
        raise membership_changed()
    return by_id


def _lock_class(
    session: Session, school_id: UUID, class_id: UUID
) -> Classroom:
    row = session.scalars(
        select(Classroom)
        .where(
            Classroom.id == class_id,
            Classroom.school_id == school_id,
        )
        .with_for_update()
    ).one_or_none()
    if row is None:
        raise class_not_found()
    return row


def _membership(
    session: Session, teacher_id: UUID
) -> TeacherClassMembership | None:
    return session.scalars(
        select(TeacherClassMembership).where(
            TeacherClassMembership.teacher_id == teacher_id
        )
    ).one_or_none()


def _require_membership(
    session: Session,
    principal: TeacherPrincipal,
    *,
    class_id: UUID | None = None,
) -> TeacherClassMembership:
    membership = _membership(session, principal.teacher_id)
    if membership is None:
        raise membership_required()
    if membership.school_id != principal.school_id:
        raise membership_changed()
    if class_id is not None and membership.class_id != class_id:
        raise membership_changed()
    return membership


def get_me(principal: TeacherPrincipal) -> TeacherOut:
    return TeacherOut(
        teacher_id=principal.teacher_id,
        display_name=principal.display_name,
        school_id=principal.school_id,
        school_name=principal.school_name,
    )


def list_classes(
    session: Session, principal: TeacherPrincipal
) -> list[ClassOut]:
    rows = session.scalars(
        select(Classroom).where(
            Classroom.school_id == principal.school_id
        )
    ).all()
    names = effective_class_names_now(session, [row.id for row in rows])
    items = [
        ClassOut(
            class_id=row.id,
            display_name=names.get(row.id, row.display_name),
        )
        for row in rows
    ]
    items.sort(key=lambda item: (item.display_name, item.class_id))
    return items


def current_membership(
    session: Session, principal: TeacherPrincipal
) -> MembershipOut | None:
    # Read the membership and stable class ID together, then resolve the
    # promotion-aware display name from that stable ID.
    actor = aliased(TeacherClassMembership)
    row = session.execute(
        select(actor, Classroom)
        .select_from(actor)
        .outerjoin(
            Classroom,
            and_(
                Classroom.id == actor.class_id,
                Classroom.school_id == actor.school_id,
            ),
        )
        .where(actor.teacher_id == principal.teacher_id)
    ).one_or_none()
    if row is None:
        return None
    actor_row, class_row = row
    if (
        actor_row.school_id != principal.school_id
        or class_row is None
    ):
        raise membership_changed()
    return MembershipOut(
        teacher_id=principal.teacher_id,
        school_id=principal.school_id,
        class_id=actor_row.class_id,
        class_name=effective_class_name_now(
            session, class_row.id, class_row.display_name
        ),
        selected_at=actor_row.selected_at,
    )


def select_class(
    session: Session, principal: TeacherPrincipal, class_id: UUID
) -> MembershipOut:
    with session.begin():
        _lock_teachers(session, [principal.teacher_id])
        class_row = _lock_class(session, principal.school_id, class_id)
        membership = _membership(session, principal.teacher_id)
        now = _utcnow()
        if membership is None:
            membership = TeacherClassMembership(
                teacher_id=principal.teacher_id,
                school_id=principal.school_id,
                class_id=class_id,
                membership_generation=uuid4(),
                selected_at=now,
                updated_at=now,
            )
            session.add(membership)
        else:
            if (
                membership.school_id != principal.school_id
                or membership.class_id != class_id
            ):
                # A real switch invalidates every outstanding preview.  A
                # repeated selection of the same class keeps its generation.
                membership.membership_generation = uuid4()
            membership.school_id = principal.school_id
            membership.class_id = class_id
            membership.selected_at = now
            membership.updated_at = now
        session.flush()
        return MembershipOut(
            teacher_id=principal.teacher_id,
            school_id=principal.school_id,
            class_id=class_id,
            class_name=effective_class_name_now(
                session, class_row.id, class_row.display_name
            ),
            selected_at=membership.selected_at,
        )


def leave_current_class(
    session: Session, principal: TeacherPrincipal
) -> None:
    with session.begin():
        _lock_teachers(session, [principal.teacher_id])
        membership = _membership(session, principal.teacher_id)
        if membership is None:
            return
        _lock_class(
            session,
            membership.school_id,
            membership.class_id,
        )
        session.delete(membership)
        session.flush()


def list_classmates(
    session: Session, principal: TeacherPrincipal
) -> list[ClassmateOut]:
    # The actor membership and every returned classmate/config row come from
    # one statement, so a page read cannot mix old and new classes.
    actor = aliased(TeacherClassMembership)
    classmate = aliased(TeacherClassMembership)
    rows = session.execute(
        select(
            actor,
            Teacher,
            TeacherGameConfig.version,
            TeacherGameConfig.updated_at,
        )
        .select_from(actor)
        .outerjoin(
            classmate,
            and_(
                classmate.school_id == actor.school_id,
                classmate.class_id == actor.class_id,
                classmate.teacher_id != actor.teacher_id,
            ),
        )
        .outerjoin(
            Teacher,
            and_(
                Teacher.id == classmate.teacher_id,
                Teacher.school_id == actor.school_id,
                Teacher.active.is_(True),
            ),
        )
        .outerjoin(
            TeacherGameConfig,
            and_(
                TeacherGameConfig.teacher_id == Teacher.id,
                TeacherGameConfig.school_id == actor.school_id,
                TeacherGameConfig.class_id == actor.class_id,
            ),
        )
        .where(actor.teacher_id == principal.teacher_id)
        .order_by(Teacher.display_name, Teacher.id)
    ).all()
    if not rows:
        raise membership_required()
    actor_row = rows[0][0]
    if actor_row.school_id != principal.school_id:
        raise membership_changed()
    return [
        ClassmateOut(
            teacher_id=teacher.id,
            display_name=teacher.display_name,
            config_version=int(version or 0),
            config_updated_at=updated_at,
        )
        for _, teacher, version, updated_at in rows
        if teacher is not None
    ]


def get_own_config(
    session: Session, principal: TeacherPrincipal
) -> ConfigCurrentOut:
    # One statement keeps the current membership and own config/version in
    # the same snapshot (a concurrent switch cannot pair old class metadata
    # with another class's row).
    actor = aliased(TeacherClassMembership)
    own = aliased(TeacherGameConfig)
    row = session.execute(
        select(actor, own)
        .select_from(actor)
        .outerjoin(
            own,
            and_(
                own.teacher_id == actor.teacher_id,
                own.school_id == actor.school_id,
                own.class_id == actor.class_id,
            ),
        )
        .where(actor.teacher_id == principal.teacher_id)
    ).one_or_none()
    if row is None:
        raise membership_required()
    actor_row, own_row = row
    if actor_row.school_id != principal.school_id:
        raise membership_changed()
    if own_row is None:
        return ConfigCurrentOut(
            class_id=actor_row.class_id,
            config_version=0,
            payload=_validated_payload(_empty_payload()),
        )
    return ConfigCurrentOut(
        class_id=actor_row.class_id,
        config_version=own_row.version,
        payload=_validated_payload(own_row.payload),
    )


def _save_fingerprint(
    school_id: UUID,
    class_id: UUID,
    expected_version: int,
    payload: dict,
) -> str:
    return _fingerprint(
        {
            "kind": "save",
            "school_id": str(school_id),
            "class_id": str(class_id),
            "expected_version": int(expected_version),
            "change": payload,
        }
    )


def _import_fingerprint(claims: PreviewClaims) -> str:
    return _fingerprint(
        {
            "kind": "import",
            "request_id": str(claims.request_id),
            "actor_teacher_id": str(claims.actor_teacher_id),
            "school_id": str(claims.school_id),
            "class_id": str(claims.class_id),
            "actor_membership_generation": str(
                claims.actor_membership_generation
            ),
            "source_membership_generation": str(
                claims.source_membership_generation
            ),
            "source_teacher_id": str(claims.source_teacher_id),
            "source_version": claims.source_version,
            "target_version": claims.target_version,
        }
    )


def _operation(
    session: Session,
    principal: TeacherPrincipal,
    request_id: UUID,
) -> CollaborationOperation | None:
    return session.scalars(
        select(CollaborationOperation)
        .where(
            CollaborationOperation.actor_teacher_id == principal.teacher_id,
            CollaborationOperation.request_id == request_id,
        )
        .with_for_update()
    ).one_or_none()


def _add_operation(
    session: Session,
    *,
    principal: TeacherPrincipal,
    class_id: UUID,
    request_id: UUID,
    kind: str,
    fingerprint: str,
    result: dict,
    source_teacher_id: UUID | None = None,
    source_version: int | None = None,
    target_version: int | None = None,
) -> None:
    session.add(
        CollaborationOperation(
            actor_teacher_id=principal.teacher_id,
            request_id=request_id,
            school_id=principal.school_id,
            class_id=class_id,
            kind=kind,
            request_fingerprint=fingerprint,
            source_teacher_id=source_teacher_id,
            source_version=source_version,
            target_version=target_version,
            result_json=result,
        )
    )


def _replayed_save(result: dict) -> ConfigSaveOut:
    value = dict(result)
    value["replayed"] = True
    return ConfigSaveOut.model_validate(value)


def _replayed_import(result: dict) -> ConfigConfirmOut:
    value = dict(result)
    value["replayed"] = True
    return ConfigConfirmOut.model_validate(value)


def save_config(
    session: Session,
    principal: TeacherPrincipal,
    data: ConfigSaveIn,
) -> ConfigSaveOut:
    payload = normalize_class_games(data.change)
    fingerprint = _save_fingerprint(
        principal.school_id,
        data.class_id,
        data.expected_version,
        payload,
    )
    with session.begin():
        _lock_teachers(session, [principal.teacher_id])
        membership = _require_membership(
            session,
            principal,
            class_id=data.class_id,
        )
        _lock_class(session, principal.school_id, data.class_id)
        existing_operation = _operation(session, principal, data.request_id)
        if existing_operation is not None:
            if (
                existing_operation.request_fingerprint != fingerprint
                or existing_operation.class_id != data.class_id
                or existing_operation.school_id != principal.school_id
            ):
                raise request_conflict()
            return _replayed_save(existing_operation.result_json)
        row = session.scalars(
            select(TeacherGameConfig)
            .where(
                TeacherGameConfig.teacher_id == principal.teacher_id,
                TeacherGameConfig.school_id == principal.school_id,
                TeacherGameConfig.class_id == data.class_id,
            )
            .with_for_update()
        ).one_or_none()
        current_version = row.version if row is not None else 0
        if data.expected_version != current_version:
            raise target_version_changed(current_version)
        new_hash = _payload_hash(payload)
        changed = row is None or row.payload_hash != new_hash
        if changed:
            new_version = current_version + 1
            if row is None:
                row = TeacherGameConfig(
                    teacher_id=principal.teacher_id,
                    school_id=principal.school_id,
                    class_id=data.class_id,
                    version=new_version,
                    payload=payload,
                    payload_hash=new_hash,
                    updated_at=_utcnow(),
                )
                session.add(row)
            else:
                row.version = new_version
                row.payload = payload
                row.payload_hash = new_hash
                row.updated_at = _utcnow()
        else:
            new_version = current_version
        result = ConfigSaveOut(
            request_id=data.request_id,
            class_id=data.class_id,
            config_version=new_version,
            changed=changed,
            payload=_validated_payload(payload),
        )
        _add_operation(
            session,
            principal=principal,
            class_id=data.class_id,
            request_id=data.request_id,
            kind="save",
            fingerprint=fingerprint,
            result=result.model_dump(mode="json"),
            target_version=current_version,
        )
        session.flush()
        return result


def preview_import(
    session: Session,
    principal: TeacherPrincipal,
    data: ConfigPreviewIn,
    settings: CollaborationSettings,
) -> ConfigPreviewOut:
    if data.source_teacher_id == principal.teacher_id:
        raise source_not_available()

    # One SQL statement gives this preview a single MVCC snapshot: actor
    # membership, source membership, source teacher, source config and own
    # config cannot come from mutually exclusive moments.  No lock is needed
    # because preview is read-only; confirm rechecks everything under locks.
    actor_membership = aliased(TeacherClassMembership)
    source_membership = aliased(TeacherClassMembership)
    source_config = aliased(TeacherGameConfig)
    own_config = aliased(TeacherGameConfig)
    row = session.execute(
        select(
            actor_membership,
            source_membership,
            Teacher,
            source_config,
            own_config,
        )
        .select_from(actor_membership)
        .outerjoin(
            source_membership,
            and_(
                source_membership.teacher_id == data.source_teacher_id,
                source_membership.school_id == actor_membership.school_id,
                source_membership.class_id == actor_membership.class_id,
            ),
        )
        .outerjoin(
            Teacher,
            and_(
                Teacher.id == source_membership.teacher_id,
                Teacher.school_id == actor_membership.school_id,
                Teacher.active.is_(True),
            ),
        )
        .outerjoin(
            source_config,
            and_(
                source_config.teacher_id == source_membership.teacher_id,
                source_config.school_id == actor_membership.school_id,
                source_config.class_id == actor_membership.class_id,
            ),
        )
        .outerjoin(
            own_config,
            and_(
                own_config.teacher_id == actor_membership.teacher_id,
                own_config.school_id == actor_membership.school_id,
                own_config.class_id == actor_membership.class_id,
            ),
        )
        .where(actor_membership.teacher_id == principal.teacher_id)
    ).one_or_none()
    if row is None:
        raise membership_required()
    (
        actor_membership_row,
        source_membership_row,
        source_teacher_row,
        source_config_row,
        own_config_row,
    ) = row
    if (
        actor_membership_row.school_id != principal.school_id
        or actor_membership_row.class_id != data.class_id
    ):
        raise membership_changed()
    if (
        source_membership_row is None
        or source_membership_row.school_id != principal.school_id
        or source_membership_row.class_id != data.class_id
        or source_teacher_row is None
    ):
        raise source_not_available()
    if source_config_row is None:
        raise source_config_missing()

    source_payload = _validated_payload(
        source_config_row.payload
    ).model_dump(mode="python")
    target_payload = _validated_payload(
        own_config_row.payload if own_config_row is not None else _empty_payload()
    ).model_dump(mode="python")
    target_version = own_config_row.version if own_config_row is not None else 0
    token, expires_at = issue_preview_token(
        secret=settings.preview_secret,
        request_id=data.request_id,
        actor_teacher_id=principal.teacher_id,
        school_id=principal.school_id,
        class_id=data.class_id,
        actor_membership_generation=actor_membership_row.membership_generation,
        source_membership_generation=source_membership_row.membership_generation,
        source_teacher_id=source_teacher_row.id,
        source_version=source_config_row.version,
        target_version=target_version,
        ttl_seconds=settings.preview_ttl_seconds,
    )
    return ConfigPreviewOut(
        request_id=data.request_id,
        preview_token=token,
        expires_at=expires_at,
        class_id=data.class_id,
        source_teacher_id=source_teacher_row.id,
        source_teacher_name=source_teacher_row.display_name,
        source_version=source_config_row.version,
        target_version=target_version,
        source_payload=_validated_payload(source_payload),
        target_payload=_validated_payload(target_payload),
        diff=build_diff(source_payload, target_payload),
    )


def confirm_import(
    session: Session,
    principal: TeacherPrincipal,
    data: ConfigConfirmIn,
    settings: CollaborationSettings,
) -> ConfigConfirmOut:
    claims = read_preview_token(
        secret=settings.preview_secret,
        token=data.preview_token,
        allow_expired=True,
    )
    if (
        claims.request_id != data.request_id
        or claims.actor_teacher_id != principal.teacher_id
        or claims.school_id != principal.school_id
        or claims.source_teacher_id != data.source_teacher_id
        or claims.source_version != data.source_version
        or claims.target_version != data.target_version
    ):
        raise preview_binding_mismatch()
    fingerprint = _import_fingerprint(claims)
    if claims.source_teacher_id == principal.teacher_id:
        raise source_not_available()
    with session.begin():
        teachers = _lock_teachers(
            session,
            [principal.teacher_id, claims.source_teacher_id],
        )
        _lock_class(session, principal.school_id, claims.class_id)

        # A committed receipt may be replayed even after a switch/expiry;
        # it is not a new write.  New confirms must pass every live check
        # below before the target row is touched.
        existing_operation = _operation(
            session, principal, data.request_id
        )
        if existing_operation is not None:
            if (
                existing_operation.request_fingerprint != fingerprint
                or existing_operation.class_id != claims.class_id
                or existing_operation.school_id != principal.school_id
            ):
                raise request_conflict()
            return _replayed_import(existing_operation.result_json)

        actor_teacher = teachers[principal.teacher_id]
        source_teacher = teachers[claims.source_teacher_id]
        if not actor_teacher.active:
            raise auth_required()
        if not source_teacher.active:
            raise source_not_available()
        if (
            actor_teacher.school_id != principal.school_id
            or source_teacher.school_id != principal.school_id
        ):
            raise membership_changed()

        actor_membership = _membership(session, principal.teacher_id)
        source_membership = _membership(session, claims.source_teacher_id)
        if (
            actor_membership is None
            or actor_membership.school_id != principal.school_id
            or actor_membership.class_id != claims.class_id
            or actor_membership.membership_generation
            != claims.actor_membership_generation
            or source_membership is None
            or source_membership.school_id != principal.school_id
            or source_membership.class_id != claims.class_id
            or source_membership.membership_generation
            != claims.source_membership_generation
        ):
            raise membership_changed()

        # The preview is valid strictly before expires_at.  A receipt replay
        # above is intentionally exempt, because it writes nothing.
        if int(time.time()) >= claims.expires_at:
            raise preview_expired()

        source_config = session.get(
            TeacherGameConfig,
            (
                claims.source_teacher_id,
                principal.school_id,
                claims.class_id,
            ),
        )
        if source_config is None:
            raise source_config_missing()
        if source_config.version != claims.source_version:
            raise source_version_changed(source_config.version)
        target_row = session.scalars(
            select(TeacherGameConfig)
            .where(
                TeacherGameConfig.teacher_id == principal.teacher_id,
                TeacherGameConfig.school_id == principal.school_id,
                TeacherGameConfig.class_id == claims.class_id,
            )
            .with_for_update()
        ).one_or_none()
        current_target_version = (
            target_row.version if target_row is not None else 0
        )
        if current_target_version != claims.target_version:
            raise target_version_changed(current_target_version)
        source_payload = _validated_payload(
            source_config.payload
        ).model_dump(mode="python")
        target_payload = _validated_payload(
            target_row.payload if target_row is not None else _empty_payload()
        ).model_dump(mode="python")
        changed = source_payload != target_payload
        new_version = current_target_version
        if changed:
            new_version = current_target_version + 1
            new_hash = _payload_hash(source_payload)
            if target_row is None:
                target_row = TeacherGameConfig(
                    teacher_id=principal.teacher_id,
                    school_id=principal.school_id,
                    class_id=claims.class_id,
                    version=new_version,
                    payload=source_payload,
                    payload_hash=new_hash,
                    updated_at=_utcnow(),
                )
                session.add(target_row)
            else:
                target_row.version = new_version
                target_row.payload = source_payload
                target_row.payload_hash = new_hash
                target_row.updated_at = _utcnow()
        result = ConfigConfirmOut(
            request_id=data.request_id,
            class_id=claims.class_id,
            source_teacher_id=claims.source_teacher_id,
            source_version=claims.source_version,
            target_version=claims.target_version,
            config_version=new_version,
            changed=changed,
            payload=_validated_payload(source_payload),
        )
        _add_operation(
            session,
            principal=principal,
            class_id=claims.class_id,
            request_id=data.request_id,
            kind="import",
            fingerprint=fingerprint,
            result=result.model_dump(mode="json"),
            source_teacher_id=claims.source_teacher_id,
            source_version=claims.source_version,
            target_version=claims.target_version,
        )
        session.flush()
        return result


def query_operation(
    session: Session,
    principal: TeacherPrincipal,
    request_id: UUID,
) -> OperationOut:
    row = session.scalars(
        select(CollaborationOperation).where(
            CollaborationOperation.actor_teacher_id == principal.teacher_id,
            CollaborationOperation.request_id == request_id,
        )
    ).one_or_none()
    if row is None:
        raise operation_not_found()
    if row.kind == "save":
        result = ConfigSaveOut.model_validate(row.result_json)
    elif row.kind == "import":
        result = ConfigConfirmOut.model_validate(row.result_json)
    else:
        raise operation_not_found()
    return OperationOut(
        request_id=row.request_id,
        kind=row.kind,
        result=result,
    )
