import { useEffect, useState, type FormEvent } from 'react'
import { PARTICIPANT_NAME } from '../../lib/productIdentity.ts'
import DOMPurify from 'dompurify'
import { useAppStore } from '../../stores/appStore.ts'
import { api, ApiError } from '../../lib/api.ts'
import './TradingPanel.css'

// --- Staleness helpers ---

function formatRelativeTime(isoTimestamp: string): { text: string; level: 'fresh' | 'stale' | 'expired' } {
  const then = new Date(isoTimestamp).getTime()
  const now = Date.now()
  const diffMs = now - then

  if (isNaN(then)) return { text: 'Unknown', level: 'expired' }

  const minutes = Math.floor(diffMs / 60_000)
  const hours = Math.floor(diffMs / 3_600_000)
  const days = Math.floor(diffMs / 86_400_000)

  let text: string
  if (minutes < 1) text = 'Just now'
  else if (minutes < 60) text = `${minutes}m ago`
  else if (hours < 24) text = `${hours}h ago`
  else text = `${days}d ago`

  let level: 'fresh' | 'stale' | 'expired'
  if (hours < 1) level = 'fresh'
  else if (hours < 48) level = 'stale'
  else level = 'expired'

  return { text, level }
}

function sanitize(value: unknown): string {
  if (value === null || value === undefined) return ''
  return DOMPurify.sanitize(String(value))
}

// --- Sub-components ---

function StalenessIndicator({ timestamp }: { timestamp: string }) {
  const { text, level } = formatRelativeTime(timestamp)
  return (
    <div className={`trading-staleness trading-staleness--${level}`}>
      <span className="trading-staleness-dot" />
      <span>Last updated: {text}</span>
    </div>
  )
}

function PhaseBadge({ phase }: { phase: { number: number; key: string; status: string } }) {
  return (
    <div className="trading-phase-badge">
      Phase {phase.number}: {sanitize(phase.key)} — <span className="trading-phase-status">{sanitize(phase.status).toUpperCase()}</span>
    </div>
  )
}

function ActiveNodes({ nodeStates }: { nodeStates: Record<string, string> }) {
  const fired = Object.entries(nodeStates).filter(([, s]) => s === 'fired')
  const approaching = Object.entries(nodeStates).filter(([, s]) => s === 'approaching')

  if (fired.length === 0 && approaching.length === 0) {
    return <div className="trading-section-empty">No active signals</div>
  }

  return (
    <div className="trading-node-list">
      {fired.map(([id]) => (
        <span key={id} className="trading-node-badge trading-node-badge--fired">
          {sanitize(id)}
        </span>
      ))}
      {approaching.map(([id]) => (
        <span key={id} className="trading-node-badge trading-node-badge--approaching">
          {sanitize(id)}
        </span>
      ))}
    </div>
  )
}

function Countdowns({ countdowns }: { countdowns: { nodeId: string; daysRemaining: number; deadline: string; label?: string }[] }) {
  if (!countdowns || countdowns.length === 0) return null

  const sorted = [...countdowns].sort((a, b) => a.daysRemaining - b.daysRemaining)

  return (
    <div className="trading-countdowns">
      {sorted.map((cd) => (
        <div
          key={cd.nodeId}
          className={`trading-countdown-row ${cd.daysRemaining < 7 ? 'trading-countdown-row--urgent' : ''}`}
        >
          <span className="trading-countdown-label">{sanitize(cd.label || cd.nodeId)}</span>
          <span className="trading-countdown-days">{cd.daysRemaining}d</span>
        </div>
      ))}
    </div>
  )
}

function ConfluenceScores({ scores }: { scores: Record<string, number> }) {
  if (!scores) return null

  const highlighted = Object.entries(scores)
    .sort(([, a], [, b]) => b - a)

  if (highlighted.length === 0) return null

  return (
    <div className="trading-confluence">
      {highlighted.map(([id, score]) => (
        <div key={id} className={`trading-confluence-row ${score > 0.5 ? 'trading-confluence-row--high' : ''}`}>
          <span className="trading-confluence-id">{sanitize(id)}</span>
          <span className="trading-confluence-score">{score.toFixed(2)}</span>
        </div>
      ))}
    </div>
  )
}

function ScenarioPills({ scenarios }: { scenarios: Record<string, { probability: number; netImpact: number }> }) {
  if (!scenarios) return null

  const sorted = Object.entries(scenarios)
    .sort(([, a], [, b]) => b.probability - a.probability)
    .slice(0, 4)

  if (sorted.length === 0) return null

  return (
    <div className="trading-scenarios">
      {sorted.map(([id, { probability, netImpact }]) => (
        <div key={id} className="trading-scenario-pill">
          <span className="trading-scenario-name">{sanitize(id)}</span>
          <span className="trading-scenario-prob">{Math.round(probability * 100)}%</span>
          <span className={`trading-scenario-impact ${netImpact >= 0 ? 'trading-scenario-impact--pos' : 'trading-scenario-impact--neg'}`}>
            {netImpact >= 0 ? '+' : ''}{typeof netImpact === 'number' ? netImpact.toLocaleString() : netImpact}
          </span>
        </div>
      ))}
    </div>
  )
}

function PortfolioSummary({ portfolio }: { portfolio: { monthlyBudget?: number; topPositions?: string[]; sgovAvailable?: number; sgov_available?: number; allocated?: number } }) {
  if (!portfolio) return null

  const sgov = portfolio.sgovAvailable ?? portfolio.sgov_available ?? 0

  return (
    <div className="trading-portfolio">
      {portfolio.topPositions && portfolio.topPositions.length > 0 && (
        <div className="trading-portfolio-positions">
          {portfolio.topPositions.map((pos, i) => (
            <div key={i} className="trading-portfolio-position">{sanitize(pos)}</div>
          ))}
        </div>
      )}
      <div className="trading-portfolio-footer">
        {portfolio.monthlyBudget != null && (
          <span className="trading-portfolio-budget">Budget: ${portfolio.monthlyBudget.toLocaleString()}/mo</span>
        )}
        {sgov > 0 && (
          <span className="trading-portfolio-sgov">SGOV: ${sgov.toLocaleString()}</span>
        )}
      </div>
    </div>
  )
}

// --- tradingDesk handoff ---

const TRADINGDESK_URL = 'https://td.somacura.org'

/**
 * Build the deep link that carries this session across to tradingDesk.
 *
 * The token rides in the URL FRAGMENT, never the query string: fragments are
 * not sent to the server, so the token stays out of nginx/Cloudflare access
 * logs. tradingDesk strips it from the address bar on arrival.
 *
 * WHY the ROOM id and not a book id: the trading snapshot carries no book
 * identifier — verified against rooms.trading_config in the live DB, whose
 * only identifying field is a display `title`. Matching on a title would break
 * silently the first time someone renames a thesis. Each tradingDesk book
 * already records the room that discusses it (meta.dialecticRoomId), so the
 * room id IS the join key between the two systems, and the desk resolves it to
 * the right case on arrival. Omitted if unknown — the desk then falls back to
 * its own default case rather than following a broken pointer.
 */
function buildTradingDeskUrl(
  accessToken: string, roomId?: string | null, path = '/',
): string {
  const params = new URLSearchParams()
  params.set('dialectic_token', accessToken)
  if (roomId) params.set('dialectic_room', roomId)
  // The desk adopts the fragment token at boot on ANY route, so a deep link
  // straight into /builder carries the session with it.
  return `${TRADINGDESK_URL}${path}#${params.toString()}`
}

// --- Create Thesis (empty-state flow) ---

type DraftNode = {
  id: string
  label: string
  type: string
  phase: number
  context?: string
  thresholds?: { level: number; label?: string }[]
  feeds?: { source: string; symbol?: string; series?: string; label?: string }[]
}
type DraftEdge = {
  source: string
  target: string
  mechanism: string
  lag: string
  strength: number
}
type ThesisDraft = { nodes: DraftNode[]; edges: DraftEdge[]; rationale: string }

const PHASE_NAMES: Record<number, string> = {
  1: 'Shock',
  2: 'Transmission',
  3: 'Amplification',
  4: 'Policy Response',
  5: 'Resolution',
}

/** Compact review rendering: nodes grouped by cascade phase, then edges. */
function DraftPreview({ draft }: { draft: ThesisDraft }) {
  const phases = [...new Set(draft.nodes.map((n) => n.phase))].sort()
  const labelOf = (id: string) =>
    draft.nodes.find((n) => n.id === id)?.label ?? id
  return (
    <div className="thesis-draft">
      {phases.map((phase) => (
        <div key={phase} className="thesis-draft-phase">
          <div className="thesis-draft-phase-label">
            {phase} · {PHASE_NAMES[phase] ?? 'Phase'}
          </div>
          {draft.nodes
            .filter((n) => n.phase === phase)
            .map((n) => (
              <div key={n.id} className="thesis-draft-node" title={n.context}>
                <span className="thesis-draft-node-type">{n.type}</span>
                <span className="thesis-draft-node-label">{sanitize(n.label)}</span>
                {(n.thresholds?.length ?? 0) > 0 && (
                  <span className="thesis-draft-node-extra">
                    {n.thresholds!.length} lvl
                  </span>
                )}
                {(n.feeds?.length ?? 0) > 0 && (
                  <span className="thesis-draft-node-extra">live</span>
                )}
              </div>
            ))}
        </div>
      ))}
      <div className="thesis-draft-phase-label">
        Edges ({draft.edges.length})
      </div>
      {draft.edges.map((e, i) => (
        <div key={i} className="thesis-draft-edge">
          <span className="thesis-draft-edge-route">
            {sanitize(labelOf(e.source))} → {sanitize(labelOf(e.target))}
          </span>
          <span className="thesis-draft-edge-mech">
            {sanitize(e.mechanism)} · {sanitize(e.lag)} · {e.strength}
          </span>
        </div>
      ))}
    </div>
  )
}

/**
 * The room births its book. Dialectic deliberately has no DAG-authoring
 * surface — the Builder lives on the desk — so this form only establishes
 * the binding: title + claim + budget become a book born bound to this
 * room, and the first snapshot arrives on the coordinator's next cycle.
 */
function CreateThesisForm({ roomId }: { roomId: string }) {
  const accessToken = useAppStore((s) => s.accessToken)
  const [title, setTitle] = useState('')
  const [claim, setClaim] = useState('')
  const [budget, setBudget] = useState('5000')
  const [draftEnabled, setDraftEnabled] = useState(true)
  const [busy, setBusy] = useState<'idle' | 'drafting' | 'creating'>('idle')
  const [error, setError] = useState<string | null>(null)
  const [draft, setDraft] = useState<ThesisDraft | null>(null)
  const [created, setCreated] = useState<{ bookId: string; title: string } | null>(null)

  // A propose_thesis chat card seeds the form through the store — consume
  // the seed once so a later card can seed again.
  const thesisSeed = useAppStore((s) => s.thesisSeed)
  const setThesisSeed = useAppStore((s) => s.setThesisSeed)
  useEffect(() => {
    if (!thesisSeed) return
    setTitle(thesisSeed.title)
    setClaim(thesisSeed.claim)
    setBudget(String(thesisSeed.monthlyBudget))
    setThesisSeed(null)
  }, [thesisSeed, setThesisSeed])

  const requestBody = () => ({
    title: title.trim(),
    claim: claim.trim(),
    monthly_budget: Math.max(0, Math.round(Number(budget) || 0)),
  })

  const create = async (nodes: unknown[], edges: unknown[]) => {
    setBusy('creating')
    setError(null)
    try {
      const res = await api.createThesis(roomId, { ...requestBody(), nodes, edges })
      setCreated({ bookId: res.book_id, title: res.title })
      setDraft(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not reach the server')
    } finally {
      setBusy('idle')
    }
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (busy !== 'idle' || !title.trim()) return
    if (!draftEnabled) {
      await create([], [])
      return
    }
    setBusy('drafting')
    setError(null)
    try {
      const res = await api.draftThesis(roomId, requestBody())
      setDraft({
        nodes: res.nodes as DraftNode[],
        edges: res.edges as DraftEdge[],
        rationale: res.rationale,
      })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not reach the server')
    } finally {
      setBusy('idle')
    }
  }

  if (created) {
    return (
      <div className="thesis-create thesis-create--done">
        <div className="thesis-create-heading">Thesis created</div>
        <p className="thesis-create-note">
          “{created.title}” is live as <code>{created.bookId}</code>, bound to
          this room.
        </p>
        <ul className="thesis-create-next">
          <li>The first snapshot lands here within seconds</li>
          <li>{PARTICIPANT_NAME} now sees the thesis state in every turn</li>
          <li>Refine the DAG in the desk’s Builder</li>
          <li>Retire it any time from this panel’s footer</li>
        </ul>
        {accessToken && (
          <a
            className="trading-instrument-link"
            href={buildTradingDeskUrl(accessToken, roomId, '/builder')}
            target="_blank"
            rel="noopener noreferrer"
          >
            <span className="trading-instrument-link-kicker">Deep instrument</span>
            Open Builder — refine the DAG →
          </a>
        )}
      </div>
    )
  }

  if (draft) {
    const phases = draft.nodes.map((n) => n.phase)
    return (
      <div className="thesis-create">
        <div className="thesis-create-heading">
          Drafted cascade — review before it becomes the book
        </div>
        <div className="thesis-draft-summary">
          {draft.nodes.length} nodes · {draft.edges.length} edges · phases{' '}
          {Math.min(...phases)}–{Math.max(...phases)}
        </div>
        {draft.rationale && (
          <p className="thesis-create-note">{draft.rationale}</p>
        )}
        <DraftPreview draft={draft} />
        {error && <div className="thesis-create-error">{error}</div>}
        <button
          type="button"
          className="thesis-create-submit thesis-create-submit--primary"
          disabled={busy !== 'idle'}
          onClick={() => create(draft.nodes, draft.edges)}
        >
          {busy === 'creating' ? 'Creating…' : 'Accept & Create'}
        </button>
        <div className="thesis-draft-actions">
          <button
            type="button"
            className="thesis-draft-discard"
            disabled={busy !== 'idle'}
            onClick={() => { setDraft(null); setError(null) }}
          >
            ← Discard draft
          </button>
          <button
            type="button"
            className="thesis-draft-discard"
            disabled={busy !== 'idle'}
            onClick={() => create([], [])}
          >
            Create empty instead
          </button>
        </div>
      </div>
    )
  }

  const locked = busy !== 'idle'

  return (
    <form className="thesis-create" onSubmit={submit}>
      <div className="thesis-create-heading">Create a thesis</div>
      <ol className="thesis-create-steps">
        <li><em>Name it</em> — a title and the causal claim it stakes</li>
        <li><em>{PARTICIPANT_NAME} drafts</em> the cascade for your review</li>
        <li><em>You accept</em> — nothing exists until your tap</li>
        <li><em>Refine on the desk</em> — the Builder owns the canvas</li>
      </ol>
      <label className="thesis-create-label">
        Title
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          maxLength={120}
          placeholder="e.g. Sovereign Debt Doom Loop"
          disabled={locked}
          required
        />
      </label>
      <label className="thesis-create-label">
        Claim
        <textarea
          value={claim}
          onChange={(e) => setClaim(e.target.value)}
          maxLength={2000}
          rows={3}
          placeholder="The shock, the transmission, the payoff"
          disabled={locked}
        />
      </label>
      <label className="thesis-create-label">
        Monthly budget ($)
        <input
          type="number"
          min={0}
          step={500}
          value={budget}
          onChange={(e) => setBudget(e.target.value)}
          disabled={locked}
        />
      </label>
      <label className="thesis-create-toggle">
        <input
          type="checkbox"
          checked={draftEnabled}
          onChange={(e) => setDraftEnabled(e.target.checked)}
          disabled={locked}
        />
        Draft the cascade with {PARTICIPANT_NAME}
      </label>
      {error && <div className="thesis-create-error">{error}</div>}
      <button
        type="submit"
        className="thesis-create-submit thesis-create-submit--primary"
        disabled={locked || !title.trim()}
      >
        {busy === 'drafting'
          ? 'Drafting cascade…'
          : busy === 'creating'
            ? 'Creating…'
            : draftEnabled
              ? 'Draft Thesis'
              : 'Create Empty Thesis'}
      </button>
      {busy === 'drafting' && (
        <p className="thesis-create-note">
          {PARTICIPANT_NAME} is composing nodes, mechanisms and thresholds — usually
          20–40 seconds.
        </p>
      )}
    </form>
  )
}

// --- Main component ---

export function TradingPanel() {
  const tradingConfig = useAppStore((s) => s.tradingConfig)
  const accessToken = useAppStore((s) => s.accessToken)
  const currentRoom = useAppStore((s) => s.currentRoom)
  const setTradingConfig = useAppStore((s) => s.setTradingConfig)
  const [retireState, setRetireState] =
    useState<'idle' | 'confirm' | 'retiring' | 'error'>('idle')

  const retire = async () => {
    if (!currentRoom || retireState === 'retiring') return
    setRetireState('retiring')
    try {
      await api.retireThesis(currentRoom.id)
      // The panel falls back to the create surface — the room can birth
      // its successor immediately.
      setTradingConfig(null)
      setRetireState('idle')
    } catch {
      setRetireState('error')
    }
  }

  // Home connects the schemes; it can never hold a thesis of its own
  // (backend and tool guards are authoritative — this is explanation,
  // not enforcement). The tab stays present, the create form does not.
  if (currentRoom?.is_home && !tradingConfig) {
    return (
      <div className="trading-panel-empty trading-panel-home">
        <strong>Home connects the schemes.</strong>
        <p>Propose and create a thesis in the scheme&apos;s own room.</p>
      </div>
    )
  }

  if (!tradingConfig) {
    return (
      <div className="trading-panel-empty">
        {currentRoom ? (
          // The create surface IS the zero state — no "no data" apology
          // above a form that exists precisely because there is no data.
          <CreateThesisForm roomId={currentRoom.id} />
        ) : (
          <>
            <p>No trading data available.</p>
            <p className="trading-panel-hint">
              Enter a room to create a thesis, or push a snapshot from the
              Trading Desk.
            </p>
          </>
        )}
      </div>
    )
  }

  const {
    timestamp,
    title,
    nodeStates,
    cascadePhase,
    countdowns,
    confluenceScores,
    scenarioImpacts,
    portfolioSummary,
  } = tradingConfig

  return (
    <div className="trading-panel">
      {/* Header: title + staleness */}
      <div className="trading-header">
        {title && <div className="trading-title">{sanitize(title)}</div>}
        {timestamp && <StalenessIndicator timestamp={timestamp} />}
      </div>

      {/* Bound but undrawn — a created thesis whose DAG has no nodes yet */}
      {(!nodeStates || Object.keys(nodeStates).length === 0) && (
        <div className="trading-section">
          <p className="thesis-create-note">
            The cascade is undrawn — this thesis has no nodes yet. Draw it
            in the Builder and the panel fills in on the next snapshot.
          </p>
          {accessToken && (
            <a
              className="trading-instrument-link"
              href={buildTradingDeskUrl(accessToken, currentRoom?.id, '/builder')}
              target="_blank"
              rel="noopener noreferrer"
            >
              <span className="trading-instrument-link-kicker">Deep instrument</span>
              Open Builder — draw the cascade →
            </a>
          )}
        </div>
      )}

      {/* Phase badge */}
      {cascadePhase && (
        <div className="trading-section">
          <PhaseBadge phase={cascadePhase} />
        </div>
      )}

      {/* Active nodes */}
      {nodeStates && (
        <div className="trading-section">
          <div className="trading-section-label">Active Nodes</div>
          <ActiveNodes nodeStates={nodeStates} />
        </div>
      )}

      {/* Countdowns */}
      {countdowns && countdowns.length > 0 && (
        <div className="trading-section">
          <div className="trading-section-label">Countdowns</div>
          <Countdowns countdowns={countdowns} />
        </div>
      )}

      {/* Confluence */}
      {confluenceScores && Object.keys(confluenceScores).length > 0 && (
        <div className="trading-section">
          <div className="trading-section-label">Confluence</div>
          <ConfluenceScores scores={confluenceScores} />
        </div>
      )}

      {/* Scenarios */}
      {scenarioImpacts && Object.keys(scenarioImpacts).length > 0 && (
        <div className="trading-section">
          <div className="trading-section-label">Scenarios</div>
          <ScenarioPills scenarios={scenarioImpacts} />
        </div>
      )}

      {/* Portfolio */}
      {portfolioSummary && (
        <div className="trading-section">
          <div className="trading-section-label">Portfolio</div>
          <PortfolioSummary portfolio={portfolioSummary} />
        </div>
      )}

      {/* Footer — the ONE remaining hand-off, and it is deep EDITING only.
          The dashboard link died with the cockpit merge (2026-08-14): the
          Bench now renders the graph, quotes, trades, scenarios and news
          natively, so "open the other app to see your thesis" is over. The
          Builder link survives per design v2 §12.5 — a deeper instrument
          for restructuring the DAG, not an exit to a parallel product. */}
      <div className="trading-footer">
        {accessToken ? (
          <a
            className="trading-instrument-link"
            href={buildTradingDeskUrl(accessToken, currentRoom?.id, '/builder')}
            target="_blank"
            rel="noopener noreferrer"
          >
            <span className="trading-instrument-link-kicker">Deep instrument</span>
            Open Builder — restructure the DAG →
          </a>
        ) : (
          // No token means no handoff is possible; a link that silently
          // dumped you on a login screen would be worse than no link.
          <span className="trading-instrument-link trading-instrument-link--inert">
            Builder unavailable — sign in again
          </span>
        )}
        {/* Retire — two taps on purpose. The book survives on the desk;
            only the binding and the push path die. */}
        {currentRoom && (
          <div className="trading-retire">
            {retireState === 'idle' && (
              <button
                className="thesis-draft-discard"
                onClick={() => setRetireState('confirm')}
              >
                Retire thesis…
              </button>
            )}
            {retireState === 'confirm' && (
              <>
                <span className="trading-retire-warning">
                  Unbind this thesis from the room? The book survives on the
                  desk; snapshots stop.
                </span>
                <div className="thesis-draft-actions">
                  <button className="thesis-retire-confirm" onClick={retire}>
                    Confirm retire
                  </button>
                  <button
                    className="thesis-draft-discard"
                    onClick={() => setRetireState('idle')}
                  >
                    Keep it
                  </button>
                </div>
              </>
            )}
            {retireState === 'retiring' && (
              <span className="trading-retire-warning">Retiring…</span>
            )}
            {retireState === 'error' && (
              <>
                <span className="thesis-create-error">
                  could not retire — try again
                </span>
                <button
                  className="thesis-draft-discard"
                  onClick={() => setRetireState('idle')}
                >
                  Dismiss
                </button>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
