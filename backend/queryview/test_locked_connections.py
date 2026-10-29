"""Locked connections: a passphrase-locked saved connection serves only the
tab holding its unlock token; the agent (MCP tools, or REST without the token)
is refused. See docs/connect.md#locked-connections."""

from __future__ import annotations

import asyncio
import sqlite3

import pytest
from fastapi.testclient import TestClient

from queryview import connect, mcp_server, remote, sessions
from queryview.connect import _db_path, _hash_passphrase, _passphrase_matches
from queryview.main import app


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch):
    """Wrong guesses sleep; tests only record that they would have."""
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(connect, "_backoff", fake_sleep)
    connect._unlock_failures.clear()
    return slept


def _client() -> TestClient:
    """A client on a fresh session row, as every tab has one."""
    return TestClient(app, headers={"X-QV-Session": _run(sessions.create_session()).id})


def _connected(name: str) -> TestClient:
    """A client whose session is on a saved in-memory DuckDB connection `name`."""
    c = _client()
    r = c.post("/api/db/connect", json={"type": "duckdb", "name": name, "path": ":memory:"})
    assert r.json()["ok"], r.text
    return c


def test_hash_verifies_and_never_stores_the_passphrase():
    stored = _hash_passphrase("open sesame")
    assert "open sesame" not in stored
    assert _passphrase_matches(stored, "open sesame")
    assert not _passphrase_matches(stored, "open sesame!")
    assert _hash_passphrase("x") != _hash_passphrase("x"), "a fresh salt per lock"


def test_lock_keeps_the_locking_tab_working_and_shuts_out_everyone_else():
    c = _connected("lock-duck")
    # A space can't appear in base64, so the plaintext never hides in the hash by chance.
    r = c.post("/api/db/lock", json={"name": "lock-duck", "passphrase": "open sesame"})
    assert r.json()["ok"], r.text
    token = r.json()["token"]

    con = sqlite3.connect(_db_path())
    try:
        (lock_hash,) = con.execute("SELECT lock_hash FROM connections WHERE name='lock-duck'").fetchone()
    finally:
        con.close()
    assert lock_hash and "open sesame" not in lock_hash

    # The same session without the token: what an agent copying the id sends.
    for path, body in (("/api/db/query", {"query": "SELECT 1"}), ("/api/db/execute", {"sql": "SELECT 1"})):
        r = c.post(path, json=body)
        assert r.status_code == 403 and r.json()["message"] == "connection is locked", (path, r.text)
    assert c.get("/api/db/tables").status_code == 403
    assert c.post("/api/db/database", json={"database": "x"}).status_code == 403
    probe = c.get("/api/session").json()
    assert probe["locked"] is True and probe["unlocked"] is False

    c.headers["X-QV-Token"] = token
    assert c.post("/api/db/query", json={"query": "SELECT 1"}).json()["ok"] is True
    probe = c.get("/api/session").json()
    assert probe["locked"] is True and probe["unlocked"] is True
    cards = {x["name"]: x for x in c.get("/api/db/connections").json()["connections"]}
    assert cards["lock-duck"]["locked"] is True

    # A wrong token is no token.
    c.headers["X-QV-Token"] = token[:-1] + ("A" if token[-1] != "A" else "B")
    assert c.post("/api/db/query", json={"query": "SELECT 1"}).status_code == 403


def test_mcp_tools_are_refused_on_a_locked_connection():
    c = _connected("lock-mcp-duck")
    assert c.post("/api/db/lock", json={"name": "lock-mcp-duck", "passphrase": "pw"}).json()["ok"]
    sid = c.headers["X-QV-Session"]
    remote.register(sid)  # armed, so a push would otherwise be delivered

    assert _run(mcp_server.run_sql(sid, "SELECT 1"))["message"] == "connection is locked"
    assert _run(mcp_server.run_script(sid, "SELECT 1"))["message"] == "connection is locked"
    assert _run(mcp_server.push_script(sid, "SELECT 1"))["message"] == "connection is locked"
    assert _run(mcp_server.push_query(sid, "SELECT 1"))["message"] == "connection is locked"
    pushed = _run(mcp_server.push_dashboard(sid, "d", "<p>", {"q": "SELECT 1"}))
    assert pushed["ok"] is False and pushed["message"] == "connection is locked"
    info = _run(mcp_server.session_info(sid))
    assert info["locked"] is True and info["tables"] == [] and "unlocked" not in info
    listed = [x["name"] for x in _run(mcp_server.list_connections(sid))["connections"]]
    assert "lock-mcp-duck" not in listed  # though this session is on it, unlocked
    # The REST push surface, with the session id only.
    assert c.post("/api/remote/push", json={"session_id": sid, "query": "SELECT 1"}).json() == {
        "ok": False,
        "message": "connection is locked",
    }


def test_unlock_takes_the_passphrase_and_opening_lands_locked(_no_backoff):
    c = _connected("lock-open-duck")
    assert c.post("/api/db/lock", json={"name": "lock-open-duck", "passphrase": "pw"}).json()["ok"]

    # Opening lands on the connection, telling the tab to ask; data stays shut.
    other = _client()
    r = other.post("/api/db/open", json={"name": "lock-open-duck"}).json()
    assert r["ok"] and r["locked"] is True and r["unlocked"] is False
    assert other.post("/api/db/query", json={"query": "SELECT 1"}).status_code == 403

    r = other.post("/api/db/unlock", json={"name": "lock-open-duck", "passphrase": "nope"})
    assert r.status_code == 403 and r.json()["message"] == "wrong passphrase"
    r = other.post("/api/db/unlock", json={"name": "lock-open-duck", "passphrase": "nope"})
    assert r.status_code == 403
    assert _no_backoff == [2], "the second wrong guess waited; the first was free"

    r = other.post("/api/db/unlock", json={"name": "lock-open-duck", "passphrase": "pw"})
    assert r.json()["ok"], r.text
    assert _no_backoff == [2, 4], "the right guess after two wrong ones waited too, then reset"
    assert "lock-open-duck" not in connect._unlock_failures
    other.headers["X-QV-Token"] = r.json()["token"]
    assert other.post("/api/db/query", json={"query": "SELECT 1"}).json()["ok"]
    # A session's token is its own: it does not open the connection elsewhere.
    third = _client()
    third.headers["X-QV-Token"] = other.headers["X-QV-Token"]
    assert third.post("/api/db/open", json={"name": "lock-open-duck"}).json()["unlocked"] is False
    assert third.post("/api/db/query", json={"query": "SELECT 1"}).status_code == 403


def test_lock_refusals_and_removal():
    c = _connected("lock-rm-duck")
    assert c.post("/api/db/lock", json={"name": "lock-rm-duck", "passphrase": ""}).status_code == 400
    assert c.post("/api/db/lock", json={"name": "lock-absent", "passphrase": "pw"}).status_code == 400
    assert c.post("/api/db/unlock", json={"name": "lock-rm-duck", "passphrase": "pw"}).status_code == 400
    assert c.post("/api/db/lock", json={"name": "lock-rm-duck", "passphrase": "pw"}).json()["ok"]
    assert c.post("/api/db/lock", json={"name": "lock-rm-duck", "passphrase": "pw"}).status_code == 400

    r = c.request("DELETE", "/api/db/lock", json={"name": "lock-rm-duck", "passphrase": "wrong"})
    assert r.status_code == 403
    r = c.request("DELETE", "/api/db/lock", json={"name": "lock-rm-duck", "passphrase": "pw"})
    assert r.json()["ok"], r.text
    # No token needed any more, by the tab or the agent.
    assert c.post("/api/db/query", json={"query": "SELECT 1"}).json()["ok"]
    assert _run(mcp_server.run_sql(c.headers["X-QV-Session"], "SELECT 1"))["ok"] is True
    assert c.get("/api/session").json()["locked"] is False
    # Relocking, with a new passphrase, starts over.
    assert c.post("/api/db/lock", json={"name": "lock-rm-duck", "passphrase": "pw2"}).json()["ok"]
    assert _run(mcp_server.run_sql(c.headers["X-QV-Session"], "SELECT 1"))["message"] == "connection is locked"
    assert c.post("/api/db/unlock", json={"name": "lock-rm-duck", "passphrase": "pw"}).status_code == 403
    assert c.post("/api/db/unlock", json={"name": "lock-rm-duck", "passphrase": "pw2"}).json()["ok"]


def test_a_restart_forgets_tokens_but_not_the_lock():
    c = _connected("lock-restart-duck")
    r = c.post("/api/db/lock", json={"name": "lock-restart-duck", "passphrase": "pw"})
    c.headers["X-QV-Token"] = r.json()["token"]
    assert c.post("/api/db/query", json={"query": "SELECT 1"}).json()["ok"]

    connect._unlocked.clear()  # what a restart does to memory
    connect._sessions.clear()
    assert c.post("/api/db/query", json={"query": "SELECT 1"}).status_code == 403
    assert c.get("/api/session").json() | {"unlocked": False} == c.get("/api/session").json()
    r = c.post("/api/db/unlock", json={"name": "lock-restart-duck", "passphrase": "pw"})
    c.headers["X-QV-Token"] = r.json()["token"]
    assert c.post("/api/db/query", json={"query": "SELECT 1"}).json()["ok"]


def test_lock_reaches_sessions_already_on_the_connection():
    c = _connected("lock-shared-duck")
    other = _client()
    assert other.post("/api/db/open", json={"name": "lock-shared-duck"}).json()["ok"]
    assert c.post("/api/db/lock", json={"name": "lock-shared-duck", "passphrase": "pw"}).json()["ok"]
    assert other.post("/api/db/query", json={"query": "SELECT 1"}).status_code == 403
    assert _run(mcp_server.run_sql(other.headers["X-QV-Session"], "SELECT 1"))["message"] == "connection is locked"


def test_resaving_a_locked_connection_keeps_it_locked():
    c = _connected("lock-resave-duck")
    token = c.post("/api/db/lock", json={"name": "lock-resave-duck", "passphrase": "pw"}).json()["token"]
    body = {"type": "duckdb", "name": "lock-resave-duck", "path": ":memory:"}
    # Without the token the config behind the lock cannot be replaced either.
    r = c.post("/api/db/connect", json=body)
    assert r.status_code == 403 and r.json() == {"ok": False, "message": "connection is locked"}
    c.headers["X-QV-Token"] = token
    r = c.post("/api/db/connect", json=body)
    assert r.json()["ok"], r.text
    c.headers.pop("x-qv-token")
    assert _run(mcp_server.run_sql(c.headers["X-QV-Session"], "SELECT 1"))["message"] == "connection is locked"
    assert c.get("/api/session").json()["locked"] is True


def test_one_token_per_session_so_locking_another_connection_keeps_this_one_open():
    c = _connected("lock-tok-a")
    _connected("lock-tok-b")
    token = c.post("/api/db/lock", json={"name": "lock-tok-a", "passphrase": "pw"}).json()["token"]
    assert c.post("/api/db/lock", json={"name": "lock-tok-b", "passphrase": "pw"}).json()["token"] == token


def test_edit_reads_the_config_back_without_the_password_and_a_blank_one_keeps_it(monkeypatch):
    from queryview.drivers import DRIVERS
    from queryview.drivers.base import DatabasesResult

    seen: list[str] = []

    async def one_db(config):
        seen.append(config.password)
        return DatabasesResult(databases=["a"])

    monkeypatch.setattr(DRIVERS["clickhouse"], "list_databases", one_db)
    c = _client()
    body = {"type": "clickhouse", "name": "edit-ch", "host": "h", "port": 8123, "username": "u", "password": "p"}
    assert c.post("/api/db/connect", json=body).json()["ok"]
    r = c.get("/api/db/connections/edit-ch").json()
    config = {"host": "h", "port": 8123, "username": "u", "password": ""}
    assert r == {"ok": True, "name": "edit-ch", "type": "clickhouse", "config": config}
    # A re-save with a blank password keeps the saved one; a new one replaces it.
    assert c.post("/api/db/connect", json={**body, "host": "h2", "password": ""}).json()["ok"]
    assert c.post("/api/db/connect", json={**body, "password": "p2"}).json()["ok"]
    assert seen == ["p", "p", "p2"]
    assert c.get("/api/db/connections/edit-ch").json()["config"]["host"] == "h"
    assert c.get("/api/db/connections/nope").status_code == 404


def test_a_locked_connection_hides_its_config_from_a_tab_without_the_token():
    c = _connected("edit-locked-duck")
    token = c.post("/api/db/lock", json={"name": "edit-locked-duck", "passphrase": "pw"}).json()["token"]
    r = c.get("/api/db/connections/edit-locked-duck")
    assert r.status_code == 403 and r.json()["message"] == "connection is locked"
    c.headers["X-QV-Token"] = token
    assert c.get("/api/db/connections/edit-locked-duck").json()["config"] == {"path": ":memory:"}


def test_delete_disconnects_every_session_on_it_and_a_locked_one_takes_the_passphrase():
    c = _connected("del-duck")
    other = _client()
    assert other.post("/api/db/open", json={"name": "del-duck"}).json()["ok"]
    r = c.request("DELETE", "/api/db/connections", json={"name": "del-duck"})
    assert r.json() == {"ok": True}
    names = {x["name"] for x in c.get("/api/db/connections").json()["connections"]}
    assert "del-duck" not in names
    for client in (c, other):
        assert client.get("/api/session").json()["connected"] is False
    assert c.request("DELETE", "/api/db/connections", json={"name": "del-duck"}).status_code == 404

    c = _connected("del-locked-duck")
    assert c.post("/api/db/lock", json={"name": "del-locked-duck", "passphrase": "pw"}).json()["ok"]
    r = c.request("DELETE", "/api/db/connections", json={"name": "del-locked-duck"})
    assert r.status_code == 403
    r = c.request("DELETE", "/api/db/connections", json={"name": "del-locked-duck", "passphrase": "nope"})
    assert r.status_code == 403 and r.json()["message"] == "wrong passphrase"
    r = c.request("DELETE", "/api/db/connections", json={"name": "del-locked-duck", "passphrase": "pw"})
    assert r.json() == {"ok": True}
    assert c.get("/api/session").json()["connected"] is False


def test_delete_drops_a_session_connection_of_this_session():
    c = _client()
    body = {"type": "duckdb", "name": "del-session-duck", "path": ":memory:", "session": True}
    assert c.post("/api/db/connect", json=body).json()["ok"]
    assert c.request("DELETE", "/api/db/connections", json={"name": "del-session-duck"}).json() == {"ok": True}
    assert c.get("/api/session").json()["connected"] is False
    assert "del-session-duck" not in {x["name"] for x in c.get("/api/db/connections").json()["connections"]}


def test_list_databases_leaves_out_locked_connections_even_when_unlocked():
    c = _connected("lock-list-duck")
    sid = c.headers["X-QV-Session"]
    assert {"name": "lock-list-duck", "type": "duckdb", "databases": []} in _run(mcp_server.list_databases(sid))[
        "connections"
    ]
    assert _run(mcp_server.list_databases(sid, "lock-list-duck"))["connections"] == [
        {"name": "lock-list-duck", "type": "duckdb", "databases": []}
    ]
    # The locking tab holds the unlock token, but the lock is the connection's.
    assert c.post("/api/db/lock", json={"name": "lock-list-duck", "passphrase": "pw"}).json()["ok"]
    names = [x["name"] for x in _run(mcp_server.list_databases(sid))["connections"]]
    assert "lock-list-duck" not in names
    assert _run(mcp_server.list_databases(sid, "lock-list-duck")) == {
        "ok": False,
        "message": 'no connection named "lock-list-duck"',
    }
    assert _run(mcp_server.list_databases("no-such-session"))["ok"] is False


def test_list_databases_reports_a_failing_connection_without_failing_the_rest(monkeypatch):
    sid = _connected("list-fail-duck").headers["X-QV-Session"]

    async def boom(config):
        raise RuntimeError("server gone")

    monkeypatch.setattr(connect.DRIVERS["duckdb"], "list_databases", boom)
    out = _run(mcp_server.list_databases(sid, "list-fail-duck"))
    assert out["connections"] == [{"name": "list-fail-duck", "type": "duckdb", "error": "RuntimeError: server gone"}]
