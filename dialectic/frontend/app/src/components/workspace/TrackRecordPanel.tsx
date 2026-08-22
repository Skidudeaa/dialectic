import { useEffect, useState } from 'react'
import { api } from '../../lib/api'
import { useAppStore } from '../../stores/appStore'
import type { Portfolio } from '../../types/trading'
import { Explain } from '../common/Explain'
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

/**
 * The panel's own name for itself, shown in every state that draws the board.
 *
 * WHY one constant and not the sentence written twice: the empty state is the
 * one most readers meet first — production has scored nothing at all — so it
 * must carry the same orientation as the populated one, and two copies of a
 * sentence are two sentences that drift.
 */
/*
 * TWO THINGS THIS SENTENCE MUST NOT SAY, both traced end to end before it was
 * rewritten. Neither is a nicety; both were in the first draft and both were
 * false in exactly the way the capabilities doctrine exists to prevent.
 *
 * NOT "this room's". The panel is DESK-WIDE and every room renders identical
 * numbers. `api/trading_relay.py` resolves the room's book and then discards
 * it — its own docstring says "desk-wide, like trades … the room gate is about
 * who may look, not what they see" — and the desk answers from
 * `repo.list_predictions()`, a bare `SELECT * FROM predictions` with no filter.
 * The rows include claims belonging to no room at all.
 *
 * NOT "per forecaster". The grouping key is `source_label`, which
 * `stakes/manager.py::_relay_source_label` derives from the commitment's
 * CREATOR, not from whoever moved the slider — and a Round question is created
 * with `created_by_user_id=None`, which that function maps to the literal
 * "LLM". So both humans' Round forecasts land on one row labelled LLM. Saying
 * "per forecaster" would not merely overstate; it would name the wrong person.
 */
const INTRO =
  'What forecasts across the whole desk were worth once the world answered — one row per '
  + 'source, scored only on the questions that actually resolved.'

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
    // The state most readers meet: nothing in this product has ever been
    // scored. A blank panel with "no data" on it is read as a broken feature,
    // so this one says what it is WAITING FOR and roughly when that arrives.
    // SceneEmpty's four questions — what this place is, what lands here, how
    // it gets here, what you can do now — in the panel's own smaller frame;
    // the component itself is a scene-level surface and the Ledger already
    // wraps this panel in one.
    return (
      <div className="track-record-panel" data-testid="track-record-empty">
        <h3>Track Record</h3>
        <p className="track-record-intro">{INTRO}</p>
        <div className="track-record-quiet track-record-waiting">
          <p>
            Nothing has been scored yet. That is the board waiting on outcomes,
            not a panel that failed to load.
          </p>
          <p>
            A forecast scores when its question <strong>closes</strong>, not
            when you answer it — and{' '}
            <Explain term="settlement">nothing settles itself</Explain>: someone
            has to say what happened before a row can appear here.
          </p>
          {/* "each Sunday" is the Round's cadence, which is a product rule and
              is stated as one. NOT "drafted for this room each Sunday" — which
              room gets a slate depends on who is in it and whether anyone has
              spoken lately, and that is deployment state this panel has not
              read. Never advertise a door the server may refuse. */}
          <p>
            Questions arrive with{' '}
            <Explain term="round">the Round</Explain>, drafted each Sunday.
            Answer them as they land and the first scores show up once the
            first close date has passed.
          </p>
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
      <p className="track-record-intro">{INTRO}</p>
      <div className="track-record-headline">
        <span>{calibration.total_predictions ?? 0} resolved</span>
        {typeof brier === 'number' && (
          <span>
            <Explain term="brier">Brier {brier.toFixed(2)}</Explain>
          </span>
        )}
        {typeof bss === 'number' && (
          <span>
            <Explain term="bss">
              BSS {bss >= 0 ? '+' : ''}{bss.toFixed(2)}
            </Explain>
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
          {/* The two columns nothing else explains, plus the lone middot in
              the Source cell — which is undecodable on its own and until now
              carried its meaning only in a `title`, i.e. only for a reader on
              a mouse. Both facts are read off the desk's own aggregate:
              provenance is EMPIRICAL or UNVERIFIED_INSUFFICIENT_SAMPLES, and
              bias is signed confidence minus outcome. The sample floor is
              deliberately not quoted as a number here — it is the desk's
              constant, and a copy of it in this file would drift. */}
          <p className="track-record-note">
            Acc is how often those calls came in. Bias is signed — positive
            means overconfident, believing it harder than reality paid.
            {leaderboard.some(
              (row) => row.provenance && row.provenance !== 'EMPIRICAL',
            ) && ' A · marks a row with too few resolved questions to read as a track record yet.'}
          </p>
        </div>
      )}

      {points.length > 0 && (
        <div className="calibration-section">
          <h4><Explain term="calibration">Calibration</Explain></h4>
          {/* The bars carried their meaning in a `title` only, which is hover
              -only and so barred by the same accessibility rule sceneIdentity
              states. The caption says it in text instead; the titles stay as
              the per-bar detail. */}
          <p className="track-record-note">
            One bar per confidence band: of the calls made at that number, how
            many came in. Well calibrated means the bars climb with the labels.
          </p>
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

/**
 * SVG equity-vs-SPY sparkline. Renders nothing without two real marks.
 *
 * The key lives INSIDE this component rather than beside it in the panel so
 * the drawing and the words naming it share one guard — a legend that can
 * outlive its chart is a legend that eventually points at nothing. Until this
 * it drew two unlabelled lines and expected the reader to know which was which.
 */
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
    <>
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
      <p className="track-record-key">
        <span className="track-record-swatch is-equity" aria-hidden="true" />
        <Explain term="paper-book">the paper book</Explain>
        <span className="track-record-swatch is-spy" aria-hidden="true" />
        <Explain term="spy-benchmark">the same cash in SPY</Explain>
      </p>
    </>
  )
}
