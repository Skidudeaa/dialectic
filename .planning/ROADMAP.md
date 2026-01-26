# Roadmap: Dialectic

## Overview

This roadmap delivers Dialectic as a cross-platform collaborative workspace (iOS, Android, macOS, Windows) where two humans and an LLM co-reason in real-time. Development progresses from mobile foundation through authentication, real-time communication, LLM integration, session history, push notifications, and the unique Dialectic features (forking, heuristic interjection), culminating with desktop expansion. The existing Dialectic backend (WebSocket, LLM orchestration) and Cairn backend (sessions, search) provide substantial infrastructure.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Project Foundation** - React Native/Expo scaffolding with iOS and Android baseline
- [x] **Phase 2: Authentication** - User accounts with session persistence and biometric unlock
- [x] **Phase 3: Real-Time Core** - WebSocket messaging with presence, typing, and reconnection
- [x] **Phase 4: LLM Participation** - LLM context, streaming responses, and explicit mentions
- [x] **Phase 5: Session & History** - Conversation persistence, pagination, and search
- [ ] **Phase 6: Push Notifications** - Background notifications with badges and deep linking
- [ ] **Phase 7: Dialectic Differentiators** - Thread forking, genealogy, and LLM heuristic controls
- [ ] **Phase 8: Desktop Expansion** - macOS and Windows clients via React Native

## Phase Details

### Phase 1: Project Foundation
**Goal**: Establish cross-platform mobile development infrastructure with working iOS and Android builds
**Depends on**: Nothing (first phase)
**Requirements**: PLAT-01, PLAT-02
**Success Criteria** (what must be TRUE):
  1. App launches on iOS simulator and physical iPhone
  2. App launches on Android emulator and physical device
  3. Shared React Native codebase compiles for both platforms
  4. CI pipeline builds both platform artifacts
**Plans**: 3 plans

Plans:
- [x] 01-01-PLAN.md — Expo project scaffold with ESLint/Prettier and Jest testing
- [x] 01-02-PLAN.md — EAS Build configuration and GitHub Actions CI
- [x] 01-03-PLAN.md — Platform verification (iOS and Android)

### Phase 2: Authentication
**Goal**: Users can create accounts, log in, and maintain sessions across app restarts
**Depends on**: Phase 1
**Requirements**: AUTH-01, AUTH-02, AUTH-03, AUTH-04
**Success Criteria** (what must be TRUE):
  1. User can sign up with email and password
  2. User can log in with email and password
  3. User remains logged in after closing and reopening app
  4. User can unlock app with Face ID or fingerprint after brief absence
**Plans**: 5 plans

Plans:
- [x] 02-01-PLAN.md — Backend auth module with JWT, Argon2, and email verification
- [x] 02-02-PLAN.md — Mobile auth infrastructure with SecureStore and API client
- [x] 02-03-PLAN.md — Auth screens (sign-in, sign-up, verify, reset password)
- [x] 02-04-PLAN.md — Route protection with session-based navigation
- [x] 02-05-PLAN.md — Biometric unlock with PIN fallback

### Phase 3: Real-Time Core
**Goal**: Users experience real-time messaging with presence awareness and graceful disconnection handling
**Depends on**: Phase 2
**Requirements**: RTCOM-01, RTCOM-02, RTCOM-03, RTCOM-04
**Success Criteria** (what must be TRUE):
  1. Messages appear on all connected devices within 100ms
  2. Typing indicator shows when another participant is composing
  3. Presence indicator shows online/away/offline status for each participant
  4. App reconnects automatically after network interruption and syncs missed messages
**Plans**: 6 plans

Plans:
- [x] 03-01-PLAN.md — Backend presence and receipt handlers
- [x] 03-02-PLAN.md — Mobile WebSocket service with reconnection
- [x] 03-03-PLAN.md — Presence tracking with auto-away
- [x] 03-04-PLAN.md — Typing indicators with debounce
- [x] 03-05-PLAN.md — Offline queue and gap sync
- [x] 03-06-PLAN.md — Message delivery states

### Phase 4: LLM Participation
**Goal**: LLM participates in conversations with streamed responses and can be explicitly summoned
**Depends on**: Phase 3
**Requirements**: LLM-01, LLM-02, LLM-03
**Success Criteria** (what must be TRUE):
  1. LLM receives full conversation history for context-aware responses
  2. LLM responses stream token-by-token with visible typing animation
  3. User can summon LLM with @Claude mention and receive response
  4. LLM "thinking" indicator appears during response generation
**Plans**: 4 plans

Plans:
- [x] 04-01-PLAN.md — Backend streaming handler with token broadcast
- [x] 04-02-PLAN.md — Mobile LLM store and WebSocket types
- [x] 04-03-PLAN.md — LLM UI components (thinking indicator, markdown, bubble)
- [x] 04-04-PLAN.md — @Claude mention input and detection

### Phase 5: Session & History
**Goal**: Conversations persist across sessions with full history access and search
**Depends on**: Phase 4
**Requirements**: HIST-01, HIST-02, HIST-03, HIST-04
**Success Criteria** (what must be TRUE):
  1. Conversation history persists and loads on app restart
  2. User can scroll up to load older messages (pagination works smoothly)
  3. User can search within current conversation and find matching messages
  4. User can search across all conversations by topic or date
**Plans**: 7 plans

Plans:
- [x] 05-01-PLAN.md — Backend search infrastructure (tsvector, GIN index, search endpoints)
- [x] 05-02-PLAN.md — Mobile SQLite database with Drizzle ORM and FTS5
- [x] 05-03-PLAN.md — Session state store (MMKV) and draft auto-save
- [x] 05-04-PLAN.md — Message cache with 500-message limit and pagination hook
- [x] 05-05-PLAN.md — FlashList message list with bidirectional pagination
- [x] 05-06-PLAN.md — Search feature (local FTS5 + server, overlay UI with filters)
- [x] 05-07-PLAN.md — Session continuity (app launch restoration, scroll position)

### Phase 6: Push Notifications
**Goal**: Users receive timely notifications when messages arrive while app is backgrounded
**Depends on**: Phase 3
**Requirements**: PUSH-01, PUSH-02, PUSH-03, PUSH-04
**Success Criteria** (what must be TRUE):
  1. User receives push notification when message arrives while app is backgrounded
  2. App icon badge shows unread message count
  3. Push notification shows message preview (sender name and content)
  4. Tapping notification opens the relevant conversation at the new message
**Plans**: 5 plans

Plans:
- [ ] 06-01-PLAN.md — Backend push infrastructure (schema, Expo SDK service, token endpoints)
- [ ] 06-02-PLAN.md — Mobile notification setup (packages, channels, token registration)
- [ ] 06-03-PLAN.md — Message handler push trigger (foreground suppression)
- [ ] 06-04-PLAN.md — Notification handlers and deep linking
- [ ] 06-05-PLAN.md — Badge management (server-synced counts, visibility tracking)

### Phase 7: Dialectic Differentiators
**Goal**: Users access Dialectic's unique features: thread forking, genealogy visualization, and LLM behavior configuration
**Depends on**: Phase 5
**Requirements**: HIST-05, HIST-06, LLM-04, LLM-05
**Success Criteria** (what must be TRUE):
  1. User can fork a thread from any message, creating a branched conversation
  2. User can view thread genealogy showing parent/child relationships
  3. LLM interjects proactively based on heuristics (turn count, questions, stagnation)
  4. User can configure LLM interjection thresholds and behavior
**Plans**: TBD

Plans:
- [ ] 07-01: TBD
- [ ] 07-02: TBD

### Phase 8: Desktop Expansion
**Goal**: Dialectic runs natively on macOS and Windows with feature parity to mobile
**Depends on**: Phase 7
**Requirements**: PLAT-03, PLAT-04
**Success Criteria** (what must be TRUE):
  1. App runs natively on macOS with platform-appropriate UI conventions
  2. App runs natively on Windows with platform-appropriate UI conventions
  3. All core features work identically to mobile (messaging, LLM, forking)
  4. Desktop apps share codebase with mobile (React Native Windows/macOS)
**Plans**: TBD

Plans:
- [ ] 08-01: TBD
- [ ] 08-02: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4 -> 5 -> 6 -> 7 -> 8

Note: Phase 6 (Push Notifications) depends on Phase 3, not Phase 5. Can execute in parallel with Phase 4/5 if resources allow.

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Project Foundation | 3/3 | Complete | 2026-01-21 |
| 2. Authentication | 5/5 | Complete | 2026-01-20 |
| 3. Real-Time Core | 6/6 | Complete | 2026-01-25 |
| 4. LLM Participation | 4/4 | Complete | 2026-01-25 |
| 5. Session & History | 7/7 | Complete | 2026-01-25 |
| 6. Push Notifications | 0/5 | Ready | - |
| 7. Dialectic Differentiators | 0/TBD | Not started | - |
| 8. Desktop Expansion | 0/TBD | Not started | - |

---
*Roadmap created: 2026-01-20*
*Last updated: 2026-01-25 (Phase 6 planned)*
