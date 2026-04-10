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

    async def connect(self, websocket: WebSocket, room_id: str, username: str) -> None:
        """Register connection in room. Caller must have already accepted the WebSocket."""
        async with self._lock:
            if room_id not in self._rooms:
                self._rooms[room_id] = set()
            self._rooms[room_id].add((websocket, username))
            self._user_activity[username] = {"room": room_id, "viewing": ""}
        log.info("WS connected: %s in room %s", username, room_id)
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
        log.info("WS disconnected: %s from room %s", username, room_id)
        try:
            await self.broadcast(room_id, "presence", await self.get_presence(room_id), user="system")
        except Exception as e:
            log.warning("Post-disconnect presence broadcast failed: %s", e)

    async def broadcast(self, room_id: str, msg_type: str, payload: dict,
                        user: str = "system", exclude: Optional[WebSocket] = None) -> None:
        """Send a typed message to all connections in a room."""
        message = {
            "type": msg_type,
            "payload": payload,
            "ts": datetime.now(timezone.utc).isoformat(),
            "user": user,
        }
        text = json.dumps(message)
        async with self._lock:
            connections = list(self._rooms.get(room_id, set()))
        targets = [(ws, uname) for ws, uname in connections if ws is not exclude]
        if not targets:
            return

        # WHY: Fan out sends concurrently so a slow client doesn't block delivery
        # to others. 5-second timeout per send prevents indefinite stalls.
        async def _send(ws: WebSocket, uname: str) -> Optional[tuple]:
            try:
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

    async def send_to(self, websocket: WebSocket, msg_type: str, payload: dict,
                      user: str = "system") -> None:
        """Send a typed message to a single connection."""
        message = {
            "type": msg_type,
            "payload": payload,
            "ts": datetime.now(timezone.utc).isoformat(),
            "user": user,
        }
        try:
            await websocket.send_text(json.dumps(message))
        except Exception:
            log.warning("Failed to send to individual WS")

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
