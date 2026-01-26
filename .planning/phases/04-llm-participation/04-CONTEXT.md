# Phase 4: LLM Participation - Context

**Gathered:** 2026-01-25
**Status:** Ready for planning

<domain>
## Phase Boundary

LLM participates in conversations with streamed responses and can be explicitly summoned via @Claude mentions. Users see LLM responses stream in real-time with thinking indicators. Heuristic interjection (LLM speaking proactively) is Phase 7.

</domain>

<decisions>
## Implementation Decisions

### Streaming display
- Tokens appear as word chunks (matches API delivery pattern)
- Pulsing dots indicator (three animated dots like iMessage) while thinking
- Visible stop button appears during streaming to allow interruption
- On streaming failure: show partial response + retry button

### @Claude mentions
- Either autocomplete or direct typing works (@ shows popup, but @Claude typed directly also triggers)
- @Claude detected anywhere in message triggers response
- Styled as bold/colored text (not a chip)
- Brief visual pulse on the mention when detected in input
- Anyone in the conversation can @Claude
- Multiple rapid mentions batched into combined response (single response addresses all)
- Cancel button available while Claude is thinking (before streaming starts)

### Context window
- Smart truncation: fill context window, prioritizing recent messages + @Claude exchanges
- Context indicator on demand (tappable to see "Using last X messages")
- Truncation priority strategy: Claude's discretion
- For forked threads: include messages up to fork point, then child thread only

### Response presentation
- Claude messages have both different bubble color AND avatar/label
- Avatar is a friendly character illustration
- Claude messages appear centered (humans left/right)
- Full markdown rendering (bold, italic, lists, code blocks)

### Claude's Discretion
- Exact truncation algorithm and priority weighting
- Character illustration design
- Specific bubble color (should complement theme)
- Markdown rendering library choice
- Exact timing for "thinking" dots animation

</decisions>

<specifics>
## Specific Ideas

- Centered Claude messages create visual hierarchy that emphasizes the "third participant" nature
- Pulsing dots should feel conversational, not robotic
- The stop button should be unobtrusive but discoverable

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 04-llm-participation*
*Context gathered: 2026-01-25*
