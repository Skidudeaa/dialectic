# Project State

## Project Reference

See: .planning/PROJECT.md
See: .planning/VISION-NEXT.md (strategic vision)
See: .planning/NEXT-LEVEL-ROADMAP.md (execution plan)

**Core value:** Real-time collaborative creation with an LLM as a first-class participant
**Current focus:** v2.0 Hardening + Vision — Security fixes, schema gaps, then vision features

## Current Position

Phase: Post v1.1, pre-v2.0
Plan: Deep audit complete (4-agent analysis, 2026-02-20). Executing Category 1 fixes.
Status: Fixing critical security + bugs before building vision features
Last activity: 2026-02-20 — Full codebase audit (frontend, backend, LLM, vision gap analysis)

Progress: v1.0 [██████████] 100%  |  v1.1 [█████████░] 90%  |  v2.0 [░░░░░░░░░░] 0%

## Milestone Status

**v1.0 Mobile MVP:** ✅ SHIPPED 2026-01-25
- Phases 1-7 complete (35 plans)
- See: `.planning/MILESTONES.md`

**v1.1 Desktop:** 🚧 CODE COMPLETE
- Phase 8 code complete (9/9 plans)
- Verification pending on actual macOS/Windows machines
- See: `.planning/ROADMAP.md`

**v2.0 Hardening + Vision:** 🚧 IN PROGRESS
- Deep audit complete (2026-02-20)
- Category 1 executing: security fixes, critical bugs, schema gaps
- Category 2 planned: foundation upgrades (testing, packaging, frontend architecture)
- Category 3 planned: vision features (analytics, self-memory, protocols, identity)
- See: `.planning/NEXT-LEVEL-ROADMAP.md`

## Audit Findings (2026-02-20)

### Critical Security Issues
- REST endpoints accept `user_id` as unauthenticated query param (impersonation)
- No rate limiting on auth endpoints (code exists, never wired)
- Verification/reset codes logged in plaintext
- `python-multipart==0.0.6` has CVE-2024-53498
- Room tokens exposed in URL query params

### Critical Bugs
- Schema gap: `memory_references`, `user_memory_collections`, `collection_memories` tables missing from schema.sql (migration exists but never applied)
- Streaming bypasses retry/fallback router (unrecoverable failures)
- Context truncation only on streaming path, not on_message/force_response
- CrossSessionContextBuilder fully built but never wired to orchestrator
- httpx client leak in streaming path
- datetime.utcnow() in multiple files (deprecated, TIMESTAMPTZ mismatch)

### Architecture Assessment
- Backend: Event-sourced layered monolith — strong foundation, ~40% of vision surface area built
- Frontend: 2,897-line monolithic HTML — polished but cannot support vision features
- LLM layer: Extensible prompt system, clean provider abstraction, but heuristics limited
- Memory: Cross-session system fully coded but disconnected from live path

## Accumulated Context

### Key Decisions

**v2.0 Architecture:**
- Fix security and schema gaps before any new features
- Apply cross-session migration to schema.sql (unblocks 4+ features)
- Wire CrossSessionContextBuilder into live LLM path
- Frontend migration to component framework needed for vision features (decision pending)

### Documents Inventory

**Active planning docs:**
- `.planning/VISION-NEXT.md` — 5 strategic directions
- `.planning/technical-opportunities.md` — 7 technical capabilities
- `.planning/NEXT-LEVEL-ROADMAP.md` — Prioritized execution plan
- `dialectic/docs/VISION.md` — Product vision + pitch
- `dialectic/TODOS.md` — Current issue tracker
- `dialectic/CHANGELOG.md` — Release history

**Reference docs:**
- `.planning/codebase/` — Architecture, stack, conventions, concerns, testing, integrations, structure
- `.planning/research/` — Pre-build analysis (architecture, stack, features, pitfalls, summary)
- `.planning/phases/01-08/` — Completed phase documentation (126 files)
- `dialectic/docs/CROSS_SESSION_MEMORIES.md` — Cross-session feature spec

## Session Continuity

Last session: 2026-02-20
Stopped at: Category 1 execution (security fixes + schema gaps)
Resume file: None

---
*State initialized: 2026-01-20*
*Last updated: 2026-02-20 (deep audit complete, Category 1 executing)*
