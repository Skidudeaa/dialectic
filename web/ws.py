"""
WebSocket connection manager for real-time room messaging.

WHY: Chat and LLM streaming need push delivery. REST polling would add
latency and waste bandwidth. WebSocket connections are keyed by room + user
so broadcasts target only participants in the active room.

Protocol: every message is JSON with shape:
  {"type": str, "payload": dict, "ts": ISO8601, "user": str}

Types: "message", "llm_chunk", "llm_done", "system", "state_update",
       "presence", "typing", "error"
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from fastapi import WebSocket

from web.runtime.live_bus import get_live_bus

log = logging.getLogger(__name__)


# ── Agent presence state (Unit 9) ──────────────────────────────────────
# WHY: A tiny module-level dict that web/routes/llm.py writes to on tool-call
# start/end. broadcast_presence() reads it to synthesize the agent pill.
# Unit 11 will replace this with the richer agent-in-room state.
_AGENT_STATE: Dict[str, Any] = {
    "status": "idle",        # "thinking" | "idle"
    "last_activity": None,   # ISO 8601 timestamp of most recent tool-call
    "book_id": None,         # which book the agent is reasoning about
}
# WHY: Agent pill drops out of the roster after this idle window so it
# doesn't linger forever after the LLM finishes.
_AGENT_ACTIVE_WINDOW_S = 30.0


def mark_agent_thinking(book_id: Optional[str] = None) -> None:
    """LLM hook: agent has started a tool call. Triggers presence broadcast.

    WHY: Two-line surgical hook for web/routes/llm.py. The route wraps each
    tool call in mark_agent_thinking() / mark_agent_idle() and the presence
    pill picks it up automatically via the next broadcast.
    """
    _AGENT_STATE["status"] = "thinking"
    _AGENT_STATE["last_activity"] = datetime.now(timezone.utc).isoformat()
    if book_id is not None:
        _AGENT_STATE["book_id"] = book_id
    # WHY: Schedule a broadcast on the running loop. The route may be sync
    # or async — we don't await here so the hook stays trivially callable.
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(manager.broadcast_presence())
    except RuntimeError:
        # No running loop — caller is synchronous. Skip broadcast; the next
        # connect/disconnect/update will pick up the new state.
        pass


def mark_agent_idle() -> None:
    """LLM hook: agent has finished its tool call. Triggers presence broadcast."""
    _AGENT_STATE["status"] = "idle"
    _AGENT_STATE["last_activity"] = datetime.now(timezone.utc).isoformat()
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(manager.broadcast_presence())
    except RuntimeError:
        pass


def _agent_is_active() -> bool:
    """True if the LLM has emitted activity within the active window."""
    last = _AGENT_STATE.get("last_activity")
    if not last:
        return False
    try:
        ts = datetime.fromisoformat(last.replace("Z", "+00:00"))
    except Exception:
        return False
    delta = (datetime.now(timezone.utc) - ts).total_seconds()
    return delta <= _AGENT_ACTIVE_WINDOW_S


def _reset_agent_state_for_tests() -> None:
    """Test helper — clears the global agent state so tests are isolated."""
    _AGENT_STATE["status"] = "idle"
    _AGENT_STATE["last_activity"] = None
    _AGENT_STATE["book_id"] = None


class ConnectionManager:
    """Manages WebSocket connections per room with presence tracking."""

    def __init__(self) -> None:
        # WHY: room_id -> set of (websocket, username) tuples.
        self._rooms: Dict[str, Set[tuple]] = {}
        # WHY: Track what each user is currently viewing for activity status.
        self._user_activity: Dict[str, dict] = {}  # username -> {"room": str, "viewing": str}
        self._lock = asyncio.Lock()
        # WHY: Repository reference for broadcast_to_book_rooms. Set during
        # lifespan init. Avoids circular import of web.state.
        self._repo = None
        # WHY: Coordinator reference for bootstrap data. Set during lifespan init.
        self._coordinator = None
        # WHY: v2 protocol — monotonic seq counter per connection for gap detection.
        # Client sees seq=47 then seq=49, knows it missed one, re-subscribes.
        self._seq_counters: Dict[int, int] = {}  # id(websocket) -> seq
        # Unit 6: per-connection live-bus forwarder — subscribes to the
        # room's linked_book_id channel and forwards price.tick frames.
        # Key is id(websocket); value is {"task": asyncio.Task, "token": int}.
        self._bus_forwarders: Dict[int, Dict[str, Any]] = {}
        # Unit 9: per-WS presence map — what each socket is doing right now.
        # Key is id(websocket); value is {"user_id", "book_id", "last_activity", "ws"}.
        # WHY keyed by id(ws): a single user can have multiple sockets
        # (multiple tabs); each gets a row, but we dedupe in the broadcast
        # payload by (user_id, book_id) so the pill row stays clean.
        self._presence: Dict[int, Dict[str, Any]] = {}
        # WHY: Cache the last broadcast payload so we can debounce duplicates
        # — flapping connect/disconnect or a client posting the same
        # presence.update twice produces a single broadcast.
        self._last_presence_payload: Optional[Dict[str, Any]] = None

    def set_repo(self, repo) -> None:
        """Inject Repository reference. Called from lifespan init."""
        self._repo = repo

    def set_coordinator(self, coordinator) -> None:
        """Inject RuntimeCoordinator reference. Called from lifespan init."""
        self._coordinator = coordinator

    async def connect(self, websocket: WebSocket, room_id: str, username: str) -> None:
        """Register connection in room. Caller must have already accepted the WebSocket."""
        async with self._lock:
            if room_id not in self._rooms:
                self._rooms[room_id] = set()
            self._rooms[room_id].add((websocket, username))
            self._user_activity[username] = {"room": room_id, "viewing": ""}
            self._seq_counters[id(websocket)] = 0
            # Unit 9: register for global presence. book_id starts None and
            # is set by the client posting a presence.update C2S frame.
            self._presence[id(websocket)] = {
                "user_id": username,
                "book_id": None,
                "last_activity": datetime.now(timezone.utc).isoformat(),
                "ws": websocket,
            }
        log.info("WS connected: %s in room %s", username, room_id)
        # WHY: Send bootstrap with thesis state on connect so the client can
        # render immediately without additional REST calls. On reconnect, the
        # same bootstrap replaces stale state.
        await self._send_bootstrap(websocket, room_id)
        # Unit 6: start live-bus forwarder for the room's linked thesis.
        await self._start_bus_forwarder(websocket, room_id)
        await self.broadcast(room_id, "presence", await self.get_presence(room_id), user="system")
        # Unit 9: always send the current roster directly to the newly
        # connected socket so it renders pills immediately — the broader
        # fan-out below may dedupe if the roster shape is unchanged.
        async with self._lock:
            payload = self._build_global_presence_payload()
        await self.send_to(websocket, "presence.changed", payload, user="system")
        # Unit 9: global cross-room presence broadcast (fan-out to others).
        await self.broadcast_presence()

    async def disconnect(self, websocket: WebSocket, room_id: str, username: str) -> None:
        """Remove connection from room registry."""
        async with self._lock:
            room = self._rooms.get(room_id)
            if room:
                room.discard((websocket, username))
                if not room:
                    del self._rooms[room_id]
            if username in self._user_activity:
                del self._user_activity[username]
            self._seq_counters.pop(id(websocket), None)
            # Unit 9: drop from global presence roster.
            self._presence.pop(id(websocket), None)
        # Unit 6: tear down the live-bus forwarder for this connection.
        await self._stop_bus_forwarder(websocket)
        log.info("WS disconnected: %s from room %s", username, room_id)
        try:
            await self.broadcast(room_id, "presence", await self.get_presence(room_id), user="system")
        except Exception as e:
            log.warning("Post-disconnect presence broadcast failed: %s", e)
        # Unit 9: global broadcast so all rooms see the user drop out.
        try:
            await self.broadcast_presence()
        except Exception as e:
            log.warning("Post-disconnect global presence broadcast failed: %s", e)

    async def broadcast(self, room_id: str, msg_type: str, payload: dict,
                        user: str = "system", exclude: Optional[WebSocket] = None,
                        thesis_id: Optional[str] = None,
                        revision: Optional[int] = None) -> None:
        """Send a typed message to all connections in a room.

        WHY v2 envelope: messages include v, thesisId, revision, seq fields.
        The v1 fields (type, payload, ts, user) are preserved so the existing
        frontend continues to work — the extra fields are additive.
        """
        message = {
            "v": 1,
            "type": msg_type,
            "payload": payload,
            "ts": datetime.now(timezone.utc).isoformat(),
            "user": user,
        }
        if thesis_id is not None:
            message["thesisId"] = thesis_id
        if revision is not None:
            message["revision"] = revision
        async with self._lock:
            connections = list(self._rooms.get(room_id, set()))
        targets = [(ws, uname) for ws, uname in connections if ws is not exclude]
        if not targets:
            return

        # WHY: Fan out sends concurrently so a slow client doesn't block delivery
        # to others. 5-second timeout per send prevents indefinite stalls.
        async def _send(ws: WebSocket, uname: str) -> Optional[tuple]:
            try:
                # WHY: Per-connection seq for gap detection on reconnect
                ws_id = id(ws)
                seq = self._seq_counters.get(ws_id, 0) + 1
                self._seq_counters[ws_id] = seq
                msg_with_seq = {**message, "seq": seq}
                text = json.dumps(msg_with_seq)
                await asyncio.wait_for(ws.send_text(text), timeout=5.0)
                return None
            except Exception:
                return (ws, uname)

        results = await asyncio.gather(*[_send(ws, u) for ws, u in targets])
        dead = [r for r in results if r is not None]
        if dead:
            async with self._lock:
                room = self._rooms.get(room_id)
                if room:
                    for entry in dead:
                        room.discard(entry)

    async def broadcast_all(self, msg_type: str, payload: dict, user: str = "system") -> None:
        """Broadcast to all rooms — used for global events like prediction updates."""
        for room_id in list(self._rooms.keys()):
            await self.broadcast(room_id, msg_type, payload, user=user)

    async def broadcast_to_book_rooms(self, book_id: str, msg_type: str,
                                      payload: dict, user: str = "system") -> int:
        """Fan out a message to every connected room whose linked_book_id matches.

        WHY scoped to linked rooms: TradingView alerts are book-specific
        (e.g. a brent alert only affects iran-hormuz watchers). Broadcasting
        to unrelated rooms would add noise. Falls back to zero broadcasts
        when no rooms match — caller can choose to send a global broadcast
        separately if that's the desired UX.

        Returns the number of rooms actually broadcast to (useful for the
        route's ack payload + audit log).
        """
        # WHY: repo passed by caller — no lazy import of web.state needed.
        if not hasattr(self, '_repo') or self._repo is None:
            log.warning("broadcast_to_book_rooms: no repo available")
            return 0
        try:
            rooms = self._repo.list_rooms()
        except Exception:  # pragma: no cover — DB failure shouldn't block the webhook
            log.warning("broadcast_to_book_rooms: failed to list rooms")
            return 0

        target_room_ids = [
            r["id"] for r in rooms
            if r.get("linked_book_id") == book_id
        ]
        sent = 0
        for rid in target_room_ids:
            # Only broadcast to rooms that have at least one live WS
            async with self._lock:
                has_connections = rid in self._rooms and bool(self._rooms[rid])
            if has_connections:
                await self.broadcast(rid, msg_type, payload, user=user)
                sent += 1
        return sent

    async def send_to(self, websocket: WebSocket, msg_type: str, payload: dict,
                      user: str = "system") -> None:
        """Send a typed message to a single connection."""
        ws_id = id(websocket)
        seq = self._seq_counters.get(ws_id, 0) + 1
        self._seq_counters[ws_id] = seq
        message = {
            "v": 1,
            "type": msg_type,
            "payload": payload,
            "ts": datetime.now(timezone.utc).isoformat(),
            "user": user,
            "seq": seq,
        }
        try:
            await websocket.send_text(json.dumps(message))
        except Exception:
            log.warning("Failed to send to individual WS")

    # ────────────────────────────────────────────────────────────────
    # LIVE BUS FORWARDER (Unit 6 — push-driven MarketTicker)
    # ────────────────────────────────────────────────────────────────

    async def _start_bus_forwarder(self, websocket: WebSocket, room_id: str) -> None:
        """Subscribe to the room's linked-book price.tick channel and forward.

        WHY: MarketTicker needs diff-only price updates within 500ms of
        fetch. The coordinator publishes to LiveBus on every commit; each
        connection owns a background task that pulls its room's thesis
        channel and ships frames over the WS. We gate on linked_book_id —
        a room with no linked book (e.g. a pure chat room) gets no
        forwarder.
        """
        if self._repo is None:
            return
        try:
            room = self._repo.get_room(room_id)
        except Exception:  # pragma: no cover — treat as no forwarder
            return
        linked_book = (room or {}).get("linked_book_id")
        if not linked_book:
            return

        bus = get_live_bus()
        token, stream = await bus.subscribe(linked_book)

        async def _forward() -> None:
            try:
                async for frame in stream:
                    # WHY: Reuse send_to's envelope (v, type, ts, user, seq)
                    # so the client sees price.tick with the same metadata
                    # it already parses on every other S2C message.
                    try:
                        await self.send_to(
                            websocket, "price.tick", frame, user="system",
                        )
                    except Exception:
                        # send_to swallows send errors already, but we
                        # defensively loop here so a single bad send never
                        # kills the forwarder for the rest of the session.
                        log.debug("price.tick forward failed", exc_info=True)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.warning("bus forwarder crashed for room=%s", room_id,
                            exc_info=True)

        task = asyncio.create_task(_forward())
        self._bus_forwarders[id(websocket)] = {"task": task, "token": token}

    async def _stop_bus_forwarder(self, websocket: WebSocket) -> None:
        """Tear down the bus forwarder for a disconnecting WebSocket.

        Idempotent — safe to call more than once. The LiveBus.unsubscribe
        sentinel terminates the async iterator, which ends the forward
        task naturally; we also cancel as a belt-and-suspenders measure.
        """
        entry = self._bus_forwarders.pop(id(websocket), None)
        if entry is None:
            return
        try:
            await get_live_bus().unsubscribe(entry["token"])
        except Exception:  # pragma: no cover
            log.debug("unsubscribe failed during forwarder teardown",
                      exc_info=True)
        task: asyncio.Task = entry["task"]
        if not task.done():
            task.cancel()
            try:
                await asyncio.wait_for(task, timeout=1.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            except Exception:  # pragma: no cover
                log.debug("forwarder task raised on cancel", exc_info=True)

    async def _send_bootstrap(self, websocket: WebSocket, room_id: str) -> None:
        """Send bootstrap message with thesis state on connect.

        WHY: Full state on connect means the client renders immediately without
        additional REST calls. On reconnect, the same bootstrap replaces stale
        state — no delta replay needed.
        """
        bootstrap_payload: Dict[str, Any] = {
            "thesisCatalog": [],
        }

        # Build thesis catalog and find linked thesis snapshot
        if self._coordinator:
            for tid in self._coordinator.get_thesis_ids():
                defn = self._coordinator.definitions.get(tid, {})
                meta = defn.get("meta", {})
                bootstrap_payload["thesisCatalog"].append({
                    "thesisId": tid,
                    "title": meta.get("title", tid),
                    "definitionHash": self._coordinator.definition_hashes.get(tid),
                    "nodeCount": len(defn.get("nodes", [])),
                    "edgeCount": len(defn.get("edges", [])),
                })

            # Find linked book for this room
            if self._repo:
                room = self._repo.get_room(room_id)
                linked_book = room.get("linked_book_id") if room else None
                if linked_book:
                    snap = self._coordinator.get_latest_snapshot(linked_book)
                    if snap:
                        bootstrap_payload["snapshot"] = snap
                        bootstrap_payload["thesisId"] = linked_book
                        bootstrap_payload["revision"] = snap.get("revision")

                    # Active overrides for linked thesis
                    overrides = self._repo.list_active_overrides(linked_book)
                    bootstrap_payload["activeOverrides"] = overrides

                    # Recent alerts for linked thesis
                    alerts = self._repo.list_alert_events(thesis_id=linked_book, limit=20)
                    bootstrap_payload["recentAlerts"] = alerts

        await self.send_to(websocket, "bootstrap", bootstrap_payload, user="system")

    def set_user_viewing(self, username: str, viewing: str) -> None:
        """Update what thesis/page a user is viewing (for activity status)."""
        if username in self._user_activity:
            self._user_activity[username]["viewing"] = viewing

    # ────────────────────────────────────────────────────────────────
    # GLOBAL PRESENCE (Unit 9 — presence pills in the dashboard header)
    # ────────────────────────────────────────────────────────────────

    async def update_presence(
        self, websocket: WebSocket, book_id: Optional[str]
    ) -> None:
        """Mark the connection as viewing book_id and broadcast.

        WHY: Called from the WS handler on every C2S 'presence.update' frame.
        The broadcast is debounced — if nothing actually changed (same user,
        same book) and the roster as a whole is unchanged, broadcast_presence
        is a no-op and skips the fan-out.
        """
        async with self._lock:
            entry = self._presence.get(id(websocket))
            if entry is not None:
                entry["book_id"] = book_id
                entry["last_activity"] = datetime.now(timezone.utc).isoformat()
        await self.broadcast_presence()

    async def bump_activity(self, websocket: WebSocket) -> None:
        """Refresh the last_activity timestamp on any C2S frame.

        WHY: Idle detection in the UI. A pill goes dim after 60s of no
        traffic. We DO NOT broadcast on every keystroke — the ts changes
        but content equality skips the fan-out.
        """
        async with self._lock:
            entry = self._presence.get(id(websocket))
            if entry is not None:
                entry["last_activity"] = datetime.now(timezone.utc).isoformat()

    def _build_global_presence_payload(self) -> Dict[str, Any]:
        """Construct the {users, generated_at} envelope payload.

        WHY: Dedupe by (user_id, book_id) so multiple tabs don't spam the
        pill row. Append a synthetic agent row when the LLM is recently
        active. Caller already holds (or doesn't need) the lock — the read
        is atomic enough for an O(N=2-4) connection set.
        """
        seen: Dict[tuple, Dict[str, Any]] = {}
        for entry in self._presence.values():
            key = (entry["user_id"], entry.get("book_id"))
            existing = seen.get(key)
            # Keep the most recent last_activity for a duplicate (multi-tab) user
            if existing is None or entry["last_activity"] > existing["last_activity"]:
                seen[key] = {
                    "user_id": entry["user_id"],
                    "book_id": entry.get("book_id"),
                    "last_activity": entry["last_activity"],
                    "kind": "human",
                }
        users = list(seen.values())
        # Stable order — frontend pill row shouldn't reshuffle on every broadcast.
        users.sort(key=lambda u: (u["user_id"], u.get("book_id") or ""))

        # Append agent pill if the LLM has been active in the last window.
        if _agent_is_active():
            users.append({
                "user_id": "agent",
                "book_id": _AGENT_STATE.get("book_id"),
                "last_activity": _AGENT_STATE.get("last_activity"),
                "kind": "agent",
                "status": _AGENT_STATE.get("status", "idle"),
            })
        return {
            "users": users,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    async def broadcast_presence(self) -> int:
        """Fan out a presence.changed envelope to every connected client.

        WHY cross-room: presence is GLOBAL — a user in chat-room-A wants to
        see that the other analyst joined chat-room-B and is staring at a
        different book. Returns count of sockets the broadcast reached.

        Debounce: if the (sorted, agent-included) roster is byte-identical
        to the last broadcast, skip the fan-out. The generated_at timestamp
        is excluded from the equality check so it doesn't defeat the dedupe.
        """
        async with self._lock:
            payload = self._build_global_presence_payload()
            # Compare excluding volatile per-row timestamps so a bump of
            # last_activity (which changes on every C2S frame) doesn't
            # defeat the dedupe. The meaningful shape is (user_id, book_id,
            # kind, status) + membership.
            def _sig(users: list) -> str:
                compact = [
                    {
                        "user_id": u.get("user_id"),
                        "book_id": u.get("book_id"),
                        "kind": u.get("kind"),
                        "status": u.get("status"),
                    }
                    for u in users
                ]
                return json.dumps(compact, sort_keys=True)

            payload_signature = _sig(payload["users"])
            last = self._last_presence_payload
            last_signature = _sig(last["users"]) if last else None
            if payload_signature == last_signature:
                return 0
            self._last_presence_payload = payload
            # Snapshot the live ws list under the lock.
            sockets: List[WebSocket] = []
            for room_conns in self._rooms.values():
                for ws, _ in room_conns:
                    sockets.append(ws)

        if not sockets:
            return 0

        message = {
            "v": 1,
            "type": "presence.changed",
            "payload": payload,
            "ts": payload["generated_at"],
            "user": "system",
        }

        async def _send(ws: WebSocket) -> Optional[WebSocket]:
            try:
                ws_id = id(ws)
                seq = self._seq_counters.get(ws_id, 0) + 1
                self._seq_counters[ws_id] = seq
                msg_with_seq = {**message, "seq": seq}
                await asyncio.wait_for(
                    ws.send_text(json.dumps(msg_with_seq)), timeout=5.0
                )
                return None
            except Exception:
                return ws

        results = await asyncio.gather(*[_send(ws) for ws in sockets])
        return sum(1 for r in results if r is None)

    def _build_presence(self, room_id: str) -> dict:
        """Build presence payload for a room."""
        users: list[dict] = []
        for _, uname in self._rooms.get(room_id, set()):
            activity = self._user_activity.get(uname, {})
            users.append({
                "username": uname,
                "viewing": activity.get("viewing", ""),
            })
        return {"room_id": room_id, "users": users}

    async def get_presence(self, room_id: str) -> dict:
        """Build and return presence payload under lock — safe for external callers."""
        async with self._lock:
            return self._build_presence(room_id)

    def get_room_users(self, room_id: str) -> List[str]:
        """List usernames connected to a room."""
        return list(set(u for _, u in self._rooms.get(room_id, set())))

    @property
    def total_connections(self) -> int:
        return sum(len(conns) for conns in self._rooms.values())

    @property
    def active_rooms(self) -> List[str]:
        return [rid for rid, conns in self._rooms.items() if conns]

    @property
    def online_users(self) -> List[str]:
        return list(self._user_activity.keys())


# WHY: Singleton — FastAPI lifespan creates one instance, routes share it.
manager = ConnectionManager()
