import { useMemo } from 'react'
import { PARTICIPANT_NAME } from '../../../../lib/productIdentity'
import type { MessageRef } from '../../../../types'
import { WHOLE_ROOM_TOPIC, type SurfaceAuthor, type SurfaceMsg } from '../surfaceModel'
import { SurfaceMessage } from './SurfaceMessage'
import './shapes.css'

export interface ShapeLanesProps {
  messages: SurfaceMsg[]
  /** The room's humans in column order (the reader first); may be 1..3. */
  humans: SurfaceAuthor[]
  onOpenRef: (ref: MessageRef) => void
  onReply?: (id: string) => void
}

interface Column {
  kind: 'human' | 'machine'
  id: string
  label: string
}

const MACHINE_ID = 'dialectic'

function buildColumns(humans: SurfaceAuthor[]): Column[] {
  if (humans.length === 0) return [{ kind: 'machine', id: MACHINE_ID, label: PARTICIPANT_NAME }]
  const cols: Column[] = []
  humans.forEach((h, i) => {
    cols.push({ kind: 'human', id: h.id, label: h.name })
    // The machine column sits between the first human and the rest.
    if (i === 0) cols.push({ kind: 'machine', id: MACHINE_ID, label: PARTICIPANT_NAME })
  })
  return cols
}

/** Whose turn it reads as in this band: the human whose last word here is
 *  oldest (never having spoken counts as infinitely old). With exactly one
 *  human there is no second candidate to compare against, so the rule
 *  collapses to "did they write the last word" instead. */
function whoseMove(bandMessages: SurfaceMsg[], humans: SurfaceAuthor[]): string {
  if (humans.length === 0) return '—'
  if (humans.length === 1) {
    const [h] = humans
    const last = bandMessages[bandMessages.length - 1]
    const theirsLast = last?.author.kind === 'human' && last.author.id === h.id
    return theirsLast ? 'the other side' : h.name
  }
  const lastByHuman = new Map<string, number>()
  for (const m of bandMessages) {
    if (m.author.kind === 'human') lastByHuman.set(m.author.id, new Date(m.createdAt).getTime())
  }
  let winner = humans[0]
  let winnerTime = lastByHuman.get(winner.id) ?? -Infinity
  for (const h of humans.slice(1)) {
    const t = lastByHuman.get(h.id) ?? -Infinity
    if (t < winnerTime) {
      winner = h
      winnerTime = t
    }
  }
  return winner.name
}

/**
 * The topic-lane shape: rows are the distinct things the room has been
 * discussing (the whole room last), columns are the people plus one machine
 * column — a per-band readout of who has spoken, how much of it is machine,
 * and whose move it reads as.
 */
export function ShapeLanes({ messages, humans, onOpenRef, onReply }: ShapeLanesProps) {
  const columns = useMemo(() => buildColumns(humans), [humans])

  const bands = useMemo(() => {
    const order: string[] = []
    let sawWholeRoom = false
    for (const m of messages) {
      if (m.topic === WHOLE_ROOM_TOPIC) {
        sawWholeRoom = true
        continue
      }
      if (!order.includes(m.topic)) order.push(m.topic)
    }
    if (sawWholeRoom) order.push(WHOLE_ROOM_TOPIC)
    return order.map((topic) => ({ topic, msgs: messages.filter((m) => m.topic === topic) }))
  }, [messages])

  return (
    <div className="surf-lanes">
      {bands.map(({ topic, msgs }) => {
        const machineCount = msgs.filter((m) => m.author.kind === 'machine').length
        const machinePct = msgs.length > 0 ? Math.round((machineCount / msgs.length) * 100) : 0
        return (
          <section key={topic} className="surf-lane-band">
            <header className="surf-lane-band-header">
              <span className="surf-lane-band-topic">{topic.toUpperCase()}</span>
              <span className="surf-lane-band-count">{msgs.length} msgs</span>
              <span className="surf-lane-band-machine">machine {machinePct}%</span>
              <span className="surf-lane-band-move">move: {whoseMove(msgs, humans)}</span>
            </header>
            <div
              className="surf-lane-band-grid"
              style={{ gridTemplateColumns: `140px repeat(${columns.length}, minmax(0,1fr))` }}
            >
              <div className="surf-lane-gutter" aria-hidden="true" />
              {columns.map((col) => {
                const cellMsgs = msgs.filter((m) => (
                  col.kind === 'machine' ? m.author.kind === 'machine' : m.author.id === col.id && m.author.kind === 'human'
                ))
                return (
                  <div key={`${col.kind}:${col.id}`} className="surf-lane-cell">
                    <span className="surf-lane-cell-author">{col.label}</span>
                    {cellMsgs.map((m) => (
                      <SurfaceMessage key={m.id} msg={m} onOpenRef={onOpenRef} onReply={onReply} compact />
                    ))}
                  </div>
                )
              })}
            </div>
          </section>
        )
      })}
    </div>
  )
}
