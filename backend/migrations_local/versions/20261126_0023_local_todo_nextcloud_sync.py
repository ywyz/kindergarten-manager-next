"""Add the optional Nextcloud Tasks (CalDAV) todo sync tables.

Revision ID: 20261126_0023_local_todo_nextcloud_sync
Revises: 20261122_0022_local_record_history
Create Date: 2026-11-26

Forward-only: the feature is strictly opt-in and defaults to disabled for
every existing profile.  The Nextcloud *password* is never stored here; it
lives only in the machine-local DPAPI credential store, so no existing row
or teacher archive changes meaning.  No bundle or AI schema is touched.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261126_0023_local_todo_nextcloud_sync"
down_revision: Union[str, None] = "20261122_0022_local_record_history"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "local_todo_sync_settings",
        sa.Column("profile_id", sa.String(length=32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("server_url", sa.String(length=2048), nullable=False),
        sa.Column("username", sa.String(length=256), nullable=False),
        sa.Column("list_href", sa.String(length=2048), nullable=True),
        sa.Column("list_name", sa.String(length=256), nullable=True),
        sa.Column("setting_version", sa.Integer(), nullable=False),
        sa.Column("last_sync_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("last_result", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False),
        sa.PrimaryKeyConstraint("profile_id", name="pk_local_todo_sync_settings"),
        sa.CheckConstraint(
            "length(server_url) BETWEEN 1 AND 2048",
            name="ck_local_todo_sync_settings_url",
        ),
        sa.CheckConstraint(
            "setting_version >= 1", name="ck_local_todo_sync_version"
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["local_profile.id"],
            name="fk_local_todo_sync_settings_profile",
        ),
    )
    op.create_table(
        "local_todo_sync_links",
        sa.Column("profile_id", sa.String(length=32), nullable=False),
        sa.Column("todo_id", sa.String(length=32), nullable=False),
        # The account+list origin this link was created against: two
        # different servers (or two accounts on one server) can serve
        # byte-identical href paths, so the binding is the normalized
        # server origin + username + the full selected list href — never
        # the item href alone.
        sa.Column("server_url", sa.String(length=2048), nullable=False),
        sa.Column("username", sa.String(length=256), nullable=False),
        sa.Column("list_href", sa.String(length=2048), nullable=False),
        sa.Column("remote_uid", sa.String(length=255), nullable=False),
        sa.Column("remote_href", sa.String(length=2048), nullable=False),
        sa.Column("remote_etag", sa.String(length=256), nullable=True),
        sa.Column("pushed_state", sa.String(length=64), nullable=True),
        sa.Column("remote_missing", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False),
        sa.PrimaryKeyConstraint(
            "profile_id", "todo_id", name="pk_local_todo_sync_links"
        ),
        sa.CheckConstraint(
            "length(remote_uid) BETWEEN 1 AND 255",
            name="ck_local_todo_sync_links_uid",
        ),
        sa.CheckConstraint(
            "length(remote_href) BETWEEN 1 AND 2048",
            name="ck_local_todo_sync_links_href",
        ),
        sa.CheckConstraint(
            "length(server_url) BETWEEN 1 AND 2048",
            name="ck_local_todo_sync_links_server",
        ),
        sa.CheckConstraint(
            "length(username) BETWEEN 1 AND 256",
            name="ck_local_todo_sync_links_username",
        ),
        sa.CheckConstraint(
            "length(list_href) BETWEEN 1 AND 2048",
            name="ck_local_todo_sync_links_list",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["local_profile.id"],
            name="fk_local_todo_sync_links_profile",
        ),
    )
    op.create_index(
        "ix_local_todo_sync_links_uid",
        "local_todo_sync_links",
        ["profile_id", "remote_uid"],
    )
    op.create_index(
        "ix_local_todo_sync_links_scope",
        "local_todo_sync_links",
        ["profile_id", "server_url", "username", "list_href"],
    )
    op.create_table(
        "local_todo_sync_operations",
        sa.Column("profile_id", sa.String(length=32), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.PrimaryKeyConstraint(
            "profile_id", "request_id", name="pk_local_todo_sync_operations"
        ),
        sa.CheckConstraint(
            "action IN ('connect','select','sync','disable')",
            name="ck_local_todo_sync_operations_action",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["local_profile.id"],
            name="fk_local_todo_sync_operations_profile",
        ),
    )


def downgrade() -> None:
    raise RuntimeError(
        "local schema is forward-only; restore a verified backup instead"
    )
