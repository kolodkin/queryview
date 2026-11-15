"""dashboards: add commit_sha — the git commit whose content the row holds

Revision ID: e0f1a2b3c4d5
Revises: d7e8f9a0b1c2
Create Date: 2026-11-15

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "e0f1a2b3c4d5"
down_revision: str | None = "d7e8f9a0b1c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("dashboards", schema=None) as batch_op:
        batch_op.add_column(sa.Column("commit_sha", sqlmodel.sql.sqltypes.AutoString(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("dashboards", schema=None) as batch_op:
        batch_op.drop_column("commit_sha")
