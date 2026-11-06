"""connections: drop lock_hash — locked connections are gone (docs/creds.md)

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
Create Date: 2026-11-06

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "c8d9e0f1a2b3"
down_revision: str | None = "b7c8d9e0f1a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("connections", schema=None) as batch_op:
        batch_op.drop_column("lock_hash")


def downgrade() -> None:
    with op.batch_alter_table("connections", schema=None) as batch_op:
        batch_op.add_column(sa.Column("lock_hash", sqlmodel.sql.sqltypes.AutoString(), nullable=True))
