// The document a dashboard iframe renders: a theme, a prologue + the agent HTML.

import type { ResolvedParam } from './params'

// Column-oriented results map: {query_name: {column_name: values[]}}.
export type DashboardResults = Record<string, Record<string, unknown[]>>

// The kernel's theme tokens (core/kernel.css), each a --qv-<token> variable.
// Keep in step with the @property list in kernel.css.
const QV_TOKENS = ['accent', 'accent-strong', 'accent-soft', 'accent-text', 'accent-ink'] as const
export type QvToken = (typeof QV_TOKENS)[number]
export type QvTheme = Partial<Record<QvToken, string>>

// Variables don't cross into the sandboxed frame, so the host's theme is
// written into it; the widgets' shadow roots inherit it from there. Unknown
// keys and values that could leave the style block are dropped.
function themeStyle(theme: QvTheme): string {
  const vars = QV_TOKENS.filter((k) => typeof theme[k] === 'string' && !/[<;{}]/.test(theme[k]))
    .map((k) => `--qv-${k}:${theme[k]};`)
    .join('')
  return vars ? `<style>:root{${vars}}</style>\n` : ''
}

// The in-iframe half of the params channel, plus the bound values. The page
// sends values only; the host substitutes them into the dashboard's own SQL and
// posts results back, so the page re-renders without a reload and never handles
// SQL. Wrapped so a page script can't replace the binder by reusing a name.
const SET_PARAMS_HELPER = `
(function () {
function own(o, k) { return o != null && Object.prototype.hasOwnProperty.call(o, k); }
// Fill each [data-qv-query] element with row 1 of its data-qv-column
// (default: the query's first column). A query with no results here (held back
// for an unchosen param, failed, or a widget's) reads as a dash, not an error.
// The text mirrors cellText (core/results/rows.ts), with null as a dash.
function bind() {
  document.querySelectorAll('[data-qv-query]').forEach(function (el) {
    var q = el.getAttribute('data-qv-query');
    var cols = own(window.queries, q) ? window.queries[q] : null;
    var c = el.getAttribute('data-qv-column') || (cols && Object.keys(cols)[0]) || '';
    var vals = own(cols, c) ? cols[c] : null;
    var v = vals && vals.length ? vals[0] : null;
    el.textContent = cols && !vals ? 'Unknown column \\u201c' + c + '\\u201d'
      : v === null ? '\\u2014' : typeof v === 'object' ? JSON.stringify(v) : String(v);
  });
}
document.addEventListener('DOMContentLoaded', bind);
window.setParams = function (values) {
  parent.postMessage({ type: 'set-params', values: values }, '*');
};
window.addEventListener('message', function (e) {
  var d = e.data;
  if (!d || d.type !== 'params-results') return;
  // A failed run keeps the previous results on screen and reports the message.
  if (d.results) { window.queries = d.results; bind(); }
  if (d.params && d.params.length) window.params = d.params;
  if (typeof window.onQueryResults === 'function') {
    window.onQueryResults(window.queries, window.params, d.ok ? null : d.message);
  }
});
})();`

// Build the iframe document: a prologue exposing results as `window.queries`,
// the resolved selectors as `window.params` and `window.setParams`, then the
// agent-authored HTML. JSON `<` is escaped so an embedded `</script>` in result
// data can't break out of the prologue script.
export function buildSrcDoc(
  html: string,
  results: DashboardResults,
  params: ResolvedParam[] = [],
  theme: QvTheme = {},
): string {
  const safe = (v: unknown) => JSON.stringify(v).replace(/</g, '\\u003c')
  return (
    themeStyle(theme) +
    `<script>window.queries = ${safe(results)};\nwindow.params = ${safe(params)};` +
    `${SET_PARAMS_HELPER}\n</script>\n` +
    // The <qv-*> tags: loaded only by dashboards that use one, deferred so the
    // tags upgrade once the HTML, their <template> children included, is parsed.
    (/<qv-/i.test(html) ? `<script defer src="${__WIDGETS_URL__}"></script>\n` : '') +
    html
  )
}
