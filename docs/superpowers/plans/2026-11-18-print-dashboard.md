# Print a dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A **Print** button on `/dashboard` prints the whole dashboard, unclipped, through the browser's print dialog.

**Architecture:** The frame's prologue reports its content height to the host over the existing postMessage channel. The host keeps the last value, sets the iframe to that height around `window.print()`, and hides its chrome with Tailwind `print:` variants. Inside the frame the widget stylesheet lifts the widget's height cap under print.

**Tech Stack:** React 19, Tailwind v4 (`print:` variant), vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-11-18-print-dashboard-design.md`

## Global Constraints

- No change to the iframe `sandbox` attribute.
- The screen layout is identical before and after a print: the height override is removed on `afterprint`.
- Button label **Print**, after **Export** in the toolbar; disabled while no dashboard is open or its queries are running.
- Frame messages are accepted only from the dashboard's own frame (`e.source === frame.contentWindow`), as every message is today.
- Run checks with `uv run --frozen --group dev pre-commit run --files <files>`, `npx tsc -b` and `npx vitest run` in `frontend/`. e2e via `npm run e2e` or a backend started with a scratch `DATA_DIR`, never the dev server on `~/.queryview`.

## Review Focus

1. A forged `qv-size` with a huge or non-numeric height: the host must clamp or ignore it, never set a 10-million-pixel iframe. Pinned in Task 1 (`parseSizeReport`).
2. A dashboard whose `html,body{height:100%}` (the e2e `DASHBOARD_HTML`): the box height is the viewport, not the content; the prologue must report `scrollHeight`. Pinned in Task 1's prologue test by asserting the posted expression.
3. Print pressed while a re-run is in flight: the button is disabled on `loading`; otherwise the old height could be printed. Pinned in Task 2's e2e by asserting the disabled state during load.
4. `window.print()` where `afterprint` never fires (a stubbed print in tests, some headless browsers): the override must not leak into the next load. Task 2 keys the override off the frame element, which a reload replaces (`key={loadSeq}`).
5. A widget's rows past its 36rem cap: still clipped unless the in-frame print rule reaches the shadow root. Pinned in Task 3's e2e (scroll container no taller than its content).

---

### Task 1: The frame reports its height

**Files:**
- Modify: `frontend/src/core/dashboard/srcDoc.ts` (the `SET_PARAMS_HELPER` prologue)
- Modify: `frontend/src/core/dashboard/widgetChannel.ts`
- Modify: `frontend/src/app/DashboardView.tsx` (`onMessage`, near line 483)
- Test: `frontend/src/core/dashboard/srcDoc.test.ts`, `frontend/src/core/dashboard/widgetChannel.test.ts`

**Interfaces:**
- Produces: `parseSizeReport(data: unknown): number | null` in `widgetChannel.ts`: the height of a `{type: 'qv-size', height}` message, an integer in `[0, 50_000]`, else `null`.
- Produces: in `DashboardView`, `const sizeRef = useRef(0)` holding the last accepted height for the open frame.

- [ ] **Step 1: Write the failing tests**

`srcDoc.test.ts`:
```ts
test('the prologue reports the document height to the host', () => {
  const doc = buildSrcDoc('', {})
  expect(doc).toContain("type: 'qv-size'")
  expect(doc).toContain('document.documentElement.scrollHeight')
  expect(doc).toContain('new ResizeObserver(')
})
```
`widgetChannel.test.ts`:
```ts
describe('parseSizeReport', () => {
  test('accepts an integer height in range', () => {
    expect(parseSizeReport({ type: 'qv-size', height: 1234 })).toBe(1234)
  })
  test('rejects other messages and out-of-range or non-numeric heights', () => {
    expect(parseSizeReport({ type: 'widget-query' })).toBeNull()
    expect(parseSizeReport({ type: 'qv-size', height: '12' })).toBeNull()
    expect(parseSizeReport({ type: 'qv-size', height: -1 })).toBeNull()
    expect(parseSizeReport({ type: 'qv-size', height: 50_001 })).toBeNull()
    expect(parseSizeReport({ type: 'qv-size', height: 1.5 })).toBeNull()
  })
})
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd frontend && npx vitest run src/core/dashboard`
Expected: FAIL (`parseSizeReport` not exported; prologue lacks `qv-size`).

- [ ] **Step 3: Implement**

In `SET_PARAMS_HELPER`, after the `message` listener: a `report()` that posts `{type: 'qv-size', height: document.documentElement.scrollHeight}` to `parent`; call it on `DOMContentLoaded` and `load`, from a `ResizeObserver` observing `document.documentElement` and `document.body` (attached on `DOMContentLoaded`), and at the end of the `params-results` handler after `onQueryResults`. One comment line: the host prints the frame at this height.

In `widgetChannel.ts`: `export function parseSizeReport(data: unknown): number | null`, with the bounds in the Interfaces block.

In `DashboardView.tsx`: `const sizeRef = useRef(0)`; in `onMessage`, right after the source check, `const h = parseSizeReport(e.data); if (h !== null) { sizeRef.current = h; return }`.

- [ ] **Step 4: Run the tests and typecheck**

Run: `cd frontend && npx vitest run src/core/dashboard && npx tsc -b`
Expected: PASS, no type errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/core/dashboard frontend/src/app/DashboardView.tsx
git commit -m "Dashboard frame reports its content height to the host"
```

### Task 2: Print button and print styles

**Files:**
- Modify: `frontend/src/app/DashboardView.tsx` (toolbar after `ExportImportControls`, the `DashboardFrame` render, the SQL panel and error banner)
- Modify: `frontend/src/app/App.tsx:486` (the `<header>`)
- Modify: `frontend/src/index.css` (`@layer base`)
- Modify: `docs/dashboard.md`
- Test: `e2e/dashboard.spec.ts`

**Interfaces:**
- Consumes: `sizeRef` from Task 1.
- Produces: button `data-testid="dashboard-print"`; toolbar wrapper `data-testid="dashboard-toolbar"`.

- [ ] **Step 1: Write the failing e2e test**

In `e2e/dashboard.spec.ts`:
```ts
test("Print sizes the frame to its content and hides the chrome", async ({ page, seeds, baseURL }) => {
  await connect(page, DUCK, await seeds.duckdb());
  const frame = await openDashboard(page, baseURL, {
    name: "tall",
    html: '<qv-select-view query="rows" limit="200"></qv-select-view>',
    queries: { rows: "SELECT range AS n FROM range(200)" },
  });
  await expect(frame.getByTestId("qv-results").locator("tbody tr")).toHaveCount(200);
  await expect(page.getByTestId("dashboard-print")).toBeEnabled();

  await page.evaluate(() => { window.print = () => {}; }); // no dialog; afterprint never fires
  await page.getByTestId("dashboard-print").click();
  const content = await frame.locator("html").evaluate((el) => el.scrollHeight);
  await expect(page.getByTestId("dashboard-frame")).toHaveCSS("height", `${content}px`);

  await page.emulateMedia({ media: "print" });
  await expect(page.getByTestId("dashboard-toolbar")).toBeHidden();
  await expect(page.getByTestId("nav")).toBeHidden();
  const results = frame.getByTestId("qv-results");
  expect(await results.evaluate((el) => el.scrollHeight <= el.clientHeight)).toBe(true);
});
```
The last assertion belongs to Task 3's rule and fails until then; keep it here so one test covers the acceptance line.

- [ ] **Step 2: Run it to verify it fails**

Run: `npx playwright test e2e/dashboard.spec.ts -g "Print sizes"` (with the suite's own backend)
Expected: FAIL, `dashboard-print` not found.

- [ ] **Step 3: Implement the button**

In `DashboardView.tsx`:
- `function print()`: `const frame = frameRef.current; if (!frame) return; frame.style.height = `${sizeRef.current}px`; const restore = () => { frame.style.height = ''; window.removeEventListener('afterprint', restore) }; window.addEventListener('afterprint', restore); window.print()`.
- Button after `ExportImportControls`: `type="button"`, `data-testid="dashboard-print"`, `onClick={print}`, `disabled={!active || loading}`, class `glass-btn px-3 py-2 text-sm font-medium`, text **Print**.
- Add `data-testid="dashboard-toolbar"` and `print:hidden` to the toolbar's wrapper div; `print:hidden` on the SQL panel's wrapper (wrap `DashboardSqlPanel` in a `div` if it has none) and on the error `<p>`.
- `DashboardFrame`'s `className` default gains `print:rounded-none print:border-0`.

In `App.tsx`: `print:hidden` on the `<header>` at line 486.

Same toolbar, same size: the non-compact class in `ExportImportControls.tsx:25` and the Restore button in `GitSyncControls.tsx` lack `text-sm`, so **Restore**, **Export** and **Import** render larger than their neighbours. Add `text-sm` to both so every toolbar button is `glass-btn px-3 py-2 text-sm font-medium`.

In `index.css`, inside `@layer base`: `@media print { body { background: white; color: black } }`.

- [ ] **Step 4: Docs**

`docs/dashboard.md`: in the page list add `- **Print** — prints the whole dashboard, the frame sized to its content and the app's chrome hidden; the browser's dialog is where **Save as PDF** lives. A widget prints the page of rows it holds: raise its **Limit** first for more.` Add `[Print]` to the sketch after `[Import]`. In "Isolation & security" append: `window.print()` and downloads are blocked inside the frame by the sandbox; **Print** is the way out.

- [ ] **Step 5: Run checks**

Run: `cd frontend && npx tsc -b && npx eslint src/app && cd .. && uv run --frozen --group dev pre-commit run --files frontend/src/app/DashboardView.tsx frontend/src/app/App.tsx frontend/src/index.css docs/dashboard.md`
Expected: clean. The e2e still fails on its last assertion only.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app frontend/src/index.css frontend/src/core/dashboard/DashboardFrame.tsx docs/dashboard.md e2e/dashboard.spec.ts
git commit -m "Dashboard: Print prints the whole dashboard at its content height"
```

### Task 3: Widgets print unclipped

**Files:**
- Modify: `frontend/src/core/widgets/SelectView.tsx:180` (the `<section>` class)
- Modify: `frontend/src/core/results/ResultsTable.tsx:98` (the scroll wrapper) and its `<tr>` rows
- Test: `e2e/dashboard.spec.ts` (Task 2's test, last assertion)

**Interfaces:** none new.

- [ ] **Step 1: Confirm the failing assertion**

Run: `npx playwright test e2e/dashboard.spec.ts -g "Print sizes"`
Expected: FAIL on `scrollHeight <= clientHeight`.

- [ ] **Step 2: Implement**

`SelectView.tsx`: add `print:max-h-none print:break-inside-avoid` to the `<section>` class.
`ResultsTable.tsx`: add `print:overflow-visible` to the wrapper div's class and `print:break-inside-avoid` to each body `<tr>`.
`kernel.css` scans `src/core`, so the classes reach the widgets' shadow roots with no other change.

- [ ] **Step 3: Run the e2e and the unit suite**

Run: `npx playwright test e2e/dashboard.spec.ts && cd frontend && npx vitest run`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/core/widgets/SelectView.tsx frontend/src/core/results/ResultsTable.tsx
git commit -m "Widgets print every held row: no height cap or scroll under print"
```

### Task 4: Ship

- [ ] Delete the spec (`docs/superpowers/specs/2026-11-18-print-dashboard-design.md`) and this plan, per `docs/AGENTS.md`; commit `Docs: print-dashboard design shipped`.
- [ ] Run the full `npm run e2e` once; push; open the PR with a body naming **Print**, the `qv-size` report, the sandbox unchanged.
