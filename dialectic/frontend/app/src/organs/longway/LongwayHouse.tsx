import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { api } from '../../lib/api'
import { useLongwayChart } from '../../hooks/useLongwayChart'
import { declineRequester, inviteRequester, listInviteRequests, longwayPath, longwayRequest } from './api'
import type { InviteRequests, RequesterInvite } from './api'
import type { Ink, Journey, Season } from './types'
import Chart from './chartSlot'
import { InkKey, JourneyStrip } from './chart/Cards'

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

function requestDate(value: string) {
  return new Date(value).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
}

/** [9, 10, 11, 12] -> "Sep–Dec"; runs that cross the new year join: [1, 2, 11, 12] -> "Nov–Feb". */
// Exported for its test; the cost is only a full reload instead of fast refresh when this file changes in dev.
// eslint-disable-next-line react-refresh/only-export-components
export function monthRuns(months: number[]): string {
  const sorted = [...new Set(months)].filter(m => m >= 1 && m <= 12).sort((a, b) => a - b)
  const runs: [number, number][] = []
  for (const m of sorted) {
    const last = runs[runs.length - 1]
    if (last && m === last[1] + 1) last[1] = m
    else runs.push([m, m])
  }
  if (runs.length > 1 && runs[0][0] === 1 && runs[runs.length - 1][1] === 12) {
    const first = runs.shift()!
    runs[runs.length - 1][1] = first[1]
  }
  return runs.map(([a, b]) => a === b ? MONTHS[a - 1] : `${MONTHS[a - 1]}–${MONTHS[b - 1]}`).join(', ')
}

function seasonLine(season: Season | null) {
  if (!season) return null
  const said = season.good.length ? `Best ${monthRuns(season.good)}` : season.possible.length ? `Possible ${monthRuns(season.possible)}` : null
  return said && (season.basis === 'hypothesis' ? `${said} (estimate)` : said)
}

function meta(journey: Journey) {
  const days = journey.days && (journey.days[0] === journey.days[1] ? `${journey.days[0]} days` : `${journey.days[0]}–${journey.days[1]} days`)
  return [journey.where, days, seasonLine(journey.season)].filter(Boolean).join(' · ')
}

const stage = (status: string) => status.charAt(0).toUpperCase() + status.slice(1).replace(/[_-]/g, ' ')

function feasibility(value: string | null) {
  if (!value) return null
  return value === 'unverified' ? 'Feasibility not checked yet' : `Feasibility: ${value}`
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
  const waiting = requests.filter(request => !request.decision).length
  return <section aria-label="Asking for a seat" className="longway-seat-requests lw-section">
    <h2>Asking for a seat{waiting > 0 && <>{' '}<span className="lw-count">{waiting} waiting</span></>}</h2>
    {data?.mail_configured === false && <p className="lw-note">Email to you is not set up yet; requests wait here.</p>}
    {error && <p role="alert" className="lw-alert">{error} {!data && <button onClick={() => setRetry(value => value + 1)}>Retry requests</button>}</p>}
    {!data && !error && <p role="status" className="lw-note">Loading requests</p>}
    {data && requests.length === 0 && <p className="lw-note">Nobody is asking right now.</p>}
    {requests.map(request => {
      const invite = invites[request.id]
      return <article key={request.id} className={`longway-card lw-request${request.decision ? ' is-decided' : ''}`} aria-label={`Request from ${request.name}`} aria-busy={busy === request.id}>
        {request.decision ? <p>{request.name} · {request.decision}{request.decided_at && ` ${requestDate(request.decided_at)}`}</p> : <>
          <h3>{request.name}</h3>
          <p className="lw-meta"><span>{request.email}</span> · <span>asked {requestDate(request.created_at)}</span></p>
          {request.note && <p className="longway-plan">{request.note}</p>}
        </>}
        <div className="longway-actions">
          {request.decision !== 'declined' && <button className={request.decision ? undefined : 'lw-primary'} disabled={busy !== null} onClick={() => void decide(request.id, 'invited')}>{request.decision === 'invited' ? 'Invite again' : 'Invite'}</button>}
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
  const globe = useRef<HTMLDivElement>(null)
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
  // Picking a journey in the list draws it on the globe, so bring the globe back into view when the list has
  // scrolled it away (a phone); beside the list (a wide screen) it never leaves.
  function show(slug: string) {
    setSelected(slug)
    const box = globe.current?.getBoundingClientRect()
    if (box && (box.top < 0 || box.top > window.innerHeight / 2)) {
      globe.current?.scrollIntoView?.({ behavior: window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches ? 'auto' : 'smooth', block: 'start' })
    }
  }
  if (error) return <div className="longway-house scene-body"><p role="alert" className="lw-alert">The house could not load: {error} <button onClick={refresh}>Retry house</button></p></div>
  if (!data) return <div className="longway-house scene-body"><div className="lw-atlas"><div className="lw-globe-wait" role="status">Loading the globe and the journeys…</div></div></div>

  const rooms = data.rooms.filter(room => room.id !== data.room.id)
  const roomFor = (slug: string) => rooms.find(room => room.linked_journey === slug)
  const inks = new Set<Ink>(data.journeys.flatMap(journey => journey.segments.map(segment => segment.proposed ? 'dotted' : segment.ink)))
  const chosen = data.journeys.find(journey => journey.slug === selected)
  const action = (journey: Journey): ReactNode => {
    const room = roomFor(journey.slug)
    if (room) return <button className="lw-primary" aria-label={`Enter the room for ${journey.title}`} onClick={() => void onNavigate(room.id)}>Enter the room</button>
    if (journey.kind !== 'candidate') return null
    if (canManageHome) return <button disabled={busy !== null} onClick={() => void openRoom(journey.slug, journey.title)}>{busy === journey.slug ? 'Opening…' : 'Open a room for this journey'}</button>
    return <p className="lw-note">No room yet. A house manager can open one.</p>
  }
  return <div className="longway-house scene-body">
    <div className="lw-atlas">
      <div className="lw-atlas-globe" ref={globe}>
        <div className="longway-chart"><Chart data={data} focus={null} selected={selected} myth={myth} onSelectJourney={setSelected} onSelectLeg={slug => setSelected(slug)} /></div>
        <div className="lw-globe-bar">
          <InkKey inks={inks} myth={myth} />
          <div className="lw-toggle">
            <label><input type="checkbox" checked={myth} aria-describedby="lw-myth-hint" onChange={e => setMyth(e.target.checked)} /> Without the mythology</label>
            <span id="lw-myth-hint" className="lw-hint">Only legs a checked source supports</span>
          </div>
        </div>
        {chosen ? <div className="lw-chosen" aria-label={`On the globe: ${chosen.title}`} role="group">
          <p className="lw-eyebrow">On the globe</p>
          <h3>{chosen.title}</h3>
          {meta(chosen) && <p className="lw-meta">{meta(chosen)}</p>}
          <div className="longway-actions">{action(chosen)}<button onClick={() => setSelected(null)}>Show every journey</button></div>
          {writeError && <p role="alert" className="lw-alert">{writeError}</p>}
        </div> : <p className="lw-hint lw-globe-tip">Tap a journey’s name on the globe, or pick one below, to see its route.</p>}
      </div>
      <div className="lw-atlas-list">
        <section aria-label="Your rooms" className="lw-section">
          <h2>Your rooms</h2>
          {rooms.length ? <ul className="lw-rooms">{rooms.map(room => {
            const title = room.linked_journey && data.journeys.find(journey => journey.slug === room.linked_journey)?.title
            return <li key={room.id}><button className="lw-room" onClick={() => void onNavigate(room.id)}>
              <span className="lw-room-name">{room.name}</span>
              {title && title !== room.name && <span className="lw-room-journey">{title}</span>}
              <span className="lw-room-go" aria-hidden="true">→</span>
            </button></li>
          })}</ul> : <p className="lw-note">No journey rooms yet. {canManageHome ? 'Open one from a journey below.' : 'A house manager opens them.'}</p>}
        </section>
        {canManageHome && <SeatRequests key={roomId} roomId={roomId} />}
        {writeError && !chosen && <p role="alert" className="lw-alert">{writeError}</p>}
        <section aria-label="Journeys" className="lw-section">
          <h2>Journeys{' '}<span className="lw-count">{data.journeys.length}</span></h2>
          {data.journeys.length === 0 && <p className="lw-note">The register has no journeys yet.</p>}
          {data.journeys.map(journey => <article key={journey.slug} className="longway-card lw-journey" data-selected={selected === journey.slug || undefined} aria-labelledby={`lw-j-${journey.slug}`}>
            <div className="lw-journey-head">
              <h3><button id={`lw-j-${journey.slug}`} className="lw-journey-title" aria-pressed={selected === journey.slug} onClick={() => show(journey.slug)}>{journey.title}</button></h3>
              <span className="lw-chip">{stage(journey.status)}</span>
            </div>
            {meta(journey) && <p className="lw-meta">{meta(journey)}</p>}
            {journey.segments.length > 0 && <JourneyStrip journey={journey} />}
            <p className="lw-pull">{journey.pull}</p>
            {feasibility(journey.feasibility) && <p className="lw-feasibility">{feasibility(journey.feasibility)}</p>}
            <div className="longway-actions">{action(journey)}</div>
          </article>)}
        </section>
      </div>
    </div>
  </div>
}
