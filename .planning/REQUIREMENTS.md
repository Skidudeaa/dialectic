# Requirements: Dialectic

**Defined:** 2026-01-20
**Core Value:** Real-time collaborative creation with an LLM as a first-class participant

## v1 Requirements

Requirements for initial release. Each maps to roadmap phases.

### Authentication

- [x] **AUTH-01**: User can sign up with email and password
- [x] **AUTH-02**: User can log in with email and password
- [x] **AUTH-03**: User session persists across app restarts
- [x] **AUTH-04**: User can unlock app with biometric auth (Face ID / fingerprint)

### Real-Time Communication

- [ ] **RTCOM-01**: Messages sync in real-time across all participants (< 100ms latency)
- [ ] **RTCOM-02**: Typing indicators show when other participants are composing
- [ ] **RTCOM-03**: Presence indicators show online/away/offline status
- [ ] **RTCOM-04**: WebSocket reconnects automatically with gap sync after disconnection

### Push Notifications

- [ ] **PUSH-01**: User receives push notification when message arrives while app backgrounded
- [ ] **PUSH-02**: App icon badge shows unread message count
- [ ] **PUSH-03**: Push notifications show message preview (rich notifications)
- [ ] **PUSH-04**: Tapping notification opens relevant conversation

### LLM Participation

- [ ] **LLM-01**: LLM receives full conversation context for each interaction
- [ ] **LLM-02**: LLM responses stream token-by-token (not all at once)
- [ ] **LLM-03**: User can explicitly mention/summon LLM (e.g., @Claude)
- [ ] **LLM-04**: LLM interjects proactively based on heuristics (turn count, questions, stagnation)
- [ ] **LLM-05**: LLM interjection heuristics are configurable by users

### Session & History

- [ ] **HIST-01**: Conversation history persists across app sessions
- [ ] **HIST-02**: User can scroll up to load older messages (pagination)
- [ ] **HIST-03**: User can search within current conversation
- [ ] **HIST-04**: User can search across all conversations by topic/date
- [ ] **HIST-05**: User can fork a thread from any message (branch conversations)
- [ ] **HIST-06**: User can view thread genealogy (parent/child relationships)

### Platform Support

- [x] **PLAT-01**: App runs on iOS (iPhone)
- [x] **PLAT-02**: App runs on Android
- [ ] **PLAT-03**: App runs on macOS (desktop)
- [ ] **PLAT-04**: App runs on Windows (desktop)

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Enhanced Authentication

- **AUTH-05**: User can log in via magic link (passwordless)
- **AUTH-06**: User can link multiple devices to same account

### Offline & Sync

- **SYNC-01**: Messages queue locally when offline and sync when back online
- **SYNC-02**: Conflict resolution for simultaneous edits
- **SYNC-03**: Full offline mode with local-first architecture

### Advanced Notifications

- **PUSH-05**: User can reply to messages directly from notification
- **PUSH-06**: User can configure notification preferences per conversation

### Collaborative Artifacts (Phase 2 Vision)

- **COLLAB-01**: Shared document editing with real-time cursors
- **COLLAB-02**: Semantic version history for documents
- **COLLAB-03**: Partial/semantic diffs for document changes
- **COLLAB-04**: Shared code editor with real-time cursors
- **COLLAB-05**: LLM-driven code generation in shared editor

### AI Enhancements

- **AI-01**: AI-generated session summaries
- **AI-02**: Automatic topic extraction and tagging
- **AI-03**: Cross-session pattern detection

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Voice/video calls | Complexity, not core to text-based collaborative reasoning |
| File sharing/uploads | Deferred; text collaboration first |
| Multi-group support | v1 is for 2 users; multi-tenancy architected but not built |
| Custom LLM fine-tuning | Use general-purpose models first |
| Public/discoverable rooms | Private collaboration only for v1 |
| Web app | Native cross-platform clients only for v1 |

## Traceability

Which phases cover which requirements.

| Requirement | Phase | Status |
|-------------|-------|--------|
| AUTH-01 | Phase 2 | Complete |
| AUTH-02 | Phase 2 | Complete |
| AUTH-03 | Phase 2 | Complete |
| AUTH-04 | Phase 2 | Complete |
| RTCOM-01 | Phase 3 | Pending |
| RTCOM-02 | Phase 3 | Pending |
| RTCOM-03 | Phase 3 | Pending |
| RTCOM-04 | Phase 3 | Pending |
| PUSH-01 | Phase 6 | Pending |
| PUSH-02 | Phase 6 | Pending |
| PUSH-03 | Phase 6 | Pending |
| PUSH-04 | Phase 6 | Pending |
| LLM-01 | Phase 4 | Pending |
| LLM-02 | Phase 4 | Pending |
| LLM-03 | Phase 4 | Pending |
| LLM-04 | Phase 7 | Pending |
| LLM-05 | Phase 7 | Pending |
| HIST-01 | Phase 5 | Pending |
| HIST-02 | Phase 5 | Pending |
| HIST-03 | Phase 5 | Pending |
| HIST-04 | Phase 5 | Pending |
| HIST-05 | Phase 7 | Pending |
| HIST-06 | Phase 7 | Pending |
| PLAT-01 | Phase 1 | Complete |
| PLAT-02 | Phase 1 | Complete |
| PLAT-03 | Phase 8 | Pending |
| PLAT-04 | Phase 8 | Pending |

**Coverage:**
- v1 requirements: 27 total
- Mapped to phases: 27
- Unmapped: 0

---
*Requirements defined: 2026-01-20*
*Last updated: 2026-01-20 after roadmap creation*
