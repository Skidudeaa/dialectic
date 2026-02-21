# Next-Level Roadmap: Dialectic v2.0

**Created:** 2026-02-20
**Source:** 4-agent deep audit (frontend, backend, LLM architecture, vision gap analysis)

---

## Assessment Summary

The architecture is genuinely strong — event sourcing, pgvector memory, cross-session references, dual-LLM modes, and thread forking are real foundations. The codebase is at ~40% of the VISION-NEXT surface area, and it's the right 40%: foundational infrastructure, not surface features.

Three categories of work stand between current state and "next level."

---

## Category 1: Fix What's Broken (Do First)

### Critical Security (days)

| Issue | Severity | Fix | Files |
|-------|----------|-----|-------|
| REST endpoints accept `user_id` as unauth query param | CRITICAL | Validate user_id matches JWT caller | `api/main.py` all endpoints |
| No rate limiting on auth endpoints | HIGH | Wire existing `check_rate_limit` to routes | `api/main.py`, `api/auth/routes.py` |
| Verification/reset codes logged in plaintext | HIGH | Remove from log output | `api/auth/routes.py:133,377` |
| `python-multipart==0.0.6` CVE-2024-53498 | HIGH | Update to 0.0.12+ | `requirements.txt` |
| Room tokens in URL query params | HIGH | Move to Authorization header | Multiple endpoints |

### Critical Bugs (days)

| Issue | Impact | Fix | Files |
|-------|--------|-----|-------|
| Schema gap: 3 cross-session tables missing | Blocks 4+ vision features | Apply `migrations/cross_session_memories.sql` to schema.sql | `schema.sql` |
| Streaming bypasses retry/fallback router | Broken resilience | Route streaming through ModelRouter | `llm/orchestrator.py` |
| Context truncation only on streaming | Token overflow risk | Apply `assemble_context()` in all paths | `llm/orchestrator.py` |
| CrossSessionContextBuilder never wired | Dead feature | Connect in `on_message()` | `llm/orchestrator.py` |
| httpx client leak in streaming | Resource exhaustion | Reuse provider from router cache | `llm/orchestrator.py:251` |
| datetime.utcnow() in 11 files | Timestamp bugs | Replace with `datetime.now(timezone.utc)` | Multiple |

---

## Category 2: Foundation Upgrades (Weeks)

### 2A. Backend Foundations
1. Proper Python packaging — `pyproject.toml` + `pip install -e .` (replaces 9-file sys.path hack)
2. Test suite phase 1 — Unit tests for heuristics, context, prompts, auth utils
3. Test suite phase 2 — Integration tests for auth, messages, memory, forking
4. Dependency updates — FastAPI 0.115+, pin anthropic/openai, fix python-multipart
5. Fix memory injection — Wire `get_context_for_prompt(query=...)` instead of brute-force
6. Fix user modifier blending — Per-user modifiers instead of averaging

### 2B. Frontend Architecture Decision
The web frontend (`app.html`, 2,897 lines) is impressively polished but structurally cannot support vision features. The Dialectic Graph alone needs interactive SVG, state management, and URL routing.

**Decision needed:** Migrate to component framework before vision features, or accept increasing friction.

---

## Category 3: Vision Features (Prioritized Build Order)

### Phase A: Make Thinking Visible (2-3 weeks)

| # | Feature | Effort | Rationale |
|---|---------|--------|-----------|
| 1 | Conversation Analytics | Low | Event log has everything; pure read-side computation |
| 2 | LLM Self-Memory | Medium | 80% infrastructure ready; seed of Third Mind |
| 3 | Knowledge Graph Layer | Medium-Low | Data exists; materialized view + traversal API |

### Phase B: Structure the Dialogue (2-3 weeks)

| # | Feature | Effort | Rationale |
|---|---------|--------|-----------|
| 4 | Thinking Protocols | Medium | Most differentiating; prompt infra exists |
| 5 | Real-Time Typing Analysis | Low | Additive, noticeable UX improvement |

### Phase C: The Third Mind (2-3 weeks)

| # | Feature | Effort | Rationale |
|---|---------|--------|-----------|
| 6 | Persistent LLM Identity | Medium | Builds on Self-Memory |
| 7 | Async Dialogue / Slow Channel | Medium | Push infra exists; need ANNOTATOR mode |

### Phase D: Accountability Layer (3-4 weeks)

| # | Feature | Effort | Rationale |
|---|---------|--------|-----------|
| 8 | Event Replay Engine | Medium | Perfect architectural fit |
| 9 | Stakes / Commitments | Large | Most new code; build after data model matures |

### Phase E: Scale & Visualize (ongoing)

| # | Feature | Effort | Rationale |
|---|---------|--------|-----------|
| 10 | Redis Pub/Sub | Medium | Infrastructure; build when scale requires |
| 11 | Multi-Model Rooms | Medium | N named LLM personas with turn-taking |
| 12 | Dialectic Graph UI | Large | Culmination; needs frontend framework first |
| 13 | Frontend Migration | Large | Component framework for all vision features |

---

## Dependency Map

```
Schema Fix (days)
  ├── unlocks → Knowledge Graph (#3)
  ├── unlocks → LLM Self-Memory (#2)
  ├── unlocks → Persistent LLM Identity (#6)
  └── unlocks → Dialectic Graph (#12, partially)

Conversation Analytics (#1)
  └── data layer for → Stakes/Predictions (#9)

Knowledge Graph (#3)
  └── prerequisite for → Dialectic Graph UI (#12)

LLM Self-Memory (#2)
  └── prerequisite for → Persistent LLM Identity (#6)

Multi-Model Rooms (#11)
  └── enables richer → Thinking Protocols (#4)

Redis Pub/Sub (#10)
  └── prerequisite for → horizontal scaling of everything

Frontend Migration (#13)
  └── prerequisite for → Dialectic Graph UI (#12)
```

---

## The Single Highest-Leverage Action

Fix the schema gaps and wire up cross-session context. It's days of work, unblocks 4+ vision features, and activates code that's already written but disconnected. The cross-session memory system — collections, references, promotion, citation tracking — is the connective tissue that makes Dialectic more than a chat app. It's built. It just needs to be turned on.

---

## Cross-Reference

| Document | Purpose | Location |
|----------|---------|----------|
| VISION-NEXT.md | 5 strategic directions | `.planning/VISION-NEXT.md` |
| technical-opportunities.md | 7 technical capabilities | `.planning/technical-opportunities.md` |
| docs/VISION.md | Product vision + pitch | `dialectic/docs/VISION.md` |
| CONCERNS.md | Codebase risk analysis | `.planning/codebase/CONCERNS.md` |
| ARCHITECTURE.md | System architecture | `.planning/codebase/ARCHITECTURE.md` |
| TODOS.md | Current issue tracker | `dialectic/TODOS.md` |

---
*Created: 2026-02-20 (4-agent deep audit)*
