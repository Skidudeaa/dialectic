import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../../lib/api'
import { useAppStore } from '../../stores/appStore'
import type { Message } from '../../types'
import type { ChartProjection, ChartProps } from './types'
import raw from './__fixtures__/chart.json'
import { chartProposal, proposal, question, run } from './__fixtures__/scout'
import { LongwayField } from './LongwayField'
import { LongwayBench } from './LongwayBench'
import { DispatchCard } from './DispatchCard'
import { LegCard, JourneyStrip } from './chart/Cards'
import { MessageBubble } from '../../components/chat/MessageBubble'

vi.mock('../../organ', () => ({ ORGAN: 'longway', IDENTITY: { name: 'The Long Way', participantName: 'Scout', signature: ')' } }))
vi.mock('./chart/Chart', () => ({ default: (props: ChartProps) => <button onClick={() => props.onSelectLeg('ogasawara', 0)}>Select Tokyo leg</button> }))
vi.mock('../../hooks/useMessageDecisions', () => ({ useMessageDecisions: () => ({ status: 'ready', decisions: {} }) }))

const chart = { ...raw, room: { id: 'room', linked_journey: 'ogasawara', is_home: false }, proposals: { ogasawara: [chartProposal] }, fixes_state: { stale: false } } as unknown as ChartProjection
const journey = { ...chart.journeys.find(j => j.slug === 'ogasawara')!, segments: chart.journeys.find(j => j.slug === 'ogasawara')!.segments.map((s, i) => ({ ...s, proposed: i === 0 })) }
let calls: { path: string; method: string; body?: Record<string, unknown> }[]
function serve(extra: (path: string, init?: RequestInit) => unknown = () => undefined) {
  vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
    const path = String(input), method = init?.method ?? 'GET'
    calls.push({ path, method, body: init?.body ? JSON.parse(String(init.body)) : undefined })
    const custom = extra(path, init)
    if (custom instanceof Response) return custom
    const result = custom ?? (path === '/users/me/rooms' ? [] : path.endsWith('/proposals') ? [proposal]
      : path.endsWith('/questions') ? [question] : path.endsWith('/scout/runs') ? [run]
      : path.endsWith('/scout') ? { run_id: run.id }
      : path.endsWith('/field') ? { marks: [{ id: 'field_mark:mark-1', relation: 'evidence_attachment', review: 'proposed', subjects: [{ entity: 'longway_evidence_proposals', id: proposal.id }] }] }
      : path.endsWith('/chart') ? { ...chart, journeys: [journey] } : {})
    return new Response(JSON.stringify(result), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }))
}
const writes = () => calls.filter(c => c.method === 'POST')
beforeEach(() => {
  calls = []; api.setAccessToken('jwt'); api.setToken('room-token')
  useAppStore.setState({ messages: [], currentRoom: { id: 'room', name: 'Journey', token: 'room-token', is_home: false }, currentThread: { id: 'thread', room_id: 'room', parent_thread_id: null, title: 'Root', message_count: 0 } })
})
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

describe('the Scout editors’ desk', () => {
  it('puts the passage first and shows scope, structured fields, question, publisher, and the source gate', async () => {
    serve()
    render(<LongwayField roomId="room" canManageHome={false} />)
    const card = await screen.findByRole('article', { name: proposal.claim })
    expect(card.firstElementChild?.tagName).toBe('BLOCKQUOTE')
    for (const text of [proposal.support!, proposal.scope, '2027-10-01 to 2027-10-31', 'outbound', 'any', 'Maru', 'Tokyo (Takeshiba) to Chichijima', `answers: ${proposal.question_text}`]) expect(within(card).getByText(text)).toBeVisible()
    expect(card).toHaveTextContent(proposal.publisher!)
    const confirm = within(card).getByRole('button', { name: 'Confirm' })
    expect(confirm).toBeDisabled(); expect(confirm).toHaveAccessibleDescription('Open the page first')
    fireEvent.click(confirm); expect(writes()).toHaveLength(0)
    fireEvent.click(within(card).getByRole('link', { name: 'Open page' }))
    expect(confirm).toBeEnabled(); fireEvent.click(confirm)
    await waitFor(() => expect(writes()).toEqual([{ path: '/rooms/room/field/marks/mark-1/review', method: 'POST', body: { action: 'confirm' } }]))
  })
  it('keeps a load-bearing claim gated after opening its page', async () => {
    serve(path => path.endsWith('/proposals') ? [{ ...proposal, requires_counter: true }] : undefined)
    render(<LongwayField roomId="room" canManageHome={false} />)
    fireEvent.click(await screen.findByRole('link', { name: 'Open page' }))
    const confirm = screen.getByRole('button', { name: 'Confirm' })
    expect(confirm).toBeDisabled(); expect(confirm).toHaveAccessibleDescription('Load-bearing claim: no contrary search yet')
    fireEvent.click(confirm); expect(writes()).toHaveLength(0)
  })
  it.each(['contest', 'correct'] as const)('posts %s through the bare Field mark id with the entered claim/note', async action => {
    serve()
    render(<LongwayField roomId="room" canManageHome={false} />)
    fireEvent.click(await screen.findByRole('button', { name: action === 'contest' ? 'Contest' : 'Correct' }))
    const save = screen.getByRole('button', { name: `Save ${action}` })
    expect(save).toBeDisabled()
    fireEvent.change(screen.getByRole('textbox', { name: action === 'contest' ? 'Contest note' : 'Better claim' }), { target: { value: '  The service is suspended.  ' } })
    fireEvent.click(save)
    await waitFor(() => expect(writes()).toHaveLength(1))
    expect(writes()[0]).toMatchObject({ path: '/rooms/room/field/marks/mark-1/review', body: { action, note: 'The service is suspended.' } })
    if (action === 'correct') expect(writes()[0].body).toMatchObject({ replacement: { title: 'The service is suspended.', payload: { claim: 'The service is suspended.', url: proposal.url, scope: proposal.scope } } })
  })
  it('pales only old unreviewed rows and shows written provenance without actions', async () => {
    serve(path => path.endsWith('/proposals') ? [
      { ...proposal, created_at: new Date(Date.now() - 15 * 86400000).toISOString() },
      { ...proposal, id: 'reviewed', claim: 'Reviewed claim', review: 'contested', created_at: '2020-01-01' },
      { ...proposal, id: 'written', claim: 'Written claim', written_sid: 'S31', written_commit: 'abc12345678', created_at: '2020-01-01' },
    ] : undefined)
    render(<LongwayField roomId="room" canManageHome={false} />)
    expect(await screen.findByRole('article', { name: proposal.claim })).toHaveClass('paled')
    expect(screen.getByRole('article', { name: 'Reviewed claim' })).not.toHaveClass('paled')
    const written = screen.getByRole('article', { name: 'Written claim' })
    expect(written).not.toHaveClass('paled'); expect(written).toHaveTextContent('Written as S31, commit abc1234')
    expect(within(written).queryByRole('button')).not.toBeInTheDocument()
  })
  it('lists open questions with sources and submits a human question, clearing only on success', async () => {
    let fail = true
    serve((path, init) => path.endsWith('/questions') ? init?.method === 'POST'
      ? fail ? new Response(JSON.stringify({ detail: 'Try again' }), { status: 503 }) : { ...question, text: 'How much?' }
      : ['human', 'reaction', 'dossier'].map((source, i) => ({ ...question, id: `${i}`, text: `Question from ${source}`, source })) : undefined)
    render(<LongwayField roomId="room" canManageHome={false} />)
    for (const source of ['human', 'reaction', 'dossier']) expect(await screen.findByText(source)).toBeVisible()
    const input = screen.getByRole('textbox', { name: 'Ask the Scout to find out' })
    fireEvent.change(input, { target: { value: 'How much?' } }); fireEvent.click(screen.getByRole('button', { name: 'Ask the Scout' }))
    expect(await screen.findByText('Try again')).toBeVisible(); expect(input).toHaveValue('How much?')
    fail = false; fireEvent.click(screen.getByRole('button', { name: 'Ask the Scout' }))
    await waitFor(() => expect(input).toHaveValue(''))
    expect(writes().at(-1)).toEqual({ path: '/rooms/room/longway/questions', method: 'POST', body: { text: 'How much?', source: 'human' } })
    expect(screen.queryByRole('button', { name: 'Scout this' })).not.toBeInTheDocument()
  })
  it('derives manager access from the existing rooms API', async () => {
    serve(path => path === '/users/me/rooms' ? [{ is_home: true, can_manage_home: true }] : undefined)
    render(<LongwayField roomId="room" />)
    expect(await screen.findByRole('button', { name: 'Scout this' })).toBeEnabled()
    expect(screen.getByText('Scout read 12 pages, filed 5 proposals, 2 contrary findings')).toBeVisible()
  })
  it('starts Scout this, polls every ten seconds through running to the receipt, refreshes proposals and stops on unmount', async () => {
    vi.useFakeTimers()
    let started = false, done = false
    serve((path, init) => {
      if (path.endsWith('/scout') && init?.method === 'POST') { started = true; return { run_id: run.id } }
      if (path.endsWith('/scout/runs')) return started ? [{ ...run, status: done ? 'done' : 'running', finished_at: done ? run.finished_at : null }] : []
    })
    const view = render(<LongwayField roomId="room" canManageHome />)
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    fireEvent.click(screen.getByRole('button', { name: 'Scout this' }))
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    expect(writes()).toContainEqual({ path: '/rooms/room/longway/scout', method: 'POST', body: {} })
    expect(screen.getByText('Scout running…')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Scout this' })).toBeDisabled()
    const polls = () => calls.filter(c => c.path.endsWith('/scout/runs')).length
    const before = polls()
    await act(async () => { await vi.advanceTimersByTimeAsync(9999) }); expect(polls()).toBe(before)
    await act(async () => { await vi.advanceTimersByTimeAsync(1) }); expect(polls()).toBe(before + 1)
    const proposalsBefore = calls.filter(c => c.path.endsWith('/proposals')).length
    done = true
    await act(async () => { await vi.advanceTimersByTimeAsync(10000) })
    expect(screen.queryByText('Scout running…')).not.toBeInTheDocument()
    expect(screen.getByText('Scout read 12 pages, filed 5 proposals, 2 contrary findings')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Scout this' })).toBeEnabled()
    expect(calls.filter(c => c.path.endsWith('/proposals')).length).toBeGreaterThan(proposalsBefore)
    view.unmount(); const count = calls.length
    await act(async () => { await vi.advanceTimersByTimeAsync(20000) }); expect(calls).toHaveLength(count)
  })
})

describe('the Scout in the chart and Record', () => {
  it('marks proposed segments in the strip and Bench list, and mounts the real proposal card on leg selection', async () => {
    serve()
    const strip = render(<JourneyStrip journey={journey} />)
    expect(screen.getByText('proposed')).toBeVisible()
    expect(screen.getByRole('img')).toHaveAccessibleName(/proposed/)
    expect(strip.container.querySelector('.ink-dotted')).not.toBeNull(); strip.unmount()
    render(<LongwayBench roomId="room" />)
    fireEvent.click(await screen.findByRole('button', { name: 'Select Tokyo leg' }))
    expect(screen.getAllByText('proposed').length).toBeGreaterThan(1)
    expect(screen.getByRole('article', { name: proposal.claim })).toHaveTextContent(proposal.support!)
  })
  it.each(['confirm', 'contest'] as const)('reviews a reverse-direction leg proposal with %s via the same Field path', async action => {
    serve()
    render(<LegCard journey={journey} index={0} sources={{}} roomId="room" proposals={[
      { ...chartProposal, leg_from: chartProposal.leg_to, leg_to: chartProposal.leg_from },
      { ...chartProposal, id: 'other', claim: 'Unrelated leg', leg_from: 'Elsewhere' },
      { ...chartProposal, id: 'contested', claim: 'Contested claim', review: 'contested' },
    ]} />)
    expect(screen.queryByText('Unrelated leg')).not.toBeInTheDocument(); expect(screen.queryByText('Contested claim')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Confirm' })).toBeDisabled()
    expect(screen.getByText('Open the page first')).toBeVisible()
    fireEvent.click(screen.getByRole('link', { name: 'Open page' }))
    fireEvent.click(screen.getByRole('button', { name: action === 'confirm' ? 'Confirm' : 'Contest' }))
    if (action === 'contest') {
      fireEvent.change(screen.getByRole('textbox', { name: 'Contest note' }), { target: { value: 'This is last year’s timetable.' } })
      fireEvent.click(screen.getByRole('button', { name: 'Save contest' }))
    }
    await waitFor(() => expect(writes()).toHaveLength(1))
    expect(writes()[0]).toMatchObject({ path: '/rooms/room/field/marks/mark-1/review', body: { action } })
  })
  it('retains the contrary-search gate in the LegCard', () => {
    serve()
    render(<LegCard journey={journey} index={0} sources={{}} roomId="room" proposals={[{ ...chartProposal, requires_counter: true }]} />)
    fireEvent.click(screen.getByRole('link', { name: 'Open page' }))
    expect(screen.getByRole('button', { name: 'Confirm' })).toBeDisabled()
    expect(screen.getByText('Load-bearing claim: no contrary search yet')).toBeVisible()
    expect(writes()).toHaveLength(0)
  })
  it('keeps the dispatch reaction and posts exactly its last paragraph; un-reacting posts nothing', async () => {
    serve()
    const toggle = vi.fn(), content = 'The crossing has new evidence.\n\nCan we take the boat\nin October?\n\nReact with 👍 I’d go · 🚫 Not for me · ❓ Tell me more'
    const props = { roomId: 'room', messageId: 'dispatch-1', content, dispatch: { journey: 'ogasawara', week_of: '2026-10-25' }, currentUserId: 'me', onToggleReaction: toggle }
    const view = render(<DispatchCard {...props} reactions={[]} />)
    fireEvent.click(screen.getByRole('button', { name: '❓ Tell me more' }))
    await waitFor(() => expect(screen.getByRole('button', { name: '❓ Tell me more' })).toBeEnabled())
    expect(toggle).toHaveBeenLastCalledWith('dispatch-1', '❓', false)
    expect(writes()).toEqual([{ path: '/rooms/room/longway/questions', method: 'POST', body: { source: 'reaction', text: 'Can we take the boat\nin October?', source_message_id: 'dispatch-1', journey: 'ogasawara' } }])
    view.rerender(<DispatchCard {...props} reactions={[{ emoji: '❓', user_ids: ['me'], user_names: ['Private reader'] }]} />)
    fireEvent.click(screen.getByRole('button', { name: '❓ Tell me more' }))
    expect(toggle).toHaveBeenLastCalledWith('dispatch-1', '❓', true); expect(writes()).toHaveLength(1)
    expect(document.body.textContent).not.toContain('Private reader')
  })
  it('renders the participant run metadata as a receipt linked to this room’s Field, but leaves human prose alone', () => {
    const message = { id: 'receipt', thread_id: 'thread', sequence: 1, created_at: '2026-10-28T12:00:00Z', speaker_type: 'llm_primary', message_type: 'text', user_id: null, content: 'Verbose original message', metadata: { longway_scout_run: { run_id: run.id, journey: run.journey, pages_read: 12, proposals: 5, counter_proposals: 2 } } } as unknown as Message
    const view = render(<MessageBubble message={message} isSelf={false} authorName="Scout" />)
    expect(screen.getByText(/Scout read 12 pages, filed 5 proposals, 2 contrary findings/)).toBeVisible()
    expect(screen.getByRole('link', { name: 'Open Field' })).toHaveAttribute('href', '/?room=room&scene=field')
    expect(screen.queryByText('Verbose original message')).not.toBeInTheDocument()
    view.rerender(<MessageBubble message={{ ...message, speaker_type: 'human' }} isSelf authorName="Reader" />)
    expect(screen.getByText('Verbose original message')).toBeVisible()
    expect(screen.queryByRole('link', { name: 'Open Field' })).not.toBeInTheDocument()
  })
})
