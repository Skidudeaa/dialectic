# Dialectic Evidence Freshness and Exact Push Landing — Live Handoff

This is the zero-context authority for the evidence-freshness and notification
deep-link release completed on 2026-08-17. The implementation is merged and
live. A fresh agent must verify current truth before doing anything and must
not restart services merely to “apply” this handoff.

## CURRENT STATE

- Repository: `/root/DwoodAmo`.
- Branch: `master`.
- Current HEAD at handoff: `7e91d21` (`docs: record evidence and push deployment`).
- Deployed code merge: `fda7beb` (`merge: evidence freshness and exact push landing`).
- Local `master` is 65 commits ahead of `origin/master`; nothing from this
  release was pushed upstream.
- Application code is live from the canonical checkout because the installed
  backend units use `/root/DwoodAmo`, not `/opt/dialectic/current`.
- `tradingdesk.service`: active at handoff, PID `2097721`, loopback port `8006`.
- `dialectic.service`: active at handoff, PID `2104998`, loopback port `8002`.
- `nginx`: active.
- Active PWA release:
  `/var/www/dialectic-releases/20260817T044128Z-fda7beb-evidence-push`.
- `/var/www/dialectic-current` points to that PWA release.
- Previous PWA rollback target:
  `/var/www/dialectic-releases/20260816-225728-mobile-composer`.
- Release manifest:
  `/var/backups/dialectic/20260817T044128Z-fda7beb-evidence-push.manifest`.
- Asset hashes:
  `/var/backups/dialectic/20260817T044128Z-fda7beb-evidence-push.assets.sha256`.
- No schema migration was required or applied.
- Two unrelated artifacts remain in the canonical checkout and are not release
  work: `IMG_0197.PNG` and `docs/superpowers/acceptance/__pycache__/`.
- The feature worktree and branch used for this release were removed after the
  merge. Other pre-existing worktrees remain and are not cleanup targets.

### Live evidence observed after deployment

- `iran-hormuz-graph` Polymarket: `status=no_data`, `freshness.state=live`,
  configured/missing market `us-iran-april-30`.
- `trump-tariffs-graph` Polymarket: `status=partial`,
  `freshness.state=live` on the first probe and `cached` on the Dialectic
  consumer probe, one real row:
  `us-recession-by-end-of-2026 = 0.075`; two authored markets missing.
- `iran-hormuz-graph` GDELT: `status=rate_limited`,
  `freshness.state=stale`, no prior observation immediately after restart.
- Dialectic validated that GDELT response and produced:
  `GDELT rate_limited for query '"Hormuz" AND ("blockade" OR "closure" OR "tanker") AND sourcelang:eng'; retry after 97s`.
- The LLM no longer receives “empty” for that failed poll.

### Authority documents

- Design:
  `docs/superpowers/specs/2026-08-16-market-evidence-freshness-hardening-design.md`
- Build plan:
  `docs/superpowers/plans/2026-08-16-market-evidence-freshness-hardening.md`
- Push design:
  `docs/superpowers/specs/2026-08-16-push-room-message-deep-link-design.md`
- Push build plan:
  `docs/superpowers/plans/2026-08-16-push-room-message-deep-links.md`
- Browser harness:
  `docs/superpowers/acceptance/2026-08-16-push-room-message-deep-link-acceptance.py`
- Durable implementation/deployment ledger: `JOURNAL.md`.

## DECISIONS WITH RATIONALE

### 1. Evidence states are explicit contracts, not inferred from array length

**Decision.** Book-scoped evidence responses carry a provider status plus a
nested freshness envelope containing `state`, `attempted_at`, `observed_at`,
`served_at`, `age_seconds`, and `ttl_seconds`. Supported distinctions include
live, cached, stale, confirmed no-data/no-matches, partial, unavailable,
rate-limited, and not-configured.

**Strongest rejected alternative:** continue returning `[]` or nullable rows
and let each consumer infer the cause.

**Why it lost:** the same observable represented no configuration, an upstream
failure, expired markets, a valid empty observation, and a stale cache. That
caused the LLM to tell humans both sources were “empty.”

### 2. A failed current poll stays failed even when prior evidence exists

**Decision.** Prior evidence may appear only under `last_observation`, with its
own timestamp. It never changes the current status from rate-limited or
unavailable to success.

**Strongest rejected alternative:** serve the last good payload as cached data
after a failed refresh.

**Why it lost:** it erases the current failure and lets stale evidence pose as
the latest observation.

### 3. Current book configuration is `market` first, legacy `slug` second

**Decision.** One shared resolver reads `feed["market"]` first and falls back to
legacy `feed["slug"]`.

**Strongest rejected alternative:** prefer `slug`, or maintain separate inline
resolvers for the browser and bridge paths.

**Why it lost:** every current book authors `market`, the engine consumes that
key, and duplicated resolvers caused the original always-empty endpoint.

### 4. LLM evidence uses strict book-scoped endpoints

**Decision.** Dialectic uses:

- `GET /api/bridge/polymarket/{thesis_id}`
- `GET /api/bridge/news/{thesis_id}`

These require `TD_SERVICE_TOKEN`, validate exact response shapes, and surface
provider failure as a failed tool result.

**Strongest rejected alternative:** make the legacy global browser endpoint
strict and use it for the LLM too.

**Why it lost:** the legacy UI contract intentionally preserves best-effort
null membership and its existing timeout; changing it would break a public
interface while still lacking book configuration/status context.

### 5. Provider load is bounded and coalesced

**Decision.** GDELT uses one bounded attempt, a two-worker executor,
query-scoped single-flight/cache, and a source-wide adaptive 429 cooldown.
Polymarket uses bounded workers, scoped cache/single-flight, and strict error
semantics for the bridge.

**Strongest rejected alternative:** retry inside each request or let every LLM
turn start independent provider calls.

**Why it lost:** GDELT rate-limits by source IP; concurrent retries kept the
throttle warm and made the outage self-sustaining.

### 6. A matched malformed Polymarket row is upstream failure

**Decision.** If a market matches but its probability cannot be parsed, the
strict path retries within budget and then raises `APIError`; it is not valid
`no_data`.

**Strongest rejected alternative:** convert any `None` probability to a
confirmed empty row.

**Why it lost:** malformed data and a genuine no-match are epistemically
different and drive different operator/LLM behavior.

### 7. Push attribution is server-owned

**Decision.** The handler joins `rooms`, uses the canonical room name, and
falls back to `Unnamed Room` for a valid null name. Human titles are
`Room · Sender`; LLM titles are `Room · ✦ Claude`.

**Strongest rejected alternative:** let clients synthesize a room label or use
a generic “new message” title.

**Why it lost:** the server is the canonical naming authority, and the user
explicitly requires the notification to identify its room.

### 8. Every message push carries the same complete destination

**Decision.** Web and Expo payloads carry identical `room_id`, `room_name`,
`thread_id`, and `message_id` data.

**Strongest rejected alternative:** use Expo `PushMessage(thread_id=...)` or
carry only a room ID.

**Why it lost:** the installed Expo SDK does not accept `thread_id`; room-only
payloads cannot land on the actual message. Grouping identity remains in data.

### 9. `useRoomNavigation` is the only destination writer

**Decision.** Cold URLs, warm service-worker messages, ordinary navigation,
and Back/Forward all install room, thread, and message through
`useRoomNavigation`.

**Strongest rejected alternative:** set the Zustand room/thread directly from
the service worker or `App.tsx`.

**Why it lost:** competing destination writers previously produced stale
room/thread state and URLs that disagreed with the rendered screen.

### 10. Exact message URLs explicitly name root threads

**Decision.** A message destination includes the thread even when it is the
root. A Home-root message includes room, root thread, and message; only a Home
root with no message canonicalizes to bare `/`.

**Strongest rejected alternative:** preserve root-thread omission for all
destinations.

**Why it lost:** reload and PopState dropped `message_id` when the requested
root thread was absent from the URL. Independent review caught the Home-only
variant after the ordinary-room fix.

### 11. Warm push delivery has an acknowledgement fallback

**Decision.** The service worker posts the destination through a
`MessageChannel`. The mounted navigator acknowledges receipt. If no listener
acknowledges within 200 ms, the service worker navigates the existing client to
the encoded URL so signed-out/loading clients retain the destination.

**Strongest rejected alternative:** post once to any matched client and return.

**Why it lost:** a loading or signed-out client has no mounted navigation
listener, so the tap disappeared.

### 12. Deleted targets fall back to current history

**Decision.** The context endpoint excludes soft-deleted targets and returns
404. The frontend also checks that a successful context response actually
contains the target; otherwise it fetches latest history and does not flash a
nonexistent message.

**Strongest rejected alternative:** install the old context window without a
target.

**Why it lost:** it leaves the reader in stale history with no explanation and
no highlighted destination.

### 13. Late media/reaction reads are destination-fenced

**Decision.** Attachment and reaction refreshes capture the expected thread
and verify it remains active before committing results.

**Strongest rejected alternative:** rely only on cancelling the history request.

**Why it lost:** those secondary requests could finish later and overwrite the
next room/thread after the history cancellation fence had already run.

### 14. Reuse the existing message landing behavior

**Decision.** Context rows install once, then the existing `MessageList`
centered scroll and `msg-flash` identify the target.

**Strongest rejected alternative:** create a new notification-only transcript
or scroll implementation.

**Why it lost:** the existing accessible message DOM and jump behavior already
worked; duplication would create two landing semantics.

### 15. Deployment follows actual installed topology

**Decision.** Both Python services were restarted from the canonical checkout;
the PWA alone was staged as an immutable release and atomically flipped.
TradingDesk was restarted first, Dialectic second, PWA last.

**Strongest rejected alternative:** silently replace the installed units with
the immutable-backend unit described in `dialectic/deploy/README.md` during
this feature deployment.

**Why it lost:** changing service topology is a separate operational change;
the installed units explicitly use `/root/DwoodAmo` and were healthy.

## DO-NOT-RELITIGATE LIST

- Do not collapse current failure, confirmed empty, no configuration, partial
  coverage, and stale observation into `[]`, `None`, or one “empty” message.
  This is the defect the release exists to remove.
- Do not promote `last_observation` to current evidence after a failed poll.
  Its separate timestamp/status is a binding epistemic fence.
- Do not reverse the `market` then `slug` precedence. Current books and engine
  behavior settled it; real-corpus mutation tests guard it.
- Do not restore `except Exception: return []` around provider calls. It hid
  upstream failure and invalid response shapes.
- Do not make the legacy `/api/market/polymarket` browser route the LLM
  authority. It remains a best-effort compatibility surface.
- Do not add unbounded provider concurrency or eager retries. The source-wide
  GDELT cooldown and bounded executors are required by observed 429 behavior.
- Do not report the current GDELT result as confirmed empty. At handoff it is
  rate-limited/stale with no current observation.
- Do not represent a matched malformed market as valid no-data. Independent
  review classified this Important and the regression is now load-bearing.
- Do not add a second room/thread/message writer. `useRoomNavigation` owns all
  navigation, including service-worker taps and history traversal.
- Do not omit room or root thread from a Home-root message URL. The exact
  regression passed review only after all three axes were serialized.
- Do not remove the service-worker acknowledgement/fallback path. It protects
  loading and signed-out clients from losing warm taps.
- Do not re-add Expo `thread_id` as a constructor argument. The installed SDK
  rejects it; destination identity belongs in `data`.
- Do not treat a soft-deleted message as a valid context target.
- Do not allow a completed old attachment/reaction fetch to commit into a new
  active thread.
- Do not deploy the acceptance build made with
  `DIALECTIC_BACKEND_URL=http://localhost:8013`. Production must be rebuilt
  without that override before a PWA flip.
- Do not source the entire production `trading/.env` into the full TradingDesk
  unit suite. It activates live FRED behavior and production passwords,
  producing seven unrelated failures. Use the neutral command in Verification.
- Do not use `/health` for TradingDesk verification; that path returns the SPA.
  TradingDesk health is `/api/health`. Dialectic health is `/health`.
- Do not reset, clean, stash, or delete `IMG_0197.PNG`, the acceptance
  `__pycache__`, or unrelated worktrees. They predate this handoff.
- Do not restart either backend just because a fresh agent resumed this plan.
  They are already live; restart only for an approved code/config activation.

## OPEN QUESTIONS — ASK BEFORE DECIDING

### 1. Which active Polymarket markets replace the three expired authored IDs?

Current expired/missing book data:

- `trading/books/iran-hormuz-graph.json`:
  `us-iran-april-30`
- `trading/books/trump-tariffs-graph.json`:
  `us-tariff-rate-china-march-31`
- `trading/books/trump-tariffs-graph.json`:
  `trump-visit-china-by-june-30`

Do not choose replacements by guess or approximate title matching. Present
active candidates, their resolution wording/deadlines, and the node each would
feed; ask the owner to approve exact slugs before editing book data.

### 2. May a controlled real-device notification be sent?

Automated warm/cold browser acceptance is complete, but no physical iPhone,
iPad, Android, or installed desktop PWA notification was sent/tapped during
this release. Ask which account/device and room may receive a controlled test.
Do not send a production notification or create a production message without
explicit approval.

### 3. Should the 65 local commits be pushed to `origin/master`?

The release is live from the droplet but not backed up to the remote. Pushing
is an external write. Ask explicitly before `git push`; do not infer approval
from deployment approval.

### 4. Should repeated GDELT 429s trigger a query/cadence change?

The current behavior is correct: explicit rate-limited/stale with retry timing.
After the cooldown, a read-only re-probe is safe. If rate limiting persists,
show timestamps/cooldown history and ask before changing queries, TTLs,
worker counts, or scheduler cadence.

### 5. Is frontend code splitting worth a separate task?

The production build is green but Vite warns that the main JavaScript chunk is
about 508 kB minified. It is not a release failure. Ask before restructuring
chunks; do not mix this optimization into evidence or notification repairs.

## REPO / ENVIRONMENT ORIENTATION

### Evidence producer and contracts

- `trading/tools/data_fetch/gdelt.py` — bounded GDELT fetch and error types.
- `trading/tools/data_fetch/polymarket.py` — Polymarket matching, probability
  parsing, retry/error semantics.
- `trading/web/adapters/market.py` — shared `market`/legacy `slug` resolver and
  browser-compatible market adapter.
- `trading/web/routes/bridge.py` — strict book-scoped news and Polymarket
  endpoints, freshness payloads, caches, single-flight, cooldown, and prior
  observation handling.
- `trading/web/routes/market.py` — legacy browser-facing market endpoint.
- `trading/web/test_bridge_endpoints.py` — main producer contract and cache/
  concurrency regression suite.
- `trading/web/test_market_quotes.py` and
  `trading/web/test_market_polymarket_id.py` — legacy compatibility and the
  original key-drift regression.
- `trading/tools/data_fetch/test_gdelt.py` and
  `trading/tools/data_fetch/test_polymarket.py` — provider parsing/transport
  behavior, including malformed matched-market failure.

### Dialectic evidence consumer

- `dialectic/llm/tradingdesk_client.py` — bounded service-token bridge client;
  news HTTP budget is 25 seconds.
- `dialectic/llm/tools.py` — response validators, degradation messages, and
  LLM tools; provider failure must raise `TradingDeskError`.
- `dialectic/llm/trading_relay.py` — Bench relay; only current live/cached rows
  are unwrapped for display.
- `dialectic/tests/test_tools_registry.py` — strict consumer contract,
  shrink-field protection, query validation, and tool trace behavior.
- `dialectic/tests/test_trading_relay_endpoint.py` — Bench relay fences.

### Push producer

- `dialectic/transport/handlers.py` — recipient membership query and canonical
  room name passed into push service.
- `dialectic/api/notifications/service.py` — title/body/data construction and
  Web Push/Expo channel parity.
- `dialectic/api/notifications/webpush.py` — Web Push transport/subscription
  handling; not changed into a navigation authority.
- `dialectic/tests/test_collaboration_contracts.py` — canonical/unnamed room
  attribution.
- `dialectic/tests/test_webpush.py` — human/LLM titles and identical data axes.

### Push navigation and message landing

- `dialectic/frontend/app/src/lib/workspaceRoute.ts` — parse/serialize exact
  room/thread/message URLs, including Home root.
- `dialectic/frontend/app/src/hooks/useRoomNavigation.ts` — sole destination
  writer and service-worker acknowledgement listener.
- `dialectic/frontend/app/src/sw.ts` — notification click, warm acknowledgement
  channel, URL fallback, and cold `openWindow`.
- `dialectic/frontend/app/src/App.tsx` — exactly one history/context hydration
  path and deleted-target fallback.
- `dialectic/frontend/app/src/hooks/useDialecticSocket.ts` — thread-fenced
  attachment and reaction hydration.
- `dialectic/frontend/app/src/components/chat/MessageList.tsx` — existing
  centered scroll and flash target.
- `dialectic/frontend/app/src/App.notification.test.tsx` — hydration ordering,
  fallback, and cancellation.
- `dialectic/frontend/app/src/sw.test.ts` — warm/cold/legacy notification click
  contracts and missing-listener fallback.
- `dialectic/frontend/app/src/lib/workspaceRoute.test.ts` — exact URL and Home
  root regression.
- `dialectic/frontend/app/src/hooks/useRoomNavigation.continuity.test.tsx` —
  navigation ownership, history, and acknowledgement.

### Files/surfaces that look authoritative but are legacy or stale

- The legacy global `/api/market/polymarket` route in
  `trading/web/routes/market.py` remains for the browser. It is not the LLM
  evidence authority.
- Legacy `feed["slug"]` remains accepted for old books. It is not the preferred
  current authoring key.
- `dialectic/deploy/README.md` describes an immutable backend symlink model,
  but the installed `/etc/systemd/system/dialectic.service` and
  `/etc/systemd/system/tradingdesk.service` currently execute the canonical
  checkout. Verify the units rather than assuming the README topology.
- `.worktrees/llm-market-verification` and
  `.worktrees/llm-market-verification-integration` are completed predecessor
  worktrees. Do not build or deploy from them.
- The old 1,394-line root `PLAN.md` described prior releases and pre-deployment
  state. This document replaces it completely.

### Invariants

- Freshness timestamps are UTC/zero-offset and status/shape combinations are
  validated at the Dialectic boundary.
- `age_seconds` is monotonic and non-negative; `observed_at` is absent when no
  observation exists.
- A current failed poll never becomes success because cached data exists.
- Confirmed empty/no-data is only emitted after a completed provider attempt.
- Polymarket probabilities are finite numbers in `[0, 1]`.
- Query echo must match the requested focused query; query length is 5–500
  characters after trimming.
- `room_id`, `room_name`, `thread_id`, and `message_id` are identical across
  Web Push and Expo payload data.
- A message target is retained only when its requested thread is installed.
- All message-context reads exclude soft-deleted rows.
- Secondary media/reaction requests cannot commit after destination change.
- Public Python interfaces and legacy browser behavior remain compatible.

### Environment assumptions

- Ubuntu droplet; repository at `/root/DwoodAmo`.
- TradingDesk environment: `/root/DwoodAmo/trading/.env`.
- Dialectic environment: `/root/DwoodAmo/dialectic/.env`.
- Shared bridge secret environment variable: `TD_SERVICE_TOKEN`.
- TradingDesk local/public health:
  `http://127.0.0.1:8006/api/health`,
  `https://td.somacura.org/api/health`.
- Dialectic local/public health:
  `http://127.0.0.1:8002/health`,
  `https://dialectic.somacura.org/health`.
- PWA public origin: `https://dialectic.somacura.org`.
- PostgreSQL and Redis are required for Dialectic health.
- `dialectic_browser` is the isolated browser-acceptance database; acceptance
  must never seed production.

## VERIFICATION

### 1. Reconcile checkout and deployment before any new work

```bash
cd /root/DwoodAmo
git status --short --branch
git log -5 --oneline --decorate
systemctl cat tradingdesk.service
systemctl cat dialectic.service
systemctl is-active tradingdesk.service dialectic.service nginx
systemctl show -p MainPID,ActiveEnterTimestamp tradingdesk.service dialectic.service
readlink -f /var/www/dialectic-current
```

Expected handoff baseline: HEAD `7e91d21`, deployed merge `fda7beb`, only the
two unrelated untracked artifacts named above, three active services, and the
`20260817T044128Z-fda7beb-evidence-push` PWA release.

### 2. Runtime health and listener boundaries

```bash
curl --fail --silent --show-error http://127.0.0.1:8006/api/health | jq .
curl --fail --silent --show-error http://127.0.0.1:8002/health | jq .
curl --fail --silent --show-error https://td.somacura.org/api/health | jq .
curl --fail --silent --show-error https://dialectic.somacura.org/health | jq .
ss -ltnp | rg ':(8002|8006)'
```

Both listeners must be `127.0.0.1`, not `0.0.0.0`. Dialectic health must show
database and Redis connected plus scheduler fresh.

### 3. Live producer contract without printing secrets

```bash
cd /root/DwoodAmo
set -a
source trading/.env
set +a
curl --fail --silent --show-error --max-time 35 \
  -H "X-Service-Token: $TD_SERVICE_TOKEN" \
  http://127.0.0.1:8006/api/bridge/polymarket/trump-tariffs-graph \
  | jq '{status,configured_markets,missing_markets,markets,freshness,last_observation}'
curl --fail --silent --show-error --max-time 35 \
  -H "X-Service-Token: $TD_SERVICE_TOKEN" \
  http://127.0.0.1:8006/api/bridge/news/iran-hormuz-graph \
  | jq '{status,query,article_count:(.articles|length),freshness,last_observation}'
```

Never print `TD_SERVICE_TOKEN`. A repeated news probe may return cached
rate-limited state until cooldown expires; that is valid and must remain
explicit.

### 4. Dialectic consumer truth

```bash
cd /root/DwoodAmo/dialectic
set -a
source .env
set +a
python3 - <<'PY'
import asyncio
from llm import tools
from llm import tradingdesk_client as td

async def main() -> None:
    news = await td.service_get('/api/bridge/news/iran-hormuz-graph', timeout=25.0)
    checked = tools._validate_news_payload(news, None)
    print(checked['status'], checked['freshness'])
    if checked['status'] in {'rate_limited', 'unavailable'}:
        print(tools._degraded_evidence_message('GDELT', checked))

asyncio.run(main())
PY
```

The failed-provider message must name the current status and retry/prior
observation timing. It must not claim both sources are empty.

### 5. Full automated gate

Dialectic backend baseline:

```bash
cd /root/DwoodAmo/dialectic
python3 -m pytest -q
```

Handoff result: `1511 passed`.

TradingDesk neutral baseline:

```bash
cd /root/DwoodAmo/trading
env -u FRED_API_KEY -u EIA_API_KEY -u DEV_USER_PASSWORD \
  -u TRADING_ADMIN_PASSWORD -u DIALECTIC_ROOM_TOKENS \
  /root/DwoodAmo/trading/venv/bin/python -m pytest -q
```

Handoff result: `1426 passed, 23 skipped`; one existing Starlette/httpx
deprecation warning. Do not source the full production environment for this
suite.

Frontend baseline:

```bash
cd /root/DwoodAmo/dialectic/frontend/app
npm test -- --run
npm run lint
env -u DIALECTIC_BACKEND_URL npm run build
```

Handoff result: `40` files / `331` tests passed, lint green, production build
green. The ~508 kB chunk warning is non-fatal.

### 6. Browser acceptance

Use the isolated backend and preview commands in
`docs/superpowers/plans/2026-08-16-push-room-message-deep-links.md`, then run:

```bash
cd /root/DwoodAmo
python3 docs/superpowers/acceptance/2026-08-16-push-room-message-deep-link-acceptance.py
```

Handoff result: `18/18 passed` at `390x844` and `1024x900`. Required proof:
cold exact URL, warm service-worker entry, canonical room, correct branch,
visible flashing message, and near-center landing. Screenshots:

- `docs/superpowers/acceptance/screenshots-push-deep-link/push-message-390.png`
- `docs/superpowers/acceptance/screenshots-push-deep-link/push-message-1024.png`

The harness seeds `dialectic_browser`, never production. Stop both isolated
processes afterward.

### 7. Public PWA identity and API routing

```bash
sha256sum /var/www/dialectic-current/index.html
curl --fail --silent --show-error \
  'https://dialectic.somacura.org/?release=fda7beb' | sha256sum
curl --fail --silent --show-error \
  'https://dialectic.somacura.org/sw.js?release=fda7beb' | sha256sum
sha256sum /var/www/dialectic-current/sw.js
curl --silent --show-error --output /dev/null \
  --write-out 'status=%{http_code} content_type=%{content_type}\n' \
  https://dialectic.somacura.org/notifications/badge
```

At handoff, local/public `index.html` SHA-256 was
`fa455e662954e65d1ef9db529e3e4499a1472683e4e37995bbbfdfe080df10c2`;
local/public `sw.js` SHA-256 was
`fda9e7d5b83496c135fc038327c7aec99dff4975d0aac634ba410ac32367dbfd`.
The unauthenticated badge request must be `401 application/json`, not SPA HTML.

### 8. Post-activation log gate

```bash
journalctl -u tradingdesk.service -u dialectic.service \
  --since '2026-08-16 23:42:10' --no-pager \
  | rg 'ERROR|Traceback|Exception'
```

Handoff result: no post-deploy errors. A provider `rate_limited` status in the
API payload is operational evidence, not a backend crash.

### 9. Rollback orientation

- Frontend rollback target and manifest are listed in CURRENT STATE.
- The backend units run the canonical checkout. Do not use `git reset --hard`
  or check out an old commit over live dirty state.
- The pre-merge first parent is `4c7a40f`.
- If backend rollback is required, stop and obtain owner approval for a revert
  commit or an explicitly staged immutable worktree/unit change. Then verify
  both health surfaces and logs before flipping the frontend rollback symlink.
- No database rollback exists or is needed because this release applied no
  migration.

### Definition of done

The implemented release itself is done: merged, independently reviewed with
zero Critical/Important findings, deployed, hash-matched, health-checked, and
live-contract-proven.

The remaining follow-up is done only when:

1. The owner approves exact replacement Polymarket slugs and the three expired
   book entries are changed, tested, deployed, and observed live; or the owner
   explicitly elects to keep them as no-data.
2. A controlled physical-device notification proves the room name and exact
   message landing, with device/account/result recorded in `JOURNAL.md`; or the
   owner explicitly waives device proof.
3. The owner decides whether to push the 65 local commits, and that decision is
   executed or recorded without inference.
4. Any persistent GDELT rate-limit remediation is evidence-driven and owner-
   approved; current explicit stale/rate-limited behavior must remain intact.

## CONFLICT RULE

If implementation reality contradicts this plan, the builder flags the contradiction and stops — no silent improvisation, no quiet re-planning.

## AMENDMENTS
