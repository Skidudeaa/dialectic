# Roadmap: Dialectic

## Milestones

- ✅ **v1.0 Mobile MVP** — Phases 1-7 (shipped 2026-01-25)
- 🚧 **v1.1 Desktop** — Phase 8 (in progress)

## Phases

<details>
<summary>✅ v1.0 Mobile MVP (Phases 1-7) — SHIPPED 2026-01-25</summary>

- [x] Phase 1: Project Foundation (3/3 plans) — completed 2026-01-21
- [x] Phase 2: Authentication (5/5 plans) — completed 2026-01-20
- [x] Phase 3: Real-Time Core (6/6 plans) — completed 2026-01-25
- [x] Phase 4: LLM Participation (4/4 plans) — completed 2026-01-25
- [x] Phase 5: Session & History (7/7 plans) — completed 2026-01-25
- [x] Phase 6: Push Notifications (5/5 plans) — completed 2026-01-25
- [x] Phase 7: Dialectic Differentiators (5/5 plans) — completed 2026-01-25

See: `.planning/milestones/v1.0-ROADMAP.md` for full details

</details>

### 🚧 v1.1 Desktop (In Progress)

- [ ] **Phase 8: Desktop Expansion** - macOS and Windows clients via React Native

## Phase Details

### Phase 8: Desktop Expansion
**Goal**: Dialectic runs natively on macOS and Windows with feature parity to mobile
**Depends on**: Phase 7
**Requirements**: PLAT-03, PLAT-04
**Success Criteria** (what must be TRUE):
  1. App runs natively on macOS with platform-appropriate UI conventions
  2. App runs natively on Windows with platform-appropriate UI conventions
  3. All core features work identically to mobile (messaging, LLM, forking)
  4. Desktop apps share codebase with mobile (React Native Windows/macOS)
**Plans**: 9 plans

Plans:
- [x] 08-01-PLAN.md — Monorepo setup with Yarn Workspaces and shared app package
- [x] 08-02-PLAN.md — macOS workspace with react-native-macos and Xcode project
- [x] 08-03-PLAN.md — Windows workspace with react-native-windows and Visual Studio project
- [x] 08-04-PLAN.md — Platform service abstractions (secure storage, database, notifications)
- [x] 08-05-PLAN.md — macOS platform implementation (Keychain, SQLite, menu bar)
- [x] 08-06-PLAN.md — Windows platform implementation (MMKV, SQLite, WinRT notifications)
- [x] 08-07-PLAN.md — Desktop UX features (keyboard shortcuts, hover, context menu, drag-drop, sidebar)
- [x] 08-08-PLAN.md — Desktop visual polish (centered layout, scrollbars, window persistence)
- [x] 08-09-PLAN.md — Platform verification checkpoint

**Status:** Code complete, awaiting platform verification on actual macOS/Windows machines

## Progress

**Execution Order:**
Phase 8 builds on v1.0 Mobile MVP (Phases 1-7).

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Project Foundation | v1.0 | 3/3 | Complete | 2026-01-21 |
| 2. Authentication | v1.0 | 5/5 | Complete | 2026-01-20 |
| 3. Real-Time Core | v1.0 | 6/6 | Complete | 2026-01-25 |
| 4. LLM Participation | v1.0 | 4/4 | Complete | 2026-01-25 |
| 5. Session & History | v1.0 | 7/7 | Complete | 2026-01-25 |
| 6. Push Notifications | v1.0 | 5/5 | Complete | 2026-01-25 |
| 7. Dialectic Differentiators | v1.0 | 5/5 | Complete | 2026-01-25 |
| 8. Desktop Expansion | v1.1 | 9/9 | Verification pending | - |

---
*Roadmap created: 2026-01-20*
*Last updated: 2026-01-26 (v1.0 archived)*
