"""The /api/sessions surface: attach claims a session, patches round-trip, and
a session a live tab holds refuses deletion."""

from __future__ import annotations

from fastapi.testclient import TestClient

from queryview.main import app


def test_attach_creates_a_session_and_returns_it():
    client = TestClient(app)
    r = client.post("/api/sessions/attach", json={"tab": "tab-http-1"})
    assert r.status_code == 200
    body = r.json()
    assert body["session"]["url"] == "/queries"
    assert body["session"]["id"]


def test_attach_requires_a_tab_token():
    client = TestClient(app)
    r = client.post("/api/sessions/attach", json={})
    assert r.status_code == 400


def test_patch_and_read_back_through_the_header():
    client = TestClient(app)
    sid = client.post("/api/sessions/attach", json={"tab": "tab-http-2"}).json()["session"]["id"]
    r = client.patch(f"/api/sessions/{sid}", json={"url": "/explorer?table=events"})
    assert r.json() == {"ok": True}
    listed = client.get("/api/sessions").json()["sessions"]
    assert any(row["id"] == sid for row in listed)


def test_delete_refuses_a_held_session():
    client = TestClient(app)
    sid = client.post("/api/sessions/attach", json={"tab": "tab-http-3"}).json()["session"]["id"]
    r = client.request("DELETE", f"/api/sessions/{sid}")
    assert r.status_code == 409


def test_release_frees_the_claim_so_the_next_tab_resumes_it():
    client = TestClient(app)
    sid = client.post("/api/sessions/attach", json={"tab": "tab-http-4"}).json()["session"]["id"]
    client.post("/api/sessions/release", json={"tab": "tab-http-4"})
    again = client.post("/api/sessions/attach", json={"tab": "tab-http-5"}).json()
    assert again["created"] is False
    assert again["session"]["id"] == sid
