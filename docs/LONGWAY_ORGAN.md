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

New in the port: `focus` dims every other journey; `vehicles` with a `fix` draw as a small vessel mark at the fix with a label "<name>, heard <age> ago" (hours or days when over 120 min; "never heard" vehicles are not drawn; they fold into one details line, "N vehicles never heard", floating in the chart's lower-left corner inside its box, with the stale-listener warning above it, and the globe's error line floats at the top of the box, so a host that fixes the chart's height never sees them spill below it); the card is NOT inside the component (the Bench renders `LegCard` and `SeasonStrip`, both exported from `chart/`, beside it); `onSelectJourney`, `onSelectLeg` and `onDiscussLeg` are callbacks. Reduced motion respected. Colours read from CSS variables once at mount, as the page does.

Tests (`Chart.test.tsx`, vitest + jsdom with `maplibre-gl` mocked): the features built from a projection carry one segment per route pair with its ink; myth mode hides pencil and dotted; a vehicle without a fix is not in the vessel source; `SeasonStrip` marks hypothesis seasons hatched; `LegCard` lists the basis rows with their status text.

## 10. Ownership

| Build | Owns | Does not touch |
|---|---|---|
| backend organ | `dialectic/organ.py`, `dialectic/organs/**`, `dialectic/migrations/029_longway.sql`, the `029` block appended to `dialectic/schema.sql`, `dialectic/tests/test_organ*.py`, `dialectic/tests/test_longway*.py`, `dialectic/.env.example` (append), and surgical edits in `dialectic/api/main.py`, `dialectic/llm/tools.py` (`build_registry` only), `dialectic/llm/prompts.py` (identity lookup only), `dialectic/field_marks.py` (one table entry) | `frontend/**` |
| frontend shell | `frontend/app/src/organ.ts`, `frontend/app/src/organs/longway/**` except `chart/`, `frontend/app/vite.config.ts`, `frontend/app/index.html`, `frontend/app/src/lib/productIdentity.ts`, `lib/workspaceRoute.ts`, `types/workspace.ts`, scene files under `components/workspace/scenes/`, `components/workspace/SceneSwitcher.tsx`, `components/workspace/WorkspaceSceneFrame.tsx`, `App.tsx` (minimal), `components/chat/MessageBubble.tsx` (the dispatch card and anchor line), `components/home/**` | `organs/longway/chart/**`, `dialectic/*.py` |
| chart | `frontend/app/src/organs/longway/chart/**`, `frontend/app/public/longway/**`, `frontend/app/package.json` and lockfile (adding `maplibre-gl`, `topojson-client`, `@types/topojson-client`) | everything else |

`frontend/app/src/organs/longway/types.ts` is committed before any build starts and is read-only for all three.

## 11. The Scout goes scouting (added 2026-10-28, 04:10 CDT; proposal `/root/theLongWay/docs/moonshot-scout.md`)

The house fills its own register. Questions from the rooms and the dossiers feed Scout runs; a run searches (when a provider is configured), reads, files proposals that are passages, searches for the contrary, and reports. Ink moves only through a person's confirm in the Field. Nothing here changes the trading organ.

### 11.1 Migration `030_longway_scout.sql`

```sql
CREATE TABLE longway_questions (
  id UUID PRIMARY KEY, room_id UUID NOT NULL REFERENCES rooms(id), journey TEXT NOT NULL, text TEXT NOT NULL,
  source TEXT NOT NULL CHECK (source IN ('human','reaction','message','dossier','scout')),
  source_message_id UUID REFERENCES messages(id), asked_by UUID REFERENCES users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  answered_by_proposal UUID REFERENCES longway_evidence_proposals(id), closed_at TIMESTAMPTZ, closed_by UUID REFERENCES users(id)
);
CREATE TABLE longway_scout_runs (
  id UUID PRIMARY KEY, room_id UUID NOT NULL REFERENCES rooms(id), journey TEXT NOT NULL,
  trigger TEXT NOT NULL CHECK (trigger IN ('manual','nightly')), started_by UUID REFERENCES users(id),
  started_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(), finished_at TIMESTAMPTZ,
  status TEXT NOT NULL CHECK (status IN ('running','done','failed','killed')),
  questions UUID[] NOT NULL DEFAULT '{}', pages_read INT NOT NULL DEFAULT 0, searches INT NOT NULL DEFAULT 0,
  proposals INT NOT NULL DEFAULT 0, counter_proposals INT NOT NULL DEFAULT 0,
  input_tokens INT NOT NULL DEFAULT 0, output_tokens INT NOT NULL DEFAULT 0, error TEXT, log JSONB NOT NULL DEFAULT '[]'::jsonb
);
CREATE TABLE longway_search_results (
  id UUID PRIMARY KEY, run_id UUID NOT NULL REFERENCES longway_scout_runs(id), provider TEXT NOT NULL, query TEXT NOT NULL,
  rank INT NOT NULL, url TEXT NOT NULL, title TEXT, snippet TEXT, retrieved_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
ALTER TABLE longway_evidence_proposals
  ADD COLUMN question_id UUID REFERENCES longway_questions(id),
  ADD COLUMN run_id UUID REFERENCES longway_scout_runs(id),
  ADD COLUMN search_result_id UUID REFERENCES longway_search_results(id),
  ADD COLUMN contradicts UUID REFERENCES longway_evidence_proposals(id),
  ADD COLUMN applies_from DATE, ADD COLUMN applies_to DATE, ADD COLUMN direction TEXT, ADD COLUMN passport TEXT, ADD COLUMN vehicle TEXT,
  ADD COLUMN leg_from TEXT, ADD COLUMN leg_to TEXT,
  ADD COLUMN load_bearing BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN counter_searched_at TIMESTAMPTZ,
  ADD COLUMN publisher_count INT;
```

`load_bearing` is true when the scope is a schedule, an operating status, an entry rule or a price (the five checks of §15 apply). `counter_searched_at` is stamped when the run has searched for the contrary of that claim, whether or not it found anything. A load-bearing proposal with no `counter_searched_at` cannot be confirmed; the route refuses with 409 and the reason.

### 11.2 Environment

```
LONGWAY_SEARCH_PROVIDER=none | brave | exa      # none: the search tool is absent and runs read known sources only
LONGWAY_SEARCH_KEY=<key>                         # Amo's account; never logged
LONGWAY_FIRECRAWL_KEY=<key>                      # optional: renders pages defuddle sees thin (under 1,000 characters)
LONGWAY_SCOUT_ENABLED=0                          # the nightly job; off until Amo
LONGWAY_SCOUT_MODEL=claude-opus-5-5
LONGWAY_SCOUT_BUDGET_PAGES=40  LONGWAY_SCOUT_BUDGET_PROPOSALS=20  LONGWAY_SCOUT_BUDGET_OUTPUT_TOKENS=60000  LONGWAY_SCOUT_BUDGET_SECONDS=1200
```

### 11.3 The run (`organs/longway/scout.py`)

A plain asyncio task in the backend process (the Workshop sandbox has no network; the run executes no code and holds no credential beyond the search key). `run(pool, room_id, journey, question_ids, trigger, started_by)`:

1. Insert the `longway_scout_runs` row (`running`); one running run per journey (409 otherwise).
2. Build a registry for the tool loop (`llm/tool_loop.py` over `llm/tools.py` `Tool` objects, with `llm/providers.py`, model `LONGWAY_SCOUT_MODEL`, effort high):
   - `known_sources()`: the journey's evidence URLs with their S-numbers and claims, every `vehicles[].timetable`, and http(s) links in the room's human messages of the last 30 days, each with its origin.
   - `search(query, count<=8)`: present only when a provider is configured. Brave: `GET https://api.search.brave.com/res/v1/web/search?q=…&count=…` with header `X-Subscription-Token`; Exa: `POST https://api.exa.ai/search` with header `x-api-key` and `{"query", "numResults", "type": "auto"}`. Verify both against the provider's documentation before trusting these shapes; keep each adapter a single function with a test over a canned response. Every result is inserted into `longway_search_results` before it is returned; the tool returns `{id, url, title, snippet}` rows. The query is the Scout's own phrasing of a place question; the run never searches a person's name.
   - `read_page(url)`: `llm/defuddle_client.extract_article` (defuddle on `:8010`, Jina fallback), capped at 40 pages per run; returns `{site, published, text}` where text is capped at 12,000 characters with the cut noted; logs the read. (Pelni's booking page yields 721 characters this way; a browser fetcher is not part of this slice.)
   - `propose(candidate, url, claim, scope, question_id?, search_result_id?, contradicts?, applies_from?, applies_to?, direction?, passport?, vehicle?, leg_from?, leg_to?, load_bearing)`: `proposals.propose` extended with those columns and `run_id`; the `supported_passage` gate stays (the claim's words contiguous in the extracted text, 3 to 35 words); a second gate: the passage must be a whole sentence of the main text, not a navigation fragment (a sentence boundary on each side, or the whole paragraph when the extractor gives none). `leg_from`/`leg_to` must name neighbouring stops of the candidate's `route` or be null.
   - `read_register(...)` as today.
3. System prompt: the Scout identity (`identity.py`) plus the research instruction: answer the given questions (ids and text), read known sources first, then search if available; file every claim as a proposal with its exact passage; mark load-bearing claims; use the charter's source order (§14: operators and official pages for transport and entry, independent reporting and local accounts for context, Wikipedia last); never state a fact in prose that is not a proposal; stop when the questions are answered or the budget is spent.
4. Counter-search phase: for every proposal filed in this run with `load_bearing` and no `contradicts`, one more loop turn asking the Scout to look for the contrary (suspended, cancelled, closed, a later year, a different operator) using `search` when present and `known_sources` otherwise, filing anything found with `contradicts = <id>`; stamp `counter_searched_at` on each such proposal whether or not something was found; also stamp `publisher_count` from the distinct publishers in this run's proposals with the same claim words (independence).
5. Finish the row (`done` or `failed` with `error`), post one participant message in the room (`metadata.longway_scout_run = {run_id, journey, pages_read, proposals, counter_proposals}`, content: "Scout run on <journey>: read N pages, filed M proposals and K contrary findings for the Field. Questions: …") through the same posting path the dispatch uses, broadcast; questions with a proposal get `answered_by_proposal`.

Budgets from the environment; the run stops cleanly at any of them and says which in the receipt.

### 11.4 Routes (all under `/rooms/{room_id}/longway/`, same auth as section 5)

- `GET questions`: open questions for the room's journey (or every journey in the house room), newest first, each with `answered_by_proposal` and the proposal's review state; `POST questions {journey?, text, source?: 'human'|'reaction'|'message', source_message_id?}` (any member; journey defaults to the room's); `POST questions/{id}/close` (any member); `POST questions/seed` (managers): seeds the journey's dossier questions (`atlas_data` `questions`) as `source='dossier'`, deduplicated by text.
- `POST scout {question_ids?: [..]}` (managers): starts a manual run for the room's journey with those questions or, when omitted, the five oldest open ones; 409 while one runs; returns `{run_id}`. `GET scout/runs` (last 20 receipts), `GET scout/runs/{id}` (receipt with log), `POST scout/runs/{id}/kill` (managers).
- `GET proposals` gains every new column plus `question_text`, `requires_counter` (load_bearing and not counter-searched) and `run_id`.
- The Field's review route (`api/field.py`) refuses `confirm` on a proposal mark whose proposal has `requires_counter` with 409 "load-bearing claim has no contrary search yet"; the shell shows that reason.
- `GET chart` gains `proposals`: `{ <slug>: [ {id, claim, support, review, url, publisher, leg_from, leg_to, load_bearing, requires_counter} ] }` for proposals not written and not contested/corrected; a segment whose stops match a proposal's `leg_from`/`leg_to` (either direction) gets `proposed: true` so the chart draws it dotted with a "proposed" label (section 11.6).
- Dispatch: `dispatch.history()` adds this week's confirmed and contested proposals (from `field_marks`) and the run receipts; the prose names them by proposal id and by the S-number once written. The one question keeps its place as the last paragraph before the reaction line, so the card can read it.

### 11.5 Jobs

- `scout_nightly` (02:00 America/Chicago, `LONGWAY_SCOUT_ENABLED`, default off): for each room bound to a journey with at least one open question, one run with up to five questions, serially; the house room is skipped. Receipts are the only output; the dispatch summarises them.
- `evidence_writer` writes a confirmed proposal's new fields into the evidence row: `scope` gains the direction, passport and vehicle when present; `applies_from`/`applies_to` are written as `applies` ("2027-08-24 to 2027-09-30"); `checked_by` is the confirmer's display name (`tools/longway.py check` accepts it as optional text).

### 11.6 Frontend

- **Field**: a "What the Scout is working on" section (open questions with their source; an "Ask the Scout to find out" form; "Scout this" for managers with the latest receipt and a running indicator) above "Proposed evidence". Each proposal renders passage first (blockquote), then the claim, the scope, the structured fields that are set, the question it answers, the publisher and the link; Confirm is disabled until the link has been opened from this device (component state), and disabled with its reason when `requires_counter`; Contest asks for one line; Correct asks for the better claim; a row with `written_sid` shows it. A proposal older than 14 days with no review is paled.
- **Chart**: segments with `proposed: true` draw dotted with a "proposed" tag in the strip and the LegCard; the LegCard lists the pending proposals for that leg (passage, claim, publisher) with Confirm/Contest through the same Field path.
- **Dispatch card**: the ❓ reaction also `POST`s a question (`source: 'reaction'`, text = the dispatch's last paragraph before the reaction line, `source_message_id` the dispatch message).
- **Record**: a participant message with `metadata.longway_scout_run` renders as a one-line card ("Scout read 12 pages, filed 5 proposals") linking to the Field.
- Types: `types.ts` carries `Question`, `ScoutRun`, `ProposalScope`, `ScoutedProposal`, `ChartProposal`, `ScoutRunMetadata`, `Segment.proposed`, `ChartProjection.proposals`.

### 11.7 Ownership for this slice

| Build | Owns | Does not touch |
|---|---|---|
| backend scout | `dialectic/organs/longway/scout.py`, `search.py`, `questions.py`, `migrations/030_longway_scout.sql`, the `030` block in `schema.sql`, `tests/test_longway_scout*.py`, `tests/test_longway_questions*.py`, `tests/test_longway_search*.py`, and edits in `organs/longway/{api,proposals,jobs,dispatch,register,tools,__init__}.py`, `api/field.py` (the 409 on confirm), `.env.example` | `frontend/**` |
| frontend scout | `src/organs/longway/**` except `chart/mapRuntime.ts`, `chart/mapStyle.ts`, `chart/Chart.tsx` (edit `chart/Cards.tsx` for the LegCard), `src/hooks/useLongway*.ts`, `components/workspace/scenes/FieldScene.tsx`, `components/chat/MessageBubble.tsx`, `src/lib/releases.ts` | `dialectic/*.py` |

`types.ts` carries the new shapes before either build starts; it is read-only for both.

### 11.8 Amendments after the first live runs (28 Oct, evening)

Manual runs in a room bound to `banda-islands` with the question "Is there a boat from Ambon to Banda in October?", no search provider (known sources only), `claude-opus-5-5` at high effort. Each run changed the contract above in one place:

1. **A page costs once per run.** Run 1 (the slice as integrated) read 40 pages, the whole budget, and filed 14 proposals with 1 contrary finding in 4 min 20 s; the budget ran out inside the counter-search phase because `propose` and every counter phase re-fetched pages the research phase had read and each fetch counted. Load-bearing proposals left without a contrary search could never be confirmed, and nothing would ever perform it. Now `Research.fetch` keeps a per-run page cache and `pages_read` counts distinct pages; the counter loop takes this run's proposals first, then any load-bearing proposal in the room for the journey that still has no `counter_searched_at` (a starved run's, or one a member filed by hand).
2. **The run owns its journey.** Run 2 read 7 pages and filed nothing in 105 s (178k input, 9.2k output tokens): the model named `candidate` "Banda Islands", the tool refused all six proposals and the Scout gave up. `propose` no longer takes `candidate` from the model.
3. **A timetable line is a passage.** Run 3 read 6 pages and filed nothing in 90 s (158k / 7.8k tokens): four proposals came back unfiled because the Bluemotion schedule is a nested list and the whole-sentence gate skipped list paragraphs entirely. A list item or a table row is now its own unit (it carries its own negation); headings and link-only menus stay excluded.
4. **Refusals are visible.** Every proposal the gate does not file, or that raises, is logged in the run as `propose_refused` with its reason, and the receipt message says "filed M proposals (N refused by the passage gate)".
5. **A confirmed answer closes its question.** The Field's confirm closes the question the proposal answers (`closed_at`, `closed_by`) in the same transaction; the nightly job would otherwise research it again every night. The questions list says "answered below, awaiting confirmation" while a proposal cites the question.
6. **The passage is shown once.** The proposal card marks the claim inside its passage (the claim is by construction a run of the passage's words) and repeats it as a heading only when a plain substring match fails.
7. **Run 4 held the done criterion, and showed the next three tolerances.** After 1 to 6: 16 distinct pages, 20 proposals (the budget; 17 load-bearing, 4 contradictions), 10 contrary searches completed and 7 load-bearing proposals left for the next run, 15 attempts refused, 10 min 50 s, 1.51 million input tokens and 58 thousand output tokens; the chart drew Ambon to Banda Neira proposed, the Field confirmed one proposal and refused a load-bearing one without its contrary search. Of the 15 refusals, four were dates given as a month or a year, three were S-numbers or claim text where an id belongs, and the rest paraphrases; and six of the twenty rows were the same car-ferry line refiled by the counter phases. So `propose` now reads a year or a month as a period (first day for `applies_from`, last day for `applies_to`), names the field when an id is not a UUID, and refuses a claim already filed from the same page in the room with the existing id in its answer, so the Scout can file a contradiction instead. Unit-tested, not yet exercised in a live run. The input volume is the tool loop's growing context: every page read stays in the conversation for the rest of the run; item 8 trims it.
8. **Search, rendering and a smaller context (28 Oct, later).** Amo supplied a Brave Search key and a Firecrawl key. The Brave adapter was checked against Brave's documentation (GET `/res/v1/web/search`, `X-Subscription-Token`, `web.results[].url/title/description`) and answered five schedule pages for "Ambon Banda Neira ferry schedule". `read_page` now renders a page through Firecrawl (`POST https://api.firecrawl.dev/v2/scrape`, `Authorization: Bearer`, markdown, main content, image markup stripped) when defuddle returns under 1,000 characters and `LONGWAY_FIRECRAWL_KEY` is set, keeping the longer text; Pelni's booking page went from 721 to about 30,000 characters that way, cut at the 12,000-character cap. And before every model call the run shrinks old tool results in place (`Research.trim`, `CONTEXT_KEEP`: the last four `read_page` bodies, the last `known_sources` and `read_register`), replacing each with a one-line stub that says to call the tool again; a result the model has not yet seen is never shrunk, and a page already read costs no budget to read again.
9. **Run 5, the first with search, and what it forced.** 10 pages, 2 searches, 3 proposals (all load-bearing, 2 contradictions) from pages the ledger did not know, 2 min 46 s, 539 thousand input tokens and 13 thousand output tokens, with the trim in place. Nine reads failed because the pages answered the extractor with 403 or 429, each still charged to the pages budget; six proposals were refused as paraphrases of a schedule sheet, the most useful claims of the run; one search failed at Brave's one-query-per-second limit. So `read_page` renders through Firecrawl when the extractor fails, not only when it returns thin text, and refunds a page the Scout never got; a refusal carries the page's own line nearest to the claim (`closest_unit`); Brave calls are serialized a second apart.
10. **Run 6, with everything on, and the nightly switch.** 29 pages (21 through defuddle, 7 rendered by Firecrawl), 15 searches phrased in Indonesian ("jadwal kapal Pelni Ambon Banda Neira Oktober", "KM Labobar docking Oktober 2026 rute Ambon Banda pengganti"), 14 proposals from nine publishers, all load-bearing, 10 of them contradictions (KM Labobar in dock with no replacement, a Pangrango sailing held by weather), 4 contrary searches, 9 min 4 s, 1.90 million input tokens and 37 thousand output tokens; 10 refusals, half of them now carrying the closest line. Two gaps it exposed: a contradiction is itself load-bearing and was reported as needing a contrary search of its own, so ten rows could not be confirmed; `requires_counter`, the Field's 409 and the writer now exempt a proposal with `contradicts`. And a restart during a run would have left its row 'running' and the journey blocked for good; `scout.recover`, started by the organ's `startup`, closes such rows with a receipt. Amo then switched the nightly job on (`LONGWAY_SCOUT_ENABLED=1`, 02:00 America/Chicago): a bound room with no open question is seeded with its dossier's decisive questions first, so the job has work, and a failed run is logged and the job moves to the next room. At run 6's rate, expect about two million input tokens per bound room per night. The scheduler fires a daily job at startup when it has not run that day, so the restart that switched the job on started a run for the Sepik room at 10:21 in the morning; `scout_nightly` now runs one batch per Chicago day (it checks the last nightly run's date), so a redeploy is never a Scout run.
11. **The desk drives the spend.** A nightly run on a question whose proposal nobody has reviewed yet would spend two million tokens to pile a second answer on the first, every night, until someone looked. `questions.researchable` gives the nightly job only the open questions with no unreviewed, unwritten proposal citing them (a contest or correction frees a question again); a room whose every open question has an answer waiting is skipped with "answers waiting in the Field". "Scout this" is unchanged: a manager may research anything. Two more gate changes from run 6: a table row or list item is one unit wherever it sits in a paragraph and is never split at a full stop (run 6 quoted a Pelni timetable row and the gate refused the whole captioned table; a markdown rule line is skipped), and search results leave the context after the second newer search. A waiting desk stops research, not the contrary searches it needs: a room with no researchable question but a load-bearing proposal still without its contrary search gets a counter-only run (`execute(counter_only=True)` skips the research turn), because the Field cannot confirm such a proposal and nothing else performs the search. The first nightly run (Sepik, 28 Oct 10:21) left five of them.

## 12. Asking for a seat (28 Oct, evening)

Amo: "open them up. let people request. send it to my email." Signups stay closed (`SIGNUPS_ENABLED=0`; AGENTS.md makes
membership the planner's act). What opened is a door to ask.

- **The door.** `POST /organ/longway/invite-requests` `{email, name, note}` (public; `/organ` was already proxied by nginx).
  The sign-in screen's second tab reads "Ask for a seat" on the longway build and posts there; the trading build is
  unchanged. Ten asks a day per visitor address (`CF-Connecting-IP`, then `X-Real-IP`, then the peer) and three per
  email address through `api.rate_limit._reject_if_limited`; the answer is `{ok: true}` whether or not the address is known.
- **The record.** Migration `031_longway_invites.sql`: `longway_invite_requests` (one open request per address through a
  partial unique index; asking again refreshes the name, note and time and re-arms the email). `organs/longway/invites.py`
  owns ask, announce, listing, invite and decline.
- **The announcements.** `announce` pushes every house manager through the existing web push channel and emails the planner
  through `organs/longway/mail.py` (stdlib `smtplib`, STARTTLS; `LONGWAY_SMTP_USER` + `LONGWAY_SMTP_PASSWORD`, for Gmail an
  app password; `LONGWAY_INVITE_NOTIFY_TO` defaults to the sending address). Mail off means `MailDisabled`, the row keeps
  `notified_at` null, and the `invite_notifier` job (every 60 s) sends it once mail is on. An SMTP refusal is logged and
  retried the same way.
- **The decision.** House managers see "Asking for a seat" in the house: `GET /rooms/{id}/longway/invite-requests`
  (`mail_configured` and the requests, open first), `POST .../{id}/invite` and `POST .../{id}/decline`. Invite issues the
  same rows as `deploy/longway_seed.py invite` (both now call `organs/longway/membership.py`): account, house membership,
  a 7-day `password_reset` code; the code always returns to the manager, and the requester is emailed "Your seat at The
  Long Way" with the code when mail is on (`invited_email_at`). The invitee uses "I have a code" under Sign In.
- **Tests.** `tests/test_longway_invites.py`: the ask and its refresh, both limits, the manager's invite and decline, the
  mail with a recorder and with a refusing server, and the notifier.


## 13. Ride rooms (29 Oct 2026)

The following interface is the shared repository/backend/frontend contract.

### Ride rooms: the contract between the repository, the house backend and the house frontend

Source of the bet: /root/theLongWay/docs/moonshot-ride.md. Owner: Amo. Written 2026-10-29 by the lead.

#### Repository (/root/theLongWay, read by the house through dialectic/organs/longway/register.py -> tools/longway.py)

Already built and committed (theLongWay 90ad30c):

- `ride_data(root, slug)` -> `{"slug", "title", "route": [[lat, lon, label]], "rides": [{"id", "vehicle": {"name", "kind", "operator"?, "amtrak"?, "mmsi"?, "imo"?}, "date", "board", "alight", "riders": [names], "leg": str|null, "leg_ready": bool, "logbook": bool}]}`. Raises KeyError when the slug is not a trip with `"shared": true`. Allowlisted: never plan prose, evidence or bookings.
- `leg_data(root, leg)` -> `{"id", "leg": leg.json|null, "sights": sights.json, "coverage": coverage.json without "strips" | null, "guide": guide.json|null, "check": check.json|null}`. ValueError for a bad name, KeyError when legs/<leg>/sights.json is missing.
- `chart_data` journeys of kind "trip" now carry `"rides": <count>`. Rides themselves never enter the chart (charter §18: live movement is narrow-access).
- Real data: trip `coast-starlight-2026` is shared, ride `14-22` (vehicle "Coast Starlight 14", amtrak "14", date 2026-10-22, board MTZ, alight SEA, riders ["Amo"], leg "amtrak-313-14"). Leg folder `legs/amtrak-313-14/` has leg.json, sights.json, coverage.json, guide.json (no check.json yet). Logbook `trips/coast-starlight-2026/rides/14-22.json`.
- Run id convention: Amtrak numbers a run `<train>-<origin day of month>`; ride `date` is the run's origin date (14-22 left Los Angeles on 22 Oct; Amo boarded at Martinez that night and reached Seattle on the 23rd).

##### Leg files (formats are exactly today's live-chart files; see /root/theLongWay/tools/live/index.html for how they are drawn)

- `sights.json`: `built`, `times`, `classes` [{label, color}] (index = class number c), `eye_h`, `tree_h`, `left`/`right` [{c, pts: [[lat, lon], ...]}] (side polylines per class, side relative to the direction of travel), `km` rows `[km, left_class, right_class, lat, lon, left_name, right_name]` (one per km from the boarding end; this is also the leg's geometry), `sights` [{kind: view|peak, name, side, km0, km1, length_km, minutes, t0, t1, from_code, to_code, f0, f1, start, end, lat, lon, best, light, note, cloud?...}] (t0/t1 are minutes after 00:00 local on the first day of the timetable the file was built for; start/end are those local clock strings; the live card re-times them from live stop estimates), `stations` [{code, name, km, time, lat, lon}], `peaks` [{name, lat, lon, ele, src}].
- `coverage.json`: `classes` [{label, min, color}], `segments` [{c, pts}], `measured` [[...pts]], `gaps` [{km0, km1, length_km, minutes, start, end, near, from_code, none_pct, t0, t1, mid, tests}], `stations`, `sites`.
- `guide.json`: {sight name: {title, what, history, img, links: [...], ...}}.
- `leg.json`: {id, kind, operator, train?, route?, shape?, from, to, km, eye_h, built, basis}.
- `check.json` (new, written by tools/sights.py --score): {"source": {"title", "url", "publisher", "checked_at", "direction_note"}, "landmarks": [{"name", "side": "left"|"right", "km": float, "kind": "peak"|"water"|"canyon"|"town"|"structure"|"other", "note"?}], "score": {"agree", "total", "misses": [{"name", "side", "km", "why"}], "scored_at", "tolerance_km"}}.

##### Logbook `trips/<slug>/rides/<ride>.json` (see the 14-22 file)

`{"ride", "trip", "vehicle", "train"?, "mmsi"?, "date", "board", "alight", "leg", "written_at": "YYYY-MM-DD", "written_by": "house"|"backfill", "sources": [{"publisher", "url", "checked_at", "note"?}], "stops": [{"code", "km": float|null, "sched_arr", "arr", "late_arr", "sched_dep", "dep", "late_dep"}], "track": [[iso_utc, lat, lon, km|null]], "track_basis": str, "notes": [{"at", "km": float|null, "member", "text"}]}`. Times are ISO 8601 UTC with Z, or null; late is whole minutes, positive = late; arr/dep are actual times only.

#### House API (dialectic/organs/longway/api.py, prefix /rooms/{room_id}/longway, membership-fenced by `authorized`)

A ride room is any room whose `linked_journey` is a shared trip with rides (the existing `/bind` binds it).

`GET /ride[?ride=<id>]` -> 404 when the room's journey is not a shared trip with rides. Picks `?ride` or else the current ride: riding, then the soonest waiting, then the latest arrived.

```
{
  "trip": {"slug", "title"},
  "rides": [{"id", "date", "state"}],
  "ride": {"id", "date", "board", "alight", "riders", "leg", "leg_ready", "logbook", "vehicle": {...}, "state": "waiting"|"riding"|"arrived"},
  "run": "14-22" | null,
  "fix": {"lat", "lon", "at", "age_min", "speed_mph": number|null, "heading": str|null, "source": "amtrak"|"ais"} | null,
  "fix_unavailable_reason": str | null,
  "km": number | null,
  "stops": [{"code", "name", "km": number|null, "sched_arr", "sched_dep", "arr", "dep", "estimated": bool, "status": str|null, "late_min": int|null}],
  "history": {"days": int, "at": {"CODE": {"median": int, "worst": int, "n": int}}} | null,
  "track": [[iso, lat, lon, km|null]],
  "fetched_at": iso
}
```

Live rides take stops from Amtraker (`https://api-v3.amtraker.com/v3/trains/<num>`, run `trainID == "<num>-<day>"`; station fields schArr, schDep, arr, dep, status; `lastValTS` is the fix time). Arrived rides take stops from the logbook (estimated false, status null). Times in the API are ISO 8601 UTC with Z.

`GET /ride/leg?leg=<id>` -> `leg_data` JSON for a leg named by one of this room's rides; `Cache-Control: private, max-age=86400`; ETag from leg.built or sights.built.

`GET /riding` -> `{"rides": [{"room_id", "room_name", "trip", "ride": {"id", "state", "vehicle": {"name"}}, "fix": {...}|null, "next_stop": {"code", "name", "est"}|null, "late_min": int|null}]}`: rides in state waiting or riding, only in rooms the caller is a member of. Called from the house room.

Scout tools (dialectic/organs/longway/tools.py): `ride_status(ride?)` and `out_the_window(side="both", km=None)`; with km omitted, the ride's current km.

#### Frontend (dialectic/frontend/app/src/organs/longway/)

`LongwayBench` renders `RideBench` when the bound journey is a trip with `rides > 0`, otherwise the globe as today. `LongwayHouse` shows "Riding now" from `GET /riding`.

### Backend implementation and operation

`observe.py` reads Amtraker v3 per train number, cached for 60 seconds through
`fixes.fetch_feed`, with a plain `Mozilla/5.0` User-Agent. `lastValTS`, normalized
to UTC, is the broadcast timestamp. The house chart draws the most recently
heard run's vehicle without exposing run IDs, ride records or riders. AIS keeps
`LONGWAY_FIXES_URL` / `ships.json`; speed is converted from knots to mph for rides.
The old GeoJSON train endpoint and `LONGWAY_TRAINS_URL` are superseded.

`rides.py` is the common room projection for HTTP and Scout. Membership and room
token checks precede reads; `/ride` and `/ride/leg` conceal non-members with 404.
`/riding` enumerates only the caller's memberships. Leg reads additionally check
that the requested leg belongs to a ride in the bound shared trip. The chart
contains only a ride count, never the ride projection. Arrival logbooks win over
live observations; the existing 14-22 backfill supplies its 18 stops and no track.

Migration `032_longway_rides.sql` adds trip/ride keyed state and broadcast keyed
fixes. It also retains the last station snapshot and observation time: actual
stop times must remain recoverable after Amtraker removes a run. The operator
must apply this migration before enabling the new backend; this change does not
apply it to the live database.

`jobs.ride_watch` runs every 60 seconds. It observes origin dates from yesterday
through three days after today (Chicago), and continues for persisted riding
states. Arrived rows remain eligible for delayed writes after that window.
A train absent from the feed stays waiting. Boarding `Departed` starts the ride;
an actual alighting arrival in the past ends it. Ships use the origin date: waiting
before it, riding that day and the next, arrived afterward. GPS is projected onto
the nearest segment of the leg's km geometry; unknown geometry stays null.

Transition pushes go through the existing Web Push service to bound-room members;
signal warnings go only to members whose display names match riders without case.
Warnings require a fresh fix, positive speed, and a model gap starting within ten
minutes. Database row locks serialize watchers; pushed flags and gap keys suppress
repeat sends. A stable notification tag identifies each event. Web Push is an
external effect: a process failure after delivery but before transaction commit
can repeat a delivery attempt. Device receipt is not proven by a successful job.

TransitDocs history reads the preceding 45 Chicago origin days, five at a time,
using actual arrival variances only. It reports median, worst and sample count per
stop, cached per train per Chicago day. Cold history warms asynchronously; the
first response can have `history: null` while positions remain available.

Six hours after arrival, `ride_watch.write_book` writes through
`Register.write_logbook` only with `LONGWAY_COMMIT_ENABLED=1`. It uses actual-only
persisted stations, at most one recorded position per km bin, and human rider
messages in bound rooms from 30 minutes before departure through arrival.
Notes interpolate km only between observed track points; they never extrapolate.
Followers, model messages, deleted messages and messages outside the interval do
not enter the repository. The first rider with a house account supplies the git
author. Existing books survive retries; dirty targets are refused. Commits use
`--only`, carry `Longway-Ride: <slug>/<ride>`, and never push.

Scout's `ride_status(ride?)` uses the same room projection. `out_the_window(side,
km)` returns named sights within 2 km, class, distance, guide title/text/history/
links, `provenance: model`, and the leg check when present. Compound names resolve
to their individual guide entries. Without explicit km it requires a riding state
and an observed position.

`tests/test_longway_rides.py` uses a synthetic saved Amtraker-shaped sample, the
real Coast Starlight leg/backfill copied into a temporary repository, and real
Postgres for HTTP/state/write paths. No test writes `/root/theLongWay`.

A read-only Amtraker probe through the new observation code on 29 Oct (Chicago)
returned two train-14 runs and a drawable `14-29` fix broadcast at
`2026-10-30T04:15:39Z`. Raw response and receipt are saved in
`tests/fixtures/longway_amtraker_live_20261029*.json`. This verifies the feed
parser, not deployment, the live house database, or device push receipt.
