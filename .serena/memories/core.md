# DwoodAmo — source map & invariants

Monorepo for **Dialectic**: collaborative dialogue engine (two humans + LLM co-reasoning in real time). The LLM is a participant, not an assistant.

## Top-level map
- `dialectic/` — the product: FastAPI backend + React PWA. See `mem:dialectic/core` for internals (llm/ orchestration, memory lanes, scheduler, event sourcing).
- `trading/` — tradingDesk: causal-DAG thesis engine + live data service. See `mem:trading/core` for internals (web/, tools/, books/snapshots data).
- `cc-sidecar/` — Claude Code observability daemon; donor of the FSM/StateSource patterns now in `dialectic/llm/participation_fsm.py`. Optional local daemon.
- `packages/` — React Native workspaces (mobile/app/macos/windows). **FROZEN — cannot reach production.** The PWA is the reach strategy. Do not build features here.
- `docs/` — vision, quarter plan + Amendment 1, handoffs. `dialectic/TODOS.md` is the task board.

## Project-wide invariants
- **Never Docker.** No Dockerfiles, docker-compose, .dockerignore. Services run directly (native Postgres, python3, npm). Docker artifacts were deliberately dropped in the fusion.
- Event sourcing: dialectic's append-only `events` table is the source of truth; everything else derivable.
- Both production systemd units (`dialectic.service` :8002, `tradingdesk.service` :8006) run **their git working trees** — a restart deploys whatever is on disk. See `mem:deploy` before touching production, restarting services, or committing near a restart.
- History: tradingDesk was a standalone repo until the 2026-08-09 fusion; pre-fusion snapshot archived at `/root/_archive-tradingDesk-pre-fusion` + `/root/tradingDesk-pre-fusion.bundle`. `trading/` is the only living copy; the archive is read-only history.

## Further memories
- `mem:tech_stack` — languages, frameworks, DBs, version pins.
- `mem:suggested_commands` — run/test/build commands per project.
- `mem:conventions` — docstring style, commit message style, code idioms.
- `mem:task_completion` — what to run before calling a task done.
- `mem:deploy` — production deploy order, restart rules, verification gotchas.
