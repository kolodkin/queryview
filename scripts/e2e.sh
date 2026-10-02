#!/usr/bin/env bash
# Run the Playwright e2e suite. The suite starts its own backends (one per
# pytest worker, each on a free port and a throwaway DATA_DIR that pytest
# cleans up), so it never touches a real ~/.queryview.
#
# Assumes deps, the Playwright browser and the databases are set up
# (scripts/setup_browser.sh does that, then calls this).
#
# Usage:
#   scripts/e2e.sh [pytest args...]      e.g. scripts/e2e.sh -k workspaces
#   npm run e2e -- [pytest args...]
#
# Environment overrides:
#   E2E_WORKERS    pytest-xdist worker count   (default: auto, one per CPU)
#   SKIP_BUILD=1   reuse the existing frontend build
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

log() { printf '\033[36m[e2e]\033[0m %s\n' "$*"; }

if [ "${SKIP_BUILD:-}" != "1" ]; then
  log "building SPA"
  npm run build -w frontend
fi

log "running Playwright e2e tests"
uv run --frozen --group test pytest e2e \
  -n "${E2E_WORKERS:-auto}" \
  --tracing retain-on-failure \
  --html=report/index.html --self-contained-html \
  "$@"

log "done. HTML report at report/index.html"
