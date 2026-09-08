import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useState } from 'react'
import { api } from '../../../lib/api'
import type { MessageRef, ReadingDetail } from '../../../types'
import { SurfaceEvidence } from './SurfaceEvidence'
import { toSurfaceMessages } from './surfaceModel'

vi.mock('../../../lib/api', () => ({ api: { getReadingLibrary: vi.fn(), getReadingDetail: vi.fn() } }))
const reading: ReadingDetail = {
  id: 'source', room_id: 'room', title: 'Strait report', url: 'https://example.com/strait',
  author: null, site: 'Example', published: null, word_count: 12,
  markdown: '# Report\n\nTankers **wait outside** the strait.', summary: 'Timing matters.', key_claims: [],
  source: 'browser', source_message_id: null, saved_by_user_id: null, created_at: '2026-09-04T12:00:00Z',
  current_revision_id: 'revision', current_captured_at: '2026-09-04T12:00:00Z', content_sha256: 'a'.repeat(64), revisions: [],
}
const ref: MessageRef = { entity: 'reading_items', id: reading.id, label: reading.title! }
const messages = toSurfaceMessages(['Amo', 'Dan'].map((name, index) => ({
  id: name, thread_id: 'thread', sequence: index + 1, speaker_type: 'human', user_id: name,
  message_type: 'text', content: `${name}'s view on timing`, created_at: '2026-09-04T12:00:00Z',
  references_message_id: index ? 'Amo' : undefined,
  metadata: { refs: [{ ...ref, quote: 'Tankers wait outside the strait.' }] },
})), { userNames: { Amo: 'Amo', Dan: 'Dan' }, currentUserId: 'Amo' })
const discuss = vi.fn(), reply = vi.fn(), jump = vi.fn()
afterEach(() => vi.unstubAllGlobals())
function Table({ initial = null }: { initial?: MessageRef | null }) {
  const [selected, setSelected] = useState(initial)
  return <SurfaceEvidence roomId="room" messages={messages} selected={selected} onSelect={setSelected}
    onDiscuss={discuss} onReply={reply} onJump={jump} onOpenFull={vi.fn()} />
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.getReadingLibrary).mockResolvedValue({ items: [], next_before: null })
  vi.mocked(api.getReadingDetail).mockResolvedValue(reading)
})

describe('shared evidence', () => {
  it('captures native selection changes and offers the exact quote without pointerup', async () => {
    render(<Table initial={ref} />)
    const prose = await screen.findByTestId('reading-markdown')
    const range = document.createRange()
    range.selectNodeContents(prose.querySelector('p')!)
    const selection = window.getSelection()!
    selection.removeAllRanges(); selection.addRange(range)
    fireEvent(document, new Event('selectionchange'))
    expect(screen.getByRole('region', { name: 'Comment on selected passage' })).toHaveTextContent('Tankers wait outside the strait.')
    fireEvent.click(screen.getByRole('button', { name: 'Discuss this passage' }))
    expect(discuss).toHaveBeenCalledWith({ ...ref, quote: 'Tankers wait outside the strait.', content_sha256: reading.content_sha256 })
  })

  it('offers an explicitly bounded excerpt when a selected paragraph exceeds the quote limit', async () => {
    const paragraph = 'The opening of this paragraph uniquely locates its source. ' + 'Supporting detail follows. '.repeat(18)
    vi.mocked(api.getReadingDetail).mockResolvedValue({ ...reading, markdown: paragraph })
    render(<Table initial={ref} />)
    const prose = await screen.findByTestId('reading-markdown')
    const range = document.createRange()
    range.selectNodeContents(prose.querySelector('p')!)
    const selection = window.getSelection()!
    selection.removeAllRanges(); selection.addRange(range)
    fireEvent(document, new Event('selectionchange'))
    expect(screen.getByRole('status')).toHaveTextContent('Quoting the first 300 characters')
    fireEvent.click(screen.getByRole('button', { name: 'Discuss this passage' }))
    expect(discuss).toHaveBeenCalledWith({ ...ref, quote: paragraph.slice(0, 300).trim(), content_sha256: reading.content_sha256 })
  })

  it('opens a sole reading once and lets the reader return to all sources', async () => {
    vi.mocked(api.getReadingLibrary).mockResolvedValue({ items: [{ ...reading, revision_count: 1, capture_mode: 'article' }], next_before: null })
    render(<Table />)
    await screen.findByTestId('reading-markdown')
    fireEvent.click(screen.getByRole('button', { name: 'All sources' }))
    expect(screen.queryByTestId('reading-markdown')).not.toBeInTheDocument()
    expect(await screen.findByRole('button', { name: /Strait report/ })).toBeInTheDocument()
  })

  it('keeps source choice explicit when the library has multiple readings', async () => {
    vi.mocked(api.getReadingLibrary).mockResolvedValue({ items: [{ ...reading, revision_count: 1, capture_mode: 'article' }, { ...reading, id: 'second', title: 'Other report', revision_count: 1, capture_mode: 'article' }], next_before: null })
    render(<Table />)
    await screen.findByRole('button', { name: /Other report/ })
    expect(screen.queryByTestId('reading-markdown')).not.toBeInTheDocument()
    expect(api.getReadingDetail).not.toHaveBeenCalled()
  })

  it('opens a source and carries the exact rendered selection with its revision', async () => {
    render(<Table />)
    fireEvent.click(await screen.findByRole('button', { name: /Strait report/ }))
    const document = await screen.findByTestId('reading-markdown')
    const passage = document.querySelector('p')!
    const selection = window.getSelection()!
    const range = window.document.createRange()
    range.selectNodeContents(passage)
    selection.removeAllRanges()
    selection.addRange(range)
    fireEvent.pointerUp(document)
    fireEvent.click(screen.getByRole('button', { name: 'Discuss this passage' }))
    expect(discuss).toHaveBeenCalledWith({ ...ref, quote: 'Tankers wait outside the strait.', content_sha256: reading.content_sha256 })
    selection.removeAllRanges()
  })

  it('keeps both people with the source and provides direct reply and jump actions', async () => {
    render(<Table initial={ref} />)
    await screen.findByTestId('reading-markdown')
    fireEvent.click(screen.getByText('2 contributions · Amo · Dan'))
    expect(screen.getByText("Amo's view on timing")).toBeInTheDocument()
    expect(screen.getByText("Dan's view on timing")).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Reply to Dan' }))
    expect(reply).toHaveBeenCalledWith('Dan')
    fireEvent.click(screen.getByRole('button', { name: /Amo's view on timing/ }))
    expect(jump).toHaveBeenCalledWith('Amo')
  })

  it('retains the original quotation when a source revision changed', async () => {
    render(<Table initial={{ ...ref, quote: 'Original quoted words', content_sha256: 'b'.repeat(64) }} />)
    expect(await screen.findByText(/This source has changed/)).toBeInTheDocument()
    expect(screen.getByText('Original quoted words')).toBeInTheDocument()
  })
  it('recognizes a changed legacy reading from its text even without stored revision metadata', async () => {
    const digest = vi.fn().mockResolvedValue(new Uint8Array(32).fill(170).buffer)
    vi.stubGlobal('crypto', { subtle: { digest } })
    vi.mocked(api.getReadingDetail).mockResolvedValue({ ...reading, content_sha256: null, current_revision_id: null })
    render(<Table initial={{ ...ref, quote: 'Original passage', content_sha256: 'b'.repeat(64) }} />)
    expect(await screen.findByText(/This source has changed/)).toBeInTheDocument()
    expect(screen.getByText('Original passage')).toBeInTheDocument()
    expect(digest).toHaveBeenCalledWith('SHA-256', new TextEncoder().encode(reading.markdown))
  })

  it('shows an explicit retry when reading detail fails', async () => {
    vi.mocked(api.getReadingDetail).mockRejectedValueOnce(new Error('Source unavailable'))
    render(<Table initial={ref} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Source unavailable')
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    await screen.findByTestId('reading-markdown')
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
  })
})

describe('physical passage navigation', () => {
  it('links the exact rendered quote and does not refetch the article when navigating within it', async () => {
    const quoted = { ...ref, quote: 'Tankers wait outside the strait.', content_sha256: reading.content_sha256! }
    const open = vi.fn()
    const props = { roomId: 'room', messages, onSelect: vi.fn(), onDiscuss: discuss, onReply: reply, onJump: jump, onOpenFull: vi.fn(), passages: [quoted], onPassage: open }
    const { container, rerender } = render(<SurfaceEvidence {...props} selected={ref} />)
    await waitFor(() => expect(container.querySelectorAll('mark')).toHaveLength(3))
    window.getSelection()?.removeAllRanges()
    fireEvent.click(container.querySelector('mark')!)
    expect(open).toHaveBeenCalledWith(quoted)
    rerender(<SurfaceEvidence {...props} selected={quoted} />)
    await waitFor(() => expect(container.querySelector('mark')).toHaveAttribute('data-active', 'true'))
    expect(api.getReadingDetail).toHaveBeenCalledTimes(1)
  })
  it('preserves an active selection while another contribution adds a highlight', async () => {
    const first = { ...ref, quote: 'wait outside', content_sha256: reading.content_sha256! }
    const second = { ...ref, quote: 'the strait.', content_sha256: reading.content_sha256! }
    const props = { roomId: 'room', messages, selected: ref, onSelect: vi.fn(), onDiscuss: discuss, onReply: reply, onJump: jump, onOpenFull: vi.fn() }
    const { container, rerender } = render(<SurfaceEvidence {...props} passages={[first]} />)
    await waitFor(() => expect(container.querySelector('mark')).not.toBeNull())
    const selection = window.getSelection()!
    const range = document.createRange()
    range.selectNodeContents(container.querySelector('mark')!)
    selection.removeAllRanges(); selection.addRange(range)
    rerender(<SurfaceEvidence {...props} passages={[first, second]} />)
    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(selection.toString()).toBe('wait outside')
    selection.removeAllRanges()
    fireEvent(document, new Event('selectionchange'))
    await waitFor(() => expect(container.querySelectorAll('mark')).toHaveLength(2))
  })
  it('distinguishes adding evidence to a reply from starting a new thread', async () => {
    const attach = vi.fn()
    render(<SurfaceEvidence roomId="room" messages={messages} selected={ref} onSelect={vi.fn()} onDiscuss={discuss} onAttach={attach} onReply={reply} onJump={jump} onOpenFull={vi.fn()} />)
    await screen.findByTestId('reading-markdown')
    fireEvent.click(screen.getByRole('button', { name: 'Attach source to reply' }))
    expect(attach).toHaveBeenCalledWith({ ...ref, content_sha256: reading.content_sha256 })
    expect(discuss).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Start a new thread' }))
    expect(discuss).toHaveBeenCalledWith({ ...ref, content_sha256: reading.content_sha256 })
  })
  it('keeps a stale quote visible without painting the current article', async () => {
    const quoted = { ...ref, quote: 'Tankers wait outside the strait.', content_sha256: 'b'.repeat(64) }
    const { container } = render(<SurfaceEvidence roomId="room" messages={messages} selected={quoted} onSelect={vi.fn()} onDiscuss={discuss} onReply={reply} onJump={jump} onOpenFull={vi.fn()} passages={[quoted]} />)
    await screen.findByText(/cannot be uniquely located/)
    expect(container.querySelector('mark')).toBeNull()
    expect(container.querySelector('.surf-evidence-quoted')).toHaveTextContent(quoted.quote)
  })
})
