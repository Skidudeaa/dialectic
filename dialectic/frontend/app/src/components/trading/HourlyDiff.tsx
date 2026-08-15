import type { TradingSlice, ThesisDiff } from '../../types/trading.ts'
import './cockpit.css'

const EMPTY_COPY = 'No changes in the last hour.'

/** Compact key: value rendering for the diff's Record<string, unknown>
 * fields — shapes vary by change type, so this stays defensive rather than
 * assuming a schema. */
function compactValue(v: unknown): string {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean') return String(v)
  try {
    const s = JSON.stringify(v)
    return s.length > 80 ? `${s.slice(0, 77)}...` : s
  } catch {
    return String(v)
  }
}

function CompactRecord({ label, record }: { label: string; record: Record<string, unknown> }) {
  const entries = Object.entries(record ?? {})
  if (entries.length === 0) return null
  return (
    <>
      {entries.map(([k, v]) => (
        <div className="cockpit-diff-compact" key={`${label}-${k}`}>
          <span className="cockpit-diff-compact-key">{label}.{k}</span>
          {compactValue(v)}
        </div>
      ))}
    </>
  )
}

function DiffBody({ diff }: { diff: ThesisDiff }) {
  if (!diff.hasChanges) {
    return <div className="cockpit-empty-line">{EMPTY_COPY}</div>
  }

  const hasNewOrRemoved = (diff.newNodes?.length ?? 0) > 0 || (diff.removedNodes?.length ?? 0) > 0

  return (
    <div className="cockpit-diff-list">
      {diff.stateChanges?.map((c, i) => (
        <div className="cockpit-diff-line" key={`state-${c.nodeId ?? i}`}>
          <span className="cockpit-diff-node">{c.nodeId ?? 'node'}:</span>
          <span className="cockpit-diff-old">{c.old ?? '—'}</span>
          <span className="cockpit-diff-arrow">→</span>
          <span className="cockpit-diff-new">{c.new ?? '—'}</span>
        </div>
      ))}
      <CompactRecord label="confluence" record={diff.confluenceChanges} />
      <CompactRecord label="market" record={diff.marketChanges} />
      <CompactRecord label="scenario" record={diff.scenarioChanges} />
      <CompactRecord label="portfolio" record={diff.portfolioChanges} />
      {hasNewOrRemoved && (
        <div className="cockpit-diff-compact">
          <span className="cockpit-diff-compact-key">nodes</span>
          {(diff.newNodes?.length ?? 0) > 0 && `+${diff.newNodes!.length} new`}
          {(diff.newNodes?.length ?? 0) > 0 && (diff.removedNodes?.length ?? 0) > 0 && ', '}
          {(diff.removedNodes?.length ?? 0) > 0 && `-${diff.removedNodes!.length} removed`}
        </div>
      )}
      {diff.countdownChanges && diff.countdownChanges.length > 0 && (
        <div className="cockpit-diff-compact">
          <span className="cockpit-diff-compact-key">countdowns</span>
          {diff.countdownChanges.length} shifted
        </div>
      )}
    </div>
  )
}

export interface HourlyDiffProps {
  slice: TradingSlice<ThesisDiff>
}

export function HourlyDiff({ slice }: HourlyDiffProps) {
  return (
    <section className="cockpit-module" aria-label="Hourly diff">
      <div className="cockpit-header">
        <span className="cockpit-title">Hourly Diff</span>
      </div>
      <div className="cockpit-body">
        {slice.status === 'loading' && (
          <div className="cockpit-skeleton-group">
            <div className="cockpit-skeleton cockpit-skeleton--wide" />
          </div>
        )}
        {slice.status === 'unavailable' && (
          <>
            <div className="cockpit-error-line">{slice.error ?? 'Diff unavailable.'}</div>
            {slice.data && (
              <>
                <div className="cockpit-stale-note">Stale — last known diff</div>
                <DiffBody diff={slice.data} />
              </>
            )}
          </>
        )}
        {slice.status === 'empty' && <div className="cockpit-empty-line">{EMPTY_COPY}</div>}
        {slice.status === 'ready' && (slice.data ? <DiffBody diff={slice.data} /> : <div className="cockpit-empty-line">{EMPTY_COPY}</div>)}
      </div>
    </section>
  )
}
