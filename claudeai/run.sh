#!/usr/bin/env bash
# Start (or stop) the e2e backing services that claudeai/setup.sh installed:
# ClickHouse on :8123, Postgres on :5432 and a loopback git daemon on :9418
# serving a fresh bare repo for the git-sync e2e. Idempotent — reuses anything
# already listening. Only starts what is installed; a missing binary or
# cluster is an error that points at the matching setup_<svc>.sh.
#
# Usage:
#   claudeai/run.sh          # start both
#   claudeai/run.sh stop     # stop both (reverse order)
#
# Env overrides: CLICKHOUSE_PORT (8123), PGPORT (5432), PGUSER (postgres),
# GIT_DAEMON_PORT (9418). Run the e2e suite with
# E2E_GIT_REMOTE=git://127.0.0.1:9418/queryview.git.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
. "$ROOT/claudeai/_guard.sh"
CACHE="$ROOT/.cache"

log() { printf '\033[32m[run]\033[0m %s\n' "$*"; }
die() { printf '\033[31m[run] error:\033[0m %s\n' "$*" >&2; exit 1; }

if [ "${1:-}" = "stop" ]; then
  "$ROOT/claudeai/setup_git_daemon.sh" stop
  "$ROOT/claudeai/setup_postgres.sh" stop
  "$ROOT/claudeai/setup_clickhouse.sh" stop
  log "all services stopped"
  exit 0
fi

[ -x "$CACHE/clickhouse" ] \
  || die "clickhouse binary missing ($CACHE/clickhouse) — run claudeai/setup_clickhouse.sh first"
[ -s "$CACHE/pgdata/PG_VERSION" ] \
  || die "postgres cluster missing ($CACHE/pgdata) — run claudeai/setup_postgres.sh first"

"$ROOT/claudeai/setup_clickhouse.sh"
"$ROOT/claudeai/setup_postgres.sh"
"$ROOT/claudeai/setup_git_daemon.sh"
log "all services up — run e2e with E2E_GIT_REMOTE=git://127.0.0.1:${GIT_DAEMON_PORT:-9418}/queryview.git"
