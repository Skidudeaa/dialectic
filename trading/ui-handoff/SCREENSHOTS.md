# Trading Desk — UI Screenshot Index

Captured 2026-06-09 at 1600×1000, logged in as `amo`, against the live FastAPI
backend + Vite dev server. Each shot below maps to the source file(s) you'd edit
to change it.

> **Design system lives in one file: `frontend/src/index.css`** — Tailwind v4
> `@theme` tokens (the `void`/`surface`/`elevated` dark palette, `amber` + `teal`
> accents, JetBrains Mono + Inter, custom `btn`/`btn-primary` utilities, WCAG-checked
> muted text). Change the look there; change layout in the components below.

| # | Screenshot | Panel / surface | Source file(s) |
|---|---|---|---|
| 01 | `01-login.png` | Login screen | `src/pages/Login.tsx` |
| 02 | `02-onboarding-tour.png` | First-run product tour (step 1 of 7) | `src/components/onboarding/OnboardingTour.tsx`, `onboarding/steps/*` |
| 03 | `03-dashboard-full.png` | Full dashboard shell (top bar, book tabs, sidebar, panels) | `src/pages/Dashboard.tsx`, `src/components/BookTabBar.tsx` |
| 04 | `04-chat-and-thesis.png` | Default 3-pane: Rooms+Watchlist / Chat / Thesis | `src/components/Chat.tsx`, `MarketTicker.tsx`, `ThesisViewer.tsx` |
| 05 | `05-thesis-viewer-hormuz.png` | Thesis viewer — cascade tracker, node states, confluence, deadlines | `src/components/ThesisViewer.tsx`, `TVIndicatorBadge.tsx` |
| 06 | `06-predictions.png` | Prediction tracker (right panel) | `src/components/PredictionTracker.tsx` |
| 07 | `07-trade-journal.png` | Trade journal (right panel) | `src/components/TradeJournal.tsx` |
| 08 | `08-tradingview.png` | TradingView panel — webhook URL, bindings, alert feed | `src/components/TradingViewPanel.tsx` |
| 09 | `09-cross-book-matrix.png` | Cross-book signal matrix | `src/components/CrossBookMatrix.tsx`, `CrossBookPanel.tsx` |
| 10 | `10-morning-brief.png` | Morning brief (right panel) | `src/components/MorningBrief.tsx` |
| 11 | `11-trade-lifecycle.png` | Trade lifecycle / predicate monitor | `src/components/TradeLifecyclePanel.tsx` |
| 12 | `12-agent-in-room.png` | Agent-in-room panel | `src/components/AgentInRoomPanel.tsx` |
| 13 | `13-command-palette.png` | Command palette (Ctrl+K) | `src/components/CommandPalette.tsx` |
| 14 | `14-thesis-builder.png` | Thesis Builder — phase-laned DAG canvas + property panel | `src/components/builder/ThesisBuilder.tsx`, `GraphCanvas.tsx`, `NodeEditor.tsx`, `EdgeEditor.tsx`, `InstrumentEditor.tsx`, `ScenarioEditor.tsx`, `RulesEditor.tsx`, `MetaEditor.tsx` |
| 15 | `15-welcome-page.png` | Welcome / guide page (full scroll) | `src/pages/Welcome.tsx`, `src/components/welcome/*` |

## Shared / cross-cutting components (visible across shots)
- Top bar, book selector, panel-toggle rail, connection status, outbox badge,
  presence pills → `src/pages/Dashboard.tsx`, `OutboxBadge.tsx`, `PresencePills.tsx`
- Toasts → `src/components/Toast.tsx` + `toast.ts`
- Left sidebar Watchlist → `src/components/MarketTicker.tsx`

## The API contract (what feeds every panel)
- `src/lib/types.ts` — all data shapes
- `src/lib/api.ts` — every REST endpoint + the WebSocket client
- `src/lib/outbox.ts` — offline retry queue (the "N queued" badge)

## Notes for the dev
- The app is a single dense SPA; "panels" on the right are toggled, not routed.
- Two routes exist beyond the dashboard: `/builder` (Thesis Builder) and `/welcome`.
- Aesthetic is deliberately dense/terminal (13px base). Keep the token system —
  don't introduce a second palette or font stack.
