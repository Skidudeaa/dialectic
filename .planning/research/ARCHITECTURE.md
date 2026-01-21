# Architecture Patterns

**Domain:** Real-time collaborative workspace with LLM participant
**Researched:** 2026-01-20

## Executive Summary

Real-time collaborative apps with LLM integration require a layered architecture that separates concerns across client presentation, transport management, LLM orchestration, and persistence. The existing Dialectic backend provides a solid foundation with its WebSocket connection registry, heuristic interjection engine, and event-sourced data model. Cairn contributes session management, search, and AI service patterns with MongoDB/Redis infrastructure.

The key architectural challenge is **unifying these backends** while adding **cross-platform mobile clients** that handle unreliable network conditions gracefully.

## Recommended Architecture

```
                                    ┌─────────────────────────────────┐
                                    │     Mobile Clients              │
                                    │  (React Native / Flutter)       │
                                    └────────────┬────────────────────┘
                                                 │
                          ┌──────────────────────┼──────────────────────┐
                          │                      │                      │
                          ▼                      ▼                      ▼
                   ┌────────────┐         ┌────────────┐         ┌────────────┐
                   │ WebSocket  │         │   REST     │         │   Push     │
                   │ Connection │         │   API      │         │ Notifications│
                   └─────┬──────┘         └─────┬──────┘         └─────┬──────┘
                         │                      │                      │
                         └──────────────────────┼──────────────────────┘
                                                │
                         ┌──────────────────────┴──────────────────────┐
                         │              API Gateway Layer              │
                         │         (FastAPI + Auth + Rate Limit)       │
                         └──────────────────────┬──────────────────────┘
                                                │
              ┌─────────────────────────────────┼─────────────────────────────────┐
              │                                 │                                 │
              ▼                                 ▼                                 ▼
       ┌─────────────┐                  ┌─────────────┐                  ┌─────────────┐
       │  Dialectic  │                  │   Cairn     │                  │   Shared    │
       │   Service   │                  │  Service    │                  │  Services   │
       │             │                  │             │                  │             │
       │ - Rooms     │                  │ - Sessions  │                  │ - Auth      │
       │ - Threads   │                  │ - Insights  │                  │ - Users     │
       │ - Messages  │                  │ - Patterns  │                  │ - Billing   │
       │ - Memories  │                  │ - Search    │                  │             │
       └──────┬──────┘                  └──────┬──────┘                  └──────┬──────┘
              │                                 │                                 │
              │         ┌───────────────────────┼───────────────────────┐        │
              │         │                       │                       │        │
              ▼         ▼                       ▼                       ▼        ▼
       ┌─────────────────────┐          ┌─────────────┐         ┌─────────────────────┐
       │ LLM Orchestration   │          │   Redis     │         │    Persistence      │
       │ Layer               │          │   Pub/Sub   │         │                     │
       │                     │          │   + Cache   │         │  PostgreSQL (Dial)  │
       │ - Provider Router   │          │             │         │  MongoDB (Cairn)    │
       │ - Interjection      │          └─────────────┘         │  pgvector           │
       │ - Prompt Builder    │                                  └─────────────────────┘
       └──────────┬──────────┘
                  │
                  ▼
       ┌─────────────────────┐
       │  LLM Providers      │
       │  - Anthropic        │
       │  - OpenAI (fallback)│
       └─────────────────────┘
```

## Component Boundaries

| Component | Responsibility | Communicates With | Data Ownership |
|-----------|---------------|-------------------|----------------|
| **Mobile Client** | UI, local state, offline queue, reconnection | API Gateway via WebSocket/REST | Local cache |
| **API Gateway** | Auth, rate limiting, request routing, WebSocket upgrade | All backend services | None (stateless) |
| **Connection Manager** | WebSocket lifecycle, room membership, message routing | Redis Pub/Sub, Dialectic Service | Connection registry |
| **Dialectic Service** | Rooms, threads, messages, memories, event sourcing | PostgreSQL, LLM Orchestrator, Redis | Collaborative state |
| **Cairn Service** | Sessions, insights, patterns, search | MongoDB, Redis Cache | Development history |
| **LLM Orchestrator** | Provider routing, retry logic, interjection heuristics, prompt assembly | LLM Providers, Memory layer | None (stateless) |
| **Shared Services** | Authentication, user profiles, billing | PostgreSQL | User/auth data |
| **Redis** | Pub/sub for horizontal scaling, caching, session state | All services | Ephemeral state |
| **PostgreSQL** | Dialectic data, shared user data, embeddings (pgvector) | Dialectic Service, Shared Services | Persistent state |
| **MongoDB** | Cairn sessions, events, insights | Cairn Service | Session data |

## Data Flow Patterns

### Pattern 1: Human Message Flow

```
Mobile Client
    │
    │ 1. WebSocket: {type: "send_message", payload: {content: "..."}}
    ▼
API Gateway (validates auth, rate limit)
    │
    │ 2. Route to Connection Manager
    ▼
Connection Manager
    │
    │ 3. Persist message to PostgreSQL
    │ 4. Log event (event sourcing)
    ▼
Dialectic Service
    │
    │ 5. Broadcast "message_created" to room via Redis Pub/Sub
    ▼
Redis Pub/Sub
    │
    │ 6. Fan out to all Connection Manager instances
    ▼
All Connection Managers
    │
    │ 7. WebSocket push to all room members
    ▼
All Mobile Clients in room
```

### Pattern 2: LLM Interjection Flow

```
Message arrives → Dialectic Service
    │
    │ 1. Compute semantic novelty (embedding comparison)
    │ 2. Check interjection heuristics
    ▼
InterjectionEngine.decide()
    │
    │ Decision: {should_interject: true, use_provoker: false}
    ▼
    │ 3. Broadcast "llm_thinking" to room
    │
LLM Orchestrator
    │
    │ 4. Build prompt (system + room rules + user modifiers + memories)
    │ 5. Route request (Anthropic primary → OpenAI fallback)
    ▼
Model Router (retry with exponential backoff)
    │
    │ 6. Stream response (token-wise if streaming enabled)
    ▼
    │ 7. Persist LLM message
    │ 8. Broadcast "message_created" with speaker_type=llm_primary
    ▼
All Mobile Clients in room
```

### Pattern 3: Mobile Reconnection Flow

```
Mobile loses connection
    │
    ▼
Local state retained (messages, room ID, last sequence)
    │
    ▼
Exponential backoff reconnection (1s → 2s → 4s → ... → 30s cap)
    │
    │ Reconnection succeeds
    ▼
WebSocket: {type: "sync_request", payload: {last_sequence: 42}}
    │
    ▼
API Gateway
    │
    │ Fetch events WHERE sequence > 42
    ▼
Dialectic Service
    │
    │ Return missed events
    ▼
Mobile Client applies events to local state
```

### Pattern 4: Offline Queue (Mobile Only)

```
Mobile offline
    │
    ▼
User composes message → Queue locally (SQLite/Realm)
    │
    ▼
Connection restored
    │
    ▼
Drain queue in order, send each via WebSocket
    │
    │ Server acknowledges with sequence numbers
    ▼
Update local state with server-assigned sequences
```

## Existing Component Integration Strategy

### Dialectic Components to Retain (HIGH VALUE)

| Component | Location | Value | Integration Notes |
|-----------|----------|-------|-------------------|
| `ConnectionManager` | `transport/websocket.py` | Core WebSocket registry | Extend for Redis pub/sub |
| `MessageHandler` | `transport/handlers.py` | Message dispatch logic | Keep as-is |
| `LLMOrchestrator` | `llm/orchestrator.py` | Central LLM coordination | Add streaming support |
| `InterjectionEngine` | `llm/heuristics.py` | When LLM speaks | Tune thresholds |
| `PromptBuilder` | `llm/prompts.py` | Prompt assembly | Add user modifier injection |
| `ModelRouter` | `llm/router.py` | Retry + fallback | Production-ready |
| `MemoryManager` | `memory/manager.py` | Vector search, versioning | Excellent |
| Event sourcing schema | `schema.sql` | Append-only events | Foundation for audit |

### Dialectic Components Needing Extension

| Component | Current State | Required Extension |
|-----------|---------------|-------------------|
| `ConnectionManager` | In-memory dict | Redis pub/sub for horizontal scaling |
| `LLMOrchestrator` | Block until complete | Token-wise streaming |
| WebSocket endpoint | Single room focus | Multi-room subscriptions |
| Auth | Token-per-room | JWT with user identity |

### Cairn Components to Retain

| Component | Location | Value | Integration Notes |
|-----------|----------|-------|-------------------|
| `DatabaseManager` | `shared/database_wrapper.py` | MongoDB abstraction | Keep for sessions |
| `CacheManager` | `shared/cache_wrapper.py` | Redis caching | Unify with Dialectic |
| `SessionService` | `services/session_service.py` | Session lifecycle | Use for development sessions |
| `SearchService` | `services/search_service.py` | Text search | Complement pgvector semantic |
| AI Provider interface | `services/ai_provider.py` | LLM abstraction | Potentially merge |

### Unification Strategy

**Phase 1: Shared Infrastructure**
- Single Redis instance for both Dialectic (pub/sub) and Cairn (caching)
- Unified auth service (JWT) used by both
- Shared user table in PostgreSQL

**Phase 2: API Gateway**
- FastAPI gateway routes `/api/rooms/*` to Dialectic
- Routes `/api/sessions/*` to Cairn
- Single WebSocket endpoint handles both

**Phase 3: Cross-Service Features**
- Cairn sessions can reference Dialectic rooms
- Dialectic memories can be promoted to Cairn insights
- Unified search across both (federated query)

## Patterns to Follow

### Pattern 1: Event Sourcing (Dialectic Model)

**What:** All state changes recorded as append-only events. Current state derived from event replay.

**When:** Collaborative data where audit trail, undo, and temporal queries matter.

**Example (existing in Dialectic):**
```python
event = Event(
    id=uuid4(),
    timestamp=now,
    event_type=EventType.MESSAGE_CREATED,
    room_id=room.id,
    thread_id=thread.id,
    payload=MessageCreatedPayload(...).model_dump()
)
await db.execute("INSERT INTO events (...) VALUES (...)", ...)
```

**Build Order Implication:** Event sourcing is already implemented. Mobile clients need event replay for reconnection sync.

### Pattern 2: Heuristic Interjection (Dialectic Model)

**What:** LLM decides when to speak based on multiple signals: turn count, explicit mention, semantic novelty, stagnation detection.

**When:** LLM should feel like a participant, not a reactive assistant.

**Example (existing):**
```python
decision = self.heuristics.decide(
    messages=messages,
    mentioned=mentioned,
    semantic_novelty=semantic_novelty,
)
# Returns: InterjectionDecision(should_interject, reason, confidence, use_provoker)
```

**Build Order Implication:** This is working. Mobile clients just need to handle "llm_thinking" events.

### Pattern 3: Provider Fallback Chain (Dialectic Model)

**What:** Primary provider fails → retry with backoff → fallback to secondary provider.

**When:** LLM API availability is critical.

**Example (existing):**
```python
self.chain = [
    (primary_provider, primary_model),
    (fallback_provider, self._map_model(primary_model, fallback_provider)),
    (primary_provider, fallback_model),
]
```

**Build Order Implication:** Production-ready. No changes needed.

### Pattern 4: Connection Registry with Redis Pub/Sub (To Implement)

**What:** Replace in-memory connection dict with Redis-backed registry. Messages published to Redis, all server instances receive and forward.

**When:** Multiple server instances (horizontal scaling).

**Example (to implement):**
```python
class RedisConnectionManager:
    async def broadcast(self, room_id: UUID, message: OutboundMessage):
        # Publish to Redis channel
        await self.redis.publish(
            f"room:{room_id}",
            json.dumps(message.dict())
        )

    async def _subscribe_loop(self):
        # Each server instance subscribes
        async for message in self.pubsub.listen():
            room_id = message['channel'].decode().split(':')[1]
            # Forward to locally connected clients
            for conn in self._local_connections.get(room_id, []):
                await conn.websocket.send_text(message['data'])
```

**Build Order Implication:** Implement before deploying multiple server instances.

### Pattern 5: Mobile Offline Queue with Sequence Reconciliation

**What:** Queue messages locally when offline. On reconnect, send queued messages, reconcile with server-assigned sequences.

**When:** Mobile apps on unreliable networks.

**Example (mobile client side):**
```typescript
// On send while offline
if (!connected) {
  await localDb.insert('pending_messages', {
    tempId: uuid(),
    content: message.content,
    threadId: currentThread,
    queuedAt: Date.now()
  });
}

// On reconnect
const pending = await localDb.query('pending_messages ORDER BY queuedAt');
for (const msg of pending) {
  const response = await ws.sendAndWait('send_message', msg);
  await localDb.update('messages', {
    id: msg.tempId,
    serverId: response.id,
    sequence: response.sequence
  });
  await localDb.delete('pending_messages', msg.tempId);
}
```

**Build Order Implication:** Mobile client concern. Backend already supports REST fallback.

## Anti-Patterns to Avoid

### Anti-Pattern 1: Full Message Content in Push Notifications

**What:** Sending complete message content as push notification payload.

**Why bad:** Push delivery is not guaranteed. Payload-based delivery causes data loss and inconsistency. Also exposes content in notification previews.

**Instead:** Send only identifiers. Client fetches content on wake.
```json
// Bad
{"type": "new_message", "content": "The full message text here..."}

// Good
{"type": "new_message", "room_id": "abc", "message_id": "xyz"}
```

### Anti-Pattern 2: Immediate Reconnection on Failure

**What:** Reconnecting immediately after WebSocket closes, repeatedly.

**Why bad:** Drains battery. Overloads server during outages. Network doesn't have time to recover.

**Instead:** Exponential backoff with cap.
```typescript
const delays = [1000, 2000, 4000, 8000, 16000, 30000];
let attempt = 0;

function reconnect() {
  const delay = delays[Math.min(attempt++, delays.length - 1)];
  setTimeout(connect, delay);
}
```

### Anti-Pattern 3: Client-Side Last-Writer-Wins Without Server Arbitration

**What:** Multiple clients editing same data, client decides conflict resolution.

**Why bad:** No single source of truth. Divergent state across clients.

**Instead:** Server assigns sequence numbers. Client applies operations in server-determined order. For Dialectic (sequential messages), this is already handled. For shared memories, version numbers provide conflict detection.

### Anti-Pattern 4: Blocking on LLM Response Before UI Update

**What:** Client sends message, waits for LLM response before showing anything.

**Why bad:** LLM responses take 1-10 seconds. UI feels frozen.

**Instead:** Optimistic UI updates.
1. User sends message → immediately render with "sending" state
2. Server acknowledges → update to "sent"
3. LLM thinking event → show "Claude is thinking..."
4. LLM response → render LLM message

### Anti-Pattern 5: Single Database for All Data Types

**What:** Forcing relational or document model on everything.

**Why bad:** Different data has different access patterns. Event logs need append-only + temporal queries (PostgreSQL). Development sessions need flexible schema + text search (MongoDB). Embeddings need vector similarity (pgvector).

**Instead:** Polyglot persistence (already in place).
- PostgreSQL + pgvector for Dialectic
- MongoDB for Cairn sessions
- Redis for caching and pub/sub

## Scalability Considerations

| Concern | 10 users (MVP) | 1K users | 100K users |
|---------|----------------|----------|------------|
| **WebSocket connections** | Single server, in-memory registry | 2-3 servers, Redis pub/sub | Auto-scaling group, sticky sessions |
| **LLM rate limits** | Single provider | Provider fallback chain | Request queuing, priority tiers |
| **Database connections** | Single pool (10 conns) | Connection pooling (PgBouncer) | Read replicas, sharding by room |
| **Message history** | Load all | Pagination | Archive older messages, lazy load |
| **Embedding search** | pgvector | pgvector with IVF index | Dedicated vector DB (Pinecone) |
| **Mobile push** | Direct FCM/APNs | Message queue | Notification service (Courier) |

## Suggested Build Order

Based on dependencies and integration complexity:

### Phase 1: Foundation (Mobile + Backend Core)
**Build first because:** Everything depends on auth, basic connectivity.

1. **Shared Auth Service** - JWT-based, shared between Dialectic/Cairn
2. **Redis Integration for Dialectic** - Replace in-memory ConnectionManager
3. **Mobile Client Shell** - WebSocket connection, reconnection logic, basic UI
4. **REST Fallback Endpoints** - Mobile needs REST when WebSocket unavailable

### Phase 2: Core Collaboration
**Build second because:** Depends on Phase 1 infrastructure.

1. **Mobile Message UI** - Send/receive messages, typing indicators
2. **LLM Response Streaming** - Token-wise updates to mobile
3. **Offline Queue** - Local persistence, sync on reconnect
4. **Push Notification Integration** - FCM/APNs for backgrounded apps

### Phase 3: Advanced Features
**Build third because:** Requires stable core.

1. **Thread Forking in Mobile** - Fork UI, ancestry visualization
2. **Memory Management** - Add/edit/search shared memories
3. **Cairn Integration** - Development sessions linked to rooms
4. **Cross-Service Search** - Unified search across both backends

### Phase 4: Scale and Polish
**Build last because:** Optimization requires baseline.

1. **Horizontal Scaling** - Multiple Dialectic instances
2. **Message Archival** - Move old messages to cold storage
3. **Performance Optimization** - Caching, lazy loading
4. **Monitoring and Observability** - Metrics, tracing

## Research Flags for Phases

| Phase | Component | Research Needed | Reason |
|-------|-----------|-----------------|--------|
| 1 | Mobile WebSocket | LOW | Well-documented patterns |
| 1 | Redis Pub/Sub | LOW | Straightforward implementation |
| 2 | Token Streaming | MEDIUM | FastAPI streaming + mobile consumption |
| 2 | Push Notifications | MEDIUM | FCM/APNs integration varies by platform |
| 3 | Cairn Integration | LOW | Internal integration, known systems |
| 4 | Horizontal Scaling | MEDIUM | Load testing needed to validate |

## Sources

### Real-Time Collaboration
- [Building Real-Time Applications with WebSockets](https://render.com/articles/building-real-time-applications-with-websockets)
- [WebSockets Explained for Real-Time Web Applications](https://www.daydreamsoft.com/blog/websockets-explained-powering-real-time-web-applications)
- [Implement WebSocket in Android](https://www.videosdk.live/developer-hub/websocket/android-websocket)

### Mobile WebSocket Patterns
- [WebSocket Best Practices in React Native](https://medium.com/@tusharkumar27864/best-practices-of-using-websockets-real-time-communication-in-react-native-projects-89e749ba2e3f)
- [WebSocket Reconnection in Flutter](https://medium.com/@punithsuppar7795/websocket-reconnection-in-flutter-keep-your-real-time-app-alive-be289cff46b8)
- [React Native WebSocket Guide](https://www.videosdk.live/developer-hub/websocket/websocket-react-native)
- [Ably: WebSockets React Native Challenges](https://ably.com/topic/websockets-react-native)

### LLM Orchestration
- [LLM Orchestration 2026 Frameworks](https://research.aimultiple.com/llm-orchestration/)
- [LangGraph](https://www.langchain.com/langgraph)
- [LLM Orchestration Best Practices](https://orq.ai/blog/llm-orchestration)

### Scaling and Architecture
- [Scaling WebSockets with Redis Pub/Sub](https://medium.com/@nandagopal05/scaling-websockets-with-pub-sub-using-python-redis-fastapi-b16392ffe291)
- [Scalable FastAPI WebSocket with Redis](https://www.fastapitutorial.com/blog/scalable-fastapi-redis-websocket/)
- [How to Scale FastAPI WebSocket Servers](https://hexshift.medium.com/how-to-scale-fastapi-websocket-servers-without-losing-state-6462b43c638c)

### Push Notifications
- [Push Notifications vs WebSockets](https://www.curiosum.com/blog/mobile-push-notifications-description-and-comparison-with-web-sockets)
- [Push Notifications in Chat Apps](https://connectycube.com/2025/12/18/push-notifications-in-chat-apps-best-practices-for-android-ios/)
- [MigratoryData Fallback to Push](https://migratorydata.com/blog/migratorydata-fallback-to-firebase-push-notifications/)

### OT/CRDT Comparison
- [OT vs CRDT for Real-Time Collaboration](https://www.tiny.cloud/blog/real-time-collaboration-ot-vs-crdt/)
- [CRDTs vs OT Practical Guide](https://hackernoon.com/crdts-vs-operational-transformation-a-practical-guide-to-real-time-collaboration)

### API Gateway and Federation
- [API Gateway Pattern](https://microservices.io/patterns/apigateway.html)
- [GraphQL Federation](https://graphql.org/learn/federation/)
