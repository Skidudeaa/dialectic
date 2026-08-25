import type { GeoSourceState } from '../../../types/geo.ts'
import './SourceState.css'

/**
 * The evidence-state chip: what a surface says about how much to trust a
 * reading of the world, in the vocabulary the backend already uses
 * (geo_scopes.GEO_SOURCE_STATES = the news/polymarket statuses plus
 * `confirmed_empty`). Text first, tone second — the word is the signal and
 * the color only agrees with it, so the chip survives grayscale.
 *
 * `observedAt` renders as an age ("14h ago") because an observation's age is
 * the number a reader needs beside its state; a cached marker is never shown
 * as a current one (vision: "no cached marker presented as a current
 * observation").
 */
const LABEL: Record<GeoSourceState, string> = {
  ok: 'live',
  partial: 'partial',
  confirmed_empty: 'confirmed empty',
  stale: 'stale',
  unavailable: 'unavailable',
  rate_limited: 'rate limited',
  not_configured: 'not configured',
}

const TONE: Record<GeoSourceState, 'good' | 'warn' | 'off'> = {
  ok: 'good',
  partial: 'warn',
  confirmed_empty: 'off',
  stale: 'warn',
  unavailable: 'off',
  rate_limited: 'warn',
  not_configured: 'off',
}

function formatAge(iso: string | null | undefined, now: number = Date.now()): string | null {
  if (!iso) return null
  const t = new Date(iso).getTime()
  if (!Number.isFinite(t)) return null
  const s = Math.max(0, Math.round((now - t) / 1000))
  if (s < 60) return 'just now'
  const m = Math.round(s / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.round(m / 60)
  if (h < 48) return `${h}h ago`
  return `${Math.round(h / 24)}d ago`
}

export function SourceState({ state, observedAt }: { state: GeoSourceState; observedAt?: string | null }) {
  const age = formatAge(observedAt)
  return (
    <span className="source-state" data-tone={TONE[state]} data-state={state}>
      <span className="source-state-word">{LABEL[state]}</span>
      {age && <span className="source-state-age">· {age}</span>}
    </span>
  )
}
