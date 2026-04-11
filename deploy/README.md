# Deployment

Production deployment artifacts for the tradingDesk backend. Everything in this directory gets installed once per host; the app itself is a single systemd service wrapping the FastAPI uvicorn process.

Current target: one DigitalOcean droplet, single worker, nginx in front terminating TLS.

## What's in here

- `tradingdesk.service` — the systemd unit. Installed to `/etc/systemd/system/tradingdesk.service`.

## First-time install (fresh droplet)

```bash
# 1. Clone the repo (paths assume /root/tradingDesk; change in the unit file if different)
git clone <repo> /root/tradingDesk
cd /root/tradingDesk

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
#   - DIALECTIC_ROOM_TOKEN (optional, for tools/bridge/push-to-dialectic.py)

# 5. Install the systemd unit
cp deploy/tradingdesk.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now tradingdesk

# 6. Verify
systemctl status tradingdesk
curl http://127.0.0.1:8006/api/health
```

The service binds to `0.0.0.0:8006`. Front it with nginx/cloudflared for TLS termination before exposing publicly.

## Day-to-day operations

```bash
# Deploy a code change
cd /root/tradingDesk
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

Any secret lives in `.env` — `JWT_SECRET`, `DEV_USER_PASSWORD`, `TV_WEBHOOK_SECRET`, `OPENROUTER_API_KEY`, `DIALECTIC_ROOM_TOKEN`. Procedure:

```bash
# 1. Edit .env with the new value
vim /root/tradingDesk/.env
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
| `EnvironmentFile=/root/tradingDesk/.env` | | All secrets load from `.env` (not baked into the unit file) |
| `StandardOutput=journal` | | `journalctl -u tradingdesk` captures stdout |
| `StandardError=journal` | | Same for stderr |
| `SyslogIdentifier=tradingdesk` | | Easy to find in general journal |
| `StartLimitIntervalSec=300` / `StartLimitBurst=5` | | After 5 restarts in 5 min, systemd stops trying — crash-loop guard |

## Porting to a different path

The unit file hardcodes `/root/tradingDesk` in `WorkingDirectory`, `EnvironmentFile`, and `ExecStart`. If you deploy to a different path, edit those three lines in `tradingdesk.service` before copying to `/etc/systemd/system/`. Single `sed` works:

```bash
sed -i 's|/root/tradingDesk|/opt/tradingdesk|g' deploy/tradingdesk.service
```

## Future hardening (not yet applied)

- Run as non-root user (`User=tradingdesk`) — requires fixing file ownership on `books/`, `snapshots/`, `web/data/`, `outcomes/`.
- Sandbox with `ProtectSystem=full` + `ReadWritePaths=` — blocks most filesystem writes except the paths the app actively mutates.
- Multi-worker uvicorn (`--workers 2`) — requires swapping the in-process nonce store + rate limiter + state cache for a shared store (Redis). Not a concern at current traffic.
