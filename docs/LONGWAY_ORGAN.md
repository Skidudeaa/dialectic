# The Long Way organ: the contract

*Written 2026-10-28. This file is the single contract between the three builds that turn Dialectic into The Long Way's app server: the backend organ, the frontend organ shell, and the chart component. The proposal it implements is `/root/theLongWay/docs/moonshot-house.md`; the charter it serves is `/root/theLongWay/CHARTER.md` (sections cited as §NN). Nothing here changes Dialectic's behaviour when `DIALECTIC_ORGAN` is unset.*

## 1. The seam

One environment variable, `DIALECTIC_ORGAN`, read once at import: `trading` (the default, today's behaviour, byte for byte) or `longway`. `dialectic/organ.py` exposes the active organ; `dialectic/organs/trading.py` and `dialectic/organs/longway/` implement the same five hooks.

| Hook | trading | longway |
|---|---|---|
| `tools(room, db) -> list[Tool]` | `_build_trading_tools(room)` moved here unchanged | `organs/longway/tools.py` |
| `base_identity() -> str` | `PromptBuilder.BASE_IDENTITY` as it is today | the Scout, built from the charter's text (§4 below) |
| `register_jobs(scheduler)` | the sixteen registrations now at `api/main.py:252-267` minus the two shared ones | `sunday_dispatch`, `evidence_writer` |
| `routers() -> list[(router, kwargs)]` | trading relay, thesis relay, trading ingest, and the `/rooms/{id}/trading/*` family | `organs/longway/api.py` router |
| `name` | `"trading"` | `"longway"` |

Shared by both organs and never gated: everything else. Rooms, threads, events, memory, push, reactions, attachments, readings, `_build_dialectic_tools`, the Workshop (`run_code`, `start_job`, `workshop_job_watch`), `scheduler_heartbeat`, replay, analytics, auth, Home.

Off in the longway organ: `_build_trading_tools`, `_build_world_tools`, `_build_cairn_tools`, the morning brief, silence sweep, question round, round close, house forecast, news, wire, rss wire, congress watch, prediction watch, reading echo, field inference, world signal and world watch jobs, and the trading relay and ingest routers. Each stays importable; none is registered.

`GET /organ` (no auth): `{"organ": "longway", "name": "The Long Way", "participant": "Scout", "lede": "Go far enough to be surprised. Stay long enough to understand. Leave room to be changed."}` for longway; `{"organ": "trading", "name": "Dialectic", "participant": "Dialectic", "lede": null}` for trading. The frontend also carries the organ at build time as `VITE_ORGAN`; the two must agree, and the shell shows a one-line warning if they do not.

Tests that define done for the seam: with `DIALECTIC_ORGAN=longway`, `build_registry(room, db).tools` contains no tool whose name starts with `get_` from the trading set and does contain `read_register`; the scheduler registers exactly `sunday_dispatch`, `evidence_writer`, `workshop_job_watch`, `scheduler_heartbeat`; with the variable unset, the registry names and job names are identical to today's (`tests/test_tools_registry.py` keeps asserting 27 and passes unchanged).

## 2. The longway environment

```
DIALECTIC_ORGAN=longway
PORT=8004
DATABASE_URL=postgresql://localhost/longway
REDIS_URL=redis://localhost:6379/1
MEDIA_ROOT=/var/lib/longway/media
DIALECTIC_WORKSHOP_ROOT=/var/lib/longway/workshop
DIALECTIC_WORKSHOP_VENV=/var/lib/dialectic/workshop/venv      # shared read-only venv
LONGWAY_REPO=/root/theLongWay
LONGWAY_COMMIT_ENABLED=0            # evidence_writer appends and commits only when 1
LONGWAY_FIXES_URL=<the listener's public Blob URL for ships.json>   # see tools/live/ais.js STORE in the repo
LONGWAY_TRAINS_URL=https://amtrak-live.vercel.app/api/trains?format=geojson
LONGWAY_DISPATCH_MODEL=claude-opus-5-5
ANTHROPIC_API_KEY, VAPID_*, JWT_SECRET_KEY, ALLOWED_ORIGINS: this instance's own
SIGNUPS_ENABLED unset
```

## 3. The register: what the repo gives the organ

`organs/longway/register.py` imports `tools/longway.py` from `LONGWAY_REPO` with `importlib` (the file takes `root: Path` on every function and has no dependencies) and calls:

- `chart_data(root)`: every candidate as the globe draws it, each trip whose record says `"shared": true` through an allowlist, and the registered vehicles. Shape in §5. Run `python3 /root/theLongWay/tools/longway.py chart` to see the real output; it is the fixture for the chart.
- `atlas_data(root)`: per-record prose highlights (`pull`, `journey`, `questions`), evidence counts, `path`, `body`.
- `check(root)`: run after every write; a nonempty error list aborts the write.
- `today()`, `obj()`, `put_json()`, `local()`.

The organ reads the dossier (`candidates/<slug>/dossier.md`) and the full `evidence.jsonl` for the Library through `local(root, …)`; it never reads `trips/*/evidence.jsonl` or `trips/*/plan.md` sections other than Established and Undecided of a shared trip, and never `private/`, `inbox/`, `scratch/`.

Writes to the repo happen in one function, `register.append_evidence(candidate_slug, row, author_name, author_email)`: next free `S<n>` id, append the line to `candidates/<slug>/evidence.jsonl`, run `check`, `git add` that one file, `git commit --author` with a message `Evidence <slug> S<n>: <claim, 72 chars>` and the trailer `Confirmed-In: The Long Way house`. It runs only when `LONGWAY_COMMIT_ENABLED=1`; otherwise it raises `CommitsDisabled` and the caller leaves the proposal queued. It never pushes.

## 4. The Scout

`organs/longway/identity.py` builds the base identity at startup from the charter's own text, read from `LONGWAY_REPO/CHARTER.md` by heading: the whole of `## 03`, the "five useful questions" of `## 05`, "Name the actual failure mode" from `## 12`, "Four kinds of material" from `## 14`, the statuses and "Freshness follows the decision" from `## 15`; plus the "Evidence before confidence" and "Boundaries" sections of `AGENTS.md`. Then these rules, verbatim:

```
You are the Scout, the third chair in The Long Way, a room where close friends plan journeys together.
You are a participant, not an assistant: speak when you have something, stay quiet when you do not.
Plain prose. No brochure voice, no doctrine, no lists of adjectives. Short answers to short questions.
Every fact you state carries its evidence id (S1, S14) or the words "unknown" and what would settle it.
A published offering is not availability; a position is not a timetable; a reaction is not a decision.
You never book, pay, contact anyone, invite anyone, set a status or promise access. You propose; people confirm.
Each friend may decline anything without a reason, and you never count, rank or tally the friends.
```

The room's `global_rules` and `global_ontology` are appended as today (`llm/prompts.py:714-717`). The persona exclusions (provoker, facilitator, annotator) are unchanged.

## 5. The chart projection

`GET /rooms/{room_id}/longway/chart` (JWT, room token, membership, like every room read) returns `chart_data()` plus what only the server knows:

```jsonc
{
  "generated": "2026-10-28",          // chart_data: the repo's date
  "fetched_at": "2026-10-28T06:10:00Z",
  "name": "The Long Way",
  "room": { "id": "<uuid>", "linked_journey": "ogasawara" | null, "is_home": false },
  "rooms": [ { "id": "<uuid>", "name": "Ogasawara", "linked_journey": "ogasawara" } ],   // rooms the viewer belongs to
  "journeys": [ {
      "slug": "ogasawara", "kind": "candidate" | "trip", "title": "...", "where": "...", "status": "researching",
      "feasibility": "unverified", "judgment": "promising but underdeveloped" | null,
      "season": { "good": [9,10], "possible": [8,11], "avoid": [], "basis": "hypothesis" | ["S1"], "note": "..." } | null,
      "days": [6, 12] | null, "route": [[35.65, 139.76, "Tokyo (Takeshiba)"], ...],
      "pull": "...", "journey": "...", "questions": ["..."],
      "segments": [ { "from": "Tokyo (Takeshiba)", "to": "Chichijima", "ink": "dashed", "basis": ["S1"] } ],
      "window": { "start": "2027-08", "end": "2027-11" }        // trips only
  } ],
  "sources": { "ogasawara": { "S1": { "claim": "...", "status": "verified", "publisher": "...", "url": "https://...",
                                       "checked_at": "2026-10-09", "scope": "...", "recheck_days": 60 | null, "faded": false } } },
  "vehicles": [ { "journey": "ogasawara", "name": "Ogasawara Maru", "kind": "ship", "operator": "Ogasawara Kaiun",
                  "mmsi": "431347000", "imo": "9767687", "timetable": "https://...", "note": "...", "sourced": true,
                  "legs": [ { "from": "Tokyo (Takeshiba)", "to": "Chichijima", "points": [[35.65, 139.76], [27.09, 142.19]] } ],
                  "fix": { "lat": 35.6, "lon": 139.8, "at": "2026-10-28T05:12:00Z", "age_min": 58, "sog": 0.1,
                           "status": "moored", "place": null, "source": "ais" } | null,
                  "heard": true } ],
  "fixes_state": { "written": "2026-10-28T05:50:00Z" | null, "stale": false, "why": null | "listener silent 3 h" }
}
```

Ink values: `pencil`, `dotted`, `dashed`, `heavy`, `contradicted` (the globe's legend text is in `/root/theLongWay/templates/globe.html` lines 157-162). `heavy` is reserved: nothing produces it yet. Fixes come from `LONGWAY_FIXES_URL` (`{written, since, fixes: {mmsi: {lat, lon, ais_name, sog, cog, heading, status, fix}}}`, `fix` an ISO time) cached in process for 60 s; `stale` when `written` is older than 75 min, as `tools/live/api/vessels.js` does. Trains come from `LONGWAY_TRAINS_URL` for vehicles with an `amtrak` number. A vehicle the listener never heard has `fix: null, heard: false`; nothing is invented.

Other routes, all under `/rooms/{room_id}/longway/`, same auth:

- `GET journey/{slug}`: the journey as above plus `dossier` (the full markdown), `evidence` (every row of its `evidence.jsonl`, with `faded`), `vehicles`, and for a shared trip the `plan` sections Established and Undecided. 404 for a slug the chart does not show.
- `POST bind {"slug": ...}`: sets `rooms.linked_journey`; only a member with `can_manage_home` on the house; 404 for an unknown slug.
- `GET proposals`, `POST proposals {"candidate", "url", "claim", "scope"}`: the evidence proposals for the room's journey (§6).
- `GET confirmations`, `POST confirmations {"member_id", "binds", "confirmed_on", "channel"}`: the consent ledger of §19; POST needs `can_manage_home`.
- `GET dispatch/latest`: the latest dispatch message of the room, or 404.

## 6. Proposals, the Field and the writer

Migration `029_longway.sql`:

```sql
ALTER TABLE rooms ADD COLUMN linked_journey TEXT;
CREATE TABLE longway_evidence_proposals (
  id UUID PRIMARY KEY, room_id UUID NOT NULL REFERENCES rooms(id), created_at TIMESTAMPTZ NOT NULL,
  candidate TEXT NOT NULL, url TEXT NOT NULL, claim TEXT NOT NULL, scope TEXT NOT NULL,
  support TEXT, publisher TEXT, published_at DATE,
  proposed_by TEXT NOT NULL CHECK (proposed_by IN ('llm','human')), proposer_user_id UUID REFERENCES users(id),
  source_message_id UUID REFERENCES messages(id),
  written_sid TEXT, written_at TIMESTAMPTZ, written_commit TEXT, written_by UUID REFERENCES users(id)
);
CREATE TABLE longway_confirmations (
  id UUID PRIMARY KEY, room_id UUID NOT NULL REFERENCES rooms(id), member_id UUID NOT NULL REFERENCES users(id),
  binds TEXT NOT NULL, confirmed_on DATE NOT NULL, channel TEXT NOT NULL,
  recorded_by UUID NOT NULL REFERENCES users(id), created_at TIMESTAMPTZ NOT NULL
);
```

A proposal's review state is DERIVED from field marks, as everything in the Field is: `field_marks._SUBJECT_ENTITY_TABLES` gains `"longway_evidence_proposals": ("longway_evidence_proposals", "room_id", "id")`, and the existing write route `api/field.py` accepts marks whose subject is `{"entity": "longway_evidence_proposals", "id": <uuid>}` with the existing actions. `confirm` means "I read the page and the claim holds"; `contest` means "the page does not say that" and carries the note; `correct` supersedes with a better claim.

`evidence_writer` (60 s, `LONGWAY_COMMIT_ENABLED`): for each proposal with at least one `confirm` mark, no `contest` mark, and `written_at IS NULL`, call `register.append_evidence` with `status: "verified"`, `checked_at` the confirm mark's date, `publisher`, `support`, `scope`, `recheck_before: "set by the researcher"`, and stamp `written_sid`, `written_at`, `written_commit`, `written_by` (the confirming member). When commits are disabled the row waits and the Field shows "confirmed, waiting to be written".

The Scout's `propose_evidence(candidate, url, claim, scope)` tool: fetches the page through the existing `read_article` path (defuddle), requires the claim's key phrase to occur in the extracted text or returns `{"filed": false, "why": "the page does not contain …"}`, otherwise inserts a `proposed_by='llm'` row with `support` the matching passage (under 40 words) and `publisher` the page's site name, and returns the id. It never writes to the repo.

## 7. The dispatch

`sunday_dispatch`: `daily_at="08:00", daily_tz="America/Chicago"`, runs only when the local weekday is Sunday (the charter's recorded cadence, §16). For each room with `linked_journey` and at least one human message in the last 14 days, and for the house room, it posts one message from the participant with `metadata.longway_dispatch = {"journey": slug | null, "week_of": "YYYY-MM-DD"}` and pushes it to members (reuse `night_shift._post_brief_message` and `_push_brief` patterns, not their prose). Content, built by `organs/longway/dispatch.py` from the repo's git history of the last seven days (`git log --since=7.days -- candidates/<slug>` and the evidence diff between `HEAD` and the first commit older than seven days) and rendered by the model named in `LONGWAY_DISPATCH_MODEL` with the Scout identity:

1. What moved this week in the record (or "Nothing moved this week" in one line, and then nothing else).
2. The evidence that changed status, by S-number.
3. One question the group could decide, taken from the dossier's "Next decision" or the trip's Undecided section.
4. The last line, verbatim: `React with 👍 I'd go · 🚫 Not for me · ❓ Tell me more`.

No tallies, no names of who has not reacted, no probabilities.

## 8. The frontend organ

`src/organ.ts` reads `import.meta.env.VITE_ORGAN` (`'trading'` default) and exports `ORGAN`, `IDENTITY` (`name`, `shortName`, `participantName`, `signature`, `lede`, `originImprint`), `SCENES` and `benchLabel`. `lib/productIdentity.ts` derives `PRODUCT_NAME`, `PARTICIPANT_NAME` and `PARTICIPANT_SIGNATURE` from `IDENTITY` instead of literals. The longway identity: name `The Long Way`, short `Long Way`, participant `Scout`, signature `)`, lede the mantra above, imprint `The Long Way`. `vite.config.ts` sets the PWA manifest name, short_name, description and theme colour from the organ; `index.html` title likewise.

Scenes for longway, from `lib/workspaceRoute.ts::scenesForDestination`: ordinary rooms `record, bench, library, field, ledger`; Home root `house, record`. The scene id `bench` keeps its name in URLs; its label is "Chart" for longway (`benchLabel`). `surface`, `atlas`, `mirror`, Stakes, the trading cockpit, the World door and every "Dialectic"-specific affordance stay out of the longway shell. Trading rooms are untouched when `VITE_ORGAN` is `trading`.

The Bench for longway (`src/organs/longway/LongwayBench.tsx`) mounts the chart (`src/organs/longway/chart/Chart.tsx`, props in `src/organs/longway/types.ts`) over `useLongwayChart(roomId)` (`GET …/longway/chart`, refetch every 5 min and on the room's `message_created` with a dispatch), with the leg card beside or under it, "Without the mythology" as a toggle, and "Discuss this leg", which sends a human message through the existing send path with `metadata.longway_anchor = {"journey": slug, "leg": i}` and the text `About <from> to <to>:` for the person to finish.

House for longway: the chart with every journey (focus none), the viewer's rooms as a list with their journey, and for a `can_manage_home` member "Open a room for this journey", which creates a room through `POST /rooms` and binds it through `POST …/longway/bind`. A journey with a room links to it; one without shows its card from the chart data.

Library for longway: `GET …/longway/journey/{slug}` rendered as the dossier (markdown through the existing `marked` + DOMPurify path), the evidence ledger (S-number, claim, status with checked date, scope, publisher, link, faded shown as paled text with "past its recheck rule"), the vehicles with their last fix, and under them the room's readings as today.

Field for longway: today's Field plus a "Proposed evidence" section listing `GET …/longway/proposals` with the page link, claim, scope and passage, and Confirm / Contest / Correct through the existing Field write path with the proposal as subject; a row already written shows its S-number and commit.

Ledger for longway: the consent ledger (`GET …/longway/confirmations`, add for `can_manage_home`), and the shared trip's Undecided section as text. No spending arithmetic in version one.

Dispatch card: a participant message carrying `metadata.longway_dispatch` renders as a card at the top of the Record's day with the three reactions as buttons bound to the existing reaction API with emoji `👍`, `🚫`, `❓`; the counts are never shown, only the viewer's own reaction state.

Theme: when `ORGAN === 'longway'`, `src/organs/longway/theme.css` sets the room palette tokens from the globe's chart-table palette (`/root/theLongWay/templates/globe.html` lines 13-28: `--bg`, `--panel`, `--ink`, `--good`, `--pencil`, …, Libre Caslon for display and text, IBM Plex Sans Condensed for UI, light and dark). It maps onto the existing room-hue system rather than replacing it.

## 9. The chart component

`src/organs/longway/chart/Chart.tsx`, default export, lazy-loaded (`React.lazy`) so MapLibre (npm `maplibre-gl@^5.24`, `topojson-client`) is its own chunk, like Cesium. It is a port of `/root/theLongWay/templates/globe.html` (427 lines, read it whole): the same ink layers (pencil as two offset hairlines, dotted, dashed, contradicted; a casing over imagery; halo for the selected journey), the same label declutter (`facing`, `declutter`, `placeLabels`), stop labels for the selected journey, `applyFilters` for "Without the mythology", Esri World Imagery fading in from zoom 4.5, and the globe projection with rotation disabled. Coastlines: copy `/root/theLongWay/templates/land-50m.json` (Natural Earth 50 m, public domain, 545 KB) to `public/longway/land-50m.json` and fetch it once.

New in the port: `focus` dims every other journey; `vehicles` with a `fix` draw as a small vessel mark at the fix with a label "<name>, heard <age> ago" (hours or days when over 120 min; "never heard" vehicles are listed under the chart, not drawn); the card is NOT inside the component (the Bench renders `LegCard` and `SeasonStrip`, both exported from `chart/`, beside it); `onSelectJourney`, `onSelectLeg` and `onDiscussLeg` are callbacks. Reduced motion respected. Colours read from CSS variables once at mount, as the page does.

Tests (`Chart.test.tsx`, vitest + jsdom with `maplibre-gl` mocked): the features built from a projection carry one segment per route pair with its ink; myth mode hides pencil and dotted; a vehicle without a fix is not in the vessel source; `SeasonStrip` marks hypothesis seasons hatched; `LegCard` lists the basis rows with their status text.

## 10. Ownership

| Build | Owns | Does not touch |
|---|---|---|
| backend organ | `dialectic/organ.py`, `dialectic/organs/**`, `dialectic/migrations/029_longway.sql`, the `029` block appended to `dialectic/schema.sql`, `dialectic/tests/test_organ*.py`, `dialectic/tests/test_longway*.py`, `dialectic/.env.example` (append), and surgical edits in `dialectic/api/main.py`, `dialectic/llm/tools.py` (`build_registry` only), `dialectic/llm/prompts.py` (identity lookup only), `dialectic/field_marks.py` (one table entry) | `frontend/**` |
| frontend shell | `frontend/app/src/organ.ts`, `frontend/app/src/organs/longway/**` except `chart/`, `frontend/app/vite.config.ts`, `frontend/app/index.html`, `frontend/app/src/lib/productIdentity.ts`, `lib/workspaceRoute.ts`, `types/workspace.ts`, scene files under `components/workspace/scenes/`, `components/workspace/SceneSwitcher.tsx`, `components/workspace/WorkspaceSceneFrame.tsx`, `App.tsx` (minimal), `components/chat/MessageBubble.tsx` (the dispatch card and anchor line), `components/home/**` | `organs/longway/chart/**`, `dialectic/*.py` |
| chart | `frontend/app/src/organs/longway/chart/**`, `frontend/app/public/longway/**`, `frontend/app/package.json` and lockfile (adding `maplibre-gl`, `topojson-client`, `@types/topojson-client`) | everything else |

`frontend/app/src/organs/longway/types.ts` is committed before any build starts and is read-only for all three.
