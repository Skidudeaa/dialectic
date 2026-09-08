# Contextual reading discussion — 2026-09-08

Continue in the existing [An Alien Mind room](https://dialectic.somacura.org/?room=d428ffef-1902-4f22-9771-5b5765aa73bb&thread=52bbd568-e947-4186-ac30-4168d447e197&scene=surface), with Amo, Dan and the saved article. The owner said “keep going and going”; prior commit/deploy/handoff/push authorization persists. Preserve their room and messages. Test counts do not establish owner acceptance.

This tranche follows [the usability repair](2026-09-08-reading-room-usability-repair.md). It implements that handoff's complete passage anchors and contextual retrieval actions, plus accepted-comment visibility and branch-scoped bot answers.

## Behavior

- **Complete quotations:** selecting up to 4000 normalized characters preserves the entire passage, its reading ID, revision hash and optional zero-based repeated occurrence. Selection beyond that limit is visibly rejected, never shortened. Canonical paragraph/break/inline text is used in both DOM selection and server validation. Old unspecified quotations keep unique-only highlighting; explicit missing occurrences never fall back. No migration. General field marks retain their 300-character limit.
- **Compact context:** shared thread quotations start with three visible lines; Expand passage exposes all original text. Source highlighting still physically connects the selected quotation and discussion. Missing occurrence and occurrence zero share the existing first-passage grouping identity without duplicating source chrome.
- **Find and pull:** the action beside Reply addresses the actual thought. Selecting human words adds those words and their speaker to the editable request. Selecting article words stages the complete reading reference. Existing draft text stays present. Pressing Send makes the request; choosing the action alone does not run a model or fetch sources. Bot replies inherit the request's exact parent/source context. Source saving retains the existing human acceptance boundary.
- **Accepted comment visibility:** the composer receives the exact ID from its own correlated server receipt. Only that comment is revealed, after its DOM exists; collapsed parents open. Receipt settlement still works after navigation, but an unmounted Surface cannot navigate the new destination. Peer arrivals never replay the own-send jump. Existing draft snapshot, staged-ref and reply-target fences remain.
- **Bot branch ownership:** the handler captures the initiating human ID before asynchronous work. Prompt context follows actual same-room reply ancestry, or room chronology through a root request. Later human arrivals cannot change the target or its brevity budget. Streaming, SQL, durable events, completion and reload retain one answer ID and parent. New tool source refs are retained with inherited refs.
- **Stream lifecycle:** frontend provisional messages preserve server ID, parent, source metadata and initial timestamp. Completion uses the same keyed branch node. Thread changes synchronously clear old stream context. An unrelated background completion, identified error or silent heuristic pass cannot erase the current branch answer. Research completion names its separate stream and persisted IDs; explicit stop remains thread-wide.

Existing brevity budgets, the idle-opacity repair, authenticated Async PRAW search/read tools, article extraction and continuation, and ordinary-room scheduled-job exclusions remain in force. No new production contribution, Reddit write or membership change is part of this release.

## Qualification

- Full frontend suite: 744 tests in 83 files. Thirty-eight focused checks after final adjustments, lint, production/PWA build and lazy-Cesium qualification passed; logs are retained in the evidence archive.
- Backend: 95 focused reading-source validation/real PostgreSQL tests; 294 focused branch, prompt, transport, research, protocol and participation tests. These suites overlap; do not add them as a unique total. Saved reading IDs, revision hashes and explicit occurrences are verified in the model prompt.
- A local two-browser fixture used real SQL and message handlers in a transaction. In a 37-message conversation, own-send revealed the exact accepted ID and a peer arrival preserved scroll. A 548-character repeated paragraph persisted as occurrence 1, reloaded, highlighted only the second paragraph and drew its physical connector. Selecting “right causal link” in a human thought preserved an existing draft and persisted the contextual request under the exact parent with the source quotation. Zero browser page errors. Fixture servers stopped; rollback left zero room rows.
- Authenticated public-origin candidate checks used real room GET data and candidate assets, with mutations blocked. Twenty-one layout states and twenty-one quoted-draft states passed at seven viewport sizes; full real-article selection passed at three sizes. These are browser/geometry evidence, not physical-device or two-human acceptance.

Evidence staging: `/tmp/dialectic-context-proof`, `/tmp/dialectic-branch-proof/tests.log`, `/tmp/dialectic-full-passage-tests.log`, `/tmp/dialectic-full-passage-frontend.log`. The verified release and archive are recorded below.

## Limits and next work

1. **Observe the actual iPad session.** Amo highlights a full paragraph; Dan replies; Amo selects Dan's words and asks for evidence. Open/close the native keyboard, use selection handles and return later in the installed PWA. Physical Safari/IME, device update and owner/Dan acceptance remain unobserved.
2. **Make the map useful in a long argument.** Add search by person or phrase, focus the actual ancestor path and cited sources, and restore the exact selected message/passage and draft on return. Show aggregated branches when zoomed out. Do not infer agreement or opposition from reply edges.
3. **Bring retrieved evidence into the branch.** Put concise attributed excerpts and Open original beside the addressed thought, with explicit Save to room. Offer source-window continuation from the precise quoted revision; surface a changed-source mismatch instead of silently switching evidence.
4. **Multiple simultaneous manual research streams.** Ordinary addressed turns share a thread lock. Separate Summon/Research can still overlap the frontend's single provisional stream slot; alternating long streams can lose partial accumulation until their complete persisted messages arrive. Replace that slot with per-ID stream state before expanding concurrent research. Final persisted answers retain their correct text and parents.
5. **Radical direction:** give reading rooms no global bot speaking position. Human actions summon one compact evidence/challenge answer into a branch; long research becomes a source beside it. Keep inferred contradictions and changed minds as attributed proposals humans can inspect.

## Rollback boundary

Previous source HEAD: `e1164f430499e4331c96db418d1e0b8b4fa9256f`. Previous selected frontend: `/var/www/dialectic-releases/20260908T205525Z-usability-repair-09dfbc3`.

No migration or dependency/config change is required. Restart only Dialectic after a clean implementation commit; keep Defuddle and trading processes unchanged. Frontend rollback atomically restores the retained previous symlink, tests nginx and reloads it. Backend rollback reverts the implementation commit in a clean checkout, then restarts Dialectic. Never reset, stash or clean concurrent work. Older frontend quote creation remains compatible; stored new long/repeated anchors retain their metadata in SQL.

## Verified deployment

Implementation commit: `216165fa90eed1d3fbcc2c0e974efe43504ecf4a`. Selected frontend: `/var/www/dialectic-releases/20260908T212716Z-contextual-discussion-216165f` through `/var/www/dialectic-current`. Source tree was clean before the Dialectic restart and immutable frontend flip. No migration.

Dialectic PID `3591527` replaced `3543878`; Defuddle retained `3543860` and trading retained `1970559`. Public HTML/JS/CSS/manifest/worker hashes match the release. Database, Redis and scheduler health passed. The deployed public room passed 21 layout states at seven sizes with zero page errors; ordinary-room trading-structure 409 is expected. Stationary-pointer opacity remained 1 with and without hover. Three full real-article selection/draft checks passed against the deployed assets with all production mutations blocked.

Fresh read-only source probes returned the complete 20,303-character article and its 18,000–20,303 continuation, three authenticated Reddit search results, a 9,159-character post with eight sampled comments, and one exact linked comment. The reading room remains excluded from scheduled morning briefs.

Qualification scripts, logs, browser screenshots, public proofs, release hashes and rollback coordinates are archived at `/var/backups/dialectic/20260908T212716Z-contextual-discussion-216165f`. A documentation-only closeout commit follows this implementation release; it needs no restart. Physical iPad/Safari and owner/Dan acceptance remain open.

## Amendment — cross-platform map and stream continuation, 2026-09-08

The owner clarified that Mac/Windows desktop, iPad, Android and iPhone are equal product targets. Earlier iPad-specific acceptance notes describe historical testing gaps, not product scope. Map navigation and simultaneous-stream work now continue in [the cross-platform handoff](2026-09-08-map-navigation-concurrent-replies.md); prefer its behavior and current qualification/release evidence over the corresponding open items above.
