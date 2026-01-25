# Phase 3: Real-Time Core - Research

**Researched:** 2026-01-25
**Domain:** WebSocket real-time messaging with presence, typing indicators, and offline handling for React Native/Expo
**Confidence:** HIGH

## Summary

This research covers real-time WebSocket communication for a React Native/Expo mobile app connecting to an existing FastAPI backend. The phase requires sub-100ms message delivery, typing indicators, presence tracking (Online/Away/Offline), and graceful reconnection with gap sync for missed messages.

The existing backend already has WebSocket infrastructure with message types for `typing_start`, `typing_stop`, `ping`, and `pong`. The mobile client needs to integrate with this existing API while adding robust connection management, app lifecycle handling (foreground/background), network state monitoring, and offline message queueing.

React Native includes a built-in WebSocket class, but for production-grade reconnection logic, the `reconnecting-websocket` library provides exponential backoff, message buffering, and configurable retry behavior. The existing FastAPI backend uses Uvicorn's built-in ping/pong (20-second intervals) for connection health, but the mobile client should implement application-level heartbeats for presence tracking.

**Primary recommendation:** Use React Native's built-in WebSocket wrapped with `reconnecting-websocket` for automatic reconnection, `@react-native-community/netinfo` for network state monitoring, React Native's AppState API for foreground/background detection, and Zustand with MMKV persistence for offline message queue and presence state. Extend the existing backend WebSocket protocol to support presence heartbeats and gap sync via the events table's sequence numbers.

## Standard Stack

The established libraries for real-time WebSocket communication in Expo/React Native:

### Core (Mobile)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| React Native WebSocket | built-in | Base WebSocket API | Native to React Native, no additional deps |
| `reconnecting-websocket` | ^4.4.x | Auto-reconnect with backoff | Platform-agnostic, WebSocket API compatible, message buffering |
| `@react-native-community/netinfo` | ^11.x | Network connectivity detection | Official community package, detects online/offline |
| `react-native-mmkv` | ^4.1.x | Fast offline storage | 30-100x faster than AsyncStorage, synchronous API |
| `zustand` | ^5.x | State management | Already in use (Phase 2), persist middleware for offline |
| `expo-network` | ~8.x | Expo-native network API | Alternative to NetInfo for pure Expo apps |

### Core (Backend Additions)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Existing FastAPI WebSocket | current | Real-time transport | Already implemented |
| Uvicorn ping/pong | current | Connection health | Built-in, 20-second default intervals |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `lodash.debounce` | ^4.0.8 | Typing indicator debounce | When lodash not already installed |
| `uuid` | ^11.x | Message ID generation | Client-side message IDs for offline queue |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `reconnecting-websocket` | `react-native-use-websocket` | Hook-based but reported Expo production issues |
| `reconnecting-websocket` | Socket.IO client | Heavier, requires Socket.IO server |
| `@react-native-community/netinfo` | `expo-network` | NetInfo more feature-rich, but expo-network simpler |
| MMKV | AsyncStorage | AsyncStorage 30-100x slower, works for small queues |

**Installation (Mobile):**
```bash
cd mobile
npm install reconnecting-websocket @react-native-community/netinfo react-native-mmkv
npx expo install expo-network
```

## Architecture Patterns

### Recommended Project Structure

```
mobile/
├── services/
│   ├── api.ts                    # Existing axios client
│   ├── websocket/
│   │   ├── index.ts              # WebSocketService singleton
│   │   ├── types.ts              # Message type definitions
│   │   ├── reconnect.ts          # Reconnection configuration
│   │   └── handlers.ts           # Message type handlers
│   └── sync/
│       ├── gap-sync.ts           # Fetch missed events on reconnect
│       └── offline-queue.ts      # Queue for offline messages
├── stores/
│   ├── websocket-store.ts        # Connection state, presence
│   ├── messages-store.ts         # Message state with optimistic updates
│   └── typing-store.ts           # Typing indicator state
├── hooks/
│   ├── use-websocket.ts          # WebSocket connection hook
│   ├── use-presence.ts           # Presence tracking hook
│   ├── use-typing.ts             # Typing indicator hook
│   ├── use-network.ts            # Network state hook
│   └── use-app-state.ts          # App foreground/background hook
└── contexts/
    └── realtime-context.tsx      # WebSocket provider (optional)

dialectic/
├── api/main.py                   # Existing FastAPI app
├── transport/
│   ├── websocket.py              # Existing - add presence tracking
│   └── handlers.py               # Existing - add gap sync handler
└── schema.sql                    # Add presence/read receipt tables
```

### Pattern 1: WebSocket Service Singleton

**What:** Centralized WebSocket connection manager with reconnection logic
**When to use:** All real-time communication - single connection per room

```typescript
// Source: https://github.com/pladaria/reconnecting-websocket
// services/websocket/index.ts
import ReconnectingWebSocket from 'reconnecting-websocket';
import NetInfo from '@react-native-community/netinfo';
import { AppState, AppStateStatus } from 'react-native';

interface WebSocketConfig {
  url: string;
  roomId: string;
  userId: string;
  token: string;
  onMessage: (data: InboundMessage) => void;
  onConnectionChange: (connected: boolean) => void;
}

class WebSocketService {
  private ws: ReconnectingWebSocket | null = null;
  private config: WebSocketConfig | null = null;
  private lastSequence: number = 0;
  private heartbeatInterval: NodeJS.Timeout | null = null;
  private appState: AppStateStatus = AppState.currentState;

  connect(config: WebSocketConfig) {
    this.config = config;

    const wsUrl = `${config.url.replace('http', 'ws')}/ws/${config.roomId}?token=${config.token}&user_id=${config.userId}`;

    this.ws = new ReconnectingWebSocket(wsUrl, [], {
      maxReconnectionDelay: 10000,
      minReconnectionDelay: 1000,
      reconnectionDelayGrowFactor: 1.3,
      connectionTimeout: 4000,
      maxRetries: Infinity,
      maxEnqueuedMessages: 100, // Buffer messages while disconnected
    });

    this.ws.addEventListener('open', this.handleOpen);
    this.ws.addEventListener('close', this.handleClose);
    this.ws.addEventListener('message', this.handleMessage);

    // Listen for app state changes
    AppState.addEventListener('change', this.handleAppStateChange);

    // Listen for network changes
    NetInfo.addEventListener(this.handleNetworkChange);
  }

  private handleOpen = async () => {
    this.config?.onConnectionChange(true);
    this.startHeartbeat();

    // Request gap sync if we have a last known sequence
    if (this.lastSequence > 0) {
      this.send({
        type: 'gap_sync_request',
        payload: { after_sequence: this.lastSequence }
      });
    }
  };

  private handleClose = () => {
    this.config?.onConnectionChange(false);
    this.stopHeartbeat();
  };

  private handleMessage = (event: MessageEvent) => {
    const data = JSON.parse(event.data);

    // Track sequence for gap sync
    if (data.sequence) {
      this.lastSequence = data.sequence;
    }

    this.config?.onMessage(data);
  };

  private handleAppStateChange = (nextAppState: AppStateStatus) => {
    const wasBackground = this.appState.match(/inactive|background/);
    const isNowActive = nextAppState === 'active';

    if (wasBackground && isNowActive) {
      // Returning from background - send presence update
      this.sendPresenceUpdate('online');
    } else if (nextAppState === 'background') {
      // Going to background - send away status
      this.sendPresenceUpdate('away');
    }

    this.appState = nextAppState;
  };

  private handleNetworkChange = (state: { isConnected: boolean | null }) => {
    if (state.isConnected === false) {
      // Network lost - will trigger reconnect automatically
      this.config?.onConnectionChange(false);
    }
  };

  private startHeartbeat() {
    // Send presence heartbeat every 30 seconds
    this.heartbeatInterval = setInterval(() => {
      this.send({ type: 'presence_heartbeat', payload: {} });
    }, 30000);
  }

  private stopHeartbeat() {
    if (this.heartbeatInterval) {
      clearInterval(this.heartbeatInterval);
      this.heartbeatInterval = null;
    }
  }

  sendPresenceUpdate(status: 'online' | 'away' | 'offline') {
    this.send({ type: 'presence_update', payload: { status } });
  }

  send(message: OutboundMessage) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(message));
    }
    // reconnecting-websocket buffers messages when disconnected
  }

  disconnect() {
    this.stopHeartbeat();
    this.ws?.close();
    this.ws = null;
  }
}

export const websocketService = new WebSocketService();
```

### Pattern 2: Typing Indicator with Debounce

**What:** Debounced typing events to reduce WebSocket traffic
**When to use:** Text input in message composer

```typescript
// Source: https://ably.com/blog/in-game-chat-room-typing-indicator
// hooks/use-typing.ts
import { useState, useCallback, useRef, useEffect } from 'react';
import { websocketService } from '@/services/websocket';

const TYPING_DEBOUNCE_MS = 500;
const TYPING_TIMEOUT_MS = 3000; // Per CONTEXT.md: 3 seconds

export function useTypingIndicator(roomId: string) {
  const [isTyping, setIsTyping] = useState(false);
  const typingTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const debounceRef = useRef<NodeJS.Timeout | null>(null);

  const sendTypingStart = useCallback(() => {
    if (!isTyping) {
      setIsTyping(true);
      websocketService.send({
        type: 'typing_start',
        payload: { typing: true }
      });
    }

    // Reset the stop timeout
    if (typingTimeoutRef.current) {
      clearTimeout(typingTimeoutRef.current);
    }

    typingTimeoutRef.current = setTimeout(() => {
      setIsTyping(false);
      websocketService.send({
        type: 'typing_stop',
        payload: { typing: false }
      });
    }, TYPING_TIMEOUT_MS);
  }, [isTyping]);

  const onTextChange = useCallback((text: string) => {
    // Debounce to avoid sending too many typing events
    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
    }

    debounceRef.current = setTimeout(() => {
      if (text.length > 0) {
        sendTypingStart();
      }
    }, TYPING_DEBOUNCE_MS);
  }, [sendTypingStart]);

  const stopTyping = useCallback(() => {
    if (isTyping) {
      setIsTyping(false);
      websocketService.send({
        type: 'typing_stop',
        payload: { typing: false }
      });
    }

    if (typingTimeoutRef.current) {
      clearTimeout(typingTimeoutRef.current);
    }
  }, [isTyping]);

  // Clean up on unmount
  useEffect(() => {
    return () => {
      if (typingTimeoutRef.current) clearTimeout(typingTimeoutRef.current);
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, []);

  return { onTextChange, stopTyping, isTyping };
}
```

### Pattern 3: Presence State Machine

**What:** State machine for Online/Away/Offline transitions per CONTEXT.md
**When to use:** User presence tracking across the app

```typescript
// Source: CONTEXT.md decisions
// stores/presence-store.ts
import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import { MMKV } from 'react-native-mmkv';

const storage = new MMKV();

// CONTEXT.md: Auto-Away after 5 minutes of inactivity
const INACTIVITY_TIMEOUT_MS = 5 * 60 * 1000;
// CONTEXT.md: Background -> Offline after 5 minutes
const BACKGROUND_OFFLINE_TIMEOUT_MS = 5 * 60 * 1000;

type PresenceStatus = 'online' | 'away' | 'offline';

interface PresenceState {
  status: PresenceStatus;
  lastActivity: number;
  isManualAway: boolean;
  backgroundedAt: number | null;

  // Actions
  setOnline: () => void;
  setAway: (manual?: boolean) => void;
  setOffline: () => void;
  recordActivity: () => void;
  onBackgrounded: () => void;
  onForegrounded: () => void;
}

export const usePresenceStore = create<PresenceState>()(
  persist(
    (set, get) => ({
      status: 'online',
      lastActivity: Date.now(),
      isManualAway: false,
      backgroundedAt: null,

      setOnline: () => set({
        status: 'online',
        isManualAway: false,
        lastActivity: Date.now()
      }),

      setAway: (manual = false) => set({
        status: 'away',
        isManualAway: manual
      }),

      setOffline: () => set({ status: 'offline' }),

      recordActivity: () => {
        const { status, isManualAway } = get();
        // Don't auto-return from manual away
        if (status === 'away' && isManualAway) return;

        set({
          status: 'online',
          lastActivity: Date.now()
        });
      },

      onBackgrounded: () => set({
        status: 'away',
        backgroundedAt: Date.now()
      }),

      onForegrounded: () => {
        const { backgroundedAt, isManualAway } = get();
        // If manually away, don't auto-return
        if (isManualAway) return;

        set({
          status: 'online',
          backgroundedAt: null,
          lastActivity: Date.now()
        });
      },
    }),
    {
      name: 'presence-storage',
      storage: createJSONStorage(() => ({
        setItem: (name, value) => storage.set(name, value),
        getItem: (name) => storage.getString(name) ?? null,
        removeItem: (name) => storage.delete(name),
      })),
    }
  )
);
```

### Pattern 4: Offline Message Queue

**What:** Queue messages when offline, send on reconnect in order
**When to use:** Message sending while disconnected

```typescript
// Source: https://medium.com/@the-expert-developer/offline-first-architecture
// services/sync/offline-queue.ts
import { MMKV } from 'react-native-mmkv';
import { v4 as uuidv4 } from 'uuid';

const storage = new MMKV({ id: 'offline-queue' });
const QUEUE_KEY = 'pending_messages';

interface QueuedMessage {
  id: string;            // Client-generated UUID
  type: 'send_message';
  payload: {
    content: string;
    thread_id: string;
    message_type: string;
    references_message_id?: string;
  };
  timestamp: number;
  status: 'pending' | 'sending' | 'failed';
  retryCount: number;
}

class OfflineQueue {
  private queue: QueuedMessage[] = [];

  constructor() {
    this.loadQueue();
  }

  private loadQueue() {
    const stored = storage.getString(QUEUE_KEY);
    if (stored) {
      this.queue = JSON.parse(stored);
    }
  }

  private saveQueue() {
    storage.set(QUEUE_KEY, JSON.stringify(this.queue));
  }

  enqueue(message: Omit<QueuedMessage, 'id' | 'timestamp' | 'status' | 'retryCount'>): string {
    const id = uuidv4();
    const queuedMessage: QueuedMessage = {
      ...message,
      id,
      timestamp: Date.now(),
      status: 'pending',
      retryCount: 0,
    };

    this.queue.push(queuedMessage);
    this.saveQueue();
    return id;
  }

  dequeue(): QueuedMessage | undefined {
    const message = this.queue.shift();
    this.saveQueue();
    return message;
  }

  markSending(id: string) {
    const msg = this.queue.find(m => m.id === id);
    if (msg) {
      msg.status = 'sending';
      this.saveQueue();
    }
  }

  markFailed(id: string) {
    const msg = this.queue.find(m => m.id === id);
    if (msg) {
      msg.status = 'failed';
      msg.retryCount++;
      this.saveQueue();
    }
  }

  remove(id: string) {
    this.queue = this.queue.filter(m => m.id !== id);
    this.saveQueue();
  }

  getAll(): QueuedMessage[] {
    return [...this.queue];
  }

  getPending(): QueuedMessage[] {
    return this.queue.filter(m => m.status === 'pending' || m.status === 'failed');
  }

  clear() {
    this.queue = [];
    this.saveQueue();
  }
}

export const offlineQueue = new OfflineQueue();
```

### Pattern 5: Gap Sync on Reconnect

**What:** Fetch missed events using server's event sequence numbers
**When to use:** After WebSocket reconnection

```typescript
// services/sync/gap-sync.ts
import { api } from '@/services/api';

interface GapSyncResult {
  events: Array<{
    id: string;
    sequence: number;
    timestamp: string;
    event_type: string;
    payload: Record<string, unknown>;
  }>;
  hasMore: boolean;
}

export async function fetchMissedEvents(
  roomId: string,
  token: string,
  afterSequence: number,
  limit: number = 100
): Promise<GapSyncResult> {
  // Uses existing /rooms/{room_id}/events endpoint
  const response = await api.get(`/rooms/${roomId}/events`, {
    params: {
      token,
      after_sequence: afterSequence,
      limit,
    }
  });

  return {
    events: response.data,
    hasMore: response.data.length === limit,
  };
}

// Called on WebSocket reconnect
export async function syncMissedMessages(
  roomId: string,
  token: string,
  lastKnownSequence: number,
  onMessage: (event: any) => void
) {
  let currentSequence = lastKnownSequence;
  let hasMore = true;

  while (hasMore) {
    const result = await fetchMissedEvents(roomId, token, currentSequence);

    for (const event of result.events) {
      // Process each missed event
      if (event.event_type === 'message_created') {
        onMessage({
          type: 'message_created',
          payload: event.payload,
          sequence: event.sequence,
          isSynced: true, // Mark as synced, not real-time
        });
      }
      currentSequence = event.sequence;
    }

    hasMore = result.hasMore;
  }

  return currentSequence;
}
```

### Pattern 6: Message Delivery States

**What:** Track Sent/Delivered/Read states per CONTEXT.md
**When to use:** Message list UI

```typescript
// stores/messages-store.ts
import { create } from 'zustand';

type DeliveryStatus = 'sending' | 'sent' | 'delivered' | 'read' | 'failed';

interface Message {
  id: string;
  clientId?: string;  // For optimistic updates
  threadId: string;
  content: string;
  senderId: string;
  createdAt: string;
  deliveryStatus: DeliveryStatus;
  readBy: string[];   // User IDs who have read
}

interface MessagesState {
  messages: Record<string, Message>;

  // Optimistic add for sending
  addOptimistic: (clientId: string, message: Omit<Message, 'id' | 'deliveryStatus'>) => void;
  // Confirm sent (server acknowledged)
  confirmSent: (clientId: string, serverId: string, sequence: number) => void;
  // Mark delivered to other devices
  markDelivered: (messageId: string) => void;
  // Mark read by user
  markRead: (messageId: string, userId: string) => void;
  // Mark failed
  markFailed: (clientId: string) => void;
}

export const useMessagesStore = create<MessagesState>()((set, get) => ({
  messages: {},

  addOptimistic: (clientId, message) => set(state => ({
    messages: {
      ...state.messages,
      [clientId]: {
        ...message,
        id: clientId,
        clientId,
        deliveryStatus: 'sending',
        readBy: [],
      }
    }
  })),

  confirmSent: (clientId, serverId, sequence) => set(state => {
    const { [clientId]: optimistic, ...rest } = state.messages;
    if (!optimistic) return state;

    return {
      messages: {
        ...rest,
        [serverId]: {
          ...optimistic,
          id: serverId,
          deliveryStatus: 'sent',
        }
      }
    };
  }),

  markDelivered: (messageId) => set(state => {
    const msg = state.messages[messageId];
    if (!msg) return state;

    return {
      messages: {
        ...state.messages,
        [messageId]: { ...msg, deliveryStatus: 'delivered' }
      }
    };
  }),

  markRead: (messageId, userId) => set(state => {
    const msg = state.messages[messageId];
    if (!msg) return state;

    const readBy = msg.readBy.includes(userId)
      ? msg.readBy
      : [...msg.readBy, userId];

    return {
      messages: {
        ...state.messages,
        [messageId]: {
          ...msg,
          deliveryStatus: 'read',
          readBy,
        }
      }
    };
  }),

  markFailed: (clientId) => set(state => {
    const msg = state.messages[clientId];
    if (!msg) return state;

    return {
      messages: {
        ...state.messages,
        [clientId]: { ...msg, deliveryStatus: 'failed' }
      }
    };
  }),
}));
```

### Anti-Patterns to Avoid

- **Creating new WebSocket per screen:** Use singleton pattern; multiple connections cause race conditions
- **No message buffering during offline:** Messages sent while disconnected should queue, not silently fail
- **Polling for presence:** Use WebSocket heartbeats, not REST polling
- **Ignoring app lifecycle:** Background apps should transition to Away, not stay Online
- **No gap sync on reconnect:** Users miss messages if you don't fetch events after reconnection
- **Infinite reconnection without backoff:** Exponential backoff prevents server overload
- **Storing large message history in MMKV:** MMKV is for small data; use AsyncStorage or SQLite for large datasets

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| WebSocket reconnection | Manual retry loop | `reconnecting-websocket` | Handles backoff, buffering, edge cases |
| Network detection | Poll or timer-based | `@react-native-community/netinfo` | Native events, accurate, efficient |
| App state detection | Manual listeners | React Native `AppState` | Built-in, handles all platforms |
| Typing debounce | Manual setTimeout | Debounce utility (lodash or custom) | Tested, handles edge cases |
| Offline storage | AsyncStorage for queue | MMKV | 30-100x faster for frequent writes |
| State persistence | Manual load/save | Zustand persist middleware | Handles hydration, async correctly |
| UUID generation | Custom ID function | `uuid` package | RFC-compliant, collision-resistant |

**Key insight:** Real-time communication has many edge cases (network flapping, app backgrounding, iOS killing connections, message ordering). Libraries handle these; custom solutions don't anticipate them all.

## Common Pitfalls

### Pitfall 1: iOS Kills WebSocket in Background

**What goes wrong:** WebSocket disconnects immediately when app backgrounds on iOS
**Why it happens:** iOS aggressively terminates network connections for backgrounded apps
**How to avoid:**
- Accept disconnection as normal; reconnect on foreground
- Send Away status before backgrounding
- Use gap sync to recover missed messages
**Warning signs:** Users report missing messages after returning from background

### Pitfall 2: Race Condition Between Optimistic Update and Server Confirmation

**What goes wrong:** Duplicate messages appear, or message order scrambled
**Why it happens:** Server response arrives while optimistic update already in state
**How to avoid:**
- Use client-generated UUID for optimistic updates
- Replace optimistic entry with server entry by matching client ID
- Never use array index or timestamp for matching
**Warning signs:** Duplicate messages, messages jumping positions

### Pitfall 3: Typing Indicator Floods WebSocket

**What goes wrong:** Server overwhelmed with typing events, latency increases
**Why it happens:** Sending event on every keystroke without debounce
**How to avoid:**
- Debounce typing_start (500ms)
- Send typing_stop only after 3 seconds of no input (per CONTEXT.md)
- Throttle to max 1 typing event per second
**Warning signs:** Server logs show excessive typing events, latency spikes

### Pitfall 4: Presence Heartbeat Not Reaching Server

**What goes wrong:** Users shown as Offline when they're Online
**Why it happens:** Uvicorn's built-in ping/pong is at protocol level, not application level
**How to avoid:**
- Implement application-level heartbeat (30 seconds)
- Server marks user offline after missing 2 heartbeats (60 seconds)
- Heartbeat should be separate from Uvicorn ping/pong
**Warning signs:** Users appear offline despite active WebSocket

### Pitfall 5: Gap Sync Creates Thundering Herd

**What goes wrong:** Server overloaded when many clients reconnect simultaneously
**Why it happens:** Network outage → all clients reconnect → all request gap sync at once
**How to avoid:**
- Add random jitter to reconnection delay
- Limit gap sync batch size (100 events max)
- Server should rate-limit gap sync requests per user
**Warning signs:** Server crashes after network restoration

### Pitfall 6: MMKV Queue Grows Unbounded

**What goes wrong:** App crashes or slows down during extended offline periods
**Why it happens:** Queueing messages indefinitely without size limit
**How to avoid:**
- Limit queue to 100 messages max
- Oldest messages dropped when limit exceeded
- Show user feedback when queue is full
**Warning signs:** Memory usage grows, app sluggish

### Pitfall 7: Sequence Number Desync After Server Restart

**What goes wrong:** Gap sync returns wrong events or misses events
**Why it happens:** Client's last sequence number invalid after server restart
**How to avoid:**
- Include room_id in sequence queries
- Events table uses BIGSERIAL (never resets)
- Validate sequence exists before gap sync
**Warning signs:** Missing messages after server deployment

## Code Examples

### Backend: Presence WebSocket Handler

```python
# Source: Extend dialectic/transport/handlers.py
# Add to MessageHandler class

async def _handle_presence_heartbeat(self, conn: Connection, payload: dict) -> None:
    """Handle presence heartbeat from client."""
    now = datetime.utcnow()

    # Update user's last_seen in presence tracking
    await self.db.execute(
        """INSERT INTO user_presence (user_id, room_id, status, last_heartbeat)
           VALUES ($1, $2, 'online', $3)
           ON CONFLICT (user_id, room_id)
           DO UPDATE SET status = 'online', last_heartbeat = $3""",
        conn.user_id, conn.room_id, now
    )

    # Broadcast presence update to room
    await self.connections.broadcast(conn.room_id, OutboundMessage(
        type="presence_update",
        payload={
            "user_id": str(conn.user_id),
            "status": "online",
            "timestamp": now.isoformat(),
        },
    ), exclude_user=conn.user_id)

async def _handle_presence_update(self, conn: Connection, payload: dict) -> None:
    """Handle explicit presence status change."""
    status = payload.get("status", "online")
    now = datetime.utcnow()

    await self.db.execute(
        """INSERT INTO user_presence (user_id, room_id, status, last_heartbeat)
           VALUES ($1, $2, $3, $4)
           ON CONFLICT (user_id, room_id)
           DO UPDATE SET status = $3, last_heartbeat = $4""",
        conn.user_id, conn.room_id, status, now
    )

    await self.connections.broadcast(conn.room_id, OutboundMessage(
        type="presence_update",
        payload={
            "user_id": str(conn.user_id),
            "status": status,
            "timestamp": now.isoformat(),
        },
    ), exclude_user=conn.user_id)
```

### Backend: Message Delivery Receipts

```python
# Add to handlers.py

async def _handle_message_delivered(self, conn: Connection, payload: dict) -> None:
    """Mark message as delivered to this user's device."""
    message_id = UUID(payload["message_id"])
    now = datetime.utcnow()

    # Record delivery
    await self.db.execute(
        """INSERT INTO message_receipts (message_id, user_id, receipt_type, timestamp)
           VALUES ($1, $2, 'delivered', $3)
           ON CONFLICT (message_id, user_id, receipt_type) DO NOTHING""",
        message_id, conn.user_id, now
    )

    # Notify sender
    message_row = await self.db.fetchrow(
        "SELECT user_id FROM messages WHERE id = $1", message_id
    )
    if message_row:
        await self.connections.send_to_user(
            message_row['user_id'],
            conn.room_id,
            OutboundMessage(
                type="delivery_receipt",
                payload={
                    "message_id": str(message_id),
                    "status": "delivered",
                    "recipient_id": str(conn.user_id),
                }
            )
        )

async def _handle_message_read(self, conn: Connection, payload: dict) -> None:
    """Mark message as read by this user."""
    message_id = UUID(payload["message_id"])
    now = datetime.utcnow()

    await self.db.execute(
        """INSERT INTO message_receipts (message_id, user_id, receipt_type, timestamp)
           VALUES ($1, $2, 'read', $3)
           ON CONFLICT (message_id, user_id, receipt_type) DO NOTHING""",
        message_id, conn.user_id, now
    )

    # Notify sender
    message_row = await self.db.fetchrow(
        "SELECT user_id FROM messages WHERE id = $1", message_id
    )
    if message_row:
        await self.connections.send_to_user(
            message_row['user_id'],
            conn.room_id,
            OutboundMessage(
                type="read_receipt",
                payload={
                    "message_id": str(message_id),
                    "reader_id": str(conn.user_id),
                }
            )
        )
```

### Database Schema Additions

```sql
-- Add to dialectic/schema.sql

-- User presence tracking
CREATE TABLE user_presence (
    user_id UUID NOT NULL REFERENCES users(id),
    room_id UUID NOT NULL REFERENCES rooms(id),
    status TEXT NOT NULL DEFAULT 'offline',
    last_heartbeat TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, room_id)
);

CREATE INDEX idx_user_presence_room ON user_presence(room_id, status);

-- Message delivery receipts
CREATE TABLE message_receipts (
    message_id UUID NOT NULL REFERENCES messages(id),
    user_id UUID NOT NULL REFERENCES users(id),
    receipt_type TEXT NOT NULL,  -- 'delivered' | 'read'
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (message_id, user_id, receipt_type)
);

CREATE INDEX idx_message_receipts_message ON message_receipts(message_id);
```

### Mobile: App State and Network Hooks

```typescript
// hooks/use-app-state.ts
import { useEffect, useState, useRef } from 'react';
import { AppState, AppStateStatus } from 'react-native';

export function useAppState() {
  const [appState, setAppState] = useState<AppStateStatus>(AppState.currentState);
  const previousRef = useRef<AppStateStatus>(AppState.currentState);

  useEffect(() => {
    const subscription = AppState.addEventListener('change', (nextState) => {
      setAppState(nextState);
      previousRef.current = appState;
    });

    return () => subscription.remove();
  }, [appState]);

  return {
    current: appState,
    previous: previousRef.current,
    isActive: appState === 'active',
    isBackground: appState === 'background',
    wasBackground: previousRef.current !== 'active' && appState === 'active',
  };
}

// hooks/use-network.ts
import { useEffect, useState } from 'react';
import NetInfo, { NetInfoState } from '@react-native-community/netinfo';

export function useNetwork() {
  const [state, setState] = useState<NetInfoState | null>(null);

  useEffect(() => {
    const unsubscribe = NetInfo.addEventListener(setState);
    return () => unsubscribe();
  }, []);

  return {
    isConnected: state?.isConnected ?? null,
    isInternetReachable: state?.isInternetReachable ?? null,
    type: state?.type ?? 'unknown',
  };
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Socket.IO for mobile | Native WebSocket + reconnecting library | 2023+ | Simpler, smaller bundle, better Expo compat |
| AsyncStorage for queues | MMKV for fast storage | 2024 | 30-100x performance improvement |
| Redux for real-time state | Zustand with persist | 2024+ | Simpler API, better React 18+ support |
| Manual reconnection logic | reconnecting-websocket library | 2020+ | Battle-tested, handles edge cases |
| Polling for presence | WebSocket heartbeats | Standard | Lower latency, reduced server load |
| REST for read receipts | WebSocket events | Standard | Real-time feedback |

**Deprecated/outdated:**
- `react-native-websocket` wrapper: Use native WebSocket directly
- `socket.io-client` for simple WebSocket: Overhead not justified unless using Socket.IO features
- `AsyncStorage` for high-frequency writes: MMKV is dramatically faster

## Open Questions

Things that couldn't be fully resolved:

1. **Exact heartbeat interval for presence**
   - What we know: 20-30 seconds is common; Uvicorn defaults to 20s
   - What's unclear: Optimal balance for mobile battery vs presence accuracy
   - Recommendation: Start with 30 seconds, adjust based on production data

2. **Gap sync buffer size on server**
   - What we know: 100 events per request is reasonable
   - What's unclear: How long to retain events for gap sync
   - Recommendation: 24 hours or 1000 events per room, whichever comes first

3. **MMKV vs AsyncStorage for message cache**
   - What we know: MMKV faster but limited size; AsyncStorage slower but larger
   - What's unclear: Expected message volume per room
   - Recommendation: MMKV for offline queue (small), AsyncStorage/SQLite for message cache (large)

4. **LLM presence indicator behavior**
   - What we know: Per CONTEXT.md, LLM shows presence when active
   - What's unclear: What "active" means - only during generation, or during any processing?
   - Recommendation: Show Online when LLM is generating, neutral (no indicator) otherwise

## Sources

### Primary (HIGH confidence)
- [React Native AppState API](https://reactnative.dev/docs/appstate) - Official documentation
- [Expo Network API](https://docs.expo.dev/versions/latest/sdk/network/) - Network state detection
- [reconnecting-websocket GitHub](https://github.com/pladaria/reconnecting-websocket) - Library API and configuration
- [websockets keepalive docs](https://websockets.readthedocs.io/en/stable/topics/keepalive.html) - Uvicorn ping/pong behavior

### Secondary (MEDIUM confidence)
- [Ably WebSocket Architecture Best Practices](https://ably.com/topic/websocket-architecture-best-practices) - Heartbeat patterns
- [Ably Typing Indicator Guide](https://ably.com/blog/in-game-chat-room-typing-indicator) - Debounce patterns
- [Zustand Persist Documentation](https://zustand.docs.pmnd.rs/integrations/persisting-store-data) - Offline storage
- [react-native-mmkv GitHub](https://github.com/mrousavy/react-native-mmkv) - MMKV features and performance
- [NetInfo Community Package](https://github.com/react-native-netinfo/react-native-netinfo) - Network detection

### Tertiary (LOW confidence)
- WebSearch results for mobile chat patterns - General guidance
- Medium articles on offline-first architecture - Community patterns, needs validation

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Official React Native APIs, well-maintained libraries
- Architecture patterns: HIGH - Standard patterns, verified with docs
- Pitfalls: MEDIUM - Combination of docs and community reports
- Backend additions: HIGH - Extends existing working code

**Research date:** 2026-01-25
**Valid until:** 2026-02-25 (30 days - stable ecosystem)
