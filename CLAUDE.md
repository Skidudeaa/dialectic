# CLAUDE.md

Guidance for Claude Code working in this repository.

## What this monorepo is

**Dialectic** — a collaborative dialogue engine where two humans and an LLM
co-reason in real time. The LLM is a participant, not an assistant: it decides
when to speak, checks live market data with tools, remembers with attribution,
and follows up on silence. One product, three co-projects:

| Dir | What | Runtime |
|---|---|---|
| `dialectic/` | The product: FastAPI backend + React PWA | `dialectic.service`, :8002, Postgres |
| `trading/` | tradingDesk: causal-DAG thesis engine + live data service | `tradingdesk.service`, :8006 (loopback), SQLite at `/var/lib/tradingdesk/` |
| `cc-sidecar/` | Claude Code observability daemon (donor of the FSM/StateSource patterns now in dialectic's `llm/participation_fsm.py`) | optional local daemon |

`packages/` (React Native) is **frozen** — cannot reach production; the PWA is
the reach strategy. `docs/` holds the vision, quarter plan + Amendment 1, and
handoffs. `dialectic/TODOS.md` is the task board.

## Commands

```bash
# dialectic backend (port 8002; env from dialectic/.env)
cd dialectic && PORT=8002 python3 run.py
cd dialectic && python3 -m pytest tests/ -q          # 790 tests

# dialectic frontend (React app — the only live frontend)
cd dialectic/frontend/app && npm run dev

# tradingDesk
cd trading && python3 -m pytest --collect-only -q    # 1325 collected
uvicorn web.main:app --port 8006                     # see trading/README.md
```

## Deploy (house rules — read before touching production)

- **Both systemd units run their git working trees.** A restart deploys
  whatever is on disk. Never restart with uncommitted edits.
- Deploy is three independent steps, in order: **migration** (`psql`, verify
  `\d`) → **backend restart** (`systemctl restart dialectic`, verify `/health`)
  → **frontend release** (build → `/var/www/dialectic-releases/<ts>-<name>` →
  flip `/var/www/dialectic-current` symlink → `systemctl reload nginx`).
- Auth-touching changes: tradingDesk first, THEN the dialectic frontend flip.
- `journalctl --since` parses LOCAL time; app logs stamp UTC.
- tradingDesk's SPA answers unknown GETs with 200+HTML — check content-type,
  never just the status code.
- Docs are amended **beside**, never silently edited (dated stamps).

## Architecture essentials

- **Event sourcing**: append-only `events` table is the source of truth;
  everything else is derivable.
- **The LLM participant**: `llm/orchestrator.py` (three paths — @Claude
  streaming, heuristic non-streaming, forced) → `llm/tool_loop.py` over an
  11-tool registry (`llm/tools.py`; provoker/protocol/annotator never get
  tools) → `llm/self_model.py` decision log + `llm/participation_fsm.py`
  conversation state machine with confidence tiers.
- **The clock**: `dialectic/scheduler.py` — advisory-locked asyncio jobs on the
  `scheduled_job_runs` ledger (double-fire-proof), interval buckets + wall-clock
  daily slots. Jobs: trading reconcile/watchdog, morning brief
  (`llm/night_shift.py`, 07:00 CT), silence sweep (`llm/silence_sweep.py`, 60s).
- **Memory**: `memory/manager.py` — three-lane RRF recall (dense + FTS +
  speaker), write-path dedup, supersession with history.
- **The seam**: tradingDesk's coordinator pushes v3 snapshots on change +
  hourly heartbeat; dialectic pulls on a 15-min reconcile and calls read-only
  bridge endpoints (`X-Service-Token`) for tools. Auth bridge: shared HS256
  secret; td maps dialectic JWTs via `DIALECTIC_USER_MAP`.
- **Key tables**: `events`, `rooms` (+`linked_book_id`, `trading_config`),
  `threads`, `messages` (+`metadata`), `memories`, `attachments`,
  `llm_decisions`, `llm_participation_state`, `scheduled_job_runs`,
  `web_push_subscriptions`. `dialectic/schema.sql` is the fresh-DB baseline;
  migrations numbered, `011` current.

## Code style

ARCHITECTURE/WHY/TRADEOFF docstrings on non-obvious decisions. Match the
surrounding file's idioms; minimal diffs; house-style commit messages with the
`--` em-dash flourish (see `git log --oneline`).
