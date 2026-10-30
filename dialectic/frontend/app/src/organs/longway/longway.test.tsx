import { act, fireEvent, render, screen, waitFor, cleanup, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ChartProps, ChartProjection, EvidenceProposal } from './types'
import type { LegCardProps } from './chartSlot'
import raw from './__fixtures__/chart.json'
import banda from './__fixtures__/banda-library.json'
import { dispatchesFirst } from './record'
import type { Message } from '../../types'
import { api } from '../../lib/api'
import { useAppStore } from '../../stores/appStore'
import { LongwayBench } from './LongwayBench'
import { LongwayHouse, monthRuns } from './LongwayHouse'
import { LongwayField } from './LongwayField'
import { LongwayLibrary } from './LongwayLibrary'
import { LongwayLedger } from './LongwayLedger'
import { DispatchCard } from './DispatchCard'

vi.mock('./chart/Chart', () => ({
  default: (props: ChartProps) => <div data-testid="chart" data-focus={props.focus} data-myth={String(props.myth)}><button onClick={() => props.onSelectLeg('ogasawara', 0)}>Select Tokyo leg</button></div>,
  LegCard: ({ journey, index, sources }: LegCardProps) => <section aria-label="Leg card">{journey.segments[index].basis.map(id => <p key={id}>{id} {sources[id].claim} {sources[id].status}<a href={sources[id].url!}>{sources[id].publisher}</a></p>)}</section>,
  SeasonStrip: () => <div>Season strip</div>,
}))

function projection(home = false): ChartProjection {
  return { ...raw, fetched_at: '2026-10-28T06:10:00Z', room: { id: 'room', linked_journey: home ? null : 'ogasawara', is_home: home }, rooms: [{ id: 'existing', name: 'Banda room', linked_journey: 'banda-islands' }], vehicles: raw.vehicles.map(v => ({ ...v, fix: null, heard: false })), fixes_state: { written: null, stale: false, why: null } } as unknown as ChartProjection
}
const proposed: EvidenceProposal = { id: 'p1', room_id: 'room', candidate: 'ogasawara', claim: 'Published crossing', url: 'https://example.org/timetable', scope: 'Timetable only', support: 'The published passage', publisher: 'Operator', published_at: null, created_at: '2026-10-28', proposed_by: 'human', proposer_user_id: 'me', source_message_id: null, review: 'proposed', written_sid: null, written_at: null, written_commit: null }
let calls: { path: string; init?: RequestInit; body?: Record<string, unknown> }[]
function serve(extra: (path: string, init?: RequestInit) => unknown = () => undefined, home = false) {
  vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
    const path = String(input)
    calls.push({ path, init, body: init?.body ? JSON.parse(String(init.body)) : undefined })
    const custom = extra(path, init)
    if (custom instanceof Response) return custom
    if (custom === undefined && path.endsWith('/invite-requests')) return new Response(JSON.stringify({ mail_configured: true, requests: [] }))
    const result = custom ?? (path.endsWith('/chart') ? projection(home) : path.endsWith('/proposals') ? [proposed] : path.endsWith('/field/marks') ? (init?.method === 'POST' ? { id: 'mark1' } : { marks: [] }) : path.endsWith('/questions') || path.endsWith('/scout/runs') || path === '/users/me/rooms' ? [] : {})
    return new Response(JSON.stringify(result), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }))
}
beforeEach(() => {
  calls = []
  api.setAccessToken('jwt'); api.setToken('room-token')
  useAppStore.setState({ messages: [], currentRoom: { id: 'room', name: 'Journey', token: 'room-token', is_home: false }, currentThread: { id: 'thread', room_id: 'room', parent_thread_id: null, title: 'Root', message_count: 0 } })
})
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.unstubAllEnvs() })

describe('Long Way connected scenes', () => {
  it('selects room and Home scenes while trading retains its scene list', async () => {
    vi.stubEnv('VITE_ORGAN', 'longway'); vi.resetModules()
    const route = await import('../../lib/workspaceRoute')
    expect(route.scenesForDestination({ is_home: false }, { parent_thread_id: null })).toEqual(['bench', 'record', 'library', 'field', 'ledger'])
    expect(route.scenesForDestination({ is_home: true }, { parent_thread_id: null })).toEqual(['house', 'record'])
    expect(route.resolveWorkspaceScene({ is_home: false }, { parent_thread_id: null }, 'surface')).toBe('bench')
    const { SceneSwitcher } = await import('../../components/workspace/SceneSwitcher')
    const switcher = render(<SceneSwitcher scene="record" scenes={route.scenesForDestination({ is_home: false }, { parent_thread_id: null })} onSelect={vi.fn()} />)
    expect(screen.getAllByRole('button').map(button => button.textContent?.replace(/^[^A-Za-z]+/, ''))).toEqual(['Chart', 'Record', 'Library', 'Field', 'Ledger'])
    switcher.unmount()
    const organ = await import('../../organ')
    expect(organ.IDENTITY).toMatchObject({ name: 'The Long Way', participantName: 'Scout', signature: ')' })
    vi.stubEnv('VITE_ORGAN', 'trading'); vi.resetModules()
    const trading = await import('../../lib/workspaceRoute')
    expect(trading.scenesForDestination({ is_home: false }, { parent_thread_id: null })).toEqual(['surface', 'record', 'bench', 'field', 'atlas', 'library', 'ledger'])
  })
  it('fetches the room chart, selects S1, flips myth and sends an editable anchored discussion', async () => {
    serve()
    const send = vi.fn(() => true); useAppStore.setState({ wsSend: send })
    render(<LongwayBench roomId="room" />)
    const chart = await screen.findByTestId('chart')
    expect(chart).toHaveAttribute('data-focus', 'ogasawara')
    expect(calls[0].path).toBe('/rooms/room/longway/chart')
    expect(calls[0].init?.headers).toMatchObject({ Authorization: 'Bearer jwt', 'X-Room-Token': 'room-token' })
    fireEvent.click(screen.getByRole('checkbox', { name: 'Without the mythology' }))
    expect(chart).toHaveAttribute('data-myth', 'true')
    fireEvent.click(screen.getByText('Select Tokyo leg'))
    expect(await screen.findByRole('article', { name: 'Tokyo (Takeshiba) to Chichijima' })).toHaveTextContent(raw.sources.ogasawara.S1.claim)
    expect(screen.getAllByRole('link', { name: 'Source' })[0]).toHaveAttribute('href', raw.sources.ogasawara.S1.url)
    fireEvent.click(screen.getByText('Discuss this leg'))
    const draft = screen.getByRole('textbox', { name: 'About this leg' })
    expect(draft).toHaveValue('About Tokyo (Takeshiba) to Chichijima:')
    fireEvent.change(draft, { target: { value: 'About Tokyo (Takeshiba) to Chichijima: can we stay longer?' } })
    fireEvent.click(screen.getByText('Send to Record'))
    expect(send).toHaveBeenCalledWith('send_message', expect.objectContaining({ thread_id: 'thread', metadata: { longway_anchor: { journey: 'ogasawara', leg: 0 } }, content: expect.stringContaining('can we stay longer?') }))
  })
  it('refreshes on a dispatch and does not reuse another room response', async () => {
    serve(); const view = render(<LongwayBench roomId="room" />)
    await screen.findByTestId('chart')
    await act(async () => { useAppStore.setState({ messages: [{ id: 'dispatch', metadata: { longway_dispatch: { journey: 'ogasawara', week_of: '2026-10-28' } } }] as never }) })
    await waitFor(() => expect(calls.filter(c => c.path.endsWith('/chart'))).toHaveLength(2))
    view.rerender(<LongwayBench roomId="other" />)
    await waitFor(() => expect(calls.some(c => c.path === '/rooms/other/longway/chart')).toBe(true))
  })
  it('opens a journey room using its returned token before navigation', async () => {
    serve(path => path === '/rooms' ? { id: 'new-room', token: 'new-token' } : undefined, true)
    const navigate = vi.fn()
    render(<LongwayHouse roomId="home" canManageHome onNavigate={navigate} />)
    await screen.findByText('Your rooms')
    expect(screen.getByText('Banda room')).toBeVisible()
    const candidate = screen.getByRole('button', { name: projection().journeys.find(j => j.slug === 'ogasawara')!.title }).closest('article')!
    const button = within(candidate).getByRole('button', { name: 'Open a room for this journey' })
    fireEvent.click(button)
    await waitFor(() => expect(navigate).toHaveBeenCalledWith('new-room'))
    const writes = calls.filter(c => c.init?.method === 'POST')
    expect(writes.map(c => c.path)).toEqual(['/rooms', '/rooms/new-room/longway/bind'])
    expect(writes[1].init?.headers).toMatchObject({ 'X-Room-Token': 'new-token' })
    expect(writes[1].body).toEqual({ slug: 'ogasawara' })
    expect(api.getToken()).toBe('room-token')
  })
  it('names seasons as month runs, joining a run across the new year', () => {
    expect(monthRuns([9, 10, 11, 12])).toBe('Sep–Dec')
    expect(monthRuns([12, 1, 2, 11])).toBe('Nov–Feb')
    expect(monthRuns([1, 3, 4])).toBe('Jan, Mar–Apr')
    expect(monthRuns([6])).toBe('Jun')
    expect(monthRuns([])).toBe('')
  })
  it('lists only journey rooms, not the house itself, and shows the picked journey with a way back', async () => {
    serve(path => path.endsWith('/chart') ? { ...projection(true), rooms: [{ id: 'room', name: 'The Long Way', linked_journey: null }, { id: 'existing', name: 'Banda room', linked_journey: 'banda-islands' }] } : undefined, true)
    render(<LongwayHouse roomId="home" canManageHome={false} onNavigate={vi.fn()} />)
    const rooms = await screen.findByRole('region', { name: 'Your rooms' })
    expect(within(rooms).getAllByRole('button').map(b => b.textContent)).toEqual([expect.stringContaining('Banda room')])
    const title = projection().journeys.find(j => j.slug === 'ogasawara')!.title
    fireEvent.click(screen.getByRole('button', { name: title }))
    const chosen = screen.getByRole('group', { name: `On the globe: ${title}` })
    expect(within(chosen).getByText('No room yet. A house manager can open one.')).toBeVisible()
    fireEvent.click(within(chosen).getByRole('button', { name: 'Show every journey' }))
    expect(screen.queryByRole('group', { name: `On the globe: ${title}` })).not.toBeInTheDocument()
  })
  it('does not offer room creation to ordinary members', async () => {
    serve(undefined, true)
    render(<LongwayHouse roomId="home" canManageHome={false} onNavigate={vi.fn()} />)
    await screen.findByText('Your rooms')
    expect(screen.queryByText('Open a room for this journey')).not.toBeInTheDocument()
  })
  it.each(['confirm', 'contest', 'correct'] as const)('reviews a proposal through the shared Field path: %s', async action => {
    serve()
    render(<LongwayField roomId="room" />)
    if (action === 'confirm') fireEvent.click(await screen.findByRole('link', { name: 'Open page' }))
    fireEvent.click(await screen.findByRole('button', { name: action[0].toUpperCase() + action.slice(1) }))
    if (action !== 'confirm') {
      fireEvent.change(screen.getByRole('textbox', { name: action === 'contest' ? 'Contest note' : 'Better claim' }), { target: { value: 'The corrected page claim' } })
      fireEvent.click(screen.getByRole('button', { name: `Save ${action}` }))
    }
    await waitFor(() => expect(calls.some(c => c.path.endsWith('/mark1/review'))).toBe(true))
    expect(calls.find(c => c.path.endsWith('/field/marks') && c.init?.method === 'POST')?.body?.subjects).toEqual([{ entity: 'longway_evidence_proposals', id: 'p1' }])
    expect(calls.find(c => c.path.endsWith('/mark1/review'))?.body).toMatchObject({ action, ...(action === 'correct' ? { replacement: { title: 'The corrected page claim' } } : {}) })
  })
  it('shows written evidence provenance', async () => {
    serve(path => path.endsWith('/proposals') ? [{ ...proposed, written_sid: 'S31', written_commit: 'abc12345678' }] : undefined)
    render(<LongwayField roomId="room" />)
    expect(await screen.findByText('Written as S31, commit abc1234')).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Confirm' })).not.toBeInTheDocument()
  })
  it('renders every row of the current Banda dossier without a fixed evidence count', async () => {
    const chart = projection(); chart.room.linked_journey = 'banda-islands'
    const journey = chart.journeys.find(j => j.slug === 'banda-islands')!
    serve(path => path.endsWith('/chart') ? chart : path.includes('/journey/') ? { ...journey, ...banda, evidence: banda.evidence.map(row => ({ ...row, faded: false })), vehicles: [] } : undefined)
    const view = render(<LongwayLibrary roomId="room" />)
    await screen.findByRole('region', { name: 'Evidence ledger' })
    expect(view.container.querySelectorAll('[aria-label="Evidence ledger"] article')).toHaveLength(banda.evidence.length)
    expect(screen.getByText(`${banda.evidence.at(-1)!.id} · ${banda.evidence.at(-1)!.claim}`)).toBeVisible()
  })
  it('renders sanitized dossier, dated faded evidence, vehicle silence and consent permissions', async () => {
    const journey = projection().journeys.find(j => j.slug === 'ogasawara')!
    serve(path => path.includes('/journey/') ? { ...journey, dossier: '# The crossing\n<script>bad()</script>', evidence: [{ id: 'S1', ...raw.sources.ogasawara.S1, faded: true }], vehicles: [{ name: 'Maru', fix: null }], plan: { undecided: 'Who can travel?', established: '' } } : path.endsWith('/confirmations') ? [] : undefined)
    const view = render(<LongwayLibrary roomId="room" />)
    expect(await screen.findByText('The crossing')).toBeVisible()
    expect(screen.getByText('verified · checked 9 Oct 2026')).toBeVisible()
    expect(screen.getByText('past its recheck rule').closest('article')).toHaveClass('is-faded')
    expect(screen.getByText('never heard')).toBeVisible()
    expect(view.container.querySelector('script')).toBeNull()
    view.unmount()
    render(<LongwayLedger roomId="room" canManageHome={false} />)
    expect(await screen.findByText('Nothing confirmed yet.')).toBeVisible()
    expect(await screen.findByText('Who can travel?')).toBeVisible()
    expect(screen.queryByText('Record a confirmation')).not.toBeInTheDocument()
  })
})

describe('House seat requests', () => {
  const request = { id: 'ask-1', name: 'Ada', email: 'ada@example.com', note: 'I know Jo.', created_at: '2026-10-28T12:00:00Z', decision: null, decided_at: null, notified_at: null, invited_email_at: null }
  const invite = { id: request.id, name: request.name, email: request.email, code: '483921', emailed: false, mail_error: null, expires_at: '2026-11-04T12:00:00Z' }

  it('loads manager requests with credentials, invites, and retains a fresh code on Invite again', async () => {
    let code = '483921'
    serve(path => path.endsWith('/invite-requests') ? { mail_configured: false, requests: [request] }
      : path.endsWith('/invite') ? { ...invite, code } : undefined, true)
    render(<LongwayHouse roomId="home" canManageHome onNavigate={vi.fn()} />)
    const section = await screen.findByRole('region', { name: 'Asking for a seat' })
    expect(within(section).getByRole('heading', { level: 2 })).toHaveTextContent('Asking for a seat')
    expect(await within(section).findByText('ada@example.com')).toBeVisible()
    expect(within(section).getByText('I know Jo.')).toBeVisible()
    expect(within(section).getByText('asked 28 Oct')).toBeVisible()
    expect(within(section).getByText('Email to you is not set up yet; requests wait here.')).toBeVisible()
    expect(calls.find(call => call.path === '/rooms/home/longway/invite-requests')?.init?.headers).toMatchObject({ Authorization: 'Bearer jwt', 'X-Room-Token': 'room-token' })
    fireEvent.click(within(section).getByRole('button', { name: 'Invite' }))
    expect(await within(section).findByRole('status')).toHaveTextContent('Invited. Email is off; give ada@example.com this code: 483921 (works 7 days)')
    expect(section.querySelector('code')?.textContent).toBe('483921')
    expect(within(section).getByRole('article')).toHaveClass('is-decided')
    code = '123456'
    fireEvent.click(within(section).getByRole('button', { name: 'Invite again' }))
    await waitFor(() => expect(within(section).getByRole('status')).toHaveTextContent('this code: 123456'))
    expect(screen.queryByText('483921')).not.toBeInTheDocument()
    const writes = calls.filter(call => call.init?.method === 'POST')
    expect(writes.map(call => call.path)).toEqual(['/rooms/home/longway/invite-requests/ask-1/invite', '/rooms/home/longway/invite-requests/ask-1/invite'])
    expect(writes[0].init?.headers).toMatchObject({ Authorization: 'Bearer jwt', 'X-Room-Token': 'room-token' })
  })

  it.each([
    [true, null, 'Invited. The code went to ada@example.com.'],
    [false, 'Mail provider unavailable', 'Invited, but the email failed: Mail provider unavailable. Give ada@example.com this code: 483921'],
  ])('reports email delivery: emailed=%s, error=%s', async (emailed, mail_error, message) => {
    serve(path => path.endsWith('/invite-requests') ? { mail_configured: true, requests: [request] }
      : path.endsWith('/invite') ? { ...invite, emailed, mail_error } : undefined, true)
    render(<LongwayHouse roomId="home" canManageHome onNavigate={vi.fn()} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Invite' }))
    expect(await screen.findByRole('status')).toHaveTextContent(message!)
    expect(screen.queryByText('Email to you is not set up yet; requests wait here.')).not.toBeInTheDocument()
  })

  it('keeps open requests above decisions and moves a declined request into the decided list', async () => {
    serve(path => path.endsWith('/invite-requests') ? { mail_configured: true, requests: [
      request,
      { ...request, id: 'ask-2', name: 'Jo', created_at: '2026-10-27T12:00:00Z' },
      { ...request, id: 'ask-3', name: 'Sam', decision: 'invited', decided_at: '2026-10-28T12:00:00Z' },
      { ...request, id: 'ask-4', name: 'Lee', decision: 'declined', decided_at: '2026-10-28T12:00:00Z' },
    ] } : path.endsWith('/decline') ? { id: request.id, decision: 'declined' } : undefined, true)
    render(<LongwayHouse roomId="home" canManageHome onNavigate={vi.fn()} />)
    const ada = await screen.findByRole('article', { name: 'Request from Ada' })
    expect(screen.getByText('Sam · invited 28 Oct')).toBeVisible()
    expect(screen.getByText('Lee · declined 28 Oct')).toBeVisible()
    fireEvent.click(within(ada).getByRole('button', { name: 'Decline' }))
    await waitFor(() => expect(ada).toHaveClass('is-decided'))
    expect(ada).toHaveTextContent('Ada · declined')
    expect(within(ada).queryByRole('button')).not.toBeInTheDocument()
    const section = screen.getByRole('region', { name: 'Asking for a seat' })
    expect(within(section).getAllByRole('article')[0]).toHaveAccessibleName('Request from Jo')
    expect(calls.find(call => call.path.endsWith('/ask-1/decline'))?.init?.method).toBe('POST')
  })

  it('shows the empty state', async () => {
    serve(undefined, true)
    render(<LongwayHouse roomId="home" canManageHome onNavigate={vi.fn()} />)
    expect(await screen.findByText('Nobody is asking right now.')).toBeVisible()
  })

  it('does not render or fetch requests for a non-manager', async () => {
    serve(undefined, true)
    render(<LongwayHouse roomId="home" canManageHome={false} onNavigate={vi.fn()} />)
    await screen.findByRole('region', { name: 'Your rooms' })
    expect(screen.queryByRole('region', { name: 'Asking for a seat' })).not.toBeInTheDocument()
    expect(calls.some(call => call.path.includes('/invite-requests'))).toBe(false)
  })

  it('offers retry after a load failure and leaves failed decisions open', async () => {
    let failing = true
    serve(path => path.endsWith('/invite-requests') ? failing
      ? new Response(JSON.stringify({ detail: 'Could not load requests' }), { status: 503 })
      : { mail_configured: true, requests: [request] }
      : path.endsWith('/invite') ? new Response(JSON.stringify({ detail: 'Could not invite' }), { status: 503 }) : undefined, true)
    render(<LongwayHouse roomId="home" canManageHome onNavigate={vi.fn()} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load requests')
    failing = false
    fireEvent.click(screen.getByRole('button', { name: 'Retry requests' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Invite' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not invite')
    expect(screen.getByRole('article', { name: 'Request from Ada' })).not.toHaveClass('is-decided')
    expect(screen.getByRole('button', { name: 'Invite' })).toBeEnabled()
  })
})

describe('dispatch privacy', () => {
  it('puts each dispatch above the conversation of its own day', () => {
    const message = (id: string, day: string, dispatch = false) => ({ id, created_at: day, speaker_type: dispatch ? 'llm_primary' : 'human', metadata: dispatch ? { longway_dispatch: { week_of: '2026-10-25', journey: null } } : {} }) as unknown as Message
    expect(dispatchesFirst([message('first', '2026-10-24T12:00:00Z'), message('banter', '2026-10-25T12:00:00Z'), message('dispatch', '2026-10-25T13:00:00Z', true), message('reply', '2026-10-25T14:00:00Z')]).map(m => m.id)).toEqual(['first', 'dispatch', 'banter', 'reply'])
  })
  it('offers three reactions, toggles only the viewer state, and exposes no counts or names', async () => {
    serve()
    const toggle = vi.fn()
    render(<DispatchCard roomId="room" messageId="dispatch" content="Nothing moved this week" dispatch={{ journey: 'ogasawara', week_of: '2026-10-25' }} currentUserId="me" reactions={[{ emoji: '👍', user_ids: ['me', 'other'], user_names: ['Private viewer', 'Other member'] }]} onToggleReaction={toggle} />)
    const buttons = screen.getAllByRole('button')
    expect(buttons).toHaveLength(3)
    expect(buttons[0]).toHaveAttribute('aria-pressed', 'true')
    buttons.forEach(button => fireEvent.click(button))
    await waitFor(() => expect(calls.some(c => c.path.endsWith('/questions'))).toBe(true))
    expect(toggle.mock.calls).toEqual([['dispatch', '👍', true], ['dispatch', '🚫', false], ['dispatch', '❓', false]])
    expect(document.body.textContent).not.toMatch(/Private viewer|Other member/)
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  })
})
