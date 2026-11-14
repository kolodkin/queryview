"""predefined_queries: drop the table — dashboards are the only saved entity

Revision ID: d7e8f9a0b1c2
Revises: c6d7e8f9a0b1
Create Date: 2026-11-14

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "d7e8f9a0b1c2"
down_revision: str | None = "c6d7e8f9a0b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("predefined_queries")


def downgrade() -> None:
    op.create_table(
        "predefined_queries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("query_name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("type", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("query", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("cell_view", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("order_by", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("fields", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("deleted_at", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "type", "query_name", name="uq_predefined_ws_type_name"),
    )
    with op.batch_alter_table("predefined_queries", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_predefined_queries_query_name"), ["query_name"], unique=False)
        batch_op.create_index(batch_op.f("ix_predefined_queries_type"), ["type"], unique=False)
