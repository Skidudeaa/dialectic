"""
WebSocket connection manager for real-time room messaging.

WHY: Chat and LLM streaming need push delivery. REST polling would add
latency and waste bandwidth. WebSocket connections are keyed by room + user
so broadcasts target only participants in the active room.

Protocol: every message is JSON with shape:
  {"type": str, "payload": dict, "ts": ISO8601, "user": str}

Types: "message", "llm_chunk", "llm_done", "system", "state_update", "error"
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set

from fastapi import WebSocket

log = logging.getLogger(__name__)


class ConnectionManager:
    """Manages WebSocket connections per room."""

    def __init__(self) -> None:
        # WHY: room_id → set of (websocket, username) tuples. Set membership
        # makes disconnect O(1) without scanning all rooms.
        self._rooms: Dict[str, Set[tuple]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, room_id: str, username: str) -> None:
        """Accept connection and register in room."""
        await websocket.accept()
        async with self._lock:
            if room_id not in self._rooms:
                self._rooms[room_id] = set()
            self._rooms[room_id].add((websocket, username))
        log.info("WS connected: %s in room %s", username, room_id)

    async def disconnect(self, websocket: WebSocket, room_id: str, username: str) -> None:
        """Remove connection from room registry."""
        async with self._lock:
            room = self._rooms.get(room_id)
            if room:
                room.discard((websocket, username))
                if not room:
                    del self._rooms[room_id]
        log.info("WS disconnected: %s from room %s", username, room_id)

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
        dead: List[tuple] = []
        for ws, uname in connections:
            if ws is exclude:
                continue
            try:
                await ws.send_text(text)
            except Exception:
                dead.append((ws, uname))
        # Clean up dead connections
        if dead:
            async with self._lock:
                room = self._rooms.get(room_id)
                if room:
                    for entry in dead:
                        room.discard(entry)

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

    @property
    def total_connections(self) -> int:
        """Total active WebSocket connections across all rooms."""
        return sum(len(conns) for conns in self._rooms.values())

    @property
    def active_rooms(self) -> List[str]:
        """Room IDs with at least one connection."""
        return [rid for rid, conns in self._rooms.items() if conns]


# WHY: Singleton — FastAPI lifespan creates one instance, routes share it.
manager = ConnectionManager()
