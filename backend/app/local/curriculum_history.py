"""Read-only save history for local curriculum deliberations.

Every actual ``curriculum_service.save_record`` commit (creation or update)
retains one full snapshot of the stored content, its linkage document and the
record's own content version, inside the same ``BEGIN IMMEDIATE``
transaction.  The one-version-behind identical retry keeps returning the
already committed result and retains nothing extra.

A record whose versions predate this table (saved before the feature) keeps
its usable pre-modification original as the lowest retained version at the
first post-feature save, under the record's own version and last-save
timestamp; unknown intermediate versions are never fabricated.  Retained
rows are immutable and read-only; there is no restore path here.
"""

from __future__ import annotations

import copy
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ids import new_opaque_id
from app.local import curriculum_content, curriculum_service
from app.local.errors import (
    LocalError,
    LocalHistoryNotFound,
    LocalStorageError,
    LocalValidationError,
)
from app.local.models import (
    LocalCurriculumDeliberation,
    LocalCurriculumDeliberationVersion,
)
from app.local.tx import read_scope

__all__ = [
    "append_save_no_tx",
    "capture_before_no_tx",
    "list_versions",
    "read_version",
    "record_initial_version_no_tx",
]


def _strict_version(value: object) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 1
    ):
        raise LocalValidationError("version 必须是正整数")
    return value


def _has_versions(session: Session, record_id: str) -> bool:
    row = session.scalars(
        select(LocalCurriculumDeliberationVersion.id).where(
            LocalCurriculumDeliberationVersion.record_id == record_id
        ).limit(1)
    ).first()
    return row is not None


def capture_before_no_tx(
    session: Session, *, record_id: str, row: LocalCurriculumDeliberation
) -> dict[str, Any] | None:
    """Snapshot the pre-save content only when it must be retained.

    Returns ``None`` once the record already has retained versions, so the
    steady-state save pays one indexed lookup instead of a copy.
    """
    if _has_versions(session, record_id):
        return None
    return {
        "version": int(row.version),
        "content": copy.deepcopy(row.content_json),
        "content_hash": row.content_hash,
        "document": copy.deepcopy(row.document_json),
        "saved_at": row.updated_at,
    }


def record_initial_version_no_tx(
    session: Session, *, row: LocalCurriculumDeliberation
) -> None:
    """Retain the creation save (version 1) of a brand-new record."""
    session.add(
        LocalCurriculumDeliberationVersion(
            id=new_opaque_id(),
            record_id=row.id,
            profile_id=row.profile_id,
            version=int(row.version),
            content_json=copy.deepcopy(row.content_json),
            content_hash=row.content_hash,
            document_json=copy.deepcopy(row.document_json),
            created_at=row.created_at,
        )
    )


def append_save_no_tx(
    session: Session,
    *,
    record_id: str,
    profile_id: str,
    before: dict[str, Any] | None,
    after_version: int,
    after_content: dict[str, Any],
    after_hash: str,
    after_document: dict[str, Any] | None,
    saved_at: datetime,
) -> None:
    """Retain one actual save inside the caller's write transaction.

    ``before`` is the pre-save snapshot from :func:`capture_before_no_tx`.
    When it is not ``None`` the record has no retained versions yet (an
    archive last saved before this feature), so the usable pre-modification
    original is retained first under the record's own version and last-save
    timestamp; the freshly saved state is then retained under its new
    version.
    """
    if before is not None:
        session.add(
            LocalCurriculumDeliberationVersion(
                id=new_opaque_id(),
                record_id=record_id,
                profile_id=profile_id,
                version=int(before["version"]),
                content_json=copy.deepcopy(before["content"]),
                content_hash=before["content_hash"],
                document_json=copy.deepcopy(before["document"]),
                created_at=before["saved_at"],
            )
        )
    session.add(
        LocalCurriculumDeliberationVersion(
            id=new_opaque_id(),
            record_id=record_id,
            profile_id=profile_id,
            version=int(after_version),
            content_json=copy.deepcopy(after_content),
            content_hash=after_hash,
            document_json=copy.deepcopy(after_document),
            created_at=saved_at,
        )
    )


def list_versions(
    session: Session, *, profile_id: str, record_id: object
) -> dict[str, Any]:
    """Newest-first retained versions of one owned, class-scoped record."""
    with read_scope(session):
        row = curriculum_service.require_record(
            session, profile_id=profile_id, record_id=record_id
        )
        rows = session.execute(
            select(
                LocalCurriculumDeliberationVersion.version,
                LocalCurriculumDeliberationVersion.created_at,
            )
            .where(
                LocalCurriculumDeliberationVersion.record_id == row.id,
                LocalCurriculumDeliberationVersion.profile_id
                == row.profile_id,
            )
            .order_by(LocalCurriculumDeliberationVersion.version.desc())
        ).all()
        return {
            "items": [
                {"version": item.version, "saved_at": item.created_at.isoformat()}
                for item in rows
            ]
        }


def read_version(
    session: Session,
    *,
    profile_id: str,
    record_id: object,
    version: object,
) -> dict[str, Any]:
    """One retained full-content snapshot, read-only with integrity checks."""
    version_value = _strict_version(version)
    with read_scope(session):
        record = curriculum_service.require_record(
            session, profile_id=profile_id, record_id=record_id
        )
        row = session.scalars(
            select(LocalCurriculumDeliberationVersion)
            .where(
                LocalCurriculumDeliberationVersion.record_id == record.id,
                LocalCurriculumDeliberationVersion.profile_id
                == record.profile_id,
                LocalCurriculumDeliberationVersion.version == version_value,
            )
            .limit(1)
        ).first()
        if row is None:
            raise LocalHistoryNotFound()
        content = row.content_json
        if (
            not isinstance(content, dict)
            or curriculum_content.content_hash(content) != row.content_hash
        ):
            raise LocalStorageError("课程审议历史版本内容损坏")
        # The linkage document is part of the full read-only snapshot: a
        # retained document must be null or a valid document mapping.  An
        # unparsable or malformed stored document is a storage failure, not a
        # readable full version; a legacy row that never saved one stays null.
        try:
            document = row.document_json
            if document is not None:
                document = curriculum_content.normalize_document(document)
        except (LocalError, TypeError, ValueError):
            raise LocalStorageError("课程审议历史版本文档损坏") from None
        return {
            "version": row.version,
            "saved_at": row.created_at.isoformat(),
            "content": curriculum_content.stored_content(content),
            "document": document,
        }
