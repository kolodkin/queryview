"""workspaces: per-workspace git sync — workspaces table, entity workspace_id

Creates the 'default' workspace (its remote is configured through the UI/API
afterwards) and backfills all existing predefined queries and dashboards into
it. Name uniqueness becomes
per-workspace.

Revision ID: c7d8e9f0a1b2
Revises: b2c3d4e5f6a7
Create Date: 2026-07-10

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "c7d8e9f0a1b2"
down_revision: str | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspaces",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("remote", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("branch", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_workspaces_name"), "workspaces", ["name"], unique=True)

    # No remote yet: git sync stays disabled until one is set through the
    # UI/API, which encrypts it on the way in.
    conn = op.get_bind()
    conn.execute(
        sa.text("INSERT INTO workspaces (name, remote, branch) VALUES (:n, NULL, :b)"),
        {"n": "default", "b": "main"},
    )
    default_id = conn.execute(sa.text("SELECT id FROM workspaces WHERE name = 'default'")).scalar()

    # server_default backfills existing rows during the batch table rewrite and
    # keeps pre-workspace INSERT paths working mid-upgrade; application code
    # always passes workspace_id explicitly.
    with op.batch_alter_table("predefined_queries", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "workspace_id",
                sa.Integer(),
                nullable=False,
                server_default=str(default_id),
            )
        )
        batch_op.drop_constraint("uq_predefined_type_name", type_="unique")
        batch_op.create_unique_constraint("uq_predefined_ws_type_name", ["workspace_id", "type", "query_name"])

    with op.batch_alter_table("dashboards", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "workspace_id",
                sa.Integer(),
                nullable=False,
                server_default=str(default_id),
            )
        )
        batch_op.create_unique_constraint("uq_dashboards_ws_name", ["workspace_id", "name"])

    # Dashboard names are now unique per workspace, not globally.
    op.drop_index("ix_dashboards_name", table_name="dashboards")
    op.create_index("ix_dashboards_name", "dashboards", ["name"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("dashboards", schema=None) as batch_op:
        batch_op.drop_constraint("uq_dashboards_ws_name", type_="unique")
        batch_op.drop_column("workspace_id")
    op.drop_index("ix_dashboards_name", table_name="dashboards")
    op.create_index("ix_dashboards_name", "dashboards", ["name"], unique=True)

    with op.batch_alter_table("predefined_queries", schema=None) as batch_op:
        batch_op.drop_constraint("uq_predefined_ws_type_name", type_="unique")
        batch_op.create_unique_constraint("uq_predefined_type_name", ["type", "query_name"])
        batch_op.drop_column("workspace_id")

    op.drop_index(op.f("ix_workspaces_name"), table_name="workspaces")
    op.drop_table("workspaces")
