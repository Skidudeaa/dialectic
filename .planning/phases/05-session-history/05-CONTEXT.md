# Phase 5: Session & History - Context

**Gathered:** 2026-01-25
**Status:** Ready for planning

<domain>
## Phase Boundary

Conversation persistence, pagination, and search. Users can access past conversations, load older messages, and search within/across conversations. Creating conversations and thread forking are separate phases.

</domain>

<decisions>
## Implementation Decisions

### History Loading
- Load last 50 messages when opening a conversation
- Spinner at top when paginating older messages, maintain scroll position after load
- Entire conversation history accessible (no time limit cutoff)
- Jump + local scroll when navigating to old messages (teleport nearby, then smooth scroll to exact message)

### Local Persistence
- Cache 500 most recent messages per conversation on device
- Offline mode: show cached messages with offline banner, disable send
- Manual cache clear in settings with storage size displayed
- Auto-fetch gap when reconnecting (seamless sync of missed messages)

### Search Experience
- Default scope: current conversation first, option to expand to all
- Results displayed as list of message snippets with highlighted matches
- Filters: date range and sender (human vs Claude)
- Tapping result jumps to message in context with surrounding conversation visible

### Session Continuity
- App reopens to last active conversation
- Exact scroll position remembered within conversation
- Auto-save draft: unsent text persists as draft, can manage drafts
- Resume to same forked thread if that's where user was

### Claude's Discretion
- Exact page size for pagination API calls
- Cache eviction strategy when exceeding 500 messages
- Search result ranking algorithm
- Draft storage mechanism (local vs synced)

</decisions>

<specifics>
## Specific Ideas

No specific product references mentioned — open to standard approaches.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 05-session-history*
*Context gathered: 2026-01-25*
