# Handoff — Dialectic Field Desk: tradingDesk2.zip implementation (2026-06-09)

**Session scope:** implement `tradingDesk2.zip` (the Claude Design "Field Desk"
dossier mockup) against the live webapp, then close the gaps that made the live
version read flat next to the mockup.

## Where things stand

The Field Desk is live at **`/dialectic`** (https://td.somacura.org/dialectic),
served by the `tradingdesk` systemd unit (uvicorn `:8006` ← nginx ← Cloudflare).
The classic desk at `/` is unchanged and links to it via the amber
**◆ FIELD DESK** header button and a command-palette entry.

`frontend/dist` is what production serves — **rebuild after any frontend
change** (`cd frontend && npm run build`); no service restart needed for
assets.

## Commits this session (oldest first)

| Commit | What |
|---|---|
| `5fb9e97` | tradingDesk2 deltas: `.exhibit` code-block CSS (markup existed, styles didn't), node market readings (`.cur`) in cockpit signals, `tv-alert` WS frames → FLASH/CONFIRM telex lines in the stream, `prefers-reduced-motion`. Plus: dialectic kill-flow sent **no auth header** (read `.access_token`, storage has `.token`) — fixed via `getToken()`. |
| `e8871fa` | Same auth-header bug fixed in `TradeLifecyclePanel`. |
| `d1e5e05` | Pre-existing lint errors cleared (BookTabBar helpers → `lib/bookState.ts`, Date.now purity in PresencePills/ThesisViewer, this-alias suppression in api.ts). |
| `016e9dd` | Field Desk discoverability: header button + palette action (it was URL-only before). |
| `750b6e0` | Mockup-parity fixes: case drawer shows live phase + colored diamond + confluence bar for **every** case (`useCasePulses`, 120s poll), mock-style short titles, and case↔room mismatch fixed (unlinked case now falls back to a *general* room with an honest kicker, not another case's stream). |

## Key files

- `frontend/src/components/dialectic/` — `DialecticRoute.tsx` (shell/rail),
  `DialecticRoom.tsx` (stream/composer), `DialecticCockpit.tsx` (situation
  board + TERMINATE), `data.ts` (live hooks), `dialectic.css` (Dark Roast,
  all scoped under `.dlx`).
- Mockup source of truth: `tradingDesk2.zip` in repo root (untracked) —
  `Dialectic.html` + `data.js`/`room.js`/`cockpit.js`/`app.js`.

## Verified vs not

- **Verified live in a browser:** exhibit styling, cockpit market readings,
  case drawer pulses, room fallback kicker, kill-flow 409 confirm-token round
  trip (requested token, then cancelled — no trade harmed).
- **Code-in-place, not live-fired:** the TV-alert FLASH/CONFIRM telex. Every
  canonical binding mutates real thesis state, so no signed webhook was fired.
  To exercise: `tools/bridge/sign_tv_alert.py` with the Field Desk open.

## Known gaps / next steps

1. **Only one room is linked to a book** (`test1` → `iran-hormuz-graph`).
   The other four cases fall back to a general room. Link rooms to books to
   give each case its own dispatch stream.
2. **Mock vs live density:** the mockup is a curated demo (scripted narrative,
   tool-trace blocks, rev badges). Live renders real data; agent tool traces
   and rev numbers have no backend support — drop or build, decide later.
3. **Open question for Amo:** should `/dialectic` become the default
   post-login view? One-line route change in `App.tsx`; not done because not
   yet requested.
4. TV telex entries are ephemeral (by design — durable record is
   `web/data/tradingview-events.jsonl`). Could hydrate recent alerts from the
   audit log on room load if persistence is wanted.
5. One queued learning pending `/reflect`.

## Pre-flight status at handoff

`npm run lint` clean · 34/34 tests pass · build clean · Cloudflare serving the
current bundle (verified hash match origin↔edge).
