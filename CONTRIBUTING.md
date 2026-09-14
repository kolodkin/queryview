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
├── e2e/             # Playwright (pytest) browser tests
├── docs/            # Feature and API documentation
├── pyproject.toml   # Backend deps + console script + e2e `test` group (uv)
└── package.json     # npm workspace root: dev orchestration + frontend build
```

## Prerequisites

- [uv](https://docs.astral.sh/uv/) — runs the Python backend and the Playwright
  (pytest) e2e suite (it manages the Python toolchain and dependencies for you).
- [Node.js](https://nodejs.org) 20+ (with npm) — runs the root tasks and the
  Vite frontend.

npm runs the frontend and the root task scripts; uv handles the backend's and
e2e suite's Python virtualenv and dependencies.

## Install

Install the backend's Python dependencies (uv reads the root `pyproject.toml`;
the package lives in `backend/queryview`):

```bash
uv sync
```

Install the JavaScript dependencies for the frontend workspace:

```bash
npm install
```

Install the e2e tooling (the `test` dependency group) and fetch the Playwright
browser:

```bash
uv sync --group test
uv run --group test playwright install chromium
```

## Run dev servers

Run backend and frontend together:

```bash
npm run dev
```

Or individually:

```bash
npm run backend    # uvicorn --reload on http://localhost:8000
npm run frontend   # http://localhost:5173
```

The Vite dev server proxies `/api/*` to the FastAPI backend, so the SPA can call the API on the same origin.

## Build & preview production

```bash
npm run build      # produces frontend/dist/
npm run start      # SERVE_STATIC=1, FastAPI serves dist/ + /api on :8000
npm run preview    # build && start in one shot
```

In production there is no Vite — the FastAPI backend serves the bundled SPA from `frontend/dist/` and falls back to `index.html` for any unknown non-`/api` path so client-side routing works. Override the dist location with `STATIC_ROOT=/path/to/dist`.

## Tests

Backend unit tests live beside the code they test inside `backend/queryview`,
and ship in the wheel:

```bash
uv run --group test pytest backend/queryview
```

The e2e suite is [pytest-playwright](https://playwright.dev/python/docs/test-runners),
installed via the `test` dependency group and run through `uv`. Start the dev
servers (`npm run dev`) in one terminal, then in another:

```bash
uv run --group test pytest
```

Override the target URL with `BASE_URL=http://localhost:4173 uv run --group test pytest` (e.g. to test a built preview). To run the full suite against a real ClickHouse the way CI does, use `scripts/setup.sh`.

## Lint & type-check

[pre-commit](https://pre-commit.com) runs ruff (lint + format) and pyright, the
same checks CI's `lint` job runs. Pyright resolves imports from the project's
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
