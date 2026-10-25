"""connections: lock_hash — the salted scrypt hash of a locked connection's
passphrase, null when unlocked (docs/connect.md#locked-connections)

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-10-23

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "b4c5d6e7f8a9"
down_revision: str | None = "a3b4c5d6e7f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("connections", schema=None) as batch_op:
        batch_op.add_column(sa.Column("lock_hash", sqlmodel.sql.sqltypes.AutoString(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("connections", schema=None) as batch_op:
        batch_op.drop_column("lock_hash")
