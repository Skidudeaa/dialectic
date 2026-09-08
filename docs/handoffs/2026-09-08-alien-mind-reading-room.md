# Handoff — 2026-09-08: An Alien Mind reading room

Owner feedback and the subsequent repair supersede this delivery snapshot. Resume from [the usability repair handoff](2026-09-08-reading-room-usability-repair.md).

## Resume here

The reading-room repair and passage-thread implementation are committed and deployed. This handoff records the shipped behavior, its limits, and the next product work. The roadmap below is proposed work, not implemented functionality.

Open the actual room: https://dialectic.somacura.org/?room=d428ffef-1902-4f22-9771-5b5765aa73bb&thread=52bbd568-e947-4186-ac30-4168d447e197&scene=surface

The owner wants to explore OpenAI's **An Alien Mind** with Dan. Their controlling requirements are:

- Reddit-style thought threads, vertically compact enough to see more discussion.
- Highlighted article passages physically connected to the corresponding thread or cited comment.
- “Screen realestate is paramount.” “I can't think without context.”
- Bring in other sources, link outward, and tell Dialectic exactly which part of either person's thought or a source to investigate and pull.
- An explorable mind map.
- A readable article and an unobstructed composer, including while the tablet keyboard is open.

The owner rejected the live room when the article was confined to a narrow rail and bottom updates covered the message/composer. Earlier interactive design studies were not product delivery. Continue from the reachable application and its real content.

## Delivery state

| Item | Verified state |
| --- | --- |
| Branch / remote | `master`; `origin` is `git@github.com:Skidudeaa/dialectic.git` |
| Layout implementation | `ad62754ed40222556bfb59a968552785305a9dd2` |
| Threads/map implementation | `277f2379bb161a87d05da427d0016cd612ea02bf` |
| Release verification record | `2fb622f` and `JOURNAL.md` |
| Selected frontend | `/var/www/dialectic-releases/20260908T051234Z-passage-threads-277f237` |
| Serving symlink | `/var/www/dialectic-current` |
| Immediate rollback release | `/var/www/dialectic-releases/20260908T034648Z-reading-layout-ad62754` |
| Qualification archive | `/var/backups/dialectic/20260908T051234Z-passage-threads-277f237` |
| Backend | `dialectic.service`, PID `887261` at verification |
| Trading | `tradingdesk.service`, PID `1970559` at verification |

The implementation was deployed before this handoff. The handoff/push closeout freshly verified the selected release, public HTML/JS/CSS/manifest/service-worker hashes, healthy DB/Redis/scheduler, and unchanged service processes. Documentation-only commits after `277f237` do not change the frontend artifact. See the closeout commit containing this document and verify `origin/master` when resuming; publication follows that commit.

Room: `d428ffef-1902-4f22-9771-5b5765aa73bb`. Root conversation: `52bbd568-e947-4186-ac30-4168d447e197`. Reading: `6f4ca8ab-ade9-48db-ab6a-2e91e5884233`. The room already exists with Amo and Dan; do not recreate it or populate it with sample conversation.

## What shipped

Ordinary rooms without thesis/geography reservations use the available workspace for conversation and reading. A sole reading opens once; All sources remains usable. The article gets approximately 55% of the split and spans the discussion composer. Updates open beside discussion on larger screens and as a reversible inspection view on phones. The mounted draft survives inspection and view switches.

Ordinary rooms start in **Threads**. Independent root thoughts quoting the same source, normalized passage, and revision share a passage thread. Replies remain under their actual ancestors, including replies citing a different source. Known parent context and identical source quotations are rendered once; other citations, missing-parent notices, media, reactions, marks, proposals, editing, deletion and forking retain the existing message implementation. Reply is in the byline; secondary actions are behind the per-message `···` disclosure. Nested replies can collapse.

Selecting source text offers **Discuss this passage**. While replying, **Attach passage to reply** preserves the parent; **Start a new thread** explicitly clears it. Exact quotes and source hashes use the existing backend validation. Highlights navigate to the matching discussion. The connector is measured from the visible thread header or additional citation inside a reply to the actual rendered source highlight.

**Map** opens an expanded workspace with source → passage → thought/reply relationships. It supports scrolling, zoom, opening the article, and jumping from a thought back into its thread. Edges represent saved citations and reply ancestry. The map does not infer support, opposition, agreement, or a change of mind.

The shared Markdown renderer remains sanitized and is memoized so unrelated conversation updates do not replace the article DOM. Highlight painting waits while a source selection is active. Repeated or changed passages retain their quotation without guessing a physical location.

## Code map and contracts

All frontend paths below are under `dialectic/frontend/app/src/`.

| File | Responsibility / invariant |
| --- | --- |
| `components/workspace/surface/SurfaceScene.tsx` | Default view, room layout, staged references, source selection, updates and scene integration. Preserve bound-room behavior. |
| `components/workspace/surface/SurfaceConversation.tsx` | One mounted composer, reply ownership, source/thread navigation, measured connector, expanded map. |
| `components/workspace/surface/surfaceModel.ts` | Passage grouping over actual reply ancestry and loaded messages. |
| `components/workspace/surface/shapes/ShapeDiscussion.tsx` | Compact branches, map nodes/edges, jumps, collapse state and visible-message receipts. |
| `components/workspace/surface/shapes/SurfaceMessage.tsx` | Delegates to the complete message implementation. |
| `components/chat/MessageBubble.tsx` | Shared message content/actions; thread context removes repeated quotation and parent chrome. |
| `components/workspace/surface/SurfaceEvidence.tsx` | Library/detail fetch, selection, highlight painting, attach/start distinction and revision notices. |
| `components/workspace/focus/ReadingFocus.tsx` | Sanitized, memoized `RenderedMarkdown`; also used in Focus. |
| `lib/passageAnchor.ts` | Whitespace normalization, unique DOM quote ranges, inline-markup-safe marks and passage identity. |
| `components/workspace/surface/Surface.css`, `shapes/shapes.css` | Reading allocation, density, connectors, map, short-viewport navigation. |
| `components/layout/AppLayout.tsx` / `.css` | Prior layout repair's visual viewport fit and outer application geometry. |

Backend boundaries: `dialectic/proposal_intake.py` validates at most 12 references and deduplicates by `(entity, id)`. `quote` is accepted only for `reading_items`, with a 300-character limit. It preserves valid `content_sha256`; it does not persist a source occurrence index. Therefore multiple different passages from one reading in a single message and durable quotations of human messages are **not supported by this reference contract**. Do not invent extra client fields and assume they survive ingestion.

Keep these invariants during future work:

- Draft, reply target, research destination and receipts belong to a specific room/thread. A late result must never consume a newer draft or land in the room the user subsequently opened.
- Scroll the article or discussion pane locally. Page-wide `scrollIntoView` can move the composer out of view.
- Ambiguous text and revision drift must remain explicit. The older message-annotation locator can fall back to a first occurrence; the physical source link deliberately requires a unique match.
- Reading hashes identify the quoted version. Preserve historical quotations through edits.
- Source rendering must remain sanitized; incoming messages must not replace active selections.
- Compactness must retain provenance and access to actions. Do not create a stripped-down second message renderer.
- Keep the graph and source library honest about what is loaded and what is saved.

## Verification and its limits

Implementation qualification passed **727 frontend tests**, ESLint, TypeScript/Vite/PWA build, and the lazy-Cesium gate. Commands, from `dialectic/frontend/app`, were `npm test`, `npm run lint`, and `npm run build`.

The isolated browser fixture used real SQL and message handlers in `dialectic_test`, with two browser participants. It verified selection → persisted quote → peer reply → reload, nesting/collapse, map navigation, draft survival, a peer contribution during active selection, explicit new-root ownership, and another source attached to an existing reply. That second source retained its own quotation, physical connector and map citation. Model calls and notifications were disabled in this fixture. Its transaction rolled back; its room/user row counts were verified as zero, and fixture servers stopped.

A matched two-message passage discussion measured **303.53px** in Threads versus **504.73px** in Stream: **40% less height**. This is one controlled fixture, not a universal reduction claim.

Full authenticated application checks used seven viewports: 1824×1368, 1368×1024, 1024×768, 820×1180, 390×844, 1024×480 and 390×480. There were 21 candidate layout states, 21 isolated quoted-draft states, and 21 post-deployment public states, with no page errors. The actual article measured approximately **857px** at the owner's screenshot width and **557px** at 1024px. Public inspection blocked mutation requests and live WebSocket traffic; production received no test contributions. The ordinary room's trading-structure HTTP 409 is its expected unbound response.

Evidence is in the qualification archive: build/test/lint logs, `sha256.json`, `release.json`, and `proof/` with browser scripts, screenshots, `browser.json`, `cross-source.json`, `geometry.json`, `candidate.json`, `interactive.json`, `public.json`, `public-assets.json`, and `rollback.json`. The temporary fixture entry files were removed from the checkout; archived copies explain the harness. Full Chromium was used; the earlier headless-shell runner was unstable during viewport changes.

**Still unverified:** physical iPad Safari/PWA selection handles, real keyboard/safe-area behavior, reconnect/offline races in this new workflow, and an actual Amo/Dan discussion. Synthetic participants are not human acceptance. The map operates on supplied/loaded messages, not an independently complete history projection.

## Next: make the room excellent

### 1. Finish the reading desk on the actual iPad

The outer app still spends substantial height on navigation, notification prompts and a generic Surface masthead. The archived phone keyboard screenshot also shows crowded outer scene labels. These are concrete follow-up observations, not fixed by the thread renderer. Field-mark explanation/control density deserves inspection with the real Amo message, too.

Make the source, current branch and composer the stable center of the room. Collapse secondary chrome without hiding access to existing destinations. Give the reader an explicit article-focus/split control; preserve text size when resizing. Keep the active source quote and reply parent inspectable during deep-branch navigation. On a phone, use a compact context strip that can reopen the exact source location.

Acceptance: inspect the reachable public origin on the owner's device with the actual article, long human messages, quoted drafts, expanded replies, updates, and keyboard open. No covered text, overlapping navigation or page-level scroll jumps. Measure readable article area and visible contributions against the archived baseline. Compare identical content and state, not hand-picked empty screens.

### 2. Build “find and pull this” as the next substantive feature

Example: select “the LLM chain of thought is no longer going to be in human words” in Amo's actual message and ask, “Find the Anthropic paper I mean; pull the relevant passage and anything that challenges this interpretation.” The request must carry the exact selected words, speaker, full surrounding thought, source if applicable, and destination branch. Return an inspectable quotation, original link, publication metadata and a concise explanation of its relevance. Keep the user's interpretation separate from the source's words.

Start by tracing `llm/tools.py`, `llm/tool_loop.py`, `proposal_intake.py`, message ingestion and `api/reading_relay.py`. Existing tools include `search_transcript`, `search_memories`, `search_reading`, `read_article`, and `save_reading`. `read_article` fetches a supplied URL; that is not general web discovery. The inspected registry contains no tool named `search_web` or `web_search`; verify the full current capability path before selecting a real discovery integration. Never simulate successful research with canned results or an invented API.

`save_reading` currently returns a proposal; human acceptance files the fetched source. Preserve that behavior unless the owner explicitly changes it. New human-message excerpt support needs a concrete backend contract for message identity, attribution, exact selected text and its version, plus ingestion/round-trip tests. Coordinate this with the existing one-ref-per-source limitation instead of silently dropping a second passage.

Deliver one complete vertical slice: select → contextual instruction → real retrieval → inspect exact passage → attach to the intended reply → peer sees it → reload preserves it. Show retrieval failures, ambiguity and incomplete extraction directly. Add cancellation, safe retry, and late-result destination checks. Pass simultaneous requests and room-switch/reconnect tests before broadening the UI.

### 3. Make the map useful at 100 thoughts

The shipped map is a navigable projection with fixed columns and scroll/zoom controls. Next add fit-to-branch, focus on a selected thought and its sources, hide/reveal branches, a locator for offscreen context, and stable camera/layout behavior as new messages arrive. Keep a legible text scale; fitting the entire room into unreadable nodes repeats the original tiny-article failure.

Expose history completeness and fetch missing ancestry when needed. Use realistic long discussions to find the threshold for virtualization or server-backed branch loading. Test unread/seen behavior when branches are collapsed, nodes are hidden, the tab is backgrounded and the message window changes. Do not label unloaded history as an empty discussion.

Acceptance: navigate a 100-thought, multi-source discussion; identify what prompted a selected reply; inspect the exact cited passage; return to the same draft and branch without hunting. New activity must not jerk the map camera or steal the reader's source position.

### 4. Make disagreement and changed minds first-class

**Contrarian product bet:** more AI output is not the win. Make the room better at exposing the smallest unresolved difference between Amo and Dan.

Propose a compact “what would change your mind?” question attached to a specific claim. Let each person explicitly mark a source as supporting, challenging, qualifying, or irrelevant to that claim. Preserve attribution and evidence; do not promote the model's guess into a shared relationship. A later change-of-mind note should say whose view changed, which claim changed, and which passage or exchange mattered.

A second strong direction is a “what changed since I was here?” return view: new replies on followed passages, newly attached sources, unresolved questions and explicit belief revisions. Keep this bounded and source-linked so returning to the room feels like resuming a thought, not reading an automated meeting recap.

These are proposals. Explicit relationship semantics and persisted belief history need design and schema review before implementation.

## Operational closeout / restart instructions

Read `JOURNAL.md`, root `CLAUDE.md`, and `dialectic/CLAUDE.md` before editing. The older September 3 handoff describes an earlier Surface; this document supersedes its four-shape/plain-message limitations for the shipped reading-room work.

The checkout intentionally retains unrelated untracked `.claude/`, `.design-studies/`, `AGENTS.md`, `IMG_0197.PNG`, `companion-ui-dialectic-0.1.0.tar.gz`, and `docs/diagrams/gods-eye-integration.visual-check.*` artifacts. Do not stage, delete, reset or sweep them into a release. Design studies under `.design-studies/alien-mind/` contain illustrative interaction/research; they are not production acceptance evidence.

Both backend services execute their git working trees. This release needed no migration or backend restart. Future frontend delivery is build → immutable release directory → atomic serving-symlink replacement → tested nginx reload → public-origin proof. Keep the prior release and exact rollback coordinates. The archived deployment script contains expected-state guards for its historical run; inspect and update those guards before any future use.

To roll back this frontend, first verify the currently selected release, validate nginx configuration, atomically point `/var/www/dialectic-current` at the immediate rollback directory above, reload nginx, and verify public asset hashes and health. Do not restart the backend as a substitute for publishing or rolling back static assets.
