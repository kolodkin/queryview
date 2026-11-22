"""The app factory: one set of routes, with or without the built frontend.
Nothing is built at import; the entry point names the factory it wants."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import queryview.app
from queryview import serving
from queryview.app import create_api_app, create_app


@pytest.fixture
def built(tmp_path, monkeypatch):
    """A built frontend on disk; the process caches its root, so each test clears it."""
    (tmp_path / "index.html").write_text("<!doctype html>")
    monkeypatch.setenv("STATIC_ROOT", str(tmp_path))
    serving.static_root.cache_clear()
    yield tmp_path
    serving.static_root.cache_clear()


def test_the_full_app_serves_the_frontend(built):
    c = TestClient(create_app())
    assert c.get("/").text == "<!doctype html>"
    assert c.get("/dashboard").text == "<!doctype html>"  # a client-side route gets the app


def test_the_api_only_app_serves_no_frontend(built):
    c = TestClient(create_api_app())
    assert c.get("/").status_code == 404 and c.get("/dashboard").status_code == 404
    assert c.get("/api/health").status_code == 200


@pytest.mark.parametrize("make", [create_app, create_api_app])
def test_both_apps_have_the_api_and_the_mcp_redirect(make):
    c = TestClient(make(), follow_redirects=False)
    assert c.get("/api/health").json()["status"] == "ok"
    r = c.get("/api/nope")
    assert r.status_code == 404 and r.json() == {"error": "not found"}
    r = c.post("/mcp")
    assert r.status_code == 307 and r.headers["location"] == "/mcp/"


def test_the_session_header_reaches_the_routes():
    r = TestClient(create_app(), headers={"X-QV-Session": "factory-test"}).get("/api/session")
    assert r.status_code == 200 and r.json()["connected"] is False


def test_importing_the_module_builds_no_app():
    assert not hasattr(queryview.app, "app")
