# DECISIONS.md — Web Layer Design Decisions

## Auth: SHA-256 instead of bcrypt
**Decision:** Use hashlib SHA-256 for password hashing instead of passlib+bcrypt.
**Why:** passlib's bcrypt backend has version conflicts with Python 3.12's bundled bcrypt module. This is a two-user dev workspace with hardcoded users — no registration, no brute-force surface. SHA-256 is stdlib-only and avoids the dependency conflict entirely.

## State: File-based JSON/JSONL instead of SQLite
**Decision:** All web state (rooms, messages, journal, predictions) stored as JSON files and JSONL append logs in web/data/.
**Why:** Matches existing project patterns (outcomes/trades/*.jsonl, books/*.json). File locking via fcntl handles concurrent access. The data volume is tiny (two users, dozens of rooms). Adding SQLite would break the "zero external deps" ethos of the existing codebase.

## sys.path manipulation instead of package restructure
**Decision:** web/main.py inserts tools/ subdirectories into sys.path at startup.
**Why:** The spec explicitly forbids restructuring existing modules into packages. tools/ modules use relative imports and expect their parent on sys.path. This is the sanctioned approach.

## Tailwind v4 @utility instead of @layer components
**Decision:** Custom CSS classes use `@utility` directives instead of `@layer components` with `@apply`.
**Why:** Tailwind CSS v4 changed how `@apply` works inside `@layer components` — you can't reference custom classes defined in the same layer. `@utility` is the v4-native approach.

## OpenRouter for multi-model LLM access
**Decision:** All LLM calls go through OpenRouter's unified API.
**Why:** Single API key, single endpoint for Claude, GPT-4o, Llama, Gemini. Avoids managing four separate API integrations. Model selection via @mention syntax in chat.

## WebSocket auth via first message
**Decision:** WebSocket connections send JWT token as the first text message after connect.
**Why:** WebSocket protocol doesn't support custom headers in browser. Query string tokens are logged by proxies. First-message auth is the standard pattern for browser WebSocket auth.

## Right panel as overlay on iPad (<1024px)
**Decision:** Sidebar and right panel switch to absolute-positioned overlays on narrow screens.
**Why:** Three-panel layout doesn't fit iPad portrait (768px) or landscape (1024px) without squeezing the center chat. Overlay panels preserve full chat width while keeping context accessible via toggle buttons.
