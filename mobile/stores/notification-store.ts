/**
 * ARCHITECTURE: MMKV-backed notification store for badge counts.
 * WHY: Track unread rooms and per-room counts for badge display.
 * TRADEOFF: seenMessageIds not persisted (session-based) to handle scroll detection.
 */

import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import { createMMKV, type MMKV } from 'react-native-mmkv';

// Separate MMKV instance for notification data
const storage: MMKV = createMMKV({ id: 'notification-storage' });

interface NotificationState {
  // CONTEXT.md: Badge = rooms with unread, not total messages
  totalUnreadRooms: number;
  // CONTEXT.md: Numeric badge per room in room list
  roomUnreadCounts: Record<string, number>;
  // Track which messages have been seen (for decrement logic) - session-based
  seenMessageIds: Set<string>;

  // Actions
  setTotalUnreadRooms: (count: number) => void;
  setRoomUnreadCount: (roomId: string, count: number) => void;
  markMessageSeen: (messageId: string, roomId: string) => void;
  decrementRoomUnread: (roomId: string) => void;
  clearRoomUnread: (roomId: string) => void;
  syncFromServer: (totalRooms: number, roomCounts: Record<string, number>) => void;
}

export const useNotificationStore = create<NotificationState>()(
  persist(
    (set, get) => ({
      totalUnreadRooms: 0,
      roomUnreadCounts: {},
      seenMessageIds: new Set(),

      setTotalUnreadRooms: (count) => set({ totalUnreadRooms: count }),

      setRoomUnreadCount: (roomId, count) =>
        set((state) => ({
          roomUnreadCounts: { ...state.roomUnreadCounts, [roomId]: count },
        })),

      markMessageSeen: (messageId, roomId) => {
        const state = get();
        if (state.seenMessageIds.has(messageId)) return; // Already seen

        const newSeen = new Set(state.seenMessageIds);
        newSeen.add(messageId);

        set({ seenMessageIds: newSeen });

        // Decrement room count
        get().decrementRoomUnread(roomId);
      },

      decrementRoomUnread: (roomId) =>
        set((state) => {
          const currentCount = state.roomUnreadCounts[roomId] || 0;
          const newCount = Math.max(0, currentCount - 1);
          const newCounts = { ...state.roomUnreadCounts, [roomId]: newCount };

          // Recalculate total rooms with unread
          const totalRooms = Object.values(newCounts).filter((c) => c > 0).length;

          return {
            roomUnreadCounts: newCounts,
            totalUnreadRooms: totalRooms,
          };
        }),

      clearRoomUnread: (roomId) =>
        set((state) => {
          const newCounts = { ...state.roomUnreadCounts, [roomId]: 0 };
          const totalRooms = Object.values(newCounts).filter((c) => c > 0).length;
          return {
            roomUnreadCounts: newCounts,
            totalUnreadRooms: totalRooms,
          };
        }),

      syncFromServer: (totalRooms, roomCounts) =>
        set({
          totalUnreadRooms: totalRooms,
          roomUnreadCounts: roomCounts,
        }),
    }),
    {
      name: 'notification-state',
      storage: createJSONStorage(() => ({
        setItem: (name, value) => storage.set(name, value),
        getItem: (name) => storage.getString(name) ?? null,
        removeItem: (name) => {
          storage.remove(name);
        },
      })),
      partialize: (state) => ({
        // Only persist counts, not seenMessageIds (ephemeral)
        totalUnreadRooms: state.totalUnreadRooms,
        roomUnreadCounts: state.roomUnreadCounts,
      }),
    }
  )
);
