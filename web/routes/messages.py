"""Message routes + WebSocket endpoint for real-time chat."""

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
    # Broadcast to WebSocket connections in this room
    await manager.broadcast(room_id, "message", msg, user=user.username)
    return msg


@router.websocket("/ws/{room_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str) -> None:
    """WebSocket connection for real-time room messages.

    WHY: Client sends token as first message after connect for auth.
    Subsequent messages are broadcast to the room.
    """
    # Accept first, then authenticate via first message
    await websocket.accept()

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

        # Re-register with manager (re-accept handled internally)
        # WHY: We already accepted above, so we register directly.
        if room_id not in manager._rooms:
            manager._rooms[room_id] = set()
        manager._rooms[room_id].add((websocket, username))
        log.info("WS authenticated: %s in room %s", username, room_id)

        await manager.send_to(websocket, "system", {"detail": f"Connected as {username}"}, user="system")

        # Message loop
        while True:
            data = await websocket.receive_text()
            # WHY: WebSocket messages from client are just text content.
            # The route handles persistence and broadcast.
            import json
            try:
                parsed = json.loads(data)
                content = parsed.get("content", data)
            except (json.JSONDecodeError, AttributeError):
                content = data

            msg = state.save_message(room_id=room_id, user=username, content=content)
            await manager.broadcast(room_id, "message", msg, user=username)

    except WebSocketDisconnect:
        log.info("WS disconnected: room %s", room_id)
    except Exception as e:
        log.warning("WS error in room %s: %s", room_id, e)
    finally:
        # Clean up
        if room_id in manager._rooms:
            manager._rooms[room_id] = {
                (ws, u) for ws, u in manager._rooms.get(room_id, set())
                if ws is not websocket
            }
