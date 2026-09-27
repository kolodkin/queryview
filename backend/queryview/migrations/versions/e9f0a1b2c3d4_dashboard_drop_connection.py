"""dashboards: drop connection — a dashboard runs on the viewing session's
connection and selected database, so it names none

Revision ID: e9f0a1b2c3d4
Revises: d8e9f0a1b2c3
Create Date: 2026-09-28

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "e9f0a1b2c3d4"
down_revision: str | None = "d8e9f0a1b2c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("dashboards", schema=None) as batch_op:
        batch_op.drop_column("connection")


def downgrade() -> None:
    with op.batch_alter_table("dashboards", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("connection", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default="")
        )
