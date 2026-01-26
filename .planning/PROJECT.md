# Dialectic

## What This Is

A cross-platform mobile collaborative workspace where two humans and an LLM co-create together in real-time. The LLM isn't an assistant you query — it's a participant that interjects proactively based on configurable heuristics. Built for iOS and Android with React Native/Expo (v1.0), with desktop expansion in progress (v1.1).

## Core Value

Real-time collaborative creation with an LLM as a first-class participant, not a request-response tool.

## Requirements

### Validated

- ✓ Real-time WebSocket infrastructure (from existing Dialectic backend) — v1.0
- ✓ LLM orchestration with Anthropic/OpenAI (from existing Dialectic backend) — v1.0
- ✓ Real-time conversation between 3 parties (2 humans + 1 LLM) — v1.0
- ✓ Cross-platform mobile clients (iOS, Android) — v1.0
- ✓ Push notifications when participants are away — v1.0
- ✓ User authentication and session management (JWT, biometric unlock) — v1.0
- ✓ Persistent session history with search — v1.0
- ✓ Thread forking and genealogy visualization — v1.0
- ✓ Configurable LLM heuristic interjection — v1.0

### Active

- [ ] Desktop clients (macOS, Windows) — v1.1 in progress (Phase 8)
- [ ] Cross-referenced conversations across sessions — deferred

### Out of Scope (v2+)

- Collaborative document editing with semantic versioning — deferred to v2
- Collaborative code editor with real-time cursors — deferred to v2
- LLM-driven code generation in shared editor — deferred to v2
- Multi-tenant/multi-group support — architected for, not built in v1
- Offline mode — network required for v1
- Web app — native cross-platform clients only for v1

## Context

**Shipped v1.0 with ~9,975 LOC TypeScript (React Native/Expo).**

Tech stack:
- **Frontend**: React Native with Expo SDK 54, TypeScript
- **State**: Zustand + MMKV for persistence
- **Database**: expo-sqlite with Drizzle ORM, FTS5 for search
- **Networking**: WebSocket with reconnection, offline queue
- **Backend**: FastAPI (Dialectic), PostgreSQL + pgvector

**Existing codebases leveraged:**
- **Dialectic** (`/root/DwoodAmo/dialectic/`): FastAPI backend with WebSocket handling, LLM orchestration (Anthropic/OpenAI), heuristic interjection engine, thread forking, vector memory with pgvector.
- **Cairn** (`/root/cairn/`): Session logging system reference (MongoDB patterns adapted to PostgreSQL).

**Target users:** Two developers (the builder and friend) — one on iOS/Mac, one on Android/Windows.

**Long-term vision:** A product to develop, distribute, and run commercially.

## Constraints

- **Platforms**: iOS, Android shipped (v1.0); macOS, Windows in progress (v1.1)
- **Users**: Two users initially (different platforms), but architecture supports multi-tenancy
- **Backend**: Leveraging existing Dialectic real-time infrastructure
- **LLM**: Anthropic primary, OpenAI fallback

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| React Native with Expo | Cross-platform from single codebase, strong ecosystem | ✓ Good — shipped v1.0 |
| Build on Dialectic backend | Has WebSocket real-time, LLM orchestration already built | ✓ Good — reused infrastructure |
| Expo SDK 54 over SDK 52 | Latest stable, better tooling | ✓ Good — no issues |
| expo-sqlite + Drizzle ORM | Type-safe local database with FTS5 | ✓ Good — fast local search |
| MMKV for session persistence | 30-100x faster than AsyncStorage | ✓ Good — instant state restore |
| FlashList for message lists | Virtualization for large conversations | ✓ Good — smooth scrolling |
| Indigo (#6366f1) for Claude | Consistent brand color across LLM UI | ✓ Good — clear visual identity |
| 6-digit PIN/verification codes | Matches TOTP standard, more secure | ✓ Good — familiar pattern |
| Heuristic presets (quiet/balanced/active) | Simplify LLM behavior config | ✓ Good — user-friendly |

---
*Last updated: 2026-01-26 after v1.0 milestone*
