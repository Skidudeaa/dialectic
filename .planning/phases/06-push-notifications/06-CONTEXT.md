# Phase 6: Push Notifications - Context

**Gathered:** 2026-01-25
**Status:** Ready for planning

<domain>
## Phase Boundary

Background push notifications with badges and deep linking. Users receive timely notifications when messages arrive while app is backgrounded. Notification settings UI and advanced scheduling are out of scope.

</domain>

<decisions>
## Implementation Decisions

### Notification content
- Full message preview (up to ~200 chars) in notification body
- Title shows sender name only (room context implied)
- LLM messages distinguished with emoji/icon (🤖 or similar) before sender name
- No inline reply — tap opens app

### Badge behavior
- Badge count = number of rooms with unread messages (not total message count)
- Badge decreases when message scrolls into view (not on room open)
- Numeric badge per room in room list ("Philosophy (3)")
- Own messages sent from other devices auto-marked as read (multi-device sync)

### Sound & interruption
- Custom notification sound for Dialectic
- Distinct sound for Claude (LLM) messages vs human messages
- Multiple messages group/stack per room ("3 messages in Philosophy")
- Per-room mute option (disable all notifications from specific rooms)

### Deep link behavior
- Tap notification → scroll to exact message that triggered it
- Navigation replaces current view (not pushed on stack)
- Deleted message fallback: show brief toast "Message no longer available" then open room
- Grouped notification tap → expand to show individual messages, let user pick

### Claude's Discretion
- Exact custom sound design/selection
- Emoji choice for LLM indicator (🤖, 🧠, ✨, etc.)
- Grouping threshold timing
- Platform-specific implementation details (FCM vs APNs)

</decisions>

<specifics>
## Specific Ideas

- Badge is rooms-with-unread, not total-messages — keeps the number meaningful and not overwhelming
- LLM having a distinct sound reinforces that Claude is a participant, not just another notification
- Scroll-to-exact-message is important for context — user should land right where the notification was

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 06-push-notifications*
*Context gathered: 2026-01-25*
