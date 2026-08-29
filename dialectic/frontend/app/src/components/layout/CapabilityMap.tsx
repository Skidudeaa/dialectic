import { useEffect, useState } from 'react'
import { api } from '../../lib/api.ts'
import { PARTICIPANT_NAME } from '../../lib/productIdentity.ts'
import { Explain } from '../common/Explain'
import { GLOSSARY } from '../../lib/glossary'
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
 *
 * THE ROT FENCE: JOB_COPY must name every job the scheduler registers, and
 * tests/test_capability_copy_contract.py fails the build when it does not. It
 * finds the roster by IMPORTING api/main.py's register functions and running
 * them against a real Scheduler, so the roster is the one the app boots with
 * and not a list someone remembered to update. Six of fifteen jobs — the Round,
 * the house forecast, settlement, the watchlist wire, disclosures and field
 * marks — rendered to the reader as raw snake_case until 2026-08-21, which is
 * the same failure as the hardcoded modal wearing different clothes.
 */

interface JobCopy {
  label: string
  what: string
  /** Glossary key, when the label is a term this product defines elsewhere. */
  term?: string
  /** Why this job ships dark, shown only while it is off. */
  off?: string
  /**
   * The weekday of a job whose real rhythm lives in its BODY, where the Job
   * dataclass cannot see it.
   *
   * There is exactly one today and it is not a nicety: `question_round` is
   * registered `daily_at="09:00"` because the scheduler has interval buckets
   * and wall-clock daily slots but no weekly cadence — `is_round_day()` returns
   * immediately on the other six mornings. Rendering the scheduler's own field
   * printed "daily 09:00" on the help screen, which is a lie the reader has no
   * way to check, about the one feature they are being asked to show up for.
   *
   * WHY ONLY THE WEEKDAY, AND NEVER THE TIME: the first version of this fix
   * wrote the whole string — `'Sundays 09:00'` — which re-introduces at small
   * scale the exact drift it exists to correct. Change `daily_at` to 10:00 and
   * the screen keeps promising 09:00, with a test pinning the lie in place.
   * The weekday is genuinely unreadable and so is TOLD; the time is right there
   * on the job and so is READ. Every part of a displayed fact comes from
   * whichever side actually knows it.
   */
  weeklyOn?: string
}

/** Job name → what it does, in the reader's terms. */
const JOB_COPY: Record<string, JobCopy> = {
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
  rss_wire: {
    label: 'Watchlist feeds',
    what: 'reads the feeds this room watches and files what bears on the thesis — spending the same daily interruption budget as the wire, not a second one',
    off: 'no room lists a feed to watch yet; it stays dark until one does.',
  },
  congress_watch: {
    label: 'Disclosures',
    what: 'congressional stock filings, kept only where this room’s thesis already names the ticker — filed to the Library rather than interrupting, though the Library is read by the morning brief and by Echo',
    off: 'dark until the filings dataset is verified.',
  },
  question_round: {
    label: 'The Round',
    term: 'round',
    what: 'drafts a slate of forecastable questions for a room with two forecasters in it — each binary, each with a named resolution source and a hard close date',
    weeklyOn: 'Sundays',
  },
  house_forecast_sweep: {
    label: 'The house forecast',
    term: 'house',
    what: 'the participant answers each open question itself, sealed like yours until you have both committed — a few at a time, so one long think cannot hold up the rest of this list',
  },
  round_close_watch: {
    label: 'Settlement',
    term: 'settlement',
    what: 'when a question closes, reads the source it named and offers a verdict — it never resolves anything itself',
  },
  prediction_deadline_watch: {
    label: 'Deadline review',
    what: 'when a prediction comes due, gathers evidence and offers a verdict for you to judge',
  },
  world_signals: {
    label: 'Live world signals',
    term: 'world-signal',
    what: 'polls public feeds — aircraft, earthquakes, fires, satellites, launches — for the areas your rooms have actually placed on the map, and shows what is there right now; each observation expires on its own, and placing one is yours alone',
    off: 'nothing reads what it gathers yet, so it stays dark rather than poll unseen.',
  },
  field_inference: {
    label: 'Field marks',
    term: 'field-mark',
    what: 'pencils in provisional marks about the room’s reasoning for you to confirm or contest — capped per run and per day, so a quiet room never wakes up covered in them',
  },
  reading_echo: {
    // No `term`: the marker wraps the LABEL, so it must define the label's own
    // word. Hanging `reading` on "Echo" or "Watchlist feeds" opens a panel
    // headed "Reading" over a word the reader did not tap. Only a label that
    // IS the term earns one; the Library row below carries `reading`.
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

function cadence(
  job: { interval_s: number; daily_at: string | null },
  weeklyOn?: string,
): string {
  // Told weekday, read time — see JobCopy.weeklyOn for why the two halves come
  // from different places.
  if (weeklyOn) return job.daily_at ? `${weeklyOn} ${job.daily_at}` : weeklyOn
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
          It can <Explain term="proposal">prepare a change</Explain> — a
          prediction, a thesis, a saved source — but your Accept is the only
          thing that writes. It takes no action on its own.
        </p>
        <p className="capability-prose">
          Once a week it also puts a number down of its own. The{' '}
          <Explain term="round">Round</Explain> asks this room a slate of
          forecastable questions;{' '}
          <Explain term="house">the house</Explain> answers them too, under the
          same <Explain term="seal">seal</Explain> and the same clock, and is
          scored beside you.
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
                    <strong>
                      {copy?.term
                        ? <Explain term={copy.term}>{copy.label}</Explain>
                        : (copy?.label ?? job.name)}
                    </strong>
                    {copy ? ` — ${copy.what}` : ''}
                    {!job.enabled && copy?.off ? ` Off: ${copy.off}` : ''}
                    <span className="capability-cadence"> · {cadence(job, copy?.weeklyOn)}</span>
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
          {/* The marker sits BESIDE each place-name rather than wrapping it.
              Wrapping made the label the trigger, so tapping "Library" opened a
              panel headed "Reading" — the very mismatch the reading_echo note
              above forbids, committed by its own remedy. A place is not its
              jargon: the Bench HOLDS a causal DAG, the Ledger is WHERE
              calibration is read. A bare marker says "there is a word here to
              look up" without claiming the word and the place are the same. */}
          <li>
            <strong>Bench</strong> <Explain term="causal-dag" /> — the
            thesis this room is building, and what is staked on it.
          </li>
          <li>
            <strong>Library</strong> <Explain term="reading" /> — the
            sources kept, and why each mattered.
          </li>
          <li>
            <strong>Field</strong> <Explain term="field-mark" /> — marks
            pencilled in about the room&rsquo;s reasoning, waiting on you.
          </li>
          <li>
            <strong>Ledger</strong> <Explain term="calibration" /> — what
            the room takes as settled, and how well it has been calling things.
          </li>
        </ul>
        <p className="capability-prose">
          Fork any message to <Explain term="branch">branch</Explain> — a branch
          inherits everything above it, so you can try a line of argument without
          losing the one you were on. Restate a remembered fact and the new
          version <Explain term="supersession">supersedes</Explain> the old,
          keeping its history rather than overwriting it.
        </p>
      </section>

      {/* Collapsed, deliberately: the room's own state is the reason to open
          this screen, and a wall of definitions ahead of it buries the thing
          the reader came for. Open, it is the one place every hard word in the
          product is defined — the same entries the ? markers above show. */}
      <section className="help-section">
        <details className="capability-glossary">
          <summary>Every word this product uses</summary>
          <dl className="capability-defs">
            {Object.entries(GLOSSARY).map(([key, entry]) => (
              <div key={key}>
                <dt>{entry.term}</dt>
                <dd>{entry.short}</dd>
              </div>
            ))}
          </dl>
        </details>
      </section>

      <section className="help-section">
        <h3>Honest limits</h3>
        <ul className="capability-list capability-plain">
          <li>A remembered number can be stale. If it matters, ask for it to be fetched live.</li>
          <li>The fallback model cannot see images or use tools, and says so.</li>
          <li>
            Nothing here places an order or moves money — the{' '}
            <Explain term="paper-book">book is paper</Explain>. Your tap is the
            only write.
          </li>
          <li>
            <Explain term="settlement">Settlement</Explain> is suggested and
            never taken: a closed question stays open until a human calls it.
          </li>
        </ul>
      </section>
    </div>
  )
}
