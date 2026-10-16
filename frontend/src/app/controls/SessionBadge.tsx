import type { SavedConnection } from '../savedConnections'

// Marks a session connection (and who added it); saved ones get nothing.
export function SessionBadge({
  conn,
  className = '',
}: {
  conn: SavedConnection
  className?: string
}) {
  if (conn.scope !== 'session') return null
  return (
    <span data-testid="conn-session-badge" className={`text-amber-300 ${className}`}>
      session{conn.created_by === 'agent' ? ' · agent' : ''}
    </span>
  )
}
