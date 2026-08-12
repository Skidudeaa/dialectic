# Commands

## dialectic
```bash
cd dialectic && DATABASE_URL="postgresql://root@localhost/dialectic" PORT=8002 python3 run.py   # backend dev
cd dialectic && python3 -m pytest tests/ -q          # ~790 tests
cd dialectic/frontend/app && npm run dev             # frontend dev
cd dialectic/frontend/app && npm run build           # tsc -b && vite build
cd dialectic/frontend/app && npm run lint
```

## trading (tradingDesk)
```bash
cd trading && python3 -m pytest --collect-only -q    # ~1359 collected
cd trading && venv/bin/uvicorn web.main:app --port 8006   # local run (prod is loopback-only :8006)
cd trading/frontend && npm run dev / build / lint
cd trading/frontend && npm run test                  # vitest run
```

## Production services (see `mem:deploy` before restarting)
```bash
systemctl status dialectic tradingdesk
journalctl -u dialectic --since "10 min ago"   # journalctl parses LOCAL time; app logs stamp UTC
curl -s localhost:8002/health
```

## Linux-specific notes
- `journalctl --since/--until` = local time; app logs = UTC. Convert before concluding absence.
- tradingDesk SPA answers unknown GETs with 200+HTML — check content-type, never just status code, when probing :8006.
