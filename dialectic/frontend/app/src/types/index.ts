export interface Room {
  id: string;
  name: string | null;
  token: string;
}

export interface User {
  id: string;
  display_name: string;
}

export interface Message {
  id: string;
  thread_id: string;
  sequence: number;
  created_at: string;
  speaker_type: 'human' | 'llm_primary' | 'llm_provoker' | 'llm_annotator' | 'system';
  user_id: string | null;
  message_type: 'text' | 'claim' | 'question' | 'definition' | 'counterexample';
  content: string;
  protocol_id?: string;
  protocol_phase?: number;
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

export interface PresenceUser {
  user_id: string;
  display_name: string;
  status: string;
  last_heartbeat: string | null;
}

export interface UserRoom {
  id: string;
  name: string | null;
  unread_count: number;
  last_message_at: string | null;
  last_message_preview: string | null;
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
  | 'fork_thread' | 'add_memory' | 'edit_memory' | 'invalidate_memory'
  | 'summon_llm' | 'cancel_llm' | 'invoke_protocol' | 'advance_protocol' | 'abort_protocol'
  | 'create_commitment' | 'record_confidence' | 'resolve_commitment'
  | 'ping' | 'presence_heartbeat';

export type OutboundMessageType =
  | 'message_created' | 'user_typing' | 'llm_thinking' | 'llm_streaming' | 'llm_done'
  | 'thread_forked' | 'memory_updated' | 'annotation_created'
  | 'protocol_started' | 'protocol_phase_advanced' | 'protocol_concluded' | 'protocol_aborted'
  | 'commitment_created' | 'commitment_resolved' | 'commitment_surfaced'
  | 'trading_update'
  | 'pong' | 'error';
