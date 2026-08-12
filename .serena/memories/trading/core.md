# trading/ — tradingDesk module map

Causal-DAG thesis engine + live data service. FastAPI at :8006 (loopback), SQLite `/var/lib/tradingdesk/`, own `venv/`. Installed editable so `tools.` / `web.` import cleanly.

## Layout
- `web/` — FastAPI service: `main.py`, `auth.py` (JWT via python-jose), `routes/` (incl. `routes/bridge.py` — the dialectic-facing read-only bridge), `runtime/` (`coordinator.py` pushes v3 snapshots to dialectic on change + hourly heartbeat; `slow_feeds.py`), `adapters/`, `persistence/`, `observability/`, `ws.py`, `tv_webhook.py` (TradingView). Tests live beside code (`web/test_*.py`).
- `tools/` — stdlib-only runtime modules: `thesis_graph/` (thesisgraph CLI, graph engine), `data_fetch/` (fred, gdelt), `outcomes/` (lifecycle monitor, trade logging), `bridge/` (incl. `room_tokens.py` — room tokens come from ENVIRONMENT, not the books; post-fusion addition), `validation/`.
- Data dirs (git-tracked, churn with live pipeline): `books/` (thesis-graph JSON books), `snapshots/` (`*-latest.json`/`*-prev.json` per book), `outcomes/trades/` (JSONL trade ledger), `output/`, `research/`.
- `frontend/` — SPA (tailwind, react-router, vitest). Hotspots: `src/lib/types.ts`, `src/lib/api.ts` (RoomSocket, apiFetch, bridge exchange).

## Seam (provider side)
Coordinator pushes v3 snapshots to dialectic; dialectic pulls 15-min reconcile + calls bridge endpoints with `X-Service-Token`. Shared HS256 secret; dialectic JWTs mapped via `DIALECTIC_USER_MAP`. `DIALECTIC_ROOM_TOKENS` env holds the five original room tokens; rooms whose thesis was created FROM dialectic (Create Thesis flow, 2026-08-11) register theirs at runtime into `/var/lib/tradingdesk/room-tokens.env` via the bridge's one write, `POST /api/bridge/room-token` — env wins on conflict, and the coordinator `adopt_book`s builder-saved books without a restart.

## Gotchas
- SPA answers unknown GETs 200+HTML — check content-type when probing.
- Snapshot/ledger files churn from the live pipeline — expect them dirty in `git status`; they get committed as `chore(data)` snapshots.
- Pre-fusion standalone repo archived at `/root/_archive-tradingDesk-pre-fusion` (see `mem:core`).
