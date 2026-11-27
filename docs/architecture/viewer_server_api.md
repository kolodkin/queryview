# Viewer server API

<!-- req: names-not-sql -->
The [viewer server](../system/viewer_server.md) (`queryview-server`) is a separate app with
its own, smaller API. No session header; none of the app's
[routes](api.md) exist on it.
A body names a `dashboard` and, for an unfederated one, a `connection`,
never SQL. Errors are `{ok:false, message}`: `404` for an unknown dashboard,
query name or (unfederated) connection, `400` for a bad body, a bad value or a failing query.

| Method | Path                     | Body                                             | Description |
| ------ | ------------------------ | ------------------------------------------------ | ----------- |
| GET    | `/api/health`            | —                                                | `{status, service}`. |
| GET    | `/api/connections`       | —                                                | `[{name, type}]`, in config order; never a config. |
| GET    | `/api/dashboards`        | —                                                | `[{name}]`, the dashboards at the repo's head. |
| GET    | `/api/dashboards/{name}` | —                                                | `{name, html, queries:[name], connections?:[name]}`: names only, no SQL. |
| POST   | `/api/run`               | `{connection?, dashboard, queries?:[name], values?}` | Run the dashboard's own queries, picked by name (all when omitted), with its selectors resolved from `values`: `{ok, results, params}`, plus `connections`, each connection's status, when federated. The SQL and connections come from the repo copy, never the body; `connection` is the viewer's pick and is used only for an unfederated dashboard. |
| POST   | `/api/query`             | `{connection?, dashboard, query, values?, limit?, offset?, order_by?, format?}` | One page of a dashboard query, as the app's `/api/db/query`: `{ok, meta, data}`, or `{ok, output}` for `format:"csv"`. A query waiting on a choice → `400`. |
| POST   | `/api/describe`          | `{connection?, dashboard, query, values?}`        | The query's output columns: `{ok, fields}`. |

<!-- req: named-connection -->
A query entry that names a `connection` (a federated dashboard) runs on that
connection of the server's config, on the entry's `database` else the
connection's own. The body needs no `connection`; one sent is ignored.
`/api/run` also returns `connections: [{name, database, status, queries,
message?}]`, `status` being `ok`, `failed` or `unknown`. A name the config
lacks fails its query as `orders: unknown connection "nope"` (`400`).
`connections` on `GET /api/dashboards/{name}` lists the names its queries, then its `options_sql` params, use, each once. A dashboard
mixing named and unnamed queries is not served.

<!-- req: values-checked -->
Every POST resolves the selectors first, so a value outside a param's options
falls back to its default and never reaches the SQL.

## Related docs

- [viewer_server.md](../system/viewer_server.md) — the viewer server.
- [api.md](api.md) — the app's API.
- [dashboard.md](../system/dashboard.md#dashboard-parameters) — parameters and how they are substituted.
