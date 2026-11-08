"""MySQL 8.4 tables for signed prompt-release drafts and channels.

Drafts freeze the complete effective guidance text and the stable baseline they
were based on.  Releases are append-only preview/stable ledger rows; the
``prompt_release_state`` singleton serializes sequence allocation.  Package
files stay outside the database and are addressed by channel, sequence and
package SHA-256.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.mysql import VARCHAR
from sqlalchemy.orm import Mapped, mapped_column

from .models import CollaborationBase, UTCDateTime


def _table_options() -> dict[str, str]:
    return {
        "mysql_engine": "InnoDB",
        "mysql_charset": "utf8mb4",
        "mysql_collate": "utf8mb4_0900_ai_ci",
    }


def _ascii_string(length: int) -> String:
    return String(length).with_variant(
        VARCHAR(length, charset="ascii", collation="ascii_bin"),
        "mysql",
    )


class PromptReleaseState(CollaborationBase):
    __tablename__ = "prompt_release_state"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_prompt_release_state_singleton"),
        CheckConstraint(
            "last_sequence >= 0",
            name="ck_prompt_release_state_sequence",
        ),
        _table_options(),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
    )


class PromptReleaseDraft(CollaborationBase):
    __tablename__ = "prompt_release_drafts"
    __table_args__ = (
        CheckConstraint(
            "char_length(notes) <= 500",
            name="ck_prompt_release_draft_notes",
        ),
        CheckConstraint(
            "base_stable_sequence is null or base_stable_sequence >= 1",
            name="ck_prompt_release_draft_base",
        ),
        Index("ix_prompt_release_draft_created", "created_at"),
        _table_options(),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    notes: Mapped[str] = mapped_column(String(500), nullable=False)
    base_stable_sequence: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    changes: Mapped[dict] = mapped_column(JSON, nullable=False)
    content: Mapped[dict] = mapped_column(JSON, nullable=False)
    revisions: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
    )


class PromptRelease(CollaborationBase):
    __tablename__ = "prompt_releases"
    __table_args__ = (
        CheckConstraint(
            "release_sequence >= 1",
            name="ck_prompt_release_sequence",
        ),
        CheckConstraint(
            "channel in ('preview', 'stable')",
            name="ck_prompt_release_channel",
        ),
        CheckConstraint(
            "notes is null or char_length(notes) <= 500",
            name="ck_prompt_release_notes",
        ),
        CheckConstraint(
            "char_length(package_sha256) = 64",
            name="ck_prompt_release_sha",
        ),
        CheckConstraint(
            "package_byte_size > 0",
            name="ck_prompt_release_size",
        ),
        CheckConstraint(
            "char_length(key_id) between 1 and 64",
            name="ck_prompt_release_key",
        ),
        CheckConstraint(
            "char_length(manifest_signature) = 88",
            name="ck_prompt_release_manifest_signature",
        ),
        CheckConstraint(
            "rollback_of is null or rollback_of >= 1",
            name="ck_prompt_release_rollback",
        ),
        CheckConstraint(
            "expected_stable_sequence is null "
            "or expected_stable_sequence >= 1",
            name="ck_prompt_release_expected_stable",
        ),
        CheckConstraint(
            "(channel = 'preview' and draft_id is not null "
            "and rollback_of is null and expected_stable_sequence is null) "
            "or (channel = 'stable' and ("
            "(draft_id is not null and rollback_of is null "
            "and expected_stable_sequence is null) "
            "or (draft_id is null and rollback_of is not null "
            "and expected_stable_sequence is not null)))",
            name="ck_prompt_release_shape",
        ),
        UniqueConstraint(
            "channel",
            "draft_id",
            name="uq_prompt_release_channel_draft",
        ),
        UniqueConstraint(
            "rollback_of",
            "expected_stable_sequence",
            name="uq_prompt_release_rollback",
        ),
        Index(
            "ix_prompt_release_channel_sequence",
            "channel",
            "release_sequence",
        ),
        Index("ix_prompt_release_draft", "draft_id"),
        Index("ix_prompt_release_rollback", "rollback_of"),
        _table_options(),
    )

    release_sequence: Mapped[int] = mapped_column(
        Integer, primary_key=True
    )
    channel: Mapped[str] = mapped_column(
        _ascii_string(8), nullable=False
    )
    draft_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "prompt_release_drafts.id",
            name="fk_prompt_release_draft",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    rollback_of: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey(
            "prompt_releases.release_sequence",
            name="fk_prompt_release_rollback",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    expected_stable_sequence: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    content: Mapped[dict] = mapped_column(JSON, nullable=False)
    revisions: Mapped[dict] = mapped_column(JSON, nullable=False)
    package_sha256: Mapped[str] = mapped_column(
        _ascii_string(64), nullable=False
    )
    package_byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    key_id: Mapped[str] = mapped_column(_ascii_string(64), nullable=False)
    manifest_signature: Mapped[str] = mapped_column(
        _ascii_string(88), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
    )
