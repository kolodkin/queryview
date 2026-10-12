#!/usr/bin/env bash
# Ensure a local ClickHouse server is available for the e2e suite.
#
# Reuses one already listening on $CLICKHOUSE_PORT. Otherwise it downloads the
# standalone `clickhouse` binary into .cache/ and starts a server in the
# background, left running (pid in .cache/clickhouse.pid) so other scripts can
# use it. Safe to run repeatedly.
#
# Usage:
#   claudeai/setup_clickhouse.sh          # ensure a server is running
#   claudeai/setup_clickhouse.sh stop     # stop the server this script started
#
# Env:
#   CLICKHOUSE_PORT   ClickHouse HTTP port (default 8123)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
. "$ROOT/claudeai/_guard.sh"
CACHE="$ROOT/.cache"
CLICKHOUSE_PORT="${CLICKHOUSE_PORT:-8123}"
PIDFILE="$CACHE/clickhouse.pid"

log() { printf '\033[35m[clickhouse]\033[0m %s\n' "$*"; }
die() { printf '\033[31m[clickhouse] error:\033[0m %s\n' "$*" >&2; exit 1; }

# Kill a pid and all its descendants. The standalone clickhouse binary forks a
# launcher -> server pair, so killing just the recorded pid orphans the server.
kill_tree() {
  local p=$1 c
  for c in $(pgrep -P "$p" 2>/dev/null || true); do kill_tree "$c"; done
  kill "$p" 2>/dev/null || true
}

if [ "${1:-}" = "stop" ]; then
  if [ -f "$PIDFILE" ]; then
    pid=$(cat "$PIDFILE")
    kill_tree "$pid"
    log "stopped (pid $pid)"
    rm -f "$PIDFILE"
  else
    log "nothing to stop"
  fi
  exit 0
fi

mkdir -p "$CACHE"

if curl -sf "http://localhost:$CLICKHOUSE_PORT/ping" >/dev/null 2>&1; then
  log "already up on :$CLICKHOUSE_PORT"
  exit 0
fi

if [ ! -x "$CACHE/clickhouse" ]; then
  log "downloading standalone clickhouse binary"
  ( cd "$CACHE" && curl -sSf https://clickhouse.com/ | sh )
fi

log "starting server on :$CLICKHOUSE_PORT"
# Run inside $CACHE so data/log dirs land there. Disable the watchdog so the
# server doesn't fork — then the recorded pid is the server itself and `stop`
# can kill it directly. setsid detaches it from this shell's session and the
# stdio redirects drop every inherited fd, so the server survives this script
# exiting and never holds open a pipe the caller is reading from.
(
  cd "$CACHE"
  CLICKHOUSE_WATCHDOG_ENABLE=0 exec setsid ./clickhouse server -- --http_port="$CLICKHOUSE_PORT" \
    </dev/null >clickhouse.log 2>&1
) &
echo $! > "$PIDFILE"
disown 2>/dev/null || true

for _ in $(seq 1 60); do
  if curl -sf "http://localhost:$CLICKHOUSE_PORT/ping" >/dev/null 2>&1; then
    log "up on :$CLICKHOUSE_PORT (pid $(cat "$PIDFILE"))"
    exit 0
  fi
  sleep 1
done
die "did not come up at http://localhost:$CLICKHOUSE_PORT/ping (see $CACHE/clickhouse.log)"
