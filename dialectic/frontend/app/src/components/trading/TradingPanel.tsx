import { useState, type FormEvent } from 'react'
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
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [created, setCreated] = useState<{ bookId: string; title: string } | null>(null)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (busy || !title.trim()) return
    setBusy(true)
    setError(null)
    try {
      const res = await api.createThesis(roomId, {
        title: title.trim(),
        claim: claim.trim(),
        monthly_budget: Math.max(0, Math.round(Number(budget) || 0)),
      })
      setCreated({ bookId: res.book_id, title: res.title })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not reach the server')
    } finally {
      setBusy(false)
    }
  }

  if (created) {
    return (
      <div className="thesis-create thesis-create--done">
        <div className="thesis-create-heading">Thesis created</div>
        <p className="thesis-create-note">
          “{created.title}” is live as <code>{created.bookId}</code>, bound to
          this room. The first snapshot lands on the desk’s next cycle.
        </p>
        {accessToken && (
          <a
            className="trading-footer-link"
            href={buildTradingDeskUrl(accessToken, roomId, '/builder')}
            target="_blank"
            rel="noopener noreferrer"
          >
            Open Thesis Builder — draw the DAG →
          </a>
        )}
      </div>
    )
  }

  return (
    <form className="thesis-create" onSubmit={submit}>
      <div className="thesis-create-heading">Create a thesis</div>
      <p className="thesis-create-note">
        Name the thesis this room argues. The DAG gets drawn later, in the
        desk’s Builder.
      </p>
      <label className="thesis-create-label">
        Title
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          maxLength={120}
          placeholder="e.g. Sovereign Debt Doom Loop"
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
          placeholder="The causal claim this thesis stakes"
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
        />
      </label>
      {error && <div className="thesis-create-error">{error}</div>}
      <button
        type="submit"
        className="thesis-create-submit"
        disabled={busy || !title.trim()}
      >
        {busy ? 'Creating…' : 'Create Thesis'}
      </button>
    </form>
  )
}

// --- Main component ---

export function TradingPanel() {
  const tradingConfig = useAppStore((s) => s.tradingConfig)
  const accessToken = useAppStore((s) => s.accessToken)
  const currentRoom = useAppStore((s) => s.currentRoom)

  if (!tradingConfig) {
    return (
      <div className="trading-panel-empty">
        <p>No trading data available.</p>
        {currentRoom ? (
          <CreateThesisForm roomId={currentRoom.id} />
        ) : (
          <p className="trading-panel-hint">
            Push a thesis graph snapshot from the Trading Desk to populate this panel.
          </p>
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

      {/* Footer link — hands the current session across to tradingDesk. */}
      <div className="trading-footer">
        {accessToken ? (
          <a
            className="trading-footer-link"
            href={buildTradingDeskUrl(accessToken, currentRoom?.id)}
            target="_blank"
            rel="noopener noreferrer"
          >
            Open Full Dashboard (tradingDesk) →
          </a>
        ) : (
          // No token means no handoff is possible; a link that silently
          // dumped you on a login screen would be worse than no link.
          <span className="trading-footer-link trading-footer-link--inert">
            Open Full Dashboard (tradingDesk)
          </span>
        )}
      </div>
    </div>
  )
}
