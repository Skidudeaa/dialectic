import { Fragment, useState } from 'react'
import type { TradingSlice, OpenTrades, OpenTrade, TradePredicate } from '../../types/trading.ts'
import './cockpit.css'

const OP_SYMBOLS: Record<string, string> = {
  gte: '≥', gt: '>', lte: '≤', lt: '<', eq: '=', ne: '≠',
}

/** Predicate shapes vary by kind (threshold vs allowed-set vs day-count), so
 * every field is read defensively rather than assumed present. */
function summarizePredicate(p: TradePredicate): string {
  const subject = p.node_id ?? p.path ?? p.kind ?? 'condition'
  const opSymbol = p.op ? (OP_SYMBOLS[p.op] ?? p.op) : ''
  let value: string
  if (p.value !== undefined) value = String(p.value)
  else if (p.expected !== undefined) value = String(p.expected)
  else if (p.allowed && p.allowed.length > 0) value = p.allowed.join('/')
  else if (p.days !== undefined) value = `${p.days}d`
  else value = ''
  const bearing = p.load_bearing ? ' (load-bearing)' : ''
  return [subject, opSymbol, value].filter(Boolean).join(' ').trim() + bearing
}

const EMPTY_COPY = 'No open trades — the desk is flat.'

function TradeRows({ trades }: { trades: OpenTrade[] }) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  function toggle(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <div className="cockpit-table-wrap">
      <table className="cockpit-table">
        <thead>
          <tr>
            <th>Ticker</th>
            <th>Book</th>
            <th>Ref Price</th>
            <th>Predicates</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((t) => {
            const isOpen = expanded.has(t.trade_id)
            const predicates = t.predicates ?? []
            const first = predicates[0]
            return (
              <Fragment key={t.trade_id}>
                <tr
                  className="cockpit-table-row"
                  data-expandable="true"
                  role="button"
                  tabIndex={0}
                  aria-expanded={isOpen}
                  onClick={() => toggle(t.trade_id)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      toggle(t.trade_id)
                    }
                  }}
                >
                  <td>
                    <span className="cockpit-expand-caret">{'▸'}</span> {t.ticker}
                  </td>
                  <td>{t.book ?? '—'}</td>
                  <td>{t.ref_price !== undefined ? t.ref_price : '—'}</td>
                  <td>
                    {predicates.length} {predicates.length === 1 ? 'predicate' : 'predicates'}
                    {first && <> — {summarizePredicate(first)}</>}
                  </td>
                </tr>
                {isOpen && (
                  <tr>
                    <td colSpan={4}>
                      {predicates.length === 0 ? (
                        <span className="cockpit-empty-line">No predicates on this trade.</span>
                      ) : (
                        <ul className="cockpit-predicate-list">
                          {predicates.map((p, i) => (
                            <li key={i}>{summarizePredicate(p)}</li>
                          ))}
                        </ul>
                      )}
                    </td>
                  </tr>
                )}
              </Fragment>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export interface OpenTradesTableProps {
  slice: TradingSlice<OpenTrades>
}

export function OpenTradesTable({ slice }: OpenTradesTableProps) {
  return (
    <section className="cockpit-module" aria-label="Open trades">
      <div className="cockpit-header">
        <span className="cockpit-title">Open Trades</span>
      </div>
      <div className="cockpit-body">
        {slice.status === 'loading' && (
          <div className="cockpit-skeleton-group">
            <div className="cockpit-skeleton cockpit-skeleton--wide" />
            <div className="cockpit-skeleton cockpit-skeleton--wide" />
          </div>
        )}
        {slice.status === 'unavailable' && (
          <>
            <div className="cockpit-error-line">{slice.error ?? 'Open trades unavailable.'}</div>
            {slice.data && slice.data.trades.length > 0 && (
              <>
                <div className="cockpit-stale-note">Stale — last known trades</div>
                <TradeRows trades={slice.data.trades} />
              </>
            )}
          </>
        )}
        {slice.status === 'empty' && <div className="cockpit-empty-line">{EMPTY_COPY}</div>}
        {slice.status === 'ready' &&
          (!slice.data || slice.data.trades.length === 0 ? (
            <div className="cockpit-empty-line">{EMPTY_COPY}</div>
          ) : (
            <TradeRows trades={slice.data.trades} />
          ))}
      </div>
    </section>
  )
}
