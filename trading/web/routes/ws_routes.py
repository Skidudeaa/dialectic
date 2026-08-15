"""The machine WebSocket lane — the one survivor of the C4 chat cull.

WHY this file exists: the chat tier (routes/messages.py — chat CRUD, pins,
export, slash commands) died in the 2026-08 C4 cull, but /ws/{room_id} is
NOT chat plumbing: the coordinator, thesis, predictions and tradingview all
broadcast through web/ws.py's manager to book-linked rooms, and agents
consume that stream. The endpoint moved here verbatim so the machine lane
survives the deletion of the human chat that once shared it. Inbound chat
frames still persist as messages — the protocol is unchanged; only the
human UI over it is gone.
"""

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from web.auth import decode_token
from web.persistence.repository import Repository
from web.ws import manager

log = logging.getLogger(__name__)

router = APIRouter(tags=["ws"])


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

            # Unit 9: any C2S frame bumps last_activity for idle detection.
            # Fire-and-forget — never blocks a real chat message.
            try:
                await manager.bump_activity(websocket)
            except Exception:
                pass

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
            elif msg_type == "presence.update":
                # Unit 9: client tells us which book it's now viewing.
                payload = parsed.get("payload") or {}
                book_id = payload.get("book_id")
                # Validate — accept None or a non-empty string. Anything else
                # silently coerced to None to avoid storing junk in the roster.
                if book_id is not None and not isinstance(book_id, str):
                    book_id = None
                await manager.update_presence(websocket, book_id)
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
