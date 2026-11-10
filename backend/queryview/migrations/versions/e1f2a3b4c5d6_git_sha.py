"""predefined_queries, dashboards: add git_sha — the commit holding the row;
NULL = not in git yet

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-11-10

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e1f2a3b4c5d6"
down_revision: str | None = "d0e1f2a3b4c5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("predefined_queries", "dashboards"):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.add_column(sa.Column("git_sha", sa.String(), nullable=True))


def downgrade() -> None:
    for table in ("predefined_queries", "dashboards"):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_column("git_sha")
