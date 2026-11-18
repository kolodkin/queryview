# Dashboard snapshot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** **Snapshot** on `/dashboard` downloads the open dashboard as one static, script-free `.html` file.

**Architecture:** The frame's prologue answers `qv-snapshot` by serializing its own document, widget shadow roots included as declarative shadow DOM. The host wraps that text behind a script-blocking CSP and downloads it.

**Tech Stack:** React 19, vitest, Playwright; `Element.getHTML({shadowRoots})`.

**Spec:** `docs/superpowers/specs/2026-11-18-html-snapshot-design.md`

## Global Constraints

- No change to the iframe `sandbox`.
- The file runs no script: the CSP meta is the first thing in it, ahead of anything the frame sent.
- e2e only on the suite's own backend (`npm run e2e` / plain `npx playwright test`), never `BASE_URL` at the dev server.
- No new dependency (see Ruling 1).

## Rulings against the spec

1. The host does not parse the frame's HTML. The frame swaps scripts and canvases out of its live DOM for the serialization and back; the host prepends `<!doctype html>`, charset, the CSP and the title to the text. The CSP holds whatever the frame sent, so the security goal is met without `DOMParser`, and the cleaner is a pure string function testable without `happy-dom`.
2. The prologue, not the widget mount, writes each shadow root's adopted stylesheet into a temporary `<style>`: open shadow roots expose `adoptedStyleSheets`, so widgets need only marker attributes.

## Review Focus

1. A frame that answers with a non-string or a huge payload: ignored, error banner after the timeout.
2. A dashboard with no widgets and no canvas: still a valid file.
3. A tainted canvas: `toDataURL` throws; it is left as a canvas, the snapshot still completes.
4. The live page after a snapshot: scripts and canvases are back in place, charts still drawn, widgets still interactive.
5. Title containing `<` or `&`: escaped in `<title>`.

---

### Task 1: The frame serializes itself; the host wraps it

**Files:** `frontend/src/core/dashboard/srcDoc.ts`, `frontend/src/core/dashboard/snapshot.ts` (new), `frontend/src/core/index.ts`, `frontend/src/core/widgets/SelectView.tsx`, `frontend/src/core/results/ResultsTable.tsx`; tests `srcDoc.test.ts`, `snapshot.test.ts` (new).

**Interfaces (produces):**
- Frame: on `{type:'qv-snapshot'}` posts `{type:'qv-snapshot-result', html: string}` or `{type:'qv-snapshot-result', message: string}`.
- `parseSnapshotResult(data: unknown): { html: string } | { message: string } | null`; `html` at most `MAX_SNAPSHOT_BYTES = 50_000_000` characters.
- `snapshotDocument(html: string, title: string): string`.
- Markers: `data-qv-chrome` on what a snapshot hides (the widget's controls row, its pickers, the long-value button); `data-qv-scroll` on what it uncaps (the widget's `<section>`, the table wrapper).

- [ ] Failing unit tests: `snapshotDocument` starts with `<!doctype html><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="script-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'">`, escapes the title, keeps the html after it; `parseSnapshotResult` accepts html and message forms, rejects others and oversize; the prologue contains `'qv-snapshot'`, `getHTML(`, `adoptedStyleSheets`, `[data-qv-chrome]`.
- [ ] Run: `cd frontend && npx vitest run src/core/dashboard` → FAIL.
- [ ] Implement. Prologue steps on `qv-snapshot`: collect every open shadow root; sync form state to attributes; swap each `<script>` for a comment and each readable `<canvas>` for an `<img>` (same `class`, `style`, `width`, `height`); append to each shadow root a `<style>` of its adopted sheets' rules plus `[data-qv-chrome]{display:none!important}[data-qv-scroll]{max-height:none!important;flex:none!important}`; `document.documentElement.getHTML({shadowRoots})`; undo every swap in a `finally`; post the result.
- [ ] Run unit tests, `npx tsc -b`, `npx eslint src` → PASS. Commit.

### Task 2: The Snapshot button

**Files:** `frontend/src/app/DashboardView.tsx`, `docs/dashboard.md`, `e2e/dashboard.spec.ts`.

- [ ] Failing e2e `Snapshot downloads the dashboard as a static file`: a dashboard with a `<qv-param>`, a drawn `<canvas id="c">`, an inline `<script>` and `<qv-select-view query="rows" limit="200">`; click `dashboard-snapshot`; the download is named `snap.html`; its text has no `<script`; opened in a context with `javaScriptEnabled: false`: 200 `tbody tr`, `qv-limit` hidden, `img` in place of `#c`, the table wrapper's `scrollHeight <= clientHeight`. Back on the live page the canvas is still there and `qv-limit` still visible.
- [ ] Run → FAIL (`dashboard-snapshot` not found).
- [ ] Implement: button `data-testid="dashboard-snapshot"` after `ExportImportControls`, label **Snapshot**, `disabled={!active || loading}`; posts `qv-snapshot`, awaits the result (5 s timeout → `setError('The dashboard did not answer the snapshot request.')`), `downloadText(`${active.name || 'dashboard'}.html`, snapshotDocument(html, name), 'text/html')`.
- [ ] Docs per the spec.
- [ ] Run e2e (dashboard + widgets specs), pre-commit on touched files → PASS. Commit.

### Task 3: Ship

- [ ] Delete the spec and this plan; commit; push; open the PR.
