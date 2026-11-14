// The backend-agnostic kernel: result parsing, cell rendering, presentation
// pickers, and the dashboard sandbox and its widgets. Nothing here fetches, routes,
// or reads app state, and it imports nothing outside itself (both enforced by
// eslint.config.js), so this folder is what another app reuses; it brings its
// own styles (kernel.css), themed through the --qv-* variables. The app
// imports it only through this file.

export {
  EMPTY_ROWS,
  cellText,
  columnNames,
  columnTypes,
  isContainer,
  type Cell,
  type ColumnMeta,
  type QueryRows,
} from './results/rows'
export { ResultsTable } from './results/ResultsTable'
export { renderDefaultCell } from './cells/defaultCell'
export {
  complexCellItems,
  parseComplexType,
  PREVIEW_COUNT,
  type CellItem,
  type ComplexType,
} from './cells/complexCells'
export { ComplexCell } from './cells/ComplexCell'
export { shownColumnIndices } from './presentation/presentation'
export { FieldPickers, type Field, type OrderCol } from './presentation/FieldPickers'
export { SearchPanel } from './presentation/SearchPanel'
export { filterNames } from './nameFilter'
export { useDismiss } from './useDismiss'
export { useCopy } from './useCopy'
export { DashboardFrame } from './dashboard/DashboardFrame'
export { buildSrcDoc, type DashboardResults, type QvTheme, type QvToken } from './dashboard/srcDoc'
export {
  applyToQueries,
  parseDashboardParams,
  parseParamsRequest,
  resolveParams,
  type DashboardParam,
  type Dialect,
  type QueryRunner,
  type ResolvedParam,
} from './dashboard/params'
export {
  parseFieldsAttr,
  parseOrderByAttr,
  parseWidgetRequest,
  failureReply,
  rejectedWidgetReply,
  widgetQueryNames,
  type WidgetReply,
  type WidgetRequest,
} from './dashboard/widgetChannel'
