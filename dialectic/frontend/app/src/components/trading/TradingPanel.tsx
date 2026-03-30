import DOMPurify from 'dompurify'
import { useAppStore } from '../../stores/appStore.ts'
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

// --- Main component ---

export function TradingPanel() {
  const tradingConfig = useAppStore((s) => s.tradingConfig)

  if (!tradingConfig) {
    return (
      <div className="trading-panel-empty">
        <p>No trading data available.</p>
        <p className="trading-panel-hint">
          Push a thesis graph snapshot from the Trading Desk to populate this panel.
        </p>
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

      {/* Footer link */}
      <div className="trading-footer">
        <span className="trading-footer-link">Open Full Dashboard (tradingDesk)</span>
      </div>
    </div>
  )
}
