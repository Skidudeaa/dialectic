The Long Way frontend shell
==========================

Implemented paths (relative to frontend/app)

- `src/organ.ts`, `src/lib/productIdentity.ts`, `vite.config.ts`, `src/sw.ts`: build-time identity, Scout's signature, title, install manifest, notification default. The HTML transform leaves trading's input unchanged.
- `src/lib/workspaceRoute.ts`, `SceneSwitcher.tsx`, `SceneMasthead.tsx`: room Record / Chart / Library / Field / Ledger, Home House / Record. The URL keeps `bench`.
- `LongwayBench.tsx`, `src/hooks/useLongwayChart.ts`: room chart, focus, selected leg and sources, seasons, mythology toggle, editable discussion, room-scoped socket send with `metadata.longway_anchor`, five-minute and dispatch refresh. App composes the Record below the chart. CSS reserves 48svh for the sticky chart on phones.
- `LongwayHouse.tsx`: all journeys, viewer's room links, manager-only create then bind with the newly returned room token, navigation through the existing room navigator. A failed bind retains its created room for retry.
- `LongwayLibrary.tsx`, `src/hooks/useLongwayJourney.ts`: sanitized dossier, every evidence row, checked date, fading explanation, vehicle fixes/silence, followed by the existing readings library.
- `LongwayField.tsx`: proposed evidence plus the existing Field. Find or create the proposal's evidence-attachment mark, then confirm/contest/correct through the existing review endpoint. Corrections carry replacement subjects and claim; written rows show S-id and commit.
- `LongwayLedger.tsx`: confirmations, manager-only member/date/channel/consent form, and shared-trip Undecided text. Management is read from the viewer's Home membership.
- `DispatchCard.tsx`, `record.ts`, `MessageBubble.tsx`: dispatch first within its day; three reactions use the existing callback and expose only the viewer's selected state. No reaction counts or member names. Anchored contributions carry their journey/leg label.
- `LongwayRoomAccess.tsx`, `LongwayRoomContext.tsx`, `App.tsx`: room access, branches and household management without the trading Console, Stakes or World doors. Existing trading bodies remain behind the trading branch.
- `theme.css`: chart-table light/dark tokens and typography, loaded only for Long Way; `src/lib/releases.ts` adds the organ's glossary-linked release.

Chart integration

`chartSlot.tsx` is the only chart placeholder. It lazily imports `./chart/Chart`, shows “Chart loading”, and catches missing-module failure with “Chart unavailable”. Vite supplies a throwing virtual module only while the chart file is absent. No files were created under `chart/`; `types.ts` was not edited. The named card props were checked against the chart worker's `Cards.tsx` at `/root/scratch/omc-build/jobs/ea9d365c5830/tree/dialectic/frontend/app/src/organs/longway/chart/Cards.tsx`: LegCard takes journey/index/sources and optional onDiscuss; SeasonStrip takes season/sources. The actual map was not mounted in this checkout.

Original fixture provenance

`__fixtures__/chart.json` is the unmodified stdout of `python3 /root/theLongWay/tools/longway.py chart`, captured 2026-10-28. Tests add only the server-owned room/freshness fields and absent-live-fix state. `__fixtures__/banda-library.json` contains the actual `candidates/banda-islands/dossier.md` and every parsed row of its `evidence.jsonl`. The current source has 39 rows, rather than the historical example's 27. Tests verify all supplied rows; the UI has no fixed evidence limit.

Verification

- Trading full suite: 88 files, 797 tests passed (784 existing tests unchanged, 13 new Long Way tests). `/tmp/longway-shell-2535ed84/tests.log`.
- Focused final Long Way tests: 13 passed. `/tmp/longway-shell-2535ed84/focused.log`.
- Trading and Long Way `npm run build` passed, including TypeScript and `verify-lazy-cesium.mjs`. Final logs: `/tmp/longway-shell-2535ed84/build-trading.log` and `/tmp/longway-shell-2535ed84/build-longway.log`.
- `npm run lint` passed. `/tmp/longway-shell-2535ed84/lint.log`.
- Built manifest and HTML were inspected: The Long Way, short name Long Way, mantra description, The Long Way HTML/iOS title.
- Browser preview could not bind `127.0.0.1:4317`: sandbox `listen EPERM`. No browser, physical-device, live API, real chart rendering, or byte-for-byte baseline asset equivalence is claimed. Tests exercise real frontend request construction against mocked endpoints, not backend persistence.

Remaining integration boundaries

1. Largest functional gap: `dialectic/transport/handlers.py`, around `message_meta` at line 340, reconstructs metadata from tags/anchor/refs and ignores incoming `metadata.longway_anchor`. The frontend sends the requested shape, but this backend must validate the journey/leg against the room and preserve that field before the feature survives reload or reaches Scout. This file is outside shell ownership and was not changed.
2. `src/components/chat/MessageInput.tsx:86` still contains the visible Meta-tag tooltip “About Dialectic itself — architecture, direction”. It must derive the product name from identity for the strict no-Dialectic-wording requirement. It is outside shell ownership and was not changed. The sign-in identity, room-selector identity, header fallbacks, scene chrome and release text in owned scope are organ-aware.
3. The backend worker must supply the contracted Long Way endpoints and proposal subject allowlist. Writes and persistence have only frontend mock coverage here. Chart rendering remains the independently delivered worker's responsibility.
