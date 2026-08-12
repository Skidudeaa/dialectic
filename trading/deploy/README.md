# Deployment

Production deployment artifacts for the tradingDesk backend. Everything in this directory gets installed once per host; the app itself is a single systemd service wrapping the FastAPI uvicorn process.

Current target: one DigitalOcean droplet, single worker, nginx in front terminating TLS.

## What's in here

- `tradingdesk.service` — the systemd unit. Installed to `/etc/systemd/system/tradingdesk.service`.

## First-time install (fresh droplet)

```bash
# 1. The desk is the trading/ subtree of the DwoodAmo monorepo (since 2026-08-09).
#    Clone the monorepo, not this directory. Paths below assume the default
#    location; change them in the unit file if you put it elsewhere.
git clone <dwoodamo-repo> /root/DwoodAmo
cd /root/DwoodAmo/trading

# 2. Python venv + deps
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. Build the frontend
cd frontend && npm install && npm run build && cd ..

# 4. Create the env file (see .env.example for the full list of vars)
cp .env.example .env
chmod 600 .env
# Then edit .env with real secrets:
#   - JWT_SECRET       (generate: python3 -c "import secrets; print(secrets.token_urlsafe(32))")
#   - DEV_USER_PASSWORD (password for the amo/dan logins)
#   - TV_WEBHOOK_SECRET (generate same way)
#   - OPENROUTER_API_KEY (optional, enables @claude/@gpt/@compare in chat)
#   - DIALECTIC_ROOM_TOKENS ("<room-uuid>:<token>,..." — REQUIRED for the
#     snapshot push; the books no longer carry these, see room_tokens.py)
#   - DIALECTIC_ROOM_TOKEN (legacy single-room fallback, optional)
#   Rooms whose thesis was created FROM Dialectic register their token at
#   runtime instead: /var/lib/tradingdesk/room-tokens.env (0600, written by
#   POST /api/bridge/room-token; env wins on conflict). No restart needed,
#   and nothing to add here for those rooms — but the file must survive
#   reprovisioning like the SQLite DB beside it.

# 5. Install the systemd unit
cp deploy/tradingdesk.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now tradingdesk

# 6. Verify
systemctl status tradingdesk
curl http://127.0.0.1:8006/api/health
```

The service binds to loopback at `127.0.0.1:8006`; nginx is its only public
entry point.

## Public HTTPS (nginx + Cloudflare)

Live at **`https://td.somacura.org`**. The droplet is **shared** with other sites,
so the Trading Desk vhost is kept in its own isolated file and never edits the
others.

**The vhost** — `/etc/nginx/sites-available/td.somacura.org` (symlinked into `sites-enabled/`) reverse-proxies to `127.0.0.1:8006`, with WebSocket upgrade handling on `/ws/` for live chat/streaming. It listens on **both `:80` and `:443`**:
- `:80` — what Cloudflare actually hits today, because the `somacura.org` zone runs in Cloudflare **"Flexible"** SSL mode (shared with `feb8.somacura.org`, whose origin is `:80`-only).
- `:443` — a self-signed origin cert at `/etc/ssl/cloudflare/td.somacura.org.{crt,key}`, ready for a per-hostname upgrade to "Full" (see below). It's self-signed on purpose: Cloudflare "Full" (non-strict) doesn't validate the origin cert, so a Cloudflare Origin cert isn't required.

**DNS:** `td` A record in the **`somacura.org`** Cloudflare zone → `167.99.113.232`, **proxied (orange cloud)**. The browser↔Cloudflare hop uses Cloudflare's trusted edge cert.

**Firewall:** `ufw` opens `80/443` to **Cloudflare IP ranges only** — the origin isn't directly reachable on those ports, so the unencrypted Flexible hop is not publicly exposed.

```bash
# Always validate before reloading — a syntax error would take down ALL sites on this box.
nginx -t && systemctl reload nginx      # reload, never restart (zero-downtime, keeps other vhosts)

# Verify (origin both ports, then through Cloudflare):
curl -s  -H "Host: td.somacura.org" http://127.0.0.1/api/health     # :80  (Flexible path)
curl -sk -H "Host: td.somacura.org" https://127.0.0.1/api/health    # :443 (Full path)
curl -s  https://td.somacura.org/api/health                          # public, via Cloudflare
```

**Encrypting the Cloudflare↔origin hop (optional hardening).** The whole `somacura.org` zone is on Flexible (HTTP to origin). **Do NOT flip the zone to "Full"** — that breaks `feb8.somacura.org`, which has no `:443` origin. Instead scope it to this hostname only:

> Cloudflare dashboard → **SSL/TLS → Configuration Rules** → new rule:
> *When hostname equals `td.somacura.org`* → set **SSL = Full**.

The `:443` self-signed block already in the vhost handles it — no cert paste, no zone change, `feb8` untouched.

**Renew the self-signed origin cert** (only relevant once on Full; expires in 10 years, so rarely):

```bash
openssl req -x509 -nodes -newkey rsa:2048 -days 3650 \
  -keyout /etc/ssl/cloudflare/td.somacura.org.key \
  -out    /etc/ssl/cloudflare/td.somacura.org.crt \
  -subj "/CN=td.somacura.org" -addext "subjectAltName=DNS:td.somacura.org"
chmod 600 /etc/ssl/cloudflare/td.somacura.org.key
nginx -t && systemctl reload nginx
```

> If you instead point a **grey-cloud (DNS-only)** record straight at the droplet, use real Let's Encrypt instead of the above: `certbot --nginx -d <host> --redirect`. That path needs port 80 reachable from the internet (loosen the Cloudflare-only `ufw` rule first).

## Day-to-day operations

```bash
# Deploy a code change
cd /root/DwoodAmo/trading
git pull
# If frontend changed:
cd frontend && npm run build && cd ..
# If requirements.txt changed:
source venv/bin/activate && pip install -r requirements.txt && deactivate
# Roll the service (picks up new code + env vars)
systemctl restart tradingdesk
systemctl status tradingdesk

# Tail logs
journalctl -u tradingdesk -f

# Last 100 log lines (non-follow)
journalctl -u tradingdesk -n 100 --no-pager

# Stop without auto-restart
systemctl stop tradingdesk

# Full restart (picks up systemd unit changes)
systemctl daemon-reload && systemctl restart tradingdesk
```

## Rotating a secret

Any secret lives in `.env` — `JWT_SECRET`, `DEV_USER_PASSWORD`, `TV_WEBHOOK_SECRET`, `OPENROUTER_API_KEY`, `DIALECTIC_ROOM_TOKENS`. Procedure:

> **Room tokens have a second half.** `DIALECTIC_ROOM_TOKENS` is compared
> against `rooms.token` in dialectic's Postgres, so rotating one means
> changing it in BOTH places or that room's push goes quiet. Verify with a
> read-only call per room — `GET /stakes/rooms/{id}/commitments` with the
> token as a Bearer header should return 200, and a wrong token 401. Do not
> verify via `tradingdesk-bridge.timer`: it only pushes when a snapshot
> changed, so a clean run proves nothing about auth.

```bash
# 1. Edit .env with the new value
vim /root/DwoodAmo/trading/.env
# 2. Restart the service
systemctl restart tradingdesk
# 3. Verify
systemctl status tradingdesk
curl -sf http://127.0.0.1:8006/api/health
```

**Side effects to know:**
- Rotating `JWT_SECRET` logs out every browser session — users need to log in again.
- Rotating `TV_WEBHOOK_SECRET` breaks any Pine Script relays — update them to the new value.
- Rotating `DEV_USER_PASSWORD` changes the amo/dan login password.
- Rotating `OPENROUTER_API_KEY` just needs a restart; no user-visible impact beyond chat.

## Unit file details

| Setting | Value | Why |
|---|---|---|
| `Restart=always` | | Auto-restart on crash, kill, OOM |
| `RestartSec=5` | | Backoff before relaunch — prevents tight loops on broken configs |
| `TimeoutStopSec=15` | | Graceful shutdown window for uvicorn to drain in-flight requests |
| `EnvironmentFile=/root/DwoodAmo/trading/.env` | | All secrets load from `.env` (not baked into the unit file) |
| `StandardOutput=journal` | | `journalctl -u tradingdesk` captures stdout |
| `StandardError=journal` | | Same for stderr |
| `SyslogIdentifier=tradingdesk` | | Easy to find in general journal |
| `StartLimitIntervalSec=300` / `StartLimitBurst=5` | | After 5 restarts in 5 min, systemd stops trying — crash-loop guard |

## Porting to a different path

The unit file hardcodes `/root/DwoodAmo/trading` in `WorkingDirectory`, `EnvironmentFile`, and `ExecStart`. If you deploy to a different path, edit those three lines in `tradingdesk.service` before copying to `/etc/systemd/system/`. Single `sed` works:

```bash
sed -i 's|/root/DwoodAmo/trading|/opt/tradingdesk|g' deploy/tradingdesk.service
```

## Future hardening (not yet applied)

- Run as non-root user (`User=tradingdesk`) — requires fixing file ownership on `books/`, `snapshots/`, `web/data/`, `outcomes/`.
- Sandbox with `ProtectSystem=full` + `ReadWritePaths=` — blocks most filesystem writes except the paths the app actively mutates.
- Multi-worker uvicorn (`--workers 2`) — requires swapping the in-process nonce store + rate limiter + state cache for a shared store (Redis). Not a concern at current traffic.
