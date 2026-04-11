# tradingDesk — User Manual

A collaborative analysis workspace for two traders. Think: a living research notebook where the math keeps your thesis honest, the chat room lets you argue with the AIs, and every trigger and trade is tracked from first-idea to post-mortem.

---

## 1. Getting in

**URL:** `http://167.99.113.232:8006`
**Users:** `amo` or `dan` (pick your handle)
**Password:** set in the `.env` file on the server as `DEV_USER_PASSWORD`

If the login form rejects you:
- Did you type the username in lowercase? It's case-insensitive but best to match.
- If you just rotated the password, the `.env` change only takes effect after `systemctl restart tradingdesk`.
- If the page is perpetually loading, skip to **§9 Troubleshooting**.

Your session lasts **72 hours**. After that you'll be bounced back to the login screen. The JWT token is stored in your browser's localStorage under `td_auth` — clearing cookies wipes it.

---

## 2. The dashboard at a glance

```
┌────────────────────────────────────────────────────────────────────────┐
│ tradingDesk   [room name]            [🔧 panel tabs] [user] [logout]  │ ← top bar
├──────────────┬─────────────────────────────────────────┬───────────────┤
│ ROOMS        │                                         │               │
│ ▸ hormuz-1   │  [chat messages, newest at bottom]      │  Thesis view  │
│ ▸ tariffs    │                                         │  ◉ Cascade    │
│ [+ new]      │                                         │  ◉ Nodes      │
│              │                                         │  ◉ Confluence │
│ WATCHLIST    │                                         │  ◉ Countdowns │
│ XOP   95.21  │                                         │  ◉ Scenarios  │
│ XLE  121.4   │  ---                                    │               │
│ CF   136.4   │  [type here to chat]               [→]  │               │
└──────────────┴─────────────────────────────────────────┴───────────────┘
   SIDEBAR               CHAT (center)                      RIGHT PANEL
```

- **Sidebar (left)** — your rooms + live watchlist prices. Collapse with the chevron on the top bar.
- **Chat (center)** — the conversation for the currently-selected room. Empty until you pick a room.
- **Right panel** — context. Switches between 6 tabs: Thesis, Brief, Cross-Book, Predictions, Journal, TradingView. Close it with `Esc`.

---

## 3. The essentials

### 3a. Create a room for a thesis

1. Click the `+` next to **ROOMS** in the sidebar (or press `Ctrl+K` → "New room").
2. Type a name (e.g. `hormuz-1` or `tariffs-q2`).
3. Pick a **linked book** from the dropdown (`iran-hormuz-graph` or `trump-tariffs-graph`). The room is now tied to that thesis — whenever you fetch fresh prices or a TradingView alert fires, a system message lands in this room.
4. Click **Create**.

You and Dan can both be in the same room at the same time. Green dots next to usernames mean "currently viewing".

### 3b. Talk to the AIs

In chat, mention the model you want:

- `@claude the brent move just broke our trade 1 thesis — what am I missing?`
- `@gpt write a 3-bullet post-mortem on why the XOP entry didn't trigger`
- `@gemini what's the precedent for a hormuz closure lasting > 3 weeks?`
- `@compare should we close the CF position?` — runs all 3 models side-by-side, lets you pick which answer you trust

The AI sees the **full current thesis state** of the room's linked book when it answers — node states, confluence scores, active scenarios, countdowns. You don't have to paste context.

### 3c. Slash commands

Type these at the start of a chat message:

| Command | What it does |
|---|---|
| `/brief` | Drops the current morning brief into the room (thesis state + cross-book flags + open trades) |
| `/thesis` | Paste the current snapshot summary inline |
| `/diff` | Show what changed since the last price fetch |
| `/predict Will X happen by Y?` | Create a prediction right from chat |
| `/watchlist` | Show the watchlist with live prices |

### 3d. Pin a message

Hover a message → click the pin icon. Pinned messages stay at the top of the room so neither of you loses the important context. Unpin by clicking again.

### 3e. Export the chat

Top right of the chat panel: **Export** button → downloads the full conversation as a markdown file, timestamps and all. Good for post-mortems and for pasting into a Dialectic room.

---

## 4. Reading the Thesis Viewer (right panel)

Click the 📊 tab (or press `Ctrl+K` → "Thesis panel"). Pick a book from the dropdown.

### Cascade phase

```
CASCADE                              APPROACHING
  ▓ ▓ ▓ ▓ ░
  3. Amplification
```

**5 phases**: Shock → Transmission → Amplification → Policy Response → Resolution. The bar shows how far the cascade has progressed. A filled bar means that phase has fired; the rightmost filled box is "where we are now". **Amplification** and beyond = real PnL risk.

### Node list

Every node in the thesis with its current state, sorted by severity:

```
hormuz             [fired]
brent              [approaching]   RSI:47 ATR:8.8
em-stress          [fired]
...
```

- `fired` (red) — the node's threshold has been crossed. The causal chain is propagating.
- `approaching` (amber) — we're inside 5% of the trigger level, or the upstream is firing.
- `stable` (grey) — nothing's moving.
- `gated` / `constrained` — dependency not met yet.
- `monitoring` — default, no signal.

The tiny **RSI / ATR badges** beside some nodes come from local RSI/ATR computed over Yahoo's 3-month daily close series. They are **display-only** — they do NOT move the DAG. Treat them as "here's where the chart is technically" not "here's a new cause."

- RSI >= 70 → amber (overbought, possibly exhausted)
- RSI <= 30 → teal (oversold, possible reversal)
- 30–70 → muted grey (no signal)

### Confluence scores

```
CONFLUENCE
  em-stress              ███████░░  1.67
  earnings-compression   █████████  2.05
```

How many independent causal paths are converging on that node. Higher = more conviction. `2.0+` means at least three upstream paths are all firing simultaneously — this is the trade setup signal.

### Countdowns

Deadline nodes with days-remaining:

```
DEADLINES
  Planting Cycle Miss    6d    ← urgent, red
  Section 122 expiry    27d    ← amber
```

< 7 days = red (urgent), < 14 days = amber, else muted.

### Scenarios

```
SCENARIOS
  reopen-apr1        10%   -5.2
  closed-may         45%  +12.8
  kharg-strike       15%  +22.4
```

Probability × net impact per scenario. Positive = thesis-friendly, negative = thesis-breaking. Useful as a sanity check: the sum of your scenario probabilities should be ~1.0, and the probability-weighted expected value tells you if the market is pricing the risk correctly.

---

## 5. Fetching fresh prices

The thesis state can go stale. To pull live Yahoo + Polymarket data:

1. Open the thesis panel for the book you want.
2. There's a refresh button at the top of the panel — click it.

Behind the scenes:
- Yahoo fetches refresh every price node and instrument ref
- Polymarket refreshes every event node with a `polymarket` feed
- The derived indicator overlays (RSI/ATR/SMA) recompute from the latest 3 months of OHLCV
- `closesObserved` counters on persistence-gated nodes bump if the Yahoo close series shows additional closes over threshold
- A system message lands in every room linked to this book showing what changed (`state transitions`, `confluence shifts`, `market moves > 1%`)

**When to do it:** before a trade decision, at the start of the trading day, after a material news event.
**When not to do it:** for every little question — it costs ~10 seconds and the 60-second cache will serve stale data anyway between fetches.

---

## 6. Trade Journal & Predictions

### Trade Journal (📘 tab)

Every trade you place should be logged here. Click **+ new entry**:

- **Thesis** — which book this trade is under (`iran-hormuz-graph` / `trump-tariffs-graph`)
- **Instrument** — ticker (`XOP`, `CF`, `SH`, …)
- **Direction** — `long` or `short`
- **Entry price** — what you filled at
- **Tags** — free-form (`trade-1`, `hedge`, `kill-switch-active`, …)
- **Notes** — why you took the trade

When you close, edit the entry and fill in **exit price** + **P&L** + closing **notes**. The entry is a permanent ledger row — treat it as your record of the day you took the trade and the day you closed it.

### Predictions (🎯 tab)

Shorter-form calls, usually yes/no market questions:

- **Statement** — "Brent closes above $110 by end of April"
- **Confidence** — 0.0 to 1.0 (be honest)
- **Deadline** — when the question resolves
- **Linked book** — optional

When the deadline passes, click **Resolve** and mark it correct/incorrect. Your accuracy stats show up at the top of the panel — calibration feedback in aggregate.

---

## 7. TradingView integration

The dashboard receives real-time alerts from TradingView Pine Script and feeds them into the thesis. Open the ⚡ **TradingView** tab to see the status.

### What you see

- **Webhook URL** — copy this, give it to TradingView (or your relay)
- **SECURED / NO SECRET** — whether `TV_WEBHOOK_SECRET` is set in the backend env
- **Rate / skew / nonces** — current webhook config (60 req/min per IP, ±300s timestamp window)
- **Bindings** — every Pine alert that's been wired to mutate a graph node. Shows fire count + last-fired time
- **Recent alerts** — last 20 webhook hits (success + failure, color-coded)

### The four binding types

| Op | What it does | Use when |
|---|---|---|
| `incrementClosesObserved` | Bumps the persistence counter on a price node | Pine fires on "daily close above $X" for a node with `closesRequired` |
| `setNodeState` | Directly sets an event node's state (e.g. → `resolved`) | Manual kill-switches when news hits (e.g. "Hormuz reopen announced") |
| `setProbability` | Sets an event node's probability (0.0–1.0) | Technical confirmation of macro thesis (e.g. "SPY broke 200dma → bump tariff-shock prob to 0.95") |
| `setCurrent` | Sets a price node's current value directly | Nodes with no Yahoo feed (e.g. NOLA urea, where you proxy off a different chart) |

### Canonical bindings already wired

The four bindings from the shipping plan are already seeded:

- **`brent-persistence-close-above-115`** → brent node. Each Pine fire → 3 fires required to promote.
- **`hormuz-reopen-announced`** → hormuz node → resolved. Your kill-switch for the entire iran-hormuz book.
- **`fert-close-above-700`** → fert-shortage node. Pine body must include `"value": <close>`.
- **`spy-below-200dma-first-touch`** → tariff-shock event. Pine body must include `"value": 0.95`.

### Wiring a Pine alert

Full procedure lives in `docs/runbooks/tradingview-pine-setup.md`. Short version:

1. TradingView Pine Script can't compute HMAC signatures — run a **relay** in between (example in the runbook).
2. On the relay, point TradingView at `https://<relay>/` and give it the JSON body (e.g. `{"book":"iran-hormuz-graph","bindingId":"brent-persistence-close-above-115"}`).
3. The relay signs the body with `TV_WEBHOOK_SECRET`, adds timestamp + nonce, forwards to `https://<dashboard>/api/tradingview/webhook`.
4. Watch the **Recent alerts** section of the TradingView panel to confirm it landed.

### Testing a binding manually

```bash
export TV_WEBHOOK_SECRET=<the value in your .env>
python3 tools/bridge/sign-tv-alert.py \
  --book iran-hormuz-graph \
  --binding brent-persistence-close-above-115 \
  --url http://167.99.113.232:8006/api/tradingview/webhook \
  --format curl | bash
```

Success looks like:
```json
{"status":"ok","bookId":"iran-hormuz-graph","nodeId":"brent","op":"incrementClosesObserved","newValue":1}
```

---

## 8. Keyboard shortcuts

| Key | What it does |
|---|---|
| `Ctrl+K` / `Cmd+K` | Command palette (rooms, panels, actions — fuzzy search) |
| `Esc` | Close the command palette → close the right panel → collapse sidebar (in that order) |
| `Enter` in chat | Send the message |
| `Shift+Enter` in chat | New line (for multi-line messages) |

---

## 9. When something is wrong

### "I can't log in"
- Check the URL — it's `http://167.99.113.232:8006` (not https, not a different port).
- The password is in the server's `.env` file as `DEV_USER_PASSWORD`. If you don't know it, SSH to the droplet and read the file.
- If you just changed the password, the service needs to restart: `ssh droplet; systemctl restart tradingdesk`.

### "The page is perpetually loading"
On the droplet:
```bash
# Is the backend actually running?
systemctl status tradingdesk
# Tail the logs for errors
journalctl -u tradingdesk -n 100 --no-pager
# Is port 8006 listening?
ss -tlnp | grep :8006
```
Usually one of:
- The service died and the `RestartSec=5` backoff hasn't kicked in yet — wait 10 seconds and retry.
- An environment variable is missing — check `.env` against `.env.example`.
- A Python import error — check the log, fix the code, `systemctl restart tradingdesk`.

### "My TradingView alert didn't fire"
1. Open the **TradingView** tab → scroll to **Recent alerts**. Does your attempt show up?
2. If yes with a red status: read the status (`bad_signature` / `bad_timestamp` / `nonce_replay` / `mutation_rejected` / `rate_limited`). Each is explained in `docs/runbooks/tradingview-pine-setup.md`.
3. If no status at all: the request never reached the backend. Check your relay logs, DNS, and the webhook URL.
4. Smoke test with `sign-tv-alert.py` (above) — if that works, the backend is fine and the problem is in your relay or Pine config.

### "Chat AI isn't responding"
- Check `/api/health` — `llm_available` should be `true`. If `false`, `OPENROUTER_API_KEY` is unset or invalid.
- If `true` but answers never come: OpenRouter may be rate-limiting or down. Try a different `@model`.
- `@compare` running 4 models in parallel can take 30+ seconds — be patient.

### "My trade journal entry disappeared"
It didn't — entries are appended to `web/data/journal.jsonl` on disk. If the UI doesn't show it:
- Reload the page.
- Check the file: `cat /root/tradingDesk/web/data/journal.jsonl | tail -5`.
- If the file's healthy but the UI's empty, file bug.

### "Fetch prices takes forever"
Normal. Each book fetches:
- All Yahoo symbols in one batch call (~2 sec)
- Polymarket probabilities per event node (~1 sec per slug)
- OHLCV for every symbol with a `derivedIndicators` spec (~0.5 sec per symbol)
Total: 5–20 seconds depending on book size. If it's stuck > 60 seconds, something's wrong — check the logs.

### "I want to stop the server without it auto-restarting"
```bash
ssh droplet
systemctl stop tradingdesk  # ← won't auto-restart
# when you want it back:
systemctl start tradingdesk
```

### "I want to wipe my local session and start fresh"
Browser: Ctrl+Shift+Del → clear cookies and localStorage for `167.99.113.232`.

---

## 10. Where things live

| Need | Location |
|---|---|
| The architecture / technical docs | `CLAUDE.md` |
| Deployment instructions | `deploy/README.md` |
| TradingView Pine setup | `docs/runbooks/tradingview-pine-setup.md` |
| Feature plans (implemented + proposed) | `docs/plans/` |
| Solved bugs / past issues | `docs/solutions/` |
| The two active thesis configs | `books/iran-hormuz-graph.json`, `books/trump-tariffs-graph.json` |
| Latest snapshots (what the pipeline last exported) | `snapshots/{book-id}-latest.json` |
| Trade ledger | `outcomes/trades/TRD-*.jsonl` |
| Webhook audit log | `web/data/tradingview-events.jsonl` |

---

**One rule of thumb:** when in doubt, open the thesis panel, fetch fresh prices, and read the log. The dashboard is your eyes; the log is your hands. Everything else is just conversation.
