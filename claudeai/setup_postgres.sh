#!/usr/bin/env bash
# Ensure a local Postgres server is available for the e2e suite.
#
# Reuses one already listening on $PGPORT. Otherwise it initializes a cluster in
# .cache/pgdata (trust auth, no password — local dev only) and starts a server
# in the background, left running (pid in .cache/postgres.pid) so other scripts
# can use it. Safe to run repeatedly.
#
# Postgres refuses to run as root, so when this script runs as root the server
# (and initdb) run as the system `postgres` user via runuser/su; the data dir is
# chowned accordingly. As a non-root user everything runs in-process.
#
# Usage:
#   claudeai/setup_postgres.sh          # ensure a server is running
#   claudeai/setup_postgres.sh stop     # stop the server this script started
#
# Env:
#   PGPORT   Postgres TCP port           (default 5432)
#   PGUSER   superuser role to create    (default postgres)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
. "$ROOT/claudeai/_guard.sh"
CACHE="$ROOT/.cache"
PGPORT="${PGPORT:-5432}"
PGUSER="${PGUSER:-postgres}"
PGDATA="$CACHE/pgdata"
PIDFILE="$CACHE/postgres.pid"
LOG="$CACHE/postgres.log"
PG_OS_USER="postgres"  # the system account to run as when this script is root

log() { printf '\033[34m[postgres]\033[0m %s\n' "$*"; }
die() { printf '\033[31m[postgres] error:\033[0m %s\n' "$*" >&2; exit 1; }

# Locate a Postgres program: prefer PATH, else the versioned package bindir.
find_bin() {
  if command -v "$1" >/dev/null 2>&1; then command -v "$1"; return 0; fi
  local b
  b=$(ls -d /usr/lib/postgresql/*/bin 2>/dev/null | sort -V | tail -1 || true)
  [ -n "$b" ] && [ -x "$b/$1" ] && { echo "$b/$1"; return 0; }
  return 1
}

INITDB=$(find_bin initdb) || die "initdb not found (install postgresql)"
PG_CTL=$(find_bin pg_ctl) || die "pg_ctl not found (install postgresql)"
PG_ISREADY=$(find_bin pg_isready) || die "pg_isready not found"

# Run a command as the unprivileged Postgres account when we are root.
as_pg() {
  if [ "$(id -u)" = "0" ]; then
    runuser -u "$PG_OS_USER" -- "$@"
  else
    "$@"
  fi
}

if [ "${1:-}" = "stop" ]; then
  if [ -d "$PGDATA" ] && as_pg "$PG_CTL" -D "$PGDATA" status >/dev/null 2>&1; then
    as_pg "$PG_CTL" -D "$PGDATA" -m fast stop >/dev/null 2>&1 || true
    log "stopped"
    rm -f "$PIDFILE"
  else
    log "nothing to stop"
  fi
  exit 0
fi

mkdir -p "$CACHE"

if "$PG_ISREADY" -h localhost -p "$PGPORT" -U "$PGUSER" >/dev/null 2>&1; then
  log "already up on :$PGPORT"
  exit 0
fi

# Initialize the cluster once (trust auth so the e2e connects with no password).
if [ ! -s "$PGDATA/PG_VERSION" ]; then
  log "initializing cluster in $PGDATA"
  rm -rf "$PGDATA"
  mkdir -p "$PGDATA"
  [ "$(id -u)" = "0" ] && chown "$PG_OS_USER":"$PG_OS_USER" "$PGDATA"
  as_pg "$INITDB" -D "$PGDATA" -U "$PGUSER" --auth=trust >/dev/null
fi

# The log must be writable by the run user.
: > "$LOG"
[ "$(id -u)" = "0" ] && chown "$PG_OS_USER":"$PG_OS_USER" "$LOG"

log "starting server on :$PGPORT"
# TCP on localhost; keep the unix socket inside PGDATA to avoid /var/run perms.
as_pg "$PG_CTL" -D "$PGDATA" -l "$LOG" -w \
  -o "-p $PGPORT -c listen_addresses=localhost -k $PGDATA" start \
  || die "server failed to start (see $LOG)"

for _ in $(seq 1 60); do
  if "$PG_ISREADY" -h localhost -p "$PGPORT" -U "$PGUSER" >/dev/null 2>&1; then
    # Record the postmaster pid for symmetry with setup_clickhouse.sh.
    [ -f "$PGDATA/postmaster.pid" ] && head -1 "$PGDATA/postmaster.pid" > "$PIDFILE"
    log "up on :$PGPORT (pid $(cat "$PIDFILE" 2>/dev/null || echo '?'))"
    exit 0
  fi
  sleep 1
done
die "did not come up on :$PGPORT (see $LOG)"
