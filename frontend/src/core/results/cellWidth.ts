// How wide a result cell gets, and when a value can't be read inside one.
// Lives with the grid that renders the box, not with the cell contents.

export const CELL_WIDTH_CH = 50

// The column box: CELL_WIDTH_CH characters of content plus the cells' own px-2
// padding on both sides, so exactly that many characters are visible. The table
// is monospace throughout, so `ch` means the same in every cell.
export const CELL_WIDTH = `calc(${CELL_WIDTH_CH}ch + 1rem)`

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
