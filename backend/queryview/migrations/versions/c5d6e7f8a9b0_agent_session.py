"""sessions: seed the standing Agent session (docs/session.md#the-agent-session)

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-10-24

"""

from __future__ import annotations

import time
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c5d6e7f8a9b0"
down_revision: str | None = "b4c5d6e7f8a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AGENT_SESSION_ID = "agent"  # sessions.AGENT_SESSION_ID; a migration must not import app code


def upgrade() -> None:
    # Seq 0 keeps the user's first session "Session 1" and labels this one "Agent".
    op.get_bind().execute(
        sa.text(
            "INSERT OR IGNORE INTO sessions (id, seq, workspace, url, ui, last_active_at) "
            "VALUES (:id, 0, (SELECT name FROM workspaces ORDER BY id LIMIT 1), '/connect', '{}', :now)"
        ),
        {"id": AGENT_SESSION_ID, "now": int(time.time() * 1000)},
    )


def downgrade() -> None:
    op.get_bind().execute(sa.text("DELETE FROM sessions WHERE id = :id"), {"id": AGENT_SESSION_ID})
