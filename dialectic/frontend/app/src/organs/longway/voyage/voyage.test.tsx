import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { LongwayHouse } from '../LongwayHouse'
import { LongwayBench } from '../LongwayBench'
import { LongwayLibrary } from '../LongwayLibrary'
import { api } from '../../../lib/api'
import raw from '../__fixtures__/chart.json'
import type { JourneyDocument } from './voyage'

vi.mock('../chartSlot', () => ({ default: () => <div>Globe</div> }))
const journey = { ...raw.journeys[0], slug: 'nile', title: 'The Nile', voyage: true }
const stop = { id: 'aswan', name: 'Aswan', kicker: 'First light', moment: { text: 'Look up', cite: ['S104'] }, photos: ['sky'] }
const voyage = { title: 'The Nile', subtitle: '', seed: 3, start: 'aswan', stations: [stop, { id: 'komombo', name: 'Kom Ombo' }],
  acts: [{ id: 'upper', title: 'Upper river' }], pulse: {}, fill: {}, dams: [], timeline: [], photos: {} }
const docs: Record<string, JourneyDocument> = {
  voyage: { name: 'voyage', slug: 'nile', value: voyage, format: 'json', writable: true, why: null, protected: [] },
  record: { name: 'record', slug: 'nile', value: { title: 'Nile', status: 'candidate', reviewed_by: ['Scout'] }, format: 'json', writable: true, why: null, protected: ['status', 'reviewed_by'] },
  dossier: { name: 'dossier', slug: 'nile', value: '# The Nile', format: 'text', writable: true, why: null, protected: [] },
}
const refusal = 'voyage.json cites S999, missing from candidates/nile/evidence.jsonl'
const changed = ['stations/aswan/kicker']
const html = '<!doctype html><html><title>Nile</title><body><p>First light</p></body></html>'
const button = (name: string) => screen.getByRole('button', { name })
function serve({ refuse = false, locked = false, hasVoyage = true } = {}) {
  const calls: { path: string; init: RequestInit; body?: unknown }[] = []
  let saved = false
  vi.stubGlobal('fetch', vi.fn(async (path: string, init: RequestInit = {}) => {
    calls.push({ path, init, body: init.body && JSON.parse(String(init.body)) })
    const resource = path.split('/longway/')[1]
    if (resource === 'chart') return Response.json({ ...raw, journeys: [{ ...journey, voyage: hasVoyage }, raw.journeys[1]], rooms: [],
      room: { id: 'room', linked_journey: 'nile', is_home: false }, fixes_state: { stale: false }, vehicles: [] })
    if (resource === 'riding') return Response.json({ rides: [] })
    if (resource === 'journey/nile') return Response.json({ ...journey, voyage: undefined, dossier: saved ? '# Saved dossier' : '# The Nile', evidence: [], vehicles: [] })
    if (resource.startsWith('voyage/nile/page')) return Response.json({ html: saved ? html.replace('First light', 'New light') : html })
    const doc = docs[resource.split('document/nile/')[1]]
    if (!doc) throw new Error('Unexpected request ' + path)
    if (init.method === 'POST') {
      if (refuse) { refuse = false; return Response.json({ detail: refusal }, { status: 400 }) }
      saved = true
      return Response.json({ commit: 'ea1234567', changed: doc.name === 'voyage' ? changed : [doc.name], summary: 'Saved' })
    }
    return Response.json(locked ? { ...doc, writable: false, why: 'Writing is switched off.' } : doc)
  }))
  return calls
}
beforeEach(() => {
  api.setAccessToken('jwt')
  api.setToken('room-token')
  // jsdom has no modal top layer. Model the open attribute and dispatch cancel
  // in the Escape test. The film messages below come from its actual Window.
  HTMLDialogElement.prototype.showModal = function () { this.open = true }
  HTMLDialogElement.prototype.close = function () { this.open = false }
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

function atStop(source: Window | null, id = 'aswan', name: string | null = 'Aswan', sender = 'longway-voyage') {
  fireEvent(window, new MessageEvent('message', { source, data: { source: sender, type: 'station', station: id, name } }))
}

it('offers the film only on flagged House cards and on the picked journey, including for a non-manager', async () => {
  const calls = serve()
  render(<LongwayHouse roomId="home" canManageHome={false} onNavigate={vi.fn()} />)
  const card = await screen.findByRole('article', { name: 'The Nile' })
  expect(screen.getAllByText('Ride the voyage')).toEqual([within(card).getByText('Ride the voyage')])
  fireEvent.click(within(card).getByText('The Nile'))
  const chosen = screen.getByRole('group', { name: 'On the globe: The Nile' })
  fireEvent.click(within(chosen).getByText('Ride the voyage'))
  expect(await screen.findByTitle('The Nile voyage film')).toHaveAttribute('srcdoc', expect.stringContaining(html))
  expect(screen.getByTitle('The Nile voyage film').getAttribute('srcdoc')).toMatch(/<\/html><script>.*?Escape/s)
  expect(calls.find(c => c.path === '/rooms/home/longway/voyage/nile/page')?.init.headers).toMatchObject({ Authorization: 'Bearer jwt', 'X-Room-Token': 'room-token' })
  fireEvent.click(button('The house'))
  expect(within(chosen).getByText('Ride the voyage')).toBeVisible()
})

it('rides from the chart, authenticates film messages, retains a refused draft and resumes the accepted stop', async () => {
  const calls = serve({ refuse: true })
  const notified = vi.fn()
  window.addEventListener('longway:changed', notified, { once: true })
  render(<LongwayBench roomId="room" />)
  fireEvent.click(await screen.findByRole('button', { name: 'Ride the voyage' }))
  const frame = await screen.findByTitle<HTMLIFrameElement>('The Nile voyage film')
  expect(frame).toHaveAttribute('sandbox', 'allow-scripts allow-popups allow-popups-to-escape-sandbox')
  expect(frame).toHaveAttribute('allow', 'fullscreen; autoplay')
  atStop(window)
  atStop(frame.contentWindow, 'fake', 'Fake', 'other')
  expect(button('Edit this stop')).toBeDisabled()
  atStop(frame.contentWindow, 'aswan', null)
  expect(button('Edit this stop')).toBeEnabled()
  atStop(frame.contentWindow)
  expect(screen.getByText('Aswan')).toBeVisible()
  const send = vi.spyOn(frame.contentWindow!, 'postMessage')
  fireEvent.click(button('Edit this stop'))
  expect(send).toHaveBeenCalledWith({ source: 'longway-house', type: 'pause' }, '*')
  const kicker = await screen.findByLabelText('Kicker')
  atStop(frame.contentWindow, 'komombo', 'Kom Ombo')
  fireEvent.change(kicker, { target: { value: 'New light' } })
  fireEvent.click(button('Save'))
  expect(await screen.findByRole('alert')).toHaveTextContent(refusal)
  expect(screen.getByRole('alert').textContent).toBe(refusal)
  expect(kicker).toHaveValue('New light')
  expect(notified).not.toHaveBeenCalled()
  expect(frame).toHaveAttribute('srcdoc', expect.stringContaining(html))
  fireEvent.click(button('Save'))
  const writes = calls.filter(c => c.init.method === 'POST')
  expect(writes).toHaveLength(2)
  expect(writes[1]).toMatchObject({ path: '/rooms/room/longway/document/nile/voyage', body: { ops: [{ op: 'set', path: changed[0], value: 'New light' }] } })
  await waitFor(() => expect(screen.getByTitle('The Nile voyage film')).toHaveAttribute('srcdoc', expect.stringContaining('New light')))
  expect(calls.filter(c => c.path.includes('/page')).map(c => c.path)).toEqual(['/rooms/room/longway/voyage/nile/page', '/rooms/room/longway/voyage/nile/page?station=aswan'])
  expect(notified).toHaveBeenCalledOnce()
  expect(calls.filter(c => c.path.endsWith('/chart'))).toHaveLength(2)
  expect(screen.getByRole('status')).toHaveTextContent('ea12345 · stations/aswan/kicker')
})

it('opens the Library film, reaches every voyage part and saves only the selected JSON value', async () => {
  const calls = serve()
  render(<LongwayLibrary roomId="room" />)
  fireEvent.click(await screen.findByText('Ride the voyage'))
  const frame = await screen.findByTitle<HTMLIFrameElement>('The Nile voyage film')
  atStop(frame.contentWindow)
  fireEvent.click(button('Edit this stop'))
  await screen.findByLabelText('Name')
  fireEvent.change(screen.getByLabelText('What to edit'), { target: { value: 'everything' } })
  const picker = screen.getByLabelText<HTMLSelectElement>('Everything', { exact: true })
  expect(Array.from(picker.options, o => o.value)).toEqual([...Object.keys(voyage), 'stations/aswan', 'stations/komombo'])
  fireEvent.change(picker, { target: { value: 'acts' } })
  const acts = screen.getByLabelText('acts', { exact: true })
  fireEvent.change(acts, { target: { value: '[{' } })
  expect(screen.getByRole('alert')).toHaveTextContent('Check the JSON')
  expect(button('Save')).toBeDisabled()
  expect(calls.filter(c => c.init.method === 'POST')).toHaveLength(0)
  const value = [{ id: 'upper', title: 'Above the dam' }]
  fireEvent.change(acts, { target: { value: JSON.stringify(value) } })
  fireEvent.click(button('Save'))
  await screen.findByText('ea12345')
  expect(calls.find(c => c.init.method === 'POST')?.body).toEqual({ ops: [{ op: 'set', path: 'acts', value }] })
})


it('keeps numeric and citation fields in sync with the complete station, including fields the form does not name', async () => {
  const calls = serve()
  render(<LongwayLibrary roomId="room" />)
  fireEvent.click(await screen.findByText('Ride the voyage'))
  const frame = await screen.findByTitle<HTMLIFrameElement>('The Nile voyage film')
  atStop(frame.contentWindow)
  fireEvent.click(button('Edit this stop'))
  fireEvent.change(await screen.findByLabelText('Camera zoom'), { target: { value: '7.5' } })
  fireEvent.change(screen.getByLabelText('Moment citations (comma separated)'), { target: { value: 'S104, S12' } })
  fireEvent.click(screen.getByText('All fields (JSON)', { selector: 'summary' }))
  const all = screen.getByRole<HTMLTextAreaElement>('textbox', { name: 'All fields (JSON)' })
  const edited = { ...stop, camera: { zoom: 7.5 }, moment: { ...stop.moment, cite: ['S104', 'S12'] } }
  expect(JSON.parse(all.value)).toEqual(edited)
  const complete = { ...edited, film: { title: 'Crossing the Nile' } }
  fireEvent.change(all, { target: { value: JSON.stringify(complete) } })
  expect(screen.getByLabelText('Camera zoom')).toHaveValue(7.5)
  fireEvent.click(button('Save'))
  await screen.findByText('ea12345')
  expect(calls.find(c => c.init.method === 'POST')?.body).toEqual({
    ops: [{ op: 'set', path: 'stations/aswan', value: complete }],
  })
})

it('opens dossier and record for a Library member without a voyage and refreshes the saved projection', async () => {
  const calls = serve({ hasVoyage: false })
  render(<LongwayLibrary roomId="room" />)
  fireEvent.click(await screen.findByText('Edit dossier'))
  expect(screen.queryByText('Ride the voyage')).toBeNull()
  const markdown = await screen.findByLabelText('Dossier markdown')
  fireEvent.change(markdown, { target: { value: '# Saved dossier' } })
  fireEvent.click(button('Save'))
  await screen.findByRole('heading', { name: 'Saved dossier' })
  fireEvent.click(button('Edit record'))
  const status = await screen.findByLabelText('status')
  expect(status).toHaveAttribute('readonly')
  expect(status).toHaveValue('candidate')
  expect(screen.getByLabelText('reviewed_by')).toHaveAttribute('readonly')
  fireEvent.change(screen.getByLabelText('title'), { target: { value: 'Upper Nile' } })
  fireEvent.click(button('Save'))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  expect(calls.filter(c => c.init.method === 'POST').map(c => [c.path, c.body])).toEqual([
    ['/rooms/room/longway/document/nile/dossier', { text: '# Saved dossier' }],
    ['/rooms/room/longway/document/nile/record', { ops: [{ op: 'set', path: 'title', value: 'Upper Nile' }] }],
  ])
})

it('shows the write lock and closes the editor before the film on modal cancel', async () => {
  serve({ locked: true })
  render(<LongwayBench roomId="room" />)
  fireEvent.click(await screen.findByText('Ride the voyage'))
  const frame = await screen.findByTitle<HTMLIFrameElement>('The Nile voyage film')
  atStop(frame.contentWindow)
  fireEvent.click(button('Edit this stop'))
  expect(await screen.findByText('Writing is switched off.')).toBeVisible()
  expect(button('Save')).toBeDisabled()
  fireEvent(screen.getByRole('dialog', { name: 'Edit The Nile' }), new Event('cancel'))
  expect(frame).toBeInTheDocument()
  fireEvent(screen.getByRole('dialog', { name: 'The Nile voyage' }), new Event('cancel'))
  expect(screen.queryByRole('dialog')).toBeNull()
})

it('keeps Dialectic Bench and Library on their existing requests when the organ is unset', async () => {
  vi.stubEnv('VITE_ORGAN', undefined)
  vi.resetModules()
  try {
    const { BenchScene } = await import('../../../components/workspace/scenes/BenchScene')
    const { LibraryScene } = await import('../../../components/workspace/scenes/LibraryScene')
    const fetch = vi.fn(async () => Response.json({ items: [], next_before: null }))
    vi.stubGlobal('fetch', fetch)
    const empty = { status: 'empty' } as const
    render(<><BenchScene roomId="room" tradingPanel={<p>Trading panel</p>}
      state={{ status: 'ready', objects: [], generatedAt: 'today', retry: vi.fn() }}
      desk={{ bound: false, refresh: vi.fn(), structure: empty, quotes: empty, polymarket: empty, diff: empty, trades: empty, brief: empty, news: empty, portfolio: empty }} />
      <LibraryScene roomId="room" onOpen={vi.fn()} /></>)
    expect(screen.getByText('Trading panel')).toBeVisible()
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1))
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/rooms/room/reading/library'), expect.anything())
    expect(screen.queryByRole('button', { name: /Ride the voyage|Edit dossier|Edit record/ })).toBeNull()
  } finally { vi.unstubAllEnvs() }
})
