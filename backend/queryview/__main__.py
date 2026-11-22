"""The entry point: the `queryview` command and `python -m queryview`."""

from __future__ import annotations

import uvicorn

from .serving import port_of, port_parser


def run(argv: list[str] | None = None) -> None:
    """Serve the app: with the built frontend, or the API alone beside a
    frontend dev server."""
    parser = port_parser("queryview")
    parser.add_argument("--api-only", action="store_true", help="serve the API without the built frontend")
    parser.add_argument("--reload", action="store_true", help="restart on code changes (development)")
    args = parser.parse_args(argv)
    # Named, not built here: a reloading server re-imports its app by name.
    factory = "queryview.app:create_api_app" if args.api_only else "queryview.app:create_app"
    uvicorn.run(factory, factory=True, host="0.0.0.0", port=port_of(args), reload=args.reload)


if __name__ == "__main__":
    run()
