"""sessions: seed the always-on agent session (id all zeros, label "agent")

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-10-23

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b4c5d6e7f8a9"
down_revision: str | None = "a3b4c5d6e7f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AGENT_SESSION_ID = "0" * 32


def upgrade() -> None:
    op.execute(
        sa.text(
            "INSERT OR IGNORE INTO sessions (id, seq, label, workspace, url, ui, last_active_at)"
            " VALUES (:id, 0, 'agent', COALESCE((SELECT name FROM workspaces ORDER BY id LIMIT 1), 'default'),"
            " '/connect', '{}', 0)"
        ).bindparams(id=AGENT_SESSION_ID)
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM sessions WHERE id = :id").bindparams(id=AGENT_SESSION_ID))
