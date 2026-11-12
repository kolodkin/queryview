"""workspaces: drop autosave — only the user's Save persists

Revision ID: c6d7e8f9a0b1
Revises: a8b9c0d1e2f3
Create Date: 2026-11-12

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c6d7e8f9a0b1"
down_revision: str | None = "a8b9c0d1e2f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("workspaces", schema=None) as batch_op:
        batch_op.drop_column("autosave")


def downgrade() -> None:
    with op.batch_alter_table("workspaces", schema=None) as batch_op:
        batch_op.add_column(sa.Column("autosave", sa.Boolean(), nullable=False, server_default=sa.false()))
