// How wide a result column gets, and when a value can't be read inside one.
// Lives with the grid that renders the box, not with the cell contents.

// The cap: no column grows past this many characters, so one long-text column
// can't stretch the grid.
export const CELL_WIDTH_CH = 50
// The floor: an empty column still has a box to see and click in.
const MIN_CELL_CH = 3

// A value needs the cell's scroller and its popup button when it can't be read
// in place: too wide for the column, or spanning lines — `whitespace-pre` turns
// those into extra rows, and multi-line text is exactly what the parsed view is
// for, however short it is.
//
// Character count stands in for rendered width, which holds for the monospace
// Latin text these grids mostly carry; double-width glyphs (CJK) overflow a
// little before it notices.
export function isOverflowing(text: string): boolean {
  return text.length > CELL_WIDTH_CH || text.includes('\n')
}

// A column's size: the characters it shows and whether any of its cells carries
// the popup button, which takes room of its own at the cell's left edge.
export type ColumnSize = { chars: number; button: boolean }

// Fit a column to its header or its widest cell line, between the floor and
// the cap. Lines rather than whole values, since a multi-line value renders as
// rows and is as wide as its widest one. A `capped` column (one drawn wider
// than its text, by a cell view or a complex-type list) takes the cap outright.
export function columnSize(header: string, texts: string[], capped = false): ColumnSize {
  let chars = capped ? CELL_WIDTH_CH : Math.max(MIN_CELL_CH, header.length)
  let button = false
  for (const text of texts) {
    if (isOverflowing(text)) button = true
    for (const line of text.split('\n')) chars = Math.max(chars, line.length)
  }
  return { chars: Math.min(chars, CELL_WIDTH_CH), button }
}

// The CSS width of these columns side by side: their characters, the cells'
// px-2 padding on both sides, and where a column has the button, its room: px-1
// and three text-xs glyphs for `{ }`, plus the gap to the text, ~2.1rem.
// The table is monospace throughout, so `ch` means the same in every cell.
export function columnsWidth(sizes: ColumnSize[]): string {
  let ch = 0
  let rem = 0
  for (const s of sizes) {
    ch += s.chars
    rem += s.button ? 3.25 : 1
  }
  return `calc(${ch}ch + ${rem}rem)`
}
