# Production deploy — house rules

- **Both systemd units run their git working trees.** A restart deploys whatever is on disk. NEVER restart with uncommitted edits in the tree; freeze restarts while any agent has WIP in flight.
- `dialectic.service` :8002 (Postgres); `tradingdesk.service` :8006 loopback-only (SQLite `/var/lib/tradingdesk/`, WorkingDirectory `/root/DwoodAmo/trading`, uses `trading/venv`).
- dialectic.service does NOT hot-reload — backend edits require an explicit restart to take effect; a live probe before restart reads the OLD code.

## Deploy order (three independent steps, in order)
1. **Migration**: `psql`, verify with `\d`.
2. **Backend restart**: `systemctl restart dialectic`, then verify `/health` with a real request — `systemctl is-active` fires into the startup window and is not enough.
3. **Frontend release**: build → copy to `/var/www/dialectic-releases/<ts>-<name>` → flip `/var/www/dialectic-current` symlink → `systemctl reload nginx`.

- Auth-touching changes: deploy tradingDesk FIRST, then the dialectic frontend flip.

## Verification gotchas
- tradingDesk SPA answers unknown GETs 200+HTML — check content-type.
- `journalctl --since` parses LOCAL time; app logs stamp UTC.
- The dialectic↔tradingDesk seam and auth bridge details: `mem:trading/core` (bridge endpoints, tokens) and `mem:dialectic/core` (reconcile schedule).
