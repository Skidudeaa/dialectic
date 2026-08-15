import type { AlertEvent } from '../../types/trading.ts'
import './cockpit.css'

const EMPTY_COPY = 'No transitions in the last push.'

function severityClass(severity?: string): string {
  const s = (severity ?? '').toLowerCase()
  if (s.includes('crit') || s.includes('fired') || s.includes('high')) return 'cockpit-severity--critical'
  if (s.includes('warn') || s.includes('approach') || s.includes('medium')) return 'cockpit-severity--warning'
  return 'cockpit-severity--info'
}

function formatValue(v: unknown): string {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean') return String(v)
  try {
    return JSON.stringify(v)
  } catch {
    return String(v)
  }
}

// Straight from the snapshot — no independent fetch, so no loading/
// unavailable states of its own; the snapshot's own TradingSlice (rendered
// elsewhere) already owns that lifecycle.
export interface AlertEventsListProps {
  events?: AlertEvent[]
}

export function AlertEventsList({ events }: AlertEventsListProps) {
  const rows = events ?? []
  return (
    <section className="cockpit-module" aria-label="Alert events">
      <div className="cockpit-header">
        <span className="cockpit-title" title="State transitions carried by the latest snapshot push">Alert Events</span>
      </div>
      <div className="cockpit-body">
        {rows.length === 0 ? (
          <div className="cockpit-empty-line">{EMPTY_COPY}</div>
        ) : (
          <div className="cockpit-alert-list">
            {rows.map((e, i) => (
              <div className="cockpit-alert-row" key={`${e.node_id ?? 'event'}-${i}`}>
                <span className={`cockpit-severity ${severityClass(e.severity)}`}>
                  {e.severity ?? 'info'}
                </span>
                <span className="cockpit-alert-event-type">{e.event_type ?? 'transition'}</span>
                {e.node_id && <span className="cockpit-alert-node">{e.node_id}</span>}
                <span className="cockpit-alert-values">
                  {formatValue(e.old_value)} → {formatValue(e.new_value)}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  )
}
