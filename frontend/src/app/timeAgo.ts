// "just now" / "5 min ago" / "3 h ago" / "2 d ago" / a date — the recency line
// on a saved connection card. `now` is injectable for tests.
export function timeAgo(ms: number, now: number = Date.now()): string {
  const s = Math.max(0, Math.floor((now - ms) / 1000))
  if (s < 60) return 'just now'
  const m = Math.floor(s / 60)
  if (m < 60) return `${m} min ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h} h ago`
  const d = Math.floor(h / 24)
  if (d < 30) return `${d} d ago`
  return new Date(ms).toLocaleDateString()
}
