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
  atlas: 'The whole house mapped — rooms, artifacts, echoes, and their crossings.',
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
}
