"""Require every local term to own a first calendar revision.

Revision ID: 20261012_0002_local
Revises: 20261012_0001_local
Create Date: 2026-10-12

R2 fix: ``local_terms.current_calendar_revision_id`` was nullable in the
baseline, so a commit could leave a term without any calendar revision.
This revision rebuilds ``local_terms`` with ``NOT NULL`` after validating
that every existing term already points at a revision of its own. Terms
with a NULL/dangling/foreign pointer refuse the upgrade and keep the
original file untouched (no fabricated revision, no clean, no stamp).

The rebuild follows SQLite's documented procedure: the migration
transaction runs with ``foreign_keys=OFF`` (set in ``env.py`` before
``BEGIN IMMEDIATE``), and ``env.py`` runs ``PRAGMA foreign_key_check``
before COMMIT. The cyclic
``local_terms`` <-> ``local_calendar_revisions`` references make a plain
drop/rename under immediate enforcement unsafe; the check proves both
directions afterwards.

Downgrade is intentionally refused (the nullable schema is never restored).
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20261012_0002_local"
down_revision: Union[str, None] = "20261012_0001_local"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_VALIDATE_TERMS = (
    "SELECT count(*) FROM local_terms t "
    "LEFT JOIN local_calendar_revisions r "
    "ON r.id = t.current_calendar_revision_id AND r.term_id = t.id "
    "WHERE t.current_calendar_revision_id IS NULL OR r.id IS NULL"
)

_REBUILD_TERMS = """
CREATE TABLE _local_terms_rebuild (
    id VARCHAR(32) NOT NULL,
    name VARCHAR(80) NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    current_calendar_revision_id VARCHAR(32) NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    CONSTRAINT ck_local_terms_date_order CHECK (start_date <= end_date),
    CONSTRAINT ck_local_terms_name CHECK (length(name) BETWEEN 1 AND 80),
    CONSTRAINT fk_local_terms_current_revision
        FOREIGN KEY (id, current_calendar_revision_id)
        REFERENCES local_calendar_revisions (term_id, id)
        DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT pk_local_terms PRIMARY KEY (id)
)
"""

_COPY_TERMS = (
    "INSERT INTO _local_terms_rebuild (id, name, start_date, end_date, "
    "current_calendar_revision_id, created_at, updated_at) "
    "SELECT id, name, start_date, end_date, current_calendar_revision_id, "
    "created_at, updated_at FROM local_terms"
)


def upgrade() -> None:
    bind = op.get_bind()
    bad = bind.exec_driver_sql(_VALIDATE_TERMS).scalar()
    if bad:
        raise RuntimeError(
            f"refusing to rebuild local_terms: {int(bad)} term(s) lack a "
            "current calendar revision owned by the same term"
        )

    bind.exec_driver_sql(_REBUILD_TERMS)
    bind.exec_driver_sql(_COPY_TERMS)
    bind.exec_driver_sql("DROP TABLE local_terms")
    bind.exec_driver_sql(
        "ALTER TABLE _local_terms_rebuild RENAME TO local_terms"
    )


def downgrade() -> None:
    raise RuntimeError(
        "local revisions never restore the nullable term revision pointer: "
        "downgrade is not supported"
    )
