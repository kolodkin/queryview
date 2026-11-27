# Contributing to QueryView

QueryView is a **Python** backend (**FastAPI + SQLModel**) serving `/api/*`, a
**Vite + React + TypeScript** SPA with **Tailwind CSS**, and a
**[Playwright](https://playwright.dev)** end-to-end suite. This page covers
working on it; [README.md](README.md) covers running it.

## Layout

```
.
├── backend/         # Python FastAPI + SQLModel app exposing /api/* (queryview package)
├── frontend/        # Vite + React + TS + Tailwind v4 SPA (npm workspace)
├── e2e/             # Playwright (TypeScript) browser tests
├── docs/            # Docs by V-model layer: user_guide, architecture, designs
├── pyproject.toml   # Backend deps + console script + `test` group (uv)
└── package.json     # npm workspace root: dev orchestration, frontend build, e2e
```

## Design docs

The user guide is listed in [README.md](README.md#documentation); the
layers are described in [docs/AGENTS.md](docs/AGENTS.md).

### Architecture

- [overview.md](docs/architecture/overview.md) — the components and the contracts between them.
- [api.md](docs/architecture/api.md) — the full HTTP endpoint reference.
- [viewer_server_api.md](docs/architecture/viewer_server_api.md) — the viewer server's endpoints.
- [storage.md](docs/architecture/storage.md) — the data directory, migrations, connection table, encryption, CI.
- [sessions.md](docs/architecture/sessions.md) — how a session is stored and how a tab claims one.
- [mcp.md](docs/architecture/mcp.md) — the MCP tools and the channel behind arming.
- [dashboards.md](docs/architecture/dashboards.md) — running a dashboard's queries and its sandbox.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) — runs the Python backend and its tests
  (it manages the Python toolchain and dependencies for you).
- [Node.js](https://nodejs.org) 20+ (with npm) — runs the root tasks, the Vite
  frontend and the Playwright e2e suite.

## Install

Install the backend's Python dependencies (uv reads the root `pyproject.toml`;
the package lives in `backend/queryview`):

```bash
uv sync
```

Install the JavaScript dependencies (the frontend workspace and Playwright) and
fetch the Playwright browser:

```bash
npm install
npx playwright install chromium
```

## Run dev servers

Run backend and frontend together:

```bash
npm run dev
```

Or individually:

```bash
npm run backend    # the API alone, reloading: `queryview --api-only --reload --host 127.0.0.1` on http://localhost:8000
npm run frontend   # http://localhost:5173
```

The Vite dev server proxies `/api/*` to the FastAPI backend, so the SPA can call the API on the same origin.

To serve everything from one backend on any port, run `PORT=<port> npm run debug`
(default 8000): the backend reloads on Python changes and `frontend/dist` is
rebuilt on save (refresh the browser to see frontend changes). It uses the same
`~/.queryview` state as an installed QueryView; set `DATA_DIR` for a throwaway one.

The repo's `.mcp.json` deliberately omits the queryview MCP server. In Claude
Code, `/debug <port>` runs `npm run debug` and registers the server in local
scope against that port.

## Build & preview production

```bash
npm run build      # produces frontend/dist/
npm run start      # `queryview`: FastAPI serves dist/ + /api on :8000
npm run preview    # build && start in one shot
```

In production there is no Vite — the FastAPI backend serves the bundled SPA from `frontend/dist/` and falls back to `index.html` for any unknown non-`/api` path so client-side routing works. Override the dist location with `STATIC_ROOT=/path/to/dist`.

## Tests

Backend tests live beside the code they test inside `backend/queryview`, and
ship in the wheel; the `vmodel_check` script's tests in `scripts/` do not:

```bash
uv run --group test pytest backend/queryview scripts
```

The e2e suite is [Playwright Test](https://playwright.dev/docs/intro) in
TypeScript (`e2e/*.spec.ts`, config in `playwright.config.ts`). Each worker
starts its own backend from `.venv` (so `uv sync` first) on a throwaway
`DATA_DIR`. `npm run e2e` builds the SPA (`build:e2e`, which shortens the
session heartbeat) and runs the suite; to skip the build, or pick tests:

```bash
npm run e2e
npx playwright test -g workspaces    # reuse the existing build
```

To test a server you started yourself (e.g. `npm run dev`, or a built preview),
point at it with `BASE_URL=http://localhost:5173 npx playwright test`; it then
runs on one worker. That server must run with `DATA_DIR` set to a scratch
folder: the suite writes dashboards, connections and sessions, and refuses a
backend on the default `~/.queryview`.

The suite needs a real ClickHouse (`:8123`), Postgres (`:5432`) and MySQL (`:3306`), the way CI
has them. The scripts under `claudeai/` install and run them locally (standalone
ClickHouse binary, a Postgres cluster and a MySQL 8.4 tarball under `.cache/`); they are written for
the Claude Code web container and refuse to run elsewhere unless you opt in:

```bash
CLAUDEAI_ALLOW_LOCAL=1 claudeai/run.sh      # install (first run) and start the databases
CLAUDEAI_ALLOW_LOCAL=1 claudeai/run.sh stop
```

## Lint & type-check

[pre-commit](https://pre-commit.com) runs ruff (lint + format) and pyright, the
same checks CI's `lint` job runs, and the vmodel check
(`scripts/vmodel_check.py`). A vmodel failure means a `req:` ID with no proving
test, a test naming an unknown ID, or an untagged page or test file; the rules
are in the `devpowers:vmodel` skill and `.claude/skills/vmodel/SKILL.md`. Pyright resolves imports from the project's
`.venv`, so sync first:

```bash
uv sync --group dev
uv run pre-commit install    # once, to run on every commit
uv run pre-commit run --all-files
```

## Release to PyPI

The **Publish to PyPI** workflow (`.github/workflows/publish.yaml`, manual
dispatch with a `vX.Y.Z` tag input) builds the SPA into the wheel
(`queryview/static/`), then gates the release on the installed wheel: an HTTP
smoke test, the packaged backend test suite (`pytest --pyargs queryview`), and
the Playwright e2e suite driving the packaged server (skippable via the
`skip-e2e` input for emergencies). It then publishes
[`queryview`](https://pypi.org/project/queryview/) via PyPI trusted publishing,
pushes the tag, and creates the GitHub release. The package version comes
from the tag (no version bump in `pyproject.toml`).

An installed wheel serves the bundled UI by default — see the
[quick start](README.md#quick-start).
