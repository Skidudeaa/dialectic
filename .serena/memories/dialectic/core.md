# dialectic/ — module map

FastAPI backend (:8002, env from `dialectic/.env`, entry `run.py`) + React PWA (`frontend/app/`).

## Architecture spine
- **Event sourcing**: append-only `events` table is truth; all else derivable.
- **LLM participant**: `llm/orchestrator.py` — three paths: @Claude streaming, heuristic non-streaming, forced → `llm/tool_loop.py` over 11-tool registry in `llm/tools.py` (provoker/protocol/annotator roles never get tools) → `llm/self_model.py` decision log + `llm/participation_fsm.py` conversation FSM with confidence tiers (pattern donated by cc-sidecar).
- **Scheduler**: `scheduler.py` — advisory-locked asyncio jobs on `scheduled_job_runs` ledger (double-fire-proof); interval buckets + wall-clock daily slots. Jobs: trading reconcile/watchdog, morning brief (`llm/night_shift.py` 07:00 CT), silence sweep (`llm/silence_sweep.py`, 60s).
- **Memory**: `memory/manager.py` — three-lane RRF recall (dense + FTS + speaker), write-path dedup, supersession with history.
- **Trading seam (consumer side)**: pulls tradingDesk v3 snapshots on 15-min reconcile; calls read-only bridge endpoints with `X-Service-Token` for LLM tools (`llm/tradingdesk_client.py`, `llm/trading_curator.py`, `trading_watch.py`). Auth bridge: shared HS256 secret; td maps dialectic JWTs via `DIALECTIC_USER_MAP`.

## Key tables
`events`, `rooms` (+`linked_book_id`, `trading_config`), `threads`, `messages` (+`metadata`), `memories`, `attachments`, `llm_decisions`, `llm_participation_state`, `scheduled_job_runs`, `web_push_subscriptions`. `schema.sql` = fresh-DB baseline; migrations numbered, `011` current.

## Other dirs
`api/` routes, `transport/` (WS), `models.py`/`operations.py` (data layer), `analytics/`, `replay/`, `stakes/`, `migrations/`, `tests/` (~790).
Frontend state: zustand (`src/stores/appStore.ts`); shared types `src/types/index.ts`; API client `src/lib/api.ts`.
