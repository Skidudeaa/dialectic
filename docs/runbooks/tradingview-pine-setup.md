# TradingView Pine Script Setup

Operator runbook for wiring Pine Script alerts into the tradingDesk webhook. Covers the four canonical bindings shipped in `books/iran-hormuz-graph.json` and `books/trump-tariffs-graph.json`, plus secret rotation and troubleshooting.

## Prerequisites

- `TV_WEBHOOK_SECRET` set in the webapp environment (see `.env.example`)
- TradingView Pro+ subscription (the free tier cannot fire webhook alerts)
- A public HTTPS URL that routes to the webapp (ngrok, cloudflared, or your own nginx in front of uvicorn)
- `amo` or `dan` JWT credentials for managing bindings from the dashboard

## Architecture — what Pine Script can and cannot do

The webhook endpoint (`POST /api/tradingview/webhook`) uses HMAC-SHA256 over the raw body, with a 300-second timestamp window and nonce replay protection. That gives strong tamper resistance but means **Pine Script cannot POST directly to it** — Pine has no HMAC library and no random nonce generator.

Pick one of the two integration patterns below:

### Pattern 1: Relay service (recommended for live trading)

```
TradingView Pine alert
        │ POST (unsigned)
        ▼
 tv-webhook-relay (you run this)
        │ HMAC-sign + add timestamp + nonce
        │ POST /api/tradingview/webhook
        ▼
  tradingDesk webapp
```

The relay is tiny (~40 lines of stdlib Python — see "Minimal relay example" below). Deploy it anywhere with network access to the webapp and the `TV_WEBHOOK_SECRET`. For production, put the relay behind the same reverse proxy that terminates TLS for the webapp.

### Pattern 2: Manual fire via `sign_tv_alert.py` (for less time-sensitive signals)

Useful for the `hormuz-reopen-announced` kill-switch, where the operator is reading the news anyway. Also the right choice for smoke testing bindings you've just added.

```bash
export TV_WEBHOOK_SECRET=<same value as the webapp>
python3 tools/bridge/sign_tv_alert.py \
  --book iran-hormuz-graph \
  --binding hormuz-reopen-announced \
  --url https://tradingdesk.your-host.com/api/tradingview/webhook \
  --format curl | bash
```

## Canonical bindings

All four are pre-seeded in the books. Inspect them from the dashboard (TradingView panel) or via the API:

```bash
curl -H "Authorization: Bearer $JWT" \
  https://tradingdesk.your-host.com/api/thesis/iran-hormuz-graph/tv-bindings
```

### 1. `brent-persistence-close-above-115` (iran-hormuz-graph)

**Trade:** XOP long, Alpha v2 Trade 1. The `brent` node has `closesRequired=3` on the $115 persistence threshold. Each Pine fire increments `closesObserved`; the third fire promotes `brent` from approaching → fired.

**Pine Script alert condition:** daily close of brent (UKOIL on TradingView, or BZ=F) >= 115.

**Pine Script alert message:**
```json
{"book":"iran-hormuz-graph","bindingId":"brent-persistence-close-above-115"}
```

No `value` needed — this op doesn't take a numeric payload.

**Pine Script snippet:**
```
//@version=5
indicator("Brent persistence watch", overlay=true)
if close >= 115 and time == time(timeframe.period, "0930-1030:1234567")
    alert('{"book":"iran-hormuz-graph","bindingId":"brent-persistence-close-above-115"}', alert.freq_once_per_bar_close)
```

### 2. `hormuz-reopen-announced` (iran-hormuz-graph)

**Trade:** Kill-switch for the Iran/Hormuz book. Sets the `hormuz` event node to `resolved`, which collapses downstream amplification via the existing event→indicator edges.

**Fire manually** — this is news-driven, not chart-driven. Use `sign_tv_alert.py`:

```bash
python3 tools/bridge/sign_tv_alert.py \
  --book iran-hormuz-graph \
  --binding hormuz-reopen-announced \
  --url https://tradingdesk.your-host.com/api/tradingview/webhook \
  --format curl | bash
```

### 3. `fert-close-above-700` (iran-hormuz-graph)

**Trade:** CF long, Alpha v2 Trade 2. The `fert-shortage` price node has no yahoo feed — it's driven by a Pine alert on a proxy chart (CF or NOLA urea futures).

**Pine Script alert condition:** daily close of your chosen fertilizer proxy >= 700.

**Pine Script alert message (with Pine templating):**
```json
{"book":"iran-hormuz-graph","bindingId":"fert-close-above-700","value":{{close}}}
```

The `{{close}}` placeholder is substituted by TradingView with the actual close price at the time the alert fires. The webhook's `setCurrent` op reads this value and writes it to `fert-shortage.current`, which then triggers the existing threshold gate in `propagate()`.

**Important:** if you're using the relay pattern, the relay needs to forward the substituted body byte-for-byte so the HMAC stays valid. The relay computes the signature *after* templating, not before.

### 4. `spy-below-200dma-first-touch` (trump-tariffs-graph)

**Trade:** SPY short, Alpha v2 Trade 3. Sets `tariff-shock.probability` to confirm technical confluence with the macro recession thesis.

**Pine Script alert condition:** SPY close crosses below its 200-day SMA for the first time in 60 days.

**Pine Script alert message:**
```json
{"book":"trump-tariffs-graph","bindingId":"spy-below-200dma-first-touch","value":0.95}
```

The `value` is the new probability (0.95 = "high confidence the tariff-shock scenario is playing out"). Tune it to your own conviction level — `setProbability` accepts any float in `[0.0, 1.0]`.

## Minimal relay example

Save this as `tv-relay.py`. No pip dependencies. Run it behind a reverse proxy that terminates TLS.

```python
#!/usr/bin/env python3
"""Forwards unsigned Pine Script POSTs to the signed tradingDesk webhook."""
import hashlib, hmac, http.server, json, os, secrets, socketserver, sys, time
import urllib.request

SECRET = os.environ["TV_WEBHOOK_SECRET"].encode()
UPSTREAM = os.environ.get("TV_UPSTREAM_URL", "http://127.0.0.1:8000/api/tradingview/webhook")
PORT = int(os.environ.get("TV_RELAY_PORT", "8787"))

class Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not (0 < length <= 8192):
            self.send_error(400, "bad length"); return
        body = self.rfile.read(length)
        # Normalise: parse + re-serialise to eliminate whitespace variance
        # so HMAC stays consistent with whatever Pine actually sent.
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            self.send_error(400, "invalid json"); return
        canonical = json.dumps(payload, separators=(",", ":")).encode()
        sig = "sha256=" + hmac.new(SECRET, canonical, hashlib.sha256).hexdigest()
        req = urllib.request.Request(
            UPSTREAM,
            data=canonical,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-TV-Signature": sig,
                "X-TV-Timestamp": str(int(time.time())),
                "X-TV-Nonce": secrets.token_hex(16),
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                self.send_response(resp.status)
                self.end_headers()
                self.wfile.write(resp.read())
        except urllib.error.HTTPError as e:
            self.send_response(e.code); self.end_headers()
            self.wfile.write(e.read())
        except Exception as e:
            self.send_error(502, str(e))

    def log_message(self, *_):
        pass  # quiet

if __name__ == "__main__":
    print(f"relay listening on :{PORT} -> {UPSTREAM}", file=sys.stderr)
    socketserver.ThreadingTCPServer(("0.0.0.0", PORT), Handler).serve_forever()
```

Run it:
```bash
TV_WEBHOOK_SECRET=<secret> \
TV_UPSTREAM_URL=http://127.0.0.1:8000/api/tradingview/webhook \
python3 tv-relay.py
```

Point TradingView at `https://<public-relay-host>:8787/` — no path suffix, no auth, no headers. The relay adds everything on the way out.

## Secret rotation

Rotate `TV_WEBHOOK_SECRET` when:
- The secret is seen (logged, leaked, pasted into Slack by accident)
- On a fixed schedule (monthly is a reasonable cadence for this tier)
- After an incident, as a hygiene step

**Procedure:**

1. Generate a new secret:
   ```bash
   python3 -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
2. Update the webapp environment (`.env` or `docker-compose.yml`) with the new value.
3. Restart the webapp. The in-process nonce store is flushed, but timestamp replay is still bounded by the 300s window.
4. Update the relay's environment (`TV_WEBHOOK_SECRET`) with the same new value.
5. Restart the relay.
6. Smoke test with `sign_tv_alert.py` — expect a `200 {"status":"ok"}` response.
7. Verify the dashboard TradingView panel shows `SECURED` (not `NO SECRET`).

During the rotation window (new secret set, old still valid elsewhere), any alert signed with the old secret returns `401 bad_signature`. A few missed fires are acceptable for a rotation event.

## Troubleshooting

### `401 bad_signature`
Most common cause: the body bytes the relay signed are not identical to the body bytes the webapp verified against. Check:
- Trailing newlines or whitespace from Pine's templating
- UTF-8 vs. ASCII encoding
- Relay is re-serialising the body (see `canonical = json.dumps(...)` in the example) — if your relay passes the body through unchanged, your Pine alert message whitespace must be stable

Second cause: `TV_WEBHOOK_SECRET` mismatch between the relay and the webapp. Both must share exactly the same value.

### `410 bad_timestamp`
The `X-TV-Timestamp` header is outside the ±300s window. Check:
- Clock drift on the relay host (`date` / NTP)
- The relay is using its *current* time, not the Pine alert's original fire time

### `409 nonce_replay`
A nonce was reused within 600 seconds. Check:
- Relay is generating a fresh nonce per request (`secrets.token_hex(16)` in the example)
- The webapp was not recently restarted (in-process nonce store gets flushed, but the *new* store would still detect intra-session replay)

### `422 op not allowed on node type <t>`
The binding's declared op doesn't match the target node's type. Only the dashboard or the binding CRUD API should have been able to create this — inspect via the TradingView panel and recreate with the correct op/type pair.

### `422 probability out of [0.0, 1.0]`
The `value` in the alert body is outside the probability range. Check the Pine Script message template. Note that `setProbability` and `setCurrent` both expect the value in the body, not in the binding.

### `404 unknown bindingId`
The binding was deleted from the book since the Pine alert was configured. Recreate via the TradingView panel or re-seed the binding.

### `404 book not found`
The `book` field in the Pine message uses a kebab-case id that doesn't match any `books/*.json` stem. Check the active theses table in `CLAUDE.md`.

### `429 rate limit exceeded`
The per-IP token bucket is full. By default the webhook accepts 60 requests/minute per source IP. Raise via `TV_WEBHOOK_RATE_LIMIT_PER_MIN` env var if your alert volume is legitimately higher (unlikely for thesis-graph use cases — each alert maps to a macro trade decision, not high-frequency ticks).

## Audit trail

Every webhook attempt — success, auth failure, rate limit, op rejection — is appended to `web/data/tradingview-events.jsonl`. The dashboard TradingView panel shows the last 20 events for the active book. Filter from the command line:

```bash
# Most recent 10 events for iran-hormuz-graph
tail -100 web/data/tradingview-events.jsonl | \
    grep '"bookId":"iran-hormuz-graph"' | tail -10
```

The log is append-only — rotate manually when it grows past ~10 MB (no automatic rotation in v1).

## Related

- `docs/plans/2026-04-10-001-feat-tradingview-webapp-integration-plan.md` — the integrated architecture plan
- `.planning/tv-plan/plan-alpha-v2.md` — the original CLI-centric proposal (historical, superseded)
- `web/tv_webhook.py` — HMAC verification source
- `web/adapters/tradingview.py` — binding resolution + op enforcement
- `web/routes/tradingview.py` — FastAPI route handlers
- `tools/bridge/sign_tv_alert.py` — the signing helper referenced throughout this runbook
