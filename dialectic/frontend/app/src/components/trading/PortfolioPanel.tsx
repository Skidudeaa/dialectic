import type { Portfolio, PortfolioPosition, TradingSlice } from '../../types/trading.ts'
import './cockpit.css'

/**
 * The Paper Book — the room's belief, finally carrying a position.
 *
 * Renders the relay's portfolio read (td derives everything from the
 * append-only fill ledger at read time): cash, position rows priced off the
 * desk's quote cache, and the equity-vs-SPY one-liner. The benchmark is the
 * UNITIZED series — dated cash flows buy SPY units at each mark — and is
 * price-return-only on both sides, so the line says so.
 */

const EMPTY_COPY = 'No fills yet — seed the book with a deposit and the curve starts.'

const dollars = (v: number) =>
  `$${v.toLocaleString(undefined, { maximumFractionDigits: 2 })}`

/** Fill quantities are dollars / price, so fractional shares are normal. */
const qty = (v: number) =>
  v.toLocaleString(undefined, { maximumFractionDigits: 4 })

function bookIsEmpty(book: Portfolio): boolean {
  return book.cash === 0 && book.positions.length === 0 && book.marks.length === 0
}

function PositionRows({ positions }: { positions: PortfolioPosition[] }) {
  return (
    <div className="cockpit-table-wrap">
      <table className="cockpit-table">
        <thead>
          <tr>
            <th>Symbol</th>
            <th>Qty</th>
            <th>Avg Cost</th>
            <th>Price</th>
            <th>Value</th>
            <th>Unrealized</th>
          </tr>
        </thead>
        <tbody>
          {positions.map((p) => (
            <tr key={p.symbol}>
              <td>{p.symbol}</td>
              <td>{qty(p.qty)}</td>
              <td>{dollars(p.avg_cost)}</td>
              <td>{dollars(p.price)}</td>
              <td>{dollars(p.value)}</td>
              <td>
                {p.unrealized >= 0 ? '+' : '−'}{dollars(Math.abs(p.unrealized))}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function BookBody({ book }: { book: Portfolio }) {
  const benchmark = book.spy_baseline_now
  return (
    <>
      <div className="cockpit-line">Cash {dollars(book.cash)}</div>
      {book.positions.length > 0 ? (
        <PositionRows positions={book.positions} />
      ) : (
        <div className="cockpit-empty-line">No open positions — all cash.</div>
      )}
      <div className="cockpit-line" data-testid="portfolio-equity-line">
        Equity {dollars(book.equity)}
        {typeof benchmark === 'number' && (
          <> · vs SPY {dollars(benchmark)} <span className="cockpit-note">(price return only)</span></>
        )}
      </div>
    </>
  )
}

export interface PortfolioPanelProps {
  slice: TradingSlice<Portfolio>
}

export function PortfolioPanel({ slice }: PortfolioPanelProps) {
  return (
    <section className="cockpit-module" aria-label="Paper book">
      <div className="cockpit-header">
        <span
          className="cockpit-title"
          title="The room's paper portfolio — derived from the fill ledger, benchmarked against unitized SPY"
        >
          Paper Book
        </span>
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
            <div className="cockpit-error-line">{slice.error ?? 'Portfolio unavailable.'}</div>
            {slice.data && !bookIsEmpty(slice.data) && (
              <>
                <div className="cockpit-stale-note">Stale — last known book</div>
                <BookBody book={slice.data} />
              </>
            )}
          </>
        )}
        {slice.status === 'empty' && <div className="cockpit-empty-line">{EMPTY_COPY}</div>}
        {slice.status === 'ready' &&
          (!slice.data || bookIsEmpty(slice.data) ? (
            <div className="cockpit-empty-line">{EMPTY_COPY}</div>
          ) : (
            <BookBody book={slice.data} />
          ))}
      </div>
    </section>
  )
}
