// The height steps of a SQL textbox, shared by QueryView and the Queries page:
// Min collapses it so the results get the room.
export const TEXTAREA_SIZES: [label: string, rows: number][] = [
  ['Min', 0],
  ['S', 4],
  ['M', 8],
  ['L', 16],
  ['XL', 28],
]

// The textarea classes for a height step; Min keeps the element (and its
// value) but takes no room.
export function textareaSizeClass(rows: number): string {
  return rows === 0 ? 'h-0 min-h-0 overflow-hidden border-transparent py-0' : 'py-2'
}
