# Dashboard snapshot

**Snapshot** on the dashboard page downloads the open dashboard as one static
`.html` file: what is on screen now, every row the widgets hold, no scripts.

## Why

A dashboard lives in a sandboxed frame: it cannot print, download or open a
window, and the browser's own print shows a slice of the frame. Printing the
frame from the host was tried and dropped: the browser paginates the frame
as one image, so rows are sliced at page breaks, widget controls print as
dead buttons and wide tables are cut. A dashboard is one continuous page; a
file that keeps it that way is the right export. Whoever needs a PDF prints
the file.

## Goals

- One self-contained file that opens in any browser and needs no JavaScript.
- It shows the dashboard as rendered: current parameters, the page's own
  styling, charts, and every row each widget holds, with no scroll boxes.
- Widget controls (Fields, Limit, Offset, Previous/Next, Download CSV, the
  pickers) are not in it.
- No sandbox change. The file can run no script, whatever the dashboard's
  HTML tried to put in it.

## Non-goals

- A live or refreshable file: it is a frozen picture.
- Rows a widget has not fetched: raise its **Limit** first.
- Inlining what the dashboard loads from elsewhere (CDN stylesheets, fonts,
  images): those need the network when the file is opened.
- PDF, and the dropped **Print** button.
- Canvas content the browser refuses to read (a canvas tainted by a
  cross-origin image): it stays blank.

## Approaches

1. **The frame serializes itself; the host cleans and downloads** (chosen).
   Only the frame can read its DOM (it has an opaque origin), and only the
   host can download. Widget shadow roots are written as declarative shadow
   DOM (`<template shadowrootmode="open">`), which renders without
   JavaScript and keeps the widget's styles apart from the page's.
2. **Flatten widgets into plain tables in the page.** No shadow DOM in the
   file, but the widget stylesheet (Tailwind, with its resets) would then
   apply to the agent's own HTML and change its look. Rejected.
3. **Server-side render** with a headless browser. A heavy dependency, and it
   would render a second, different run of the queries instead of what the
   user is looking at. Rejected.

## Design

### Frame: `qv-snapshot`

On `{type: 'qv-snapshot'}` from the host, the prologue (`srcDoc.ts`):

1. Writes live form state into attributes, since serialization reads
   attributes: `value` on inputs, `selected` on options, `checked` on
   checkboxes (the page's and the widgets').
2. Tags each `<canvas>` it can read with a `data-qv-snap` index and collects
   `toDataURL()` for it.
3. Serializes `document.documentElement` with every widget shadow root
   included (`getHTML({shadowRoots})`).
4. Posts `{type: 'qv-snapshot-result', html, canvases}` and removes the tags.

The widget stylesheet is adopted, not in the DOM, so serialization would lose
it. In snapshot the widget's mount writes it into its shadow root as a
`<style>` for the serialization. The same style carries the snapshot rules:
the controls row and pickers hidden, the 36rem height cap and inner scroll
off, the long-value buttons hidden.

### Host: clean and download

The host treats the frame's answer as untrusted text. A pure function,
`cleanSnapshot(html, canvases, title): string` in `core/dashboard`:

- parses it inertly (`DOMParser`);
- removes every `<script>`, and with them `window.queries`, which holds
  query results the page may not display;
- puts `<meta http-equiv="Content-Security-Policy" content="script-src
  'none'; object-src 'none'; base-uri 'none'; form-action 'none'">` first in
  `<head>`, so inline handlers and `javascript:` links are dead too;
- adds `<meta charset="utf-8">` and `<title>`: the dashboard's name;
- replaces each tagged canvas with an `<img>` of its data URL, accepting only
  `data:image/png` values;
- returns `<!doctype html>` plus the document.

**Snapshot**, in the toolbar after **Export**, is disabled while no dashboard
is open or its queries are running. It asks the frame, cleans the answer and
downloads `<name>.html` (`dashboard.html` for an unsaved draft) with the
existing `downloadText`. A frame that does not answer within 5 s shows the
page's error banner.

### Docs

- `dashboard.md`: **Snapshot** in the page list and sketch; under "Isolation
  & security", what the file contains (rendered results, so treat it as
  data) and that it carries no script.

## Tests

- Frontend unit: `cleanSnapshot` removes scripts, places the CSP first,
  swaps tagged canvases, rejects a non-PNG data URL, keeps
  `<template shadowrootmode>` content intact; the prologue answers
  `qv-snapshot`. Needs a DOM in vitest (`happy-dom` for that test file), a
  new dev dependency.
- e2e: a dashboard with a parameter, a canvas chart and a widget at limit
  200. **Snapshot** downloads a file; opened in a context with JavaScript
  disabled, it shows 200 rows with none clipped, the chart as an image, the
  chosen parameter, no widget controls, and contains no `<script>`.

## Left to the builder

- How the widget learns it is in snapshot (a message, or a variable on
  `:root` as the theme tokens are passed).
- Whether the widget stylesheet is written once per widget or shared: it is
  about 100 KB, so a dashboard with many widgets grows by that much each.
- The button's label, if **Snapshot** reads poorly beside **Export**.
