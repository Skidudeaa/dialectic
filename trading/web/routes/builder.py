"""Thesis Builder CRUD routes — create, update, delete thesis books."""

import json
import logging
import os
import re
import threading
import uuid
from datetime import date
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from web.auth import get_current_user
from web.adapters import thesis as thesis_adapter

log = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent.parent
BOOKS_DIR = _ROOT / "books"
_BOUND_BOOK_CREATE_LOCK = threading.Lock()

router = APIRouter(
    prefix="/api/thesis/builder",
    tags=["builder"],
    dependencies=[Depends(get_current_user)],
)


def _sanitize_id(title: str) -> str:
    """Turn a human title into a safe filesystem ID."""
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:60] or f"thesis-{uuid.uuid4().hex[:8]}"


def find_book_for_dialectic_room(room_id: str) -> dict | None:
    """Return the one existing book bound to a Dialectic room, if any."""
    for path in sorted(BOOKS_DIR.glob("*.json")):
        config = json.loads(path.read_text())
        if config.get("meta", {}).get("dialecticRoomId") == room_id:
            return {"id": path.stem, "filename": path.name}
    return None
class BookMeta(BaseModel):
    title: str = ""
    claim: str = ""
    monthlyBudget: int = 5000
    asOf: str = Field(default_factory=lambda: date.today().isoformat())
    # WHY: a thesis created FROM Dialectic is born bound to its room — the
    # coordinator needs meta.dialecticRoomId to know where snapshots go.
    # Optional; the desk's own builder leaves it empty and update_book
    # preserves an existing binding over whatever a request carries.
    dialecticRoomId: str = ""
class NodeData(BaseModel):
    id: str
    label: str
    type: str = "event"
    phase: int = 1
    state: str = "monitoring"
    context: str = ""
    x: float = 0
    y: float = 0
    probability: float | None = None
    current: float | None = None
    feeds: list[dict] = Field(default_factory=list)
    thresholds: list[dict] = Field(default_factory=list)
    indicators: list[dict] = Field(default_factory=list)
    countdown: bool = False
    deadline: str | None = None
    irreversible: bool = False
    gatedBy: list[str] = Field(default_factory=list)
    logic: str | None = None
class EdgeData(BaseModel):
    source: str  # renamed from "from" to avoid Python keyword
    target: str  # renamed from "to"
    mechanism: str = ""
    lag: str = ""
    strength: float = 0.7
class InstrumentData(BaseModel):
    id: str  # ticker
    monthly: int = 0
    role: str = ""
    beta: float = 0.5
    ref: float = 0
    targetLow: float | None = None
    targetHigh: float | None = None
    stop: float | None = None
class ScenarioData(BaseModel):
    id: str
    name: str
    probability: float = 0.25
    notes: str = ""
    overrides: dict = Field(default_factory=dict)
    portfolioImpact: dict = Field(default_factory=dict)
class CascadePhase(BaseModel):
    key: str
    label: str
    status: str = "MONITORING"
    signposts: list[dict] = Field(default_factory=list)
class SaveBookRequest(BaseModel):
    """Full book payload from the builder."""
    meta: BookMeta
    nodes: list[NodeData]
    edges: list[EdgeData]
    instruments: Dict[str, Any] = Field(default_factory=dict)
    scenarios: list[ScenarioData] = Field(default_factory=list)
    cascadePhases: Dict[str, Any] = Field(default_factory=dict)
    rules: list[str] = Field(default_factory=list)
    # Builder layout data (persisted but not used by engine)
    _builderLayout: dict = {}


def _book_to_engine_format(req: SaveBookRequest, book_id: str) -> dict:
    """Convert builder format to the engine JSON format."""
    cfg: Dict[str, Any] = {
        "meta": {
            "title": req.meta.title,
            "claim": req.meta.claim,
            "monthlyBudget": req.meta.monthlyBudget,
            "asOf": req.meta.asOf,
            "version": "1.0.0",
            "type": "thesis-graph",
        },
        "nodes": [],
        "edges": [],
        "instruments": {},
        "scenarios": [],
        "cascadePhases": {},
        "rules": req.rules,
        "provenance": [],
    }
    if req.meta.dialecticRoomId:
        cfg["meta"]["dialecticRoomId"] = req.meta.dialecticRoomId

    for n in req.nodes:
        node: Dict[str, Any] = {
            "id": n.id,
            "label": n.label,
            "type": n.type,
            "phase": n.phase,
            "state": n.state,
        }
        if n.context:
            node["context"] = n.context
        if n.probability is not None:
            node["probability"] = n.probability
        if n.current is not None:
            node["current"] = n.current
        if n.feeds:
            node["feeds"] = n.feeds
        if n.thresholds:
            node["thresholds"] = n.thresholds
        if n.indicators:
            node["indicators"] = n.indicators
        if n.countdown:
            node["countdown"] = True
        if n.deadline:
            node["deadline"] = n.deadline
        if n.irreversible:
            node["irreversible"] = True
        if n.gatedBy:
            node["gatedBy"] = n.gatedBy
        if n.logic:
            node["logic"] = n.logic
        cfg["nodes"].append(node)
    for e in req.edges:
        edge: Dict[str, Any] = {
            "from": e.source,
            "to": e.target,
            "mechanism": e.mechanism,
            "lag": e.lag,
            "strength": e.strength,
        }
        cfg["edges"].append(edge)
    cfg["instruments"] = dict(req.instruments)
    for s in req.scenarios:
        cfg["scenarios"].append(s.model_dump())
    cfg["cascadePhases"] = dict(req.cascadePhases)
    return cfg
def _engine_to_builder_format(cfg: dict, book_id: str) -> dict:
    """Convert engine JSON to builder-friendly format with x/y positions.

    WHY the fallback stacks WITHIN the phase column: the old `i * 120`
    fallback used the global node index, so a 19-node unpositioned book
    rendered as a 2300px-tall diagonal — unreadable in every canvas that
    fit it. Column x by phase, row y by position within that phase, is the
    phase-column layout the fallback always meant. Persisted _builderX/Y
    still win untouched.
    """
    nodes = []
    per_phase_row: dict = {}
    for n in cfg.get("nodes", []):
        phase = n.get("phase", 1)
        row = per_phase_row.get(phase, 0)
        per_phase_row[phase] = row + 1
        node = {
            "id": n["id"],
            "label": n.get("label", n["id"]),
            "type": n.get("type", "event"),
            "phase": phase,
            "state": n.get("state", "monitoring"),
            "context": n.get("context", ""),
            "x": n.get("_builderX", (phase - 1) * 280 + 100),
            "y": n.get("_builderY", row * 120 + 60),
            "probability": n.get("probability"),
            "current": n.get("current"),
            "feeds": n.get("feeds", []),
            "thresholds": n.get("thresholds", []),
            "indicators": n.get("indicators", []),
            "countdown": n.get("countdown", False),
            "deadline": n.get("deadline"),
            "irreversible": n.get("irreversible", False),
            "gatedBy": n.get("gatedBy", []),
            "logic": n.get("logic"),
        }
        nodes.append(node)

    edges = []
    for e in cfg.get("edges", []):
        edges.append({
            "source": e["from"],
            "target": e["to"],
            "mechanism": e.get("mechanism", ""),
            "lag": e.get("lag", ""),
            "strength": e.get("strength", 0.7),
        })

    return {
        "id": book_id,
        "meta": {
            "title": cfg.get("meta", {}).get("title", ""),
            "claim": cfg.get("meta", {}).get("claim", ""),
            "monthlyBudget": cfg.get("meta", {}).get("monthlyBudget", 5000),
            "asOf": cfg.get("meta", {}).get("asOf", date.today().isoformat()),
            "dialecticRoomId": cfg.get("meta", {}).get("dialecticRoomId", ""),
        },
        "nodes": nodes,
        "edges": edges,
        "instruments": cfg.get("instruments", {}),
        "scenarios": cfg.get("scenarios", []),
        "cascadePhases": cfg.get("cascadePhases", {}),
        "rules": cfg.get("rules", []),
    }


@router.get("/books")
async def list_builder_books() -> list:
    """List all books on disk (not just *-graph.json) so the builder list
    page can show every book it can open — including ones the editor created
    that don't follow the canonical -graph.json suffix."""
    books: list[dict] = []
    if not BOOKS_DIR.exists():
        return books
    for path in sorted(BOOKS_DIR.glob("*.json")):
        try:
            with open(path) as f:
                cfg = json.load(f)
            meta = cfg.get("meta", {})
            books.append({
                "id": path.stem,
                "filename": path.name,
                "title": meta.get("title", path.stem),
                "claim": meta.get("claim", ""),
                "asOf": meta.get("asOf", ""),
                "monthlyBudget": meta.get("monthlyBudget", 0),
                "nodes": len(cfg.get("nodes", [])),
                "edges": len(cfg.get("edges", [])),
                "type": meta.get("type", "unknown"),
            })
        except (json.JSONDecodeError, OSError) as e:
            log.warning("Skipping unreadable book %s: %s", path.name, e)
    return books


@router.get("/books/{book_id}")
async def get_book_for_builder(book_id: str) -> dict:
    """Load a book in builder-friendly format."""
    try:
        thesis_adapter._validate_book_id(book_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    config_path = BOOKS_DIR / f"{book_id}.json"
    if not config_path.exists():
        raise HTTPException(status_code=404, detail=f"Book not found: {book_id}")
    with open(config_path) as f:
        cfg = json.load(f)
    return _engine_to_builder_format(cfg, book_id)
def _adopt_into_runtime(request: Request, book_id: str) -> None:
    """Hand the saved book to the live coordinator, when one is running.

    WHY: coordinator definitions are scanned once at startup, so without
    this a book saved while the desk runs gets no fetch cycles (and a
    Dialectic-born thesis never pushes its first snapshot) until a restart.
    Tolerant of a missing coordinator — tests and lifespan-less contexts
    have none; production always does.
    """
    coordinator = getattr(request.app.state, "coordinator", None)
    if coordinator is not None:
        coordinator.adopt_book(book_id)


@router.post("/books")
async def create_book(req: SaveBookRequest, request: Request) -> dict:
    """Create a new thesis book."""
    slug = _sanitize_id(req.meta.title)
    # WHY the -graph suffix for room-bound books: every shipping book is
    # *-graph.json, and both the dashboard list (adapters/thesis.list_books)
    # and the Dialectic room→book join glob exactly that pattern. A thesis
    # born from a Dialectic room must land inside the convention or the
    # deep-surface handoff cannot find it. Collision counters go BEFORE the
    # suffix so `ai-bubble-1-graph` still matches the glob.
    bound = bool(req.meta.dialecticRoomId)
    if bound and slug.endswith("-graph"):
        slug = slug[: -len("-graph")]

    def _candidate(n: int) -> str:
        stem = slug if n == 0 else f"{slug}-{n}"
        return f"{stem}-graph" if bound else stem

    def _create_new() -> dict:
        counter = 0
        book_id = _candidate(0)
        config_path = BOOKS_DIR / f"{book_id}.json"

        # Avoid overwriting
        while config_path.exists():
            counter += 1
            book_id = _candidate(counter)
            config_path = BOOKS_DIR / f"{book_id}.json"

        cfg = _book_to_engine_format(req, book_id)

        # Save builder positions into the config for round-tripping
        for node_data, cfg_node in zip(req.nodes, cfg["nodes"]):
            cfg_node["_builderX"] = node_data.x
            cfg_node["_builderY"] = node_data.y

        BOOKS_DIR.mkdir(parents=True, exist_ok=True)
        tmp = config_path.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(cfg, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(str(tmp), str(config_path))

        _adopt_into_runtime(request, book_id)
        log.info("Created book: %s", book_id)
        return {"id": book_id, "filename": f"{book_id}.json"}

    if not bound:
        return _create_new()

    # The scan, decision, and atomic rename are one critical section. This
    # service runs one application process; the room ID is the durable key.
    with _BOUND_BOOK_CREATE_LOCK:
        existing = find_book_for_dialectic_room(req.meta.dialecticRoomId)
        if existing is not None:
            # Re-adoption heals a crash after rename but before runtime wiring.
            _adopt_into_runtime(request, existing["id"])
            return existing
        return _create_new()


@router.put("/books/{book_id}")
async def update_book(book_id: str, req: SaveBookRequest, request: Request) -> dict:
    """Update an existing thesis book."""
    try:
        thesis_adapter._validate_book_id(book_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    config_path = BOOKS_DIR / f"{book_id}.json"
    if not config_path.exists():
        raise HTTPException(status_code=404, detail=f"Book not found: {book_id}")
    cfg = _book_to_engine_format(req, book_id)

    # Save builder positions
    for node_data, cfg_node in zip(req.nodes, cfg["nodes"]):
        cfg_node["_builderX"] = node_data.x
        cfg_node["_builderY"] = node_data.y

    with open(config_path) as f:
        original = json.load(f)

    # WHY: The builder only manages a subset of node fields. Engine-specific
    # fields (tvAlertBindings, derivedIndicators, closesRequired, conditions,
    # regimes, etc.) must survive a builder edit. Merge them from original.
    _BUILDER_NODE_KEYS = {
        "id", "label", "type", "phase", "state", "context",
        "probability", "current", "feeds", "thresholds", "indicators",
        "countdown", "deadline", "irreversible", "gatedBy", "logic",
        "_builderX", "_builderY",
    }
    orig_nodes_by_id = {n["id"]: n for n in original.get("nodes", [])}
    for cfg_node in cfg["nodes"]:
        orig_node = orig_nodes_by_id.get(cfg_node["id"], {})
        for key, value in orig_node.items():
            if key not in _BUILDER_NODE_KEYS and key not in cfg_node:
                cfg_node[key] = value

    # Preserve original edge fields the builder doesn't manage (e.g. amplification)
    _BUILDER_EDGE_KEYS = {"from", "to", "mechanism", "lag", "strength"}
    orig_edges_by_pair = {(e["from"], e["to"]): e for e in original.get("edges", [])}
    for cfg_edge in cfg["edges"]:
        orig_edge = orig_edges_by_pair.get((cfg_edge["from"], cfg_edge["to"]), {})
        for key, value in orig_edge.items():
            if key not in _BUILDER_EDGE_KEYS and key not in cfg_edge:
                cfg_edge[key] = value
    for key in ("dialecticRoomId", "dialecticRoomToken"):
        if key in original.get("meta", {}):
            cfg["meta"][key] = original["meta"][key]
    for key in ("fetchSymbols", "marketFields", "analogs", "provenance"):
        if key in original and key not in cfg:
            cfg[key] = original[key]
    tmp = config_path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(str(tmp), str(config_path))
    thesis_adapter.invalidate_cache(book_id)
    _adopt_into_runtime(request, book_id)
    log.info("Updated book: %s", book_id)
    return {"id": book_id, "filename": f"{book_id}.json"}
@router.delete("/books/{book_id}")
async def delete_book(book_id: str) -> dict:
    """Delete a thesis book."""
    try:
        thesis_adapter._validate_book_id(book_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    config_path = BOOKS_DIR / f"{book_id}.json"
    if not config_path.exists():
        raise HTTPException(status_code=404, detail=f"Book not found: {book_id}")

    config_path.unlink()
    thesis_adapter.invalidate_cache(book_id)

    log.info("Deleted book: %s", book_id)
    return {"deleted": book_id}
