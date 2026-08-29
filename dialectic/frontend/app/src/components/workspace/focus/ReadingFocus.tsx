import { useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import type { ReadingDetail, ReadingRevision } from '../../../types/index.ts'
import { api } from '../../../lib/api.ts'
import { SceneLoading, SceneUnavailable } from '../SceneEmpty.tsx'
import { FocusHeader } from './FocusHeader.tsx'

type DetailState =
  | { status: 'loading' }
  | { status: 'error'; error: string }
  | { status: 'ready'; detail: ReadingDetail }

const SOURCE_LABELS: Record<string, string> = {
  browser_capture: 'Safari capture',
  proposal: 'Accepted proposal',
  human: 'Filed by a person',
  wire: 'Wire',
  night_shift: 'Night shift',
  newsletter: 'Newsletter',
  congress: 'Congress',
}

const MODE_LABELS: Record<string, string> = {
  selection: 'Selection',
  article: 'Article',
  page_fallback: 'Rendered page fallback',
}

const MARKDOWN_PREVIEW_CHARS = 200_000
const COMPACT_FOCUS_QUERY = '(max-width: 1023.98px)'

function sourceLabel(value: string): string {
  return SOURCE_LABELS[value] ?? value.replaceAll('_', ' ')
}

function modeLabel(value: string): string {
  return MODE_LABELS[value] ?? value.replaceAll('_', ' ')
}

function stamp(value: string | null): string {
  if (!value) return 'Not recorded'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: 'numeric', minute: '2-digit',
  })
}

function isHttpUrl(value: string): boolean {
  try {
    const protocol = new URL(value).protocol
    return protocol === 'http:' || protocol === 'https:'
  } catch {
    return false
  }
}

/** Captured content is hostile document data. DOMPurify removes executable
 * markup; the detached template then removes passive-but-dangerous behavior:
 * CSS cannot overlay the app, and remote images become explicit links rather
 * than automatic tracking requests. Only our own class is added afterward. */
function sanitizedMarkdown(markdown: string): string {
  const parsed = marked.parse(markdown, { async: false }) as string
  const clean = DOMPurify.sanitize(parsed, {
    FORBID_TAGS: [
      'style', 'form', 'input', 'button', 'textarea', 'select', 'option',
      'iframe', 'object', 'embed', 'video', 'audio', 'source', 'track',
      'svg', 'math',
    ],
    FORBID_ATTR: [
      'style', 'class', 'id', 'srcset', 'poster', 'background', 'formaction',
      'autofocus', 'autoplay',
    ],
  })
  const template = document.createElement('template')
  template.innerHTML = clean

  for (const image of template.content.querySelectorAll('img')) {
    const source = image.getAttribute('src') ?? ''
    const label = image.getAttribute('alt')?.trim() || source || 'unavailable image'
    const replacement = document.createElement(isHttpUrl(source) ? 'a' : 'span')
    replacement.className = 'reading-focus-image-reference'
    replacement.textContent = `Image reference: ${label}`
    if (replacement instanceof HTMLAnchorElement) {
      replacement.href = source
      replacement.target = '_blank'
      replacement.rel = 'noopener noreferrer'
      replacement.setAttribute('referrerpolicy', 'no-referrer')
    }
    image.replaceWith(replacement)
  }

  for (const link of template.content.querySelectorAll('a')) {
    const href = link.getAttribute('href') ?? ''
    if (!isHttpUrl(href)) {
      const replacement = document.createElement('span')
      replacement.textContent = link.textContent
      link.replaceWith(replacement)
      continue
    }
    link.target = '_blank'
    link.rel = 'noopener noreferrer'
    link.setAttribute('referrerpolicy', 'no-referrer')
    link.removeAttribute('download')
  }
  return template.innerHTML
}

function RenderedMarkdown({ markdown }: { markdown: string }) {
  const isBoundedPreview = markdown.length > MARKDOWN_PREVIEW_CHARS
  const [showFull, setShowFull] = useState(!isBoundedPreview)
  const source = showFull ? markdown : markdown.slice(0, MARKDOWN_PREVIEW_CHARS)
  const renderKey = showFull ? 'full' : 'preview'
  const [rendered, setRendered] = useState<{
    key: string
    html: string | null
    error: string | null
  } | null>(null)

  // Parse after the detail shell paints, so Back and the exact export controls
  // remain reachable before a large document consumes the main thread. A 2 MB
  // capture starts as a bounded preview; full rendering is an explicit act.
  useEffect(() => {
    let cancelled = false
    const timer = window.setTimeout(() => {
      try {
        const html = sanitizedMarkdown(source)
        if (!cancelled) setRendered({ key: renderKey, html, error: null })
      } catch (cause: unknown) {
        if (!cancelled) {
          setRendered({
            key: renderKey,
            html: null,
            error: cause instanceof Error ? cause.message : 'Markdown rendering failed',
          })
        }
      }
    }, 0)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [renderKey, source])

  const current = rendered?.key === renderKey ? rendered : null
  return (
    <>
      {isBoundedPreview && !showFull && (
        <div className="reading-focus-preview-note" role="note">
          <span>Showing the first {MARKDOWN_PREVIEW_CHARS.toLocaleString()} characters for responsive reading.</span>
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => setShowFull(true)}>
            Render full Markdown
          </button>
        </div>
      )}
      {current?.error ? (
        <p className="reading-focus-action-error" role="alert">
          Could not render this Markdown: {current.error}. Copy and download still use the exact stored body.
        </p>
      ) : current?.html === null || !current ? (
        <p className="reading-focus-quiet" role="status">Rendering Markdown…</p>
      ) : (
        <div
          className="reading-focus-prose"
          data-testid="reading-markdown"
          dangerouslySetInnerHTML={{ __html: current.html }}
        />
      )}
    </>
  )
}

function RevisionRow({ revision }: { revision: ReadingRevision }) {
  const extraction = revision.extraction
  return (
    <li className={`reading-revision${revision.is_current ? ' is-current' : ''}`}>
      <div className="reading-revision-head">
        <span>{modeLabel(revision.capture_mode)}</span>
        {revision.is_current && <strong>Current</strong>}
      </div>
      <dl className="reading-revision-grid">
        <div><dt>Captured</dt><dd><time dateTime={revision.captured_at}>{stamp(revision.captured_at)}</time></dd></div>
        <div><dt>Received</dt><dd><time dateTime={revision.received_at}>{stamp(revision.received_at)}</time></dd></div>
        <div><dt>By</dt><dd>{revision.actor_name || revision.captured_by_user_id}</dd></div>
        <div><dt>Capture ID</dt><dd><code>{revision.capture_id}</code></dd></div>
        <div><dt>SHA-256</dt><dd><code>{revision.content_sha256}</code></dd></div>
        <div>
          <dt>Extractor</dt>
          <dd>
            {extraction.engine
              ? `${extraction.engine}${extraction.engine_version ? ` ${extraction.engine_version}` : ''}`
              : 'Not recorded'}
          </dd>
        </div>
        {extraction.client_version && <div><dt>Client</dt><dd>{extraction.client_version}</dd></div>}
        {extraction.fallback_reason && <div><dt>Fallback</dt><dd>{extraction.fallback_reason}</dd></div>}
      </dl>
      {revision.note && <p className="reading-revision-note">{revision.note}</p>}
    </li>
  )
}

/** Reading is a Focus specialization, not a second Library route. It resolves
 * directly by room + reading id so an FTS hit older than the workspace
 * projection's 50-row cap remains reloadable through the URL object axis. */
export function ReadingFocus({
  roomId,
  readingId,
  onClose,
}: {
  roomId: string
  readingId: string
  onClose: () => void
}) {
  const [attempt, setAttempt] = useState(0)
  const [state, setState] = useState<DetailState>({ status: 'loading' })
  const [copyState, setCopyState] = useState<'idle' | 'copying' | 'copied' | 'error'>('idle')
  const [downloadState, setDownloadState] = useState<'idle' | 'downloading' | 'downloaded' | 'error'>('idle')
  const [actionError, setActionError] = useState<string | null>(null)
  const [modal, setModal] = useState(
    () => typeof window.matchMedia === 'function' && window.matchMedia(COMPACT_FOCUS_QUERY).matches,
  )
  const rootRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return
    const query = window.matchMedia(COMPACT_FOCUS_QUERY)
    const onChange = (event: MediaQueryListEvent) => setModal(event.matches)
    query.addEventListener('change', onChange)
    return () => query.removeEventListener('change', onChange)
  }, [])

  useEffect(() => {
    let cancelled = false
    void api.getReadingDetail(roomId, readingId)
      .then((detail) => {
        if (!cancelled) setState({ status: 'ready', detail })
      })
      .catch((cause: unknown) => {
        if (cancelled) return
        setState({
          status: 'error',
          error: cause instanceof Error ? cause.message : 'Could not read this source',
        })
      })
    return () => { cancelled = true }
  }, [attempt, readingId, roomId])

  // A CSS takeover is not a modal by itself. On compact screens move focus
  // into Reading Focus and make every sibling outside its ancestor chain
  // inert until Back/Escape closes it. Attributes that predated us survive.
  useEffect(() => {
    const root = rootRef.current
    if (!modal || !root) return
    const changed: HTMLElement[] = []
    let current: HTMLElement = root
    while (current.parentElement) {
      const parent = current.parentElement
      for (const sibling of parent.children) {
        if (sibling === current || !(sibling instanceof HTMLElement)) continue
        if (!sibling.hasAttribute('inert')) {
          sibling.setAttribute('inert', '')
          changed.push(sibling)
        }
      }
      if (parent.id === 'root' || parent === document.body) break
      current = parent
    }
    return () => {
      for (const element of changed) element.removeAttribute('inert')
    }
  }, [modal])

  useEffect(() => {
    if (!modal) return
    rootRef.current?.querySelector<HTMLElement>('.focus-close')?.focus()
  }, [modal, state.status])

  const handleKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Escape') {
      event.preventDefault()
      onClose()
      return
    }
    if (!modal || event.key !== 'Tab') return
    const root = rootRef.current
    if (!root) return
    const focusable = [...root.querySelectorAll<HTMLElement>(
      'a[href], button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), summary',
    )]
    if (focusable.length === 0) return
    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    const active = document.activeElement
    if (event.shiftKey && (active === first || !root.contains(active))) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && (active === last || !root.contains(active))) {
      event.preventDefault()
      first.focus()
    }
  }

  const retry = () => {
    setState({ status: 'loading' })
    setAttempt((value) => value + 1)
  }

  if (state.status === 'loading') {
    return (
      <div
        ref={rootRef}
        className="reading-focus"
        role={modal ? 'dialog' : undefined}
        aria-modal={modal || undefined}
        aria-label={modal ? 'Reading Focus' : undefined}
        onKeyDown={handleKeyDown}
      >
        <button type="button" className="focus-close" onClick={onClose} aria-label="Close Focus">‹ Back</button>
        <SceneLoading kicker="Reading" />
      </div>
    )
  }

  if (state.status === 'error') {
    return (
      <div
        ref={rootRef}
        className="reading-focus"
        role={modal ? 'dialog' : undefined}
        aria-modal={modal || undefined}
        aria-label={modal ? 'Reading Focus' : undefined}
        onKeyDown={handleKeyDown}
      >
        <button type="button" className="focus-close" onClick={onClose} aria-label="Close Focus">‹ Back</button>
        <SceneUnavailable
          kicker="Reading"
          what="this reading"
          error={state.error}
          onRetry={retry}
        />
      </div>
    )
  }

  const { detail } = state
  const title = detail.title?.trim() || detail.url
  const currentRevision = detail.revisions.find((revision) => revision.is_current)

  const copyMarkdown = async () => {
    setCopyState('copying')
    setActionError(null)
    try {
      if (!navigator.clipboard?.writeText) throw new Error('Clipboard access is unavailable')
      await navigator.clipboard.writeText(detail.markdown)
      setCopyState('copied')
    } catch (cause: unknown) {
      setCopyState('error')
      setActionError(cause instanceof Error ? cause.message : 'Copy failed')
    }
  }

  const downloadMarkdown = async () => {
    setDownloadState('downloading')
    setActionError(null)
    try {
      const download = await api.fetchReadingMarkdown(roomId, readingId)
      const objectUrl = URL.createObjectURL(download.blob)
      const anchor = document.createElement('a')
      anchor.href = objectUrl
      anchor.download = download.filename
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
      // Let the browser consume the synthetic click before releasing the URL;
      // immediate revocation can cancel downloads in WebKit.
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 0)
      setDownloadState('downloaded')
    } catch (cause: unknown) {
      setDownloadState('error')
      setActionError(cause instanceof Error ? cause.message : 'Download failed')
    }
  }

  return (
    <div
      ref={rootRef}
      className="reading-focus"
      role={modal ? 'dialog' : undefined}
      aria-modal={modal || undefined}
      aria-label={modal ? 'Reading Focus' : undefined}
      onKeyDown={handleKeyDown}
    >
      <FocusHeader title={title} kindLabel={`Reading · ${sourceLabel(detail.source)}`} onClose={onClose} />

      <div className="reading-focus-actions" role="group" aria-label="Reading actions">
        <button
          type="button"
          className="btn btn-secondary"
          disabled={copyState === 'copying'}
          onClick={() => { void copyMarkdown() }}
        >
          {copyState === 'copying' ? 'Copying…' : (copyState === 'copied' ? 'Copied exact Markdown' : 'Copy Markdown')}
        </button>
        <button
          type="button"
          className="btn btn-secondary"
          disabled={downloadState === 'downloading'}
          onClick={() => { void downloadMarkdown() }}
        >
          {downloadState === 'downloading' ? 'Downloading…' : (downloadState === 'downloaded' ? 'Download started' : 'Download .md')}
        </button>
        {isHttpUrl(detail.url) ? (
          <a
            className="btn btn-ghost"
            href={detail.url}
            target="_blank"
            rel="noopener noreferrer"
          >
            Open original ↗
          </a>
        ) : (
          <span className="reading-focus-source-unavailable">Original URL is not safe to open</span>
        )}
      </div>
      {actionError && <p className="reading-focus-action-error" role="alert">{actionError}</p>}

      <dl className="reading-focus-metadata" aria-label="Reading metadata">
        <div><dt>Site</dt><dd>{detail.site || 'Not recorded'}</dd></div>
        <div><dt>Author</dt><dd>{detail.author || 'Not recorded'}</dd></div>
        <div><dt>Published</dt><dd>{detail.published || 'Not recorded'}</dd></div>
        <div><dt>Filed</dt><dd><time dateTime={detail.created_at}>{stamp(detail.created_at)}</time></dd></div>
        <div><dt>Current capture</dt><dd>{detail.current_captured_at ? <time dateTime={detail.current_captured_at}>{stamp(detail.current_captured_at)}</time> : 'Legacy entry'}</dd></div>
        <div><dt>Words</dt><dd>{detail.word_count?.toLocaleString() ?? 'Not recorded'}</dd></div>
        <div><dt>Revisions</dt><dd>{detail.revisions.length}</dd></div>
        <div><dt>Mode</dt><dd>{currentRevision ? modeLabel(currentRevision.capture_mode) : 'Legacy entry'}</dd></div>
      </dl>

      <section className="reading-focus-section" aria-labelledby="reading-summary-heading">
        <h3 id="reading-summary-heading">Why it was filed</h3>
        <p className="reading-focus-summary">{detail.summary}</p>
        {detail.key_claims.length > 0 && (
          <ul className="reading-focus-claims" aria-label="Key claims">
            {detail.key_claims.map((claim, index) => <li key={`${index}:${claim}`}>{claim}</li>)}
          </ul>
        )}
      </section>

      {detail.content_sha256 && (
        <section className="reading-focus-section" aria-labelledby="reading-hash-heading">
          <h3 id="reading-hash-heading">Current SHA-256</h3>
          <code className="reading-focus-hash">{detail.content_sha256}</code>
        </section>
      )}

      <section className="reading-focus-section" aria-labelledby="reading-content-heading">
        <h3 id="reading-content-heading">Current Markdown</h3>
        <RenderedMarkdown markdown={detail.markdown} />
      </section>

      <section className="reading-focus-section" aria-labelledby="reading-revisions-heading">
        <h3 id="reading-revisions-heading">Revision history</h3>
        {detail.revisions.length > 0 ? (
          <ol className="reading-revisions" aria-label="Revision history">
            {detail.revisions.map((revision) => <RevisionRow key={revision.id} revision={revision} />)}
          </ol>
        ) : (
          <p className="reading-focus-quiet">
            No browser-capture revisions. This reading predates direct capture.
          </p>
        )}
      </section>
    </div>
  )
}
