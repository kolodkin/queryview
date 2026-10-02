#!/usr/bin/env bash
# Set up the full local e2e environment by running the setup scripts:
#   1. setup_clickhouse.sh — download + start a local ClickHouse (left running)
#   2. setup_postgres.sh   — initialize + start a local Postgres   (left running)
#   3. setup_browser.sh    — install the Playwright browser, build the SPA,
#                            serve it, run e2e
#
# Usage:
#   scripts/setup.sh
#
# All environment overrides documented in the scripts apply here too
# (CLICKHOUSE_PORT, PGPORT, E2E_WORKERS, ...).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

"$ROOT/scripts/setup_clickhouse.sh"
"$ROOT/scripts/setup_postgres.sh"
"$ROOT/scripts/setup_browser.sh"
