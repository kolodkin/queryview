"""What both entrypoints (the app and the viewer server) share to serve: the
built frontend files and the listen port."""

from __future__ import annotations

import argparse
import os
from functools import lru_cache
from pathlib import Path

from fastapi.responses import FileResponse, JSONResponse, Response

# Frontend bundle shipped inside the wheel (release CI copies frontend/dist here);
# absent in a source checkout, where the repo's frontend/dist is used instead.
PACKAGED_STATIC = Path(__file__).resolve().parent / "static"


@lru_cache(maxsize=1)
def static_root() -> Path:
    env = os.environ.get("STATIC_ROOT")
    if env:
        return Path(env).resolve()
    repo_dist = (Path(__file__).resolve().parent.parent.parent / "frontend" / "dist").resolve()
    if repo_dist.is_dir():
        return repo_dist
    return PACKAGED_STATIC


# Vite names everything under assets/ by content, and a page asks for the
# widget bundle as /widgets.js?v=<content hash>: either can be cached for good.
_FOREVER = {"Cache-Control": "public, max-age=31536000, immutable"}


async def serve_static(full_path: str, versioned: bool = False, index: str | None = "index.html") -> Response:
    """A built file, or `index` for a client-side route (None: the page has no
    routes, so only files are served). A missing path with a file extension is
    a missing file, not a route: 404, so a broken build fails loudly instead of
    handing a script the app's HTML. So is any route when nothing was built."""
    root = static_root()
    candidate = (root / full_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return JSONResponse({"error": "not found"}, status_code=404)
    if candidate.is_file():
        cached = versioned or full_path.startswith("assets/")
        return FileResponse(candidate, headers=_FOREVER if cached else None)
    # No page to fall back to: the path names a file, the caller has no routes,
    # or nothing was built.
    if candidate.suffix or index is None or not (root / index).is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(root / index)


def resolve_port(argv: list[str] | None = None, prog: str = "queryview") -> int:
    """Listen port: --port beats the PORT env var, which beats 8000."""
    parser = argparse.ArgumentParser(prog=prog)
    parser.add_argument("--port", type=int, help="listen port (default: $PORT or 8000)")
    args = parser.parse_args(argv)
    if args.port is not None:
        return args.port
    return int(os.environ.get("PORT", "8000"))
