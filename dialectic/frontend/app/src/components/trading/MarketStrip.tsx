import type { TradingSlice, Quote } from '../../types/trading.ts'
import './cockpit.css'

// ARCHITECTURE: presentational only — the room-level fetch/poll owns the
// TradingSlice this renders. Three DISTINCT states per the cockpit spec:
// loading (skeleton), unavailable (error line, stale data below it if any),
// empty (one calm line). 'ready' with no data collapses to the same empty
// copy as an explicit 'empty' status — an empty array is still "nothing on
// the wire", not a rendering bug.

function formatPrice(price: number): string {
  if (!Number.isFinite(price)) return '—'
  return Math.abs(price) >= 1 ? price.toFixed(2) : price.toFixed(4)
}

function formatFreshness(fetchedAt?: number): string | null {
  if (!fetchedAt) return null
  const diffMs = Date.now() - fetchedAt
  if (diffMs < 1000) return 'as of just now'
  const seconds = Math.floor(diffMs / 1000)
  if (seconds < 60) return `as of ${seconds}s ago`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `as of ${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  return `as of ${hours}h ago`
}

const EMPTY_COPY = 'No quotes on the wire.'

function QuoteChips({ quotes }: { quotes: Quote[] }) {
  if (quotes.length === 0) return <div className="cockpit-empty-line">{EMPTY_COPY}</div>
  return (
    <div className="cockpit-chip-row">
      {quotes.map((q, i) => (
        <span className="cockpit-chip" key={`${q.symbol}-${q.node_id ?? i}`}>
          <span className="cockpit-chip-symbol">{q.symbol}</span>
          <span className="cockpit-chip-value">{formatPrice(q.price)}</span>
        </span>
      ))}
    </div>
  )
}

export interface MarketStripProps {
  slice: TradingSlice<Quote[]>
  onRefresh?: () => void
}

export function MarketStrip({ slice, onRefresh }: MarketStripProps) {
  const freshness = formatFreshness(slice.fetchedAt)
  return (
    <section className="cockpit-module" aria-label="Market strip">
      <div className="cockpit-header">
        <span className="cockpit-title">Market Strip</span>
        <div className="cockpit-header-right">
          {freshness && <span className="cockpit-freshness">{freshness}</span>}
          {onRefresh && (
            <button type="button" className="cockpit-refresh-btn" onClick={onRefresh}>
              Refresh
            </button>
          )}
        </div>
      </div>
      <div className="cockpit-body">
        {slice.status === 'loading' && (
          <div className="cockpit-skeleton-group">
            <div className="cockpit-skeleton cockpit-skeleton--narrow" />
          </div>
        )}
        {slice.status === 'unavailable' && (
          <>
            <div className="cockpit-error-line">{slice.error ?? 'Quotes unavailable.'}</div>
            {slice.data && slice.data.length > 0 && (
              <>
                <div className="cockpit-stale-note">Stale — last known quotes</div>
                <QuoteChips quotes={slice.data} />
              </>
            )}
          </>
        )}
        {slice.status === 'empty' && <div className="cockpit-empty-line">{EMPTY_COPY}</div>}
        {slice.status === 'ready' && <QuoteChips quotes={slice.data ?? []} />}
      </div>
    </section>
  )
}
