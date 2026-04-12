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
from typing import Dict, List, Optional, Set

from fastapi import WebSocket

log = logging.getLogger(__name__)


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
        log.info("WS connected: %s in room %s", username, room_id)
        # WHY: Send bootstrap with thesis state on connect so the client can
        # render immediately without additional REST calls. On reconnect, the
        # same bootstrap replaces stale state.
        await self._send_bootstrap(websocket, room_id)
        await self.broadcast(room_id, "presence", await self.get_presence(room_id), user="system")

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
        log.info("WS disconnected: %s from room %s", username, room_id)
        try:
            await self.broadcast(room_id, "presence", await self.get_presence(room_id), user="system")
        except Exception as e:
            log.warning("Post-disconnect presence broadcast failed: %s", e)

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
