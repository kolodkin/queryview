#!/usr/bin/env bash
# Ensure a local MySQL-compatible server (MariaDB) is available for the e2e suite.
#
# Reuses one already answering on $MYSQL_PORT. Otherwise installs mariadb-server
# via apt when missing, initializes a data dir in .cache/mysqldata and starts
# the server in the background as the `mysql` user. root logs in over TCP with
# no password (local dev only), what CI's mysql service provides.
#
# Usage:
#   claudeai/setup_mysql.sh          # ensure a server is running
#   claudeai/setup_mysql.sh stop     # stop the server this script started
#
# Env: MYSQL_PORT (default 3306)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
. "$ROOT/claudeai/_guard.sh"
CACHE="$ROOT/.cache"
PORT="${MYSQL_PORT:-3306}"
DATA="$CACHE/mysqldata"
SOCK="$DATA/mysqld.sock"
PIDFILE="$DATA/mysqld.pid"
LOG="$CACHE/mysql.log"

log() { printf '\033[35m[mysql]\033[0m %s\n' "$*"; }
die() { printf '\033[31m[mysql] error:\033[0m %s\n' "$*" >&2; exit 1; }

if [ "${1:-}" = "stop" ]; then
  if [ -f "$PIDFILE" ] && kill "$(cat "$PIDFILE")" 2>/dev/null; then
    log "stopped"
  else
    log "nothing to stop"
  fi
  rm -f "$PIDFILE"
  exit 0
fi

up() { mysqladmin -h 127.0.0.1 -P "$PORT" -u root ping >/dev/null 2>&1; }

if command -v mysqladmin >/dev/null 2>&1 && up; then
  log "already up on :$PORT"
  exit 0
fi

if ! command -v mariadbd >/dev/null 2>&1; then
  [ "$(id -u)" = "0" ] || die "mariadbd not found (install mariadb-server)"
  log "installing mariadb-server"
  (apt-get install -y -q mariadb-server || { apt-get update -q && apt-get install -y -q mariadb-server; }) >/dev/null \
    || die "apt-get install mariadb-server failed"
fi

mkdir -p "$CACHE"
if [ ! -d "$DATA/mysql" ]; then
  log "initializing data dir in $DATA"
  rm -rf "$DATA"
  mkdir -p "$DATA"
  chown mysql:mysql "$DATA"
  mariadb-install-db --user=mysql --datadir="$DATA" --auth-root-authentication-method=normal >/dev/null \
    || die "mariadb-install-db failed"
fi

: > "$LOG"
chown mysql:mysql "$LOG"
log "starting server on :$PORT"
mariadbd --user=mysql --datadir="$DATA" --port="$PORT" --bind-address=127.0.0.1 \
  --socket="$SOCK" --pid-file="$PIDFILE" --log-error="$LOG" >/dev/null 2>&1 &

for _ in $(seq 1 60); do
  if up; then
    log "up on :$PORT (pid $(cat "$PIDFILE" 2>/dev/null || echo '?'))"
    exit 0
  fi
  sleep 1
done
die "did not come up on :$PORT (see $LOG)"
