import type { DailyActivity, DailyActivityRow } from '../surfaceModel'
import './shapes.css'

export interface ShapeSignalProps {
  activity: DailyActivity | null
  status: 'loading' | 'ready' | 'unavailable'
  error?: string
  /** null = unknown */
  annotatorEnabled: boolean | null
  addressedOnly: boolean | null
}

/** The experiment's own stated window — also the fallback day count before
 *  the first fetch resolves. */
const DEFAULT_DAYS = 14

function formatDay(iso: string): string {
  const when = new Date(iso)
  if (Number.isNaN(when.getTime())) return iso
  return when.toLocaleDateString([], { month: 'short', day: 'numeric' })
}

interface Segment {
  key: string
  value: number
  fill: string
}

function segmentsFor(row: DailyActivityRow): Segment[] {
  return [
    { key: 'human', value: row.human, fill: 'url(#surf-signal-human)' },
    { key: 'llm_primary', value: row.llm_primary, fill: 'url(#surf-signal-primary)' },
    { key: 'llm_provoker', value: row.llm_provoker, fill: 'url(#surf-signal-provoker)' },
    { key: 'llm_annotator', value: row.llm_annotator, fill: 'url(#surf-signal-annotator)' },
  ]
}

const CHART_TOP = 5
const CHART_H = 100
const VIEW_W = 320

function VolumeChart({ rows }: { rows: DailyActivityRow[] }) {
  const maxTotal = Math.max(1, ...rows.map((r) => r.human + r.llm_primary + r.llm_provoker + r.llm_annotator))
  const slot = rows.length > 0 ? (VIEW_W - 20) / rows.length : VIEW_W - 20
  const barW = Math.max(2, slot - 2)
  const first = rows[0]
  const last = rows[rows.length - 1]

  return (
    <svg className="surf-signal-chart" viewBox={`0 0 ${VIEW_W} 130`} role="img" aria-label="Volume, last days">
      <defs>
        <pattern id="surf-signal-human" width="4" height="4" patternUnits="userSpaceOnUse">
          <rect width="4" height="4" fill="var(--color-bone)" />
        </pattern>
        <pattern id="surf-signal-primary" width="5" height="5" patternUnits="userSpaceOnUse">
          <rect width="5" height="5" fill="var(--color-well)" />
          <path d="M-1 5 L5 -1 M2 7 L7 2" stroke="var(--color-bone)" strokeWidth="1.25" />
        </pattern>
        <pattern id="surf-signal-provoker" width="6" height="6" patternUnits="userSpaceOnUse">
          <rect width="6" height="6" fill="var(--color-well)" />
          <path d="M0 0 L6 6 M6 0 L0 6" stroke="var(--color-bone)" strokeWidth="1" />
        </pattern>
        <pattern id="surf-signal-annotator" width="6" height="6" patternUnits="userSpaceOnUse">
          <rect width="6" height="6" fill="var(--color-well)" />
          <circle cx="3" cy="3" r="1.25" fill="var(--color-bone)" />
        </pattern>
      </defs>
      {rows.map((row, i) => {
        const x = 10 + i * slot + (slot - barW) / 2
        const dialecticTotal = row.llm_primary + row.llm_provoker + row.llm_annotator
        const title = `${formatDay(row.day)} · human ${row.human} · Dialectic ${dialecticTotal}`
        let cum = 0
        return (
          <g key={row.day}>
            {segmentsFor(row).map((seg) => {
              if (seg.value <= 0) return null
              const h = (seg.value / maxTotal) * CHART_H
              const y = CHART_TOP + CHART_H - cum - h
              cum += h
              return (
                <rect key={seg.key} x={x} y={y} width={barW} height={h} fill={seg.fill}>
                  <title>{title}</title>
                </rect>
              )
            })}
          </g>
        )
      })}
      {first && (
        <text x={10} y={124} className="surf-signal-day-label" textAnchor="start">{formatDay(first.day)}</text>
      )}
      {last && last !== first && (
        <text x={VIEW_W - 10} y={124} className="surf-signal-day-label" textAnchor="end">{formatDay(last.day)}</text>
      )}
    </svg>
  )
}

function sum(rows: DailyActivityRow[], key: keyof Omit<DailyActivityRow, 'day'>): number {
  return rows.reduce((acc, r) => acc + r[key], 0)
}

function annotatorLine(annotatorEnabled: boolean | null): string {
  if (annotatorEnabled === null) return 'Annotator: unknown'
  return annotatorEnabled ? 'Annotator speaking' : 'Annotator silent · writes marks only'
}

function addressedLine(addressedOnly: boolean | null): string {
  if (addressedOnly === null) return 'Dialectic: unknown'
  return addressedOnly ? 'Dialectic speaks when addressed or a gate fires' : 'Dialectic joins on its own judgment'
}

/**
 * The one instrument that looks at the room from outside rather than
 * inside it — the volume behind the enjoyment experiment (see the
 * 2026-09-02 amendment: scarce voice, one move a day), so the room can see
 * whether it moved.
 */
export function ShapeSignal({ activity, status, error, annotatorEnabled, addressedOnly }: ShapeSignalProps) {
  const days = activity?.days ?? DEFAULT_DAYS
  const rows = activity?.rows ?? []
  const totalHuman = sum(rows, 'human')
  const totalPrimary = sum(rows, 'llm_primary')
  const totalProvoker = sum(rows, 'llm_provoker')
  const totalAnnotator = sum(rows, 'llm_annotator')
  const totalMachine = totalPrimary + totalProvoker + totalAnnotator
  const ratio = totalHuman > 0 ? (totalMachine / totalHuman).toFixed(1) : '—'

  return (
    <section className="surf-signal">
      <h3 className="surf-signal-title">VOLUME, LAST {days} DAYS</h3>

      {status === 'loading' && <p className="surf-signal-loading">reading the last {days} days…</p>}
      {status === 'unavailable' && <p className="surf-signal-error">{error}</p>}
      {status === 'ready' && (
        <>
          <VolumeChart rows={rows} />
          <div className="surf-signal-legend" aria-label="Chart patterns">
            <span><i className="surf-signal-key surf-signal-key--human" aria-hidden="true" />human</span>
            <span><i className="surf-signal-key surf-signal-key--primary" aria-hidden="true" />Dialectic</span>
            <span><i className="surf-signal-key surf-signal-key--provoker" aria-hidden="true" />provoker</span>
            <span><i className="surf-signal-key surf-signal-key--annotator" aria-hidden="true" />annotator</span>
          </div>
          <table className="surf-signal-totals">
            <thead>
              <tr><th>humans</th><th>Dialectic</th><th>provoker</th><th>annotator</th></tr>
            </thead>
            <tbody>
              <tr>
                <td>{totalHuman}</td>
                <td>{totalPrimary}</td>
                <td>{totalProvoker}</td>
                <td>{totalAnnotator}</td>
              </tr>
            </tbody>
          </table>
          <p className="surf-signal-ratio">machine : human = {ratio} : 1</p>
        </>
      )}

      <div className="surf-signal-experiment">
        <div className="surf-signal-experiment-title">THE EXPERIMENT</div>
        <p>{annotatorLine(annotatorEnabled)}</p>
        <p>{addressedLine(addressedOnly)}</p>
        <p className="surf-signal-measure">
          Two weeks. One number: human messages per day. If it does not move, the volume was never the problem.
        </p>
      </div>
    </section>
  )
}
