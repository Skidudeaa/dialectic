import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { MirrorRoom, MirrorVersion } from '../../types'
import { MirrorPanel } from './MirrorPanel'
import { api } from '../../lib/api'

vi.mock('../../lib/api', async () => {
  const actual = await vi.importActual<typeof import('../../lib/api')>('../../lib/api')
  return {
    ...actual,
    api: {
      getMirror: vi.fn(),
      getMirrorVersions: vi.fn(),
      getMirrorDiff: vi.fn(),
    },
  }
})

afterEach(() => vi.clearAllMocks())

const ROOM = 'room-uuid-1'

const room: MirrorRoom = {
  room_id: ROOM,
  room_name: 'Japan Rate Shock',
  version: 3,
  updated_at: '2026-08-17T23:56:24Z',
  content: '## Thinking Style\nCurrent revision.',
}

const versions: MirrorVersion[] = [
  { version: 3, updated_at: '2026-08-17T23:56:24Z', content: '## Thinking Style\nCurrent revision.' },
  { version: 2, updated_at: '2026-08-12T08:01:40Z', content: '## Thinking Style\nMiddle revision.' },
  { version: 1, updated_at: '2026-08-01T08:01:40Z', content: '## Thinking Style\nFirst revision.' },
]

function mount(rooms: MirrorRoom[] = [room], history: MirrorVersion[] = versions) {
  vi.mocked(api.getMirror).mockResolvedValue(rooms)
  vi.mocked(api.getMirrorVersions).mockResolvedValue(history)
  return render(<MirrorPanel />)
}

/**
 * Wait until the HISTORY has landed, not merely the panel.
 *
 * The panel renders as soon as `getMirror` resolves; `getMirrorVersions` is a
 * second request and until it lands `versions` is empty, which leaves
 * "Earlier" disabled and every step click a no-op. In isolation both
 * microtasks drain before the first assertion and the race is invisible; in a
 * full-suite run under load it is not, and the symptom is a timed-out
 * `waitFor` that reads like a broken stepper.
 */
async function stepperReady() {
  await screen.findByTestId('mirror-panel')
  await waitFor(() =>
    expect(screen.getByText(/Earlier/).hasAttribute('disabled')).toBe(false))
}

/**
 * The Mirror's surface, rendered.
 *
 * Everything behind this panel is mutation-proven and probed against real
 * Postgres; this was the only part of the feature with no evidence at all,
 * and a passing typecheck says nothing about pixels. The house rule this
 * honours: geometry is not a render.
 *
 * What can actually break here is the step arithmetic — the history arrives
 * NEWEST FIRST, so "Earlier" walks the index UP, and getting that backwards
 * would silently show the wrong revision under the right version number.
 */
describe('the Mirror', () => {
  it('shows the current revision and how many there have been', async () => {
    mount()
    await screen.findByTestId('mirror-panel')
    expect(screen.getByTestId('mirror-version').textContent).toBe('3')
    expect(screen.getByText(/Current revision/)).toBeTruthy()
    expect(screen.getByText(/You were never the audience/)).toBeTruthy()
  })

  it('walks backwards through the rewrites, newest first', async () => {
    mount()
    await stepperReady()
    // Newest first, so stepping "Earlier" walks the index UP.
    fireEvent.click(screen.getByText(/Earlier/))
    await waitFor(() =>
      expect(screen.getByTestId('mirror-version').textContent).toBe('2'))
    expect(screen.getByText(/Middle revision/)).toBeTruthy()
    expect(screen.getByText('1 rewrite ago')).toBeTruthy()

    fireEvent.click(screen.getByText(/Later/))
    await waitFor(() =>
      expect(screen.getByTestId('mirror-version').textContent).toBe('3'))
    expect(screen.getByText('Current')).toBeTruthy()
  })

  it('stops at both ends rather than running off the history', async () => {
    mount()
    await stepperReady()
    // At the newest there is nothing later.
    expect(screen.getByText(/Later/).hasAttribute('disabled')).toBe(true)
    fireEvent.click(screen.getByText(/Earlier/))
    fireEvent.click(screen.getByText(/Earlier/))
    await waitFor(() =>
      expect(screen.getByTestId('mirror-version').textContent).toBe('1'))
    // And at the oldest there is nothing earlier, and nothing to diff against.
    expect(screen.getByText(/Earlier/).hasAttribute('disabled')).toBe(true)
    expect(screen.getByText('What changed').hasAttribute('disabled')).toBe(true)
  })

  it('asks for the diff between the shown version and the one before it', async () => {
    vi.mocked(api.getMirrorDiff).mockResolvedValue({
      room_id: ROOM, from_version: 2, to_version: 3,
      lines: ['-Middle revision.', '+Current revision.'],
    })
    mount()
    await stepperReady()
    fireEvent.click(screen.getByText('What changed'))
    // from = the OLDER one. Reversed, the diff reads as an un-edit.
    await waitFor(() =>
      expect(api.getMirrorDiff).toHaveBeenCalledWith(ROOM, 2, 3))
    expect(await screen.findByText('+Current revision.')).toBeTruthy()
    fireEvent.click(screen.getByText('Hide changes'))
    await waitFor(() =>
      expect(screen.queryByText('+Current revision.')).toBeNull())
  })

  it('says so plainly when the participant has never written one', async () => {
    mount([], [])
    await screen.findByTestId('mirror-quiet')
    expect(screen.getByText(/Nothing yet/)).toBeTruthy()
  })

  it('reads as unanswered, not as empty, when the door fails', async () => {
    // An error rendered as "you have no profile" is a lie about the data.
    vi.mocked(api.getMirror).mockRejectedValue(new Error('boom'))
    render(<MirrorPanel />)
    await screen.findByTestId('mirror-quiet')
    expect(screen.getByText(/not answering/)).toBeTruthy()
  })
})
