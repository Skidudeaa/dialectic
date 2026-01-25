# Phase 3: Real-Time Core - Context

**Gathered:** 2026-01-25
**Status:** Ready for planning

<domain>
## Phase Boundary

Real-time messaging with presence awareness, typing indicators, and graceful reconnection handling. Users see messages appear instantly, know when others are typing or away, and the app recovers seamlessly from network interruptions. LLM streaming and heuristic interjection are separate phases.

</domain>

<decisions>
## Implementation Decisions

### Presence states & transitions
- Three states: Online, Away, Offline
- Auto-Away after 5 minutes of inactivity
- App backgrounded transitions to Away immediately, then Offline after 5 minutes
- Display: Both dot indicator AND text label on participant avatars
- LLM shows presence when active (Online when processing, neutral otherwise)
- Manual Away toggle available; Online/Offline are automatic
- Offline users show relative "last seen" time ("Last seen recently" / "Last seen today")
- Presence changes are silent — no toasts or notifications

### Typing indicator behavior
- Animated dots in message area (classic "..." animation)
- Multiple typers: stacked dot animations, one per person typing
- Indicator disappears after 3 seconds of no input
- LLM uses same typing indicator as humans when generating

### Message delivery feedback
- Three states: Sent, Delivered, Read
- Display via subtle color change on message bubble (not checkmarks or text)
- Failed messages: red indicator + retry button
- Read receipts show WHO read the message (but not timestamp)

### Reconnection experience
- Connection loss shown inline in chat ("Connection lost" message)
- Users can compose and send messages while offline — queued for later
- On reconnect: "New messages" divider shows where user left off
- Queued offline messages auto-send in order upon reconnection

### Claude's Discretion
- Exact colors for delivery states
- Animation timing and easing
- Retry logic and backoff strategy
- Message queue persistence strategy

</decisions>

<specifics>
## Specific Ideas

- Presence should feel lightweight — silent updates, no interruptions
- Stacked typing indicators give visual feedback without taking much space
- Color-based delivery status is more subtle than checkmarks — matches Dialectic's conversational feel

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 03-real-time-core*
*Context gathered: 2026-01-25*
