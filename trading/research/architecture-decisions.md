# Architecture Decisions

Distilled rationale behind key design choices in the tradingDesk engine. For implementation details, read the code.

---

## 1. Why a DAG (Not Bayesian Networks, Not Belief Propagation)

**Alternatives considered:**

- **pgmpy / Bayesian Networks**: Full conditional probability tables, belief propagation, structure learning. Rejected because our edge weights come from domain expertise, not learned from data. BNs force you to discretize continuous variables and define CPDs -- complexity without payoff when you already know the graph structure.
- **CausalNex (McKinsey)**: Subclasses NetworkX DiGraph, supports do-calculus interventions. Wrong abstraction -- it wants to learn structure from data. We already know "Hormuz closure causes oil supply loss." We need magnitude and timing, not causal discovery.
- **DoWhy (Microsoft)**: Answers "does X cause Y in this dataset?" We already know X causes Y. Not relevant.
- **Full probabilistic programming (PyMC, Stan)**: MCMC inference for uncertainty quantification. Overkill for a 16-node graph with expert-assigned weights.

**Why topological propagation wins:** Our problem is simpler than any of these frameworks assume. Walk the DAG in dependency order, apply edge weights and lag offsets. That is 20 lines of Python on top of Kahn's algorithm. The weights encode domain judgment ("Hormuz closure transmits 0.95x to oil supply loss"), not statistical estimates. Bayesian inference adds machinery we do not need.

**The key insight:** This is a structured notebook for expert judgment, not an autonomous prediction engine. The math enforces consistency and propagates your estimates -- it does not generate them.

---

## 2. Propagation Design

**Node state evaluation:** Each node has an observable indicator, a threshold, and a current value. Topological sort guarantees every node's predecessors are evaluated before it. State is ternary: fired (threshold breached), approaching (within range), stable.

**Edge strength semantics:** Weights (0.0-1.0) are transmission coefficients representing how much of an upstream shock passes through. They encode attenuation, not probability. "0.7 weight" means "70% of the upstream impact transmits downstream," capturing real-world dissipation (hedging, substitution, policy buffers).

**Lag modeling:** Each edge carries `lag_months`. When evaluating a time horizon, only edges with lag <= horizon contribute. This lets you run "what does the world look like in 1 month vs. 6 months" and watch the shock wavefront move through the graph. Inspired by VAR impulse response functions but without requiring time-series data.

**Confluence scoring rationale:** When multiple independent causal paths converge on the same node (fan-in), that is a stronger signal than a single path. Scored as weighted in-degree of active upstream paths. High confluence = high confidence that the downstream effect materializes, because multiple independent transmission channels are firing simultaneously.

---

## 3. Scenario Engine

**Override propagation:** A scenario is a set of node-state overrides (e.g., "force Hormuz to fired, force Brent to $155"). The engine re-runs topological propagation with overrides applied before evaluation. Downstream nodes recompute naturally -- no special scenario logic needed beyond "set these values, re-propagate."

**Portfolio impact calculation:** Each instrument maps to one or more graph nodes. Scenario impact = position size x estimated move for that scenario. The move estimates come from factor betas (how much XOP moves per $10 Brent move) assigned by domain judgment. Displayed as a waterfall chart: contribution of each position to net scenario P&L.

**Probability weighting:** Each scenario carries a probability (sourced from prediction markets, options-implied, or expert estimate). Portfolio expected value = sum of (scenario probability x scenario net impact). This is deliberately simple -- we chose weighted-average over full distributional analysis because (a) we have few scenarios (3-5), (b) tail correlations make distributional math unreliable for rare geopolitical events, and (c) directional correctness with rough magnitudes is the goal.

---

## 4. HTML Generation

**Why single-file:** The generated HTML is both the tool and the artifact. It captures the state of a thesis at a point in time. You can email it, archive it, open it offline, compare versions by diffing files. No server, no database, no deployment. TiddlyWiki proved this pattern scales to complex applications.

**Why Cytoscape.js:** After measuring actual bundle sizes:

| Library | Minified | Why not |
|---------|----------|---------|
| Cytoscape.js + dagre | 377 KB | -- (chosen) |
| vis-network | 686 KB | 2x size, physics simulation wrong for DAGs |
| Mermaid.js | 2.7 MB | Unacceptable for inline; renders to SVG, no runtime updates |
| d3-dag | ~45 KB | ESM-only, requires building everything from scratch |
| Pure SVG + dagre | 277 KB | Lose click/hover/zoom that Cytoscape provides free |

Cytoscape's dagre layout (Sugiyama-style hierarchical ranking) is purpose-built for DAGs. State-based styling via CSS-like selectors (`node.fired { background-color: red }`) maps directly to our trigger states. Programmatic data updates (`node.data('impact', 0.85)`) trigger re-render without manual DOM manipulation.

**Why inlined (not CDN):** Offline capability. The HTML must work without network access. A 450 KB self-contained file opens instantly and works on a plane.

---

## 5. Key Design Tradeoffs

**Zero external Python dependencies.** Sacrifices: no NetworkX (reimplemented topological sort), no pgmpy, no numpy. Gains: the tool runs on any machine with Python 3 -- no virtualenv, no pip install, no version conflicts. For a 16-node graph, stdlib is sufficient.

**Expert-assigned weights over learned weights.** Sacrifices: no automatic calibration from historical data, weights may be wrong. Gains: the system works with zero training data, handles novel scenarios (no historical Hormuz closure to learn from), and the weights are transparent and auditable. When a weight is wrong, you change one number in the JSON config.

**Static generation over live server.** Sacrifices: no real-time push updates, no multi-user collaboration (within the HTML itself). Gains: zero infrastructure, zero maintenance, archivable artifacts. Live price fetch in the browser bridges the freshness gap for the data that changes fastest.

**Flat JSON config over a database.** Sacrifices: no query language, no relational joins, no concurrent writes. Gains: version-controllable in git, human-readable, diffable, editable in any text editor. One JSON file per thesis keeps concerns separated.

**Rough factor betas over precise risk models.** Sacrifices: portfolio impact numbers are directionally correct but not precise. Gains: no regression infrastructure, no historical data pipeline, no model maintenance. For judgment-driven trading where you size manually, knowing "XOP goes up 30-50% if Brent hits $155" is sufficient -- the exact number does not change the decision.
