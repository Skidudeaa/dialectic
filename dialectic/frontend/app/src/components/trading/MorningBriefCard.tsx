import type { TradingSlice, MorningBrief } from '../../types/trading.ts'
import './cockpit.css'

const EMPTY_COPY = 'No brief for this book yet.'

export interface MorningBriefCardProps {
  slice: TradingSlice<MorningBrief>
}

export function MorningBriefCard({ slice }: MorningBriefCardProps) {
  return (
    <section className="cockpit-module" aria-label="Morning brief">
      <div className="cockpit-header">
        <span className="cockpit-title">Morning Brief</span>
      </div>
      <div className="cockpit-body">
        {slice.status === 'loading' && (
          <div className="cockpit-skeleton-group">
            <div className="cockpit-skeleton cockpit-skeleton--wide" />
            <div className="cockpit-skeleton cockpit-skeleton--wide" />
            <div className="cockpit-skeleton cockpit-skeleton--narrow" />
          </div>
        )}
        {slice.status === 'unavailable' && (
          <>
            <div className="cockpit-error-line">{slice.error ?? 'Brief unavailable.'}</div>
            {slice.data?.brief && (
              <>
                <div className="cockpit-stale-note">Stale — last known brief</div>
                <pre className="cockpit-pre">{slice.data.brief}</pre>
              </>
            )}
          </>
        )}
        {slice.status === 'empty' && <div className="cockpit-empty-line">{EMPTY_COPY}</div>}
        {slice.status === 'ready' &&
          (slice.data?.brief ? (
            <pre className="cockpit-pre">{slice.data.brief}</pre>
          ) : (
            <div className="cockpit-empty-line">{EMPTY_COPY}</div>
          ))}
      </div>
    </section>
  )
}
