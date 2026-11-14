// A `<template column>` child of `<qv-select-view>`: HTML used per row, with
// `{cell}` and `{row.<column>}` substituted. See docs/dashboard.md, "Widgets".

import { escapeHtml, substituteCellTemplate } from './cellView'

// Values are HTML-escaped, and URL-encoded inside an href or src (however the
// attribute is cased, spaced or quoted), so database content stays inert there
// and in text. Other attributes (style, on*) get HTML escaping only. Both passes read the original row: one pass each, never
// re-resolving a value that looks like a placeholder.
export function renderCellTemplate(
  template: string,
  raw: string,
  row: string[],
  columns: string[],
): string {
  // Split on URL attributes so each piece gets exactly one substitution pass.
  return template
    .split(/(\b(?:href|src)\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+))/i)
    .map((piece, i) =>
      substituteCellTemplate(piece, raw, row, columns, i % 2 ? encodeURIComponent : escapeHtml),
    )
    .join('')
}
