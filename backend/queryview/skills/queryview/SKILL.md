---
name: queryview
description: Drive a live QueryView browser tab over MCP — open a tab, pick a connection, run SQL with run_script (writes applied once), and push the final script, or a Studio query or dashboard when asked, for the user to see.
---

# QueryView

## Tabs

Work in a tab of your own unless the user gives you a session id. `new_tab(name)` returns
a `session_id` and a `url`; open the url in the user's browser yourself (`open <url>` on
macOS, `xdg-open <url>` on Linux; otherwise give the user the link). One tab per task,
reused when revising it.

## Connections

`use_connection` any ClickHouse/Postgres connection `list_connections` shows, or
`add_connection` your own. A locked connection (see `session_info`) refuses every push and
query with "connection is locked"; use another one.

## Running SQL

`run_script` is the default for any SQL, reads and writes alike, and returns each
statement's result to you (`run_sql` is the read-only alternative).

1. Explore and apply writes with `run_script` — apply each write once.
2. `push_script` the final SQL with `run=False` — never re-run writes.

If a push fails, reply with the SQL.

Use `push_query` (the Studio) or `push_dashboard` only when the user asks for them.

## Dashboards

`push_dashboard` renders HTML fed by named queries as an unsaved draft; re-push to revise
it. See the tool's description for the `window.queries` and `params` contract.

A tool the user names wins over this workflow.
