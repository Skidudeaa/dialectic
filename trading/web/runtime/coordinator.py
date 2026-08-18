"""
RuntimeCoordinator — central mutation authority for the trading desk.

WHY: The v1 web layer scattered fetch, diff, persistence, WS broadcast,
and external push across routes and adapters with no central coordinator.
One stalled external dependency could silently degrade the whole desk.

The coordinator serializes all mutations under per-thesis asyncio.Lock,
produces deterministic snapshots with revision numbers, emits durable
events, and fans out WebSocket deltas after DB commit.

ARCHITECTURE: Routes submit mutations via coordinator.submit(). The
scheduler tick loop is just another mutation source. All paths acquire
the same per-thesis lock, preventing concurrent writes.
"""

import asyncio
import copy
import hashlib
import json
import logging
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from tools.bridge.room_tokens import resolve_room_token  # type: ignore[import-untyped]
from tools.thesis_graph import thesisgraph  # type: ignore[import-untyped]

from web.observability import thesis_context
from web.persistence.repository import Repository
from web.runtime.claim_resolver import ClaimResolver
from web.runtime.live_bus import get_live_bus
from web.runtime.slow_feeds import SlowFeedRefresher
from web.schemas.snapshots import snapshot_from_export

log = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent.parent
BOOKS_DIR = _ROOT / "books"


# WHY: Module-level revision cache so adjacent modules (web/routes/llm.py,
# web/routes/v1/agent.py) can ask "what revision is the desk currently on?"
# without holding a coordinator reference. Populated on every successful
# commit in _run_cycle_inner — see the _latest_revisions[thesis_id] = new_rev
# write below. Reads are lock-free (a stale-by-one int read is harmless;
# the consumer just stamps the call log with the prior revision).
_latest_revisions: Dict[str, int] = {}


def get_latest_revision(thesis_id: str) -> Optional[int]:
    """Return the most recently committed revision for a thesis, or None.

    WHY: Single import target for non-coordinator modules (e.g. the LLM
    agent-call ring buffer in web/routes/llm.py) that need to stamp every
    outbound LLM call with the snapshot revision the agent was reasoning
    against. Returns None when no commit has happened yet so callers can
    distinguish "uninitialized" from "revision 0".
    """
    return _latest_revisions.get(thesis_id)


class ScenarioEvaluationError(Exception):
    """Raised by evaluate_scenario() with a structured reason code.

    WHY: The route translates reason → HTTP status (404 for not-found kinds),
    and tests assert on the reason rather than the human message.
    """

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class RuntimeCoordinator:
    """Central mutation authority — owns thesis locks, scheduling, and snapshot commits.

    WHY: Every state-changing path (scheduler tick, on-demand fetch, TV webhook,
    manual override, config reload) goes through this coordinator under per-thesis
    locks. Routes are read-mostly; writes are submitted via submit().
    """

    def __init__(
        self,
        repo: Repository,
        ws_manager: Any,
        tick_interval: float = 300.0,
        slow_feeds: Optional[SlowFeedRefresher] = None,
    ) -> None:
        self._repo = repo
        self._ws = ws_manager
        self._tick_interval = tick_interval

        # Per-source TTL cache over the slow feeds (treasury, gdelt, fred,
        # eia, econ-calendar). Coordinator-lifetime because the cfg is
        # deep-copied every tick and cannot remember its own last pull.
        self._slow_feeds = slow_feeds if slow_feeds is not None else SlowFeedRefresher()

        # Deterministic auto-resolution of spec-carrying claims — runs at the
        # tail of every tick sweep, after all thesis locks are released.
        self._claim_resolver = ClaimResolver(repo, ws_manager)

        # Immutable thesis definitions, loaded once at startup
        self._definitions: Dict[str, dict] = {}
        self._definition_hashes: Dict[str, str] = {}

        # Per-thesis asyncio locks — single lock shared by all mutation paths
        self._locks: Dict[str, asyncio.Lock] = {}

        # Background tasks
        self._tasks: List[asyncio.Task] = []
        self._running = False

        # Monotonic revision per thesis (starts from DB state)
        self._revisions: Dict[str, int] = {}

        # Latest evaluated snapshot per thesis (in-memory for fast reads)
        self._latest_snapshots: Dict[str, dict] = {}

        # Track first tick completion for readiness probe
        self._first_tick_done = False

        # Monotonic-clock timestamp of the last successful Dialectic push per
        # thesis. WHY monotonic: this only ever feeds an elapsed-time compare
        # for the hourly heartbeat, and a wall-clock step (NTP, DST) must not
        # be able to suppress a push for an hour or fire a burst of them.
        self._last_dialectic_push: Dict[str, float] = {}

    # ════════════════════════════════════════════════════════════════
    # LIFECYCLE
    # ════════════════════════════════════════════════════════════════

    async def start(self) -> None:
        """Load definitions, hydrate state from DB, start scheduler."""
        self._load_definitions()
        self._hydrate_from_db()
        self._running = True
        self._tasks.append(asyncio.create_task(self._tick_loop()))
        log.info(
            "Coordinator started — %d theses, tick=%ds",
            len(self._definitions), int(self._tick_interval),
        )

    async def stop(self) -> None:
        """Cancel background tasks and wait for cleanup."""
        self._running = False
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        # Release the shared push client's connection pool.
        try:
            from web.runtime.dialectic_push import aclose_client
            await aclose_client()
        except Exception:  # pragma: no cover — shutdown must never raise
            log.debug("dialectic push client close failed", exc_info=True)
        log.info("Coordinator stopped")

    @property
    def is_ready(self) -> bool:
        """True when coordinator is initialized and has completed first tick."""
        return self._running and self._first_tick_done

    @property
    def definitions(self) -> Dict[str, dict]:
        """Read-only access to loaded thesis definitions."""
        return self._definitions

    @property
    def definition_hashes(self) -> Dict[str, str]:
        return self._definition_hashes

    # ════════════════════════════════════════════════════════════════
    # SUBMIT — public API for routes
    # ════════════════════════════════════════════════════════════════

    async def submit(
        self,
        thesis_id: str,
        op: str,
        payload: Optional[dict] = None,
        timeout: float = 10.0,
    ) -> Any:
        """Submit a mutation and await its result under the thesis lock.

        WHY: Routes call this instead of touching state directly. The
        coordinator serializes execution under the per-thesis lock.

        TRADEOFF: 10s default timeout prevents TV webhooks from blocking
        indefinitely during long fetch cycles. Returns TimeoutError on timeout.
        """
        if thesis_id not in self._definitions:
            raise ValueError(f"Unknown thesis: {thesis_id}")

        lock = self._get_lock(thesis_id)

        try:
            async with asyncio.timeout(timeout):
                async with lock:
                    return await self._execute(thesis_id, op, payload or {})
        except asyncio.TimeoutError:
            log.warning("submit(%s, %s) timed out after %.1fs", thesis_id, op, timeout)
            raise

    # ════════════════════════════════════════════════════════════════
    # READ — no lock needed (reads committed snapshots)
    # ════════════════════════════════════════════════════════════════

    def get_latest_snapshot(self, thesis_id: str) -> Optional[dict]:
        """Return the latest committed snapshot for a thesis.

        WHY: Reads from the in-memory cache (populated on startup from DB
        and updated after each commit). No lock needed — snapshots are
        replaced atomically via dict assignment.
        """
        return self._latest_snapshots.get(thesis_id)

    def get_revision(self, thesis_id: str) -> int:
        return self._revisions.get(thesis_id, 0)

    def get_thesis_ids(self) -> List[str]:
        return list(self._definitions.keys())

    def evaluate_scenario(
        self,
        thesis_id: str,
        scenario_id: str,
        against_revision: Optional[int] = None,
    ) -> dict:
        """Evaluate a scenario against a specific committed revision — read-only.

        WHY: The scenario tab on the desk needs to answer "what would happen if
        scenario X fired right now?" without touching live state. Because the
        underlying engine is deterministic (inputs → propagate → states), the
        result is fully reproducible: same revision + same definition always
        yields the same answer.

        TRADEOFF: Acquires NO coordinator lock and performs NO writes. A
        scenario request running concurrently with a tick sees whatever
        snapshot is committed at that moment; it never blocks or delays a
        mutation. Returning a stale-by-one-revision result is acceptable
        because the response carries baseRevision for the client.

        Raises ScenarioEvaluationError with reason codes:
            - "thesis_not_found": thesis_id not in loaded definitions
            - "scenario_not_found": scenario_id not in cfg.scenarios
            - "revision_not_found": against_revision specified but no snapshot
        """
        if thesis_id not in self._definitions:
            raise ScenarioEvaluationError("thesis_not_found")

        cfg = self._definitions[thesis_id]

        # Locate the scenario in the definition
        scenario = None
        for s in cfg.get("scenarios", []) or []:
            if isinstance(s, dict) and s.get("id") == scenario_id:
                scenario = s
                break
        if scenario is None:
            raise ScenarioEvaluationError("scenario_not_found")

        # Resolve the base snapshot + revision
        if against_revision is None:
            base_snap = self._latest_snapshots.get(thesis_id)
            base_revision = self._revisions.get(thesis_id, 0)
            provider_values = self._repo.get_latest_provider_values(thesis_id)
        else:
            base_snap = self._repo.get_snapshot_by_revision(thesis_id, against_revision)
            if base_snap is None:
                raise ScenarioEvaluationError("revision_not_found")
            base_revision = against_revision
            provider_values = self._repo.get_provider_values_for_revision(
                thesis_id, against_revision
            )

        base_states = (base_snap or {}).get("nodeStates", {}) or {}

        # Deep-copy the immutable definition, then hydrate the current/probability
        # values that were in effect at the target revision so propagate() sees
        # the same inputs the base snapshot did.
        effective = copy.deepcopy(cfg)
        if provider_values:
            node_map = {n["id"]: n for n in effective.get("nodes", [])}
            for key, val in provider_values.items():
                if key.endswith("_prob"):
                    nid = key[:-5]
                    if nid in node_map:
                        node_map[nid]["probability"] = val
                elif key in node_map:
                    node_map[key]["current"] = val

        # Run the engine's scenario evaluator. Deterministic; no I/O.
        new_states, impact = thesisgraph.eval_scenario(
            effective, scenario, base_states if base_states else None
        )

        # Diff nodes whose state changed relative to the base snapshot
        changed_nodes: Dict[str, Dict[str, str]] = {}
        for nid, new_state in new_states.items():
            old_state = base_states.get(nid, "stable")
            if new_state != old_state:
                changed_nodes[nid] = {"old": old_state, "new": new_state}

        # Human-readable summary
        probability = float(scenario.get("probability", 0) or 0)
        label = scenario.get("label") or scenario.get("name") or scenario_id
        if changed_nodes:
            explanation = (
                f"{len(changed_nodes)} node(s) change state under '{label}' "
                f"(probability {probability:.0%})."
            )
        else:
            explanation = (
                f"No node states change under '{label}' at this revision."
            )

        return {
            "baseRevision": base_revision if base_revision else None,
            "scenarioId": scenario_id,
            "label": label,
            "probability": probability,
            "changedNodes": changed_nodes,
            "portfolioImpact": impact,
            "explanation": explanation,
        }

    # ════════════════════════════════════════════════════════════════
    # INTERNALS — definition loading
    # ════════════════════════════════════════════════════════════════

    def _load_definitions(self) -> None:
        """Load all thesis-graph configs from books/ and compute hashes."""
        if not BOOKS_DIR.exists():
            log.warning("Books directory not found: %s", BOOKS_DIR)
            return

        # WHY *.json (not just *-graph.json): the shipping books all follow
        # the -graph.json suffix, but the TV webhook accepts any `book_id`
        # matching the book filename stem (see web/models.py TVWebhookAlert
        # pattern). Widening the glob keeps the coordinator and the webhook
        # in agreement. Non-thesis files get rejected by load_config.
        for path in sorted(BOOKS_DIR.glob("*.json")):
            try:
                # WHY not thesisgraph.load_config: it sys.exit()s on a
                # corrupt file, which `except Exception` cannot catch — one
                # bad book must not kill service boot (see adopt_book).
                with open(path) as f:
                    cfg = json.load(f)
                if not isinstance(cfg, dict) or "nodes" not in cfg:
                    continue  # Not a thesis file
                thesis_id = path.stem  # e.g., "iran-hormuz-graph"
                self._definitions[thesis_id] = cfg
                self._definition_hashes[thesis_id] = self._compute_hash(cfg)
                log.info("Loaded thesis: %s (%d nodes, %d edges)",
                         thesis_id,
                         len(cfg.get("nodes", [])),
                         len(cfg.get("edges", [])))
            except Exception:
                log.exception("Failed to load %s", path.name)

    def adopt_book(self, thesis_id: str) -> bool:
        """Load (or reload) one book from disk into the live cycle set.

        WHY: definitions are scanned once at startup, so a book created or
        edited through the builder while the desk runs would otherwise get
        no fetch cycles — and a thesis created FROM Dialectic would never
        push its first snapshot until someone restarted the service. The
        tick loop iterates the definitions dict afresh every tick, so a
        plain assignment here is picked up on the next tick; a cycle
        already in flight keeps the cfg it captured, which is the same
        deal a restart-time edit always had.

        Returns True when the book was adopted, False when the file is
        missing or not a thesis config — callers treat that as "nothing to
        run", not an error, mirroring _load_definitions' tolerance.
        """
        path = BOOKS_DIR / f"{thesis_id}.json"
        # WHY not thesisgraph.load_config: that is a CLI helper that
        # sys.exit()s on a missing or corrupt file — an escape no `except
        # Exception` catches, and a web process must not die for one book.
        try:
            with open(path) as f:
                cfg = json.load(f)
        except (OSError, ValueError):
            log.warning("adopt_book: cannot read %s", path.name)
            return False
        if not isinstance(cfg, dict) or "nodes" not in cfg:
            return False
        self._definitions[thesis_id] = cfg
        self._definition_hashes[thesis_id] = self._compute_hash(cfg)
        log.info("Adopted thesis at runtime: %s (%d nodes, %d edges)",
                 thesis_id, len(cfg.get("nodes", [])), len(cfg.get("edges", [])))
        # WHY the immediate cycle: a newly adopted book has no snapshot, and
        # the human who just created it is looking at an empty panel — the
        # tick interval (300s) of blankness reads as failure. Only the
        # no-snapshot case gets it; builder re-saves of a living book stay
        # on the tick, so a canvas edit-save loop cannot hammer the fetch
        # path. No running loop (sync tests, scripts) means no rush either.
        if thesis_id not in self._latest_snapshots:
            try:
                asyncio.get_running_loop().create_task(
                    self._run_adopted_cycle(thesis_id)
                )
            except RuntimeError:
                pass
        return True

    async def _run_adopted_cycle(self, thesis_id: str) -> None:
        """First cycle for a just-adopted book, under the tick's own lock."""
        lock = self._get_lock(thesis_id)
        if lock.locked():
            return
        async with lock:
            try:
                await self._run_cycle(thesis_id)
            except Exception:
                log.exception("adoption cycle failed for %s", thesis_id)

    def _hydrate_from_db(self) -> None:
        """Restore revisions and latest snapshots from SQLite on startup.

        WHY: On coordinator restart, the latest committed snapshot and
        revision are in SQLite. Provider values from the most recent
        fetch_run hydrate the effective config so the first snapshot
        uses real prices, not stale book defaults.
        """
        for thesis_id in self._definitions:
            rev = self._repo.get_latest_revision(thesis_id)
            self._revisions[thesis_id] = rev
            snap = self._repo.get_latest_snapshot(thesis_id)
            if snap:
                self._latest_snapshots[thesis_id] = snap
                log.info("Hydrated %s at revision %d", thesis_id, rev)

    @staticmethod
    def _compute_hash(cfg: dict) -> str:
        """SHA-256 of canonical JSON for definition change detection."""
        canonical = json.dumps(cfg, sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()[:16]

    def _get_lock(self, thesis_id: str) -> asyncio.Lock:
        if thesis_id not in self._locks:
            self._locks[thesis_id] = asyncio.Lock()
        return self._locks[thesis_id]

    # ════════════════════════════════════════════════════════════════
    # INTERNALS — tick loop
    # ════════════════════════════════════════════════════════════════

    async def _tick_loop(self) -> None:
        """Periodic fetch/evaluate cycle for all theses.

        WHY: Runs every tick_interval seconds. If a thesis lock is held
        (e.g., by an in-progress webhook mutation), that thesis is skipped
        for this tick. One thesis failing doesn't stop others.
        """
        # WHY: Run first tick immediately on startup, then wait interval.
        await self._run_all_ticks()
        self._first_tick_done = True

        while self._running:
            try:
                await asyncio.sleep(self._tick_interval)
                if not self._running:
                    break
                await self._run_all_ticks()
            except asyncio.CancelledError:
                break
            except Exception:
                log.exception("Tick loop error")

    async def _run_all_ticks(self) -> None:
        """Run one tick cycle for all theses."""
        for thesis_id in list(self._definitions.keys()):
            lock = self._get_lock(thesis_id)
            # WHY: Skip if lock is held — cycle-already-running guard
            if lock.locked():
                log.debug("Tick skipped for %s — lock held", thesis_id)
                continue
            async with lock:
                try:
                    await self._run_cycle(thesis_id)
                except Exception:
                    log.exception("Tick cycle failed for %s", thesis_id)

        # Claim auto-resolution rides the tail of the sweep — after every
        # thesis lock is released, since it holds none. WHY wrapped despite
        # run_once's own guards: mirrors the slow_feeds belt — a resolver
        # fault must never be able to break the snapshot cycle cadence.
        try:
            await self._claim_resolver.run_once()
        except Exception:  # noqa: BLE001
            log.warning("claim resolution failed", exc_info=True)

    async def _run_cycle(self, thesis_id: str) -> dict:
        """Full fetch → evaluate → snapshot → commit → broadcast cycle.

        WHY: This is the core evaluation pipeline. It runs under the
        per-thesis lock, so no concurrent mutations can interleave.

        Returns the committed snapshot dict.
        """
        t0 = time.monotonic()
        cfg = self._definitions[thesis_id]
        # v2 Unit 14: push thesisId (and runId once we have it) into the
        # contextvars so every log line emitted downstream is tagged.
        with thesis_context(thesis_id):
            return await self._run_cycle_inner(thesis_id, cfg, t0)

    async def _run_cycle_inner(self, thesis_id: str, cfg: dict, t0: float) -> dict:

        # 1. Deep-copy the immutable definition
        effective = copy.deepcopy(cfg)

        # 2. Fetch providers (blocking I/O in thread pool)
        run_id = self._repo.insert_fetch_run(thesis_id)
        provider_values: Dict[str, Any] = {}
        try:
            await asyncio.to_thread(thesisgraph.fetch_prices, effective)
            await asyncio.to_thread(thesisgraph.fetch_polymarket, effective)
            # Derived indicators + close-observation ingest (best-effort)
            try:
                await asyncio.to_thread(thesisgraph.fetch_ohlcv_for_derived, effective)
                await asyncio.to_thread(thesisgraph.compute_derived_indicators, effective)
                await asyncio.to_thread(
                    self._persist_close_events, thesis_id, effective
                )
            except Exception as e:
                log.warning("derived_indicators failed for %s: %s", thesis_id, e)

            # 2b. Slow feeds — treasury / gdelt / fred / eia / econ-calendar,
            # each on its own TTL, patched from cache on the ticks in between.
            # MUST run before the provider_values sweep below so their values
            # ride into fetch_runs and survive a restart, and before
            # _apply_overrides so a manual override still wins.
            #
            # WHY wrapped despite refresh() promising never to raise: the
            # dormant feeds are the least-exercised code in the cycle, and
            # the cycle holds the per-thesis lock. A treasury outage must not
            # be able to stop the desk pricing oil.
            try:
                await self._slow_feeds.refresh(thesis_id, effective)
            except Exception as e:  # noqa: BLE001
                log.warning("slow_feeds failed for %s: %s", thesis_id, e)

            # Collect provider values for restart recovery
            for node in effective.get("nodes", []):
                if "current" in node:
                    provider_values[node["id"]] = node["current"]
                if "probability" in node:
                    provider_values[node["id"] + "_prob"] = node["probability"]

        except Exception as e:
            self._repo.complete_fetch_run(run_id, status="failed")
            log.warning("Fetch failed for %s: %s", thesis_id, e)
            raise

        # 3. Query active overrides and apply precedence
        overrides = self._repo.list_active_overrides(thesis_id)
        self._apply_overrides(effective, overrides)

        # 3b. Patch closesObserved from the SQLite streak count. The engine
        # no longer mutates this field; the table is canonical. Patch happens
        # AFTER override application so a manual closesObserved override still
        # wins if an operator sets one.
        self._patch_closes_observed(thesis_id, effective)

        # 4. Propagate
        states = thesisgraph.propagate(effective)
        confluence = thesisgraph.score_confluence(effective, states)
        phase_num, phase_key = thesisgraph.get_current_phase(effective)

        # 5. Evaluate scenarios
        scenarios_result = []
        for scenario in effective.get("scenarios", []):
            scenario_overrides, impacts = thesisgraph.eval_scenario(
                effective, scenario, states
            )
            scenarios_result.append((scenario, scenario_overrides, impacts))

        # 6. Export snapshot
        export = thesisgraph.export_state(
            effective, states, confluence, phase_num, phase_key,
            scenarios_result, today=date.today(),
        )

        # 7. Bump revision and add v2 fields
        new_rev = self._revisions.get(thesis_id, 0) + 1
        self._revisions[thesis_id] = new_rev
        export["thesisId"] = thesis_id
        export["revision"] = new_rev
        export["definitionHash"] = self._definition_hashes.get(thesis_id)
        export["generatedAt"] = datetime.now(timezone.utc).isoformat()

        # 8. Compute diff for events (before commit)
        old_snap = self._latest_snapshots.get(thesis_id)
        events = self._compute_events(thesis_id, new_rev, old_snap, export)

        # 9. Commit: snapshot + events
        #
        # WHY no outbox enqueue here any more: the SQLite `outbox` table was
        # the intended Dialectic delivery queue and no drainer was ever
        # written, so every row ever enqueued sat 'pending' forever (58,769 of
        # them). Delivery is now inline — see step 11b — and the FILE outbox
        # at snapshots/outbox/ is the failure spool, because that one has a
        # replay path and an operator UI.
        snap_json = json.dumps(export, separators=(",", ":"))

        self._repo.save_snapshot(
            thesis_id, new_rev, snap_json,
            definition_hash=self._definition_hashes.get(thesis_id),
        )

        if events:
            self._repo.insert_alert_events(events)

        # Complete fetch run
        self._repo.complete_fetch_run(
            run_id, status="success", revision=new_rev,
            provider_values=provider_values,
        )

        # 10. Update in-memory cache
        self._latest_snapshots[thesis_id] = export

        # 10b. Mirror the revision into the module-level cache so other
        # modules (web/routes/llm.py, web/routes/v1/agent.py) can read it
        # via the get_latest_revision() helper without importing this class.
        _latest_revisions[thesis_id] = new_rev

        elapsed = time.monotonic() - t0
        log.info(
            "Cycle complete: %s rev=%d nodes=%d events=%d %.1fs",
            thesis_id, new_rev, len(states), len(events), elapsed,
        )

        # 11. Broadcast WS deltas (after commit — never before)
        if self._ws and events:
            try:
                await self._ws.broadcast_to_book_rooms(
                    thesis_id, "state_update",
                    {"snapshot": export, "events": events},
                    user="system",
                )
            except Exception:
                log.warning("WS broadcast failed for %s", thesis_id)

        # 12. Publish price.tick diff on the live bus (Unit 6).
        # WHY: state_update above is heavyweight (full snapshot + events) and
        # only fires when a node state changes. A pure price move doesn't
        # mutate state but still needs to push to the ticker. price.tick is
        # the diff-only channel for that — target <500ms fetch-to-pixel.
        try:
            await self._publish_price_tick(thesis_id, new_rev, old_snap, export)
        except Exception:  # pragma: no cover — bus must never break the cycle
            log.warning("live_bus publish failed for %s", thesis_id)

        # 13. Push to the linked Dialectic room (LAST — an external service
        # must never delay local WS clients).
        await self._maybe_push_dialectic(thesis_id, cfg, export, events)

        return export

    # ════════════════════════════════════════════════════════════════
    # DIALECTIC PUSH
    # ════════════════════════════════════════════════════════════════

    # WHY 3600s: a Dialectic room that has heard nothing for hours cannot
    # tell "nothing changed" from "the desk is dead" — its own freshness
    # watchdog keys off last_trading_push_at. An hourly heartbeat makes
    # silence mean something.
    DIALECTIC_HEARTBEAT_SECONDS = 3600.0

    def _should_push_dialectic(self, thesis_id: str, events: List[dict]) -> bool:
        """Push when this tick produced events, or when the heartbeat is due."""
        if events:
            return True
        last = self._last_dialectic_push.get(thesis_id)
        if last is None:
            return True
        return (time.monotonic() - last) >= self.DIALECTIC_HEARTBEAT_SECONDS

    async def _maybe_push_dialectic(
        self, thesis_id: str, cfg: dict, export: dict, events: List[dict],
    ) -> None:
        """Deliver the snapshot to the book's Dialectic room, if it has one.

        WHY fully wrapped: this is the only outbound network call in the
        cycle. push_snapshot() is written not to raise, and this is the
        second belt — a Dialectic outage, a bad room token, or an import
        error in the push module must not be able to fail a fetch cycle.
        """
        meta = cfg.get("meta", {}) or {}
        room_id = meta.get("dialecticRoomId")
        room_token = resolve_room_token(meta)
        if not room_id or not room_token:
            return
        if not self._should_push_dialectic(thesis_id, events):
            return

        try:
            from web.runtime.dialectic_push import push_snapshot
            ok = await push_snapshot(
                thesis_id=thesis_id,
                snapshot=export,
                alert_events=events,
                room_id=room_id,
                room_token=room_token,
                reason="events" if events else "heartbeat",
            )
        except Exception:  # noqa: BLE001 — cycle survives any push fault
            log.warning("dialectic push raised for %s", thesis_id, exc_info=True)
            return

        if ok:
            # Only a delivered push resets the heartbeat clock. A spooled
            # failure must leave it due, so the next tick tries again.
            self._last_dialectic_push[thesis_id] = time.monotonic()

    # ════════════════════════════════════════════════════════════════
    # INTERNALS — mutation dispatch
    # ════════════════════════════════════════════════════════════════

    async def _execute(self, thesis_id: str, op: str, payload: dict) -> Any:
        """Dispatch a submitted mutation to the appropriate handler."""
        if op == "fetch_prices":
            return await self._run_cycle(thesis_id)
        elif op == "get_state":
            # WHY: Read from committed snapshot, no re-evaluation needed
            snap = self._latest_snapshots.get(thesis_id)
            if snap is None:
                # First request before any tick — run a cycle now
                return await self._run_cycle(thesis_id)
            return snap
        elif op == "tv_webhook":
            return await self._run_tv_webhook(thesis_id, payload)
        else:
            raise ValueError(f"Unknown op: {op}")

    async def _run_tv_webhook(self, thesis_id: str, payload: dict) -> Any:
        """Apply a TradingView webhook mutation under the thesis lock.

        WHY this lives in the coordinator: the per-thesis asyncio.Lock is the
        single serialization point for all mutations. The TV adapter used to
        hold its own _book_locks dict — this unified path removes that and
        guarantees no webhook can interleave with a scheduler tick, an
        override application, or another webhook for the same thesis.

        Delegates the mechanical work (load_book, find_binding, apply_op,
        persist, propagate) to stdlib helpers in web.adapters.tradingview
        to keep that module focused on the engine contract.
        """
        from web.adapters import tradingview as tv_adapter
        binding_id = payload.get("binding_id")
        alert_value = payload.get("alert_value")
        if not binding_id:
            raise ValueError("tv_webhook payload requires binding_id")

        # Run the synchronous mechanical work in a thread so we don't block
        # the event loop on file I/O.
        return await asyncio.to_thread(
            tv_adapter.apply_webhook_sync,
            thesis_id, binding_id, alert_value, self._repo,
        )

    # ════════════════════════════════════════════════════════════════
    # INTERNALS — close-observation ingest + streak patch
    # ════════════════════════════════════════════════════════════════

    def _persist_close_events(self, thesis_id: str, effective: dict) -> None:
        """Translate engine close events to table INSERTs.

        WHY this mapper lives here (not in the engine): the engine is stdlib
        only and must never import web.persistence. It emits a transient
        `_close_events` list on the effective cfg; we drain it and write to
        SQLite via the Repository. INSERT OR IGNORE on the PK
        (thesis_id, node_id, market_date, threshold_key) gives us free dedup
        across overlapping runs.
        """
        events = effective.pop("_close_events", None) or []
        if not events:
            return
        for evt in events:
            try:
                self._repo.insert_close_observation(
                    thesis_id=thesis_id,
                    node_id=evt["node_id"],
                    market_date=evt["market_date"],
                    threshold_key=evt["threshold_key"],
                    close_value=float(evt["close_value"]),
                    qualifies=bool(evt["qualifies"]),
                    source="derived",
                )
            except (KeyError, ValueError, TypeError) as e:
                log.warning(
                    "close_event insert failed for %s/%s: %s",
                    thesis_id, evt.get("node_id"), e,
                )

    def _patch_closes_observed(self, thesis_id: str, effective: dict) -> None:
        """Replace node.closesObserved with the streak count from the table.

        WHY: The engine's closesRequired gate reads `node.closesObserved`.
        With the engine no longer mutating that field, the coordinator is
        responsible for sourcing the value from SQLite before propagate().
        We iterate each node's thresholds highest-first (matching the engine's
        own iteration in eval_node_state) and patch the streak for the first
        qualifying threshold.
        """
        for node in effective.get("nodes", []):
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
            # Highest threshold where current >= level wins — matches
            # eval_node_state's `sorted_th = sorted(..., reverse=True)` walk.
            for th in sorted(thresholds_with_closes,
                             key=lambda t: t["level"], reverse=True):
                if current >= th["level"]:
                    streak = self._repo.get_close_streak(
                        thesis_id=thesis_id,
                        node_id=node["id"],
                        threshold_key=str(th["level"]),
                    )
                    node["closesObserved"] = int(streak)
                    break
            else:
                node["closesObserved"] = 0

    # ════════════════════════════════════════════════════════════════
    # INTERNALS — override application
    # ════════════════════════════════════════════════════════════════

    @staticmethod
    def _apply_overrides(cfg: dict, overrides: List[dict]) -> None:
        """Apply active overrides to the effective config.

        WHY: Precedence is manual override > fresh provider > prior provider > config default.
        Overrides are already filtered to active-only by the caller. We patch them
        onto the deep-copied config after provider values, so overrides win.
        """
        if not overrides:
            return

        node_map = {n["id"]: n for n in cfg.get("nodes", [])}
        for ov in overrides:
            target_type = ov.get("target_type", "node")
            target_id = ov.get("target_id", "")
            field = ov.get("field", "")
            value = ov.get("value")

            if target_type == "node" and target_id in node_map:
                node_map[target_id][field] = value
            elif target_type == "marketField":
                for mf in cfg.get("marketFields", []):
                    if mf.get("key") == target_id:
                        mf[field] = value

    # ════════════════════════════════════════════════════════════════
    # INTERNALS — event generation
    # ════════════════════════════════════════════════════════════════

    async def _publish_price_tick(
        self,
        thesis_id: str,
        revision: int,
        old_snap: Optional[dict],
        new_snap: dict,
    ) -> None:
        """Diff marketSnapshot between revisions and publish a price.tick frame.

        WHY a diff-only payload: the full snapshot is already persisted and
        WS-broadcast on state changes. price.tick is the cheap continuous
        channel that lets MarketTicker update cells without refetching.

        Publishes nothing if:
        - old_snap is None (first tick — the bootstrap channel already carries
          the initial marketSnapshot)
        - no symbol changed (prevent redundant frames on a quiet tick)
        """
        new_market = new_snap.get("marketSnapshot") or {}
        if old_snap is None or not new_market:
            return

        old_market = old_snap.get("marketSnapshot") or {}
        freshness = new_snap.get("feedFreshness") or {}

        changes: Dict[str, Dict[str, Any]] = {}
        for symbol, curr in new_market.items():
            prev = old_market.get(symbol)
            if prev == curr:
                continue
            # WHY: source/fetchedAt aren't per-symbol in the current schema —
            # feedFreshness is keyed by provider (yahoo/polymarket/...). We
            # can't know which provider a symbol came from without a lookup
            # table, so we attach the full freshness map. The frontend picks
            # the provider based on the symbol's own source metadata from
            # the last /api/market/watchlist call.
            entry: Dict[str, Any] = {"prev": prev, "curr": curr}
            changes[symbol] = entry

        # Also surface newly-absent symbols (present before, missing now)
        # as curr=None so the UI can blank the cell.
        for symbol, prev in old_market.items():
            if symbol in new_market:
                continue
            changes[symbol] = {"prev": prev, "curr": None}

        if not changes:
            return

        payload: Dict[str, Any] = {
            "type": "price.tick",
            "thesis_id": thesis_id,
            "revision": revision,
            "changes": changes,
        }
        if freshness:
            payload["freshness"] = freshness

        bus = get_live_bus()
        await bus.publish(thesis_id, payload)

    def _compute_events(
        self,
        thesis_id: str,
        revision: int,
        old_snap: Optional[dict],
        new_snap: dict,
    ) -> List[dict]:
        """Generate durable events from snapshot diff.

        WHY: Only emit events for meaningful changes — node state transitions,
        phase changes, countdown threshold crossings. Do NOT emit events for
        every price tick that does not alter state.
        """
        import uuid
        from web.schemas.events import (
            EventType, make_dedupe_key, severity_for_state_change, default_severity,
        )

        events: List[dict] = []
        now = datetime.now(timezone.utc).isoformat()

        if old_snap is None:
            # First snapshot — emit snapshot.recomputed only
            events.append({
                "event_id": str(uuid.uuid4()),
                "thesis_id": thesis_id,
                "revision": revision,
                "event_type": EventType.snapshot_recomputed.value,
                "severity": default_severity(EventType.snapshot_recomputed).value,
                "occurred_at": now,
                "dedupe_key": make_dedupe_key(
                    thesis_id, EventType.snapshot_recomputed, None, revision
                ),
            })
            return events

        # Node state changes
        old_states = old_snap.get("nodeStates", {})
        new_states = new_snap.get("nodeStates", {})
        for node_id in set(old_states) | set(new_states):
            old_s = old_states.get(node_id, "unknown")
            new_s = new_states.get(node_id, "unknown")
            if old_s != new_s:
                events.append({
                    "event_id": str(uuid.uuid4()),
                    "thesis_id": thesis_id,
                    "revision": revision,
                    "event_type": EventType.node_state_changed.value,
                    "severity": severity_for_state_change(old_s, new_s).value,
                    "node_id": node_id,
                    "old_value": old_s,
                    "new_value": new_s,
                    "occurred_at": now,
                    "dedupe_key": make_dedupe_key(
                        thesis_id, EventType.node_state_changed, node_id, revision
                    ),
                })

        # Phase change
        old_phase = old_snap.get("cascadePhase", {}).get("number", 0)
        new_phase = new_snap.get("cascadePhase", {}).get("number", 0)
        if old_phase != new_phase:
            events.append({
                "event_id": str(uuid.uuid4()),
                "thesis_id": thesis_id,
                "revision": revision,
                "event_type": EventType.phase_changed.value,
                "severity": default_severity(EventType.phase_changed).value,
                "old_value": old_phase,
                "new_value": new_phase,
                "occurred_at": now,
                "dedupe_key": make_dedupe_key(
                    thesis_id, EventType.phase_changed, None, revision
                ),
            })

        return events
