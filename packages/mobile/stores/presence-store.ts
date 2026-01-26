/**
 * ARCHITECTURE: Zustand store for presence state with three-state machine.
 * WHY: Presence requires both my status and tracking other participants' status.
 * TRADEOFF: Stores participants in memory (scales fine for expected room sizes of 2-5 users).
 *
 * State Machine:
 * - ONLINE: User is active and engaged
 * - AWAY: User is idle (5 min inactivity) or app backgrounded (manual away overrides auto-return)
 * - OFFLINE: User disconnected or 5 min in background
 *
 * Transitions:
 * - recordActivity: Returns to ONLINE from auto-away (not manual)
 * - setAway(manual=true): Manual away that persists until explicit setOnline
 * - setAway(manual=false): Auto-away that will return to ONLINE on activity
 */

import { create } from 'zustand';
import { websocketService } from '@/services/websocket';

// CONTEXT.md: 5 minutes inactivity triggers Away
const INACTIVITY_TIMEOUT_MS = 5 * 60 * 1000;

type PresenceStatus = 'online' | 'away' | 'offline';

interface ParticipantPresence {
  status: PresenceStatus;
  lastSeen?: string; // ISO timestamp for offline users
}

interface PresenceState {
  // My presence
  myStatus: PresenceStatus;
  isManualAway: boolean;
  lastActivity: number;

  // Other participants (keyed by user_id)
  participants: Record<string, ParticipantPresence>;

  // Actions for my presence
  setOnline: () => void;
  setAway: (manual?: boolean) => void;
  setOffline: () => void;
  recordActivity: () => void;

  // Actions for participants
  updateParticipant: (userId: string, status: PresenceStatus, lastSeen?: string) => void;
  removeParticipant: (userId: string) => void;
  clearParticipants: () => void;
}

export const usePresenceStore = create<PresenceState>()((set, get) => ({
  myStatus: 'online',
  isManualAway: false,
  lastActivity: Date.now(),
  participants: {},

  setOnline: () => {
    set({ myStatus: 'online', isManualAway: false, lastActivity: Date.now() });
    websocketService.sendPresenceUpdate('online');
  },

  setAway: (manual = false) => {
    set({ myStatus: 'away', isManualAway: manual });
    websocketService.sendPresenceUpdate('away');
  },

  setOffline: () => {
    set({ myStatus: 'offline' });
    websocketService.sendPresenceUpdate('offline');
  },

  recordActivity: () => {
    const { myStatus, isManualAway } = get();
    // Don't auto-return from manual away
    if (myStatus === 'away' && isManualAway) return;

    if (myStatus !== 'online') {
      websocketService.sendPresenceUpdate('online');
    }
    set({ myStatus: 'online', lastActivity: Date.now() });
  },

  updateParticipant: (userId, status, lastSeen) => {
    set((state) => ({
      participants: {
        ...state.participants,
        [userId]: { status, lastSeen },
      },
    }));
  },

  removeParticipant: (userId) => {
    set((state) => {
      const { [userId]: _, ...rest } = state.participants;
      return { participants: rest };
    });
  },

  clearParticipants: () => set({ participants: {} }),
}));

// Export type for external use
export type { PresenceStatus, ParticipantPresence };
