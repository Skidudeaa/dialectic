import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { LongwayHouse } from './LongwayHouse'
import { LongwayBench } from './LongwayBench'
import { LongwayLibrary } from './LongwayLibrary'
import raw from './__fixtures__/chart.json'
import type { FriendNote } from './types'

vi.mock('./chartSlot', () => ({ default: () => <div>Globe</div> }))
const open: FriendNote = { id: 'N1', kind: 'place', by: 'Mia', at: '2026-11-21', text: 'Stay for sunset.', place: 'Philae', state: 'open', note: 'Looking for a crossing.' }
const drafted: FriendNote = { ...open, id: 'N3', state: 'drafted', place: 'Dendera', text: 'Look at the ceiling.', note: 'Found a way in.',
  draft: { name: 'Temple of Hathor', kicker: 'Painted stars', moment: { text: 'Look up into the blue.', cite: ['S104'] },
    photo: { url: 'photo.jpg', page: 'photo.html', author: 'Leila', licence: 'CC BY' } } }
const accepted: FriendNote = { ...open, id: 'N4', state: 'accepted', place: 'Luxor' }
const aside: FriendNote = { ...open, id: 'N5', state: 'set aside', place: 'Edfu', note: 'Too far this time.' }
const thought: FriendNote = { ...open, id: 'N6', kind: 'thought', text: 'An extra day here.', about: 'aswan' }
const base = '/rooms/home/longway/'
const book = base + 'notebook/nile'
const button = (name: string) => screen.getByRole('button', { name })
const list = () => within(screen.getByRole('region', { name: 'From friends' }))
function serve({ manager = false, voyage = false, locked = false, refuse = '', sendBackRefuse = '', scoutConflict = false,
  pull = raw.journeys[0].pull, dossier = '# The Nile', initial = [] as FriendNote[] } = {}) {
  let notes = [...initial]
  const calls: { path: string; method: string; body: unknown }[] = []
  const journey = { ...raw.journeys[0], slug: 'nile', title: 'The Nile', voyage, pull }
  vi.stubGlobal('fetch', vi.fn(async (path: string, init: RequestInit = {}) => {
    const method = init.method ?? 'GET'
    const body = init.body && JSON.parse(String(init.body))
    calls.push({ path, method, body })
    if (path === base + 'chart') return Response.json({ ...raw, journeys: [{ ...journey,
      notes: { open: notes.filter(n => n.state === 'open').length, drafted: notes.filter(n => n.state === 'drafted').length } }],
      rooms: [], room: { id: 'home', linked_journey: 'nile', is_home: false, can_edit: manager }, fixes_state: { stale: false } })
    if (path === base + 'riding') return Response.json({ rides: [] })
    if (path === base + 'journey/nile') return Response.json({ ...journey, dossier, evidence: [], vehicles: [] })
    if (path === book && method === 'GET') return Response.json({ slug: 'nile', notes, can_review: manager, writable: !locked, why: locked ? 'The house is resting.' : null })
    if (path === book && method === 'POST') {
      if (refuse) return Response.json({ detail: refuse }, { status: 400 })
      const note = { ...body, by: 'Amo', at: '2026-11-21', state: 'open', id: 'N' + (10 + notes.length) }
      notes = [...notes, note]
      return Response.json({ note, commit: 'abc0000' })
    }
    if (path === book + '/N3/send-back' && method === 'POST') {
      if (sendBackRefuse) return Response.json({ detail: sendBackRefuse }, { status: 400 })
      const note: FriendNote = {
        ...drafted,
        state: 'open',
        draft: null,
        note: null,
        steer: { by: 'Amo', at: '2026-11-21', text: body.why },
      }
      notes = notes.map(item => item.id === note.id ? note : item)
      return Response.json({ note, commit: 'eed0000' })
    }
    if ([book + '/N3/accept', book + '/N3/set-aside'].includes(path) && method === 'POST') {
      const note: FriendNote = { ...drafted, state: path.endsWith('/accept') ? 'accepted' : 'set aside', note: body.why }
      notes = notes.map(item => item.id === note.id ? note : item)
      return Response.json({ note, commit: 'def0000' })
    }
    if (path === book + '/scout' && method === 'POST') return scoutConflict
      ? Response.json({ detail: 'The Scout is already away.' }, { status: 409 }) : Response.json({ run_id: 'run-1' })
    if (path.startsWith(base + 'voyage/nile/page')) return Response.json({ html: path.includes('?preview=') || notes.some(n => n.id === 'N3' && n.state === 'accepted') ? '<p>Temple of Hathor</p>' : '<p>Aswan</p>' })
    throw new Error('Unexpected request ' + path)
  }))
  return calls
}
beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function () { this.open = true }
  HTMLDialogElement.prototype.close = function () { this.open = false }
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

it('adds a place from a roomless House card and shows the returned words on the picked journey', async () => {
  const calls = serve()
  render(<LongwayHouse roomId="home" canManageHome={false} onNavigate={vi.fn()} />)
  const card = within(await screen.findByRole('article', { name: 'The Nile' }))
  expect(calls.some(call => call.path === book)).toBe(false)
  expect(card.getByText('Add a thought')).toBeVisible()
  expect(card.queryByText('Ride the voyage')).toBeNull()
  fireEvent.click(card.getByText('Add a place'))
  fireEvent.change(screen.getByLabelText('Where?'), { target: { value: 'Dendera' } })
  fireEvent.change(screen.getByLabelText('Why this place?'), { target: { value: 'For the painted ceiling.' } })
  await waitFor(() => expect(button('Send')).toBeEnabled())
  fireEvent.click(button('Send'))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  expect(calls.filter(c => c.method === 'POST')).toEqual([{ path: book, method: 'POST', body: { kind: 'place', text: 'For the painted ceiling.', place: 'Dendera', about: null } }])
  expect(list().getByText('For the painted ceiling.')).toBeVisible()
  expect(list().getByText('Dendera')).toBeVisible()
  expect(list().getByText(/Amo/)).toHaveTextContent('Amo · 21 Nov')
  expect(list().getByText('New. The Scout will look into it.')).toBeVisible()
  expect(card.getByText('The Scout will look into your place overnight.')).toBeVisible()
  expect(await card.findByText('1 from friends')).toBeVisible()
  expect(card.queryByText('From friends')).toBeNull()
  expect(within(screen.getByRole('group', { name: 'On the globe: The Nile' })).getByText('Add a place')).toBeVisible()
})

it('keeps both words and place when the server refuses', async () => {
  serve({ refuse: 'Name the place' })
  render(<LongwayBench roomId="home" />)
  fireEvent.click(await screen.findByText('Add a place'))
  fireEvent.change(screen.getByLabelText('Where?'), { target: { value: 'Dendera' } })
  fireEvent.change(screen.getByLabelText('Why this place?'), { target: { value: 'Visit at dawn.' } })
  await waitFor(() => expect(button('Send')).toBeEnabled())
  fireEvent.click(button('Send'))
  expect(await screen.findByRole('alert')).toHaveTextContent(/^Name the place$/)
  expect(screen.getByLabelText('Where?')).toHaveValue('Dendera')
  expect(screen.getByLabelText('Why this place?')).toHaveValue('Visit at dawn.')
})

it('gives a friend plain place statuses, thoughts without status, and no management controls', async () => {
  serve({ initial: [open, drafted, accepted, aside, thought] })
  render(<LongwayLibrary roomId="home" />)
  await screen.findByText('New. The Scout will look into it.')
  for (const line of ['The Scout has drafted this stop. Waiting for a house manager.', 'In the journey.', 'Set aside.',
    'Looking for a crossing.', 'Found a way in.', 'Too far this time.']) expect(list().getByText(line)).toBeVisible()
  expect(list().getByText('An extra day here.').closest('article')).toHaveTextContent(/^Mia · 21 NovAn extra day here\.$/)
  for (const name of ['Accept', 'Send back', 'Set aside', 'See it in the film', 'Send the Scout now', 'Edit dossier', 'Edit record']) {
    expect(screen.queryByRole('button', { name })).toBeNull()
  }
  expect(button('Add a place')).toBeEnabled()
  expect(button('Add a thought')).toBeEnabled()
  expect(screen.queryByText(/S104|N3|Temple of Hathor/)).toBeNull()
})

it('anchors a film thought to the stop when opened, and can send one about the whole journey', async () => {
  const calls = serve({ voyage: true })
  render(<LongwayBench roomId="home" />)
  fireEvent.click(await screen.findByText('Ride the voyage'))
  const stage = within(screen.getByRole('dialog', { name: 'The Nile voyage' }))
  const frame = await stage.findByTitle<HTMLIFrameElement>('The Nile voyage film')
  const station = (id: string, name: string) => fireEvent(window, new MessageEvent('message', { source: frame.contentWindow,
    data: { source: 'longway-voyage', type: 'station', station: id, name } }))
  expect(stage.getByText('Add a place')).toBeVisible()
  expect(stage.queryByText('Edit this stop')).toBeNull()
  for (const whole of [false, true]) {
    station('aswan', 'Aswan')
    fireEvent.click(stage.getByText('Add a thought'))
    const panel = within(screen.getByRole('dialog', { name: 'Add a thought' }))
    station('luxor', 'Luxor')
    expect(panel.getByText('About Aswan')).toBeVisible()
    if (whole) fireEvent.click(panel.getByRole('button', { name: 'About the whole journey' }))
    fireEvent.change(panel.getByLabelText('Your thought'), { target: { value: 'Slow down.' } })
    fireEvent.click(panel.getByText('Send'))
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Add a thought' })).toBeNull())
    expect(stage.getByText('Your thought has been added.')).toBeVisible()
  }
  expect(calls.filter(c => c.method === 'POST').map(c => c.body)).toEqual(['aswan', null].map(about => ({ kind: 'thought', text: 'Slow down.', place: null, about })))
})

it('previews a drafted stop, accepts it, re-reads the list and opens the accepted film', async () => {
  const calls = serve({ voyage: true, manager: true, initial: [drafted] })
  render(<LongwayLibrary roomId="home" />)
  expect(await screen.findByText('Temple of Hathor')).toBeVisible()
  for (const line of ['Painted stars', 'Look up into the blue.', 'Photograph by Leila · CC BY']) expect(list().getByText(line)).toBeVisible()
  expect(button('Set aside')).toBeEnabled()
  fireEvent.click(button('See it in the film'))
  expect(await screen.findByTitle('The Nile voyage film')).toHaveAttribute('srcdoc', expect.stringContaining('Temple of Hathor'))
  expect(calls.some(c => c.path === base + 'voyage/nile/page?preview=N3')).toBe(true)
  fireEvent.click(button('The house'))
  fireEvent.click(button('Accept'))
  expect(await screen.findByText('In the journey.')).toBeVisible()
  expect(calls.filter(c => c.path.startsWith(book)).map(c => [c.method, c.path])).toEqual([['GET', book], ['POST', book + '/N3/accept'], ['GET', book]])
  expect(screen.queryByRole('button', { name: 'Accept' })).toBeNull()
  fireEvent.click(button('Ride the voyage'))
  expect(await screen.findByTitle('The Nile voyage film')).toHaveAttribute('srcdoc', expect.stringContaining('Temple of Hathor'))
  expect(calls.at(-1)?.path).toBe(base + 'voyage/nile/page')
})

it('sets a draft aside with a reason and reports the Scout’s refusal', async () => {
  const calls = serve({ manager: true, scoutConflict: true, initial: [open, drafted] })
  render(<LongwayBench roomId="home" />)
  fireEvent.click(await screen.findByText('Set aside'))
  fireEvent.change(screen.getByLabelText('Reason (optional)'), { target: { value: 'Save for winter.' } })
  fireEvent.click(button('Set aside'))
  expect(await screen.findByText('Set aside.')).toBeVisible()
  expect(list().getByText('Save for winter.')).toBeVisible()
  expect(calls.find(c => c.path === book + '/N3/set-aside')?.body).toEqual({ why: 'Save for winter.' })
  fireEvent.click(button('Send the Scout now'))
  expect(await screen.findByRole('alert')).toHaveTextContent(/^The Scout is already away\.$/)
})
it('reports when the Scout run starts', async () => {
  serve({ manager: true, initial: [open] })
  render(<LongwayBench roomId="home" />)
  fireEvent.click(await screen.findByText('Send the Scout now'))
  expect(await screen.findByText('The Scout run has started.')).toBeVisible()
})
it('gives the server’s reason when adding is closed', async () => {
  serve({ locked: true })
  render(<LongwayLibrary roomId="home" />)
  expect(await screen.findByText('The house is resting.')).toBeVisible()
  expect(button('Add a place')).toBeDisabled()
  expect(button('Add a thought')).toBeDisabled()
})

it('sends a drafted place back with steer, re-reads the list, and never sends a blank reason', async () => {
  const calls = serve({ manager: true, initial: [drafted] })
  render(<LongwayLibrary roomId="home" />)
  fireEvent.click(await screen.findByRole('button', { name: 'Send back' }))
  const input = screen.getByLabelText('What should change?')
  expect(button('Send back')).toBeDisabled()
  fireEvent.change(input, { target: { value: '   ' } })
  expect(button('Send back')).toBeDisabled()
  fireEvent.submit(input.closest('form')!)
  expect(calls.filter(c => c.method === 'POST')).toHaveLength(0)
  fireEvent.change(input, { target: { value: 'The photograph is the wrong temple.' } })
  expect(button('Send back')).toBeEnabled()
  fireEvent.click(button('Send back'))
  expect(await screen.findByText('Sent back to the Scout by Amo: The photograph is the wrong temple.')).toBeVisible()
  expect(list().getByText('New. The Scout will look into it.')).toBeVisible()
  expect(screen.queryByRole('button', { name: 'Send back' })).toBeNull()
  expect(calls.filter(c => c.path.startsWith(book)).map(c => [c.method, c.path, c.body])).toEqual([
    ['GET', book, undefined],
    ['POST', book + '/N3/send-back', { why: 'The photograph is the wrong temple.' }],
    ['GET', book, undefined],
  ])
})

it('shows the server’s refusal on send-back 400 and keeps what was typed', async () => {
  serve({ manager: true, sendBackRefuse: 'Say what to change, in a few words', initial: [drafted] })
  render(<LongwayLibrary roomId="home" />)
  fireEvent.click(await screen.findByRole('button', { name: 'Send back' }))
  const input = screen.getByLabelText('What should change?')
  fireEvent.change(input, { target: { value: 'Use the ceiling photo.' } })
  fireEvent.click(button('Send back'))
  expect(await screen.findByRole('alert')).toHaveTextContent(/^Say what to change, in a few words$/)
  expect(screen.getByLabelText('What should change?')).toHaveValue('Use the ceiling photo.')
})

it('shows the sent-back steer line and open status to both friend and manager without exposing controls to a friend', async () => {
  const sentBack: FriendNote = {
    ...open,
    id: 'N8',
    place: 'Dendera',
    text: 'The zodiac ceiling at dusk.',
    note: null,
    steer: { by: 'Amo', at: '2026-11-21', text: 'The photograph is the wrong temple.' },
  }
  for (const manager of [false, true]) {
    serve({ manager, initial: [sentBack] })
    render(<LongwayLibrary roomId="home" />)
    expect(await screen.findByText('Sent back to the Scout by Amo: The photograph is the wrong temple.')).toBeVisible()
    expect(list().getByText('New. The Scout will look into it.')).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Send back' })).toBeNull()
    if (!manager) expect(screen.queryByRole('button', { name: 'Send the Scout now' })).toBeNull()
    cleanup()
  }
})

it('strips citation markers from pulls on House cards, picked panel, Chart and Library hero while keeping them in the full dossier', async () => {
  const pullWithCites = 'Covers Old Nubia S123, a dahabiya under sail S177 S173, and the 2027 window S8 S9.'
  const cleanText = 'Covers Old Nubia, a dahabiya under sail, and the 2027 window.'
  const dossier = [
    '# The Nile',
    '',
    '## The pull',
    'Covers Old Nubia [S123](https://kasribrim.com/), a dahabiya under sail [S177](https://a.example) [S173](https://b.example), and the 2027 window [S8](https://c.example) [S9](https://d.example).',
    '',
    '## Notes',
    'Full evidence reference [S123](https://kasribrim.com/) stays here.',
  ].join('\n')

  serve({ pull: pullWithCites, dossier })
  render(<LongwayHouse roomId="home" canManageHome={false} onNavigate={vi.fn()} />)
  const card = await screen.findByRole('article', { name: 'The Nile' })
  expect(within(card).getByText(cleanText)).toBeVisible()
  expect(within(card).queryByText(/S123|S177|S173|S8|S9/)).toBeNull()
  fireEvent.click(within(card).getByRole('button', { name: 'The Nile' }))
  const chosen = screen.getByRole('group', { name: 'On the globe: The Nile' })
  expect(within(chosen).getByText(cleanText)).toBeVisible()
  expect(within(chosen).queryByText(/S123|S177|S173|S8|S9/)).toBeNull()
  cleanup()

  serve({ pull: pullWithCites, dossier })
  render(<LongwayBench roomId="home" />)
  const chartPull = await screen.findByText(cleanText)
  expect(chartPull).toBeVisible()
  expect(chartPull.textContent).not.toMatch(/S123|S177|S173|S8|S9/)
  expect(screen.queryByText(/S123|S177|S173/)).toBeNull()
  cleanup()

  serve({ pull: pullWithCites, dossier })
  render(<LongwayLibrary roomId="home" />)
  const hero = (await screen.findByRole('heading', { level: 1, name: 'The Nile' })).closest('header')!
  expect(within(hero).getByText(cleanText)).toBeVisible()
  expect(within(hero).queryByText(/S123|S177|S173|S8|S9/)).toBeNull()
  const dossierSection = screen.getByRole('region', { name: 'Dossier' })
  expect(within(dossierSection).getAllByRole('link', { name: 'S123' }).length).toBeGreaterThan(0)
})
