import { useEffect, useState } from 'react'
import { api } from '../../lib/api'
import { useAppStore } from '../../stores/appStore'
import type { Portfolio } from '../../types/trading'
import '../stakes/CommitmentDashboard.css'
import './TrackRecordPanel.css'

/**
 * The Track Record — the claims ledger's scoreboard, in the Ledger scene.
 *
 * One App rules (merge decision 4): the desk computes Brier/BSS and the
 * per-source leaderboard; this panel is dialectic's ONLY analytics surface
 * for them — td gets no duplicated CalibrationPanel. Reads ride the trading
 * relay (room-scoped), so an unbound room answers 409 and the panel stays
 * silent rather than alarming: the Ledger's dossier entries are still the
 * scene's first citizens.
 *
 * The 10-bucket bars reuse CommitmentDashboard's CalibrationPoint SHAPE and
 * its .calibration-section styles — deliberately the same visual language,
 * without touching that component.
 */

/** CommitmentDashboard.tsx's CalibrationPoint shape, reused verbatim. */
interface CalibrationPoint {
  confidence: number
  accuracy: number
}

interface CalibrationBucket {
  bucket?: string
  midpoint: number
  total: number
  accuracy: number | null
}

interface CalibrationSummary {
  calibration?: CalibrationBucket[]
  total_predictions?: number
  brier_score?: number | null
  brier_skill_score?: number | null
  bss?: number | null
  bss_vs?: string
  ref_brier?: number | null
}

interface LeaderboardRow {
  group?: string
  n?: number
  brier?: number | null
  bss?: number | null
  bss_vs?: string
  accuracy?: number | null
  bias?: number | null
  provenance?: string
}

type PanelState =
  | { status: 'loading' }
  | { status: 'hidden' }
  | { status: 'empty' }
  | {
      status: 'ready'
      calibration: CalibrationSummary
      leaderboard: LeaderboardRow[]
      portfolio: Portfolio | null
    }

function leaderboardRows(data: unknown): LeaderboardRow[] {
  if (Array.isArray(data)) return data as LeaderboardRow[]
  const rows = (data as { rows?: unknown })?.rows
  return Array.isArray(rows) ? (rows as LeaderboardRow[]) : []
}

export function TrackRecordPanel() {
  const roomId = useAppStore((s) => s.currentRoom?.id ?? null)
  // Settled result, stamped with the room it answers for — a room switch
  // derives back to loading instead of flashing the previous room's board.
  const [settled, setSettled] = useState<{ roomId: string; state: PanelState } | null>(null)

  useEffect(() => {
    if (!roomId) return
    let cancelled = false
    Promise.all([
      api.getTradingCalibration(roomId),
      api.getTradingLeaderboard(roomId, 'source_label'),
      // The equity curve is garnish here, not the meal: a failed portfolio
      // read must not hide the scoreboard, so it degrades to null alone.
      api.getTradingPortfolio(roomId).catch(() => null),
    ])
      .then(([calibrationData, leaderboardData, portfolioData]) => {
        if (cancelled) return
        const calibration = (calibrationData ?? {}) as CalibrationSummary
        const leaderboard = leaderboardRows(leaderboardData)
        const state: PanelState =
          !(calibration.total_predictions ?? 0) && leaderboard.length === 0
            ? { status: 'empty' }
            : { status: 'ready', calibration, leaderboard, portfolio: portfolioData }
        setSettled({ roomId, state })
      })
      .catch(() => {
        // 409 = unbound room (no cockpit, no ledger view); anything else =
        // desk down. Both are "not now", never an error banner in the Ledger.
        if (!cancelled) setSettled({ roomId, state: { status: 'hidden' } })
      })
    return () => {
      cancelled = true
    }
  }, [roomId])

  if (!roomId) return null
  const state: PanelState =
    settled && settled.roomId === roomId ? settled.state : { status: 'loading' }

  if (state.status === 'hidden') return null
  if (state.status === 'loading') {
    return (
      <div className="track-record-panel" data-testid="track-record-loading">
        <h3>Track Record</h3>
        <div className="track-record-quiet">Reading the ledger…</div>
      </div>
    )
  }
  if (state.status === 'empty') {
    return (
      <div className="track-record-panel" data-testid="track-record-empty">
        <h3>Track Record</h3>
        <div className="track-record-quiet">
          No scored predictions yet. Resolve one and the scoreboard starts.
        </div>
      </div>
    )
  }

  const { calibration, leaderboard, portfolio } = state
  const points: CalibrationPoint[] = (calibration.calibration ?? [])
    .filter((bucket) => bucket.accuracy !== null && bucket.total > 0)
    .map((bucket) => ({ confidence: bucket.midpoint, accuracy: bucket.accuracy as number }))
  const brier = calibration.brier_score
  const bss = calibration.brier_skill_score ?? calibration.bss

  // Equity vs unitized SPY, joined on mark_date — only dates BOTH series
  // hold draw, so a mark before the first deposit (no benchmark units yet)
  // cannot bend the comparison. Null-safe throughout: no portfolio, no line.
  const spyByDate = new Map(
    (portfolio?.spy_baseline ?? []).map((b) => [b.mark_date, b.value]),
  )
  const sparkPoints = (portfolio?.marks ?? [])
    .filter((m) => typeof m.equity === 'number' && spyByDate.has(m.mark_date))
    .map((m) => ({ equity: m.equity, benchmark: spyByDate.get(m.mark_date) as number }))

  return (
    <div className="track-record-panel" data-testid="track-record-panel">
      <h3>Track Record</h3>
      <div className="track-record-headline">
        <span>{calibration.total_predictions ?? 0} resolved</span>
        {typeof brier === 'number' && <span>Brier {brier.toFixed(2)}</span>}
        {typeof bss === 'number' && (
          <span>
            BSS {bss >= 0 ? '+' : ''}{bss.toFixed(2)}
            {calibration.bss_vs && (
              <span className="track-record-vs"> vs {calibration.bss_vs}</span>
            )}
          </span>
        )}
      </div>

      {leaderboard.length > 0 && (
        <div className="track-record-table-wrap">
          <table className="track-record-table">
            <thead>
              <tr>
                <th>Source</th>
                <th>n</th>
                <th>Brier</th>
                <th>BSS</th>
                <th>Acc</th>
                <th>Bias</th>
              </tr>
            </thead>
            <tbody>
              {leaderboard.map((row, i) => (
                <tr key={row.group ?? i}>
                  <td>
                    {row.group ?? '—'}
                    {row.provenance && row.provenance !== 'EMPIRICAL' && (
                      <span
                        className="track-record-unverified"
                        title={row.provenance}
                      >
                        {' '}·
                      </span>
                    )}
                  </td>
                  <td>{row.n ?? '—'}</td>
                  <td>{typeof row.brier === 'number' ? row.brier.toFixed(2) : '—'}</td>
                  <td>
                    {typeof row.bss === 'number'
                      ? `${row.bss >= 0 ? '+' : ''}${row.bss.toFixed(2)}`
                      : '—'}
                    {row.bss_vs && <span className="track-record-vs"> {row.bss_vs}</span>}
                  </td>
                  <td>
                    {typeof row.accuracy === 'number'
                      ? `${Math.round(row.accuracy * 100)}%`
                      : '—'}
                  </td>
                  <td>
                    {typeof row.bias === 'number'
                      ? `${row.bias >= 0 ? '+' : ''}${row.bias.toFixed(2)}`
                      : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {points.length > 0 && (
        <div className="calibration-section">
          <h4>Calibration</h4>
          <div className="track-record-buckets">
            {points.map((point) => (
              <div
                key={point.confidence}
                className="track-record-bucket"
                title={`${Math.round(point.confidence * 100)}% confident → ${Math.round(point.accuracy * 100)}% correct`}
              >
                <div
                  className="track-record-bar"
                  style={{ height: `${Math.max(4, point.accuracy * 100)}%` }}
                />
                <span>{Math.round(point.confidence * 100)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Equity vs SPY (dashed) off the relay's portfolio read — the
          unitized benchmark, price-return-only on both sides. Renders
          nothing until two marks exist; a curve needs two points. */}
      <EquitySparkline points={sparkPoints} />
    </div>
  )
}

/** SVG equity-vs-SPY sparkline. Renders nothing without two real marks. */
export function EquitySparkline({
  points,
}: {
  points: { equity: number; benchmark: number }[]
}) {
  if (points.length < 2) return null
  const w = 280
  const h = 60
  const values = points.flatMap((p) => [p.equity, p.benchmark])
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  const x = (i: number) => (i / (points.length - 1)) * w
  const y = (v: number) => h - ((v - min) / span) * h
  const path = (pick: (p: { equity: number; benchmark: number }) => number) =>
    points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${x(i)} ${y(pick(p))}`).join(' ')
  return (
    <svg
      className="track-record-sparkline"
      width={w}
      height={h}
      viewBox={`0 0 ${w} ${h}`}
      data-testid="track-record-sparkline"
    >
      <path d={path((p) => p.benchmark)} fill="none" stroke="var(--text-ghost)" strokeWidth={1} strokeDasharray="4 3" />
      <path d={path((p) => p.equity)} fill="none" stroke="var(--claude-primary)" strokeWidth={1.5} />
    </svg>
  )
}
