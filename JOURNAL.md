[2026-08-11] verified Serena access boundary — CLI 1.7.0 is installed, but DwoodAmo is not registered and Serena is not exposed in this Codex session's MCP tools
[2026-08-11] `serena project create` found an existing DwoodAmo project — Claude Code's Serena health probe had auto-created it, so reused the generated configuration instead of overwriting it
[2026-08-11] registered and indexed DwoodAmo in Serena with Python and TypeScript — retained Claude Code's connected cwd-aware setup, added the equivalent Codex registration, and ignored generated Serena caches/logs
[2026-08-11] reviewed live project and upgrade state with Serena — healthy HTTP masked a scheduler outage after unattended upgrades restarted Postgres and invalidated the scheduler's held pool proxy
[2026-08-11] verified room-token exposure without printing credentials — all five tokens published in git history still match production; the corrected env/process/database comparison is 5/5 after an awk reserved-name dead end
[2026-08-11] refreshed verification baseline — 790 backend tests and the frontend production build pass; frontend lint fails at App.tsx:254 for assigning a ref during render
[2026-08-11] approved production stabilization design — recover scheduler connections at the ledger boundary, health-check the existing heartbeat, rotate all room tokens, and repair lint/systemd before separate P2 work
[2026-08-11] found canonical tradingDesk unit drift before install — preserve the live monorepo paths and loopback bind while moving start-limit keys into Unit
[2026-08-11] preserved cold-start room deep links during lint repair — synchronize switchRoomRef before the one-shot URL effect consumes its room target
[2026-08-11] aligned tradingDesk deployment docs with the canonical unit — port 8006 is loopback-only and nginx is the public entry point
[2026-08-11] token rotation guard rolled back two incomplete activations — the five-thesis first tick needs more than 30 seconds and Cloudflare returns 403 to urllib while curl succeeds
[2026-08-11] rotated all five published room tokens and activated the corrected tradingDesk unit — old tokens are 401, new tokens are 200, env/database/process match 5/5, and local/public readiness pass
[2026-08-11] deployed scheduler recovery and the lint-clean frontend — health reports a fresh heartbeat, the ledger advances, and the served versioned asset digest matches the committed build
[2026-08-11] selected personal cross-room memory promotion — store per-user grants without mutating shared memory scope so one collaborator cannot alter another's LLM context
[2026-08-11] planned personal promotion as four isolated implementation units plus verification — schema, manager recall, authenticated REST, and minimal PWA controls remain separately reviewable while activation stays deferred
