"""Resolve local term display names at a record's creation time.

The current ``local_terms.name`` is the name new records use.  Committed
renames are append-only rows so old records can keep their recorded name, while
a rename with ``update_existing_documents=true`` also updates the display and
re-export projection of records that already existed.

History is never written into observation snapshots or exported Word bytes.
Only the read projection is resolved here.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.local.models import LocalTermNameChange


@dataclass(frozen=True)
class TermNameChange:
    old_name: str
    new_name: str
    update_existing_documents: bool
    config_version: int
    changed_at: datetime


def load_term_name_changes(
    session: Session, term_ids: Iterable[str]
) -> dict[str, tuple[TermNameChange, ...]]:
    """Load every committed rename for the given terms in commit order."""

    ids = tuple(dict.fromkeys(term_ids))
    if not ids:
        return {}
    rows = session.scalars(
        select(LocalTermNameChange)
        .where(LocalTermNameChange.term_id.in_(ids))
        .order_by(
            LocalTermNameChange.changed_at,
            LocalTermNameChange.config_version,
            LocalTermNameChange.id,
        )
    ).all()
    grouped: dict[str, list[TermNameChange]] = defaultdict(list)
    for row in rows:
        grouped[row.term_id].append(
            TermNameChange(
                old_name=row.old_name,
                new_name=row.new_name,
                update_existing_documents=bool(row.update_existing_documents),
                config_version=row.config_version,
                changed_at=row.changed_at,
            )
        )
    return {term_id: tuple(changes) for term_id, changes in grouped.items()}


def resolve_term_name(
    changes: Sequence[TermNameChange],
    *,
    recorded_at: datetime | None,
    fallback_name: str,
) -> str:
    """Resolve one record's display name from the committed rename timeline.

    Used where no stored term snapshot exists (listening).  ``fallback_name``
    is the name before the first committed rename.  False renames only affect
    records created afterwards; a true rename also applies to records that
    already existed, but a later false rename does not take that display name
    away.
    """

    if not changes:
        return fallback_name
    if recorded_at is None:
        return changes[-1].new_name
    base: TermNameChange | None = None
    retroactive: TermNameChange | None = None
    for change in changes:
        if change.changed_at <= recorded_at:
            base = change
        elif change.update_existing_documents:
            retroactive = change
    chosen = retroactive or base
    return chosen.new_name if chosen is not None else fallback_name


def resolve_snapshot_term_name(
    changes: Sequence[TermNameChange],
    *,
    recorded_at: datetime | None,
    snapshot_name: str,
) -> str:
    """Resolve an observation name with its stored snapshot as authority.

    An observation can be moved to another term and saved with that term's
    current snapshot after its original creation time.  Timeline ``base``
    events must therefore never replace the snapshot.  Only an explicit
    retroactive rename that happened after the record was created overlays the
    new name; every ordinary rename keeps the saved snapshot name.
    """

    if not changes or recorded_at is None:
        return snapshot_name
    retroactive: TermNameChange | None = None
    for change in changes:
        if change.changed_at > recorded_at and change.update_existing_documents:
            retroactive = change
    return retroactive.new_name if retroactive is not None else snapshot_name
