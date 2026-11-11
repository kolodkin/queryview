"""The MCP mount's slashless path.

The MCP app is mounted at `/mcp` with its own path set to `/`, so the
canonical endpoint is `/mcp/`. Starlette would normally redirect `/mcp` there,
but the SPA catch-all (`@app.get("/{full_path:path}")`) matches the slashless
path on GET only, which Starlette scores as a partial match — that suppresses
the redirect and answers `405 allow: GET` instead, pointing a client at a path
the MCP server never serves. These tests pin the redirect so the catch-all
can't swallow it again.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from queryview.main import app

# Streamable HTTP uses POST (messages), GET (the SSE stream) and DELETE
# (session termination) — all three must reach the mount.
MCP_METHODS = ["POST", "GET", "DELETE"]


@pytest.mark.parametrize("method", MCP_METHODS)
def test_slashless_mcp_redirects_to_canonical_path(method):
    c = TestClient(app, follow_redirects=False)
    r = c.request(method, "/mcp")
    assert r.status_code == 307, f"{method} /mcp returned {r.status_code}, not a redirect"
    assert r.headers["location"].endswith("/mcp/")


@pytest.mark.parametrize("method", MCP_METHODS)
def test_canonical_mcp_path_is_not_redirected(method):
    """The redirect must not shadow the mount itself."""
    c = TestClient(app, follow_redirects=False, raise_server_exceptions=False)
    r = c.request(method, "/mcp/")
    assert r.status_code != 307
    assert "location" not in r.headers
