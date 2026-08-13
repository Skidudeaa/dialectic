import {
  PROPOSAL_LIST_KIND,
  PROPOSAL_LIST_SLOT,
  PROPOSAL_SLOTS,
  type ProposalAction,
  type ProposalKind,
  type ProposalStatus,
} from '../types/workspace.ts'
import type { MessageMetadata } from '../types/index.ts'

/**
 * The client's view of a message's proposals (design v2 §8.3–8.4).
 *
 * WHY the client derives anything at all, when the server projects the full
 * envelope: proposal cards render INSIDE the message stream, live, as messages
 * arrive over the WebSocket. Refetching a room projection per message would be
 * a network round trip to learn something the message in hand already says.
 *
 * WHAT it deliberately does NOT derive: `expired` and `superseded`. Those are
 * facts about the rest of the room — a bound book, an article already filed —
 * and re-deriving them here would be a second copy of a rule that needs joins
 * this side does not have. They arrive from the projection endpoint.
 *
 * So this covers exactly the message-local facts: which slots are proposals
 * (the one table, pinned to the backend's by a test), whether the stored flag
 * says accepted, and the transient `failed` this side owns because a relay
 * failure deliberately leaves the stored flag false.
 */
export interface LocalProposal {
  id: string
  kind: ProposalKind
  slot: string
  index: number | null
  payload: Record<string, unknown>
  status: Extract<ProposalStatus, 'proposed' | 'accepted' | 'failed'>
  available_actions: ProposalAction[]
}

/** What a surface may offer. Accepted proposals keep `inspect`, never nothing:
 *  §8.4 requires an accepted proposal to remain inspectable rather than vanish
 *  as if no proposal had ever been made. */
export function actionsFor(
  kind: ProposalKind,
  status: LocalProposal['status'],
): ProposalAction[] {
  if (status === 'accepted') return ['inspect']
  // A failed write keeps its action: failure means retry is available, and a
  // card that removes the button after a failure strands the human (§9.3).
  if (kind === 'thesis_proposal') return ['open_thesis', 'inspect']
  return ['accept', 'inspect']
}

/** What this tab knows that the stored metadata does not yet.
 *  `accepted` is optimistic — the relay returned before its MESSAGE_METADATA
 *  patch arrived. `failed` is the state no row can hold: on a relay failure the
 *  stored flag deliberately stays false so a retry is a fresh accept. */
export interface LocalProposalOverrides {
  accepted?: ReadonlySet<string>
  failed?: ReadonlySet<string>
}

/**
 * Every proposal a message carries, in id order stable with the backend's.
 *
 * Narrow on purpose: a metadata key outside the slot table is not a proposal.
 * `claim_check` is the case that matters — it is a nudge, not a decision, and
 * must never acquire an Accept button by passing through here.
 */
export function localProposals(
  messageId: string,
  metadata: MessageMetadata | undefined,
  overrides: LocalProposalOverrides = {},
): LocalProposal[] {
  if (!metadata) return []
  const found: LocalProposal[] = []

  const push = (slot: string, kind: ProposalKind, index: number | null,
                payload: Record<string, unknown>) => {
    const coordinate = index === null ? slot : `${slot}[${index}]`
    const id = `proposal:${messageId}:${coordinate}`
    const status: LocalProposal['status'] =
      payload.accepted || overrides.accepted?.has(id)
        ? 'accepted'
        : overrides.failed?.has(id) ? 'failed' : 'proposed'
    found.push({
      id, kind, slot, index, payload, status,
      available_actions: actionsFor(kind, status),
    })
  }

  for (const [slot, kind] of Object.entries(PROPOSAL_SLOTS)) {
    const payload = (metadata as Record<string, unknown>)[slot]
    if (payload && typeof payload === 'object' && !Array.isArray(payload)) {
      push(slot, kind, null, payload as Record<string, unknown>)
    }
  }
  const listed = (metadata as Record<string, unknown>)[PROPOSAL_LIST_SLOT]
  if (Array.isArray(listed)) {
    listed.forEach((payload, index) => {
      if (payload && typeof payload === 'object') {
        push(PROPOSAL_LIST_SLOT, PROPOSAL_LIST_KIND, index,
             payload as Record<string, unknown>)
      }
    })
  }
  return found
}

/** The proposal in one slot, or undefined. Cards render per slot, so this is
 *  what a card asks for. */
export function localProposal(
  messageId: string,
  metadata: MessageMetadata | undefined,
  slot: string,
  index: number | null = null,
  overrides: LocalProposalOverrides = {},
): LocalProposal | undefined {
  const coordinate = index === null ? slot : `${slot}[${index}]`
  return localProposals(messageId, metadata, overrides)
    .find(p => (p.index === null ? p.slot : `${p.slot}[${p.index}]`) === coordinate)
}
