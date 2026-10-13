"""sessions: follow the Queries page's rename to Scripts — move the `queries`
ui key to `scripts` (old `/queries` urls are redirected by the frontend)

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-10-13

"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d5e6f7a8b9c0"
down_revision: str | None = "c4d5e6f7a8b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, ui FROM sessions WHERE ui LIKE '%\"queries\"%'")).all()
    for sid, ui in rows:
        try:
            data = json.loads(ui)
        except ValueError:
            continue  # unreadable ui is already treated as empty (sessions._to_rec)
        if isinstance(data, dict) and "queries" in data:
            data.setdefault("scripts", data.pop("queries"))
            conn.execute(sa.text("UPDATE sessions SET ui = :ui WHERE id = :id"), {"ui": json.dumps(data), "id": sid})


def downgrade() -> None:
    pass  # a data repair; nothing to undo
