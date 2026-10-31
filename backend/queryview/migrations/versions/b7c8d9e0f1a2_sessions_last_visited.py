"""sessions: add last_visited — per connection, the database and table the
session was last on, so reopening a connection goes straight back

Revision ID: b7c8d9e0f1a2
Revises: c5d6e7f8a9b0
Create Date: 2026-10-31

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "b7c8d9e0f1a2"
down_revision: str | None = "c5d6e7f8a9b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("sessions", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("last_visited", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default="{}")
        )


def downgrade() -> None:
    with op.batch_alter_table("sessions", schema=None) as batch_op:
        batch_op.drop_column("last_visited")
