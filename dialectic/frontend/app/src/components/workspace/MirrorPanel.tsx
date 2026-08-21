import { useEffect, useMemo, useState } from 'react'
import type { MirrorDiff, MirrorRoom, MirrorVersion } from '../../types'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { api } from '../../lib/api'
import '../trading/cockpit.css'
import './MirrorPanel.css'

/**
 * The Mirror — the participant's own evolving theory of how YOU think.
 *
 * ARCHITECTURE: a reader, not a dashboard. `llm/identity.py` has been
 * rewriting a private prose model of each human, per room, since February;
 * this is the first surface that hands one back to the person it describes.
 * So the layout is a page, not a grid: one column, serif, long measure, and
 * a stepper that walks BACKWARDS through the rewrites. Everything numeric —
 * the version count, the stamp — is a readout on the chassis rail, never the
 * subject.
 *
 * WHY IT REUSES cockpit.css RATHER THAN A NEW PALETTE: the Instrument Desk
 * grammar (`.cockpit-module` chassis, `.cockpit-header`, `.cockpit-title`,
 * `.cockpit-freshness`) is the house visual language, and a surface this
 * strange needs to look like it belongs to the same machine. MirrorPanel.css
 * adds only what the desk has no shape for yet: reading typography and the
 * stepper.
 *
 * WHY THE FENCE IS NOT MENTIONED IN THE UI: `api/mirror.py` binds every
 * statement to the caller's own `user_model:` key, so there is no other
 * person's profile for this component to accidentally render. A room where
 * only the OTHER human is modelled simply does not appear in the list — the
 * component cannot tell that case from "no model here", which is the point.
 */

// The shapes live in `types/index.ts` beside every other API contract -- a
// second copy here would be a second definition of the same wire format, and
// the one that drifts is always the one nobody is looking at.

type Status = 'loading' | 'empty' | 'error' | 'ready'

function stamp(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

/** The prose is markdown-ish (`## Thinking Style`, the odd list). `marked` +
 *  DOMPurify are already dependencies and MessageBubble already renders LLM
 *  prose this exact way — same order, sanitize AFTER parse. */
function Prose({ text }: { text: string }) {
  const html = useMemo(
    () => DOMPurify.sanitize(marked.parse(text, { async: false }) as string),
    [text],
  )
  return <div className="mirror-prose" dangerouslySetInnerHTML={{ __html: html }} />
}

/** Unified-diff lines, colored by their first character. Not a merge tool —
 *  just enough to see what the machine changed its mind about. */
function Diff({ lines }: { lines: string[] }) {
  if (lines.length === 0) {
    return <div className="mirror-quiet">Rewritten, but the prose is identical.</div>
  }
  return (
    <pre className="mirror-diff" data-testid="mirror-diff">
      {lines.map((line, i) => {
        const kind = line.startsWith('+++') || line.startsWith('---') || line.startsWith('@@')
          ? 'meta'
          : line.startsWith('+') ? 'add'
          : line.startsWith('-') ? 'cut'
          : 'same'
        return (
          <span key={i} className={`mirror-diff-line mirror-diff-${kind}`}>{line || ' '}</span>
        )
      })}
    </pre>
  )
}

export function MirrorPanel() {
  const [rooms, setRooms] = useState<MirrorRoom[]>([])
  const [status, setStatus] = useState<Status>('loading')
  const [roomId, setRoomId] = useState<string | null>(null)
  // Stamped with the room it answers for, so a room switch derives back to
  // "no history yet" instead of briefly showing the previous room's rewrites.
  const [history, setHistory] = useState<{ roomId: string; versions: MirrorVersion[] } | null>(null)
  // Index into the history, which is newest-first — 0 is always "now".
  const [step, setStep] = useState(0)
  const [diff, setDiff] = useState<MirrorDiff | null>(null)

  useEffect(() => {
    let cancelled = false
    api.getMirror()
      .then((list: MirrorRoom[]) => {
        if (cancelled) return
        setRooms(list)
        setStatus(list.length ? 'ready' : 'empty')
        setRoomId(list[0]?.room_id ?? null)
      })
      .catch(() => { if (!cancelled) setStatus('error') })
    return () => { cancelled = true }
  }, [])

  // The history is fetched whole (see api/mirror.py's TRADEOFF note), so
  // stepping back is instant — no round-trip between one rewrite and the one
  // before it, which is the only way reading them in sequence feels like
  // reading rather than querying.
  useEffect(() => {
    if (!roomId) return
    let cancelled = false
    api.getMirrorVersions(roomId)
      .then((versions: MirrorVersion[]) => { if (!cancelled) setHistory({ roomId, versions }) })
      .catch(() => { if (!cancelled) setHistory({ roomId, versions: [] }) })
    return () => { cancelled = true }
  }, [roomId])

  const room = rooms.find((r) => r.room_id === roomId) ?? null
  const versions = history && history.roomId === roomId ? history.versions : []
  const shown = versions[step] ?? null
  // Before the history lands, the list's own copy of the current prose is
  // already in hand — show it rather than a spinner over a thing we have.
  const text = shown?.content ?? room?.content ?? ''
  const at = shown?.updated_at ?? room?.updated_at ?? ''
  const number = shown?.version ?? room?.version ?? 0
  const previous = versions[step + 1] ?? null

  const showDiff = () => {
    if (!roomId || !shown || !previous) return
    if (diff && diff.to_version === shown.version) { setDiff(null); return }
    api.getMirrorDiff(roomId, previous.version, shown.version)
      .then((d: MirrorDiff) => setDiff(d))
      .catch(() => setDiff(null))
  }

  if (status === 'loading') {
    return (
      <section className="cockpit-module mirror-panel" data-testid="mirror-loading">
        <div className="cockpit-header"><span className="cockpit-title">The Mirror</span></div>
        <div className="cockpit-skeleton-group">
          <div className="cockpit-skeleton cockpit-skeleton--wide" />
          <div className="cockpit-skeleton cockpit-skeleton--wide" />
          <div className="cockpit-skeleton" />
        </div>
      </section>
    )
  }

  if (status === 'error' || status === 'empty') {
    return (
      <section className="cockpit-module mirror-panel" data-testid="mirror-quiet">
        <div className="cockpit-header"><span className="cockpit-title">The Mirror</span></div>
        <div className="mirror-quiet">
          {status === 'error'
            ? 'The mirror is not answering.'
            : 'Nothing yet. The participant writes one of these after a real session.'}
        </div>
      </section>
    )
  }

  return (
    <section className="cockpit-module mirror-panel" data-testid="mirror-panel">
      <div className="cockpit-header">
        <span className="cockpit-title">The Mirror</span>
        <div className="cockpit-header-right">
          <span className="mirror-readout" title="rewrites of this profile">
            <span className="mirror-readout-value" data-testid="mirror-version">{number}</span>
            <span className="mirror-readout-unit">
              / {versions.length || room?.version || 0} REV
            </span>
          </span>
          <span className="cockpit-freshness">{at ? stamp(at) : ''}</span>
        </div>
      </div>

      {rooms.length > 1 && (
        <div className="mirror-rooms" role="tablist" aria-label="Rooms the participant models you in">
          {rooms.map((r) => (
            <button
              key={r.room_id}
              role="tab"
              type="button"
              aria-selected={r.room_id === roomId}
              className={`mirror-room${r.room_id === roomId ? ' is-current' : ''}`}
              onClick={() => { setRoomId(r.room_id); setStep(0); setDiff(null) }}
            >
              {r.room_name ?? 'Untitled room'}
            </button>
          ))}
        </div>
      )}

      <p className="mirror-preamble">
        Written by the participant, for itself. You were never the audience.
      </p>

      <Prose text={text} />

      <div className="mirror-stepper">
        <button
          type="button"
          className="mirror-step"
          disabled={step + 1 >= versions.length}
          onClick={() => { setStep((s) => s + 1); setDiff(null) }}
        >
          ◀ Earlier
        </button>
        <span className="mirror-step-where">
          {step === 0 ? 'Current' : `${step} rewrite${step === 1 ? '' : 's'} ago`}
        </span>
        <button
          type="button"
          className="mirror-step"
          disabled={step === 0}
          onClick={() => { setStep((s) => Math.max(0, s - 1)); setDiff(null) }}
        >
          Later ▶
        </button>
        <button
          type="button"
          className="mirror-step mirror-step-diff"
          disabled={!previous}
          onClick={showDiff}
        >
          {diff && shown && diff.to_version === shown.version ? 'Hide changes' : 'What changed'}
        </button>
      </div>

      {diff && shown && diff.to_version === shown.version && <Diff lines={diff.lines} />}
    </section>
  )
}
