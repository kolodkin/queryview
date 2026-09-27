"""dashboards: add params — selectors substituted into the dashboard's queries

Revision ID: a2b3c4d5e6f7
Revises: f0a1b2c3d4e5
Create Date: 2026-09-28

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "a2b3c4d5e6f7"
down_revision: str | None = "f0a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("dashboards", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("params", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default="[]")
        )


def downgrade() -> None:
    with op.batch_alter_table("dashboards", schema=None) as batch_op:
        batch_op.drop_column("params")
