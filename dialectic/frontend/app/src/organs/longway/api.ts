import { api } from '../../lib/api'

/** Same JWT and room capability as the shared API. An explicit token is used
 * only while binding a newly created room, before navigation installs it. */
export async function longwayRequest<T>(path: string, options: RequestInit = {}, roomToken = api.getToken()): Promise<T> {
  const response = await fetch(path, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(api.getAccessToken() ? { Authorization: `Bearer ${api.getAccessToken()}` } : {}),
      ...(roomToken ? { 'X-Room-Token': roomToken } : {}),
      ...options.headers,
    },
  })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(body?.detail ?? `Request failed (${response.status})`)
  }
  return response.json() as Promise<T>
}

export function longwayPath(roomId: string, resource: string) {
  return `/rooms/${encodeURIComponent(roomId)}/longway/${resource}`
}
