# Home Base: built, gated, activated — session handoff (2026-08-12)

**One line**: Home Base went from approved plan to live production in one
session — 21 commits (`d4fc37e`..`a9a581f`), all 70 plan steps, 913 backend
tests, 14 browser-acceptance proofs, the nine-step activation gate crossed,
and Amo + Dan now land in a shared Home at https://dialectic.somacura.org.

## What production is right now

- **Backend**: `dialectic.service` PID 1072990 runs master @ `54c6efa`+
  (restarted twice during the gate: once for the build, once for the uuid
  binding fix). Health ok, scheduler fresh.
- **Frontend**: release `/var/www/dialectic-releases/20260812T182348Z-home-base`
  behind `/var/www/dialectic-current`; public bundle sha verified
  byte-identical to the committed build.
- **Database**: migration `013` (schema gate crossed early, while the OLD
  backend ran — additive, Pydantic ignores unknown columns). Founders
  activated: exactly two Home managers — `namosson@gmail.com`,
  `danielpharwood@gmail.com` — identified from production trading-room
  memberships, never guessed. Zero other members.
- **The pulse shows FOUR rooms, not five**: the Trump Tariffs Trading Room
  has zero members, and Home surfaces only rooms EVERY Home member belongs
  to. Both founders joining it will make it appear. Not a bug.

## The one open gate step

Real-device acceptance (spec list): cold + open notification entry,
background eviction recovery, keyboard, branch reachability through the
drawers, offline-stale rendering — iPhone and Android, owner coordinates.

## What the gate caught (the session's best lesson)

The live battery's first run failed on the FIRST production member-add:
`_ADD_MEMBER_SQL` typed its event parameter `$3::text`, the route binds a
Python UUID, asyncpg refused (`DataError: expected str, got UUID`). The
mocked API tests assert that SQL's TEXT and could never execute it; it was
the only Home statement with no real-Postgres run. Fix `($3::uuid)::text` +
`test_add_member_statement_binds_the_routes_real_types` executes the actual
statement with the route's real parameter types (`54c6efa`). Rule to keep:
**any raw SQL a route sends gets at least one real-Postgres execution test
with the route's exact parameter types** — text assertions on mocks read
the query, they don't bind it.

## Amendments to the design doc (recorded in PLAN.md, live in code)

1. **Unread boundaries are per-thread** (the rail's exact semantics), not
   the spec's room-scoped boundary — pulse and badge can never disagree,
   and branch unread needs per-thread anyway. Activity window for question
   resolution stays room-scoped as designed.
2. **Claude's Home projection runs on a fresh `db_pool` connection** under
   `HOME_ACTIVITY_TIMEOUT_SECONDS = 2.0` — a racy timeout cancel must not
   land on the turn's own connection.
3. **Drawer breakpoint is `max-width: 1023.98px`** — acceptance case 11
   requires exactly-1024 to be desktop; shipped CSS had 1024 inclusive.
4. `BriefingHighlight` gained optional `thread_id` (the shared
   unanswered-question heuristic must name the branch a question lives in).

## Where things live

- Spec `docs/superpowers/specs/2026-08-11-dialectic-home-base-design.md`;
  executable plan (all 70 boxes ticked + amendments)
  `docs/superpowers/plans/2026-08-11-dialectic-home-base.md`; root `PLAN.md`
  was the zero-context build handoff — complete, kept for the record.
- Backend: `home_activity.py` (projection: intersection CTE, ID-fenced
  reads, set-based receipt boundaries — p95 51 ms at seed-20260811 scale),
  `api/home.py` (membership + activity endpoint), `llm/orchestrator.py`
  `_get_home_activity_context`, `migrations/013_home_base.sql`,
  `deploy/activate_home_founders.sql`, `deploy/remove_home_member.sql`
  (both rehearsed; removal has a psql-driven pytest).
- Frontend: `hooks/useRoomNavigation.ts` (the ONE destination writer — an
  `rg` for `setRoom\(|setThread\(|leaveRoom\(` outside it should stay
  empty), `components/home/`, `components/sidebar/BranchTree.tsx`,
  `components/auth/RoomAccess.tsx`.

## Operational gotchas for the next session

- **Restart = deploy.** Both systemd units run their git working trees;
  never restart with uncommitted dialectic edits.
- **Port 8003 is an impostor**: an unrelated service answers `/health`
  there (`/api/v1/homepage`, v0.1.0). The browser harness uses :8013.
- Browser harness recipe (reusable): `dialectic_browser` DB (schema.sql +
  013), uvicorn :8013 with explicit env (`ANTHROPIC_API_KEY` required —
  dummy ok, `SIGNUPS_ENABLED=1`, scheduler off),
  `DIALECTIC_BACKEND_URL=http://localhost:8013 npx vite preview --port
  4173` (vite.config gained a preview proxy), auth injected via
  localStorage key `dialectic-auth` (zustand persist, version 0). Pydantic
  rejects `.local` emails — use `@example.com`. Playwright MCP scripts must
  live under `/root/DwoodAmo/.playwright-mcp/` (gitignored) and its VM has
  no `require`/`import`/`URL`/`setTimeout` — bake fixtures in, delay via
  microtask spin, and `unrouteAll` at script start (crashed handlers
  persist). A PWA page serves the OLD precached bundle after a rebuild —
  unregister service workers before re-testing.
- **dialectic_test** carries the committed Home row with ZERO memberships —
  the pg fixtures depend on that; never activate founders there.
  **dialectic_browser** still holds the acceptance fixture (3 accounts,
  rooms, forks) — disposable, drop or reuse freely.
- Trading snapshots + `TRD-SH-RECESSION.jsonl` are live runtime data the
  desk rewrites — left uncommitted deliberately.
- Claude's Home context markers (`HOME_ACTIVITY_UNAVAILABLE`, 2s timeout)
  are unit-verified; no live LLM turn was fired in Home during the gate.
  The first real @Claude conversation in Home is still ahead — watch its
  `## Shared Home Activity` section renders and the FSM behaves normally.

## Sensible next moves

1. Device acceptance (the open gate step).
2. Both founders join Trump Tariffs so the pulse shows all five schemes.
3. First real Home conversation with @Claude — observe the digest layer.
4. Home membership growth: the add flow is founder-only by design; the
   emergency removal script is the only way out — keep it reviewed.
