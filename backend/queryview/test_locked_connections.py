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
    r = c.post("/api/db/lock", json={"name": "lock-duck", "passphrase": "pw"})
    assert r.json()["ok"], r.text
    token = r.json()["token"]

    con = sqlite3.connect(_db_path())
    try:
        (lock_hash,) = con.execute("SELECT lock_hash FROM connections WHERE name='lock-duck'").fetchone()
    finally:
        con.close()
    assert lock_hash and "pw" not in lock_hash

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
    listed = {x["name"]: x for x in _run(mcp_server.list_connections(sid))["connections"]}
    assert listed["lock-mcp-duck"]["locked"] is True
    # The REST push surface, with the session id only.
    assert c.post("/api/remote/push", json={"session_id": sid, "query": "SELECT 1"}).json() == {
        "ok": False,
        "message": "connection is locked",
    }


def test_unlock_takes_the_passphrase_and_open_needs_it_first(_no_backoff):
    c = _connected("lock-open-duck")
    assert c.post("/api/db/lock", json={"name": "lock-open-duck", "passphrase": "pw"}).json()["ok"]

    other = _client()
    r = other.post("/api/db/open", json={"name": "lock-open-duck"})
    assert r.status_code == 403 and r.json()["message"] == "connection is locked"

    r = other.post("/api/db/unlock", json={"name": "lock-open-duck", "passphrase": "nope"})
    assert r.status_code == 403 and r.json()["message"] == "wrong passphrase"
    r = other.post("/api/db/unlock", json={"name": "lock-open-duck", "passphrase": "nope"})
    assert r.status_code == 403
    assert _no_backoff == [2], "the second wrong guess waited; the first was free"

    r = other.post("/api/db/unlock", json={"name": "lock-open-duck", "passphrase": "pw"})
    assert r.json()["ok"], r.text
    other.headers["X-QV-Token"] = r.json()["token"]
    assert other.post("/api/db/open", json={"name": "lock-open-duck"}).json()["ok"]
    assert other.post("/api/db/query", json={"query": "SELECT 1"}).json()["ok"]
    # A session's token is its own: it does not open the connection elsewhere.
    third = _client()
    third.headers["X-QV-Token"] = other.headers["X-QV-Token"]
    assert third.post("/api/db/open", json={"name": "lock-open-duck"}).status_code == 403


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
