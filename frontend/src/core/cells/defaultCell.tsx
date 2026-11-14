// A cell with no design of its own: collections (a ClickHouse Array / Map /
// Tuple, or any JSON array or object) get the built-in collapsible view, the
// rest is plain text.

import { ComplexCell } from './ComplexCell'
import { parseComplexType } from './complexCells'
import { cellText, isContainer, type Cell } from '../results/rows'

export function renderDefaultCell(
  colName: string,
  value: Cell,
  colTypes: Record<string, string>,
): React.ReactNode {
  const complex = parseComplexType(colTypes[colName] ?? '')
  if (complex || isContainer(value))
    return <ComplexCell type={complex} value={value} col={colName} />
  return cellText(value)
}
