import { useState } from 'react'
import type { ThesisScenario, ScenarioEvaluation } from '../../types/trading.ts'
import type { TradingSnapshot } from '../../types/index.ts'
import { api, ApiError } from '../../lib/api.ts'
import './cockpit.css'

type RowStatus = 'idle' | 'evaluating' | 'result' | 'failed'

interface RowState {
  status: RowStatus
  result?: ScenarioEvaluation
  error?: string
}

/** Defensive: probability may arrive 0–1 or already 0–100 — see
 * PolymarketStrip for the same convention. */
function formatPercent(p: number | undefined | null): string {
  if (p === undefined || p === null || !Number.isFinite(p)) return '—'
  const pct = p > 1 ? p : p * 100
  return `${pct.toFixed(1)}%`
}

function formatDollar(n: number | undefined): string {
  if (n === undefined || !Number.isFinite(n)) return '—'
  const sign = n < 0 ? '-' : ''
  return `${sign}$${Math.abs(n).toLocaleString(undefined, { maximumFractionDigits: 0 })}`
}

/** snapshotImpacts is keyed loosely by whichever id the desk pushed last —
 * scenario id or its display name. Check both rather than assume. */
function lookupSnapshotImpact(
  scenario: ThesisScenario,
  snapshotImpacts?: TradingSnapshot['scenarioImpacts'],
): { probability: number; netImpact: number } | undefined {
  if (!snapshotImpacts) return undefined
  return snapshotImpacts[scenario.id] ?? (scenario.name ? snapshotImpacts[scenario.name] : undefined)
}

const NOTES_LIMIT = 90

function ScenarioNotes({ notes }: { notes: string }) {
  const [expanded, setExpanded] = useState(false)
  if (notes.length <= NOTES_LIMIT) {
    return <div className="cockpit-scenario-notes">{notes}</div>
  }
  return (
    <div className="cockpit-scenario-notes">
      {expanded ? notes : `${notes.slice(0, NOTES_LIMIT)}...`}{' '}
      <button type="button" className="cockpit-btn cockpit-btn--ghost" onClick={() => setExpanded((v) => !v)}>
        {expanded ? 'Less' : 'More'}
      </button>
    </div>
  )
}

function ChangedNodeChips({ changedNodes }: { changedNodes: ScenarioEvaluation['changedNodes'] }) {
  const entries = Object.entries(changedNodes ?? {})
  if (entries.length === 0) return null
  return (
    <div className="cockpit-node-chip-row">
      {entries.map(([nodeId, change]) => (
        <span className="cockpit-node-chip" key={nodeId}>
          {nodeId}: {change.old} → {change.new}
        </span>
      ))}
    </div>
  )
}

function PortfolioImpactTable({ portfolioImpact }: { portfolioImpact: ScenarioEvaluation['portfolioImpact'] }) {
  const entries = Object.entries(portfolioImpact ?? {})
  if (entries.length === 0) return null
  const sorted = [...entries].sort(
    (a, b) => Math.abs(b[1].dollarImpact ?? 0) - Math.abs(a[1].dollarImpact ?? 0),
  )
  return (
    <div className="cockpit-table-wrap">
      <table className="cockpit-mini-table">
        <thead>
          <tr>
            <th>Instrument</th>
            <th>% Impact</th>
            <th>$ Impact</th>
            <th>From → To</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map(([instrument, impact]) => (
            <tr key={instrument}>
              <td>{instrument}</td>
              <td>{Number.isFinite(impact.pctImpact) ? `${impact.pctImpact.toFixed(1)}%` : '—'}</td>
              <td>{formatDollar(impact.dollarImpact)}</td>
              <td>{impact.from ?? '—'} → {impact.to ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export interface ScenarioWhatIfProps {
  roomId: string
  scenarios: ThesisScenario[]
  snapshotImpacts?: TradingSnapshot['scenarioImpacts']
}

export function ScenarioWhatIf({ roomId, scenarios, snapshotImpacts }: ScenarioWhatIfProps) {
  const [rows, setRows] = useState<Record<string, RowState>>({})

  async function evaluate(scenario: ThesisScenario) {
    setRows((prev) => ({ ...prev, [scenario.id]: { status: 'evaluating' } }))
    try {
      const result = await api.evaluateScenario(roomId, scenario.id) as ScenarioEvaluation
      setRows((prev) => ({ ...prev, [scenario.id]: { status: 'result', result } }))
    } catch (err) {
      const message = err instanceof ApiError ? err.message : 'Evaluation failed — check your connection.'
      setRows((prev) => ({ ...prev, [scenario.id]: { status: 'failed', error: message } }))
    }
  }

  return (
    <section className="cockpit-module" aria-label="Scenario what-if">
      <div className="cockpit-header">
        <span className="cockpit-title" title="Authored scenarios — Evaluate runs a hypothetical against the live snapshot, nothing is placed">Scenario What-If</span>
      </div>
      <div className="cockpit-body">
        {scenarios.length === 0 ? (
          <div className="cockpit-empty-line">No scenarios authored for this thesis.</div>
        ) : (
          <div className="cockpit-scenario-list">
            {scenarios.map((scenario) => {
              const row = rows[scenario.id] ?? { status: 'idle' as const }
              const snapshotImpact = lookupSnapshotImpact(scenario, snapshotImpacts)
              const label = scenario.name ?? scenario.id
              const buttonLabel =
                row.status === 'evaluating' ? 'Evaluating…' : row.status === 'failed' ? 'Retry' : 'Evaluate'

              return (
                <div className="cockpit-scenario-row" key={scenario.id}>
                  <div className="cockpit-scenario-head">
                    <span className="cockpit-scenario-name">{label}</span>
                    <div className="cockpit-scenario-probs">
                      <span>
                        <span className="cockpit-scenario-prob-label">Authored</span>
                        <span className="cockpit-scenario-prob-authored">{formatPercent(scenario.probability)}</span>
                      </span>
                      {snapshotImpact && (
                        <span>
                          <span className="cockpit-scenario-prob-label">Live</span>
                          <span className="cockpit-scenario-prob-live">{formatPercent(snapshotImpact.probability)}</span>
                          {' '}
                          <span
                            className={
                              snapshotImpact.netImpact < 0
                                ? 'cockpit-scenario-net-impact cockpit-scenario-net-impact--neg'
                                : snapshotImpact.netImpact > 0
                                  ? 'cockpit-scenario-net-impact cockpit-scenario-net-impact--pos'
                                  : 'cockpit-scenario-net-impact'
                            }
                          >
                            ({formatDollar(snapshotImpact.netImpact)})
                          </span>
                        </span>
                      )}
                    </div>
                  </div>
                  {scenario.notes && <ScenarioNotes notes={scenario.notes} />}
                  <div className="cockpit-scenario-actions">
                    <button
                      type="button"
                      className={row.status === 'failed' ? 'cockpit-btn cockpit-btn--retry' : 'cockpit-btn'}
                      disabled={row.status === 'evaluating'}
                      onClick={() => evaluate(scenario)}
                    >
                      {buttonLabel}
                    </button>
                  </div>
                  {row.status === 'failed' && row.error && (
                    <div className="cockpit-error-line">{row.error}</div>
                  )}
                  {row.status === 'result' && row.result && (
                    <div className="cockpit-scenario-result">
                      <div className="cockpit-scenario-result-label">Hypothetical — nothing placed</div>
                      <div className="cockpit-scenario-result-prob">
                        Probability: {formatPercent(row.result.probability)}
                      </div>
                      <ChangedNodeChips changedNodes={row.result.changedNodes} />
                      <PortfolioImpactTable portfolioImpact={row.result.portfolioImpact} />
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>
    </section>
  )
}
