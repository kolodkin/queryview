#!/usr/bin/env bash
# Run the Playwright browser e2e suite locally against a real ClickHouse, the
# same way CI does: install the Playwright browser, ensure ClickHouse (via
# setup_clickhouse.sh) and Postgres, then run scripts/e2e.sh, which builds the
# SPA, serves it from a throwaway backend and drives a real Chromium.
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
# running; the backend e2e.sh starts is stopped on exit.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

BACKEND_PORT="${BACKEND_PORT:-8000}"
CLICKHOUSE_PORT="${CLICKHOUSE_PORT:-8123}"

log() { printf '\033[36m[browser]\033[0m %s\n' "$*"; }
die() { printf '\033[31m[browser] error:\033[0m %s\n' "$*" >&2; exit 1; }

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

# --- e2e (throwaway backend + DATA_DIR) ----------------------------------
BACKEND_PORT="$BACKEND_PORT" "$ROOT/scripts/e2e.sh"
