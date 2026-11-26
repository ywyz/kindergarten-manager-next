"""Local personal-todo Nextcloud Tasks (CalDAV) sync tables.

Added by the forward-only ``20261126_0023_local_todo_nextcloud_sync``
migration.  The optional linkage is per local teacher profile and strictly
opt-in: the ``enabled`` flag is False until the teacher explicitly chooses
「双向同步所选清单（新增、编辑和完成）」.

Nothing secret is ever stored here: the server URL, user name, chosen list
href/display name and the bounded last-result summary are settings, while
the Nextcloud *password* lives only in the machine-local DPAPI credential
store under the injected credential root — never in SQLite, never in a
backup package, never in the frontend.

Deletes are deliberately not propagated in either direction: a locally
deleted todo removes only its link row (the remote task is untouched), and
a remotely deleted task keeps the local todo while its link is detached.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    PrimaryKeyConstraint,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.local.base import LocalBase, utc_now


class LocalTodoSyncSetting(LocalBase):
    __tablename__ = "local_todo_sync_settings"
    __table_args__ = (
        PrimaryKeyConstraint("profile_id", name="pk_local_todo_sync_settings"),
        CheckConstraint(
            "length(server_url) BETWEEN 1 AND 2048",
            name="ck_local_todo_sync_settings_url",
        ),
        CheckConstraint("setting_version >= 1", name="ck_local_todo_sync_version"),
        ForeignKeyConstraint(
            ["profile_id"],
            ["local_profile.id"],
            name="fk_local_todo_sync_settings_profile",
        ),
    )

    profile_id: Mapped[str] = mapped_column(String(32), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    server_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    username: Mapped[str] = mapped_column(String(256), nullable=False)
    list_href: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    list_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    setting_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    last_result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, default=utc_now
    )


class LocalTodoSyncLink(LocalBase):
    __tablename__ = "local_todo_sync_links"
    __table_args__ = (
        PrimaryKeyConstraint("profile_id", "todo_id", name="pk_local_todo_sync_links"),
        CheckConstraint(
            "length(remote_uid) BETWEEN 1 AND 255",
            name="ck_local_todo_sync_links_uid",
        ),
        CheckConstraint(
            "length(remote_href) BETWEEN 1 AND 2048",
            name="ck_local_todo_sync_links_href",
        ),
        CheckConstraint(
            "length(server_url) BETWEEN 1 AND 2048",
            name="ck_local_todo_sync_links_server",
        ),
        CheckConstraint(
            "length(username) BETWEEN 1 AND 256",
            name="ck_local_todo_sync_links_username",
        ),
        CheckConstraint(
            "length(list_href) BETWEEN 1 AND 2048",
            name="ck_local_todo_sync_links_list",
        ),
        ForeignKeyConstraint(
            ["profile_id"],
            ["local_profile.id"],
            name="fk_local_todo_sync_links_profile",
        ),
        Index("ix_local_todo_sync_links_uid", "profile_id", "remote_uid"),
        Index(
            "ix_local_todo_sync_links_scope",
            "profile_id",
            "server_url",
            "username",
            "list_href",
        ),
    )

    profile_id: Mapped[str] = mapped_column(String(32), nullable=False)
    todo_id: Mapped[str] = mapped_column(String(32), nullable=False)
    # The account+list origin this link was created against: two different
    # servers (or two accounts on one server) can serve byte-identical href
    # paths, so the binding is the normalized server origin + username + the
    # full selected list href — never the item href alone.
    server_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    username: Mapped[str] = mapped_column(String(256), nullable=False)
    list_href: Mapped[str] = mapped_column(String(2048), nullable=False)
    remote_uid: Mapped[str] = mapped_column(String(255), nullable=False)
    remote_href: Mapped[str] = mapped_column(String(2048), nullable=False)
    remote_etag: Mapped[str | None] = mapped_column(String(256), nullable=True)
    # Hash of the local state that was last pushed/adopted; a pull only
    # overwrites the local todo when this still matches the current local
    # state, so a remote change never clobbers a local edit (and vice versa).
    pushed_state: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Set when the remote task disappeared: the local todo is kept, the
    # linkage for it stops, and nothing is pushed back.
    remote_missing: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, default=utc_now
    )


class LocalTodoSyncOperation(LocalBase):
    __tablename__ = "local_todo_sync_operations"
    __table_args__ = (
        PrimaryKeyConstraint(
            "profile_id", "request_id", name="pk_local_todo_sync_operations"
        ),
        CheckConstraint(
            "action IN ('connect','select','sync','disable')",
            name="ck_local_todo_sync_operations_action",
        ),
        ForeignKeyConstraint(
            ["profile_id"],
            ["local_profile.id"],
            name="fk_local_todo_sync_operations_profile",
        ),
    )

    profile_id: Mapped[str] = mapped_column(String(32), nullable=False)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, default=utc_now
    )


__all__ = [
    "LocalTodoSyncLink",
    "LocalTodoSyncOperation",
    "LocalTodoSyncSetting",
]
