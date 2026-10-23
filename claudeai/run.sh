#!/usr/bin/env bash
# Start (or stop) the e2e backing services that claudeai/setup.sh installed:
# ClickHouse on :8123 and Postgres on :5432, plus a loopback git daemon on
# :9418 serving a fresh bare repo for the git-sync e2e (what CI's
# start-git-daemon action does). Idempotent — reuses anything already
# listening. Only starts what is installed; a missing binary or cluster is an
# error that points at the matching setup_<svc>.sh.
#
# Usage:
#   claudeai/run.sh          # start both
#   claudeai/run.sh stop     # stop both (reverse order)
#
# Env overrides: CLICKHOUSE_PORT (8123), PGPORT (5432), PGUSER (postgres).
# Run the e2e suite with E2E_GIT_REMOTE=git://127.0.0.1:9418/queryview.git.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
. "$ROOT/claudeai/_guard.sh"
CACHE="$ROOT/.cache"

log() { printf '\033[32m[run]\033[0m %s\n' "$*"; }
die() { printf '\033[31m[run] error:\033[0m %s\n' "$*" >&2; exit 1; }

GITSRV="$CACHE/gitsrv"
GIT_PID="$CACHE/git-daemon.pid"
git_daemon_up() { (exec 3<>/dev/tcp/127.0.0.1/9418) 2>/dev/null; }

if [ "${1:-}" = "stop" ]; then
  if [ -s "$GIT_PID" ]; then
    kill "$(cat "$GIT_PID")" 2>/dev/null || true
    rm -f "$GIT_PID"
    log "git daemon stopped"
  fi
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

# A fresh empty remote per start, as CI gets one per run: rerun this before
# an e2e run, or a dashboard committed last time reads as "No changes".
rm -rf "$GITSRV/queryview.git"
mkdir -p "$GITSRV"
git init -q --bare -b main "$GITSRV/queryview.git"
if git_daemon_up; then
  log "git daemon already up on :9418 (remote reset)"
else
  git daemon --reuseaddr --listen=127.0.0.1 --port=9418 \
    --base-path="$GITSRV" --export-all --enable=receive-pack \
    --detach --pid-file="$GIT_PID"
  for _ in $(seq 1 30); do
    git_daemon_up && break
    sleep 1
  done
  git_daemon_up || die "git daemon failed to become ready on :9418"
  log "git daemon up on :9418"
fi
log "all services up — run e2e with E2E_GIT_REMOTE=git://127.0.0.1:9418/queryview.git"
