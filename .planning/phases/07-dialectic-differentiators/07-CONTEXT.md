# Phase 7: Dialectic Differentiators - Context

**Gathered:** 2026-01-25
**Status:** Ready for planning

<domain>
## Phase Boundary

Thread forking, genealogy visualization, and LLM heuristic interjection controls. Users can fork conversations from any message, view thread relationships in a cladogram, experience proactive LLM participation, and configure interjection behavior.

</domain>

<decisions>
## Implementation Decisions

### Fork Interaction
- Long-press message reveals context menu with "Fork from here" option
- After forking, navigate immediately to the new thread
- Forked thread shows collapsed summary: "Forked from [thread] at [message]" with expand option to load parent context
- Optional naming prompt when forking — allow skip, auto-generate from timestamp/fork message if skipped

### Genealogy Visualization
- Cladogram-style tree diagram (biological taxonomy style, not git graph)
- Accessible via dedicated "Branches" tab/screen in room navigation
- Show full tree by default — entire genealogy from root to all leaves
- Each node displays: thread name, timestamp, message count, and optional preview of fork point message

### LLM Interjection Behavior
- Subtle indicator distinguishes proactive interjections from summoned (@Claude) responses — small badge/label marking "unprompted"
- Stop button visible during streaming to allow users to cancel mid-response
- Provoker mode uses distinct persona: different name/avatar (e.g., "Claude ⚡") when in destabilizer mode
- Thinking indicator shown for 1-2 seconds before proactive response starts streaming

### Heuristic Configuration UI
- Presets for most users: "Quiet", "Balanced", "Active" with descriptions
- "Advanced" toggle reveals sliders for direct control (turn threshold, stagnation timeout, etc.)
- Global default + per-room override: settings in app settings, per-room override via room menu
- Global settings live in app settings under "Claude Behavior" section
- Per-room override accessible via room menu → "LLM Settings"
- No full disable option — minimum is "Quiet" preset (LLM still participates, just less often)

### Claude's Discretion
- Exact cladogram layout algorithm and styling
- Transition animations for fork navigation
- Specific slider ranges and defaults for advanced heuristic controls
- Stop button placement and styling during streaming
- Provoker persona name/avatar specifics beyond "Claude ⚡" example

</decisions>

<specifics>
## Specific Ideas

- Cladogram chosen over git-graph style — biological taxonomy feel, branches diverge from common ancestors
- Provoker mode should feel like a different "mood" of Claude, not a different entity entirely
- "Quiet" preset should still allow Claude to jump in on direct questions or stagnation, just with higher thresholds

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 07-dialectic-differentiators*
*Context gathered: 2026-01-25*
