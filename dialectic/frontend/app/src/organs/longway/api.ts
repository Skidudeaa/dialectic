import { api } from '../../lib/api'

export type InviteRequest = {
  id: string; email: string; name: string; note: string; created_at: string
  decision: null | 'invited' | 'declined'; decided_at: string | null
  notified_at: string | null; invited_email_at: string | null
}
export type InviteRequests = { mail_configured: boolean; requests: InviteRequest[] }
export type RequesterInvite = {
  id: string; email: string; name: string; code: string; emailed: boolean
  mail_error: string | null; expires_at: string
}

/** The signed-out door must never inherit bearer or room credentials. */
export async function askForSeat(request: { email: string; name: string; note: string }): Promise<void> {
  const response = await fetch('/organ/longway/invite-requests', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
  if (response.ok) return
  if (response.status === 429) throw new Error('Too many asks from here. Try again later.')
  const body = await response.json().catch(() => null)
  const detail = body?.detail
  const message = typeof detail === 'string' ? detail : Array.isArray(detail)
    ? detail.map(item => typeof item?.msg === 'string' ? item.msg : '').filter(Boolean).join('; ') : ''
  throw new Error(message || 'Could not send your request')
}

export function listInviteRequests(roomId: string) {
  return longwayRequest<InviteRequests>(longwayPath(roomId, 'invite-requests'))
}

export function inviteRequester(roomId: string, id: string) {
  return longwayRequest<RequesterInvite>(longwayPath(roomId, `invite-requests/${encodeURIComponent(id)}/invite`), { method: 'POST' })
}

export function declineRequester(roomId: string, id: string) {
  return longwayRequest<{ id: string; decision: 'declined' }>(longwayPath(roomId, `invite-requests/${encodeURIComponent(id)}/decline`), { method: 'POST' })
}

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

/** Re-read projections after a Field write or a completed Scout run. */
export function notifyLongwayChanged(roomId: string) {
  window.dispatchEvent(new CustomEvent('longway:changed', { detail: longwayPath(roomId, '') }))
}

export const getRide = (roomId: string, ride?: string, signal?: AbortSignal) =>
  longwayRequest<import('./types').RideData>(longwayPath(roomId, `ride${ride ? `?ride=${encodeURIComponent(ride)}` : ''}`), { signal })
export const getRideLeg = (roomId: string, leg: string, signal?: AbortSignal) =>
  longwayRequest<import('./types').RideLeg>(longwayPath(roomId, `ride/leg?leg=${encodeURIComponent(leg)}`), { signal })
export const getRiding = (roomId: string, signal?: AbortSignal) =>
  longwayRequest<import('./types').RidingData>(longwayPath(roomId, 'riding'), { signal })
