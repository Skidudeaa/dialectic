# Handoff, 28 Oct 2026: the `longway` branch, a second organ on the room engine

For a Dialectic-side session with no context. The Long Way (Amo's travel group) now runs on this codebase as a second deployment, selected by `DIALECTIC_ORGAN=longway`. The product-side record is `/root/theLongWay/docs/handoffs/2026-10-28-the-house.md`; the contract is `docs/LONGWAY_ORGAN.md`; the proposal is `/root/theLongWay/docs/moonshot-house.md`.

## What the branch is

- 21 commits on master `25ee122`, built in three OMC Codex (gpt-6-astra) jobs plus lead commits, in the worktree `/root/DwoodAmo/.worktrees/longway`. Pushed to `origin/longway`.
- **Not merged.** Master's working tree carries the owner's uncommitted palette pass (about 90 CSS and TSX files) and `dialectic.service` runs that tree, so nothing here was integrated into the checkout. Merge when the palette pass is committed; see the checklist below.
- The second instance: `longway.service` (`WorkingDirectory` the worktree's `dialectic/`, `EnvironmentFile /etc/longway/longway.env`, `:8004`), database `longway` (Dialectic's live schema copied with `pg_dump --schema-only` plus `029_longway.sql`), `/var/lib/longway/{media,workshop}`, nginx site `thelongway.world` (certbot, proxied through Cloudflare because ufw admits 80/443 only from Cloudflare ranges), frontend releases under `/var/www/longway-releases` flipped by `/var/www/longway-current`. Deploy: move the branch, `systemctl restart longway`, `bash dialectic/deploy/longway_release.sh`.

## What touches shared code (the merge checklist)

| File | Change | Effect on trading |
|---|---|---|
| `organ.py`, `organs/trading.py`, `organs/__init__.py` | the seam: five hooks per organ, trading's moved unchanged | none by design; `tests/test_organ_trading.py` asserts the 27 tool names and the job names match |
| `api/main.py` | job registration and the relay routers go through `organ.register_jobs`/`routers()`; inline trading routes moved onto `organs.trading.room_router`; `GET /organ` | same routes and jobs register; verify the scheduler banner after a restart |
| `llm/tools.py` `build_registry` | `organ.tools()` first; world and cairn builders only for trading | none |
| `llm/prompts.py` | base identity from the organ; `_anchor_prefix` reads `longway_anchor` | none unless a message carries that key |
| `llm/mentions.py` | aliases read at first use from the organ's participant name | none for trading (dialectic, claude, llm) |
| `llm/providers.py` | **the 5.5 models**: ids starting `claude-opus-5-5`, `claude-sonnet-5-5`, `claude-haiku-5-5`, `claude-fable-` get `thinking: adaptive` plus `output_config.effort` (default medium) and a 2048-token floor, because the API refuses `thinking: disabled` for them; the stream fold keeps signed thinking blocks; `LLMRequest.effort` | none for mapped ids (they still roll to `claude-opus-5` / `claude-sonnet-5` with `disabled`); this is the one change master would want anyway |
| `transport/handlers.py` | `metadata.longway_anchor` validated by the longway register, refused outside that organ | none |
| `field_marks.py` | `longway_evidence_proposals` subject entity | none |
| `api/auth` screen (`AuthScreen.tsx`, `api.ts`) | "I have a code": `/auth/reset-password` from the sign-in tab | available on Dialectic too; harmless |
| `components/chat/MessageInput.tsx` | Meta tag tooltip reads `PRODUCT_NAME` | cosmetic |
| frontend shell files (`App.tsx`, `SceneSwitcher`, `SceneMasthead`, `BenchScene`, `LedgerScene`, `LibraryScene`, `FieldScene`, `workspaceRoute.ts`, `productIdentity.ts`, `vite.config.ts`, `sw.ts`, `releases.ts`, `RoomHeader.tsx`) | branch on `ORGAN` from `src/organ.ts` | identical with `VITE_ORGAN` unset; these overlap the owner's dirty files, so expect conflicts to resolve by hand |
| `migrations/029_longway.sql`, `schema.sql` | `rooms.linked_journey`, `longway_evidence_proposals`, `longway_confirmations` | additive; apply to `dialectic` only if the organ seam lands there (not needed for trading) |

Suites at the branch tip: backend organ and Long Way suites 269 passed, provider suite 31, frontend 807 of 807; the trading build (`npm run build`) passes with `VITE_ORGAN` unset.

## Operating the Long Way instance

- Invitations: `longway-invite EMAIL "Name" [--manager]` prints a one-time reset code; signups stay closed. `longway-members` lists the house.
- Probe: `python3 dialectic/deploy/longway_observe.py` (16 checks against the real database and repo; also the `omc build observe` recipe).
- Jobs: `sunday_dispatch` (08:00 America/Chicago, Sundays), `evidence_writer` (60 s; writes to the Long Way repo only when `LONGWAY_COMMIT_ENABLED=1`), plus the shared heartbeat and workshop watch. Manual door: `POST /rooms/{id}/longway/dispatch/now` (house managers).
- Models: rooms default to `claude-opus-5-5` in the `longway` database; `LONGWAY_DISPATCH_MODEL=claude-opus-5-5` at high effort with a 110 s wait.

## Known gaps

- Amtraker's feed carries no fix timestamp, so a train vehicle shows no fix until `api/trains` exposes one (only a private trip has a train).
- Push delivery to a real device and a real Sunday firing are unverified; the paths are unit-tested with real Postgres.
- The chart's imagery at zoom and the Workshop under adaptive thinking were not exercised.
