# Dialectic Home Base Build Handoff

Build the approved Home Base design from the current local `master`. Planning is
complete. Do not redesign it. The canonical behavior is
`docs/superpowers/specs/2026-08-11-dialectic-home-base-design.md` at `f77ff3a`;
the executable 9-task/70-step plan is
`docs/superpowers/plans/2026-08-11-dialectic-home-base.md` at `2704e51`.
Execute that detailed plan in order and update its checkboxes as work lands.

## START HERE

1. Read `AGENTS.md`, `JOURNAL.md`, root and `dialectic/` `CLAUDE.md`/README files,
   the approved spec, and the detailed plan completely.
2. Run `git status --short`, `git log -5 --oneline`, and
   `git merge-base --is-ancestor 2704e51 HEAD`. Preserve every unrelated dirty
   artifact; never stash, reset, clean, or broadly stage.
3. Use `superpowers:executing-plans` or `superpowers:subagent-driven-development`,
   plus test-driven development and verification-before-completion.
4. Work on local `master`. Commit each detailed-plan task separately using its
   prescribed narrow file list and commit message.
5. Do not begin Task 2 until Task 1 is tested, committed, and the authorized
   schema-only production migration gate below has passed.

## DECISIONS WITH RATIONALE

- Home is one real, unbound room with one root thread named `Main`. Rejected: a
  synthetic dashboard. It lost because Home must retain normal conversation,
  replay, memory, protocol, push, and Claude participation behavior.
- Represent Home with `rooms.is_home` plus a partial unique index. Rejected: a
  room-kind enum. It lost because one additive boolean preserves existing room
  interfaces and enforces the singleton in PostgreSQL.
- Migration `013` creates Home/Main and bootstrap events but no memberships.
  Rejected: inferring founders during migration. It lost because production has
  other credentialed accounts and display names are not identity authority.
- Founder activation is a reviewed, parameterized transaction resolving exactly
  Amo and Dan by normalized credential email. Rejected: display-name or all-user
  backfill. It lost on identity and least-privilege grounds.
- Amo and Dan alone receive `can_manage_home`; either may add an existing account,
  while added members cannot delegate. Rejected: ordinary-room invite semantics.
  It lost because Home membership controls shared cross-room visibility.
- Cross-room activity is a live projection, not a new table. Rejected: an
  activity/notification ledger. It lost because message, receipt, commitment,
  membership, and thread truth already exist and would drift if duplicated.
- The source set is the database-enforced intersection of rooms accessible to
  every current Home member. Rejected: per-viewer union. It lost because Home
  content must be safe for everyone currently in Home.
- The HTTP endpoint and Claude use the same `HomeActivityService`. Rejected:
  separate queries. It lost because divergent privacy and ordering logic is unsafe.
- Claude participates in Home through every normal participant path; the only new
  layer is bounded shared-room activity context with explicit unavailable/timeout
  markers. Rejected: a special Home bot. It lost because it would bypass shipped
  participation, tools, briefs, protocols, and silence behavior.
- Home cannot acquire `linked_book_id`; thesis draft/create return `409`, and
  `propose_thesis` tells the user to use the scheme room. Rejected: allowing Home
  to become a trading room. It lost because durable schemes belong in their rooms.
- Trading remains an unconditional right-rail tab, including in Home. Rejected:
  restoring the binding-dependent tab. It previously made Create Thesis
  unreachable in precisely the rooms that needed it.
- One navigation hook owns destination validation, room/thread state, URL history,
  notification entry, revoked-room correction, and mobile drawer close. Rejected:
  retaining competing effects/click handlers. They already caused stale-closure
  and history-order regressions.
- Bare `/` enters Home; explicit room/branch URLs and notifications win. Valid
  popstate re-entry mutates no history. Rejected: persisted-room-first launch and
  push/replace during popstate. They break intentional links and Back/Forward.
- Extend the shipped mobile drawers. Rejected: another mobile shell. Scrim,
  Escape, room-change close, and responsive structure already shipped in `273a42b`.
- Exclude soft-deleted messages from every preview, timestamp, unread count,
  unresolved question, and branch count. Rejected: partial filtering. It leaks
  deleted message truth through derived fields.
- Choice A is settled: after Task 1 is committed and verified, apply additive
  migration `013` to production while the old backend runs, then continue on
  `master`. Rejected: an isolated branch with migration deferred. It lost by owner
  choice; the old backend safely ignores the additive columns.

## DO-NOT-RELITIGATE LIST

- Initial Home membership is exactly Amo and Dan; no other account is inferred.
- Added Home members participate but cannot add further members.
- No room token or inaccessible-room field may appear in activity responses or
  Claude context; authenticated nonmembers get `404 Home unavailable`.
- No activity table, notification-center workflow, feature flag, frontend unit-test
  framework, native-app work, tradingDesk change, room-kind enum, or compatibility
  shim belongs in this build.
- Normal Home messages, memories, protocols, autonomous interjection, tools,
  participation FSM, silence follow-ups, briefs, commitments, replay, and push stay
  intact. Home specialization is additive.
- The mobile drawer foundation and unconditional Trading tab are existing working
  behavior, not work to rebuild or simplify.
- Production migration authorization is schema/bootstrap only. It does not include
  founder activation, backend restart, account exposure, nginx reload, or frontend
  release.
- Rollback is additive: roll back frontend then backend; do not delete Home, its
  token, messages, memberships, threads, or events.

## OPEN QUESTIONS — ASK BEFORE DECIDING

- Before founder activation, obtain separate explicit approval and the reviewed
  Amo and Dan credential emails. Never derive or guess them.
- Before restarting `dialectic.service`, placing backend code in service, exposing
  Home to accounts, flipping `/var/www/dialectic-current`, or reloading nginx,
  obtain separate explicit production approval.
- Actual iPhone and Android acceptance remains a production/device gate. Ask the
  owner to coordinate devices rather than substituting responsive screenshots.
- If current code, schema, or runtime contradicts the approved spec/detailed plan,
  stop under the conflict rule below. Do not select a new product behavior.

## REPO / ENVIRONMENT ORIENTATION

- `docs/superpowers/specs/2026-08-11-dialectic-home-base-design.md`: approved UX,
  auth, privacy, Claude, navigation, mobile, rollout, and acceptance contracts.
- `docs/superpowers/plans/2026-08-11-dialectic-home-base.md`: canonical file-level,
  TDD, SQL, API, query, frontend, commit, and activation sequence.
- `dialectic/schema.sql`, `migrations/`, `models.py`: schema and wire models. Create
  `migrations/013_home_base.sql`; never edit/reuse `012_user_memory_promotions.sql`.
- `dialectic/api/main.py`, new `api/home.py`: auth-mounted room APIs, generic join
  denial, Home membership, and activity endpoint.
- `dialectic/llm/orchestrator.py`, `llm/prompts.py`, `llm/tools.py`: normal Claude
  orchestration, the additive Home context layer, and Home thesis refusal.
- `dialectic/frontend/app/src/App.tsx`, `stores/appStore.ts`, `lib/api.ts`, and
  `types/index.ts`: current room boot, state, HTTP client, and response types.
- `components/sidebar/{RoomList,ThreadPanel,RightPanel,SharePanel}.tsx`,
  `components/layout/{AppLayout,RoomHeader}.tsx`, and trading panel files: shared
  genealogy, Home pulse/settings, drawers, breadcrumb, and unconditional Trading.
- New backend tests named in the detailed plan prove schema, membership, activity,
  auth, prompt context, lifecycle denial, ordering, deletion, and performance.
- `dialectic/frontend/app.html` and `dialectic/frontend/index.html` are retired
  legacy frontends. The only live frontend is `dialectic/frontend/app/`.
- `dialectic/deploy/dialectic.service`, `deploy/README.md`, and
  `deploy/nginx.conf.example` define production service/release topology.
- Assumed stack: PostgreSQL 16/asyncpg, FastAPI/Pydantic, Redis, pytest, React 19,
  TypeScript 5.9, Zustand 5, Vite 7; backend loopback port `8002`; immutable web
  releases behind `/var/www/dialectic-current`.
- Production state is never inferred from git. Re-check systemd, `/health`, schema,
  scheduler heartbeat, served asset digest, and browser/device behavior separately.
- The checkout contains unrelated trading snapshots and generated/browser artifacts.
  Preserve them and stage only the current task's named files.

## EXECUTION ORDER

1. Task 1 (9 steps): singleton Home schema, migration/bootstrap, founder activation
   script, real-Postgres idempotency, test-DB persistence, and foundation commit.
2. Cross Task 1's authorized production gate: capture old service/health; apply only
   committed `013` with `ON_ERROR_STOP`; verify columns/index, one Home, one Main,
   bootstrap events once, zero memberships, and unchanged health; journal evidence.
3. Task 2 (7): nondelegable membership APIs, generic-join denial, removal script.
4. Task 3 (5): Home thesis draft/create/tool refusal.
5. Task 4 (10): membership-intersection activity projection and p95 <= 150 ms proof.
6. Task 5 (7): authenticated endpoint and bounded Claude Home context.
7. Task 6 (8): single URL-authoritative navigation transaction and Create/Join overlay.
8. Task 7 (8): soft-delete-correct branch tree, pinned Home, responsive breadcrumb.
9. Task 8 (7): Home pulse, nondelegable settings, explanatory Trading empty state.
10. Task 9 (9): integrated backend/frontend gates, isolated browser acceptance,
    current-state docs, hygiene, and final implementation commit. Stop before the
    separate production activation gate. Total implementation checklist: 70 steps.

## VERIFICATION

- Per task, perform the RED command, minimal implementation, focused GREEN command,
  and narrow commit exactly as written in the detailed plan. Never skip RED/GREEN.
- Task 1: `cd dialectic && python3 -m pytest tests/test_home_schema_pg.py -q`;
  then persist `013` only in `postgresql://root@localhost/dialectic_test` before the
  authorized production migration gate.
- Focused integrated backend gate:
  `cd dialectic && python3 -m pytest tests/test_home_schema_pg.py tests/test_home_membership_api.py tests/test_home_activity_pg.py tests/test_home_activity_api.py tests/test_home_prompt.py tests/test_thesis_relay_endpoint.py tests/test_tools_registry.py tests/test_user_rooms_read_state.py -q`.
- Re-run deterministic seed `20260811`, `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`,
  and 20 warm calls; journal planning/execution/shared-block metrics and p95. p95
  must be <= 150 ms before consumers/browser acceptance are accepted.
- Full backend: `cd dialectic && python3 -m pytest tests/ -q`. Report real-Postgres
  cases as run or explicitly environment-skipped.
- Frontend: `cd dialectic/frontend/app && npm run lint && npm run build`.
- Browser acceptance must use an isolated `DIALECTIC_TEST_DATABASE_URL`, real auth,
  three test accounts, shared/private rooms, a fork, asserted URL/history/drawer/
  stale-state behavior, and all 14 cases in Task 9. Never source production `.env`.
- Hygiene: `git diff --check`, `git status --short`, inspect staged names, and prove
  no trading snapshot, credential, generated release, browser profile, or unrelated
  file is staged.
- Definition of built: all 70 steps complete; migrations/tests/performance/static/
  browser gates pass; docs and journal reflect measured truth; all nine task commits
  are reviewable; production has only the approved additive Task 1 schema bootstrap.
- Definition of live: after new explicit approval, complete the detailed plan's
  separate nine-step activation gate, including founder activation, backend health
  and scheduler proof, immutable frontend digest/symlink proof, and real iPhone plus
  Android acceptance. Report code, schema, runtime, browser, and device states apart.

## CONFLICT RULE

If implementation reality contradicts this plan, the builder flags the contradiction and stops — no silent improvisation, no quiet re-planning.

## AMENDMENTS

- [2026-08-12, Task 4] Unread boundaries are PER-THREAD (latest viewer read
  receipt in that thread, fallback room join time) — the room rail's exact
  semantics — not the design doc's room-scoped boundary. Reason: the rail
  badge and the Home pulse sit one panel apart and must agree, and branch
  unread needs per-thread boundaries regardless. The 100-message activity
  window feeding question resolution keys on the room-scoped boundary as
  designed.
- [2026-08-12, Task 4] BriefingHighlight gained optional `thread_id` so the
  shared unanswered-question heuristic can name the branch a question lives
  in; brief responses carry an additive null for older rows.
- [2026-08-12, Task 4] The per-thread boundary is computed as one set-based
  receipts CTE, not a correlated probe per thread — EXPLAIN at seed 20260811
  scale showed 306 ms/398k buffer hits correlated vs 27.5 ms/7.7k set-based;
  build p95 51 ms against the 150 ms gate, no extra index, no cache.
