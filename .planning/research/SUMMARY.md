# Project Research Summary

**Project:** Dialectic Cross-Platform Clients
**Domain:** Real-time collaborative workspace with LLM participant
**Researched:** 2026-01-20
**Confidence:** HIGH

## Executive Summary

Dialectic is a collaborative dialogue engine where 2 humans and an LLM co-reason in real-time. The existing FastAPI backend provides a solid foundation with WebSocket-based real-time messaging, event sourcing, heuristic LLM interjection, and vector memory. The mobile client challenge is straightforward: React Native with Expo is the clear choice given JavaScript alignment, Microsoft-maintained desktop support, and the existing JSON/WebSocket backend.

The recommended approach is to build mobile-first with Expo managed workflow, then eject for desktop (Windows/macOS) support. The core architecture already exists on the backend; the client work is primarily transport integration, offline resilience, and UI. The LLM-as-participant differentiator is already implemented in the backend heuristics engine.

The key risks are: (1) WebSocket connections dying when mobile apps background (design for disconnection from day one), (2) LLM latency breaking the real-time experience (stream tokens, show typing indicators), and (3) push notification complexity being underestimated (allow 4-6 weeks, not 1-2). All three are addressable with proper architecture decisions made early.

## Key Findings

### Recommended Stack

React Native 0.83+ with Expo SDK 55+ is the clear recommendation. The New Architecture (TurboModules, Fabric) is now mandatory and mature. Microsoft maintains React Native Windows and macOS, making cross-platform desktop support viable. The existing Dialectic backend speaks JSON over WebSocket, which maps directly to JavaScript's native capabilities.

**Core technologies:**
- **React Native 0.83+ / Expo SDK 55+**: Cross-platform framework with mature New Architecture
- **Zustand 5.x**: Lightweight state management (3KB, hook-based, 40% market share)
- **TanStack Query 5.x**: Server state management with offline persistence
- **react-native-mmkv 4.x**: Fast key-value storage (30x faster than AsyncStorage, encryption built-in)
- **React Navigation 7.x**: De facto navigation standard
- **Native WebSocket API**: No Socket.IO needed; backend already speaks raw WebSocket

**Desktop targets:**
- React Native Windows 0.79+ (Microsoft-maintained)
- React Native macOS 0.79+ (Microsoft-maintained)

### Expected Features

**Must have (table stakes):**
- Real-time message sync (WebSocket to mobile)
- Presence indicators (online/away/offline)
- Typing indicators
- Push notifications (APNs + FCM)
- Message history persistence
- Unread indicators / read receipts
- Cross-device sync
- Offline message queuing

**Should have (differentiators):**
- LLM as participant (proactive interjection, not reactive assistant)
- Thread forking mobile UI
- LLM mode switching (primary/provoker)
- Shared memory viewing/editing
- Cross-session memory recall
- LLM thought transparency ("I'm jumping in because...")

**Defer (v2+):**
- Collaborative document editing (CRDT complexity)
- Code editing features
- Annotation/highlighting system
- Advanced LLM personality switching

### Architecture Approach

The architecture follows a layered pattern: mobile clients communicate via WebSocket/REST through an API gateway to the Dialectic and Cairn services, with shared Redis infrastructure for pub/sub and caching. The existing Dialectic backend provides event sourcing, LLM orchestration with provider fallback, and vector memory. The key extension needed is replacing the in-memory connection registry with Redis pub/sub for horizontal scaling.

**Major components:**
1. **Mobile Client**: UI, local state, offline queue, WebSocket reconnection
2. **API Gateway**: Auth (JWT), rate limiting, WebSocket upgrade, request routing
3. **Dialectic Service**: Rooms, threads, messages, memories, event sourcing
4. **LLM Orchestrator**: Provider routing, retry logic, interjection heuristics, prompt assembly
5. **Redis**: Pub/sub for horizontal scaling, caching, session state

### Critical Pitfalls

1. **WebSocket background handling on mobile** — iOS/Android kill connections when backgrounded. Design for disconnection from day one. Use sequence numbers for gap detection. Push notifications are the reliability layer, not WebSocket.

2. **LLM latency destroying real-time experience** — LLM responses take 1-5 seconds. Stream tokens immediately. Show "Claude is thinking..." typing indicator. First token matters more than total time.

3. **State synchronization without conflict strategy** — Choose conflict strategy during design: server-assigned sequence numbers for messages (already implemented), version numbers for memories. Don't retrofit.

4. **Push notification complexity underestimation** — Budget 4-6 weeks, not 1-2. Token lifecycle management, platform-specific payloads, silent failures are all traps. Use Expo Push if staying managed.

5. **Cross-platform UI divergence** — Test on both iOS and Android from day one. Platform-specific components where needed. Back button (Android) vs swipe navigation (iOS) differ.

## Implications for Roadmap

Based on research, suggested phase structure:

### Phase 1: Foundation
**Rationale:** Everything depends on auth and basic connectivity. The backend architecture decisions (Redis pub/sub, JWT auth) must precede mobile development.
**Delivers:** Authenticated WebSocket connection, reconnection with gap detection, basic message UI
**Addresses:** Real-time message sync, presence indicators, typing indicators
**Avoids:** WebSocket background handling pitfall (design for disconnection from start), cross-platform divergence (dual-platform testing from day 1)
**Stack:** React Native 0.83, Expo SDK 55, Zustand, Native WebSocket API

### Phase 2: Core Collaboration
**Rationale:** Once connected, users need the full messaging experience including LLM participation visibility.
**Delivers:** Complete message flow with LLM responses streaming, offline queuing, basic push notifications
**Addresses:** LLM participation in mobile, offline message queuing, push notifications
**Avoids:** LLM latency pitfall (streaming from start), message ordering issues (sequence numbers)
**Stack:** TanStack Query with MMKV persister, @react-native-firebase/messaging or expo-notifications

### Phase 3: Dialectic Differentiators
**Rationale:** Core communication is stable; now add the features that make Dialectic unique.
**Delivers:** Thread forking UI, memory viewing, LLM controls (quiet mode, mode switching)
**Addresses:** Thread forking, shared memories, LLM mode switching, cross-session memory recall
**Avoids:** LLM behavior pitfall (configurable interjection thresholds, user controls)

### Phase 4: Desktop and Scale
**Rationale:** Mobile MVP is complete; now extend to desktop and prepare for growth.
**Delivers:** Windows/macOS clients, horizontal scaling, performance optimization
**Addresses:** Cross-platform desktop, multi-server deployment, message archival
**Avoids:** React Native upgrade pain (stay current), battery drain (tune keep-alives)

### Phase Ordering Rationale

- **Auth before features**: JWT shared between Dialectic/Cairn enables unified identity
- **WebSocket before push**: Push supplements WebSocket, not replaces it
- **Streaming before UI polish**: LLM latency perception must be solved architecturally
- **Mobile before desktop**: Expo managed workflow for fast iteration, then eject for desktop
- **Forking after messaging**: Thread forking requires stable message infrastructure

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 2 (Push Notifications)**: Platform-specific integration varies significantly. Research FCM/APNs specifics when implementing.
- **Phase 4 (Desktop)**: React Native Windows/macOS ejection process may have evolved. Check current docs.

Phases with standard patterns (skip research-phase):
- **Phase 1 (WebSocket/Auth)**: Well-documented patterns, existing Dialectic code as reference
- **Phase 3 (Forking/Memories)**: Backend already implemented; mobile is UI work

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Official docs, Microsoft-maintained desktop, mature ecosystem |
| Features | HIGH | Based on established collaboration app patterns (Slack, Discord, Notion) |
| Architecture | HIGH | Dialectic backend already implemented; extending existing patterns |
| Pitfalls | MEDIUM-HIGH | Verified via multiple sources; some platform-specific details may change |

**Overall confidence:** HIGH

### Gaps to Address

- **Push notification token lifecycle**: Exact implementation varies by React Native version and Firebase SDK. Validate during Phase 2 planning.
- **Expo ejection for desktop**: Process may have changed since research. Check Expo docs when ready for Phase 4.
- **LLM interjection tuning**: Heuristics exist but optimal thresholds need user testing. Plan for iteration in Phase 3.

## Sources

### Primary (HIGH confidence)
- [React Native Blog - Official Releases](https://reactnative.dev/blog)
- [Expo SDK 54 Changelog](https://expo.dev/changelog/sdk-54)
- [React Native Windows Documentation](https://microsoft.github.io/react-native-windows/)
- [Expo Push Notifications Documentation](https://docs.expo.dev/push-notifications/)

### Secondary (MEDIUM confidence)
- [Shopify Engineering: React Native New Architecture](https://shopify.engineering/react-native-new-architecture)
- [Ably: WebSocket Authentication](https://ably.com/blog/websocket-authentication)
- [Ably: Chat Architecture Message Ordering](https://ably.com/blog/chat-architecture-reliable-message-ordering)
- [Stream: Real-time AI Agents Latency](https://getstream.io/blog/realtime-ai-agents-latency/)

### Tertiary (LOW confidence)
- Individual Medium posts on platform-specific patterns (validate during implementation)
- GitHub issue discussions on WebSocket background handling (problem identification, not solutions)

---
*Research completed: 2026-01-20*
*Ready for roadmap: yes*
