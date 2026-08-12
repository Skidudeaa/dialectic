export interface Room {
  id: string;
  name: string | null;
  token: string;
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
  tools?: {
    iterations: number;
    degraded: boolean;
    calls: ToolCallTrace[];
  };
  /** A draft_prediction awaiting (or granted) the human Accept tap. */
  proposal?: PredictionProposal;
  /** A propose_thesis card — its tap opens the Create Thesis panel. */
  thesis_proposal?: ThesisProposal;
  /** Detected implicit commitments ("I bet…") awaiting the Accept tap. */
  commitment_proposals?: CommitmentProposal[];
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

/** Transient "Claude is checking live prices…" signal, one per tool event. */
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
