import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import axe from 'axe-core'
import { Console } from './Console'
import { useAppStore } from '../../stores/appStore.ts'
import type { TradingDeskState } from '../../hooks/useTradingDesk.ts'
import type { ThesisStructure } from '../../types/trading.ts'

// The Console is display-only: it reads the lifted desk instance and the
// store's presence flags, and it is the ONE place --energy-level is set at
// runtime. These tests pin the lamp/energy contract and the bound/unbound
// tile boundary, plus the app's first real axe pass (axe-core sat in
// devDependencies unused until this file).

function deskState(overrides: Partial<TradingDeskState> = {}): TradingDeskState {
  return {
    structure: { status: 'empty' },
    quotes: { status: 'empty' },
    polymarket: { status: 'empty' },
    diff: { status: 'empty' },
    trades: { status: 'empty' },
    brief: { status: 'empty' },
    news: { status: 'empty' },
    portfolio: { status: 'empty' },
    bound: false,
    refresh: () => {},
    ...overrides,
  }
}

const structure: ThesisStructure = {
  id: 't1',
  meta: { title: 'Test thesis' },
  nodes: [{
    id: 'n1', label: 'OPEC meeting', type: 'event', phase: 1, state: 'monitoring',
    x: 0, y: 0, deadline: new Date(Date.now() + 3 * 24 * 60 * 60 * 1000).toISOString(),
  }],
  edges: [],
  scenarios: [],
}

function resetPresence() {
  useAppStore.setState({ isLLMThinking: false, isLLMStreaming: false, isDeepDiveActive: false })
  document.documentElement.style.removeProperty('--energy-level')
  document.documentElement.style.removeProperty('--energy-color')
}

afterEach(resetPresence)

describe('Console', () => {
  it('shows the ARMED lamp at rest and leaves the energy level at 0', () => {
    resetPresence()
    render(<Console desk={deskState()} />)
    expect(screen.getByText('ARMED')).toBeInTheDocument()
    expect(document.documentElement.style.getPropertyValue('--energy-level')).toBe('0')
  })

  it('lights THINKING and raises the energy level while the LLM deliberates', () => {
    resetPresence()
    useAppStore.setState({ isLLMThinking: true })
    render(<Console desk={deskState()} />)
    expect(screen.getByText('THINKING')).toBeInTheDocument()
    expect(document.documentElement.style.getPropertyValue('--energy-level')).toBe('0.45')
  })

  it('resets the energy level on unmount so a torn-down room never glows', () => {
    useAppStore.setState({ isLLMStreaming: true })
    const { unmount } = render(<Console desk={deskState()} />)
    expect(document.documentElement.style.getPropertyValue('--energy-level')).toBe('0.85')
    unmount()
    expect(document.documentElement.style.getPropertyValue('--energy-level')).toBe('0')
  })

  it('renders instrument tiles only for a bound desk', () => {
    resetPresence()
    const { rerender } = render(<Console desk={deskState()} />)
    expect(screen.queryByText('SPY')).not.toBeInTheDocument()
    rerender(<Console desk={deskState({
      bound: true,
      quotes: { status: 'ready', data: [{ symbol: 'SPY', price: 648.13, source: 'test' }], fetchedAt: Date.now() },
      polymarket: { status: 'ready', data: [{ slug: 'strait-closed', probability: 0.62 }], fetchedAt: Date.now() },
      structure: { status: 'ready', data: structure, fetchedAt: Date.now() },
    })} />)
    expect(screen.getByText('SPY')).toBeInTheDocument()
    expect(screen.getByText('648.13')).toBeInTheDocument()
    expect(screen.getByText('62')).toBeInTheDocument()
    // The nearest structure deadline surfaces as the UP NEXT countdown.
    expect(screen.getByText(/UP NEXT · OPEC meeting/)).toBeInTheDocument()
    // The lamp survives binding — it is not a bound-room tile.
    expect(screen.getByText('ARMED')).toBeInTheDocument()
  })

  it('passes the axe accessibility gate', async () => {
    resetPresence()
    const { container } = render(<Console desk={deskState({
      bound: true,
      quotes: { status: 'ready', data: [{ symbol: 'SPY', price: 648.13, source: 'test' }], fetchedAt: Date.now() },
    })} />)
    const results = await axe.run(container)
    expect(results.violations).toEqual([])
  })
})
