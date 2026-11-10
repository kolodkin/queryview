"""The /api/git surface: validation 400s, unconfigured 409, and a store ->
history -> restore round trip against a local bare repo."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from queryview.main import app

# The git_env fixture (bare repo + redirected clone base) lives in conftest.py.


def _run(coro):
    return asyncio.run(coro)


def _default_ws_id() -> int:
    from queryview.workspaces import DEFAULT_WORKSPACE, resolve

    return _run(resolve(DEFAULT_WORKSPACE)).id


def test_status_reports_unconfigured():
    # Outside git_env the default workspace has no remote configured.
    c = TestClient(app)
    assert c.get("/api/git/status").json() == {"configured": False, "conflicts": [], "unsynced": []}


def test_status_reports_configured(git_env):
    c = TestClient(app)
    r = c.get("/api/git/status").json()
    assert r["configured"] is True and r["conflicts"] == []


def test_store_validation_400():
    c = TestClient(app)
    assert c.post("/api/git/store", json={}).status_code == 400
    assert c.post("/api/git/store", json={"kind": "nope", "name": "x"}).status_code == 400
    # queries require conn_type
    assert c.post("/api/git/store", json={"kind": "query", "name": "x"}).status_code == 400


def test_store_history_restore_round_trip(git_env):
    from queryview.queries import list_predefined_queries, save_predefined_query

    c = TestClient(app)
    _run(save_predefined_query("api rt", "clickhouse", "SELECT 1", workspace_id=_default_ws_id()))
    r1 = c.post(
        "/api/git/store",
        json={"kind": "query", "name": "api rt", "conn_type": "clickhouse"},
    ).json()
    assert r1["ok"] is True and r1["committed"] is True
    _run(save_predefined_query("api rt", "clickhouse", "SELECT 2", workspace_id=_default_ws_id()))
    c.post(
        "/api/git/store",
        json={"kind": "query", "name": "api rt", "conn_type": "clickhouse"},
    )

    h = c.get(
        "/api/git/history",
        params={"kind": "query", "name": "api rt", "conn_type": "clickhouse"},
    ).json()
    assert h["ok"] is True and len(h["revisions"]) == 2 and h["has_more"] is False
    oldest = h["revisions"][-1]["sha"]

    r2 = c.post(
        "/api/git/restore",
        json={"kind": "query", "name": "api rt", "conn_type": "clickhouse", "ref": oldest},
    ).json()
    assert r2["ok"] is True
    rows = _run(list_predefined_queries("clickhouse", _default_ws_id()))
    row = next(x for x in rows if x["query_name"] == "api rt")
    assert row["query"] == "SELECT 1"


def test_restore_unknown_entity_404(git_env):
    c = TestClient(app)
    r = c.post(
        "/api/git/restore",
        json={"kind": "query", "name": "never stored api", "conn_type": "clickhouse"},
    )
    assert r.status_code == 404


def test_sync_merges_on_demand_and_needs_a_remote():
    c = TestClient(app)
    r = c.post("/api/git/sync", json={})
    assert r.status_code == 409  # the default workspace has no remote here


def test_saves_and_deletes_commit_to_the_repo(git_env):
    import subprocess

    from queryview.queries import list_predefined_queries
    from queryview.workspaces import DEFAULT_WORKSPACE

    c = TestClient(app)
    ws_id = _default_ws_id()
    base = {"type": "clickhouse"}

    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=git_env, capture_output=True, text=True, check=True).stdout

    def files() -> str:
        return git("ls-tree", "-r", "--name-only", "main")

    def last() -> str:
        return git("log", "-1", "--format=%s", "main").strip()

    assert c.post("/api/predefined-queries", json={**base, "query_name": "api a", "query": "SELECT 1"}).json() == {
        "ok": True
    }
    assert last() == "store query clickhouse/api a"
    c.patch("/api/predefined-queries", json={**base, "query_name": "api a", "new_name": "api b"})
    assert "api b.yaml" in files() and "api a.yaml" not in files()
    c.delete("/api/predefined-queries", params={**base, "query_name": "api b"})
    assert last() == "delete query clickhouse/api b" and "api b" not in files()
    c.patch("/api/predefined-queries", json={**base, "query_name": "api b", "deleted": False})
    assert last() == "store query clickhouse/api b" and "api b.yaml" in files()

    # Purge after a delete: the file is already gone, only the row goes.
    c.delete("/api/predefined-queries", params={**base, "query_name": "api b"})
    r = c.post(f"/api/workspaces/{DEFAULT_WORKSPACE}/purge-deleted").json()
    assert r == {"ok": True, "purged": 1}
    assert last() == "delete query clickhouse/api b"
    names = [q["query_name"] for q in _run(list_predefined_queries("clickhouse", ws_id, include_deleted=True))]
    assert "api b" not in names


def test_a_failed_commit_keeps_the_save(tmp_path, clone_base):
    from queryview.queries import get_predefined_query
    from queryview.workspaces import DEFAULT_WORKSPACE, update_workspace

    _run(update_workspace(DEFAULT_WORKSPACE, remote=str(tmp_path / "missing.git")))
    try:
        c = TestClient(app)
        body = {"type": "clickhouse", "query_name": "api offline", "query": "SELECT 1"}
        r = c.post("/api/predefined-queries", json=body).json()
        assert r["ok"] is True and "git" in r["git_error"]
        assert _run(get_predefined_query("clickhouse", "api offline", _default_ws_id())) is not None
    finally:
        _run(update_workspace(DEFAULT_WORKSPACE, remote=None))


def test_unsynced_lists_what_git_lacks_until_committed(git_env, monkeypatch):
    from queryview import gitsync

    c = TestClient(app)
    body = {"type": "clickhouse", "query_name": "api pending", "query": "SELECT 1"}
    entry = {"kind": "query", "name": "api pending", "conn_type": "clickhouse"}

    def unsynced() -> list:
        return c.get("/api/git/status").json()["unsynced"]

    real_git = gitsync._git

    async def offline(*args, **kw):
        if args[0] == "push":
            raise gitsync.GitSyncError("git push failed: offline")
        return await real_git(*args, **kw)

    monkeypatch.setattr(gitsync, "_git", offline)
    assert "git_error" in c.post("/api/predefined-queries", json=body).json()
    gitsync.forget(_default_ws_id())  # drop the clone's unpushed commit
    assert entry in unsynced()

    monkeypatch.setattr(gitsync, "_git", real_git)
    c.post("/api/git/store", json={"kind": "query", "name": "api pending", "conn_type": "clickhouse"})
    assert entry not in unsynced()

    # A failed delete is pending too; Commit retries it as the file's removal.
    monkeypatch.setattr(gitsync, "_git", offline)
    c.delete("/api/predefined-queries", params={"type": "clickhouse", "query_name": "api pending"})
    gitsync.forget(_default_ws_id())
    assert entry in unsynced()
    monkeypatch.setattr(gitsync, "_git", real_git)
    r = c.post("/api/git/store", json={"kind": "query", "name": "api pending", "conn_type": "clickhouse"}).json()
    assert r["committed"] is True and entry not in unsynced()
