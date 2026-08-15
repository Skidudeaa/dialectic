import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useTradingDesk } from './useTradingDesk'
import { api, ApiError } from '../lib/api.ts'
import { useAppStore } from '../stores/appStore.ts'
import type {
  MorningBrief,
  OpenTrades,
  PolymarketOdd,
  Quote,
  ThesisDiff,
  ThesisNews,
  ThesisStructure,
} from '../types/trading.ts'
import type { TradingSnapshot } from '../types/index.ts'

vi.mock('../lib/api.ts', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../lib/api.ts')>()
  return {
    ...actual,
    api: {
      getThesisStructure: vi.fn(),
      getTradingQuotes: vi.fn(),
      getPolymarketOdds: vi.fn(),
      getTradingDiff: vi.fn(),
      getOpenTrades: vi.fn(),
      getMorningBrief: vi.fn(),
      getThesisNews: vi.fn(),
    },
  }
})

// Selector-driven, like the real Zustand hook, but backed by a plain mutable
// object the tests can reassign between renders — real Zustand subscriptions
// aren't needed to prove the hook diffs the stamp correctly.
let storeState: { tradingConfig: TradingSnapshot | null } = { tradingConfig: null }
vi.mock('../stores/appStore.ts', () => ({
  useAppStore: vi.fn(),
}))

const structureData: ThesisStructure = {
  id: 'book-1',
  meta: { title: 'Iran/Hormuz' },
  nodes: [],
  edges: [],
  scenarios: [],
}
const quotesData: Quote[] = [{ symbol: 'USO', price: 71.2, source: 'test' }]
const polymarketData: PolymarketOdd[] = [{ slug: 'strait-closure', probability: 0.12 }]
const diffData: ThesisDiff = {
  hasChanges: false,
  stateChanges: [],
  confluenceChanges: {},
  countdownChanges: [],
  marketChanges: {},
  cascadePhaseChange: null,
  scenarioChanges: {},
  portfolioChanges: {},
  newNodes: [],
  removedNodes: [],
  tvIndicatorShifts: {},
}
const tradesData: OpenTrades = { count: 0, trades: [] }
const briefData: MorningBrief = { book_id: 'book-1', brief: 'quiet morning' }
const newsData: ThesisNews = { articles: [] }

function mockAllSuccess() {
  vi.mocked(api.getThesisStructure).mockResolvedValue(structureData)
  vi.mocked(api.getTradingQuotes).mockResolvedValue(quotesData)
  vi.mocked(api.getPolymarketOdds).mockResolvedValue(polymarketData)
  vi.mocked(api.getTradingDiff).mockResolvedValue(diffData)
  vi.mocked(api.getOpenTrades).mockResolvedValue(tradesData)
  vi.mocked(api.getMorningBrief).mockResolvedValue(briefData)
  vi.mocked(api.getThesisNews).mockResolvedValue(newsData)
}

async function waitForAllReady(result: { current: ReturnType<typeof useTradingDesk> }) {
  await waitFor(() => {
    expect(result.current.structure.status).toBe('ready')
    expect(result.current.quotes.status).toBe('ready')
    expect(result.current.polymarket.status).toBe('ready')
    expect(result.current.diff.status).toBe('ready')
    expect(result.current.trades.status).toBe('ready')
    expect(result.current.brief.status).toBe('ready')
    expect(result.current.news.status).toBe('ready')
  })
}

describe('useTradingDesk', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    storeState = { tradingConfig: null }
    // The hook only selects tradingConfig; a full AppState mock would be 70
    // irrelevant fields, so the partial goes through a deliberate cast.
    vi.mocked(useAppStore).mockImplementation(((selector: (s: { tradingConfig: TradingSnapshot | null }) => unknown) =>
      selector(storeState)) as unknown as typeof useAppStore)
  })

  it('roomId null: fetches nothing, everything empty', () => {
    const { result } = renderHook(() => useTradingDesk(null))
    expect(result.current.bound).toBe(false)
    expect(result.current.structure.status).toBe('empty')
    expect(result.current.news.status).toBe('empty')
    expect(api.getThesisStructure).not.toHaveBeenCalled()
    expect(api.getTradingQuotes).not.toHaveBeenCalled()
  })

  it('409 on structure: bound=false, all slices empty, no fan-out', async () => {
    vi.mocked(api.getThesisStructure).mockRejectedValue(new ApiError('unbound', 409))
    const { result } = renderHook(() => useTradingDesk('r1'))

    await waitFor(() => expect(result.current.bound).toBe(false))
    expect(result.current.structure.status).toBe('empty')
    expect(result.current.quotes.status).toBe('empty')
    expect(result.current.polymarket.status).toBe('empty')
    expect(result.current.diff.status).toBe('empty')
    expect(result.current.trades.status).toBe('empty')
    expect(result.current.brief.status).toBe('empty')
    expect(result.current.news.status).toBe('empty')

    // The short-circuit: a room already known unbound must not hammer the
    // other six routes.
    expect(api.getTradingQuotes).not.toHaveBeenCalled()
    expect(api.getPolymarketOdds).not.toHaveBeenCalled()
    expect(api.getTradingDiff).not.toHaveBeenCalled()
    expect(api.getOpenTrades).not.toHaveBeenCalled()
    expect(api.getMorningBrief).not.toHaveBeenCalled()
    expect(api.getThesisNews).not.toHaveBeenCalled()
  })

  it('happy path: all slices ready with data, bound stays true', async () => {
    mockAllSuccess()
    const { result } = renderHook(() => useTradingDesk('r1'))

    await waitForAllReady(result)
    expect(result.current.bound).toBe(true)
    expect(result.current.structure.data).toEqual(structureData)
    expect(result.current.quotes.data).toEqual(quotesData)
    expect(result.current.news.data).toEqual(newsData)
  })

  it('structure only fetched once bound is known: fan-out waits on the probe', async () => {
    let resolveStructure: (v: ThesisStructure) => void = () => {}
    vi.mocked(api.getThesisStructure).mockReturnValue(
      new Promise((resolve) => { resolveStructure = resolve }),
    )
    vi.mocked(api.getTradingQuotes).mockResolvedValue(quotesData)
    vi.mocked(api.getPolymarketOdds).mockResolvedValue(polymarketData)
    vi.mocked(api.getTradingDiff).mockResolvedValue(diffData)
    vi.mocked(api.getOpenTrades).mockResolvedValue(tradesData)
    vi.mocked(api.getMorningBrief).mockResolvedValue(briefData)
    vi.mocked(api.getThesisNews).mockResolvedValue(newsData)

    renderHook(() => useTradingDesk('r1'))
    await waitFor(() => expect(api.getThesisStructure).toHaveBeenCalled())
    // Give the fan-out every chance to have fired wrongly before the probe
    // resolves — it must not have.
    await new Promise((r) => setTimeout(r, 10))
    expect(api.getTradingQuotes).not.toHaveBeenCalled()

    await act(async () => { resolveStructure(structureData) })
    await waitFor(() => expect(api.getTradingQuotes).toHaveBeenCalled())
  })

  it('502 on one slice after a prior success: that slice unavailable, keeps stale data', async () => {
    mockAllSuccess()
    const { result } = renderHook(() => useTradingDesk('r1'))
    await waitForAllReady(result)

    vi.mocked(api.getTradingQuotes).mockRejectedValue(new ApiError('bad gateway', 502))
    act(() => { result.current.refresh() })

    await waitFor(() => expect(result.current.quotes.status).toBe('unavailable'))
    expect(result.current.quotes.data).toEqual(quotesData)
    expect(result.current.quotes.error).toBeTruthy()
    // The rest of the fan-out is unaffected by one slice's failure.
    expect(result.current.structure.status).toBe('ready')
    expect(result.current.bound).toBe(true)
  })

  it('a 409 discovered mid-fan-out still marks every slice empty', async () => {
    vi.mocked(api.getThesisStructure).mockResolvedValue(structureData)
    vi.mocked(api.getTradingQuotes).mockResolvedValue(quotesData)
    vi.mocked(api.getPolymarketOdds).mockResolvedValue(polymarketData)
    vi.mocked(api.getTradingDiff).mockRejectedValue(new ApiError('unbound', 409))
    vi.mocked(api.getOpenTrades).mockResolvedValue(tradesData)
    vi.mocked(api.getMorningBrief).mockResolvedValue(briefData)
    vi.mocked(api.getThesisNews).mockResolvedValue(newsData)

    const { result } = renderHook(() => useTradingDesk('r1'))
    await waitFor(() => expect(result.current.bound).toBe(false))
    expect(result.current.structure.status).toBe('empty')
    expect(result.current.quotes.status).toBe('empty')
    expect(result.current.trades.status).toBe('empty')
  })

  it('a store stamp change refetches (structure called twice), initial hydration does not double-fetch', async () => {
    mockAllSuccess()
    storeState = { tradingConfig: { v: 3, timestamp: 't0', generatedAt: 'stamp-1' } as TradingSnapshot }

    const { rerender } = renderHook(() => useTradingDesk('r1'))
    await waitFor(() => expect(api.getThesisStructure).toHaveBeenCalledTimes(1))

    // Re-render with the SAME stamp: must not trigger a second fetch.
    rerender()
    await new Promise((r) => setTimeout(r, 10))
    expect(api.getThesisStructure).toHaveBeenCalledTimes(1)

    storeState = { tradingConfig: { v: 3, timestamp: 't1', generatedAt: 'stamp-2' } as TradingSnapshot }
    rerender()
    await waitFor(() => expect(api.getThesisStructure).toHaveBeenCalledTimes(2))
    // Quotes are on their own clock — a snapshot refetch never touches them.
    expect(api.getTradingQuotes).toHaveBeenCalledTimes(1)
  })

  it('room change abandons the previous room\'s in-flight response', async () => {
    let resolveR1: (v: ThesisStructure) => void = () => {}
    vi.mocked(api.getThesisStructure).mockImplementation((roomId: string) => {
      if (roomId === 'r1') return new Promise((resolve) => { resolveR1 = resolve })
      return Promise.resolve({ ...structureData, id: 'book-2' })
    })
    vi.mocked(api.getTradingQuotes).mockResolvedValue(quotesData)
    vi.mocked(api.getPolymarketOdds).mockResolvedValue(polymarketData)
    vi.mocked(api.getTradingDiff).mockResolvedValue(diffData)
    vi.mocked(api.getOpenTrades).mockResolvedValue(tradesData)
    vi.mocked(api.getMorningBrief).mockResolvedValue(briefData)
    vi.mocked(api.getThesisNews).mockResolvedValue(newsData)

    const { result, rerender } = renderHook(({ room }) => useTradingDesk(room), {
      initialProps: { room: 'r1' as string | null },
    })
    await waitFor(() => expect(api.getThesisStructure).toHaveBeenCalledWith('r1'))

    rerender({ room: 'r2' })
    await waitFor(() => expect(result.current.structure.data).toEqual({ ...structureData, id: 'book-2' }))

    await act(async () => { resolveR1(structureData) })
    // r1's late response must not overwrite r2's already-applied data.
    expect(result.current.structure.data).toEqual({ ...structureData, id: 'book-2' })
  })
})
