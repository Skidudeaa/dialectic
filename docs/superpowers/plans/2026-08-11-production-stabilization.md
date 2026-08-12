# Production Stabilization Implementation Plan

> Execute in order. Production mutations occur only after focused tests pass.

**Goal:** Restore the scheduler after database restarts, make scheduler failure
visible, rotate exposed room tokens, and clear the two known operational/static
checks.

**Architecture:** Preserve the existing scheduler ownership boundary: `_tick()`
runs jobs, `run()` owns pooled connection lifetime and recovery. Health reads
the existing `scheduler_heartbeat` ledger. tradingDesk remains the only token
consumer and receives one coordinated restart.

**Stack:** Python 3.12, asyncio, asyncpg, FastAPI, pytest, React 19, TypeScript,
Vite, ESLint, systemd, nginx.

---

## Task 1: Isolated baseline

**Files:** none

- [ ] Create `.worktrees/production-stabilization` on
  `codex/production-stabilization-2026-08-11`.
- [ ] Confirm the worktree is clean and based on the documentation commit.
- [ ] Run `python3 -m pytest tests/test_scheduler.py
  tests/test_trading_alerts_endpoint.py -q` from `dialectic/`.
- [ ] Run `npm ci`, `npm run build`, and capture the expected single lint failure
  from `dialectic/frontend/app/`.

## Task 2: Scheduler connection recovery

**Files:**

- Modify: `dialectic/tests/test_scheduler.py`
- Modify: `dialectic/scheduler.py`

- [ ] Add a regression where the first acquired connection raises on ledger
  insert and the second completes a tick.
- [ ] Patch `asyncio.sleep` in the regression so reconnect is immediate and
  stop the infinite scheduler loop after the second connection proves use.
- [ ] Run the new test and confirm it fails because `_tick()` swallows the
  released-connection error.
- [ ] Remove the ledger insert and terminal update exception swallowing from
  `_tick()`; retain job-function exception recording.
- [ ] Run the focused scheduler tests and confirm they pass.

## Task 3: Scheduler freshness health

**Files:**

- Modify: `dialectic/tests/test_trading_alerts_endpoint.py`
- Modify: `dialectic/api/main.py`

- [ ] Add health cases for fresh, stale, missing, and explicitly disabled
  scheduler states.
- [ ] Run the health tests and confirm stale/missing cases fail first.
- [ ] Query successful `scheduler_heartbeat` age through the same acquired
  health connection after `SELECT 1` succeeds.
- [ ] Return `fresh`, `stale`, `missing`, or `disabled`; degrade only the stale
  and missing enabled states.
- [ ] Run the focused health tests and confirm they pass.

## Task 4: Frontend lint

**Files:**

- Modify: `dialectic/frontend/app/src/App.tsx`

- [ ] Replace the render-time ref assignment with an effect keyed by the
  existing `switchRoom` callback.
- [ ] Run `npm run lint` and `npm run build`.

## Task 5: Canonical tradingDesk unit

**Files:**

- Modify: `trading/deploy/tradingdesk.service`

- [ ] Add the two start-limit keys under `[Unit]` and remove them from
  `[Service]`.
- [ ] Run `systemd-analyze verify` against the canonical file.
- [ ] Confirm the warning is gone before installation.

## Task 6: Source verification and commit

**Files:** all files above plus `JOURNAL.md`

- [ ] Run focused scheduler and health tests.
- [ ] Run the complete Dialectic backend suite.
- [ ] Run frontend lint and build.
- [ ] Run `git diff --check` and inspect the exact diff.
- [ ] Append the implementation decisions and verification to `JOURNAL.md`.
- [ ] Commit only the stabilization files.

## Task 7: Rotate tokens and activate tradingDesk

**Files/State:**

- Modify secret: `/root/DwoodAmo/trading/.env`
- Modify database: five `rooms.token` rows
- Install: `/etc/systemd/system/tradingdesk.service`

- [ ] Revalidate the exact five room IDs in DB and env without printing tokens.
- [ ] Generate five new values and update DB/env as one guarded operation.
- [ ] Install the verified canonical unit and run `systemctl daemon-reload`.
- [ ] Restart `tradingdesk.service` once.
- [ ] Verify active state and local/public readiness.
- [ ] Prove old tokens return five 401 responses.
- [ ] Prove new tokens return five 200 responses.
- [ ] Prove process env, env file, and DB match 5/5 without secret output.

## Task 8: Deploy Dialectic backend

**Files/State:** production checkout and `dialectic.service`

- [ ] Merge or cherry-pick the verified source commit into `master` without
  staging runtime artifacts.
- [ ] Confirm the committed Dialectic source matches the tested commit and its
  subtree has no uncommitted changes.
- [ ] Restart `dialectic.service`.
- [ ] Verify active state, local `/health`, and public `/health`.
- [ ] Confirm `scheduler_heartbeat` receives a new successful ledger row.
- [ ] Confirm scheduler logs show a fresh lock/acquisition and no released-pool
  errors after restart.

## Task 9: Deploy frontend

**Files/State:** `/var/www/dialectic-releases` and
`/var/www/dialectic-current`

- [ ] Build from the committed production checkout.
- [ ] Copy `dist/` to a new timestamped release directory.
- [ ] Atomically flip `/var/www/dialectic-current`.
- [ ] Run `nginx -t`, reload nginx, and verify public HTML references the new
  versioned asset.
- [ ] Compare the served asset digest with the release file.

## Task 10: Final reconciliation

- [ ] Confirm intended commits and remote divergence separately.
- [ ] Confirm unrelated trading snapshots/outcomes and untracked artifacts were
  preserved.
- [ ] Append live activation and proof to `JOURNAL.md`; commit that line only if
  it belongs with this rollout.
- [ ] Report implementation, commit, runtime, and browser proof as separate
  states.
- [ ] Open a new design tranche for P2 only after stabilization is proven.
