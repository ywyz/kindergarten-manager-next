"""Local persistence and export reads for curriculum deliberations.

Ownership is always re-derived from the single local profile and stable class;
the request never supplies a profile or class id.  Saves use an explicit
``BEGIN IMMEDIATE`` transaction and a version compare.  A retry of the same
content exactly one version behind the current row is returned as the already
committed result instead of creating a second version.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.local import curriculum_content, profile_service
from app.local.base import utc_now
from app.local.errors import LocalError, LocalValidationError
from app.local.models import LocalCurriculumDeliberation
from app.local.tx import begin_immediate, read_scope, rollback
from app.services.word_export_curriculum import render_curriculum_docx


class CurriculumNotFound(LocalError):
    code = "CURRICULUM_NOT_FOUND"
    status_code = 404
    message = "未找到该课程审议记录"


class CurriculumVersionConflict(LocalError):
    code = "CURRICULUM_VERSION_CONFLICT"
    status_code = 409
    message = "课程审议记录已被其他保存更新，请重新核对"


_DOCUMENT_UNSET = object()


def normalize_record_id(value: object) -> str:
    if not isinstance(value, str):
        raise LocalValidationError("记录 ID 必须是 UUID")
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError, TypeError):
        raise LocalValidationError("记录 ID 必须是 UUID") from None


def _expected_version(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LocalValidationError("expected_version 必须是非负整数")
    return value


def _preview_version(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LocalValidationError("version 必须是非负整数")
    return value


def _context(session: Session):
    return profile_service.require_context(session, date.today())


def _scoped_row(
    session: Session,
    *,
    profile_id: str,
    class_id: str,
    record_id: str,
) -> LocalCurriculumDeliberation:
    row = session.get(LocalCurriculumDeliberation, record_id)
    if (
        row is None
        or row.profile_id != profile_id
        or row.class_id != class_id
    ):
        raise CurriculumNotFound()
    return row


def _record_payload(row: LocalCurriculumDeliberation) -> dict[str, Any]:
    return {
        "id": row.id,
        "version": row.version,
        "content": curriculum_content.stored_content(row.content_json),
        "document": row.document_json,
        "updated_at": row.updated_at.isoformat(),
    }


def list_records(session: Session, *, profile_id: str) -> dict[str, Any]:
    with read_scope(session):
        context = _context(session)
        class_id = context.school_class.id
        rows = session.scalars(
            select(LocalCurriculumDeliberation)
            .where(
                LocalCurriculumDeliberation.profile_id == profile_id,
                LocalCurriculumDeliberation.class_id == class_id,
            )
            .order_by(
                LocalCurriculumDeliberation.updated_at.desc(),
                LocalCurriculumDeliberation.id.desc(),
            )
        ).all()
        defaults = curriculum_content.default_content(
            school_name=context.settings.school_name,
            class_name=context.school_class.name,
            recorder_name=context.profile.display_name,
        )
        return {
            "records": [
                curriculum_content.list_summary(row) for row in rows
            ],
            "defaults": defaults,
        }


def get_record(
    session: Session, *, profile_id: str, record_id: object
) -> dict[str, Any]:
    rid = normalize_record_id(record_id)
    with read_scope(session):
        context = _context(session)
        row = _scoped_row(
            session,
            profile_id=profile_id,
            class_id=context.school_class.id,
            record_id=rid,
        )
        return _record_payload(row)


def save_record(
    session: Session,
    *,
    profile_id: str,
    record_id: object,
    expected_version: object,
    content: object,
    document: object = _DOCUMENT_UNSET,
) -> dict[str, Any]:
    rid = normalize_record_id(record_id)
    expected = _expected_version(expected_version)
    canonical = curriculum_content.normalize_content(content)
    digest = curriculum_content.content_hash(canonical)
    supplied_document = (
        _DOCUMENT_UNSET
        if document is _DOCUMENT_UNSET
        else curriculum_content.normalize_document(document)
    )
    activity_date = (
        date.fromisoformat(canonical["activity_date"])
        if canonical["activity_date"]
        else None
    )
    now = utc_now()

    begin_immediate(session)
    try:
        context = _context(session)
        class_id = context.school_class.id
        row = session.get(LocalCurriculumDeliberation, rid)
        if row is None:
            if expected != 0:
                raise CurriculumNotFound()
            row = LocalCurriculumDeliberation(
                id=rid,
                profile_id=profile_id,
                class_id=class_id,
                version=1,
                activity_name=canonical["activity_name"],
                activity_date=activity_date,
                content_json=canonical,
                content_hash=digest,
                document_json=(
                    None
                    if supplied_document is _DOCUMENT_UNSET
                    else supplied_document
                ),
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            session.flush()
            result = _record_payload(row)
            session.commit()
            return result

        if row.profile_id != profile_id or row.class_id != class_id:
            raise CurriculumNotFound()

        effective_document = (
            row.document_json
            if supplied_document is _DOCUMENT_UNSET
            else supplied_document
        )
        if row.version == expected:
            result = session.execute(
                update(LocalCurriculumDeliberation)
                .where(
                    LocalCurriculumDeliberation.id == rid,
                    LocalCurriculumDeliberation.profile_id == profile_id,
                    LocalCurriculumDeliberation.class_id == class_id,
                    LocalCurriculumDeliberation.version == expected,
                )
                .values(
                    version=expected + 1,
                    activity_name=canonical["activity_name"],
                    activity_date=activity_date,
                    content_json=canonical,
                    content_hash=digest,
                    document_json=effective_document,
                    updated_at=now,
                )
                .execution_options(synchronize_session=False)
            )
            if result.rowcount != 1:
                raise CurriculumVersionConflict(
                    details={"version": row.version}
                )
            session.expire_all()
            updated = _scoped_row(
                session,
                profile_id=profile_id,
                class_id=class_id,
                record_id=rid,
            )
            result_payload = _record_payload(updated)
            session.commit()
            return result_payload

        if (
            row.version == expected + 1
            and row.content_hash == digest
            and row.document_json == effective_document
        ):
            result = _record_payload(row)
            rollback(session)
            return result

        raise CurriculumVersionConflict(details={"version": row.version})
    except BaseException:
        rollback(session)
        raise


def export_preview(
    session: Session,
    *,
    profile_id: str,
    record_id: object,
    version: object,
) -> dict[str, Any]:
    rid = normalize_record_id(record_id)
    requested = _preview_version(version)
    with read_scope(session):
        context = _context(session)
        row = _scoped_row(
            session,
            profile_id=profile_id,
            class_id=context.school_class.id,
            record_id=rid,
        )
        if row.version != requested:
            raise CurriculumVersionConflict(details={"version": row.version})
        content = curriculum_content.stored_content(row.content_json)
        return {
            "id": row.id,
            "version": row.version,
            "activity_name": content["activity_name"],
            "activity_date": content["activity_date"],
            "missing": curriculum_content.missing_fields(content),
            "appendices": curriculum_content.appendices(content),
        }


def word_bytes(
    session: Session,
    *,
    profile_id: str,
    record_id: object,
    version: object,
) -> tuple[bytes, dict[str, str]]:
    rid = normalize_record_id(record_id)
    requested = _preview_version(version)
    with read_scope(session):
        context = _context(session)
        row = _scoped_row(
            session,
            profile_id=profile_id,
            class_id=context.school_class.id,
            record_id=rid,
        )
        if row.version != requested:
            raise CurriculumVersionConflict(details={"version": row.version})
        content = curriculum_content.stored_content(row.content_json)

    # The materialized content and version are already frozen; rendering must
    # not extend or re-enter the read transaction.
    return render_curriculum_docx(content), content


__all__ = [
    "CurriculumNotFound",
    "CurriculumVersionConflict",
    "export_preview",
    "get_record",
    "list_records",
    "normalize_record_id",
    "save_record",
    "word_bytes",
]
