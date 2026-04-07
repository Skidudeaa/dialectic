"""Message routes + WebSocket endpoint for real-time chat."""

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect

from web.auth import get_current_user, decode_token
from web.models import User, MessageCreate
from web import state
from web.ws import manager

log = logging.getLogger(__name__)

router = APIRouter(tags=["messages"])


@router.get("/api/rooms/{room_id}/messages")
async def list_messages(
    room_id: str,
    limit: int = Query(default=50, le=200),
    before: Optional[str] = Query(default=None),
    _user: User = Depends(get_current_user),
) -> list:
    if state.get_room(room_id) is None:
        raise HTTPException(status_code=404, detail="Room not found")
    return state.list_messages(room_id, limit=limit, before=before)


@router.post("/api/rooms/{room_id}/messages")
async def create_message(
    room_id: str,
    req: MessageCreate,
    user: User = Depends(get_current_user),
) -> dict:
    if state.get_room(room_id) is None:
        raise HTTPException(status_code=404, detail="Room not found")
    msg = state.save_message(
        room_id=room_id,
        user=user.username,
        content=req.content,
        msg_type=req.msg_type,
        model=req.model,
    )
    await manager.broadcast(room_id, "message", msg, user=user.username)
    return msg


@router.websocket("/ws/{room_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str) -> None:
    """WebSocket connection for real-time room messages.

    WHY: Client sends token as first message after connect for auth.
    Subsequent messages are typed JSON: {"type": "message"|"typing", ...}
    """
    await websocket.accept()
    username = ""

    try:
        # First message must be auth token
        auth_msg = await websocket.receive_text()
        try:
            payload = decode_token(auth_msg)
            username = payload["sub"]
        except Exception:
            await websocket.send_text('{"type":"error","payload":{"detail":"Invalid token"}}')
            await websocket.close(code=4001)
            return

        # Register in manager with presence tracking
        async with manager._lock:
            if room_id not in manager._rooms:
                manager._rooms[room_id] = set()
            manager._rooms[room_id].add((websocket, username))
            manager._user_activity[username] = {"room": room_id, "viewing": ""}
        log.info("WS authenticated: %s in room %s", username, room_id)

        # Send welcome + initial presence
        await manager.send_to(websocket, "system", {"detail": f"Connected as {username}"}, user="system")
        await manager.broadcast(room_id, "presence", manager._build_presence(room_id), user="system")

        # Message loop
        while True:
            data = await websocket.receive_text()
            try:
                parsed = json.loads(data)
            except (json.JSONDecodeError, AttributeError):
                parsed = {"type": "message", "content": data}

            msg_type = parsed.get("type", "message")

            if msg_type == "typing":
                # WHY: Broadcast typing indicator to other users in the room.
                await manager.broadcast(
                    room_id, "typing",
                    {"username": username, "typing": parsed.get("typing", True)},
                    user=username, exclude=websocket,
                )
            elif msg_type == "viewing":
                # WHY: User is viewing a specific thesis — update activity status.
                viewing = parsed.get("viewing", "")
                manager.set_user_viewing(username, viewing)
                await manager.broadcast(
                    room_id, "presence", manager._build_presence(room_id), user="system",
                )
            else:
                content = parsed.get("content", data)
                msg = state.save_message(room_id=room_id, user=username, content=content)
                await manager.broadcast(room_id, "message", msg, user=username)

    except WebSocketDisconnect:
        log.info("WS disconnected: %s from room %s", username, room_id)
    except Exception as e:
        log.warning("WS error in room %s: %s", room_id, e)
    finally:
        async with manager._lock:
            room = manager._rooms.get(room_id)
            if room:
                room.discard((websocket, username))
                if not room:
                    del manager._rooms[room_id]
            if username in manager._user_activity:
                del manager._user_activity[username]
        # Broadcast updated presence after disconnect
        try:
            await manager.broadcast(room_id, "presence", manager._build_presence(room_id), user="system")
        except Exception:
            pass
