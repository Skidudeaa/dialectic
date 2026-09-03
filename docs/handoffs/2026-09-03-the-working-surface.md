# Handoff — 2026-09-03: the working surface is code

Owner, on being told the surface mocks were never ported: **"all of it."**
This session ported both mocks into the app. Read `dialectic/CLAUDE.md`'s
2026-09-03 amendment for the contract; this file is where each piece stands.

## What is live (after the deploy recorded in JOURNAL.md)

- **Scene `surface`**, default for a scheme room's root. Four panes:
  graph (ThesisDag + human-word slots + verbs + drop targets), atlas
  (SVG, `SurfaceAtlas`), conversation (`SurfaceConversation`, four shapes),
  updates tray (`SurfaceUpdates`). Files: `frontend/app/src/components/workspace/surface/`.
- **Anchors and refs on messages** (`metadata.anchor`, `metadata.refs`),
  both doors, in-room resolution, prompt rendering, tool-loop hoisting,
  reply inheritance. Backend tests: `tests/test_surface_anchor_refs.py`,
  `tests/test_surface_activity_pg.py`.
- **`GET /rooms/{id}/activity/daily`** and the two voice flags on
  `GET /rooms/{id}/capabilities`.

## What was decided, and why

- Dropping an update onto a node STAGES a ref on the next message and seeds
  the composer, rather than posting silently — conversation stays the base
  unit and a human word accompanies every attachment. The verbs
  (Speak to it / Ask Dialectic / Dispute / Bench ↗) insert into the composer
  through `MessageInput`'s new `composerRef`.
- Thesis nodes are not database rows, so an anchor is shape-validated only;
  refs to rows are resolved in SQL. `thesis_node` is the one non-row ref
  entity.
- The atlas is an SVG on purpose. Cesium stays behind the `World ↗` door.
- Human-word coverage is computed from the loaded message window (200).
  ponytail: a room with more than 200 messages since a node's last human
  word will show it as quiet; a server-side "last human word per node"
  projection is the upgrade path.

## Open, deliberately

- `search_transcript`, `get_thesis_state`, `evaluate_scenario`,
  `read_article` do not return refs yet; the three that do cover the
  stream rail's common case (readings, memories, scopes/contacts).
- Lanes/tree "whose move" and merge candidates are heuristics over the
  loaded window, not server truth.
- The Round card, proposals and protocol banners render only in Record;
  the surface's conversation pane renders plain messages (`SurfaceMessage`).
- Seven `tests/test_world_watch_pg.py` failures predate this work
  (reproduced on a clean HEAD worktree). Cause not investigated here.
