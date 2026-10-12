#!/usr/bin/env bash
# One-time install for the Claude Code web environment: project deps plus the
# e2e backing services (ClickHouse and Postgres), left running afterwards.
#
#   1. npm ci / uv sync        — frontend + backend + test deps
#   2. Playwright Chromium     — the revision pinned by uv.lock (no-op if present)
#   3. setup_clickhouse.sh     — download the standalone binary into .cache/,
#                                start a server on :8123
#   4. setup_postgres.sh       — initdb a cluster in .cache/pgdata, start a
#                                server on :5432
#
# Binaries and data under .cache/ survive a container suspend/resume; the
# server processes don't. Use claudeai/run.sh to bring them back up.
#
# Usage:
#   claudeai/setup.sh
#
# Env overrides: CLICKHOUSE_PORT (8123), PGPORT (5432), PGUSER (postgres).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
. "$ROOT/claudeai/_guard.sh"
cd "$ROOT"

log() { printf '\033[36m[setup]\033[0m %s\n' "$*"; }
die() { printf '\033[31m[setup] error:\033[0m %s\n' "$*" >&2; exit 1; }

command -v uv >/dev/null 2>&1 || die "uv not found — install from https://docs.astral.sh/uv/"
command -v npm >/dev/null 2>&1 || die "npm not found — install Node.js from https://nodejs.org"

log "installing frontend deps"
npm ci
log "installing backend + test deps"
uv sync --frozen --group test

# The web container ships a Chromium under PLAYWRIGHT_BROWSERS_PATH, but its
# revision need not match the playwright pinned in uv.lock, and the suite
# refuses a mismatched one. `playwright install` is a no-op when the pinned
# revision is already there, so always run it; it installs next to the
# pre-shipped one. System deps are only pulled in outside the web container,
# which already has them.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ] && [ "$(id -u)" = "0" ] && command -v apt-get >/dev/null 2>&1; then
  log "installing Playwright Chromium (+ system deps)"
  uv run --frozen --group test playwright install --with-deps chromium
else
  log "installing Playwright Chromium (pinned revision)"
  uv run --frozen --group test playwright install chromium
fi

"$ROOT/claudeai/setup_clickhouse.sh"
"$ROOT/claudeai/setup_postgres.sh"

log "done — services are up; use claudeai/run.sh to restart them in a new session"
