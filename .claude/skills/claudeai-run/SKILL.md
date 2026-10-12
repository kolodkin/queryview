---
name: claudeai-run
description: Start the local backing services (ClickHouse, PostgreSQL) needed for the e2e suite by running claudeai/run.sh. Use at the start of a new session, or whenever the services are down (e.g. after a container suspend/resume) and tests need them up.
disable-model-invocation: true
---

# claudeai-run Skill

Brings up the local e2e backing services. Binaries and on-disk state are installed
once by `claudeai/setup.sh` and survive a container resume, but the processes
don't — so each session must restart them. That's what `claudeai/run.sh` does.

## Preflight: web environment only

These services are meant only for the Claude Code web (cloud) environment. Before
running anything, verify you're there — abort the skill if not:

```bash
[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || { echo "Not the Claude Code web environment — skipping claudeai-run."; exit 1; }
```

`CLAUDE_CODE_REMOTE=true` is set only in the remote/web container (`CLAUDECODE=1`
is set for any Claude Code session, local included, so don't gate on that). The
`claudeai/*.sh` scripts enforce the same guard via `claudeai/_guard.sh`; a
deliberate local run can override with `CLAUDEAI_ALLOW_LOCAL=1`.

## Start

```bash
claudeai/run.sh
```

Idempotently starts (reusing anything already up):

1. **ClickHouse** — `:8123` (standalone binary in `.cache/clickhouse`, user `default`, no password)
2. **PostgreSQL** — `:5432` (cluster in `.cache/pgdata`, trust auth, superuser `postgres`)

Prints `[run] all services up` on success. A failure exits non-zero with a
`[<svc>] error:` line pointing at its log under `.cache/`.

Then run the suite with `npm run e2e` (or `scripts/e2e.sh -k <expr>`).

## Stop

```bash
claudeai/run.sh stop   # reverse dependency order
```

## If a service won't start

`run.sh` only starts what `setup.sh` installed. A "binary/cluster missing … run
claudeai/setup_<svc>.sh first" error means the install is gone (fresh container):

```bash
claudeai/setup.sh   # then re-run claudeai/run.sh
```

Per-service logs: `.cache/clickhouse.log`, `.cache/postgres.log`.
