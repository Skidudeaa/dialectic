import { useEffect, useRef, useState } from 'react'
import { api } from '../../../lib/api.ts'
import { agoLabel } from '../../../lib/relativeTime.ts'
import type { MessageRef, ReadingLibraryItem } from '../../../types'
import type { WorldObservation } from '../../../types/geo.ts'
import type { FieldMark } from '../../../types/workspace.ts'
import './SurfaceUpdates.css'

/** Matches ThesisDag.tsx's DAG_DROP_MIME (out of scope to import here — see
 *  handoff notes); a card dragged onto a graph node carries the same ref
 *  shape the drop target already understands. */
const DRAG_MIME = 'application/x-dialectic-ref'
const TRAY_CAP = 30

export interface SurfaceUpdatesProps {
  roomId: string
  /** The reader's last read receipt in this room (ISO) — null means "show the latest". */
  since: string | null
  observations: WorldObservation[]
  marks: FieldMark[]
  /** The currently selected item id (an observation id, `reading:<id>` or `field_mark:<id>`), or null. */
  selectedId: string | null
  onSelect: (ref: MessageRef | null) => void
  onOpen: (ref: MessageRef) => void
  onAttach: (ref: MessageRef) => void
  attachTargetLabel: string | null
}

type ReadingsSlice =
  | { status: 'loading' }
  | { status: 'ready'; items: ReadingLibraryItem[] }
  | { status: 'unavailable'; error: string }

interface FireCard { kind: 'fire'; key: string; selId: string; ref: MessageRef; obs: WorldObservation }
interface ReadingCard { kind: 'reading'; key: string; selId: string; ref: MessageRef; item: ReadingLibraryItem }
interface MarkCard { kind: 'mark'; key: string; selId: string; ref: MessageRef; mark: FieldMark }
type Card = FireCard | ReadingCard | MarkCard

function isAfter(iso: string, since: string): boolean {
  return new Date(iso).getTime() > new Date(since).getTime()
}

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? '' : 's'}`
}

function frpOf(details: Record<string, unknown>): number {
  const n = typeof details.frp === 'number' ? details.frp : Number(details.frp)
  return Number.isFinite(n) ? n : 0
}

/**
 * "Updates since you left" — the bottom tray of the working surface: new
 * FIRMS fire cells, newly filed readings, and new Field marks since the
 * reader's last visit. A card drags onto a graph node as evidence (the drop
 * side lives in ThesisDag.tsx), or opens/attaches via its own buttons.
 */
export function SurfaceUpdates(props: SurfaceUpdatesProps) {
  const {
    roomId, since, observations, marks, selectedId, onSelect, onOpen, onAttach, attachTargetLabel,
  } = props
  const [readings, setReadings] = useState<ReadingsSlice>({ status: 'loading' })
  const ticketRef = useRef(0)

  useEffect(() => {
    const ticket = ++ticketRef.current
    void (async () => {
      await Promise.resolve()
      if (ticketRef.current !== ticket) return
      setReadings({ status: 'loading' })
      try {
        const res = await api.getReadingLibrary(roomId, { limit: 40 })
        if (ticketRef.current !== ticket) return
        setReadings({ status: 'ready', items: res.items })
      } catch (error: unknown) {
        if (ticketRef.current !== ticket) return
        setReadings({
          status: 'unavailable',
          error: error instanceof Error ? error.message : 'Could not read this room’s reading library',
        })
      }
    })()
  }, [roomId])

  const readingItems = readings.status === 'ready' ? readings.items : []

  const filteredFires = observations.filter(
    (o) => o.layer === 'fires' && (since === null || isAfter(o.first_seen_at, since)),
  )
  const novelFires = filteredFires.filter((o) => o.details.novel === true)
  const recurringFires = filteredFires.filter((o) => o.details.novel !== true)
  const sortedNovelFires = [...novelFires].sort((a, b) => frpOf(b.details) - frpOf(a.details))
  const sortedRecurringFires = [...recurringFires].sort(
    (a, b) => new Date(b.first_seen_at).getTime() - new Date(a.first_seen_at).getTime(),
  )

  const filteredReadings = readingItems.filter((r) => {
    const date = r.current_captured_at ?? r.created_at
    return since === null || isAfter(date, since)
  })
  const sortedReadings = [...filteredReadings].sort((a, b) => {
    const da = a.current_captured_at ?? a.created_at
    const db = b.current_captured_at ?? b.created_at
    return new Date(db).getTime() - new Date(da).getTime()
  })

  const filteredMarks = marks.filter((m) => since === null || isAfter(m.created_at, since))
  const sortedMarks = [...filteredMarks].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
  )

  const fireRef = (obs: WorldObservation): MessageRef => (
    { entity: 'world_observations', id: obs.id, label: `${obs.label} · ${obs.scope_label}` }
  )

  const cards: Card[] = [
    ...[...sortedNovelFires, ...sortedRecurringFires].map((obs): FireCard => ({
      kind: 'fire', key: obs.id, selId: obs.id, ref: fireRef(obs), obs,
    })),
    ...sortedReadings.map((item): ReadingCard => ({
      kind: 'reading',
      key: item.id,
      selId: `reading:${item.id}`,
      ref: { entity: 'reading_items', id: item.id, label: item.title ?? item.url },
      item,
    })),
    ...sortedMarks.map((mark): MarkCard => ({
      kind: 'mark',
      key: mark.id,
      selId: mark.id,
      ref: { entity: 'field_marks', id: mark.id.replace(/^field_mark:/, ''), label: mark.title },
      mark,
    })),
  ]
  const capped = cards.slice(0, TRAY_CAP)

  const headerTitle = since === null ? 'Latest updates' : 'Updates since you left'
  const countsLabel = [
    plural(sortedNovelFires.length, 'new fire'),
    plural(filteredReadings.length, 'reading'),
    plural(filteredMarks.length, 'mark'),
  ].join(' · ')
  const rightText = attachTargetLabel
    ? `drag onto a node to attach as evidence · tap to select · attaching to ${attachTargetLabel}`
    : 'drag onto a node to attach as evidence · tap to select'
  const emptyText = since === null ? 'Nothing recorded yet.' : 'Nothing new since you left.'

  function activate(card: Card) {
    onSelect(card.selId === selectedId ? null : card.ref)
  }

  return (
    <section className="surf-upd" aria-label={headerTitle}>
      <div className="surf-upd-header">
        <span className="surf-upd-header-title">{headerTitle} · {countsLabel}</span>
        <span className="surf-upd-header-right">{rightText}</span>
      </div>
      {readings.status === 'unavailable' && (
        <div className="surf-upd-readings-error">readings unavailable: {readings.error}</div>
      )}
      {capped.length === 0 ? (
        <div className="surf-upd-empty">{emptyText}</div>
      ) : (
        <div className="surf-upd-tray">
          {capped.map((card) => {
            const isSelected = card.selId === selectedId
            return (
              <div
                key={card.key}
                role="button"
                tabIndex={0}
                draggable
                aria-pressed={isSelected}
                className={`surf-upd-card${isSelected ? ' is-selected' : ''}`}
                onDragStart={(e) => {
                  e.dataTransfer.setData(DRAG_MIME, JSON.stringify(card.ref))
                  e.dataTransfer.setData('text/plain', card.ref.label)
                  e.dataTransfer.effectAllowed = 'link'
                }}
                onClick={() => activate(card)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    activate(card)
                  }
                }}
              >
                {card.kind === 'fire' && (
                  <>
                    <div className="surf-upd-card-kicker">
                      <span className={card.obs.details.novel === true ? 'surf-upd-fire-new' : 'surf-upd-fire-recurring'}>
                        {card.obs.details.novel === true
                          ? 'FIRE · NEW'
                          : `FIRE · recurring ${String(card.obs.details.baseline_days ?? '?')}d`}
                      </span>
                      <span className="surf-upd-card-frp">{frpOf(card.obs.details)} MW</span>
                    </div>
                    <div className="surf-upd-card-title">{card.obs.label}</div>
                    <div className="surf-upd-card-meta">
                      {String(card.obs.details.confidence ?? '')} confidence · {String(card.obs.details.satellite ?? '')}
                    </div>
                    <div className="surf-upd-card-meta">
                      {agoLabel(card.obs.first_seen_at)} · in {card.obs.scope_label}
                    </div>
                  </>
                )}
                {card.kind === 'reading' && (
                  <>
                    <div className="surf-upd-card-kicker">READING · {card.item.site ?? card.item.source}</div>
                    <div className="surf-upd-card-title">{card.item.title ?? card.item.url}</div>
                    <div className="surf-upd-card-meta">
                      saved {agoLabel(card.item.current_captured_at ?? card.item.created_at)}
                    </div>
                  </>
                )}
                {card.kind === 'mark' && (
                  <>
                    <div className="surf-upd-card-kicker">MARK · {card.mark.relation}</div>
                    <div className="surf-upd-card-title">{card.mark.title}</div>
                    <div className="surf-upd-card-meta">{card.mark.origin} · {card.mark.review}</div>
                  </>
                )}
                <div className="surf-upd-card-actions">
                  <button
                    type="button"
                    className="surf-upd-action"
                    onClick={(e) => { e.stopPropagation(); onOpen(card.ref) }}
                  >
                    open
                  </button>
                  {attachTargetLabel && (
                    <button
                      type="button"
                      className="surf-upd-action"
                      onClick={(e) => { e.stopPropagation(); onAttach(card.ref) }}
                    >
                      Attach ▸ {attachTargetLabel}
                    </button>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </section>
  )
}
