"""The SPA catch-all: real files, the index.html fallback for client routes,
and a 404 for a missing file, so a broken build fails loudly."""

import asyncio

import pytest
from fastapi.responses import FileResponse

from queryview import main


@pytest.fixture
def static_root(tmp_path, monkeypatch):
    """A built-SPA folder; the process caches its root, so each test clears it."""
    (tmp_path / "index.html").write_text("<!doctype html>")
    (tmp_path / "widgets.js").write_text("// bundle")
    monkeypatch.setenv("STATIC_ROOT", str(tmp_path))
    main._static_root.cache_clear()
    yield tmp_path
    main._static_root.cache_clear()


def test_static_serves_files_routes_and_404s_missing_files(static_root):
    tmp_path = static_root

    def serve(path: str):
        return asyncio.run(main._serve_static(path))

    file = serve("widgets.js")
    assert isinstance(file, FileResponse) and str(file.path) == str(tmp_path / "widgets.js")
    route = serve("dashboard")  # a client-side route gets the app
    assert isinstance(route, FileResponse) and str(route.path) == str(tmp_path / "index.html")
    assert serve("assets/gone-1234.js").status_code == 404
    assert serve("../outside.js").status_code == 404


def test_only_content_addressed_files_are_cached_for_good(static_root):
    (static_root / "assets").mkdir()
    (static_root / "assets" / "index-abc123.js").write_text("// app")

    def cache(path: str, versioned: bool = False):
        return asyncio.run(main._serve_static(path, versioned)).headers.get("cache-control")

    forever = "public, max-age=31536000, immutable"
    assert cache("assets/index-abc123.js") == forever  # Vite puts a content hash in the name
    assert cache("widgets.js", versioned=True) == forever  # the app asks for /widgets.js?v=<hash>
    assert cache("widgets.js") is None
    assert cache("dashboard") is None  # index.html must never be cached for good
