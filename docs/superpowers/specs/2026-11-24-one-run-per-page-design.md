# One run for a dashboard page

## Intent

A dashboard page loads through several kinds of request, and the app and the
[viewer server](../../user_guide/viewer_server.md) each have their own:

| | App | Viewer server |
|---|---|---|
| Params and the page's own queries | `/api/runqueries` | `/api/run` |
| A table widget's rows, sort, CSV | `/api/db/query` | `/api/query` |
| A table widget's columns | `/api/db/describe` | `/api/describe` |

Each widget request resolves on its own. On the viewer server it checks the
sent values against the params' options again, running the `options_sql` its
query uses; the app skips that check, so the two behave differently.

One run call replaces all of these for dashboards, with the same logic in both
servers, and the page becomes a dependency tree: each param and each query is
a value that re-runs only when a value it uses changes. Two reasons, both
wanted: fewer database queries on load and on a param change, and simpler
frontend code.

## Goals

- One endpoint, `POST /api/run`, serves every dashboard scenario in both
  servers: load, a param change, Execute, a widget's next page, a sort, CSV.
- Opening a dashboard is one run call: params resolved once, every query on
  the page run, the first page of each table widget included.
- A change re-runs and re-renders only what depends on it.
- The app and the viewer server share the run logic and the frontend tree.
  They differ only in where the SQL comes from.
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
- No change to param semantics (kinds, `default: none`, casts, quoting). An
  `each` param keeps its meaning: a page query naming one runs once per
  option and stacks the rows, and a table widget over such a query is
  refused, as today. This design predates `each`; the plan's tasks 1 and 2
  must carry it through the shared run.

## Anti-goals

- The viewer server never accepts SQL, and never puts an unchecked value into
  SQL.
- The browser never parses SQL or placeholders: the dependencies come from
  the server.
- One failing widget query does not blank the page.
- No scenario issues more database queries than today, except the app's
  paging case named under Goals.

## Approaches

1. **A dependency tree in the page, fed by a map from the server, over one
   batched run call.** *(Decided.)* The page's React tree decides what
   re-runs; the requests of one render are collected into a single call. The
   protocol stays simple: the server runs what it is asked. Cost: a query
   that depends on the changed param only through another param's new value
   takes a second round trip, and the frontend holds the tree and the
   batching.
2. The server walks the dependencies: the page sends everything it shows plus
   what changed, and the server runs only the affected queries. One round
   trip for any chain and less frontend code, but the page is not a
   dependency tree and the protocol carries a notion of change.
3. Keep per-widget requests and cache resolved options on the server. Fewer
   option queries, but still one request per widget and two code paths.

## Design

### The run call

Request, shared part:

```
{
  queries: [{name, limit?, offset?, order_by?, format?}],   // which to run, each with its page
  resolve: "all" | [<param>],                               // optional: params to resolve besides those the queries use
  values:  {<param>: <string>}
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

The server, identically in both, runs what it is asked and nothing else:

1. Parses the params, and resolves those the requested queries use, directly
   or through another param's `options_sql` (the existing `needed` rule,
   applied to the whole request), plus those `resolve` names. A value is kept
   only while its options offer it.
2. Runs each requested query that is ready, up to five at a time as today.
   One waiting on a choice is reported as waiting, not run.
3. Returns

   ```
   {
     ok,
     results: [{name, ok, meta, data} | {name, ok, output}
               | {name, ok: false, message} | {name, ok: false, waiting: true}],
     params:  [{name, kind, options, value}],     // the ones it resolved
     uses:    {queries: {<name>: [<param>]}, params: {<param>: [<param>]}}
   }
   ```

`uses` is the dependency map for the queries and params this call handled:
the params each one references. It holds names only, so the viewer server
still sends no SQL. It comes with every reply rather than from a separate
call, so SQL edited in the app's query popup gets its new map when it runs.

Per-query status replaces fail-fast: a failing query fails alone. The request
as a whole fails when it is malformed, names an unknown query or connection,
the session gate refuses it, or a param cannot be resolved (a failing
`options_sql`, a cycle, an unknown cast): a `400` with `reason: params`, as
today. The malformed-param `warning` and the "nothing needs the database, so
no session is needed" rule carry over.

### The dependency tree in the page

One core module, used by both pages (`DashboardView`, `ViewerApp`), holds the
tree and is the only code that calls the run endpoint. A page passes in only
its transport: what to add to the request.

- **Nodes are the elements on the page.** *(Decided.)* The wiring from `uses`
  is applied to the DOM: a `<qv-select-view>` receives the values of the
  params its query uses as its inputs, next to its page (limit, offset,
  sort), and a `<qv-param>` holds its param's value. React inside the element
  re-runs it when an input changes. Authors write nothing extra: the page
  sets the inputs.
- **What has no element** is an entry in the page's run state instead: each
  of the page's own queries (read through `window.queries`) and each param
  whose options depend on another param. Its inputs are the values of the
  params it uses, and it is judged stale by the same rule an element applies.
- **A node asks when its inputs change.** Each result records the values it
  was run with, as the server resolved them. A node asks again only when its
  current inputs differ from those, so a value the server already corrected
  does not cause a second run.
- **Batching.** The asks that follow one change are collected and sent as one
  run call: param nodes become `resolve`, queries become `queries`. Asks from
  elements in the frame arrive as messages, so the batch waits for them
  before it is sent.
- **Load.** Nothing is known yet, so the first call asks for everything:
  `resolve: "all"` and every query view on the page. The server resolves the
  whole chain in that one call, and its `uses` map gives every node its
  inputs from then on.
- **A param change.** The nodes that list that param ask again, in one call.
  If the reply changes another param's value (a `city` no longer offered
  under the new `region`), the nodes that use only that param ask in a second
  call. *(Decided: this extra round trip is accepted.)*
- **Execute** marks the edited queries as changed; **paging or sorting**
  changes one view's page input. Both are ordinary asks.

### Widgets and the frame

- The frame is given `uses` and the param values when it is built, and again
  with each reply. Each widget element takes from them the values of the
  params its query uses; those are its inputs.
- A widget asks the page by message when an input or its page changes. The
  ask carries the query's name and page only, as today: the page holds the
  values, so a frame cannot send one of its own.
- On load the page reads each `<qv-select-view>` tag's `query`, `limit` and
  `order-by` from the dashboard's HTML (it already reads `query`), so the
  first call includes each widget's first page. When the widget mounts and
  asks, the page answers from that result.
- A widget the HTML does not show, such as one a script creates, asks the
  same way and is answered through the batch. Two frames asking for the same
  page of the same query share one result, which replaces `sharedPost`.
- A widget's columns come from its result's `meta`; the describe request is
  answered from the result.
- The page holds only the latest result per widget page asked for, so paging
  back asks the database again, as today, and nothing grows with pages
  visited.
- After a call, the page posts its own queries' results and the params to the
  frame as today. A widget whose inputs did not change does not ask again. A
  param change returns the widgets it reaches to their first page, keeping
  their sort and page size.
- Execute with nothing edited, and a connection or database switch, run
  everything again.

### Errors

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
- Frontend: unit tests for the tree's pure logic: which nodes ask after a
  change, that a server-corrected value causes no second run, that one render
  makes one call, and that a dependent param costs exactly one more.
- The existing dashboard, widgets and viewer e2e specs pass with their
  assertions unchanged, apart from request names they intercept.

## Calls made while writing this up

These were not discussed; each is open to correction.

- The endpoint is named `/api/run` in both servers.
- Per-query status instead of fail-fast for the whole call.
- The dependency map travels in every run reply, not in a separate call.
- The page's own queries, and params whose options depend on another param,
  have no element: they are entries in the page's run state, not components.
- A widget's inputs also include its query's revision, which the page raises
  when Execute re-runs that query: the SQL changed, the params did not.
- A widget names itself in its asks (`view`), so the page keeps one latest
  page per widget.
- A widget's ask carries no values; the page supplies them.
- A result records the values it was run with, and a node asks only when its
  inputs differ from them.
- First pages are found by reading widget tags from the HTML; anything missed
  asks through the batch.
- A param change returns affected widgets to their first page.
- Results travel as rows (`meta`, `data`); the page builds the column-wise
  `window.queries` from them.
- `queries` and `results` are lists.
- A param that cannot be resolved fails the whole call, as today.
- A view keeps only the latest page it ran.
- A failing own query on a re-run keeps its previous result in the frame.

## Left to the builder

- Module and function names, and how the shared run logic is split between
  `dashboard_queries.py` and the two route files.
- How the nodes share state (context, a store, or props) and how the batch
  is flushed.
- Whether the work lands as one change or in steps (backend endpoint first,
  then each page).
