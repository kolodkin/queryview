# One run for a dashboard page

## Intent

A dashboard page loads through several kinds of request, and the app and the
[viewer server](../../viewer_server/README.md) each have their own:

| | App | Viewer server |
|---|---|---|
| Params and the page's own queries | `/api/runqueries` | `/api/run` |
| A table widget's rows, sort, CSV | `/api/db/query` | `/api/query` |
| A table widget's columns | `/api/db/describe` | `/api/describe` |

Each widget request resolves on its own. On the viewer server it checks the
sent values against the params' options again, running the `options_sql` its
query uses; the app skips that check, so the two behave differently.

One run call replaces all of these for dashboards, with the same logic in both
servers. Two reasons, both wanted: fewer database queries on load and on a
param change, and simpler frontend code.

## Goals

- One endpoint, `POST /api/run`, serves every dashboard scenario in both
  servers: load, a param change, Execute, a widget's next page, a sort, CSV.
- Opening a dashboard is one run call: params resolved once, every query on
  the page run, the first page of each table widget included.
- A change re-runs and re-renders only what depends on it.
- The app and the viewer server share the run logic. They differ only in
  where the SQL comes from.
- Both check each value against its param's options. *(Decided: the app pays
  one option query when someone pages or sorts a widget whose query uses an
  `options_sql` param.)*

## Non-goals

- Explorer and Scripts keep `/api/db/query` and `/api/db/describe`.
- No cache or signed pass for resolved options. Either can be added later
  behind the same endpoint.
- No change to what a dashboard's HTML sees: `window.queries`,
  `window.params`, `setParams`, `<qv-select-view>` and `<qv-param>` keep their
  meaning.
- No change to param semantics (kinds, `default: none`, casts, quoting).

## Anti-goals

- The viewer server never accepts SQL, and never puts an unchecked value into
  SQL.
- One failing widget query does not blank the page.
- No scenario issues more database queries than today, except the app's
  paging case named under Goals.

## Approaches

1. **One run endpoint; the host keeps the results and answers the frame from
   them.** Picked: it is the only one that gives one call per load and one
   code path for both servers.
2. Keep per-widget requests and cache resolved options on the server. Fewer
   option queries, but still one request per widget and two code paths.
3. Per-node fetching in the browser (each param and query fetches itself).
   Natural in React, but one request per node, each re-checked on the viewer
   server: the cost this design removes, multiplied.

## Design

### The run call

Request, shared part:

```
{
  queries: [{name, limit?, offset?, order_by?, format?}],   // the queries to consider, each with its page
  values:  {<param>: <string>},
  changed: "all" | [<param>]                               // optional: what changed since the page's last run
}
```

`queries` is a list, so two widgets over one query with different pages both
fit; results come back as a list in the same order.

- The viewer server adds `connection` and `dashboard` (names). The SQL and
  params come from its repo copy.
- The app adds `sql: {<name>: <SQL>}` and `params: [...]`: the dashboard as
  open in the page, so an unsaved edit runs. It runs on the session's
  connection, behind the existing session gate.
- A query's page defaults to no sort, offset 0 and the dashboard row cap
  (1000). `format: "csv"` returns text instead of rows.

The server, identically in both:

1. Picks the queries to run. Without `changed`: every listed query. With
   `changed: [..]`: only the listed queries that use one of those params,
   directly or through a param whose `options_sql` references it.
2. Parses the params, and resolves those the picked queries use, directly or
   through another param's `options_sql` (the existing `needed` rule), plus
   the changed params and those that depend on them. `changed: "all"`
   resolves every param and runs every listed query. A value is kept only
   while its options offer it.
3. Runs each picked query that is ready, up to five at a time as today. One
   waiting on a choice is reported as waiting, not run.
4. Returns `{ok, results: [{name, ok, meta, data} | {name, ok, output} |
   {name, ok: false, message} | {name, ok: false, waiting: true}],
   params: [...]}`: a result per picked query, in the request's order, and
   the params it resolved.

Per-query status replaces fail-fast: a failing query fails alone. The request
as a whole fails when it is malformed, names an unknown query or connection,
the session gate refuses it, or a param cannot be resolved (a failing
`options_sql`, a cycle, an unknown cast): a `400` with `reason: params`, as
today. The malformed-param `warning` and
the "nothing needs the database, so no session is needed" rule carry over.

### What changed, and what depends on it

The server decides what a change affects: it holds the dependency rule
already, in both servers, so the browser never parses placeholders.

- **Load:** every query on the page, `changed: "all"`. The page draws every
  selector, including one no query uses.
- **A param change:** every query on the page with its current sort and page
  size, widgets at their first page, and `changed` naming the param. The
  server runs and returns only the affected ones. A param no query uses is
  still resolved, with those that depend on it.
- **Execute:** the edited queries, without `changed`.
- **A widget's page or sort:** that one query, without `changed`.

### The host

One core module holds the page's state and is the only code that calls the
run endpoint. Both pages (`DashboardView`, `ViewerApp`) use it and pass in
only their transport: what to add to the request.

- State: the resolved params, merged by name from each reply, and for each
  query the pages its most recent run returned, keyed by limit, offset and
  sort. A new run of a query replaces its pages, so paging back asks the
  database again, as today, and state does not grow with pages visited.
- Execute with nothing edited, and a connection or database switch, run
  everything again and so replace all of it.
- A widget still asks the host by message, as today. The host answers from
  its state when it holds that page, and otherwise makes a run call for that
  one query and keeps the answer. Two frames asking for the same page share
  one answer, which replaces `sharedPost`.
- On load the host reads each `<qv-select-view>` tag's `query`, `limit` and
  `order-by` from the dashboard's HTML (it already reads `query`) so the
  first run includes each widget's first page. A widget the HTML does not
  show, such as one a script creates, simply asks and is answered by a run
  call of its own.
- A widget's columns come from its result's `meta`; the describe request is
  answered from state.
- After a run, the host posts the page's own results and params to the frame
  as today, naming the queries that ran. Only widgets over those queries ask
  again, and their first pages are already in state. A param change resets
  those widgets to their first page, keeping their sort and page size.
- On load, a failing query of the page's own still shows the error banner
  with no frame, as today. A failing widget query shows in that widget.
- On a param change or Execute, a failing query of the page's own keeps its
  previous entry in `window.queries`, the others are updated, and
  `onQueryResults` gets the first failure's message, as today.
- A waiting query is left out of `window.queries` and raises no error.

### Removed

- App: `/api/runqueries`; the `params` and `values` handling in
  `/api/db/query` and `/api/db/describe`.
- Viewer server: `/api/query`, `/api/describe`.
- Frontend: the two widget transports, `sharedPost`, and the duplicated run
  and re-run code in the two pages.

### Docs

`api.md`, `viewer_server/api.md`, `dashboard.md` (the run section and
Widgets). This spec and its plan are deleted when the work ships.

### Tests

- Backend: the run logic tested once and exercised through both servers. For
  load, a param change and a widget page, a test counts the queries the
  database receives; these counts are the measurable goal.
- A value outside its options never reaches the SQL, in both servers.
- Frontend: unit tests for the host state (what to ask for on each change,
  answering from state, sharing one answer).
- The existing dashboard, widgets and viewer e2e specs pass with their
  assertions unchanged, apart from request names they intercept.

## Calls made while writing this up

These were not discussed; each is open to correction.

- The endpoint is named `/api/run` in both servers.
- Per-query status instead of fail-fast for the whole call.
- `changed: "all"` is how a load asks for every param.
- First pages are found by reading widget tags from the HTML; anything missed
  falls back to its own run call.
- A param change returns affected widgets to their first page.
- Results travel as rows (`meta`, `data`); the host builds the column-wise
  `window.queries` from them.
- `queries` and `results` are lists.
- A param that cannot be resolved fails the whole call, as today.
- Host state keeps only the latest run's pages per query.
- A failing own query on a re-run keeps its previous result in the frame.

## Left to the builder

- Module and function names, and how the shared run logic is split between
  `dashboard_queries.py` and the two route files.
- The exact shape of the host state.
- Whether the work lands as one change or in steps (backend endpoint first,
  then each page).
