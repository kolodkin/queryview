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

// While a re-run is in flight the page carries data-qv-loading: a bar runs
// across its top (a lit segment sweeping over a faint track, clear of a rounded
// frame's corners), and the page's own CSS can dim what is now stale.
const LOADING_STYLE =
  '<style>html[data-qv-loading]::before{content:"";position:fixed;z-index:2147483647;top:0;left:0;' +
  'width:100%;height:4px;background:linear-gradient(90deg,transparent,var(--qv-accent,#818cf8) 35%,' +
  'var(--qv-accent,#818cf8) 65%,transparent) no-repeat,rgba(129,140,248,.4);' +
  'background-size:35% 100%,100% 100%;animation:qv-loading 1.2s linear infinite}' +
  '@keyframes qv-loading{from{background-position:-30% 0,0 0}to{background-position:130% 0,0 0}}</style>\n'

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
// The page as static HTML, for the host's Snapshot: scripts out, canvases as
// images, dropdowns as their chosen value, input state in attributes, and each widget's shadow root written as
// declarative shadow DOM with its stylesheet, marked as snapshotting. Every
// change to the live page is undone before returning.
function snapshot() {
  var undo = [];
  function swap(el, other) {
    el.replaceWith(other);
    undo.push(function () { other.replaceWith(el); });
  }
  // A stand-in for el: a new element carrying these attributes of its.
  function standIn(el, tag, names) {
    var other = document.createElement(tag);
    names.forEach(function (a) { if (el.hasAttribute(a)) other.setAttribute(a, el.getAttribute(a)); });
    return other;
  }
  // Serialization reads attributes, so live state is written into them.
  function attr(el, name, value) {
    var had = el.getAttribute(name);
    if (value === null) el.removeAttribute(name); else el.setAttribute(name, value);
    undo.push(function () {
      if (had === null) el.removeAttribute(name); else el.setAttribute(name, had);
    });
  }
  try {
    var roots = [];
    (function walk(scope) {
      scope.querySelectorAll('*').forEach(function (el) {
        if (el.shadowRoot) { roots.push(el.shadowRoot); walk(el.shadowRoot); }
      });
    })(document);
    // Stale or no rows yet: a re-run in flight, a widget mid-query, or a qv-* tag
    // the bundle has not upgraded (once the page has loaded, one still undefined
    // is unknown to it and stays).
    if (document.documentElement.hasAttribute('data-qv-loading') ||
        (document.readyState !== 'complete' && Array.prototype.some.call(document.querySelectorAll(':not(:defined)'), function (el) {
          return el.localName.indexOf('qv-') === 0;
        })) ||
        roots.some(function (root) { return root.querySelector('[data-qv-busy]'); })) {
      return { type: 'qv-snapshot-result', message: 'The dashboard is still loading. Take the snapshot when it has finished.' };
    }
    var scopes = [document].concat(roots);
    // Canvases are read before anything moves: one layout, and the size each
    // is shown at (a rule selecting canvas will not match its image).
    var images = [];
    scopes.forEach(function (scope) {
      scope.querySelectorAll('canvas').forEach(function (c) {
        var img = standIn(c, 'img', ['id', 'class', 'style', 'width', 'height']);
        try { img.src = c.toDataURL('image/png'); } catch (err) { return; } // tainted: left as is
        var box = c.getBoundingClientRect();
        img.style.width = box.width + 'px';
        img.style.height = box.height + 'px';
        images.push([c, img]);
      });
    });
    images.forEach(function (pair) { swap(pair[0], pair[1]); });
    scopes.forEach(function (scope) {
      scope.querySelectorAll('input').forEach(function (i) {
        if (i.type === 'password') attr(i, 'value', null);
        else if (i.type === 'checkbox' || i.type === 'radio') attr(i, 'checked', i.checked ? '' : null);
        else if (i.type !== 'file') attr(i, 'value', i.value);
      });
      scope.querySelectorAll('textarea').forEach(function (t) {
        var area = standIn(t, 'textarea', ['id', 'class', 'style', 'rows', 'cols']);
        area.textContent = t.value;
        swap(t, area);
      });
      // A dropdown becomes its chosen value: the file has nothing to pick.
      scope.querySelectorAll('select').forEach(function (sel) {
        var span = standIn(sel, 'span', ['id', 'class', 'style', 'data-testid']);
        span.textContent = Array.prototype.map.call(sel.selectedOptions, function (o) { return o.textContent; }).join(', ');
        swap(sel, span);
      });
      scope.querySelectorAll('script').forEach(function (s) {
        swap(s, document.createComment(''));
      });
    });
    // Every widget adopts one shared sheet: its text is built once.
    var texts = new Map();
    function cssText(sheet) {
      if (!texts.has(sheet)) {
        texts.set(sheet, Array.prototype.map.call(sheet.cssRules, function (r) { return r.cssText; }).join('\\n'));
      }
      return texts.get(sheet);
    }
    roots.forEach(function (root) {
      var style = document.createElement('style');
      style.textContent = root.adoptedStyleSheets.map(cssText).join('\\n');
      // The widgets' own stylesheet holds the snapshot rules, keyed on this.
      attr(root.host, 'data-qv-snapshotting', '');
      root.append(style);
      undo.push(function () { style.remove(); });
    });
    return { type: 'qv-snapshot-result', html: document.documentElement.getHTML({ shadowRoots: roots }) };
  } catch (err) {
    return { type: 'qv-snapshot-result', message: String(err && err.message || err) };
  } finally {
    undo.reverse().forEach(function (f) { f(); });
  }
}
window.addEventListener('message', function (e) {
  var d = e.data;
  if (d && d.type === 'qv-snapshot') { parent.postMessage(snapshot(), '*'); return; }
  // The host says when a re-run starts and when the last one has answered.
  if (d && d.type === 'qv-loading') { document.documentElement.toggleAttribute('data-qv-loading', !!d.on); return; }
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
    LOADING_STYLE +
    // The <qv-*> tags: loaded only by dashboards that use one, deferred so the
    // tags upgrade once the HTML, their <template> children included, is parsed.
    (/<qv-/i.test(html) ? `<script defer src="${__WIDGETS_URL__}"></script>\n` : '') +
    html
  )
}
