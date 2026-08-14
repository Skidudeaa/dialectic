# Release 3 — Deliberation and Whole-House Intelligence: integrated gate

Date derived in America/Chicago: **2026-08-14**. Branch
`claude/release-3-deliberation`, gate run by the orchestrating session per
PLAN.md §5.8. Every number below was observed fresh at this gate, never
inherited (§1.8).

## 1. Fresh verification

| Check | Observed |
|---|---|
| Backend suite | **1300 passed**, one clean line (baseline 1174 + 126 new) |
| Frontend suite | **233 passed / 29 files** (baseline 131/19) |
| Lint | 0 errors |
| `npm ci` + production build | clean (`tsc -b` + vite + PWA precache) |
| ruff `--select F`, whole tree | **80** — exactly master's pre-existing count, zero new |

## 2. Mutation guards — every one re-proven red-then-green

All reverted by targeted edit, never `git checkout`. Each red was on the
guard's own assertion (verified, not assumed).

**Release 1:** movement-fence per-arm (red: `unfenced rows leaked`) · twin
rule ×3 (reading-key exclusion 3 red / twin absorption 1 red / thesis-slot
exclusion 1 red) · proposal slot-table single definition (1 red) ·
relationship ids flat-not-kind-keyed (1 red) · boot-consults-restoration
(2 red) · remember-INSTALLED-not-requested (ghost-branch red) · access-error
set only-after-correction (explicit-refusal red — first mutation attempt
*added* an early set instead of moving it and killed nothing; corrected
mutation isolated the bug and went red).

**Release 2:** capabilities delegates-not-copies (identity red, all nine
behavioural tests stayed green — which is the point) · live scheduler roster
(5 red under a hardcoded roster) · workspace staleness ticket (1 red) ·
provider-name ban (red naming the file).

**Release 3:** field dedup law (`UniqueViolationError` with ON CONFLICT
removed) · atlas both-endpoint fence (sentinel CONTENT leak with the
source-side fence removed) · proposal-intake kind gate (6 red disabled) ·
contract FIELD_* order (red on a tuple swap) · continuity v1-degradation
(3 red on throw) · setRoom axis reset (bleed test red) · MessageInput draft
seed (2 red) · **the new rememberScene scene-preservation fence** (red under
the reverse mutation — see §4).

## 3. Browser acceptance — 25/25 (new gate harness)

`docs/superpowers/acceptance/2026-08-14-release-3-gate-browser-acceptance.py`
against the isolated fixture (`dialectic_browser`, :8013/:4173; production
verified untouched before and after). Proven live: Field installs from the
URL; a provisional mark renders at nonzero size with a literal "provisional"
chip AND a dashed rule; a real confirm round-trips through the live POST and
restyles **in place** (DOM order string-identical before/after); the Focus
selection rides `&object=` and survives a fresh context + reload; the empty
Field teaches (449 chars of SceneEmpty copy); Atlas installs at Home root,
lists rooms at nonzero size, and its node navigates into the room; "Make a
move" opens without hover, the proposal lands as a normal message, the OTHER
user (a second real account) accepts, and `accepted_by` stamps that user's id
in the stored row; kill-and-reopen (new tab, sessionStorage gone) restores
room + scene + object exactly and Focus is actually open; an explicit deep
link overrides restoration; a composer draft survives reload with the
message count unchanged. Screenshots committed under
`screenshots-release-3/gate-0*.png`, each looked at.

## 4. What the gate caught — a real defect, fixed at the gate

The kill-and-reopen scenario failed against fully-green unit suites.
`rememberScene` preserved same-room axes by spreading the whole prior record
after the destination, so `prior.scene` clobbered `destination.scene`: a
Record → Field switch stored `record` forever and restoration reopened the
wrong scene. All 232 unit tests passed because none asserted both halves at
once. Fixed (explicit axes pick), fenced
(`sceneContinuity.test.ts` "takes the NEW scene on that same repeat
navigate"), reverse-mutation-proven, gate scenario green. Commit `23b7591`.

## 5. Identity / a11y / grayscale (TG-F artifacts re-run fresh at the gate)

**30/30** on the re-run after the harness learned to let
`document.getAnimations()` drain before measuring geometry — `claudeEnter`
scales a Dialectic row from 0.97, and a width sampled mid-animation reads 3%
narrow under load (the recorded animated-property trap; the CSS was correct).
axe-core: **0 serious/critical at 1600 / 1200 / exactly-1024 / 820 / 390**,
zero to triage. No hover-only action (49 actionable elements walked), visible
keyboard focus, reduced-motion neutralizes entrance/shimmer/flash with
meaning intact. Grayscale screenshots (ordinary room + House) looked at:
still unmistakably Dialectic. F2 (three typographic voices + causality
motion) deliberately not shipped per Ruling R3 — the voice split needs a
contribution-vs-position classification that does not exist in the message
model; recorded as post-gate work, not silently dropped.

## 6. Performance (§5.7 / §7.5)

Reference run (TG-G, box load ~13, commit `bf5c94f`): workspace **47.4ms** ·
field **5.6ms** · atlas **98.2ms** · home **43.0ms** p95 — all four under the
150ms target. Gate re-observation (box load 35–45 from unrelated agents —
an ollama runner at 255% CPU and two Codex processes): field **62ms** still
passes; workspace 213 / atlas 437 / home 185 miss — with **zero backend
changes between the two runs**, so the delta measures the box, not the code.
Recorded per §5.7's written-analysis escape hatch; the standing suspect if
atlas p95 regresses at scale is its per-eligible-room FieldMarkService loop
(a structural N+1, profiled at 27.3% of build time at seed scale).

## 7. Honest limits carried into the release record

- **§15.2 restored-vs-stored:** objectId, replyToId, composerDraft restored
  end-to-end. focusMode / inspectorTab / openProposal structurally empty this
  release (the shipped Focus renders everything at once — no hidden state to
  lose). fieldViewport / recordScroll **stored with no capture point** — a
  real gap, distinct from the structurally-empty three: the scene frame does
  not scroll, Record's scrolling belongs to MessageList's follow-the-tail
  logic, and forcing a restore against it is conflicting-behavior design
  work, deferred with reasons.
- A **merge's non-primary sources** are retired by review rows alone (only
  the primary target is anchored by the replacement's `supersedes_id`), so a
  later confirm can reopen one — same deliberate family as the reopenable
  bare `supersede`.
- The review POST returns targeted single-mark builds because the room
  projection is capped at 500 — a committed review of a mark past the cap
  must never read as a failure.
- `judgment` stays name-only (§1.15). Guest access stays off (§1.14).
- Deploy-order amendment (PLAN.md, 2026-08-14): the owner device checklist
  runs **after** the deploy — §7.6's content is unreachable from any real
  device before the flip. Results to be recorded verbatim below when the
  owner runs it.

## 8. Riding commits

`f9d125c` (trading OHLCV fix), `5019e2b` (human-interaction audit),
`7d79bd6` (indicator-window handoff) from parallel sessions; `e234212`
(audit's two lying tradingDesk affordances removed — goes live at
tradingDesk's next deploy, not this one).

## 9. Owner items (pending)

- [ ] §7.6 device checklist (macOS, Windows, iPhone, iPad, Android) —
      results recorded verbatim here.
- [ ] §4.1 stray room `eeffa8f1-9d5a-4d31-981d-b5cf0a0627e8`
      (`probe-do-not-create`): owner cleared the question mid-build; the
      production DELETE awaits one unambiguous yes.
