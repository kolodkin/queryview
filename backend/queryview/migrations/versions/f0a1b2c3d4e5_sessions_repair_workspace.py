"""sessions: move sessions stranded on a renamed or deleted workspace to the
oldest workspace (renames and deletes now carry sessions along themselves)

Revision ID: f0a1b2c3d4e5
Revises: e9f0a1b2c3d4
Create Date: 2026-09-28

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f0a1b2c3d4e5"
down_revision: str | None = "e9f0a1b2c3d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE sessions SET workspace = (SELECT name FROM workspaces ORDER BY id LIMIT 1)"
            " WHERE workspace NOT IN (SELECT name FROM workspaces)"
            " AND EXISTS (SELECT 1 FROM workspaces)"
        )
    )


def downgrade() -> None:
    pass  # a data repair; nothing to undo
