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
  value: <span style="padding:1px 8px;border-radius:999px;font-size:12px;background:#e8f0fe;color:#1a56db">{cell}</span>
```

A chip's color comes from its template, not the value, so give a column one neutral
chip, or compute the color in SQL as its own column (e.g. `status_color`) and use
`{row.status_color}` in the style. Other good uses: numbers right-aligned with
`font-variant-numeric:tabular-nums`, small inline bars (`width:{row.pct}%`), a `link`
to the record in its own system. Array/Map/Tuple columns already render as lists;
leave them alone. Keep chips to columns with a handful of values.

## Dashboards

`push_dashboard` renders HTML fed by named queries as an unsaved draft; re-push to revise
it. See the tool's description for the `window.queries` and `params` contract.

Design it in a liquid-glass style:

- **Backdrop:** a soft full-page gradient (e.g. `linear-gradient(135deg,#dbeafe,#ede9fe,#fce7f3)`)
  so the glass has something to refract; never a flat white page.
- **Panels:** translucent cards — `background:rgba(255,255,255,.55)`,
  `backdrop-filter:blur(20px) saturate(180%)` (plus `-webkit-backdrop-filter`),
  `border:1px solid rgba(255,255,255,.6)`, `border-radius:20px`,
  `box-shadow:0 8px 32px rgba(15,23,42,.12)`, and an inner top highlight
  (`inset 0 1px 0 rgba(255,255,255,.8)`).
- **Type:** the system stack (`-apple-system, system-ui, sans-serif`); dark slate text
  (`#0f172a`, muted `#475569`) for contrast on glass; KPIs large with
  `font-variant-numeric:tabular-nums`.
- **Layout:** a responsive grid (`repeat(auto-fit,minmax(280px,1fr))`, 16–20px gaps); KPI
  tiles first, then charts, then detail tables.
- **Charts:** transparent chart backgrounds, light gridlines, one accent hue per series;
  rounded bars and smooth lines suit the style.
- **Controls:** `params` selectors as pill-shaped glass chips.
- **Restraint:** blur only on panels, not every element, and keep text on solid-enough
  fills to stay readable.

A tool the user names wins over this workflow.
