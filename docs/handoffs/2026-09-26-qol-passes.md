# QoL + visual passes — 2026-09-26

Owner request: "take a few aggressive user quality of life and visual enhancement passes."

## State at close

- **Live:** frontend release `/var/www/dialectic-releases/20260926T064938Z-qol-passes-ee1f36f`.
  - The previous release was `20260919T225732Z-column-waste-b243a4c`.
  - Backend PID `130600` was not restarted; there were no backend changes.
  - Public asset hashes match the release. A read-only tour of 20 live pages showed no errors and no horizontal overflow.
- **Master** (not pushed; origin is 10 commits behind):
  - `1b3ac8e` acceptance
  - `5c6d6f0` visual integrity
  - `ee1f36f` readable thesis graph
  - `ebef045` journal
- **Uncommitted, not deployed:** `dialectic/frontend/app/src/styles/global.css`.
  - It adds `flex-shrink: 0` to `.push-enable-chip`. The phone notification banner was squeezed to 42px against 49px of text, so "write" painted below its border.
  - Checked on a scratch build: the squeeze probe finds nothing, visual-integrity passes 36/36 and dag-legibility passes 3/3.
  - To ship it: commit, then `python3 /root/scratch/20260926-qol/release-frontend.py <tag>` from `/root/DwoodAmo`.
- The owner's unrelated uncommitted edit to `dialectic/tests/test_reddit_sources.py` was left untouched.

## What changed for users

- **Home:** the house panel was squeezed to 3–7px and drew over the timeline and composer. It now has a scrollable reading region, and the composer sits outside it.
- **Scene tabs on tablet and phone:** they no longer collide. On phone they wrap to two rows.
- **Collisions:**
  - Unread badges no longer cover room names.
  - The touch action row no longer covers bylines.
  - Day dividers are no longer sticky over message text.
- **Participant names:** `llm_primary`, `llm_provoker` and `llm_annotator` in bot prose, the Record briefing and Ledger memories now read "Dialectic". One render-time helper in `lib/productIdentity.ts` does this; stored data is unchanged.
- **Bench thesis graph:**
  - Node names render at 18.7px on desktop, up from 6.2px.
  - The drawing sizes from its container and pans inside its canvas.
  - Edge mechanisms moved into the selected node's detail panel.

## Checks you can rerun

`dialectic/frontend/app/tests/visual-integrity/`:

- `visual-integrity.acceptance.cjs`: no overlapping text, no horizontal overflow, no raw ids, key content present. It covers 12 pages at 1440×900, 834×1194 touch and 390×844 touch.
- `dag-legibility.acceptance.cjs`: all 19 node names readable, fits on desktop and tablet, no graph text collisions.
- Both build the app, then replay HAR fixtures recorded read-only from production at a fixed clock.
  - The fixtures are in `/root/scratch/20260926-qol/fixtures`, sha256-pinned. They hold real room content, so they stay out of the tree.
  - The scratch directory is kept until **2026-10-10**. After that, re-record with `/root/scratch/20260926-qol/tour/record.cjs` and update `fixtures.sha256.json`.
- Iterate with `--dist <dir> --only <page>`. `VI_SHOTS=<dir>` saves screenshots.
- At release: vitest 781/781, eslint clean.
- A generic "no overlapping text" rule found 30 of 36 page views broken on master. Every hit was a real defect.

## Process record (OMC-B)

- Two medium-effort Astra workers ran with disjoint scopes. The trial record is `/root/omc-baselines/trials/qol-2026-09-26.md`.
- The 5M-token session cap was exceeded: 8.5M raw worker tokens in about 20 minutes. Idle workers kept spending tokens answering throttle notices until they were stopped.
- Chromium cannot launch inside the Codex worker sandbox. The lead ran every browser check.
- `qol-visual-integrity` completed through the gate.
- `qol-readable-thesis-graph` passed its check, but the claim expired 6 seconds after the finish decision.
  - It is held as `step_recovery_required` at the owner's choice, so the gate keeps posting reminders. Ignore them unless the budget is raised.
- No independent review ran. The owner chose merge and deploy without it.
- Worktrees are kept: the baseline, both worker worktrees under `baseline/.omc/team/*/worktrees/`, and `combined/`.

## Known residue, highest value first

1. The desktop Home timeline gets about 100px under the "Needs you" list. Fold that list into a one-row summary.
2. The phone header and scene tabs take three rows before content. Merge them into one row.
3. The banner fix above is waiting to ship.
4. Nothing was tested on a physical iPad, phone or installed PWA. The Surface-scene graph pane was not looked at after the graph change.
