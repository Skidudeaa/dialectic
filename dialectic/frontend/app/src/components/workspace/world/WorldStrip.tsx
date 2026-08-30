import type { ReactNode } from 'react'
import { useGeoScopes } from '../../../hooks/useGeoScopes.ts'
import { useWorldObservations } from '../../../hooks/useWorldObservations.ts'
import { agoLabel } from '../../../lib/relativeTime.ts'
import './WorldStrip.css'

/**
 * The Bench's one line of World orientation, above the DAG hero (World Lens:
 * the consumer, 2026-08-30). "This is the only reason a non-Hormuz room
 * would ever discover World exists" — so a bound room with no geography
 * says so and hands over the door, rather than staying silent about a
 * feature it cannot use yet.
 *
 * SELF-CONTAINED, LIKE CapabilityMap: its own useGeoScopes + one poll of
 * useWorldObservations, rather than threading two more hook results through
 * BenchScene's props. Loading and unavailable render nothing — this is
 * orientation, not a surface that owns an error state of its own; the Bench
 * cockpit already has one (SceneUnavailable) for the projection that matters.
 */
export interface WorldStripProps {
  roomId: string
  /**
   * The existing "World ↗" door, computed and passed down from App.tsx
   * (roomGeo + the one navigate call). Rendered here, not recomputed — one
   * navigation writer, reused rather than duplicated.
   */
  worldLink?: ReactNode
}

/** `?scene=atlas` for the room already in the URL — every other axis
 *  (`room`, `thread`, …) carries over untouched. A plain link, not a
 *  useRoomNavigation call: this component does not own navigation, and the
 *  URL is already authoritative on load. */
function seedHref(): string {
  const params = new URLSearchParams(window.location.search)
  params.set('scene', 'atlas')
  return `?${params.toString()}`
}

export function WorldStrip({ roomId, worldLink }: WorldStripProps) {
  const geo = useGeoScopes(roomId)
  const observations = useWorldObservations(roomId)

  if (geo.status !== 'ready') return null
  const scopeCount = geo.projection.scopes.length

  if (scopeCount === 0) {
    return (
      <p className="world-strip world-strip-empty" data-testid="world-strip">
        No geography placed — <a href={seedHref()}>seed it</a>
      </p>
    )
  }

  const counts = observations.status === 'ready' ? observations.projection.counts : []
  const contactTotal = counts.reduce((sum, row) => sum + row.count, 0)
  const scopesWithContacts = new Set(counts.map((row) => row.scope_id)).size
  const newestAt = counts.reduce<string | null>(
    (latest, row) => (!latest || row.newest_at > latest ? row.newest_at : latest),
    null,
  )
  const age = agoLabel(newestAt)
  // Counted client-side from the rows already fetched: `details.novel` is
  // world_watch's verdict against the room's 30-day fire baseline.
  const newFires = observations.status === 'ready'
    ? observations.projection.observations.filter(
      (o) => o.layer === 'fires' && o.details.novel === true,
    ).length
    : 0

  return (
    <p className="world-strip" data-testid="world-strip">
      World · {contactTotal} contact{contactTotal === 1 ? '' : 's'} in{' '}
      {scopesWithContacts} scope{scopesWithContacts === 1 ? '' : 's'} today
      {age ? ` · last ${age}` : ''}
      {newFires > 0 ? ` · ${newFires} new fire${newFires === 1 ? '' : 's'}` : ''}
      {worldLink}
    </p>
  )
}
