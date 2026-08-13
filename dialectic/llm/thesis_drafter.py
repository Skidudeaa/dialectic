# llm/thesis_drafter.py — Claude drafts the causal DAG for a newborn thesis.
#
# ARCHITECTURE: the draft is a PROPOSAL, never a write. The endpoint that
# calls this returns the drafted nodes/edges to the human, who reviews them
# in the panel and taps Accept — and the Accept is an ordinary create-thesis
# call carrying the payload. Same trust shape as draft_prediction: the LLM
# proposes, the human tap is the write.
#
# WHY builder format (edges as source/target, not the engine's from/to):
# the accepted draft travels through tradingDesk's builder API
# (POST /api/thesis/builder/books), whose SaveBookRequest speaks builder
# format and converts to engine format itself. Emitting the same shape the
# canvas edits means a drafted book round-trips through the Builder with
# no translation anywhere on our side.

import json
import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)


class DraftError(Exception):
    """The model could not produce a valid draft after a retry."""


_ALLOWED_TYPES = {
    "event", "price", "indicator", "deadline",
    "gate", "constraint", "conditional", "reversal",
}

# WHY these caps: the five shipping books run 15–19 nodes. A draft is a
# starting skeleton the humans refine on the canvas, not a finished book —
# past ~16 nodes the review step stops being a review.
_MIN_NODES, _MAX_NODES = 4, 16
_MAX_EDGES = 30

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")

_PHASES = {
    1: "shock", 2: "transmission", 3: "amplification",
    4: "policyResponse", 5: "resolution",
}

DRAFT_SYSTEM = """You are the thesis architect for a macro trading desk. \
Given a thesis title and claim, you draft the causal DAG: the chain of \
observable states through which the shock transmits into markets.

Output STRICT JSON only — no markdown fences, no prose outside the JSON:

{
  "rationale": "2-3 sentences: the cascade's spine and the key gate",
  "nodes": [
    {
      "id": "kebab-case-id",
      "label": "Short Label",
      "type": "event|price|indicator|deadline|gate|constraint|conditional|reversal",
      "phase": 1,
      "context": "1-2 sentences: what this node observes and why it matters",
      "thresholds": [{"level": 4.75, "label": "GDP drag begins"}],
      "feeds": [{"source": "yahoo", "symbol": "BDRY", "label": "Baltic Dry"}]
    }
  ],
  "edges": [
    {
      "source": "upstream-id",
      "target": "downstream-id",
      "mechanism": "the specific causal channel, quantified when possible",
      "lag": "immediate|1 week|1-2 months|...",
      "strength": 0.85
    }
  ]
}

The vocabulary, learned from the desk's live books:
- phase 1 = shock (the triggering states), 2 = transmission (first-order
  pass-through), 3 = amplification (second-order feedback), 4 = policy
  response, 5 = resolution/reversal. Every cascade needs phases 1 and 2;
  include later phases only where the thesis genuinely reaches them.
- type "event" for discrete states (a closure, a default, an election),
  "price" for market prices with meaningful levels, "indicator" for macro
  series, "deadline" for calendar gates, "reversal" for the state that
  KILLS the thesis — always include exactly one reversal node: the desk's
  discipline is knowing what would prove the thesis wrong.
- A good mechanism is specific and quantified: "20% global seaborne oil
  disrupted", "crack spread transmission" — never "affects" or "impacts".
- thresholds carry {"level": number, "label": "what crossing it means"} on
  price/indicator nodes where a level is decision-relevant. Omit elsewhere.
- feeds: only where you are confident of the identifier — "yahoo" with a
  real ticker symbol, or "fred" with a real series id. Omit when unsure;
  the desk wires data by hand rather than trusting a guessed symbol.
- strength is 0.0-1.0 causal confidence. The graph must be acyclic.
- 6-12 nodes for a typical thesis. Do not invent current values, states,
  probabilities, or positions — every node starts unobserved.

Example fragment (from a live oil-shock book), showing the register:
{"id": "hormuz", "label": "Hormuz Closure", "type": "event", "phase": 1,
 "context": "Strait carries ~20% of seaborne oil; closure is the shock."}
{"id": "diesel", "label": "Diesel Stress", "type": "price", "phase": 2,
 "context": "Crack spread doubles on crude disruption; trucking cost shock.",
 "thresholds": [{"level": 4.75, "label": "GDP drag begins"},
                 {"level": 5.5, "label": "freight capitulation"}]}
{"source": "hormuz", "target": "diesel",
 "mechanism": "crack spread transmission", "lag": "1-2 weeks",
 "strength": 0.85}"""


def validate_draft(draft: Any) -> list[str]:
    """Every reason this draft cannot be accepted, or [] when it can.

    WHY a list rather than raise-on-first: the errors go back to the model
    verbatim as the retry prompt, and one pass with all defects beats a
    retry per defect.
    """
    errors: list[str] = []
    if not isinstance(draft, dict):
        return ["draft must be a JSON object"]

    nodes = draft.get("nodes")
    edges = draft.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return ["'nodes' and 'edges' must be lists"]

    if not _MIN_NODES <= len(nodes) <= _MAX_NODES:
        errors.append(
            f"node count {len(nodes)} outside {_MIN_NODES}-{_MAX_NODES}"
        )
    if len(edges) > _MAX_EDGES:
        errors.append(f"edge count {len(edges)} above {_MAX_EDGES}")

    ids: set[str] = set()
    for i, n in enumerate(nodes):
        if not isinstance(n, dict):
            errors.append(f"nodes[{i}] is not an object")
            continue
        nid = n.get("id")
        if not isinstance(nid, str) or not _ID_RE.match(nid):
            errors.append(f"nodes[{i}].id {nid!r} is not kebab-case")
            continue
        if nid in ids:
            errors.append(f"duplicate node id {nid!r}")
        ids.add(nid)
        if not (n.get("label") or "").strip():
            errors.append(f"node {nid!r} has no label")
        if n.get("type") not in _ALLOWED_TYPES:
            errors.append(f"node {nid!r} type {n.get('type')!r} not in "
                          f"{sorted(_ALLOWED_TYPES)}")
        if n.get("phase") not in _PHASES:
            errors.append(f"node {nid!r} phase {n.get('phase')!r} not 1-5")
        thresholds = n.get("thresholds", [])
        if not isinstance(thresholds, list) or any(
            not isinstance(t, dict) or not isinstance(t.get("level"), (int, float))
            for t in thresholds
        ):
            errors.append(f"node {nid!r} thresholds must be "
                          f"[{{level: number, label: str}}]")
        feeds = n.get("feeds", [])
        if not isinstance(feeds, list) or any(
            not isinstance(f, dict) or f.get("source") not in ("yahoo", "fred")
            for f in feeds
        ):
            errors.append(f"node {nid!r} feeds must be yahoo/fred entries "
                          f"(omit when unsure)")

    seen_pairs: set[tuple] = set()
    adjacency: dict[str, list[str]] = {nid: [] for nid in ids}
    indegree: dict[str, int] = {nid: 0 for nid in ids}
    for i, e in enumerate(edges):
        if not isinstance(e, dict):
            errors.append(f"edges[{i}] is not an object")
            continue
        src, tgt = e.get("source"), e.get("target")
        if src not in ids or tgt not in ids:
            errors.append(f"edges[{i}] references unknown node "
                          f"({src!r} -> {tgt!r})")
            continue
        if src == tgt:
            errors.append(f"edges[{i}] is a self-loop on {src!r}")
            continue
        if (src, tgt) in seen_pairs:
            errors.append(f"duplicate edge {src!r} -> {tgt!r}")
        seen_pairs.add((src, tgt))
        if not (e.get("mechanism") or "").strip():
            errors.append(f"edge {src!r} -> {tgt!r} has no mechanism")
        strength = e.get("strength")
        if not isinstance(strength, (int, float)) or not 0.0 <= strength <= 1.0:
            errors.append(f"edge {src!r} -> {tgt!r} strength "
                          f"{strength!r} not in 0..1")
        adjacency[src].append(tgt)
        indegree[tgt] += 1

    # Kahn's — the engine topologically sorts, so a cycle is fatal there.
    if not errors:
        queue = [nid for nid, d in indegree.items() if d == 0]
        visited = 0
        while queue:
            nid = queue.pop()
            visited += 1
            for nxt in adjacency[nid]:
                indegree[nxt] -= 1
                if indegree[nxt] == 0:
                    queue.append(nxt)
        if visited != len(ids):
            errors.append("the graph has a cycle — the engine requires a DAG")

    return errors


def _layout(nodes: list[dict]) -> None:
    """Phase-column positions, matching the Builder's own fallback layout."""
    rows: dict[int, int] = {}
    for n in nodes:
        phase = n.get("phase", 1)
        row = rows.get(phase, 0)
        rows[phase] = row + 1
        n["x"] = (phase - 1) * 280 + 100
        n["y"] = row * 120 + 60


def _sanitize(draft: dict) -> dict:
    """Strip everything a draft must not claim.

    WHY: a draft describes a structure, not an observation. state, current,
    probability and indicators are runtime facts the live pipeline earns —
    a model asserting them would put fiction into the room's first snapshot.
    """
    nodes = []
    for n in draft["nodes"]:
        nodes.append({
            "id": n["id"],
            "label": str(n.get("label", "")).strip(),
            "type": n.get("type", "event"),
            "phase": n.get("phase", 1),
            "state": "monitoring",
            "context": str(n.get("context", "")).strip(),
            "thresholds": n.get("thresholds", []) or [],
            "feeds": n.get("feeds", []) or [],
        })
    edges = []
    for e in draft["edges"]:
        edges.append({
            "source": e["source"],
            "target": e["target"],
            "mechanism": str(e.get("mechanism", "")).strip(),
            "lag": str(e.get("lag", "")).strip(),
            "strength": float(e.get("strength", 0.7)),
        })
    _layout(nodes)
    return {
        "nodes": nodes,
        "edges": edges,
        "rationale": str(draft.get("rationale", "")).strip(),
    }


def _parse_json(text: str) -> Optional[dict]:
    """The JSON object in the reply, fences and prose tolerated."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            return None
        try:
            parsed = json.loads(text[start:end + 1])
            return parsed if isinstance(parsed, dict) else None
        except ValueError:
            return None


async def draft_thesis_graph(
    title: str, claim: str, monthly_budget: int,
    model: str = "claude-sonnet-5",
) -> dict:
    """Draft {nodes, edges, rationale} for the thesis, or raise DraftError.

    One retry, fed the validator's full error list — a second failure means
    the human creates empty and draws by hand, which is where they started.
    """
    from .providers import get_provider, ProviderName, LLMRequest

    provider = get_provider(ProviderName.ANTHROPIC)
    user_prompt = (
        f"Thesis title: {title}\n"
        f"Thesis claim: {claim or '(none given — infer from the title)'}\n"
        f"Monthly budget: ${monthly_budget:,}\n\n"
        f"Draft the causal DAG."
    )
    messages = [{"role": "user", "content": user_prompt}]

    last_errors: list[str] = []
    for attempt in (1, 2):
        request = LLMRequest(
            messages=messages,
            system=DRAFT_SYSTEM,
            model=model,
            max_tokens=8192,
            temperature=0.6,
        )
        response = await provider.complete(request)
        parsed = _parse_json(response.content)
        if parsed is None:
            last_errors = ["reply was not parseable JSON"]
        else:
            last_errors = validate_draft(parsed)
            if not last_errors:
                logger.info(
                    "thesis draft ok (attempt %d): %d nodes, %d edges",
                    attempt, len(parsed["nodes"]), len(parsed["edges"]),
                )
                return _sanitize(parsed)

        logger.warning(
            "thesis draft attempt %d invalid: %s", attempt, last_errors[:5]
        )
        if attempt == 1:
            messages = messages + [
                {"role": "assistant", "content": response.content},
                {"role": "user", "content": (
                    "That draft failed validation:\n- "
                    + "\n- ".join(last_errors)
                    + "\n\nEmit the corrected STRICT JSON only."
                )},
            ]

    raise DraftError(
        "the model could not produce a valid cascade: "
        + "; ".join(last_errors[:3])
    )
