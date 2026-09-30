#!/usr/bin/env bash
# Run the Playwright e2e suite against a backend on a fresh temp DATA_DIR, then
# delete it. The suite writes workspaces, dashboards, sessions and connections,
# so it must never point at a real ~/.queryview.
#
# Assumes deps, the Playwright browser and the databases are set up
# (scripts/setup_browser.sh does that, then calls this).
#
# Usage:
#   scripts/e2e.sh [pytest args...]      e.g. scripts/e2e.sh -k workspaces
#   npm run e2e -- [pytest args...]
#
# Environment overrides:
#   BACKEND_PORT   backend / BASE_URL port   (default: a free port)
#   SKIP_BUILD=1   reuse the existing frontend build
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

log() { printf '\033[36m[e2e]\033[0m %s\n' "$*"; }
die() { printf '\033[31m[e2e] error:\033[0m %s\n' "$*" >&2; exit 1; }

DATA_DIR="$(mktemp -d "${TMPDIR:-/tmp}/qv-e2e.XXXXXX")"
BACKEND_PID=""
cleanup() {
  [ -n "$BACKEND_PID" ] && kill "$BACKEND_PID" 2>/dev/null || true
  rm -rf "$DATA_DIR"
}
trap cleanup EXIT

if [ -n "${BACKEND_PORT:-}" ]; then
  # A server already answering there would take the tests, and it isn't ours.
  curl -sf "http://localhost:$BACKEND_PORT/api/health" >/dev/null 2>&1 &&
    die "port $BACKEND_PORT is already serving; pick another BACKEND_PORT"
else
  BACKEND_PORT="$(python3 -c 'import socket; s = socket.socket(); s.bind(("", 0)); print(s.getsockname()[1])')"
fi
BASE_URL="http://localhost:$BACKEND_PORT"
healthy() { curl -sf "$BASE_URL/api/health" >/dev/null 2>&1; }
fail() { cat "$DATA_DIR/backend.log"; die "$@"; }

if [ "${SKIP_BUILD:-}" != "1" ]; then
  log "building SPA"
  npm run build -w frontend
fi

log "starting backend on :$BACKEND_PORT (DATA_DIR=$DATA_DIR)"
SERVE_STATIC=1 PORT="$BACKEND_PORT" DATA_DIR="$DATA_DIR" \
  uv run --frozen queryview-backend > "$DATA_DIR/backend.log" 2>&1 &
BACKEND_PID=$!
tries=0
until healthy; do
  kill -0 "$BACKEND_PID" 2>/dev/null || fail "backend exited"
  (( ++tries <= 300 )) || fail "backend did not come up"
  sleep 0.2
done

log "running Playwright e2e tests"
BASE_URL="$BASE_URL" uv run --frozen --group test pytest e2e \
  --tracing retain-on-failure \
  --html=report/index.html --self-contained-html \
  "$@"

log "done. HTML report at report/index.html"
