# Dialectic

## What This Is

A collaborative workspace where two humans and an LLM co-create together in real-time. The LLM isn't an assistant you query — it's a participant in both conversation and creation. Built for iOS, Android, macOS, and Windows via React Native or Flutter.

## Core Value

Real-time collaborative creation with an LLM as a first-class participant, not a request-response tool.

## Requirements

### Validated

- Real-time WebSocket infrastructure (from existing Dialectic backend)
- LLM orchestration with Anthropic/OpenAI (from existing Dialectic backend)
- Session persistence model (from existing Cairn backend)
- Search and indexing infrastructure (from existing Cairn backend)

### Active

- [ ] Real-time conversation between 3 parties (2 humans + 1 LLM)
- [ ] Cross-platform mobile/desktop clients (React Native or Flutter)
- [ ] Push notifications when participants are away
- [ ] User authentication and session management
- [ ] Persistent session history with indexing by topic/date
- [ ] Cross-referenced conversations across sessions

### Out of Scope (v1)

- Collaborative document editing with semantic versioning — deferred to v2
- Collaborative code editor with real-time cursors — deferred to v2
- LLM-driven code generation in shared editor — deferred to v2
- Multi-tenant/multi-group support — architected for, not built in v1
- Offline mode — network required for v1

## Context

**Existing codebases:**
- **Dialectic** (`/root/DwoodAmo/dialectic/`): FastAPI backend with WebSocket handling, LLM orchestration (Anthropic/OpenAI), heuristic interjection engine, thread forking, vector memory with pgvector. Untested but substantial.
- **Cairn** (`/root/cairn/`): Session logging system with MongoDB + Redis, AI-powered summarization, search with relevance scoring, Vue frontend, CLI. 276 tests passing, well-documented.

**Target users:** Initially two developers (the builder and their friend) — one on iOS/Mac, one on Android/Windows.

**Long-term vision:** A product to develop, distribute, and run commercially.

**Technical environment:** DigitalOcean droplet, PostgreSQL (Dialectic) + MongoDB (Cairn), Redis available.

## Constraints

- **Platforms**: Must work on iOS, Android, macOS, Windows — drives React Native or Flutter choice
- **Users**: Two users initially (different platforms), but architecture should support multi-tenancy
- **Backend**: Leverage existing Dialectic real-time infrastructure, integrate Cairn persistence model
- **LLM**: Anthropic primary, OpenAI fallback (already implemented in Dialectic)

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| React Native or Flutter for clients | Cross-platform from single codebase, user wants to learn | — Pending |
| Build on Dialectic backend | Has WebSocket real-time, LLM orchestration already built | — Pending |
| Integrate Cairn persistence model | Has session structure, search, indexing already built | — Pending |
| PostgreSQL + pgvector for persistence | Dialectic already uses it, vector search for semantic memory | — Pending |

---
*Last updated: 2026-01-20 after initialization*
