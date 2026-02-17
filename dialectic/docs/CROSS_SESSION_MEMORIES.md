# Cross-Session Memory References

## Overview

This feature enables memories and insights from one room/session to be referenced 
in another, creating a persistent knowledge graph across all conversations.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         User's Memory Graph                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   ┌──────────────┐     ┌──────────────┐     ┌──────────────┐   │
│   │   Room A     │     │   Room B     │     │   Room C     │   │
│   │  (Philosophy)│     │  (Science)   │     │  (Politics)  │   │
│   │              │     │              │     │              │   │
│   │  Memory A1 ──┼─────┼──> Ref ──────┼─────┼──> Ref       │   │
│   │  Memory A2   │     │  Memory B1   │     │  Memory C1   │   │
│   │              │     │  Memory B2 ──┼─────┼──> Ref       │   │
│   └──────────────┘     └──────────────┘     └──────────────┘   │
│                                                                  │
│   ┌──────────────────────────────────────────────────────────┐  │
│   │            User Collections (Auto-Inject)                 │  │
│   │  ┌─────────────────┐  ┌──────────────────────┐           │  │
│   │  │ Core Beliefs    │  │ Definitions          │           │  │
│   │  │  - Memory A1    │  │  - Memory from B     │           │  │
│   │  │  - Memory C1    │  │  - Memory from A     │           │  │
│   │  └─────────────────┘  └──────────────────────┘           │  │
│   └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

## Key Concepts

### 1. Memory Scopes

- **ROOM** (default): Memory visible only in the originating room
- **USER**: Memory visible only to the owner user
- **GLOBAL**: Memory visible across all rooms the user participates in

### 2. Memory References (Citations)

When a memory from Room A is relevant to a discussion in Room B, a reference 
can be created. This:
- Links the source memory to the target context
- Records who/what created the reference (user or LLM)
- Tracks relevance score for auto-suggested references

### 3. User Collections

Users can organize memories into named collections:
- Collections span all rooms
- Can be set to "auto-inject" into all LLM contexts
- Useful for core beliefs, definitions, personal axioms

## API Endpoints

### REST API (`/cross-session/`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/search` | Search all user's memories across rooms |
| GET | `/rooms/{room_id}/relevant-memories` | Get relevant cross-room memories |
| POST | `/memories/{memory_id}/promote` | Promote to global scope |
| POST | `/rooms/{room_id}/references` | Create memory reference |
| GET | `/collections` | List user's collections |
| POST | `/collections` | Create new collection |

### WebSocket Messages

**Inbound:**
- `search_global_memories` - Search across rooms
- `promote_memory` - Promote to global scope
- `reference_memory` - Create citation

**Outbound:**
- `global_memory_results` - Search results
- `memory_promoted` - Promotion confirmation
- `memory_referenced` - Citation confirmation
- `cross_room_context` - Auto-suggested memories

## Migration

```bash
psql dialectic < migrations/cross_session_memories.sql
```

## Files Added

- `migrations/cross_session_memories.sql` - Database schema
- `memory/cross_session.py` - Core manager (492 lines)
- `api/cross_session_routes.py` - REST endpoints (350 lines)
- `llm/cross_session_context.py` - LLM context builder (145 lines)
- `transport/cross_session_handlers.py` - WebSocket handlers (235 lines)
