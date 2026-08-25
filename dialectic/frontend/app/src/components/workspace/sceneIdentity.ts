import type { ImplementedWorkspaceScene } from '../../types'

// The one copy of each scene's name, purpose and mark — read by the switcher
// tray (labels + tooltips) and the SceneMasthead (the place-maker). A total
// Record over the union on purpose: adding a scene without naming it here is
// a build error, not a blank tab discovered in the browser.
//
// The names are places, not features — the room is a workroom and these are
// parts of it. "Library" says what it holds; "Evidence Management" would not.
export const SCENE_LABELS: Record<ImplementedWorkspaceScene, string> = {
  house: 'House',
  record: 'Record',
  bench: 'Bench',
  field: 'Field',
  library: 'Library',
  ledger: 'Ledger',
  atlas: 'Atlas',
  mirror: 'Mirror',
}

// One clause per place — rendered large in the SceneMasthead as the answer to
// "why am I here", and as a hover/focus tooltip on every tab. WHY visible and
// not tooltip-only: the names are deliberately spare, and a newcomer should
// not have to click every tab to learn the room's floor plan — hover-only
// meaning is also barred by the accessibility gate.
export const SCENE_HINTS: Record<ImplementedWorkspaceScene, string> = {
  house: 'Movement across every scheme you share — each item links to its source.',
  record: 'The exact transcript — searchable, attributable, never paraphrased.',
  bench: 'The thesis under construction — causal graph, live market, open trades, what-ifs.',
  field: 'Provisional reasoning — support, tension, and synthesis candidates awaiting review.',
  library: 'What the room has actually read — filed evidence, one entry per source.',
  ledger: 'What the room holds itself to — commitments, dossier entries, memories.',
  atlas: 'The whole house mapped — rooms, artifacts, echoes, and their crossings; or the same map on the world.',
  mirror: 'What the participant thinks of how you think — its own words, dated, and yours alone.',
}

// Two or three sentences per place, answering the two questions the one-clause
// hint above cannot: WHAT DO I DO HERE, and WHAT WILL I FIND. Shown ONLY behind
// the masthead's disclosure — a returning user never reads it again, a newcomer
// can always reach it. The switcher tooltips keep the short hint; a paragraph in
// a tooltip is a paragraph nobody reads.
//
// AUTHORED PROSE, DELIBERATELY, and every clause is a DURABLE RULE. Per the
// split api/capabilities.py and CapabilityMap.tsx enforce — facts about this
// deployment are READ from the running system, rules about the product are TOLD
// — nothing here is a count, a flag or a timestamp. The Mirror's version count
// is a readout inside MirrorPanel because it is state; "you can only read your
// own" is here because it is law.
//
// Each was written from the scene it describes. Where a scene has an honest
// limit it is stated in the same breath as the capability: Home refuses thesis
// work, the Bench moves no money, the Field concludes nothing.
export const SCENE_PRIMER: Record<ImplementedWorkspaceScene, string> = {
  house:
    'Home is the room for everything that is not one scheme’s business. Above the ' +
    'transcript, the pulse shows who is here, what needs a body, and what moved in the ' +
    'schemes you share — each line links to its source. Scheme work stays in the scheme’s ' +
    'own room: a thesis cannot be created here, on purpose.',
  record:
    'The conversation itself, kept whole — attributable, searchable, and never paraphrased ' +
    'into a summary that replaces it. Fork any message to open a branch, which inherits ' +
    'everything above it, so you can try a line without losing the one you were on. The ' +
    'participant reads that inherited thread the same way you do.',
  bench:
    'Where the thesis is built and watched: the causal graph with live node states over ' +
    'the authored structure, the market strip, open trades, the hourly diff, and scenario ' +
    'what-ifs you can run without committing to them. A room with no thesis shows the ' +
    'draft-and-create form instead — that is an empty Bench doing its job. Nothing here ' +
    'places an order or moves money; the book is paper.',
  field:
    'Provisional marks the participant pencils in as the room argues — a support, a ' +
    'tension, a question worth tracking. None of it is a conclusion, and none of it ' +
    'outranks what you said. Your confirm makes a mark solid and your contest puts it on ' +
    'notice; both are recorded beside it rather than over it, so a mark already ruled on ' +
    'cannot be quietly re-asserted later.',
  library:
    'Every source this room has actually read, one entry per source, kept whole enough to ' +
    'quote from. Two things fill it, and they fill it differently: paste a link and the ' +
    'participant reads it and offers it to you, where your Accept is what files it — while ' +
    'the wire and the overnight passes file what bears on the thesis directly, with no tap ' +
    'from anyone. Most of what is in here arrived that second way. Filing the same URL ' +
    'twice refreshes the entry rather than adding a second.',
  ledger:
    'What this room takes as settled, and how well it has actually done. Commitments and ' +
    'remembered facts sit here beside the scored track record — Brier, calibration bands, ' +
    'and the paper book’s equity against the index. Restate a fact and the new version ' +
    'supersedes the old, which keeps its history rather than vanishing.',
  atlas:
    'The map of everywhere you can go: every room you belong to, its branches, and what ' +
    'each one holds — a thesis, a reading, a brief, a question still open. Tap any node to ' +
    'land on it. It shows only rooms you are a member of, so it is your map and not the ' +
    'house’s. World is the same map drawn on a globe: only what a person confirmed or a ' +
    'source reported is placed there, and a proposal the participant makes stays dashed ' +
    'until someone confirms it.',
  mirror:
    'The participant keeps a private prose model of how you think, per room, rewritten as ' +
    'the room talks. This is the whole history of it — step back through the rewrites, and ' +
    'at any version ask what changed since the one before it. You can only ever read your own: ' +
    'a room where just the other person is modelled looks exactly like a room with no ' +
    'model at all.',
}

// Each place's mark, shown on the masthead's glyph plate beside the name.
export const SCENE_GLYPHS: Record<ImplementedWorkspaceScene, string> = {
  house: '⌂',
  record: '¶',
  bench: '⚒',
  field: '※',
  library: '❧',
  ledger: '☰',
  atlas: '✦',
  mirror: '☾',
}
