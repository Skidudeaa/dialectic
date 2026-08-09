# BUGS.md — Issues Found During Phase 6 Audit

## Fixed
1. **Vite proxy pointing to port 8000** — Backend runs on 8005 due to port conflict. Fixed proxy in vite.config.ts.
2. **`/api/market/watchlist` 500 error** — instruments in book JSON is `dict[nodeId, list[dict]]`, not `list[dict]`. Fixed in `web/adapters/market.py` with `_iter_instruments()` helper.
3. **LLM error not visible in chat** — When OPENROUTER_API_KEY is missing or invalid, the error was saved to JSONL but not broadcast via WebSocket. Fixed: now broadcasts the system error message via WS so it appears inline.
4. **LLM error handler only catches HTTPException** — OpenRouter 400 errors propagate as generic exceptions too. Fixed: now catches all exceptions.

## Noted (not bugs)
- Sidebar auto-collapses on viewport < 1024px — working as designed for iPad responsive.
- Watchlist prices show "--" — expected when no live fetch has been done. Prices populate when user clicks fetch-prices.
- Empty panels for predictions/journal — expected when no data exists yet.
