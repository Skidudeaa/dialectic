import { useEffect, useState, type ReactNode } from 'react'
import { api } from '../../lib/api.ts'
import { RELEASES, markAllSeen, readLastSeen, unreadBefore } from '../../lib/releases.ts'
import { Explain } from '../common/Explain'
import './WhatsNewPanel.css'

/**
 * What changed, and whether it is switched on for YOU.
 *
 * WHY THIS IS TWO HALVES AND NOT ONE: a changelog written entirely by hand is
 * the same instrument as the help modal that advertised "five live theses" —
 * it is a description of a system, and a description drifts away from the
 * system silently. But git history genuinely does not rot: a commit is dated,
 * append-only, and cannot un-ship.
 *
 * So the split runs THROUGH each entry rather than between entries. The prose
 * is authored (lib/releases.ts). The state beside it is read from the same
 * capabilities response CapabilityMap uses — job by job, by the job's real
 * registered name, from the running scheduler. An entry whose job is switched
 * off in this deployment says "off" in a word, and an entry that introduced no
 * scheduled work gets no badge at all rather than a green one it did not earn.
 *
 * The failure mode this forbids: shipping a list that reads like a feature tour
 * while half of it is dark on the box the reader is holding.
 */

/** `[[glossary-key|the words to underline]]`. The label is required — see Release.body. */
const TERM_MARK = /\[\[([^\]|]+)\|([^\]]+)\]\]/g

/**
 * Prose with its hard words marked.
 *
 * WHY a marker in the string rather than an array of segments: the changelog is
 * the one file in this product a human will edit under time pressure, and it has
 * to read as prose while being edited. An unknown key costs nothing — Explain
 * renders the label as plain text and no button — so a mistyped term degrades to
 * exactly the sentence that was written.
 */
function markUp(text: string): ReactNode[] {
  const out: ReactNode[] = []
  let cursor = 0
  for (const match of text.matchAll(TERM_MARK)) {
    const at = match.index ?? 0
    if (at > cursor) out.push(text.slice(cursor, at))
    out.push(
      <Explain key={`${at}-${match[1]}`} term={match[1]}>
        {match[2]}
      </Explain>,
    )
    cursor = at + match[0].length
  }
  if (cursor < text.length) out.push(text.slice(cursor))
  return out
}

type Capabilities = Awaited<ReturnType<typeof api.getRoomCapabilities>>

type JobState = 'live' | 'off' | 'absent'

/** State is a WORD first (§17.4) — a reader who cannot see the dimming reads it anyway. */
const STATE_NOTE: Record<JobState, string> = {
  // DEPLOYMENT-scoped, never room-scoped. `api/capabilities.py` builds the job
  // list from `app.state.scheduler.jobs`, which is byte-identical for every
  // room — the route is room-ADDRESSED, not room-filtered. Saying "here" told
  // the reader it was per-room, and that reading is false on the room every
  // user lands in: Home is excluded from the Round by `AND NOT r.is_home`,
  // while the job itself is enabled and would have rendered "running here".
  live: 'running on this deployment',
  off: 'installed, switched off',
  absent: 'not on this deployment',
}

/**
 * A job absent from the scheduler's own list is `absent`, never `off`. The two
 * are different facts and only one of them is a flag someone can flip. When no
 * scheduler is running the list is empty, so every job reads absent — which is
 * the honest answer, not the roster it WOULD have registered.
 */
function jobState(caps: Capabilities, name: string): JobState {
  const job = caps.jobs.find((entry) => entry.name === name)
  if (!job) return 'absent'
  return job.enabled ? 'live' : 'off'
}

export interface WhatsNewPanelProps {
  /** The room whose live job states the entries are checked against. */
  roomId: string
}

export function WhatsNewPanel({ roomId }: WhatsNewPanelProps) {
  const [caps, setCaps] = useState<Capabilities | null>(null)
  const [failed, setFailed] = useState(false)
  // Frozen at mount, deliberately: marking seen below must not make the "new"
  // marks vanish out from under the person currently reading them. Compared per
  // entry rather than taken as a count of the first N, so the marks stay correct
  // if the list is ever authored out of order.
  const [seenAtOpen] = useState(readLastSeen)

  useEffect(() => {
    markAllSeen()
  }, [])

  useEffect(() => {
    let live = true
    void api.getRoomCapabilities(roomId)
      .then((data) => { if (live) setCaps(data) })
      .catch(() => { if (live) setFailed(true) })
    return () => { live = false }
  }, [roomId])

  // Unreadable storage marks nothing new — the same rule unreadCount answers 0
  // by. Position, not date: two entries shipped on one day are both new, which
  // a date comparison cannot see. `unreadBefore` is the badge's own answer, so
  // the count in the header and the marks in the list cannot disagree.
  const newCount =
    seenAtOpen === undefined ? 0
      : seenAtOpen === null ? RELEASES.length
        : unreadBefore(seenAtOpen)
  const isNew = (index: number) => index < newCount

  return (
    <section className="whats-new" data-testid="whats-new">
      {/* No heading of its own: the panel is rendered inside HelpDialog, whose
          header already names the shelf, and the two stacked read as a stutter
          ("What changed / What changed"). A caller that ever renders this
          somewhere else supplies the heading, the same way the dialog does. */}
      <div className="wn-head">
        <p className="wn-sub">
          What shipped is written down. Whether it is switched on is read from
          the running scheduler — which is one answer for the whole deployment,
          not for this room. Whether a room qualifies for a given job is a
          separate question, and each entry says so where it matters.
        </p>
      </div>

      {failed && (
        <p className="wn-unknown" data-testid="wn-unknown">
          Could not read what is running in this room — so nothing below claims
          to be live.
        </p>
      )}

      <ol className="wn-list">
        {RELEASES.map((release, index) => (
          <li key={release.id} className="wn-entry">
            <p className="wn-entry-head">
              <time className="wn-date" dateTime={release.date}>{release.date}</time>
              <strong className="wn-title">{release.title}</strong>
              {isNew(index) && <span className="wn-new">new</span>}
            </p>
            {/* A div, not a p: an open Explain panel is a <div> child of the
                marked word, and a div inside a p is invalid markup. */}
            <div className="wn-body">{markUp(release.body)}</div>
            {caps && release.jobs && (
              <ul className="wn-jobs">
                {release.jobs.map((name) => {
                  const state = jobState(caps, name)
                  return (
                    <li key={name} className={state === 'live' ? '' : 'is-off'}>
                      <span className="wn-state">{state}</span>
                      <code className="wn-job">{name}</code>
                      <span className="wn-note">{STATE_NOTE[state]}</span>
                    </li>
                  )
                })}
              </ul>
            )}
          </li>
        ))}
      </ol>
    </section>
  )
}
