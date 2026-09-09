# Reading room: evidence beside thoughts, depth by shade, reading focus — 2026-09-08 (closeout)

Dialectic serves Mac and Windows desktops, iPad, Android and iPhone as equal targets. Continue in the existing [An Alien Mind room](https://dialectic.somacura.org/?room=d428ffef-1902-4f22-9771-5b5765aa73bb&thread=52bbd568-e947-4186-ac30-4168d447e197&scene=surface); preserve Amo and Dan's membership, messages and saved article. Prior commit/deploy/handoff/push authorization persists. This closes out the evening that began with [map navigation and concurrent replies](2026-09-08-map-navigation-concurrent-replies.md) and ran through [evidence beside thoughts](2026-09-08-evidence-beside-thoughts.md) and its amendments. Everything below is committed, deployed and pushed; `origin/master` is `6927602`.

## What is live

| Commit | Release | What |
|---|---|---|
| `5e74949` | backend PID `3932798` + `20260909T020353Z-evidence-beside-5e74949` | `evidence` stamped on tool-trace entries by `llm.tools.evidence_of` in `ToolLoop._execute`; Evidence card under machine answers (Open original, byline, excerpt, revision hash, Save to room, raw payload); `POST /reading/file` accepts a url the answer itself fetched; map clusters at ≤50% zoom; `Challenge` beside `Find and pull`. |
| `c08a262` | `20260909T031112Z-depth-shade-c08a262` | Reply depth by shade, not tabbing: a single-reply chain stays full width; only a fork opens an 8px rail and deepens the sheet one step per fork depth. `data-depth` stays the DOM truth for jump/identity logic. |
| `76c1f66` | `20260909T031428Z-byline-row-76c1f66` | Challenge moves under ··· in compact branches so the byline stays one row. |
| `5078f63` | `20260909T033647Z-reading-focus-5078f63` (selected) | Reading focus mode: per-device toggle in the conversation head hides room header, presence chips, notification chip, scene tabs and the desktop rail; the head is the one strip and carries the room name and Exit focus. Source-less threads drop their label row. |

The backend has not changed since `5e74949`; the three later releases were frontend-only flips. Production also runs `DIALECTIC_ADDRESSED_ONLY=1` and `ANNOTATOR_ENABLED=0`, so in reading rooms the participant speaks only when summoned.

Two real summons ran in An Alien Mind tonight: the owner's own Find and pull at 21:56 CDT (answer `c5090cb7`, Reddit evidence) and one sent as Amo on the owner's "do it" (request `446a83d9`, answer `0b056cdc`, the Kokotajlo tweet). Both carry evidence cards on the live origin. Nothing was saved to the library.

## Verified at closeout

- Tracked tree clean; `origin/master` = local `master` = `6927602`.
- Public `index.html`, JavaScript, CSS, manifest and service worker match the selected release's hash manifest; `/health` reports db, redis and scheduler fresh; Dialectic PID `3932798` serves `/root/DwoodAmo/dialectic` since 21:03:54 CDT; Defuddle and trading active and unchanged.
- Gates on the final frontend: 771 tests in 84 files, eslint, `tsc -b`, production build and the lazy-Cesium contract. Backend at `5e74949`: 2401 passed, 1 pre-existing failure (`tests/test_surface_anchor_refs.py::TestPromptRendering::test_anchor_prefix_and_refs_suffix_are_data`, stale since `216165f` changed `_refs_suffix` in `llm/prompts.py`; a one-line expectation update).
- Browser evidence: isolated real-SQL fixture in Chromium/Firefox/WebKit desktop and Chromium phone (evidence card, Save wiring, Challenge, cluster fold/expand); candidate bundle against production data read-only for focus mode at 1280×900 and 390×844 (first thought y=289→62 desktop, y=353→84 phone; no clipped head control); live screenshots of the deployed chain and cards. All Linux engine runs; physical Mac/Windows/iPad/Android/iPhone, native selection handles, soft keyboards, installed-PWA update and Amo/Dan acceptance remain unobserved.
- Archives with scripts, logs, screenshots and hash manifests: `/var/backups/dialectic/20260909T020353Z-evidence-beside-5e74949`, `…T031112Z-depth-shade-c08a262`, `…T031428Z-byline-row-76c1f66`, `…T033647Z-reading-focus-5078f63`.

## Next work

1. **More waste inside the column.** Cheapest first: fold the `· WHY` provenance line under machine messages into ···; collapse the article pane's action row to icons in focus; hide the composer's "Message options · text" row until an attachment or tag is in play.
2. **Focus keeps scene tabs?** Focus hides Record/Field/Library/Ledger behind Exit focus. If scene switching is frequent, keep the tab row as a 32px strip in focus.
3. **Reddit excerpt chrome.** `read_reddit` evidence excerpts start with the post's markdown header (title, byline, "## Comments"); start at the body or first comment.
4. **Mismatch beyond library rows.** Only `search_reading` items can be compared to a quoted passage's revision; carry the reading url or id on `read_article` items when the url matches a library row.
5. **Server search of older history** behind the map search box, with a path back to the saved thought.
6. **Generation-scoped Stop** and **physical-platform acceptance** as in the prior handoffs. Fix the stale `test_surface_anchor_refs` expectation.

## Rollback

Frontend: repoint `/var/www/dialectic-current` at any retained release above (previous selected: `20260909T031428Z-byline-row-76c1f66`), `nginx -t`, `systemctl reload nginx`. Backend: the only backend change tonight is `5e74949`; revert it in a clean checkout and `systemctl restart dialectic`. No migration. Old messages carry no `evidence` and render as before; messages stamped by the new backend are inert on an older frontend.
