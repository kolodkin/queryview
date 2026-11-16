# `<qv-chip>` dashboard widget

## Intent

A KPI pill bound to a dashboard query: one value, optionally labelled, that
follows parameter changes. Today an author writes script against
`window.queries` and redraws it on every `onQueryResults`; the chip makes that
one tag.

```html
<qv-chip query="totals" column="revenue" label="Revenue"></qv-chip>
```

## Approaches

1. **Read `window.queries`** (the up-front results): no new host channel; the
   chip re-reads on `params-results`, as `<qv-param>` does. **Picked.**
2. Own the query through the widget channel, like `<qv-select-view>`: a request
   per chip and a new host message, for one cell.

## Design

- **Attributes:** `query` (required), `column` (default: the query's first
  column), `label` (default: none). The value is row 1 of that column.
- **Rendering:** a pill in the kernel's glass style, `label` muted, value with
  `tabular-nums`; accent from `--qv-*` tokens only. The value is shown as
  `cellText` gives it: 64-bit and decimal strings stay unrounded; no number
  formatting.
- **States:** no rows → `—`; unknown query → `Unknown query “…”`; unknown
  column → `Unknown column “…”`. A failed re-run keeps the last value, since
  the prologue keeps the previous `window.queries`.
- **Updates:** `onParamsResults` (`core/widgets/frameChannel.ts`) re-reads
  `window.queries`, covering a param change and Execute.
- **Code:** `core/widgets/Chip.tsx`; registered in `src/widgets.tsx` with
  `defineWidget('qv-chip', …, 'inline-block')`. The bundle already loads for
  any `<qv-` tag; no backend change.
- **A query a chip names stays in `window.queries`**: unlike
  `<qv-select-view>`, the chip doesn't own it, so a chart may share it.
- **Docs:** `dashboard.md` Widgets section; the `push_dashboard` description
  (`mcp_server.py`) and the queryview `SKILL.md` tag list; drop the chip from
  `future.md`'s "More widgets".
- **Tests:** a vitest for `Chip` (value, default column, `—`, both unknowns,
  update on `params-results`); one chip added to the existing widgets e2e,
  checking it changes with a `<qv-param>`.

## Non-goals

Number formatting or units, trend arrows or deltas, a row other than the
first, aggregation in the widget, click actions.
