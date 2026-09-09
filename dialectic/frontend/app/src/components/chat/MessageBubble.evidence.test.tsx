import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Message, MessageMetadata, MessageRef } from '../../types'
import { MessageBubble } from './MessageBubble'
import { api } from '../../lib/api'
import { useAppStore } from '../../stores/appStore'

vi.mock('../../lib/api', async () => {
  const actual = await vi.importActual<typeof import('../../lib/api')>('../../lib/api')
  return {
    ...actual,
    api: { fileReading: vi.fn(), getThreadDecisions: vi.fn(() => new Promise(() => {})) },
  }
})

afterEach(() => {
  useAppStore.setState({ currentRoom: null } as never)
  vi.clearAllMocks()
})

const MID = '33333333-3333-4333-8333-333333333333'
const ARTICLE_URL = 'https://example.test/tanker-rates'

function message(metadata: MessageMetadata, speaker: Message['speaker_type'] = 'llm_primary'): Message {
  return {
    id: MID, thread_id: 'thread-1', sequence: 2, created_at: '2026-09-08T12:00:00Z',
    speaker_type: speaker, message_type: 'text', user_id: speaker === 'human' ? 'u1' : null,
    content: 'The freight lead shows up in the tanker data first.', metadata,
  } as unknown as Message
}

const EVIDENCE: MessageMetadata = {
  tools: { iterations: 2, degraded: false, calls: [
    { name: 'read_article', label: 'reading the article', ok: true, input: { url: ARTICLE_URL }, evidence: [
      { kind: 'article', url: ARTICLE_URL, title: 'Tanker rates lead crude', author: 'A Reporter', site: 'example.test', published: '2026-08-15T00:00:00Z',
        content_sha256: 'f'.repeat(64), excerpt: 'Freight rates on the Gulf routes moved first.', excerpt_truncated: true },
    ] },
    { name: 'search_reading', label: 'searching what we’ve read', ok: true, input: { query: 'delay' }, evidence: [
      { kind: 'reading', url: 'https://example.test/kept', reading_id: 'kept', title: 'Kept piece', content_sha256: 'b'.repeat(64), excerpt: 'the ranked extract' },
    ] },
    { name: 'get_live_quotes', label: 'checking prices', ok: true },
  ] },
  refs: [{ entity: 'reading_items', id: 'kept', label: 'Kept piece', quote: 'quoted words', content_sha256: 'a'.repeat(64) }],
}

describe('evidence beside the thought', () => {
  it('renders attributed excerpts with Open original, the exact revision, a visible revision mismatch, and the raw stamp', () => {
    useAppStore.setState({ currentRoom: { id: 'room-1' } } as never)
    render(<MessageBubble message={message(EVIDENCE)} authorName="Dialectic" isSelf={false} />)
    expect(screen.getByRole('region', { name: 'Evidence · 2 sources' })).toBeInTheDocument()
    expect(screen.getByText('Tanker rates lead crude')).toBeInTheDocument()
    expect(screen.getByText('A Reporter · example.test · 2026-08-15')).toBeInTheDocument()
    expect(screen.getByText(/Freight rates on the Gulf routes moved first\. …$/)).toBeInTheDocument()
    const links = screen.getAllByRole('link', { name: 'Open original ↗' })
    expect(links[0]).toHaveAttribute('href', ARTICLE_URL)
    expect(links[0]).toHaveAttribute('target', '_blank')
    expect(links[0]).toHaveAttribute('rel', 'noopener noreferrer')
    expect(screen.getByText('revision ffffffff')).toBeInTheDocument()
    expect(screen.getByText('Source revision differs from the quoted passage (aaaaaaaa)')).toBeInTheDocument()
    expect(screen.getByText('in the library')).toBeInTheDocument()
    expect(screen.getByText('Raw tool payload · read_article')).toBeInTheDocument()
    expect(screen.getByText('Raw tool payload · search_reading').closest('details')!.querySelector('pre')!.textContent).toContain('"query": "delay"')
  })

  it('saves a fetched source to the room from the answer that fetched it, and reports failure', async () => {
    useAppStore.setState({ currentRoom: { id: 'room-1' } } as never)
    const fileReading = vi.mocked(api.fileReading)
    fileReading.mockRejectedValueOnce(new Error('422')).mockResolvedValueOnce({ reading: {} })
    render(<MessageBubble message={message(EVIDENCE)} authorName="Dialectic" isSelf={false} />)
    expect(screen.getAllByRole('button', { name: 'Save to room' })).toHaveLength(1)
    fireEvent.click(screen.getByRole('button', { name: 'Save to room' }))
    expect(fileReading).toHaveBeenCalledWith('room-1', { message_id: MID, url: ARTICLE_URL })
    await waitFor(() => expect(screen.getByRole('button', { name: 'Retry save' })).toBeInTheDocument())
    expect(screen.getByText('could not save — try again')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Retry save' }))
    await waitFor(() => expect(screen.getByText('saved to room')).toBeInTheDocument())
    expect(fileReading).toHaveBeenCalledTimes(2)
  })

  it('stays out of streaming and human messages, and summons evidence or a challenge into the exact branch', () => {
    useAppStore.setState({ currentRoom: { id: 'room-1' } } as never)
    const investigate = vi.fn()
    const source: MessageRef = { entity: 'reading_items', id: 'r', label: 'Source' }
    const { rerender } = render(<MessageBubble message={message(EVIDENCE)} authorName="Dialectic" isSelf={false} isStreaming onInvestigate={investigate} threadSource={source} />)
    expect(screen.queryByRole('region', { name: /Evidence/ })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Challenge' })).toBeNull()
    rerender(<MessageBubble message={message(EVIDENCE, 'human')} authorName="Amo" isSelf onInvestigate={investigate} threadSource={source} />)
    expect(screen.queryByRole('region', { name: /Evidence/ })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Find and pull' }))
    expect(investigate).toHaveBeenLastCalledWith(MID)
    fireEvent.click(screen.getByRole('button', { name: 'Challenge' }))
    expect(investigate).toHaveBeenLastCalledWith(MID, undefined, 'challenge')
  })
})
