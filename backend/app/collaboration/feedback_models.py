"""MySQL 8.4 ORM tables for the in-app online feedback slice.

The table lives in the same collaboration database and is created only by
``backend/migrations_collaboration/mysql/0007_online_feedback.sql``; the
service never creates or alters it at startup.  Only a keyed digest of the
feedback code is stored (never the plaintext), and the submission content is
exactly the teacher-typed text plus the version string — no teacher profile,
child record, photo, database or credential data is collected.

``length()`` is used in CHECK constraints instead of ``char_length()``: MySQL
accepts both, SQLite (used only by isolated service-level tests) knows only
``length()``, and the authoritative MySQL DDL in the migration file keeps the
exact ``CHAR_LENGTH`` bounds.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .models import CollaborationBase, UTCDateTime, _ascii_string, _table_options

FEEDBACK_STATUSES = ("new", "processing", "resolved")
FEEDBACK_STATUS_DEFAULT = "new"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FeedbackSubmission(CollaborationBase):
    __tablename__ = "feedback_submissions"
    __table_args__ = (
        CheckConstraint(
            "status in ('new', 'processing', 'resolved')",
            name="ck_feedback_status",
        ),
        CheckConstraint(
            "length(content) between 1 and 12000",
            name="ck_feedback_content_length",
        ),
        CheckConstraint(
            "contact is null or (length(contact) between 1 and 200)",
            name="ck_feedback_contact_length",
        ),
        CheckConstraint(
            "app_version is null or (length(app_version) between 1 and 100)",
            name="ck_feedback_app_version_length",
        ),
        CheckConstraint(
            "length(feedback_code_hash) = 64",
            name="ck_feedback_code_hash_length",
        ),
        CheckConstraint(
            "length(content_fingerprint) = 64",
            name="ck_feedback_fingerprint_length",
        ),
        Index("ix_feedback_status_created", "status", "created_at"),
        Index("ix_feedback_created", "created_at"),
        _table_options(),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # The client-generated request id is the idempotency key: the same
    # submission replayed after a lost response returns the original receipt
    # and never enters the admin list twice.
    request_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, unique=True
    )
    content_fingerprint: Mapped[str] = mapped_column(
        _ascii_string(64), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    contact: Mapped[str | None] = mapped_column(String(200), nullable=True)
    app_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    feedback_code_hash: Mapped[str] = mapped_column(
        _ascii_string(64), nullable=False
    )
    status: Mapped[str] = mapped_column(
        _ascii_string(16),
        nullable=False,
        default=FEEDBACK_STATUS_DEFAULT,
        server_default=text(f"'{FEEDBACK_STATUS_DEFAULT}'"),
    )
    handled_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "admin_users.id",
            name="fk_feedback_handled_by_admin",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    handled_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )
    # Python-side UTC defaults keep ORM inserts portable across backends; the
    # MySQL migration additionally declares CURRENT_TIMESTAMP(6) so direct
    # SQL inserts keep microsecond timestamps.
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
