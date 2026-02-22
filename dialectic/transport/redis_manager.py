# transport/redis_manager.py — Redis pub/sub connection manager for horizontal scaling

import asyncio
import json
import logging
from typing import Optional
from uuid import UUID

from .websocket import ConnectionManager, Connection, OutboundMessage

logger = logging.getLogger(__name__)

# Reconnect delay bounds (exponential backoff)
_RECONNECT_MIN_DELAY = 1.0
_RECONNECT_MAX_DELAY = 30.0


class RedisConnectionManager(ConnectionManager):
    """
    ARCHITECTURE: Drop-in replacement for ConnectionManager using Redis pub/sub.
    WHY: In-memory registry breaks with multiple uvicorn workers or server instances.
    TRADEOFF: Redis dependency + slight latency vs horizontal scalability.
    """

    def __init__(self, redis_url: str = "redis://localhost:6379"):
        super().__init__()  # Keep local connection tracking
        self.redis_url = redis_url
        self._redis = None
        self._pubsub = None
        self._listener_task: Optional[asyncio.Task] = None
        self._subscribed_rooms: set[UUID] = set()

    async def initialize(self):
        """Connect to Redis and start listener."""
        import redis.asyncio as aioredis

        self._redis = aioredis.from_url(self.redis_url, decode_responses=True)
        await self._redis.ping()
        self._pubsub = self._redis.pubsub()
        self._listener_task = asyncio.create_task(self._listen())

    async def shutdown(self):
        """Clean shutdown of Redis connections."""
        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
        if self._pubsub:
            await self._pubsub.unsubscribe()
            await self._pubsub.aclose()
        if self._redis:
            await self._redis.aclose()

    async def connect(
        self,
        websocket,
        user_id: UUID,
        room_id: UUID,
        thread_id: Optional[UUID] = None,
    ) -> Connection:
        """Subscribe to room's Redis channel, then connect."""
        # Subscribe before connect so the "user_joined" broadcast (sent by
        # the parent's connect()) is received by all instances including this one.
        await self._subscribe_to_room(room_id)
        conn = await super().connect(websocket, user_id, room_id, thread_id)
        return conn

    async def disconnect(self, conn: Connection) -> None:
        """Disconnect + unsubscribe if no more local connections in room."""
        room_id = conn.room_id
        await super().disconnect(conn)
        # Check if any local connections remain for this room
        if not self._rooms.get(room_id):
            await self._unsubscribe_from_room(room_id)

    async def broadcast(
        self,
        room_id: UUID,
        message: OutboundMessage,
        exclude_user: Optional[UUID] = None,
    ) -> None:
        """Publish to Redis channel instead of iterating local connections."""
        payload = json.dumps({
            "room_id": str(room_id),
            "message": message.to_dict(),
            "exclude_user": str(exclude_user) if exclude_user else None,
        })
        await self._redis.publish(f"room:{room_id}", payload)

    async def send_to_user(
        self,
        user_id: UUID,
        room_id: UUID,
        message: OutboundMessage,
    ) -> bool:
        """
        Publish a targeted message via Redis.

        ARCHITECTURE: Targeted messages go through Redis too for cross-instance delivery.
        WHY: The target user may be connected to a different server instance.
        TRADEOFF: Slight overhead for same-instance sends, but correct for multi-instance.
        """
        payload = json.dumps({
            "room_id": str(room_id),
            "message": message.to_dict(),
            "target_user_id": str(user_id),
        })
        await self._redis.publish(f"room:{room_id}", payload)
        return True

    async def _subscribe_to_room(self, room_id: UUID):
        """Subscribe to a room's Redis channel."""
        if room_id not in self._subscribed_rooms:
            await self._pubsub.subscribe(f"room:{room_id}")
            self._subscribed_rooms.add(room_id)

    async def _unsubscribe_from_room(self, room_id: UUID):
        """Unsubscribe from a room's Redis channel."""
        if room_id in self._subscribed_rooms:
            await self._pubsub.unsubscribe(f"room:{room_id}")
            self._subscribed_rooms.discard(room_id)

    async def _listen(self):
        """
        Background listener that delivers Redis messages to local connections.

        ARCHITECTURE: Exponential backoff reconnection on Redis failure.
        WHY: Redis restarts should not permanently kill the pub/sub listener.
        TRADEOFF: Messages can be lost during reconnection window.
        """
        reconnect_delay = _RECONNECT_MIN_DELAY

        while True:
            try:
                async for raw_message in self._pubsub.listen():
                    if raw_message["type"] != "message":
                        continue

                    # Reset backoff on successful message processing
                    reconnect_delay = _RECONNECT_MIN_DELAY

                    try:
                        data = json.loads(raw_message["data"])
                        room_id = UUID(data["room_id"])

                        target_user_id = (
                            UUID(data["target_user_id"])
                            if data.get("target_user_id")
                            else None
                        )
                        exclude_user = (
                            UUID(data["exclude_user"])
                            if data.get("exclude_user")
                            else None
                        )

                        msg = OutboundMessage(
                            type=data["message"]["type"],
                            payload=data["message"]["payload"],
                        )

                        if target_user_id:
                            # Targeted message — deliver to specific local user
                            await super().send_to_user(room_id=room_id, user_id=target_user_id, message=msg)
                        else:
                            # Broadcast — deliver to all local connections in room
                            await super().broadcast(room_id, msg, exclude_user=exclude_user)

                    except (KeyError, ValueError, json.JSONDecodeError) as e:
                        logger.warning(f"Malformed Redis message, skipping: {e}")

            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.error(
                    f"Redis listener error: {e}. Reconnecting in {reconnect_delay:.1f}s..."
                )
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, _RECONNECT_MAX_DELAY)

                # Re-subscribe to all rooms after reconnection
                try:
                    for room_id in list(self._subscribed_rooms):
                        await self._pubsub.subscribe(f"room:{room_id}")
                    logger.info("Redis listener reconnected and re-subscribed")
                except Exception as resub_err:
                    logger.error(f"Redis re-subscribe failed: {resub_err}")
