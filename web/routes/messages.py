"""Message routes + WebSocket endpoint for real-time chat."""

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect

from web.auth import get_current_user, decode_token
from web.deps import get_repo
from web.models import User, MessageCreate, PinRequest
from web.persistence.repository import Repository
from web.ws import manager

log = logging.getLogger(__name__)

router = APIRouter(tags=["messages"])


@router.get("/api/rooms/{room_id}/messages")
async def list_messages(
    room_id: str,
    limit: int = Query(default=50, le=200),
    before: Optional[str] = Query(default=None),
    _user: User = Depends(get_current_user),
    repo: Repository = Depends(get_repo),
) -> list:
    if await asyncio.to_thread(repo.get_room, room_id) is None:
        raise HTTPException(status_code=404, detail="Room not found")
    return await asyncio.to_thread(repo.list_messages, room_id, limit, before)


@router.post("/api/rooms/{room_id}/messages")
async def create_message(
    room_id: str,
    req: MessageCreate,
    user: User = Depends(get_current_user),
    repo: Repository = Depends(get_repo),
) -> dict:
    if await asyncio.to_thread(repo.get_room, room_id) is None:
        raise HTTPException(status_code=404, detail="Room not found")
    msg = await asyncio.to_thread(
        repo.save_message,
        room_id=room_id,
        user=user.username,
        content=req.content,
        msg_type=req.msg_type,
        model=req.model,
    )
    await manager.broadcast(room_id, "message", msg, user=user.username)
    return msg


@router.get("/api/rooms/{room_id}/pins")
async def list_pins(room_id: str, _user: User = Depends(get_current_user),
                    repo: Repository = Depends(get_repo)) -> list:
    return await asyncio.to_thread(repo.list_pins, room_id)


@router.post("/api/rooms/{room_id}/pins")
async def add_pin(room_id: str, req: PinRequest, _user: User = Depends(get_current_user),
                  repo: Repository = Depends(get_repo)) -> list:
    """Pin a message by passing its typed message object."""
    return await asyncio.to_thread(repo.add_pin, room_id, req.model_dump())


@router.delete("/api/rooms/{room_id}/pins/{message_id}")
async def remove_pin(room_id: str, message_id: str, _user: User = Depends(get_current_user),
                     repo: Repository = Depends(get_repo)) -> list:
    return await asyncio.to_thread(repo.remove_pin, room_id, message_id)


@router.get("/api/rooms/{room_id}/export")
async def export_chat(room_id: str, _user: User = Depends(get_current_user),
                      repo: Repository = Depends(get_repo)) -> dict:
    """Export room chat as markdown."""
    return {"markdown": await asyncio.to_thread(repo.export_room_markdown, room_id)}


@router.websocket("/ws/{room_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str) -> None:
    """WebSocket connection for real-time room messages.

    WHY: Client sends token as first message after connect for auth.
    Subsequent messages are typed JSON: {"type": "message"|"typing", ...}
    """
    await websocket.accept()
    username = ""
    # WHY: Access repo from app state — Depends() doesn't work on WS endpoints.
    repo: Repository = websocket.app.state.repo

    try:
        # WHY: Accept token via query param (?token=...) or as first WS message.
        token_param = websocket.query_params.get("token")
        if token_param:
            try:
                payload = decode_token(token_param)
                username = payload["sub"]
            except Exception:
                await websocket.send_text('{"type":"error","payload":{"detail":"Invalid token"}}')
                await websocket.close(code=4001)
                return
        else:
            auth_msg = await websocket.receive_text()
            try:
                payload = decode_token(auth_msg)
                username = payload["sub"]
            except Exception:
                await websocket.send_text('{"type":"error","payload":{"detail":"Invalid token"}}')
                await websocket.close(code=4001)
                return

        # WHY: Validate room exists before registering.
        if await asyncio.to_thread(repo.get_room, room_id) is None:
            await websocket.send_text('{"type":"error","payload":{"detail":"Room not found"}}')
            await websocket.close(code=4004)
            return

        await manager.connect(websocket, room_id, username)
        log.info("WS authenticated: %s in room %s", username, room_id)
        await manager.send_to(websocket, "system", {"detail": f"Connected as {username}"}, user="system")

        while True:
            data = await websocket.receive_text()
            try:
                parsed = json.loads(data)
            except (json.JSONDecodeError, AttributeError):
                parsed = {"type": "message", "content": data}

            msg_type = parsed.get("type", "message")

            if msg_type == "typing":
                await manager.broadcast(
                    room_id, "typing",
                    {"username": username, "typing": parsed.get("typing", True)},
                    user=username, exclude=websocket,
                )
            elif msg_type == "viewing":
                viewing = parsed.get("viewing", "")
                manager.set_user_viewing(username, viewing)
                await manager.broadcast(
                    room_id, "presence", await manager.get_presence(room_id), user="system",
                )
            else:
                content = parsed.get("content", data)
                msg = await asyncio.to_thread(
                    repo.save_message, room_id=room_id, user=username, content=content
                )
                await manager.broadcast(room_id, "message", msg, user=username)

    except WebSocketDisconnect:
        log.info("WS disconnected: %s from room %s", username, room_id)
    except Exception as e:
        log.warning("WS error in room %s: %s", room_id, e)
    finally:
        if username:
            await manager.disconnect(websocket, room_id, username)
