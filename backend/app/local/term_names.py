"""Resolve local term display names at a record's creation time.

The current ``local_terms.name`` is the name new records use.  Committed
renames are append-only rows so old records keep their recorded name.  Even a
legacy ``update_existing_documents=true`` row does not rewrite existing
records; the explicit historical reissue flow creates a new version instead.

History is never written into observation snapshots or exported Word bytes.
Only the listening read projection is resolved here; observations always read
their stored snapshot.
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
    """Resolve one listening record's name from its creation time.

    Existing records keep the name that was current when they were created.
    Even a legacy ``update_existing_documents=true`` row does not rewrite an
    already stored record's display; the explicit reissue flow creates a new
    confirmation/version instead.  ``fallback_name`` is the name before the
    first committed rename.
    """

    if not changes:
        return fallback_name
    if recorded_at is None:
        return changes[-1].new_name
    base: TermNameChange | None = None
    for change in changes:
        if change.changed_at <= recorded_at:
            base = change
    return base.new_name if base is not None else fallback_name
