"""Read-only full-history retention for one-to-one listening records.

Every actual content save (manual domain save, record rename, photo import /
batch import / removal / reorder / rotation, and the listening-AI adoption
kernel) appends exactly one retained version row inside the same
``BEGIN IMMEDIATE`` transaction that bumps the shared record revision.  The
retained content is the exact record detail projection (identity, five
domains, three groups per domain, evaluation stars, asset references and
rotations); photo bytes stay in the immutable per-asset store and remain
readable through the existing record asset content route.

A record whose revisions predate this table (an archive created or edited
before the feature) keeps its usable pre-modification original as the lowest
retained version at the first post-feature save, using the record's own
last-save timestamp.  Unknown intermediate revisions are never fabricated.
No-change saves, idempotent replays and revision conflicts append nothing.
"""

from __future__ import annotations

import copy
import hashlib
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ids import new_opaque_id
from app.local import listening_service
from app.local.errors import (
    LocalHistoryNotFound,
    LocalStorageError,
    LocalValidationError,
)
from app.local.models import LocalListeningRecord, LocalListeningRecordVersion
from app.local.prompt_bundles import canonical_json
from app.local.tx import read_scope

__all__ = [
    "capture_before_no_tx",
    "list_versions",
    "read_version",
    "record_initial_version_no_tx",
    "append_save_no_tx",
]


def _content_hash(content: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(content).encode("utf-8")).hexdigest()


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
        select(LocalListeningRecordVersion.id).where(
            LocalListeningRecordVersion.record_id == record_id
        ).limit(1)
    ).first()
    return row is not None


def capture_before_no_tx(
    session: Session, *, record: LocalListeningRecord
) -> dict[str, Any] | None:
    """Snapshot the pre-change record content only when it must be retained.

    Returns ``None`` when the record already has retained versions, so the
    steady-state save path pays one indexed lookup instead of a second full
    projection build.
    """
    if _has_versions(session, record.id):
        return None
    return listening_service._record_dto(session, record)


def record_initial_version_no_tx(
    session: Session,
    *,
    record: LocalListeningRecord,
    content: dict[str, Any],
    now: datetime,
) -> None:
    """Retain the creation save (revision 1) of a brand-new record."""
    session.add(
        LocalListeningRecordVersion(
            id=new_opaque_id(),
            record_id=record.id,
            profile_id=record.profile_id,
            version=int(record.revision),
            content_json=copy.deepcopy(content),
            content_hash=_content_hash(content),
            created_at=now,
        )
    )


def append_save_no_tx(
    session: Session,
    *,
    record_id: str,
    profile_id: str,
    before: dict[str, Any] | None,
    after: dict[str, Any],
    now: datetime,
) -> None:
    """Retain one actual content save inside the caller's write transaction.

    ``before`` is the pre-change record projection captured with
    :func:`capture_before_no_tx`.  When it is not ``None`` the record has no
    retained versions yet (an archive last saved before this feature), so the
    usable pre-modification original is retained first under the record's own
    revision and last-save timestamp; the new state is then retained under the
    freshly bumped revision.
    """
    if before is not None:
        session.add(
            LocalListeningRecordVersion(
                id=new_opaque_id(),
                record_id=record_id,
                profile_id=profile_id,
                version=int(before["revision"]),
                content_json=copy.deepcopy(before),
                content_hash=_content_hash(before),
                created_at=datetime.fromisoformat(before["updated_at"]),
            )
        )
    session.add(
        LocalListeningRecordVersion(
            id=new_opaque_id(),
            record_id=record_id,
            profile_id=profile_id,
            version=int(after["revision"]),
            content_json=copy.deepcopy(after),
            content_hash=_content_hash(after),
            created_at=now,
        )
    )


def list_versions(
    session: Session, *, profile_id: str, record_id: str
) -> dict[str, Any]:
    """Newest-first retained versions of one owned, class-scoped record."""
    with read_scope(session):
        record, _context_value = listening_service._load_record(
            session, profile_id, record_id
        )
        rows = session.execute(
            select(
                LocalListeningRecordVersion.version,
                LocalListeningRecordVersion.created_at,
            )
            .where(
                LocalListeningRecordVersion.record_id == record.id,
                LocalListeningRecordVersion.profile_id == record.profile_id,
            )
            .order_by(LocalListeningRecordVersion.version.desc())
        ).all()
        return {
            "items": [
                {"version": row.version, "saved_at": row.created_at.isoformat()}
                for row in rows
            ]
        }


def read_version(
    session: Session,
    *,
    profile_id: str,
    record_id: str,
    version: object,
) -> dict[str, Any]:
    """One retained full-content snapshot, read-only with integrity checks."""
    version_value = _strict_version(version)
    with read_scope(session):
        record, _context_value = listening_service._load_record(
            session, profile_id, record_id
        )
        row = session.scalars(
            select(LocalListeningRecordVersion)
            .where(
                LocalListeningRecordVersion.record_id == record.id,
                LocalListeningRecordVersion.profile_id == record.profile_id,
                LocalListeningRecordVersion.version == version_value,
            )
            .limit(1)
        ).first()
        if row is None:
            raise LocalHistoryNotFound()
        content = row.content_json
        if (
            not isinstance(content, dict)
            or content.get("record_id") != record.id
            or content.get("revision") != row.version
            or _content_hash(content) != row.content_hash
        ):
            raise LocalStorageError("倾听历史版本内容损坏")
        return {
            "version": row.version,
            "saved_at": row.created_at.isoformat(),
            "content": copy.deepcopy(content),
        }
