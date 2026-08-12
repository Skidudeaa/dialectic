# dialectic/ — module map

FastAPI backend (:8002, env from `dialectic/.env`, entry `run.py`) + React PWA (`frontend/app/`).

## Architecture spine
- **Event sourcing**: append-only `events` table is truth; all else derivable.
- **LLM participant**: `llm/orchestrator.py` — three paths: @Claude streaming, heuristic non-streaming, forced → `llm/tool_loop.py` over 12-tool registry in `llm/tools.py` (read-only + proposal-shaped `draft_prediction`/`propose_thesis`; provoker/protocol/annotator roles never get tools) → `llm/self_model.py` decision log + `llm/participation_fsm.py` conversation FSM with confidence tiers (pattern donated by cc-sidecar).
- **Scheduler**: `scheduler.py` — advisory-locked asyncio jobs on `scheduled_job_runs` ledger (double-fire-proof); interval buckets + wall-clock daily slots. Jobs: trading reconcile/watchdog, morning brief (`llm/night_shift.py` 07:00 CT), silence sweep (`llm/silence_sweep.py`, 60s).
- **Memory**: `memory/manager.py` — three-lane RRF recall (dense + FTS + speaker), write-path dedup, supersession with history.
- **Trading seam (consumer side)**: pulls tradingDesk v3 snapshots on 15-min reconcile; calls bridge endpoints with `X-Service-Token` for LLM tools (`llm/tradingdesk_client.py`, `llm/trading_curator.py`, `trading_watch.py`). Auth bridge: shared HS256 secret; td maps dialectic JWTs via `DIALECTIC_USER_MAP`.
- **Thesis lifecycle (2026-08-11)**: `api/thesis_relay.py` — create (`POST /rooms/{id}/trading/thesis`, draft via `llm/thesis_drafter.py` + human Accept), retire (`DELETE`, td unbinds first, book survives, `thesis_state_current` memory invalidated). `propose_thesis` tool → `metadata.thesis_proposal` chat card seeds the panel form. Trading tab in the PWA is ALWAYS visible (conditional rendering was a reachability bug); rails are slide-over drawers below 1024px (`mobileDrawer` in appStore).
- **Commitment detection (P4, 2026-08-11)**: fire-and-forget on human messages in `transport/handlers.py` (`_detect_commitment_proposals`, needs `db_pool` — the per-message conn is released before Haiku answers); hits → `metadata.commitment_proposals` + `MESSAGE_METADATA` WS broadcast; Accept = ordinary `create_commitment` carrying `proposal_index`, server stamps `accepted`. Gate: `COMMITMENT_DETECTION_ENABLED`.

## Key tables
`events`, `rooms` (+`linked_book_id`, `trading_config`), `threads`, `messages` (+`metadata`), `memories`, `attachments`, `llm_decisions`, `llm_participation_state`, `scheduled_job_runs`, `web_push_subscriptions`. `schema.sql` = fresh-DB baseline; migrations numbered, `011` current.

## Other dirs
`api/` routes, `transport/` (WS), `models.py`/`operations.py` (data layer), `analytics/`, `replay/`, `stakes/`, `migrations/`, `tests/` (~790).
Frontend state: zustand (`src/stores/appStore.ts`); shared types `src/types/index.ts`; API client `src/lib/api.ts`.
