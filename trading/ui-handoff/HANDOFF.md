# Trading Desk — Frontend UI/UX Handoff

You're enhancing an existing React 19 + Vite + Tailwind v4 SPA. **Match the existing
design system, then improve** — don't design fresh. The look is fully captured here.

## What's in this package
- `screenshots/` + `SCREENSHOTS.md` — every panel, each mapped to its source file.
- `frontend/` — the full UI source (edit this). The two most important files:
  - `src/index.css` — the entire design system (Tailwind v4 `@theme` tokens).
  - `src/lib/types.ts` + `src/lib/api.ts` — the data contract every panel renders.

## Run it locally
The frontend needs a backend on `:8006` (Vite proxies `/api` and `/ws` there).

```bash
# 1. Frontend
cd frontend
npm install
npm run dev            # http://localhost:5173

# 2. Backend (separate terminal, from repo root) — ask the owner for this half,
#    or point the proxy at a mock. Minimal boot:
pip install -r requirements.txt
JWT_SECRET=dev DEV_USER_PASSWORD=testpass123 \
  uvicorn web.main:app --port 8006
```

Log in with `amo` / `testpass123` (dev users: `amo`, `dan`).

## Scope
- Two routes beyond the dashboard: `/builder` and `/welcome`. Everything else is
  toggled right-side panels, not separate pages.
- Keep the token system in `index.css` — one palette (`void`/`amber`/`teal`), one
  font stack (JetBrains Mono + Inter), 13px dense base. No second design language.
- `lint` + `test` before handing back: `npm run lint && npm run test`.
