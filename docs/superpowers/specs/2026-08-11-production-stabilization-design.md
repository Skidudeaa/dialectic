# Production Stabilization Design

**Date:** 2026-08-11
**Scope:** Token rotation, scheduler recovery and observability, frontend lint,
and the tradingDesk systemd warning. Cross-room memory and commitment proposals
remain separate upgrades.

## Evidence

- Postgres and Redis restarted during unattended upgrades while Dialectic stayed
  alive.
- The scheduler retained a released asyncpg connection proxy. `_tick()` caught
  ledger insert/update failures, so `run()` never reached its existing
  reacquisition path.
- `/health` acquired a fresh connection and therefore stayed green while the
  scheduler ledger stopped advancing.
- All five current production room tokens still matched values published in git
  history.
- Frontend build passed, but lint rejected a ref assignment during render.
- systemd ignored both start-limit keys because they were under `[Service]`.

## Design

### Scheduler recovery

Ledger operations define whether a scheduler connection is usable. Failures
from the insert or terminal update therefore escape `_tick()`. `run()` already
owns connection lifetime and recovery: it releases the failed proxy, sleeps,
and acquires a new connection. Job-function errors remain isolated, logged, and
recorded as `status=error` so one bad job does not stop the clock.

The regression test uses a first connection that fails on the ledger insert and
a second connection that succeeds. It proves that `run()` reacquires rather
than repeatedly invoking jobs through the dead proxy.

### Scheduler health

`scheduler_heartbeat` already runs every 600 seconds and writes the shared
ledger. `/health` queries the age of its latest successful `finished_at` value.
When `SCHEDULER_ENABLED` is false, health reports `disabled`. Otherwise:

- no successful heartbeat is `missing` and degrades health;
- age over 1,200 seconds is `stale` and degrades health;
- a younger heartbeat is `fresh`.

The threshold tolerates one missed bucket plus the 60-second reconnect backoff
without hiding a stopped scheduler for hours. The response exposes state and
age, not database errors or credentials.

### Token rotation

Generate five independent cryptographically random tokens. Update the five
production `rooms.token` rows in one database transaction and replace the
single `DIALECTIC_ROOM_TOKENS` line in `trading/.env`. The operation validates
that the same five room IDs exist on both sides before mutation.

Restart tradingDesk once so its process consumes the new map. Verify without
printing secrets:

- old history-derived tokens return 401 for all five rooms;
- new env-derived tokens return 200 for all five rooms;
- env and database IDs/tokens match 5/5;
- tradingDesk readiness and process environment are current.

If the database transaction or env replacement fails, stop before restart. If
the restart or verification fails, restore the in-process old database/env map
before ending the rotation command.

### Frontend and unit file

Update `switchRoomRef.current` in a `useEffect` keyed by `switchRoom`; callers
continue using the stable ref and room-switch behavior is unchanged.

Move `StartLimitIntervalSec` and `StartLimitBurst` to `[Unit]` in the canonical
unit, validate it, install the exact file, reload systemd, and restart only as
part of token activation.

## Deployment

1. Commit documentation/worktree setup.
2. Build and test source changes in an isolated worktree.
3. Rotate tokens and activate the corrected tradingDesk unit.
4. Merge the verified source commit into the production checkout.
5. Confirm the Dialectic subtree has no uncommitted source edits.
6. Restart Dialectic and verify `/health`, scheduler ledger advancement, and
   scheduler logs.
7. Build a versioned frontend release, flip the symlink, reload nginx, and
   verify the served asset hash.

No schema migration is required.

## Deferred upgrades

- P2 needs an authenticated, membership-fenced promote/demote contract and UI.
- P4 should reuse the proposal-card acceptance contract after P2 is stable.
- P5 remains blocked on a named research provider.
- P6 follows the benchmark definition, not intuition-driven memory tuning.
