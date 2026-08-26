import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../../../lib/api.ts'
import type { GeoScope, GeoScopeReview, GeoSubjectDestination } from '../../../types/geo.ts'
import type { ThesisStructure } from '../../../types/trading.ts'
import type { FieldRelation } from '../../../types/workspace.ts'
import { AUTHORITY_LABEL, KIND_LABEL } from '../world/worldScopes.ts'
import { FocusHeader } from './FocusHeader.tsx'
import { SceneLoading } from '../SceneEmpty.tsx'
import './Focus.css'

interface ScopeReviewProps {
  roomId: string
  scopeId: string
  canAct: boolean
  onClose: () => void
  onNavigate: (target: {
    threadId?: string
    messageId?: string
    object: string | null
    historyMode?: 'push' | 'replace'
  }) => void
  onChanged: () => void
  onMarked: () => void
}

function bareScopeId(id: string): string {
  return id.replace(/^geo_scope:/, '')
}

function humanize(value: string): string {
  const text = value.replaceAll('_', ' ')
  return text.charAt(0).toUpperCase() + text.slice(1)
}

function vertexCount(value: unknown): number {
  if (!Array.isArray(value)) return 0
  if (value.length >= 2 && typeof value[0] === 'number' && typeof value[1] === 'number') return 1
  return value.reduce((sum, child) => sum + vertexCount(child), 0)
}

function geometrySummary(scope: GeoScope): string {
  return `${scope.geometry.type} · ${vertexCount(scope.geometry.coordinates)} vertices`
}

function dateOnly(value: string): string {
  return value.slice(0, 10)
}

function subjectLabel(scope: GeoScope): string {
  return `${humanize(scope.subject.entity)} · ${scope.subject.id}`
}

function destinationLabel(destination: GeoSubjectDestination): string {
  const parts = [`Room ${destination.room_id}`]
  if (destination.thread_id) parts.push(`thread ${destination.thread_id}`)
  if (destination.message_id) parts.push(`message ${destination.message_id}`)
  if (destination.object_id) parts.push(`object ${destination.object_id}`)
  return parts.join(' · ')
}

function isHttpUrl(value: string): boolean {
  try {
    const protocol = new URL(value).protocol
    return protocol === 'http:' || protocol === 'https:'
  } catch {
    return false
  }
}

function ScopeProvenance({ scope, label }: { scope: GeoScope; label: string }) {
  const provenance = scope.provenance
  return (
    <dl className="scope-review-provenance" role="group" aria-label={`${label} provenance`}>
      <div><dt>Provider</dt><dd>{provenance.provider}</dd></div>
      <div><dt>Acquisition</dt><dd>{provenance.acquisition}</dd></div>
      <div><dt>Source ID</dt><dd>{provenance.source_id || 'Not supplied'}</dd></div>
      <div>
        <dt>Exact URL</dt>
        <dd>
          {provenance.url && isHttpUrl(provenance.url)
            ? <a href={provenance.url}>{provenance.url}</a>
            : (provenance.url || 'Not supplied')}
        </dd>
      </div>
      <div><dt>Credit</dt><dd>{provenance.credit || 'Not supplied'}</dd></div>
    </dl>
  )
}

function navigateToSubject(
  destination: GeoSubjectDestination,
  onNavigate: ScopeReviewProps['onNavigate'],
): void {
  onNavigate({
    ...(destination.thread_id ? { threadId: destination.thread_id } : {}),
    ...(destination.message_id ? { messageId: destination.message_id } : {}),
    object: destination.object_id ?? null,
  })
}

export function ScopeReview({
  roomId, scopeId, canAct, onClose, onNavigate, onChanged, onMarked,
}: ScopeReviewProps) {
  const [review, setReview] = useState<GeoScopeReview | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [note, setNote] = useState('')
  const [redrawing, setRedrawing] = useState(false)
  const [redrawLabel, setRedrawLabel] = useState('')
  const [redrawGeometry, setRedrawGeometry] = useState('')
  const [binding, setBinding] = useState(false)
  const [bindingBusy, setBindingBusy] = useState(false)
  const [structure, setStructure] = useState<ThesisStructure | null>(null)
  const [causalRelation, setCausalRelation] = useState<FieldRelation>('supports')
  const [nodeId, setNodeId] = useState('')
  const requestRef = useRef(0)
  const bindingRequestRef = useRef(0)
  const canonicalizedRef = useRef<string | null>(null)

  const load = useCallback(async () => {
    const ticket = ++requestRef.current
    bindingRequestRef.current += 1
    setBinding(false)
    setBindingBusy(false)
    setStructure(null)
    setNodeId('')
    await Promise.resolve()
    if (requestRef.current !== ticket) return
    setLoading(true)
    setError(null)
    try {
      const next = await api.getGeoScopeReview(roomId, bareScopeId(scopeId))
      if (requestRef.current !== ticket) return
      setReview(next)
    } catch (err) {
      if (requestRef.current !== ticket) return
      setError(err instanceof Error ? err.message : 'Could not read this scope')
    } finally {
      if (requestRef.current === ticket) setLoading(false)
    }
  }, [roomId, scopeId])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (!review || review.root_id === scopeId) return
    const key = `${scopeId}|${review.root_id}`
    if (canonicalizedRef.current === key) return
    canonicalizedRef.current = key
    onNavigate({ object: review.root_id, historyMode: 'replace' })
  }, [onNavigate, review, scopeId])

  const run = async (write: (currentId: string) => Promise<unknown>) => {
    if (!review) return
    setBusy(true)
    setError(null)
    try {
      await write(bareScopeId(review.current.id))
      await load()
      setNote('')
      setRedrawing(false)
      onChanged()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'That review did not go through')
    } finally {
      setBusy(false)
    }
  }

  const openBinding = async () => {
    const ticket = ++bindingRequestRef.current
    setBindingBusy(true)
    setError(null)
    try {
      const next = await api.getThesisStructure(roomId)
      if (bindingRequestRef.current !== ticket) return
      if (!Array.isArray(next.nodes) || next.nodes.length === 0) {
        throw new Error('This thesis has no nodes to bind.')
      }
      setStructure(next)
      setNodeId(next.nodes[0].id)
      setBinding(true)
    } catch (err) {
      if (bindingRequestRef.current !== ticket) return
      setStructure(null)
      setBinding(false)
      setError(err instanceof Error ? err.message : 'Thesis structure is unavailable')
    } finally {
      if (bindingRequestRef.current === ticket) setBindingBusy(false)
    }
  }

  const createBinding = async () => {
    if (!structure || !review) return
    const node = structure.nodes.find((candidate) => candidate.id === nodeId)
    if (!node) return
    setBindingBusy(true)
    setError(null)
    try {
      await api.createFieldMark(roomId, {
        relation: causalRelation,
        subjects: [
          { entity: 'geo_scopes', id: bareScopeId(review.current.id) },
          {
            entity: 'rooms', id: roomId,
            field: `thesis_node:${structure.id}:${node.id}`,
          },
        ],
        title: `${review.current.label || 'GeoScope'} ${causalRelation} ${node.label}`,
        payload: { node_label: node.label },
      })
      setBinding(false)
      onMarked()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not add this binding to Field')
    } finally {
      setBindingBusy(false)
    }
  }

  if (loading && !review) return <SceneLoading kicker="Scope review" />
  if (!review) {
    return (
      <>
        <FocusHeader title="Scope unavailable" kindLabel="World placement" onClose={onClose} />
        <p className="focus-actions-error" role="alert">{error || 'This scope is not available.'}</p>
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => void load()}>Try again</button>
      </>
    )
  }

  const current = review.current
  const proposed = current.review_state === 'proposed'
  const accepted = current.review_state === 'accepted'
  const currentIsLive = current.freshness.state !== 'expired'
  const bindable = accepted && currentIsLive
  const bindingLoading = bindingBusy && !binding
  const canRatify = accepted && (
    current.revision_action === 'place' || current.revision_action === 'place_signal'
  ) && current.supersedes_id === null

  return (
    <>
      <FocusHeader
        title={current.label || 'Unlabelled placement'}
        kindLabel={`World placement · ${KIND_LABEL[current.kind]}`}
        onClose={onClose}
      />
      <button
        type="button"
        className="btn btn-ghost btn-sm focus-open-subject"
        onClick={() => navigateToSubject(review.subject_destination, onNavigate)}
      >
        Open subject
      </button>
      <p className="scope-review-subject">{subjectLabel(current)}</p>
      <p className="scope-review-destination">{destinationLabel(review.subject_destination)}</p>
      <dl className="scope-review-axes" aria-label="Scope state">
        <div><dt>Authority</dt><dd>{AUTHORITY_LABEL[current.authority]}</dd></div>
        <div><dt>Source condition</dt><dd>{humanize(current.source_state)}</dd></div>
        <div><dt>Freshness</dt><dd>{humanize(current.freshness.state)}</dd></div>
        <div><dt>Review decision</dt><dd>{humanize(current.review_state)}</dd></div>
      </dl>
      <section className="focus-section scope-review-current" aria-label="Current placement">
        <h3 className="focus-section-label">Current placement</h3>
        <p>{geometrySummary(current)} · centroid {current.centroid.join(', ')}</p>
        <ScopeProvenance scope={current} label="Current placement" />
      </section>
      <section className="focus-section" aria-label="Scope lineage">
        <h3 className="focus-section-label">History</h3>
        <ol className="scope-review-history" aria-label="Scope history">
          {review.lineage.map((scope) => (
            <li key={scope.id} className="scope-review-history-row" data-review={scope.review_state}>
              <div className="scope-review-history-head">
                <time dateTime={scope.created_at}>{dateOnly(scope.created_at)}</time>
                <strong>{humanize(scope.revision_action)}</strong>
                <span>{scope.created_by ?? scope.confirmed_by ?? 'system'}</span>
              </div>
              <div>{scope.label || 'Unlabelled'} · {geometrySummary(scope)}</div>
              <ScopeProvenance scope={scope} label={scope.label || 'Unlabelled placement'} />
              {scope.review_note ? <p className="scope-review-note">{scope.review_note}</p> : null}
            </li>
          ))}
        </ol>
      </section>
      {canAct && currentIsLive && (proposed || accepted) ? (
        <section className="focus-section scope-review-actions" aria-label="Scope actions">
          <h3 className="focus-section-label">Review</h3>
          <label className="scope-review-note-label">
            Review note
            <textarea value={note} onChange={(event) => setNote(event.target.value)} disabled={busy} />
          </label>
          <div className="focus-actions-row">
            {proposed ? (
              <>
                <button type="button" className="btn btn-sm" disabled={busy} onClick={() => void run((id) => api.confirmGeoScope(roomId, id, note))}>Confirm</button>
                <button type="button" className="btn btn-ghost btn-sm" disabled={busy} onClick={() => void run((id) => api.rejectGeoScope(roomId, id, note))}>Reject</button>
              </>
            ) : null}
            {canRatify ? (
              <button type="button" className="btn btn-sm" disabled={busy} onClick={() => void run((id) => api.ratifyGeoScope(roomId, id, note))}>Ratify</button>
            ) : null}
            {accepted ? (
              <>
                {bindable ? (
                  <button
                    type="button"
                    className="btn btn-sm"
                    disabled={busy || bindingBusy}
                    aria-busy={bindingLoading}
                    onClick={() => void openBinding()}
                  >
                    {bindingLoading ? 'Loading thesis structure…' : 'Bind to thesis node'}
                  </button>
                ) : null}
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  disabled={busy}
                  onClick={() => {
                    setRedrawLabel(current.label)
                    setRedrawGeometry(JSON.stringify(current.geometry))
                    setRedrawing(true)
                  }}
                >
                  Redraw
                </button>
                <button type="button" className="btn btn-ghost btn-sm" disabled={busy} onClick={() => void run((id) => api.supersedeGeoScope(roomId, id, note))}>Supersede</button>
              </>
            ) : null}
          </div>
          {bindingLoading ? <p role="status">Loading thesis structure…</p> : null}
          {binding && structure ? (
            <form
              className="focus-actions-editor scope-review-causal"
              onSubmit={(event) => {
                event.preventDefault()
                void createBinding()
              }}
            >
              <label>
                Causal relation
                <select
                  value={causalRelation}
                  disabled={bindingBusy}
                  onChange={(event) => setCausalRelation(event.target.value as FieldRelation)}
                >
                  <option value="supports">Supports</option>
                  <option value="challenges">Challenges</option>
                  <option value="context">Context</option>
                </select>
              </label>
              <label>
                Thesis node
                <select
                  value={nodeId}
                  disabled={bindingBusy}
                  onChange={(event) => setNodeId(event.target.value)}
                >
                  {structure.nodes.map((node) => (
                    <option key={node.id} value={node.id}>{node.label}</option>
                  ))}
                </select>
              </label>
              <button type="submit" className="btn btn-sm" disabled={bindingBusy || !nodeId}>
                Add to Field
              </button>
            </form>
          ) : null}
          {redrawing ? (
            <form
              className="scope-review-redraw"
              onSubmit={(event) => {
                event.preventDefault()
                try {
                  const geometry = JSON.parse(redrawGeometry) as unknown
                  void run((id) => api.redrawGeoScope(roomId, id, {
                    label: redrawLabel, geometry, note,
                  }))
                } catch {
                  setError('Geometry must be valid GeoJSON.')
                }
              }}
            >
              <label>Placement label<input value={redrawLabel} onChange={(event) => setRedrawLabel(event.target.value)} /></label>
              <label>GeoJSON geometry<textarea value={redrawGeometry} onChange={(event) => setRedrawGeometry(event.target.value)} /></label>
              <button type="submit" className="btn btn-sm" disabled={busy || !redrawLabel.trim()}>Save redraw</button>
            </form>
          ) : null}
        </section>
      ) : null}
      {error ? <p className="focus-actions-error" role="alert">{error}</p> : null}
    </>
  )
}
