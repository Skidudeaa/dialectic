import { useEffect, useMemo, useRef, useState } from 'react'
import type { ReadingLibraryItem } from '../../../types/index.ts'
import { api } from '../../../lib/api.ts'
import { PARTICIPANT_NAME } from '../../../lib/productIdentity.ts'
import { SceneEmpty, SceneLoading, SceneUnavailable } from '../SceneEmpty'

const SEARCH_DEBOUNCE_MS = 220
const PAGE_SIZE = 50

const SOURCE_LABELS: Record<string, string> = {
  browser_capture: 'Safari capture',
  proposal: 'Accepted proposal',
  human: 'Filed by a person',
  wire: 'Wire',
  night_shift: 'Night shift',
  newsletter: 'Newsletter',
  congress: 'Congress',
}

const CAPTURE_MODE_LABELS: Record<string, string> = {
  selection: 'Selection',
  article: 'Article',
  page_fallback: 'Rendered page fallback',
}

interface LibraryPage {
  key: string
  items: ReadingLibraryItem[]
  nextBefore: string | null
}

interface RequestState {
  key: string
  status: 'loading' | 'ready' | 'error'
  error?: string
}

interface MoreRequestState {
  key: string
  loading: boolean
  error: string | null
}

function dateLabel(value: string | null): string {
  if (!value) return 'Date unavailable'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleDateString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
  })
}

function sourceLabel(value: string): string {
  return SOURCE_LABELS[value] ?? value.replaceAll('_', ' ')
}

function ReadingCard({
  item,
  onOpen,
}: {
  item: ReadingLibraryItem
  onOpen: (readingId: string) => void
}) {
  const title = item.title?.trim() || item.url
  const effectiveAt = item.current_captured_at ?? item.created_at
  const revisionLabel = `${item.revision_count} ${item.revision_count === 1 ? 'revision' : 'revisions'}`

  return (
    <li className="library-card" data-source={item.source}>
      <button
        type="button"
        className="library-card-open"
        onClick={() => onOpen(item.id)}
        aria-label={`Open ${title}`}
      >
        <div className="library-card-head">
          <span className="library-card-title">{title}</span>
          <span className="library-card-revisions">{revisionLabel}</span>
        </div>
        {item.summary && <p className="library-card-summary">{item.summary}</p>}
        <div className="library-card-meta">
          <span>{item.site || 'Site unavailable'}</span>
          {item.author && <span>{item.author}</span>}
          {item.published && <span>Published {item.published}</span>}
        </div>
        <div className="library-card-foot">
          <span>{sourceLabel(item.source)}</span>
          {item.capture_mode && <span>{CAPTURE_MODE_LABELS[item.capture_mode]}</span>}
          <time dateTime={effectiveAt}>{dateLabel(effectiveAt)}</time>
        </div>
      </button>
    </li>
  )
}

/**
 * The room's complete collaborative Library.
 *
 * Unlike the generic workspace projection, this endpoint is searchable,
 * cursor-paginated, and not capped at the newest 50 objects. Selection still
 * goes through App's one navigation writer as `reading:<id>`; this component
 * owns no URL or detail route of its own.
 */
export function LibraryScene({
  roomId,
  onOpen,
  enabled = true,
}: {
  roomId: string
  onOpen: (readingId: string) => void
  enabled?: boolean
}) {
  const [query, setQuery] = useState('')
  const [site, setSite] = useState('')
  const [source, setSource] = useState('')
  const [attempt, setAttempt] = useState(0)
  const [page, setPage] = useState<LibraryPage | null>(null)
  const [request, setRequest] = useState<RequestState>({ key: '', status: 'loading' })
  const [moreRequest, setMoreRequest] = useState<MoreRequestState>({
    key: '', loading: false, error: null,
  })
  const requestSeq = useRef(0)

  const trimmedQuery = query.trim()
  const trimmedSite = site.trim()
  const filterKey = JSON.stringify([roomId, trimmedQuery, trimmedSite, source])
  const currentPage = page?.key === filterKey ? page : null
  const currentRequest = request.key === filterKey ? request : null
  const currentMoreRequest = moreRequest.key === filterKey ? moreRequest : null
  const loadingMore = currentMoreRequest?.loading === true
  const moreError = currentMoreRequest?.error ?? null

  useEffect(() => {
    if (!enabled) return
    const seq = ++requestSeq.current
    let cancelled = false
    const timer = window.setTimeout(() => {
      setRequest({ key: filterKey, status: 'loading' })
      setMoreRequest({ key: filterKey, loading: false, error: null })
      void api.getReadingLibrary(roomId, {
        q: trimmedQuery,
        site: trimmedSite,
        source,
        limit: PAGE_SIZE,
      }).then((result) => {
        if (cancelled || seq !== requestSeq.current) return
        setPage({ key: filterKey, items: result.items, nextBefore: result.next_before })
        setRequest({ key: filterKey, status: 'ready' })
      }).catch((cause: unknown) => {
        if (cancelled || seq !== requestSeq.current) return
        setRequest({
          key: filterKey,
          status: 'error',
          error: cause instanceof Error ? cause.message : 'Could not read the Library',
        })
      })
    }, SEARCH_DEBOUNCE_MS)

    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [attempt, enabled, filterKey, roomId, source, trimmedQuery, trimmedSite])

  const knownSites = useMemo(
    () => [...new Set(
      (currentPage?.items ?? [])
        .map((item) => item.site)
        .filter((value): value is string => Boolean(value)),
    )].sort(),
    [currentPage],
  )
  const knownSources = useMemo(() => {
    const values = new Set([...Object.keys(SOURCE_LABELS), source])
    for (const item of currentPage?.items ?? []) values.add(item.source)
    values.delete('')
    return [...values].sort((a, b) => sourceLabel(a).localeCompare(sourceLabel(b)))
  }, [currentPage, source])

  const hasFilters = Boolean(trimmedQuery || trimmedSite || source)
  const clearFilters = () => {
    setQuery('')
    setSite('')
    setSource('')
  }
  const retry = () => {
    setRequest({ key: filterKey, status: 'loading' })
    setAttempt((value) => value + 1)
  }

  const loadMore = async () => {
    if (!currentPage?.nextBefore || loadingMore) return
    const key = filterKey
    const generation = requestSeq.current
    let error: string | null = null
    setMoreRequest({ key, loading: true, error: null })
    try {
      const result = await api.getReadingLibrary(roomId, {
        q: trimmedQuery,
        site: trimmedSite,
        source,
        limit: PAGE_SIZE,
        before: currentPage.nextBefore,
      })
      if (generation !== requestSeq.current) return
      setPage((existing) => {
        if (!existing || existing.key !== key) return existing
        const seen = new Set(existing.items.map((item) => item.id))
        const additions = result.items.filter((item) => !seen.has(item.id))
        return {
          key,
          items: [...existing.items, ...additions],
          nextBefore: result.next_before,
        }
      })
    } catch (cause: unknown) {
      if (generation !== requestSeq.current) return
      error = cause instanceof Error ? cause.message : 'Could not load more readings'
    } finally {
      if (generation === requestSeq.current) {
        setMoreRequest({ key, loading: false, error })
      }
    }
  }

  let resultSurface
  if (!enabled) {
    resultSurface = (
      <SceneEmpty kicker="Library" headline="Sign in to open the Library.">
        <p>
          Guest room access carries no account identity. The collaborative
          Library needs a signed-in room member so its sources stay room-fenced.
        </p>
      </SceneEmpty>
    )
  } else if (!currentPage && currentRequest?.status === 'error') {
    resultSurface = (
      <SceneUnavailable
        kicker="Library"
        what="Library"
        error={currentRequest.error}
        onRetry={retry}
      />
    )
  } else if (!currentPage) {
    resultSurface = <SceneLoading kicker="Library" />
  } else if (currentPage.items.length === 0 && hasFilters) {
    resultSurface = (
      <SceneEmpty
        kicker="Library"
        headline="No filed readings match."
        action={(
          <button type="button" className="btn btn-secondary" onClick={clearFilters}>
            Clear filters
          </button>
        )}
      >
        <p>The search and exact filters returned no sources in this room.</p>
      </SceneEmpty>
    )
  } else if (currentPage.items.length === 0) {
    resultSurface = (
      <SceneEmpty kicker="Library" headline="Nothing filed here yet.">
        <p>
          The Library holds sources this room has actually kept — the article
          behind a claim, with where it came from and why it mattered.
        </p>
        <p>
          Paste a link and {PARTICIPANT_NAME} can offer it for your Accept.
          The Wire and overnight reading file relevant sources directly, while
          Somacura Capture files the exact rendered Markdown from Safari.
          Every row here is already durable evidence, not a suggestion.
        </p>
      </SceneEmpty>
    )
  } else {
    resultSurface = (
      <>
        <ul className="library-list" aria-label="Filed readings">
          {currentPage.items.map((item) => (
            <ReadingCard key={item.id} item={item} onOpen={onOpen} />
          ))}
        </ul>
        {currentPage.nextBefore && (
          <div className="library-more">
            <button
              type="button"
              className="btn btn-secondary"
              disabled={loadingMore}
              onClick={() => { void loadMore() }}
            >
              {loadingMore ? 'Loading more…' : (moreError ? 'Try loading more' : 'Load more')}
            </button>
            {moreError && <p className="library-status is-error">{moreError}</p>}
          </div>
        )}
      </>
    )
  }

  return (
    <div
      className="scene-body library-scene-body"
      aria-busy={enabled && (!currentPage || currentRequest?.status === 'loading')}
    >
      {enabled && <section className="library-toolbar" aria-label="Library search and filters">
        <label className="library-filter library-filter-search">
          <span>Search</span>
          <input
            type="search"
            className="form-input"
            value={query}
            maxLength={500}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search title, summary, and Markdown…"
            aria-label="Search readings"
          />
        </label>
        <label className="library-filter">
          <span>Site</span>
          <input
            type="search"
            className="form-input"
            value={site}
            maxLength={500}
            onChange={(event) => setSite(event.target.value)}
            placeholder="Exact site"
            list="library-site-options"
          />
          <datalist id="library-site-options">
            {knownSites.map((value) => <option key={value} value={value} />)}
          </datalist>
        </label>
        <label className="library-filter">
          <span>Source</span>
          <select
            className="form-input"
            value={source}
            onChange={(event) => setSource(event.target.value)}
          >
            <option value="">All sources</option>
            {knownSources.map((value) => (
              <option key={value} value={value}>{sourceLabel(value)}</option>
            ))}
          </select>
        </label>
        {hasFilters && (
          <button type="button" className="btn btn-ghost library-clear" onClick={clearFilters}>
            Clear
          </button>
        )}
      </section>}

      {currentPage && currentRequest?.status === 'loading' && (
        <p className="library-status" role="status">Updating the Library…</p>
      )}
      {currentPage && currentRequest?.status === 'error' && (
        <div className="library-inline-error" role="alert">
          <span>{currentRequest.error}</span>
          <button type="button" className="btn btn-secondary btn-sm" onClick={retry}>
            Try again
          </button>
        </div>
      )}
      {resultSurface}
    </div>
  )
}
