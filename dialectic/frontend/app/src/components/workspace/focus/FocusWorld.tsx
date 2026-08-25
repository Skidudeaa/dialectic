import { useState } from 'react'
import type { WorkspaceObject } from '../../../types/workspace.ts'
import type { GeoScope } from '../../../types/geo.ts'
import type { GeoScopesState } from '../../../hooks/useGeoScopes.ts'
import { api } from '../../../lib/api.ts'
import { SourceState } from '../world/SourceState.tsx'
import { AUTHORITY_LABEL, KIND_LABEL } from '../world/worldScopes.ts'
import './Focus.css'

/**
 * FocusWorld — where this object is, and who says so (World Lens, Phase 2).
 *
 * The evidence loop the vision asks for, on the object the reader already
 * opened: the scopes whose subject IS this object, each with its authority
 * and source state; Confirm / Reject on a machine_proposed one (the
 * participant's guess becomes a person's act, or is put away); "Place" to
 * attach one of the room's own confirmed areas to this object; and "Mark"
 * to file an evidence_attachment Field mark whose subjects are the object
 * AND the scope — so the map and the Field share one row, never two
 * authorities.
 *
 * Every write goes through the existing doors (api/geo.py, api/field.py)
 * and refreshes through the caller — this component owns no projection.
 */

interface FocusWorldProps {
  roomId: string
  object: WorkspaceObject
  geo: GeoScopesState
  canAct: boolean
  onChanged: () => void
  onMarked: () => void
}

function coordinatesOf(object: WorkspaceObject): { entity: string; id: string }[] {
  return object.source_entity.map((r) => ({ entity: r.entity, id: r.id }))
}

function isAbout(scope: GeoScope, coords: { entity: string; id: string }[]): boolean {
  return coords.some((c) => c.entity === scope.subject.entity && c.id === scope.subject.id)
}

/** The areas a person may place this object on: the room's own confirmed
 *  polygons/regions/routes (never another reading's placement, never a
 *  proposal — a placement copies geometry a human already stood behind). */
function placeable(scopes: GeoScope[]): GeoScope[] {
  return scopes.filter((s) => s.authority === 'human_confirmed' && s.subject.entity === 'rooms' && s.kind !== 'point')
}

export function FocusWorld({ roomId, object, geo, canAct, onChanged, onMarked }: FocusWorldProps) {
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [placeId, setPlaceId] = useState('')

  if (geo.status !== 'ready') return null
  const coords = coordinatesOf(object)
  const mine = geo.projection.scopes.filter((s) => isAbout(s, coords))
  const options = placeable(geo.projection.scopes)
  const primary = coords[0]

  const run = async (key: string, fn: () => Promise<unknown>, after: () => void) => {
    setBusy(key)
    setError(null)
    try {
      await fn()
      after()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'That did not go through')
    } finally {
      setBusy(null)
    }
  }

  const bare = (scope: GeoScope) => scope.id.replace(/^geo_scope:/, '')

  return (
    <section className="focus-section focus-world" aria-label="World">
      <h3 className="focus-section-label">World</h3>
      {mine.length === 0 ? (
        <p className="focus-world-empty">Not placed on the world.</p>
      ) : (
        <ul className="focus-world-list">
          {mine.map((scope) => (
            <li key={scope.id} className="focus-world-row" data-authority={scope.authority}>
              <div className="focus-world-line">
                <span className="focus-world-kind">{KIND_LABEL[scope.kind]}</span>
                <span className="focus-world-label">{scope.label || 'Unlabelled'}</span>
                <span className="focus-world-authority">{AUTHORITY_LABEL[scope.authority]}</span>
                <SourceState state={scope.source_state} observedAt={scope.observed_at ?? scope.retrieved_at} />
              </div>
              <div className="focus-world-provenance">
                {scope.provenance.provider}
                {scope.provenance.credit ? ` · ${scope.provenance.credit}` : ''}
              </div>
              {canAct && scope.authority === 'machine_proposed' && (
                <div className="focus-world-actions">
                  <button
                    type="button"
                    className="btn btn-sm"
                    disabled={busy !== null}
                    onClick={() => run(`confirm:${scope.id}`, () => api.confirmGeoScope(roomId, bare(scope)), onChanged)}
                  >
                    Confirm
                  </button>
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    disabled={busy !== null}
                    onClick={() => run(`reject:${scope.id}`, () => api.rejectGeoScope(roomId, bare(scope)), onChanged)}
                  >
                    Reject
                  </button>
                </div>
              )}
              {canAct && scope.authority !== 'machine_proposed' && primary && (
                <div className="focus-world-actions">
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    disabled={busy !== null}
                    onClick={() => run(`mark:${scope.id}`, () => api.createFieldMark(roomId, {
                      relation: 'evidence_attachment',
                      subjects: [{ entity: 'geo_scopes', id: bare(scope) }, { entity: primary.entity, id: primary.id }],
                      title: `${object.title} — ${scope.label || KIND_LABEL[scope.kind]}`,
                      payload: { note: 'placed on the world' },
                    }), onMarked)}
                  >
                    Mark as evidence here
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      {canAct && primary && options.length > 0 && (
        <form
          className="focus-world-place"
          onSubmit={(e) => {
            e.preventDefault()
            const chosen = options.find((s) => s.id === placeId)
            if (!chosen) return
            void run('place', () => api.createGeoScope(roomId, {
              subject: { entity: primary.entity, id: primary.id },
              kind: chosen.kind === 'route' ? 'route' : 'region',
              geometry: chosen.geometry,
              label: chosen.label,
              provenance: {
                provider: 'room_scope',
                source_id: bare(chosen),
                credit: chosen.provenance.credit,
              },
            }), () => { setPlaceId(''); onChanged() })
          }}
        >
          <label className="focus-world-place-label">
            Place on
            <select
              className="focus-world-select"
              value={placeId}
              onChange={(e) => setPlaceId(e.target.value)}
              disabled={busy !== null}
            >
              <option value="">— an area this room holds —</option>
              {options.map((s) => (
                <option key={s.id} value={s.id}>{s.label || KIND_LABEL[s.kind]}</option>
              ))}
            </select>
          </label>
          <button type="submit" className="btn btn-sm" disabled={busy !== null || !placeId}>
            Place
          </button>
        </form>
      )}
      {error && <p className="focus-world-error" role="alert">{error}</p>}
    </section>
  )
}
