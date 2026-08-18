import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { PortfolioPanel } from './PortfolioPanel'
import type { Portfolio, TradingSlice } from '../../types/trading'

// The Paper Book module is pure render over its slice — no fetching of its
// own (useTradingDesk owns that). The contracts here: the four slice states
// are DISTINCT (loading skeleton, calm empty, populated book, unavailable
// with stale data kept), and the benchmark one-liner carries its
// price-return-only label so the comparison never overclaims.

const BOOK: Portfolio = {
  cash: 1200.5,
  positions: [
    { symbol: 'XOP', qty: 14.2045, avg_cost: 140.8, price: 143.1, value: 2032.66, unrealized: 32.67 },
    { symbol: 'CF', qty: 5, avg_cost: 80, price: 78, value: 390, unrealized: -10 },
  ],
  equity: 3623.16,
  inception: '2026-08-16T14:00:00',
  marks: [{ mark_date: '2026-08-16', equity: 3600, spy_close: 560 }],
  spy_baseline: [{ mark_date: '2026-08-16', value: 3000 }],
  spy_baseline_now: 3010.25,
  price_return_only: true,
}

const EMPTY_BOOK: Portfolio = {
  cash: 0, positions: [], equity: 0, marks: [], spy_baseline: [],
  spy_baseline_now: null, price_return_only: true,
}

function slice(s: Partial<TradingSlice<Portfolio>>): TradingSlice<Portfolio> {
  return { status: 'ready', ...s } as TradingSlice<Portfolio>
}

describe('PortfolioPanel — slice states', () => {
  it('loading renders the skeleton, not copy', () => {
    const { container } = render(<PortfolioPanel slice={slice({ status: 'loading' })} />)
    expect(container.querySelector('.cockpit-skeleton')).not.toBeNull()
    expect(screen.queryByText(/No fills yet/)).toBeNull()
  })

  it('an empty slice and an empty ready book both read as the calm empty', () => {
    const { rerender } = render(<PortfolioPanel slice={slice({ status: 'empty' })} />)
    expect(screen.getByText(/No fills yet/)).toBeInTheDocument()
    rerender(<PortfolioPanel slice={slice({ status: 'ready', data: EMPTY_BOOK })} />)
    expect(screen.getByText(/No fills yet/)).toBeInTheDocument()
  })

  it('a populated book renders cash, position rows, and the benchmark line', () => {
    render(<PortfolioPanel slice={slice({ status: 'ready', data: BOOK })} />)
    expect(screen.getByText(/Cash \$1,200\.5/)).toBeInTheDocument()
    expect(screen.getByText('XOP')).toBeInTheDocument()
    expect(screen.getByText('14.2045')).toBeInTheDocument()
    expect(screen.getByText('CF')).toBeInTheDocument()
    const equityLine = screen.getByTestId('portfolio-equity-line')
    expect(equityLine.textContent).toContain('Equity $3,623.16')
    expect(equityLine.textContent).toContain('vs SPY $3,010.25')
    expect(equityLine.textContent).toContain('(price return only)')
  })

  it('a book with no benchmark yet renders equity without a vs-SPY claim', () => {
    render(
      <PortfolioPanel
        slice={slice({ status: 'ready', data: { ...BOOK, spy_baseline_now: null } })}
      />,
    )
    const equityLine = screen.getByTestId('portfolio-equity-line')
    expect(equityLine.textContent).toContain('Equity')
    expect(equityLine.textContent).not.toContain('vs SPY')
  })

  it('unavailable keeps the last known book, marked stale', () => {
    render(
      <PortfolioPanel
        slice={slice({ status: 'unavailable', error: 'tradingDesk: boom', data: BOOK })}
      />,
    )
    expect(screen.getByText('tradingDesk: boom')).toBeInTheDocument()
    expect(screen.getByText(/Stale — last known book/)).toBeInTheDocument()
    expect(screen.getByText('XOP')).toBeInTheDocument()
  })

  it('unavailable with no prior data shows only the error', () => {
    render(
      <PortfolioPanel slice={slice({ status: 'unavailable', error: 'down' })} />,
    )
    expect(screen.getByText('down')).toBeInTheDocument()
    expect(screen.queryByText(/Stale/)).toBeNull()
  })
})
