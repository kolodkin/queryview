# `run_dashboard` MCP tool

## Intent

An agent writing a dashboard with `{placeholders}` cannot test its queries
through `run_sql` without substituting by hand. Give it a tool that runs a
draft's queries for given values and returns the rows, so it checks them
before `push_dashboard`.

## Approaches

1. **An MCP tool over `dashboard_queries.run_dashboard`**, the function the
   page's own run uses: same resolution, substitution and `each` fan-out.
   **Picked.**
2. `params` and `values` arguments on `run_sql`: one statement at a time, and
   a second caller of the substitution with its own rules for a waiting query.
3. A new HTTP route the agent calls: the agent has no HTTP client for the
   app, only MCP.

## Design

- `run_dashboard(session_id, queries?, params?, values?, dir?, limit?=100)`
  in `mcp_server.py`. `queries` and `params` inline or from `dir`, read as
  `push_dashboard` reads them (`_read_dashboard_dir`; inline `params` win;
  both sources given is refused; `dashboard_params_error` checked first).
- `values` is a `{param: value}` map, cleaned with `clean_values`. A param
  left out takes its default, as on the page.
- Reply: `{"ok": True, "database", "results", "meta", "params"}`, `results`
  in the `window.queries` shape, `params` as `[{name, kind, options, value}]`.
  A query waiting on a choice is left out of `results`, as on the page.
  Failure: `{"ok": False, "message"}`, plus `params` when they resolved.
- `limit` caps the rows of each query, 0..`DASHBOARD_ROW_CAP`; it is threaded
  through `run_dashboard` and `run_dashboard_on` to `run_queries_on`, default
  unchanged for the page.
- Gate: `_gated_session`, as today, so a locked connection, a disconnected
  session and a missing database are refused. Read-only: each query runs in
  the drivers' wrapping `SELECT … LIMIT`. The default **Query timeout** (30 s)
  bounds each query.
- Docs: `mcp.md` tool list, `dashboard.md` parameters section, the queryview
  skill's workflow; the entry leaves `future.md`.
- Tests: `test_mcp_dashboards.py` next to the other MCP tests: substituted
  values reach the SQL, a default applies, `limit` cuts rows, `dir` is read,
  a bad param and a locked connection are refused.

## Non-goals

No run of a saved dashboard by `name`, no per-query error list (the run stays
fail-fast, its message naming the query), no HTML rendering.
