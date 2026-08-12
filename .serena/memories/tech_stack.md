# Tech stack

## Backends (Python, requires-python >=3.10)
- `dialectic/`: FastAPI 0.109 (pinned) + uvicorn, asyncpg → **PostgreSQL with pgvector** (DB user is `root`, not `postgres`), pydantic 2.x, pyjwt, pwdlib[argon2], anthropic + openai SDKs, tiktoken, redis, pywebpush, websockets 12. Deps in `dialectic/requirements.txt` (pinned) + `dialectic/pyproject.toml`.
- `trading/`: FastAPI >=0.115 + uvicorn, python-jose (JWT), httpx. **SQLite** at `/var/lib/tradingdesk/`. Editable install (`pip install -e .`) makes `tools/` and `web/` importable — no sys.path hacks. Own `venv/` inside `trading/` (systemd ExecStart uses `trading/venv/bin/uvicorn`).
  - Convention: `trading/tools/` modules are **stdlib-only at runtime**; web deps only needed for the FastAPI layer. CLI entry point `thesisgraph` preserved for cron jobs.
- `cc-sidecar/`: Python daemon, own schema.sql.

## Frontends (both Vite + TypeScript + React 18)
- `dialectic/frontend/app/` — the live product frontend (PWA). Deps: zustand (state), marked + dompurify (markdown), no CSS framework. Legacy `dialectic/frontend/app.html` still exists but React app is the only live frontend.
- `trading/frontend/` — tradingDesk SPA. Deps: tailwindcss 4 (@tailwindcss/vite), react-router-dom, react-markdown, lucide-react. Has **vitest** (dialectic frontend does not).

## Test frameworks
- Python: pytest + pytest-asyncio (dialectic ~790 tests; trading ~1359 collected).
- TS: vitest only in `trading/frontend`; eslint in both frontends.

## packages/ (frozen)
Yarn workspaces `@dialectic/{mobile,app,macos,windows}` — React Native. Frozen, not shipped.
