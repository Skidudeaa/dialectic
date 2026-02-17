# Agent-Native Architecture Audit: Dialectic

> **Audit Date:** January 2026
> **Audited By:** 8 parallel specialized agents
> **Scope:** Full codebase analysis against agent-native principles

---

## Overall Score Summary

| Core Principle | Score | Percentage | Status |
|----------------|-------|------------|--------|
| Action Parity | 6/26 | 23% | ❌ |
| Tools as Primitives | 13/24 | 54% | ⚠️ |
| Context Injection | 7.5/15 | 50% | ⚠️ |
| Shared Workspace | 6/8 | 75% | ⚠️ |
| CRUD Completeness | 2/16 | 12.5% | ❌ |
| UI Integration | 7/7 | 100% | ✅ |
| Capability Discovery | 3/7 | 43% | ❌ |
| Prompt-Native Features | 13/24 | 54% | ⚠️ |

**Overall Agent-Native Score: 51%**

### Status Legend
- ✅ Excellent (80%+)
- ⚠️ Partial (50-79%)
- ❌ Needs Work (<50%)

---

## Principle Summaries

### 1. Action Parity (23%) ❌

**"Whatever the user can do, the agent can do."**

The LLM is primarily a **read-only dialogue respondent**. It can:
- ✅ Send messages
- ✅ Read messages/memories

It **cannot**:
- ❌ Create/edit/invalidate memories
- ❌ Fork threads
- ❌ Switch threads
- ❌ Update room settings
- ❌ Specify message types (Claim/Question/Definition)
- ❌ Reply to specific messages
- ❌ Search conversation history

**Impact:** LLM is a reactive tool, not a proactive participant.

---

### 2. Tools as Primitives (54%) ⚠️

**"Tools provide capability, not behavior."**

**Good primitives (13):** `fork_thread`, `add_memory`, `edit_memory`, `broadcast`, `typing_indicator`, `presence_heartbeat`, `get_thread_messages`

**Problematic workflows (11):**
- `InterjectionEngine.decide()` - encodes decision logic
- `PromptBuilder.build()` - mixes reading with assembly
- `_trigger_llm()` - couples transport + orchestration
- `ModelRouter.route()` - embeds retry/fallback logic
- `_detect_message_type()` - hardcoded classification

**Impact:** Decision-making is hidden inside tools, preventing LLM from querying its own decision state.

---

### 3. Context Injection (50%) ⚠️

**"System prompt includes dynamic context about app state."**

**Currently injected:**
- ✅ Room ontology & rules
- ✅ User preferences (aggression, metaphysics tolerance)
- ✅ Recent messages & thread ancestry
- ✅ Shared memories

**Missing context:**
- ❌ Online users/presence status
- ❌ Memory metadata (version, creator, scope)
- ❌ Semantic novelty signal
- ❌ Interjection decision rationale
- ❌ Thread topology/fork structure
- ❌ Model/mode awareness

**Impact:** LLM operates partially blind to why it's being invoked and who's present.

---

### 4. Shared Workspace (75%) ⚠️

**"Agent and user work in the same data space."**

**Fully shared (6):** messages, events, memories, memory_versions, threads, rooms

**Partial (2):** user_presence, message_receipts (LLM doesn't write)

**No isolation anti-patterns found.** This is exemplary:
- Same database, no sandboxes
- Unified event sourcing
- Both humans and LLM write to identical tables

**Impact:** Already production-grade for shared workspace principle.

---

### 5. CRUD Completeness (12.5%) ❌

**"Every entity has full CRUD for both users and agents."**

| Entity | User | LLM |
|--------|------|-----|
| Message | C✓R✓ | C✓R✓ |
| Memory | CRUD✓ | R only |
| Thread | CR✓ | R only |
| Room | CRU✓ | R only |

**Critical gaps:**
- LLM cannot create/edit/invalidate memories
- LLM cannot fork threads
- No message edit/delete for anyone
- LLM cannot update room settings

**Impact:** LLM is read-only for 87.5% of operations. Users have asymmetric advantages.

---

### 6. UI Integration (100%) ✅

**"Agent actions immediately reflected in UI."**

All 7 LLM actions have immediate WebSocket broadcasts:
- ✅ LLM message creation
- ✅ Streaming tokens (RAF-batched)
- ✅ Thinking indicator
- ✅ Stream completion
- ✅ Cancellation
- ✅ Error handling
- ✅ Heuristic interjections

**Architecture strengths:**
- DB persistence before broadcast (consistency)
- Message queue during disconnection (resilience)
- No silent actions detected

**Impact:** Excellent real-time synchronization. Reference implementation quality.

---

### 7. Capability Discovery (43%) ❌

**"Users can discover what the agent can do."**

| Mechanism | Status |
|-----------|--------|
| Onboarding flow | ❌ Missing |
| Help documentation | ❌ Missing |
| UI capability hints | ⚠️ Minimal |
| Agent self-description | ✅ In prompts |
| Suggested prompts | ❌ Missing |
| Empty state guidance | ⚠️ Weak |
| Help commands | ❌ Missing |

**Critical issue:** System prompt defines capabilities beautifully, but **users never see it**. The `@llm` syntax, message types, and fork capability are undiscoverable.

**Impact:** Users won't discover what makes Dialectic special.

---

### 8. Prompt-Native Features (54%) ⚠️

**"Features are prompts defining outcomes, not code."**

**Prompt-defined (13):**
- LLM identity & personality
- User preference blending
- Room ontology & rules
- Memory formatting
- Message type prefixes

**Code-defined anti-patterns (11):**
- Interjection triggers (turn count, question detection, novelty, stagnation)
- Message type classification
- Speaking role selection (primary vs provoker)
- Context truncation priority
- Streaming vs non-streaming decision

**Critical issue:** Room model has `interjection_turn_threshold` and `semantic_novelty_threshold` fields that are **never read**. Thresholds are hardcoded in `heuristics.py`.

**Impact:** Changing LLM behavior requires code changes, not prompt edits.

---

## Top 10 Recommendations by Impact

| Priority | Action | Principle | Effort |
|----------|--------|-----------|--------|
| P0 | Enable LLM memory writes (add/edit/invalidate) | CRUD, Parity | 4h |
| P0 | Enable LLM thread forking | CRUD, Parity | 2h |
| P1 | Move interjection rules to prompts | Prompt-Native | 3h |
| P1 | Inject interjection rationale into context | Context | 1h |
| P1 | Add `/help` command and onboarding | Discovery | 3h |
| P2 | Connect Room config fields to prompt assembly | Prompt-Native | 2h |
| P2 | Inject presence/online users into prompt | Context | 1h |
| P2 | Add UI tooltips for message types/features | Discovery | 2h |
| P3 | Extract decision logic from workflows into queryable state | Tools | 4h |
| P3 | Enable message reply references for LLM | Parity | 2h |

---

## What's Working Excellently

1. **Shared Workspace (75%)** - No sandbox anti-patterns. Both humans and LLM operate on the same data.

2. **UI Integration (100%)** - All LLM actions have immediate WebSocket broadcasts with RAF-batched streaming.

3. **Event Sourcing** - All state changes logged to append-only `events` table for full auditability.

4. **Prompt Identity** - BASE_IDENTITY and PROVOKER_IDENTITY clearly define LLM role as "co-thinker, not assistant."

5. **User Preference Blending** - Aggression level, metaphysics tolerance, and custom instructions properly injected.

---

## Architecture Diagnosis

### Root Cause of Gaps

The codebase was designed with LLM as a **reactive dialogue generator**, not an **autonomous agent**. Evidence:

1. **Handler-centric design** - All LLM actions flow through `MessageHandler` which is inbound-message oriented
2. **No tool definitions** - LLM has no explicit tool schema; it only receives context and generates text
3. **Heuristics as black box** - Decision logic hidden from both LLM and users
4. **Read-only memories** - LLM reads memories but never writes them

### Path to Agent-Native

Transform from "LLM as smart responder" to "LLM as co-participant":

```
Current Flow:
  Human message → Handler → Heuristics (code) → LLM generates text → Persist

Agent-Native Flow:
  Human message → Handler → LLM decides + acts:
    - Query: "Should I respond?"
    - Query: "Who's present?"
    - Action: Add memory
    - Action: Fork thread
    - Action: Respond with type
```

This requires:
1. Exposing operations as LLM-callable tools
2. Injecting decision context into prompts
3. Moving heuristics from code to prompt directives
4. Surfacing capabilities to users

---

## Implementation Roadmap

### Phase 1: Core Agency (Week 1)
- [ ] Enable LLM memory writes
- [ ] Enable LLM thread forking
- [ ] Connect Room config to prompts
- [ ] Inject interjection rationale

### Phase 2: Discoverability (Week 2)
- [ ] Add onboarding modal
- [ ] Implement `/help` command
- [ ] Add feature tooltips
- [ ] Surface LLM capabilities in UI

### Phase 3: Tool Architecture (Week 3)
- [ ] Extract decision logic to queryable state
- [ ] Decompose workflows into primitives
- [ ] Create explicit LLM tool definitions
- [ ] Move classification to prompt

---

## Files Requiring Changes

| File | Changes Needed |
|------|----------------|
| `llm/orchestrator.py` | Add memory/thread operations callable by LLM |
| `llm/heuristics.py` | Move thresholds to Room config, inject rationale |
| `llm/prompts.py` | Add interjection directives, presence context |
| `transport/handlers.py` | Wire LLM-initiated operations |
| `frontend/index.html` | Add onboarding, tooltips, `/help` |
| `api/main.py` | Add message edit/delete endpoints |

---

## Conclusion

Dialectic scores **51% agent-native**, with UI Integration being the standout strength (100%) and CRUD Completeness the critical gap (12.5%). The codebase has excellent foundations (shared workspace, event sourcing, prompt identity) but treats the LLM as a sophisticated responder rather than an autonomous agent.

**To achieve the vision of "two humans and an LLM co-reasoning together,"** the LLM needs:
1. Write access to shared knowledge (memories)
2. Ability to reshape conversation structure (threads)
3. Self-awareness of why it's speaking (context)
4. Discoverable capabilities (UI)
5. Prompt-directed behavior (not code)

The architectural bones are solid. The gaps are addressable with focused work on the top 10 recommendations above.
