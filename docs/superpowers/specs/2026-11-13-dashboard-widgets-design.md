# Dashboard widgets replace Studio — design

## Intent

One place to look at data. The `/studio` page and the saved-query store go
away; a query-and-results panel becomes a widget an agent drops into a
dashboard's HTML. The agent keeps a free hand over layout: HTML stays the only
layout language, and there is no widget grid or block spec.

## Goals

- `<qv-select-view>` and `<qv-param>` tags usable anywhere in dashboard HTML.
- Per-column cell design declared as `<template>` children of the table tag.
- SQL edited in an app-side panel on `/dashboard`, never inside the frame.
- Every saved query becomes a dashboard; nothing a user saved is lost.
- Ad-hoc querying survives as an unsaved scratch dashboard.

## Non-goals

- More tags (chip and others): added when a dashboard needs one.
- A UI editor for dashboard HTML or cell templates.
- Persisting in-widget order-by / field changes from the UI.
- Migrating the app off React.

## Anti-goals

- A Datadog-style widget language or grid the agent must target.
- SQL text crossing from the frame to the app.
- Agent-authored code running in the app's origin.

## Constraints

- The frame stays `sandbox="allow-scripts"` with an opaque origin: no session,
  no `/api/*`, no downloads of its own.
- The frame sends **values only**: a query name the dashboard declares, plus
  limit, offset, order-by columns and param values. The host substitutes and
  runs the dashboard's own SQL and answers only its own frame.
- `src/core` never fetches (lint-enforced): widgets live in `core`, the host
  side of the channel in `app`.
- Existing plain-HTML dashboards render unchanged.

## Approaches

| | What | Trade-off |
| --- | --- | --- |
| A | Dashboard is a stacked list of blocks; widgets render in the app, HTML is one block | Least code, real API; agent can't place a widget inside its own layout |
| **B (picked)** | Widgets are custom tags inside the sandboxed frame, talking to the app by message | Free layout; React + table ship into the frame, SQL editing must live outside it |
| C | HTML marks slots, the app overlays widgets on top of the frame | Free layout and real API; position tracking through scroll/resize is fragile |

B was picked because the agent must have a free hand, not a widget language.
The bundle cost (a few hundred KB, cached) is accepted.

## Design

### Tags

```html
<qv-param name="region"></qv-param>
<qv-select-view query="sales" limit="100" order-by="day desc" fields="day,revenue">
  <template column="revenue"><strong>{cell}</strong></template>
  <template column="name"><a href="https://example.internal/items/{row.id}">{cell}</a></template>
</qv-select-view>
```

- **`<qv-select-view query>`** — the Studio results area: table, **Fields**,
  select-fields and order-by pickers, **Limit** / **Offset**, **Previous** /
  **Next**, **Download CSV**, the array/map/tuple default views and the
  long-value popup. `query` names an entry in the dashboard's `queries`.
  `limit`, `order-by` and `fields` attributes are the saved presentation;
  changes made in the widget last for the visit.
- **`<template column>`** — the only way to design a cell. Its HTML is used
  per row with `{cell}` and `{row.<column>}` substituted and HTML-escaped (the
  existing `substituteCellTemplate`), URL-encoded inside `href`/`src`. A
  template wins over the default view for its column.
- **`<qv-param name>`** — a selector for one dashboard param (a checkbox for
  `dimension`), drawn from `window.params`; a change calls `setParams`.

The tags are React components from `src/core`, registered as custom elements
by a second build entry. The frame prologue loads that bundle only when the
HTML contains `<qv-`.

### Channel

Extends today's `set-params` / `params-results` messages:

| Frame → host | Host does |
| --- | --- |
| `widget-query {id, query, limit, offset, order_by}` | substitutes current params into `queries[query]`, runs `/api/db/query`, replies `{id, meta, data}` or `{id, message}` |
| `widget-describe {id, query}` | `/api/db/describe`, replies `{id, fields}` |
| `widget-csv {query, limit, offset, order_by}` | runs the CSV format and downloads `query.csv` from the app |

A widget re-queries when params change, and shows its own query's error in
place. A query named by a `<qv-select-view>` in the HTML is the widget's alone:
it is left out of the up-front `/api/runqueries` run and of `window.queries`,
so it runs once and a typo in it never blanks the dashboard. **Execute** in the
SQL panel posts into the live frame instead of rebuilding it, so widgets and
page state survive.

### The `/dashboard` page

```
+-- /dashboard ------------------------------------------+
| [ dashboard v ] [New query] [Save] ...  [Edit queries] |
| +- SQL panel (Edit queries) -------------------------+ |
| | query [ sales v ]          [Min][S][M][L][XL]      | |
| | SELECT ...                              [Execute]  | |
| +----------------------------------------------------+ |
| +- sandboxed frame (agent HTML) ---------------------+ |
| | <qv-param>  chart  <qv-select-view query=sales>    | |
| +----------------------------------------------------+ |
+--------------------------------------------------------+
```

- **Edit queries** opens the SQL panel: pick one of the dashboard's queries,
  edit its SQL, **Execute** re-runs the dashboard with the draft. **Save**
  persists the dashboard as today. The human edit lock moves to this panel.
- **New query** opens an unsaved draft: HTML `<qv-select-view query="main">`,
  one empty query `main`, SQL panel open. **Save** asks for a name, like a
  pushed draft. `/studio` redirects here; Scripts' load-into-Studio opens it
  with that SQL.
- Dashboards gain **Rename**, **Delete** (soft), **Undelete** and **Purge**,
  taking over the saved-query behaviour and its git-sync markers.

### Migration of saved queries

Each `predefined_queries` row becomes a dashboard:

- name = `query_name`; on a clash with a dashboard or another driver's query,
  the driver is appended: `sales (postgres)`;
- `queries: {main: <sql>}`; `params` = the `params:` block of its cell view
  YAML, unchanged (kind `value`);
- HTML = a `<qv-param>` per param, then `<qv-select-view query="main">` with
  `order-by` / `fields` from the saved presentation and a `<template>` per
  `link` / `custom` cell rule;
- `deleted_at` carries over.

The migration is a one-shot move, shipped together with Studio's removal.

YAML import keeps accepting `kind: query` entries, converting them the same
way. Git sync converts a legacy `queries/{type}/…` file once: the converted
path is remembered with the "last agreed" ids, so a later rename, edit or
purge of the dashboard does not re-import it, and the dashboard's first
**Commit** removes the legacy file in the same commit. Only dashboards are
written. History of a migrated dashboard starts at that commit.

### Removed

`StudioView`, the **Cell view** modal, cell-view YAML parsing and validation,
the predefined-queries store and API, the `studio` push event, MCP
`push_studio` and `list_queries`. `push_dashboard` is the one push tool; the
agent skill text documents the tags. `query.md` folds into `dashboard.md`.

## Build order

Each step ships on its own:

1. Tags, channel and SQL panel; Studio untouched.
2. Dashboard rename/delete (new `deleted_at` column and endpoints), the
   migration, git-sync and import conversion, and in the same release the
   removal of Studio, the query store and `push_studio`; docs and skill.

## Left to the builder

- How the widget bundle is served and styled inside the frame (shadow DOM or
  scoped CSS) without clashing with agent CSS.
- The on-disk marker for a deleted dashboard in git sync.
- Behaviour differences between query params and dashboard params (for
  example `options_sql` caching, re-run on database switch): list and close.
- Test layers, per the project `testing` skill.
