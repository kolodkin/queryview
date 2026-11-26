# Dashboard internals

How a dashboard's queries run and how its HTML is isolated. Building and using a dashboard is in [dashboard.md](../system/dashboard.md).

## Running the queries: `/api/runqueries`

<!-- req: runqueries -->
The browser POSTs `{queries, params, values}` to `/api/runqueries`: the
dashboard's queries as written, its `params` declaration and the chosen
values. The backend resolves each selector's options and value, substitutes
them into the queries, and runs each one on the session's connection and
selected database (wrapped in a paginated subselect capped at 1000 rows). It
returns column-oriented results and the resolved selectors. Up to five queries
run at once. Switching the connection or database re-runs them.

<!-- req: fail-fast -->
It is **fail-fast**: if any query fails, or the session is not connected or has
no database selected, the whole request returns an HTTP error and the page shows a
dashboard-level error banner instead of partial panels. On success every named
query is present in `window.queries`. A failing query's message is prefixed with
its panel name (e.g. `churn: Unknown table …`) so it's clear which one to fix. When
several fail, the first in the dashboard's order is the one reported.

## Isolation & security

The HTML renders in
`<iframe sandbox="allow-scripts allow-popups allow-popups-to-escape-sandbox" srcdoc=…>`
**without** `allow-same-origin`, giving it an opaque origin: it can run JS and load CDN
assets but cannot read the app's storage or call `/api/*` as the session (it
has neither the session id nor any credential). A link the page opens with
`target="_blank"` lands in a normal tab. The page cannot print or download;
[Snapshot](../system/dashboard.md#snapshot) is the way out; its file runs no script because the
host puts a script-blocking policy ahead of the frame's text. Data reaches the page only through the
injected `window.queries` and the [widget](../system/dashboard.md#widgets) replies; the
`window.queries` JSON has `<` escaped so result data containing `</script>` can't break out
of the prologue.

Persisted dashboards are shared via SQLite and keyed by name within their
[workspace](../system/workspace.md). The agent HTML
is untrusted and confined to the sandbox; it never sees connection secrets or
the session id.

## Related docs

- [dashboard.md](../system/dashboard.md) — dashboards and how agents author them.
- [api.md](./api.md) — `/api/runqueries` and `/api/dashboards`.
- [workspace.md](../system/workspace.md) — workspaces.
