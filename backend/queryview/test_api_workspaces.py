"""The /api/workspaces surface: CRUD round trip and no-secret listing.
Store-level rules (delete-non-empty 409, name validation details) are covered
in test_workspaces.py."""

from __future__ import annotations

from fastapi.testclient import TestClient

from queryview.main import app


def test_list_includes_default():
    c = TestClient(app)
    names = [w["name"] for w in c.get("/api/workspaces").json()["workspaces"]]
    assert "default" in names


def test_create_list_update_delete_round_trip():
    c = TestClient(app)
    r = c.post(
        "/api/workspaces",
        json={"name": "t6-rt", "remote": "https://u:tok@example.test/r.git", "branch": "dev"},
    )
    # Saved even though the fake remote can't be reached to merge from.
    assert r.json()["ok"] is True and "sync_error" in r.json()

    listed = {w["name"]: w for w in c.get("/api/workspaces").json()["workspaces"]}
    assert listed["t6-rt"] == {
        "name": "t6-rt",
        "branch": "dev",
        "configured": True,
        # Shown without the credential, which never leaves the server.
        "remote": "https://example.test/r.git",
    }
    assert "tok" not in r.text and "tok" not in str(listed["t6-rt"])

    # Rename + clear the remote (present-but-null clears; absent keeps).
    assert c.patch("/api/workspaces/t6-rt", json={"name": "t6-rt2", "remote": None}).json() == {"ok": True}
    listed = {w["name"]: w for w in c.get("/api/workspaces").json()["workspaces"]}
    assert "t6-rt" not in listed
    assert listed["t6-rt2"]["configured"] is False

    assert c.delete("/api/workspaces/t6-rt2").json() == {"ok": True}
    assert c.delete("/api/workspaces/t6-rt2").status_code == 404


def test_create_validation_and_conflict():
    c = TestClient(app)
    assert c.post("/api/workspaces", json={}).status_code == 400
    c.post("/api/workspaces", json={"name": "t6-dup"})
    assert c.post("/api/workspaces", json={"name": "t6-dup"}).status_code == 409
