# Print a dashboard

A **Print** button on the dashboard page prints the whole dashboard through
the browser's print dialog, which is also where **Save as PDF** lives.

## Why

A dashboard renders in `<iframe sandbox="allow-scripts allow-popups
allow-popups-to-escape-sandbox" srcdoc=…>`. Nothing inside can get it out:
`window.print()` needs `allow-modals`, `<a download>` needs
`allow-downloads`, and `window.open(blob:)` is refused for an opaque origin.
Printing the page from the browser menu prints only the visible 78vh slice
of the frame, and a `qv-select-view` clips itself at 36rem with an inner
scroll. So neither the agent's HTML nor the user can get a dashboard onto
paper or into a PDF.

## Goals

- **Print** prints the entire dashboard as it stands: the current parameters,
  every row each widget currently shows, nothing of the app's chrome.
- The screen layout is unchanged before and after.
- No new sandbox permission.

## Non-goals

- A PDF file produced by the server (a headless browser): a different project.
- Rows a widget has not fetched. A widget prints the page it holds; raise its
  **Limit** first for more.
- A frame that always fits its content. Printing resizes it for the print
  only.
- `allow-modals` / `allow-downloads` on the sandbox: alert and confirm can
  block the tab, and downloads from agent HTML are a new surface. Host-side
  print covers the need.

## Approaches

1. **Host-side print** (chosen): the frame reports its content height; the
   host unclips it, hides its own chrome under `@media print`, calls
   `window.print()`, and restores. Browsers print a sandboxed srcdoc frame's
   content, so no sandbox change.
2. **Relax the sandbox** so the dashboard prints itself: needs `allow-modals`,
   gives agent HTML alert/confirm/prompt, and each dashboard would have to
   implement its own print. Rejected.
3. **Server-side render** with a headless browser to a PDF file: a heavy
   dependency for a button; worth it only when something other than a person
   needs the file. Deferred.

## Design

### Frame → host: `qv-size`

The prologue (`srcDoc.ts`) posts `{type: 'qv-size', height}` to the host on
load, after each `onQueryResults`, and on every change of the document's
height (a `ResizeObserver` on `document.documentElement`). The host accepts
it only from the dashboard's own frame, as it does every frame message, and
keeps the last value.

### Host: the print

**Print**, in the toolbar after **Export**, disabled while no dashboard is
open or its queries are running:

1. Set the frame's height to the last `qv-size` (a style override, not a
   class change).
2. `window.print()`.
3. On `afterprint`, remove the override.

A print stylesheet on the dashboard page (`@media print`) hides the app
header, the toolbar, the SQL panel and the error banner, and removes the
frame's border, radius and the page's background so the paper is white. The
frame keeps its width; a dashboard wider than the page is cut at the edge,
as any web page is.

### Inside the frame

The widget's kernel stylesheet gains a print rule lifting `qv-select-view`'s
36rem cap and its inner scroll, so every held row prints. Panels and table
rows get `break-inside: avoid` so a page break does not split one.

### Docs

- `dashboard.md`: **Print** in the page section and the sketch; a line in
  "Isolation & security" that `window.print()` inside a dashboard is blocked
  by design and **Print** is the way out.
- `api.md`: nothing (no endpoint).

## Tests

- Frontend unit, `srcDoc.test.ts`: the prologue contains the `qv-size` post.
- e2e, `dashboard.spec.ts`: a tall dashboard (a widget over 200 rows at
  limit 200); `page.emulateMedia({media: 'print'})`; after **Print** is
  armed (the host sets the height before calling `window.print`, which the
  test stubs), the frame's height equals the reported content height, the
  toolbar is hidden, and inside the frame the widget's rows are all laid out
  (no scroll container shorter than its content).

## Left to the builder

- Whether to debounce `qv-size` (a ResizeObserver can fire in bursts).
- Button label: **Print**, or **Print / PDF**.
