"""The git-sync MCP tools: registration and delegation to gitsync (errors come
back as {ok: False} rather than raising, matching the other tools)."""

from __future__ import annotations

import asyncio


def _run(coro):
    return asyncio.run(coro)


def test_git_tools_are_registered():
    from queryview.mcp_server import mcp

    names = {t.name for t in _run(mcp.list_tools())}
    assert {"git_history", "git_restore"} <= names
    assert "git_store" not in names  # only a user's Save commits


def test_git_restore_tool_reports_unconfigured():
    from queryview.mcp_server import git_restore

    r = _run(git_restore("dashboard", "x"))
    assert r["ok"] is False


def test_git_history_resolves_workspace_from_session(tmp_path, clone_base):
    """An armed session on workspace B routes git_history to B's remote."""
    import subprocess

    from queryview import gitsync, remote
    from queryview.mcp_server import git_history
    from queryview.workspaces import create_workspace, resolve

    rb = tmp_path / "b.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(rb)],
        check=True,
        capture_output=True,
    )
    _run(create_workspace("t7-b", remote=str(rb)))
    ws = _run(resolve("t7-b"))
    _run(gitsync.save(ws, {"name": "sess dash", "html": "<p/>", "queries": {"q": "SELECT 1"}, "params": []}))

    from queryview import sessions

    rec = _run(sessions.create_session())
    _run(sessions.patch_session(rec.id, workspace="t7-b"))
    rid = remote.register(rec.id)
    try:
        r = _run(git_history("dashboard", "sess dash", session_id=rid))
        assert r["ok"] is True
        assert [v["message"] for v in r["revisions"]] == ["store dashboard sess dash"]
    finally:
        remote.unregister(rid)


def test_git_history_without_session_uses_default_workspace():
    from queryview.mcp_server import git_history

    # Outside git_env the default workspace has no remote -> unconfigured.
    r = _run(git_history("dashboard", "anything"))
    assert r["ok"] is False
    assert "no git remote" in r["message"]


def test_git_tools_refuse_the_removed_query_kind():
    from queryview.mcp_server import git_history, git_restore

    for tool in (git_history, git_restore):
        r = _run(tool("query", "anything"))
        assert r["ok"] is False and "expected 'dashboard'" in r["message"]
