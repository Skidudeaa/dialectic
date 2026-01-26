# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-01-20)

**Core value:** Real-time collaborative creation with an LLM as a first-class participant
**Current focus:** Phase 7 - Dialectic Differentiators

## Current Position

Phase: 7 of 8 (Dialectic Differentiators)
Plan: 1 of 5 in current phase
Status: In progress
Last activity: 2026-01-26 - Completed 07-01-PLAN.md (Backend Genealogy and Settings)

Progress: [████████░░] 78%

## Performance Metrics

**Velocity:**
- Total plans completed: 31
- Average duration: 2.5 min
- Total execution time: 1.3 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-project-foundation | 3 | 6 min | 2 min |
| 02-authentication | 5 | 19 min | 3.8 min |
| 03-real-time-core | 6 | 13 min | 2.2 min |
| 04-llm-participation | 4 | 13 min | 3.25 min |
| 05-session-history | 7 | 15 min | 2.1 min |
| 06-push-notifications | 5 | 14 min | 2.8 min |
| 07-dialectic-differentiators | 1 | 4 min | 4 min |

**Recent Trend:**
- Last 5 plans: 06-02 (2 min), 06-03 (2 min), 06-04 (3 min), 06-05 (2 min), 07-01 (4 min)
- Trend: Stable

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Init]: React Native with Expo selected as cross-platform framework (per research)
- [Init]: Mobile-first development, desktop expansion in Phase 8
- [01-01]: Used SDK 54 (latest stable) instead of SDK 52 from research
- [01-01]: Used --legacy-peer-deps for @testing-library/react-native (React 19 peer conflict)
- [01-02]: Build job uses --no-wait to avoid blocking CI on EAS build completion
- [01-02]: Path filters limit CI runs to mobile/ changes only
- [02-01]: 6-digit verification codes (matches TOTP standard, more secure)
- [02-01]: 5 device limit per user (upper bound of 3-5 range per CONTEXT.md)
- [02-01]: No refresh token rotation (simpler, can add later if needed)
- [02-02]: expo-secure-store plugin added to app.config.js for keychain access
- [02-02]: API interceptor queues requests during token refresh to prevent race conditions
- [02-03]: Zod v4 for form validation with TypeScript type inference
- [02-03]: Generic FormInput with Controller for type-safe controlled inputs
- [02-04]: Reused full auth screens from 02-03 rather than placeholders (already existed)
- [02-05]: 6-digit PIN for consistency with TOTP verification code length
- [02-05]: 3 biometric attempts before PIN fallback (security vs UX balance)
- [02-05]: 15-minute background timeout per CONTEXT.md spec
- [03-01]: PRESENCE_BROADCAST uses same wire value as PRESENCE_UPDATE for client simplicity
- [03-01]: Receipts sent only to message sender, not broadcast to room
- [03-01]: Presence status validated to online/away/offline only
- [03-02]: Singleton WebSocket service pattern (one connection per room)
- [03-02]: 30-second heartbeat interval for connection keep-alive
- [03-02]: Ref-based onMessage to avoid reconnection on callback changes
- [03-03]: 5-minute inactivity timeout for auto-away (per CONTEXT.md)
- [03-03]: Manual away persists through activity (requires explicit setOnline)
- [03-03]: PresenceProvider at app root ensures presence tracked from app launch
- [03-04]: 500ms debounce for typing_start per RESEARCH.md spec
- [03-04]: 3 second auto-stop timeout per CONTEXT.md
- [03-04]: ReturnType<typeof setTimeout> for cross-platform timer types
- [03-05]: MMKV for offline queue (30-100x faster than AsyncStorage)
- [03-05]: 100-message queue limit to prevent unbounded memory growth
- [03-05]: Gap sync first on reconnect, then flush queued messages
- [03-06]: Color-based delivery status per CONTEXT.md (gray->light blue->blue->green, red for failed)
- [03-06]: Client ID correlation for matching optimistic updates to server acknowledgments
- [03-06]: Sequence-based insertion for gap sync message ordering
- [04-01]: 100k token context window with 4k reserved for output
- [04-01]: Priority scoring for truncation: recency > @Claude > LLM responses > questions
- [04-01]: Always include last 10 messages regardless of priority score
- [04-01]: tiktoken for token counting with 4-char fallback
- [04-02]: Handlers object pattern for useLLM WebSocket event wiring
- [04-02]: State scoped to active thread for multi-thread support
- [04-02]: LLM events dual dispatch (callback AND onMessage)
- [04-03]: Custom Animated API for thinking dots instead of library dependency
- [04-03]: Indigo (#6366f1) as Claude's brand color throughout LLM UI
- [04-03]: Separate LLMMessageBubble vs extending MessageBubble for clear separation
- [04-04]: react-native-controlled-mentions v3 API (triggersConfig, onTriggersChange)
- [04-04]: Case-insensitive @Claude detection with word boundary regex
- [04-04]: External suggestions rendering via onTriggersChange callback
- [05-02]: expo-sqlite v16 with Drizzle ORM for type-safe local database
- [05-02]: FTS5 with porter unicode61 tokenizer for local full-text search
- [05-02]: Babel inline-import plugin for bundling SQL migrations
- [05-02]: Triggers for automatic FTS sync on insert/update/delete
- [05-03]: Separate MMKV instance for session data (id: session-storage)
- [05-03]: 500ms debounce for draft saves per RESEARCH.md guidance
- [05-03]: ReturnType<typeof setTimeout> for cross-platform timer types
- [05-04]: 500-message limit per thread matches CONTEXT.md spec
- [05-04]: Eviction by sequence (oldest first) maintains recent availability
- [05-04]: Cache-first loading with server fallback for offline+fresh data
- [05-04]: loadOlder checks cache before server to minimize API calls
- [05-05]: FlashList v2 API (estimatedItemSize removed, auto-measures items)
- [05-05]: maintainVisibleContentPosition with autoscrollToTopThreshold:10 for stable upward scroll
- [05-05]: speakerType field added to Message for LLM message type detection
- [05-06]: 300ms debounce for search queries per RESEARCH.md guidance
- [05-06]: expo.getAllSync for raw FTS5 queries (Drizzle ORM doesn't support)
- [05-06]: Local-first search with server extension for full history
- [05-06]: BM25 scoring for relevance ranking
- [05-07]: Database migrations run during loading state (before auth check completes)
- [05-07]: Restoration triggers only after: db ready AND auth complete AND signed in AND not locked AND email verified
- [05-07]: Database errors are non-fatal (app continues with warning)
- [06-02]: 880Hz for human notification, 659Hz for LLM (distinct sounds per CONTEXT.md)
- [06-02]: Different vibration patterns: human [0,250,250,250] vs LLM [0,100,100,100,100,100]
- [06-02]: Purple (#8b5cf6) light color for LLM messages to match Claude brand
- [06-02]: Re-register token on every call (prevents stale tokens per RESEARCH.md)
- [06-01]: Badge count = rooms with unread (not total message count) per CONTEXT.md
- [06-01]: LLM messages use robot emoji prefix in notification title
- [06-01]: DeviceNotRegisteredError marks tokens inactive (not deleted)
- [06-01]: Token upsert pattern for re-registration with ON CONFLICT DO UPDATE
- [06-03]: Foreground suppression checks WebSocket connection AND presence status
- [06-03]: Sentinel UUID (all zeros) for LLM sender_id to avoid self-exclusion
- [06-03]: Push failures logged but don't block message delivery (fire and forget)
- [06-03]: Lazy import of notification service to avoid circular imports
- [06-04]: Foreground suppression: notifications suppressed when viewing same room
- [06-04]: 300ms delay on cold start navigation to ensure router ready
- [06-04]: NotificationProvider placed after LockProvider, before PresenceProvider
- [06-04]: currentRoomId added to websocket-store for foreground suppression
- [06-05]: seenMessageIds not persisted (session-based for scroll detection)
- [06-05]: 50% visible for 500ms counts as message "seen"
- [06-05]: Badge sync on app foreground via AppState listener
- [06-05]: Backend needs GET /notifications/badge endpoint (noted for follow-up)
- [07-01]: Recursive CTE for genealogy with max_depth limit (default 20)
- [07-01]: Class-level _active_streams dict for task tracking (single-server, Redis for scale)
- [07-01]: Settings validation: turn threshold 2-12, novelty threshold 0.3-0.95

### Pending Todos

- User setup required: Expo account and EXPO_TOKEN for EAS builds (see 01-02-SUMMARY.md)
- Deferred: iOS/Android manual testing for Phase 1 (automated checks pass, user will verify later)
- Deferred: Session restore manual verification to Phase 8 (see 05-07-SUMMARY.md)

### Blockers/Concerns

Research flags for later phases:
- Phase 8 (Desktop): React Native Windows/macOS ejection process may need updated docs

## Session Continuity

Last session: 2026-01-26
Stopped at: Completed 07-01-PLAN.md (Backend Genealogy and Settings)
Resume file: None

---
*State initialized: 2026-01-20*
*Last updated: 2026-01-26*
