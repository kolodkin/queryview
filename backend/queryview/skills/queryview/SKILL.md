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

Use `push_studio` or `push_dashboard` only when the user asks for them.

## Studio results

When the user asks for a Studio query, push a designed result, not a raw dump:

- `fields`: only the columns that answer the question, in reading order.
- `order_by`: the order the user cares about (e.g. `[{"name": "revenue", "dir": "DESC"}]`).
- `limit`: a page that fits the question; aggregate in SQL instead of pushing raw rows.
- `cell_view`: YAML, one entry per column, `type: link` or `type: custom` with a `value`
  template; `{cell}` is the value, `{row.<column>}` another column of the same row.
  Substituted values are HTML-escaped; the template HTML (inline `style` included) is
  rendered as written.

Use `custom` for chips on categorical columns (status, severity, environment, type):

```yaml
status:
  type: custom
  value: <span style="padding:1px 8px;border-radius:999px;font-size:12px;border:1px solid rgba(255,255,255,.12);background:rgba(255,255,255,.06);color:#e2e8f0">{cell}</span>
```

Other good uses: right-aligned numbers with `font-variant-numeric:tabular-nums`, small
inline bars (`width:{row.pct}%`), a `link` to the record in its own system.

## Dashboards

`push_dashboard` renders HTML fed by named queries as an unsaved draft; re-push to revise
it. See the tool's description for the `window.queries` and `params` contract.

Two tags save hand-drawing a table or a selector; place them anywhere in the HTML:

```html
<qv-param name="region"></qv-param>
<qv-select-view query="sales" limit="100" order-by="day desc">
  <template column="revenue"><strong>{cell}</strong></template>
</qv-select-view>
```

`<qv-select-view>` pages the named query (it is then not in `window.queries`);
a `<template column>` designs a column with `{cell}` and `{row.<column>}`.

Never name a new query or dashboard: push it unnamed and the user names it on Save.
`name` only takes one that is already saved, to edit it.
You cannot save: when asked to, push it and tell the user to click **Save**.

Match QueryView's look — dark liquid glass. The dashboard runs in an iframe, so it paints
its own backdrop (the app's doesn't show through):

```css
body {
  color-scheme: dark; color: #e2e8f0; min-height: 100vh;
  background:
    radial-gradient(820px 620px at 12% 6%, rgba(99,102,241,.3), transparent 62%),
    radial-gradient(760px 580px at 88% 14%, rgba(168,85,247,.24), transparent 60%),
    radial-gradient(900px 720px at 78% 104%, rgba(45,212,191,.16), transparent 60%),
    linear-gradient(160deg, #070a14, #0c1124 52%, #160f2b);
}
.panel {
  border-radius: 1rem; border: 1px solid rgba(255,255,255,.12);
  background: rgba(255,255,255,.025);
  backdrop-filter: blur(22px) saturate(170%); -webkit-backdrop-filter: blur(22px) saturate(170%);
  box-shadow: 0 16px 40px -16px rgba(0,0,0,.7), inset 0 1px 0 rgba(255,255,255,.16);
}
```

- **Chips and selectors:** pill-shaped, `border:1px solid rgba(255,255,255,.12);`
  `background:rgba(255,255,255,.06)`; accent indigo (`#818cf8` / `#4f46e5`).
- **Type and charts:** slate text (`#e2e8f0`, muted `#94a3b8`), tabular numbers for KPIs,
  transparent chart backgrounds with faint gridlines (`rgba(255,255,255,.08)`).
- **Layout:** a responsive grid (`repeat(auto-fit,minmax(280px,1fr))`); KPI tiles first,
  then charts, then detail tables.

A tool the user names wins over this workflow.
