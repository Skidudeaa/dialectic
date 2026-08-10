# tradingDesk

The market-cognition organ of the dialectic app: a causal-DAG thesis engine plus a live data service. Five thesis books are evaluated against Yahoo / Polymarket / GDELT / Treasury feeds on their own clocks, and state changes reach dialectic within one coordinator tick.

Runs as `tradingdesk.service` — FastAPI + uvicorn on port 8006 (loopback, nginx in front at `https://td.somacura.org`), SQLite at `/var/lib/tradingdesk/tradingdesk.db`. Ops runbook: [`deploy/README.md`](deploy/README.md).

## Run Locally

### Web service

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn web.main:app --reload --port 8006
```

Env vars (see `.env.example`): `JWT_SECRET`, `DEV_USER_PASSWORD`, `TV_WEBHOOK_SECRET`, `OPENROUTER_API_KEY`, plus the dialectic vars listed under Integration below.

### CLI dashboard generation (still works — stdlib only)

```bash
# Interactive single-file HTML dashboard
python3 tools/thesis_graph/thesisgraph.py books/iran-hormuz-graph.json \
  -o output/iran-hormuz-graph.html

# With live prices (Yahoo Finance + Polymarket)
python3 tools/thesis_graph/thesisgraph.py books/iran-hormuz-graph.json \
  -o output/iran-hormuz-graph.html --fetch

# Validate a book, no output
python3 tools/thesis_graph/thesisgraph.py books/iran-hormuz-graph.json --dry-run

# Export evaluated graph state as JSON
python3 tools/thesis_graph/thesisgraph.py books/iran-hormuz-graph.json \
  --export-state snapshots/latest.json

# Diff two snapshots (exit 0 = changed, 1 = identical, 2 = error)
python3 tools/bridge/diff_snapshots.py snapshots/old.json snapshots/new.json

# Manual kick of the full pipeline for all books (fetch → export → diff → push)
python3 tools/bridge/run-all.py --dry-run
```

The dashboard has 5 tabs: **Graph** (interactive Cytoscape.js DAG), **Cascade** (5-phase crisis tracker), **Scenarios** (probability-weighted portfolio impact), **Portfolio**, **Journal**. Open the HTML in any browser — no server needed.

## Books

| Config | Thesis | Nodes | Edges | Monthly Budget |
|---|---|---|---|---|
| `books/iran-hormuz-graph.json` | Iran/Hormuz oil shock transmission | 19 | 16 | $8,000 |
| `books/trump-tariffs-graph.json` | Trump tariff escalation | 15 | 18 | $6,000 |
| `books/ai-capex-unwind-graph.json` | AI capex unwind | 14 | 16 | $7,000 |
| `books/china-property-cascade-graph.json` | China property + EM cascade | 16 | 17 | $9,000 |
| `books/japan-rate-shock-graph.json` | Japan rate normalization shock | 14 | 17 | $10,000 |

Node/edge counts and budgets read from the book JSONs (`meta.monthlyBudget`). New book: copy an existing config, keep the `meta` / `nodes` / `edges` / `instruments` / `scenarios` / `cascadePhases` / `fetchSymbols` sections, validate with `--dry-run`.

## Dialectic Integration

The 2026-03-30 design in [`INTEGRATION.md`](INTEGRATION.md) is superseded (its header says so). Live wiring since 2026-08-09:

- **Push (desk → dialectic):** the runtime coordinator POSTs a v3 snapshot on material change plus an hourly heartbeat — `web/runtime/dialectic_push.py`. Failures spool to `snapshots/outbox/` and drain on recovery. Target from `DIALECTIC_URL` (default `http://localhost:8002`).
- **Bridge (dialectic → desk):** read-only endpoints `GET /api/bridge/snapshot/{thesis_id}` and `GET /api/bridge/news/{thesis_id}` — `web/routes/bridge.py`, authenticated by `X-Service-Token` header against `TD_SERVICE_TOKEN`. Dialectic's LLM calls 11 read-only tools against these.
  - News: every book declares a watch-only GDELT rhetoric node, which is what makes `/news/{book}` answer with headlines instead of `"no gdelt config"`. Those nodes deliberately carry **no `current` key** — the coordinator skips fetching for a node that cannot receive a value, so the whole per-IP GDELT budget belongs to the bridge. Adding `current` to one opts it into volume fetching and starts costing a request every tick.
  - GDELT rejects quoted terms shorter than 5 characters ("The specified phrase is too short"), which is why the catalog in `tools/data_fetch/gdelt.py` spells out `Bank of Japan`, `Taiwan Semiconductor` and `local government financing` rather than BOJ/TSMC/LGFV.
- **Auth bridge:** dialectic-issued JWTs are accepted and mapped to local users via `DIALECTIC_USER_MAP`; a `dialectic` service user is created from `DIALECTIC_SERVICE_PASSWORD` — `web/auth.py`.
- Master plan: `/root/DwoodAmo/docs/plans/2026-Q3-consigliere-amendment-1-fusion.md`.

The duplicated social tier (chat / rooms / Field Desk) still exists in `web/` but is scheduled for removal in the C4 cull. `tools/validation/mock_dialectic.py` is legacy from the old push era, pending the same cull.

## Tests

1359 tests collected (`python3 -m pytest --collect-only -q`). Run by area:

```bash
python3 -m pytest tools/ -q    # engine, bridge, data fetch, outcomes, validation
python3 -m pytest web/ -q      # web layer, coordinator, bridge routes
```

## Structure

```
trading/
├── books/        # 5 thesis configs (one JSON per thesis)
├── tools/        # stdlib-only CLIs: thesis_graph, bridge, data_fetch, outcomes, validation
├── web/          # FastAPI service: routes/, runtime/ (coordinator + dialectic push), persistence/
├── frontend/     # React + Vite SPA (built dist served by FastAPI)
├── snapshots/    # per-book latest/prev state + outbox spool
├── outcomes/     # trade ledger (open_trades.json + trades/*.jsonl)
├── deploy/       # systemd unit + ops runbook
└── docs/         # user manual, plans, runbooks, solutions
```

## Requirements

- Python 3.10+
- Web layer: FastAPI, uvicorn, python-jose, httpx, websockets — see `requirements.txt` / `pyproject.toml`
- `tools/` CLIs remain stdlib-only by convention; pytest for tests
