// Outbox types — local to the bridge/badge feature.
// WHY a NEW file (not lib/types.ts): the user is concurrently editing
// lib/types.ts for the builder feature; keeping our types separate avoids
// merge conflicts.

export interface OutboxStatus {
  queued: number;
  byRoom: Record<string, number>;
  oldest: string | null;   // ISO 8601 UTC, null when empty
  newest: string | null;
  totalBytes: number;
  replayCap: number;
}

// "Drain now" response — POST /api/bridge/outbox/replay.
// `errors` is per-room and may be populated even when the request itself
// returned 200 (e.g. dialectic unreachable -> partial drain). The badge
// renders this as a warning toast with a Retry action, not an error.
export interface PerRoomReplayResult {
  roomId: string;
  replayed: number;
  remaining: number;
  errors: string[];
}

export interface OutboxReplayResponse {
  replayed: number;
  remaining: number;
  perRoom: PerRoomReplayResult[];
  dialecticUrl: string;
  durationMs: number;
}

export interface OutboxReplayRequest {
  roomId?: string;
}
