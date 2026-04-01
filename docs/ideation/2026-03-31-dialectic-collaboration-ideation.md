---
date: 2026-03-31
topic: dialectic-collaboration
focus: working feature set with backbone of Dialectic/dWoodAmo collaboration functionality
---

# Ideation: Dialectic Collaboration Feature Set

## Codebase Context

**Project shape:** Python stdlib-only causal reasoning engine. Two active theses (Iran/Hormuz 16 nodes, Trump tariffs 15 nodes). Core pipeline: JSON thesis config → topological DAG propagation → snapshot JSON export → diff-snapshots.py → push-to-dialectic.py → Dialectic room.

**What's built:** tradingDesk side is complete (export, diff, push, mock server, 118 tests). Dialectic side is in-progress (endpoint, memory storage, LLM prompt injection, Trading Curator).

**Collaboration context:** Dan and Amo discuss markets in Dialectic. LLM participates as collaborator and sees thesis state in real-time. Trading Curator alerts the offline user when a trigger fires.

**Pain points:**
- diff-snapshots.py requires two explicit file paths; without rotation, keeping an "old" snapshot to diff against is manual and error-prone
- Snapshot export only records categorical node states (fired/approaching/stable) — the numeric proximity (% of threshold) that is already computed by the propagation engine is discarded at export time
- No explicit kill-switch conditions per thesis; the system models "things progressing" well but not "we were wrong about the causal structure"
- Two active theses require two separate command invocations; no unified runner exists
- No validation that live market prices are consistent with the stated node states at push time

**Past learnings:** XSS doc notes snapshot data flowing back into the dashboard HTML needs `esc()` at every innerHTML site — relevant if round-trip ever occurs.

---

## Ranked Ideas

### 1. Snapshot Ring Buffer
**Description:** On each pipeline run, instead of overwriting `snapshots/latest.json`, rotate: save the new snapshot as `snapshots/YYYY-MM-DD-{thesis}-{run}.json`, maintain a `latest.json` symlink, and automatically determine `previous.json` (the prior run) so `diff-snapshots.py` can be called without manual path management. Keep the last N snapshots (configurable, default 30 days).

**Rationale:** `diff-snapshots.py` was designed to require two file paths, but the "old" path doesn't exist unless someone manually saved it before the current run. In practice this means the conditional-push pipeline (`diff → only push if something changed`) breaks unless the user explicitly manages file names. A ring buffer makes this automatic. It also enables "what changed this week?" queries.

**Downsides:** Adds disk footprint (small — JSON snapshots are ~2KB each). Introduces file naming conventions that must be stable. If the ring fills with identical snapshots, diffing becomes noisier, but exit code 1 (no changes) already handles this.

**Confidence:** 82%
**Complexity:** Low
**Status:** Unexplored

---

### 2. Divergence Alerts
**Description:** Before pushing a snapshot to Dialectic, run a divergence check: compare the `marketSnapshot` live prices against each node's configured threshold. If a node is marked `approaching` but its current price is above the fire threshold, flag it as divergent (stale state, price already past trigger). If a node is marked `fired` but its price has retreated materially below threshold, flag it as potentially stale. Surface divergent nodes in the diff output and optionally block the push pending confirmation.

**Rationale:** The propagation engine evaluates node states at generation time. If prices move between `--fetch` runs, the snapshot state becomes stale without any visible signal. Pushing stale-contradicted state into Dialectic means the LLM reasons from a lie: "brent is approaching threshold" while the live price is $8 past it. Divergence detection is garbage-in-garbage-out prevention at the integration boundary. All data needed is already in the snapshot (marketSnapshot + node threshold config).

**Downsides:** Requires access to threshold values at push time (currently in the book JSON, not in the snapshot export). Either the snapshot needs to export threshold values, or the bridge script needs to read the book JSON. Adds a step that could block automated pushes, creating friction if thresholds are imprecise.

**Confidence:** 85%
**Complexity:** Medium
**Status:** Unexplored

---

### 3. Signal Severity + Proximity Export
**Description:** Extend the snapshot export to include a `nodeProximity` field alongside `nodeStates`: for each node with a numeric threshold, export the current proximity as a percentage (e.g., `"brent": 0.979` = 97.9% of threshold). The propagation engine already computes this for the HTML dashboard meter bars — this exports it instead of discarding it. The Curator alert in Dialectic can then say "diesel at 97.9% of $5.25 threshold" rather than just "diesel: approaching."

**Rationale:** The binary state categories (approaching/fired/stable) are sufficient for graph coloring but too coarse for the collaboration use case. When Amo is offline and the Curator fires an alert, "freight node approaching" is much less actionable than "freight at 94.3% of $5.25 sustained-stress threshold — 2 closes at current rate." The proximity data is already computed — it's just not in the export contract. Schema change is additive and backward compatible.

**Downsides:** Proximity is only meaningful for nodes with numeric thresholds (price/indicator types). Event and deadline nodes don't have continuous proximity. The export needs to handle this gracefully (null or omit for non-numeric nodes).

**Confidence:** 78%
**Complexity:** Low
**Status:** Unexplored

---

### 4. Multi-Book Runner
**Description:** Add `--all` flag to the pipeline wrapper (or create a `run-all.py` script) that reads every JSON in `books/`, skips legacy configs (based on a `"type": "commodity-book"` marker), and runs each through the full pipeline: fetch → export → diff → conditional push. Room ID lives in the book JSON meta block (`"dialecticRoomId": "..."`), not on the command line. One command runs both theses. Cron-compatible.

**Rationale:** Two active theses currently require two separate commands with different room IDs. As thesis count grows, this becomes a maintenance tax. More importantly, it makes automated scheduling fragile — a cron job for two theses is two cron entries, each with its own token and room-ID configuration to keep synchronized. Putting room-id in the book config makes adding a new thesis a data-only change (write the JSON, run `--all`).

**Downsides:** Meta fields in the book JSON add schema surface area. If a book is tested without a valid room-id, the push step will fail — need graceful handling (skip push if no roomId configured). The `--all` flag needs to aggregate exit codes sensibly across multiple books.

**Confidence:** 88%
**Complexity:** Low
**Status:** Explored (brainstorm: `docs/brainstorms/2026-03-31-multi-book-runner-requirements.md`)

---

### 5. Thesis Invalidation Tripwires
**Description:** Add an `invalidation` block to the thesis JSON config: a set of explicit conditions that signal the thesis is structurally wrong (not just delayed). Example: `{"conditions": [{"nodeId": "hormuz", "state": "stable", "minDays": 30}, {"observable": "brent", "below": 85}]}`. When the propagation engine detects any invalidation condition met, emit a distinct snapshot field `"thesisStatus": "INVALIDATED"` alongside a reason. The push script escalates invalidated snapshots (force-push regardless of diff severity) and the Curator generates a high-priority alert.

**Rationale:** The system currently models "thesis progressing" excellently. It does not model "we were wrong about the causal structure." A thesis can silently zombie — nodes stuck at "approaching" for months, positions bleeding slowly, nobody making the explicit call to exit because the graph never formally disagrees. Invalidation tripwires operationalize the question every good trader must answer: "what would have to be true for me to be fundamentally wrong?" This is the adversarial complement to the cascade phase tracker. The `reversal` node type is a partial implementation — this makes it explicit and first-class.

**Downsides:** Requires thesis authors to write explicit invalidation conditions upfront, which is harder than writing entry conditions (it forces consideration of being wrong). Threshold values for invalidation may be hard to calibrate. False invalidations (thesis temporarily invalidated but recovers) need handling — possibly a re-validation confirmation step.

**Confidence:** 72%
**Complexity:** Medium
**Status:** Unexplored

---

## Rejection Summary

| # | Idea | Reason Rejected |
|---|------|-----------------|
| 1 | Persistent Watcher Daemon | Cron covers 95% of value; daemon ops overhead not justified for 2-person team on laptops |
| 2 | Polymarket Slug Cache | Three-pass matcher already handles it; cache adds stale-entry failure mode harder to debug than live-lookup failure |
| 4 | Cascade Phase Regression Alerting | Phase is manually set in JSON; regression requires deliberate human edit, which git diff already catches |
| 5 | Per-Node Staleness Signal | Data model already handles this — nodes either have live feeds (fetched together in one batch) or `"feed": "manual"` |
| 6 | Cross-Thesis Interference Detector | Two theses are deliberately non-overlapping; cross-thesis correlation is an economic opinion, not automatable |
| 7 | Dialectic Round-Trip: LLM → Journal | Requires second integration direction + NLP parsing of free text; problem already solved by Dialectic's own conversation history |
| 8 | Scenario Probability Drift Tracker | Probabilities are manually set; drift tracking duplicates git blame/log |
| 9 | Conviction Score Feedback | Inverts the trust model; LLM updating model probabilities undermines the epistemic foundation the graph is built on |
| 11 | Scenario Probability Ownership | Two users; who changed it is answerable in 5 seconds with git blame |
| 12 | Causal Path Explainer | Dan and Amo built the graph; they already know why nodes fire; for 16 nodes, graph tab shows it in 10 seconds |
| 14 | Temporal Coherence Check | This is a test, not a feature; belongs in test suite not the live system |
| 15 | Dialectic Conversation Mining | NLP-suggested graph nodes from LLM text create a feedback loop where the model's talking points become graph structure |
| 18 | Heartbeat Push | Explicitly anti-spec: "only deltas get pushed to Dialectic as alerts. No noise." |
| 19 | Topology-First Dialectic Integration | Premature optimization before the single-phase integration is even live |
| 20 | Pull Model | Requires tradingDesk to run as a server — a larger architectural inversion than the entire current integration |
| 21 | Thesis Memory Layer / Decision Archaeology | Too vague; journal + snapshots + Dialectic history already serve this purpose |
| 22 | Causal Chain Backtester | Thresholds are acknowledged as expert heuristics; backtesting against historical data produces false confidence in deliberately approximate values |
| 23 | Signal Velocity Tracker | Second-order feature; requires ring buffer (idea 1) first; build separately if needed |
| 24 | Outcome Attribution Pipeline | Post-trade review tool for a mid-thesis book; outcome attribution requires closed P&L which is out of scope |
| 25 | Asymmetric Information Surfacer | Just a formatted diff; diff-snapshots.py already produces this |
| 26 | Analog Library | Two high-quality analogs already hand-annotated in config; automated matching would degrade precision vs. curated entries |
| S1 | Velocity-Aware Ring Buffer | Compounds three unbuilt features; build ring buffer alone first |
| S2 | Topology-First + Causal Path Explainer | Combines two rejected ideas |
| S3 | Epistemic Integrity Monitor | Diverts attention from concrete implementation into vague "monitoring" abstraction |

---

## Session Log
- 2026-03-31: Initial ideation — 30 raw ideas generated (4 frames × 7-8), 3 cross-cutting syntheses added, 5 survivors after adversarial filter
- 2026-03-31: Brainstormed idea #4 (Multi-Book Runner) → requirements doc at `docs/brainstorms/2026-03-31-multi-book-runner-requirements.md`
