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
  no route body changes or re-indents.
- `create_app(frontend: bool) -> FastAPI` in `app.py` builds the app: the
  lifespan, the MCP mount, the session middleware, the router, and, only
  with `frontend=True`, the frontend catch-all. Without it a non-API path is
  FastAPI's own 404.
- Three small modules name an app:

  | Module | Holds | Started by |
  | --- | --- | --- |
  | `queryview/main.py` | `app = create_app(frontend=True)`, `run()` | the `queryview` command, `npm run debug`, `npm run start` |
  | `queryview/api.py` | `app = create_app(frontend=False)` | `npm run backend` (the API beside Vite) |
  | `queryview/__main__.py` | calls `run()` | `python -m queryview` |

- `SERVE_STATIC` is deleted: the env read, the `if/else`, and its uses in
  `package.json`, `e2e/fixtures.ts` and `CONTRIBUTING.md`.
- The `queryview-backend` command, a duplicate of `queryview`, is deleted;
  the e2e fixture and the release workflow's comment name `queryview`.
- A frontend route with no build on disk is a 404 rather than a failed file
  response (`serving.serve_static`).
- Tests: the existing suites pass with their `from queryview.main import app`
  unchanged; one new test that `api.app` answers `/` with a 404 while
  `main.app` serves the page; one for the missing-build 404. The e2e suite
  passes.

## Non-goals

- Touching the viewer server, which already has its own factory and command.
- A `python -m` entry for the viewer server.
