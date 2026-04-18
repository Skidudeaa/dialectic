# Deployment

Production deployment artifacts for the dialectic backend. Single systemd service wrapping the `python3 run.py` entry point.

Current target: one DigitalOcean droplet (`167.99.113.232`), co-located with the tradingDesk backend (which pushes thesis snapshots into dialectic over `localhost:8002`).

## What's in here

- `dialectic.service` — the systemd unit. Installed to `/etc/systemd/system/dialectic.service`.

## First-time install (fresh droplet)

```bash
# 1. Clone the repo (paths in the unit file assume /root/DwoodAmo/dialectic — adjust if different)
git clone <repo> /root/DwoodAmo/dialectic
cd /root/DwoodAmo/dialectic

# 2. Python deps. Dialectic uses the system python (no venv) so the systemd unit
#    can run `/usr/bin/python3 run.py` without venv activation. Install with
#    --break-system-packages on Debian/Ubuntu Python 3.11+ where PEP 668 applies.
/usr/bin/pip3 install --break-system-packages -r requirements.txt

# 3. Postgres + pgvector
createdb dialectic
psql dialectic -c "CREATE EXTENSION IF NOT EXISTS vector;"
psql dialectic < schema.sql
for m in migrations/*.sql; do psql dialectic < "$m"; done

# 4. Create the .env file (gitignored, file-permission 600 recommended)
cat > .env <<'EOF'
DATABASE_URL=postgresql://localhost/dialectic
JWT_SECRET_KEY=<generate: python3 -c "import secrets; print(secrets.token_hex(32))">
ALLOWED_ORIGINS=http://localhost:3000,http://localhost:8002
PORT=8002
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...   # optional, enables LLM fallback + vector embeddings
EOF
chmod 600 .env

# 5. Install + enable + start the systemd unit
cp deploy/dialectic.service /etc/systemd/system/dialectic.service
systemctl daemon-reload
systemctl enable dialectic.service
systemctl start dialectic.service

# 6. Verify
systemctl status dialectic --no-pager | head -8
curl -s http://127.0.0.1:8002/health
```

Expected `/health` response: `{"status":"ok","checks":{"db":"connected","redis":"not configured (in-memory mode)"}}`.

## Day-to-day operations

```bash
# Logs (tailing)
journalctl -u dialectic -f

# Logs (last 100 lines, no pager)
journalctl -u dialectic -n 100 --no-pager

# Restart after code update (git pull)
cd /root/DwoodAmo/dialectic && git pull && systemctl restart dialectic

# Restart after .env edit
systemctl restart dialectic

# Apply a new migration
psql dialectic < migrations/NNN_*.sql
systemctl restart dialectic
```

## Updating secrets

`.env` is the canonical secrets store. Systemd reloads it on every service start, so:

```bash
# Edit .env (e.g. rotate ANTHROPIC_API_KEY)
${EDITOR:-vi} /root/DwoodAmo/dialectic/.env

# Apply
systemctl restart dialectic
```

`.env` is gitignored; never commit it. If you need to share secret values across hosts, use a secrets manager — don't email the file.

## Troubleshooting

**Service is `active` but `curl` to :8002 hangs / connection refused**

Likely the worker subprocess crashed on startup but the controller is still alive. Check `journalctl -u dialectic -n 50 --no-pager` for the import error or env-validation failure, fix, restart.

**`Address already in use` on startup**

Another process is holding port 8002 (often an orphan from before the systemd migration). Find + kill:
```bash
ss -tlnp | grep ":8002"
kill -9 <pid>
systemctl restart dialectic
```

**`Missing required environment variables: ANTHROPIC_API_KEY`**

The `EnvironmentFile=` directive in the unit points at `/root/DwoodAmo/dialectic/.env`. Make sure the file exists, is readable by root, and the variable is set without quotes (systemd's parser is stricter than shell):
```
ANTHROPIC_API_KEY=sk-ant-...
```
Not:
```
ANTHROPIC_API_KEY="sk-ant-..."   # bad — quotes become part of the value
export ANTHROPIC_API_KEY=...     # bad — `export` not understood
```

**`ModuleNotFoundError` on startup**

The unit uses `/usr/bin/python3` (system python), not a venv. Reinstall deps system-wide:
```bash
/usr/bin/pip3 install --break-system-packages -r requirements.txt
systemctl restart dialectic
```

**Service flaps (start → fail → restart loop)**

`Restart=always` will keep retrying every 5 seconds. The unit caps the loop at 5 starts per 5 minutes (`StartLimitBurst=5`, `StartLimitIntervalSec=300`); after that it gives up. Look at the journal between flaps to find the underlying error.

## Reverting to manual launch

If you need to bypass the service for debugging:

```bash
systemctl stop dialectic
cd /root/DwoodAmo/dialectic
set -a && source .env && set +a
python3 run.py
# Ctrl-C when done, then `systemctl start dialectic` to restore
```
