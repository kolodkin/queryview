#!/usr/bin/env bash
# Ensure a loopback git daemon serves a bare repo for the git-sync e2e — what
# CI's start-git-daemon action provides. The repo under .cache/gitsrv is
# recreated empty on every run (CI gets a fresh one per run), so run this
# before each e2e pass; the daemon itself is reused if already listening.
#
# Usage:
#   claudeai/setup_git_daemon.sh          # ensure the daemon is up, reset the repo
#   claudeai/setup_git_daemon.sh stop     # stop the daemon this script started
#
# Then run the suite with E2E_GIT_REMOTE=git://127.0.0.1:$GIT_DAEMON_PORT/queryview.git.
#
# Env:
#   GIT_DAEMON_PORT   TCP port (default 9418)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
. "$ROOT/claudeai/_guard.sh"
CACHE="$ROOT/.cache"
PORT="${GIT_DAEMON_PORT:-9418}"
GITSRV="$CACHE/gitsrv"
PIDFILE="$CACHE/git-daemon.pid"
LOG="$CACHE/git-daemon.log"

log() { printf '\033[33m[git-daemon]\033[0m %s\n' "$*"; }
die() { printf '\033[31m[git-daemon] error:\033[0m %s\n' "$*" >&2; exit 1; }

up() { (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null; }

if [ "${1:-}" = "stop" ]; then
  if [ -s "$PIDFILE" ] && kill "$(cat "$PIDFILE")" 2>/dev/null; then
    log "stopped"
  else
    log "nothing to stop"
  fi
  rm -f "$PIDFILE"
  exit 0
fi

command -v git >/dev/null 2>&1 || die "git not found"

rm -rf "$GITSRV/queryview.git"
mkdir -p "$GITSRV"
git init -q --bare -b main "$GITSRV/queryview.git"

if up; then
  log "already up on :$PORT (remote reset)"
  exit 0
fi

log "starting on :$PORT"
git daemon --reuseaddr --listen=127.0.0.1 --port="$PORT" \
  --base-path="$GITSRV" --export-all --enable=receive-pack \
  --detach --pid-file="$PIDFILE" >"$LOG" 2>&1

for _ in $(seq 1 30); do
  if up; then
    log "up on :$PORT (pid $(cat "$PIDFILE" 2>/dev/null || echo '?'))"
    exit 0
  fi
  sleep 1
done
die "did not come up on :$PORT (see $LOG)"
