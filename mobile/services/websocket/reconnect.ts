/**
 * ARCHITECTURE: Reconnection configuration for reconnecting-websocket.
 * WHY: Exponential backoff prevents server overload during outages.
 * TRADEOFF: Longer delays reduce responsiveness but improve reliability.
 */

export const RECONNECT_OPTIONS = {
  maxReconnectionDelay: 10000, // Max 10s between retries
  minReconnectionDelay: 1000, // Start at 1s
  reconnectionDelayGrowFactor: 1.3, // Exponential backoff multiplier
  connectionTimeout: 4000, // 4s connection timeout
  maxRetries: Infinity, // Never give up - mobile users expect persistence
  maxEnqueuedMessages: 100, // Buffer messages while disconnected
};
