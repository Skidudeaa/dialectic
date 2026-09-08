# Reading room usability repair — 2026-09-08

The owner rejected the previous release as marginally usable. This repair addresses observable failures in that release; prior test counts were not acceptance. Continue from the public room with actual content, never a design study or synthetic chat presented as delivery.

Room: https://dialectic.somacura.org/?room=d428ffef-1902-4f22-9771-5b5765aa73bb&thread=52bbd568-e947-4186-ac30-4168d447e197&scene=surface

Amo and Dan are the existing members. Preserve the room, messages and saved article. Do not recreate or seed it.

## What changed

- **Readable without hover:** `focus/Focus.css` had applied 55% opacity to every scene, even without an open Focus panel; hover restored only 85%. That rule is removed globally. Pointer inactivity must never imply inattention.
- **Comment where text is selected:** `SurfaceEvidence.tsx` listens for native `selectionchange`, pointer and keyboard selection. A nearby action quotes the selected passage and stages a main-conversation comment. The popup stays inside the article pane and puts its action first. Existing persisted quotes remain capped at 300 characters: a longer paragraph offers an explicitly labeled first-300-character excerpt. Repeated text is not guessed; choose a distinctive passage.
- **Actual reply ancestry:** source requests, article opening and external message jumps no longer force flat Stream. Threads receives both internal and external jump targets. Children and grandchildren have visible rails and indentation; collapsing a parent preserves its descendants. Original source/revision context remains with the thread; additional source citations remain on the relevant reply.
- **Less chrome:** ordinary reading rooms omit the duplicate Surface masthead. Field marks fold behind one row, and old long bot posts' forecasting cards follow Show more. Review/forecast actions remain available. Make a move is under Message options in compact composers. Phone navigation and composition retain room for the discussion.
- **Bot restraint:** routine addressed replies track recent human length within 40–100 words; automatic replies within 24–60. Explicit detailed work, protocols and Research preserve extended output. Brief tool turns emit one final answer, while tool progress remains live. Exceeding the word ceiling produces a visibly abbreviated response, preferably at a sentence boundary. This changes short-answer streaming timing: final prose appears when complete.
- **Scheduled intrusions:** morning brief now requires Home or a linked thesis plus recent human activity; forecasting rounds require a linked thesis. Ordinary reading rooms receive neither job. Manual briefing and intended Home/trading workflows remain available. Existing noisy posts were not deleted.
- **Real source retrieval:** Defuddle was working for the OpenAI/Anthropic articles. Its Reader fallback treated an upstream 403 page as successful content and let an empty Title absorb URL Source; both are fixed. Article tool results now support exact-phrase lookup and continuation beyond the old first-6,000-character window, with a source hash fence.
- **Reddit:** `search_reddit` discovers/browses topics and `read_reddit` reads posts or exact comment permalinks using read-only Async PRAW. Existing `read_article` and human-approved filing route Reddit permalinks through the same authenticated extractor. Results retain author, date, original URL, vote count and parent IDs. Comment samples are explicitly bounded; linked external article bodies must be fetched separately. Valid short Reddit sources use the existing social-content threshold.

Example request: `@Dialectic find Reddit discussions about chain-of-thought faithfulness and pull the comments relevant to Dan's point.` The bot can search room history/readings for that point, then search/read Reddit and propose filing the source. Human acceptance remains the library write boundary.

## Qualification and limits

- Frontend: 729 tests, lint, production/PWA build and lazy-Cesium gate.
- Bot suite: 318 focused checks including real PostgreSQL scheduler eligibility, short reply persistence, fallback, protocol and Research behavior. Two isolated real Sonnet 5 calls finished naturally at 36/40 and 20/24 words. No test replies were posted in the production room.
- Source suite: 279 backend/source/SQL/news/wire checks and 19 sidecar checks. Suites overlap; do not sum their counts as unique tests. Live read-only API checks used the owner's existing Reddit application credentials.
- Two-browser fixture: real SQL/message handlers, exact quoted comment, Dan reply, grandchild, reload, collapse/reopen, physical source connectors, second source, map and retained drafts. Indentation at 1024px: 23→55→87px; at 390px: 23→45→67px. Fixture transaction rolled back; zero room rows remained.
- Public-origin candidate checks use real authenticated GET data and candidate static assets. All mutations are blocked; a local WebSocket sink enables draft-only checks. These establish geometry and application behavior, not actual two-human acceptance.
- Physical iPad/Safari selection handles, native keyboard/IME, installed PWA update, and owner/Dan acceptance remain unobserved. Do not call simulated touch a physical-device pass.
- Reddit comments are a loaded sample, up to 30, not exhaustive research. `/s/` share-token URLs require a real permalink or search. Credentials are application-only: no Reddit posting, voting or account messaging was added.

## Deployment and rollback

Deployment state and final public verification are recorded below after release. This release requires both `dialectic.service` and `defuddle.service` to restart after all tracked edits are committed; both run the shared working tree. Trading must retain its existing process. No migration is required.

Runtime preparation: Async PRAW 8.0.3 and its new dependencies installed for `/usr/bin/python3`. Existing `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT` were copied from the owner's existing configuration into gitignored `dialectic/.env`. Never print or commit values.

Qualification evidence: `/tmp/dialectic-usability-proof`, `/tmp/dialectic-source-proof`, `/tmp/dialectic-brevity-final.log`, `/tmp/dialectic-brevity-model-probe.json`; release archives preserve these before handoff.

Previous frontend: `/var/www/dialectic-releases/20260908T051234Z-passage-threads-277f237`.
Previous source HEAD: `6d4bc53c6691c48f7a6504c225e96e8e4a422f01`.

Frontend rollback: atomically repoint `/var/www/dialectic-current` to the retained previous release, test nginx configuration and reload nginx. Backend rollback: revert this implementation commit in a clean checkout, then restart Dialectic and Defuddle. Never reset/stash/clean concurrent work. The additional Reddit settings/packages can remain unused with old code. Verify public assets, health and service processes after either rollback.

## Next — highest-value work

1. **Physical reading session first.** On the owner's actual iPad, Amo selects a passage, Dan replies, Amo replies to Dan, the keyboard opens/closes, and each returns later. Watch where context disappears. Owner acceptance outranks these test counts.
2. **Find and pull at the thought itself.** Add a small action to selected human words or a passage. Pass exact quote, speaker, ancestry, source hash and room identity into retrieval; return a short attributed excerpt beside that thought, with Open original and human-approved Save. Search tools already exist; the missing piece is choosing context without restating it into a global prompt.
3. **Durable complete passage anchors.** Support entire paragraphs and repeated phrases using validated quote/prefix/suffix or occurrence plus revision identity. Preserve the original selected text when an article changes; never silently attach the first matching phrase. Today the 300-character unique-quote constraint remains explicit.
4. **A map that navigates a long argument.** Search/focus a person's claim, show its actual reply ancestors and source links, and return to precisely the same passage and draft. Aggregate by actual ancestry when zoomed out. Inferred agreement, contradiction and changed minds must be attributed proposals a human can inspect.
5. **Radical option: remove the bot's global speaking position in reading rooms.** Summon it into a particular branch with a concrete retrieval/challenge request. Keep one compact answer there; longer research opens as a source beside the discussion. This would make context selection and consent to interruption structural rather than dependent on a personality prompt.
