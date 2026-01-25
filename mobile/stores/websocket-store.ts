/**
 * ARCHITECTURE: Zustand store for WebSocket connection state.
 * WHY: Reactive state enables UI components to respond to connection changes.
 * TRADEOFF: Separate store from service adds indirection but follows React patterns.
 */

import { create } from 'zustand';

interface WebSocketState {
  isConnected: boolean;
  lastSequence: number;
  reconnectAttempts: number;

  // Actions
  setConnected: (connected: boolean) => void;
  setLastSequence: (sequence: number) => void;
  incrementReconnectAttempts: () => void;
  resetReconnectAttempts: () => void;
}

export const useWebSocketStore = create<WebSocketState>()((set) => ({
  isConnected: false,
  lastSequence: 0,
  reconnectAttempts: 0,

  setConnected: (connected) =>
    set((state) => {
      // Reset reconnect attempts on successful connection
      if (connected && !state.isConnected) {
        return { isConnected: connected, reconnectAttempts: 0 };
      }
      return { isConnected: connected };
    }),

  setLastSequence: (sequence) => set({ lastSequence: sequence }),

  incrementReconnectAttempts: () =>
    set((state) => ({
      reconnectAttempts: state.reconnectAttempts + 1,
    })),

  resetReconnectAttempts: () => set({ reconnectAttempts: 0 }),
}));
