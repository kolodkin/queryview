# Viewer server API

The [viewer server](../system/viewer_server.md) (`queryview-server`) is a separate app with
its own, smaller API. No session header; none of the app's
[routes](api.md) exist on it.
A body names a `connection` and a `dashboard`, never SQL. Errors are
`{ok:false, message}`: `404` for an unknown connection, dashboard or query
name, `400` for a bad body, a bad value or a failing query.

| Method | Path                     | Body                                             | Description |
| ------ | ------------------------ | ------------------------------------------------ | ----------- |
| GET    | `/api/health`            | —                                                | `{status, service}`. |
| GET    | `/api/connections`       | —                                                | `[{name, type}]`, in config order; never a config. |
| GET    | `/api/dashboards`        | —                                                | `[{name}]`, the dashboards at the repo's head. |
| GET    | `/api/dashboards/{name}` | —                                                | `{name, html, queries:[name]}`: query names only, no SQL. |
| POST   | `/api/run`               | `{connection, dashboard, queries?:[name], values?}` | Resolve the selectors from `values` and run the named queries (all when omitted), as the app's `/api/runqueries` does with `params`: `{ok, results, params}`. |
| POST   | `/api/query`             | `{connection, dashboard, query, values?, limit?, offset?, order_by?, format?}` | One page of a dashboard query, as the app's `/api/db/query`: `{ok, meta, data}`, or `{ok, output}` for `format:"csv"`. A query waiting on a choice → `400`. |
| POST   | `/api/describe`          | `{connection, dashboard, query, values?}`        | The query's output columns: `{ok, fields}`. |

Every POST resolves the selectors first, so a value outside a param's options
falls back to its default and never reaches the SQL.

## Related docs

- [README.md](../system/viewer_server.md) — the viewer server.
- [../api.md](api.md) — the app's API.
- [../dashboard.md](../system/dashboard.md#dashboard-parameters) — parameters and how they are substituted.
