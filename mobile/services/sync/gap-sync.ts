/**
 * ARCHITECTURE: Gap sync using existing /rooms/{room_id}/events endpoint.
 * WHY: Fetch missed events after reconnection to maintain consistency.
 * TRADEOFF: Batched fetch (100 max) vs real-time replay.
 */

import { api } from '@/services/api';

interface EventPayload {
  id: string;
  sequence: number;
  timestamp: string;
  event_type: string;
  user_id: string | null;
  payload: Record<string, unknown>;
}

interface GapSyncResult {
  events: EventPayload[];
  hasMore: boolean;
  lastSequence: number;
}

export async function fetchMissedEvents(
  roomId: string,
  token: string,
  afterSequence: number,
  limit: number = 100
): Promise<GapSyncResult> {
  const response = await api.get(`/rooms/${roomId}/events`, {
    params: {
      token,
      after_sequence: afterSequence,
      limit,
    },
  });

  const events: EventPayload[] = response.data;
  const lastSequence =
    events.length > 0 ? events[events.length - 1].sequence : afterSequence;

  return {
    events,
    hasMore: events.length === limit,
    lastSequence,
  };
}

export async function syncMissedMessages(
  roomId: string,
  token: string,
  lastKnownSequence: number,
  onEvent: (event: EventPayload) => void
): Promise<number> {
  let currentSequence = lastKnownSequence;
  let hasMore = true;

  while (hasMore) {
    const result = await fetchMissedEvents(roomId, token, currentSequence);

    for (const event of result.events) {
      onEvent(event);
    }

    currentSequence = result.lastSequence;
    hasMore = result.hasMore;
  }

  return currentSequence;
}
