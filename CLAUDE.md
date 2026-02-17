# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Dialectic** is a collaborative dialogue engine where two humans and an LLM co-reason together in real-time. The LLM acts as a participant (not an assistant)—it challenges, synthesizes, and provokes rather than simply responding to requests.

## Commands

```bash
# Run the server on port 8002 (port 8000 is reserved for another app)
PORT=8002 python dialectic/run.py

# Serve the frontend
python -m http.server 3000 --directory dialectic/frontend

# Database setup
createdb dialectic
psql dialectic < dialectic/schema.sql
```

## Required Environment Variables

```bash
export DATABASE_URL="postgresql://localhost/dialectic"
export ANTHROPIC_API_KEY="sk-ant-..."
export OPENAI_API_KEY="sk-..."  # Optional, enables fallback + embeddings
```

## Architecture

### Core Modules (`dialectic/`)

| Module | Purpose |
|--------|---------|
| `api/main.py` | FastAPI server, REST endpoints, WebSocket handler |
| `llm/` | LLM orchestration layer |
| `memory/` | Vector search + versioned shared memories |
| `transport/` | WebSocket connection management + message dispatch |
| `models.py` | Pydantic models, enums, event payloads |
| `operations.py` | Fork thread, ancestry queries |

### LLM Layer (`llm/`)

- **orchestrator.py**: Central coordinator for all LLM interactions
- **providers.py**: Anthropic + OpenAI abstraction with httpx
- **router.py**: Retry logic with exponential backoff, provider fallback chain
- **heuristics.py**: Interjection decision engine—determines when/how LLM speaks
- **prompts.py**: Layered prompt assembly (identity + room rules + user modifiers + memories)

### Key Design Patterns

1. **Event Sourcing**: All state changes recorded in `events` table (append-only), enabling replay and temporal queries
2. **Heuristic Interjection**: LLM decides when to speak based on turn count (4+), questions, semantic novelty, or stagnation
3. **Two LLM Modes**: "primary" (equal participant) vs "provoker" (destabilizer for stale conversations)
4. **Fork Genealogy**: Threads can fork from any message; child threads inherit ancestor messages up to fork point
5. **Vector Memory**: pgvector for semantic search over shared memories (1536-dim OpenAI embeddings)

### WebSocket Message Types

Messages sent to `/ws/{room_id}`:
- `send_message` - Human message
- `fork_thread` - Create branch from message
- `add_memory` / `edit_memory` / `invalidate_memory` - Shared memory operations

### Database Schema

PostgreSQL with pgvector extension. Key tables:
- `events` - Append-only event log (source of truth)
- `rooms` - Conversation spaces with LLM settings
- `threads` - Conversation branches (supports forking via `parent_thread_id`)
- `messages` - Sequential messages with `speaker_type` (HUMAN, LLM_PRIMARY, LLM_PROVOKER)
- `memories` - Versioned shared knowledge with embeddings

## Code Style

All modules use ARCHITECTURE/WHY/TRADEOFF comments to document design decisions:

```python
class InterjectionEngine:
    """
    ARCHITECTURE: Rule-based + heuristic interjection triggers.
    WHY: LLM should feel like a participant, not a reactive tool.
    TRADEOFF: False positives (annoying) vs false negatives (silent).
    """
```

## Scaling Notes

Current implementation uses in-memory connection registry—single-server only. Redis pub/sub planned for horizontal scaling.
