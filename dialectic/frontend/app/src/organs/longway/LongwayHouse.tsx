import { useEffect, useRef, useState } from 'react'
import { api } from '../../lib/api'
import { useLongwayChart } from '../../hooks/useLongwayChart'
import { declineRequester, inviteRequester, listInviteRequests, longwayPath, longwayRequest } from './api'
import type { InviteRequests, RequesterInvite } from './api'
import Chart from './chartSlot'

function requestDate(value: string) {
  return new Date(value).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
}

function SeatRequests({ roomId }: { roomId: string }) {
  const [data, setData] = useState<InviteRequests | null>(null)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  const [busy, setBusy] = useState<string | null>(null)
  const [invites, setInvites] = useState<Record<string, RequesterInvite>>({})
  const writing = useRef(false)
  useEffect(() => {
    let live = true
    setError('')
    void listInviteRequests(roomId).then(result => { if (live) setData(result) })
      .catch(error => { if (live) setError(error instanceof Error ? error.message : 'Could not load requests') })
    return () => { live = false }
  }, [roomId, retry])

  async function decide(id: string, decision: 'invited' | 'declined') {
    if (writing.current) return
    writing.current = true; setBusy(id); setError('')
    try {
      if (decision === 'invited') {
        const result = await inviteRequester(roomId, id)
        setInvites(current => ({ ...current, [id]: result }))
      } else {
        await declineRequester(roomId, id)
      }
      setData(current => current && ({ ...current, requests: current.requests.map(request => request.id === id
        ? { ...request, decision, decided_at: new Date().toISOString() } : request) }))
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Could not save the decision')
    } finally { writing.current = false; setBusy(null) }
  }

  const requests = [...(data?.requests ?? [])].sort((a, b) =>
    Number(a.decision !== null) - Number(b.decision !== null) || b.created_at.localeCompare(a.created_at))
  return <section aria-label="Asking for a seat" className="longway-seat-requests">
    <h2>Asking for a seat</h2>
    {data?.mail_configured === false && <p>Email to you is not set up yet; requests wait here.</p>}
    {error && <p role="alert">{error} {!data && <button onClick={() => setRetry(value => value + 1)}>Retry requests</button>}</p>}
    {!data && !error && <p role="status">Loading requests</p>}
    {data && requests.length === 0 && <p>Nobody is asking right now.</p>}
    {requests.map(request => {
      const invite = invites[request.id]
      return <article key={request.id} className={`longway-card${request.decision ? ' is-decided' : ''}`} aria-label={`Request from ${request.name}`} aria-busy={busy === request.id}>
        {request.decision ? <p>{request.name} · {request.decision}{request.decided_at && ` ${requestDate(request.decided_at)}`}</p> : <>
          <h3>{request.name}</h3>
          <p>{request.email}</p>
          {request.note && <p className="longway-plan">{request.note}</p>}
          <p>asked {requestDate(request.created_at)}</p>
        </>}
        <div className="longway-actions">
          {request.decision !== 'declined' && <button disabled={busy !== null} onClick={() => void decide(request.id, 'invited')}>{request.decision === 'invited' ? 'Invite again' : 'Invite'}</button>}
          {!request.decision && <button disabled={busy !== null} onClick={() => void decide(request.id, 'declined')}>Decline</button>}
        </div>
        {invite && <p role="status" className="longway-invite-result">
          {invite.mail_error ? <>Invited, but the email failed: {invite.mail_error}. Give {invite.email} this code: <code>{invite.code}</code></>
            : invite.emailed ? <>Invited. The code went to {invite.email}.</>
              : <>Invited. Email is off; give {invite.email} this code: <code>{invite.code}</code> (works 7 days)</>}
        </p>}
      </article>
    })}
  </section>
}

export function LongwayHouse({ roomId, canManageHome, onNavigate }: {
  roomId: string; canManageHome: boolean; onNavigate: (roomId: string) => Promise<unknown> | void
}) {
  const { data, error, refresh } = useLongwayChart(roomId)
  const [selected, setSelected] = useState<string | null>(null)
  const [myth, setMyth] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [writeError, setWriteError] = useState('')
  // Retain a created room if bind fails: retry binds that room, never creates
  // another one. The created id is exposed with the failure for recovery.
  const created = useRef<Record<string, { id: string; token: string }>>({})
  const opening = useRef(false)
  async function openRoom(slug: string, title: string) {
    if (opening.current || !canManageHome) return
    opening.current = true; setBusy(slug); setWriteError('')
    try {
      const room = created.current[slug] ?? await api.createRoom(title) as { id: string; token: string }
      created.current[slug] = room
      await longwayRequest(longwayPath(room.id, 'bind'), { method: 'POST', body: JSON.stringify({ slug }) }, room.token)
      refresh()
      if (await onNavigate(room.id) === false) throw new Error('Room is ready but could not be entered')
    } catch (error) {
      setWriteError(`${error instanceof Error ? error.message : 'Could not open room'}${created.current[slug] ? ` — room ${created.current[slug].id} exists; retry to finish opening it.` : ''}`)
    } finally { opening.current = false; setBusy(null) }
  }
  if (error) return <div role="alert">{error} <button onClick={refresh}>Retry house</button></div>
  if (!data) return <p role="status">Chart loading</p>
  return <div className="longway-house scene-body">
    <div className="longway-chart"><Chart data={data} focus={null} selected={selected} myth={myth} onSelectJourney={setSelected} onSelectLeg={slug => setSelected(slug)} /></div>
    <label><input type="checkbox" checked={myth} onChange={e => setMyth(e.target.checked)} /> Without the mythology</label>
    <section aria-label="Your rooms"><h2>Your rooms</h2>{data.rooms.map(room => <p key={room.id}>
      <button onClick={() => void onNavigate(room.id)}>{room.name}</button>{room.linked_journey && ` · ${data.journeys.find(j => j.slug === room.linked_journey)?.title ?? room.linked_journey}`}
    </p>)}</section>
    {canManageHome && <SeatRequests key={roomId} roomId={roomId} />}
    {writeError && <p role="alert">{writeError}</p>}
    <section aria-label="Journeys"><h2>Journeys</h2>{data.journeys.map(journey => {
      const room = data.rooms.find(r => r.linked_journey === journey.slug)
      return <article key={journey.slug} className="longway-card" data-selected={selected === journey.slug || undefined}>
        <h3><button onClick={() => setSelected(journey.slug)}>{journey.title}</button></h3>
        <p>{journey.pull}</p><p>{journey.status} · {journey.feasibility ?? 'unknown'}</p>
        {room ? <button onClick={() => void onNavigate(room.id)}>Open {room.name}</button>
          : canManageHome && journey.kind === 'candidate' && <button disabled={busy !== null} onClick={() => void openRoom(journey.slug, journey.title)}>{busy === journey.slug ? 'Opening…' : 'Open a room for this journey'}</button>}
      </article>
    })}</section>
  </div>
}
