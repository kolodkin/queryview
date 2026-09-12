#!/usr/bin/env bash
# Run the Playwright browser e2e suite locally against a real ClickHouse, the
# same way CI does: install the Playwright browser, ensure ClickHouse (via
# setup_clickhouse.sh), build the SPA, serve it from the FastAPI backend, and
# drive a real Chromium.
#
# Usage:
#   scripts/setup_browser.sh
#
# Environment overrides:
#   BACKEND_PORT      backend / BASE_URL port            (default 8000)
#   CLICKHOUSE_PORT   ClickHouse HTTP port               (default 8123)
#   PGPORT            Postgres TCP port                  (default 5432)
#
# The ClickHouse and Postgres servers are owned by their setup scripts and left
# running; the backend this script starts is stopped on exit.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

BACKEND_PORT="${BACKEND_PORT:-8000}"
CLICKHOUSE_PORT="${CLICKHOUSE_PORT:-8123}"
CACHE="$ROOT/.cache"
mkdir -p "$CACHE"

BACKEND_PID=""
cleanup() { [ -n "$BACKEND_PID" ] && kill "$BACKEND_PID" 2>/dev/null || true; }
trap cleanup EXIT

log() { printf '\033[36m[browser]\033[0m %s\n' "$*"; }
die() { printf '\033[31m[browser] error:\033[0m %s\n' "$*" >&2; exit 1; }

wait_for() { # url label
  for _ in $(seq 1 60); do
    curl -sf "$1" >/dev/null 2>&1 && { log "$2 is up"; return 0; }
    sleep 1
  done
  die "$2 did not come up at $1"
}

command -v uv >/dev/null 2>&1 || die "uv not found — install from https://docs.astral.sh/uv/"
command -v npm >/dev/null 2>&1 || die "npm not found — install Node.js from https://nodejs.org"

# --- deps + Playwright browser -------------------------------------------
log "installing frontend deps"
npm ci
log "installing backend + test deps"
uv sync --frozen --group test
log "installing Playwright Chromium"
if [ "$(id -u)" = "0" ] && command -v apt-get >/dev/null 2>&1; then
  uv run --frozen --group test playwright install --with-deps chromium
else
  uv run --frozen --group test playwright install chromium
fi

# --- Databases (delegated) ----------------------------------------------
CLICKHOUSE_PORT="$CLICKHOUSE_PORT" "$ROOT/scripts/setup_clickhouse.sh"
PGPORT="${PGPORT:-5432}" "$ROOT/scripts/setup_postgres.sh"

# --- Frontend build + backend -------------------------------------------
log "building SPA"
npm run build -w frontend
log "starting backend (serving built SPA) on :$BACKEND_PORT"
SERVE_STATIC=1 PORT="$BACKEND_PORT" DATA_DIR="${DATA_DIR:-$CACHE/data}" \
  uv run --frozen queryview-backend \
  > "$CACHE/backend.log" 2>&1 &
BACKEND_PID=$!
wait_for "http://localhost:$BACKEND_PORT/api/health" "backend"

# --- e2e -----------------------------------------------------------------
log "running Playwright e2e tests"
BASE_URL="http://localhost:$BACKEND_PORT" \
  uv run --frozen --group test pytest e2e \
    --tracing retain-on-failure \
    --html=report/index.html --self-contained-html

log "done. HTML report at report/index.html"
