"""sessions: a `tab` column, set on the sessions an agent opens for itself,
and no standing Agent session (docs/session.md#tabs)

Revision ID: a8b9c0d1e2f3
Revises: b7c8d9e0f1a2
Create Date: 2026-11-10

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a8b9c0d1e2f3"
down_revision: str | None = "b7c8d9e0f1a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("sessions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("tab", sa.String(), nullable=True))
    # The row c5d6e7f8a9b0 seeded: an agent now opens a tab session of its own.
    op.execute(sa.text("DELETE FROM sessions WHERE id = 'agent'"))


def downgrade() -> None:
    with op.batch_alter_table("sessions", schema=None) as batch_op:
        batch_op.drop_column("tab")
