import { useEffect, useState } from 'react'
import type { TradingDeskState } from '../../hooks/useTradingDesk.ts'
import { useAppStore } from '../../stores/appStore.ts'
import { PARTICIPANT_NAME } from '../../lib/productIdentity.ts'
import './Console.css'

/**
 * The Console — the instrument cluster on the right of the scene-switcher
 * tray (the docky-inspired dock: navigation tiles left, live widget tiles
 * right, a machined divider between).
 *
 * ARCHITECTURE: display-only. Every reading comes from state that already
 * exists — the lifted useTradingDesk instance (passed down, never mounted
 * here) and the store's LLM presence flags. The Console writes nothing and
 * fetches nothing; unbinding a room or losing the desk degrades tiles by
 * the same tri-state grammar the cockpit uses.
 *
 * The presence lamp is also where `--energy-level` is finally set at
 * runtime — the token shipped 2026-08-15 wired to the app-main scanline and
 * the breathe keyframe, and nothing ever moved it off 0 until now.
 */

const MAX_QUOTE_TILES = 2 // ponytail: seven-seg digits are wide; more tiles walk the divider off-screen at 1280px

type LampState = {
  word: 'ARMED' | 'THINKING' | 'STREAMING' | 'RESEARCH'
  tone: 'green' | 'amber' | 'teal'
  blink: boolean
  energy: number
  color: string
}

function lampState(thinking: boolean, streaming: boolean, research: boolean): LampState {
  if (streaming) return { word: 'STREAMING', tone: 'teal', blink: false, energy: 0.85, color: 'var(--color-teal)' }
  if (research) return { word: 'RESEARCH', tone: 'teal', blink: true, energy: 0.85, color: 'var(--color-teal)' }
  if (thinking) return { word: 'THINKING', tone: 'amber', blink: true, energy: 0.45, color: 'var(--color-amber)' }
  return { word: 'ARMED', tone: 'green', blink: false, energy: 0, color: 'var(--color-amber)' }
}

function formatPct(p: number): string {
  if (!Number.isFinite(p)) return '—'
  const pct = p > 1 ? p : p * 100 // same defensive normalization as PolymarketStrip
  return pct.toFixed(0)
}

/** Nearest future deadline among the structure's countdown-bearing nodes. */
function nextDeadline(desk: TradingDeskState): { label: string; parts: { value: string; unit: string }[] } | null {
  if (desk.structure.status !== 'ready' || !desk.structure.data) return null
  const now = Date.now()
  let best: { label: string; at: number } | null = null
  for (const node of desk.structure.data.nodes) {
    if (!node.deadline) continue
    const at = new Date(node.deadline).getTime()
    if (!Number.isFinite(at) || at <= now) continue
    if (!best || at < best.at) best = { label: node.label, at }
  }
  if (!best) return null
  const mins = Math.floor((best.at - now) / 60_000)
  const parts = mins >= 48 * 60
    ? [{ value: String(Math.floor(mins / (24 * 60))), unit: 'd' }, { value: String(Math.floor((mins % (24 * 60)) / 60)), unit: 'h' }]
    : [{ value: String(Math.floor(mins / 60)), unit: 'h' }, { value: String(mins % 60).padStart(2, '0'), unit: 'm' }]
  return { label: best.label, parts }
}

export function Console({ desk }: { desk: TradingDeskState }) {
  const isLLMThinking = useAppStore((s) => s.isLLMThinking)
  const isLLMStreaming = useAppStore((s) => s.isLLMStreaming)
  const isDeepDiveActive = useAppStore((s) => s.isDeepDiveActive)
  const lamp = lampState(isLLMThinking, isLLMStreaming, isDeepDiveActive)

  // The ambient energy scanline follows the lamp. Reset on unmount so a
  // room/scene teardown never leaves the chassis glowing.
  useEffect(() => {
    const root = document.documentElement
    root.style.setProperty('--energy-level', String(lamp.energy))
    root.style.setProperty('--energy-color', lamp.color)
    return () => { root.style.setProperty('--energy-level', '0') }
  }, [lamp.energy, lamp.color])

  // Quote direction needs a previous observation — the relay's Quote carries
  // no direction field. React's documented "adjust state when props change"
  // pattern: compare against the last-seen quotes array during render and
  // fold each price into the baseline; neutral on first observation.
  const quotesData = desk.quotes.status === 'ready' ? (desk.quotes.data ?? null) : null
  const [quoteTrack, setQuoteTrack] = useState<{
    seen: typeof quotesData
    dirs: Record<string, 'up' | 'down' | 'flat'>
    prices: Record<string, number>
  }>({ seen: null, dirs: {}, prices: {} })
  if (quotesData && quotesData !== quoteTrack.seen) {
    const nextDirs: Record<string, 'up' | 'down' | 'flat'> = {}
    const nextPrices = { ...quoteTrack.prices }
    for (const q of quotesData) {
      const prev = quoteTrack.prices[q.symbol]
      nextDirs[q.symbol] = prev === undefined || prev === q.price ? 'flat' : q.price > prev ? 'up' : 'down'
      nextPrices[q.symbol] = q.price
    }
    setQuoteTrack({ seen: quotesData, dirs: nextDirs, prices: nextPrices })
  }
  const dirs = quoteTrack.dirs

  const quotes = (desk.quotes.data ?? []).slice(0, MAX_QUOTE_TILES)
  const quotesStale = desk.quotes.status === 'unavailable'
  const odd = (desk.polymarket.data ?? [])[0]
  const upNext = nextDeadline(desk)

  return (
    <div className="console" role="group" aria-label="Instruments">
      {desk.bound && (
        <>
          {desk.quotes.status === 'loading' && <div className="console-tile console-tile-skeleton" aria-hidden="true" />}
          {quotes.map((q) => {
            const dir = dirs[q.symbol] ?? 'flat'
            return (
              <div key={q.symbol} className={`console-tile console-quote${quotesStale ? ' is-stale' : ''}`} title={quotesStale ? `Stale: ${desk.quotes.error}` : q.source}>
                <span className="console-tile-label">{q.symbol}</span>
                <span className="console-readout">
                  <span className="seg">{q.price.toFixed(2)}</span>
                  <span className={`console-dir console-dir-${dir}`} aria-hidden="true">
                    {dir === 'up' ? '▲' : dir === 'down' ? '▼' : '·'}
                  </span>
                  <span className="visually-hidden">{dir === 'flat' ? '' : dir}</span>
                </span>
              </div>
            )
          })}
          {odd && (
            <div className="console-tile console-odds" title={odd.slug}>
              <span className="console-tile-label">POLY</span>
              <span className="console-readout">
                <span className="seg">{formatPct(odd.probability)}</span>
                <span className="console-unit">%</span>
              </span>
              <span className="console-ledbar" aria-hidden="true">
                {Array.from({ length: 10 }, (_, i) => (
                  <i key={i} className={i < Math.round((odd.probability > 1 ? odd.probability : odd.probability * 100) / 10) ? 'lit' : ''} />
                ))}
              </span>
            </div>
          )}
          {upNext && (
            <div className="console-tile console-upnext" title={`Next deadline: ${upNext.label}`}>
              <span className="console-tile-label">UP NEXT · {upNext.label}</span>
              <span className="console-readout">
                {upNext.parts.map((part) => (
                  <span key={part.unit}>
                    <span className="seg">{part.value}</span>
                    <span className="console-unit">{part.unit}</span>
                  </span>
                ))}
              </span>
            </div>
          )}
        </>
      )}
      <div className={`console-lamp console-lamp-${lamp.tone}`}>
        <span className="console-tile-label">{PARTICIPANT_NAME}</span>
        <span className="console-lamp-row">
          <span className={`console-led${lamp.blink ? ' is-blinking' : ''}`} aria-hidden="true" />
          <span className="console-lamp-word">{lamp.word}</span>
        </span>
      </div>
    </div>
  )
}
