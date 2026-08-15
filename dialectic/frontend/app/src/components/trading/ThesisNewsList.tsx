import type { TradingSlice, ThesisNews, NewsItem } from '../../types/trading.ts'
import './cockpit.css'

const EMPTY_COPY = 'No news for this thesis.'

/** GDELT's seendate is a compact YYYYMMDDTHHMMSSZ string. Parsed
 * defensively — an unrecognized shape is shown verbatim rather than
 * dropped, since a raw string still tells the reader something. */
function formatSeendate(seendate?: string): string | null {
  if (!seendate) return null
  const m = /^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z?$/.exec(seendate)
  if (!m) return seendate
  const [, y, mo, d, h, mi] = m
  return `${y}-${mo}-${d} ${h}:${mi} UTC`
}

function ArticleList({ articles }: { articles: NewsItem[] }) {
  return (
    <div className="cockpit-news-list">
      {articles.map((a, i) => (
        <div className="cockpit-news-item" key={`${a.url}-${i}`}>
          <a className="cockpit-news-link" href={a.url} target="_blank" rel="noopener noreferrer">
            {a.title}
          </a>
          <span className="cockpit-news-meta">
            {a.domain ?? 'unknown source'}
            {formatSeendate(a.seendate) && ` · ${formatSeendate(a.seendate)}`}
          </span>
        </div>
      ))}
    </div>
  )
}

function NewsBody({ news }: { news: ThesisNews }) {
  const articles = news.articles ?? []
  if (articles.length === 0) {
    // A present note explains WHY there's nothing (e.g. "no gdelt config")
    // — show it verbatim rather than a generic line that would hide it.
    return <div className="cockpit-empty-line">{news.note ?? EMPTY_COPY}</div>
  }
  return <ArticleList articles={articles} />
}

export interface ThesisNewsListProps {
  slice: TradingSlice<ThesisNews>
}

export function ThesisNewsList({ slice }: ThesisNewsListProps) {
  return (
    <section className="cockpit-module" aria-label="Thesis news">
      <div className="cockpit-header">
        <span className="cockpit-title" title="Fresh GDELT headlines matched to this book's query">Thesis News</span>
      </div>
      <div className="cockpit-body">
        {slice.status === 'loading' && (
          <div className="cockpit-skeleton-group">
            <div className="cockpit-skeleton cockpit-skeleton--wide" />
            <div className="cockpit-skeleton cockpit-skeleton--wide" />
          </div>
        )}
        {slice.status === 'unavailable' && (
          <>
            <div className="cockpit-error-line">{slice.error ?? 'News unavailable.'}</div>
            {slice.data && (slice.data.articles?.length ?? 0) > 0 && (
              <>
                <div className="cockpit-stale-note">Stale — last known headlines</div>
                <ArticleList articles={slice.data.articles} />
              </>
            )}
          </>
        )}
        {slice.status === 'empty' && <div className="cockpit-empty-line">{EMPTY_COPY}</div>}
        {slice.status === 'ready' && (slice.data ? <NewsBody news={slice.data} /> : <div className="cockpit-empty-line">{EMPTY_COPY}</div>)}
      </div>
    </section>
  )
}
