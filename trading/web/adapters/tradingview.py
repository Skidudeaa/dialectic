"""
Adapter for TradingView webhook mutation + binding CRUD.

WHY an adapter (not inline in the route): separating the mutation logic from
the HTTP plumbing lets us unit-test binding resolution, op/type enforcement,
and atomic writes without spinning up FastAPI or forging signatures. The
route handler becomes a thin layer that validates input, delegates here,
and broadcasts the result.

Responsibilities:
1. Load book config by ID with path-traversal defense
2. Look up the binding that matches the incoming alert
3. Enforce the op/type contract (price vs event vs reversal vs constraint)
4. Apply the mutation
5. Atomic tmp+rename write back to the book JSON
6. Invalidate the thesis-state cache so next GET /state reads fresh data
7. Append a single ENTRY to the tradingview-events.jsonl audit log
8. Return a structured result the route can turn into HTTP + WebSocket payload

This module is stdlib-only and never imports FastAPI.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from web.adapters import thesis as thesis_adapter

if TYPE_CHECKING:
    from web.persistence.repository import Repository

log = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent.parent
BOOKS_DIR = _ROOT / "books"

# WHY no local locks: the RuntimeCoordinator owns a single per-thesis
# asyncio.Lock shared by the scheduler tick, overrides, and webhooks. All
# TV webhook mutations are dispatched through coordinator.submit(thesis_id,
# "tv_webhook", ...), which acquires that lock before invoking
# apply_webhook_sync. The old _book_locks dict is removed.


# ── Path + ID validation ──────────────────────────────────────────────────

_BOOK_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def validate_book_id(book_id: str) -> None:
    """Reject book IDs that could traverse the filesystem or be malformed."""
    if not isinstance(book_id, str) or not _BOOK_ID_RE.fullmatch(book_id):
        raise ValueError(f"invalid book id: {book_id!r}")


def resolve_book_path(book_id: str) -> Path:
    """Resolve a book ID to its JSON path with startswith containment check.

    WHY startswith: even with the regex upfront, belt-and-braces — the
    resolved path MUST live under BOOKS_DIR. Any symlink or race that
    produced a path outside raises ValueError.
    """
    validate_book_id(book_id)
    candidate = (BOOKS_DIR / f"{book_id}.json").resolve()
    root = BOOKS_DIR.resolve()
    if not str(candidate).startswith(str(root) + os.sep) and candidate.parent != root:
        raise ValueError(f"book path escapes books dir: {candidate}")
    return candidate


def load_book(book_id: str) -> dict:
    """Load a book JSON with path-validated access. Raises FileNotFoundError
    when the book doesn't exist."""
    path = resolve_book_path(book_id)
    if not path.exists():
        raise FileNotFoundError(f"book not found: {book_id}")
    with open(path) as f:
        return json.load(f)


def write_book_atomic(book_id: str, cfg: dict) -> None:
    """Write a book JSON atomically via tmp+os.replace, fsync'd first.

    WHY fsync then os.replace: matches update_config_file() in thesisgraph.
    Prevents the book being truncated if the process crashes mid-write.
    """
    path = resolve_book_path(book_id)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(str(tmp), str(path))


# ── Binding resolution ────────────────────────────────────────────────────

@dataclass
class BindingMatch:
    """Resolved (node, binding) pair, with the list + index for rewrites."""
    node: dict
    binding: dict
    node_index: int
    binding_index: int


def find_binding(cfg: dict, binding_id: str) -> Optional[BindingMatch]:
    """Walk all nodes → tvAlertBindings looking for the matching bindingId.

    Returns None when not found. The caller turns that into an HTTP 404.
    """
    for ni, node in enumerate(cfg.get("nodes", [])):
        bindings = node.get("tvAlertBindings") or []
        for bi, binding in enumerate(bindings):
            if binding.get("bindingId") == binding_id:
                return BindingMatch(
                    node=node, binding=binding,
                    node_index=ni, binding_index=bi,
                )
    return None


# ── Op / type contract enforcement ────────────────────────────────────────

class MutationError(Exception):
    """Raised when an op cannot be applied (wrong type, value out of range).

    The message is intended to be operator-readable; the route maps it to
    HTTP 422 with the message in the detail.
    """


# (op, allowed node types) — mirrors docs/plans/.../tradingview-plan.md §5
_OP_TYPE_ALLOW: Dict[str, Tuple[str, ...]] = {
    "incrementClosesObserved": ("price", "reversal"),
    "setNodeState": ("event",),
    "setProbability": ("event",),
    "setCurrent": ("price", "reversal", "constraint"),
}

_ALLOWED_STATES = {"active", "resolved", "partial", "monitoring", "fired"}


def apply_op(
    node: dict,
    binding: dict,
    alert_value: Optional[float],
    *,
    repo: "Optional[Repository]" = None,
    thesis_id: Optional[str] = None,
) -> Any:
    """Apply the binding's declared op and return the new value/state.

    WHY repo + thesis_id kwargs: incrementClosesObserved now inserts a row
    into the close_observations SQLite table (instead of mutating the node's
    closesObserved field). The table is the canonical source; the coordinator
    reads the streak before propagate. These kwargs are required for
    incrementClosesObserved and ignored for the other three ops.

    Returns the new value of whichever field was mutated (or the new streak
    count for incrementClosesObserved). Raises MutationError on contract
    violations.
    """
    op = binding.get("op")
    if op not in _OP_TYPE_ALLOW:
        raise MutationError(f"unknown op: {op!r}")

    allowed_types = _OP_TYPE_ALLOW[op]
    if node.get("type") not in allowed_types:
        raise MutationError(
            f"op {op} not allowed on node type {node.get('type')!r}; "
            f"allowed: {', '.join(allowed_types)}"
        )

    if op == "incrementClosesObserved":
        if repo is None or thesis_id is None:
            raise MutationError(
                "incrementClosesObserved requires repo + thesis_id — "
                "the webhook route must supply them"
            )
        threshold_level = binding.get("thresholdLevel")
        if threshold_level is None:
            raise MutationError("binding missing thresholdLevel")
        threshold_key = str(threshold_level)
        # Pine Script fires on bar close — the alert's reception date is the
        # market_date for the close it represents. Alert body may carry the
        # explicit close value; if absent, fall back to the threshold level
        # itself (still qualifies by construction).
        market_date = date.today().isoformat()
        close_value = (
            float(alert_value) if alert_value is not None else float(threshold_level)
        )
        qualifies = close_value >= float(threshold_level)
        repo.insert_close_observation(
            thesis_id=thesis_id,
            node_id=node["id"],
            market_date=market_date,
            threshold_key=threshold_key,
            close_value=close_value,
            qualifies=qualifies,
            source="tv_webhook",
        )
        return repo.get_close_streak(
            thesis_id=thesis_id,
            node_id=node["id"],
            threshold_key=threshold_key,
        )

    if op == "setNodeState":
        target = binding.get("targetState")
        if target not in _ALLOWED_STATES:
            raise MutationError(
                f"disallowed target state: {target!r}; allowed: {sorted(_ALLOWED_STATES)}"
            )
        node["state"] = target
        return target

    if op == "setProbability":
        if alert_value is None or not isinstance(alert_value, (int, float)):
            raise MutationError("setProbability requires numeric value in alert body")
        v = float(alert_value)
        # WHY reject NaN/Inf explicitly: Pydantic with allow_inf_nan=True (the
        # v2 default) happily parses "NaN"/"Infinity" JSON literals. A NaN
        # probability poisons every downstream comparator since NaN > x and
        # NaN < x both return False — the node silently falls out of eval.
        if math.isnan(v) or math.isinf(v):
            raise MutationError(f"probability must be finite, got {alert_value!r}")
        if not 0.0 <= v <= 1.0:
            raise MutationError(f"probability out of [0.0, 1.0]: {v}")
        node["probability"] = round(v, 4)
        return node["probability"]

    if op == "setCurrent":
        if alert_value is None or not isinstance(alert_value, (int, float)):
            raise MutationError("setCurrent requires numeric value in alert body")
        v = float(alert_value)
        # WHY reject NaN/Inf explicitly: see setProbability above. NaN prices
        # break eval_node_state silently (NaN >= threshold is False for every
        # threshold), so a malicious or malformed alert could mute a node's
        # firing without leaving a visible error in the snapshot.
        if math.isnan(v) or math.isinf(v):
            raise MutationError(f"current must be finite, got {alert_value!r}")
        node["current"] = round(v, 4)
        return node["current"]

    # Unreachable — the first check rejected unknown ops.
    raise MutationError(f"op handler missing for {op}")  # pragma: no cover


# ── High-level mutation entry point ──────────────────────────────────────

@dataclass
class ApplyResult:
    """Outcome of apply_webhook — used by the route to build HTTP + WS."""
    book_id: str
    node_id: str
    binding_id: str
    op: str
    new_value: Any
    prior_states: Dict[str, str]
    new_states: Dict[str, str]

    def state_changed(self) -> bool:
        """True when any node state transitioned as a result of this op."""
        return self.prior_states != self.new_states

    def changed_node_ids(self) -> List[str]:
        """The subset of nodeIds whose state actually changed."""
        return sorted(
            nid for nid, s in self.new_states.items()
            if self.prior_states.get(nid) != s
        )


def apply_webhook_sync(
    thesis_id: str,
    binding_id: str,
    alert_value: Optional[float],
    repo: "Repository",
) -> ApplyResult:
    """Apply one validated Pine alert — synchronous, already under the lock.

    WHY synchronous: this is the mechanical half of the webhook flow —
    load_book, find_binding, apply_op, persist, propagate. The
    RuntimeCoordinator acquires the per-thesis lock in `submit()` and
    then calls this via `asyncio.to_thread`, keeping the event loop free
    while the blocking file I/O runs.

    WHY thesis_id == book_id: the coordinator keys theses by `Path.stem`
    which matches the book_id used by the TV webhook route. We accept
    thesis_id as the parameter name to make the coordinator boundary
    obvious in callers' code.
    """
    cfg = load_book(thesis_id)

    match = find_binding(cfg, binding_id)
    if match is None:
        raise LookupError(f"unknown bindingId: {binding_id}")

    # Capture prior states BEFORE mutation so we can report transitions.
    # Patch closesObserved from the table first — the engine reads this
    # field during propagate but it is no longer the persistent source.
    _patch_closes_from_table(cfg, repo, thesis_id)
    prior_states = _propagate_states(cfg)

    new_value = apply_op(
        match.node, match.binding, alert_value,
        repo=repo, thesis_id=thesis_id,
    )

    # Stamp audit fields on the binding itself for operator visibility.
    match.binding["fireCount"] = int(match.binding.get("fireCount", 0) or 0) + 1
    from datetime import datetime, timezone
    match.binding["lastFiredAt"] = datetime.now(timezone.utc).isoformat()

    # Persist the updated book. closesObserved is deliberately NOT a
    # persistent field — the close_observations table is its source.
    write_book_atomic(thesis_id, cfg)

    # Invalidate the thesis-state cache so the next GET reads fresh.
    thesis_adapter.invalidate_cache(thesis_id)

    # Recompute states from the post-insert table.
    _patch_closes_from_table(cfg, repo, thesis_id)
    new_states = _propagate_states(cfg)

    return ApplyResult(
        book_id=thesis_id,
        node_id=match.node["id"],
        binding_id=binding_id,
        op=match.binding["op"],
        new_value=new_value,
        prior_states=prior_states,
        new_states=new_states,
    )


def _patch_closes_from_table(
    cfg: dict, repo: "Repository", thesis_id: str,
) -> None:
    """Patch node.closesObserved in-memory from the close_observations table.

    Mirrors RuntimeCoordinator._patch_closes_observed. For each price/reversal
    node with a closesRequired threshold, finds the highest threshold where
    current >= level, queries the streak for that threshold_key, and writes
    the count onto the node. This keeps the webhook-local propagate() in
    agreement with the coordinator's cycle propagate().
    """
    for node in cfg.get("nodes", []):
        if node.get("type") not in ("price", "reversal"):
            continue
        thresholds = node.get("thresholds") or []
        thresholds_with_closes = [
            th for th in thresholds
            if isinstance(th, dict) and th.get("closesRequired") and th.get("level") is not None
        ]
        if not thresholds_with_closes:
            continue
        current = node.get("current")
        if current is None:
            node["closesObserved"] = 0
            continue
        for th in sorted(thresholds_with_closes,
                         key=lambda t: t["level"], reverse=True):
            if current >= th["level"]:
                node["closesObserved"] = int(repo.get_close_streak(
                    thesis_id=thesis_id,
                    node_id=node["id"],
                    threshold_key=str(th["level"]),
                ))
                break
        else:
            node["closesObserved"] = 0


def _propagate_states(cfg: dict) -> Dict[str, str]:
    """Run thesisgraph.propagate() on an in-memory cfg, returning the states dict.

    WHY lazy import: thesisgraph is on sys.path only after web.main sets it
    up. Importing at module level can race with the main.py initialization
    when tests import this adapter before the app starts.
    """
    from tools.thesis_graph import thesisgraph  # type: ignore[import-untyped]
    return thesisgraph.propagate(cfg)


# ── Binding CRUD (JWT-gated routes call into this) ────────────────────────

def list_bindings(book_id: str) -> List[dict]:
    """Return all tvAlertBindings across all nodes in the book, flattened."""
    cfg = load_book(book_id)
    result: List[dict] = []
    for node in cfg.get("nodes", []):
        for b in node.get("tvAlertBindings") or []:
            entry = dict(b)
            entry.setdefault("nodeId", node.get("id"))
            result.append(entry)
    return result


def create_binding(book_id: str, binding: dict) -> dict:
    """Insert a new binding onto the target node. Validates uniqueness and
    op/type compatibility before writing."""
    cfg = load_book(book_id)

    # Uniqueness check — bindingId must be unique across the book
    for n in cfg.get("nodes", []):
        for existing in n.get("tvAlertBindings") or []:
            if existing.get("bindingId") == binding["bindingId"]:
                raise ValueError(f"bindingId already exists: {binding['bindingId']}")

    # Find target node
    target_node = None
    for n in cfg.get("nodes", []):
        if n.get("id") == binding["nodeId"]:
            target_node = n
            break
    if target_node is None:
        raise LookupError(f"nodeId not found: {binding['nodeId']}")

    # Op/type precheck — fail now, not at first alert fire.
    op = binding["op"]
    if op not in _OP_TYPE_ALLOW:
        raise ValueError(f"unknown op: {op}")
    if target_node.get("type") not in _OP_TYPE_ALLOW[op]:
        raise ValueError(
            f"op {op} not allowed on node type {target_node.get('type')!r}"
        )
    if op == "setNodeState":
        if binding.get("targetState") not in _ALLOWED_STATES:
            raise ValueError(
                f"setNodeState requires valid targetState, got {binding.get('targetState')!r}"
            )
    if op == "incrementClosesObserved":
        # thresholdLevel should be set so the operator sees what the counter tracks
        if binding.get("thresholdLevel") is None:
            raise ValueError("incrementClosesObserved requires thresholdLevel")

    # Normalise the stored record — initialize fireCount/lastFiredAt
    stored = dict(binding)
    stored.setdefault("fireCount", 0)
    stored.setdefault("lastFiredAt", None)
    stored.setdefault("description", "")

    target_node.setdefault("tvAlertBindings", []).append(stored)
    write_book_atomic(book_id, cfg)
    thesis_adapter.invalidate_cache(book_id)
    return stored


def delete_binding(book_id: str, binding_id: str) -> bool:
    """Remove a binding by bindingId. Returns True on success, False if missing."""
    cfg = load_book(book_id)
    removed = False
    for n in cfg.get("nodes", []):
        bindings = n.get("tvAlertBindings") or []
        new_bindings = [b for b in bindings if b.get("bindingId") != binding_id]
        if len(new_bindings) != len(bindings):
            n["tvAlertBindings"] = new_bindings
            removed = True
    if not removed:
        return False
    write_book_atomic(book_id, cfg)
    thesis_adapter.invalidate_cache(book_id)
    return True


# ── Status + event feed (read-only surfaces) ─────────────────────────────

def get_tv_indicators(book_id: str) -> Dict[str, dict]:
    """Return every node's tvIndicators dict (if any), keyed by nodeId.

    Used by the frontend TradingViewPanel and inline ThesisViewer badges.
    Reads from the live book JSON — does NOT run propagate; these are
    non-causal overlays and don't depend on state transitions.
    """
    cfg = load_book(book_id)
    out: Dict[str, dict] = {}
    for node in cfg.get("nodes", []):
        tv = node.get("tvIndicators")
        if isinstance(tv, dict) and tv:
            out[node["id"]] = dict(tv)
    return out


