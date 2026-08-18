import { describe, expect, it } from 'vitest'
import { actionsFor, localProposal, localProposals } from './proposalEnvelope.ts'
import { PROPOSAL_SLOTS } from '../types/workspace.ts'
import type { MessageMetadata } from '../types/index.ts'

/**
 * The client half of the proposal envelope (design v2 §8.3–8.4).
 *
 * The SHAPES and the slot table are pinned to the backend by a Python test
 * that reads types/workspace.ts. What lives here is the message-local
 * derivation: which slots are proposals, what "accepted" means, and the
 * `failed` state no row can hold.
 */

const MID = '11111111-1111-4111-8111-111111111111'

// Exactly what the relays and hoists write today — D4's migration case.
const RAW: MessageMetadata = {
  proposal: {
    statement: 'Brent over 90', confidence: 0.6,
    deadline: '2026-10-01', accepted: false,
  },
  thesis_proposal: {
    title: 'Strait risk', claim: 'the strait shuts', monthly_budget: 5000,
  },
  reading_proposal: {
    url: 'https://example.test/a', title: 'A', summary: 's', accepted: false,
  },
  resolution_proposal: {
    prediction_id: 'p1', statement: 'Brent over 90', verdict: 'correct',
    rationale: 'r', accepted: false,
  },
  trade_proposal: {
    symbol: 'XOP', side: 'buy', dollars: 2000, rationale: 'r',
    prediction: { statement: 'XOP above 150', confidence: 0.65,
                  deadline: '2026-09-30' },
    accepted: false,
  },
  commitment_proposals: [
    { claim: 'I close before CPI', resolution_criteria: 'flat',
      category: 'commitment', accepted: false },
    { claim: 'I halve the position', resolution_criteria: 'size',
      category: 'commitment', accepted: true },
  ],
} as MessageMetadata

describe('localProposals', () => {
  it('normalizes every stored shape, list slot included', () => {
    const found = localProposals(MID, RAW)
    expect(found.map(p => p.kind).sort()).toEqual([
      'commitment_proposal', 'commitment_proposal', 'prediction_draft',
      'prediction_resolution', 'reading_draft', 'thesis_proposal',
      'trade_proposal',
    ])
  })

  it('addresses each proposal by message and slot', () => {
    const found = localProposals(MID, RAW)
    expect(found.map(p => p.id)).toContain(`proposal:${MID}:proposal`)
    expect(found.map(p => p.id)).toContain(
      `proposal:${MID}:commitment_proposals[1]`,
    )
    expect(new Set(found.map(p => p.id)).size).toBe(found.length)
  })

  it('reads the stored accepted flag per list entry', () => {
    const found = localProposals(MID, RAW)
    const byId = new Map(found.map(p => [p.id, p]))
    expect(byId.get(`proposal:${MID}:commitment_proposals[0]`)?.status)
      .toBe('proposed')
    expect(byId.get(`proposal:${MID}:commitment_proposals[1]`)?.status)
      .toBe('accepted')
  })

  it('treats a claim check as a nudge, never a proposal', () => {
    // It must not acquire an Accept button by passing through a normalizer
    // that assumed every metadata badge is a decision to make.
    const found = localProposals(MID, {
      claim_check: { url: 'https://x.test', verdict: 'mixed', note: 'n' },
    } as MessageMetadata)
    expect(found).toEqual([])
  })

  it('ignores metadata that is not a proposal slot at all', () => {
    const found = localProposals(MID, {
      source: 'deep_dive',
      tools: { iterations: 3, calls: [] },
    } as unknown as MessageMetadata)
    expect(found).toEqual([])
    expect(Object.keys(PROPOSAL_SLOTS)).not.toContain('tools')
  })

  it('has nothing to say about a message with no metadata', () => {
    expect(localProposals(MID, undefined)).toEqual([])
  })
})

describe('the states no row can hold', () => {
  it('carries this tab optimistic acceptance until the patch arrives', () => {
    const id = `proposal:${MID}:proposal`
    const p = localProposal(MID, RAW, 'proposal', null,
                            { accepted: new Set([id]) })
    expect(p?.status).toBe('accepted')
    expect(p?.available_actions).toEqual(['inspect'])
  })

  it('surfaces a failed write instead of pretending success', () => {
    // §5.1/§9.3: the relay leaves the stored flag FALSE on failure so a retry
    // is a fresh accept. If this side dropped the state, the human would see a
    // card that looks untouched and no reason it did not work.
    const id = `proposal:${MID}:reading_proposal`
    const p = localProposal(MID, RAW, 'reading_proposal', null,
                            { failed: new Set([id]) })
    expect(p?.status).toBe('failed')
  })

  it('keeps the action available after a failure, so a retry is possible', () => {
    expect(actionsFor('reading_draft', 'failed')).toContain('accept')
  })
})

describe('available actions', () => {
  it('keeps an accepted proposal inspectable rather than vanishing it', () => {
    // §8.4: accepted proposals do not disappear as if no proposal was made.
    expect(actionsFor('prediction_draft', 'accepted')).toEqual(['inspect'])
  })

  it('sends a thesis proposal to review, never straight to a write', () => {
    // Nothing exists until the cascade is drafted and a human reviews it.
    expect(actionsFor('thesis_proposal', 'proposed')).toContain('open_thesis')
    expect(actionsFor('thesis_proposal', 'proposed')).not.toContain('accept')
  })
})
