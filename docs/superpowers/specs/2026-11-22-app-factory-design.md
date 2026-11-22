# App factory instead of `SERVE_STATIC`

## Intent

Whether the app serves the built frontend is chosen today by an env var read
at import (`SERVE_STATIC`), which registers one of two catch-all routes. Make
it an argument instead: a factory builds the app, and each way of starting it
names the app it wants. No backwards compatibility is kept.

## Approaches

1. No modes: always serve the frontend when a build exists. Least code, but
   opening the API port during `npm run dev` shows a stale build.
2. One module per mode, the second importing the first and adding the
   catch-all. No factory, but two app objects built by side effect.
3. **A factory, `create_app(frontend: bool)`**, as the viewer server already
   has. **Picked.**

## Design

- `backend/queryview/main.py` becomes `backend/queryview/app.py`. Its 45
  routes move from `@app.…` to a module-level `APIRouter` (`@router.…`), so
  no route body changes or re-indents. No app object is built at import.
- `create_app(frontend: bool = True) -> FastAPI` in `app.py` builds the app:
  the lifespan, the MCP mount, the session middleware, the router, and, only
  with `frontend=True`, the frontend catch-all. Without it a non-API path is
  FastAPI's own 404.
- The mode is a command-line argument. `backend/queryview/__main__.py` is the
  one entry point, behind both the `queryview` command and
  `python -m queryview`:

  | Argument | Meaning |
  | --- | --- |
  | `--port N` | as today: the flag, else `PORT`, else 8000 |
  | `--api-only` | no frontend: the API beside Vite |
  | `--reload` | restart on code changes, for development |

- `--reload` makes uvicorn re-import the app by name, and a name cannot carry
  an argument. So `app.py` also has `create_api_app()`, which is
  `create_app(frontend=False)`, and the entry point hands uvicorn one of the
  two factory names.
- The dev scripts go through the command: `npm run backend` is
  `queryview --api-only --reload`, `npm run debug` is `queryview --reload`,
  `npm run start` is `queryview`.
- `SERVE_STATIC` is deleted: the env read, the `if/else`, and its uses in
  `package.json`, `e2e/fixtures.ts` and `CONTRIBUTING.md`.
- The `queryview-backend` command, a duplicate of `queryview`, is deleted;
  the e2e fixture and the release workflow's comment name `queryview`.
- A frontend route with no build on disk is a 404 rather than a failed file
  response (`serving.serve_static`).
- Tests: the nine files that import `app` from `queryview.main` take one
  shared `create_app()` from `conftest.py` instead. New tests: `--api-only`
  and `--reload` pick the right factory; the API-only app answers `/` with a
  404 while the full one serves the page; the missing-build 404. The e2e
  suite passes.

## Non-goals

- Touching the viewer server, which already has its own factory and command.
- A `python -m` entry for the viewer server.
