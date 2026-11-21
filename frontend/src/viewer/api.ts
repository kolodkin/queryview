// The viewer server's API (docs/server.md). No session: every request names
// its connection and dashboard, and none carries SQL.

type Json = Record<string, unknown>

// A failed request as the `{ok: false, message}` the server itself sends.
const failed = (message: string): Json => ({ ok: false, message })

export async function getJson(path: string): Promise<{ status: number; body: unknown }> {
  try {
    const res = await fetch(path)
    return { status: res.status, body: await res.json().catch(() => null) }
  } catch {
    return { status: 0, body: null }
  }
}

export async function postJson(path: string, body: Json): Promise<Json> {
  try {
    const res = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    const data = (await res.json().catch(() => null)) as Json | null
    return data ?? failed('request failed')
  } catch {
    return failed('request failed')
  }
}
