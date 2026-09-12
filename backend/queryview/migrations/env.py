"""Alembic environment. Uses a *sync* SQLite engine (separate from the app's
async aiosqlite runtime, to avoid async-greenlet complexity). Importing the model
modules populates SQLModel.metadata so autogenerate sees every table;
render_as_batch=True is required for SQLite's limited ALTER TABLE.

Online migrations only — the app and dev CLI both run `alembic upgrade` against a
real connection; offline (`--sql`) mode isn't used."""

from __future__ import annotations

# Import for side effects: register all tables on SQLModel.metadata.
import queryview.connect  # noqa: F401
import queryview.dashboards  # noqa: F401
import queryview.queries  # noqa: F401
from alembic import context
from sqlalchemy import create_engine, pool
from sqlmodel import SQLModel

config = context.config
target_metadata = SQLModel.metadata


def _url() -> str:
    """Prefer the URL the app injects; fall back to the data dir so the dev CLI
    (`alembic ...`) targets the same SQLite file the app would."""
    from queryview.connect import _db_path

    return config.get_main_option("sqlalchemy.url") or f"sqlite:///{_db_path()}"


connectable = create_engine(_url(), poolclass=pool.NullPool)
with connectable.connect() as connection:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()
