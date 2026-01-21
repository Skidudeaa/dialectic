# Roadmap: Dialectic

## Overview

This roadmap delivers Dialectic as a cross-platform collaborative workspace (iOS, Android, macOS, Windows) where two humans and an LLM co-reason in real-time. Development progresses from mobile foundation through authentication, real-time communication, LLM integration, session history, push notifications, and the unique Dialectic features (forking, heuristic interjection), culminating with desktop expansion. The existing Dialectic backend (WebSocket, LLM orchestration) and Cairn backend (sessions, search) provide substantial infrastructure.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Project Foundation** - React Native/Expo scaffolding with iOS and Android baseline
- [ ] **Phase 2: Authentication** - User accounts with session persistence and biometric unlock
- [ ] **Phase 3: Real-Time Core** - WebSocket messaging with presence, typing, and reconnection
- [ ] **Phase 4: LLM Participation** - LLM context, streaming responses, and explicit mentions
- [ ] **Phase 5: Session & History** - Conversation persistence, pagination, and search
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
- [ ] 01-01-PLAN.md — Expo project scaffold with ESLint/Prettier and Jest testing
- [ ] 01-02-PLAN.md — EAS Build configuration and GitHub Actions CI
- [ ] 01-03-PLAN.md — Platform verification (iOS and Android)

### Phase 2: Authentication
**Goal**: Users can create accounts, log in, and maintain sessions across app restarts
**Depends on**: Phase 1
**Requirements**: AUTH-01, AUTH-02, AUTH-03, AUTH-04
**Success Criteria** (what must be TRUE):
  1. User can sign up with email and password
  2. User can log in with email and password
  3. User remains logged in after closing and reopening app
  4. User can unlock app with Face ID or fingerprint after brief absence
**Plans**: TBD

Plans:
- [ ] 02-01: TBD
- [ ] 02-02: TBD

### Phase 3: Real-Time Core
**Goal**: Users experience real-time messaging with presence awareness and graceful disconnection handling
**Depends on**: Phase 2
**Requirements**: RTCOM-01, RTCOM-02, RTCOM-03, RTCOM-04
**Success Criteria** (what must be TRUE):
  1. Messages appear on all connected devices within 100ms
  2. Typing indicator shows when another participant is composing
  3. Presence indicator shows online/away/offline status for each participant
  4. App reconnects automatically after network interruption and syncs missed messages
**Plans**: TBD

Plans:
- [ ] 03-01: TBD
- [ ] 03-02: TBD

### Phase 4: LLM Participation
**Goal**: LLM participates in conversations with streamed responses and can be explicitly summoned
**Depends on**: Phase 3
**Requirements**: LLM-01, LLM-02, LLM-03
**Success Criteria** (what must be TRUE):
  1. LLM receives full conversation history for context-aware responses
  2. LLM responses stream token-by-token with visible typing animation
  3. User can summon LLM with @Claude mention and receive response
  4. LLM "thinking" indicator appears during response generation
**Plans**: TBD

Plans:
- [ ] 04-01: TBD
- [ ] 04-02: TBD

### Phase 5: Session & History
**Goal**: Conversations persist across sessions with full history access and search
**Depends on**: Phase 4
**Requirements**: HIST-01, HIST-02, HIST-03, HIST-04
**Success Criteria** (what must be TRUE):
  1. Conversation history persists and loads on app restart
  2. User can scroll up to load older messages (pagination works smoothly)
  3. User can search within current conversation and find matching messages
  4. User can search across all conversations by topic or date
**Plans**: TBD

Plans:
- [ ] 05-01: TBD
- [ ] 05-02: TBD

### Phase 6: Push Notifications
**Goal**: Users receive timely notifications when messages arrive while app is backgrounded
**Depends on**: Phase 3
**Requirements**: PUSH-01, PUSH-02, PUSH-03, PUSH-04
**Success Criteria** (what must be TRUE):
  1. User receives push notification when message arrives while app is backgrounded
  2. App icon badge shows unread message count
  3. Push notification shows message preview (sender name and content)
  4. Tapping notification opens the relevant conversation at the new message
**Plans**: TBD

Plans:
- [ ] 06-01: TBD
- [ ] 06-02: TBD
- [ ] 06-03: TBD

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
| 1. Project Foundation | 0/3 | Planned | - |
| 2. Authentication | 0/TBD | Not started | - |
| 3. Real-Time Core | 0/TBD | Not started | - |
| 4. LLM Participation | 0/TBD | Not started | - |
| 5. Session & History | 0/TBD | Not started | - |
| 6. Push Notifications | 0/TBD | Not started | - |
| 7. Dialectic Differentiators | 0/TBD | Not started | - |
| 8. Desktop Expansion | 0/TBD | Not started | - |

---
*Roadmap created: 2026-01-20*
*Last updated: 2026-01-20*
