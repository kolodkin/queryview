"""sessions: parent and tab, set on the agent's tab sessions
(docs/session.md#tabs); (parent, tab) names a tab

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
        batch_op.add_column(sa.Column("parent", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("tab", sa.String(), nullable=True))
        # NULLs are distinct to SQLite, so ordinary sessions are unaffected.
        batch_op.create_index("ix_sessions_parent_tab", ["parent", "tab"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table("sessions", schema=None) as batch_op:
        batch_op.drop_index("ix_sessions_parent_tab")
        batch_op.drop_column("tab")
        batch_op.drop_column("parent")
