import type { SavedConnection } from '../savedConnections'

// Marks a connection the agent added; the user's own get nothing.
export function AgentBadge({
  conn,
  className = '',
}: {
  conn: SavedConnection
  className?: string
}) {
  if (conn.created_by !== 'agent') return null
  return (
    <span data-testid="conn-agent-badge" className={`text-amber-300 ${className}`}>
      agent
    </span>
  )
}
