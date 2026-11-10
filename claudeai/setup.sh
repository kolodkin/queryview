#!/usr/bin/env bash
# One-time install for the Claude Code web environment: project deps plus the
# e2e backing services (ClickHouse, Postgres, git daemon), left running afterwards.
#
#   1. npm ci / uv sync        — frontend + e2e + backend deps
#   2. Playwright Chromium     — the revision pinned by package-lock.json
#   3. setup_clickhouse.sh     — download the standalone binary into .cache/,
#                                start a server on :8123
#   4. setup_postgres.sh       — initdb a cluster in .cache/pgdata, start a
#                                server on :5432
#   5. setup_git_daemon.sh     — a loopback git daemon on :9418 serving a bare
#                                repo in .cache/gitsrv for the git-sync e2e
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

# The web container ships a Chromium that playwright.config.ts launches
# directly (it can't download the pinned revision), so skip the install there.
# System deps are pulled in only when running as root with apt.
if [ "${CLAUDE_CODE_REMOTE:-}" = "true" ]; then
  log "using the web container's pre-installed Chromium"
elif [ "$(id -u)" = "0" ] && command -v apt-get >/dev/null 2>&1; then
  log "installing Playwright Chromium (+ system deps)"
  npx playwright install --with-deps chromium
else
  log "installing Playwright Chromium (pinned revision)"
  npx playwright install chromium
fi

"$ROOT/claudeai/setup_clickhouse.sh"
"$ROOT/claudeai/setup_postgres.sh"
"$ROOT/claudeai/setup_git_daemon.sh"

log "done — services are up; use claudeai/run.sh to restart them in a new session"
