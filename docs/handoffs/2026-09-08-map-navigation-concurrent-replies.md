# Map navigation and concurrent replies — 2026-09-08

Dialectic is a shared web/PWA product for Mac and Windows desktop, iPad, Android and iPhone. These are equal targets. Preserve readable source text, compact reply ancestry, full quotation provenance and draft continuity across mouse, trackpad, keyboard, touch, native selection and mobile keyboards. Browser-engine/viewport simulations are separate from physical operating-system/device and owner acceptance.

Continue in the existing [An Alien Mind room](https://dialectic.somacura.org/?room=d428ffef-1902-4f22-9771-5b5765aa73bb&thread=52bbd568-e947-4186-ac30-4168d447e197&scene=surface). Preserve Amo and Dan's membership, messages and saved article. Prior commit/deploy/handoff/push authorization persists. This follows [contextual reading discussion](2026-09-08-contextual-reading-discussion.md), implementing map navigation and independent concurrent answer state.

## Behavior

- **Search and focus:** search loaded discussion by person, phrase, source or full quoted passage. Focus shows the selected thought's actual ancestor path and citations, excluding unrelated siblings. Source/passage focus shows direct citing thoughts and their ancestry. No agreement, opposition or causal relationship is inferred from reply edges.
- **Readable map navigation:** Focus path and Show whole map use 100% scale. Fit view explicitly fits the graph; zoom, keyboard arrows, mouse dragging on the canvas and native touch scrolling support exploration. Source and passage cards retain revision/occurrence identity. Actual reply descendants can collapse. Query, selected focus, zoom and pan survive Map→Threads→Map.
- **Context on return:** opening a thought selects its own cited reading before revealing the exact message. Explicit passage navigation takes precedence over the thought's first citation. Draft text remains present; scrolling stays within the relevant pane. The selected map context exposes its complete scrollable text independently of the compact card. Actual pane size controls the dense layout: at most 150px high, or at most 190px when controls need two rows, Search/Context/Controls become explicit panels confined above the composer. Escape restores focus to the opener; choosing a search result focuses the map. The Surface workspace fills the remaining app height even when map content has no intrinsic size.
- **Concurrent answers:** each streamed message owns its text, timestamp, parent and metadata. Alternating tokens accumulate separately. An identified completion/error only settles its own answer; another unfinished answer remains mounted. Completed answers keep their DOM identity and gain persisted-message actions. Thread changes clear previous provisional state atomically.
- **Research identity:** research allocates its message UUID before streaming, then uses that same UUID for SQL, durable event and completion. The existing `stream_message_id` completion field remains. No schema migration or production dependency/config change.

The previous passage-selection, compact Reddit-style replies, idle-opacity, brevity, Defuddle and authenticated Async PRAW repairs remain in effect. This tranche does not add production contributions, trigger provider generations, write to Reddit or change room membership.

## Qualification and release

- Final frontend suite: **763 tests in 83 files**, lint, TypeScript/production/PWA build and lazy-Cesium gate passed. Research: 14 focused tests passed. The map animation-frame and compact keyboard-focus regressions failed before their fixes and passed afterward.
- Isolated Chromium 143, Firefox 144 and WebKit 26 runs exercised real frontend reducers over scripted interleaved WebSocket events, SQL persistence/reload and stable DOM identities. Each preserved two answers under their correct parents when the other completed. These are transport/UI replays, not live provider generations.
- Map fixture checks retained exact root/child ancestry and both cited sources, excluded unrelated branches, collapsed actual descendants, opened the thought's own cited article/physical passage link, and restored the draft/query/focus/zoom/nonzero pan. A separate real PostgreSQL call to research persistence verified original message UUIDs in both SQL rows and durable events. Fixtures stopped and rollback left zero room rows.
- Final authenticated public-origin candidate checks passed **108 layout states and 24 full-paragraph selection workflows** across Chromium, Firefox and WebKit. The nine layout profiles cover mouse/keyboard desktop and touch tablet/phone contexts, 1824–390px widths, two phone widths and 480px reduced height. Selection checks selected the complete 649-character real article paragraph, retained the draft/quote through Map↔Threads, and kept the composer clear. Compact Context exposed a complete 1671-character saved contribution through its own scroll area. Actual pointer clicks, keyboard navigation and emulated taps were exercised; native selection handles and software keyboards were not.
- Production probes use real room GET data with all mutations blocked and WebSockets closed or replaced by a local sink. Zero browser page errors; the ordinary-room trading-structure 409 is expected. Engine checks run on Linux and do not establish Mac/Windows or mobile OS/device acceptance, installed-PWA update behavior, or Amo/Dan acceptance.

Evidence staging: `/tmp/dialectic-map-stream-proof`. The immutable release, public proof and durable archive are recorded below.

## Boundaries and next work

1. **Put retrieved evidence beside the addressed thought.** Render concise attributed excerpts, Open original and explicit Save to room in the branch. Preserve the exact selected source revision/occurrence; a changed-source mismatch must remain visible. Keep raw tool payloads in expandable details.
2. **Make overview scale useful.** Aggregate branches into inspectable clusters when zoomed out, with human/source counts and an explicit expansion path. Search labels its loaded-discussion scope; add server search of older unloaded history with an exact path back to the saved thought.
3. **Finish generation-scoped activity.** Tokens, answers and identified errors now have independent ownership. Pre-token thinking/tool activity and explicit cancellation still use thread-level events; generation IDs should extend through those events before adding per-answer Stop. The research composer guard remains unchanged.
4. **Exercise real workflows on all five platforms.** Read/select/comment/reply/retrieve/map/return, with mouse/trackpad and keyboard on Mac/Windows, and native selection handles, soft keyboards and installed PWA lifecycle on iPad/Android/iPhone. Observe Amo/Dan collaboration and reload/update behavior. Engine simulation does not establish that acceptance.
5. **Reclaim the room header deliberately.** Add an explicit reading focus mode that gives the article/discussion/map the screen while retaining a clear route back to room controls. Never tie visibility to pointer presence or inactivity.
6. **Radical direction:** remove the global bot speaking position from reading rooms. A human summons one compact evidence or challenge answer into a branch; long research becomes an inspectable source beside it. Treat inferred contradictions and changed minds as attributed proposals for humans to review.

## Rollback boundary

Previous source HEAD: `4143759703711099238097e60436a7c2fe30f1e1`. Previous selected frontend: `/var/www/dialectic-releases/20260908T212716Z-contextual-discussion-216165f`.

Restart only Dialectic after a clean implementation commit; preserve Defuddle and trading processes. Frontend rollback atomically restores the retained previous symlink, checks nginx and reloads it. Backend rollback reverts the implementation code paths in a clean checkout while retaining newer handoff/platform guidance, then restarts Dialectic. Do not reset, stash or clean concurrent work. No migration. Older clients still receive the same research completion fields; stream and persisted IDs now coincide.


## Verified deployment

Implementation commit: `e6b7bbdecd97d5333da8a6f9ed6d901208c7d3e6`. Selected frontend: `/var/www/dialectic-releases/20260908T221959Z-map-streams-e6b7bbd` through `/var/www/dialectic-current`. Tracked source was clean before the Dialectic restart and immutable frontend flip. No migration or production dependency/config change.

Dialectic PID `3692256` replaced `3591527`, serving `/root/DwoodAmo/dialectic`. Defuddle retained `3543860`; trading retained `1970559`. Public HTML, JavaScript, CSS, manifest and service-worker hashes match the release. Database, Redis and scheduler health passed.

The **deployed public origin**, with no candidate asset substitution, passed the same **108 layout states and 24 selection/draft workflows** across Chromium, Firefox and WebKit. Complete quoted draft context, 1671-character compact context, map search/focus/navigation/restoration and composer bounds passed, with zero page errors. All production mutations remained blocked. These are Linux engine/input/viewport simulations; physical Mac/Windows/iPad/Android/iPhone, installed-PWA lifecycle and Amo/Dan acceptance remain unobserved.

Qualification scripts, logs, screenshots, public proofs, release hashes and rollback coordinates are archived at `/var/backups/dialectic/20260908T221959Z-map-streams-e6b7bbd`. The previous frontend remains retained at `/var/www/dialectic-releases/20260908T212716Z-contextual-discussion-216165f`. A documentation-only closeout commit follows this implementation release and needs no restart.

## Amendment — evidence beside thoughts, 2026-09-08 (late)

Next-work items 1 (evidence beside the addressed thought), the aggregation half of 2 (overview clusters) and the summons half of 6 (Challenge beside Find and pull) continue in [evidence beside thoughts](2026-09-08-evidence-beside-thoughts.md); prefer its behavior and evidence over the corresponding items above. Server search of older history, generation-scoped Stop, physical-platform acceptance and reading focus mode remain open.
