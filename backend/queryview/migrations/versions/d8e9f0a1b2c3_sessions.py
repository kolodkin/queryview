"""sessions: persistent per-tab UI state (route, connection, query panel)

Creates the 'sessions' table. Nothing is backfilled: the previous session
concept was in-memory only, so there is no prior state to carry forward.

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
Create Date: 2026-09-17

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "d8e9f0a1b2c3"
down_revision: str | None = "c7d8e9f0a1b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("label", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("connection_name", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("database", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("workspace", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("url", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("ui", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("claimed_by", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("claim_seen_at", sa.Integer(), nullable=True),
        sa.Column("last_active_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sessions_last_active_at"), "sessions", ["last_active_at"], unique=False)
    # Claims are released by tab token on every heartbeat.
    op.create_index(op.f("ix_sessions_claimed_by"), "sessions", ["claimed_by"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_sessions_claimed_by"), table_name="sessions")
    op.drop_index(op.f("ix_sessions_last_active_at"), table_name="sessions")
    op.drop_table("sessions")
