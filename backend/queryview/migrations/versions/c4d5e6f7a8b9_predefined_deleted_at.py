"""predefined_queries: add deleted_at (soft delete)

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-10-10

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4d5e6f7a8b9"
down_revision: str | None = "b3c4d5e6f7a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("predefined_queries", schema=None) as batch_op:
        batch_op.add_column(sa.Column("deleted_at", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("predefined_queries", schema=None) as batch_op:
        batch_op.drop_column("deleted_at")
