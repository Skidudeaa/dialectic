# Feature Landscape

**Domain:** Real-time collaborative workspace with LLM participant
**Researched:** 2026-01-20
**Project:** Dialectic - 2 humans + 1 LLM co-reasoning in real-time
**Target Platforms:** iOS/Mac, Android/Windows (mobile clients)

## Executive Summary

Real-time collaboration is now table stakes, not a differentiator. Users trained by Slack, Discord, Notion, and Figma expect instantaneous updates, presence indicators, and seamless cross-device sync. The differentiating opportunity for Dialectic lies in the LLM-as-participant model - no major collaboration tool has an LLM that genuinely participates rather than assists.

---

## Table Stakes

Features users expect. Missing = product feels incomplete or broken.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Real-time message sync | Slack/Discord set this expectation; users won't tolerate refresh delays | Medium | WebSocket foundation already exists in Dialectic backend |
| Presence indicators (online/away/offline) | Standard in every collaboration app since 2010 | Low | Green/yellow/gray dots next to user avatars |
| Typing indicators | Creates sense of presence and prevents message collisions | Low | "Alice is typing..." shown to all participants |
| Push notifications | Users expect to be notified when away from app | Medium | Platform-specific (APNs for iOS, FCM for Android); needs backend support |
| Message history persistence | Users expect to see full conversation when returning | Low | Already implemented via event sourcing |
| Cross-device sync | Users switch between phone/desktop constantly | Medium | Session state must persist server-side |
| Search within conversations | Finding past discussions is critical | Medium | Elasticsearch or pgvector semantic search (already have vector infrastructure) |
| Read receipts / unread indicators | Know what you've missed | Low | Track last-read message per user per thread |
| Basic thread organization | Navigate between different conversations/rooms | Low | Already have rooms/threads in schema |
| Offline message queuing | Messages should send when connection returns | Medium | Critical for mobile; queue locally, sync when online |

### Presence Indicator Requirements

Based on research from [Sendbird](https://sendbird.com/learn/what-are-user-presence-indicators) and [PubNub](https://www.pubnub.com/guides/the-importance-of-user-presence-in-real-time-technology/):

- **Online:** Active in app (green dot)
- **Idle:** App open but inactive 5+ minutes (yellow dot)
- **Away:** Manually set or app backgrounded 15+ minutes (gray dot)
- **Offline:** Disconnected (no dot or outline only)
- **Do Not Disturb:** User-configurable status suppressing notifications

### Push Notification Requirements

Based on [Reteno best practices](https://reteno.com/blog/push-notification-best-practices-ultimate-guide-for-2026):

- Truncated message previews that create curiosity without revealing full content
- Segment by user behavior (power user vs. casual)
- Time-sensitive triggers (real-time on new message, batched for non-urgent)
- Respect user preferences (granular opt-in per room/thread)
- iOS opt-in rate: 51%; Android opt-in rate: 81% - onboard carefully

---

## Differentiators

Features that set Dialectic apart. Not expected, but valuable.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **LLM as participant** (not assistant) | Unique interaction model - LLM challenges and synthesizes rather than serving | High | Core differentiator; already in backend architecture |
| **Proactive LLM interjection** | LLM speaks unprompted when it has relevant insight | High | Heuristics engine exists; tune for mobile UX |
| **Thread forking/branching** | Explore tangent without polluting main thread | Medium | Already implemented; expose in mobile UI |
| **Shared memories with versioning** | Build persistent shared knowledge base across sessions | High | Already have vector memory; needs mobile CRUD UI |
| **LLM mode switching** (primary/provoker) | Adjust LLM personality based on conversation needs | Medium | Backend supports; expose as user control |
| **Cross-session memory recall** | LLM remembers context from previous sessions | High | Uses vector similarity; powerful differentiator |
| **Conversation genealogy visualization** | See how threads branched and evolved | Medium | Unique to Dialectic's fork model |
| **Collaborative annotation** | Mark key moments/insights in conversation | Medium | Future enhancement for knowledge capture |
| **LLM thought transparency** | Show why LLM chose to interject | Low | Build trust; distinguish from random chatbots |

### LLM-as-Participant Design Patterns

Based on research from [arXiv Inner Thoughts paper](https://arxiv.org/html/2501.00383v2) and [CHI 2025 proceedings](https://dl.acm.org/doi/10.1145/3706598.3715579):

**Proactive Interjection Model:**
1. **Motivation scoring:** LLM evaluates each "thought" for relevance before speaking
2. **Interruption threshold:** Configurable 1-5 scale for how assertively LLM interjects
3. **Tonal proactivity:** LLM can be assertive ("Actually, there's a problem with that") or gentle ("I have a thought, if you'd like to hear it")

**Key Design Choices for Dialectic:**
- LLM should NOT speak on every turn (overwhelming)
- LLM should NOT wait to be addressed (reactive assistant behavior)
- Sweet spot: LLM speaks when it detects genuine opportunity to advance discussion
- Existing heuristics (turn count 4+, questions, semantic novelty, stagnation) are well-aligned

**Transparency Pattern:**
- Show "thinking..." indicator before LLM speaks (like typing indicator)
- Optionally show brief rationale: "I'm jumping in because this connects to something we discussed earlier"

### Thread Forking UX

Based on [LibreChat fork documentation](https://www.librechat.ai/docs/features/fork) and [ChatGPT branching](https://medium.com/@CherryZhouTech/chatgpt-launches-branched-chats-effortless-multi-threaded-conversations-d188b90bd78b):

**Why forking matters:**
- Long conversations spawn tangential ideas
- Forking prevents main thread pollution
- Each branch develops independently
- Both branches retain context up to fork point

**Mobile UX considerations:**
- Long-press on any message to fork
- Visual indicator of fork points in timeline
- Easy navigation between sibling branches
- Show fork lineage/genealogy when requested

---

## Anti-Features

Features to explicitly NOT build. Common mistakes in this domain.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| **LLM that always responds** | Feels like assistant, not participant; overwhelming | Heuristic-based interjection with tunable thresholds |
| **LLM that only responds when mentioned** | Passive assistant pattern; defeats purpose | Proactive engagement with relevance scoring |
| **Notification spam** | 46+ notifications/day already; users will mute everything | Smart batching, user-controlled granularity, truncated previews |
| **Hide-and-hover UI patterns** | Forces exploration with mouse; terrible on mobile | Show action affordances visibly |
| **All-or-nothing notification permission** | Users reject; 49% iOS opt-out rate | Delayed permission request after value demonstration |
| **Form data loss on errors** | Highest-frustration pattern in UX | Always preserve user input; inline validation |
| **No human escalation path** | LLM will occasionally fail or misunderstand | Clear "mute LLM" or "take a break" controls |
| **Cluttered interface** | Microsoft Teams syndrome; overwhelms new users | Progressive disclosure; show essentials first |
| **Sync-first architecture** | Fails on spotty mobile connections | Offline-first with background sync |
| **Complex onboarding** | Notion requires ~1 week setup; Slack onboards in minutes | Minimal viable configuration; learn by doing |
| **LLM amnesia across sessions** | Defeats persistent collaboration value | Leverage existing vector memory for continuity |
| **Last-write-wins for all conflicts** | Loses user work silently | CRDT for text, user-assisted resolution for critical data |
| **Proactive chat without qualifying** | Intrusive if untargeted | Only interject when relevance score exceeds threshold |

### Specific LLM Anti-Patterns

From [Certainly UX mistakes](https://www.certainly.io/blog/top-ux-mistakes-chatbot) and [Khoros GenAI fails](https://khoros.com/blog/5-gen-ai-chatbot-fails-and-how-to-avoid-them):

1. **Repeating questions user already answered:** Maintain conversation context
2. **Ignoring multi-part messages:** Parse full input, don't keyword-match first word
3. **No error recovery:** Allow users to backtrack, correct, or restart
4. **Promising capabilities that don't exist:** (Air Canada chatbot lawsuit example)
5. **No handoff to "quiet mode":** Users must be able to silence LLM

---

## Feature Dependencies

```
Push Notifications
    <- Presence System (know when user is away)
    <- User Preferences (granular opt-in)

Cross-Device Sync
    <- Session Persistence (server-side state)
    <- Offline Queuing (handle disconnections)

LLM Proactive Interjection
    <- Conversation Context (full history access)
    <- Memory System (cross-session recall)
    <- Heuristics Engine (when to speak)

Thread Forking UI
    <- Fork Backend (already exists)
    <- Genealogy Queries (ancestry tracking)
    <- Navigation System (switch between branches)

Shared Memories
    <- Vector Search (semantic retrieval)
    <- Memory CRUD (add/edit/invalidate)
    <- Versioning (track changes)

Offline-First
    <- Local Storage (queue messages)
    <- Sync Engine (reconcile on reconnect)
    <- Conflict Resolution (handle concurrent edits)
```

---

## Complexity Estimates by Category

### Low Complexity (Days)
- Typing indicators
- Read receipts / unread counts
- Presence indicators (online/away/offline)
- User-controllable LLM quiet mode

### Medium Complexity (1-2 Weeks)
- Push notification integration (APNs + FCM)
- Cross-device session sync
- Thread forking mobile UI
- Search within conversations
- Offline message queuing
- Basic notification preferences

### High Complexity (2-4+ Weeks)
- Offline-first with conflict resolution
- CRDT-based collaborative editing (future)
- Advanced LLM proactive tuning
- Memory CRUD with versioning UI
- Conversation genealogy visualization

---

## MVP Recommendation

For mobile MVP, prioritize in this order:

### Phase 1: Core Communication (Table Stakes)
1. Real-time message sync (WebSocket to mobile)
2. Presence indicators
3. Typing indicators
4. Message history persistence
5. Push notifications (basic)
6. Unread indicators

### Phase 2: Dialectic Differentiators
1. LLM participation visible in mobile UI
2. Thread forking mobile UX
3. LLM quiet mode toggle
4. Basic memory viewing (read-only)

### Phase 3: Polish & Delight
1. Cross-session memory recall UI
2. Advanced notification preferences
3. Offline-first with sync
4. Memory CRUD operations
5. Conversation genealogy visualization

### Defer to Post-MVP
- Collaborative document editing (CRDT complexity)
- Code editing features (specialized tooling)
- Advanced LLM mode switching UI
- Annotation/highlighting system

---

## Platform-Specific Considerations

### iOS
- Push via APNs (Apple Push Notification service)
- Background app refresh for sync
- Notification grouping by room/thread
- Privacy-conscious (presence opt-out expected)

### Android
- Push via FCM (Firebase Cloud Messaging)
- More permissive background sync
- Higher notification opt-in rate (81%)
- Widget potential for quick access

### Cross-Platform
- Shared backend (existing FastAPI + WebSocket)
- Platform-specific push registration endpoints
- Unified presence/typing protocol
- Same message format (existing Pydantic models)

---

## Sources

**Real-time Collaboration:**
- [The Digital Project Manager - Real-Time Collaboration Tools 2026](https://thedigitalprojectmanager.com/tools/real-time-collaboration-tools/)
- [DEV Community - Real-time Multiplayer Collaboration](https://dev.to/vladi-stevanovic/real-time-multiplayer-collaboration-is-a-must-in-modern-applications-10ml)

**Presence & Typing Indicators:**
- [Sendbird - User Presence Indicators](https://sendbird.com/learn/what-are-user-presence-indicators)
- [PubNub - User Presence Guide](https://www.pubnub.com/guides/the-importance-of-user-presence-in-real-time-technology/)
- [MyShyft - Typing Indicators UX](https://www.myshyft.com/blog/typing-indicators/)

**Push Notifications:**
- [Reteno - Push Notification Best Practices 2026](https://reteno.com/blog/push-notification-best-practices-ultimate-guide-for-2026)
- [Knock - Real-time Notification Services](https://knock.app/blog/the-top-real-time-notification-services-for-building-in-app-notifications)

**LLM Conversation Patterns:**
- [arXiv - Proactive Conversational Agents with Inner Thoughts](https://arxiv.org/html/2501.00383v2)
- [CHI 2025 - LLM Powered Chatbot as Proactive Companion](https://dl.acm.org/doi/10.1145/3706598.3715579)
- [Pinecone - Conversational Memory for LLMs](https://www.pinecone.io/learn/series/langchain/langchain-conversational-memory/)
- [arXiv - Collaborative Memory: Multi-User Memory Sharing](https://arxiv.org/html/2505.18279v1)

**Thread Forking/Branching:**
- [LibreChat - Forking Messages and Conversations](https://www.librechat.ai/docs/features/fork)
- [Medium - ChatGPT Branched Chats](https://medium.com/@CherryZhouTech/chatgpt-launches-branched-chats-effortless-multi-threaded-conversations-d188b90bd78b)

**Offline-First & Sync:**
- [Android Developers - Offline-First Architecture](https://developer.android.com/topic/architecture/data-layer/offline-first)
- [DeveloperVoice - Offline-First Sync Patterns](https://developersvoice.com/blog/mobile/offline-first-sync-patterns/)

**UX Anti-Patterns:**
- [Certainly - Chatbot UX Mistakes](https://www.certainly.io/blog/top-ux-mistakes-chatbot)
- [Eleken - Bad UX Examples](https://www.eleken.co/blog-posts/bad-ux-examples)
- [Khoros - GenAI Chatbot Fails](https://khoros.com/blog/5-gen-ai-chatbot-fails-and-how-to-avoid-them)

**Collaborative Editing (Future Reference):**
- [TinyMCE - OT vs CRDT](https://www.tiny.cloud/blog/real-time-collaboration-ot-vs-crdt/)
- [Ink & Switch - Peritext CRDT](https://www.inkandswitch.com/peritext/)
