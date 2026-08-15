import type { WorkspaceScene } from './workspace.ts'
export * from './workspace.ts'

export interface Room {
  id: string;
  name: string | null;
  token: string;
  /** The one Home room (migration 013). Copied from the saved-room
   *  descriptor — never re-derived from name or URL. */
  is_home: boolean;
}

export type HistoryMode = 'push' | 'replace' | 'none';

/** A navigation target. roomId null is the canonical Home-root destination.
 *  `scene` is the third destination axis: null means "no scene requested",
 *  which resolves to the destination's default rather than to an error.
 *  `object` is the fourth axis (§1.18) — the workspace object id selected
 *  into Focus. Focus is a STATE, not a scene: it rides alongside whatever
 *  scene is showing rather than replacing it, so it is a destination axis
 *  of its own rather than a WorkspaceScene value. null/omitted means no
 *  object is selected; an id that does not resolve renders Focus's own
 *  unavailable state, never a 404 — resolution happens client-side against
 *  whatever projection the caller already has, not here. */
export interface RoomDestination {
  roomId: string | null;
  threadId?: string | null;
  scene?: WorkspaceScene | null;
  object?: string | null;
}

export interface User {
  id: string;
  display_name: string;
}

/** One tool the participant called while writing a message. */
export interface ToolCallTrace {
  name: string;
  /** Human-facing phrase, stamped server-side from the tool registry. */
  label?: string;
  ok: boolean;
  latency_ms?: number;
  input?: Record<string, unknown>;
  /** Present on hypotheticals — e.g. { base_revision: 29395 }. */
  provenance?: Record<string, unknown>;
  /** Present only when the call failed. */
  error?: string;
}

/**
 * Per-message server metadata. Only present on LLM messages that used tools.
 * Carried on the live llm_done event and, since the REST projection learned
 * the field, on history reloads too.
 */
export interface MessageMetadata {
  /** Set on research-mode briefs ('deep_dive') — the message came from the
   *  long tool loop, not an ordinary turn. */
  source?: string;
  tools?: {
    iterations: number;
    degraded: boolean;
    calls: ToolCallTrace[];
  };
  /** A draft_prediction awaiting (or granted) the human Accept tap. */
  proposal?: PredictionProposal;
  /** A propose_thesis card — its tap opens the Create Thesis panel. */
  thesis_proposal?: ThesisProposal;
  /** A save_reading card — its tap files the article into the library. */
  reading_proposal?: ReadingProposal;
  /** Detected implicit commitments ("I bet…") awaiting the Accept tap. */
  commitment_proposals?: CommitmentProposal[];
  /** A claim-check verdict when a linked article isn't fairly represented. */
  claim_check?: ClaimCheck;
  /** A deadline-watch resolution proposal awaiting the human's verdict tap. */
  resolution_proposal?: ResolutionProposal;
}

/**
 * A commitment the detector heard in a human message. Detection writes
 * only this chrome; the Accept tap sends an ordinary create_commitment
 * (carrying proposal_index so the server stamps `accepted`).
 */
export interface CommitmentProposal {
  claim: string;
  resolution_criteria: string;
  category: string;
  accepted?: boolean;
}

/**
 * The claim checker's verdict on a human message linking an article.
 * Only `mixed`/`misrepresented` ever reach the client — supported links
 * stay silent by design, so a badge always means "read it yourself first".
 */
export interface ClaimCheck {
  url: string;
  title?: string | null;
  verdict: 'mixed' | 'misrepresented';
  note: string;
}

/**
 * Claude's proposal that the conversation becomes a tracked thesis.
 * Nothing exists yet: the card seeds the Create Thesis form, where the
 * cascade is drafted, reviewed, and — only on the human's tap — created.
 */
export interface ThesisProposal {
  title: string;
  claim: string;
  monthly_budget?: number;
}

/**
 * Claude's drafted prediction. The draft writes nothing; a human tapping
 * Accept POSTs it to tradingDesk and the server flips `accepted`, so
 * accepted=false is what keeps the button armed.
 */
export interface PredictionProposal {
  statement: string;
  /** Probability 0–1, e.g. 0.7. */
  confidence: number;
  /** ISO date (YYYY-MM-DD) the prediction resolves by. */
  deadline: string;
  linked_book_id?: string;
  accepted?: boolean;
}

/**
 * Claude's drafted library entry. The draft writes nothing; a human tapping
 * Accept re-fetches the page through the sidecar and files it into the
 * room's reading library, and the server flips `accepted`.
 */
export interface ReadingProposal {
  url: string;
  title?: string | null;
  site?: string | null;
  published?: string | null;
  summary: string;
  key_claims?: string[];
  accepted?: boolean;
}

/**
 * The deadline watcher's proposed resolution for a logged prediction. The
 * proposal writes nothing; a human tapping Mark correct/incorrect relays
 * THEIR verdict to tradingDesk and the server flips `accepted`. An `unclear`
 * verdict renders no buttons — the evidence is the whole message.
 */
export interface ResolutionProposal {
  prediction_id: string;
  statement: string;
  verdict: 'correct' | 'incorrect' | 'unclear';
  rationale: string;
  evidence?: { url: string; title?: string | null }[];
  accepted?: boolean;
}

/** Transient "Dialectic is checking live prices…" signal, one per tool event. */
export interface LLMToolActivity {
  tool: string;
  label: string;
  status: 'started' | 'finished' | 'failed';
  latency_ms?: number;
}

export interface Message {
  id: string;
  thread_id: string;
  sequence: number;
  created_at: string;
  speaker_type: 'human' | 'llm_primary' | 'llm_provoker' | 'llm_annotator' | 'llm_persona' | 'system';
  user_id: string | null;
  message_type: 'text' | 'claim' | 'question' | 'definition' | 'counterexample';
  content: string;
  user_name?: string;
  persona_name?: string;
  protocol_id?: string;
  protocol_phase?: number;
  references_message_id?: string | null;
  /** Set only when the message was revised after posting. */
  edited_at?: string | null;
  /** Tool trace, when this turn checked something live. */
  metadata?: MessageMetadata | null;
  /** Carried on the live message_created broadcast; history loads fill the
   * attachments map instead (see appStore). */
  attachments?: Attachment[];
}

/** What a stored attachment is, as the server classifies it. */
export type AttachmentKind = 'image' | 'video' | 'file';

/**
 * One uploaded blob, as returned by POST /rooms/{id}/attachments.
 *
 * `url` is the server's own path (/attachments/{id}) and is NOT directly
 * usable as an <img src> — that endpoint requires the room token and the JWT.
 * Bytes are fetched with headers and rendered from an object URL; see
 * lib/attachments.ts.
 */
export interface Attachment {
  id: string;
  room_id: string;
  /** Null until the uploader binds it to the message that carries it. */
  message_id: string | null;
  uploader_user_id: string;
  kind: AttachmentKind;
  mime: string;
  bytes: number;
  sha256: string;
  width: number | null;
  height: number | null;
  original_name: string;
  storage_path: string;
  created_at: string;
  url: string;
  /** True when identical bytes were already in the room and the row was reused. */
  deduplicated?: boolean;
}

/** Reactions on one message, grouped by emoji. */
export interface Reaction {
  emoji: string;
  user_ids: string[];
  user_names: string[];
}

export interface Thread {
  id: string;
  room_id: string;
  parent_thread_id: string | null;
  title: string | null;
  message_count: number;
}

/** Mirrors home_activity.py's response models (GET /users/me/home/activity). */
export interface HomeActivityBranch {
  id: string;
  parent_thread_id: string | null;
  title: string | null;
  depth: number;
  message_count: number;
  unread_count: number;
  last_message_at: string | null;
}

export interface HomeActivityQuestion {
  thread_id: string;
  speaker: string;
  content_preview: string;
  timestamp: string;
}

export interface HomeActivityCommitment {
  id: string;
  claim: string;
  deadline: string;
  category: string;
}

/** One thing that moved in a room the whole household can see.
 *  Mirrors home_activity.HomeActivityMovement. A movement is a PROJECTION —
 *  `destination` is the canonical URL of where the thing actually lives. */
export interface HomeActivityMovement {
  kind:
    | 'reading_filed'
    | 'research_completed'
    | 'claim_warning'
    | 'wire_interruption'
    | 'prediction_review'
    | 'commitment_due'
    | 'echo_created'
    | 'thesis_lifecycle';
  room_id: string;
  thread_id: string | null;
  object_id: string | null;
  title: string;
  state: string;
  requires_judgment: boolean;
  occurred_at: string;
  destination: string;
}

export interface HomeActivityRoom {
  id: string;
  name: string | null;
  last_message_at: string | null;
  last_speaker: string | null;
  last_message_preview: string | null;
  unread_count: number;
  branches: HomeActivityBranch[];
  unresolved_questions: HomeActivityQuestion[];
  commitments_due: HomeActivityCommitment[];
  movement: HomeActivityMovement[];
}

export interface HomeActivityProjection {
  generated_at: string;
  rooms: HomeActivityRoom[];
}

/** One node of GET /rooms/{id}/genealogy — the fork tree with lineage. */
export interface ThreadNode {
  id: string;
  parent_thread_id: string | null;
  fork_point_message_id: string | null;
  title: string | null;
  message_count: number;
  created_at: string;
  depth: number;
  children: ThreadNode[];
}

export interface Memory {
  id: string;
  key: string;
  content: string;
  scope: 'room' | 'user' | 'global' | 'llm';
  version: number;
  status: 'active' | 'invalidated';
  personally_promoted: boolean;
}

export interface ConversationDNA {
  thread_id: string;
  tension: number;
  velocity: number;
  asymmetry: number;
  depth: number;
  divergence: number;
  memory_density: number;
  fingerprint: string;
  archetype: string;
}

export interface ProtocolState {
  id: string;
  thread_id: string;
  protocol_type: 'steelman' | 'socratic' | 'devil_advocate' | 'synthesis';
  status: 'invoked' | 'active' | 'concluding' | 'concluded' | 'aborted';
  current_phase: number;
  total_phases: number;
}

export interface Commitment {
  id: string;
  room_id: string;
  claim: string;
  resolution_criteria: string;
  category: 'prediction' | 'commitment' | 'bet';
  status: 'active' | 'resolved' | 'voided' | 'expired';
  deadline: string | null;
  created_at: string;
  confidence_history: ConfidenceEntry[];
}

export interface ConfidenceEntry {
  user_id: string | null;
  confidence: number;
  reasoning: string | null;
  recorded_at: string;
}

export interface SearchResult {
  id: string;
  thread_id: string;
  content: string;
  /** Server-generated ts_headline snippet containing <mark> tags. */
  snippet: string;
  sender_name: string;
  speaker_type: Message['speaker_type'];
  created_at: string;
  rank: number;
}

export interface PresenceUser {
  user_id: string;
  display_name: string;
  status: string;
  last_heartbeat: string | null;
}

export interface UserRoom {
  id: string;
  name: string | null;
  token: string;
  unread_count: number;
  last_message_at: string | null;
  last_message_preview: string | null;
  /** Last read receipt in this room; null if the user has never marked one. */
  last_read_at?: string | null;
  joined_at?: string | null;
  is_home: boolean;
  /** The caller's OWN Home administration capability. */
  can_manage_home: boolean;
}

export interface TradingSnapshot {
  v: number;
  timestamp: string;
  title?: string;
  nodeStates: Record<string, string>;
  confluenceScores?: Record<string, number>;
  cascadePhase?: { number: number; key: string; status: string };
  countdowns?: { nodeId: string; daysRemaining: number; deadline: string; label?: string }[];
  marketSnapshot?: Record<string, number>;
  scenarioImpacts?: Record<string, { probability: number; netImpact: number }>;
  portfolioSummary?: {
    monthlyBudget?: number;
    topPositions?: string[];
    sgovAvailable?: number;
    sgov_available?: number;
    allocated?: number;
  };
  // v2/v3 fields that were always pushed but never typed until the Bench
  // cockpit started rendering them (2026-08-14).
  tvIndicators?: Record<string, Record<string, number | null>>;
  alertEvents?: import('./trading').AlertEvent[];
  thesisId?: string;
  revision?: number;
  generatedAt?: string;
}

// WebSocket message types
export type InboundMessageType =
  | 'send_message' | 'typing_start' | 'typing_stop' | 'typing_content'
  | 'switch_thread' | 'fork_thread' | 'add_memory' | 'edit_memory' | 'invalidate_memory'
  | 'summon_llm' | 'cancel_llm' | 'invoke_protocol' | 'advance_protocol' | 'abort_protocol'
  | 'create_commitment' | 'record_confidence' | 'resolve_commitment'
  | 'ping' | 'presence_heartbeat';

export type OutboundMessageType =
  | 'message_created' | 'persona_response' | 'user_typing'
  | 'user_joined' | 'user_left' | 'presence_update'
  | 'llm_thinking' | 'llm_streaming' | 'llm_tool_activity'
  | 'llm_done' | 'llm_error' | 'llm_cancelled'
  | 'thread_created' | 'thread_forked' | 'memory_updated' | 'annotation_created'
  | 'protocol_started' | 'protocol_phase_advanced' | 'protocol_concluded' | 'protocol_aborted'
  | 'commitment_created' | 'commitment_confidence_updated' | 'commitment_resolved' | 'commitment_surfaced'
  | 'trading_update'
  | 'pong' | 'error';
