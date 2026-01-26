# Phase 8: Desktop Expansion - Context

**Gathered:** 2026-01-26
**Status:** Ready for planning

<domain>
## Phase Boundary

Native macOS and Windows clients with feature parity to mobile. Apps share the React Native codebase (React Native Windows/macOS). All core features work identically: messaging, LLM participation, thread forking, genealogy visualization.

</domain>

<decisions>
## Implementation Decisions

### Window behavior
- Multiple windows supported — different rooms can open in separate windows
- System tray (Windows) and dock menu (macOS) with quick actions: minimize to tray, unread count, quick room switching
- Minimal native menus — just essentials (Quit, Preferences), most actions stay in-app
- Window size/position remembered as single default (app opens at last used size/position)

### Input adaptation
- Essential keyboard shortcuts only: Cmd/Ctrl+N (new room), Cmd/Ctrl+F (search), Cmd/Ctrl+Enter (send)
- Rich right-click context menus on messages: Copy, Fork from here, Reply, Quote (mirrors mobile long-press)
- Hover states reveal action buttons on messages (Fork, React, Copy) — Slack/Discord pattern
- Tab navigation limited to input fields only (not full accessibility keyboard nav)

### Platform conventions
- Native title bars on both platforms — standard OS window chrome
- Unified visual look across macOS and Windows — Dialectic brand consistency over platform adaptation
- Auto-detect modifier keys: Cmd on macOS, Ctrl on Windows — standard platform behavior
- Unified thin overlay scrollbars on both platforms

### Desktop-specific UX
- Native OS notifications (Notification Center on macOS, Action Center on Windows)
- Collapsible sidebar for room navigation — can hide for focused view, toggle to show
- Centered max-width chat layout on wide screens — no side panels
- Drag-and-drop file attachments supported

### Claude's Discretion
- Exact tray/dock menu items and organization
- Specific hover animation timing
- Scrollbar fade behavior
- Window minimum size constraints

</decisions>

<specifics>
## Specific Ideas

- System tray should feel like Slack's — unread indicator visible, quick access to rooms
- Hover actions similar to Discord message hover — subtle, doesn't clutter the UI
- Collapsible sidebar like VS Code's — smooth toggle, remembers state

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 08-desktop-expansion*
*Context gathered: 2026-01-26*
