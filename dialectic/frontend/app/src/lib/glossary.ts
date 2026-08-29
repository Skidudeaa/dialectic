// lib/glossary.ts — the one definition of every hard word in this product.
//
// ARCHITECTURE: authored prose, deliberately. Per the split CapabilityMap.tsx
// and api/capabilities.py already enforce — FACTS ABOUT THIS DEPLOYMENT ARE
// READ FROM THE RUNNING SYSTEM, RULES ABOUT THE PRODUCT ARE TOLD — every entry
// here is a durable rule. Nothing below is state. If a definition ever needs a
// count, a flag or a timestamp to be true, it does not belong in this file; it
// belongs in a capabilities read.
//
// WHY one table rather than a sentence beside each control: "Brier score"
// appears on the Round card, in the Ledger's headline, in the track record the
// participant reads about itself, and in the help map. Four copies drift, and
// the reader has no way to tell which one is current — the same failure the
// hardcoded help modal had. One entry, four call sites.
//
// EVERY DEFINITION WAS WRITTEN FROM THE CODE THAT IMPLEMENTS IT, not from a
// doc about it. The scoring entries come from stakes/timeweighted.py, the Round
// from llm/question_round.py + api/rounds.py + stakes/house.py, the settlement
// from llm/round_close_watch.py, the desk terms from trading/'s own contracts.
// A term whose implementation is not read is a term that gets defined wrong and
// then quoted confidently in four places.
//
// HOUSE VOICE: spare, concrete, second person, and the honest limit stated in
// the same breath as the capability. Where a term is genuinely hard, it is
// defined by what it DOES to you, never by its formula.

export interface GlossaryEntry {
  /** Display form, as it should be read aloud. */
  term: string
  /** ONE line. Shown first, and must stand alone — many call sites show only this. */
  short: string
  /** A short paragraph: the why, and the honest limit. */
  long?: string
  /** Keys of related entries. */
  seeAlso?: string[]
}

export const GLOSSARY: Record<string, GlossaryEntry> = {
  // ── ways of talking ─────────────────────────────────────────────────────
  protocol: {
    term: 'Protocol',
    short: 'A structured exchange — Steelman, Socratic, Devil’s Advocate, Synthesis — the participant runs in phases and closes with a memory.',
    long:
      'You start one from the room header with a claim. The participant steps out of its ordinary ' +
      'voice to facilitate the phases, and when it concludes, its final message is kept as the memory ' +
      'of the exchange. One protocol per thread at a time.',
  },
  attachment: {
    term: 'Attachment',
    short: 'A file on a message — yours by upload, or the participant’s when it writes a document.',
  },
  // ── scoring ─────────────────────────────────────────────────────────────
  brier: {
    term: 'Brier score',
    short: '0 is perfect, 1 is perfectly wrong, and 0.25 is what you get by always saying 50%.',
    long:
      'The squared distance between what you said and what happened, averaged. It punishes ' +
      'confidence, which is the point — being sure and wrong costs more than being unsure and ' +
      'wrong. Only questions that resolved correct or incorrect are scored: a voided or partial ' +
      'question is counted and never graded, because inventing a half-outcome for a binary ' +
      'question is exactly the manufactured number this ledger exists to avoid.',
    seeAlso: ['time-weighted-brier', 'coverage', 'bss'],
  },
  'time-weighted-brier': {
    term: 'Time-weighted Brier',
    short:
      'You are scored on every day the question was open, not on your last answer — so an early ' +
      'correct call beats a late one.',
    long:
      'The rule the ACE tournament ran on, and the reason updating is a skill worth measuring. ' +
      'Each day inherits whatever forecast you had standing that day, and the days are averaged ' +
      'across the question’s life. Under final-answer scoring, someone who sat at 0.50 for 27 ' +
      'days and moved to 0.95 on the last one scores the same as someone who was at 0.95 from ' +
      'the start. The final-answer Brier rides alongside rather than instead — the gap between ' +
      'the two says whether you got there early or merely got there.',
    seeAlso: ['brier', 'coverage', 'round'],
  },
  coverage: {
    term: 'Coverage',
    short: 'The share of the question’s life you actually had a forecast on file for.',
    long:
      'Never folded into the Brier, and it has to be read beside it. Open a card late and you ' +
      'are scored only on the days you were there — days nearer the outcome, and therefore ' +
      'easier. A 0.09 across a third of a question’s life is not a 0.09. The window opens when ' +
      'the question was written, not when the first person got round to answering it.',
    seeAlso: ['time-weighted-brier', 'brier'],
  },
  bss: {
    term: 'Brier skill score',
    short:
      'Your Brier measured against what a know-nothing would have scored. Above 0 you beat it; ' +
      'below 0 you did worse than guessing.',
    long:
      'One minus your Brier divided by the reference. With no base rate to compare against, the ' +
      'reference is 0.25 — the score of answering 50% to everything. It answers the question a ' +
      'raw Brier cannot: whether this was a hard slate or an easy one.',
    seeAlso: ['brier', 'peer-delta'],
  },
  'peer-delta': {
    term: 'Peer delta',
    short:
      'Who took whose points. Positive means you gained them from the other forecaster, and the ' +
      'same number is negative on their side.',
    long:
      '100 × the average, over days you were both in, of your log score minus theirs. With two ' +
      'forecasters answering the same slate on the same clock, the question’s difficulty cancels ' +
      '— so this measures the duel rather than the weather. Contested days only: a day someone ' +
      'had not yet forecast is absence, not loss, and coverage reports that separately. At two ' +
      'people it sums to zero, so neither of you can quietly both be winning.',
    seeAlso: ['log-clip', 'coverage', 'round'],
  },
  'log-clip': {
    term: 'The clip',
    short:
      'However far you push the slider, a forecast is scored as no more certain than 1% or 99%.',
    long:
      'This is a rule, not a detail, and it is stated wherever the number is shown. The slider ' +
      'reaches 0.00, and a 0.00 that happens is infinitely wrong — unclipped, one ' +
      'certain-and-wrong call would annihilate a season and the ledger would be unreadable ' +
      'forever after. The floor reads as “I was essentially certain” and caps a single blown ' +
      'call at about −4.6. It binds the log score and the peer delta; the Brier needs no clip.',
    seeAlso: ['peer-delta', 'brier'],
  },
  calibration: {
    term: 'Calibration',
    short: 'Whether the things you call 70% happen about 70% of the time.',
    long:
      'Separate from being right. Say 90% and be right nine times in ten and you are calibrated; ' +
      'say 90% and be right six times in ten and you are overconfident, which the bars in the ' +
      'Ledger show band by band. Calibration is fixable by moving your numbers. Skill is not.',
    seeAlso: ['brier', 'bss'],
  },

  // ── the Sunday Round ────────────────────────────────────────────────────
  round: {
    term: 'The Round',
    short:
      'A slate of forecastable questions drafted each Sunday for any room with two forecasters ' +
      'in it — each binary, each with a named resolution source and a hard close date.',
    long:
      'One event per question, revisable until it closes, because revising is the thing being ' +
      'scored. Questions are drafted against the room’s live thesis and the week’s reading and ' +
      'posted without review: a bad question is visible and skippable, and a review gate would ' +
      'mean the round stops arriving, which is the one failure it exists to prevent.',
    seeAlso: ['seal', 'house', 'peer-read', 'settlement'],
  },
  seal: {
    term: 'The seal',
    short: 'Until you have forecast a question, the other numbers are not sent to you at all.',
    long:
      'Not hidden by the screen — absent from the server’s answer. With two forecasters there is ' +
      'no crowd to hide in, so seeing the other number first is pure anchoring. That is why you ' +
      'cannot see the other forecast yet: it was never sent. The participant’s own number is ' +
      'sealed by the same rule and for the same reason. Both humans have to commit before ' +
      'either is revealed.',
    seeAlso: ['round', 'house', 'peer-read'],
  },
  house: {
    term: 'The house',
    short:
      'The participant forecasts every question itself, under the same seal and the same clock, ' +
      'and can be publicly and permanently wrong.',
    long:
      'One number per question, scored on the same time-weighted rule as yours. It argues about ' +
      'probability all week; with nothing on the record it is a pundit, and a pundit cannot be ' +
      'wrong, so its confidence carries no information. If its answer does not parse cleanly the ' +
      'question is dropped rather than guessed at — a missing house forecast reads as sitting ' +
      'one out, and a fabricated one would cost this scoreboard the only thing it is worth.',
    seeAlso: ['round', 'seal', 'peer-delta'],
  },
  'peer-read': {
    term: 'The peer read',
    short: 'The second slider: where you think the OTHER forecaster will land.',
    long:
      'The only number here that scores the moment you both commit — it never waits on the ' +
      'world. Yours to see and revise at any time, since hiding your own guess from you would ' +
      'only stop you improving it. When the question unseals, the signed error says which way ' +
      'you misread them; reading them consistently high or low is a habit worth naming.',
    seeAlso: ['round', 'seal', 'mirror'],
  },
  settlement: {
    term: 'Settlement',
    short:
      'When a question closes, the participant gathers evidence from the source the question ' +
      'named and asks a human for the verdict.',
    long:
      'It suggests; it never resolves. Your tap on the card is the only thing that writes an ' +
      'outcome. One wrong auto-settlement would cost the ledger its standing permanently and ' +
      'there is no earning that back — so the machine does the tedious part, finding out what ' +
      'happened, and none of the binding part.',
    seeAlso: ['round', 'proposal'],
  },

  // ── the room ────────────────────────────────────────────────────────────
  'world-signal': {
    term: 'World signal',
    short:
      'A live observation from a public feed — an aircraft, a quake, a fire, the ISS — shown ' +
      'on the World globe for as long as it is current, and no longer.',
    long:
      'A signal is not geography. It is one provider\u2019s report, held only in memory, stamped ' +
      'with when it was observed, when we fetched it, and when it stops counting as now. It ' +
      'expires on its own and nothing keeps a copy. To make a place out of one \u2014 to argue ' +
      'from it, mark evidence on it, or have it survive a restart \u2014 a person has to place ' +
      'it, which is what turns a report into a scope the room owns. Every layer also reports ' +
      'its own condition: live, partial, stale, throttled, unavailable, or not configured \u2014 ' +
      'so an empty globe never has to be guessed at.',
    seeAlso: ['field-mark'],
  },
  'field-mark': {
    term: 'Field mark',
    short:
      'A provisional note the participant pencils in about the room’s reasoning — a support, a ' +
      'tension, an open question — for you to confirm or contest.',
    long:
      'Proofreader’s marks, not conclusions. Every mark is a row and nothing is overwritten: ' +
      'confirming or contesting restyles the mark and keeps its history, and a mark already ' +
      'ruled on cannot be quietly re-asserted later. A mark can only claim one of a fixed set ' +
      'of relations, so the inference pass structurally cannot record a decision, a consensus, ' +
      'or a claim that someone changed their position — those are yours to make.',
    seeAlso: ['supersession', 'proposal'],
  },
  supersession: {
    term: 'Supersession',
    short:
      'Restate a remembered fact and the new version replaces the old — which is kept, marked ' +
      'superseded, with its validity window closed.',
    long:
      'Only a restatement by the same speaker supersedes. The other person agreeing keeps the ' +
      'original standing rather than replacing it, because agreement is confirmation and not a ' +
      'correction. Nothing is overwritten anywhere in this product, so a memory can be read as ' +
      'it stood at any point rather than only as it stands now.',
    seeAlso: ['field-mark', 'branch'],
  },
  branch: {
    term: 'Branch',
    short: 'Fork any message to open a new line of argument. A branch inherits everything above it.',
    long:
      'The parent transcript is context inside the branch, so you can try a line without losing ' +
      'the one you were on and without re-explaining it. The participant reads that inherited ' +
      'thread the same way you do.',
    seeAlso: ['supersession'],
  },
  reading: {
    term: 'Reading',
    short: 'A source the room has actually read, filed as one entry per source in the Library.',
    long:
      'Filed by your tap, or by the overnight passes that read against the thesis. The article ' +
      'is kept whole enough to quote from, and a distilled twin goes into memory so recall finds ' +
      'it; filing the same URL twice refreshes that entry rather than adding a second. When ' +
      'something filed here bears on another room, that room gets a citation, never a copy.',
    seeAlso: ['proposal'],
  },
  proposal: {
    term: 'Proposal',
    short:
      'Anything the participant prepares — a prediction, a thesis, a trade, a source to file — ' +
      'waits as a card. Your tap is the only write.',
    long:
      'It can shape a change and cannot commit one. Every accept records who accepted and when ' +
      'in the same write, so nothing can be accepted by nobody, and an accept that fails leaves ' +
      'the card untouched so a retry is fresh rather than half-done. Nothing here places an ' +
      'order or moves money.',
    seeAlso: ['settlement', 'paper-book'],
  },
  mirror: {
    term: 'The Mirror',
    short: 'What the participant thinks of how you think — its own words, dated, and yours alone.',
    long:
      'It has kept a private prose model of each person, per room, rewritten as the room talks. ' +
      'The Mirror is the history: every version, and at each one what changed since the ' +
      'version before it. One ' +
      'paragraph is a fact about you; a hundred in sequence is a theory of you being revised. ' +
      'You can only ever read your own — a room where only the other person is modelled looks ' +
      'exactly like a room with no model at all.',
    seeAlso: ['peer-read'],
  },

  // ── the desk ────────────────────────────────────────────────────────────
  'causal-dag': {
    term: 'Causal DAG',
    short:
      'The thesis drawn as nodes and arrows: what has to happen for what, in the order it would ' +
      'have to happen.',
    long:
      'Each node is one testable condition; each edge carries the claim that one moves the next. ' +
      'The structure is authored and the live state — fired, approaching, dormant — is laid over ' +
      'it. The Bench renders it read-only; deep editing happens on the desk itself.',
    seeAlso: ['cascade-phase', 'confluence'],
  },
  'cascade-phase': {
    term: 'Cascade phase',
    short:
      'Which of five stages the thesis has reached: shock, transmission, amplification, policy ' +
      'response, resolution.',
    long:
      'A coarse read on how far a crisis has actually travelled, kept separate from any single ' +
      'node’s state. It rides in every turn the participant takes in a bound room, so “we are ' +
      'still in transmission” is something it already knows rather than something you have to ' +
      'tell it.',
    seeAlso: ['causal-dag', 'confluence'],
  },
  confluence: {
    term: 'Confluence',
    short:
      'How many independent causal paths have arrived at the same node. High confluence, high ' +
      'confidence.',
    long:
      'Fan-in, scored: one route to a node is a story, three unrelated routes landing at once is ' +
      'a signal. Derived indicators are barred from feeding it by construction, so a score ' +
      'cannot be talked up by another number computed from the same move.',
    seeAlso: ['causal-dag', 'cascade-phase'],
  },
  'paper-book': {
    term: 'The paper book',
    short:
      'Positions and cash held on paper, not with money. Fills are append-only and the book is ' +
      'replayed from them.',
    long:
      'Long-only: a sell past flat is refused at the door rather than quietly opening a short. ' +
      'Trades price off the desk’s own quote cache and never off a number sent by a browser, ' +
      'and every deposit is recorded as an external flow so the return stays honest about what ' +
      'was added rather than earned.',
    seeAlso: ['spy-benchmark', 'discretionary', 'proposal'],
  },
  'spy-benchmark': {
    term: 'The SPY benchmark',
    short:
      'What the same cash would have done in the index, so the book’s equity line has something ' +
      'to be measured against.',
    long:
      'Unitized: each dated deposit buys units at that day’s close, so adding money mid-season ' +
      'cannot flatter the comparison. Price return only, and labelled as such — it does not ' +
      'include dividends.',
    seeAlso: ['paper-book'],
  },
  discretionary: {
    term: 'Discretionary trade',
    short:
      'A paper trade either carries a dated forecast that can be scored, or is labelled ' +
      'discretionary — never neither.',
    long:
      'A trade with neither moves paper money while dodging the scoreboard, so a proposal that ' +
      'offers neither is refused outright. The label is the honest option and not the loophole: ' +
      'it says on the record that this one was a judgement call and will not be graded.',
    seeAlso: ['paper-book', 'proposal'],
  },
}

/**
 * Look up an entry, or `undefined` for a term this product does not define.
 *
 * WHY it normalizes: the callers are spread across the Round card, the Ledger,
 * the Bench and the help map, and `term="Brier"` silently rendering nothing is
 * the kind of miss no test catches and every reader does. Case and surrounding
 * space are forgiven; the key itself is not guessed at.
 */
export function glossaryEntry(key: string): GlossaryEntry | undefined {
  return GLOSSARY[key.trim().toLowerCase()]
}
