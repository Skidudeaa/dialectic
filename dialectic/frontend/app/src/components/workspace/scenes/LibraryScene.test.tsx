import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import axe from 'axe-core'
import type { ReadingLibraryItem } from '../../../types/index.ts'
import { api } from '../../../lib/api.ts'
import { PARTICIPANT_NAME } from '../../../lib/productIdentity.ts'
import { LibraryScene } from './LibraryScene.tsx'

vi.mock('../../../lib/api.ts', () => ({
  api: { getReadingLibrary: vi.fn() },
}))

const reading = (overrides: Partial<ReadingLibraryItem> = {}): ReadingLibraryItem => ({
  id: 'reading-1',
  url: 'https://example.com/exact',
  title: 'Exact capture',
  author: 'A. Writer',
  site: 'Example',
  published: '2026-08-28',
  summary: 'The exact rendered source.',
  source: 'browser_capture',
  saved_by_user_id: 'user-1',
  created_at: '2026-08-27T12:00:00Z',
  current_captured_at: '2026-08-28T12:00:00Z',
  content_sha256: 'a'.repeat(64),
  current_revision_id: 'revision-1',
  revision_count: 2,
  capture_mode: 'article',
  ...overrides,
})

async function runDebounce() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(220)
  })
}

describe('LibraryScene', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('loads rich server rows and opens a branchless reading through its bare id', async () => {
    vi.mocked(api.getReadingLibrary).mockResolvedValue({ items: [reading()], next_before: null })
    const onOpen = vi.fn()
    render(<LibraryScene roomId="room-1" onOpen={onOpen} />)

    expect(screen.getByTestId('scene-loading')).toBeInTheDocument()
    await runDebounce()

    expect(screen.getAllByText('Safari capture')).toHaveLength(2)
    expect(screen.getByText('2 revisions')).toBeInTheDocument()
    expect(screen.getByText('Article')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Open Exact capture' }))
    expect(onOpen).toHaveBeenCalledWith('reading-1')
  })

  it('sends debounced full-text, exact-site, and source filters to the server', async () => {
    vi.mocked(api.getReadingLibrary).mockResolvedValue({ items: [reading()], next_before: null })
    render(<LibraryScene roomId="room-1" onOpen={vi.fn()} />)
    await runDebounce()

    fireEvent.change(screen.getByRole('searchbox', { name: 'Search readings' }), {
      target: { value: '  shipping risk  ' },
    })
    fireEvent.change(screen.getByRole('combobox', { name: 'Site' }), {
      target: { value: ' Example ' },
    })
    fireEvent.change(screen.getByRole('combobox', { name: 'Source' }), {
      target: { value: 'browser_capture' },
    })
    await runDebounce()

    expect(api.getReadingLibrary).toHaveBeenLastCalledWith('room-1', {
      q: 'shipping risk',
      site: 'Example',
      source: 'browser_capture',
      limit: 50,
    })
  })

  it('appends stable cursor pages without duplicating an overlapping row', async () => {
    vi.mocked(api.getReadingLibrary)
      .mockResolvedValueOnce({ items: [reading()], next_before: 'cursor-1' })
      .mockResolvedValueOnce({
        items: [reading(), reading({ id: 'reading-2', title: 'Older capture' })],
        next_before: null,
      })
    render(<LibraryScene roomId="room-1" onOpen={vi.fn()} />)
    await runDebounce()

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Load more' }))
      await Promise.resolve()
    })

    expect(api.getReadingLibrary).toHaveBeenLastCalledWith('room-1', {
      q: '', site: '', source: '', limit: 50, before: 'cursor-1',
    })
    expect(screen.getAllByRole('listitem')).toHaveLength(2)
    expect(screen.getByText('Older capture')).toBeInTheDocument()
  })

  it('keeps errors distinct from empty and makes retry recover in place', async () => {
    vi.mocked(api.getReadingLibrary)
      .mockRejectedValueOnce(new Error('database unavailable'))
      .mockResolvedValueOnce({ items: [reading()], next_before: null })
    render(<LibraryScene roomId="room-1" onOpen={vi.fn()} />)
    await runDebounce()

    expect(screen.getByTestId('scene-unavailable')).toHaveTextContent('database unavailable')
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    await runDebounce()
    expect(screen.getByText('Exact capture')).toBeInTheDocument()
  })

  it('teaches the real filing paths without claiming every source needs Accept', async () => {
    vi.mocked(api.getReadingLibrary).mockResolvedValue({ items: [], next_before: null })
    render(<LibraryScene roomId="room-1" onOpen={vi.fn()} />)
    await runDebounce()

    const empty = screen.getByTestId('scene-empty')
    expect(empty).toHaveTextContent('Somacura Capture')
    expect(empty).toHaveTextContent('file relevant sources directly')
    expect(empty).not.toHaveTextContent('nothing lands here on its own')
    expect(empty.textContent).not.toMatch(new RegExp(`${PARTICIPANT_NAME}[a-z]`))
  })

  it('does not let a slow previous-room response replace the new room', async () => {
    let resolveFirst: (value: { items: ReadingLibraryItem[]; next_before: null }) => void = () => {}
    vi.mocked(api.getReadingLibrary)
      .mockReturnValueOnce(new Promise((resolve) => { resolveFirst = resolve }))
      .mockResolvedValueOnce({
        items: [reading({ id: 'new', title: 'New room reading' })],
        next_before: null,
      })
    const { rerender } = render(<LibraryScene roomId="old-room" onOpen={vi.fn()} />)
    await runDebounce()
    rerender(<LibraryScene roomId="new-room" onOpen={vi.fn()} />)
    await runDebounce()
    expect(screen.getByText('New room reading')).toBeInTheDocument()

    await act(async () => {
      resolveFirst({ items: [reading({ title: 'Stale room reading' })], next_before: null })
      await Promise.resolve()
    })
    expect(screen.queryByText('Stale room reading')).toBeNull()
  })

  it('does not let an old A page append after an A to B to A filter cycle', async () => {
    let resolveOldPage: (value: { items: ReadingLibraryItem[]; next_before: null }) => void = () => {}
    vi.mocked(api.getReadingLibrary)
      .mockResolvedValueOnce({ items: [reading({ title: 'Initial A' })], next_before: 'old-a-cursor' })
      .mockReturnValueOnce(new Promise((resolve) => { resolveOldPage = resolve }))
      .mockResolvedValueOnce({ items: [reading({ id: 'b', title: 'Result B' })], next_before: null })
      .mockResolvedValueOnce({ items: [reading({ id: 'fresh-a', title: 'Fresh A' })], next_before: null })
    render(<LibraryScene roomId="room-1" onOpen={vi.fn()} />)
    await runDebounce()
    fireEvent.click(screen.getByRole('button', { name: 'Load more' }))

    const search = screen.getByRole('searchbox', { name: 'Search readings' })
    fireEvent.change(search, { target: { value: 'B' } })
    await runDebounce()
    expect(screen.getByText('Result B')).toBeInTheDocument()
    fireEvent.change(search, { target: { value: '' } })
    await runDebounce()
    expect(screen.getByText('Fresh A')).toBeInTheDocument()

    await act(async () => {
      resolveOldPage({ items: [reading({ id: 'stale-a', title: 'Stale A page' })], next_before: null })
      await Promise.resolve()
    })
    expect(screen.queryByText('Stale A page')).toBeNull()
    expect(screen.queryByRole('button', { name: /loading more/i })).toBeNull()
  })

  it('does not call JWT-only Library routes for a guest identity', async () => {
    render(<LibraryScene roomId="room-1" enabled={false} onOpen={vi.fn()} />)
    await runDebounce()
    expect(api.getReadingLibrary).not.toHaveBeenCalled()
    expect(screen.getByText('Sign in to open the Library.')).toBeInTheDocument()
    expect(screen.queryByLabelText('Library search and filters')).toBeNull()
  })

  it('passes the accessibility gate with filters and a populated result', async () => {
    vi.mocked(api.getReadingLibrary).mockResolvedValue({ items: [reading()], next_before: null })
    const { container } = render(<LibraryScene roomId="room-1" onOpen={vi.fn()} />)
    await runDebounce()
    vi.useRealTimers()
    const results = await axe.run(container)
    expect(results.violations).toEqual([])
  })
})
