"""The git-sync MCP tools: registration and delegation to gitsync (errors come
back as {ok: False} rather than raising, matching the other tools)."""

from __future__ import annotations

import asyncio


def _run(coro):
    return asyncio.run(coro)


def test_git_tools_are_registered():
    from queryview.mcp_server import mcp

    names = {t.name for t in _run(mcp.list_tools())}
    assert {"git_store", "git_history", "git_restore"} <= names


def test_git_restore_tool_reports_unconfigured(monkeypatch):
    monkeypatch.delenv("GIT_SYNC_REMOTE", raising=False)
    from queryview.mcp_server import git_restore

    r = _run(git_restore("dashboard", "x"))
    assert r["ok"] is False


def test_git_store_resolves_workspace_from_session(tmp_path, monkeypatch):
    """An armed session on workspace B routes git_store to B's remote; no
    session_id falls back to the default workspace."""
    import subprocess

    from queryview import gitsync, remote
    from queryview.mcp_server import git_store
    from queryview.queries import save_predefined_query
    from queryview.workspaces import create_workspace, resolve

    monkeypatch.setattr(gitsync, "_clone_base", lambda: tmp_path / "clones")
    rb = tmp_path / "b.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(rb)],
        check=True,
        capture_output=True,
    )
    _run(create_workspace("t7-b", remote=str(rb)))
    wid = _run(resolve("t7-b")).id
    _run(save_predefined_query("sess q", "clickhouse", "SELECT 1", workspace_id=wid))

    rid = remote.register()
    try:
        remote.set_session_workspace(rid, "t7-b")
        r = _run(git_store("query", "sess q", "clickhouse", session_id=rid))
        assert r["ok"] is True and r["committed"] is True
        log = subprocess.run(
            ["git", "log", "--format=%s", "main"],
            cwd=rb,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        assert "sess q" in log
    finally:
        remote.unregister(rid)


def test_git_store_without_session_uses_default_workspace():
    from queryview.mcp_server import git_store

    # Outside git_env the default workspace has no remote -> unconfigured.
    r = _run(git_store("query", "anything", "clickhouse"))
    assert r["ok"] is False
    assert "no git remote" in r["message"]
