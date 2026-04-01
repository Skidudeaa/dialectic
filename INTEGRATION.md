# tradingDesk × Dialectic Integration

> **STATUS: FULLY IMPLEMENTED** (2026-04-01)
>
> Both sides are built and live. Both thesis rooms are wired. Run `python3 tools/bridge/run-all.py` from tradingDesk to push fresh thesis state into both Dialectic rooms. The LLM in each room sees the full thesis state (node states, confluence, countdowns, scenarios, portfolio) on every message.
>
> **Live rooms:**
> - Iran/Hormuz: `56ba2f1e-5c70-4290-a77d-52404f0095da` (Dialectic `localhost:8002`)
> - Trump Tariffs: `8adcabb7-817a-4802-87c6-3bfd42e6a9eb` (Dialectic `localhost:8002`)
>
> **Dialectic server:** `/root/DwoodAmo/dialectic` — `PORT=8002 python dialectic/run.py`

---

## The Idea

You and Dan discuss markets in Dialectic. The LLM participates as an equal — but right now it has no idea what your actual positions are, what triggers are approaching, or what the thesis graph says.

Path B: tradingDesk pushes thesis graph state into Dialectic as structured context. The LLM sees the graph when you talk. When Dan says "should we add to CF?", the LLM can say "fertilizer stress node is at 97.6% of threshold, 17 days to planting deadline, and the Kharg scenario shows CF +7.2%."

When you're offline and a trigger fires, the Trading Curator generates an alert in the room for Dan to see when he logs in.

---

## Data Flow

```
tradingDesk                          Dialectic
─────────────                        ─────────

thesisgraph.py
  --fetch --export-state ──────────→ POST /rooms/{id}/trading/snapshot
                                         │
                                         ├─→ Store as room-scoped memory
                                         │   (versioned, embedded, searchable)
                                         │
                                         ├─→ Broadcast to connected clients
                                         │   (WebSocket: "trading_update")
                                         │
                                         ├─→ If user offline:
                                         │   TradingCurator generates alert
                                         │   "Brent crossed $115 — persistence
                                         │    trigger approaching. 17 days to
                                         │    planting deadline."
                                         │
                                         └─→ Next LLM prompt includes:
                                             ## Trading Thesis State
                                             Phase 2: Transmission (STARTING)
                                             FIRED: hormuz, diesel, dxy-stress...
                                             APPROACHING: brent (97.9%), fert (97.6%)
                                             Confluence: em-stress = 1.30
                                             Countdown: 17d to planting deadline
                                             Portfolio: XOP $1400/mo, CF $800/mo...
```

---

## What tradingDesk Adds

### `--export-state` flag on thesisgraph.py

New flag that dumps evaluated graph state as JSON instead of (or in addition to) generating HTML.

```bash
# Export state only
python3 thesisgraph.py books/iran-hormuz-graph.json --export-state snapshots/latest.json

# Fetch live prices + export state
python3 thesisgraph.py books/iran-hormuz-graph.json --fetch --export-state snapshots/latest.json

# Full pipeline: fetch + export + generate HTML
python3 thesisgraph.py books/iran-hormuz-graph.json --fetch --export-state snapshots/latest.json -o output/iran-hormuz-graph.html
```

### `push-to-dialectic.py` — bridge script

```bash
# Push latest snapshot to a Dialectic trading room
python3 tools/bridge/push-to-dialectic.py \
  --snapshot snapshots/latest.json \
  --room-id <uuid> \
  --dialectic-url http://localhost:8000 \
  --token <room-token>
```

Or combined:
```bash
# One-liner: fetch prices → evaluate graph → push to Dialectic
python3 thesisgraph.py books/iran-hormuz-graph.json \
  --fetch --export-state - | \
  python3 tools/bridge/push-to-dialectic.py \
  --snapshot - --room-id <uuid>
```

### Snapshot JSON shape (what gets pushed)

```json
{
  "v": 1,
  "timestamp": "2026-03-30T14:00:00Z",
  "title": "Iran/Hormuz Thesis — March 2026",

  "nodeStates": {
    "hormuz": "fired",
    "brent": "approaching",
    "diesel": "fired",
    "fert-shortage": "approaching",
    "planting-miss": "approaching",
    "em-stress": "fired",
    "services": "gated"
  },

  "confluenceScores": {
    "em-stress": 1.30
  },

  "cascadePhase": {
    "number": 2,
    "key": "transmission",
    "status": "STARTING"
  },

  "countdowns": [
    {"nodeId": "planting-miss", "label": "Planting Cycle Miss", "deadline": "2026-04-15", "daysRemaining": 17}
  ],

  "marketSnapshot": {
    "brent": 112.57,
    "diesel": 5.38,
    "nolaFert": 683,
    "dxy": 100.18,
    "curveSpread": 15
  },

  "scenarioImpacts": {
    "reopen-apr1": {"probability": 0.10, "netImpact": -5.2},
    "closed-may": {"probability": 0.45, "netImpact": +12.8},
    "kharg-strike": {"probability": 0.15, "netImpact": +22.4},
    "selective-reopen": {"probability": 0.30, "netImpact": +4.1}
  },

  "portfolioSummary": {
    "monthlyBudget": 8000,
    "topPositions": ["XOP $1400/mo", "XLE $1200/mo", "SGOV $1200/mo", "GLD $1000/mo"],
    "sgovAvailable": 1200
  }
}
```

### Delta detection

```bash
# Compare two snapshots, output only what changed
python3 tools/bridge/diff-snapshots.py snapshots/2026-03-29.json snapshots/2026-03-30.json
```

Output:
```json
{
  "stateChanges": [
    {"nodeId": "freight", "from": "approaching", "to": "fired", "reason": "diesel sustained above $5.25"}
  ],
  "confluenceChanges": {
    "em-stress": {"from": 1.30, "to": 1.75}
  },
  "countdownChanges": [
    {"nodeId": "planting-miss", "from": 18, "to": 17}
  ],
  "marketChanges": {
    "brent": {"from": 112.57, "to": 114.20, "pctChange": 1.4}
  }
}
```

Only deltas get pushed to Dialectic as alerts. No noise.

---

## What Dialectic Adds

### 1. REST endpoint: `POST /rooms/{room_id}/trading/snapshot`

Receives the snapshot JSON from tradingDesk. Stores it as a room-scoped memory via the existing `MemoryManager`. Broadcasts to connected WebSocket clients.

```python
@app.post("/rooms/{room_id}/trading/snapshot")
async def inject_trading_snapshot(room_id: UUID, request: TradingSnapshotRequest, ...):
    # Store as versioned memory (auto-embedded for semantic search)
    await memory_manager.add_memory(
        room_id=room_id,
        key=f"thesis_state_{request.timestamp[:10]}",
        content=format_snapshot_for_memory(request),
        scope=MemoryScope.ROOM,
    )

    # Store raw JSON in room config for prompt injection
    await db.execute(
        "UPDATE rooms SET trading_config = $2 WHERE id = $1",
        room_id, json.dumps(request.dict())
    )

    # Broadcast to connected clients
    await connection_manager.broadcast(room_id, OutboundMessage(
        type="trading_update", payload=request.dict()
    ))

    # If any user offline, trigger trading curator
    if await annotator.should_annotate(room_id, system_user_id):
        await trading_curator.generate_alert(room_id, request)
```

### 2. Prompt injection: thesis state in LLM context

Extend `PromptBuilder.build()` — insert between room context (step 5) and user preferences (step 6):

```python
# In prompts.py, after room_context:
if room.trading_config:
    tc = json.loads(room.trading_config)
    thesis_section = f"""
## Trading Thesis State (as of {tc['timestamp']})

**Phase:** {tc['cascadePhase']['number']} — {tc['cascadePhase']['key']} ({tc['cascadePhase']['status']})

**Node States:**
{chr(10).join(f"- {nid}: {state}" for nid, state in tc['nodeStates'].items() if state in ('fired', 'approaching'))}

**Confluence:** {', '.join(f"{nid}={score}" for nid, score in tc.get('confluenceScores', {}).items())}

**Countdowns:** {', '.join(f"{c['label']}: {c['daysRemaining']}d" for c in tc.get('countdowns', []))}

**Scenarios (probability-weighted):**
{chr(10).join(f"- {sid}: {s['probability']*100:.0f}% → net {s['netImpact']:+.1f}%" for sid, s in tc.get('scenarioImpacts', {}).items())}

**Portfolio:** {', '.join(tc.get('portfolioSummary', {}).get('topPositions', []))}

When discussing trading decisions, reference this thesis state. Flag disagreements between the thesis and the conversation. If a trigger is approaching threshold, mention it proactively.
"""
    system_parts.append(thesis_section)
```

### 3. Trading Curator (async alerts when offline)

Extend `AnnotatorEngine` with a trading-specific identity:

```python
TRADING_CURATOR_IDENTITY = """You are a trading curator in a collaborative thesis room.
When new market data arrives and a participant is offline:

1. SIGNAL: Flag nodes that changed state (approaching → fired, new confluences)
2. COUNTDOWN: Highlight approaching deadlines ("17 days to planting deadline")
3. RISK: Note portfolio vulnerabilities if triggers are approaching stops
4. ACTION: Suggest what to discuss when the offline person returns
5. DISAGREE: If the data contradicts something said in recent conversation, flag it

Keep it brief. One paragraph max. This is an alert, not an essay."""
```

Triggered when a snapshot arrives and one user is offline. Generates an `LLM_ANNOTATOR` message in the room that the offline user sees on return.

### 4. Trading Panel in UI (right sidebar tab)

New tab in `RightPanel.tsx` showing:
- Node state badges (fired/approaching/gated)
- Active countdowns
- Portfolio summary
- Scenario probabilities
- Last snapshot timestamp

No graph visualization in Dialectic — the full interactive graph stays in the tradingDesk HTML. Dialectic shows the summary state.

---

## Room Setup

```bash
# Create a trading room in Dialectic
curl -X POST http://localhost:8000/rooms \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Iran/Hormuz Trading Room",
    "global_ontology": "Commodity trading thesis discussion. Two traders (Amo and Dan) managing an active commodity book focused on the Iran/Hormuz oil shock and its transmission chains.",
    "global_rules": "Reference the thesis graph state when making claims. Flag when personal opinion diverges from the model. Escalate approaching triggers proactively."
  }'
```

The `global_ontology` and `global_rules` fields already exist and are already injected into every LLM prompt. No schema changes needed for this part.

---

## Build Order

### Week 1: tradingDesk export ✅ DONE

1. ✅ Add `--export-state` flag to thesisgraph.py
2. ✅ Implement snapshot JSON export (the shape above)
3. ✅ Build `diff-snapshots.py` for delta detection
4. ✅ Test: `--fetch --export-state` produces valid JSON

### Week 2: Dialectic endpoint + memory storage ✅ DONE

1. ✅ Add `POST /rooms/{room_id}/trading/snapshot` endpoint (`api/main.py`)
2. ✅ Store snapshots as room-scoped memories (`memory/manager.py`)
3. ✅ Store latest snapshot in `room.trading_config` (JSONB)
4. ✅ Add `TRADING_SNAPSHOT_RECEIVED` event type

### Week 3: LLM context + curator ✅ DONE

1. ✅ Extend `PromptBuilder.build()` with thesis state section (`llm/prompts.py`)
2. ✅ Create `TradingCuratorEngine` (`llm/trading_curator.py`)
3. ✅ Annotator fires alongside primary LLM (both paths run concurrently)
4. ✅ LLM reads thesis state: node states, confluence, countdowns, scenarios, portfolio

### Week 4: Bridge + automation ✅ DONE

1. ✅ `push-to-dialectic.py` bridge script with retry + token auth
2. ✅ `run-all.py` multi-book runner: `python3 tools/bridge/run-all.py`
3. ✅ Per-book room IDs and tokens in `meta.dialecticRoomId` / `meta.dialecticRoomToken`
4. ✅ Cron-ready (see Quick Start in CLAUDE.md)

### Week 5: UI panel ⏳ PARTIAL

The thesis state is visible in Dialectic's Memory panel (`thesis_state_current` key, v10+). A dedicated Trading Panel tab in the right sidebar was planned but not yet built — the memory panel serves the same purpose adequately for now.

---

## What This Gets You

**Before:** You and Dan talk in Dialectic about markets. The LLM tries to help but has no idea about your positions, triggers, or thesis structure. You switch to the tradingDesk HTML to check the graph, then go back to Dialectic to discuss.

**After:** The LLM sees the thesis graph in real-time. When Dan says "diesel is crushing truckers," the LLM responds: "The freight node just fired — diesel at $5.38 is above the $5.25 demand destruction threshold. This cascades to employment with a 1-3 month lag per the 2008 template. Your XOP position is +11.6% to target with 1.3:1 R:R. The planting deadline is in 17 days — if fertilizer stays above $700, Layer 3 activates."

When you're asleep and Brent crosses $115, the Trading Curator drops a message: "Brent persistence trigger approaching — $115 for 3 closes. Dan, if this holds through Wednesday, the framework says deploy $400 SGOV → XOP."

That's the collaborative judgment toolkit.
