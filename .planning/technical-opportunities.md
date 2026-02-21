# Technical Opportunities: Capabilities That Unlock New Experiences

**Author:** Technical Architect
**Date:** 2026-02-14
**Scope:** Deep analysis of the Dialectic backend, identifying capabilities the current architecture makes uniquely possible and what new primitives would unlock genuinely new product surfaces.

---

## Executive Summary

Dialectic's architecture is more powerful than its current feature set exploits. The combination of append-only event sourcing, pgvector semantic memory, thread forking with ancestry traversal, and cross-session memory references creates a substrate for capabilities that most dialogue systems cannot achieve. This document identifies seven technical opportunity areas, ordered by architectural leverage (what the existing code most naturally enables) rather than by implementation effort.

---

## 1. CONVERSATION TIME TRAVEL (Event Replay Engine)

### What exists now
- `events` table: append-only, `BIGSERIAL` sequenced, JSONB payload (`schema.sql:7-16`)
- Event types cover the full state lifecycle: room/thread creation, message CRUD, memory add/edit/invalidate, forking, settings changes (`models.py:31-49`)
- `get_events` REST endpoint already exposes events with cursor-based pagination and type filtering (`api/main.py:1459-1495`)
- Thread forking records `fork_memory_version` at fork time (`operations.py:23-26`), creating a snapshot of memory state

### What this unlocks
**Temporal state reconstruction.** The event log is already a complete audit trail. A replay engine would materialize room state at any point in time by replaying events up to a target sequence number. This is not a theoretical capability -- the data model was designed for it.

Concrete applications:
- **"What if" branching from the past**: Fork a thread from message N, but also restore the memory state to what it was at message N. The `fork_memory_version` field on threads already anticipates this, but the memory replay is not implemented.
- **Conversation archaeology**: Visualize how a shared memory evolved over time by replaying `MEMORY_ADDED -> MEMORY_EDITED -> MEMORY_EDITED -> MEMORY_INVALIDATED` event chains. The `memory_versions` table already stores every version.
- **LLM decision replay**: Every LLM response stores `prompt_hash` and `model_used` (`messages` table). Combined with event replay, you could reconstruct what the LLM "saw" at any decision point, then ask "what would Claude have said if we'd used Opus instead of Sonnet?"

### Implementation sketch
```python
class EventReplayEngine:
    """Materializes room state at any event sequence."""

    async def state_at(self, room_id: UUID, target_sequence: int) -> RoomSnapshot:
        events = await self.db.fetch(
            "SELECT * FROM events WHERE room_id = $1 AND sequence <= $2 ORDER BY sequence",
            room_id, target_sequence
        )
        # Apply events to build state
        state = RoomSnapshot.empty(room_id)
        for event in events:
            state = state.apply(EventType(event['event_type']), event['payload'])
        return state
```

### Architectural fit: **Perfect.** This is what event sourcing is for.

---

## 2. PERSISTENT EVOLVING LLM IDENTITY (LLM Self-Memory)

### What exists now
- Prompt assembly in `prompts.py` has a fixed `BASE_IDENTITY` and `PROVOKER_IDENTITY` (`prompts.py:34-58`)
- Memory system gives the LLM access to shared room memories (`prompts.py:92`)
- Cross-session context already injects memories from other rooms (`prompts.py:83-84, cross_session_context.py`)
- The LLM's own messages are stored with `speaker_type=LLM_PRIMARY/LLM_PROVOKER` and `model_used`

### What's missing
The LLM has no memory of its own positions. It can see the conversation history within a context window, but it has no persistent record of: what positions it took, what it was wrong about, what arguments convinced it to change its mind, or how its thinking has evolved.

### What this unlocks
**LLM self-memory.** After each response, extract and store the LLM's epistemic state:
- Key claims it made (already classified by `_detect_message_type` in `orchestrator.py:383-396`)
- Position changes ("I was wrong about X because Y")
- Recurring themes across rooms (via cross-session memory)

This creates an LLM that genuinely evolves. Not through fine-tuning, but through structured memory that persists across context windows and sessions. The `MemoryScope.GLOBAL` scope already exists for this -- add an `LLM` scope.

### Implementation approach
```python
class LLMSelfMemory:
    """Extracts and stores LLM's evolving epistemic state."""

    async def post_response_extraction(self, response: Message, context: list[Message]):
        """Run after each LLM response to extract positions."""
        # Use a cheap model (Haiku) to extract: claims, questions, position changes
        extraction = await self.extract_positions(response.content, context)

        for claim in extraction.claims:
            await self.memory_manager.add_memory(
                room_id=response.thread_id,  # or global
                key=f"llm_position:{claim.topic}",
                content=claim.position,
                scope=MemoryScope.GLOBAL,  # Persists across rooms
                created_by_user_id=None,  # LLM-authored
            )
```

The prompt builder already has the `memory_context` injection point. LLM self-memories would appear in the "Shared Memory" section, making the LLM aware of its own prior positions.

### Architectural fit: **Strong.** The memory system (scoping, versioning, cross-session) already supports this; the main addition is automated extraction after LLM responses.

---

## 3. MULTI-MODEL ROOMS (Adversarial Dialogue Between LLMs)

### What exists now
- `providers.py` abstracts Anthropic and OpenAI behind a uniform `LLMProvider` interface
- `router.py` already chains providers: primary -> fallback -> secondary model
- Room model has `primary_provider`, `fallback_provider`, `primary_model`, `provoker_model` (`models.py:74-77`)
- `SpeakerType` already distinguishes `LLM_PRIMARY` from `LLM_PROVOKER` (`models.py:24-27`)
- Prompts have separate `BASE_IDENTITY` and `PROVOKER_IDENTITY` templates

### What this unlocks
The two-persona system (primary + provoker) is the seed of a multi-model room. The architecture already routes different speaker types to different models. Extending this to N named LLM participants requires:

1. **Named LLM personas** stored in a `room_personas` table, each with: model, provider, identity prompt, personality parameters, and a trigger strategy (when does this persona speak?)
2. **Inter-LLM dialogue**: When one LLM speaks, other LLM personas can be triggered to respond (the heuristic engine already evaluates "should I speak?" -- parameterize it per persona)
3. **Model diversity**: Run Claude Opus as the deep thinker, Haiku as the provocateur, GPT-4o as the devil's advocate. Each sees the same conversation but through different system prompts.

The provider abstraction is already model-agnostic. The main work is making `InterjectionEngine` and `PromptBuilder` persona-aware, and adding a turn-taking protocol so LLMs don't endlessly respond to each other.

### Turn-taking protocol
```python
class MultiModelCoordinator:
    """Manages turn-taking between multiple LLM personas."""

    MAX_LLM_CONSECUTIVE = 2  # Max LLM turns before requiring human input
    COOLDOWN_SECONDS = 30    # Minimum time between same persona's responses

    async def should_persona_speak(self, persona_id, messages, all_personas):
        # Count consecutive LLM turns
        consecutive = 0
        for msg in reversed(messages):
            if msg.speaker_type == SpeakerType.HUMAN:
                break
            consecutive += 1
        if consecutive >= self.MAX_LLM_CONSECUTIVE:
            return False
        # Per-persona heuristics
        return await persona.heuristics.decide(messages)
```

### Architectural fit: **Good.** The dual-persona system is already 60% of the way there. Main extension is parameterizing identities and adding turn coordination.

---

## 4. KNOWLEDGE GRAPH FROM EVENT SOURCING + MEMORIES

### What exists now
- Memories with semantic embeddings (1536-dim, pgvector cosine search: `vector_store.py`)
- Cross-room memory references with `MemoryReference` model (`models.py:208-223`)
- Memory collections that span rooms (`UserMemoryCollection`, `CollectionMembership`: `models.py:226-247`)
- Citation tracking: `referenced_by_user_id`, `referenced_by_llm`, `citation_context`, `relevance_score`
- Cross-session search across all user rooms (`cross_session.py:68-130`)

### What this unlocks
The pieces of a knowledge graph are scattered across the codebase. Assembling them creates something powerful:

**Nodes**: Memories (with embeddings for similarity), Messages (with type classification), Users, Rooms, Threads
**Edges**: Memory references (cross-room citations), thread fork genealogy (parent_thread_id chains), message references (references_message_id), memory versioning (edit chains), user contributions (who created/edited memories)

This is not a hypothetical -- the data already exists. What's missing is a **graph query layer** that traverses these relationships.

Applications:
- **Concept maps**: "Show me everything we've discussed about consciousness across all my rooms" -- semantic search over memories, grouped by room, with citation links between them
- **Idea provenance**: Trace a memory back through its version history, through the message that spawned it, through the thread fork that created the context, to the original conversation
- **Contribution graphs**: Which participants introduced ideas that became shared memories? Which memories get cited most across rooms?

### Implementation: Graph materialization
```sql
-- Materialized view: knowledge graph edges
CREATE MATERIALIZED VIEW knowledge_graph AS
SELECT
    'memory_reference' as edge_type,
    source_memory_id as source_id,
    'memory' as source_type,
    target_message_id as target_id,
    'message' as target_type,
    relevance_score as weight
FROM memory_references
UNION ALL
SELECT
    'thread_fork' as edge_type,
    parent_thread_id as source_id,
    'thread' as source_type,
    id as target_id,
    'thread' as target_type,
    1.0 as weight
FROM threads WHERE parent_thread_id IS NOT NULL
UNION ALL
SELECT
    'message_reference' as edge_type,
    references_message_id as source_id,
    'message' as source_type,
    id as target_id,
    'message' as target_type,
    1.0 as weight
FROM messages WHERE references_message_id IS NOT NULL;
```

Combined with pgvector's similarity search, this enables "find me everything related to X" queries that traverse both semantic similarity and explicit structural relationships.

### Architectural fit: **Excellent.** The data model already encodes graph relationships. This is about surfacing them.

---

## 5. REAL-TIME TYPING ANALYSIS (React Before Send)

### What exists now
- WebSocket handlers for `TYPING_START` and `TYPING_STOP` (`handlers.py:59`)
- Typing indicators are broadcast to the room (`handlers.py:339-349`)
- The connection is bidirectional and low-latency

### What this unlocks
Currently typing indicators are binary (typing/not typing). The WebSocket connection could carry the actual typed content before it's sent. This enables:

1. **Predictive interjection**: The LLM begins formulating a response as the user types, reducing perceived latency. When the message is finally sent, the LLM response appears almost instantly.
2. **Clarification prompts**: If the LLM detects ambiguity in what's being typed, it could surface a "Did you mean...?" before the user sends.
3. **Real-time semantic novelty**: Compute `compute_message_novelty` on typing content in real-time to prepare the interjection engine.

### Privacy considerations
This must be opt-in and clearly communicated. The typing content should never be persisted -- only used for real-time pre-computation.

### Implementation
```python
# New message type
MessageTypes.TYPING_CONTENT = "typing_content"

async def _handle_typing_content(self, conn: Connection, payload: dict):
    """Pre-process content as user types."""
    partial_content = payload.get("content", "")

    # Debounce: only process every 500ms
    # Pre-compute novelty score
    novelty = await self.memory.compute_message_novelty(conn.room_id, partial_content)

    # If novelty is very high, start pre-fetching LLM context
    if novelty > 0.8:
        asyncio.create_task(self._prefetch_llm_context(conn.room_id, conn.thread_id))
```

### Architectural fit: **Good.** The WebSocket transport layer already handles typing events. This extends the protocol without changing the architecture.

---

## 6. CONVERSATION ANALYTICS AND PATTERN DETECTION

### What exists now
- Full-text search with tsvector ranking (`schema.sql:209-234`, `api/main.py:1081-1158`)
- Message type classification: TEXT, CLAIM, QUESTION, DEFINITION, COUNTEREXAMPLE (`models.py:14-21`)
- Semantic novelty computation (`memory/vector_store.py:92-114`)
- Event log with complete lifecycle tracking
- Token counts stored per LLM message (`messages.token_count`)

### What this unlocks
The raw material for conversation analytics is already being collected. What's missing is the analysis layer:

**Per-conversation metrics:**
- Argument density: ratio of CLAIM/COUNTEREXAMPLE messages to TEXT messages
- Question resolution rate: questions followed by substantive responses vs. ignored
- Semantic trajectory: embedding distance between first and last N messages (how far did the conversation travel?)
- Turn balance: ratio of human turns to LLM turns, per participant
- Stagnation events: how often did the provoker fire? (tracked via `InterjectionDecision.use_provoker`)

**Cross-conversation metrics:**
- Topic recurrence: semantic similarity between rooms, identifying recurring themes
- Memory network centrality: which memories are cited across the most rooms?
- User contribution patterns: who creates memories that stick?

**Pattern detection (via event stream):**
```python
class ConversationAnalyzer:
    """Computes conversation metrics from event stream."""

    async def analyze_thread(self, thread_id: UUID) -> ThreadAnalytics:
        events = await self.db.fetch(
            "SELECT * FROM events WHERE thread_id = $1 ORDER BY sequence", thread_id
        )

        metrics = ThreadAnalytics()
        for event in events:
            if event['event_type'] == 'message_created':
                payload = event['payload']
                metrics.update_speaker_stats(payload['speaker_type'])
                metrics.update_message_type_stats(payload['message_type'])
            elif event['event_type'] == 'memory_added':
                metrics.memory_crystallizations += 1
            elif event['event_type'] == 'thread_forked':
                metrics.fork_count += 1

        return metrics
```

### Architectural fit: **Excellent.** The event sourcing pattern was designed for exactly this kind of derived computation.

---

## 7. HORIZONTAL SCALING: REDIS PUB/SUB FOR MULTI-SERVER

### What exists now
- In-memory `ConnectionManager` with per-room broadcast (`transport/websocket.py`, `handlers.py:36-37`)
- Class-level `_active_streams` dict for LLM cancellation tracking (`handlers.py:37`)
- In-memory `RateLimiter` (`api/main.py:45-68`)
- The code explicitly acknowledges this limitation: "Class-level dict works for single-server; Redis needed for scale" (`handlers.py:726`)

### What this unlocks
Every distributed capability requires multi-server communication. Without this:
- No horizontal scaling
- No failover (single point of failure)
- No geographic distribution (all users hit one server)

The current architecture cleanly separates transport (WebSocket management) from business logic (message handlers). This makes the Redis migration straightforward:

```python
class RedisConnectionManager(ConnectionManager):
    """Drop-in replacement that uses Redis pub/sub for cross-server broadcast."""

    async def broadcast(self, room_id: UUID, message: OutboundMessage, **kwargs):
        # Publish to Redis channel instead of iterating local connections
        await self.redis.publish(
            f"room:{room_id}",
            message.to_json()
        )

    # Each server subscribes to channels for rooms it has connections to
    async def _subscribe_to_room(self, room_id: UUID):
        channel = self.redis.subscribe(f"room:{room_id}")
        async for message in channel:
            await self._deliver_to_local_connections(room_id, message)
```

This is infrastructure, not product -- but it's the prerequisite for everything else at scale.

### Architectural fit: **Designed for this.** The clean transport abstraction makes it a drop-in replacement.

---

## Priority Matrix

| Opportunity | Architectural Leverage | New Product Surface | Implementation Effort |
|---|---|---|---|
| 1. Event Replay / Time Travel | Exploits existing event sourcing | High: "what-if" exploration | Medium |
| 2. LLM Self-Memory | Extends existing memory system | Very High: evolving AI identity | Medium |
| 3. Multi-Model Rooms | Extends existing dual-persona | High: model debates | Medium |
| 4. Knowledge Graph | Surfaces existing relationships | High: cross-room insight | Medium-Low |
| 5. Real-Time Typing Analysis | Extends existing WebSocket | Medium: reduced latency | Low |
| 6. Conversation Analytics | Consumes existing event stream | Medium: insight layer | Low-Medium |
| 7. Redis Pub/Sub | Replaces in-memory transport | Prerequisite for scale | Medium |

---

## What Makes Dialectic's Architecture Uniquely Positioned

Most chat applications store messages in a table. Dialectic stores *events* in an append-only log with JSONB payloads, and derives messages as a view of that log. This is not just an architectural choice -- it is a fundamental capability difference:

1. **No other chat app can replay its own history** to a consistent state at an arbitrary point in time.
2. **No other chat app has thread forking with ancestry traversal** -- the recursive CTE in `get_thread_messages` that walks the parent chain is a unique primitive.
3. **No other chat app has semantic memory with versioning and cross-room references** -- the `memory_versions` + `memory_references` + `pgvector` combination is a knowledge graph in disguise.
4. **No other chat app stores LLM decision traces** (prompt_hash, model_used, token_count, interjection_reason) alongside the output, making every AI contribution auditable and replayable.

The opportunities above are not feature requests bolted onto a chat app. They are capabilities that emerge naturally from the architectural decisions already made. The question is not "can the system do this?" but "what new experiences become possible when we surface what the system already knows?"
