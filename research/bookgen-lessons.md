# bookgen.py Lessons -- What Carried Forward, What Didn't

Reference for understanding why the thesis graph engine (`thesisgraph.py`) exists and how it relates to the original commodity book generator.

## What bookgen.py does well (patterns kept)

- **Single-file HTML output** with all JS/CSS inlined -- zero hosting deps, works offline. Both generators preserve this.
- **JSON config as single source of truth** -- declarative data, generated presentation. The graph engine kept this 1:1.
- **Linear pipeline**: load -> validate -> transform -> template -> write. `thesisgraph.py` uses the same flow.
- **Thorough config validation** with separated errors/warnings and actionable messages. Graph engine copied the `validate_config() -> (errors, warnings)` pattern directly.
- **`__PLACEHOLDER__` template replacement** -- simple, dependency-free HTML assembly. Both generators use it.
- **Yahoo Finance fetch via allorigins proxy** -- server-side batching (groups of 8, retries, courtesy delays) reused in graph engine.
- **DEFAULTS object pattern** for localStorage state (generate from config, deep-clone on reset, JSON export/import).
- **No external Python deps** -- stdlib only. Project convention.

## What it doesn't do (limitations that motivated the graph engine)

- **Flat trigger model**: triggers are independent threshold checks with no causal relationships. Cannot express "A causes B causes C" -- each trigger is an island. The graph engine replaces this with a DAG where edges carry mechanisms, lags, and amplification.
- **No AND logic**: triggers are evaluated independently. Composite conditions (Brent > $115 AND rigs flat) require a new trigger type. The graph engine's confluence scoring (fan-in analysis) solves this naturally.
- **No propagation**: firing a trigger doesn't affect downstream triggers. The graph engine uses Kahn's topological sort to propagate state changes through the DAG.
- **No scenarios**: one fixed view of the world. No way to ask "what if Hormuz closes in May vs August?" The graph engine has scenario overrides with probability-weighted portfolio impact.
- **No cascade tracking**: no concept of crisis phases. The "WE ARE HERE" phase tracker was entirely new in the graph engine.
- **No snapshot export**: state lives only in browser localStorage. The graph engine's `--export-state` enables Dialectic integration and diff-based change detection.
- **JS_LOGIC is an opaque string constant** (~40KB of dense minified JS in a Python raw string). No syntax highlighting, no linting. This was the biggest maintainability problem. The graph engine improved this somewhat but the pattern persists.

## Migration: flat triggers -> DAG nodes

| bookgen concept | graph engine equivalent |
|---|---|
| `triggers[]` with `metricKey` + `threshold` | Node with `type: "price"` + threshold, connected by edges |
| `triggers[]` with `binaryKey` | Node with `type: "event"` + manual state |
| `isConstraint: true` | Node with `type: "constraint"` |
| `isReversal: true` | Node with `type: "reversal"` |
| `overlays[]` unlocked by `triggerIds` | Downstream nodes connected by edges from gate nodes |
| `instruments[]` per trigger | `instruments[]` in graph config, mapped to nodes via `nodeId` |
| `marketFields[]` (flat key-value inputs) | Market data attached to price-type nodes |
| `closesRequired` (consecutive close counter) | Not yet ported -- graph engine evaluates point-in-time only |
| `altMetric` (OR logic second threshold) | Multiple edges into a node (natural in DAG) |

## HTML generation patterns (what works, what to watch)

**Keep**: Template with `__PLACEHOLDER__` markers replaced by `str.replace()`. Simple, debuggable, no template engine dependency.

**Keep**: Tab-based single-page layout with `data-tab` attributes and CSS class toggling. Both generators use identical tab switching logic.

**Keep**: Full `renderAll()` re-render approach is fine for manual-interaction tools. Not viable for real-time streaming data.

**Watch**: Inlined JS/CSS in Python string constants remains the biggest maintenance burden. Extracting to separate `.js`/`.css` files read at generation time would enable proper tooling. Neither generator has done this yet.

**Watch**: No error boundaries in browser JS. If any render function throws, the entire dashboard goes blank with no user-facing message. Both generators share this gap.

**Watch**: Browser-side fetch doesn't batch (unlike server-side). Could hit URL length limits with 20+ symbols.
