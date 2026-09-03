// lib/releases.ts — what changed, and when. The authored half of the surface.
//
// ARCHITECTURE: this file carries HISTORY and nothing else. Per the split
// api/capabilities.py and CapabilityMap.tsx enforce — FACTS ABOUT THIS
// DEPLOYMENT ARE READ FROM THE RUNNING SYSTEM, RULES ABOUT THE PRODUCT ARE
// TOLD — a changelog sits on the "told" side, but only just, and the line is
// worth stating precisely.
//
// WHY a hardcoded list is safe here when "five live theses" was not: a shipped
// commit is append-only, dated, and cannot un-ship. It does not rot. What DOES
// rot is whether the thing it introduced is switched on for the reader today,
// which is exactly why an entry names its scheduler jobs by their real
// registered name and WhatsNewPanel resolves each one against the live
// capabilities response. The prose says what was built; the badge says whether
// it is running for you. Neither is allowed to answer the other's question.
//
// SO: no entry below may contain a count, a flag, or a claim about current
// state. "First fire Sunday 2026-08-23" is a date that was set and stays true.
// "The Round is on" would be a lie the moment someone flips the env var.
//
// The job names were read from the registrations, not from the docs:
// llm/question_round.py:569, llm/house_forecast.py:381,
// llm/round_close_watch.py:708, llm/field_inference.py:402, llm/rss_wire.py:384,
// llm/congress_watch.py:317. A name typed from memory renders "not on this
// deployment" forever and looks exactly like a switched-off feature.

import { useSyncExternalStore } from 'react'

export interface Release {
  /** Stable slug. Dates are not unique — two things shipped on 2026-08-18. */
  id: string
  /** ISO day it went live. The sort key, and the unread comparison key. */
  date: string
  /** A name, not a summary. */
  title: string
  /**
   * Plain prose. `[[glossary-key|the words to underline]]` marks a hard term;
   * WhatsNewPanel turns it into an <Explain>. The label is REQUIRED — an
   * unlabelled `[[key]]` does not match and renders literally, which is a
   * visible typo rather than a word silently dropped from a sentence.
   */
  body: string
  /**
   * Scheduler job names, exactly as registered, whose live state the panel
   * verifies. Omit entirely when a release introduced no scheduled work — a
   * UI change gets no badge rather than a green one it did not earn.
   */
  jobs?: string[]
}

/** Newest first. `releases.test.ts` pins that order at the data level. */
export const RELEASES: Release[] = [
  {
    id: 'working-surface',
    date: '2026-09-03',
    title: 'The working surface',
    body:
      'A scheme room now opens on one surface with everything it is about side by side: the ' +
      'causal graph with the last human word under every node, the room’s geography with the ' +
      'fires and aircraft the feeds saw inside it, the conversation, and the updates that arrived ' +
      'while you were away. Focus a node and what you write lands on it; drop an update onto a ' +
      'node to attach it as evidence; tap an edge to dispute it. The conversation can be read ' +
      'as a stream with a context rail, a tree of replies with its [[branch|branches]], lanes ' +
      'per person with whose move it is, or the volume chart the experiment is measured by. ' +
      'The participant’s replies now carry the [[reading|readings]], memories and scopes its ' +
      'tools actually used, and land on the node you were speaking to.',
  },
  {
    id: 'your-move',
    date: '2026-09-02',
    title: 'Your move',
    body:
      'Home now opens on whose turn it is. Every open question in the ' +
      '[[round|daily Round]] across your rooms sits at the top, the ones the other person has ' +
      'answered and you have not first, by name and never by number. The Round itself is ' +
      'one question a day now, one room at a time, instead of twenty on a Sunday. And the ' +
      'participant is quieter by policy: the annotator no longer posts, and Dialectic speaks ' +
      'unprompted only when you address it or a gate fires.',
    jobs: ['question_round', 'house_forecast_sweep'],
  },
  {
    id: 'fires',
    date: '2026-08-30',
    title: 'Fires',
    body:
      'NASA’s satellites report every hot pixel they see, and over an oil coast that is a ' +
      'hundred a day — flares, furnaces, the same cells every night. Each fire on the globe is ' +
      'now one square kilometre for one day, scored against what the room has seen in the last ' +
      'thirty days: a recurring cell is labelled as the flare it almost certainly is, and only a ' +
      'cell the room has never seen, burning hard enough, is marked NEW. The participant is ' +
      'woken for those, and never for the flare field. The Bench counts them; ' +
      '[[world-signal|World]] draws them sized by fire power.',
    jobs: ['world_watch'],
  },
  {
    id: 'world-consumer',
    date: '2026-08-30',
    title: 'World watch',
    body:
      'A [[world-signal|world signal]] used to vanish the moment the next poll moved on. Now, ' +
      'what a live feed reports inside geography a room has placed is kept — a dimmer, recorded ' +
      'layer on the globe beside what is live, and one line on the Bench counting today’s ' +
      'contacts across the room’s scopes. When a new one lands inside geography bound to the ' +
      'thesis, the participant speaks up about it, at most twice a day. A room with nothing placed ' +
      'yet gets a plain door to placing some, instead of a globe that never comes up.',
    jobs: ['world_watch'],
  },
  {
    id: 'reads-the-room',
    date: '2026-08-29',
    title: 'The participant reads the room',
    body:
      'Before it speaks, the participant now checks what the room has already recorded: the ' +
      'confirmed and contested field marks, any open commitments, the open ' +
      '[[round|Round]] (forecast presence only — the numbers stay sealed until both humans ' +
      'commit), and what was read lately. A wire post or a quiet-hours follow-up can now check ' +
      'a memory, read an article, or draft a prediction instead of speaking with no tools at ' +
      'all. Field inference reads the room’s memory, thesis and recent readings before ' +
      'proposing a mark, rather than the transcript alone. And the multi-model persona feature — a second, ' +
      'disconnected way for the app to speak, shipped early and never adopted — is gone.',
  },
  {
    id: 'protocol-fractures',
    date: '2026-08-26',
    title: 'Protocols keep their word',
    body:
      'Four repairs to structured [[protocol|protocols]]. The claim you type when you start a ' +
      'Steelman or Devil\u2019s Advocate now reaches the facilitator, so it frames ' +
      'your position instead of whatever the thread last said. Reloading, opening ' +
      'the room on another device, or switching threads brings back the protocol ' +
      'banner and its controls. When a protocol concludes, the memory it leaves ' +
      'behind is the facilitator\u2019s actual synthesis, linked to the message it ' +
      'came from, not a note saying one is pending. And if the connection is down ' +
      'when you tap Invoke, the window stays open with your claim in it and tells you.',
  },
  {
    id: 'documents',
    date: '2026-08-22',
    title: 'A file, not a blob',
    body:
      'Ask the participant for a document — a brief, a newsletter, a memo, a PDF — ' +
      'and it writes the whole piece and attaches it to its reply as a download, ' +
      'instead of pasting it into the chat or saying it has no way to make a file. ' +
      'The file sits on the message like any [[attachment|upload]], authored by the participant.',
  },
  {
    id: 'duel',
    date: '2026-08-21',
    title: 'The duel',
    body:
      'Beside your own probability there is now a second slider — ' +
      'where you think the other forecaster will land — the [[peer-read|peer read]]. The participant ' +
      'forecasts every question itself, under the same [[seal|seal]] and the same clock, ' +
      'and can be publicly and permanently wrong. A closed question gathers its own ' +
      'evidence and asks a human for the [[settlement|verdict]]. The first round fires ' +
      'Sunday 2026-08-23 at 09:00 CT; it had never run when this shipped.',
    jobs: ['house_forecast_sweep', 'round_close_watch'],
  },
  {
    id: 'mirror',
    date: '2026-08-21',
    title: 'The Mirror',
    body:
      'The [[mirror|Mirror]] is what the participant thinks of how you think — its own words, dated, ' +
      'and yours alone. It has kept a private model of each person all along; the Mirror ' +
      'is the history of it, every version and the difference between any two. A room ' +
      'where only the other person is modelled looks exactly like a room with no model ' +
      'at all.',
  },
  {
    id: 'sunday-round',
    date: '2026-08-20',
    title: 'The Sunday Round',
    body:
      'Each Sunday a slate of forecastable questions is drafted for every room that has ' +
      'two forecasters and recent human talk in it — so not Home, which is excluded — each ' +
      'binary, each with a named resolution source and a hard close date, and ' +
      '[[seal|blind]] until you have both committed. Presence and push were repaired in ' +
      'the same pass: one stranded row could silently disable a member’s notifications, ' +
      'notes and alerts for a room, with no error anywhere.',
    jobs: ['question_round'],
  },
  {
    id: 'calibration-spine',
    date: '2026-08-18',
    title: 'Belief connects to capital',
    body:
      'A prediction stopped being a sentence in a transcript. Every claim now carries ' +
      'provenance, a deadline and a [[brier|Brier score]], and the [[paper-book|paper ' +
      'book]] holds a position for what the room believes. The participant reads its own ' +
      'track record — scored, not self-reported — before it argues with you about the next one.',
  },
  {
    id: 'instrument-desk',
    date: '2026-08-18',
    title: 'The Instrument Desk',
    body:
      'The whole app was rebuilt as a machined chassis with paper on it: bezels, ' +
      'seven-segment quote tiles, a running lamp on each scene. The scene band became the ' +
      'Console and carries the live instruments, so what the room is doing stays legible ' +
      'without changing scene.',
  },
  {
    id: 'source-lanes',
    date: '2026-08-18',
    title: 'New source lanes',
    body:
      'The Library gained doors beyond the wire: an RSS watchlist per room, a dropped PDF ' +
      'or newsletter filed as a [[reading|reading]], and congressional filings. Each lane ' +
      'is scheduled separately, so one can be switched on while another is dark — as they ' +
      'are today.',
    jobs: ['rss_wire', 'congress_watch'],
  },
  {
    id: 'legibility',
    date: '2026-08-16',
    title: 'Legibility',
    body:
      '@-mentions render as chips, and the address line shows who a message was actually ' +
      'for. You can file a link you pasted as a [[reading|reading]], tag a message meta, ' +
      'bug or idea, and confirm or contest a [[field-mark|field mark]] without leaving ' +
      'the transcript.',
  },
  {
    id: 'one-app',
    date: '2026-08-14',
    title: 'One app',
    body:
      'The Bench became the trading cockpit. The [[causal-dag|causal DAG]], market strip, ' +
      'open trades, hourly diff and scenario what-ifs render in the room itself — no ' +
      'second interface to keep open, and the book id never reaches the browser.',
  },
  {
    id: 'release-3',
    date: '2026-08-14',
    title: 'Field, Focus, Atlas',
    body:
      'The participant pencils provisional [[field-mark|marks]] about the room’s reasoning ' +
      'for you to confirm or contest, Focus holds one object beside the talk, and the ' +
      'Atlas maps what crosses rooms. The transcript was de-chatted in the same pass: ' +
      'full-width rows, signature marks, no colour coding of who spoke.',
    jobs: ['field_inference'],
  },
  {
    id: 'workroom',
    date: '2026-08-13',
    title: 'Scenes',
    body:
      'A room stopped being one scrolling page. Record, Bench, Field, Library and Ledger ' +
      'are places you switch between, each a read-only projection of things that already ' +
      'existed — no new store, and nothing kept twice.',
  },
  {
    id: 'home-base',
    date: '2026-08-12',
    title: 'Home Base',
    body:
      'One shared room is the default landing: who is around, what moved, and a door into ' +
      'every scheme room. Home coordinates and the scheme rooms own the scheme work — and ' +
      'Home can now make one and carry everybody into it.',
  },
]

/** Where the last-seen date lives. Matches `dialectic-scene-*` naming. */
export const RELEASES_SEEN_KEY = 'dialectic-releases-seen'

/**
 * Fired on `window` by markAllSeen, so a badge rendered in one component and a
 * panel rendered in another agree without either owning the other's state.
 */
export const RELEASES_SEEN_EVENT = 'dialectic:releases-seen'

/**
 * Newest entry's id, or '' if the list is ever emptied.
 *
 * WHY THE ID AND NOT THE DATE. The stored token used to be the newest DATE and
 * the unread test was `release.date > seen`, which is blind at exactly the
 * granularity this project ships at. Open the panel at 10:00, store
 * '2026-08-21'; append a second entry the same afternoon and
 * '2026-08-21' > '2026-08-21' is false — no badge, ever, for that entry. Not a
 * corner case: 7 of the entries below share a date with a sibling, because a
 * day's work lands as two or three things. An id is unique per entry, and
 * RELEASES is newest-first, so the seen entry's INDEX is already the count of
 * everything above it.
 */
export function latestReleaseId(): string {
  return RELEASES[0]?.id ?? ''
}

/**
 * Survives a write that failed. Storage can be readable and NOT writable —
 * quota exhausted, or a browser that hands back getItem and throws on setItem —
 * and without this the badge would be uncleanable for the rest of the session,
 * which is the one failure mode a help badge must never have.
 */
let memorySeen: string | null = null

/**
 * What storage says about the last time this reader caught up.
 *
 *   string     a stored date
 *   null       storage works, nothing stored yet — a first run
 *   undefined  storage is UNAVAILABLE (private window, blocked site data)
 *
 * The null/undefined split is the whole point: a first run should badge once
 * and then clear, while an unreadable store must never badge at all, because
 * nothing it does could ever clear it.
 */
export function readLastSeen(): string | null | undefined {
  if (memorySeen !== null) return memorySeen
  try {
    return window.localStorage.getItem(RELEASES_SEEN_KEY)
  } catch {
    return undefined
  }
}

/**
 * How many entries this reader has not caught up with.
 *
 * `undefined` in means storage could not be read, and the answer is 0 — never
 * "all of them". A badge that cannot be cleared is worse than no badge.
 */
export function unreadCount(seen: string | null | undefined): number {
  if (seen === undefined) return 0
  if (seen === null) return RELEASES.length
  return unreadBefore(seen)
}

/**
 * How many entries sit above `seenId`, newest-first — the shared answer for the
 * badge and for the panel's per-entry mark, so the two cannot disagree.
 *
 * An id we do not recognise (a token from an older build, or an entry since
 * renamed) counts as caught up, NOT as everything-unread. A badge nothing can
 * clear is the failure mode readLastSeen's undefined case exists to avoid, and
 * a stale id must not reintroduce it through the back door.
 */
export function unreadBefore(seenId: string): number {
  const index = RELEASES.findIndex((release) => release.id === seenId)
  return index === -1 ? 0 : index
}

/** Catch this reader up to the newest entry, and tell any live badge. */
export function markAllSeen(): void {
  const latest = latestReleaseId()
  memorySeen = latest
  try {
    window.localStorage.setItem(RELEASES_SEEN_KEY, latest)
  } catch {
    // Nothing to recover — memorySeen already holds the session.
  }
  try {
    window.dispatchEvent(new Event(RELEASES_SEEN_EVENT))
  } catch {
    // A host with no CustomEvent constructor still gets the storage write.
  }
}

/** Test seam: forget the in-memory fallback. Not used by the app. */
export function resetSeenCache(): void {
  memorySeen = null
}

function subscribeToSeen(onChange: () => void): () => void {
  window.addEventListener(RELEASES_SEEN_EVENT, onChange)
  return () => window.removeEventListener(RELEASES_SEEN_EVENT, onChange)
}

/**
 * How many entries this reader has not seen — for a badge anywhere in the app.
 *
 * Never throws and never sticks: an unreadable store answers 0, and opening the
 * panel clears it through RELEASES_SEEN_EVENT even when the write itself failed.
 *
 * WHY useSyncExternalStore and not useState + a listener: effects run in tree
 * order, so if the badge sits AFTER the panel in the same commit, the panel has
 * already marked everything seen and dispatched the event by the time the badge
 * subscribes — the badge misses it and sits stale until something remounts it.
 * This hook re-reads the snapshot after subscribing, which is exactly that case.
 * A useState + listener version passes when the badge happens to mount first and
 * fails when it does not, which makes render ORDER decide whether a badge is
 * honest. Mutation-proven both ways by the two harnesses in
 * WhatsNewPanel.test.tsx. The snapshot is a number, so Object.is settles it and
 * there is no cached-snapshot loop.
 *
 * WHY IT LIVES HERE rather than beside WhatsNewPanel: the same reason
 * `markGlyph` sits in productIdentity.ts (see its comment) — a component file
 * that also exports a hook trips `react-refresh/only-export-components`. It is
 * a view onto this module's own store, so this is its home rather than its exile.
 */
export function useUnreadReleases(): number {
  return useSyncExternalStore(subscribeToSeen, () => unreadCount(readLastSeen()))
}
