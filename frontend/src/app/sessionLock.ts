// Fire-and-forget edit-lock control for the live QueryView session. The lock is
// advisory (the backend TTL-expires it), so failures are swallowed.
import { apiFetch } from './api'

export async function postLock(
  sessionId: string,
  action: 'acquire' | 'release',
): Promise<void> {
  if (!sessionId) return
  try {
    await apiFetch('/api/remote/lock', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId, action }),
    })
  } catch {
    /* advisory lock: ignore transport errors */
  }
}
