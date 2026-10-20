"""Configuration maintenance: global config version and apply receipts.

Revision ID: 20261014_0003_local
Revises: 20261012_0002_local
Create Date: 2026-10-14

D1B spec §10.3: one global ``config_version`` on the settings singleton
(initial value 1 for upgraded D1A databases, CHECK >= 1) for single-profile
configuration concurrency, plus the committed-apply receipt table
(``request_id`` unique) used to answer retries after a lost response. The
receipt stores only the request id, input fingerprint, result JSON,
committed config version and time — never lesson-plan content.

Existing revision history is untouched: fresh databases run the full chain
(0001 -> 0002 -> 0003) and upgraded D1A databases keep all rows.

Downgrade is intentionally refused (the added state is never dropped).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20261014_0003_local"
down_revision: Union[str, None] = "20261012_0002_local"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_ADD_CONFIG_VERSION = (
    "ALTER TABLE local_settings ADD COLUMN config_version INTEGER NOT NULL "
    "DEFAULT 1 CONSTRAINT ck_local_settings_config_version "
    "CHECK (config_version >= 1)"
)


def upgrade() -> None:
    bind = op.get_bind()

    columns = {
        row[1]
        for row in bind.exec_driver_sql(
            "PRAGMA table_info('local_settings')"
        ).fetchall()
    }
    if "config_version" not in columns:
        bind.exec_driver_sql(_ADD_CONFIG_VERSION)
    # Existing D1A rows keep their initial value 1 (the column default);
    # an explicit statement documents that the value is never 0/NULL.
    bind.exec_driver_sql(
        "UPDATE local_settings SET config_version = 1 "
        "WHERE config_version IS NULL"
    )

    tables = {
        row[0]
        for row in bind.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if "local_config_operations" not in tables:
        op.create_table(
            "local_config_operations",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("request_id", sa.String(36), nullable=False),
            sa.Column(
                "input_fingerprint", sa.String(64), nullable=False
            ),
            sa.Column("result_json", sa.JSON(), nullable=False),
            sa.Column("config_version", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.CheckConstraint(
                "length(request_id) BETWEEN 1 AND 36",
                name="ck_local_config_operations_request_id",
            ),
            sa.CheckConstraint(
                "length(input_fingerprint) = 64",
                name="ck_local_config_operations_fingerprint",
            ),
            sa.CheckConstraint(
                "config_version >= 1",
                name="ck_local_config_operations_config_version",
            ),
            sa.UniqueConstraint(
                "request_id",
                name="uq_local_config_operations_request_id",
            ),
        )


def downgrade() -> None:
    raise RuntimeError(
        "local revisions never drop the configuration version or the "
        "apply receipt table: downgrade is not supported"
    )
