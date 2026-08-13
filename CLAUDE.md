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
cd trading && python3 -m pytest --collect-only -q    # 1359 collected
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
  streaming, heuristic non-streaming, forced) → `llm/tool_loop.py` over a
  12-tool registry (`llm/tools.py`; provoker/protocol/annotator never get
  tools) → `llm/self_model.py` decision log + `llm/participation_fsm.py`
  conversation state machine with confidence tiers.
- **The clock**: `dialectic/scheduler.py` — advisory-locked asyncio jobs on the
  `scheduled_job_runs` ledger (double-fire-proof), interval buckets + wall-clock
  daily slots. Jobs: trading reconcile/watchdog, morning brief
  (`llm/night_shift.py`, 07:00 CT), silence sweep (`llm/silence_sweep.py`, 60s).
- **Memory**: `memory/manager.py` — three-lane RRF recall (dense + FTS +
  speaker), write-path dedup, supersession with history.
- **The seam**: tradingDesk's coordinator pushes v3 snapshots on change +
  hourly heartbeat; dialectic pulls on a 15-min reconcile and calls bridge
  endpoints (`X-Service-Token`) for tools — read-only except two lifecycle
  writes: `POST /api/bridge/room-token` (create-thesis registers the push
  credential into `/var/lib/tradingdesk/room-tokens.env`, no restart) and
  `POST /api/bridge/room-unbind` (retire; the book survives). Auth bridge:
  shared HS256 secret; td maps dialectic JWTs via `DIALECTIC_USER_MAP`.
- **The workroom projection** (live in production since 2026-08-13):
  `dialectic/workspace_objects.py` gives readings, briefs, the thesis,
  commitments, proposals, dossier entries and the Record one read-only shape —
  **adapters over the entities that already exist, never a universal artifact
  table**. Two entities keep a deliberate memory twin that must project as one
  object (a reading + its `reading:` memory; a thesis + its
  `thesis_state_current` slot). Shipped as Release 1 with NO migration — it
  projects entities that already exist, so its deploy was a backend restart
  plus a frontend flip. `docs/superpowers/plans/…-release-1-sdd-ledger.md` is
  the canonical record of what landed and what was deliberately left open.
- **Key tables**: `events`, `rooms` (+`linked_book_id`, `trading_config`,
  `is_home`), `threads`, `messages` (+`metadata`), `memories`, `attachments`,
  `room_memberships` (+`can_manage_home`), `llm_decisions`,
  `llm_participation_state`, `scheduled_job_runs`, `web_push_subscriptions`.
  `dialectic/schema.sql` is the fresh-DB baseline; migrations numbered,
  `013` current (Home Base — live in production since 2026-08-12 with the
  two founders activated; membership changes go through `api/home.py` or
  the reviewed deploy scripts, never ad-hoc SQL).

## Amendment 2026-08-13 — corrections from the architecture map

Drawing `docs/diagrams/dialectic-architecture.drawio` meant sourcing every
label from the running code instead of from this file. Five claims above had
drifted. The originals are left in place per the amend-beside rule; **prefer
what follows.**

- **The tool registry is 15 tools, not the "12-tool registry" above.** Eight
  tradingDesk (`get_live_quotes`, `get_polymarket_odds`, `get_thesis_state`,
  `diff_thesis_last_hour`, `evaluate_scenario`, `get_open_trades`,
  `get_morning_brief`, `get_thesis_news`) + seven dialectic (`search_memories`,
  `search_transcript`, `draft_prediction`, `propose_thesis`, `read_article`,
  `save_reading`, `search_reading`). `tests/test_tools_registry.py:70` already
  asserts `len(registry.tools) == 15`. Note also that `build_registry` adds all
  fifteen **unconditionally** — its docstring's "room-scoped" claim is not what
  the code does; the persona exclusion (provoker/protocol/annotator) is enforced
  elsewhere. Kill switch: `DIALECTIC_TOOLS_ENABLED`.
- **Nine scheduled jobs, not the four listed.** Beyond reconcile/watchdog,
  morning brief and silence sweep: `scheduler_heartbeat` (600s),
  `thesis_news_digest` (05:30 CT, `llm/news_night.py`), `wire_watch` (900s,
  `llm/wire.py`), `prediction_deadline_watch` (3600s,
  `llm/prediction_watch.py`), `reading_echo` (1800s, `llm/reading_echo.py`).
  Each has its own `*_ENABLED` flag; all are registered in the `api/main.py`
  lifespan (~:254-265) and only when `db_pool` exists. Tick is 30s.
- **Migrations run to `016`, not `013`.** Verified against the live DB, not the
  file listing: `reading_items` exists (014 applied) and `memories.embedding` is
  1024-wide (016 applied). 015 is `room_watchlist`. `013` remains correct only
  as "the Home Base migration", not as "the latest one". Note `reading_items`
  (014) is therefore **absent from the `schema.sql` baseline** — a fresh DB
  needs the migrations, not just the baseline.
- **There is a third service: `defuddle.service` on :8010.** Node article
  extractor (`dialectic/defuddle_service/server.mjs`), reached via
  `llm/defuddle_client.py`, backing the `read_article` tool. Live and active;
  missing from the co-projects table above.
- **`dialectic/deploy/dialectic.service` is NOT what runs.** It describes an
  `/opt/dialectic/current` release-symlink deploy; that path does not exist on
  this host. The unit systemd actually loads is
  `/etc/systemd/system/dialectic.service`, with
  `WorkingDirectory=/root/DwoodAmo/dialectic` and
  `ExecStart=/usr/bin/python3 run.py`. **The "both units run their git working
  trees" house rule above is the accurate one** — the checked-in service file is
  the trap, and a deploy that trusted it would target a directory that isn't
  there. Tombstoned in place.

Two things checked and found **correct**, recorded so they aren't re-litigated:
the seam's "v3 push on change + hourly heartbeat" is exact
(`coordinator.py:660`, `DIALECTIC_HEARTBEAT_SECONDS = 3600.0` — and only a
*delivered* push resets the clock, so a spooled failure stays due); and
cc-sidecar really is pattern-donor only — nothing in `dialectic/` or `trading/`
imports it and no unit runs it.

One minor inconsistency, left alone deliberately: tradingDesk's **dev** port is
8000 (`Makefile`, `trading/CLAUDE.md`, and `dialectic/CLAUDE.md`'s "port 8000 is
reserved"), while `trading/README.md:14` shows 8006 for dev. Production is 8006
everywhere. The Makefile is not wrong; the README's dev line is the odd one.

## Code style

ARCHITECTURE/WHY/TRADEOFF docstrings on non-obvious decisions. Match the
surrounding file's idioms; minimal diffs; house-style commit messages with the
`--` em-dash flourish (see `git log --oneline`).
