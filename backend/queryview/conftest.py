"""Shared fixtures for backend (non-e2e) tests.

Redirects the data directory to a per-session tempdir so tests don't touch the
real one, and resets the lazy module-level engine/schema state in
`queryview.connect` before tests run."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def clone_base(tmp_path, monkeypatch) -> Path:
    """Redirect every workspace's sync clone into this test's tmpdir, so clones
    never land in the session data dir and can't leak between tests."""
    from queryview import gitsync

    base = tmp_path / "clones"
    monkeypatch.setattr(gitsync, "_clone_base", lambda: base)
    return base


@pytest.fixture
def git_env(tmp_path, clone_base):
    """A local bare repo as the default workspace's git-sync remote + a fresh
    per-workspace clone base dir. Resets the default workspace to 'no remote'
    on teardown so unconfigured-state tests stay valid."""
    import asyncio

    from queryview.workspaces import DEFAULT_WORKSPACE, update_workspace

    remote = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(remote)],
        check=True,
        capture_output=True,
    )
    asyncio.run(update_workspace(DEFAULT_WORKSPACE, remote=str(remote)))
    yield remote
    asyncio.run(update_workspace(DEFAULT_WORKSPACE, remote=None))


@pytest.fixture
def wipe_workspace_entities():
    """A callable that deletes every entity a workspace owns — teardown for
    import tests that must leave a non-default workspace empty so
    delete_workspace accepts it."""
    import asyncio

    from sqlalchemy import text

    def _wipe(workspace_id: int) -> None:
        import queryview.connect as c

        async def go():
            async with c._engine_for_db().begin() as conn:
                await conn.execute(text("DELETE FROM predefined_queries WHERE workspace_id = :w"), {"w": workspace_id})
                await conn.execute(text("DELETE FROM dashboards WHERE workspace_id = :w"), {"w": workspace_id})

        asyncio.run(go())

    return _wipe


@pytest.fixture
def default_ws_id() -> int:
    """The seeded default workspace's id, for store-level calls in tests."""
    import asyncio

    from queryview.workspaces import DEFAULT_WORKSPACE, resolve

    return asyncio.run(resolve(DEFAULT_WORKSPACE)).id


@pytest.fixture(scope="session", autouse=True)
def _isolated_db(tmp_path_factory: pytest.TempPathFactory):
    tmp: Path = tmp_path_factory.mktemp("qv_backend_tests")
    os.environ["DATA_DIR"] = str(tmp)

    # Reset the lazy globals so the next DB touch picks up the new paths.
    import queryview.connect as _c

    _c._engine = None  # type: ignore[attr-defined]
    _c._schema_ready = False  # type: ignore[attr-defined]
    _c._key = None  # type: ignore[attr-defined]
    yield
