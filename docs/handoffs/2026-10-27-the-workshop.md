# The Workshop — 2026-10-27

Owner request, in order: a moonshot for the app ("assume unlimited dev
resources and 12 months"), then "now" under the three-pillar charter, then
"deploy both". This handoff is the zero-context record of what shipped.

## State at close

- **Live:** backend PID `1970471` on commit `3a24bbb`, started 03:07:31 CDT,
  `/health` ok, 17 jobs in the scheduler banner. PWA release
  `/var/www/dialectic-releases/20261027T080824Z-workshop-3a24bbb` (built from
  a clean worktree of the commit; served `index.html`/`sw.js` hashes match).
  Previous release `20261012T052046Z-room-palette-1041fb4` kept for rollback.
- **Master:** `3a24bbb` (the Workshop), `61b7950` (deploy record), this
  handoff. Pushed with this commit.
- **Host change outside git:** `pypdf` 6.21.2 installed for `/usr/bin/python3`
  (`python3 -m pip install --break-system-packages pypdf`; uv refuses the
  system interpreter). Newsletter ingest had been broken in production since
  the 08-18 amendment added the dependency; 19/19 tests now.
- **Host change outside git:** `/var/lib/dialectic/workshop/venv` (uv, 743 MB,
  python3.12 symlinked into `/usr` so it works read-only inside the sandbox)
  and `/var/lib/dialectic/workshop/rooms/<room_id>` workspaces created on
  first use. Rebuild command is in `dialectic/CLAUDE.md`'s 10-27 amendment.
- **Untouched:** the owner's uncommitted palette pass (~105 files, mostly CSS,
  plus `ShapeTree.tsx` and friends and `tests/test_reddit_sources.py`). The one
  red frontend test (`ShapeTree > merge candidate`) is in that dirty state and
  passes at HEAD.

## What changed for users

- Dialectic has hands. Ask it for a backtest, a simulation, a chart, a table
  from a dropped file, or arithmetic, and it runs Python (or bash) in a sandbox
  that belongs to the room. Charts save as PNG and show inline; tables as CSV
  download. Under "used N tools" the code and what it printed are readable.
- The workspace persists: files from one run are there for the next, and every
  run is a git commit in `/var/lib/dialectic/workshop/rooms/<room_id>`.
- What Changed carries the entry `the-workshop`.

## The mechanism (read before touching)

- `dialectic/llm/workshop.py`: `run()` writes the program under
  `runs/<stamp>-<id>/`, launches `prlimit … bwrap … /opt/venv/bin/python`
  with `--unshare-all`, uid 65534, `/usr` and the venv read-only, `/work`
  read-write, tmpfs `/tmp`, `--clearenv`, `PYTHONPATH=/work`, and waits with
  a wall-clock kill on the process group. **Pipe readers are separate tasks**:
  `communicate()` under `wait_for` drops the bytes already read, so a killed
  run came back empty until that was fixed. `file_artifacts()` turns new or
  changed files (not under `runs/`, `.git`, dotfiles, `__pycache__`) into
  `attachments` rows with uploader NULL and message NULL, kind by mime, PNG
  dimensions parsed, cap 8 per run and the per-kind byte cap.
- `_build_workshop_tools` in `llm/tools.py` registers `run_code` (tool 26)
  under `DIALECTIC_WORKSHOP_ENABLED` (default on). The run cap is **25 s with
  a 29 s guard** because `test_tools_registry` caps every guard under half the
  60 s loop budget. Do not raise the cap; hours-long work is `start_job`.
- `documents.document_ids_from_calls` reads `provenance.attachment_ids`
  beside `attachment_id` for kinds in `BOUND_PROVENANCE_KINDS`
  (`document`, `workshop`), so the orchestrator's existing `_bind_documents`
  homes run artifacts on both tool paths with no orchestrator change.
- Prompt policy paragraph in `TOOLS_SECTION` (`llm/prompts.py`): computing
  beats recalling; report what the run printed.
- Frontend: `RunCodeTrace` in `MessageBubble.tsx` (reuses `.msg-evidence-raw`,
  no CSS change); `releases.ts` entry with an `[[attachment|…]]` gloss.

## Proof

- `tests/test_workshop.py` (20 tests): the argv fence, real runs (no network,
  nobody, no `/etc/shadow`, no `.env`, `/usr` read-only), the kill keeping
  output, persistence as git history, bash, artifact kinds and caps, the bind,
  the registry and the kill switch, one real-Postgres image row.
- `dialectic/deploy/probe_run_code.py` (real Sonnet, real sandbox, fake DB):
  the model chose `run_code` unprompted for a GBM ask, 2.6 s, p5/p95
  86.85/114.61 (theory 86.7/114.5), 1040×650 PNG filed.
- Production, over the real WebSocket (E2E Test Room `e78ebe5c…`, Test User,
  the `write_document` probe recipe): `run_code` 42 ms, `fib.csv` on the
  `llm_done` frame already bound to message `ed12b05e…`, workspace commit
  `ee34d01`. Not yet observed in a browser or from a founder account.
- Suites: backend 2423 passed, 5 pre-existing reds (four newsletter = pypdf,
  now fixed; `test_workspace_objects_pg::test_proposals_carry_stable_source_coordinates`
  red on clean HEAD); frontend 783/784 (above); lint, `tsc -b`, build and the
  lazy-Cesium gate clean.

## Rollback

```
ln -sfn /var/www/dialectic-releases/20261012T052046Z-room-palette-1041fb4 /var/www/dialectic-current && systemctl reload nginx
git checkout 1d581d6 -- dialectic/llm dialectic/tests && systemctl restart dialectic
```

Or leave the code and set `DIALECTIC_WORKSHOP_ENABLED=0` in `.env` and
restart: the tool leaves the registry, nothing else changes.

## Why this first

`docs/MOONSHOT_2026-10-27.md` is the plan. The ordering came from the
database, not the doc: human messages per week were 110 in mid-August and
**0 every week since 2026-09-21**. Pull is the limiter; hands are the organ
that makes a room worth opening over a private chat.

## Next

1. The owner asks it something computational from a phone and looks at the
   bubble. That is the gate for everything below.
2. `start_job`: hours-long runs on the `scheduled_job_runs` ledger, progress as
   one updating workspace object, result cited by the morning brief.
3. Search and browse behind the two-key `capabilities` ledger (migration),
   on a second machine before any credential enters the sandbox.
4. Two ESP32 boards for the Hearth's lamp.

## Traps for the next session

- Parallel Bash tool calls share one shell cwd; two commands that both `cd`
  interleave. Wrap in `( cd X && … )` and use absolute paths.
- Host `python3` is a venv (`/root/defGen2/venv`); `/usr/bin/python3` is what
  `dialectic.service` runs and what the tests must run under.
- The sandbox shares the production kernel and CPU (prlimit plus a user
  namespace, not a VM). A second box before credentials.

## Addendum, same day — `start_job`: the long runs (LIVE)

**Deployed 14:21 CDT at the owner's call:** migration 028 on prod (20 columns,
3 indexes), backend PID `2683147` on `5aa8816` with `workshop_job_watch@60s`
in the banner, release `20261027T192154Z-workshop-jobs-5aa8816` (previous
`20261027T080824Z-workshop-3a24bbb`). Production proof: a real socket turn in
the E2E Test Room started an 8-round job ("not waiting on it now"); 40 s
later the sweep's forced turn arrived on the live socket with `rounds.csv`
bound and `metadata.workshop_job`, correct sums. Rows, events and the bound
attachment verified in the DB; no tracebacks in the journal.

- **What it is**: tool 27, `start_job(code, label, language, timeout_s ≤ 21600)`.
  `llm/workshop_jobs.py` launches the same sandbox detached (stdout/stderr to
  files in the run dir, own session), inserts a `workshop_jobs` row
  (**migration `028_workshop_jobs.sql`**, applied to `dialectic_test` and
  production), and an in-process watcher finalises the row when the
  process ends. The `workshop_job_watch` scheduler job (60 s, flag
  `DIALECTIC_WORKSHOP_ENABLED`) marks jobs the restart killed as `lost` and
  reports each finished job as a forced participant turn
  (`reason=workshop_job_done`) with the files bound to that message and
  broadcast live. `api/workshop.py`: list / get (live stdout tail) / kill
  (human-only, stamps `killed_by`). Frontend: `JobTrace` on the message that
  started the job, polling 10 s while running, with Stop; release entry
  `the-workshop-jobs`; `JOB_COPY.workshop_job_watch`.
- **Laws**: one running job per room, three per host; JSON values go to
  asyncpg raw (the pool codec serialises); `clock_timestamp()` for job
  timestamps; the scheduler tick never runs the job, only spawns the report.
- **Proof**: `tests/test_workshop_jobs.py` (13: launch/finalise, timeout
  kill, human kill, cap, lost pass, report sweep with real bind + broadcast,
  owed-on-silence, tool, routes). Real-model probe
  (`scratchpad/probe/start_job_probe.py`, rolled-back test DB): Sonnet chose
  `start_job` unprompted for a "don't make me wait" Monte Carlo, 1800 s
  budget, replied it would report back without estimating; the job ran 7.2 M
  paths in 5.4 s, two files, one commit. The REPORT turn through the real
  orchestrator is proven in production (above).
- **Deploy order**: `psql dialectic < dialectic/migrations/028_workshop_jobs.sql`
  → `systemctl restart dialectic` (the banner must list
  `workshop_job_watch@60s`) → frontend release. Rollback: the flag to 0 and a
  restart removes both tools and the sweep; the table can stay.
- **Known gaps**: no push notification when a job finishes (the report rides
  the ordinary message broadcast); no `list_jobs` tool for the participant
  (it learns a job is running from the one-per-room refusal); a job and a
  `run_code` can touch the same workspace files concurrently.
