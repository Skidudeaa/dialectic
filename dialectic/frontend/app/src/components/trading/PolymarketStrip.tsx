import { useState } from 'react'
import type { TradingSlice, PolymarketOdd } from '../../types/trading.ts'
import './cockpit.css'

// Same three-state grammar as MarketStrip — see that file's header comment.

function prettifySlug(slug: string): string {
  return slug
    .split('-')
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}

/** Defensive: `probability` may arrive 0–1 (the desk's native scale) or
 * already 0–100 depending on the market source. Values above 1 are treated
 * as already-percent rather than multiplied again. */
function formatProbability(p: number): string {
  if (!Number.isFinite(p)) return '—'
  const pct = p > 1 ? p : p * 100
  return `${pct.toFixed(1)}%`
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

const EMPTY_COPY = 'No Polymarket bindings.'

type TickDir = 'up' | 'down' | 'flat'

const TICK_GLYPH: Record<TickDir, string> = { up: '▲', down: '▼', flat: '◆' }

function OddsChips({ odds }: { odds: PolymarketOdd[] }) {
  // Same tick-flash grammar as MarketStrip: directions come from comparing
  // this slice against the previously rendered one (adjust-state-during-
  // render), and the arrow glyph pairs with the hue — never hue alone.
  const [prev, setPrev] = useState<{ src: PolymarketOdd[]; dirs: Map<string, TickDir> }>({
    src: odds,
    dirs: new Map(),
  })
  if (prev.src !== odds) {
    const before = new Map(prev.src.map((o) => [o.slug, o.probability]))
    const dirs = new Map<string, TickDir>()
    for (const o of odds) {
      const b = before.get(o.slug)
      dirs.set(o.slug, b === undefined || b === o.probability ? 'flat' : o.probability > b ? 'up' : 'down')
    }
    setPrev({ src: odds, dirs })
  }
  const dirs = prev.src === odds ? prev.dirs : new Map<string, TickDir>()
  if (odds.length === 0) return <div className="cockpit-empty-line">{EMPTY_COPY}</div>
  return (
    <div className="cockpit-chip-row">
      {odds.map((o, i) => {
        const dir = dirs.get(o.slug) ?? 'flat'
        return (
          <span className="cockpit-chip" key={`${o.slug}-${i}`}>
            <span className={`cockpit-chip-tick cockpit-chip-tick--${dir}`} aria-hidden="true">
              {TICK_GLYPH[dir]}
            </span>
            <span className="cockpit-chip-symbol">{prettifySlug(o.slug)}</span>
            <span
              key={o.probability}
              className={dir === 'flat' ? 'cockpit-chip-value' : `cockpit-chip-value cockpit-chip-value--${dir}`}
            >
              {formatProbability(o.probability)}
            </span>
          </span>
        )
      })}
    </div>
  )
}

export interface PolymarketStripProps {
  slice: TradingSlice<PolymarketOdd[]>
}

export function PolymarketStrip({ slice }: PolymarketStripProps) {
  const freshness = formatFreshness(slice.fetchedAt)
  return (
    <section className="cockpit-module" aria-label="Polymarket strip">
      <div className="cockpit-header">
        <span className="cockpit-title" title="Prediction-market odds bound to this thesis">Polymarket</span>
        <div className="cockpit-header-right">
          {slice.status === 'ready' && (
            <span className="cockpit-live">
              <span className="cockpit-live-lamp" aria-hidden="true" />
              Live
            </span>
          )}
          {freshness && <span className="cockpit-freshness">{freshness}</span>}
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
            <div className="cockpit-error-line">{slice.error ?? 'Polymarket odds unavailable.'}</div>
            {slice.data && slice.data.length > 0 && (
              <>
                <div className="cockpit-stale-note">Stale — last known odds</div>
                <OddsChips odds={slice.data} />
              </>
            )}
          </>
        )}
        {slice.status === 'empty' && <div className="cockpit-empty-line">{EMPTY_COPY}</div>}
        {slice.status === 'ready' && <OddsChips odds={slice.data ?? []} />}
      </div>
    </section>
  )
}
