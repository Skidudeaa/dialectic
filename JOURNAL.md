[2026-08-11] verified Serena access boundary — CLI 1.7.0 is installed, but DwoodAmo is not registered and Serena is not exposed in this Codex session's MCP tools
[2026-08-11] `serena project create` found an existing DwoodAmo project — Claude Code's Serena health probe had auto-created it, so reused the generated configuration instead of overwriting it
[2026-08-11] registered and indexed DwoodAmo in Serena with Python and TypeScript — retained Claude Code's connected cwd-aware setup, added the equivalent Codex registration, and ignored generated Serena caches/logs
[2026-08-11] reviewed live project and upgrade state with Serena — healthy HTTP masked a scheduler outage after unattended upgrades restarted Postgres and invalidated the scheduler's held pool proxy
[2026-08-11] verified room-token exposure without printing credentials — all five tokens published in git history still match production; the corrected env/process/database comparison is 5/5 after an awk reserved-name dead end
[2026-08-11] refreshed verification baseline — 790 backend tests and the frontend production build pass; frontend lint fails at App.tsx:254 for assigning a ref during render
[2026-08-11] approved production stabilization design — recover scheduler connections at the ledger boundary, health-check the existing heartbeat, rotate all room tokens, and repair lint/systemd before separate P2 work
[2026-08-11] found canonical tradingDesk unit drift before install — preserve the live monorepo paths and loopback bind while moving start-limit keys into Unit
