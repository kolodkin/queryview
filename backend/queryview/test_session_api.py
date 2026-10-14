"""The /api/sessions surface: attach claims a session, patches round-trip, and
a session a live tab holds refuses deletion."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from queryview import sessions as sessions_mod
from queryview.main import app


def _run(coro):
    return asyncio.run(coro)


def test_attach_creates_a_session_and_returns_it():
    client = TestClient(app)
    r = client.post("/api/sessions/attach", json={"tab": "tab-http-1"})
    assert r.status_code == 200
    body = r.json()
    assert body["session"]["url"] == "/connect"
    assert body["session"]["id"]


def test_attach_requires_a_tab_token():
    client = TestClient(app)
    r = client.post("/api/sessions/attach", json={})
    assert r.status_code == 400


def test_patch_and_read_back_through_the_header():
    client = TestClient(app)
    sid = client.post("/api/sessions/attach", json={"tab": "tab-http-2"}).json()["session"]["id"]
    client.headers.update({"X-QV-Session": sid, "X-QV-Tab": "tab-http-2"})
    r = client.patch(f"/api/sessions/{sid}", json={"url": "/explorer?table=events"})
    # The updated session comes back, so the client's mirror cannot drift.
    assert r.json()["session"]["url"] == "/explorer?table=events"
    listed = client.get("/api/sessions").json()["sessions"]
    assert any(row["id"] == sid for row in listed)


def test_delete_refuses_a_held_session():
    client = TestClient(app)
    sid = client.post("/api/sessions/attach", json={"tab": "tab-http-3"}).json()["session"]["id"]
    r = client.request("DELETE", f"/api/sessions/{sid}", headers={"X-QV-Session": sid, "X-QV-Tab": "tab-http-3"})
    assert r.status_code == 409


def test_release_frees_the_claim_so_the_next_tab_resumes_it():
    client = TestClient(app)
    sid = client.post("/api/sessions/attach", json={"tab": "tab-http-4"}).json()["session"]["id"]
    client.post("/api/sessions/release", json={"tab": "tab-http-4"})
    again = client.post("/api/sessions/attach", json={"tab": "tab-http-5"}).json()
    assert again["created"] is False
    assert again["session"]["id"] == sid


def test_release_applies_the_state_the_tab_had_not_flushed():
    """A reload fires pagehide inside the client's debounce window, so the
    beacon carries the pending patch and it must not be lost."""
    client = TestClient(app)
    sid = client.post("/api/sessions/attach", json={"tab": "tab-http-6"}).json()["session"]["id"]

    client.post(
        "/api/sessions/release",
        json={"tab": "tab-http-6", "session_id": sid, "ui": {"explorer": {"sidebarWidth": 376}}},
    )

    resumed = client.post("/api/sessions/attach", json={"tab": "tab-http-7"}).json()["session"]
    assert resumed["id"] == sid
    assert resumed["ui"]["explorer"]["sidebarWidth"] == 376


def test_a_heartbeat_on_a_taken_session_is_409_and_force_takes_it_back():
    client = TestClient(app)
    sid = client.post("/api/sessions/attach", json={"tab": "tab-http-6"}).json()["session"]["id"]
    r = client.post("/api/sessions/select", json={"tab": "tab-http-7", "id": sid, "force": True})
    assert r.json()["session"]["id"] == sid
    beat = client.post("/api/sessions/attach", json={"tab": "tab-http-6", "session_id": sid, "keep": True})
    assert beat.status_code == 409


def test_api_answers_only_the_tab_holding_the_session():
    """The session id alone (what an agent knows) is refused; so is a wrong tab."""
    client = TestClient(app)
    sid = client.post("/api/sessions/attach", json={"tab": "tab-http-8"}).json()["session"]["id"]
    assert client.get("/api/session", headers={"X-QV-Session": sid}).status_code == 403
    assert client.get("/api/session", headers={"X-QV-Session": sid, "X-QV-Tab": "other"}).status_code == 403
    assert client.get("/api/session", headers={"X-QV-Session": sid, "X-QV-Tab": "tab-http-8"}).status_code == 200
    assert client.get("/api/health").status_code == 200


def test_release_from_another_tab_writes_nothing():
    client = TestClient(app)
    sid = client.post("/api/sessions/attach", json={"tab": "tab-http-9"}).json()["session"]["id"]
    client.post("/api/sessions/release", json={"tab": "intruder", "session_id": sid, "url": "/scripts"})
    held = {"X-QV-Session": sid, "X-QV-Tab": "tab-http-9"}
    rows = client.get("/api/sessions", headers=held).json()["sessions"]
    assert any(r["id"] == sid for r in rows)
    beat = client.post("/api/sessions/attach", json={"tab": "tab-http-9", "session_id": sid, "keep": True})
    assert beat.json()["session"]["url"] == "/connect"


def test_a_reloads_late_beacon_keeps_the_new_pages_claim():
    """A reload keeps the tab token; its beacon may land after the new page's
    attach. A claim renewed since the beacon's `claimed_at` survives it."""
    client = TestClient(app)
    old = client.post("/api/sessions/attach", json={"tab": "tab-http-10"}).json()["session"]
    _run(sessions_mod.touch_for_test(old["id"], claim_seen_at=old["claimed_at"] - 5000))
    stale = client.post(
        "/api/sessions/attach", json={"tab": "tab-http-10", "session_id": old["id"], "keep": True}
    ).json()["session"]
    assert stale["claimed_at"] > old["claimed_at"] - 5000
    held = {"X-QV-Session": old["id"], "X-QV-Tab": "tab-http-10"}
    client.post("/api/sessions/release", json={"tab": "tab-http-10", "claimed_at": old["claimed_at"] - 5000})
    assert client.get("/api/session", headers=held).status_code == 200
    client.post("/api/sessions/release", json={"tab": "tab-http-10", "claimed_at": stale["claimed_at"]})
    assert client.get("/api/session", headers=held).status_code == 403
