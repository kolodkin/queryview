#!/usr/bin/env bash
# Ensure a local MySQL 8.4 server is available for the e2e suite.
#
# Reuses one already answering on $MYSQL_PORT. Otherwise downloads Oracle's
# generic Linux tarball (the version CI's mysql:8.4 service runs) into
# .cache/mysql, initializes a data dir in .cache/mysqldata and starts the server
# in the background as the `mysql` user. root logs in over TCP with no password
# (local dev only), what CI's mysql service provides.
#
# Usage:
#   claudeai/setup_mysql.sh          # ensure a server is running
#   claudeai/setup_mysql.sh stop     # stop the server this script started
#
# Env: MYSQL_PORT (default 3306), MYSQL_VERSION (default 8.4.7)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
. "$ROOT/claudeai/_guard.sh"
CACHE="$ROOT/.cache"
PORT="${MYSQL_PORT:-3306}"
VERSION="${MYSQL_VERSION:-8.4.7}"
MY="$CACHE/mysql"
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
  exit 0
fi

up() { [ -x "$MY/bin/mysqladmin" ] && "$MY/bin/mysqladmin" -h 127.0.0.1 -P "$PORT" -u root ping >/dev/null 2>&1; }

if up; then
  log "already up on :$PORT"
  exit 0
fi

# The tarball links libaio.so.1, symlinked into its lib/ below when the system names it differently.
export LD_LIBRARY_PATH="$MY/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
mkdir -p "$CACHE"
if [ ! -x "$MY/bin/mysqld" ] || ! "$MY/bin/mysqld" --version 2>/dev/null | grep -q " $VERSION "; then
  name="mysql-$VERSION-linux-glibc2.28-x86_64-minimal"
  log "downloading $name"
  curl -fsSL --retry 3 -o "$CACHE/$name.tar.xz" "https://dev.mysql.com/get/Downloads/MySQL-${VERSION%.*}/$name.tar.xz" \
    || die "download failed"
  rm -rf "$MY" "$CACHE/$name"
  tar -xf "$CACHE/$name.tar.xz" -C "$CACHE"
  mv "$CACHE/$name" "$MY"
  rm -f "$CACHE/$name.tar.xz"
fi

# Ubuntu 24.04 ships libaio.so.1 as libaio.so.1t64.
if ! ldconfig -p | grep -q 'libaio\.so\.1 '; then
  aio=$(ldconfig -p | awk '/libaio\.so\.1t64 /{print $NF; exit}')
  if [ -z "$aio" ]; then
    command -v apt-get >/dev/null 2>&1 || die "libaio missing (install libaio1)"
    apt-get install -y -q libaio1t64 >/dev/null 2>&1 || apt-get install -y -q libaio1 >/dev/null || die "libaio install failed"
    aio=$(ldconfig -p | awk '/libaio\.so\.1(t64)? /{print $NF; exit}')
  fi
  ln -sf "$aio" "$MY/lib/libaio.so.1"
fi

# mysqld refuses to run as root.
id mysql >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin mysql

if [ ! -d "$DATA/mysql" ]; then
  log "initializing data dir in $DATA"
  rm -rf "$DATA"
  # root@localhost with an empty password
  "$MY/bin/mysqld" --no-defaults --initialize-insecure --user=mysql --basedir="$MY" --datadir="$DATA" 2>"$LOG" \
    || die "mysqld --initialize failed (see $LOG)"
fi

: > "$LOG"
chown mysql:mysql "$LOG"
log "starting server on :$PORT"
"$MY/bin/mysqld" --no-defaults --user=mysql --basedir="$MY" --datadir="$DATA" --port="$PORT" \
  --bind-address=127.0.0.1 --mysqlx=OFF --secure-file-priv=NULL \
  --socket="$SOCK" --pid-file="$PIDFILE" --log-error="$LOG" >/dev/null 2>&1 &

for _ in $(seq 1 60); do
  if up; then
    log "up on :$PORT (pid $(cat "$PIDFILE" 2>/dev/null || echo '?'))"
    exit 0
  fi
  sleep 1
done
die "did not come up on :$PORT (see $LOG)"
