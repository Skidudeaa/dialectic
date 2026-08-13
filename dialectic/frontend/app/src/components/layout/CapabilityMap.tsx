import { useEffect, useState } from 'react'
import { api } from '../../lib/api.ts'
import { PARTICIPANT_NAME } from '../../lib/productIdentity.ts'
import './CapabilityMap.css'

/**
 * What this room can do — read from the room, not from prose about it.
 *
 * WHY THIS REPLACED THE HELP MODAL'S FACTS: the modal was the only place the
 * product explained itself, and every word was hardcoded — "five live theses",
 * a fixed daily rhythm, a fixed tool list.
 *
 * How wrong that gets, measured rather than assumed: the module docstrings and
 * CLAUDE.md both describe WIRE, NEWS_DIGEST, PREDICTION_WATCH and READING_ECHO
 * as defaulting OFF. Production's .env sets every one of them to 1. So the
 * written description and the running system disagree, and a reader had no way
 * to tell which they were looking at. A map that reads the scheduler cannot
 * drift that way, in either direction.
 *
 * WHAT STAYS WRITTEN DOWN: the durable rules. That the participant decides for
 * itself when to speak, that a branch inherits everything above it, that a
 * restatement supersedes rather than appends, that your tap is the only write —
 * none of those are state, and inventing a state field for them would be worse.
 * The split is deliberate: facts about THIS deployment are read; rules about
 * the product are told.
 */

/** Job name → what it does, in the reader's terms. */
const JOB_COPY: Record<string, { label: string; what: string }> = {
  morning_brief: {
    label: 'Morning brief',
    what: 'a catch-up each morning in rooms that saw activity — missed threads, unanswered questions, anything due',
  },
  thesis_news_digest: {
    label: 'Night reading',
    what: 'reads overnight headlines against this room’s thesis and files what holds up',
  },
  wire_watch: {
    label: 'The wire',
    what: 'watches for news that bears on the thesis and interrupts when it matters',
  },
  prediction_deadline_watch: {
    label: 'Deadline review',
    what: 'when a prediction comes due, gathers evidence and offers a verdict for you to judge',
  },
  reading_echo: {
    label: 'Echo',
    what: 'notices when something filed here bears on another room, and says so there — a citation, never a copy',
  },
  scheduler_heartbeat: {
    label: 'Heartbeat',
    what: 'the clock the rest of this list runs on',
  },
  trading_reconcile: {
    label: 'Thesis sync',
    what: 'pulls the desk’s latest thesis state so what it sees here is current',
  },
  trading_freshness_watchdog: {
    label: 'Staleness watch',
    what: 'notices when the thesis state stops arriving, so a quiet desk is not mistaken for a calm one',
  },
  participation_sweep: {
    label: 'Follow-up',
    what: 'one nudge if a question of yours goes unanswered, capped and quiet overnight',
  },
}

function cadence(job: { interval_s: number; daily_at: string | null }): string {
  if (job.daily_at) return `daily ${job.daily_at}`
  if (job.interval_s >= 3600) return `every ${Math.round(job.interval_s / 3600)}h`
  return `every ${Math.round(job.interval_s / 60)} min`
}

type Capabilities = Awaited<ReturnType<typeof api.getRoomCapabilities>>

export function CapabilityMap({ roomId }: { roomId: string }) {
  const [caps, setCaps] = useState<Capabilities | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let live = true
    void api.getRoomCapabilities(roomId)
      .then((data) => { if (live) setCaps(data) })
      .catch(() => { if (live) setFailed(true) })
    return () => { live = false }
  }, [roomId])

  return (
    <div className="capability-map" data-testid="capability-map">
      <section className="help-section">
        <h3>What {PARTICIPANT_NAME} is</h3>
        <p className="capability-prose">
          A participant, not an assistant. It reads along and decides for itself
          when it has something worth saying — a challenge, a connection, a check
          against live data. Say <strong>@{PARTICIPANT_NAME}</strong> to bring it
          in directly. <strong>@Claude</strong> and <strong>@llm</strong> still work.
        </p>
        <p className="capability-prose">
          It can prepare a change — a prediction, a thesis, a saved source — but
          your Accept is the only thing that writes. It takes no action on its own.
        </p>
      </section>

      <section className="help-section">
        <h3>In this room, right now</h3>
        {failed && (
          <p className="capability-unknown" data-testid="capability-unknown">
            Could not read this room&rsquo;s settings — so nothing is claimed
            about them here.
          </p>
        )}
        {!failed && !caps && <p className="capability-prose">Reading the room…</p>}
        {caps && (
          <ul className="capability-list">
            <li>
              <span className="capability-state">{caps.thesis_bound ? 'yes' : 'no'}</span>
              <span>
                {caps.thesis_bound
                  ? 'A thesis is bound here — its live state is in every turn, and the Bench holds it.'
                  : 'No thesis here yet. The Bench is where one gets drafted and created.'}
              </span>
            </li>
            <li>
              <span className="capability-state">
                {caps.auto_interjection ? 'on' : 'off'}
              </span>
              <span>
                {caps.auto_interjection
                  ? `${PARTICIPANT_NAME} may join without being summoned, from about ${caps.interjection_turn_threshold} turns in.`
                  : `${PARTICIPANT_NAME} speaks only when you summon it here.`}
              </span>
            </li>
          </ul>
        )}
      </section>

      <section className="help-section">
        <h3>Running in the background</h3>
        {caps && !caps.scheduler_running && (
          <p className="capability-unknown">
            No background work is running on this deployment.
          </p>
        )}
        {caps && caps.scheduler_running && (
          <ul className="capability-list">
            {caps.jobs.map((job) => {
              const copy = JOB_COPY[job.name]
              return (
                <li key={job.name} className={job.enabled ? '' : 'is-off'}>
                  <span className="capability-state">{job.enabled ? 'on' : 'off'}</span>
                  <span>
                    <strong>{copy?.label ?? job.name}</strong>
                    {copy ? ` — ${copy.what}` : ''}
                    <span className="capability-cadence"> · {cadence(job)}</span>
                  </span>
                </li>
              )
            })}
          </ul>
        )}
      </section>

      <section className="help-section">
        <h3>The parts of a room</h3>
        <ul className="capability-list capability-plain">
          <li><strong>Record</strong> — everything said, exactly, and searchable.</li>
          <li><strong>Bench</strong> — the thesis this room is building, and what is staked on it.</li>
          <li><strong>Library</strong> — the sources kept, and why each mattered.</li>
          <li><strong>Ledger</strong> — what the room takes as settled.</li>
        </ul>
        <p className="capability-prose">
          Fork any message to branch — a branch inherits everything above it, so
          you can try a line of argument without losing the one you were on.
          Restate a remembered fact and the new version supersedes the old,
          keeping its history rather than overwriting it.
        </p>
      </section>

      <section className="help-section">
        <h3>Honest limits</h3>
        <ul className="capability-list capability-plain">
          <li>A remembered number can be stale. If it matters, ask for it to be fetched live.</li>
          <li>The fallback model cannot see images or use tools, and says so.</li>
          <li>Nothing here places an order or moves money. Your tap is the only write.</li>
        </ul>
      </section>
    </div>
  )
}
