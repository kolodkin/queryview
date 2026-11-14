"""The SPA catch-all: real files, the index.html fallback for client routes,
and a 404 for a missing file, so a broken build fails loudly."""

import asyncio

from fastapi.responses import FileResponse

from queryview import main


def test_static_serves_files_routes_and_404s_missing_files(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("<!doctype html>")
    (tmp_path / "widgets.js").write_text("// bundle")
    monkeypatch.setenv("STATIC_ROOT", str(tmp_path))

    def serve(path: str):
        return asyncio.run(main._serve_static(path))

    file = serve("widgets.js")
    assert isinstance(file, FileResponse) and str(file.path) == str(tmp_path / "widgets.js")
    route = serve("dashboard")  # a client-side route gets the app
    assert isinstance(route, FileResponse) and str(route.path) == str(tmp_path / "index.html")
    assert serve("assets/gone-1234.js").status_code == 404
    assert serve("../outside.js").status_code == 404
