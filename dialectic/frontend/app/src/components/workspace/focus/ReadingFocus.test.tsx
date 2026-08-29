import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import axe from 'axe-core'
import type { ReadingDetail } from '../../../types/index.ts'
import { api } from '../../../lib/api.ts'
import { FocusSurface } from './FocusSurface.tsx'

vi.mock('../../../lib/api.ts', () => ({
  api: {
    getReadingDetail: vi.fn(),
    fetchReadingMarkdown: vi.fn(),
  },
}))

const exactMarkdown = [
  '# Captured heading',
  '',
  'Exact *body*.',
  '',
  '<script>window.__hostile = true</script>',
  '',
  '<div style="position:fixed;inset:0;z-index:9999">overlay attempt</div>',
  '',
  '![Tracking pixel](https://tracker.example/pixel.png)',
  '',
  '[unsafe](javascript:alert(1))',
].join('\n')

const detail = (overrides: Partial<ReadingDetail> = {}): ReadingDetail => ({
  id: 'reading-1',
  room_id: 'room-1',
  url: 'https://example.com/source',
  title: 'Exact capture',
  author: 'A. Writer',
  site: 'Example',
  published: '2026-08-28',
  word_count: 1200,
  markdown: exactMarkdown,
  summary: 'Why this source mattered.',
  key_claims: ['The body is exact.'],
  source: 'browser_capture',
  source_message_id: null,
  saved_by_user_id: 'user-1',
  created_at: '2026-08-28T12:00:00Z',
  current_revision_id: 'revision-1',
  current_captured_at: '2026-08-28T11:59:00Z',
  content_sha256: 'a'.repeat(64),
  revisions: [{
    id: 'revision-1',
    capture_id: 'capture-1',
    capture_mode: 'article',
    content_sha256: 'a'.repeat(64),
    captured_at: '2026-08-28T11:59:00Z',
    received_at: '2026-08-28T12:00:00Z',
    captured_by_user_id: 'user-1',
    actor_name: 'Amo',
    is_current: true,
    extraction: {
      engine: 'defuddle',
      engine_version: '1.0',
      client_version: '0.1',
      fallback_reason: null,
    },
    note: 'Captured while authenticated.',
  }],
  ...overrides,
})

const baseProps = {
  objectId: 'reading:reading-1',
  objects: { status: 'ready' as const, objects: [], generatedAt: 'x', retry: vi.fn() },
  fieldMarks: { status: 'ready' as const, marks: [], generatedAt: 'x', refresh: vi.fn() },
  canAct: true,
  onNavigate: vi.fn(),
  onReview: vi.fn().mockResolvedValue(undefined),
  roomId: 'room-1',
}

afterEach(() => {
  vi.clearAllMocks()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: undefined })
})

describe('Reading Focus', () => {
  it('loads directly by room and id outside the 50-object workspace projection', async () => {
    vi.mocked(api.getReadingDetail).mockResolvedValue(detail())
    render(<FocusSurface {...baseProps} />)

    expect(await screen.findByRole('heading', { name: 'Exact capture' })).toBeInTheDocument()
    expect(api.getReadingDetail).toHaveBeenCalledWith('room-1', 'reading-1')
    expect(screen.getByText(/Safari capture/)).toBeInTheDocument()
    expect(screen.getByText('The body is exact.')).toBeInTheDocument()

    const source = screen.getByRole('link', { name: 'Open original ↗' })
    expect(source).toHaveAttribute('href', 'https://example.com/source')
    expect(source).toHaveAttribute('target', '_blank')
    expect(source).toHaveAttribute('rel', 'noopener noreferrer')

    const revisionHistory = screen.getByRole('list', { name: 'Revision history' })
    expect(within(revisionHistory).getByText('Current')).toBeInTheDocument()
    expect(revisionHistory).toHaveTextContent('Captured while authenticated.')
  })

  it('renders Markdown only after sanitizing hostile HTML and active URLs', async () => {
    vi.mocked(api.getReadingDetail).mockResolvedValue(detail())
    const { container } = render(<FocusSurface {...baseProps} />)

    expect(await screen.findByRole('heading', { name: 'Captured heading' })).toBeInTheDocument()
    expect(container.querySelector('script')).toBeNull()
    expect(container).not.toHaveTextContent('window.__hostile')
    expect(container.querySelector('[style]')).toBeNull()
    expect(container.querySelector('img')).toBeNull()
    const imageReference = screen.getByRole('link', { name: 'Image reference: Tracking pixel' })
    expect(imageReference).toHaveAttribute('href', 'https://tracker.example/pixel.png')
    expect(imageReference).toHaveAttribute('referrerpolicy', 'no-referrer')
    expect(screen.getByText('unsafe').closest('a')).toBeNull()
  })

  it('never turns a non-HTTP source value into an active link', async () => {
    vi.mocked(api.getReadingDetail).mockResolvedValue(detail({ url: 'javascript:alert(1)' }))
    render(<FocusSurface {...baseProps} />)
    await screen.findByRole('heading', { name: 'Exact capture' })
    expect(screen.queryByRole('link', { name: 'Open original ↗' })).toBeNull()
    expect(screen.getByText('Original URL is not safe to open')).toBeInTheDocument()
  })

  it('copies the untouched Markdown string rather than rendered HTML', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    })
    vi.mocked(api.getReadingDetail).mockResolvedValue(detail())
    render(<FocusSurface {...baseProps} />)
    await screen.findByRole('heading', { name: 'Exact capture' })

    fireEvent.click(screen.getByRole('button', { name: 'Copy Markdown' }))
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(exactMarkdown))
    expect(screen.getByRole('button', { name: 'Copied exact Markdown' })).toBeInTheDocument()
  })

  it('downloads the authenticated server Blob under the server filename', async () => {
    vi.mocked(api.getReadingDetail).mockResolvedValue(detail())
    const blob = new Blob([exactMarkdown], { type: 'text/markdown' })
    vi.mocked(api.fetchReadingMarkdown).mockResolvedValue({ blob, filename: 'Exact-capture.md' })
    const createObjectURL = vi.fn().mockReturnValue('blob:exact-reading')
    const revokeObjectURL = vi.fn()
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createObjectURL })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: revokeObjectURL })
    let clicked: { href: string; download: string } | null = null
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function click(this: HTMLAnchorElement) {
      clicked = { href: this.href, download: this.download }
    })
    render(<FocusSurface {...baseProps} />)
    await screen.findByRole('heading', { name: 'Exact capture' })

    fireEvent.click(screen.getByRole('button', { name: 'Download .md' }))
    await waitFor(() => expect(api.fetchReadingMarkdown).toHaveBeenCalledWith('room-1', 'reading-1'))
    expect(createObjectURL).toHaveBeenCalledWith(blob)
    expect(clicked).toEqual({ href: 'blob:exact-reading', download: 'Exact-capture.md' })
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:exact-reading')
  })

  it('keeps a detail failure visible and retryable instead of claiming the object is absent', async () => {
    vi.mocked(api.getReadingDetail)
      .mockRejectedValueOnce(new Error('detail unavailable'))
      .mockResolvedValueOnce(detail())
    render(<FocusSurface {...baseProps} />)

    expect(await screen.findByTestId('scene-unavailable')).toHaveTextContent('detail unavailable')
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByRole('heading', { name: 'Exact capture' })).toBeInTheDocument()
  })

  it('does not fetch a JWT-only reading detail for a guest identity', () => {
    render(<FocusSurface {...baseProps} canAct={false} />)
    expect(api.getReadingDetail).not.toHaveBeenCalled()
    expect(screen.getByText('Sign in to open this reading.')).toBeInTheDocument()
  })

  it('starts an oversized valid capture as an explicit bounded preview', async () => {
    vi.mocked(api.getReadingDetail).mockResolvedValue(detail({
      markdown: `# Large\n\n${'x'.repeat(200_001)}`,
    }))
    render(<FocusSurface {...baseProps} />)
    expect(await screen.findByRole('button', { name: 'Render full Markdown' })).toBeInTheDocument()
    expect(screen.getByText(/Showing the first 200,000 characters/)).toBeInTheDocument()
  })

  it('makes the compact takeover modal, isolates its background, focuses Back, and closes on Escape', async () => {
    vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({
      matches: true,
      media: '(max-width: 1023.98px)',
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }))
    vi.mocked(api.getReadingDetail).mockResolvedValue(detail({ markdown: 'Compact body.' }))
    const onNavigate = vi.fn()
    render(
      <div>
        <button type="button">Background action</button>
        <FocusSurface {...baseProps} onNavigate={onNavigate} />
      </div>,
    )

    const dialog = await screen.findByRole('dialog', { name: 'Reading Focus' })
    const back = screen.getByRole('button', { name: 'Close Focus' })
    await waitFor(() => expect(back).toHaveFocus())
    expect(screen.getByRole('button', { name: 'Background action' })).toHaveAttribute('inert')
    fireEvent.keyDown(dialog, { key: 'Escape' })
    expect(onNavigate).toHaveBeenCalledWith({ object: null })
  })

  it('passes the accessibility gate at the ready detail state', async () => {
    vi.mocked(api.getReadingDetail).mockResolvedValue(detail({ markdown: 'A plain captured paragraph.' }))
    const { container } = render(<FocusSurface {...baseProps} />)
    await screen.findByRole('heading', { name: 'Exact capture' })
    const results = await axe.run(container)
    expect(results.violations).toEqual([])
  })
})
