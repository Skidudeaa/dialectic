# Project Milestones: Dialectic

## v1.0 Mobile MVP (Shipped: 2026-01-25)

**Delivered:** Cross-platform mobile collaborative workspace where two humans and an LLM co-reason together in real-time, with forking, genealogy, and configurable LLM interjection.

**Phases completed:** 1-7 (35 plans total)

**Key accomplishments:**

- Cross-platform mobile foundation with Expo SDK 54, EAS Build, and CI/CD pipeline
- Complete authentication system (JWT, Argon2, email verification, biometric unlock with PIN fallback)
- Real-time WebSocket messaging with presence, typing indicators, and auto-reconnection with gap sync
- LLM participation with streaming responses, @Claude mentions, and thinking indicators
- Local-first session history with SQLite FTS5 search, pagination, and session restoration
- Push notifications with deep linking, rich previews, and server-synced badge counts
- Dialectic differentiators: thread forking, cladogram genealogy, and configurable LLM heuristics (quiet/balanced/active)

**Stats:**

- ~9,975 lines of TypeScript (mobile app code)
- 7 phases, 35 plans
- ~152 commits
- 5 days from start to ship (2026-01-20 → 2026-01-25)

**Git range:** `docs(01): capture phase context` → `docs(07): complete dialectic-differentiators phase`

**What's next:** v1.1 Desktop — macOS and Windows clients via React Native

---
