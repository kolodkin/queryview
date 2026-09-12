# QueryView

Project skeleton: **Python** backend (**FastAPI + SQLModel**) + **Vite + React + TypeScript** SPA frontend with **Tailwind CSS**, plus **[Playwright](https://playwright.dev)** end-to-end tests.

## Quick start

Run the released package — API + bundled SPA on http://localhost:8000:

```bash
uvx queryview
```

`--port` (or the `PORT` env var) picks the listen port, default 8000:
`uvx queryview --port 9000`.

Or run the container image — every release publishes
`ghcr.io/kolodkin/queryview` to GHCR for `linux/amd64` and `linux/arm64`, tagged
`vX.Y.Z` and (for non-pre-releases) `latest`:

```bash
docker run -p 8000:8000 ghcr.io/kolodkin/queryview:latest
```

To serve on a different host port, remap it (the container keeps listening on
8000, which its healthcheck probes): `docker run -p 9000:8000 ...`. QueryView
expects to be reached from localhost only, so prefer binding the published port
to loopback: `docker run -p 127.0.0.1:8000:8000 ...`.

The command above keeps its state inside the container, so connections and
workspaces are lost when the container is removed. See
[Run with Docker](#run-with-docker) for a persistent setup.

## Run with Docker

The image runs as the non-root user `queryview` (UID 1000) and sets
`DATA_DIR=/var/lib/queryview`, so every piece of state lives directly under that
one directory:

| Path | Contents |
|---|---|
| `/var/lib/queryview/db.sqlite` | SQLite store: connections, workspaces, queries, dashboards |
| `/var/lib/queryview/encryption.key` | Key that encrypts stored connection passwords |
| `/var/lib/queryview/gitsync/` | Local clones used by workspace git sync |

Mount a volume at `/var/lib/queryview` and all three persist across container
restarts, removals and upgrades.

### Persisting it

```bash
mkdir -p "$HOME/.queryview"
docker run -d --name queryview \
  -p 127.0.0.1:8000:8000 \
  -v "$HOME/.queryview:/var/lib/queryview" \
  ghcr.io/kolodkin/queryview:latest
```

Create the directory first so Docker doesn't create it owned by root. The
container runs as UID 1000, the first user on most Linux distributions; if
`id -u` prints something else, add `--user "$(id -u):$(id -g)"` so the
container writes the files as you.

Two variants on that mount:

- **Let Docker own the location.** Swap the path for a named volume,
  `-v queryview-data:/var/lib/queryview`. Docker seeds it from the image, so
  ownership is already right and there is nothing to create up front. The
  volume outlives `docker rm`; only `docker volume rm` deletes it.
- **Share with a local `uvx queryview`.** Point the mount at its data
  directory, `~/.local/share/queryview`, and the container and a local run use
  one database, key and set of clones. Don't run both against it at once:
  each would serve the same SQLite file.

### Git sync

The image ships `git`, so workspace git sync (see
[docs/gitsync.md](docs/gitsync.md)) works in the container; clones live under
`/var/lib/queryview/gitsync/`, which the mount above already covers. What is
left is authenticating to the remote.

Use an HTTPS remote with a token, which needs nothing beyond the URL:

```
https://<token>@github.com/<org>/<repo>.git
```

Scope the token to the one repository and give it an expiry. QueryView stores
the URL encrypted alongside the workspace, but git also writes it verbatim into
each clone's config, so treat the data directory as holding a live credential
and guard backups of it accordingly.

SSH works too, but it is the harder path in a container: a passphrase cannot be
entered, an unknown host key cannot be written into a read-only mount, and the
key must be owned by UID 1000 as the container sees it. If you need it, mount a
dedicated deploy key rather than your whole `.ssh` directory, which would hand
the container every key you own:

```bash
docker run -d --name queryview \
  -p 127.0.0.1:8000:8000 \
  -v "$HOME/.queryview:/var/lib/queryview" \
  -v ~/.ssh/queryview_deploy:/home/queryview/.ssh/id_ed25519:ro \
  -v ~/.ssh/known_hosts:/home/queryview/.ssh/known_hosts:ro \
  ghcr.io/kolodkin/queryview:latest
```

## Layout

```
.
├── backend/         # Python FastAPI + SQLModel app exposing /api/* (queryview package)
├── frontend/        # Vite + React + TS + Tailwind v4 SPA (npm workspace)
├── e2e/             # Playwright (pytest) browser tests
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

## End-to-end tests

The e2e suite is [pytest-playwright](https://playwright.dev/python/docs/test-runners),
installed via the `test` dependency group and run through `uv`.

Start the dev servers (`npm run dev`) in one terminal, then in another:

```bash
uv run --group test pytest
```

Override the target URL with `BASE_URL=http://localhost:4173 uv run --group test pytest` (e.g. to test a built preview). To run the full suite against a real ClickHouse the way CI does, use `scripts/setup.sh`.

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

An installed wheel serves the bundled UI by default — see
[Quick start](#quick-start).

## MCP server

The backend mounts a FastMCP server (Streamable HTTP) at
`http://localhost:8000/mcp/`. There is nothing extra to start — it runs inside
the server process (`uvx queryview`, `npm run dev`, ...). Registering the client
is a separate, one-time step on the machine running the agent: an HTTP MCP
server can't install itself into someone else's client.

```bash
claude mcp add --transport http queryview http://localhost:8000/mcp/
```

Three things to get right:

- **Prefer the trailing slash.** The mount serves `/mcp/`. The slashless
  `/mcp` also works — it 307-redirects — but registering the canonical path
  skips a round trip on every call.
- **Match the port.** The URL must point at the port QueryView actually
  listens on — `--port 9000` means `http://localhost:9000/mcp/`, and
  `docker run -p 9000:8000` means the *host* port, `9000`, not the container's
  `8000`.
- **Start QueryView first.** The client dials this URL when it starts; if
  nothing is listening it reports a connection error and stays failed until you
  reconnect it.

QueryView is a **local, single-user tool**: it assumes it is reachable only from
localhost. `/mcp/` is unauthenticated, and its tools can query every configured
connection and rewrite workspace git state, so don't publish the port. Bind the
container to loopback — `docker run -p 127.0.0.1:8000:8000 ...` — since a plain
`-p 8000:8000` listens on all interfaces.

Tools: `run_query` (read-only SQL, rows returned to the agent), `push_query`
and `push_dashboard` (fill a live browser session), `list_queries` /
`list_dashboards`, and `git_store` / `git_history` / `git_restore` (workspace
git backups). The push tools target an **armed** browser session: enable
"Allow remote control" from the agent icon next to the connection pill and use
the session id it shows. See [docs/remote.md](docs/remote.md) for the full
protocol.

## API

See [docs/api.md](docs/api.md) for the full endpoint reference.

The single-page prompt UI is described in [docs/queryview.md](docs/queryview.md);
connecting (`new <type>` / `connect <name>`), SQLite persistence, and session
auto-connect are specified in [docs/connect.md](docs/connect.md).

All state lives in one data directory, which defaults to the platform's
user-data directory: `~/.local/share/queryview/` on Linux,
`~/Library/Application Support/queryview/` on macOS, and
`%LOCALAPPDATA%\queryview\` on Windows. `DATA_DIR` moves it. Inside are the
SQLite store `db.sqlite`, the local password-encryption key `encryption.key`,
and the workspace git-sync clones under `gitsync/`.
