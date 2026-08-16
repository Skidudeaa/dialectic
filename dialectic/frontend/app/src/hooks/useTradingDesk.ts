import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../lib/api.ts'
import { useAppStore } from '../stores/appStore.ts'
import { useDocumentVisibility } from './useDocumentVisibility.ts'
import type {
  MorningBrief,
  OpenTrades,
  PolymarketOdd,
  Quote,
  ThesisDiff,
  ThesisNews,
  ThesisStructure,
  TradingSlice,
} from '../types/trading.ts'

// Quotes are the only slice on their own clock (design v2 §12.4) — a live
// price does not wait for a snapshot push, but it also should not be hammered
// faster than the desk's own refresh cadence.
const QUOTES_POLL_MS = 300_000

type SliceKey = 'structure' | 'quotes' | 'polymarket' | 'diff' | 'trades' | 'brief' | 'news'
type FanOutKey = Exclude<SliceKey, 'structure'>

// The stamp-triggered refetch (a new trading snapshot landed) touches every
// slice EXCEPT quotes (own clock) and polymarket (not snapshot-derived).
const SNAPSHOT_KEYS: SliceKey[] = ['structure', 'diff', 'trades', 'brief', 'news']
const ALL_FAN_OUT_KEYS: FanOutKey[] = ['quotes', 'polymarket', 'diff', 'trades', 'brief', 'news']

interface Slices {
  structure: TradingSlice<ThesisStructure>;
  quotes: TradingSlice<Quote[]>;
  polymarket: TradingSlice<PolymarketOdd[]>;
  diff: TradingSlice<ThesisDiff>;
  trades: TradingSlice<OpenTrades>;
  brief: TradingSlice<MorningBrief>;
  news: TradingSlice<ThesisNews>;
  bound: boolean;
}

export interface TradingDeskState extends Slices {
  refresh: () => void;
}

function emptySlices(bound: boolean): Slices {
  return {
    structure: { status: 'empty' },
    quotes: { status: 'empty' },
    polymarket: { status: 'empty' },
    diff: { status: 'empty' },
    trades: { status: 'empty' },
    brief: { status: 'empty' },
    news: { status: 'empty' },
    bound,
  }
}

// Optimistic: assumed bound until a fetch proves otherwise (409). Every slice
// starts loading rather than empty — a room mid-probe is not yet known to
// have "nothing", which is the exact conflation design v2 §7.5-style tri-
// state rules exist to prevent.
function loadingSlices(): Slices {
  return {
    structure: { status: 'loading' },
    quotes: { status: 'loading' },
    polymarket: { status: 'loading' },
    diff: { status: 'loading' },
    trades: { status: 'loading' },
    brief: { status: 'loading' },
    news: { status: 'loading' },
    bound: true,
  }
}

type FetchOutcome = 'ok' | 'unbound' | 'error' | 'stale';

/** Per-room API calls, built fresh each cycle so every closure captures the
 * right roomId (never the one a stale ticket left behind). */
function sliceCalls(roomId: string): Record<SliceKey, () => Promise<unknown>> {
  return {
    structure: () => api.getThesisStructure(roomId),
    quotes: () => api.getTradingQuotes(roomId),
    polymarket: () => api.getPolymarketOdds(roomId),
    diff: () => api.getTradingDiff(roomId),
    trades: () => api.getOpenTrades(roomId),
    brief: () => api.getMorningBrief(roomId),
    news: () => api.getThesisNews(roomId),
  }
}

/**
 * useTradingDesk — the cockpit's one data source, fanning out across the
 * seven trading-relay reads with the tri-state every slice must report
 * (design v2 §12.4: loading / ready / empty / unavailable are distinct —
 * "empty" is a positive "nothing here", never a stand-in for "the fetch
 * failed"). Components decide how to render an empty slice; this hook only
 * reports transport truth.
 *
 * ARCHITECTURE: `structure` is probed FIRST on every full cycle. A 409 means
 * the room holds no bound thesis, and firing the other six routes anyway
 * would hammer an endpoint we already know will refuse every one of them —
 * so the fan-out only happens once structure comes back non-409.
 */
export function useTradingDesk(roomId: string | null): TradingDeskState {
  const [slices, setSlices] = useState<Slices>(() => (roomId ? loadingSlices() : emptySlices(false)))

  // Identifies the fetch cycle a still-pending response belongs to. A room
  // switch (or manual refresh) while requests are in flight must not paint a
  // stale room's data into the new one — same idiom as useWorkspaceObjects.
  const requestRef = useRef(0)

  const applyUnbound = useCallback(() => {
    setSlices(emptySlices(false))
  }, [])

  const fetchSlice = useCallback(
    async <T,>(
      key: SliceKey,
      ticket: number,
      call: () => Promise<T>,
    ): Promise<FetchOutcome> => {
      try {
        const data = await call()
        if (requestRef.current !== ticket) return 'stale'
        setSlices((prev) => ({ ...prev, [key]: { status: 'ready', data, fetchedAt: Date.now() } }))
        return 'ok'
      } catch (err) {
        if (requestRef.current !== ticket) return 'stale'
        if (err instanceof ApiError && err.status === 409) return 'unbound'
        const message = err instanceof Error ? err.message : 'Request failed'
        // Stale-but-shown: keep the last good data and fetchedAt rather than
        // blanking a slice a transient 502 or network error just interrupted.
        setSlices((prev) => ({
          ...prev,
          [key]: { status: 'unavailable', error: message, data: prev[key].data, fetchedAt: prev[key].fetchedAt },
        }));
        return 'error'
      }
    },
    [],
  )

  const runCycle = useCallback(
    async (roomIdForCycle: string, keys: SliceKey[], ticket: number) => {
      const calls = sliceCalls(roomIdForCycle)
      const includesStructure = keys.includes('structure')
      const fanOut = keys.filter((k): k is FanOutKey => k !== 'structure')

      if (includesStructure) {
        const outcome = await fetchSlice('structure', ticket, calls.structure as () => Promise<ThesisStructure>)
        if (requestRef.current !== ticket) return
        if (outcome === 'unbound') {
          applyUnbound()
          return
        }
      }

      if (fanOut.length === 0) return
      const results = await Promise.all(
        fanOut.map((key) => fetchSlice(key, ticket, calls[key] as () => Promise<unknown>)),
      )
      if (requestRef.current !== ticket) return
      if (results.includes('unbound')) applyUnbound()
    },
    [applyUnbound, fetchSlice],
  )

  // Room change (including the initial mount) blanks every slice to loading
  // — it is a genuinely different room, so the previous room's data has no
  // business surviving onscreen while the new one loads.
  const stampRef = useRef<string | undefined>(undefined)
  useEffect(() => {
    const ticket = ++requestRef.current
    stampRef.current = undefined
    if (!roomId) {
      const timeout = window.setTimeout(() => {
        if (requestRef.current === ticket) setSlices(emptySlices(false))
      }, 0)
      return () => window.clearTimeout(timeout)
    }
    const timeout = window.setTimeout(() => {
      if (requestRef.current !== ticket) return
      setSlices(loadingSlices())
      void runCycle(roomId, ['structure', ...ALL_FAN_OUT_KEYS], ticket)
    }, 0)
    return () => window.clearTimeout(timeout)
  }, [roomId, runCycle])

  // Manual refresh() re-runs the full cycle for the SAME room, in the
  // background — no loading blank, so a slice that is still ready keeps
  // showing its data until (and unless) the refetch replaces or fails it,
  // same stale-but-shown contract as any other refetch.
  const refresh = useCallback(() => {
    if (!roomId) return
    const ticket = ++requestRef.current
    void runCycle(roomId, ['structure', ...ALL_FAN_OUT_KEYS], ticket)
  }, [roomId, runCycle])

  // Refetch on a new trading snapshot: subscribe to the store's tradingConfig
  // and diff its stamp. The first observation for a room only baselines the
  // ref — it never fetches — so a store that was already hydrated when this
  // hook mounted doesn't double the room-change effect's own fetch.
  const tradingConfig = useAppStore((s) => s.tradingConfig)
  useEffect(() => {
    if (!roomId) return
    const stamp = tradingConfig?.generatedAt ?? tradingConfig?.timestamp
    const prevStamp = stampRef.current
    stampRef.current = stamp
    if (prevStamp === undefined) return
    if (stamp !== undefined && stamp !== prevStamp) {
      const timeout = window.setTimeout(() => {
        const ticket = ++requestRef.current
        void runCycle(roomId, SNAPSHOT_KEYS, ticket)
      }, 0)
      return () => window.clearTimeout(timeout)
    }
  }, [tradingConfig, roomId, runCycle])

  // Quotes poll every 300s while bound and the tab is visible. Nothing else
  // rides this clock.
  const visible = useDocumentVisibility()
  useEffect(() => {
    if (!roomId || !slices.bound || !visible) return
    const roomIdForPoll = roomId
    const id = window.setInterval(() => {
      const ticket = requestRef.current
      void fetchSlice('quotes', ticket, () => api.getTradingQuotes(roomIdForPoll) as Promise<Quote[]>).then(
        (outcome) => { if (outcome === 'unbound') applyUnbound() },
      )
    }, QUOTES_POLL_MS)
    return () => window.clearInterval(id)
  }, [roomId, slices.bound, visible, fetchSlice, applyUnbound])

  return { ...slices, refresh }
}
