"""predefined_queries: drop soft delete — deleting removes the row (and, with
a git remote, its file); rows already soft-deleted go

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-11-11

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f2a3b4c5d6e7"
down_revision: str | None = "e1f2a3b4c5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DELETE FROM predefined_queries WHERE deleted_at IS NOT NULL")
    with op.batch_alter_table("predefined_queries", schema=None) as batch_op:
        batch_op.drop_column("deleted_at")


def downgrade() -> None:
    with op.batch_alter_table("predefined_queries", schema=None) as batch_op:
        batch_op.add_column(sa.Column("deleted_at", sa.Integer(), nullable=True))
