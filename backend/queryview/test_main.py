"""Tests for the console-script entry point (port resolution) and the UI-only
API gate."""

from fastapi.testclient import TestClient

from queryview import main
from queryview.main import app


def test_port_flag_beats_env(monkeypatch):
    monkeypatch.setenv("PORT", "7777")
    assert main._resolve_port(["--port", "9000"]) == 9000


def test_port_env_used_without_flag(monkeypatch):
    monkeypatch.setenv("PORT", "7777")
    assert main._resolve_port([]) == 7777


def test_port_defaults_to_8000(monkeypatch):
    monkeypatch.delenv("PORT", raising=False)
    assert main._resolve_port([]) == 8000


def _bare_client() -> TestClient:
    """A client without conftest's Sec-Fetch-Site shim: what curl or an agent sends."""
    c = TestClient(app)
    c.headers.pop("sec-fetch-site")
    return c


def test_api_refuses_non_browser_clients():
    r = _bare_client().get("/api/session")
    assert r.status_code == 403
    assert r.json() == {"ok": False, "message": main.UI_ONLY_MESSAGE}
    assert _bare_client().get("/api/health").status_code == 200
    assert TestClient(app).get("/api/session").status_code == 200


def test_cross_site_browser_request_refused():
    c = TestClient(app, headers={"Sec-Fetch-Site": "cross-site"})
    assert c.get("/api/session").status_code == 403
