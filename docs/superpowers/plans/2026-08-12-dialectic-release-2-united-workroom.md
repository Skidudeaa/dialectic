# Release 2 — The United Workroom: build sheet

**Branch:** `claude/release-2-united-workroom` off `fc7ac68`
**Starts:** when Release 1's Task Group F is green. Not before.
**Authority:** design v2 §6–§7, §19.5; the living-workroom program's Release 2.

> **Not mine:** Release 1 groups D, E, F. Codex is building them in
> `.worktrees/release-1-workroom-foundation`. This branch touches nothing there.

---

## 1. Reconnaissance — observed, not assumed

Read-only against production, 2026-08-12 23:40.

| Entity | Population | Rooms holding it |
|---|---|---|
| Rooms | 23 | — |
| Messages | 296 across 24 threads | **11 of 23** |
| Active memories | 425 | 8 |
| Readings | 13 | **3** |
| Thesis (`linked_book_id`) | 5 books | 5 |
| Events | 5,938 | — |
| **Commitments** | **0** | 0 |
| **Proposals** (all 5 metadata slots) | **0** | 0 |
| **Research briefs** (`source='deep_dive'`) | **0** | 0 |

Message metadata keys in production, complete: `source` (29), `snapshot_timestamp`
(12), `snapshot_v` (12), `tools` (11), `url` (7), `origin_room` (7).
`source` values, complete: `trading_curator` 12, `night_shift` 10, `reading_echo` 7.

Message types, complete: `text` 247, `question` 44, `definition` 4,
`counterexample` 1.

### What this forces

1. **Twelve of twenty-three rooms are completely empty.** Emptiness is the
   product's normal state, not its edge case. Empty states carry the entire
   burden of "a new user understands this" and must be built first, not last.
2. **Do not build Judgment or Brief scenes.** They would render zero rows in
   every room in production. The program forbids a scene name that opens
   nothing; `IMPLEMENTED_WORKSPACE_SCENES` already handles approved-but-unbuilt
   names by falling back.
3. **Scenes shipped: House · Record · Bench · Library · Ledger.** Each has real
   population behind it.

---

## 2. The recomposition map

Ten flat tabs today: Users · Memory · Branches · Insights · Stakes · History ·
AI · Share · House · Trading. Where each goes, and what it costs:

| Today's tab | Component | LOC | Lands in |
|---|---|---|---|
| Trading | `trading/TradingPanel.tsx` | **715** | **Bench** — its empty state is already the create-thesis surface |
| Memory | `sidebar/MemoryPanel.tsx` | 232 | **Ledger** |
| Stakes | `stakes/CommitmentDashboard.tsx` | 201 | **Bench** (judgment folds in until it has population) |
| History | `replay/ReplayTimeline.tsx` | 128 | **Record** |
| Insights | `analytics/AnalyticsPanel.tsx` | 145 | **Record** |
| AI | `analytics/IdentityViewer.tsx` | 104 | **Ledger** (Dialectic's own papers, §7.7) |
| Branches | `sidebar/ThreadPanel.tsx` | 47 | navigation — rail `BranchTree`, not a scene |
| Users | `sidebar/UsersPanel.tsx` | 24 | room-wide rail |
| Share | `sidebar/SharePanel.tsx` | 69 | room-wide rail |
| House | `home/HomeSettingsPanel.tsx` | — | **House** (Home only) |

**Moved, not rewritten** (§7.2, §19.5). ~1,700 lines of working workflow — the
thesis create/draft/accept/retire lifecycle lives inside `TradingPanel` and must
stay functional through the move. That is the single highest-risk edit in this
release; it gets its own commit and its own browser proof.

---

## 3. Empty states — the primary teaching surface

One `SceneEmpty` contract: **what this place is · what lands here · how it gets
here · the on-ramp.** Every scene distinguishes three states, never collapsing
them (§7.5 — an empty automated run is not evidence that nothing happened):

```
unavailable   projection failed        → say so, offer retry
capable-empty room could hold this     → teach + on-ramp
populated     render objects
```

Draft copy, to be reviewed against the real surfaces:

- **Bench, no thesis** — "No thesis here yet. A thesis is the causal model this
  room argues about — Dialectic can draft one from what you've discussed, and
  you accept or reject it. [Draft a thesis]"
- **Bench, thesis live, nothing moved** — "Thesis live, 4 nodes. Nothing has
  fired since <time>." Never "no activity".
- **Library, empty** — "Nothing filed yet. Evidence lands here when you accept an
  article, or when Dialectic reads overnight against this thesis. [Paste a link]"
- **Ledger, empty** — "The room hasn't agreed anything yet. Facts land here when
  you save them or Dialectic records one — restate a fact and it supersedes the
  old version, keeping the history."
- **Record, empty** — replaces the current *"Start the dialogue / Claude will
  join the conversation"*, which is both uninformative and **factually stale**:
  A5 renamed the participant to Dialectic.

---

## 4. The capability map — replaces `HelpDialog`

Today's help modal is hardcoded prose, stale on the participant name
("Claude's hands and eyes") and on content ("Five live theses"). It is the only
place the product explains itself.

Replace with a map rendered from **real state**. Signals verified to exist:

- Room: `linked_book_id`, `trading_config`, `auto_interjection_enabled`,
  `interjection_turn_threshold` (`GET /rooms/{id}/settings`).
- Scheduler: jobs register with `enabled_env` — `NIGHT_SHIFT_ENABLED` (on),
  `WIRE_ENABLED` (off), `NEWS_DIGEST_ENABLED` (off), `READING_ECHO_ENABLED`
  (off), `PREDICTION_WATCH_ENABLED` (off), `CLAIM_CHECK_ENABLED` (on),
  `DEEP_DIVE_ENABLED`, `COMMITMENT_DETECTION_ENABLED`.

**Needs one new read-only endpoint** exposing which jobs are registered and
enabled, so the map cannot drift from the runtime. Reading the scheduler's own
registry — not a second hardcoded list — is what makes it accurate.

---

## 5. Build order

1. `SceneEmpty` + the three-state contract, with tests.
2. `WorkspaceObjectList` / `ObjectCard` over C's `WorkspaceObject`; navigation
   through `useRoomNavigation` by room/branch, never the server's destination
   string (B's rule).
3. Extend `IMPLEMENTED_WORKSPACE_SCENES`; `WorkspaceSceneFrame` stops forcing
   `record` outside Home root; `SceneSwitcher` gains real labels.
4. Ledger (`MemoryPanel` + `IdentityViewer`) — largest population, lowest risk.
5. Library (13 readings) — reading/twin renders **once**.
6. Bench (`TradingPanel` move) — highest risk, own commit, own browser proof.
7. Record (`ReplayTimeline` + `AnalyticsPanel` + search).
8. Right rail becomes scene-contextual; every panel stays reachable in mobile
   drawers — no feature becomes desktop-only.
9. Capability map + endpoint; identity accuracy pass through `productIdentity.ts`.

## 6. Fences that must stay green

House movement never exceeds the all-members intersection · human House and
Dialectic prompt context stay projection-identical · reading + memory twin
renders once · thesis create/draft/accept/retire intact · personal promotion
never becomes shared state · Home still refuses a thesis · exactly 1024 is
desktop · every panel reachable at 390.

Browser results are worthless until the service worker is unregistered and
caches cleared — workbox served stale JS during Task Group A and made a working
fix read as broken.
