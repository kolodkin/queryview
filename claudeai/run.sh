#!/usr/bin/env bash
# Start (or stop) the e2e backing services: ClickHouse on :8123, Postgres on
# :5432, MySQL on :3306 and a loopback git daemon on :9418 serving a fresh bare
# repo for the git-sync e2e. Each claudeai/setup_<svc>.sh reuses a server
# already listening, installs under .cache/ when missing, then starts it.
# Binaries and data under .cache/ survive a container suspend/resume; the
# processes don't, so run this at the start of each session.
#
# Usage:
#   claudeai/run.sh          # start all
#   claudeai/run.sh stop     # stop all (reverse order)
#
# Env overrides: CLICKHOUSE_PORT (8123), PGPORT (5432), PGUSER (postgres), MYSQL_PORT (3306),
# GIT_DAEMON_PORT (9418). Run the e2e suite with
# E2E_GIT_REMOTE=git://127.0.0.1:9418/queryview.git.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
. "$ROOT/claudeai/_guard.sh"

# One entry per claudeai/setup_<svc>.sh; stopped in reverse order.
SERVICES=(clickhouse postgres mysql git_daemon)

log() { printf '\033[32m[run]\033[0m %s\n' "$*"; }

usage() { echo "usage: $0 [start|stop]" >&2; exit 2; }
[ $# -le 1 ] || usage

case "${1:-start}" in
  stop)
    failed=()
    for ((i = ${#SERVICES[@]} - 1; i >= 0; i--)); do
      "$ROOT/claudeai/setup_${SERVICES[i]}.sh" stop || failed+=("${SERVICES[i]}")   # keep stopping the rest
    done
    if ((${#failed[@]})); then
      echo "[run] failed to stop: ${failed[*]}" >&2
      exit 1
    fi
    log "all services stopped"
    exit 0
    ;;
  start) ;;
  *) usage ;;
esac

for svc in "${SERVICES[@]}"; do
  "$ROOT/claudeai/setup_$svc.sh"
done
log "all services up — run e2e with E2E_GIT_REMOTE=git://127.0.0.1:${GIT_DAEMON_PORT:-9418}/queryview.git"
